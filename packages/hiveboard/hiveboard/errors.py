"""Exceptions raised by hiveboard. Everything fails loudly; nothing falls back to canned data."""


class HiveError(Exception):
    """Base class for hiveboard errors."""


class NotFound(HiveError):
    """A node (task, fact, skill, tenant) does not exist or is not in the expected state."""


class Conflict(HiveError):
    """A write was rejected because the caller's view is stale or violates a rule."""
