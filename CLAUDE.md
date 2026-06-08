# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this repo is

A suite of scripts for managing, converting, and synchronizing a high-quality photo library
between **digiKam** (management/storage) and **Immich** (display/sharing). It has two layers:

1. **Operational scripts** (`convert/`, `storage/`, `immich/`, `archive/`) — standalone tools
   organized by *where they run*. See `README.md` for per-script descriptions, the `__std.jpg` /
   `__std.jxl` naming convention, dependencies, and the `immich/photos-cfg.json` shape.
2. **`reengineer/`** — the **active development area**: a ground-up rewrite of the ingestion/calibration
   pipeline around a safe plan/validate/execute architecture. New work happens here.

The headline capability of the pipeline is **automatic camera-clock correction**: it infers a camera's
clock offset by matching its already-geotagged frames against GPX tracks, then geotags the un-tagged
majority by interpolating along the track. See `reengineer/workflows/README.md`.

## Commands

Scripts are **executable Python files with no `.py` extension** (`photos-ingest`, `photos-1-prep`,
`storage/photos-developer`). Tests load them via `importlib.machinery.SourceFileLoader`, not normal import.

```bash
# Run the test suite — MUST be run from the repo root.
# Some tests hardcode paths like 'reengineer/photos-ingest', so a different CWD breaks collection.
python3 -m pytest reengineer/tests/ -q

# A single test file / test
python3 -m pytest reengineer/tests/test_phase5_planner.py -q
python3 -m pytest reengineer/tests/test_phase5_planner.py::test_name -q
```

There is no build step, no linter config, and no dependency manifest; deps are system tools
(`exiftool`, `magick`, `cjxl`, `avifenc`, `ffmpeg`) plus pip packages listed in `README.md`.

### CLI contracts

- `photos-1-prep` (new split-out prep script): subcommands `plan` / `dry-run` / `execute`.
- `photos-ingest` (monolithic prototype, being split): subcommands `prep` / `calibrate` /
  `refresh-library` / `merge`, each with `--plan` / `--execute-plan`.

## Architecture & non-negotiable rules

The whole design exists to safely mutate **irreplaceable originals**. These rules come from
`reengineer/00_master_roadmap.md` and `01_architecture_and_cli_contract.md` and override convenience:

- **No mutation outside a plan.** Every move/rename/quarantine/metadata-write/DB-mutation is a planned
  operation with a plan ID, op ID, explicit preconditions, expected result, and journal entry. Planning
  never mutates.
- **Dry-run is not simulation.** Dry-run serializes and displays the *real* plan JSON that execution
  would consume — not a virtual-filesystem code path.
- **Instruction fingerprint.** Execution recomputes the SHA-256 of the human-edited instruction file
  (e.g. `calibration.json`) and aborts if it differs from what the plan was built against.
- **No clobber.** No operation ever overwrites existing media. Destinations are reserved/validated first.
- **Quarantine, not delete.** Duplicates are moved to a recoverable quarantine; permanent purge would be
  a separate explicit command.
- **Existing `photos-ingest` is a prototype, not a patch target.** Mine it for parsing/grouping/naming
  logic, but do not bolt fixes onto its destructive in-place mutation model — build the plan/validate/
  execute path instead.
- **Idempotent & resumable.** Reruns act on the diff; a crash mid-run is recoverable (prep re-plans from
  the filesystem as truth; calibration resumes its plan and skips applied ops).

### Pipeline layout (shared contract)

Defined in `reengineer/workflows/10_photos-shared-contract.md`:

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

- `reengineer/photos_utils.py` — shared config template + utilities imported by the scripts.
- `reengineer/photos-ingest` — original monolith (~3.7k lines); component boundaries it targets are in
  `01_architecture_and_cli_contract.md` §3 (`RootGuard`, `InventoryScanner`, `OperationPlanner`,
  `PlanValidator`, `PlanExecutor`, `JournalWriter`, etc.).
- `reengineer/photos-1-prep` — prep workflow split out of the monolith; owns *only* filesystem prep,
  no-clobber moves, dedup/quarantine, SQLite/hash cache, and the handoff manifest. It must not plan or
  apply GPS/time fixes.

## Specs are phase-gated

`reengineer/` is driven by numbered specification documents (`00_master_roadmap.md` → `07_*`, plus
`06_*` and `08_*` sub-phases) and the authoritative `reengineer/workflows/*.md`. Implementation is
**review-gated**: each phase is specified, implemented, tested, and approved before the next. When
changing pipeline behavior, find and update the governing spec — the markdown is the source of truth,
not just the code.
