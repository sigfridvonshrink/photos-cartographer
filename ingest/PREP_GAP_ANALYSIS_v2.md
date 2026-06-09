# `photos-1-prep` — Compliance Gap Analysis v2 (post init/closure spec rework)

Gap analysis of `ingest/photos-1-prep` against the **updated** specs (merged 2026-06-09):
`10_photos-1-prep-workflow.md`, `10_photos-shared-contract.md`, and the new
`10_photos-3-merge-workflow.md`. The v1 analysis (`PREP_GAP_ANALYSIS.md`, all 26 items done)
was against the prior specs; this v2 covers only what the init/closure rework newly requires.

Severity: **High** = breaks the new model / blocks conformance · **Med** = real deviation,
non-blocking · **Low** = polish/cleanup.

Scope note: the **merge phase** (`photos-3-merge`) is a brand-new, separate script and is *out
of scope for prep*. Prep's only merge obligations are indirect: honor the seal marker (G2.3),
produce the prep audit log that calibration/merge carry forward (G3.1), and the per-phase DB
snapshot (G3.2). Building `photos-3-merge` itself is a later, separate effort.

---

## 0. Headline

The spec moved from a 6-folder (`0-source`…`5-photos-by-dest`) model to a **7-folder `0`–`6`
model** (`0-sources`, new `1-strays/`, `2-missing-metadata`, `3-redundant-jpgs`,
`4-videos-by-date`, `5-photos-by-date`, `6-photos-by-dest`) and added a **workspace lifecycle**
(uninitialized → initialized → sealed). Three behaviors prep currently implements are now
**reversed**: (a) non-media stays in `0-source` → must move to `1-strays/`; (b) dumped folder
trees are flattened into `0-source` → must be left in place (no flatten); (c) root-loose files
are consolidated → must be **blocked** on an initialized workspace. Prep also currently
*requires* the sentinel to exist (`RootGuard.check_sentinel`, `:2507`) — it must instead
**create** it (last) when initializing. Two new end-of-prep artifacts are required. The
already-shipped Phase 9 (atomic no-clobber) and Phase 10 (config validation) are now **codified
in the spec and already conformant**.

---

## 1. Folder model overhaul (`0`–`6`, strays, no-flatten) — **High**

| # | Requirement (spec §) | Status | Evidence | Action |
|---|---|---|---|---|
| **G1.1** | Folders renumbered to `0-sources`/`1-strays`/`2-missing-metadata`/`3-redundant-jpgs`/`4-videos-by-date`/`5-photos-by-date`/`6-photos-by-dest` (prep §3) | **Divergent** (old `0-source`…`5-photos-by-dest`) | `managed_folders` `:1520`; every folder literal: dedup priority, band guard, organization routing, `5-photos-by-dest/` by-dest prefix checks, handoff `folders_scanned` | Centralize folder names in one place; shift the dedup priority ladder, the band-misplacement guard (video under `5`/`6`, image/raw under `4`), organization routing, and **every `5-photos-by-dest/` prefix → `6-photos-by-dest/`** (validator read-only guard, move-aware, preconditions) |
| **G1.2** | New `1-strays/<plan-id>/`: non-media (`other`) moved out of `0-sources`, **structure preserved**, inert (not fingerprinted, not cached, not logged, not in the package), excluded from scan (prep §3.2, §7.6, §18) | **Divergent** | Phase-7 routing leaves `other` in `0-source`; no strays folder; `1-strays/` not in the scan-skip set | Add a Stage-5 `move_no_clobber` routing `other`-class files to `1-strays/<plan_id>/<rel-under-0-sources>`; add `1-strays/` to the directory-skip set (alongside `.photos-ingest/`, quarantine); never fingerprint/cache/handoff/log strays |
| **G1.3** | **No flattening** of `0-sources` — dumped folder trees stay on disk; output-name collisions resolved **in memory** at planning via the `-NNN` allocator (prep §7.2) | **Divergent** (Phase 3b flattens trees into `0-source`) | nested-dump walk `:1558-1571`; "Consolidate into 0-source" op `:1911-1932` | Remove the disk consolidation/flatten ops; leave trees in place under `0-sources/`; the by-date suffix allocator already de-collides organized outputs in memory (keep that) |
| **G1.4** | `other`-class files are **not fingerprinted at all**; the *absence* of a fingerprint is never a blocker (prep §9) | **Partial** (a sha256 `hash` is computed for every file incl. `other`, and `other` is deduped by it) | `hash_file` runs for all classes `:1775`; dedup key `ch_str = content_hash or hash` `:2059` | Stop fingerprinting/deduping `other`; route to strays (G1.2). `other` never enters a content-equality decision |

> G1.1–G1.4 are one coupled change (the new `0`–`6` + strays model) and should land together.

---

## 2. Workspace lifecycle: initialization & seal — **High**

| # | Requirement (spec §) | Status | Evidence | Action |
|---|---|---|---|---|
| **G2.1** | **Initialize** an uninitialized workspace (no sentinel): create any missing `0`–`6` folder + control dir, **move every base entry not part of the managed structure (files *and* whole trees, structure preserved, no flatten) into `0-sources/`**, excluding the managed/control/dot dirs (prep §3.1, §7.1) | **Missing** (prep hard-fails when the sentinel is absent) | `RootGuard.check_sentinel` raises if guard missing `:536`, called `:2507`; no init path | Detect "uninitialized" (no guard); on an init run, plan the `mkdir`s + base-entry moves into `0-sources/` |
| **G2.2** | Sentinel `photos-00-workspace-guard` is **written last**, only after every other op succeeds (so a crashed init re-enters harmlessly); base-is-folders-only afterward (prep §14.3 step 11, §3.1) | **Missing** (the guard is a *precondition* today, never written by prep) | check at `:2507`; nothing writes the guard | On an init run, append a final execute step that writes the guard after success; idempotent no-op when already initialized |
| **G2.3** | **Sealed/terminal workspace** guard: a merged workspace carries a terminal marker (in/alongside the guard); prep **hard-stops, mutates nothing**, and warns if a likely new dump sits at the root or in `0-sources` (prep §6.2 item 1, shared §13.7) | **Missing** | no seal concept anywhere | At startup (after the lock, with the sentinel check), read the terminal marker; if present, hard-stop touching nothing + emit the new-dump warning. (Merge writes the marker; prep only honors it) |
| **G2.4** | **Loose file at the root of an *initialized* workspace** is a hard block (strict, dotfiles included) — dumps belong in `0-sources/` (prep §6.2 item 2, §3.1) | **Divergent** (prep consolidates root-loose files into `0-source`) | root `os.listdir` consolidation `:1554+` | On an initialized workspace, replace root-file consolidation with a hard blocker; only the init path (G2.1) ever moves base files |

---

## 3. New end-of-prep artifacts — **High / Med**

| # | Requirement (spec §) | Status | Evidence | Action |
|---|---|---|---|---|
| **G3.1** | `photos-15-prep-log.json` — human-readable, **content-fingerprint-keyed** per-photo transformation log of all prep actions (ext-norm, consolidation-on-init, redundant-jpeg, dedup/quarantine with evidence, organization, provisional rename); **complete & self-sufficient**; written on success; **maintained incrementally** across runs; carried forward by calibration (prep §16.1, shared §13.0/§13.3/§13.3a) | **Missing** (only the handoff is written) | no prep-log; `handoff_path` only `:photos_utils:87` | Build a per-photo `journey` from the validated plan + retained journals; write deterministically at the handoff gate; update incrementally on re-prep (move recognition) |
| **G3.2** | `photos-15-prep-ingest.db` — **transactionally-consistent** DB backup snapshot (SQLite backup API / `VACUUM INTO`), under the lock, **no-clobber + atomic** (temp → verify → atomic rename), on success; bundled in the package (shared §13.4a, §13.2) | **Missing** | no snapshot logic | At the end-of-prep gate, `VACUUM INTO` a temp path then atomic-rename to `photos-15-prep-ingest.db`; refresh on each successful prep run |
| **G3.3** | Retention sufficient to reconstruct the prep journey; **fail/warn** if insufficient rather than emit a deceptively-complete log (shared §13.3a, prep §16.1 item) | **Partial** (per-run journals already retained, not overwritten) | journals `journal-<id>.json` retained | Confirm retained journals + DB suffice for G3.1; warn + mark the log partial if not |

---

## 4. Already conformant (now codified in the spec) — verify only

| # | Requirement (spec §) | Status | Note |
|---|---|---|---|
| **G4.1** | Execute-time **atomic no-clobber**, re-verified at the instant of the op (prep §14.3 step 4, shared §15) | **DONE** (Phase 9: `_move_no_clobber`/`renameat2`) | Spec now mandates exactly this; conformant |
| **G4.2** | **Config sanity-validation** before use (prep §6.3, shared §14) | **Mostly DONE** (Phase 10 `validate_config`) | Verify coverage vs §6.3/§14.1 (paths, zfs prefix, IANA tz, filename format, numerics). `library_root` validation deferred until the merge config key is seeded |
| **G4.3** | Media identified by **decoded-content fingerprint** — ImageMagick `identify` (photo) / `ffmpeg` stream MD5 (video), tool/version recorded & version-bound (prep §9) | **DONE** | Terminology only ("hash"→"fingerprint"); behavior already matches |

---

## 5. Reporting, terminology, cleanup — **Med / Low**

| # | Requirement (spec §) | Status | Action | Sev |
|---|---|---|---|---|
| **G5.1** | Summary §19: blockers now include **sealed workspace** + **loose root file**; add confirmation that `photos-15-prep-log.json` and `photos-15-prep-ingest.db` were written; report strays moved (prep §19 items 10, 13) | **Missing** (depends on G2.3/G2.4/G3.x) | Extend the run report once those land | Med |
| **G5.2** | Handoff: rename "hash algorithm" → "content-fingerprint algorithm"; `folders_scanned` reflects the new `0`–`6` names + strays mutability (prep §16) | **Divergent** (old names/terms) | Folds into G1.1; rename the handoff field | Low |
| **G5.3** | Byte SHA-256 is **reserved for artifacts**; media is never *identified* by a byte hash (shared §9.1) | **Dead-once-G1.4** (not a violation today) | Prep computes a whole-file SHA-256 for **every** file (`hash_file` `:1775`) into the `file_cache.hash` column (`:1840`), separate from the identity `content_hash`. It is **already unused for media** — the only live read is the dedup fallback `ch_str = content_hash or hash` (`:2059`), which fires solely for `other`-class files (the handoff-status `elif record.get('hash')` branch `:1213` is unreachable: media uses `content_hash`, `other` is forced `not_applicable` `:1220`). Once `other` → `1-strays/` and is no longer deduped (G1.4), the `hash` field has **no remaining live use** → drop computing/storing the per-file byte SHA-256 for managed media. Not a conformance violation today (prep never *identifies* media by it), just wasted work; do it **after** G1.4 | Low |
| **G5.4** | New config key `library_root` + merge policy is seeded in the template (consumed by merge; shared §4.3 item 7) | **Missing** | Add `library_root` (+ merge policy block) to `photos_utils.CONFIG` so the seed is forward-compatible; validate it (G4.2) | Low |

---

## 6. Suggested sequencing

The folder model and the lifecycle are the load-bearing changes; everything references the new
names, so do them first.

1. **Phase A — Folder model** (G1.1–G1.4): renumber to `0`–`6`, add `1-strays/` routing + skip,
   stop flattening, stop fingerprinting/deduping `other`. One cohesive PR; update every test.
2. **Phase B — Lifecycle** (G2.1–G2.4): initialization path (create structure, move base dump,
   sentinel-written-last), root-file hard block (initialized), sealed-workspace guard.
3. **Phase C — Audit artifacts** (G3.1–G3.3, G5.1): `photos-15-prep-log.json`, the DB backup
   snapshot, retention check, and the summary additions.
4. **Phase D — Cleanup** (G5.2–G5.4): handoff terminology, vestigial media `hash`, seed
   `library_root`, close any config-validation gaps.

(Then, separately and later: the new `photos-3-merge` script — a different phase entirely.)
