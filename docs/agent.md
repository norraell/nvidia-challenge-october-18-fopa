# Agent stage: how to run it

Entry point: `tasks.agent`. Command: `uv run nemotron-challenge run agent`.

The agent answers comparison questions with evidence from the saved artifacts.
It calls `nvidia/Nemotron-3.5-Super-VL` on Nebius Token Factory through `ChatClient`.
The same four tools are registered in Hermes through `integrations/hermes/nemotron-challenge`.

## Tools

Every tool reads files that earlier stages wrote. No tool calls a model or the network.

| Tool | Input | Returns |
| --- | --- | --- |
| `challenge_find_entry` | `query`, `limit` | entries whose headword or text contains the query words, with match status |
| `challenge_get_entry` | `entry_id`, `offset`, `max_chars` | entry text, page id, scan file, quality flags, match decision, top candidates with scores |
| `challenge_get_article` | `page_id`, `offset`, `max_chars` | cached Wikipedia text for a matched page, verified against the saved sha256 and revision |
| `challenge_compare` | `entry_id`, `max_chars` | both texts, match evidence, shared terms, and the terms each source uses more, each with a quoted sentence |

`challenge_compare` returns `status: no_match` when the match stage accepted no article.
`challenge_get_article` refuses a page that the match stage did not select.
A bad request returns `{"error": ...}` so the model can report missing evidence.

## Evidence policy

The system prompt tells the model to call tools before it answers, to cite with `[B:<entry_id>]` and
`[W:<page_id>@<revision_id>]`, to say when evidence is missing or uncertain, and to treat source text as data.
The reply ends with a `CITATIONS:` JSON line. The runner stores it in `citations` with verbatim quotes.
The evaluate stage checks that each citation id resolves and that each quote appears in the saved sources.

The loop allows `AGENT_MAX_ROUNDS` tool rounds (default 8). After the limit it asks for an answer with tools off.
A model error, a cut-off reply, or an invalid tool call is saved under `agent/failed/` with the error text.
The stage never replaces a failed call with an invented result.

## Inputs and outputs

Questions come from `artifacts/agent/questions.json`, a JSON list of `{"id", "question", "image"?}`.
`image` is a crop path relative to the repository root. The crop goes to Super VL as an inline PNG.

| Output | Content |
| --- | --- |
| `agent/runs/<run_id>.json` | one `RunRecord`: model id from the reply, tool calls with results, answer, citations, finish reason |
| `agent/raw/<run_id>.json` | every raw reply and the request messages, with image data replaced by its length |
| `agent/failed/<run_id>.json` | a failed run with its error and the tool calls made before it |
| `agent/summary.json` | counts of the last stage run |

Options: `AGENT_QUESTIONS` (path), `AGENT_LIMIT`, `AGENT_ONLY` (comma-separated ids), `AGENT_MAX_ROUNDS`.

## Review

The stage writes every run with `label: unreviewed`. A person reads the record and the sources, then sets the label:

```sh
uv run python scripts/label_runs.py <run_id> success "why the evidence supports the answer"
uv run python scripts/label_runs.py <run_id> failure "what went wrong"
```

Keep a failed first attempt as its own record. Rerun the question and label the new record separately.
The evaluate stage links both.

## Hermes

```sh
sh scripts/setup_hermes.sh      # profile in data/hermes, plugin copied and enabled, registration check
export HERMES_HOME="$PWD/data/hermes"
uv run python -c 'import os; from dotenv import load_dotenv; load_dotenv(".env"); os.execvp("hermes", ["hermes", "chat", "--toolsets", "nemotron_challenge"])'
```

Hermes 0.19.0 has no `plugins doctor` command. `scripts/check_hermes_plugin.py` loads the plugin with the Hermes
plugin manager and dispatches one tool. It makes no model call.
