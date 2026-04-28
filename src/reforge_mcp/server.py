"""
Reforge MCP Server.

Defines the FastMCP server instance that exposes all tools to Claude Code.
When fully built, will register scan, chunk, fix, and git tools as MCP endpoints
and handle the communication protocol between Claude Code and the cleanup logic.
"""

from fastmcp import FastMCP
from typing import Any

from .tools.scan import scan_repo
from .tools.chunk import get_chunk
from .tools.fix import write_fix
from .tools.git import git_commit

# Create the FastMCP server instance
mcp = FastMCP(
    name="reforge-mcp",
)


@mcp.tool()
def scan_repo_tool(
    root_path: str,
    languages: list[str] | None = None,
    include_tests: bool = True,
    max_depth: int = 10,
) -> dict[str, Any]:
    """
    Scan a repository and return a structured analysis report.

    Parameter contract:
    - root_path: Absolute path to the repository root to scan.
    - languages: Optional list of languages to analyze (e.g., ["python", "typescript"]).
                 If None, auto-detect from package.json, pyproject.toml, go.mod, etc.
    - include_tests: Whether to include test files in the scan and report coverage gaps.
    - max_depth: Maximum directory depth to traverse (prevents infinite loops in symlinked repos).

    Returns:
        A scan report dictionary containing:
        - project_type: Detected project type (e.g., "python-fastapi", "node-express")
        - files: List of file paths analyzed
        - modules: Dependency graph of imports between files
        - test_coverage: Percentage of code covered by tests
        - issues: List of detected problems (dead code, duplicates, naming issues)
        - summary: Human-readable summary of findings
    """
    return scan_repo(root_path, languages, include_tests, max_depth)


@mcp.tool()
def get_chunk_tool(
    file_path: str,
    chunk_id: str | None = None,
    strategy: str = "semantic",
    max_tokens: int = 2000,
) -> dict[str, Any]:
    """
    Retrieve a specific chunk from a file or generate chunks on demand.

    Parameter contract:
    - file_path: Absolute path to the file to chunk.
    - chunk_id: Optional identifier for a specific chunk. If None, returns all chunks.
                Format: "<file_path>:<line_start>-<line_end>" or a semantic label.
    - strategy: Chunking strategy — "semantic" (AST-based), "line" (fixed lines),
                or "token" (fixed token count). Default: "semantic".
    - max_tokens: Maximum tokens per chunk. Adjusts chunk boundaries to fit.

    Returns:
        A chunk or list of chunks containing:
        - chunk_id: Unique identifier for this chunk
        - content: The actual code content
        - start_line: Starting line number (1-indexed)
        - end_line: Ending line number (inclusive)
        - symbol_name: If semantic, the function/class name this chunk represents
        - symbol_type: Type of symbol ("function", "class", "method", "module")
    """
    return get_chunk(file_path, chunk_id, strategy, max_tokens)


@mcp.tool()
def write_fix_tool(
    file_path: str,
    fix_type: str,
    chunk_id: str | None = None,
    description: str | None = None,
    run_tests: bool = True,
) -> dict[str, Any]:
    """
    Apply a refactoring fix to a file or chunk.

    Parameter contract:
    - file_path: Absolute path to the file to modify.
    - fix_type: Type of fix to apply. One of:
                - "remove_dead": Remove unused code
                - "consolidate_duplicate": Merge duplicate implementations
                - "rename": Fix naming convention violations
                - "extract_method": Pull out a method for better cohesion
                - "inline": Remove unnecessary abstraction
    - chunk_id: Optional chunk identifier to limit the fix scope.
                If None, applies to the entire file.
    - description: Optional human-readable description of what this fix does.
                   Used for commit messages and audit trails.
    - run_tests: Whether to run tests after applying the fix. Default: True.

    Returns:
        A fix result dictionary containing:
        - success: Boolean indicating if the fix was applied
        - diff: Unified diff showing what changed
        - test_result: If run_tests=True, the test output (pass/fail, errors)
        - backup_path: Path to the backup file created before modification
        - warnings: Any warnings generated during the fix
    """
    return write_fix(file_path, fix_type, chunk_id, description, run_tests)


@mcp.tool()
def git_commit_tool(
    repo_path: str,
    files: list[str] | None = None,
    message: str | None = None,
    branch: str | None = None,
    create_branch: bool = False,
) -> dict[str, Any]:
    """
    Create a git commit with the specified files.

    Parameter contract:
    - repo_path: Absolute path to the git repository root.
    - files: List of file paths to stage and commit. If None, stages all changes.
             Paths should be relative to repo_path.
    - message: Commit message. If None, auto-generates from file changes.
               Should follow conventional commits format: "type: description".
    - branch: Branch to operate on. If None, uses current branch.
    - create_branch: If True, creates a new branch from the current HEAD.
                     Requires branch parameter to specify the new branch name.

    Returns:
        A git result dictionary containing:
        - success: Boolean indicating if the commit succeeded
        - commit_hash: The SHA of the created commit (if successful)
        - branch: The branch the commit was made to
        - files_committed: List of files that were committed
        - stdout: Git command output
        - stderr: Git command errors or warnings
    """
    return git_commit(repo_path, files, message, branch, create_branch)


@mcp.tool()
def read_memory_tool(
    key: str,
) -> dict[str, Any]:
    """
    Read a value from the persistent memory store.

    Parameter contract:
    - key: The memory key to retrieve. Keys are strings that identify
           stored values (e.g., "last_scan_path", "pending_fixes").

    Returns:
        A memory result dictionary containing:
        - key: The key that was requested
        - value: The stored value (any JSON-serializable type)
        - found: Boolean indicating if the key existed
        - metadata: Optional metadata (created_at, updated_at, version)

    Why this tool:
    - Enables stateful operations across MCP sessions
    - Stores intermediate scan results for large repos
    - Remembers user preferences and pending operations
    """
    # TODO: Implement persistent memory store (SQLite or file-based)
    return {
        "key": key,
        "value": None,
        "found": False,
        "metadata": {},
        "note": "Memory store not yet implemented — placeholder response",
    }


@mcp.tool()
def write_memory_tool(
    key: str,
    value: Any,
    ttl_seconds: int | None = None,
) -> dict[str, Any]:
    """
    Write a value to the persistent memory store.

    Parameter contract:
    - key: The memory key to store. Must be a string.
           Use snake_case convention (e.g., "last_scan_result").
    - value: The value to store. Must be JSON-serializable.
             Can be any type: str, int, float, bool, list, dict, None.
    - ttl_seconds: Optional time-to-live in seconds. If set, the value
                   will be automatically deleted after this duration.
                   Useful for temporary caches and session data.

    Returns:
        A write result dictionary containing:
        - success: Boolean indicating if the write succeeded
        - key: The key that was written
        - previous_value: The previous value if key existed (for audit)
        - expires_at: ISO timestamp when the value will expire (if ttl_seconds set)

    Why this tool:
    - Persists state across MCP sessions
    - Caches expensive scan results
    - Stores user preferences and configuration
    - Enables undo/redo by storing previous states
    """
    # TODO: Implement persistent memory store with TTL support
    return {
        "success": True,
        "key": key,
        "previous_value": None,
        "expires_at": None,
        "note": "Memory store not yet implemented — placeholder response",
    }


@mcp.tool()
def get_health_score_tool(
    repo_path: str | None = None,
) -> dict[str, Any]:
    """
    Calculate and return a health score for the repository or server.

    Parameter contract:
    - repo_path: Optional absolute path to a repository to scan.
                 If None, returns server health only.
                 If provided, includes repository health metrics.

    Returns:
        A health report dictionary containing:
        - overall_score: 0-100 score representing overall health
        - server_health: Server-specific metrics (uptime, memory, active connections)
        - repo_health: Repository-specific metrics (if repo_path provided):
            - test_coverage: Percentage of code covered by tests
            - dead_code_ratio: Percentage of unused code
            - duplicate_ratio: Percentage of duplicated code
            - naming_violations: Count of naming convention issues
            - complexity_score: Average cyclomatic complexity
        - recommendations: List of prioritized improvement suggestions

    Why this tool:
    - Quick health check before starting refactoring work
    - Tracks progress as reforge-mcp cleans up the repository
    - Identifies the biggest opportunities for improvement
    - Provides before/after metrics to show impact
    """
    # TODO: Implement health scoring using scanner/ metrics
    result: dict[str, Any] = {
        "overall_score": 50,
        "server_health": {
            "status": "healthy",
            "uptime_seconds": 0,
            "memory_mb": 0,
            "active_connections": 0,
        },
        "recommendations": [
            "Run scan_repo to get detailed repository health metrics",
            "Health scoring not yet fully implemented — placeholder response",
        ],
    }
    if repo_path:
        result["repo_health"] = {
            "test_coverage": 0.0,
            "dead_code_ratio": 0.0,
            "duplicate_ratio": 0.0,
            "naming_violations": 0,
            "complexity_score": 0.0,
        }
    return result


def main() -> None:
    """
    Entry point for the reforge-mcp server.

    Runs the FastMCP server using stdio transport by default.
    Can be configured via environment variables or command-line args
    to use SSE or WebSocket transport for remote connections.
    """
    mcp.run()


if __name__ == "__main__":
    main()
