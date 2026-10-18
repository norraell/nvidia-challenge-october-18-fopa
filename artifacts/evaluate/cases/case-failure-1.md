# Case study

Case ID: case-failure-1
Classification: failure
Run record: artifacts/agent/runs/run-20261018T144825Z-q03-buttress.json
Code revision: d0d0b26dfd89609e3bb40ac51d157fafcd565e92
Model: nvidia/Nemotron-3.5-Super-VL
Finish reason: stop

## Question

What does the Britannica entry on BUTTRESS say about the purpose of a buttress, and does the Wikipedia article agree? Quote the evidence.

## Evidence

Citations in the run record:

- Britannica `e2250-02`: "serving to prop or support the sides of a building, wall, &c., on the outside, where it is either very high, or has any considerable load to sustain on the other side, as a bank of earth"
- Wikipedia `663464@1346148586`: "A buttress is an architectural structure built against or projecting from a wall which serves to support or reinforce the wall."

Tool calls: 3 recorded, 0 with errors. The raw calls and model reply are in the run record.

Evidence checks. Observations read the saved records. Inferences apply a rule and need review.

| Check | Kind | Result | Detail |
| --- | --- | --- | --- |
| model_id | observation | pass | reply model 'nvidia/Nemotron-3.5-Super-VL' |
| finish_reason | observation | pass | finish_reason 'stop' |
| tool_calls | observation | pass | 3 tool calls without errors (challenge_compare, challenge_find_entry, challenge_get_entry) |
| citations_present | observation | pass | 2 citations in the run record |
| citations_resolve | observation | pass | all 2 citation ids resolve to saved records |
| citation_quotes | observation | fail | quotes not found in saved source text: Britannica:e2250-02 |
| answer_cites | inference | pass | answer text mentions every citation id |
| uncertainty_claim | inference | noted | no missing-evidence or uncertainty phrase in the answer |

## Result

Agent answer:

> The Britannica entry (headword "BUTTRESS," entry e2250-02) defines a buttress as a mass built against the outside of a building or wall whose purpose is to prop/support the sides where the wall is "very high, or has any considerable load to sustain on the other side, as a bank of earth." It adds that buttresses are used at the angles of steeples and stone buildings, and along walls of buildings with "great and heavy roofs, which would be subject to [thrust] the walls out, unless very thick, if no buttresses were placed against them," and also "for a support ... against the feet of fine arches" in great halls of old palaces and abbeys.[B:e2250-02] (The text is an OCR-normalized scan, so "ſ" appears as "f" and "&c" as "6e"/"eC"; the meaning is "prop or support the sides ... on the outside ... considerable load to sustain on the other side.")

The matched Wikipedia article (page 663464, revision 1346148586) states: "A buttress is an architectural structure built against or projecting from a wall which serves to support or reinforce the wall. Buttresses are fairly common on more ancient (typically Gothic) buildings, as a means of providing support to act against the lateral (sideways) forces arising out of inadequately braced roof structures."[W:663464@1346148586]

So yes, the Wikipedia article agrees on the core purpose: a buttress is built against a wall to support/reinforce it, resisting lateral (sideways) forces—Britannica frames those forces as heavy roofs, banks of earth, and arch thrust, while Wikipedia frames them as lateral forces from inadequately braced roof structures. Britannica simply gives more specific historical examples (steeples, arches, palaces, abbeys, retaining earth).

Classification source: run.label (team review recorded in the run record).
Reviewer notes: citation_quotes fails. The Britannica quote was silently corrected from the OCR text (ferving to prop of flapper the fides became serving to prop or support the sides), so the quote is not in the source. The comparison itself is sound. Repaired in run-20261018T145107Z-q03-buttress after the prompt gained an explicit verbatim-OCR rule.

No earlier attempt on this question. A later run `run-20261018T145107Z-q03-buttress` repaired this question. This record keeps the failed attempt.

Limits: the checks confirm ids, quotes, and the model reply. They do not confirm the facts in the answer.
