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

    if should_skip_file(resolved):
        return {
            "error": f"File skipped: '{resolved.name}' is a binary, lock, or oversized file"
        }

    try:
        text = resolved.read_text(encoding="utf-8", errors="strict")
    except UnicodeDecodeError:
        return {"error": f"Binary or non-UTF-8 file: '{resolved.name}' cannot be read as text"}
    except OSError as e:
        return {"error": f"Cannot read '{resolved}': {e}"}

    lines = text.splitlines()
    total = len(lines)

    # Clamp range to valid bounds — never crash on out-of-range requests
    s = max(1, min(start_line, total or 1))
    e = min(end_line if end_line is not None else total, total or 1)
    e = max(e, s)

    return {
        "source": "\n".join(lines[s - 1 : e]),
        "language": _detect_language(resolved),
        "start_line": s,
        "end_line": e,
        "total_lines": total,
    }
