# Concepts

The ideas behind photos-cartographer — *why* the pipeline is shaped the way it is. Read this once and
the [quick start](quickstart.md) and the [editor guide](editor.md) will make sense. For the safety
model and the tool comparison, see the [main README](../README.md) and the authoritative specs in
[`spec/`](../spec/).

---

## The workspace and its numbered folders

All work happens inside a **workspace**: a transient working area, separate from your permanent photo
library. A workspace is *initialized* the first time you run `prep` in a folder — that creates the
managed structure and a hidden control directory `.photos-ingest/` (config, decision files, journals,
the SQLite cache; `prep` skips this subtree wholesale, so it can never be mistaken for a photo).

The managed folders, by number:

```
0-sources/           a raw dump lands here; prep empties it after every run
1-strays/<plan-id>/  non-media set aside per run (structure preserved, inert)
2-missing-metadata/  media with no usable timestamp
3-redundant-jpgs/    JPEGs that have a RAW sibling
4-videos-by-date/    timestamped videos, in YYYY-MM-DD/ day folders
5-photos-by-date/    timestamped photos, in YYYY-MM-DD/ day folders
6-photos-by-dest/    YOU curate this: photos sorted into destination folders
```

`prep` does the mechanical work — consolidate, normalize, deduplicate (to a recoverable quarantine,
never deleted), and date-organize — landing photos in `5-photos-by-date/`. **You** then move photos
into `6-photos-by-dest/`; that curation is the one creative step the tool can't do for you, and it's
what every later phase reasons about.

After a workspace is **merged** into your library it is **sealed**: every phase refuses to touch it,
and new photos require a fresh workspace.

---

## Destinations and the by-dest tree

A **destination** is simply *the folder that directly contains a set of photos* inside
`6-photos-by-dest/`. That's the whole rule — a destination is not necessarily a leaf, and a
destination may contain nested destinations.

The recommended shape is a geographic hierarchy, e.g.:

```
6-photos-by-dest/
  2026/
    Belgium/
      Brussels/
        Atomium/          <- destination (holds photos)
        Grand-Place/      <- destination (holds photos)
      Bruges/
        Markt/            <- destination (holds photos)
```

The intermediate folders (`2026`, `Belgium`, `Brussels`) hold only sub-folders, no photos. The
pipeline still tracks them as **container destinations** — they exist so you can author a decision
once on a parent and have it flow down to every child (see *What cascades*, below).

**Why a hierarchy helps:** two facts — the timezone and the folder GPS fallback — inherit *downward*
through this tree. Set the timezone on `Belgium` once and every place beneath it adopts it; drop a GPS
fallback on `Brussels` and every leaf under it can fall back to it. A coherent, unitary structure
means you author each decision at the highest level where it's true and let it propagate, overriding
only where a leaf differs. It also keeps each "unitary group" of photos — one place, one visit —
together, which is exactly the unit the next two concepts operate on.

> Moving a photo between destinations is a real input change: it's re-evaluated under the new
> destination's timezone *and* clock offset on the next run.

---

## Camera groups

A **camera group** is the set of photos that share one physical camera's identity — derived by `prep`
from device-identity metadata (serial / make / model / owner) into a single `camera_group_key`,
computed once and reused everywhere. It is **not** a folder, a date, or a destination.

Why it matters: the headline trick — inferring a wrong camera clock automatically — works *per
camera*. The pipeline matches a camera's already-located frames against your GPX track to discover
that camera's clock error, then applies that one correction to the rest of *that camera's* photos.
That only makes sense within a single clock domain.

So the grouping has to be right:

- **Two cameras wrongly merged into one group** → one camera's clock error gets applied to the other's
  photos, sliding them to the wrong time and therefore the wrong place on the track.
- **One camera wrongly split into two groups** → a fragment with no GPS-anchored frame loses the
  evidence its other half has, forcing needless manual work and risking two inconsistent corrections
  for what was one clock.

A camera group also carries a **classification** (a normal camera vs. a smartphone) from config. A
phone usually records a correct timezone and is solved straight from its own metadata; a camera with a
wrong, timezone-less clock needs the clock-offset inference. An unrecognized camera stops geotag with a
ready-to-paste config snippet rather than guessing.

---

## Why grouping is per-day within a destination

A camera's clock error is **constant within one destination on one day**, but **not across days**. The
reason is human habit: travelling, you tend to set the camera to local time each morning — so the
offset is a per-day fact. A camera's clock also drifts and is sometimes reset between trips.

So the clock-offset decision is bucketed per **(camera group, destination, day)**. A place you visit on
two different days gets two independent offset buckets (keyed by the camera's own uncorrected calendar
date); a single visit that crosses local midnight splits into two by design. The common single-day
case stays a single bucket.

Each day's bucket gets its offset independently, in priority order:

1. **Self-anchored** — that camera's GPS-tagged frames *that day, that place* match the GPX track and
   reveal the offset directly. (This is the strong case — measured straight off the track.)
2. **Timezone-derived** — if the destination's timezone is known, the offset is computed from it
   (DST-aware). Must be confirmed, never auto-applied.
3. **Manual** — you enter it.

There is deliberately **no inheritance** between buckets: a correction you enter for one day applies
only to that day, never to a sibling day or a neighbouring place. This is the day-level refinement of
the rule "clock corrections vary between days and between destinations, never within a single day's
shoot."

---

## Clock offset vs. GPS drift

Two distinct ideas the pipeline keeps carefully separated:

- **Clock offset** — the *constant* correction between a camera's wall-clock and true UTC for one
  (group, destination, day) bucket. Ideally *measured* from GPX self-anchors. Physical drift between
  days/trips is handled structurally by re-deriving the offset per bucket, so it never contaminates
  another bucket.

- **GPS drift** — the *residual danger* that a clock offset which was **not** measured against the
  track (i.e. a manual or timezone-derived offset, on a bucket with no GPS-anchored frame) is silently
  wrong. Because GPS placement positions a photo purely from its corrected UTC, a wrong offset slides
  the **whole bucket** to the wrong point on the track — drift you'd never see.

photos-cartographer forces you to close that gap: a dedicated **drift-validation** step (between time
and GPS) makes you confirm each at-risk bucket against the track before any GPS is placed. Crucially,
**inaction is not consent** — an untouched at-risk bucket *blocks* the run; you must actively affirm
even "the offset is fine, no change." This is the load-bearing safety rule of the time→GPS ordering.

---

## What cascades down the tree (and what doesn't)

Exactly **two** facts inherit downward through the destination tree, via nearest-resolved-ancestor,
parent-first, parent→child only (never sibling→sibling):

| Fact | Inherits? | Auto-applied? | Reset on a manual edit? |
|---|---|---|---|
| **Civil timezone** | yes, downward | yes (inheritance/default auto-resolve) | a manual zone **re-roots the chain** at that node for its descendants |
| **Folder GPS fallback** | yes, downward | no — an inherited fallback must be **confirmed** | a manual fallback **re-roots the chain** at that node for its descendants |
| **Clock offset** | **no** | only a GPX self-anchor auto-applies | n/a — each day's bucket is re-derived from its own evidence |

**Re-rooting** is the behavior to internalize: when you author a manual timezone (or fallback) on a
folder, that value becomes the folder's effective value and the new basis its descendants inherit —
replacing whatever would have flowed from further up. On the next run, descendants that merely
inherited the old value re-point to the new one; a descendant that set its *own* value keeps it (it
overrides, and itself re-roots the chain for *its* descendants).

The **folder GPS fallback** is the per-destination "if nothing else placed this photo, put it here"
coordinate. It ranks last in GPS resolution — after native GPS, a per-file manual lock, and GPX
interpolation/extrapolation, and before "leave it unlocated" or "block." It is **optional and never
blocks**: an inherited fallback is offered as a proposal you *may* confirm, not a gate. A fallback
placement is recorded as a manual GPS write (reversible) so it's always clear it wasn't measured.

---

## Putting it together

The pipeline's order falls straight out of these concepts:

1. **Timezone first** — it's what lets a no-anchor offset bucket get a proposal at all, and it cascades.
2. **Clock offset (drift) next** — corrected UTC needs the offset; the drift gate validates the risky ones.
3. **GPS last** — placement is purely a function of corrected UTC, so it can't run until time is solved.

Each step unlocks the next, which is why the [quick start](quickstart.md) walks them in exactly that
order, and why the [editor](editor.md) gates Time → Drift → GPS.
