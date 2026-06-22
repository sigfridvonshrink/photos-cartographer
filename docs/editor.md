# Editor guide

The decision editor is a small single-page web app the pipeline serves locally. It's where you answer
the few questions geotag can't decide on its own — timezones, risky clock offsets, and un-placeable
photos — each shown with its proposal and the evidence behind it. It writes those answers back into the
durable decision records geotag reads.

This guide assumes you've reached the geotag loop in the [quick start](quickstart.md); the [concepts
guide](concepts.md) explains the ideas (camera groups, day buckets, drift, cascading) the views act on.

---

## Launching it

```bash
cd /path/to/workspace
photos-cartographer edit
```

Like every phase, `edit` operates on the **current-directory workspace** (no workspace-naming
argument). It refuses to run if the cwd isn't an initialized workspace. It serves on port **8765** by
default (climbing to the next free port if busy) and binds all interfaces, so you can reach it from a
laptop browser while SSH'd into a server — it prints a clickable `http://<host>:8765/` link. Use
`--host 127.0.0.1` for local-only, `--port N` to choose a port. When bound to loopback (`--host
127.0.0.1`), startup also prints a ready-to-copy `ssh -L …` tunnel command for reaching it from your
local machine. A lock prevents two editors on the same workspace at once. Stop it with Ctrl-C.

### Demo mode — zero setup

```bash
photos-cartographer edit --demo
```

A read-only tour on bundled example data — **no workspace, nothing written**. The fixtures, web assets,
and map library are all packaged inside the executable, so `--demo` works straight from the downloaded
release: it needs only a `python3` host and a browser. (No photo previews in demo — it touches no
workspace files. Map tiles and place search need internet but degrade gracefully offline.) It's the
fastest way to see what the three views look like before you have real data.

---

## The working loop

The editor edits decisions; it does **not** recompute the pipeline. The loop is always:

> **edit → Save → re-run `photos-cartographer geotag plan` in a terminal → reload the page**

There is deliberately **no in-app "re-run" button** (it proved error-prone). Instead, every gate and
stale banner tells you to re-run in a terminal and reload. Until you do, anything the editor shows about
*outcomes* is advisory — geotag computes the authoritative result on the next run.

The editor only ever writes the **`user_decision`** field of each decision cell, round-tripping every
other field exactly as geotag produced it. The **Save** button is disabled if any field is invalid (it
won't let you save a bad timezone or out-of-range coordinate), so geotag never has to reject what you
wrote.

---

## The three views, and why they're gated

The header toggles between **Time → Drift → GPS**, in that order — and the order is enforced:

- **Time gates Drift** — you can't validate drift until the time decisions are complete (drift checks
  offsets that must already exist).
- **Drift gates GPS** — the GPS view is locked until drift is resolved (a wrong, unvalidated offset
  would place photos at the wrong point).

If you edit a Time or Drift decision, the downstream views show a "decisions changed since the last
run — re-run `geotag plan` and reload" notice until you do. That's the same gating the CLI applies,
surfaced in the UI.

---

## Time view

A recursive tree of your destinations. For each one you settle two things:

- **Timezone** — most destinations auto-resolve. A child with no timezone of its own shows a live
  preview of the value it would **inherit** from its nearest resolved ancestor, badged
  `inherited ⟵ <ancestor>`; the badge updates as you edit ancestors. To override, pick an IANA zone from
  the dropdown; or tick "accept proposed" to adopt a system proposal. A manual zone you set **re-roots
  the chain** — it becomes the basis every destination beneath it inherits (until one of them overrides
  in turn). Authoritative only after you re-run.
- **Clock offset** — per (camera group, destination, day) bucket. Unlike the timezone, offsets **never
  inherit** — each day's bucket stands alone (the editor shows no inherited badge for them). See
  [why grouping is per-day](concepts.md#why-grouping-is-per-day-within-a-destination).

Container folders (those holding only sub-destinations) appear badged `container` — you author
decisions on them purely to propagate downward.

---

## Drift view

The drift view lists the **at-risk** offset buckets: those whose offset is manual or timezone-derived
and that have **no GPS-anchored frame** — so nothing has ever checked that offset against the track.
This view sits between Time and GPS and is **gated on time being complete** (the offsets it validates
must already exist; that's why drift can only be used once timezones are done).

For each bucket you confirm the offset by sliding a representative photo along its GPX segment under a
fixed crosshair until it lines up:

- **Scroll the wheel** over the map to step the marker one track point per notch.
- **`[` / `]`** step one point; **`{` / `}`** (Shift) step ten.
- "Don't move" = accept the current placement — but you **must** actively affirm it. An untouched
  at-risk bucket **blocks** the run; inaction is never read as "no change." This is the load-bearing
  safety rule.

Confirming refines the offset without altering your Time decision; the corrected offset feeds the
recomputed UTC on the next run.

---

## GPS view

A worklist of only the photos the automatic sources (native GPS, GPX match) couldn't place, plus a
per-destination **folder fallback**.

**Folder GPS fallback** — a single coordinate that places any photo in that destination nothing else
could. It cascades downward like the timezone (badged `inherited ⟵ <ancestor>`), but unlike the
timezone it is **never auto-applied and never blocks**: an inherited fallback is a proposal you *may*
confirm. A fallback you author **re-roots the chain** for descendants. It ranks last in placement (after
native GPS, per-file manual locks, and GPX), and is recorded as a manual (reversible) write so it's
always clear it wasn't measured. A fallback you set — manual or accepted-inherited — can be taken back
with **Clear** (resets the folder to *no fallback*; descendants then re-inherit from above, or tick
*accept inherited* to adopt the parent's instead).

**Placing individual photos** on the map beside the photo:

- **Paste `lat, lon`** straight from Google Maps into the coordinate field — it commits on paste and
  jumps the map to that point.
- **Search a place by name** (OpenStreetMap/Nominatim) — submit with Enter or the button; picking a
  result moves the map, then you "use map center" to set it.
- **Pan the crosshair** and "use map center" to drop a point by eye.
- **Copy / paste a location** between photos — "copy location" stashes the coordinate (and writes
  `lat, lon` to your system clipboard); "paste" applies it to the current photo. Consecutive nearby
  shots open centred where you last placed one.

**Place many at once with shift-click:** click a photo to select it (and set an anchor), then
**shift-click** another *in the same destination* to select the contiguous run between them. One
location you set then applies to every photo in the run. (Shift-clicking into a different destination
starts a fresh selection — runs never cross destinations.)

---

## How edits reset things

Two reset behaviors worth knowing (both take effect on the next run):

- **Re-rooting** — authoring a manual **timezone** or **folder fallback** at a folder makes that the new
  basis its descendants inherit, replacing whatever flowed from higher up. A descendant that set its own
  value keeps it (it overrides).
- **Restaling** — changing an upstream timezone, offset, drift confirmation, or fallback marks the
  downstream artifacts (corrected UTC, the GPS decisions, the executable plan) stale; `geotag plan`
  recomputes them on the next run. Your authored decisions are **preserved** wherever their target still
  exists; if a target's context changed so a decision can't be safely applied, it's flagged for review,
  never silently dropped.

---

## Quick reference

| Action | How |
|---|---|
| Launch on a workspace | `photos-cartographer edit` (port 8765) |
| Zero-setup demo | `photos-cartographer edit --demo` |
| Apply your edits | Save → `photos-cartographer geotag plan` (terminal) → reload |
| Step a photo along the track (Drift) | scroll wheel, or `[` `]` (Shift `{` `}` for ×10) |
| Set a coordinate (GPS) | paste `lat, lon`, place-name search, or pan + "use map center" |
| Place a run of photos | click, then shift-click another in the same destination |
| Copy a location to the next photo | "copy location" → "paste" |
