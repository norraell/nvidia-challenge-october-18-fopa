"""Question-set check and run review tests. They use no network and no model."""
import json
import shutil
from pathlib import Path

import pytest

from nemotron_challenge.agent_review import check_questions, main, review_run
from nemotron_challenge.config import ConfigurationError
from nemotron_challenge.contracts import RunRecord
from nemotron_challenge.stages.agent import SecretFound

FIXTURES = Path(__file__).parent / "fixtures" / "artifacts"


@pytest.fixture
def work(tmp_path):
    shutil.copytree(FIXTURES, tmp_path, dirs_exist_ok=True)
    entries = tmp_path / "extract" / "entries.jsonl"
    rows = [json.loads(line) for line in entries.read_text().splitlines()]
    rows[-1]["quality"]["low_quality"] = True  # The fixtures hold no low-quality entry.
    entries.write_text("\n".join(json.dumps(r) for r in rows) + "\n")
    (tmp_path / "agent").mkdir(exist_ok=True)
    return tmp_path


def write(work: Path, rows: list[dict]):
    (work / "agent" / "questions.jsonl").write_text("\n".join(json.dumps(r) for r in rows) + "\n")


def good_set(image: Path) -> list[dict]:
    rows = [{"qid": f"q{i}", "question": f"Question {i}", "entry_id": "e0013-01", "tools": True} for i in range(10)]
    rows += [
        {"qid": "p-on", "question": "Same question", "entry_id": "e0104-01", "tools": True},
        {"qid": "p-off", "question": "Same question", "entry_id": "e0104-01", "tools": False},
        {"qid": "p2-on", "question": "Other question", "entry_id": "e0104-01", "tools": True},
        {"qid": "p2-off", "question": "Other question", "entry_id": "e0104-01", "tools": False},
        {"qid": "rej", "question": "Rejected entry", "entry_id": "e0115-01", "tools": True},
        {"qid": "img", "question": "Read the plate", "entry_id": "e0104-02", "image": str(image), "tools": True},
        {"qid": "none", "question": "Topic outside the scans", "tools": True},
    ]
    return rows


@pytest.fixture
def image(tmp_path_factory):
    path = tmp_path_factory.mktemp("img") / "plate.png"
    path.write_bytes(b"\x89PNG")
    return path


def test_complete_question_set_passes(work, image):
    rows = good_set(image)
    rows[0]["entry_id"] = "e0115-01"  # Placeholder so the low-quality entry is in scope below.
    rows[1]["entry_id"] = "e0115-01"
    write(work, rows)
    assert check_questions(work) == []


def test_each_missing_requirement_is_named(work, image):
    write(work, [{"qid": "a", "question": "Q", "entry_id": "ghost"}])
    text = "\n".join(check_questions(work))
    assert "1 questions" in text and "ghost is not in extract/entries.jsonl" in text
    assert "no question has an image" in text and "0 tools-on and tools-off pairs" in text
    assert "rejected or no_candidates" in text and "low_quality=true" in text
    assert "no question lacks an entry_id" in text


def test_missing_image_file_is_named(work):
    rows = good_set(Path("/nonexistent/plate.png"))
    write(work, rows)
    assert any("img: image /nonexistent/plate.png does not exist" in p for p in check_questions(work))


def test_pair_needs_the_same_question_and_entry(work, image):
    rows = good_set(image)
    rows[-5]["question"] = "A different question"  # p-off no longer matches p-on.
    write(work, rows)
    assert any("1 tools-on and tools-off pairs" in p for p in check_questions(work))


def test_missing_question_file_or_artifacts(tmp_path):
    assert "missing" in check_questions(tmp_path)[0]
    (tmp_path / "agent").mkdir()
    (tmp_path / "agent" / "questions.jsonl").write_text(json.dumps({"qid": "a", "question": "Q"}) + "\n")
    text = "\n".join(check_questions(tmp_path))
    assert "extract/entries.jsonl is missing" in text and "match/matches.jsonl is missing" in text


def save_run(work: Path, run_id: str = "20261018T000000Z-q1", notes: str = "qid=q1") -> Path:
    runs = work / "agent" / "runs"
    runs.mkdir(parents=True, exist_ok=True)
    base = json.loads((FIXTURES / "agent" / "runs" / "run-001.json").read_text())
    base.update(run_id=run_id, notes=notes, label="unreviewed")
    path = runs / f"{run_id}.json"
    path.write_text(json.dumps(base))
    return path


def test_review_sets_label_and_appends_notes_only(work):
    path = save_run(work)
    before = RunRecord.model_validate_json(path.read_text())
    after = review_run(work, before.run_id, "failure", "Wikipedia citation does not support the claim.")
    saved = RunRecord.model_validate_json(path.read_text())
    assert saved == after and saved.label == "failure"
    assert saved.notes == "qid=q1; review: Wikipedia citation does not support the claim."
    assert saved.model_copy(update={"label": "unreviewed", "notes": before.notes}) == before


def test_repaired_rerun_points_to_the_old_run(work):
    save_run(work, "old")
    save_run(work, "new")
    updated = review_run(work, "new", "success", "Citations support each sentence.", repairs="old")
    assert "repairs run_id=old" in updated.notes
    with pytest.raises(ConfigurationError, match="not a saved run"):
        review_run(work, "new", "success", "ok", repairs="ghost")


@pytest.mark.parametrize("args,match", [
    (("ghost", "success", "ok"), "no saved run"),
    (("run", "unreviewed", "ok"), "label must be"),
    (("run", "success", "   "), "write notes"),
])
def test_review_rejects_bad_input(work, args, match):
    save_run(work, "run")
    with pytest.raises(ConfigurationError, match=match):
        review_run(work, *args)


def test_review_refuses_key_material(work, monkeypatch):
    path = save_run(work, "run")
    original = path.read_text()
    monkeypatch.setenv("SUPER_API_KEY", "test-key-value-123456")
    with pytest.raises(SecretFound):
        review_run(work, "run", "failure", "the answer printed test-key-value-123456")
    assert path.read_text() == original


def test_cli_exit_codes(work, image, capsys):
    save_run(work, "run")
    assert main(["--work-dir", str(work), "review", "run", "--label", "success", "--notes", "ok"]) == 0
    assert main(["--work-dir", str(work), "review", "ghost", "--label", "success", "--notes", "ok"]) == 1
    write(work, [{"qid": "a", "question": "Q"}])
    assert main(["--work-dir", str(work), "check"]) == 1
    assert '"ok": false' in capsys.readouterr().out
