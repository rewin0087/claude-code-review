"""Validation of review.json against the diff, and resolution of cited commits."""
import json
import re

from .errors import ReviewError
from .gitcmd import describe_commit

SEVERITIES = ["critical", "major", "minor", "suggestion", "nitpick", "praise"]
VERDICTS = ["approve", "approve_with_suggestions", "request_changes"]


def load_json(path, what):
    try:
        with open(path) as fh:
            return json.load(fh)
    except FileNotFoundError:
        raise ReviewError("%s not found: %s" % (what, path))
    except json.JSONDecodeError as e:
        raise ReviewError("%s is not valid JSON (%s line %d col %d): %s" % (what, path, e.lineno, e.colno, e.msg))


def _line_numbers(f, key):
    return {l[key] for h in f["hunks"] for l in h["lines"] if l.get(key)}


def validate(diff, review):
    """-> (errors, warnings). Normalises comments in place (ids, file paths, side, _unanchored)."""
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
            alt = re.sub(r"^(\./|[ab]/)", "", path or "")   # tolerate ./ a/ b/ prefixes
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
        key, other = ("n", "o") if side == "new" else ("o", "n")
        if line not in _line_numbers(files[path], key):
            warnings.append("%s (%s:%s side=%s) is not on a diff line%s; shown as file-level comment"
                            % (where, path, line, side,
                               " (it exists on the other side)" if line in _line_numbers(files[path], other) else ""))
            c["_unanchored"] = True
    return errors, warnings


def resolve_history(diff, review):
    """Verify every cited commit exists; fill in short sha / date / subject. -> warnings."""
    repo = diff["meta"].get("repo_path")
    warnings, cache = [], {}

    def resolve(entry, where):
        sha = str(entry.get("sha") or "").strip()
        if sha not in cache:
            cache[sha] = describe_commit(repo, sha)
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
