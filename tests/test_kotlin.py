"""Tests for the Kotlin adapter and the false positives it would otherwise cause."""

from pathlib import Path

from reforge_mcp.scanner.dead_code import find_dead_code
from reforge_mcp.scanner.duplicates import find_duplicates
from reforge_mcp.scanner.parser import parse_directory, parse_file

ACTIVITY = """package com.example.app

import android.os.Bundle
import androidx.activity.ComponentActivity

class MainActivity : ComponentActivity() {
    override fun onCreate(savedInstanceState: Bundle?) {
        helper()
    }

    private fun helper() {
        println("called from onCreate")
    }

    private fun neverCalled() {
        println("nothing reaches this")
    }
}
"""


def _write(tmp_path: Path, name: str, body: str) -> Path:
    f = tmp_path / name
    f.write_text(body, encoding="utf-8")
    return f


def test_kotlin_functions_classes_and_imports_are_extracted(tmp_path: Path) -> None:
    f = _write(tmp_path, "MainActivity.kt", ACTIVITY)

    result = parse_file(f, tmp_path)

    assert result.error is None
    assert result.language == "kotlin"
    assert {fn.name for fn in result.functions} == {"onCreate", "helper", "neverCalled"}
    assert [c.name for c in result.classes] == ["MainActivity"]
    assert [i.from_module for i in result.imports] == [
        "android.os.Bundle",
        "androidx.activity.ComponentActivity",
    ]


def test_a_supertype_is_recorded_as_a_base(tmp_path: Path) -> None:
    # the grammar wraps the list in (delegation_specifiers), and missing that
    # left every Android class with no bases and its overrides reported dead
    f = _write(tmp_path, "MainActivity.kt", ACTIVITY)

    result = parse_file(f, tmp_path)

    assert result.classes[0].bases == ("ComponentActivity",)


def test_an_override_is_not_dead_code(tmp_path: Path) -> None:
    _write(tmp_path, "MainActivity.kt", ACTIVITY)

    dead = {d.symbol for d in find_dead_code(parse_directory(tmp_path, tmp_path))}

    assert "onCreate" not in dead


def test_a_method_of_an_externally_derived_class_is_exempt(tmp_path: Path) -> None:
    """
    Nothing in a class extending a framework base is reported, not even an
    unused private helper.

    That is the external-base exemption working as designed, and it is a real
    limitation for Android: almost every class extends something from the
    framework, so method-level dead code there goes unreported. The bias is
    deliberate - an `android:onClick` handler named only in an XML layout is
    invisible to this scan, and calling it dead would cost working code.
    Narrowing the exemption to overrides only would find more and break that.
    """
    _write(tmp_path, "MainActivity.kt", ACTIVITY)

    dead = {d.symbol for d in find_dead_code(parse_directory(tmp_path, tmp_path))}

    assert dead == set()


def test_an_unused_top_level_function_is_reported(tmp_path: Path) -> None:
    # no class, so no exemption: this is where Kotlin dead code is found, and
    # all three findings in the repository that prompted the adapter were here
    _write(
        tmp_path,
        "Icons.kt",
        """package com.example.app

internal fun squareIn(): Int {
    return 1
}

internal fun used(): Int {
    return 2
}

fun entry(): Int {
    return used()
}
""",
    )

    dead = {d.symbol for d in find_dead_code(parse_directory(tmp_path, tmp_path))}

    assert "squareIn" in dead
    assert "used" not in dead


def test_an_annotated_test_function_is_not_dead_code(tmp_path: Path) -> None:
    # JUnit collects @Test by annotation, so nothing in the repo names it, and
    # Kotlin tests carry no test_ prefix for the name-based exemption to catch
    _write(
        tmp_path,
        "FpsReasonTest.kt",
        """package com.example.app

class FpsReasonTest {
    @Test
    fun onlyThirtyEverywhere() {
        assertEquals(1, 1)
    }
}
""",
    )

    dead = {d.symbol for d in find_dead_code(parse_directory(tmp_path, tmp_path))}

    assert dead == set()


def test_empty_callback_overrides_are_not_reported_as_duplicates(tmp_path: Path) -> None:
    # eight empty camera callbacks on anonymous `object :` expressions were
    # grouped as one duplicate; they are conformance, not copy-paste
    _write(
        tmp_path,
        "Streamer.kt",
        """package com.example.app

class Streamer {
    override fun onFirst() {}
    override fun onSecond() {}
}
""",
    )

    groups = find_duplicates(parse_directory(tmp_path, tmp_path))

    assert groups == []
