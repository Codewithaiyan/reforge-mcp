# Changelog

## 0.3.0 - 2026-10-30

The first validation sweep: seven real open-source repositories, scanned with
0.2.9. **Two of the five advertised languages had never worked at all.**

### Breaking

`get_health_score` returns `score: None` when no files could be analysed. A
number there was a lie — see below.

### Fixed - TypeScript had never parsed a single file

The class query asked for `(class_declaration name: (identifier))`. TypeScript
names a class with a `type_identifier`, which makes that an *impossible
pattern*, and tree-sitter rejects the whole query. Every `.ts` and `.tsx` file
handed to this tool since 0.1.0 came back as a parse error.

It was worse than one language: a rejected query leaves tree-sitter unable to
run later ones, so after a single `.ts` file, JavaScript parsing failed too.
Scanning axios reported **277 of 277 files failed**, one function, and a health
score of **100.0**. Express, which has no TypeScript, was fine throughout.

axios now reports 277 files, 896 functions and 374 dependency edges.

### Fixed - Go had never parsed a single file either

The same mistake in another grammar: `(type_spec name: (identifier))`, where Go
also uses `type_identifier`. Scanning spf13/cobra reported 36 of 36 files
failed, 0 functions, health **100.0**.

Three further Go defects were hiding behind that one:

- **Imports were never extracted.** The handler walked an import declaration's
  direct children, but a grouped import nests its strings two levels deeper.
  0 to 190 imports on cobra.
- **Structs and interfaces were never recorded as classes**, for the same
  nesting reason.
- **Every test function was reported as dead code** — 311 of cobra's 595
  functions. Go's runner collects `Test`, `Benchmark`, `Example` and `Fuzz` by
  capitalised prefix; the exemption only knew lowercase `test_`. 311 to 26.

cobra now reports 36 files, 595 functions and health 73.6.

### Fixed - a repository nothing could be read from scored 100 out of 100

`total_files` counted files whose parse had failed, and the failure was never
surfaced. Every health penalty is a ratio over findings, and a file that fails
to parse produces no findings — so total failure scored as perfection.

- `summary.parse_failures` reports how many files could not be read.
- `summary.total_files` counts only files that actually parsed.
- `coverage` counts a parse failure against the tool.
- The caveat names parse failures and says they are a defect in this tool.
- `score` is `None` when nothing was analysed, rather than 100.

### Already working

Flask, requests, express and okhttp produced **no defects** — every file parsed,
imports resolved into real dependency graphs, findings were plausible. okhttp
alone is 619 Kotlin files and 7,261 functions.

### Known gaps the sweep surfaced

- **Kotlin dependency edges are all missed.** okhttp shows 0 edges, 6,869
  external imports and 0 unresolved relative imports — which reads as "no
  internal imports" and is false. Kotlin imports are absolute package paths and
  nothing maps a package to a file.
- Duplicate detection is noisy at scale: 176 groups on okhttp.
- A library's exported API reads as dead code, since nothing in its own
  repository calls it. 26 of cobra's 26 findings are its public surface.

## 0.2.9 - 2026-10-24

### Added - Kotlin

The repository this tool has been tested against all day is an Android app with
a C++ PC companion, and the scan could read 6 of its 175 source files. 39 of
them are Kotlin. All 39 now parse, with zero errors, including an 854-line one.

That scan went from 6 files to 48, and from 79 functions to 507.

Reading Kotlin surfaced three false-positive classes, all now closed:

- **96 dead-code findings, mostly JUnit tests.** Kotlin tests have no `test_`
  prefix for the name-based exemption to catch; they are annotated `@Test`.
  Annotations are now collected as decorators, so the existing exemption covers
  `@Test`, `@Composable` and the rest with no new rule. 96 to 26.
- **The rest were framework callbacks on anonymous objects.** Kotlin puts them
  on `object : MediaCodec.Callback()`, which is not a named class, so the
  external-base exemption had nothing to work from. The `override` keyword is
  collected as a marker instead: an override is dispatched through its
  supertype, so something reaches it even when no call names it. 26 to 3, and
  all three are genuine.
- **Eight empty callbacks reported as one duplicate group.** The shared
  interface filter required every member to be a method of a named class. It
  now also accepts a one-line `override`.

### Fixed - a call inside an f-string did not count as a reference

This project's own scan then reported `_fix_label` dead while it was being
called on the next line, inside an f-string. `_collect_references` skips
`string` nodes so that a docstring mentioning `foo()` is not a use of `foo` -
and an f-string is a `string` node, so every call inside `{...}` went with it.
The same applied to `${...}` in a JS template literal.

Any codebase that calls a function inside an f-string had false dead-code
findings from this. Interpolations are now descended into; a name in a plain
string is still not a reference.

### Removed

`rollback` from `utils.diff` and `Path_stem` from `scanner.risk`, both
genuinely dead - found by the fixed self-scan. `rollback` restored from a
`.bak` name that nothing has written since 0.2.7.

### Known limitation

Nothing in a class extending a base outside the repository is reported dead,
not even an unused private helper. On Android that is nearly every class, so
Kotlin findings come from top-level and extension functions. Narrowing this to
overrides only would find more, and would start calling an `android:onClick`
handler named in an XML layout dead.

C and C++ are not added. Their real project files parse cleanly, but it is a
larger job than Kotlin was.

## 0.2.8 - 2026-10-24

The last two untested tools, `get_chunk` and `generate_changelog`. Both were
wrong, which makes it eight of eight: every tool in this server had a real
defect the first time it was pointed at real code.

### Fixed - get_chunk refused the files it exists to read

A 955 KB source file came back as "binary, lock, or oversized". The size guard
it shares with the scanner defaults to 500 KB, which is right for a parser that
loads whole files and exactly wrong for a tool whose purpose is reading a slice
of a large one.

The size rule is now bypassed while the binary, lock and minified rules still
apply, and the read is streamed line by line, so memory is bounded by the
requested slice rather than by the file.

Also: a missing file said "binary, lock, or oversized" and now says "Not a
file"; and an inverted range (`start_line=50, end_line=10`) returns the single
line at `start_line`.

### Fixed - generate_changelog raised on state it had not written

A `health_history` entry with no `score`, a null score, or a string score threw
`KeyError`, `TypeError` and `ValueError` respectively - out through the MCP
boundary, which tool functions are not allowed to do. `reforge-state.json` is a
file on disk that an older version or a partial scan can shape differently.

Unusable entries are now skipped, and with no usable score the health line is
omitted rather than fabricated. The same applies to a `fix_log` entry that is
not a dict.

### Fixed - generate_changelog claimed success for a write that never happened

The writer ended `except OSError: pass`, and the MCP tool returned
`{"success": True}` unconditionally. A read-only file or a full disk looked
exactly like a success. `generate_changelog` now returns whether it wrote, and
the tool reports `success: False` with the path when it did not.

## 0.2.7 - 2026-10-24

**If you have run `write_fix` on a Windows checkout, check `git diff`.** Before
this release it could rewrite every line ending in the file, including on calls
that changed nothing and calls that failed.

The first adversarial exercise of `write_fix` - the one tool that writes to
disk. Four defects, all in the "the file must be either correctly changed or
byte-identical" contract.

### Fixed - every line ending in the file was rewritten

Both the applier and the backup read with `read_text` and wrote with
`write_text`. Reading folds CRLF to LF; writing expands LF to the platform's
ending. On Windows an LF file came back as CRLF whatever the diff said, so a
two-line patch produced a diff against the whole file.

Both sides now use `newline=""`, and replacement lines - which come out of the
diff, with the diff's endings - are reterminated to the file's own. A CRLF file
patched by an LF diff stays entirely CRLF, and the reverse.

All ten existing diff tests created their fixture with `write_text` and
asserted with `read_text`, so the translation cancelled out on both sides of
every assertion. The new tests compare bytes.

### Fixed - a refused diff still rewrote the file

The applier correctly leaves the file alone when a diff does not match, but
`write_fix` then restored from the re-encoded backup anyway. A call that
changed nothing rewrote every line. Same for an empty diff.

The backup is now a byte-for-byte copy, so restoring it is a no-op on the paths
where nothing needed restoring.

### Fixed - a pre-existing .bak file was destroyed

The backup was written to `<file>.bak`, overwriting whatever was there, and
deleted on success. If you keep your own `config.py.bak`, it was gone. The
backup now uses a unique `tempfile` name in the same directory.

### Fixed - a non-UTF8 file raised instead of returning

Only `OSError` was caught, so `UnicodeDecodeError` escaped across the MCP
boundary. A binary file now returns `success: False` and is left untouched.

### Not covered

No test interrupts the process mid-write. The applier writes a `.tmp` and
renames, and the restore is a single `os.replace` - both atomic - but that is
reasoned, not demonstrated.

## 0.2.6 - 2026-10-24

The first time anyone pointed `score_risk`, `infer_architecture` and
`get_health_score` at real code. All three were wrong.

### Breaking

`score_risk` takes `repo_path` instead of `dep_graph` and `scan_result`. It
needs per-file reference data the caller had no way to supply.

### Fixed - score_risk never looked at the symbol

Asked about `parseCommand`, a wire-protocol parser with nine call sites, it
answered "safe to fix". So did a name that exists nowhere, and the empty
string - all three scored 29.

- `inbound_refs` counted imports of the *file*, so `symbol` went unused. It now
  counts files that reference the symbol, which also catches a caller that has
  no import edge at all - MyCam's `app.js` reaches `parseCommand` through a
  `<script>` tag.
- `has_tests` claimed to check "whether a test file references this symbol" and
  actually checked whether any file in the repo had "test" in its name. It now
  requires a referencing file to be a test.
- `lines_changed` was the repo average unless the file was already flagged as
  oversized. It now sizes the real file.
- Path separators changed the answer: `web/p.js` scored 0 inbound refs where
  `web\p.js` scored 12.

The result now carries `basis` ("symbol" or "file") and `referenced_by`, so the
score can be checked rather than trusted. `parseCommand` scores 48, "fix with
caution".

### Fixed - infer_architecture classified by filename

It called an Android camera app a "REST API" with confidence 0.7, because the
REST marker list contained "app" and the repo had an `app.js`. Confidence was
`ratio * 3 + 0.2`, and a winner was always elected even when every score was
zero.

Classification is now by what the code imports: flask, fastapi, django,
express for REST; argparse, click, typer for CLI; react, vue, svelte for a
frontend. With no framework import, a package is a "library" and anything else
is `"unknown"` at 0.1 confidence instead of a guess. The result carries
`evidence` - the imports the verdict rests on.

### Fixed - get_health_score reported 90/100 for a repo it had barely read

Every ratio in the score is taken over scanned files, so 169 unreadable Kotlin
and C++ files did not count and a 6-file scan scored 90. The result now carries
`coverage`, with a `caveat` below 0.5 naming the fraction.

### Added

- `summary.imported_modules` - the distinct top-level module of every import.
- `scan_repo(include_references=True)` - adds `references_by_file` and
  `lines_by_file`. Off by default because it is large.

## 0.2.5 - 2026-10-24

### Fixed - a require() with a computed path is read

```js
const P = require(path.join(__dirname, "..", "..", "companion", "web", "protocol.js"));
```

That is how a Node script references a sibling when it needs an absolute path,
and it was invisible: the argument is a `path.join` call, not a string literal,
so 0.2.4 saw no import at all. Two real dependencies in the repository that
prompted this work were missing from its graph.

`path.join` and `path.resolve` rooted at `__dirname` are now read. A path built
from a variable is still not followed - guessing at it would invent an edge
that does not exist.

This also makes the counts above honest. On that repository 0.2.4 would have
reported zero edges and zero unresolved relative imports, which reads as "this
code has no internal imports" - and that was false.

### Added - the dependency graph says why it is empty

A scan reporting 22 imports and `edges: []` was read as a broken resolver three
times, by two different readers. It was not: for a repository whose JavaScript
is loaded through `<script>` tags and whose Python imports only the standard
library, no edges is the correct answer. The output just could not tell that
apart from a resolver dropping every import on the floor.

`dep_graph` now carries two counts:

- `external_imports` - imports that leave the repository: stdlib, npm, a
  vendored package. These can never be edges.
- `unresolved_relative_imports` - a relative import that must point inside the
  repository and did not resolve. Anything above zero here is a defect in this
  tool, and worth reporting.

Zero edges alongside zero unresolved relative imports now means "this code has
no internal imports". This project's own scan reports 24 edges, 112 external,
0 unresolved.

A `<script src=...>` tag is still not an import anywhere in the AST, so files
sharing browser globals have no detectable dependency between them. The counts
make that visible rather than leaving it to look like a bug.

## 0.2.3 - 2026-10-24

Re-scan anything you scanned with an earlier version. Until now the scan
analysed code your repository does not own, and reported findings in it.

### Fixed

- **Only git-tracked files are analysed.** A scan of a repo with a Claude Code
  skill installed put *every* dead-code finding in untracked
  `.github/skills/` vendor scripts - code the user did not write and cannot
  change. Filtering was a fixed list of directory names (`node_modules`,
  `dist`, ...), which can never cover the next place something gets vendored.
  Tracked-only replaces that denylist with one rule, and also excludes build
  output, caches and anything gitignored. A non-git directory still scans
  everything, so the tool works outside git.

  `summary.untracked_files_skipped` reports how many parseable files this
  removed, so the filter is visible rather than silent.

- **A bare Python import no longer resolves to a sibling inside a package.**
  `from git import Repo` resolved to the `git.py` module sitting next to it
  rather than to installed GitPython, inventing a dependency the code does not
  have. Any dependency whose name collides with a local module did this. Inside
  a package the import is now treated as external; a flat directory of scripts,
  where the sibling genuinely is what the import means, is unchanged.

  Found by this project's own self-scan, which went from 24 edges to 25 right
  after the fix above.

### Note

A file you have created but not yet `git add`ed is no longer analysed. The rule
is "analyse what the repository versions"; add the file to see it in a scan.

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
