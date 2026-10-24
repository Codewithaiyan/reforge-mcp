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


def _same_line(a: str, b: str) -> bool:
    # Compare ignoring line endings, so an LF diff applies to a CRLF file.
    return a.rstrip("\r\n") == b.rstrip("\r\n")


def _dominant_newline(text: str) -> str:
    """The line ending the file mostly uses, so a patch can keep using it."""
    crlf = text.count("\r\n")
    return "\r\n" if crlf > text.count("\n") - crlf else "\n"


def _reterminate(line: str, newline: str) -> str:
    """
    Give a line from the diff the file's own ending.

    Replacement lines come out of the diff, so without this a CRLF file
    patched by an LF diff ends up with mixed endings inside the hunk.
    """
    body = line.rstrip("\r\n")
    return body + newline if body != line else body


def apply_diff(file_path: str | Path, diff_str: str) -> bool:
    """Apply a unified diff to a file atomically via .tmp rename. Returns True on success.

    Rejects the whole diff unless every hunk's context and removed lines match
    the file at the position the hunk header claims; a mismatched diff must never
    partially modify the file.
    """
    path = Path(file_path)
    try:
        # newline="" so the file's own endings survive the round trip.
        # With translation on, writing back an LF file on Windows rewrote
        # every line as CRLF: a diff changing two lines touched all of them.
        with path.open(encoding="utf-8", newline="") as fh:
            original = fh.read()
    except (OSError, UnicodeDecodeError):
        return False

    hunks = _parse_hunks(diff_str)
    if not hunks:
        return False

    lines = original.splitlines(keepends=True)
    result = list(lines)
    offset = 0
    newline = _dominant_newline(original)

    for hunk in hunks:
        old_count = hunk["old_count"]
        # A zero-count hunk inserts *after* the line in its header, so old_start
        # is already the 0-based insertion index.
        start = hunk["old_start"] + offset
        if old_count:
            start -= 1

        expected: list[str] = []
        replacement: list[str] = []
        for line in hunk["lines"]:
            if line.startswith("\\"):  # "\ No newline at end of file"
                continue
            if line.startswith(" "):
                expected.append(line[1:])
                replacement.append(_reterminate(line[1:], newline))
            elif line.startswith("-"):
                expected.append(line[1:])
            elif line.startswith("+"):
                replacement.append(_reterminate(line[1:], newline))

        if len(expected) != old_count:
            return False  # header disagrees with its own body
        if start < 0 or start + old_count > len(result):
            return False  # hunk points outside the file
        if not all(_same_line(a, b) for a, b in zip(result[start : start + old_count], expected)):
            return False  # context does not match the file

        result[start : start + old_count] = replacement
        offset += len(replacement) - old_count

    tmp = path.with_suffix(path.suffix + ".tmp")
    try:
        with tmp.open("w", encoding="utf-8", newline="") as fh:
            fh.write("".join(result))
        tmp.replace(path)
    except OSError:
        tmp.unlink(missing_ok=True)
        return False
    return True
