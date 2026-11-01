"""The MCP wire form of a scan has to fit in a caller's context.

A 2,500-file repository produced a 0.74 MB report and django 1.18 MB - roughly
180-295k tokens, more than a caller can spend on one tool result, so pointing a
model at a large repository failed.

`scan_repo()` still returns everything, because `get_health_score`,
`score_risk` and `infer_architecture` read it in full. Only `cap_report` trims,
and only the MCP wrapper calls it.
"""

import json
import subprocess
from pathlib import Path

from reforge_mcp import server
from reforge_mcp.tools.scan import (
    _MAX_DUPLICATE_LOCATIONS,
    _MAX_ITEMS,
    cap_report,
    get_health_score,
    scan_repo,
)


def _commit(root: Path) -> None:
    subprocess.run(["git", "init", "-q", str(root)], check=True)
    subprocess.run(["git", "-C", str(root), "add", "-A"], check=True)
    subprocess.run(
        ["git", "-C", str(root), "-c", "user.email=t@t", "-c", "user.name=t",
         "commit", "-qm", "init"],
        check=True,
    )


def _big_repo(tmp_path: Path, files: int) -> Path:
    """Files that import their neighbour, so nodes and edges both exceed the cap."""
    for i in range(files):
        body = f"def f{i}():\n    return {i}\n"
        if i:
            body = f"import m{i - 1}\n\n\n" + body + f"\n\ndef g{i}():\n    return m{i - 1}.f{i - 1}()\n"
        (tmp_path / f"m{i}.py").write_text(body, encoding="utf-8")
    _commit(tmp_path)
    return tmp_path


def test_a_small_repo_is_returned_whole(tmp_path: Path) -> None:
    (tmp_path / "a.py").write_text("def f():\n    return 1\n", encoding="utf-8")
    _commit(tmp_path)

    wire = server.scan_repo_tool(str(tmp_path))

    assert "truncated" not in wire
    assert "edges_total" not in wire["dep_graph"]


def test_long_lists_are_capped_and_their_real_lengths_reported(tmp_path: Path) -> None:
    _big_repo(tmp_path, _MAX_ITEMS + 40)

    wire = server.scan_repo_tool(str(tmp_path))
    graph = wire["dep_graph"]

    assert len(graph["nodes"]) == _MAX_ITEMS
    assert graph["nodes_total"] == _MAX_ITEMS + 40
    assert wire["truncated"]["nodes"] == _MAX_ITEMS + 40
    # the exact counts survive even though the lists do not
    assert len(graph["edges"]) <= _MAX_ITEMS


def test_the_summary_is_never_trimmed(tmp_path: Path) -> None:
    _big_repo(tmp_path, _MAX_ITEMS + 40)

    wire = server.scan_repo_tool(str(tmp_path))

    assert wire["summary"] == scan_repo(str(tmp_path))["summary"]


def test_a_fat_duplicate_group_keeps_a_sample_and_the_count(tmp_path: Path) -> None:
    # one ktor group held 913 locations: 189 KB of a 289 KB response
    body = "def helper():\n    value = 1\n    return value + 1\n"
    for i in range(_MAX_DUPLICATE_LOCATIONS + 15):
        (tmp_path / f"d{i}.py").write_text(body, encoding="utf-8")
    _commit(tmp_path)

    wire = server.scan_repo_tool(str(tmp_path))
    group = wire["duplicates"][0]

    assert len(group["locations"]) == _MAX_DUPLICATE_LOCATIONS
    assert group["locations_total"] == _MAX_DUPLICATE_LOCATIONS + 15


def test_capping_does_not_modify_the_report_it_was_given(tmp_path: Path) -> None:
    _big_repo(tmp_path, _MAX_ITEMS + 40)
    report = scan_repo(str(tmp_path))
    before = json.dumps(report)

    cap_report(report)

    assert json.dumps(report) == before


def test_the_health_score_is_unaffected_by_capping(tmp_path: Path) -> None:
    # it calls scan_repo directly, so a ratio over findings stays exact
    _big_repo(tmp_path, _MAX_ITEMS + 40)

    score = get_health_score(str(tmp_path), state_path=None)["score"]
    server.scan_repo_tool(str(tmp_path))

    assert get_health_score(str(tmp_path), state_path=None)["score"] == score


def test_reference_data_never_reaches_the_wire(tmp_path: Path) -> None:
    # references_by_file is for score_risk and is enormous
    (tmp_path / "a.py").write_text("def f():\n    return 1\n", encoding="utf-8")
    _commit(tmp_path)

    report = scan_repo(str(tmp_path), include_references=True)
    assert "references_by_file" in report

    assert "references_by_file" not in cap_report(report)
    assert "lines_by_file" not in cap_report(report)
