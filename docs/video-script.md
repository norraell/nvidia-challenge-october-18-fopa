# Two-minute video script

Use this script for the screen recording.
Read the quoted text aloud. Do the action in each "Screen" line at the same time.
The spoken text is about 300 words, which fits 2 minutes at a calm pace.

## Before you record

```sh
python3 -m http.server --bind 127.0.0.1 --directory web 8080
```

1. Open `http://127.0.0.1:8080/#viewer` in the browser.
2. Open a second tab at `http://127.0.0.1:8080/#match?e=e0261-02`. This is ENTOMOLOGY.
3. Zoom the browser to 125% so the scores are readable.
4. Keep `artifacts/evaluate/cases/case-success-1.md` open in an editor tab as a backup.

## Script

### 0:00 to 0:15 · What we built

Screen: Show the header. Point at the five tabs.

> "This is Britannica-Wiki Lens. We take 100 scanned pages of an old Britannica edition, extract 270 entries, and match each entry to a modern Wikipedia article. The site is static. All data comes from saved JSON."

### 0:15 to 0:35 · Archive Viewer (extract)

Screen: Open **Archive Viewer**. Hover over a bounding box. Open the PDF link.

> "Nemotron Parse 3.5 reads each scan and returns text with bounding boxes. We split the output into entries. 94 pages parsed, 3 were blank, 1 illegible, 2 failed. Every entry keeps its crop, and each page has a compiled LaTeX PDF."

### 0:35 to 1:20 · Match Explorer with ENTOMOLOGY (match)

Screen: Open **Match Explorer**. Select ENTOMOLOGY. Move left to right across the four cards.

> "Here is the match for ENTOMOLOGY. Card A is the Britannica entry and the exact queries we sent. We search by headword and by body text."

Screen: Point at card B.

> "Card B is the shared Wikipedia BM25 search. It is keyword-only. The hits are insect and spider species pages, because our body-text query contains words like thorax and abdomen."

Screen: Point at card C. Read the top titles. Do not look for Entomology here.

> "Card C is Embed VL. It shows only the top five by cosine, and they are all species pages. The real Entomology article ranks 39th with a cosine of 0.16. The OCR text is mostly specimen descriptions, so its vector looks like an insect, not like the word entomology."

Screen: Point at card D. Point at the green row and the `#39→#1` label.

> "Card D is Rerank VL. Entomology reaches it because we always keep an exact title match. It then jumps from 39th to 1st with a logit of minus 3.2. Our rule accepts a match when the top logit is at least minus 5 and the margin to the second is at least 0.75. The margin here is 1.9."

### 1:20 to 1:35 · Agent Console (agent)

Screen: Open **Agent Console**. Open the ENTOMOLOGY run. Show the tool calls and the two citations.

> "A Hermes agent on Super 3.5 VL answers questions with four tools. For ENTOMOLOGY it quotes both sources and says the Britannica text holds specimen descriptions, not a definition. We check ids and quotes against saved text."

### 1:35 to 2:00 · Where we are stuck

Screen: Stay on the Match Explorer. Optionally switch to `artifacts/match/ablation.json`.

> "Three limits. First, recall. Only 22 of 159 headword entries match. Often the right article is not in the BM25 pool, and a reranker cannot recover a missing candidate. Second, OCR. Our character error rate is 14 percent on the one gold page we corrected. The model repairs OCR errors inside quotes, so a quote can pass the text check and still differ from the scan. Third, the plate match XVII passes our rule but is wrong."

> "With more time we would add title-guess queries, check quotes against the crop image, and label more pairs."

## Technical facts to keep in mind

Each number below comes from a saved artifact.

| Fact | Source |
| --- | --- |
| 100 scans: 94 ok, 3 blank, 2 failed, 1 illegible | `artifacts/extract/coverage.json` |
| 270 entries: 159 entry, 83 continuation, 20 plate, 8 cross reference | `artifacts/extract/coverage.json` |
| Pipeline: BM25 top 20 per query, Embed VL keeps top 10, Rerank VL scores the kept set | `match/candidates.py` (`TOP_K`), `match/embed_stage.py` (`KEEP_TOP`) |
| Exact title match always reaches the reranker | `match/embed_stage.py` (`always_keep`) |
| Rule: `tau=-5`, `delta=0.75`, calibrated on 30 labeled pairs, precision 1.0, recall 0.75 | `artifacts/match/calibration.json` |
| Top-1 accuracy on those 30 pairs: BM25 6.7%, plus Embed 20%, plus Rerank 40% | `artifacts/match/ablation.json` |
| Result: 22 matched, 226 rejected, 12 no candidates, 10 skipped | `artifacts/match/matches.jsonl` |
| ENTOMOLOGY: entry `e0261-02`, article `59238@1353043526`, Embed rank 39, Rerank rank 1, logit -3.233, margin 1.877 | `artifacts/match/matches.jsonl` |
| Mean CER 0.1383, measured on one gold page (row 251) | `artifacts/extract/coverage.json` |
| ENTOMOLOGY agent run is `case-success-1` | `artifacts/evaluate/cases/case-success-1.md` |

Models: `nvidia/nemotron-3.5-parse`, `nvidia/llama-nemotron-embed-vl-1b-v2`, `nvidia/llama-nemotron-rerank-vl-1b-v2`, `nvidia/Nemotron-3.5-Super-VL`.

## Where we are stuck (detail for questions)

| Problem | What we know | What we would do next |
| --- | --- | --- |
| Low recall: 22 of 159 headword entries | The canonical article is often missing from the BM25 pool. Treatise pages such as ENTOMOLOGY have no definition text, so body-text queries return unrelated species pages. | Add title-guess queries from the headword and its variants. Add a dense retrieval step over a larger pool. |
| Weak ENTOMOLOGY signal | Embed rank 39 shows the OCR text does not look like the article. The accepted logit of -3.2 is low in absolute terms. | Embed the page crop with the text. Test `MATCH_PLATE_IMAGES` on entries, not only on plates. |
| OCR errors inside quotes | Mean CER is 0.1383 on one gold page. Four of five planned gold pages are missing. The quote check reads saved text, not the scan. Failure cases: BUTTRESS, ORATORY, HUGUENOTS. | Correct gold pages for the other four rows. Add a crop-based quote check. |
| Plate false positive | `e1845-01` (text `XVII.`) passes the rule but is not a real association. Image rerank did not stop it. | Add a plate-specific rule that needs a caption. |
| Small calibration set | 30 labeled pairs, 12 with a correct top-1 candidate. Recall 0.75 rests on 12 positives. | Label 100 or more pairs. |
| Comparison measures vocabulary only | The term log-ratio does not show factual agreement. OCR noise inflates Britannica-only terms. | Add claim-level comparison with cited sentences. |
| Hermes chats not recorded | The `agent` stage records runs through its own tool loop. Interactive Hermes sessions have no run records. | Record Hermes sessions as run records. |

## If you run over time

Cut these parts in this order:

1. The Archive Viewer PDF link.
2. The Agent Console section. Mention it in one sentence during the limits.
3. Card B detail in the Match Explorer.

Keep the ENTOMOLOGY walk-through and the limits. They show the method and the honest results.

## Stale values to fix before you submit

These files disagree with the current artifacts. Check them before you cite numbers.

- `artifacts/extract/coverage.json` reports LaTeX as `not compiled`, but `artifacts/extract/latex/` and `web/latex/` hold 94 PDFs.
- `HANDOVER.md` item 3 also says LaTeX is not compiled.
- `docs/submission.md` reports 14 agent runs over 10 questions. `artifacts/agent/runs/` holds 36 run files, labeled 20 success and 16 failure.
