"""CER scoring and LaTeX generation for the extract stage. No network and no LaTeX compiler needed."""
from nemotron_challenge.stages.cer import align, cer, report, select_pages
from nemotron_challenge.stages.latex import entry_tex, escape, inline, page_tex, two_columns


def test_identical_text_has_zero_cer():
    assert cer("The house was built.", "the  house was built.")["cer"] == 0.0


def test_substitutions_are_counted_and_long_s_matches_s():
    result = cer("the house", "the honse")
    assert result["cer"] == round(1 / 9, 4)
    assert result["substitutions"] == {("u", "n"): 1}
    assert cer("vessel", "veſſel")["cer"] == 0.0  # long s is read as s on both sides
    assert cer("vessel", "veffel")["substitutions"] == {("s", "f"): 2}


def test_parse_text_may_run_past_the_gold_text_and_start_later():
    result = align("abc", "header abc and more text")
    assert result["distance"] == 0 and result["pred_start"] == 7 and result["pred_end"] == 10


def test_missing_characters_count_against_gold():
    assert cer("abcd", "abd")["distance"] == 1


def page(row, words, status="ok"):
    return {"row_index": row, "page_id": f"p{row}", "status": status, "entry_ids": [f"e{row}"]}, \
        {f"e{row}": {"kind": "entry", "text": " ".join(["word"] * words)}}


def test_selection_is_seeded_and_skips_short_or_failed_pages():
    pages, entries = [], {}
    for row in range(1, 13):
        p, e = page(row, 200 if row % 4 else 50, "ok" if row != 2 else "failed")
        pages.append(p)
        entries.update(e)
    chosen = select_pages(pages, entries)
    assert chosen == select_pages(list(reversed(pages)), entries)  # same answer for any input order
    assert len(chosen) == 5 and 2 not in chosen and not {4, 8, 12} & set(chosen)


def test_report_scores_gold_files_and_lists_missing_ones(tmp_path):
    pages, entries = [], {}
    for row in range(1, 6):
        p, e = page(row, 200)
        pages.append(p)
        entries.update(e)
    assert report(pages, entries, tmp_path)["status"] == "missing gold"
    (tmp_path / "0001.txt").write_text(" ".join(["word"] * 150), encoding="utf-8")
    result = report(pages, entries, tmp_path)
    assert result["status"] == "partial" and result["missing_gold_rows"] == [2, 3, 4, 5]
    assert result["pages"][0]["cer"] == 0.0 and result["mean_cer"] == 0.0


def test_latex_escaping_and_emphasis():
    assert escape("50% & $5 #1 a_b {x} ~ ^ \\") == (
        r"50\% \& \$5 \#1 a\_b \{x\} \textasciitilde{} \textasciicircum{} \textbackslash{}")
    assert inline("the eye at _h_ on below i") == r"the eye at \emph{h} on below i"
    assert inline("snake_case_name") == r"snake\_case\_name"


def entry(kind, headword=None, text="Text.", **quality):
    return {"entry_id": "e0007-01", "kind": kind, "headword": headword, "text": text,
            "crop_path": "artifacts/extract/crops/e0007-01.png",
            "blocks": [{"bbox": [10.0, 10.0, 100.0, 50.0]}], "quality": {"low_quality": False, **quality}}


def test_each_entry_kind_renders():
    assert entry_tex(entry("entry", "ABACUS", "ABACUS, a table.")).startswith(r"\subsection*{ABACUS}")
    assert r"\textit{continued:} SHIP-BUILDING" in entry_tex(entry("continuation", running_header="SHIP-BUILDING"))
    assert r"continued from the previous page" in entry_tex(entry("continuation"))
    assert r"\textit{BYZANT. See BEZANT.}" in entry_tex(entry("cross_reference", "BYZANT", "BYZANT. See BEZANT."))
    plate = entry_tex(entry("plate", text="HYDROSTATICS. Plate CCXXXIX."))
    assert r"\includegraphics" in plate and "{../crops/e0007-01.png}" in plate and "figure" not in plate
    assert r"(no caption)" in entry_tex(entry("plate", text=""))
    assert "[Margin: Practical Building]" in entry_tex(entry("continuation", margin_notes="Practical Building"))
    assert r"[Low OCR quality: 30\% of tokens suspect]" in entry_tex(
        entry("entry", "X", low_quality=True, ocr_suspect_ratio=0.3))


def test_two_column_pages_use_multicols_and_markers_are_all_replaced():
    left = {"bbox": [30.0, 100.0, 280.0, 300.0]}
    right = {"bbox": [320.0, 100.0, 570.0, 300.0]}
    two = entry("entry", "ABACUS") | {"blocks": [left, left, right, right]}
    one = entry("entry", "ABACUS") | {"blocks": [{"bbox": [30.0, 100.0, 570.0, 300.0]}]}
    whole_left_column = entry("continuation") | {"blocks": [{"bbox": [35.8, 56.3, 270.7, 749.9]}, right]}  # row 2001
    margin_note = entry("entry", "X") | {"blocks": [{"bbox": [36.0, 50.0, 75.0, 90.0]}, {"bbox": [80.0, 50.0, 320.0, 700.0]}]}
    assert two_columns([two], 600) and two_columns([whole_left_column], 600)
    assert not two_columns([one], 600) and not two_columns([margin_note], 600)
    record = {"row_index": 7, "page_id": "britannica:x:train:7", "filename": "page-0007-a.jpg", "width": 600,
              "height": 826, "image_sha256": "ab" * 32,
              "parse": {"model": "nvidia/nemotron-3.5-parse", "raw_path": "artifacts/extract/raw/0007.json"}}
    tex = page_tex(record, [two])
    assert r"\begin{multicols}{2}" in tex and r"\section*{Historical source: ABACUS}" in tex
    assert "%%" not in tex and tex.index(r"\documentclass") < tex.index(r"\subsection*")
    assert r"\begin{multicols}" not in page_tex(record, [one])
    plate_only = page_tex(record, [entry("plate", text="HYDROSTATICS. Plate CCXXXIX.")])
    assert r"\section*{Historical source: HYDROSTATICS}" in plate_only
