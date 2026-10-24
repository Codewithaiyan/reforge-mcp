# Changelog

## 0.2.2 — 2026-10-24

Re-scan any repository containing JavaScript or TypeScript: 0.2.1 and earlier
reported an empty dependency graph for most front-end code.

### Fixed

- **An import that names its own extension now resolves.** Candidate paths were
  built as `base + extension` only, so `import { encode } from './protocol.js'`
  looked for `protocol.js.py` and `protocol.js.js` and matched nothing. A
  browser ES module cannot omit the extension, so this lost every edge in a
  plain front-end project. Python imports are always extensionless, which is why
  the project's own self-scan never saw it.

- **`require()` is read as an import.** The JavaScript query matched
  `import_statement` only, so a CommonJS module's dependencies were invisible.

- **A bare JS specifier is no longer resolved to a sibling file.**
  `require("express")` resolved to a local `express.js` if one happened to exist,
  inventing an edge to a file the code never imports. Bare specifiers in JS and
  TS are now treated as external, which is what they are. Python's dotted
  resolution is unchanged.

### Not covered

Dynamic `import()`, `<script src=...>` tags, `package.json` `"main"`, and
tsconfig path mappings. A repo relying on one of those still under-reports.

## 0.2.1 — 2026-10-24

Both items come from the first report by someone outside this project, who ran
0.2.0 against a mixed Kotlin/C++/Python/JavaScript repository.

### Fixed

- **Methods overriding a base class defined outside your repo are no longer
  reported as dead code.** `log_message`, `do_GET` and `do_POST` on a
  `BaseHTTPRequestHandler` subclass were all flagged: the standard library calls
  them by name when a request arrives, so nothing in the repository references
  them. The scan cannot see outside the repository, so it no longer claims a
  method of an externally-derived class is unused. The same bug applied to
  `render` on a `React.Component` subclass, `get` on a Django `View`, and
  `unittest.TestCase` helpers.

  Still reported: an unused override of a base class that *is* defined in your
  repo, because then every call into it is visible. A class with no bases is
  unaffected.

### Added

- **`scan_repo` now reports the source files it could not read**, as
  `unscanned_source_files` and `unscanned_by_extension` in the summary. A scan
  of that repository said `total_files: 7` while silently skipping roughly
  twenty Kotlin and C++ files, which reads as a verdict on the whole project
  when it is a report on the web tooling. Adapters still cover Python,
  JavaScript, TypeScript and Go only — the difference is that the output now
  says so.

## 0.2.0 — 2026-10-24

**If you used 0.1.0, re-scan your repositories.** Three of the four analyses
returned meaningless output, so anything 0.1.0 told you about your code can be
discarded rather than trusted.

### Fixed — results you can believe

- **Dead code detection never worked.** The regex that found call sites matched
  `foo` in `def foo(`, so every function counted as a call to itself and nothing
  was ever reported. References are now collected from the AST, skipping each
  definition's own name and the contents of comments and strings. Verified
  against this repository: 0 findings before, 4 genuine ones after.
- **The dependency graph had no edges.** Relative imports were never captured by
  the parser, bare `import sibling` was ignored by the graph builder, and the
  file set was populated inside the loop that read it. All three fixed — 0 edges
  before, 24 correct ones after. Cycle detection worked all along and had simply
  never been given an edge; it is now covered by tests.
- **Duplicate detection was mostly phantom.** Decorated functions were parsed
  twice, so a function was reported as a duplicate of itself. 12 groups before,
  0 after, with real copy-paste still found.
- **God files counted every method as an export**, so any class-heavy module
  tripped the threshold, and test suites were judged by production limits. Now
  top-level definitions only, and test files are skipped.
- **Decorators were never extracted**, which left the guard against reporting
  framework callbacks inert. `@app.route`, `@pytest.fixture`, `@mcp.tool()` and
  anything else that is not a pure modifier now mark a function as reachable.

### Fixed — safety

- **`write_fix` could silently corrupt a file.** The applier trusted the hunk
  header's line numbers, and a diff claiming lines 40–42 of a three-line file
  returned `success: true` after rewriting the file. Every hunk's context is now
  checked against the file first, and any mismatch rejects the whole diff.
- **`write_fix` stashed your working tree** before patching and popped it
  afterwards, which on a dirty tree patched content you never saw and could bury
  uncommitted work. The stash is gone; the `.bak` copy now captures what was
  actually on disk.
- **`git_commit` staged everything** when `files` was omitted, sweeping unrelated
  work into a "refactor" commit. `files` is now required and must be non-empty.
- **A test command could hang the server forever**, timeout notwithstanding:
  output went to a pipe that a grandchild process could hold open past the
  timeout, and `stdin` was inherited so anything that prompted waited forever.
  Output now goes to a file and `stdin` is closed.
- **`dry_run = true` in `reforge.toml` did nothing.** It was commented as a
  safety default that prevented all modification, and `write_fix` wrote
  regardless. The key is removed rather than left to mislead.
- **The test-command allowlist was empty** unless the caller supplied one, which
  rejected every command including the documented ones. It now has a default.
- The test command runs with no shell.

### Changed

- **The ten tools are now named as documented** — `scan_repo`, `get_chunk` and so
  on. They were previously exposed as `scan_repo_tool`, `get_chunk_tool`, etc.,
  because FastMCP derives a tool's name from its function name. **Update any
  saved prompt that referred to the `_tool` names.**
- **The commit budget is per session, not per lifetime.** It was persisted to
  `.reforge-session.json` and only ever incremented, so after 20 commits ever the
  tool refused to work with no way to reset it. It is now held per repository for
  the life of the server process.
- `reforge.toml` is three keys, all of which are read. `test_before_fix`,
  `atomic_commits`, `dry_run`, `max_file_size_kb`, `skip_extensions` and
  `auto_detect` were documented but wired to nothing, and are gone. `[scan]
  ignore` is now actually read — the code looked for a top-level `ignore_dirs`
  that neither the shipped file nor the README used.

### Removed

- **`sentence-transformers` and `rich` are no longer dependencies.** Neither was
  imported anywhere, and the former pulled PyTorch — roughly 2 GB for a function
  that logged "not implemented". Installing 0.2.0 resolves 78 packages with no
  torch and no nvidia packages.
- `find_similar_functions`, `extract_call_sites`, `hash_body` / `normalize_code`
  (a dead second copy of the parser's hashing), `embeddings_cache` and
  `ttl_seconds` — all unreachable or inert.

### Documentation

The README advertised 7 tools where 10 were registered, told you to export an
`ANTHROPIC_API_KEY` the server has never used two sections above a table stating
it makes no network calls, documented the Claude desktop config path for a Claude
Code tool, and claimed a 10 MB file-size limit where the code uses 500 KB. Its
example also showed `write_fix` creating a new file, which it cannot do. All
corrected, and the sample scan output is now a real run.

### Testing

50 tests to 115, with the one Windows-only failure now skipped on platforms that
forbid creating symlinks. CI runs on ubuntu and windows against Python 3.11 and
3.14; it previously ran one ubuntu job whose venv activation step could never
have worked on Windows.

## 0.1.0 — 2026-05-04

First release.
