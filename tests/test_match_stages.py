"""Search pooling, retry, cache, embed batching, rerank cap, article pagination."""
from pathlib import Path

import pytest

from nemotron_challenge.clients import ProtocolError, ServiceError
from nemotron_challenge.match.articles import cache_article, fetch_article, load_cached_article, write_articles_index
from nemotron_challenge.match.candidates import (
    RetryExhausted, SearchCache, call_with_retry, pool_candidates, retry_delay, search_cached,
)
from nemotron_challenge.match.embed_stage import embed_candidates
from nemotron_challenge.match.rerank_stage import rerank_candidates
from tests.match_fakes import FakeRetrieval, FakeWiki, hit, search


def test_pool_dedupes_by_page_and_keeps_best_score():
    a = search("q1", [hit("7", 1, 12.0), hit("99", 2, 11.0)])
    b = search("q2", [hit("7", 3, 15.0)])
    candidates, sources = pool_candidates([("headword", a), ("content", b)])
    assert [c.wiki.page_id for c in candidates] == ["7", "99"]
    assert candidates[0].bm25_score == 15.0 and candidates[0].bm25_rank == 3
    assert set(sources["7"]["queries"]) == {"headword", "content"}
    assert sources["99"]["queries"] == {"content": {"bm25_rank": 2, "bm25_score": 11.0}} or "headword" in sources["99"]["queries"]


def test_retry_honors_retry_after_and_caches(tmp_path):
    wiki = FakeWiki(fail_once=True)
    slept: list[float] = []
    cache = SearchCache(tmp_path / "search")
    attempts: list[dict] = []
    result, cached = search_cached(wiki, cache, "abacus", sleep=slept.append, attempts_log=attempts)
    assert not cached and slept == [1.0] and attempts[0]["status_code"] == 429
    assert result.hits[0].title == "Abacus"
    again, cached = search_cached(wiki, cache, "abacus", sleep=slept.append)
    assert cached and again == result and wiki.calls == ["abacus"]


def test_retry_never_repeats_422_and_caps_attempts():
    calls = []

    def bad():
        calls.append(1)
        raise ServiceError("422", status_code=422)
    with pytest.raises(ServiceError):
        call_with_retry(bad, sleep=lambda s: None)
    assert len(calls) == 1

    def always_busy():
        raise ServiceError("503", status_code=503)
    slept: list[float] = []
    with pytest.raises(RetryExhausted):
        call_with_retry(always_busy, sleep=slept.append, max_attempts=3)
    assert slept == [retry_delay(0, None), retry_delay(1, None)]
    assert retry_delay(0, "7") == 7.0 and retry_delay(10, None) == 30.0


def test_embed_batches_at_16_and_cuts_query(tmp_path):
    retrieval = FakeRetrieval()
    results = search("q", [hit(pid, i + 1, 10.0 - i) for i, pid in enumerate(["7", "99", "1024", "3845"])])
    candidates, _ = pool_candidates([("headword", results)])
    many = candidates * 5  # 20 documents -> batches of 16 and 4
    stats: dict = {}
    scored, vector, kept = embed_candidates(retrieval, "shipbuilding text " * 500, many, stats=stats, sleep=lambda s: None)
    assert retrieval.embed_batches == [1, 16, 4]
    assert stats["embed_query_chars"] <= 1500 and len(vector) == 2048
    assert all(c.embed_cosine is not None and c.embed_rank is not None for c in scored)
    assert len(kept) == 10 and scored[0].embed_cosine == pytest.approx(1.0)


def test_rerank_caps_documents_and_marks_only_kept():
    retrieval = FakeRetrieval()
    candidates, _ = pool_candidates([("headword", search("q", [hit("7", 1, 12.0), hit("99", 2, 11.0), hit("1024", 3, 1.0)]))])
    out = rerank_candidates(retrieval, "x" * 5000, candidates, keep_ids=["7", "99"], sleep=lambda s: None)
    assert len(retrieval.rerank_docs[0]) == 2 and len(retrieval.rerank_queries[0]) <= 2000
    by_id = {c.wiki.page_id: c for c in out}
    assert by_id["7"].rerank_rank == 1 and by_id["99"].rerank_rank == 2 and by_id["1024"].rerank_logit is None
    assert by_id["7"].rerank_logit == 3.0


def test_rerank_with_image_sends_documents_with_image():
    retrieval = FakeRetrieval()
    candidates, _ = pool_candidates([("headword", search("q", [hit("7", 1, 12.0)]))])
    rerank_candidates(retrieval, "caption", candidates, ["7"], image_data_url="data:image/png;base64,AAAA", sleep=lambda s: None)
    assert retrieval.rerank_docs[0][0]["image"] == "data:image/png;base64,AAAA"


def test_fetch_article_paginates_verifies_and_caches(tmp_path):
    wiki = FakeWiki(page_chars=400)
    article = fetch_article(wiki, "1024", sleep=lambda s: None)
    assert len(wiki.article_calls) > 1 and article["total_chars"] == len(article["text"])
    path = cache_article(tmp_path, article)
    assert path == tmp_path / "articles" / "1024.json"
    assert load_cached_article(tmp_path, "1024")["title"] == "Abacus"
    write_articles_index(tmp_path / "articles.jsonl", [article])
    assert '"text_sha256"' in (tmp_path / "articles.jsonl").read_text()


def test_fetch_article_rejects_hash_mismatch():
    class Tampered(FakeWiki):
        def article(self, page_id, offset=0, max_chars=10000):
            page = super().article(page_id, offset, max_chars)
            return page.model_copy(update={"text": page.text.replace("a", "e"), "returned_chars": page.returned_chars})
    with pytest.raises(ProtocolError):
        fetch_article(Tampered(page_chars=400), "1024", sleep=lambda s: None)


def test_exact_title_candidate_always_reaches_reranker():
    from nemotron_challenge.match.embed_stage import title_matches
    retrieval = FakeRetrieval()
    hits = [hit(pid, i + 1, 10.0 - i) for i, pid in enumerate(["99", "1024", "3845"])] + [hit("7", 4, 1.0)]
    candidates, _ = pool_candidates([("headword", search("q", hits))])
    keep = title_matches(candidates, ["shipbuilding", "ship building"])
    assert keep == ["7"]
    _, _, kept = embed_candidates(retrieval, "abacus text", candidates, keep_top=1, always_keep=keep, sleep=lambda s: None)
    assert kept[0] == "1024" and "7" in kept and len(kept) == 2
