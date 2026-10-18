"""Build the reproduction record: code revision, model IDs, data revisions, counts, and limits."""
from __future__ import annotations

from collections import Counter
import importlib.metadata
import json
from pathlib import Path
import platform
import subprocess
from typing import Any

from ..config import (
    EMBED_MODEL,
    EMBED_REVISION,
    PARSE_MODEL,
    RERANK_MODEL,
    RERANK_REVISION,
    SUPER_MODEL,
    WIKIPEDIA_REVISION,
)
from ..contracts import DriftReport, MatchRecord, PageRecord, ReproductionRecord, RunRecord
from ..data import load_manifest

PACKAGES = ("httpx", "pydantic", "python-dotenv", "lancedb", "pyarrow", "huggingface-hub")
REPRODUCE_COMMANDS = [
    "uv sync --locked",
    "cp .env.example .env  # then set your own keys and URLs",
    "uv run nemotron-challenge doctor --offline",
    "uv run nemotron-challenge data fetch",
    "uv run nemotron-challenge run extract",
    "uv run nemotron-challenge run match",
    "uv run nemotron-challenge run compare",
    "uv run nemotron-challenge run agent",
    "uv run nemotron-challenge run site",
    "uv run nemotron-challenge run evaluate",
    "uv run pytest",
]
STATIC_LIMITS = [
    "Fixture tests prove the setup. They do not prove OCR accuracy or retrieval quality.",
    "Automated checks compare citation ids and quotes with saved records. They do not verify factual claims.",
    "The success or failure label comes from the team's review in each run record, not from the checks.",
    "Uncertainty-claim detection is a phrase rule. A reviewer must confirm it against the evidence.",
]


def _git(args: list[str], cwd: Path) -> str | None:
    try:
        result = subprocess.run(["git", *args], cwd=cwd, capture_output=True, text=True, timeout=10, check=False)
    except (OSError, subprocess.SubprocessError):
        return None
    return result.stdout.strip() if result.returncode == 0 else None


def code_revision(runs: list[RunRecord], repo_dir: Path) -> tuple[str, str, bool | None]:
    """Return (sha, source, working_tree_clean). Git wins; run records are the fallback."""
    sha = _git(["rev-parse", "HEAD"], repo_dir)
    if sha:
        status = _git(["status", "--porcelain"], repo_dir)
        return sha, "git rev-parse HEAD", (status == "") if status is not None else None
    run_shas = sorted({run.code_revision for run in runs})
    if len(run_shas) == 1:
        return run_shas[0], "run records (git unavailable)", None
    return "unknown", "git unavailable and run records disagree or are empty", None


def package_versions() -> dict[str, str]:
    versions = {}
    for package in PACKAGES:
        try:
            versions[package] = importlib.metadata.version(package)
        except importlib.metadata.PackageNotFoundError:
            versions[package] = "missing"
    return versions


def retrieval_service(inputs_dir: Path) -> dict[str, Any]:
    smoke = inputs_dir / "match" / "model-service-smoke.json"
    if not smoke.exists():
        return {"status": "no smoke record at artifacts/match/model-service-smoke.json"}
    try:
        data = json.loads(smoke.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        return {"status": f"unreadable smoke record: {exc}"}
    runtime = data.get("runtime", {})
    return {
        "status": "smoke record present",
        "checked_at": data.get("checked_at"),
        "models": [{"id": m.get("id"), "revision": m.get("revision"), "role": m.get("role")} for m in data.get("models", [])],
        "precision": runtime.get("precision"),
        "backend": runtime.get("backend"),
        "weights_verified": runtime.get("weights_verified"),
    }


def model_record(runs: list[RunRecord], inputs_dir: Path) -> dict[str, Any]:
    return {
        "parse": {"id": PARSE_MODEL, "deployment": "shared organizer endpoint"},
        "embed": {"id": EMBED_MODEL, "revision": EMBED_REVISION, "deployment": "team Nebius AI Cloud service"},
        "rerank": {"id": RERANK_MODEL, "revision": RERANK_REVISION, "deployment": "team Nebius AI Cloud service"},
        "super": {"id": SUPER_MODEL, "deployment": "Nebius Token Factory through Hermes"},
        "super_ids_in_runs": sorted({run.model for run in runs}),
        "retrieval_service": retrieval_service(inputs_dir),
    }


def data_record() -> dict[str, Any]:
    try:
        manifest = load_manifest()
    except (OSError, ValueError) as exc:
        britannica: dict[str, Any] = {"status": f"manifest unavailable: {exc}"}
    else:
        britannica = {
            "dataset": manifest["dataset"],
            "revision": manifest["revision"],
            "manifest_sha256": manifest["manifest_sha256"],
            "source_file_sha256": manifest["source_file_sha256"],
            "sample_size": manifest["sample_size"],
            "selection": manifest["selection"],
        }
    return {
        "britannica": britannica,
        "wikipedia": {"dataset": "wikimedia/structured-wikipedia", "revision": WIKIPEDIA_REVISION,
                      "access": "shared BM25 API over the pinned snapshot"},
    }


def counts_record(pages: list[PageRecord], matches: list[MatchRecord], drift: DriftReport | None,
                  runs: list[RunRecord]) -> dict[str, Any]:
    return {
        "pages_by_status": dict(sorted(Counter(page.status for page in pages).items())),
        "entries": sum(len(page.entry_ids) for page in pages),
        "matches_by_status": dict(sorted(Counter(match.status for match in matches).items())),
        "compare": None if drift is None else {
            "method": drift.method, "pairs_used": drift.pairs_used,
            "exclusions": len(drift.exclusions), "terms": len(drift.terms),
        },
        "runs_by_label": dict(sorted(Counter(run.label for run in runs).items())),
    }


def build_reproduction(*, runs: list[RunRecord], pages: list[PageRecord], matches: list[MatchRecord],
                       drift: DriftReport | None, inputs_dir: Path, repo_dir: Path,
                       extra_limits: list[str]) -> ReproductionRecord:
    sha, source, clean = code_revision(runs, repo_dir)
    return ReproductionRecord(
        code_revision=sha,
        code_revision_source=source,
        working_tree_clean=clean,
        run_code_revisions=sorted({run.code_revision for run in runs}),
        python_version=platform.python_version(),
        packages=package_versions(),
        models=model_record(runs, inputs_dir),
        data=data_record(),
        hermes_versions=sorted({run.hermes_version for run in runs}),
        counts=counts_record(pages, matches, drift, runs),
        commands=list(REPRODUCE_COMMANDS),
        known_limits=[*STATIC_LIMITS, *extra_limits],
    )
