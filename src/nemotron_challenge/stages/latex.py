"""LaTeX documents for the extracted Britannica pages (issue #2, step 8).

One .tex file per ok scan, filled from templates/page.tex, written to <work_dir>/extract/latex/
and compiled to PDF with tectonic (XeTeX, so Unicode such as æ and — works).

Structure kept from Parse: reading order (entries in page order), headings (one bold
subsection per entry headword), two columns (multicols when the page's blocks form two
columns), plates (the entry crop with its caption), and margin notes (a small aside).
Plates are not floats, because floats are not allowed inside multicols.

Limits: Formula and Table blocks are printed as escaped plain text. Missing glyphs (for
example Greek) give compiler warnings, not errors.
"""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
import difflib
from pathlib import Path
import re
import shutil
import subprocess
from typing import Any

from .segment import clean_running_header

TEMPLATE = Path(__file__).resolve().parents[3] / "templates" / "page.tex"
SPECIALS = {"\\": r"\textbackslash{}", "{": r"\{", "}": r"\}", "$": r"\$", "&": r"\&", "#": r"\#",
            "^": r"\textasciicircum{}", "_": r"\_", "%": r"\%", "~": r"\textasciitilde{}"}
EMPHASIS_RE = re.compile(r"(?<!\w)_([^_\n]{1,80})_(?!\w)")
COMPILE_TIMEOUT = 300
MAX_IN_FLIGHT = 4


def escape(text: str) -> str:
    return "".join(SPECIALS.get(char, char) for char in text)


def inline(text: str) -> str:
    """Escape text for LaTeX and turn markdown _italic_ from Parse into \\emph."""
    parts = EMPHASIS_RE.split(text)
    return "".join(escape(part) if index % 2 == 0 else r"\emph{" + escape(part) + "}" for index, part in enumerate(parts))


def diff_tex(before: str, after: str) -> str:
    """Parse's words struck through, Super VL's correction in bold: 'Calvinia and \\sout{Sprayer} \\textbf{Popery}'."""
    a, b = before.split(), after.split()
    parts = []
    for tag, i1, i2, j1, j2 in difflib.SequenceMatcher(None, a, b, autojunk=False).get_opcodes():
        if tag == "equal":
            parts.append(escape(" ".join(a[i1:i2])))
            continue
        if i2 > i1:
            parts.append(r"\sout{" + escape(" ".join(a[i1:i2])) + "}")
        if j2 > j1:
            parts.append(r"\textbf{" + escape(" ".join(b[j1:j2])) + "}")
    return " ".join(parts)


def two_columns(entries: list[dict[str, Any]], width: int) -> bool:
    """True when column-width blocks sit on both sides of the page middle.

    One block per side is enough: Parse can return a whole column as one block (row 2001).
    Blocks narrower than a quarter page (margin notes, signature marks) do not count.
    """
    left = right = 0
    for entry in entries:
        for block in entry["blocks"]:
            x0, _, x1, _ = block["bbox"]
            if 0.25 * width <= x1 - x0 < 0.6 * width:
                if (x0 + x1) / 2 < width / 2:
                    left += 1
                else:
                    right += 1
    return left >= 1 and right >= 1


def entry_tex(entry: dict[str, Any], correction: dict[str, Any] | None = None) -> str:
    quality = entry["quality"]
    kind = entry["kind"]
    lines = []
    if kind == "plate":
        crop = Path(entry["crop_path"])
        relative = Path("..") / crop.parent.name / crop.name if crop.parent.name == "crops" else crop
        lines.append(r"\begin{center}")
        lines.append(r"\includegraphics[width=\linewidth,height=0.4\textheight,keepaspectratio]{" + relative.as_posix() + "}")
        caption = inline(entry["text"]) if entry["text"] else r"\textit{(no caption)}"
        lines.append(r"\par{\small \textit{Plate:} " + caption + "}")
        lines.append(r"\end{center}")
        return "\n".join(lines)
    if kind == "continuation":
        title = quality.get("running_header")
        heading = r"\textit{continued:} " + escape(str(title)) if title else r"\textit{continued from the previous page}"
    else:
        heading = escape(entry["headword"] or "")
    lines.append(r"\subsection*{" + heading + "}")
    if quality.get("margin_notes"):
        lines.append(r"{\small\itshape [Margin: " + inline(str(quality["margin_notes"])) + "]}\\par")
    if quality.get("low_quality"):
        lines.append(r"{\small\itshape [Low OCR quality: " + f"{quality.get('ocr_suspect_ratio', 0):.0%}".replace("%", r"\%")
                     + " of tokens suspect]}\\par")
    corrected = correction is not None and correction.get("parse") == entry["text"] and correction.get("faithful_changes")
    body = diff_tex(entry["text"], correction["faithful"]) if corrected else inline(entry["text"])
    lines.append(r"\textit{" + body + "}" if kind == "cross_reference" else body)
    return "\n".join(lines)


def page_tex(page: dict[str, Any], entries: list[dict[str, Any]],
             corrections: dict[str, dict[str, Any]] | None = None) -> str:
    corrections = corrections or {}
    body = "\n\n".join(entry_tex(entry, corrections.get(entry["entry_id"])) for entry in entries)
    if two_columns(entries, page["width"]):
        body = "\\begin{multicols}{2}\n" + body + "\n\\end{multicols}"
    titles = [e["headword"] for e in entries if e["kind"] == "entry" and e["headword"]]
    titles += [str(e["quality"]["running_header"]) for e in entries if e["quality"].get("running_header")]
    titles += [clean_running_header(e["text"]) for e in entries if e["kind"] == "plate"]  # 'HYDROSTATICS. Plate ...'
    titles = [t for t in titles if t]
    title = titles[0] if titles else f"scan row {page['row_index']}"
    parse = page["parse"] or {}
    source = "\n".join([
        r"\begin{itemize}",
        r"\item Page ID: \texttt{" + escape(page["page_id"]) + "}",
        r"\item Scan: \texttt{" + escape(page["filename"]) + "}, " + f"{page['width']} x {page['height']} px",
        r"\item Image SHA-256: \texttt{\small " + escape(page["image_sha256"]) + "}",
        r"\item Extraction: \texttt{" + escape(str(parse.get("model", ""))) + r"}, raw reply \texttt{"
        + escape(str(parse.get("raw_path", ""))) + "}",
        r"\item Text is Parse OCR output, normalized (long s as s, line-end hyphens joined). It is not corrected by hand.",
    ] + ([r"\item \sout{Struck-through} words are Parse's reading; \textbf{bold} words are Super VL's correction,"
          r" checked against the scan image. Both are model output."]
         if any(corrections.get(e["entry_id"], {}).get("faithful_changes") for e in entries) else []) + [
        r"\end{itemize}",
    ])
    template = TEMPLATE.read_text(encoding="utf-8")
    return template.replace("%%TITLE%%", escape(title)).replace("%%BODY%%", body).replace("%%SOURCE%%", source)


def tectonic() -> str | None:
    return shutil.which("tectonic") or (str(Path.home() / ".local/bin/tectonic")
                                        if (Path.home() / ".local/bin/tectonic").is_file() else None)


def compile_tex(compiler: str, tex: Path) -> str | None:
    """Compile one file. Return None on success, else the last lines of the compiler output."""
    pdf = tex.with_suffix(".pdf")
    if pdf.is_file() and pdf.stat().st_mtime >= tex.stat().st_mtime:
        return None
    try:
        result = subprocess.run([compiler, "--chatter", "minimal", tex.name], cwd=tex.parent,
                                capture_output=True, text=True, timeout=COMPILE_TIMEOUT)
    except subprocess.TimeoutExpired:
        return f"timed out after {COMPILE_TIMEOUT} s"
    if result.returncode != 0 or not pdf.is_file():
        return "\n".join((result.stdout + result.stderr).strip().splitlines()[-8:])
    return None


def build(pages: list[dict[str, Any]], entries_by_id: dict[str, dict[str, Any]], out: Path,
          compile_pdf: bool = True, corrections: dict[str, dict[str, Any]] | None = None) -> dict[str, Any]:
    """Write one .tex per ok page, then compile them. Unchanged .tex files keep their PDFs."""
    latex_dir = out / "latex"
    latex_dir.mkdir(parents=True, exist_ok=True)
    written = []
    for page in pages:
        tex = latex_dir / f"{page['row_index']:04d}.tex"
        if page["status"] != "ok":
            for stale in (tex, tex.with_suffix(".pdf")):
                stale.unlink(missing_ok=True)  # a page can change status between runs
            continue
        content = page_tex(page, [entries_by_id[eid] for eid in page["entry_ids"]], corrections)
        if not tex.is_file() or tex.read_text(encoding="utf-8") != content:
            tex.write_text(content, encoding="utf-8")
        written.append((page["row_index"], tex))
    compiler = tectonic() if compile_pdf else None
    failed = []
    if compiler:
        with ThreadPoolExecutor(max_workers=MAX_IN_FLIGHT) as pool:
            errors = list(pool.map(lambda item: compile_tex(compiler, item[1]), written))
        failed = [{"row_index": row, "error": error} for (row, _), error in zip(written, errors) if error]
    compiled = sum((latex_dir / f"{row:04d}.pdf").is_file() for row, _ in written)
    if compiler:
        status = "compiled"
    else:  # no compiler on this machine: report the PDFs already in the repository, do not claim 0
        status = f"not compiled on this machine; {compiled} existing PDFs kept"
    return {
        "status": status,
        "compiler": "tectonic" if compiler else None,
        "tex_files": len(written),
        "compiled": compiled,
        "failed": failed,
        "skipped_pages": [p["row_index"] for p in pages if p["status"] != "ok"],
    }
