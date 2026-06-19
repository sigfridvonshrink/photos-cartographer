# Photos pipeline — geotag and time-correct a shoot from your GPS track

*Engineered for safety: non-destructive, idempotent, and resumable — no photo is ever lost or
overwritten, and nothing is mutated without a validated plan.*

If you shoot with a **GPS logger running** (in my case UltraGPSLogger on my mobile) and want your photos
to end up correctly geotagged afterwards — including the frames the camera never tagged itself —
this is for you. Drop all your track files into one folder and the pipeline matches each photo
against the right point across the whole set; you don't sort tracks per shoot.

It does three things, carefully:

1. **Prep** — takes an unorganized dump of files and leaves a clean, deduplicated,
   date-organized working set, without ever destroying an original.
2. **Geotag** — resolves each photo to real UTC, **automatically figures out and
   corrects a wrong camera clock** by matching your geotagged frames against the GPX track, then
   geotags everything from the track and renames by corrected local time.
3. **Library merge** — once a shoot is geotagged and **finalized**, **moves** the staging tree into your
   permanent library (the merged files leave the workspace; anything that can't be merged stays put for
   you to deal with),
   **renaming the incoming file (never a file already in your library)** if a name would clash, recording
   exactly where every photo ended up, then re-sealing the complete archive and marking the workspace
   done — after a merge that workspace is **sealed**, and new photos go to a fresh one. (Sealed means
   sealed: every script then refuses to touch that workspace. If you dump new files into a sealed
   workspace by mistake, the scripts notice the likely new dump, tell you to start fresh, and leave your
   files **untouched** for you to move by hand — there's no automatic sweeping of a finished workspace.)

It is built around one assumption: **your photos are irreplaceable, so no photo is ever lost or
overwritten, and nothing is mutated without a validated plan.**

---

## Why this exists

Phones geotag perfectly and keep an accurate clock, so for snapshots this problem looks solved.
It isn't, for serious cameras. High-end bodies increasingly ship **without onboard GPS** (relying
on flaky phone-sync that catches *some* frames, not all), and their clocks **drift, miss DST, and
usually store a naive local time with no timezone at all.** The classic tool for fixing this from a
GPS track — GeoSetter — is effectively unmaintained, and nothing has cleanly replaced it.

So if you keep a **local, owned, correctly-tagged library** (mine feeds digiKam) and run a logger in
the field, you're stranded between aging tools and cloud services that don't care about correctness.
This is the reconciliation engine that fuses your camera's flawed self-report with your logger's
trustworthy track.

The capable tool that does the hard part well — reference-frame clock correction — is **Mac-only and
paid** (HoudahGeo). The other capable ones are Mac-only (Geolignment) or Windows-only and unmaintained
(GeoSetter) — none of them runs on Linux at all. The open-source tools that *do* run on Linux either do
manual-offset geotagging without the automatic clock inference, or don't treat your originals as a
reproducible, recoverable pipeline. This sits in that hole: it runs on Linux, it's open-source, and it's
built like a build system. See the comparison below.

---

## The core: automatic camera-clock correction

A GPS track is keyed to real UTC. Your camera clock is wrong and might be timezone-less. The track is
useless until the two are aligned. So the pipeline:

1. finds the frames that **do** have native GPS (phone-sync caught them),
2. matches each against your tracks (nearest point, or interpolation along a short segment under
   configurable distance/time thresholds), across the whole GPX folder,
3. derives the **camera clock offset** from those matches — ranked by confidence, **not averaged** —
   and proposes it **per (camera, destination)**: the same camera gets an independently-inferred offset
   in each destination it shot in, because a clock drifts (and gets reset) between trips, and a
   destination *is* a trip,
4. after you confirm (or auto-applies, per policy), resolves every frame to UTC and geotags the
   **un-logged majority** by interpolating along the track.

If it cannot, it asks you (and remembers your answers).

This idea isn't unique — HoudahGeo does reference-frame clock correction well (on Mac, paid). What's
distinct here is doing it on Linux, open-source, in a reproducible pipeline, with the offset inferred
automatically from your already-geotagged frames and confirmable before anything is written.
The clock correction is the *core mechanism*; the safety and reproducibility around it are the point.

---

## Safety model (why you can trust it on originals)

- **Plan → validate → execute.** Planning never mutates. Execution applies only a plan that
  re-validated against current state; stale plans are rejected before any change.
- **No-clobber everywhere — and re-checked at the last moment.** No operation overwrites the
  photographic content of an existing file. The safety doesn't rest on the plan being right: just
  before each move, rename, or library placement, the executor *re-verifies* the exact target is free,
  and the operation is atomic — so an interrupted run leaves either the old file or the new one, never a
  half-written one.
- **Everything you typed is sanity-checked.** Before anything runs, the values you authored — config
  paths, the ZFS snapshot prefix, timezones, coordinates, the filename format, and the decisions in the
  JSON files — are validated. A bad value (a malformed path, a typo'd timezone, an out-of-range
  coordinate) is reported as a specific, located error and blocks the run, rather than being silently
  coerced or half-applied.
- **Recoverable, not destructive.** Duplicates are *quarantined*, never deleted, and never
  auto-removed; you prune them explicitly when you choose.
- **Resumable.** A crash mid-run is recoverable — prep re-plans from the filesystem (which is treated
  as truth), geotag resumes its plan and skips already-applied operations, and merge finishes moving
  the files it hadn't yet placed (and never loses one — a file leaves the workspace only once its verified
  copy is in the library).
- **Read-only destinations.** Prep treats your curated `6-photos-by-dest` staging tree as read-only —
  it's scanned but never mutated; geotag writes only the corrected metadata/renames you've approved.
  And when a finalized shoot is merged into your permanent library, **library files are never renamed or
  overwritten** — on a name clash it's the incoming file that gets renamed, never the file already in your
  library.
- **Optional snapshots.** If you're on ZFS you can enable pre-mutation snapshots for clean-slate
  rollback — but they are **strictly optional**; the safety above does not depend on them.

One boundary: this no-clobber guarantee begins at the **first prep run**. It cannot protect a file
you overwrite *while dumping* — if your own copy command clobbers a same-named file in the drop
folder (`0-sources/`) before prep ever sees it, that loss is outside the pipeline's view. Dump each
source into its own subfolder or use a non-overwriting copy, and prep then preserves everything (prep
`photos-1-prep-workflow.md` Section 7.2).

The full design is specified in four documents:

- `photos-1-prep-workflow.md` — the prep phase
- `photos-2-geotag-workflow.md` — the geotag phase
- `photos-3-merge-workflow.md` — the library-merge phase
- `photos-shared-contract.md` — facts the phases share (lock, config, formats, GPX root, the
  input-validation discipline, the execute-time no-clobber/atomicity rule, the archival package, the
  end-to-end operator loop, and the workspace lifecycle: initialization, the strays folder, and the
  sealed terminal state)

These four are the **authoritative** behavioral specs. The decision *editor* that helps a human fill in
the JSON they produce has its own docs alongside its code — **non-authoritative and downstream of the
above** (if they ever disagree, the spec and code win):

- `../cartographer/editor/decision-json-reference.md` — the field-level shape of the decision
  artifacts (`photos-21`/`22`/`23`) the editor reads and writes.
- `../cartographer/editor/design-notes.md` — the editor's UI/architecture design notes.

For a user-facing walkthrough, see the guides in [`../docs/`](../docs/).

---

## It works with you, not against you

Safe doesn't mean rigid. All three phases are **idempotent** — they track what they've already done, so every
run changes only what actually needs changing:

- **Add a dump later and it does the diff.** Re-running reuses everything already fingerprinted, organized, and
  geotagged; only the genuinely new files get processed. A run over unchanged state is a no-op.
- **Your decisions stick.** Set a timezone or accept a clock offset once — reruns preserve it; you never
  re-answer a settled question.
- **Re-run anytime, even after geotagging.** New photos months later just flow through; already-processed
  files are left untouched.

Same mechanism as the safety, seen from the other side: because it tracks state and acts on the diff, it
never redoes settled work and never surprises you with churn.

---

## You decide, in writing — and you can change your mind

The tool never silently changes anything on its own. Every correction it makes — every timestamp,
coordinate, and rename — comes from a decision **you wrote into a plain JSON file.** The machine
proposes; you dispose; the file is the record of what you chose.

This is deliberate. I don't trust tools to mutate irreplaceable photos in ways I didn't author and can't
explain. So when something comes out wrong, there's always a specific recorded decision to point at —
*my* choice, which means I can find it, understand it, and fix it. And because decisions are just data
and nothing is destructive, you change the decision, re-run, and everything downstream re-derives. No
mutation is a one-way door.

Concretely: if you manually tag a photo's GPS and later delete that decision, the next run **undoes**
it — restoring whatever GPS the file had before, or clearing it entirely if it had none. (Manual GPS is
reversed from a saved pre-state; automated GPS is just recomputed; time and filenames are recomputed too,
since they place the file in the folder structure.) Withdrawing a choice removes its effect, not just its
re-assertion.

And the decisions are **kept** — and the record is whole at the end of *every* phase, not just at the
finish. By the end of **prep** you already have a complete, human-readable audit log of everything prep
did (`photos-15-prep-log.json`), plus a point-in-time backup image of the SQLite database as of the end of
prep — a full account even if you never geotag. By the end of **geotag**, an explicit finalize
step bundles an *archival package* — the config, the live SQLite database (and the per-phase DB backup
images), all the decision JSONs, and a consolidated **full transformation log**
(`photos-26-complete-log.json`): a per-photo record of every change each photo underwent from dump to
finished geotag, and why (the prep log carried forward and extended, not regenerated). That package
is **complete on its own** — if you finalize but never merge, you still have the full human-readable audit
log, the database images, and the job reports, exactly as if the merge phase didn't exist. And by the end
of **merge**, the same log is **additionally extended** with where each photo finally landed in your
library, and a final database image is captured — so a single entry traces the whole journey, dump →
corrected → its exact path in your library. Each phase only *adds* to a record that was already whole, and
each phase leaves its own retained database snapshot, so you keep a full image of what the pipeline knew at
every step; nothing earlier is ever lost or rewritten. It lands in one known place you keep alongside your
library — not scattered across per-file sidecars, and not (as with most tools) applied and forgotten. Years
later you can open one folder and see exactly what you did, and why.

---

## Assumptions and scope (read before trying it)

This is **built for my own workflow** and open-sourced in case it fits yours. It is opinionated:

- **Linux.** Built and run on Linux; that's where I use it. It's plain Python plus `exiftool` (metadata
  read/write), ImageMagick `identify` (the per-image **content fingerprint**), and `ffmpeg` (the per-video
  **stream-MD5 fingerprint**). Both fingerprints are taken over *decoded content*, not file bytes, so a
  photo or video keeps the same identity even when the pipeline rewrites a photo's EXIF or renames a file;
  non-media files aren't fingerprinted at all (they're set aside as *strays*, below). Whole-file SHA-256 is
  used only for the pipeline's own JSON/config artifacts, never to identify a photo. It may well work
  elsewhere, but I don't test on Windows or macOS and make no promises there.
- **GPS tracks** (GPX) from a logger. You dump **all** your track files into a single GPX folder
  (`gpx_root`) and geotag ingests the whole set, matching each photo against the right point
  across all tracks — no per-shoot sorting. No tracks at all, no geotag-from-track.
- **One destination = one coherent shoot, time-wise.** The clock correction is figured out and applied
  **per (camera, destination folder)**, not once per camera — because a camera's clock drifts (and gets
  reset) between trips, so its true offset differs from one destination to the next. The assumption that
  makes this work: you keep a single shoot in one destination, so a destination never spans a change in a
  camera's clock error. Corrections happen *between* destinations, never *within* one. (A nested subfolder
  is its own destination and gets its own correction; a destination where a camera shot nothing geotagged
  doesn't start blank — it inherits its parent destination's offset as a proposal to confirm, recursively
  down nested folders, and a manual offset you set at any folder re-roots what its sub-folders inherit.
  The same downward inheritance applies to a destination's **GPS "folder fallback"** coordinate and to its
  **civil timezone** — a nested folder proposes its nearest parent's fallback, and its nearest parent's
  timezone, for you to confirm — so you set sensible defaults once at a trip's root and accept or override
  them per level. (All three of these proposals are always confirmable, never auto-applied.))
- **A specific workspace layout** — numbered working folders (`0-sources`, `1-strays`,
  `2-missing-metadata`, `3-redundant-jpgs`, `4-videos-by-date`, `5-photos-by-date`, `6-photos-by-dest`).
  You drop dumps into **`0-sources`** (the one inbox); prep organizes the media out and moves any
  non-media into **`1-strays`** (a per-run subfolder, structure preserved, never processed again), leaving
  `0-sources` empty. The workspace is transient working space for one or more dumps, *not* your library:
  `6-photos-by-dest` is a staging area where a dump is organized and geotagged, then — by the merge
  phase — **merged into** your permanent library at a configured `library_root` elsewhere. It's structured
  to merge in cleanly (e.g. into digiKam), but workspace ≠ library, and the merge never renames or
  overwrites anything already in the library. A workspace is **single-use through to merge**: once its
  batch is merged, the workspace is sealed (its archive and database images are kept) and more photos go
  to a fresh workspace. (The one thing you can still do to a sealed workspace is **prune its quarantine**
  to reclaim disk — that only deletes recoverable duplicate copies and touches nothing in your library or
  the sealed record; every media-changing command refuses a sealed workspace.)
- **First run is forgiving; after that, use the inbox.** You don't have to set anything up before your
  first dump — drop files straight into a new empty folder and the first prep run *initializes* it
  (creating the numbered folders and moving your dump into `0-sources` for you), writing an
  "initialized" marker last so a crash mid-setup just re-runs cleanly. That convenience is a **one-time**
  thing: once a workspace exists, the inbox is `0-sources`, and a misplaced entry at the workspace root —
  a loose file, a stray folder, or a symlink — is treated as a misplaced dump and **blocks** until you move
  it (strictly — even a stray `.DS_Store`; a dumped *folder* belongs inside `0-sources`, and a symlink is
  barred outright rather than followed, since following it would escape the workspace). The full `0`–`6`
  structure is likewise an invariant: if one of those folders goes missing, the tools stop and tell you to
  restore it rather than silently rebuild it (a missing folder means something deleted it, possibly with
  media inside). The asymmetry is deliberate: bootstrap once, then there's an inbox and you use it.
- **`exiftool`** for metadata read/write.
- **Config lives in the workspace.** Prep seeds a `photos-00-config.json` in the workspace on first run;
  after that it's authoritative and you change settings by hand-editing it. It's hashed and archived with
  everything else, so each workspace records the exact config its processing ran under.
- **ZFS is optional** — only needed if you want pre-mutation snapshots; everything works without it.
- Designed to feed a **digiKam**-style by-folder library, though nothing forces that downstream.

If those don't match how you work, this may be more friction than it's worth — and that's fine.

---

## How this compares to existing tools

These are all good tools — several are better than this one at the thing they focus on. The point of
this table isn't that they're bad; it's that **none of them sits where I needed to be**: runs on Linux,
open-source, working against a local owned library, and built as a reproducible pipeline rather than an
interactive one-shot. If one of them fits you, use it.

| Tool | Open source | Runs on Linux | Auto clock-fix from track | Reproducible pipeline | Why not for me |
|---|---|---|---|---|---|
| **HoudahGeo** | No | No (Mac only) | Yes (reference frames) | No (interactive) | Mac-only and paid |
| **GeoSetter** | No | No (Windows only) | Partial | No (interactive) | Windows-only, effectively unmaintained |
| **Geolignment** | Yes | No (Mac only) | Yes (geosync slider) | No (interactive) | Mac-only native app |
| **gpscorrelate** | Yes | Yes | No (manual offset) | No (one-shot CLI) | No auto clock inference; no safety/idempotency envelope |
| **darktable** (geotag module) | Yes | Yes | No (reference-photo/manual) | No (catalog-bound) | Manual offset; lives inside darktable's catalog, not a standalone pipeline |
| **exiftool `-geotag`** | Yes | Yes | Manual (`Geosync`, multi-point) | No (primitive) | It's the engine, not a workflow — no organize/dedup/decisions/safety |
| **Lightroom** (Map) | No | No | No (manual offset) | No | Proprietary/subscription; not a local-owned-library pipeline |
| **Google / Apple Photos** | No | Web only | No | No | No track-based correction; not local/owned; no correctness control |

The detail behind the table:

- **HoudahGeo** — the closest in capability. It does the part I care about most: it trusts photos that
  already carry timezone info and uses them as reference points to correct the cameras that don't, then
  matches against the track. Genuinely good. But it's Mac-only and proprietary, so it can't run on Linux.
- **GeoSetter** — for years the free Windows standard, map-driven and capable. Windows-only and now
  effectively unmaintained, which is much of why this gap exists at all.
- **Geolignment** — open-source and nicely designed around a geosync slider with multi-track folders.
  It's a native macOS app, so again no good off the Mac.
- **gpscorrelate** — open-source, cross-platform, scriptable, handles multiple GPX files. But the clock
  offset is something you supply manually (e.g. from a photo of a GPS screen); it won't infer the offset
  from the frames that already have GPS, and it's a one-shot correlate-and-write, not a recoverable
  pipeline that organizes, deduplicates, tracks decisions, and resumes after a crash.
- **darktable** — the geotagging module is solid and cross-platform, but it's a reference-photo/manual
  offset workflow bound to darktable's own catalog/sidecars, rather than a standalone reproducible
  pipeline feeding a folder-based library.
- **exiftool `-geotag`** — the actual metadata engine (and `Geosync` even supports multi-point drift
  correction). It's a primitive, not a workflow: no organization, dedup, decision-tracking, or safety
  envelope. This project can sit *on top* of exiftool rather than competing with it.
- **Lightroom Map module** — fine if you're already in Lightroom, but proprietary/subscription, manual
  offset, and oriented around the catalog rather than a local owned folder tree.
- **Cloud (Google / Apple Photos)** — effortless for phone shooters and solves the *loss* fear, but does
  no track-based correction, isn't local or owned, and gives you no control over correctness.

What's distinct here, then, isn't a new technique — the matching and offset ideas exist above. It's the
*treatment*: a Linux, open-source, reproducible pipeline (plan/validate/execute, idempotent,
recoverable, crash-resumable, decisions captured as editable artifacts) for people who keep a local owned
library and run a logger. That combination is the niche the tools above leave open.

---

## Status

Personal project, shared as-is. Issues and PRs welcome from anyone with the same setup, but it is not
a supported product and I'm not chasing adoption — I built it because my photos are worth the rigor.
