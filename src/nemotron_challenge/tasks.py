"""Teams implement these stages with their coding agents."""
from pathlib import Path
from typing import Any

from .config import Settings
from . import stages
from .stages import _unfinished

STAGES = ("extract", "match", "compare", "agent", "site", "evaluate")


def extract(settings: Settings, work_dir: Path) -> dict[str, Any]:
    """TODO: define your extraction and entry segmentation process."""
    return stages.extract.run(settings, work_dir)


def match(settings: Settings, work_dir: Path) -> dict[str, Any]:
    """TODO: define how your team finds and verifies article matches."""
    return stages.match.run(settings, work_dir)


def compare(settings: Settings, work_dir: Path) -> dict[str, Any]:
    """TODO: define your vocabulary, frequency, or topic comparison."""
    return stages.compare.run(settings, work_dir)


def agent(settings: Settings, work_dir: Path) -> dict[str, Any]:
    """Run the saved questions through Hermes and save a RunRecord for each."""
    return stages.agent.run(settings, work_dir)


def site(settings: Settings, work_dir: Path) -> dict[str, Any]:
    """TODO: build your LaTeX documents and static website."""
    return stages.site.run(settings, work_dir)


def evaluate(settings: Settings, work_dir: Path) -> dict[str, Any]:
    """TODO: review your results and document successes and failures."""
    return stages.evaluate.run(settings, work_dir)
