"""Check Super VL access on Token Factory with real requests: catalog, text, tool call, and image."""
from __future__ import annotations

import argparse
import base64
from datetime import datetime, timezone
import json
from pathlib import Path
import sys
import time
from typing import Any, Callable

import httpx

from .clients import ChatClient, ProtocolError, ServiceError
from .config import ConfigurationError, Settings
from .data import file_sha256

CHECKS = ("catalog", "text", "tool_call", "vision")
MAX_TOKENS = 1024
EXCERPT_CHARS = 300
IMAGE_TYPES = {".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".png": "image/png"}

LOOKUP_TOOL = {
    "type": "function",
    "function": {
        "name": "lookup_entry",
        "description": "Look up a historical Britannica entry by its headword.",
        "parameters": {
            "type": "object",
            "properties": {"headword": {"type": "string", "description": "The entry headword."}},
            "required": ["headword"],
        },
    },
}


def find_scan(scan_dir: Path) -> Path | None:
    scans = sorted(path for path in Path(scan_dir).glob("*") if path.suffix.lower() in IMAGE_TYPES)
    return scans[0] if scans else None


def image_data_url(path: Path) -> str:
    encoded = base64.b64encode(path.read_bytes()).decode()
    return f"data:{IMAGE_TYPES[path.suffix.lower()]};base64,{encoded}"


def explain(exc: Exception) -> str:
    """Turn a client error into the action a participant should take."""
    status = getattr(exc, "status_code", None)
    message = str(exc)
    if status in {401, 403}:
        return f"Token Factory rejected the key (HTTP {status}). Check SUPER_API_KEY in .env."
    if status == 402:
        return "Token Factory reports no credit (HTTP 402). Redeem your promo code and check the balance."
    if status == 429:
        return "Token Factory rate limit (HTTP 429). Wait, then run the check again."
    if "absent from the catalog" in message:
        return "Super VL is not in this account's model catalog. Ask an organizer to enable it."
    if "incomplete" in message:
        return "The reply was cut off before it finished (finish_reason was not 'stop')."
    return message


def _reply(result: dict[str, Any]) -> dict[str, Any]:
    choice = result["choices"][0]
    content = choice.get("message", {}).get("content") or ""
    return {"model": result.get("model"), "finish_reason": choice.get("finish_reason"),
            "usage": result.get("usage"), "excerpt": content.strip()[:EXCERPT_CHARS]}


def run_checks(client: ChatClient, scan: Path | None) -> list[dict[str, Any]]:
    """Run each check in order. Stop at the first failure and mark the rest as skipped."""

    def catalog() -> dict[str, Any]:
        client.verify_model()
        return {"model": client.model}

    def text() -> dict[str, Any]:
        return _reply(client.complete([{"role": "user", "content": "Reply with the single word READY."}],
                                      max_tokens=MAX_TOKENS))

    def tool_call() -> dict[str, Any]:
        result = client.complete(
            [{"role": "user", "content": "Use the lookup_entry tool to find the Britannica entry for OPTICS."}],
            max_tokens=MAX_TOKENS, extra_body={"tools": [LOOKUP_TOOL], "tool_choice": "auto"})
        reply = _reply(result)
        if reply["finish_reason"] != "tool_calls":
            raise ProtocolError("the model answered in text and made no tool call")
        call = result["choices"][0]["message"]["tool_calls"][0]["function"]
        if call["name"] != "lookup_entry":
            raise ProtocolError(f"the model called an unknown tool: {call['name']}")
        return {**reply, "tool": call["name"], "arguments": json.loads(call["arguments"])}

    def vision() -> dict[str, Any]:
        reply = _reply(client.complete([{"role": "user", "content": [
            {"type": "text", "text": "This is a scanned encyclopaedia page. What is the first headword on it? "
                                     "Answer with the headword only."},
            {"type": "image_url", "image_url": {"url": image_data_url(scan)}},
        ]}], max_tokens=MAX_TOKENS))
        return {**reply, "scan_file": scan.name, "scan_sha256": file_sha256(scan)}

    steps: list[tuple[str, Callable[[], dict[str, Any]] | None]] = [
        ("catalog", catalog),
        ("text", text),
        ("tool_call", tool_call),
        ("vision", vision if scan is not None else None),
    ]
    results: list[dict[str, Any]] = []
    for name, step in steps:
        if step is None:
            results.append({"name": name, "status": "skipped", "detail": "no scan image; run data fetch"})
            continue
        if any(result["status"] == "fail" for result in results):
            results.append({"name": name, "status": "skipped", "detail": "an earlier check failed"})
            continue
        started = time.monotonic()
        try:
            detail = step()
            results.append({"name": name, "status": "pass", "seconds": round(time.monotonic() - started, 2), **detail})
        except (ServiceError, ConfigurationError, ValueError) as exc:
            results.append({"name": name, "status": "fail", "seconds": round(time.monotonic() - started, 2),
                            "detail": explain(exc)})
    return results


def check(settings: Settings, *, scan: Path | None, receipt_dir: Path,
          http: httpx.Client | None = None) -> tuple[dict[str, Any], Path]:
    """Run the checks and save a receipt. The receipt never contains the API key."""
    if not settings.super_api_key:
        raise ConfigurationError("SUPER_API_KEY is empty. Put your Token Factory key in .env.")
    with ChatClient(settings.super_base_url, settings.super_api_key, settings.super_model, client=http) as client:
        results = run_checks(client, scan)
    now = datetime.now(timezone.utc)
    receipt = {
        "checked_at": now.isoformat(timespec="seconds"),
        "base_url": settings.super_base_url,
        "model": settings.super_model,
        "passed": not any(result["status"] == "fail" for result in results),
        "checks": results,
    }
    receipt_dir.mkdir(parents=True, exist_ok=True)
    path = receipt_dir / f"super-check-{now:%Y%m%dT%H%M%SZ}.json"
    path.write_text(json.dumps(receipt, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return receipt, path


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Check Super VL access on Token Factory with real requests.")
    parser.add_argument("--scan-dir", type=Path, default=Path("data/raw/britannica"))
    parser.add_argument("--receipt-dir", type=Path, default=Path("runs"))
    parser.add_argument("--skip-vision", action="store_true", help="skip the image check")
    args = parser.parse_args(argv)
    try:
        settings = Settings.from_env()
        scan = None if args.skip_vision else find_scan(args.scan_dir)
        receipt, path = check(settings, scan=scan, receipt_dir=args.receipt_dir)
    except ConfigurationError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1
    for result in receipt["checks"]:
        line = f"{result['status'].upper():7} {result['name']}"
        if result["status"] == "pass" and result.get("excerpt"):
            line += f"  -> {result['excerpt'][:80]!r}"
        elif result.get("detail"):
            line += f"  ({result['detail']})"
        print(line)
    passed = sum(result["status"] == "pass" for result in receipt["checks"])
    print(f"{passed}/{len(CHECKS)} checks passed. Receipt: {path}")
    return 0 if receipt["passed"] else 1
