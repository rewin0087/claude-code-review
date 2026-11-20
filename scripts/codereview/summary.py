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


REQ_ORDER = ["met", "partial", "missing", "contradicted", "unclear", "not_applicable"]


def _requirements_lines(req):
    items = req.get("items") or []
    if not items:
        return []
    counts = {}
    for it in items:
        counts[it.get("status")] = counts.get(it.get("status"), 0) + 1
    L = ["", "**Requirements:** %d/%d met%s" % (
        counts.get("met", 0), len(items),
        "".join(" · %d %s" % (counts[s], s.replace("_", " ")) for s in REQ_ORDER[1:] if counts.get(s)))]
    for it in items:
        if it.get("status") in ("partial", "missing", "contradicted", "unclear"):
            L.append("- %s **%s**: %s" % (it.get("id", ""), it["status"], first_sentence(it.get("text"), 160)))
    return L


def _impact_lines(impact, limit=6):
    L = []
    breaking = impact.get("breaking_changes") or []
    if breaking:
        L += ["", "**Breaking changes:**"] + ["- %s" % first_sentence(b, 200) for b in breaking[:limit]]
    caveats = (impact.get("caveats") or []) + (impact.get("considerations") or [])
    if caveats:
        L += ["", "**Caveats and things to consider:**"] + ["- %s" % first_sentence(c, 200) for c in caveats[:limit]]
        if len(caveats) > limit:
            L.append("- … %d more in the report" % (len(caveats) - limit))
    return L


def _checks_lines(checks, scan):
    L = []
    if scan:
        on = [f for f in scan.get("findings", []) if f.get("on_change")]
        ran = [t["tool"] for t in scan.get("tools", []) if t["status"] == "ran"]
        missing = [t["tool"] for t in scan.get("tools", []) if t["status"] == "missing"]
        sev = {}
        for f in on:
            sev[f["severity"]] = sev.get(f["severity"], 0) + 1
        L += ["", "**Automated checks** (%s): %s on the change%s" % (
            ", ".join(ran) or "none ran",
            ", ".join("%d %s" % (sev[k], k) for k in ("high", "medium", "low", "info") if sev.get(k)) or "no findings",
            ("; not installed: " + ", ".join(missing)) if missing else "")]
    for ch in checks:
        L.append("- %s **%s** — %s: %s" % ({"pass": "✓", "warn": "!", "fail": "✗"}.get(ch.get("status"), "·"),
                                          ch.get("name", ""), ch.get("status", ""), first_sentence(ch.get("result"), 180)))
    return L


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
    L += _requirements_lines(summary.get("requirements") or {})
    L += _impact_lines(summary.get("impact") or {})
    L += _checks_lines(summary.get("checks") or [], meta.get("scan"))
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
