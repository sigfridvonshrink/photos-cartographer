# Time/GPS Calibration Workflow Specification

## 1. Purpose

This document defines the high-level workflow for the time/GPS calibration phase that follows `photos-1-prep`.

The calibration phase exists to:

1. validate that prep has produced a current by-dest working set;
2. operate only on files under `5-photos-by-dest`;
3. require `4-photos-by-date` to contain no photos before calibration can proceed;
4. require that destination development (the jpg/tif breakout) has not yet started;
5. ensure every file can be resolved to real UTC;
6. persist resolved UTC for every file in SQLite;
7. plan GPS decisions only after time is solved;
8. plan timestamp-based no-clobber renames using destination-local civil time;
9. produce numbered JSON decision artifacts at formal decision stages;
10. execute only a complete, dependency-validated executable plan.

This is a workflow specification, not a script implementation specification.

Cross-phase facts shared with prep — the workspace lock, the pre-mutation snapshot (`zfs`) mechanism, the shared configuration object, the workspace control directory, the camera-group identity key, the filename timestamp format, the GPX root, and the end-to-end operator loop — are defined in `10_photos-shared-contract.md` and are authoritative there. This document references that contract rather than restating it.

---

## 2. Core workflow rule

The workflow is ordered as:

```text
Time first.
GPS second.
Rename/metadata execution last.
```

GPS planning must not begin until every file has valid resolved UTC.

Execution must not recalculate decisions. Execution only validates and applies decisions already recorded in the executable plan.

If an executable plan says GPS metadata, time metadata, markers, or filenames need to change, execution applies those planned changes after dependency validation.

### 2.1 The workflow is a convergent rerun loop, not a single pass

Calibration is not a one-shot batch. The normal operation mode is:

```text
run -> inspect textual output / blockers
    -> edit the human-decision fields in the numbered JSON artifacts
    -> rerun
    -> machine proposals recomputed, user decisions preserved (Section 9)
    -> downstream artifacts recomputed where upstream changed (Section 30)
    -> repeat until photos-23-executable-plan.json is ready
    -> execute
```

Each rerun is idempotent for unchanged inputs (Section 30) and preserves prior user decisions whose logical target is unchanged (Sections 9, 21, 24). The ordered list in Section 34 describes one pass through this loop, not a workflow that runs exactly once.

Calibration is also re-runnable *after* a successful execute — it is not a terminal, run-once phase. Media added later is absorbed by re-running prep (to recognize it) and then calibration, bounded only by calibration's gating preconditions and the rule that development must not have started. The authoritative cross-phase account of this — including why already-processed files are no-ops on rerun and when a rerun legitimately re-enters the decision loop — is in the shared contract (`10_photos-shared-contract.md` Section 10).

---

## 3. Artifact dependency rule

Every durable artifact follows the same dependency rule:

```text
validate upstream -> create artifact -> record dependencies in it -> reject downstream use if dependencies changed
```

No artifact may be created from stale upstream inputs.

No downstream artifact may be used if any upstream input or artifact recorded in its dependency block has changed.

Dependencies must be explicit, flattened, and directly verifiable.

---

## 4. JSON artifact dependency representation

If an artifact depends on another JSON artifact, the dependency must name that JSON file and store the SHA-256 hash of the exact file bytes.

Example dependency entry:

```json
{
  "dependency_type": "json_artifact",
  "artifact_name": "photos-21-time-decisions.json",
  "artifact_path": ".photos-ingest/photos-21-time-decisions.json",
  "sha256": "..."
}
```

Before an artifact is used, each named JSON artifact dependency must be re-read and re-hashed using Python SHA-256 functions. The computed hash must match the recorded hash.

The workflow must not rely only on:

1. file mtime;
2. file size;
3. cached metadata;
4. recursive dependency blocks;
5. previous validation results.

The rule is:

```text
If artifact B depends on artifact A,
artifact B must name artifact A and store A's SHA-256 hash.
Before B is used, A must be re-hashed from file bytes and compared.
```

This applies to every JSON artifact in the calibration dependency graph, including the upstream prep handoff that calibration consumes:

```text
photos-11-handoff.json   (upstream input, produced by prep)
photos-21-time-decisions.json
photos-22-gps-decisions.json
photos-23-executable-plan.json
photos-24-execution-summary.json
```

`photos-11-handoff.json` is the contract calibration receives from prep (prep `10_photos-1-prep-workflow.md` Section 16). It is a deterministic JSON file, so it is treated as a first-class hashed dependency exactly like the numbered artifacts: wherever calibration depends on it, the dependency entry names the file and stores its SHA-256, and the file is re-hashed from its exact bytes before use. There is no separate, weaker "handoff fingerprint" path — the handoff is verified by byte-hash like every other JSON dependency, closing what would otherwise be the one exception to this rule. (Prep separates run-metadata timestamps from its internal fingerprints when *building* the handoff, per Section 16; calibration nonetheless hashes the whole file as written, since it depends on the exact bytes prep produced for that run.)

`photos-24-execution-summary.json` is the terminal artifact. It records the SHA-256 of the JSON artifacts it summarizes (which is why it appears in the list above), but nothing downstream depends on it, so it is never itself re-hashed as an upstream dependency.

---

## 5. Linear dependency inclusion

Dependencies must be included linearly.

A downstream artifact must not depend only on the immediately previous artifact and assume that previous artifact’s recursive dependency block is enough.

Each downstream artifact must include the full flattened dependency set it relies on.

For example, `photos-23-executable-plan.json` must directly include dependencies for:

1. `photos-21-time-decisions.json` and its SHA-256;
2. `photos-22-gps-decisions.json` and its SHA-256;
3. resolved UTC cache fingerprint;
4. `photos-11-handoff.json` and its SHA-256 (re-hashed from file bytes like any JSON dependency, Section 4);
5. prep SQLite cache fingerprint;
6. config fingerprint;
7. camera group/config classification fingerprint;
8. GPX folder/file fingerprint, if relevant;
9. metadata field-set version;
10. media file preconditions;
11. filename-format config fingerprint;
12. planned operation fingerprint.

It must not merely say:

```text
depends on photos-22-gps-decisions.json
```

and rely on `photos-22-gps-decisions.json` to prove all earlier dependencies recursively.

The flattened dependency model makes validation simple, auditable, and resistant to stale partial chains.

---

## 6. Dependency verification rule

Before creating or using any downstream artifact, the workflow must validate every dependency listed in that artifact’s dependency block.

Validation includes:

1. re-hashing named JSON artifacts from file bytes using SHA-256 (including the upstream `photos-11-handoff.json`, Section 4);
2. recomputing config fingerprints from the active config;
3. recomputing GPX folder/file fingerprints where relevant;
4. validating SQLite cache fingerprints or cache-generation markers;
5. validating resolved UTC cache fingerprints;
6. checking media file size/mtime/hash preconditions;
7. checking metadata field-set/extractor versions;
8. checking filename-format config fingerprint.

If any dependency does not match, the artifact is stale and must not be used.

Execution must not proceed from stale dependency state.

---

## 7. Calibration scope

Calibration operates only on files under:

```text
5-photos-by-dest/
```

The workflow must not calibrate files still in:

```text
0-source/
1-missing-metadata/
2-redundant-jpgs/
3-videos-by-date/
4-photos-by-date/
```

These folders are not calibration's concern. Residual content left in `0-source` (including `other`-class non-media files prep does not organize), `1-missing-metadata`, `2-redundant-jpgs`, or `3-videos-by-date` is expected and **does not block** calibration. Only `4-photos-by-date` is gated (below), because a non-empty `4-photos-by-date` means the user has not finished placing photos into by-dest.

Before calibration may proceed, the workflow must verify that:

```text
4-photos-by-date/
```

contains no photos.

If `4-photos-by-date/` still contains photos, calibration must block before creating any calibration JSON artifact.

The reason is to push the user to complete prep and place the current batch of files into `5-photos-by-dest` before calibrating that batch. This is a per-run gate, not a once-ever deadline: more files can be added and calibrated in a later cycle (shared contract `10_photos-shared-contract.md` Section 10), but each calibration run requires `4-photos-by-date` to be empty at the time it runs.

The workflow may print a textual message such as:

```text
Calibration cannot proceed.

Reason:
4-photos-by-date still contains photos.

Calibration only operates on 5-photos-by-dest.
Move/place remaining by-date files into by-dest through the prep workflow before calibrating.

No calibration JSON was written.
```

### 7.1 Development must not have started

Breaking a destination's media out into format-specific subfolders (by default `jpg/` and `tif/`, configurable via a `destination_distribution_subfolders` config key) belongs to a *later* development/processing phase that runs only after time and GPS are fixed. Development depends on the corrected timestamps, GPS, and filenames that calibration produces, so it must not run first.

Therefore, before calibration may proceed, the workflow must verify that no such distribution subfolder exists anywhere under `5-photos-by-dest`. The check is strict: the mere existence of a folder whose name matches `destination_distribution_subfolders` triggers the hard-stop, **even if that folder is empty**. The workflow must not attempt to decide whether the folder "really" holds development output — presence alone is the signal. On detecting one, the workflow must hard-stop before creating any calibration JSON artifact: it means development has already begun and would be invalidated by the time/GPS corrections calibration is about to plan.

The workflow may print a textual message such as:

```text
Calibration cannot proceed.

Reason:
A jpg/ or tif/ development subfolder was found under 5-photos-by-dest:
  5-photos-by-dest/2025/France/Paris/Louvre/jpg

This means photo development/processing has already started.
Time/GPS calibration must run BEFORE development, because it rewrites
timestamps, GPS, and filenames that development depends on.

Stop and roll back the development breakout (remove the jpg/tif subfolders
and restore the undistributed destination) before calibrating.

No calibration JSON was written.
```

### 7.2 By-dest must contain only photos

`5-photos-by-dest` is the user-curated **staging area** that calibration operates on: the user organizes a dump into destination folders here, calibration corrects time/GPS and finalizes names, and the result is then **merged into** the user's permanent library (e.g. digiKam) elsewhere. The workspace is not the library — it is transient working space for one or more dumps — but by-dest is structured to merge cleanly into the library, so it must contain **only photo files** (`image`/`raw` classes): the photos the user actively moved from by-date. It must not contain `other`-class non-media files, stray sidecars, notes, archives, or any non-media artifact — and it must not contain **videos** (Section 7.3); videos stay in `3-videos-by-date`.

Before calibration may proceed, the workflow must verify that under `5-photos-by-dest` (recursively) there is no `other`-class non-media file **and no `video`-class file** — only `image`/`raw` photo files are permitted. Media classes are the project's `image`/`raw`/`video` extensions; `other` is non-media, and `video` belongs in `3-videos-by-date`, not by-dest (Section 7.3). The pipeline's own control artifacts are not affected because they never live under `5-photos-by-dest` — the numbered calibration artifacts are written to `.photos-ingest/` (Section 8.1), and `gpx_root` resolves outside the managed tree (shared contract Section 8). If any non-photo file (non-media or video) is found under by-dest, calibration must hard-stop before creating any calibration JSON artifact and report the offending path(s); it does not silently ignore or skip the file, because its presence means by-dest is not the clean photo-only set that calibration and the later merge into the library assume.

The workflow may print a textual message such as:

```text
Calibration cannot proceed.

Reason:
A non-photo file was found under 5-photos-by-dest:
  5-photos-by-dest/Japan/Kyoto/notes.txt        (non-media)
  5-photos-by-dest/Japan/Kyoto/clip.mp4         (video — belongs in 3-videos-by-date)

5-photos-by-dest must contain only photo files moved in from by-date.
Remove or relocate non-photo files (and any videos) before calibrating.

No calibration JSON was written.
```

### 7.3 Videos are not calibrated, and must not be in by-dest

Calibration's target is **photos**. Videos are **semi-foreign** (prep `10_photos-1-prep-workflow.md` Section 2.4): prep date-organizes and naively renames them into `3-videos-by-date` and they **stay there** — they are never sorted into destinations. Videos must **never** appear in `4-photos-by-date` or `5-photos-by-dest`.

This is a hard invariant, not a preference. The by-dest verification that enforces it — rejecting both `other`-class non-media and `video`-class files so only `image`/`raw` photos remain — lives in Section 7.2; a video found under `5-photos-by-dest` is a calibration break there. Likewise, a video found in `4-photos-by-date` is a prep-side break (prep `10_photos-1-prep-workflow.md` Section 6.1).

Because videos never reach by-dest, calibration never plans or applies time/GPS metadata writes or renames for a video, never reasons about them in the camera-group/GPX/pre-state machinery, and they never appear in the per-destination artifacts. If a future need arises to calibrate video time/GPS, it is out of scope for this workflow as specified.

---

## 8. JSON artifact rule

The workflow distinguishes between:

```text
textual reports / terminal output
```

and:

```text
durable JSON artifacts
```

JSON artifacts must not be produced merely for preliminary reports, blocked preconditions, or suggested config snippets.

However, once the workflow reaches a formal decision stage, that stage must always produce its numbered JSON artifact, even if the artifact records that no user input or no metadata change is required.

The rule is:

```text
Before formal decision stage:
  use textual output only.

At formal decision stage:
  always create the numbered JSON artifact,
  even if the result is complete/no-op.

After artifact creation:
  record dependencies and require downstream validation.
```

The required numbered artifacts are:

```text
photos-21-time-decisions.json
photos-22-gps-decisions.json
photos-23-executable-plan.json
photos-24-execution-summary.json
```

The first durable calibration artifact is:

```text
photos-21-time-decisions.json
```

No earlier calibration JSON artifact should be produced.

### 8.1 Where calibration artifacts live

All numbered calibration artifacts are written to the workspace control directory used by prep, flat (no subdirectory):

```text
.photos-ingest/photos-21-time-decisions.json
.photos-ingest/photos-22-gps-decisions.json
.photos-ingest/photos-23-executable-plan.json
.photos-ingest/photos-24-execution-summary.json
```

They must never be written inside `5-photos-by-dest/` (or any scanned media folder), because that tree is read-only for prep and prep would otherwise inventory the artifacts as ordinary files and fold them into its cache fingerprint.

Placing the artifacts in `.photos-ingest/` is sufficient: prep skips that directory wholesale during its media scan (shared contract `10_photos-shared-contract.md` Section 5), so the artifacts are never inventoried or folded into prep's cache fingerprint. There is no per-file registry to maintain — keeping every control and artifact file inside `.photos-ingest/` is the whole mechanism.

---

## 9. Human decision field rule

This rule is the mechanism behind the pipeline's authored-decisions principle (shared contract `10_photos-shared-contract.md` Section 12): the tool never mutates autonomously — it proposes, the user disposes by filling decision fields, and the executor acts only on what the user wrote down. These fields are therefore the durable, traceable record of *why* every time/GPS/rename change happens, and editing them and re-running is how a decision is revised and re-derived.

Calibration JSON artifacts must be generated with all human-decision fields already present.

The user should never have to add object structure, brackets, keys, arrays, commas, or new decision sections manually. Human input should be limited to filling existing empty fields or changing explicit boolean/string decision values.

The general pattern is:

```text
machine proposals go in proposal/status fields
human decisions go in pre-created user_decision fields
effective values are derived during validation
```

When an artifact is generated, manual override fields must exist and be empty unless the user has already filled them in a previous version of the same logical section.

When an artifact is regenerated, existing user-filled decision fields must be preserved where the logical target is still the same, for example the same destination, camera group, file, or decision item.

Machine-generated proposal fields may be recalculated.

User decision fields must not be silently overwritten.

If a user decision can no longer be safely applied because its upstream context changed, the workflow should preserve the value but mark it stale or requiring review rather than deleting it.

This applies to:

1. destination timezone decisions;
2. camera-group time offset decisions;
3. GPX/native-GPS time-anchor acceptance;
4. manual time segment decisions;
5. destination/folder GPS fallback decisions;
6. file-level manual GPS overrides;
7. ambiguous GPX interpolation/extrapolation decisions;
8. any other human-reviewed decision.

### 9.1 Auto-resolution policy

A machine proposal may be *auto-resolved* (its `effective_*` value set without an explicit `user_decision`) only when the workspace config opts into it, and the governing flag depends on the proposal class:

1. Time-anchor proposals (Section 19) are governed by the existing flags in `camera_time_and_timezone_policy` (workspace config `photos-00-config.json`):

```text
single_anchor_auto_apply   (default false)
multi_anchor_auto_apply    (default true)
```

2. Other proposal classes (e.g. destination timezone) auto-resolve only if a corresponding policy flag is enabled. With no such flag, the default is conservative and the proposal keeps `requires_user_input: true`.

The default posture is therefore conservative. A single high-confidence time-anchor proposal with `single_anchor_auto_apply` false still sets `requires_user_input: true`; likewise the destination-timezone proposal in the Section 18 example keeps `requires_user_input: true` because no timezone auto-accept policy is enabled. When a policy flag enables auto-apply for a given class, the workflow may set the effective value directly and mark that section `requires_user_input: false` with `decision_mode: "auto_resolved"`.

This is what makes the no-op/`complete` artifact path of Sections 20.2 and 25.2 reachable: a `complete` artifact is produced only for sections that are either genuinely no-op or auto-resolved under an enabled policy flag. When auto-apply is disabled, every proposal requires confirmation and resolved UTC is not finalized until the user acts.

---

## 10. Per-destination structure

### 10.1 What a destination is

A *destination* is the folder that directly contains a logically distinct set of media files. At the calibration stage media has not yet been broken out into format-specific subfolders (those belong to a later development phase — see Section 7.1), so the destination is simply the folder a media file sits in.

1. A destination is NOT necessarily a leaf folder. A destination may itself contain nested destinations. Example: `.../Louvre` is a destination (it directly contains media), and `.../Louvre/Napoleon's Apartments` is a separate, distinct destination, even though it is nested inside Louvre.

2. The derivation rule for any media file is simply its immediate containing folder:

```text
destination = the folder that directly contains the file
```

A folder is a destination if it directly contains media; nested folders that directly contain media are their own destinations.

This matches prep's handoff `destination_folders` grouping (immediate parent, `os.path.dirname`), which is correct precisely *because* the format-distribution subfolders (jpg/tif) must not exist yet. Their presence is a hard-stop blocker, not a grouping case to collapse (Section 7.1).

All numbered calibration JSON artifacts must cover destinations separately.

This applies to:

```text
photos-21-time-decisions.json
photos-22-gps-decisions.json
photos-23-executable-plan.json
```

Each artifact should be grouped by destination under `5-photos-by-dest`.

A global summary section may exist, but decisions must be inspectable per destination.

### 10.2 Destination-scoped vs. camera-group-scoped decisions

Grouping by destination is the default, but not every decision is destination-scoped. Two scopes coexist:

1. **Destination-scoped decisions** belong to a folder: the destination civil timezone (Section 18), folder/destination GPS fallback, and anything else that is a property of *where* files sit. These live inside the per-destination sections.
2. **Camera-group-scoped decisions** belong to a *camera*, not a folder: a camera clock offset / time-anchor calibration (Section 19) is a property of the device's clock and applies to every file from that group regardless of which destination it landed in. A single camera group can appear in multiple destinations (Section 16), so representing its offset separately inside each destination section would duplicate one logical decision and invite inconsistent edits.

Therefore camera-group time calibration is represented **once, at group scope**, in a top-level section of `photos-21-time-decisions.json` keyed by `camera_group_key`:

```json
{
  "artifact_type": "time_decisions",
  "camera_group_time_decisions": {
    "sony_a6400_serial_123456": {
      "camera_group": "sony_a6400_serial_123456",
      "destinations_present": [
        "5-photos-by-dest/Belgium/Brussels",
        "5-photos-by-dest/Japan/Kyoto"
      ],
      "proposal": { "...": "..." },
      "user_decision": { "...": "..." },
      "effective_time_anchor": "",
      "requires_user_input": true
    }
  },
  "destinations": {
    "5-photos-by-dest/Belgium/Brussels": {
      "camera_groups_present": ["sony_a6400_serial_123456"],
      "...": "..."
    }
  }
}
```

The rules are:

1. there is exactly **one** editable decision per camera group, in `camera_group_time_decisions`; the user fills it once and it applies to every destination the group touches;
2. each per-destination section **references** the group key(s) present (e.g. `camera_groups_present`) but does **not** carry its own editable copy of the group's offset decision. It may surface the group decision's *effect* read-only for inspection, but the editable field exists only at group scope;
3. there is no "accepted in one destination, not another" state to reconcile, because the decision exists in only one place. The group offset is either decided or not, uniformly across its destinations;
4. `destinations_present` records every destination the group appears in, so the cross-destination span of a group-scoped decision is explicit and auditable;
5. resolved UTC for a file uses its camera group's effective time anchor (group scope) together with its destination's effective timezone (destination scope). A file is fully solvable only when **both** the group-scoped time decision and its destination-scoped timezone are complete.

All other artifacts remain destination-grouped as before; this group-scoped section is specific to camera-group time calibration in `photos-21-time-decisions.json`.

### 10.3 Per-destination grouping (default)

Except for the camera-group-scoped time decisions of Section 10.2, all numbered calibration JSON artifacts cover destinations separately.

This applies to:

```text
photos-21-time-decisions.json   (destination sections + the group-scoped block)
photos-22-gps-decisions.json
photos-23-executable-plan.json
```

Each artifact should be grouped by destination under `5-photos-by-dest`.

Example shape:

```json
{
  "artifact_type": "time_decisions",
  "artifact_name": "photos-21-time-decisions.json",
  "camera_group_time_decisions": {
    "sony_a6400_serial_123456": { "...": "see Section 10.2" }
  },
  "destinations": {
    "5-photos-by-dest/Belgium/Brussels": {
      "destination_id": "...",
      "destination_path": "5-photos-by-dest/Belgium/Brussels",
      "camera_groups_present": ["sony_a6400_serial_123456"],
      "status": "...",
      "depends_on": {}
    },
    "5-photos-by-dest/Japan/Kyoto": {
      "destination_id": "...",
      "destination_path": "5-photos-by-dest/Japan/Kyoto",
      "camera_groups_present": ["sony_a6400_serial_123456"],
      "status": "...",
      "depends_on": {}
    }
  }
}
```

---

## 11. High-level artifact cascade

The calibration workflow follows this cascade:

```text
calibration invocation
  -> prep/by-dest staleness validation
  -> in-memory by-dest file objects
  -> GPX folder parsing/fingerprinting
  -> camera group recognition/classification
  -> textual config snippets if unknown groups exist
  -> time-decision stage
  -> photos-21-time-decisions.json
  -> resolved UTC per file in SQLite
  -> GPS-decision stage
  -> photos-22-gps-decisions.json
  -> photos-23-executable-plan.json
  -> metadata/rename execution
  -> updated SQLite/cache/journal
  -> photos-24-execution-summary.json
```

If any upstream dependency changes, all downstream artifacts that depend on it become stale.

---

## 12. Workflow states

The workflow should be understood as a state machine:

```text
STATE 1 — calibration invoked
STATE 2 — prep/by-dest preflight passed
STATE 3 — GPX indexed/fingerprinted
STATE 4 — camera groups classified or blocked
STATE 5 — time-decision stage reached
STATE 6 — photos-21-time-decisions.json created
STATE 7 — resolved UTC persisted
STATE 8 — GPS-decision stage reached
STATE 9 — photos-22-gps-decisions.json created
STATE 10 — photos-23-executable-plan.json ready
STATE 11 — executed
STATE 12 — photos-24-execution-summary.json created
```

A calibration JSON file existing on disk does not automatically mean execution is allowed.

Execution is allowed only after `photos-23-executable-plan.json` exists, is current, and validates all upstream dependencies.

---

## 13. Stage 1 — Invoke calibration and validate prep state

Calibration may be invoked without assuming upstream prep artifacts are valid.

The workspace lock is acquired at process startup, before preflight (shared contract `10_photos-shared-contract.md` Section 2); if another pipeline run holds it, calibration exits fail-fast without scanning, planning, or writing anything. Otherwise, the first workflow action is always preflight validation.

The workflow must:

1. load the available `photos-1-prep` handoff and SQLite cache state;
2. verify that `4-photos-by-date/` contains no photos;
3. verify that no `destination_distribution_subfolders` (jpg/tif) exist under `5-photos-by-dest` and hard-stop if development has started (Section 7.1);
4. verify that `5-photos-by-dest` contains only photo files and hard-stop on any non-photo file — `other`-class non-media or `video`-class — found under it (Sections 7.2, 7.3);
5. identify files under `5-photos-by-dest`;
6. detect by-dest media not yet recorded by prep (and/or handoff by-date files now missing) and hard-stop with the targeted "re-run prep" blocker if found (Section 13.1);
7. validate whether the prep/cache state for by-dest files is current;
8. block before producing calibration JSON artifacts if the prep/cache state is stale, missing, incomplete, or unverifiable.

The workflow must validate that:

1. the workspace config `photos-00-config.json` exists and is read as the authoritative configuration (seeded by prep; shared contract `10_photos-shared-contract.md` Section 4), with its field-scoped fingerprints used for staleness and its whole-file SHA-256 available for provenance;
2. the prep handoff exists and re-hashes to the SHA-256 recorded wherever it is depended upon (Section 4);
3. SQLite schema/cache versions are acceptable;
4. expected by-dest media files still exist;
5. size/mtime/hash preconditions are current;
6. the metadata field-set version is acceptable;
7. prep handoff dependencies are still current;
8. by-dest SQLite records are current.

If validation fails, the workflow prints a textual stale-state report and produces no JSON artifact.

Example:

```text
Calibration cannot proceed.
Reason: by-dest cache records are stale.
Next action: rerun photos-1-prep for cache refresh / prep completion.
No calibration JSON was written.
```

### 13.1 Calibration requires a prep run after the latest by-date → by-dest move

Prep recognizes a user's by-date → by-dest move and folds it into the handoff/cache only on its *next run* (prep `10_photos-1-prep-workflow.md` Section 10.1). Calibration consumes the handoff and operates on by-dest. Therefore:

**A prep run must occur after the most recent by-date → by-dest move, before calibration runs.** This is a hard contract requirement, not merely advisory. The intended sequence is *move → re-run prep (move recognition) → calibrate* (shared contract `10_photos-shared-contract.md` Section 10). A handoff that predates the latest move does not describe the by-dest set calibration sees, so calibrating against it is unsafe.

This requirement is largely self-enforcing through the validations above: a stale handoff fails the SHA-256/cache checks, and moved files break the "expected by-dest media files still exist" and "by-dest SQLite records are current" checks. But calibration must detect this specific situation and report it **as a targeted, actionable blocker** rather than as a generic hash mismatch or opaque stale-cache message, because the precise fix (re-run prep) differs from other staleness causes.

Detection (cache/handoff vs. filesystem, `stat`-level, no media re-read):

1. one or more media files exist under `5-photos-by-dest` that the handoff/cache does not record at their current by-dest path (unrecorded by-dest media); and/or
2. one or more photos the handoff records under `4-photos-by-date` are now missing from there (consistent with having been moved into by-dest). (Videos in `3-videos-by-date` are not part of this check — they are never moved into by-dest, Section 7.3.)

When either condition holds, calibration hard-stops before creating any calibration JSON artifact and emits the targeted blocker:

```text
Calibration cannot proceed.

Reason:
5-photos-by-dest contains photos that prep has not yet recorded
(the handoff predates your most recent move from by-date into by-dest).

Next action:
Re-run photos-1-prep. It will recognize the moved files (no re-hash,
no re-read) and refresh the handoff/cache, then calibration can proceed.

No calibration JSON was written.
```

Calibration never performs the move recognition itself and never writes to the cache, handoff, or by-dest to "fix" this — recognizing moves and refreshing the handoff is prep's responsibility alone (prep Section 10.1). Calibration's only action is to detect the gap and direct the user to re-run prep.

---

## 14. Stage 2 — Create in-memory by-dest file objects

After preflight passes, the workflow creates in-memory file objects for files under `5-photos-by-dest` only.

Each file object should represent facts such as:

1. workspace-relative path;
2. destination path;
3. file size;
4. mtime;
5. content hash, if available;
6. media type;
7. camera identity fields;
8. raw timestamp fields;
9. native GPS fields;
10. metadata field-set version;
11. current folder class;
12. prep handoff/cache provenance;
13. planned filename (mutable field used for lookahead name de-collisioning).

These objects are the planning basis for all later stages.

---

## 15. Stage 3 — Load, parse, and fingerprint GPX folder

GPX folder scanning, parsing, and fingerprinting must happen before the time-decision stage.

This is required because GPX data may be used in two distinct ways:

1. upstream, as evidence for GPX/native-GPS time-anchor proposals;
2. downstream, for GPS interpolation/extrapolation after time is solved.

The workflow must record:

1. GPX root path;
2. GPX files considered;
3. GPX file size/mtime/hash or equivalent fingerprint;
4. parsed GPX time ranges;
5. GPX policy/config fingerprint;
6. whether GPX was available, disabled, missing, or unusable.

If GPX is unavailable or disabled, later artifacts should record that no GPX evidence was used.

If GPX is used for time-anchor proposals, the GPX fingerprint becomes an upstream dependency of `photos-21-time-decisions.json`.

If GPX is used for GPS interpolation/extrapolation, the GPX fingerprint becomes an upstream dependency of `photos-22-gps-decisions.json` and `photos-23-executable-plan.json`.

---

## 16. Stage 4 — Camera group recognition and classification

The workflow groups by-dest media by camera/device identity using SQLite metadata and the workspace config.

For each group, the workflow determines:

1. camera group key;
2. device identity fields used;
3. number of files;
4. destinations in which the group appears;
5. earliest/latest source-naive timestamp;
6. whether the group is known;
7. whether the group is classified as mobile or fixed-clock camera;
8. whether the group has native GPS on some/all files;
9. whether the group has missing or ambiguous timestamp metadata.

If unknown camera groups are found, the workflow should output directly pasteable config snippets (for the workspace config `photos-00-config.json`) as textual output.

If camera group classification is incomplete:

1. do not create `photos-21-time-decisions.json`;
2. print textual config snippets;
3. stop and require the user to update the workspace config;
4. require the workflow to be rerun.

Unknown camera group snippets are not JSON artifacts.

Camera-group identity reuses prep's grouping rather than reinventing it: prep already computes a `camera_group_key` (at `CAMERA_GROUP_KEY_VERSION`) from serial/make/model/owner fields and emits it in both the handoff and SQLite. Mobile vs fixed-clock classification reuses the existing config in `camera_time_and_timezone_policy.device_groups` (workspace config `photos-00-config.json`), where `phones` denotes mobile and `fixed_clock_cameras` denotes fixed-clock. A group is "known" when its key is listed under one of those classes; unknown groups are exactly what the pasteable config snippets ask the user to classify.

---

## 17. Stage 5 — Determine per-destination time requirements

Once camera groups are known and classified, the workflow determines whether every media item can be mapped from source media time to real UTC.

This analysis must be grouped by destination.

For each destination, the workflow determines:

1. destination path;
2. destination civil timezone proposal/status;
3. camera groups present;
4. source-naive timestamp range;
5. whether each file can be mapped to real UTC;
6. which camera groups need manual time decisions;
7. whether GPX/native-GPS time-anchor proposals are available;
8. whether blockers remain.

For each camera group, the workflow determines whether time can be solved from:

1. trustworthy native UTC timestamps;
2. mobile-device timestamps with reliable timezone/offset metadata;
3. existing user calibration rules;
4. manual fixed UTC offset;
5. manual time segments;
6. GPX/native-GPS time-anchor proposals;
7. other explicitly supported calibration evidence.

Once this analysis is complete, the workflow has reached the formal time-decision stage.

At that point, it must create:

```text
photos-21-time-decisions.json
```

even if no user input is required.

---

## 18. Destination civil timezone decision

`photos-21-time-decisions.json` must settle the civil timezone for every destination under `5-photos-by-dest`.

The destination civil timezone is used to:

1. interpret local/civil destination context;
2. convert resolved UTC to destination-local civil time;
3. plan timestamp-based no-clobber renames;
4. produce filename timestamp components.

The artifact must include, for each destination, pre-created human decision fields.

Example shape:

```json
{
  "destination_path": "5-photos-by-dest/Belgium/Brussels",
  "destination_timezone": {
    "proposed_iana_timezone": "Europe/Brussels",
    "proposal_source": "config_or_native_gps_or_gpx",
    "proposal_confidence": "high",
    "user_decision": {
      "manual_iana_timezone": "",
      "accept_proposed_timezone": false
    },
    "effective_iana_timezone": "",
    "requires_user_input": true,
    "stale_user_decision": false
  }
}
```

The user may accept the proposal by changing:

```json
"user_decision": {
  "manual_iana_timezone": "",
  "accept_proposed_timezone": true
}
```

Or override it by filling:

```json
"user_decision": {
  "manual_iana_timezone": "Europe/Paris",
  "accept_proposed_timezone": false
}
```

The workflow derives `effective_iana_timezone` during validation.

The user should not directly edit machine proposal fields or generated effective fields.

If destination timezone is unknown or ambiguous, the artifact must contain an empty manual override field and mark the destination as requiring user input.

Resolved UTC must not be finalized for files in a destination whose timezone/time dependencies are incomplete.

### 18.1 Re-evaluation when a file is moved between destinations

A file's destination is an input to its time decision: the destination civil timezone above, and downstream the resolved UTC and the local-time rename. If the user re-sorts a file from one destination to another inside `5-photos-by-dest` (e.g. fixing a mis-sort), prep recognizes the move and updates the handoff to record the new destination (prep `10_photos-1-prep-workflow.md` Section 10.2). On the next calibration run this changes the handoff, which — through the dependency cascade (Section 30; shared contract Section 9) — restales the affected destination's per-file decisions for that file, so calibration **re-evaluates** it under its **new** destination: it applies the new destination's effective timezone, recomputes resolved UTC and the local-time rename accordingly, and never silently carries the old destination's timezone onto a file that now lives elsewhere.

Decisions that are genuinely destination-scoped (the timezone of each destination) are unaffected for files that did not move; only the moved file is re-evaluated, and only against its new destination. As always, the mandatory re-prep after the move applies (shared contract Section 10) so calibration sees the move at all.

---

## 19. GPX/native-GPS time-anchor proposals

This stage is part of time calibration, not GPS interpolation.

It is used when:

1. GPX data is available;
2. a camera group has at least one file with native GPS;
3. that native GPS position matches a GPX point or a short GPX segment under configured thresholds.

The purpose is to propose a real UTC timestamp for a photo whose camera clock may be wrong.

This can produce a proposed camera-time calibration for the whole camera group. Because the offset is a property of the camera's clock and not of any one folder, the resulting decision is **camera-group-scoped**: it is recorded once in the `camera_group_time_decisions` block keyed by `camera_group_key` (Section 10.2), not duplicated into each destination the group appears in. The user accepts or overrides it once, and it applies uniformly to every file from that group across all its destinations.

### 19.1 Matching cases

A native-GPS photo may produce a time-anchor proposal if either:

1. its native GPS position is close enough to a GPX point with a known timestamp; or
2. its native GPS position lies close enough to a GPX segment between two GPX points that are close enough in time.

The relevant thresholds must be defined in the workspace config, for example:

1. maximum distance to GPX point;
2. maximum distance to GPX segment;
3. maximum duration between the two GPX points forming a segment;
4. maximum segment length;
5. ambiguity policy when multiple possible GPX matches exist;
6. minimum evidence required for auto-proposal;
7. maximum allowed offset spread between supporting anchors.

These thresholds are config-driven and several already have homes in the workspace config `photos-00-config.json`, for example `gpx_direct_match_max_seconds` (point match), `gpx_interpolation_max_gap_seconds` and `gpx_interpolation_max_distance_meters` (segment match), and `gpx_root` for the GPX folder. The list above is the conceptual set; the concrete keys live in config and participate in dependency fingerprints.

### 19.2 Ranking, not averaging

If multiple native-GPS/GPX time-anchor candidates exist for the same camera group, the workflow must not average them.

Instead, it should:

1. collect candidate anchors;
2. rank them by precision and confidence;
3. select the best candidate as the recommended calibration proposal;
4. use other candidates only as supporting or conflicting evidence.

The best candidate is normally:

1. a near-perfect GPX point match; otherwise
2. the closest valid GPX point match; otherwise
3. the closest valid short-segment match.

Supporting candidates confirm that the selected offset is plausible.

Conflicting candidates trigger user review.

### 19.3 Human decision fields for time-anchor proposals

Each proposed anchor should include generated proposal fields and pre-created user decision fields.

Example shape:

```json
{
  "proposal_id": "anchor-001",
  "source_file": "5-photos-by-dest/Belgium/Brussels/DSC01234.ARW",
  "camera_group": "sony_a6400_serial_123456",
  "camera_source_naive_time": "2024:07:03 14:12:08",
  "native_gps": {
    "lat": 50.8467,
    "lon": 4.3525
  },
  "gpx_match": {
    "match_type": "gpx_segment_interpolation",
    "gpx_file": "tracks/brussels.gpx",
    "distance_to_segment_m": 8.4,
    "segment_duration_seconds": 30
  },
  "proposal": {
    "proposed_real_utc": "2024-07-03T12:12:21Z",
    "proposed_offset_seconds": -71987,
    "confidence": "review_required",
    "rank": "recommended"
  },
  "user_decision": {
    "accept_proposal": false,
    "manual_real_utc": "",
    "manual_offset_seconds": ""
  },
  "effective_time_anchor": "",
  "requires_user_input": true
}
```

The user fills existing fields only.

---

## 20. Create `photos-21-time-decisions.json`

Once the time-decision stage is reached, the workflow must create:

```text
photos-21-time-decisions.json
```

This artifact exists even if no user input is required.

It is grouped by destination, plus the top-level `camera_group_time_decisions` block holding camera-group-scoped decisions (Section 10.2).

### 20.1 If user time decisions are required

The artifact should indicate:

```json
{
  "artifact_type": "time_decisions",
  "artifact_name": "photos-21-time-decisions.json",
  "status": "requires_user_input",
  "requires_user_input": true,
  "executable": false
}
```

It should include only the sections needed to solve time, such as:

1. destination timezone decisions (per-destination scope);
2. camera groups requiring time calibration (group scope, in `camera_group_time_decisions`, Section 10.2);
3. GPX/native-GPS time-anchor proposals (group scope — the resulting decision is recorded against the camera group, Section 19);
4. manual fixed-offset fields (group scope);
5. manual segment templates (group scope);
6. explicit accept/reject fields for proposed time anchors (group scope);
7. blockers preventing resolved UTC computation.

The user should not have to create JSON structure manually. Required sections should already exist and be fillable.

### 20.2 If no user time decisions are required

The artifact should still be created and should indicate:

```json
{
  "artifact_type": "time_decisions",
  "artifact_name": "photos-21-time-decisions.json",
  "status": "complete",
  "requires_user_input": false,
  "executable": false,
  "decision_mode": "no_op_or_auto_resolved"
}
```

This no-op/complete artifact becomes part of the dependency cascade.

Downstream stages must depend on it and validate it.

---

## 21. Stage 6 — User completes or accepts time decisions

If `photos-21-time-decisions.json` requires user input, the user may resolve time calibration by:

1. accepting a proposed destination timezone;
2. entering a manual destination timezone;
3. accepting a GPX/native-GPS time-anchor proposal;
4. entering a manual fixed UTC offset;
5. filling manual time segments;
6. updating the workspace config with camera group classifications;
7. correcting or confirming other required time policy fields.

After edits, the workflow must validate `photos-21-time-decisions.json`.

If the workspace config changed, the time-decision artifact may become stale and must be regenerated or revalidated.

If camera group classification changed, time-calibration requirements must be recomputed and the time-decision artifact becomes stale.

User-filled fields should be preserved across regeneration where the logical target is still the same.

---

## 22. Stage 7 — Compute resolved UTC per file

Once time decisions are complete, the workflow computes resolved UTC for every media file.

The result should be persisted into SQLite as a derived calibration cache.

SQLite should contain per-file facts such as:

```text
file_id / workspace_path
destination_path
destination_timezone
camera_group
source_naive_time
source_time_provenance
time_rule_used
utc_offset_used
resolved_utc
resolved_utc_status
resolved_utc_provenance
config_fingerprint
camera_group_fingerprint
photos-21-time-decisions.json fingerprint
prep_cache_fingerprint
metadata_field_set_version
gpx_fingerprint if GPX-derived time anchors influenced time decisions
```

The resolved UTC cache is an artifact even though it is stored in SQLite rather than as a standalone JSON file.

It must be created only after validating all upstream dependencies, including `photos-21-time-decisions.json`.

If config, camera grouping, `photos-21-time-decisions.json`, prep cache, metadata field-set version, GPX dependency, or relevant source file facts change, resolved UTC becomes stale and must be recomputed.

### 22.1 Resolved-UTC cache fingerprint

Because the resolved-UTC cache lives in SQLite rather than as a hashable file, it must expose a deterministic fingerprint so downstream JSON artifacts can record and re-verify it the same way they re-hash JSON dependencies. The `resolved_utc_cache_fingerprint` must be a SHA-256 computed over a canonical, deterministically ordered serialization of:

1. every per-file resolved row (`file_id`/workspace path, `resolved_utc`, `resolved_utc_status`, `time_rule_used`, `utc_offset_used`, `source_time_provenance`);
2. the input fingerprints that produced those rows (config fingerprint, camera-group fingerprint, `photos-21-time-decisions.json` SHA-256, prep cache fingerprint, metadata field-set version, and GPX fingerprint where time anchors used GPX).

Rows must be ordered by workspace path and all values normalized to text before hashing, so the fingerprint is stable across runs with unchanged inputs. This `resolved_utc_cache_fingerprint` is the value referenced as the "resolved UTC cache fingerprint" dependency in Sections 5, 6, 24, and 28.

---

## 23. Stage 8 — GPS planning begins only after time is solved

GPS planning must not start until every file has valid resolved UTC.

The GPS planning stage consumes:

1. resolved UTC per file;
2. destination timezone per destination;
3. native GPS facts;
4. GPX folder/index/fingerprint;
5. manual GPS overrides;
6. folder fallback rules;
7. existing GPS markers;
8. device class: mobile or fixed-clock camera;
9. destination-folder context;
10. GPS policy config (workspace config).

The workflow then decides, for each file, whether to:

1. preserve native GPS;
2. use manual locked GPS;
3. use manual fallback GPS;
4. use GPX interpolation;
5. use GPX extrapolation;
6. block because no reliable GPS source exists;
7. skip because no GPS change is needed.

This stage is separate from GPX/native-GPS time-anchor proposals.

The earlier stage uses native GPS + GPX to infer time.

This stage uses solved time + GPX/manual/native data to plan GPS placement.

Once GPS decisions have been analysed, the workflow has reached the formal GPS-decision stage.

At this point, it must create:

```text
photos-22-gps-decisions.json
```

even if no GPS changes are required.

---

## 24. Automated GPS recalculation policy

Automated GPS decisions, including GPX interpolation and extrapolation, are ordinary derived decisions in the dependency cascade.

If any upstream dependency used by automated GPS planning changes, the affected GPS decision artifact becomes stale and must be regenerated before execution.

Relevant upstream dependencies include:

1. GPX folder/file fingerprints;
2. GPX parsing/config thresholds;
3. resolved UTC cache fingerprint;
4. destination grouping;
5. native GPS metadata facts;
6. manual GPS decision fields;
7. GPS policy config (workspace config).

There is no special forced recalculation mode.

The rule is:

```text
If GPS planning inputs changed, GPS decisions are stale.
If GPS decisions are stale, regenerate photos-22-gps-decisions.json.
If regenerated GPS decisions imply metadata changes, photos-23-executable-plan.json must include those changes.
If the executable plan includes GPS metadata writes, execution applies them after dependency validation.
```

The workflow must not preserve outdated automated GPS decisions merely to avoid touching media files.

Human-filled GPS decision fields should still be preserved across regeneration where the logical target is unchanged.

If a preserved human decision no longer safely applies, it must be marked stale or requiring review rather than silently used.

### 24.1 Reversible manual GPS overrides (pre-state ledger)

A **manual GPS override is reversible**: withdrawing it undoes its effect, and changing it re-applies cleanly. Automated GPS values are **not** rolled back — they are overwritten or recomputed (below). This reversibility is scoped **only to manual GPS**; time and filename are never undone (they position the file and are always recomputed, see the end of this section).

The mechanism is a **pre-state ledger** in SQLite, archived with the database (shared contract `10_photos-shared-contract.md` Section 13.4):

1. **Capture on first application.** The first time a manual GPS decision causes the executor to write GPS to a file, it captures that file's GPS EXIF *as it was immediately before the write* and pins it in the ledger, keyed by content hash. The captured pre-state is one of:
   - the **previous GPS coordinates** (and related GPS fields) that were present, or
   - an explicit **"absent" sentinel** meaning the file had no GPS before the override.
   This pinned value is the **true original**: it is written once and never overwritten by subsequent runs of the same or a changed decision, so it always represents the state before the pipeline first touched the file's GPS via a manual decision.

2. **Withdraw → restore.** If, before a later run, the user **removes** the manual GPS decision, the next run's plan must include an explicit **revert operation** that drives the field back to the pinned pre-state: write the previous coordinates back, or — if the pre-state was "absent" — **clear** the GPS the override added. Withdrawal therefore *undoes*; it does not merely stop re-asserting. ("Tag a file that had no GPS, then withdraw" correctly leaves the file with no GPS, not with the tagged value.)

3. **Change → overwrite, original stays pinned.** If the user **changes** the manual GPS to a new value, the executor overwrites to the new value; the pinned pre-state is unchanged, so a later full withdrawal still restores the true original.

4. **Once restored, the ledger entry is consumed.** After a withdrawal has restored the pre-state of a file that still exists, the override is gone and the file is back to original; a subsequent fresh manual decision on the same file pins the (now original) pre-state again on its first application. (This consume-on-restore applies only to files still present; an entry for a file that has disappeared is kept — item 5.)

5. **A disappeared file's entry is kept for reference.** If a file that has a pre-state ledger entry no longer exists at the next run (deleted, or removed from the workspace), prep/calibration must **not** prune its ledger entry. The pinned pre-state is retained as a historical record — it documents that the pipeline once overrode that file's GPS and what the original was — keyed by the content hash that identified it. A retained entry for an absent file triggers no operation (there is nothing to revert), and it is carried into the archived `photos-00-ingest.db`. Keeping it preserves the "every change is explainable from the record" guarantee (shared contract Section 12) even for files that later left the workspace; the cost (a few stale rows) is accepted in exchange for never silently dropping evidence of a past mutation.

6. **The ledger is per-workspace.** The pre-state ledger lives in that workspace's `photos-00-ingest.db` and is meaningful only within it. If a workspace is finalized and torn down and the same photos are later re-imported into a **fresh** workspace, the new workspace starts with no ledger: a manual GPS override there pins whatever GPS the files *now* carry (i.e. the previously-applied value) as that workspace's "original." This is intended and correct — within any one workspace, "original" means the state before that workspace first touched the field. The archived `photos-00-ingest.db` (shared contract Section 13.4) preserves the original ledger as a historical record of the finalized workspace; it is not auto-merged into a new workspace's live ledger. Reversibility is therefore a within-workspace guarantee, not a cross-workspace one — consistent with the workspace being transient and decisions being re-authored per workspace.

**Manual vs. automated is the dividing line.** Two GPS writes can target the same field, but only the manual override is reversible:

- **Manual GPS** (locked or fallback, authored by the user) — reversible via the pinned pre-state as above.
- **Automated GPS** (GPX interpolation/extrapolation, preserved native GPS) — **not** rolled back. Withdrawing or invalidating an automated decision simply means it is not re-derived; the field is recomputed from current inputs and whatever recomputation yields is written. No pre-state is stored for automated values, and no revert operation is emitted for them. This must be explicit in the plan: a revert operation exists *only* for a withdrawn manual GPS override.

**Time and filename are never reverted.** Resolved UTC and the destination-local filename position the file *within its destination*. They are always **recomputed** to match current decisions, never rolled back to a pre-pipeline value — reverting them would un-position an already-organized file, which is meaningless. Recomputation only rewrites the timestamp metadata and the filename **in place within `5-photos-by-dest`**; it never moves the file to a different destination or anywhere else in the tree — the file stays in the destination folder the user placed it in. So: GPS manual overrides are reversible from stored pre-state; time and naming are recomputed in place within by-dest; automated GPS is overwritten by recomputation.

The plan therefore distinguishes three operation origins for a GPS field — *apply manual*, *revert manual to pinned pre-state*, and *recompute automated* — and the transformation log (shared contract Section 13.3) records which applied to each file, including a revert and the pre-state it restored.

---

## 25. Create `photos-22-gps-decisions.json`

Once the GPS-decision stage is reached, the workflow must create:

```text
photos-22-gps-decisions.json
```

This artifact exists even if no GPS changes are required.

It must be grouped by destination.

`photos-22-gps-decisions.json` is a GPS decision artifact, not the executable operation list.

For files whose GPS decision is automatic, no-op, or automatically correctable without user review, the JSON should contain per-destination summaries rather than enumerating every file path.

File paths should appear in `photos-22-gps-decisions.json` only for items where the user must make or review a decision, for example:

1. manual GPS fallback needed;
2. ambiguous GPX match;
3. conflicting GPS evidence;
4. stale preserved user decision;
5. blocker that the user must resolve.

The exact file-level operation list belongs in:

```text
photos-23-executable-plan.json
```

That executable plan must include the actual file paths, metadata writes, marker writes, and rename operations to be executed.

The GPS decision artifact therefore follows this rule:

```text
photos-22-gps-decisions.json:
  summarize automatic/no-op GPS decisions;
  list file paths only for user-review or blocker items.

photos-23-executable-plan.json:
  list exact file-level operations to execute.
```

Because `photos-22-gps-decisions.json` only *summarizes* automatic and no-op GPS decisions (it enumerates individual file paths solely for user-review and blocker items), it is NOT the source of the per-file automatic GPS operations. `photos-23-executable-plan.json` re-derives every automatic GPS decision deterministically from its own validated inputs (resolved-UTC cache, GPX index/fingerprint, native GPS facts, folder fallback rules, and GPS policy config). `photos-22-gps-decisions.json` contributes to the plan only (a) the human-reviewed decisions and (b) its SHA-256 as a dependency proving the review state the plan was built against. Automatic decisions must be reproducible from inputs alone, so the summary-only artifact never needs to carry per-file automatic data.

For each destination, `photos-22-gps-decisions.json` should summarize automatic categories such as:

1. number of files preserving native GPS;
2. number of files with no GPS change needed;
3. number of files automatically assigned GPX interpolation;
4. number of files automatically assigned GPX extrapolation;
5. number of files automatically assigned manual/folder fallback GPS, if policy allows;
6. number of files blocked;
7. number of files requiring user review;
8. GPX sources used;
9. confidence/quality summary;
10. dependency fingerprints.

Example shape:

```json
{
  "destination_path": "5-photos-by-dest/Belgium/Brussels",
  "gps_decisions": {
    "summary": {
      "files_total": 842,
      "preserve_native_gps": 510,
      "automatic_gpx_interpolation": 210,
      "automatic_gpx_extrapolation": 14,
      "automatic_folder_fallback": 0,
      "manual_review_required": 7,
      "blocked": 0,
      "no_gps_change_needed": 101
    },
    "automatic_decision_summary": {
      "gpx_files_used": [
        "tracks/brussels-2024-07-03.gpx"
      ],
      "max_interpolation_gap_seconds": 120,
      "max_distance_to_track_m": 30,
      "confidence": "mixed",
      "notes": [
        "Automatic decisions are summarized here. Exact file-level write operations are listed only in photos-23-executable-plan.json."
      ]
    },
    "review_items": []
  }
}
```

### 25.1 If user GPS decisions are required

The artifact should indicate:

```json
{
  "artifact_type": "gps_decisions",
  "artifact_name": "photos-22-gps-decisions.json",
  "status": "requires_user_input",
  "requires_user_input": true,
  "executable": false
}
```

It should include only the sections needed to complete GPS decisions, such as:

1. files requiring manual GPS fallback;
2. destination folders requiring fallback coordinates;
3. GPX interpolation/extrapolation candidates requiring review;
4. ambiguous GPS decisions;
5. explicit accept/reject/fillable decision fields;
6. blockers preventing executable planning.

### 25.2 If no user GPS decisions are required

The artifact should still be created and should indicate:

```json
{
  "artifact_type": "gps_decisions",
  "artifact_name": "photos-22-gps-decisions.json",
  "status": "complete",
  "requires_user_input": false,
  "executable": false,
  "decision_mode": "no_op_or_auto_resolved"
}
```

This no-op/complete artifact becomes part of the dependency cascade.

Downstream stages must depend on it and validate it.

---

## 26. Filename format configuration

Timestamp rename format must be part of the workspace config.

The workflow must not hard-code a single filename format.

The default filename pattern should produce names like:

```text
2024-07-03--14-12-21.ext
2024-07-03--14-12-21-001.ext
2024-07-03--14-12-21-002.ext
```

where:

```text
2024-07-03--14-12-21
```

is the destination-local naive timestamp derived from:

```text
resolved UTC
  -> destination civil timezone
  -> local civil datetime
  -> configured filename timestamp pattern
```

and:

```text
-001
```

is the first differentiating no-clobber suffix allocated when needed.

The default timestamp format should therefore be equivalent to:

```text
YYYY-MM-DD--HH-MM-SS
```

The full filename pattern should be configurable, with the default behaviour conceptually equivalent to:

```text
{destination_local_datetime:%Y-%m-%d--%H-%M-%S}{dedupe_suffix}{ext}
```

The differentiating suffix must be allocated deterministically and safely.

The first file with a given timestamp receives no suffix if the base name is free.

The first collision receives:

```text
-001
```

The second collision receives:

```text
-002
```

and so on.

Examples:

```text
2024-07-03--14-12-21.ext
2024-07-03--14-12-21-001.ext
2024-07-03--14-12-21-002.ext
```

The requirements are:

1. filename format is config-driven;
2. default timestamp format is `YYYY-MM-DD--HH-MM-SS`;
3. timestamp is computed from resolved UTC converted to destination civil timezone;
4. differentiating suffix is no-clobber and deterministic;
5. extension is preserved according to the project’s extension-normalisation rules;
6. filename-format config participates in dependency fingerprints;
7. changing the filename format invalidates the executable rename plan.

The default timestamp format is supplied by the shared, phase-neutral config key `filename_timestamp_format` (in the workspace config `photos-00-config.json`, default `%Y-%m-%d--%H-%M-%S`), defined authoritatively in the shared contract (`10_photos-shared-contract.md` Sections 4 and 7). The same key is read by prep from the same file, so the format is never hard-coded and cannot drift between phases; its value feeds the filename-format dependency fingerprint. (The name `calibration_filename_timestamp_format` used elsewhere historically is an alias for this shared key — see shared contract Section 7.1.)

---

## 27. Stage 9 — Plan timestamp-based no-clobber renames

The executable plan must include no-clobber rename operations where the corrected timestamp implies a different filename under the project’s timestamp naming pattern.

The planning must account for cases where files might effectively trade names. During the planning phase, never optimize by assuming a currently occupied filename will become free due to a planned rename. Always treat existing disk files as permanently occupied for the duration of the suffix allocation loop. It is vastly safer to end up with a -001 suffix than to accidentally clobber a file because an execution sequence ran slightly out of order.

The rename time basis is:

```text
resolved UTC per file
  -> converted to destination civil timezone
  -> formatted as naive local timestamp
  -> used for configured filename pattern
```

Filenames are based on destination-local civil time, not raw camera time and not UTC text.

Correct example:

```text
resolved_utc = 2024-07-03T12:12:21Z
destination_timezone = Europe/Brussels
destination_local_time = 2024-07-03 14:12:21
configured default timestamp component = 2024-07-03--14-12-21
planned filename = 2024-07-03--14-12-21.ext
```

If that name already exists and the no-clobber allocator chooses the first suffix:

```text
planned filename = 2024-07-03--14-12-21-001.ext
```

If both the base name and `-001` exist:

```text
planned filename = 2024-07-03--14-12-21-002.ext
```

The executable plan must:

1. compute planned destination-local naive timestamp for each file;
2. apply the configured filename format;
3. compare it to the current filename/path;
4. plan a rename only if needed;
5. allocate unique target names sequentially, updating each object's planned filename field and evaluating collisions strictly against the current filename and planned filename of all other in-memory objects;
6. detect case-insensitive conflicts;
7. reject unsafe rename plans;
8. record rename dependencies, including filename-format config fingerprint;
9. execute only the planned rename operations after stale-plan validation.

Execution must not invent new rename decisions or choose a different suffix.

It only applies renames already present in `photos-23-executable-plan.json`.

---

## 28. Create `photos-23-executable-plan.json`

An executable calibration plan may be produced only when:

1. `photos-21-time-decisions.json` exists and completely covers each destination;
2. destination timezone is known;
3. resolved UTC exists for every file and is current;
4. `photos-22-gps-decisions.json` exists and completely covers each destination;
5. all GPS decisions are complete;
6. planned timestamp renames are no-clobber and safe;
7. no blockers remain;
8. config dependencies are current;
9. GPX dependencies are current, where relevant;
10. prep handoff/cache dependencies are current;
11. media file size/mtime/hash preconditions are current.

The executable artifact is:

```text
photos-23-executable-plan.json
```

It must be grouped by destination.

Per destination, it should include:

1. metadata time writes;
2. metadata GPS writes, distinguishing their origin: *apply manual* GPS, *recompute automated* GPS (interpolation/extrapolation/preserved native), and *revert manual* — restoring the pinned pre-state of a withdrawn manual GPS override (previous coordinates, or clearing GPS if the pre-state was "absent"), per Section 24.1;
3. GPSProcessingMethod marker writes, if applicable;
4. no-clobber timestamp rename operations;
5. no-op files;
6. blockers;
7. dependency fingerprints.

It should clearly indicate:

```json
{
  "artifact_type": "executable_plan",
  "artifact_name": "photos-23-executable-plan.json",
  "status": "ready",
  "executable": true
}
```

The executable plan must include dependency fingerprints sufficient to reject stale execution.

It must include a flattened dependency list that directly names and fingerprints all required upstream artifacts and inputs.

It must depend on:

1. `photos-21-time-decisions.json` path and SHA-256;
2. resolved UTC cache fingerprint;
3. `photos-22-gps-decisions.json` path and SHA-256;
4. config fingerprint;
5. camera group/config classification fingerprint;
6. `photos-11-handoff.json` path and SHA-256;
7. prep SQLite cache fingerprint;
8. GPX fingerprint, if relevant;
9. media file preconditions;
10. metadata field-set version;
11. filename-format config fingerprint;
12. planned operation fingerprint.

---

## 29. Stage 10 — Execution

The entire calibration run — every pass of the convergent rerun loop (Section 2.1), including preflight, planning, and execution — runs under the single workspace-wide lock acquired at process startup and held until exit (shared contract `10_photos-shared-contract.md` Section 2). No two pipeline processes of either phase ever overlap. The execution steps below assume the lock is already held; they do not re-acquire or independently scope it.

Execution applies only the already-planned metadata and rename operations.

Execution must:

1. load `photos-23-executable-plan.json`;
2. re-hash all named JSON artifact dependencies using SHA-256;
3. validate all non-JSON upstream dependencies;
4. reject stale plans before mutation;
5. confirm the workspace lock is held (acquired at run start per shared contract Section 2);
6. take a pre-mutation snapshot where configured, reusing the same ZFS snapshot mechanism prep uses (the `zfs` block in the workspace config `photos-00-config.json`, keyed by plan id), and honoring the same `snapshots_required` semantics (abort if a required snapshot fails);
7. apply only planned operations;
8. journal every metadata write, marker write, file move, or rename;
9. update SQLite/cache after successful writes;
10. write `photos-24-execution-summary.json` (contents per Section 29.2);
11. produce a final execution summary.

Execution must not recalculate time, GPS, filename, or rename decisions.

If any dependency changed, execution must block and require replanning from the correct upstream stage.

If the executable plan includes GPS metadata writes, execution applies those writes.

If the executable plan includes local-time-based no-clobber renames, execution applies those renames exactly as planned.

### 29.1 Execution idempotency and resume

Execution must be safely re-runnable after a crash or partial application. The plan carries a stable plan id and every applied operation is journaled (steps above), so a re-run of the same `photos-23-executable-plan.json` must:

1. re-validate all dependencies (a crash does not excuse stale execution);
2. consult the journal and treat already-applied operations as completed no-ops rather than reapplying them;
3. detect already-satisfied target state directly (e.g. metadata already equal to the planned value, rename target already in place) and skip it;
4. apply only the remaining operations, then finalize the summary.

Re-running a fully-applied plan must be a no-op. Execution must never reapply a metadata write or rename whose effect is already present, and must never choose a different no-clobber suffix than the one recorded in the plan.

### 29.1a Per-operation atomicity and torn-write detection

Execution mutates the photographic files' metadata and names, so each operation must be individually atomic and crash-detectable — a crash, a kill, or an `exiftool` failure mid-operation must never leave a file in a half-written or ambiguous state, and the resume logic of Section 29.1 must be able to tell, per file, whether an operation completed. (Calibration operates on photos only and writes metadata with `exiftool`; videos never reach by-dest and are never touched here, Section 7.3.)

1. **Atomic writes.** A metadata write or rename either fully takes effect or not at all. Metadata writes are performed so that the original file is never left partially overwritten — e.g. write to a temporary copy and atomically rename it into place, or use the tool's safe-write mode — so an interruption leaves either the pre-write file or the fully-written file, never a corrupt intermediate. Renames are single atomic filesystem operations (no-clobber, Section 27).
2. **Journal intent before, confirmation after.** For each operation the journal records an *intent* record before the mutation and a *confirmation* record after it succeeds (with enough identity — content hash, target field/name, and the resulting value — to verify completion). On resume, an operation with intent-but-no-confirmation is treated as **possibly torn**: execution re-derives the file's actual current state and either completes the operation (if the pre-write state is still present) or marks it done (if the post-write state is already present). Because writes are atomic (point 1), the file is always in exactly one of those two states, never a corrupt third.
3. **Pre-state captured before the overwrite it protects.** For a manual GPS override, the pinned pre-state (Section 24.1) must be committed to the ledger **before** the GPS write that overwrites it is applied. If the capture and the write were ordered the other way, a crash between them could lose the true original. So the ordering is: capture-and-commit pre-state → then write. A crash after capture but before write leaves a pinned pre-state equal to the current file state, which is harmless (a later revert simply restores what is already there).
4. **Tool failure is fatal to that operation, not silent.** If `exiftool` reports failure for a file, execution records the failure (Section 29.2 item 6), leaves that file at its pre-operation state (point 1 guarantees it is intact), and continues or aborts per policy — it never records the operation as applied. A failed write is never treated as a no-op on the next run.

### 29.2 The execution summary artifact (`photos-24-execution-summary.json`)

On finishing execution, the workflow writes the terminal artifact `photos-24-execution-summary.json` to `.photos-ingest/` (Section 8.1). It is a record of what execution actually did; unlike `photos-21`–`23` it is never an upstream dependency and is never re-hashed (Section 4), so nothing is built from it.

It must record at least:

1. **Artifact identity** — artifact type, name, and schema version;
2. **Run identity** — the plan id and execution id it summarizes;
3. **What it summarizes** — the SHA-256 of `photos-23-executable-plan.json` (the plan that was executed) and the flattened upstream chain that plan validated against (e.g. `photos-21-time-decisions.json`, `photos-22-gps-decisions.json`, and `photos-11-handoff.json` SHA-256s and the non-JSON fingerprints), so the summary unambiguously identifies the exact inputs the execution was based on;
4. **Operations applied, per destination and in global total** — counts of: time-metadata writes, GPS metadata writes, `GPSProcessingMethod` marker writes, no-clobber renames, no-ops (already-correct files), and skips;
5. **Resume/journal facts** — for a re-run after a crash or partial application (Section 29.1): how many planned operations were newly applied versus treated as already-satisfied-and-skipped, so a resumed run is auditable;
6. **Failures and blockers** — any operation that failed or any blocker encountered during execution, with enough detail to act on;
7. **Final status** — `success`, `partial`, or `failed`;
8. **Run metadata** — wall-clock timestamps, job count, and similar, kept **separate** from the fingerprints in item 3.

Although nothing re-hashes it, the artifact follows the same structure and determinism discipline as the other artifacts for consistency: it is grouped by destination (with a global summary), records the SHA-256 of what it summarizes (item 3), and separates run-metadata timestamps from fingerprints (item 8), mirroring the prep handoff's determinism rule (prep `10_photos-1-prep-workflow.md` Section 16).

Example shape:

```json
{
  "artifact_type": "execution_summary",
  "artifact_name": "photos-24-execution-summary.json",
  "schema_version": "...",
  "plan_id": "...",
  "execution_id": "...",
  "status": "success",
  "summarizes": {
    "photos-23-executable-plan.json": { "sha256": "..." },
    "upstream": { "photos-21-time-decisions.json": "sha256", "photos-22-gps-decisions.json": "sha256", "photos-11-handoff.json": "sha256", "...": "..." }
  },
  "totals": {
    "time_metadata_writes": 0,
    "gps_metadata_writes": 0,
    "gps_processing_method_markers": 0,
    "renames": 0,
    "no_ops": 0,
    "skipped": 0
  },
  "resume": { "newly_applied": 0, "already_satisfied_skipped": 0 },
  "failures": [],
  "destinations": { "5-photos-by-dest/Belgium/Brussels": { "...": "..." } },
  "run_metadata": { "started_at": "...", "finished_at": "...", "jobs": 1 }
}
```

---

## 30. Idempotency and recalculation

The calibration workflow must be idempotent, upholding the shared idempotency principle — change only what needs changing; a no-op run is a no-op (shared contract `10_photos-shared-contract.md` Section 11).

Repeated planning with unchanged inputs should produce the same semantic results.

The workflow should recalculate only the affected downstream artifacts when upstream inputs change.

Examples:

```text
4-photos-by-date contains photos
  -> calibration blocked
  -> no JSON artifact created

jpg/tif development subfolder present under 5-photos-by-dest
  -> calibration hard-stops (development already started)
  -> no JSON artifact created

Non-media (other-class) file present under 5-photos-by-dest
  -> calibration hard-stops (by-dest must be photo-only, Section 7.2)
  -> offending path(s) reported; no JSON artifact created

User moved files into by-dest but did not re-run prep
  -> by-dest media not recorded by handoff / by-date files now missing
  -> calibration hard-stops with targeted "re-run prep" blocker (Section 13.1)
  -> no JSON artifact created

Prep cache / by-dest file facts changed
  -> calibration blocked
  -> prep/cache refresh required

Workspace config changed
  -> camera groups stale
  -> photos-21-time-decisions.json stale
  -> resolved UTC stale
  -> photos-22-gps-decisions.json stale
  -> photos-23-executable-plan.json stale

Camera group classification changed
  -> photos-21-time-decisions.json stale
  -> resolved UTC stale
  -> photos-22-gps-decisions.json stale

photos-21-time-decisions.json changed
  -> resolved UTC stale
  -> photos-22-gps-decisions.json stale
  -> photos-23-executable-plan.json stale

Resolved UTC cache changed
  -> photos-22-gps-decisions.json stale
  -> photos-23-executable-plan.json stale

GPX folder changed
  -> GPX index stale
  -> GPX/native-GPS time-anchor proposals stale if they used GPX
  -> photos-22-gps-decisions.json stale
  -> photos-23-executable-plan.json stale

Destination timezone changed
  -> resolved UTC may be stale where timezone affected time interpretation
  -> local rename plan stale
  -> photos-23-executable-plan.json stale

Filename format config changed
  -> local rename plan stale
  -> photos-23-executable-plan.json stale

photos-22-gps-decisions.json changed
  -> photos-23-executable-plan.json stale

Media file size/mtime/hash changed
  -> calibration blocked
  -> prep/cache refresh required
```

---

## 31. Stage 11 — Finalize and archive (explicit command)

Finalize is a **separate, explicitly-invoked command**, not part of `execute` and not run automatically at the end of calibration. Because calibration is freely re-runnable (Section 2.1; shared contract `10_photos-shared-contract.md` Section 10.1), "this dump is done" is a human judgement, so the user invokes finalize when finished with a workspace to produce the durable archival package.

Finalize must:

1. run under the workspace lock (shared contract Section 2) and be **non-destructive** — it reads and bundles; it never mutates the workspace, the artifacts, the SQLite DB, or the library;
2. require that calibration has ended successfully (a complete, executed `photos-23-executable-plan.json` with a corresponding `photos-24-execution-summary.json`); it refuses to finalize an incomplete or stale state;
3. assemble the **archival package** defined in shared contract Section 13 — `photos-00-config.json`, the SQLite database `photos-00-ingest.db`, the JSON artifacts `photos-11-handoff.json`, `photos-21-time-decisions.json`, `photos-22-gps-decisions.json`, `photos-23-executable-plan.json`, `photos-24-execution-summary.json`, and a freshly generated `photos-25-complete-log.json`;
4. generate the transformation log `photos-25-complete-log.json` (shared contract Section 13.3) by consolidating prep's handoff/journal and calibration's decision artifacts/journal into a per-photo, content-hash-keyed, human-readable JSON record of every transformation between ingestion and successful calibration;
5. write a self-describing manifest (workspace identity, plan/execution ids, and SHA-256 of each bundled item) so the package's integrity is verifiable later;
6. leave the package in a known location the user can move to permanent storage alongside the library.

Finalize creates no new authority and makes no decisions; it is the retention step that makes authored decisions (shared contract Section 12) outlive the transient workspace.

---

## 32. User-visible outputs

The workflow should produce user-facing outputs at each blocked or decision point.

Important textual outputs include:

1. by-date-not-empty blocker;
2. development-already-started (jpg/tif subfolder present) hard-stop;
3. stale prep/by-dest dependency report;
4. unknown camera group report;
5. pasteable config snippets for newly recognised groups;
6. reason why no JSON artifact was produced, if blocked before time-decision stage;
7. time-decision summary;
8. resolved UTC cache summary;
9. GPS-decision summary;
10. executable plan summary;
11. execution summary.

Important JSON artifacts include:

```text
photos-21-time-decisions.json
photos-22-gps-decisions.json
photos-23-executable-plan.json
photos-24-execution-summary.json
```

The user should always know:

1. which stage they are in;
2. why the workflow is blocked, if blocked;
3. which artifact was created, if any;
4. what action is needed next.

---

## 33. Non-goals

This workflow does not define:

1. the exact CLI;
2. the exact Python classes;
3. the exact SQLite schema;
4. the exact JSON schema;
5. the exact implementation of GPX parsing;
6. the exact metadata write commands.

Those belong in later script-level specifications.

This document defines only the calibration workflow, artifact states, dependencies, and decision order.

---

## 34. Summary

This section restates the rules established above as a single ordered reference. Sections 11 (data cascade) and 12 (state machine) are two views of the same pipeline. On any apparent conflict, the numbered specification sections above govern over this summary.

The calibration workflow is:

```text
1. Invoke calibration.
2. Load prep handoff and SQLite cache.
3. Verify 4-photos-by-date contains no photos and no jpg/tif development subfolders exist under 5-photos-by-dest (hard-stop if development started).
4. Restrict calibration scope to 5-photos-by-dest.
5. Validate by-dest cache/media/prep dependencies.
6. Load, parse, and fingerprint GPX folder/files if configured or available.
7. Recognise and classify camera groups.
8. If unknown groups exist, print config snippets and stop. No JSON artifact yet.
9. Analyse per-destination time requirements.
10. Determine/confirm destination civil timezone for every destination.
11. Generate GPX/native-GPS time-anchor proposals where possible.
12. Create photos-21-time-decisions.json, grouped by destination, even if no-op.
13. User completes/accepts time decisions if needed.
14. Compute and persist resolved UTC per file in SQLite.
15. Start GPS planning only after resolved UTC exists for every file.
16. Create photos-22-gps-decisions.json, grouped by destination, even if no-op; summarize automatic/no-op decisions and list file paths only for review/blocker items.
17. Plan metadata writes and no-clobber destination-local-time renames using configured filename format.
18. Create photos-23-executable-plan.json, grouped by destination, with flattened dependency list and exact file-level operations.
19. Execute only after strict dependency validation, including SHA-256 rehashing of named JSON artifacts.
```

The most important workflow rule is:

```text
Time first. GPS second. Rename/metadata execution last.
```

The artifact rule is:

```text
No JSON before the first formal decision stage.
Always produce numbered JSON artifacts at formal decision stages, even when no-op.
Human decisions go into pre-created empty fields and are preserved across regeneration.
Dependencies are flattened, named, and directly verified.
JSON artifact dependencies are verified by SHA-256 rehashing exact file bytes.
Validate upstream -> create artifact -> record dependencies in it -> reject downstream use if dependencies changed.
```
