"""The markdown summary relayed in the chat: verdict, approach, every finding, report link."""
import os
import re
import urllib.parse

from .review import SEVERITIES


def first_sentence(text, limit=220):
    t = re.sub(r"```.*?```", "", str(text or ""), flags=re.S)
    t = re.sub(r"\s+", " ", t).strip()
    m = re.match(r"(.+?[.!?])(\s|$)", t)
    t = m.group(1) if m else t
    return t if len(t) <= limit else t[:limit - 1].rstrip() + "…"


def file_url(path):
    return "file://" + urllib.parse.quote(os.path.abspath(path))


def _cell(x):
    return str(x).replace("|", "\\|").replace("\n", " ")


def terminal_summary(diff, review, report_path):
    meta, summary = diff["meta"], review.get("summary") or {}
    comments = sorted(review.get("comments") or [], key=lambda c: (SEVERITIES.index(c["severity"]),
                                                                   c.get("file", ""), c.get("line") or 0))
    counts = {}
    for c in comments:
        counts[c["severity"]] = counts.get(c["severity"], 0) + 1
    scope = ", ".join("`%s`" % sc["spec"] for sc in meta.get("scope") or [])
    target = ("%s on `%s`" % (scope, meta["branch"])) if scope else ("`%s` → `%s`" % (meta["branch"], meta["base"]))
    L = ["## Code review: %s — **%s**" % (target, summary.get("verdict", "").replace("_", " ").upper())]
    if summary.get("headline"):
        L.append(summary["headline"])
    L.append("")
    mode_note = {"code": "existing code reviewed as-is (no branch changes in scope)",
                 "mixed": "branch changes + existing code reviewed as-is"}.get(meta.get("mode"))
    if mode_note:
        L.append("_Scope: %s._" % mode_note)
    L.append("%d files, +%d / -%d · %d commit(s) · %s" % (
        meta["stats"]["files"], meta["stats"]["additions"], meta["stats"]["deletions"],
        len(meta.get("commits") or []),
        ", ".join("%d %s" % (counts[s], s) for s in SEVERITIES if s in counts) or "no findings"))
    aa = summary.get("approach_assessment") or {}
    if aa:
        L.append("")
        L.append("**Approach — %s:** %s" % (aa.get("rating", "n/a"), first_sentence(aa.get("analysis"))))
        rec = [a for a in aa.get("alternatives") or [] if a.get("recommended")]
        if rec:
            desc = first_sentence(rec[0].get("description"))
            L.append("**Recommended alternative:** %s%s" % (rec[0].get("title", ""), " — " + desc if desc else ""))
    hist = summary.get("history") or {}
    if hist.get("context"):
        L.append("**History:** %s" % first_sentence(hist["context"], 300))
    findings = [c for c in comments if c["severity"] != "praise"]
    if findings:
        L += ["", "### Findings", "", "| # | Severity | Location | Issue | Suggested fix |", "|---|---|---|---|---|"]
        for i, c in enumerate(findings, 1):
            loc = c["file"] + (":%s" % c["line"] if c.get("line") is not None else "")
            suggestion = c.get("suggestion") or {}
            fix = first_sentence(suggestion.get("description") or "", 140) or \
                ("see code in report" if suggestion.get("code") else "")
            L.append("| %d | %s | `%s` | %s | %s |" % (i, c["severity"], _cell(loc), _cell(c.get("title", "")), _cell(fix)))
    praise = [c for c in comments if c["severity"] == "praise"]
    if praise:
        L += ["", "**Done well:** " + "; ".join(c.get("title", "") for c in praise)]
    L.append("")
    L.append("**Full interactive review** (diff with inline comments, reasoning, alternatives, references): [%s](%s)"
             % (os.path.basename(report_path), file_url(report_path)))
    L.append("Path: `%s`" % os.path.abspath(report_path))
    return "\n".join(L) + "\n"
