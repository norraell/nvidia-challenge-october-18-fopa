"""The Super VL check must name the real problem and never report a false pass."""
import json

import httpx
import pytest

from nemotron_challenge.config import ConfigurationError, SUPER_MODEL, Settings
from nemotron_challenge.super_check import check

PNG = bytes.fromhex(
    "89504e470d0a1a0a0000000d4948445200000001000000010804000000b51c0c020000000b4944415478da6364f80f00010501012718e3660000000049454e44ae426082"
)
KEY = "secret-test-key"
SETTINGS = Settings(super_base_url="https://chat.example/v1", super_api_key=KEY)


def chat(finish_reason="stop", content="READY", tool_calls=None):
    message = {"content": content}
    if tool_calls is not None:
        message["tool_calls"] = tool_calls
    return {"model": SUPER_MODEL, "usage": {"total_tokens": 9},
            "choices": [{"finish_reason": finish_reason, "message": message}]}


TOOL_REPLY = chat("tool_calls", None, [{"id": "call-1", "type": "function",
                                       "function": {"name": "lookup_entry", "arguments": '{"headword": "OPTICS"}'}}])


def service(*, catalog=None, catalog_status=200, text=None, tool=None, vision=None):
    """A fake Token Factory that answers each check by what the request contains."""
    def handle(request):
        assert request.headers["Authorization"] == f"Bearer {KEY}"
        if request.url.path.endswith("/models"):
            body = catalog if catalog is not None else {"data": [{"id": SUPER_MODEL}]}
            return httpx.Response(catalog_status, json=body)
        payload = json.loads(request.content)
        if "tools" in payload:
            return httpx.Response(200, json=tool or TOOL_REPLY)
        if isinstance(payload["messages"][0]["content"], list):
            return httpx.Response(200, json=vision or chat(content="ABACUS"))
        return httpx.Response(200, json=text or chat())
    return httpx.Client(transport=httpx.MockTransport(handle))


@pytest.fixture
def scan(tmp_path):
    path = tmp_path / "page-0001-000000000000.png"
    path.write_bytes(PNG)
    return path


def statuses(receipt):
    return {result["name"]: result["status"] for result in receipt["checks"]}


def run(http, scan, tmp_path):
    with http:
        return check(SETTINGS, scan=scan, receipt_dir=tmp_path / "runs", http=http)


def test_all_checks_pass_and_receipt_has_no_key(scan, tmp_path):
    receipt, path = run(service(), scan, tmp_path)
    assert receipt["passed"] is True
    assert statuses(receipt) == {"catalog": "pass", "text": "pass", "tool_call": "pass", "vision": "pass"}
    assert receipt["checks"][2]["arguments"] == {"headword": "OPTICS"}
    assert receipt["checks"][3]["excerpt"] == "ABACUS"
    assert KEY not in path.read_text(encoding="utf-8")


def test_rejected_key_stops_all_later_checks(scan, tmp_path):
    receipt, _ = run(service(catalog_status=401, catalog={"detail": "unauthorized"}), scan, tmp_path)
    assert receipt["passed"] is False
    assert statuses(receipt) == {"catalog": "fail", "text": "skipped", "tool_call": "skipped", "vision": "skipped"}
    assert "rejected the key" in receipt["checks"][0]["detail"]


def test_missing_model_is_reported(scan, tmp_path):
    receipt, _ = run(service(catalog={"data": [{"id": "some/other-model"}]}), scan, tmp_path)
    assert statuses(receipt)["catalog"] == "fail"
    assert "not in this account's model catalog" in receipt["checks"][0]["detail"]


def test_cut_off_reply_is_not_a_pass(scan, tmp_path):
    receipt, _ = run(service(text=chat("length", "REA")), scan, tmp_path)
    assert receipt["passed"] is False
    assert statuses(receipt)["text"] == "fail"
    assert "cut off" in receipt["checks"][1]["detail"]


def test_text_answer_instead_of_tool_call_fails(scan, tmp_path):
    receipt, _ = run(service(tool=chat(content="I would look up OPTICS.")), scan, tmp_path)
    assert receipt["passed"] is False
    assert statuses(receipt)["tool_call"] == "fail"
    assert "made no tool call" in receipt["checks"][2]["detail"]


def test_skipped_vision_still_passes(tmp_path):
    receipt, _ = run(service(), None, tmp_path)
    assert receipt["passed"] is True
    assert statuses(receipt)["vision"] == "skipped"


def test_empty_key_is_refused_before_any_request(tmp_path):
    with pytest.raises(ConfigurationError, match="SUPER_API_KEY"):
        check(Settings(super_api_key=""), scan=None, receipt_dir=tmp_path)
