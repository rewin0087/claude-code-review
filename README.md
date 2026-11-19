# claude-code-review

An AI code reviewer for [Claude Code](https://claude.com/claude-code). It reviews **only the changes your branch introduces**, or just the file, lines or editor selection you point it at, in any tech stack. It checks the approach, suggests better alternatives backed by web sources, looks back through git history to see *why* the existing code was written that way, and opens an **interactive HTML report** with the review comments shown on the diff lines.

It runs on your existing Claude Code session. You don't need an API key or a server.

## Features

- **Branch-only diff**: compares against the merge-base, so commits that landed on `main` after you branched are excluded. The base branch (`main`, `master`, `develop`, …) is detected automatically.
- **Any stack**: detects languages, frameworks and versions from the files and manifests, and fits its advice to the versions you use.
- **Approach validation**: infers what the change is trying to do and rates the approach (sound / acceptable / questionable / flawed). It proposes alternative approaches with pros and cons and marks one as recommended.
- **Reasoned comments**: each comment has a severity, category, confidence, a concrete failure scenario, its reasoning, a suggested fix with code, and alternatives.
- **Web references**: cites official docs, OWASP/CWE, RFCs and well-known open-source projects. It may only cite links it actually opened, and its searches never include your code.
- **Git history ("why is it like this?")**: blames the lines your branch removes or rewrites and finds the commits that introduced them. It flags past fixes, reverts and workarounds, and warns when a change could bring an old bug back. Every cited commit SHA is checked against the repo.
- **Interactive report**: unified or side-by-side diff with inline comments, a file/comment sidebar, severity filters, search, resolve/viewed tracking, an "Open in VS Code" link, commit links to GitHub/GitLab, keyboard navigation, dark mode, and "Copy as Markdown" for PR descriptions.
- **Large diffs**: split across parallel sub-agents.

## Install

Install it **for one folder only** (it's available when you start `claude` in that folder):

```bash
git clone https://github.com/rewin0087/claude-code-review.git <folder>/.claude/skills/code-review
```

Or **for every project**:

```bash
git clone https://github.com/rewin0087/claude-code-review.git ~/.claude/skills/code-review
```

Requirements: Claude Code, `git`, and Python 3.8+ (standard library only).

> Claude Code looks for project skills from the folder where you start it up to that repo's root. If the skill is in a parent folder that holds several repos, start `claude` in the parent folder and pass the repo name (see below), or install it globally.

## Usage

Inside Claude Code:

```text
/code-review                              # review the checked-out branch against its base
/code-review my-repo                      # review a repo inside the current folder
/code-review my-repo --head feat/login    # review another branch without checking it out
/code-review develop                      # set the base branch yourself
/code-review --uncommitted                # include staged and unstaged changes
/code-review --history                    # deep git-history investigation
/code-review --focus security             # put more weight on one area
/code-review --no-open                    # don't open the browser
```

You can also ask in plain words, e.g. *"review this with history"*.

### Review specific files, lines or the editor selection

```text
/code-review src/billing/charge.ts            # one file
/code-review src/billing/charge.ts:40-80      # a line range (also :40 or #L40-L80)
/code-review src/billing/ 'src/**/*.sql'      # folders and globs
/code-review @src/app.py                      # Claude Code @-mentions work too
/code-review --selection                      # the code highlighted in VS Code / JetBrains
/code-review --file                           # the file open in the editor
/code-review --all                            # ignore the editor; review the whole branch
```

- In the IDE, **highlighted code is used automatically**: highlight lines, run `/code-review`, and only that selection is reviewed. An open file with nothing highlighted is ignored unless you pass `--file` or say "review this file".
- If the branch changed code inside the scope, those changes are reviewed. If it didn't (or you're on `main`), the **current code is reviewed as-is**. Mixed scopes do both, file by file. `--changes-only` / `--as-is` force one mode.
- Scoped reviews include uncommitted edits, so line numbers match your editor. Each scope gets its own report folder, so it doesn't overwrite the full-branch report.

When the review finishes, Claude posts a summary in the chat (terminal or VS Code): the verdict, the approach rating, the recommended alternative, history notes, a table of **every** finding with `file:line`, and a link to the full interactive report. The same summary is saved as `summary.md`.

The report is written to `<repo>/.code-review/<branch>/report.html`. That folder is added to the repo's local `.git/info/exclude`, so it never gets committed.

### Report keyboard shortcuts

| Key | Action |
|---|---|
| `j` / `k` | next / previous comment |
| `n` / `p` | next / previous file |
| `r` | resolve / reopen the focused comment |
| `x` | collapse / expand the focused comment |
| `s` | toggle unified / split view |
| `e` | collapse / expand all files |
| `o` | jump to the overview |
| `/` | filter |
| `t` | toggle theme |
| `?` | help |

## How it works

```
SKILL.md                    instructions Claude follows (review method, history, references, output)
scripts/collect_diff.py     finds the base + merge-base, writes diff.patch / diff.json / meta.json
scripts/history.py          git blame + log at the merge-base for the lines being changed
references/review-schema.md the review.json format Claude writes
scripts/render.py           checks review.json (anchors, SHAs) and builds the HTML report
templates/report.html       the self-contained interactive report
```

1. `collect_diff.py` diffs `merge-base(base, head)..head`.
2. Claude reads the full changed files, their callers and tests, and (when needed) the git history.
3. Claude researches supporting references on the web.
4. Claude writes `review.json`, which `render.py` checks and turns into the report.

Syntax highlighting loads highlight.js from cdnjs. Without internet the report still works, just without colours.

## License

MIT
