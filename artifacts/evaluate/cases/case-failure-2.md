# Case study

Case ID: case-failure-2
Classification: failure
Run record: artifacts/agent/runs/run-20261018T144825Z-q04-oratory.json
Code revision: d0d0b26dfd89609e3bb40ac51d157fafcd565e92
Model: nvidia/Nemotron-3.5-Super-VL
Finish reason: stop

## Question

Compare the Britannica treatment of ORATORY with the Wikipedia article. Which terms does each source use that the other does not?

## Evidence

Citations in the run record:

- Britannica `e1933-02`: "And Cicero, in the charge which she brings against Mark Authority before the feature, makes life of this figure, when he fays"
- Britannica `e1933-02`: "As thus: _Ruse concord was left, friendship was left,_ _fidelity was left, liberty was left, all was left*."
- Wikipedia `350407@1056850807`: "Oratory is a type of public speaking."
- Wikipedia `350407@1056850807`: "Oratory (worship), a public or private place of divine worship, akin to a chapel The Oratory, Liverpool"

Tool calls: 3 recorded, 0 with errors. The raw calls and model reply are in the run record.

Evidence checks. Observations read the saved records. Inferences apply a rule and need review.

| Check | Kind | Result | Detail |
| --- | --- | --- | --- |
| model_id | observation | pass | reply model 'nvidia/Nemotron-3.5-Super-VL' |
| finish_reason | observation | pass | finish_reason 'stop' |
| tool_calls | observation | pass | 3 tool calls without errors (challenge_compare, challenge_find_entry, challenge_get_entry) |
| citations_present | observation | pass | 4 citations in the run record |
| citations_resolve | observation | pass | all 4 citation ids resolve to saved records |
| citation_quotes | observation | fail | quotes not found in saved source text: Britannica:e1933-02 |
| answer_cites | inference | pass | answer text mentions every citation id |
| uncertainty_claim | inference | noted | no missing-evidence or uncertainty phrase in the answer |

## Result

Agent answer:

> The Britannica entry (e1933-02, a heavily OCR-corrupted 1933 scan) treats "Oratory" as a discussion of rhetorical figures of repetition (e.g., sympleces, epanadiplosis), citing Cicero, St. Paul, and Anthony [B:e1933-02]. The matched Wikipedia article (page 350407, revision 1056850807) is a short disambiguation page: "Oratory is a type of public speaking," plus a list of other meanings (eloquence, rhetoric, worship chapels, and specific oratories) [W:350407@1056850807].

Terms Britannica uses that Wikipedia does not (from the term comparison): figure, cicero, anthony, authority, left, fame, abraham, begins, fays, find, following, word. Example: "And Cicero, in the charge which she brings against Mark Authority before the feature, makes life of this figure, when he fays..." [B:e1933-02]; "As thus: _Ruse concord was left, friendship was left,_ _fidelity was left, liberty was left, all was left*." [B:e1933-02].

Terms Wikipedia uses that Britannica does not: oratory, public, catholic, chapel, house, liverpool. Example: "Oratory is a type of public speaking." [W:350407@1056850807]; "Oratory (worship), a public or private place of divine worship, akin to a chapel The Oratory, Liverpool..." [W:350407@1056850807]. The only shared terms are "former," "good," and "roman."

Caveat: the Britannica text is OCR-degraded (e.g., "fays" for "says," "fame" for "same"), and the Wikipedia match is a disambiguation page rather than a substantive oratory article, so the term differences partly reflect genre and OCR noise rather than a clean substantive contrast.

Classification source: run.label (team review recorded in the run record).
Reviewer notes: citation_quotes fails. The second Britannica quote replaced an underscore with an asterisk, so it is not an exact copy. The answer also leans on a disambiguation-page match that the agent correctly called weak. Repaired in run-20261018T145107Z-q04-oratory.

No earlier attempt on this question. A later run `run-20261018T145107Z-q04-oratory` repaired this question. This record keeps the failed attempt.

Limits: the checks confirm ids, quotes, and the model reply. They do not confirm the facts in the answer.
