"""Choosing which base branch a branch should be compared against."""
from .gitcmd import git, ref_exists

BASE_CANDIDATES = ["main", "master", "develop", "development", "dev", "trunk"]


def detect_base(cwd, current, head="HEAD"):
    """Pick the candidate base whose merge-base is closest to head (fewest commits ahead)."""
    candidates = []
    origin_head = git(["symbolic-ref", "--quiet", "refs/remotes/origin/HEAD"], cwd, check=False).strip()
    if origin_head:
        candidates.append(origin_head.replace("refs/remotes/", ""))
    for name in BASE_CANDIDATES:
        candidates += [name, "origin/" + name]
    best, seen = None, set()
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


def is_base_branch(name):
    return name in BASE_CANDIDATES
