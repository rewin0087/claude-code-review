"""Requirements and context supplied with a review: ticket text, specs, docs, images, links.

Each source is classified, copied into <OUT_DIR>/context/ (local files and free text), and
recorded in <OUT_DIR>/context.json so that the reviewer can read it and the report can list
it. Nothing is fetched from the network here: URLs are recorded and Claude fetches them.
"""
import hashlib
import json
import os
import re
import shutil
import zipfile

from .errors import ReviewError

TEXT_EXT = {".txt", ".md", ".markdown", ".rst", ".adoc", ".csv", ".tsv", ".json", ".yaml", ".yml",
            ".xml", ".html", ".htm", ".feature", ".gherkin", ".org", ".log", ".ini", ".toml", ".sql"}
IMAGE_EXT = {".png", ".jpg", ".jpeg", ".gif", ".webp", ".svg", ".bmp"}
PDF_EXT = {".pdf"}
DOCX_EXT = {".docx"}
MAX_INLINE_CHARS = 20000          # per source, in the digest printed for the reviewer
MAX_FILE_BYTES = 20 * 1024 * 1024
URL_RE = re.compile(r"^https?://", re.I)
TICKET_HOSTS = ("atlassian.net", "jira", "linear.app", "github.com", "gitlab", "azure.com", "visualstudio.com",
                "shortcut.com", "clickup.com", "asana.com", "notion.so", "trello.com", "monday.com")


def _slug(text, limit=40):
    return re.sub(r"[^A-Za-z0-9._-]+", "-", text).strip("-")[:limit] or "source"


def classify(source, cwd):
    """-> (kind, value): kind is file | url | text; value is an absolute path, URL or text."""
    s = source.strip()
    if URL_RE.match(s):
        return "url", s
    candidate = s[1:] if s.startswith("@") else s
    path = candidate if os.path.isabs(candidate) else os.path.join(cwd, candidate)
    if os.path.isfile(path):
        return "file", os.path.realpath(path)
    if os.path.isdir(path):
        raise ReviewError("Context source '%s' is a folder; pass the individual files." % source)
    return "text", s


def file_type(path):
    ext = os.path.splitext(path)[1].lower()
    if ext in IMAGE_EXT:
        return "image"
    if ext in PDF_EXT:
        return "pdf"
    if ext in DOCX_EXT:
        return "docx"
    if ext in TEXT_EXT:
        return "text"
    with open(path, "rb") as fh:
        head = fh.read(8000)
    return "binary" if b"\0" in head else "text"


def docx_text(path):
    """Plain text of a .docx (paragraphs only) without third-party libraries."""
    try:
        with zipfile.ZipFile(path) as z:
            xml = z.read("word/document.xml").decode("utf-8", errors="replace")
    except (KeyError, zipfile.BadZipFile) as e:
        raise ReviewError("Could not read %s as .docx: %s" % (path, e))
    xml = re.sub(r"</w:p>", "\n", xml)
    xml = re.sub(r"<w:tab/>", "\t", xml)
    text = re.sub(r"<[^>]+>", "", xml)
    return re.sub(r"\n{3,}", "\n\n", text).strip()


def _read_text(path):
    with open(path, "rb") as fh:
        return fh.read().decode("utf-8", errors="replace")


def ingest(sources, out_dir, cwd):
    """Copy/record every source. -> manifest dict (also written to context.json)."""
    ctx_dir = os.path.join(out_dir, "context")
    if os.path.isdir(ctx_dir):
        shutil.rmtree(ctx_dir)           # each run reflects exactly the sources given
    os.makedirs(ctx_dir, exist_ok=True)
    items, seen = [], set()
    for i, src in enumerate(sources, 1):
        kind, value = classify(src, cwd)
        key = (kind, value)
        if key in seen:
            continue
        seen.add(key)
        sid = "S%d" % (len(items) + 1)
        item = {"id": sid, "kind": kind, "source": src}
        if kind == "url":
            item.update(type="ticket" if any(h in value.lower() for h in TICKET_HOSTS) else "link", url=value,
                        title=value)
        elif kind == "text":
            name = "%s-note.md" % sid
            with open(os.path.join(ctx_dir, name), "w") as fh:
                fh.write(value + "\n")
            item.update(type="text", path="context/" + name, title=_first_line(value), chars=len(value))
        else:
            size = os.path.getsize(value)
            if size > MAX_FILE_BYTES:
                raise ReviewError("Context file %s is larger than %d MB." % (value, MAX_FILE_BYTES // 2**20))
            ftype = file_type(value)
            if ftype == "binary":
                raise ReviewError("Context file %s is binary and not a supported type "
                                  "(text, markdown, pdf, docx, or an image)." % value)
            name = "%s-%s" % (sid, _slug(os.path.basename(value), 80))
            dest = os.path.join(ctx_dir, name)
            shutil.copyfile(value, dest)
            item.update(type=ftype, path="context/" + name, title=os.path.basename(value), bytes=size,
                        sha256=hashlib.sha256(open(value, "rb").read()).hexdigest()[:16])
            if ftype == "docx":
                txt_name = name + ".txt"
                with open(os.path.join(ctx_dir, txt_name), "w") as fh:
                    fh.write(docx_text(value))
                item["text_path"] = "context/" + txt_name
        items.append(item)
    manifest = {"sources": items}
    with open(os.path.join(out_dir, "context.json"), "w") as fh:
        json.dump(manifest, fh, indent=2)
    return manifest


def _first_line(text, limit=80):
    line = next((l.strip() for l in text.splitlines() if l.strip()), "Note")
    line = re.sub(r"^[#>*\-\s]+", "", line)
    return line if len(line) <= limit else line[:limit - 1] + "…"


def format_digest(manifest, out_dir):
    """What the reviewer reads: inline text, plus what to Read / WebFetch next."""
    out_dir = os.path.abspath(out_dir)
    L = ["Context sources: %d" % len(manifest["sources"])]
    to_read, to_fetch = [], []
    for it in manifest["sources"]:
        L.append("\n### %s · %s · %s" % (it["id"], it["type"], it.get("title") or it["source"]))
        if it["type"] in ("text", "docx"):
            path = os.path.join(out_dir, it.get("text_path") or it["path"])
            body = _read_text(path)
            if len(body) > MAX_INLINE_CHARS:
                L.append(body[:MAX_INLINE_CHARS] + "\n… [truncated: Read %s for the rest]" % path)
            else:
                L.append(body.rstrip())
        elif it["type"] in ("image", "pdf"):
            p = os.path.join(out_dir, it["path"])
            to_read.append("%s (%s)" % (p, it["id"]))
            L.append("(%s: Read %s)" % (it["type"], p))
        else:
            to_fetch.append("%s (%s)" % (it["url"], it["id"]))
            L.append("(%s: WebFetch %s)" % (it["type"], it["url"]))
    if to_read:
        L.append("\nREAD_FILES:\n  " + "\n  ".join(to_read))
    if to_fetch:
        L.append("\nFETCH_URLS:\n  " + "\n  ".join(to_fetch))
    L.append("\nCONTEXT_JSON=%s" % os.path.join(out_dir, "context.json"))
    return "\n".join(L)
