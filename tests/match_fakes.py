"""Fake Wikipedia and retrieval clients for match tests. No network."""
from __future__ import annotations

import hashlib
from typing import Any

from nemotron_challenge.clients import ServiceError
from nemotron_challenge.config import EMBED_DIMENSIONS, WIKIPEDIA_REVISION
from nemotron_challenge.contracts import WikiArticle, WikiSearch

PROVENANCE = {"dataset": "wikimedia/structured-wikipedia", "dataset_revision": WIKIPEDIA_REVISION,
              "dataset_url": "https://hf", "source_key": "k", "source_row_idx": 0, "source_shard": None,
              "text_sha256": "0" * 64, "extraction": "sections", "revision_url": "https://rev"}
LICENSE = {"spdx": "CC-BY-SA-4.0", "name": "CC BY-SA 4.0"}

ARTICLES = {
    "1024": ("Abacus", "An abacus is a calculating tool used in counting. " * 30),
    "3845": ("Barometer", "A barometer is a scientific instrument used to measure air pressure. " * 30),
    "99": ("Active Shipbuilding Experts' Federation", "The federation is an organization about shipbuilding. " * 30),
    "7": ("Shipbuilding", "Shipbuilding is the construction of ships and other floating vessels. " * 30),
}


def hit(page_id: str, rank: int, score: float, excerpt: str | None = None) -> dict[str, Any]:
    title, text = ARTICLES[page_id]
    return {"page_id": page_id, "revision_id": "100" + page_id, "title": title, "url": f"https://en.wikipedia.org/wiki/{title}",
            "provenance": {**PROVENANCE, "text_sha256": hashlib.sha256(text.encode()).hexdigest()}, "license": LICENSE,
            "rank": rank, "bm25_score": score, "excerpt": excerpt or text[:120], "excerpt_offset": 0, "total_chars": len(text)}


def search(query: str, hits: list[dict[str, Any]]) -> WikiSearch:
    return WikiSearch.model_validate({"query": query, "retrieval": "lexical_bm25", "corpus_revision": WIKIPEDIA_REVISION,
                                      "count": len(hits), "hits": hits})


class FakeWiki:
    """Routes queries by keyword. `fail_once` raises one 429 before the first successful search."""

    def __init__(self, fail_once: bool = False, page_chars: int = 500):
        self.calls: list[str] = []
        self.article_calls: list[tuple[str, int]] = []
        self.fail_once = fail_once
        self.page_chars = page_chars

    def search(self, query: str, top_k: int = 10, excerpt_chars: int = 1000) -> WikiSearch:
        if self.fail_once:
            self.fail_once = False
            raise ServiceError("service returned HTTP 429", status_code=429, retry_after="1")
        self.calls.append(query)
        q = query.lower()
        if "abacus" in q or "counters" in q:
            return search(query, [hit("1024", 1, 18.4)])
        if "barometer" in q or "atmosphere" in q:
            return search(query, [hit("3845", 1, 21.2)])
        if "shipbuilding" in q or "ship" in q:
            return search(query, [hit("99", 1, 12.6), hit("7", 2, 12.1)])
        return search(query, [])

    def article(self, page_id: str, offset: int = 0, max_chars: int = 10000) -> WikiArticle:
        self.article_calls.append((page_id, offset))
        title, text = ARTICLES[page_id]
        chunk = text[offset:offset + min(max_chars, self.page_chars)]
        end = offset + len(chunk)
        return WikiArticle.model_validate({
            "page_id": page_id, "revision_id": "100" + page_id, "title": title, "url": f"https://en.wikipedia.org/wiki/{title}",
            "provenance": {**PROVENANCE, "text_sha256": hashlib.sha256(text.encode()).hexdigest()}, "license": LICENSE,
            "text": chunk, "offset": offset, "returned_chars": len(chunk), "total_chars": len(text),
            "next_offset": end if end < len(text) else None})


def unit(seed: str) -> list[float]:
    """A deterministic unit vector with its mass on one axis chosen by the seed."""
    axis = int(hashlib.sha256(seed.encode()).hexdigest(), 16) % EMBED_DIMENSIONS
    vector = [0.0] * EMBED_DIMENSIONS
    vector[axis] = 1.0
    return vector


class FakeRetrieval:
    """Embeds by topic keyword so the right article gets cosine 1. Reranks by a fixed logit table."""

    LOGITS = {"Abacus": 3.4, "Barometer": 4.1, "Shipbuilding": 3.0, "Active Shipbuilding Experts' Federation": 2.8}

    def __init__(self):
        self.embed_batches: list[int] = []
        self.rerank_docs: list[list[Any]] = []
        self.rerank_queries: list[str] = []

    def verify_models(self) -> dict:
        return {}

    @staticmethod
    def topic(text: str) -> str:
        t = text.lower()
        for word in ("abacus", "barometer", "shipbuilding"):
            if word in t:
                return word
        return "other:" + t[:10]

    def embed(self, inputs: list[Any], input_type: str) -> list[list[float]]:
        assert 1 <= len(inputs) <= 16, "embedding items must be 1 to 16"
        self.embed_batches.append(len(inputs))
        texts = [i if isinstance(i, str) else i.get("text", "") for i in inputs]
        assert all(len(t) <= (2000 if input_type == "query" else 32000) for t in texts)
        return [unit(self.topic(t)) for t in texts]

    def rerank(self, query: str, documents: list[Any], top_n: int | None = None) -> list[dict[str, Any]]:
        assert 1 <= len(documents) <= 32 and len(query) <= 2000
        self.rerank_docs.append(documents)
        self.rerank_queries.append(query)
        rows = []
        for index, doc in enumerate(documents):
            text = doc if isinstance(doc, str) else doc["text"]
            title = text.split(" ", 1)[0]
            score = next((v for k, v in self.LOGITS.items() if text.startswith(k)), -5.0)
            if isinstance(doc, dict) and doc.get("image"):
                score += 0.5
            rows.append({"index": index, "relevance_score": score, "_title": title})
        rows.sort(key=lambda r: -r["relevance_score"])
        return [{"index": r["index"], "relevance_score": r["relevance_score"]} for r in rows]
