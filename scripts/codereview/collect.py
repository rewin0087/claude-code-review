"""Turn "what should be reviewed" options into the review input (meta + files)."""
import datetime
import json
import os
import re
from dataclasses import dataclass, field
from typing import List, Optional

from . import gitcmd
from .branch import detect_base, is_base_branch
from .diffparse import parse_diff
from .errors import ReviewError
from .scope import build_snapshots, list_files, parse_scope, split_diff_by_scope, unchanged_targets

MODES = ("auto", "changes", "code")
MODE_DESCRIPTIONS = {
    "changes": " - review the branch's changes",
    "code": " - no branch changes in scope; review the current code as-is",
    "mixed": " - branch changes where present, current code as-is elsewhere",
}
LARGE_LINES, LARGE_FILES = 1500, 25


@dataclass
class CollectOptions:
    repo: str
    base: Optional[str] = None
    head: Optional[str] = None
    uncommitted: bool = False
    context: int = 5
    paths: List[str] = field(default_factory=list)
    mode: str = "auto"


@dataclass
class Collection:
    repo: str
    meta: dict
    files: list
    patch: str
    scopes: list
    skipped: list


def _resolve_head(repo, opts):
    if not opts.head:
        return "HEAD"
    head = gitcmd.resolve_ref(opts.head, repo)
    if not head:
        raise ReviewError("Branch/ref '%s' not found." % opts.head)
    return head


def _resolve_base(repo, opts, current, head, scopes):
    if opts.base:
        base = gitcmd.resolve_ref(opts.base, repo)
        if not base:
            raise ReviewError("Base ref '%s' not found." % opts.base)
        return base
    base = detect_base(repo, current, head) if opts.mode != "code" else None
    if base or scopes:
        return base
    if is_base_branch(current):
        others = [b for b in gitcmd.local_branches(repo) if b != current]
        raise ReviewError(
            "'%s' is checked out, which is itself a base branch, so there is nothing branch-specific to review.\n"
            "Review a feature branch with --head <branch>%s, local work with --uncommitted, or specific "
            "code with a path (e.g. src/app.py or src/app.py:10-40)."
            % (current, (" (local branches: %s)" % ", ".join(others[:15])) if others else ""))
    raise ReviewError("Could not auto-detect a base branch. Re-run with --base <branch>.")


def _branch_commits(repo, merge_base, head):
    raw = gitcmd.git(["log", "--no-merges", "--format=%H%x1f%h%x1f%an%x1f%ad%x1f%s",
                      "--date=short", merge_base + ".." + head], repo)
    return [dict(zip(["sha", "short", "author", "date", "subject"], l.split("\x1f")))
            for l in raw.strip().split("\n") if l]


def _branch_diff(repo, merge_base, head, context, uncommitted):
    args = ["diff", "--no-color", "--find-renames", "-U%d" % context, merge_base]
    if not uncommitted:
        args.append(head)
    return gitcmd.git(args, repo)


def collect(opts):
    """Resolve refs and scope, compute the diff and/or snapshots. Raises ReviewError."""
    if opts.mode not in MODES:
        raise ReviewError("Unknown mode '%s'." % opts.mode)
    repo = gitcmd.repo_root(opts.repo)
    if not repo:
        raise ReviewError("Not inside a git repository: %s" % opts.repo)
    if opts.head and opts.uncommitted:
        raise ReviewError("--uncommitted only applies to the checked-out branch; drop --head or --uncommitted.")
    if opts.mode == "code" and not opts.paths:
        raise ReviewError("--mode code needs at least one --path (file, range, dir or glob).")

    head = _resolve_head(repo, opts)
    current = opts.head or gitcmd.current_branch(repo)
    checked_out = not opts.head or gitcmd.git(["rev-parse", head], repo) == gitcmd.git(["rev-parse", "HEAD"], repo)
    worktree = not opts.head
    cwd = os.path.abspath(opts.repo) if os.path.isdir(opts.repo) else os.getcwd()
    scopes = [parse_scope(sp, repo, cwd) for sp in opts.paths]
    # scoped reviews read the working tree so line numbers match the user's editor
    uncommitted = opts.uncommitted or bool(scopes and worktree)

    base = _resolve_base(repo, opts, current, head, scopes)
    merge_base, commits, patch, files = None, [], "", []
    if base:
        merge_base = gitcmd.git(["merge-base", base, head], repo).strip()
        commits = _branch_commits(repo, merge_base, head)
        patch = _branch_diff(repo, merge_base, head, opts.context, uncommitted)
        files = parse_diff(patch)

    skipped = []
    if not scopes:
        if not patch.strip() and merge_base == gitcmd.rev_parse(head, repo):
            raise ReviewError("'%s' has no commits that aren't already in %s (it is fully merged). Nothing to review.\n"
                              "Tip: pass a path (file, file:10-40, dir) to review specific code as-is." % (current, base))
        if not patch.strip():
            raise ReviewError("No changes between %s (merge-base %s) and %s%s." % (
                base, merge_base[:10], current, " + working tree" if uncommitted else
                ". Tip: pass --uncommitted to review local, uncommitted work, or a path to review code as-is"))
        mode = "changes"
    else:
        kept, need_snapshot = split_diff_by_scope(files, scopes) if opts.mode != "code" else ([], {})
        if opts.mode != "changes":
            exclude = {f["path"] for f in kept} | set(need_snapshot)
            need_snapshot.update(unchanged_targets(list_files(repo, head, worktree), scopes, exclude))
        snaps, skipped = build_snapshots(repo, head, worktree, need_snapshot, opts.context)
        files = kept + snaps
        if not files:
            raise ReviewError("Nothing to review for scope %s%s." % (
                ", ".join(sc["spec"] for sc in scopes),
                " (no branch changes there; drop --changes-only to review the code as-is)" if opts.mode == "changes"
                else " (no matching files)"))
        mode = "code" if not kept else ("changes" if not snaps else "mixed")

    meta = {
        "repo": os.path.basename(repo), "repo_path": repo, "branch": current, "base": base,
        "merge_base": merge_base, "head": gitcmd.rev_parse(head, repo), "head_ref": head,
        "checked_out": checked_out, "worktree": worktree,
        "uncommitted": uncommitted, "commits": commits, "mode": mode,
        "scope": [{k: sc[k] for k in ("spec", "path", "start", "end")} for sc in scopes],
        "generated_at": datetime.datetime.now().isoformat(timespec="seconds"),
        "remote_url": gitcmd.remote_url(repo),
        "stats": {"files": len(files), "additions": sum(f["additions"] for f in files),
                  "deletions": sum(f["deletions"] for f in files)},
    }
    return Collection(repo=repo, meta=meta, files=files, patch=patch, scopes=scopes, skipped=skipped)


def output_dir(repo, branch, scopes):
    """<repo>/.code-review/<branch>[__<scope>] — scoped runs don't overwrite the full review."""
    slug = re.sub(r"[^A-Za-z0-9._-]+", "-", branch).strip("-") or "HEAD"
    if scopes:
        tag = re.sub(r"[^A-Za-z0-9]+", "-", "_".join(sc["spec"] for sc in scopes)).strip("-")[:40]
        slug += "__" + (tag or "scope")
    return os.path.join(repo, ".code-review", slug)


def write_collection(c, out_dir):
    os.makedirs(out_dir, exist_ok=True)
    gitcmd.ensure_ignored(c.repo)
    with open(os.path.join(out_dir, "diff.patch"), "w") as fh:
        fh.write(c.patch)
    with open(os.path.join(out_dir, "diff.json"), "w") as fh:
        json.dump({"meta": c.meta, "files": c.files}, fh)
    with open(os.path.join(out_dir, "meta.json"), "w") as fh:
        json.dump(c.meta, fh, indent=2)


def format_report(c, out_dir):
    """The overview printed for the reviewer after collecting."""
    meta, files = c.meta, c.files
    reviewable = [f for f in files if not f["generated"] and not f["binary"]]
    changed = sum(f["additions"] + f["deletions"] for f in reviewable)
    snapshot_lines = sum(len(h["lines"]) for f in reviewable if f["status"] == "snapshot" for h in f["hunks"])
    L = []
    if c.skipped:
        L.append("Skipped:     " + ", ".join(c.skipped[:20]) + (" …" if len(c.skipped) > 20 else ""))
    L.append("Repo:        %s" % c.repo)
    L.append("Branch:      %s" % meta["branch"])
    L.append("Base:        %s" % ("%s (merge-base %s)" % (meta["base"], meta["merge_base"][:10]) if meta["base"]
                                  else "none (reviewing code as-is)"))
    if c.scopes:
        L.append("Scope:       %s" % ", ".join(sc["spec"] for sc in c.scopes))
    L.append("Mode:        %s%s" % (meta["mode"], MODE_DESCRIPTIONS[meta["mode"]]))
    L.append("Commits:     %d%s" % (len(meta["commits"]),
                                    "  (+ uncommitted working tree)" if meta["uncommitted"] and meta["base"] else ""))
    for cm in meta["commits"][:30]:
        L.append("  %s %s" % (cm["short"], cm["subject"]))
    L.append("Files:       %d  (+%d / -%d)" % (len(files), meta["stats"]["additions"], meta["stats"]["deletions"]))
    for f in files:
        flags = ",".join(x for x in [f["status"], "generated" if f["generated"] else "",
                                     "binary" if f["binary"] else "", "truncated" if f.get("truncated") else ""] if x)
        extra = ""
        if f["status"] == "snapshot":
            extra = " lines " + ",".join("%d-%d" % (h["new_start"], h["lines"][-1]["n"]) for h in f["hunks"])
        L.append("  %-60s +%-5d -%-5d %s %s%s" % (f["path"], f["additions"], f["deletions"], flags,
                                                 f["language"], extra))
    L.append("Reviewable:  %d files, %d changed lines%s" % (
        len(reviewable), changed, ", %d lines of existing code" % snapshot_lines if snapshot_lines else ""))
    if changed + snapshot_lines > LARGE_LINES or len(reviewable) > LARGE_FILES:
        L.append("SIZE:        LARGE - split the review across subagents by file group.")
    L.append("OUT_DIR=%s" % out_dir)
    return "\n".join(L)
