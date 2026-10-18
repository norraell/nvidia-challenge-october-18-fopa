"""Tests for stages/compare.py lexical drift analysis, exclusion rules, and SVG generation."""
import json
from pathlib import Path

from nemotron_challenge.contracts import (
    Block,
    CandidateScore,
    DriftReport,
    EntryRecord,
    MatchRecord,
    WikiRef,
)
from nemotron_challenge.stages.compare import (
    compute_drift_analysis,
    find_quote,
    generate_drift_plot,
    tokenize,
)


def test_tokenize_normalization_and_stopwords():
    raw = "The quickſilver was meaſured in the Torricellian tube!"
    tokens = tokenize(raw)
    assert "quicksilver" in tokens
    assert "measured" in tokens
    assert "torricellian" in tokens
    assert "tube" in tokens
    # Stopwords and short tokens removed
    assert "the" not in tokens
    assert "was" not in tokens
    assert "in" not in tokens


def test_find_quote_sentence_selection():
    text = "First sentence about weather. Second sentence details quicksilver and barometers. Third sentence concludes."
    quote = find_quote(text, "quicksilver")
    assert quote == "Second sentence details quicksilver and barometers."


def test_compute_drift_on_fixture_pair(tmp_path):
    # Construct 1 Britannica entry and 1 Matched Wikipedia article
    entry = EntryRecord(
        entry_id="e0001-01",
        kind="entry",
        headword="BAROMETER",
        text="A barometer uses quicksilver quicksilver quicksilver quicksilver quicksilver to measure pressure.",
        text_raw="raw",
        blocks=[Block(page_id="p1", bbox=[0.0, 0.0, 10.0, 10.0], cls="Text", text="t")],
        crop_path="crops/e1.png",
        quality={"low_quality": False},
    )

    wiki_ref = WikiRef(page_id="3845", revision_id="100", title="Barometer", url="http://wiki")
    match = MatchRecord(
        entry_id="e0001-01",
        status="matched",
        reason="rule: score ok",
        queries=["BAROMETER"],
        candidates=[CandidateScore(wiki=wiki_ref, bm25_rank=1, bm25_score=10.0, excerpt="barometer pressure", excerpt_offset=0)],
        match=wiki_ref,
        rerank_margin=1.0,
        method_version="m1",
    )

    # Cache article
    articles_dir = tmp_path / "articles"
    articles_dir.mkdir(parents=True)
    article_path = articles_dir / "3845-100.json"
    with article_path.open("w") as f:
        json.dump({"text": "Modern barometers measure atmospheric pressure using digital sensors and electronic transducers digital digital digital."}, f)

    report, terms = compute_drift_analysis([entry], [match], articles_dir)
    assert report.pairs_used == 1
    assert report.brit_tokens > 0
    assert report.wiki_tokens > 0

    term_map = {t.term: t for t in terms}
    assert "quicksilver" in term_map
    assert term_map["quicksilver"].brit_count == 5
    assert term_map["quicksilver"].log_ratio > 0

    # Test plot generation
    svg_out = tmp_path / "terms.svg"
    generate_drift_plot(terms, report.pairs_used, svg_out)
    assert svg_out.exists()
    svg_content = svg_out.read_text()
    assert "<svg" in svg_content
    assert "1 matched document pairs" in svg_content


def test_low_quality_exclusion_rule(tmp_path):
    entry_bad = EntryRecord(
        entry_id="e0002-01",
        kind="entry",
        headword="BAD",
        text="corrupted text",
        text_raw="raw",
        blocks=[Block(page_id="p1", bbox=[0.0, 0.0, 10.0, 10.0], cls="Text", text="t")],
        crop_path="crops/e2.png",
        quality={"low_quality": True},
    )
    wiki_ref = WikiRef(page_id="999", revision_id="100", title="Bad", url="http://wiki")
    match = MatchRecord(
        entry_id="e0002-01",
        status="matched",
        reason="rule: score ok",
        queries=["BAD"],
        candidates=[],
        match=wiki_ref,
        rerank_margin=1.0,
        method_version="m1",
    )
    report, _ = compute_drift_analysis([entry_bad], [match], tmp_path)
    assert report.pairs_used == 0
    assert "low_quality:e0002-01" in report.exclusions
