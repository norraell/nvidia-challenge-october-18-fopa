from pathlib import Path
from typing import Any

from ..config import Settings
from . import _unfinished


def run(settings: Settings, work_dir: Path) -> dict[str, Any]:
    _unfinished("evaluate")
