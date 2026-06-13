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
  scripts (`ingest/decision-editor/serve <workspace>`, not via `python3`): serves the SPA, reads/writes the
  workspace's `.photos-ingest/` decision JSON, serves **photo previews** (embedded JPEG via
  exiftool/ImageMagick — already repo deps), and offers a **Re-run calibration** action. Default with no
  workspace = demo mode loading the `examples/` fixtures, so it runs with nothing installed.
- **No-build SPA**: plain ES modules; a tiny reactive helper (**Preact + htm**) and **Leaflet** for the
  map, both **vendored** under `web/vendor/` (no CDN at runtime, no build step, works offline). The
  skeleton is dependency-free vanilla; the lib/map come in with the editing/map phases.
- Rationale: matches the repo's Python/CLI, no-build, system-deps-only ethos; zero new package managers.

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
  counts row. Either view is switchable to the other.
- **Side-panel editor** for the selected cell: the proposal + evidence (for offsets, the GPX anchors +
  confidence), the decision control, a **photo thumbnail** (review items), a **context map**, and a live
  **effective-outcome** preview with client-side validation.
- **Specialized controls:**
  - **Timezone:** searchable IANA select; or accept the proposal.
  - **Clock offset:** a **mouse-wheel spinner** (`+1h 00m 00s` / raw seconds) whose **step accelerates
    with scroll velocity** (gentle nudge ±1 s → fast flick minutes→hours); arrow keys (±1 s, Shift ±60 s)
    and type-to-set fallbacks; "accept" pre-fills it. Wheel-edit only when hovered/focused, with
    `preventDefault` so it never hijacks page scroll. **Real-UTC** entry is the equivalent alternate input.
  - **GPS coordinate / fallback:** a **zoomable map with a fixed centre crosshair** — pan/zoom under it,
    validate → take `map.getCenter()`. The map also shows the **GPX track**, nearby **anchors**, and a
    ghost marker of where the track *would* place the photo. The **photo** (embedded-JPEG preview from the
    server) sits beside the map for context.
- **Validation** mirrors the reference (IANA tz, offset ±86400, ISO-UTC, lat/lon ranges); invalid input is
  blocked client-side so calibration never rejects the save.

## 5. Build plan (phased)

0. **Skeleton (this step):** `serve` loads the artifacts (fixtures by default) + the SPA shell renders
   both views **read-only** (tree for time, worklist for GPS, selection → side-panel detail). No editing.
1. **Editing:** the shared model + `user_decision` overlay; per-cell controls (tz select, offset
   wheel-spinner, accept toggles); override/inherited badges; client-side validation; dirty state.
2. **Map + photo:** vendor Leaflet; the side-panel context map (centre-crosshair pick, track/anchors/ghost)
   and embedded-JPEG photo previews served by `serve`, for GPS cells.
3. **Persist + loop:** **Save** (write `user_decision` back, round-tripping the rest) and **Re-run
   calibration** (invoke `photos-2-time-gps run`, reload the authoritative artifacts); the advisory live
   inheritance preview for the time tree.
