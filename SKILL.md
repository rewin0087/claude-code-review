---
name: code-review
description: Review ONLY the changes introduced by the current git branch (merge-base..HEAD) in any tech stack, use git history to understand why existing code was written that way, validate the approach, propose better/alternative approaches backed by web references, and open an interactive HTML report showing the diff with the review comments inline.
argument-hint: "[repo-dir] [base-branch] [--head <branch>] [--uncommitted] [--history] [--focus <area>] [--no-open]"
disable-model-invocation: true
allowed-tools: Bash(python3 ${CLAUDE_SKILL_DIR}/scripts/*) Bash(git diff *) Bash(git log *) Bash(git show *) Bash(git blame *) Bash(git rev-parse *) Bash(git merge-base *) Bash(git ls-files *) Bash(git status *) Bash(git -C *) Bash(git grep *) Bash(ls *) Read Grep Glob WebSearch WebFetch Agent Write(**/.code-review/**)
---

# Branch code review

Arguments: `$ARGUMENTS`

Parse the arguments:
- a bare word that is an existing directory = the repo to review (`REPO`). Otherwise `REPO` is
  the current directory. If the current directory is not inside a git repo and no directory was
  given, find git repos one level down (`ls -d */.git`) and ask the user which one to review
  (AskUserQuestion); if there is exactly one, use it.
- any other bare word (no `--`) = base branch (optional; auto-detected otherwise)
- `--head <branch>` = review that branch without checking it out (default: the checked-out branch)
- `--uncommitted` = also review staged/unstaged working-tree changes
- `--history` = do a deep git-history investigation (Step 2b is mandatory and thorough). The
  user may also ask for this in words ("review with history", "check why it was done this way").
- `--focus <area>` = weight the review toward that area (e.g. security, performance) — still report anything critical
- `--no-open` = don't open the browser at the end

You are a principal engineer doing a rigorous, constructive review. Your job is not only to
find bugs but to judge whether the **approach** is right and show a better one when it isn't.

## Step 1 — Collect the branch diff

```bash
python3 ${CLAUDE_SKILL_DIR}/scripts/collect_diff.py --repo <REPO> [--base <base>] [--head <branch>] [--uncommitted]
```

It finds the repo root from `--repo`; use that root for all later reads, greps and git
commands (`git -C <root> ...`). If `meta.json` has `"checked_out": false`, the working tree
is a different branch: read files with `git -C <root> show <head_ref>:<path>` instead of Read, and
grep with `git -C <root> grep <pattern> <head_ref>`. It diffs from the merge-base, so
only this branch's own changes are included. Note the `OUT_DIR=` line. If it exits with an
error (not a repo, no changes, base not found), tell the user the message and stop.

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

## Step 3 — Review

Apply this checklist to every change, adapting to the stack:

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
  memory, caching, bundle size for frontend.
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

## Step 4 — Validate the approach and back it with references

Write the `approach_assessment`: infer the intent, then judge whether the chosen solution is
the right one. Offer at least one alternative approach (mark one `recommended` if it beats the
current one; if the current approach is best, say so and explain why the alternatives lose).

Use `WebSearch`/`WebFetch` to support important claims (every critical/major comment and every
alternative approach should have at least one reference when a good source exists): official
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

If it reports JSON or validation errors, fix `review.json` and re-run. If it warns that a
comment's line is not in the diff, re-check the anchor and fix it if it was a mistake.

## Step 7 — Report back in the terminal

Keep it short: verdict + headline, counts by severity, the top 3 issues as
`file:line — title`, the recommended alternative approach (one line), and the full path to the
HTML report. Do not paste the whole review into the terminal.
