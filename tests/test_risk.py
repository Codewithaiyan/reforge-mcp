"""Tests for the risk scorer."""
import pytest
from reforge_mcp.scanner.risk import score_risk


def _graph(edges=None, circular=None, nodes=None):
    return {
        "edges": edges or [],
        "circular": circular or [],
        "nodes": nodes or [],
    }


def _scan(dead_code=None, god_files=None, summary=None):
    return {
        "dead_code": dead_code or [],
        "god_files": god_files or [],
        "summary": summary or {"total_files": 1, "total_lines": 50},
    }


def test_isolated_symbol_scores_low():
    result = score_risk(
        symbol="helpers.do_thing",
        file="helpers.py",
        dep_graph=_graph(nodes=["test_helpers.py"]),
        scan_result=_scan(),
    )
    assert result["score"] <= 30
    assert result["recommendation"] == "safe to fix"


def test_heavily_imported_symbol_scores_high():
    edges = [{"from": f"module_{i}.py", "to": "core.py"} for i in range(6)]
    result = score_risk(
        symbol="core.run",
        file="core.py",
        dep_graph=_graph(edges=edges),
        scan_result=_scan(
            god_files=[{"file": "core.py", "lines": 500}],
        ),
    )
    assert result["score"] > 30
    assert result["breakdown"]["inbound_refs"] == 30


def test_circular_dep_increases_score():
    base = score_risk(
        symbol="a.func",
        file="a.py",
        dep_graph=_graph(),
        scan_result=_scan(),
    )
    with_circular = score_risk(
        symbol="a.func",
        file="a.py",
        dep_graph=_graph(circular=[["a.py", "b.py"]]),
        scan_result=_scan(),
    )
    assert with_circular["score"] > base["score"]
    assert with_circular["breakdown"]["is_circular"] == 25


def test_recommendation_matches_score_range():
    safe = score_risk(
        symbol="util.helper",
        file="util.py",
        dep_graph=_graph(nodes=["test_util.py"]),
        scan_result=_scan(),
    )
    assert safe["score"] <= 30
    assert safe["recommendation"] == "safe to fix"

    risky = score_risk(
        symbol="core.engine",
        file="core.py",
        dep_graph=_graph(
            edges=[{"from": f"m{i}.py", "to": "core.py"} for i in range(6)],
            circular=[["core.py", "base.py"]],
        ),
        scan_result=_scan(god_files=[{"file": "core.py", "lines": 500}]),
    )
    assert risky["score"] > 60
    assert risky["recommendation"] == "manual review recommended"
