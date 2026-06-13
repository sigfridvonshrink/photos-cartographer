# Calibration (`photos-2-time-gps`) — Analysis & Phased Build Roadmap

Reference for implementing the pipeline's second phase, **calibration**, against
`ingest/workflows/10_photos-2-time-gps-workflow.md` (the authoritative spec, 34 sections) and
`10_photos-shared-contract.md`. This is the calibration counterpart to `PREP_GAP_ANALYSIS_v2.md`:
it is the map we build against, phase by reviewed phase. The spec is authoritative; where this
doc and the spec disagree, the spec wins.

---

## 1. What calibration is

The headline capability: **automatically infer a camera's clock offset** by matching its
already-geotagged frames against GPX tracks, then **resolve every photo to real UTC**,
**interpolate GPS** for the un-tagged majority, and **rename** files to destination-local civil
time — all through the same plan/validate/execute, fingerprinted-dependency, authored-decisions
discipline prep uses. It is a net-new extensionless script `ingest/photos-2-time-gps` beside
`photos-1-prep` and `photos_utils.py`, at least as large as the whole prep reengineering.

### Non-negotiable rules (spec)
- **Scope:** operates ONLY on `6-photos-by-dest/` — photo-only (`image`/`raw`), never videos (§7).
- **Order is hard:** *Time first → GPS second → rename/metadata execution last* (§2, §34). GPS
  planning cannot begin until **every** file has a resolved UTC; execution **never recalculates**,
  it only validates and applies a complete plan.
- **Convergent rerun loop** (§2.1): run → inspect → edit decision fields in the JSON artifacts →
  rerun. Machine proposals recompute; **authored decisions are preserved** where their logical
  target is unchanged; downstream artifacts recompute only where an upstream fingerprint changed.
- **Calibration is read-only w.r.t. config and the by-dest tree's identity:** it never writes
  config, never does prep's move-recognition, never touches `6-photos-by-dest` except the planned
  in-place metadata writes / renames.

### Preflight hard-stops (Stage 1, §7 / §13)
Acquired under the workspace lock, before any artifact is written:
1. Lifecycle guards (shared with prep): **sealed** workspace → refuse; **uninitialized** (no
   guard) → "run prep first"; **loose file at root** → hard-stop.
2. `0-sources/` must be **empty**; `5-photos-by-date/` must contain **no photos**.
3. No `destination_distribution_subfolders` (e.g. `jpg/`,`tif/`) anywhere under by-dest —
   presence alone (even empty) means development started → hard-stop (§7.1).
4. By-dest contains **only photos** — no `other`-class, no `video` (§7.2/§7.3).
5. **A prep run must follow the latest by-date→by-dest move** (§13.1): detect (stat-level, no
   media re-read) by-dest media the handoff doesn't record and/or by-date photos now missing →
   targeted "re-run prep" blocker (calibration never auto-fixes this).
6. Config + handoff + cache dependencies current; every human-authored value sanity-validated
   (§9.2) — invalid value is a located hard blocker, preserved and flagged, never coerced.

### Inputs
- `photos-11-handoff.json` — the prep contract, **SHA-256-verified by exact bytes** like every
  JSON dependency (§4); supplies per-file metadata, `camera_group_key`, native-GPS/timestamp
  flags, and `destination_folders` facts.
- The live `photos-00-ingest.db` cache (prep owns `file_cache`/`metadata_cache`; calibration owns
  its own disjoint tables, shared §13.4).
- The shared config `photos-00-config.json`.
- GPX tracks under `gpx_root`.

### Artifact / decision cascade (all in `.photos-ingest/`, grouped by destination)
Every artifact records a **flattened** SHA-256 dependency block (§5) and is rejected downstream if
any recorded dependency changed (§3/§6). Decision artifacts carry pre-created human-decision
fields that are preserved across reruns (§9).

```
preflight (textual, no JSON)
  → photos-21-time-decisions.json        (timezone + per-(group,dest) offset decisions)
  → resolved-UTC cache (SQLite) + fingerprint
  → photos-22-gps-decisions.json         (summary + review/blocker items only)
  → photos-23-executable-plan.json        (exact file-level ops; executable:true)
  → execute → photos-24-execution-summary.json (terminal; never a dependency)
  → finalize (explicit): photos-25-complete-log.json + photos-25-calibrate-ingest.db + package
```

### The two hard parts
- **Per-(camera group, destination) clock-offset inference (§10.2/§19) — the headline.** Offset is
  decided per *(group, destination)*, not per camera, because clocks drift/reset between trips. It
  is **self-anchored** only from that group's native-GPS frames *in that destination*, by matching
  each geotagged frame to a GPX point or short segment and reading the GPX timestamp; the offset is
  `gpx_utc − camera_naive_time`. Multiple candidates are **ranked, never averaged** (§19.2): pick
  the best match, treat the rest as supporting (within an offset-spread threshold) or conflicting
  (→ user review). A cell with no native-GPS frame **inherits the nearest ancestor destination's
  effective offset downward** as a confirmable proposal (never sideways, never up); a manual offset
  at any level re-roots what descendants inherit.
- **GPS placement (§24) + reversible manual overrides (§24.1).** After UTC is solved, un-tagged
  photos get coordinates by interpolating/extrapolating along the GPX track (and/or native-GPS
  photo anchors) using resolved UTC, bounded by gap/distance/speed thresholds. Manual overrides are
  reversible via a **pinned pre-state ledger** in the DB (capture the field before the first
  overriding write, keyed by content fingerprint; withdraw → restore the pinned value, or clear if
  the pre-state was "absent"). Automated GPS is recomputed, never rolled back; time/filename are
  always recomputed in place, never reverted.

---

## 2. Reuse / refactor / new / mine

**Reuse as-is from `photos_utils.py`** (already importable): `CONFIG` + `load_or_seed_config` +
`validate_config` + `config_path`; the path helpers (`control_dir`, `guard_path`,
`sealed_marker_path`, `is_sealed`, `db_path`, `handoff_path`, `journal_path`, `lock_path`,
`prep_log_path`); `MetadataReader`/`ExifToolWorkerPool`/`is_metadata_cache_fresh`;
`CAMERA_IDENTITY_FIELDS` + `CAMERA_GROUP_KEY_VERSION`; `ProgressCoordinator`; version/fingerprint
constants (`FIELD_SET_VERSION`, `METADATA_SCHEMA_VERSION`, `EXTRACTION_OPTIONS_FINGERPRINT`);
`detect_zfs_dataset`; `_atomic_write_text`.

**Refactor out of `photos-1-prep` into `photos_utils` (Phase 0):** `WorkspaceCache` (the
`file_cache`/`metadata_cache`/`meta` tables; calibration adds its own disjoint tables) and
`WorkspaceLock` — both currently live in `photos-1-prep` and are not importable. Add a shared
**JSON-artifact dependency helper** (write artifact with a recorded `depends_on` block; re-read +
re-hash exact bytes + verify before use) and the `_move_no_clobber` / atomic-write / zfs-snapshot
helpers. The `Operation`/`Plan`/`Journal`/`PlanValidator`/`PlanExecutor` spine is partly generic —
extract the reusable parts; op-types stay phase-specific.

**New (calibration-owned):** the by-dest in-memory file model; the GPX index; the
per-(group,destination) offset inference; destination-timezone + resolved-UTC engine; the GPS
decision tree + pre-state ledger; the destination-local rename planner; the 21–25 artifacts and
their convergent-rerun staleness cascade.

**Mine the algorithms** (not the destructive in-place model) — historical note: the source files
below have since been removed; these algorithms now live in `photos-2-time-gps`. Line references are
kept for provenance only:
- `archive/reengineer/photos-ingest`: `GPXIndex` (XML parse + deterministic fingerprint, ~`:1712`),
  `haversine` (~`:1694`), `apply_gpx_placement` (GPX interp/extrap with gap/distance/speed
  thresholds, ~`:2345`), `apply_photo_anchors` (~`:2420`), exiftool read + **CSV batch write with
  read-back verification** (~`:1175`), `apply_time_sync` offset application (~`:2316`).
- `archive/storage/photos-gps-tagger`: the mature **photo-anchor interp/extrap engine** (`:505-664`) —
  native-point detection via `GPSProcessingMethod ∉ {manual, interpolated}`, velocity-aware
  extrapolation using a `MIN_EXTRAPOLATE_GAP_S` stability vector, **idempotent skip-if-unchanged**,
  N/S/E/W ref handling. The GPX-track engine (monolith) is the primary source; photo-anchors are
  the secondary. Config thresholds already exist in `CONFIG` (`gpx_*`, `photo_anchor_*`).

Both prototypes are **algorithm references only** — they mutate originals in place with no
plan/validate/execute, journal, dependency cascade, or reversibility; calibration rebuilds those
on the prep harness.

---

## 3. Phased roadmap (each a reviewed PR; the whole suite stays green)

- **Phase 0 — Shared-infra refactor.** Extract `WorkspaceCache` + `WorkspaceLock` into
  `photos_utils`; add the JSON-artifact-dependency helper + shared no-clobber/zfs helpers. Prep
  behavior identical (its 200 tests green). *Prerequisite; no calibration code yet.*
- **Phase 1 — Skeleton + preflight (Stage 1).** `ingest/photos-2-time-gps` with the
  plan/dry-run/execute(/finalize) CLI, lifecycle guards, handoff load + SHA-256 verify, all by-dest
  scope gates, and the §13.1 re-prep blocker. Textual only — no JSON artifacts yet.
- **Phase 2 — Model + GPX + camera groups (Stages 2–4).** By-dest file objects from the
  handoff/cache; GPX load/parse/fingerprint (mine `GPXIndex`); camera-group recognition +
  camera/smartphone classification + unknown-group config snippets.
- **Phase 3 — Time decisions + offset inference (Stages 5–6, §17–21).** *The headline.*
  Per-destination time requirements; destination-timezone decisions; the ranking GPX/native-GPS
  anchor inference per (group,destination) with downward inheritance; the auto-resolution policy;
  `photos-21-time-decisions.json` + the decision-field/rerun-preservation engine.
- **Phase 4 — Resolved UTC (Stage 7, §22).** offset + timezone → UTC; persist the resolved-UTC
  cache table + its deterministic fingerprint.
- **Phase 5 — GPS decisions (Stage 8, §23–25).** GPX/photo-anchor interp/extrap engines (mined);
  the 7-option decision tree; the manual-GPS pre-state ledger (§24.1); `photos-22-gps-decisions.json`
  (per-destination summary; file paths only for review/blocker items).
- **Phase 6 — Executable plan + execution (Stages 9–10, §26–29).** destination-local no-clobber
  rename planner; `photos-23-executable-plan.json` (flattened deps + exact ops); execution
  (validate → zfs snapshot → atomic exiftool metadata writes + no-clobber renames re-verified at
  execute time → journal intent/confirm → idempotent crash-resume); `photos-24-execution-summary.json`.
- **Phase 7 — Finalize (Stage 11, §31).** `photos-25-complete-log.json` (prep log carried forward
  and extended), `photos-25-calibrate-ingest.db` snapshot, the archival package + manifest.

Large phases (especially 3, 5, 6) will likely split into sub-PRs at implementation time, as prep's
did.

---

## 4. Verification approach

Same discipline as prep: an `ingest/tests/` suite that loads the extensionless script via
`importlib.machinery.SourceFileLoader`, mocks exiftool/GPX where possible and runs real-tool
`@slow` integration tests, and holds the coverage gate. Each phase adds its own tests and keeps the
combined prep + calibration suite green.

---

## 5. Open questions to resolve as we build

- **SQLite ownership/schema:** calibration's resolved-UTC cache and manual-GPS pre-state ledger are
  new tables in the shared `photos-00-ingest.db` (disjoint from prep's, shared §13.4). Settle the
  exact table shapes in Phase 4 / Phase 5.
- **GPX library:** the monolith uses stdlib `xml.etree`; confirm that's sufficient (no extra dep)
  vs. `gpxpy`. Default: stdlib, to keep the no-dependency-manifest posture.
- **Timezone engine:** `zoneinfo` (stdlib, already used by `validate_config`) for IANA → UTC.
- **exiftool write path:** adopt the monolith's CSV-batch-write + read-back-verify pattern, made
  atomic + journaled on the calibration harness.
