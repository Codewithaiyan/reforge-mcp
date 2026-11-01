"""Regressions from the third validation sweep.

Repositories: prometheus, caddy, ktor, pydantic, nest, scrapy, svelte.
"""

import subprocess
from pathlib import Path

from reforge_mcp.scanner.dead_code import find_dead_code
from reforge_mcp.scanner.parser import get_adapter_for_file, parse_directory
from reforge_mcp.tools.scan import scan_repo


def _write(path: Path, body: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(body, encoding="utf-8")


def _commit(root: Path) -> None:
    subprocess.run(["git", "init", "-q", str(root)], check=True)
    subprocess.run(["git", "-C", str(root), "add", "-A"], check=True)
    subprocess.run(
        ["git", "-C", str(root), "-c", "user.email=t@t", "-c", "user.name=t",
         "commit", "-qm", "init"],
        check=True,
    )


def _edges(root: Path) -> set[tuple[str, str]]:
    graph = scan_repo(str(root))["dep_graph"]
    return {(Path(e["from"]).name, Path(e["to"]).name) for e in graph["edges"]}


# --- .mts and .cts are TypeScript --------------------------------------------


def test_mts_and_cts_are_scanned(tmp_path: Path) -> None:
    # nest has 79 .mts files; they were neither parsed nor counted as
    # unreadable, so coverage claimed 0.995 while they were invisible
    _write(tmp_path / "a.mts", "export function fromMts(): number {\n  return 1;\n}\n")
    _write(tmp_path / "b.cts", "export function fromCts(): number {\n  return 2;\n}\n")
    _commit(tmp_path)

    summary = scan_repo(str(tmp_path))["summary"]

    assert summary["total_files"] == 2
    assert summary["unscanned_source_files"] == 0
    assert "typescript" in summary["languages_detected"]


def test_an_mts_file_gets_the_typescript_adapter(tmp_path: Path) -> None:
    adapter = get_adapter_for_file(tmp_path / "x.mts")

    assert adapter is not None
    assert adapter.get_language_name() == "typescript"


# --- TypeScript decorators and heritage --------------------------------------


NEST_STYLE = """@Scalar('Date')
export class DateScalar implements CustomScalar<number, Date> {
  @SubscribeMessage('push')
  onPush(data: string) {
    return helper();
  }

  parseValue(value: any) {
    return new Date(value);
  }
}

export function helper(): number {
  return 1;
}

export function nobodyCallsThis(): number {
  return 2;
}
"""


def test_a_decorated_method_is_not_dead_code(tmp_path: Path) -> None:
    # TypeScript attaches a decorator as a preceding sibling, not a child, so
    # a @SubscribeMessage handler looked like a plain method: nest reported
    # 422 dead functions, most of them decorated handlers
    _write(tmp_path / "scalar.ts", NEST_STYLE)
    _commit(tmp_path)

    dead = {d.symbol for d in find_dead_code(parse_directory(tmp_path, tmp_path))}

    assert "onPush" not in dead


def test_a_method_of_a_class_implementing_an_external_interface_is_exempt(
    tmp_path: Path,
) -> None:
    # parseValue is reached through CustomScalar, declared outside this repo
    _write(tmp_path / "scalar.ts", NEST_STYLE)
    _commit(tmp_path)

    dead = {d.symbol for d in find_dead_code(parse_directory(tmp_path, tmp_path))}

    assert "parseValue" not in dead


def test_an_undecorated_unused_function_is_still_reported(tmp_path: Path) -> None:
    _write(tmp_path / "scalar.ts", NEST_STYLE)
    _commit(tmp_path)

    dead = {d.symbol for d in find_dead_code(parse_directory(tmp_path, tmp_path))}

    assert "nobodyCallsThis" in dead
    assert "helper" not in dead


def test_the_implements_clause_is_recorded_as_a_base(tmp_path: Path) -> None:
    _write(tmp_path / "scalar.ts", NEST_STYLE)

    result = parse_directory(tmp_path, tmp_path)[0]

    assert result.classes[0].bases == ("CustomScalar",)


# --- absolute intra-repo Python imports --------------------------------------


def test_an_absolute_import_of_this_repos_package_resolves(tmp_path: Path) -> None:
    # scrapy imports scrapy.utils.misc from inside scrapy/, which resolved to
    # nothing: 29 edges for 540 files. django's graph was eight times too sparse.
    _write(tmp_path / "scrapy" / "__init__.py", "")
    _write(tmp_path / "scrapy" / "utils" / "__init__.py", "")
    _write(tmp_path / "scrapy" / "utils" / "misc.py", "def helper():\n    return 1\n")
    _write(
        tmp_path / "scrapy" / "core" / "__init__.py",
        "",
    )
    _write(
        tmp_path / "scrapy" / "core" / "engine.py",
        "from scrapy.utils.misc import helper\n\n\ndef run():\n    return helper()\n",
    )
    _commit(tmp_path)

    assert ("engine.py", "misc.py") in _edges(tmp_path)


def test_a_src_layout_resolves_too(tmp_path: Path) -> None:
    _write(tmp_path / "src" / "mypkg" / "__init__.py", "")
    _write(tmp_path / "src" / "mypkg" / "util.py", "def helper():\n    return 1\n")
    _write(
        tmp_path / "tests" / "test_util.py",
        "from mypkg.util import helper\n\n\ndef test_it():\n    assert helper() == 1\n",
    )
    _commit(tmp_path)

    assert ("test_util.py", "util.py") in _edges(tmp_path)


def test_a_third_party_import_does_not_resolve_to_a_nested_module(
    tmp_path: Path,
) -> None:
    # R31 must survive: "from git import Repo" inside a package is installed
    # GitPython, not the git.py sitting next to it
    _write(tmp_path / "pkg" / "__init__.py", "")
    _write(tmp_path / "pkg" / "git.py", "def commit():\n    return 1\n")
    _write(tmp_path / "pkg" / "scan.py", "from git import Repo\n\nRepo('.')\n")
    _commit(tmp_path)

    assert ("scan.py", "git.py") not in _edges(tmp_path)
