"""
Reforge MCP Server.

Defines the FastMCP server instance that exposes all tools to Claude Code.
"""

import os
from typing import Annotated, Any

from fastmcp import FastMCP
from pydantic import Field

from . import __version__
from .scanner.architecture import infer_architecture
from .scanner.risk import score_risk
from .tool_results import (
    ArchitectureResult,
    ChangelogResult,
    ChunkResult,
    CommitResult,
    FixResult,
    HealthResult,
    ReadMemoryResult,
    RiskResult,
    ScanResult,
    WriteMemoryResult,
)
from .tools.chunk import get_chunk
from .tools.fix import write_fix
from .tools.git import git_commit
from .tools.scan import cap_report, get_health_score, scan_repo
from .utils.state import (
    generate_changelog,
    load_state,
    save_state,
    startup_tasks,
)

mcp = FastMCP(name="reforge-mcp", version=__version__)


# ---------------------------------------------------------------------------
# scan
# ---------------------------------------------------------------------------


@mcp.tool(
    name="scan_repo",
    annotations={
        "readOnlyHint": True,
        "destructiveHint": False,
        "idempotentHint": True,
        "openWorldHint": False,
    },
)
def scan_repo_tool(
    root_path: Annotated[
        str,
        Field(
            description=(
                "Existing source directory to scan; prefer an absolute path, e.g. /work/app. "
                "Relative paths resolve from the server working directory."
            )
        ),
    ],
    languages: Annotated[
        list[str] | None,
        Field(
            description=(
                "Optional case-insensitive language filter: python, javascript, typescript, "
                "go, kotlin. Default null (or []) scans all supported languages; unknown "
                "names are ignored. Example: ['python', 'typescript']."
            )
        ),
    ] = None,
    include_tests: Annotated[
        bool,
        Field(
            description=(
                "Defaults to true. Currently accepted for compatibility but does not "
                "filter test files: both true and false include them."
            )
        ),
    ] = True,
) -> ScanResult:
    """Scan source files for dead code, duplicates, oversized modules, and dependencies.
    Use when: you need repository-wide findings before planning changes.
    Don't use when: you only need source lines from a known file (use get_chunk instead).

    Returns {summary, dead_code, duplicates, god_files, dep_graph, subprojects}.
    Summary includes file/symbol/line counts, languages, parse_failures and
    unscanned-source counts. Findings carry file paths and 1-indexed lines;
    dep_graph has nodes, {from, to} edges, circular paths, external_imports,
    unresolved_relative_imports and package_imports counts. A missing/non-directory
    root or a path-validation failure
    returns error, empty findings/graph and a zero summary, without subprojects.
    Lists are capped at 200 items, duplicate groups at 50 and their locations
    at 10; shortened lists gain <key>_total, with truncated listing shortened
    top-level/graph lists. Summary counts remain complete. In a nonempty Git
    index, only tracked files are analysed; outside Git, all eligible files are.
    """
    return cap_report(scan_repo(root_path, languages, include_tests))


# ---------------------------------------------------------------------------
# chunk
# ---------------------------------------------------------------------------


@mcp.tool(
    name="get_chunk",
    annotations={
        "readOnlyHint": True,
        "destructiveHint": False,
        "idempotentHint": True,
        "openWorldHint": False,
    },
)
def get_chunk_tool(
    file_path: Annotated[
        str,
        Field(
            description=(
                "UTF-8 text file to read, e.g. /work/app/src/main.py. Relative paths "
                "resolve from the server working directory, not repo_root; the resolved "
                "file must remain inside repo_root. Binary/lock/minified files are skipped."
            )
        ),
    ],
    repo_root: Annotated[
        str | None,
        Field(
            description=(
                "Repository boundary used to validate file_path. Default null uses the "
                "server working directory; prefer an absolute path, e.g. /work/app."
            )
        ),
    ] = None,
    start_line: Annotated[
        int,
        Field(
            description=(
                "First line, 1-indexed and inclusive; default 1. Values below 1 clamp "
                "to 1; a request beyond EOF returns the last line."
            )
        ),
    ] = 1,
    end_line: Annotated[
        int | None,
        Field(
            description=(
                "Last line, 1-indexed and inclusive; default null reads through EOF. "
                "An inverted range returns the start line; values beyond EOF clamp to EOF."
            )
        ),
    ] = None,
) -> ChunkResult:
    """Read an inclusive line range from a UTF-8 file without modifying it.
    Use when: you need to inspect a finding or obtain context for a patch.
    Don't use when: you need repository-wide findings (use scan_repo instead).

    Returns {source, language, start_line, end_line, total_lines} on success,
    or {error} on failure. Source joins the selected lines with newlines;
    start_line/end_line report the clamped inclusive range. Large files can
    be read in slices; binary, lock and minified-file guards still apply.
    """
    return get_chunk(file_path, repo_root, start_line, end_line)


# ---------------------------------------------------------------------------
# fix
# ---------------------------------------------------------------------------


@mcp.tool(
    name="write_fix",
    annotations={
        "readOnlyHint": False,
        "destructiveHint": True,
        "idempotentHint": False,
        "openWorldHint": True,
    },
)
def write_fix_tool(
    file_path: Annotated[
        str,
        Field(
            description=(
                "Existing file to patch, e.g. /work/app/src/main.py; must remain within "
                "repo_root. Relative paths resolve from the server working directory."
            )
        ),
    ],
    diff_str: Annotated[
        str,
        Field(
            description=(
                "Single-file unified diff with @@ -old_start,old_count +new_start,new_count @@ "
                "hunks (1-indexed lines). Context and removed lines must match the file "
                "at the stated positions; a mismatched patch is rejected."
            )
        ),
    ],
    repo_root: Annotated[
        str | None,
        Field(
            description=(
                "Repository boundary and test-command working directory; default null "
                "uses the server working directory. Prefer an absolute path."
            )
        ),
    ] = None,
    test_command: Annotated[
        str | None,
        Field(
            description=(
                "Optional allowlisted test command, e.g. pytest or npm test. Default "
                "null skips tests. Runs without a shell from repo_root, with closed "
                "stdin and a 120-second timeout; test failure triggers file rollback."
            )
        ),
    ] = None,
    allowed_test_commands: Annotated[
        list[str] | None,
        Field(
            description=(
                "Command-prefix allowlist; a nonempty list replaces the built-in list. "
                "Default null (or []) uses built-ins such as pytest, python -m pytest, "
                "npm test and go test. Prefixes match complete shell-split tokens; "
                "command chaining remains rejected."
            )
        ),
    ] = None,
) -> FixResult:
    """Apply a unified diff to one file, optionally run tests, and attempt rollback on failure.
    Use when: you have reviewed the source and prepared a specific patch.
    Don't use when: you only need to record existing edits in Git (use git_commit instead).

    Returns {success, test_output, error, rolled_back}. Successful patches also
    return git_state (clean, modified, untracked or no_repo) and backup (null
    when Git holds the original, otherwise a retained .reforge-bak path).
    Tests are optional; success without test_command does not mean tests ran.
    No commit is created. Reapplying the same diff is not idempotent.
    """
    return write_fix(
        file_path, diff_str, repo_root, test_command, allowed_test_commands
    )


# ---------------------------------------------------------------------------
# git
# ---------------------------------------------------------------------------


@mcp.tool(
    name="git_commit",
    annotations={
        "readOnlyHint": False,
        "destructiveHint": True,
        "idempotentHint": False,
        "openWorldHint": True,
    },
)
def git_commit_tool(
    repo_path: Annotated[
        str,
        Field(
            description=(
                "Git repository directory to commit in; prefer an absolute path, e.g. /work/app."
            )
        ),
    ],
    files: Annotated[
        list[str],
        Field(
            description=(
                "Required nonempty list of files to stage, relative to repo_path or "
                "absolute within it; e.g. ['src/main.py']. Already staged changes are "
                "also included by Git's index commit; inspect the index first."
            )
        ),
    ],
    message: Annotated[
        str | None,
        Field(
            description=(
                "Commit message; null (default) or an empty string uses "
                "'refactor: automated fix #N', with N the next per-repository session count."
            )
        ),
    ] = None,
    branch: Annotated[
        str | None,
        Field(
            description=(
                "Branch name to check out before staging; default null stays on the "
                "current branch. Must exist unless create_branch is true."
            )
        ),
    ] = None,
    create_branch: Annotated[
        bool,
        Field(
            description=(
                "Default false. When true and branch is supplied, create and check out "
                "that branch; without branch this flag has no effect."
            )
        ),
    ] = False,
    confirmed: Annotated[
        bool,
        Field(
            description=(
                "Default false. Set true on retry after needs_confirmation is returned "
                "and the user approves. Does not bypass session_budget (default 20 commits); "
                "checkpoints default to every 5 commits via reforge.toml."
            )
        ),
    ] = False,
) -> CommitResult:
    """Stage the named files and create a Git commit within the session budget.
    Use when: edits have been reviewed and should be recorded in local Git history.
    Don't use when: you need to apply or test a patch first (use write_fix instead).

    Returns {success, commit_hash, branch, files_committed, error}. A checkpoint
    additionally returns needs_confirmation=true and message; retry with
    confirmed=true after approval. files_committed echoes the requested list,
    not an inventory of the commit: previously staged changes are also committed.
    Refuses an empty commit when the staged index matches HEAD; refusals do not
    consume the session budget. Initial commits with staged content are allowed.
    May create/check out a branch and invoke Git hooks; does not push.
    """
    return git_commit(repo_path, files, message, branch, create_branch, confirmed)


# ---------------------------------------------------------------------------
# memory — backed by reforge-state.json
# ---------------------------------------------------------------------------


@mcp.tool(
    name="read_memory",
    annotations={
        "readOnlyHint": True,
        "destructiveHint": False,
        "idempotentHint": True,
        "openWorldHint": False,
    },
)
def read_memory_tool(
    key: Annotated[
        str,
        Field(
            description=(
                "Top-level state key to read, e.g. architecture_hypothesis, fix_log, "
                "pending_fixes or health_history. Arbitrary strings are accepted; "
                "built-in default keys count as found even without a state file."
            )
        ),
    ],
    repo_path: Annotated[
        str,
        Field(
            description=(
                "Directory containing reforge-state.json; prefer an absolute path. "
                "Missing/unreadable/invalid JSON state is replaced by in-memory defaults."
            )
        ),
    ],
) -> ReadMemoryResult:
    """Read one top-level value from persisted repository state without writing files.
    Use when: you need a saved hypothesis, fix queue, fix log or health history.
    Don't use when: you need to replace a stored value (use write_memory instead).

    Returns {key, value, found}; an unknown key returns value=null and found=false.
    Built-in default keys may return found=true even when no state file exists.
    """
    state = load_state(repo_path)
    found = key in state
    return {"key": key, "value": state.get(key), "found": found}


@mcp.tool(
    name="write_memory",
    annotations={
        "readOnlyHint": False,
        "destructiveHint": False,
        "idempotentHint": False,
        "openWorldHint": False,
    },
)
def write_memory_tool(
    key: Annotated[
        str,
        Field(
            description=(
                "Top-level state key to create or replace; arbitrary strings are accepted, "
                "e.g. pending_fixes. This is a literal key, not a dotted path."
            )
        ),
    ],
    value: Annotated[
        Any,
        Field(
            description=(
                "Required JSON value to store: object, array, string, number, boolean or "
                "null. Replaces the entire value at key rather than merging/appending. "
                "Example for pending_fixes: ['split handlers.py']."
            )
        ),
    ],
    repo_path: Annotated[
        str,
        Field(
            description=(
                "Existing directory containing reforge-state.json; prefer an absolute "
                "path. Writes through reforge-state.tmp, replaces the state file and "
                "rotates up to five timestamped backups; other top-level keys are preserved."
            )
        ),
    ],
) -> WriteMemoryResult:
    """Create or replace one top-level value in reforge-state.json via a staged write.
    Use when: you need to persist a hypothesis, fix log or pending work across sessions.
    Don't use when: you only need to inspect a stored value (use read_memory instead).

    Returns {success, key, previous_value}, with error on an OSError while saving.
    previous_value is null for an absent key or a previously null value. Repeated
    calls can change previous_value and rotate timestamped state backups, so this
    is not idempotent even when the supplied value is unchanged.
    """
    state = load_state(repo_path)
    previous = state.get(key)
    state[key] = value
    try:
        save_state(repo_path, state)
        return {"success": True, "key": key, "previous_value": previous}
    except OSError as e:
        return {
            "success": False,
            "key": key,
            "previous_value": previous,
            "error": str(e),
        }


# ---------------------------------------------------------------------------
# architecture inference
# ---------------------------------------------------------------------------


@mcp.tool(
    name="infer_architecture",
    # This wrapper saves architecture_hypothesis: it is not a read-only scan.
    annotations={
        "readOnlyHint": False,
        "destructiveHint": False,
        "idempotentHint": False,
        "openWorldHint": False,
    },
)
def infer_architecture_tool(
    repo_path: Annotated[
        str,
        Field(
            description=(
                "Repository directory to scan and save architecture_hypothesis in "
                "reforge-state.json; prefer an absolute path. Existing state backups rotate."
            )
        ),
    ],
) -> ArchitectureResult:
    """Infer a repository's architectural pattern and save its hypothesis to reforge-state.json.
    Use when: you need an initial map of the project's likely shape and entry points.
    Don't use when: you only need the previously saved hypothesis (use read_memory instead).

    Returns {pattern, evidence, entry_points, inferred_modules, confidence,
    hypothesis}. Pattern is REST API, CLI tool, web frontend, library or unknown;
    confidence is a heuristic fraction from 0 to 1. Classification uses imported
    modules, with filename-based entry-point/module guesses. Scans without an
    external model, then writes architecture_hypothesis and rotates state backups.
    """
    scan_result = scan_repo(repo_path)
    result = infer_architecture(repo_path, scan_result)
    state = load_state(repo_path)
    state["architecture_hypothesis"] = result
    save_state(repo_path, state)
    return result


# ---------------------------------------------------------------------------
# risk scoring
# ---------------------------------------------------------------------------


@mcp.tool(
    name="score_risk",
    annotations={
        "readOnlyHint": True,
        "destructiveHint": False,
        "idempotentHint": True,
        "openWorldHint": False,
    },
)
def score_risk_tool(
    symbol: Annotated[
        str,
        Field(
            description=(
                "Exact case-sensitive unqualified symbol name, e.g. calculate_discount. "
                "Matches AST reference names across files, not fully resolved symbols; "
                "the implementation does not validate that the symbol exists."
            )
        ),
    ],
    file: Annotated[
        str,
        Field(
            description=(
                "Repository-relative file path exactly as reported by scan_repo, e.g. "
                "src/pricing.py. Use native separators or forward slashes; absolute "
                "paths do not match the scan's relative paths. Used for file size and cycles."
            )
        ),
    ],
    repo_path: Annotated[
        str,
        Field(
            description=(
                "Repository directory to rescan with per-file symbol references enabled; "
                "prefer an absolute path. No source or state files are written."
            )
        ),
    ],
) -> RiskResult:
    """Estimate the risk of changing one symbol on a heuristic 0-to-100 scale.
    Use when: you need to prioritize a specific proposed change before patching.
    Don't use when: you need an overall repository health trend (use get_health_score instead).

    Returns {score, breakdown, basis, referenced_by, recommendation}. Breakdown
    contains point contributions: inbound_refs (0-30), has_tests (0 or 20 for
    no referencing test), lines_changed (5/10/17/25 based on file length, not
    patch size), is_circular (0 or 25). basis is symbol, or file when reference
    sets are unavailable. referenced_by contains at most 10 sorted paths.
    Recommendation is safe to fix (<=30), fix with caution (<=60), or manual
    review recommended (>60); this is not a guarantee of correctness or coverage.
    """
    scan_result = scan_repo(repo_path, include_references=True)
    return score_risk(symbol, file, scan_result["dep_graph"], scan_result)


# ---------------------------------------------------------------------------
# health score
# ---------------------------------------------------------------------------


@mcp.tool(
    name="get_health_score",
    annotations={
        "readOnlyHint": False,
        "destructiveHint": False,
        "idempotentHint": False,
        "openWorldHint": False,
    },
)
def get_health_score_tool(
    repo_path: Annotated[
        str,
        Field(
            description=(
                "Existing repository directory to scan and persist health_history in "
                "reforge-state.json; prefer an absolute path, e.g. /work/app. Every call "
                "appends a UTC-timestamped entry and rotates state backups."
            )
        ),
    ],
) -> HealthResult:
    """Compute repository health from scan metrics and append a timestamped state entry.
    Use when: you need a before/after health metric and persisted history.
    Don't use when: you only need findings without writing state (use scan_repo instead).

    Returns {score, coverage, breakdown, scan_summary}, plus caveat for limited
    coverage or parse failures. score is 0-100 (higher is healthier), or null
    when no files were analysed. coverage is the analysed fraction (0-1, three
    decimal places), not test coverage. Breakdown contains dead_code_ratio,
    duplicate_ratio (fractions rounded to three decimals), god_file_count and
    circular_count. Deductions cap at 30/30/20/20 points respectively; only
    Python/JS/TS-sensitive cycles reduce health. The history entry is appended
    on every call, so repeated calls are not idempotent.
    """
    return get_health_score(repo_path, state_path=repo_path)


# ---------------------------------------------------------------------------
# changelog
# ---------------------------------------------------------------------------


@mcp.tool(
    name="generate_changelog",
    annotations={
        "readOnlyHint": False,
        "destructiveHint": False,
        "idempotentHint": False,
        "openWorldHint": False,
    },
)
def generate_changelog_tool(
    repo_path: Annotated[
        str,
        Field(
            description=(
                "Existing repository directory containing reforge-state.json and the "
                "output REFORGE_CHANGES.md; prefer an absolute path. Existing output "
                "is overwritten, and each successful call adds a fresh UTC timestamp."
            )
        ),
    ],
) -> ChangelogResult:
    """Write REFORGE_CHANGES.md from saved health history, fixes and pending work.
    Use when: you need a human-readable report of state recorded during cleanup.
    Don't use when: you only need one raw saved state value (use read_memory instead).

    Returns {success, path}, with error if the Markdown file could not be written.
    Reads health_history, fix_log and pending_fixes; it does not rescan, infer
    fixes from Git or populate those lists. Overwrites the report with a fresh
    UTC generation timestamp, so repeated calls are not idempotent.
    """
    state = load_state(repo_path)
    written = generate_changelog(repo_path, state)
    path = str(os.path.join(repo_path, "REFORGE_CHANGES.md"))
    if not written:
        return {
            "success": False,
            "path": path,
            "error": f"Could not write '{path}'",
        }
    return {"success": True, "path": path}


# ---------------------------------------------------------------------------
# entry point
# ---------------------------------------------------------------------------


def main() -> None:
    repo_path = os.getcwd()
    startup_tasks(repo_path)
    mcp.run()


if __name__ == "__main__":
    main()
