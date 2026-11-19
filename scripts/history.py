#!/usr/bin/env python3
"""Explain WHY the code under review is the way it is, from git history.

For each modified / deleted / renamed file (as of the merge-base) and each file reviewed
as-is, records who last touched the affected lines (git blame), recent commits on the
file, issue/PR/ticket references, and fix/revert/workaround commits flagged NOTABLE.

Writes <OUT_DIR>/history.json and prints a digest for the reviewer.

Usage: history.py --dir <OUT_DIR> [--recent 8] [--deep]
  --deep  also blame the context lines around each change and keep longer commit bodies

Logic lives in codereview.githistory; this file is only the command-line interface.
"""
import argparse
import json
import os
import sys

from codereview import ReviewError
from codereview.githistory import collect_history, format_digest
from codereview.review import load_json


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--dir", required=True, help="OUT_DIR printed by collect_diff.py")
    ap.add_argument("--recent", type=int, default=8, help="recent commits per file")
    ap.add_argument("--deep", action="store_true")
    a = ap.parse_args(argv)
    try:
        diff = load_json(os.path.join(a.dir, "diff.json"), "diff.json")
    except ReviewError as e:
        sys.exit("history.py: " + str(e))
    history = collect_history(diff, recent=a.recent, deep=a.deep)
    path = os.path.join(a.dir, "history.json")
    with open(path, "w") as fh:
        json.dump(history, fh, indent=1)
    print(format_digest(history, diff["meta"], path))


if __name__ == "__main__":
    main()
