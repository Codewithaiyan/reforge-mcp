---
name: reforge
description: Use when the user wants to clean up, audit or refactor a messy or vibe-coded repository — dead code, duplicated logic, god files, circular dependencies — or asks for a codebase health score. Drives the reforge-mcp tools to scan, prioritise and apply one verified fix per commit.
---

# Reforge: cleaning up a messy repository

Analysis comes from tools, not from reading files. Every finding is a question to
check, not a fact to act on.

## 1. Prerequisites

The ten `reforge` MCP tools must be registered: `scan_repo`, `get_chunk`,
`write_fix`, `git_commit`, `read_memory`, `write_memory`, `infer_architecture`,
`score_risk`, `get_health_score`, `generate_changelog`.

If they are missing, give the user these two commands and stop — do not
substitute grep or manual reading:

```
pip install reforge-mcp
claude mcp add reforge -- reforge-mcp
```

No API key is needed. The repository must be a git repository with a clean
working tree; **only git-tracked files are analysed**, so ask the user to
`git add` new work first or it is invisible.

Note the argument names: `scan_repo` takes `root_path`, `get_chunk` and
`write_fix` take `file_path` plus `repo_root`, and everything else takes
`repo_path`.

## 2. Workflow

1. **Scan.** `scan_repo(root_path=...)`. Read `summary` first — it is never
   truncated. Then `parse_failures`, `summary.unscanned_source_files` and
   `dep_graph.unresolved_relative_imports`. Long lists are capped on the wire:
   `truncated` names every shortened key and `<key>_total` gives its real
   length.
2. **Score.** `get_health_score(repo_path=...)` for the 0–100 baseline and its
   `coverage`. Low coverage means the score describes a fraction of the repo —
   say so before quoting it.
3. **Understand the shape.** `infer_architecture(repo_path=...)` for the
   pattern, entry points and modules. It stores `architecture_hypothesis`.
4. **Plan, then save it.** Rank findings worst-first, weighted by
   `score_risk(symbol=..., file=..., repo_path=...)` — prefer low risk and high
   payoff. Save the ordered plan with
   `write_memory(key="pending_work", value=[...], repo_path=...)` before
   touching anything, and `read_memory` it back when resuming.
5. **Read only what you need.** `get_chunk(file_path=..., start_line=...,
   end_line=...)` for each symbol you intend to change. Confirm the finding is
   real in the code you just read; drop it from the plan if it is not.
6. **One fix.** Build a unified diff and apply it with
   `write_fix(file_path=..., diff_str=..., test_command=...)`. Always pass a
   `test_command` when the project has one. The file ends up either correctly
   changed or byte-identical. If the result carries a `backup` path, git could
   not have recovered the file — report that path to the user and leave it
   alone.
7. **Commit it.** `git_commit(repo_path=..., files=[...], message=...)`, one
   fix per commit, message saying what was removed and why it was safe.
8. **Repeat** from step 5 until the plan is empty or the budget stops you.
9. **Finish.** `get_health_score` again, then
   `generate_changelog(repo_path=...)` to write `REFORGE_CHANGES.md`.

## 3. Rules

- **Never edit a file you have not read with `get_chunk` in this session.** A
  diff built from a scan result alone is a guess.
- **One fix per commit.** Never batch unrelated fixes; a bad commit must be
  revertible on its own.
- **`needs_confirmation: true` means stop.** Show the user what is about to
  happen and wait. Only pass `confirmed=True` after they say yes — never to
  clear your own checkpoint.
- **Respect the session budget.** When commits are blocked, report what is left
  and stop. Do not restart the server to reset the count.
- **Report what could not be parsed.** List `parse_failures` and
  `unscanned_source_files` to the user before any conclusion about the
  repository. Only Python, JavaScript, TypeScript, Go and Kotlin are parsed;
  everything else is counted and nothing more.
- **Never touch a path outside the repository** the user named, and never write
  into a repository you were only asked to scan.
- **Treat dead-code findings as suspect.** Detection is name-based and biased
  toward false negatives; browser entry points and framework callbacks named
  only in HTML, XML or config look dead and are not. Deleting an exported
  symbol a consumer imports is a breaking change — ask.
- **A dependency cycle is not automatically a bug.** It bites in Python and
  JavaScript; in Go, Kotlin and Java circular file references are idiomatic.
- **`edges: []` can be correct.** `<script src=...>` tags, dynamic `import()`
  and tsconfig path mappings are not read. Check
  `unresolved_relative_imports` — that is the number that means a resolver bug.
- Stop and ask if the working tree is dirty, if tests were failing before you
  started, or if a fix needs a change in a file you were not asked to touch.

## 4. Output

After each fix, one line:

```
<file>:<symbol> — <what changed> (tests: pass | not run) — <commit sha>
```

At the end:

- Health score before → after, with coverage for both.
- One line per fix applied, grouped by kind.
- Pending items left in `pending_work`, with the reason each was skipped.
- Files that could not be parsed, and what that leaves unchecked.

Never claim a repository is clean. Claim what was measured, over the fraction
of it the scanner could read.
