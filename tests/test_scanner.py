"""Tests for the reforge scanner modules."""
import tempfile
import pytest
from pathlib import Path


def create_fake_repo(tmp_path):
    (tmp_path / "main.py").write_text(
        "def used_function():\n    return 42\n\ndef dead_function():\n    return 99\n\nresult = used_function()\n"
    )
    (tmp_path / "utils_a.py").write_text(
        "def calculate_total(items):\n    return sum(items)\n"
    )
    (tmp_path / "utils_b.py").write_text(
        "def calculate_total(items):\n    return sum(items)\n"
    )
    (tmp_path / "data.bin").write_bytes(b'\x00\x01\x02\x03')
    return tmp_path


def test_output_schema():
    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = Path(tmp)
        create_fake_repo(tmp_path)
        from reforge_mcp.tools.scan import scan_repo
        result = scan_repo(str(tmp_path))
        assert "summary" in result
        assert "dead_code" in result
        assert "duplicates" in result
        assert "god_files" in result
        assert "dep_graph" in result


def test_binary_file_skipped():
    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = Path(tmp)
        create_fake_repo(tmp_path)
        from reforge_mcp.tools.scan import scan_repo
        result = scan_repo(str(tmp_path))
        processed = [f for f in result.get("summary", {}).get("files_scanned", []) if f.endswith(".bin")]
        assert len(processed) == 0


def test_duplicates_detected():
    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = Path(tmp)
        create_fake_repo(tmp_path)
        from reforge_mcp.tools.scan import scan_repo
        result = scan_repo(str(tmp_path))
        assert len(result["duplicates"]) > 0


def test_summary_totals():
    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = Path(tmp)
        create_fake_repo(tmp_path)
        from reforge_mcp.tools.scan import scan_repo
        result = scan_repo(str(tmp_path))
        assert result["summary"]["total_files"] > 0
        assert result["summary"]["total_lines"] > 0


def test_dep_graph_structure():
    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = Path(tmp)
        create_fake_repo(tmp_path)
        from reforge_mcp.tools.scan import scan_repo
        result = scan_repo(str(tmp_path))
        assert "nodes" in result["dep_graph"]
        assert "edges" in result["dep_graph"]
        assert "circular" in result["dep_graph"]


def test_scan_ignore_key_is_honoured(tmp_path: Path) -> None:
    # "[scan] ignore" is what the shipped config and the README use; the reader
    # looked for a top-level "ignore_dirs", so the list was silently discarded
    from reforge_mcp.tools.scan import scan_repo

    (tmp_path / "keep.py").write_text("def kept():\n    return 1\n")
    generated = tmp_path / "generated"
    generated.mkdir()
    (generated / "noise.py").write_text("def generated_noise():\n    return 1\n")

    before = scan_repo(str(tmp_path))["summary"]["total_files"]

    (tmp_path / "reforge.toml").write_text('[scan]\nignore = ["generated"]\n')
    after = scan_repo(str(tmp_path))

    assert before == 2
    assert after["summary"]["total_files"] == 1
    assert "generated_noise" not in {d["symbol"] for d in after["dead_code"]}


def test_unsupported_source_files_are_counted(tmp_path: Path) -> None:
    # a partial scan must not read as a verdict on the whole repository
    from reforge_mcp.tools.scan import scan_repo

    (tmp_path / "tool.py").write_text("def go():\n    return 1\n")
    (tmp_path / "Proto.kt").write_text("class A\n")
    (tmp_path / "link.cpp").write_text("int main(){}\n")
    (tmp_path / "protocol.h").write_text("#pragma once\n")

    summary = scan_repo(str(tmp_path))["summary"]

    assert summary["total_files"] == 1
    assert summary["unscanned_source_files"] == 3
    assert summary["unscanned_by_extension"] == {".kt": 1, ".cpp": 1, ".h": 1}


def test_ignored_directories_are_not_counted_as_unscanned(tmp_path: Path) -> None:
    from reforge_mcp.tools.scan import scan_repo

    (tmp_path / "tool.py").write_text("def go():\n    return 1\n")
    vendored = tmp_path / "node_modules"
    vendored.mkdir()
    (vendored / "junk.kt").write_text("class Junk\n")

    assert scan_repo(str(tmp_path))["summary"]["unscanned_source_files"] == 0


def test_non_source_files_are_not_counted_as_unscanned(tmp_path: Path) -> None:
    from reforge_mcp.tools.scan import scan_repo

    (tmp_path / "tool.py").write_text("def go():\n    return 1\n")
    (tmp_path / "README.md").write_text("# hi\n")
    (tmp_path / "data.json").write_text("{}\n")

    assert scan_repo(str(tmp_path))["summary"]["unscanned_source_files"] == 0
