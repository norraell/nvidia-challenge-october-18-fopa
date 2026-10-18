"""Report tables for plates, calibration, and ablation."""
import json

from nemotron_challenge.match.report import load_side_files, plate_image_table, render_markdown, build_report


def test_plate_table_picks_top_by_each_ranking():
    logs = [{"entry_id": "e0270-01", "plate_image": {"logits": [
        {"page_id": "1", "title": "Hydrostatics", "text_only": -4.0, "with_image": -2.2, "text_rank": 1, "image_rank": 1},
        {"page_id": "2", "title": "Muscular hydrostat", "text_only": -5.7, "with_image": -2.9, "text_rank": 2, "image_rank": 6}]}},
            {"entry_id": "e0374-01", "plate_image": {"skipped": "no candidates"}}]
    rows = plate_image_table(logs)
    assert len(rows) == 1 and rows[0]["same_top"] is True and rows[0]["mean_shift"] == 2.3


def test_side_files_and_markdown_sections(tmp_path):
    (tmp_path / "calibration.json").write_text(json.dumps({"labeled": 30, "labeled_top1_correct": 20,
                                                           "chosen": {"tau": -5.0, "delta": 0.5, "precision": 0.95, "recall": 0.8, "tp": 16, "fp": 1, "fn": 4}}))
    (tmp_path / "ablation.json").write_text(json.dumps({"methods": {"bm25_only": {"top1_correct": 5, "top1_accuracy": 0.167}}}))
    side = load_side_files(tmp_path / "dev")
    report = build_report([], [], failures=[], query_only_rescues=0, summary={}, logs=[], side_files=side)
    text = render_markdown(report)
    assert "## Calibration" in text and "tau=-5.0" in text and "| bm25_only | 5 | 0.167 |" in text
    assert "no plate was reranked" in text
