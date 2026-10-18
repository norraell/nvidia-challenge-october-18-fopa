"""Agent stage: run saved questions through Super VL with the challenge tools and record each run.

Outputs under <work_dir>/agent/:
  questions.json        the team's question list (input; this stage reads it)
  runs/<run_id>.json    one RunRecord per completed reply, label "unreviewed" until the team reviews it
  raw/<run_id>.json     every model reply and the redacted request messages
  failed/<run_id>.json  a run whose model call failed, with the error and the tool calls made before it
  summary.json          counts and settings of the last stage run

Options are environment variables: AGENT_QUESTIONS (path, default <work_dir>/agent/questions.json),
AGENT_LIMIT (first N questions), AGENT_ONLY (comma-separated question ids), AGENT_MAX_ROUNDS (tool rounds, default 8).
Label runs afterwards with scripts/label_runs.py. The stage never sets success or failure.
"""
from __future__ import annotations

from datetime import datetime, timezone
import json
import os
from pathlib import Path
import shutil
import subprocess
from typing import Any

from ..agent.evidence import EvidenceStore
from ..agent.runner import MAX_ROUNDS, AgentRunner, Question
from ..clients import ChatClient
from ..config import ConfigurationError, Settings

QUESTION_FILE = "questions.json"


def _git_head(repo_dir: Path) -> str:
    try:
        result = subprocess.run(["git", "rev-parse", "HEAD"], cwd=repo_dir, capture_output=True, text=True, timeout=10, check=False)
    except (OSError, subprocess.SubprocessError):
        return "unknown"
    return result.stdout.strip() if result.returncode == 0 and result.stdout.strip() else "unknown"


def hermes_version() -> str:
    """The installed Hermes Agent version, or a plain statement that it is absent. Never invented."""
    executable = shutil.which("hermes")
    if executable is None:
        return "hermes-agent not installed; stage loop via ChatClient"
    try:
        result = subprocess.run([executable, "--version"], capture_output=True, text=True, timeout=30, check=False)
    except (OSError, subprocess.SubprocessError):
        return "hermes-agent present, version unreadable; stage loop via ChatClient"
    first = (result.stdout or result.stderr).strip().splitlines()
    return (first[0].strip() if first else "hermes-agent present, version unreadable") + "; stage loop via ChatClient"


def load_questions(path: Path) -> list[Question]:
    if not path.exists():
        raise ConfigurationError(f"no question list at {path}; write it or set AGENT_QUESTIONS")
    rows = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(rows, list) or not rows:
        raise ValueError(f"{path} must hold a non-empty JSON list of questions")
    questions = []
    for index, row in enumerate(rows):
        if not isinstance(row, dict) or not isinstance(row.get("question"), str) or not row["question"].strip():
            raise ValueError(f"{path} row {index} needs a question string")
        image = row.get("image")
        if image is not None and not isinstance(image, str):
            raise ValueError(f"{path} row {index}: image must be a path string")
        questions.append(Question(question=row["question"].strip(), image=image, question_id=str(row.get("id") or f"q{index + 1:02d}")))
    return questions


def select_questions(questions: list[Question], environ: dict[str, str] = os.environ) -> list[Question]:
    only = {q.strip() for q in environ.get("AGENT_ONLY", "").split(",") if q.strip()}
    if only:
        questions = [q for q in questions if q.question_id in only]
    limit = environ.get("AGENT_LIMIT", "").strip()
    return questions[: int(limit)] if limit else questions


def run_questions(questions: list[Question], chat: Any, store: EvidenceStore, out_dir: Path, *, repo_dir: Path,
                  code_revision: str, hermes: str, max_rounds: int = MAX_ROUNDS) -> dict[str, Any]:
    """Run each question and write the run, raw, and failed records. Returns the summary."""
    for name in ("runs", "raw", "failed"):
        (out_dir / name).mkdir(parents=True, exist_ok=True)
    runner = AgentRunner(chat, store, repo_dir=repo_dir, code_revision=code_revision, hermes_version=hermes, max_rounds=max_rounds)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    completed, failed = [], []
    for index, question in enumerate(questions, start=1):
        run_id = f"run-{stamp}-{question.question_id or index:>02}"
        result = runner.run(question, run_id)
        (out_dir / "raw" / f"{run_id}.json").write_text(json.dumps(result.raw, indent=2, ensure_ascii=False), encoding="utf-8")
        if result.record is None:
            failure = {"run_id": run_id, "question": question.question, "image": question.image, "error": result.error,
                       "tool_calls": [call.model_dump() for call in result.tool_calls], "raw_path": f"agent/raw/{run_id}.json"}
            (out_dir / "failed" / f"{run_id}.json").write_text(json.dumps(failure, indent=2, ensure_ascii=False), encoding="utf-8")
            failed.append({"run_id": run_id, "error": result.error})
            continue
        (out_dir / "runs" / f"{run_id}.json").write_text(result.record.model_dump_json(indent=2), encoding="utf-8")
        completed.append({"run_id": run_id, "model": result.record.model, "finish_reason": result.record.finish_reason,
                          "tool_calls": len(result.record.tool_calls),
                          "tool_errors": sum(1 for call in result.record.tool_calls if call.error),
                          "citations": len(result.record.citations)})
    summary = {
        "status": "ok" if not failed else ("failed" if not completed else "partial"),
        "questions": len(questions), "completed": completed, "failed": failed,
        "hermes_version": hermes, "code_revision": code_revision,
        "outputs": {"runs": str(out_dir / "runs"), "raw": str(out_dir / "raw"), "failed": str(out_dir / "failed")},
        "next": "review each run, then: uv run python scripts/label_runs.py <run_id> success|failure \"reason\"",
    }
    (out_dir / "summary.json").write_text(json.dumps(summary, indent=2, ensure_ascii=False), encoding="utf-8")
    return summary


def run(settings: Settings, work_dir: Path) -> dict[str, Any]:
    out_dir = work_dir / "agent"
    questions_path = Path(os.environ["AGENT_QUESTIONS"]) if os.environ.get("AGENT_QUESTIONS", "").strip() else out_dir / QUESTION_FILE
    questions = select_questions(load_questions(questions_path))
    if not questions:
        raise ValueError("AGENT_ONLY or AGENT_LIMIT selected no questions")
    if not settings.super_api_key:
        raise ConfigurationError("SUPER_API_KEY is empty. Put your Token Factory key in .env before you run agent.")
    store = EvidenceStore(work_dir)
    store.entries  # fail early when extract output is missing
    repo_dir = Path.cwd()
    max_rounds = int(os.environ.get("AGENT_MAX_ROUNDS", "").strip() or MAX_ROUNDS)
    with ChatClient(settings.super_base_url, settings.super_api_key, settings.super_model) as chat:
        chat.verify_model()
        summary = run_questions(questions, chat, store, out_dir, repo_dir=repo_dir, code_revision=_git_head(repo_dir),
                                hermes=hermes_version(), max_rounds=max_rounds)
    summary["questions_path"] = str(questions_path)
    return summary
