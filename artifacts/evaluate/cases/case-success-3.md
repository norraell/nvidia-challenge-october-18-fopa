# Case study

Case ID: case-success-3
Classification: success
Run record: artifacts/agent/runs/run-20261018T144825Z-q06-buttress-image.json
Code revision: d0d0b26dfd89609e3bb40ac51d157fafcd565e92
Model: nvidia/Nemotron-3.5-Super-VL
Finish reason: stop

## Question

This image is a crop from a Britannica page. Which entry is it? Find that entry in the saved artifacts and compare it with its matched Wikipedia article.

## Evidence

Citations in the run record:

- Britannica `e2250-02`: "BUTTRESS, a kind of batment built archwife, or a mals of flouse or birds, ferving to prop of flapper the fides of a building, wall, 6e, on the outside"
- Wikipedia `663464@1346148586`: "A buttress is an architectural structure built against or projecting from a wall which serves to support or reinforce the wall."

Tool calls: 4 recorded, 0 with errors. The raw calls and model reply are in the run record.

Evidence checks. Observations read the saved records. Inferences apply a rule and need review.

| Check | Kind | Result | Detail |
| --- | --- | --- | --- |
| model_id | observation | pass | reply model 'nvidia/Nemotron-3.5-Super-VL' |
| finish_reason | observation | pass | finish_reason 'stop' |
| tool_calls | observation | pass | 4 tool calls without errors (challenge_compare, challenge_find_entry, challenge_get_article, challenge_get_entry) |
| citations_present | observation | pass | 2 citations in the run record |
| citations_resolve | observation | pass | all 2 citation ids resolve to saved records |
| citation_quotes | observation | pass | quotes found in saved source text |
| answer_cites | inference | pass | answer text mentions every citation id |
| uncertainty_claim | inference | noted | no missing-evidence or uncertainty phrase in the answer |

## Result

Agent answer:

> The crop is the historical Encyclopaedia Britannica entry **e2250-02**, headword **“BUTTRESS”** (scan file `page-2250-75315f455009.jpg`, crop `artifacts/extract/crops/e2250-02.png`). The match stage accepted it as matched to the Wikipedia article **“Buttress”** (page_id `663464`, revision_id `1346148586`); the rerank margin was 1.719, above the threshold, though relevance scores indicate shared subject matter, not factual agreement.

Both sources agree on the core idea: a buttress is a support built on the outside of a wall to hold it up. Britannica defines it as “a kind of batment … serving to prop … the sides of a building, wall, &c. on the outside, where it is either very high, or has any considerable load to sustain on the other side, as a bank of earth” [B:e2250-02]. Wikipedia defines it as “an architectural structure built against or projecting from a wall which serves to support or reinforce the wall” [W:663464@1346148586].

They differ in detail. Britannica says buttresses are used against the angles of steeples and stone buildings, along walls of buildings with “great and heavy roofs” that would thrust the walls out unless thick, and “against the feet of fine arches” in old palaces and abbeys [B:e2250-02]. Wikipedia instead stresses lateral (sideways) forces from inadequately braced roof structures, notes buttresses are common on ancient (typically Gothic) buildings, and says “counterfort” is synonymous when referring to dams and retaining walls holding back earth [W:663464@1346148586]. Wikipedia also adds history (Eanna Temple, ancient Uruk, 4th millennium BC) and a ground-plan taxonomy (clasping/clamped, angled, setback, diagonal/“French”) absent from Britannica [W:663464@1346148586]; Britannica’s palace/abbey/arch examples are not in the Wikipedia excerpt. Note the Britannica text is OCR-normalized and retains long-s artifacts (e.g., “f” for “s”), so some words are garbled.

Classification source: run.label (team review recorded in the run record).
Reviewer notes: All checks pass. Super VL read the crop image, found e2250-02 with challenge_find_entry, read the entry and the matched article, and quoted both verbatim including OCR errors. Real image request confirmed.

No earlier attempt on this question.

Limits: the checks confirm ids, quotes, and the model reply. They do not confirm the facts in the answer.
