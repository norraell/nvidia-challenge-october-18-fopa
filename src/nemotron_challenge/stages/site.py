"""Transform pipeline artifacts into static site JSON and assets for GitHub Pages."""
from __future__ import annotations

DONE = True

import difflib
import json
import os
from pathlib import Path
import shutil
from typing import Any

from ..config import Settings
from ..contracts import (
    DriftReport,
    EntryRecord,
    MatchRecord,
    PageRecord,
    RunRecord,
)


def _status_counts(path: Path) -> dict[str, int] | None:
    rows = _load_jsonl(path)
    if not rows:
        return None
    counts: dict[str, int] = {}
    for row in rows:
        counts[row["status"]] = counts.get(row["status"], 0) + 1
    return counts


def _tokens(text: str) -> list[str]:
    return [w for w in (t.strip(".,;:!?()[]\"'“”‘’") for t in text.split()) if w]


def _confirmed_fixes(parse: str, faithful: str, gold: str) -> list[tuple[str, str]]:
    """Parse -> Super VL replacements whose new words line up with the same words in the gold text."""
    p, f, g = _tokens(parse), _tokens(faithful), _tokens(gold)
    lower = lambda words: [w.lower() for w in words]
    aligned = set()
    for a, _, size in difflib.SequenceMatcher(None, lower(f), lower(g), autojunk=False).get_matching_blocks():
        if size >= 3:  # a run of 3+ words anchors the position; 1-2 word matches ("a small") can be chance
            aligned.update(range(a, a + size))
    fixes = []
    for tag, i1, i2, j1, j2 in difflib.SequenceMatcher(None, lower(p), lower(f), autojunk=False).get_opcodes():
        if tag == "replace" and all(j in aligned for j in range(j1, j2)):
            fixes.append((" ".join(p[i1:i2]), " ".join(f[j1:j2])))
    return fixes


def reading_check(work_dir: Path) -> dict[str, Any] | None:
    """Numbers for the Reading Check view: OCR correction, matching, ablation. Only real artifact values."""
    coverage_path = work_dir / "extract" / "coverage.json"
    if not coverage_path.exists():
        return None
    coverage = json.loads(coverage_path.read_text(encoding="utf-8"))
    correction = coverage.get("correction")
    result: dict[str, Any] = {"cer": coverage.get("cer"), "correction": None, "verified_fixes": [],
                              "ablation": None, "matching": None}
    if correction:
        result["correction"] = {key: correction.get(key) for key in (
            "model", "blocks_sent", "blocks_with_fallback", "fallback_reasons", "meaning_check", "gold")}
        # Fixes that the hand-typed gold page confirms: the corrected words line up with the same words in the gold text.
        corrected = {row["entry_id"]: row for row in _load_jsonl(work_dir / "extract" / "corrected.jsonl")}
        pages = {p["row_index"]: p for p in _load_jsonl(work_dir / "extract" / "pages.jsonl")}
        for gold_row in correction.get("gold") or []:
            gold_path = work_dir / "extract" / "gold" / f"{gold_row['row_index']:04d}.txt"
            page = pages.get(gold_row["row_index"])
            if not gold_path.exists() or not page:
                continue
            gold = gold_path.read_text(encoding="utf-8")
            for entry_id in page["entry_ids"]:
                row = corrected.get(entry_id)
                if not row or row.get("kind") == "plate":
                    continue
                for old, new in _confirmed_fixes(row["parse"], row["faithful"], gold):
                    result["verified_fixes"].append({"row_index": gold_row["row_index"], "entry_id": entry_id,
                                                     "parse": old, "super_vl": new})
    ablation_path = work_dir / "match" / "ablation.json"
    if ablation_path.exists():
        result["ablation"] = json.loads(ablation_path.read_text(encoding="utf-8"))
    parse_counts = _status_counts(work_dir / "match" / "matches.jsonl")
    modern_counts = _status_counts(work_dir / "match" / "modern" / "matches.jsonl")
    if parse_counts:
        result["matching"] = {"parse_text": parse_counts, "modern_text": modern_counts}
    return result


def _load_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    records = []
    with path.open("r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                records.append(json.loads(line))
    return records


def transform_artifacts_to_site_data(
    work_dir: Path,
    raw_scans_dir: Path,
    web_dir: Path,
    assert_real: bool = False,
) -> dict[str, Any]:
    """Read artifacts from work_dir, transform into web/data JSON shapes, and copy assets."""
    data_dir = web_dir / "data"
    data_dir.mkdir(parents=True, exist_ok=True)
    scans_dest = web_dir / "scans"
    crops_dest = web_dir / "crops"
    latex_dest = web_dir / "latex"
    scans_dest.mkdir(parents=True, exist_ok=True)
    crops_dest.mkdir(parents=True, exist_ok=True)
    latex_dest.mkdir(parents=True, exist_ok=True)

    pages_file = work_dir / "extract" / "pages.jsonl"
    entries_file = work_dir / "extract" / "entries.jsonl"
    matches_file = work_dir / "match" / "matches.jsonl"
    drift_file = work_dir / "compare" / "drift.json"
    runs_dir = work_dir / "agent" / "runs"

    # 1. Load entries and matches
    raw_entries = _load_jsonl(entries_file)
    validated_entries = [EntryRecord.model_validate(e) for e in raw_entries]
    entries_by_id: dict[str, EntryRecord] = {e.entry_id: e for e in validated_entries}

    raw_matches = _load_jsonl(matches_file)
    validated_matches = [MatchRecord.model_validate(m) for m in raw_matches]
    matches_by_entry: dict[str, MatchRecord] = {m.entry_id: m for m in validated_matches}

    # 2. Transform pages and embed entry data with matches
    raw_pages = _load_jsonl(pages_file)
    validated_pages = [PageRecord.model_validate(p) for p in raw_pages]

    transformed_pages = []
    for p in validated_pages:
        page_entries = []
        for eid in p.entry_ids:
            entry = entries_by_id.get(eid)
            if not entry:
                continue

            match = matches_by_entry.get(eid)
            match_dict = None
            if match:
                match_dict = {
                    "status": match.status,
                    "reason": match.reason,
                    "method_version": match.method_version,
                    "rerank_margin": match.rerank_margin,
                    "queries": match.queries,
                    "matched_wiki": match.match.model_dump() if match.match else None,
                    "candidates": [
                        {
                            "title": c.wiki.title,
                            "page_id": c.wiki.page_id,
                            "revision_id": c.wiki.revision_id,
                            "url": c.wiki.url,
                            "bm25_rank": c.bm25_rank,
                            "bm25_score": c.bm25_score,
                            "embed_cosine": c.embed_cosine,
                            "embed_rank": c.embed_rank,
                            "rerank_logit": c.rerank_logit,
                            "rerank_rank": c.rerank_rank,
                            "excerpt": c.excerpt,
                        }
                        for c in match.candidates
                    ],
                }

            page_entries.append({
                "entry_id": entry.entry_id,
                "kind": entry.kind,
                "headword": entry.headword,
                "text": entry.text,
                "text_raw": entry.text_raw,
                "crop_path": entry.crop_path,
                "blocks": [b.model_dump() for b in entry.blocks],
                "quality": entry.quality,
                "match": match_dict,
            })

            # Copy crop if present
            crop_src = Path(entry.crop_path)
            if not crop_src.is_absolute() and not crop_src.exists():
                crop_src = work_dir / entry.crop_path
            if crop_src.exists():
                shutil.copy2(crop_src, crops_dest / crop_src.name)

        # Copy scan image if available
        scan_src = raw_scans_dir / p.filename
        if scan_src.exists():
            shutil.copy2(scan_src, scans_dest / p.filename)

        # Check for compiled LaTeX PDF
        pdf_name = f"{p.row_index:04d}.pdf"
        latex_src = work_dir / "extract" / "latex" / pdf_name
        latex_pdf_url = f"latex/{pdf_name}" if latex_src.exists() else None
        if latex_src.exists():
            shutil.copy2(latex_src, latex_dest / pdf_name)

        transformed_pages.append({
            "page_id": p.page_id,
            "row_index": p.row_index,
            "volume_id": p.volume_id,
            "filename": p.filename,
            "image_url": f"scans/{p.filename}" if scan_src.exists() else None,
            "latex_pdf_url": latex_pdf_url,
            "width": p.width,
            "height": p.height,
            "status": p.status,
            "parse": p.parse.model_dump() if p.parse else None,
            "entries": page_entries,
        })

    # 3. Transform drift report
    drift_data: dict[str, Any] = {"method": "none", "exclusions": [], "pairs_used": 0, "brit_tokens": 0, "wiki_tokens": 0, "terms": []}
    if drift_file.exists():
        with drift_file.open("r", encoding="utf-8") as f:
            drift_obj = DriftReport.model_validate(json.load(f))
            drift_data = drift_obj.model_dump()

    # 4. Transform agent runs
    transformed_runs = []
    if runs_dir.exists():
        for run_file in sorted(runs_dir.glob("*.json")):
            with run_file.open("r", encoding="utf-8") as f:
                run_obj = RunRecord.model_validate(json.load(f))
                transformed_runs.append(run_obj.model_dump())

    # Check fixture assertion if requested
    has_fixture_data = any(
        e.get("quality", {}).get("fixture") is True
        for p in transformed_pages
        for e in p.get("entries", [])
    ) or any("fixture" in str(r.get("notes", "")).lower() for r in transformed_runs)

    if assert_real and has_fixture_data:
        raise AssertionError("Expected 100% real artifacts, but found fixture data in records.")

    # Write transformed JSON to web/data
    with (data_dir / "pages.json").open("w", encoding="utf-8") as f:
        json.dump(transformed_pages, f, indent=2)

    with (data_dir / "drift.json").open("w", encoding="utf-8") as f:
        json.dump(drift_data, f, indent=2)

    with (data_dir / "cases.json").open("w", encoding="utf-8") as f:
        json.dump(transformed_runs, f, indent=2)

    quality = reading_check(work_dir)
    if quality is not None:
        with (data_dir / "quality.json").open("w", encoding="utf-8") as f:
            json.dump(quality, f, indent=2, ensure_ascii=False)

    return {
        "status": "ok",
        "pages_transformed": len(transformed_pages),
        "entries_count": len(entries_by_id),
        "matches_count": len(matches_by_entry),
        "runs_count": len(transformed_runs),
        "has_fixture_data": has_fixture_data,
        "site_dir": str(web_dir),
    }


def run(settings: Settings, work_dir: Path) -> dict[str, Any]:
    """Execute site generation milestone. SITE_WEB_DIR and SITE_SCANS_DIR override the default paths."""
    web_dir = Path(os.environ.get("SITE_WEB_DIR", "").strip() or "web")
    raw_scans_dir = Path(os.environ.get("SITE_SCANS_DIR", "").strip() or "data/raw/britannica")

    # If artifacts directory has no extract/pages.jsonl, fallback to fixtures directory for early testing
    target_work_dir = work_dir
    if not (work_dir / "extract" / "pages.jsonl").exists():
        fixture_dir = Path(__file__).parent.parent.parent.parent / "tests" / "fixtures" / "artifacts"
        if (fixture_dir / "extract" / "pages.jsonl").exists():
            target_work_dir = fixture_dir

    return transform_artifacts_to_site_data(
        work_dir=target_work_dir,
        raw_scans_dir=raw_scans_dir,
        web_dir=web_dir,
        assert_real=False,
    )
