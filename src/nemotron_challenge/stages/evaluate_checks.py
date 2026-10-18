"""Evidence checks for saved agent runs. Observations read the record; inferences use rules."""
from __future__ import annotations

import re

from ..config import SUPER_MODEL
from ..contracts import EntryRecord, EvidenceCheck, MatchRecord, RunRecord

UNCERTAINTY_PATTERNS = (
    r"\bcannot answer\b", r"\bcan't answer\b", r"\bno evidence\b", r"\bnot enough evidence\b",
    r"\bdoes not mention\b", r"\bdo not mention\b", r"\bunable to\b", r"\bnot found\b",
    r"\buncertain\b", r"\bconflict", r"\bmissing\b",
)


def _citation_key(citation: dict[str, str]) -> tuple[str, str, str]:
    return (citation.get("source", ""), citation.get("id", ""), citation.get("quote", ""))


def check_model_id(run: RunRecord, expected: str = SUPER_MODEL) -> EvidenceCheck:
    passed = run.model == expected
    detail = f"reply model {run.model!r}" + ("" if passed else f" differs from required {expected!r}")
    return EvidenceCheck(name="model_id", kind="observation", passed=passed, detail=detail)


def check_finish_reason(run: RunRecord) -> EvidenceCheck:
    passed = run.finish_reason == "stop"
    return EvidenceCheck(name="finish_reason", kind="observation", passed=passed,
                         detail=f"finish_reason {run.finish_reason!r}")


def check_tool_calls(run: RunRecord) -> EvidenceCheck:
    errors = [call for call in run.tool_calls if call.error]
    if not run.tools_enabled:
        return EvidenceCheck(name="tool_calls", kind="observation", passed=None, detail="tools disabled for this run")
    if not run.tool_calls:
        return EvidenceCheck(name="tool_calls", kind="observation", passed=False, detail="tools enabled but no tool call recorded")
    names = ", ".join(sorted({call.name for call in run.tool_calls}))
    if errors:
        detail = f"{len(errors)} of {len(run.tool_calls)} tool calls failed ({names}): " + "; ".join(str(call.error) for call in errors)
        return EvidenceCheck(name="tool_calls", kind="observation", passed=False, detail=detail)
    return EvidenceCheck(name="tool_calls", kind="observation", passed=True,
                         detail=f"{len(run.tool_calls)} tool calls without errors ({names})")


def check_citations_present(run: RunRecord) -> EvidenceCheck:
    passed = len(run.citations) > 0
    return EvidenceCheck(name="citations_present", kind="observation", passed=passed,
                         detail=f"{len(run.citations)} citations in the run record")


def _wiki_ids(matches: list[MatchRecord]) -> set[str]:
    ids: set[str] = set()
    for match in matches:
        for candidate in match.candidates:
            ids.add(f"{candidate.wiki.page_id}@{candidate.wiki.revision_id}")
        if match.match is not None:
            ids.add(f"{match.match.page_id}@{match.match.revision_id}")
    return ids


def check_citations_resolve(run: RunRecord, entries: list[EntryRecord], matches: list[MatchRecord]) -> EvidenceCheck:
    """Each citation ID must name a known entry or a Wikipedia page@revision seen in matching."""
    if not run.citations:
        return EvidenceCheck(name="citations_resolve", kind="observation", passed=None, detail="no citations to resolve")
    if not entries and not matches:
        return EvidenceCheck(name="citations_resolve", kind="observation", passed=None,
                             detail="no entries or matches available to resolve citations")
    entry_ids = {entry.entry_id for entry in entries}
    wiki_ids = _wiki_ids(matches)
    unresolved = []
    for citation in run.citations:
        source, cite_id, _ = _citation_key(citation)
        known = entry_ids if source.lower().startswith("brit") else wiki_ids
        if cite_id not in known:
            unresolved.append(f"{source}:{cite_id}")
    if unresolved:
        return EvidenceCheck(name="citations_resolve", kind="observation", passed=False,
                             detail="unresolved citation ids: " + ", ".join(unresolved))
    return EvidenceCheck(name="citations_resolve", kind="observation", passed=True,
                         detail=f"all {len(run.citations)} citation ids resolve to saved records")


def _normalize(text: str) -> str:
    return re.sub(r"\s+", " ", text.replace("ſ", "s")).strip().lower()


def check_citation_quotes(run: RunRecord, entries: list[EntryRecord], matches: list[MatchRecord]) -> EvidenceCheck:
    """Each quote must appear in the cited entry text or in a saved Wikipedia excerpt."""
    if not run.citations:
        return EvidenceCheck(name="citation_quotes", kind="observation", passed=None, detail="no citations to check")
    entry_text = {entry.entry_id: _normalize(entry.text) for entry in entries}
    wiki_text: dict[str, str] = {}
    for match in matches:
        for candidate in match.candidates:
            key = f"{candidate.wiki.page_id}@{candidate.wiki.revision_id}"
            wiki_text[key] = wiki_text.get(key, "") + " " + _normalize(candidate.excerpt)
    missing, unchecked = [], []
    for citation in run.citations:
        source, cite_id, quote = _citation_key(citation)
        haystack = entry_text.get(cite_id) if source.lower().startswith("brit") else wiki_text.get(cite_id)
        if haystack is None:
            unchecked.append(f"{source}:{cite_id}")
        elif _normalize(quote) not in haystack:
            missing.append(f"{source}:{cite_id}")
    if missing:
        return EvidenceCheck(name="citation_quotes", kind="observation", passed=False,
                             detail="quotes not found in saved source text: " + ", ".join(missing))
    if unchecked and len(unchecked) == len(run.citations):
        return EvidenceCheck(name="citation_quotes", kind="observation", passed=None,
                             detail="no saved source text for: " + ", ".join(unchecked))
    detail = "quotes found in saved source text"
    if unchecked:
        detail += "; no saved text for: " + ", ".join(unchecked)
    return EvidenceCheck(name="citation_quotes", kind="observation", passed=True, detail=detail)


def check_answer_cites(run: RunRecord) -> EvidenceCheck:
    """Inference: the answer refers to every citation id. A marker match is not a factual check."""
    if not run.answer.strip():
        return EvidenceCheck(name="answer_cites", kind="inference", passed=False, detail="empty answer")
    if not run.citations:
        return EvidenceCheck(name="answer_cites", kind="inference", passed=None, detail="no citations to look for")
    absent = [cite_id for _, cite_id, _ in map(_citation_key, run.citations) if cite_id not in run.answer]
    if absent:
        return EvidenceCheck(name="answer_cites", kind="inference", passed=False,
                             detail="answer does not mention citation ids: " + ", ".join(absent))
    return EvidenceCheck(name="answer_cites", kind="inference", passed=True,
                         detail="answer text mentions every citation id")


def check_uncertainty_claim(run: RunRecord) -> EvidenceCheck:
    """Inference: the answer states missing, uncertain, or conflicting evidence. Reviewers confirm it."""
    hits = sorted({match.group(0) for pattern in UNCERTAINTY_PATTERNS
                   for match in re.finditer(pattern, run.answer, flags=re.IGNORECASE)})
    if not hits:
        return EvidenceCheck(name="uncertainty_claim", kind="inference", passed=None,
                             detail="no missing-evidence or uncertainty phrase in the answer")
    return EvidenceCheck(name="uncertainty_claim", kind="inference", passed=None,
                         detail="answer claims missing or uncertain evidence: " + ", ".join(hits))


def run_checks(run: RunRecord, entries: list[EntryRecord], matches: list[MatchRecord]) -> list[EvidenceCheck]:
    return [
        check_model_id(run),
        check_finish_reason(run),
        check_tool_calls(run),
        check_citations_present(run),
        check_citations_resolve(run, entries, matches),
        check_citation_quotes(run, entries, matches),
        check_answer_cites(run),
        check_uncertainty_claim(run),
    ]
