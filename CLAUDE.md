# CLAUDE.md

Guidance for working in this repository.

## What this is

An MCP server that exposes a codebase to Claude Code as structured tools so it
can scan, plan and apply refactors with rollback. Python 3.11+, tree-sitter for
parsing, FastMCP for the tool surface. Pre-1.0 and honestly alpha.

## Commands

```bash
uv run pytest -q            # the test suite — plain `python -m pytest` has no pytest installed
uv run pytest tests/test_fix.py -q
uv run reforge-mcp          # start the server (stdio)
```

Self-scan — the fastest way to see whether a scanner change actually works:

```bash
uv run python -c "import sys,json; sys.path.insert(0,'src'); \
from reforge_mcp.tools.scan import scan_repo; \
print(json.dumps(scan_repo('.'), indent=1))"
```

## Layout

```
src/reforge_mcp/
  server.py          FastMCP entry point — registers all tools, thin wrappers only
  tools/             one file per MCP tool: scan, chunk, fix, git
  scanner/           analysis: parser (tree-sitter), dead_code, duplicates, risk, architecture
  scanner/adapters/  per-language stubs (currently 7 lines each; see R20)
  utils/             security (path + command validation), diff, state
tests/               one file per module, pytest, no fixtures framework beyond tmp_path
```

## Invariants — do not break these

- **Every path from a tool argument goes through `utils.security.validate_path`
  before any read or write.** It is the only thing standing between a caller and
  the rest of the filesystem. Same for `validate_test_command` before any
  subprocess.
- **`server.py` stays thin.** Tool functions there wrap an implementation in
  `tools/` or `scanner/` and do nothing else. Logic in `server.py` is untestable.
- **State writes are `.tmp` -> rename.** See `utils/state.py:save_state`. Never
  write `reforge-state.json` in place.
- **`write_fix` must be able to restore the original file on every failure
  path.** If a new early-return is added, check the `.bak` is either used or
  cleaned up.
- **Scanner output is a public contract.** `scan_repo`'s return shape is consumed
  by `get_health_score`, `score_risk` and `infer_architecture`. Changing a key
  means changing all three.

## Known-broken — read before trusting any output

[IMPROVEMENTS.md](IMPROVEMENTS.md) is a reviewed, reproduced list of what does
not work; [TASK.md](TASK.md) tracks the fixes. Until M0 and M1 are closed:

- **Do not use this project's own `write_fix` to edit this repository.** It can
  silently corrupt a file (R1). Use ordinary edits.
- **Do not treat `scan_repo` output as truth.** Dead-code detection reports
  nothing ever, duplicates are mostly phantom, and the dependency graph is empty
  (R4, R9, R6). The health score is derived from those numbers.
- **`reforge.toml` is mostly ignored**, including `dry_run` (R12). Assume any
  tool that can write, writes.

When you fix one of these, tick its box in TASK.md in the same change.

## Conventions

- Match the surrounding style: module docstring, `logging.getLogger(__name__)`,
  frozen dataclasses for results, `dict[str, Any]` returns from tool functions.
- Tool functions return a dict and never raise across the MCP boundary — catch
  and return `{"success": False, "error": ...}`.
- New non-trivial logic gets a test in the matching `tests/test_*.py`. A fix for
  an IMPROVEMENTS.md finding gets a test that fails before it.
- No new runtime dependency without a reason in the commit message. Two of the
  current nine are unused (R10).

## graphify

This project has a graphify knowledge graph at graphify-out/.

Rules:
- Before answering architecture or codebase questions, read graphify-out/GRAPH_REPORT.md for god nodes and community structure
- If graphify-out/wiki/index.md exists, navigate it instead of reading raw files
- For cross-module "how does X relate to Y" questions, prefer `graphify query "<question>"`, `graphify path "<A>" "<B>"`, or `graphify explain "<concept>"` over grep — these traverse the graph's EXTRACTED + INFERRED edges instead of scanning files
- After modifying code files in this session, run `graphify update .` to keep the graph current (AST-only, no API cost)

Note: `graphify-out/` is currently empty, so these tools have nothing to read
until the graph is generated.
