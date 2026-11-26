"""Fresh private bulk staging for one native game."""
from contextlib import contextmanager
import os
from pathlib import Path
import tempfile


def configured_scratch(option):
    value = option if option is not None else os.environ.get("ADJOIN_MATCH_SCRATCH")
    return Path(value) if value else None


@contextmanager
def match_scratch(option, inputs=(), *, default=None):
    root = configured_scratch(option)
    parent = root if root is not None else default
    if parent is not None:
        parent = Path(parent)
        if not parent.is_absolute() or not parent.is_dir():
            raise ValueError("Match scratch root must be an existing absolute directory.")
        parent = parent.resolve()
        if any((path / ".git").exists() for path in (parent, *parent.parents)):
            raise ValueError("Match scratch must be outside a source checkout.")
        if any(parent.is_relative_to(Path(source).resolve()) for source in inputs):
            raise ValueError("Match scratch must be outside game data and retained outputs.")
    with tempfile.TemporaryDirectory(prefix="jk-force-", dir=parent) as owned:
        scratch = Path(owned).resolve()
        # On some Windows-backed mounts Linux chmod does not isolate a directory.
        if os.name == "posix" and scratch.stat().st_mode & 0o077:
            raise ValueError("Match scratch filesystem must support private mode 0700 directories.")
        if any((path / ".git").exists() for path in scratch.parents) or any(
                scratch.is_relative_to(Path(source).resolve()) for source in inputs):
            raise ValueError("Match scratch overlaps a source checkout, game data or retained outputs.")
        yield scratch
