"""Runner tests use a fake `hermes` executable. They use no network and no model."""
import json
import os
import stat
import sys
from pathlib import Path

import pytest

from nemotron_challenge.config import ConfigurationError, Settings
from nemotron_challenge.contracts import RunRecord
from nemotron_challenge.stages import agent

FAKE = '''#!{python}
import json, os, sys
args = sys.argv[1:]
mode = os.environ.get("FAKE_MODE", "ok")
if args[:1] == ["--version"]:
    print("Hermes Agent vTEST"); sys.exit(0)
if args[:2] == ["sessions", "export"]:
    out = args[2]
    tool_call = {{"id": "c1", "function": {{"name": "challenge_compare", "arguments": json.dumps({{"entry_id": "e0104-01"}})}}}}
    messages = [
        {{"role": "user", "content": "q"}},
        {{"role": "assistant", "tool_calls": [tool_call], "finish_reason": "tool_calls", "content": ""}},
        {{"role": "tool", "tool_call_id": "c1", "content": json.dumps({{"error": "revision mismatch", "evidence": "missing"}})}},
        {{"role": "assistant", "finish_reason": "stop", "content": "A. [B:e0104-01]"}},
    ]
    open(out, "w").write(json.dumps({{"id": "sess", "messages": messages}}) + "\\n"); sys.exit(0)
if mode == "timeout":
    import time; time.sleep(30)
if mode == "crash":
    print("boom", file=sys.stderr); sys.exit(1)
trace = os.environ["CHALLENGE_TRACE_FILE"]
if mode != "noreply":
    open(trace, "a").write(json.dumps({{"response_model": "nvidia/Nemotron-3.5-Super-VL", "finish_reason": "stop"}}) + "\\n")
text = {{"ok": "Britannica says X [B:e0104-01]. Wikipedia says Y [W:3845@12490182].",
        "empty": "", "leak": "key is " + os.environ["SUPER_API_KEY"], "noreply": "answer",
        "bearer": "Authorization: Bearer abcdefgh12345678"}}.get(mode, "answer")
if "-Q" in args:
    print(text); print("\\nsession_id: sess", file=sys.stderr); sys.exit(0)
print(json.dumps({{"type": "result", "session_id": "sess", "exit_code": 0, "text": text}}))
'''

KEY = "test-key-value-123456"


@pytest.fixture
def env(tmp_path, monkeypatch):
    fake = tmp_path / "hermes"
    fake.write_text(FAKE.format(python=sys.executable))
    fake.chmod(fake.stat().st_mode | stat.S_IEXEC)
    home = tmp_path / "data" / "hermes"
    (home / "plugins" / "nemotron-challenge").mkdir(parents=True)
    (home / "config.yaml").write_text("model: {}\n")
    work = tmp_path / "artifacts"
    (work / "agent").mkdir(parents=True)
    monkeypatch.setenv("HERMES_BIN", str(fake))
    monkeypatch.setenv("HERMES_HOME", str(home))
    monkeypatch.delenv("CHALLENGE_AGENT_QIDS", raising=False)
    return work


def write_questions(work: Path, *rows: dict):
    (work / "agent" / "questions.jsonl").write_text("\n".join(json.dumps(r) for r in rows) + "\n")


def settings() -> Settings:
    return Settings(super_api_key=KEY)


def runs(work: Path) -> list[RunRecord]:
    return [RunRecord.model_validate_json(p.read_text()) for p in sorted((work / "agent" / "runs").glob("*.json"))]


def test_successful_run_saves_a_full_record(env, monkeypatch):
    write_questions(env, {"qid": "s1", "question": "Compare barometer", "entry_id": "e0104-01", "tools": True})
    monkeypatch.setenv("FAKE_MODE", "ok")
    summary = agent.run(settings(), env)
    assert summary["failed"] == 0
    [record] = runs(env)
    assert record.model == "nvidia/Nemotron-3.5-Super-VL"  # From the reply hook, not from config.
    assert record.finish_reason == "stop" and record.tools_enabled is True
    assert record.hermes_version == "Hermes Agent vTEST"
    assert len(record.code_revision) == 40
    call = record.tool_calls[0]
    assert call.name == "challenge_compare" and call.arguments == {"entry_id": "e0104-01"}
    assert call.error == "revision mismatch"
    assert {c["id"] for c in record.citations} == {"e0104-01", "3845@12490182"}
    assert "qid=s1" in record.notes and "FAILED" not in record.notes
    assert record.label == "unreviewed"
    meta = json.loads((env / "agent" / "env.json").read_text())
    assert meta["models_from_replies"] == ["nvidia/Nemotron-3.5-Super-VL"]
    assert meta["hermes_version"] == "Hermes Agent vTEST"


@pytest.mark.parametrize("mode,fragment", [
    ("crash", "exit code 1"), ("empty", "empty reply"), ("noreply", "model ID missing"),
])
def test_failed_attempts_still_leave_a_record(env, monkeypatch, mode, fragment):
    write_questions(env, {"qid": "f1", "question": "Q", "tools": True})
    monkeypatch.setenv("FAKE_MODE", mode)
    summary = agent.run(settings(), env)
    [record] = runs(env)
    assert fragment in record.notes
    if mode != "noreply":
        assert summary["failed"] == 1 and "FAILED" in record.notes


def test_timeout_leaves_a_record(env, monkeypatch):
    write_questions(env, {"qid": "t1", "question": "Q"})
    monkeypatch.setenv("FAKE_MODE", "timeout")
    monkeypatch.setattr(agent, "RUN_TIMEOUT_SECONDS", 1)
    agent.run(settings(), env)
    [record] = runs(env)
    assert "timeout after 1 seconds" in record.notes and record.finish_reason == "error"
    assert record.answer == "" and record.model == "unavailable"


@pytest.mark.parametrize("mode", ["leak", "bearer"])
def test_run_with_key_material_is_withheld(env, monkeypatch, mode):
    write_questions(env, {"qid": "k1", "question": "Q"})
    monkeypatch.setenv("FAKE_MODE", mode)
    summary = agent.run(settings(), env)
    [record] = runs(env)
    text = (env / "agent" / "runs").glob("*.json").__next__().read_text()
    assert KEY not in text and "Bearer abcdefgh" not in text
    assert summary["failed"] == 1 and "key material" in record.notes
    assert record.answer == "" and record.tool_calls == []


def test_tools_off_uses_a_profile_without_the_plugin_and_an_empty_toolset(env, monkeypatch):
    write_questions(env, {"qid": "n1", "question": "Q", "tools": False})
    seen = {}
    real_run = agent.subprocess.run

    def spy(command, *args, **kwargs):
        if "chat" in command:
            seen["command"], seen["home"] = command, kwargs["env"]["HERMES_HOME"]
        return real_run(command, *args, **kwargs)

    monkeypatch.setattr(agent.subprocess, "run", spy)
    agent.run(settings(), env)
    assert seen["command"][seen["command"].index("--toolsets") + 1] == "context_engine"
    assert seen["home"].endswith("hermes-notools")
    assert not json.loads((Path(seen["home"]) / "challenge_run.json").read_text())["tools"]
    assert runs(env)[0].tools_enabled is False


def test_image_question_passes_image_and_records_it(env, monkeypatch, tmp_path):
    image = tmp_path / "crop.png"
    image.write_bytes(b"\x89PNG")
    write_questions(env, {"qid": "i1", "question": "Read the plate", "image": str(image)})
    seen = {}
    real_run = agent.subprocess.run

    def spy(command, *args, **kwargs):
        if "chat" in command:
            seen["command"] = command
        return real_run(command, *args, **kwargs)

    monkeypatch.setattr(agent.subprocess, "run", spy)
    agent.run(settings(), env)
    assert seen["command"][seen["command"].index("--image") + 1] == str(image)
    record = runs(env)[0]
    assert record.image_inputs == [str(image)]
    assert [call.name for call in record.tool_calls] == ["challenge_compare"]  # The session line is on stderr.


def test_question_file_errors(env):
    with pytest.raises(ConfigurationError, match="missing"):
        agent.run(settings(), env)
    write_questions(env, {"qid": "a", "question": "Q"}, {"qid": "a", "question": "R"})
    with pytest.raises(ConfigurationError, match="unique"):
        agent.run(settings(), env)
    write_questions(env, {"qid": "a", "question": "Q", "surprise": 1})
    with pytest.raises(ConfigurationError, match="not a valid question"):
        agent.run(settings(), env)
    with pytest.raises(ConfigurationError, match="SUPER_API_KEY"):
        agent.run(Settings(), env)


def test_missing_plugin_in_profile_is_a_clear_error(env, monkeypatch, tmp_path):
    write_questions(env, {"qid": "a", "question": "Q"})
    bare = tmp_path / "bare"
    bare.mkdir()
    (bare / "config.yaml").write_text("x: 1\n")
    monkeypatch.setenv("HERMES_HOME", str(bare))
    with pytest.raises(ConfigurationError, match="plugin"):
        agent.run(settings(), env)


def test_citation_and_tool_call_parsing():
    answer = "Old text [B:e0013-01]. New text [W:1024@11823901]. Inference: they differ."
    cites = agent.citations_from(answer)
    assert [(c["source"], c["id"]) for c in cites] == [("Britannica", "e0013-01"), ("Wikipedia", "1024@11823901")]
    assert cites[0]["sentence"] == "Old text [B:e0013-01]."
    assert agent.citations_from("No citation here.") == []
    assert agent.tool_calls_from([{"role": "assistant", "tool_calls": [
        {"id": "z", "function": {"name": "brit_entry", "arguments": "not json"}}]}])[0].error == "no tool result"


def test_secret_check_flags_key_and_authorization_header():
    for text in (f"x {KEY} y", "Authorization: Bearer abcdefgh1234", "authorization=abc"):
        with pytest.raises(agent.SecretFound):
            agent.check_no_secret(text, [KEY])
    agent.check_no_secret("A clean answer with no key.", [KEY])
