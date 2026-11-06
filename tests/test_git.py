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

    def test_unchanged_named_file_is_rejected_without_using_budget(self, git_repo: Path) -> None:
        import git as _git

        repo = _git.Repo(git_repo)
        before = repo.head.commit.hexsha
        key = str(git_repo.resolve())

        result = git_commit(str(git_repo), files=["README.md"])

        assert result["success"] is False
        assert result["error"] == "Nothing to commit: staged files match HEAD."
        assert result["commit_hash"] is None
        assert repo.head.commit.hexsha == before
        assert git_tool._fix_counts.get(key, 0) == 0

    def test_modified_named_file_is_committed(self, git_repo: Path) -> None:
        import git as _git

        readme = git_repo / "README.md"
        readme.write_bytes(b"updated\n")
        result = git_commit(str(git_repo), files=["README.md"], message="docs: update readme")

        assert result["success"] is True
        assert _git.Repo(git_repo).head.commit.tree["README.md"].data_stream.read() == b"updated\n"

    def test_previously_staged_change_is_still_committed(self, git_repo: Path) -> None:
        import git as _git

        repo = _git.Repo(git_repo)
        (git_repo / "staged.py").write_text("x = 1\n", encoding="utf-8")
        repo.index.add(["staged.py"])

        result = git_commit(str(git_repo), files=["README.md"])

        assert result["success"] is True
        assert "staged.py" in repo.head.commit.tree

    def test_initial_commit_is_allowed(self, tmp_path: Path) -> None:
        import git as _git

        repo = _git.Repo.init(tmp_path)
        with repo.config_writer() as config:
            config.set_value("user", "name", "Test User")
            config.set_value("user", "email", "test@example.com")
        (tmp_path / "first.py").write_text("x = 1\n", encoding="utf-8")

        result = git_commit(str(tmp_path), files=["first.py"])

        assert result["success"] is True
        assert not repo.head.commit.parents

    def test_confirmation_still_precedes_empty_commit_guard(self, git_repo: Path) -> None:
        key = str(git_repo.resolve())
        git_tool._fix_counts[key] = 5

        checkpoint = git_commit(str(git_repo), files=["README.md"])
        assert checkpoint["needs_confirmation"] is True

        refused = git_commit(str(git_repo), files=["README.md"], confirmed=True)
        assert refused["success"] is False
        assert refused["error"] == "Nothing to commit: staged files match HEAD."
        assert git_tool._fix_counts[key] == 5

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
