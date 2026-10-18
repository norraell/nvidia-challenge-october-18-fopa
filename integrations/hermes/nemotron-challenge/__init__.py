"""Native Hermes tools for the Britannica vs Wikipedia comparison agent.

Each handler returns a JSON string and never raises to Hermes.
A failure returns {"error": "...", "evidence": "missing"}.
Handlers read saved artifacts from CHALLENGE_WORK_DIR (default: artifacts/).
"""
from __future__ import annotations

import functools
import json
import os
import re
import sys
from pathlib import Path
from typing import Any, Callable

try:  # Hermes imports the plugin as a package. Tests import it by file path.
    from . import schemas
except ImportError:
    import schemas  # type: ignore[no-redef]

ENTRY_ID = re.compile(r"^e[0-9]{4}-[0-9]{2}$")
PAGE_ID = re.compile(r"^[0-9]{1,20}$")
PREVIEW_CHARS = 300
COMPARE_CHARS = 1500
WIKI_PAGE_CHARS = 6000
MAX_QUERY_CHARS = 500
MAX_K = 10
DELTA_PATTERN = re.compile(r"delta=([0-9]+(?:\.[0-9]+)?)")


class ToolError(Exception):
    """A handled failure. The message goes to the model, so keep it free of secrets."""

    def __init__(self, message: str, **extra: Any):
        super().__init__(message)
        self.extra = extra


def _error(message: str, **extra: Any) -> str:
    return json.dumps({"error": message, "evidence": "missing", **extra}, ensure_ascii=False)


def _tool(func: Callable[[dict[str, Any]], dict[str, Any]]) -> Callable[..., str]:
    @functools.wraps(func)
    def wrapper(params: Any = None, **kwargs: Any) -> str:
        del kwargs
        try:
            result = func(params if isinstance(params, dict) else {})
            return json.dumps(result, ensure_ascii=False, allow_nan=False)
        except ToolError as exc:
            return _error(str(exc), **exc.extra)
        except Exception as exc:  # The handler must never raise to Hermes.
            return _error(f"{type(exc).__name__}: {str(exc)[:200]}")

    return wrapper


def _runtime() -> dict[str, Any]:
    """Per-run settings. The agent stage writes `challenge_run.json` into the profile before each run.

    The Hermes gateway keeps the environment of the first client that started it,
    so environment variables can be stale. The file wins; the environment is the fallback.
    """
    home = os.environ.get("HERMES_HOME")
    if home:
        try:
            data = json.loads((Path(home) / "challenge_run.json").read_text(encoding="utf-8"))
            return data if isinstance(data, dict) else {}
        except (OSError, ValueError):
            pass
    return {}


def _setting(key: str, env_name: str) -> str | None:
    return _runtime().get(key) or os.environ.get(env_name) or None


def _work_dir() -> Path:
    return Path(_setting("work_dir", "CHALLENGE_WORK_DIR") or "artifacts")


def _core() -> None:
    """Make `nemotron_challenge` importable inside the Hermes Python environment."""
    try:
        import nemotron_challenge  # noqa: F401
        return
    except ImportError:
        pass
    roots = [_setting("repo_root", "CHALLENGE_REPO_ROOT"), Path(__file__).resolve().parents[3], Path.cwd()]
    if os.environ.get("HERMES_HOME"):
        roots.append(Path(os.environ["HERMES_HOME"]).resolve().parents[1])
    for root in roots:
        if root and (Path(root) / "src" / "nemotron_challenge").is_dir():
            sys.path.insert(0, str(Path(root) / "src"))
            return
    raise ToolError("nemotron_challenge package is not importable; set CHALLENGE_REPO_ROOT")


def _read_jsonl(relative: str, model: Any) -> list[Any]:
    path = _work_dir() / relative
    if not path.is_file():
        raise ToolError(f"missing artifact: {relative}")
    return [model.model_validate_json(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def _entries() -> dict[str, Any]:
    _core()
    from nemotron_challenge.contracts import EntryRecord

    return {row.entry_id: row for row in _read_jsonl("extract/entries.jsonl", EntryRecord)}


def _matches() -> dict[str, Any]:
    _core()
    from nemotron_challenge.contracts import MatchRecord

    return {row.entry_id: row for row in _read_jsonl("match/matches.jsonl", MatchRecord)}


def _need_entry_id(params: dict[str, Any]) -> str:
    entry_id = params.get("entry_id")
    if not isinstance(entry_id, str) or not ENTRY_ID.fullmatch(entry_id):
        raise ToolError("entry_id must look like e0013-01")
    return entry_id


def _need_int(value: Any, low: int, high: int, name: str) -> int:
    if type(value) is not int or not low <= value <= high:
        raise ToolError(f"{name} must be an integer from {low} to {high}")
    return value


def _entry_page_id(entry: Any) -> str:
    return entry.blocks[0].page_id


def _source_info(entry: Any) -> dict[str, Any] | None:
    """Scan identity from the packaged manifest. The manifest has no edition field."""
    _core()
    from nemotron_challenge.data import load_manifest

    manifest = load_manifest()
    for page in manifest["pages"]:
        if page["page_id"] == _entry_page_id(entry):
            return {
                "dataset": manifest["dataset"], "dataset_revision": manifest["revision"],
                "volume_id": page["volume_id"], "filename": page["filename"],
                "image_sha256": page["image_sha256"], "edition": None,
            }
    return None



# ---------------------------------------------------------------- Wikipedia text

def _cached_article(page_id: str) -> dict[str, Any] | None:
    """Read a full article from artifacts/match/cache/articles/{page_id}.json when the match stage saved one.

    Expected keys: page_id, revision_id, title, url, text. Other keys are ignored.
    """
    path = _work_dir() / "match" / "cache" / "articles" / f"{page_id}.json"
    if not path.is_file():
        return None
    data = json.loads(path.read_text(encoding="utf-8"))
    needed = ("page_id", "revision_id", "url", "text")
    if not isinstance(data, dict) or any(not isinstance(data.get(key), str) for key in needed):
        raise ToolError(f"cached article {page_id} has an invalid shape")
    if data["page_id"] != page_id:
        raise ToolError(f"cached article {page_id} holds page {data['page_id']}")
    return data


def _live_article(page_id: str, offset: int, max_chars: int) -> dict[str, Any]:
    _core()
    from nemotron_challenge.clients import ServiceError, WikiClient
    from nemotron_challenge.config import ConfigurationError, Settings

    try:
        settings = Settings.from_env(env_file=None)
        with WikiClient(settings.wikipedia_api_url, timeout=30) as client:
            article = client.article(page_id, offset=offset, max_chars=max_chars)
    except (ServiceError, ConfigurationError, ValueError) as exc:
        raise ToolError(f"Wikipedia article {page_id} is unavailable: {str(exc)[:160]}") from None
    return {
        "page_id": article.page_id, "revision_id": article.revision_id, "title": article.title,
        "url": article.url, "text": article.text, "offset": article.offset,
        "next_offset": article.next_offset, "total_chars": article.total_chars, "source": "live",
    }


def _wiki_page(page_id: str, offset: int, max_chars: int, expected_revision: str | None) -> dict[str, Any]:
    cached = _cached_article(page_id)
    if cached is not None:
        text = cached["text"]
        page = {
            "page_id": page_id, "revision_id": cached["revision_id"], "title": cached.get("title", ""),
            "url": cached["url"], "text": text[offset:offset + max_chars], "offset": offset,
            "next_offset": offset + max_chars if offset + max_chars < len(text) else None,
            "total_chars": len(text), "source": "cache",
        }
    else:
        page = _live_article(page_id, offset, max_chars)
    if expected_revision is not None and page["revision_id"] != expected_revision:
        raise ToolError(
            f"revision mismatch for page {page_id}: match record has {expected_revision}, "
            f"source has {page['revision_id']}",
            expected_revision_id=expected_revision, found_revision_id=page["revision_id"],
        )
    return page


def _match_revision(page_id: str) -> str | None:
    """Revision that a match record pinned for this page, or None when no record names it."""
    revisions = {m.match.revision_id for m in _matches().values() if m.match and m.match.page_id == page_id}
    if len(revisions) > 1:
        raise ToolError(f"match records pin more than one revision for page {page_id}")
    return revisions.pop() if revisions else None


# ---------------------------------------------------------------- brit_search

def _keyword_search(query: str, k: int, entries: dict[str, Any]) -> list[Any]:
    words = [w for w in re.findall(r"\w+", query.lower()) if len(w) > 1]
    scored = []
    for entry in entries.values():
        haystack = f"{entry.headword or ''} {entry.text}".lower()
        hits = sum(haystack.count(w) for w in words)
        head_bonus = 5 if entry.headword and entry.headword.lower() in query.lower() else 0
        if hits or head_bonus:
            scored.append((hits + head_bonus, entry.entry_id, entry))
    scored.sort(key=lambda row: (-row[0], row[1]))
    return [row[2] for row in scored[:k]]


def _vector_search(query: str, k: int, entries: dict[str, Any]) -> list[Any]:
    """Embed VL query against LanceDB table `entries`. Raises when any piece is unavailable."""
    _core()
    import lancedb  # Not installed in every Hermes environment.
    from nemotron_challenge.clients import RetrievalClient
    from nemotron_challenge.config import Settings

    settings = Settings.from_env(env_file=None)
    if not settings.retrieval_base_url:
        raise RuntimeError("RETRIEVAL_BASE_URL is not set")
    with RetrievalClient(settings.retrieval_base_url, settings.retrieval_api_key, timeout=20) as client:
        vector = client.embed([query], "query")[0]
    table = lancedb.connect(str(settings.db_path)).open_table("entries")
    rows = table.search(vector).limit(k).to_list()
    return [entries[row["entry_id"]] for row in rows if row.get("entry_id") in entries]


def _preview(entry: Any) -> dict[str, Any]:
    return {
        "entry_id": entry.entry_id, "headword": entry.headword, "page_id": _entry_page_id(entry),
        "kind": entry.kind, "text_start": entry.text[:PREVIEW_CHARS], "quality": entry.quality,
    }


@_tool
def handle_brit_search(params: dict[str, Any]) -> dict[str, Any]:
    query = params.get("query")
    if not isinstance(query, str) or not query.strip() or len(query) > MAX_QUERY_CHARS:
        raise ToolError(f"query must contain 1 to {MAX_QUERY_CHARS} characters")
    k = _need_int(params.get("k", 5), 1, MAX_K, "k")
    entries = _entries()
    method, note = "keyword", None
    try:
        found = _vector_search(query, k, entries)
        method = "embedding"
    except Exception as exc:  # Unreachable service, missing table, or missing package.
        found = _keyword_search(query, k, entries)
        note = f"embedding search unavailable ({type(exc).__name__}); keyword match ran instead"
    if not found:
        raise ToolError("no Britannica entry matched this query", method=method, note=note)
    result: dict[str, Any] = {"method": method, "entries": [_preview(e) for e in found]}
    if note:
        result["note"] = note
    return result


# ---------------------------------------------------------------- brit_entry

@_tool
def handle_brit_entry(params: dict[str, Any]) -> dict[str, Any]:
    entry_id = _need_entry_id(params)
    entry = _entries().get(entry_id)
    if entry is None:
        raise ToolError(f"no Britannica entry with id {entry_id}")
    return {
        "entry_id": entry.entry_id, "kind": entry.kind, "headword": entry.headword,
        "page_id": _entry_page_id(entry), "text": entry.text, "text_raw": entry.text_raw,
        "blocks": [block.model_dump() for block in entry.blocks], "quality": entry.quality,
        "crop_path": entry.crop_path, "continues_from": entry.continues_from,
        "continues_to": entry.continues_to, "source": _source_info(entry),
    }


# ---------------------------------------------------------------- wiki_article

@_tool
def handle_wiki_article(params: dict[str, Any]) -> dict[str, Any]:
    page_id = params.get("page_id")
    if not isinstance(page_id, str) or not PAGE_ID.fullmatch(page_id):
        raise ToolError("page_id must contain digits only")
    offset = _need_int(params.get("offset", 0), 0, 100_000_000, "offset")
    page = _wiki_page(page_id, offset, WIKI_PAGE_CHARS, _match_revision(page_id))
    return {
        "page_id": page["page_id"], "revision_id": page["revision_id"], "title": page["title"],
        "url": page["url"], "offset": page["offset"], "text": page["text"],
        "next_offset": page["next_offset"], "total_chars": page["total_chars"], "source": page["source"],
    }


# ---------------------------------------------------------------- challenge_compare

def _delta(method_version: str) -> float | None:
    found = DELTA_PATTERN.search(method_version)
    return float(found.group(1)) if found else None


def _shared_terms(entry_id: str, page_id: str, revision_id: str) -> tuple[list[dict[str, Any]], str]:
    path = _work_dir() / "compare" / "drift.json"
    if not path.is_file():
        return [], "missing"
    _core()
    from nemotron_challenge.contracts import DriftReport

    report = DriftReport.model_validate_json(path.read_text(encoding="utf-8"))
    terms = [
        {
            "term": t.term, "brit_count": t.brit_count, "wiki_count": t.wiki_count,
            "log_ratio": t.log_ratio, "brit_quote": t.brit_example, "wiki_quote": t.wiki_example,
        }
        for t in report.terms
        if t.brit_count > 0 and t.wiki_count > 0
        and t.brit_example.get("entry_id") == entry_id
        and t.wiki_example.get("page_id") == page_id
        and t.wiki_example.get("revision_id") == revision_id
    ]
    return terms, report.method


@_tool
def handle_compare(params: dict[str, Any]) -> dict[str, Any]:
    entry_id = _need_entry_id(params)
    entry = _entries().get(entry_id)
    if entry is None:
        raise ToolError(f"no Britannica entry with id {entry_id}")
    record = _matches().get(entry_id)
    if record is None:
        raise ToolError(f"no match record for {entry_id}")
    result: dict[str, Any] = {
        "entry_id": entry_id, "headword": entry.headword, "quality": entry.quality,
        "match_record": {
            "status": record.status, "reason": record.reason,
            "rerank_margin": record.rerank_margin, "method_version": record.method_version,
        },
        "britannica": {"page_id": _entry_page_id(entry), "text_start": entry.text[:COMPARE_CHARS]},
    }
    delta = _delta(record.method_version)
    reasons = []
    if record.status != "matched":
        reasons.append(f"match status is {record.status}")
    if record.rerank_margin is not None and delta is not None and record.rerank_margin < delta:
        reasons.append(f"rerank margin {record.rerank_margin} is below delta {delta}")
    if reasons:
        result["match_uncertain"] = "; ".join(reasons)
    if record.match is None:
        result.update(wikipedia=None, shared_terms=[], evidence="missing",
                      missing="wikipedia: no accepted match for this entry")
        return result
    ref = record.match
    page = _wiki_page(ref.page_id, 0, COMPARE_CHARS, ref.revision_id)
    terms, method = _shared_terms(entry_id, ref.page_id, ref.revision_id)
    result["wikipedia"] = {
        "page_id": ref.page_id, "revision_id": ref.revision_id, "title": ref.title, "url": ref.url,
        "text_start": page["text"],
    }
    result["shared_terms"] = terms
    result["drift_method"] = method
    return result


# ---------------------------------------------------------------- registration

def _trace_reply(**kwargs: Any) -> None:
    """Record the model ID from each reply. The runner names the trace file."""
    path = _setting("trace_file", "CHALLENGE_TRACE_FILE")
    if not path:
        return
    row = {key: kwargs.get(key) for key in ("session_id", "response_model", "finish_reason", "api_call_count")}
    with open(path, "a", encoding="utf-8") as stream:
        stream.write(json.dumps(row) + "\n")


TOOLS = (
    ("brit_search", schemas.BRIT_SEARCH, handle_brit_search),
    ("brit_entry", schemas.BRIT_ENTRY, handle_brit_entry),
    ("wiki_article", schemas.WIKI_ARTICLE, handle_wiki_article),
    ("challenge_compare", schemas.CHALLENGE_COMPARE, handle_compare),
)


def register(ctx: Any) -> None:
    # The tools-off profile sets "tools": false in challenge_run.json. It keeps the trace hook only.
    for name, schema, handler in (TOOLS if _runtime().get("tools") is not False else ()):
        ctx.register_tool(name=name, toolset="nemotron_challenge", schema=schema, handler=handler)
    ctx.register_hook("post_api_request", _trace_reply)
