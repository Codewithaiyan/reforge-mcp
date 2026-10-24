# TASK.md — reforge-mcp work tracker

Single source of truth for what is left. Rationale, evidence and proposed fixes
live in [IMPROVEMENTS.md](IMPROVEMENTS.md) under the matching `R<n>` id — do not
restate them here.

**Conventions**

- `[ ]` open · `[~]` in progress · `[x]` done · `[-]` dropped (say why inline)
- Tick a box only when the fix has a test proving it, or it is a pure deletion.
- New findings: add to IMPROVEMENTS.md with the next `R<n>`, then add the line here.
- Log finished milestones at the bottom.

**Status:** M0 and M1 complete. M2 complete bar R12b. M3 in progress.
Baseline 2026-10-24 at `7039af9` — 50 tests pass, 1 Windows-only failure.
Now **103 pass, 1 skipped, 0 failed**.

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
- [ ] **R21** Delete `embeddings_cache` from the state schema and `ttl_seconds` from `write_memory_tool`
- [ ] **R12b** One config loader with one documented schema; delete every key nothing reads

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

## M4 — Ship honestly

- [ ] **R18** Rewrite the README against the shipped software (10 tools, no API key, `claude mcp add`, correct `reforge.toml`)
- [ ] **R18b** Regenerate the sample `scan_repo` output from a real run
- [ ] **R22** Add a status line to the README while P1 work is open
- [ ] **R20** Move the four adapters into the existing `adapters/*.py` stubs
- [ ] Tag `0.2.0` and publish

**Exit:** every claim in the README is reproducible by a user in five minutes.

---

## Done

_Nothing yet — baseline recorded 2026-10-24._
