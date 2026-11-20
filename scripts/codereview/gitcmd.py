"""Thin, testable wrappers around the git CLI."""
import os
import re
import subprocess

from .errors import ReviewError


def git(args, cwd, check=True):
    """Run git and return stdout. With check=False a failing command returns ""."""
    r = subprocess.run(["git", "-c", "core.quotepath=off"] + list(args), cwd=cwd,
                       capture_output=True, text=True, errors="replace")
    if r.returncode != 0:
        if check:
            raise ReviewError("git %s failed:\n%s" % (" ".join(args), r.stderr.strip()))
        return ""
    return r.stdout


def git_bytes(args, cwd):
    """Run git and return raw stdout bytes, or None if it fails."""
    r = subprocess.run(["git"] + list(args), cwd=cwd, capture_output=True)
    return r.stdout if r.returncode == 0 else None


def ref_exists(ref, cwd):
    return subprocess.run(["git", "rev-parse", "--verify", "--quiet", ref + "^{commit}"],
                          cwd=cwd, capture_output=True).returncode == 0


def resolve_ref(ref, cwd):
    """Return ref, or origin/<ref> when only the remote-tracking branch exists, else None."""
    if ref_exists(ref, cwd):
        return ref
    if ref_exists("origin/" + ref, cwd):
        return "origin/" + ref
    return None


def repo_root(path):
    return git(["rev-parse", "--show-toplevel"], path, check=False).strip()


def rev_parse(ref, cwd):
    return git(["rev-parse", ref], cwd).strip()


def current_branch(cwd):
    return git(["rev-parse", "--abbrev-ref", "HEAD"], cwd).strip()


def local_branches(cwd):
    return [b.strip() for b in git(["branch", "--format=%(refname:short)"], cwd).split("\n") if b.strip()]


def remote_url(cwd):
    return git(["config", "--get", "remote.origin.url"], cwd, check=False).strip()


def remote_web_url(remote):
    """git@github.com:me/repo.git | https://gitlab.com/g/repo.git -> https://host/path"""
    if not remote:
        return None
    m = re.match(r"^(?:git@|ssh://git@)([^:/]+)[:/](.+?)(?:\.git)?/?$", remote) or \
        re.match(r"^https?://(?:[^@/]+@)?([^/]+)/(.+?)(?:\.git)?/?$", remote)
    return "https://%s/%s" % (m.group(1), m.group(2)) if m else None


def describe_commit(repo, sha):
    """[full_sha, short_sha, date, subject] for a commit-ish, or None if it doesn't exist."""
    if not repo or not re.match(r"^[0-9a-fA-F]{4,40}$", sha or ""):
        return None
    out = git(["-C", repo, "show", "-s", "--date=short", "--format=%H%x1f%h%x1f%ad%x1f%s",
               sha + "^{commit}"], None, check=False).strip()
    return out.split("\x1f") if out else None


def ensure_ignored(repo, entry=".code-review/"):
    """Keep review output out of commits without touching the tracked .gitignore."""
    git_dir = git(["rev-parse", "--git-common-dir"], repo).strip()
    exclude = os.path.join(git_dir if os.path.isabs(git_dir) else os.path.join(repo, git_dir), "info", "exclude")
    try:
        os.makedirs(os.path.dirname(exclude), exist_ok=True)
        existing = open(exclude).read() if os.path.exists(exclude) else ""
        if entry not in existing.split("\n"):
            with open(exclude, "a") as fh:
                fh.write(("" if existing.endswith("\n") or not existing else "\n") + entry + "\n")
    except OSError:
        pass


def path_exists(repo, rev, path):
    """True if path exists at rev (or in the working tree when rev is None)."""
    if not path:
        return False
    if rev is None:
        return os.path.exists(os.path.join(repo, path))
    return subprocess.run(["git", "cat-file", "-e", "%s:%s" % (rev, path)], cwd=repo,
                          capture_output=True).returncode == 0
