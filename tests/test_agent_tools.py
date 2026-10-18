"""Tool handler tests on the #1 fixtures. They use no network and no model."""
import importlib.util
import json
import shutil
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
PLUGIN = ROOT / "integrations" / "hermes" / "nemotron-challenge"
FIXTURES = Path(__file__).parent / "fixtures" / "artifacts"


@pytest.fixture(scope="module")
def plugin():
    spec = importlib.util.spec_from_file_location(
        "nemotron_challenge_plugin", PLUGIN / "__init__.py", submodule_search_locations=[str(PLUGIN)])
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module  # The plugin imports its sibling schemas module.
    spec.loader.exec_module(module)
    yield module
    sys.modules.pop(spec.name, None)


@pytest.fixture
def work(tmp_path, monkeypatch):
    shutil.copytree(FIXTURES, tmp_path, dirs_exist_ok=True)
    monkeypatch.setenv("CHALLENGE_WORK_DIR", str(tmp_path))
    monkeypatch.setenv("CHALLENGE_REPO_ROOT", str(ROOT))
    monkeypatch.delenv("RETRIEVAL_BASE_URL", raising=False)
    monkeypatch.setenv("WIKIPEDIA_API_URL", "http://127.0.0.1:9")  # Refuses connections at once.
    return tmp_path


def cache_article(work: Path, page_id: str, revision_id: str, text: str = "A barometer measures air pressure. " * 100):
    folder = work / "match" / "cache"
    folder.mkdir(parents=True, exist_ok=True)
    (folder / f"{page_id}.json").write_text(json.dumps({
        "page_id": page_id, "revision_id": revision_id, "title": "Barometer",
        "url": "https://en.wikipedia.org/wiki/Barometer", "text": text}))


def call(handler, **params):
    raw = handler(params)
    assert isinstance(raw, str)
    return json.loads(raw)


def edit_margin(work: Path, entry_id: str, margin: float):
    path = work / "match" / "matches.jsonl"
    rows = [json.loads(line) for line in path.read_text().splitlines()]
    for row in rows:
        if row["entry_id"] == entry_id:
            row["rerank_margin"] = margin
    path.write_text("\n".join(json.dumps(r) for r in rows) + "\n")


def test_manifest_and_registration_agree(plugin):
    import re
    declared = re.findall(r"^  - (\w+)$", (PLUGIN / "plugin.yaml").read_text().split("provides_hooks")[0], re.M)
    registered = []

    class Ctx:
        def register_tool(self, name, **kwargs):
            registered.append(name)
            assert kwargs["handler"] and kwargs["schema"]["name"] == name

        def register_hook(self, *args):
            pass

    plugin.register(Ctx())
    assert sorted(declared) == sorted(registered) == sorted(
        ["brit_search", "brit_entry", "wiki_article", "challenge_compare"])


def test_brit_search_falls_back_to_keyword_and_says_so(plugin, work):
    result = call(plugin.handle_brit_search, query="barometer pressure", k=3)
    assert result["method"] == "keyword"
    assert "keyword match ran" in result["note"]
    assert result["entries"][0]["entry_id"] == "e0104-01"
    first = result["entries"][0]
    assert set(first) >= {"entry_id", "headword", "page_id", "text_start", "quality"}
    assert len(first["text_start"]) <= 300


def test_brit_search_rejects_bad_input_and_empty_result(plugin, work):
    assert call(plugin.handle_brit_search, query="x" * 501)["evidence"] == "missing"
    assert "k must be" in call(plugin.handle_brit_search, query="abacus", k=11)["error"]
    assert call(plugin.handle_brit_search, query="")["evidence"] == "missing"
    none = call(plugin.handle_brit_search, query="locomotive railway engine")
    assert none["evidence"] == "missing" and "no Britannica entry" in none["error"]


def test_brit_entry_returns_full_record(plugin, work):
    result = call(plugin.handle_brit_entry, entry_id="e0013-01")
    assert result["headword"] == "ABACUS"
    assert "deſk" in result["text_raw"] and "desk" in result["text"]
    assert result["blocks"][0]["cls"] == "Text"
    assert result["crop_path"] == "artifacts/extract/crops/e0013-01.png"
    assert result["source"]["dataset_revision"] == "309f765b1ecc83e0a7f7762e44b4a927a7555443"
    assert result["source"]["edition"] is None  # The manifest has no edition field.


def test_brit_entry_errors(plugin, work):
    missing = call(plugin.handle_brit_entry, entry_id="e9999-01")
    assert missing == {"error": "no Britannica entry with id e9999-01", "evidence": "missing"}
    assert call(plugin.handle_brit_entry, entry_id="../etc")["evidence"] == "missing"
    assert call(plugin.handle_brit_entry)["evidence"] == "missing"


def test_handler_never_raises_on_missing_artifacts(plugin, tmp_path, monkeypatch):
    monkeypatch.setenv("CHALLENGE_WORK_DIR", str(tmp_path / "empty"))
    monkeypatch.setenv("CHALLENGE_REPO_ROOT", str(ROOT))
    result = call(plugin.handle_brit_entry, entry_id="e0013-01")
    assert result["evidence"] == "missing" and "missing artifact" in result["error"]
    assert json.loads(plugin.handle_compare("not a dict"))["evidence"] == "missing"


def test_wiki_article_reads_cache_with_pagination(plugin, work):
    cache_article(work, "3845", "12490182", "x" * 9000)
    first = call(plugin.handle_wiki_article, page_id="3845")
    assert first["revision_id"] == "12490182" and first["source"] == "cache"
    assert first["url"].endswith("/Barometer")
    assert len(first["text"]) == 6000 and first["next_offset"] == 6000
    last = call(plugin.handle_wiki_article, page_id="3845", offset=first["next_offset"])
    assert len(last["text"]) == 3000 and last["next_offset"] is None


def test_wiki_article_rejects_revision_mismatch(plugin, work):
    cache_article(work, "3845", "99999999")
    result = call(plugin.handle_wiki_article, page_id="3845")
    assert result["evidence"] == "missing"
    assert "revision mismatch" in result["error"]
    assert result["expected_revision_id"] == "12490182" and result["found_revision_id"] == "99999999"
    assert "text" not in result


def test_wiki_article_unreachable_source_is_an_error_not_a_crash(plugin, work):
    result = call(plugin.handle_wiki_article, page_id="3845")
    assert result["evidence"] == "missing" and "unavailable" in result["error"]
    assert call(plugin.handle_wiki_article, page_id="abc")["evidence"] == "missing"
    assert call(plugin.handle_wiki_article, page_id="3845", offset=-1)["evidence"] == "missing"


def test_compare_matched_entry_returns_both_sides_and_shared_terms(plugin, work):
    cache_article(work, "3845", "12490182")
    result = call(plugin.handle_compare, entry_id="e0104-01")
    assert result["match_record"]["status"] == "matched"
    assert result["match_record"]["rerank_margin"] == 1.2
    assert "match_uncertain" not in result
    assert result["wikipedia"]["revision_id"] == "12490182"
    assert len(result["wikipedia"]["text_start"]) <= 1500
    assert len(result["britannica"]["text_start"]) <= 1500
    terms = {t["term"]: t for t in result["shared_terms"]}
    assert set(terms) == {"quicksilver", "atmosphere"}
    assert terms["quicksilver"]["brit_quote"]["quote"] == "constructed with a column of quicksilver"
    assert terms["quicksilver"]["wiki_quote"]["revision_id"] == "12490182"


def test_compare_rejected_entry_reports_missing_wikipedia(plugin, work):
    result = call(plugin.handle_compare, entry_id="e0115-01")
    assert result["match_record"]["status"] == "rejected"
    assert "rejected" in result["match_uncertain"]
    assert result["wikipedia"] is None and result["evidence"] == "missing"
    assert "no accepted match" in result["missing"]
    assert result["britannica"]["text_start"].startswith("CALORIC")


def test_compare_no_candidates(plugin, work):
    result = call(plugin.handle_compare, entry_id="e0013-02")
    assert result["match_record"]["status"] == "no_candidates"
    assert result["wikipedia"] is None and result["evidence"] == "missing"


def test_compare_flags_margin_below_delta(plugin, work):
    cache_article(work, "1024", "11823901")
    edit_margin(work, "e0013-01", 0.3)  # delta is 0.4 in the fixture method_version
    result = call(plugin.handle_compare, entry_id="e0013-01")
    assert result["match_record"]["status"] == "matched"
    assert "below delta 0.4" in result["match_uncertain"]


def test_compare_missing_entry_and_revision_mismatch(plugin, work):
    assert call(plugin.handle_compare, entry_id="e9999-01")["evidence"] == "missing"
    cache_article(work, "3845", "1")
    result = call(plugin.handle_compare, entry_id="e0104-01")
    assert result["evidence"] == "missing" and "revision mismatch" in result["error"]


def test_trace_hook_writes_model_id_from_reply(plugin, tmp_path, monkeypatch):
    trace = tmp_path / "trace.jsonl"
    monkeypatch.setenv("CHALLENGE_TRACE_FILE", str(trace))
    plugin._trace_reply(session_id="s", response_model="nvidia/Nemotron-3.5-Super-VL",
                        finish_reason="stop", api_call_count=1, ignored="x")
    row = json.loads(trace.read_text())
    assert row["response_model"] == "nvidia/Nemotron-3.5-Super-VL" and "ignored" not in row
