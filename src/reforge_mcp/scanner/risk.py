"""Risk scorer for proposed fixes."""

from __future__ import annotations

import os


def _looks_like_test(path: str) -> str:
    """
    Whether a path is a test file, by the conventions runners use.

    Deliberately strict. A wrong "yes" lowers the risk score and tells the
    caller a change is safer than it is, so an unconventionally named test -
    MyCam's webtest/golden_check.js - is missed and the score errs high.

    shortcut: conventional names and directories only, upgrade if a real repo
    keeps its tests somewhere this does not reach.
    """
    norm = path.replace(os.sep, "/").lower()
    name = norm.rsplit("/", 1)[-1]
    return (
        name.startswith("test_")
        or name.startswith("test.")
        or "_test." in name
        or ".test." in name
        or ".spec." in name
        or "_spec." in name
        or any(part in ("test", "tests", "spec", "specs") for part in norm.split("/"))
    )


def _norm(path: str) -> str:
    """
    Compare paths regardless of separator.

    A caller passing "pc/companion/web/protocol.js" scored 0 inbound refs while
    the same file as the scan reports it, with native separators, scored 12.
    """
    return path.replace(os.sep, "/")


def score_risk(
    symbol: str,
    file: str,
    dep_graph: dict,
    scan_result: dict,
) -> dict:
    """
    Score a proposed fix from 0 (safe) to 100 (very risky).

    Factors
    -------
    inbound_refs  – other files that reference this symbol  (+30 max)
    has_tests     – a test file references this symbol       (+20 max)
    lines_changed – lines in the symbol's file               (+25 max)
    is_circular   – symbol's file is in a circular dep cycle (+25 max)

    `inbound_refs` and `has_tests` need `references_by_file`, which
    `scan_repo(..., include_references=True)` provides. Without it this falls
    back to counting imports of the whole file, and `basis` in the result says
    which was used - the file-level number is coarser and can call a widely
    used symbol safe.
    """
    edges: list[dict] = dep_graph.get("edges", [])
    circular: list[list[str]] = dep_graph.get("circular", [])

    target = _norm(file)
    references: dict = scan_result.get("references_by_file", {})

    # --- inbound_refs (+30 max) -------------------------------------------
    # Previously this counted imports of the file and ignored `symbol`
    # entirely, so a name that does not exist scored the same as a parser
    # called from nine places.
    if references:
        basis = "symbol"
        referring = [
            path
            for path, names in references.items()
            if _norm(path) != target and symbol in names
        ]
        inbound = len(referring)
    else:
        basis = "file"
        referring = [
            e.get("from", "") for e in edges if _norm(e.get("to", "")) == target
        ]
        inbound = len(referring)
    inbound_score = min(30, inbound * 6)

    # --- has_tests (+20 max) -------------------------------------------------
    # This used to ask whether ANY file in the repo had "test" in its name,
    # while its docstring claimed it checked references to the symbol. A
    # protocol parser was credited with coverage because an unrelated
    # webtest_server.py existed.
    covered = any(_looks_like_test(path) for path in referring)
    test_score = 0 if covered else 20

    # --- lines_changed (+25 max) --------------------------------------------
    god_files: list[dict] = scan_result.get("god_files", [])
    lines_by_file: dict = scan_result.get("lines_by_file", {})
    exact = next(
        (n for path, n in lines_by_file.items() if _norm(path) == target), None
    )
    god_entry = next(
        (g for g in god_files if _norm(g.get("file", "")) == target), None
    )
    if exact is not None:
        file_lines = exact
    elif god_entry:
        file_lines = god_entry.get("lines", 0)
    else:
        # the repo average: only reached when no per-file count was supplied
        # fall back to summary average
        summary = scan_result.get("summary", {})
        total_files = summary.get("total_files", 1) or 1
        total_lines = summary.get("total_lines", 0)
        file_lines = total_lines / total_files

    # bucket: ≤50 → 5, ≤150 → 10, ≤300 → 17, >300 → 25
    if file_lines <= 50:
        lines_score = 5
    elif file_lines <= 150:
        lines_score = 10
    elif file_lines <= 300:
        lines_score = 17
    else:
        lines_score = 25

    # --- is_circular (+25 max) ----------------------------------------------
    flat_cycles = {f for cycle in circular for f in cycle}
    circular_score = 25 if target in {_norm(f) for f in flat_cycles} else 0

    # --- total ---------------------------------------------------------------
    total = inbound_score + test_score + lines_score + circular_score

    if total <= 30:
        recommendation = "safe to fix"
    elif total <= 60:
        recommendation = "fix with caution"
    else:
        recommendation = "manual review recommended"

    return {
        "score": total,
        "breakdown": {
            "inbound_refs": inbound_score,
            "has_tests": test_score,
            "lines_changed": lines_score,
            "is_circular": circular_score,
        },
        "basis": basis,
        "referenced_by": sorted(referring)[:10],
        "recommendation": recommendation,
    }
