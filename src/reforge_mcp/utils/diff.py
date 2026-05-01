"""Diff application utility."""

import re
from pathlib import Path

_HUNK_HEADER = re.compile(r"^@@ -(\d+)(?:,(\d+))? \+(\d+)(?:,(\d+))? @@")


def _parse_hunks(diff_str: str) -> list[dict]:
    hunks: list[dict] = []
    current: dict | None = None
    for line in diff_str.splitlines(keepends=True):
        m = _HUNK_HEADER.match(line)
        if m:
            if current is not None:
                hunks.append(current)
            current = {
                "old_start": int(m.group(1)),
                "old_count": int(m.group(2)) if m.group(2) is not None else 1,
                "lines": [],
            }
        elif current is not None:
            current["lines"].append(line)
    if current is not None:
        hunks.append(current)
    return hunks


def apply_diff(file_path: str | Path, diff_str: str) -> bool:
    """Apply a unified diff to a file atomically via .tmp rename. Returns True on success."""
    path = Path(file_path)
    try:
        original = path.read_text(encoding="utf-8")
    except OSError:
        return False

    hunks = _parse_hunks(diff_str)
    if not hunks:
        return False

    lines = original.splitlines(keepends=True)
    result = list(lines)
    offset = 0

    try:
        for hunk in hunks:
            start = hunk["old_start"] - 1 + offset
            old_count = hunk["old_count"]
            replacement: list[str] = []
            for line in hunk["lines"]:
                if line.startswith("\\"):
                    continue
                if line.startswith((" ", "+")):
                    replacement.append(line[1:])
                # "-" lines are dropped from output
            result[start : start + old_count] = replacement
            offset += len(replacement) - old_count
    except (IndexError, ValueError):
        return False

    tmp = path.with_suffix(path.suffix + ".tmp")
    try:
        tmp.write_text("".join(result), encoding="utf-8")
        tmp.replace(path)
    except OSError:
        tmp.unlink(missing_ok=True)
        return False
    return True


def rollback(file_path: str | Path) -> bool:
    """Restore a file from its .bak backup created before apply_diff. Returns True on success."""
    path = Path(file_path)
    bak = path.with_suffix(path.suffix + ".bak")
    if not bak.exists():
        return False
    try:
        bak.replace(path)
        return True
    except OSError:
        return False
