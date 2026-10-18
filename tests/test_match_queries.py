"""Query building for the match stage."""
from nemotron_challenge.contracts import Block, EntryRecord
from nemotron_challenge.match.queries import (
    build_queries, clean_text, content_words, headword_from_text, headword_variants, is_range_header,
    normalize_header,
)


def entry(text: str, headword: str | None = None, kind: str = "entry") -> EntryRecord:
    return EntryRecord(entry_id="e0001-01", kind=kind, headword=headword, text=text, text_raw=text,
                       blocks=[Block(page_id="p", bbox=[0.0, 0.0, 1.0, 1.0], cls="Text", text=text)], crop_path="x.png")


def test_treatise_header_gives_hyphen_variants():
    assert normalize_header("292 SHIP-BUILDING.") == "SHIP-BUILDING"
    assert headword_variants("SHIP-BUILDING") == ["shipbuilding", "ship building"]


def test_dictionary_range_header_gives_no_headword():
    for header in ("HEL (781) HEM", "FAR [ 107] FAR", "DAM [ 658]", "182 COM COM", "**ED U** **[ 353 1 E D U**", "B I L B I L 503"):
        assert is_range_header(header), header
        assert normalize_header(header) is None, header


def test_spaced_and_decorated_headers_join():
    assert normalize_header("O P T I C S. 427") == "OPTICS"
    assert normalize_header("ABY S SINIA. 57") == "ABYSSINIA"
    assert normalize_header("**LIBERTY OF THE PRESS.**") == "LIBERTY OF THE PRESS"
    assert normalize_header("HELMINTHOLOGY. Plate CCLI") == "HELMINTHOLOGY"
    assert normalize_header("6goa BLEACHING. Part II.") == "BLEACHING"
    assert normalize_header("948 L A W.") == "LAW"
    assert normalize_header("") is None


def test_dictionary_entry_headword_from_text():
    assert headword_from_text("ABACUS, among the ancients, was a table or desk for calculating.") == "ABACUS"
    assert headword_from_text("the frame presents various compartments") is None


def test_content_words_skip_stopwords_and_junk():
    text = "Barometer barometer barometer qzxv the atmosphere atmosphere <image> xxxx mmmm pressure quicksilver"
    words = content_words(text, 10)
    assert words[:2] == ["barometer", "atmosphere"]
    assert "qzxv" not in words and "xxxx" not in words and "the" not in words and "image" not in words


def test_clean_text_removes_markers_and_parse_tokens():
    raw = "<x_0.1><y_0.2>Hello <image> world <IMG_CONTEXT><x_0.3><y_0.4><class_Text>"
    assert clean_text(raw) == "Hello world"


def test_build_queries_three_kinds_and_limits():
    text = "An instrument for measuring the weight and pressure of the atmosphere with quicksilver. " * 40
    queries = build_queries(entry(text, "BAROMETER"))
    kinds = [q["kind"] for q in queries]
    assert kinds == ["headword", "headword_content", "content"]
    assert queries[0]["text"] == "barometer"
    assert queries[1]["text"].startswith("barometer instrument")
    assert queries[2]["text"].startswith("instrument") and "barometer" not in queries[2]["text"]
    for q in queries:
        assert len(q["text"]) <= 512 and len(q["text"].split()) <= 64


def test_build_queries_without_headword_falls_back_to_content():
    queries = build_queries(entry("continued from the preceding page concerning arithmetic operations", None, "continuation"))
    assert [q["kind"] for q in queries] == ["content"]
    assert "arithmetic" in queries[0]["text"]


def test_build_queries_range_header_uses_text_headword():
    queries = build_queries(entry("ABACUS, among the ancients, was a table for calculating with counters.", "HEL (781) HEM"))
    assert queries[0] == {"kind": "headword", "text": "abacus"}
