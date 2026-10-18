"""Extract stage rules: Parse block reading, header drop, headwords, continuations, normalization, crops."""
import base64
import hashlib
import io
import json
from pathlib import Path

import httpx
from PIL import Image

from nemotron_challenge.clients import ParseClient
from nemotron_challenge.config import PARSE_MODEL
from nemotron_challenge.contracts import EntryRecord, PageRecord
from nemotron_challenge.stages.extract import extract, link_continuations
from nemotron_challenge.stages.segment import (
    RawBlock, clean_running_header, drop_reason, headword, is_margin_note, normalize, ocr_suspect_ratio,
    parse_blocks, reading_order, segment, title_headword, to_pixels,
)

REAL_HEAD = (Path(__file__).parent / "fixtures" / "parse" / "0013-head.txt").read_text(encoding="utf-8")
PAGE_ID = "britannica:309f765b1ecc83e0a7f7762e44b4a927a7555443:train:13"


def block(x0, y0, x1, y1, text, cls="Text"):
    return f"<x_{x0}><y_{y0}>{text}<x_{x1}><y_{y1}><class_{cls}>"


def test_real_parse_reply_reads_into_blocks():
    blocks, leftover = parse_blocks(REAL_HEAD)
    assert leftover == 0
    assert [b.cls for b in blocks] == ["Page-header", "Section-header", "Text", "Text", "Text", "Text"]
    assert blocks[0].text == "292 SHIP-BUILDING."
    assert (blocks[0].x0, blocks[0].y0, blocks[0].x1, blocks[0].y1) == (0.0576, 0.0445, 0.6514, 0.0563)


def test_fractions_convert_to_source_pixels_and_clip():
    assert to_pixels(RawBlock(0.1, 0.2, 0.5, 0.6, "t", "Text"), 600, 826) == [60.0, 165.2, 300.0, 495.6]
    assert to_pixels(RawBlock(-0.01, 0.0, 1.2, 1.0, "t", "Text"), 600, 826) == [0.0, 0.0, 600.0, 826.0]


def test_header_and_footer_drop():
    assert drop_reason(RawBlock(0.25, 0.0648, 0.96, 0.0859, "6goa BLEACHING. Part II.", "Page-header")) == "class Page-header"
    assert drop_reason(RawBlock(0.89, 0.045, 0.93, 0.058, "853", "Text"))
    assert drop_reason(RawBlock(0.1, 0.95, 0.9, 0.99, "Vol. IV. Part I.", "Text"))
    # A body text block that starts near the top is kept.
    assert drop_reason(RawBlock(0.11, 0.057, 0.52, 0.117, "ends in close contact with, and coaked or dowelled", "Text")) is None


def test_headword_split():
    assert headword("ABACUS, among the ancients, was a table") == "ABACUS"
    assert headword("**ABACUS**, among the ancients") == "ABACUS"
    assert headword("SHIP-BUILDING. The art of") == "SHIP-BUILDING"
    assert headword("A T reads—timber is then introduced") is None
    assert headword("The beams are disposed in the new system") is None


def test_headword_cleanup_seen_in_the_real_run():
    assert headword("C O N C H O L O G Y. The science of shells") == "CONCHOLOGY"
    assert headword("CH E M I S T R Y. Chemistry is") == "CHEMISTRY"
    assert headword("A TEMPO GIUSTO, in music") == "A TEMPO GIUSTO"
    assert headword("CHAP. II. Of the beams") is None
    assert headword("VII. The seventh method") is None
    assert headword("CIVIL, relating to") == "CIVIL"
    assert headword("BUS', a measure") == "BUS"
    assert title_headword("A N A T O M Y.") == "ANATOMY"
    assert title_headword("Of the Atmosphere") is None
    assert clean_running_header("292 SHIP-BUILDING.") == "SHIP-BUILDING"
    assert clean_running_header("6goa BLEACHING. Part II.") == "BLEACHING"
    assert clean_running_header("WEIGHTS AND MEASURES.") == "WEIGHTS AND MEASURES"
    assert clean_running_header("853") == ""
    assert clean_running_header("C ARPENTRY. 631") == "CARPENTRY"
    assert clean_running_header("ABY S SINIA.") == "ABYSSINIA"
    assert clean_running_header("LIBERTY OF THE PRESS.") == "LIBERTY OF THE PRESS"
    assert clean_running_header("COM [ 345 ] COM") == ""
    assert clean_running_header("COM COM") == ""


def test_title_block_starts_an_entry():
    page = block(0.3, 0.08, 0.7, 0.12, "C H E M I S T R Y.", "Title") + "\n\n" + block(0.1, 0.13, 0.9, 0.3, "Chemistry is the science.")
    entries = segment(page, 5, PAGE_ID, 600, 826)["entries"]
    assert [(e["kind"], e["headword"]) for e in entries] == [("entry", "CHEMISTRY")]


def test_margin_note_is_not_a_headword_and_stays_out_of_text():
    page = "\n\n".join([
        block(0.06, 0.07, 0.126, 0.11, "PRACTICAL.", "Section-header"),
        block(0.12, 0.07, 0.52, 0.2, "continued text of the article."),
    ])
    entry = segment(page, 13, PAGE_ID, 600, 826)["entries"][0]
    assert is_margin_note(RawBlock(0.06, 0.07, 0.126, 0.11, "PRACTICAL.", "Section-header"))
    assert entry["kind"] == "continuation" and entry["headword"] is None
    assert entry["text"] == "continued text of the article."
    assert entry["quality"]["margin_notes"] == "PRACTICAL."
    assert "PRACTICAL." in entry["text_raw"]


def test_real_continuation_page_keeps_running_header():
    result = segment(REAL_HEAD, 13, PAGE_ID, 600, 826)
    assert [d["text"] for d in result["dropped"]] == ["292 SHIP-BUILDING."]
    assert len(result["entries"]) == 1
    entry = result["entries"][0]
    assert entry["entry_id"] == "e0013-01" and entry["kind"] == "continuation"
    assert entry["quality"]["running_header"] == "SHIP-BUILDING"
    assert entry["quality"]["margin_notes"] == "Fractical Building"
    assert len(entry["blocks"]) == 5


def test_entries_plates_and_cross_references_split_in_reading_order():
    page = "\n\n".join([
        block(0.1, 0.10, 0.48, 0.20, "the end of an article from the previous page."),
        block(0.1, 0.22, 0.48, 0.40, "ABACUS, among the ancients, was a table for calculating."),
        block(0.1, 0.42, 0.48, 0.60, "Picture of an abacus", "Picture"),
        block(0.1, 0.61, 0.48, 0.64, "Plate I. An abacus.", "Caption"),
        block(0.52, 0.10, 0.9, 0.30, "the abacus is still used by merchants."),
        block(0.52, 0.32, 0.9, 0.40, "ABBA, see ABBOT."),
    ])
    entries = segment(page, 7, PAGE_ID, 600, 826)["entries"]
    assert [(e["entry_id"], e["kind"], e["headword"]) for e in entries] == [
        ("e0007-01", "continuation", None),
        ("e0007-02", "entry", "ABACUS"),
        ("e0007-03", "plate", None),
        ("e0007-04", "cross_reference", "ABBA"),
    ]
    assert "still used by merchants" in entries[1]["text"]  # text resumes after the plate
    assert entries[2]["text"] == "Picture of an abacus Plate I. An abacus."


def test_two_columns_read_left_then_right_with_full_width_band_break():
    left_low = RawBlock(0.1, 0.6, 0.48, 0.8, "left low", "Text")
    right_top = RawBlock(0.52, 0.1, 0.9, 0.4, "right top", "Text")
    left_top = RawBlock(0.1, 0.1, 0.48, 0.4, "left top", "Text")
    title = RawBlock(0.1, 0.45, 0.9, 0.5, "TITLE", "Section-header")
    right_low = RawBlock(0.52, 0.6, 0.9, 0.8, "right low", "Text")
    ordered = reading_order([right_low, left_low, title, right_top, left_top])
    assert [b.text for b in ordered] == ["left top", "right top", "TITLE", "left low", "right low"]


def test_normalization():
    assert normalize("an inſtrument for meaſuring") == "an instrument for measuring"
    assert normalize("repre-\nsenting the  figure\n of") == "representing the figure of"
    assert normalize("**ABACUS**, a table") == "ABACUS, a table"
    assert normalize("thus au- thors mention endlefs rolls") == "thus authors mention endlefs rolls"
    assert normalize("SWIVEL- Cannon") == "SWIVEL- Cannon"  # a capital after the hyphen is not a line break


def test_ocr_suspect_ratio_ignores_numbers_and_punctuation():
    assert ocr_suspect_ratio("In 1733 the weight was 27/430 lb.") == 0.0
    assert ocr_suspect_ratio("3hr 34:300698 Brit. quarters") == 0.5
    assert ocr_suspect_ratio("") == 0.0


def test_continuation_links_only_to_previous_scan_in_same_volume():
    pages = [{"row_index": 12, "volume_id": "v1"}, {"row_index": 13, "volume_id": "v1"},
             {"row_index": 40, "volume_id": "v2"}]
    entries = {
        12: [{"entry_id": "e0012-01", "kind": "entry", "quality": {}, "continues_to": None}],
        13: [{"entry_id": "e0013-01", "kind": "continuation", "quality": {}, "continues_from": None}],
        40: [{"entry_id": "e0040-01", "kind": "continuation", "quality": {}, "continues_from": None}],
    }
    link_continuations(pages, entries)
    assert entries[13][0]["continues_from"] == "e0012-01"
    assert entries[12][0]["continues_to"] == "e0013-01"
    assert entries[13][0]["quality"]["orphan_continuation"] is False
    assert entries[40][0]["quality"]["orphan_continuation"] is True


def test_extract_writes_valid_records_crops_and_resumes(tmp_path):
    scan_dir = tmp_path / "scans"
    scan_dir.mkdir()
    buffer = io.BytesIO()
    Image.new("RGB", (600, 826), "white").save(buffer, format="JPEG")
    (scan_dir / "page-0007-aaaaaaaaaaaa.jpg").write_bytes(buffer.getvalue())
    page = {"page_id": PAGE_ID, "row_index": 7, "volume_id": "v1", "filename": "page-0007-aaaaaaaaaaaa.jpg",
            "image_sha256": hashlib.sha256(buffer.getvalue()).hexdigest()}
    content = "\n\n".join([
        block(0.1, 0.03, 0.6, 0.05, "7 ABACUS.", "Page-header"),
        block(0.1, 0.22, 0.48, 0.40, "ABACUS, among the ancients, was a table for calculating."),
    ])
    calls = []

    def handle(request):
        if request.url.path.endswith("/models"):
            return httpx.Response(200, json={"data": [{"id": PARSE_MODEL}]})
        calls.append(json.loads(request.content)["messages"][0]["content"][1]["image_url"]["url"][:22])
        return httpx.Response(200, json={"model": PARSE_MODEL, "choices": [
            {"finish_reason": "stop", "message": {"content": content}}]})

    with httpx.Client(transport=httpx.MockTransport(handle)) as http:
        client = ParseClient("https://parse.example/v1", client=http)
        summary = extract([page], scan_dir, tmp_path / "artifacts", client)
        extract([page], scan_dir, tmp_path / "artifacts", client)  # second run reuses the raw reply

    assert calls == ["data:image/jpeg;base64"]
    assert summary["pages_by_status"] == {"ok": 1} and summary["entries_by_kind"] == {"entry": 1}
    out = tmp_path / "artifacts" / "extract"
    page_record = PageRecord.model_validate_json((out / "pages.jsonl").read_text(encoding="utf-8").strip())
    entry_record = EntryRecord.model_validate_json((out / "entries.jsonl").read_text(encoding="utf-8").strip())
    assert page_record.width == 600 and page_record.entry_ids == ["e0007-01"]
    assert entry_record.headword == "ABACUS" and entry_record.blocks[0].bbox == [60.0, 181.7, 288.0, 330.4]
    with Image.open(entry_record.crop_path) as crop:
        assert crop.size == (int(288.0 + 8) - int(60.0 - 8), int(330.4 + 8) - int(181.7 - 8))
    coverage = json.loads((out / "coverage.json").read_text(encoding="utf-8"))
    assert coverage["dropped_blocks"][0]["text"] == "7 ABACUS."
    assert coverage["cer"]["status"] == "no eligible pages"  # one short entry: under 150 words
    assert coverage["latex"] == {"status": "not compiled on this machine; 0 existing PDFs kept", "compiler": None,
                                 "tex_files": 1, "compiled": 0, "failed": [], "skipped_pages": []}
    assert r"\subsection*{ABACUS}" in (out / "latex" / "0007.tex").read_text(encoding="utf-8")


def test_blank_sheet_with_full_page_picture_is_blank_but_engraving_is_a_plate(tmp_path):
    from nemotron_challenge.stages.extract import is_blank

    picture = [{"text": "", "kind": "plate", "blocks": [{"bbox": [0.0, 0.0, 600.0, 800.0], "text": "", "cls": "Picture"}]}]
    blank = tmp_path / "blank.jpg"
    Image.new("L", (600, 800), 225).save(blank, format="JPEG")
    engraving = tmp_path / "engraving.png"
    image = Image.new("L", (600, 800), 225)
    image.paste(0, (100, 100, 500, 700))  # dark printed area
    image.save(engraving, format="PNG")
    assert is_blank(picture, blank)
    assert not is_blank(picture, engraving)
    captioned = [dict(picture[0], text="Plate XVII.")]
    assert not is_blank(captioned, blank)


def test_failed_parse_is_recorded_not_raised(tmp_path):
    scan_dir = tmp_path / "scans"
    scan_dir.mkdir()
    page = {"page_id": PAGE_ID, "row_index": 9, "volume_id": "v1", "filename": "page-0009-bbbbbbbbbbbb.jpg",
            "image_sha256": "0" * 64}
    (scan_dir / page["filename"]).write_bytes(base64.b64decode("/9j/"))
    with httpx.Client(transport=httpx.MockTransport(lambda r: httpx.Response(500))) as http:
        summary = extract([page], scan_dir, tmp_path / "artifacts", ParseClient("https://parse.example/v1", client=http))
    assert summary["pages_by_status"] == {"failed": 1}
    coverage = json.loads((tmp_path / "artifacts" / "extract" / "coverage.json").read_text(encoding="utf-8"))
    assert "checksum differs" in coverage["failed_pages"][0]["error"]
