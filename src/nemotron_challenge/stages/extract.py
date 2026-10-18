"""Extract stage: run Parse 3.5 on the manifest scans, then write pages, entries, crops and coverage.

Outputs under <work_dir>/extract/ (issue #2):
  raw/{row_index:04d}.json  raw Parse reply plus request record; reused when image_sha256 matches
  pages.jsonl               one PageRecord per processed scan
  entries.jsonl             EntryRecords in page and reading order
  crops/{entry_id}.png      union of the entry's block boxes, padded 8 px, grayscale
                            (the scans are grayscale paper; RGB PNGs were 2.7 times larger)
  coverage.json             counts, dropped blocks, failures, latency, CER, LaTeX results
  gold/{row_index:04d}.txt  hand transcriptions for CER (typed by a person; see gold/README.md)
  latex/{row_index:04d}.tex and .pdf   one document per ok scan

Blank pages: Parse returns a full-page Picture block for an empty sheet (rows 374, 1615, 2077),
so "no text blocks" alone would also catch uncaptioned engravings. A page is blank when no
block has text and every picture region is nearly flat (grayscale standard deviation below 15).
Measured: blank sheets 5.9 to 12.1; the faintest real plate (a map, row 1845) 16.9; engravings 29+.

Set EXTRACT_LIMIT=N to process only the first N manifest scans.
Set EXTRACT_SKIP_LATEX=1 to write the .tex files without compiling them.
"""
from __future__ import annotations

DONE = True

from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
import base64
import json
import os
from pathlib import Path
import time
from typing import Any

from PIL import Image, ImageStat

from ..clients import ParseClient, ProtocolError, ServiceError
from ..config import PARSE_MODEL, Settings
from ..contracts import EntryRecord, PageRecord
from ..data import file_sha256, load_manifest
from . import cer, latex
from .segment import segment

MAX_IN_FLIGHT = 4
RETRIES = 3
CROP_PADDING = 8
CROP_MAX_SIDE = 2048
CROP_MAX_BYTES = 8 * 1024 * 1024
BLANK_STDDEV = 15.0


def is_blank(entries: list[dict[str, Any]], scan: Path) -> bool:
    """No text anywhere, and every picture region is nearly flat paper."""
    if any(e["text"].strip() for e in entries) or any(b["text"].strip() for e in entries for b in e["blocks"]):
        return False
    with Image.open(scan) as image:
        gray = image.convert("L")
        for entry in entries:
            for block in entry["blocks"]:
                x0, y0, x1, y1 = block["bbox"]
                region = gray.crop((int(x0), int(y0), max(int(x1), int(x0) + 1), max(int(y1), int(y0) + 1)))
                if ImageStat.Stat(region).stddev[0] >= BLANK_STDDEV:
                    return False
    return True


def _retry_delay(exc: ServiceError, attempt: int) -> float:
    try:
        return float(exc.retry_after) if exc.retry_after else 2.0 * 2 ** attempt
    except ValueError:
        return 2.0 * 2 ** attempt


def _retryable(exc: ServiceError) -> bool:
    if isinstance(exc, ProtocolError):
        return False
    return exc.status_code is None or exc.status_code == 429 or exc.status_code >= 500


def parse_page(client: ParseClient, page: dict[str, Any], scan: Path, raw_dir: Path,
               sleep=time.sleep) -> dict[str, Any]:
    """Return the raw record for one scan: reuse a good saved reply, else call Parse with retries."""
    path = raw_dir / f"{page['row_index']:04d}.json"
    if path.is_file():
        saved = json.loads(path.read_text(encoding="utf-8"))
        if saved.get("image_sha256") == page["image_sha256"] and saved.get("error") is None:
            return saved
    record: dict[str, Any] = {
        "page_id": page["page_id"], "row_index": page["row_index"], "filename": page["filename"],
        "image_sha256": page["image_sha256"], "model": PARSE_MODEL, "latency_ms": 0, "attempts": 0,
        "finish_reason": None, "parsed_at": None, "error": None, "reply": None,
    }
    if not scan.is_file():
        record["error"] = f"scan file is missing: {scan}. Run `nemotron-challenge data fetch`."
    elif file_sha256(scan) != page["image_sha256"]:
        record["error"] = "scan checksum differs from the manifest"
    else:
        url = "data:image/jpeg;base64," + base64.b64encode(scan.read_bytes()).decode()
        for attempt in range(RETRIES + 1):
            record["attempts"] = attempt + 1
            started = time.monotonic()
            try:
                reply = client.parse(url)
            except ServiceError as exc:
                record["latency_ms"] = int((time.monotonic() - started) * 1000)
                if _retryable(exc) and attempt < RETRIES:
                    sleep(_retry_delay(exc, attempt))
                    continue
                record["error"] = f"{type(exc).__name__}: {exc}"
                break
            record.update(latency_ms=int((time.monotonic() - started) * 1000), reply=reply,
                          model=reply.get("model", PARSE_MODEL),
                          finish_reason=reply["choices"][0].get("finish_reason"),
                          parsed_at=datetime.now(timezone.utc).isoformat(timespec="seconds"))
            break
    raw_dir.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(record, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    return record


def link_continuations(pages: list[dict[str, Any]], entries_by_row: dict[int, list[dict[str, Any]]]) -> None:
    """Link a page's leading continuation to the last text entry of the previous scan in the same volume."""
    by_row = {page["row_index"]: page for page in pages}
    for page in pages:
        entries = entries_by_row.get(page["row_index"], [])
        if not entries or entries[0]["kind"] != "continuation":
            continue
        first = entries[0]
        previous = by_row.get(page["row_index"] - 1)
        candidates = [e for e in entries_by_row.get(page["row_index"] - 1, []) if e["kind"] != "plate"]
        if previous is not None and previous["volume_id"] == page["volume_id"] and candidates:
            first["continues_from"] = candidates[-1]["entry_id"]
            candidates[-1]["continues_to"] = first["entry_id"]
            first["quality"]["orphan_continuation"] = False
        else:
            first["quality"]["orphan_continuation"] = True


def save_crop(image: Image.Image, boxes: list[list[float]], path: Path) -> None:
    width, height = image.size
    x0 = max(min(b[0] for b in boxes) - CROP_PADDING, 0)
    y0 = max(min(b[1] for b in boxes) - CROP_PADDING, 0)
    x1 = min(max(b[2] for b in boxes) + CROP_PADDING, width)
    y1 = min(max(b[3] for b in boxes) + CROP_PADDING, height)
    crop = image.crop((int(x0), int(y0), max(int(x1), int(x0) + 1), max(int(y1), int(y0) + 1)))
    crop.thumbnail((CROP_MAX_SIDE, CROP_MAX_SIDE))
    path.parent.mkdir(parents=True, exist_ok=True)
    crop.save(path, format="PNG", optimize=True)
    if path.stat().st_size > CROP_MAX_BYTES:
        raise ValueError(f"crop exceeds 8 MiB: {path}")


def _percentile(values: list[int], share: float) -> int | None:
    if not values:
        return None
    ordered = sorted(values)
    return ordered[min(len(ordered) - 1, round(share * (len(ordered) - 1)))]


def extract(pages: list[dict[str, Any]], scan_dir: Path, work_dir: Path, client: ParseClient,
            compile_latex: bool = False) -> dict[str, Any]:
    out = work_dir / "extract"
    raw_dir = out / "raw"
    with ThreadPoolExecutor(max_workers=MAX_IN_FLIGHT) as pool:
        raws = list(pool.map(lambda page: parse_page(client, page, scan_dir / page["filename"], raw_dir), pages))

    page_rows: list[dict[str, Any]] = []
    entries_by_row: dict[int, list[dict[str, Any]]] = {}
    dropped: list[dict[str, Any]] = []
    unparsed: dict[str, int] = {}
    for page, raw in zip(pages, raws, strict=True):
        scan = scan_dir / page["filename"]
        width = height = 0
        if scan.is_file():
            try:
                with Image.open(scan) as image:
                    width, height = image.size
            except OSError:
                pass  # unreadable scan: the page is recorded as failed below
        parse_run = None
        if raw["reply"] is not None:
            parse_run = {"model": raw["model"], "latency_ms": raw["latency_ms"],
                         "finish_reason": raw["finish_reason"],
                         "raw_path": (raw_dir / f"{page['row_index']:04d}.json").as_posix()}
        row = {"page_id": page["page_id"], "row_index": page["row_index"], "volume_id": page["volume_id"],
               "filename": page["filename"], "image_sha256": page["image_sha256"], "width": width,
               "height": height, "status": "failed", "parse": parse_run, "error": raw["error"], "entry_ids": []}
        if raw["error"] is None:
            content = raw["reply"]["choices"][0]["message"]["content"]
            result = segment(content, page["row_index"], page["page_id"], width, height)
            entries = result["entries"]
            dropped.extend(result["dropped"])
            if result["unparsed_chars"]:
                unparsed[str(page["row_index"])] = result["unparsed_chars"]
            if result["kept_blocks"] == 0 or not entries or is_blank(entries, scan):
                row["status"] = "blank"
                entries = []
            elif all(e["quality"]["low_quality"] for e in entries):
                row["status"] = "illegible"
            else:
                row["status"] = "ok"
            for entry in entries:
                entry.update(crop_path=(out / "crops" / f"{entry['entry_id']}.png").as_posix(),
                             continues_from=None, continues_to=None)
            entries_by_row[page["row_index"]] = entries
            row["entry_ids"] = [e["entry_id"] for e in entries]
        page_rows.append(row)

    link_continuations(pages, entries_by_row)
    all_entries = [e for page in pages for e in entries_by_row.get(page["row_index"], [])]
    for page in pages:
        for stale in (out / "crops").glob(f"e{page['row_index']:04d}-*.png"):
            stale.unlink()  # entry numbering can change between runs
        entries = entries_by_row.get(page["row_index"], [])
        if not entries:
            continue
        with Image.open(scan_dir / page["filename"]) as image:
            image = image.convert("L")
            for entry in entries:
                save_crop(image, [b["bbox"] for b in entry["blocks"]], Path(entry["crop_path"]))

    # Validate the way readers load these files (JSON lines), so every written row loads downstream.
    page_records = [PageRecord.model_validate_json(json.dumps(row, ensure_ascii=False)) for row in page_rows]
    entry_records = [EntryRecord.model_validate_json(json.dumps(entry, ensure_ascii=False)) for entry in all_entries]
    out.mkdir(parents=True, exist_ok=True)
    (out / "pages.jsonl").write_text("".join(r.model_dump_json() + "\n" for r in page_records), encoding="utf-8")
    (out / "entries.jsonl").write_text("".join(r.model_dump_json() + "\n" for r in entry_records), encoding="utf-8")

    entries_by_id = {entry["entry_id"]: entry for entry in all_entries}
    cer_report = cer.report(page_rows, entries_by_id, out / "gold")
    latex_report = latex.build(page_rows, entries_by_id, out, compile_pdf=compile_latex)

    def count(values: list[str]) -> dict[str, int]:
        return {value: values.count(value) for value in sorted(set(values))}

    latencies = [r["latency_ms"] for r in raws if r["error"] is None]
    coverage = {
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "pages_total": len(page_rows),
        "pages_by_status": count([r["status"] for r in page_rows]),
        "entries_total": len(all_entries),
        "entries_by_kind": count([e["kind"] for e in all_entries]),
        "orphan_continuations": [e["entry_id"] for e in all_entries if e["quality"].get("orphan_continuation")],
        "linked_continuations": [e["entry_id"] for e in all_entries if e["continues_from"]],
        "low_quality_entries": [e["entry_id"] for e in all_entries if e["quality"]["low_quality"]],
        "dropped_blocks": dropped,
        "unparsed_chars_by_row": unparsed,
        "parse_latency_ms": {"p50": _percentile(latencies, 0.5), "p95": _percentile(latencies, 0.95)},
        "failed_pages": [{"row_index": r["row_index"], "page_id": r["page_id"], "error": r["error"]}
                         for r in page_rows if r["status"] == "failed"],
        "cer": cer_report,
        "latex": latex_report,
    }
    (out / "coverage.json").write_text(json.dumps(coverage, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return {"pages": len(page_rows), "pages_by_status": coverage["pages_by_status"],
            "entries": len(all_entries), "entries_by_kind": coverage["entries_by_kind"],
            "cer": {"status": cer_report["status"], "mean_cer": cer_report["mean_cer"],
                    "missing_gold_rows": cer_report["missing_gold_rows"]},
            "latex": {key: latex_report[key] for key in ("status", "tex_files", "compiled")} | {
                "failed": len(latex_report["failed"])},
            "output_dir": out.as_posix()}


def run(settings: Settings, work_dir: Path) -> dict[str, Any]:
    pages = load_manifest()["pages"]
    limit = os.environ.get("EXTRACT_LIMIT", "").strip()
    if limit:
        pages = pages[: int(limit)]
    scan_dir = Path("data/raw/britannica")
    if not any(scan_dir.glob("*.jpg")):
        raise FileNotFoundError("no scans found in data/raw/britannica. Run `nemotron-challenge data fetch` first.")
    with ParseClient(settings.parse_base_url, settings.parse_api_key, timeout=300) as client:
        return extract(pages, scan_dir, Path(work_dir), client,
                       compile_latex=os.environ.get("EXTRACT_SKIP_LATEX", "").strip() != "1")
