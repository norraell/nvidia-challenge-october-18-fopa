"""Native Hermes registration for the challenge evidence tools.

The handlers live in the repository package `nemotron_challenge.agent`. This plugin finds the repository
(NEMOTRON_CHALLENGE_ROOT, else the nearest parent of the working directory with pyproject.toml), adds its
`src` directory to sys.path, and reads artifacts from NEMOTRON_CHALLENGE_WORK_DIR (default <root>/artifacts).
Every tool reads saved files only. Errors return as {"error": ...} JSON so the model can report missing evidence.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
import sys
from typing import Any

TOOLSET = "nemotron_challenge"
_STORE: Any = None


def repo_root() -> Path:
    configured = os.environ.get("NEMOTRON_CHALLENGE_ROOT", "").strip()
    if configured:
        return Path(configured)
    for candidate in (Path.cwd(), *Path.cwd().parents):
        if (candidate / "pyproject.toml").exists() and (candidate / "src" / "nemotron_challenge").exists():
            return candidate
    return Path.cwd()


def _import_agent() -> tuple[Any, Any]:
    src = str(repo_root() / "src")
    if src not in sys.path:
        sys.path.insert(0, src)
    from nemotron_challenge.agent import evidence, tools  # noqa: PLC0415

    return evidence, tools


def _store() -> Any:
    global _STORE
    if _STORE is None:
        evidence, _ = _import_agent()
        work_dir = os.environ.get("NEMOTRON_CHALLENGE_WORK_DIR", "").strip() or str(repo_root() / "artifacts")
        _STORE = evidence.EvidenceStore(Path(work_dir))
    return _STORE


def _handler(name: str):
    def handle(params: dict[str, Any], **kwargs: Any) -> str:
        del kwargs
        try:
            _, tools = _import_agent()
            result, _ = tools.dispatch(_store(), name, params)
            return result
        except Exception as exc:  # the model must see the failure as data, not as a crash
            return json.dumps({"error": f"{type(exc).__name__}: {exc}"})

    handle.__name__ = f"handle_{name}"
    return handle


def _schemas() -> list[dict[str, Any]]:
    _, tools = _import_agent()
    return list(tools.TOOL_SCHEMAS)


TOOL_NAMES = ("challenge_find_entry", "challenge_get_entry", "challenge_get_article", "challenge_compare")
handle_compare = _handler("challenge_compare")


def register(ctx: Any) -> None:
    """Register every evidence tool through the native Hermes interface."""
    for schema in _schemas():
        ctx.register_tool(name=schema["name"], toolset=TOOLSET, schema=schema, handler=_handler(schema["name"]),
                          description=schema["description"], emoji="📚")
