"""Tests for state persistence, crash recovery, health score, and gitignore setup."""

import json
from pathlib import Path

import pytest

from reforge_mcp.utils.state import (
    cleanup_tmp_files,
    ensure_gitignore,
    load_state,
    save_state,
)
from reforge_mcp.tools.scan import get_health_score


class TestMemory:

    def test_state_written_and_read_back(self, tmp_path: Path) -> None:
        state = load_state(str(tmp_path))
        assert state["health_history"] == []
        assert state["fix_log"] == []

        state["architecture_hypothesis"] = "event-driven microservices"
        state["pending_fixes"].append("remove dead utils.py")
        save_state(str(tmp_path), state)

        loaded = load_state(str(tmp_path))
        assert loaded["architecture_hypothesis"] == "event-driven microservices"
        assert loaded["pending_fixes"] == ["remove dead utils.py"]
        assert (tmp_path / "reforge-state.json").exists()

    def test_crash_recovery_cleans_tmp_files(self, tmp_path: Path) -> None:
        orphan1 = tmp_path / "reforge-state.tmp"
        orphan2 = tmp_path / "other.tmp"
        orphan1.write_text("crashed mid-write")
        orphan2.write_text("also orphaned")

        removed = cleanup_tmp_files(str(tmp_path))

        assert not orphan1.exists()
        assert not orphan2.exists()
        assert len(removed) == 2

    def test_health_score_appended_to_history(self, tmp_path: Path) -> None:
        # Minimal source file so scan_repo has something to analyse
        (tmp_path / "app.py").write_text("def hello():\n    pass\n")

        result = get_health_score(str(tmp_path), state_path=str(tmp_path))

        assert "score" in result
        assert 0 <= result["score"] <= 100
        assert "breakdown" in result

        state = load_state(str(tmp_path))
        assert len(state["health_history"]) == 1
        assert state["health_history"][0]["score"] == result["score"]

        # Second call appends a second entry
        get_health_score(str(tmp_path), state_path=str(tmp_path))
        state2 = load_state(str(tmp_path))
        assert len(state2["health_history"]) == 2

    def test_gitignore_entries_added_on_first_run(self, tmp_path: Path) -> None:
        assert not (tmp_path / ".gitignore").exists()

        added = ensure_gitignore(str(tmp_path))

        assert added is True
        content = (tmp_path / ".gitignore").read_text()
        assert "reforge-state.json" in content
        assert ".reforge*" in content
        assert "REFORGE_CHANGES.md" in content
        assert ".reforge*" in content

        # Idempotent: second call adds nothing
        added_again = ensure_gitignore(str(tmp_path))
        assert added_again is False
        # File should be identical — no duplicate lines appended
        content2 = (tmp_path / ".gitignore").read_text()
        assert content2 == content


def test_health_score_reports_coverage_and_caveats_a_partial_scan(tmp_path) -> None:
    # one readable file beside nine the adapters cannot parse: a bare score
    # would read as a verdict on the whole repository
    (tmp_path / "a.py").write_text("def f():\n    return 1\n")
    for i in range(9):
        (tmp_path / f"n{i}.kt").write_text("fun x() {}\n")

    h = get_health_score(str(tmp_path), state_path=None)

    assert h["coverage"] == 0.1
    assert "1 of 10 source files" in h["caveat"]


def test_health_score_on_a_fully_readable_repo_has_no_caveat(tmp_path) -> None:
    (tmp_path / "a.py").write_text("def f():\n    return 1\n")

    h = get_health_score(str(tmp_path), state_path=None)

    assert h["coverage"] == 1.0
    assert "caveat" not in h
