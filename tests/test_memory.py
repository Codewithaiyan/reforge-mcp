"""Tests for state persistence, crash recovery, health score, and gitignore setup."""

import json
from pathlib import Path

import pytest

from reforge_mcp.utils.state import (
    cleanup_tmp_files,
    ensure_gitignore,
    generate_changelog,
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
        (tmp_path / f"n{i}.cpp").write_text("int x() { return 1; }\n")

    h = get_health_score(str(tmp_path), state_path=None)

    assert h["coverage"] == 0.1
    assert "1 of 10 source files" in h["caveat"]


def test_health_score_on_a_fully_readable_repo_has_no_caveat(tmp_path) -> None:
    (tmp_path / "a.py").write_text("def f():\n    return 1\n")

    h = get_health_score(str(tmp_path), state_path=None)

    assert h["coverage"] == 1.0
    assert "caveat" not in h

class TestGenerateChangelogOnBadState:
    """State on disk was not necessarily written by this version."""

    def test_a_history_entry_with_no_score_does_not_raise(self, tmp_path: Path) -> None:
        assert generate_changelog(str(tmp_path), {"health_history": [{"timestamp": "x"}]})
        assert "Health score" not in (tmp_path / "REFORGE_CHANGES.md").read_text()

    def test_a_null_score_does_not_raise(self, tmp_path: Path) -> None:
        assert generate_changelog(str(tmp_path), {"health_history": [{"score": None}]})

    def test_a_string_score_does_not_raise(self, tmp_path: Path) -> None:
        assert generate_changelog(str(tmp_path), {"health_history": [{"score": "ninety"}]})

    def test_a_fix_log_entry_that_is_not_a_dict_does_not_raise(
        self, tmp_path: Path
    ) -> None:
        assert generate_changelog(str(tmp_path), {"fix_log": ["just a string"]})
        assert "just a string" in (tmp_path / "REFORGE_CHANGES.md").read_text()

    def test_usable_scores_still_produce_a_signed_delta(self, tmp_path: Path) -> None:
        state = {"health_history": [{"score": 70.0}, {"score": 85.0}]}

        assert generate_changelog(str(tmp_path), state)
        text = (tmp_path / "REFORGE_CHANGES.md").read_text()
        assert "**Health score:** 85.0 (+15.0 from previous scan)" in text

    def test_unusable_entries_are_skipped_when_computing_the_delta(
        self, tmp_path: Path
    ) -> None:
        state = {"health_history": [{"score": 70.0}, {"broken": True}, {"score": 85.0}]}

        assert generate_changelog(str(tmp_path), state)
        assert "(+15.0 from previous scan)" in (
            tmp_path / "REFORGE_CHANGES.md"
        ).read_text()

    def test_a_write_that_fails_returns_false(self, tmp_path: Path) -> None:
        # it swallowed OSError and returned None, so the MCP tool reported
        # success for a file that was never written
        import os
        import stat

        target = tmp_path / "REFORGE_CHANGES.md"
        target.write_text("placeholder", encoding="utf-8")
        os.chmod(target, stat.S_IREAD)
        try:
            assert generate_changelog(str(tmp_path), {"pending_fixes": ["x"]}) is False
            assert target.read_text() == "placeholder"
        finally:
            os.chmod(target, stat.S_IWRITE)


def test_parse_failures_are_counted_and_not_called_scanned(
    tmp_path, monkeypatch
) -> None:
    """A file whose adapter raises is not a file that was scanned.

    Counting them as scanned let axios report 277 files, no findings and a
    health score of 100 while every single file had failed to parse.
    """
    from reforge_mcp.scanner import parser as parser_module
    from reforge_mcp.tools.scan import scan_repo

    (tmp_path / "good.py").write_text("def kept():" + chr(10) + "    return 1" + chr(10))
    (tmp_path / "bad.py").write_text("def broken():" + chr(10) + "    return 2" + chr(10))

    real = parser_module.parse_file

    def fail_on_bad(file_path, repo_root, *a, **k):
        result = real(file_path, repo_root, *a, **k)
        if result is not None and result.file.endswith("bad.py"):
            return parser_module.ParseResult(
                file=result.file,
                language=result.language,
                references=(),
                functions=(),
                classes=(),
                imports=(),
                total_lines=result.total_lines,
                error="Parse error: forced by test",
            )
        return result

    monkeypatch.setattr(parser_module, "parse_file", fail_on_bad)

    summary = scan_repo(str(tmp_path))["summary"]

    assert summary["parse_failures"] == 1
    assert summary["total_files"] == 1


def test_a_repo_nothing_could_be_read_from_has_no_score(tmp_path) -> None:
    # ripgrep scored 100.0 with zero files analysed, which is the most
    # misleading output this tool can produce
    from reforge_mcp.tools.scan import get_health_score

    (tmp_path / "main.rs").write_text("fn main() {}" + chr(10))
    (tmp_path / "lib.rs").write_text("pub fn f() -> i32 { 1 }" + chr(10))

    h = get_health_score(str(tmp_path), state_path=None)

    assert h["score"] is None
    assert h["coverage"] == 0.0
    assert "no score to report" in h["caveat"]


def test_a_fully_readable_repo_reports_zero_failures(tmp_path) -> None:
    from reforge_mcp.tools.scan import get_health_score, scan_repo

    (tmp_path / "a.py").write_text("def f():" + chr(10) + "    return 1" + chr(10))

    assert scan_repo(str(tmp_path))["summary"]["parse_failures"] == 0
    h = get_health_score(str(tmp_path), state_path=None)
    assert isinstance(h["score"], float)
    assert "caveat" not in h
