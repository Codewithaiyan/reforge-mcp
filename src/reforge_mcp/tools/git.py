"""Git Operations Tool."""

import json
import os
import tomllib
from pathlib import Path
from typing import Any

from ..utils.security import SecurityError, validate_path

_SESSION_FILE = ".reforge-session.json"
_DEFAULT_FIX_CFG = {"session_budget": 20, "confirm_every": 5}


def _load_config(repo_path: str) -> dict:
    try:
        with open(Path(repo_path) / "reforge.toml", "rb") as f:
            return tomllib.load(f)
    except (OSError, tomllib.TOMLDecodeError):
        return {"fix": _DEFAULT_FIX_CFG}


def _load_session(repo_path: str) -> dict:
    try:
        return json.loads(
            (Path(repo_path) / _SESSION_FILE).read_text(encoding="utf-8")
        )
    except (OSError, json.JSONDecodeError, ValueError):
        return {"fix_count": 0}


def _save_session(repo_path: str, session: dict) -> None:
    dest = Path(repo_path) / _SESSION_FILE
    tmp = dest.with_suffix(".tmp")
    try:
        tmp.write_text(json.dumps(session, indent=2), encoding="utf-8")
        tmp.replace(dest)
    except OSError:
        tmp.unlink(missing_ok=True)


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
    files: list[str] | None = None,
    message: str | None = None,
    branch: str | None = None,
    create_branch: bool = False,
    confirmed: bool = False,
) -> dict[str, Any]:
    """
    Stage specific files and create an atomic git commit.

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

    # Validate each requested file path
    if files:
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
    session = _load_session(repo_path)
    fix_count: int = session.get("fix_count", 0)

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
    repo_root = Path(repo_path)
    try:
        if files is None:
            repo.git.add(A=True)
        else:
            relative: list[str] = [
                str(Path(fp).relative_to(repo_root))
                if Path(fp).is_absolute()
                else fp
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

    # Persist incremented fix count atomically
    session["fix_count"] = fix_count + 1
    _save_session(repo_path, session)

    try:
        current_branch = repo.active_branch.name
    except TypeError:
        current_branch = commit.hexsha[:8]

    files_committed = files if files is not None else list(commit.stats.files.keys())

    return {
        "success": True,
        "commit_hash": commit.hexsha,
        "branch": current_branch,
        "files_committed": files_committed,
        "error": None,
    }
