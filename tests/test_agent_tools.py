"""Agent evidence tools read saved artifacts only and report missing evidence as data."""
import hashlib
import json
from pathlib import Path
import shutil

import pytest

from nemotron_challenge.agent.evidence import EvidenceError, EvidenceStore
from nemotron_challenge.agent.tools import TOOL_NAMES, TOOL_SCHEMAS, call_tool, dispatch, openai_tools

FIXTURES = Path(__file__).parent / "fixtures" / "artifacts"
ARTICLE_TEXT = ("An abacus is a calculating tool used since ancient times. The abacus consists of a frame with rods "
                "and beads that slide along them. Modern users still learn the abacus in parts of Asia.")


@pytest.fixture
def work_dir(tmp_path):
    shutil.copytree(FIXTURES, tmp_path / "artifacts")
    work = tmp_path / "artifacts"
    (work / "match").mkdir(exist_ok=True)
    digest = hashlib.sha256(ARTICLE_TEXT.encode()).hexdigest()
    (work / "match" / "articles.jsonl").write_text(json.dumps({
        "page_id": "1024", "revision_id": "11823901", "title": "Abacus", "url": "https://en.wikipedia.org/wiki/Abacus",
        "text_sha256": digest, "total_chars": len(ARTICLE_TEXT)}) + "\n")
    cache = work / "match" / "cache" / "articles"
    cache.mkdir(parents=True)
    (cache / "1024.json").write_text(json.dumps({
        "page_id": "1024", "revision_id": "11823901", "title": "Abacus", "url": "https://en.wikipedia.org/wiki/Abacus",
        "provenance": {"dataset_revision": "417c267bb457fa645c22eb3b5c77764963194c70", "text_sha256": digest},
        "license": {"spdx": "CC-BY-SA-4.0"}, "text": ARTICLE_TEXT}))
    return work


def test_schemas_are_consistent_with_the_openai_wrapper_and_plugin_manifest():
    assert TOOL_NAMES == ("challenge_find_entry", "challenge_get_entry", "challenge_get_article", "challenge_compare")
    assert [tool["function"]["name"] for tool in openai_tools()] == list(TOOL_NAMES)
    manifest = (Path(__file__).parent.parent / "integrations" / "hermes" / "nemotron-challenge" / "plugin.yaml").read_text()
    for schema in TOOL_SCHEMAS:
        assert f"  - {schema['name']}" in manifest
        assert schema["parameters"]["additionalProperties"] is False


def test_find_entry_ranks_headword_hits_first(work_dir):
    result = call_tool(EvidenceStore(work_dir), "challenge_find_entry", {"query": "abacus"})
    assert result["count"] >= 1
    assert result["entries"][0]["entry_id"] == "e0013-01"
    assert result["entries"][0]["match_status"] == "matched"
    assert result["entries"][0]["matched_title"] == "Abacus"


def test_find_entry_without_a_hit_says_so_instead_of_guessing(work_dir):
    result = call_tool(EvidenceStore(work_dir), "challenge_find_entry", {"query": "zeppelin"})
    assert result["count"] == 0 and "no saved entry" in result["note"]


def test_get_entry_returns_text_page_and_match_evidence(work_dir):
    result = call_tool(EvidenceStore(work_dir), "challenge_get_entry", {"entry_id": "e0013-01"})
    assert result["citation_id"] == "e0013-01"
    assert result["text"].startswith("ABACUS")
    assert result["match"]["status"] == "matched"
    assert result["match"]["match"]["citation_id"] == "1024@11823901"
    assert result["match"]["top_candidates"][0]["title"] == "Abacus"


def test_get_article_verifies_the_cached_text_against_the_match_index(work_dir):
    store = EvidenceStore(work_dir)
    result = call_tool(store, "challenge_get_article", {"page_id": "1024", "max_chars": 40})
    assert result["citation_id"] == "1024@11823901" and result["returned_chars"] == 40 and result["next_offset"] == 40
    assert result["license"] == "CC-BY-SA-4.0"
    (work_dir / "match" / "cache" / "articles" / "1024.json").write_text(json.dumps({
        "page_id": "1024", "revision_id": "11823901", "title": "Abacus", "url": "u", "provenance": {"text_sha256": "0" * 64},
        "text": "tampered"}))
    with pytest.raises(EvidenceError, match="differs"):
        call_tool(EvidenceStore(work_dir), "challenge_get_article", {"page_id": "1024"})


def test_get_article_rejects_pages_outside_the_saved_match_run(work_dir):
    with pytest.raises(EvidenceError, match="not a matched article"):
        call_tool(EvidenceStore(work_dir), "challenge_get_article", {"page_id": "99"})


def test_compare_returns_both_texts_and_term_contrast(work_dir):
    result = call_tool(EvidenceStore(work_dir), "challenge_compare", {"entry_id": "e0013-01"})
    assert result["status"] == "compared"
    assert result["article"]["citation_id"] == "1024@11823901"
    terms = result["terms"]
    assert any(row["term"] == "abacus" for row in terms["shared"])
    wiki_only = {row["term"] for row in terms["wikipedia_only_or_more"]}
    assert "beads" in wiki_only
    bead_row = next(row for row in terms["wikipedia_only_or_more"] if row["term"] == "beads")
    assert "beads" in bead_row["quote"] and bead_row["quote_source"] == "1024@11823901"


def test_compare_without_a_match_reports_missing_evidence(work_dir):
    result = call_tool(EvidenceStore(work_dir), "challenge_compare", {"entry_id": "e0115-01"})
    assert result["status"] == "no_match"
    assert "article" not in result
    assert result["match"]["status"] == "rejected"


def test_dispatch_turns_errors_into_json_for_the_model(work_dir):
    store = EvidenceStore(work_dir)
    text, error = dispatch(store, "challenge_get_entry", {"entry_id": "not-an-id"})
    assert json.loads(text)["error"] == error and "e0013-01" in error
    text, error = dispatch(store, "challenge_fly", {})
    assert "unknown tool" in error
    text, error = dispatch(store, "challenge_get_entry", {"entry_id": "e0013-01", "max_chars": "ten"})
    assert "integer" in error
    text, error = dispatch(store, "challenge_get_entry", {"entry_id": "e0013-01"})
    assert error is None and json.loads(text)["entry_id"] == "e0013-01"


def test_store_without_extract_output_names_the_missing_file(tmp_path):
    with pytest.raises(EvidenceError, match="run extract first"):
        EvidenceStore(tmp_path).entries


def test_hermes_plugin_registers_every_tool_and_reads_the_work_dir(work_dir, monkeypatch):
    import importlib.util

    plugin_path = Path(__file__).parent.parent / "integrations" / "hermes" / "nemotron-challenge" / "__init__.py"
    spec = importlib.util.spec_from_file_location("nemotron_challenge_plugin", plugin_path)
    plugin = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(plugin)
    monkeypatch.setenv("NEMOTRON_CHALLENGE_ROOT", str(Path(__file__).parent.parent))
    monkeypatch.setenv("NEMOTRON_CHALLENGE_WORK_DIR", str(work_dir))
    plugin._STORE = None

    registered = {}

    class Ctx:
        def register_tool(self, name, toolset, schema, handler, **kwargs):
            registered[name] = (toolset, schema, handler)

    plugin.register(Ctx())
    assert set(registered) == set(TOOL_NAMES)
    assert all(toolset == "nemotron_challenge" for toolset, _, _ in registered.values())
    reply = json.loads(registered["challenge_compare"][2]({"entry_id": "e0013-01"}))
    assert reply["status"] == "compared"
    assert json.loads(registered["challenge_get_entry"][2]({"entry_id": "bad"}))["error"]
