# Matching on corrected, modern text vs Parse text

Both runs use the same match stage, rule m1 (tau = -5, delta = 0.75), and the same 270 entries.
Only the entry text differs:

- **Parse text:** `artifacts/match/matches.jsonl` (P2's run on `artifacts/extract/entries.jsonl`).
- **Modern text:** `artifacts/match/modern/matches.jsonl` (this run on `artifacts/extract/entries.modern.jsonl`, the Super VL corrected and modernized text, meaning-checked with Embed VL).

Command for the modern run (no LanceDB writes, no article fetch, P2's outputs untouched):

```sh
MATCH_ENTRIES=artifacts/extract/entries.modern.jsonl MATCH_OUT_DIR=artifacts/match/modern \
  MATCH_TAU=-5 MATCH_DELTA=0.75 MATCH_STORE=0 MATCH_FETCH_ARTICLES=0 \
  uv run nemotron-challenge run match --work-dir artifacts
```

## Results

| | Parse text | Modern text |
| --- | --- | --- |
| Matched | 22 | 55 |
| Rejected | 226 | 194 |
| No candidates | 12 | 11 |
| Skipped | 10 | 10 |
| Median rerank logit of the top candidate | -6.40 | -5.31 |
| Top candidate title equals the headword (159 headword entries) | 49 | 46 |

The last row is a rough proxy (an exact title match only), the same for both runs.

## Newly matched (37), first-pass review

This is a first reading of entry and title only. It is **not** a verified label set. P2 should label these 37 entries and the 4 below before anyone quotes a precision figure.

- Look right (about 25): Political economy, Optics, Thistle, Thomism, Erfurt, Buxton, Buzzard, Hellebore, Thrace, Thrapston, Olney, Huéscar, Hugonia, Escalade, Eschar, Erigeron, Cabeiri, Byrrhus, Aternum, Athamanta, Tempo giusto, Achievement (heraldry), Hydrostatics (plate), Forlorn hope (ENFANS PERDUS), Litre (WEIGHTS AND MEASURES, partial).
- Look wrong (about 6): Energy (disambiguation), Roman conquest of Britain (ENGINEER), Helos (HELOTS), Glossary of Stoicism terms, Bus (disambiguation), Danas Run.
- Uncertain (about 6): Mollusc shell (CONCHOLOGY), Helston (UK Parliament constituency), Landkreis Thorn, Ergot (horse anatomy), Hel, Lom.

## No longer matched (4)

`e0251-01` (Switzerland, was correct), `e0258-03` (Williamsburg, was correct), `e2209-01` (title "Plate", was wrong), `e2473-06` (was wrong).

## Reading

The corrected, modern text raises recall a lot (22 to 55 matched) and the reranker scores its top candidates higher. Precision does not hold at the same threshold: tau and delta were calibrated on Parse's noisier text. Next step: label the 41 changed entries, then recalibrate with `scripts/calibrate_matches.py` before adopting the modern text for matching.
