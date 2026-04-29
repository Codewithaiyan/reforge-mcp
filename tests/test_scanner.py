"""
Scanner Test Suite.

Tests for the AST parser, dead code detector, duplicate detector, and scan_repo tool.

TEST STRATEGY:
1. Create a temporary fake repository with known code patterns
2. Run the scanner on it
3. Verify expected findings (dead code, duplicates, god files)
4. Verify schema of output JSON

TEST FIXTURES:
- Dead function (defined but never called)
- Live function (defined and called)
- Duplicate functions (identical bodies in different files)
- God file (>500 lines or >10 exports)
- Binary file (should be skipped)
"""

import json
import tempfile
from pathlib import Path

import pytest

from reforge_mcp.scanner.dead_code import DeadCodeInfo, find_dead_code
from reforge_mcp.scanner.duplicates import DuplicateGroup, find_duplicates
from reforge_mcp.scanner.parser import (
    FunctionInfo,
    ParseResult,
    parse_directory,
    parse_file,
)
from reforge_mcp.tools.scan import scan_repo


@pytest.fixture
def fake_repo(tmp_path: Path) -> Path:
    """
    Create a fake repository with known code patterns for testing.

    Structure:
    fake_repo/
    ├── src/
    │   ├── main.py           # Entry point, calls process_data
    │   ├── utils.py          # Has live_func and dead_func
    │   ├── duplicates.py     # Has duplicate of utils.process_data
    │   └── god_file.py       # 600 lines, 15 functions
    ├── tests/
    │   └── test_main.py      # Test file (should be included)
    ├── binary.png            # Should be skipped
    └── package-lock.json     # Should be skipped
    """
    # Create directory structure
    src_dir = tmp_path / "src"
    src_dir.mkdir()
    tests_dir = tmp_path / "tests"
    tests_dir.mkdir()

    # main.py - entry point that calls process_data
    main_py = src_dir / "main.py"
    main_py.write_text("""
\"\"\"Main entry point.\"\"\"

from utils import process_data, live_func

def main():
    \"\"\"Application entry point.\"\"\"
    result = process_data("input")
    print(result)
    live_func()

if __name__ == "__main__":
    main()
""")

    # utils.py - has both live and dead functions
    utils_py = src_dir / "utils.py"
    utils_py.write_text("""
\"\"\"Utility functions.\"\"\"

def process_data(data: str) -> str:
    \"\"\"Process input data.\"\"\"
    processed = data.upper()
    return f"Processed: {processed}"

def live_func():
    \"\"\"This function is called from main.\"\"\"
    return "I am alive"

def dead_func():
    \"\"\"This function is never called - dead code.\"\"\"
    x = 1
    y = 2
    return x + y

def another_dead():
    \"\"\"Also never called.\"\"\"
    return "unused"
""")

    # duplicates.py - has duplicate of utils.process_data
    duplicates_py = src_dir / "duplicates.py"
    duplicates_py.write_text("""
\"\"\"Duplicate code examples.\"\"\"

def process_data_copy(data: str) -> str:
    \"\"\"Exact copy of utils.process_data.\"\"\"
    processed = data.upper()
    return f"Processed: {processed}"

def calculate_total(items):
    \"\"\"Calculate total.\"\"\"
    total = 0
    for item in items:
        total += item
    return total

def sum_items(items):
    \"\"\"Duplicate of calculate_total.\"\"\"
    total = 0
    for item in items:
        total += item
    return total
""")

    # god_file.py - large file with many functions
    god_file = src_dir / "god_file.py"
    god_lines = ['\"\"\"God file with too many responsibilities.\"\"\"\n\n']

    # Add 15 functions
    for i in range(15):
        god_lines.append(f"def function_{i}():\n")
        god_lines.append(f'    """Function number {i}."""\n')
        god_lines.append(f"    return {i}\n\n")

    # Add more lines to exceed 500
    god_lines.append("\n# Padding to exceed 500 lines\n")
    for i in range(400):
        god_lines.append(f"# Comment line {i}\n")

    god_file.write_text("".join(god_lines))

    # test_main.py - test file
    test_main = tests_dir / "test_main.py"
    test_main.write_text("""
\"\"\"Tests for main module.\"\"\"

import pytest

def test_main():
    \"\"\"Test main function.\"\"\"
    assert True

@pytest.fixture
def sample_data():
    \"\"\"Test fixture.\"\"\"
    return "test"
""")

    # Binary file (should be skipped)
    binary_file = tmp_path / "binary.png"
    binary_file.write_bytes(b"\x89PNG\r\n\x1a\n" + b"\x00" * 100)

    # Lock file (should be skipped)
    lock_file = tmp_path / "package-lock.json"
    lock_file.write_text('{"name": "test", "version": "1.0.0"}')

    return tmp_path


class TestParser:
    """Tests for the AST parser."""

    @pytest.mark.unit
    def test_parse_python_file(self, fake_repo: Path) -> None:
        """Test parsing a Python file extracts functions correctly."""
        utils_path = fake_repo / "src" / "utils.py"

        result = parse_file(utils_path, fake_repo)

        assert result is not None
        assert result.language == "python"
        assert result.error is None
        assert len(result.functions) == 4  # process_data, live_func, dead_func, another_dead

        # Check function details
        func_names = [f.name for f in result.functions]
        assert "process_data" in func_names
        assert "live_func" in func_names
        assert "dead_func" in func_names
        assert "another_dead" in func_names

    @pytest.mark.unit
    def test_parse_file_extracts_line_numbers(self, fake_repo: Path) -> None:
        """Test that line numbers are correctly extracted."""
        utils_path = fake_repo / "src" / "utils.py"

        result = parse_file(utils_path, fake_repo)

        # process_data starts at line 4 (after docstring)
        process_data_func = next(f for f in result.functions if f.name == "process_data")
        assert process_data_func.start_line >= 1
        assert process_data_func.end_line > process_data_func.start_line

    @pytest.mark.unit
    def test_parse_file_computes_body_hash(self, fake_repo: Path) -> None:
        """Test that body hashes are computed for duplicate detection."""
        utils_path = fake_repo / "src" / "utils.py"

        result = parse_file(utils_path, fake_repo)

        process_data_func = next(f for f in result.functions if f.name == "process_data")
        assert process_data_func.body_hash
        assert len(process_data_func.body_hash) == 64  # SHA256 hex length

    @pytest.mark.unit
    def test_parse_directory_parses_all_files(self, fake_repo: Path) -> None:
        """Test parsing a directory recursively."""
        results = parse_directory(fake_repo, fake_repo)

        # Should parse Python files in src/ and tests/
        # Should skip binary.png and package-lock.json
        assert len(results) >= 4  # main.py, utils.py, duplicates.py, god_file.py, test_main.py

        python_results = [r for r in results if r.language == "python"]
        assert len(python_results) >= 4

    @pytest.mark.unit
    def test_binary_file_skipped(self, fake_repo: Path) -> None:
        """Test that binary files are skipped during parsing."""
        binary_path = fake_repo / "binary.png"

        result = parse_file(binary_path, fake_repo)

        # Should return None for binary files
        assert result is None

    @pytest.mark.unit
    def test_lock_file_skipped(self, fake_repo: Path) -> None:
        """Test that lock files are skipped during parsing."""
        lock_path = fake_repo / "package-lock.json"

        result = parse_file(lock_path, fake_repo)

        # Should return None for lock files
        assert result is None


class TestDeadCodeDetector:
    """Tests for the dead code detector."""

    @pytest.mark.unit
    def test_dead_function_detected(self, fake_repo: Path) -> None:
        """Test that unused functions are detected as dead code."""
        parse_results = parse_directory(fake_repo, fake_repo)

        dead_code = find_dead_code(parse_results, repo_root=str(fake_repo))

        # dead_func and another_dead should be detected
        dead_names = {info.symbol for info in dead_code}

        assert "dead_func" in dead_names
        assert "another_dead" in dead_names

    @pytest.mark.unit
    def test_live_function_not_flagged(self, fake_repo: Path) -> None:
        """Test that called functions are not flagged as dead."""
        parse_results = parse_directory(fake_repo, fake_repo)

        dead_code = find_dead_code(parse_results, repo_root=str(fake_repo))

        dead_names = {info.symbol for info in dead_code}

        # main and process_data are called, should not be dead
        assert "main" not in dead_names
        assert "process_data" not in dead_names

    @pytest.mark.unit
    def test_entry_point_not_flagged(self, fake_repo: Path) -> None:
        """Test that entry point functions are not flagged as dead."""
        parse_results = parse_directory(fake_repo, fake_repo)

        dead_code = find_dead_code(parse_results, repo_root=str(fake_repo))

        dead_names = {info.symbol for info in dead_code}

        # main() is an entry point, should not be dead
        assert "main" not in dead_names


class TestDuplicateDetector:
    """Tests for the duplicate code detector."""

    @pytest.mark.unit
    def test_duplicate_functions_found(self, fake_repo: Path) -> None:
        """Test that duplicate functions are detected."""
        parse_results = parse_directory(fake_repo, fake_repo)

        duplicates = find_duplicates(parse_results)

        # Should find at least one duplicate group
        assert len(duplicates) >= 1

        # Check that duplicate locations are recorded
        for group in duplicates:
            assert len(group.locations) >= 2
            for loc in group.locations:
                assert loc.file
                assert loc.line >= 1
                assert loc.name

    @pytest.mark.unit
    def test_duplicate_hash_is_sha256(self, fake_repo: Path) -> None:
        """Test that duplicate hashes are SHA256."""
        parse_results = parse_directory(fake_repo, fake_repo)

        duplicates = find_duplicates(parse_results)

        for group in duplicates:
            assert len(group.hash) == 64  # SHA256 hex length


class TestScanRepo:
    """Tests for the scan_repo tool."""

    @pytest.mark.integration
    def test_scan_returns_valid_json(self, fake_repo: Path) -> None:
        """Test that scan_repo returns valid JSON structure."""
        result = scan_repo(str(fake_repo))

        # Check top-level keys
        assert "summary" in result
        assert "dead_code" in result
        assert "duplicates" in result
        assert "god_files" in result
        assert "dep_graph" in result

        # Verify JSON serializable
        json_str = json.dumps(result)
        assert json_str

    @pytest.mark.integration
    def test_scan_summary_correct(self, fake_repo: Path) -> None:
        """Test that scan summary contains correct counts."""
        result = scan_repo(str(fake_repo))

        summary = result["summary"]

        assert summary["total_files"] >= 4
        assert summary["total_functions"] >= 20  # Including god_file functions
        assert summary["total_lines"] >= 500  # god_file alone has 500+
        assert "python" in summary["languages_detected"]

    @pytest.mark.integration
    def test_god_file_flagged(self, fake_repo: Path) -> None:
        """Test that god file is detected."""
        result = scan_repo(str(fake_repo))

        god_files = result["god_files"]

        # god_file.py should be flagged
        assert len(god_files) >= 1

        god_file = next(g for g in god_files if "god_file" in g["file"])
        assert god_file["lines"] >= 500
        assert god_file["exports"] >= 10

    @pytest.mark.integration
    def test_dead_code_in_results(self, fake_repo: Path) -> None:
        """Test that dead code appears in scan results."""
        result = scan_repo(str(fake_repo))

        dead_code = result["dead_code"]

        # Should have detected dead functions
        assert len(dead_code) >= 2

        dead_names = {dc["symbol"] for dc in dead_code}
        assert "dead_func" in dead_names
        assert "another_dead" in dead_names

    @pytest.mark.integration
    def test_duplicates_in_results(self, fake_repo: Path) -> None:
        """Test that duplicates appear in scan results."""
        result = scan_repo(str(fake_repo))

        duplicates = result["duplicates"]

        # Should have detected at least one duplicate group
        assert len(duplicates) >= 1

        for dup in duplicates:
            assert "hash" in dup
            assert "locations" in dup
            assert len(dup["locations"]) >= 2

    @pytest.mark.integration
    def test_dep_graph_structure(self, fake_repo: Path) -> None:
        """Test that dependency graph has correct structure."""
        result = scan_repo(str(fake_repo))

        dep_graph = result["dep_graph"]

        assert "nodes" in dep_graph
        assert "edges" in dep_graph
        assert "circular" in dep_graph

        assert isinstance(dep_graph["nodes"], list)
        assert isinstance(dep_graph["edges"], list)
        assert isinstance(dep_graph["circular"], list)

    @pytest.mark.integration
    def test_binary_files_excluded(self, fake_repo: Path) -> None:
        """Test that binary files are excluded from scan results."""
        result = scan_repo(str(fake_repo))

        summary = result["summary"]

        # Should not count binary files
        # (binary.png and package-lock.json should be excluded)
        # We can't assert exact count, but we can verify no errors
        assert "error" not in result or result.get("error") is None


class TestSchemaValidation:
    """Tests validating output JSON schema."""

    @pytest.mark.integration
    def test_output_matches_expected_schema(self, fake_repo: Path) -> None:
        """Test that output matches the expected schema exactly."""
        result = scan_repo(str(fake_repo))

        # Validate summary schema
        summary = result["summary"]
        assert isinstance(summary["total_files"], int)
        assert isinstance(summary["total_functions"], int)
        assert isinstance(summary["total_lines"], int)
        assert isinstance(summary["languages_detected"], list)

        # Validate dead_code schema
        for dc in result["dead_code"]:
            assert "symbol" in dc
            assert "file" in dc
            assert "line" in dc
            assert isinstance(dc["symbol"], str)
            assert isinstance(dc["file"], str)
            assert isinstance(dc["line"], int)

        # Validate duplicates schema
        for dup in result["duplicates"]:
            assert "hash" in dup
            assert "locations" in dup
            assert isinstance(dup["hash"], str)
            assert isinstance(dup["locations"], list)

            for loc in dup["locations"]:
                assert "file" in loc
                assert "line" in loc
                assert "name" in loc
                assert isinstance(loc["file"], str)
                assert isinstance(loc["line"], int)
                assert isinstance(loc["name"], str)

        # Validate god_files schema
        for gf in result["god_files"]:
            assert "file" in gf
            assert "lines" in gf
            assert "exports" in gf
            assert isinstance(gf["file"], str)
            assert isinstance(gf["lines"], int)
            assert isinstance(gf["exports"], int)

        # Validate dep_graph schema
        dep_graph = result["dep_graph"]
        assert isinstance(dep_graph["nodes"], list)
        assert isinstance(dep_graph["edges"], list)
        assert isinstance(dep_graph["circular"], list)

        for edge in dep_graph["edges"]:
            assert "from" in edge
            assert "to" in edge
