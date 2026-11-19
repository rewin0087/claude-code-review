#!/usr/bin/env python3
"""Collect git history for the code a branch changes, to explain WHY it was written that way.

For every modified / deleted / renamed file in diff.json it records, as of the merge-base
(i.e. before this branch):
  - who/what last touched each line this branch removes or edits (git blame on the base)
  - the most recent commits that touched the file (git log --follow)
  - issue / PR / ticket references found in those commit messages
  - commits whose subject looks like a fix, revert, hotfix or workaround (often the reason
    "odd-looking" code exists)

Writes <OUT_DIR>/history.json and prints a compact digest for the reviewer to read.

Usage: history.py --dir <OUT_DIR> [--recent 8] [--deep]
  --deep  also blame the context lines around each change and keep longer commit bodies
"""
import argparse
import json
import os
import re
import subprocess
import sys

REF_RE = re.compile(r"(?:(?<![\w/])#\d+|![\d]+|\b[A-Z][A-Z0-9]{1,9}-\d+\b|https?://\S+/(?:pull|merge_requests|issues)/\d+)")
NOTABLE_RE = re.compile(r"\b(fix(e[sd])?|bug|revert|hotfix|workaround|regression|security|cve|race|deadlock|"
                        r"leak|perf(ormance)?|rollback|incident|outage|patch|hack|temporar(y|ily))\b", re.I)
SEP = "\x1e"


def git(args, cwd, check=False):
    r = subprocess.run(["git", "-c", "core.quotepath=off"] + args, cwd=cwd, capture_output=True,
                       text=True, errors="replace")
    if check and r.returncode != 0:
        sys.exit("git %s failed: %s" % (" ".join(args), r.stderr.strip()))
    return r.stdout if r.returncode == 0 else ""


def ranges(nums, pad=0):
    """Group sorted line numbers into (start, end) ranges, optionally padded."""
    out = []
    for n in sorted(set(nums)):
        s, e = max(1, n - pad), n + pad
        if out and s <= out[-1][1] + 1:
            out[-1][1] = max(out[-1][1], e)
        else:
            out.append([s, e])
    return out


def blame(repo, rev, path, start, end):
    """Return list of (line_no, sha) for the range at rev."""
    txt = git(["blame", "--line-porcelain", "-w", "-M", "-C", "-L", "%d,%d" % (start, end), rev, "--", path], repo)
    res, sha, final = [], None, None
    for ln in txt.split("\n"):
        m = re.match(r"^([0-9a-f]{40}) \d+ (\d+)", ln)
        if m:
            sha, final = m.group(1), int(m.group(2))
        elif ln.startswith("\t") and sha:
            res.append((final, sha))
            sha = None
    return res


def commit_info(repo, sha, body_len):
    fmt = SEP.join(["%H", "%h", "%an", "%ad", "%s", "%b"])
    out = git(["show", "-s", "--date=short", "--format=" + fmt, sha], repo)
    if not out:
        return None
    p = out.split(SEP)
    body = p[5].strip()
    text = p[4] + "\n" + body
    return {"sha": p[0], "short": p[1], "author": p[2], "date": p[3], "subject": p[4],
            "body": body[:body_len] + ("…" if len(body) > body_len else ""),
            "refs": sorted(set(REF_RE.findall(text))),
            "notable": bool(NOTABLE_RE.search(text))}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dir", required=True)
    ap.add_argument("--recent", type=int, default=8, help="recent commits per file")
    ap.add_argument("--deep", action="store_true")
    a = ap.parse_args()

    diff = json.load(open(os.path.join(a.dir, "diff.json")))
    meta = diff["meta"]
    repo, base_rev = meta["repo_path"], meta["merge_base"]
    body_len = 1500 if a.deep else 400
    commits, files_out = {}, {}

    def remember(sha):
        if sha not in commits and not sha.startswith("0000000"):
            info = commit_info(repo, sha, body_len)
            if info:
                commits[sha] = info
        return sha in commits

    for f in diff["files"]:
        if f["status"] == "added" or f["generated"] or f["binary"]:
            continue
        old = f["old_path"]
        # lines of the BASE version that this branch removes, plus (deep) surrounding context
        removed = [l["o"] for h in f["hunks"] for l in h["lines"] if l["t"] == "del"]
        context = [l["o"] for h in f["hunks"] for l in h["lines"] if l["t"] == "ctx"] if a.deep else []
        blamed = []
        for s, e in ranges(removed + context):
            by_sha = {}
            for line_no, sha in blame(repo, base_rev, old, s, e):
                if remember(sha):
                    by_sha.setdefault(sha, []).append(line_no)
            for sha, lines in by_sha.items():
                for rs, re_ in ranges(lines):
                    blamed.append({"old_start": rs, "old_end": re_, "sha": sha,
                                   "removed": any(rs <= n <= re_ for n in removed)})
        log = git(["log", "--follow", "-n", str(a.recent), "--format=%H", base_rev, "--", old], repo).split()
        recent = [sha for sha in log if remember(sha)]
        files_out[f["path"]] = {"old_path": old, "blame": sorted(blamed, key=lambda b: b["old_start"]),
                                "recent": recent}

    with open(os.path.join(a.dir, "history.json"), "w") as fh:
        json.dump({"base": base_rev, "files": files_out, "commits": commits}, fh, indent=1)

    # ---- digest for the reviewer ----
    print("History as of merge-base %s (%d files, %d commits)" % (base_rev[:10], len(files_out), len(commits)))
    if not files_out:
        print("Branch only ADDS files - no prior history for the changed code.")
    for path, info in files_out.items():
        print("\n## %s%s" % (path, "  (was %s)" % info["old_path"] if info["old_path"] != path else ""))
        removed_blame = [b for b in info["blame"] if b["removed"]]
        if removed_blame:
            print("  Lines this branch removes/rewrites were introduced by:")
            for b in removed_blame:
                c = commits[b["sha"]]
                print("    old L%d-%d  %s %s  %s%s%s" % (b["old_start"], b["old_end"], c["short"], c["date"], c["subject"],
                                                   "  [%s]" % ", ".join(c["refs"]) if c["refs"] else "",
                                                   "  <- NOTABLE" if c["notable"] else ""))
        if info["recent"]:
            print("  Recent commits on this file:")
            for sha in info["recent"]:
                c = commits[sha]
                print("    %s %s  %s%s" % (c["short"], c["date"], c["subject"], "  <- NOTABLE" if c["notable"] else ""))
    notable = [c for c in commits.values() if c["notable"] and c["body"]]
    if notable:
        print("\n## Messages of notable commits (fixes / reverts / workarounds)")
        for c in notable:
            print("\n%s %s\n%s" % (c["short"], c["subject"], re.sub(r"(?m)^", "    ", c["body"])))
    print("\nHISTORY_JSON=%s" % os.path.join(a.dir, "history.json"))


if __name__ == "__main__":
    main()
