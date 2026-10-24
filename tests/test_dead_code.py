"""Tests for dead code detection."""

from pathlib import Path

from reforge_mcp.scanner.dead_code import find_dead_code
from reforge_mcp.scanner.parser import parse_directory


def dead_symbols(tmp_path: Path, **files: str) -> set[str]:
    for name, source in files.items():
        (tmp_path / f"{name}.py").write_text(source)
    results = parse_directory(directory=tmp_path, repo_root=tmp_path)
    return {d.symbol for d in find_dead_code(results)}


def test_unreferenced_function_is_found(tmp_path: Path) -> None:
    found = dead_symbols(
        tmp_path,
        mod="def used():\n    return 1\n\n\ndef unused():\n    return 2\n",
        caller="from mod import used\n\nprint(used())\n",
    )

    assert found == {"unused"}


def test_definition_is_not_a_reference_to_itself(tmp_path: Path) -> None:
    # the old regex counted "def lonely(" as a call to lonely, so nothing was
    # ever reported dead
    found = dead_symbols(tmp_path, mod="def lonely():\n    return 1\n")

    assert found == {"lonely"}


def test_method_called_on_an_object_is_not_dead(tmp_path: Path) -> None:
    found = dead_symbols(
        tmp_path,
        mod="class Thing:\n    def do_work(self):\n        return 1\n",
        caller="from mod import Thing\n\nThing().do_work()\n",
    )

    assert found == set()


def test_mention_in_a_docstring_is_not_a_reference(tmp_path: Path) -> None:
    found = dead_symbols(
        tmp_path,
        mod='def ghost():\n    return 1\n',
        other='"""Call ghost() to do the thing."""\n\n\ndef real():\n    return ghost\n',
    )

    assert "ghost" not in found  # referenced by name in real()
    assert found == {"real"}


def test_mention_only_in_a_comment_is_not_a_reference(tmp_path: Path) -> None:
    found = dead_symbols(
        tmp_path,
        mod="def ghost():\n    return 1\n",
        other="# ghost() used to be called here\n",
    )

    assert found == {"ghost"}


def test_reference_without_a_call_keeps_a_function_alive(tmp_path: Path) -> None:
    found = dead_symbols(
        tmp_path,
        mod="def handler():\n    return 1\n",
        caller="from mod import handler\n\nroutes = {'/': handler}\n",
    )

    assert found == set()


def test_framework_decorated_function_is_not_dead(tmp_path: Path) -> None:
    found = dead_symbols(
        tmp_path,
        mod='@app.route("/health")\ndef health():\n    return 1\n',
    )

    assert found == set()


def test_unknown_framework_decorator_is_not_dead(tmp_path: Path) -> None:
    # the reason the decorator rule is a denylist: mcp.tool, celery.task and
    # typer.command can never all be enumerated
    found = dead_symbols(
        tmp_path,
        mod="@mcp.tool()\ndef my_tool():\n    return 1\n",
    )

    assert found == set()


def test_property_is_not_exempt(tmp_path: Path) -> None:
    found = dead_symbols(
        tmp_path,
        mod="class Thing:\n    @property\n    def never_read(self):\n        return 1\n",
    )

    assert found == {"never_read"}


def test_all_export_keeps_a_function_alive(tmp_path: Path) -> None:
    found = dead_symbols(
        tmp_path,
        mod='__all__ = ["public"]\n\n\ndef public():\n    return 1\n',
    )

    assert found == set()


def test_test_functions_are_not_dead(tmp_path: Path) -> None:
    found = dead_symbols(
        tmp_path,
        test_thing="def test_it_works():\n    assert True\n",
    )

    assert found == set()


def test_dunder_methods_are_not_dead(tmp_path: Path) -> None:
    found = dead_symbols(
        tmp_path,
        mod="class Thing:\n    def __init__(self):\n        self.x = 1\n\n    def __repr__(self):\n        return 'Thing'\n",
    )

    assert found == set()


def test_override_of_an_external_base_is_not_dead(tmp_path: Path) -> None:
    # do_GET is called by http.server, which this scan cannot see
    found = dead_symbols(
        tmp_path,
        server=(
            "from http.server import BaseHTTPRequestHandler\n\n\n"
            "class Handler(BaseHTTPRequestHandler):\n"
            "    def log_message(self, fmt, *args):\n"
            "        pass\n\n"
            "    def do_GET(self):\n"
            "        self.send_response(200)\n"
        ),
    )

    assert found == set()


def test_unused_override_of_a_local_base_is_still_dead(tmp_path: Path) -> None:
    # the base is in the repo, so every call into it is visible
    found = dead_symbols(
        tmp_path,
        mod=(
            "class Base:\n"
            "    def used_hook(self):\n"
            "        return 0\n\n"
            "    def unused_hook(self):\n"
            "        return 0\n\n\n"
            "class Child(Base):\n"
            "    def used_hook(self):\n"
            "        return 1\n\n"
            "    def unused_hook(self):\n"
            "        return 2\n\n\n"
            "def go():\n"
            "    return Child().used_hook()\n\n\n"
            "go()\n"
        ),
    )

    assert found == {"unused_hook"}


def test_dotted_external_base_is_recognised(tmp_path: Path) -> None:
    found = dead_symbols(
        tmp_path,
        views=(
            "import django.views\n\n\n"
            "class Home(django.views.View):\n"
            "    def get(self, request):\n"
            "        return 1\n"
        ),
    )

    assert found == set()


def test_plain_class_methods_are_still_reportable(tmp_path: Path) -> None:
    # no bases at all, so nothing external can be calling in
    found = dead_symbols(
        tmp_path,
        mod="class Thing:\n    def orphan(self):\n        return 1\n",
    )

    assert found == {"orphan"}
