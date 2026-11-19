#!/usr/bin/env python3
"""Merge diff.json + review.json into a self-contained interactive HTML report.

Validates review.json (line anchors, cited commit SHAs), writes report.html and
summary.md, prints the summary for the chat, and opens the report.

Usage: render.py --dir <OUT_DIR> [--no-open] [--out report.html]

Logic lives in codereview.review / .report / .summary; this file is only the CLI.
"""
import argparse
import os
import subprocess
import sys

from codereview import ReviewError
from codereview.report import build_html
from codereview.review import load_json, resolve_history, validate
from codereview.summary import file_url, terminal_summary


def open_file(path):
    """Best-effort: open the report in the default browser."""
    try:
        if sys.platform == "darwin":
            subprocess.Popen(["open", path])
        elif sys.platform.startswith("win"):
            os.startfile(path)  # noqa
        else:
            subprocess.Popen(["xdg-open", path], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    except Exception as e:
        print("Could not open browser automatically: %s" % e)


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--dir", required=True, help="OUT_DIR printed by collect_diff.py")
    ap.add_argument("--out", help="output HTML path (default <dir>/report.html)")
    ap.add_argument("--no-open", action="store_true")
    a = ap.parse_args(argv)

    try:
        diff = load_json(os.path.join(a.dir, "diff.json"), "diff.json")
        review = load_json(os.path.join(a.dir, "review.json"), "review.json")
    except ReviewError as e:
        sys.exit("render.py: " + str(e))
    errors, warnings = validate(diff, review)
    warnings += resolve_history(diff, review)
    for w in warnings:
        print("WARNING: " + w)
    if errors:
        print("review.json has %d error(s):" % len(errors))
        for e in errors:
            print("  - " + e)
        sys.exit(1)

    try:
        html = build_html(diff, review)
    except ReviewError as e:
        sys.exit("render.py: " + str(e))
    out = os.path.abspath(a.out or os.path.join(a.dir, "report.html"))
    with open(out, "w") as fh:
        fh.write(html)
    md = terminal_summary(diff, review, out)
    with open(os.path.join(a.dir, "summary.md"), "w") as fh:
        fh.write(md)
    print("REPORT=%s" % out)
    print("REPORT_URL=%s" % file_url(out))
    print("----- SUMMARY (relay this to the user) -----")
    print(md)
    if not a.no_open:
        open_file(out)


if __name__ == "__main__":
    main()
