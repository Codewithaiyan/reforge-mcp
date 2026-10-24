"""
Code Chunking Tool.

MCP tool that retrieves a line-range slice from a file.
"""

import os
from pathlib import Path
from typing import Any

from ..utils.security import SecurityError, should_skip_file, validate_path

_LANGUAGE_MAP: dict[str, str] = {
    ".py": "python",
    ".js": "javascript",
    ".ts": "typescript",
    ".tsx": "typescript",
    ".jsx": "javascript",
    ".rs": "rust",
    ".go": "go",
    ".java": "java",
    ".c": "c",
    ".cpp": "cpp",
    ".h": "c",
    ".hpp": "cpp",
    ".rb": "ruby",
    ".php": "php",
    ".sh": "bash",
    ".bash": "bash",
    ".zsh": "bash",
    ".yaml": "yaml",
    ".yml": "yaml",
    ".json": "json",
    ".toml": "toml",
    ".md": "markdown",
    ".html": "html",
    ".css": "css",
    ".sql": "sql",
}


# the characters a line terminator can be made of, however the file ends
_EOL = chr(13) + chr(10)


def _detect_language(path: Path) -> str:
    return _LANGUAGE_MAP.get(path.suffix.lower(), "text")


def get_chunk(
    file_path: str,
    repo_root: str | None = None,
    start_line: int = 1,
    end_line: int | None = None,
) -> dict[str, Any]:
    """
    Retrieve a line-range slice from a file.

    Args:
        file_path: Path to the file (absolute or relative to repo_root).
        repo_root: Repository root for path validation. Defaults to cwd.
        start_line: First line to return, 1-indexed. Clamped to [1, total].
        end_line: Last line to return, inclusive. Defaults to end of file.

    Returns:
        {source, language, start_line, end_line, total_lines} on success,
        {error} on failure.
    """
    if repo_root is None:
        repo_root = os.getcwd()

    try:
        resolved = validate_path(file_path, repo_root)
    except SecurityError as e:
        return {"error": str(e)}

    if not resolved.is_file():
        return {"error": f"Not a file: '{resolved}'"}

    # The size rule is bypassed on purpose. Reading a slice of a large
    # file is what this tool is for, and the 500 KB default refused the
    # very files worth chunking. The binary, lock and minified rules
    # still apply, and the read below is streamed, so memory is bounded
    # by the requested slice rather than the file.
    if should_skip_file(resolved, max_file_size_kb=2**40):
        return {
            "error": f"File skipped: '{resolved.name}' is a binary, lock, or generated file"
        }

    first = max(1, start_line)
    last = end_line if end_line is not None else None
    if last is not None and last < first:
        last = first  # an inverted range means the single line at `first`

    lines: list[str] = []
    tail = ""
    total = 0
    try:
        with resolved.open(encoding="utf-8", errors="strict") as fh:
            for number, line in enumerate(fh, start=1):
                total = number
                tail = line.rstrip(_EOL)
                if number >= first and (last is None or number <= last):
                    lines.append(tail)
    except UnicodeDecodeError:
        return {"error": f"Binary or non-UTF-8 file: '{resolved.name}' cannot be read as text"}
    except OSError as e:
        return {"error": f"Cannot read '{resolved}': {e}"}

    # Clamp the reported range to valid bounds; never crash on an
    # out-of-range request. `lines` already holds only what was asked
    # for, so a request past the end yields the tail, not invented text.
    s = max(1, min(start_line, total or 1))
    e = min(end_line if end_line is not None else total, total or 1)
    e = max(e, s)
    if not lines and total:
        # the request started past the end: hand back the last line, which
        # the stream above kept, rather than re-reading the file
        s = e = total
        lines = [tail]

    return {
        "source": "\n".join(lines),
        "language": _detect_language(resolved),
        "start_line": s,
        "end_line": e,
        "total_lines": total,
    }
