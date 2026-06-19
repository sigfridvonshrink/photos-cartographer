# photos-cartographer

**Automatic, safe, whole-trip photo geotagging from GPX tracks — even when the camera's clock was wrong.**

photos-cartographer takes an unorganized dump of photos and videos, cleans and date-organizes it, then
**figures out where every shot was taken** by correlating each frame against a set of GPS tracks (GPX) —
*first inferring and correcting each camera's clock error automatically*, so a camera set to the wrong
timezone or drifting by minutes still lands on the right point of the track. Nothing is deleted and nothing is
changed without a plan that can be inspected first, and **every coordinate it writes is recorded with how it was
derived** — native, track direct-match / interpolated / extrapolated, or manual.

The aim is **100% geolocation coverage for the least possible effort**: every photo placed — precise where the tracks
allow, rough or manual where they don't — so a map view in a library like Immich shows the whole trip, not
just the frames that came with a location baked in.

It is built for **irreplaceable originals and large batches**: a whole holiday, several cameras and phones,
thousands of RAW and JPEG frames — resolved in one reviewable pass instead of photo-by-photo, then merged
cleanly into a permanent **folder-based photo library** (digiKam, or anything that reads a plain folder tree).
Almost all of the code that writes into those originals — the geotag phase — is exercised by an automated test
suite (**98% of lines, 97% of branches**), so a change that would misbehave is caught before it can touch a
photo.

> **Searches that might land here:** how to *geotag photos with no GPS from a GPX track*,
> *correlate photos to a GPS track when the camera time is wrong*, *batch/bulk geotag thousands of RAW photos
> non-destructively*, *auto-detect a camera clock offset / timezone for geotagging*, or a scriptable
> **GeoSetter / HoudahGeo / gpscorrelate / darktable alternative** for an entire trip at once.

## How it works in one minute

A clean **prep → geotag → merge** pipeline. Geotag resolves everything it can on its own, in an order chosen
so each supplied answer unlocks the most automatic work downstream:

1. **Prep** — consolidate the dump, normalize extensions, detect duplicates (quarantined, never deleted), and
   date-organize everything. Photos are then dragged into destination folders (`2026/France/Paris/Louvre`, …).
2. **Timezone** — establish each destination's timezone, from the photos' own evidence where possible,
   otherwise asked **once** and cascaded down the folder tree.
3. **Clock offset** — infer each camera's clock error by matching its already-located frames against the GPX
   track, then solve the rest from that. A wrong-timezone or drifting clock is corrected automatically; only
   the cameras the data can't disambiguate need a confirmation.
4. **Place** — geotag every frame the track can cover: **direct matches**, **interpolation** between track
   points, and **bounded extrapolation** off the ends. Each write is tagged with its method.
5. **Remainder** — whatever no evidence can locate is collected into a short, explicit worklist of what's
   actually left to decide.
6. **Merge** — move the finalized set into the permanent folder-based library, with a full transformation log.

Every run is a **plan that can be dry-run and inspected**; only a validated plan ever writes. Re-runs act on
the diff and are resumable after a crash.

## Documentation

- **[Quick start](docs/quickstart.md)** — download → prerequisites → the full end-to-end run (prep, sort into
  destinations, the geotag time → drift → GPS loop, execute, merge).
- **[Concepts](docs/concepts.md)** — the *why*: camera groups, per-day clock offsets, the by-dest tree, clock
  offset vs. GPS drift, and what cascades down the folder tree.
- **[Editor guide](docs/editor.md)** — driving the browser decision editor: the three views, validating drift,
  placing GPS, shift-click multi-select, and how edits reset/cascade.

The authoritative behavioral specifications live in [`spec/`](spec/) (see *How it works (the detail)* below).

## Decide in the browser, recorded in writing

When the pipeline needs a decision, it's made in a **small single-page web app the pipeline serves locally**
(`photos-cartographer edit`) — no build step, no CDN, works offline. It isn't a JSON editor: it shows a worklist of
only the open decisions, each with its proposal and the evidence behind it, and writes the choice back into
the durable decision records geotag reads. The loop is **edit → Save → re-run → reload**: save in the app,
re-run geotag to recompute everything downstream, reload the refreshed decisions. It only ever touches the
`user_decision` field and validates each entry before saving, so geotag never rejects what was written.

It has a view for each kind of decision:

- **Time** — a destination tree where each folder's timezone and clock offset can be accepted or overridden.
  A child shows the value it would inherit from its parent, badged with where that came from, and updates live
  when the parent is edited.
- **Drift** — for a camera whose offset isn't anchored to the track, **scroll a photo along its GPX segment**
  under a fixed crosshair until it lines up; the app reads the corrected clock offset off the track.
- **GPS** — for any shot the tracks couldn't place, an **interactive map beside the photo**: pan a crosshair,
  paste a `lat, lon` straight from Google Maps, or search a place by name. Copy a location once and paste it
  onto the next shot, or shift-select a run of photos and place them all at a single point.

So the ease of clicking and dragging on a map and the auditability of *every decision recorded in writing* are
the same act — and because re-running re-reads those records, nothing decided is lost or entered twice.

## Why it's different from GeoSetter, HoudahGeo, gpscorrelate, darktable

Those tools are excellent **interactive correlators**, but they share two assumptions this pipeline removes:

- **They trust the camera clock.** Correlating photos to a GPX track only works if the camera's time is right;
  when it isn't, the offset has to be discovered and typed in by hand, per camera, per trip.
  photos-cartographer **infers the offset automatically** — it matches a camera's already-geolocated or
  anchored frames against the track and solves for the clock error, then geotags the rest from that.
- **They work one import, one photo, one map-click at a time.** This pipeline is **batch, plan-driven, and
  safety-first**: it plans the whole job, allows a dry-run of the exact operations, and only then writes —
  never overwriting an original, always reversible by design.

If the offsets are already known and clicking each photo onto a map is fine, the classic tools are great. For
a pile of mixed-clock photos that need *correct placement with the least possible effort*, that is what this
is for.

## Every change is non-destructive **and** traceable

Photos are irreplaceable, so the whole design is **plan → validate → execute**, and every mutation is
explainable from the record afterward:

- **No mutation outside a plan.** Planning never touches files; execution applies only a validated plan whose
  preconditions still hold. The dry-run *is* the real plan, serialized and shown.
- **No clobber, no delete.** No operation overwrites existing media; duplicates are moved to a recoverable
  quarantine, never auto-removed.
- **Idempotent & resumable.** Re-runs act only on the diff; a crash mid-run is recoverable; already-placed
  files are recognized and skipped, not re-written.
- **Every GPS write records how it was derived.** Each photo's journey log (below) captures the full
  five-way provenance of its coordinates, and GPX- or manually-placed writes additionally carry a
  `GPSProcessingMethod` EXIF marker for downstream tools:
  - **native** — the camera's or phone's own GPS, preserved untouched (left exactly as-is, no marker written);
  - **GPX direct match** — a track point within seconds of the shot;
  - **GPX interpolation** — computed between the two surrounding track points;
  - **GPX extrapolation** — a bounded estimate just past the ends of a track;
  - **manual** — hand-entered coordinates, or a confirmed per-folder fallback.

  (The EXIF marker is coarser than the log: every GPX-derived write shares `GPSProcessingMethod=interpolated`,
  manual writes use `manual_locked` / `manual_fallback`, and native GPS is left untouched — the precise
  five-way derivation lives in the per-photo journey log.)
- **Manual coordinates are reversible.** A pinned pre-state ledger remembers what each file held before an
  override, so withdrawing a manual GPS decision restores the original — or clears the tag entirely if the
  file had no GPS to begin with. (Automated placements are simply recomputed from current inputs.)
- **A human-readable journey log per photo.** Finalize writes a per-file, content-fingerprint-keyed JSON log
  of every transformation between ingestion and final placement — clock offset applied, resolved UTC,
  timezone chosen, GPS method, every rename — each step linked to the decision that caused it. The merge step
  carries it forward with the final library path.

## Designed to ask for the least

Every other tool treats geotagging as a **manual operation performed by hand** — supply the offset, supply the
coordinates. Even the advanced ones leave a camera's clock offset to be *calculated* manually, when many of
those offsets could be derived automatically from a single correct input. photos-cartographer treats
geotagging as a **constraint-propagation problem** and converges on the **minimal sufficient set of human
decisions** — and it **orders the questions so each answer unlocks the most automatic work downstream**,
shrinking not just *repeated* questions but the *total number* of them. It never asks for the geolocating to be
done by hand, never asks for a value the data can derive, only for the inputs the data truly can't supply —
each at the point where it resolves the most — and never twice for the same fact.

So it works as a funnel that resolves everything it can before asking anything:

1. **Timezone first.** Establish each destination's timezone — from the photos' own evidence where possible,
   otherwise once by hand.
2. **Then clock offsets.** Infer each camera's clock error against the GPX tracks; only the cameras the data
   can't disambiguate need a confirmation.
3. **Then place everything placeable.** Geotag every frame the tracks can cover — direct matches, interpolation
   between points, bounded extrapolation off the ends.
4. **Then resolve only the true remainder.** What no evidence can locate is collected into a short, explicit
   worklist: the minimum that's actually left.

Every decision is also **reused, not re-asked.** A timezone set once feeds the offset and placement steps
downstream. A decision made on a parent destination **cascades recursively** to its children unless they
override it. A manual coordinate or confirmed offset is remembered across re-runs. So input is requested only
for what is *truly undetermined* — and the moment something becomes derivable from an earlier answer, it isn't
asked again.

This is why the *order* matters: a single well-placed answer high in the funnel — one timezone, one confirmed
anchor — can let the pipeline solve **every** camera's clock offset on its own, where a traditional tool would
require each offset to be worked out and typed in by hand.

**Propagation is opt-out, not opt-in.** Set a fact once near the top of the folder tree — a trip's timezone, a
city's GPS fallback — and it flows down to every destination beneath it *automatically*, because a place nested
inside another can scarcely sit in a different timezone than its parent. Each child **auto-adopts** the
inherited value — it doesn't block and doesn't ask, it just shows where the value came from — and a child is
overridden **only when the inherited value is visibly wrong** (an override then re-roots the chain from that
point down). **Leaving a cell untouched *is* the decision to accept it**, so the common case costs zero clicks.
It stays safe, too, because every value remains overridable and is validated before use, and a value is
auto-adopted only where the folder geometry makes it a sound default.

## Safety model

Photos are irreplaceable, so the whole design is **plan → validate → execute**:

- **No mutation outside a plan.** Planning never touches files; execution applies only a validated plan whose
  preconditions still hold.
- **Dry-run is the real plan**, serialized and shown — not a separate simulation path.
- **No clobber** — no operation overwrites existing media; destinations are reserved first.
- **Quarantine, not delete** — duplicates are moved to a recoverable quarantine, never auto-removed.
- **Idempotent & resumable** — reruns act only on the diff; a crash mid-run is recoverable.
- **Provenance-preserving** — identity is a decoded-pixel fingerprint, invariant under in-place metadata
  writes and renames, so each file's full history stays attached to it across every transformation.

## How it works (the detail)

The pipeline is **specification-driven** — behavior is defined by the documents in
[`spec/`](spec/), and the code follows them. Start with
**[`spec/README.md`](spec/README.md)** for the architecture and the full motivation/safety model, then the
per-phase specs:

| Document | Scope |
|---|---|
| [`photos-1-prep-workflow.md`](spec/photos-1-prep-workflow.md) | **Phase 1 — prep:** consolidation, extension normalization, dedup/quarantine, date-organization, cache/handoff. |
| [`photos-2-geotag-workflow.md`](spec/photos-2-geotag-workflow.md) | **Phase 2 — geotag:** timezone resolution, automatic camera-clock-offset inference, and track-based GPS placement. |
| [`photos-3-merge-workflow.md`](spec/photos-3-merge-workflow.md) | **Phase 3 — merge:** safe merge of the finalized working set into the permanent folder-based library. |
| [`photos-shared-contract.md`](spec/photos-shared-contract.md) | Facts all phases share: the run lock, the `.photos-ingest/` control directory, `photos-00-config.json`, the registry, formats, `gpx_root`, and the end-to-end operator loop. |

## Requirements

The pipeline is **Python 3** and shells out to a few standard command-line tools (it doesn't bundle them):

- **exiftool** — reads and writes photo time/GPS metadata (run as a persistent `-stay_open` worker).
- **ImageMagick** (`magick` / `identify`) — the decoded-pixel fingerprint that gives each photo a stable
  identity across metadata writes and renames, plus the editor's photo previews.
- **ffmpeg** — the stream fingerprint used to date-organize and de-duplicate videos.

SQLite (the cache and decision database) comes in through Python's standard library, so there's nothing extra
to install for it. **ZFS** is optional: when configured, the pipeline can take a pre-mutation snapshot before
any write, but the safety model — journal, recoverable quarantine, no-clobber, filesystem-as-truth — stands on
its own without it. The decision editor vendors its front-end (Leaflet — no CDN, no build step);
its map tiles and place search use OpenStreetMap/Nominatim at runtime and degrade gracefully offline.

## Layout

- `photos_pipeline/` — the pipeline package: `photos_1_prep.py` / `photos_2_geotag.py` /
  `photos_3_merge.py` (the three phases) + `photos_utils.py` (shared `CONFIG` + utilities) + `cli.py`
  (the combined `photos-cartographer` entry) + `editor/` (the locally-served Time/Drift/GPS decision app — a map-based web UI — that drives the worklist above).
  Run a phase with `python3 -m photos_pipeline <phase> <subcommand>` (from the repo root),
  or build the self-contained `photos-cartographer` zipapp with `tools/build-pyz`.
- `spec/` — the authoritative specifications. `tests/` — the test suite.
  `tools/` — build + test helpers. `.githooks/` — pre-commit / pre-push.

## Tests and coverage

The geotag phase — the one that writes time and GPS into irreplaceable originals — is the most heavily tested,
at **98.4% line / 96.8% branch** coverage. Across the whole codebase the suite covers **90.9% of lines and
86.7% of branches**; the lighter areas are the merge phase and the editor's local server, neither of which
writes metadata into the photos.

| Component | Line | Branch |
|---|---:|---:|
| prep (`photos_1_prep`) | 90.0% | 83.5% |
| geotag (`photos_2_geotag`) | 98.4% | 96.8% |
| merge (`photos_3_merge`) | 84.3% | 80.6% |
| shared (`photos_utils`) | 89.4% | 83.4% |
| cli | 87.5% | 75.0% |
| editor server | 78.8% | 76.7% |
| **Total** | **90.9%** | **86.7%** |

Run the suite from the repository root (`conftest.py` puts the repo root on `sys.path`):

```bash
python3 -m pytest -q
```

See `CLAUDE.md` for the full build/test/CLI contract and the seeded config defaults.

## Why this exists

I built this after years of frustration with geotagging photos by hand: typing in offsets, clicking shots onto
a map one at a time, and still ending up with gaps. It does the tedious parts automatically and asks only for
what it truly can't work out, so geotagging a whole trip stops being a chore. It's made first for my own
archive and shared as-is, in case it's useful to anyone with the same problem.

## License

Apache License 2.0 — see [`LICENSE`](LICENSE) and [`NOTICE`](NOTICE). The bundled Leaflet library keeps
its own BSD-2-Clause license (`photos_pipeline/editor/web/vendor/leaflet/LICENSE`).
