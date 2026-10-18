# Build your Hermes agent

Use your coding agent to develop this project.
Use Hermes Agent to run the comparison agent that your team builds.

The plugin registers four native Hermes tools over the team's saved artifacts:
`challenge_find_entry`, `challenge_get_entry`, `challenge_get_article`, and `challenge_compare`.
Read [agent.md](agent.md) for the tool contracts, the evidence policy, and the recorded stage runs.

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
```

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
sh scripts/setup_hermes.sh
```

The script copies the config and plugin into the profile, enables the plugin, and runs
`scripts/check_hermes_plugin.py` with the Hermes interpreter.
That check loads the plugin through the Hermes plugin manager and dispatches one tool.
Hermes 0.19.0 has no `plugins doctor` command.
If your Hermes version has it, you can also run `hermes plugins doctor integrations/hermes/nemotron-challenge --ci`.
Neither check calls a model or checks comparison quality.

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

## The agent milestone

The tool handlers live in `src/nemotron_challenge/agent/`.
The plugin in `integrations/hermes/nemotron-challenge/__init__.py` imports them from the repository.
It reads `NEMOTRON_CHALLENGE_ROOT` and `NEMOTRON_CHALLENGE_WORK_DIR`, or finds the repository from the working directory.
Keep `plugin.yaml`, `tools.TOOL_SCHEMAS`, and `register()` consistent when you add or rename tools.

The `agent` stage runs the saved question list through Super VL with the same tools and records each run.
Plugin registration does not run that stage.

Check real replies for the expected model ID and tool call.
Check the tool result and the final response against saved evidence.
Test a request with missing evidence.
If your agent uses image inputs, check a real image request.
The capability declarations in the config do not prove that the endpoint accepts either request.

Use the [native plugin guide](https://github.com/NousResearch/hermes-agent/blob/main/website/docs/developer-guide/plugins/index.md) for the plugin API.

Registration and config checks used Hermes Agent v0.19.0 (2026.7.20) installed with `uv tool install hermes-agent`.
These checks made no model calls.
Run `scripts/check_hermes_plugin.py` after a Hermes update.
