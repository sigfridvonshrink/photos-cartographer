# photos-cartographer

**Automatic, safe, whole-trip geotagging — even when your camera's clock was wrong.**

photos-cartographer takes an unorganized dump of photos and videos, cleans and date-organizes it, then
**figures out where every shot was taken** by correlating it against your GPS tracks — *first inferring
and correcting each camera's clock error automatically*, so a camera set to the wrong timezone or drifting
by minutes still lands on the right point of the track. Nothing is deleted and nothing is changed without
a plan you can inspect first.

It is built for **irreplaceable originals and large batches**: a whole holiday, several cameras and
phones, thousands of frames — resolved in one reviewable pass instead of photo-by-photo.

## Why it's different from GeoSetter, HoudahGeo, gpscorrelate, darktable

Those tools are excellent **interactive correlators**, but they share two assumptions this pipeline
removes:

- **They trust your camera clock.** Correlating photos to a GPX track only works if the camera's time is
  right; when it isn't, you must discover and type in the offset yourself, per camera, per trip.
  photos-cartographer **infers the offset automatically** — it matches a camera's already-geolocated or
  anchored frames against the track and solves for the clock error, then geotags the rest from that.
- **They work one import, one photo, one map-click at a time.** This pipeline is **batch, plan-driven,
  and safety-first**: it plans the whole job, lets you dry-run the exact operations, and only then writes
  — never overwriting an original, always reversible by design.

If you already know your offsets and like clicking each photo onto a map, the classic tools are great.
If you have a pile of mixed-clock photos and want them *correctly placed with the least possible effort*,
that is what this is for.

## Designed to ask you the least

Every other tool treats geotagging as a **manual operation you perform** — you supply the offset, you
supply the coordinates. Even the advanced ones leave you to *calculate* things yourself, like a camera's
clock offset, when many of those offsets could be derived automatically from a single correct input.
photos-cartographer treats geotagging as a **constraint-propagation problem** and converges on the
**minimal sufficient set of human decisions** — and, crucially, it **orders the questions so each answer
unlocks the most automatic work downstream**, shrinking not just *repeated* questions but the *total
number* of them. You are never asked to do the geolocating, never asked to hand-compute what the data can
derive, asked only for the irreducible inputs the data genuinely can't supply — each at the point where it
resolves the most — and never asked twice for the same fact.

So it works as a funnel that resolves everything it can before it ever asks you:

1. **Timezone first.** Establish each destination's timezone — from the photos' own evidence where
   possible, otherwise once from you.
2. **Then clock offsets.** Infer each camera's clock error against the GPX tracks; only genuinely
   ambiguous cameras need a confirmation.
3. **Then place everything placeable.** Geotag every frame the tracks can cover — direct matches,
   interpolation between points, bounded extrapolation off the ends.
4. **Then resolve only the true remainder.** What no evidence can locate is surfaced as a short,
   explicit worklist — the irreducible minimum.

Also, **every decision you make is reused, not re-asked.** A timezone you set feeds the offset and
placement steps downstream. A decision made on a parent destination **cascades recursively** to its
children unless they override it. A manual coordinate or confirmed offset is remembered across re-runs.
So you are asked only for what is *genuinely undetermined* — and the moment something becomes derivable
from an earlier answer, you are not asked again.

This is why the *order* matters: a single well-placed answer high in the funnel — one timezone, one
confirmed anchor — can let the pipeline solve **every** camera's clock offset on its own, where a
traditional tool would have you work out and type in each offset by hand.

**Propagation is opt-out, not opt-in.** Set a fact once near the top of the folder tree — a trip's
timezone, a city's GPS fallback — and it flows down to every destination beneath it *automatically*,
because a place nested inside another can scarcely sit in a different timezone than its parent. Each child
**auto-adopts** the inherited value — it doesn't block and doesn't ask, it just shows where the value came
from — and you override a child **only if you can see the inherited value is wrong** (an override then
re-roots the chain from that point down). **Leaving a cell untouched *is* the decision to accept it**, so
the common case costs zero clicks. It can't really get easier — and it stays safe, because every value
remains overridable and is validated before use, and a value is auto-adopted only where the folder
geometry makes it a sound default.

## Safety model

Your photos are irreplaceable, so the whole design is **plan → validate → execute**:

- **No mutation outside a plan.** Planning never touches files; execution applies only a validated plan
  whose preconditions still hold.
- **Dry-run is the real plan**, serialized and shown — not a separate simulation path.
- **No clobber** — no operation overwrites existing media; destinations are reserved first.
- **Quarantine, not delete** — duplicates are moved to a recoverable quarantine, never auto-removed.
- **Idempotent & resumable** — reruns act only on the diff; a crash mid-run is recoverable.

## How it works (the detail)

The pipeline is **specification-driven** — behavior is defined by the documents in
[`ingest/workflows/`](ingest/workflows/), and the code follows them. Start with
**[`ingest/README.md`](ingest/README.md)** for the architecture and the full motivation/safety model, then
the per-phase specs:

| Document | Scope |
|---|---|
| [`photos-1-prep-workflow.md`](ingest/workflows/photos-1-prep-workflow.md) | **Phase 1 — prep:** consolidation, extension normalization, dedup/quarantine, date-organization, cache/handoff. |
| [`photos-2-geotag-workflow.md`](ingest/workflows/photos-2-geotag-workflow.md) | **Phase 2 — geotag:** timezone resolution, automatic camera-clock-offset inference, and track-based GPS placement. |
| [`photos-3-merge-workflow.md`](ingest/workflows/photos-3-merge-workflow.md) | **Phase 3 — merge:** safe merge of the finalized working set into the permanent digiKam library. |
| [`photos-shared-contract.md`](ingest/workflows/photos-shared-contract.md) | Facts all phases share: the run lock, the `.photos-ingest/` control directory, `photos-00-config.json`, the registry, formats, `gpx_root`, and the end-to-end operator loop. |

## Layout

- `ingest/photos_pipeline/` — the pipeline package: `photos_1_prep.py` / `photos_2_geotag.py` /
  `photos_3_merge.py` (the three phases) + `photos_utils.py` (shared `CONFIG` + utilities) + `cli.py`
  (the combined `photos-ingest` entry) + `editor/` (the decision editor that drives the worklist above).
  Run a phase with `python3 -m photos_pipeline <phase> <subcommand>` (with `ingest/` on `PYTHONPATH`),
  or build the self-contained `photos-ingest` zipapp with `tools/build-pyz`.
- `ingest/workflows/` — the authoritative specifications. `ingest/tests/` — the test suite.
  `tools/` — build + test helpers. `.githooks/` — pre-commit / pre-push.

## Running the tests

From the repository root (`conftest.py` puts `ingest/` on `sys.path`):

```bash
python3 -m pytest -q
```

See `CLAUDE.md` for the full build/test/CLI contract and the seeded config defaults.
