"""Tests for the tree-sitter parser adapters."""

from pathlib import Path

from reforge_mcp.scanner.parser import parse_file

DECORATED = '''\
import functools


def plain():
    return 1


@functools.cache
def cached():
    return 2


@app.route("/health")
def health():
    return 3


class Service:

    @property
    def name(self):
        return "svc"

    @staticmethod
    def helper():
        return 4
'''


def test_decorated_functions_are_not_counted_twice(tmp_path: Path) -> None:
    f = tmp_path / "mod.py"
    f.write_text(DECORATED)

    result = parse_file(f, tmp_path)
    names = sorted(fn.name for fn in result.functions)

    assert names == ["cached", "health", "helper", "name", "plain"]


def test_each_function_is_reported_once_per_definition(tmp_path: Path) -> None:
    f = tmp_path / "mod.py"
    # the dedupe keys off node identity, so two same-named defs must both survive
    f.write_text("@deco\ndef go():\n    return 1\n\n\nclass K:\n    @deco\n    def go(self):\n        return 2\n")

    result = parse_file(f, tmp_path)

    assert [fn.name for fn in result.functions] == ["go", "go"]
    assert len({fn.start_line for fn in result.functions}) == 2
