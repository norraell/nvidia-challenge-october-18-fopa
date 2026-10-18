"""Evaluate: select three success and three failure cases from saved runs and record reproduction data."""
from __future__ import annotations

DONE = True

from datetime import datetime, timezone
import json
from pathlib import Path
import re
from typing import Any

from ..config import Settings
from ..contracts import (
    CaseStudy,
    DriftReport,
    EntryRecord,
    EvaluationReport,
    MatchRecord,
    PageRecord,
    RunRecord,
)
from .evaluate_checks import run_checks
from .evaluate_render import render_case, render_summary
from .evaluate_repro import build_reproduction

REQUIRED_PER_LABEL = 3
LABELS = ("success", "failure")
FIXTURES_DIR = Path(__file__).resolve().parents[3] / "tests" / "fixtures" / "artifacts"


def _load_jsonl(path: Path, model: type) -> list[Any]:
    if not path.exists():
        return []
    with path.open("r", encoding="utf-8") as handle:
        return [model.model_validate_json(line.strip()) for line in handle if line.strip()]


def load_runs(runs_dir: Path) -> list[tuple[Path, RunRecord]]:
    """Load every run record. A record that does not validate stops the stage with its path."""
    runs = []
    for path in sorted(runs_dir.glob("*.json")) if runs_dir.exists() else []:
        try:
            runs.append((path, RunRecord.model_validate(json.loads(path.read_text(encoding="utf-8")))))
        except ValueError as exc:
            raise ValueError(f"invalid run record {path}: {exc}") from exc
    return runs


def question_key(question: str) -> str:
    return re.sub(r"\s+", " ", question).strip().lower()


def attempt_chains(runs: list[RunRecord]) -> dict[str, tuple[list[str], str | None]]:
    """Per run_id: (earlier run_ids on the same question, later success run_id that repaired it)."""
    groups: dict[str, list[RunRecord]] = {}
    for run in sorted(runs, key=lambda r: (r.started_at, r.run_id)):
        groups.setdefault(question_key(run.question), []).append(run)
    chains: dict[str, tuple[list[str], str | None]] = {}
    for group in groups.values():
        for index, run in enumerate(group):
            earlier = [prior.run_id for prior in group[:index]]
            repaired_by = None
            if run.label == "failure":
                repaired_by = next((later.run_id for later in group[index + 1:] if later.label == "success"), None)
            chains[run.run_id] = (earlier, repaired_by)
    return chains


def select_runs(runs: list[RunRecord], label: str, limit: int = REQUIRED_PER_LABEL) -> list[RunRecord]:
    """Pick up to `limit` runs with the label. Distinct questions first, then earlier runs fill the rest."""
    ordered = sorted((run for run in runs if run.label == label), key=lambda r: (r.started_at, r.run_id))
    chosen: list[RunRecord] = []
    seen_questions: set[str] = set()
    for run in ordered:
        key = question_key(run.question)
        if key not in seen_questions:
            chosen.append(run)
            seen_questions.add(key)
        if len(chosen) == limit:
            return chosen
    for run in ordered:
        if len(chosen) == limit:
            break
        if run not in chosen:
            chosen.append(run)
    return chosen


def _display_path(path: Path) -> str:
    try:
        return str(path.resolve().relative_to(Path.cwd().resolve()))
    except ValueError:
        return str(path)


def build_case(*, case_id: str, run: RunRecord, run_path: Path, entries: list[EntryRecord],
               matches: list[MatchRecord], chain: tuple[list[str], str | None],
               articles_dir: Path | None = None) -> CaseStudy:
    earlier, repaired_by = chain
    assert run.label in LABELS
    return CaseStudy(
        case_id=case_id,
        classification=run.label,  # type: ignore[arg-type]
        classification_source="run.label (team review recorded in the run record)",
        run_id=run.run_id,
        run_path=_display_path(run_path),
        code_revision=run.code_revision,
        model=run.model,
        question=run.question,
        answer=run.answer,
        citations=list(run.citations),
        tool_calls=len(run.tool_calls),
        tool_errors=sum(1 for call in run.tool_calls if call.error),
        finish_reason=run.finish_reason,
        review_notes=run.notes,
        checks=run_checks(run, entries, matches, articles_dir),
        earlier_attempts=earlier,
        repaired_by=repaired_by,
        case_path=f"cases/{case_id}.md",
    )


def derived_limits(report_cases: list[CaseStudy], missing: dict[str, int], fixture_inputs: bool,
                   unreviewed: list[str]) -> list[str]:
    limits = []
    if fixture_inputs:
        limits.append("Inputs are starter fixtures. Rerun this stage after real agent runs exist in artifacts/agent/runs.")
    for label, count in missing.items():
        if count:
            limits.append(f"Only {REQUIRED_PER_LABEL - count} {label} case(s) found. {REQUIRED_PER_LABEL} are required.")
    if unreviewed:
        limits.append(f"{len(unreviewed)} run(s) have no review label and were not considered.")
    failed_checks = sorted({check.name for case in report_cases for check in case.checks if check.passed is False})
    if failed_checks:
        limits.append("Some selected cases fail evidence checks: " + ", ".join(failed_checks) + ". See each case study.")
    return limits


def evaluate(inputs_dir: Path, repo_dir: Path, fixture_inputs: bool) -> EvaluationReport:
    run_pairs = load_runs(inputs_dir / "agent" / "runs")
    runs = [run for _, run in run_pairs]
    paths = {run.run_id: path for path, run in run_pairs}
    entries = _load_jsonl(inputs_dir / "extract" / "entries.jsonl", EntryRecord)
    pages = _load_jsonl(inputs_dir / "extract" / "pages.jsonl", PageRecord)
    matches = _load_jsonl(inputs_dir / "match" / "matches.jsonl", MatchRecord)
    drift_path = inputs_dir / "compare" / "drift.json"
    drift = DriftReport.model_validate(json.loads(drift_path.read_text(encoding="utf-8"))) if drift_path.exists() else None

    chains = attempt_chains(runs)
    cases: list[CaseStudy] = []
    selected: dict[str, int] = {}
    for label in LABELS:
        picked = select_runs(runs, label)
        selected[label] = len(picked)
        for number, run in enumerate(picked, start=1):
            cases.append(build_case(case_id=f"case-{label}-{number}", run=run, run_path=paths[run.run_id],
                                    entries=entries, matches=matches, chain=chains[run.run_id],
                                    articles_dir=inputs_dir / "match" / "cache" / "articles"))
    missing = {label: REQUIRED_PER_LABEL - selected[label] for label in LABELS}
    unreviewed = sorted(run.run_id for run in runs if run.label == "unreviewed")
    chosen_ids = {case.run_id for case in cases}
    unselected = sorted(run.run_id for run in runs if run.label != "unreviewed" and run.run_id not in chosen_ids)
    limits = derived_limits(cases, missing, fixture_inputs, unreviewed)
    reproduction = build_reproduction(runs=runs, pages=pages, matches=matches, drift=drift,
                                      inputs_dir=inputs_dir, repo_dir=repo_dir, extra_limits=limits)
    return EvaluationReport(
        status="ok" if not any(missing.values()) else "incomplete",
        generated_at=datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z"),
        inputs_dir=_display_path(inputs_dir),
        fixture_inputs=fixture_inputs,
        required_per_label=REQUIRED_PER_LABEL,
        selected=selected,
        missing=missing,
        unreviewed_run_ids=unreviewed,
        unselected_run_ids=unselected,
        cases=cases,
        reproduction=reproduction,
    )


def write_report(report: EvaluationReport, out_dir: Path) -> None:
    (out_dir / "cases").mkdir(parents=True, exist_ok=True)
    (out_dir / "report.json").write_text(report.model_dump_json(indent=2), encoding="utf-8")
    (out_dir / "README.md").write_text(render_summary(report), encoding="utf-8")
    for case in report.cases:
        (out_dir / case.case_path).write_text(render_case(case), encoding="utf-8")


def run(settings: Settings, work_dir: Path) -> dict[str, Any]:
    """Read saved runs from work_dir (fixtures when none exist) and write artifacts/evaluate."""
    inputs_dir = work_dir
    fixture_inputs = False
    if not (work_dir / "agent" / "runs").exists() and (FIXTURES_DIR / "agent" / "runs").exists():
        inputs_dir, fixture_inputs = FIXTURES_DIR, True
    out_dir = work_dir / "evaluate"
    report = evaluate(inputs_dir, repo_dir=Path.cwd(), fixture_inputs=fixture_inputs)
    write_report(report, out_dir)
    return {
        "status": report.status,
        "fixture_inputs": fixture_inputs,
        "selected": report.selected,
        "missing": report.missing,
        "unreviewed_runs": len(report.unreviewed_run_ids),
        "code_revision": report.reproduction.code_revision,
        "report_json": str(out_dir / "report.json"),
        "summary_md": str(out_dir / "README.md"),
        "case_files": [str(out_dir / case.case_path) for case in report.cases],
    }
