![Python 3.11+](https://img.shields.io/badge/python-3.11%2B-blue)
![License MIT](https://img.shields.io/badge/license-MIT-green)
![PRs Welcome](https://img.shields.io/badge/PRs-welcome-brightgreen)

# reforge-mcp

An MCP server that connects Claude Code to your codebase and systematically cleans it up — scanning, planning, and applying fixes one reversible file at a time.

---

![CI](https://github.com/Codewithaiyan/reforge-mcp/actions/workflows/ci.yml/badge.svg)

## What it does

Vibe-coded repos accumulate fast: functions nobody calls, copy-pasted logic in three files, one 900-line god module that does everything, circular imports that break at runtime. Spotting this manually takes hours; fixing it safely takes longer. `reforge-mcp` exposes your codebase to Claude Code as a set of structured tools so it can analyse, prioritise, and apply fixes autonomously — one atomic commit at a time.

### The 10 MCP tools

| Tool | What it does |
|---|---|
| `scan_repo` | AST-parses your repo (Python, JS, TS, Go) and returns dead code, duplicates, god files, the dependency graph with any cycles, and monorepo subprojects |
| `get_chunk` | Reads an exact line-range slice from any file — lets Claude fetch only what it needs without blowing its context window |
| `write_fix` | Applies a unified diff, runs an optional test command, and rolls the file back if either the diff or the tests fail |
| `git_commit` | Stages and commits a named list of files; enforces a per-session budget and confirmation checkpoints |
| `read_memory` | Reads a value from `reforge-state.json` — architecture hypotheses, fix log, pending work, health history |
| `write_memory` | Writes any value atomically to `reforge-state.json` |
| `infer_architecture` | Scans, then guesses the project's shape (REST API, CLI, library, web frontend), its entry points and logical modules, and stores the result as `architecture_hypothesis` |
| `score_risk` | Scores how dangerous it is to change one symbol, 0–100, from inbound references, test coverage, file size and circular deps — with a recommendation string |
| `get_health_score` | Computes a 0–100 health score from scan metrics and appends a timestamped entry to the project's health history |
| `generate_changelog` | Writes `REFORGE_CHANGES.md` from the current session state, with the score delta, fixes applied and pending items |

### Status

The five analyses `scan_repo` reports — dead code, duplicates, god files, the
dependency graph and cycle detection — are each covered by tests and verified by
running the scanner against this repository. Python is the best-exercised
language by a distance; the JavaScript, TypeScript and Go adapters share the
same machinery but have far less test coverage, so treat their findings as
indicative. `write_fix` will not apply a diff that does not match the file.

### Also included

- **Health score trending** — every `get_health_score` call appends to `health_history` so you can chart improvement over time
- **Persistent memory** — `reforge-state.json` survives across Claude Code sessions; stores the architecture hypothesis, fix log and pending work
- **Monorepo support** — `scan_repo` detects Python, JavaScript, TypeScript, Go and Kotlin subprojects from their marker files and returns the correct `test_command` per subproject
- **Changelog generation** — `REFORGE_CHANGES.md` is written on demand with score deltas, applied fixes, and pending items

---

## Installation

**Prerequisites:** Python 3.11+, Claude Code CLI, Git

### From PyPI (recommended)

```bash
pip install reforge-mcp
```

### From source

```bash
git clone https://github.com/codewithaiyan/reforge-mcp.git
cd reforge-mcp
python3 -m venv venv
source venv/bin/activate          # Windows: venv\Scripts\activate
pip install -e .
```

### Register it with Claude Code

```bash
claude mcp add reforge -- reforge-mcp
```

If `reforge-mcp` is not on your `PATH` — which is usual when you installed into
a virtualenv — give the absolute path instead:

```bash
which reforge-mcp                 # Windows: where reforge-mcp
claude mcp add reforge -- /path/from/the/line/above
```

`claude mcp list` should then show `reforge`, and the ten tools become available
in your next session. No API key is needed: the server does no network calls and
Claude Code supplies the model.

<details>
<summary>Using the Claude desktop app instead</summary>

Add it to `claude_desktop_config.json` (`~/Library/Application Support/Claude/`
on macOS, `%APPDATA%\Claude\` on Windows, `~/.config/claude/` on Linux):

```json
{
  "mcpServers": {
    "reforge": {
      "command": "/absolute/path/to/reforge-mcp",
      "args": [],
      "env": {}
    }
  }
}
```

</details>

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

Confirmed — identical bodies. I'll keep the one in src/billing/utils.py and have
src/cart/helpers.py import it.

[calls write_fix("src/cart/helpers.py", diff_str="...", test_command="pytest")]
[calls git_commit("/home/me/myproject", files=["src/cart/helpers.py"], message="refactor: drop duplicate calculate_discount")]

Committed: a3f91c2. Running next fix...
```

### Sample `scan_repo` output

Real output, not an illustration. The repository behind it is four files:
`calculate_discount` copy-pasted into `src/pricing.py` and `src/cart.py`, an
unused `parse_legacy_csv` and `_old_validate`, and `auth.py` and `middleware.py`
importing each other.

```json
{
  "summary": {
    "total_files": 4,
    "total_functions": 7,
    "total_classes": 0,
    "total_imports": 3,
    "total_lines": 41,
    "languages_detected": ["python"]
  },
  "dead_code": [
    { "symbol": "_old_validate",    "file": "auth.py",        "line": 8 },
    { "symbol": "checkout",         "file": "src/cart.py",    "line": 10 },
    { "symbol": "parse_legacy_csv", "file": "src/pricing.py", "line": 7 }
  ],
  "duplicates": [
    {
      "hash": "0a764010605b675494ce6d70c89bb5da7bf02f63589dd69d232c1b057c76569f",
      "locations": [
        { "file": "src/cart.py",    "line": 4, "name": "calculate_discount" },
        { "file": "src/pricing.py", "line": 1, "name": "calculate_discount" }
      ]
    }
  ],
  "god_files": [],
  "dep_graph": {
    "nodes": ["auth.py", "middleware.py", "src/cart.py", "src/pricing.py"],
    "edges": [
      { "from": "auth.py", "to": "middleware.py" },
      { "from": "middleware.py", "to": "auth.py" }
    ],
    "circular": [["auth.py", "middleware.py", "auth.py"]]
  },
  "subprojects": []
}
```

`checkout` is reported dead because nothing in those four files calls it — which
is what the tool promises, and a reminder that a finding is a question for
Claude to answer, not an instruction. On a monorepo, `subprojects` fills in from
the marker files it finds:

```json
"subprojects": [
  { "root": "frontend",        "language": "javascript", "test_command": "npm test" },
  { "root": "services/worker", "language": "go",         "test_command": "go test ./..." }
]
```

Paths use your platform's separator, so they come back with backslashes on
Windows.

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

`scan_repo` walks the repository with `parse_directory`, feeding each source file to the appropriate tree-sitter adapter (Python, JavaScript/TypeScript, Go or Kotlin). Tree-sitter builds a full AST — unlike regex, it understands nested scope, decorators, arrow functions, and generics. The adapters extract functions, classes, and imports into typed dataclasses.

Each parsed file also reports every name it *uses*, collected from the AST while
skipping each definition's own name and the contents of comments and strings.
From the parse results, three analyses run:

- **Dead code** — functions whose name appears in nobody's reference set. Matching is by name, not resolved symbol, so a repo-wide name collision hides a finding: a missed one costs nothing, a wrong one costs you working code. Exempt: dunder methods, conventional entry points, `test_*`, anything listed in `__all__`, and anything carrying a decorator that is not a pure modifier like `@property` — a framework calls its registered functions without naming them anywhere a parser can see
- **Duplicates** — functions whose normalised bodies share the same SHA-256 hash. One-line methods that several classes implement identically are treated as interface conformance, not copy-paste
- **God files** — non-test files over 500 lines or with more than 10 top-level definitions. Methods do not count towards that total

A dependency graph is built from resolved imports — `from x import y`, bare `import x`, relative `from ..pkg import y`, and JS/TS `./path` forms — and checked for cycles with DFS. Imports that resolve outside the repository are external and get no edge. Monorepo subprojects are discovered by scanning subdirectories for marker files (`pyproject.toml`, `package.json`, `go.mod`, `tsconfig.json`).

### 2. Plan

Claude Code receives the structured scan report and uses `get_chunk` to read specific line ranges before deciding what to fix and in what order. The architecture hypothesis, pending fix queue, and health history are all persisted in `reforge-state.json` via `read_memory` / `write_memory` so the plan survives a session restart.

### 3. Fix

`write_fix` applies a unified diff atomically:

1. Creates a `.bak` backup of the target file
2. Parses the diff into hunks and checks every hunk's context and removed lines against the file at the position its header claims
3. Applies the hunks with line-offset tracking — or, if any hunk failed that check, writes nothing at all
4. Runs the optional test command (validated against the allowlist)
5. On any failure — a diff that does not match the file, test exit ≠ 0 — restores from `.bak` and returns `rolled_back: true`

`git_commit` stages only the listed files and creates an atomic commit via GitPython. It reads `session_budget` and `confirm_every` from `reforge.toml` and enforces them: once the session budget is exceeded commits are blocked; at every `confirm_every` checkpoint the tool returns `needs_confirmation: true` and waits for `confirmed: true` before proceeding. The count is held per repository for the life of the server process, so restarting the server starts a new session.

---

## Security

| Boundary | Mechanism |
|---|---|
| Path traversal | Every file path is validated against `repo_root` before any read or write — paths that escape the repo root are rejected with `SecurityError` |
| Binary / lock files | `should_skip_file()` blocks binaries, images, minified bundles, lock files and anything over 500 KB before it is parsed, read or patched |
| Test command injection | `write_fix` validates `test_command` against an explicit allowlist (`pytest`, `python3 -m pytest`, `npm test`, `go test ./...`, etc.) before executing |
| Atomic state writes | `reforge-state.json` is always written via `.tmp` → `rename` — a crash mid-write leaves an orphaned `.tmp`, not a corrupt file; `startup_tasks()` cleans these on boot |
| Mismatched diffs | `apply_diff` rebuilds each hunk's expected old lines from its context and `-` lines and compares them against the file before mutating anything — a stale or wrong diff is rejected whole, leaving the file byte-identical |
| Runaway test commands | The test command runs with no shell, with `stdin` closed and its output going to a file rather than a pipe. A prompt it cannot answer, or a grandchild process holding a pipe open, used to hang the server past its own timeout |
| No network calls | The server makes zero outbound network requests; all analysis is local |

---

## Contributing

```bash
# Clone and install
git clone https://github.com/codewithaiyan/reforge-mcp.git
cd reforge-mcp
python3 -m venv venv && source venv/bin/activate
pip install -e ".[dev]"

# Run the full test suite
pytest

# Run with coverage
pytest --cov=src --cov-report=term-missing
```

### Project structure

```
reforge-mcp/
├── src/reforge_mcp/
│   ├── server.py              # FastMCP server — registers all 10 tools
│   ├── tools/
│   │   ├── scan.py            # scan_repo, get_health_score, monorepo detection
│   │   ├── chunk.py           # get_chunk — line-range file reads
│   │   ├── fix.py             # write_fix — diff apply + rollback
│   │   └── git.py             # git_commit — atomic commits with budget enforcement
│   ├── scanner/
│   │   ├── parser.py          # tree-sitter adapters (Python, JS/TS, Go) + reference collection
│   │   ├── dead_code.py       # unreferenced symbol detection
│   │   ├── duplicates.py      # body-hash duplicate detection
│   │   ├── architecture.py    # project-shape inference
│   │   ├── risk.py            # per-symbol change risk
│   │   └── adapters/          # per-language project-detection stubs
│   └── utils/
│       ├── state.py           # reforge-state.json load/save, gitignore, changelog
│       ├── security.py        # path validation, file guard, command allowlist
│       └── diff.py            # unified diff parser and applier
├── tests/                     # one file per module, plus test_end_to_end.py
│   ├── test_parser.py         #   which drives scan -> fix -> commit for real
│   ├── test_dead_code.py
│   ├── test_duplicates.py
│   ├── test_dep_graph.py
│   ├── test_god_files.py
│   ├── test_diff.py
│   ├── test_fix.py
│   ├── test_git.py
│   ├── test_chunk.py
│   ├── test_memory.py
│   ├── test_monorepo.py
│   ├── test_scanner.py
│   └── test_security.py
├── pyproject.toml
└── reforge.toml               # optional per-repo config
```

### `reforge.toml` reference

```toml
[scan]
ignore = ["generated", "vendor"]   # added to the built-in skip list

[fix]
confirm_every  = 5       # pause for confirmation every N commits
session_budget = 20      # max commits per session, per repo, before a hard stop
```

Those three keys are the whole file. Every one of them is read.

---

## Changelog

See [CHANGELOG.md](CHANGELOG.md). If you used 0.1.0, re-scan: three of the four
analyses returned meaningless output.

## License

MIT — see [LICENSE](LICENSE).
