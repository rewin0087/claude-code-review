"""Parse `git diff` output into files -> hunks -> lines.

Each line is {"t": "ctx"|"add"|"del"|"meta", "o": old line no, "n": new line no, "c": text}.
"""
import re

from .languages import is_generated, language_for

HUNK_RE = re.compile(r"^@@ -(\d+)(?:,(\d+))? \+(\d+)(?:,(\d+))? @@ ?(.*)$")
DIFF_GIT_RE = re.compile(r'^diff --git "?a/(.+?)"? "?b/(.+?)"?$')


def strip_prefix(p):
    p = p.strip()
    if p.startswith('"') and p.endswith('"'):
        p = p[1:-1]
    if p == "/dev/null":
        return None
    return p[2:] if p[:2] in ("a/", "b/") else p


def _new_file(raw):
    m = DIFF_GIT_RE.match(raw)
    return {"old_path": m.group(1) if m else None, "new_path": m.group(2) if m else None,
            "status": "modified", "binary": False, "hunks": [], "additions": 0, "deletions": 0}


def _apply_header(cur, raw):
    """Handle the extended header lines between `diff --git` and the first hunk."""
    if raw.startswith("new file mode"):
        cur["status"] = "added"
    elif raw.startswith("deleted file mode"):
        cur["status"] = "deleted"
    elif raw.startswith("rename from "):
        cur["status"] = "renamed"
        cur["old_path"] = raw[len("rename from "):]
    elif raw.startswith("rename to "):
        cur["new_path"] = raw[len("rename to "):]
    elif raw.startswith("Binary files ") or raw.startswith("GIT binary patch"):
        cur["binary"] = True
    elif raw.startswith("--- "):
        path = strip_prefix(raw[4:])
        cur["old_path"] = path or cur["old_path"]
        if path is None:
            cur["status"] = "added"
    elif raw.startswith("+++ "):
        path = strip_prefix(raw[4:])
        cur["new_path"] = path or cur["new_path"]
        if path is None:
            cur["status"] = "deleted"


def parse_diff(text):
    files, cur, hunk = [], None, None
    old_no = new_no = 0
    for raw in text.split("\n"):
        if raw.startswith("diff --git "):
            cur, hunk = _new_file(raw), None
            files.append(cur)
            continue
        if cur is None:
            continue
        if hunk is None:
            _apply_header(cur, raw)
        m = HUNK_RE.match(raw)
        if m:
            old_no, new_no = int(m.group(1)), int(m.group(3))
            hunk = {"header": raw, "section": m.group(5), "old_start": old_no, "new_start": new_no, "lines": []}
            cur["hunks"].append(hunk)
            continue
        if hunk is None or raw == "":
            continue
        tag, content = raw[0], raw[1:]
        if tag == " ":
            hunk["lines"].append({"t": "ctx", "o": old_no, "n": new_no, "c": content})
            old_no += 1
            new_no += 1
        elif tag == "+":
            hunk["lines"].append({"t": "add", "o": None, "n": new_no, "c": content})
            new_no += 1
            cur["additions"] += 1
        elif tag == "-":
            hunk["lines"].append({"t": "del", "o": old_no, "n": None, "c": content})
            old_no += 1
            cur["deletions"] += 1
        elif tag == "\\":
            hunk["lines"].append({"t": "meta", "o": None, "n": None, "c": raw})
    for f in files:
        f["path"] = f["new_path"] if f["status"] != "deleted" else f["old_path"]
        f["language"] = language_for(f["path"] or "")
        f["generated"] = is_generated(f["path"])
    return files
