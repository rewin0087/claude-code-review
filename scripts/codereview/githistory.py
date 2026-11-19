"""Git history for the code under review: who introduced it, in which commit, and why."""
import re

from .gitcmd import git

REF_RE = re.compile(r"(?:(?<![\w/])#\d+|![\d]+|\b[A-Z][A-Z0-9]{1,9}-\d+\b|https?://\S+/(?:pull|merge_requests|issues)/\d+)")
NOTABLE_RE = re.compile(r"\b(fix(e[sd])?|bug|revert|hotfix|workaround|regression|security|cve|race|deadlock|"
                        r"leak|perf(ormance)?|rollback|incident|outage|patch|hack|temporar(y|ily))\b", re.I)
SEP = "\x1e"
BLAME_HEADER_RE = re.compile(r"^([0-9a-f]{40}) \d+ (\d+)")


def ranges(nums, pad=0):
    """Group line numbers into [start, end] ranges, optionally padded."""
    out = []
    for n in sorted(set(nums)):
        s, e = max(1, n - pad), n + pad
        if out and s <= out[-1][1] + 1:
            out[-1][1] = max(out[-1][1], e)
        else:
            out.append([s, e])
    return out


def blame(repo, rev, path, start, end):
    """[(line_no, sha)] for the range at rev (rev=None: the working-tree file)."""
    txt = git(["blame", "--line-porcelain", "-w", "-M", "-C", "-L", "%d,%d" % (start, end)] +
              ([rev] if rev else []) + ["--", path], repo, check=False)
    res, sha, final = [], None, None
    for ln in txt.split("\n"):
        m = BLAME_HEADER_RE.match(ln)
        if m:
            sha, final = m.group(1), int(m.group(2))
        elif ln.startswith("\t") and sha:
            res.append((final, sha))
            sha = None
    return res


def commit_info(repo, sha, body_len):
    fmt = SEP.join(["%H", "%h", "%an", "%ad", "%s", "%b"])
    out = git(["show", "-s", "--date=short", "--format=" + fmt, sha], repo, check=False)
    if not out:
        return None
    p = out.split(SEP)
    body = p[5].strip()
    text = p[4] + "\n" + body
    return {"sha": p[0], "short": p[1], "author": p[2], "date": p[3], "subject": p[4],
            "body": body[:body_len] + ("…" if len(body) > body_len else ""),
            "refs": sorted(set(REF_RE.findall(text))),
            "notable": bool(NOTABLE_RE.search(text))}


class _CommitCache:
    def __init__(self, repo, body_len):
        self.repo, self.body_len, self.commits = repo, body_len, {}

    def remember(self, sha):
        if sha not in self.commits and not sha.startswith("0000000"):
            info = commit_info(self.repo, sha, self.body_len)
            if info:
                self.commits[sha] = info
        return sha in self.commits


def _blame_lines(repo, cache, rev, path, line_nos, removed):
    blamed = []
    for s, e in ranges(line_nos):
        by_sha = {}
        for line_no, sha in blame(repo, rev, path, s, e):
            if cache.remember(sha):
                by_sha.setdefault(sha, []).append(line_no)
        for sha, lines in by_sha.items():
            for rs, re_ in ranges(lines):
                blamed.append({"old_start": rs, "old_end": re_, "sha": sha,
                               "removed": removed is True or any(rs <= n <= re_ for n in removed)})
    return sorted(blamed, key=lambda b: b["old_start"])


def _recent(repo, cache, rev, path, recent):
    log = git(["log", "--follow", "-n", str(recent), "--format=%H", rev, "--", path], repo, check=False).split()
    return [sha for sha in log if cache.remember(sha)]


def collect_history(diff, recent=8, deep=False):
    """-> {"base", "files": {path: {old_path, blame, recent[, snapshot]}}, "commits": {sha: info}}"""
    meta = diff["meta"]
    repo = meta["repo_path"]
    base_rev = meta.get("merge_base") or meta["head"]
    snap_rev = None if meta.get("worktree") else meta["head"]
    cache = _CommitCache(repo, 1500 if deep else 400)
    files_out = {}
    for f in diff["files"]:
        if f["status"] == "added" or f["generated"] or f["binary"]:
            continue
        old = f["old_path"]
        if f["status"] == "snapshot":
            # existing code reviewed as-is: blame the selected lines of the current file
            sel = [l["n"] for h in f["hunks"] for l in h["lines"] if l.get("s")] or \
                  [l["n"] for h in f["hunks"] for l in h["lines"]]
            files_out[f["path"]] = {"old_path": old, "blame": _blame_lines(repo, cache, snap_rev, old, sel, True),
                                    "recent": _recent(repo, cache, meta["head"], old, recent), "snapshot": True}
            continue
        # lines of the BASE version this branch removes, plus (deep) surrounding context
        removed = [l["o"] for h in f["hunks"] for l in h["lines"] if l["t"] == "del"]
        context = [l["o"] for h in f["hunks"] for l in h["lines"] if l["t"] == "ctx"] if deep else []
        files_out[f["path"]] = {"old_path": old,
                                "blame": _blame_lines(repo, cache, base_rev, old, removed + context, removed),
                                "recent": _recent(repo, cache, base_rev, old, recent)}
    return {"base": base_rev, "files": files_out, "commits": cache.commits}


def format_digest(history, meta, history_path):
    """Human-readable digest the reviewer reads."""
    files_out, commits, base_rev = history["files"], history["commits"], history["base"]
    L = ["History as of %s %s (%d files, %d commits)" % (
        "merge-base" if meta.get("merge_base") else "HEAD", base_rev[:10], len(files_out), len(commits))]
    if not files_out:
        L.append("Branch only ADDS files - no prior history for the changed code.")
    for path, info in files_out.items():
        L.append("\n## %s%s" % (path, "  (was %s)" % info["old_path"] if info["old_path"] != path else ""))
        removed_blame = [b for b in info["blame"] if b["removed"]]
        if removed_blame:
            L.append("  Selected lines were last changed by:" if info.get("snapshot")
                     else "  Lines this branch removes/rewrites were introduced by:")
            for b in removed_blame:
                c = commits[b["sha"]]
                L.append("    old L%d-%d  %s %s  %s%s%s" % (b["old_start"], b["old_end"], c["short"], c["date"], c["subject"],
                                                       "  [%s]" % ", ".join(c["refs"]) if c["refs"] else "",
                                                       "  <- NOTABLE" if c["notable"] else ""))
        if info["recent"]:
            L.append("  Recent commits on this file:")
            for sha in info["recent"]:
                c = commits[sha]
                L.append("    %s %s  %s%s" % (c["short"], c["date"], c["subject"], "  <- NOTABLE" if c["notable"] else ""))
    notable = [c for c in commits.values() if c["notable"] and c["body"]]
    if notable:
        L.append("\n## Messages of notable commits (fixes / reverts / workarounds)")
        for c in notable:
            L.append("\n%s %s\n%s" % (c["short"], c["subject"], re.sub(r"(?m)^", "    ", c["body"])))
    L.append("\nHISTORY_JSON=%s" % history_path)
    return "\n".join(L)
