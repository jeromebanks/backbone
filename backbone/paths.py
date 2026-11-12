"""Output paths built from identifiers (question IDs, MRNs) must stay inside their output directory."""
from __future__ import annotations

import re
from pathlib import Path

SAFE_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]*")


def safe_output_path(base: Path, ident, suffix: str) -> Path:
    """`base / (ident + suffix)`, or ValueError if `ident` is not a plain file-name identifier (letters, digits,
    `.`, `_`, `-`; no separators, traversal or absolute paths) or the result would resolve outside `base`."""
    if not isinstance(ident, str) or not SAFE_ID.fullmatch(ident) or ".." in ident:
        raise ValueError(f"unsafe identifier for an output file name: {ident!r}")
    path = Path(base) / f"{ident}{suffix}"
    if not path.resolve().is_relative_to(Path(base).resolve()):
        raise ValueError(f"output path escapes {base}: {ident!r}")
    return path
