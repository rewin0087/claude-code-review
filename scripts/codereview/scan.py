"""Automated checks on the code under review: a built-in secret detector plus whichever
security / dependency scanners are installed (semgrep, bandit, npm audit, pip-audit).

Only files in the review are scanned, and every finding is tagged with whether it sits on a
changed (or selected) line, so the reviewer can separate what this change introduced from
what was already there. Scanners that aren't installed are reported as "missing", never
installed automatically.
"""
import json
import os
import re
import shutil
import subprocess
import time

from .gitcmd import git_bytes

SEVERITY_ORDER = ["high", "medium", "low", "info"]
NEAR = 2   # a finding within this many lines of a changed line counts as "on the change"


# ---------------------------------------------------------------- what to scan

def changed_lines(f):
    """New-side line numbers this review is about: added lines, or selected lines when as-is."""
    if f["status"] == "snapshot":
        return {l["n"] for h in f["hunks"] for l in h["lines"] if l.get("s")} or \
               {l["n"] for h in f["hunks"] for l in h["lines"]}
    return {l["n"] for h in f["hunks"] for l in h["lines"] if l["t"] == "add"}


def scan_targets(diff):
    """{path: set(changed lines)} for text files that exist after the change."""
    out = {}
    for f in diff["files"]:
        if f["status"] == "deleted" or f["binary"]:
            continue
        out[f["path"]] = changed_lines(f)
    return out


def source_root(meta, paths, work_dir):
    """Directory holding the files as reviewed. The working tree when it matches the review,
    otherwise copies taken from the reviewed commit (so line numbers line up)."""
    repo = meta["repo_path"]
    if meta.get("worktree") and meta.get("uncommitted"):
        return repo
    root = os.path.join(work_dir, "scan-src")
    if os.path.isdir(root):
        shutil.rmtree(root)
    for p in paths:
        data = git_bytes(["show", "%s:%s" % (meta["head"], p)], repo)
        if data is None:
            continue
        dest = os.path.join(root, p)
        os.makedirs(os.path.dirname(dest), exist_ok=True)
        with open(dest, "wb") as fh:
            fh.write(data)
    return root


# ---------------------------------------------------------------- built-in secret detector

SECRET_PATTERNS = [
    ("private-key", "high", r"-----BEGIN (?:RSA |EC |DSA |OPENSSH |PGP |ENCRYPTED )?PRIVATE KEY-----"),
    ("aws-access-key-id", "high", r"\b(?:AKIA|ASIA)[0-9A-Z]{16}\b"),
    ("github-token", "high", r"\bgh[pousr]_[A-Za-z0-9]{36,}\b|\bgithub_pat_[A-Za-z0-9_]{60,}\b"),
    ("gitlab-token", "high", r"\bglpat-[A-Za-z0-9_\-]{20,}\b"),
    ("slack-token", "high", r"\bxox[abprs]-[A-Za-z0-9-]{10,}\b"),
    ("stripe-live-key", "high", r"\b[sr]k_live_[A-Za-z0-9]{20,}\b"),
    ("google-api-key", "high", r"\bAIza[0-9A-Za-z\-_]{35}\b"),
    ("anthropic-api-key", "high", r"\bsk-ant-[A-Za-z0-9_\-]{20,}\b"),
    ("openai-api-key", "high", r"\bsk-(?:proj-)?[A-Za-z0-9]{32,}\b"),
    ("jwt", "medium", r"\beyJ[A-Za-z0-9_-]{10,}\.eyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\b"),
    ("hardcoded-credential", "medium",
     r"""(?i)(?<![a-z])(?:password|passwd|pwd|secret|api[_-]?key|access[_-]?token|auth[_-]?token|client[_-]?secret)(?![a-z])"""
     r"""\s*[:=]\s*(['"])(?P<val>[^'"\s]{8,})\1"""),
]
PLACEHOLDER_RE = re.compile(r"(?i)(example|changeme|change_me|placeholder|dummy|your[_-]|xxx+|\*\*\*|<.*>|\$\{|%\(|"
                            r"env|test|fake|sample|redacted)")


def _redact(s):
    s = s.strip()
    return (s[:4] + "…" + "*" * 6) if len(s) > 4 else "****"


def detect_secrets(root, targets):
    findings = []
    for path, lines in targets.items():
        full = os.path.join(root, path)
        try:
            with open(full, encoding="utf-8", errors="replace") as fh:
                content = fh.read().split("\n")
        except OSError:
            continue
        for n in sorted(lines):
            if n < 1 or n > len(content):
                continue
            text = content[n - 1]
            for rule, sev, pat in SECRET_PATTERNS:
                m = re.search(pat, text)
                if not m:
                    continue
                value = m.groupdict().get("val") or m.group(0)
                if rule == "hardcoded-credential" and PLACEHOLDER_RE.search(value):
                    continue
                findings.append({"tool": "secrets", "rule": rule, "severity": sev, "file": path, "line": n,
                                 "message": "Possible %s committed in source: %s" % (rule.replace("-", " "),
                                                                                    _redact(value))})
                break
    return findings


# ---------------------------------------------------------------- external scanners

def _run(cmd, cwd, timeout):
    t0 = time.time()
    try:
        r = subprocess.run(cmd, cwd=cwd, capture_output=True, text=True, errors="replace", timeout=timeout)
    except subprocess.TimeoutExpired:
        return None, "timeout", time.time() - t0
    return r, None, time.time() - t0


def _rel(path, root):
    p = os.path.relpath(os.path.realpath(os.path.join(root, path)), os.path.realpath(root))
    return p.replace(os.sep, "/")


def run_semgrep(root, targets, timeout):
    files = [p for p in targets if os.path.isfile(os.path.join(root, p))]
    if not files:
        return [], "skipped", "no files"
    r, err, _ = _run(["semgrep", "scan", "--json", "--quiet", "--metrics=off", "--config", "p/default"] + files,
                     root, timeout)
    if err:
        return [], err, ""
    try:
        data = json.loads(r.stdout or "{}")
    except ValueError:
        return [], "error", (r.stderr or "unparseable output").strip()[-300:]
    sev = {"ERROR": "high", "WARNING": "medium", "INFO": "low"}
    out = []
    for res in data.get("results", []):
        extra = res.get("extra", {})
        refs = (extra.get("metadata") or {}).get("references") or []
        out.append({"tool": "semgrep", "rule": res.get("check_id", ""), "severity": sev.get(extra.get("severity"), "low"),
                    "file": _rel(res.get("path", ""), root), "line": (res.get("start") or {}).get("line"),
                    "message": (extra.get("message") or "").strip(), "url": refs[0] if refs else None})
    errs = [e.get("message", "") for e in data.get("errors", []) if e.get("level") == "error"]
    return out, "ran" if not errs or out else "error", "; ".join(errs)[-300:]


def run_bandit(root, targets, timeout):
    files = [p for p in targets if p.endswith(".py") and os.path.isfile(os.path.join(root, p))]
    if not files:
        return [], "skipped", "no Python files"
    r, err, _ = _run(["bandit", "-f", "json", "-q"] + files, root, timeout)
    if err:
        return [], err, ""
    try:
        data = json.loads(r.stdout or "{}")
    except ValueError:
        return [], "error", (r.stderr or "unparseable output").strip()[-300:]
    sev = {"HIGH": "high", "MEDIUM": "medium", "LOW": "low"}
    return [{"tool": "bandit", "rule": "%s %s" % (x.get("test_id", ""), x.get("test_name", "")),
             "severity": sev.get(x.get("issue_severity"), "low"), "file": _rel(x.get("filename", ""), root),
             "line": x.get("line_number"), "message": x.get("issue_text", ""), "url": x.get("more_info")}
            for x in data.get("results", [])], "ran", ""


def _manifest_dirs(targets, names):
    return sorted({os.path.dirname(p) for p in targets if os.path.basename(p) in names})


def run_npm_audit(root, targets, timeout):
    dirs = _manifest_dirs(targets, {"package.json", "package-lock.json", "npm-shrinkwrap.json"})
    if not dirs:
        return [], "skipped", "no package.json / lockfile changes"
    out, notes = [], []
    for d in dirs:
        cwd = os.path.join(root, d)
        if not os.path.isfile(os.path.join(cwd, "package-lock.json")) and \
                not os.path.isfile(os.path.join(cwd, "npm-shrinkwrap.json")):
            notes.append("%s: no package-lock.json" % (d or "."))
            continue
        r, err, _ = _run(["npm", "audit", "--json", "--package-lock-only"], cwd, timeout)
        if err:
            notes.append("%s: %s" % (d or ".", err))
            continue
        try:
            data = json.loads(r.stdout or "{}")
        except ValueError:
            notes.append("%s: unparseable output" % (d or "."))
            continue
        if "error" in data:
            notes.append("%s: %s" % (d or ".", (data["error"] or {}).get("summary", "error")))
            continue
        manifest = os.path.join(d, "package.json") if d else "package.json"
        for name, v in (data.get("vulnerabilities") or {}).items():
            advisories = [x for x in v.get("via", []) if isinstance(x, dict)]
            title = advisories[0].get("title") if advisories else "via " + ", ".join(
                x for x in v.get("via", []) if isinstance(x, str))
            fix = v.get("fixAvailable")
            fix_txt = ("fix: %s@%s" % (fix.get("name"), fix.get("version"))) if isinstance(fix, dict) else \
                ("fix available" if fix else "no fix available")
            out.append({"tool": "npm-audit", "rule": name, "severity": {"critical": "high", "high": "high",
                        "moderate": "medium", "low": "low"}.get(v.get("severity"), "info"),
                        "file": manifest, "line": None, "package": name,
                        "message": "%s %s: %s (%s)" % (name, v.get("range", ""), title, fix_txt),
                        "url": advisories[0].get("url") if advisories else None})
    status = "ran" if out or len(notes) < len(dirs) else "error"
    return out, status, "; ".join(notes)


def run_pip_audit(root, targets, timeout):
    reqs = [p for p in targets if re.search(r"(^|/)requirements[^/]*\.txt$", p)]
    if not reqs:
        return [], "skipped", "no requirements*.txt changes"
    out, notes = [], []
    for req in reqs:
        r, err, _ = _run(["pip-audit", "-r", req, "-f", "json", "--progress-spinner", "off",
                          "--no-deps", "--disable-pip"], root, timeout)
        if err:
            notes.append("%s: %s" % (req, err))
            continue
        try:
            data = json.loads(r.stdout or "{}")
        except ValueError:
            notes.append("%s: %s" % (req, (r.stderr or "unparseable output").strip()[-200:]))
            continue
        deps = data.get("dependencies", data if isinstance(data, list) else [])
        for dep in deps:
            for v in dep.get("vulns", []):
                fixes = ", ".join(v.get("fix_versions") or []) or "no fix version"
                out.append({"tool": "pip-audit", "rule": v.get("id", ""), "severity": "high", "file": req,
                            "line": None, "package": dep.get("name"),
                            "message": "%s %s: %s (fix: %s)" % (dep.get("name"), dep.get("version"),
                                                                (v.get("description") or v.get("id", ""))[:200], fixes),
                            "url": "https://osv.dev/vulnerability/%s" % v.get("id") if v.get("id") else None})
    status = "ran" if out or len(notes) < len(reqs) else "error"
    return out, status, "; ".join(notes)


SCANNERS = [
    ("semgrep", "semgrep", run_semgrep),
    ("bandit", "bandit", run_bandit),
    ("npm-audit", "npm", run_npm_audit),
    ("pip-audit", "pip-audit", run_pip_audit),
]


# ---------------------------------------------------------------- orchestration

SECRETISH_RE = re.compile(r"(?i)password|passwd|secret|token|api[_ -]?key|credential|private key")
QUOTED_RE = re.compile(r"""(['"])([^'"]{4,})\1""")


def scrub(message):
    """Never repeat a secret value from a scanner message in the report."""
    if not message or not SECRETISH_RE.search(message):
        return message
    return QUOTED_RE.sub(lambda m: m.group(1) + _redact(m.group(2)) + m.group(1), message)


def added_text(diff):
    """{dir: lowercase text of added lines in that dir's dependency files} for dependency findings."""
    out = {}
    for f in diff["files"]:
        if f["status"] == "deleted":
            continue
        d = os.path.dirname(f["path"])
        text = "\n".join(l["c"] for h in f["hunks"] for l in h["lines"] if l["t"] == "add" or l.get("s"))
        out[d] = out.get(d, "") + "\n" + text.lower()
    return out


def _on_change(finding, targets, added):
    lines = targets.get(finding["file"])
    if not lines:
        return False
    if finding.get("line") is None:
        # dependency finding: only "on the change" if this package was added or changed here
        pkg = (finding.get("package") or "").lower()
        text = added.get(os.path.dirname(finding["file"]), "")
        return bool(pkg) and re.search(r"(?<![a-z0-9_.-])%s(?![a-z0-9_-])" % re.escape(pkg), text) is not None
    return any(abs(finding["line"] - n) <= NEAR for n in lines)


def run_scans(diff, work_dir, only=None, timeout=180):
    """-> {"tools": [...], "findings": [...]} for the files in the review."""
    meta = diff["meta"]
    targets = scan_targets(diff)
    root = source_root(meta, list(targets), work_dir)
    tools, findings = [], []

    t0 = time.time()
    found = detect_secrets(root, targets)
    tools.append({"tool": "secrets", "status": "ran", "note": "built-in", "findings": len(found),
                  "seconds": round(time.time() - t0, 2)})
    findings += found

    for name, binary, fn in SCANNERS:
        if only and name not in only:
            continue
        if not shutil.which(binary):
            tools.append({"tool": name, "status": "missing", "note": "%s not installed" % binary, "findings": 0})
            continue
        t0 = time.time()
        try:
            found, status, note = fn(root, targets, timeout)
        except Exception as e:      # a broken scanner must never break the review
            found, status, note = [], "error", str(e)[:300]
        found = [f for f in found if f["file"] in targets]
        tools.append({"tool": name, "status": status, "note": note, "findings": len(found),
                      "seconds": round(time.time() - t0, 2)})
        findings += found

    added = added_text(diff)
    for f in findings:
        f["message"] = scrub(f.get("message"))
        f["on_change"] = _on_change(f, targets, added)
    findings.sort(key=lambda f: (not f["on_change"], SEVERITY_ORDER.index(f["severity"]), f["file"], f.get("line") or 0))
    return {"tools": tools, "findings": findings, "scanned_files": sorted(targets),
            "source": "working tree" if root == meta["repo_path"] else "reviewed commit %s" % meta["head"][:10]}


def format_digest(result, path, limit=60):
    L = ["Automated checks on %d file(s) (%s)" % (len(result["scanned_files"]), result["source"])]
    for t in result["tools"]:
        L.append("  %-10s %-8s %3s finding(s)%s" % (t["tool"], t["status"], t["findings"],
                                                  ("  - " + t["note"]) if t.get("note") else ""))
    on = [f for f in result["findings"] if f["on_change"]]
    off = [f for f in result["findings"] if not f["on_change"]]
    if on:
        L.append("\nOn changed / selected lines (%d):" % len(on))
        for f in on[:limit]:
            L.append("  [%s] %s:%s  %s  %s%s" % (f["severity"], f["file"], f.get("line") or "-", f["tool"], f["rule"],
                                                ("\n      " + f["message"]) if f.get("message") else ""))
    if off:
        L.append("\nElsewhere in the reviewed files, pre-existing (%d): not introduced by this change" % len(off))
        for f in off[:15]:
            L.append("  [%s] %s:%s  %s  %s" % (f["severity"], f["file"], f.get("line") or "-", f["tool"], f["rule"]))
    if not result["findings"]:
        L.append("\nNo findings.")
    L.append("\nSCAN_JSON=%s" % path)
    return "\n".join(L)
