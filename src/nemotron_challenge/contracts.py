"""Data contracts keep source evidence with team artifacts."""
from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


class Contract(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, allow_inf_nan=False)


class ScanReference(Contract):
    scan_key: str = Field(min_length=1)
    dataset: str
    dataset_revision: str = Field(pattern=r"^[0-9a-f]{40}$")
    split: str
    row_index: int = Field(ge=0)
    source_id: str
    image_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")


class SourceReference(Contract):
    dataset: str
    dataset_revision: str
    source_id: str
    source_url: str
    content_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    license: str


class ArtifactRecord(Contract):
    record_id: str = Field(min_length=1, max_length=200)
    stage: Literal["extract", "match", "compare", "agent", "site", "evaluate"]
    sources: list[SourceReference] = Field(min_length=1)
    artifact_path: str = Field(min_length=1)
    metadata: dict[str, Any] = Field(default_factory=dict)


class WikiProvenance(BaseModel):
    model_config = ConfigDict(extra="ignore", strict=True)
    dataset: str
    dataset_revision: str
    dataset_url: str
    source_key: str
    source_row_idx: int = Field(ge=0)
    source_shard: str | None
    text_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    extraction: str
    revision_url: str


class WikiArticle(BaseModel):
    model_config = ConfigDict(extra="ignore", strict=True, allow_inf_nan=False)
    page_id: str = Field(pattern=r"^[0-9]{1,20}$")
    revision_id: str = Field(pattern=r"^[0-9]+$")
    title: str
    url: str
    provenance: WikiProvenance
    license: dict[str, str]
    text: str
    offset: int = Field(ge=0)
    returned_chars: int = Field(ge=0)
    total_chars: int = Field(ge=0)
    next_offset: int | None

    @model_validator(mode="after")
    def valid_page(self) -> WikiArticle:
        if self.returned_chars != len(self.text) or self.offset + self.returned_chars > max(self.offset, self.total_chars):
            raise ValueError("article page length differs from its metadata")
        expected_next = self.offset + self.returned_chars if self.offset + self.returned_chars < self.total_chars else None
        if self.next_offset != expected_next:
            raise ValueError("article page continuation differs from its metadata")
        return self


class WikiHit(BaseModel):
    model_config = ConfigDict(extra="ignore", strict=True, allow_inf_nan=False)
    page_id: str = Field(pattern=r"^[0-9]{1,20}$")
    revision_id: str = Field(pattern=r"^[0-9]+$")
    title: str
    url: str
    provenance: WikiProvenance
    license: dict[str, str]
    rank: int = Field(ge=1)
    bm25_score: float
    excerpt: str
    excerpt_offset: int = Field(ge=0)
    total_chars: int = Field(ge=0)


class WikiSearch(BaseModel):
    model_config = ConfigDict(extra="ignore", strict=True)
    query: str
    retrieval: Literal["lexical_bm25"]
    corpus_revision: str
    count: int = Field(ge=0)
    hits: list[WikiHit]


class ParseRun(Contract):
    model: str
    latency_ms: int
    finish_reason: str
    raw_path: str                      # artifacts/extract/raw/{row_index:04d}.json


class PageRecord(Contract):            # artifacts/extract/pages.jsonl, one per manifest scan (100 rows)
    page_id: str                       # manifest page_id, e.g. britannica:<rev>:train:13
    row_index: int
    volume_id: str
    filename: str
    image_sha256: str
    width: int
    height: int
    status: Literal["ok", "blank", "illegible", "failed"]
    parse: ParseRun | None
    error: str | None = None
    entry_ids: list[str]


class Block(Contract):
    page_id: str
    bbox: list[float] = Field(min_length=4, max_length=4)   # x0,y0,x1,y1 in source-image pixels
    cls: str                           # Parse class as returned (Text, Section-header, Picture, ...)
    text: str


class EntryRecord(Contract):           # artifacts/extract/entries.jsonl
    entry_id: str                      # "e{row_index:04d}-{n:02d}", n = reading order on first page
    kind: Literal["entry", "continuation", "plate", "cross_reference"]
    headword: str | None
    text: str                          # normalized (long s -> s, line-end hyphens joined)
    text_raw: str                      # exact Parse text, concatenated blocks
    blocks: list[Block] = Field(min_length=1)
    crop_path: str                     # artifacts/extract/crops/{entry_id}.png
    continues_from: str | None = None
    continues_to: str | None = None
    quality: dict[str, float | bool | str] = Field(default_factory=dict)


class WikiRef(Contract):
    page_id: str
    revision_id: str
    title: str
    url: str


class CandidateScore(Contract):
    wiki: WikiRef
    bm25_rank: int
    bm25_score: float
    excerpt: str
    excerpt_offset: int
    embed_cosine: float | None = None
    embed_rank: int | None = None
    rerank_logit: float | None = None
    rerank_rank: int | None = None


class MatchRecord(Contract):           # artifacts/match/matches.jsonl, one per EntryRecord
    entry_id: str
    status: Literal["matched", "rejected", "no_candidates", "skipped"]
    reason: str                        # human-readable rule that fired
    queries: list[str]
    candidates: list[CandidateScore]   # every pooled candidate, all scores kept
    match: WikiRef | None
    rerank_margin: float | None
    method_version: str


class TermRow(Contract):
    term: str
    brit_count: int
    wiki_count: int
    brit_per_10k: float
    wiki_per_10k: float
    log_ratio: float
    brit_example: dict[str, str]       # {"entry_id", "quote"}
    wiki_example: dict[str, str]       # {"page_id", "revision_id", "quote"}


class DriftReport(Contract):           # artifacts/compare/drift.json
    method: str
    exclusions: list[str]
    pairs_used: int
    brit_tokens: int
    wiki_tokens: int
    terms: list[TermRow]


class ToolCall(Contract):
    name: str
    arguments: dict[str, Any]
    result: str
    error: str | None = None


class RunRecord(Contract):             # artifacts/agent/runs/{run_id}.json
    run_id: str
    started_at: str                    # ISO 8601 UTC
    code_revision: str                 # git SHA
    hermes_version: str
    model: str                         # model ID from the reply, not from config
    question: str
    image_inputs: list[str]
    tools_enabled: bool
    tool_calls: list[ToolCall]
    answer: str
    citations: list[dict[str, str]]
    finish_reason: str
    label: Literal["unreviewed", "success", "failure"] = "unreviewed"
    notes: str = ""


class EvidenceCheck(Contract):
    name: str
    kind: Literal["observation", "inference"]
    passed: bool | None                # None = not checked (input missing)
    detail: str


class CaseStudy(Contract):             # artifacts/evaluate/report.json, cases[]
    case_id: str
    classification: Literal["success", "failure"]
    classification_source: str         # where the label came from, e.g. "run.label"
    run_id: str
    run_path: str
    code_revision: str
    model: str
    question: str
    answer: str
    citations: list[dict[str, str]]
    tool_calls: int
    tool_errors: int
    finish_reason: str
    review_notes: str
    checks: list[EvidenceCheck]
    earlier_attempts: list[str]        # run_ids of earlier runs on the same question
    repaired_by: str | None            # later success run on the same question
    case_path: str                     # artifacts/evaluate/cases/{case_id}.md


class ReproductionRecord(Contract):    # artifacts/evaluate/report.json, reproduction
    code_revision: str
    code_revision_source: str
    working_tree_clean: bool | None
    run_code_revisions: list[str]
    python_version: str
    packages: dict[str, str]
    models: dict[str, Any]
    data: dict[str, Any]
    hermes_versions: list[str]
    counts: dict[str, Any]
    commands: list[str]
    known_limits: list[str]


class EvaluationReport(Contract):      # artifacts/evaluate/report.json
    status: Literal["ok", "incomplete"]
    generated_at: str                  # ISO 8601 UTC
    inputs_dir: str
    fixture_inputs: bool
    required_per_label: int
    selected: dict[str, int]
    missing: dict[str, int]
    unreviewed_run_ids: list[str]
    unselected_run_ids: list[str]
    cases: list[CaseStudy]
    reproduction: ReproductionRecord
