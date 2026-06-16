# Photos Pipeline Shared Contract (`photos-shared-contract`)

## 1. Purpose and status

This document is the single authoritative home for facts that span the phases of the photos pipeline:

1. the preparation phase, `photos-1-prep` (`photos-1-prep-workflow.md`);
2. the time/GPS calibration phase, `photos-2-time-gps` (`photos-2-time-gps-workflow.md`);
3. the library-merge phase, `photos-3-merge` (`photos-3-merge-workflow.md`).

Anything the phases must agree on — the workspace lock, the pre-mutation snapshot mechanism, the shared configuration object, the workspace control directory, the camera-group identity key, the filename timestamp format, the GPX root, the input-validation discipline, the execute-time no-clobber/atomicity rule, and the end-to-end operator loop — is defined here and is authoritative here. The phase specifications reference this document rather than restating these facts, so the contract cannot drift between them.

The merge phase joins the pipeline as a third phase that runs *after* a workspace has been calibrated and finalized: it merges the finalized `6-photos-by-dest` staging tree into the user's permanent library. Most of this contract was written for the two-phase (prep + calibration) pipeline and continues to govern it; where a fact applies only to merge, that is called out explicitly (e.g. Sections 5, 10, 13, the library facts in Section 15). Where this document says "both phases," it means **prep and calibration** for facts specific to those two (e.g. camera grouping, Section 6; naming a file from its timestamp, Section 7). Several facts it states in "both phases" language, however, apply to **all three phases, merge included** — notably the shared configuration (Section 4), the workspace lock (Section 2), idempotency (Section 11), authored/derived-from-recorded-input mutation (Section 12), and the execute-time no-clobber/atomicity rule (Section 15); merge upholds these through its own spec, and where that is the case it is noted. Merge is a distinct, later phase with a narrower contract surface, called out per section.

This is a workflow/contract specification, not a script implementation specification. It describes *what* the phases must share and uphold, not the classes or modules that implement it.

---

## 2. Workspace lock

The pipeline is protected by a single workspace-wide lock. There is exactly one lock for the whole workspace, shared by every pipeline command, and it enforces **total mutual exclusion of pipeline processes**: at most one pipeline invocation may be running against a given workspace at any time. This excludes every concurrent combination — two prep runs, two calibration runs, a prep run and a calibration run, the merge command (`photos-3-merge`, Section 13.5) overlapping with either, or any of these overlapping with the finalize/archive command (Section 13) or prep's `prune-quarantine` command. Any command that reads or touches the workspace takes the lock; only one holds it at a time. The merge phase additionally takes a separate library-side lock for the duration of its run (Section 15.2), so two merges into the same library — even from different workspaces — cannot overlap; that library lock is independent of, and held in addition to, the workspace lock.

The lock guards the entire run, not just mutation:

1. The lock is acquired at process startup, immediately after the workspace root is resolved and the root sentinel (`photos-00-workspace-guard`) is verified, and **before any planning, scanning, fingerprinting, metadata extraction, dry-run, or execution begins**. Planning is non-mutating, but it must still not run concurrently: a plan computed against a workspace another process is reading or mutating is untrustworthy, so planning is inside the lock too.
2. The lock is held for the duration of a run — across plan, dry-run, execute, cache update, and handoff/artifact writes — and released when the script finishes (success or failure). It is per-run, not a persistent lock on the workspace between runs: when no script is running, the workspace is unlocked.
3. Acquisition is **fail-fast, not blocking**. If the lock is already held by another run, the invocation does not wait: it exits immediately with a clear message that the workspace is locked by an in-progress run, and performs no scan, no planning, and no mutation. It produces no plan, no dry-run report, and no artifact.
4. The lock must be released on normal exit and on error. A lock left behind by a crashed process (a stale lock) must be detectable as stale — e.g. by recording the owning process identity/liveness and start time — and recoverable, so a crash does not permanently wedge the workspace. Stale-lock takeover must be conservative: only a lock whose owner is provably gone may be reclaimed.

Because the lock covers planning as well as execution, the per-phase `plan` / `dry-run` / `execute` lifecycles described in `photos-1-prep-workflow.md` Section 14 and `photos-2-time-gps-workflow.md` Section 29 all run with the lock already held; those sections do not re-acquire or independently scope the lock. This whole-run lock is independent of, and stricter than, the dependency-revalidation discipline (Section 9): revalidation guards against *stale* inputs across separate runs, while the lock guarantees runs never overlap in the first place.

---

## 3. Pre-mutation snapshots: the `zfs` block

Each phase that mutates can take an optional pre-mutation snapshot before applying any planned mutation, using the same mechanism so the phases behave identically and cannot diverge (prep and calibration snapshot the workspace tree; merge optionally snapshots the library volume — closing note below). **Snapshots are an optional extra safety layer, not a requirement.** The pipeline operates fully and safely without them: correctness and recoverability rest on the journal, recoverable quarantine, no-clobber operations, and filesystem-as-truth reconciliation (prep Section 14.4; calibration Section 29.1; merge Section 8). Snapshots add a clean-slate rollback path on top of those for operators whose filesystem supports it; they are not the basis of the safety model.

1. The snapshot mechanism is configured by the `zfs` block in the workspace config `photos-00-config.json` (Section 4). It is disabled by default unless explicitly configured; ZFS is not assumed and is not a prerequisite for running the pipeline.
2. Snapshots are keyed by plan id, so each plan's pre-mutation state is independently identifiable.
3. `snapshots_required` governs strictness: when true, a failure to take a required snapshot is fatal and execution aborts before mutating; when false (or when snapshots are not configured), execution proceeds without a snapshot and relies on the journal/quarantine/no-clobber safety layer above.
4. When taken, the snapshot is taken after the plan has been dependency-validated and the lock acquired, but before the first mutation.

The mechanism is named for ZFS because that is the reference implementation, but it is deliberately the *only* part of the pipeline that touches a specific filesystem feature, and it is optional; everything else is filesystem-agnostic.

`photos-1-prep-workflow.md` Section 14.3, `photos-2-time-gps-workflow.md` Section 29, and `photos-3-merge-workflow.md` Section 10.3 invoke this mechanism; none redefines it. (Merge's optional snapshot targets the **library** volume, where its placements land, rather than the workspace tree — see the merge spec.)

---

## 4. Shared configuration (`photos-00-config.json`)

All three phases read a single shared configuration for the whole pipeline. The config is a **workspace artifact** — a JSON file, `photos-00-config.json`, living alongside the other persistent artifacts in the control directory `.photos-ingest/` — not an ambient in-code global. The phases consume different keys from it (prep and calibration the bulk; merge the library-merge area, Section 4.3 item 7) but never maintain separate configs.

### 4.1 A pinned, per-workspace artifact

Making the config a file binds it intrinsically to the workspace and to everything processed in it:

1. **Seeded by prep.** On a prep run, if `photos-00-config.json` is absent, prep creates it from the in-code default template (`photos_utils.CONFIG`). If it is present, prep uses it as-is. The in-code `photos_utils.CONFIG` is therefore only a **default template for seeding a fresh workspace**; once the file exists, the workspace copy is authoritative and governs all processing in that workspace, regardless of what the code's defaults later become.
2. **Prep is the sole writer of config in the data pipeline; the user hand-edits.** Like the handoff, the config file is written by prep alone in the prep→calibrate→merge data flow (prep seeds it once). (The SQLite DB is shared-write across phases — prep owns its cache/identity content, calibration its derived regions (resolved-UTC cache and manual-GPS pre-state ledger), and merge its library-file fingerprint cache, all disjoint, Section 13.4 — but the config file, like the handoff, has a single writer in that flow: prep.) The one narrow exception is the **one-time `init-library` setup command** (merge spec `photos-3-merge-workflow.md` Section 4), which, when run from inside a workspace with an explicit library path, may write the single `library_root` key — and only that key — into config, as an operator convenience for recording which library this workspace merges into. That setup write is not part of the merge *data path*: merge's `plan`/`dry-run`/`execute` are strictly **read-only** with respect to config, exactly like calibration, which never writes it. To change any other configuration, the user edits the JSON by hand — it is an authored input in the same sense as the decision fields (Section 12).
3. **Hashed like every other artifact.** Because it is a file, it is SHA-256'd and folded into the dependency cascade (Section 9) exactly as the handoff and numbered artifacts are — closing the gap where an ambient config could change a run without leaving a trace. Its whole-file SHA-256 is recorded for integrity (and in the archival manifest, Section 13).
4. **Archived.** It is part of the archival package (Section 13.2), so a future reader knows not only what was decided but **under what configuration**.
5. **In the control directory.** It lives in `.photos-ingest/` (Section 5), which prep skips wholesale, so prep never treats it as managed media or folds it into the media cache fingerprint.

### 4.2 Granular staleness, plus a whole-file hash

The config is the root of the dependency cascade (Section 9), but staleness stays **surgical**: the fingerprints remain field-scoped, so a change to one area invalidates only what depends on it. A GPX-threshold edit restales GPS/plan artifacts but not the rename plan; a filename-format edit restales renames but not GPS placement. The whole-file SHA-256 is used for integrity and archival, **not** as the staleness trigger — collapsing all staleness to a single whole-file hash would needlessly restale unrelated artifacts on any edit and is explicitly not done.

So two things are derived from the file: (a) field-scoped fingerprints (filename-format, camera-time/timezone policy, GPX thresholds, camera-group-key version, snapshot policy, …) that drive precise staleness; and (b) one whole-file hash for integrity/provenance.

**The whole-file config fingerprint has a deliberate *second* role beyond integrity: a coarse, conservative staleness trigger.** It is carried in the executable plan's `depends_on` (calibration `photos-2-time-gps-workflow.md` Section 28, within the flattened dependency set of Section 5) so that **any** config edit changes it and restales the **plan** — a catch-all guaranteeing no config-driven change is ever silently missed, even one in an area without its own field-scoped fingerprint. This is intentional belt-and-braces *alongside* the field-scoped fingerprints, not a contradiction of surgical staleness: the field-scoped fingerprints keep the **expensive** derived caches from restaling on unrelated edits (resolved UTC is keyed on the time-policy subset, calibration Section 22.1; renames on the filename-format fingerprint), while the **cheap-to-rebuild** plan simply re-plans on any config change. The two triggers therefore have deliberately different scopes: a config edit *outside* the time policy re-plans but does **not** restale already-resolved UTC. What §4.2 rules out is collapsing the *surgical* caches onto the whole-file hash; using that hash as an additional coarse trigger for a cheap artifact is consistent with — indeed protective of — surgical staleness.

### 4.3 Config areas

Config areas relevant across phases include, at least:

1. the `zfs` snapshot block and `snapshots_required` (Section 3);
2. the workspace control directory (Section 5);
3. camera-group **classification**: `camera_time_and_timezone_policy.device_groups` (`phones`, `fixed_clock_cameras`) (Section 6) — the only camera-grouping value that lives in config. The derivation *version*, `CAMERA_GROUP_KEY_VERSION`, is **not** a config field: it is a code constant (defined in `photos_utils`) that versions how `camera_group_key` is computed and participates in the dependency fingerprints (Section 6, Section 9), so a change to the derivation is detectable. The user classifies device groups in config; the user never sets the key-derivation version;
4. the filename timestamp format, the shared key `filename_timestamp_format` (Section 7);
5. the GPX root and GPX matching thresholds, e.g. `gpx_root`, `gpx_direct_match_max_seconds`, `gpx_interpolation_max_gap_seconds`, `gpx_interpolation_max_distance_meters` (Section 8);
6. camera-time/timezone policy flags, e.g. `single_anchor_auto_apply`, `multi_anchor_auto_apply` (consumed by calibration);
7. the library-merge settings, e.g. `library_root` and the merge collision/placement policy (consumed by merge, Section 13.5 and the merge spec `photos-3-merge-workflow.md`).

Every config value that comes from the user is subject to the input-validation discipline of Section 14 before it is used — a path must resolve sanely, a ZFS snapshot prefix must be a syntactically valid snapshot component, an IANA timezone must be a real zone, and so on. Validation is part of consuming config, not a separate optional pass.

The precise key names, defaults, and which-phase-consumes-which are finalized in the sections cross-referenced above (Sections 5–8). This list is the conceptual surface; the per-key detail lives in those sections.

---

## 5. Control directory: everything lives in `.photos-ingest/`

All pipeline control and artifact files live inside a single workspace control directory, `.photos-ingest/`. Nothing pipeline-related sits among managed media or at the workspace root. Prep walks the workspace to inventory media and skips `.photos-ingest/` **wholesale** (as a whole subtree), so a control or artifact file can never be mistaken for a photo. There is no per-file "ignore list" to maintain — consolidating everything in one skipped directory replaces the basename registry that earlier designs needed.

### 5.1 Contents

```text
.photos-ingest/
  photos-00-config.json            workspace configuration (seeded by prep, Section 4)
  photos-00-workspace-guard        workspace root sentinel: marks the workspace as INITIALIZED (written last by prep on init, prep photos-1-prep-workflow.md Section 3.1)
  photos-00-sealed.json            terminal/sealed marker, written by a successful merge ALONGSIDE the guard (a separate file, not a field inside the guard) — its presence seals the workspace (Section 13.7)
  photos-00-ingest.db              SQLite identity/metadata cache + derived caches (live working DB, Section 13.4)
  photos-15-prep-ingest.db         prep-phase artifact: DB backup snapshot, end of prep (Section 13.4a)
  journal-*.json                   execution journals
  photos-10-prep-plan.json         prep-phase artifact: prep plan (written by `plan`, consumed by `dry-run`/`execute`; see "Canonical plan persistence" below)
  photos-11-handoff.json           prep-phase artifact: handoff manifest
  photos-15-prep-log.json          prep-phase artifact: end-of-prep audit log (Section 13.3 / prep 16.1)
  photos-21-time-decisions.json    calibration-phase artifact
  photos-21a-gps-drift-validation.json  calibration-phase artifact: GPS-drift validation gate between 21 and 22 (§21a)
  photos-22-gps-decisions.json     calibration-phase artifact
  photos-23-executable-plan.json   calibration-phase artifact
  photos-24-execution-summary.json calibration-phase artifact
  photos-25-complete-log.json      calibration-phase artifact: full transformation log (prep+calibrate, at finalize, Section 13.3)
  photos-25-calibrate-ingest.db    calibration-phase artifact: DB backup snapshot, end of calibration (Section 13.4a)
  photos-31-merge-summary.json     merge-phase artifact: library-merge summary (Section 13.5)
  photos-35-merge-log.json         merge-phase artifact: full transformation log (prep+calibrate+merge, Section 13.3)
  photos-35-merge-ingest.db        merge-phase artifact: DB backup snapshot, end of merge (Section 13.4a)
  gpx/                             gpx_root, when configured to live here (Section 8)
```

**Numbering convention.** The first digit identifies the phase that produces the file — nothing more:

```text
0X  workspace infrastructure (phase-neutral): config, guard, live database
1X  prep-phase artifacts        (currently: 10 = prep plan, 11 = handoff, 15 = prep audit log + prep DB snapshot)
2X  calibration-phase artifacts (currently: 21–25; 25 = complete log + calibration DB snapshot)
3X  merge-phase artifacts        (currently: 31 = merge summary, 35 = merge log + merge DB snapshot)
```

That is the whole meaning of the scheme: read the first digit to know the producing phase. The second digit is just a sequence number within the phase and carries no further significance — absent numbers (there is no `photos-07`, no `photos-12`–`14`, etc.) are not reserved, not headroom, and not missing; they simply don't exist. Do not infer anything from a gap. A number may be shared by sibling end-of-phase records that differ only by extension — `photos-15-prep-log.json` and `photos-15-prep-ingest.db` are both "the end-of-prep record," one the human-readable log and one the DB image; likewise `photos-25-complete-log.json` and `photos-25-calibrate-ingest.db`. The full filename (number + name + extension) is the identifier, not the number alone. One artifact carries a **letter suffix**, `photos-21a-gps-drift-validation.json`: it was inserted between `photos-21` and `photos-22` after the numbering was established, and the `21a` form keeps its file-sort position aligned with its pipeline position (it runs after time-decisions, before gps-decisions). The letter is just part of that filename identifier; it implies nothing beyond "a calibration artifact that sequences between 21 and 22." The shorthand `photos-0X-*` (and `1X`/`2X`/`3X`) refers to a band of numbered artifacts collectively. (Note: the artifact-number bands `0X`–`3X` are unrelated to the workspace's numbered media folders `0-sources`…`6-photos-by-dest`; the folder `1-strays/` is a media-tree folder, not an artifact band.)

Skipping is directory-level: prep skips `.photos-ingest/`, `.photos-ingest-quarantine/`, and `.git` as whole subtrees, plus dot-prefixed files (never inventoried as media), and the strays folder `1-strays/` in its entirety (all `<plan-id>` subfolders) (`photos-1-prep-workflow.md` Sections 3, 3.2). Hidden dotfiles arriving in a **dump area** (the workspace root on an init run, or the `0-sources/` inbox) are not merely skipped but swept to the recoverable quarantine so a dump leaves no hidden litter (`photos-1-prep-workflow.md` Sections 3, 15). A `gpx_root` misconfigured to resolve inside the managed `0`–`6` tree is the one case needing an extra subtree skip (Section 8).

(`1-strays/` is a media-tree folder at the workspace root, holding non-media files prep moved out of `0-sources` per run, structure preserved, in per-`<plan-id>` subfolders — prep writes to it but never scans it, and the pipeline never processes its contents again. It is *not* an artifact band and *not* a phase output; see prep Section 3.2.)

**Canonical plan persistence.** Every phase's plan/decision artifact lives at a **fixed, canonical control-dir path** — prep's `photos-10-prep-plan.json`, calibration's `photos-21`/`photos-22`/`photos-23`, merge's `photos-30-merge-plan.json` — and the phase always reads and writes it there: the planning command (`plan` / calibration `run`) writes the canonical file and the validating/applying commands (`dry-run` / `execute`) read it from the same place. **No command takes a path flag telling it where to put or find its plan**; the canonical location is the contract. A planning command **prints the path it saved to** so the operator can review the artifact without hunting for it, and a validate/apply command that finds the canonical file missing stops and directs the operator to plan first. Because the full plan is now a persisted artifact, **`dry-run` reports a concise summary** (operation/move counts by type, blockers, and the path to the full plan) rather than dumping the whole plan to the terminal — this is still not a simulation (the summary is computed from the real serialized plan, not a separate virtual-filesystem walk), it simply summarizes the on-disk plan instead of printing all of it. Re-planning **never clobbers** a prior plan or hand-edited decision file: when the regenerated artifact **differs** from what is on disk, the existing artifact is first renamed aside under the shared incremental `-NNN` suffix (Section 7.2) — e.g. `photos-10-prep-plan-001.json` — and the backup location is announced, so a superseded plan and any authored decisions stay recoverable. An **unchanged** re-run (byte-identical regenerated content — e.g. calibration re-running with no edited decisions) writes nothing and backs up nothing, so the iterative decision-editing loop does not accumulate redundant backups. A plan carrying a fresh plan id differs every run, so re-planning always preserves the prior plan. (Per-run *journals* keep their existing `journal-<run_id>.json` naming, Section 5 listing; this convention governs the plan/decision artifacts.)

### 5.2 The handoff is hashed despite living in the skipped directory

`photos-11-handoff.json` lives in `.photos-ingest/` and so is never inventoried as media. That is independent of its role as a dependency: calibration fully verifies it before use — by **recomputing its `content_fingerprint`** (the content-scoped staleness key prep stamps on it) and comparing it to the value recorded in the dependency block (`photos-2-time-gps-workflow.md` Section 4; prep `photos-1-prep-workflow.md` Section 16.2). Its whole-file SHA-256 is retained as an integrity/archival hash (Section 13), but the dependency check is the recomputed content fingerprint, so a run-only refresh of the handoff does not restale downstream (Section 9.1). So the handoff is invisible to prep's media scan yet fully verified as a dependency by calibration — verified by content, not by exact bytes.

Prep `photos-1-prep-workflow.md` Section 3 and calibration `photos-2-time-gps-workflow.md` Section 8.1 reference this control-directory model rather than maintaining their own ignore lists.

### 5.3 Workspace structural integrity: symlinks and the base-is-folders invariant

Three structural facts about an **initialized** workspace are shared by every phase, because each phase relies on them when it scans, and a violation of any one means the workspace was disturbed out-of-band and must not be processed silently. They are stated here once; the phase specs enforce them (prep is the structural gatekeeper — it is the only phase that creates the managed workspace `0`–`6` folders and the only one that walks the full tree to organize media; the other phases uphold the same guards at their own entry and never create or repair the workspace structure, though merge does create ordinary destination subdirectories *under `library_root`*, which is library placement, not part of the managed tree).

1. **The base holds only the managed folders and control/dot directories.** After initialization the workspace root contains exactly the numbered managed folders (`0-sources`…`6-photos-by-dest`) plus the control/dot directories (`.photos-ingest/`, `.photos-ingest-quarantine/`, `.git`, dotfiles/dotdirs). **Any other root entry is a misplaced dump and a hard block**, treated identically whether it is a loose **file**, a **non-managed folder** (a dumped folder belongs *inside* `0-sources/`, never loose at the base), or a **symlink**. The one and only inbox is `0-sources/`. (This is the base-is-folders-only invariant of prep Section 3.1; calibration applies the same guard at startup, calibration Section 13, and merge applies it as precondition 0a, `photos-3-merge-workflow.md` Section 3. It does not apply to an *uninitialized* workspace, where root files and folders are the expected first dump and trigger initialization — except that a symlink at the base is still barred, see item 2.)

2. **Symlinks are barred everywhere among managed files — including nested directory symlinks.** The pipeline never follows or organizes a symbolic link, because following one would let a planned read or write reach a target **outside** the managed tree — a pipeline escape that breaks the no-clobber and "originals never lost" guarantees (Section 15) and the closed-world assumption the content fingerprint and de-duplication rest on. The bar is comprehensive and covers every place a link can appear: a **file symlink** anywhere; a **nested directory symlink** encountered inside a dump tree or inside any managed folder (the walk does not descend into it, but its mere presence is a hard blocker, never a silent skip); a **managed folder that is itself a symlink** (blocked before it is walked); and a **root dump entry that is a symlink** (item 1). In every case the phase reports the offending path and produces no executable plan or downstream artifact. Prep enforces this across the whole tree it walks (prep Section 6.2 item 3); because `6-photos-by-dest` is read-only for prep yet still scanned by it, prep is also the gatekeeper for links that appear under by-dest, and the mandatory re-prep after any by-dest change (Section 10) means calibration and merge only ever consume a handoff prep built with no forbidden link present (calibration Section 7.2; merge `photos-3-merge-workflow.md` Section 3 precondition 3). Calibration and merge additionally bar symlinks at the workspace root at their own startup (calibration Section 13; merge precondition 0a).

3. **The managed `0`–`6` structure is complete and is never silently rebuilt.** Prep creates the full structure exactly once, at initialization, and never removes a folder. On an initialized workspace a **missing** managed folder is therefore evidence the structure was deleted or moved out-of-band — a hard block, not a state any phase produces. Prep does **not** auto-recreate the structure on a non-init run (folder creation is an init-only action), and no phase organizes media into a structure it had to silently rebuild, because doing so could mask a real loss (a deleted folder may have taken organized media with it). The block names the missing folder(s), warns that something is wrong, and directs the operator to restore them (an empty folder satisfies the structure check; recovering any lost media — e.g. from an optional pre-mutation snapshot, Section 3 — is the operator's task) and re-run. (Prep Section 6.2 item 7; calibration Section 13; merge `photos-3-merge-workflow.md` Section 3 precondition 0c. An *empty* `0-sources/` is normal — the steady end-state, not a missing folder.)

These guards are structural, evaluated at each phase's startup right after the lock and the seal check (Section 2, Section 13.7), before any scan, plan, or mutation. They compose with — but are distinct from — the input-validation discipline (Section 14, which checks *authored values*) and the dependency cascade (Section 9, which checks *change*): these check the *shape of the workspace itself*.

---

## 6. Camera-group identity (`camera_group_key`)

Both phases identify a camera/device by a single derived key so grouping is computed once (by prep) and reused (by calibration), never reinvented.

1. Prep computes `camera_group_key` from device-identity metadata (serial/make/model/owner fields) and emits it in both the handoff manifest and SQLite.
2. The derivation is versioned by `CAMERA_GROUP_KEY_VERSION`; the version participates in metadata-freshness and dependency fingerprints so a change to the derivation is detectable rather than silently mixing old and new keys.
3. Calibration reuses prep's `camera_group_key` rather than recomputing identity. Mobile vs fixed-clock *classification* is a separate config concern, governed by `camera_time_and_timezone_policy.device_groups` (`phones` = mobile, `fixed_clock_cameras` = fixed-clock) in the shared config (Section 4). A group is "known" when its key is listed under one of those classes.

`photos-1-prep-workflow.md` (Section 12) emits the key; `photos-2-time-gps-workflow.md` (Section 16) consumes and classifies it.

---

## 7. Filename timestamp format

Both phases name files from a timestamp using a **single shared, config-driven format**. There is one format key for the whole pipeline, not one per phase, so the provisional names prep assigns and the final names calibration assigns are guaranteed to share the same textual shape and can never drift apart.

### 7.1 The shared key

The format lives in the shared configuration (Section 4) under a phase-neutral key:

```text
filename_timestamp_format   (photos-00-config.json, default "%Y-%m-%d--%H-%M-%S")
```

The default produces a timestamp component of the form:

```text
YYYY-MM-DD--HH-MM-SS
```

The format is never hard-coded in either phase; both read this key, and the key participates in the dependency cascade (Section 9). Changing it makes any artifact whose names depend on it stale — in prep, the by-date organization; in calibration, the executable rename plan.

> The calibration specification historically referred to this key as `calibration_filename_timestamp_format`. It is the **same** key as `filename_timestamp_format` defined here; the phase-neutral name is authoritative because the key is shared, and any remaining phase-specific name is an alias for it.

### 7.2 The differentiating suffix

A file whose timestamp component collides with one already taken receives a zero-padded differentiating suffix, allocated deterministically and no-clobber:

```text
<timestamp>.ext        first file with a free base name (no suffix)
<timestamp>-001.ext    first collision
<timestamp>-002.ext    second collision
```

The suffix (`-NNN`) is allocated **no-clobber against a per-run, case-insensitive occupied-name set** — every on-disk and planned name is treated as occupied for the duration of the allocation loop — so two files never collide. *Which* free name is chosen differs by phase, and deliberately so:

- **Prep and calibration** take the **first free** name: the bare `<timestamp>.ext` when available, otherwise the lowest free `-NNN`. Bare-first is what makes an uncorrected file's provisional (prep) and final (calibration) names coincide, so calibration plans no needless rename (Section 7.3); the two phases use the identical rule so they never disagree on a name.
- **Merge** instead **appends at `max+1`** (the next index above the highest already in use for that root name), never reusing a freed-up lower number, because the library is append-only and a re-run must reproduce the same name (merge spec `photos-3-merge-workflow.md` Section 7).

Suffix allocation rules are specified per phase where the renames are planned (prep Section 8 / Section 7.3; calibration Section 27; merge spec Section 7).

### 7.3 Provisional (prep) vs. final (calibration) timestamps

Both phases use the same format, but the **value** differs by phase and that difference is intentional:

1. **Prep** derives the timestamp from the *raw, camera-naive* source timestamp, purely for organization and ordering. The resulting by-date name is **provisional** — prep does not correct, timezone-resolve, or UTC-convert it.
2. **Calibration** recomputes the timestamp from *corrected, destination-local civil time* (resolved UTC → destination civil timezone → local naive datetime → this format) and rewrites the name to its **final** value.

Because the shape is identical, a file's name changes between phases only when its timestamp is genuinely corrected; an uncorrected file's provisional and final names coincide, so calibration plans no needless rename for it.

### 7.4 Both phases use the same format; non-conforming names are dumps

Both prep and calibration read the same `filename_timestamp_format` and emit the same name shape, so a file's provisional (prep) and final (calibration) names differ only when the timestamp is actually corrected (Section 7.3). There is no format divergence to reconcile.

A file already in the workspace whose name does **not** match the convention is not specially migrated or pattern-matched — it is simply treated as an ordinary dump: re-ingested and named by the pipeline like any other incoming file. The pipeline never tries to parse meaning out of a non-conforming existing filename; the timestamp comes from metadata, not from the name.

---

## 8. GPX root

GPX track files are consumed only by calibration (`photos-2-time-gps-workflow.md` Section 15), for time-anchor proposals and for GPS interpolation/extrapolation. Prep never parses, fingerprints, or organizes them. The shared rule that makes this safe is **where the GPX files live**.

### 8.1 Location

The GPX folder is configured by `gpx_root` in the shared configuration (Section 4). The contract is only that `gpx_root` resolves to a path **outside the managed media tree** — that is, not under any of the numbered folders `0-sources` … `6-photos-by-dest`. Its specific location is a deployment choice, not part of this contract: it may be an absolute path anywhere on disk, or a subdirectory of the prep control directory (e.g. `.photos-ingest/gpx/`, which is already outside the managed tree since prep treats `.photos-ingest/` as control, not media). Keeping GPX outside `0`–`6` means prep's normal scan never encounters GPX files, so they can never be misclassified as `other`-class media or swept into `0-sources` and organized.

### 8.2 Prep's only obligation

Prep stays GPX-unaware: it does not read, parse, fingerprint, or move GPX files. Its sole obligation is defensive — **if `gpx_root` resolves to a location inside the managed media tree** (a misconfiguration), prep must skip that subtree during scanning exactly as it skips `.photos-ingest-quarantine` and registered control files, so GPX files are never organized even under a bad configuration. Prep does not otherwise act on GPX.

### 8.3 Calibration's use and fingerprinting

Calibration owns all GPX behaviour: scanning `gpx_root`, parsing tracks, computing the GPX fingerprint, and using it as evidence. The GPX fingerprint participates in calibration's dependency cascade (Section 9): it becomes an upstream dependency of `photos-21-time-decisions.json` when GPX is used for time anchors, and of `photos-22-gps-decisions.json` / `photos-23-executable-plan.json` when GPX is used for GPS placement. The `gpx_root` value and GPX matching thresholds live in the shared config (Section 4); their detailed semantics are in `photos-2-time-gps-workflow.md` Sections 15 and 19.

---

## 9. Dependency-fingerprint/hash cascade

Both phases enforce the same anti-stale rule, stated in full in each phase spec (prep Section 5; calibration Sections 3–6):

```text
validate upstream -> create artifact -> record dependencies in it -> reject downstream use if dependencies changed
```

The shared facts that feed these fingerprints — config (Section 4), control directory (Section 5), camera-group key version (Section 6), filename format (Section 7), GPX root/fingerprint (Section 8), and the snapshot mechanism (Section 3) — are defined here so that a single change has one authoritative source and a predictable staleness footprint in both phases. This staleness mechanism is the **dependency-fingerprint/hash cascade** (the name carries the `/hash` because it tracks both kinds of identity below); where context is clear it is shortened to "the dependency cascade."

### 9.1 "Fingerprint" and "hash" are deliberately different words for two different jobs

These specs draw an intentional, load-bearing distinction between the two terms — they name a value by the role it plays, not by the algorithm underneath:

- a **fingerprint** is the **decoded-content identity of a media file** — a photo's pixels via ImageMagick `identify`, a video's streams via the `ffmpeg` stream MD5 (prep `photos-1-prep-workflow.md` Section 9). It is chosen precisely so it stays the **same** when the pipeline rewrites a photo's EXIF/GPS or renames a file: a media file's identity must survive those mutations, which is what makes it the identity spine the transformation log and de-duplication rely on (Section 13.3).
- a **hash** is a **byte-level SHA-256 over an artifact's exact bytes** — the numbered JSON artifacts and the config. It is chosen precisely so it **changes** on any byte change: detecting change is its whole purpose, which is what makes it the right dependency check for artifacts (Section 4.1, Section 5.2). The **prep handoff** is the one deliberate refinement: its whole-file SHA-256 is kept as an **integrity/archival** hash, but its **staleness** key is a content-scoped fingerprint (`content_fingerprint`), because the handoff also carries per-run audit that would otherwise restale downstream on a no-op re-prep (prep `photos-1-prep-workflow.md` Section 16.2; calibration `photos-2-time-gps-workflow.md` Section 4). This keeps the handoff's staleness surgical (Section 4.2) without weakening byte-integrity.

So the two values do **opposite** jobs — one must be invariant under mutation, the other must be sensitive to it — and they keep different names even though a content fingerprint is itself computed with a hash function internally (`identify`'s value is a SHA-256 of the normalized pixel stream; the video one is an MD5). The cascade above consumes both: media identity as **content fingerprints**, artifacts as **byte hashes**, plus the field-scoped **config fingerprints** (Section 4.2) that keep staleness surgical. "Fingerprint" unqualified means the media content fingerprint; "hash" unqualified means an artifact byte hash.

---

## 10. Canonical cross-phase operator loop

This section is the authoritative end-to-end view of how an operator drives all three phases. Each phase spec describes only its own loop; this is the sequence that spans them.

```text
0. (first run)     INIT — drop the initial dump into the (empty) folder; prep moves it
   uninitialized   into 0-sources (structure preserved, no flatten), creates the 0-6
                   structure + control dir, organizes it, and writes the root sentinel
                   LAST. After this the base holds only folders. [prep 3.1, 7.1]

1. PREP            plan -> dry-run -> execute (dumps go in 0-sources)
                   photos organized into 5-photos-by-date, videos into
                   4-videos-by-date, untimestamped media into 2-missing-metadata,
                   non-media moved to 1-strays/<plan-id>/ (inert). 0-sources LEFT EMPTY.

2. SORT (user)     move PHOTOS ONLY from 5-photos-by-date into 6-photos-by-dest.
                   by-dest stays photo-only: no non-media, no videos (videos
                   remain in 4-videos-by-date). [cal 7.2, 7.3]

3. RE-PREP         MANDATORY after the latest move. Prep recognizes the moves
   (mandatory)     (stat-only, no re-fingerprint/re-read), carries cache identity
                   forward, refreshes handoff + cache. [prep 10.1, 10.2]

4. CALIBRATE       convergent rerun loop (cal 2.1):
   (loop)          run -> inspect blockers -> edit human-decision fields in the
                   photos-2X JSON -> rerun -> ... until photos-23-executable-plan.json is ready.

5. EXECUTE         apply planned time/GPS metadata + renames; write
                   photos-24-execution-summary.json.

6. (optional)      add more media later: drop a new dump into 0-sources, then
   ADD MORE        re-run the loop from PREP (step 1) — prep organizes the new
                   media, you SORT the new photos into by-dest, RE-PREP recognizes
                   the move, then RE-CALIBRATE/EXECUTE (steps 1-5). Allowed even
                   after a prior successful calibration.

7. FINALIZE        explicit command, once "this dump is done" (Section 13.1):
                   assemble the archival package and generate the full
                   transformation log photos-25-complete-log.json.
                   Required before merge; kept separate from merge because
                   calibration is freely re-run and re-finalizing each pass
                   would be wasteful.

8. MERGE           explicit command (photos-3-merge): requires a finalized
                   workspace. MOVES the finalized photos from 6-photos-by-dest
                   into the permanent library (removing merged sources; by-dest
                   keeps only un-merged leftovers). Incoming files may be
                   RENAMED to avoid clobbering the library; library files are
                   NEVER renamed, overwritten, or deleted. Records where each
                   file landed (photos-31-merge-summary.json), writes its own
                   log photos-35-merge-log.json (copied forward from photos-25,
                   never editing it), captures the end-of-merge DB snapshot, and
                   RE-SEALS the archival package automatically (Section 13.6). On
                   success the workspace is SEALED (terminal): no further
                   dumps/prep/calibration in it (Section 13.7).
                   [merge spec photos-3-merge-workflow.md]

   NEW MEDIA       to process more photos after a merge, start a FRESH workspace
   (after merge)   (new control dir + new SQLite DB) and run from step 0. The
                   permanent library is shared across workspaces; the workspace
                   is single-use through to merge. A SEALED workspace is done:
                   ALL scripts (prep, calibration, merge) HARD-STOP on it and
                   touch nothing. If a dump was dropped into a sealed workspace
                   (files at the root or in 0-sources), the scripts additionally
                   warn that a likely new dump was detected and leave it exactly
                   where it is — move it by hand into a fresh workspace
                   (Section 13.7). There is no recovery utility.

9. DEVELOPMENT     the jpg/tif breakout. A later processing phase, applied in
   (later phase)   the library after merge. Starting it inside the workspace
                   before calibration is settled is a hard-stop. [cal 7.1]
```

### 10.1 Calibration is freely re-runnable, not one-shot

Calibration is not a terminal, run-once phase. It may be re-run any number of times — including after a prior successful execution — to absorb media added later, **up until the workspace is merged**. Merge seals the workspace (Section 13.7), and a sealed workspace accepts no further prep or calibration; the freedom to re-calibrate exists across the prep→calibrate cycles of a single workspace's life, and ends when that workspace's batch is merged into the library. (More media after a merge means a fresh workspace, Section 13.7 / 10.4.) The re-runnability before sealing is safe because:

1. human decisions (timezones, accepted anchors, manual offsets, manual GPS) live in the `photos-2X` calibration JSON and are preserved across regeneration where their logical target is unchanged (cal Section 9);
2. GPS that calibration applied is recognizable on rerun (e.g. via the `GPSProcessingMethod` marker), so already-placed files are no-ops, not re-writes;
3. renames are computed from destination-local civil time, so an already-finalized file recomputes to the same name and is a no-op (cal Section 27).

What bounds the freedom is a small, fixed set of gating preconditions, not a "has calibration run before?" flag. Calibration may proceed whenever, and only when:

```text
a. 5-photos-by-date contains no photo files;          [cal 7]
b. 6-photos-by-dest is photo-only — no non-media
   files and no videos (videos stay in
   4-videos-by-date);                                   [cal 7.2, 7.3]
c. no jpg/tif development subfolder exists under
   6-photos-by-dest (development not started);          [cal 7.1]
d. by-dest is prep-consistent — the handoff recognizes
   all by-dest photos (i.e. prep was re-run after the
   latest by-date -> by-dest move).                      [cal 13.1]
```

Condition (d) is why the re-prep of step 3 is mandatory every time new photos enter by-dest, even post-calibration: calibration depends on the prep handoff as a hashed artifact (cal Section 4), and files prep has not yet recognized are not in it. New photos never reach calibration "behind prep's back."

### 10.2 A rerun may legitimately require new decisions

"Freely re-runnable" does not mean "always a no-op." A rerun is triggered whenever an upstream input changes — and any such change may pull artifacts back into the convergent decision loop (`requires_user_input`) for the parts it affects, while leaving unaffected stored decisions and already-applied operations untouched. Newly added media is only one example: it can introduce a new camera group needing classification, or land in a destination whose timezone was never settled. But the same is true of any invalidating upstream change — an edited config value, a changed GPX set, a withdrawn or altered manual decision, a refreshed handoff — each restales exactly the dependent artifacts (Section 9) and may surface new decisions for the affected items. A rerun is therefore safe but not guaranteed frictionless: it does exactly as much work as the changed inputs require, and no more.

### 10.3 Interleaving

The operator may run several prep → sort cycles before ever calibrating (import a batch, sort it, import more, sort more). Calibration cares only that the *current* state satisfies the gating preconditions above; it does not require that prep and sort happened exactly once. The loop is a steady state to return to, not a one-way pipeline.

The entire loop runs under the single workspace lock (Section 2): only one pipeline process — prep or calibration — touches the workspace at a time.

### 10.4 Merge is the terminal step for a workspace

Merge (`photos-3-merge`, Section 13.5; spec `photos-3-merge-workflow.md`) runs **after** finalize, when the operator has decided a workspace's `6-photos-by-dest` is complete and correct. It is the bridge from the transient workspace to the permanent library, and the **terminal** action for that workspace:

1. **Position.** Prep → sort → re-prep → calibrate → execute → finalize → **merge → sealed**. Merge consumes a calibrated, finalized by-dest and **moves** it into the library (removing merged sources from by-dest); it is the last pipeline action against a given dump's workspace, after which the workspace is sealed (Section 13.7).
2. **Preconditions.** Merge requires that calibration ended successfully and the workspace was finalized (the archival package and `photos-25-complete-log.json` exist), so what merge moves into the library is the corrected, named, fully-recorded set — never a half-calibrated one. Because finalize is a point in time and by-dest can change after it, merge does not merely trust that finalize was last: it re-validates that the finalized plan is **current** with the present by-dest (recomputing `photos-11-handoff.json`'s content fingerprint against the value `photos-23-executable-plan.json` recorded — so a real by-dest change is caught while a run-only re-prep is not), and hard-stops directing the operator to re-calibrate and re-finalize if a by-dest photo postdates finalize — so "never a half-calibrated one" is mechanically enforced, not assumed. The detailed preconditions are in the merge spec (merge spec Section 3, precondition 1a).
3. **Re-seals the archive automatically.** Unlike calibration's finalize (a deliberate separate step, kept manual because calibration is freely re-run), merge re-seals the archival package automatically on success — it has added to the durable record (its own `photos-35-merge-log.json` copied forward from `photos-25` and extended, the end-of-merge DB snapshot, the merge summary), so it bundles the now-current archive without a manual re-finalize (Section 13.6).
4. **Terminal: the workspace is sealed, not recycled.** A successfully merged workspace is marked terminal and **every media-mutating script refuses to run on it** (Section 13.7) — even if by-dest looks empty, the workspace is not a clean slate (its DB, ledgers, caches, snapshots, and sealed archive persist). To add more media, the operator starts a **fresh workspace** and runs from the start; the shared permanent library accepts merges from many workspaces (the library-side lock, Section 15.2). Sealed means sealed: prep, calibration, **and merge** all hard-stop and touch nothing — there is no confirming re-merge and no recovery utility (Section 13.7). The sole exception is prep's `prune-quarantine`, which is still allowed because it only reclaims recoverable quarantine copies and touches no controlled content (Section 13.7 item 2).
5. **Development is downstream of merge.** The jpg/tif development breakout (cal Section 7.1) is a library-side processing phase that runs *after* a batch is merged, never inside the workspace before calibration settles.

---

## 11. Idempotency: change only what needs changing

All three phases are idempotent in the same sense, and to the greatest extent the work allows: **a run changes only what actually needs changing, and a run over unchanged inputs is a no-op.** No phase redoes settled work to "be safe," and none leaves a file in a different state than its inputs require.

The shared principle has four parts:

1. **Reuse, don't recompute.** Work already done and still valid is reused, not repeated — prep reuses cached fingerprints and metadata for files whose size/mtime (and move-aware identity) are unchanged; calibration reuses resolved UTC and preserves human decisions whose logical target is unchanged. Expensive operations (fingerprinting, metadata extraction, GPX parsing) run only for genuinely new or changed inputs.
2. **Recompute only what staleness forces.** When an upstream input changes, only the artifacts whose dependency fingerprints actually depend on it become stale and are regenerated; unaffected artifacts are left as-is. This is the dependency cascade of Section 9, run minimally.
3. **Mutate only on a real difference.** A file is moved, renamed, or metadata-written only when its current state differs from the planned target. A file already in its correct location with its correct name and metadata produces no operation — it is reported as a no-op, not re-applied. Calibration's renames recompute to the same name for an already-finalized file; prep does not re-move or re-normalize files already in place.
4. **A no-op run is a no-op.** Re-running any phase on a workspace whose relevant state has not changed produces zero mutations and a stable, equal result (same plan, same fingerprints, same names), reporting cache hits and already-correct files rather than treating prior work as error.

Each phase states the concrete consequences of this principle in its own terms — prep in `photos-1-prep-workflow.md` Sections 13 and 21 (idempotency, incremental operation, staleness examples), calibration in `photos-2-time-gps-workflow.md` Sections 29.1 and 30 (execution idempotency/resume, recalculation), and merge in `photos-3-merge-workflow.md` Section 8 (idempotency, resume, non-destructiveness). This section is the single statement of the principle they share.

---

## 12. Authored decisions: nothing changes that the user did not write down

Every mutation any phase performs traces back to an explicit, recorded human decision or to a deterministic rule applied to recorded inputs — never to an autonomous, unexplained choice by the tool. This is a deliberate trust stance for irreplaceable data: the pipeline is built so that a user who distrusts opaque automatic mutation can always answer *why did this change happen?* and can revise the answer.

The principle has three parts, and the existing machinery already implements all three:

1. **No autonomous mutation.** The machine *proposes* (time-anchor offsets, GPS placements, timezone candidates); the user *disposes* by filling decision fields in the numbered JSON artifacts; the executor acts only on the disposed plan. Human-decision fields are authored by the user and never silently overwritten (calibration Section 9). Required fields are pre-created so the user fills values, not structure (calibration Section 20). Prep embeds no human decisions and instead derives organization deterministically from filesystem state — also a recorded, inspectable input, not an opaque choice.

2. **Locatable cause.** Because decisions live in durable artifacts, every executed operation can be traced to the recorded decision and the fingerprinted inputs that produced it: decision artifact → dependency fingerprints (Section 9) → executable plan → journal of what executed (prep Section 14.3; calibration Section 29). When an output is wrong, there is a specific recorded decision to point at, so the cause is attributable to an authored choice rather than to tool behaviour.

3. **Re-derivable, never a one-way door.** Decisions are data and the pipeline is idempotent (Section 11) and non-destructive (no-clobber on content; recoverable quarantine; read-only destinations). The user changes a decision in the artifact, re-runs, and the dependency cascade re-derives everything downstream that the change affects. No mutation the tool makes is irreversible at the decision level — a wrong choice is fixed by editing the record and re-running, not by manual repair of mutated files. Withdrawing a decision *undoes* its effect, not merely stops re-asserting it: for **manual GPS overrides** this is guaranteed by a pinned pre-state ledger that restores the original GPS (or clears it, if there was none) when the override is removed (calibration Section 24.1); automated GPS is recomputed rather than rolled back; time and filename are recomputed in place within the file's destination under `6-photos-by-dest` (the rename and timestamp rewrite never relocate the file to another destination or elsewhere in the tree), since reverting them would un-position an organized file.

Together with the safety model (validated plans, no-clobber, recoverability) and idempotency (Section 11), this means the user retains authorship: nothing changes that they did not write down, every change is explainable from the record, and any change can be revised and re-derived. The retention half of this — keeping that record in one durable place that outlives the transient workspace — is defined in Section 13 (the archival package).

The phase specs implement this via calibration Sections 9 and 20 (authored, preserved decision fields) and the journal/fingerprint discipline of prep Section 14.3 and calibration Sections 4–6 and 29; merge adds no human-decision fields but its placement is the same deterministic-rule-on-recorded-inputs kind, recorded the same way (`photos-3-merge-workflow.md` Sections 8–9). This section is the single statement of the principle they share.

---

## 13. Archival package: the permanent record that outlives the workspace

The decision artifacts drive a run, but their value is also long-term: they are the record of *what was done to this archive and why*. The workspace, however, is transient (Section 10) — it may be merged into the permanent library and then torn down or reused, or it may simply be set aside at any phase boundary without ever advancing. So authored decisions (Section 12) are only truly "saved for the future" if they are **preserved beyond the workspace**, consolidated in one known place rather than scattered across per-file sidecars or — as with tools that mutate and forget — left unrecorded.

This section defines the **archival package**: a single, portable bundle that is the complete, durable record of a dump's journey through the pipeline. It is what the user keeps when the workspace goes away.

### 13.0 A complete audit record at the end of every phase

The pipeline's recording guarantee is **recurring, not terminal**: at the end of *each* phase the workspace holds a complete, self-sufficient, human-readable audit record of everything done to the files **so far**, and that record stands on its own whether or not any later phase ever runs.

```text
end of PREP       -> complete audit record of all prep transformations
                     (as if calibration and merge did not exist)
end of CALIBRATE  -> that record, extended through calibration
   (+ finalize)     (as if merge did not exist)
end of MERGE      -> that record, extended through merge
                     (the full journey into the library)
```

Concretely:

1. **Each phase brings the record up to date through its own work.** The per-photo **transformation log** is the human-readable spine, realized as one file per phase in the artifact-numbering scheme (Section 5): prep writes `photos-15-prep-log.json` (prep `photos-1-prep-workflow.md` Section 16.1); calibration's finalize produces `photos-25-complete-log.json` by **copying the prep log forward under its own phase name and extending the copy** (Section 13.3); merge produces `photos-35-merge-log.json` by copying the calibration log forward and extending it (Section 13.5). Each step is **additive and owned**: a phase writes only its own phase-named log and never rewrites or invalidates an earlier phase's file (Section 13.0a) — it copies the predecessor forward and appends. (Calibration does not re-derive prep's history; it consumes `photos-15-prep-log.json` and the prep journals as the prep portion of each journey.)
2. **The SQLite database** (Section 13.4) is a live durable record updated by each phase, complete-as-of-now at every phase boundary; and at the end of each phase a **point-in-time backup snapshot** of it is captured and retained (`photos-15-prep-ingest.db`, `photos-25-calibrate-ingest.db`, `photos-35-merge-ingest.db`, Section 13.4a), so a full DB image is preserved as of each phase, not just the last.
3. **The per-phase job artifacts** — prep's handoff/summary, calibration's decision/plan/execution-summary artifacts, merge's summary — each describe what their phase did and remain on disk.
4. **No later phase is a prerequisite for an earlier phase's record being whole.** A workspace prepped but never calibrated has a complete prep audit record; one calibrated and finalized but never merged has a complete prep+calibration record; merge only *adds* the library destination. An absent later phase reads as "not advanced past phase N," never as "incomplete record."

The **archival package** (Sections 13.1–13.2) is the bundling of this record for retention. It is conventionally assembled at the finalize step (after calibration), because that is when a dump is usually "done"; but the *guarantee* that a complete audit record exists is not tied to finalize — it holds at every phase boundary. The subsections below specify the package and the cumulative log; Section 13.5 specifies merge's additive extension.

### 13.0a Phase artifact ownership: no phase clobbers another phase's artifacts

Each numbered artifact is **owned by the single phase whose number it carries** (Section 5), and only that phase ever writes it. A phase may freely create, overwrite, or (for its own audit log) extend its **own** phase-named artifacts across its runs; it must **never** overwrite, truncate, mutate, or extend an artifact belonging to a different phase. The rule, stated once:

```text
A phase writes only artifacts in its own number band (prep 1X, calibration 2X, merge 3X).
It reads earlier phases' artifacts read-only.
To carry an earlier phase's record forward, it COPIES that artifact to its own
phase-named file and extends the copy — the earlier file is left untouched.
```

This is why the transformation log is three separate files rather than one mutated in place (Section 13.3): calibration does not edit prep's `photos-15-prep-log.json` — it copies it to `photos-25-complete-log.json` and extends that; merge does not edit `photos-25-complete-log.json` — it copies it to `photos-35-merge-log.json` and extends that. The same ownership holds for every artifact:

1. **Prep (1X)** owns and writes `photos-11-handoff.json`, `photos-15-prep-log.json`, `photos-15-prep-ingest.db`. It is also the sole writer of the *live* SQLite cache/identity rows (Section 13.4) and the seeded `photos-00-config.json` (Section 4) — but those are phase-neutral 0X infrastructure with their own single-writer rules, not another phase's numbered artifact.
2. **Calibration (2X)** owns and writes `photos-21`–`photos-25` (including `photos-25-complete-log.json` and `photos-25-calibrate-ingest.db`). It reads prep's 1X artifacts read-only and never modifies them. (It writes only its own disjoint live-DB regions, Section 13.4.)
3. **Merge (3X)** owns and writes `photos-31-merge-summary.json`, `photos-35-merge-log.json`, `photos-35-merge-ingest.db`. It reads calibration's and prep's artifacts read-only and never modifies them. (It writes only its own disjoint live-DB regions, Section 13.4.)

Re-running a phase may legitimately refresh **its own** artifacts (a re-prep updates `photos-15-*`; calibration reruns update `photos-2X-*`); it still never touches another phase's. The benefit is that each phase's outputs are a stable, attributable record that a later phase cannot silently alter — combined with the per-phase completeness guarantee above, every phase's artifacts are both complete and tamper-evident with respect to later phases. (The archival package bundles copies of all phases' artifacts, Section 13.2; bundling is a read, not a write, so it does not violate ownership.)

### 13.1 When the archival package is produced

The package is produced by an **explicit finalize/archive command**, not automatically at the end of each calibrate. Because calibration is freely re-runnable (Section 10.1) — the user may calibrate, add a dump, and calibrate again — "this dump is done" is a human judgement, so package assembly is a deliberate, separate step the user invokes when finished with a workspace. The command runs under the same workspace lock as every other operation (Section 2) and is non-destructive: it reads and bundles, it does not mutate the workspace or the library. (Finalize bundles a record that already exists at the calibration phase boundary, Section 13.0; it consolidates and seals it, it does not create the audit record from nothing.)

### 13.2 Contents

The archival package contains:

1. **The workspace configuration** — `photos-00-config.json`, the pinned config that governed all processing in this workspace (Section 4).
2. **All current decision/plan JSON artifacts** — the prep handoff (`photos-11-handoff.json`); the numbered calibration artifacts `photos-21-time-decisions.json`, `photos-21a-gps-drift-validation.json`, `photos-22-gps-decisions.json`, `photos-23-executable-plan.json`, `photos-24-execution-summary.json`; and, if merge has run, the merge summary (`photos-31-merge-summary.json`) — exactly as written (same bytes the pipeline validated against, Section 12 part 2).
3. **The SQLite database and its per-phase backup snapshots** — the live `photos-00-ingest.db` (Section 13.4) plus every per-phase backup snapshot present (`photos-15-prep-ingest.db`, `photos-25-calibrate-ingest.db`, and, if merge has run, `photos-35-merge-ingest.db`, Section 13.4a): the DB is part of the durable record, not throwaway scratch, and is archived with the artifacts, together with a full point-in-time image as of each phase boundary.
4. **The per-phase transformation logs** — every phase log present (`photos-15-prep-log.json`, `photos-25-complete-log.json`, and, if merge has run, `photos-35-merge-log.json`, Section 13.3), each a complete record through its phase and each a superset of the one before. The latest-phase log is the authoritative full record; the earlier ones are each phase's own standalone record (Section 13.0a). All present are bundled.

The package is self-describing: it should record the workspace identity, the plan/execution ids it corresponds to, and a manifest of its own contents with their SHA-256s, so its integrity is verifiable later. (When merge re-seals the package, Section 13.6, it re-bundles to include the merge artifacts — `photos-31-merge-summary.json`, `photos-35-merge-log.json`, `photos-35-merge-ingest.db` — and refreshes the manifest.)

### 13.3 The transformation log (`photos-25-complete-log.json`)

The transformation log answers, for any photo, "what happened to this file and why?" — in one place. It is a **derived, consolidated view** stitched from records that already exist: prep's execution journal and handoff, calibration's decision artifacts and execution journal, and merge's summary. It does not introduce new authority; it fuses the phases' existing records into a per-photo story, and it is **maintained cumulatively** — each phase brings it up to date through its own work (Section 13.0), so at every phase boundary there is a complete human-readable log of everything done so far.

It is realized as **one log file per phase**, each owned and written only by its producing phase, so the numbering scheme (Section 5) stays phase-aligned and **no phase ever clobbers another phase's artifact** (the general rule, Section 13.0a):

```text
photos-15-prep-log.json        prep's end-of-prep audit log        (written/extended only by prep)
photos-25-complete-log.json    prep+calibration log                (written/extended only by calibration)
photos-35-merge-log.json       prep+calibration+merge log          (written/extended only by merge)
```

Each later phase **copies its predecessor's log forward under its own phase name and extends the copy**, leaving the predecessor's file untouched: calibration's finalize copies `photos-15-prep-log.json` to `photos-25-complete-log.json` and appends the calibration steps; merge copies `photos-25-complete-log.json` to `photos-35-merge-log.json` and appends the merge steps. Each file is a strict superset of the one before, and each remains its phase's standalone, self-sufficient record. The latest-phase file is the authoritative full record (`photos-35` if merged, else `photos-25` if calibrated, else `photos-15`); the earlier files are kept as each phase's own snapshot of the journey through that phase.

Requirements:

1. **Each entry covers the journey so far, growing one phase at a time.** A photo's entry accumulates steps as it advances: prep actions (extension normalization, move into by-date, content de-duplication / quarantine, provisional rename), then — if the file is calibrated — calibration actions (camera-group clock offset applied, resolved UTC, destination timezone decision, GPS placement and method, final destination-local rename), then — if the workspace is merged — the merge action (final library path and whether it was renamed to avoid a library collision; Section 13.5). Whatever phases have run, the entry is **complete and self-sufficient through the latest phase that touched the file**: a prep-only entry is a whole record of prep, a calibrated entry a whole record through calibration, a merged entry the full journey. An absent later-phase step means "not advanced past that phase," never "incomplete." Each phase **only appends** its own steps and never rewrites earlier ones.
2. **Keyed by content fingerprint.** The content fingerprint is the identity spine: it is computed over the file's **decoded content** — photos with ImageMagick `identify`, videos with the `ffmpeg` stream MD5 — not its file bytes (prep `photos-1-prep-workflow.md` Section 9), so it survives every rename, move, **and (for photos) in-place EXIF/metadata write** the pipeline performs — calibration rewriting a photo's time/GPS does not change its identity. Each media entry is keyed by its fingerprint and carries the ordered chain of names/locations it passed through. Names alone cannot key the log because a file is renamed up to twice (provisional, then final) and may be renamed again on the way into the library. (`other`-class files are not fingerprinted and not logged as journeys — they are moved to `1-strays/` and ignored, prep Sections 3.2, 9.)
3. **Decision provenance per change.** Where a transformation followed from an authored decision (a timezone choice, an accepted clock offset, a manual GPS entry), the entry references that decision so the *why* is attached to the *what* (Section 12 part 2).
4. **Records GPS reverts and pre-state.** Where a manual GPS override was applied, changed, or **withdrawn**, the entry records the action and — for an applied or reverted override — the pinned pre-state it captured or restored (previous coordinates, or "absent"), per calibration Section 24.1, so the reversal is as traceable as the application.
5. **Human-readable JSON.** The log is JSON — pretty-printed, stably ordered, and keyed/labelled so a human can open it and read each photo's history directly. It is not a separate rendered report; the JSON itself is the readable artifact. Field names are descriptive, values are human-legible (ISO timestamps, IANA timezones, human-facing offset descriptions), and entries are ordered deterministically.
6. **Maintained per phase by copy-forward-and-extend; complete at each phase boundary.** Prep writes `photos-15-prep-log.json` at the end of every prep run — a complete record of prep that stands on its own if calibration never runs (prep Section 16.1). Calibration's finalize produces `photos-25-complete-log.json` by **copying `photos-15-prep-log.json` forward** (it does not edit the prep file) and appending the calibration steps; merge produces `photos-35-merge-log.json` by **copying `photos-25-complete-log.json` forward** and appending the merge steps (Section 13.5). A phase only ever writes its own phase-named log; it reads its predecessor's read-only. So there is a whole human-readable log at the end of prep (`photos-15`), a whole superset at the end of calibration (`photos-25`), and a whole superset again at the end of merge (`photos-35`) — each its phase's standalone record, none clobbering another (Section 13.0a). (If the archival package was already copied to permanent storage before a later phase ran, that phase's new log and artifacts are added to the stored record so it stays current — Section 13.5 for merge.)

### 13.3a History retention (what must survive across runs)

The transformation log must cover the whole journey a file has taken so far — but that journey usually spans **many runs** across phases (prep, re-prep after moves, repeated calibration passes, then merge). So the records the log is built from must be **retained across runs in enough detail to reconstruct each photo's per-file history**; they must not be overwritten such that only the last run's actions survive.

This is a retention requirement, not a prescription of format. Concretely:

1. Per-run journals are not discarded or truncated to a single run: either journals accumulate (e.g. one `journal-<run>.json` per run, all retained) or an equivalent durable per-file history is maintained in `photos-00-ingest.db`. The choice is an implementation detail; what is required is that each phase can recover, for every file it is responsible for, the ordered set of transformations it underwent and the decisions/inputs behind them.
2. The minimum that must be recoverable per file: the prep actions (normalization, organization, dedup/quarantine, provisional naming); for calibrated files the move into by-dest and the calibration actions (clock offset, resolved UTC, timezone, GPS placement and method, any manual-GPS apply/change/revert with pre-state, final naming); for merged files the library destination and any anti-collision rename — each attributable to the run and decision that caused it.
3. Anything beyond that minimum may be pruned. Retention exists to serve the log (and resume/auditing); it is not an open-ended event store.

Each phase fails (or warns and produces a clearly-partial record) if the retained history is insufficient to reconstruct the journey through its phase — it must not silently emit a log that looks complete but only reflects the last run. (Prep applies this to its own end-of-phase log, Section 16.1; finalize applies it through calibration; merge through merge.)

Illustrative per-photo shape (not normative):

```json
{
  "content_sha256": "…",
  "final_path": "6-photos-by-dest/Belgium/Brussels/2024-07-03--14-12-21.arw",
  "camera_group": "sony_a6400_serial_123456",
  "journey": [
    { "phase": "prep", "action": "extension_normalized", "from": "DSC01234.ARW", "to": "dsc01234.arw" },
    { "phase": "prep", "action": "moved_to_by_date", "to": "5-photos-by-date/2024-07-03/…" },
    { "phase": "prep", "action": "provisional_rename", "to": "2024-07-03--14-12-08.arw" },
    { "phase": "user", "action": "moved_to_by_dest", "to": "6-photos-by-dest/Belgium/Brussels/…" },
    { "phase": "calibrate", "action": "clock_offset_applied",
      "offset_seconds": -7187, "because": "destinations.'Belgium/Brussels'.camera_group_time_decisions.sony_a6400_serial_123456 (accepted anchor anchor-001)" },
    { "phase": "calibrate", "action": "resolved_utc", "value": "2024-07-03T12:12:21Z" },
    { "phase": "calibrate", "action": "timezone_resolved",
      "value": "Europe/Brussels", "because": "destinations.Belgium/Brussels.user_decision" },
    { "phase": "calibrate", "action": "gps_written",
      "lat": 50.8467, "lon": 4.3525, "method": "gpx_segment_interpolation", "gps_processing_method": "…" },
    { "phase": "calibrate", "action": "final_rename", "to": "2024-07-03--14-12-21.arw" },
    { "phase": "merge", "action": "merged_to_library",
      "to": "/library/Belgium/Brussels/2024-07-03--14-12-21.arw", "renamed_for_library": false }
  ]
}
```

### 13.4 SQLite is a durable artifact, not scratch

The SQLite database holds content-fingerprint and metadata identity, move-aware carry-forward history, the **manual-GPS pre-state ledger** (calibration Section 24.1, the pinned originals that make manual GPS overrides reversible), the **library-file fingerprint cache** (merge Section 13.5: on-the-fly fingerprints of library files computed during collision checks, stored so a given library file is fingerprinted at most once), and the cache that makes idempotency cheap. There is exactly **one** database, the workspace's `photos-00-ingest.db` in `.photos-ingest/`; **the permanent library has no database of its own.** The "library-file fingerprint cache" is named for *what* it holds (fingerprints **of** library files), not *where* it lives — it lives in this workspace DB. Merge never indexes or scans the library (merge `photos-3-merge-workflow.md` Section 2.3); it computes a library file's fingerprint only when an incoming file collides with it, and caches that result here so the same library file is not re-read within or across runs. The only library-side construct is the **lock** keyed to `library_root` (Section 15.2), which is a mutual-exclusion guard, not a store. It is part of the durable record of what the pipeline knows about the archive, so:

1. it is archived as part of the package (Section 13.2 item 3), alongside the JSON artifacts, not discarded with the transient workspace;
2. conceptually it belongs with the artifacts in the control directory `.photos-ingest/` rather than being treated as throwaway scratch elsewhere;
3. prep is the sole writer of the cache/identity content through its controlled single-writer path (prep Section 14.3); calibration is the writer of the GPS pre-state ledger (it captures pre-state when it applies a manual GPS override, per calibration Section 24.1); merge is the writer of the library-file fingerprint cache (Section 13.5) — populated during planning; merge records each file's library destination in its JSON artifacts (`photos-31-merge-summary.json`, `photos-35-merge-log.json`), not in a SQLite table, since a write-only destination table would have no reader (merge is terminal and resumes from the filesystem + journal); finalize only reads and bundles the database. The three writers' regions are disjoint (Section 5 / prep Section 3), so no two phases ever write the same rows.

This reframes the DB from "cache that happens to persist" to "an archived artifact that also serves as cache." Prep `photos-1-prep-workflow.md` (which owns the cache/identity content) and the control directory (Section 5) treat it accordingly.

#### 13.4a Per-phase database backup snapshots

The live `photos-00-ingest.db` is a single mutating file — at any instant it shows only the *current* state, and a later phase's writes overwrite the picture an earlier phase left. To uphold the recurring guarantee that each phase leaves a complete image of what happened (Section 13.0), each phase additionally captures a **point-in-time backup snapshot of the database** at its successful end and **retains it** as a distinct artifact, so the user keeps a full DB image as of every phase boundary, not just the last.

1. **One snapshot per phase, retained, never overwritten.** On a successful run, each phase writes a consistent copy of `photos-00-ingest.db` to a phase-named file in `.photos-ingest/`, aligned with the artifact-numbering scheme (Section 5):

```text
photos-15-prep-ingest.db        DB image as of the end of prep        (prep)
photos-25-calibrate-ingest.db   DB image as of the end of calibration (calibration finalize)
photos-35-merge-ingest.db       DB image as of the end of merge        (merge)
```

   These are **backups, not the working database**: the pipeline always reads and writes the live `photos-00-ingest.db`; the `*-ingest.db` snapshots are write-once-per-phase images that are never read back as cache and never mutated after capture. Re-running a phase refreshes that phase's snapshot to reflect the latest successful run of that phase (it is the "end of phase N" image, kept current for phase N), while the other phases' snapshots are left untouched — so a re-prep updates `photos-15-prep-ingest.db` but not `photos-25-*`/`photos-35-*`.

2. **Consistent and atomic capture (atomic replace, not no-clobber).** A snapshot must be a **transactionally consistent** image of the database (e.g. via SQLite's online-backup API or `VACUUM INTO`), not a raw byte-copy of a possibly-open file, so it is never torn or mid-transaction. It is written under the workspace lock (Section 2) at the end of the phase by writing to a temporary name, then **atomically replacing** the phase's snapshot file with it (a single atomic rename that overwrites any prior snapshot of the same phase). Atomicity guarantees an interrupted capture leaves either the prior snapshot or the complete new one, never a corrupt file. This is deliberately **clobber-on-refresh, not no-clobber**: re-running a phase must *refresh* that phase's snapshot to reflect its latest successful run (item 1), which means overwriting the previous same-phase snapshot — the opposite of the no-clobber rule that governs *content-bearing* media operations (Section 15). (No-clobber protects irreplaceable photographic content from being overwritten; a phase DB snapshot is a regenerable image of the live DB, and the *current* end-of-phase image is the one to keep, so replacing the prior same-phase image is correct. The temporary-then-atomic-rename technique provides the crash-safety; the rename target is intentionally allowed to pre-exist.)

3. **Captured at the same gate as the phase's other end-of-phase artifacts.** Prep captures `photos-15-prep-ingest.db` when it writes the handoff and prep log (prep Section 14.3 / 16.1); calibration captures `photos-25-calibrate-ingest.db` at finalize alongside `photos-25-complete-log.json` (calibration Section 31); merge captures `photos-35-merge-ingest.db` when it writes the merge summary (merge Section 9 / 10.3). A phase that does not complete successfully writes no new snapshot, leaving the prior one intact.

4. **All snapshots are bundled in the archival package.** The package (Section 13.2) carries the live `photos-00-ingest.db` **and** every phase backup snapshot present, so the retained bundle contains both the final working DB and the per-phase images. Their SHA-256s go in the package manifest like every other bundled item.

The live working DB remains the single source of truth during processing (item 3 of Section 13.4 still governs which phase writes which live rows); the per-phase snapshots are immutable copies taken from it. Together they give a complete, replayable image history: open `photos-15-prep-ingest.db` to see exactly what the DB knew at the end of prep, `photos-25-calibrate-ingest.db` for the end of calibration, and so on.

### 13.5 The library-merge phase and its summary (`photos-31-merge-summary.json`)

Merge (`photos-3-merge`, spec `photos-3-merge-workflow.md`) is the explicit, separately-invoked command that takes a calibrated, finalized `6-photos-by-dest` and merges it into the user's permanent library at `library_root` (Section 4.3). This subsection states only the cross-phase facts; the full workflow lives in the merge spec.

1. **The library is authoritative and protected.** Library files are **never renamed and never overwritten** by merge. When an incoming by-dest file would land on a path already occupied in the library, it is the **incoming (by-dest) file** that is renamed to a safe non-colliding name, never the library file. The library's existing organization and names are treated as ground truth.

2. **No library-wide scan or index.** Merge does **not** build or maintain a full scan of the library, and does not perform library-wide de-duplication. It assumes the library is already well-organized. Merge touches the library only at the specific destination paths its incoming files map to; it inspects an existing library file **only on a path collision**.

3. **Collisions are resolved by content fingerprint, computed on the fly.** When an incoming file's mapped destination path is already occupied, merge compares the two by content fingerprint to decide identity:
   - **Same content** (fingerprints equal) → the file is already in the library; merge writes nothing to the library and renames nothing, but — because the library already holds the content — it **removes the by-dest source** (the workspace keeps no duplicate of a file already in the library), recording the file as `already_present`.
   - **Different content** (fingerprints differ) → a genuine name clash between distinct files; merge gives the **incoming** file a safe differentiating name (the shared suffix convention, Section 7.2) and places it, leaving the library file untouched.
   The library-file fingerprint is **computed on the fly at collision time and stored in the SQLite library-file fingerprint cache** (Section 13.4), keyed so the same library file is never fingerprinted twice across the run or across re-runs while its size/mtime are unchanged. The by-dest-side fingerprint is already known from prep's cache (prep Section 9) and is reused, not recomputed.

4. **Records where every file landed — in its own phase artifacts.** Merge writes `photos-31-merge-summary.json` to `.photos-ingest/` recording, per file and in global total, the final library path each by-dest file was placed at, whether it was renamed to avoid a collision (and from/to names), which files were already-present, which were removed from by-dest, and any blockers. It writes its own transformation log `photos-35-merge-log.json` by **copying calibration's `photos-25-complete-log.json` forward and appending** each file's final library location (Section 13.3 item 6; Section 13.0a — merge never edits the `photos-25` log) and, on success, re-seals the archival package to include these (Section 13.6). All of this is **additive and owned**: the prep and calibration logs, the per-phase DB snapshots, and the calibration job/decision artifacts already exist and are complete before merge runs, and merge does not replace, regenerate, or invalidate any of them — it writes its own 3X artifacts. A workspace that is never merged retains all of those earlier records, intact and self-sufficient, exactly as if the merge phase were not specified. The merge summary and log are terminal records, not upstream dependencies: nothing is built from them and they are never re-hashed.

5. **Move, not copy — merged files leave by-dest.** Merge **moves** each successfully-placed photo into the library and **removes it from `6-photos-by-dest`**. A fully successful merge moves every photo (or confirms it already in the library) and leaves by-dest **empty of photos** (which is what permits sealing, Section 13.7); a file that cannot be merged — a **blocker** (un-fingerprintable library file on a collision, unresolved collision, or a failed move; merge spec Sections 7, 8, 11) — is **left in by-dest** and keeps the run `partial` *without* sealing, so the operator can resolve it and re-run. The move is performed safely and atomically (Section 15): for each file, copy to a temporary name on the library volume → verify (fingerprint) → atomically rename into the just-verified-free library target → **only then** remove the by-dest source; the source removal is the last, journaled step, so a crash never loses a file (it remains in by-dest until the library copy is verified and in place). A library file is never deleted or mutated. "Already-present" files — content identical to a file already in the library (item 3) — are treated as successfully in the library and are likewise **removed from by-dest** (the library holds the content). This realizes the operator's intent that the workspace not keep duplicates of files already in the library — keeping only what still needs attention, and nothing once the merge fully succeeds.

6. **Idempotent and resumable.** A re-run recognizes files already in the library (same content already at the mapped path, item 3) and moves nothing for them beyond completing any interrupted by-dest source removal; it applies only the outstanding moves. An interrupted merge is finished by re-running. A merge over a fully-merged batch is a no-op — by-dest holds only leftovers (or is empty) and every mapped target already holds identical content (Section 11).

### 13.6 Merge re-seals the archival package; the workspace becomes terminal

Merge requires that calibration was finalized (Section 13.5; merge spec Section 3) — it operates on the finalized record. But merge then *adds to* that record: it writes its own log `photos-35-merge-log.json` (copied forward from `photos-25` and extended with library destinations), captures the end-of-merge DB snapshot `photos-35-merge-ingest.db`, and writes `photos-31-merge-summary.json`. So the package finalize sealed no longer reflects the full state. Two consequences:

1. **Merge re-seals the archival package automatically.** On successful completion (every by-dest photo moved into or confirmed already in the library, with no un-merged photo left — Section 13.7 / merge spec Section 9.4), merge re-assembles the archival package (Section 13.2) so it includes the merge log `photos-35-merge-log.json`, the merge summary, and the end-of-merge DB snapshot, and re-writes the self-describing manifest with the updated SHA-256s. This is **automatic**, not a separate command: the whole point of merge is to land the batch in the library, so the operator should get the complete, library-aware archive as a matter of course. (Contrast calibration's finalize, Section 13.1, which stays a deliberate, separately-invoked step precisely because calibration is freely re-run and re-finalizing after every pass would be wasteful; merge, by contrast, is the terminal action for the workspace — Section 13.7 — so re-sealing once at its end is the right standard behavior.) Merge re-seals by bundling the now-current artifacts (a read of each, never editing another phase's file, Section 13.0a); it does not re-run calibration's finalize logic or re-derive calibration's portion of the record.

2. **The workspace becomes terminal.** A successfully merged workspace has done its job: its batch is in the permanent library and its complete archive is sealed. The workspace must not be silently reused for a fresh dump, because it is no longer a clean slate — see Section 13.7.

### 13.7 Terminal (sealed) workspace: do not reuse after merge

After a successful merge, the workspace is **sealed**: it is marked terminal and the pipeline refuses to process new media in it. A merge reaches success only when every by-dest photo has moved into the library (or was confirmed already there) and **no un-merged photo remains in `6-photos-by-dest`** (Section 13.6; merge spec Section 9.4) — so a *sealed* workspace's by-dest is empty of photos. Even so, an empty by-dest is **not** a reliable signal that the workspace is a clean slate, and treating it as one would be unsafe; the seal is a deliberate stance, not a convenience.

Why a merged workspace is not "virgin" even though its by-dest is empty:

1. **State persists.** The SQLite database still holds the merged batch's identity rows, the manual-GPS pre-state ledger (calibration Section 24.1), and the library-file fingerprint cache (Section 13.4); the per-phase DB snapshots, the per-phase logs, and the sealed archive sit in `.photos-ingest/`; residuals may remain in `1-strays`, `2-missing-metadata`, `3-redundant-jpgs`, `4-videos-by-date`, and the quarantine tree (Section 5 / prep). Any new dump dropped in later sits where the operator put it (the workspace root, or `0-sources`), **untouched**, because every script aborts on a sealed workspace (item 2). A new dump processed on top of this would interleave with a prior batch's record and caches — which is exactly why it is refused.
2. **by-dest emptiness is ambiguous, not authoritative.** An empty by-dest can mean "merged and done" (sealed) or "freshly created / sorted but not yet merged" (not sealed); a *non-empty* by-dest during an unfinished run means a merge is still outstanding (un-merged leftovers / blockers, which prevent the seal). Emptiness alone is therefore not a reliable signal either way — the durable **terminal/sealed marker**, not the folder state, is the authority for whether a workspace is finished.
3. **The archive describes one dump's journey.** The sealed package (and the transformation logs keyed by content fingerprint) is the record of *this* workspace's batch. Mixing a second, unrelated batch into the same workspace would muddy that record and the per-phase DB images.

The mechanism:

1. **A terminal seal mark.** On successful merge (no un-merged photo remaining), the workspace records a durable **terminal/sealed marker** in the control directory as a **separate file alongside the workspace guard**, `photos-00-sealed.json` (Section 5.1) — *not* a field written into `photos-00-workspace-guard` itself (the guard is prep's init sentinel and prep is its only writer; the seal is merge's, so they are kept as distinct files). The marker records that the workspace was merged, the merge run id, and `library_root`, and its mere presence is what seals the workspace. The marker is part of the sealed state, not editable casual config. A `partial` merge (blockers still in by-dest) or a failed/crashed run writes **no** marker, so the workspace stays open and the operator can clear the blocker and re-run (merge spec Section 9.4).
2. **Every *mutating media* script refuses a sealed workspace — sealed means sealed.** Prep, calibration, **and merge** each check for the terminal marker at startup (right after taking the lock and verifying the guard, before any scan or plan). If it is present, the script **hard-stops immediately, mutating nothing and touching nothing** — there is no confirming re-run, no sweep, and no recovery utility. A sealed workspace's durable outputs may still be *read* (open the archive, inspect the DB), but no script ever organizes, calibrates, or merges it again.
   - **Exception — `prune-quarantine` is permitted on a sealed workspace.** Prep's `prune-quarantine` command (prep Section 15.3) is the one deliberate exception, because it has **no impact on any controlled content**: it deletes only recoverable duplicate copies under `.photos-ingest-quarantine/` (the quarantine tree persists on a sealed workspace, item 1), and it never touches a library file, a by-dest photo, the managed media, the SQLite DB's identity/ledger rows, or the archival record. Sealing exists to stop a finished workspace from being *re-processed* or having a *second batch* interleaved with it; reclaiming quarantine space does neither. So `prune-quarantine` still runs on a sealed workspace (under the workspace lock like always, Section 2), while every media-mutating path stays barred. (It remains the only operation that removes quarantine contents, still never implicit, still requiring explicit confirmation — prep Section 15.3.)
   The way forward for adding media is always a fresh workspace (item 3).
   - **New-dump warning.** If, on a sealed workspace, a script sees files at the **workspace root** *or* in **`0-sources`** (the two places a dump would land), it additionally reports that a **likely new dump was detected** and that, because this workspace is done, the dump must be moved by hand into a **fresh workspace**. The script leaves the dump exactly where it is — it never relocates, organizes, or records it. (This subsumes what the old stray-collection utility did: recovery is now simply "the files are untouched and visible; move them yourself," which is safer than any automated touch of a frozen workspace.)
3. **The way forward is a new workspace.** To process more media, the operator starts a new workspace (a fresh control directory and a fresh SQLite DB) and runs the loop from the start (init). The permanent library is shared across workspaces (merge's library-side lock, Section 15.2, exists precisely so multiple workspaces can merge into one library safely); the *workspace* is single-use through to merge. (Resuming an *interrupted* merge is a different case and predates the seal: the seal is written only on full success, so an interrupted run left the workspace unsealed and re-running completes it — that is not a sealed-workspace re-run.)

This makes "workspace" genuinely transient and single-batch: prep → … → calibrate → finalize → merge → **sealed**. The durable outputs (the library and the archival package) live on; the workspace does not invite reuse.

---

## 14. Input-validation discipline: sanity-check everything authored by a human

Every value that originates from a human — config fields (Section 4) and the decision fields in the numbered JSON artifacts (Section 12) — must be **sanity-validated before it is used**, in addition to the dependency cascade (Section 9). Fingerprinting detects *change*; validation detects *invalid content*. A value can be perfectly current (matching its fingerprint) yet meaningless or dangerous; a value can also be freshly typed and wrong. Both checks are required, and validation runs whenever a human-authored value is first consumed in a run.

This is a direct consequence of the authored-decisions stance (Section 12): because the user writes decisions and config by hand, the pipeline must not assume they are well-formed. Catching a malformed value early — with a clear, located error — is part of "every change is explainable and the user retains authorship": a typo'd timezone or an unsafe path is reported as a specific, fixable problem, not silently coerced, half-applied, or allowed to corrupt a downstream operation.

### 14.1 What must be validated

At minimum:

1. **Config paths** (`gpx_root`, `library_root`, control-directory and workspace paths, any configured output location): must resolve to a sane, syntactically valid path of the expected kind; must not contain characters illegal for the platform; must not escape where they are required to stay (e.g. a path required to be outside the managed `0`–`6` tree, Section 8.2, or a `library_root` that must be a directory). An empty or whitespace-only required path is invalid.
2. **The ZFS snapshot configuration** (`zfs` block, Section 3): the dataset/pool names and especially any **snapshot name prefix** must be valid snapshot-name components — they must not contain characters that would make a resulting `dataset@prefix-<plan_id>` snapshot name invalid (e.g. whitespace, `/`, a second `@`, or other characters ZFS forbids in a snapshot name). An invalid prefix is rejected before any snapshot is attempted, so a snapshot failure never surprises execution mid-run.
3. **Timezones**: any IANA timezone string a user enters (e.g. a destination timezone decision, calibration Section 18) must be a real, resolvable zone, not an arbitrary string.
4. **Coordinates and offsets**: manually entered GPS coordinates must be in-range (latitude −90…90, longitude −180…180) and numerically well-formed; manual UTC offsets / `manual_real_utc` values must parse and fall within sane bounds.
5. **Filename format** (`filename_timestamp_format`, Section 7): must be a usable timestamp format that produces a non-empty, filesystem-safe component and contains no path separators or illegal filename characters.
6. **Threshold and numeric config** (GPX distance/time thresholds, job counts, etc.): must be of the right type and within sane ranges (e.g. non-negative durations and distances).
7. **Enumerated / structured decision values**: boolean decision flags must be booleans; device-group classifications and other enumerated fields must be among the permitted values; a decision object must have the shape the artifact defines (the user fills values, not structure, calibration Section 9/20 — a structurally broken decision is a validation error, not a silently-ignored one).

This list is the conceptual surface; each phase spec names the concrete fields it validates and where (prep validates the config it seeds and reads; calibration validates config plus the calibration decision JSONs; merge validates `library_root` and merge-policy config). The principle — *no human-authored value is consumed without a sanity check* — is shared and authoritative here.

### 14.2 How validation behaves

1. **Fail closed, before mutation.** A validation failure is a hard blocker reported in the textual output (and, for a decision field, located precisely: which artifact, which destination/group/file, which field). The phase does not produce a downstream artifact or mutate anything from an invalid value — it stops exactly as it does for a stale dependency or a hard input guard.
2. **Locate the cause.** Because the offending value is human-authored, the error names the file and field so the user can fix the source directly and re-run (Section 12 part 2). Validation never "repairs" a value silently.
3. **Validate at consumption, every run.** Validation is re-done whenever the value is consumed, not cached as "once valid, always valid" — an edit between runs is re-checked. (A value's *content* is validated here; its *change* is what the fingerprint cascade tracks, Section 9.)
4. **Preserve, don't delete, an invalid authored value.** Consistent with calibration Section 9, an invalid user decision is preserved and flagged as requiring correction, not erased; the user retains what they wrote so they can see and fix it.

---

## 15. Execute-time no-clobber and filesystem atomicity

Both the safety model's "no operation overwrites existing content" promise and the resume guarantees depend on filesystem operations being **defensive at the moment they execute**, not merely planned to be safe. This section states the shared rule; prep Section 14.3 and 14.4, calibration Sections 27 and 29.1a, and the merge spec implement it.

1. **No-clobber is re-checked at execute time, not assumed from the plan.** A plan is computed against a snapshot of filesystem state and may be validated against current state (the dependency cascade, Section 9), but the executor must **still verify, immediately before each individual filesystem mutation, that the specific target does not already exist** (case-insensitively where the filesystem is case-insensitive). The planner's collision analysis (prep Section 8 / calibration Section 27, which treat every on-disk and planned name as permanently occupied) is the first line of defence; the execute-time check is the second, independent one. Execution must never write or rename onto an existing path on the strength of the plan alone — if the target unexpectedly exists at execute time, the operation is a blocker (or, where the operation class permits and the plan recorded a safe alternative allocation, it is re-checked against that), never a clobber. This applies to every content-bearing operation: prep moves/renames/quarantine, calibration renames, and merge placement into the library.
2. **Operations are atomic where the filesystem allows.** A move, rename, or placement should be a single atomic filesystem operation so an interruption leaves either the pre-state or the post-state, never a partial result. A metadata write that rewrites a file in place is performed atomically — write to a temporary file and atomically rename it into the final name, or use the tool's safe-write mode — so a crash mid-write leaves the intact original or the fully-written file, never a corrupt intermediate (calibration Section 29.1a). Atomicity and the execute-time no-clobber check compose: the atomic rename that finalizes an operation is itself a no-clobber rename onto a target just verified free.
3. **Cross-filesystem placement stays atomic-equivalent; a move removes the source last.** Where an operation crosses filesystem boundaries (notably merge **moving** files into a library that may be on a different volume, so a same-inode `rename` is unavailable), the executor must preserve the same guarantee by an equivalent technique: copy to a temporary name on the destination filesystem, verify, then atomically rename into the final (just-verified-free) target, and treat a crash as leaving either no destination file or the complete one — never a half-copied file presented under the final name. For a **move** (merge), the source is removed only **after** the destination copy is verified in place, as the last journaled step — so a crash leaves the file in the source, or in both source and destination (resume completes the source removal), but never lost and never half-present (merge spec Section 11).
4. **A failed operation is left clean and reported.** If an operation cannot complete (tool failure, unexpected existing target, permission error), the executor leaves the file at its pre-operation state, records the failure, and never records the operation as applied (so resume does not treat it as done). This mirrors calibration Section 29.1a item 4 and prep's blocker handling, and applies equally to merge.

### 15.1 Library facts shared with merge

Three library-side facts are stated here because they constrain the merge spec and are referenced by the cross-phase loop (Section 10.4):

1. **`library_root`** (Section 4.3) is the permanent library directory merge places files into. It is validated like every other configured path (Section 14.1) and is **outside** the workspace and its managed `0`–`6` tree.
2. **The library is never rescanned wholesale and never mutated except by additive, no-clobber placement.** Merge reads an existing library file only to fingerprint it on a path collision (Section 13.5 item 3), caches that fingerprint (Section 13.4), and otherwise leaves the library untouched. There is no library-wide index, no library de-duplication, and no library renaming — the library's organization is assumed correct and authoritative.
3. **Library identity is a single dotfile marker, created once.** Unlike a workspace, the permanent library has **none** of the workspace scaffolding — no managed `0`–`6` folders, no workspace guard, no lifecycle. A directory is recognized as a library by **one sentinel: an empty `.photos-library` marker file in `library_root`**, and by nothing else — merge performs **no** structural inspection, folder count, or present/absent check on the library beyond this marker. The marker is created by an explicit, idempotent one-time **`init-library`** command (merge spec Section 4); the merge data path (`plan`/`dry-run`/`execute`) only **reads** it and hard-stops if it is absent, exactly as prep's init is the sole creator of workspace structure. Merge still creates ordinary missing destination subdirectories under `library_root` when placing a file (additive placement), which is not structural validation.

### 15.2 Library-side lock

Because two different workspaces could be merged into the same library, merge takes a **library-side lock** (keyed to `library_root`) for the duration of its run, in addition to the workspace lock (Section 2). This guarantees that no two merge runs write the same library concurrently, even when they originate from different workspaces with different workspace locks. The library lock follows the same fail-fast, stale-detectable discipline as the workspace lock (Section 2 items 3–4): a merge that cannot take the library lock exits without touching the library.

The lock is realized as a **`.photos-merge.lock` dotfile in `library_root`** (the sole library-side construct besides the `.photos-library` identity marker, item 15.1.3; it stores only the holder's stale-detection record and nothing about library state). Because the lock file is written *into* `library_root`, merge confirms the directory is a library — the `.photos-library` marker is present (item 15.1.3) — **before** acquiring the lock, so no `.photos-merge.lock` is ever dropped into a directory that is not a blessed library. The acquisition order is therefore: workspace lock, then `library_root` validation and the marker identity check (both under the workspace lock), then the library lock; a merge that fails any of these exits cleanly having mutated nothing.
