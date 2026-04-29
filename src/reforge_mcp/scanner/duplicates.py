"""
Duplicate Code Detector.

Identifies copy-pasted code and near-duplicate implementations by hashing
normalized function bodies and grouping functions with identical hashes.

HOW IT WORKS:
1. For each function body:
   - Strip whitespace and comments (normalize)
   - Compute SHA256 hash
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

import hashlib
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


def normalize_code(code: str) -> str:
    """
    Normalize code for duplicate comparison.

    Normalization removes:
    - Leading/trailing whitespace from each line
    - Empty lines
    - Single-line comments (# // /*)
    - Extra blank lines between statements

    This ensures that copy-pasted code with minor formatting differences
    is detected as a duplicate.

    Example:
        # These two functions are duplicates:
        def foo():
            x = 1
            return x

        def bar():
            # Comment added
            x = 1

            return x

        After normalization, both become:
        x = 1
        return x
    """
    lines = code.split("\n")
    normalized_lines = []

    for line in lines:
        stripped = line.strip()

        # Skip empty lines
        if not stripped:
            continue

        # Skip single-line comments
        if stripped.startswith(("#", "//")):
            continue

        # Skip docstring lines (triple quotes on their own line)
        if stripped.startswith('"""') or stripped.startswith("'''"):
            continue

        # Skip block comment markers
        if stripped.startswith("*") or stripped.startswith("/*") or stripped.startswith("*/"):
            continue

        normalized_lines.append(stripped)

    return "\n".join(normalized_lines)


def hash_body(body: str) -> str:
    """
    Compute SHA256 hash of a normalized function body.

    Uses normalize_code() to preprocess the body before hashing.

    Why SHA256:
    - Fast: computed in microseconds
    - Collision-resistant: effectively impossible for two different
      function bodies to have the same hash
    - Standard: available in Python's hashlib without external deps
    """
    normalized = normalize_code(body)
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()


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

    for result in parse_results:
        if result.error:
            continue

        for func in result.functions:
            location = DuplicateLocation(
                file=func.file,
                line=func.start_line,
                name=func.name,
            )
            hash_groups[func.body_hash].append(location)

    # Filter to groups with >= min_duplicates members
    duplicate_groups: list[DuplicateGroup] = []

    for body_hash, locations in hash_groups.items():
        if len(locations) >= min_duplicates:
            # Estimate line count from first location
            # (We'd need the actual body to know exactly)
            first_location = locations[0]
            # Find the function in parse results to get end_line
            line_count = 1  # Default

            for result in parse_results:
                for func in result.functions:
                    if func.file == first_location.file and func.start_line == first_location.line:
                        line_count = func.end_line - func.start_line + 1
                        break

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


def find_similar_functions(
    parse_results: list[ParseResult],
    similarity_threshold: float = 0.8,
) -> list[tuple[FunctionInfo, FunctionInfo, float]]:
    """
    Find similar (but not identical) functions using token-based comparison.

    NOTE: This is a placeholder for future enhancement.
    Current implementation only detects exact duplicates via hash matching.

    For true similarity detection, you would:
    1. Tokenize each function body
    2. Compute Jaccard similarity or cosine similarity
    3. Group functions above threshold

    This is more expensive and requires additional libraries
    (e.g., scikit-learn for TF-IDF + cosine similarity).

    Args:
        parse_results: List of ParseResult
        similarity_threshold: Minimum similarity score (0.0-1.0)

    Returns:
        List of (func1, func2, similarity_score) tuples
    """
    # Placeholder - returns empty list
    # Full implementation would require embedding models or token-based comparison
    logger.debug("Similar function detection not implemented (requires embeddings)")
    return []
