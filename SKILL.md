---
name: code-review
description: Review ONLY the changes introduced by the current git branch (merge-base..HEAD), or a specific file / line range / folder / editor selection, in any tech stack. Checks the code against supplied requirements (ticket text, docs, images, links), validates the approach and business logic, looks for reusable existing code, runs security/dependency scanners, analyses performance and memory (with optional benchmarks), uses git history, lists impact and caveats, and opens an interactive HTML report with the review inline on the diff.
argument-hint: "[path[:start-end] ...] [--req <file|url|text> ...] [--selection|--file|--all] [repo-dir] [base-branch] [--head <branch>] [--uncommitted] [--history] [--bench|--no-bench] [--no-scan] [--focus <area>] [--no-open] [-- requirements text]"
disable-model-invocation: true
allowed-tools: Bash(python3 ${CLAUDE_SKILL_DIR}/scripts/*) Bash(git diff *) Bash(git log *) Bash(git show *) Bash(git blame *) Bash(git rev-parse *) Bash(git merge-base *) Bash(git ls-files *) Bash(git status *) Bash(git -C *) Bash(git grep *) Bash(ls *) Read Grep Glob WebSearch WebFetch Agent Edit(**/.code-review/**)
---

# Branch code review

Arguments: `$ARGUMENTS`

Parse the arguments:
- **repo**: a bare word that is a directory containing its own `.git` (a different repo from the
  current one) = the repo to review (`REPO`). Otherwise `REPO` is the current directory. If the
  current directory is not inside a git repo and no repo was given, find git repos one level down
  (`ls -d */.git`) and ask the user which one to review (AskUserQuestion); if there is exactly
  one, use it.
- **scope paths** (each becomes a `--path`): any bare word that is an existing file or folder in the
  repo, a glob (`src/**/*.ts`), or a file with a line range: `app/models/user.rb:40`,
  `user.rb:40-80`, `user.rb#L40-L80`. Paths are relative to the current directory or the repo
  root. `@file` mentions from Claude Code count as paths too (drop the `@`).
- **any other bare word** (no `--`) = base branch (optional; auto-detected otherwise)
- `--selection` = review only the code highlighted in the editor (see "Scope" below)
- `--file` = review only the file open in the editor
- `--all` = ignore editor context and review the whole branch
- `--changes-only` = in a scoped review, only review branch changes (never the code as-is)
- `--as-is` = in a scoped review, ignore the diff and review the current code itself
- `--head <branch>` = review that branch without checking it out (default: the checked-out branch)
- `--uncommitted` = also review staged/unstaged working-tree changes
- `--history` = do a deep git-history investigation (Step 2b is mandatory and thorough). The
  user may also ask for this in words ("review with history", "check why it was done this way").
- `--req <file|url|text>` (repeatable; aliases `--ticket`, `--spec`, `--context`) = requirements and
  context to review against: a ticket or spec file (txt, md, pdf, docx…), an image (mockup,
  diagram, screenshot), a URL (ticket, design doc, API docs), or quoted free text.
- everything after a standalone ` -- ` = free-text requirements / instructions / caveats.
- Also treat as requirements: images or files the user attached or pasted in the conversation,
  `@`-mentioned documents that aren't code under review, and requirement-like instructions written
  in the user's message ("it must…", acceptance criteria, a todo list). If unsure whether an
  `@file` is code to review or a spec, a `.md/.txt/.pdf/.docx/image` outside the diff is a spec.
- `--bench` = always benchmark the performance-sensitive code (Step 3b); `--no-bench` = never run benchmarks.
- `--no-scan` = skip the automated scanners (Step 2c). When turning a scanner finding into a
  comment, its rule or advisory URL from `scan.json` counts as a reference.
- `--focus <area>` = (e.g. security, performance) — still report anything critical
- `--no-open` = don't open the browser at the end

### Scope — what to review

Pick the scope in this order, then say which one you chose in one line before starting:

1. **Explicit paths/ranges in the arguments**: use those.
2. **Editor context (VS Code / JetBrains)**: the IDE extension shares the user's editor state with
   you in the conversation context, e.g. "The user selected the lines 40 to 80 from
   /abs/path/user.rb" with the selected text, or "The user opened the file /abs/path/user.rb".
   - `--selection`, or the user says "this", "the selection", "the highlighted code" → scope to that
     file **and line range** (`<path>:<start>-<end>`).
   - `--file`, or the user says "this file", "the open file" → scope to that whole file.
   - With no flag and no such words: if a **selection** (a highlighted line range) is present, scope to
     it, because highlighting is a deliberate signal. Say so, and tell the user `/code-review --all`
     reviews the whole branch. An open file **without** a selection is not a signal (the IDE always
     reports one), so ignore it and review the whole branch.
   - `--selection` / `--file` but no such context → tell the user nothing is selected or open,
     and stop.
   - Free text works too: "review lines 10-30 of utils.py" → `utils.py:10-30`.
3. **Otherwise** the whole branch diff, or the scope given by `--all`.

For a scoped review the collector picks the mode itself:
- `changes`: the branch changed code in the scope → review those changes (only hunks overlapping
  the range are kept).
- `code`: no branch changes in the scope → review the **current code as-is**. This also works on
  `main`, or with no base branch at all.
- `mixed`: some of each.
Scoped reviews include uncommitted edits, so line numbers match what the user sees in the editor.

You are a principal engineer doing a rigorous, constructive review. Your job is not only to
find bugs but to judge whether the **approach** is right and show a better one when it isn't.

## Step 1 — Collect the branch diff

```bash
python3 ${CLAUDE_SKILL_DIR}/scripts/collect_diff.py --repo <REPO> [--path <p> ...] [--mode changes|code] \
    [--base <base>] [--head <branch>] [--uncommitted]
```

Pass each scope item as its own `--path` (quote globs). Use `--mode changes` for `--changes-only`
and `--mode code` for `--as-is`. Otherwise leave the mode at `auto`. Note the `Mode:` line in the output.

It finds the repo root from `--repo`; use that root for all later reads, greps and git
commands (`git -C <root> ...`). If `meta.json` has `"checked_out": false`, the working tree
is a different branch: read files with `git -C <root> show <head_ref>:<path>` instead of Read, and
grep with `git -C <root> grep <pattern> <head_ref>`. It diffs from the merge-base, so
only this branch's own changes are included. Note the `OUT_DIR=` line. If it exits with an
error (not a repo, no changes, base not found), tell the user the message and stop.

## Step 1b — Gather requirements and context (when any were given)

Collect every requirement source from the arguments and the conversation (see `--req` above).
Pasted or typed text goes in as a quoted `--source` string. Then run:

```bash
python3 ${CLAUDE_SKILL_DIR}/scripts/context.py --dir <OUT_DIR> --cwd <current dir> \
    --source <file|url|"text"> [--source ...]
```

It copies files and text into `<OUT_DIR>/context/`, records them in `context.json` as S1, S2, …
and prints text sources inline. Then:
- **Read** every file under `READ_FILES` (images and PDFs). Look at mockups and diagrams carefully:
  field names, states, error messages, flows.
- **WebFetch** every URL under `FETCH_URLS`. Tickets and private docs often need a login. If a
  fetch fails or returns a login page, say so in one line and ask the user to paste the content.
  Don't guess what the ticket says. For GitHub/GitLab issue links, `gh issue view <url>` or
  `glab issue view <url>` may work if installed and logged in.
- Images the user pasted directly in the chat are already visible to you. Note them as a source
  in `summary.requirements.coverage_note` (they can't be copied into the report).

Distil the sources into a numbered checklist, `summary.requirements.items` R1, R2, …, one
testable statement each, citing its source id. Include: acceptance criteria and business rules;
**mandated tools, libraries, APIs, endpoints, data formats and versions** ("use the pdf-service
API", "amounts in cents"); non-functional requirements (performance budgets, security, a11y);
edge cases; and caveats the ticket mentions. Never put ticket or business content into web
searches.

With no requirement sources, skip this step and infer intent from the code and commits as usual.

**Reviewing code as-is** (files with status `snapshot`, mode `code` or `mixed`): there is no diff,
so review the selected lines (marked `"s": 1` in diff.json; the extra lines around them are
context) as you would code in a PR. Look for bugs, security, design, performance and readability, and
check whether the design suits what the code is for. In the approach assessment, judge how
the code is designed rather than "the branch's change". Anchor comments on `side: "new"` with
the current line numbers. Keep comments inside the selected lines unless the surrounding code
causes the problem. Git history (Step 2b) is especially useful here to explain why the code
looks the way it does.

## Step 2 — Understand before judging

1. Read `<OUT_DIR>/diff.patch` (and `meta.json` for commit messages — they reveal intent).
2. Detect the stack from file extensions and manifests (`package.json`, `Gemfile`, `go.mod`,
   `pyproject.toml`, `pom.xml`, `*.csproj`, `Cargo.toml`, `composer.json`, …). Note framework
   versions — advice must fit the version actually used.
3. For every non-generated changed file, Read the **full current file** (not just the hunk)
   and Grep for callers/usages of changed functions, classes, routes, columns, and config keys.
   Look at neighbouring code and existing tests to learn the project's conventions — the best
   alternative is often "do it the way the rest of this codebase already does".
4. Skim generated files (lockfiles, snapshots, build output) only for surprising dependency
   changes (new packages, major bumps, removed integrity hashes).

If the diff is LARGE (the script prints `SIZE: LARGE`), split files into 3–6 cohesive groups and
launch one `Agent` per group **in a single message** so they run in parallel. Give each agent:
the repo path, `OUT_DIR`, its file list, the branch intent you inferred, the path to
`${CLAUDE_SKILL_DIR}/references/review-schema.md`, and ask it to return only a JSON array of
`comments` following that schema. You then do the cross-cutting summary and approach assessment
yourself and merge/deduplicate their comments.

## Step 2b — Look back through git history (why is the code the way it is?)

A change that looks like a simplification can quietly undo a past bug fix. Use history to learn
**why** the existing code was written as it was, and **why** the author is changing it.

Run this step when `--history` was passed or the user asked for history. Otherwise run it when it
is needed: the branch modifies or deletes existing lines (not only adds new files) **and** any of
these hold — it removes a guard, check, retry, lock, timeout, special case, or "magic" value;
reverses a previous decision; touches code that looks deliberately odd; or touches security,
money, data or concurrency code. For pure additions, skip it.

```bash
python3 ${CLAUDE_SKILL_DIR}/scripts/history.py --dir <OUT_DIR> [--deep]   # --deep when --history was passed
```

It blames, at the merge-base, the lines this branch removes or rewrites, lists recent commits per
file, extracts issue/PR/ticket refs, and flags fix/revert/workaround commits as `NOTABLE`. Then dig
deeper where it matters, using these read-only commands:
- `git -C <root> show <sha>` — the full commit that introduced the code (message + diff)
- `git -C <root> log -L <start>,<end>:<path> <merge_base>` — the evolution of a specific block
- `git -C <root> log -S '<identifier>' --oneline <merge_base>` — when a symbol/value appeared or vanished
- `git -C <root> log --grep '<keyword>' --oneline` — related fixes, reverts or tickets
- the branch's own commit messages in `meta.json` — the author's stated reason for the change

Use what you learn:
- If the branch removes or alters code that a past commit added to fix a bug, comment on it
  (category `regression`) and cite that commit in the comment's `history`. Explain what bug may
  come back and how to keep the fix while still achieving the branch's goal.
- If history shows the old approach was a known temporary workaround, say the change is
  justified, and credit it.
- If history shows an approach was tried before and reverted, say so and explain why that matters.
- Write `summary.history` (context + timeline). Only cite SHAs you actually saw. `render.py`
  checks every SHA against the repo.

## Step 2c — Automated checks (unless `--no-scan`)

```bash
python3 ${CLAUDE_SKILL_DIR}/scripts/scan.py --dir <OUT_DIR>
```

It always runs a built-in secret detector, then any installed scanners: semgrep, bandit,
npm audit, pip-audit. It never installs anything. Findings are split into **on the change** and
**pre-existing**. Triage the on-change findings: turn real ones into review comments (cite the
tool and rule, and link the rule URL in `references`) and ignore false positives. Mention
pre-existing ones only if the change makes them worse. The report shows all scanner results in
its own section. If useful scanners for the stack are missing, mention it in one line in the
checks (e.g. "semgrep not installed").

## Step 3 — Review

Apply this checklist to every change, adapting to the stack:

- **Requirements and business logic** (when Step 1b ran): check every R-item against the code.
  Set its status: `met`, `partial`, `missing`, `contradicted` (the code does the opposite),
  `unclear` (the requirement is ambiguous) or `not_applicable`. Point to `evidence` lines and link
  the comments that explain gaps. Check that the **mandated tools, APIs, libraries and data
  formats** are the ones used, and that they're used correctly: verify the API usage (endpoint,
  parameters, auth, error codes, pagination, idempotency) against the official docs for that API
  and version. Flag behaviour the requirements didn't ask for (scope creep) and requirements that
  conflict with each other.
- **Reuse and DRY**: before accepting new helpers, utilities, components, queries, validations or
  constants, **search the codebase** (Grep/Glob on names, key strings and similar logic) for an
  existing implementation to reuse or extend. Also look for duplication inside the change. Report
  it with category `duplication` and a `reuse` pointer to the existing code (`file`, `line`,
  `symbol`, how to use it). If the existing code needs a small extension to fit, say what.
- **Correctness**: logic errors, off-by-one, null/undefined/nil, wrong conditions, unhandled
  states, timezone/encoding, integer/float issues, broken contracts with callers you found.
- **Security**: injection (SQL/command/template/XSS), authN/authZ gaps and IDOR, secrets in code,
  unsafe deserialization, SSRF, path traversal, CSRF, mass assignment, weak crypto, sensitive
  data in logs. Map to OWASP/CWE where relevant.
- **Data & migrations**: backwards compatibility, locking on large tables, irreversible
  migrations, missing indexes/constraints, N+1 queries, transactions boundaries.
- **Concurrency & reliability**: races, idempotency, retries, timeouts, resource leaks,
  error handling and failure modes of external calls.
- **Performance**: algorithmic complexity on realistic data sizes, unnecessary work in loops,
  N+1 queries, blocking I/O on hot paths, caching, bundle size for frontend. See Step 3b.
- **Memory and resource leaks**: unbounded caches, maps and lists that only grow; listeners,
  subscriptions, observers, intervals and timers not removed (`useEffect` without cleanup,
  `addEventListener` without `removeEventListener`); unclosed files, sockets, DB connections,
  cursors and streams (missing `with`/`try-finally`/`using`/`defer`/`ensure`); goroutines, threads
  or promises that never finish; closures capturing large objects; temp files never deleted;
  global or singleton state that accumulates per request.
- **Vulnerabilities and dependencies**: new or upgraded dependencies with known CVEs (from
  Step 2c, or check the advisory database), abandoned packages, too-loose version ranges, licence
  changes, and insecure defaults.
- **Design**: does it fit the existing architecture, right layer/responsibility, coupling,
  duplication of existing helpers, public API shape, naming.
- **Tests**: are new behaviours and edge cases tested; do tests assert the right thing.
- **Frontend (if any)**: accessibility, state management, effects/cleanup, rendering cost.

Rules for a high-signal review:
- Every bug claim states a concrete failure scenario (input/state → wrong outcome). If you can't
  construct one, lower `confidence` or drop it.
- Verify before claiming: check the callee, the framework behaviour, the version.
- Each non-praise comment gets a `suggestion` with real code that fits this codebase, and —
  where there is a meaningfully different design — `alternatives` with trade-offs.
- Don't flag what a linter/formatter in the repo already enforces. Quality over quantity.

## Step 3b — Performance analysis and benchmarks

Do a **static analysis** for every performance-sensitive change (loops over data, queries, hot
paths, serialisation, rendering): complexity, data sizes, allocations, I/O. Record the result in
`summary.checks` (kind `performance` or `memory`).

**Benchmark** when `--bench` was passed, or when a change is clearly performance-sensitive *and* can
be measured in isolation (pure functions, algorithms, parsing, queries against an in-memory
fixture). Don't benchmark with `--no-bench`. Rules:
- Write a throwaway script under `<OUT_DIR>/bench/` in the repo's own language that imports or
  copies the function(s). Compare the old version (from the merge-base, `git show`) with the new
  version, or the current version with your suggested alternative, on realistic input sizes, with
  several runs and a warm-up.
- **Never modify the repo**, start servers, call external services or the network, touch real
  databases, or install packages. Keep each run under ~60 seconds. Running it asks the user for
  permission, which is expected.
- Record each benchmark in `summary.checks` (kind `benchmark`): the result in `result`, and the
  command and numbers in `details`. If you can't run one (missing runtime or dependencies), say
  so and fall back to static analysis.

## Step 3c — Impact and caveats

Always fill `summary.impact`, so the developer knows the consequences of the change:
- `breaking_changes`: API/contract/schema/config/behaviour changes that break callers, clients,
  other services, stored data or the mobile/web apps. Name who is affected.
- `caveats`: things that are true *after* merging and easy to miss: data migrations, rotating a
  leaked secret, cache invalidation, feature-flag cleanup, rate limits, cost.
- `considerations`: what to check or decide before shipping: edge cases, rollout order,
  monitoring, docs, follow-up tickets.
- `affected_areas`: modules, services, endpoints, screens and jobs this touches.
- `rollout`: how to ship it safely (flags, migrations order, backfill, rollback plan), if relevant.

## Step 4 — Validate the approach and back it with references

Write the `approach_assessment`: infer the intent, then judge whether the chosen solution is
the right one. Offer at least one alternative approach (mark one `recommended` if it beats the
current one; if the current approach is best, say so and explain why the alternatives lose).

**References are required, not optional.** Every critical/major comment and every alternative
approach MUST cite at least one source you actually opened. If `WebSearch`/`WebFetch` aren't
loaded yet, load them first (e.g. with ToolSearch). Only if web access is truly unavailable,
leave those `references` empty and say "web research unavailable" in `summary.overview`. Never
skip this step silently. Use `WebSearch`/`WebFetch` to support the claims: official
docs for the exact framework version, language specs, RFCs, OWASP/CWE, and source code, docs or
issues of well-known open-source projects that solve the same problem. Run independent searches
in parallel.
- Only cite URLs you actually fetched or saw in results. Never fabricate links or quotes.
- **Never put the repo's proprietary code, names, secrets, hostnames or business data into a
  search query.** Search for the generic concept (e.g. "rails after_commit vs after_save
  transaction"), not the user's code.

## Step 5 — Write review.json

Read `${CLAUDE_SKILL_DIR}/references/review-schema.md` and write `<OUT_DIR>/review.json`
following it exactly (valid JSON, no comments/trailing commas). Anchor each comment on the
correct `side` and line number from the diff.

## Step 6 — Render the interactive report

```bash
python3 ${CLAUDE_SKILL_DIR}/scripts/render.py --dir <OUT_DIR> [--no-open]
```

If it reports JSON or validation errors, fix `review.json` and re-run. If the output ends with
**ACTION REQUIRED**, you are not done: fix each warning, re-run `render.py`, and repeat (at most
two more times). Only then reply. Any warning you couldn't fix goes in your reply. Warnings cover: a comment's line not in the diff (re-check the anchor), a
cited commit that doesn't exist, a critical/major finding or alternative without a reference
(do the web research, then re-run), a requirement marked partial/missing/contradicted without a
linked comment or notes, or a `reuse` pointer to a file that doesn't exist.

## Step 7 — Return the review in the chat

`render.py` prints a `SUMMARY` block (also saved as `<OUT_DIR>/summary.md`). Your final message
must contain that summary in full: the verdict, approach rating, recommended alternative, history
note, requirements coverage, breaking changes and caveats, automated checks, the table of **all**
findings with `file:line`, and the link to the HTML report. Copy it
as printed. Don't shorten the findings table or drop the link. You may add up to 3 sentences on
the most important thing to fix first. Don't paste the full comment bodies, which are in the report.
