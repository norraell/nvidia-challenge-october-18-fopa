"""Read-only access to saved artifacts for the agent tools.

Every tool reads files that earlier stages wrote. No tool calls a model or the network.
Text is source data: the tools return it, they never act on instructions inside it.
"""
from __future__ import annotations

from collections import Counter
from functools import cached_property
import hashlib
import json
from pathlib import Path
import re
from typing import Any

from ..contracts import DriftReport, EntryRecord, MatchRecord, PageRecord
from ..textstats import find_quote, tokenize

DEFAULT_CHARS = 3000
MAX_CHARS = 8000
MAX_FIND = 20
TOP_TERMS = 12
ENTRY_ID_PATTERN = re.compile(r"^e\d{4}-\d{2}$")
PAGE_ID_PATTERN = re.compile(r"^[0-9]{1,20}$")


class EvidenceError(ValueError):
    """A tool request names evidence that the saved artifacts do not hold."""


def _read_jsonl(path: Path, model: type) -> list[Any]:
    if not path.exists():
        return []
    return [model.model_validate_json(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def _clip(text: str, offset: int, max_chars: int) -> dict[str, Any]:
    offset = max(0, min(offset, len(text)))
    max_chars = max(1, min(max_chars, MAX_CHARS))
    piece = text[offset: offset + max_chars]
    next_offset = offset + len(piece) if offset + len(piece) < len(text) else None
    return {"text": piece, "offset": offset, "returned_chars": len(piece), "total_chars": len(text), "next_offset": next_offset}


class EvidenceStore:
    """Loads extract, match, and compare outputs from one work directory, once."""

    def __init__(self, work_dir: Path):
        self.work_dir = Path(work_dir)

    # -- loaders ---------------------------------------------------------------------------------------
    @cached_property
    def entries(self) -> dict[str, EntryRecord]:
        rows = _read_jsonl(self.work_dir / "extract" / "entries.jsonl", EntryRecord)
        if not rows:
            raise EvidenceError(f"no entries at {self.work_dir / 'extract' / 'entries.jsonl'}; run extract first")
        return {row.entry_id: row for row in rows}

    @cached_property
    def pages(self) -> dict[str, PageRecord]:
        return {row.page_id: row for row in _read_jsonl(self.work_dir / "extract" / "pages.jsonl", PageRecord)}

    @cached_property
    def matches(self) -> dict[str, MatchRecord]:
        return {row.entry_id: row for row in _read_jsonl(self.work_dir / "match" / "matches.jsonl", MatchRecord)}

    @cached_property
    def article_index(self) -> dict[str, dict[str, Any]]:
        path = self.work_dir / "match" / "articles.jsonl"
        if not path.exists():
            return {}
        rows = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
        return {row["page_id"]: row for row in rows}

    @cached_property
    def drift(self) -> DriftReport | None:
        path = self.work_dir / "compare" / "drift.json"
        return DriftReport.model_validate_json(path.read_text(encoding="utf-8")) if path.exists() else None

    def article(self, page_id: str) -> dict[str, Any]:
        """Full cached article text, verified against the sha256 the match stage recorded."""
        if not PAGE_ID_PATTERN.fullmatch(page_id):
            raise EvidenceError("page_id must be a Wikipedia page id (digits only)")
        index = self.article_index.get(page_id)
        if index is None:
            raise EvidenceError(f"page {page_id} is not a matched article in the saved match run")
        path = self.work_dir / "match" / "cache" / "articles" / f"{page_id}.json"
        if not path.exists():
            raise EvidenceError(f"article {page_id} ({index['title']}) text is not cached; rerun match with MATCH_FETCH_ARTICLES=1")
        data = json.loads(path.read_text(encoding="utf-8"))
        digest = hashlib.sha256(data["text"].encode("utf-8")).hexdigest()
        if digest != index["text_sha256"] or data["revision_id"] != index["revision_id"]:
            raise EvidenceError(f"cached article {page_id} differs from the saved match index (sha256 or revision)")
        return data

    # -- helpers ---------------------------------------------------------------------------------------
    def entry(self, entry_id: str) -> EntryRecord:
        if not ENTRY_ID_PATTERN.fullmatch(entry_id or ""):
            raise EvidenceError("entry_id must look like e0013-01")
        entry = self.entries.get(entry_id)
        if entry is None:
            raise EvidenceError(f"entry {entry_id} is not in the saved extract run")
        return entry

    def _match_summary(self, entry_id: str, top: int = 3) -> dict[str, Any]:
        match = self.matches.get(entry_id)
        if match is None:
            return {"status": "not_run", "reason": "the match stage has no record for this entry"}
        ranked = sorted((c for c in match.candidates if c.rerank_rank is not None), key=lambda c: c.rerank_rank)[:top]
        return {
            "status": match.status, "reason": match.reason, "method_version": match.method_version,
            "rerank_margin": match.rerank_margin,
            "match": None if match.match is None else {
                "page_id": match.match.page_id, "revision_id": match.match.revision_id,
                "citation_id": f"{match.match.page_id}@{match.match.revision_id}",
                "title": match.match.title, "url": match.match.url},
            "top_candidates": [{"title": c.wiki.title, "page_id": c.wiki.page_id, "revision_id": c.wiki.revision_id,
                                "bm25_score": c.bm25_score, "embed_cosine": c.embed_cosine, "rerank_logit": c.rerank_logit}
                               for c in ranked],
            "note": "Relevance scores show shared subject matter. They do not establish factual agreement.",
        }

    def _entry_header(self, entry: EntryRecord) -> dict[str, Any]:
        page = self.pages.get(entry.blocks[0].page_id)
        return {
            "entry_id": entry.entry_id, "citation_id": entry.entry_id, "kind": entry.kind, "headword": entry.headword,
            "running_header": entry.quality.get("running_header"), "page_id": entry.blocks[0].page_id,
            "row_index": page.row_index if page else None, "scan_file": page.filename if page else None,
            "crop_path": entry.crop_path, "continues_from": entry.continues_from, "continues_to": entry.continues_to,
            "low_quality": bool(entry.quality.get("low_quality", False)),
        }

    # -- tools -----------------------------------------------------------------------------------------
    def find_entry(self, query: str, limit: int = 8) -> dict[str, Any]:
        words = [w for w in re.findall(r"[a-z0-9]+", (query or "").lower().replace("ſ", "s")) if len(w) > 1]
        if not words:
            raise EvidenceError("query needs at least one word")
        limit = max(1, min(int(limit), MAX_FIND))
        scored = []
        for entry in self.entries.values():
            head = " ".join(filter(None, [entry.headword or "", str(entry.quality.get("running_header") or "")])).lower()
            body = entry.text.lower().replace("ſ", "s")
            head_hits = sum(w in head for w in words)
            body_hits = sum(w in body for w in words)
            if body_hits < len(words) and head_hits == 0:
                continue
            match = self.matches.get(entry.entry_id)
            scored.append((-(head_hits * 10 + body_hits + (2 if match and match.status == "matched" else 0)
                             + (1 if entry.kind == "entry" else 0)), entry.entry_id, entry))
        scored.sort()
        results = []
        for _, _, entry in scored[:limit]:
            summary = self._match_summary(entry.entry_id, top=1)
            results.append({**self._entry_header(entry), "match_status": summary["status"],
                            "matched_title": summary["match"]["title"] if summary.get("match") else None,
                            "snippet": entry.text[:200]})
        return {"query": query, "count": len(results), "total_hits": len(scored), "entries": results,
                "note": "" if results else "no saved entry mentions every query word; try one headword or a shorter query"}

    def get_entry(self, entry_id: str, offset: int = 0, max_chars: int = DEFAULT_CHARS) -> dict[str, Any]:
        entry = self.entry(entry_id)
        return {**self._entry_header(entry), **_clip(entry.text, offset, max_chars),
                "source": "Britannica scan via Parse 3.5; text normalized (long s to s, hyphens joined)",
                "match": self._match_summary(entry.entry_id)}

    def get_article(self, page_id: str, offset: int = 0, max_chars: int = DEFAULT_CHARS) -> dict[str, Any]:
        data = self.article(str(page_id))
        return {"page_id": data["page_id"], "revision_id": data["revision_id"],
                "citation_id": f"{data['page_id']}@{data['revision_id']}", "title": data["title"], "url": data["url"],
                "license": data.get("license", {}).get("spdx"), "dataset_revision": data["provenance"]["dataset_revision"],
                **_clip(data["text"], offset, max_chars)}

    def compare(self, entry_id: str, max_chars: int = DEFAULT_CHARS) -> dict[str, Any]:
        entry = self.entry(entry_id)
        summary = self._match_summary(entry.entry_id)
        result: dict[str, Any] = {"entry": {**self._entry_header(entry), **_clip(entry.text, 0, max_chars)}, "match": summary}
        if summary["status"] != "matched" or summary["match"] is None:
            result["status"] = "no_match"
            result["note"] = ("No Wikipedia article passed the match rule for this entry, so there is no second source to compare. "
                              "Say that the evidence is missing. Do not compare against a candidate that was rejected.")
            return result
        try:
            article = self.article(summary["match"]["page_id"])
        except EvidenceError as exc:
            result["status"] = "article_missing"
            result["note"] = str(exc)
            return result
        article_text = article["text"][: max(len(entry.text) * 3, max_chars)]
        result["article"] = {"page_id": article["page_id"], "revision_id": article["revision_id"],
                             "citation_id": f"{article['page_id']}@{article['revision_id']}", "title": article["title"],
                             "url": article["url"], **_clip(article["text"], 0, max_chars)}
        result["terms"] = self._term_contrast(entry, article_text, article)
        result["status"] = "compared"
        result["note"] = ("Term rates are per 1,000 tokens after stop words are removed. A term that only one source uses shows "
                          "a vocabulary difference, not a factual disagreement. Quote the sentences before you claim a difference.")
        return result

    def _term_contrast(self, entry: EntryRecord, article_text: str, article: dict[str, Any]) -> dict[str, Any]:
        brit, wiki = Counter(tokenize(entry.text)), Counter(tokenize(article_text))
        b_total, w_total = max(1, sum(brit.values())), max(1, sum(wiki.values()))
        rate = lambda n, total: round(n * 1000 / total, 1)
        drift = {row.term: row for row in (self.drift.terms if self.drift else [])}

        def rows(primary: Counter, other: Counter, text: str, citation: str) -> list[dict[str, Any]]:
            picked = sorted(primary, key=lambda t: (-(primary[t] - other.get(t, 0)), t))[:TOP_TERMS]
            out = []
            for term in picked:
                if primary[term] <= other.get(term, 0):
                    break
                row = {"term": term, "brit_count": brit.get(term, 0), "wiki_count": wiki.get(term, 0),
                       "brit_per_1k": rate(brit.get(term, 0), b_total), "wiki_per_1k": rate(wiki.get(term, 0), w_total),
                       "quote": find_quote(text, term)[:300], "quote_source": citation}
                if term in drift:
                    row["corpus_log_ratio"] = drift[term].log_ratio
                out.append(row)
            return out

        shared = sorted((t for t in brit if t in wiki), key=lambda t: (-(brit[t] + wiki[t]), t))[:TOP_TERMS]
        wiki_citation = f"{article['page_id']}@{article['revision_id']}"
        return {
            "brit_tokens": b_total, "wiki_tokens": w_total, "article_chars_compared": len(article_text),
            "shared": [{"term": t, "brit_count": brit[t], "wiki_count": wiki[t]} for t in shared],
            "britannica_only_or_more": rows(brit, wiki, entry.text, entry.entry_id),
            "wikipedia_only_or_more": rows(wiki, brit, article_text, wiki_citation),
        }
