"""Agent stage: run each saved question through Hermes and save a RunRecord.

The runner starts Hermes in one-shot mode, reads the stored session, and writes
artifacts/agent/runs/{run_id}.json. A failed attempt also leaves a record.
"""
from __future__ import annotations

DONE = True

import json
import os
import re
import shutil
import subprocess
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from pydantic import ValidationError

from ..config import ConfigurationError, Settings
from ..contracts import Contract, RunRecord, ToolCall

TOOLSET = "nemotron_challenge"
RUN_TIMEOUT_SECONDS = 300
MAX_TURNS = 12
CITATION = re.compile(r"\[(B):([^\]\s]+)\]|\[(W):([0-9]+@[0-9]+)\]")
SECRET_PATTERNS = (
    re.compile(r"authorization\s*[:=]", re.IGNORECASE),
    re.compile(r"bearer\s+[A-Za-z0-9._~+/=-]{8,}", re.IGNORECASE),
)


class Question(Contract):
    qid: str
    question: str
    entry_id: str | None = None
    image: str | None = None
    tools: bool = True


class SecretFound(RuntimeError):
    """The record holds key material. The runner must not write it."""


def repo_root() -> Path:
    return Path(__file__).resolve().parents[3]


def code_revision(root: Path) -> str:
    try:
        done = subprocess.run(["git", "rev-parse", "HEAD"], cwd=root, capture_output=True, text=True, timeout=10)
        return done.stdout.strip() if done.returncode == 0 and done.stdout.strip() else "unknown"
    except (OSError, subprocess.SubprocessError):
        return "unknown"


def hermes_bin() -> str:
    found = os.environ.get("HERMES_BIN") or shutil.which("hermes") or str(Path.home() / ".local" / "bin" / "hermes")
    if not Path(found).exists():
        raise ConfigurationError("Hermes is not installed. Follow docs/hermes.md.")
    return found


def hermes_version(binary: str, env: dict[str, str]) -> str:
    done = subprocess.run([binary, "--version"], capture_output=True, text=True, timeout=60, env=env)
    lines = done.stdout.strip().splitlines()
    return lines[0] if lines else "unknown"


def load_questions(path: Path) -> list[Question]:
    if not path.is_file():
        raise ConfigurationError(f"missing {path}. Write the question set first.")
    questions = []
    for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        if not line.strip():
            continue
        try:
            questions.append(Question.model_validate_json(line))
        except ValidationError as exc:
            raise ConfigurationError(f"{path}:{number} is not a valid question: {exc.error_count()} error(s)") from None
    ids = [q.qid for q in questions]
    if len(set(ids)) != len(ids):
        raise ConfigurationError("question IDs must be unique")
    return questions


def profile_home(root: Path, tools: bool) -> Path:
    """Tools-on runs use HERMES_HOME. Tools-off runs use a sibling profile. Its plugin registers no tools."""
    home = Path(os.environ.get("HERMES_HOME") or root / "data" / "hermes").resolve()
    if not (home / "config.yaml").is_file():
        raise ConfigurationError(f"{home} has no config.yaml. Follow docs/hermes.md.")
    if tools:
        if not (home / "plugins" / "nemotron-challenge").is_dir():
            raise ConfigurationError("the nemotron-challenge plugin is not in the profile. Follow docs/hermes.md.")
        return home
    plain = home.parent / f"{home.name}-notools"
    plain.mkdir(parents=True, exist_ok=True)
    if not (plain / "config.yaml").is_file():
        shutil.copy(home / "config.yaml", plain / "config.yaml")
    # The plugin stays in this profile for its trace hook. challenge_run.json sets "tools": false, so it registers no tools.
    shutil.copytree(home / "plugins" / "nemotron-challenge", plain / "plugins" / "nemotron-challenge", dirs_exist_ok=True)
    # Without this line the model writes calls to tools it does not have. It carries no answer policy.
    note = root / "integrations" / "hermes" / "SOUL.notools.md"
    if note.is_file():
        shutil.copy(note, plain / "SOUL.md")
    return plain


def parse_stream(stdout: str) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for line in stdout.splitlines():
        try:
            event = json.loads(line)
        except ValueError:
            continue
        if isinstance(event, dict) and event.get("type") == "result":
            result = event
    return result


def parse_quiet(stdout: str, stderr: str = "") -> dict[str, Any]:
    """`chat -Q` prints the answer on stdout and a `session_id: ID` line on stderr.

    The line may also appear in stdout, so the parser checks both and removes it from the answer.
    """
    pattern = re.compile(r"^session_id:\s*(\S+)\s*$", re.MULTILINE)
    found = pattern.search(stderr) or pattern.search(stdout)
    text = pattern.sub("", stdout).strip()
    return {"text": text, "session_id": found.group(1)} if found else {"text": text}


def export_session(binary: str, env: dict[str, str], session_id: str) -> dict[str, Any]:
    with tempfile.TemporaryDirectory() as tmp:
        target = Path(tmp) / "session.jsonl"
        done = subprocess.run([binary, "sessions", "export", str(target), "--session-id", session_id, "--redact"],
                              capture_output=True, text=True, timeout=60, env=env)
        if done.returncode != 0 or not target.is_file():
            raise RuntimeError("session export failed")
        return json.loads(target.read_text(encoding="utf-8").splitlines()[0])


def tool_calls_from(messages: list[dict[str, Any]]) -> list[ToolCall]:
    results = {m.get("tool_call_id"): m.get("content") or "" for m in messages if m.get("role") == "tool"}
    calls = []
    for message in messages:
        if message.get("role") != "assistant" or not message.get("tool_calls"):
            continue
        raw = message["tool_calls"]
        for call in json.loads(raw) if isinstance(raw, str) else raw:
            try:
                arguments = json.loads(call["function"]["arguments"] or "{}")
            except ValueError:
                arguments = {"unparsed": call["function"]["arguments"]}
            output = results.get(call["id"], "")
            error = None
            try:
                parsed = json.loads(output)
                if isinstance(parsed, dict) and parsed.get("error"):
                    error = str(parsed["error"])
            except ValueError:
                error = None if output else "no tool result"
            calls.append(ToolCall(name=call["function"]["name"], arguments=arguments, result=output, error=error))
    return calls


def citations_from(answer: str) -> list[dict[str, str]]:
    found, seen = [], set()
    for match in CITATION.finditer(answer):
        source, ident = ("Britannica", match.group(2)) if match.group(1) else ("Wikipedia", match.group(4))
        start = max(answer.rfind(".", 0, match.start()), answer.rfind("\n", 0, match.start())) + 1
        end = answer.find(".", match.end())
        sentence = " ".join(answer[start:end + 1 if end >= 0 else len(answer)].split())
        if (source, ident, sentence) not in seen:
            seen.add((source, ident, sentence))
            found.append({"source": source, "id": ident, "sentence": sentence})
    return found


def last_reply_model(trace: Path) -> tuple[str | None, str | None]:
    """Model ID and finish reason from the last provider reply, written by the plugin hook."""
    if not trace.is_file():
        return None, None
    rows = [json.loads(line) for line in trace.read_text(encoding="utf-8").splitlines() if line.strip()]
    rows = [row for row in rows if row.get("response_model")]
    return (rows[-1]["response_model"], rows[-1].get("finish_reason")) if rows else (None, None)


def check_no_secret(text: str, secrets: list[str]) -> None:
    if any(secret and secret in text for secret in secrets) or any(p.search(text) for p in SECRET_PATTERNS):
        raise SecretFound("key material found in the run record")


def attempt(question: Question, *, root: Path, work_dir: Path, binary: str, version: str, base_env: dict[str, str],
            revision: str, secrets: list[str]) -> tuple[RunRecord, str | None]:
    """Run one question. Return the record and the reply model ID, or None when no reply came."""
    started = datetime.now(timezone.utc)
    run_id = f"{started:%Y%m%dT%H%M%SZ}-{question.qid}"
    home = profile_home(root, question.tools)
    image_inputs = [question.image] if question.image else []
    notes = [f"qid={question.qid}"] + ([f"entry_id={question.entry_id}"] if question.entry_id else [])
    query = question.question + (f"\n\n(Entry in scope: {question.entry_id})" if question.entry_id else "")
    answer, finish, model, calls, problem = "", "error", None, [], None

    with tempfile.TemporaryDirectory() as tmp:
        trace, query_file = Path(tmp) / "trace.jsonl", Path(tmp) / "query.txt"
        query_file.write_text(query, encoding="utf-8")
        env = dict(base_env, HERMES_HOME=str(home), CHALLENGE_WORK_DIR=str(work_dir.resolve()),
                   CHALLENGE_REPO_ROOT=str(root), CHALLENGE_TRACE_FILE=str(trace))
        # The Hermes gateway keeps the environment of its first client, so the plugin reads this file too.
        (home / "challenge_run.json").write_text(json.dumps({
            "work_dir": str(work_dir.resolve()), "repo_root": str(root), "trace_file": str(trace),
            "tools": question.tools}), encoding="utf-8")
        toolsets = TOOLSET if question.tools else "context_engine"  # context_engine holds no tools
        if question.image:
            # The stream-json path refuses --image. The quiet path accepts it and prints the answer, then a session line.
            image = Path(question.image)
            command = [binary, "chat", "-Q", "--query-file", str(query_file), "--toolsets", toolsets,
                       "--max-turns", str(MAX_TURNS), "--image", str(image if image.is_absolute() else root / image)]
        else:
            command = [binary, "chat", "--oneshot", "--query-file", str(query_file), "--toolsets", toolsets,
                       "--format", "stream-json", "--max-turns", str(MAX_TURNS)]
        try:
            done = subprocess.run(command, capture_output=True, text=True, timeout=RUN_TIMEOUT_SECONDS, env=env, cwd=root)
            result = parse_quiet(done.stdout, done.stderr) if question.image else parse_stream(done.stdout)
            answer = (result.get("text") or "").strip()
            if done.returncode != 0 or result.get("error"):
                detail = result.get("error") or done.stderr.strip()[-300:] or "no error text"
                problem = f"hermes exit code {done.returncode}: {str(detail)[:300]}"
            session_id = result.get("session_id")
            if session_id:
                messages = export_session(binary, env, session_id).get("messages", [])
                calls = tool_calls_from(messages)
                replies = [m for m in messages if m.get("role") == "assistant"]
                if replies and replies[-1].get("finish_reason"):
                    finish = replies[-1]["finish_reason"]
            model, reply_finish = last_reply_model(trace)
            if finish == "error" and reply_finish:
                finish = reply_finish
            if not problem and not answer:
                problem = "empty reply"
        except subprocess.TimeoutExpired:
            problem = f"timeout after {RUN_TIMEOUT_SECONDS} seconds"
        except (OSError, RuntimeError, ValueError, KeyError, subprocess.SubprocessError) as exc:
            problem = f"{type(exc).__name__}: {str(exc)[:200]}"

    if problem:
        notes.append(f"FAILED: {problem}")
    if not model:
        notes.append("model ID missing: no provider reply was recorded")
    record = RunRecord(
        run_id=run_id, started_at=started.strftime("%Y-%m-%dT%H:%M:%SZ"), code_revision=revision,
        hermes_version=version, model=model or "unavailable", question=question.question,
        image_inputs=image_inputs, tools_enabled=question.tools, tool_calls=calls, answer=answer,
        citations=citations_from(answer), finish_reason=finish, notes="; ".join(notes),
    )
    try:
        check_no_secret(record.model_dump_json(), secrets)
    except SecretFound:
        record = record.model_copy(update={
            "tool_calls": [], "answer": "", "citations": [], "finish_reason": "error",
            "notes": "FAILED: key material found in the run record; content withheld",
        })
    return record, model


def run(settings: Settings, work_dir: Path) -> dict[str, Any]:
    root, work_dir = repo_root(), Path(work_dir)
    if not settings.super_api_key:
        raise ConfigurationError("set SUPER_API_KEY in .env")
    questions = load_questions(work_dir / "agent" / "questions.jsonl")
    only = {q for q in os.environ.get("CHALLENGE_AGENT_QIDS", "").split(",") if q}
    if only:
        questions = [q for q in questions if q.qid in only]
    binary = hermes_bin()
    base_env = dict(os.environ, SUPER_API_KEY=settings.super_api_key)
    version, revision = hermes_version(binary, base_env), code_revision(root)
    runs_dir = work_dir / "agent" / "runs"
    runs_dir.mkdir(parents=True, exist_ok=True)
    summary, models = [], set()
    for question in questions:
        record, model = attempt(question, root=root, work_dir=work_dir, binary=binary, version=version,
                                base_env=base_env, revision=revision, secrets=[settings.super_api_key])
        (runs_dir / f"{record.run_id}.json").write_text(record.model_dump_json(indent=2) + "\n", encoding="utf-8")
        if model:
            models.add(model)
        failed = "FAILED" in record.notes
        summary.append({"qid": question.qid, "run_id": record.run_id, "failed": failed})
    env_path = work_dir / "agent" / "env.json"
    previous = json.loads(env_path.read_text(encoding="utf-8")) if env_path.is_file() else {}
    env_path.write_text(json.dumps({
        "hermes_version": version, "code_revision": revision,
        "models_from_replies": sorted(set(previous.get("models_from_replies", [])) | models),
        "toolset": TOOLSET, "tools_off_toolset": "context_engine (profile without the plugin)",
    }, indent=2) + "\n", encoding="utf-8")
    return {"stage": "agent", "runs": summary, "failed": sum(1 for row in summary if row["failed"])}
