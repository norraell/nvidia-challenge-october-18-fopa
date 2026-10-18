"""Set the review label and note on a saved agent run.

Usage: uv run python scripts/label_runs.py <run_id> success|failure "why" [--runs-dir artifacts/agent/runs]
The stage never labels a run. A person reads the record and the sources, then records the decision here.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from nemotron_challenge.contracts import RunRecord  # noqa: E402


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("run_id")
    parser.add_argument("label", choices=["success", "failure", "unreviewed"])
    parser.add_argument("notes", nargs="?", default="")
    parser.add_argument("--runs-dir", type=Path, default=Path("artifacts/agent/runs"))
    args = parser.parse_args(argv)
    path = args.runs_dir / f"{args.run_id}.json"
    if not path.exists():
        print(f"Error: no run record at {path}", file=sys.stderr)
        return 1
    if args.label != "unreviewed" and not args.notes.strip():
        print("Error: give the reason for the label in the notes argument", file=sys.stderr)
        return 1
    record = RunRecord.model_validate(json.loads(path.read_text(encoding="utf-8")))
    updated = record.model_copy(update={"label": args.label, "notes": args.notes.strip()})
    path.write_text(updated.model_dump_json(indent=2), encoding="utf-8")
    print(f"{args.run_id}: {args.label}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
