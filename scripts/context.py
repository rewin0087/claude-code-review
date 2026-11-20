#!/usr/bin/env python3
"""Collect requirements/context for a review: ticket text, specs, docs, images and links.

Each --source is a file path (txt/md/pdf/docx/images/...), a URL, or free text. Files and
text are copied into <OUT_DIR>/context/, everything is recorded in <OUT_DIR>/context.json,
and a digest is printed: text inline, plus the images/PDFs to Read and the URLs to WebFetch.

Usage: context.py --dir <OUT_DIR> --source <file|url|text> [--source ...] [--cwd DIR]

Logic lives in codereview.context; this file is only the command-line interface.
"""
import argparse
import os
import sys

from codereview import ReviewError
from codereview.context import format_digest, ingest


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--dir", required=True, help="OUT_DIR printed by collect_diff.py")
    ap.add_argument("--source", action="append", default=[], required=True,
                    help="file path, URL, or free text (repeatable)")
    ap.add_argument("--cwd", default=os.getcwd(), help="base directory for relative paths")
    a = ap.parse_args(argv)
    if not os.path.isdir(a.dir):
        sys.exit("context.py: output folder not found: %s (run collect_diff.py first)" % a.dir)
    try:
        manifest = ingest(a.source, a.dir, a.cwd)
    except ReviewError as e:
        sys.exit("context.py: " + str(e))
    print(format_digest(manifest, a.dir))


if __name__ == "__main__":
    main()
