# Build your Hermes agent

Use your coding agent to develop this project.
Use Hermes Agent to run the comparison agent that your team builds.

The plugin registers four native Hermes tools: `brit_search`, `brit_entry`, `wiki_article`, and `challenge_compare`.
Each handler reads saved artifacts from `CHALLENGE_WORK_DIR` (default `artifacts/`).
Each handler returns a JSON string.
On failure it returns `{"error": "...", "evidence": "missing"}`.
`integrations/hermes/SOUL.md` holds the answer policy.

## Set up a separate profile

Install Hermes Agent with the [official instructions](https://hermes-agent.nousresearch.com/docs/getting-started/installation).
Record the installed version with `hermes --version`.
Run the following commands from the starter repository root.

Use a separate profile directory for the challenge:

```bash
export HERMES_HOME="$PWD/data/hermes"
mkdir -p "$HERMES_HOME/plugins"
cp integrations/hermes/config.example.yaml "$HERMES_HOME/config.yaml"
cp -R integrations/hermes/nemotron-challenge "$HERMES_HOME/plugins/"
cp integrations/hermes/SOUL.md "$HERMES_HOME/SOUL.md"
```

Hermes reads `$HERMES_HOME/SOUL.md` as the first part of the system prompt.
The config sets `tools.tool_search.enabled: "off"`, so Hermes shows the team tools to the model directly.
It sets `agent.coding_context: "off"`, so the model has no file or terminal tools.
It sets `agent.image_input_mode: native`, so `--image` files go into the user turn.

The tools-off runs use a second profile, `data/hermes-notools`.
The runner creates it from `config.yaml` and the plugin. It does not copy `SOUL.md`, so tools-off runs get no answer policy.
The runner writes `challenge_run.json` into the profile before each run. With `"tools": false` the plugin registers no tools.
The runner also starts that profile with the empty `context_engine` toolset.

Keep `data/hermes` out of Git.
It can contain conversations and credentials.
If that directory exists, inspect its contents before you replace its configuration.

The config uses the official [named custom provider interface](https://github.com/NousResearch/hermes-agent/blob/main/website/docs/integrations/providers.md#named-custom-providers).
It selects `nvidia/Nemotron-3.5-Super-VL` at `https://api.tokenfactory.nebius.com/v1`.
It declares tool and vision support.
It uses your `SUPER_API_KEY` through `key_env`.

Set `SUPER_API_KEY` in the starter's root `.env` file.
Use your own Nebius Token Factory account and key.

## Check registration

```bash
hermes plugins doctor integrations/hermes/nemotron-challenge --ci
hermes plugins enable nemotron-challenge
hermes plugins list
```

[Plugin Doctor](https://github.com/NousResearch/hermes-agent/blob/main/website/docs/developer-guide/plugins/index.md#validate-with-plugin-doctor) checks discovery, imports, and registration.
It does not call `handle_compare` or check comparison quality.

Start Hermes from the shell that set `HERMES_HOME`:

```bash
uv run python - <<'PY'
import os
from dotenv import load_dotenv

load_dotenv(".env", override=False)
os.execvp("hermes", ["hermes", "chat", "--toolsets", "nemotron_challenge"])
PY
```

Copy your changed plugin into the profile.
Restart Hermes.

## Complete the agent milestone

Work with your coding agent in `integrations/hermes/nemotron-challenge/__init__.py`.
Change the schema if your chosen tool boundary needs different inputs.
Implement `handle_compare` and define its result format.
Keep `plugin.yaml` and `register()` consistent when you add or rename tools.
Your team chooses its evidence checks, tool boundaries, stopping rules, and behavior when a source is missing.
Connect these tools to your own saved project artifacts and pipeline.

## Run the agent stage

Write questions to `artifacts/agent/questions.jsonl`, one JSON object per line:
`{"qid", "question", "entry_id"?, "image"?, "tools": true|false}`.
Run the stage:

```bash
uv run nemotron-challenge run agent
```

The runner reads `SUPER_API_KEY` from `.env`.
It finds Hermes through `HERMES_BIN`, `PATH`, or `~/.local/bin/hermes`.
Set `CHALLENGE_AGENT_QIDS=q1,q2` to run only some questions.
Each question starts `hermes chat --oneshot` and exports the session with `hermes sessions export`.
The runner saves one `RunRecord` per attempt in `artifacts/agent/runs/`.
It writes `artifacts/agent/env.json` with the Hermes version and the model ID from the reply.
A failed attempt also leaves a record, with the error in `notes`.
The runner fails a run if it finds the key value or an `Authorization` header in the record.

Check the question set before you run it:

```bash
uv run python -m nemotron_challenge.agent_review check
```

The check needs at least 14 questions, one image, two tools-on and tools-off pairs, and entries with status `rejected` or `no_candidates` and with `low_quality=true`.
It also needs one question without an `entry_id`.
It reports each missing item and each unknown `entry_id`.

After you read a run, set its label and notes:

```bash
uv run python -m nemotron_challenge.agent_review review RUN_ID --label failure --notes "The Wikipedia citation does not support sentence 2."
uv run python -m nemotron_challenge.agent_review review NEW_RUN_ID --label success --notes "Fixed the policy." --repairs OLD_RUN_ID
```

The command appends your notes to the notes that the runner wrote.
It changes no other field and refuses to write key material.
Keep the wrong runs.

The Hermes plugin runs in the Hermes Python environment.
That environment has no `lancedb`, so `brit_search` uses keyword search and says so in its result.
The plugin finds `nemotron_challenge` through `CHALLENGE_REPO_ROOT`.

Copy the plugin into the profile after each change.
Hermes uses the copy, not the repository folder.
Hermes starts a background gateway for each profile and keeps it for a short time.
The gateway keeps the old plugin code and the environment of the first client.
After a plugin change, stop it with `pkill -f "gateway run"` before the next run.
The plugin reads `work_dir`, `repo_root`, and `trace_file` from `challenge_run.json` first, then from the environment.

The `--image` flag does not work with `--format stream-json` in this Hermes version.
The runner uses `hermes chat -Q --image PATH` for questions with an `image` field.

Check real replies for the expected model ID and tool call.
Check the tool result and the final response against saved evidence.
Test a request with missing evidence.
If your agent uses image inputs, check a real image request.
The capability declarations in the config do not prove that the endpoint accepts either request.

Use the [native plugin guide](https://github.com/NousResearch/hermes-agent/blob/main/website/docs/developer-guide/plugins/index.md) for the plugin API.

Registration and config checks used Hermes [commit `6255980b`](https://github.com/NousResearch/hermes-agent/commit/6255980b191e87815be728dcae9a25a3f39a9308).
These checks made no model calls.
Run Plugin Doctor after a Hermes update.
