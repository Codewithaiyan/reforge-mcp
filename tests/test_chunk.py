"""Tests for the get_chunk tool."""

from pathlib import Path

import pytest

from reforge_mcp.tools.chunk import get_chunk


class TestGetChunk:

    def test_valid_slice(self, tmp_path: Path) -> None:
        f = tmp_path / "hello.py"
        f.write_text("line1\nline2\nline3\nline4\nline5\n")

        result = get_chunk(str(f), repo_root=str(tmp_path), start_line=2, end_line=4)

        assert result["source"] == "line2\nline3\nline4"
        assert result["start_line"] == 2
        assert result["end_line"] == 4
        assert result["total_lines"] == 5
        assert result["language"] == "python"
        assert "error" not in result

    def test_out_of_bounds_clamped(self, tmp_path: Path) -> None:
        f = tmp_path / "short.py"
        f.write_text("only\ntwo\n")

        result = get_chunk(str(f), repo_root=str(tmp_path), start_line=50, end_line=100)

        assert "error" not in result
        assert result["total_lines"] == 2
        assert result["start_line"] <= result["end_line"]
        assert result["start_line"] >= 1

    def test_binary_file_returns_error(self, tmp_path: Path) -> None:
        f = tmp_path / "data.bin"
        f.write_bytes(bytes(range(256)))

        result = get_chunk(str(f), repo_root=str(tmp_path))

        assert "error" in result
        assert "binary" in result["error"].lower() or "skipped" in result["error"].lower()

    def test_language_detection(self, tmp_path: Path) -> None:
        cases = {
            "app.ts": "typescript",
            "main.go": "go",
            "index.js": "javascript",
            "lib.rs": "rust",
            "query.sql": "sql",
            "unknown.xyz": "text",
        }
        for filename, expected_lang in cases.items():
            f = tmp_path / filename
            f.write_text("content\n")
            result = get_chunk(str(f), repo_root=str(tmp_path))
            assert result.get("language") == expected_lang, f"{filename}: expected {expected_lang}"
