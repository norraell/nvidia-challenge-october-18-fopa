# Handover

Branch: `4-p3-agent-hermes-super-vl-tools-answer-policy-and-saved-run-records`
Last commit: `494c105` — agent: add 22 reviewed run records, env.json, handoff, tools-off note

Read `README.md`, `docs/challenge.md`, and `docs/milestones.md` before starting work.

---

## What is done

### Extract (DONE)

- 100 scans processed. 94 ok, 3 blank, 2 failed, 1 illegible.
- 270 entries: 159 `entry`, 83 `continuation`, 20 `plate`, 8 `cross_reference`.
- 94 `.tex` files in `artifacts/extract/latex/`, all 94 compiled to PDF with tectonic. A machine without tectonic keeps the committed PDFs.
- CER measured on one gold row (e0251); mean CER recorded in `artifacts/extract/coverage.json`.
- Crops for each entry in `artifacts/extract/crops/`.
- Source: `artifacts/extract/entries.jsonl`, `artifacts/extract/pages.jsonl`, `artifacts/extract/coverage.json`.

### Match (DONE)

- Method: BM25 candidate pool → Nemotron Embed VL cosine → Nemotron Rerank VL logit → threshold decision.
- Ablation on 30 labeled pairs: BM25 only 6.7%, +embed 20%, +rerank 40% top-1 accuracy.
- Calibration: `tau=-5`, `delta=0.75`, precision 1.0, recall 0.75 on the labeled sample.
- Result in `artifacts/match/matches.jsonl` (committed): 22 matched, 226 rejected, 12 no candidates, 10 skipped, from 270 entries.
- Source: `artifacts/match/calibration.json`, `artifacts/match/ablation.json`, `artifacts/match/labels.csv`.
- **The Wikipedia article cache is gitignored.** Re-run `match` on a clean checkout before running `compare` or the agent tools.

### Compare (DONE)

- Token log-ratio analysis over matched pairs.
- Cuts Wikipedia article text to 3× entry length before counting.
- Drops terms with combined count < 5 and standard stop words.
- Output: `artifacts/compare/drift.json`, `artifacts/compare/plots/terms.svg` (generated on `run compare`).
- Source: `src/nemotron_challenge/stages/compare.py` (`DONE = True`).

### Agent (DONE)

- Hermes v0.22.1, model `nvidia/Nemotron-3.5-Super-VL` (confirmed from replies).
- Toolset: `nemotron_challenge`. Tools-off runs use a sibling profile with `SOUL.notools.md`.
- 22 saved run records for 17 questions in `artifacts/agent/runs/`.
- 10 labeled `success`, 12 labeled `failure`. 4 runs used an image. 9 runs used no tools.
- Env snapshot: `artifacts/agent/env.json`.
- See `artifacts/agent/HANDOFF.md` for the full list of success/failure candidates and known issues.

### Site (DONE)

- `src/nemotron_challenge/stages/site.py` (`DONE = True`) reads all pipeline artifacts and writes `web/data/pages.json`, `web/data/drift.json`, `web/data/cases.json`.
- `web/data/pages.json` is committed and reflects the last `run site` output.
- `web/scans/` (100 scans), `web/latex/` (94 PDFs) and `web/crops/` are committed. `web/data/pages.json` holds all 100 real pages.

### Evaluate (DONE)

- `src/nemotron_challenge/stages/evaluate.py` (`DONE = True`) selects 3 success and 3 failure cases from saved runs and writes `artifacts/evaluate/`.
- Re-run `uv run nemotron-challenge run evaluate` after any change to the run records.

---

## Known issues

1. **OCR errors cause wrong answers.** Two failure cases (Huesca, Silius) show the model quoting verbatim OCR text that differs from the page image. A quote-match check passes while the claim is false. Detection requires reading the crop. This is documented in `artifacts/agent/HANDOFF.md` and in the run notes.

2. **Wikipedia article cache not committed.** `artifacts/match/cache/` is gitignored. A reader on a clean checkout cannot rerun agent tools without first running `uv run nemotron-challenge run match`. The match output (`matches.jsonl`) is committed.

3. **LaTeX (resolved).** All 94 PDFs compile with tectonic. A rerun of extract on a machine without tectonic had set `coverage.json` to "not compiled"; it now reports the PDFs it keeps instead.

4. **Scans (resolved).** `web/scans/` is committed. `data/raw/britannica` stays gitignored; run `uv run nemotron-challenge data fetch` to rebuild from scratch.

5. **Match coverage is low.** 22 matched from 270 entries at the chosen threshold. Precision is 1.0 on the labeled sample, but recall is 0.75. Consider loosening the threshold or adding more query strategies to increase coverage before the final submission.

---

## Remaining work

| Stage | Task |
|---|---|
| Match | Document how to regenerate the article cache (`run match`). |
| Evaluate | Rerun `uv run nemotron-challenge run evaluate` after any change to the 36 run records. |
| Submission | Fill in `templates/submission.md`. Record model IDs, data revisions, and known limits. |
| Submission | Record the six case studies (3 success, 3 failure) as required by the challenge brief. |
| Submission | Prepare the 3–5 minute video. |

---

## How to run each stage

```sh
uv run nemotron-challenge run extract    # OCR + entry segmentation + crops + LaTeX
uv run nemotron-challenge run match      # BM25 + embed + rerank + threshold decision
uv run nemotron-challenge run compare    # token log-ratio, drift.json, terms.svg
uv run nemotron-challenge run agent      # Hermes one-shot runs (needs SUPER_API_KEY in .env)
uv run nemotron-challenge run site       # write web/data JSON and copy assets
uv run nemotron-challenge run evaluate   # select 6 case studies, write artifacts/evaluate/
```

Run `uv run nemotron-challenge stages` to see the current completion status of each stage.
Run `uv run pytest` to check the starter infrastructure contracts.

---

## Key file locations

| Path | Contents |
|---|---|
| `artifacts/extract/entries.jsonl` | All 270 extracted entries |
| `artifacts/extract/pages.jsonl` | All 100 page records |
| `artifacts/extract/coverage.json` | Page and entry counts, CER, LaTeX status |
| `artifacts/match/calibration.json` | Chosen threshold (`tau=-5`, `delta=0.75`) |
| `artifacts/match/ablation.json` | Method comparison on 30 labeled pairs |
| `artifacts/agent/runs/` | 36 saved Hermes run records (20 labeled success, 16 failure) |
| `artifacts/agent/env.json` | Hermes version, model IDs, toolset |
| `artifacts/agent/HANDOFF.md` | P3 agent notes: success/failure candidates, known causes |
| `artifacts/agent/questions.jsonl` | Question set used for agent runs |
| `web/data/pages.json` | Site data (last `run site` output, committed) |
| `integrations/hermes/SOUL.notools.md` | Answer policy for tools-off runs |
| `docs/hermes.md` | Hermes setup and plugin installation |
| `docs/super-vl.md` | Token Factory key setup |
| `templates/submission.md` | Submission template |
