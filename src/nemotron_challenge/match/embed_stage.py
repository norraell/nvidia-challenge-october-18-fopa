"""Embed the entry text and candidate excerpts. Keep the top candidates by cosine."""
from __future__ import annotations

from collections.abc import Callable
import time
from typing import Any, Protocol

from ..contracts import CandidateScore
from .candidates import call_with_retry
from .queries import clean_text, cut

QUERY_CHARS = 1500
DOCUMENT_CHARS = 6000
BATCH_SIZE = 16
KEEP_TOP = 10


class Embedder(Protocol):
    def embed(self, inputs: list[str | dict[str, str]], input_type: str) -> list[list[float]]: ...


def document_text(candidate: CandidateScore, limit: int = DOCUMENT_CHARS) -> str:
    text = clean_text(f"{candidate.wiki.title}\n{candidate.excerpt}".replace("\n", " ")) or candidate.wiki.title
    return cut(text, limit) or candidate.wiki.title


def query_text(entry_text: str, limit: int = QUERY_CHARS) -> str:
    return cut(clean_text(entry_text), limit)


def cosine(a: list[float], b: list[float]) -> float:
    return float(sum(x * y for x, y in zip(a, b)))


def batches(items: list[Any], size: int = BATCH_SIZE) -> list[list[Any]]:
    return [items[i:i + size] for i in range(0, len(items), size)]


def title_matches(candidates: list[CandidateScore], titles: list[str]) -> list[str]:
    """page_ids whose title equals one of the headword variants, ignoring case."""
    wanted = {t.lower() for t in titles}
    return [c.wiki.page_id for c in candidates if c.wiki.title.lower() in wanted]


def embed_candidates(client: Embedder, entry_text: str, candidates: list[CandidateScore], *,
                     keep_top: int = KEEP_TOP, query_chars: int = QUERY_CHARS, always_keep: list[str] | None = None,
                     sleep: Callable[[float], None] = time.sleep,
                     attempts_log: list[dict[str, Any]] | None = None,
                     stats: dict[str, int] | None = None) -> tuple[list[CandidateScore], list[float], list[str]]:
    """Return (candidates with embed scores, query vector, page_ids kept for reranking)."""
    if not candidates:
        return [], [], []
    query = query_text(entry_text, query_chars)
    if not query:
        raise ValueError("entry text is empty after cleaning")
    calls = 0
    query_vector = call_with_retry(lambda: client.embed([query], "query"), sleep=sleep, attempts_log=attempts_log)[0]
    calls += 1
    documents = [document_text(c) for c in candidates]
    vectors: list[list[float]] = []
    for batch in batches(documents):
        vectors.extend(call_with_retry(lambda b=batch: client.embed(b, "document"), sleep=sleep, attempts_log=attempts_log))
        calls += 1
    if stats is not None:
        stats["embed_calls"] = stats.get("embed_calls", 0) + calls
        stats["embed_query_chars"] = len(query)
    scores = [cosine(query_vector, v) for v in vectors]
    order = sorted(range(len(candidates)), key=lambda i: (-scores[i], i))
    ranks = {index: rank + 1 for rank, index in enumerate(order)}
    scored = [c.model_copy(update={"embed_cosine": scores[i], "embed_rank": ranks[i]}) for i, c in enumerate(candidates)]
    kept = [candidates[i].wiki.page_id for i in order[:keep_top]]
    for page_id in always_keep or []:  # an exact title match always reaches the reranker
        if page_id not in kept and any(c.wiki.page_id == page_id for c in candidates):
            kept.append(page_id)
    return scored, query_vector, kept
