# Changelog

All notable changes to this project are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and versions follow
[Semantic Versioning](https://semver.org/).

## [2.1.0] - 2026-11-27

### Added
- **Focus areas: N+1 queries, SQL injection, performance and benchmarks.** Always assessed, each
  with a status, findings and a recommended fix, in a new report card and a new table in the chat
  summary (`summary.focus_areas` in review.json).
- Built-in `sql-checks` scanner: flags SQL built with interpolation/concatenation, `ORDER BY` from
  request input, and database calls inside loops (N+1 suspects). The reviewer confirms or dismisses each.
- **Recommended fixes you decide on.** Every finding carries one recommended fix marked *required* or
  *optional*, with effort and why it's the best fix. The report has **Agree / Won't fix / Comment**
  on each fix (saved in the browser) and a **Copy decisions** button that you paste back into Claude
  Code. The chat summary asks for your call (`agree c1 c3`, `skip c2`, `c4: …`). Claude implements
  only the fixes you agreed to (new Step 8).
- Per-finding `benchmark` numbers (before/after).
- **Word-level diff.** Inside a changed line, the exact words added, removed or replaced get a
  second, stronger highlight on top of the line colour (replaced words are underlined, and hovering
  shows the old/new text). Toggle with the **Word diff** button or `w`. Works in unified and split views.
- Keyboard: `a` / `d` agree / won't fix the focused finding.

### Changed
- The findings table in the chat now shows the comment ID, focus area, and whether the fix is
  required or optional.

## [2.0.0] - 2026-11-20

### Changed (breaking)
- Renamed the command from `/code-review` to **`/branch-review`**, so it no longer hides Claude
  Code's built-in `/code-review` (or clashes with the official `code-review` plugin). The plugin is
  now `branch-review@rewin0087`, run as `/branch-review:branch-review`. Standalone installs go in
  `~/.claude/skills/branch-review`. The GitHub repo keeps its name.
- The output folder is now `.branch-review/<branch>/` (it was `.code-review/`).

### Added
- README: "How it compares" with the built-in `/code-review` and the official plugin.

### Upgrading
- Plugin: `claude plugin uninstall code-review@rewin0087`, then `claude plugin marketplace update rewin0087`
  and `claude plugin install branch-review@rewin0087`.
- Standalone: `mv ~/.claude/skills/code-review ~/.claude/skills/branch-review`.
- Old `.code-review/` folders in your repos can be deleted.

## [1.1.0] - 2026-11-20

### Added
- **Review against requirements**: `--req <file|url|text>` (repeatable) and free text after ` -- `.
  Takes tickets, specs (md, txt, pdf, docx), mockup images and links, plus anything pasted in the
  chat. A new `context.py` collects the sources. The review turns them into a requirements
  checklist (met / partial / missing / contradicted / unclear) with evidence lines and linked
  comments, and checks that mandated tools, APIs and data formats are used correctly.
- **Reuse / DRY**: the reviewer searches the codebase for existing code the change duplicates.
  Comments can carry a `reuse` pointer to the code to reuse or extend.
- **Automated checks**: a new `scan.py` runs a built-in secret detector plus semgrep, bandit,
  npm audit and pip-audit when installed, only on the reviewed files. Findings on changed lines
  are separated from pre-existing ones, and secret values are redacted.
- **Performance and memory**: a per-stack memory-leak checklist, static performance analysis,
  and optional throwaway benchmarks (`--bench` / `--no-bench`) written to the output folder.
- **Impact and caveats**: breaking changes, caveats, considerations, affected areas and rollout.
- Report: Requirements, Impact & caveats, and Analysis & automated checks sections; requirement
  chips and reuse boxes on comments; click-to-line evidence links. The chat summary includes
  requirements coverage, breaking changes, caveats and check results.
- Validation for the new fields, including unknown requirement links, unexplained gaps and reuse
  targets that don't exist.

## [1.0.0] - 2026-11-19

First public release.

### Added
- `/code-review` Claude Code skill. It reviews **only the changes a branch introduces**
  (`merge-base..head`) in any tech stack and detects the base branch automatically.
- Scoped reviews: files, line ranges (`file:40-80`, `file#L40-L80`), folders, globs,
  `@`-mentions, and the code highlighted in VS Code or JetBrains (`--selection`, `--file`, `--all`).
  Unchanged code in scope is reviewed as-is.
- Approach validation: a rating plus alternative approaches with pros, cons and a recommendation.
- Web-referenced findings (official docs, OWASP/CWE, RFCs, open-source code). Every critical/major
  finding and alternative approach must cite a source, and `render.py` warns when one doesn't.
  Only links that were actually opened are cited, and no repo code goes into search queries.
- Git-history analysis (`--history`, or automatic when existing code changes). It blames the lines
  being changed, flags past fixes, reverts and workarounds, and every cited SHA is checked.
- Interactive HTML report: unified and split diff, inline comments, severity filters, search,
  resolve and viewed tracking, Open in VS Code, commit links, keyboard navigation, dark mode,
  and Copy as Markdown.
- A summary in the chat with the verdict, the approach, a table of every finding, and a link to the report.
- Large diffs are split across parallel sub-agents.
- Installs as a Claude Code plugin (its own marketplace), or by cloning into a skills folder.

[1.0.0]: https://github.com/rewin0087/claude-code-review/releases/tag/v1.0.0
[1.1.0]: https://github.com/rewin0087/claude-code-review/compare/v1.0.0...v1.1.0
[2.0.0]: https://github.com/rewin0087/claude-code-review/compare/v1.1.0...v2.0.0
