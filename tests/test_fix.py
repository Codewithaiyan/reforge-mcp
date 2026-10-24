"""Tests for the write_fix tool."""

from pathlib import Path

from reforge_mcp.tools.fix import write_fix


class TestWriteFix:

    def test_valid_diff_applied(self, tmp_path: Path) -> None:
        f = tmp_path / "code.py"
        f.write_text("x = 1\n")
        diff = (
            "--- a/code.py\n"
            "+++ b/code.py\n"
            "@@ -1 +1 @@\n"
            "-x = 1\n"
            "+x = 99\n"
        )

        result = write_fix(str(f), diff, repo_root=str(tmp_path))

        assert result["success"] is True
        assert result["rolled_back"] is False
        assert result["error"] is None
        assert f.read_text() == "x = 99\n"

    def test_failing_tests_trigger_rollback(self, tmp_path: Path) -> None:
        f = tmp_path / "code.py"
        f.write_text("x = 1\n")
        diff = (
            "--- a/code.py\n"
            "+++ b/code.py\n"
            "@@ -1 +1 @@\n"
            "-x = 1\n"
            "+x = 99\n"
        )

        result = write_fix(
            str(f),
            diff,
            repo_root=str(tmp_path),
            test_command='python3 -c "raise SystemExit(1)"',
            allowed_test_commands=["python3"],
        )

        assert result["success"] is False
        assert result["rolled_back"] is True
        assert f.read_text() == "x = 1\n"

    def test_invalid_diff_handled_gracefully(self, tmp_path: Path) -> None:
        f = tmp_path / "code.py"
        f.write_text("x = 1\n")

        result = write_fix(str(f), "this is not a valid diff", repo_root=str(tmp_path))

        assert result["success"] is False
        assert result["error"] is not None
        assert f.read_text() == "x = 1\n"

    def test_path_traversal_blocked(self, tmp_path: Path) -> None:
        outer = tmp_path / "secret.py"
        outer.write_text("secret\n")
        repo = tmp_path / "repo"
        repo.mkdir()
        diff = (
            "--- a/secret.py\n"
            "+++ b/secret.py\n"
            "@@ -1 +1 @@\n"
            "-secret\n"
            "+hacked\n"
        )

        result = write_fix(str(outer), diff, repo_root=str(repo))

        assert result["success"] is False
        assert result["error"] is not None
        assert outer.read_text() == "secret\n"

    def test_default_allowlist_permits_a_documented_runner(self, tmp_path: Path) -> None:
        # no allowed_test_commands given: the built-in allowlist must apply,
        # not an empty one that rejects everything
        f = tmp_path / "code.py"
        f.write_text("x = 1\n")
        diff = "@@ -1 +1 @@\n-x = 1\n+x = 99\n"

        result = write_fix(str(f), diff, repo_root=str(tmp_path), test_command="pytest --version")

        assert result["success"] is True
        assert f.read_text() == "x = 99\n"

    def test_command_outside_the_default_allowlist_is_rejected(self, tmp_path: Path) -> None:
        f = tmp_path / "code.py"
        f.write_text("x = 1\n")
        diff = "@@ -1 +1 @@\n-x = 1\n+x = 99\n"

        result = write_fix(str(f), diff, repo_root=str(tmp_path), test_command="rm -rf /")

        assert result["success"] is False
        assert f.read_text() == "x = 1\n", "the diff must not be applied at all"

    def test_missing_executable_rolls_back(self, tmp_path: Path) -> None:
        f = tmp_path / "code.py"
        f.write_text("x = 1\n")
        diff = "@@ -1 +1 @@\n-x = 1\n+x = 99\n"

        result = write_fix(
            str(f),
            diff,
            repo_root=str(tmp_path),
            test_command="gradle test",
            allowed_test_commands=["gradle test"],
        )

        assert result["success"] is False
        assert result["rolled_back"] is True
        assert f.read_text() == "x = 1\n"

LF_SOURCE = b"def a():\n    return 1\n\n\ndef b():\n    return 2\n"
CRLF_SOURCE = LF_SOURCE.replace(b"\n", b"\r\n")

LF_DIFF = (
    "--- a/t.py\n"
    "+++ b/t.py\n"
    "@@ -1,2 +1,2 @@\n"
    " def a():\n"
    "-    return 1\n"
    "+    return 99\n"
)
CRLF_DIFF = LF_DIFF.replace("\n", "\r\n")


class TestWriteFixPreservesBytes:
    """
    A file writer has exactly two acceptable outcomes: the change landed, or
    the file is byte-identical. Everything here was failing before 0.2.7.
    """

    def test_an_lf_file_stays_lf(self, tmp_path: Path) -> None:
        # read_text/write_text round-tripped through os.linesep, so on Windows
        # a two-line patch rewrote every line ending in the file
        f = tmp_path / "t.py"
        f.write_bytes(LF_SOURCE)

        result = write_fix(str(f), LF_DIFF, repo_root=str(tmp_path))

        assert result["success"] is True
        assert b"\r" not in f.read_bytes()

    def test_a_crlf_file_patched_by_an_lf_diff_stays_crlf(self, tmp_path: Path) -> None:
        # replacement lines come from the diff, so without reterminating them
        # the hunk ends up with different endings from the rest of the file
        f = tmp_path / "t.py"
        f.write_bytes(CRLF_SOURCE)

        result = write_fix(str(f), LF_DIFF, repo_root=str(tmp_path))
        data = f.read_bytes()

        assert result["success"] is True
        assert data.count(b"\r\n") == CRLF_SOURCE.count(b"\r\n")
        assert b"\n" not in data.replace(b"\r\n", b"")

    def test_an_lf_file_patched_by_a_crlf_diff_stays_lf(self, tmp_path: Path) -> None:
        f = tmp_path / "t.py"
        f.write_bytes(LF_SOURCE)

        result = write_fix(str(f), CRLF_DIFF, repo_root=str(tmp_path))

        assert result["success"] is True
        assert b"\r" not in f.read_bytes()

    def test_a_refused_diff_leaves_the_file_byte_identical(self, tmp_path: Path) -> None:
        # the file is never modified when a diff is refused, but the rollback
        # that ran anyway used to rewrite it from a re-encoded backup
        f = tmp_path / "t.py"
        f.write_bytes(LF_SOURCE)
        stale = LF_DIFF.replace("    return 1", "    return 7777")

        result = write_fix(str(f), stale, repo_root=str(tmp_path))

        assert result["success"] is False
        assert f.read_bytes() == LF_SOURCE

    def test_an_empty_diff_leaves_the_file_byte_identical(self, tmp_path: Path) -> None:
        f = tmp_path / "t.py"
        f.write_bytes(LF_SOURCE)

        write_fix(str(f), "", repo_root=str(tmp_path))

        assert f.read_bytes() == LF_SOURCE

    def test_rollback_restores_the_file_byte_identical(self, tmp_path: Path) -> None:
        f = tmp_path / "t.py"
        f.write_bytes(LF_SOURCE)

        result = write_fix(
            str(f),
            LF_DIFF,
            repo_root=str(tmp_path),
            test_command="python -c exit(1)",
            allowed_test_commands=["python"],
        )

        assert result["rolled_back"] is True
        assert f.read_bytes() == LF_SOURCE

    def test_a_users_own_bak_file_is_not_destroyed(self, tmp_path: Path) -> None:
        # the backup used a fixed "<name>.bak", overwrote whatever was there
        # and then deleted it
        f = tmp_path / "t.py"
        f.write_bytes(LF_SOURCE)
        mine = tmp_path / "t.py.bak"
        mine.write_bytes(b"a backup of my own\n")

        result = write_fix(str(f), LF_DIFF, repo_root=str(tmp_path))

        assert result["success"] is True
        assert mine.exists()
        assert mine.read_bytes() == b"a backup of my own\n"

    def test_a_non_utf8_file_returns_an_error_instead_of_raising(
        self, tmp_path: Path
    ) -> None:
        # only OSError was caught, so UnicodeDecodeError crossed the MCP
        # boundary, which tool functions are not allowed to do
        f = tmp_path / "t.py"
        original = bytes([0xFF, 0xFE, 0x00]) + b"binary\n"
        f.write_bytes(original)

        result = write_fix(str(f), LF_DIFF, repo_root=str(tmp_path))

        assert isinstance(result, dict)
        assert result["success"] is False
        assert f.read_bytes() == original

    def test_no_backup_is_left_behind_on_any_path(self, tmp_path: Path) -> None:
        f = tmp_path / "t.py"
        f.write_bytes(LF_SOURCE)
        write_fix(str(f), LF_DIFF, repo_root=str(tmp_path))
        write_fix(str(f), LF_DIFF, repo_root=str(tmp_path))  # now refused

        leftovers = [
            q.name
            for q in tmp_path.iterdir()
            if ".reforge-bak" in q.name or q.name.endswith((".bak", ".tmp"))
        ]
        assert leftovers == []
