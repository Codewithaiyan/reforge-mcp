"""Automated Fix Tool."""

import os
import subprocess
from typing import Any

from ..utils.diff import apply_diff, rollback
from ..utils.security import SecurityError, validate_path, validate_test_command


def _git_stash(repo_root: str) -> bool:
    try:
        r = subprocess.run(
            ["git", "stash"],
            cwd=repo_root,
            capture_output=True,
            text=True,
            timeout=30,
        )
        return r.returncode == 0 and "No local changes to save" not in r.stdout
    except (subprocess.SubprocessError, FileNotFoundError, OSError):
        return False


def _git_stash_pop(repo_root: str) -> None:
    try:
        subprocess.run(
            ["git", "stash", "pop"],
            cwd=repo_root,
            capture_output=True,
            text=True,
            timeout=30,
        )
    except (subprocess.SubprocessError, FileNotFoundError, OSError):
        pass


def write_fix(
    file_path: str,
    diff_str: str,
    repo_root: str | None = None,
    test_command: str | None = None,
    allowed_test_commands: list[str] | None = None,
) -> dict[str, Any]:
    """
    Apply a unified diff to a file and optionally run tests to verify safety.

    Returns {success, test_output, error, rolled_back}.
    Rolls back automatically (via .bak + git stash pop) if tests fail.
    """
    if repo_root is None:
        repo_root = os.getcwd()

    try:
        resolved = validate_path(file_path, repo_root)
    except SecurityError as e:
        return {"success": False, "test_output": None, "error": str(e), "rolled_back": False}

    if test_command is not None:
        try:
            validate_test_command(test_command, allowed_test_commands or [])
        except SecurityError as e:
            return {"success": False, "test_output": None, "error": str(e), "rolled_back": False}

    # Create .bak for reliable file-level rollback
    bak = resolved.with_suffix(resolved.suffix + ".bak")
    try:
        original = resolved.read_text(encoding="utf-8")
        bak.write_text(original, encoding="utf-8")
    except OSError as e:
        return {
            "success": False,
            "test_output": None,
            "error": f"Cannot read/backup '{resolved}': {e}",
            "rolled_back": False,
        }

    # Git stash saves any pre-existing dirty state; best-effort, not required
    stash_created = _git_stash(repo_root)

    if not apply_diff(str(resolved), diff_str):
        rollback(str(resolved))
        bak.unlink(missing_ok=True)
        if stash_created:
            _git_stash_pop(repo_root)
        return {
            "success": False,
            "test_output": None,
            "error": "Failed to apply diff — verify the diff is valid and matches the file content",
            "rolled_back": True,
        }

    if test_command is None:
        bak.unlink(missing_ok=True)
        if stash_created:
            _git_stash_pop(repo_root)
        return {"success": True, "test_output": None, "error": None, "rolled_back": False}

    try:
        proc = subprocess.run(
            test_command,
            shell=True,
            capture_output=True,
            text=True,
            timeout=120,
            cwd=repo_root,
        )
        test_output = proc.stdout + proc.stderr
        passed = proc.returncode == 0
    except subprocess.TimeoutExpired:
        passed = False
        test_output = "Test command timed out"
    except (subprocess.SubprocessError, OSError) as e:
        passed = False
        test_output = str(e)

    if passed:
        bak.unlink(missing_ok=True)
        if stash_created:
            _git_stash_pop(repo_root)
        return {"success": True, "test_output": test_output, "error": None, "rolled_back": False}

    # Tests failed — restore original file
    rollback(str(resolved))
    bak.unlink(missing_ok=True)
    if stash_created:
        _git_stash_pop(repo_root)
    return {
        "success": False,
        "test_output": test_output,
        "error": "Tests failed — changes rolled back",
        "rolled_back": True,
    }
