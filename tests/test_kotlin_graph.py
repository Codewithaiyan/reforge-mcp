"""Tests for resolving Kotlin's package imports into dependency edges.

Before 0.3.1 a Kotlin repository reported no edges at all. okhttp showed 0
edges, 6,869 external imports and 0 unresolved relative imports, which by the
R32 diagnostic reads as "this code has no internal imports" - about a library
that imports its own packages on nearly every file.
"""

from pathlib import Path

from reforge_mcp.tools.scan import get_health_score, scan_repo


def _write(path: Path, body: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(body, encoding="utf-8")


def _graph(root: Path) -> dict:
    return scan_repo(str(root))["dep_graph"]


def _edge_names(graph: dict) -> set[tuple[str, str]]:
    return {(Path(e["from"]).name, Path(e["to"]).name) for e in graph["edges"]}


def _init_repo(tmp_path: Path) -> None:
    """A git repo, since only tracked files are analysed (R30)."""
    import subprocess

    subprocess.run(["git", "init", "-q", str(tmp_path)], check=True)
    subprocess.run(["git", "-C", str(tmp_path), "add", "-A"], check=True)
    subprocess.run(
        ["git", "-C", str(tmp_path), "-c", "user.email=t@t", "-c", "user.name=t",
         "commit", "-qm", "init"],
        check=True,
    )


def test_a_kotlin_package_import_becomes_an_edge(tmp_path: Path) -> None:
    _write(
        tmp_path / "src" / "platform" / "Platform.kt",
        "package app.platform\n\nclass Platform {\n    fun name(): String = \"x\"\n}\n",
    )
    _write(
        tmp_path / "src" / "Client.kt",
        "package app\n\nimport app.platform.Platform\n\n"
        "class Client {\n    fun go(): String = Platform().name()\n}\n",
    )
    _init_repo(tmp_path)

    assert ("Client.kt", "Platform.kt") in _edge_names(_graph(tmp_path))


def test_a_star_import_depends_on_every_file_in_the_package(tmp_path: Path) -> None:
    _write(tmp_path / "src" / "util" / "One.kt", "package app.util\n\nfun one(): Int = 1\n")
    _write(tmp_path / "src" / "util" / "Two.kt", "package app.util\n\nfun two(): Int = 2\n")
    _write(
        tmp_path / "src" / "Main.kt",
        "package app\n\nimport app.util.*\n\nfun main() {\n    println(one() + two())\n}\n",
    )
    _init_repo(tmp_path)

    edges = _edge_names(_graph(tmp_path))

    assert ("Main.kt", "One.kt") in edges
    assert ("Main.kt", "Two.kt") in edges


def test_importing_a_member_resolves_to_its_declaring_file(tmp_path: Path) -> None:
    # `import app.config.Config.DEFAULT` names something inside Config
    _write(
        tmp_path / "src" / "config" / "Config.kt",
        "package app.config\n\nobject Config {\n    const val DEFAULT = 1\n}\n",
    )
    _write(
        tmp_path / "src" / "Use.kt",
        "package app\n\nimport app.config.Config.DEFAULT\n\nfun f(): Int = DEFAULT\n",
    )
    _init_repo(tmp_path)

    assert ("Use.kt", "Config.kt") in _edge_names(_graph(tmp_path))


def test_an_import_from_outside_the_repo_stays_external(tmp_path: Path) -> None:
    _write(
        tmp_path / "src" / "Main.kt",
        "package app\n\nimport android.os.Bundle\nimport kotlin.math.roundToInt\n\n"
        "fun f(b: Bundle): Int = 1.4.roundToInt()\n",
    )
    _init_repo(tmp_path)

    graph = _graph(tmp_path)

    assert graph["edges"] == []
    assert graph["external_imports"] == 2
    assert graph["unresolved_relative_imports"] == 0


def test_a_python_import_cannot_match_a_kotlin_package(tmp_path: Path) -> None:
    # the package index is only consulted for files that declare a package
    _write(tmp_path / "src" / "app" / "Platform.kt", "package app\n\nclass Platform\n")
    _write(tmp_path / "platform.py", "def helper():\n    return 1\n")
    _write(tmp_path / "main.py", "import app.Platform\n")
    _init_repo(tmp_path)

    assert ("main.py", "Platform.kt") not in _edge_names(_graph(tmp_path))


def test_a_kotlin_cycle_does_not_cost_health_points(tmp_path: Path) -> None:
    """Kotlin compiles a module as a whole, so circular file imports are normal.

    okhttp has 64 of them and was losing the full 20-point cycle penalty for
    writing ordinary Kotlin.
    """
    _write(
        tmp_path / "src" / "A.kt",
        "package app.a\n\nimport app.b.Beta\n\nclass Alpha {\n    fun f() = Beta()\n}\n",
    )
    _write(
        tmp_path / "src" / "B.kt",
        "package app.b\n\nimport app.a.Alpha\n\nclass Beta {\n    fun g() = Alpha()\n}\n",
    )
    _init_repo(tmp_path)

    graph = _graph(tmp_path)
    health = get_health_score(str(tmp_path), state_path=None)

    # the cycle is still reported, it just is not a defect in this language
    assert graph["circular"]
    assert health["breakdown"]["circular_count"] == 0


def test_a_python_cycle_still_costs_health_points(tmp_path: Path) -> None:
    _write(tmp_path / "a.py", "import b\n\n\ndef f():\n    return b.g()\n")
    _write(tmp_path / "b.py", "import a\n\n\ndef g():\n    return a.f()\n")
    _init_repo(tmp_path)

    health = get_health_score(str(tmp_path), state_path=None)

    assert health["breakdown"]["circular_count"] >= 1
