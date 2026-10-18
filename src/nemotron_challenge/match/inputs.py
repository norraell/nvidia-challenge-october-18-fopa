"""Load EntryRecord rows, or build development entries from raw Parse output."""
from __future__ import annotations

import json
from pathlib import Path
import re

from ..contracts import Block, EntryRecord
from .queries import clean_text, normalize_header

ELEMENT_RE = re.compile(r"<x_([0-9.]+)><y_([0-9.]+)>(.*?)<x_([0-9.]+)><y_([0-9.]+)><class_([A-Za-z-]+)>", re.DOTALL)
SKIP_CLASSES = frozenset({"Page-header", "Page-footer"})
SCAN_DIR = Path("data/raw/britannica")


def load_entries(path: Path) -> list[EntryRecord]:
    if not path.exists():
        raise FileNotFoundError(f"entries file is missing: {path}")
    rows: list[EntryRecord] = []
    for number, line in enumerate(path.read_text().splitlines(), start=1):
        if line.strip():
            try:
                rows.append(EntryRecord.model_validate_json(line))
            except ValueError as exc:
                raise ValueError(f"{path}:{number} is not a valid EntryRecord: {exc}") from None
    if not rows:
        raise ValueError(f"entries file has no rows: {path}")
    ids = [r.entry_id for r in rows]
    if len(set(ids)) != len(ids):
        raise ValueError("entries file repeats an entry_id")
    return rows


def parse_elements(markdown: str) -> list[dict[str, object]]:
    """One record per Parse element: class, fractional bbox, raw text."""
    elements = []
    for m in ELEMENT_RE.finditer(markdown):
        x0, y0, text, x1, y1, cls = m.groups()
        elements.append({"cls": cls, "bbox": [float(x0), float(y0), float(x1), float(y1)], "text": text.strip()})
    return elements


def join_hyphenation(text: str) -> str:
    return re.sub(r"(\w)- (\w)", r"\1\2", text)


def _header_text(metric: dict) -> str:
    return " ".join(h for h in metric.get("headers", []) if isinstance(h, str))


def bootstrap_entries_from_raw(raw_dir: Path, metrics_path: Path, scan_dir: Path = SCAN_DIR) -> list[EntryRecord]:
    """Build one pseudo EntryRecord per parsed page. Development only, never written to artifacts/extract."""
    metrics = {row["row_index"]: row for row in (json.loads(l) for l in metrics_path.read_text().splitlines() if l.strip())}
    entries: list[EntryRecord] = []
    for raw_path in sorted(raw_dir.glob("page-*.json")):
        raw = json.loads(raw_path.read_text())
        page, metric = raw["page"], metrics.get(raw["page"]["row_index"], {})
        if metric.get("status") not in (None, "ok"):
            continue
        content = raw["response"]["choices"][0]["message"]["content"]
        elements = parse_elements(content)
        if not elements:
            continue
        body = [e for e in elements if e["cls"] not in SKIP_CLASSES] or elements
        text_raw = "\n".join(str(e["text"]) for e in body)
        text = join_hyphenation(clean_text(text_raw))
        is_plate = bool(metric.get("is_plate_only")) or all(e["cls"] == "Picture" for e in body)
        if not text and not is_plate:
            continue
        header = _header_text(metric)
        headword = normalize_header(header) if header else None
        if is_plate:
            headword = normalize_header(clean_text(text).split(".")[0]) or headword
        blocks = [Block(page_id=page["page_id"], bbox=list(e["bbox"]), cls=str(e["cls"]), text=str(e["text"])) for e in elements]
        quality: dict[str, float | bool | str] = {"dev_bootstrap": True, "bbox_units": "fraction", "page_header": header}
        if isinstance(metric.get("dict_rate"), (int, float)):
            quality["dict_rate"] = float(metric["dict_rate"])
        entries.append(EntryRecord(
            entry_id=f"e{page['row_index']:04d}-01", kind="plate" if is_plate else "entry", headword=headword,
            text=text, text_raw=text_raw, blocks=blocks, crop_path=str(scan_dir / page["filename"]), quality=quality,
        ))
    return entries


def write_entries(path: Path, entries: list[EntryRecord]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("".join(e.model_dump_json() + "\n" for e in entries))
