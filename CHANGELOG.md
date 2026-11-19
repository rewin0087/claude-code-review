# Changelog

All notable changes to this project are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and versions follow
[Semantic Versioning](https://semver.org/).

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
