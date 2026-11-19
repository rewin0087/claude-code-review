class ReviewError(Exception):
    """A user-facing failure: the message is shown as-is and the command exits non-zero."""
