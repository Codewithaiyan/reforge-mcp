[![PyPI](https://img.shields.io/pypi/v/reforge-mcp)](https://pypi.org/project/reforge-mcp/)
![Python 3.11+](https://img.shields.io/badge/python-3.11%2B-blue)
![License MIT](https://img.shields.io/badge/license-MIT-green)
![PRs Welcome](https://img.shields.io/badge/PRs-welcome-brightgreen)


[![Agensi](https://img.shields.io/badge/Agensi-reforge%20skill-2563eb)](https://www.agensi.io/skills/reforge)

> **Also available as an agent skill on [Agensi](https://www.agensi.io/skills/reforge).** The skill teaches your agent the full reforge workflow (scan → score → plan → fix → commit). Install reforge-mcp first, then add the skill.


#
Available on Glama - https://glama.ai/mcp/servers/Codewithaiyan/reforge-mcp

[![reforge-mcp MCP server – quality and maintenance score on Glama](https://glama.ai/mcp/servers/Codewithaiyan/reforge-mcp/badges/score.svg)](https://glama.ai/mcp/servers/Codewithaiyan/reforge-mcp)

[![reforge-mcp MCP server – quality and maintenance score on Glama](https://glama.ai/mcp/servers/Codewithaiyan/reforge-mcp/badges/card.svg)](https://glama.ai/mcp/servers/Codewithaiyan/reforge-mcp)




# reforge-mcp

An MCP server that gives Claude Code structured tools over your codebase — dead code, duplicates, god files, the dependency graph — and tells you what it could not read.

Reports expose their limits: the health result's `coverage` is the fraction of counted source files analysed, `summary.parse_failures` counts files the parser could not read, and `dep_graph.unresolved_relative_imports` counts unresolved relative imports of supported source files. `get_health_score` returns `score: null` when no files were analysed. Coverage is not test coverage, and unsupported source extensions are counted from a fixed list.

The skill source is in [`skills/reforge/SKILL.md`](skills/reforge/SKILL.md).

---

![CI](https://github.com/Codewithaiyan/reforge-mcp/actions/workflows/ci.yml/badge.svg)

## What it does

Repos built quickly with AI can accumulate unused functions, copied logic, oversized modules and circular imports. `reforge-mcp` gives Claude Code structured findings so it can inspect the source, prioritize changes, apply patches with optional tests, and create local Git commits. Findings and risk scores are heuristics that need review before deleting or changing code.

### The 10 MCP tools

These are the exact registered MCP names; Python wrapper functions have a `_tool` suffix.

| Registered tool | What it does | File effects |
|---|---|---|
| `scan_repo` | Reports dead-code candidates, duplicates, oversized modules, dependencies and subprojects for supported source files. | Read-only |
| `get_chunk` | Reads an inclusive, 1-indexed line range from a UTF-8 file. | Read-only |
| `get_health_score` | Computes health and analysis coverage, then appends a timestamped history entry. | Writes state and backups |
| `write_fix` | Patches one existing file, optionally runs tests, and attempts rollback if the patch or tests fail. | Writes source and recovery backups; tests may write files |
| `git_commit` | Stages named files and commits the index within session budgets and confirmation checkpoints. | Writes Git index/history; may switch branches and run hooks |
| `infer_architecture` | Infers a likely pattern, entry points and modules, then saves `architecture_hypothesis`. | Writes state and backups |
| `read_memory` | Reads a top-level state value, with defaults when state is missing or unreadable. | Read-only |
| `write_memory` | Creates or replaces a top-level state value through a staged write. | Writes state and backups |
| `score_risk` | Estimates change risk from symbol-name references, referencing tests, file size and cycles. | Read-only |
| `generate_changelog` | Writes a timestamped Markdown report from saved health history, fixes and pending work. | Overwrites `REFORGE_CHANGES.md` |

State lives in `reforge-state.json`. State writes rotate up to five timestamped
backups. `infer_architecture` is a writing tool despite doing analysis first.
The server entry point also adds Reforge entries to `.gitignore` and removes
top-level `*.tmp` files in its working directory at startup.

### Status

Verified against **21 open-source repositories** across three validation
sweeps — django, flask, fastapi, scrapy, pydantic, requests, express, axios,
react, vue, svelte, zod, nest, cobra, gin, caddy, prometheus, okhttp, ktor,
nowinandroid and ripgrep. Those sweeps found and closed **17 defects**,
including two languages whose tree-sitter queries had never compiled at all
and a Python dependency graph that had been mostly missing for nine
releases. Every one is reproduced and documented in
[IMPROVEMENTS.md](IMPROVEMENTS.md).

CI runs lint and the test suite on Linux and Windows with Python 3.11, 3.12 and 3.14.

What is still true, and worth knowing before you trust a number:

- **A Go dependency graph is roughly 1% resolved.** Go imports are module
  paths that need `go.mod` to resolve; caddy reports 31 edges from 3,321
  imports. Treat Go dependency and risk results as incomplete.
- **A whole-repo scan of a large project is summarised, not complete.** Long
  lists are capped to reduce the context needed — a 3,000-file
  repository comes back around 170 KB instead of 1.2 MB. Every count stays
  exact, and `truncated` names each list that was shortened with its real
  length, so a short list is never mistaken for a complete one.
- **Dead-code detection is name-based**, with no type resolution. It is
  deliberately biased toward missing a finding rather than inventing one,
  because the advice is "delete this".
- **Successful patches preserve recovery information.** `write_fix` rejects
  mismatched diff hunks and keeps a byte-exact `.reforge-bak` copy after a
  successful patch when the file was modified, untracked or outside Git.
  When Git already holds the original contents, `backup` is null.

### Also included

- **Health score trending** — every `get_health_score` call appends to `health_history` so you can chart improvement over time
- **Persistent memory** — `reforge-state.json` survives across Claude Code sessions; stores the architecture hypothesis, fix log and pending work
- **Monorepo support** — `scan_repo` finds subprojects from `pyproject.toml`, `setup.py`, `package.json`, `tsconfig.json` and `go.mod`. It suggests a conventional test command; it does not verify that command or detect Kotlin/Gradle subprojects. When markers overlap, the first matching marker wins.
- **Changelog generation** — `REFORGE_CHANGES.md` is written on demand with score deltas, applied fixes, and pending items

---

## Installation

**Prerequisites:** Python 3.11+, Git, and Claude Code or Claude Desktop.

**API keys:** Reforge does not require `ANTHROPIC_API_KEY` or another model API
key. Its analysis and state tools run locally without calling an external
model; Claude Code or Claude Desktop manages its own model access. Test commands
launched by `write_fix` and Git hooks invoked by `git_commit` may have their own
network activity.

### Claude Code

```bash
pip install reforge-mcp
claude mcp add reforge-mcp -- reforge-mcp
```

Run `claude mcp list` to check that `reforge-mcp` is registered, then start a
new session to use its ten tools. The executable must be on the client's `PATH`.
To request an upgrade, run `pip install --upgrade reforge-mcp`; the selected
version also depends on your Python version and configured package index.

### Claude Desktop

```bash
pip install reforge-mcp
```

Add this to `claude_desktop_config.json`, merging it with any existing
`mcpServers` entries:

```json
{
  "mcpServers": {
    "reforge-mcp": {
      "command": "reforge-mcp",
      "args": []
    }
  }
}
```

The config is in `~/Library/Application Support/Claude/` on macOS or
`%APPDATA%\Claude\` on Windows. Restart Claude Desktop after saving. Its process
must be able to find `reforge-mcp` on `PATH`; a terminal's activated virtualenv
does not automatically change a desktop application's environment.

### From source

```bash
git clone https://github.com/Codewithaiyan/reforge-mcp
cd reforge-mcp
python3 -m venv venv
source venv/bin/activate          # PowerShell: .\venv\Scripts\Activate.ps1
pip install -e .
```

For a source install in a virtualenv, the executable is `venv/bin/reforge-mcp`
(Windows: `venv\Scripts\reforge-mcp.exe`). If the client cannot find it, use its
absolute path as the Claude Desktop `command` or after `--` in the Claude Code
registration command. `which reforge-mcp` (PowerShell: `Get-Command reforge-mcp`)
shows the executable from an activated environment.

---

## Usage

### Example session with Claude Code

Illustrative session; the counts and commit hash below are examples.

```
You: Use reforge-mcp to scan my repo at /home/me/myproject and fix the top issues.

Claude: I'll start with a full scan.

[calls scan_repo("/home/me/myproject")]

The scan found:
- 14 dead functions across 6 files
- 3 duplicate implementations of `calculate_discount`
- 1 god file: src/api/handlers.py (847 lines, 23 exports)
- 1 circular dependency: auth → middleware → auth

[calls get_health_score(repo_path="/home/me/myproject")]
Health score: 47/100

Let me fetch the duplicate implementations to confirm they're identical.

[calls get_chunk(file_path="/home/me/myproject/src/billing/utils.py", repo_root="/home/me/myproject", start_line=12, end_line=28)]
[calls get_chunk(file_path="/home/me/myproject/src/cart/helpers.py", repo_root="/home/me/myproject", start_line=5, end_line=21)]

Confirmed — identical bodies. I'll keep the one in src/billing/utils.py and have
src/cart/helpers.py import it.

[calls write_fix(file_path="/home/me/myproject/src/cart/helpers.py", repo_root="/home/me/myproject", diff_str="...", test_command="pytest")]
[calls git_commit("/home/me/myproject", files=["src/cart/helpers.py"], message="refactor: drop duplicate calculate_discount")]

Committed: a3f91c2. Running next fix...
```

### Sample `scan_repo` output

Illustrative excerpt from a four-file repository; additional summary and graph
diagnostics are omitted here for brevity. The example has
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

`checkout` is a dead-code candidate because nothing in those four files references
its name. A finding is a question for Claude to check, not a deletion instruction.
On a monorepo, `subprojects` fills in from
the marker files it finds:

```json
{
  "subprojects": [
    { "root": "frontend",        "language": "javascript", "test_command": "npm test" },
    { "root": "services/worker", "language": "go",         "test_command": "go test ./..." }
  ]
}
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

When Git reports a nonempty tracked-file list, only those files are analysed;
outside Git or with an empty index, all eligible files are analysed. `languages`
can filter supported languages. `include_tests` is currently accepted but does
not filter test files, whether true or false.

A missing root or a root that is a file returns an explicit `error` report.
Existing directories without Git are still supported, including empty directories
and extracted source archives.

Each parsed file also collects reference names from the AST while
skipping each definition's own name and the contents of comments and strings.
From the parse results, three analyses run:

- **Dead code** — functions whose name appears in nobody's reference set. Matching is by name, not resolved symbol, so a repo-wide name collision hides a finding: a missed one costs nothing, a wrong one costs you working code. Exempt: dunder methods, conventional entry points, `test_*`, anything listed in `__all__`, and anything carrying a decorator that is not a pure modifier like `@property` — a framework calls its registered functions without naming them anywhere a parser can see
- **Duplicates** — functions whose normalised bodies share the same SHA-256 hash. One-line methods that several classes implement identically are treated as interface conformance, not copy-paste
- **God files** — non-test files over 500 lines or with more than 10 top-level definitions. Methods do not count towards that total

A dependency graph is built from resolved imports — `from x import y`, bare `import x`, relative `from ..pkg import y`, and JS/TS `./path` forms — and checked for cycles with DFS. Imports that resolve outside the repository are external and get no edge. Monorepo subprojects are discovered by scanning subdirectories for marker files (`pyproject.toml`, `package.json`, `go.mod`, `tsconfig.json`).

### 2. Plan

Claude Code receives the structured scan report and uses `get_chunk` to read specific line ranges before deciding what to fix and in what order. `infer_architecture` saves its hypothesis, and `get_health_score` appends history. The agent must use `write_memory` to maintain its fix log and pending queue; patches and commits do not update those lists automatically. `read_memory` retrieves saved values in later sessions.

### 3. Fix

`write_fix` validates a unified diff before writing the target:

1. Creates a unique byte-for-byte backup ending in `.reforge-bak` beside the existing target file
2. Parses the diff into hunks and checks every hunk's context and removed lines against the file at the position its header claims
3. Applies the hunks with line-offset tracking — or, if any hunk failed that check, writes nothing at all
4. Runs the optional test command (validated against the allowlist)
5. On a mismatched diff or test failure, attempts to restore the backup and returns `rolled_back: true`. This flag records the rollback path, not independent verification that restoration succeeded; filesystem failures can prevent recovery.

`git_commit` stages the listed files and commits the Git index via GitPython.
It returns an error when the staged index has no changes to commit; a refused
empty commit does not consume the session budget.
**Previously staged changes are also included**, so review the index first;
`files_committed` echoes the requested file list, not the full commit contents.
The tool reads `session_budget` and `confirm_every` from `reforge.toml`: commits
are blocked when the budget is reached, and the next call after each
`confirm_every` group returns `needs_confirmation: true` until retried with
`confirmed: true`. The count is held per repository for the life of the server
process, so restarting the server starts a new session. This tool does not push.

---

## Security

| Boundary | Mechanism |
|---|---|
| Source-file boundaries | Parsing, `get_chunk` and `write_fix` validate source paths against the supplied repository boundary. Relative `file_path` values resolve from the server working directory, not `repo_root`. State/report tools use the caller-supplied `repo_path` as their destination |
| File guards | Parsing skips configured binary/lock/minified files and files over 500 KiB. `get_chunk` retains the file-type guards but permits large files. `write_fix` does not apply those file-type/size guards |
| Test command injection | `write_fix` validates `test_command` against an explicit allowlist (`pytest`, `python3 -m pytest`, `npm test`, `go test ./...`, etc.) before executing |
| Staged state writes | State is serialized to `reforge-state.tmp`, the previous file is backed up and removed, then the temporary file is renamed. This is not a fully atomic replacement: a crash between removal and rename can leave no state file. Startup removes top-level `*.tmp` files in its working directory |
| Mismatched diffs | `apply_diff` rebuilds each hunk's expected old lines from its context and `-` lines and compares them against the file before mutating anything — a stale or wrong diff is rejected whole, leaving the file byte-identical |
| Runaway test commands | The test command runs with no shell, with `stdin` closed and its output going to a file rather than a pipe. A prompt it cannot answer, or a grandchild process holding a pipe open, used to hang the server past its own timeout |
| Local analysis | Reforge's analysis and state tools make no outbound API calls. The AI client's model requests, user-supplied test commands and Git hooks have their own network behavior |

---

## Contributing

```bash
# Clone and install
git clone https://github.com/Codewithaiyan/reforge-mcp
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
│   ├── tool_results.py        # TypedDict output schemas for MCP results
│   ├── tools/
│   │   ├── scan.py            # scan_repo, get_health_score, monorepo detection
│   │   ├── chunk.py           # get_chunk — line-range file reads
│   │   ├── fix.py             # write_fix — diff apply + rollback
│   │   └── git.py             # git_commit — atomic commits with budget enforcement
│   ├── scanner/
│   │   ├── parser.py          # tree-sitter adapters (Python, JS/TS, Go, Kotlin) + reference collection
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

See [CHANGELOG.md](CHANGELOG.md). **If you used any earlier version, re-scan.** Three validation sweeps changed what the analyses report: TypeScript and Go parsed nothing at all before 0.3.0, Python dependency graphs were mostly missing before 0.4.0, and dead-code findings in Go, Kotlin and TypeScript included whole classes of false positive.

## License

MIT — see [LICENSE](LICENSE).
