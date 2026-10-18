# Evaluate stage

Entry point: `tasks.evaluate`.
Command: `uv run nemotron-challenge run evaluate`.

## Inputs

The stage reads saved artifacts from the work directory, `artifacts` by default:

- `agent/runs/*.json`: one `RunRecord` per Hermes run.
- `extract/entries.jsonl` and `extract/pages.jsonl`: used to resolve Britannica citations and count coverage.
- `match/matches.jsonl`: used to resolve Wikipedia citations and count match outcomes.
- `compare/drift.json`: used for comparison counts.
- `match/model-service-smoke.json`: optional record of the deployed embedder and reranker.

When `agent/runs` does not exist, the stage reads the starter fixtures and marks the report as fixture input.

## Label runs

The stage does not judge a run. The team does.
Set `label` in each run record to `success` or `failure` and write the reason in `notes`.
Runs with `label: unreviewed` are listed but not selected.

Keep a failed first attempt as its own run record.
Save the repaired run as a new record with the same question and a later `started_at`.
The stage links the two records and keeps both.

## Selection rule

The stage sorts labeled runs by `started_at`.
It selects up to three runs per label.
It prefers runs with distinct questions, then fills with earlier runs.
When fewer than three runs exist for a label, the status is `incomplete` and the report names the shortfall.

## Evidence checks

Each case carries checks on the saved record.
Observations read the record and the saved sources:
model ID, finish reason, tool call errors, citation presence, citation ID resolution, and quote lookup.
Inferences apply a rule and need a reviewer:
whether the answer mentions each citation ID, and whether the answer claims missing or uncertain evidence.
A check confirms ids, quotes, and the model reply. It does not confirm the facts in the answer.

## Outputs

- `evaluate/report.json`: `EvaluationReport` with the cases and the reproduction record.
- `evaluate/cases/<case_id>.md`: one case study per selected run, in the `templates/case-study.md` layout.
- `evaluate/README.md`: summary, reproduction commands, code revision, model IDs, data revisions, counts, and limits.

The reproduction record takes the code revision from `git rev-parse HEAD`.
It records the Python version, package versions, model IDs and revisions from `config.py`,
the Britannica manifest hash, and the Wikipedia snapshot revision.
It never includes API keys.
