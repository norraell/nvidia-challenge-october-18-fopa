"""Rule m1: accept the reranker's top candidate when its logit and margin clear the thresholds.

The rule uses relevance scores. It does not establish factual agreement between the sources.
"""
from __future__ import annotations

from dataclasses import dataclass

from ..contracts import CandidateScore, MatchRecord, WikiRef

DEFAULT_TAU = 2.1
DEFAULT_DELTA = 0.4
RULE_NAME = "m1"


@dataclass(frozen=True)
class Thresholds:
    tau: float = DEFAULT_TAU
    delta: float = DEFAULT_DELTA

    @property
    def method_version(self) -> str:
        return f"{RULE_NAME}-tau={self.tau:g}-delta={self.delta:g}"


def reranked(candidates: list[CandidateScore]) -> list[CandidateScore]:
    """Candidates that carry a rerank score, in rerank order."""
    scored = [c for c in candidates if c.rerank_rank is not None and c.rerank_logit is not None]
    return sorted(scored, key=lambda c: c.rerank_rank or 0)


def rerank_margin(candidates: list[CandidateScore]) -> float | None:
    top = reranked(candidates)
    if len(top) < 2:
        return None
    return float(top[0].rerank_logit - top[1].rerank_logit)  # type: ignore[operator]


def decide(entry_id: str, queries: list[str], candidates: list[CandidateScore],
           thresholds: Thresholds = Thresholds()) -> MatchRecord:
    """Apply rule m1 to candidates that already carry rerank scores."""
    common = {"entry_id": entry_id, "queries": queries, "candidates": candidates,
              "method_version": thresholds.method_version}
    if not candidates:
        return MatchRecord(status="no_candidates", reason="rule: zero BM25 candidates for every query",
                           match=None, rerank_margin=None, **common)
    top = reranked(candidates)
    if not top:
        return MatchRecord(status="rejected", reason="rule: no candidate reached the reranker",
                           match=None, rerank_margin=None, **common)
    logit = float(top[0].rerank_logit)  # type: ignore[arg-type]
    margin = rerank_margin(candidates)
    clauses: list[str] = []
    if logit < thresholds.tau:
        clauses.append(f"top-1 logit {logit:.3f} < tau {thresholds.tau:g}")
    if margin is not None and margin < thresholds.delta:
        clauses.append(f"margin {margin:.3f} < delta {thresholds.delta:g}")
    if clauses:
        return MatchRecord(status="rejected", reason="rule: " + "; ".join(clauses), match=None,
                           rerank_margin=margin, **common)
    margin_note = f"margin {margin:.3f} >= {thresholds.delta:g}" if margin is not None else "single reranked candidate, margin not applicable"
    reason = f"rule: rerank top-1 logit {logit:.3f} >= tau {thresholds.tau:g} and {margin_note}"
    return MatchRecord(status="matched", reason=reason, match=top[0].wiki, rerank_margin=margin, **common)


def skipped(entry_id: str, reason: str, thresholds: Thresholds = Thresholds(),
            match: WikiRef | None = None) -> MatchRecord:
    return MatchRecord(entry_id=entry_id, status="skipped", reason=reason, queries=[], candidates=[],
                       match=match, rerank_margin=None, method_version=thresholds.method_version)


def redecide(record: MatchRecord, thresholds: Thresholds) -> MatchRecord:
    """Apply new thresholds to stored scores without any model call. Skipped rows keep their status."""
    if record.status == "skipped":
        return record.model_copy(update={"method_version": thresholds.method_version})
    return decide(record.entry_id, record.queries, record.candidates, thresholds)
