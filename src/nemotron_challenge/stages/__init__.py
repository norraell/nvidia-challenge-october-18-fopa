"""Stage implementations for the challenge milestones."""


def _unfinished(stage: str) -> None:
    raise NotImplementedError(
        f"TODO: implement the {stage} milestone. Read docs/milestones.md#{stage}. "
        "The starter has no result for this stage."
    )


from . import agent, compare, evaluate, extract, match, site
__all__ = [
    "_unfinished",
    "agent",
    "compare",
    "evaluate",
    "extract",
    "match",
    "site",
]
