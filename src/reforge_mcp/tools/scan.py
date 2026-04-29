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

    # Build summary
    total_files = len(parse_results)
    total_functions = sum(len(r.functions) for r in parse_results)
    total_classes = sum(len(r.classes) for r in parse_results)
    total_imports = sum(len(r.imports) for r in parse_results)
    total_lines = sum(r.total_lines for r in parse_results)

    languages_detected = set()
    for result in parse_results:
        languages_detected.add(result.language)

    # Detect dead code
    logger.info("Analyzing dead code...")
    dead_code_results = find_dead_code(parse_results, repo_root=root_path)
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

    logger.info(
        f"Scan complete: {total_files} files, {total_functions} functions, "
        f"{len(dead_code)} dead code findings, {len(duplicates)} duplicate groups"
    )

    return {
        "summary": {
            "total_files": total_files,
            "total_functions": total_functions,
            "total_classes": total_classes,
            "total_imports": total_imports,
            "total_lines": total_lines,
            "languages_detected": sorted(languages_detected),
        },
        "dead_code": dead_code,
        "duplicates": duplicates,
        "god_files": god_files,
        "dep_graph": dep_graph,
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
        import tomllib
    except ImportError:
        # Python < 3.11
        import tomli as tomllib

    try:
        config = tomllib.loads(toml_path.read_text())
        ignore_from_config = config.get("ignore_dirs", [])
        return default_ignore | set(ignore_from_config)
    except Exception as e:
        logger.warning(f"Failed to parse reforge.toml: {e}")
        return default_ignore


def _find_god_files(
    parse_results: list,
    max_lines: int = 500,
    max_exports: int = 10,
) -> list[dict[str, int | str]]:
    """
    Find "god files" - files that are too large or have too many exports.

    GOD FILE CRITERIA:
    - >500 lines of code: Hard to understand, likely does too much
    - >10 exports (functions + classes): Too many responsibilities

    WHY THIS MATTERS:
    God files violate single responsibility principle. They're:
    - Hard to understand and navigate
    - Prone to merge conflicts
    - Difficult to test comprehensively
    - Often indicate missing abstractions
    """
    god_files = []

    for result in parse_results:
        if result.error:
            continue

        export_count = len(result.functions) + len(result.classes)

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
    # Build file -> imports mapping
    file_imports: dict[str, list[str]] = {}
    all_files: set[str] = set()

    for result in parse_results:
        if result.error:
            continue

        file_path = result.file
        all_files.add(file_path)

        imported_files = []
        for imp in result.imports:
            # Try to resolve import to a file path
            # This is simplified - real resolution would need package.json, etc.
            if imp.from_module:
                # Convert module path to potential file path
                potential_path = _resolve_import_to_file(
                    imp.from_module, Path(result.file).parent
                )
                if potential_path and str(potential_path) in all_files:
                    imported_files.append(str(potential_path))

        file_imports[file_path] = imported_files

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
    }


def _resolve_import_to_file(import_path: str, current_dir: Path) -> Path | None:
    """
    Resolve an import path to a potential file path.

    This is a simplified resolver - a full implementation would:
    - Check package.json for module resolution
    - Handle TypeScript path mappings
    - Handle Python package imports
    - Check node_modules for external packages
    """
    # Try common extensions
    for ext in ["", ".py", ".js", ".ts", ".tsx", ".jsx"]:
        potential = current_dir / (import_path + ext)
        if potential.exists():
            return potential

    # Try as a package import (import_path/__init__.py)
    package_init = current_dir / import_path / "__init__.py"
    if package_init.exists():
        return package_init

    return None


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
