"""Read, correct, modernize: Super VL checks Parse's text against the scan (opt-in step of extract).

Parse sometimes replaces old words with plausible modern ones ("Popery" -> "Sprayer",
"Baden" -> "Canada"). This step sends each text block's scan region (enlarged 2.5 times)
with Parse's text to Super VL, reasoning off, and asks for two versions:

  faithful  the text as printed, misread words fixed, old spelling kept (long s as "f")
  modern    the same text in modern spelling, for search, comparison and the agent

Parse's text is never overwritten. Guardrails keep Parse's text (or the faithful text)
when a version changes the word count by more than 15% (at least 3 words), or when the
reply is not valid JSON. Embed VL checks that the modern version keeps the meaning: a
block whose faithful/modern cosine is below MEANING_MIN keeps the faithful text.

Outputs under <work_dir>/extract/:
  correct/raw/{key}.json   Super VL replies, reused on rerun (the key hashes model, prompt, text, image)
  corrected.jsonl          per entry: parse, faithful and modern text, word changes, fallbacks
  entries.modern.jsonl     EntryRecords whose text is the modern reading (text_raw unchanged)

Measured on row 251 before this module: Parse CER 13.8%, Super VL (reasoning off) 7.1%.
"""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
import base64
import difflib
import hashlib
import io
import json
from pathlib import Path
import statistics
from typing import Any

from PIL import Image

from ..clients import ChatClient, RetrievalClient, ServiceError
from ..contracts import EntryRecord
from .cer import cer, page_text
from .segment import RawBlock, is_margin_note, normalize

PROMPT_VERSION = "c2"
SCALE = 2.5
PADDING = 6
MAX_SIDE = 2048
MIN_WORDS = 3
WORD_DRIFT = 0.15
MEANING_MIN = 0.90
MAX_IN_FLIGHT = 4
SKIP_CLASSES = {"Picture", "Figure", "Image", "Formula", "Table"}

PROMPT = """You are checking OCR output of a scanned block from an early 1800s Encyclopaedia Britannica.
The image is the scanned block. TEXT is what an OCR model read from it. The OCR model often replaces old words
with wrong but plausible modern words, and misreads names.

The image may also show parts of neighbouring lines or paragraphs. Ignore any text that is not part of TEXT:
correct only the words of TEXT, from its first word to its last word, and write one paragraph without line breaks.

Return JSON with two fields:
"faithful": TEXT with misread words fixed so it matches the image. Fix only words where the image clearly shows
something different; if a word is unreadable, keep the OCR word. Keep the old spelling exactly as printed. The printed
long s looks like "f": write it as "f" (for example "Bafel", "Calvinifm"). Do not add or remove sentences.
The result must have about the same number of words as TEXT.
"modern": the faithful text in modern English spelling (long s as s, "Bafel" -> "Basel", "fome" -> "some").
Change spelling only. Keep every word's meaning, the order, and the sentences. Do not add explanations.

Reply with the JSON object only.

TEXT:
"""


def block_key(model: str, text: str, image_bytes: bytes) -> str:
    digest = hashlib.sha256()
    for part in (model, PROMPT_VERSION, text):
        digest.update(part.encode("utf-8") + b"\0")
    digest.update(image_bytes)
    return digest.hexdigest()[:32]


def block_image(gray: Image.Image, bbox: list[float]) -> bytes:
    x0, y0, x1, y1 = bbox
    width, height = gray.size
    box = (max(int(x0) - PADDING, 0), max(int(y0) - PADDING, 0),
           min(int(x1) + PADDING, width), min(int(y1) + PADDING, height))
    region = gray.crop((box[0], box[1], max(box[2], box[0] + 1), max(box[3], box[1] + 1)))
    region = region.resize((max(1, int(region.width * SCALE)), max(1, int(region.height * SCALE))), Image.LANCZOS)
    region.thumbnail((MAX_SIDE, MAX_SIDE))
    buffer = io.BytesIO()
    region.save(buffer, format="PNG")
    return buffer.getvalue()


def parse_reply(content: str) -> dict[str, str] | None:
    """Read {"faithful": ..., "modern": ...} from a reply, also inside a ```json fence."""
    start, end = content.find("{"), content.rfind("}")
    if start < 0 or end <= start:
        return None
    try:
        data = json.loads(content[start:end + 1])
    except ValueError:
        return None
    if not isinstance(data, dict) or not all(isinstance(data.get(key), str) for key in ("faithful", "modern")):
        return None
    return {"faithful": data["faithful"].strip(), "modern": data["modern"].strip()}


def word_drift_ok(before: str, after: str) -> bool:
    a, b = len(before.split()), len(after.split())
    return abs(a - b) <= max(MIN_WORDS, WORD_DRIFT * a)


def trim_to_span(reference: str, version: str) -> str:
    """Cut words that Super VL read from neighbouring lines: keep the span of `version` aligned with `reference`.

    The span runs from the first matching word to the last, widened by as many words as the
    reference has before its first match and after its last match.
    """
    a, b = reference.split(), version.split()
    matches = [m for m in difflib.SequenceMatcher(None, [w.lower() for w in a], [w.lower() for w in b],
                                                  autojunk=False).get_matching_blocks() if m.size]
    if not matches:
        return version
    first, last = matches[0], matches[-1]
    start = max(0, first.b - first.a)
    end = min(len(b), last.b + last.size + (len(a) - last.a - last.size))
    return " ".join(b[start:end])


def word_changes(before: str, after: str) -> list[list[str]]:
    a, b = before.split(), after.split()
    return [[" ".join(a[i1:i2]), " ".join(b[j1:j2])]
            for tag, i1, i2, j1, j2 in difflib.SequenceMatcher(None, a, b, autojunk=False).get_opcodes() if tag != "equal"]


def correct_block(client: ChatClient, text: str, image_bytes: bytes, raw_dir: Path) -> dict[str, Any]:
    """One Super VL call (cached). Returns the reply fields plus a status."""
    key = block_key(client.model, text, image_bytes)
    path = raw_dir / f"{key}.json"
    if path.is_file():
        return json.loads(path.read_text(encoding="utf-8"))
    url = "data:image/png;base64," + base64.b64encode(image_bytes).decode()
    record: dict[str, Any] = {"key": key, "model": client.model, "prompt_version": PROMPT_VERSION, "text": text}
    try:
        reply = client.complete([{"role": "user", "content": [
            {"type": "text", "text": PROMPT + text},
            {"type": "image_url", "image_url": {"url": url}},
        ]}], max_tokens=min(8192, int(len(text) * 1.6) + 600),
            extra_body={"temperature": 0, "chat_template_kwargs": {"enable_thinking": False}})
        content = reply["choices"][0]["message"]["content"]
        record.update(model=reply.get("model", client.model), content=content, usage=reply.get("usage"),
                      parsed=parse_reply(content), error=None)
    except ServiceError as exc:
        record.update(content=None, parsed=None, error=f"{type(exc).__name__}: {exc}")
        return record  # not cached: a later run retries it
    raw_dir.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(record, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    return record


def decide(text: str, record: dict[str, Any]) -> dict[str, Any]:
    """Apply the guardrails to one block. Returns faithful and modern text with fallback reasons."""
    parsed = record.get("parsed")
    if record.get("error"):
        return {"faithful": text, "modern": text, "fallback": f"call failed: {record['error'][:120]}"}
    if parsed is None:
        return {"faithful": text, "modern": text, "fallback": "reply was not the expected JSON"}
    faithful = trim_to_span(text, " ".join(parsed["faithful"].split()))
    modern = trim_to_span(faithful, " ".join(parsed["modern"].split()))
    fallback = None
    if not faithful or not word_drift_ok(text, faithful):
        faithful, fallback = text, "faithful version changed the word count too much"
    if not modern or not word_drift_ok(faithful, modern):
        modern, fallback = faithful, fallback or "modern version changed the word count too much"
    return {"faithful": faithful, "modern": modern, "fallback": fallback}


def overcorrections(parse: str, corrected: str, gold: str) -> int:
    """Words Parse got right (equal to gold) that the correction changed: the hallucination check."""
    p, c, g = parse.lower().split(), corrected.lower().split(), gold.lower().split()
    right = set()
    for tag, i1, i2, _, _ in difflib.SequenceMatcher(None, p, g, autojunk=False).get_opcodes():
        if tag == "equal":
            right.update(range(i1, i2))
    changed = set()
    for tag, i1, i2, _, _ in difflib.SequenceMatcher(None, p, c, autojunk=False).get_opcodes():
        if tag in ("replace", "delete"):
            changed.update(range(i1, i2))
    return len(right & changed)


def meaning_scores(retrieval: RetrievalClient | None, pairs: list[tuple[str, str]]) -> list[float | None]:
    """Embed VL cosine between faithful and modern text for each pair (None when no check ran)."""
    if retrieval is None:
        return [None] * len(pairs)
    scores: list[float | None] = []
    for start in range(0, len(pairs), 8):
        batch = pairs[start:start + 8]
        vectors = retrieval.embed([t for pair in batch for t in pair], "document")
        for index in range(len(batch)):
            a, b = vectors[2 * index], vectors[2 * index + 1]
            scores.append(round(sum(x * y for x, y in zip(a, b)), 4))
    return scores


def run_corrections(pages: list[dict[str, Any]], entries: list[dict[str, Any]], scan_dir: Path, out: Path,
                    chat: ChatClient, retrieval: RetrievalClient | None) -> dict[str, Any]:
    """Correct every text block, write corrected.jsonl and entries.modern.jsonl, return the coverage section."""
    by_row = {page["page_id"]: page for page in pages}
    jobs = []  # (entry index, block index, text, image bytes, margin)
    for e_index, entry in enumerate(entries):
        for b_index, block in enumerate(entry["blocks"]):
            page = by_row[block["page_id"]]
            width, height = page["width"], page["height"]
            x0, y0, x1, y1 = block["bbox"]
            margin = bool(width and is_margin_note(RawBlock(x0 / width, y0 / height, x1 / width, y1 / height,
                                                            block["text"], block["cls"])))
            jobs.append((e_index, b_index, block["text"], margin, page["filename"], block["bbox"], block["cls"]))
    images: dict[str, Image.Image] = {}

    def image_for(filename: str) -> Image.Image:
        if filename not in images:
            with Image.open(scan_dir / filename) as image:
                images[filename] = image.convert("L")
        return images[filename]

    todo = [job for job in jobs if job[6] not in SKIP_CLASSES and len(job[2].split()) >= MIN_WORDS]
    payloads = [(job, block_image(image_for(job[4]), job[5])) for job in todo]
    with ThreadPoolExecutor(max_workers=MAX_IN_FLIGHT) as pool:
        records = list(pool.map(lambda item: correct_block(chat, item[0][2], item[1], out / "correct" / "raw"), payloads))

    decisions: dict[tuple[int, int], dict[str, Any]] = {}
    for (job, _), record in zip(payloads, records, strict=True):
        decisions[(job[0], job[1])] = decide(job[2], record)
    keys = [key for key, d in decisions.items() if d["modern"] != d["faithful"]]
    scores = meaning_scores(retrieval, [(decisions[k]["faithful"], decisions[k]["modern"]) for k in keys])
    for key, score in zip(keys, scores, strict=True):
        decisions[key]["meaning_cosine"] = score
        if score is None:
            decisions[key].update(modern=decisions[key]["faithful"],
                                  fallback=decisions[key]["fallback"] or "no meaning check (Embed VL not configured)")
        elif score < MEANING_MIN:
            decisions[key].update(modern=decisions[key]["faithful"],
                                  fallback=decisions[key]["fallback"] or f"meaning check failed (cosine {score})")

    corrected_rows, modern_entries = [], []
    for e_index, entry in enumerate(entries):
        body_parse, body_faithful, body_modern, fallbacks = [], [], [], []
        for job in (j for j in jobs if j[0] == e_index):
            decision = decisions.get((job[0], job[1]), {"faithful": job[2], "modern": job[2], "fallback": None})
            if decision.get("fallback"):
                fallbacks.append({"block": job[1], "reason": decision["fallback"]})
            if job[3]:  # margin notes stay out of the entry text, as in segment.py
                continue
            body_parse.append(job[2])
            body_faithful.append(decision["faithful"])
            body_modern.append(decision["modern"])
        parse_text = entry["text"]
        faithful = normalize("\n".join(body_faithful)) if body_faithful else parse_text
        modern = normalize("\n".join(body_modern)) if body_modern else parse_text
        corrected_rows.append({"entry_id": entry["entry_id"], "kind": entry["kind"], "parse": parse_text,
                               "faithful": faithful, "modern": modern,
                               "faithful_changes": word_changes(parse_text, faithful),
                               "modern_changes": word_changes(faithful, modern), "fallbacks": fallbacks,
                               "model": chat.model, "prompt_version": PROMPT_VERSION})
        modern_entry = dict(entry, text=modern, quality=dict(entry["quality"], text_layer="modern (Super VL, meaning-checked)"))
        modern_entries.append(EntryRecord.model_validate_json(json.dumps(modern_entry, ensure_ascii=False)))

    (out / "corrected.jsonl").write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in corrected_rows),
                                         encoding="utf-8")
    (out / "entries.modern.jsonl").write_text("".join(r.model_dump_json() + "\n" for r in modern_entries), encoding="utf-8")
    return summarize(pages, entries, corrected_rows, decisions, out / "gold")


def summarize(pages: list[dict[str, Any]], entries: list[dict[str, Any]], rows: list[dict[str, Any]],
              decisions: dict[tuple[int, int], dict[str, Any]], gold_dir: Path) -> dict[str, Any]:
    by_id = {e["entry_id"]: e for e in entries}
    faithful_by_id = {r["entry_id"]: dict(by_id[r["entry_id"]], text=r["faithful"]) for r in rows}
    fallback_reasons: dict[str, int] = {}
    for decision in decisions.values():
        if decision.get("fallback"):
            reason = decision["fallback"].split(":")[0].split(" (")[0]
            fallback_reasons[reason] = fallback_reasons.get(reason, 0) + 1
    gold_rows = []
    for page in pages:
        path = gold_dir / f"{page['row_index']:04d}.txt"
        if page["status"] != "ok" or not path.is_file():
            continue
        gold = path.read_text(encoding="utf-8")
        before_text, after_text = page_text(page, by_id), page_text(page, faithful_by_id)
        before, after = cer(gold, before_text), cer(gold, after_text)
        window = len(gold.split()) + 20
        gold_rows.append({"row_index": page["row_index"], "cer_parse": before["cer"], "cer_faithful": after["cer"],
                          "errors_parse": before["distance"], "errors_faithful": after["distance"],
                          "gold_chars": before["gold_chars"],
                          "overcorrected_words": overcorrections(" ".join(before_text.split()[:window]),
                                                                 " ".join(after_text.split()[:window]), gold)})
    cosines = [d["meaning_cosine"] for d in decisions.values() if d.get("meaning_cosine") is not None]
    return {
        "status": "done",
        "model": rows[0]["model"] if rows else None,
        "prompt_version": PROMPT_VERSION,
        "blocks_sent": len(decisions),
        "blocks_with_fallback": sum(1 for d in decisions.values() if d.get("fallback")),
        "fallback_reasons": fallback_reasons,
        "entries_with_faithful_changes": sum(1 for r in rows if r["faithful_changes"]),
        "faithful_word_changes": sum(len(r["faithful_changes"]) for r in rows),
        "modern_word_changes": sum(len(r["modern_changes"]) for r in rows),
        "meaning_check": {"pairs": len(cosines), "min": min(cosines) if cosines else None,
                          "median": round(statistics.median(cosines), 4) if cosines else None,
                          "below_threshold": sum(1 for c in cosines if c < MEANING_MIN), "threshold": MEANING_MIN},
        "gold": gold_rows,
    }


def load_existing(out: Path) -> dict[str, dict[str, Any]]:
    """Corrections from an earlier run, by entry_id, so a normal extract rerun keeps them in the LaTeX."""
    path = out / "corrected.jsonl"
    if not path.is_file():
        return {}
    return {row["entry_id"]: row for row in map(json.loads, path.read_text(encoding="utf-8").splitlines())}
