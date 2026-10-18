"""Print each entry next to its reranker top candidate so a reader can label the match by hand.

Usage:
    uv run python scripts/label_matches.py artifacts/match/dev [--sample 30] [--seed 1] [--labels artifacts/match/labels.csv]

The script writes a labels template when the labels file does not exist. Fill the `label` column with
`correct` or `wrong`. Put the right page_id in `correct_page_id` when you know it, else leave it blank.
"""
from __future__ import annotations

import argparse
import csv
import json
import random
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from nemotron_challenge.contracts import EntryRecord, MatchRecord  # noqa: E402

FIELDS = ("entry_id", "page_id", "title", "label", "correct_page_id", "note")


def load(out_dir: Path) -> tuple[dict[str, EntryRecord], list[MatchRecord]]:
    entries_path = out_dir / "entries.jsonl"
    if not entries_path.exists():
        entries_path = out_dir.parent / "extract" / "entries.jsonl"
    entries = {e.entry_id: e for e in (EntryRecord.model_validate_json(l) for l in entries_path.read_text().splitlines() if l.strip())}
    records = [MatchRecord.model_validate_json(l) for l in (out_dir / "matches.jsonl").read_text().splitlines() if l.strip()]
    return entries, records


def top(record: MatchRecord):
    scored = [c for c in record.candidates if c.rerank_rank is not None]
    return min(scored, key=lambda c: c.rerank_rank) if scored else None


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("out_dir", type=Path)
    ap.add_argument("--sample", type=int, default=30)
    ap.add_argument("--seed", type=int, default=1)
    ap.add_argument("--labels", type=Path, default=Path("artifacts/match/labels.csv"))
    ap.add_argument("--chars", type=int, default=500)
    args = ap.parse_args()
    entries, records = load(args.out_dir)
    scorable = [r for r in records if top(r) is not None]
    kinds = {}
    for r in scorable:
        kinds.setdefault(entries[r.entry_id].kind, []).append(r)
    rng = random.Random(args.seed)
    sample: list[MatchRecord] = []
    for kind, rows in sorted(kinds.items()):  # spread the sample across kinds
        rng.shuffle(rows)
        sample.extend(rows[: max(1, round(args.sample * len(rows) / len(scorable)))])
    sample = sorted(sample[: args.sample], key=lambda r: r.entry_id)
    for r in sample:
        e, t = entries[r.entry_id], top(r)
        print("=" * 100)
        print(f"{r.entry_id}  kind={e.kind}  headword={e.headword!r}  status={r.status}")
        print(f"ENTRY: {e.text[: args.chars]}")
        print(f"TOP:   [{t.wiki.page_id}] {t.wiki.title}  logit={t.rerank_logit:.3f} cosine={t.embed_cosine:.3f} bm25_rank={t.bm25_rank}")
        print(f"       {t.excerpt[: args.chars]}")
        others = sorted((c for c in r.candidates if c.rerank_rank and c.rerank_rank <= 3), key=lambda c: c.rerank_rank)[1:]
        print("       next: " + " | ".join(f"[{c.wiki.page_id}] {c.wiki.title} ({c.rerank_logit:.2f})" for c in others))
    if not args.labels.exists():
        args.labels.parent.mkdir(parents=True, exist_ok=True)
        with args.labels.open("w", newline="") as f:
            w = csv.DictWriter(f, fieldnames=FIELDS)
            w.writeheader()
            for r in sample:
                t = top(r)
                w.writerow({"entry_id": r.entry_id, "page_id": t.wiki.page_id, "title": t.wiki.title, "label": "", "correct_page_id": "", "note": ""})
        print(f"\nwrote label template: {args.labels}")
    else:
        print(f"\nlabels file exists, left unchanged: {args.labels}")
    print(json.dumps({"sampled": len(sample), "scorable": len(scorable), "by_kind": {k: len(v) for k, v in kinds.items()}}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
