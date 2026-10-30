"""Tests for the TypeScript and Go adapters, neither of which ever worked.

Both failed to compile their own tree-sitter queries, so every .ts and .go file
returned a parse error. Found by scanning axios and spf13/cobra.
"""

from pathlib import Path

import pytest

from reforge_mcp.scanner.dead_code import find_dead_code
from reforge_mcp.scanner.parser import get_adapter_for_language, parse_directory

TS_SOURCE = """export class Client {
  send(path: string): number {
    return helper(path);
  }
}

export function helper(path: string): number {
  return path.length;
}

function unusedOne(): void {}
"""

GO_SOURCE = """package main

import (
\t"fmt"
\t"os"
)

type Config struct {
\tName string
}

func helper(c Config) string {
\treturn c.Name
}

func main() {
\tfmt.Println(helper(Config{Name: "x"}), os.Args)
}
"""

GO_TEST_SOURCE = """package main

import "testing"

func TestSomething(t *testing.T) {
\tt.Log("collected by name, never referenced")
}

func BenchmarkSomething(b *testing.B) {
\tb.Log("same")
}

func unusedHelper() int {
\treturn 1
}
"""


@pytest.mark.parametrize("language", ["python", "javascript", "typescript", "go", "kotlin"])
def test_every_adapter_can_compile_its_own_queries(language: str) -> None:
    # the whole defect: a query that cannot compile makes the adapter useless
    # for every file, and nothing reported it
    tiny = {
        "python": (b"class A:\n    def b(self):\n        return 1\n", "a.py"),
        "javascript": (b"class A { b() { return 1; } }\n", "a.js"),
        "typescript": (b"class A { b(): number { return 1; } }\n", "a.ts"),
        "go": (b"package main\n\ntype A struct{}\n\nfunc b() int { return 1 }\n", "a.go"),
        "kotlin": (b"class A {\n    fun b(): Int = 1\n}\n", "a.kt"),
    }[language]

    adapter = get_adapter_for_language(language)
    assert adapter is not None

    result = adapter.parse(tiny[0], tiny[1])

    assert result.error is None
    assert len(result.functions) >= 1


def test_typescript_classes_and_functions_are_extracted(tmp_path: Path) -> None:
    # a TypeScript class name is a type_identifier; asking for an identifier is
    # an impossible pattern and tree-sitter rejected the whole query
    (tmp_path / "client.ts").write_text(TS_SOURCE, encoding="utf-8")

    results = parse_directory(directory=tmp_path, repo_root=tmp_path)

    assert [r.error for r in results] == [None]
    result = results[0]
    assert [c.name for c in result.classes] == ["Client"]
    assert {f.name for f in result.functions} >= {"send", "helper", "unusedOne"}


def test_go_types_functions_and_imports_are_extracted(tmp_path: Path) -> None:
    (tmp_path / "main.go").write_text(GO_SOURCE, encoding="utf-8")

    results = parse_directory(directory=tmp_path, repo_root=tmp_path)

    assert [r.error for r in results] == [None]
    result = results[0]
    assert [c.name for c in result.classes] == ["Config"]
    assert {f.name for f in result.functions} == {"helper", "main"}
    # a grouped import nests the strings two levels below the declaration, so
    # walking its direct children found none of them
    assert {i.from_module for i in result.imports} == {"fmt", "os"}


def test_a_single_go_import_is_extracted(tmp_path: Path) -> None:
    (tmp_path / "one.go").write_text(
        'package main\n\nimport "strings"\n\nfunc f() int { return len(strings.Fields("a")) }\n',
        encoding="utf-8",
    )

    results = parse_directory(directory=tmp_path, repo_root=tmp_path)

    assert [i.from_module for i in results[0].imports] == ["strings"]


def test_go_test_functions_are_not_dead_code(tmp_path: Path) -> None:
    # Go's runner collects TestXxx and BenchmarkXxx by prefix; the exemption
    # only knew lowercase test_, so 311 of cobra's 595 functions were reported
    (tmp_path / "main_test.go").write_text(GO_TEST_SOURCE, encoding="utf-8")

    dead = {d.symbol for d in find_dead_code(parse_directory(tmp_path, tmp_path))}

    assert "TestSomething" not in dead
    assert "BenchmarkSomething" not in dead
    assert "unusedHelper" in dead
