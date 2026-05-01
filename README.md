![Python 3.11+](https://img.shields.io/badge/python-3.11%2B-blue)
![License MIT](https://img.shields.io/badge/license-MIT-green)
![PRs Welcome](https://img.shields.io/badge/PRs-welcome-brightgreen)

# reforge-mcp

An MCP server that connects Claude Code to your codebase and systematically cleans it up — scanning, planning, and applying fixes with full rollback safety.

---

## What it does

Vibe-coded repos accumulate fast: functions nobody calls, copy-pasted logic in three files, one 900-line god module that does everything, circular imports that break at runtime. Spotting this manually takes hours; fixing it safely takes longer. `reforge-mcp` exposes your codebase to Claude Code as a set of structured tools so it can analyse, prioritise, and apply fixes autonomously — one atomic commit at a time.

### The 7 MCP tools

| Tool | What it does |
|---|---|
| `scan_repo` | AST-parses your repo (Python, JS, TS, Go) and returns dead code, duplicates, god files, circular deps, and monorepo subprojects |
| `get_chunk` | Reads an exact line-range slice from any file — lets Claude fetch only what it needs without blowing its context window |
| `write_fix` | Applies a unified diff atomically, runs optional tests, and auto-rolls back on failure |
| `git_commit` | Stages and commits specific files; enforces a per-session budget and confirmation checkpoints |
| `read_memory` | Reads a value from `reforge-state.json` — persists architecture hypotheses, pending fixes, and embeddings across sessions |
| `write_memory` | Writes any value atomically to `reforge-state.json` |
| `get_health_score` | Computes a 0–100 health score from scan metrics and appends a timestamped entry to the project's health history |

### Also included

- **Health score trending** — every `get_health_score` call appends to `health_history` so you can chart improvement over time
- **Persistent memory** — `reforge-state.json` survives across Claude Code sessions; stores architecture hypotheses, fix logs, pending work
- **Monorepo support** — `scan_repo` detects Python, JavaScript, TypeScript, and Go subprojects from their marker files and returns the correct `test_command` per subproject
- **Changelog generation** — `REFORGE_CHANGES.md` is written on demand with score deltas, applied fixes, and pending items

---

## Installation

**Prerequisites:** Python 3.11+, Claude Code CLI, Git

```bash
# 1. Clone the repo
git clone https://github.com/your-org/reforge-mcp.git
cd reforge-mcp

# 2. Create and activate a virtual environment
python3 -m venv venv
source venv/bin/activate          # Windows: venv\Scripts\activate

# 3. Install in editable mode
pip install -e .

# 4. Find the absolute path to the server entry point
which reforge-mcp                 # e.g. /home/you/reforge-mcp/venv/bin/reforge-mcp
```

**Add to `claude_desktop_config.json`** (usually `~/.config/claude/claude_desktop_config.json` on Linux, `~/Library/Application Support/Claude/claude_desktop_config.json` on macOS):

```json
{
  "mcpServers": {
    "reforge-mcp": {
      "command": "/home/you/reforge-mcp/venv/bin/reforge-mcp",
      "args": [],
      "env": {}
    }
  }
}
```

Replace the path with the output of `which reforge-mcp` from step 4.

```bash
# 5. Set your Anthropic API key (if not already set)
export ANTHROPIC_API_KEY=sk-ant-...
```

Restart Claude Code. The seven tools will appear under the MCP panel.

---

## Usage

### Example session with Claude Code

```
You: Use reforge-mcp to scan my repo at /home/me/myproject and fix the top issues.

Claude: I'll start with a full scan.

[calls scan_repo("/home/me/myproject")]

The scan found:
- 14 dead functions across 6 files
- 3 duplicate implementations of `calculate_discount`
- 1 god file: src/api/handlers.py (847 lines, 23 exports)
- 2 circular dependencies: auth → middleware → auth

Health score: 47/100

Let me fetch the duplicate implementations to confirm they're identical.

[calls get_chunk("src/billing/utils.py", start_line=12, end_line=28)]
[calls get_chunk("src/cart/helpers.py", start_line=5, end_line=21)]

Confirmed — identical bodies. I'll consolidate them into src/shared/pricing.py and
remove both originals.

[calls write_fix("src/shared/pricing.py", diff_str="...")]
[calls write_fix("src/billing/utils.py", diff_str="...")]
[calls write_fix("src/cart/helpers.py", diff_str="...")]
[calls git_commit("/home/me/myproject", files=[...], message="refactor: consolidate duplicate calculate_discount")]

Committed: a3f91c2. Running next fix...
```

### Sample `scan_repo` output

```json
{
  "summary": {
    "total_files": 42,
    "total_functions": 187,
    "total_lines": 8304,
    "languages_detected": ["python"]
  },
  "dead_code": [
    { "symbol": "parse_legacy_csv", "file": "src/importers/csv.py", "line": 44 },
    { "symbol": "_old_validate",    "file": "src/models/user.py",   "line": 112 }
  ],
  "duplicates": [
    {
      "hash": "a3f2...91bc",
      "locations": [
        { "file": "src/billing/utils.py",  "line": 12, "name": "calculate_discount" },
        { "file": "src/cart/helpers.py",   "line":  5, "name": "calculate_discount" },
        { "file": "src/orders/pricing.py", "line": 78, "name": "apply_discount" }
      ]
    }
  ],
  "god_files": [
    { "file": "src/api/handlers.py", "lines": 847, "exports": 23 }
  ],
  "dep_graph": {
    "nodes": ["src/auth/__init__.py", "src/middleware/auth.py"],
    "edges": [{ "from": "src/auth/__init__.py", "to": "src/middleware/auth.py" }],
    "circular": [
      ["src/auth/__init__.py", "src/middleware/auth.py", "src/auth/__init__.py"]
    ]
  },
  "subprojects": [
    { "root": "services/worker", "language": "go",         "test_command": "go test ./..." },
    { "root": "frontend",        "language": "javascript", "test_command": "npm test" }
  ]
}
```

### Sample `REFORGE_CHANGES.md`

```markdown
# Reforge Changes

*Generated: 2025-05-02T14:33:00+00:00*

**Health score:** 73.5 (+26.5 from previous scan)

## Fixes Applied

- refactor: consolidate duplicate calculate_discount
- fix: remove dead parse_legacy_csv from src/importers/csv.py
- refactor: split handlers.py into auth_handlers.py and order_handlers.py

## Pending Fixes

- resolve circular dep: src/auth/__init__.py ↔ src/middleware/auth.py
- remove _old_validate from src/models/user.py
```

---

## How it works

Reforge works in three phases:

### 1. Scan

`scan_repo` walks the repository with `parse_directory`, feeding each source file to the appropriate tree-sitter adapter (Python, JavaScript/TypeScript, or Go). Tree-sitter builds a full AST — unlike regex, it understands nested scope, decorators, arrow functions, and generics. The adapters extract functions, classes, and imports into typed dataclasses.

From the parse results, three analyses run in sequence:

- **Dead code** — symbols defined but never referenced anywhere in the repo
- **Duplicates** — functions whose normalised bodies share the same SHA-256 hash
- **God files** — files exceeding 500 lines or 10 exported symbols

A dependency graph is built from resolved imports and checked for cycles with DFS. Monorepo subprojects are discovered by scanning subdirectories for marker files (`pyproject.toml`, `package.json`, `go.mod`, `tsconfig.json`).

### 2. Plan

Claude Code receives the structured scan report and uses `get_chunk` to read specific line ranges before deciding what to fix and in what order. The architecture hypothesis, pending fix queue, and health history are all persisted in `reforge-state.json` via `read_memory` / `write_memory` so the plan survives a session restart.

### 3. Fix

`write_fix` applies a unified diff atomically:

1. Creates a `.bak` backup of the target file
2. Best-effort `git stash` before touching the working tree
3. Parses the diff into hunks and applies them with line-offset tracking
4. Runs the optional test command (validated against the allowlist)
5. On any failure — diff parse error, test exit ≠ 0 — restores from `.bak` and returns `rolled_back: true`

`git_commit` stages only the listed files and creates an atomic commit via GitPython. It reads `session_budget` and `confirm_every` from `reforge.toml` and enforces them: once the session budget is exceeded commits are blocked; at every `confirm_every` checkpoint the tool returns `needs_confirmation: true` and waits for `confirmed: true` before proceeding.

---

## Security

| Boundary | Mechanism |
|---|---|
| Path traversal | Every file path is validated against `repo_root` before any read or write — paths that escape the repo root are rejected with `SecurityError` |
| Binary / lock files | `should_skip_file()` blocks binary files, `package-lock.json`, `.yarn.lock`, and files over 10 MB before any processing |
| Test command injection | `write_fix` validates `test_command` against an explicit allowlist (`pytest`, `python3 -m pytest`, `npm test`, `go test ./...`, etc.) before executing |
| Atomic state writes | `reforge-state.json` is always written via `.tmp` → `rename` — a crash mid-write leaves an orphaned `.tmp`, not a corrupt file; `startup_tasks()` cleans these on boot |
| Pre-fix stash | `write_fix` attempts `git stash` before touching the working tree; on rollback the stash is discarded, leaving the repo clean |
| No network calls | The server makes zero outbound network requests; all analysis is local |

---

## Contributing

```bash
# Clone and install
git clone https://github.com/your-org/reforge-mcp.git
cd reforge-mcp
python3 -m venv venv && source venv/bin/activate
pip install -e .
pip install pytest pytest-cov

# Run the full test suite
pytest

# Run with coverage
pytest --cov=src --cov-report=term-missing
```

### Project structure

```
reforge-mcp/
├── src/reforge_mcp/
│   ├── server.py              # FastMCP server — registers all 7 tools
│   ├── tools/
│   │   ├── scan.py            # scan_repo, get_health_score, monorepo detection
│   │   ├── chunk.py           # get_chunk — line-range file reads
│   │   ├── fix.py             # write_fix — diff apply + rollback
│   │   └── git.py             # git_commit — atomic commits with budget enforcement
│   ├── scanner/
│   │   ├── parser.py          # tree-sitter adapters (Python, JS/TS, Go) + QueryCursor wiring
│   │   ├── dead_code.py       # unused symbol detection
│   │   ├── duplicates.py      # body-hash duplicate detection
│   │   └── adapters/          # per-language project-detection stubs
│   └── utils/
│       ├── state.py           # reforge-state.json load/save, gitignore, changelog
│       ├── security.py        # path validation, file guard, command allowlist
│       └── diff.py            # unified diff parser and applier
├── tests/
│   ├── test_scanner.py
│   ├── test_chunk.py
│   ├── test_fix.py
│   ├── test_git.py
│   ├── test_memory.py
│   └── test_monorepo.py
├── pyproject.toml
└── reforge.toml               # optional per-repo config
```

### `reforge.toml` reference

```toml
[fix]
session_budget = 20      # max commits per Claude session before hard stop
confirm_every  = 5       # pause for confirmation every N commits

[scan]
ignore_dirs = ["generated", "vendor"]
```

---

## License

MIT — see [LICENSE](LICENSE).
