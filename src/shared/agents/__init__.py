"""Production-located agent builders.

Phase 1 (Sprint M2): General Counsel — copy-not-import of the Sprint 9
three-level pattern (GC → Head of Commercial → accept-reject-reasoner) per
M2 pre-flight decision § 6.1. The Sprint 9 experiment file at
src/redline/experiments/sprint-09-accept-reject-specialist/ stays untouched;
this module is the production-located copy the dispatcher invokes.

Adds a ``MemorySaver`` checkpointer wired at GC build time (decision § 6.2)
so the dispatcher can address per-conversation threads via
``config={"configurable": {"thread_id": ...}}``.
"""
