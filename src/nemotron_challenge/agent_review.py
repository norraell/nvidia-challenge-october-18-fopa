"""Check the agent question set and record the hand review of saved runs.

    uv run python -m nemotron_challenge.agent_review check
    uv run python -m nemotron_challenge.agent_review review RUN_ID --label failure --notes "why"

`check` reads artifacts/agent/questions.jsonl and compares it with the saved entries and matches.
`review` sets `label` and `notes` on one saved RunRecord. It changes no other field.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

from pydantic import ValidationError

from .config import ConfigurationError
from .contracts import EntryRecord, MatchRecord, RunRecord
from .stages.agent import SecretFound, check_no_secret, load_questions

MIN_QUESTIONS = 14
MIN_TOOL_PAIRS = 2


def _read_jsonl(path: Path, model):
    if not path.is_file():
        return None
    return [model.model_validate_json(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def check_questions(work_dir: Path, root: Path | None = None) -> list[str]:
    """Return one message per problem. An empty list means the question set passes."""
    root = root or Path.cwd()
    problems: list[str] = []
    try:
        questions = load_questions(work_dir / "agent" / "questions.jsonl")
    except ConfigurationError as exc:
        return [str(exc)]
    if len(questions) < MIN_QUESTIONS:
        problems.append(f"{len(questions)} questions. The set needs at least {MIN_QUESTIONS}.")

    try:
        entries = _read_jsonl(work_dir / "extract" / "entries.jsonl", EntryRecord)
        matches = _read_jsonl(work_dir / "match" / "matches.jsonl", MatchRecord)
    except ValidationError as exc:
        return problems + [f"saved entries or matches do not follow the contract: {exc.error_count()} error(s)"]
    if entries is None:
        problems.append("extract/entries.jsonl is missing. Entry IDs cannot be checked.")
    if matches is None:
        problems.append("match/matches.jsonl is missing. Match statuses cannot be checked.")
    by_entry = {entry.entry_id: entry for entry in entries or []}
    status = {match.entry_id: match.status for match in matches or []}

    for q in questions:
        if q.entry_id and entries is not None and q.entry_id not in by_entry:
            problems.append(f"{q.qid}: entry_id {q.entry_id} is not in extract/entries.jsonl")
        if q.image:
            path = Path(q.image)
            if not (path if path.is_absolute() else root / path).is_file():
                problems.append(f"{q.qid}: image {q.image} does not exist")

    if not any(q.image for q in questions):
        problems.append("no question has an image. The set needs at least one.")
    pairs = {(q.question, q.entry_id) for q in questions if q.tools} & {(q.question, q.entry_id) for q in questions if not q.tools}
    if len(pairs) < MIN_TOOL_PAIRS:
        problems.append(f"{len(pairs)} tools-on and tools-off pairs. The set needs at least {MIN_TOOL_PAIRS} pairs with the same question and entry_id.")

    scoped = [q.entry_id for q in questions if q.entry_id and q.tools]
    if matches is not None and not any(status.get(e) in {"rejected", "no_candidates"} for e in scoped):
        problems.append("no tools-on question targets an entry with status rejected or no_candidates.")
    if entries is not None and not any(by_entry[e].quality.get("low_quality") is True for e in scoped if e in by_entry):
        problems.append("no tools-on question targets an entry with low_quality=true.")
    if not any(q.entry_id is None for q in questions):
        problems.append("no question lacks an entry_id. Add one about a topic outside the scans.")
    return problems


def review_run(work_dir: Path, run_id: str, label: str, notes: str, repairs: str | None = None) -> RunRecord:
    """Set label and notes on a saved run. Append the review to the notes the runner wrote."""
    runs = work_dir / "agent" / "runs"
    path = runs / f"{run_id}.json"
    if not path.is_file():
        raise ConfigurationError(f"no saved run {path}")
    if label not in {"success", "failure"}:
        raise ConfigurationError("label must be success or failure")
    if not notes.strip():
        raise ConfigurationError("write notes that say whether the citations support the answer")
    if repairs and not (runs / f"{repairs}.json").is_file():
        raise ConfigurationError(f"repairs points to {repairs}, which is not a saved run")
    record = RunRecord.model_validate_json(path.read_text(encoding="utf-8"))
    parts = [record.notes, f"review: {notes.strip()}"] + ([f"repairs run_id={repairs}"] if repairs else [])
    updated = record.model_copy(update={"label": label, "notes": "; ".join(p for p in parts if p)})
    check_no_secret(updated.model_dump_json(), [os.environ.get("SUPER_API_KEY", "")])
    path.write_text(updated.model_dump_json(indent=2) + "\n", encoding="utf-8")
    return updated


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="agent_review")
    parser.add_argument("--work-dir", type=Path, default=Path("artifacts"))
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("check", help="check the question set")
    review = sub.add_parser("review", help="set label and notes on a saved run")
    review.add_argument("run_id")
    review.add_argument("--label", required=True, choices=["success", "failure"])
    review.add_argument("--notes", required=True)
    review.add_argument("--repairs", help="run_id of the earlier run that this run repairs")
    args = parser.parse_args(argv)
    try:
        if args.command == "check":
            problems = check_questions(args.work_dir)
            for problem in problems:
                print(f"- {problem}", file=sys.stderr)
            print(json.dumps({"ok": not problems, "problems": len(problems)}))
            return 1 if problems else 0
        record = review_run(args.work_dir, args.run_id, args.label, args.notes, args.repairs)
        print(json.dumps({"run_id": record.run_id, "label": record.label}))
        return 0
    except (ConfigurationError, SecretFound, ValidationError, OSError) as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
