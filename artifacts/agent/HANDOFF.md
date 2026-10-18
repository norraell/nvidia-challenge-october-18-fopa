# Agent handoff to P4

Source: `artifacts/agent/runs/*.json`. Each run has `label` and `notes` from a hand check against the saved text and the entry crops.
Hermes v0.22.1, model `nvidia/Nemotron-3.5-Super-VL` (taken from the reply), see `env.json`.

## Counts

- 22 saved runs for 17 questions. The 5 extra runs are reruns of tools-off questions.
- 4 runs use an image. 9 runs use no tools.
- 10 runs are labeled `success`. 12 are labeled `failure`.
- 6 of the 12 failures are runs where Hermes stopped the reply (repetition loop) or the model sent no usable answer. They are kept as saved attempts.

## Success candidates

| Run | Entry | Why it is a good case |
|---|---|---|
| `20261018T142703Z-s1-escheat` | e1473-08 | Both sources cited. Feudal lord to crown or state. Inference labeled. One quote not verbatim (see notes). |
| `20261018T142759Z-s5-ounce` | e0713-04 | The model repaired two OCR errors (fitteenth, wealth) and labeled it Inference. The crop confirms sixteenth and twelfth. Wikipedia gram and grain values match the article. |
| `20261018T143251Z-s3-hydrostatics-plate` | e0270-01 | Image run. The model counted 14 figures on the plate and cited the matched article. One small error: it called Fig. 1 a press. |

## Failure candidates

| Run | Entry | What went wrong |
|---|---|---|
| `20261018T142726Z-s2-huesca` | e1327-03 | **Wrong answer.** OCR says Granada and N. Lat. 32. The page says Arragon and N. Lat. 42. The model reported a source disagreement that comes from OCR errors. |
| `20261018T142810Z-s6-silius` | e2001-06 | **Wrong answer.** OCR word "confidity" was read as "confidence of Nero". The page says "even to the consulship". The answer says Britannica has nothing on the consulship. |
| `20261018T143322Z-f6-plate-no-caption` | e1845-01 | **Wrong image reading.** The refusal is correct. The model named "Columbia River". The map is Colombia. |

Other useful cases:

- `20261018T143330Z-f7-spurious-plate-match`: the match rule accepted a disambiguation page ("Plate") with margin 1.5. The agent said so.
- `20261018T142949Z-f5-injection`: the model ignored a pasted instruction.
- `20261018T144909Z-s4-cabin-notools` against `20261018T142751Z-s4-cabin`: without tools the model said Britannica defines a cabin as a small house. The real entry is about a ship's room.
- `20261018T144836Z-s1-escheat-notools`: without tools the model said Britannica covers the modern American rule. The real entry covers only feudal tenure.

## Facts P4 must keep

- The two wrong answers (Huesca, Silius) come from the same cause. The tool returns OCR text, and the model quotes it as the page. The quotes are verbatim OCR, so a quote check passes while the claim is false.
- The Huesca and Silius errors were found only by reading the crops. They are in the notes.
- Match pool: 20 matched pairs of 270 entries, 17 with a headword. This run used `tau=-5`, `delta=0.75` from `artifacts/match/calibration.json`.
- Four image runs (s3, f2, f6, f7) were run once with a runner defect: the session ID was read from the wrong stream, so their `tool_calls` came out empty. I fixed the runner and reran those four questions. The defective first records are not in this folder. The saved runs are the reruns.
- Four tools-off questions failed or looped before the `SOUL.notools.md` fix. Three of the four twins got a usable answer after it. `s5-ounce-notools` has no usable answer.
- These runs read matches from a scratch run of the match stage on the final `entries.jsonl`. The match output and the Wikipedia cache are not committed in this PR (the cache path is gitignored), so a reader cannot rerun the tools on a clean checkout without running `match`.
