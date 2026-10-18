"""Tool schemas and dispatch shared by the Hermes plugin and the agent stage.

The schemas use the plain {name, description, parameters} shape. Hermes takes it as is.
The agent stage wraps each one as an OpenAI function tool for Super VL.
"""
from __future__ import annotations

import json
from typing import Any, Callable

from .evidence import DEFAULT_CHARS, MAX_CHARS, MAX_FIND, EvidenceError, EvidenceStore

TOOLSET = "nemotron_challenge"
MAX_RESULT_CHARS = 12000

_CHARS = {"type": "integer", "minimum": 1, "maximum": MAX_CHARS, "default": DEFAULT_CHARS,
          "description": "Characters of text to return."}
_OFFSET = {"type": "integer", "minimum": 0, "default": 0, "description": "Start offset into the text, for paging."}

TOOL_SCHEMAS: list[dict[str, Any]] = [
    {
        "name": "challenge_find_entry",
        "description": ("Search the extracted historical Britannica entries by headword or words in the text. "
                        "Returns entry ids, headwords, page ids, match status, and a short snippet. Use it first to "
                        "find the entry id for a topic."),
        "parameters": {
            "type": "object",
            "properties": {
                "query": {"type": "string", "minLength": 1, "maxLength": 200, "description": "A headword or a few words."},
                "limit": {"type": "integer", "minimum": 1, "maximum": MAX_FIND, "default": 8},
            },
            "required": ["query"], "additionalProperties": False,
        },
    },
    {
        "name": "challenge_get_entry",
        "description": ("Read the extracted text of one Britannica entry with its page id, scan file, quality flags, "
                        "and the saved match decision with the top Wikipedia candidates and their scores."),
        "parameters": {
            "type": "object",
            "properties": {"entry_id": {"type": "string", "pattern": "^e\\d{4}-\\d{2}$", "description": "Entry id such as e0013-01."},
                           "offset": _OFFSET, "max_chars": _CHARS},
            "required": ["entry_id"], "additionalProperties": False,
        },
    },
    {
        "name": "challenge_get_article",
        "description": ("Read the pinned Wikipedia article text for a matched page id, with its revision id, title, url, "
                        "and license. Only articles the match stage selected and verified are available."),
        "parameters": {
            "type": "object",
            "properties": {"page_id": {"type": "string", "pattern": "^[0-9]{1,20}$", "description": "Wikipedia page id."},
                           "offset": _OFFSET, "max_chars": _CHARS},
            "required": ["page_id"], "additionalProperties": False,
        },
    },
    {
        "name": "challenge_compare",
        "description": ("Compare one Britannica entry with its matched Wikipedia article: both texts, the match evidence, "
                        "shared terms, and the terms each source uses more, each with a quoted sentence. Reports "
                        "status no_match when the entry has no accepted article."),
        "parameters": {
            "type": "object",
            "properties": {"entry_id": {"type": "string", "pattern": "^e\\d{4}-\\d{2}$", "description": "Entry id such as e0013-01."},
                           "max_chars": _CHARS},
            "required": ["entry_id"], "additionalProperties": False,
        },
    },
]
TOOL_NAMES = tuple(schema["name"] for schema in TOOL_SCHEMAS)


def openai_tools() -> list[dict[str, Any]]:
    return [{"type": "function", "function": schema} for schema in TOOL_SCHEMAS]


def _int(args: dict[str, Any], name: str, default: int) -> int:
    value = args.get(name, default)
    if type(value) is bool or not isinstance(value, int):
        raise EvidenceError(f"{name} must be an integer")
    return value


def call_tool(store: EvidenceStore, name: str, args: dict[str, Any]) -> dict[str, Any]:
    """Run one tool. Raises EvidenceError for a bad request or missing evidence."""
    if not isinstance(args, dict):
        raise EvidenceError("tool arguments must be a JSON object")
    handlers: dict[str, Callable[[], dict[str, Any]]] = {
        "challenge_find_entry": lambda: store.find_entry(str(args.get("query", "")), _int(args, "limit", 8)),
        "challenge_get_entry": lambda: store.get_entry(str(args.get("entry_id", "")), _int(args, "offset", 0),
                                                       _int(args, "max_chars", DEFAULT_CHARS)),
        "challenge_get_article": lambda: store.get_article(str(args.get("page_id", "")), _int(args, "offset", 0),
                                                           _int(args, "max_chars", DEFAULT_CHARS)),
        "challenge_compare": lambda: store.compare(str(args.get("entry_id", "")), _int(args, "max_chars", DEFAULT_CHARS)),
    }
    if name not in handlers:
        raise EvidenceError(f"unknown tool {name}; available: {', '.join(TOOL_NAMES)}")
    return handlers[name]()


def dispatch(store: EvidenceStore, name: str, args: dict[str, Any]) -> tuple[str, str | None]:
    """Return (result_json, error). Errors are returned to the model as data, never raised to it."""
    try:
        result = call_tool(store, name, args)
    except EvidenceError as exc:
        return json.dumps({"error": str(exc)}, ensure_ascii=False), str(exc)
    except (OSError, ValueError) as exc:
        message = f"{type(exc).__name__}: {exc}"
        return json.dumps({"error": message}, ensure_ascii=False), message
    text = json.dumps(result, ensure_ascii=False)
    if len(text) > MAX_RESULT_CHARS:
        text = json.dumps({**result, "truncated": True, "note": "result cut to the tool size limit; page with offset"},
                          ensure_ascii=False)[:MAX_RESULT_CHARS]
    return text, None
