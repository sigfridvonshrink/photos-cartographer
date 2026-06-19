# Decision editor — design notes

> **NON-AUTHORITATIVE.** Design/UX decisions for the decision-editing app, recorded so the build has a
> shared picture. The JSON it edits is described in `decision-json-reference.md`; the authoritative
> behaviour is the geotag code (`../photos_2_geotag.py`). These notes are a plan, not a contract.

## 1. What it is

A small single-page app that helps a human resolve the open decisions in a workspace's
`photos-21-time-decisions.json` / `photos-23-gps-decisions.json`. It is **not** a generic JSON editor:
it surfaces a to-do list, shows each decision's proposal + evidence, captures a choice, validates it,
and writes back. Its **only hard requirement is conforming output** (see the reference's "conformance
contract"): it edits **only `user_decision`**, round-trips everything else, and never recomputes
`proposal`/`effective_*`/`status` — geotag does that on the next run. Any in-app outcome it shows
is **advisory**; the loop is **edit → Save → re-run `photos-cartographer geotag plan` → reload**.

## 2. Stack (decided)

- **Local Python server**, stdlib only — launched as `photos-cartographer edit`, which (like every phase)
  operates on the **current-directory workspace**; there is no workspace-naming argument, and it
  refuses to run if the cwd is not an initialized workspace. It serves the SPA, reads/writes the
  workspace's `.photos-ingest/` decision JSON, and serves **photo previews** (embedded JPEG via
  exiftool/ImageMagick — already repo deps). `--demo` is the only no-workspace mode: read-only on the
  `examples/` fixtures, so it runs with nothing installed.
  - The editor is **folded into the `photos_pipeline` package** (`photos_pipeline/editor/`): `server.py`
    plus the `web/` and `examples/` assets, which the server reads as **package data via
    `importlib.resources`**. So it ships inside the single `photos-cartographer` zipapp — no separate bundle,
    no `./bundle` step. Previews still need exiftool / ImageMagick and degrade gracefully when absent.
- **No-build SPA**: plain vanilla ES modules — a hand-rolled DOM builder (`el()` + a manual `render()`),
  **no framework**. **Leaflet** (the map) is the only vendored library, under `web/vendor/` (no CDN at
  runtime, no build step, works offline).
- Rationale: matches the repo's Python/CLI, no-build, system-deps-only ethos; zero new package managers.
- **Front-end tests**: the pure logic in `app.js` (validation, offset⟷UTC/local date math, the §6
  resolution rules, inheritance previews) is unit-tested with **Node's built-in runner** (`node:test`,
  no npm) in `tests/*.test.mjs` — run via `tools/jstest`, also in CI and the pre-push hook. `app.js`
  exports those functions and guards its auto-start (`if (typeof document !== "undefined") main()`) so it
  imports cleanly in Node. The server is tested in Python (`tests/test_serve.py`); DOM-building
  functions aren't covered yet (would need jsdom — deliberately out of scope for the no-deps harness).

## 3. Architecture

One **shared model** = the loaded artifacts + a pending **`user_decision` overlay** (the edits). The
views are pure projections of that model, so the user can **switch views mid-edit** with no loss. Saving
applies the overlay onto the artifact JSON (round-tripping every other field) and writes it.

## 4. UI

**Master–detail shell:** header (workspace • view toggle • to-do/stale count • Reset • Save) → a compact
**list** (left) + a persistent **side-panel** editor (right), separated by a **draggable divider** (the
split width is clamped and persisted in `localStorage`; the map is resized live as you drag). Selecting a
cell anywhere opens it in the panel. The panel itself does **not** scroll: a **fixed top** holds the
title, status, the **decision controls**, and the effective preview — always visible — over a **scroll
area** (the only thing that scrolls) that, for a GPS coord cell, orders the **map first** — directly
under the pinned decision so a paste/edit's jump-to-zoom is visible without scrolling — then the photo,
then the proposal evidence last; non-coord cells just show the proposal.

- **Two views, switchable mid-edit** (one shared model): **Time** defaults to a **recursive destination
  tree** — a parent shows its descendants' proposals; you can override any node; inheriting cells are
  badged "inherited from `<ancestor>`" and overrides badged "overridden"; a **live, advisory** inheritance
  preview updates children when you override a parent (the rule mirrored is just "nearest **resolved**
  ancestor → child with no own decision"; badged *preview*, authoritative on re-run). **GPS** defaults to
  a **worklist** of review items (+ per-destination fallback); automatic-only destinations collapse to a
  counts row. Either view is switchable to the other. File-less **container** destinations (parents with
  no media of their own, Section 10.1 of the time spec) appear in both views badged `container` —
  editable propagation points that hold defaults for their children and never sit on the to-do list.
- **GPS-depends-on-time gate.** GPS placement is derived from each photo's resolved UTC, and the pipeline
  only (re)generates `photos-23` once **every** time decision is resolved. The editor surfaces that gate:
  while the time artifact `requires_user_input`, the GPS view is **locked** behind an explanatory banner
  (finish time, then Re-run) instead of showing an empty or stale list; and once any time decision is
  changed, a **stale** banner on both views reminds you a Re-run is needed before GPS reflects it (tracked
  by `timeChangedSinceRerun`, cleared on Re-run). Both notices are skipped in demo mode (its curated
  fixtures intentionally pair an incomplete time artifact with a GPS one).
- **Drift view + GPS-depends-on-drift gate.** A third view (`photos-22-gps-drift-validation.json`, geotag
  workflow §22a) sits between Time and GPS. It lists the **at-risk buckets** — a manual/timezone-derived
  clock offset with no native-GPS anchor — that GPX *can* validate, and must be confirmed before GPS is
  placed (an unconfirmed bucket could silently mis-place a whole batch along the track). It is gated behind
  time (`time.requires_user_input`) and in turn gates GPS (`drift.requires_user_input` locks the GPS view).
  A drift edit sets `driftChangedSinceRerun` so the GPS view shows a stale banner until Re-run; both flags
  clear on Re-run.
  - **Scrub-on-track control.** The drift panel shows a representative photo above a max-zoomed map of the
    bucket's covering GPX segment (`proposal.track_segment`). The **scroll wheel** slides the photo along the
    track under the centre crosshair (`map.js` `mapPicker({track, onScrub})`); each step computes
    `corrected_offset_seconds = (chosen track point's UTC) − (that photo's camera-naive)` (pure `scrubOffset`)
    and writes it with `confirmed:true`. The marker **seeds** at the point the current offset implies
    (`scrubSeedIndex`), so "don't move" = the current placement and any scroll is a deliberate correction.
    A frame picker lets the operator cross-check other photos in the bucket (each must yield the same offset;
    the last scrub wins). **Confirming without moving** (the pinned checkbox / "clear correction") is a
    **zero scrub** — `confirmed:true` with an empty correction — and must be explicit; inaction never resolves.
  - **No-merry-go-round invariant.** The script extracts the track segment ±2 days
    (`gpx_anchor_max_clock_error_seconds`) around the bucket. Since valid offsets are capped at ±1 day, any
    two valid offsets differ by ≤2 days, so **every reachable scrub correction is already inside the loaded
    segment** — a scrub never needs a Re-run to fetch more track. The editor validates the computed offset
    against the ±1-day bound (`validOffset`) and flags a point that falls outside it. Re-extraction happens
    only when a *time* decision changes (edit → Save → Re-run → reload), which legitimately shifts the window;
    the editor never touches GPX itself.
- **Side-panel editor** for the selected cell: the proposal + evidence, the decision control, a **photo
  thumbnail** (review items), a **context map**, and a live **effective-outcome** preview with
  client-side validation. For an **offset** proposal the raw anchor list is **collapsed**: the consensus
  correction, then up to three "N photos → ±Xh Ym" groups — each naming one photo by its full by-dest
  path and showing that photo's camera time → **corrected local time** (via the destination timezone,
  with the usual "set the timezone" nudge when unresolved) — plus a note counting frames skipped (no
  nearby track / a track only from another trip). The data comes from the proposal's `groups`/`skipped`
  (geotag); the editor only renders it. The camera and corrected sides are formatted **identically**
  (`DD Mon YYYY` + `HH:MM:SS`); when the date is unchanged it's shown once and the arrow carries only the
  time correction (`22 Mar 2026 · 13:25:21 → 13:24:18 (Europe/Brussels)`).
- **Status is edit-aware.** The status chip normally reflects the last geotag run (`needs input` /
  `stale` / `auto` / `resolved`), but a **pending edit supersedes it**: once your working decision would
  resolve the cell (mirroring the §6 resolution rules) it shows `resolved` next to the `edited` chip
  rather than the now-stale `needs input` — advisory until Re-run, like the effective-outcome preview.
- **Specialized controls:**
  - **Timezone:** a full IANA-zone **drop-down**; accepting the proposal mirrors it into the field and
    **locks** the drop-down (unaccepting frees it). The "accept" box is disabled when there's nothing to accept.
  - **Clock offset:** **three always-visible choices, click-to-activate** — *accept proposal* (the
    automatic offset, never edited → `accept_proposal`), *manual offset* (the **h/m/s spinner**:
    hover-scroll or focus + ↑/↓ nudges just that unit by ±3600/±60/±1 s, clamped to ±86400 s;
    `preventDefault` keeps the wheel off page scroll), and *anchor real-UTC* (a `datetime-local` picker,
    only for a `gpx_self_anchor` proposal). Exactly one is active; clicking another **deactivates the
    others and they update to the active value** — the two manual views are synced (offset ⟷ anchor camera
    time + offset), while the automatic stays the proposal. Only the active view is editable; the rest are
    read-only but **still show the effective offset** (nothing hidden). Manual offset and anchor-UTC are
    both stored canonically as `manual_offset_seconds` (which one is active is per-cell UI state); the
    picker writes the derived offset, so the editor never persists `manual_real_utc` (a hand-edited one is
    still honored). Below the choices a common **Impact** line shows what the effective offset does to the
    anchor photo: `camera local → corrected local (tz, UTC …)` — same compact format as the proposal
    groups (one date copy when invariant; UTC in parens after), with a no-anchor fallback (offset +
    formula). A small "clear"
    returns the cell to unset (geotag auto-resolves / inherits). The picker writes the derived
    offset, so `manual_real_utc` isn't persisted by the editor (a hand-edited one is still honored). The
    *accept* row notes the proposal's source (`from timezone <tz>` for a `timezone_naive` proposal); when
    there's no proposal at all the editor says to set the destination timezone and Re-run to derive one
    from the local time. **Per-date buckets:** a destination spanning >1 naive day keys its offset cells
    `<group>@<YYYY-MM-DD>` (a camera set to local time each morning has a per-day offset). The time view
    groups these under the camera group and **collapses equal-proposal undecided days into one cluster
    row** (e.g. all summer days → one row, winter → another), so the operator confirms each distinct
    offset once; editing a cluster **fans out** to all its days (`ref.peers`). A chevron expands a cluster
    to per-day rows for a divergent manual edit; a day with its own decision breaks out automatically.
    Offsets do **not** inherit between destinations (only the timezone and folder fallback do).
  - **GPS coordinate / fallback:** a **single `lat, lon` text field** (accepts a value pasted straight
    from Google Maps, e.g. `50.525434, 4.269781` — comma- or space-separated; parsed by the one canonical
    `parseLatLon`) plus a **zoomable map with a fixed centre crosshair** — pan/zoom under it, "use map
    center" → take `map.getCenter()`. A valid field entry / paste (committed on paste, or on Enter / blur) writes the
    coordinate, refreshes the clipboard, and **jumps the map to that exact point at full zoom**
    (`map.setView(c, getMaxZoom())`) — an exact coordinate wants the closest view, not the old one; a bad
    non-empty entry is kept verbatim and flagged invalid. As the map pans, the live crosshair centre is
    **mirrored into the pinned `lat, lon` field** (display only — unless it is being typed in — so the
    always-visible top box reflects where the crosshair sits without scrolling down to the map readout).
    The in-editor *copy/paste-location* pair still **`panTo`s keeping zoom**. Reference pins (effective /
    inherited / folder fallback) and a marker
    for the current decision give context, and the map seeds its view to the current coordinate, **else
    the last coordinate the operator placed** (so the next un-located photo opens centred where the
    previous one was set — consecutive shots are usually near each other), else the nearest known
    reference. A **copy/paste** pair under the map remembers a found location (set on every pick, or via
    *copy location*, which also writes `lat, lon` to the system clipboard) and **paste**s it onto another
    cell, so a place found once need not be re-navigated. **Multi-select:** shift-click another review
    photo in the **same destination** to select a **contiguous run** (a multi-selection never crosses a
    destination boundary); the side panel then **applies one location to every photo in the run** (a
    `peers` ref whose edits fan out). The **photo** (embedded-JPEG preview from the server) appears as a
    thumbnail in the pinned "Your decision" box and as a hover preview in the worklist; the **map** sits
    directly under the decision (map-first), so a paste/edit's jump-to-zoom is visible without scrolling.
    A **place-search box** under the map (geocoding via **Nominatim/OpenStreetMap**,
    Google-Maps style) **relocates** the map to a named place — manual submit only (Enter/button, never
    per-keystroke, to respect Nominatim's ≤1 req/s policy); picking a result moves the view but does **not**
    set the decision (the operator still picks under the crosshair).
    - *Built with vendored Leaflet (`web/vendor/leaflet/`, no CDN/build); two **runtime** OpenStreetMap
      dependencies — map **tiles** and the **Nominatim** geocoder — degrade gracefully when offline.*
    - *The earlier idea of drawing the **GPX track / anchors / ghost marker** is not realised here: a GPS
      `review_item` is on the list precisely because no reliable GPS source placed it, so the
      `photos-23` artifact carries no track/anchor/candidate for it. The crosshair pick + photo are the
      manual-placement aid; the fallback pins are the only positional evidence the artifact provides.*
- **Validation** mirrors the reference (IANA tz, offset ±86400, ISO-UTC, lat/lon ranges); invalid input is
  blocked client-side so geotag never rejects the save.

## 5. Build plan (phased)

0. **Skeleton (done):** the server loads the artifacts (fixtures by default) + the SPA shell renders
   both views read-only (tree for time, worklist for GPS, selection → side-panel detail).
1. **Editing (done):** the shared model + `user_decision` overlay; per-cell controls (tz select, offset
   wheel-spinner, accept toggles); override/inherited badges; client-side validation; dirty state.
2. **Map + photo (done):** vendored Leaflet; the side-panel centre-crosshair map picker with reference
   pins + current-decision marker, and embedded-JPEG photo previews served by the server (`/api/photo`,
   path-safe, workspace-only), for GPS cells. (Track/anchors/ghost dropped — not in the GPS artifact for
   review items; see §4.)
3. **Persist + loop (done):** **Save** writes `user_decision` back (round-tripping every other field); a
   **Reset** discards unsaved edits. The loop is **terminal**: after saving, re-run `photos-cartographer geotag
   plan` in a terminal and reload the regenerated artifacts. There is deliberately **no in-app Re-run
   button** — it proved error-prone and added little over the terminal command, so it was removed; every
   gate/stale banner instead tells you to re-run in a terminal and reload. (The server still exposes a
   `/api/rerun` endpoint and an `environment` check on the configured **`gpx_root`** — resolved from
   `photos-00-config.json` and `os.path.isdir`-checked, an empty `gpx_root` meaning "no GPX configured"
   and not gating — so the UI can warn when GPX isn't mounted on the editor's host; but no button drives
   it.) Plus the **advisory live inheritance preview** for the time tree (§4): a timezone
   with no own decision shows, badged `inherited ⟵ <ancestor>`, the value it would inherit from its
   nearest resolved ancestor, updating as you edit ancestors — display-only, authoritative on the next
   Re-run. (Offsets do **not** inherit — they are per-date buckets resolved from a GPX self-anchor or the
   destination timezone, §4.4 — so the live inheritance preview is scoped to timezones and the folder
   fallback, the two facts that actually cascade.)
