"""Business logic for the branch-review skill.

The scripts in the parent directory (collect_diff.py, history.py, render.py) are thin
command-line wrappers around this package:

  gitcmd      running git, resolving refs, repo housekeeping
  languages   language detection and generated-file patterns
  diffparse   unified diff -> structured files/hunks/lines
  branch      choosing the base branch
  scope       file / line-range / glob scopes and "review as-is" snapshots
  collect     orchestrates the above into a review input (meta + files)
  githistory  blame / log analysis explaining why existing code exists
  review      review.json validation and commit-reference resolution
  summary     the markdown summary relayed in the chat
  report      the self-contained interactive HTML report
"""
from .errors import ReviewError

__all__ = ["ReviewError"]
