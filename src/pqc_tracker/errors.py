"""Exception types. Any of these in a collector means: keep the last good snapshot."""


class TrackerError(Exception):
    """Base class."""


class CollectionError(TrackerError):
    """A collector failed or returned malformed data. Nothing may be published from this run."""


class ValidationError(TrackerError):
    """Data files failed schema or semantic validation."""
