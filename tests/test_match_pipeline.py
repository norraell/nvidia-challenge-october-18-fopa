"""Fixture entries through fake clients produce valid MatchRecord rows."""
import json
from pathlib import Path

import pytest

from nemotron_challenge.clients import ServiceError
from nemotron_challenge.contracts import MatchRecord
from nemotron_challenge.match.decide import Thresholds
from nemotron_challenge.match.inputs import bootstrap_entries_from_raw, load_entries
from nemotron_challenge.stages.match import MatchOptions, run_pipeline
from tests.match_fakes import FakeRetrieval, FakeWiki

FIXTURE_ENTRIES = Path(__file__).parent / "fixtures" / "artifacts" / "extract" / "entries.jsonl"


def run_fixture(tmp_path, **overrides):
    entries = load_entries(FIXTURE_ENTRIES)
    options = MatchOptions(**{"use_store": False, **overrides})
    wiki, retrieval = FakeWiki(), FakeRetrieval()
    summary = run_pipeline(entries, wiki, retrieval, options, tmp_path / "out", tmp_path / "cache", sleep=lambda s: None)
    rows = [MatchRecord.model_validate_json(l) for l in (tmp_path / "out" / "matches.jsonl").read_text().splitlines()]
    return entries, summary, rows, wiki, retrieval


def test_pipeline_writes_one_valid_record_per_entry(tmp_path):
    entries, summary, rows, wiki, retrieval = run_fixture(tmp_path)
    assert [r.entry_id for r in rows] == [e.entry_id for e in entries]
    by_id = {r.entry_id: r for r in rows}
    assert by_id["e0013-01"].status == "matched" and by_id["e0013-01"].match.title == "Abacus"
    assert by_id["e0104-01"].status == "matched" and by_id["e0104-01"].match.title == "Barometer"
    assert by_id["e0104-02"].status == "matched"  # plate caption names the barometer
    assert by_id["e0013-02"].status == "no_candidates"  # orphan continuation, head entry absent from the file
    assert by_id["e0115-01"].status in {"no_candidates", "rejected"}
    assert summary["entries_seen"] == 5 and sum(summary["status_counts"].values()) == 5
    assert summary["calls"]["embed_calls"] >= 3 and summary["calls"]["rerank_calls"] == 3
    assert summary["distinct_articles"] == 2 and summary["repeated_articles"] == 1
    assert summary["method_version"] == "m1-tau=2.1-delta=0.4"
    assert (tmp_path / "out" / "candidates.jsonl").exists() and (tmp_path / "out" / "REPORT.md").exists()
    report = json.loads((tmp_path / "out" / "report.json").read_text())
    assert report["coverage"]["by_status"]["matched"] == 3
    assert "factual agreement" in report["disclaimer"]
    assert any(row["entry_ids"] == ["e0104-01", "e0104-02"] for row in report["repeated_articles"]["suspicious"] + report["repeated_articles"]["expected"])


def test_pipeline_fetches_articles_and_writes_index(tmp_path):
    _, summary, rows, wiki, _ = run_fixture(tmp_path)
    index = [json.loads(l) for l in (tmp_path / "out" / "articles.jsonl").read_text().splitlines()]
    assert {r["title"] for r in index} == {"Abacus", "Barometer"}
    assert summary["articles_fetched"] == 2
    assert (tmp_path / "cache" / "articles" / "1024.json").exists()


def test_rerun_uses_search_cache(tmp_path):
    run_fixture(tmp_path)
    entries = load_entries(FIXTURE_ENTRIES)
    wiki, retrieval = FakeWiki(), FakeRetrieval()
    summary = run_pipeline(entries, wiki, retrieval, MatchOptions(use_store=False, fetch_articles=False),
                           tmp_path / "out", tmp_path / "cache", sleep=lambda s: None)
    assert wiki.calls == [] and summary["calls"]["search_calls"] == 0 and summary["calls"]["search_cached"] > 0


def test_continuation_copies_head_decision(tmp_path):
    entries = load_entries(FIXTURE_ENTRIES)
    head, cont = entries[0], entries[1].model_copy(update={"continues_from": entries[0].entry_id})
    summary = run_pipeline([head, cont], FakeWiki(), FakeRetrieval(), MatchOptions(use_store=False, fetch_articles=False),
                           tmp_path / "out", tmp_path / "cache", sleep=lambda s: None)
    rows = [MatchRecord.model_validate_json(l) for l in (tmp_path / "out" / "matches.jsonl").read_text().splitlines()]
    assert rows[1].status == "skipped" and rows[1].match == rows[0].match and "continuation of e0013-01" in rows[1].reason
    assert summary["repeated_articles"] == 1


def test_thresholds_change_decisions_and_version(tmp_path):
    _, summary, rows, _, _ = run_fixture(tmp_path, thresholds=Thresholds(tau=5.0), fetch_articles=False)
    assert all(r.status != "matched" for r in rows) and summary["method_version"] == "m1-tau=5-delta=0.4"


def test_service_outage_writes_no_matches(tmp_path):
    class Down(FakeRetrieval):
        def embed(self, inputs, input_type):
            raise ServiceError("service connection failed")
    entries = load_entries(FIXTURE_ENTRIES)
    with pytest.raises(ServiceError, match="no matches.jsonl"):
        run_pipeline(entries, FakeWiki(), Down(), MatchOptions(use_store=False), tmp_path / "out", tmp_path / "cache",
                     sleep=lambda s: None)
    assert not (tmp_path / "out" / "matches.jsonl").exists() and (tmp_path / "out" / "run-failed.json").exists()


def test_token_overflow_is_recorded_not_invented(tmp_path):
    class Overflow(FakeRetrieval):
        def rerank(self, query, documents, top_n=None):
            raise ServiceError("service returned HTTP 422", status_code=422)
    entries = load_entries(FIXTURE_ENTRIES)[:1]
    summary = run_pipeline(entries, FakeWiki(), Overflow(), MatchOptions(use_store=False, fetch_articles=False),
                           tmp_path / "out", tmp_path / "cache", sleep=lambda s: None)
    row = MatchRecord.model_validate_json((tmp_path / "out" / "matches.jsonl").read_text().strip())
    assert row.status == "rejected" and row.reason.startswith("error:") and row.match is None
    assert summary["failed_calls"][0]["status_code"] == 422


def test_options_from_env():
    options = MatchOptions.from_env({"MATCH_ENTRIES": "a.jsonl", "MATCH_TAU": "3", "MATCH_LIMIT": "7", "MATCH_STORE": "0"})
    assert options.entries_path == Path("a.jsonl") and options.thresholds.tau == 3.0 and options.limit == 7
    assert options.use_store is False and options.fetch_articles is True


def test_dev_bootstrap_builds_entries_from_raw_parse(tmp_path):
    raw_dir, metrics = Path("artifacts/extract/raw"), Path("artifacts/extract/parse_metrics.jsonl")
    if not raw_dir.exists() or not metrics.exists():
        pytest.skip("raw Parse output is not in this checkout")
    entries = bootstrap_entries_from_raw(raw_dir, metrics)
    by_id = {e.entry_id: e for e in entries}
    assert len(entries) >= 90 and by_id["e0013-01"].headword == "SHIP-BUILDING"
    assert "<x_" not in by_id["e0013-01"].text and by_id["e0013-01"].quality["dev_bootstrap"] is True
    assert by_id["e0270-01"].kind == "plate" and by_id["e0270-01"].headword == "HYDROSTATICS"
    assert by_id["e1017-01"].headword is None  # dictionary range header


def test_redecide_rewrites_matches_without_model_calls(tmp_path):
    from nemotron_challenge.stages.match import redecide_pipeline
    entries, _, rows, _, _ = run_fixture(tmp_path, thresholds=Thresholds(tau=5.0), fetch_articles=False)
    assert all(r.status != "matched" for r in rows)
    wiki, retrieval = FakeWiki(), FakeRetrieval()
    summary = redecide_pipeline(entries, wiki, retrieval, MatchOptions(use_store=False, thresholds=Thresholds(tau=2.1)),
                                tmp_path / "out", tmp_path / "cache", sleep=lambda s: None)
    rows = [MatchRecord.model_validate_json(l) for l in (tmp_path / "out" / "matches.jsonl").read_text().splitlines()]
    assert summary["status_counts"]["matched"] == 3 and summary["previous_method_version"] == "m1-tau=5-delta=0.4"
    assert retrieval.embed_batches == [] and retrieval.rerank_docs == [] and wiki.calls == []
    assert summary["articles_fetched"] == 2 and all(r.method_version == "m1-tau=2.1-delta=0.4" for r in rows)


def test_model_query_prefixes_headword_once():
    from nemotron_challenge.stages.match import model_query_text
    assert model_query_text("SHIP-BUILDING", "ends in close contact") == "SHIP-BUILDING. ends in close contact"
    assert model_query_text("ABACUS", "ABACUS, among the ancients") == "ABACUS, among the ancients"
    assert model_query_text(None, "<image> plain") == "plain"
    assert model_query_text("Lava", "") == "Lava"


def test_plate_images_rerank_twice_and_log_both_logits(tmp_path):
    import base64
    png = base64.b64decode("iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNkYPhfDwAChwGA60e6kgAAAABJRU5ErkJggg==")
    image = tmp_path / "plate.png"
    image.write_bytes(png)
    entries = load_entries(FIXTURE_ENTRIES)
    plate = next(e for e in entries if e.kind == "plate").model_copy(update={"crop_path": str(image)})
    retrieval = FakeRetrieval()
    run_pipeline([plate], FakeWiki(), retrieval, MatchOptions(use_store=False, fetch_articles=False, plate_images=True),
                 tmp_path / "out", tmp_path / "cache", sleep=lambda s: None)
    assert len(retrieval.rerank_docs) == 2 and isinstance(retrieval.rerank_docs[1][0], dict)
    log = json.loads((tmp_path / "out" / "candidates.jsonl").read_text())
    row = log["plate_image"]["logits"][0]
    assert row["with_image"] == pytest.approx(row["text_only"] + 0.5)
    record = MatchRecord.model_validate_json((tmp_path / "out" / "matches.jsonl").read_text())
    assert record.candidates[0].rerank_logit == row["text_only"]  # decision uses the text-only logit
