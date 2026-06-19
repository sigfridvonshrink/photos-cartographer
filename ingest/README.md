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
| [`workflows/photos-1-prep-workflow.md`](workflows/photos-1-prep-workflow.md) | **Phase 1 — prep:** consolidation, extension normalization, dedup/quarantine, organization, cache/handoff. Implemented by `photos-1-prep`. |
| [`workflows/photos-2-time-gps-workflow.md`](workflows/photos-2-time-gps-workflow.md) | **Phase 2 — time/GPS calibration:** camera-clock inference and track-based geotagging. Reserved for `photos-2-time-gps` (not yet implemented here). |
| [`workflows/photos-shared-contract.md`](workflows/photos-shared-contract.md) | Facts both phases share: the run lock, the `.photos-ingest/` control directory, `photos-00-config.json`, the registry, formats, `gpx_root`, and the end-to-end operator loop. |

## Contents

- `photos_pipeline/` — the pipeline package: `photos_1_prep.py` (Phase 1 prep; subcommands
  `plan` / `dry-run` / `execute`), `photos_2_time_gps.py` (Phase 2 geotag), `photos_3_merge.py`
  (Phase 3 merge), and `photos_utils.py` (shared `CONFIG` template + utilities, imported
  package-relatively). Run a phase from a checkout with `python3 -m photos_pipeline.photos_1_prep plan`
  (with `ingest/` on `PYTHONPATH`); shipped detached as three executable zipapps named
  `photos-1-prep` / `photos-2-time-gps` / `photos-3-merge` (run `./photos-1-prep plan`).
- `workflows/` — the authoritative specifications (above).
- `photos_pipeline/editor/` — the decision editor, folded into the package (served by `photos-ingest edit`).
- `tests/` — the test suite for the pipeline.

## Core safety rules

- **No mutation outside a plan.** Planning never mutates; execution applies only a validated plan whose
  preconditions still hold.
- **Dry-run is the real plan**, serialized and displayed — not a separate simulation path.
- **No clobber** — no operation overwrites existing media; destinations are reserved first.
- **Quarantine, not delete** — duplicates are moved to a recoverable quarantine, never auto-removed.
- **Idempotent & resumable** — reruns act on the diff; prep re-plans from the filesystem after a crash.

## Running the tests

From the **repository root** (`conftest.py` puts `ingest/` on `sys.path` so `import photos_pipeline`
resolves; some tests reference repo-root paths like `ingest/photos_pipeline/photos_1_prep.py`):

```bash
python3 -m pytest -q
```

`tests/conftest.py` imports the package modules once and aliases them under their short names in
`sys.modules` (`photos_1_prep` → `photos_pipeline.photos_1_prep`, etc.), so test files keep
`import photos_1_prep` / `@patch("photos_1_prep....")` working against a single shared instance.

## History

This pipeline was built from an earlier monolithic prototype, which has since been removed — its
behavior now lives in `photos-1-prep`, `photos-2-time-gps`, and `photos-3-merge`, governed by the
`workflows/` specifications.
