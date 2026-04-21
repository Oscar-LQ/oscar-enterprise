# Redline track documentation

Track-specific documentation for Oscar's contract redlining capability.
Cross-track material — ADRs, SDK reference, shared patterns — lives
outside this directory. See `docs/` top level for the overall layout.

## Layout

- `reference/` — redline-specific reference material (e.g. the
  lawyer-shape criteria for NDA transformations).
- `research/` — exploratory research tied to specific redline sprints
  (e.g. the Adeu integration survey from Sprint 10A).

## Where other material lives

- **Sprint log.** Redline sprints are logged chronologically in the
  repo-root `SPRINT_LOG.md` with `[Redline]` heading tags. The
  `PROJECT.md` Sprint Index carries one-line summaries.
- **Cross-track SDK references** (e.g. Adeu API reference, Adeu
  idioms). `docs/reference/`.
- **Architecture Decision Records.** Single numbering sequence across
  tracks — redline ADRs from 019 onwards carry the `[Redline]` tag in
  the title. `docs/adr/`.
- **Track-shared architectural principles.** `PROJECT.md`
  (track-specific principles live here instead of `PROJECT.md` from
  M1 onwards).
