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

**Fixed 2026-10-24.** The regex path is gone. `ParseResult` gained a
`references` field, filled by one generic `_collect_references` walker in
`parser.py` that all three adapters call — no per-language queries were needed,
because `identifier` / `property_identifier` / `field_identifier` cover all four
grammars. The walker skips the first name child of any definition node (the
self-match bug), skips `comment` and string nodes (the docstring bug), and
collects `__all__` string contents as references (R4b). `find_dead_code` is now
set arithmetic over those names, and lost the unused `repo_root` parameter along
with the O(defs x files) loop.

`dead_code.py`: 405 -> 217 lines, and R5 was deleted as part of it.

**Self-scan: 6 findings, every one genuine, no false positives.**

```
hash_body               duplicates.py:134   (duplicate of parser._hash_body)
find_similar_functions  duplicates.py:223   (the R10 stub)
get_language            parser.py:147,295,550,769  (declared and implemented, never called)
```

Two false-positive classes showed up on the first run and were fixed before
this was called done:

- **pytest tests (66 of the original 73 findings).** A runner collects `test_*`
  by naming convention, so nothing references them. Added to
  `is_entry_point_name`.
- **This project's own `@mcp.tool()` functions** — see R4d below.

**R4d: the decorator rule is now a denylist.** R7 flagged that
`FRAMEWORK_DECORATORS` was an allowlist that could never be complete. Confirmed
on the first self-scan: all ten `@mcp.tool()` functions were reported dead. The
30-line allowlist is replaced by `NEUTRAL_DECORATORS` — the five or so
decorators that change *how* a function is invoked rather than *whether*
something invokes it (`property`, `staticmethod`, `classmethod`,
`functools.wraps`, `functools.cache`, `abstractmethod`, `overload`). Any other
decorator is taken as evidence of a framework caller. This errs toward false
negatives, which is the trade this module's own docstring asks for, and it
needs no maintenance as frameworks come and go.

One deliberate consequence: a `@property` that nothing ever reads is now
reported, where the old allowlist exempted it. That is correct — a property is
reached by attribute access, which the walker already collects.

### R5. `extract_call_sites` is 70 lines of code that does nothing
`src/reforge_mcp/scanner/dead_code.py:177`

It builds an empty dict, sets `content = None` inside a `try` that cannot fail,
runs `for func in result.functions: pass`, and returns the empty dict. Nothing in
`src/` or `tests/` calls it. Dead code inside the dead-code detector.

**Fixed 2026-10-24 as part of R4.** Deleted with the rest of the regex path:
`extract_call_sites`, the unused `call_pattern`, both copies of
`general_call_pattern`, and the `FRAMEWORK_DECORATORS` allowlist.

Postscript worth keeping: the rewritten detector, run on this repo, reports
`find_similar_functions` and `hash_body` as dead — so the tool now finds the
same *class* of defect in its own source that R5 was. It cannot demonstrate it
on `extract_call_sites` itself, because that function no longer exists; the
equivalent case is covered synthetically by
`test_definition_is_not_a_reference_to_itself`.

### R6. Dependency graph resolves zero edges
`src/reforge_mcp/tools/scan.py` — `_build_dependency_graph`

`all_files` is populated inside the same loop that checks
`str(potential_path) in all_files`, so any import pointing at a file later in
iteration order can never match. Combined with relative-import resolution
(`from ..utils.security import X`), the result is 0 edges — which means circular
dependency detection, `dep_graph` in every scan report, and the circular-dep
component of both the health score and `score_risk` are all permanently inert.

**Fixed 2026-10-24.** The loop-ordering bug was real but it was not the whole
story — fixing it alone would have changed nothing, because **the Python adapter
never captured a relative import in the first place**. Two separate defects:

1. The query required `module_name: (dotted_name)`, which does not match
   `from ..scanner.dead_code import x` — that statement's `module_name` is a
   `relative_import` node, so the whole statement failed to match and was
   invisible. Now `[(dotted_name) (relative_import)]`.
2. The handler picked the *first `dotted_name` child* as the module. In a
   relative import the first one is the **imported name**, so even a matched
   statement would have recorded `find_dead_code` as the module and then
   dropped the record for having no names. Now reads
   `child_by_field_name("module_name")`.

With imports visible, `_build_dependency_graph` collects `all_files` in its own
pass first, and `_resolve_import_to_file` resolves against that parsed-file set
instead of touching the filesystem — so resolution no longer depends on the
process working directory, which was a latent bug of its own. It handles Python
relative dots, JS/TS `./` paths, `__init__.py` packages and `index.js`/`index.ts`.

**Self-scan: 0 -> 24 edges, all correct** (`server.py -> scan.py`,
`dead_code.py -> parser.py`, and so on). `circular` is `[]` because this repo
genuinely has no cycles; `_detect_cycles` turned out to be correct all along and
is now proven by a synthetic two-file cycle in the tests.

Downstream: `score_risk`'s circular-dependency factor and the health score's
`circular_count` now receive real data. The health score reads 75.0 and is for
the first time computed from inputs that mean something.

### R7. Decorator extraction returns nothing, so false-positive guards are dead
`src/reforge_mcp/scanner/parser.py`

Every function in `server.py` carries `@mcp.tool()`, yet the parser emits
`decorators=()` for all of them. `FRAMEWORK_DECORATORS`,
`is_decorated_entry_point` and the entire "we exclude `@app.route` and
`@pytest.fixture`" claim in the README are therefore inoperative. Once R4 is
fixed, every Flask route and pytest fixture in a user's repo will be reported as
dead code.

**Fixed 2026-10-24.** Two independent causes, both confirmed against the real
grammar:

```
decorated_definition
  decorator            | @mcp.tool()      | children: ['@', 'call']
  decorator            | @property        | children: ['@', 'identifier']
  function_definition  | def h(): ...     | children: ['def','identifier','parameters',':','block']
```

1. `extract_function` looked for `decorator` children of the
   `function_definition`. The grammar hangs them off the enclosing
   `decorated_definition`, so that branch was unreachable dead code.
2. Even reached, it only assembled `identifier` and `.` children — so
   `@mcp.tool()` and `@app.route("/x")`, whose child is a `call` node, would
   still have produced nothing.

Decorators are now read from the parent `decorated_definition` as node text with
`@` stripped and the argument list cut at the first `(`, which handles all four
shapes in one line. `is_decorated_entry_point` works as designed again.

**Open question this exposes, to settle in R4:** `FRAMEWORK_DECORATORS` is an
allowlist that can never be complete — it has no `mcp.tool`, so this project's
own ten tool functions would be reported dead the moment R4 starts working, and
every user's `@celery.task` or `@typer.command` has the same problem. The
inverse rule is both smaller and matches the module's stated preference for
false negatives: *any* decorator implies something else calls the function,
except a known set of reachability-neutral ones (`property`, `staticmethod`,
`classmethod`, `functools.wraps`, `functools.cache`). Deferred to R4, where the
filter actually runs and can be tested.

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

**Finished 2026-10-24.** The surviving group is suppressed by
`_is_shared_interface_method`, which is deliberately narrow: every member must
be a **method** (its name appears in some class's method list in that file)
*and* have a one-line body. A duplicated module-level function stays reported
however short it is — that is the case this tool exists to find. Two tests pin
both sides of that line, including the short cross-file duplicate
`tests/test_scanner.py` depends on, so over-filtering fails the suite.

Two more defects found while in the file, both now fixed:

- **`hash_body` and `normalize_code` were a dead second implementation** of
  `parser._hash_body`. The adapters hash through the parser, so this module's
  entire documented normalization never ran. `_hash_body` does normalize, so the
  behaviour was right — but 72 lines of it existed twice, and the dead-code
  detector had already flagged `hash_body`. Deleted. (`normalize_code` was
  reachable only from `hash_body`, so it was transitively dead — the detector
  does not chase transitive reachability, which is worth knowing about its
  output.)
- **The `line_count` lookup was O(groups x all functions)** with an inner
  `break` that left the outer loop scanning every remaining file. Replaced by a
  `(file, line) -> FunctionInfo` index built in the pass that already walks
  every function.

**Self-scan: 0 duplicate groups**, down from 12.

### R10. `detect_similar_functions` is a stub, and its dependency costs ~2 GB
`src/reforge_mcp/scanner/duplicates.py:249`

The function logs `"Similar function detection not implemented (requires
embeddings)"`. Meanwhile `sentence-transformers` sits in `[project]
dependencies` and is imported nowhere — so `pip install reforge-mcp` pulls
PyTorch for a `logger.debug`. `rich` is also unused.

**Fixed 2026-10-24.** `find_similar_functions` is deleted and both packages are
out of `dependencies` — confirmed first that neither is imported anywhere in
`src/` or `tests/`. `uv.lock` shed **939 lines**; torch and every nvidia CUDA
package are gone from the resolution.

No optional extra was added. An extra for a feature that does not exist is just
a slower way to keep the claim; when the embedding path is actually built it can
declare its own.

---

## P2 — Correctness and trust

### R11. `session_budget` is a lifetime budget with no reset
`src/reforge_mcp/tools/git.py:92`

`fix_count` is persisted to `.reforge-session.json` and only ever incremented.
There is no session id, no timestamp, and no reset path — so after 20 commits
*ever*, every call fails with "Start a new session to continue" and no way to
start one short of deleting the file by hand.

**Fixed 2026-10-24 by deleting the persistence instead.** The plan above was
three fields and a new tool; none were needed. `.reforge-session.json` existed
only to carry the count across restarts, and that was the entire defect — the
server process already *is* the session, under stdio transport one process per
client. The count is now a module-level `dict[repo_path, int]`, so it resets
when the process does, and the error message's "Start a new session to
continue" is literally true for the first time.

Per-repo keying is kept (one server may be pointed at several repos), and
`_load_session` / `_save_session` / `_SESSION_FILE` / `import json` are gone -
`git.py` 175 -> 164 lines. The redundant `.reforge-session.json` gitignore entry
went too; `.reforge*` already covered it and the file is no longer written.

No README change was needed: it already said "max commits per Claude session
before hard stop", which the code simply did not implement. One clause was added
to say where the session boundary is.

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

**R12b finished 2026-10-24.** `_load_ignore_dirs` now reads
`[scan] ignore` — the key both the shipped file and the README use — instead of
a top-level `ignore_dirs` that matched neither. A test proves a configured
directory is actually skipped, which nothing checked before.

The five keys nothing read (`test_before_fix`, `atomic_commits`,
`max_file_size_kb`, `skip_extensions`, `auto_detect`) are deleted rather than
wired. Wiring them would have meant threading config through `parse_directory`
into `should_skip_file` for file-size and extension limits whose defaults are
already sensible, and adding switches for an atomic-commit mode that is the only
mode and a test-before-fix step `write_fix`'s `test_command` already covers.
`reforge.toml` is now three keys, all of them read, with a comment at the top
saying so.

Also removed the dead `import tomli` fallback for "Python < 3.11" — the package
requires 3.11+, so `tomllib` is always present.

**No config module was built**, which the plan above called for. Two small
readers of two different sections of one file is not duplication worth an
abstraction, and the defect here was a key mismatch, not a missing loader.

### R13. `write_fix` has no default test-command allowlist
`src/reforge_mcp/tools/fix.py:59`

`validate_test_command(test_command, allowed_test_commands or [])` — if the
caller passes no allowlist, the loop over `allowed_commands` matches nothing and
every command is rejected. The README advertises a built-in allowlist
(`pytest`, `npm test`, `go test ./...`), so documented and actual behaviour
differ, and the useful path requires the *caller* to supply the allowlist, which
is not a security boundary at all.

**Fixed 2026-10-24.** `DEFAULT_ALLOWED_TEST_COMMANDS` lives in `security.py`
next to the validator, and is used whenever the caller passes no allowlist *or
an empty one* — an empty list meaning "reject everything" is not an API anyone
wants, and it was the behaviour `write_fix` triggered on every call. The
chaining-operator rejection is unchanged.

Worth stating plainly: an allowlist that is empty unless the caller fills it is
not a security boundary, it is a disabled feature. The documented runners
(`pytest`, `npm test`, `go test`, `tox`, `cargo test` and friends) now work out
of the box, and `rm -rf /` is still refused.

### R14. `shell=True` for the test command
`src/reforge_mcp/tools/fix.py:103`

Mitigated by the operator blocklist, but prefix matching plus a shell is a
weaker boundary than it needs to be: `pytest --foo=$(...)` is blocked only
because `$(` is in the blocklist, which is an enumerate-the-bad approach.

**Fixed 2026-10-24.** The command is now `shlex.split`, its executable
resolved with `shutil.which`, and run as an argv list with no shell — so nothing
in the string can be interpreted as shell syntax and the operator blocklist
becomes defence in depth rather than the only defence.

`shutil.which` was the detail that made this safe to do rather than a Windows
regression: `subprocess.run(["npm", "test"])` fails there because npm ships as
`npm.cmd`, and `which` resolves exactly those shims. A missing executable now
returns `Test command not found: <name>` and rolls the fix back, instead of
whatever the shell would have said.

Prefix matching against the allowlist is kept rather than switching to an
`argv[0]` check, because entries like `python3 -m pytest` are multi-token.

### R15. God-file export counts are inflated and the thresholds are unexplained
`src/reforge_mcp/tools/scan.py` — `_find_god_files`

`server.py` is flagged with "21 exports" for 11 definitions (R8), and
`tests/test_security.py` is flagged as a god file — test files should not be
judged by production thresholds. 500 lines / 10 exports are presented as facts
with no justification or override.

**Fixed 2026-10-24.** R8 fixed the double-count (`server.py` 21 -> 11), but a
second counting defect survived it: `export_count` was
`len(functions) + len(classes)`, which counts **every method** as an export. A
file holding one class with thirty methods read as thirty-one exports, so any
class-heavy module was guaranteed to trip the threshold — that is why
`parser.py` showed 36 and `test_security.py` 24. Exports are now top-level
definitions only (functions whose names are not in any class's method list,
plus the classes themselves).

Test files are skipped: thirty small test functions in one file is good
practice, not a god object. `_is_test_file` covers `tests/` directories,
`test_*.py`, `*_test.py`, `*_test.go` and `.test/.spec.{js,ts}`.

**Self-scan: 6 god files -> 3**, all genuine (`parser.py` at 1161 lines,
`scan.py` at 579, `server.py` at 11 exports). Health score 75.0 -> 82.8.

**Thresholds stayed as function arguments rather than moving to config**, which
is a change from the plan above. The complaint was that 500 and 10 are presented
as facts with no justification — the fix for that is to say so, which the
docstring now does, not to add a config knob nobody has asked for. They are
already overridable by a caller, and the report carries the raw `lines` and
`exports` so a reader can disagree with the verdict. `server.py` being flagged
for 11 exports against a threshold of 10 is exactly that case, and it is left
in the report rather than special-cased.

### R16. Windows-only test failure
`tests/test_security.py` — `test_symlink_to_outside_blocked`

`os.symlink` raises `WinError 1314` without Developer Mode or elevation. CI is
Linux so it passes there, but the suite is red for Windows contributors.

**Fixed 2026-10-24.** `@pytest.mark.skipif` on `_symlinks_available()`, which
probes by actually creating a symlink in a temp directory rather than guessing
from `os.name` — Developer Mode and elevation both change the answer on the same
platform.

**The suite is now fully green for the first time: 103 passed, 1 skipped, 0
failed.** The security property itself is still covered on any platform that
permits the fixture, which includes CI.

### R17. CI tests one platform and one Python version
`.github/workflows/ci.yml`

A tool that edits files, resolves paths and shells out is exactly the kind of
code that breaks on Windows path separators and CRLF. The self-scan output above
shows `src\reforge_mcp\...` separators leaking into report payloads.

**Fixed 2026-10-24, smaller than planned.** The matrix is 4 jobs:
ubuntu + windows x 3.11 + 3.14. Windows earns its column because this tool
resolves paths, rewrites files and shells out. macOS would behave like ubuntu
here, so it buys runtime rather than cover, and for a pure-Python package with
no version-gated code the floor and the newest release bracket everything
between them. Classifiers now claim 3.11 through 3.14.

The old workflow also ran `python -m venv venv` and `. venv/bin/activate`,
which is bash-only — it could never have run on a Windows runner even if one
had been configured. The venv bought nothing on an isolated runner, so both
steps are gone.

**Path normalisation deliberately dropped** (was the second half of this item).
It is cosmetic: `src
It is cosmetic: a backslash-separated path is the native form on Windows and
`get_chunk` accepts it. Against that, `_resolve_import_to_file` builds its
candidate paths with `os.sep` to match `ParseResult.file`, so normalising one
without the other would silently return the dependency graph to zero edges on
Windows. Not worth that risk for consistent-looking output. If it is wanted
later it has to be one change in `parse_file` plus the resolver, proven by the
Windows CI column this item just added.

### R23. `write_fix` can hang forever on a test command, timeout notwithstanding
`src/reforge_mcp/tools/fix.py`

**Found by CI, not by the review.** The first run of the new Windows matrix
(R17) sat in "Run tests" for **32 minutes** while both ubuntu jobs passed in 35
seconds. Locally the same suite is under 7 seconds on Windows 11. The jobs were
cancelled rather than left to burn an hour of runner time.

The trigger was three end-to-end tests shelling out to the real `pytest` binary
as their gating command. The underlying defect is in the product, and the
`timeout=120` gives false comfort against both halves of it:

- **Pipes outlive the timeout.** `capture_output=True` means `subprocess.run`
  waits for EOF on the pipes. The timeout kills the direct child, not a
  grandchild that inherited the pipe, and the `communicate()` that `run()`
  performs after `TimeoutExpired` has **no timeout of its own** - so it blocks
  for as long as anything holds the write end.
- **stdin was inherited.** Any command that prompts - a git credential prompt,
  an `npm` confirmation, a stray `pdb` - waits on input that will never arrive.

Both are fixed: output is captured to a `tempfile.TemporaryFile` instead of a
pipe, so there is no pipe to hold open, and `stdin=subprocess.DEVNULL` closes
the input. This is worth having independently of CI: a user whose `test_command`
leaves a background process running would have hung `write_fix` with no way out
on any platform.

The tests now gate on `python check.py`, a script in the fixture repo that
imports the project's own module and asserts on it. That keeps the end-to-end
meaning - a command exercising real project code decides whether the fix stays -
while removing the nested test runner. Suite time went from 6.7s to 4.6s.

A side note that is its own small reassurance: the first attempt used
`python -c "import calc; assert calc.add(2, 2) == 4"` and was refused, because
`validate_test_command` saw the semicolon and called it command chaining. The
injection guard works.

One nested-runner call is kept on purpose -
`test_default_allowlist_permits_a_documented_runner` runs `pytest --version` -
because nothing else proves the default allowlist resolves a real runner. If
Windows CI hangs again, that single test is the suspect.

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

**Fixed 2026-10-24.** `tests/test_end_to_end.py` drives the chain Claude
actually drives, on a temp git repo holding a real defect: `scan_repo` reports
`unused_helper` as dead, `get_chunk` reads those lines, `write_fix` removes them
gated on the project's own `pytest` run, `git_commit` commits `calc.py` and
nothing else, and a rescan returns no dead code against a clean working tree.

Four failure paths beside it:

- a diff that breaks `add()` makes the project's tests fail, and the file comes
  back byte-identical with `rolled_back: true`
- a hunk pointing past the end of the file changes nothing
- a **stale** diff — right line numbers, content that no longer matches — changes
  nothing. This is the case a slightly out-of-date plan produces, and the one
  that used to corrupt files
- no `.bak` or `.tmp` is left behind after a successful fix

It also caught a documentation-level mistake of my own: I had assumed
`get_chunk` returns `content`, and it returns `source`. Worth knowing for the
README rewrite in R18.

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
