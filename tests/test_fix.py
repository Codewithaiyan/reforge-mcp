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
