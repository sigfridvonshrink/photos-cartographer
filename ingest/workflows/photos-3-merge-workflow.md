# Library-Merge Workflow Specification (`photos-3-merge`)

## 1. Purpose

This document defines the complete, self-contained workflow for the library-merge phase implemented by `photos-3-merge`.

The merge phase exists to take a **geotagged, finalized** `6-photos-by-dest` staging tree and merge it into the user's **permanent library** at `library_root`, placing every photo at its corresponding library path without ever renaming or overwriting a file already in the library. It is the bridge from the transient workspace to the durable, owned library (e.g. a digiKam by-folder tree), and the **terminal action** for the workspace: prep organizes a dump, geotag corrects time/GPS and finalizes names, finalize bundles the archival record, merge moves the result into the library — then **re-seals** the archive to include the library destinations and **seals the workspace** so it is not reused for new media (shared contract Sections 13.6, 13.7).

Merge:

1. validates that the workspace was successfully geotagged and finalized (its archival record exists), and that `6-photos-by-dest` is the clean, photo-only, fully-named set the earlier phases guarantee;
2. validates `library_root` and the merge/placement config;
3. maps each by-dest photo to its destination path under `library_root`, preserving the destination folder structure the user curated;
4. on a path collision with an existing library file, resolves identity **by content fingerprint** — same content means it is already in the library (the by-dest source is removed), different content gets the **incoming** file a safe non-colliding name;
5. **moves** files into the library by a no-clobber, atomic (or atomic-equivalent across filesystems) place-then-remove operation — never mutating, renaming, or deleting a library file — and removes each by-dest source only after its verified copy is in the library; a fully successful merge empties by-dest of photos, while any file that could not be merged (a blocker) is left in by-dest and the run ends `partial` without sealing (Section 9.4);
6. records, per file, exactly where it landed in the library and whether it was renamed, in `photos-31-merge-summary.json`; writes its own transformation log `photos-35-merge-log.json` by copying geotag's `photos-26-complete-log.json` forward and appending each file's final library location (never editing the `photos-26` log, shared contract Section 13.0a); and captures an end-of-merge database backup snapshot (`photos-35-merge-ingest.db`, shared contract Section 13.4a);
7. on success, **re-seals the archival package** automatically so it includes the library-aware log, the merge summary, and the end-of-merge DB snapshot (shared contract Section 13.6);
8. on success, **marks the workspace terminal (sealed)** so it is not reused for new media; further dumps go to a fresh workspace (shared contract Section 13.7);
9. is idempotent and resumable on an **unsealed** workspace: re-running recognizes files already in the library and applies only what remains (completing any interrupted source removals). Once a workspace is **sealed** (a prior merge fully succeeded), merge refuses outright and touches nothing — sealed means sealed (Section 3 precondition 0; shared contract Section 13.7).

This is a workflow specification, not a script implementation specification. It describes *what* merge does and the invariants it upholds, not the classes or modules that implement it.

Cross-phase facts shared with prep and geotag — the workspace lock, the library-side lock, the pre-mutation snapshot mechanism, the shared configuration object, the workspace control directory, the **workspace structural-integrity guards** (base-is-folders, symlinks barred including nested directory symlinks, and the complete `0`–`6` structure — shared contract Section 5.3), the camera-group identity key, the filename timestamp format, the input-validation discipline, the execute-time no-clobber/atomicity rule, the archival package and transformation log, and the end-to-end operator loop — are defined in `photos-shared-contract.md` and are authoritative there. This document references that contract rather than restating it. In particular, the library-specific facts merge depends on are stated in the shared contract Sections 13.5, 15.1, and 15.2; this spec is the detailed workflow built on top of them.

---

## 2. Scope and boundary

### 2.1 Merge is merge-only

`photos-3-merge` owns one thing: placing a finalized by-dest set into the library, safely and traceably. It must not re-organize, re-deduplicate, re-fingerprint by-dest content (prep already did, and its fingerprints are reused), correct time or GPS (geotag already did), or alter the library's existing organization. It plans and executes additive library placement and nothing else. The full prohibition list is in Section 14.

### 2.2 The library is authoritative and protected

The permanent library at `library_root` is treated as ground truth. Merge **never renames a library file and never overwrites the photographic content of a library file** (shared contract `photos-shared-contract.md` Section 15.1). When a name would collide, it is always the **incoming by-dest file** that is renamed, never the resident library file. Merge reads an existing library file only to fingerprint it on a collision (Section 7), and otherwise leaves the library untouched.

### 2.3 No library-wide scan, no library-wide dedup

Merge does **not** build or maintain a full index of the library, and does **not** perform library-wide deduplication. It assumes the library is already well-organized and internally consistent. Merge inspects the library only at the specific destination paths its incoming files map to, and only when a path is already occupied. This keeps merge cheap and bounded by the size of the incoming batch, not the size of the (potentially enormous) library.

The library also has **no database of its own.** When merge needs a library file's fingerprint to resolve a collision, it computes it on the fly and caches the result in the **workspace** SQLite (`photos-00-ingest.db`, the only database; shared contract Section 13.4) so the same library file is fingerprinted at most once per run and across re-runs while unchanged. Nothing about the library's state is persisted library-side — the only library-side construct is the lock keyed to `library_root` (Section 12; shared contract Section 15.2), which serializes concurrent merges and stores nothing.

### 2.4 By-dest is the source; merged files are moved out

Merge reads `6-photos-by-dest` as its source and **moves** each successfully-placed photo into the library, removing it from by-dest. A **fully successful** merge moves every photo (or confirms it already in the library) and leaves by-dest **empty of photos** — at which point the workspace is sealed (Section 9.4). If a file cannot be merged — a **blocker** (Section 7) — it is **left in by-dest** and the run ends `partial` *without* sealing, so the operator can resolve the blocker and re-run; the un-merged leftovers are exactly the files that still need attention. Either way the workspace never keeps a duplicate of a file already in the library. The move is safe and atomic (Section 11): the by-dest source is removed only *after* the library copy is verified in place, so a crash never loses a file. Merge never mutates by-dest content or alters a file's name except where a library collision forces an incoming rename (Section 7); the names by-dest carries are geotag's final names.

---

## 3. Preconditions (block before any operation)

The workspace lock is acquired at process startup, and the library-side lock is acquired before any library access (Section 12; shared contract Sections 2 and 15.2). With the locks held, merge validates the following and **hard-stops before any placement** if any fails:

0. **Terminal-seal check — sealed means sealed.** If the workspace carries the terminal/sealed marker from a prior successful merge (shared contract Section 13.7), merge **hard-stops immediately, touching nothing** — there is no confirming re-merge and no recovery utility. If files are present at the **workspace root** or in **`0-sources`**, merge additionally warns that a likely new dump was detected and that, because this workspace is done, the dump must be moved into a **fresh workspace** by hand; merge leaves it exactly where it is. (A merge that was merely *interrupted* is not sealed — the seal is written only on full success, step 10 of Section 10.3 — so resuming an interrupted merge proceeds normally and may still have files to move; that is an unsealed workspace, not a sealed-workspace re-run.)
0a. **Initialized, and no misplaced entry at the workspace root.** The workspace must be initialized — root sentinel `photos-00-workspace-guard` present (shared contract Section 5; prep Section 3.1). If it is not, merge hard-stops with "not an initialized workspace — run prep first" (only prep's init path may consume an as-arrived dump). And, exactly as in prep and geotag, **any misplaced entry at the workspace root blocks** — a **loose file** (strict: any file, dotfiles included), a **non-managed folder** (a stray dump folder belongs *inside* `0-sources`, not loose at the base), or a **symlink** (barred outright rather than followed, since following it would escape the workspace). The base of an initialized workspace holds only the managed folders and control/dot directories, and dumps belong in `0-sources`. This is the shared structural-integrity guard every script applies at startup (shared contract Section 5.3; prep Section 6.2 items 2–3; geotag Section 13).
0b. **`0-sources` is empty.** Prep leaves `0-sources` empty at the end of every run (prep Sections 7.6, 18). Merge requires it empty, confirming no un-processed dump is sitting in the inbox. (By-date *photos* empty is required separately by precondition 3. By-date *videos* (`4-videos-by-date`), `2-missing-metadata`, `3-redundant-jpgs`, and `1-strays` may hold residuals — they are not library-bound and do not block merge.)
0c. **The managed `0`–`6` structure is intact.** Every managed folder (`0-sources`…`6-photos-by-dest`) must exist. A *missing* managed folder on an initialized workspace means the structure was disturbed out-of-band (the operator deleted or moved one — possibly with media inside); merge **hard-stops** and directs the operator to restore the folder(s) and re-run, rather than proceeding against a damaged workspace. Like geotag, merge never creates or repairs the workspace structure — folder creation is prep's init-only job (shared contract Section 5.3 item 3; prep Section 6.2 item 7). (This concerns the *workspace* `0`–`6` tree, not the library: merge does create any missing destination subdirectory *under `library_root`* when it places a file, which is ordinary additive library placement, Section 6.)
1. **Geotag ended successfully.** A complete, executed `photos-24-executable-plan.json` with a corresponding `photos-25-execution-summary.json` (status `success`) exists, exactly as finalize requires (geotag `photos-2-time-gps-workflow.md` Section 31). Merge never moves a half-geotagged set into the library.
1a. **The finalized record is current with by-dest — no post-finalize drift.** "Geotag ended successfully and was finalized" is a point-in-time fact; the by-dest set can change *after* finalize (the operator adds or edits a photo and re-runs prep, but does **not** re-run geotag/re-finalize), which would leave a by-dest photo that prep recognizes but the finalized plan never geotagged — exactly the "half-geotagged set" preconditions 1–2 promise to exclude. Merge therefore re-checks currency mechanically, not by trusting that finalize was the last thing to happen: it **recomputes the current `photos-11-handoff.json`'s `content_fingerprint` and requires it to equal the handoff content fingerprint that `photos-24-executable-plan.json` recorded as a dependency** (prep `photos-1-prep-workflow.md` Section 16.2; geotag `photos-2-time-gps-workflow.md` Section 4). Because that fingerprint pins only the handoff's **deterministic content** (not its per-run audit), a **no-op re-prep** that refreshes only run metadata between finalize and merge does **not** trip this check — only a genuine by-dest content change does. If they differ, by-dest changed since the finalized plan was built. Equivalently, every by-dest photo's content fingerprint must be one the finalized `photos-24`/`photos-25` covered; a by-dest photo absent from the finalized plan is the signal. On a mismatch, merge **hard-stops** with a targeted blocker directing the operator to **re-run geotag and re-finalize** (not merely re-prep) before merging — distinct from the "re-run prep" blocker of precondition 4, because the fix differs. (Merge still records the handoff's whole-file SHA-256 in its summary for byte-identification, Section 9.1 item 3; that is integrity, separate from this content-fingerprint currency check.) This is what actually enforces shared contract Section 10.4 item 2 ("never a half-geotagged one"): the guarantee rests on this check, not on operator discipline.
2. **The workspace was finalized — required, and kept a separate step.** The archival package and the transformation log `photos-26-complete-log.json` exist (shared contract Section 13). Finalize is a deliberate, separately-invoked geotag-side command (geotag Section 31) and **must have run before merge** — merge operates on the finalized record and refuses to run without it. Finalize stays separate from merge (rather than being folded into it) because geotag is freely re-run and re-finalizing after every pass would be wasteful; merge, by contrast, re-seals the package itself afterwards (Section 10.3 step 9; shared contract Section 13.6) because it is the terminal action. If finalize has not run, merge hard-stops with a "run finalize first" blocker.
3. **By-dest is the clean photo-only set.** `5-photos-by-date` contains no photos, `6-photos-by-dest` contains only `image`/`raw` photo files (no non-media, no videos), and no `jpg`/`tif` development subfolder exists under `6-photos-by-dest` (the geotag gating conditions, geotag Sections 7, 7.1, 7.2, 7.3; shared contract Section 10.1). Merge re-verifies these rather than assuming them, because the workspace may have been touched since geotag. **Symlinks under `6-photos-by-dest` — file symlinks and nested directory symlinks alike — are barred** (shared contract Section 5.3 item 2): the pipeline never follows a link into or out of the managed tree. As with geotag, prep is the gatekeeper that detects such a link while scanning by-dest (it is a managed folder prep walks, prep Section 6.2 item 3), and the prep-consistency check of precondition 4 (and the post-finalize-currency check of precondition 1a) means merge only ever operates on a by-dest set prep recorded with no forbidden link present; merge itself never follows a link when reading by-dest.
4. **Prep-consistency.** The prep handoff recognizes all by-dest photos (prep was re-run after the latest move into by-dest, geotag Section 13.1). Because geotag renamed by-dest files without re-keying the handoff, this is checked against the **finalized-name set** — the handoff's by-dest photos joined to `photos-24`'s rename operations by content fingerprint (Section 10.1), each yielding its final on-disk name — not against the raw handoff names. A photo file present under `6-photos-by-dest` that is **not** in that finalized set is a "re-run prep" blocker, identical in spirit to geotag's. (The converse — a finalized entry whose file is absent from by-dest — is not a blocker: it is the already-merged/resume case Section 8 resolves, not a missing-input error.)
5. **Config is valid and `library_root` is a blessed library.** `library_root` and the merge/placement config pass sanity-validation (Section 4; shared contract Section 14), and `library_root` carries the `.photos-library` identity marker (shared contract Section 15.1 item 3) — the **sole** check that the target is a library; merge performs no other structural inspection of it. A missing marker is a hard blocker directing the operator to run `init-library` first (Section 4); merge never auto-creates the marker on the data path. Crucially, **`library_root` validation and this marker check run under the workspace lock but *before* the library lock is acquired** (Section 12), so merge never drops a `.photos-merge.lock` into a directory that is not a blessed library; every remaining precondition runs with both locks held.

If any precondition fails, merge prints a textual blocker naming the cause and the fix, and writes no `photos-31-merge-summary.json` and performs no placement. The required sequence is *geotag → execute → finalize → merge* (shared contract Section 10.4).

Example:

```text
Merge cannot proceed.

Reason:
The workspace has not been finalized (photos-26-complete-log.json is missing).

Merge places the finalized, fully-recorded by-dest set into the library.
Run the finalize/archive command first, then merge.

No files were merged.
```

---

## 4. Configuration and validation

Merge reads the shared workspace config `photos-00-config.json` (shared contract Section 4) and consumes the library-merge area (shared contract Section 4.3):

1. **`library_root`** — the permanent library directory files are placed into. It must resolve to a valid, existing directory **outside** the workspace and its managed `0`–`6` tree, and is validated like every other configured path (shared contract Section 14.1). An empty, malformed, non-existent, or workspace-internal `library_root` is a hard blocker.
2. **Placement / collision policy** — how a by-dest destination maps to a library subpath (Section 6) and how incoming-file renames are formed on a genuine collision (Section 7). These have conservative defaults (preserve the destination structure; allocate a differentiating suffix via the shared convention) and are config-overridable; any override is validated.

Merge's **data path is read-only with respect to config** — like geotag, `plan`/`dry-run`/`execute` never write `photos-00-config.json` (prep is the seeder, shared contract Section 4.1 item 2). Every human-authored value merge consumes is sanity-validated before use (shared contract Section 14): a failure is a hard blocker located to the offending field, and merge produces no summary and no placement until it is fixed. Validation detects invalid *content*; the dependency machinery detects *change* — both apply.

**Library identity and the `init-library` setup command.** A directory is recognized as a library solely by the empty `.photos-library` marker in its root (shared contract Section 15.1 item 3); merge does no other structural check on it. The marker is created by an explicit, idempotent, one-time **`init-library`** subcommand — the only path that creates it (`plan`/`dry-run`/`execute` only read it and hard-stop if it is absent, Section 3 precondition 5). `init-library` blesses a directory as a library: it resolves the given path to an absolute path, validates it (an existing directory; and, when run from inside a workspace, outside that workspace and its managed `0`–`6` tree), and writes `.photos-library` no-clobber (a second run is a no-op success). As an operator convenience it also records the resolved path:

- **Run from inside a workspace with an explicit path** → it blesses the directory *and* writes that one resolved `library_root` value into the workspace `photos-00-config.json`. This is the single narrow exception to "prep is the config seeder" (shared contract Section 4.1 item 2): the one-time setup command may set `library_root`, and only that key — never any other config, and never on the merge data path.
- **Run from inside a workspace with no path** → it reads `library_root` from config and blesses that directory (no config write).
- **Run outside any workspace with an explicit path** → it blesses the directory only, and advises the operator to re-run from a workspace if they also want it recorded in config.
- **Run outside any workspace with no path** → there is nothing to bless and no config to read; it is an error.

---

## 5. Core workflow rule

Merge is a plan/validate/execute workflow with the same strict separation as the other phases:

```text
Plan (non-mutating): map each by-dest file to its library target, detect collisions, resolve them.
Validate the plan against current library + by-dest state.
Execute only the validated plan: MOVE files (place no-clobber + atomic, then remove the by-dest source).
Journal every move (library placement, then source removal).
Update SQLite (the library-file fingerprint cache only, populated during planning); each file's library destination is recorded in photos-31/photos-35, not the database.
Write photos-31-merge-summary.json and photos-35-merge-log.json (copied forward from photos-26) only after success.
```

Invariants that hold at every gate:

1. planning is non-mutating — it touches no library file, no by-dest file, no artifact;
2. dry-run validates the real saved plan and reports a concise summary of the moves (counts of new/already-present/renamed/blocked) plus the path to the full plan — never a separate simulation, and never a full dump;
3. execution revalidates the plan before any mutation and rejects stale plans;
4. all library placements are no-clobber — planned no-clobber *and* re-verified no-clobber at execute time, performed atomically or atomic-equivalent across filesystems (shared contract Section 15);
5. a library file is never deleted, written, or renamed — it is read only to fingerprint on a collision;
6. a by-dest source is removed only after its verified copy is in the library; un-merged files stay in by-dest;
7. merge writes only its own 3X artifacts and copies the `photos-26` log forward rather than editing it (shared contract Section 13.0a);
8. all human-authored config is sanity-validated before use (Section 4; shared contract Section 14);
9. no summary/log is written from a stale or partial run.

Execution never re-derives placement decisions. It applies only the moves already recorded in the validated plan.

---

## 6. Destination-to-library mapping

Each by-dest photo sits in a destination folder under `6-photos-by-dest` (geotag's notion of a destination, `photos-2-time-gps-workflow.md` Section 10.1). Merge maps that destination to a library subpath under `library_root`, preserving the curated structure:

```text
6-photos-by-dest/<relative-destination-path>/<final-name>.ext
  ->  <library_root>/<relative-destination-path>/<final-name>.ext
```

By default the relative destination path is preserved verbatim, so the library mirrors the destination tree the user built (e.g. `Belgium/Brussels/...`). The mapping is config-driven where the user wants a transform (for example prefixing a year derived from the geotagged date), but the default is the identity mapping above. The mapping is deterministic: the same by-dest file maps to the same library target on every run, which is what makes idempotency (Section 8) and resume work.

The **final name** is the name geotag already assigned (destination-local civil time, shared contract Section 7.3). Merge does not recompute it. The only name change merge ever introduces is the anti-collision rename of Section 7, applied to the **incoming** file alone.

---

## 7. Collision resolution by content fingerprint

A *collision* is when an incoming file's mapped library target path (Section 6) is already occupied by an existing library file. Because merge keeps no library-wide index (Section 2.3), collisions are discovered per target, at the moment merge considers placing that file, by a single existence check on the target path.

On a collision, merge decides identity by **content fingerprint**:

1. **Compute the library file's fingerprint on the fly, once.** Merge fingerprints the resident library file at the colliding path and stores the result in the SQLite **library-file fingerprint cache** (shared contract Section 13.4), keyed so that the same library file (by path plus size/mtime) is fingerprinted **at most once** across the run and across re-runs while it is unchanged. A second collision against the same library file reuses the cached fingerprint rather than re-reading it. The incoming by-dest file's fingerprint is already known from prep's cache (prep `photos-1-prep-workflow.md` Section 9) and is reused, never recomputed.
2. **Same content (fingerprints equal) → already-present; remove from by-dest.** The colliding library file *is* this photo, already in the library (e.g. from a previous merge, or a prior import). Merge places nothing and renames nothing, but — because the library already holds the content — it treats the file as successfully merged and **removes the by-dest source** (the workspace should not keep a duplicate of a file already in the library, Section 2.4). It is recorded as an `already_present` placement whose library location is the existing path. This is the idempotent case (Section 8).
3. **Different content (fingerprints differ) → rename the incoming file.** Two distinct photos genuinely map to the same name. The library file is authoritative and untouched; the **incoming** file receives a safe differentiating name using the shared no-clobber suffix convention (shared contract Section 7.2). Because the library is **append-only** (a resident file is never renamed, so its names are never reclaimed), the suffix is realized as **append-at-max+1**, not gap-filling from `-001`: the incoming name is canonicalized to its root (the `-NNN` dedup suffix stripped, shared contract Section 7.2), and the next index is `max(highest existing `-NNN` for that root among the destination's library files, highest `-NNN` for that root among the incoming files targeting the same destination this run) + 1` — so `<root>-NNN.ext` always extends past every existing and in-batch suffix and a previously-allocated number is never reused on a re-run. Allocation treats existing library names at that destination and all incoming files targeting the same destination as occupied for its duration (the same "permanently occupied" discipline as prep Section 8 and geotag Section 27). The renamed incoming file is then placed at the new, just-verified-free target.

If the library-file fingerprint cannot be computed (read/permission error on the library file), merge must **not** guess identity: it treats the file as a blocker for that one item (it neither overwrites nor blindly renames-and-duplicates), reports it, and continues with the rest of the batch or aborts per policy. A collision is never resolved by overwriting or by assuming equality without a fingerprint.

Fingerprinting only happens **on a collision**. The overwhelming common case — an incoming file whose target path is free — places directly with no library read at all, which is what keeps merge bounded by the incoming batch size.

---

## 8. Idempotency, resume, and non-destructiveness

Merge upholds the shared idempotency principle — change only what needs changing; a no-op run is a no-op (shared contract Section 11).

1. **Move, not destroy — and the library is never destroyed.** Merge **moves** files into the library (a no-clobber, atomic-equivalent place-then-remove, Section 11): it copies to the library, verifies, atomically renames into place, and only then removes the by-dest source. It **never deletes or mutates a library file** — "non-destructive" here means the *library* is never harmed and no file is ever lost (a file is removed from by-dest only once its verified copy is in the library). A fully successful merge empties by-dest of photos (every file moved into / confirmed already in the library); only a `partial` run leaves un-merged blockers behind, and that run does not seal (Section 9.4; Sections 2.4, 7).
2. **Already-in-library files need no placement.** A file whose mapped target already holds the same content (Section 7 item 2) is recognized as already in the library, produces no placement, and is removed from by-dest. Re-running merge over a batch already in the library changes the library not at all and simply confirms/clears any stragglers — reported as `already_present`.
3. **Resume after interruption.** Merge is safe to re-run after a crash or partial run. Resume is **state-derivation** (mirroring geotag `photos-2-time-gps-workflow.md` Section 29.1a): the journal records only **confirmed-completed** moves, and on resume each file's state is re-derived from the **filesystem plus its recorded content fingerprint**, so each file is recognized as being in exactly one of — not yet placed (still in by-dest), placed-but-source-not-yet-removed (the library copy is present and its fingerprint matches; finish by removing the source), or fully moved (source gone, library copy verified). Because placement is atomic and the source is removed **last**, the only crash window — renamed into the library, source-unlink pending — is safely recognized and completed, and no file is ever lost or half-present under its final name. Resume re-validates the plan, treats fingerprint-confirmed library copies (and already-in-library targets) as done, and applies only the outstanding work. **Resume is via `execute`, not a fresh `plan`:** a partially-applied merge has already moved some files out of by-dest, and the saved plan still records them, so re-running `execute` finishes the remaining moves and writes a log covering every file. Re-running `plan` over a partially-applied merge would instead enumerate only the files still in by-dest and omit the already-moved ones from the merge log (and an already-placed *renamed* file cannot be reliably re-located by a fresh plan). `plan` therefore **refuses while a prior merge is in flight but not sealed** — a `photos-31-merge-summary.json` of status `partial` (a blocker remains) *or* `success` (it completed the moves but crashed before sealing) is present with a saved `photos-30-merge-plan.json`, on an as-yet-unsealed workspace — directing the operator to `execute` to resume. (A `rejected` summary moved nothing, so re-planning after it is allowed.)
4. **Deterministic re-derivation.** Because the destination mapping (Section 6) and the suffix allocation (Section 7) are deterministic for a given library + by-dest state, a re-run reproduces the same targets and the same anti-collision names; it does not, for example, allocate a *new* suffix to a file it already placed under `-001`.

A merge interrupted partway is finished by re-running; a merge over a fully-merged batch is a complete no-op (nothing left in by-dest to move, every target already holding identical content).

---

## 9. User-visible outputs and the merge summary

### 9.1 The merge summary artifact (`photos-31-merge-summary.json`)

On finishing, merge writes the terminal artifact `photos-31-merge-summary.json` to `.photos-ingest/` (shared contract Section 5). Like geotag's execution summary, it records what merge actually did; it is never an upstream dependency and is never re-hashed.

It must record at least:

1. **Artifact identity** — artifact type, name, schema version.
2. **Run identity** — the merge run id, and the plan/execution ids of the geotag run whose finalized output it merged, plus `library_root`.
3. **What it merged** — the SHA-256 of the artifacts that pinned the merged state (`photos-24-executable-plan.json`, `photos-25-execution-summary.json`, and the prep handoff `photos-11-handoff.json`), so the merge unambiguously identifies the exact finalized set it placed.
4. **Per-file placement, per destination and in global total** — for each by-dest photo: its (original) by-dest path, its **final library path**, whether it was **renamed for the library** (and the from/to names if so), whether it was **already present** (identical content already in the library), and whether it was **removed from by-dest** (true for placed and already-present files; false for blocked leftovers that remain). This is the authoritative "where did each file end up, and is it still in the workspace?" record.
5. **Counts** — the per-file dispositions partition the batch into mutually exclusive outcomes: **placed-new** (target was free, placed under the geotagged name), **renamed-to-avoid-collision** (different-content collision, placed under a safe alternative name), **already-present** (identical content already in the library, nothing written), and **blocked** (left in by-dest). Each merged file is in exactly one of the first three. **removed-from-by-dest** is a derived total — the sum of placed-new + renamed + already-present (every successful disposition removes the source) — surfaced separately because it answers "how many sources left the workspace," and equals (batch − blocked).
6. **Resume facts** — for a re-run after interruption: how many files were newly moved versus treated as already-done/already-in-library.
7. **Failures and blockers** — any item that could not be placed or fingerprinted (left in by-dest), with enough detail to act on.
8. **Final status** — `success`, `partial`, `failed`, or `rejected` (a pre-mutation abort — e.g. a required ZFS snapshot that could not be taken, Section 10.3 step 3 — that mutated nothing but records the snapshot/abort detail for audit, mirroring geotag's rejected execution summary; a *stale-plan* rejection writes no summary at all, Section 5 invariant 9).
9. **Run metadata** — wall-clock timestamps, job count, kept separate from the fingerprints in item 3.

It is grouped by destination (with a global summary), records the SHA-256 of what it merged (item 3), and separates run-metadata timestamps from fingerprints (item 9), mirroring the determinism discipline of the other terminal artifacts (geotag Section 29.2; prep Section 16).

Example shape:

```json
{
  "artifact_type": "merge_summary",
  "artifact_name": "photos-31-merge-summary.json",
  "schema_version": "...",
  "merge_run_id": "...",
  "library_root": "/library",
  "merged": {
    "photos-24-executable-plan.json": { "sha256": "..." },
    "photos-25-execution-summary.json": { "sha256": "..." },
    "photos-11-handoff.json": { "sha256": "..." }
  },
  "totals": {
    "placed_new": 0,
    "already_present": 0,
    "renamed_for_library": 0,
    "removed_from_by_dest": 0,
    "blocked": 0
  },
  "resume": { "newly_moved": 0, "already_done_skipped": 0 },
  "failures": [],
  "destinations": {
    "Belgium/Brussels": {
      "files": [
        {
          "by_dest_path": "6-photos-by-dest/Belgium/Brussels/2024-07-03--14-12-21.arw",
          "library_path": "/library/Belgium/Brussels/2024-07-03--14-12-21.arw",
          "renamed_for_library": false,
          "already_present": false,
          "removed_from_by_dest": true
        }
      ]
    }
  },
  "status": "success",
  "snapshot": null,
  "run_metadata": { "started_at": "...", "finished_at": "...", "jobs": 1 }
}
```

### 9.2 The merge transformation log (`photos-35-merge-log.json`)

Merge writes its **own** phase-named transformation log, `photos-35-merge-log.json`, by **copying geotag's `photos-26-complete-log.json` forward** and appending, per file, a `merge` step recording the final library path and whether the file was renamed for the library — then writing the result deterministically. Merge does **not** edit `photos-26-complete-log.json`: under the phase-artifact-ownership rule (shared contract Section 13.0a), each phase writes only its own numbered artifacts and copies a predecessor's forward rather than mutating it. So geotag's `photos-26` log is left exactly as geotag produced it, and `photos-35-merge-log.json` is the new, merge-owned superset.

The result is additive: `photos-35-merge-log.json` records the complete journey — prep → geotag → merge — and a reader can answer "where is this photo now, and how did it get there?" from one file. A workspace that is **never merged** simply has no `photos-35` log; its authoritative record remains `photos-26-complete-log.json`, complete through geotag (the absence of a merge log reads as "not merged," not "incomplete"). (If the archival package was already copied to permanent storage before merge, `photos-35-merge-log.json` and `photos-31-merge-summary.json` are added to that stored record so it stays current.)

### 9.3 Textual output

Merge produces a textual summary separating: files moved into the library (placed new or renamed-to-avoid-collision); files already in the library (content identical, also removed from by-dest); files left in by-dest as un-merged leftovers (blockers — failed preconditions, un-fingerprintable library files, unexpected occupied targets); and confirmation that no library file was renamed or overwritten, that `photos-31-merge-summary.json` and `photos-35-merge-log.json` were written, the end-of-merge DB backup snapshot `photos-35-merge-ingest.db` captured (shared contract Section 13.4a), the archival package re-sealed (Section 9.4), and the workspace sealed terminal (Section 9.4). The user always knows what was moved, where, what was renamed, what remains in by-dest, and that the workspace is now sealed.

### 9.4 Re-sealing the archive and sealing the workspace

On overall success, merge performs two terminal bookkeeping steps (Section 10.3 steps 9–10; shared contract Sections 13.6, 13.7):

1. **Re-seal the archival package (automatic).** Merge has added to the durable record — it wrote `photos-35-merge-log.json` (copied forward from `photos-26` and extended with library destinations), captured `photos-35-merge-ingest.db`, and wrote `photos-31-merge-summary.json` — so the package finalize sealed no longer reflects the full state. Merge re-assembles the archival package (shared contract Section 13.2) to include these and re-writes the self-describing manifest with updated SHA-256s. This is **automatic, not a separate command**: the operator gets the complete, library-aware archive as a matter of course. Merge re-seals by re-bundling the now-current artifacts (a read of each, not a mutation of another phase's file, shared contract Section 13.0a); it does not re-run geotag's finalize logic or re-derive geotag's portion of the record (which is why geotag's finalize remains a distinct, manual step — it is freely re-run and expensive to repeat, shared contract Section 13.1 / 13.6).

2. **Seal the workspace terminal.** Merge records a durable terminal/sealed marker (merge run id, `library_root`) as a **separate `photos-00-sealed.json` file alongside the workspace guard** — not a field written into the guard itself (shared contract Sections 5.1, 13.7). Thereafter **every media-mutating script — prep, geotag, and merge — refuses to run on this workspace** (prep's `prune-quarantine` is the sole exception, as it only reclaims recoverable quarantine copies and touches no controlled content, shared contract Section 13.7 item 2), because a merged workspace is not a clean slate even though its by-dest is now empty of photos (its SQLite DB, ledgers, library-file fingerprint cache, per-phase DB snapshots, per-phase logs, and sealed archive all persist; residuals may remain in `1-strays`, `2-missing-metadata`, `3-redundant-jpgs`, `4-videos-by-date`, and the quarantine tree). The durable seal marker — not by-dest emptiness — is the authority for "this workspace is finished." To process more media, the operator starts a **fresh workspace** (new control directory, new SQLite DB) and runs from the start (init); the permanent library is shared across workspaces (the library-side lock, Section 12, exists for exactly this). Sealed means sealed: there is no confirming re-merge and no recovery utility — a dump dropped into a sealed workspace is left untouched and the scripts warn to start fresh (Section 3 precondition 0; shared contract Section 13.7).

Both steps happen only on **full success** — defined precisely as: every by-dest photo reached a terminal disposition (moved into the library, or confirmed already in the library) and **no un-merged photo remains in `6-photos-by-dest`**. If any file is still un-merged — a **blocker** (un-fingerprintable library file at a collision, unresolved conflict, or a failed move) or an interrupted/crashed run — the result is `partial` or `failed`: merge writes **no** seal and **no** re-seal, leaving the workspace re-runnable. The operator resolves the blocker (e.g. fixes the unreadable library file or the config) and **re-runs merge**, which converges; the seal is written only once the leftover set is empty. This guarantees a sealed workspace has nothing left to merge, and that a blocker never strands a recoverable file in a sealed (and therefore frozen) workspace. (A blocker is left in by-dest, not lost; merge never deletes an un-merged file, merge spec Section 11 / non-goal 6.)

---

## 10. Plan / dry-run / execute lifecycle

The whole merge run — `plan`, `dry-run`, and `execute` — runs under the workspace lock and the library-side lock, both acquired at startup and held until exit (Section 12). Planning and dry-run are non-mutating but still run inside the locks. The steps assume the locks are held.

### 10.1 Plan

`plan` produces a serialized plan, written to the control directory as **`photos-30-merge-plan.json`** (the merge-phase plan artifact, preceding the `photos-31` summary; shared contract Section 5), which `dry-run` summarizes and `execute` consumes and revalidates. It contains: merge plan id, plan/schema version, `library_root`, the ordered move list (each: by-dest source path, mapped library target, and — where a collision was detected during planning — the resolved disposition: **already-in-library** (identical content; the move reduces to removing the by-dest source), or **renamed-incoming** (different content; place under a safe alternative target, then remove the source)), detected blockers, warnings, per-file preconditions (the by-dest content fingerprint reused from prep's cache — stable because it is EXIF-invariant — plus the file's *current* size/mtime stat-ed at plan time, since geotag's metadata writes changed them from prep's recorded values; any library-file fingerprint computed for a planning-time collision check, cached per shared contract Section 13.4), the dependency fingerprints (`photos-24`/`photos-25`/handoff), and a summary. The by-dest enumeration is built from the finalized record — the handoff joined to `photos-24`'s rename operations by content fingerprint — not from a disk-name scan, because geotag renamed by-dest files without re-keying the handoff. Planning mutates nothing — neither the library nor by-dest nor the summary; the only durable side effects permitted are writing `photos-30-merge-plan.json` itself and populating the library-file fingerprint cache for files it had to fingerprint, which is cache content, not a mutation of any photo.

### 10.2 Dry-run

`dry-run` validates the saved plan and reports a concise summary of the placements and resolved collisions that would execute (move counts by disposition, any blockers, and the path to the full plan), without mutating. The full exact set of placements is the saved `photos-30-merge-plan.json` itself, available for review at that path; dry-run summarizes the real plan rather than dumping it, and is never a separate simulation. If no saved plan is present, it stops and directs the operator to run `plan` first.

### 10.3 Execute

`execute` applies the validated plan. It must:

1. confirm the workspace lock and the library-side lock are held (both established at run start, Section 12);
2. revalidate every recorded dependency and per-file precondition; reject the plan before any mutation if stale, missing, or unverifiable, or if produced by a different tool/version/schema;
3. take a pre-mutation snapshot where configured (the `zfs` block, shared contract Section 3), honoring `snapshots_required` — applicable where the **library** resides on a snapshot-capable dataset; snapshots remain strictly optional (shared contract Section 3). Merge's snapshot targets the **library** volume (where its placements land), not the workspace tree, and is **labelled for its phase** (e.g. a `merge` label distinct from prep's and geotag's) so it never collides in name with another phase's snapshot even on a shared dataset; the record is carried into `photos-31-merge-summary.json` either way. A required snapshot that cannot be taken aborts before any placement;
4. apply only the planned **moves**, each verified no-clobber **at execute time** and performed atomically or atomic-equivalent across filesystems (Section 11; shared contract Section 15): for each file, immediately before placing, confirm the library target is not occupied (re-checking, since the library may have changed since planning), place under the plan's recorded safe-alternative name for a genuine collision discovered only now, never onto an occupied target, and — once the library copy is verified in place — **remove the by-dest source**. A library file is never renamed or overwritten;
5. journal every move's **confirmed completion**, persisted incrementally as each file finishes (single-writer, main thread), so a re-run can re-derive per file — from the filesystem plus the recorded content fingerprint — whether it is not-yet-placed, placed-but-source-not-removed, or fully moved, and apply only the outstanding work (Section 8);
6. the only SQLite merge writes is the **library-file fingerprint cache**, and it is populated during *planning* (Section 10.1) — execute adds no database rows. Each file's library destination is the durable record of `photos-31-merge-summary.json` and the merge log `photos-35-merge-log.json` (Section 9), **not** a SQLite table: those JSON artifacts already carry, per file, where it landed and whether it was renamed, so a write-only destination table would have no reader (merge is terminal, and its own resume derives state from the filesystem + journal, not the database). The fingerprint cache is captured in the end-of-merge DB snapshot (step 8) as usual;
7. write `photos-31-merge-summary.json` and the merge transformation log `photos-35-merge-log.json` (copied forward from `photos-26-complete-log.json` and extended — never editing `photos-26`, shared contract Section 13.0a) only on overall success (Section 9);
8. capture the end-of-merge database backup snapshot `photos-35-merge-ingest.db` on overall success — a consistent, atomic copy of the live `photos-00-ingest.db` (shared contract Section 13.4a);
9. **re-seal the archival package** on overall success — re-assemble the package (shared contract Section 13.2) to include the merge log, the merge summary, and the end-of-merge DB snapshot, and re-write its self-describing manifest with the updated SHA-256s (shared contract Section 13.6). This is automatic, not a separate command;
10. **mark the workspace terminal (sealed)** on overall success — record the durable terminal/sealed marker (merge run id, `library_root`) as a **separate `photos-00-sealed.json` file alongside the workspace guard** (shared contract Sections 5.1, 13.7), after which prep and geotag refuse to process new media in this workspace (prune-quarantine excepted, shared contract Section 13.7 item 2);
11. emit the textual summary (the locks are released at process exit, not as a step of `execute`).

Execution must not patch or recompute a stale plan, and must never rename or overwrite a library file. If a target that planning found free is occupied at execute time by **identical** content, execution treats the file as already-in-library and removes the by-dest source (no library write); if occupied by **different** content not anticipated by the plan, the item is a blocker and stays in by-dest (the plan's safe-alternative allocation is used only where the plan already recorded it for an anticipated collision) — never a clobber. The by-dest source removal is always the **last** step for a file, after its library copy is verified; a crash before that leaves the file safely in by-dest (Section 8). The re-seal and the terminal mark (steps 9–10) happen **only on full success** — every by-dest photo moved into or confirmed already in the library, with no un-merged photo left in by-dest (Section 9.4). A `partial` run (any remaining blocker) or a `failed`/crashed run writes no seal, leaving the workspace re-runnable so merge can be resumed or re-run after the operator clears the blocker (Section 8).

### 10.4 Concurrency, determinism, and observability

Merge's per-file work — the copy to the library volume, the copy-verification fingerprint (Section 11 step 2), the atomic rename into the final target, and the by-dest source removal — may run **concurrently** under `-j`/`--jobs`, on the same discipline prep applies to fingerprinting/extraction (prep `photos-1-prep-workflow.md` Section 17) and geotag applies to its metadata writes (geotag `photos-2-time-gps-workflow.md` Section 29.3). Concurrency is a throughput device only and **must never change semantic results** (the placement decisions, the anti-collision names, or the final summary). The discipline:

1. **The move set is fixed before any concurrent work.** Locks, precondition checks, plan revalidation, and the optional pre-mutation snapshot (Section 10.3 steps 1–3) run single-threaded; the per-file move batches and all anti-collision target names are decided deterministically at plan time (Sections 6, 7). Only the application of those already-decided moves is parallelized — execution never *decides* placement concurrently.
2. **Per-file isolation.** Each file's place-then-remove sequence is an independent unit touching only that file's source, its temporary, and its final target; a worker mutates no shared state and returns a per-file result the executor aggregates. Targets do not contend because anti-collision names were allocated against the whole batch (and the colliding library names) at plan time, treating every name as occupied for the allocation (Section 7), and the execute-time no-clobber check re-verifies each target free immediately before its own atomic rename (Section 11).
3. **Deterministic aggregation.** Results are merged in a deterministic (by-destination, then path-sorted) order so the journal, the per-destination and global counts, the resume facts, and the failure/blocker list in `photos-31-merge-summary.json` are identical regardless of job count or completion order. Two safe job counts produce the same summary content (modulo run-metadata timestamps and the recorded `jobs` value, Section 9.1 item 9).
4. **Single-writer journal and SQLite.** The execution journal goes through a single controlled writer on the main thread, never from worker threads — the same rule prep and geotag follow. (Execute writes no SQLite at all: the library-file fingerprint cache was populated single-threaded during planning, and the per-file library destination is recorded in the JSON artifacts, not the database — so single-writer holds trivially during the concurrent move pass.)
5. **Library lock held throughout.** The library-side lock (Section 12) is held for the entire concurrent pass, so all of this run's parallel placements are still serialized against any *other* workspace's merge into the same library. Concurrency is within a single merge run; it never relaxes the cross-run library exclusion.
6. **Observability.** Long-running execution is visible: phase-level log lines (locks, validate, snapshot, place, verify, journal, cache, summary, re-seal, seal) and live aggregate progress for the concurrent move pass, with the journal — not the progress output — as the durable record.

Job count is run metadata, not a semantic dependency (it changes only throughput).

---

## 11. Atomic, cross-filesystem move

Merge **moves** files into the library, but the library frequently lives on a different filesystem/volume than the workspace, so a same-inode `rename` (and any atomic OS-level move) is generally unavailable. Merge therefore realizes the move as a safe **place-then-remove** sequence that preserves the shared atomicity guarantee (shared contract Section 15 item 3) and never loses a file:

1. copy the by-dest source to a **temporary name on the library filesystem** (so the copy and the final library target live on the same volume);
2. verify the copy (size, and content fingerprint against the known by-dest fingerprint, so a torn copy is detected);
3. **atomically rename** the verified temporary into the final library target name — which was just re-verified free (execute-time no-clobber, Section 10.3);
4. **only now remove the by-dest source.** Until this step the file exists in by-dest; after it the file exists in the library. The source removal is the file's last, journaled sub-step.

Crash safety follows from the ordering: a crash before step 3 completes leaves the file in by-dest and at most a discardable temporary in the library (never a half-copied file under the final name); a crash between steps 3 and 4 leaves the file **in both** the library (complete, verified) and by-dest — which resume resolves by recognizing the verified library copy and completing the source removal (Section 8). The file is therefore never lost and never left half-present under its final name. A library file is never deleted or overwritten at any step.

A failed move (copy error, verification mismatch, unexpected occupied target with differing content, permission error) leaves the library unchanged for that item **and leaves the source in by-dest** (it becomes an un-merged leftover), is recorded as a failure/blocker (Section 9.1 item 7), and is never journaled as a completed move — so resume does not treat it as done (shared contract Section 15 item 4).

---

## 12. Locking

Merge holds **two** locks for the duration of its run:

1. **The workspace lock** (shared contract Section 2), acquired at startup after the workspace root sentinel is verified, guaranteeing no other pipeline process touches this workspace concurrently — fail-fast, stale-detectable, released on exit.
2. **The library-side lock** (shared contract Section 15.2), keyed to `library_root` and realized as a **`.photos-merge.lock` dotfile in the library root**, guaranteeing that no two merge runs write the same library concurrently **even when they originate from different workspaces** (each with its own workspace lock). It follows the same fail-fast, stale-detectable discipline: a merge that cannot take the library lock exits without touching the library.

Both must be held before any library *content* access. Acquisition order is: workspace lock, then — still under the workspace lock — `library_root` config-validation and the `.photos-library` marker identity check (Section 3 precondition 5), then the library lock. The marker check necessarily precedes the library lock because the lock file is written into `library_root`: confirming the directory is a blessed library first ensures no `.photos-merge.lock` is ever dropped into a non-library directory. A merge that fails to acquire either lock, or finds the marker absent, exits cleanly having mutated nothing.

---

## 13. Idempotency and staleness examples

```text
Second run, workspace already sealed (prior merge fully succeeded)
  -> HARD-STOP: sealed means sealed; nothing is read for placement, nothing touched
  -> if files sit at the root or in 0-sources, also warn "likely new dump; start
     a fresh workspace; left untouched" (Section 3 precond 0)

Misplaced entry at the workspace root (loose file, non-managed folder, or symlink)
  -> HARD-STOP (Section 3 precond 0a; shared contract 5.3): the base holds only
     managed folders; a stray folder belongs in 0-sources; a symlink is barred

A managed 0-6 folder is missing
  -> HARD-STOP (Section 3 precond 0c): structure disturbed out-of-band; restore the
     folder(s) and re-run; merge never creates/repairs the workspace structure

Incoming file's target path is free
  -> copied to library, verified, renamed into place, then by-dest source removed

Incoming file collides, library file has identical content
  -> already in library; nothing written to library; by-dest source removed

Incoming file collides, library file has different content
  -> incoming copied under a renamed target (-001, ...), verified, placed;
     by-dest source removed; library file untouched

Library file at a collision cannot be read/fingerprinted
  -> that item is a blocker (no overwrite, no blind duplicate); LEFT in by-dest; rest continue per policy

library_root invalid (missing, malformed, or inside the workspace)
  -> config sanity-validation fails (Section 4); hard blocker; nothing moved

Workspace not finalized (no photos-26-complete-log.json)
  -> precondition blocker (Section 3); nothing moved; "run finalize first"

By-dest changed since finalize (photo added/edited + re-prep, but no re-run geotag)
  -> current handoff content_fingerprint != the one photos-24 recorded -> precondition 1a blocker
  -> nothing moved; "re-run geotag and re-finalize before merging" (avoids merging a
     present-but-ungeotagged photo). A no-op re-prep (run-metadata only) does NOT trip this.

By-dest no longer photo-only / development started since geotag
  -> precondition blocker (Section 3); nothing moved

Crash after library copy verified but before by-dest source removed
  -> file is in BOTH library and by-dest; re-run recognizes the verified library
     copy and completes the source removal; no file lost, no duplicate kept

Crash before a file's library copy is verified
  -> file remains in by-dest; re-run places it normally

Fully successful merge (no blockers)
  -> every file moved into / confirmed already in the library; by-dest empty of photos
  -> photos-31-merge-summary.json + photos-35-merge-log.json written; DB snapshot taken
  -> archive re-sealed; workspace marked terminal/sealed

Merge with a blocker (e.g. un-fingerprintable library file at a collision)
  -> blocked file LEFT in by-dest; status partial; NO seal, NO re-seal
  -> operator resolves the blocker and re-runs merge; seal only once by-dest is clear

Operator drops a NEW dump into a sealed workspace and runs any script
  -> every script refuses: workspace sealed (shared contract 13.7) -> use a fresh workspace
  -> it warns a likely new dump was detected (files at root or in 0-sources) and
     leaves the dump UNTOUCHED; the operator moves it by hand into a fresh workspace
     (manual recovery only — there is no collection utility)
```

---

## 14. Non-goals (merge must not do)

`photos-3-merge` must not:

1. rename or overwrite any existing library file (only incoming files are ever renamed);
2. build or maintain a library-wide index, or perform library-wide deduplication;
3. re-organize, re-deduplicate, or re-fingerprint by-dest content (prep's fingerprints are reused);
4. correct, recompute, or rewrite time, GPS, or filenames (geotag owns those; merge preserves geotag's final names except for the anti-collision incoming rename);
5. write the shared config `photos-00-config.json` (read-only, like geotag);
6. delete or mutate a **library** file, or remove an **un-merged** by-dest file (merge removes a by-dest source only after its verified copy is in the library — moving it, not deleting it; blockers and un-merged files are left in by-dest, Sections 8, 11). Merge does not tear down the workspace or clear leftovers — that is a separate operator decision;
7. perform the jpg/tif development breakout (a later library-side processing phase, geotag Section 7.1);
8. merge an un-finalized or stale workspace (Section 3);
9. write into, overwrite, or invalidate another phase's artifacts (shared contract Section 13.0a). The prep and geotag logs (`photos-15-prep-log.json`, `photos-26-complete-log.json`), the geotag job/decision artifacts, and the prep/geotag DB snapshots are complete before merge runs; merge writes only its **own** 3X artifacts (`photos-31-merge-summary.json`, `photos-35-merge-log.json`, `photos-35-merge-ingest.db`), copying the geotag log forward rather than editing it. A workspace that is never merged retains the full geotag-time record, intact, exactly as if this phase were not specified (shared contract Sections 13, 13.0a, 13.3 item 6, 13.5 item 4);
10. create or repair the workspace's managed `0`–`6` structure, or follow a symlink into or out of the managed tree. Folder creation is prep's init-only job; a missing managed folder is a hard-stop, not something merge rebuilds (precondition 0c), and a misplaced root entry or any symlink is blocked, never followed (precondition 0a; precondition 3; shared contract Section 5.3). (Creating a missing destination subdirectory *under `library_root`* to place a file is ordinary additive **library** placement, Section 6 — not a workspace-structure repair.)

---

## 15. Summary

This section restates the rules established above as a single reference. On any apparent conflict, the numbered sections above govern over this summary.

The merge workflow is:

```text
1. Acquire the workspace lock and the library-side lock.
2. If the workspace is already sealed (prior merge), HARD-STOP — sealed means sealed;
   touch nothing, and warn of a likely new dump if files sit at root or in 0-sources.
   Require an initialized workspace (else "run prep first"); block on any misplaced root
   entry (loose file, non-managed folder, or symlink — strict); require 0-sources empty;
   require the managed 0-6 structure intact (a missing folder blocks; merge never
   creates/repairs it). [shared contract 5.3]
3. Validate preconditions: geotag succeeded, workspace FINALIZED (required;
   run finalize first), by-dest photo-only and prep-consistent, config valid. Block if not.
4. Map each by-dest photo to its library target (preserve destination structure).
5. Where a target is free, plan a direct no-clobber move.
6. Where a target is occupied, fingerprint the library file (on the fly, cached) and the
   incoming file (reuse prep's fingerprint): identical -> already in library;
   different -> rename the INCOMING file safely, never the library file.
7. Validate the plan; execute only the validated plan.
8. MOVE files: copy to library (atomic / atomic-equivalent), verify, atomically
   rename into the re-verified-free target, then remove the by-dest source last.
   Already-in-library files: remove the by-dest source (no library write).
   Blockers: leave in by-dest. Journal both sub-steps per file.
9. Update SQLite (the library-file fingerprint cache only, from planning); record each file's library destination in photos-31/photos-35, not the database.
10. Write photos-31-merge-summary.json and photos-35-merge-log.json (copied
    forward from photos-26-complete-log.json and extended — never editing it),
    capture the end-of-merge DB snapshot (photos-35-merge-ingest.db), RE-SEAL
    the archival package, and SEAL the workspace terminal — all on success.
```

The most important rules are:

```text
Finalize (geotag-side) must have run first; merge refuses an un-finalized workspace.
The library is authoritative: never rename, never overwrite, never delete a library file.
On a name clash, rename the INCOMING file; resolve identity by content fingerprint.
No library-wide scan and no library-wide dedup; fingerprint only on collision, cache the result.
All moves are no-clobber and atomic — re-verified at execute time, not trusted from the plan.
Move, don't copy: remove the by-dest source only after its verified copy is in the library.
By-dest keeps only the un-merged leftovers (blockers); merged + already-in-library files move out.
Each phase writes only its own artifacts: merge writes its own log by copying photos-26 forward.
On success, re-seal the archive automatically and seal the workspace terminal (no reuse for new media).
All human-authored config is sanity-validated before use.
```

Merge is the terminal pipeline step for a workspace: it moves the geotagged, finalized photos into the permanent library, writes its own complete log, and — once by-dest is clear of photos — re-seals the archive and seals the workspace. Any file that cannot be merged is left in by-dest as a blocker and keeps the run `partial` (no seal) until the operator resolves it and re-runs. The library and the archival package live on; the workspace does not invite reuse — more media means a fresh workspace.
