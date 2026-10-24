"""Tests for duplicate detection."""

from pathlib import Path

from reforge_mcp.scanner.duplicates import find_duplicates
from reforge_mcp.scanner.parser import parse_directory


def groups(tmp_path: Path, **files: str) -> list:
    for name, source in files.items():
        (tmp_path / f"{name}.py").write_text(source)
    return find_duplicates(parse_directory(directory=tmp_path, repo_root=tmp_path))


def test_copy_pasted_function_is_reported(tmp_path: Path) -> None:
    body = "def calculate_discount(price):\n    rate = 0.1\n    return price * (1 - rate)\n"
    found = groups(tmp_path, billing=body, cart=body)

    assert len(found) == 1
    assert {loc.file for loc in found[0].locations} == {"billing.py", "cart.py"}


def test_reformatting_does_not_hide_a_duplicate(tmp_path: Path) -> None:
    found = groups(
        tmp_path,
        a="def total(items):\n    return sum(items)\n",
        b="def total(items):\n\n    # adds them up\n    return sum(items)\n",
    )

    assert len(found) == 1


def test_different_bodies_are_not_duplicates(tmp_path: Path) -> None:
    found = groups(
        tmp_path,
        a="def total(items):\n    return sum(items)\n",
        b="def total(items):\n    return len(items)\n",
    )

    assert found == []


def test_one_line_interface_methods_are_not_duplicates(tmp_path: Path) -> None:
    # four adapters conforming to one Protocol is not copy-paste
    found = groups(
        tmp_path,
        adapters=(
            "class PyAdapter:\n"
            "    def get_language(self):\n"
            "        return self._language\n"
            "\n\n"
            "class JsAdapter:\n"
            "    def get_language(self):\n"
            "        return self._language\n"
            "\n\n"
            "class GoAdapter:\n"
            "    def get_language(self):\n"
            "        return self._language\n"
        ),
    )

    assert found == []


def test_short_module_level_duplicate_is_still_reported(tmp_path: Path) -> None:
    # the narrow filter above must not swallow this: a duplicated module-level
    # function is the case the tool exists to find, however short it is
    found = groups(
        tmp_path,
        utils_a="def calculate_total(items):\n    return sum(items)\n",
        utils_b="def calculate_total(items):\n    return sum(items)\n",
    )

    assert len(found) == 1


def test_multi_line_duplicate_methods_are_still_reported(tmp_path: Path) -> None:
    method = (
        "    def charge(self, amount):\n"
        "        fee = amount * 0.02\n"
        "        total = amount + fee\n"
        "        return total\n"
    )
    found = groups(
        tmp_path,
        services="class A:\n" + method + "\n\nclass B:\n" + method,
    )

    assert len(found) == 1
