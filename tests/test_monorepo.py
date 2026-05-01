"""Tests for monorepo subproject detection in scan_repo."""

from pathlib import Path

import pytest

from reforge_mcp.tools.scan import scan_repo


class TestMonorepoDetection:

    def test_python_subproject_detected(self, tmp_path: Path) -> None:
        sub = tmp_path / "services" / "auth"
        sub.mkdir(parents=True)
        (sub / "pyproject.toml").write_text("[project]\nname = 'auth'\n")
        (sub / "main.py").write_text("def login():\n    pass\n")

        result = scan_repo(str(tmp_path))

        roots = [sp["root"] for sp in result["subprojects"]]
        assert any("auth" in r for r in roots)

    def test_javascript_subproject_detected(self, tmp_path: Path) -> None:
        sub = tmp_path / "packages" / "ui"
        sub.mkdir(parents=True)
        (sub / "package.json").write_text('{"name": "ui", "scripts": {"test": "jest"}}\n')
        (sub / "index.js").write_text("function render() {}\n")

        result = scan_repo(str(tmp_path))

        found = [sp for sp in result["subprojects"] if "ui" in sp["root"]]
        assert len(found) == 1
        assert found[0]["language"] == "javascript"

    def test_subproject_test_commands(self, tmp_path: Path) -> None:
        py_sub = tmp_path / "backend"
        py_sub.mkdir()
        (py_sub / "pyproject.toml").write_text("[project]\nname = 'backend'\n")

        js_sub = tmp_path / "frontend"
        js_sub.mkdir()
        (js_sub / "package.json").write_text('{"name": "frontend"}\n')

        go_sub = tmp_path / "worker"
        go_sub.mkdir()
        (go_sub / "go.mod").write_text("module example.com/worker\n\ngo 1.21\n")

        result = scan_repo(str(tmp_path))

        by_root = {sp["root"]: sp for sp in result["subprojects"]}
        assert by_root["backend"]["test_command"] == "pytest"
        assert by_root["frontend"]["test_command"] == "npm test"
        assert by_root["worker"]["test_command"] == "go test ./..."
