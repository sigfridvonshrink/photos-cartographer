# Prep Workflow Specification (`photos-1-prep`)

## 1. Purpose

This document defines the complete, self-contained workflow for the preparation phase implemented by `photos-1-prep`.

The prep phase exists to take an unorganized workspace and leave it in a clean, deduplicated, date-organized state so the user can then move photos into the correct destination folders under `6-photos-by-dest`, after which the geotag phase (`photos-2-geotag`, see `photos-2-geotag-workflow.md`) takes over.

The prep phase:

1. **initializes** the workspace on first run — creating the `0`–`6` folder structure and control directory, moving any as-arrived base dump into `0-sources/`, and writing the root sentinel last (Sections 3.1, 7.1);
2. seeds the workspace configuration (`photos-00-config.json`) on first run if absent, then reads it as authoritative;
3. inventories the workspace safely and blocks on unsafe inputs (a sealed workspace; a misplaced root entry — loose file, non-managed folder, or symlink — on an initialized workspace; a missing managed folder; or a symlink anywhere among managed files, including nested directory symlinks, Section 6.2);
4. takes each dump from `0-sources/` (the one inbox) without flattening it, resolving destination-name collisions in memory at planning (Section 7.2);
5. normalizes file extensions;
6. separates redundant JPEGs that have a RAW sibling;
7. detects content duplicates and quarantines them recoverably;
8. organizes timestamped media into by-date folders, untimestamped media into a missing-metadata folder, and **non-media into the strays folder `1-strays/`** — leaving `0-sources/` empty (Sections 7.6, 18, 3.2);
9. maintains a SQLite fingerprint/metadata cache so repeated runs are cheap and idempotent;
10. passively caches the EXIF/QuickTime/XMP facts the geotag phase will need, without making any time/GPS decision;
11. writes a dependency-fingerprinted handoff manifest for the geotag phase;
12. writes a complete, human-readable end-of-prep audit log (`photos-15-prep-log.json`) recording every transformation each photo underwent in prep — a self-sufficient record even if no later phase ever runs.

The prep phase ends when timestamped photos are in `5-photos-by-date` and videos in `4-videos-by-date`. Only the photos are then moved by the user into `6-photos-by-dest`; videos stay in `4-videos-by-date` and never enter by-dest (Section 2.4).

This is a workflow specification, not a script implementation specification. It describes *what* the prep phase does and the invariants it must uphold, not the staged build or class layout that implements it; those details live in the prep implementation/build notes and are out of scope here.

Cross-phase facts shared with geotag — the workspace lock, the pre-mutation snapshot (`zfs`) mechanism, the shared configuration object, the workspace control directory, the camera-group identity key, the filename timestamp format, the GPX root, and the end-to-end operator loop — are defined in `photos-shared-contract.md` and are authoritative there. This document references that contract rather than restating it.

---

## 2. Scope and boundary

### 2.1 Prep is prep-only

`photos-1-prep` owns filesystem organization, deduplication, cache/fingerprint maintenance, passive metadata acceleration, and handoff generation. It must not plan, infer, write, or apply any time or GPS correction. The full prohibition list is in Section 20.

### 2.2 `6-photos-by-dest` is read-only for media

`photos-1-prep` scans and accounts for `6-photos-by-dest` but must never move, rename, quarantine, delete, touch, or metadata-write any file inside it (Section 11).

### 2.3 The end of prep is the start of geotag

Prep leaves organized media in `4-videos-by-date` and `5-photos-by-date`. The user then moves the **photos** from `5-photos-by-date` into destination folders under `6-photos-by-dest`; videos remain in `4-videos-by-date` and are never moved into by-dest (Section 2.4). Geotag (`photos-2-geotag-workflow.md`) requires that `5-photos-by-date` contain no photos, that `6-photos-by-dest` be photo-only (no non-media files and no videos), and that no `jpg`/`tif` development subfolders exist under `6-photos-by-dest` before it will run. Prep itself does not perform that move and does not enforce the geotag preconditions; it only produces the by-date working set and the handoff. Crucially, when the user does move files into by-dest, the next prep run must recognize the move rather than rescan (Section 10.1); this re-prep is mandatory before geotagging the moved files, and applies every time new media enters by-dest — including after a prior successful geotag. The full cross-phase cycle is in the shared contract (`photos-shared-contract.md` Section 10).

### 2.4 Videos are semi-foreign

The pipeline's main target is **photos**. Videos are handled as **semi-foreign**: prep inventories, deduplicates, and date-organizes them into `4-videos-by-date`, and names them by date with the same convention as photos — but that is the extent of their special treatment. Videos are renamed naively (by their own timestamp) and otherwise left alone; in particular they are **not** time/GPS-geotagged downstream (geotag `photos-2-geotag-workflow.md` Section 7.3). They are organized so they aren't lost or scattered, not because the pipeline aims to correct them.

Videos live **only** in `4-videos-by-date`. They must **never** appear in `5-photos-by-date` or `6-photos-by-dest`, and the user does not sort them into destinations. This is a hard invariant: a `video`-class file found in **either** `5-photos-by-date` **or** `6-photos-by-dest` is a **prep-side hard block** (Section 6.1, Section 6.2 item 6) — prep reports the offending path and produces no plan. Geotag independently re-guards the same condition for by-dest as a second line of defence (geotag Section 7.3), but the primary stop is prep's band-misplacement guard, which fires for a video in by-dest exactly as for one in by-date. By-date and by-dest are photo-only (`image`/`raw`); the video band is separate and stays separate.

---

## 3. Workspace layout

Prep manages a fixed set of numbered folders under the workspace root, plus control directories.

```text
0-sources/           dump arrives here; emptied by prep after each run   (mutable)
1-strays/<plan-id>/  non-media set aside per run, structure preserved    (mutable)
2-missing-metadata/  media with no usable timestamp                      (mutable)
3-redundant-jpgs/    JPEGs that have a RAW sibling                       (mutable)
4-videos-by-date/    timestamped videos, in YYYY-MM-DD/ day folders      (mutable)
5-photos-by-date/    timestamped photos, in YYYY-MM-DD/ day folders      (mutable)
6-photos-by-dest/    user-curated destinations                           (READ-ONLY)
```

### 3.1 Workspace initialization (the base-is-folders-only invariant)

A workspace is **initialized** when its root sentinel `photos-00-workspace-guard` exists (inside `.photos-ingest/`, shared contract `photos-shared-contract.md` Section 5). The sentinel is the authoritative "this is a workspace" signal, and it is created **last** — only after the full `0`–`6` folder structure and the control directory exist (Section 7.1). Prep behaves differently depending on whether it is present:

1. **Uninitialized** (no sentinel — a brand-new empty folder, or a folder that already holds an "as-arrived" dump). This is the deliberately comfortable entry point: you may drop a dump into a bare folder without pre-creating anything. Prep's first action is to **initialize**: it creates any missing part of the `0`–`6` structure and the control directory, and moves every base entry that is **not** part of that managed structure — loose files *and* whole folder trees, **structure preserved, no flattening** — into `0-sources/`. The move **excludes the managed folders themselves** (`0-sources/` and its `1`–`6` siblings) and the control directories (`.photos-ingest/`, `.photos-ingest-quarantine/`, `.git`), so it never moves a structure folder into `0-sources`. **Hidden (dot-prefixed) entries in the dump** — OS metadata (`.DS_Store`), thumbnail caches (`.thumbnails/`), editor temp files — are neither organized as media nor left behind: they are swept to the **recoverable quarantine** (Section 15), so an init run leaves no hidden litter at the root (the control directories above are the only dot entries that remain). The sentinel `photos-00-workspace-guard` is written **last** (Section 7.1). Because it is written last, a crash partway through init leaves no sentinel, so the next run simply re-enters the init path harmlessly — the already-created `0`–`6` folders are recognized and left in place (not re-moved), the dump already in `0-sources/` stays put, any missing structure is created, and only genuinely new base entries (if any) are consolidated. There is no half-initialized trap. (The numbered folder names `0-sources`…`6-photos-by-dest` are reserved for the managed structure; a same-named folder in an as-arrived dump is treated as the managed folder, not moved beneath itself.)
2. **Initialized** (sentinel present). Prep operates normally: new dumps live in **`0-sources/`** and prep distributes them. After initialization the **base of the workspace contains only the managed folders and the control/dot directories, never loose files or stray folders** — an invariant every script relies on (the control directory `.photos-ingest/` and the numbered folders are folders; the sentinel lives *inside* `.photos-ingest/`, not at the root). Any **misplaced entry at the root** — a loose file, a non-managed folder, or a symlink — is a misplaced dump and a hard block (Section 6.2 item 2): once a workspace exists, the one and only inbox is `0-sources/`, never the root, and a symlink is barred outright rather than followed (it would escape the workspace; Section 6.2 item 3, shared contract Section 5.3). The full `0`–`6` **structure is itself an invariant**: prep created it at init and never removes a folder, so a *missing* managed folder on an initialized workspace is treated as evidence the structure was disturbed out-of-band and is a hard block that tells the operator to restore it — prep does not silently re-create it on a non-init run (Section 6.2 item 7).

So "drop files in the folder" is the happy path **exactly once** — the uninitialized first run — and a hard error every time after. This asymmetry is intentional and is stated for the operator: the first gesture *bootstraps* an empty folder; afterwards the workspace has an inbox (`0-sources/`) and that is the only place a dump belongs. The post-init root-file block message says exactly this and points to `0-sources/`.

### 3.2 The strays folder (`1-strays/`)

`1-strays/` holds **non-media (`other`-class) files** — anything the pipeline never fingerprints, organizes, or reasons about (Section 6.1, Section 9). On each run that finds such files in `0-sources`, prep **moves them out into a per-run subfolder `1-strays/<plan-id>/`, preserving their relative path under `0-sources`** (a file at `0-sources/trip/notes.txt` moves to `1-strays/<plan-id>/trip/notes.txt`). Each prep run uses its own `<plan-id>` subfolder, so successive runs never collide and nothing is ever overwritten — within a run paths are unique, across runs the `<plan-id>` differs. Strays are **inert**: prep journals the move and does nothing else with them — they are not fingerprinted, not recorded in the SQLite cache, not in any phase log, and not part of the archival package. `1-strays/` is excluded from prep's processing scan (like `.photos-ingest/` and the quarantine tree), so already-parked strays are never re-swept. Moving non-media into `1-strays/` is what lets prep leave **`0-sources/` empty** at the end of every run, ready for the next dump (Section 7.6, Section 18).

Control / non-media paths (never treated as managed media). All pipeline control and artifact files live inside `.photos-ingest/`. The **authoritative, complete listing** is the shared contract (`photos-shared-contract.md` Section 5.1); the layout below mirrors it (prep itself only writes the `0X`/`1X` entries — the `2X`/`3X` artifacts are produced by geotag and merge but live here too):

```text
.photos-ingest/                          all pipeline control & artifact files live here
  photos-00-config.json                  workspace config (seeded by prep)
  photos-00-workspace-guard              workspace guard / sentinel (prep writes it last on init; prep is its sole writer)
  photos-00-sealed.json                  terminal/sealed marker, written ALONGSIDE the guard by a successful merge (a separate file)
  photos-00-ingest.db                    SQLite identity/metadata cache + derived caches (live working DB; archived)
  photos-15-prep-ingest.db               prep-phase artifact: DB backup snapshot, end of prep
  journal-*.json                         execution journals
  photos-11-handoff.json                 prep-phase artifact: handoff manifest
  photos-15-prep-log.json                prep-phase artifact: end-of-prep audit log
  photos-21-time-decisions.json          geotag-phase artifact
  photos-23-gps-decisions.json           geotag-phase artifact
  photos-24-executable-plan.json         geotag-phase artifact
  photos-25-execution-summary.json       geotag-phase artifact
  photos-26-complete-log.json            geotag-phase artifact: transformation log (at finalize)
  photos-26-geotag-ingest.db          geotag-phase artifact: DB backup snapshot, end of geotag
  photos-31-merge-summary.json           merge-phase artifact: library-merge summary
  photos-35-merge-log.json               merge-phase artifact: full transformation log (prep+geotag+merge)
  photos-35-merge-ingest.db              merge-phase artifact: DB backup snapshot, end of merge
  gpx/                                    gpx_root, when configured to live here (geotag GPX tracks; not prep media)
.photos-ingest-quarantine/<plan_id>      recoverable duplicate quarantine
```

Because every control and artifact file lives under `.photos-ingest/`, prep skips that directory **wholesale** during its media scan — there is no per-file ignore list to maintain. The scanner must skip `.git`, `.photos-ingest/`, and `.photos-ingest-quarantine/` as whole subtrees, plus dot-prefixed files (which are never inventoried as media), **and the strays folder `1-strays/` in its entirety** (all `<plan-id>` subfolders, Section 3.2) — its contents are already-parked non-media that the pipeline never re-processes. Hidden dotfiles are not merely ignored, though: a dedicated sweep moves any that arrive in a **dump area** — the workspace root on an init run, or the `0-sources/` inbox on any run — into the **recoverable quarantine** (Section 15), and prunes the emptied hidden-dir skeletons, so a dump leaves no hidden litter. (The control directories above are never swept; dotfiles inside the band folders, `1-strays/`, or the read-only `6-photos-by-dest` are not in a dump area and are left untouched.) Prep *writes* to `1-strays/` (it moves new strays in) but never *scans* it, exactly as with the quarantine tree. Nothing pipeline-related ever sits among managed media, so a control file can never be mistaken for a photo. GPX track files are geotag's alone and live under `gpx_root` (shared contract `photos-shared-contract.md` Section 8), which resolves outside the managed `0`–`6` tree by contract — wherever it points (its specific location is a config choice, not part of the contract); should `gpx_root` be misconfigured to resolve inside the managed `0`–`6` tree, prep must skip that subtree too so GPX files are never organized. Prep is otherwise GPX-unaware — it does not read, parse, or fingerprint GPX.

The mutable/immutable status of each folder is recorded in the handoff manifest (Section 16).

The SQLite database (`photos-00-ingest.db`) is not throwaway scratch: besides serving as the fingerprint/metadata cache that makes runs cheap and idempotent, it is part of the durable record of what the pipeline knows about the archive, and it is bundled into the archival package on finalize (shared contract `photos-shared-contract.md` Section 13.4). Prep is the sole writer of its cache/identity content (fingerprints, metadata, move-aware history) through the controlled single-writer path (Section 14.3); geotag writes only its own derived regions of the database (the resolved-UTC cache and the manual-GPS pre-state ledger, geotag Section 24.1), which are disjoint from prep's; and merge writes only the library-file fingerprint cache and per-file library-destination rows (shared contract `photos-shared-contract.md` Section 13.4). The three writers' regions are disjoint — no two phases ever write the same rows.

The workspace configuration, `photos-00-config.json`, is defined authoritatively in the shared contract (`photos-shared-contract.md` Section 4). Prep seeds it: on a run, if the file is absent prep creates it in `.photos-ingest/` from the in-code default template (`photos_utils.CONFIG`); if present, prep reads it as-is and treats the workspace copy as authoritative for all processing in that workspace. Prep is the sole writer of the file (it only seeds it once); the user changes configuration by hand-editing the JSON, and geotag reads it but never writes it. Its field-scoped fingerprints feed dependency staleness (so a config edit invalidates only the artifacts that depend on the changed area), and its whole-file SHA-256 is recorded for integrity and archived in the package. Seeding happens at the start of the run, before any config-dependent fingerprint is computed, so that all fingerprints (and the handoff's recorded config hash) are derived from the on-disk `photos-00-config.json`, never from the in-code defaults directly — on a first run the freshly seeded file is the thing fingerprinted.

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
2. dry-run validates the real saved plan and reports a concise summary of it (the full exact plan is the saved artifact), never a separate simulation;
3. execution revalidates the plan before any mutation and rejects stale plans;
4. all media operations are no-clobber — planned no-clobber *and* re-verified no-clobber at execute time, performed atomically (Section 14.3; shared contract `photos-shared-contract.md` Section 15);
5. all media mutations are journaled;
6. `6-photos-by-dest` is never a mutation source or target;
7. no downstream artifact is created from stale upstream inputs (Section 5);
8. all human-authored config is sanity-validated before use (Section 6.3; shared contract Section 14).

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
  -> fingerprint + metadata freshness decisions
  -> prep plan
  -> execution journal
  -> updated SQLite cache
  -> photos-1-prep handoff manifest (photos-11-handoff.json)
  -> end-of-prep audit log (photos-15-prep-log.json)
  -> end-of-prep DB backup snapshot (photos-15-prep-ingest.db)
```

Durable artifacts (plan, journal, SQLite cache, handoff, prep audit log) must carry a `depends_on` block (or equivalent) recording the upstream fingerprints they relied on. Intermediate items (inventory snapshot, freshness maps) are internal pipeline state of a single run, not independently revalidated artifacts.

At minimum the recorded fingerprints include:

1. config fingerprint;
2. CLI-options fingerprint where options affect planning;
3. per-file preconditions (size, mtime) for files involved in operations;
4. SQLite schema/cache version;
5. content-fingerprint algorithm/version;
6. metadata extractor name + version, field-set version, extraction-options fingerprint, metadata-schema version, camera-group-key version;
7. by-dest read-only preconditions for any by-dest file that influenced a decision;
8. final workspace/cache fingerprint (handoff only).

If any recorded dependency is stale, missing, or unverifiable, the script blocks before creating or using the downstream artifact.

---

## 6. Media classification and input guards

### 6.1 Media classes

Each file is classified by extension. The class **vocabulary** — `image` / `raw` / `video`, with
`other` as the residual for any unlisted extension — is fixed pipeline logic; the **extension lists**
are config (`media_extensions`, shared contract `photos-shared-contract.md` Section 4.3 item 9), seeded
on first run from the in-code default below and authoritative per workspace thereafter. Extensions are
canonical (lowercase, no leading dot) and each maps to exactly one class. The seed defaults:

```text
image : jpg jpeg png heic tiff
raw   : cr2 cr3 nef arw dng
video : mp4 mov avi mkv
other : everything else   (residual — not a config list)
```

Because the lists are config, they participate in the field-scoped config fingerprint (shared contract
Section 4.2): moving an extension between a media class and `other` changes which files prep organizes
versus sets aside as strays, so the change restales the organization-shaped downstream stages.

`other` files are carried in the cache as `not_applicable` for metadata, are **not fingerprinted** (Section 9), and are not date-organized. Prep **moves them out of `0-sources` into `1-strays/<plan-id>/`** (structure preserved) and ignores them thereafter — never deduplicated, organized, or blocking (Sections 3.2, 7.6, 18).

**Stray-media detection (advisory, never blocking).** Because the media-extension lists are config, a dump may contain a real photo/video format the operator has not yet listed — it would be classed `other` and parked in `1-strays`. To catch this, during `plan` prep probes each **distinct** extension among the `0-sources` files it is about to set aside as strays: it asks `exiftool` for that extension's `MIMEType` (one probe per distinct extension, not per file) and, when the type is `image/*` or `video/*`, emits a **warning** in the plan output naming the extension and suggesting it be added to the appropriate `media_extensions` class. This is a hint only — it never blocks, never reclassifies on its own, and never mutates config; the operator decides whether to add the extension and re-run. (`other` extensions exiftool does not see as image/video — documents, archives, sidecars — are not flagged.)

Photos (`image`/`raw`) and videos are organized into **separate bands** that never mix: photos into `5-photos-by-date` (then by-dest), videos into `4-videos-by-date` (and nowhere else). A `video`-class file found under `5-photos-by-date` or `6-photos-by-dest`, or an `image`/`raw` file found under `4-videos-by-date`, is a misplacement the pipeline must not tolerate: **prep treats a video under either photo band (`5-photos-by-date` or `6-photos-by-dest`) as a hard break** — it reports the offending path and does not proceed (the band-misplacement guard, Section 6.2 item 6). This is a *prep* hard-stop, not a deferral to geotag; geotag re-checks the by-dest case as well (geotag `photos-2-geotag-workflow.md` Section 7.3), but prep is the primary guard and fires first. Prep's own routing never places a video into a photo band; this guard catches a video that arrived there by other means (e.g. a hand-move). (Prep blocks but never *mutates* by-dest — by-dest is read-only, Section 2.2 — so resolving a by-dest video is the operator's manual fix, after which prep proceeds.)

### 6.2 Hard input guards (block before any operation)

Planning must block, producing no executable plan, if it finds:

1. a **sealed (terminal) workspace** — a terminal/sealed marker written by a prior successful merge (shared contract `photos-shared-contract.md` Section 13.7). A merged workspace is **done**: prep **hard-stops immediately, mutating nothing, and never touches anything**, directing the user to start a fresh workspace. There is no recovery utility and no sweeping — if a new dump was dropped into a sealed workspace (files at the workspace root **or** in `0-sources/`), prep additionally reports that a likely new dump was detected and that, because this workspace is sealed, the dump must be moved into a **fresh** workspace by hand; prep leaves it exactly where it is. This check runs at startup, right after the lock is acquired — on an initialized workspace, alongside verifying the sentinel (shared contract Section 2); an uninitialized workspace carries no seal marker and enters the init path instead (Section 7.1), so this guard never fires there. The check precedes any scan or plan. (This seal guard governs the media-mutating commands `plan`/`dry-run`/`execute`; the `prune-quarantine` command is **exempt** and still runs on a sealed workspace, because it only reclaims recoverable quarantine copies and touches no controlled content — Section 15.3; shared contract Section 13.7 item 2.);
2. a **misplaced entry at the workspace root of an initialized workspace** — once a workspace is initialized (sentinel present, Section 3.1), the base must contain only the managed numbered folders and the control/dot directories (`.photos-ingest/`, `.photos-ingest-quarantine/`, `.git`, dotfiles/dotdirs). Anything else at the root is a misplaced dump and a hard block. This covers **three kinds of root entry, treated identically**:
   - **a loose file** — the original case: dumps belong in `0-sources/`, not the root;
   - **a non-managed folder** — a directory at the root whose name is **not** one of the reserved managed names (`0-sources`…`6-photos-by-dest`) and is not a control/dot directory. Prep does **not** treat a stray root folder as an additional inbox to sweep; a dump that arrives as a folder belongs **inside** `0-sources/` (its tree is preserved there, Section 7.2), not loose at the base. (This is the symmetric counterpart to the loose-file rule: after init, the base holds *only* the managed folders, whether the intruder is a file or a folder.);
   - **a symlink** — any non-dot symlink at the root (whether it points at a file or a directory) is blocked rather than followed. Following a root symlink would let the scan traverse an external target and plan moves for files outside the workspace — a pipeline escape (item 3; shared contract Section 5.3). A symlink is therefore checked **before** the file/folder distinction and blocked outright.

   Prep hard-stops with a message that dumps belong in `0-sources/` (move the entry there or remove it, then re-run). The check is **strict**: any such root entry blocks, dotfiles included — nothing but the numbered folders and the control/dot directories belongs at the base. (This guard does **not** apply on an *uninitialized* workspace, where root files and folders are the expected first dump and trigger initialization instead, Section 3.1; even there, a **symlink** at the base is still barred as an escape rather than consumed into `0-sources/`.);
3. a **symlink among managed files (forbidden), including nested directory symlinks** — the pipeline never follows or organizes a symlink, because doing so would let a planned move read from or write to a target outside the managed tree (an escape, shared contract `photos-shared-contract.md` Section 5.3). The bar is comprehensive and covers every place a symlink can appear:
   - a **file symlink** anywhere in a dump or a managed folder;
   - a **nested directory symlink** — a directory symlink encountered *inside* a dump tree (under `0-sources/`, or under an as-arrived base dump on an init run) **or inside any managed folder** (including `6-photos-by-dest`). The traversal does not descend into it (it is not followed), but its mere presence is a hard blocker — it is never silently skipped;
   - a **managed folder that is itself a symlink** (e.g. `5-photos-by-date` replaced by a link to an external directory) — blocked before the folder is walked, since walking it would traverse the external target;
   - a **root dump entry that is a symlink** (item 2 above) — the same escape, caught at the base before the directory walk.
   In every case prep reports the offending path and produces no executable plan. The decoded-content fingerprint and organization machinery only ever operate on real files inside the workspace;
4. a forbidden sidecar (`.xmp`, `.dop`, `.pp3`) — editing sidecars are not part of this pipeline;
5. a content fingerprint failure for any non-by-dest **media** file whose content equality a decision depends on (Section 11.3);
6. a band misplacement — a `video`-class file under `5-photos-by-date` or `6-photos-by-dest`, or an `image`/`raw` file under `4-videos-by-date` (Section 6.1). Prep never creates such a placement itself; this guard catches one introduced by hand.
7. an **incomplete managed folder structure on an initialized workspace** — on an *initialized* workspace (sentinel present, Section 3.1) the full `0`–`6` structure is an invariant: prep created every folder during init and never removes one. If any of the managed folders (`0-sources`…`6-photos-by-dest`) is **missing** at the start of a run, that is not a state prep can produce — it means the structure was disturbed out-of-band (most likely the user deleted a folder), so something is genuinely wrong with the workspace. Prep must **hard-stop, mutating nothing**, rather than silently tolerating the gap or quietly re-creating the folder: a missing folder may have taken organized media with it, and re-creating it blind would mask a real loss. The block message must (a) name exactly which managed folders are absent, (b) warn the operator plainly that an initialized workspace should always hold all of `0`–`6` and that their absence indicates the structure was deleted or moved, and (c) tell the operator how to restore it — recreate the missing folder(s) by name (an empty folder is sufficient to satisfy the structure check; any media that was inside a deleted folder is the operator's to recover, e.g. from a ZFS snapshot if one was taken, Section 14.4) and re-run. Prep does **not** auto-recreate the structure on a non-init run — folder creation is an *init-only* action (Section 7.1), and silently rebuilding folders on an established workspace would hide the fact that something destructive happened. (This guard is distinct from the *uninitialized* path, where a missing or partial structure is expected and is created by initialization, Section 3.1.) An empty `0-sources/` is normal and is **not** a missing-folder condition — emptiness is the steady end-state (Section 18); this guard is about a folder that does not *exist*.

Blockers are reported textually; the workflow does not silently skip them.

### 6.3 Config sanity-validation (block before any operation)

Prep seeds and then reads `photos-00-config.json` (Section 3), and every human-authored value in it must be sanity-validated before it is used, per the shared input-validation discipline (shared contract `photos-shared-contract.md` Section 14). This is separate from, and in addition to, the dependency cascade (Section 5): fingerprints detect that a value *changed*; validation detects that a value is *invalid*. A config value can match its fingerprint and still be meaningless or unsafe.

Prep validates at least the config it actually consumes:

1. **Workspace and control paths** must resolve to sane, syntactically valid paths; required paths must be non-empty.
2. **`gpx_root`** must be a syntactically valid path; the defensive skip of Section 3 / shared contract Section 8.2 handles a misconfiguration that resolves inside the managed tree, but a path that is malformed (illegal characters, not a path at all) is a validation blocker.
3. **The `zfs` block** (when snapshots are configured): the dataset/pool name and any snapshot-name prefix must be valid snapshot-name components — in particular a prefix must not contain whitespace, `/`, a second `@`, or other characters that would make the resulting `dataset@prefix-<plan_id>` snapshot name invalid. An invalid prefix is rejected before planning, so a snapshot that `snapshots_required` would demand can never fail at execute time for a name-syntax reason prep could have caught.
4. **`filename_timestamp_format`** must produce a non-empty, filesystem-safe component containing no path separators or illegal filename characters (the by-date provisional names depend on it, Section 8).
5. **Numeric/threshold and enumerated config** prep reads (e.g. job count) must be of the right type and within sane ranges. The classification lists prep consults are validated too: `folders` (every role present, each name a unique single path component, no control-dir collision) and `media_extensions` (each class a non-empty list of canonical lowercase, dot-less extensions, with no extension mapped to more than one class).

A validation failure is a hard blocker: prep reports it textually, naming the offending config field so the user can fix the JSON and re-run, and produces no executable plan and no mutation — exactly as for a hard input guard above. Validation never silently coerces or "repairs" a value.

---

## 7. The prep pipeline

Planning derives operations in a fixed, deterministic order. Each stage updates an in-memory "current path" for every file so later stages reason about where a file will be, not only where it is. Allowed operation types are:

```text
mkdir, move_no_clobber, rename_no_clobber, quarantine_move, db_upsert, db_remove
```

### 7.1 Stage 0 — Initialize if needed; inventory; guards

First, determine whether the workspace is **initialized** — root sentinel `photos-00-workspace-guard` present (Section 3.1):

- **Uninitialized** (no sentinel): prep plans **initialization** — create any missing part of the `0`–`6` structure and the control directory `.photos-ingest/`, and move every base entry that is **not** part of the managed structure (loose files *and* whole folder trees, **structure preserved — no flattening**) into `0-sources/`. The move **excludes** the numbered folders themselves and the control directories (`.photos-ingest/`, `.photos-ingest-quarantine/`, `.git`), so a re-entry after a crashed init never moves an already-created `0`–`6` folder beneath `0-sources/`. Hidden (dot-prefixed) dump entries are instead swept to the recoverable quarantine (Section 15), not left at the root. The sentinel is **not** written now; it is written **last**, only on successful completion of the run (Section 14.3), so a crash before then leaves the workspace uninitialized and the next run re-enters this path harmlessly — the dump already in `0-sources/` and the already-created structure are recognized and left in place (Section 3.1).
- **Initialized** (sentinel present): the structure already exists and the dump lives in `0-sources/`. The root-entry guard (Section 6.2 item 2) blocks any misplaced base entry — a loose file, a non-managed folder, or a symlink; the structure guard (Section 6.2 item 7) blocks a workspace missing any of its `0`–`6` folders; the symlink guard (Section 6.2 item 3) blocks symlinks anywhere among managed files, including nested directory symlinks and a managed folder that is itself a symlink; and the seal guard (Section 6.2 item 1) blocks a sealed workspace.

Then scan `0-sources/` and every managed folder, apply the guards of Section 6.2, and split the inventory into **mutable-side files** (everything outside `6-photos-by-dest`) and **read-only by-dest files**.

### 7.2 Stage 1 — The dump in `0-sources` (no flattening)

**`0-sources/` is the one and only inbox.** On an initialized workspace you place a dump — arbitrary files and whole folder trees, in any structure — into `0-sources/`; on an uninitialized workspace prep moves the as-arrived base dump into `0-sources/` during initialization (Stage 0). Either way the dump then sits in `0-sources/` and prep processes it from there. You are not expected to pre-organize, rename, or sort anything. A single workspace may receive one or many dumps over time (shared contract `photos-shared-contract.md` Section 10).

**Prep does not flatten `0-sources`.** Dumped folder trees are left as they are on disk; prep does not lift files up into the top level of `0-sources/`. The job flattening used to do — guaranteeing no destination-name collisions — is instead handled **in memory during planning**: prep computes each file's by-date destination name and resolves any collision with the deterministic `-NNN` suffix allocator (Section 8), treating every on-disk and planned name as occupied. So the *organized outputs* — by-date photos and videos — always land at a unique destination path (logically "flattened") without ever physically flattening `0-sources`; uniqueness is per day folder (within a `YYYY-MM-DD/` band subfolder, Section 8). Files already inside a managed folder are left where they are at this stage, **except** a by-date file not in its conforming day folder, which is re-located into it (Section 7.6); non-media files are routed to `1-strays/` at Stage 5 (Section 7.6).

> **Caution — protect your originals *during* the dump; a clobber at copy time is invisible to the pipeline.** Every operation the pipeline performs is no-clobber and atomic (Section 14.3; shared contract `photos-shared-contract.md` Section 15), and prep preserves every distinct file it finds — photos and videos are organized under uniquely-allocated by-date names (Section 8), non-media is moved into `1-strays/` (Section 3.2), and nothing is overwritten. **That protection begins only at the first prep invocation.** It cannot cover a file overwritten *while you are dumping*, before prep has run: if your own copy/move command overwrites a same-named file in the same destination folder as you stage files — e.g. `cp a/IMG_1234.jpg 0-sources/` then `cp b/IMG_1234.jpg 0-sources/`, where the second silently replaces the first — that file is gone at the filesystem level and the pipeline has **no record it ever existed**: nothing to detect, nothing to recover. The pipeline cannot see a collision that happened before it was invoked. To stay safe, dump each source into its **own subfolder** under `0-sources/` (prep keeps the subfolder structure on disk and gives same-named files from different subtrees distinct by-date names — it won't conflate them), or use a non-overwriting copy (`cp -n`, `rsync --ignore-existing`, or a tool that refuses to overwrite) and verify file counts before running prep. The dump is the one step where avoiding a clobber is in your hands, not the pipeline's.

### 7.3 Stage 2 — Normalize extension case

A file whose extension is not lowercase (e.g. `.JPG`, `.ARW`) is renamed to the lowercase form. To stay safe on case-insensitive filesystems this is done as two no-clobber renames (to a unique temporary name, then to the final lowercase name). Collisions are resolved by suffix allocation (Section 8).

### 7.4 Stage 3 — Separate redundant JPEGs

Files are grouped by `(folder, basename-without-extension)`. If a group contains both a RAW and a `.jpg`, the JPEG is considered redundant (the RAW is the master). A redundant JPEG that is in `0-sources` is moved to `3-redundant-jpgs/`. Paired JPEGs are excluded from the content-dedup stage so a RAW+JPEG pair is never treated as a duplicate of itself.

### 7.5 Stage 4 — Content deduplication and quarantine

Remaining files (mutable-side **and** by-dest, excluding paired JPEGs **and excluding `other`-class files, which are not fingerprinted, Section 9**) are grouped by `(content_fingerprint, media_class)`. Within a group of more than one file:

1. one file is **retained**, chosen by folder priority — by-dest wins, then the more-organized folder:

```text
6-photos-by-dest  >  5-photos-by-date  >  4-videos-by-date
                  >  3-redundant-jpgs  >  2-missing-metadata  >  0-sources
```

2. every other copy on the mutable side is moved to `.photos-ingest-quarantine/<plan_id>/<original-path>` via `quarantine_move`;
3. a by-dest copy is **never** quarantined (it can only ever be the retained file);
4. quarantine is recoverable: each quarantined file gets a manifest entry recording its original path, quarantine path, the retained counterpart, and the duplicate evidence (Section 15);
5. files with unknown/invalid fingerprints are not grouped as duplicates (Section 11.3).

### 7.6 Stage 5 — Chronological organization

Every mutable-side file still in `0-sources` after Stages 2–4 (not already routed and not quarantined) is handled by its class and timestamp. The timestamp is read passively from cached metadata in priority order:

```text
DateTimeOriginal -> CreateDate -> ModifyDate
```

Routing:

```text
valid timestamp + video    -> 4-videos-by-date/YYYY-MM-DD/
valid timestamp + photo    -> 5-photos-by-date/YYYY-MM-DD/
media, no valid timestamp  -> 2-missing-metadata/            (flat — no day folder)
non-media (other-class)    -> 1-strays/<plan-id>/            (structure preserved, inert; Section 3.2)
```

Timestamped media is grouped into a **`YYYY-MM-DD/` day subfolder** under its band (the day is the date portion of the source-naive timestamp, Section 8); the filename still carries the full timestamp. An already-organized by-date file that is **not** in its conforming day folder — a flat file from an older layout, or one whose timestamp changed — is **re-located into the correct day folder** on the next run (idempotent: a file already in its day folder is a no-op). `2-missing-metadata` stays flat (it has no date to group by). Empty day folders left behind (e.g. after the user moves a day's photos into by-dest) are pruned (Section 14.3).

After Stage 5, **`0-sources/` is empty** — every file it held has been organized into a by-date band, set aside in `2-missing-metadata`, quarantined as a duplicate, or moved to `1-strays/`. Leaving `0-sources/` empty at the end of every run is a deliberate end-state (Section 18): it is the clean inbox the next dump arrives into, and it is what geotag's "`0-sources` empty" gate checks (geotag `photos-2-geotag-workflow.md` Section 13).

The timestamp used here is the raw camera-naive value, used only for organization and ordering. Prep does **not** correct it, resolve a timezone, or convert to UTC — that is geotag's job.

**How files leave `2-missing-metadata`.** Prep cannot invent a timestamp, so a media file with no usable one lands in `2-missing-metadata` and stays there until **the user supplies the missing metadata** (e.g. sets `DateTimeOriginal` in the file). Resolving these is the user's responsibility, not the pipeline's. Once the user has fixed a file, they move it back into `0-sources` — at which point it is simply an **additional dump** (Section 7.2): the next prep run re-inventories it, and because its size/mtime changed (the metadata edit) it is re-extracted, now has a valid timestamp, and is routed normally to `5-photos-by-date` (or `4-videos-by-date`). (It must go into `0-sources`, not the workspace root — a root file is blocked on an initialized workspace, Section 6.2 item 2.) Prep provides no special "re-import from missing-metadata" path; the file just flows through the ordinary pipeline as any dumped file does. A file left in `2-missing-metadata` is residual and never blocks geotag (geotag `photos-2-geotag-workflow.md` Section 7).

### 7.7 Stage 6 — Cache reconciliation

For files that were not mutated and whose cache record is stale (changed size/mtime or stale metadata), a `db_upsert` records the refreshed state. Before treating a cached file whose path has disappeared as a ghost, prep applies the move-recognition rule of Section 10.1: a disappearance explained by a matching new by-dest entry is a move (cache carried forward), not a ghost. Genuinely missing cache rows are pruned with `db_remove` (ghost prune). Unchanged, already-fresh files produce no operation and are reported as `no_op` / `already_correct`.

---

## 8. Naming conventions

Date-organized names follow the project standard and are derived from the source-naive timestamp:

```text
4-videos-by-date / 5-photos-by-date :  YYYY-MM-DD/YYYY-MM-DD--HH-MM-SS[-NNN].ext
2-missing-metadata                  :  UNKN_<original-base>[-NNN].ext            (flat — no day folder)
```

By-date media is grouped into a `YYYY-MM-DD/` day subfolder (the date portion of the same source-naive timestamp); the filename keeps the full timestamp. Because the filename already encodes the full date, two files can share a name only if they share the whole timestamp — i.e. the same day, hence the same day folder — so a single occupied-name set across the band is sufficient to allocate suffixes (two files in different day folders can never collide on name).

The **first** file at a given name takes the **bare** name (no suffix); a `-NNN` zero-padded differentiating suffix (`-001`, `-002`, …) is added only on a collision, allocated deterministically and no-clobber against a per-run, case-insensitive occupied-name set, taking the **lowest free** index, so two files never collide. This bare-first, first-free rule is shared with geotag so an uncorrected file's provisional (prep) and final (geotag) names coincide (Section 7.3; shared contract `photos-shared-contract.md` Section 7.2) — it is **not** monotonic/append-only; only merge appends at `max+1` (for its append-only library). Extensions are normalized to lowercase (Section 7.3). The timestamp shape and the differentiating-suffix convention are defined once in the shared contract (Section 7); prep reads the same shared `filename_timestamp_format` key as geotag.

The timestamp component (`YYYY-MM-DD--HH-MM-SS`) is the raw camera-naive value, used here only for organization and ordering. It shares the same textual format as the final filename geotag assigns later (`photos-2-geotag-workflow.md` Section 26 / shared contract Section 7.3), but the value is **provisional**: geotag recomputes it from corrected, destination-local civil time and rewrites the name. Prep does not correct, timezone-resolve, or UTC-convert the timestamp.

> Both prep and geotag use the same `filename_timestamp_format` (shared contract `photos-shared-contract.md` Section 7). A pre-existing file whose name does not match the convention is treated as an ordinary dump and re-ingested — prep never parses meaning from a non-conforming filename; the timestamp comes from metadata.

---

## 9. Content fingerprinting and cache reuse

Content fingerprints back the duplicate and content-uniqueness checks, are persisted in SQLite, and serve as the **identity spine** the later phases rely on (shared contract `photos-shared-contract.md` Section 13.3 item 2).

**The media content fingerprint is over decoded *content*, computed by an external tool — not a byte hash.** Each fingerprinted media file's content fingerprint is derived from its **decoded content**, not its raw file bytes, and the tool differs by class:

1. **Photos** (`image`/`raw`): the fingerprint is computed with **ImageMagick `identify`** over the normalized decoded image (pixels). This is essential because geotag rewrites photos' EXIF/metadata in place (time, GPS, the `GPSProcessingMethod` marker) and renames them: a file-byte hash would change on every such write, so it could not serve as a stable identity. An `identify` pixel fingerprint is **invariant under in-place metadata writes and renames** — the decoded pixels do not change.
2. **Videos** (`video`): the fingerprint is the **`ffmpeg` stream MD5** over the decoded media streams. Videos are date-organized and renamed but not otherwise mutated (Section 2.4); a content fingerprint still gives them a stable identity for de-duplication and move-aware recognition, on the same footing as photos.

A single decoded-content fingerprint is therefore what keys the transformation log (shared contract `photos-shared-contract.md` Section 13.3 item 2), the manual-GPS pre-state ledger (geotag `photos-2-geotag-workflow.md` Section 24.1, photos only), content de-duplication (Section 7.5), and merge's collision / already-present checks (`photos-3-merge-workflow.md` Section 7) — *across* the renames, moves, and (for photos) metadata writes the pipeline performs. The fingerprint tool/identity and its version (ImageMagick `identify` for photos, `ffmpeg` stream MD5 for videos) are part of the recorded content-fingerprint algorithm/version (Section 5 item 5; Section 12.1), so a tool change is detectable rather than silently shifting identities.

**`other`-class files are not fingerprinted at all.** Non-media (`other`-class) files get **no content fingerprint** — there is nothing meaningful to decode and they are never content-deduplicated or organized. They are moved out of `0-sources` into `1-strays/<plan-id>/` and ignored thereafter (Sections 3.2, 6.1, 7.6). This is by design, not a fingerprint failure: the absence of a fingerprint on an `other` file is normal and never a blocker, unlike a *media* fingerprint **failure** (Section 11.3).

**Byte-level (whole-file) SHA-256 is reserved for artifacts.** The only place a hash is taken over raw file bytes is the pipeline's **artifacts** — the numbered JSON files and `photos-00-config.json` (geotag Section 4 / shared contract Section 4.1) — where detecting a byte change *is* the point. Media is never identified by a byte hash.

Reuse rules (apply to the fingerprinted media classes — photos and videos; `other` is not fingerprinted):

1. if a path exists in the cache with unchanged size and mtime (and fresh metadata context), reuse the cached content fingerprint;
2. if a fingerprinted media file is absent from the cache, compute its decoded-content fingerprint (ImageMagick `identify` / `ffmpeg` stream MD5) and store the result;
3. if size or mtime changed, treat the cached fingerprint as stale and recompute — a metadata-only edit (including the pipeline's own EXIF writes) changes size/mtime and forces a recompute, but a photo's `identify` fingerprint (or a video's `ffmpeg` stream MD5) recomputes to the **same** value, so identity is preserved while the cache freshness is refreshed;
4. if prep moves or case-normalizes a file without changing content, carry the known fingerprint forward to the new workspace-relative path (Section 10);
5. a fingerprint failure on a media file never implies equality;
6. an unknown or failed fingerprint on a *media* file blocks any decision that depends on content equality (Section 11.3); an `other` file's absence of a fingerprint is not such a case (it is intentionally unfingerprinted and never enters a content-equality decision);
7. the fingerprint algorithm — including the tool identity/version (ImageMagick `identify` for photos, `ffmpeg` stream MD5 for videos) — is recorded in the cache and handoff.

---

## 10. Move-aware cache identity

The cache must distinguish: same content at a new path because of a move; same path with changed content; different path and different content; duplicate content already in by-dest; duplicate content already quarantined.

Each planned move/rename carries enough to update the cache row without re-fingerprinting after the move: source path, destination path, source size, source mtime, source fingerprint if known, the post-move expected path, the post-move cache action, and the dependency facts proving the carried-forward fingerprint is still valid. Cache updates are derived from the validated plan and applied during execution, never speculatively during planning.

### 10.1 Recognizing manual moves from by-date into by-dest

After prep organizes media into `4-videos-by-date`/`5-photos-by-date`, the user moves **photos** from `5-photos-by-date` into destination folders under `6-photos-by-dest` (videos are not moved; Section 2.4). On the next prep run those photos appear at a new by-dest path and are absent from their old by-date path. Prep must recognize this as a move and must **not** re-fingerprint or re-extract metadata for the moved file.

Detection is cache-only — no file re-read beyond `stat`:

1. a previously cached mutable-side file (typically under `5-photos-by-date`/`4-videos-by-date`) is now missing from its cached path; and
2. a by-dest file that was not previously cached now exists whose `stat` (size and `mtime_ns`) and basename match that missing file.

On a unique match, prep treats it as a move: it carries the cached content fingerprint and metadata record forward to the new by-dest path (move-aware identity), drops the stale old cache row, and records the new by-dest row from the carried-forward facts. Because `6-photos-by-dest` is read-only, prep performs **no** filesystem operation — it only fixes its cache and the handoff manifest to reflect the new location.

Safety:

1. if more than one missing file could match (ambiguous size/mtime/basename), or the move did not preserve mtime, prep does not guess: it treats the by-dest file as a normal newly-seen by-dest file and scans it (Section 9), and the old row is ghost-pruned;
2. carried-forward identity never overrides a content change — if the by-dest file's size/mtime differ from the cached source, it is rescanned;
3. move recognition only updates prep's own cache/handoff; it never mutates by-dest media.

This makes the round trip cheap: after the user sorts the by-date working set into by-dest, re-running prep does not re-fingerprint or re-read the moved files — it simply fixes the handoff.

### 10.2 Recognizing moves between destinations (re-sort within by-dest)

The user may also move an already-placed file from one destination to another inside `6-photos-by-dest` (e.g. correcting a mis-sort: `Belgium/Brussels` → `Belgium/Bruges`). Prep must recognize this the same cache-only way: a previously cached by-dest file is now missing from its cached by-dest path, and an uncached by-dest file with matching `stat` and basename now exists at a different by-dest path. On a unique match, prep carries the cached identity forward to the new by-dest path, drops the old row, and updates the handoff to record the new destination — performing **no** filesystem operation (by-dest is read-only).

This matters because a file's **destination is a geotag input**: the destination civil timezone is destination-scoped (geotag `photos-2-geotag-workflow.md` Section 18). When prep moves a file's recorded destination, the handoff changes, which (via the dependency cascade) restales the affected destination decisions so geotag **re-evaluates** the moved file under its new destination rather than silently keeping the old destination's timezone (geotag Section 18.1). As with all by-dest moves, the mandatory re-prep after the move applies (shared contract `photos-shared-contract.md` Section 10), and the same ambiguity safety as Section 10.1 holds (ambiguous matches are treated as new files and rescanned).

---

## 11. Uniqueness and duplicate rules involving by-dest

### 11.1 Content duplicate against by-dest

If a mutable-side file has the same content fingerprint as a *different* by-dest file (i.e. not the same file recognized as moved per Section 10.1), it is classified as a duplicate against existing by-dest content. The by-dest file is the retained copy; only the mutable-side file is acted on (quarantined). The relationship is recorded in the summary, journal, and handoff.

### 11.2 Path conflict against by-dest

If a planned destination path would collide with an existing by-dest path (including case-insensitively), prep must not clobber it: it allocates a safe alternative name where the operation class allows, otherwise it blocks. The by-dest file is never touched.

### 11.3 Unknown fingerprints

This rule concerns **media** files (photos and videos), which are fingerprinted; `other`-class files are intentionally unfingerprinted (Section 9) and never enter a content-equality decision, so they are out of scope here. If either side of a potential duplicate is a **media** file with an unknown fingerprint (a fingerprint *failure* — the decode/fingerprint could not be computed), prep must not classify it as a content duplicate and must not remove or quarantine based on equality. For a mutable-side media file this is a blocker; for a by-dest file it is skipped (by-dest is read-only and never quarantined regardless).

By-dest inventory facts that influenced any decision are recorded in the plan dependencies, so execution rejects the plan if by-dest state changed in a way that affects uniqueness decisions.

---

## 12. Passive metadata acceleration

Because prep already opens every file for fingerprinting and organization, it caches the EXIF/QuickTime/XMP facts the geotag phase will need, so geotag can avoid re-reading unchanged files. This is strictly passive: prep stores facts, makes no time/GPS decision, and corrects nothing.

Cached per file (raw values plus clearly-labelled parsed helpers):

1. **camera/device identity**: `Make`, `Model`, `UniqueCameraModel`, `BodySerialNumber`, `CameraSerialNumber`, `InternalSerialNumber`, `SerialNumber`, `OwnerName`, lens model/serial, and a derived `camera_group_key`;
2. **timestamps (uncorrected)**: `DateTimeOriginal`, `CreateDate`, `ModifyDate`, sub-second and offset/timezone fields, XMP/IPTC `CreateDate`/`ModifyDate`/`DateCreated`, and the QuickTime `*CreateDate`/`*ModifyDate`/`Track*`/`Media*` family, plus the selected source-naive timestamp and its provenance;
3. **native GPS (uncorrected)**: presence flag, `GPSLatitude(Ref)`, `GPSLongitude(Ref)`, parsed signed decimals where safe, `GPSAltitude(Ref)`, `GPSDateStamp`, `GPSTimeStamp`, `GPSDateTime`, `GPSProcessingMethod`;
4. **normalized media facts**: folder class, extension, normalized extension, media kind, dimensions, orientation, rotation, video duration;
5. a raw metadata payload (or at least the raw values for the requested field set) so future fields can be added without re-reading unchanged files.

### 12.1 Metadata freshness

A cached metadata record is reusable only when all freshness inputs still match: path (or move-aware identity, Section 10.1), size, mtime, content fingerprint if available, extractor name, extractor version, field-set version, extraction-options fingerprint, metadata-schema version, and camera-group-key version. Changing the field set or extractor in a future release makes existing records detectably stale without being confused with content changes.

### 12.2 Passive grouping facts

The handoff/summary reports passive grouping facts for later use, with no inference: per camera group (key, file count, contributing identity fields, earliest/latest source-naive timestamp, native-GPS counts, missing/ambiguous-timestamp count, and phone/camera class only if already known from config) and per by-dest folder (path, files scanned, camera groups present, timestamp range, native-GPS/missing-GPS/GPSProcessingMethod counts, cache-freshness summary, and conflicts/duplicates involving files outside by-dest).

---

## 13. Idempotency and incremental operation

Prep upholds the shared idempotency principle — change only what needs changing; a no-op run is a no-op (shared contract `photos-shared-contract.md` Section 11). Concretely: a second run on an unchanged workspace must produce zero media mutations. Prep must:

1. tolerate already-populated by-date and by-dest folders;
2. recognize files already in their correct location and not move them;
3. not re-normalize already-normalized extensions;
4. not re-quarantine already-quarantined duplicates;
5. produce the same destination names for the same unchanged input state;
6. reuse cached fingerprints and metadata for unchanged files;
7. recognize files the user moved from by-date into by-dest and carry their cache identity forward without re-fingerprinting or re-extracting (Section 10.1);
8. report `no_op` / `already_correct` facts rather than treating prior work as error.

When new files appear in a mutable folder after a previous run, a new plan acts only on the files that require action; existing by-date/by-dest files are still scanned for uniqueness/cache freshness but are not moved or re-fingerprinted unnecessarily.

---

## 14. Plan / dry-run / execute lifecycle

The whole prep run — `plan`, `dry-run`, and `execute` alike — runs under the single workspace-wide lock acquired at process startup and held until exit (shared contract `photos-shared-contract.md` Section 2). Planning and dry-run are non-mutating but still run inside the lock, so no two pipeline processes (of any phase) ever overlap. The steps below therefore assume the lock is already held; they do not re-acquire or independently scope it.

### 14.1 Plan

`plan` produces a serialized plan containing: plan id, plan/schema version, command, config fingerprint, the ordered operation list, blockers, warnings, per-file workspace preconditions (with role `no_op_prepared` or `by_dest_read_only`), metadata dependencies, and a summary (no-op count, operations planned, blockers, per-file metadata plan status). Planning mutates nothing (the plan file it writes is a control artifact, not workspace media).

The plan is written to the **canonical control-directory path `photos-10-prep-plan.json`** (shared contract `photos-shared-contract.md` Section 5) — there is no flag that tells prep where to put it or where to find it; `dry-run` and `execute` read it from the same canonical path. `plan` prints the saved location so the operator can review it without hunting for it. Re-planning **never clobbers** a prior plan: any existing `photos-10-prep-plan.json` is first renamed aside under the shared incremental `-NNN` suffix (Section 7.2) and its backup location is announced, so a superseded plan stays recoverable. (This is consistent with "prep re-plans, it does not resume the old plan," Section 14 below: re-planning supersedes the prior plan but preserves it.)

### 14.2 Dry-run

`dry-run` reads the saved `photos-10-prep-plan.json`, validates it, and reports a **concise summary** of what would execute — operation counts by type, the no-op/already-correct count, the number of warnings, and any blockers (which `execute` would refuse on) — followed by the path to the full plan. It does **not** dump every operation: the exact, complete plan is the saved canonical artifact itself, available for review at that path. Dry-run is still *not a simulation* — the summary is derived from the **real** serialized plan that `execute` will consume, not from a separate virtual-filesystem walk — it simply summarizes that real plan rather than printing all of it. Dry-run mutates nothing. If no saved plan is present, it stops and directs the operator to run `plan` first.

### 14.3 Execute

`execute` reads the saved `photos-10-prep-plan.json` from the canonical control-dir path (no flag; if absent, it stops and directs the operator to run `plan` first) and applies the validated plan.

As a friendly fast-path, when a saved plan **is** present but the workspace is already **initialized** (sentinel present) and `0-sources/` holds **no files** — the normal empty steady end-state of an already-prepped workspace (Section 18) — there is nothing to ingest. Execute then stops immediately with a *nothing to do* notice and exits cleanly (success), rather than replaying the now-stale saved plan, whose moves were already applied and would otherwise collide with the files they produced (a confusing case-insensitive-clobber error). The notice directs the operator to add media to `0-sources/` and re-`plan` before executing. (This check is gated on a plan existing — a *missing* plan still takes the "run `plan` first" path above; and it is the gentle special case of the stale-plan rejection in item 2 below, which still applies when `0-sources/` is non-empty but the plan no longer matches the filesystem.)

It must:

1. run under the workspace lock, which is already held — acquired once at process startup and held for the whole run (shared contract `photos-shared-contract.md` Section 2); this step does not re-acquire or re-verify it. Detect whether the workspace is initialized via the root sentinel `photos-00-workspace-guard`: on an **initialized** workspace the sentinel is present; on an **uninitialized** workspace this is an **init run** (Section 7.1) — there is no sentinel yet, the planned operations include creating the control directory and the full `0`–`6` structure and moving the base dump into `0-sources/`, and the sentinel is written at the very end (step 11);
2. revalidate every recorded dependency and per-file precondition; reject the plan before any mutation if stale, missing, or unverifiable, or if the plan was produced by a different tool/version/schema;
3. take a pre-mutation snapshot where configured (the `zfs` block in config), honoring `snapshots_required`;
4. apply only the planned operations, each verified no-clobber **at execute time** and performed atomically (shared contract `photos-shared-contract.md` Section 15): immediately before each move/rename/quarantine, confirm the specific target path does not already exist (case-insensitively where the filesystem is case-insensitive) rather than trusting the plan's collision analysis, and perform the operation as a single atomic filesystem action. If a target unexpectedly exists at execute time, the operation is a blocker (or is re-checked against the plan's recorded safe-alternative allocation where the operation class permits) — never a clobber;
5. journal every operation (move, rename, quarantine, cache write) with its result;
6. write each quarantined file's manifest entry **before** moving that file into quarantine, so the recoverable record always precedes the move (evidence-before-quarantine, Section 15);
7. update SQLite/cache from the validated plan and journal in a single controlled writer/transaction after verification;
8. write the handoff manifest only on overall success (Section 16);
9. write the end-of-prep audit log `photos-15-prep-log.json` on overall success (Section 16.1);
10. capture the end-of-prep database backup snapshot `photos-15-prep-ingest.db` on overall success — a consistent, atomic copy of the live `photos-00-ingest.db` (shared contract `photos-shared-contract.md` Section 13.4a);
11. on an **init run** (the workspace was uninitialized at start), write the root sentinel `photos-00-workspace-guard` as the **last** durable step, only after every operation above has succeeded (Section 3.1). Because the sentinel is written last, a crash anywhere earlier leaves the workspace uninitialized — the dump is already in `0-sources/` and the next run safely re-enters the init path. On an already-initialized workspace this step is a no-op (the sentinel exists);
12. emit the summary (the workspace lock is released at process exit per shared contract Section 2, not as a step of `execute`).

Execution must not patch or recompute a stale plan, and SQLite writes must never come from uncontrolled worker threads. The execute-time no-clobber check is a second, independent line of defence on top of the planner's collision analysis (Section 8): planning treats every on-disk and planned name as permanently occupied, and execution still re-verifies the actual target is free at the instant it acts. Neither replaces the other.

### 14.4 Execution idempotency and resume

Prep execution must be safe to re-run after a crash or partial application. Prep upholds the shared idempotency principle (shared contract `photos-shared-contract.md` Section 11): a crashed or interrupted run leaves the workspace in a state the next run can finish without redoing completed work and without double-applying anything.

**Prep re-plans; it does not resume the old plan.** This is a deliberate difference from geotag, which resumes the *same* `photos-24-executable-plan.json` because that plan embeds irreplaceable human decisions (geotag Section 29.1). Prep embeds no human decisions — it derives organization purely from filesystem and cache state — so after a crash the next invocation discards the interrupted plan and **plans afresh from the current workspace state**. Because every prep operation is idempotent by target state (a file already moved, already case-normalized, already separated, or already quarantined is detected as already-correct and produces a `no_op`/`already_correct`, per Section 13), re-planning naturally proposes only the operations still outstanding and completes the remaining work without repeating finished work. A stale interrupted plan is never patched or resumed; it is simply superseded (consistent with Section 14.3's rejection of stale plans).

**The filesystem is the source of truth; the cache is reconciled to it.** The one genuinely hazardous interval is a crash *between* a filesystem mutation and its corresponding cache write, leaving SQLite and the filesystem disagreeing (e.g. a move applied on disk whose `db_upsert` never committed, or a `db_remove` that committed before the file was actually moved). On the next run, inventory treats the filesystem as authoritative:

1. a cached row whose file is not where the cache says — but is explained by a completed on-disk move — is reconciled via the move-aware identity and ghost-prune rules (Sections 7.7, 10, 10.1), not trusted blindly;
2. where stat/identity cannot prove the cached fingerprint still valid, the affected file is re-stat'd/re-fingerprinted rather than relying on a possibly-stale cache row;
3. the controlled single-writer cache update (Section 14.3 step 7) commits only after the corresponding filesystem effect is verified, so a fresh run converges the cache back to filesystem truth.

**The journal supports reconciliation and observability, not blind replay.** Every mutation is journaled (Section 14.3 step 5), and the journal records what the interrupted run had done, which aids reconciliation and auditing. But prep does not replay the journal to "continue" the old plan — recovery is re-plan-from-current-state, with the journal as evidence, not as a script to resume.

**Snapshot rollback is the heavy-hammer option.** Where a pre-mutation ZFS snapshot was taken (Section 14.3 step 3; shared contract Section 3), the operator may roll the workspace back to its pre-run state and start over, instead of relying on forward reconciliation. This is the clean-slate recovery path when a partial run's state is easier to discard than to reconcile.

A successful prep run still writes the handoff manifest only as the final step (Section 14.3 step 8 / Section 16); a crash before that leaves no handoff (or the prior run's handoff), so geotag will not act on an incomplete prep run.

---

## 15. Quarantine model

Duplicate removal is recoverable, never destructive. Each duplicate is moved (not deleted) under `.photos-ingest-quarantine/<plan_id>/` preserving its original relative path, and a manifest records, per item: original path, quarantine path, retained counterpart, duplicate evidence (the content fingerprint), and the plan id. The quarantine directory is excluded from scanning, so re-running prep neither re-organizes nor re-quarantines already-quarantined files.

**Evidence is recorded before the move (evidence-before-quarantine).** The manifest entry is the only durable record of *why* a file was quarantined (the journal records the operation's result, not its duplicate evidence; the cache is committed once at the end of the run), and the quarantine tree is excluded from scanning, so a file moved into quarantine without its manifest entry would be invisible to every later run and stranded with no record. Prep therefore writes the manifest entry **first**, then moves the file. A crash or move failure in between leaves the file at its source — where the next run re-detects and re-quarantines it (with fresh evidence under a new plan id) — so the interrupted run's pre-written entry becomes at worst a benign, prunable orphan (a `<plan_id>/` holding only a manifest), never a quarantined file with no record of why.

### 15.1 Retention

Quarantine is the recoverable safety net for de-duplication, so prep **never deletes quarantined files automatically**. No run — however many times prep is re-run, and regardless of age — removes anything under `.photos-ingest-quarantine/` on its own. Quarantined copies persist until the user explicitly removes them (Section 15.3). This means quarantine grows monotonically across runs by design; the trade-off is accepted in exchange for never silently destroying a file that de-duplication set aside.

### 15.2 Recovery (manual restore)

A user may recover a quarantined file at any time by moving it out of `.photos-ingest-quarantine/` back into a managed folder (typically `0-sources/`). Prep does not provide a dedicated "un-quarantine" operation and does not track such a move as a special case; the restored file is simply re-evaluated as a normal newly-seen file on the next run:

1. it is inventoried, fingerprinted, and metadata-extracted like any other new mutable-side file;
2. it flows through the ordinary pipeline (extension normalization, redundant-JPEG separation, content de-duplication, chronological organization);
3. if its content still duplicates a retained copy (mutable-side or by-dest), de-duplication will quarantine it again — into the **current** run's `<plan_id>` directory, not the original one. This is safe and predictable: restoring a still-duplicate file simply re-quarantines it;
4. if the previously retained counterpart no longer exists (the user deleted or moved it), the restored file is no longer a duplicate and is organized normally.

Prep does not attempt to reconcile the old quarantine manifest entry with the restored file; the old entry remains as a historical record of that earlier plan, and the new disposition is recorded under the new run. The user is responsible for not leaving a file in two places (restored *and* still under quarantine); because the quarantine tree is excluded from scanning, a copy left behind under quarantine is neither re-organized nor counted as a live duplicate.

### 15.3 Pruning and reporting

Because quarantine is never auto-deleted, prep makes its growth visible and provides an explicit, opt-in way to reclaim the space:

1. **Reporting (every run):** the user-visible summary reports the current quarantine footprint — total quarantined files, total size, number of distinct `<plan_id>` directories, and the oldest/newest plan id present — so the user always knows quarantine is accumulating and by how much (Section 19).
2. **Explicit prune command:** prep exposes a `prune-quarantine` command that deletes quarantined files. It is the only operation that removes quarantine contents, it is never invoked implicitly by `plan`/`dry-run`/`execute`, and it acts only within `.photos-ingest-quarantine/`. It supports at least selecting by `<plan_id>` and/or by age, defaults to a non-destructive dry-run that lists what would be removed, and requires explicit confirmation (or an explicit `--yes`/equivalent) before deleting. It never touches live managed folders or `6-photos-by-dest`, and it runs under the same workspace lock as every other pipeline operation (shared contract `photos-shared-contract.md` Section 2). **`prune-quarantine` is the one command that still runs on a sealed (merged) workspace** (shared contract Section 13.7 item 2): because it only reclaims recoverable quarantine copies and touches no controlled content — no library file, no by-dest photo, no managed media, no DB identity/ledger row, no archival artifact — it is exempt from the seal that bars every media-mutating path. The seal exists to prevent re-processing or interleaving a second batch; reclaiming quarantine space does neither. So the seal guard (Section 6.2 item 1) blocks `plan`/`dry-run`/`execute` on a sealed workspace but **not** `prune-quarantine`.

Pruning is the user's decision, not the pipeline's: prep surfaces the cost and offers the tool, but the recoverable copies stay until the user chooses to discard them.

---

## 16. Handoff manifest

After a successful run, prep writes a machine-readable, non-editable handoff manifest at:

```text
.photos-ingest/photos-11-handoff.json
```

It is written only after the validated plan executed, the journal is complete, the final filesystem matches expected postconditions, and the SQLite/cache state matches the filesystem. It must include at least:

1. schema version and tool name (`photos-1-prep`);
2. the per-run identifiers (plan id, execution id) under a dedicated **`run_metadata`** block — segregated from the deterministic content, not at the top level (Section 16.2);
3. the cache fingerprint and content-fingerprint algorithm, and a top-level **`content_fingerprint`** that pins the handoff's deterministic content (Section 16.2);
4. folders scanned with mutability flags — the managed bands prep scans/organizes; **`1-strays` is excluded**, because strays are abandoned once moved there (written but never re-scanned) and are not part of the deterministic content downstream phases depend on (Section 3.2);
5. a sorted file list with workspace-relative path, size, mtime, fingerprint status, folder class, and per-file metadata status;
6. camera groups and by-dest destination-folder facts (Section 12.2);
7. metadata field-set/extractor versions and per-file metadata cache status;
8. diagnostics — duplicates/conflicts/blockers and warnings — recorded as per-run **audit**, not deterministic content (Section 16.2);
9. a `depends_on` block recording the upstream fingerprints used to create it (its `execution_journal` pointer, which names the per-run `journal-<plan_id>.json`, is run audit, Section 16.2).

The manifest must be deterministic for a given workspace state (sorted lists, no reliance on unordered iteration), with run metadata and diagnostics segregated from the deterministic content so the content stays byte-stable across reruns that change nothing but the run (Section 16.2). The manifest is the contract consumed by `photos-2-geotag` (`photos-2-geotag-workflow.md` Section 13): geotag depends on the handoff's **`content_fingerprint`** — which it **recomputes** from the handoff and re-verifies before use (`photos-2-geotag-workflow.md` Sections 4, 6) — rather than on the handoff's exact bytes, so a no-op prep re-run that refreshes only `run_metadata` does not restale geotag's downstream artifacts. The whole-file SHA-256 of the handoff remains its **integrity/archival** hash (shared contract Section 13), not the staleness trigger — consistent with surgical staleness (shared contract Section 4.2). Prep must write the handoff deterministically and never edit it in place. It lives in `.photos-ingest/`, which prep skips wholesale, so prep never inventories or fingerprints it as media (shared contract `photos-shared-contract.md` Section 5). When the only change since the last run is the user moving photos (from by-date into by-dest, or re-sorting between destinations within by-dest), the handoff is updated to reflect the new locations using carried-forward cache identity (Sections 10.1, 10.2), without re-reading the moved files.

### 16.1 End-of-prep audit log (`photos-15-prep-log.json`)

The handoff is prep's machine-readable *contract* for geotag; it is not, on its own, a human-readable per-photo audit record. To uphold the shared guarantee that **every phase leaves a complete, self-sufficient audit record at its end** (shared contract `photos-shared-contract.md` Section 13.0), a successful prep run also writes a human-readable transformation log at:

```text
.photos-ingest/photos-15-prep-log.json
```

This is prep's realization of the cumulative transformation log (shared contract Section 13.3). It records, per photo and keyed by content fingerprint, the ordered chain of everything prep did to that file — and it is **complete and stands on its own**: if geotag and merge never run, `photos-15-prep-log.json` is still a full, honest account of every transformation the files underwent in prep, exactly as if the later phases did not exist.

It must:

1. be **per-photo, content-fingerprint-keyed, human-readable JSON** in the same shape and discipline as the consolidated log (shared contract Section 13.3 items 2 and 5): pretty-printed, stably ordered, descriptive field names, human-legible values;
2. record, for each file, the ordered prep `journey` — at least: extension normalization (from/to), the initial consolidation into `0-sources` (only on the workspace's first/initializing run, Section 7.1), redundant-JPEG separation, content de-duplication / quarantine (with the retained counterpart and duplicate evidence), chronological organization into `4-videos-by-date`/`5-photos-by-date`/`2-missing-metadata`, and the provisional date-rename — each step attributable to the run that caused it;
3. record duplicates that were quarantined (origin path, quarantine path, retained counterpart, content fingerprint) so the recoverable-set-aside is auditable, not just the retained file;
4. be **derived from the validated plan and journal** of the run (and prior retained journals, shared contract Section 13.3a), introducing no new authority — it consolidates records prep already produced;
5. be written **only after a successful run** (the same gate as the handoff, Section 14.3 step 8), be **deterministic** for a given workspace state, and live in `.photos-ingest/` (skipped wholesale, never inventoried as media);
6. be **maintained incrementally across prep runs** like the handoff: re-prep that only recognizes a by-date→by-dest move (Sections 10.1, 10.2) updates the affected entries' locations from carried-forward identity without re-deriving unmoved files; a no-op prep run leaves it unchanged.

`photos-15-prep-log.json` is **carried forward, not discarded**: geotag's finalize consumes it (with the prep journals) as the prep portion of each photo's journey when it produces `photos-26-complete-log.json` (shared contract Section 13.3 item 6), appending geotag's steps rather than re-deriving prep's. Where both files exist, `photos-26-complete-log.json` is the authoritative full record and `photos-15-prep-log.json` remains as prep's standalone phase record. Prep fails (or warns and writes a clearly-partial log) if retained history is insufficient to reconstruct the prep journey (shared contract Section 13.3a) — it must not emit a log that looks complete but reflects only the last run.

### 16.2 Handoff determinism

The handoff manifest records **two kinds of thing**: a deterministic description of the post-prep workspace state, and per-run audit metadata. To keep the handoff **byte-deterministic for a given workspace state** — so geotag's dependency on it does not flip across reruns that changed nothing but the run — the two are kept separate, and a content fingerprint pins the deterministic part.

1. **Run metadata is segregated.** The per-run identifiers (`plan_id`, `execution_id`) live under a dedicated **`run_metadata`** block, **not at the top level**. The other run-scoped fields are likewise treated as **audit, not content**: the diagnostics (blockers, warnings, the quarantine footprint) and the `depends_on.execution_journal` pointer (which names the per-run `journal-<plan_id>.json`). None of these describes the *state of the workspace*; they describe *this run*, and they change run to run even when nothing about the organized result did.

2. **A content fingerprint pins the deterministic content.** The handoff carries a top-level **`content_fingerprint`** = SHA-256 over the canonical (sorted-key) serialization of the handoff with the run-scoped fields **removed**: `run_metadata`, `diagnostics`, `depends_on.execution_journal`, `content_fingerprint` itself, **and the per-run audit nested inside `camera_groups`/`destination_folders`** — the cache-freshness counts (extracted-vs-reused) and the conflicts/duplicates lists, which describe *this run's* cache behavior rather than the organized result. (Excluding the nested per-run audit, not just the top-level run blocks, is what actually makes the fingerprint stable — a no-op re-prep still re-derives those counts, so leaving them in would flip the fingerprint even though nothing about the workspace state changed.) The remaining content — the file inventory, the camera groups' identity facts, folder mutability, the cache fingerprint, and the config/extractor fingerprints — is deterministic for a given workspace state, so `content_fingerprint` is **byte-stable across reruns that change nothing but the run**. (Computing the fingerprint over a serialization with `content_fingerprint` itself excluded is what lets the value live *inside* the file it describes without being self-referential.)

3. **Geotag depends on the content fingerprint, not the file bytes.** Geotag records the handoff's `content_fingerprint` in its `depends_on` and re-verifies it by **recomputing it from the handoff** before use (geotag `photos-2-geotag-workflow.md` Sections 4, 6), exactly as it re-derives any other dependency fingerprint. A **no-op prep re-run** refreshes only `run_metadata` (and diagnostics/journal pointer), leaving `content_fingerprint` — and therefore geotag's `photos-21`/`22`/`23` — **unchanged**, so geotag is not needlessly restaled. A **real content change** (e.g. the inventory, a moved file, a changed camera group, an upstream fingerprint) changes `content_fingerprint` and **does** restale, exactly as it should. The whole-file SHA-256 of the handoff remains the **integrity/archival** hash (shared contract Section 13) — used to identify the exact bytes a given run produced — **not** the staleness trigger. This is the handoff's application of surgical staleness (shared contract Section 4.2): the staleness key is scoped to the content that actually matters, while the whole-file hash does the separate job of byte-integrity.

This is why the handoff is the one JSON artifact whose **dependency** check is a recomputed content fingerprint rather than a whole-file byte hash (shared contract Section 9.1): it is also the only JSON artifact prep updates incrementally and stamps with per-run audit, so a content-scoped fingerprint is what makes "deterministic for a given workspace state" actually hold across reruns.

---

## 17. Concurrency, determinism, and observability

Expensive work (fingerprinting, metadata extraction) may run concurrently under `-j` / `--jobs`, but concurrency must never change semantic results:

1. filesystem traversal and stat collection are single-threaded and deterministic, fixing the candidate list before any concurrent work;
2. candidate lists are sorted before submission and worker results aggregated deterministically;
3. two safe job counts produce the same semantic plan and the same dependency fingerprints for the same workspace — in fact the saved plan is **byte-identical** across job counts, since the count is not recorded in it (item 6);
4. SQLite writes go through a single controlled writer / collect-then-write transaction, never from worker threads;
5. **External tools run as persistent workers wherever the tool supports a long-lived mode**, to avoid paying process-startup cost per file:
   - **`exiftool`** runs as a persistent `-stay_open` worker — one process serves many files — restarted safely on crash.
   - **ImageMagick (`magick`/`identify`, the photo content fingerprint)** also supports a long-lived **command-stream mode** (its script/MSL interface — `magick -script -` fed independent commands over a pipe, or the named-pipe client-server form — keeps one process alive across many images), so the photo-fingerprint worker **should use it rather than spawning per file**. The persistent driver must **reset per-image state between commands** (an ImageMagick setting persists on the command line until reset, so one file's settings must never leak into the next) and delimit each file's `%#` signature output unambiguously. It falls back to per-file spawning only where the persistent path is unavailable.
   - **`ffmpeg` (the video stream-MD5 fingerprint)** has **no** stay-open/server mode, so a persistent worker is not possible for it — `ffmpeg` is **spawned per file** as a short-lived subprocess (with the same crash-safe restart and bounded per-file retry described below).

   In every case the worker is **crash-safe and retried**: a worker crash is recovered by safe restart, and a transient per-file failure is retried a small bounded number of times — equally for the photo (`identify`) and video (`ffmpeg`) fingerprint tools — before the file becomes a blocker. Partial or failed tool output is **never** persisted as a valid cache record; it surfaces as a clear blocker, never a silent success (Section 9);
6. job count (`-j`/`--jobs`) is a transient, machine-dependent runtime knob, not a semantic dependency: it is **not recorded in the saved plan** (nor in the workspace config file, nor the handoff). A workspace may be processed on different machines across runs, so baking a host's core count into the portable plan would be wrong; keeping it out also makes the plan byte-identical across job counts (item 3). It would only matter if a job count genuinely changed planned behaviour — which it must not.

Long-running execution is visible: phase-level log lines (lock, validate, scan, fingerprint, extract, dedup, apply, cache update, handoff, release) and live aggregate progress for concurrent fingerprinting/metadata, with in-place updates on a TTY and periodic plain lines when output is redirected. Progress output is never the only record of a mutation — the journal is durable; progress is transient and never a dependency.

---

## 18. End state and handoff to geotag

A successful prep run leaves:

```text
6-photos-by-dest/    unchanged (read-only)
5-photos-by-date/    timestamped photos, date-named, deduplicated
4-videos-by-date/    timestamped videos, date-named, deduplicated
3-redundant-jpgs/    JPEGs whose RAW master is retained
2-missing-metadata/  media with no usable timestamp
1-strays/<plan-id>/  non-media moved out of 0-sources this run (and prior runs' subfolders)
0-sources/           EMPTY — every file organized, set aside, quarantined, or moved to strays
workspace root       only folders (no loose files) — the base-is-folders-only invariant (Section 3.1)
.photos-ingest/photos-00-workspace-guard written last on an init run (Section 14.3 step 11)
.photos-ingest/photos-11-handoff.json   written
.photos-ingest/photos-15-prep-log.json  written (complete end-of-prep audit log)
.photos-ingest/photos-15-prep-ingest.db written (end-of-prep DB backup snapshot)
```

`0-sources/` is left **empty** at the end of every successful run: media is organized into the by-date bands (or `2-missing-metadata`), duplicates are quarantined, and non-media is moved to `1-strays/<plan-id>/` (Section 7.6). This empty inbox is exactly what geotag's "`0-sources` empty" gate checks (geotag `photos-2-geotag-workflow.md` Section 13). Non-media files are **not** left in `0-sources`; they are the strays in `1-strays/`, which the pipeline never processes again (Section 3.2).

At this point the workspace already holds a **complete, self-sufficient audit record of everything prep did**: the human-readable `photos-15-prep-log.json` (Section 16.1), a point-in-time backup image of the database as of the end of prep (`photos-15-prep-ingest.db`, shared contract `photos-shared-contract.md` Section 13.4a), the live SQLite database, and the handoff/summary. This record stands on its own — if the user never geotags or merges, it remains a full, honest account of the prep phase, exactly as if the later phases did not exist (shared contract Section 13.0).

The user then reviews `5-photos-by-date` and moves the **photos** into the appropriate destination folders under `6-photos-by-dest` (videos stay in `4-videos-by-date` and are never moved into by-dest, Section 2.4). The user moves **only photos** into by-dest: geotag requires `6-photos-by-dest` to contain photo files exclusively and hard-stops on any non-photo file — non-media or video — found there (geotag `photos-2-geotag-workflow.md` Sections 7.2, 7.3). Once the move is complete — `5-photos-by-date` empty, by-dest photo-only, and no `jpg`/`tif` development subfolders present under `6-photos-by-dest` — the geotag phase (`photos-2-geotag-workflow.md`) may run.

Re-running prep after the user's move must **not** re-fingerprint or re-read the moved files: prep recognizes them as moved (Section 10.1), carries their cached fingerprint/metadata forward to the new by-dest path, and simply updates the cache and handoff. by-dest media is never touched. Prep neither performs the move nor enforces the geotag preconditions.

---

## 19. User-visible outputs

Prep produces a textual summary that lets a reviewer confirm safety and progress, clearly separating:

1. media operations planned/executed;
2. no-op / already-correct files;
3. files scanned only for uniqueness/cache;
4. by-dest files scanned read-only (and confirmation by-dest was not mutated);
5. files recognized as moved from by-date into by-dest (cache carried forward, not rescanned);
6. duplicates against mutable folders vs. against read-only by-dest;
7. cache records reused, fingerprints recomputed, fingerprints carried forward after moves, cache records updated;
8. metadata records reused/extracted/failed, field-set and extractor versions;
9. camera groups found; native-GPS and missing/ambiguous-timestamp counts;
10. blockers (sealed workspace, loose root file, symlinks, forbidden sidecars, fingerprint failures, stale dependencies) and warnings (including, on a sealed workspace, a detected likely-new-dump);
11. confirmation that durable artifacts were written only after dependency validation;
12. the current quarantine footprint — total quarantined files, total size, number of distinct `<plan_id>` directories, and oldest/newest plan id present — since quarantine is never auto-deleted and grows across runs (Section 15.3);
13. confirmation that the end-of-prep audit log `photos-15-prep-log.json` was written (a complete, self-sufficient record of the prep phase, Section 16.1), and that the end-of-prep database backup snapshot `photos-15-prep-ingest.db` was captured (shared contract `photos-shared-contract.md` Section 13.4a).

---

## 20. Non-goals (prep must not do)

`photos-1-prep` must not expose behaviour for:

1. geotag JSON generation or validation;
2. camera-time policy or folder-timezone decisions;
3. GPX matching/interpolation/extrapolation;
4. manual GPS fallback planning;
5. time-offset calculation;
6. EXIF/QuickTime timestamp write planning or execution;
7. GPS metadata write planning or execution;
8. `GPSProcessingMethod` marker writes;
9. rename/relocation caused by corrected timestamps;
10. any `geotag` command.

Passive extraction and caching of fields the geotag phase will need (Section 12) is allowed and required; making decisions from them is not.

---

## 21. Idempotency and staleness examples

```text
Uninitialized folder with an as-arrived dump (no sentinel)
  -> prep initializes: base files/trees moved into 0-sources (no flatten),
     0-6 structure + control dir created, dump organized, sentinel written LAST
  -> base ends with only folders; 0-sources empty

Crash during init (before the sentinel is written)
  -> next run sees no sentinel -> re-enters init harmlessly
     (dump already in 0-sources; structure re-created; continues)

Second run, unchanged workspace
  -> no media operations
  -> cache hits reported, handoff unchanged

New dump added to 0-sources (initialized workspace)
  -> only the new files are fingerprinted/extracted and organized
  -> non-media moved to 1-strays/<plan-id>/; 0-sources left empty again
  -> existing files scanned for uniqueness/cache only

Loose file appears at the workspace root (initialized workspace)
  -> hard block (Section 6.2 item 2): dumps belong in 0-sources
  -> strict: any root file blocks, dotfiles included

Non-managed folder or symlink appears at the workspace root (initialized)
  -> same hard block as a loose root file (Section 6.2 item 2):
     a stray folder belongs INSIDE 0-sources; a symlink is barred (escape)

A managed 0-6 folder is missing (initialized workspace)
  -> hard block (Section 6.2 item 7): the 0-6 structure is an invariant
  -> warns the structure was disturbed (likely deleted) and names the
     missing folder(s); operator recreates them and re-runs
  -> prep never silently re-creates folders on a non-init run

Sealed workspace (prior successful merge)
  -> hard stop, nothing touched (Section 6.2 item 1)
  -> if files are seen at the root or in 0-sources, also warn: likely new dump,
     this workspace is done -> move it into a FRESH workspace by hand

User restored a file out of quarantine into 0-sources
  -> re-evaluated as a normal new file (no special "un-quarantine" path)
  -> if it still duplicates a retained copy, re-quarantined under the
     current plan_id; otherwise organized normally
  -> old quarantine manifest entry left as historical record

User moved a file from 5-photos-by-date into 6-photos-by-dest
  -> recognized as a move (matching size/mtime/basename)
  -> cached fingerprint/metadata carried forward, no rescan
  -> old cache row dropped, handoff updated; by-dest untouched

File size/mtime changed
  -> cached fingerprint + metadata stale -> recompute
     (a metadata-only edit recomputes to the SAME fingerprint)

Config changed
  -> config fingerprint changes -> plan dependency stale
  -> a previously generated plan is rejected at execute time

Config value invalid (e.g. zfs snapshot prefix contains a '/' or whitespace,
or gpx_root is malformed)
  -> config sanity-validation fails (Section 6.3)
  -> hard blocker, offending field named, no executable plan produced

By-dest file changed before execute (affecting a uniqueness decision)
  -> recorded by-dest precondition stale -> plan rejected before mutation

Fingerprint failure on a mutable-side media file
  -> equality-based duplicate decision blocked -> reported blocker
  -> (an other-class file has no fingerprint by design — not a failure)

Symlink (incl. nested directory symlink) or .xmp/.dop/.pp3 sidecar present
  -> hard block, no executable plan produced
  -> the symlink bar is comprehensive: file symlinks, nested directory
     symlinks inside a dump or managed folder, a managed folder that is
     itself a symlink, and a root dump symlink are all forbidden escapes
     (Section 6.2 item 3)
```

---

## 22. Summary

This section restates the rules established above as a single reference. On any apparent conflict, the numbered specification sections above govern over this summary.

The prep workflow is:

```text
1. Initialize if needed (uninitialized -> move base dump into 0-sources, no flatten;
   create 0-6 structure + control dir; sentinel written LAST on success).
2. Inventory; block on a sealed workspace; any misplaced root entry (loose
   file, non-managed folder, or symlink) on an initialized workspace; a
   missing 0-6 folder (disturbed structure); symlinks anywhere (incl. nested
   directory symlinks); forbidden sidecars.
3. Reuse cache for unchanged files; recognize by-date -> by-dest moves;
   fingerprint + extract metadata only for genuinely new/changed media.
4. Take the dump from 0-sources (no flattening; collisions resolved in memory).
5. Normalize extension case (lowercase, collision-safe).
6. Separate redundant JPEGs (RAW master retained) into 3-redundant-jpgs.
7. Deduplicate by content fingerprint; quarantine extra copies recoverably;
   by-dest is always the retained copy and is never mutated.
8. Organize by source-naive timestamp:
   videos -> 4-videos-by-date, photos -> 5-photos-by-date,
   untimestamped media -> 2-missing-metadata, non-media -> 1-strays/<plan-id>/.
   0-sources is left EMPTY.
9. Reconcile the SQLite cache (move carry-forward, upserts, ghost prune).
10. Execute only the validated plan: lock, snapshot, no-clobber ops
    (re-verified and atomic at execute time), journal, controlled cache update.
11. Write the dependency-fingerprinted handoff manifest, the complete
    end-of-prep audit log (photos-15-prep-log.json), the end-of-prep
    DB backup snapshot (photos-15-prep-ingest.db), and — on an init run —
    the root sentinel LAST, all on success.
```

The most important rules are:

```text
Plan, validate, execute, journal — never re-decide at execution time.
0-sources is the one inbox; after init the base holds only the managed folders
  (any root file, stray folder, or symlink blocks; a missing 0-6 folder blocks too).
Symlinks are never followed — file, nested-directory, managed-folder-as-symlink,
  and root dump symlinks are all forbidden escapes.
The sentinel is written last, so a crashed init is safely re-runnable.
0-sources is left empty every run; non-media goes to 1-strays (inert, never re-processed).
6-photos-by-dest is read-only; by-dest always wins a duplicate tie.
A file moved into by-dest is recognized, not rescanned — just fix the handoff.
Media is identified by a decoded-content fingerprint (ImageMagick identify / ffmpeg
  stream MD5), invariant under metadata writes; byte SHA-256 is for artifacts only.
All media operations are no-clobber — planned and re-verified atomic at execute time;
  duplicate removal is recoverable quarantine.
A sealed workspace is done: prep refuses and never touches it.
All human-authored config is sanity-validated before use; an invalid value blocks.
Prep caches time/GPS-relevant facts passively but makes no time/GPS decision.
Prep leaves a complete, self-sufficient end-of-prep audit log — whole even if no later phase runs.
No durable artifact is created from stale upstream inputs.
```

Prep ends with media organized into by-date, ready for the user to place into `6-photos-by-dest` before geotag (`photos-2-geotag-workflow.md`) begins.
