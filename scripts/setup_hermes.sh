#!/bin/sh
# Create the separate Hermes profile for the challenge and install the plugin into it.
# Run from the repository root: sh scripts/setup_hermes.sh
set -eu
export HERMES_HOME="${HERMES_HOME:-$PWD/data/hermes}"
mkdir -p "$HERMES_HOME/plugins"
cp integrations/hermes/config.example.yaml "$HERMES_HOME/config.yaml"
rm -rf "$HERMES_HOME/plugins/nemotron-challenge"
cp -R integrations/hermes/nemotron-challenge "$HERMES_HOME/plugins/"
echo "HERMES_HOME=$HERMES_HOME"
hermes --version
hermes plugins enable nemotron-challenge
hermes plugins list --plain --no-bundled
HERMES_PYTHON="$(dirname "$(readlink -f "$(command -v hermes)")")/python"
"$HERMES_PYTHON" scripts/check_hermes_plugin.py
cat <<'MSG'
Start a chat with the tools (reads SUPER_API_KEY from .env):
  export HERMES_HOME="$PWD/data/hermes"
  uv run python -c 'import os; from dotenv import load_dotenv; load_dotenv(".env"); os.execvp("hermes", ["hermes", "chat", "--toolsets", "nemotron_challenge"])'
MSG
