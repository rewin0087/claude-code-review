#!/usr/bin/env python3
"""Collect what to review: ONLY the current branch's changes, or a given scope.

Diffs merge-base(base, head)..head so commits that landed on the base branch after you
branched off are NOT included. With --path, narrows to files / line ranges / globs and
reviews unchanged code as-is. Writes to <repo>/.code-review/<branch>[__<scope>]/:

  diff.patch   raw unified diff
  diff.json    parsed diff + meta (used by history.py and render.py)
  meta.json    branch / base / commit / scope info

Logic lives in codereview.collect; this file is only the command-line interface.
"""
import argparse
import os
import sys

from codereview import ReviewError
from codereview.collect import CollectOptions, MODES, collect, format_report, output_dir, write_collection


def parse_args(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--base", help="base branch to compare against (auto-detected if omitted)")
    ap.add_argument("--uncommitted", action="store_true",
                    help="also include staged + unstaged changes in the working tree")
    ap.add_argument("--context", type=int, default=5, help="context lines around changes")
    ap.add_argument("--head", help="branch/ref to review without checking it out (default: current HEAD)")
    ap.add_argument("--path", action="append", default=[],
                    help="limit the review to a file, dir, glob or range: a.py, a.py:10-40, a.py#L10-L40, src/, '**/*.ts' "
                         "(repeatable; relative to the current directory or the repo root)")
    ap.add_argument("--mode", choices=list(MODES), default="auto",
                    help="auto: branch changes in scope, else the code as-is | changes: only branch changes | "
                         "code: review the scoped code as-is, ignore the diff")
    ap.add_argument("--repo", default=os.getcwd())
    return ap.parse_args(argv)


def main(argv=None):
    a = parse_args(argv)
    opts = CollectOptions(repo=a.repo, base=a.base, head=a.head, uncommitted=a.uncommitted,
                          context=a.context, paths=a.path, mode=a.mode)
    try:
        c = collect(opts)
        out = output_dir(c.repo, c.meta["branch"], c.scopes)
        write_collection(c, out)
    except ReviewError as e:
        sys.exit(str(e))
    print(format_report(c, out))


if __name__ == "__main__":
    main()
