"""Tests for architecture inference."""
import json
import tempfile
from pathlib import Path

from reforge_mcp.scanner.architecture import infer_architecture
from reforge_mcp.utils.state import load_state, save_state


def _scan(nodes=None, languages=None):
    return {
        "dep_graph": {"nodes": nodes or [], "edges": [], "circular": []},
        "god_files": [],
        "summary": {
            "total_files": len(nodes or []),
            "total_functions": 0,
            "total_lines": 0,
            "languages_detected": languages or ["python"],
        },
    }


def test_cli_tool_detected():
    nodes = ["main.py", "cli.py", "commands/run.py", "utils/helpers.py"]
    result = infer_architecture("/fake/repo", _scan(nodes=nodes))

    assert result["pattern"] == "CLI tool"
    assert result["confidence"] > 0.0
    assert result["confidence"] <= 1.0
    assert isinstance(result["entry_points"], list)
    assert isinstance(result["inferred_modules"], list)
    assert isinstance(result["hypothesis"], str)
    assert "CLI tool" in result["hypothesis"]


def test_library_pattern_detected():
    nodes = [
        "setup.py",
        "pyproject.toml",
        "src/mylib/__init__.py",
        "src/mylib/core.py",
        "src/mylib/utils.py",
        "tests/test_core.py",
    ]
    result = infer_architecture("/fake/repo", _scan(nodes=nodes))

    assert result["pattern"] == "library"
    assert result["confidence"] > 0.0
    assert "library" in result["hypothesis"]


def test_result_stored_in_state_file():
    nodes = ["main.py", "cli.py", "parser.py"]
    scan_result = _scan(nodes=nodes)

    with tempfile.TemporaryDirectory() as tmp:
        result = infer_architecture(tmp, scan_result)
        state = load_state(tmp)
        state["architecture_hypothesis"] = result
        save_state(tmp, state)

        loaded = load_state(tmp)
        stored = loaded.get("architecture_hypothesis")

        assert stored is not None
        assert stored["pattern"] == result["pattern"]
        assert stored["confidence"] == result["confidence"]
        assert stored["hypothesis"] == result["hypothesis"]
