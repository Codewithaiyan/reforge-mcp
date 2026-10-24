"""Tests for the risk scorer."""
import os
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


def test_inbound_refs_ignore_path_separator() -> None:
    # the same file in either form must score the same: a caller passing
    # forward slashes used to score 0 inbound refs against a native-separator
    # graph, turning a depended-on file into "safe to fix"
    graph = {
        "edges": [
            {"from": "tools" + os.sep + "a.js", "to": "web" + os.sep + "p.js"},
            {"from": "tools" + os.sep + "b.js", "to": "web" + os.sep + "p.js"},
        ],
        "circular": [],
        "nodes": [],
    }
    scan = {"dead_code": [], "god_files": [], "summary": {}}

    native = score_risk("parse", "web" + os.sep + "p.js", graph, scan)
    slashes = score_risk("parse", "web/p.js", graph, scan)

    assert native["breakdown"]["inbound_refs"] == slashes["breakdown"]["inbound_refs"]
    assert slashes["breakdown"]["inbound_refs"] == 12


def _refs_scan(references, lines=None):
    return {
        "dead_code": [],
        "god_files": [],
        "summary": {},
        "references_by_file": references,
        "lines_by_file": lines or {},
    }


def test_the_symbol_actually_changes_the_score() -> None:
    # a name nothing references used to score the same as one called from
    # three files, because `symbol` was never looked at
    scan = _refs_scan(
        {
            "web/p.js": [],
            "tools/a.js": ["parseCommand"],
            "tools/b.js": ["parseCommand"],
            "web/app.js": ["parseCommand"],
        }
    )

    used = score_risk("parseCommand", "web/p.js", _graph(), scan)
    unused = score_risk("doesNotExistAnywhere", "web/p.js", _graph(), scan)

    assert used["breakdown"]["inbound_refs"] == 18
    assert unused["breakdown"]["inbound_refs"] == 0
    assert used["score"] > unused["score"]
    assert used["basis"] == "symbol"
    assert "web/app.js" in used["referenced_by"]


def test_has_tests_needs_a_test_to_reference_the_symbol() -> None:
    # it used to be enough that some file in the repo had "test" in its name
    with_test = _refs_scan({"a.py": [], "tests/test_a.py": ["helper"]})
    without = _refs_scan({"a.py": [], "other.py": ["helper"], "tests/test_b.py": []})

    assert score_risk("helper", "a.py", _graph(), with_test)["breakdown"]["has_tests"] == 0
    assert score_risk("helper", "a.py", _graph(), without)["breakdown"]["has_tests"] == 20


def test_lines_changed_uses_the_file_not_the_repo_average() -> None:
    scan = _refs_scan({"a.py": [], "b.py": ["f"]}, lines={"a.py": 40, "b.py": 4000})
    scan["summary"] = {"total_files": 2, "total_lines": 4040}

    assert score_risk("f", "a.py", _graph(), scan)["breakdown"]["lines_changed"] == 5


def test_without_references_it_falls_back_to_file_edges_and_says_so() -> None:
    graph = _graph(edges=[{"from": "a.py", "to": "b.py"}])
    scan = {"dead_code": [], "god_files": [], "summary": {}}

    r = score_risk("anything", "b.py", graph, scan)

    assert r["basis"] == "file"
    assert r["breakdown"]["inbound_refs"] == 6
