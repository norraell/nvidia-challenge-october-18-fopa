# Case study

Case ID: case-success-2
Classification: success
Run record: artifacts/agent/runs/run-20261018T144825Z-q02-escheat.json
Code revision: d0d0b26dfd89609e3bb40ac51d157fafcd565e92
Model: nvidia/Nemotron-3.5-Super-VL
Finish reason: stop

## Question

Compare how Britannica and Wikipedia explain ESCHEAT: who receives the property and under what conditions. Cite the exact sentences.

## Evidence

Citations in the run record:

- Britannica `e1473-08`: "ESCHEAT, in law, signifies any lands or tenparts that cafinally fail to a Lord within his manor."
- Wikipedia `175519@1353158843`: "In feudal England, escheat referred to the situation where the tenant of a fee (or "fief") died without an heir or committed a felony."

Tool calls: 3 recorded, 0 with errors. The raw calls and model reply are in the run record.

Evidence checks. Observations read the saved records. Inferences apply a rule and need review.

| Check | Kind | Result | Detail |
| --- | --- | --- | --- |
| model_id | observation | pass | reply model 'nvidia/Nemotron-3.5-Super-VL' |
| finish_reason | observation | pass | finish_reason 'stop' |
| tool_calls | observation | pass | 3 tool calls without errors (challenge_find_entry, challenge_get_article, challenge_get_entry) |
| citations_present | observation | pass | 2 citations in the run record |
| citations_resolve | observation | pass | all 2 citation ids resolve to saved records |
| citation_quotes | observation | pass | quotes found in saved source text |
| answer_cites | inference | pass | answer text mentions every citation id |
| uncertainty_claim | inference | noted | no missing-evidence or uncertainty phrase in the answer |

## Result

Agent answer:

> ## Comparison: Who receives escheated property, and under what conditions

### Who receives the property

**Britannica (historical entry)** frames escheat as a return of land to the feudal lord: it "signifies any lands or tenparts that cafinally fail to a Lord within his manor," and where the tenant's bloodline ends or is corrupted, the land "cakes the hand echated or fell back to the lost of the cry" — i.e., it falls back to the lord of the fee.[B:e1473-08] The recipient is thus the **Lord of the manor/fee**.

**Wikipedia** gives the recipient as the **government or Crown** in modern terms: escheat "is a common law doctrine that transfers the real property of a person who has died without heirs to the government, or in the United Kingdom, crown."[W:175519@1353158843] In feudal England, the land was "technically owned by either the crown or the immediate overlord" when no heir existed; a felon's land reverted to the overlord after a year and a day, while treason forfeited land directly to the Crown.[W:175519@1353158843]

### Conditions for escheat

**Britannica** lists: (1) "the extinction of the blood of the latter by natural or civil means" — i.e., "death without heirs of his blood"; (2) "the tenant, by perpetrating an atrocious crime" (corruption of blood); and (3) "breach of the original condition, expressed or implied in the feudal donation."[B:e1473-08]

**Wikipedia** lists: (1) the tenant "died without an heir or committed a felony"[W:175519@1353158843]; (2) in modern usage, when "the person dies intestate without any other person capable of taking the property as heir," title transfers to the state[W:175519@1353158843]; and (3) a distinction Britannica does not draw — felony sends land to the overlord, but treason forfeits it to the Crown.[W:175519@1353158843]

**Key difference:** Britannica's historical entry centers on the feudal lord as recipient, triggered by failure of heirs, corruption of blood, or breach of feudal condition. Wikipedia adds the state/Crown as recipient, separates felony (overlord) from treason (Crown), and describes the modern doctrine as intestate succession failing entirely, with property passing to the state. Note: the Britannica text is OCR-noisy (e.g., "tenparts," "cafinally"), so its wording is quoted verbatim as extracted.[B:e1473-08]

Classification source: run.label (team review recorded in the run record).
Reviewer notes: All checks pass. Both quotes are verbatim, the three Britannica conditions and the Wikipedia felony versus treason distinction are in the cited texts, and the OCR noise is named instead of corrected.

No earlier attempt on this question.

Limits: the checks confirm ids, quotes, and the model reply. They do not confirm the facts in the answer.
