"""
End-to-end test of the tool chain Claude actually drives.

scan_repo -> get_chunk -> write_fix -> git_commit, on a real git repo with a
real defect, plus the two paths where the fix must be undone. The bad-diff case
here is the one that would have caught the applier silently corrupting files.

The gating command imports the project's own module rather than shelling out to
pytest. Nesting the full test runner hung Windows CI indefinitely, and a command
that exercises calc.add directly proves the same thing in milliseconds.
"""

from pathlib import Path

import pytest

from reforge_mcp.tools.chunk import get_chunk
from reforge_mcp.tools.fix import write_fix
from reforge_mcp.tools.git import git_commit
from reforge_mcp.tools.scan import scan_repo

CALC = """\
def add(a, b):
    return a + b


def unused_helper(x):
    return x * 2
"""

TEST_CALC = """\
from calc import add


def test_add():
    assert add(2, 2) == 4
"""

# removes unused_helper, keeping add intact
REMOVE_DEAD_CODE = (
    "@@ -2,5 +2,1 @@\n"
    "     return a + b\n"
    "-\n"
    "-\n"
    "-def unused_helper(x):\n"
    "-    return x * 2\n"
)

# changes add() so test_add fails
BREAK_ADD = "@@ -2,1 +2,1 @@\n-    return a + b\n+    return a - b\n"

CHECK = """import calc

assert calc.add(2, 2) == 4
"""

# Exercises the project's own code and exits in milliseconds. Shelling out to
# the real pytest here hung Windows CI indefinitely. It lives in a file rather
# than a -c one-liner because an inline "import calc; assert ..." contains a
# semicolon, which validate_test_command correctly refuses as command chaining.
CHECK_ADD = "python check.py"
ALLOW_PYTHON = ["python"]


@pytest.fixture
def project(tmp_path: Path) -> Path:
    import git as _git

    repo_path = tmp_path / "project"
    repo_path.mkdir()
    (repo_path / "calc.py").write_text(CALC)
    (repo_path / "test_calc.py").write_text(TEST_CALC)
    (repo_path / "check.py").write_text(CHECK)

    repo = _git.Repo.init(str(repo_path))
    with repo.config_writer() as cw:
        cw.set_value("user", "name", "Test User")
        cw.set_value("user", "email", "test@example.com")
    repo.index.add(["calc.py", "test_calc.py", "check.py"])
    repo.index.commit("init")
    return repo_path


def test_scan_fix_commit(project: Path) -> None:
    import git as _git

    # 1. scan finds the dead function
    scan = scan_repo(str(project))
    assert "unused_helper" in {d["symbol"] for d in scan["dead_code"]}

    # 2. read the lines before changing them
    chunk = get_chunk(str(project / "calc.py"), repo_root=str(project), start_line=5, end_line=6)
    assert "unused_helper" in chunk["source"]

    # 3. apply the fix, gated on the project's own test suite
    fix = write_fix(
        str(project / "calc.py"),
        REMOVE_DEAD_CODE,
        repo_root=str(project),
        test_command=CHECK_ADD,
        allowed_test_commands=ALLOW_PYTHON,
    )
    assert fix["success"] is True, fix
    assert fix["rolled_back"] is False
    assert (project / "calc.py").read_text() == "def add(a, b):\n    return a + b\n"

    # 4. commit only that file
    commit = git_commit(
        str(project), files=["calc.py"], message="refactor: drop unused_helper"
    )
    assert commit["success"] is True, commit

    repo = _git.Repo(str(project))
    assert list(repo.head.commit.stats.files.keys()) == ["calc.py"]
    assert repo.head.commit.message.startswith("refactor:")

    # 5. the defect is gone and nothing else moved
    assert scan_repo(str(project))["dead_code"] == []
    assert repo.is_dirty() is False


def test_failing_tests_undo_the_fix(project: Path) -> None:
    original = (project / "calc.py").read_text()

    fix = write_fix(
        str(project / "calc.py"),
        BREAK_ADD,
        repo_root=str(project),
        test_command=CHECK_ADD,
        allowed_test_commands=ALLOW_PYTHON,
    )

    assert fix["success"] is False
    assert fix["rolled_back"] is True
    assert "AssertionError" in fix["test_output"]
    assert (project / "calc.py").read_text() == original


def test_bad_diff_changes_nothing(project: Path) -> None:
    original = (project / "calc.py").read_text()

    # line numbers point past the end of a six-line file
    fix = write_fix(
        str(project / "calc.py"),
        "@@ -40,2 +40,1 @@\n-whatever\n-else\n+replaced\n",
        repo_root=str(project),
    )

    assert fix["success"] is False
    assert (project / "calc.py").read_text() == original


def test_stale_diff_changes_nothing(project: Path) -> None:
    # right line numbers, content that no longer matches - the case a slightly
    # out-of-date plan produces, and the one that used to corrupt files
    original = (project / "calc.py").read_text()

    fix = write_fix(
        str(project / "calc.py"),
        "@@ -2,1 +2,1 @@\n-    return a * b\n+    return a + b + 1\n",
        repo_root=str(project),
    )

    assert fix["success"] is False
    assert (project / "calc.py").read_text() == original


def test_no_backup_files_are_left_behind(project: Path) -> None:
    write_fix(
        str(project / "calc.py"),
        REMOVE_DEAD_CODE,
        repo_root=str(project),
        test_command=CHECK_ADD,
        allowed_test_commands=ALLOW_PYTHON,
    )

    assert list(project.glob("*.bak")) == []
    assert list(project.glob("*.tmp")) == []
