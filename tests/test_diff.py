"""Tests for the unified diff applier."""

from pathlib import Path

from reforge_mcp.utils.diff import apply_diff


class TestApplyDiff:

    def test_applies_matching_hunk(self, tmp_path: Path) -> None:
        f = tmp_path / "code.py"
        f.write_text("a\nb\nc\n")
        diff = "@@ -2,1 +2,1 @@\n-b\n+B\n"

        assert apply_diff(f, diff) is True
        assert f.read_text() == "a\nB\nc\n"

    def test_applies_multiple_hunks_with_offset(self, tmp_path: Path) -> None:
        f = tmp_path / "code.py"
        f.write_text("a\nb\nc\nd\n")
        # first hunk grows the file by one line; the second must still line up
        diff = "@@ -1,1 +1,2 @@\n-a\n+a1\n+a2\n@@ -4,1 +5,1 @@\n-d\n+D\n"

        assert apply_diff(f, diff) is True
        assert f.read_text() == "a1\na2\nb\nc\nD\n"

    def test_rejects_hunk_past_end_of_file(self, tmp_path: Path) -> None:
        f = tmp_path / "code.py"
        f.write_text("a\nb\nc\n")
        diff = "@@ -40,3 +40,1 @@\n-x\n-y\n-z\n+REPLACED\n"

        assert apply_diff(f, diff) is False
        assert f.read_text() == "a\nb\nc\n"

    def test_rejects_mismatched_context(self, tmp_path: Path) -> None:
        f = tmp_path / "code.py"
        f.write_text("a\nb\nc\n")
        diff = "@@ -2,1 +2,1 @@\n-NOT_B\n+B\n"

        assert apply_diff(f, diff) is False
        assert f.read_text() == "a\nb\nc\n"

    def test_rejects_header_disagreeing_with_body(self, tmp_path: Path) -> None:
        f = tmp_path / "code.py"
        f.write_text("a\nb\nc\n")
        diff = "@@ -1,3 +1,1 @@\n-a\n+A\n"

        assert apply_diff(f, diff) is False
        assert f.read_text() == "a\nb\nc\n"

    def test_later_bad_hunk_leaves_file_untouched(self, tmp_path: Path) -> None:
        f = tmp_path / "code.py"
        f.write_text("a\nb\nc\n")
        # first hunk is valid, second is not — neither may be written
        diff = "@@ -1,1 +1,1 @@\n-a\n+A\n@@ -3,1 +3,1 @@\n-NOT_C\n+C\n"

        assert apply_diff(f, diff) is False
        assert f.read_text() == "a\nb\nc\n"

    def test_insertion_hunk_at_start(self, tmp_path: Path) -> None:
        f = tmp_path / "code.py"
        f.write_text("a\nb\n")
        diff = "@@ -0,0 +1,1 @@\n+header\n"

        assert apply_diff(f, diff) is True
        assert f.read_text() == "header\na\nb\n"

    def test_insertion_hunk_after_a_line(self, tmp_path: Path) -> None:
        f = tmp_path / "code.py"
        f.write_text("a\nb\n")
        diff = "@@ -1,0 +2,1 @@\n+middle\n"

        assert apply_diff(f, diff) is True
        assert f.read_text() == "a\nmiddle\nb\n"

    def test_crlf_file_accepts_lf_diff(self, tmp_path: Path) -> None:
        f = tmp_path / "code.py"
        f.write_bytes(b"a\r\nb\r\n")
        diff = "@@ -1,1 +1,1 @@\n-a\n+A\n"

        assert apply_diff(f, diff) is True
        assert "A" in f.read_text()

    def test_no_hunks_is_rejected(self, tmp_path: Path) -> None:
        f = tmp_path / "code.py"
        f.write_text("a\n")

        assert apply_diff(f, "this is not a diff") is False
        assert f.read_text() == "a\n"
