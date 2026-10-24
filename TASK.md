# TASK.md — reforge-mcp work tracker

Single source of truth for what is left. Rationale, evidence and proposed fixes
live in [IMPROVEMENTS.md](IMPROVEMENTS.md) under the matching `R<n>` id — do not
restate them here.

**Conventions**

- `[ ]` open · `[~]` in progress · `[x]` done · `[-]` dropped (say why inline)
- Tick a box only when the fix has a test proving it, or it is a pure deletion.
- New findings: add to IMPROVEMENTS.md with the next `R<n>`, then add the line here.
- Log finished milestones at the bottom.

**Status:** M0 in progress (R1 done). Baseline 2026-10-24 at `7039af9` — 50 tests
pass, 1 Windows-only failure (R16). Now 60 pass, same 1 failure.

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
- [ ] **R7** Populate `FunctionInfo.decorators` from `decorated_definition`
- [ ] **R7b** Test: an `@app.route` function never called directly is not reported dead
- [ ] **R4** Rebuild reference collection on the tree-sitter AST (calls, attributes, bare identifiers); delete the regex path
- [ ] **R4b** Implement the documented `__all__` exemption
- [ ] **R4c** Test: instance methods called as `obj.method()` are not reported dead
- [ ] **R6** Two-pass `_build_dependency_graph`; resolve relative imports and `__init__.py` packages
- [ ] **R6b** Test: a known two-file import cycle is detected
- [ ] **R9** Dedupe duplicate groups; filter trivial bodies and same-base-class overrides
- [ ] **R15** Fix god-file export counts, exclude test paths, move thresholds to config

**Exit:** self-scan finds `extract_call_sites` as dead code, reports 0 phantom
duplicate groups, and draws a non-empty dependency graph.

## M2 — Delete what is not real

Pure subtraction. Safe to do any time, including before M1.

- [ ] **R5** Delete `extract_call_sites`, the unused `call_pattern`, and the duplicate `general_call_pattern` definition
- [ ] **R10** Drop `sentence-transformers` and `rich` from `dependencies`; move the former to an optional `semantic` extra if ever needed
- [ ] **R21** Delete `embeddings_cache` from the state schema and `ttl_seconds` from `write_memory_tool`
- [ ] **R12b** One config loader with one documented schema; delete every key nothing reads

**Exit:** `pip install reforge-mcp` no longer pulls PyTorch; no module ships a
function nothing calls.

## M3 — Harden

- [ ] **R13** `DEFAULT_ALLOWED_TEST_COMMANDS` used when the caller passes no allowlist
- [ ] **R14** `shlex.split` the test command; drop `shell=True`; validate `argv[0]`
- [ ] **R11** Real session identity in `.reforge-session.json` (`session_id`, `started_at`); add a reset path
- [ ] **R19** End-to-end test: scan -> apply -> test -> commit, plus the three rollback paths
- [ ] **R16** Skip the symlink test when the platform denies symlink creation
- [ ] **R17** CI matrix: ubuntu/macos/windows x 3.11/3.12/3.13; normalise report paths to forward slashes

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
