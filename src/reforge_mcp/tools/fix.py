"""Automated Fix Tool."""

import os
import shlex
import shutil
import subprocess
import tempfile
from typing import Any

from ..utils.diff import apply_diff, rollback
from ..utils.security import SecurityError, validate_path, validate_test_command


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
    Rolls back automatically from the .bak copy if tests fail.
    """
    if repo_root is None:
        repo_root = os.getcwd()

    try:
        resolved = validate_path(file_path, repo_root)
    except SecurityError as e:
        return {"success": False, "test_output": None, "error": str(e), "rolled_back": False}

    if test_command is not None:
        try:
            validate_test_command(test_command, allowed_test_commands)
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

    if not apply_diff(str(resolved), diff_str):
        rollback(str(resolved))
        bak.unlink(missing_ok=True)
        return {
            "success": False,
            "test_output": None,
            "error": "Failed to apply diff — verify the diff is valid and matches the file content",
            "rolled_back": True,
        }

    if test_command is None:
        bak.unlink(missing_ok=True)
        return {"success": True, "test_output": None, "error": None, "rolled_back": False}

    # No shell: the command is split here and the executable resolved by name,
    # so nothing in it can be interpreted as shell syntax. shutil.which also
    # finds the .cmd shims that npm and yarn install on Windows.
    try:
        argv = shlex.split(test_command)
    except ValueError as e:
        argv = []
        test_output = f"Could not parse test command: {e}"

    executable = shutil.which(argv[0]) if argv else None

    if executable is None:
        passed = False
        if argv:
            test_output = f"Test command not found: {argv[0]}"
    else:
        # Output goes to a file rather than a pipe, and stdin is closed. Both
        # matter for a command we do not control: a test runner that leaves a
        # grandchild holding an inherited pipe makes the communicate() after a
        # timeout block forever - the timeout kills the child, not the pipe -
        # and an inherited stdin lets anything that prompts wait for input that
        # will never arrive. Either one hangs write_fix with no way out.
        with tempfile.TemporaryFile() as out:
            note = ""
            try:
                proc = subprocess.run(
                    [executable, *argv[1:]],
                    stdin=subprocess.DEVNULL,
                    stdout=out,
                    stderr=subprocess.STDOUT,
                    timeout=120,
                    cwd=repo_root,
                )
                passed = proc.returncode == 0
            except subprocess.TimeoutExpired:
                passed = False
                note = "\nTest command timed out after 120s"
            except (subprocess.SubprocessError, OSError) as e:
                passed = False
                note = f"\n{e}"

            out.seek(0)
            test_output = out.read().decode("utf-8", "replace") + note

    if passed:
        bak.unlink(missing_ok=True)
        return {"success": True, "test_output": test_output, "error": None, "rolled_back": False}

    # Tests failed — restore original file
    rollback(str(resolved))
    bak.unlink(missing_ok=True)
    return {
        "success": False,
        "test_output": test_output,
        "error": "Tests failed — changes rolled back",
        "rolled_back": True,
    }
