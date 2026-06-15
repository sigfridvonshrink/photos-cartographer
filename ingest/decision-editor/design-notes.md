# Decision editor — design notes

> **NON-AUTHORITATIVE.** Design/UX decisions for the decision-editing app, recorded so the build has a
> shared picture. The JSON it edits is described in `decision-json-reference.md`; the authoritative
> behaviour is the calibration code (`../photos-2-time-gps`). These notes are a plan, not a contract.

## 1. What it is

A small single-page app that helps a human resolve the open decisions in a workspace's
`photos-21-time-decisions.json` / `photos-22-gps-decisions.json`. It is **not** a generic JSON editor:
it surfaces a to-do list, shows each decision's proposal + evidence, captures a choice, validates it,
and writes back. Its **only hard requirement is conforming output** (see the reference's "conformance
contract"): it edits **only `user_decision`**, round-trips everything else, and never recomputes
`proposal`/`effective_*`/`status` — calibration does that on the next run. Any in-app outcome it shows
is **advisory**; the loop is **edit → Save → re-run `photos-2-time-gps run` → reload**.

## 2. Stack (decided)

- **Local Python server**, stdlib only — an extensionless executable run directly like the pipeline
  scripts (`ingest/decision-editor/decision-editor <workspace>`, not via `python3`): serves the SPA,
  reads/writes the workspace's `.photos-ingest/` decision JSON, serves **photo previews** (embedded JPEG
  via exiftool/ImageMagick — already repo deps), and offers a **Re-run calibration** action. Default with
  no workspace = demo mode loading the `examples/` fixtures, so it runs with nothing installed.
  - Ships in two forms: the readable source **`decision-editor.unbundled`** (reads `web/` + `examples/`
    from disk) and the **`decision-editor`** single file, which **`./bundle`** regenerates with those
    assets embedded inline so it runs anywhere from one copied file. `./bundle --check` fails if the
    committed bundle is stale or hand-edited (CI/pre-push guard). Re-run and previews still need the
    surrounding pipeline / exiftool / ImageMagick, and degrade gracefully when absent.
- **No-build SPA**: plain ES modules; a tiny reactive helper (**Preact + htm**) and **Leaflet** for the
  map, both **vendored** under `web/vendor/` (no CDN at runtime, no build step, works offline). The
  skeleton is dependency-free vanilla; the lib/map come in with the editing/map phases.
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

**Master–detail shell:** header (workspace • view toggle • to-do/stale count • Save • Re-run) → a compact
**list** (left) + a persistent **side-panel** editor (right). Selecting a cell anywhere opens it in the
panel.

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
  only (re)generates `photos-22` once **every** time decision is resolved. The editor surfaces that gate:
  while the time artifact `requires_user_input`, the GPS view is **locked** behind an explanatory banner
  (finish time, then Re-run) instead of showing an empty or stale list; and once any time decision is
  changed, a **stale** banner on both views reminds you a Re-run is needed before GPS reflects it (tracked
  by `timeChangedSinceRerun`, cleared on Re-run). Both notices are skipped in demo mode (its curated
  fixtures intentionally pair an incomplete time artifact with a GPS one).
- **Side-panel editor** for the selected cell: the proposal + evidence, the decision control, a **photo
  thumbnail** (review items), a **context map**, and a live **effective-outcome** preview with
  client-side validation. For an **offset** proposal the raw anchor list is **collapsed**: the consensus
  correction, then up to three "N photos → ±Xh Ym" groups — each naming one photo by its full by-dest
  path and showing that photo's camera time → **corrected local time** (via the destination timezone,
  with the usual "set the timezone" nudge when unresolved) — plus a note counting frames skipped (no
  nearby track / a track only from another trip). The data comes from the proposal's `groups`/`skipped`
  (calibration); the editor only renders it. The camera and corrected sides are formatted **identically**
  (`DD Mon YYYY` + `HH:MM:SS`); when the date is unchanged it's shown once and the arrow carries only the
  time correction (`22 Mar 2026 · 13:25:21 → 13:24:18 (Europe/Brussels)`).
- **Status is edit-aware.** The status chip normally reflects the last calibration run (`needs input` /
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
    returns the cell to unset (calibration auto-resolves / inherits). The picker writes the derived
    offset, so `manual_real_utc` isn't persisted by the editor (a hand-edited one is still honored).
  - **GPS coordinate / fallback:** a **zoomable map with a fixed centre crosshair** — pan/zoom under it,
    "use map center" → take `map.getCenter()` into the lat/lon fields. Reference pins (effective /
    inherited / folder fallback) and a marker for the current decision give context, and the map seeds
    its view to the current coordinate or the nearest known reference. The **photo** (embedded-JPEG
    preview from the server) sits above the map for review items.
    - *Built with vendored Leaflet (`web/vendor/leaflet/`, no CDN/build); map tiles load from
      OpenStreetMap **at runtime** — the one external dependency, as any web map needs a tile source.*
    - *The earlier idea of drawing the **GPX track / anchors / ghost marker** is not realised here: a GPS
      `review_item` is on the list precisely because no reliable GPS source placed it, so the
      `photos-22` artifact carries no track/anchor/candidate for it. The crosshair pick + photo are the
      manual-placement aid; the fallback pins are the only positional evidence the artifact provides.*
- **Validation** mirrors the reference (IANA tz, offset ±86400, ISO-UTC, lat/lon ranges); invalid input is
  blocked client-side so calibration never rejects the save.

## 5. Build plan (phased)

0. **Skeleton (this step):** the server loads the artifacts (fixtures by default) + the SPA shell renders
   both views **read-only** (tree for time, worklist for GPS, selection → side-panel detail). No editing.
1. **Editing:** the shared model + `user_decision` overlay; per-cell controls (tz select, offset
   wheel-spinner, accept toggles); override/inherited badges; client-side validation; dirty state.
2. **Map + photo (done):** vendored Leaflet; the side-panel centre-crosshair map picker with reference
   pins + current-decision marker, and embedded-JPEG photo previews served by the server (`/api/photo`,
   path-safe, workspace-only), for GPS cells. (Track/anchors/ghost dropped — not in the GPS artifact for
   review items; see §4.)
3. **Persist + loop (done):** **Save** (write `user_decision` back, round-tripping the rest) plus
   **Re-run** — `POST /api/rerun` invokes `photos-2-time-gps run` (workspace as CWD; calibration owns its
   own `WorkspaceLock`, separate from the editor lock) and, on success, reloads the regenerated
   authoritative artifacts. Re-run acts on the *saved* decisions, so it's disabled while there are
   unsaved/invalid edits (save first); its outcome — exit code + stderr/stdout tail — shows in a
   dismissible banner. **Re-run is also gated on calibration's dependencies being present on the host
   running the editor** — two of them: the **pipeline script** (`CALIBRATE`, expected beside the editor;
   the single-file bundle does not embed it, so a copy taken away from the repo can't re-run), and the
   configured **`gpx_root`** (a mount that may live only on the workspace's own host — re-running without
   it would regenerate the time/GPS decisions as if there were no GPX, silently discarding good offsets
   and placements). So `/api/artifacts` returns an `environment` block (`_environment`: `os.path.isfile`
   on `CALIBRATE`; `gpx_root` resolved from `photos-00-config.json` the way `selected_gpx_root` does and
   `os.path.isdir`-checked — an empty `gpx_root` means "no GPX configured" and does not gate). When any
   dependency is missing the Re-run button is **disabled with a tooltip** naming it (from `missing[]`),
   and `_rerun` refuses server-side too (defence in depth) — editing and Save stay available so decisions
   can be prepared anywhere and calibrated on the right host. No other dependencies exist today. Plus the **advisory live inheritance preview** for the time tree (§4): a timezone
   with no own decision shows, badged `inherited ⟵ <ancestor>`, the value it would inherit from its
   nearest resolved ancestor, updating as you edit ancestors — display-only, authoritative on the next
   Re-run. (Offsets also inherit, but their resolution is GPX/auto-driven rather than a manual-override
   cascade, so the live preview is scoped to timezones — the clearest override-and-inherit case.)
