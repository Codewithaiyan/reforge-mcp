"""Git Operations Tool."""

import os
import tomllib
from pathlib import Path
from typing import Any

from ..utils.security import SecurityError, validate_path

_DEFAULT_FIX_CFG = {"session_budget": 20, "confirm_every": 5}

# Commits made this session, per repo. The server process *is* the session, so
# this resets when it restarts - which is what "start a new session" means and
# what the budget is documented to cover. Persisting it to disk, as an earlier
# version did, made it a lifetime budget: after 20 commits ever, every call
# failed and the only way out was deleting a file by hand.
_fix_counts: dict[str, int] = {}


def _session_key(repo_path: str) -> str:
    try:
        return str(Path(repo_path).resolve())
    except OSError:
        return repo_path


def _load_config(repo_path: str) -> dict:
    try:
        with open(Path(repo_path) / "reforge.toml", "rb") as f:
            return tomllib.load(f)
    except (OSError, tomllib.TOMLDecodeError):
        return {"fix": _DEFAULT_FIX_CFG}


def _err(msg: str) -> dict[str, Any]:
    return {
        "success": False,
        "commit_hash": None,
        "branch": None,
        "files_committed": [],
        "error": msg,
    }


def git_commit(
    repo_path: str,
    files: list[str],
    message: str | None = None,
    branch: str | None = None,
    create_branch: bool = False,
    confirmed: bool = False,
) -> dict[str, Any]:
    """
    Stage specific files and create an atomic git commit.

    files must be a non-empty list: a fix commit may only ever contain the files
    that fix touched, never whatever else happened to be in the working tree.
    Enforces session budget and confirmation checkpoints from reforge.toml.
    Returns {success, commit_hash, branch, files_committed, error}.
    Set confirmed=True to proceed past a confirmation checkpoint.
    """
    import git as _git  # deferred to avoid name collision with this module

    # Validate repo root
    try:
        validate_path(repo_path, repo_path)
    except SecurityError as e:
        return _err(str(e))

    if not files:
        return _err("No files given: list the files this commit should contain.")

    # Validate each requested file path
    repo_root = Path(repo_path)
    for fp in files:
        full = str(repo_root / fp) if not Path(fp).is_absolute() else fp
        try:
            validate_path(full, repo_path)
        except SecurityError as e:
            return _err(str(e))

    # Load config
    config = _load_config(repo_path)
    fix_cfg = config.get("fix", _DEFAULT_FIX_CFG)
    session_budget: int = fix_cfg.get("session_budget", 20)
    confirm_every: int = fix_cfg.get("confirm_every", 5)

    # Load session state
    session_key = _session_key(repo_path)
    fix_count: int = _fix_counts.get(session_key, 0)

    # Enforce session budget
    if fix_count >= session_budget:
        return _err(
            f"Session budget exceeded: {fix_count}/{session_budget} fixes used. "
            "Start a new session to continue."
        )

    # Confirmation checkpoint (skip if caller already confirmed)
    if not confirmed and fix_count > 0 and fix_count % confirm_every == 0:
        return {
            "success": False,
            "commit_hash": None,
            "branch": None,
            "files_committed": [],
            "error": None,
            "needs_confirmation": True,
            "message": (
                f"Checkpoint: {fix_count} fixes applied. "
                "Re-call with confirmed=True to proceed."
            ),
        }

    # Open repo
    try:
        repo = _git.Repo(repo_path)
    except (_git.InvalidGitRepositoryError, _git.NoSuchPathError) as e:
        return _err(f"Not a git repository: {e}")

    # Branch handling
    if create_branch and branch:
        try:
            repo.create_head(branch).checkout()
        except Exception as e:
            return _err(f"Cannot create branch '{branch}': {e}")
    elif branch:
        try:
            repo.heads[branch].checkout()
        except Exception as e:
            return _err(f"Cannot checkout branch '{branch}': {e}")

    # Stage files
    try:
        relative: list[str] = [
            str(Path(fp).relative_to(repo_root)) if Path(fp).is_absolute() else fp
            for fp in files
        ]
        repo.index.add(relative)
    except Exception as e:
        return _err(f"Failed to stage files: {e}")

    # Commit
    auto_message = message or f"refactor: automated fix #{fix_count + 1}"
    try:
        commit = repo.index.commit(auto_message)
    except Exception as e:
        return _err(f"Failed to commit: {e}")

    _fix_counts[session_key] = fix_count + 1

    try:
        current_branch = repo.active_branch.name
    except TypeError:
        current_branch = commit.hexsha[:8]

    files_committed = files

    return {
        "success": True,
        "commit_hash": commit.hexsha,
        "branch": current_branch,
        "files_committed": files_committed,
        "error": None,
    }
