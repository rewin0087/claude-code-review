"""Validation of review.json against the diff, and resolution of cited commits."""
import json
import re

from .errors import ReviewError
from .gitcmd import describe_commit, path_exists

SEVERITIES = ["critical", "major", "minor", "suggestion", "nitpick", "praise"]
VERDICTS = ["approve", "approve_with_suggestions", "request_changes"]
REQUIREMENT_STATUSES = ["met", "partial", "missing", "contradicted", "unclear", "not_applicable"]
CHECK_STATUSES = ["pass", "warn", "fail", "info"]


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
    warnings += missing_references(review)
    e2, w2 = validate_context_sections(diff, review)
    return errors + e2, warnings + w2


def _anchor_warning(files, path, line, where):
    if path not in files:
        return "%s points at %s, which is not in the review" % (where, path)
    if line is not None and line not in _line_numbers(files[path], "n") | _line_numbers(files[path], "o"):
        return "%s points at %s:%s, which is not a line in the review" % (where, path, line)
    return None


def validate_context_sections(diff, review):
    """Requirements traceability, analysis checks, and comment reuse/requirement links."""
    errors, warnings = [], []
    meta = diff["meta"]
    files = {f["path"]: f for f in diff["files"]}
    summary = review.get("summary") if isinstance(review.get("summary"), dict) else {}
    comments = review.get("comments") if isinstance(review.get("comments"), list) else []
    comment_ids = {c.get("id") for c in comments}

    req = summary.get("requirements") or {}
    items = req.get("items") or []
    req_ids = set()
    for i, it in enumerate(items):
        where = "summary.requirements.items[%d]" % i
        it.setdefault("id", "R%d" % (i + 1))
        req_ids.add(it["id"])
        if not it.get("text"):
            errors.append("%s.text is required" % where)
        if it.get("status") not in REQUIREMENT_STATUSES:
            errors.append("%s.status must be one of %s" % (where, REQUIREMENT_STATUSES))
        for j, ev in enumerate(it.get("evidence") or []):
            w = _anchor_warning(files, ev.get("file"), ev.get("line"), "%s.evidence[%d]" % (where, j))
            if w:
                ev["_unanchored"] = True
                warnings.append(w)
        for cid in it.get("comments") or []:
            if cid not in comment_ids:
                warnings.append("%s links comment '%s', which does not exist" % (where, cid))
        if it.get("status") in ("partial", "missing", "contradicted") and not (it.get("comments") or it.get("notes")):
            warnings.append("%s (%s) is %s but has no linked comment or notes explaining the gap"
                            % (where, it["id"], it.get("status")))

    for i, ch in enumerate(summary.get("checks") or []):
        where = "summary.checks[%d]" % i
        if not ch.get("name"):
            errors.append("%s.name is required" % where)
        if ch.get("status") not in CHECK_STATUSES:
            errors.append("%s.status must be one of %s" % (where, CHECK_STATUSES))

    rev = None if meta.get("worktree") and meta.get("uncommitted") else meta.get("head")
    for i, c in enumerate(comments):
        for rid in c.get("requirements") or []:
            if rid not in req_ids:
                warnings.append("comments[%d] links requirement '%s', which does not exist" % (i, rid))
        reuse = c.get("reuse")
        if reuse:
            if not reuse.get("file"):
                errors.append("comments[%d].reuse.file is required" % i)
            elif not path_exists(meta["repo_path"], rev, reuse["file"]):
                reuse["_missing"] = True
                warnings.append("comments[%d].reuse points at %s, which does not exist in the repo"
                                % (i, reuse["file"]))
    return errors, warnings


def missing_references(review):
    """Warnings for important claims that aren't backed by a source."""
    out = []
    for i, c in enumerate(review.get("comments") or []):
        # a reuse pointer is its own evidence: the existing code in this repo
        if c.get("severity") in ("critical", "major") and not c.get("references") and not c.get("reuse"):
            out.append("comments[%d] (%s: %s) has no references; cite a source for it"
                       % (i, c.get("severity"), c.get("title", "")))
    aa = (review.get("summary") or {}).get("approach_assessment") or {}
    for i, alt in enumerate(aa.get("alternatives") or []):
        if not alt.get("references"):
            out.append("summary.approach_assessment.alternatives[%d] (%s) has no references"
                       % (i, alt.get("title", "")))
    return out


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
