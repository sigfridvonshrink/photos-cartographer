# Prep Workflow Specification (`photos-1-prep`)

## 1. Purpose

This document defines the complete, self-contained workflow for the preparation phase implemented by `photos-1-prep`.

The prep phase exists to take an unorganized workspace and leave it in a clean, deduplicated, date-organized state so the user can then move photos into the correct destination folders under `5-photos-by-dest`, after which the time/GPS calibration phase (`photos-2-time-gps`, see `10_photos-2-time-gps-workflow.md`) takes over.

The prep phase:

1. seeds the workspace configuration (`photos-00-config.json`) on first run if absent, then reads it as authoritative;
2. inventories the workspace safely and blocks on unsafe inputs;
3. consolidates loose files into a single staging folder;
4. normalizes file extensions;
5. separates redundant JPEGs that have a RAW sibling;
6. detects content duplicates and quarantines them recoverably;
7. organizes timestamped media into by-date folders, and untimestamped media into a missing-metadata folder;
8. maintains a SQLite hash/metadata cache so repeated runs are cheap and idempotent;
9. passively caches the EXIF/QuickTime/XMP facts the calibration phase will need, without making any time/GPS decision;
10. writes a dependency-fingerprinted handoff manifest for the calibration phase.

The prep phase ends when timestamped photos are in `4-photos-by-date` and videos in `3-videos-by-date`. Only the photos are then moved by the user into `5-photos-by-dest`; videos stay in `3-videos-by-date` and never enter by-dest (Section 2.4).

This is a workflow specification, not a script implementation specification. It describes *what* the prep phase does and the invariants it must uphold, not the staged build or class layout that implements it; those details live in the prep implementation/build notes and are out of scope here.

Cross-phase facts shared with calibration — the workspace lock, the pre-mutation snapshot (`zfs`) mechanism, the shared configuration object, the workspace control directory, the camera-group identity key, the filename timestamp format, the GPX root, and the end-to-end operator loop — are defined in `10_photos-shared-contract.md` and are authoritative there. This document references that contract rather than restating it.

---

## 2. Scope and boundary

### 2.1 Prep is prep-only

`photos-1-prep` owns filesystem organization, deduplication, cache/hash maintenance, passive metadata acceleration, and handoff generation. It must not plan, infer, write, or apply any time or GPS correction. The full prohibition list is in Section 20.

### 2.2 `5-photos-by-dest` is read-only for media

`photos-1-prep` scans and accounts for `5-photos-by-dest` but must never move, rename, quarantine, delete, touch, or metadata-write any file inside it (Section 11).

### 2.3 The end of prep is the start of calibration

Prep leaves organized media in `3-videos-by-date` and `4-photos-by-date`. The user then moves the **photos** from `4-photos-by-date` into destination folders under `5-photos-by-dest`; videos remain in `3-videos-by-date` and are never moved into by-dest (Section 2.4). Calibration (`10`) requires that `4-photos-by-date` contain no photos, that `5-photos-by-dest` be photo-only (no non-media files and no videos), and that no `jpg`/`tif` development subfolders exist under `5-photos-by-dest` before it will run. Prep itself does not perform that move and does not enforce the calibration preconditions; it only produces the by-date working set and the handoff. Crucially, when the user does move files into by-dest, the next prep run must recognize the move rather than rescan (Section 10.1); this re-prep is mandatory before calibrating the moved files, and applies every time new media enters by-dest — including after a prior successful calibration. The full cross-phase cycle is in the shared contract (`10_photos-shared-contract.md` Section 10).

### 2.4 Videos are semi-foreign

The pipeline's main target is **photos**. Videos are handled as **semi-foreign**: prep inventories, deduplicates, and date-organizes them into `3-videos-by-date`, and names them by date with the same convention as photos — but that is the extent of their special treatment. Videos are renamed naively (by their own timestamp) and otherwise left alone; in particular they are **not** time/GPS-calibrated downstream (calibration `10_photos-2-time-gps-workflow.md` Section 7.3). They are organized so they aren't lost or scattered, not because the pipeline aims to correct them.

Videos live **only** in `3-videos-by-date`. They must **never** appear in `4-photos-by-date` or `5-photos-by-dest`, and the user does not sort them into destinations. This is a hard invariant: a `video`-class file found in `4-photos-by-date` is a prep-side break (Section 6.1), and a video found under `5-photos-by-dest` is a calibration break (calibration Section 7.3). By-date and by-dest are photo-only (`image`/`raw`); the video band is separate and stays separate.

---

## 3. Workspace layout

Prep manages a fixed set of numbered folders under the workspace root, plus control directories.

```text
0-source/            staging for incoming/loose files            (mutable)
1-missing-metadata/  media with no usable timestamp              (mutable)
2-redundant-jpgs/    JPEGs that have a RAW sibling               (mutable)
3-videos-by-date/    timestamped videos, renamed by date         (mutable)
4-photos-by-date/    timestamped photos, renamed by date         (mutable)
5-photos-by-dest/    user-curated destinations                   (READ-ONLY)
```

Control / non-media paths (never treated as managed media). All pipeline control and artifact files live inside `.photos-ingest/`:

```text
.photos-ingest/                          all pipeline control & artifact files live here
  photos-00-config.json                  workspace config (seeded by prep)
  photos-00-workspace-guard              workspace guard / sentinel
  photos-00-ingest.db                    SQLite identity/metadata cache + derived caches (archived)
  journal-*.json                         execution journals
  photos-11-handoff.json                 prep-phase artifact: handoff manifest
  photos-21-time-decisions.json          calibration-phase artifact
  photos-22-gps-decisions.json           calibration-phase artifact
  photos-23-executable-plan.json         calibration-phase artifact
  photos-24-execution-summary.json       calibration-phase artifact
  photos-25-complete-log.json            calibration-phase artifact: transformation log (at finalize)
  gpx/                                    default gpx_root (calibration GPX tracks; not prep media)
.photos-ingest-quarantine/<plan_id>      recoverable duplicate quarantine
```

Because every control and artifact file lives under `.photos-ingest/`, prep skips that directory **wholesale** during its media scan — there is no per-file ignore list to maintain. The scanner must skip `.git`, `.photos-ingest/`, and `.photos-ingest-quarantine/` as whole subtrees, plus dotfiles. Nothing pipeline-related ever sits among managed media, so a control file can never be mistaken for a photo. GPX track files are calibration's alone and live under `gpx_root` (default `.photos-ingest/gpx/`, shared contract `10_photos-shared-contract.md` Section 8), inside the skipped control directory; should `gpx_root` be misconfigured to resolve inside the managed `0`–`5` tree, prep must skip that subtree too so GPX files are never organized. Prep is otherwise GPX-unaware — it does not read, parse, or fingerprint GPX.

The mutable/immutable status of each folder is recorded in the handoff manifest (Section 16).

The SQLite database (`photos-00-ingest.db`) is not throwaway scratch: besides serving as the hash/metadata cache that makes runs cheap and idempotent, it is part of the durable record of what the pipeline knows about the archive, and it is bundled into the archival package on finalize (shared contract `10_photos-shared-contract.md` Section 13.4). Prep is the sole writer of its cache/identity content (hashes, metadata, move-aware history) through the controlled single-writer path (Section 14.3); calibration writes only its own derived regions of the database (the resolved-UTC cache and the manual-GPS pre-state ledger, calibration Section 24.1), which are disjoint from prep's. The two never write the same rows.

The workspace configuration, `photos-00-config.json`, is defined authoritatively in the shared contract (`10_photos-shared-contract.md` Section 4). Prep seeds it: on a run, if the file is absent prep creates it in `.photos-ingest/` from the in-code default template (`photos_utils.CONFIG`); if present, prep reads it as-is and treats the workspace copy as authoritative for all processing in that workspace. Prep is the sole writer of the file (it only seeds it once); the user changes configuration by hand-editing the JSON, and calibration reads it but never writes it. Its field-scoped fingerprints feed dependency staleness (so a config edit invalidates only the artifacts that depend on the changed area), and its whole-file SHA-256 is recorded for integrity and archived in the package. Seeding happens at the start of the run, before any config-dependent fingerprint is computed, so that all fingerprints (and the handoff's recorded config hash) are derived from the on-disk `photos-00-config.json`, never from the in-code defaults directly — on a first run the freshly seeded file is the thing fingerprinted.

---

## 4. Core workflow rule

Prep is a plan/execute workflow with strict separation:

```text
Plan (non-mutating).
Validate the plan against current state.
Execute only the validated plan.
Journal every mutation.
Update the cache from the validated plan + journal + final filesystem state.
Write the handoff manifest only after success.
```

Invariants that hold at every gate:

1. planning is non-mutating — it touches no media, no SQLite, no manifest;
2. dry-run reports the exact serialized plan that would execute;
3. execution revalidates the plan before any mutation and rejects stale plans;
4. all media operations are no-clobber;
5. all media mutations are journaled;
6. `5-photos-by-dest` is never a mutation source or target;
7. no downstream artifact is created from stale upstream inputs (Section 5).

Execution never re-derives organization decisions. It applies only the operations already recorded in the plan, after validation.

---

## 5. Artifact dependency cascade

Every durable artifact follows the same discipline:

```text
validate upstream -> create artifact -> record dependencies in it -> reject downstream use if dependencies changed
```

For prep, the cascade is:

```text
workspace config (photos-00-config.json) / CLI options
  -> workspace inventory snapshot
  -> SQLite/cache precondition state
  -> hash + metadata freshness decisions
  -> prep plan
  -> execution journal
  -> updated SQLite cache
  -> photos-1-prep handoff manifest
```

Durable artifacts (plan, journal, SQLite cache, handoff) must carry a `depends_on` block (or equivalent) recording the upstream fingerprints they relied on. Intermediate items (inventory snapshot, freshness maps) are internal pipeline state of a single run, not independently revalidated artifacts.

At minimum the recorded fingerprints include:

1. config fingerprint;
2. CLI-options fingerprint where options affect planning;
3. per-file preconditions (size, mtime) for files involved in operations;
4. SQLite schema/cache version;
5. hash algorithm/version;
6. metadata extractor name + version, field-set version, extraction-options fingerprint, metadata-schema version, camera-group-key version;
7. by-dest read-only preconditions for any by-dest file that influenced a decision;
8. final workspace/cache fingerprint (handoff only).

If any recorded dependency is stale, missing, or unverifiable, the script blocks before creating or using the downstream artifact.

---

## 6. Media classification and input guards

### 6.1 Media classes

Each file is classified by extension:

```text
image : jpg jpeg png heic tiff
raw   : cr2 cr3 nef arw dng
video : mp4 mov avi mkv
other : everything else
```

`other` files are carried in the cache as `not_applicable` for metadata and are not date-organized.

Photos (`image`/`raw`) and videos are organized into **separate bands** that never mix: photos into `4-photos-by-date` (then by-dest), videos into `3-videos-by-date` (and nowhere else). A `video`-class file found under `4-photos-by-date` or `5-photos-by-dest`, or an `image`/`raw` file found under `3-videos-by-date`, is a misplacement the pipeline must not tolerate: prep treats a video under `4-photos-by-date` as a hard break (it reports the offending path and does not proceed), and a video under `5-photos-by-dest` is a calibration-side break (calibration `10_photos-2-time-gps-workflow.md` Section 7.3). Prep's own routing never places a video into the photo band; this guard catches a video that arrived there by other means (e.g. a hand-move).

### 6.2 Hard input guards (block before any operation)

Planning must block, producing no executable plan, if it finds:

1. a symlink among managed files (forbidden);
2. a forbidden sidecar (`.xmp`, `.dop`, `.pp3`) — editing sidecars are not part of this pipeline;
3. a content hash failure for any non-by-dest media file whose content equality a decision depends on (Section 11.3);
4. a band misplacement — a `video`-class file under `4-photos-by-date` or `5-photos-by-dest`, or an `image`/`raw` file under `3-videos-by-date` (Section 6.1). Prep never creates such a placement itself; this guard catches one introduced by hand.

Blockers are reported textually; the workflow does not silently skip them.

---

## 7. The prep pipeline

Planning derives operations in a fixed, deterministic order. Each stage updates an in-memory "current path" for every file so later stages reason about where a file will be, not only where it is. Allowed operation types are:

```text
mkdir, move_no_clobber, rename_no_clobber, quarantine_move, db_upsert, db_remove
```

### 7.1 Stage 0 — Inventory and guards

Scan the workspace root (top-level loose files) and every managed folder. Apply the guards of Section 6.2. Split the inventory into **mutable-side files** (everything outside `5-photos-by-dest`) and **read-only by-dest files**.

### 7.2 Stage 1 — Consolidate loose files into `0-source`

**How media enters the workspace (the "dump").** The user adds material by dumping folders and files into the **base of the workspace** and/or directly into `0-source/`. "Dump" means exactly this: drop arbitrary files and folder trees in either location, in any structure. The user is not expected to pre-organize, rename, or sort them. A single workspace may receive one or many dumps over time (shared contract `10_photos-shared-contract.md` Section 10).

Stage 1 consolidates that material: any media file sitting loose at the workspace root — or anywhere outside the managed `0`–`5` folders and the skipped control/quarantine directories — is moved into `0-source/` (no-clobber, case-insensitive collision-safe), flattening dumped folder trees as needed. Files already inside a managed folder are left where they are at this stage. Non-media (`other`-class) files dumped in are not organized (Section 6.1) and remain where prep leaves them; they never block prep.

### 7.3 Stage 2 — Normalize extension case

A file whose extension is not lowercase (e.g. `.JPG`, `.ARW`) is renamed to the lowercase form. To stay safe on case-insensitive filesystems this is done as two no-clobber renames (to a unique temporary name, then to the final lowercase name). Collisions are resolved by suffix allocation (Section 8).

### 7.4 Stage 3 — Separate redundant JPEGs

Files are grouped by `(folder, basename-without-extension)`. If a group contains both a RAW and a `.jpg`, the JPEG is considered redundant (the RAW is the master). A redundant JPEG that is in `0-source` is moved to `2-redundant-jpgs/`. Paired JPEGs are excluded from the content-dedup stage so a RAW+JPEG pair is never treated as a duplicate of itself.

### 7.5 Stage 4 — Content deduplication and quarantine

Remaining files (mutable-side **and** by-dest, excluding paired JPEGs) are grouped by `(content_hash, media_class)`. Within a group of more than one file:

1. one file is **retained**, chosen by folder priority — by-dest wins, then the more-organized folder:

```text
5-photos-by-dest  >  4-photos-by-date  >  3-videos-by-date
                  >  2-redundant-jpgs  >  1-missing-metadata  >  0-source
```

2. every other copy on the mutable side is moved to `.photos-ingest-quarantine/<plan_id>/<original-path>` via `quarantine_move`;
3. a by-dest copy is **never** quarantined (it can only ever be the retained file);
4. quarantine is recoverable: each quarantined file gets a manifest entry recording its original path, quarantine path, the retained counterpart, and the duplicate evidence (Section 15);
5. files with unknown/invalid hashes are not grouped as duplicates (Section 11.3).

### 7.6 Stage 5 — Chronological organization

Every mutable-side file still in `0-source` (not already routed to `1`–`5` and not quarantined) is organized by its source timestamp. The timestamp is read passively from cached metadata in priority order:

```text
DateTimeOriginal -> CreateDate -> ModifyDate
```

Routing:

```text
valid timestamp + video  -> 3-videos-by-date/
valid timestamp + photo  -> 4-photos-by-date/
no valid timestamp       -> 1-missing-metadata/
```

The timestamp used here is the raw camera-naive value, used only for organization and ordering. Prep does **not** correct it, resolve a timezone, or convert to UTC — that is calibration's job.

**How files leave `1-missing-metadata`.** Prep cannot invent a timestamp, so a file with no usable one lands in `1-missing-metadata` and stays there until **the user supplies the missing metadata** (e.g. sets `DateTimeOriginal` in the file). Resolving these is the user's responsibility, not the pipeline's. Once the user has fixed a file, they move it back to the workspace base or `0-source` — at which point it is simply an **additional dump** (Section 7.2): the next prep run re-inventories it, and because its size/mtime changed (the metadata edit) it is re-hashed and re-extracted, now has a valid timestamp, and is routed normally to `4-photos-by-date` (or `3-videos-by-date`). Prep provides no special "re-import from missing-metadata" path; the file just flows through the ordinary pipeline as any dumped file does. A file left in `1-missing-metadata` is residual and never blocks calibration (calibration `10_photos-2-time-gps-workflow.md` Section 7).

### 7.7 Stage 6 — Cache reconciliation

For files that were not mutated and whose cache record is stale (changed size/mtime or stale metadata), a `db_upsert` records the refreshed state. Before treating a cached file whose path has disappeared as a ghost, prep applies the move-recognition rule of Section 10.1: a disappearance explained by a matching new by-dest entry is a move (cache carried forward), not a ghost. Genuinely missing cache rows are pruned with `db_remove` (ghost prune). Unchanged, already-fresh files produce no operation and are reported as `no_op` / `already_correct`.

---

## 8. Naming conventions

Date-organized names follow the project standard and are derived from the source-naive timestamp:

```text
3-videos-by-date / 4-photos-by-date :  YYYY-MM-DD--HH-MM-SS-NNN.ext
1-missing-metadata                  :  UNKN_<original-base>-NNN.ext
```

`-NNN` is a zero-padded differentiating suffix (`-001`, `-002`, …) allocated deterministically against a per-run, case-insensitive, monotonic index (only grows, from the current highest), so two files never collide and ordering is stable. Extensions are normalized to lowercase (Section 7.3). The timestamp shape and the differentiating-suffix convention are defined once in the shared contract (`10_photos-shared-contract.md` Section 7); prep reads the same shared `filename_timestamp_format` key as calibration.

The timestamp component (`YYYY-MM-DD--HH-MM-SS`) is the raw camera-naive value, used here only for organization and ordering. It shares the same textual format as the final filename calibration assigns later (`10` Section 26 / shared contract Section 7.3), but the value is **provisional**: calibration recomputes it from corrected, destination-local civil time and rewrites the name. Prep does not correct, timezone-resolve, or UTC-convert the timestamp.

> Both prep and calibration use the same `filename_timestamp_format` (shared contract `10_photos-shared-contract.md` Section 7). A pre-existing file whose name does not match the convention is treated as an ordinary dump and re-ingested — prep never parses meaning from a non-conforming filename; the timestamp comes from metadata.

---

## 9. Hashing and cache reuse

Hashes back the duplicate and content-uniqueness checks and are persisted in SQLite.

1. if a path exists in the cache with unchanged size and mtime (and fresh metadata context), reuse the cached content hash;
2. if a file is absent from the cache, hash it and store the result;
3. if size or mtime changed, treat the cached hash as stale and recompute;
4. if prep moves or case-normalizes a file without changing content, carry the known hash forward to the new workspace-relative path (Section 10);
5. a hash failure never implies equality;
6. an unknown hash blocks any decision that depends on content equality;
7. the hash algorithm is recorded in the cache and handoff.

---

## 10. Move-aware cache identity

The cache must distinguish: same content at a new path because of a move; same path with changed content; different path and different content; duplicate content already in by-dest; duplicate content already quarantined.

Each planned move/rename carries enough to update the cache row without rehashing after the move: source path, destination path, source size, source mtime, source hash if known, the post-move expected path, the post-move cache action, and the dependency facts proving the carried-forward hash is still valid. Cache updates are derived from the validated plan and applied during execution, never speculatively during planning.

### 10.1 Recognizing manual moves from by-date into by-dest

After prep organizes media into `3-videos-by-date`/`4-photos-by-date`, the user moves **photos** from `4-photos-by-date` into destination folders under `5-photos-by-dest` (videos are not moved; Section 2.4). On the next prep run those photos appear at a new by-dest path and are absent from their old by-date path. Prep must recognize this as a move and must **not** re-hash or re-extract metadata for the moved file.

Detection is cache-only — no file re-read beyond `stat`:

1. a previously cached mutable-side file (typically under `4-photos-by-date`/`3-videos-by-date`) is now missing from its cached path; and
2. a by-dest file that was not previously cached now exists whose `stat` (size and `mtime_ns`) and basename match that missing file.

On a unique match, prep treats it as a move: it carries the cached content hash and metadata record forward to the new by-dest path (move-aware identity), drops the stale old cache row, and records the new by-dest row from the carried-forward facts. Because `5-photos-by-dest` is read-only, prep performs **no** filesystem operation — it only fixes its cache and the handoff manifest to reflect the new location.

Safety:

1. if more than one missing file could match (ambiguous size/mtime/basename), or the move did not preserve mtime, prep does not guess: it treats the by-dest file as a normal newly-seen by-dest file and scans it (Section 9), and the old row is ghost-pruned;
2. carried-forward identity never overrides a content change — if the by-dest file's size/mtime differ from the cached source, it is rescanned;
3. move recognition only updates prep's own cache/handoff; it never mutates by-dest media.

This makes the round trip cheap: after the user sorts the by-date working set into by-dest, re-running prep does not re-hash or re-read the moved files — it simply fixes the handoff.

### 10.2 Recognizing moves between destinations (re-sort within by-dest)

The user may also move an already-placed file from one destination to another inside `5-photos-by-dest` (e.g. correcting a mis-sort: `Belgium/Brussels` → `Belgium/Bruges`). Prep must recognize this the same cache-only way: a previously cached by-dest file is now missing from its cached by-dest path, and an uncached by-dest file with matching `stat` and basename now exists at a different by-dest path. On a unique match, prep carries the cached identity forward to the new by-dest path, drops the old row, and updates the handoff to record the new destination — performing **no** filesystem operation (by-dest is read-only).

This matters because a file's **destination is a calibration input**: the destination civil timezone is destination-scoped (calibration `10_photos-2-time-gps-workflow.md` Section 18). When prep moves a file's recorded destination, the handoff changes, which (via the dependency cascade) restales the affected destination decisions so calibration **re-evaluates** the moved file under its new destination rather than silently keeping the old destination's timezone (calibration Section 18.1). As with all by-dest moves, the mandatory re-prep after the move applies (shared contract `10_photos-shared-contract.md` Section 10), and the same ambiguity safety as Section 10.1 holds (ambiguous matches are treated as new files and rescanned).

---

## 11. Uniqueness and duplicate rules involving by-dest

### 11.1 Content duplicate against by-dest

If a mutable-side file has the same content hash as a *different* by-dest file (i.e. not the same file recognized as moved per Section 10.1), it is classified as a duplicate against existing by-dest content. The by-dest file is the retained copy; only the mutable-side file is acted on (quarantined). The relationship is recorded in the summary, journal, and handoff.

### 11.2 Path conflict against by-dest

If a planned destination path would collide with an existing by-dest path (including case-insensitively), prep must not clobber it: it allocates a safe alternative name where the operation class allows, otherwise it blocks. The by-dest file is never touched.

### 11.3 Unknown hashes

If either side of a potential duplicate has an unknown hash (hash failure), prep must not classify it as a content duplicate and must not remove or quarantine based on equality. For a mutable-side file this is a blocker; for a by-dest file it is skipped (by-dest is read-only and never quarantined regardless).

By-dest inventory facts that influenced any decision are recorded in the plan dependencies, so execution rejects the plan if by-dest state changed in a way that affects uniqueness decisions.

---

## 12. Passive metadata acceleration

Because prep already opens every file for hashing and organization, it caches the EXIF/QuickTime/XMP facts the calibration phase will need, so calibration can avoid re-reading unchanged files. This is strictly passive: prep stores facts, makes no time/GPS decision, and corrects nothing.

Cached per file (raw values plus clearly-labelled parsed helpers):

1. **camera/device identity**: `Make`, `Model`, `UniqueCameraModel`, `BodySerialNumber`, `CameraSerialNumber`, `InternalSerialNumber`, `SerialNumber`, `OwnerName`, lens model/serial, and a derived `camera_group_key`;
2. **timestamps (uncorrected)**: `DateTimeOriginal`, `CreateDate`, `ModifyDate`, sub-second and offset/timezone fields, XMP/IPTC `CreateDate`/`ModifyDate`/`DateCreated`, and the QuickTime `*CreateDate`/`*ModifyDate`/`Track*`/`Media*` family, plus the selected source-naive timestamp and its provenance;
3. **native GPS (uncorrected)**: presence flag, `GPSLatitude(Ref)`, `GPSLongitude(Ref)`, parsed signed decimals where safe, `GPSAltitude(Ref)`, `GPSDateStamp`, `GPSTimeStamp`, `GPSDateTime`, `GPSProcessingMethod`;
4. **normalized media facts**: folder class, extension, normalized extension, media kind, dimensions, orientation, rotation, video duration;
5. a raw metadata payload (or at least the raw values for the requested field set) so future fields can be added without re-reading unchanged files.

### 12.1 Metadata freshness

A cached metadata record is reusable only when all freshness inputs still match: path (or move-aware identity, Section 10.1), size, mtime, content hash if available, extractor name, extractor version, field-set version, extraction-options fingerprint, metadata-schema version, and camera-group-key version. Changing the field set or extractor in a future release makes existing records detectably stale without being confused with content changes.

### 12.2 Passive grouping facts

The handoff/summary reports passive grouping facts for later use, with no inference: per camera group (key, file count, contributing identity fields, earliest/latest source-naive timestamp, native-GPS counts, missing/ambiguous-timestamp count, and phone/camera class only if already known from config) and per by-dest folder (path, files scanned, camera groups present, timestamp range, native-GPS/missing-GPS/GPSProcessingMethod counts, cache-freshness summary, and conflicts/duplicates involving files outside by-dest).

---

## 13. Idempotency and incremental operation

Prep upholds the shared idempotency principle — change only what needs changing; a no-op run is a no-op (shared contract `10_photos-shared-contract.md` Section 11). Concretely: a second run on an unchanged workspace must produce zero media mutations. Prep must:

1. tolerate already-populated by-date and by-dest folders;
2. recognize files already in their correct location and not move them;
3. not re-normalize already-normalized extensions;
4. not re-quarantine already-quarantined duplicates;
5. produce the same destination names for the same unchanged input state;
6. reuse cached hashes and metadata for unchanged files;
7. recognize files the user moved from by-date into by-dest and carry their cache identity forward without re-hashing or re-extracting (Section 10.1);
8. report `no_op` / `already_correct` facts rather than treating prior work as error.

When new files appear in a mutable folder after a previous run, a new plan acts only on the files that require action; existing by-date/by-dest files are still scanned for uniqueness/cache freshness but are not moved or rehashed unnecessarily.

---

## 14. Plan / dry-run / execute lifecycle

The whole prep run — `plan`, `dry-run`, and `execute` alike — runs under the single workspace-wide lock acquired at process startup and held until exit (shared contract `10_photos-shared-contract.md` Section 2). Planning and dry-run are non-mutating but still run inside the lock, so no two pipeline processes (of either phase) ever overlap. The steps below therefore assume the lock is already held; they do not re-acquire or independently scope it.

### 14.1 Plan

`plan` produces a serialized plan containing: plan id, plan/schema version, command, config fingerprint, the ordered operation list, blockers, warnings, per-file workspace preconditions (with role `no_op_prepared` or `by_dest_read_only`), metadata dependencies, and a summary (no-op count, operations planned, blockers, per-file metadata plan status). Planning mutates nothing.

### 14.2 Dry-run

`dry-run` validates and reports the exact plan that would execute, without mutating.

### 14.3 Execute

`execute` applies the validated plan. It must:

1. confirm the workspace lock is held and the root sentinel verified (both established at run start per shared contract Section 2);
2. revalidate every recorded dependency and per-file precondition; reject the plan before any mutation if stale, missing, or unverifiable, or if the plan was produced by a different tool/version/schema;
3. take a pre-mutation snapshot where configured (the `zfs` block in config), honoring `snapshots_required`;
4. apply only the planned operations, each no-clobber;
5. journal every operation (move, rename, quarantine, cache write) with its result;
6. write the quarantine manifest for any quarantined file;
7. update SQLite/cache from the validated plan and journal in a single controlled writer/transaction after verification;
8. write the handoff manifest only on overall success (Section 16);
9. emit the summary (the workspace lock is released at process exit per shared contract Section 2, not as a step of `execute`).

Execution must not patch or recompute a stale plan, and SQLite writes must never come from uncontrolled worker threads.

### 14.4 Execution idempotency and resume

Prep execution must be safe to re-run after a crash or partial application. Prep upholds the shared idempotency principle (shared contract `10_photos-shared-contract.md` Section 11): a crashed or interrupted run leaves the workspace in a state the next run can finish without redoing completed work and without double-applying anything.

**Prep re-plans; it does not resume the old plan.** This is a deliberate difference from calibration, which resumes the *same* `photos-23-executable-plan.json` because that plan embeds irreplaceable human decisions (calibration Section 29.1). Prep embeds no human decisions — it derives organization purely from filesystem and cache state — so after a crash the next invocation discards the interrupted plan and **plans afresh from the current workspace state**. Because every prep operation is idempotent by target state (a file already moved, already case-normalized, already separated, or already quarantined is detected as already-correct and produces a `no_op`/`already_correct`, per Section 13), re-planning naturally proposes only the operations still outstanding and completes the remaining work without repeating finished work. A stale interrupted plan is never patched or resumed; it is simply superseded (consistent with Section 14.3's rejection of stale plans).

**The filesystem is the source of truth; the cache is reconciled to it.** The one genuinely hazardous interval is a crash *between* a filesystem mutation and its corresponding cache write, leaving SQLite and the filesystem disagreeing (e.g. a move applied on disk whose `db_upsert` never committed, or a `db_remove` that committed before the file was actually moved). On the next run, inventory treats the filesystem as authoritative:

1. a cached row whose file is not where the cache says — but is explained by a completed on-disk move — is reconciled via the move-aware identity and ghost-prune rules (Sections 7.7, 10, 10.1), not trusted blindly;
2. where stat/identity cannot prove the cached hash still valid, the affected file is re-stat'd/re-hashed rather than relying on a possibly-stale cache row;
3. the controlled single-writer cache update (Section 14.3 step 7) commits only after the corresponding filesystem effect is verified, so a fresh run converges the cache back to filesystem truth.

**The journal supports reconciliation and observability, not blind replay.** Every mutation is journaled (Section 14.3 step 5), and the journal records what the interrupted run had done, which aids reconciliation and auditing. But prep does not replay the journal to "continue" the old plan — recovery is re-plan-from-current-state, with the journal as evidence, not as a script to resume.

**Snapshot rollback is the heavy-hammer option.** Where a pre-mutation ZFS snapshot was taken (Section 14.3 step 3; shared contract Section 3), the operator may roll the workspace back to its pre-run state and start over, instead of relying on forward reconciliation. This is the clean-slate recovery path when a partial run's state is easier to discard than to reconcile.

A successful prep run still writes the handoff manifest only as the final step (Section 14.3 step 8 / Section 16); a crash before that leaves no handoff (or the prior run's handoff), so calibration will not act on an incomplete prep run.

---

## 15. Quarantine model

Duplicate removal is recoverable, never destructive. Each duplicate is moved (not deleted) under `.photos-ingest-quarantine/<plan_id>/` preserving its original relative path, and a manifest records, per item: original path, quarantine path, retained counterpart, duplicate evidence (the content hash), and the plan id. The quarantine directory is excluded from scanning, so re-running prep neither re-organizes nor re-quarantines already-quarantined files.

### 15.1 Retention

Quarantine is the recoverable safety net for de-duplication, so prep **never deletes quarantined files automatically**. No run — however many times prep is re-run, and regardless of age — removes anything under `.photos-ingest-quarantine/` on its own. Quarantined copies persist until the user explicitly removes them (Section 15.3). This means quarantine grows monotonically across runs by design; the trade-off is accepted in exchange for never silently destroying a file that de-duplication set aside.

### 15.2 Recovery (manual restore)

A user may recover a quarantined file at any time by moving it out of `.photos-ingest-quarantine/` back into a managed folder (typically `0-source/`). Prep does not provide a dedicated "un-quarantine" operation and does not track such a move as a special case; the restored file is simply re-evaluated as a normal newly-seen file on the next run:

1. it is inventoried, hashed, and metadata-extracted like any other new mutable-side file;
2. it flows through the ordinary pipeline (extension normalization, redundant-JPEG separation, content de-duplication, chronological organization);
3. if its content still duplicates a retained copy (mutable-side or by-dest), de-duplication will quarantine it again — into the **current** run's `<plan_id>` directory, not the original one. This is safe and predictable: restoring a still-duplicate file simply re-quarantines it;
4. if the previously retained counterpart no longer exists (the user deleted or moved it), the restored file is no longer a duplicate and is organized normally.

Prep does not attempt to reconcile the old quarantine manifest entry with the restored file; the old entry remains as a historical record of that earlier plan, and the new disposition is recorded under the new run. The user is responsible for not leaving a file in two places (restored *and* still under quarantine); because the quarantine tree is excluded from scanning, a copy left behind under quarantine is neither re-organized nor counted as a live duplicate.

### 15.3 Pruning and reporting

Because quarantine is never auto-deleted, prep makes its growth visible and provides an explicit, opt-in way to reclaim the space:

1. **Reporting (every run):** the user-visible summary reports the current quarantine footprint — total quarantined files, total size, number of distinct `<plan_id>` directories, and the oldest/newest plan id present — so the user always knows quarantine is accumulating and by how much (Section 19).
2. **Explicit prune command:** prep exposes a `prune-quarantine` command that deletes quarantined files. It is the only operation that removes quarantine contents, it is never invoked implicitly by `plan`/`dry-run`/`execute`, and it acts only within `.photos-ingest-quarantine/`. It supports at least selecting by `<plan_id>` and/or by age, defaults to a non-destructive dry-run that lists what would be removed, and requires explicit confirmation (or an explicit `--yes`/equivalent) before deleting. It never touches live managed folders or `5-photos-by-dest`, and it runs under the same workspace lock as every other pipeline operation (shared contract `10_photos-shared-contract.md` Section 2).

Pruning is the user's decision, not the pipeline's: prep surfaces the cost and offers the tool, but the recoverable copies stay until the user chooses to discard them.

---

## 16. Handoff manifest

After a successful run, prep writes a machine-readable, non-editable handoff manifest at:

```text
.photos-ingest/photos-11-handoff.json
```

It is written only after the validated plan executed, the journal is complete, the final filesystem matches expected postconditions, and the SQLite/cache state matches the filesystem. It must include at least:

1. schema version and tool name (`photos-1-prep`);
2. plan id (and execution id where applicable);
3. cache fingerprint and hash algorithm;
4. folders scanned with mutability flags;
5. a sorted file list with workspace-relative path, size, mtime, hash status, folder class, and per-file metadata status;
6. camera groups and by-dest destination-folder facts (Section 12.2);
7. metadata field-set/extractor versions and per-file metadata cache status;
8. duplicates/conflicts/blockers and warnings;
9. a `depends_on` block recording the upstream fingerprints used to create it.

The manifest must be deterministic for a given workspace state (sorted lists, no reliance on unordered iteration), with run-metadata timestamps separated from fingerprints. The manifest is the contract consumed by `photos-2-time-gps` (`10` Section 13), which treats it as a first-class SHA-256 dependency — re-hashing its exact bytes before use (`10` Section 4) — so prep must write it deterministically and never edit it in place. It lives in `.photos-ingest/`, which prep skips wholesale, so prep never inventories or fingerprints it as media (shared contract `10_photos-shared-contract.md` Section 5). When the only change since the last run is the user moving photos (from by-date into by-dest, or re-sorting between destinations within by-dest), the handoff is updated to reflect the new locations using carried-forward cache identity (Sections 10.1, 10.2), without re-reading the moved files.

---

## 17. Concurrency, determinism, and observability

Expensive work (hashing, metadata extraction) may run concurrently under `-j` / `--jobs`, but concurrency must never change semantic results:

1. filesystem traversal and stat collection are single-threaded and deterministic, fixing the candidate list before any concurrent work;
2. candidate lists are sorted before submission and worker results aggregated deterministically;
3. two safe job counts produce the same semantic plan and the same dependency fingerprints for the same workspace;
4. SQLite writes go through a single controlled writer / collect-then-write transaction, never from worker threads;
5. external tools (`exiftool`, `magick`) use persistent-worker patterns rather than per-file spawning, with safe restart on crash; partial/failed worker output is never persisted as a valid cache record and becomes a clear blocker;
6. job count is run metadata, not a semantic dependency, unless it genuinely changes planned behaviour.

Long-running execution is visible: phase-level log lines (lock, validate, scan, hash, extract, dedup, apply, cache update, handoff, release) and live aggregate progress for concurrent hashing/metadata, with in-place updates on a TTY and periodic plain lines when output is redirected. Progress output is never the only record of a mutation — the journal is durable; progress is transient and never a dependency.

---

## 18. End state and handoff to calibration

A successful prep run leaves:

```text
4-photos-by-date/    timestamped photos, date-named, deduplicated
3-videos-by-date/    timestamped videos, date-named, deduplicated
2-redundant-jpgs/    JPEGs whose RAW master is retained
1-missing-metadata/  media with no usable timestamp
0-source/            empty (or only files still pending, incl. other-class non-media)
5-photos-by-dest/    unchanged (read-only)
.photos-ingest/photos-11-handoff.json   written
```

Residual `other`-class non-media files legitimately remain in `0-source` — prep does not organize them — and this is an expected, non-blocking end state; calibration tolerates such residuals (calibration `10` Section 7).

The user then reviews `4-photos-by-date` and moves the **photos** into the appropriate destination folders under `5-photos-by-dest` (videos stay in `3-videos-by-date` and are never moved into by-dest, Section 2.4). The user moves **only photos** into by-dest: calibration requires `5-photos-by-dest` to contain photo files exclusively and hard-stops on any non-photo file — non-media or video — found there (calibration `10` Sections 7.2, 7.3). Once the move is complete — `4-photos-by-date` empty, by-dest photo-only, and no `jpg`/`tif` development subfolders present under `5-photos-by-dest` — the calibration phase (`10`) may run.

Re-running prep after the user's move must **not** re-hash or re-read the moved files: prep recognizes them as moved (Section 10.1), carries their cached hash/metadata forward to the new by-dest path, and simply updates the cache and handoff. by-dest media is never touched. Prep neither performs the move nor enforces the calibration preconditions.

---

## 19. User-visible outputs

Prep produces a textual summary that lets a reviewer confirm safety and progress, clearly separating:

1. media operations planned/executed;
2. no-op / already-correct files;
3. files scanned only for uniqueness/cache;
4. by-dest files scanned read-only (and confirmation by-dest was not mutated);
5. files recognized as moved from by-date into by-dest (cache carried forward, not rescanned);
6. duplicates against mutable folders vs. against read-only by-dest;
7. cache records reused, hashes recomputed, hashes carried forward after moves, cache records updated;
8. metadata records reused/extracted/failed, field-set and extractor versions;
9. camera groups found; native-GPS and missing/ambiguous-timestamp counts;
10. blockers (symlinks, forbidden sidecars, hash failures, stale dependencies) and warnings;
11. confirmation that durable artifacts were written only after dependency validation;
12. the current quarantine footprint — total quarantined files, total size, number of distinct `<plan_id>` directories, and oldest/newest plan id present — since quarantine is never auto-deleted and grows across runs (Section 15.3).

---

## 20. Non-goals (prep must not do)

`photos-1-prep` must not expose behaviour for:

1. calibration JSON generation or validation;
2. camera-time policy or folder-timezone decisions;
3. GPX matching/interpolation/extrapolation;
4. manual GPS fallback planning;
5. time-offset calculation;
6. EXIF/QuickTime timestamp write planning or execution;
7. GPS metadata write planning or execution;
8. `GPSProcessingMethod` marker writes;
9. rename/relocation caused by corrected timestamps;
10. any `calibrate` command.

Passive extraction and caching of fields the calibration phase will need (Section 12) is allowed and required; making decisions from them is not.

---

## 21. Idempotency and staleness examples

```text
Second run, unchanged workspace
  -> no media operations
  -> cache hits reported, handoff unchanged

New file added to 0-source
  -> only the new file is hashed/extracted and organized
  -> existing files scanned for uniqueness/cache only

User restored a file out of quarantine into 0-source
  -> re-evaluated as a normal new file (no special "un-quarantine" path)
  -> if it still duplicates a retained copy, re-quarantined under the
     current plan_id; otherwise organized normally
  -> old quarantine manifest entry left as historical record

User moved a file from 4-photos-by-date into 5-photos-by-dest
  -> recognized as a move (matching size/mtime/basename)
  -> cached hash/metadata carried forward, no rescan
  -> old cache row dropped, handoff updated; by-dest untouched

File size/mtime changed
  -> cached hash + metadata stale -> recompute

Config changed
  -> config fingerprint changes -> plan dependency stale
  -> a previously generated plan is rejected at execute time

By-dest file changed before execute (affecting a uniqueness decision)
  -> recorded by-dest precondition stale -> plan rejected before mutation

Hash failure on a mutable-side media file
  -> equality-based duplicate decision blocked -> reported blocker

Symlink or .xmp/.dop/.pp3 sidecar present
  -> hard block, no executable plan produced
```

---

## 22. Summary

This section restates the rules established above as a single reference. On any apparent conflict, the numbered specification sections above govern over this summary.

The prep workflow is:

```text
1. Inventory the workspace; block on symlinks and forbidden sidecars.
2. Reuse cache for unchanged files; recognize by-date -> by-dest moves;
   hash + extract metadata only for genuinely new/changed files.
3. Consolidate loose files into 0-source.
4. Normalize extension case (lowercase, collision-safe).
5. Separate redundant JPEGs (RAW master retained) into 2-redundant-jpgs.
6. Deduplicate by content hash; quarantine extra copies recoverably;
   by-dest is always the retained copy and is never mutated.
7. Organize by source-naive timestamp:
   videos -> 3-videos-by-date, photos -> 4-photos-by-date,
   untimestamped -> 1-missing-metadata.
8. Reconcile the SQLite cache (move carry-forward, upserts, ghost prune).
9. Execute only the validated plan: lock, snapshot, no-clobber ops, journal,
   controlled cache update.
10. Write the dependency-fingerprinted handoff manifest on success.
```

The most important rules are:

```text
Plan, validate, execute, journal — never re-decide at execution time.
5-photos-by-dest is read-only; by-dest always wins a duplicate tie.
A file moved into by-dest is recognized, not rescanned — just fix the handoff.
All media operations are no-clobber; duplicate removal is recoverable quarantine.
Prep caches time/GPS-relevant facts passively but makes no time/GPS decision.
No durable artifact is created from stale upstream inputs.
```

Prep ends with media organized into by-date, ready for the user to place into `5-photos-by-dest` before calibration (`10_photos-2-time-gps-workflow.md`) begins.
