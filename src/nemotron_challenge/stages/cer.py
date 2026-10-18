"""Character error rate (CER) of Parse text against hand transcriptions (issue #2, step 7).

Each gold file holds the first 150 to 200 body words of one page, typed from the scan
(rules in artifacts/extract/gold/README.md). The alignment is a fitting alignment: the gold
text must be matched in full, but the Parse text may start and stop anywhere at no cost.
So the transcriber's stopping point does not matter, and an extra block before the body
does not count as an OCR error. pred_start reports where the match begins, so a reading
order problem is still visible.

CER = edit distance / gold characters, after both texts are lowercased, the long s is
mapped to s, and whitespace is collapsed. Punctuation counts.
"""
from __future__ import annotations

from collections import Counter
from pathlib import Path
import random
import re
from typing import Any

SEED = 7
PAGES = 5
MIN_WORDS = 150
TOP_SUBSTITUTIONS = 10


def page_text(page: dict[str, Any], entries_by_id: dict[str, dict[str, Any]]) -> str:
    """The page's body text in reading order: every non-plate entry's normalized text."""
    return " ".join(entries_by_id[eid]["text"] for eid in page["entry_ids"] if entries_by_id[eid]["kind"] != "plate")


def select_pages(pages: list[dict[str, Any]], entries_by_id: dict[str, dict[str, Any]]) -> list[int]:
    """5 random ok pages (seed 7) among pages with at least 150 body words."""
    eligible = sorted((p for p in pages if p["status"] == "ok" and len(page_text(p, entries_by_id).split()) >= MIN_WORDS),
                      key=lambda p: p["row_index"])
    chosen = random.Random(SEED).sample(eligible, min(PAGES, len(eligible)))
    return sorted(p["row_index"] for p in chosen)


def clean(text: str) -> str:
    return re.sub(r"\s+", " ", text.replace("ſ", "s").lower()).strip()


def align(gold: str, pred: str) -> dict[str, Any]:
    """Fitting alignment of all of gold inside pred. Returns distance, match span, and substitutions."""
    n, m = len(gold), len(pred)
    previous = [0] * (m + 1)                    # free start in pred
    ops = [bytearray(b"\x03" * (m + 1))]        # 0 diagonal, 1 gold char missing, 2 extra pred char, 3 start
    for i in range(1, n + 1):
        current = [i] + [0] * m
        row = bytearray(m + 1)
        row[0] = 1
        g = gold[i - 1]
        for j in range(1, m + 1):
            diagonal = previous[j - 1] + (g != pred[j - 1])
            missing = previous[j] + 1
            extra = current[j - 1] + 1
            if diagonal <= missing and diagonal <= extra:
                current[j] = diagonal
            elif missing <= extra:
                current[j], row[j] = missing, 1
            else:
                current[j], row[j] = extra, 2
        ops.append(row)
        previous = current
    end = min(range(m + 1), key=lambda j: previous[j])  # free end in pred
    distance = previous[end]
    substitutions: Counter[tuple[str, str]] = Counter()
    i, j = n, end
    while i > 0:
        op = ops[i][j]
        if op == 0:
            if gold[i - 1] != pred[j - 1]:
                substitutions[(gold[i - 1], pred[j - 1])] += 1
            i, j = i - 1, j - 1
        elif op == 1:
            i -= 1
        else:
            j -= 1
    return {"distance": distance, "pred_start": j, "pred_end": end, "substitutions": substitutions}


def cer(gold: str, predicted: str) -> dict[str, Any]:
    gold, predicted = clean(gold), clean(predicted)
    if not gold:
        raise ValueError("gold text is empty")
    window = predicted[: 3 * len(gold) + 500]  # the gold text covers the start of the page
    result = align(gold, window)
    return {"cer": round(result["distance"] / len(gold), 4), "distance": result["distance"],
            "gold_chars": len(gold), "pred_start": result["pred_start"], "pred_end": result["pred_end"],
            "substitutions": result["substitutions"]}


def report(pages: list[dict[str, Any]], entries_by_id: dict[str, dict[str, Any]], gold_dir: Path) -> dict[str, Any]:
    """Per-page CER for the selected pages that have a gold file, plus the most frequent substitutions."""
    selected = select_pages(pages, entries_by_id)
    by_row = {p["row_index"]: p for p in pages}
    rows, missing = [], []
    total: Counter[tuple[str, str]] = Counter()
    distance = gold_chars = 0
    for row_index in selected:
        path = gold_dir / f"{row_index:04d}.txt"
        if not path.is_file() or not path.read_text(encoding="utf-8").strip():
            missing.append(row_index)
            continue
        result = cer(path.read_text(encoding="utf-8"), page_text(by_row[row_index], entries_by_id))
        total.update(result.pop("substitutions"))
        distance += result["distance"]
        gold_chars += result["gold_chars"]
        rows.append({"row_index": row_index, "page_id": by_row[row_index]["page_id"], "gold_path": path.as_posix(), **result})
    if not selected:
        status = "no eligible pages"
    else:
        status = "complete" if not missing else ("missing gold" if not rows else "partial")
    return {
        "status": status,
        "method": "fitting alignment of the full gold text inside the page's Parse text; lowercase, long s as s, "
                  "whitespace collapsed; CER = edit distance / gold characters",
        "selection": f"{PAGES} random ok pages with >= {MIN_WORDS} body words, seed {SEED}",
        "selected_rows": selected,
        "missing_gold_rows": missing,
        "pages": rows,
        "mean_cer": round(distance / gold_chars, 4) if gold_chars else None,
        "top_substitutions": [{"gold": g, "parse": p, "count": c} for (g, p), c in total.most_common(TOP_SUBSTITUTIONS)],
    }
