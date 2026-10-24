"""Tests for dependency graph construction and cycle detection."""

from pathlib import Path

from reforge_mcp.tools.scan import scan_repo


def graph(tmp_path: Path) -> dict:
    return scan_repo(str(tmp_path))["dep_graph"]


def edge_names(g: dict) -> set[tuple[str, str]]:
    return {(Path(e["from"]).name, Path(e["to"]).name) for e in g["edges"]}


def test_sibling_import_becomes_an_edge(tmp_path: Path) -> None:
    (tmp_path / "helpers.py").write_text("def helper():\n    return 1\n")
    (tmp_path / "app.py").write_text("from helpers import helper\n\nhelper()\n")

    assert ("app.py", "helpers.py") in edge_names(graph(tmp_path))


def test_relative_import_becomes_an_edge(tmp_path: Path) -> None:
    pkg = tmp_path / "pkg"
    (pkg / "inner").mkdir(parents=True)
    (pkg / "util.py").write_text("def helper():\n    return 1\n")
    (pkg / "inner" / "use.py").write_text("from ..util import helper\n\nhelper()\n")

    assert ("use.py", "util.py") in edge_names(graph(tmp_path))


def test_package_import_resolves_to_init(tmp_path: Path) -> None:
    pkg = tmp_path / "pkg"
    pkg.mkdir()
    (pkg / "__init__.py").write_text("def helper():\n    return 1\n")
    (tmp_path / "app.py").write_text("from pkg import helper\n\nhelper()\n")

    assert ("app.py", "__init__.py") in edge_names(graph(tmp_path))


def test_external_import_is_not_an_edge(tmp_path: Path) -> None:
    (tmp_path / "app.py").write_text("from pathlib import Path\n\nPath('.')\n")

    assert graph(tmp_path)["edges"] == []


def test_two_file_cycle_is_detected(tmp_path: Path) -> None:
    (tmp_path / "a.py").write_text("from b import beta\n\n\ndef alpha():\n    return beta()\n")
    (tmp_path / "b.py").write_text("from a import alpha\n\n\ndef beta():\n    return alpha()\n")

    circular = graph(tmp_path)["circular"]

    assert circular, "an a -> b -> a import cycle must be reported"
    assert {Path(p).name for p in circular[0]} == {"a.py", "b.py"}


def test_acyclic_repo_reports_no_cycles(tmp_path: Path) -> None:
    (tmp_path / "a.py").write_text("def alpha():\n    return 1\n")
    (tmp_path / "b.py").write_text("from a import alpha\n\nalpha()\n")

    assert graph(tmp_path)["circular"] == []


def test_repeated_imports_from_one_module_are_one_edge(tmp_path: Path) -> None:
    (tmp_path / "util.py").write_text("def one():\n    return 1\n\n\ndef two():\n    return 2\n")
    (tmp_path / "app.py").write_text(
        "from util import one\nfrom util import two\n\none()\ntwo()\n"
    )

    assert len(graph(tmp_path)["edges"]) == 1


def test_bare_import_becomes_an_edge(tmp_path: Path) -> None:
    # "import sibling" carries its module in names, not from_module
    (tmp_path / "helpers.py").write_text("def helper():\n    return 1\n")
    (tmp_path / "app.py").write_text("import helpers\n\nhelpers.helper()\n")

    assert ("app.py", "helpers.py") in edge_names(graph(tmp_path))


def test_bare_import_cycle_is_detected(tmp_path: Path) -> None:
    # the commonest Python cycle: two modules importing each other by name
    (tmp_path / "a.py").write_text("import b\n\n\ndef alpha():\n    return b.beta()\n")
    (tmp_path / "b.py").write_text("import a\n\n\ndef beta():\n    return a.alpha()\n")

    circular = graph(tmp_path)["circular"]

    assert circular, "an import-by-name cycle must be reported"
    assert {Path(p).name for p in circular[0]} == {"a.py", "b.py"}


def test_dotted_bare_import_resolves(tmp_path: Path) -> None:
    pkg = tmp_path / "pkg"
    pkg.mkdir()
    (pkg / "__init__.py").write_text("")
    (pkg / "util.py").write_text("def helper():\n    return 1\n")
    (tmp_path / "app.py").write_text("import pkg.util\n\npkg.util.helper()\n")

    assert ("app.py", "util.py") in edge_names(graph(tmp_path))


def test_multiple_bare_imports_on_one_line_both_resolve(tmp_path: Path) -> None:
    # "import a, b" must not be read as the single module "a.b"
    (tmp_path / "a.py").write_text("def alpha():\n    return 1\n")
    (tmp_path / "b.py").write_text("def beta():\n    return 2\n")
    (tmp_path / "app.py").write_text("import a, b\n\na.alpha()\nb.beta()\n")

    edges = edge_names(graph(tmp_path))

    assert ("app.py", "a.py") in edges
    assert ("app.py", "b.py") in edges
