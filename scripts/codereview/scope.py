"""Review scopes: files, folders, globs and line ranges, plus "review as-is" snapshots.

A scope is {"spec": as typed, "path": repo-relative path or glob ("" = whole repo),
"start": first line or None, "end": last line or None}.
"""
import fnmatch
import os
import re

from .errors import ReviewError
from .gitcmd import git, git_bytes
from .languages import is_generated, language_for

MAX_SNAPSHOT_LINES = 1500     # per file, when reviewing code as-is
MAX_SNAPSHOT_FILES = 40
SCOPE_RE = re.compile(r"^(.*?)(?:(?::|#L)(\d+)(?:-L?(\d+))?)?$")


def is_glob(path):
    return any(ch in path for ch in "*?[")


def parse_scope(spec, repo, cwd):
    """'src/a.py', 'src/a.py:10', 'src/a.py:10-40', 'src/a.py#L10-L40', 'src/', 'src/**/*.ts'"""
    m = SCOPE_RE.match(spec.strip())
    path, start, end = m.group(1), m.group(2), m.group(3)
    if not is_glob(path):
        absolute = path if os.path.isabs(path) else os.path.join(cwd, path)
        path = os.path.relpath(os.path.realpath(absolute), os.path.realpath(repo))
        if path.startswith(".."):
            raise ReviewError("Path '%s' is outside the repository %s." % (spec, repo))
    path = "" if path == "." else path.replace(os.sep, "/")
    start = int(start) if start else None
    end = int(end) if end else start
    if start and end < start:
        start, end = end, start
    return {"spec": spec, "path": path, "start": start, "end": end}


def scope_match(path, sc):
    p = sc["path"]
    if not p:
        return True
    if is_glob(p):
        return fnmatch.fnmatch(path, p) or fnmatch.fnmatch(path, p.rstrip("/") + "/*")
    return path == p or path.startswith(p.rstrip("/") + "/")


def merge_spans(spans):
    out = []
    for s_, e_ in sorted(spans):
        if out and s_ <= out[-1][1] + 1:
            out[-1][1] = max(out[-1][1], e_)
        else:
            out.append([s_, e_])
    return out


def spans_for(scopes):
    """Line spans requested for one file, or None if any scope wants the whole file."""
    if any(not sc["start"] for sc in scopes):
        return None
    return [(sc["start"], sc["end"]) for sc in scopes]


# ---------------------------------------------------------------- narrowing a diff

def _hunk_overlaps(hunk, spans):
    ns = [l["n"] for l in hunk["lines"] if l.get("n")]
    return ns and any(min(ns) <= e_ and max(ns) >= s_ for s_, e_ in spans)


def narrow_file_to_spans(f, spans):
    """Keep hunks overlapping the spans and mark in-span lines with "s": 1.

    Returns True if the branch changed anything inside the spans (else the caller should
    review that range as-is). Mutates f.
    """
    f["hunks"] = [h for h in f["hunks"] if _hunk_overlaps(h, spans)]
    changed_in_span = False
    for h in f["hunks"]:
        pos = h["new_start"]          # new-file position; a deletion sits at the next line
        for l in h["lines"]:
            here = l["n"] if l.get("n") else pos
            inside = any(s_ <= here <= e_ for s_, e_ in spans)
            l["s"] = 1 if inside and l["t"] != "meta" else 0
            if inside and l["t"] in ("add", "del"):
                changed_in_span = True
            if l.get("n"):
                pos = l["n"] + 1
    if changed_in_span:
        f["additions"] = sum(1 for h in f["hunks"] for l in h["lines"] if l["t"] == "add")
        f["deletions"] = sum(1 for h in f["hunks"] for l in h["lines"] if l["t"] == "del")
    return changed_in_span


def split_diff_by_scope(files, scopes):
    """-> (changed files to review, {path: spans} of in-scope ranges with no changes)."""
    kept, need_snapshot = [], {}
    for f in files:
        matching = [sc for sc in scopes if scope_match(f["path"], sc)]
        if not matching:
            continue
        spans = spans_for(matching)
        if spans and not narrow_file_to_spans(f, spans):
            need_snapshot[f["path"]] = spans
            continue
        kept.append(f)
    return kept, need_snapshot


def unchanged_targets(listing, scopes, exclude):
    """{path: spans|None} for files matching the scopes that aren't in `exclude`."""
    out = {}
    for path in listing:
        if path in exclude:
            continue
        matching = [sc for sc in scopes if scope_match(path, sc)]
        if matching:
            out[path] = spans_for(matching)
    return out


def list_files(repo, head, worktree):
    if worktree:
        out = git(["ls-files", "--cached", "--others", "--exclude-standard"], repo)
    else:
        out = git(["ls-tree", "-r", "--name-only", head], repo)
    return [p for p in out.split("\n") if p]


# ---------------------------------------------------------------- snapshots (code as-is)

def read_source(repo, path, head, worktree):
    """File text; None if unreadable; False if binary."""
    if worktree:
        try:
            with open(os.path.join(repo, path), "rb") as fh:
                data = fh.read()
        except OSError:
            return None
    else:
        data = git_bytes(["show", "%s:%s" % (head, path)], repo)
        if data is None:
            return None
    if b"\0" in data[:8000]:
        return False
    return data.decode("utf-8", errors="replace")


def snapshot_file(path, text, spans, context):
    """A pseudo-diff of unchanged code (all context lines) so the report can show it."""
    lines = text.split("\n")
    if text.endswith("\n"):
        lines = lines[:-1]
    total = len(lines)
    selected = merge_spans([(max(1, s_), min(total, e_)) for s_, e_ in spans]) if spans else [[1, total]]
    shown = merge_spans([(max(1, s_ - context), min(total, e_ + context)) for s_, e_ in selected]) if spans else selected
    hunks, budget, truncated = [], MAX_SNAPSHOT_LINES, False
    for s_, e_ in shown:
        if budget <= 0:
            truncated = True
            break
        if e_ - s_ + 1 > budget:
            e_, truncated = s_ + budget - 1, True
        budget -= e_ - s_ + 1
        hl = [{"t": "ctx", "o": n, "n": n, "c": lines[n - 1],
               "s": 1 if any(a <= n <= b for a, b in selected) else 0} for n in range(s_, e_ + 1)]
        hunks.append({"header": "@@ lines %d-%d of %d (current code, reviewed as-is) @@" % (s_, e_, total),
                      "section": "", "old_start": s_, "new_start": s_, "lines": hl})
    return {"old_path": path, "new_path": path, "path": path, "status": "snapshot", "binary": False,
            "hunks": hunks, "additions": 0, "deletions": 0, "language": language_for(path),
            "generated": False, "truncated": truncated, "total_lines": total}


def build_snapshots(repo, head, worktree, targets, context):
    """-> (snapshot files, skipped descriptions)."""
    snaps, skipped = [], []
    for path, spans in sorted(targets.items()):
        if is_generated(path):
            skipped.append(path + " (generated)")
            continue
        if len(snaps) >= MAX_SNAPSHOT_FILES:
            skipped.append(path + " (file limit)")
            continue
        text = read_source(repo, path, head, worktree)
        if text is None or text is False:
            skipped.append(path + (" (binary)" if text is False else " (unreadable)"))
            continue
        snaps.append(snapshot_file(path, text, spans, context))
    return snaps, skipped
