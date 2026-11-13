"""Backbone clinical abstraction prototype."""

EXTRACTOR_VERSION = "x1"   # bump when the extraction prompt or schema changes (invalidates the extraction cache)
RULESET_VERSION = "r3"     # bump when reconciliation rules change (reconcile is cheap and always re-runnable)
QUERY_VERSION = "q7"       # bump when operator/projection output changes (invalidates cached answers)
