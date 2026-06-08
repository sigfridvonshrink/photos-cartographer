# Photos Pipeline Shared Contract (`photos-shared-contract`)

## 1. Purpose and status

This document is the single authoritative home for facts that span both phases of the photos pipeline:

1. the preparation phase, `photos-1-prep` (`10_photos-1-prep-workflow.md`);
2. the time/GPS calibration phase, `photos-2-time-gps` (`10_photos-2-time-gps-workflow.md`).

Anything that both phases must agree on — the workspace lock, the pre-mutation snapshot mechanism, the shared configuration object, the workspace control directory, the camera-group identity key, the filename timestamp format, the GPX root, and the end-to-end operator loop — is defined here and is authoritative here. The two phase specifications reference this document rather than restating these facts, so the contract cannot drift between them.

This is a workflow/contract specification, not a script implementation specification. It describes *what* both phases must share and uphold, not the classes or modules that implement it.

---

## 2. Workspace lock

The pipeline is protected by a single workspace-wide lock. There is exactly one lock for the whole workspace, shared by every pipeline command, and it enforces **total mutual exclusion of pipeline processes**: at most one pipeline invocation may be running against a given workspace at any time. This excludes every concurrent combination — two prep runs, two calibration runs, a prep run and a calibration run, or any of these overlapping with the finalize/archive command (Section 13) or prep's `prune-quarantine` command. Any command that reads or touches the workspace takes the lock; only one holds it at a time.

The lock guards the entire run, not just mutation:

1. The lock is acquired at process startup, immediately after the workspace root is resolved and the root sentinel (`photos-00-workspace-guard`) is verified, and **before any planning, scanning, hashing, metadata extraction, dry-run, or execution begins**. Planning is non-mutating, but it must still not run concurrently: a plan computed against a workspace another process is reading or mutating is untrustworthy, so planning is inside the lock too.
2. The lock is held for the duration of a run — across plan, dry-run, execute, cache update, and handoff/artifact writes — and released when the script finishes (success or failure). It is per-run, not a persistent lock on the workspace between runs: when no script is running, the workspace is unlocked.
3. Acquisition is **fail-fast, not blocking**. If the lock is already held by another run, the invocation does not wait: it exits immediately with a clear message that the workspace is locked by an in-progress run, and performs no scan, no planning, and no mutation. It produces no plan, no dry-run report, and no artifact.
4. The lock must be released on normal exit and on error. A lock left behind by a crashed process (a stale lock) must be detectable as stale — e.g. by recording the owning process identity/liveness and start time — and recoverable, so a crash does not permanently wedge the workspace. Stale-lock takeover must be conservative: only a lock whose owner is provably gone may be reclaimed.

Because the lock covers planning as well as execution, the per-phase `plan` / `dry-run` / `execute` lifecycles described in `10_photos-1-prep-workflow.md` Section 14 and `10_photos-2-time-gps-workflow.md` Section 29 all run with the lock already held; those sections do not re-acquire or independently scope the lock. This whole-run lock is independent of, and stricter than, the dependency-revalidation discipline (Section 9): revalidation guards against *stale* inputs across separate runs, while the lock guarantees runs never overlap in the first place.

---

## 3. Pre-mutation snapshots: the `zfs` block

Both phases can take an optional pre-mutation snapshot before applying any planned mutation, using the same mechanism so the two phases behave identically and cannot diverge. **Snapshots are an optional extra safety layer, not a requirement.** The pipeline operates fully and safely without them: correctness and recoverability rest on the journal, recoverable quarantine, no-clobber operations, and filesystem-as-truth reconciliation (prep Section 14.4; calibration Section 29.1). Snapshots add a clean-slate rollback path on top of those for operators whose filesystem supports it; they are not the basis of the safety model.

1. The snapshot mechanism is configured by the `zfs` block in the workspace config `photos-00-config.json` (Section 4). It is disabled by default unless explicitly configured; ZFS is not assumed and is not a prerequisite for running the pipeline.
2. Snapshots are keyed by plan id, so each plan's pre-mutation state is independently identifiable.
3. `snapshots_required` governs strictness: when true, a failure to take a required snapshot is fatal and execution aborts before mutating; when false (or when snapshots are not configured), execution proceeds without a snapshot and relies on the journal/quarantine/no-clobber safety layer above.
4. When taken, the snapshot is taken after the plan has been dependency-validated and the lock acquired, but before the first mutation.

The mechanism is named for ZFS because that is the reference implementation, but it is deliberately the *only* part of the pipeline that touches a specific filesystem feature, and it is optional; everything else is filesystem-agnostic.

`10_photos-1-prep-workflow.md` Section 14.3 and `10_photos-2-time-gps-workflow.md` Section 29 invoke this mechanism; neither redefines it.

---

## 4. Shared configuration (`photos-00-config.json`)

Both phases read a single shared configuration for the whole pipeline. The config is a **workspace artifact** — a JSON file, `photos-00-config.json`, living alongside the other persistent artifacts in the control directory `.photos-ingest/` — not an ambient in-code global. The two phases consume different keys from it but never maintain separate configs.

### 4.1 A pinned, per-workspace artifact

Making the config a file binds it intrinsically to the workspace and to everything processed in it:

1. **Seeded by prep.** On a prep run, if `photos-00-config.json` is absent, prep creates it from the in-code default template (`photos_utils.CONFIG`). If it is present, prep uses it as-is. The in-code `photos_utils.CONFIG` is therefore only a **default template for seeding a fresh workspace**; once the file exists, the workspace copy is authoritative and governs all processing in that workspace, regardless of what the code's defaults later become.
2. **Prep is the sole writer; the user hand-edits.** Like the handoff, the config file is written by prep alone (prep seeds it once). (The SQLite DB is shared-write — prep owns its cache/identity content, calibration owns its derived regions, Section 13.4 — but the config file, like the handoff, has a single writer: prep.) To change configuration, the user edits the JSON by hand — it is an authored input in the same sense as the decision fields (Section 12). Calibration is strictly **read-only** with respect to config; it never writes it.
3. **Hashed like every other artifact.** Because it is a file, it is SHA-256'd and folded into the dependency-fingerprint cascade (Section 9) exactly as the handoff and numbered artifacts are — closing the gap where an ambient config could change a run without leaving a trace. Its whole-file SHA-256 is recorded for integrity (and in the archival manifest, Section 13).
4. **Archived.** It is part of the archival package (Section 13.2), so a future reader knows not only what was decided but **under what configuration**.
5. **In the control directory.** It lives in `.photos-ingest/` (Section 5), which prep skips wholesale, so prep never treats it as managed media or folds it into the media cache fingerprint.

### 4.2 Granular staleness, plus a whole-file hash

The config is the root of the dependency cascade (Section 9), but staleness stays **surgical**: the fingerprints remain field-scoped, so a change to one area invalidates only what depends on it. A GPX-threshold edit restales GPS/plan artifacts but not the rename plan; a filename-format edit restales renames but not GPS placement. The whole-file SHA-256 is used for integrity and archival, **not** as the staleness trigger — collapsing all staleness to a single whole-file hash would needlessly restale unrelated artifacts on any edit and is explicitly not done.

So two things are derived from the file: (a) field-scoped fingerprints (filename-format, camera-time/timezone policy, GPX thresholds, camera-group-key version, snapshot policy, …) that drive precise staleness; and (b) one whole-file hash for integrity/provenance.

### 4.3 Config areas

Config areas relevant across phases include, at least:

1. the `zfs` snapshot block and `snapshots_required` (Section 3);
2. the workspace control directory (Section 5);
3. camera-group identity and classification: `CAMERA_GROUP_KEY_VERSION` and `camera_time_and_timezone_policy.device_groups` (`phones`, `fixed_clock_cameras`) (Section 6);
4. the filename timestamp format, the shared key `filename_timestamp_format` (Section 7);
5. the GPX root and GPX matching thresholds, e.g. `gpx_root`, `gpx_direct_match_max_seconds`, `gpx_interpolation_max_gap_seconds`, `gpx_interpolation_max_distance_meters` (Section 8);
6. camera-time/timezone policy flags, e.g. `single_anchor_auto_apply`, `multi_anchor_auto_apply` (consumed by calibration).

The precise key names, defaults, and which-phase-consumes-which are finalized in the sections cross-referenced above (Sections 5–8). This list is the conceptual surface; the per-key detail lives in those sections.

---

## 5. Control directory: everything lives in `.photos-ingest/`

All pipeline control and artifact files live inside a single workspace control directory, `.photos-ingest/`. Nothing pipeline-related sits among managed media or at the workspace root. Prep walks the workspace to inventory media and skips `.photos-ingest/` **wholesale** (as a whole subtree), so a control or artifact file can never be mistaken for a photo. There is no per-file "ignore list" to maintain — consolidating everything in one skipped directory replaces the basename registry that earlier designs needed.

### 5.1 Contents

```text
.photos-ingest/
  photos-00-config.json            workspace configuration (seeded by prep, Section 4)
  photos-00-workspace-guard        workspace guard / sentinel
  photos-00-ingest.db              SQLite identity/metadata cache + derived caches (Section 13.4)
  journal-*.json                   execution journals
  photos-11-handoff.json           prep-phase artifact: handoff manifest
  photos-21-time-decisions.json    calibration-phase artifact
  photos-22-gps-decisions.json     calibration-phase artifact
  photos-23-executable-plan.json   calibration-phase artifact
  photos-24-execution-summary.json calibration-phase artifact
  photos-25-complete-log.json      calibration-phase artifact: full transformation log (at finalize, Section 13.3)
  gpx/                             default gpx_root (Section 8)
```

**Numbering convention.** The first digit identifies the phase that produces the file — nothing more:

```text
0X  workspace infrastructure (phase-neutral): config, guard, database
1X  prep-phase artifacts        (currently: 11 = handoff)
2X  calibration-phase artifacts (currently: 21–25)
```

That is the whole meaning of the scheme: read the first digit to know the producing phase. The second digit is just a sequence number within the phase and carries no further significance — absent numbers (there is no `photos-07`, no `photos-12`–`19`, etc.) are not reserved, not headroom, and not missing; they simply don't exist. Do not infer anything from a gap. The shorthand `photos-0X-*.json` (and `1X`/`2X`) refers to a band of numbered artifacts collectively.

Skipping is directory-level: prep skips `.photos-ingest/`, `.photos-ingest-quarantine/`, and `.git` as whole subtrees, plus dotfiles (`10_photos-1-prep-workflow.md` Section 3). A `gpx_root` misconfigured to resolve inside the managed `0`–`5` tree is the one case needing an extra subtree skip (Section 8).

### 5.2 The handoff is hashed despite living in the skipped directory

`photos-11-handoff.json` lives in `.photos-ingest/` and so is never inventoried as media. That is independent of its role as a dependency: calibration treats it as a first-class SHA-256 dependency, re-hashed from its exact bytes before use (`10_photos-2-time-gps-workflow.md` Section 4). So the handoff is invisible to prep's media scan yet fully verified as a JSON dependency by calibration — there is no weaker "handoff fingerprint" path.

Prep `10_photos-1-prep-workflow.md` Section 3 and calibration `10_photos-2-time-gps-workflow.md` Section 8.1 reference this control-directory model rather than maintaining their own ignore lists.

---

## 6. Camera-group identity (`camera_group_key`)

Both phases identify a camera/device by a single derived key so grouping is computed once (by prep) and reused (by calibration), never reinvented.

1. Prep computes `camera_group_key` from device-identity metadata (serial/make/model/owner fields) and emits it in both the handoff manifest and SQLite.
2. The derivation is versioned by `CAMERA_GROUP_KEY_VERSION`; the version participates in metadata-freshness and dependency fingerprints so a change to the derivation is detectable rather than silently mixing old and new keys.
3. Calibration reuses prep's `camera_group_key` rather than recomputing identity. Mobile vs fixed-clock *classification* is a separate config concern, governed by `camera_time_and_timezone_policy.device_groups` (`phones` = mobile, `fixed_clock_cameras` = fixed-clock) in the shared config (Section 4). A group is "known" when its key is listed under one of those classes.

`10_photos-1-prep-workflow.md` (Section 12) emits the key; `10_photos-2-time-gps-workflow.md` (Section 16) consumes and classifies it.

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

The format is never hard-coded in either phase; both read this key, and the key participates in the dependency-fingerprint cascade (Section 9). Changing it makes any artifact whose names depend on it stale — in prep, the by-date organization; in calibration, the executable rename plan.

> The calibration specification historically referred to this key as `calibration_filename_timestamp_format`. It is the **same** key as `filename_timestamp_format` defined here; the phase-neutral name is authoritative because the key is shared, and any remaining phase-specific name is an alias for it.

### 7.2 The differentiating suffix

A file whose timestamp component collides with one already taken receives a zero-padded differentiating suffix, allocated deterministically and no-clobber:

```text
<timestamp>.ext        first file with a free base name (no suffix)
<timestamp>-001.ext    first collision
<timestamp>-002.ext    second collision
```

The suffix (`-NNN`) is allocated against a per-run, case-insensitive, **monotonic** index — it only grows, always taking the next value above the current highest in use, never reusing a freed-up lower number — so two files never collide and ordering is stable. Suffix allocation rules (treating all on-disk and planned names as occupied for the duration of the allocation loop) are specified per phase where the renames are planned (prep Section 8 / Section 7.3; calibration Section 27).

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

GPX track files are consumed only by calibration (`10_photos-2-time-gps-workflow.md` Section 15), for time-anchor proposals and for GPS interpolation/extrapolation. Prep never parses, fingerprints, or organizes them. The shared rule that makes this safe is **where the GPX files live**.

### 8.1 Location

The GPX folder is configured by `gpx_root` in the shared configuration (Section 4). `gpx_root` resolves to a path **outside the managed media tree** — that is, not under any of the numbered folders `0-source` … `5-photos-by-dest`. The default location is under the prep control directory:

```text
.photos-ingest/gpx/        default gpx_root
```

which is already outside the managed tree (prep treats `.photos-ingest/` as control, not media). `gpx_root` may instead be configured to an arbitrary path outside the managed tree (including an absolute path elsewhere on disk). Keeping GPX outside `0`–`5` means prep's normal scan never encounters GPX files, so they can never be misclassified as `other`-class media or swept into `0-source` and organized.

### 8.2 Prep's only obligation

Prep stays GPX-unaware: it does not read, parse, fingerprint, or move GPX files. Its sole obligation is defensive — **if `gpx_root` resolves to a location inside the managed media tree** (a misconfiguration), prep must skip that subtree during scanning exactly as it skips `.photos-ingest-quarantine` and registered control files, so GPX files are never organized even under a bad configuration. Prep does not otherwise act on GPX.

### 8.3 Calibration's use and fingerprinting

Calibration owns all GPX behaviour: scanning `gpx_root`, parsing tracks, computing the GPX fingerprint, and using it as evidence. The GPX fingerprint participates in calibration's dependency cascade (Section 9): it becomes an upstream dependency of `photos-21-time-decisions.json` when GPX is used for time anchors, and of `photos-22-gps-decisions.json` / `photos-23-executable-plan.json` when GPX is used for GPS placement. The `gpx_root` value and GPX matching thresholds live in the shared config (Section 4); their detailed semantics are in `10_photos-2-time-gps-workflow.md` Sections 15 and 19.

---

## 9. Dependency-fingerprint discipline

Both phases enforce the same anti-stale rule, stated in full in each phase spec (prep Section 5; calibration Sections 3–6):

```text
validate upstream -> create artifact -> record dependencies in it -> reject downstream use if dependencies changed
```

The shared facts that feed these fingerprints — config (Section 4), control directory (Section 5), camera-group key version (Section 6), filename format (Section 7), GPX root/fingerprint (Section 8), and the snapshot mechanism (Section 3) — are defined here so that a single change has one authoritative source and a predictable staleness footprint in both phases.

---

## 10. Canonical cross-phase operator loop

This section is the authoritative end-to-end view of how an operator drives both phases. Each phase spec describes only its own loop; this is the sequence that spans them.

```text
1. PREP            plan -> dry-run -> execute
                   photos organized into 4-photos-by-date, videos into
                   3-videos-by-date, untimestamped into 1-missing-metadata,
                   residual other-class files left in 0-source (expected).

2. SORT (user)     move PHOTOS ONLY from 4-photos-by-date into 5-photos-by-dest.
                   by-dest stays photo-only: no non-media, no videos (videos
                   remain in 3-videos-by-date). [cal 7.2, 7.3]

3. RE-PREP         MANDATORY after the latest move. Prep recognizes the moves
   (mandatory)     (stat-only, no re-hash/re-read), carries cache identity
                   forward, refreshes handoff + cache. [item 3 / prep 10.1, 10.2]

4. CALIBRATE       convergent rerun loop (cal 2.1):
   (loop)          run -> inspect blockers -> edit human-decision fields in the
                   photos-2X JSON -> rerun -> ... until photos-23-executable-plan.json is ready.

5. EXECUTE         apply planned time/GPS metadata + renames; write
                   photos-24-execution-summary.json.

6. (optional)      add more media later: drop into the workspace (a new dump),
   ADD MORE        then RE-PREP (step 3), re-SORT photos, and RE-CALIBRATE
                   (steps 4-5). Allowed even after a prior successful calibration.

7. DEVELOPMENT     the jpg/tif breakout. Runs ONLY once calibration is settled.
   (later phase)   Starting it earlier is a hard-stop. [item 4 / cal 7.1]
```

### 10.1 Calibration is freely re-runnable, not one-shot

Calibration is not a terminal, run-once phase. It may be re-run any number of times — including after a prior successful execution — to absorb media added later. This is safe because:

1. human decisions (timezones, accepted anchors, manual offsets, manual GPS) live in the `photos-2X` calibration JSON and are preserved across regeneration where their logical target is unchanged (cal Section 9);
2. GPS that calibration applied is recognizable on rerun (e.g. via the `GPSProcessingMethod` marker), so already-placed files are no-ops, not re-writes;
3. renames are computed from destination-local civil time, so an already-finalized file recomputes to the same name and is a no-op (cal Section 27).

What bounds the freedom is a small, fixed set of gating preconditions, not a "has calibration run before?" flag. Calibration may proceed whenever, and only when:

```text
a. 4-photos-by-date contains no photo files;          [cal 7]
b. 5-photos-by-dest is photo-only — no non-media
   files and no videos (videos stay in
   3-videos-by-date);                                   [cal 7.2, 7.3]
c. no jpg/tif development subfolder exists under
   5-photos-by-dest (development not started);          [cal 7.1]
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

---

## 11. Idempotency: change only what needs changing

Both phases are idempotent in the same sense, and to the greatest extent the work allows: **a run changes only what actually needs changing, and a run over unchanged inputs is a no-op.** Neither phase redoes settled work to "be safe," and neither leaves a file in a different state than its inputs require.

The shared principle has four parts:

1. **Reuse, don't recompute.** Work already done and still valid is reused, not repeated — prep reuses cached hashes and metadata for files whose size/mtime (and move-aware identity) are unchanged; calibration reuses resolved UTC and preserves human decisions whose logical target is unchanged. Expensive operations (hashing, metadata extraction, GPX parsing) run only for genuinely new or changed inputs.
2. **Recompute only what staleness forces.** When an upstream input changes, only the artifacts whose dependency fingerprints actually depend on it become stale and are regenerated; unaffected artifacts are left as-is. This is the dependency cascade of Section 9, run minimally.
3. **Mutate only on a real difference.** A file is moved, renamed, or metadata-written only when its current state differs from the planned target. A file already in its correct location with its correct name and metadata produces no operation — it is reported as a no-op, not re-applied. Calibration's renames recompute to the same name for an already-finalized file; prep does not re-move or re-normalize files already in place.
4. **A no-op run is a no-op.** Re-running either phase on a workspace whose relevant state has not changed produces zero mutations and a stable, equal result (same plan, same fingerprints, same names), reporting cache hits and already-correct files rather than treating prior work as error.

Each phase states the concrete consequences of this principle in its own terms — prep in `10_photos-1-prep-workflow.md` Sections 13 and 21 (idempotency, incremental operation, staleness examples), calibration in `10_photos-2-time-gps-workflow.md` Sections 29.1 and 30 (execution idempotency/resume, recalculation). This section is the single statement of the principle they share.

---

## 12. Authored decisions: nothing changes that the user did not write down

Every mutation either phase performs traces back to an explicit, recorded human decision or to a deterministic rule applied to recorded inputs — never to an autonomous, unexplained choice by the tool. This is a deliberate trust stance for irreplaceable data: the pipeline is built so that a user who distrusts opaque automatic mutation can always answer *why did this change happen?* and can revise the answer.

The principle has three parts, and the existing machinery already implements all three:

1. **No autonomous mutation.** The machine *proposes* (time-anchor offsets, GPS placements, timezone candidates); the user *disposes* by filling decision fields in the numbered JSON artifacts; the executor acts only on the disposed plan. Human-decision fields are authored by the user and never silently overwritten (calibration Section 9). Required fields are pre-created so the user fills values, not structure (calibration Section 20). Prep embeds no human decisions and instead derives organization deterministically from filesystem state — also a recorded, inspectable input, not an opaque choice.

2. **Locatable cause.** Because decisions live in durable artifacts, every executed operation can be traced to the recorded decision and the fingerprinted inputs that produced it: decision artifact → dependency fingerprints (Section 9) → executable plan → journal of what executed (prep Section 14.3; calibration Section 29). When an output is wrong, there is a specific recorded decision to point at, so the cause is attributable to an authored choice rather than to tool behaviour.

3. **Re-derivable, never a one-way door.** Decisions are data and the pipeline is idempotent (Section 11) and non-destructive (no-clobber on content; recoverable quarantine; read-only destinations). The user changes a decision in the artifact, re-runs, and the dependency cascade re-derives everything downstream that the change affects. No mutation the tool makes is irreversible at the decision level — a wrong choice is fixed by editing the record and re-running, not by manual repair of mutated files. Withdrawing a decision *undoes* its effect, not merely stops re-asserting it: for **manual GPS overrides** this is guaranteed by a pinned pre-state ledger that restores the original GPS (or clears it, if there was none) when the override is removed (calibration Section 24.1); automated GPS is recomputed rather than rolled back; time and filename are recomputed in place within the file's destination under `5-photos-by-dest` (the rename and timestamp rewrite never relocate the file to another destination or elsewhere in the tree), since reverting them would un-position an organized file.

Together with the safety model (validated plans, no-clobber, recoverability) and idempotency (Section 11), this means the user retains authorship: nothing changes that they did not write down, every change is explainable from the record, and any change can be revised and re-derived. The retention half of this — keeping that record in one durable place that outlives the transient workspace — is defined in Section 13 (the archival package).

The phase specs implement this via calibration Sections 9 and 20 (authored, preserved decision fields) and the journal/fingerprint discipline of prep Section 14.3 and calibration Sections 4–6 and 29. This section is the single statement of the principle they share.

---

## 13. Archival package: the permanent record that outlives the workspace

The decision artifacts drive a run, but their value is also long-term: they are the record of *what was done to this archive and why*. The workspace, however, is transient (Section 10) — it is merged into the permanent library and then torn down or reused. So authored decisions (Section 12) are only truly "saved for the future" if they are **preserved beyond the workspace**, consolidated in one known place rather than scattered across per-file sidecars or — as with tools that mutate and forget — left unrecorded.

This section defines the **archival package**: a single, portable bundle that is the complete, durable record of one dump's journey from ingestion to successful calibration. It is what the user keeps when the workspace goes away.

### 13.1 When it is produced

The package is produced by an **explicit finalize/archive command**, not automatically at the end of each calibrate. Because calibration is freely re-runnable (Section 10.1) — the user may calibrate, add a dump, and calibrate again — "this dump is done" is a human judgement, so package assembly is a deliberate, separate step the user invokes when finished with a workspace. The command runs under the same workspace lock as every other operation (Section 2) and is non-destructive: it reads and bundles, it does not mutate the workspace or the library.

### 13.2 Contents

The archival package contains:

1. **The workspace configuration** — `photos-00-config.json`, the pinned config that governed all processing in this workspace (Section 4).
2. **All current decision/plan JSON artifacts** — the prep handoff (`photos-11-handoff.json`) and the numbered calibration artifacts `photos-21-time-decisions.json`, `photos-22-gps-decisions.json`, `photos-23-executable-plan.json`, and `photos-24-execution-summary.json`, exactly as written (same bytes the pipeline validated against, Section 12 part 2).
3. **The SQLite database** — see Section 13.4: the DB is part of the durable record, not throwaway scratch, and is archived with the artifacts.
4. **The full transformation log** — `photos-25-complete-log.json`, a newly generated, consolidated per-photo record (Section 13.3) of every transformation each by-dest photo underwent between being dumped into the workspace and the moment calibration ended successfully.

The package is self-describing: it should record the workspace identity, the plan/execution ids it corresponds to, and a manifest of its own contents with their SHA-256s, so its integrity is verifiable later.

### 13.3 The transformation log (`photos-25-complete-log.json`)

The transformation log, `photos-25-complete-log.json`, answers, for any photo, "what happened to this file and why?" — in one place, after the fact. It is a **derived, consolidated view** stitched from records that already exist: prep's execution journal and handoff, calibration's decision artifacts and execution journal. It does not introduce new authority; it fuses the two phases' existing records into a per-photo story.

Requirements:

1. **Spans both phases.** Each entry covers the whole journey — prep actions (extension normalization, move into by-date, content de-duplication / quarantine, provisional rename) and calibration actions (camera-group clock offset applied, resolved UTC, destination timezone decision, GPS placement and method, final destination-local rename).
2. **Keyed by content hash.** The content hash is the identity spine: it survives every rename and move, so each photo's entry is keyed by its hash and carries the ordered chain of names/locations it passed through. Names alone cannot key the log because a file is renamed up to twice (provisional, then final).
3. **Decision provenance per change.** Where a transformation followed from an authored decision (a timezone choice, an accepted clock offset, a manual GPS entry), the entry references that decision so the *why* is attached to the *what* (Section 12 part 2).
4. **Records GPS reverts and pre-state.** Where a manual GPS override was applied, changed, or **withdrawn**, the entry records the action and — for an applied or reverted override — the pinned pre-state it captured or restored (previous coordinates, or "absent"), per calibration Section 24.1, so the reversal is as traceable as the application.
5. **Human-readable JSON.** The log is JSON — pretty-printed, stably ordered, and keyed/labelled so a human can open it and read each photo's history directly. It is not a separate rendered report; the JSON itself is the readable artifact. Field names are descriptive, values are human-legible (ISO timestamps, IANA timezones, human-facing offset descriptions), and entries are ordered deterministically.
6. **Generated at finalize.** It is produced by the finalize/archive command (Section 13.1) from the then-current journals and artifacts, reflecting the state at successful end of calibration.

### 13.3a History retention (what must survive across runs)

The transformation log must cover the whole journey from a file's first ingestion to the successful end of calibration — but that journey usually spans **many runs** of both phases (prep, re-prep after moves, repeated calibration passes). So the records the log is built from must be **retained across runs in enough detail to reconstruct each photo's per-file history**; they must not be overwritten such that only the last run's actions survive.

This is a retention requirement, not a prescription of format. Concretely:

1. Per-run journals are not discarded or truncated to a single run: either journals accumulate (e.g. one `journal-<run>.json` per run, all retained until finalize) or an equivalent durable per-file history is maintained in `photos-00-ingest.db`. The choice is an implementation detail; what is required is that finalize can recover, for every by-dest photo, the ordered set of transformations it underwent and the decisions/inputs behind them.
2. The minimum that must be recoverable per file: the prep actions (normalization, organization, dedup/quarantine, provisional naming), the move into by-dest, and the calibration actions (clock offset, resolved UTC, timezone, GPS placement and method, any manual-GPS apply/change/revert with pre-state, final naming) — each attributable to the run and decision that caused it.
3. Anything beyond that minimum may be pruned. Retention exists to serve the log (and resume/auditing); it is not an open-ended event store.

Finalize fails (or warns and produces a clearly-partial log) if the retained history is insufficient to reconstruct the journey — it must not silently emit a log that looks complete but only reflects the last run.

Illustrative per-photo shape (not normative):

```json
{
  "content_sha256": "…",
  "final_path": "5-photos-by-dest/Belgium/Brussels/2024-07-03--14-12-21.arw",
  "camera_group": "sony_a6400_serial_123456",
  "journey": [
    { "phase": "prep", "action": "extension_normalized", "from": "DSC01234.ARW", "to": "dsc01234.arw" },
    { "phase": "prep", "action": "moved_to_by_date", "to": "4-photos-by-date/2024/2024-07-03/…" },
    { "phase": "prep", "action": "provisional_rename", "to": "2024-07-03--14-12-08.arw" },
    { "phase": "user", "action": "moved_to_by_dest", "to": "5-photos-by-dest/Belgium/Brussels/…" },
    { "phase": "calibrate", "action": "clock_offset_applied",
      "offset_seconds": -71987, "because": "camera_group_time_decisions.sony_a6400_serial_123456 (accepted anchor anchor-001)" },
    { "phase": "calibrate", "action": "resolved_utc", "value": "2024-07-03T12:12:21Z" },
    { "phase": "calibrate", "action": "timezone_resolved",
      "value": "Europe/Brussels", "because": "destinations.Belgium/Brussels.user_decision" },
    { "phase": "calibrate", "action": "gps_written",
      "lat": 50.8467, "lon": 4.3525, "method": "gpx_segment_interpolation", "gps_processing_method": "…" },
    { "phase": "calibrate", "action": "final_rename", "to": "2024-07-03--14-12-21.arw" }
  ]
}
```

### 13.4 SQLite is a durable artifact, not scratch

The SQLite database holds content-hash and metadata identity, move-aware carry-forward history, the **manual-GPS pre-state ledger** (calibration Section 24.1, the pinned originals that make manual GPS overrides reversible), and the cache that makes idempotency cheap. It is part of the durable record of what the pipeline knows about the archive, so:

1. it is archived as part of the package (Section 13.2 item 3), alongside the JSON artifacts, not discarded with the transient workspace;
2. conceptually it belongs with the artifacts in the control directory `.photos-ingest/` rather than being treated as throwaway scratch elsewhere;
3. prep is the sole writer of the cache/identity content through its controlled single-writer path (prep Section 14.3); calibration is the writer of the GPS pre-state ledger (it captures pre-state when it applies a manual GPS override, per calibration Section 24.1); finalize only reads and bundles the database.

This reframes the DB from "cache that happens to persist" to "an archived artifact that also serves as cache." Prep `10_photos-1-prep-workflow.md` (which owns the cache/identity content) and the control directory (Section 5) treat it accordingly.
