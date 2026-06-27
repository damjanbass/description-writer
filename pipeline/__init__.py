"""Phase 1 batch pipeline: CSV/XLSX in -> attribute-grounded generation ->
correctness layer -> dual-script out -> provenance report.

Public data contracts live in `pipeline.types` and are the single source of
truth every stage composes through. The stage modules (ingest, generation,
correctness, provenance, runner) keep their public signatures stable so the
runner can wire them without each stage re-inventing shapes.
"""
