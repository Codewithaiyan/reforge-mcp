# reforge-mcp — Improvement Plan

Findings from a full review on 2026-10-24 against commit `7039af9`, with the
scanner pointed at its own repository as the test case. Every claim below was
reproduced, not inferred.

**Baseline:** 3,665 LOC src / 904 LOC tests, 50 tests passing (1 Windows-only
symlink failure), 10 MCP tools registered.

**Self-scan result (the headline):**

| Feature | Advertised | Actual on this repo |
|---|---|---|
| Dead code | "symbols defined but never referenced" | **0 of 152 functions** — while `extract_call_sites` is provably unused |
| Duplicates | "identical normalised bodies" | **12 groups, nearly all phantom** — functions reported as duplicates of themselves |
| Circular deps | "DFS over resolved imports" | **0 edges** on a package built from relative imports |
| God files | >500 lines / >10 exports | works (but inflated export counts) |

Three of the four analyses return meaningless output. The health score is
computed from those numbers, so it is meaningless too. That is the real state of
the project, and it is fixable — the parsing layer underneath is sound.

Priorities: **P0** = ships wrong results or can corrupt a user's files.
**P1** = advertised feature that does not work. **P2** = correctness/trust.
**P3** = polish.

---

## P0 — Can damage a repository

### R1. `apply_diff` never verifies the diff matches the file
`src/reforge_mcp/utils/diff.py:29`

It trusts the hunk header's line numbers and does a slice assignment. Python
slice assignment never raises for an out-of-range start, so the `except
IndexError` at line 56 is unreachable. Reproduced against a 3-line file with a
hunk claiming lines 40-42:

```
returned: True
file now: 'a\nb\nc\nREPLACED\n'
```

Wrong input, `success: True`, file silently corrupted. `write_fix` only rolls
back when a test command fails — with `test_command=None` (the default) the
corruption persists, and `git_commit` will commit it. This is the most important
bug in the project: the core promise is safe autonomous edits.

**Fixed 2026-10-24.** `git apply` was the first choice, but `write_fix` is
contracted to work on any directory — the existing tests patch files in a bare
`tmp_path` with no git repo — so delegating to git would have narrowed the tool's
scope. Instead `apply_diff` now builds each hunk's expected old lines from its
context and `-` lines and compares them against the file at the claimed
position, rejecting the entire diff unless every hunk matches. Also fixed in the
same pass: zero-count insertion hunks (`@@ -0,0 +1,1 @@` previously resolved to
index `-1` and inserted before the last line) and hunk headers that disagree
with their own body. Line endings are compared ignoring `\r\n` so an LF diff
still applies to a CRLF file. Covered by `tests/test_diff.py` (10 cases).

Still open from this area: the applier writes the diff's line endings rather
than preserving the file's, so patching a CRLF file with an LF diff mixes
endings. Flagged with a `shortcut:` comment in `diff.py`; not worth fixing until
a mixed-ending repo shows up.

### R2. `_git_stash` before patching can destroy uncommitted work
`src/reforge_mcp/tools/fix.py:11`

If the working tree is dirty, the flow is: stash (target file reverts to HEAD) ->
patch the HEAD version -> `stash pop` into a now-modified file. Best case a
conflict, worst case the patch lands on content the user never saw while their
own edits come back as conflict markers. The `.bak` file already provides
file-level rollback, which is all `write_fix` needs.

**Fixed 2026-10-24.** Both helpers and their four call sites deleted; `fix.py`
went from 133 to 95 lines. The planned dirty-file guard turned out to be
unnecessary: the hazard was created *by* the stash. Without it, patching a dirty
file is safe — the `.bak` captures whatever was on disk, so rollback restores the
user's uncommitted edits rather than HEAD. The two README claims this made false
(the numbered fix sequence and the "Pre-fix stash" security row) were corrected
in the same change.

### R3. `git_commit(files=None)` stages the entire working tree
`src/reforge_mcp/tools/git.py:135`

`repo.git.add(A=True)` contradicts the README ("stages only the listed files")
and the atomic-commit guarantee: unrelated in-flight work gets swept into a
"refactor" commit.

**Fixed 2026-10-24.** `files` is now a required argument, rejected when empty,
and the `add(A=True)` branch is gone. Worth recording: no caller in `src/` and no
test ever omitted `files`, so this was an unreachable branch that existed only to
cause damage — the fix was deletion, not a new guard. FastMCP now advertises the
argument as required, so the tool cannot be called without it.

---

## P1 — Advertised features that do not work

### R4. Dead-code detection has a 100% false-negative rate
`src/reforge_mcp/scanner/dead_code.py:290`

`general_call_pattern` is `(?<![\w.])([a-zA-Z_]\w{2,})\s*\(`. On the line
`def extract_call_sites(` the name is preceded by a space, so the lookbehind
passes and **the definition itself is counted as a call to itself**. Every
function with a 3+ character name is therefore always "called". Hence 0 findings
on a repo with known dead code.

The irony: `call_pattern`, built ten lines above with `(?<!def\s)` and
`(?<!function\s)` precisely to avoid this, is never used.

Secondary defects in the same function:

- Dotted calls are excluded by `(?<![\w.])`, so `obj.method()` never counts as a
  call to `method` — once the self-match bug is fixed, every instance method in
  the scanned repo becomes a false positive.
- References without a call (`handler = my_func`, callbacks, decorator
  arguments) are not counted at all.
- Only line-leading `#` and `//` are skipped, so docstrings and string literals
  containing `foo(` register as calls.
- `__all__` filtering is documented in the module docstring and not implemented.
- Classes are never analysed, despite the docstring claiming classes, imports
  and variables.
- The "is it called from another file" check loops all parse results per
  definition — O(defs x files) for what a set membership test answers.

**Fix:** drop the regex approach entirely. The tree-sitter trees are already
built; add a `call` / `attribute` / `identifier` query per adapter and collect
referenced names from the AST. That removes the comment problem, the dotted-call
problem and the self-match problem in one change, and it is the whole reason the
README argues for AST over regex.

### R5. `extract_call_sites` is 70 lines of code that does nothing
`src/reforge_mcp/scanner/dead_code.py:177`

It builds an empty dict, sets `content = None` inside a `try` that cannot fail,
runs `for func in result.functions: pass`, and returns the empty dict. Nothing in
`src/` or `tests/` calls it. Dead code inside the dead-code detector.

**Fix:** delete it, along with the now-unused `call_pattern`, and resolve the
duplicate module-level definition of `general_call_pattern` at line 290 (defined
*after* its only use — it resolves at call time, which is fragile and confusing).

### R6. Dependency graph resolves zero edges
`src/reforge_mcp/tools/scan.py` — `_build_dependency_graph`

`all_files` is populated inside the same loop that checks
`str(potential_path) in all_files`, so any import pointing at a file later in
iteration order can never match. Combined with relative-import resolution
(`from ..utils.security import X`), the result is 0 edges — which means circular
dependency detection, `dep_graph` in every scan report, and the circular-dep
component of both the health score and `score_risk` are all permanently inert.

**Fix:** two passes — collect `all_files` first, then resolve. Then teach
`_resolve_import_to_file` about leading-dot relative imports and `__init__.py`
packages. Add a test asserting a known two-file cycle is found.

### R7. Decorator extraction returns nothing, so false-positive guards are dead
`src/reforge_mcp/scanner/parser.py`

Every function in `server.py` carries `@mcp.tool()`, yet the parser emits
`decorators=()` for all of them. `FRAMEWORK_DECORATORS`,
`is_decorated_entry_point` and the entire "we exclude `@app.route` and
`@pytest.fixture`" claim in the README are therefore inoperative. Once R4 is
fixed, every Flask route and pytest fixture in a user's repo will be reported as
dead code.

**Fix:** capture `decorated_definition` in the Python query and populate
`decorators`. Test with an `@app.route`-decorated function that is never called
directly.

### R8. Decorated functions are parsed twice
`src/reforge_mcp/scanner/parser.py`

`parse_file` on `server.py` emits 21 functions for 11 real definitions — each
`@mcp.tool()` function appears twice (same name, same line). Consequences:

- `summary.total_functions` is inflated (152 reported for this repo)
- phantom duplicate groups: `scan_repo_tool` is reported as a duplicate of
  itself (see R9)
- every ratio-based health deduction is computed against an inflated denominator

**Fixed 2026-10-24.** My diagnosis above was wrong about the mechanism, and the
real cause is worth recording. The adapter *already had* the right design: a
`processed_nodes` set marks each `function_definition` reached through the
`decorated_definition` query so the plain `function_definition` query can skip
it. It keyed that set on `id(child)` — the **Python object** id. py-tree-sitter
mints a fresh `Node` wrapper on every `.children` access, so the same underlying
node has a different `id()` each time it is reached and the skip never fired.
Confirmed directly:

```
same python object : False
id() equal         : False
node.id equal      : True
```

The fix is `child.id` instead of `id(child)` in two places — `Node.id` is the
stable tree-sitter node identity. No dedupe pass on `ParseResult` was needed.
`server.py` went from 21 reported functions to its real 11, and the self-scan's
duplicate groups fell from 12 to 1.

Only the Python adapter had this pattern; the JS/TS/Go adapters have no
`decorated_definition` handling, so they were never affected.

### R9. Duplicate detection reports noise
`src/reforge_mcp/scanner/duplicates.py:150`

12 groups on a repo with essentially no copy-paste. Two distinct causes:

- R8's double-emission creates self-duplicates.
- Trivial bodies are not filtered: the four language adapters each define
  `def get_language(self): return Language(...)` — correct interface
  implementations, not refactorable duplication.

**Partly fixed 2026-10-24 by R8** — the self-duplicates are gone and the count
is down from 12 groups to 1. The survivor is the real case: the four adapters'
`get_language` methods.

**Fix for what remains:** skip groups whose members are all overrides of the
same interface method. Note the constraint before reaching for a blanket
"minimum body size" filter, which was my first instinct: `tests/test_scanner.py`
depends on a genuine cross-file duplicate whose body is a single
`return sum(items)`, so filtering every one-line body would hide real
duplication as well as this noise. Same-name-same-signature across sibling
classes is the signal to suppress, not body length.

### R10. `detect_similar_functions` is a stub, and its dependency costs ~2 GB
`src/reforge_mcp/scanner/duplicates.py:249`

The function logs `"Similar function detection not implemented (requires
embeddings)"`. Meanwhile `sentence-transformers` sits in `[project]
dependencies` and is imported nowhere — so `pip install reforge-mcp` pulls
PyTorch for a `logger.debug`. `rich` is also unused.

**Fix:** drop both from `dependencies`. If the embedding path is ever built, add
`[project.optional-dependencies] semantic = ["sentence-transformers"]` and
import lazily inside the function.

---

## P2 — Correctness and trust

### R11. `session_budget` is a lifetime budget with no reset
`src/reforge_mcp/tools/git.py:92`

`fix_count` is persisted to `.reforge-session.json` and only ever incremented.
There is no session id, no timestamp, and no reset path — so after 20 commits
*ever*, every call fails with "Start a new session to continue" and no way to
start one short of deleting the file by hand.

**Fix:** store `{session_id, started_at, fix_count}`; treat a new server process
(or a gap beyond N hours) as a new session. Add a `reset_session` tool or accept
`reset=True` on `git_commit`.

### R12. `reforge.toml` is largely decorative
`reforge.toml`, `src/reforge_mcp/tools/scan.py:181`

- `_load_ignore_dirs` reads top-level `config.get("ignore_dirs")`. The shipped
  file has `[scan] ignore`. The README documents `[scan] ignore_dirs`. Three
  spellings, none agree — the key never resolves and the user's ignore list is
  silently discarded.
- Never read anywhere: `test_before_fix`, `atomic_commits`, `dry_run`,
  `max_file_size_kb`, `skip_extensions`, `auto_detect`.
- `dry_run = true` is commented as a "safe default that requires explicit opt-in
  before any modifications are made". It is ignored. `write_fix` writes. A user
  who reads that comment and trusts it will lose data.

**Fix:** one config loader module, one documented schema, read at every point
that has a corresponding knob. Delete keys that are not wired.

**`dry_run` resolved 2026-10-24 by deleting the key.** Implementing it faithfully
was the worse option in both directions: as shipped (`dry_run = true`) it would
have disabled `write_fix` for every user who has a `reforge.toml`, breaking the
entire autonomous flow by default; defaulting it to `false` would have
contradicted the file it ships in. The preview path already exists — Claude shows
the diff in chat before calling `write_fix`, and `get_chunk` reads the current
content. A three-line reinstatement is available if a real need appears; a
comment promising "no modifications are made" while the tool writes is worse
than no option at all.

The rest of R12 (the `ignore` / `ignore_dirs` mismatch and the five other
unwired keys) stays open as R12b in M2.

### R13. `write_fix` has no default test-command allowlist
`src/reforge_mcp/tools/fix.py:59`

`validate_test_command(test_command, allowed_test_commands or [])` — if the
caller passes no allowlist, the loop over `allowed_commands` matches nothing and
every command is rejected. The README advertises a built-in allowlist
(`pytest`, `npm test`, `go test ./...`), so documented and actual behaviour
differ, and the useful path requires the *caller* to supply the allowlist, which
is not a security boundary at all.

**Fix:** a module-level `DEFAULT_ALLOWED_TEST_COMMANDS` used when the argument is
omitted. Keep the chaining-operator rejection; it is good.

### R14. `shell=True` for the test command
`src/reforge_mcp/tools/fix.py:103`

Mitigated by the operator blocklist, but prefix matching plus a shell is a
weaker boundary than it needs to be: `pytest --foo=$(...)` is blocked only
because `$(` is in the blocklist, which is an enumerate-the-bad approach.

**Fix:** `shlex.split` and run without a shell. Validate `argv[0]` against the
allowlist. Strictly simpler and strictly safer.

### R15. God-file export counts are inflated and the thresholds are unexplained
`src/reforge_mcp/tools/scan.py` — `_find_god_files`

`server.py` is flagged with "21 exports" for 11 definitions (R8), and
`tests/test_security.py` is flagged as a god file — test files should not be
judged by production thresholds. 500 lines / 10 exports are presented as facts
with no justification or override.

**Fix:** fix the count via R8, exclude test paths (or report them in a separate
bucket) and move both thresholds into config.

### R16. Windows-only test failure
`tests/test_security.py` — `test_symlink_to_outside_blocked`

`os.symlink` raises `WinError 1314` without Developer Mode or elevation. CI is
Linux so it passes there, but the suite is red for Windows contributors.

**Fix:** `@pytest.mark.skipif` on a probe for symlink privilege.

### R17. CI tests one platform and one Python version
`.github/workflows/ci.yml`

A tool that edits files, resolves paths and shells out is exactly the kind of
code that breaks on Windows path separators and CRLF. The self-scan output above
shows `src\reforge_mcp\...` separators leaking into report payloads.

**Fix:** matrix over ubuntu/macos/windows x 3.11/3.12/3.13. Normalise report
paths to forward slashes so output is stable across platforms.

---

## P3 — Polish and credibility

### R18. README does not describe the shipped software

- Claims "The 7 MCP tools"; `server.py` registers **10** —
  `infer_architecture_tool`, `score_risk_tool` and `generate_changelog_tool` are
  undocumented.
- Tells users to `export ANTHROPIC_API_KEY`, two sections above a security table
  stating "zero outbound network requests". No key is needed.
- Documents `claude_desktop_config.json`; for Claude Code the path is
  `claude mcp add` / `.mcp.json`.
- The `reforge.toml` reference block does not match the shipped file (R12).
- Shows `scan_repo` returning clean findings, which the self-scan contradicts.

**Fix:** regenerate the tool table from `server.py`, drop the API-key step, fix
the install instructions, and do not re-publish sample output until R4/R6/R9 are
fixed.

### R19. No end-to-end test of the one flow that matters
`tests/`

There is no test that scans a scratch repo, applies a real diff, runs tests, and
asserts the file is correct afterwards — or that a *bad* diff leaves the file
byte-identical. R1 would have been caught on day one by the latter.

**Fix:** one integration test with a temp git repo: good diff applies; bad diff
is rejected and the file is unchanged; failing test command triggers rollback;
`rolled_back` is accurate in every case.

### R20. `parser.py` is 1,061 lines and flagged by the project's own tool

Four adapters, the query strings, the directory walker and the dataclasses in one
file. The tool flags it as a god file — eating the project's own dog food is free
credibility.

**Fix:** `adapters/{python,javascript,typescript,golang}.py` already exist as
7-line stubs. Move each adapter into its matching stub and leave `parser.py` as
the dataclasses plus `parse_file` / `parse_directory`.

### R21. `embeddings_cache` and `ttl_seconds` are vestigial
`src/reforge_mcp/utils/state.py:27`, `src/reforge_mcp/server.py:113`

`embeddings_cache` is an always-empty state key for the unbuilt R10 feature.
`write_memory_tool` accepts `ttl_seconds` and documents that it is "accepted but
not enforced" — an argument that does nothing is worse than no argument.

**Fix:** delete both.

### R22. Version and status say "alpha"; the README reads like 1.0

`pyproject.toml` is `0.1.0` / `Development Status :: 3 - Alpha`, which is honest.
The README is not. Keep the version, add a short "Status: alpha — dead-code and
dependency-graph analysis are being rebuilt" line until P1 is closed.

---

## Suggested order

1. **Stop the bleeding (R1, R2, R3, R12-`dry_run`)** — nothing else matters while
   the tool can corrupt files. Do not publish to PyPI before this.
2. **Make the analyses real (R8, R7, R4, R6, R9)** — in that order; R8 and R7 are
   parser fixes the rest depend on.
3. **Trim (R5, R10, R21)** — pure deletion, shrinks the install by roughly 2 GB.
4. **Harden (R13, R14, R11, R19, R16, R17)**.
5. **Tell the truth (R18, R22)**, then split `parser.py` (R20) and ship.

A good finish line for v0.2.0: the scanner run on its own repository finds
`extract_call_sites` as dead code, reports zero phantom duplicates, draws a
non-empty dependency graph, and a deliberately bad diff cannot change a single
byte on disk.
