"""
Duplicate Code Detector.

Identifies copy-pasted code and near-duplicate implementations by hashing
normalized function bodies and grouping functions with identical hashes.

HOW IT WORKS:
1. Each function arrives with body_hash already computed by the parser,
   which strips whitespace and comments before hashing
2. Group functions by hash
3. Flag groups with 2+ members as duplicates

WHY HASH-BASED DETECTION:
- Fast: O(n) single pass through all functions
- Deterministic: same code always produces same hash
- Exact matching: no false positives from "similar but different" code
- Handles reformatting: normalized comparison catches copy-paste with minor edits

LIMITATIONS:
- Only catches exact duplicates (not "similar" code with variable renaming)
- Doesn't catch duplicates across different languages
- May miss duplicates if function bodies have significant whitespace differences

For more advanced duplicate detection, consider:
- Token-based comparison (catches renamed variables)
- AST-based comparison (catches structurally identical code)
- Embedding similarity (catches semantically similar code)

But for a learning project, hash-based detection is:
- Simple to understand and implement
- Fast enough for large codebases
- Easy to explain: "same code = same hash"
"""

import logging
from collections import defaultdict
from dataclasses import dataclass

from .parser import FunctionInfo, ParseResult

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class DuplicateLocation:
    """
    Represents one location of a duplicate code group.

    Attributes:
        file: File path where the duplicate is located
        line: Line number where the function starts
        name: Function name
    """

    file: str
    line: int
    name: str


@dataclass(frozen=True)
class DuplicateGroup:
    """
    Represents a group of duplicate functions.

    Attributes:
        hash: SHA256 hash of the normalized function body
        locations: List of locations where this code appears
        line_count: Approximate lines of code in each duplicate
    """

    hash: str
    locations: tuple[DuplicateLocation, ...]
    line_count: int


def _is_shared_interface_method(
    locations: list[DuplicateLocation],
    functions_by_location: dict[tuple[str, int], FunctionInfo],
    method_names_by_file: dict[str, set[str]],
) -> bool:
    """
    Is this group several classes implementing one interface method the same way?

    Four adapters each answering `def get_language(self): return self._language`
    is conformance to a Protocol, not copy-paste anyone can consolidate.

    The test is deliberately narrow — every member must be a one-line body that
    is either a method of a named class or marked `override`. A module-level
    function duplicated across files stays reported however short it is,
    because that is the case this tool exists to find.

    The `override` arm exists because Kotlin puts most framework callbacks on an
    anonymous `object : SomeCallback()`, which is not a named class, so its
    members are in no class's method list. Eight empty camera and surface
    callbacks were being reported as one duplicate group.
    """
    for loc in locations:
        func = functions_by_location.get((loc.file, loc.line))
        if func is None or func.end_line - func.start_line > 1:
            return False
        is_method = loc.name in method_names_by_file.get(loc.file, set())
        if not is_method and "override" not in func.decorators:
            return False
    return True


def find_duplicates(
    parse_results: list[ParseResult],
    min_duplicates: int = 2,
) -> list[DuplicateGroup]:
    """
    Find duplicate code across all parsed files.

    ALGORITHM:
    1. For each function in each parse result:
       - Extract the function body (not available in ParseResult, so we hash during parsing)
       - Use the pre-computed body_hash from FunctionInfo
    2. Group functions by body_hash
    3. Return groups with >= min_duplicates members

    Args:
        parse_results: List of ParseResult from parser.parse_directory()
        min_duplicates: Minimum number of duplicates to report (default 2)

    Returns:
        List of DuplicateGroup for each set of duplicate functions found
    """
    # Group functions by body hash
    # hash -> list of (file, line, name)
    hash_groups: dict[str, list[DuplicateLocation]] = defaultdict(list)
    functions_by_location: dict[tuple[str, int], FunctionInfo] = {}
    method_names_by_file: dict[str, set[str]] = defaultdict(set)

    for result in parse_results:
        if result.error:
            continue

        for cls in result.classes:
            method_names_by_file[result.file].update(cls.methods)

        for func in result.functions:
            location = DuplicateLocation(
                file=func.file,
                line=func.start_line,
                name=func.name,
            )
            hash_groups[func.body_hash].append(location)
            functions_by_location[(func.file, func.start_line)] = func

    # Filter to groups with >= min_duplicates members
    duplicate_groups: list[DuplicateGroup] = []

    for body_hash, locations in hash_groups.items():
        if len(locations) < min_duplicates:
            continue

        if _is_shared_interface_method(
            locations, functions_by_location, method_names_by_file
        ):
            continue

        first = functions_by_location.get((locations[0].file, locations[0].line))
        line_count = first.end_line - first.start_line + 1 if first else 1

        duplicate_groups.append(
            DuplicateGroup(
                hash=body_hash,
                locations=tuple(locations),
                line_count=line_count,
            )
        )

    # Sort by number of duplicates (most duplicated first)
    duplicate_groups.sort(key=lambda g: len(g.locations), reverse=True)

    logger.info(
        f"Found {len(duplicate_groups)} duplicate groups "
        f"(code appearing 2+ times with identical body)"
    )

    return duplicate_groups
