"""Tests for architecture inference."""
import json
import tempfile
from pathlib import Path

from reforge_mcp.scanner.architecture import infer_architecture
from reforge_mcp.utils.state import load_state, save_state


def _scan(nodes=None, languages=None, imports=None):
    return {
        "dep_graph": {"nodes": nodes or [], "edges": [], "circular": []},
        "god_files": [],
        "summary": {
            "total_files": len(nodes or []),
            "total_functions": 0,
            "total_lines": 0,
            "languages_detected": languages or ["python"],
            "imported_modules": imports or [],
        },
    }


def test_cli_tool_detected():
    # detected from the import, not from a file called cli.py
    nodes = ["main.py", "cli.py", "commands/run.py", "utils/helpers.py"]
    result = infer_architecture(
        "/fake/repo", _scan(nodes=nodes, imports=["argparse", "os"])
    )

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


def test_a_file_called_app_is_not_a_rest_api():
    # the regression that called an Android camera app a "REST API" at 0.7:
    # _REST_MARKERS contained "app" and the repo had an app.js
    result = infer_architecture(
        "/fake/repo",
        _scan(nodes=["app.js", "protocol.js"], languages=["javascript"], imports=["fs"]),
    )

    assert result["pattern"] != "REST API"
    assert result["pattern"] == "unknown"
    assert result["confidence"] <= 0.2


def test_rest_api_needs_a_framework_import():
    result = infer_architecture(
        "/fake/repo",
        _scan(nodes=["app.py", "routes.py"], imports=["flask", "os"]),
    )

    assert result["pattern"] == "REST API"
    assert result["evidence"] == ["flask"]
