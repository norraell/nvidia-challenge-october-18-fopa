"""Choose tau and delta from hand labels, and run the BM25 / embed / rerank ablation.

Usage:
    uv run python scripts/calibrate_matches.py artifacts/match/dev --labels artifacts/match/labels.csv \
        --out-dir artifacts/match [--min-precision 0.9]

Reads matches.jsonl (all scores are stored, so no model call is needed) and labels.csv with columns
entry_id,page_id,title,label,correct_page_id,note. Writes calibration.json and ablation.json.
"""
from __future__ import annotations

import argparse
import csv
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from nemotron_challenge.contracts import MatchRecord  # noqa: E402
from nemotron_challenge.match.decide import Thresholds, decide  # noqa: E402

TAU_GRID = [round(-9 + 0.25 * i, 2) for i in range(60)]
DELTA_GRID = [0.0, 0.1, 0.2, 0.3, 0.4, 0.5, 0.75, 1.0, 1.5, 2.0]


def read_labels(path: Path) -> dict[str, dict[str, str]]:
    with path.open(newline="") as f:
        rows = {r["entry_id"]: r for r in csv.DictReader(f)}
    for row in rows.values():
        if row["label"] not in {"correct", "wrong"}:
            raise SystemExit(f"label for {row['entry_id']} must be correct or wrong, got {row['label']!r}")
        if row["label"] == "correct" and not row.get("correct_page_id"):
            row["correct_page_id"] = row["page_id"]
    return rows


def top_by(record: MatchRecord, field: str) -> str | None:
    scored = [c for c in record.candidates if getattr(c, field) is not None]
    if field == "bm25_rank":
        scored = record.candidates
        return max(scored, key=lambda c: c.bm25_score).wiki.page_id if scored else None
    return min(scored, key=lambda c: getattr(c, field)).wiki.page_id if scored else None


def evaluate(records: list[MatchRecord], labels: dict[str, dict[str, str]], th: Thresholds) -> dict[str, float | int]:
    tp = fp = fn = tn = 0
    for r in records:
        lab = labels[r.entry_id]
        d = decide(r.entry_id, r.queries, r.candidates, th)
        accepted = d.status == "matched"
        correct = accepted and d.match is not None and d.match.page_id == lab["correct_page_id"]
        if accepted and correct:
            tp += 1
        elif accepted:
            fp += 1
        elif lab["label"] == "correct":
            fn += 1
        else:
            tn += 1
    precision = tp / (tp + fp) if tp + fp else 1.0
    recall = tp / (tp + fn) if tp + fn else 0.0
    return {"tau": th.tau, "delta": th.delta, "tp": tp, "fp": fp, "fn": fn, "tn": tn,
            "precision": round(precision, 3), "recall": round(recall, 3), "accepted": tp + fp}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("run_dir", type=Path)
    ap.add_argument("--labels", type=Path, default=Path("artifacts/match/labels.csv"))
    ap.add_argument("--out-dir", type=Path, default=Path("artifacts/match"))
    ap.add_argument("--min-precision", type=float, default=0.9)
    args = ap.parse_args()
    labels = read_labels(args.labels)
    records = [r for r in (MatchRecord.model_validate_json(l) for l in (args.run_dir / "matches.jsonl").read_text().splitlines() if l.strip())
               if r.entry_id in labels]
    missing = set(labels) - {r.entry_id for r in records}
    if missing:
        raise SystemExit(f"labels name entries that are not in matches.jsonl: {sorted(missing)}")
    grid = [evaluate(records, labels, Thresholds(tau=t, delta=d)) for t in TAU_GRID for d in DELTA_GRID]
    eligible = [g for g in grid if g["precision"] >= args.min_precision and g["tp"] > 0]
    best = max(eligible, key=lambda g: (g["recall"], g["precision"], g["tau"], g["delta"])) if eligible else None
    labeled_correct = sum(1 for l in labels.values() if l["label"] == "correct")
    calibration = {
        "labels_file": str(args.labels), "labeled": len(labels), "labeled_top1_correct": labeled_correct,
        "min_precision": args.min_precision, "chosen": best,
        "default_rule": evaluate(records, labels, Thresholds()),
        "grid_top": sorted(eligible, key=lambda g: (-g["recall"], -g["precision"]))[:15],
        "note": "Precision counts an accepted match as correct only when its page_id equals the labeled correct_page_id. "
                "A relevance score never proves factual agreement.",
    }
    ablation = {"labeled": len(labels), "methods": {}}
    for name, field in (("bm25_only", "bm25_rank"), ("bm25_embed", "embed_rank"), ("bm25_embed_rerank", "rerank_rank")):
        hits = sum(1 for r in records if top_by(r, field) is not None and top_by(r, field) == labels[r.entry_id]["correct_page_id"])
        ablation["methods"][name] = {"top1_correct": hits, "top1_accuracy": round(hits / len(records), 3)}
    ablation["note"] = ("Top-1 accuracy on the labeled sample for the candidate ranked first by BM25 score, by embedding cosine, "
                        "and by reranker logit. Candidates are the same pooled BM25 set in all three rows.")
    args.out_dir.mkdir(parents=True, exist_ok=True)
    (args.out_dir / "calibration.json").write_text(json.dumps(calibration, indent=2))
    (args.out_dir / "ablation.json").write_text(json.dumps(ablation, indent=2))
    print(json.dumps({"chosen": best, "default_rule": calibration["default_rule"], "ablation": ablation["methods"]}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
