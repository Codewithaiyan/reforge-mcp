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


def test_decorators_are_extracted(tmp_path: Path) -> None:
    f = tmp_path / "mod.py"
    f.write_text(DECORATED)

    by_name = {fn.name: fn.decorators for fn in parse_file(f, tmp_path).functions}

    assert by_name["plain"] == ()
    assert by_name["cached"] == ("functools.cache",)
    assert by_name["name"] == ("property",)
    assert by_name["helper"] == ("staticmethod",)
    # a decorator with arguments keeps only the dotted name
    assert by_name["health"] == ("app.route",)


def test_stacked_decorators_are_all_extracted(tmp_path: Path) -> None:
    f = tmp_path / "mod.py"
    f.write_text('@app.route("/x")\n@auth.required\ndef view():\n    return 1\n')

    fn = parse_file(f, tmp_path).functions[0]

    assert fn.decorators == ("app.route", "auth.required")


def test_decorated_function_is_a_framework_entry_point(tmp_path: Path) -> None:
    # the guard that stops dead-code detection reporting framework callbacks
    from reforge_mcp.scanner.dead_code import is_decorated_entry_point

    f = tmp_path / "mod.py"
    f.write_text(DECORATED)
    by_name = {fn.name: fn for fn in parse_file(f, tmp_path).functions}

    assert is_decorated_entry_point(by_name["health"]) is True
    assert is_decorated_entry_point(by_name["name"]) is True
    assert is_decorated_entry_point(by_name["plain"]) is False


def test_each_function_is_reported_once_per_definition(tmp_path: Path) -> None:
    f = tmp_path / "mod.py"
    # the dedupe keys off node identity, so two same-named defs must both survive
    f.write_text("@deco\ndef go():\n    return 1\n\n\nclass K:\n    @deco\n    def go(self):\n        return 2\n")

    result = parse_file(f, tmp_path)

    assert [fn.name for fn in result.functions] == ["go", "go"]
    assert len({fn.start_line for fn in result.functions}) == 2
