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

class TestGetChunkOnDifficultFiles:
    """All of this was failing or wrong before 0.2.8."""

    def _numbered(self, tmp_path: Path, count: int) -> Path:
        f = tmp_path / "numbered.py"
        f.write_text("".join(f"line {i}\n" for i in range(1, count + 1)), encoding="utf-8")
        return f

    def test_a_file_over_the_size_limit_can_still_be_chunked(self, tmp_path: Path) -> None:
        # reading a slice of a large file is the whole point of this tool, and
        # should_skip_file's 500 KB default refused exactly those files
        f = tmp_path / "big.py"
        f.write_text("".join(f"x = {i}\n" for i in range(90000)), encoding="utf-8")
        assert f.stat().st_size > 500 * 1024

        result = get_chunk(str(f), repo_root=str(tmp_path), start_line=5, end_line=7)

        assert "error" not in result, result.get("error")
        assert result["source"] == "x = 4\nx = 5\nx = 6"

    def test_a_minified_file_is_still_refused(self, tmp_path: Path) -> None:
        # the size rule was bypassed, the generated-file rules were not
        f = tmp_path / "bundle.min.js"
        f.write_text("var a=1;\n", encoding="utf-8")

        assert "error" in get_chunk(str(f), repo_root=str(tmp_path))

    def test_a_missing_file_says_so(self, tmp_path: Path) -> None:
        # it used to report a missing file as "binary, lock, or oversized"
        result = get_chunk(str(tmp_path / "nope.py"), repo_root=str(tmp_path))

        assert "error" in result
        assert "Not a file" in result["error"]

    def test_an_inverted_range_returns_the_line_at_start(self, tmp_path: Path) -> None:
        f = self._numbered(tmp_path, 100)

        result = get_chunk(str(f), repo_root=str(tmp_path), start_line=50, end_line=10)

        assert result["source"] == "line 50"
        assert (result["start_line"], result["end_line"]) == (50, 50)

    def test_a_request_past_the_end_returns_the_last_line(self, tmp_path: Path) -> None:
        f = self._numbered(tmp_path, 100)

        result = get_chunk(str(f), repo_root=str(tmp_path), start_line=500, end_line=600)

        assert result["source"] == "line 100"
        assert (result["start_line"], result["end_line"]) == (100, 100)
        assert result["total_lines"] == 100

    def test_a_crlf_file_yields_no_stray_carriage_returns(self, tmp_path: Path) -> None:
        f = tmp_path / "crlf.py"
        f.write_bytes(b"alpha\r\nbeta\r\ngamma\r\n")

        result = get_chunk(str(f), repo_root=str(tmp_path))

        assert result["source"] == "alpha\nbeta\ngamma"
        assert result["total_lines"] == 3

    def test_the_whole_file_is_returned_by_default(self, tmp_path: Path) -> None:
        f = self._numbered(tmp_path, 4)

        result = get_chunk(str(f), repo_root=str(tmp_path))

        assert result["source"] == "line 1\nline 2\nline 3\nline 4"
        assert (result["start_line"], result["end_line"]) == (1, 4)
