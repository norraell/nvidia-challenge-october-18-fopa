"""Rule m1 decisions from stored scores."""
import pytest

from nemotron_challenge.contracts import CandidateScore, MatchRecord, WikiRef
from nemotron_challenge.match.decide import Thresholds, decide, redecide, rerank_margin, skipped


def cand(page_id: str, logit: float | None, rank: int | None, cosine: float | None = 0.5) -> CandidateScore:
    return CandidateScore(wiki=WikiRef(page_id=page_id, revision_id="1", title=f"T{page_id}", url="https://e/x"),
                         bm25_rank=1, bm25_score=10.0, excerpt="e", excerpt_offset=0,
                         embed_cosine=cosine, embed_rank=1, rerank_logit=logit, rerank_rank=rank)


def test_method_version_encodes_thresholds():
    assert Thresholds().method_version == "m1-tau=2.1-delta=0.4"
    assert Thresholds(tau=3.0, delta=1.25).method_version == "m1-tau=3-delta=1.25"


def test_matched_when_logit_and_margin_clear():
    record = decide("e1", ["q"], [cand("1", 3.4, 1), cand("2", 2.5, 2)])
    assert record.status == "matched" and record.match.page_id == "1"
    assert record.rerank_margin == pytest.approx(0.9)
    assert "logit 3.400 >= tau 2.1" in record.reason
    MatchRecord.model_validate(record.model_dump())


def test_rejected_on_low_logit_and_on_small_margin():
    low = decide("e1", ["q"], [cand("1", 1.0, 1), cand("2", 0.0, 2)])
    assert low.status == "rejected" and low.match is None and "< tau" in low.reason
    close = decide("e1", ["q"], [cand("1", 3.0, 1), cand("2", 2.9, 2)])
    assert close.status == "rejected" and "margin 0.100 < delta" in close.reason
    assert close.candidates and close.rerank_margin == pytest.approx(0.1)


def test_no_candidates_and_skipped():
    none = decide("e1", ["q"], [])
    assert none.status == "no_candidates" and none.rerank_margin is None
    skip = skipped("e2", "continuation of e1", match=WikiRef(page_id="1", revision_id="1", title="T", url="https://e"))
    assert skip.status == "skipped" and skip.match.page_id == "1" and skip.candidates == []


def test_single_candidate_has_no_margin_but_can_match():
    record = decide("e1", ["q"], [cand("1", 3.0, 1)])
    assert record.status == "matched" and record.rerank_margin is None
    assert rerank_margin(record.candidates) is None


def test_unreranked_candidates_are_rejected_not_matched():
    record = decide("e1", ["q"], [cand("1", None, None, None)])
    assert record.status == "rejected" and "reranker" in record.reason


def test_redecide_from_stored_scores_without_model_calls():
    record = decide("e1", ["q"], [cand("1", 3.0, 1), cand("2", 2.9, 2)])
    assert record.status == "rejected"
    loose = redecide(record, Thresholds(tau=2.0, delta=0.05))
    assert loose.status == "matched" and loose.method_version == "m1-tau=2-delta=0.05"
    skip = redecide(skipped("e2", "cross reference"), Thresholds(tau=9.0))
    assert skip.status == "skipped" and skip.method_version == "m1-tau=9-delta=0.4"
