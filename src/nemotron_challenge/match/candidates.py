"""Search Wikipedia for each query, cache replies on disk, and pool hits by page_id."""
from __future__ import annotations

from collections.abc import Callable
import hashlib
import json
from pathlib import Path
import time
from typing import Any, Protocol

from ..clients import ServiceError
from ..contracts import CandidateScore, WikiHit, WikiRef, WikiSearch

TOP_K = 20
EXCERPT_CHARS = 1000
MAX_ATTEMPTS = 5
BACKOFF_BASE_SECONDS = 1.0
BACKOFF_CAP_SECONDS = 30.0
NON_RETRY_STATUSES = frozenset({400, 404, 413, 422})


class Searcher(Protocol):
    def search(self, query: str, top_k: int = ..., excerpt_chars: int = ...) -> WikiSearch: ...


class RetryExhausted(ServiceError):
    """Every retry attempt failed."""


def retry_delay(attempt: int, retry_after: str | None) -> float:
    if retry_after:
        try:
            return min(max(float(retry_after), 0.0), BACKOFF_CAP_SECONDS)
        except ValueError:
            pass
    return min(BACKOFF_BASE_SECONDS * (2 ** attempt), BACKOFF_CAP_SECONDS)


def call_with_retry(operation: Callable[[], Any], *, sleep: Callable[[float], None] = time.sleep,
                    max_attempts: int = MAX_ATTEMPTS, attempts_log: list[dict[str, Any]] | None = None) -> Any:
    """Run `operation`. Retry on 429, 503, timeouts, and connection errors. Never retry a 422 unchanged."""
    last: ServiceError | None = None
    for attempt in range(max_attempts):
        try:
            return operation()
        except ServiceError as exc:
            last = exc
            if attempts_log is not None:
                attempts_log.append({"attempt": attempt + 1, "status_code": exc.status_code, "error": str(exc),
                                     "retry_after": exc.retry_after, "at": time.time()})
            if exc.status_code in NON_RETRY_STATUSES:
                raise
            if attempt + 1 < max_attempts:
                sleep(retry_delay(attempt, exc.retry_after))
    raise RetryExhausted(f"gave up after {max_attempts} attempts: {last}",
                         status_code=last.status_code if last else None)


class SearchCache:
    """Store search replies as JSON files keyed by sha256 of the request."""

    def __init__(self, directory: Path | None):
        self.directory = directory
        if directory is not None:
            directory.mkdir(parents=True, exist_ok=True)

    def key(self, query: str, top_k: int, excerpt_chars: int) -> str:
        payload = json.dumps({"query": query, "top_k": top_k, "excerpt_chars": excerpt_chars}, sort_keys=True)
        return hashlib.sha256(payload.encode()).hexdigest()

    def path(self, key: str) -> Path | None:
        return None if self.directory is None else self.directory / f"{key}.json"

    def get(self, query: str, top_k: int, excerpt_chars: int) -> WikiSearch | None:
        path = self.path(self.key(query, top_k, excerpt_chars))
        if path is None or not path.exists():
            return None
        try:
            return WikiSearch.model_validate_json(path.read_text())
        except ValueError:
            path.unlink()
            return None

    def put(self, query: str, top_k: int, excerpt_chars: int, result: WikiSearch) -> None:
        path = self.path(self.key(query, top_k, excerpt_chars))
        if path is None:
            return
        tmp = path.with_suffix(".tmp")
        tmp.write_text(result.model_dump_json())
        tmp.replace(path)


def search_cached(client: Searcher, cache: SearchCache, query: str, *, top_k: int = TOP_K,
                  excerpt_chars: int = EXCERPT_CHARS, sleep: Callable[[float], None] = time.sleep,
                  attempts_log: list[dict[str, Any]] | None = None) -> tuple[WikiSearch, bool]:
    """Return (result, from_cache)."""
    hit = cache.get(query, top_k, excerpt_chars)
    if hit is not None:
        return hit, True
    result = call_with_retry(lambda: client.search(query, top_k=top_k, excerpt_chars=excerpt_chars),
                             sleep=sleep, attempts_log=attempts_log)
    cache.put(query, top_k, excerpt_chars, result)
    return result, False


def _ref(hit: WikiHit) -> WikiRef:
    return WikiRef(page_id=hit.page_id, revision_id=hit.revision_id, title=hit.title, url=hit.url)


def pool_candidates(results: list[tuple[str, WikiSearch]]) -> tuple[list[CandidateScore], dict[str, dict[str, Any]]]:
    """Union hits by page_id. Keep the hit with the best BM25 score. Record which query found each page.

    Returns (candidates sorted by bm25_score descending, sources keyed by page_id).
    """
    best: dict[str, WikiHit] = {}
    sources: dict[str, dict[str, Any]] = {}
    for kind, result in results:
        for hit in result.hits:
            found = sources.setdefault(hit.page_id, {"title": hit.title, "queries": {}})
            found["queries"][kind] = {"bm25_rank": hit.rank, "bm25_score": float(hit.bm25_score)}
            current = best.get(hit.page_id)
            if current is None or hit.bm25_score > current.bm25_score:
                best[hit.page_id] = hit
    ordered = sorted(best.values(), key=lambda h: (-h.bm25_score, h.rank, h.page_id))
    candidates = [CandidateScore(wiki=_ref(h), bm25_rank=h.rank, bm25_score=float(h.bm25_score),
                                 excerpt=h.excerpt, excerpt_offset=h.excerpt_offset) for h in ordered]
    return candidates, sources
