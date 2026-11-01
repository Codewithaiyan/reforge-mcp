"""Regressions from the second validation sweep.

Repositories: vuejs/core, colinhacks/zod, gin-gonic/gin, android/nowinandroid,
tiangolo/fastapi, django/django, facebook/react.
"""

import subprocess
from pathlib import Path

from reforge_mcp.scanner.dead_code import find_dead_code
from reforge_mcp.scanner.duplicates import find_duplicates
from reforge_mcp.scanner.parser import parse_directory
from reforge_mcp.tools.scan import scan_repo
from reforge_mcp.utils.paths import looks_like_test_path


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


# --- R54: TypeScript imports the path it will emit -------------------------


def test_a_js_import_resolves_to_its_ts_source(tmp_path: Path) -> None:
    # zod writes `from "../core/util.js"` for a file that is util.ts; it
    # resolved 2 of 1290 imports before this
    _write(tmp_path / "core" / "util.ts", "export function helper(): number {\n  return 1;\n}\n")
    _write(
        tmp_path / "schema" / "parse.ts",
        'import { helper } from "../core/util.js";\n\nexport const n = helper();\n',
    )
    _commit(tmp_path)

    assert ("parse.ts", "util.ts") in _edges(tmp_path)


def test_an_extensionless_import_resolves_to_a_declaration_file(tmp_path: Path) -> None:
    # vue core's dts-test package imports "./utils" where the file is utils.d.ts
    _write(tmp_path / "dts" / "utils.d.ts", "export declare function describe(): void;\n")
    _write(tmp_path / "dts" / "main.ts", 'import { describe } from "./utils";\n')
    _commit(tmp_path)

    assert ("main.ts", "utils.d.ts") in _edges(tmp_path)


# --- R56: an asset import is not a resolver bug ----------------------------


def test_a_relative_asset_import_is_not_counted_as_unresolved(tmp_path: Path) -> None:
    # 35 of vue core's 54 "unresolved" were .vue, .json and dist paths, which
    # made the number useless as a signal that the resolver is broken
    _write(
        tmp_path / "app.js",
        "import styles from './app.css';\n"
        "import data from './package.json';\n"
        "import Widget from './Widget.vue';\n",
    )
    _commit(tmp_path)

    graph = scan_repo(str(tmp_path))["dep_graph"]

    assert graph["unresolved_relative_imports"] == 0
    assert graph["external_imports"] == 3


def test_a_missing_relative_source_import_is_still_counted(tmp_path: Path) -> None:
    _write(tmp_path / "app.js", "import { gone } from './gone.js';\n")
    _commit(tmp_path)

    assert scan_repo(str(tmp_path))["dep_graph"]["unresolved_relative_imports"] == 1


# --- R57: vendored directories are not this repo's code --------------------


def test_a_vendored_directory_is_not_scanned(tmp_path: Path) -> None:
    # django commits its admin JS vendor tree; one bundled file there produced
    # 532 unresolved imports and a pile of findings in third-party code
    _write(tmp_path / "app" / "main.py", "def go():\n    return 1\n")
    _write(tmp_path / "vendor" / "lib.py", "def vendored_orphan():\n    return 2\n")
    _write(tmp_path / "third_party" / "other.py", "def also_vendored():\n    return 3\n")
    _commit(tmp_path)

    report = scan_repo(str(tmp_path))
    dead = {d["symbol"] for d in report["dead_code"]}

    assert report["summary"]["total_files"] == 1
    assert "vendored_orphan" not in dead
    assert "also_vendored" not in dead


# --- R58: Go dead-code exemptions ------------------------------------------


def test_go_init_and_methods_are_not_dead_code(tmp_path: Path) -> None:
    # gin declares 15 init() functions, all reported dead; the other 20
    # findings were methods satisfying stdlib and protobuf interfaces
    _write(
        tmp_path / "main.go",
        "package main\n"
        "\n"
        "type Payload struct{}\n"
        "\n"
        "func init() {\n"
        "\tsetup()\n"
        "}\n"
        "\n"
        "func setup() {}\n"
        "\n"
        "func (p Payload) MarshalJSON() ([]byte, error) {\n"
        "\treturn nil, nil\n"
        "}\n"
        "\n"
        "func unusedPlainFunction() int {\n"
        "\treturn 1\n"
        "}\n",
    )
    _commit(tmp_path)

    dead = {d.symbol for d in find_dead_code(parse_directory(tmp_path, tmp_path))}

    assert "init" not in dead
    assert "MarshalJSON" not in dead
    # a plain function with no receiver is still reportable
    assert "unusedPlainFunction" in dead


# --- R59: duplication among tests is expected ------------------------------


def test_a_duplicate_group_entirely_in_tests_is_not_reported(tmp_path: Path) -> None:
    body = "def helper():\n    value = 1\n    return value + 1\n"
    _write(tmp_path / "tests" / "test_one.py", body)
    _write(tmp_path / "tests" / "test_two.py", body)
    _commit(tmp_path)

    assert find_duplicates(parse_directory(tmp_path, tmp_path)) == []


def test_a_duplicate_shared_between_a_test_and_the_product_is_reported(
    tmp_path: Path,
) -> None:
    body = "def helper():\n    value = 1\n    return value + 1\n"
    _write(tmp_path / "src" / "app.py", body)
    _write(tmp_path / "tests" / "test_app.py", body)
    _commit(tmp_path)

    assert len(find_duplicates(parse_directory(tmp_path, tmp_path))) == 1


def test_kotlin_multiplatform_test_directories_are_recognised() -> None:
    # okhttp keeps tests in src/jvmTest and src/commonTest, which is why
    # filtering on a directory named exactly "test" barely helped it
    assert looks_like_test_path("okhttp/src/jvmTest/kotlin/okhttp3/CacheTest.kt")
    assert looks_like_test_path("okhttp/src/commonTest/kotlin/Thing.kt")
    assert looks_like_test_path("app/src/androidTest/java/Example.kt")
    # a directory that merely ends in the letters "test"
    assert not looks_like_test_path("pkg/latest/config.py")
