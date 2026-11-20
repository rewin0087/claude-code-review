#!/usr/bin/env python3
"""Run automated security / dependency checks on the files in the review.

Always runs a built-in secret detector, then any installed scanners: semgrep, bandit,
npm audit, pip-audit. Nothing is installed automatically. Findings are tagged with whether
they sit on a changed (or selected) line. Writes <OUT_DIR>/scan.json and prints a digest.

Usage: scan.py --dir <OUT_DIR> [--only semgrep,bandit] [--timeout 180]

Logic lives in codereview.scan; this file is only the command-line interface.
"""
import argparse
import json
import os
import sys

from codereview import ReviewError
from codereview.review import load_json
from codereview.scan import format_digest, run_scans


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--dir", required=True, help="OUT_DIR printed by collect_diff.py")
    ap.add_argument("--only", help="comma-separated scanners to run (secrets always runs)")
    ap.add_argument("--timeout", type=int, default=180, help="seconds per scanner")
    a = ap.parse_args(argv)
    try:
        diff = load_json(os.path.join(a.dir, "diff.json"), "diff.json")
    except ReviewError as e:
        sys.exit("scan.py: " + str(e))
    only = set(a.only.split(",")) if a.only else None
    result = run_scans(diff, a.dir, only=only, timeout=a.timeout)
    path = os.path.join(a.dir, "scan.json")
    with open(path, "w") as fh:
        json.dump(result, fh, indent=1)
    print(format_digest(result, path))


if __name__ == "__main__":
    main()
