"""Load the challenge plugin through Hermes' own plugin manager and call one tool. No model call.

Run from the repository root after scripts/setup_hermes.sh:
  HERMES_HOME=$PWD/data/hermes "$(dirname "$(readlink -f "$(command -v hermes)")")/python" scripts/check_hermes_plugin.py
It replaces `hermes plugins doctor`, which Hermes 0.19 does not ship.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
import sys

EXPECTED = ("challenge_find_entry", "challenge_get_entry", "challenge_get_article", "challenge_compare")


def main() -> int:
    root = Path(__file__).resolve().parents[1]
    os.environ.setdefault("NEMOTRON_CHALLENGE_ROOT", str(root))
    os.environ.setdefault("HERMES_HOME", str(root / "data" / "hermes"))
    try:
        from hermes_cli.plugins import get_plugin_manager
        from tools.registry import registry
    except ImportError as exc:
        print(f"FAIL    import: run this script with the Hermes interpreter ({exc})", file=sys.stderr)
        return 1
    manager = get_plugin_manager()
    manager.discover_and_load(force=True)
    registered = sorted(manager._plugin_tool_names)
    missing = [name for name in EXPECTED if name not in registered]
    print(f"{'PASS' if not missing else 'FAIL':7} registration -> {registered}")
    if missing:
        print(f"        missing: {missing}", file=sys.stderr)
        return 1
    toolset = registry.get_tool_names_for_toolset("nemotron_challenge")
    print(f"{'PASS' if set(EXPECTED) <= set(toolset) else 'FAIL':7} toolset nemotron_challenge -> {sorted(toolset)}")
    reply = registry.dispatch("challenge_find_entry", {"query": "optics", "limit": 2})
    data = json.loads(reply) if isinstance(reply, str) else reply
    ok = isinstance(data, dict) and ("entries" in data or "error" in data)
    print(f"{'PASS' if ok else 'FAIL':7} dispatch challenge_find_entry -> {json.dumps(data)[:200]}")
    return 0 if ok and "error" not in data else 1


if __name__ == "__main__":
    raise SystemExit(main())
