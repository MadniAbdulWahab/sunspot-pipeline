"""Sunspot number pipeline: ingest, validate, process, reconcile and archive WDC-SILSO data."""

# Bump this when processing logic or the output schema changes.
# A new version gets its own archive/<version>/ folder, so old outputs stay untouched.
__version__ = "1.0.0"
