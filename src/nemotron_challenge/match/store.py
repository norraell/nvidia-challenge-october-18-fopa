"""LanceDB tables for entry and article vectors. The agent stage searches these tables."""
from __future__ import annotations

from pathlib import Path
from typing import Any

from ..config import EMBED_DIMENSIONS

ENTRIES_TABLE = "entries"
ARTICLES_TABLE = "articles"


class VectorStore:
    def __init__(self, path: str | Path):
        import lancedb
        import pyarrow as pa

        self.db = lancedb.connect(str(path))
        vector = pa.list_(pa.float32(), EMBED_DIMENSIONS)
        self.entries = self.db.create_table(ENTRIES_TABLE, exist_ok=True, schema=pa.schema([
            ("entry_id", pa.string()), ("vector", vector), ("text_sha256", pa.string()), ("page_id", pa.string()),
        ]))
        self.articles = self.db.create_table(ARTICLES_TABLE, exist_ok=True, schema=pa.schema([
            ("page_id", pa.string()), ("revision_id", pa.string()), ("vector", vector), ("text_sha256", pa.string()),
            ("title", pa.string()),
        ]))

    def put_entry(self, entry_id: str, vector: list[float], text_sha256: str, page_id: str) -> None:
        self.entries.merge_insert("entry_id").when_matched_update_all().when_not_matched_insert_all().execute([
            {"entry_id": entry_id, "vector": vector, "text_sha256": text_sha256, "page_id": page_id}])

    def put_article(self, page_id: str, revision_id: str, vector: list[float], text_sha256: str, title: str) -> None:
        self.articles.merge_insert("page_id").when_matched_update_all().when_not_matched_insert_all().execute([
            {"page_id": page_id, "revision_id": revision_id, "vector": vector, "text_sha256": text_sha256, "title": title}])

    def has_article(self, page_id: str) -> bool:
        escaped = page_id.replace("'", "''")
        return bool(self.articles.search().where(f"page_id = '{escaped}'").select(["page_id"]).limit(1).to_list())

    def counts(self) -> dict[str, int]:
        return {ENTRIES_TABLE: self.entries.count_rows(), ARTICLES_TABLE: self.articles.count_rows()}

    def search_articles(self, vector: list[float], limit: int = 5) -> list[dict[str, Any]]:
        return self.articles.search(vector).limit(limit).select(["page_id", "revision_id", "title", "text_sha256"]).to_list()
