"""Tests for stages/evaluate: case selection, attempt chains, evidence checks, and the reproduction record."""
import json
from pathlib import Path

from nemotron_challenge.cli import main
from nemotron_challenge.config import SUPER_MODEL, Settings
from nemotron_challenge.contracts import EvaluationReport, RunRecord
from nemotron_challenge.stages import evaluate
from nemotron_challenge.stages.evaluate_checks import run_checks

FIXTURES_DIR = Path(__file__).parent / "fixtures" / "artifacts"


def _run(run_id: str, label: str, question: str, started_at: str, **overrides) -> dict:
    record = {
        "run_id": run_id,
        "started_at": started_at,
        "code_revision": "4b825dc642cb6eb9a060e54bf8d69288fbee4904",
        "hermes_version": "hermes-agent 0.4.1",
        "model": SUPER_MODEL,
        "question": question,
        "image_inputs": [],
        "tools_enabled": True,
        "tool_calls": [{"name": "brit_entry", "arguments": {"entry_id": "e0013-01"}, "result": "{}", "error": None}],
        "answer": "Britannica calls the abacus a table for calculating [B:e0013-01].",
        "citations": [{"source": "Britannica", "id": "e0013-01",
                       "quote": "ABACUS, among the ancients, was a table or desk for calculating"}],
        "finish_reason": "stop",
        "label": label,
        "notes": "synthetic test run",
    }
    record.update(overrides)
    return record


def _write_runs(work_dir: Path, runs: list[dict]) -> None:
    runs_dir = work_dir / "agent" / "runs"
    runs_dir.mkdir(parents=True)
    for record in runs:
        (runs_dir / f"{record['run_id']}.json").write_text(json.dumps(record), encoding="utf-8")


def test_fixture_inputs_give_incomplete_report_and_files(tmp_path):
    result = evaluate.run(Settings(), tmp_path)

    assert result["status"] == "incomplete"
    assert result["fixture_inputs"] is True
    assert result["selected"] == {"success": 1, "failure": 1}
    assert result["missing"] == {"success": 2, "failure": 2}
    report = EvaluationReport.model_validate(json.loads((tmp_path / "evaluate" / "report.json").read_text()))
    assert [case.case_id for case in report.cases] == ["case-success-1", "case-failure-1"]
    assert (tmp_path / "evaluate" / "README.md").exists()
    for case in report.cases:
        assert (tmp_path / "evaluate" / case.case_path).exists()
    assert any("starter fixtures" in limit for limit in report.reproduction.known_limits)


def test_selects_three_per_label_and_keeps_failed_attempt_separate(tmp_path):
    runs = [
        _run("run-01", "failure", "Compare abacus", "2026-10-18T10:00:00Z", answer="No citation here."),
        _run("run-02", "success", "Compare abacus", "2026-10-18T10:05:00Z"),
        _run("run-03", "success", "Compare barometer", "2026-10-18T10:10:00Z"),
        _run("run-04", "success", "Compare caloric", "2026-10-18T10:15:00Z"),
        _run("run-05", "success", "Compare caloric", "2026-10-18T10:20:00Z"),
        _run("run-06", "failure", "Steam speed", "2026-10-18T10:25:00Z"),
        _run("run-07", "failure", "Unknown plate", "2026-10-18T10:30:00Z"),
        _run("run-08", "unreviewed", "Not reviewed yet", "2026-10-18T10:35:00Z"),
    ]
    _write_runs(tmp_path, runs)

    result = evaluate.run(Settings(), tmp_path)

    assert result["status"] == "ok"
    assert result["fixture_inputs"] is False
    report = EvaluationReport.model_validate(json.loads((tmp_path / "evaluate" / "report.json").read_text()))
    by_run = {case.run_id: case for case in report.cases}
    assert sorted(by_run) == ["run-01", "run-02", "run-03", "run-04", "run-06", "run-07"]
    assert report.unselected_run_ids == ["run-05"]
    assert report.unreviewed_run_ids == ["run-08"]
    # The failed first attempt and its repaired result stay separate records that point at each other.
    assert by_run["run-01"].classification == "failure"
    assert by_run["run-01"].repaired_by == "run-02"
    assert by_run["run-02"].earlier_attempts == ["run-01"]
    assert by_run["run-02"].repaired_by is None
    failure_md = (tmp_path / "evaluate" / by_run["run-01"].case_path).read_text()
    assert "A later run `run-02` repaired this question" in failure_md
    success_md = (tmp_path / "evaluate" / by_run["run-02"].case_path).read_text()
    assert "Earlier attempts on the same question, kept as separate run records: `run-01`" in success_md


def test_evidence_checks_flag_unresolved_citation_and_wrong_model():
    fixture_entries = evaluate._load_jsonl(FIXTURES_DIR / "extract" / "entries.jsonl", evaluate.EntryRecord)
    fixture_matches = evaluate._load_jsonl(FIXTURES_DIR / "match" / "matches.jsonl", evaluate.MatchRecord)
    run = RunRecord.model_validate(_run(
        "run-x", "failure", "Q", "2026-10-18T10:00:00Z",
        model="nvidia/other-model",
        answer="Wikipedia says something, but I cannot answer fully.",
        citations=[{"source": "Wikipedia", "id": "999@1", "quote": "not in any excerpt"}],
        tool_calls=[{"name": "wiki_article", "arguments": {}, "result": "", "error": "timeout"}],
    ))

    checks = {check.name: check for check in run_checks(run, fixture_entries, fixture_matches)}

    assert checks["model_id"].passed is False
    assert checks["tool_calls"].passed is False and "timeout" in checks["tool_calls"].detail
    assert checks["citations_resolve"].passed is False and "999@1" in checks["citations_resolve"].detail
    assert checks["answer_cites"].passed is False and checks["answer_cites"].kind == "inference"
    assert "cannot answer" in checks["uncertainty_claim"].detail


def test_evidence_checks_pass_on_fixture_success_run():
    fixture_entries = evaluate._load_jsonl(FIXTURES_DIR / "extract" / "entries.jsonl", evaluate.EntryRecord)
    fixture_matches = evaluate._load_jsonl(FIXTURES_DIR / "match" / "matches.jsonl", evaluate.MatchRecord)
    run = RunRecord.model_validate(json.loads((FIXTURES_DIR / "agent" / "runs" / "run-001.json").read_text()))

    checks = {check.name: check for check in run_checks(run, fixture_entries, fixture_matches)}

    observations = [name for name, check in checks.items() if check.kind == "observation"]
    assert all(checks[name].passed is True for name in observations), {n: checks[n].detail for n in observations}
    assert checks["answer_cites"].passed is True


def test_reproduction_record_lists_models_data_and_revision(tmp_path):
    evaluate.run(Settings(), tmp_path)
    report = EvaluationReport.model_validate(json.loads((tmp_path / "evaluate" / "report.json").read_text()))
    repro = report.reproduction

    assert repro.models["embed"]["revision"] == "582e3bf72aee355e3c59ed89de53543c5b0657ee"
    assert repro.models["rerank"]["revision"] == "b8a9987b05b75db5ad949c825cbcbf6eb7c48b5a"
    assert repro.models["super"]["id"] == SUPER_MODEL
    assert repro.data["britannica"]["revision"] == "309f765b1ecc83e0a7f7762e44b4a927a7555443"
    assert repro.data["wikipedia"]["revision"] == "417c267bb457fa645c22eb3b5c77764963194c70"
    assert len(repro.code_revision) == 40 or repro.code_revision == "unknown"
    assert repro.packages["pydantic"] != "missing"
    assert "uv run nemotron-challenge run evaluate" in repro.commands
    assert repro.counts["matches_by_status"] == {"matched": 3, "no_candidates": 1, "rejected": 1}


def test_invalid_run_record_names_its_file(tmp_path):
    runs_dir = tmp_path / "agent" / "runs"
    runs_dir.mkdir(parents=True)
    (runs_dir / "bad.json").write_text('{"run_id": "bad"}', encoding="utf-8")

    try:
        evaluate.run(Settings(), tmp_path)
    except ValueError as exc:
        assert "bad.json" in str(exc)
    else:
        raise AssertionError("invalid run record was accepted")


def test_cli_runs_evaluate_stage(tmp_path, capsys):
    assert main(["run", "evaluate", "--work-dir", str(tmp_path)]) == 0
    result = json.loads(capsys.readouterr().out)
    assert result["status"] == "incomplete"
    assert (tmp_path / "evaluate" / "report.json").exists()
