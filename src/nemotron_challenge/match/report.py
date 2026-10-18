"""Coverage, omissions, repeated articles, and failures for the match run."""
from __future__ import annotations

from collections import Counter, defaultdict
import json
from pathlib import Path
from typing import Any

from ..contracts import EntryRecord, MatchRecord

DISCLAIMER = ("Relevance scores from BM25, the embedder, and the reranker show that two texts treat the same subject. "
              "They do not establish factual agreement between Britannica and Wikipedia.")


def _top(record: MatchRecord) -> dict[str, Any] | None:
    scored = [c for c in record.candidates if c.rerank_rank is not None]
    top = min(scored, key=lambda c: c.rerank_rank or 0) if scored else (record.candidates[0] if record.candidates else None)
    if top is None:
        return None
    return {"page_id": top.wiki.page_id, "title": top.wiki.title, "bm25_score": top.bm25_score,
            "embed_cosine": top.embed_cosine, "rerank_logit": top.rerank_logit}


def plate_image_table(logs: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """D6: for each plate, the reranker's top candidate with text only and with the scan image."""
    rows = []
    for log in logs:
        plate = log.get("plate_image")
        if not plate or not plate.get("logits"):
            continue
        text_top = min(plate["logits"], key=lambda r: r["text_rank"])
        image_top = min(plate["logits"], key=lambda r: r["image_rank"])
        rows.append({"entry_id": log["entry_id"], "text_top": text_top["title"], "text_logit": text_top["text_only"],
                     "image_top": image_top["title"], "image_logit": image_top["with_image"],
                     "same_top": text_top["page_id"] == image_top["page_id"],
                     "mean_shift": round(sum(r["with_image"] - r["text_only"] for r in plate["logits"]) / len(plate["logits"]), 3)})
    return rows


def load_side_files(out_dir: Path) -> dict[str, Any]:
    """calibration.json and ablation.json from the output directory or its parent, when present."""
    found: dict[str, Any] = {}
    for name in ("calibration", "ablation"):
        for folder in (out_dir, out_dir.parent):
            path = folder / f"{name}.json"
            if path.exists():
                found[name] = json.loads(path.read_text())
                break
    return found


def build_report(entries: list[EntryRecord], records: list[MatchRecord], *, failures: list[dict[str, Any]],
                 query_only_rescues: int, summary: dict[str, Any], logs: list[dict[str, Any]] | None = None,
                 side_files: dict[str, Any] | None = None) -> dict[str, Any]:
    by_id = {e.entry_id: e for e in entries}
    status_counts = Counter(r.status for r in records)
    kind_status: dict[str, Counter] = defaultdict(Counter)
    page_matched: dict[str, bool] = {}
    for r in records:
        entry = by_id.get(r.entry_id)
        kind = entry.kind if entry else "unknown"
        kind_status[kind][r.status] += 1
        page = entry.blocks[0].page_id if entry else "unknown"
        page_matched[page] = page_matched.get(page, False) or r.status == "matched"
    omissions = [{"entry_id": r.entry_id, "status": r.status, "reason": r.reason,
                  "headword": by_id[r.entry_id].headword if r.entry_id in by_id else None, "top_candidate": _top(r)}
                 for r in records if r.status in {"rejected", "no_candidates"}]
    article_entries: dict[str, list[str]] = defaultdict(list)
    for r in records:
        if r.match is not None:
            article_entries[r.match.page_id].append(r.entry_id)
    expected, suspicious = [], []
    for page_id, ids in article_entries.items():
        if len(ids) < 2:
            continue
        title = next(r.match.title for r in records if r.match and r.match.page_id == page_id)
        heads = {(by_id[i].headword or "").lower() for i in ids if i in by_id}
        statuses = {next(r.status for r in records if r.entry_id == i) for i in ids}
        row = {"page_id": page_id, "title": title, "entry_ids": ids, "headwords": sorted(heads)}
        (expected if statuses & {"skipped"} or len(heads) <= 1 else suspicious).append(row)
    return {
        "disclaimer": DISCLAIMER,
        "coverage": {
            "entries": len(records), "pages": len(page_matched),
            "pages_with_match": sum(1 for v in page_matched.values() if v),
            "by_status": dict(status_counts), "by_kind": {k: dict(v) for k, v in kind_status.items()},
        },
        "omissions": omissions,
        "repeated_articles": {"expected": expected, "suspicious": suspicious},
        "matches_rescued_by_content_query_only": query_only_rescues,
        "plates_text_vs_image": plate_image_table(logs or []),
        "calibration": (side_files or {}).get("calibration"),
        "ablation": (side_files or {}).get("ablation"),
        "failures": failures,
        "summary": summary,
    }


def render_markdown(report: dict[str, Any]) -> str:
    cov = report["coverage"]
    lines = ["# Match report", "", report["disclaimer"], "",
             f"Method: `{report['summary'].get('method_version')}`. Elapsed: {report['summary'].get('elapsed_seconds')} s.", "",
             "## Coverage", "",
             f"- Entries: {cov['entries']}", f"- Pages: {cov['pages']}, with at least one match: {cov['pages_with_match']}",
             "- By status: " + ", ".join(f"{k}={v}" for k, v in sorted(cov["by_status"].items())),
             "- By kind: " + "; ".join(f"{k}: " + ", ".join(f"{s}={n}" for s, n in sorted(v.items())) for k, v in sorted(cov["by_kind"].items())),
             f"- Matches found only by the content-words query: {report['matches_rescued_by_content_query_only']}", "",
             "## Omissions", "", "| entry | headword | status | top candidate | bm25 | cosine | logit |", "|---|---|---|---|---|---|---|"]
    for o in report["omissions"]:
        t = o["top_candidate"] or {}
        fmt = lambda v: "" if v is None else f"{v:.3f}"
        lines.append(f"| {o['entry_id']} | {o['headword'] or ''} | {o['status']} | {t.get('title', '')} | "
                     f"{fmt(t.get('bm25_score'))} | {fmt(t.get('embed_cosine'))} | {fmt(t.get('rerank_logit'))} |")
    lines += ["", "## Repeated article selections", ""]
    for label in ("expected", "suspicious"):
        rows = report["repeated_articles"][label]
        lines.append(f"### {label.title()} ({len(rows)})")
        lines += [f"- {r['title']} ({r['page_id']}): {', '.join(r['entry_ids'])}" for r in rows] or ["- none"]
        lines.append("")
    plates = report.get("plates_text_vs_image") or []
    lines += ["## Plates: reranker top candidate with text only and with the scan image", ""]
    if plates:
        lines += ["| entry | text-only top | logit | with image top | logit | same | mean logit shift |", "|---|---|---|---|---|---|---|"]
        lines += [f"| {r['entry_id']} | {r['text_top']} | {r['text_logit']:.2f} | {r['image_top']} | {r['image_logit']:.2f} | "
                  f"{'yes' if r['same_top'] else 'no'} | {r['mean_shift']:+.2f} |" for r in plates]
    else:
        lines.append("- no plate was reranked with an image in this run")
    lines.append("")
    cal = report.get("calibration")
    if cal:
        chosen = cal.get("chosen") or {}
        lines += ["## Calibration", "", f"Labeled entries: {cal.get('labeled')}, top-1 correct by reading: {cal.get('labeled_top1_correct')}.",
                  f"Chosen rule: tau={chosen.get('tau')}, delta={chosen.get('delta')}, precision {chosen.get('precision')}, "
                  f"recall {chosen.get('recall')} (tp={chosen.get('tp')}, fp={chosen.get('fp')}, fn={chosen.get('fn')}).", ""]
    abl = report.get("ablation")
    if abl:
        lines += ["## Ablation (top-1 accuracy on the labeled sample)", "", "| method | top-1 correct | accuracy |", "|---|---|---|"]
        lines += [f"| {k} | {v['top1_correct']} | {v['top1_accuracy']} |" for k, v in abl["methods"].items()]
        lines.append("")
    lines += ["## Failed calls", ""]
    lines += [f"- {f.get('at')} {f.get('entry_id', '')} {f.get('stage', '')}: {f.get('error')}" for f in report["failures"]] or ["- none"]
    lines.append("")
    return "\n".join(lines)
