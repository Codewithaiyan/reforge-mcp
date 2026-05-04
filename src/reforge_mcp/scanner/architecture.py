"""Architecture inference from scan results."""

from __future__ import annotations

import os

_CLI_MARKERS = {"main", "__main__", "cli", "argparse", "click", "typer", "fire"}
_REST_MARKERS = {"route", "router", "app", "fastapi", "flask", "django", "starlette", "endpoint", "handler"}
_LIBRARY_MARKERS = {"setup", "pyproject", "package", "module", "__init__"}
_WEB_MARKERS = {"component", "render", "jsx", "tsx", "react", "vue", "svelte", "page", "layout"}


def infer_architecture(repo_root: str, scan_result: dict) -> dict:
    nodes: list[str] = scan_result.get("dep_graph", {}).get("nodes", [])
    god_files: list[dict] = scan_result.get("god_files", [])
    summary: dict = scan_result.get("summary", {})
    languages: list[str] = summary.get("languages_detected", [])

    all_files = nodes or [g["file"] for g in god_files]
    basenames = [os.path.basename(f).lower() for f in all_files]
    stems = [os.path.splitext(b)[0] for b in basenames]

    entry_points = _find_entry_points(all_files, basenames, stems)
    inferred_modules = _find_modules(stems)

    cli_hits = sum(1 for s in stems if any(m in s for m in _CLI_MARKERS))
    rest_hits = sum(1 for s in stems if any(m in s for m in _REST_MARKERS))
    lib_hits = sum(1 for s in stems if any(m in s for m in _LIBRARY_MARKERS))
    web_hits = sum(1 for s in stems if any(m in s for m in _WEB_MARKERS))

    total = max(len(all_files), 1)
    scores = {
        "CLI tool": cli_hits / total,
        "REST API": rest_hits / total,
        "library": lib_hits / total,
        "web frontend": web_hits / total,
    }

    is_js = any(lang in ("javascript", "typescript") for lang in languages)
    is_py = "python" in languages

    if is_js and not is_py:
        scores["web frontend"] += 0.2
    if is_py and not is_js:
        scores["library"] += 0.05

    pattern = max(scores, key=lambda k: scores[k])
    confidence = min(1.0, round(scores[pattern] * 3 + 0.2, 2))

    hypothesis = _build_hypothesis(pattern, entry_points, inferred_modules, languages)

    return {
        "pattern": pattern,
        "entry_points": entry_points,
        "inferred_modules": inferred_modules,
        "confidence": confidence,
        "hypothesis": hypothesis,
    }


def _find_entry_points(files: list[str], basenames: list[str], stems: list[str]) -> list[str]:
    candidates = []
    for f, b, s in zip(files, basenames, stems):
        if s in ("main", "__main__", "app", "server", "index", "cli", "run", "manage"):
            candidates.append(f)
        elif b in ("main.py", "__main__.py", "app.py", "server.py", "index.js", "index.ts"):
            candidates.append(f)
    seen: set[str] = set()
    result = []
    for c in candidates:
        if c not in seen:
            seen.add(c)
            result.append(c)
    return result


def _find_modules(stems: list[str]) -> list[str]:
    skip = {
        "test", "tests", "spec", "conftest", "setup", "pyproject",
        "__init__", "utils", "helpers", "constants", "config",
    }
    seen: set[str] = set()
    modules = []
    for s in stems:
        if s and s not in skip and not s.startswith("test_") and s not in seen:
            seen.add(s)
            modules.append(s)
    return modules[:20]


def _build_hypothesis(
    pattern: str,
    entry_points: list[str],
    modules: list[str],
    languages: list[str],
) -> str:
    lang_str = ", ".join(languages) if languages else "unknown language"
    ep_str = (
        f"Entry point{'s' if len(entry_points) != 1 else ''}: {', '.join(entry_points[:3])}."
        if entry_points
        else "No clear entry point detected."
    )
    mod_str = (
        f"Logical modules include: {', '.join(modules[:5])}."
        if modules
        else ""
    )
    return f"This appears to be a {pattern} written in {lang_str}. {ep_str} {mod_str}".strip()
