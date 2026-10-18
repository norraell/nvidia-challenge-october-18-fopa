# Case study

Case ID: case-failure-3
Classification: failure
Run record: artifacts/agent/runs/run-20261018T144825Z-q05-huguenots.json
Code revision: d0d0b26dfd89609e3bb40ac51d157fafcd565e92
Model: nvidia/Nemotron-3.5-Super-VL
Finish reason: stop

## Question

How does Britannica explain the origin of the name HUGUENOTS, and what does Wikipedia say about the same question?

## Evidence

Citations in the run record:

- Britannica `e1327-08`: "The name had its first rise in 1560; but authors are"
- Wikipedia `75899@1352397655`: "A term used originally in derision, Huguenot has unclear origins. Various hypotheses have been promoted."

Tool calls: 5 recorded, 0 with errors. The raw calls and model reply are in the run record.

Evidence checks. Observations read the saved records. Inferences apply a rule and need review.

| Check | Kind | Result | Detail |
| --- | --- | --- | --- |
| model_id | observation | pass | reply model 'nvidia/Nemotron-3.5-Super-VL' |
| finish_reason | observation | pass | finish_reason 'stop' |
| tool_calls | observation | pass | 5 tool calls without errors (challenge_compare, challenge_find_entry, challenge_get_article, challenge_get_entry) |
| citations_present | observation | pass | 2 citations in the run record |
| citations_resolve | observation | pass | all 2 citation ids resolve to saved records |
| citation_quotes | observation | fail | quotes not found in saved source text: Britannica:e1327-08 |
| answer_cites | inference | pass | answer text mentions every citation id |
| uncertainty_claim | inference | noted | no missing-evidence or uncertainty phrase in the answer |

## Result

Agent answer:

> ## Britannica on the origin of the name "Huguenots"

The historical Britannica entry (headword "HUGUENOTS") says the name was "an application given by way of concept to the referred or Protestant Calvinists of France," and that "The name had its first rise in 1560; but authors are…" [B:e1327-08]

Importantly, the saved Britannica text ends there — it cuts off mid-sentence at "but authors are," so the entry's full explanation of the name's origin is not present in the saved evidence. What survives only dates the name's first appearance to 1560 without completing the etymological account.

## Wikipedia on the same question

Wikipedia states that "A term used originally in derision, Huguenot has unclear origins. Various hypotheses have been promoted." [W:75899@1352397655] It then lays out several competing explanations:

- The term "may be derived from the name of a Swiss political leader, the Genevan burgomaster Besançon Hugues," and was in common use by around 1550 [W:75899@1352397655].
- It may be a derogatory pun combining Besançon Hugues with the Dutch word *Huisgenoten* ("housemates") and the German *Eidgenosse* ("Confederate," a citizen of the Swiss Confederacy) [W:75899@1352397655].
- Historian O. I. A. Roche described it as a combination of Dutch *Huis Genooten* and German *Eid Genossen* ("oath fellows"), Gallicized into "Huguenot" [W:75899@1352397655].
- Janet Gray's "Hugues hypothesis" derives it from Hugues Capet, king of France — roughly "little Hugos" or "those who want Hugo" [W:75899@1352397655].
- Paul Ristelhuber supported a Catholic origin: a legend of *le roi Huguet*, a sinister spirit haunting a gateway in Tours, after which Protestants who met secretly at night were called Huguenots [W:75899@1352397655].
- Reguier de la Plancha's account ties the name "huguenand" to the Amboise affair of 1560, when Protestants forced to meet at night were mockingly linked to night-roaming spirits [W:75899@1352397655].
- A further suggestion derives it, "with intended scorn, from *les guenon de Hus* (the 'monkeys' or 'apes of Jan Hus')" [W:75899@1352397655].

## Comparison

Britannica's surviving text only establishes that the name was applied to French Protestants/Calvinists and first appeared around 1560, but its origin explanation is cut off. Wikipedia, by contrast, explicitly treats the origin as unclear and surveys multiple hypotheses — a derivation from Genevan burgomaster Besançon Hugues, a Dutch/German pun (*Huisgenoten*/*Eidgenosse*), Hugues Capet, the Catholic *le roi Huguet* legend of Tours, the Amboise plot of 1560, and a possible reference to Jan Hus — while noting the term was originally used in derision.

Classification source: run.label (team review recorded in the run record).
Reviewer notes: citation_quotes fails. The quote changed the OCR word rife to rise. The answer correctly states that the saved entry ends mid-sentence. Repaired in run-20261018T145107Z-q05-huguenots.

No earlier attempt on this question. A later run `run-20261018T145107Z-q05-huguenots` repaired this question. This record keeps the failed attempt.

Limits: the checks confirm ids, quotes, and the model reply. They do not confirm the facts in the answer.
