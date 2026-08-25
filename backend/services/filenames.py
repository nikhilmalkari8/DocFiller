"""Filename derivation for generated documents."""
import re
from typing import Optional

_ILLEGAL_CHARS = re.compile(r'[/\\:*?"<>|\x00-\x1f]')
_WHITESPACE_RUN = re.compile(r"\s+")
_MAX_BASENAME_LENGTH = 60


def _sanitize(raw: str) -> str:
    value = _ILLEGAL_CHARS.sub("_", raw)
    value = _WHITESPACE_RUN.sub("_", value)
    value = value.strip(" .")
    return value[:_MAX_BASENAME_LENGTH]


def build_filenames(
    rows: list[dict[str, str]], filename_column: Optional[str], ext: str
) -> list[str]:
    """
    Derive a unique filename per row.

    Rules:
    1. Raw name = row[filename_column], trimmed.
    2. Sanitize illegal filesystem characters and collapse whitespace.
    3. Truncate to 60 characters.
    4. Empty after sanitizing (blank cell, or no filename_column) -> row_{n}.
    5. Collision: every colliding sanitized name gets _row_{n} appended.
    6. Append the template's own extension.
    """
    basenames = []
    for i, row in enumerate(rows):
        n = i + 1
        raw = str(row.get(filename_column, "")).strip() if filename_column else ""
        sanitized = _sanitize(raw)
        basenames.append(sanitized if sanitized else f"row_{n}")

    counts: dict[str, int] = {}
    for name in basenames:
        counts[name] = counts.get(name, 0) + 1

    filenames = []
    for i, name in enumerate(basenames):
        n = i + 1
        if counts[name] > 1:
            filenames.append(f"{name}_row_{n}{ext}")
        else:
            filenames.append(f"{name}{ext}")

    return filenames
