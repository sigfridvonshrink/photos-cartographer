# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this repo is

The ingestion pipeline for a high-quality photo library managed in **digiKam**: a safe
plan/validate/execute pipeline that ingests media and performs automatic GPS/time calibration.
Top-level layout (the package lives at the repo root):

- **`cartographer/`** — the pipeline package: prep / geotag / merge phases + the decision editor.
- **`tests/`** — the test suite. **`spec/`** — the authoritative workflow specs (with their own
  `README.md`).
- **`docs/`** — user-facing guides (`quickstart.md`, `concepts.md`, `editor.md`), linked from `README.md`.
  These are user docs; `spec/` remains the behavioral source of truth.
- **`tools/`** — build + test helpers (`build-pyz`, `coverage`, `jstest`, `spec-coverage`).
- **`.githooks/`** — local pre-commit / pre-push hooks. `.github/workflows/` — CI.

See `README.md` for the overview.

The headline capability of the pipeline is **automatic camera-clock correction**: it infers a camera's
clock offset by matching its already-geotagged frames against GPX tracks, then geotags the un-tagged
majority by interpolating along the track. See `spec/README.md`.

## Commands

The active pipeline is the **`cartographer` package** at `cartographer/`:
`photos_utils.py` (shared lib) + `photos_1_prep.py` / `photos_2_geotag.py` / `photos_3_merge.py`
(the three phases) + `cli.py`/`__main__.py` (the combined entry) + `editor/` (the decision editor).
From a checkout, run via `python3 -m cartographer <phase> <subcommand>` (with the repo root on
`PYTHONPATH`, or from the repo root). It is **shipped detached** as ONE self-contained executable
`dist/photos-cartographer` — a shebang'd zipapp of the whole package — built deterministically by
`tools/build-pyz` (+ an editable `photos-config-defaults.json` sibling); launched `./photos-cartographer
prep plan` exactly like a plain script (needs a `python3` on the host; zipapp doesn't embed Python).
`tools/build-pyz --check` (CI + pre-push) builds it to a temp dir and smoke-runs it; `dist/` is gitignored (build output, not committed).

**Config seed source:** a new workspace's `photos-00-config.json` is seeded by
`photos_utils.default_config()` — an external `photos-config-defaults.json` beside the executable (or
`$PHOTOS_CARTOGRAPHER_CONFIG`) wins over the built-in `DEFAULT_CONFIG`, so a detached deploy retunes
defaults by editing that sibling, never the zip. The built-in (with its documented tunables) stays in
`photos_utils.py`.

Tests **MUST be run from the repo root** — `conftest.py` puts the repo root on `sys.path` so
`import cartographer` resolves, and some tests reference repo-root paths like
`cartographer/photos_1_prep.py`. `pytest.ini` sets
`testpaths=tests cartographer/editor/tests`.

```bash
# Whole suite
python3 -m pytest -q

# A single test file / test
python3 -m pytest tests/test_workspace_prep.py -q
python3 -m pytest tests/test_workspace_prep.py::test_name -q

# Per-script test coverage (branch coverage; report scoped to the production scripts).
# tools/coverage bootstraps a local .venv (--system-site-packages) with dev-requirements.txt,
# runs `coverage run -m pytest` against .coveragerc, and writes htmlcov/. Args pass through:
tools/coverage                 # whole suite + per-script report + htmlcov/
tools/coverage -k merge        # subset (report % will be partial)

# Decision-editor front-end unit tests (web/app.js pure logic) — Node's built-in runner, no deps.
tools/jstest                   # node --test over cartographer/editor/tests/*.test.mjs

# Spec-clause coverage gate: every clause in spec/spec-clauses.json must keep >=1 test tagged
# @pytest.mark.spec("<id>"). Collection-only (fast); exits non-zero if a clause lost its test. CI runs
# it. Complements line/branch coverage — it tracks the SPEC behaviours/anti-behaviours, not lines.
tools/spec-coverage            # report + gate; --verbose for the per-clause table
```

`tests/conftest.py` imports the package modules once and **aliases them under their historical
short names** in `sys.modules` (`photos_1_prep` → `cartographer.photos_1_prep`, likewise
`photos_utils` / `photos_2_geotag` / `photos_3_merge`), then restores the global `CONFIG` between
tests. So test files keep `import photos_1_prep` and `@patch("photos_1_prep....")` unchanged — the
alias is the *same module object* as the package module, so every import and patch resolves
identically. (This replaced the old `SourceFileLoader` hack once the scripts became package modules.)

There is no build step and no linter config; runtime deps are system tools (`exiftool`, `magick`,
`ffmpeg`) plus pip packages listed in `README.md`. The only manifest is
`dev-requirements.txt` — `pytest` + `coverage` for running the suite / measuring coverage (used by
`tools/coverage` and CI); the pipeline itself needs no pip install.

### Continuous integration

- **GitHub Actions** (`.github/workflows/tests.yml`) runs `python3 -m pytest -q` on every push to `main`
  and on every pull request.
- **Local `pre-push` hook** (`.githooks/pre-push`) runs a static guard
  (`.githooks/check_test_only_functions.py` — fails if any production function is referenced only by
  tests) and then the suite before a push, aborting on either failure. Enable it per clone with
  `git config core.hooksPath .githooks`; bypass once with `git push --no-verify`. The guard's
  `SRC_FILES` covers all three phase modules + `photos_utils` under `cartographer/`.
- **Local `pre-commit` hook** (`.githooks/pre-commit`) rebuilds `dist/photos-cartographer` on every
  commit so the local executable is never stale. `dist/` is gitignored — this is a LOCAL build
  only; nothing is committed or pushed. It blocks a commit only if the build itself breaks.
- **Releases** (`.github/workflows/release.yml`): push a version tag (`git tag v1.2.0 && git push
  origin v1.2.0`) and CI builds `photos-cartographer` with `__version__` set to the tag (via
  `tools/build-pyz --version`) and attaches it + `photos-config-defaults.json` to a GitHub Release.
  The executable is distributed via releases, never committed to the repo.

### Release history

- **v1.1.1** — docs fix: correct the destination model in `docs/concepts.md` (an intermediate folder
  may hold photos *and* sub-destinations; only folders with no direct media are `container` nodes).
  Docs-only; the binary is unchanged from v1.1.0 (docs are not bundled).
- **v1.1.0** — **media extensions are now workspace config** (`media_extensions`, seeded then
  authoritative); folder-set and media-extension changes get field-scoped config fingerprints so they
  surgically restale the geotag/merge plans. Prep `plan` now **warns on dump files exiftool sees as
  media** (`image/*`/`video/*`) that aren't listed, suggesting a config add. Added user guides under
  `docs/`. Renames: package `photos_pipeline` → `cartographer`, `workflows/` → `spec/`, and the
  config-override env var `PHOTOS_PIPELINE_CONFIG` → `PHOTOS_CARTOGRAPHER_CONFIG` (the only
  deploy-facing break; the CLI is unchanged and existing workspaces keep working).
- **v1.0.1** — flatten `ingest/` into the repo root (`photos_pipeline/`, `tests/`, `workflows/`);
  README destination-folder-format update. No behavioral change.
- **v1.0.0** — first release: the unified `photos-cartographer` executable (renamed from `photos-ingest`).

### CLI contract

One combined entry point — `cartographer.cli:main` — dispatched git-style as
`photos-cartographer <phase> <subcommand>` (shipped as the single `photos-cartographer` zipapp executable; from a
checkout, `python -m cartographer <phase> <subcommand>`). The CLI is **self-documenting**: bare
`photos-cartographer` prints the overall role + phase list; bare `photos-cartographer <phase>` prints that phase's
role blurb + its subcommands (the tool is used a few times a year). Each phase still has a standalone
entry (`python -m cartographer.photos_1_prep …`) sharing the same `add_arguments`/`run` — tests use it.

- `photos-cartographer prep` — subcommands `plan` / `dry-run` / `execute` (+ `prune-quarantine`).
- `photos-cartographer geotag` — `plan` / `execute` / `finalize` (was the `photos-2-geotag` phase, formerly
  named "calibrate"; its `run` subcommand was **renamed to `plan`** so all phases start with `plan`).
- `photos-cartographer merge` — `init-library` / `plan` / `dry-run` / `execute`.
- `photos-cartographer edit` — the decision editor (a local web server; folded into the package at `cartographer/editor/`, web assets served as package data via importlib.resources, no bundler).
  Like every phase it operates on the **cwd workspace** (no workspace-naming argument) and refuses to
  run if the cwd is not an initialized workspace; `--demo` is the only no-workspace mode (read-only
  fixtures tour). Phases share the plan/validate/execute contract; workspace = cwd. The original `prep` / `geotag` /
  `refresh-library` / `merge` monolith they were split from has been removed; `refresh-library` was
  deliberately dropped in favor of on-demand fingerprinting in merge (see its workflow spec).
- `photos-cartographer console` — the operational console (a local web server at `cartographer/console/`):
  run **and monitor** phases from a browser over the **cwd workspace**. It only *triggers* phase
  `run()`s (in-process, single-slot) and *observes* their status via the reporting seam streamed over
  SSE — one mutation path, never re-implemented in the web layer. Bound to `127.0.0.1` by default
  (on loopback startup it prints a copy-paste `ssh -L` tunnel command — `photos_utils.ssh_tunnel_hint`;
  see `docs/design/web-console.md`). Built incrementally: prep `plan` /
  `dry-run` monitoring (v2.1) + prep `execute` behind a **2-step confirm gate** (v2.2 — Execute is
  enabled only when a clean, blocker-free saved plan exists, and the server re-checks
  confirmation + no-blockers + plan_id before running; the gate summarizes the *real* plan artifact,
  not a simulation), the **geotag/merge tabs** with planning/monitoring (v2.3), and **execute behind a
  per-phase confirm gate for all three phases** (v2.3.1 — each gate summarizes that phase's own plan
  artifact: prep photos-10, geotag photos-24, merge photos-30), and **precondition + staleness-aware
  action enablement** (v2.3.2 — buttons reflect visible `.photos-ingest` state: pipeline order,
  plan-exists, blockers, sealed/lock, and cross-phase staleness via the shared
  `photos_utils.plan_dependencies_fresh` helper; idle + window-focus polling keeps it current).
  Affordance only — the core still validates in depth and refuses; the helper is the cheap shared
  subset of the per-phase stale checks (quick ⊆ deep, same authoritative hash), and the **decision
  editor folded in as the 4th tab** (v2.4 — served through the console origin at `/edit/` as an
  iframe, with the editor's `/api/*` delegated to its own functions on the cwd workspace; one origin
  so the single SSH tunnel still suffices, and **zero editor changes**), and merge **`init-library`**
  with an optional-path prompt (blank → bless the configured `library_root`; given → bless + record),
  and **full CLI parity** (v2.5 — geotag **`finalize`** as a plain run, enabled only after a successful
  geotag execute and before finalize; prep **`prune-quarantine`** with a dry-run/delete dialog, the
  destructive delete gated by `_prune_guard` and the action kept enabled even on a sealed workspace as
  the sole sealed-allowed op). **All eleven phase commands are now driveable from the console.** Built
  on the shared event/sink seam (`cartographer/reporting.py`) and design tokens
  (`cartographer/editor/web/tokens.css`).
- **Canonical plan persistence (all phases):** each phase's plan/decision artifact lives at a fixed
  control-dir path (`photos-10-prep-plan.json`, geotag `photos-21`/`22`/`23`, `photos-30-merge-plan.json`).
  The planning command writes it there and prints the location; the validate/apply commands read it from
  there — there are **no** `--output`/`--plan` path flags. Re-planning backs up the prior artifact under
  the shared incremental `-NNN` suffix (never clobbered). See shared contract Section 5 ("Canonical plan
  persistence") and `photos_utils.write_versioned_json`.

### Seeded config defaults

The in-code `photos_utils.CONFIG` template is the source of these defaults; it is seeded into each
workspace's `photos-00-config.json` on first prep run, then hand-edited and authoritative thereafter
(the workflow specs deliberately do **not** pin default *values* — they are a deployment choice, not
part of the behavioral contract). Current defaults worth knowing:

- **`gpx_root`**: `/srv/pictures/gpslogs/gpx` — where geotag looks for GPX tracks.
- **`merge.library_root`**: `/srv/pictures/5-finished` — the permanent digiKam library merge writes into.
- **GPX placement is tuned for narrow destinations** (museum/castle/park, where you move slowly and GPS
  goes sparse/indoors): interpolation gap `1800s`, extrapolation `300s`, anchor-match distance `50m`.
  The interpolation **distance** (`1000m`) and **speed** (`150 km/h`) caps are the safety net and are
  left tight, so a long time-gap only interpolates when net movement is small.

## Architecture & non-negotiable rules

The whole design exists to safely mutate **irreplaceable originals**. These rules are specified in
`spec/` and override convenience:

- **No mutation outside a plan.** Every move/rename/quarantine/metadata-write/DB-mutation is a planned
  operation with a plan ID, op ID, explicit preconditions, expected result, and journal entry. Planning
  never mutates.
- **Dry-run is not simulation.** Dry-run validates the *real* serialized plan that execution would
  consume (the persisted canonical plan artifact) and reports a **summary** of it — never a separate
  virtual-filesystem code path. It does not dump every operation: the full exact plan is the saved
  artifact on disk, so dry-run summarizes the real plan rather than flooding the terminal.
- **Instruction fingerprint.** Execution recomputes the SHA-256 of the human-edited instruction file
  (e.g. `geotag.json`) and aborts if it differs from what the plan was built against.
- **No clobber.** No operation ever overwrites existing media. Destinations are reserved/validated first.
- **Quarantine, not delete.** Duplicates are moved to a recoverable quarantine; permanent purge would be
  a separate explicit command.
- **No destructive in-place mutation model.** The active scripts work strictly on the plan/validate/execute
  path; never reintroduce the original monolith's destructive in-place mutation approach.
- **Idempotent & resumable.** Reruns act on the diff; a crash mid-run is recoverable (prep re-plans from
  the filesystem as truth; geotag resumes its plan and skips applied ops).

### Pipeline layout (shared contract)

Defined in `spec/photos-shared-contract.md`:

- The pipeline is three phases: **prep** (`photos-1-prep`) → **geotag**
  (`photos-2-geotag`) → **merge** (`photos-3-merge`), all implemented.
- A transient **workspace** holds numbered media folders `0-sources` … `6-photos-by-dest`
  (`6-photos-by-dest` is read-only staging that merge joins into the permanent digiKam library — it is
  *not* the library).
- All control/artifact files live in a single `.photos-ingest/` control directory (config, guard
  sentinel `photos-00-workspace-guard`, handoff manifest, decision JSONs, journals, default `gpx/` root).
  Prep skips this subtree wholesale, so artifacts can never be mistaken for media.
- `photos-00-config.json` is the **workspace config**: seeded on first prep run from the in-code template
  `photos_utils.CONFIG`, then authoritative and hand-edited thereafter.
- A whole-run lock covers planning *and* execution so runs never overlap.

### Module structure

- `cartographer/photos_utils.py` — shared config template (`CONFIG`) + utilities; the phase
  modules import it package-relatively (`from .photos_utils import ...`).
- `cartographer/photos_1_prep.py` — the prep workflow; owns *only* filesystem prep,
  no-clobber moves, dedup/quarantine, SQLite/hash cache, and the handoff manifest. It must not plan or
  apply GPS/time fixes.
- `cartographer/photos_2_geotag.py` — the geotag workflow: camera-clock-offset inference,
  resolve-to-UTC, GPX-based GPS placement, and destination-local renaming.
- `cartographer/photos_3_merge.py` — the merge workflow: safe merge of the finalized
  `6-photos-by-dest` staging tree into the permanent digiKam library.
- `tests/` — `test_prep_split`, `test_idempotency_cache`, `test_exif_metadata`,
  `test_workspace_prep`, `test_concurrency` (named for what they test, not the old phase numbers).
- `spec/` — the authoritative specs (see below).

## Specs are the source of truth

The pipeline is **specification-driven**: behavior is defined by `spec/*.md` — the three
per-phase workflows (prep / geotag / merge) plus `photos-shared-contract.md`. When changing pipeline
behavior, update the governing spec; the markdown is authoritative, not just the code, so reconcile
differences between a script and its spec rather than treating the existing code as ground truth.
