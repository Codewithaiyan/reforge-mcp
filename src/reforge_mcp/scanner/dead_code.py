"""
Dead Code Detector.

Finds functions that nothing in the repository references.

HOW IT WORKS:
1. Every parsed file reports the names it *uses* (ParseResult.references), which
   the parser collects from the AST while skipping each definition's own name,
   plus comments and string literals
2. Collect all function definitions across the repo
3. Report definitions whose name appears in nobody's reference set
4. Filter the things that are called without being named: special methods,
   conventional entry points, and anything carrying a decorator

WHY THIS MATTERS:
Dead code increases cognitive load, slows down builds, and can harbor security
vulnerabilities (unused auth checks, deprecated API endpoints). Automatic
detection makes cleanup systematic rather than relying on memory.

FALSE POSITIVE PREVENTION:
Detection is by name, not by resolved symbol, so a repo-wide name collision
hides a dead function. That is the intended bias: a missed finding costs
nothing, a wrong one costs the user working code. The filters below exist for
the same reason.
"""

import logging
from dataclasses import dataclass

from .parser import FunctionInfo, ParseResult

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class DeadCodeInfo:
    """
    Represents a dead code finding.

    Attributes:
        symbol: Name of the unused function/class
        file: File path where it's defined
        line: Line number where it's defined
        reason: Why it's considered dead (e.g., "no_callers")
    """

    symbol: str
    file: str
    line: int
    reason: str


# Decorators that do not imply anything else calls the function: they adjust how
# it is invoked, not whether it is.
#
# This is deliberately a denylist. The allowlist it replaced ("@app.route,
# @pytest.fixture, @click.command, ...") could never be complete - it had no
# entry for mcp.tool, so this project's own tools would have been reported dead,
# and every user's @celery.task or @typer.command had the same problem. Treating
# any other decorator as a sign of a framework caller errs toward false
# negatives, which is the trade this module wants.
NEUTRAL_DECORATORS = {
    "property",
    "cached_property",
    "functools.cached_property",
    "staticmethod",
    "classmethod",
    "abstractmethod",
    "abc.abstractmethod",
    "functools.wraps",
    "functools.cache",
    "functools.lru_cache",
    "overload",
    "typing.overload",
}

# Special methods that are called implicitly
SPECIAL_METHODS = {
    "__init__",
    "__new__",
    "__del__",
    "__str__",
    "__repr__",
    "__eq__",
    "__hash__",
    "__lt__",
    "__le__",
    "__gt__",
    "__ge__",
    "__bool__",
    "__len__",
    "__getitem__",
    "__setitem__",
    "__delitem__",
    "__iter__",
    "__next__",
    "__enter__",
    "__exit__",
    "__call__",
    "__getattr__",
    "__setattr__",
    "__delattr__",
    "__contains__",
    "__add__",
    "__sub__",
    "__mul__",
    "__truediv__",
    "__floordiv__",
    "__mod__",
    "__pow__",
    "__and__",
    "__or__",
    "__xor__",
    "__neg__",
    "__pos__",
    "__abs__",
    "__invert__",
    "__int__",
    "__float__",
    "__complex__",
    "__bytes__",
    "__copy__",
    "__deepcopy__",
    "__reduce__",
    "__reduce_ex__",
    "__getstate__",
    "__setstate__",
    "__dir__",
    "__sizeof__",
    "__weakref__",
    "__format__",
    "__subclasshook__",
    "__init_subclass__",
}

# Function names that are typically entry points
ENTRY_POINT_NAMES = {
    "main",
    "run",
    "start",
    "execute",
    "entry_point",
    "cli",
    "app",
    "create_app",
}


def is_decorated_entry_point(func: FunctionInfo) -> bool:
    """
    Check whether a decorator implies something outside this repo calls it.

    Frameworks call registered functions without naming them anywhere a parser
    can see - a route, a task, a fixture, an MCP tool. Any decorator that is not
    in NEUTRAL_DECORATORS is treated as such a registration.
    """
    return any(dec not in NEUTRAL_DECORATORS for dec in func.decorators)


def is_special_method(name: str) -> bool:
    """Check if a function name is a special/dunder method."""
    return name in SPECIAL_METHODS or (name.startswith("__") and name.endswith("__"))


def is_entry_point_name(name: str) -> bool:
    """
    Check if a function name suggests it's an entry point.

    `test_*` counts: a test runner collects those by naming convention, so
    nothing in the repo ever references them by name.
    """
    return name in ENTRY_POINT_NAMES or name.startswith("test_")


def _externally_derived_methods(parse_results: list[ParseResult]) -> set[str]:
    """
    Methods of classes that inherit from something outside the scanned repo.

    Those are overrides, and whatever calls them lives in the base class's own
    code, which this scan cannot see: `do_GET` on a
    `BaseHTTPRequestHandler` subclass is called by the standard library, and
    `render` on a `React.Component` subclass by React. Nothing in the repo names
    them, so without this they are reported dead - which they emphatically are
    not.

    A class whose bases are all defined in the repo is left alone: the calls
    into it are visible, so a genuinely unused override stays reportable.
    """
    local_classes = {
        cls.name
        for result in parse_results
        if not result.error
        for cls in result.classes
    }

    protected: set[str] = set()
    for result in parse_results:
        if result.error:
            continue
        for cls in result.classes:
            if any(base not in local_classes for base in cls.bases):
                protected.update(cls.methods)
    return protected


def find_dead_code(parse_results: list[ParseResult]) -> list[DeadCodeInfo]:
    """
    Find functions that nothing in the parsed files references.

    Args:
        parse_results: List of ParseResult from parser.parse_directory()

    Returns:
        List of DeadCodeInfo for each unreferenced function found
    """
    referenced: set[str] = set()
    for result in parse_results:
        if result.error:
            continue
        referenced.update(result.references)

    referenced.update(_externally_derived_methods(parse_results))

    dead_code: list[DeadCodeInfo] = []

    for result in parse_results:
        if result.error:
            continue
        for func in result.functions:
            if func.name in referenced:
                continue
            if is_special_method(func.name):
                continue
            if is_entry_point_name(func.name):
                continue
            if is_decorated_entry_point(func):
                continue
            dead_code.append(
                DeadCodeInfo(
                    symbol=func.name,
                    file=result.file,
                    line=func.start_line,
                    reason="no_callers",
                )
            )

    logger.debug(
        f"Dead code: {len(dead_code)} findings from {len(referenced)} referenced names"
    )
    return dead_code
