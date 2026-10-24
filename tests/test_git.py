"""Tests for the git_commit tool."""

from pathlib import Path

import pytest

from reforge_mcp.tools import git as git_tool
from reforge_mcp.tools.git import git_commit


@pytest.fixture
def git_repo(tmp_path: Path):
    """Initialise a temporary git repo with an initial commit and reforge.toml."""
    import git as _git

    repo_path = tmp_path / "repo"
    repo_path.mkdir()
    repo = _git.Repo.init(str(repo_path))
    with repo.config_writer() as cw:
        cw.set_value("user", "name", "Test User")
        cw.set_value("user", "email", "test@example.com")

    readme = repo_path / "README.md"
    readme.write_text("init\n")
    repo.index.add(["README.md"])
    repo.index.commit("init")

    (repo_path / "reforge.toml").write_text(
        "[fix]\nsession_budget = 20\nconfirm_every = 5\n"
    )
    return repo_path


class TestGitCommit:

    def test_valid_commit_succeeds(self, git_repo: Path) -> None:
        f = git_repo / "code.py"
        f.write_text("x = 1\n")

        result = git_commit(str(git_repo), files=["code.py"], message="feat: add code")

        assert result["success"] is True
        assert result["error"] is None
        assert result["commit_hash"] is not None
        assert len(result["commit_hash"]) == 40
        assert result["branch"] is not None
        assert "code.py" in result["files_committed"]

    def test_session_budget_exceeded_blocks_commit(self, git_repo: Path) -> None:
        git_tool._fix_counts[str(git_repo.resolve())] = 20

        f = git_repo / "code.py"
        f.write_text("x = 1\n")

        result = git_commit(str(git_repo), files=["code.py"], message="feat: add")

        assert result["success"] is False
        assert result["error"] is not None
        assert "budget" in result["error"].lower() or "exceeded" in result["error"].lower()

    def test_confirmation_checkpoint_triggers(self, git_repo: Path) -> None:
        # fix_count=5 is a multiple of confirm_every=5, so checkpoint fires
        git_tool._fix_counts[str(git_repo.resolve())] = 5

        f = git_repo / "code.py"
        f.write_text("x = 1\n")

        result = git_commit(str(git_repo), files=["code.py"], message="feat: add")

        assert result["success"] is False
        assert result.get("needs_confirmation") is True
        assert result["error"] is None

        # confirmed=True bypasses the checkpoint
        result2 = git_commit(
            str(git_repo), files=["code.py"], message="feat: add", confirmed=True
        )
        assert result2["success"] is True

    def test_invalid_file_path_blocked(self, git_repo: Path) -> None:
        result = git_commit(
            str(git_repo),
            files=["../../etc/passwd"],
            message="bad commit",
        )

        assert result["success"] is False
        assert result["error"] is not None
        assert result["commit_hash"] is None

    def test_empty_file_list_is_rejected(self, git_repo: Path) -> None:
        import git as _git

        unrelated = git_repo / "user_work_in_progress.py"
        unrelated.write_text("do not commit me\n")

        result = git_commit(str(git_repo), files=[], message="refactor: automated fix")

        assert result["success"] is False
        assert result["error"] is not None
        # the unrelated file must still be untracked - no sweeping commit happened
        assert "user_work_in_progress.py" in _git.Repo(str(git_repo)).untracked_files

    def test_budget_resets_for_a_new_session(self, git_repo: Path) -> None:
        # the budget covers one server process; an earlier version persisted the
        # count to disk, making 20 commits *ever* a permanent hard stop
        key = str(git_repo.resolve())
        git_tool._fix_counts[key] = 20
        f = git_repo / "code.py"
        f.write_text("x = 1\n")

        blocked = git_commit(str(git_repo), files=["code.py"], message="feat: add")
        assert blocked["success"] is False

        git_tool._fix_counts.pop(key)  # a fresh process starts with no history
        allowed = git_commit(str(git_repo), files=["code.py"], message="feat: add")
        assert allowed["success"] is True

    def test_commit_leaves_no_session_file_behind(self, git_repo: Path) -> None:
        f = git_repo / "code.py"
        f.write_text("x = 1\n")

        git_commit(str(git_repo), files=["code.py"], message="feat: add")

        assert not (git_repo / ".reforge-session.json").exists()
