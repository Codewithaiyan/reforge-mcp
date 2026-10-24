"""Persistent state management for reforge-mcp."""

import json
import os
import shutil
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

STATE_FILE = "reforge-state.json"
MAX_BACKUPS = 5

_GITIGNORE_ENTRIES = [
    "reforge-state.json",
    ".reforge*",
    "reforge-state.json.bak.*",
    "REFORGE_CHANGES.md",
]

_EMPTY_STATE: dict[str, Any] = {
    "created_at": None,
    "last_scan": None,
    "architecture_hypothesis": None,
    "health_history": [],
    "fix_log": [],
    "pending_fixes": [],
}


def load_state(repo_path: str) -> dict[str, Any]:
    """Load reforge-state.json, returning defaults for missing keys."""
    state_path = Path(repo_path) / STATE_FILE
    try:
        data = json.loads(state_path.read_text(encoding="utf-8"))
        return {**_EMPTY_STATE, **data}
    except (OSError, json.JSONDecodeError, ValueError):
        return {**_EMPTY_STATE, "created_at": _now()}


def save_state(repo_path: str, state: dict[str, Any]) -> None:
    """Write state atomically (.tmp → rename) and rotate to keep last 5 backups."""
    dest = Path(repo_path) / STATE_FILE
    tmp = dest.with_suffix(".tmp")

    try:
        tmp.write_text(json.dumps(state, indent=2, default=str), encoding="utf-8")
        if dest.exists():
            _rotate_backup(dest)
            dest.unlink()  # Windows-safe: unlink before rename
        tmp.rename(dest)
    except OSError:
        tmp.unlink(missing_ok=True)
        raise


def _rotate_backup(dest: Path) -> None:
    ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S")
    bak = dest.parent / f"{dest.name}.bak.{ts}"
    try:
        shutil.copy2(str(dest), str(bak))
    except OSError:
        pass

    backups = sorted(dest.parent.glob(f"{dest.name}.bak.*"))
    for old in backups[:-MAX_BACKUPS]:
        try:
            old.unlink()
        except OSError:
            pass


def cleanup_tmp_files(repo_path: str) -> list[str]:
    """Remove orphaned .tmp files left by crashed writes. Returns removed paths."""
    removed: list[str] = []
    for tmp in Path(repo_path).glob("*.tmp"):
        try:
            tmp.unlink()
            removed.append(str(tmp))
        except OSError:
            pass
    return removed


def ensure_gitignore(repo_path: str) -> bool:
    """Append reforge entries to .gitignore if absent. Returns True if anything was added."""
    gitignore = Path(repo_path) / ".gitignore"
    try:
        existing = gitignore.read_text(encoding="utf-8") if gitignore.exists() else ""
    except OSError:
        existing = ""

    missing = [e for e in _GITIGNORE_ENTRIES if e not in existing]
    if not missing:
        return False

    block = "\n# reforge-mcp\n" + "\n".join(missing) + "\n"
    try:
        with open(gitignore, "a", encoding="utf-8") as fh:
            fh.write(block)
        return True
    except OSError:
        return False


def _fix_label(entry: Any) -> str:
    """A one-line description of a fix_log entry, whatever shape it is in."""
    if not isinstance(entry, dict):
        return str(entry)
    return str(entry.get("message") or entry.get("file") or "unknown")


def _score_of(entry: Any) -> float | None:
    """
    The score in a history entry, or None if it is not a usable number.

    State on disk is not guaranteed to have been written by this version:
    an entry with no score, or a null, or a string, used to raise KeyError,
    TypeError and ValueError respectively - out through the MCP boundary.
    """
    if not isinstance(entry, dict):
        return None
    value = entry.get("score")
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return float(value)


def generate_changelog(repo_path: str, state: dict[str, Any]) -> bool:
    """
    Write REFORGE_CHANGES.md: health delta, fixes, pending items.

    Returns whether the file was written. It used to swallow OSError and
    return None, so the MCP tool reported success for a write that never
    happened.
    """
    history: list[Any] = state.get("health_history") or []
    fix_log: list[Any] = state.get("fix_log") or []
    pending: list[Any] = state.get("pending_fixes") or []

    scores = [s for s in (_score_of(h) for h in history) if s is not None]
    if len(scores) >= 2:
        delta = scores[-1] - scores[-2]
        sign = "+" if delta >= 0 else ""
        score_line = (
            f"**Health score:** {scores[-1]:.1f} "
            f"({sign}{delta:.1f} from previous scan)\n\n"
        )
    elif scores:
        score_line = f"**Health score:** {scores[-1]:.1f}\n\n"
    else:
        score_line = ""

    fixes_md = ""
    if fix_log:
        items = "".join(
            f"- {_fix_label(f)}\n" for f in fix_log
        )
        fixes_md = f"## Fixes Applied\n\n{items}\n"

    pending_md = "## Pending Fixes\n\n" + (
        "".join(f"- {p}\n" for p in pending) if pending else "_None_\n"
    )

    content = (
        "# Reforge Changes\n\n"
        f"*Generated: {_now()}*\n\n"
        f"{score_line}"
        f"{fixes_md}"
        f"{pending_md}"
    )

    try:
        (Path(repo_path) / "REFORGE_CHANGES.md").write_text(content, encoding="utf-8")
        return True
    except OSError:
        return False


def startup_tasks(repo_path: str) -> dict[str, Any]:
    """Run on server startup: clean .tmp files, ensure .gitignore entries."""
    removed = cleanup_tmp_files(repo_path)
    gitignore_updated = ensure_gitignore(repo_path)
    return {"cleaned_tmp_files": removed, "gitignore_updated": gitignore_updated}


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()
