"""Rerank the embed shortlist with the entry text as the query. Keep raw logits."""
from __future__ import annotations

from collections.abc import Callable
import time
from typing import Any, Protocol

from ..contracts import CandidateScore
from .candidates import call_with_retry
from .embed_stage import document_text
from .queries import clean_text, cut

QUERY_CHARS = 2000
MAX_DOCUMENTS = 32


class Reranker(Protocol):
    def rerank(self, query: str, documents: list[str | dict[str, str]], top_n: int | None = None) -> list[dict[str, Any]]: ...


def rerank_query(entry_text: str, limit: int = QUERY_CHARS) -> str:
    return cut(clean_text(entry_text), limit)


def rerank_candidates(client: Reranker, entry_text: str, candidates: list[CandidateScore], keep_ids: list[str], *,
                      query_chars: int = QUERY_CHARS, image_data_url: str | None = None,
                      sleep: Callable[[float], None] = time.sleep,
                      attempts_log: list[dict[str, Any]] | None = None,
                      stats: dict[str, int] | None = None) -> list[CandidateScore]:
    """Return candidates with rerank_logit and rerank_rank on the kept ones. Others keep None.

    When `image_data_url` is given, each document carries the scan image next to its text.
    """
    chosen = [c for c in candidates if c.wiki.page_id in set(keep_ids)][:MAX_DOCUMENTS]
    if not chosen:
        return list(candidates)
    query = rerank_query(entry_text, query_chars)
    if not query:
        raise ValueError("entry text is empty after cleaning")
    documents: list[str | dict[str, str]] = []
    for c in chosen:
        text = document_text(c)
        documents.append({"text": text, "image": image_data_url} if image_data_url else text)
    rows = call_with_retry(lambda: client.rerank(query, documents), sleep=sleep, attempts_log=attempts_log)
    if stats is not None:
        stats["rerank_calls"] = stats.get("rerank_calls", 0) + 1
        stats["rerank_query_chars"] = len(query)
    ordered = sorted(rows, key=lambda r: (-float(r["relevance_score"]), r["index"]))
    by_page = {chosen[r["index"]].wiki.page_id: (float(r["relevance_score"]), rank + 1) for rank, r in enumerate(ordered)}
    return [c.model_copy(update={"rerank_logit": by_page[c.wiki.page_id][0], "rerank_rank": by_page[c.wiki.page_id][1]})
            if c.wiki.page_id in by_page else c for c in candidates]
