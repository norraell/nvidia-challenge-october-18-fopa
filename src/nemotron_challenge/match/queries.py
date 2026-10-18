"""Build the three BM25 queries for one entry. Pure functions, no network."""
from __future__ import annotations

from collections import Counter
from functools import lru_cache
from pathlib import Path
import re

from ..contracts import EntryRecord

IMAGE_MARKERS = ("<image>", "<img>", "</img>", "<IMG_CONTEXT>")
MAX_QUERY_CHARS = 512
MAX_QUERY_WORDS = 64
CONTENT_WORDS_WITH_HEADWORD = 15
CONTENT_WORDS_ALONE = 20
MIN_CONTENT_WORD_LETTERS = 4
WORD_LIST_PATHS = (Path("/usr/share/dict/words"), Path("/usr/share/dict/american-english"))

STOPWORDS = frozenset("""
about above after again against also among another anything because been before being below between
both call called cannot could does doing done down during each either else even ever every first from
further great hath have having here himself however into itself just least less like many might more
most much must never once only other others ought over same says several shall should since some
something still such than that their theirs them themselves then thence there therefore these they
thing things this those though through thus till toward towards under until unto upon very were what
whatever when whence where wherein whether which while whither whole whom whose will with within without
would your yours very also well made make makes making much many part parts manner means much more
whole sort kind kinds take taken given give form forms general called name names
""".split())

HEADER_NOISE = frozenset({"part", "chap", "chapter", "plate", "book", "sect", "sc", "section", "vol"})
ROMAN = re.compile(r"^[ivxlcdm]{2,}$", re.IGNORECASE)  # single letters stay: they may be spaced capitals
WORD = re.compile(r"[A-Za-z][A-Za-z'-]*")
TOKEN_RE = re.compile(r"<x_[0-9.]+><y_[0-9.]+>|<class_[A-Za-z-]+>")


def strip_image_markers(text: str) -> str:
    for marker in IMAGE_MARKERS:
        text = text.replace(marker, " ")
    return text


def clean_text(text: str) -> str:
    """Remove Parse tokens, reserved markers, control characters, and extra whitespace."""
    text = TOKEN_RE.sub(" ", text)
    text = strip_image_markers(text)
    text = "".join(ch if ch >= " " or ch in "\n\t" else " " for ch in text)
    return re.sub(r"\s+", " ", text).strip()


def cut(text: str, limit: int) -> str:
    """Cut text to at most `limit` characters on a word boundary when possible."""
    text = text.strip()
    if len(text) <= limit:
        return text
    head = text[:limit]
    space = head.rfind(" ")
    return (head[:space] if space > limit // 2 else head).strip()


@lru_cache(maxsize=1)
def word_list() -> frozenset[str] | None:
    for path in WORD_LIST_PATHS:
        if path.exists():
            return frozenset(w.strip().lower() for w in path.read_text(errors="ignore").splitlines() if w.strip().isalpha())
    return None


def _join_spaced_letters(tokens: list[str]) -> list[str]:
    """Join runs like ['O','P','T','I','C','S'] or ['ABY','S','SINIA'] into one word."""
    out: list[str] = []
    run: list[str] = []

    def flush() -> None:
        if not run:
            return
        if len(run) > 1 and any(len(t) == 1 for t in run) and all(t.isupper() for t in run):
            out.append("".join(run))
        else:
            out.extend(run)
        run.clear()

    for tok in tokens:
        if tok.isupper():
            run.append(tok)
        else:
            flush()
            out.append(tok)
    flush()
    return out


def is_range_header(header: str) -> bool:
    """`HEL (781) HEM`, `DAM [ 658]`, `182 COM COM` are dictionary range headers."""
    if re.search(r"[\[\(\|{]\s*\d|\d\s*[\]\)\|}J]", header):
        return True
    tokens = _header_tokens(header)
    if not tokens:
        return False
    if len(tokens) == 2 and all(len(t) <= 4 and t.isupper() for t in tokens):
        return True
    if len(tokens) == 1:
        tok = tokens[0]
        half = len(tok) // 2
        if len(tok) % 2 == 0 and len(tok) >= 4 and tok[:half] == tok[half:]:
            return True
    return False


def _header_tokens(header: str) -> list[str]:
    header = header.replace("*", " ")
    tokens = [t for t in WORD.findall(header) if t.lower() not in HEADER_NOISE and not ROMAN.fullmatch(t)]
    if any(t.isupper() and len(t) >= 4 for t in tokens):
        tokens = [t for t in tokens if not (t.islower() and len(t) <= 3)]  # `6goa` is a misread page number
    return _join_spaced_letters(tokens)


def normalize_header(header: str) -> str | None:
    """`292 SHIP-BUILDING.` gives `SHIP-BUILDING`. A dictionary range header gives None."""
    if not header or is_range_header(header):
        return None
    tokens = _header_tokens(header)
    if not tokens:
        return None
    result = " ".join(tokens).strip("-' ")
    return result or None


def headword_variants(headword: str) -> list[str]:
    """`SHIP-BUILDING` gives ['shipbuilding', 'ship building']."""
    base = re.sub(r"[^A-Za-z' -]", " ", headword).lower()
    base = re.sub(r"\s+", " ", base).strip(" -'")
    if not base:
        return []
    variants = [base.replace("-", "").replace(" ", " ")] if "-" in base else [base]
    if "-" in base:
        variants.append(base.replace("-", " "))
    seen: list[str] = []
    for v in variants:
        v = re.sub(r"\s+", " ", v).strip()
        if v and v not in seen:
            seen.append(v)
    return seen


def headword_from_text(text: str) -> str | None:
    """`ABACUS, among the ancients...` gives `ABACUS`."""
    text = clean_text(text)
    match = re.match(r"^([A-Z][A-Z' -]{1,40}?)(?=[,.;:(]|\s[a-z])", text)
    if not match:
        return None
    word = match.group(1).strip(" -'")
    return word if len(word) >= 2 else None


def _looks_like_word(token: str) -> bool:
    if len(token) < MIN_CONTENT_WORD_LETTERS or not token.isalpha():
        return False
    if not re.search(r"[aeiouy]", token):
        return False
    if re.search(r"(.)\1\1", token):
        return False
    return True


def content_words(text: str, limit: int, exclude: set[str] | None = None) -> list[str]:
    """Most frequent informative words: not stopwords, 4+ letters, in the word list when available."""
    words = word_list()
    exclude = {w.lower() for w in (exclude or set())}
    counts: Counter[str] = Counter()
    first_seen: dict[str, int] = {}
    for position, raw in enumerate(WORD.findall(clean_text(text))):
        token = raw.lower().strip("'-")
        if token in STOPWORDS or token in exclude or not _looks_like_word(token):
            continue
        if words is not None and token not in words:
            continue
        counts[token] += 1
        first_seen.setdefault(token, position)
    ranked = sorted(counts, key=lambda w: (-counts[w], first_seen[w]))
    return ranked[:limit]


def fit_query(text: str) -> str:
    words = text.split()[:MAX_QUERY_WORDS]
    return cut(" ".join(words), MAX_QUERY_CHARS)


def resolve_headword(entry: EntryRecord) -> str | None:
    if entry.headword:
        normalized = normalize_header(entry.headword)
        if normalized:
            return normalized
    if entry.kind == "entry":
        return headword_from_text(entry.text)
    return None


def build_queries(entry: EntryRecord) -> list[dict[str, str]]:
    """Return up to three queries as {'kind': ..., 'text': ...}. Kinds: headword, headword_content, content."""
    headword = resolve_headword(entry)
    variants = headword_variants(headword) if headword else []
    head_terms = set(" ".join(variants).split())
    queries: list[dict[str, str]] = []
    if variants:
        queries.append({"kind": "headword", "text": fit_query(" ".join(variants))})
        words = content_words(entry.text, CONTENT_WORDS_WITH_HEADWORD, exclude=head_terms)
        if words:
            queries.append({"kind": "headword_content", "text": fit_query(" ".join([variants[0], *words]))})
    words = content_words(entry.text, CONTENT_WORDS_ALONE)
    if words:
        queries.append({"kind": "content", "text": fit_query(" ".join(words))})
    unique: list[dict[str, str]] = []
    for q in queries:
        if q["text"] and all(q["text"] != u["text"] for u in unique):
            unique.append(q)
    return unique
