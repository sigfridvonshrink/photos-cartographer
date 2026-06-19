# photos-cartographer

A ground-up, safety-first **photo ingestion & GPS/time-calibration pipeline**. It takes an unorganized
dump of photos and produces a clean, deduplicated, date-organized working set, then resolves each photo
to real UTC, automatically corrects a wrong camera clock against your GPX tracks, and geotags everything
from the track.

It is built around one assumption: **your photos are irreplaceable, so nothing is deleted and nothing is
mutated without a validated plan.** The full motivation, the safety model, and a comparison to existing
tools (HoudahGeo, GeoSetter, gpscorrelate, darktable, …) are in
[`ingest/workflows/README.md`](ingest/workflows/README.md).

## The specifications are the source of truth

The pipeline is **specification-driven**: behavior is defined by the documents in
[`ingest/workflows/`](ingest/workflows/), and the code is expected to follow them. When changing
behavior, update the governing spec first.

| Document | Scope |
|---|---|
| [`photos-1-prep-workflow.md`](ingest/workflows/photos-1-prep-workflow.md) | **Phase 1 — prep:** consolidation, extension normalization, dedup/quarantine, organization, cache/handoff. |
| [`photos-2-time-gps-workflow.md`](ingest/workflows/photos-2-time-gps-workflow.md) | **Phase 2 — time/GPS calibration:** camera-clock inference and track-based geotagging. |
| [`photos-3-merge-workflow.md`](ingest/workflows/photos-3-merge-workflow.md) | **Phase 3 — merge:** safe merge of the calibrated working set into the permanent digiKam library. |
| [`photos-shared-contract.md`](ingest/workflows/photos-shared-contract.md) | Facts all phases share: the run lock, the `.photos-ingest/` control directory, `photos-00-config.json`, the registry, formats, `gpx_root`, and the end-to-end operator loop. |

## Layout

- `ingest/photos_pipeline/` — the pipeline package: `photos_1_prep.py` / `photos_2_time_gps.py` /
  `photos_3_merge.py` (the three phases) + `photos_utils.py` (shared `CONFIG` template + utilities) +
  `cli.py` (the combined `photos-ingest` entry) + `editor/` (the decision editor). Run a phase from a
  checkout with `python3 -m photos_pipeline <phase> <subcommand>` (with `ingest/` on `PYTHONPATH`), or
  build the self-contained `photos-ingest` zipapp with `tools/build-pyz`.
- `ingest/workflows/` — the authoritative specifications (above).
- `ingest/tests/` — the test suite. `tools/` — build + test helpers. `.githooks/` — pre-commit/pre-push.

## Core safety rules

- **No mutation outside a plan.** Planning never mutates; execution applies only a validated plan whose
  preconditions still hold.
- **Dry-run is the real plan**, serialized and displayed — not a separate simulation path.
- **No clobber** — no operation overwrites existing media; destinations are reserved first.
- **Quarantine, not delete** — duplicates are moved to a recoverable quarantine, never auto-removed.
- **Idempotent & resumable** — reruns act on the diff; prep re-plans from the filesystem after a crash.

## Running the tests

From the **repository root** (`conftest.py` puts `ingest/` on `sys.path` so `import photos_pipeline`
resolves):

```bash
python3 -m pytest -q
```

See `CLAUDE.md` for the full build/test/CLI contract and the seeded config defaults.
