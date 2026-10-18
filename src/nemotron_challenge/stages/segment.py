"""Turn Nemotron Parse 3.5 replies into blocks and Britannica entries. No network calls.

Parse reply format, checked on rows 13, 104 and 115 of the event sample:
the message content is a list of blocks separated by blank lines. Each block is

    <x_X0><y_Y0>TEXT<x_X1><y_Y1><class_CLS>

X and Y are fractions (0 to 1) of the source image width and height, origin top left.
Pixel box = (x0 * width, y0 * height, x1 * width, y1 * height). An overlay of row 13
confirmed this: the boxes align with the text and have no padding offset, but a box can
clip its last text line by a few pixels (crops add padding for this).
Classes seen so far: Page-header, Section-header, Text, List-item.

Rules (issue #2, step 3), with these team decisions:
- Headers: drop Page-header and Page-footer blocks, and blocks wholly inside the top or
  bottom 6% of the page with 4 or fewer tokens or numeric text. Page headers are not always
  inside the top 6% (row 115 starts at 6.5%), so the class check is needed too.
- Margin notes (narrow blocks at the page edge, such as "Practical Building") stay in the
  entry blocks and text_raw, but never start an entry and stay out of the normalized text.
- Cross references: only short entries (300 characters or fewer) that match "See WORD".
- OCR suspect ratio: pure numbers such as 1733 or 27/430 do not count as suspect.
- Headwords: spaced titles such as "C H E M I S T R Y" collapse to one word; chapter and
  section words (CHAP, SECT, PART, ...) and Roman numerals are not headwords. An all-caps
  Title block also starts an entry, because treatise titles often have no trailing comma.
- Continuations keep a cleaned running header ("292 SHIP-BUILDING." -> "SHIP-BUILDING") in
  quality.running_header, so a continuation page can still be matched by its article title.
"""
from __future__ import annotations

from dataclasses import dataclass
import re
import string
from typing import Any

BLOCK_RE = re.compile(r"<x_([0-9.]+)><y_([0-9.]+)>(.*?)<x_([0-9.]+)><y_([0-9.]+)><class_([^>]+)>", re.S)
HEADWORD_RE = re.compile(r"^([A-ZÆŒ][A-ZÆŒ\-' ]{1,40})[,.]")
SEE_RE = re.compile(r"\b[Ss]ee [A-Z]{2,}")
NUMBER_RE = re.compile(r"\d+(?:[.,/]\d+)*")
WORD_RE = re.compile(r"[^\W\d_]+(?:[-'’][^\W\d_]+)*")
PUNCTUATION = string.punctuation + "“”‘’—–«»•¬§¶†‡"

CAPS_RUN_RE = re.compile(r"[A-ZÆŒ][A-ZÆŒ\-' ]{2,}")
ROMAN_RE = re.compile(r"M{0,4}(CM|CD|D?C{0,3})(XC|XL|L?X{0,3})(IX|IV|V?I{0,3})")  # valid numerals only
NOT_HEADWORDS = {"CHAP", "CHAPTER", "SECT", "SECTION", "PART", "BOOK", "ART", "FIG", "PLATE", "VOL", "NO"}

HEADER_CLASSES = {"Page-header", "Page-footer"}
TITLE_CLASSES = {"Title"}
PICTURE_CLASSES = {"Picture", "Figure", "Image"}
CAPTION_CLASSES = {"Caption"}
EDGE = 0.06
CROSS_REFERENCE_MAX_CHARS = 300
LOW_QUALITY_RATIO = 0.25


@dataclass(frozen=True)
class RawBlock:
    x0: float
    y0: float
    x1: float
    y1: float
    text: str
    cls: str

    @property
    def width(self) -> float:
        return self.x1 - self.x0

    @property
    def center_x(self) -> float:
        return (self.x0 + self.x1) / 2


def parse_blocks(content: str) -> tuple[list[RawBlock], int]:
    """Read Parse content into blocks. Also return the count of characters outside any block."""
    blocks = [RawBlock(float(x0), float(y0), float(x1), float(y1), text.strip(), cls.strip())
              for x0, y0, text, x1, y1, cls in BLOCK_RE.findall(content)]
    leftover = len(BLOCK_RE.sub("", content).strip())
    return blocks, leftover


def to_pixels(block: RawBlock, width: int, height: int) -> list[float]:
    """Convert a fractional box to x0, y0, x1, y1 in source-image pixels, clipped to the image."""
    def clip(value: float, limit: int) -> float:
        return round(min(max(value, 0.0), 1.0) * limit, 1)
    return [clip(block.x0, width), clip(block.y0, height), clip(block.x1, width), clip(block.y1, height)]


def drop_reason(block: RawBlock) -> str | None:
    """Return why a block is a page header or footer, or None to keep it."""
    if block.cls in HEADER_CLASSES:
        return f"class {block.cls}"
    in_edge = block.y1 <= EDGE or block.y0 >= 1 - EDGE
    text = block.text.strip()
    if in_edge and (len(text.split()) <= 4 or NUMBER_RE.fullmatch(text)):
        return "inside top or bottom 6% with 4 or fewer tokens or numeric text"
    return None


def is_margin_note(block: RawBlock) -> bool:
    return block.width < 0.15 and (block.x1 <= 0.16 or block.x0 >= 0.84)


def reading_order(blocks: list[RawBlock]) -> list[RawBlock]:
    """Keep Parse order on one-column pages. On two-column pages read left then right, band by band.

    A full-width block (spanning the page middle) closes a band, so a title between two
    column runs stays in place.
    """
    columns = [b for b in blocks if b.width < 0.6]
    left = [b for b in columns if b.center_x < 0.5]
    right = [b for b in columns if b.center_x >= 0.5]
    if len(left) < 2 or len(right) < 2:
        return list(blocks)
    ordered: list[RawBlock] = []
    band: list[RawBlock] = []

    def flush() -> None:
        ordered.extend(sorted((b for b in band if b.center_x < 0.5), key=lambda b: b.y0))
        ordered.extend(sorted((b for b in band if b.center_x >= 0.5), key=lambda b: b.y0))
        band.clear()

    for block in sorted(blocks, key=lambda b: b.y0):
        if block.width >= 0.6:
            flush()
            ordered.append(block)
        else:
            band.append(block)
    flush()
    return ordered


def collapse_spaced(word: str) -> str:
    """Join letter-spaced titles: 'C H E M I S T R Y' and 'CH E M I S T R Y' become 'CHEMISTRY'."""
    tokens = word.split()
    if len(tokens) >= 3 and sum(len(token) == 1 for token in tokens) >= 0.75 * len(tokens):
        return "".join(tokens)
    return " ".join(tokens)


def clean_headword(word: str) -> str | None:
    word = collapse_spaced(word).strip(" '-")
    if len(word) < 2 or ROMAN_RE.fullmatch(word) or word.split()[0] in NOT_HEADWORDS:
        return None
    return word


def headword(text: str) -> str | None:
    """Return the entry headword if the text starts a new entry, such as 'ABACUS, among ...'."""
    cleaned = re.sub(r"^[#\s]+", "", text).replace("**", "").replace("__", "")
    match = HEADWORD_RE.match(cleaned)
    return clean_headword(match.group(1)) if match else None


def title_headword(text: str) -> str | None:
    """Return the headword of an all-caps Title block, such as 'C H E M I S T R Y.'."""
    letters = [char for char in text if char.isalpha()]
    if not letters or sum(char.isupper() for char in letters) < 0.8 * len(letters):
        return None
    word = re.sub(r"[^A-ZÆŒ\-' ]", " ", normalize(text)).strip()
    return clean_headword(word) if 2 <= len(word) <= 40 else None


def clean_running_header(text: str) -> str:
    """Keep the article title from a page header: '292 SHIP-BUILDING.' -> 'SHIP-BUILDING'.

    OCR splits header letters ('C ARPENTRY', 'ABY S SINIA'), so a run with a one-letter
    fragment is joined. Three-letter catchwords ('COM [ 345 ] COM') name no article and are dropped.
    """
    titles = []
    for run in CAPS_RUN_RE.findall(normalize(text)):
        tokens = run.split()
        if any(len(token) == 1 for token in tokens):
            tokens = ["".join(tokens)]
        if len(set(tokens)) == 1:
            tokens = tokens[:1]
        title = clean_headword(" ".join(tokens))
        if title and len(title) >= 4:
            titles.append(title)
    return max(titles, key=len) if titles else ""


def normalize(text: str) -> str:
    """Long s to s, join line-end hyphens, drop markdown emphasis, collapse whitespace."""
    text = text.replace("ſ", "s").replace("**", "").replace("__", "")
    text = re.sub(r"(\w)[-¬]\s*\n\s*(\w)", r"\1\2", text)
    return re.sub(r"\s+", " ", text).strip()


def ocr_suspect_ratio(text: str) -> float:
    """Share of tokens that are neither words, punctuation, nor plain numbers."""
    tokens = text.split()
    if not tokens:
        return 0.0
    suspect = 0
    for token in tokens:
        core = token.strip(PUNCTUATION)
        if core and not WORD_RE.fullmatch(core) and not NUMBER_RE.fullmatch(core):
            suspect += 1
    return round(suspect / len(tokens), 3)


def segment(content: str, row_index: int, page_id: str, width: int, height: int) -> dict[str, Any]:
    """Split one Parse reply into entry dicts (EntryRecord fields except crop and continuation links)."""
    raw_blocks, leftover = parse_blocks(content)
    kept: list[RawBlock] = []
    dropped: list[dict[str, Any]] = []
    running_header = ""
    for block in raw_blocks:
        reason = drop_reason(block)
        if reason is None:
            kept.append(block)
            continue
        dropped.append({"page_id": page_id, "row_index": row_index, "cls": block.cls,
                        "text": block.text, "reason": reason})
        if block.cls == "Page-header" and not running_header:
            running_header = block.text

    groups: list[dict[str, Any]] = []
    text_group: dict[str, Any] | None = None
    plate_group: dict[str, Any] | None = None
    for block in reading_order(kept):
        margin = is_margin_note(block)
        if block.cls in PICTURE_CLASSES:
            plate_group = {"kind": "plate", "headword": None, "blocks": [block], "margin": []}
            groups.append(plate_group)
            continue
        if block.cls in CAPTION_CLASSES and plate_group is not None:
            plate_group["blocks"].append(block)
            continue
        plate_group = None
        word = None
        if not margin:
            word = title_headword(block.text) if block.cls in TITLE_CLASSES else headword(block.text)
        if word is not None:
            text_group = {"kind": "entry", "headword": word, "blocks": [block], "margin": []}
            groups.append(text_group)
        elif text_group is None:
            text_group = {"kind": "continuation", "headword": None, "blocks": [block], "margin": []}
            groups.append(text_group)
        else:
            text_group["blocks"].append(block)
        if margin:
            text_group["margin"].append(block)

    entries = []
    for n, group in enumerate(groups, start=1):
        body = [b for b in group["blocks"] if b not in group["margin"]] or group["blocks"]
        text = normalize("\n".join(b.text for b in body))
        kind = group["kind"]
        if kind == "entry" and len(text) <= CROSS_REFERENCE_MAX_CHARS and SEE_RE.search(text):
            kind = "cross_reference"
        ratio = ocr_suspect_ratio(text)
        quality: dict[str, float | bool | str] = {"ocr_suspect_ratio": ratio, "low_quality": ratio > LOW_QUALITY_RATIO}
        if group["margin"]:
            quality["margin_notes"] = " | ".join(normalize(b.text) for b in group["margin"])
        if kind == "continuation" and clean_running_header(running_header):
            quality["running_header"] = clean_running_header(running_header)
        entries.append({
            "entry_id": f"e{row_index:04d}-{n:02d}",
            "kind": kind,
            "headword": group["headword"],
            "text": text,
            "text_raw": "\n\n".join(b.text for b in group["blocks"]),
            "blocks": [{"page_id": page_id, "bbox": to_pixels(b, width, height), "cls": b.cls, "text": b.text}
                       for b in group["blocks"]],
            "quality": quality,
        })
    return {"entries": entries, "dropped": dropped, "kept_blocks": len(kept),
            "unparsed_chars": leftover, "running_header": running_header}
