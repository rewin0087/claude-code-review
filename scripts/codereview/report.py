"""Build the self-contained interactive HTML report from diff + review data."""
import json
import os

from .errors import ReviewError
from .gitcmd import remote_web_url

DEFAULT_TEMPLATE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "templates", "report.html")
DATA_PLACEHOLDER, TITLE_PLACEHOLDER = "__REVIEW_DATA__", "__TITLE__"


def embed_json(obj):
    """JSON that is safe to place inside a <script> element."""
    return json.dumps(obj).replace("<", "\\u003c").replace("\u2028", "\\u2028").replace("\u2029", "\\u2029")


def report_title(meta):
    title = "Review: %s → %s" % (meta["branch"], meta["base"] or "as-is")
    return title.replace("&", "&amp;").replace("<", "&lt;")


def build_html(diff, review, template_path=DEFAULT_TEMPLATE):
    """Render the report. Adds meta["web_url"] (for commit links) as a side effect."""
    diff["meta"]["web_url"] = remote_web_url(diff["meta"].get("remote_url"))
    with open(template_path) as fh:
        html = fh.read()
    if DATA_PLACEHOLDER not in html:
        raise ReviewError("template is missing the %s placeholder" % DATA_PLACEHOLDER)
    html = html.replace(DATA_PLACEHOLDER, embed_json({"meta": diff["meta"], "files": diff["files"], "review": review}), 1)
    return html.replace(TITLE_PLACEHOLDER, report_title(diff["meta"]), 1)
