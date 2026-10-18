"""Fetch full Wikipedia articles with pagination, verify sha256, and cache them."""
from __future__ import annotations

from collections.abc import Callable
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import time
from typing import Any, Protocol

from ..clients import ProtocolError
from ..contracts import WikiArticle
from .candidates import call_with_retry

PAGE_CHARS = 20000
INDEX_FIELDS = ("page_id", "revision_id", "title", "url", "text_sha256", "total_chars")


class ArticleReader(Protocol):
    def article(self, page_id: str, offset: int = ..., max_chars: int = ...) -> WikiArticle: ...


def fetch_article(client: ArticleReader, page_id: str, *, sleep: Callable[[float], None] = time.sleep,
                  attempts_log: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    """Read every page of the article, concatenate in offset order, and verify the checksum."""
    offset: int | None = 0
    parts: list[str] = []
    first: WikiArticle | None = None
    while offset is not None:
        page = call_with_retry(lambda o=offset: client.article(page_id, offset=o, max_chars=PAGE_CHARS),
                               sleep=sleep, attempts_log=attempts_log)
        first = first or page
        if page.revision_id != first.revision_id:
            raise ProtocolError(f"article {page_id} changed revision during pagination")
        parts.append(page.text)
        offset = page.next_offset
    assert first is not None
    text = "".join(parts)
    digest = hashlib.sha256(text.encode("utf-8")).hexdigest()
    if digest != first.provenance.text_sha256 or len(text) != first.total_chars:
        raise ProtocolError(f"article {page_id} text hash or length differs from its provenance")
    return {
        "page_id": first.page_id, "revision_id": first.revision_id, "title": first.title, "url": first.url,
        "provenance": first.provenance.model_dump(), "license": first.license, "text": text,
        "total_chars": first.total_chars, "fetched_at": datetime.now(timezone.utc).isoformat(),
    }


def article_path(cache_dir: Path, page_id: str) -> Path:
    return cache_dir / "articles" / f"{page_id}.json"


def load_cached_article(cache_dir: Path, page_id: str) -> dict[str, Any] | None:
    path = article_path(cache_dir, page_id)
    if not path.exists():
        return None
    data = json.loads(path.read_text())
    digest = hashlib.sha256(data["text"].encode("utf-8")).hexdigest()
    if digest != data["provenance"]["text_sha256"]:
        path.unlink()
        return None
    return data


def cache_article(cache_dir: Path, article: dict[str, Any]) -> Path:
    path = article_path(cache_dir, article["page_id"])
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(article, ensure_ascii=False))
    tmp.replace(path)
    return path


def index_row(article: dict[str, Any]) -> dict[str, Any]:
    row = {k: article[k] for k in INDEX_FIELDS if k in article}
    row["text_sha256"] = article["provenance"]["text_sha256"]
    return {k: row[k] for k in INDEX_FIELDS}


def write_articles_index(path: Path, articles: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    rows = sorted((index_row(a) for a in articles), key=lambda r: int(r["page_id"]))
    path.write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in rows))
