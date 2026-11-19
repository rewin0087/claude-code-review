#!/usr/bin/env python3
"""Collect ONLY the changes introduced by the current branch.

Finds the fork point (merge-base) between HEAD and the base branch, then diffs
merge-base..HEAD so commits that landed on the base branch after you branched
off are NOT included. Writes:

  <repo>/.code-review/<branch>/diff.patch   raw unified diff
  <repo>/.code-review/<branch>/diff.json    parsed diff (used by the renderer)
  <repo>/.code-review/<branch>/meta.json    branch / base / commit info

Usage:
  collect_diff.py [--base BRANCH] [--uncommitted] [--context N] [--repo PATH]
"""
import argparse
import datetime
import fnmatch
import json
import os
import re
import subprocess
import sys

BASE_CANDIDATES = ["main", "master", "develop", "development", "dev", "trunk"]

GENERATED_PATTERNS = [
    r"(^|/)package-lock\.json$", r"(^|/)yarn\.lock$", r"(^|/)pnpm-lock\.yaml$",
    r"(^|/)Gemfile\.lock$", r"(^|/)Cargo\.lock$", r"(^|/)poetry\.lock$",
    r"(^|/)composer\.lock$", r"(^|/)go\.sum$", r"(^|/)Pipfile\.lock$",
    r"(^|/)uv\.lock$", r"(^|/)bun\.lockb?$", r"(^|/)mix\.lock$", r"(^|/)Podfile\.lock$",
    r"\.min\.(js|css)$", r"\.map$", r"(^|/)dist/", r"(^|/)build/", r"(^|/)vendor/",
    r"(^|/)node_modules/", r"\.snap$", r"\.pb\.go$", r"_pb2\.py$", r"\.generated\.",
    r"(^|/)db/schema\.rb$", r"(^|/)structure\.sql$",
]

LANG_BY_EXT = {
    "py": "python", "rb": "ruby", "rake": "ruby", "js": "javascript", "mjs": "javascript",
    "cjs": "javascript", "jsx": "javascript", "ts": "typescript", "tsx": "typescript",
    "vue": "xml", "svelte": "xml", "html": "xml", "htm": "xml", "xml": "xml", "erb": "erb",
    "css": "css", "scss": "scss", "sass": "scss", "less": "less", "go": "go", "rs": "rust",
    "java": "java", "kt": "kotlin", "kts": "kotlin", "scala": "scala", "swift": "swift",
    "m": "objectivec", "mm": "objectivec", "c": "c", "h": "c", "cc": "cpp", "cpp": "cpp",
    "cxx": "cpp", "hpp": "cpp", "cs": "csharp", "fs": "fsharp", "php": "php", "pl": "perl",
    "sh": "bash", "bash": "bash", "zsh": "bash", "ps1": "powershell", "sql": "sql",
    "json": "json", "yml": "yaml", "yaml": "yaml", "toml": "ini", "ini": "ini", "md": "markdown",
    "dart": "dart", "ex": "elixir", "exs": "elixir", "erl": "erlang", "hs": "haskell",
    "clj": "clojure", "lua": "lua", "r": "r", "jl": "julia", "tf": "hcl", "hcl": "hcl",
    "graphql": "graphql", "gql": "graphql", "proto": "protobuf", "gradle": "gradle",
    "groovy": "groovy", "dockerfile": "dockerfile", "makefile": "makefile", "cmake": "cmake",
}


def git(args, cwd, check=True):
    r = subprocess.run(["git", "-c", "core.quotepath=off"] + args, cwd=cwd,
                       capture_output=True, text=True, errors="replace")
    if check and r.returncode != 0:
        sys.exit("git %s failed:\n%s" % (" ".join(args), r.stderr.strip()))
    return r.stdout


def ref_exists(ref, cwd):
    return subprocess.run(["git", "rev-parse", "--verify", "--quiet", ref + "^{commit}"],
                          cwd=cwd, capture_output=True).returncode == 0


def detect_base(cwd, current, head="HEAD"):
    """Pick the candidate base whose merge-base is closest to HEAD."""
    candidates = []
    origin_head = git(["symbolic-ref", "--quiet", "refs/remotes/origin/HEAD"], cwd, check=False).strip()
    if origin_head:
        candidates.append(origin_head.replace("refs/remotes/", ""))
    for name in BASE_CANDIDATES:
        candidates += [name, "origin/" + name]
    best = None
    seen = set()
    for ref in candidates:
        if ref in seen or not ref_exists(ref, cwd):
            continue
        seen.add(ref)
        if ref == current or ref == "origin/" + current:
            continue
        mb = git(["merge-base", ref, head], cwd, check=False).strip()
        if not mb:
            continue
        ahead = int(git(["rev-list", "--count", mb + ".." + head], cwd).strip() or 0)
        if best is None or ahead < best[1]:
            best = (ref, ahead)
    return best[0] if best else None


def language_for(path):
    base = os.path.basename(path).lower()
    if base in ("dockerfile", "makefile", "gemfile", "rakefile"):
        return {"gemfile": "ruby", "rakefile": "ruby"}.get(base, base)
    ext = base.rsplit(".", 1)[-1] if "." in base else ""
    return LANG_BY_EXT.get(ext, "")


HUNK_RE = re.compile(r"^@@ -(\d+)(?:,(\d+))? \+(\d+)(?:,(\d+))? @@ ?(.*)$")


def strip_prefix(p):
    p = p.strip()
    if p.startswith('"') and p.endswith('"'):
        p = p[1:-1]
    if p == "/dev/null":
        return None
    return p[2:] if p[:2] in ("a/", "b/") else p


def parse_diff(text):
    files = []
    cur = None
    hunk = None
    old_no = new_no = 0
    for raw in text.split("\n"):
        if raw.startswith("diff --git "):
            m = re.match(r'^diff --git "?a/(.+?)"? "?b/(.+?)"?$', raw)
            cur = {"old_path": m.group(1) if m else None, "new_path": m.group(2) if m else None,
                   "status": "modified", "binary": False, "hunks": [], "additions": 0, "deletions": 0}
            files.append(cur)
            hunk = None
            continue
        if cur is None:
            continue
        if hunk is None:
            if raw.startswith("new file mode"):
                cur["status"] = "added"
            elif raw.startswith("deleted file mode"):
                cur["status"] = "deleted"
            elif raw.startswith("rename from "):
                cur["status"] = "renamed"; cur["old_path"] = raw[len("rename from "):]
            elif raw.startswith("rename to "):
                cur["new_path"] = raw[len("rename to "):]
            elif raw.startswith("Binary files ") or raw.startswith("GIT binary patch"):
                cur["binary"] = True
            elif raw.startswith("--- "):
                cur["old_path"] = strip_prefix(raw[4:]) or cur["old_path"]
                if strip_prefix(raw[4:]) is None:
                    cur["status"] = "added"
            elif raw.startswith("+++ "):
                cur["new_path"] = strip_prefix(raw[4:]) or cur["new_path"]
                if strip_prefix(raw[4:]) is None:
                    cur["status"] = "deleted"
        m = HUNK_RE.match(raw)
        if m:
            old_no, new_no = int(m.group(1)), int(m.group(3))
            hunk = {"header": raw, "section": m.group(5), "old_start": old_no,
                    "new_start": new_no, "lines": []}
            cur["hunks"].append(hunk)
            continue
        if hunk is None or raw == "":
            continue
        tag, content = raw[0], raw[1:]
        if tag == " ":
            hunk["lines"].append({"t": "ctx", "o": old_no, "n": new_no, "c": content})
            old_no += 1; new_no += 1
        elif tag == "+":
            hunk["lines"].append({"t": "add", "o": None, "n": new_no, "c": content})
            new_no += 1; cur["additions"] += 1
        elif tag == "-":
            hunk["lines"].append({"t": "del", "o": old_no, "n": None, "c": content})
            old_no += 1; cur["deletions"] += 1
        elif tag == "\\":
            hunk["lines"].append({"t": "meta", "o": None, "n": None, "c": raw})
    for f in files:
        f["path"] = f["new_path"] if f["status"] != "deleted" else f["old_path"]
        f["language"] = language_for(f["path"] or "")
        f["generated"] = any(re.search(p, f["path"] or "") for p in GENERATED_PATTERNS)
    return files


def ensure_ignored(repo):
    """Keep review output out of commits without touching the tracked .gitignore."""
    git_dir = git(["rev-parse", "--git-common-dir"], repo).strip()
    exclude = os.path.join(repo, git_dir, "info", "exclude") if not os.path.isabs(git_dir) \
        else os.path.join(git_dir, "info", "exclude")
    try:
        os.makedirs(os.path.dirname(exclude), exist_ok=True)
        existing = open(exclude).read() if os.path.exists(exclude) else ""
        if ".code-review/" not in existing.split("\n"):
            with open(exclude, "a") as fh:
                fh.write(("" if existing.endswith("\n") or not existing else "\n") + ".code-review/\n")
    except OSError:
        pass


MAX_SNAPSHOT_LINES = 1500     # per file, when reviewing code as-is
MAX_SNAPSHOT_FILES = 40
SCOPE_RE = re.compile(r"^(.*?)(?:(?::|#L)(\d+)(?:-L?(\d+))?)?$")


def parse_scope(spec, repo, cwd):
    """'src/a.py', 'src/a.py:10', 'src/a.py:10-40', 'src/a.py#L10-L40', 'src/', 'src/**/*.ts'"""
    m = SCOPE_RE.match(spec.strip())
    path, start, end = m.group(1), m.group(2), m.group(3)
    if not any(ch in path for ch in "*?["):
        absolute = path if os.path.isabs(path) else os.path.join(cwd, path)
        path = os.path.relpath(os.path.realpath(absolute), os.path.realpath(repo))
        if path.startswith(".."):
            sys.exit("Path '%s' is outside the repository %s." % (spec, repo))
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
    if any(ch in p for ch in "*?["):
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


def read_source(repo, path, head, worktree):
    if worktree:
        try:
            with open(os.path.join(repo, path), "rb") as fh:
                data = fh.read()
        except OSError:
            return None
    else:
        r = subprocess.run(["git", "show", "%s:%s" % (head, path)], cwd=repo, capture_output=True)
        if r.returncode != 0:
            return None
        data = r.stdout
    if b"\0" in data[:8000]:
        return False  # binary
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


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", help="base branch to compare against (auto-detected if omitted)")
    ap.add_argument("--uncommitted", action="store_true",
                    help="also include staged + unstaged changes in the working tree")
    ap.add_argument("--context", type=int, default=5, help="context lines around changes")
    ap.add_argument("--head", help="branch/ref to review without checking it out (default: current HEAD)")
    ap.add_argument("--path", action="append", default=[],
                    help="limit the review to a file, dir, glob or range: a.py, a.py:10-40, a.py#L10-L40, src/, '**/*.ts' "
                         "(repeatable; relative to the current directory or the repo root)")
    ap.add_argument("--mode", choices=["auto", "changes", "code"], default="auto",
                    help="auto: branch changes in scope, else the code as-is | changes: only branch changes | "
                         "code: review the scoped code as-is, ignore the diff")
    ap.add_argument("--repo", default=os.getcwd())
    a = ap.parse_args()

    repo = git(["rev-parse", "--show-toplevel"], a.repo, check=False).strip()
    if not repo:
        sys.exit("Not inside a git repository: %s" % a.repo)
    if a.head and a.uncommitted:
        sys.exit("--uncommitted only applies to the checked-out branch; drop --head or --uncommitted.")
    if a.mode == "code" and not a.path:
        sys.exit("--mode code needs at least one --path (file, range, dir or glob).")
    head = a.head or "HEAD"
    if a.head and not ref_exists(head, repo) and ref_exists("origin/" + head, repo):
        head = "origin/" + head
    if not ref_exists(head, repo):
        sys.exit("Branch/ref '%s' not found." % a.head)
    current = a.head or git(["rev-parse", "--abbrev-ref", "HEAD"], repo).strip()
    checked_out = not a.head or git(["rev-parse", head], repo) == git(["rev-parse", "HEAD"], repo)
    worktree = not a.head
    cwd = os.path.abspath(a.repo) if os.path.isdir(a.repo) else os.getcwd()
    scopes = [parse_scope(sp, repo, cwd) for sp in a.path]
    if scopes and worktree:
        a.uncommitted = True   # line numbers must match what the user sees in the editor

    base = a.base
    if base and not ref_exists(base, repo) and ref_exists("origin/" + base, repo):
        base = "origin/" + base
    if base and not ref_exists(base, repo):
        sys.exit("Base ref '%s' not found." % a.base)
    if not base and a.mode != "code":
        base = detect_base(repo, current, head)
    if not base and not scopes:
        if current in BASE_CANDIDATES:
            others = [b.strip().lstrip("* ") for b in git(["branch", "--format=%(refname:short)"], repo).split("\n")
                      if b.strip() and b.strip() != current]
            sys.exit("'%s' is checked out, which is itself a base branch, so there is nothing branch-specific to review.\n"
                     "Review a feature branch with --head <branch>%s, local work with --uncommitted, or specific "
                     "code with a path (e.g. src/app.py or src/app.py:10-40)."
                     % (current, (" (local branches: %s)" % ", ".join(others[:15])) if others else ""))
        sys.exit("Could not auto-detect a base branch. Re-run with --base <branch>.")

    merge_base, commits, patch, files = None, [], "", []
    if base:
        merge_base = git(["merge-base", base, head], repo).strip()
        commits_raw = git(["log", "--no-merges", "--format=%H%x1f%h%x1f%an%x1f%ad%x1f%s",
                           "--date=short", merge_base + ".." + head], repo)
        commits = [dict(zip(["sha", "short", "author", "date", "subject"], l.split("\x1f")))
                   for l in commits_raw.strip().split("\n") if l]
        diff_args = ["diff", "--no-color", "--find-renames", "-U%d" % a.context, merge_base]
        if not a.uncommitted:
            diff_args.append(head)
        patch = git(diff_args, repo)
        files = parse_diff(patch)

    if not scopes:
        if not patch.strip() and merge_base == git(["rev-parse", head], repo).strip():
            sys.exit("'%s' has no commits that aren't already in %s (it is fully merged). Nothing to review.\n"
                     "Tip: pass a path (file, file:10-40, dir) to review specific code as-is." % (current, base))
        if not patch.strip():
            sys.exit("No changes between %s (merge-base %s) and %s%s." % (
                base, merge_base[:10], current, " + working tree" if a.uncommitted else
                ". Tip: pass --uncommitted to review local, uncommitted work, or a path to review code as-is"))
        mode = "changes"
    else:
        # ---- narrow to the requested scope ----
        kept, need_snapshot = [], {}   # path -> list of spans (None = whole file)
        if a.mode != "code":
            for f in files:
                matching = [sc for sc in scopes if scope_match(f["path"], sc)]
                if not matching:
                    continue
                spans = [(sc["start"], sc["end"]) for sc in matching if sc["start"]]
                if spans and not any(not sc["start"] for sc in matching):
                    def overlaps(h):
                        ns = [l["n"] for l in h["lines"] if l.get("n")]
                        return ns and any(min(ns) <= e_ and max(ns) >= s_ for s_, e_ in spans)
                    f["hunks"] = [h for h in f["hunks"] if overlaps(h)]
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
                    if not changed_in_span:
                        need_snapshot[f["path"]] = spans      # range has no changes -> review as-is
                        continue
                    f["additions"] = sum(1 for h in f["hunks"] for l in h["lines"] if l["t"] == "add")
                    f["deletions"] = sum(1 for h in f["hunks"] for l in h["lines"] if l["t"] == "del")
                kept.append(f)
        if a.mode != "changes":
            listing = git(["ls-files", "--cached", "--others", "--exclude-standard"], repo) if worktree \
                else git(["ls-tree", "-r", "--name-only", head], repo)
            changed_paths = {f["path"] for f in kept}
            for path in [p for p in listing.split("\n") if p]:
                if path in changed_paths or path in need_snapshot:
                    continue
                matching = [sc for sc in scopes if scope_match(path, sc)]
                if not matching:
                    continue
                if any(not sc["start"] for sc in matching):
                    need_snapshot[path] = None
                else:
                    need_snapshot[path] = [(sc["start"], sc["end"]) for sc in matching]
        snaps, skipped = [], []
        for path, spans in sorted(need_snapshot.items()):
            if any(re.search(p, path) for p in GENERATED_PATTERNS):
                skipped.append(path + " (generated)")
                continue
            if len(snaps) >= MAX_SNAPSHOT_FILES:
                skipped.append(path + " (file limit)")
                continue
            text = read_source(repo, path, head, worktree)
            if text is None or text is False:
                skipped.append(path + (" (binary)" if text is False else " (unreadable)"))
                continue
            snaps.append(snapshot_file(path, text, spans, a.context))
        files = kept + snaps
        if not files:
            sys.exit("Nothing to review for scope %s%s." % (
                ", ".join(sc["spec"] for sc in scopes),
                " (no branch changes there; drop --changes-only to review the code as-is)" if a.mode == "changes" else
                " (no matching files)"))
        mode = "code" if not kept else ("changes" if not snaps else "mixed")
        if skipped:
            print("Skipped:     " + ", ".join(skipped[:20]) + (" …" if len(skipped) > 20 else ""))

    slug = re.sub(r"[^A-Za-z0-9._-]+", "-", current).strip("-") or "HEAD"
    if scopes:
        tag = re.sub(r"[^A-Za-z0-9]+", "-", "_".join(sc["spec"] for sc in scopes)).strip("-")[:40]
        slug += "__" + (tag or "scope")
    out_dir = os.path.join(repo, ".code-review", slug)
    os.makedirs(out_dir, exist_ok=True)
    ensure_ignored(repo)

    meta = {
        "repo": os.path.basename(repo), "repo_path": repo, "branch": current, "base": base,
        "merge_base": merge_base, "head": git(["rev-parse", head], repo).strip(), "head_ref": head,
        "checked_out": checked_out, "worktree": worktree,
        "uncommitted": a.uncommitted, "commits": commits, "mode": mode,
        "scope": [{k: sc[k] for k in ("spec", "path", "start", "end")} for sc in scopes],
        "generated_at": datetime.datetime.now().isoformat(timespec="seconds"),
        "remote_url": git(["config", "--get", "remote.origin.url"], repo, check=False).strip(),
        "stats": {"files": len(files), "additions": sum(f["additions"] for f in files),
                  "deletions": sum(f["deletions"] for f in files)},
    }
    with open(os.path.join(out_dir, "diff.patch"), "w") as fh:
        fh.write(patch)
    with open(os.path.join(out_dir, "diff.json"), "w") as fh:
        json.dump({"meta": meta, "files": files}, fh)
    with open(os.path.join(out_dir, "meta.json"), "w") as fh:
        json.dump(meta, fh, indent=2)

    reviewable = [f for f in files if not f["generated"] and not f["binary"]]
    changed = sum(f["additions"] + f["deletions"] for f in reviewable)
    snapshot_lines = sum(len(h["lines"]) for f in reviewable if f["status"] == "snapshot" for h in f["hunks"])
    print("Repo:        %s" % repo)
    print("Branch:      %s" % current)
    print("Base:        %s" % ("%s (merge-base %s)" % (base, merge_base[:10]) if base else "none (reviewing code as-is)"))
    if scopes:
        print("Scope:       %s" % ", ".join(sc["spec"] for sc in scopes))
    print("Mode:        %s%s" % (mode, {"changes": " - review the branch's changes",
                                       "code": " - no branch changes in scope; review the current code as-is",
                                       "mixed": " - branch changes where present, current code as-is elsewhere"}[mode]))
    print("Commits:     %d%s" % (len(commits), "  (+ uncommitted working tree)" if a.uncommitted and base else ""))
    for c in commits[:30]:
        print("  %s %s" % (c["short"], c["subject"]))
    print("Files:       %d  (+%d / -%d)" % (len(files), meta["stats"]["additions"], meta["stats"]["deletions"]))
    for f in files:
        flags = ",".join(x for x in [f["status"], "generated" if f["generated"] else "",
                                     "binary" if f["binary"] else "", "truncated" if f.get("truncated") else ""] if x)
        extra = ""
        if f["status"] == "snapshot":
            extra = " lines " + ",".join("%d-%d" % (h["new_start"], h["lines"][-1]["n"]) for h in f["hunks"])
        print("  %-60s +%-5d -%-5d %s %s%s" % (f["path"], f["additions"], f["deletions"], flags,
                                              f["language"], extra))
    print("Reviewable:  %d files, %d changed lines%s" % (
        len(reviewable), changed, ", %d lines of existing code" % snapshot_lines if snapshot_lines else ""))
    if changed + snapshot_lines > 1500 or len(reviewable) > 25:
        print("SIZE:        LARGE - split the review across subagents by file group.")
    print("OUT_DIR=%s" % out_dir)


if __name__ == "__main__":
    main()
