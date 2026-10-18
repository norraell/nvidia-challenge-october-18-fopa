# Match stage: how to run it

The stage reads `EntryRecord` rows and writes one `MatchRecord` per entry.
It uses the shared Wikipedia BM25 API for candidates, Embed VL for a first semantic pass, and Rerank VL for the final ranking.
Rule m1 accepts the reranker's top candidate when its raw logit is at least `tau` and the margin to the second candidate is at least `delta`.
A relevance score never proves factual agreement between the two sources.

## Commands

```sh
sh scripts/check_retrieval.sh                    # confirm the GPU service is up
uv run nemotron-challenge run match --work-dir artifacts
```

Without options the stage reads `artifacts/extract/entries.jsonl` and writes to `artifacts/match/`.
Options are environment variables, so the CLI signature stays fixed:

| Variable | Default | Meaning |
| --- | --- | --- |
| `MATCH_ENTRIES` | `<work-dir>/extract/entries.jsonl` | input rows |
| `MATCH_OUT_DIR` | `<work-dir>/match` | output directory |
| `MATCH_CACHE_DIR` | `<work-dir>/match/cache` | search replies and full article text, gitignored |
| `MATCH_TAU`, `MATCH_DELTA` | `2.1`, `0.4` | rule m1 thresholds, recorded in `method_version` |
| `MATCH_LIMIT` | all | process only the first N entries |
| `MATCH_FETCH_ARTICLES` | `1` | fetch and verify full articles for matched entries |
| `MATCH_REFETCH_ARTICLES` | `0` | ignore the article cache |
| `MATCH_STORE` | `1` | write entry and article vectors to LanceDB at `CHALLENGE_DB_PATH` |
| `MATCH_PLATE_IMAGES` | `0` | rerank plates a second time with the scan image in each document |
| `MATCH_REDECIDE` | `0` | re-apply thresholds to stored scores, no embed or rerank calls |

Development run from raw Parse output while extract is unfinished:

```sh
uv run python -c "from pathlib import Path; from nemotron_challenge.match.inputs import *; \
  write_entries(Path('artifacts/match/dev/entries.jsonl'), bootstrap_entries_from_raw(Path('artifacts/extract/raw'), Path('artifacts/extract/parse_metrics.jsonl')))"
MATCH_ENTRIES=artifacts/match/dev/entries.jsonl MATCH_OUT_DIR=artifacts/match/dev MATCH_PLATE_IMAGES=1 \
  uv run nemotron-challenge run match --work-dir artifacts
```

Calibrate after a run. All scores are stored, so this step makes no model call:

```sh
uv run python scripts/label_matches.py artifacts/match/dev --sample 30     # prints pairs, writes labels.csv template
# fill label (correct|wrong) and correct_page_id in artifacts/match/labels.csv
uv run python scripts/calibrate_matches.py artifacts/match/dev             # writes calibration.json and ablation.json
MATCH_REDECIDE=1 MATCH_TAU=<tau> MATCH_DELTA=<delta> MATCH_ENTRIES=artifacts/match/dev/entries.jsonl \
  MATCH_OUT_DIR=artifacts/match/dev uv run nemotron-challenge run match --work-dir artifacts
```

## Outputs

| File | Content |
| --- | --- |
| `matches.jsonl` | one `MatchRecord` per entry, every pooled candidate with BM25, cosine, and logit scores |
| `candidates.jsonl` | per entry: the three queries, cache hits, which query found each page, retry attempts, plate image logits |
| `articles.jsonl` | one row per distinct matched article: page_id, revision_id, title, url, text_sha256, total_chars |
| `cache/articles/<page_id>.json` | full article text with provenance, verified by sha256, gitignored |
| `report.json`, `REPORT.md` | coverage, omissions, repeated articles, failed calls |
| `run-failed.json` | written instead of `matches.jsonl` when a service stays down |

LanceDB tables at `CHALLENGE_DB_PATH`: `entries` (`entry_id`, `vector`, `text_sha256`, `page_id`) and
`articles` (`page_id`, `revision_id`, `vector`, `text_sha256`, `title`). Vectors are 2048 floats from Embed VL.

## Decisions

See `docs/match-plan.md` section 3. Continuations copy the head entry's match with `status=skipped`.
Cross references are skipped. Plates search with their caption text. Entries without BM25 hits are `no_candidates`.
A `422` token overflow after the text is cut twice is recorded as `rejected` with an `error:` reason, never as an invented score.

## Calibrated values (dev run, 2026-10-18)

`artifacts/match/calibration.json`: tau=-5.0, delta=0.75 from 30 hand-labeled entries, precision 1.0, recall 0.75.
Raw reranker logits on this service are negative for every candidate, so the fixture value tau=2.1 accepts nothing.
`artifacts/match/ablation.json`: top-1 correct on the same 30 labels is 2 for BM25 alone, 6 with the embedder, 12 with the reranker.
Labels were assigned by the coding agent reading each entry against its full candidate pool. Review them before you cite them.

Known limits seen in `artifacts/match/dev/`:

- Dictionary range pages carry 8 to 15 short entries. One pseudo entry per page cannot match them all. Real segmentation from extract fixes this.
- The canonical article is often absent from the BM25 pool (Mount Etna, Chivalry, Kalmyks, Assay). A reranker cannot recover a missing candidate.
- A plate whose caption is only `XVII.` matched `XVII Reserve Corps (German Empire)` with margin 1.11. The image rerank did not prevent it. Keep this as a failure case.
- Page 0546 is a Parse repetition loop. Its text is not from the scan, so no match can be right.
