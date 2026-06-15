# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this repo is

A suite of scripts for managing, converting, and synchronizing a high-quality photo library
between **digiKam** (management/storage) and **Immich** (display/sharing). Top-level layout:

- **`ingest/`** — the **active development area**: a safe plan/validate/execute ingestion + GPS/time
  calibration pipeline. New work happens here. Each folder has its own `README.md`.
- **`convert/`** — compute-node image-conversion tools (RAW/TIFF → `__std.jpg` / `__std.jxl`).
- **`develop/`** — `photos-developer`, the development-workspace manager (RAW/JPEG → `__std.tif`
  masters). Kept and active; slated for later improvement.
- **`immich/`** — Immich-backend integration (timeline-visibility sync, hardlinked "TV" folder).
- **`archive/`** — reference-only, *not* active. Holds standalone legacy tools whose functionality has
  **not** been reimplemented in the active pipeline: direct-mutation digiKam↔Immich integration scripts
  (`photos-dk2im-sync`, `photos-im2dk-sync`, `photos-dk-pick-std-jpg`, `photos-im-mark`,
  `photos-gps-sync-xmp`, `photos-fix-exif-dates`) and `archive/storage/legacy-utils/` (the `photocheck-*`
  library-audit scripts and `photoflow.py`). The reengineering specs, the monolithic `photos-ingest`
  prototype that `ingest/` was split out of, and the superseded `photos-gps-tagger` have been removed —
  their behavior now lives in `ingest/` (`photos-1-prep`, `photos-2-time-gps`, `photos-3-merge`).

See `README.md` for the `__std` naming convention and dependencies, and each folder's `README.md` for
per-script detail.

The headline capability of the pipeline is **automatic camera-clock correction**: it infers a camera's
clock offset by matching its already-geotagged frames against GPX tracks, then geotags the un-tagged
majority by interpolating along the track. See `ingest/workflows/README.md`.

## Commands

The active script is an **executable Python file with no `.py` extension** (`ingest/photos-1-prep`).
Tests load it via `importlib.machinery.SourceFileLoader`, not normal import. `ingest/photos_utils.py`
must sit beside it — the script adds its own directory to `sys.path` and imports `photos_utils`.

Tests **MUST be run from the repo root** — several reference paths like `ingest/photos-1-prep`
relative to the root. `pytest.ini` sets `testpaths=ingest/tests develop/tests` and ignores `archive/`.

```bash
# Whole suite
python3 -m pytest -q

# A single test file / test
python3 -m pytest ingest/tests/test_workspace_prep.py -q
python3 -m pytest ingest/tests/test_workspace_prep.py::test_name -q

# Per-script test coverage (branch coverage; report scoped to the production scripts).
# tools/coverage bootstraps a local .venv (--system-site-packages) with dev-requirements.txt,
# runs `coverage run -m pytest` against .coveragerc, and writes htmlcov/. Args pass through:
tools/coverage                 # whole suite + per-script report + htmlcov/
tools/coverage -k merge        # subset (report % will be partial)

# Decision-editor front-end unit tests (web/app.js pure logic) — Node's built-in runner, no deps.
tools/jstest                   # node --test over ingest/decision-editor/tests/*.test.mjs
```

`ingest/tests/conftest.py` loads the extensionless `photos-1-prep` script and `photos_utils` **once**
into `sys.modules` so every test file shares one module instance (and restores the global `CONFIG`
between tests). Test files therefore `import photos_1_prep` rather than each re-loading the script —
without that, a combined `pytest` session breaks because `@patch("photos_1_prep....")` and a test's
captured module reference can resolve to different objects.

There is no build step and no linter config; runtime deps are system tools (`exiftool`, `magick`,
`cjxl`, `avifenc`, `ffmpeg`) plus pip packages listed in `README.md`. The only manifest is
`dev-requirements.txt` — `pytest` + `coverage` for running the suite / measuring coverage (used by
`tools/coverage` and CI); the pipeline itself needs no pip install.

### Continuous integration

- **GitHub Actions** (`.github/workflows/tests.yml`) runs `python3 -m pytest -q` on every push to `main`
  and on every pull request.
- **Local `pre-push` hook** (`.githooks/pre-push`) runs a static guard
  (`.githooks/check_test_only_functions.py` — fails if any production function is referenced only by
  tests) and then the suite before a push, aborting on either failure. Enable it per clone with
  `git config core.hooksPath .githooks`; bypass once with `git push --no-verify`. When the merge phase
  `ingest/photos-3-merge` lands, add it to `SRC_FILES` in the guard so the same sweep covers it.

### CLI contract

- `ingest/photos-1-prep` (prep phase): subcommands `plan` / `dry-run` / `execute`.
- `ingest/photos-2-time-gps` (time/GPS calibration phase) and `ingest/photos-3-merge` (library merge)
  are implemented and share the same plan/validate/execute contract. The original `prep` / `calibrate` /
  `refresh-library` / `merge` monolith they were split from has been removed; `refresh-library` was
  deliberately dropped in favor of on-demand fingerprinting in `photos-3-merge` (see its workflow spec).
- **Canonical plan persistence (all phases):** each phase's plan/decision artifact lives at a fixed
  control-dir path (`photos-10-prep-plan.json`, calibration `photos-21`/`22`/`23`, `photos-30-merge-plan.json`).
  The planning command writes it there and prints the location; the validate/apply commands read it from
  there — there are **no** `--output`/`--plan` path flags. Re-planning backs up the prior artifact under
  the shared incremental `-NNN` suffix (never clobbered). See shared contract Section 5 ("Canonical plan
  persistence") and `photos_utils.write_versioned_json`.

### Seeded config defaults

The in-code `photos_utils.CONFIG` template is the source of these defaults; it is seeded into each
workspace's `photos-00-config.json` on first prep run, then hand-edited and authoritative thereafter
(the workflow specs deliberately do **not** pin default *values* — they are a deployment choice, not
part of the behavioral contract). Current defaults worth knowing:

- **`gpx_root`**: `/srv/pictures/gpslogs/gpx` — where calibration looks for GPX tracks.
- **`merge.library_root`**: `/srv/pictures/5-finished` — the permanent digiKam library merge writes into.
- **GPX placement is tuned for narrow destinations** (museum/castle/park, where you move slowly and GPS
  goes sparse/indoors): interpolation gap `1800s`, extrapolation `300s`, anchor-match distance `50m`.
  The interpolation **distance** (`1000m`) and **speed** (`150 km/h`) caps are the safety net and are
  left tight, so a long time-gap only interpolates when net movement is small.

## Architecture & non-negotiable rules

The whole design exists to safely mutate **irreplaceable originals**. These rules are specified in
`ingest/workflows/` and override convenience:

- **No mutation outside a plan.** Every move/rename/quarantine/metadata-write/DB-mutation is a planned
  operation with a plan ID, op ID, explicit preconditions, expected result, and journal entry. Planning
  never mutates.
- **Dry-run is not simulation.** Dry-run validates the *real* serialized plan that execution would
  consume (the persisted canonical plan artifact) and reports a **summary** of it — never a separate
  virtual-filesystem code path. It does not dump every operation: the full exact plan is the saved
  artifact on disk, so dry-run summarizes the real plan rather than flooding the terminal.
- **Instruction fingerprint.** Execution recomputes the SHA-256 of the human-edited instruction file
  (e.g. `calibration.json`) and aborts if it differs from what the plan was built against.
- **No clobber.** No operation ever overwrites existing media. Destinations are reserved/validated first.
- **Quarantine, not delete.** Duplicates are moved to a recoverable quarantine; permanent purge would be
  a separate explicit command.
- **No destructive in-place mutation model.** The active scripts work strictly on the plan/validate/execute
  path; never reintroduce the original monolith's destructive in-place mutation approach.
- **Idempotent & resumable.** Reruns act on the diff; a crash mid-run is recoverable (prep re-plans from
  the filesystem as truth; calibration resumes its plan and skips applied ops).

### Pipeline layout (shared contract)

Defined in `ingest/workflows/photos-shared-contract.md`:

- The pipeline is two phases: **prep** (`photos-1-prep`) → **time/GPS calibration**
  (`photos-2-time-gps`, reserved/in progress).
- A transient **workspace** holds numbered media folders `0-source` … `5-photos-by-dest`
  (`5-photos-by-dest` is read-only staging, later merged into the permanent digiKam library — it is *not*
  the library).
- All control/artifact files live in a single `.photos-ingest/` control directory (config, guard
  sentinel `photos-00-workspace-guard`, handoff manifest, decision JSONs, journals, default `gpx/` root).
  Prep skips this subtree wholesale, so artifacts can never be mistaken for media.
- `photos-00-config.json` is the **workspace config**: seeded on first prep run from the in-code template
  `photos_utils.CONFIG`, then authoritative and hand-edited thereafter.
- A whole-run lock covers planning *and* execution so runs never overlap.

### Module structure

- `ingest/photos_utils.py` — shared config template (`CONFIG`) + utilities; must sit beside
  `photos-1-prep` (the script inserts its own directory into `sys.path` to import it).
- `ingest/photos-1-prep` — the prep workflow; owns *only* filesystem prep, no-clobber moves,
  dedup/quarantine, SQLite/hash cache, and the handoff manifest. It must not plan or apply GPS/time fixes.
- `ingest/tests/` — `test_prep_split`, `test_idempotency_cache`, `test_exif_metadata`,
  `test_workspace_prep`, `test_concurrency` (named for what they test, not the old phase numbers).
- `ingest/workflows/` — the authoritative specs (see below).

## Specs are the source of truth

The pipeline is **specification-driven**: behavior is defined by `ingest/workflows/*.md` — the two
per-phase workflows plus `photos-shared-contract.md`. When changing pipeline behavior, update the
governing spec; the markdown is authoritative, not just the code. The current task is to make
`photos-1-prep` fully conform to these (updated) workflow specs, so expect to reconcile differences
between the script and the spec rather than treat the existing code as ground truth.
