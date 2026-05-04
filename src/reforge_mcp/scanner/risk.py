"""Risk scorer for proposed fixes."""

from __future__ import annotations


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
    inbound_refs  – how many other files import this file  (+30 max)
    has_tests     – whether a test file references this symbol (+20 max)
    lines_changed – estimated lines in the symbol's file     (+25 max)
    is_circular   – symbol's file is in a circular dep cycle (+25 max)
    """
    edges: list[dict] = dep_graph.get("edges", [])
    circular: list[list[str]] = dep_graph.get("circular", [])

    # --- inbound_refs (+30 max) -------------------------------------------
    inbound = sum(1 for e in edges if e.get("to") == file)
    inbound_score = min(30, inbound * 6)

    # --- has_tests (+20 max) -------------------------------------------------
    # no tests found → full penalty
    dead_code: list[dict] = scan_result.get("dead_code", [])
    symbol_lower = symbol.lower()
    # check dead_code list: if symbol appears there, it has no callers → no tests
    in_dead_code = any(
        d.get("symbol", "").lower() == symbol_lower for d in dead_code
    )
    # also look for a test file among scanned nodes
    nodes: list[str] = dep_graph.get("nodes", [])
    has_test_file = any(
        "test" in n.lower() and Path_stem(n) != Path_stem(file) for n in nodes
    )
    test_score = 0 if (has_test_file and not in_dead_code) else 20

    # --- lines_changed (+25 max) --------------------------------------------
    god_files: list[dict] = scan_result.get("god_files", [])
    god_entry = next((g for g in god_files if g.get("file") == file), None)
    if god_entry:
        file_lines = god_entry.get("lines", 0)
    else:
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
    circular_score = 25 if file in flat_cycles else 0

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
        "recommendation": recommendation,
    }


def Path_stem(path: str) -> str:
    """Return the stem (filename without extension) of a path string."""
    import os
    return os.path.splitext(os.path.basename(path))[0]
