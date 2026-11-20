# review.json schema

Write exactly one JSON object to `<OUT_DIR>/review.json`. All string fields that say
"markdown" support: paragraphs, `inline code`, fenced ```lang code blocks, **bold**,
*italic*, [links](https://...), and `-` / `1.` lists.

```jsonc
{
  "summary": {
    "verdict": "approve | approve_with_suggestions | request_changes",
    "headline": "One sentence: what this branch does and the bottom line.",
    "overview": "markdown — what changed and why it matters, 1-3 short paragraphs",
    "stack": ["Ruby on Rails 7.1", "React 18", "PostgreSQL"],   // detected tech
    "intent": "What the author appears to be trying to achieve (inferred from code + commits)",
    "approach_assessment": {
      "rating": "sound | acceptable | questionable | flawed",
      "analysis": "markdown — does the chosen approach actually solve the problem? correctness, fit with the existing codebase, scalability, security, operability",
      "alternatives": [
        {
          "title": "Use a background job instead of an inline HTTP call",
          "description": "markdown — how it would work",
          "pros": ["..."],
          "cons": ["..."],
          "recommended": true,
          "references": [{ "title": "...", "url": "https://...", "note": "what this source supports" }]
        }
      ]
    },
    "strengths": ["markdown bullet", "..."],
    "risks": ["markdown bullet — the things most likely to break in production", "..."],
    "test_assessment": "markdown — are the changes tested? what's missing?",
    "requirements": {                              // include when requirement sources were given (Step 1b)
      "coverage_note": "markdown — which sources were used, anything that couldn't be read",
      "items": [
        {
          "id": "R1",
          "source": "S1",                          // id from context.json (or "chat" for pasted content)
          "text": "markdown — one testable requirement",
          "status": "met | partial | missing | contradicted | unclear | not_applicable",
          "evidence": [ { "file": "app/invoice.py", "line": 12, "note": "where it's (not) satisfied" } ],
          "comments": ["c2"],                      // comments that explain a gap; required when not met
          "notes": "optional markdown"
        }
      ]
    },
    "impact": {                                    // always include (Step 3c)
      "breaking_changes": ["markdown — what breaks, for whom"],
      "caveats": ["markdown — true after merging and easy to miss"],
      "considerations": ["markdown — check or decide before shipping"],
      "affected_areas": ["markdown"],
      "rollout": "markdown — how to ship safely (optional)"
    },
    "checks": [                                    // analysis results (Step 3b) — not scanner output
      {
        "name": "Benchmark: invoice_total, 10k lines",
        "kind": "benchmark | performance | memory | security | other",
        "status": "pass | warn | fail | info",
        "result": "markdown — the conclusion with numbers",
        "details": "markdown — command, code, raw numbers (optional)"
      }
    ],
    "history": {                                   // optional; include when Step 2b ran
      "context": "markdown — why the existing code was written that way, and whether this branch's reason for changing it holds up",
      "timeline": [
        { "sha": "a1b2c3d", "date": "2024-03-02", "subject": "Fix double charge on retry", "note": "added the idempotency key this branch removes" }
      ]
    }
  },

  "comments": [
    {
      "id": "c1",                                  // unique, stable
      "file": "app/models/user.rb",                // MUST equal a `path` in diff.json
      "line": 42,                                  // line number on `side`; null = file-level comment
      "end_line": 47,                              // optional, for multi-line ranges (same side)
      "side": "new",                               // "new" (added/context lines) or "old" (deleted lines)
      "severity": "critical | major | minor | suggestion | nitpick | praise",
      "category": "bug | regression | security | requirements | duplication | memory | dependency | performance | design | correctness | concurrency | error-handling | testing | readability | maintainability | best-practice | accessibility | api-design | data",
      "confidence": "high | medium | low",
      "title": "Short imperative headline",
      "body": "markdown — what is wrong and the concrete impact (inputs/state -> wrong outcome)",
      "reasoning": "markdown — step-by-step why you believe this; what you checked in the surrounding code",
      "suggestion": {
        "description": "markdown — the better approach",
        "code": "replacement code for the commented line(s), no diff markers",
        "language": "ruby"
      },
      "alternatives": [
        { "title": "...", "description": "markdown", "code": "optional", "language": "optional" }
      ],
      "requirements": ["R1"],                      // optional: requirement ids this comment is about
      "reuse": {                                   // optional: existing code to reuse or extend (DRY)
        "file": "app/money.py", "line": 4, "symbol": "format_currency(amount_cents, currency)",
        "description": "markdown — how to use or extend it here"
      },
      "history": [                                 // optional: commits that explain this code's past
        { "sha": "a1b2c3d", "subject": "Fix double charge on retry", "note": "why this guard exists" }
      ],
      "references": [
        { "title": "Rails Guides — Active Record Callbacks", "url": "https://guides.rubyonrails.org/...", "note": "explains after_commit vs after_save" }
      ]
    }
  ],

  "references": [ { "title": "...", "url": "https://...", "note": "..." } ]   // global bibliography
}
```

## Severity guide

| severity | use when |
|---|---|
| critical | data loss, security hole, crash on a common path, broken build/migration |
| major | real bug on a plausible path, wrong behaviour, serious perf/scalability problem |
| minor | edge-case bug, missing error handling, weak test coverage of new logic |
| suggestion | a clearly better design/idiom; current code works |
| nitpick | style / naming; only if the project has no linter enforcing it |
| praise | a notably good decision worth keeping (use sparingly, 0-3 per review) |

## Anchoring rules

- `line` must be a line that appears in the diff hunks for that file on the given `side`
  (an added `+` line or a context line for `new`; a removed `-` line for `old`).
  Use the line numbers from `diff.json` (`n` = new, `o` = old). The renderer
  moves comments whose line is not in the diff to the file-level section and warns.
- Prefer anchoring on the first line of the problematic statement.
- Use `line: null` for comments about the file as a whole (e.g. "this file needs tests").

## Requirements, reuse and checks rules

- Every requirement with status `partial`, `missing` or `contradicted` must link a comment
  (`comments`) or explain the gap in `notes`.
- `evidence` and `reuse.line` use current (new-side) line numbers. `evidence` must point at lines in
  the review. `reuse.file` may be anywhere in the repo, and must exist.
- Scanner output is shown by the report automatically from `scan.json`. Don't copy it into
  `checks`; turn real findings into comments instead.

## History rules

- `sha` must be a real commit you saw in `history.py` output or a git command (short or full).
  `render.py` warns about SHAs that don't exist in the repo — fix or remove them.
- `note` explains what that commit tells us about *this* code, not just its subject line.

## Reference rules

- Only cite URLs you actually opened with WebFetch or saw in WebSearch results during this run.
  Never invent URLs, version numbers or quotes.
- Prefer, in order: official docs / specs (language, framework, RFC, W3C, OWASP, CWE),
  source code or issues of well-known open-source projects (link to the exact file/line or
  issue on GitHub), then respected engineering blogs.
- `note` says what the source supports, so the reader knows why it is there.
