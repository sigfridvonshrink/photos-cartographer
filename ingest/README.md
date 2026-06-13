# ingest/ — safe photo ingestion & GPS/time calibration pipeline

This is the **active** part of the project: a ground-up, safety-first pipeline that takes an unorganized
dump of photos and produces a clean, deduplicated, date-organized working set, then resolves each photo
to real UTC, automatically corrects a wrong camera clock against your GPX tracks, and geotags everything
from the track.

It is built around one assumption: **your photos are irreplaceable, so nothing is deleted and nothing is
mutated without a validated plan.** The full motivation, the safety model, and a comparison to existing
tools (HoudahGeo, GeoSetter, gpscorrelate, darktable, …) are in [`workflows/README.md`](workflows/README.md).

## The specifications are the source of truth

The pipeline is **specification-driven**: behavior is defined by the documents in [`workflows/`](workflows/),
and the code is expected to follow them. When changing behavior, update the governing spec first.

| Document | Scope |
|---|---|
| [`workflows/10_photos-1-prep-workflow.md`](workflows/10_photos-1-prep-workflow.md) | **Phase 1 — prep:** consolidation, extension normalization, dedup/quarantine, organization, cache/handoff. Implemented by `photos-1-prep`. |
| [`workflows/10_photos-2-time-gps-workflow.md`](workflows/10_photos-2-time-gps-workflow.md) | **Phase 2 — time/GPS calibration:** camera-clock inference and track-based geotagging. Reserved for `photos-2-time-gps` (not yet implemented here). |
| [`workflows/10_photos-shared-contract.md`](workflows/10_photos-shared-contract.md) | Facts both phases share: the run lock, the `.photos-ingest/` control directory, `photos-00-config.json`, the registry, formats, `gpx_root`, and the end-to-end operator loop. |

## Contents

- `photos-1-prep` — the Phase 1 prep script. Subcommands: `plan` / `dry-run` / `execute`.
- `photos_utils.py` — shared config template (`CONFIG`) and utilities; must sit beside `photos-1-prep`
  (the script adds its own directory to `sys.path` and imports it).
- `workflows/` — the authoritative specifications (above).
- `tests/` — the test suite for the prep script.

## Core safety rules

- **No mutation outside a plan.** Planning never mutates; execution applies only a validated plan whose
  preconditions still hold.
- **Dry-run is the real plan**, serialized and displayed — not a separate simulation path.
- **No clobber** — no operation overwrites existing media; destinations are reserved first.
- **Quarantine, not delete** — duplicates are moved to a recoverable quarantine, never auto-removed.
- **Idempotent & resumable** — reruns act on the diff; prep re-plans from the filesystem after a crash.

## Running the tests

From the **repository root** (some tests reference `ingest/photos-1-prep` relative to the root):

```bash
python3 -m pytest -q
```

`tests/conftest.py` loads the extensionless `photos-1-prep` script and `photos_utils` once into
`sys.modules` so every test file shares a single module instance; tests `import photos_1_prep` rather
than re-loading it.

## History

This pipeline was split out of an earlier monolithic `photos-ingest` prototype. That prototype, the
phase-gated reengineering specs, and the original calibration/merge tests have since been removed — their
behavior now lives in `photos-1-prep`, `photos-2-time-gps`, and `photos-3-merge`, governed by the
`workflows/` specifications.
