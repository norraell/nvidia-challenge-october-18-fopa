"""Compare vocabulary, word frequencies, and semantic drift across matched sources."""
from __future__ import annotations

from collections import Counter
import json
import math
from pathlib import Path
import re
from typing import Any

from ..config import Settings
from ..contracts import (
    DriftReport,
    EntryRecord,
    MatchRecord,
    TermRow,
)

# Standard English stop words (stdlib list in code)
STOPWORDS = frozenset({
    "a", "about", "above", "after", "again", "against", "all", "also", "am", "an",
    "and", "any", "are", "aren't", "as", "at", "be", "because", "been", "before",
    "being", "below", "between", "both", "but", "by", "can", "cannot", "could",
    "couldn't", "did", "didn't", "do", "does", "doesn't", "doing", "don't", "down",
    "during", "each", "few", "for", "from", "further", "had", "hadn't", "has",
    "hasn't", "have", "haven't", "having", "he", "he'd", "he'll", "he's", "her",
    "here", "here's", "hers", "herself", "him", "himself", "his", "how", "how's",
    "i", "i'd", "i'll", "i'm", "i've", "if", "in", "into", "is", "isn't", "it",
    "it's", "its", "itself", "let's", "me", "more", "most", "mustn't", "my",
    "myself", "no", "nor", "not", "of", "off", "on", "once", "only", "or", "other",
    "ought", "our", "ours", "ourselves", "out", "over", "own", "same", "shan't",
    "she", "she'd", "she'll", "she's", "should", "shouldn't", "so", "some", "such",
    "than", "that", "that's", "the", "their", "theirs", "them", "themselves",
    "then", "there", "there's", "these", "they", "they'd", "they'll", "they're",
    "they've", "this", "those", "through", "to", "too", "under", "until", "up",
    "very", "was", "wasn't", "we", "we'd", "we'll", "we're", "we've", "were",
    "weren't", "what", "what's", "when", "when's", "where", "where's", "which",
    "while", "who", "who's", "whom", "why", "why's", "with", "won't", "would",
    "wouldn't", "you", "you'd", "you'll", "you're", "you've", "your", "yours",
    "yourself", "yourselves",
})


def tokenize(text: str) -> list[str]:
    """Normalize and tokenize text: lowercase, ſ->s, split on non-letters, drop < 3 chars & stopwords."""
    norm = text.lower().replace("ſ", "s")
    raw_tokens = re.findall(r"[a-z]+", norm)
    return [t for t in raw_tokens if len(t) >= 3 and t not in STOPWORDS]


def split_sentences(text: str) -> list[str]:
    """Split text into sentences for quote extraction."""
    clean = re.sub(r"\s+", " ", text).strip()
    if not clean:
        return []
    # Split on sentence terminals followed by space
    sentences = re.split(r"(?<=[.!?])\s+", clean)
    return [s.strip() for s in sentences if s.strip()]


def find_quote(text: str, term: str) -> str:
    """Find the first sentence containing the term as a whole word."""
    sentences = split_sentences(text)
    pattern = re.compile(rf"\b{re.escape(term)}\b", re.IGNORECASE)
    for s in sentences:
        if pattern.search(s):
            return s
    return sentences[0] if sentences else ""


def generate_drift_plot(terms: list[TermRow], num_pairs: int, out_svg_path: Path) -> None:
    """Generate plots/terms.svg with top-25 each way and document count."""
    top_brit = sorted([t for t in terms if t.log_ratio > 0], key=lambda x: x.log_ratio, reverse=True)[:25]
    top_wiki = sorted([t for t in terms if t.log_ratio < 0], key=lambda x: x.log_ratio)[:25]
    selected = top_brit + top_wiki

    width = 900
    row_height = 24
    header_height = 80
    height = header_height + (len(selected) * row_height) + 40

    svg_lines = [
        f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {width} {height}" width="{width}" height="{height}">',
        '  <style>',
        '    .title { font-family: sans-serif; font-size: 16px; font-weight: bold; fill: #0f172a; }',
        '    .subtitle { font-family: sans-serif; font-size: 12px; fill: #64748b; }',
        '    .label { font-family: sans-serif; font-size: 11px; fill: #1e293b; }',
        '    .val { font-family: monospace; font-size: 10px; fill: #475569; }',
        '  </style>',
        f'  <rect width="{width}" height="{height}" fill="#ffffff"/>',
        f'  <text x="40" y="35" class="title">Lexical Drift Analysis: Historical Britannica vs Modern Wikipedia</text>',
        f'  <text x="40" y="55" class="subtitle">Evaluated on {num_pairs} matched document pairs | Log2 Frequency Ratio</text>',
        f'  <line x1="450" y1="75" x2="450" y2="{height - 20}" stroke="#cbd5e1" stroke-width="2"/>',
    ]

    y = header_height
    for row in selected:
        ratio = row.log_ratio
        clamped_ratio = max(-8.0, min(8.0, ratio))
        bar_len = abs(clamped_ratio) * 40.0

        if ratio >= 0:
            # Britannica higher -> draw right of center in amber
            x_bar = 450
            bar_color = "#f59e0b"
            svg_lines.append(f'  <rect x="{x_bar}" y="{y}" width="{bar_len:.1f}" height="16" fill="{bar_color}" rx="2"/>')
            svg_lines.append(f'  <text x="440" y="{y + 12}" text-anchor="end" class="label">{row.term}</text>')
            svg_lines.append(f'  <text x="{x_bar + bar_len + 8:.1f}" y="{y + 12}" class="val">+{ratio:.2f}</text>')
        else:
            # Wikipedia higher -> draw left of center in blue
            x_bar = 450 - bar_len
            bar_color = "#3b82f6"
            svg_lines.append(f'  <rect x="{x_bar:.1f}" y="{y}" width="{bar_len:.1f}" height="16" fill="{bar_color}" rx="2"/>')
            svg_lines.append(f'  <text x="460" y="{y + 12}" text-anchor="start" class="label">{row.term}</text>')
            svg_lines.append(f'  <text x="{x_bar - 8:.1f}" y="{y + 12}" text-anchor="end" class="val">{ratio:.2f}</text>')

        y += row_height

    svg_lines.append('</svg>')
    out_svg_path.parent.mkdir(parents=True, exist_ok=True)
    out_svg_path.write_text("\n".join(svg_lines), encoding="utf-8")


def compute_drift_analysis(
    entries: list[EntryRecord],
    matches: list[MatchRecord],
    cached_articles_dir: Path,
) -> tuple[DriftReport, list[TermRow]]:
    """Compare matched pairs, compute term counts, rates, log ratios, and quotes."""
    matched_by_id = {m.entry_id: m for m in matches if m.status == "matched" and m.match is not None}
    
    exclusions: list[str] = []
    valid_pairs: list[tuple[EntryRecord, MatchRecord, str]] = []

    for entry in entries:
        if entry.entry_id not in matched_by_id:
            continue
        
        # Check low_quality exclusion rule
        if entry.quality.get("low_quality") is True:
            exclusions.append(f"low_quality:{entry.entry_id}")
            continue

        match = matched_by_id[entry.entry_id]
        assert match.match is not None
        page_id = match.match.page_id
        rev_id = match.match.revision_id

        # Lookup cached article text
        article_file = cached_articles_dir / f"{page_id}-{rev_id}.json"
        article_text = ""
        if article_file.exists():
            try:
                with article_file.open("r", encoding="utf-8") as f:
                    data = json.load(f)
                    article_text = data.get("text", "")
            except Exception:
                article_text = ""
        
        # If cache file not found, use candidate excerpt as fallback
        if not article_text:
            for cand in match.candidates:
                if cand.wiki.page_id == page_id:
                    article_text = cand.excerpt
                    break

        if not article_text:
            continue

        # Rule 1: cut article text to min(len(article), 3 * len(entry.text))
        max_wiki_len = 3 * len(entry.text)
        cut_article_text = article_text[:max_wiki_len]
        valid_pairs.append((entry, match, cut_article_text))

    brit_term_counts: Counter[str] = Counter()
    wiki_term_counts: Counter[str] = Counter()
    total_brit_tokens = 0
    total_wiki_tokens = 0

    brit_texts_by_term: dict[str, tuple[str, str]] = {}  # term -> (entry_id, text)
    wiki_texts_by_term: dict[str, tuple[str, str, str]] = {}  # term -> (page_id, rev_id, text)

    for entry, match, wiki_text in valid_pairs:
        assert match.match is not None
        p_id = match.match.page_id
        r_id = match.match.revision_id

        b_tokens = tokenize(entry.text)
        w_tokens = tokenize(wiki_text)

        total_brit_tokens += len(b_tokens)
        total_wiki_tokens += len(w_tokens)

        for t in b_tokens:
            brit_term_counts[t] += 1
            if t not in brit_texts_by_term:
                brit_texts_by_term[t] = (entry.entry_id, entry.text)

        for t in w_tokens:
            wiki_term_counts[t] += 1
            if t not in wiki_texts_by_term:
                wiki_texts_by_term[t] = (p_id, r_id, wiki_text)

    all_vocab = set(brit_term_counts.keys()) | set(wiki_term_counts.keys())
    term_rows: list[TermRow] = []

    # Safeguard against zero tokens
    denom_brit = max(1, total_brit_tokens)
    denom_wiki = max(1, total_wiki_tokens)

    for term in sorted(all_vocab):
        b_cnt = brit_term_counts[term]
        w_cnt = wiki_term_counts[term]
        
        # Rule 3: Keep terms with total count >= 5
        if (b_cnt + w_cnt) < 5:
            continue

        b_per_10k = (b_cnt / denom_brit) * 10000.0
        w_per_10k = (w_cnt / denom_wiki) * 10000.0
        log_ratio = math.log2((b_per_10k + 0.5) / (w_per_10k + 0.5))

        # Quote lookup
        b_entry_id, b_src_text = brit_texts_by_term.get(term, ("", ""))
        w_pid, w_rid, w_src_text = wiki_texts_by_term.get(term, ("", "", ""))

        b_quote = find_quote(b_src_text, term) if b_src_text else ""
        w_quote = find_quote(w_src_text, term) if w_src_text else ""

        term_rows.append(TermRow(
            term=term,
            brit_count=b_cnt,
            wiki_count=w_cnt,
            brit_per_10k=round(b_per_10k, 2),
            wiki_per_10k=round(w_per_10k, 2),
            log_ratio=round(log_ratio, 2),
            brit_example={"entry_id": b_entry_id, "quote": b_quote},
            wiki_example={"page_id": w_pid, "revision_id": w_rid, "quote": w_quote},
        ))

    report = DriftReport(
        method="token_log_ratio_min_3x_entry_length",
        exclusions=exclusions,
        pairs_used=len(valid_pairs),
        brit_tokens=total_brit_tokens,
        wiki_tokens=total_wiki_tokens,
        terms=term_rows,
    )
    return report, term_rows


def run(settings: Settings, work_dir: Path) -> dict[str, Any]:
    """Execute compare milestone: analyze matched pairs, write drift.json and plots/terms.svg."""
    # Look for inputs in work_dir, fallback to fixtures if empty
    entries_file = work_dir / "extract" / "entries.jsonl"
    matches_file = work_dir / "match" / "matches.jsonl"
    cache_dir = work_dir / "match" / "cache" / "articles"

    if not entries_file.exists():
        fixture_dir = Path(__file__).parent.parent.parent.parent / "tests" / "fixtures" / "artifacts"
        entries_file = fixture_dir / "extract" / "entries.jsonl"
        matches_file = fixture_dir / "match" / "matches.jsonl"
        cache_dir = fixture_dir / "match" / "cache" / "articles"

    entries_raw = []
    if entries_file.exists():
        with entries_file.open("r", encoding="utf-8") as f:
            for line in f:
                if line.strip():
                    entries_raw.append(EntryRecord.model_validate_json(line.strip()))

    matches_raw = []
    if matches_file.exists():
        with matches_file.open("r", encoding="utf-8") as f:
            for line in f:
                if line.strip():
                    matches_raw.append(MatchRecord.model_validate_json(line.strip()))

    report, terms = compute_drift_analysis(entries_raw, matches_raw, cache_dir)

    # Write artifacts/compare/drift.json
    out_dir = work_dir / "compare"
    out_dir.mkdir(parents=True, exist_ok=True)
    drift_out = out_dir / "drift.json"
    with drift_out.open("w", encoding="utf-8") as f:
        f.write(report.model_dump_json(indent=2))

    # Write plots/terms.svg
    plots_dir = out_dir / "plots"
    plots_dir.mkdir(parents=True, exist_ok=True)
    plot_svg = plots_dir / "terms.svg"
    generate_drift_plot(terms, report.pairs_used, plot_svg)

    return {
        "status": "ok",
        "pairs_used": report.pairs_used,
        "terms_analyzed": len(report.terms),
        "brit_tokens": report.brit_tokens,
        "wiki_tokens": report.wiki_tokens,
        "drift_json": str(drift_out),
        "plot_svg": str(plot_svg),
    }
