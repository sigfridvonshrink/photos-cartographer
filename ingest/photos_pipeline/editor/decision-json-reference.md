# Decision-JSON reference (for the decision editor)

> **NON-AUTHORITATIVE.** This describes the shape of the two geotag *decision* artifacts so the
> editor can be built against a stable picture. The **authoritative** source is the code that writes
> and validates them — `ingest/photos_pipeline/photos_2_geotag.py` (`build_time_decisions`, `build_gps_decisions`,
> `_timezone_decision`, `_offset_cell`, `_folder_fallback_cell`, `_review_item`, and the `_valid_*`
> validators) — with the geotag spec `ingest/workflows/photos-2-geotag-workflow.md` as the
> behavioural reference. If this doc and the code ever disagree, the code wins; update this doc.

The editor is narrowly scoped: it helps a human fill in the **decisions** these files request, and its
only hard requirement is that its output **conforms** (so geotag accepts it). It does **not** need
to understand the wider pipeline.

> **Worked examples:** real, code-generated fixtures of both files in both states (`requires_user_input`
> and `complete`) live in [`examples/`](examples/) — develop and test against those alongside this doc.

---

## 1. The files

All live in the workspace control directory `.photos-ingest/`:

| File | `artifact_type` | What the human decides |
|------|-----------------|------------------------|
| `photos-21-time-decisions.json` | `time_decisions` | Per-destination **civil timezone**, and per-(camera-group, destination) **clock offset** for fixed-clock cameras. |
| `photos-22-gps-drift-validation.json` | `gps_drift_validation` | Per at-risk bucket, **confirm or correct** a manual/timezone-derived clock offset against the GPX track before it is used to place photos (§5a below). |
| `photos-23-gps-decisions.json`  | `gps_decisions`  | Per-destination **GPS fallback** coordinate, and per-file **GPS** decisions for files an automatic source could not place. |

The editor opens one of these, presents the open decisions, lets the human resolve them, and writes the
file back. (`photos-22` is produced by the pipeline today and resolvable by hand-editing its
`user_decision` fields, or via the editor's dedicated scrub-on-track view — see §5a.)

---

## 2. The conformance contract (read this first)

Everything the editor must guarantee, in five rules:

1. **Only `user_decision` blocks are yours to write.** Every other field — `proposal*`, `effective_*`,
   `requires_user_input`, `stale_user_decision`, `status`, `summary`, `automatic_decision_summary`,
   `depends_on`, `artifact_type`/`artifact_name`, `decision_mode`, the per-file `reason`, etc. — is
   **system-owned**. Geotag **regenerates the whole artifact from scratch** on its next run and
   reads back **only the `user_decision` values** from the file you saved, matched by their location
   (destination path → camera-group key / file `relative_path`). So:
   - You may **round-trip the whole file** (load, change `user_decision` in place, save). The
     system-owned fields you carry along are ignored and overwritten next run — they exist only so the
     UI can *show* the proposal/result.
   - You do **not** need to (and must not rely on having) recomputed `effective_*`, `status`,
     `requires_user_input`, or the summaries. They go stale the instant you edit; geotag recomputes
     them. (If you want a live preview, compute it for display only.)
2. **Preserve structure and unknown keys verbatim.** Keep the JSON shape (the `destinations` map keyed by
   destination path, the cells, the `review_items` list) and pass through any field you don't recognise,
   so a future geotag field isn't dropped by a round-trip.
3. **Write only valid values** (Section 7). Geotag **sanity-validates** every authored value; a bad
   value makes geotag **reject the artifact as a blocker and leave it untouched** (it will not
   partially apply). Validate client-side so the human never has to round-trip through a rejection.
4. **`""` (empty string) means "no decision".** That is how every `user_decision` text/number field is
   left unset. Clearing a field = setting it back to `""`. Booleans default to `false`.
5. **Don't invent keys in `destinations`.** The set of destinations, camera groups, and review items is
   determined by the current photo set; the human resolves what's there, they don't add entries.

---

## 3. The decision-cell pattern (the spine of both files)

Almost every editable thing is a **cell** with the same four parts. Learn this once and both files read
the same way:

```jsonc
{
  "proposal":           { ... },        // SYSTEM: what geotag suggests + the evidence for it
  "user_decision":      { ... },        // EDITABLE: the only thing the editor writes
  "effective_…":        ... ,           // SYSTEM: the resolved outcome ("" / null = unresolved)
  "requires_user_input": false,         // SYSTEM: true => this cell still needs a human decision
  "stale_user_decision": false          // SYSTEM: true => you accepted a proposal that no longer exists
                                         //                 (re-decide: the inputs changed)
}
```

- **`proposal`** — show this to the human: it's the system's suggestion and its supporting evidence
  (GPX anchors, confidence, inherited-from, …). Read-only.
- **`user_decision`** — the human's choice. Typically "accept the proposal" (a boolean) *or* enter a
  manual value. **Within a cell, a manual value takes precedence over `accept_*`** (Section 6).
- **`effective_…`** — the resolved result after applying the decision. `""` or `null` = not yet
  resolved. Read-only (recomputed by geotag).
- **`requires_user_input`** — the actionable flag: `true` means this cell is blocking geotag until
  the human decides. The editor's "to-do list" is every cell with `requires_user_input: true`.
- **`stale_user_decision`** — `true` means a previously-accepted proposal disappeared (e.g. the GPX
  evidence changed); the accept is now inert and the human should re-decide.

Top-level **`status`** is `"complete"` when nothing requires input, else `"requires_user_input"`;
**`requires_user_input`** (top level) is the OR of all cells. The editor can use these to show overall
progress and to know when the file is "done". (Both are system-owned; don't set them.)

---

## 4. `photos-21-time-decisions.json` (time)

### 4.1 Top level

```jsonc
{
  "artifact_type": "time_decisions",
  "artifact_name": "photos-21-time-decisions.json",
  "status": "requires_user_input",        // or "complete"
  "requires_user_input": true,            // OR of all cells
  "executable": false,
  "destinations": {                        // keyed by destination path, e.g. "Belgium/Brussels"
    "<destination_path>": { /* §4.2 */ }
  },
  "depends_on": { /* system fingerprints */ },
  "decision_mode": "no_op_or_auto_resolved" // present ONLY when nothing requires input
}
```

### 4.2 A destination

```jsonc
{
  "destination_path": "Belgium/Brussels",
  "destination_timezone": { /* §4.3 tz cell */ },
  "camera_groups_present": ["<camera_group_key>", ...],   // SYSTEM: groups seen in this destination
  "camera_group_time_decisions": {                        // one offset cell per FIXED-CLOCK camera group,
    "<camera_group_key>": { /* §4.4 offset cell */ },     //   SPLIT per naive date when the group spans >1
    "<camera_group_key>@<YYYY-MM-DD>": { /* §4.4 */ }      //   day here (see §4.4 "per-date buckets")
  },
  "file_less": true                                       // SYSTEM, optional: a CONTAINER destination (see below)
}
```

Note: smartphones are resolved per-file and get **no** offset cell — `camera_group_time_decisions` only
holds `camera`-class groups.

**Container destinations.** A folder that holds only sub-destinations (no media of its own) is still
emitted as a destination, flagged `"file_less": true`, so you can author timezone / fallback decisions on
it that propagate **downward** to its children. A container carries timezone and fallback cells (which
inherit), but **no offset cells at all** — `camera_group_time_decisions` is empty, because clock offsets
neither cascade down nor roll up and a file-less folder has no media to time-correct. Having no media to
act on, **none of a container's cells ever block**: each `requires_user_input` is `false` and an unset
timezone cell **auto-resolves by inheritance** (`decision_mode: "auto_resolved"`) while staying editable.
The editor badges these destinations as `container` and keeps them off the to-do list.

### 4.3 `destination_timezone` cell

| Field | Type | Editable | Meaning |
|-------|------|----------|---------|
| `proposed_iana_timezone` | string \| null | no | Suggested zone, or null if none. |
| `proposal_source` | `"inherited"` \| `"config_default"` \| `"none"` | no | Where the proposal came from. |
| `proposal_confidence` | `"review_required"` \| `"high"` \| `"none"` | no | `inherited` is always `review_required`. |
| `inherited_from` | string | no | Present only when `proposal_source == "inherited"`: the ancestor destination. |
| **`user_decision.manual_iana_timezone`** | string (`""`) | **yes** | A human-entered IANA zone (e.g. `"Asia/Tokyo"`). |
| **`user_decision.accept_proposed_timezone`** | bool | **yes** | Accept `proposed_iana_timezone`. |
| `effective_iana_timezone` | string (`""` if unresolved) | no | The resolved zone. |
| `requires_user_input` | bool | no | `true` ⇔ `effective_iana_timezone == ""` **and** no proposal exists (no ancestor zone and no configured `default_folder_timezone`). **Any** destination — `file_less` container *or* real — that has a proposal auto-adopts it and is `false`; only a destination with no proposal at all blocks for review. |
| `decision_mode` | `"auto_resolved"` | no | Present on **any** destination (container *or* real) that auto-adopted its inherited or config-default zone. |
| `stale_user_decision` | bool | no | Accepted a proposal that no longer exists. |

Resolution: `manual_iana_timezone` (if valid) wins; else `accept_proposed_timezone` applies the proposal.

### 4.4 `camera_group_time_decisions[<key>]` offset cell

**Per-date buckets.** The cell key is normally the bare `<camera_group_key>`, but when a (camera group,
destination) spans **more than one naive calendar date** the cell SPLITS into per-day buckets keyed
`<camera_group_key>@<YYYY-MM-DD>` (the camera is set to local time each morning, so its offset is constant
only within a day). Each bucket carries a `date` field and proposes/resolves independently; a manual
decision on one day's bucket does not touch the others. The single-day common case keeps the bare key with
no `date`. Resolved-UTC picks each file's own naive-date bucket. Offsets do **not** inherit between
destinations or buckets.

| Field | Type | Editable | Meaning |
|-------|------|----------|---------|
| `camera_group` | string | no | The camera-group key (the bare group, even for a dated bucket). |
| `camera_group_class` | `"camera"` | no | Always `camera` here. |
| `date` | string | no | Present only on a per-date bucket: the naive calendar date (`"YYYY-MM-DD"`) this bucket covers. |
| `proposal` | object | no | One of three shapes — see below. |
| **`user_decision.accept_proposal`** | bool | **yes** | Accept the proposal's offset. |
| **`user_decision.manual_offset_seconds`** | number \| `""` | **yes** | A manual clock offset, seconds (camera_time + offset = real UTC). |
| **`user_decision.manual_real_utc`** | string (`""`) | **yes** | The true UTC of the recommended anchor frame, ISO-8601 (`"2024-07-03T14:12:21Z"`). **Only meaningful when `proposal.proposal_source == "gpx_self_anchor"`** (geotag derives the offset from the recommended anchor's camera time). |
| `effective_time_anchor` | `""` \| object | no | `""` if unresolved; else `{ "offset_seconds": int, "source": … }` where source ∈ `manual` \| `manual_real_utc` \| `gpx_anchor_accepted` \| `timezone_accepted` \| `gpx_anchor_auto`. |
| `requires_user_input` | bool | no | `true` ⇔ `effective_time_anchor == ""`. (Containers carry no offset cells, so this is never softened here.) |
| `stale_user_decision` | bool | no | Accepted a proposal with no offset. |
| `decision_mode` | `"auto_resolved"` | no | Present when a GPX self-anchor auto-resolved under the policy flags. (Timezone-derived and manual offsets are never auto-resolved.) |

**`proposal` shapes** (all read-only; this is the evidence the UI shows):

- **GPX self-anchor** (`proposal_source: "gpx_self_anchor"`) — geotag matched the group's geotagged
  frames against GPX tracks:
  ```jsonc
  {
    "proposal_source": "gpx_self_anchor",
    "proposed_offset_seconds": -3600,
    "proposed_real_utc": "2024-07-03T14:12:21Z",
    "confidence": "high",                 // "high" | "medium" | "review_required"
    "rank": "recommended",
    "recommended_gpx_match": { "match_type": "gpx_point_match", "gpx_file": "…", "distance_m": 4.2,
                               "segment_duration_seconds": 0 },
    "anchor_count": 3, "supporting_count": 2, "conflicting_count": 0,
    "anchors": [ { "proposal_id": "anchor-001", "source_file": "…", "camera_source_naive_time": "…",
                   "native_gps": { … }, "gpx_match": { … }, "proposed_offset_seconds": -3600 }, … ],
    // collapsed view: the offset clusters, largest first (the recommended offset = the largest cluster)
    "groups": [ { "offset_seconds": -3600, "count": 2,
                  "representative": { "source_file": "6-photos-by-dest/Japan/Kyoto/IMG_1234.arw",  // FULL by-dest path
                                      "camera_source_naive_time": "2024:07:03 15:12:08",
                                      "real_utc": "2024-07-03T14:12:21Z",       // → corrected local time via the tz
                                      "match_type": "gpx_point_match", "distance_m": 4.2 } }, … ],
    // frames that produced no in-window anchor, by reason (a track only from another trip vs none nearby)
    "skipped": { "no_nearby_track": 0, "outside_time_window": 1,
                 "examples": [ { "source_file": "…", "reason": "outside_time_window" } ] }
  }
  ```
  The recommended `proposed_offset_seconds` is the **largest agreeing cluster** (consensus), not merely the
  closest single match; `anchors[0]` is that cluster's representative. The editor renders `groups` (top ~3)
  and `skipped` instead of dumping every anchor — see the offset proposal panel.
- **Timezone-derived** (`proposal_source: "timezone_naive"`) — no GPX anchor, but the destination's
  timezone is resolved, so the offset is derived from the bucket's local time assuming the camera clock
  tracked it (DST-aware, per day):
  `{ "proposal_source": "timezone_naive", "proposed_offset_seconds": int, "proposed_real_utc": "…Z",
     "proposed_from_timezone": "Europe/Brussels", "confidence": "review_required", "rank": "timezone_derived" }`.
  Confirmable only — the assumption can be wrong (camera on home time). This is the no-anchor default;
  offsets are never inherited from an ancestor destination.
- **Manual required** (`proposal_source: "manual_required"`) — no signal (and no resolved timezone); the
  human must enter a manual offset (or real UTC): `{ "proposal_source": "manual_required" }`.

---

## 5. `photos-23-gps-decisions.json` (GPS)

### 5.1 Top level

Same wrapper as §4.1 with `artifact_type: "gps_decisions"` / `artifact_name:
"photos-23-gps-decisions.json"`. `destinations` is keyed by destination path; each destination is §5.2.

### 5.2 A destination

```jsonc
{
  "destination_path": "Belgium/Brussels",
  "folder_fallback": { /* §5.3 fallback cell */ },
  "gps_decisions": {
    "summary": { /* §5.5 counts — SYSTEM */ },
    "automatic_decision_summary": {        // SYSTEM, informational
      "gpx_files_used": ["…"], "max_interpolation_gap_seconds": 120,
      "max_distance_to_track_m": 50, "confidence": "automatic", "notes": ["…"]   // confidence: "automatic", or "mixed" if the destination has blocked files
    },
    "review_items": [ /* §5.4 — the per-file editable list */ ]
  }
}
```

**Editable surface in this file = `folder_fallback` (per destination) + `review_items` (per file).**
Automatically-placed files (preserve-native, GPX interpolation/extrapolation, fallback) are **only
counted** in `summary`, never listed per file — they are not editable here (they're automatic; the
exact per-file writes live in `photos-24-executable-plan.json`, which the editor does not touch).

### 5.3 `folder_fallback` cell

A destination-level default coordinate, applied to files with no better source. **Optional — never
blocks** (`requires_user_input` is always `false`).

| Field | Type | Editable | Meaning |
|-------|------|----------|---------|
| `proposal` | object | no | `{ "proposal_source": "inherited", "proposed_fallback": {lat,lon}, "inherited_from": "<ancestor>" }` or `{ "proposal_source": "manual_required" }`. |
| **`user_decision.fallback_lat`** | number \| `""` | **yes** | Fallback latitude (set both lat and lon). |
| **`user_decision.fallback_lon`** | number \| `""` | **yes** | Fallback longitude. |
| **`user_decision.accept_proposal`** | bool | **yes** | Accept an inherited fallback. |
| `effective_fallback` | null \| `{lat,lon}` | no | The resolved fallback. |
| `requires_user_input` | bool (always `false`) | no | The fallback is optional. |
| `stale_user_decision` | bool | no | Accepted a fallback that no longer exists. |

### 5.4 `review_items[]` — the per-file decisions

One entry per file that needs the human (or that the human already locked/accepted):

| Field | Type | Editable | Meaning |
|-------|------|----------|---------|
| `relative_path` | string | no | Workspace-relative path of the photo. |
| `reason` | `"no_reliable_gps_source"` \| `"manual_locked"` \| `"accepted_unlocated"` | no | Why it's here (see below). |
| **`user_decision.manual_lat`** | number \| `""` | **yes** | Human-entered latitude (set both). |
| **`user_decision.manual_lon`** | number \| `""` | **yes** | Human-entered longitude. |
| **`user_decision.accept_unlocated`** | bool | **yes** | Accept leaving this file with no GPS. |
| `requires_user_input` | bool | no | `true` only for `no_reliable_gps_source` (until resolved). |
| `stale_user_decision` | bool (always `false`) | no | — |

`reason` values:
- **`no_reliable_gps_source`** — *blocked*; `requires_user_input: true`. The human resolves it by setting
  `manual_lat`+`manual_lon` **or** `accept_unlocated: true`. On the next run it reclassifies (below).
- **`manual_locked`** — informational: a valid manual coordinate is already set. Editable (change/clear it).
- **`accepted_unlocated`** — informational: `accept_unlocated` is set, so the file stays without GPS.
  Editable.

(So resolving a `no_reliable_gps_source` item → after re-run it becomes `manual_locked` or
`accepted_unlocated` with `requires_user_input: false`. The editor's per-file to-do list is the
`no_reliable_gps_source` items.)

### 5.5 `summary` (read-only counts)

`files_total`, `preserve_native_gps`, `automatic_gpx_interpolation`, `automatic_gpx_extrapolation`,
`automatic_folder_fallback`, `manual_locked`, `manual_review_required`, `blocked`,
`no_gps_change_needed`. Useful for a per-destination progress display; the editor never writes these.

---

## 5a. `photos-22-gps-drift-validation.json` (GPS-drift validation)

A gate the pipeline writes **between** photos-21 and photos-23 (geotag workflow §22a). It flags
every `(camera group, destination[, date])` offset bucket whose clock offset is **manual or
timezone-derived** and that has **no native-GPS anchor** but **does** have GPX coverage — exactly the
case where a wrong offset would silently mis-place the whole bucket along the track. Each flagged
bucket must be **explicitly confirmed** (or corrected) before photos-23 is generated.

### 5a.1 Top level

Same decision wrapper as §4.1 with `artifact_type: "gps_drift_validation"` / `artifact_name:
"photos-22-gps-drift-validation.json"` — except its top-level `decision_mode`, when present (nothing
requires input), is `"no_op_or_confirmed"` (not `"no_op_or_auto_resolved"`). `destinations` maps a destination path to
`{ "destination_path", "drift_decisions": { <bucket_key>: cell } }`. The `<bucket_key>` matches the
photos-21 offset cell it refines — bare `<camera_group_key>` or `<camera_group_key>@<YYYY-MM-DD>`.

### 5a.2 A `drift_decisions[<bucket>]` cell

```json
{
  "camera_group": "SONY|ILCE-6400|A",
  "date": "2024-07-03",
  "proposal": {
    "proposal_source": "timezone_accepted",
    "current_offset_seconds": -7200,
    "frames": [ { "source_file": "6-photos-by-dest/Belgium/Brussels/a.arw", "camera_naive": "2024:07:03 14:00:00" }, ... ],
    "track_segment": [ { "lat": 50.0, "lon": 4.0, "time_utc": "2024-07-03T12:00:00Z" }, ... ]
  },
  "user_decision": { "confirmed": false, "corrected_offset_seconds": "" },
  "effective_drift_offset": "",
  "requires_user_input": true,
  "stale_user_decision": false
}
```

- `proposal.track_segment` is read-only evidence — the GPX points covering the bucket's time window
  (±2 days, wide enough that any valid corrected offset lands on a point already in the segment, so a
  scrub never needs a re-run to fetch more track). `current_offset_seconds` is the offset photos-21
  resolved.
- `proposal.frames` is read-only — every photo in the bucket as `{source_file, camera_naive}`,
  earliest first. The editor scrubs one (default the earliest) along the track and **computes** the
  decision: `corrected_offset_seconds = (chosen track point's time_utc) − (that frame's camera_naive)`.
  Both `track_segment` and `frames` are re-extracted by the script on every re-run, so a changed
  photos-21 time decision shifts them automatically.
- `user_decision.confirmed` (bool) — the **only** thing that satisfies the gate. `false` (the default)
  blocks. **A "zero scrub" / "the offset was right" must be set explicitly** (`confirmed: true` with an
  empty `corrected_offset_seconds`) — inaction never counts.
- `user_decision.corrected_offset_seconds` — empty for a zero scrub, or a number (seconds, ±86400) to
  correct the whole bucket's offset.
- `effective_drift_offset` — `""` until confirmed, then `{ "offset_seconds": N, "source":
  "gps_drift_validated" }`. Geotag recomputes resolved UTC consuming this; the value does **not**
  mutate the photos-21 decision it refines.

### 5a.3 `date`

Present only when the bucket is per-date (the group spans >1 naive day in this destination, §10.2);
omitted for a single-date bucket.

---

## 6. Within-cell precedence (which `user_decision` field wins)

A cell can carry more than one decision field; geotag applies them in a fixed order. The editor's
UI should make the *effective* choice obvious and ideally offer them as mutually-exclusive.

- **Timezone:** `manual_iana_timezone` (if valid) → else `accept_proposed_timezone`.
- **Clock offset:** `manual_offset_seconds` (if set & valid) → `manual_real_utc` (GPX proposals only) →
  `accept_proposal` → automatic GPX resolution (no human input). Setting a manual field overrides
  `accept_proposal`.
- **Folder fallback:** `fallback_lat`+`fallback_lon` (if both set & valid) → `accept_proposal`.
- **Per-file GPS:** `manual_lat`+`manual_lon` (if both set & valid) → `accept_unlocated`. (If neither and
  no automatic source exists, the file stays blocked = `no_reliable_gps_source`.)

A bare `""`/`false` everywhere = "no decision yet".

---

## 7. Validation rules for editable values

Mirror these client-side; a value that fails makes geotag reject the whole artifact as a blocker.
(Source: the `_valid_*` helpers in `ingest/photos_pipeline/photos_2_geotag.py`.)

| Field(s) | Rule |
|----------|------|
| `manual_iana_timezone` | Must resolve as a real IANA zone (e.g. `zoneinfo`/`Intl` knows it). `""` allowed (= unset). |
| `manual_offset_seconds` | A finite number with `abs(v) <= 86400` (±1 day). Not a boolean. `""` allowed. |
| `manual_real_utc` | ISO-8601 datetime, trailing `Z` accepted (`"2024-07-03T14:12:21Z"`). Only takes effect on GPX-self-anchor proposals. `""` allowed. |
| `fallback_lat` / `fallback_lon`, `manual_lat` / `manual_lon` | Numbers; latitude ∈ [-90, 90], longitude ∈ [-180, 180]. Set both or neither. `""` allowed (= unset). |
| `accept_*` / `accept_unlocated` | Booleans; default `false`. |

---

## 8. Suggested editor model (non-binding)

A natural shape that satisfies the contract:

1. Load the JSON; index the cells by location (destination path → camera-group key / `relative_path`).
2. Build the to-do list from `requires_user_input: true` (plus surface `stale_user_decision: true` as
   "re-decide"). Show `proposal` + evidence for each.
3. Let the human edit only `user_decision`; validate per §7 live; show a computed preview of the outcome
   if desired (display-only — not written authoritatively).
4. Save by writing the modified `user_decision` blocks back into the loaded JSON (round-trip, preserving
   all other fields and unknown keys) and serialising. The human then re-runs `photos-cartographer geotag`, which
   regenerates the artifact, reads back the `user_decision` values, recomputes everything, and validates.
