"""Architecture inference from scan results."""

from __future__ import annotations

import os

# Classification is by what the code imports, not what its files are called.
# The filename heuristic this replaced called an Android camera app a "REST API"
# at 0.7 confidence, because _REST_MARKERS contained "app" and the repo had an
# app.js. A framework in an import statement is evidence; a filename is not.
_REST_IMPORTS = {
    "flask", "fastapi", "django", "starlette", "aiohttp", "bottle", "falcon",
    "tornado", "sanic", "quart", "connexion", "express", "koa", "hapi",
    "restify", "fastify", "nest",
}
_CLI_IMPORTS = {
    "argparse", "click", "typer", "fire", "docopt", "optparse", "getopt",
    "commander", "yargs", "inquirer", "cobra",
}
_WEB_IMPORTS = {
    "react", "preact", "vue", "svelte", "next", "nuxt", "angular", "solid",
    "lit", "ember", "backbone", "jquery",
}


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

    imported = {m.lower() for m in summary.get("imported_modules", [])}
    evidence = {
        "REST API": sorted(imported & _REST_IMPORTS),
        "CLI tool": sorted(imported & _CLI_IMPORTS),
        "web frontend": sorted(imported & _WEB_IMPORTS),
    }

    pattern = max(evidence, key=lambda k: len(evidence[k]))
    matched = evidence[pattern]

    if matched:
        # one framework import is weak evidence, several is strong; nothing
        # here is ever certain, so this does not reach 1.0
        confidence = min(0.9, round(0.5 + 0.1 * len(matched), 2))
    elif any(os.path.basename(f) == "__init__.py" for f in all_files):
        # a package with no application framework: importable, not runnable
        pattern, confidence = "library", 0.4
    else:
        pattern, confidence = "unknown", 0.1

    hypothesis = _build_hypothesis(
        pattern, entry_points, inferred_modules, languages, matched, summary
    )

    return {
        "pattern": pattern,
        "evidence": matched,
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
    evidence: list[str] | None = None,
    summary: dict | None = None,
) -> str:
    lang_str = ", ".join(languages) if languages else "unknown language"
    if pattern == "unknown":
        lead = f"No architectural pattern could be inferred from the {lang_str} imports."
    else:
        why = f" (from {', '.join(evidence)})" if evidence else ""
        lead = f"This appears to be a {pattern} written in {lang_str}{why}."

    scanned = (summary or {}).get("total_files", 0)
    skipped = (summary or {}).get("unscanned_source_files", 0)
    partial = (
        f" Based on {scanned} of {scanned + skipped} source files."
        if skipped and scanned + skipped and scanned / (scanned + skipped) < 0.5
        else ""
    )
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
    return f"{lead} {ep_str} {mod_str}{partial}".strip()
