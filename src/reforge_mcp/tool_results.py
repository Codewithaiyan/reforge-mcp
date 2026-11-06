"""Output schemas for the existing MCP results; no runtime conversion logic."""

from typing import Any, NotRequired

from typing_extensions import TypedDict


class ScanSummary(TypedDict):
    total_files: int
    total_functions: int
    total_lines: int
    languages_detected: list[str]
    total_classes: NotRequired[int]
    total_imports: NotRequired[int]
    unscanned_source_files: NotRequired[int]
    unscanned_by_extension: NotRequired[dict[str, int]]
    untracked_files_skipped: NotRequired[int]
    parse_failures: NotRequired[int]
    imported_modules: NotRequired[list[str]]


class DeadCode(TypedDict):
    symbol: str
    file: str
    line: int


class DuplicateLocation(TypedDict):
    file: str
    line: int
    name: str


class DuplicateGroup(TypedDict):
    hash: str
    locations: list[DuplicateLocation]
    locations_total: NotRequired[int]


class GodFile(TypedDict):
    file: str
    lines: int
    exports: int


DependencyEdge = TypedDict("DependencyEdge", {"from": str, "to": str})


class DependencyGraph(TypedDict):
    nodes: list[str]
    edges: list[DependencyEdge]
    circular: list[list[str]]
    external_imports: NotRequired[int]
    unresolved_relative_imports: NotRequired[int]
    package_imports: NotRequired[int]
    nodes_total: NotRequired[int]
    edges_total: NotRequired[int]
    circular_total: NotRequired[int]


class Subproject(TypedDict):
    root: str
    language: str
    test_command: str


class ScanResult(TypedDict):
    summary: ScanSummary
    dead_code: list[DeadCode]
    duplicates: list[DuplicateGroup]
    god_files: list[GodFile]
    dep_graph: DependencyGraph
    subprojects: NotRequired[list[Subproject]]
    error: NotRequired[str]
    dead_code_total: NotRequired[int]
    duplicates_total: NotRequired[int]
    god_files_total: NotRequired[int]
    subprojects_total: NotRequired[int]
    truncated: NotRequired[dict[str, int]]


class ChunkResult(TypedDict, total=False):
    source: str
    language: str
    start_line: int
    end_line: int
    total_lines: int
    error: str


class FixResult(TypedDict):
    success: bool
    test_output: str | None
    error: str | None
    rolled_back: bool
    git_state: NotRequired[str]
    backup: NotRequired[str | None]


class CommitResult(TypedDict):
    success: bool
    commit_hash: str | None
    branch: str | None
    files_committed: list[str]
    error: str | None
    needs_confirmation: NotRequired[bool]
    message: NotRequired[str]


class ReadMemoryResult(TypedDict):
    key: str
    value: Any
    found: bool


class WriteMemoryResult(TypedDict):
    success: bool
    key: str
    previous_value: Any
    error: NotRequired[str]


class ArchitectureResult(TypedDict):
    pattern: str
    evidence: list[str]
    entry_points: list[str]
    inferred_modules: list[str]
    confidence: float
    hypothesis: str


class RiskBreakdown(TypedDict):
    inbound_refs: int
    has_tests: int
    lines_changed: int
    is_circular: int


class RiskResult(TypedDict):
    score: int
    breakdown: RiskBreakdown
    basis: str
    referenced_by: list[str]
    recommendation: str


class HealthBreakdown(TypedDict):
    dead_code_ratio: float
    duplicate_ratio: float
    god_file_count: int
    circular_count: int


class HealthResult(TypedDict):
    score: float | None
    coverage: float
    breakdown: HealthBreakdown
    scan_summary: ScanSummary
    caveat: NotRequired[str]


class ChangelogResult(TypedDict):
    success: bool
    path: str
    error: NotRequired[str]
