"""Locate Docker-recorded result inputs in this checkout without changing evidence.

Only the framework's known /workspace/results mount is portable. Literal existing
paths take precedence; callers still own hash, size and symlink verification.
Recorded paths and sealed files are never rewritten or searched for by basename.
"""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
CONTAINER_RESULTS = Path('/workspace/results')


def result_path(value):
    """Resolve an absent Docker result path against the active repository root."""
    path = Path(value)
    if ROOT == CONTAINER_RESULTS.parent or not path.is_relative_to(CONTAINER_RESULTS):
        return path
    if '..' in path.parts:
        raise ValueError('result path must not traverse outside its recorded location')
    # Do not replace a present path, a dangling symlink, or a symlinked ancestor.
    # A mismatch at that location must fail the normal integrity check.
    if path.exists() or any(p.is_symlink() for p in (path, *path.parents)):
        return path
    return ROOT / 'results' / path.relative_to(CONTAINER_RESULTS)
