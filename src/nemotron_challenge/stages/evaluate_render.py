"""Render case studies and the evaluation summary as Markdown, following templates/case-study.md."""
from __future__ import annotations

from typing import Any

from ..contracts import CaseStudy, EvaluationReport, EvidenceCheck


def _mark(check: EvidenceCheck) -> str:
    if check.passed is None:
        return "not checked" if check.kind == "observation" else "noted"
    return "pass" if check.passed else "fail"


def _checks_table(checks: list[EvidenceCheck]) -> list[str]:
    lines = ["| Check | Kind | Result | Detail |", "| --- | --- | --- | --- |"]
    for check in checks:
        detail = check.detail.replace("|", "\\|")
        lines.append(f"| {check.name} | {check.kind} | {_mark(check)} | {detail} |")
    return lines


def _citations(case: CaseStudy) -> list[str]:
    if not case.citations:
        return ["No citations in the run record."]
    lines = []
    for citation in case.citations:
        source, cite_id, quote = citation.get("source", "?"), citation.get("id", "?"), citation.get("quote", "")
        lines.append(f"- {source} `{cite_id}`: \"{quote}\"")
    return lines


def render_case(case: CaseStudy) -> str:
    lines = [
        "# Case study",
        "",
        f"Case ID: {case.case_id}",
        f"Classification: {case.classification}",
        f"Run record: {case.run_path}",
        f"Code revision: {case.code_revision}",
        f"Model: {case.model}",
        f"Finish reason: {case.finish_reason}",
        "",
        "## Question",
        "",
        case.question,
        "",
        "## Evidence",
        "",
        "Citations in the run record:",
        "",
        *_citations(case),
        "",
        f"Tool calls: {case.tool_calls} recorded, {case.tool_errors} with errors. "
        f"The raw calls and model reply are in the run record.",
        "",
        "Evidence checks. Observations read the saved records. Inferences apply a rule and need review.",
        "",
        *_checks_table(case.checks),
        "",
        "## Result",
        "",
        "Agent answer:",
        "",
        f"> {case.answer}" if case.answer.strip() else "> (empty answer)",
        "",
        f"Classification source: {case.classification_source}.",
        f"Reviewer notes: {case.review_notes}" if case.review_notes else "Reviewer notes: none recorded.",
        "",
        _attempt_lines(case),
        "",
        "Limits: the checks confirm ids, quotes, and the model reply. They do not confirm the facts in the answer.",
        "",
    ]
    return "\n".join(lines)


def _attempt_lines(case: CaseStudy) -> str:
    parts = []
    if case.earlier_attempts:
        parts.append("Earlier attempts on the same question, kept as separate run records: "
                     + ", ".join(f"`{run_id}`" for run_id in case.earlier_attempts) + ".")
    else:
        parts.append("No earlier attempt on this question.")
    if case.repaired_by:
        parts.append(f"A later run `{case.repaired_by}` repaired this question. This record keeps the failed attempt.")
    return " ".join(parts)


def _bullets(value: Any, indent: int = 0) -> list[str]:
    pad = "  " * indent
    if not isinstance(value, dict):
        return [f"{pad}- {value}"]
    lines = []
    for key, item in value.items():
        if isinstance(item, dict):
            lines.append(f"{pad}- {key}:")
            lines += _bullets(item, indent + 1)
        elif isinstance(item, list):
            lines.append(f"{pad}- {key}: " + (", ".join(str(x) for x in item) or "none"))
        else:
            lines.append(f"{pad}- {key}: {item}")
    return lines


def render_summary(report: EvaluationReport) -> str:
    repro = report.reproduction
    lines = [
        "# Evaluation",
        "",
        f"Status: {report.status}",
        f"Generated: {report.generated_at}",
        f"Inputs: {report.inputs_dir}" + (" (fixture inputs, not real runs)" if report.fixture_inputs else ""),
        "",
        "## Case studies",
        "",
        "| Case | Classification | Run | Question |",
        "| --- | --- | --- | --- |",
    ]
    for case in report.cases:
        question = case.question.replace("|", "\\|")
        lines.append(f"| [{case.case_id}]({case.case_path}) | {case.classification} | `{case.run_id}` | {question} |")
    for label in ("success", "failure"):
        if report.missing.get(label, 0):
            lines.append(f"\nMissing {report.missing[label]} {label} case(s). Label more runs and rerun this stage.")
    if report.unreviewed_run_ids:
        lines += ["", "Unreviewed runs: " + ", ".join(f"`{run_id}`" for run_id in report.unreviewed_run_ids) + "."]
    lines += [
        "",
        "## Reproduce the run",
        "",
        "```sh",
        *repro.commands,
        "```",
        "",
        f"Code revision: `{repro.code_revision}` ({repro.code_revision_source}).",
        f"Working tree clean: {repro.working_tree_clean}.",
        f"Python: {repro.python_version}.",
        "Packages: " + ", ".join(f"{name} {version}" for name, version in repro.packages.items()) + ".",
        "",
        "| Role | Model | Revision |",
        "| --- | --- | --- |",
        f"| Page extraction | {repro.models['parse']['id']} | shared endpoint |",
        f"| Embedding | {repro.models['embed']['id']} | {repro.models['embed']['revision']} |",
        f"| Reranking | {repro.models['rerank']['id']} | {repro.models['rerank']['revision']} |",
        f"| Hermes reasoning | {repro.models['super']['id']} | Token Factory |",
        "",
        "Data revisions:",
        "",
        *_bullets(repro.data),
        "",
        "Retrieval service:",
        "",
        *_bullets(repro.models["retrieval_service"]),
        "",
        f"Hermes versions in runs: {', '.join(repro.hermes_versions) or 'none'}.",
        f"Super model ids in runs: {', '.join(repro.models['super_ids_in_runs']) or 'none'}.",
        "",
        "## Results",
        "",
        *_bullets(repro.counts),
        "",
        "## Limits",
        "",
        *[f"- {limit}" for limit in repro.known_limits],
        "",
    ]
    return "\n".join(lines)
