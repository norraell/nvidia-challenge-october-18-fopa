"""Tests for artifact contracts and validation of frozen fixtures."""
import json
from pathlib import Path
import pytest
from pydantic import ValidationError

from nemotron_challenge.contracts import (
    Block,
    CandidateScore,
    DriftReport,
    EntryRecord,
    MatchRecord,
    PageRecord,
    ParseRun,
    RunRecord,
    TermRow,
    ToolCall,
    WikiRef,
)

FIXTURES_DIR = Path(__file__).parent / "fixtures" / "artifacts"


def test_fixture_pages_validate():
    pages_path = FIXTURES_DIR / "extract" / "pages.jsonl"
    assert pages_path.exists(), f"Missing fixture: {pages_path}"
    pages: list[PageRecord] = []
    with pages_path.open() as f:
        for line in f:
            line = line.strip()
            if line:
                pages.append(PageRecord.model_validate_json(line))
    assert len(pages) == 3
    assert all(p.status == "ok" for p in pages)
    assert all(p.parse is not None for p in pages)


def test_fixture_entries_validate():
    entries_path = FIXTURES_DIR / "extract" / "entries.jsonl"
    assert entries_path.exists(), f"Missing fixture: {entries_path}"
    entries: list[EntryRecord] = []
    with entries_path.open() as f:
        for line in f:
            line = line.strip()
            if line:
                entries.append(EntryRecord.model_validate_json(line))
    assert len(entries) == 5

    # Exactly one continuation and one plate required
    kinds = [e.kind for e in entries]
    assert kinds.count("continuation") == 1
    assert kinds.count("plate") == 1
    assert kinds.count("entry") == 3

    # Every entry fixture has fixture=true in quality
    for e in entries:
        assert e.quality.get("fixture") is True
        assert len(e.blocks) >= 1
        for b in e.blocks:
            assert len(b.bbox) == 4


def test_fixture_matches_validate():
    matches_path = FIXTURES_DIR / "match" / "matches.jsonl"
    assert matches_path.exists(), f"Missing fixture: {matches_path}"
    matches: list[MatchRecord] = []
    with matches_path.open() as f:
        for line in f:
            line = line.strip()
            if line:
                matches.append(MatchRecord.model_validate_json(line))
    assert len(matches) == 5

    # 3 matched, 1 rejected, 1 no_candidates required
    statuses = [m.status for m in matches]
    assert statuses.count("matched") == 3
    assert statuses.count("rejected") == 1
    assert statuses.count("no_candidates") == 1


def test_fixture_drift_report_validate():
    drift_path = FIXTURES_DIR / "compare" / "drift.json"
    assert drift_path.exists(), f"Missing fixture: {drift_path}"
    with drift_path.open() as f:
        data = json.load(f)
    report = DriftReport.model_validate(data)
    assert report.pairs_used == 3
    assert len(report.terms) >= 1
    assert all(isinstance(t, TermRow) for t in report.terms)


def test_fixture_agent_runs_validate():
    runs_dir = FIXTURES_DIR / "agent" / "runs"
    assert runs_dir.exists(), f"Missing fixtures dir: {runs_dir}"
    run_files = sorted(runs_dir.glob("*.json"))
    assert len(run_files) == 2

    runs: list[RunRecord] = []
    for rf in run_files:
        with rf.open() as f:
            runs.append(RunRecord.model_validate(json.load(f)))

    labels = [r.label for r in runs]
    assert "success" in labels
    assert "failure" in labels
    for r in runs:
        assert "fixture: true" in r.notes


def test_contract_strictness_extra_forbid():
    """Ensure strict extra='forbid' rejects unexpected fields."""
    with pytest.raises(ValidationError):
        ParseRun.model_validate({
            "model": "nvidia/nemotron-3.5-parse",
            "latency_ms": 100,
            "finish_reason": "stop",
            "raw_path": "test.json",
            "unknown_extra": 123,
        })

    with pytest.raises(ValidationError):
        Block(
            page_id="p1",
            bbox=[0.0, 0.0, 10.0],  # min_length=4
            cls="Text",
            text="short",
        )

    with pytest.raises(ValidationError):
        Block(
            page_id="p1",
            bbox=[0.0, 0.0, 10.0, 10.0, 10.0],  # max_length=4
            cls="Text",
            text="long",
        )

    with pytest.raises(ValidationError):
        WikiRef.model_validate({
            "page_id": "1",
            "revision_id": "2",
            "title": "T",
            "url": "http://example.com",
            "extra_field": "bad",
        })


def test_contract_edge_cases():
    """Test status variations and optional field handling across contracts."""
    # Failed PageRecord without ParseRun
    failed_page = PageRecord(
        page_id="britannica:rev:train:999",
        row_index=999,
        volume_id="vol1",
        filename="page-0999.jpg",
        image_sha256="a" * 64,
        width=1000,
        height=1000,
        status="failed",
        parse=None,
        error="Service 504 Gateway Timeout",
        entry_ids=[],
    )
    assert failed_page.status == "failed"
    assert failed_page.parse is None

    # Skipped MatchRecord with null match and rerank_margin
    skipped_match = MatchRecord(
        entry_id="e0001-02",
        status="skipped",
        reason="continuation entry skipped",
        queries=[],
        candidates=[],
        match=None,
        rerank_margin=None,
        method_version="m1",
    )
    assert skipped_match.status == "skipped"

    # Invalid status should raise ValidationError
    with pytest.raises(ValidationError):
        MatchRecord(
            entry_id="e0001-01",
            status="invalid_status",  # type: ignore
            reason="bad",
            queries=[],
            candidates=[],
            match=None,
            rerank_margin=None,
            method_version="m1",
        )

    # CandidateScore defaults
    score = CandidateScore(
        wiki=WikiRef(page_id="1", revision_id="2", title="T", url="http://example.com"),
        bm25_rank=1,
        bm25_score=10.5,
        excerpt="excerpt",
        excerpt_offset=0,
    )
    assert score.embed_cosine is None
    assert score.rerank_logit is None

    # EntryRecord default quality is empty dict
    entry = EntryRecord(
        entry_id="e0001-01",
        kind="entry",
        headword="HEAD",
        text="text",
        text_raw="text",
        blocks=[Block(page_id="p1", bbox=[0.0, 0.0, 10.0, 10.0], cls="Text", text="t")],
        crop_path="crops/e0001-01.png",
    )
    assert entry.quality == {}
