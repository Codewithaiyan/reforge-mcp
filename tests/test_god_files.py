"""Tests for god file detection."""

from pathlib import Path

from reforge_mcp.tools.scan import scan_repo


def god_files(tmp_path: Path) -> list[dict]:
    return scan_repo(str(tmp_path))["god_files"]


def test_long_file_is_flagged(tmp_path: Path) -> None:
    body = "".join(f"x{i} = {i}\n" for i in range(600))
    (tmp_path / "huge.py").write_text(body)

    assert [g["file"] for g in god_files(tmp_path)] == ["huge.py"]


def test_many_top_level_functions_are_flagged(tmp_path: Path) -> None:
    body = "".join(f"def fn_{i}():\n    return {i}\n\n\n" for i in range(11))
    (tmp_path / "wide.py").write_text(body)

    found = god_files(tmp_path)

    assert len(found) == 1
    assert found[0]["exports"] == 11


def test_methods_do_not_count_as_exports(tmp_path: Path) -> None:
    # one class holding thirty methods exports one name, not thirty-one
    methods = "".join(f"    def m_{i}(self):\n        return {i}\n\n" for i in range(30))
    (tmp_path / "service.py").write_text("class Service:\n" + methods)

    assert god_files(tmp_path) == []


def test_test_files_are_not_god_files(tmp_path: Path) -> None:
    tests = tmp_path / "tests"
    tests.mkdir()
    body = "".join(f"def test_case_{i}():\n    assert True\n\n\n" for i in range(30))
    (tests / "test_everything.py").write_text(body)

    assert god_files(tmp_path) == []


def test_test_file_outside_a_tests_dir_is_also_skipped(tmp_path: Path) -> None:
    body = "".join(f"def test_case_{i}():\n    assert True\n\n\n" for i in range(30))
    (tmp_path / "test_inline.py").write_text(body)

    assert god_files(tmp_path) == []


def test_small_module_is_not_flagged(tmp_path: Path) -> None:
    (tmp_path / "tidy.py").write_text("def one():\n    return 1\n")

    assert god_files(tmp_path) == []
