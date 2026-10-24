"""
Repository Scan Tool.

MCP tool that performs deep analysis of a codebase structure using AST parsing.
Detects project type, maps file relationships, identifies dead code and duplicates,
and produces a structured report of findings.

WHAT THIS TOOL DOES:
1. Walks the repository respecting ignore lists
2. Parses each source file using tree-sitter (Python, JS, TS, Go)
3. Extracts functions, classes, and imports
4. Detects dead code (unused functions)
5. Finds duplicate code (identical function bodies)
6. Identifies "god files" (>500 lines, >10 exports)
7. Builds dependency graph and detects circular dependencies

WHY AST PARSING MATTERS:
Unlike regex-based scanning, AST parsing understands code structure:
- Distinguishes function definitions from function calls
- Handles nested structures (functions in classes in modules)
- Extracts exact line numbers and body content
- Works across multiple languages with a unified interface
"""

import logging
import os
import tomllib
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from ..scanner.dead_code import find_dead_code
from ..scanner.duplicates import find_duplicates
from ..scanner.parser import parse_directory, parse_file
from ..utils.security import SecurityError, validate_path

logger = logging.getLogger(__name__)


def scan_repo(
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
        {
          "summary": {
            "total_files": int,
            "total_functions": int,
            "total_lines": int,
            "languages_detected": list[str]
          },
          "dead_code": [{"symbol": str, "file": str, "line": int}],
          "duplicates": [{"hash": str, "locations": [{"file": str, "line": int, "name": str}]}],
          "god_files": [{"file": str, "lines": int, "exports": int}],
          "dep_graph": {"nodes": list, "edges": list, "circular": list}
        }

    Why these parameters:
    - root_path is required to know what to scan
    - languages lets users focus analysis on specific stacks in monorepos
    - include_tests allows skipping test analysis for speed
    - max_depth prevents path traversal attacks and infinite loops
    """
    # SECURITY: Validate root_path is within a safe boundary
    # For scan_repo, we validate the path exists and is absolute
    # The repo_root for validation is the path itself (we're scanning that repo)
    try:
        validate_path(root_path, root_path)
    except SecurityError as e:
        logger.error(f"Security validation failed: {e}")
        return {
            "summary": {
                "total_files": 0,
                "total_functions": 0,
                "total_lines": 0,
                "languages_detected": [],
            },
            "dead_code": [],
            "duplicates": [],
            "god_files": [],
            "dep_graph": {"nodes": [], "edges": [], "circular": []},
            "error": f"Security validation failed: {e}",
        }

    root = Path(root_path)

    # Load ignore list from reforge.toml if present
    ignore_dirs = _load_ignore_dirs(root)

    # Parse all source files
    logger.info(f"Scanning repository: {root_path}")
    parse_results = parse_directory(
        directory=root,
        repo_root=root,
        ignore_dirs=ignore_dirs,
        languages=languages,
    )

    # Only analyse what the repository versions - see _tracked_files
    tracked = _tracked_files(root)
    untracked_skipped = 0
    if tracked is not None:
        kept = [r for r in parse_results if r.file in tracked]
        untracked_skipped = len(parse_results) - len(kept)
        parse_results = kept

    # Build summary
    total_files = len(parse_results)
    total_functions = sum(len(r.functions) for r in parse_results)
    total_classes = sum(len(r.classes) for r in parse_results)
    total_imports = sum(len(r.imports) for r in parse_results)
    total_lines = sum(r.total_lines for r in parse_results)

    languages_detected = set()
    for result in parse_results:
        languages_detected.add(result.language)

    unscanned = _count_unscanned_sources(root, ignore_dirs, tracked)

    # Detect dead code
    logger.info("Analyzing dead code...")
    dead_code_results = find_dead_code(parse_results)
    dead_code = [
        {
            "symbol": info.symbol,
            "file": info.file,
            "line": info.line,
        }
        for info in dead_code_results
    ]

    # Detect duplicates
    logger.info("Analyzing code duplicates...")
    duplicate_results = find_duplicates(parse_results)
    duplicates = [
        {
            "hash": group.hash,
            "locations": [
                {"file": loc.file, "line": loc.line, "name": loc.name}
                for loc in group.locations
            ],
        }
        for group in duplicate_results
    ]

    # Detect god files
    logger.info("Identifying god files...")
    god_files = _find_god_files(parse_results)

    # Build dependency graph
    logger.info("Building dependency graph...")
    dep_graph = _build_dependency_graph(parse_results)

    # Detect monorepo subprojects
    subprojects = _detect_subprojects(root)

    logger.info(
        f"Scan complete: {total_files} files, {total_functions} functions, "
        f"{len(dead_code)} dead code findings, {len(duplicates)} duplicate groups, "
        f"{len(subprojects)} subprojects"
    )

    return {
        "summary": {
            "total_files": total_files,
            "total_functions": total_functions,
            "total_classes": total_classes,
            "total_imports": total_imports,
            "total_lines": total_lines,
            "languages_detected": sorted(languages_detected),
            "unscanned_source_files": sum(unscanned.values()),
            "unscanned_by_extension": unscanned,
            "untracked_files_skipped": untracked_skipped,
        },
        "dead_code": dead_code,
        "duplicates": duplicates,
        "god_files": god_files,
        "dep_graph": dep_graph,
        "subprojects": subprojects,
    }


def _load_ignore_dirs(root: Path) -> set[str]:
    """
    Load ignore directories from reforge.toml if present.

    Falls back to default ignore list if config file doesn't exist.
    """
    default_ignore = {
        "node_modules",
        ".git",
        "__pycache__",
        ".venv",
        "venv",
        "dist",
        "build",
        ".egg-info",
        ".pytest_cache",
        ".mypy_cache",
        ".tox",
        ".coverage",
        "htmlcov",
        ".cache",
        ".next",
        "out",
        "target",
    }

    toml_path = root / "reforge.toml"
    if not toml_path.exists():
        return default_ignore

    try:
        config = tomllib.loads(toml_path.read_text())
    except (OSError, tomllib.TOMLDecodeError) as e:
        logger.warning(f"Failed to parse reforge.toml: {e}")
        return default_ignore

    # [scan] ignore — the key the shipped config file and the README both use.
    # This read "ignore_dirs" at the top level, which matched neither, so a
    # user's ignore list was silently discarded.
    return default_ignore | set(config.get("scan", {}).get("ignore", []))


_SUBPROJECT_MARKERS: dict[str, tuple[str, str]] = {
    "pyproject.toml": ("python", "pytest"),
    "setup.py": ("python", "pytest"),
    "package.json": ("javascript", "npm test"),
    "tsconfig.json": ("typescript", "npm test"),
    "go.mod": ("go", "go test ./..."),
}

_SUBPROJECT_IGNORE: set[str] = {
    "node_modules", ".git", "__pycache__", ".venv", "venv", "dist", "build",
}


def _detect_subprojects(root: Path) -> list[dict[str, str]]:
    """
    Walk subdirectories looking for project marker files and return a list of
    {root, language, test_command} dicts for each discovered subproject.

    The repo root itself is excluded — only proper subdirectories are returned.
    When multiple markers exist in the same directory, the first one wins
    (ordered by _SUBPROJECT_MARKERS insertion order).
    """
    seen: set[str] = set()
    subprojects: list[dict[str, str]] = []

    for marker, (language, test_command) in _SUBPROJECT_MARKERS.items():
        for marker_path in sorted(root.rglob(marker)):
            subdir = marker_path.parent
            if subdir == root:
                continue
            # Skip ignored directories
            rel_parts = set(subdir.relative_to(root).parts)
            if rel_parts & _SUBPROJECT_IGNORE:
                continue
            key = str(subdir)
            if key in seen:
                continue
            seen.add(key)
            subprojects.append(
                {
                    "root": str(subdir.relative_to(root)),
                    "language": language,
                    "test_command": test_command,
                }
            )

    return subprojects


_TEST_FILE_SUFFIXES = (".test.js", ".test.ts", ".spec.js", ".spec.ts", "_test.go")


def _is_test_file(file_path: str) -> bool:
    """
    Is this a test file?

    Test suites are held to different norms: thirty small test functions in one
    file is good practice, not a god object.
    """
    path = Path(file_path)
    if "tests" in path.parts or "test" in path.parts or "__tests__" in path.parts:
        return True
    if path.name.startswith("test_") or path.name.endswith("_test.py"):
        return True
    return path.name.endswith(_TEST_FILE_SUFFIXES)


def _find_god_files(
    parse_results: list,
    max_lines: int = 500,
    max_exports: int = 10,
) -> list[dict[str, int | str]]:
    """
    Find "god files" - files that are too large or have too many exports.

    GOD FILE CRITERIA:
    - >500 lines of code: Hard to understand, likely does too much
    - >10 exports (top-level functions + classes): Too many responsibilities

    Methods do not count towards the export total. A file holding one class with
    thirty methods exports one name, and counting each method made every
    class-heavy module look like a god file.

    Both thresholds are round numbers rather than discoveries - they are
    arguments so a caller can disagree, and the report carries the raw `lines`
    and `exports` so a reader can judge for themselves.

    WHY THIS MATTERS:
    God files violate single responsibility principle. They're:
    - Hard to understand and navigate
    - Prone to merge conflicts
    - Difficult to test comprehensively
    - Often indicate missing abstractions
    """
    god_files = []

    for result in parse_results:
        if result.error or _is_test_file(result.file):
            continue

        method_names = {m for cls in result.classes for m in cls.methods}
        top_level = [f for f in result.functions if f.name not in method_names]
        export_count = len(top_level) + len(result.classes)

        if result.total_lines > max_lines or export_count > max_exports:
            god_files.append(
                {
                    "file": result.file,
                    "lines": result.total_lines,
                    "exports": export_count,
                }
            )

    # Sort by line count (largest first)
    god_files.sort(key=lambda x: x["lines"], reverse=True)

    return god_files


def _build_dependency_graph(
    parse_results: list,
) -> dict[str, list]:
    """
    Build a dependency graph from import statements and detect circular dependencies.

    GRAPH STRUCTURE:
    - nodes: List of file paths
    - edges: List of {from, to} representing "from imports to"
    - circular: List of cycles detected (each cycle is a list of file paths)

    CYCLE DETECTION ALGORITHM:
    Uses DFS with recursion stack tracking:
    1. Start DFS from each unvisited node
    2. Track nodes in current recursion stack
    3. If we visit a node already in the stack, we found a cycle
    4. Record the cycle path

    WHY CIRCULAR DEPENDENCIES MATTER:
    - Makes code hard to understand (chicken-and-egg problem)
    - Can cause runtime errors (import cycles in Python/JS)
    - Indicates poor architectural boundaries
    - Makes refactoring risky (change ripples through cycle)
    """
    # Collect every parsed file before resolving anything: populating this set
    # inside the resolution loop meant an import could only ever match a file
    # seen earlier in iteration order, which is why no edge was ever found.
    all_files: set[str] = {r.file for r in parse_results if not r.error}

    file_imports: dict[str, list[str]] = {}
    external_imports = 0
    unresolved_relative = 0

    for result in parse_results:
        if result.error:
            continue

        imported_files: list[str] = []
        for imp in result.imports:
            # A bare "import sibling" carries its module in names, not
            # from_module. Skipping those missed every edge in a flat repo -
            # including the commonest Python cycle, two modules importing each
            # other by name.
            module = imp.from_module or ".".join(imp.names)
            if not module or module == "*":
                continue
            target = _resolve_import_to_file(
                module, Path(result.file).parent, all_files, result.language
            )
            if target is not None and target != result.file:
                imported_files.append(target)
            elif target is None:
                # A relative import must point inside the repo, so failing to
                # resolve one is a defect here. A bare one is a package.
                if module.startswith("."):
                    unresolved_relative += 1
                else:
                    external_imports += 1

        # several imports from one module are one edge
        file_imports[result.file] = list(dict.fromkeys(imported_files))

    # Build nodes and edges
    nodes = list(all_files)
    edges = []

    for file_path, imports in file_imports.items():
        for imp in imports:
            edges.append({"from": file_path, "to": imp})

    # Detect cycles using DFS
    circular = _detect_cycles(file_imports)

    return {
        "nodes": nodes,
        "edges": edges,
        "circular": circular,
        # Imports with no edge read as a broken resolver. These say which:
        # imports that leave the repo, versus relative ones that should have
        # resolved and did not.
        "external_imports": external_imports,
        "unresolved_relative_imports": unresolved_relative,
    }


_SOURCE_EXTENSIONS = (".py", ".js", ".jsx", ".ts", ".tsx", ".go")

# Source files no adapter can read. Counted and reported so a partial scan is
# never mistaken for a verdict on the whole repository: a seven-file result on a
# Kotlin and C++ project says nothing about the Kotlin or the C++.
#
# A bounded list on purpose. Counting every unparsed file instead would bury the
# signal under README and lockfile noise, and an extension missing from here is
# simply not mentioned.
_UNSUPPORTED_SOURCE_EXTENSIONS = frozenset(
    {
        ".c", ".cc", ".cpp", ".cxx", ".h", ".hpp", ".hh",
        ".cs", ".java", ".kt", ".kts", ".scala", ".groovy",
        ".rb", ".php", ".rs", ".swift", ".m", ".mm",
        ".dart", ".ex", ".exs", ".erl", ".hs", ".ml", ".clj",
        ".lua", ".pl", ".r", ".jl", ".zig", ".nim",
        ".sh", ".bash", ".zsh", ".ps1", ".bat",
        ".vue", ".svelte", ".sql",
    }
)


def _tracked_files(root: Path) -> set[str] | None:
    """
    Repo-relative paths that git tracks, or None if that cannot be determined.

    Analysing what the repository does not version means reporting findings in
    code the user does not own: a vendored dependency, build output, an
    installed tool's bundled scripts. An external scan of a repo carrying
    `.github/skills/` reported dead code exclusively in those files.

    None - a non-git directory, or a repo with nothing added yet - scans
    everything, so the tool still works outside git.
    """
    try:
        from git import GitCommandError, InvalidGitRepositoryError, NoSuchPathError, Repo

        repo = Repo(root, search_parent_directories=False)
        out = repo.git.ls_files()
    except (InvalidGitRepositoryError, NoSuchPathError, GitCommandError, OSError):
        return None
    except ImportError:
        return None

    # git reports "/" on every platform; parse results use the native separator
    # shortcut: a path containing a newline is dropped, which git quotes anyway
    names = {name.replace("/", os.sep) for name in out.splitlines() if name}
    return names or None


def _count_unscanned_sources(
    root: Path, ignore_dirs: set[str], tracked: set[str] | None = None
) -> dict[str, int]:
    """Count source files, by extension, that no adapter could parse."""
    counts: dict[str, int] = {}
    for path in root.rglob("*"):
        if not path.is_file():
            continue
        suffix = path.suffix.lower()
        if suffix not in _UNSUPPORTED_SOURCE_EXTENSIONS:
            continue
        try:
            parts = path.relative_to(root).parts
        except ValueError:
            continue
        if any(part in ignore_dirs for part in parts):
            continue
        if tracked is not None and str(path.relative_to(root)) not in tracked:
            continue
        counts[suffix] = counts.get(suffix, 0) + 1
    return dict(sorted(counts.items(), key=lambda kv: -kv[1]))


def _resolve_import_to_file(
    import_path: str, current_dir: Path, known_files: set[str], language: str = ""
) -> str | None:
    """
    Resolve an import to one of the files we parsed, or None for an external one.

    Matches against the parsed file set rather than touching the filesystem, so
    resolution does not depend on the process working directory.

    shortcut: no package.json "main", no tsconfig path mappings, and no
    resolution of absolute intra-repo package imports ("from mypkg.a import b"
    where mypkg lives under src/) - upgrade when a repo that needs one shows up.
    """
    if import_path.startswith("."):
        if "/" in import_path:
            # JS/TS path: "./utils", "../lib/thing"
            base = Path(os.path.normpath(current_dir / import_path))
        else:
            # Python relative: "." is this package, ".." the one above it
            dots = len(import_path) - len(import_path.lstrip("."))
            base = current_dir
            for _ in range(dots - 1):
                base = base.parent
            remainder = import_path[dots:]
            if remainder:
                base = base.joinpath(*remainder.split("."))
    else:
        # In JS/TS a bare specifier is a node_modules package, never a sibling
        # file, so require("express") must not resolve to a local express.js.
        if language in ("javascript", "typescript"):
            return None
        # Inside a package, a bare import is absolute: "from git import Repo"
        # is the installed GitPython, not the tools/git.py next door.
        if str(current_dir / "__init__.py") in known_files:
            return None
        base = current_dir.joinpath(*import_path.split("."))

    # str(base) first: a browser ES module must name its extension
    # ("./protocol.js"), so base is already the whole path.
    candidates = [str(base)]
    candidates += [str(base) + ext for ext in _SOURCE_EXTENSIONS]
    candidates += [
        str(base / "__init__.py"),
        str(base / "index.js"),
        str(base / "index.ts"),
    ]
    for candidate in candidates:
        if candidate in known_files:
            return candidate

    return None


def get_health_score(
    root_path: str,
    state_path: str | None = None,
) -> dict[str, Any]:
    """
    Compute a 0-100 health score from scan metrics and optionally persist to state.

    Scoring (penalties are capped per category):
    - duplicate_ratio  → up to -30
    - dead_code_ratio  → up to -30
    - god_file_count   → up to -20 (5 pts each)
    - circular_count   → up to -20 (10 pts each)
    """
    scan = scan_repo(root_path)

    summary = scan.get("summary", {})
    total_functions = max(summary.get("total_functions", 0), 1)
    total_files = max(summary.get("total_files", 0), 1)

    dead_code = scan.get("dead_code", [])
    duplicates = scan.get("duplicates", [])
    god_files = scan.get("god_files", [])
    circular = scan.get("dep_graph", {}).get("circular", [])

    dead_code_ratio = len(dead_code) / total_functions
    dup_symbols = sum(len(g.get("locations", [])) for g in duplicates)
    duplicate_ratio = dup_symbols / total_functions
    god_file_count = len(god_files)
    circular_count = len(circular)

    score = 100.0
    score -= min(30.0, duplicate_ratio * 100)
    score -= min(30.0, dead_code_ratio * 100)
    score -= min(20.0, god_file_count * 5.0)
    score -= min(20.0, circular_count * 10.0)
    score = max(0.0, round(score, 1))

    entry: dict[str, Any] = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "score": score,
        "dead_code_ratio": round(dead_code_ratio, 3),
        "duplicate_ratio": round(duplicate_ratio, 3),
        "god_file_count": god_file_count,
        "circular_count": circular_count,
        "total_files": total_files,
        "total_functions": total_functions,
    }

    if state_path is not None:
        from ..utils.state import load_state, save_state

        state = load_state(state_path)
        state["health_history"] = state.get("health_history", []) + [entry]
        save_state(state_path, state)

    return {
        "score": score,
        "breakdown": {
            "dead_code_ratio": entry["dead_code_ratio"],
            "duplicate_ratio": entry["duplicate_ratio"],
            "god_file_count": god_file_count,
            "circular_count": circular_count,
        },
        "scan_summary": summary,
    }


def _detect_cycles(
    graph: dict[str, list[str]],
) -> list[list[str]]:
    """
    Detect circular dependencies in a directed graph using DFS.

    ALGORITHM:
    1. Maintain three states for each node:
       - unvisited: not yet processed
       - visiting: currently in recursion stack
       - visited: fully processed
    2. For each unvisited node, start DFS
    3. If we encounter a "visiting" node, we found a cycle
    4. Record the cycle path from the recursion stack

    Returns:
        List of cycles, where each cycle is a list of file paths
    """
    UNVISITED = 0
    VISITING = 1
    VISITED = 2

    state: dict[str, int] = {node: UNVISITED for node in graph}
    cycles: list[list[str]] = []
    path: list[str] = []

    def dfs(node: str) -> None:
        if state[node] == VISITED:
            return

        if state[node] == VISITING:
            # Found a cycle - extract it from the path
            try:
                cycle_start = path.index(node)
                cycle = path[cycle_start:] + [node]
                cycles.append(cycle)
            except ValueError:
                pass
            return

        state[node] = VISITING
        path.append(node)

        for neighbor in graph.get(node, []):
            if neighbor in state:
                dfs(neighbor)

        path.pop()
        state[node] = VISITED

    for node in graph:
        if state[node] == UNVISITED:
            dfs(node)

    return cycles
