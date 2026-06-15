# Time/GPS Calibration Workflow Specification (`photos-2-time-gps`)

## 1. Purpose

This document defines the high-level workflow for the time/GPS calibration phase that follows `photos-1-prep`.

The calibration phase exists to:

1. validate that prep has produced a current by-dest working set;
2. operate only on files under `6-photos-by-dest`;
3. require `5-photos-by-date` to contain no photos before calibration can proceed;
4. require that destination development (the jpg/tif breakout) has not yet started;
5. ensure every file can be resolved to real UTC;
6. persist resolved UTC for every file in SQLite;
7. plan GPS decisions only after time is solved;
8. plan timestamp-based no-clobber renames using destination-local civil time;
9. produce numbered JSON decision artifacts at formal decision stages;
10. execute only a complete, dependency-validated executable plan.

This is a workflow specification, not a script implementation specification.

Cross-phase facts shared with prep — the workspace lock, the pre-mutation snapshot (`zfs`) mechanism, the shared configuration object, the workspace control directory, the camera-group identity key, the filename timestamp format, the GPX root, and the end-to-end operator loop — are defined in `photos-shared-contract.md` and are authoritative there. This document references that contract rather than restating it.

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

Calibration is also re-runnable *after* a successful execute — it is not a terminal, run-once phase. Media added later is absorbed by re-running prep (to recognize it) and then calibration, bounded only by calibration's gating preconditions and the rule that development must not have started — and by the fact that this freedom lasts only until the workspace is **merged and sealed** (shared contract `photos-shared-contract.md` Sections 13.7, 10.1): a sealed workspace accepts no further prep or calibration, and more media then means a fresh workspace. The authoritative cross-phase account of this — including why already-processed files are no-ops on rerun and when a rerun legitimately re-enters the decision loop — is in the shared contract (`photos-shared-contract.md` Section 10).

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

`photos-11-handoff.json` is the contract calibration receives from prep (prep `photos-1-prep-workflow.md` Section 16). It is the **one JSON dependency calibration checks by a recomputed content fingerprint rather than a whole-file byte hash**, and for a specific reason: the handoff deliberately mixes a deterministic description of the post-prep workspace state with per-run audit (the `run_metadata` block, diagnostics, and the `execution_journal` pointer), so its exact bytes change on every prep run even when the organized result did not (prep Section 16.2). Depending on the whole-file SHA-256 would therefore restale calibration on a no-op re-prep, which is wrong. Instead, wherever calibration depends on the handoff, the dependency entry records the handoff's top-level **`content_fingerprint`** (the SHA-256 prep computes over the handoff's deterministic content with `run_metadata`, diagnostics, the journal pointer, and the fingerprint field itself removed, prep Section 16.2), and calibration **recomputes that fingerprint from the handoff** and compares it before use — the same recompute-and-verify discipline it applies to every other dependency fingerprint. The handoff's **whole-file SHA-256 still exists** as its integrity/archival hash (shared contract Section 13), and calibration may record it for identification, but it is **not** the staleness trigger. This keeps the handoff's staleness **surgical** (shared contract Section 4.2): only a change to the deterministic content restales downstream, while a run-only refresh does not. (Among the numbered `photos-2X` artifacts, which carry no per-run audit of this kind, the dependency check remains the whole-file byte hash as before.)

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
4. `photos-11-handoff.json` and its **`content_fingerprint`** (recomputed from the handoff's deterministic content, not a whole-file byte hash, Section 4; prep Section 16.2);
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

1. re-hashing named JSON artifacts from file bytes using SHA-256 (the numbered `photos-2X` artifacts);
1a. recomputing the prep handoff's `content_fingerprint` from `photos-11-handoff.json` and comparing it to the value recorded in the dependency block — the handoff is verified by recomputed content fingerprint, not whole-file byte hash, so a run-only refresh of the handoff does not register as a change (Section 4; prep Section 16.2);
2. recomputing config fingerprints from the active config;
3. recomputing GPX folder/file fingerprints where relevant;
4. validating SQLite cache fingerprints or cache-generation markers;
5. validating resolved UTC cache fingerprints;
6. checking media file size/mtime/fingerprint preconditions;
7. checking metadata field-set/extractor versions;
8. checking filename-format config fingerprint.

If any dependency does not match, the artifact is stale and must not be used.

Not every listed check is an independent re-derivation from raw inputs at this step. Some dependencies are verified **transitively** through the linear-inclusion rule (Section 5): a fingerprint that an upstream artifact already validated and recorded — for example the **resolved-UTC cache fingerprint**, the **prep cache fingerprint**, and the **metadata field-set version** — is checked at the point that owns it and then carried forward in each downstream artifact's flattened dependency set, rather than recomputed from scratch every time it is named again. Because each artifact carries the *full* flattened set (Section 5), a change anywhere still surfaces downstream; transitivity is about not redundantly recomputing the same value at every step, not about skipping it. The values verified directly at a given step are the named JSON artifact hashes and the prep handoff's recomputed content fingerprint (items 1–1a), the config and GPX fingerprints recomputed from their live sources, and the per-file media preconditions; the rest are honored through the chain.

Execution must not proceed from stale dependency state.

---

## 7. Calibration scope

Calibration operates only on files under:

```text
6-photos-by-dest/
```

The workflow must not calibrate files still in:

```text
0-sources/           (must be EMPTY — gated below)
1-strays/
2-missing-metadata/
3-redundant-jpgs/
4-videos-by-date/
5-photos-by-date/    (must contain no photos — gated below)
```

These folders are not calibration's concern for *processing*. Residual content in `1-strays/` (the non-media prep moved out of `0-sources`, prep Section 3.2), `2-missing-metadata`, `3-redundant-jpgs`, or `4-videos-by-date` is expected and **does not block** calibration. Two of these folders are **gated**, however (Section 13): `0-sources/` must be **empty** (prep leaves it empty after every run, so a non-empty `0-sources` means an un-processed dump is waiting and the user should re-run prep), and `5-photos-by-date/` must contain no photos (a non-empty one means the user has not finished placing photos into by-dest).

Before calibration may proceed, the workflow must verify that:

```text
5-photos-by-date/
```

contains no photos.

If `5-photos-by-date/` still contains photos, calibration must block before creating any calibration JSON artifact.

The reason is to push the user to complete prep and place the current batch of files into `6-photos-by-dest` before calibrating that batch. This is a per-run gate, not a once-ever deadline: more files can be added and calibrated in a later cycle (shared contract `photos-shared-contract.md` Section 10), but each calibration run requires `5-photos-by-date` to be empty at the time it runs.

The workflow may print a textual message such as:

```text
Calibration cannot proceed.

Reason:
5-photos-by-date still contains photos.

Calibration only operates on 6-photos-by-dest.
Move/place remaining by-date files into by-dest through the prep workflow before calibrating.

No calibration JSON was written.
```

### 7.0a Assumption: each destination is time-coherent for a camera

Calibration assumes that **a camera's clock error is constant within one destination on one day** — every photo from one camera within one destination *on the same naive calendar date* shares one true clock offset. Clock corrections therefore vary **between** destinations and **between days within a destination** (a place revisited on different days or seasons), never within a single day's shoot. The user typically sets the camera to local time each morning, so the offset is a per-day fact; a destination spanning more than one naive date splits into per-day offset buckets (Section 10.2 rule 4).

This is a deliberate assumption about how the user organizes media, and it is *why* the camera clock offset is inferred and applied per **(camera group, destination)** rather than once per camera (Section 10.2):

- A camera's clock **drifts**, and is sometimes **reset**, between trips. Different destinations correspond to different trips/time-windows, so the same camera's true offset can differ from one destination to the next. A single global per-camera offset would be wrong the moment the clock moved between two destinations.
- Each destination's offset is anchored only from that camera group's native-GPS frames *in that destination* (Section 19), so each trip is corrected on its own evidence.
- A **nested subfolder is a separate destination** (Section 10.1) with its own offset cell — there is no roll-up. If you keep a single coherent shoot in one destination (the natural way to organize), this assumption holds automatically; if you deliberately split one shoot across nested destinations, each is corrected independently.

A (camera group, destination, date) bucket with no native-GPS frame of its own does not start blank: when the destination's civil timezone is resolved, calibration proposes a **timezone-derived** offset from the local clock for that day (Section 10.2 rule 4b, Section 19.4), confirmable. Clock offsets are **not** inherited from ancestor destinations — unlike the timezone and the folder GPS fallback, an offset is a measured/assumed fact tied to a specific place and day, not a folder default to cascade. A bucket with neither its own GPS frames nor a resolved timezone starts from a blank manual field.

### 7.1 Development must not have started

Breaking a destination's media out into format-specific subfolders (by default `jpg/` and `tif/`, configurable via a `destination_distribution_subfolders` config key) belongs to a *later* development/processing phase that runs only after time and GPS are fixed. Development depends on the corrected timestamps, GPS, and filenames that calibration produces, so it must not run first.

Therefore, before calibration may proceed, the workflow must verify that no such distribution subfolder exists anywhere under `6-photos-by-dest`. The check is strict: the mere existence of a folder whose name matches `destination_distribution_subfolders` triggers the hard-stop, **even if that folder is empty**. The workflow must not attempt to decide whether the folder "really" holds development output — presence alone is the signal. On detecting one, the workflow must hard-stop before creating any calibration JSON artifact: it means development has already begun and would be invalidated by the time/GPS corrections calibration is about to plan. This presence check is **re-evaluated at every invocation — `run`, `execute`, and `finalize` alike**, not only at planning: a breakout begun *between* `run` and `execute` moves no planned file, so the per-operation media preconditions (Section 29) would not catch it; the existence check is the only thing that does, so `execute`/`finalize` hard-stop on it before any mutation or bundling.

The workflow may print a textual message such as:

```text
Calibration cannot proceed.

Reason:
A jpg/ or tif/ development subfolder was found under 6-photos-by-dest:
  6-photos-by-dest/2025/France/Paris/Louvre/jpg

This means photo development/processing has already started.
Time/GPS calibration must run BEFORE development, because it rewrites
timestamps, GPS, and filenames that development depends on.

Stop and roll back the development breakout (remove the jpg/tif subfolders
and restore the undistributed destination) before calibrating.

No calibration JSON was written.
```

### 7.2 By-dest must contain only photos

`6-photos-by-dest` is the user-curated **staging area** that calibration operates on: the user organizes a dump into destination folders here, calibration corrects time/GPS and finalizes names, and the result is then **merged into** the user's permanent library (e.g. digiKam) elsewhere. The workspace is not the library — it is transient working space for one or more dumps — but by-dest is structured to merge cleanly into the library, so it must contain **only photo files** (`image`/`raw` classes): the photos the user actively moved from by-date. It must not contain `other`-class non-media files, stray sidecars, notes, archives, or any non-media artifact — and it must not contain **videos** (Section 7.3); videos stay in `4-videos-by-date`.

Before calibration may proceed, the workflow must verify that under `6-photos-by-dest` (recursively) there is no `other`-class non-media file **and no `video`-class file** — only `image`/`raw` photo files are permitted. Media classes are the project's `image`/`raw`/`video` extensions; `other` is non-media, and `video` belongs in `4-videos-by-date`, not by-dest (Section 7.3). The pipeline's own control artifacts are not affected because they never live under `6-photos-by-dest` — the numbered calibration artifacts are written to `.photos-ingest/` (Section 8.1), and `gpx_root` resolves outside the managed tree (shared contract Section 8). If any non-photo file (non-media or video) is found under by-dest, calibration must hard-stop before creating any calibration JSON artifact and report the offending path(s); it does not silently ignore or skip the file, because its presence means by-dest is not the clean photo-only set that calibration and the later merge into the library assume.

The workflow may print a textual message such as:

```text
Calibration cannot proceed.

Reason:
A non-photo file was found under 6-photos-by-dest:
  6-photos-by-dest/Japan/Kyoto/notes.txt        (non-media)
  6-photos-by-dest/Japan/Kyoto/clip.mp4         (video — belongs in 4-videos-by-date)

6-photos-by-dest must contain only photo files moved in from by-date.
Remove or relocate non-photo files (and any videos) before calibrating.

No calibration JSON was written.
```

**Symlinks under by-dest are barred, including nested directory symlinks.** A symlink anywhere under `6-photos-by-dest` — a file symlink, or a **nested directory symlink** — is forbidden for the same escape reason it is forbidden elsewhere in the managed tree (shared contract `photos-shared-contract.md` Section 5.3; prep `photos-1-prep-workflow.md` Section 6.2 item 3): the pipeline never follows or organizes a link. Because `6-photos-by-dest` is **read-only for prep** yet still **scanned by prep as a managed folder**, prep is the gatekeeper that detects and blocks such a symlink, and the mandatory re-prep after any by-dest change (Section 13.1; shared contract Section 10) means a link that slipped in is caught at the prep run that must precede calibration — calibration consumes prep's handoff, which is built only when prep found no forbidden symlink. Calibration itself bars symlinks at the **workspace root** (Section 13) and never follows a link when reading by-dest; it relies on prep's symlink guard for nested links *inside* by-dest rather than re-walking the tree to re-flag them.

### 7.3 Videos are semi-foreign and never reach by-dest

Calibration's target is **photos**. Videos are **semi-foreign** (prep `photos-1-prep-workflow.md` Section 2.4): prep date-organizes and naively renames them into `4-videos-by-date` and they **stay there** — they are never sorted into destinations. Videos must **never** appear in `5-photos-by-date` or `6-photos-by-dest`.

This is a hard invariant, not a preference, and **prep is the primary guard that enforces it**: prep's band-misplacement check hard-blocks a `video`-class file found under **either** `5-photos-by-date` **or** `6-photos-by-dest` (prep `photos-1-prep-workflow.md` Section 6.1, Section 6.2 item 6) — prep reports the offending path and produces no plan. Calibration **re-guards** the by-dest case as a **second line of defence**, not as the primary stop: the by-dest verification of Section 7.2 — rejecting both `other`-class non-media and `video`-class files so only `image`/`raw` photos remain — also rejects a video under `6-photos-by-dest`, so even on the (not-expected) path where calibration runs against a by-dest that still holds a video, calibration hard-stops before creating any artifact. In the normal flow the video never survives the mandatory re-prep that precedes calibration, because prep blocks first; the calibration check exists so a video can never be silently calibrated even if prep's guard were somehow bypassed.

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

They must never be written inside `6-photos-by-dest/` (or any scanned media folder), because that tree is read-only for prep and prep would otherwise inventory the artifacts as ordinary files and fold them into its cache fingerprint.

Placing the artifacts in `.photos-ingest/` is sufficient: prep skips that directory wholesale during its media scan (shared contract `photos-shared-contract.md` Section 5), so the artifacts are never inventoried or folded into prep's cache fingerprint. There is no per-file registry to maintain — keeping every control and artifact file inside `.photos-ingest/` is the whole mechanism.

---

## 9. Human decision field rule

This rule is the mechanism behind the pipeline's authored-decisions principle (shared contract `photos-shared-contract.md` Section 12): the tool never mutates autonomously — it proposes, the user disposes by filling decision fields, and the executor acts only on what the user wrote down. These fields are therefore the durable, traceable record of *why* every time/GPS/rename change happens, and editing them and re-running is how a decision is revised and re-derived.

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
2. **(camera group, destination)** time offset decisions — the logical target is the pair, so a user-filled offset for a group in one destination is preserved independently of the same group's decision in another destination (Section 10.2);
3. GPX/native-GPS time-anchor acceptance;
4. manual time segment decisions;
5. destination/folder GPS fallback decisions (the per-destination folder fallback, inherited downward as a confirmable proposal, Section 25.3);
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

### 9.2 Decision and config sanity-validation

Every human-authored value calibration consumes — the workspace config it reads (Section 13) and the decision fields the user fills in the numbered JSON artifacts — must be **sanity-validated before use**, per the shared input-validation discipline (shared contract `photos-shared-contract.md` Section 14). This is in addition to the dependency-fingerprint/SHA-256 verification of Sections 3–6: the hash checks detect that an artifact *changed*; validation detects that a value *inside* it is invalid. A decision file can re-hash correctly and still contain a malformed timezone or an out-of-range coordinate, and that must be caught.

Calibration validates at least:

1. **Config it reads** (read-only — calibration never writes config): the `gpx_root` resolves sanely; the `zfs` block's snapshot prefix is a valid snapshot-name component (no whitespace, `/`, or second `@`); `filename_timestamp_format` produces a filesystem-safe, non-empty component; GPX thresholds are non-negative numbers; `camera_time_and_timezone_policy.device_groups` classifications are well-formed and reference permitted classes. (Calibration does not consume `library_root` or the merge/placement config — those are merge's to validate, shared contract Section 14.1. Prep is the sole writer of config and validates it on seeding/read too, prep Section 6.3; calibration re-validates the values it actually consumes.)
2. **Destination timezone decisions** (Section 18): a user-entered `manual_iana_timezone` must be a real, resolvable IANA zone; `accept_proposed_timezone` must be boolean; a destination cannot end with an empty effective timezone and still be treated as solved.
3. **Camera-group time decisions** (Sections 10.2, 19): a `manual_real_utc` must parse as a valid UTC datetime; a `manual_offset_seconds` must be a number within sane bounds; `accept_proposal` must be boolean; an accepted anchor must reference an anchor that exists.
4. **Manual GPS decisions** (Section 24.1): entered coordinates must be in range (latitude −90…90, longitude −180…180) and numerically well-formed; a structurally malformed GPS decision object is a validation error, not a silently-skipped one.
5. **Decision structure** (Section 9): the user fills *values*, not structure. A decision object whose shape was broken by hand-editing (missing required keys, wrong types, malformed JSON in a section) is a validation blocker located to the exact artifact, destination/group/file, and field.

Behaviour follows the shared discipline (shared contract Section 14.2): a validation failure is a **hard blocker** reported textually and located precisely (which artifact, which destination/group/file, which field); calibration produces no downstream artifact and mutates nothing from an invalid value, exactly as for a stale dependency. An invalid user decision is **preserved and flagged as requiring correction**, never silently deleted, coerced, or repaired (consistent with Section 9) — the user fixes the source and re-runs. Validation runs whenever the value is consumed on a given run, not cached as permanently valid.

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

A folder that holds only sub-destinations — with **no media directly in it** — is *also* materialized as a destination, called a **container destination** and flagged `file_less: true`. It exists so an operator can author timezone / folder-GPS-fallback decisions on it that propagate **downward** to its children, through the same nearest-ancestor inheritance those two facts use (Section 18, Section 25.3) — e.g. setting one GPS fallback on a trip's parent folder seeds every leaf beneath it. The container set is derived from the real destinations' ancestor paths within `6-photos-by-dest` (no extra filesystem scan); the by-dest root is itself a container when it holds only sub-destinations, giving a single library-wide default node. Because a container has no media of its own to act on, its decision cells **never block and never demand input**: each cell **auto-resolves by inheritance** (it adopts its own nearest-ancestor or config-default proposal without confirmation) yet stays fully overridable, so containers extend reach without adding to the operator's to-do list. A container carries **no clock-offset cells at all**: offsets neither cascade downward nor roll up (Section 10.2 rules 3–4), and a file-less folder has no media to time-correct, so `camera_group_time_decisions` on a container is empty.

All numbered calibration JSON artifacts must cover destinations separately.

This applies to:

```text
photos-21-time-decisions.json
photos-22-gps-decisions.json
photos-23-executable-plan.json
```

Each artifact should be grouped by destination under `6-photos-by-dest`.

A global summary section may exist, but decisions must be inspectable per destination.

### 10.2 Destination-scoped vs. group-scoped decisions

Two scopes coexist, but the split is **not** "timezone is per-folder, clock offset is per-camera." It is:

1. **Group-scoped facts** belong to a *camera* and are the same wherever that camera's files land: the camera-group **identity** (`camera_group_key`) and its **classification as a camera or a smartphone** (config-driven, Section 16). The classification decides *how* a group's time is solved at all — a smartphone carries reliable timezone/offset metadata and is solved per file from that metadata; a camera with a wrong, timezone-less clock needs a clock-offset decision. These facts live in config and in camera-group recognition (Section 16); they are not per-destination.
2. **Destination-scoped decisions** belong to a *destination folder*: the destination civil timezone (Section 18), folder/destination GPS fallback, **and the camera clock offset / time-anchor calibration** (Section 19). The offset is destination-scoped because a camera's clock error is **not** constant across the user's shoots: clocks drift, and are sometimes reset, *between* trips — and destinations are trips. A single global per-camera offset applied to every destination would be wrong the moment the clock drifted between two of them. So the offset is decided **per (camera group, destination)**: the same camera appearing in two destinations gets two independently-inferred offsets, each anchored only from that group's native-GPS frames *in that destination* (Section 19). This is the core assumption stated in Section 7: corrections are made **between destinations, never within one**.

Therefore the time-anchor decision lives **inside each per-destination section**, sub-keyed by the camera group(s) present in that destination — there is no separate top-level group-scoped offset block:

```json
{
  "artifact_type": "time_decisions",
  "destinations": {
    "6-photos-by-dest/Belgium/Brussels": {
      "destination_timezone": { "...": "Section 18" },
      "camera_group_time_decisions": {
        "sony_a6400_serial_123456": {
          "camera_group": "sony_a6400_serial_123456",
          "camera_group_class": "camera",
          "proposal": { "...": "anchored from Brussels' native-GPS frames" },
          "user_decision": { "...": "..." },
          "effective_time_anchor": "",
          "requires_user_input": true
        }
      }
    },
    "6-photos-by-dest/Japan/Kyoto": {
      "destination_timezone": { "...": "Section 18" },
      "camera_group_time_decisions": {
        "sony_a6400_serial_123456": {
          "camera_group": "sony_a6400_serial_123456",
          "camera_group_class": "camera",
          "proposal": { "...": "anchored independently from Kyoto's native-GPS frames" },
          "user_decision": { "...": "..." },
          "effective_time_anchor": "",
          "requires_user_input": true
        }
      }
    }
  }
}
```

The rules are:

1. there is exactly **one** editable clock-offset decision per **(camera group, destination)** — inside that destination's section, keyed by `camera_group_key`. The same camera group appearing in N destinations has N independent decisions, not one shared one;
2. each cell's offset is inferred only from that group's native-GPS frames **in that destination** (Section 19). The same camera in two destinations is anchored twice, independently — never is one destination's offset carried onto another;
3. a **destination is the immediate containing folder, and a nested subfolder is a separate destination** (Section 10.1): there is **no upward roll-up** — a parent's offset is never computed by aggregating its children, and `.../Louvre` and `.../Louvre/Napoleon's Apartments` are distinct cells each with its own effective offset. **Clock offsets also do not flow downward**: unlike the civil timezone (Section 18) and the folder GPS fallback (Section 25.3), an offset is *never* inherited from an ancestor destination — it is a measured/assumed clock fact specific to where and when frames were shot, not a folder default to cascade. A child with no anchor of its own does not borrow its parent's offset;
4. **per-date buckets within a destination.** A user travelling typically **sets the camera to local time each morning**, so the clock offset is constant only *within a naive calendar day*, not across a destination revisited on different days or seasons (nearby attractions hit on separate trips). Therefore the offset cell **splits per naive date** when a (camera group, destination) spans more than one day there: each day gets its own bucket keyed `<camera_group_key>@<YYYY-MM-DD>` and carrying a `date` field. The common single-day case keeps the bare `<camera_group_key>` key with no `date`. A single visit that crosses local midnight splits into two buckets by design. The naive date is the camera's own wall-clock date (`source_naive_time`), taken before any correction. Each bucket's proposed offset is chosen independently, in priority order:
   - **(a) self-anchored** — if that group has native-GPS frame(s) *for this date in this destination* that produce a GPX anchor (Section 19), that anchor is the proposal;
   - **(b) timezone-derived** — otherwise, if the destination's civil timezone is resolved (Section 18), assume the camera clock tracked that local time and propose `offset = -(timezone UTC offset)` at the bucket's earliest naive instant, DST-aware (Section 19.4). `proposal_source: "timezone_naive"`, confirmable-only (the local-clock assumption can be wrong — e.g. a camera left on home time), never auto-applied;
   - **(c) manual-required** — otherwise (no self-anchor, no resolved timezone), a blank manual field.

   There is **no inheritance step** — a bucket is resolved entirely from its own date's evidence or the destination timezone. A manual offset entered on one bucket applies only to that day; sibling date buckets are untouched. This honors "corrections between destinations, never within" (Section 7) refined to the day: within one day the offset is one constant, across days it is re-derived. The **only** offset auto-resolution is a GPX self-anchor under the Section 9.1 policy flags; timezone-derived and manual buckets are always confirmable;
5. camera-group **identity and classification** (camera vs smartphone) remain group-scoped config (Section 16). A cell may surface `camera_group_class` read-only to explain why it needs (camera) or does not need (smartphone solved from its own metadata) a clock-offset decision; the editable offset itself is per (group, destination[, date]);
6. resolved UTC for a file uses its **(camera group, destination, date) effective offset** — selecting the file's own naive-date bucket, falling back to the bare-group bucket for a single-day destination — together with its **destination effective timezone**. A file is fully solvable only when **both** are complete.

A **timezone-derived** proposal (rule 4b) is the no-anchor default — e.g. a `…/Kyoto/Kinkaku-ji` day with no native-GPS frame, deriving its offset from Kyoto's resolved `Asia/Tokyo`:

```json
{
  "camera_group": "sony_a6400_serial_123456",
  "camera_group_class": "camera",
  "date": "2024-04-07",
  "proposal": {
    "proposed_offset_seconds": -32400,
    "proposal_source": "timezone_naive",
    "proposed_real_utc": "2024-04-07T03:12:08Z",
    "proposed_from_timezone": "Asia/Tokyo",
    "confidence": "review_required",
    "rank": "timezone_derived"
  },
  "user_decision": { "accept_proposal": false, "manual_offset_seconds": "" },
  "effective_time_anchor": "",
  "requires_user_input": true
}
```

If the user instead types a `manual_offset_seconds` here, that becomes this bucket's effective offset for that day only.

All numbered calibration JSON artifacts are destination-grouped (Section 10.3); the time decisions are no exception — they sit inside their destination's section like everything else.

### 10.3 Per-destination grouping (default)

All numbered calibration JSON artifacts cover destinations separately — including the time decisions, which (since Section 10.2) now sit inside each destination's section rather than in a separate top-level block.

This applies to:

```text
photos-21-time-decisions.json   (destination sections; each carries its timezone + per-group time decisions)
photos-22-gps-decisions.json
photos-23-executable-plan.json
```

Each artifact should be grouped by destination under `6-photos-by-dest`.

Example shape:

```json
{
  "artifact_type": "time_decisions",
  "artifact_name": "photos-21-time-decisions.json",
  "destinations": {
    "6-photos-by-dest/Belgium/Brussels": {
      "destination_id": "...",
      "destination_path": "6-photos-by-dest/Belgium/Brussels",
      "destination_timezone": { "...": "Section 18" },
      "camera_groups_present": ["sony_a6400_serial_123456"],
      "camera_group_time_decisions": { "sony_a6400_serial_123456": { "...": "see Section 10.2" } },
      "status": "...",
      "depends_on": {}
    },
    "6-photos-by-dest/Japan/Kyoto": {
      "destination_id": "...",
      "destination_path": "6-photos-by-dest/Japan/Kyoto",
      "destination_timezone": { "...": "Section 18" },
      "camera_groups_present": ["sony_a6400_serial_123456"],
      "camera_group_time_decisions": { "sony_a6400_serial_123456": { "...": "independent offset; see Section 10.2" } },
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

The workspace lock is acquired at process startup, before preflight (shared contract `photos-shared-contract.md` Section 2); if another pipeline run holds it, calibration exits fail-fast without scanning, planning, or writing anything. Immediately after, calibration applies the same startup guards every script does (shared contract Section 13.7; prep Section 6.2):

- **Sealed workspace → hard-stop, sealed means sealed.** If a **terminal/sealed marker** from a prior successful merge is present (shared contract Section 13.7), calibration **hard-stops immediately, mutating nothing and touching nothing**, and directs the user to a fresh workspace — a merged workspace is done. There is no recovery utility. If files are seen at the **workspace root** or in **`0-sources`**, calibration additionally warns that a likely new dump was detected and that, because this workspace is sealed, the dump must be moved into a **fresh workspace** by hand; it leaves the dump exactly where it is.
- **Uninitialized → run prep first.** If the workspace has no root sentinel `photos-00-workspace-guard` (it was never initialized, shared contract Section 5; prep Section 3.1), calibration hard-stops with "not an initialized workspace — run prep first" (only prep's init path consumes an as-arrived dump).
- **Misplaced entry at the workspace root → hard-stop (strict).** On an initialized workspace the base must hold only the managed folders and control/dot directories; any misplaced root entry blocks — a **loose file** (dotfiles included), a **non-managed folder** (a stray dump folder belongs *inside* `0-sources`, not loose at the base), or a **symlink** (barred outright rather than followed, since following it would escape the workspace). Dumps belong in `0-sources` (shared contract Section 5.3; prep Section 6.2 items 2–3). Calibration matches prep here so a misplaced dump is caught no matter which phase the operator runs next.
- **Incomplete managed folder structure → hard-stop.** If any of the managed `0`–`6` folders is missing on an initialized workspace, the structure was disturbed out-of-band; calibration hard-stops and directs the operator to restore it and re-run prep, rather than proceeding against a damaged workspace (shared contract Section 5.3; prep Section 6.2 item 7). Folder creation is prep's init-only job; calibration never creates or repairs the structure.

Otherwise, the first workflow action is always preflight validation.

The workflow must:

1. load the available `photos-1-prep` handoff and SQLite cache state;
2. verify that `5-photos-by-date/` contains no photos, **and that `0-sources/` is empty** — prep leaves `0-sources` empty at the end of every run (prep Sections 7.6, 18), so a non-empty `0-sources` means an un-processed dump is waiting; calibration hard-stops directing the user to re-run prep. (Residuals in `1-strays`, `2-missing-metadata`, `3-redundant-jpgs`, and `4-videos-by-date` are tolerated and do not block.);
3. verify that no `destination_distribution_subfolders` (jpg/tif) exist under `6-photos-by-dest` and hard-stop if development has started (Section 7.1);
4. verify that `6-photos-by-dest` contains only photo files and hard-stop on any non-photo file — `other`-class non-media or `video`-class — found under it (Sections 7.2, 7.3);
5. identify files under `6-photos-by-dest`;
6. detect by-dest media not yet recorded by prep (and/or handoff by-date files now missing) and hard-stop with the targeted "re-run prep" blocker if found (Section 13.1);
7. validate whether the prep/cache state for by-dest files is current;
8. block before producing calibration JSON artifacts if the prep/cache state is stale, missing, incomplete, or unverifiable.

The workflow must validate that:

1. the workspace config `photos-00-config.json` exists and is read as the authoritative configuration (seeded by prep; shared contract `photos-shared-contract.md` Section 4), with its field-scoped fingerprints used for staleness and its whole-file SHA-256 available for provenance;
2. the prep handoff exists and its recomputed `content_fingerprint` matches the value recorded wherever it is depended upon (Section 4; prep Section 16.2);
3. the SQLite schema and cache versions are acceptable **as established via the handoff** — calibration reads the handoff's recorded cache/field-set fingerprints (Section 4; prep Section 16.2) rather than opening and inspecting prep's database directly to check schema/cache versions;
4. expected by-dest media files still exist;
5. size/mtime/fingerprint preconditions are current;
6. the metadata field-set version is acceptable;
7. prep handoff dependencies are still current;
8. by-dest SQLite records are current.

If validation fails, the workflow prints a textual stale-state report and produces no JSON artifact.

Separately from staleness, every human-authored value calibration consumes — the config it reads and the decision fields it loads — is **sanity-validated before use** (Section 9.2; shared contract `photos-shared-contract.md` Section 14). An invalid value (e.g. a non-resolvable timezone, an out-of-range coordinate, a malformed `zfs` snapshot prefix, or a structurally broken decision object) is a hard blocker located to the offending field; calibration produces no downstream artifact and mutates nothing until the user fixes it. Validation detects invalid *content*; the dependency cascade detects *change* — both run.

Example:

```text
Calibration cannot proceed.
Reason: by-dest cache records are stale.
Next action: rerun photos-1-prep for cache refresh / prep completion.
No calibration JSON was written.
```

### 13.1 Calibration requires a prep run after the latest by-date → by-dest move

Prep recognizes a user's by-date → by-dest move and folds it into the handoff/cache only on its *next run* (prep `photos-1-prep-workflow.md` Section 10.1). Calibration consumes the handoff and operates on by-dest. Therefore:

**A prep run must occur after the most recent by-date → by-dest move, before calibration runs.** This is a hard contract requirement, not merely advisory. The intended sequence is *move → re-run prep (move recognition) → calibrate* (shared contract `photos-shared-contract.md` Section 10). A handoff that predates the latest move does not describe the by-dest set calibration sees, so calibrating against it is unsafe.

This requirement is largely self-enforcing through the validations above: a stale handoff fails the content-fingerprint/cache checks, and moved files break the "expected by-dest media files still exist" and "by-dest SQLite records are current" checks. But calibration must detect this specific situation and report it **as a targeted, actionable blocker** rather than as a generic hash mismatch or opaque stale-cache message, because the precise fix (re-run prep) differs from other staleness causes.

Detection (cache/handoff vs. filesystem, `stat`-level, no media re-read):

1. one or more media files exist under `6-photos-by-dest` that the handoff/cache does not record at their current by-dest path (unrecorded by-dest media); and/or
2. one or more photos the handoff records under `5-photos-by-date` are now missing from there (consistent with having been moved into by-dest). (Videos in `4-videos-by-date` are not part of this check — they are never moved into by-dest, Section 7.3.)

When either condition holds, calibration hard-stops before creating any calibration JSON artifact and emits the targeted blocker:

```text
Calibration cannot proceed.

Reason:
6-photos-by-dest contains photos that prep has not yet recorded
(the handoff predates your most recent move from by-date into by-dest).

Next action:
Re-run photos-1-prep. It will recognize the moved files (no re-fingerprint,
no re-read) and refresh the handoff/cache, then calibration can proceed.

No calibration JSON was written.
```

Calibration never performs the move recognition itself and never writes to the cache, handoff, or by-dest to "fix" this — recognizing moves and refreshing the handoff is prep's responsibility alone (prep Section 10.1). Calibration's only action is to detect the gap and direct the user to re-run prep.

---

## 14. Stage 2 — Create in-memory by-dest file objects

After preflight passes, the workflow creates in-memory file objects for files under `6-photos-by-dest` only.

Each file object should represent facts such as:

1. workspace-relative path;
2. destination path;
3. file size;
4. mtime;
5. content fingerprint, if available;
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

The two statements above describe *why* the GPX fingerprint matters. In practice the implementation records the current GPX fingerprint as a dependency **unconditionally whenever a GPX set is loaded** — even for an artifact (or destination) that ended up using no GPX evidence — rather than tracking per-artifact whether GPX actually contributed. This is a deliberate, conservative over-inclusion (Section 22.1): editing the GPX set may restale an artifact that did not depend on GPX, which only costs a recompute and never serves a stale result. If GPX is wholly unavailable or disabled, there is no fingerprint to record and these dependencies are simply absent.

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
6. for each camera group present, whether **this destination's** clock-offset decision for that group is needed and whether it can be auto-anchored or needs manual input (Section 10.2) — a *camera* group needs a per-(group, destination) offset; a *smartphone* group is solved per file from its own metadata and needs no offset cell;
7. whether GPX/native-GPS time-anchor proposals are available **for that (group, destination)** — i.e. whether that group has native-GPS frames *in this destination* to anchor from;
8. whether blockers remain.

For each camera group **present in the destination**, the workflow determines whether that destination's time can be solved from:

1. trustworthy native UTC timestamps;
2. mobile-device timestamps with reliable timezone/offset metadata (smartphone groups; no per-destination offset needed);
3. existing user calibration rules;
4. a manual fixed UTC offset for this (group, destination);
5. manual time segments;
6. GPX/native-GPS time-anchor proposals anchored from that group's native-GPS frames in this destination (Section 19);
7. other explicitly supported calibration evidence.

A camera group present in a destination with **no** anchorable native-GPS frame *for a given day* is not self-solved for that day's bucket; the bucket instead takes a **timezone-derived** proposal from the destination's resolved civil timezone (Section 10.2 rule 4b, Section 19.4), and falls to a blank manual field only if the timezone is unresolved too. Offsets are **not** inherited from ancestor destinations. The destination's **civil timezone**, by contrast, *does* inherit: a destination with no timezone of its own takes its nearest ancestor destination's effective timezone as a confirmable proposal (Section 18), seeding downward from a trip's root — so the timezone cascades, while each day's offset is re-derived locally.

Once this analysis is complete, the workflow has reached the formal time-decision stage.

At that point, it must create:

```text
photos-21-time-decisions.json
```

even if no user input is required.

---

## 18. Destination civil timezone decision

`photos-21-time-decisions.json` must settle the civil timezone for every destination under `6-photos-by-dest`.

The destination civil timezone is used to:

1. interpret local/civil destination context;
2. convert resolved UTC to destination-local civil time;
3. plan timestamp-based no-clobber renames;
4. produce filename timestamp components.

The artifact must include, for each destination, pre-created human decision fields.

Example shape:

```json
{
  "destination_path": "6-photos-by-dest/Belgium/Brussels",
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

If destination timezone is unknown or ambiguous **and no ancestor destination supplies one and no configured default applies** (see the priority order below), the artifact must contain an empty manual override field and mark the destination as requiring user input.

Resolved UTC must not be finalized for files in a destination whose timezone/time dependencies are incomplete.

**Downward inheritance of the timezone proposal.** A destination whose timezone cannot be proposed on its own evidence **does not start from a blank field — it inherits, downward, as a confirmable proposal**, reusing the **same nearest-ancestor machinery** as the folder GPS fallback (Section 25.3). (The per-(camera group, destination) clock offset does **not** inherit — Section 10.2 rule 4 — so the timezone and the fallback are the only two facts that cascade down the destination tree.) The `proposed_iana_timezone` for a destination is chosen in priority order:

1. **(a) self-proposed** — a timezone derived from **this destination's own evidence** (a native-GPS/GPX-derived zone), with the corresponding `proposal_source`. *(Not yet implemented: the code currently has no GPS-derived zone, so in practice the chain starts at (b).)*
2. **(b) inherited** — otherwise, the destination takes the **effective timezone of the nearest ancestor destination** that has one, surfaced as a **proposal to confirm**, with `proposal_source: "inherited"` and an `inherited_from` field naming the ancestor path;
3. **(c) config default** — otherwise, the configured global **`default_folder_timezone`** is the proposal (`proposal_source: "config_default"`). The configured default is a **global fallback, not per-destination evidence**, so it sits **below** inheritance: a nested destination prefers its nearest ancestor's confirmed timezone over the blunt global default, and only falls to the global default when no ancestor supplies one. (Putting the default above inheritance would make inheritance unreachable whenever a default is set, and would contradict the fallback model and Section 17.)
4. **else** — no self-proposal, no ancestor timezone, and no configured default: the manual field starts blank and the destination is marked `requires_user_input`.

Inheritance is **recursive down the destination tree**: a destination's *effective* timezone — however it was reached (self-proposed-and-accepted, inherited-and-confirmed, or manually set) — is the basis propagated to its immediate children, and onward. A **manual timezone set at a folder re-roots the chain** at that point: that zone becomes the folder's effective timezone and therefore the basis its descendants inherit. To compute this, destinations are processed **parent-first** (the same ordering the fallback inheritance uses), so an ancestor's effective timezone is known before any child that would inherit it is built; inheritance flows **parent → child only**, never sibling → sibling.

An inherited timezone proposal is **confirmable, never auto-applied**. As a non-anchor proposal class (Section 9.1 item 2), it keeps `requires_user_input: true` by default — there is no timezone auto-accept policy. Propagation is therefore the operator accepting a sensible default at each level (a single `accept_proposed_timezone: true`, or a manual override), never a hidden cross-destination borrow: every level is confirmable and any level can diverge. The exception is a **file-less container** destination (Section 10.1): with no photos to mis-tag, its timezone **auto-resolves** from the nearest-ancestor (or config-default) proposal (`decision_mode: "auto_resolved"`, `requires_user_input: false`) rather than requiring an accept, and remains overridable by a manual zone. An inherited proposal looks like a self-proposed one but names its source ancestor:

```json
{
  "destination_path": "6-photos-by-dest/Belgium/Brussels/Grand-Place",
  "destination_timezone": {
    "proposed_iana_timezone": "Europe/Brussels",
    "proposal_source": "inherited",
    "inherited_from": "6-photos-by-dest/Belgium/Brussels",
    "proposal_confidence": "review_required",
    "user_decision": { "manual_iana_timezone": "", "accept_proposed_timezone": false },
    "effective_iana_timezone": "",
    "requires_user_input": true,
    "stale_user_decision": false
  }
}
```

### 18.1 Re-evaluation when a file is moved between destinations

A file's destination is an input to its time decision: the destination civil timezone, **the clock offset that applies to it (now per (camera group, destination), Section 10.2)**, and downstream the resolved UTC and the local-time rename. If the user re-sorts a file from one destination to another inside `6-photos-by-dest` (e.g. fixing a mis-sort), prep recognizes the move and updates the handoff to record the new destination (prep `photos-1-prep-workflow.md` Section 10.2). On the next calibration run this changes the handoff, which — through the dependency cascade (Section 30; shared contract Section 9) — restales the affected destinations' per-file decisions for that file, so calibration **re-evaluates** it under its **new** destination: it applies the new destination's effective timezone **and the new destination's (group) clock offset**, recomputes resolved UTC and the local-time rename accordingly, and never silently carries the old destination's timezone or offset onto a file that now lives elsewhere. The new destination's effective timezone may itself be an **inherited** one (proposed from its nearest ancestor and confirmed, Section 18); the moved file simply takes whatever that destination's effective timezone is. Because the offset is anchored from each destination's own native-GPS frames, moving a file may also change the *anchoring evidence* in both the source and target destinations — both cells are re-evaluated.

Decisions that are genuinely destination-scoped (each destination's timezone and its per-group offset) are unaffected for files that did not move; only the moved file is re-evaluated, and only against its new destination. As always, the mandatory re-prep after the move applies (shared contract Section 10) so calibration sees the move at all.

---

## 19. GPX/native-GPS time-anchor proposals

This stage is part of time calibration, not GPS interpolation.

It is used when:

1. GPX data is available;
2. a camera group has at least one file with native GPS **in a given destination**;
3. that native GPS position matches a GPX point or a short GPX segment under configured thresholds.

The purpose is to propose a real UTC timestamp for a photo whose camera clock may be wrong.

This produces a proposed camera-time calibration for that **(camera group, destination)** — not for the whole camera group. Because the camera's clock error varies between destinations (it drifts, and may be reset, between trips, Section 10.2), the offset is anchored **only from that group's native-GPS frames in that destination** and the resulting decision is **destination-scoped**: it is recorded inside that destination's section, keyed by `camera_group_key` (Section 10.2), not shared across the destinations the group appears in. The user accepts or overrides it per destination. The same camera appearing in two destinations yields two independent proposals, each anchored from its own destination's frames, and within a destination it splits per naive date (Section 10.2 rule 4). A bucket with **no** native-GPS frame of its own produces no self-anchor here; instead of a blank field it takes a timezone-derived proposal when the destination timezone is resolved (Section 19.4), else manual-required. Offsets are never inherited from an ancestor destination.

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

**Plausible-clock-error window (eligibility).** A candidate anchors a frame only if its GPX timestamp is within a configured window (`gpx_anchor_max_clock_error_seconds`, default 2 days) of the frame's naive capture time read as UTC. This is applied *during* the spatial search, so a track that merely passes through the **same place on a different trip** — e.g. the same spot years earlier — is skipped even when it is the spatially closest point, instead of winning on distance and yielding an absurd multi-year "offset". The window is deliberately wide (it must cover whatever timezone the camera clock was set to, ±14 h, plus drift) yet far below the gap to any realistic prior visit; a genuinely huge clock error (a battery-reset clock) falls outside it and is left to a manual offset. It is **timezone-independent on purpose**: the offset already folds in whatever timezone the camera clock was set to, which is *not* necessarily the destination's civil timezone (a camera left on home time while travelling), so the destination timezone must **not** be used to bound matching.

### 19.2 Ranking, not averaging

If multiple native-GPS/GPX time-anchor candidates exist for the same **(camera group, destination)**, the workflow must not average them.

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

**Consensus over a lone closest match.** Because a camera's clock error is essentially constant across a destination, the eligible candidates' offsets are clustered (within `gpx_anchor_offset_spread_max_seconds`) and the **largest agreeing cluster wins** — the recommended offset is that cluster's best-ranked member, with point-before-segment then closest as the *within-cluster* tiebreak. This keeps a single spurious match from outvoting the crowd: candidates inside the chosen cluster are the supporting evidence, those outside are the conflicting evidence. The proposal also carries, for the editor's collapsed view, a `groups` summary (each cluster's offset, its photo **count**, and one **representative** photo named by its full by-dest relative path, with that photo's GPX-derived real-UTC so the editor can show its corrected local time) and a `skipped` summary (frames that produced no in-window match, split into `outside_time_window` — a track only from another trip — vs `no_nearby_track`), so the operator sees a few grouped proposals instead of every anchor.

### 19.3 Human decision fields for time-anchor proposals

Each proposed anchor should include generated proposal fields and pre-created user decision fields.

Example shape:

```json
{
  "proposal_id": "anchor-001",
  "source_file": "6-photos-by-dest/Belgium/Brussels/DSC01234.ARW",
  "destination": "6-photos-by-dest/Belgium/Brussels",
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
    "proposed_offset_seconds": -7187,
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

The proposal is anchored only from native-GPS frames of this `camera_group` within this `destination`, and its accepted/effective offset is recorded in that destination's `camera_group_time_decisions[camera_group]` cell (Section 10.2) — it does not affect the same group in any other destination. The user fills existing fields only.

### 19.4 Timezone-derived offset (no anchor)

When a `(camera group, destination, date)` bucket has **no** GPX self-anchor (Section 19.1) but the destination's **civil timezone is resolved** (Section 18), calibration proposes an offset by assuming the camera clock was set to that local time:

```text
offset = -(civil timezone's UTC offset at the bucket's earliest naive instant)
```

computed DST-aware via `zoneinfo` — so a destination revisited in summer and winter yields the summer or winter offset **per day bucket** (Section 10.2 rule 4), each derived from its own date's local instant. The proposal carries `proposal_source: "timezone_naive"`, the chosen `proposed_offset_seconds`, a `proposed_real_utc`, and `proposed_from_timezone`. It is **confirmable-only** (`confidence: review_required`, never auto-applied) because the local-clock assumption can be wrong — a camera left on home time gives a wrong offset — so the operator reviews it like any non-anchor proposal. It ranks directly **above** manual-required (there is no inherited offset — offsets do not cascade). It needs the timezone first, so the operator resolves the destination timezone and re-runs to obtain it; until then the bucket is `manual_required` and the editor says so.

---

## 20. Create `photos-21-time-decisions.json`

Once the time-decision stage is reached, the workflow must create:

```text
photos-21-time-decisions.json
```

This artifact exists even if no user input is required.

It is grouped by destination; each destination section carries its timezone decision and one time decision per camera group present (per (group, destination), Section 10.2). There is no separate top-level group-scoped block.

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
2. camera groups requiring time calibration, **per (group, destination)** inside each destination section (Section 10.2);
3. GPX/native-GPS time-anchor proposals (recorded against the camera group **within its destination**, Section 19);
4. manual fixed-offset fields (per (group, destination), used when a cell has no anchorable native-GPS frame);
5. manual segment templates (per (group, destination));
6. explicit accept/reject fields for proposed time anchors (per (group, destination));
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
time_decision_scope        (the (camera_group, destination_path) pair this file's offset came from)
source_naive_time
source_time_provenance
time_rule_used
utc_offset_used            (the effective offset for this file's (camera_group, destination))
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
2. the input fingerprints that produced those rows: the **time-policy fingerprint** (a SHA-256 over just the `camera_time_and_timezone_policy` config area — *not* the whole-config hash), the camera-group-key version, `photos-21-time-decisions.json` SHA-256, the prep cache fingerprint, the metadata field-set version, and the **GPX fingerprint**. The GPX fingerprint is included **unconditionally** — a deliberate, conservative over-inclusion: even a destination whose UTC was resolved entirely without GPX (e.g. from native EXIF plus a manual offset) still carries the current GPX fingerprint, so editing the GPX set conservatively restales resolved UTC even where GPX had no effect on the result. This errs toward re-resolving rather than risk serving a stale value, and the cost is bounded (resolved UTC is recomputed, not the expensive media work).

The config input is deliberately the **time-policy subset**, not the whole-config file hash, so resolved-UTC staleness stays **surgical** (shared contract `photos-shared-contract.md` Section 4.2): a config edit *outside* the time policy — for example to `library_root`, the GPX matching thresholds, the filename format, or the `zfs` block — must **not** restale already-resolved UTC, because none of those affect how UTC is computed. Only a change to the time policy (or to one of the other listed inputs) restales it. The whole-config SHA-256 still appears as `config_fingerprint` in the **executable plan's** (`photos-23`) `depends_on` for end-to-end **integrity and change-detection** (it is the byte hash the dependency cascade re-verifies, shared contract Section 9), but it is **not** the resolved-UTC staleness trigger — the two roles are kept distinct exactly as Section 4.2 prescribes (field-scoped fingerprints drive staleness; the whole-file hash is for integrity, not staleness). The decision artifacts (`photos-21`/`photos-22`) deliberately carry only their **field-scoped** policy fingerprints (the time-policy / GPS-policy subsets), not the whole-file hash, so an unrelated config edit cannot needlessly restale them; the whole-file integrity hash enters the cascade once, at the plan, which is the artifact `execute` revalidates.

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
6. folder fallback rules — the per-destination folder GPS fallback, inherited downward from the nearest ancestor as a confirmable proposal (Section 25.3);
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

The mechanism is a **pre-state ledger** in SQLite, archived with the database (shared contract `photos-shared-contract.md` Section 13.4):

1. **Capture on first application.** The first time a manual GPS decision causes the executor to write GPS to a file, it captures that file's GPS EXIF *as it was immediately before the write* and pins it in the ledger, keyed by content fingerprint. The captured pre-state is one of:
   - the **previous GPS coordinates** (and related GPS fields) that were present, or
   - an explicit **"absent" sentinel** meaning the file had no GPS before the override.
   This pinned value is the **true original**: it is written once and never overwritten by subsequent runs of the same or a changed decision, so it always represents the state before the pipeline first touched the file's GPS via a manual decision.

   **The "previous coordinates present" pre-state is a completeness case, intentionally unreachable via `apply_manual`.** A manual override (locked or fallback) is only ever *selected* for a file that has **no native GPS**: `classify_gps` returns `preserve_native` for any file that already carries native GPS **before** it ever consults the manual coordinates (Section 23 resolution order; Section 25.3 — preserve-native wins). So an `apply_manual` operation never targets a file whose GPS field was occupied, and the pre-state captured on first application is therefore **always the "absent" sentinel**, never a set of previous coordinates. The crucial corollary: if a file *did* already hold GPS — including the case where a manual coordinate written on an earlier run has since been **re-folded into the file's native EXIF** (e.g. the file was re-imported with that GPS baked in) — it now **reads as native GPS and is preserved, not overridden**, so it is never an `apply_manual` target in the first place. The "previous GPS coordinates were present" branch above is thus kept only for **completeness and robustness** (it keeps the ledger correct should that precedence ever be relaxed); under the current rules the ledger only ever pins, and reverts to, "absent" — withdrawal *clears* the GPS the override added rather than restoring a prior coordinate. Consistent with this, the pinned pre-state is the GPS value **prep recorded in its scan/handoff** (which the executor pins before the write), not a fresh execute-time re-read — for a file with no native GPS the two coincide at "absent."

2. **Withdraw → restore.** If, before a later run, the user **removes** the manual GPS decision, the next run's plan must include an explicit **revert operation** that drives the field back to the pinned pre-state: write the previous coordinates back, or — if the pre-state was "absent" — **clear** the GPS the override added. Withdrawal therefore *undoes*; it does not merely stop re-asserting. ("Tag a file that had no GPS, then withdraw" correctly leaves the file with no GPS, not with the tagged value.)

3. **Change → overwrite, original stays pinned.** If the user **changes** the manual GPS to a new value, the executor overwrites to the new value; the pinned pre-state is unchanged, so a later full withdrawal still restores the true original.

4. **Once restored, the ledger entry is consumed.** After a withdrawal has restored the pre-state of a file that still exists, the override is gone and the file is back to original; a subsequent fresh manual decision on the same file pins the (now original) pre-state again on its first application. (This consume-on-restore applies only to files still present; an entry for a file that has disappeared is kept — item 5.)

5. **A disappeared file's entry is kept for reference.** If a file that has a pre-state ledger entry no longer exists at the next run (deleted, or removed from the workspace), prep/calibration must **not** prune its ledger entry. The pinned pre-state is retained as a historical record — it documents that the pipeline once overrode that file's GPS and what the original was — keyed by the content fingerprint that identified it. A retained entry for an absent file triggers no operation (there is nothing to revert), and it is carried into the archived `photos-00-ingest.db`. Keeping it preserves the "every change is explainable from the record" guarantee (shared contract Section 12) even for files that later left the workspace; the cost (a few stale rows) is accepted in exchange for never silently dropping evidence of a past mutation.

6. **The ledger is per-workspace.** The pre-state ledger lives in that workspace's `photos-00-ingest.db` and is meaningful only within it. If a workspace is finalized and torn down and the same photos are later re-imported into a **fresh** workspace, the new workspace starts with no ledger: a manual GPS override there pins whatever GPS the files *now* carry (i.e. the previously-applied value) as that workspace's "original." This is intended and correct — within any one workspace, "original" means the state before that workspace first touched the field. The archived `photos-00-ingest.db` (shared contract Section 13.4) preserves the original ledger as a historical record of the finalized workspace; it is not auto-merged into a new workspace's live ledger. Reversibility is therefore a within-workspace guarantee, not a cross-workspace one — consistent with the workspace being transient and decisions being re-authored per workspace.

**Manual vs. automated is the dividing line.** Two GPS writes can target the same field, but only the manual override is reversible:

- **Manual GPS** (locked or fallback, authored by the user) — reversible via the pinned pre-state as above.
- **Automated GPS** (GPX interpolation/extrapolation, preserved native GPS) — **not** rolled back. Withdrawing or invalidating an automated decision simply means it is not re-derived; the field is recomputed from current inputs and whatever recomputation yields is written. No pre-state is stored for automated values, and no revert operation is emitted for them. This must be explicit in the plan: a revert operation exists *only* for a withdrawn manual GPS override.

**Time and filename are never reverted.** Resolved UTC and the destination-local filename position the file *within its destination*. They are always **recomputed** to match current decisions, never rolled back to a pre-pipeline value — reverting them would un-position an already-organized file, which is meaningless. Recomputation only rewrites the timestamp metadata and the filename **in place within `6-photos-by-dest`**; it never moves the file to a different destination or anywhere else in the tree — the file stays in the destination folder the user placed it in. So: GPS manual overrides are reversible from stored pre-state; time and naming are recomputed in place within by-dest; automated GPS is overwritten by recomputation.

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
  "destination_path": "6-photos-by-dest/Belgium/Brussels",
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

### 25.3 Per-destination folder GPS fallback (downward inheritance)

The **folder GPS fallback** is a per-destination decision that supplies a single coordinate to place any photo in that destination which has no native GPS, no per-file manual lock, and no usable GPX match. In the resolution order calibration applies, it ranks **after** preserve-native, the per-file manual lock, and GPX interpolation/extrapolation, and **before** accept-unlocated or block (the seven GPS outcomes of Section 23). It is the destination-level analogue of the per-(camera group, destination) clock offset (Section 10.2): a destination-scoped value that a nested subfolder does not have to re-author from scratch.

Its decision cell lives **inside each per-destination section** of `photos-22-gps-decisions.json` (alongside that destination's `gps_decisions` summary), with pre-created human-decision fields exactly like every other decision (Section 9). It carries a machine `proposal`, a `user_decision` the operator fills, and a derived `effective_fallback`:

```json
{
  "destination_path": "6-photos-by-dest/Japan/Kyoto/Kinkaku-ji",
  "folder_fallback": {
    "proposal": {
      "proposal_source": "inherited",
      "proposed_fallback": { "lat": 35.0394, "lon": 135.7292 },
      "inherited_from": "6-photos-by-dest/Japan/Kyoto"
    },
    "user_decision": { "fallback_lat": "", "fallback_lon": "", "accept_proposal": false },
    "effective_fallback": null,
    "requires_user_input": false,
    "stale_user_decision": false
  },
  "gps_decisions": { "...": "Section 25" }
}
```

The fallback proposal is chosen by **downward inheritance**, mirroring the clock-offset rule of Section 10.2 rule 4 (and reusing the same nearest-ancestor walk):

1. **(a) inherited** — if a **nearest ancestor destination** has a resolved effective fallback, this cell's proposal is that ancestor's fallback, surfaced as a **proposal to confirm** and labelled with the `inherited_from` ancestor path. Inheritance is **recursive down the destination tree**: a destination's *effective* fallback — however it was reached, whether authored here or inherited-and-accepted — is the basis propagated to its immediate children, and onward to grandchildren. A **fallback authored at a folder resets the chain** at that point: that coordinate becomes the folder's effective fallback and therefore the basis its descendants inherit, replacing whatever would have flowed down from further up.
2. **(b) manual-required** — otherwise (no ancestor has a fallback), the proposal is `manual_required` and the manual coordinate fields start blank.

To compute inheritance correctly, destinations are processed **parent-first**, so an ancestor's effective fallback is known before any child cell that would inherit it is built — the same ordering the clock-offset inheritance uses (Section 10.2). Inheritance flows **parent → child only** (never sibling → sibling). A **file-less container** destination (Section 10.1) carries a `folder_fallback` cell for exactly this purpose — to seed its children — even though it holds no media itself; like every fallback cell it never blocks (`requires_user_input: false`), so a coordinate authored on a container simply becomes the effective fallback its descendants inherit.

The cell resolves its `effective_fallback` during validation:

1. if the operator fills `fallback_lat`/`fallback_lon` with an in-range coordinate (latitude −90…90, longitude −180…180, Section 9.2), that authored coordinate is the effective fallback (and re-roots inheritance for descendants);
2. else if the operator sets `accept_proposal: true` and the proposal is `inherited`, the inherited coordinate becomes the effective fallback;
3. else the effective fallback is **absent** (`null`).

The fallback is **optional and never blocks**: a destination with no effective fallback is fine — its un-located photos simply fall through to the remaining Section 23 options (accept-unlocated if the operator marked the file so, otherwise a per-file blocker). Accordingly the cell's `requires_user_input` is always `false`; the inherited proposal is a convenience the operator *may* validate, not a gate. An authored coordinate that is out of range is a validation blocker located to the destination's `folder_fallback` (Section 9.2), preserved and flagged rather than silently dropped; accepting a proposal that no longer exists marks the cell `stale_user_decision` rather than failing.

A file placed from the effective folder fallback is a **manual** GPS placement (origin *apply manual*, marker `manual_fallback`), so it is reversible via the pre-state ledger exactly like a per-file manual lock (Section 24.1) — withdrawing the destination's fallback (or moving the file out of a destination that had one) restores the file's pinned pre-state. In the `photos-22` per-destination summary it is counted under `automatic_folder_fallback`; the exact per-file write is re-derived in `photos-23-executable-plan.json` from the resolved inputs (the effective fallback among them), never read from the summary (Section 25).

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

The default timestamp format is supplied by the shared, phase-neutral config key `filename_timestamp_format` (in the workspace config `photos-00-config.json`, default `%Y-%m-%d--%H-%M-%S`), defined authoritatively in the shared contract (`photos-shared-contract.md` Sections 4 and 7). The same key is read by prep from the same file, so the format is never hard-coded and cannot drift between phases; its value feeds the filename-format dependency fingerprint. (The name `calibration_filename_timestamp_format` used elsewhere historically is an alias for this shared key — see shared contract Section 7.1.)

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
11. media file size/mtime/fingerprint preconditions are current.

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
6. `photos-11-handoff.json` path and its `content_fingerprint` (the content-scoped staleness key, not a whole-file byte hash, Section 4; prep Section 16.2);
7. prep SQLite cache fingerprint;
8. GPX fingerprint (recorded unconditionally where a GPX set is loaded — a conservative over-inclusion, Sections 15, 22.1);
9. media file preconditions;
10. metadata field-set version;
11. filename-format config fingerprint;
12. planned operation fingerprint.

---

## 29. Stage 10 — Execution

The entire calibration run — every pass of the convergent rerun loop (Section 2.1), including preflight, planning, and execution — runs under the single workspace-wide lock acquired at process startup and held until exit (shared contract `photos-shared-contract.md` Section 2). No two pipeline processes of any phase ever overlap. The execution steps below assume the lock is already held; they do not re-acquire or independently scope it.

Execution applies only the already-planned metadata and rename operations.

Execution must:

1. load `photos-23-executable-plan.json`;
2. re-hash all named JSON artifact dependencies using SHA-256;
3. validate all non-JSON upstream dependencies;
4. reject stale plans before mutation;
5. confirm the workspace lock is held (acquired at run start per shared contract Section 2);
6. take a pre-mutation snapshot where configured, reusing the **same optional ZFS snapshot mechanism prep uses** (the `zfs` block in the workspace config `photos-00-config.json`, keyed by plan id; shared contract `photos-shared-contract.md` Section 3), and honoring the same `snapshots_required` semantics (abort before any mutation if a required snapshot fails, and carry the snapshot record into `photos-24` either way). Snapshots are **strictly optional** — disabled by default and never a prerequisite for the safety model, which rests on the plan/validate/execute discipline, the journal, no-clobber, and the pre-state ledger (shared contract Section 3); they add a clean-slate rollback path for operators on ZFS. The snapshot is **labelled for its phase** (e.g. a `calibrate` label distinct from prep's) so that, even on a dataset shared with prep, calibration's pre-mutation snapshot never collides in name with a prep snapshot for the same plan id;
7. apply only planned operations, each re-verified no-clobber **at execute time** and performed atomically (Section 29.1a; shared contract `photos-shared-contract.md` Section 15): immediately before each rename, confirm the target name is not already occupied (case-insensitively where applicable) rather than trusting the plan's suffix allocation, and apply the rename as a single atomic filesystem operation; metadata writes are applied atomically (write-and-atomic-rename or safe-write mode). Per-file operations may be applied **concurrently** under `-j`/`--jobs` without changing semantic results (Section 29.3). An unexpectedly occupied rename target at execute time is a blocker, never a clobber;
8. after each file's metadata write, **verify the photo's decoded-content fingerprint is unchanged** before treating the write as applied — the integrity check of Section 29.1a item 5: an `identify` pixel fingerprint must be invariant under an EXIF/GPS write (prep Section 9), so a mismatch means the write altered pixels and the operation is held back (no confirm, no dependent rename) and recorded for review, not silently accepted;
9. journal every metadata write, marker write, file move, or rename;
10. update SQLite/cache after successful writes;
11. write `photos-24-execution-summary.json` (contents per Section 29.2);
12. produce a final execution summary.

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

1. **Atomic writes, no-clobber re-checked at execute time.** A metadata write or rename either fully takes effect or not at all. Metadata writes are performed so that the original file is never left partially overwritten — e.g. write to a temporary copy and atomically rename it into place, or use the tool's safe-write mode — so an interruption leaves either the pre-write file or the fully-written file, never a corrupt intermediate. Renames are single atomic filesystem operations and are no-clobber **verified at the moment of execution**: immediately before the rename, execution confirms the planned target name is not already present (case-insensitively where the filesystem is case-insensitive) rather than relying solely on the plan's suffix allocation (Section 27). The planner treats every on-disk and planned name as permanently occupied; the executor independently re-verifies the actual target is free. An unexpectedly occupied target is a blocker, never a clobber (shared contract `photos-shared-contract.md` Section 15).
2. **Confirmation journal + state re-derivation on resume.** The journal records a **confirmation** record after each operation succeeds (with enough identity — content fingerprint, target field/name, and the resulting value — to verify completion). On resume, execution does **not** rely on a pre-mutation *intent* record; it **re-derives each file's actual current state** and acts on what it finds: if the renamed target is already present (the source is gone), the operation is already done and is **skipped**; if the source is present and its content fingerprint still matches the plan's precondition, the operation is **re-applied idempotently**; only a *differing* content fingerprint **blocks**. Because writes are atomic (point 1), the file is always in exactly one of those states, never a corrupt third — so no pre-mutation intent record is needed to disambiguate a torn write.
3. **Pre-state captured before the overwrite it protects.** For a manual GPS override, the pinned pre-state (Section 24.1) must be committed to the ledger **before** the GPS write that overwrites it is applied. If the capture and the write were ordered the other way, a crash between them could lose the true original. So the ordering is: capture-and-commit pre-state → then write. A crash after capture but before write leaves a pinned pre-state equal to the current file state, which is harmless (a later revert simply restores what is already there).
4. **Tool failure is fatal to that operation, not silent.** If `exiftool` reports failure for a file, execution records the failure (Section 29.2 item 6), leaves that file at its pre-operation state (point 1 guarantees it is intact), and continues or aborts per policy — it never records the operation as applied. A failed write is never treated as a no-op on the next run.
5. **Post-write content-fingerprint verification.** After a file's metadata write succeeds, execution **recomputes the photo's decoded-content fingerprint** (ImageMagick `identify`, prep Section 9) and compares it to the fingerprint recorded for that file in the plan's per-operation preconditions. The fingerprint is the file's identity spine precisely *because* it is invariant under an in-place EXIF/GPS write (prep Section 9; shared contract Section 9.1), so the expected result is that it is **unchanged**:
   - **unchanged → the write is confirmed.** Only then are the write operation (and any rename that depends on it) eligible to proceed and be journaled as confirmed.
   - **changed → the operation is held back, not silently accepted.** A changed fingerprint means the metadata write disturbed decoded pixels — something the pipeline's identity model does not expect and must not paper over. Execution does **not** confirm the write, does **not** apply the file's dependent rename (the file keeps its current name), and records a **fingerprint mismatch** for the file in `photos-24-execution-summary.json` (Section 29.2 item 8) carrying the expected and actual fingerprints. The run's status becomes `partial`.
   This verification is what `photos-24`'s mismatch list and its `accept_fingerprint_change` review field exist for (Section 29.2 item 8): the operator inspects a flagged file, and if the pixel change is understood and acceptable, sets `accept_fingerprint_change: true` for it and re-runs, at which point execution treats that file's post-write fingerprint as the accepted identity and confirms the held-back operation. The verification runs **per file** and is therefore safe to perform inside the concurrent worker pool (Section 29.3) — each file's check touches only that file and contributes an independent result the executor aggregates deterministically.

### 29.2 The execution summary artifact (`photos-24-execution-summary.json`)

On finishing execution, the workflow writes the terminal artifact `photos-24-execution-summary.json` to `.photos-ingest/` (Section 8.1). It is a record of what execution actually did; unlike `photos-21`–`23` it is never an upstream **dependency** and is never re-hashed (Section 4), so nothing is built from it. It does, however, carry **one confirmable review field** — the per-file `accept_fingerprint_change` flag in its `fingerprint_mismatches` list (item 8) — that a *subsequent* execution reads back to learn which flagged pixel changes the operator has accepted (Section 29.1a item 5). This is not a hash dependency (the file is still never re-hashed); it is a small authored-decision surface on the otherwise terminal artifact, in the same spirit as the decision fields of the numbered artifacts (Section 9).

It must record at least:

1. **Artifact identity** — artifact type, name, and schema version;
2. **Run identity** — the plan id and execution id it summarizes;
3. **What it summarizes** — the SHA-256 of `photos-23-executable-plan.json` (the plan that was executed) and the flattened upstream chain that plan validated against (e.g. `photos-21-time-decisions.json`, `photos-22-gps-decisions.json`, and `photos-11-handoff.json` SHA-256s and the non-JSON fingerprints), so the summary unambiguously identifies the exact inputs the execution was based on;
4. **Operations applied, per destination and in global total** — counts of: time-metadata writes, GPS metadata writes, `GPSProcessingMethod` marker writes, no-clobber renames, no-ops (already-correct files), and skips;
5. **Resume/journal facts** — for a re-run after a crash or partial application (Section 29.1): how many planned operations were newly applied versus treated as already-satisfied-and-skipped, so a resumed run is auditable;
6. **Failures and blockers** — any operation that failed or any blocker encountered during execution, with enough detail to act on;
7. **Final status** — `success`, `partial`, or `failed`;
8. **Fingerprint mismatches** — the per-file list of post-write content-fingerprint mismatches detected in this run (Section 29.1a item 5): for each, the file path, the expected fingerprint, the actual fingerprint, and a pre-created `user_decision` object with `accept_fingerprint_change` (default `false`). A non-empty list forces status `partial`. On a later run, a file whose entry has `accept_fingerprint_change: true` has its held-back operation confirmed (the accepted post-write fingerprint becomes its identity); entries the operator has not accepted remain held back. This is the only field of `photos-24` that a later run consumes;
9. **Run metadata** — wall-clock timestamps, job count, and similar, kept **separate** from the fingerprints in item 3.

Although nothing re-hashes it, the artifact follows the same structure and determinism discipline as the other artifacts for consistency: it is grouped by destination (with a global summary), records the SHA-256 of what it summarizes (item 3), and separates run-metadata timestamps from fingerprints (item 9), mirroring the prep handoff's determinism rule (prep `photos-1-prep-workflow.md` Section 16).

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
  "fingerprint_mismatches": [
    {
      "relative_path": "6-photos-by-dest/Belgium/Brussels/2024-07-03--14-12-21.arw",
      "expected_fingerprint": "...",
      "actual_fingerprint": "...",
      "user_decision": { "accept_fingerprint_change": false }
    }
  ],
  "destinations": { "6-photos-by-dest/Belgium/Brussels": { "...": "..." } },
  "run_metadata": { "started_at": "...", "finished_at": "...", "jobs": 1 }
}
```

### 29.3 Concurrency, determinism, and observability

Execution's per-file work — the `exiftool` metadata/marker writes, the post-write content-fingerprint verification (Section 29.1a item 5), and the no-clobber rename — may run **concurrently** under `-j`/`--jobs`, on the same discipline prep applies to its concurrent fingerprinting and metadata extraction (prep `photos-1-prep-workflow.md` Section 17): concurrency is a performance device only and **must never change semantic results**.

1. **The operation set is fixed before any concurrent work.** The plan is loaded, dependency-revalidated, and the optional pre-mutation snapshot taken (Section 29 steps 1–6) single-threaded; the per-file operation batches are then derived deterministically. Only the application of those already-decided per-file batches is parallelized — execution never *decides* anything concurrently (it never recalculates time, GPS, filename, or rename, Section 29).
2. **Per-file isolation.** Each file's batch (its metadata write, fingerprint verify, and rename) is applied as an independent unit of work that touches only that file; a worker mutates no shared state and returns a per-file result the executor aggregates. Two files never contend, because the no-clobber rename targets were allocated against the whole destination's occupied-name set at plan time (Section 27) and are re-verified free at execute time (Section 29.1a item 1).
3. **Deterministic aggregation.** Results are merged in a deterministic (path-sorted) order so the journal, the per-destination and global totals, the resume facts, and the `fingerprint_mismatches` list (Section 29.2) are identical regardless of job count or completion order. Two different safe job counts produce the same `photos-24-execution-summary.json` content (modulo run-metadata timestamps and the recorded `jobs` value, which are run metadata, not semantic fingerprints, Section 29.2 item 9).
4. **Single-writer journal and cache.** The execution journal and the SQLite writes (including the manual-GPS pre-state ledger captures, which are committed **before** the writes they protect, Section 29.1a item 3) go through a single controlled writer, never from worker threads. The pre-state capture pass therefore completes before the concurrent write pass begins, so no worker races the ledger.
5. **Tool workers, safe restart, no partial persistence.** `exiftool` runs as a persistent `-stay_open` worker, and the `identify` fingerprint tool can likewise run as a persistent worker via ImageMagick's script/command-stream mode (resetting per-image state between commands), falling back to per-file spawn where that is unavailable (prep `photos-1-prep-workflow.md` Section 17 item 5). Either way a worker crash is recoverable and a transient per-file failure is retried, bounded, before becoming a blocker. (Calibration touches photos only, so `ffmpeg`/video is never involved here.) Partial or failed worker output is never journaled as a confirmed operation or cached as a valid fingerprint — it surfaces as a failure or a held-back mismatch (Section 29.1a items 4–5), not a silent success.
6. **Observability.** Long-running execution is visible: phase-level log lines (lock, validate, snapshot, apply, verify, journal, cache, summary) and live aggregate progress for the concurrent apply/verify pass, with the journal — not the progress output — as the durable record (mirroring prep Section 17).

Job count is run metadata, not a semantic dependency, unless it genuinely changes planned behaviour (it does not here — it changes only throughput).


---

## 30. Idempotency and recalculation

The calibration workflow must be idempotent, upholding the shared idempotency principle — change only what needs changing; a no-op run is a no-op (shared contract `photos-shared-contract.md` Section 11).

Repeated planning with unchanged inputs should produce the same semantic results.

The workflow should recalculate only the affected downstream artifacts when upstream inputs change.

Examples:

```text
Workspace sealed (prior successful merge)
  -> calibration hard-stops; nothing touched (sealed means sealed, Section 13)
  -> if files sit at the root or in 0-sources, also warn "likely new dump;
     this workspace is done; move it to a fresh workspace; left untouched"

Workspace not initialized (no root sentinel)
  -> calibration hard-stops: "not an initialized workspace — run prep first" (Section 13)

Loose file at the workspace root (initialized workspace)
  -> calibration hard-stops (strict: any root file, dotfiles included; Section 13)

Non-managed folder or symlink at the workspace root (initialized)
  -> calibration hard-stops, same as a loose root file (Section 13):
     a stray folder belongs inside 0-sources; a symlink is barred (escape)

A managed 0-6 folder is missing (initialized workspace)
  -> calibration hard-stops: structure disturbed — restore it and re-run prep
     (calibration never creates folders; Section 13 / prep Section 6.2 item 7)

0-sources not empty (un-processed dump waiting)
  -> calibration blocked: re-run prep (prep leaves 0-sources empty, Section 13)
  -> residuals in 1-strays / 2-missing-metadata / 3-redundant-jpgs / 4-videos-by-date are fine

5-photos-by-date contains photos
  -> calibration blocked
  -> no JSON artifact created

jpg/tif development subfolder present under 6-photos-by-dest
  -> calibration hard-stops (development already started)
  -> no JSON artifact created

Non-media (other-class) file present under 6-photos-by-dest
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

Media file size/mtime/fingerprint changed
  -> calibration blocked
  -> prep/cache refresh required

Invalid human-authored value (e.g. manual_iana_timezone not a real zone,
manual GPS latitude out of range, zfs snapshot prefix contains '/',
or a hand-edited decision object is structurally broken)
  -> sanity-validation fails (Section 9.2)
  -> hard blocker, offending artifact/field located, no downstream artifact
  -> value preserved and flagged for correction, never silently dropped

Post-write content fingerprint changed (metadata write disturbed pixels)
  -> the file's write is held back: not confirmed, dependent rename not applied
  -> recorded in photos-24 fingerprint_mismatches (Section 29.1a item 5 / 29.2 item 8)
  -> run status partial; operator sets accept_fingerprint_change=true and re-runs
     to accept the new identity, else fixes the cause

Required ZFS snapshot configured but cannot be taken
  -> execution aborts before any mutation (snapshots_required honored, Section 29 step 6)
  -> with snapshots optional/disabled (the default), execution proceeds normally
```

---

## 31. Stage 11 — Finalize and archive (explicit command)

Finalize is a **separate, explicitly-invoked command**, not part of `execute` and not run automatically at the end of calibration. Because calibration is freely re-runnable (Section 2.1; shared contract `photos-shared-contract.md` Section 10.1), "this dump is done" is a human judgement, so the user invokes finalize when finished with a workspace to produce the durable archival package.

Finalize must:

1. run under the workspace lock (shared contract Section 2) and be **non-destructive** — it reads and bundles; it never mutates the workspace, the artifacts, the live SQLite DB, or the library. (Generating `photos-25-complete-log.json` and capturing the `photos-25-calibrate-ingest.db` backup snapshot below are *new-file* writes into `.photos-ingest/`, not mutations of any existing photo, artifact, or the live DB — the snapshot is a read-only copy of the live DB.)
2. require that calibration has ended successfully (a complete, executed `photos-23-executable-plan.json` with a corresponding `photos-24-execution-summary.json`); it refuses to finalize an incomplete or stale state;
3. assemble the **archival package** defined in shared contract Section 13 — `photos-00-config.json`, the live SQLite database `photos-00-ingest.db`, the per-phase DB backup snapshots present (`photos-15-prep-ingest.db` and the calibration snapshot captured in item 4a), the JSON artifacts `photos-11-handoff.json`, `photos-15-prep-log.json`, `photos-21-time-decisions.json`, `photos-22-gps-decisions.json`, `photos-23-executable-plan.json`, `photos-24-execution-summary.json`, and a freshly generated `photos-25-complete-log.json`;
4. generate the transformation log `photos-25-complete-log.json` (shared contract Section 13.3) by **carrying prep's end-of-prep audit log (`photos-15-prep-log.json`) forward** as the prep portion of each photo's journey and appending calibration's steps — consolidating prep's handoff/journal and calibration's decision artifacts/journal into a per-photo, content-fingerprint-keyed, human-readable JSON record of every transformation between ingestion and successful calibration. It does not re-derive prep's history or discard the prep log; `photos-25-complete-log.json` is a superset of `photos-15-prep-log.json` (shared contract Section 13.3 item 6);
4a. capture the end-of-calibration database backup snapshot `photos-25-calibrate-ingest.db` — a consistent, atomic copy of the live `photos-00-ingest.db` taken at finalize (shared contract Section 13.4a). This reads the live DB and writes a new immutable file; it does not mutate the live DB (consistent with item 1);
5. write a self-describing manifest (workspace identity, plan/execution ids, and SHA-256 of each bundled item, including the DB snapshots) so the package's integrity is verifiable later;
6. leave the package in a known location the user can move to permanent storage alongside the library.

Finalize creates no new authority and makes no decisions; it is the retention step that makes authored decisions (shared contract Section 12) outlive the transient workspace.

Finalize is followed, when the operator chooses, by the **merge** phase (`photos-3-merge`, spec `photos-3-merge-workflow.md`; shared contract Sections 10.4 and 13.5), which **moves** the finalized photos from `6-photos-by-dest` into the permanent library and writes its own log `photos-35-merge-log.json` (copied forward from `photos-25-complete-log.json`, never editing it) recording each file's final library location. Merge is optional and additive: the finalize archival package — the `photos-25` transformation log, the SQLite database and its snapshots, and the job/decision artifacts — is complete and self-sufficient without it, and a workspace that is never merged keeps that full record intact (shared contract Section 13). Merge requires a successfully finalized workspace; calibration and finalize never perform the merge themselves.

---

## 32. User-visible outputs

The workflow should produce user-facing outputs at each blocked or decision point.

Important textual outputs include:

1. sealed-workspace hard-stop (with new-dump warning if files sit at the root or in `0-sources`, Section 13);
2. not-initialized hard-stop ("run prep first", Section 13);
3. misplaced-root-entry hard-stop — loose file, non-managed folder, or symlink at the root (strict, Section 13);
3a. incomplete-structure hard-stop — a missing managed `0`–`6` folder; restore it and re-run prep (Section 13);
4. `0-sources`-not-empty blocker (re-run prep, Section 13);
5. by-date-not-empty blocker;
6. development-already-started (jpg/tif subfolder present) hard-stop;
7. stale prep/by-dest dependency report;
8. unknown camera group report;
9. pasteable config snippets for newly recognised groups;
10. invalid-value blocker — a config or decision field that failed sanity-validation, naming the artifact and field (Section 9.2);
11. reason why no JSON artifact was produced, if blocked before time-decision stage;
12. time-decision summary (including per-(destination, camera group, naive date) clock-offset buckets and their self-anchor/timezone-derived/confirmable proposals, Section 10.2, and per-destination civil-timezone decisions including timezone proposals inherited from the nearest ancestor destination, Section 18);
13. resolved UTC cache summary;
14. GPS-decision summary (including per-destination folder-fallback cells and their inherited/confirmable proposals, Section 25.3);
15. executable plan summary;
16. execution summary — counts applied/skipped, the pre-mutation snapshot record (or "none"), and any **post-write fingerprint mismatches** awaiting `accept_fingerprint_change` review (Section 29).

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
1. Invoke calibration; take the workspace lock.
2. Startup guards: hard-stop on a sealed workspace, an uninitialized workspace, a misplaced root entry (loose file, non-managed folder, or symlink), a missing managed 0-6 folder, or a symlink among managed files (Section 13).
3. Load prep handoff and SQLite cache.
4. Verify 5-photos-by-date contains no photos and no jpg/tif development subfolders exist under 6-photos-by-dest (hard-stop if development started).
5. Restrict calibration scope to 6-photos-by-dest (photo-only; symlinks barred — prep is the gatekeeper for nested links there, Section 7.2).
6. Validate by-dest cache/media/prep dependencies.
7. Load, parse, and fingerprint GPX folder/files if configured or available.
8. Recognise and classify camera groups.
9. If unknown groups exist, print config snippets and stop. No JSON artifact yet.
10. Analyse per-destination time requirements.
11. Determine/confirm destination civil timezone for every destination; a destination with no timezone of its own inherits its nearest ancestor destination's timezone as a confirmable proposal (Section 18).
12. Generate GPX/native-GPS time-anchor proposals where possible, per (group, destination, naive date) bucket; a bucket with no self-anchor takes a timezone-derived offset proposal when the destination timezone is resolved, else manual-required (Section 10.2 rule 4, Section 19.4). Offsets are not inherited across destinations.
13. Create photos-21-time-decisions.json, grouped by destination, even if no-op.
14. User completes/accepts time decisions if needed.
15. Compute and persist resolved UTC per file in SQLite.
16. Start GPS planning only after resolved UTC exists for every file.
17. Create photos-22-gps-decisions.json, grouped by destination, even if no-op; summarize automatic/no-op decisions and list file paths only for review/blocker items. Each destination's folder GPS fallback inherits its nearest ancestor's fallback as a confirmable proposal (Section 25.3).
18. Plan metadata writes and no-clobber destination-local-time renames using configured filename format.
19. Create photos-23-executable-plan.json, grouped by destination, with flattened dependency list and exact file-level operations.
20. Execute only after strict dependency validation (SHA-256 rehashing of named JSON artifacts): take the optional pre-mutation snapshot (like prep), apply per-file operations concurrently, verify each photo's content fingerprint is unchanged after the metadata write, journal, and write photos-24 (with any fingerprint mismatches for review).
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
Human-authored config and decision values are sanity-validated before use; an invalid value blocks.
Dependencies are flattened, named, and directly verified.
JSON artifact dependencies are verified by SHA-256 rehashing exact file bytes.
Renames and metadata writes are no-clobber and atomic — re-verified at execute time, not trusted from the plan.
Validate upstream -> create artifact -> record dependencies in it -> reject downstream use if dependencies changed.
```
