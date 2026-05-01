"""
Reforge MCP Server.

Defines the FastMCP server instance that exposes all tools to Claude Code.
"""

import os
from typing import Any

from fastmcp import FastMCP

from .tools.git import git_commit
from .tools.scan import get_health_score, scan_repo
from .tools.chunk import get_chunk
from .tools.fix import write_fix
from .utils.state import (
    generate_changelog,
    load_state,
    save_state,
    startup_tasks,
)

mcp = FastMCP(name="reforge-mcp")


# ---------------------------------------------------------------------------
# scan
# ---------------------------------------------------------------------------


@mcp.tool()
def scan_repo_tool(
    root_path: str,
    languages: list[str] | None = None,
    include_tests: bool = True,
    max_depth: int = 10,
) -> dict[str, Any]:
    """Scan a repository and return a structured analysis report."""
    return scan_repo(root_path, languages, include_tests, max_depth)


# ---------------------------------------------------------------------------
# chunk
# ---------------------------------------------------------------------------


@mcp.tool()
def get_chunk_tool(
    file_path: str,
    repo_root: str | None = None,
    start_line: int = 1,
    end_line: int | None = None,
) -> dict[str, Any]:
    """Retrieve a line-range slice from a file."""
    return get_chunk(file_path, repo_root, start_line, end_line)


# ---------------------------------------------------------------------------
# fix
# ---------------------------------------------------------------------------


@mcp.tool()
def write_fix_tool(
    file_path: str,
    diff_str: str,
    repo_root: str | None = None,
    test_command: str | None = None,
    allowed_test_commands: list[str] | None = None,
) -> dict[str, Any]:
    """Apply a unified diff to a file; run optional tests and auto-rollback on failure."""
    return write_fix(file_path, diff_str, repo_root, test_command, allowed_test_commands)


# ---------------------------------------------------------------------------
# git
# ---------------------------------------------------------------------------


@mcp.tool()
def git_commit_tool(
    repo_path: str,
    files: list[str] | None = None,
    message: str | None = None,
    branch: str | None = None,
    create_branch: bool = False,
    confirmed: bool = False,
) -> dict[str, Any]:
    """Create an atomic git commit; enforces session budget and confirmation checkpoints."""
    return git_commit(repo_path, files, message, branch, create_branch, confirmed)


# ---------------------------------------------------------------------------
# memory — backed by reforge-state.json
# ---------------------------------------------------------------------------


@mcp.tool()
def read_memory_tool(key: str, repo_path: str) -> dict[str, Any]:
    """
    Read a value from reforge-state.json.

    Returns {key, value, found}.
    """
    state = load_state(repo_path)
    found = key in state
    return {"key": key, "value": state.get(key), "found": found}


@mcp.tool()
def write_memory_tool(
    key: str,
    value: Any,
    repo_path: str,
    ttl_seconds: int | None = None,
) -> dict[str, Any]:
    """
    Write a value to reforge-state.json atomically.

    Returns {success, key, previous_value}.
    ttl_seconds is accepted but not enforced (stored as metadata only).
    """
    state = load_state(repo_path)
    previous = state.get(key)
    state[key] = value
    try:
        save_state(repo_path, state)
        return {"success": True, "key": key, "previous_value": previous}
    except OSError as e:
        return {"success": False, "key": key, "previous_value": previous, "error": str(e)}


# ---------------------------------------------------------------------------
# health score
# ---------------------------------------------------------------------------


@mcp.tool()
def get_health_score_tool(repo_path: str) -> dict[str, Any]:
    """
    Compute a 0-100 health score from scan metrics and append to health_history.

    Scoring deductions: duplicate ratio (-30 max), dead code ratio (-30 max),
    god files (-20 max), circular deps (-20 max).
    """
    return get_health_score(repo_path, state_path=repo_path)


# ---------------------------------------------------------------------------
# changelog
# ---------------------------------------------------------------------------


@mcp.tool()
def generate_changelog_tool(repo_path: str) -> dict[str, Any]:
    """Write REFORGE_CHANGES.md from current session state."""
    state = load_state(repo_path)
    generate_changelog(repo_path, state)
    return {"success": True, "path": str(os.path.join(repo_path, "REFORGE_CHANGES.md"))}


# ---------------------------------------------------------------------------
# entry point
# ---------------------------------------------------------------------------


def main() -> None:
    repo_path = os.getcwd()
    startup_tasks(repo_path)
    mcp.run()


if __name__ == "__main__":
    main()
