"""Offline setup, stage listing, and storage contracts."""
from dataclasses import replace
import json

import httpx
import pytest

from nemotron_challenge.cli import doctor, main
from nemotron_challenge.config import ConfigurationError, Settings
from nemotron_challenge.contracts import ArtifactRecord, SourceReference
from nemotron_challenge.storage import LanceArtifactStore


def test_offline_doctor_needs_no_secrets_or_network(monkeypatch, capsys):
    monkeypatch.setattr(httpx.Client, "send", lambda *args, **kwargs: pytest.fail("offline doctor started a request"))
    for key in ("SUPER_API_KEY", "RETRIEVAL_BASE_URL", "PARSE_API_KEY"):
        monkeypatch.delenv(key, raising=False)
    assert main(["doctor", "--offline"]) == 0
    data = json.loads(capsys.readouterr().out)
    assert data["inference"] == "not tested"
    assert data["challenge_stages"] == "see `nemotron-challenge stages`"
    assert all(row["status"] == "not_tested" for row in data["checks"] if "configured" in row)


def test_live_doctor_reports_missing_resources(monkeypatch):
    settings = Settings(wikipedia_api_url="", parse_base_url="", retrieval_base_url="", super_api_key="")
    monkeypatch.setattr(httpx.Client, "send", lambda *args, **kwargs: pytest.fail("missing config started a request"))
    report, code = doctor(settings, live=True)
    assert code == 1
    assert {check["name"] for check in report["checks"] if check["status"] == "missing"} == {"wikipedia", "parse", "retrieval", "super"}
    assert report["inference"] == "not tested"


def test_agent_stage_without_questions_fails_before_any_model_call(tmp_path, capsys, monkeypatch):
    monkeypatch.setattr(httpx.Client, "send", lambda *args, **kwargs: pytest.fail("agent stage started a request"))
    monkeypatch.delenv("AGENT_QUESTIONS", raising=False)
    path = tmp_path / "team-artifacts"
    assert main(["run", "agent", "--work-dir", str(path)]) == 1
    assert "questions.json" in capsys.readouterr().err
    assert not path.exists()


def test_agent_stage_without_super_key_fails_before_any_model_call(tmp_path, capsys, monkeypatch):
    monkeypatch.setattr(httpx.Client, "send", lambda *args, **kwargs: pytest.fail("agent stage started a request"))
    monkeypatch.setenv("SUPER_API_KEY", "")
    questions = tmp_path / "q.json"
    questions.write_text(json.dumps([{"id": "q1", "question": "Compare the abacus."}]))
    monkeypatch.setenv("AGENT_QUESTIONS", str(questions))
    assert main(["run", "agent", "--work-dir", str(tmp_path / "work")]) == 1
    assert "SUPER_API_KEY" in capsys.readouterr().err


def test_stages_list_names_every_stage_with_its_command(capsys):
    assert main(["stages"]) == 0
    rows = json.loads(capsys.readouterr().out)
    assert [row["stage"] for row in rows] == ["extract", "match", "compare", "agent", "site", "evaluate"]
    assert all(row["status"] == "implemented" and row["command"].endswith(row["stage"]) for row in rows)


def test_keys_are_not_exposed_by_settings_repr():
    settings = Settings(parse_api_key="parse-secret", retrieval_api_key="retrieval-secret", super_api_key="super-secret")
    assert "secret" not in repr(settings)


@pytest.mark.parametrize("name,value", [("PARSE_MODEL", "old-parse"), ("SUPER_MODEL", "other-model"), ("SUPER_BASE_URL", "https://user:key@example.com/v1")])
def test_wrong_models_or_url_credentials_are_rejected(monkeypatch, name, value):
    monkeypatch.setenv(name, value)
    with pytest.raises(ConfigurationError):
        Settings.from_env(None)


def test_provenance_store_persists_upserts_and_quotes_ids(tmp_path):
    source = SourceReference(dataset="synthetic-fixture", dataset_revision="v1", source_id="source-1",
                             source_url="https://example.com/fixture", content_sha256="a" * 64, license="CC0-1.0")
    record = ArtifactRecord(record_id="team's-record", stage="extract", sources=[source], artifact_path="artifacts/raw.json")
    store = LanceArtifactStore(tmp_path / "team.lancedb")
    store.put(record)
    assert store.get(record.record_id) == record
    changed = record.model_copy(update={"artifact_path": "artifacts/reviewed.json"})
    store.put(changed)
    reopened = LanceArtifactStore(tmp_path / "team.lancedb")
    assert reopened.get(record.record_id) == changed
    assert reopened.get("' OR 1=1 --") is None
    assert reopened.table.count_rows() == 1
