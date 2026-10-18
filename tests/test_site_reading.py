"""The Reading Check data lists only real numbers and only fixes that the hand-typed page confirms."""
import json

from nemotron_challenge.stages.site import reading_check


def write_jsonl(path, rows):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("".join(json.dumps(r) + "\n" for r in rows), encoding="utf-8")


def test_reading_check_keeps_only_gold_confirmed_fixes(tmp_path):
    extract = tmp_path / "extract"
    write_jsonl(extract / "pages.jsonl", [{"row_index": 251, "entry_ids": ["e0251-01"]}])
    write_jsonl(extract / "corrected.jsonl", [{"entry_id": "e0251-01", "kind": "continuation",
        "parse": "Calvinia and Sprayer. Of Canada and the house was big. Swivels be fault and",
        "faithful": "Calvinifm and Popery. Of Baden and the horse was big. Swivels or small and"}])
    (extract / "gold").mkdir()
    # Gold covers only the first sentence: "horse" disagrees (an over-correction), and the
    # last fixes fall outside the gold text, so common words like "or" and "small" are not confirmed.
    (extract / "gold" / "0251.txt").write_text("Calvinifm and Popery. Of Baden and the house was big.", encoding="utf-8")
    (extract / "coverage.json").write_text(json.dumps({"cer": {"status": "partial"}, "correction": {
        "model": "nvidia/Nemotron-3.5-Super-VL", "blocks_sent": 10, "blocks_with_fallback": 1,
        "fallback_reasons": {}, "meaning_check": {"median": 0.95, "threshold": 0.9},
        "gold": [{"row_index": 251, "cer_parse": 0.138, "cer_faithful": 0.073}]}}), encoding="utf-8")
    write_jsonl(tmp_path / "match" / "matches.jsonl", [{"status": "matched"}, {"status": "rejected"}])
    write_jsonl(tmp_path / "match" / "modern" / "matches.jsonl", [{"status": "matched"}, {"status": "matched"}])

    result = reading_check(tmp_path)
    assert [(f["parse"], f["super_vl"]) for f in result["verified_fixes"]] == [
        ("Calvinia", "Calvinifm"), ("Sprayer", "Popery"), ("Canada", "Baden")]
    assert result["matching"] == {"parse_text": {"matched": 1, "rejected": 1}, "modern_text": {"matched": 2}}
    assert result["correction"]["gold"][0]["cer_faithful"] == 0.073 and result["ablation"] is None


def test_reading_check_is_absent_without_extract_output(tmp_path):
    assert reading_check(tmp_path) is None
