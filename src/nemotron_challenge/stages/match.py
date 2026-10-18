"""Match stage entry point. Wires queries, search, embed, rerank, decision, articles, and the report.

Options come from environment variables so the CLI signature `run(settings, work_dir)` stays fixed:
MATCH_ENTRIES, MATCH_OUT_DIR, MATCH_CACHE_DIR, MATCH_TAU, MATCH_DELTA, MATCH_LIMIT,
MATCH_FETCH_ARTICLES (0/1), MATCH_REFETCH_ARTICLES (0/1), MATCH_STORE (0/1), MATCH_PLATE_IMAGES (0/1),
MATCH_REDECIDE (0/1: re-apply thresholds to the stored scores in MATCH_OUT_DIR, no embed or rerank calls).

Relevance scores do not establish factual agreement. See docs/match-plan.md section 3, D5.
"""
from __future__ import annotations

import base64
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import time
from typing import Any

from ..clients import RetrievalClient, ServiceError, WikiClient
from ..config import ConfigurationError, Settings
from ..contracts import EntryRecord, MatchRecord
from ..match import articles as article_io
from ..match.candidates import SearchCache, call_with_retry, pool_candidates, search_cached
from ..match.decide import Thresholds, decide, redecide, skipped
from ..match.embed_stage import DOCUMENT_CHARS, embed_candidates, title_matches
from ..match.inputs import load_entries
from ..match.queries import build_queries, clean_text, cut, headword_variants, resolve_headword
from ..match.report import build_report, load_side_files, render_markdown
from ..match.rerank_stage import rerank_candidates
from ..match.store import VectorStore

ARTICLE_EMBED_CHARS = 8000
TOKEN_OVERFLOW = 422


@dataclass(frozen=True)
class MatchOptions:
    entries_path: Path | None = None
    out_dir: Path | None = None
    cache_dir: Path | None = None
    thresholds: Thresholds = Thresholds()
    limit: int | None = None
    fetch_articles: bool = True
    refetch_articles: bool = False
    use_store: bool = True
    plate_images: bool = False
    redecide: bool = False

    @classmethod
    def from_env(cls, environ: Mapping[str, str] = os.environ) -> MatchOptions:
        def flag(name: str, default: bool) -> bool:
            value = environ.get(name, "").strip().lower()
            return default if not value else value in {"1", "true", "yes"}
        path = lambda name: Path(environ[name]) if environ.get(name, "").strip() else None
        limit = environ.get("MATCH_LIMIT", "").strip()
        return cls(
            entries_path=path("MATCH_ENTRIES"), out_dir=path("MATCH_OUT_DIR"), cache_dir=path("MATCH_CACHE_DIR"),
            thresholds=Thresholds(tau=float(environ.get("MATCH_TAU", Thresholds.tau)),
                                  delta=float(environ.get("MATCH_DELTA", Thresholds.delta))),
            limit=int(limit) if limit else None,
            fetch_articles=flag("MATCH_FETCH_ARTICLES", True), refetch_articles=flag("MATCH_REFETCH_ARTICLES", False),
            use_store=flag("MATCH_STORE", True), plate_images=flag("MATCH_PLATE_IMAGES", False),
            redecide=flag("MATCH_REDECIDE", False),
        )


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _write_jsonl(path: Path, rows: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text("".join(r + "\n" for r in rows))
    tmp.replace(path)


def model_query_text(headword: str | None, text: str) -> str:
    """The embed and rerank query. A treatise page never repeats its own running head, so prepend it."""
    body = clean_text(text)
    if not headword:
        return body
    head = headword.strip().rstrip(".")
    return f"{head}. {body}" if body and not body.lower().startswith(head.lower()) else body or head


def image_data_url(path: Path) -> str | None:
    """Inline the scan for a plate document. Scans are 600 px wide, below the 2048 image token budget."""
    if not path.exists():
        return None
    mime = {".jpg": "jpeg", ".jpeg": "jpeg", ".png": "png"}.get(path.suffix.lower())
    if mime is None:
        return None
    return f"data:image/{mime};base64," + base64.b64encode(path.read_bytes()).decode("ascii")


class MatchRunner:
    """Processes entries in order. Clients are injected so tests can use fakes."""

    def __init__(self, wiki: Any, retrieval: Any, options: MatchOptions, out_dir: Path, cache_dir: Path, *,
                 store: VectorStore | None = None, sleep: Callable[[float], None] = time.sleep):
        self.wiki, self.retrieval, self.options, self.out_dir = wiki, retrieval, options, out_dir
        self.cache = SearchCache(cache_dir / "search")
        self.cache_dir, self.store, self.sleep = cache_dir, store, sleep
        self.stats: dict[str, int] = {"search_calls": 0, "search_cached": 0, "embed_calls": 0, "rerank_calls": 0}
        self.failures: list[dict[str, Any]] = []
        self.decisions: dict[str, MatchRecord] = {}
        self.logs: list[dict[str, Any]] = []

    # -- per entry -------------------------------------------------------------------------------------
    def process(self, entry: EntryRecord) -> MatchRecord:
        th = self.options.thresholds
        if entry.kind == "cross_reference":
            return self._finish(entry, skipped(entry.entry_id, "cross reference", th), {})
        if entry.kind == "continuation" and entry.continues_from in self.decisions:
            head = self.decisions[entry.continues_from]
            return self._finish(entry, skipped(entry.entry_id, f"continuation of {entry.continues_from}", th, head.match),
                                {"continues_from": entry.continues_from, "head_status": head.status})
        return self._finish(entry, *self._match(entry))

    def _finish(self, entry: EntryRecord, record: MatchRecord, log: dict[str, Any]) -> MatchRecord:
        MatchRecord.model_validate(record.model_dump())
        self.decisions[entry.entry_id] = record
        self.logs.append({"entry_id": entry.entry_id, "kind": entry.kind, "status": record.status, **log})
        return record

    def _search(self, entry: EntryRecord, log: dict[str, Any]) -> tuple[list, dict]:
        queries = build_queries(entry)
        results, query_log = [], []
        for q in queries:
            attempts: list[dict[str, Any]] = []
            result, cached = search_cached(self.wiki, self.cache, q["text"], sleep=self.sleep, attempts_log=attempts)
            self.stats["search_cached" if cached else "search_calls"] += 1
            results.append((q["kind"], result))
            query_log.append({**q, "from_cache": cached, "hits": len(result.hits), "attempts": attempts})
        candidates, sources = pool_candidates(results)
        headword = resolve_headword(entry)
        variants = headword_variants(headword) if headword else []
        log.update({"queries": query_log, "candidate_sources": sources, "headword": headword,
                    "title_matches": title_matches(candidates, variants)})
        return candidates, {"texts": [q["text"] for q in queries], "headword": headword, "variants": variants}

    def _match(self, entry: EntryRecord) -> tuple[MatchRecord, dict[str, Any]]:
        th, log = self.options.thresholds, {}
        candidates, meta = self._search(entry, log)
        if not candidates:
            return decide(entry.entry_id, meta["texts"], [], th), log
        attempts: list[dict[str, Any]] = []
        text = model_query_text(meta["headword"], entry.text)
        log["model_query_prefix"] = meta["headword"]
        try:
            candidates, vector, kept = self._embed_with_shrink(text, candidates, attempts, log["title_matches"])
            log["embed_query_chars"] = self.stats.get("embed_query_chars")
            candidates = self._rerank_with_shrink(text, candidates, kept, attempts)
            log["rerank_query_chars"] = self.stats.get("rerank_query_chars")
            if entry.kind == "plate" and self.options.plate_images:
                log["plate_image"] = self._plate_image_logits(entry, text, candidates, kept, attempts)
        except ServiceError as exc:
            if exc.status_code != TOKEN_OVERFLOW:
                raise
            self.failures.append({"at": _now(), "entry_id": entry.entry_id, "stage": "retrieval", "error": str(exc),
                                  "status_code": exc.status_code, "attempts": attempts})
            log["attempts"] = attempts
            record = MatchRecord(entry_id=entry.entry_id, status="rejected", reason=f"error: model call failed, {exc}",
                                 queries=meta["texts"], candidates=candidates, match=None, rerank_margin=None,
                                 method_version=th.method_version)
            return record, log
        log["attempts"] = attempts
        if self.store is not None:
            self.store.put_entry(entry.entry_id, vector, hashlib.sha256(text.encode()).hexdigest(), entry.blocks[0].page_id)
        return decide(entry.entry_id, meta["texts"], candidates, th), log

    def _embed_with_shrink(self, text: str, candidates: list, attempts: list, always_keep: list[str]) -> tuple[list, list[float], list[str]]:
        for chars in (1500, 750):
            try:
                return embed_candidates(self.retrieval, text, candidates, query_chars=chars, sleep=self.sleep,
                                        attempts_log=attempts, stats=self.stats, always_keep=always_keep)
            except ServiceError as exc:
                if exc.status_code != TOKEN_OVERFLOW or chars == 750:
                    raise
        raise AssertionError("unreachable")

    def _rerank_with_shrink(self, text: str, candidates: list, kept: list[str], attempts: list, image: str | None = None) -> list:
        for chars in (2000, 1000):
            try:
                return rerank_candidates(self.retrieval, text, candidates, kept, query_chars=chars, image_data_url=image,
                                         sleep=self.sleep, attempts_log=attempts, stats=self.stats)
            except ServiceError as exc:
                if exc.status_code != TOKEN_OVERFLOW or chars == 1000:
                    raise
        raise AssertionError("unreachable")

    def _plate_image_logits(self, entry: EntryRecord, text: str, candidates: list, kept: list[str], attempts: list) -> dict[str, Any]:
        """D6: rerank again with the scan image in each document. Record both logits, decide on text only."""
        image = image_data_url(Path(entry.crop_path))
        if image is None:
            return {"skipped": f"image missing: {entry.crop_path}"}
        with_image = self._rerank_with_shrink(text, candidates, kept, attempts, image=image)
        return {"image_path": entry.crop_path, "logits": [
            {"page_id": c.wiki.page_id, "title": c.wiki.title, "text_only": t.rerank_logit, "with_image": c.rerank_logit,
             "text_rank": t.rerank_rank, "image_rank": c.rerank_rank}
            for c, t in zip(with_image, candidates) if c.rerank_logit is not None]}

    # -- articles --------------------------------------------------------------------------------------
    def fetch_articles(self, records: list[MatchRecord]) -> list[dict[str, Any]]:
        wanted = {r.match.page_id: r.match for r in records if r.match is not None}
        fetched: list[dict[str, Any]] = []
        for page_id in sorted(wanted, key=int):
            article = None if self.options.refetch_articles else article_io.load_cached_article(self.cache_dir, page_id)
            try:
                if article is None:
                    attempts: list[dict[str, Any]] = []
                    article = article_io.fetch_article(self.wiki, page_id, sleep=self.sleep, attempts_log=attempts)
                    article_io.cache_article(self.cache_dir, article)
                    self.stats["article_fetches"] = self.stats.get("article_fetches", 0) + 1
                fetched.append(article)
                self._store_article(article)
            except ServiceError as exc:
                self.failures.append({"at": _now(), "page_id": page_id, "stage": "article", "error": str(exc),
                                      "status_code": exc.status_code})
        return fetched

    def _store_article(self, article: dict[str, Any]) -> None:
        if self.store is None or (self.store.has_article(article["page_id"]) and not self.options.refetch_articles):
            return
        text = cut(clean_text(article["text"]), ARTICLE_EMBED_CHARS) or article["title"]
        try:
            vector = call_with_retry(lambda: self.retrieval.embed([cut(text, DOCUMENT_CHARS)], "document"), sleep=self.sleep)[0]
        except ServiceError as exc:
            self.failures.append({"at": _now(), "page_id": article["page_id"], "stage": "article_embed", "error": str(exc)})
            return
        self.stats["embed_calls"] += 1
        self.store.put_article(article["page_id"], article["revision_id"], vector, article["provenance"]["text_sha256"], article["title"])


def content_only_rescues(records: list[MatchRecord], logs: list[dict[str, Any]]) -> int:
    sources = {l["entry_id"]: l.get("candidate_sources", {}) for l in logs}
    count = 0
    for r in records:
        if r.status == "matched" and r.match is not None:
            kinds = set(sources.get(r.entry_id, {}).get(r.match.page_id, {}).get("queries", {}))
            count += int(kinds == {"content"})
    return count


def run_pipeline(entries: list[EntryRecord], wiki: Any, retrieval: Any, options: MatchOptions, out_dir: Path,
                 cache_dir: Path, *, store: VectorStore | None = None,
                 sleep: Callable[[float], None] = time.sleep) -> dict[str, Any]:
    """Match every entry and write matches.jsonl, candidates.jsonl, articles.jsonl, report.json, REPORT.md."""
    started = time.time()
    runner = MatchRunner(wiki, retrieval, options, out_dir, cache_dir, store=store, sleep=sleep)
    out_dir.mkdir(parents=True, exist_ok=True)
    records: list[MatchRecord] = []
    try:
        for entry in entries[: options.limit]:
            records.append(runner.process(entry))
    except ServiceError as exc:
        failure = {"at": _now(), "stage": "pipeline", "error": str(exc), "status_code": exc.status_code,
                   "entries_done": len(records), "failures": runner.failures, "stats": runner.stats}
        (out_dir / "run-failed.json").write_text(json.dumps(failure, indent=2))
        raise ServiceError(f"match stopped after {len(records)} entries, no matches.jsonl written: {exc}",
                           status_code=exc.status_code) from exc
    _write_jsonl(out_dir / "matches.jsonl", [r.model_dump_json() for r in records])
    _write_jsonl(out_dir / "candidates.jsonl", [json.dumps(l, ensure_ascii=False) for l in runner.logs])
    fetched = runner.fetch_articles(records) if options.fetch_articles else []
    if options.fetch_articles:
        article_io.write_articles_index(out_dir / "articles.jsonl", fetched)
    matched_pages = [r.match.page_id for r in records if r.match is not None]
    summary = {
        "entries_seen": len(records), "status_counts": {s: sum(r.status == s for r in records) for s in
                                                        ("matched", "rejected", "no_candidates", "skipped")},
        "distinct_articles": len(set(matched_pages)), "repeated_articles": len(matched_pages) - len(set(matched_pages)),
        "candidates_per_entry_mean": round(sum(len(r.candidates) for r in records) / max(len(records), 1), 2),
        "calls": runner.stats, "failed_calls": runner.failures, "method_version": options.thresholds.method_version,
        "articles_fetched": len(fetched), "store_counts": store.counts() if store is not None else None,
        "elapsed_seconds": round(time.time() - started, 1),
        "outputs": {name: str(out_dir / name) for name in ("matches.jsonl", "candidates.jsonl", "report.json", "REPORT.md")
                    } | ({"articles.jsonl": str(out_dir / "articles.jsonl")} if options.fetch_articles else {}),
    }
    report = build_report(entries[: options.limit], records, failures=runner.failures,
                          query_only_rescues=content_only_rescues(records, runner.logs), summary=summary,
                          logs=runner.logs, side_files=load_side_files(out_dir))
    (out_dir / "report.json").write_text(json.dumps(report, indent=2, ensure_ascii=False))
    (out_dir / "REPORT.md").write_text(render_markdown(report))
    return summary


def load_records(path: Path) -> list[MatchRecord]:
    if not path.exists():
        raise FileNotFoundError(f"matches file is missing: {path}")
    return [MatchRecord.model_validate_json(l) for l in path.read_text().splitlines() if l.strip()]


def load_logs(path: Path) -> list[dict[str, Any]]:
    return [json.loads(l) for l in path.read_text().splitlines() if l.strip()] if path.exists() else []


def redecide_pipeline(entries: list[EntryRecord], wiki: Any, retrieval: Any, options: MatchOptions, out_dir: Path,
                      cache_dir: Path, *, store: VectorStore | None = None,
                      sleep: Callable[[float], None] = time.sleep) -> dict[str, Any]:
    """Re-apply thresholds to stored scores, then fetch articles for the new matches. No embed or rerank calls."""
    started = time.time()
    previous = load_records(out_dir / "matches.jsonl")
    logs = load_logs(out_dir / "candidates.jsonl")
    runner = MatchRunner(wiki, retrieval, options, out_dir, cache_dir, store=store, sleep=sleep)
    records: list[MatchRecord] = []
    for old in previous:
        new = redecide(old, options.thresholds)
        if new.status == "skipped" and new.reason.startswith("continuation of "):
            head = next((r for r in records if r.entry_id == new.reason.removeprefix("continuation of ")), None)
            new = new.model_copy(update={"match": head.match if head else None})
        records.append(new)
    runner.logs = logs
    _write_jsonl(out_dir / "matches.jsonl", [r.model_dump_json() for r in records])
    fetched = runner.fetch_articles(records) if options.fetch_articles else []
    if options.fetch_articles:
        article_io.write_articles_index(out_dir / "articles.jsonl", fetched)
    matched_pages = [r.match.page_id for r in records if r.match is not None]
    summary = {
        "mode": "redecide", "previous_method_version": previous[0].method_version if previous else None,
        "entries_seen": len(records), "status_counts": {s: sum(r.status == s for r in records) for s in
                                                        ("matched", "rejected", "no_candidates", "skipped")},
        "distinct_articles": len(set(matched_pages)), "repeated_articles": len(matched_pages) - len(set(matched_pages)),
        "candidates_per_entry_mean": round(sum(len(r.candidates) for r in records) / max(len(records), 1), 2),
        "calls": runner.stats, "failed_calls": runner.failures, "method_version": options.thresholds.method_version,
        "articles_fetched": len(fetched), "store_counts": store.counts() if store is not None else None,
        "elapsed_seconds": round(time.time() - started, 1),
        "outputs": {name: str(out_dir / name) for name in ("matches.jsonl", "candidates.jsonl", "report.json", "REPORT.md", "articles.jsonl")},
    }
    report = build_report(entries, records, failures=runner.failures,
                          query_only_rescues=content_only_rescues(records, logs), summary=summary,
                          logs=logs, side_files=load_side_files(out_dir))
    (out_dir / "report.json").write_text(json.dumps(report, indent=2, ensure_ascii=False))
    (out_dir / "REPORT.md").write_text(render_markdown(report))
    return summary


def run(settings: Settings, work_dir: Path) -> dict[str, Any]:
    options = MatchOptions.from_env()
    entries_path = options.entries_path or work_dir / "extract" / "entries.jsonl"
    out_dir = options.out_dir or work_dir / "match"
    cache_dir = options.cache_dir or work_dir / "match" / "cache"
    entries = load_entries(entries_path)
    if not settings.retrieval_base_url:
        raise ConfigurationError("set RETRIEVAL_BASE_URL in .env before you run match")
    with WikiClient(settings.wikipedia_api_url) as wiki, \
            RetrievalClient(settings.retrieval_base_url, settings.retrieval_api_key) as retrieval:
        retrieval.verify_models()
        store = VectorStore(settings.db_path) if options.use_store else None
        pipeline = redecide_pipeline if options.redecide else run_pipeline
        summary = pipeline(entries, wiki, retrieval, options, out_dir, cache_dir, store=store)
    summary["entries_path"] = str(entries_path)
    return summary
