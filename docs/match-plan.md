# Match stage plan

Written 2026-10-18 for the `match` milestone in `docs/milestones.md`.
Give this file to a coding agent in a new conversation together with `AGENTS.md`.

## 1. Goal

Turn each Britannica entry into a verified Wikipedia match or a recorded rejection.
Write one `MatchRecord` per entry to `artifacts/match/matches.jsonl`.
Keep every query, candidate, and score, so the decision can be audited later.
Use the shared Wikipedia BM25 API for candidates, Embed VL for a first semantic pass, and Rerank VL for the final ranking.

The stage must work before the extract stage is finished.
Section 5 explains the development inputs that make this possible.

## 2. Fixed facts the agent must respect

Read these files first: `README.md`, `docs/challenge.md`, `docs/milestones.md`, `docs/wikipedia-api.md`, `docs/model-service.md`, `src/nemotron_challenge/contracts.py`, `src/nemotron_challenge/clients.py`, `tests/fixtures/artifacts/`.

### Contracts (frozen, in `contracts.py`)

- Input: `EntryRecord` rows in `artifacts/extract/entries.jsonl`. Fields used by match: `entry_id`, `kind` (`entry`, `continuation`, `plate`, `cross_reference`), `headword`, `text`, `blocks[0].page_id`, `crop_path`, `continues_from`, `quality`.
- Output: `MatchRecord` rows, one per entry. `status` is one of `matched`, `rejected`, `no_candidates`, `skipped`. `reason` is the human readable rule that fired. `candidates` keeps every pooled candidate with `bm25_rank`, `bm25_score`, `excerpt`, `excerpt_offset`, and optional `embed_cosine`, `embed_rank`, `rerank_logit`, `rerank_rank`. `match` is a `WikiRef` or null. `rerank_margin` is top-1 logit minus top-2 logit. `method_version` names the rule and thresholds, for example `m1-tau=2.1-delta=0.4`.
- Contracts use `extra="forbid"` and `strict=True`. Floats must be floats, not ints. Validate every row with `MatchRecord.model_validate` before you write it.
- `tests/test_contracts.py::test_fixture_matches_validate` fixes the fixture shape: 5 rows, 3 matched, 1 rejected, 1 no_candidates. Do not change the fixture.

### Wikipedia API (`WikiClient`)

- `search(query, top_k, excerpt_chars)`: query up to 512 characters and 64 words, `top_k` 1 to 100, excerpt 100 to 2000 characters. BM25 over words. No query language. Redirect titles are absent, so `Ship-building` must become `Shipbuilding` by your own normalization.
- `article(page_id, offset, max_chars)`: `max_chars` 1 to 20000. Follow `next_offset` until null and concatenate in offset order. The client verifies `text_sha256` only when the article fits in one page. For longer articles, compute sha256 over the full UTF-8 text yourself and compare with `provenance.text_sha256`. Refuse to cache a mismatch.
- Limits: four active reads, ten second deadline, per peer rate limit shared through the proxy. On `429` or `503`, honor `Retry-After`, back off, and cap attempts. Never retry a `422` unchanged. Measured latency: about 0.5 s per search.

### Retrieval service (`RetrievalClient`, team deployment, URL in `.env`)

- `embed(inputs, input_type)`: 1 to 16 items per request. `query` items are text only, 512 token context. `document` items are text, image, or both, 8192 token text context, 2048 token image context. Vectors are 2048 floats, unit length. Do not add model prefixes.
- `rerank(query, documents, top_n)`: query text up to 2000 characters, 1 to 32 documents, scores are raw logits, not probabilities. Documents can include an image as a base64 data URL.
- Text must not contain `<image>`, `<img>`, `</img>`, or `<IMG_CONTEXT>`. Strip these from OCR text before any call.
- The service runs one request at a time with a queue of four. A full queue returns `429` with `Retry-After: 1`. Keep client calls sequential.
- Token overflow returns `422` and the service does not cut text. Cut entry text and article text in the pipeline before you send it.
- Receipts already exist: `artifacts/match/model-service-smoke.json` and `artifacts/receipts/`. Run `scripts/check_retrieval.sh` to confirm the service is up before a full run.

### Repository wiring

- Entry point: `src/nemotron_challenge/stages/match.py::run(settings, work_dir) -> dict`. The CLI calls it through `tasks.match` with `uv run nemotron-challenge run match --work-dir artifacts`.
- `tests/test_core_cli_storage.py::test_unfinished_stage_fails_with_guide_and_creates_no_result` is parametrized over all six stages. Remove `match` from that list when the stage runs. Add match tests in a new file.
- `Settings.db_path` points at `data/team.lancedb`, which is gitignored. `storage.py` has `LanceArtifactStore` for provenance records. Add your own vector tables next to it.
- `.gitignore` already ignores `artifacts/match/cache/`. Put the full article text cache there. Commit `matches.jsonl`, `candidates.jsonl`, labels, and reports.
- Dependencies are pinned in `pyproject.toml`. Add new packages with `uv add` and commit `uv.lock`.

### Source data already in the repo

- `artifacts/extract/raw/page-NNNN-<hash>.json`: raw Parse 3.5 output for 98 pages. Keys: `page`, `request`, `response`. The markdown with bbox and class tokens is at `response.choices[0].message.content`.
- `artifacts/extract/parse_metrics.jsonl`: per page `headers`, `titles`, `dict_rate`, `classes`, `is_plate_only`, `status`. Headers look like `292 SHIP-BUILDING.`, `WEIGHTS AND MEASURES.`, `HEL (781) HEM`.
- `data/raw/britannica/`: the 100 scans, 600 px wide JPEG.
- Page mix from the team plan: 26 treatise pages, 34 dictionary range pages with 8 to 15 headwords, 8 engraving plates, 30 pages with a number only or missing header, 2 Parse failures.

## 3. Method decisions

Each decision lists the options, the tradeoff, and the default to use unless the team says otherwise.

### D1. What is one match unit

- Option A: one match per `EntryRecord`. Matches the contract exactly. Dictionary pages produce 8 to 15 records each.
- Option B: one match per page. Simpler, but loses the dictionary headwords and violates the one-record-per-entry contract.
- Default: A. Treat `continuation` rows as follows: if `continues_from` names an entry with a decision, copy its `match` and write `status="skipped"`, `reason="continuation of <entry_id>"`. If the head entry is missing, search with the continuation text alone. Treat `cross_reference` rows as `skipped` with reason `cross reference`. Treat `plate` rows as normal entries whose text is the engraved caption, and see D6.

### D2. Candidate retrieval

- Build three queries per entry and pool the hits:
  1. The normalized headword or treatise title. Normalize: lowercase, join `word-word` into `wordword` and also keep `word word`, strip trailing punctuation, drop Roman numeral part markers, replace long s remnants (`f` before a consonant in a non-dictionary token is not safe to fix here, leave that to extract).
  2. Headword plus the 15 most informative content words from the entry text. Informative means not a stopword, 4 or more letters, present in a word list, highest term frequency in the entry.
  3. Content words only, 20 words. This rescues entries with a garbled or missing headword.
- Ask for `top_k=20` and `excerpt_chars=1000` on each query. Union by `page_id`, keep the best `bm25_rank` and `bm25_score` per page, and record which query produced each hit in `candidates.jsonl`.
- Tradeoff: more queries raise recall and cost about 1.5 s per entry. With roughly 400 entries that is about 10 minutes of search, which is acceptable. Cache search responses on disk keyed by sha256 of the query so reruns are free.

### D3. What to embed

- Option A: embed the Wikipedia excerpt from the search hit as the document. No article fetch before the decision. Cheap.
- Option B: fetch the first 8000 characters of every candidate article. Better signal, 20 to 60 article reads per entry, which will hit the four read limit.
- Default: A. Query is the entry text cut to about 1500 characters. Document is `title + "\n" + excerpt`. Batch 16 documents per embed call. Keep the top 10 by cosine for reranking. Record `embed_cosine` and `embed_rank` on every candidate, including the ones dropped.

### D4. How to rerank

- Query is the same entry text, cut to 2000 characters. Documents are the top 10 embed candidates as `title + "\n" + excerpt`. One rerank call per entry. Record `rerank_logit` and `rerank_rank` on each of the 10.
- Keep raw logits. Do not convert to probabilities.

### D5. Decision rule and rejection

- Rule m1: accept when `top1_logit >= tau` and `top1_logit - top2_logit >= delta`. Start with `tau=2.1`, `delta=0.4`, the values the fixture names. Record the rule and thresholds in `method_version` and the fired clause in `reason`.
- Calibrate after the first full run. Sample 30 entries across page kinds, hand label the top candidate as correct or wrong in `artifacts/match/labels.csv` with columns `entry_id,page_id,label,note`. Choose `tau` and `delta` that keep precision at or above 0.9 on the labeled set. Record the chosen values and the precision in `artifacts/match/calibration.json`.
- Ablation on the same 30 labels: top-1 correct for BM25 only, BM25 plus embed, BM25 plus embed plus rerank. Write `artifacts/match/ablation.json`. This proves both required models contribute.
- When BM25 returns no hits for all three queries, write `status="no_candidates"`. When the rule fails, write `status="rejected"` with the top candidate kept in `candidates` and `match=null`.
- A match score never proves factual agreement. Say so in the module docstring and in the report.

### D6. Plates with image documents (do this only after D1 to D5 run end to end)

- For `kind="plate"` entries, rerank with the scan image as part of the document: `{"text": title + excerpt, "image": data URL of the crop or page}`. The query stays the caption text. Compare against the text only logit and record both in `candidates`. Keep the image under 2048 image tokens, so downscale to about 1000 px on the long side.
- Tradeoff: this is the only place the VL capability is used. It costs one extra rerank call per plate, 8 plates in total.

### D7. Article cache and storage

- After a decision of `matched`, fetch the full article with pagination, verify sha256, and write `artifacts/match/cache/articles/<page_id>.json` with `page_id`, `revision_id`, `title`, `url`, `provenance`, `license`, `text`, `total_chars`, `fetched_at`.
- Write a committed index `artifacts/match/articles.jsonl` with one row per distinct article: `page_id`, `revision_id`, `title`, `url`, `text_sha256`, `total_chars`. Compare and agent read this index and the cache. A fresh clone rebuilds the cache with `run match --refetch-articles`.
- LanceDB at `Settings.db_path`: table `entries` with `entry_id`, `vector`, `text_sha256`; table `articles` with `page_id`, `revision_id`, `vector`, `text_sha256`. Embed articles as documents, cut to 8000 characters. The agent stage will search these tables.

## 4. Module layout

```
src/nemotron_challenge/match/
  __init__.py
  inputs.py       load EntryRecord rows, select by kind, dev bootstrap (section 5)
  queries.py      normalize headwords, pick content words, build the three queries
  candidates.py   WikiClient search with disk cache, retry with Retry-After, pool by page_id
  embed_stage.py  batch embed, cosine, keep top 10
  rerank_stage.py rerank call, text documents and plate image documents
  decide.py       rule m1, reason strings, method_version
  articles.py     paginated fetch, sha256 check, cache write, articles.jsonl
  store.py        LanceDB tables for entry and article vectors
  report.py       coverage, omissions, repeated articles, per kind counts
src/nemotron_challenge/stages/match.py   run(): wires the modules, writes outputs, returns a summary dict
tests/test_match_queries.py
tests/test_match_decide.py
tests/test_match_pipeline.py             fake WikiClient and RetrievalClient, fixture entries in, MatchRecord rows out
scripts/label_matches.py                 prints entry text next to top candidate excerpt for hand labeling
```

Keep each file under 400 lines. Keep functions pure where possible: pass clients in as arguments so tests can inject fakes.

The `run()` summary dict should contain: entries seen, counts per status, distinct articles, repeated article count, candidates per entry mean, embed and rerank call counts, failed calls with error strings, `method_version`, elapsed seconds, and the output paths.

## 5. Working before extract is finished

The real `artifacts/extract/entries.jsonl` may not exist when you start. Use two stand-ins, in this order.

1. Fixtures: `tests/fixtures/artifacts/extract/entries.jsonl` has 5 entries with real page IDs and headwords (Abacus, Barometer, and three more). Use them for unit tests and the first live smoke run.
2. Dev bootstrap from raw Parse output: `inputs.py::bootstrap_entries_from_raw(raw_dir, metrics_path)` builds one pseudo `EntryRecord` per parsed page. Headword is the cleaned page header from `parse_metrics.jsonl` (`292 SHIP-BUILDING.` becomes `SHIP-BUILDING`). Text is the page content with bbox and class tokens stripped by this regex family: `<x_[0-9.]+><y_[0-9.]+>` and `<class_[A-Za-z-]+>`. Blocks hold one block per Parse element. `quality` gets `{"dev_bootstrap": True}`.
   Write these to `artifacts/match/dev/entries.jsonl`. Never write them to `artifacts/extract/`. Run the pipeline on them with `run match --entries artifacts/match/dev/entries.jsonl --out-dir artifacts/match/dev`.
   When the real `entries.jsonl` lands, run without the flags. The code path is identical.

Add `--entries` and `--out-dir` options to `stages/match.py::run` through a small `MatchOptions` dataclass. Do not change the CLI signature `run(settings, work_dir)`; read options from environment variables `MATCH_ENTRIES` and `MATCH_OUT_DIR`, or add the flags to the `run` subparser in `cli.py` if the team agrees.

Agree with the extract owner on two things now: the `entry_id` format stays `e{row_index:04d}-{n:02d}`, and `headword` is null for continuations. Both are already in the contract.

## 6. Step by step

Each step ends with a check you can show to the team.

1. Read the files in section 2. Run `uv run pytest` and `sh scripts/check_retrieval.sh`. Save the retrieval check output to `artifacts/receipts/retrieval-check-<date>.txt`.
2. Write `queries.py` with tests. Cases: `292 SHIP-BUILDING.` gives `shipbuilding` and `ship building`; `HEL (781) HEM` is a dictionary range header and yields no headword query; a dictionary entry `ABACUS, among the ancients...` gives headword `abacus`; content words skip stopwords and OCR junk; reserved image markers are removed.
3. Write `candidates.py` with a disk cache under `artifacts/match/cache/search/`. Test the pool and dedupe logic with a fake client. Test the retry path with a fake that returns 429 once with `Retry-After: 1`.
4. Write `decide.py` with tests for all four statuses and the margin computation. Test that `method_version` encodes the thresholds.
5. Write `embed_stage.py` and `rerank_stage.py` with fakes that return fixed vectors and logits. Test batching at 16 and the 32 document cap. Test that text is cut before the call.
6. Write `stages/match.py::run` and `test_match_pipeline.py`. Feed the fixture entries through fakes and assert the output validates as `MatchRecord`, has one row per entry, and the summary dict has the counts. Remove `match` from the unfinished stage parametrize list.
7. Live smoke on the 5 fixture entries. Check the reply model IDs and revisions match `config.py`. Read the matched article titles. Save the run to `artifacts/match/dev/smoke-fixtures/`.
8. Build the dev bootstrap and run all 98 parsed pages. Record elapsed time and failures. Expect about 15 minutes. Write the report.
9. Hand label 30 entries with `scripts/label_matches.py`. Compute precision, pick `tau` and `delta`, write `calibration.json` and `ablation.json`. Rerun decisions from the saved candidates without new model calls. Rerunning the decision from stored scores must be possible, so store all scores.
10. Write `articles.py` and the LanceDB store. Fetch articles for matched entries. Verify every sha256. Write `articles.jsonl`.
11. Plates with image documents (D6). Compare logits with and without the image for the 8 plates and write a short table in the report.
12. When the real `entries.jsonl` exists, run the stage without dev flags, commit outputs, and hand the `articles.jsonl` path and the LanceDB table names to the compare and agent owners.

## 7. Reports the milestone asks for

`artifacts/match/report.json` and a short `artifacts/match/REPORT.md` with:

- Coverage: pages with at least one matched entry, entries per status, per `kind` and per page type.
- Omissions: entries with `rejected` or `no_candidates`, with the top candidate and its scores, so a reader can see what was missed.
- Repeated article selections: articles matched by more than one entry. Separate the expected repeats (continuations of the same entry) from the suspicious ones (two different headwords on the same article).
- Calibration and ablation tables.
- Failed calls with error text and timestamps.
- A sentence that relevance scores do not establish factual agreement.

## 8. Risks and fallbacks

- Retrieval service down or the DevLab stopped: the stage must fail with a clear error and write no partial `matches.jsonl`. Search caching means a rerun costs only model calls. Do not invent scores.
- Wikipedia rate limit: sequential requests, `Retry-After`, exponential backoff capped at 5 attempts, and the search cache.
- Token overflow `422` on long OCR entries: cut entry text to 1500 characters for embed and 2000 for rerank before the call. Log the cut length in `candidates.jsonl`.
- Headword OCR errors on dictionary pages: query 3 (content words only) is the rescue path. Report how many matches came only from query 3.
- Hyphenation and redirects: query normalization in D2. Add a short alias list only when a run shows a repeated miss, and record each alias with the entry that needed it.
- Time: steps 1 to 8 are the minimum. Steps 9 to 11 add the receipts that score points. Stop new features at the team freeze time and spend the rest on the report.

## 9. Prompt for the next conversation

Paste this into a fresh session in the repository root:

```
Read AGENTS.md, then read docs/match-plan.md in full. I own the match milestone.
Follow the plan's defaults unless I say otherwise. Start with section 6 step 1
and stop after each step to show me the check. The extract stage is owned by a
teammate and is not finished, so use the dev bootstrap in section 5 for real
runs. Keep all model calls real and record failures. Do not modify files under
tests/fixtures or src/nemotron_challenge/contracts.py.
```
