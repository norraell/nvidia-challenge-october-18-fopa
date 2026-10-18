# Case study

Case ID: case-success-1
Classification: success
Run record: artifacts/agent/runs/run-20261018T144825Z-q01-entomology.json
Code revision: d0d0b26dfd89609e3bb40ac51d157fafcd565e92
Model: nvidia/Nemotron-3.5-Super-VL
Finish reason: stop

## Question

How does the historical Britannica entry on ENTOMOLOGY define and divide the subject, compared with the modern Wikipedia article? Quote both sources.

## Evidence

Citations in the run record:

- Britannica `e0261-02`: "ENTOMOLOGY. gentle suborfics, thorax marked with a large depressed circular spot; abdominal oval; legs equal."
- Wikipedia `59238@1353043526`: "is the branch of zoology that focuses on insects."

Tool calls: 3 recorded, 0 with errors. The raw calls and model reply are in the run record.

Evidence checks. Observations read the saved records. Inferences apply a rule and need review.

| Check | Kind | Result | Detail |
| --- | --- | --- | --- |
| model_id | observation | pass | reply model 'nvidia/Nemotron-3.5-Super-VL' |
| finish_reason | observation | pass | finish_reason 'stop' |
| tool_calls | observation | pass | 3 tool calls without errors (challenge_compare, challenge_find_entry, challenge_get_entry) |
| citations_present | observation | pass | 2 citations in the run record |
| citations_resolve | observation | pass | all 2 citation ids resolve to saved records |
| citation_quotes | observation | pass | quotes found in saved source text |
| answer_cites | inference | pass | answer text mentions every citation id |
| uncertainty_claim | inference | noted | no missing-evidence or uncertainty phrase in the answer |

## Result

Agent answer:

> The saved historical Britannica entry under the headword "ENTOMOLOGY" does not actually define or divide the subject of entomology. Its extracted text is OCR noise consisting of numbered descriptions of insect specimens (e.g., "Eyes placed thus," "thorax marked with," "A native of Europe"), with no statement of what entomology is or how it is subdivided [B:e0261-02]. So the comparison can only be drawn by quoting what the entry actually contains versus what the Wikipedia article says.

The modern Wikipedia article defines entomology explicitly: "Entomology, from Ancient Greek ἔντο몬 (éntomon), meaning "insect", and λόγος (lógos), meaning "study", is the branch of zoology that focuses on insects" [W:59238@1353043526]. It divides the field into branches such as forensic entomology ("studies insects found on corpses or elsewhere around crime scenes") and medical entomology ("focused upon insects and arthropods that impact human health") [W:59238@1353043526], and into order- or family-based subspecialties: "Many entomologists specialize in a single order or even a family of insects," listing Coleopterology (beetles), Dipterology (flies), Lepidopterology (moths and butterflies), Myrmecology (ants), and others [W:59238@1353043526].

In short, the Wikipedia article offers a clear definition and a taxonomy of subfields, whereas the saved Britannica entry text provides neither — it appears to be mis-extracted specimen descriptions rather than an encyclopedic definition of entomology [B:e0261-02].

Classification source: run.label (team review recorded in the run record).
Reviewer notes: All checks pass. The agent read e0261-02 and reported that the extracted text holds specimen descriptions, not a definition; both quotes are verbatim and the Wikipedia definition is from the matched article 59238@1353043526. The segmentation limit it reports is real: the page is a treatise table, not a headword entry.

No earlier attempt on this question.

Limits: the checks confirm ids, quotes, and the model reply. They do not confirm the facts in the answer.
