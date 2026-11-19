#!/usr/bin/env python3
"""Merge diff.json + review.json into a self-contained interactive HTML report.

Usage: render.py --dir <OUT_DIR> [--no-open] [--out report.html]
"""
import argparse
import json
import os
import re
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
TEMPLATE = os.path.join(HERE, "..", "templates", "report.html")

SEVERITIES = ["critical", "major", "minor", "suggestion", "nitpick", "praise"]
VERDICTS = ["approve", "approve_with_suggestions", "request_changes"]


def fail(msg):
    sys.exit("render.py: " + msg)


def load_json(path, what):
    try:
        with open(path) as fh:
            return json.load(fh)
    except FileNotFoundError:
        fail("%s not found: %s" % (what, path))
    except json.JSONDecodeError as e:
        fail("%s is not valid JSON (%s line %d col %d): %s" % (what, path, e.lineno, e.colno, e.msg))


def validate(diff, review):
    errors, warnings = [], []
    files = {f["path"]: f for f in diff["files"]}
    summary = review.get("summary")
    if not isinstance(summary, dict):
        errors.append("summary must be an object")
    elif summary.get("verdict") not in VERDICTS:
        errors.append("summary.verdict must be one of %s" % VERDICTS)
    comments = review.get("comments")
    if not isinstance(comments, list):
        errors.append("comments must be an array")
        comments = []
    seen = set()
    for i, c in enumerate(comments):
        where = "comments[%d]" % i
        c.setdefault("id", "c%d" % (i + 1))
        if c["id"] in seen:
            c["id"] = "%s_%d" % (c["id"], i)
        seen.add(c["id"])
        if c.get("severity") not in SEVERITIES:
            errors.append("%s.severity must be one of %s" % (where, SEVERITIES))
        if not c.get("title"):
            errors.append("%s.title is required" % where)
        path = c.get("file")
        if path not in files:
            # tolerate leading ./ or a/ b/ prefixes
            alt = re.sub(r"^(\./|[ab]/)", "", path or "")
            if alt in files:
                c["file"] = path = alt
            else:
                errors.append("%s.file '%s' is not a file in the diff" % (where, path))
                continue
        side = c.get("side") or "new"
        if side not in ("new", "old"):
            errors.append("%s.side must be 'new' or 'old'" % where)
            continue
        c["side"] = side
        line = c.get("line")
        if line is None:
            continue
        key = "n" if side == "new" else "o"
        present = {l[key] for h in files[path]["hunks"] for l in h["lines"] if l.get(key)}
        if line not in present:
            # common mistake: right line, wrong side
            other = "o" if key == "n" else "n"
            other_present = {l[other] for h in files[path]["hunks"] for l in h["lines"] if l.get(other)}
            warnings.append("%s (%s:%s side=%s) is not on a diff line%s; shown as file-level comment"
                            % (where, path, line, side,
                               " (it exists on the other side)" if line in other_present else ""))
            c["_unanchored"] = True
    return errors, warnings


def remote_web_url(remote):
    """git@github.com:me/repo.git | https://gitlab.com/g/repo.git -> https://host/path"""
    if not remote:
        return None
    m = re.match(r"^(?:git@|ssh://git@)([^:/]+)[:/](.+?)(?:\.git)?/?$", remote) or \
        re.match(r"^https?://(?:[^@/]+@)?([^/]+)/(.+?)(?:\.git)?/?$", remote)
    return "https://%s/%s" % (m.group(1), m.group(2)) if m else None


def resolve_history(diff, review):
    """Verify every cited commit exists; fill in short sha / date / subject."""
    repo = diff["meta"].get("repo_path")
    warnings, cache = [], {}

    def resolve(entry, where):
        sha = str(entry.get("sha") or "").strip()
        if sha not in cache:
            out = ""
            if repo and re.match(r"^[0-9a-fA-F]{4,40}$", sha):
                r = subprocess.run(["git", "-C", repo, "show", "-s", "--date=short",
                                    "--format=%H%x1f%h%x1f%ad%x1f%s", sha + "^{commit}"],
                                   capture_output=True, text=True, errors="replace")
                out = r.stdout.strip() if r.returncode == 0 else ""
            cache[sha] = out.split("\x1f") if out else None
        info = cache[sha]
        if not info:
            entry["_missing"] = True
            warnings.append("%s cites commit '%s' which does not exist in the repo" % (where, sha))
            return
        entry["sha"], entry["short"] = info[0], info[1]
        entry.setdefault("date", info[2])
        entry.setdefault("subject", info[3])

    hist = (review.get("summary") or {}).get("history") or {}
    for i, t in enumerate(hist.get("timeline") or []):
        resolve(t, "summary.history.timeline[%d]" % i)
    for i, c in enumerate(review.get("comments") or []):
        for j, h in enumerate(c.get("history") or []):
            resolve(h, "comments[%d].history[%d]" % (i, j))
    return warnings


def open_file(path):
    try:
        if sys.platform == "darwin":
            subprocess.Popen(["open", path])
        elif sys.platform.startswith("win"):
            os.startfile(path)  # noqa
        else:
            subprocess.Popen(["xdg-open", path], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    except Exception as e:  # opening is best-effort
        print("Could not open browser automatically: %s" % e)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dir", required=True, help="OUT_DIR printed by collect_diff.py")
    ap.add_argument("--out", help="output HTML path (default <dir>/report.html)")
    ap.add_argument("--no-open", action="store_true")
    a = ap.parse_args()

    diff = load_json(os.path.join(a.dir, "diff.json"), "diff.json")
    review = load_json(os.path.join(a.dir, "review.json"), "review.json")
    errors, warnings = validate(diff, review)
    warnings += resolve_history(diff, review)
    diff["meta"]["web_url"] = remote_web_url(diff["meta"].get("remote_url"))
    for w in warnings:
        print("WARNING: " + w)
    if errors:
        print("review.json has %d error(s):" % len(errors))
        for e in errors:
            print("  - " + e)
        sys.exit(1)

    with open(TEMPLATE) as fh:
        html = fh.read()
    payload = json.dumps({"meta": diff["meta"], "files": diff["files"], "review": review})
    # make the JSON safe to embed inside <script>
    payload = payload.replace("<", "\\u003c").replace("\u2028", "\\u2028").replace("\u2029", "\\u2029")
    if "__REVIEW_DATA__" not in html:
        fail("template is missing the __REVIEW_DATA__ placeholder")
    html = html.replace("__REVIEW_DATA__", payload, 1)
    title = "Review: %s → %s" % (diff["meta"]["branch"], diff["meta"]["base"])
    html = html.replace("__TITLE__", title.replace("&", "&amp;").replace("<", "&lt;"), 1)

    out = a.out or os.path.join(a.dir, "report.html")
    with open(out, "w") as fh:
        fh.write(html)

    counts = {}
    for c in review.get("comments", []):
        counts[c["severity"]] = counts.get(c["severity"], 0) + 1
    print("Verdict: %s" % review["summary"]["verdict"])
    print("Comments: " + ", ".join("%s %d" % (s, counts[s]) for s in SEVERITIES if s in counts))
    print("REPORT=%s" % os.path.abspath(out))
    if not a.no_open:
        open_file(os.path.abspath(out))


if __name__ == "__main__":
    main()
