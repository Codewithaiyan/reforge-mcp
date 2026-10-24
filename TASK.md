# TASK.md — reforge-mcp work tracker

Single source of truth for what is left. Rationale, evidence and proposed fixes
live in [IMPROVEMENTS.md](IMPROVEMENTS.md) under the matching `R<n>` id — do not
restate them here.

**Conventions**

- `[ ]` open · `[~]` in progress · `[x]` done · `[-]` dropped (say why inline)
- Tick a box only when the fix has a test proving it, or it is a pure deletion.
- New findings: add to IMPROVEMENTS.md with the next `R<n>`, then add the line here.
- Log finished milestones at the bottom.

**Status:** M0, M1, M2 and M3 complete. M4 (the README rewrite) is all that remains.
Baseline 2026-10-24 at `7039af9` — 50 tests pass, 1 Windows-only failure.
Now **115 pass, 1 skipped, 0 failed** in 4.0s, green on ubuntu and windows x 3.11 and 3.14.

Self-scan at this point: 4 dead-code findings (all genuine), 0 duplicate groups,
24 dependency edges, 3 god files, health score 82.8.

---

## M0 — Do not corrupt repositories

Blocks the PyPI release. Nothing else ships first.

- [x] **R1** `apply_diff` verifies every hunk's context and removed lines before mutating; rejects the whole diff on any mismatch
- [x] **R1b** Regression tests in `tests/test_diff.py` — wrong line numbers, bad context, header/body disagreement and a bad second hunk all leave the file byte-identical
- [x] **R2** Deleted `_git_stash` / `_git_stash_pop` and their four call sites; the `.bak` copy is the only rollback mechanism. No dirty-file guard needed — the hazard was the stash itself
- [x] **R3** `files` is now a required, non-empty argument; the `add(A=True)` branch is deleted. No caller or test ever omitted it, so this was dead code, not a used feature
- [x] **R12a** `dry_run` deleted from `reforge.toml`. Honouring it as shipped (`true`) would have disabled `write_fix` for every user with a config file; honouring it as `false` would contradict the file. Claude already previews by showing the diff before calling the tool

**Exit:** a deliberately bad diff cannot change a byte on disk, and a commit can
only ever contain the files that were named.

## M1 — Make the analyses real

Order matters: R8 and R7 are parser fixes the rest depend on.

- [x] **R8** Root cause was `id(child)` vs `child.id` — the dedupe set already existed but keyed off Python object ids, and py-tree-sitter mints a new wrapper per access, so it never matched. Two words changed; `server.py` 21 -> 11 functions, duplicate groups 12 -> 1
- [x] **R8b** Tests in `tests/test_parser.py` — decorated defs counted once, and two same-named defs in one file both survive the dedupe
- [x] **R7** Decorators now read off the enclosing `decorated_definition`, by node text with the argument list cut off, so `@mcp.tool()` and `@app.route("/x")` both resolve. The old branch looked for `decorator` children of `function_definition`, where the grammar never puts them
- [x] **R7b** Tests in `tests/test_parser.py` — extraction including stacked and argument-carrying decorators, plus `is_decorated_entry_point` returning True for `@app.route` / `@property` and False for an undecorated function
- [x] **R4** `ParseResult.references` is collected from the AST by a single generic walker shared by all three adapters, skipping each definition's own name plus comments and strings. `find_dead_code` is now set arithmetic and the regex path is gone. Self-scan: 6 findings, all genuine, 0 false positives
- [x] **R4b** `__all__ = [...]` string contents count as references
- [x] **R4c** Tests in `tests/test_dead_code.py` (12 cases) — `obj.method()`, docstring and comment mentions, reference-without-call, `__all__`, decorators, dunders, `test_*`
- [x] **R4d** Decorator policy inverted to a denylist of five reachability-neutral decorators, settling the question R7 raised. `@mcp.tool()`, `@celery.task` and any other unknown framework decorator now imply a caller
- [x] **R6** Two causes, not one: the loop-ordering bug *and* relative imports never being captured by the Python adapter at all. Both fixed; self-scan goes from 0 to 24 correct edges
- [x] **R6b** Tests in `tests/test_dep_graph.py` (7 cases) — sibling, relative and package imports resolve; external imports do not; a two-file cycle is reported; repeated imports collapse to one edge
- [x] **R9** Phantom groups were already gone with R8; the one real-but-unactionable group (three adapters' `get_language`) is now suppressed by a deliberately narrow test — every member must be a one-line *method*. Also deleted `hash_body` + `normalize_code`, a dead second copy of `parser._hash_body`, and replaced the O(groups x functions) `line_count` lookup with an index. Self-scan: 0 groups
- [x] **R15** Methods no longer count as exports (a file with one class and thirty methods exports one name), and test files are skipped. Self-scan: 6 god files -> 3, all genuine. Thresholds stay as function arguments, not config — see IMPROVEMENTS.md for why

**Exit:** self-scan finds `extract_call_sites` as dead code, reports 0 phantom
duplicate groups, and draws a non-empty dependency graph.

## M2 — Delete what is not real

Pure subtraction. Safe to do any time, including before M1.

- [x] **R5** Deleted with R4 — `extract_call_sites`, `call_pattern`, both copies of `general_call_pattern` and the 30-line `FRAMEWORK_DECORATORS` allowlist all went with the rewrite
- [x] **R10** Deleted `find_similar_functions` (the stub) and dropped `sentence-transformers` and `rich` from `dependencies` — neither was imported anywhere. `uv.lock` shed 939 lines; torch and every nvidia package are gone. No optional extra added: nothing needs one until the feature exists
- [x] **R21** Both deleted — an always-empty cache for the feature R10 removed, and an argument documented as unenforced
- [x] **R12b** `[scan] ignore` is read correctly, and the five keys nothing read are deleted. No config module was built: two small readers of two different sections is not duplication worth an abstraction, and the defect was a key mismatch, not the lack of a loader

**Exit:** `pip install reforge-mcp` no longer pulls PyTorch; no module ships a
function nothing calls.

## M3 — Harden

- [x] **R13** `DEFAULT_ALLOWED_TEST_COMMANDS` in `security.py`, used whenever the caller passes no allowlist or an empty one
- [x] **R14** `shlex.split` + `shutil.which` + no shell. `which` also resolves the `.cmd` shims npm and yarn install on Windows, which a bare argv would have missed
- [x] **R11** Solved by deletion instead: the counter is a per-repo dict in the server process, so it resets on restart. No `session_id`, no `started_at`, no reset tool — the server process is the session, and the error message's "start a new session" is now literally true
- [x] **R19** `tests/test_end_to_end.py` — scan finds a real dead function, `get_chunk` reads it, `write_fix` removes it gated on the project's own pytest run, `git_commit` commits only that file, and a rescan shows the defect gone with a clean tree. Plus failing-tests rollback, out-of-range diff, stale-context diff, and no `.bak`/`.tmp` left behind
- [x] **R16** Skipped behind a probe that actually tries to create a symlink. Suite is now fully green: 103 passed, 1 skipped, 0 failed
- [x] **R17** CI matrix is 4 jobs — ubuntu + windows x 3.11 + 3.14 (floor and newest). Dropped macOS and the middle versions from the plan: macOS behaves like ubuntu for this code, so it buys runtime not cover. Also replaced the bash-only `. venv/bin/activate` steps, which could never have run on Windows
- [-] **R17b** Report path normalisation dropped. It is cosmetic, and `_resolve_import_to_file` builds candidates with `os.sep` to match `ParseResult.file`, so changing one without the other would silently break R6 on Windows. If wanted later: normalise once in `parse_file` and in the resolver together, with a Windows test

**Exit:** green suite on all three platforms; no security claim in the README
that a test does not cover.

## M5 — Found by users

- [x] **R26** Methods overriding a base class defined outside the repo were reported dead — `do_GET` on a `BaseHTTPRequestHandler` subclass and the same pattern in React, Django and unittest. `ClassInfo` now carries base names and externally-derived classes have their methods treated as referenced. A repo-local base still yields reportable overrides
- [ ] **R27** `scan_repo` reports `total_files` with no indication that files were skipped for having no adapter, so a 7-file result on a 30-file Kotlin/C++ repo reads as a verdict on the whole thing

## M3b — Found by CI

- [x] **R24** Bare `import sibling` produced no edge at all, so flat repos had no dependency graph and the commonest Python cycle went undetected. Found by generating real README output instead of writing it by hand
- [x] **R25** Exposed tool names were `scan_repo_tool` etc. while every doc said `scan_repo`. Fixed with `@mcp.tool(name=...)` rather than by documenting the suffix
- [x] **R23** `write_fix` could hang forever on a test command despite its timeout: pipes outlive the timeout (the post-`TimeoutExpired` `communicate()` has none of its own) and stdin was inherited. Output now goes to a temp file and stdin is `DEVNULL`. The end-to-end tests gate on `python check.py` instead of nesting the real pytest, which is what exposed it

## M4 — Ship honestly

- [x] **R18** README rewritten against the shipped software: 10 tools (table checked against `server.py` programmatically), `claude mcp add`, no API key, correct file-size limit, `.[dev]` install, real test and source layout. Also corrected the example session, which showed `write_fix` creating a new file — it can only patch an existing one
- [x] **R18b** Sample output is a real run against a four-file demo repo, and generating it is what uncovered R24
- [x] **R22** Replaced with a Status section. The original premise — "while P1 work is open" — no longer holds, so it now says what is verified and that the JS/TS/Go adapters are far less exercised than Python
- [-] **R20** Dropped. The stated reason was that our own tool flags the file, which is vanity rather than a defect; moving ~900 lines of working parser risks what R4-R8 just fixed, for no user benefit. Reopen only if it blocks real work
- [ ] Tag `0.2.0` and publish

**Exit:** every claim in the README is reproducible by a user in five minutes.

---

## Done

_Nothing yet — baseline recorded 2026-10-24._
- [x] R28 — resolve a JS import that names its own extension (0.2.2)
- [x] R29 — treat a bare JS specifier as external (0.2.2)
- [x] R30 — analyse only git-tracked files (0.2.3)
- [x] R31 — a bare import inside a package is external (0.2.3)
- [x] R32 — report external and unresolved-relative import counts (0.2.4)
