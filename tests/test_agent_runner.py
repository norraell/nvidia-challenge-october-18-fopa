"""The agent stage records real tool calls and model replies. It never invents a result."""
import json
from pathlib import Path
import shutil

import pytest

from nemotron_challenge.agent.evidence import EvidenceStore
from nemotron_challenge.agent.runner import AgentRunner, Question, parse_citations
from nemotron_challenge.clients import ProtocolError, ServiceError
from nemotron_challenge.config import SUPER_MODEL
from nemotron_challenge.contracts import RunRecord
from nemotron_challenge.stages.agent import load_questions, run_questions, select_questions

FIXTURES = Path(__file__).parent / "fixtures" / "artifacts"


def tool_reply(name: str, arguments: dict, call_id: str = "call-1") -> dict:
    return {"model": SUPER_MODEL, "choices": [{"finish_reason": "tool_calls", "message": {
        "content": "", "tool_calls": [{"id": call_id, "type": "function", "function": {"name": name, "arguments": json.dumps(arguments)}}]}}]}


def text_reply(content: str, finish: str = "stop", model: str = SUPER_MODEL) -> dict:
    return {"model": model, "usage": {"total_tokens": 10}, "choices": [{"finish_reason": finish, "message": {"content": content}}]}


class FakeChat:
    def __init__(self, replies):
        self.replies, self.requests = list(replies), []

    def complete(self, messages, max_tokens, extra_body=None):
        self.requests.append({"messages": [dict(m) for m in messages], "max_tokens": max_tokens, "extra_body": extra_body})
        reply = self.replies.pop(0)
        if isinstance(reply, Exception):
            raise reply
        return reply


@pytest.fixture
def work_dir(tmp_path):
    shutil.copytree(FIXTURES, tmp_path / "artifacts")
    return tmp_path / "artifacts"


def test_parse_citations_splits_the_trailing_line():
    answer, citations, problem = parse_citations(
        'Britannica says X [B:e0013-01].\nCITATIONS: [{"source": "Britannica", "id": "e0013-01", "quote": "ABACUS, among the ancients"}]')
    assert answer == "Britannica says X [B:e0013-01]."
    assert citations == [{"source": "Britannica", "id": "e0013-01", "quote": "ABACUS, among the ancients"}]
    assert problem is None
    assert parse_citations("no line here") == ("no line here", [], "no CITATIONS line in the reply")
    assert parse_citations("x\nCITATIONS: [oops")[2].startswith("CITATIONS line is not valid JSON")


def test_runner_records_tool_calls_results_and_citations(work_dir):
    chat = FakeChat([
        tool_reply("challenge_find_entry", {"query": "abacus"}),
        tool_reply("challenge_compare", {"entry_id": "e0013-01"}, "call-2"),
        text_reply('Britannica calls it a table [B:e0013-01].\nCITATIONS: [{"source": "Britannica", "id": "e0013-01", "quote": "ABACUS, among the ancients"}]'),
    ])
    runner = AgentRunner(chat, EvidenceStore(work_dir), repo_dir=work_dir.parent, code_revision="abc", hermes_version="test")
    result = runner.run(Question("How does Britannica describe the abacus?", question_id="q1"), "run-x")
    record = result.record
    assert record is not None and record.model == SUPER_MODEL and record.finish_reason == "stop"
    assert [call.name for call in record.tool_calls] == ["challenge_find_entry", "challenge_compare"]
    assert all(call.error is None for call in record.tool_calls)
    assert json.loads(record.tool_calls[1].result)["status"] == "article_missing"  # fixture has no cached article text
    assert record.citations[0]["id"] == "e0013-01" and record.label == "unreviewed"
    assert record.answer == "Britannica calls it a table [B:e0013-01]."
    # The request carried the tools and the tool results went back as tool messages.
    assert chat.requests[0]["extra_body"]["tools"][0]["function"]["name"] == "challenge_find_entry"
    assert chat.requests[2]["messages"][-1]["role"] == "tool" and chat.requests[2]["messages"][-1]["tool_call_id"] == "call-2"
    assert len(result.raw["replies"]) == 3 and result.raw["citation_parse_problem"] is None


def test_runner_passes_a_tool_error_back_to_the_model_as_data(work_dir):
    chat = FakeChat([
        tool_reply("challenge_get_article", {"page_id": "999"}),
        text_reply("No evidence: the article is not in the saved run.\nCITATIONS: []"),
    ])
    runner = AgentRunner(chat, EvidenceStore(work_dir), repo_dir=work_dir.parent, code_revision="abc", hermes_version="test")
    record = runner.run(Question("Compare page 999."), "run-y").record
    assert record.tool_calls[0].error and "not a matched article" in record.tool_calls[0].error
    assert json.loads(chat.requests[1]["messages"][-1]["content"])["error"]
    assert record.citations == [] and record.answer.startswith("No evidence")


def test_runner_forces_an_answer_after_the_round_limit(work_dir):
    chat = FakeChat([tool_reply("challenge_find_entry", {"query": "abacus"}, f"c{i}") for i in range(2)]
                    + [text_reply("Stopped.\nCITATIONS: []")])
    runner = AgentRunner(chat, EvidenceStore(work_dir), repo_dir=work_dir.parent, code_revision="abc", hermes_version="t", max_rounds=2)
    record = runner.run(Question("Loop?"), "run-z").record
    assert len(record.tool_calls) == 2
    assert chat.requests[-1]["extra_body"]["tool_choice"] == "none"


def test_runner_attaches_the_crop_image_and_redacts_it_in_the_raw_record(work_dir):
    crop = work_dir / "extract" / "crops" / "e0013-01.png"
    crop.parent.mkdir(parents=True, exist_ok=True)
    crop.write_bytes(b"\x89PNG\r\n\x1a\n" + b"\x00" * 16)
    chat = FakeChat([text_reply("I see a scan.\nCITATIONS: []")])
    runner = AgentRunner(chat, EvidenceStore(work_dir), repo_dir=work_dir.parent, code_revision="abc", hermes_version="t")
    result = runner.run(Question("What is on this crop?", image="artifacts/extract/crops/e0013-01.png"), "run-img")
    content = chat.requests[0]["messages"][1]["content"]
    assert content[1]["image_url"]["url"].startswith("data:image/png;base64,")
    assert result.record.image_inputs == ["artifacts/extract/crops/e0013-01.png"]
    assert "base64," not in json.dumps(result.raw)


def test_stage_writes_run_raw_and_failed_records(work_dir, tmp_path):
    chat = FakeChat([
        text_reply('Answer one [B:e0013-01].\nCITATIONS: [{"source": "Britannica", "id": "e0013-01", "quote": "ABACUS"}]'),
        ServiceError("service returned HTTP 429", status_code=429),
        ProtocolError("chat response is incomplete; inspect the token budget and finish_reason"),
    ])
    questions = [Question("One?", question_id="q1"), Question("Two?", question_id="q2"), Question("Three?", question_id="q3")]
    summary = run_questions(questions, chat, EvidenceStore(work_dir), work_dir / "agent", repo_dir=tmp_path,
                            code_revision="deadbeef", hermes="Hermes test")
    assert summary["status"] == "partial" and len(summary["completed"]) == 1 and len(summary["failed"]) == 2
    runs = sorted(p for p in (work_dir / "agent" / "runs").glob("*.json") if p.name.startswith("run-2"))  # fixtures hold run-00x
    assert len(runs) == 1
    record = RunRecord.model_validate(json.loads(runs[0].read_text()))
    assert record.code_revision == "deadbeef" and record.hermes_version == "Hermes test" and record.label == "unreviewed"
    failed = sorted((work_dir / "agent" / "failed").glob("*.json"))
    assert len(failed) == 2 and "429" in json.loads(failed[0].read_text())["error"]
    assert len(list((work_dir / "agent" / "raw").glob("*.json"))) == 3
    assert json.loads((work_dir / "agent" / "summary.json").read_text())["questions"] == 3


def test_question_file_validation_and_selection(tmp_path):
    path = tmp_path / "questions.json"
    path.write_text(json.dumps([{"id": "a", "question": "A?"}, {"question": "B?", "image": "crop.png"}]))
    questions = load_questions(path)
    assert [q.question_id for q in questions] == ["a", "q02"] and questions[1].image == "crop.png"
    assert [q.question_id for q in select_questions(questions, {"AGENT_ONLY": "q02"})] == ["q02"]
    assert len(select_questions(questions, {"AGENT_LIMIT": "1"})) == 1
    path.write_text(json.dumps([{"question": ""}]))
    with pytest.raises(ValueError, match="question string"):
        load_questions(path)
