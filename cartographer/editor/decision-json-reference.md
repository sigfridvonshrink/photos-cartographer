# Decision-JSON reference (for the decision editor)

> **NON-AUTHORITATIVE.** This describes the shape of the three geotag *decision* artifacts so the
> editor can be built against a stable picture. The **authoritative** source is the code that writes
> and validates them — `cartographer/photos_2_geotag.py` (`build_time_decisions`, `_timezone_decision`,
> `_offset_cell`, `_share_offsets_within_a_day`, `build_drift_validation`, `_drift_cell`,
> `build_gps_decisions`, `_folder_fallback_cell`, `_review_item`, `_validate_review_decision`,
> `_decision_shape_blockers`, `_decision_flag`), `cartographer/_geotag_calc.py` (`infer_anchor_proposal`,
> `_timezone_naive_offset`, `_zone_ambiguity`, `place_gps`, `classify_gps`, and the `_valid_*` validators)
> and, for saving, `cartographer/editor/server.py` (`_save`, `_apply_edits`) — with the geotag spec
> (`spec/intent/geotag.md`, `spec/build/geotag.md`) as the behavioural reference. If this doc and the
> code ever disagree, the code wins; update this doc.

The editor is narrowly scoped: it helps a human fill in the **decisions** these files request, and its
only hard requirement is that its output **conforms** (so geotag accepts it). It does **not** need
to understand the wider pipeline.

> **Worked examples:** real, code-generated fixtures of all three files in both states (`requires_user_input`
> and `complete`), plus a few photos-21 variants, live in [`examples/`](examples/) (written by
> `generate_examples.py` from the real code) — develop and test against those alongside this doc.

---

## 1. The files

All live in the workspace control directory `.photos-ingest/`:

| File | `artifact_type` | What the human decides |
|------|-----------------|------------------------|
| `photos-21-time-decisions.json` | `time_decisions` | Per-destination **country** and **civil timezone**, and per-(camera group, destination, day) **clock offset** for fixed-clock cameras. |
| `photos-22-gps-drift-validation.json` | `gps_drift_validation` | Per at-risk bucket, **confirm or correct** a clock offset that no photo's own GPS pins (a manual, timezone-derived or imprecise-anchor offset) against the GPX track before it is used to place photos (§5a below). |
| `photos-23-gps-decisions.json`  | `gps_decisions`  | Per-destination **GPS fallback** coordinate, and per-file **GPS** decisions for files an automatic source could not place. |

The editor opens one of these, presents the open decisions, lets the human resolve them, and writes the
file back. (`photos-22` is produced by the pipeline today and resolvable by hand-editing its
`user_decision` fields, or via the editor's dedicated scrub-on-track view — see §5a.)

---

## 2. The conformance contract (read this first)

Everything the editor must guarantee, in five rules:

1. **Only `user_decision` blocks are yours to write.** Every other field — `proposal*`, `effective_*`,
   `requires_user_input`, `stale_user_decision`, `status`, `summary`, `automatic_decision_summary`,
   `depends_on`, `countries`, `artifact_type`/`artifact_name`, `decision_mode`, `contradicted_by`,
   `country`/`country_from`/`country_zones`/`country_removed`, `conflicts_with`, `anchored_by`,
   `date`/`day`, the per-file `reason` and `tracks`, `track_disagreements`, etc. — is
   **system-owned**. Geotag **regenerates the whole artifact from scratch** on its next run and
   reads back **only the `user_decision` values** from the file you saved, each found again by what
   it decides about: a timezone or fallback cell by its destination path; an offset cell (and the
   photos-22 drift cell refining it) by its destination and its `day` — under its bucket key, else
   under the key's other form naming the same `day`, since a camera's only day in a destination is
   keyed `<group>` and becomes `<group>@<day>` once a second day arrives (§4.4); a review item by the
   photo's `content_fingerprint` (which follows the photo through geotag's own renames), and by
   `relative_path` only for an item recorded without one. A decision whose target is gone (no such
   destination, day or photo, or a photo that no longer needs one) is not carried over. So:
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
   The structure must hold too: every container on the way to a `user_decision` (`destinations`, each
   destination, its cells, each `user_decision`) must be an object, `review_items` a list of objects each
   with its `relative_path` — a broken one is a located blocker.
4. **`""` (empty string) means "no decision".** That is how every `user_decision` text/number field is
   left unset. Clearing a field = setting it back to `""`. Booleans default to `false`; the one list,
   `confirmed_despite_recorded_offsets`, defaults to `[]`.
5. **Don't invent keys in `destinations`.** The set of destinations, camera groups, and review items is
   determined by the current photo set; the human resolves what's there, they don't add entries.

---

## 3. The decision-cell pattern (the spine of all three files)

Almost every editable thing is a **cell** with the same parts. Learn this once and all three files read
the same way:

```jsonc
{
  "proposal":           { ... },        // SYSTEM: what geotag suggests + the evidence for it
  "user_decision":      { ... },        // EDITABLE: the only thing the editor writes
  "effective_…":        ... ,           // SYSTEM: the resolved outcome ("" / null = unresolved)
  "requires_user_input": false,         // SYSTEM: true => this cell still needs a human decision
  "stale_user_decision": false          // SYSTEM: true => your decision was given for something that is no
                                         //                 longer what is there (re-decide: the inputs changed)
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
- **`stale_user_decision`** — `true` means the decision is kept as written but names something that no
  longer holds, so it takes no effect and the human should re-decide. Per cell:
  - **offset** (§4.4): `accept_proposal` whose `accepted_offset_seconds` is no longer the offset proposed
    (another offset now, beyond the GPX tolerance, or nothing proposed);
  - **timezone** (§4.3): a zone kept by `confirmed_despite_recorded_offsets` while the photos now record
    an offset that list does not name;
  - **drift** (§5a): a confirmation whose `confirmed_offset_seconds` is no longer the current offset
    (the photos-21 offset changed), or one of whose `confirmed_against_tracks` is gone from `gpx_root` or
    changed since (or which named none, and tracks now lie by the photos);
  - **folder fallback** (§5.3): `accept_proposal` with no inherited fallback to accept.

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
  "countries": {                           // SYSTEM: the countries a destination can be said to lie in, as
    "<ISO 3166 code>": { "name": "Belgium", "zones": ["Europe/Brussels"] }   // the zone database read
  },                                       //   this run has them ({} where it ships no such table)
  "depends_on": {                          // SYSTEM fingerprints
    "handoff": { … }, "camera_time_policy_fingerprint": "…", "gpx_fingerprint": "…",
    "camera_group_key_version": …
  },
  "decision_mode": "no_op_or_auto_resolved" // present ONLY when nothing requires input
}
```

`countries` is what `user_decision.country` (§4.3) is chosen from: its keys are the valid codes, each
with its English `name` and its `zones` (sorted).

### 4.2 A destination

```jsonc
{
  "destination_path": "Belgium/Brussels",
  "destination_timezone": { /* §4.3 tz cell */ },
  "camera_group_time_decisions": {                        // one offset cell per FIXED-CLOCK camera group,
    "<camera_group_key>": { /* §4.4 offset cell */ },     //   SPLIT per naive date when the group spans >1
    "<camera_group_key>@<YYYY-MM-DD>": { /* §4.4 */ }      //   day here (see §4.4 "per-date buckets")
  },
  "file_less": true                                       // SYSTEM, optional: a CONTAINER destination (see below)
}
```

Note: smartphones are resolved per-file and get **no** offset cell — `camera_group_time_decisions` only
holds `camera`-class groups (those listed under `fixed_clock_cameras`); smartphone, unidentified and
unknown groups have none. A photo whose time was read from `ModifyDate` (no valid
`DateTimeOriginal` or `CreateDate`: an export, timed by the editing computer) counts under `unknown`, as a file
naming no camera does — it opens no cell of its camera's and takes no offset from one. A bucket whose photos are all already corrected by
geotag gets a cell only when it still resolves (its earlier answer, derived again), so that photos of the
same camera and day arriving later take the same offset; such a cell never asks.

**Container destinations.** A folder that holds only sub-destinations (no media of its own) is still
emitted as a destination, flagged `"file_less": true`, so you can author timezone / fallback decisions on
it that propagate **downward** to its children. A container carries timezone and fallback cells (which
inherit), but **no offset cells at all** — `camera_group_time_decisions` is empty, because clock offsets
neither cascade down nor roll up and a file-less folder has no media to time-correct. Having no media to
act on, **none of a container's cells ever block**: each `requires_user_input` is `false` and an unset
timezone cell **auto-resolves by inheritance** (`decision_mode: "auto_resolved"`) while staying editable — or, with
nothing to inherit, is offered the configured default without asking for it.
The editor badges these destinations as `container` and keeps them off the to-do list.

### 4.3 `destination_timezone` cell

| Field | Type | Editable | Meaning |
|-------|------|----------|---------|
| `proposed_iana_timezone` | string \| null | no | Suggested zone, or null if none. |
| `proposal_source` | `"inherited"` \| `"country"` \| `"config_default"` \| `"none"` | no | Where the proposal came from. `country`: the one timezone of the country in effect; applies itself like `inherited`. `config_default`: the configured `default_folder_timezone` (within a country, only when it is one of the country's zones); only offered. |
| `inherited_from` | string | no | Present only when `proposal_source == "inherited"`: the ancestor destination. |
| `contradicted_by` | object | no | Present when the destination's own photos speak against its zone — the one written, else the one it would inherit. The photos counted are those not yet corrected, of any group but a fixed-clock camera (whose offset tag says what its clock was set to, not where it was), whose time is recorded with an offset that is not the zone's at that time: `{ "photos": int, "example": "<path>", "recorded_offset_seconds": int, "recorded_offsets": [int…], "timezone": "<zone>", "timezone_offset_seconds": int }` (`recorded_offsets`: each distinct one, sorted). The zone then does **not** take effect: the cell asks, and destinations inside inherit nothing through it, until another zone is written that the photos agree with, or the zone is kept by `confirmed_despite_recorded_offsets` (then `"confirmed": true` appears here). A destination has one timezone: photos taken in another belong in a folder of their own. |
| **`user_decision.country`** | string (`""`) | **yes** | The country this destination is in — it need not be the country's own folder — as an ISO 3166 code from the artifact's top-level `countries` table (`{ "<code>": { "name", "zones": [...] } }`, read from the zone database) — whatever the folder is called. A country of one timezone gives it to everything inside; one of several gives none, and each destination inside answers for itself, among `country_zones` only. Chosen once, at the top of its tree: inside a country none can be chosen, and one found there is written back `""` by the next run (`country_removed` says so). |
| `country` / `country_from` / `country_zones` | string / string / array | no | The country in effect here, where it was chosen (absent when chosen here), and its timezones — a `manual_iana_timezone` here must be one of them. |
| `country_removed` | object | no | Present for the run that took out a country chosen inside another: `{ "country", "because": "<destination above>", "country_there" }`. |
| **`user_decision.confirmed_despite_recorded_offsets`** | array of int | **yes** | The user's word that the zone holds for photos recording another offset (a phone left on another zone): the `recorded_offsets` it is given for. It holds while it lists every offset the contradicting photos record; a photo with yet another offset asks again (`stale_user_decision`). `[]` = not given. |
| **`user_decision.manual_iana_timezone`** | string (`""`) | **yes** | A human-entered IANA zone (e.g. `"Asia/Tokyo"`); with a country in effect, one of `country_zones`. |
| `effective_iana_timezone` | string (`""` if unresolved) | no | The resolved zone. |
| `requires_user_input` | bool | no | `true` ⇔ `effective_iana_timezone == ""` on a destination that is not a container — no valid zone written by hand and none to inherit (a configured `default_folder_timezone` is only offered, `proposal_source: "config_default"`, and takes effect once written as `manual_iana_timezone`), or a zone the destination's own photos contradict unanswered (`contradicted_by`). |
| `decision_mode` | `"auto_resolved"` | no | Present on **any** destination (container *or* real) whose proposal took effect without the user: an inherited zone (`proposal_source: "inherited"`) or a one-zone country's zone (`proposal_source: "country"`). Never for the configured default, which is only offered, nor when a manual zone is written. |
| `stale_user_decision` | bool | no | `true` when `confirmed_despite_recorded_offsets` is given but no longer covers every one of `contradicted_by.recorded_offsets` (a photo now records an offset the user did not speak for): kept as written, it takes no effect and the cell asks. Else `false`. |

Resolution: `manual_iana_timezone` (if valid, and one of `country_zones` with a country in effect) wins; else an
`inherited` or `country` proposal applies itself; with neither, the destination needs a zone written by hand. Either
way the zone takes effect only while the destination's own photos do not contradict it, or the user has kept it
despite them.

### 4.4 `camera_group_time_decisions[<key>]` offset cell

**Per-date buckets.** The cell key is normally the bare `<camera_group_key>`, but when a (camera group,
destination) spans **more than one naive calendar date** the cell SPLITS into per-day buckets keyed
`<camera_group_key>@<YYYY-MM-DD>` (the camera is set to local time each morning, so its offset is constant
only within a day). Each bucket carries a `date` field and proposes/resolves independently; a manual
decision on one day's bucket does not touch the others. The single-day common case keeps the bare key with
no `date`. Every cell names the day its photos are of in `day`, whatever its key: when a second day arrives
(or leaves) and the key changes form, a day's answer is found again by its `day`. Resolved-UTC picks each file's own naive-date bucket. Offsets do **not** inherit between
destinations or buckets.

| Field | Type | Editable | Meaning |
|-------|------|----------|---------|
| `camera_group` | string | no | The camera-group key (the bare group, even for a dated bucket). |
| `camera_group_class` | `"camera"` | no | Always `camera` here. |
| `date` | string | no | Present only on a per-date bucket: the naive calendar date (`"YYYY-MM-DD"`) this bucket covers. |
| `proposal` | object | no | One of five shapes — see below. |
| `representative` | object | no | On a cell with photos not yet corrected: the earliest of them, `{ "source_file", "camera_source_naive_time" }` — the photo the editor asks the true time of, to set the offset by. |
| `proposal.far_from_evidence` | object | no | On a `recorded_offset` or `timezone_naive` proposal that would put every photo of the cell not yet corrected farther than `gpx_anchor_max_clock_error_seconds` from every track point and from every photo of the destination by another device whose time is known (a smartphone's; a camera's not yet corrected whose cell's offset is from its GPS, the same day elsewhere, or written by hand) — there being at least one such photo: `{ "max_clock_error_seconds", "other_photos", "nearest_other_photo", "nearest_other_photo_seconds", "nearest_track_seconds" }` (`nearest_track_seconds` `""` with no track). The proposal does **not** take effect — accepted, or bound for photos-22 — and the cell asks for `manual_offset_seconds` (a clock reset to its factory date is the case). Present whatever the cell's decision. |
| `recorded_offsets_differ` | array | no | Present when the cell's photos record more than one UTC offset with their times: `[{ "recorded_offset_seconds", "photos", "example" }]`, one per offset, sorted. No `recorded_offset` proposal is made from them. |
| `day` | string | no | The naive calendar date this cell's photos are of (`"YYYY-MM-DD"`), on every cell whose photos have a readable camera time. |
| **`user_decision.accept_proposal`** | bool | **yes** | Accept the proposal's offset. |
| **`user_decision.accepted_offset_seconds`** | number \| `""` | **yes** | The `proposed_offset_seconds` being accepted — written together with `accept_proposal: true`, cleared with it. The acceptance holds only while this is what is proposed (within `acceptance_tolerance_seconds` for a GPX proposal): a proposal that became another one was never accepted, and the cell goes `stale_user_decision` and asks. `accept_proposal: true` with this empty is a blocker. |
| **`user_decision.manual_offset_seconds`** | number \| `""` | **yes** | A manual clock offset, seconds (camera_time + offset = real UTC). |
| `effective_time_anchor` | `""` \| object | no | `""` if unresolved; else `{ "offset_seconds": int, "source": … }` where source ∈ `manual` (a manual offset) \| `gpx_anchor_chosen` (a manual offset within `gpx_anchor_offset_spread_max_seconds` of one of a precise GPX proposal's `groups`) \| `gpx_anchor_accepted` \| `gpx_anchor_imprecise` (an accepted GPX proposal with `imprecise_seconds > 0`) \| `recorded_offset_accepted` \| `timezone_accepted` \| `same_day_accepted` (an accepted proposal of that kind) \| `gpx_anchor_auto` (a GPX proposal applied by itself, or kept from earlier) \| `same_day_auto` \| `recorded_offset_unconfirmed` \| `timezone_unconfirmed` (an offset from the photos' recorded offset, or from the timezone, sent to photos-22 to be confirmed). |
| `conflicts_with` | array | no | Present when the camera's own GPS gave another offset the same day in another destination, farther off than `clock_offset_same_day_max_difference_seconds`: `[{ "destination", "bucket", "offset_seconds" }]`. Neither offset takes effect; write `manual_offset_seconds` in the cell that is wrong. |
| `anchored_by` | list | no | On a cell whose offset applied itself from GPS: the track files it was found from, each `{ "gpx_file", "sha256" }`. The offset is kept for later photos of the day (`decision_mode: "kept_from_earlier"`) only while each is under `gpx_root` unchanged and no newer GPS proposal says otherwise. |
| `requires_user_input` | bool | no | `true` ⇔ `effective_time_anchor == ""`. (Containers carry no offset cells, so this is never softened here.) |
| `stale_user_decision` | bool | no | `accept_proposal` is set but `accepted_offset_seconds` is no longer the offset proposed (another offset beyond the tolerance, or none proposed): kept as written, it takes no effect, nothing applies itself in its place, and the cell asks. |
| `decision_mode` | `"auto_resolved"` \| `"kept_from_earlier"` \| `"to_be_confirmed_against_tracks"` | no | Present only when the offset took effect without the user. `auto_resolved`: a GPX self-anchor applied itself under the policy flags (`gpx_anchor_auto`), or a same-day shared offset did (`same_day_auto`). `kept_from_earlier`: the cell's earlier `gpx_anchor_auto` offset is kept (see `anchored_by`). `to_be_confirmed_against_tracks`: an offset from the photos' recorded offset or from the timezone is passed, unasked here, to photos-22 (`recorded_offset_unconfirmed`, `timezone_unconfirmed`). A manual or accepted offset carries none. Withdrawn when a same-day conflict (`conflicts_with`) withholds the offset. |

**`proposal` shapes** (all read-only; this is the evidence the UI shows). Tried in order: the GPX
self-anchor of the bucket's native-GPS frames; else, when the camera's GPS fixed its clock that day in
another destination, the same day elsewhere; else the offset the photos record; else the timezone-derived
offset; else manual required.

- **GPX self-anchor** (`proposal_source: "gpx_self_anchor"`) — geotag matched the group's geotagged
  frames against GPX tracks:
  ```jsonc
  {
    "proposal_source": "gpx_self_anchor",
    "proposed_offset_seconds": -3600,
    "proposed_real_utc": "2024-07-03T14:12:21Z",
    "confidence": "high",                 // "high" | "medium" | "review_required"
    "recommended_gpx_match": { "match_type": "gpx_point_match", "gpx_file": "…", "distance_m": 4.2,
                               "segment_duration_seconds": 0 },
    "anchor_count": 3, "supporting_count": 2, "conflicting_count": 0,
    "conflicting_files": [], "tied": false,
    "imprecise_seconds": 0,               // > 0: the tracks STAYED at these photos' place this long — the GPS
                                          // says where, not when; never auto-applied, and once accepted
                                          // (source gpx_anchor_imprecise) still confirmed in photos-22
    "acceptance_tolerance_seconds": 120,      // offsets this close are the same finding (for accepted_offset_seconds)
    "anchors": [ { "proposal_id": "anchor-001", "source_file": "…", "camera_source_naive_time": "…",
                   "native_gps": { … }, "gpx_match": { … }, "proposed_offset_seconds": -3600 }, … ],
    // collapsed view: the offset clusters, largest first (the recommended offset = the largest cluster)
    "groups": [ { "offset_seconds": -3600, "count": 2,
                  "representative": { "source_file": "6-photos-by-dest/Japan/Kyoto/IMG_1234.arw",  // FULL by-dest path
                                      "camera_source_naive_time": "2024:07:03 15:12:08",
                                      "real_utc": "2024-07-03T14:12:21Z",       // → corrected local time via the tz
                                      "match_type": "gpx_point_match", "gpx_file": "…", "distance_m": 4.2 } }, … ],
    // frames that produced no in-window anchor, by reason (a track only from another trip vs none nearby)
    "skipped": { "no_nearby_track": 0, "outside_time_window": 1,
                 "examples": [ { "source_file": "…", "reason": "outside_time_window" } ] }
  }
  ```
  The recommended `proposed_offset_seconds` is the **largest agreeing cluster** (consensus), not merely the
  closest single match; `anchors[0]` is that cluster's representative. The editor renders `groups` (top ~3)
  and `skipped` instead of dumping every anchor — see the offset proposal panel. It applies itself
  (`gpx_anchor_auto`) only with no conflicting frame, no tie and `imprecise_seconds == 0`, and only as the
  policy flags allow (`multi_anchor_auto_apply` for two or more anchors, `single_anchor_auto_apply` for one);
  otherwise it is accepted (`accept_proposal` + `accepted_offset_seconds`) or a group's offset is picked as
  `manual_offset_seconds` (`gpx_anchor_chosen`).
- **The offset the photos record** (`proposal_source: "recorded_offset"`) — no GPX anchor and no same-day
  offset, but the bucket's photos not yet corrected record a UTC offset with their times (`OffsetTimeOriginal`
  for a time read from `DateTimeOriginal` — the field paired with the one the time came from), and every one
  recording one records the same. The camera's clock was on that offset, so the clock offset is its negative:
  `{ "proposal_source": "recorded_offset", "proposed_offset_seconds": -3600, "recorded_offset_seconds": 3600,
     "recorded_by": int, "example": "<path>", "proposed_real_utc": "…Z", "confidence": "review_required" }`.
  A value in the tag that is no offset counts as none. Taking effect exactly as the timezone-derived offset
  below does: `recorded_offset_unconfirmed` to photos-22 where tracks lie by the photos, else accepted here
  (`recorded_offset_accepted`). Photos recording different offsets give no such proposal; the cell lists
  them in `recorded_offsets_differ`.
- **Timezone-derived** (`proposal_source: "timezone_naive"`) — no GPX anchor, but the destination's
  timezone is resolved, so the offset is derived from the bucket's local time assuming the camera clock
  tracked it (DST-aware, per day):
  `{ "proposal_source": "timezone_naive", "proposed_offset_seconds": int, "proposed_real_utc": "…Z",
     "proposed_from_timezone": "Europe/Brussels", "confidence": "review_required" }`.
  Confirmable only — the assumption can be wrong (camera on home time). Where tracks lie by the bucket's
  photos it is asked about once, in photos-22: the cell's effective source is `timezone_unconfirmed`
  (`decision_mode: "to_be_confirmed_against_tracks"`), nothing is asked here, and the drift confirmation
  is its acceptance. With no track by the photos it is accepted here (`accept_proposal` +
  `accepted_offset_seconds`).
- **The same day elsewhere** (`proposal_source: "same_day_elsewhere"`) — no photo of the bucket has its
  own position, and the camera's GPS fixed its clock that day in another destination:
  `{ "proposal_source": "same_day_elsewhere", "proposed_offset_seconds": int,
     "shared_from": { "destination": "…", "bucket": "…" }, "confidence": "high" | "review_required" }`.
  `high`: it applied itself there and applies itself here (`same_day_auto`, `decision_mode: "auto_resolved"`).
  `review_required`: accept it here (`same_day_accepted`). It takes the place only of a proposal that would
  be `recorded_offset`, `timezone_naive` or `manual_required`. Never another day's offset, never one written by hand (the
  donor's source is `gpx_anchor_auto` or `gpx_anchor_accepted`, one that applied itself chosen first, then
  by path). Neither same-day source is drift-checked in photos-22.
- **Manual required** (`proposal_source: "manual_required"`) — no signal: no anchor, no same-day offset,
  and no timezone-derived offset (no resolved timezone, no readable camera time, or a camera time the zone
  reads two ways); the human must enter a manual offset (or real UTC): `{ "proposal_source": "manual_required" }`.
  When the zone is resolved but the bucket's earliest camera time falls at one of its daylight-saving changes
  — a time the clocks there showed twice, or skipped — no offset is guessed, and the proposal says why:
  ```jsonc
  { "proposal_source": "manual_required",
    "timezone_ambiguous": { "camera_time": "2024:10:27 02:30:00", "timezone": "Europe/Brussels",
                            "case": "repeated",               // "repeated" | "skipped"
                            "offsets_seconds": [7200, 3600] } }  // the zone's UTC offset before the change, after it
  ```

---

## 5. `photos-23-gps-decisions.json` (GPS)

### 5.1 Top level

Same wrapper as §4.1 with `artifact_type: "gps_decisions"` / `artifact_name:
"photos-23-gps-decisions.json"`, but no `countries`; its `depends_on` holds `resolved_utc_cache_fingerprint`,
`gpx_fingerprint`, `gps_policy_fingerprint` and `handoff`, and it carries `track_disagreements` and
`lower_track_disagreements` when there were any (§5.4). `destinations` is keyed by destination path; each destination is §5.2.

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
  },
  "file_less": true                        // SYSTEM, optional: a container destination (§4.2) — its fallback
}                                          //   only seeds the destinations inside it
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
| `relative_path` | string | no | Workspace-relative path of the photo (e.g. `6-photos-by-dest/Japan/IMG_1.arw`). The editor's save names a review item by it. |
| `content_fingerprint` | string \| null | no | The photo's identity. A decision is found again by it — through geotag's own rename of the photo — not by the path. |
| `tracks` | object | no | On a `no_reliable_gps_source` or `accepted_unlocated` photo that has a resolved time and that the tracks did not place: why. `reason` with its evidence: `no_tracks` (no track at all); `outside_track` + `seconds_from_track`; `track_gap` + `seconds_from_track` + `gap_seconds`, and `segment_break: true` when the gap is a break between two `<trkseg>` of the track (never bridged, however short); `track_jump` + `seconds_from_track` + `jump_meters`; `tracks_disagree` + `gpx_files` (the two tracks — each a file name, or `"<file> (track N)"` when both are tracks of one file) + `apart_meters`. Where several tracks miss, the one nearest in time speaks. |
| `reason` | `"no_reliable_gps_source"` \| `"manual_locked"` \| `"accepted_unlocated"` | no | Why it's here (see below). |
| **`user_decision.manual_lat`** | number \| `""` | **yes** | Human-entered latitude (set both). |
| **`user_decision.manual_lon`** | number \| `""` | **yes** | Human-entered longitude. |
| **`user_decision.accept_unlocated`** | bool | **yes** | Accept leaving this file with no GPS (taken only when neither the tracks nor the folder fallback place it). |
| `requires_user_input` | bool | no | `true` only for `no_reliable_gps_source` (until resolved). |
| `stale_user_decision` | bool (always `false`) | no | — |

`reason` values:
- **`no_reliable_gps_source`** — *blocked*; `requires_user_input: true`. The human resolves it by setting
  `manual_lat`+`manual_lon` **or** `accept_unlocated: true`. On the next run it reclassifies (below).
- **`manual_locked`** — informational: a valid manual coordinate is already set. Editable (change/clear it).
- **`accepted_unlocated`** — informational: `accept_unlocated` is set, so the file stays without GPS.
  Editable.

(So resolving a `no_reliable_gps_source` item → after re-run it becomes `manual_locked` or
`accepted_unlocated` with `requires_user_input: false` — or, with `accept_unlocated` and a folder fallback
or track that now places it, it is placed and only counted. A photo with its own GPS is preserved and never
listed. The editor's per-file to-do list is the `no_reliable_gps_source` items.)

The record's top-level `track_disagreements` (read-only, present only when it happened) lists each pair of
tracks that cover the same time in places farther apart than `gpx_tracks_agree_max_distance_meters`, and how
many photos neither placed because of it — `[ { "gpx_files": ["a.gpx", "b.gpx"], "photos": 12 } ]`, the names
as in `tracks.gpx_files` above. Those photos fell to their folder's fallback or are in `review_items`; the cure
is to file your own track in a folder `gpx_track_precedence` ranks, or to take the track that is not this trip's out
of `gpx_root`. Only tracks of one rank are compared this way.

`lower_track_disagreements` (read-only, present only when it happened) lists each lower-ranked track that put
photos more than `gpx_tracks_agree_max_distance_meters` from where a higher-ranked one placed them, and how many —
`[ { "gpx_file": "receiver/r.gpx", "outranked_by": "phone/p.gpx", "photos": 3 } ]`. The higher-ranked track placed
them; nothing here asks. It measures the worse device's error.

### 5.5 `summary` (read-only counts)

`files_total`, `preserve_native_gps`, `automatic_gpx_interpolation`, `automatic_gpx_extrapolation`,
`automatic_folder_fallback`, `manual_locked`, `manual_review_required`, `blocked`,
`no_gps_change_needed`. Useful for a per-destination progress display; the editor never writes these. A photo
whose position is exactly latitude 0, longitude 0 — what a device writes with no fix — counts as having none: it is
never in `preserve_native_gps`, and is placed like any photo without a position.

---

## 5a. `photos-22-gps-drift-validation.json` (GPS-drift validation)

A gate the pipeline writes **between** photos-21 and photos-23 (`BLD-drift_validation`), once photos-21 is
complete. It flags every `(camera group, destination[, date])` offset bucket whose photos-21 offset no
photo's own GPS pins — its `effective_time_anchor.source` is one of:

- `manual` — a manual offset (not one picked from a GPX group, which is `gpx_anchor_chosen`);
- `timezone_accepted` — an accepted timezone-derived offset;
- `timezone_unconfirmed` — a timezone-derived offset nobody has accepted, sent here to be confirmed
  (`decision_mode: "to_be_confirmed_against_tracks"` in photos-21);
- `recorded_offset_accepted` / `recorded_offset_unconfirmed` — the same two, for an offset from the photos'
  recorded offset;
- `gpx_anchor_imprecise` — an accepted GPX proposal whose track stood still at the photos' place
  (`imprecise_seconds > 0`): the GPS says where, not when;

— and whose not-yet-corrected photos lie within `drift_check_track_window_seconds` of track points, by
their resolved times or, none lying there, by the times the camera recorded read as UTC — exactly the case
where a wrong offset would silently mis-place the whole bucket along the track. A `timezone_unconfirmed` or
`recorded_offset_unconfirmed` bucket is listed **always**, with or without track coverage (its `track_segment` may then be empty): an
offset nobody has accepted is never passed over. GPS-anchored (`gpx_anchor_auto` / `_accepted` / `_chosen`)
and same-day (`same_day_*`) offsets are not checked. Each flagged bucket must be **explicitly confirmed**
(or corrected) before photos-23 is generated; a bucket that no longer qualifies is dropped with its
confirmation.

### 5a.1 Top level

Same decision wrapper as §4.1 with `artifact_type: "gps_drift_validation"` / `artifact_name:
"photos-22-gps-drift-validation.json"` — except its top-level `decision_mode`, when present (nothing
requires input), is `"no_op_or_confirmed"` (not `"no_op_or_auto_resolved"`), and it has no `countries`. Its
`depends_on` holds `photos_21_sha256`, `gpx_fingerprint`, `camera_time_policy_fingerprint` and
`camera_group_key_version`. `destinations` maps a destination path to
`{ "destination_path", "drift_decisions": { <bucket_key>: cell } }` — only destinations with a flagged bucket
appear. The `<bucket_key>` matches the photos-21 offset cell it refines — bare `<camera_group_key>` or
`<camera_group_key>@<YYYY-MM-DD>`; like that cell, its earlier answer is found again by its `day`.

### 5a.2 A `drift_decisions[<bucket>]` cell

```json
{
  "camera_group": "SONY|ILCE-6400|A",
  "date": "2024-07-03",
  "day": "2024-07-03",
  "proposal": {
    "proposal_source": "timezone_accepted",
    "current_offset_seconds": -7200,
    "frames": [ { "source_file": "6-photos-by-dest/Belgium/Brussels/a.arw", "camera_naive": "2024:07:03 14:00:00" }, ... ],
    "track_segment": [ { "lat": 50.0, "lon": 4.0, "time_utc": "2024-07-03T12:00:00Z" }, ... ],
    "tracks": [ { "gpx_file": "2024/trip-2024-07-03.gpx", "sha256": "3a52…" } ]
  },
  "user_decision": { "confirmed": false, "corrected_offset_seconds": "", "confirmed_offset_seconds": "",
                     "confirmed_against_tracks": [] },
  "confirmed_tracks_changed": [],
  "effective_drift_offset": "",
  "requires_user_input": true,
  "stale_user_decision": false
}
```

- `proposal.proposal_source` is the photos-21 cell's effective source — `manual`, `timezone_accepted`,
  `timezone_unconfirmed`, `recorded_offset_accepted`, `recorded_offset_unconfirmed` or `gpx_anchor_imprecise`
  (above). `current_offset_seconds` is the offset photos-21
  resolved.
- `proposal.track_segment` is read-only evidence — the GPX points within `drift_check_track_window_seconds`
  (a setting; default 172800 s, two days) either side of the bucket's photos' resolved times, or, none lying
  there, of their recorded camera times read as UTC. The window is wide so a scrub finds the correct point in
  the segment already, without a re-run to fetch more track.
- `proposal.frames` is read-only — every photo in the bucket as `{source_file, camera_naive}`,
  earliest first. The editor scrubs one (default the earliest) along the track and **computes** the
  decision: `corrected_offset_seconds = (chosen track point's time_utc) − (that frame's camera_naive)`.
  Both `track_segment` and `frames` are re-extracted by the script on every re-run, so a changed
  photos-21 time decision shifts them automatically.
- `proposal.tracks` is read-only — the track files `track_segment` is drawn from, by their path under
  `gpx_root`, each with the SHA-256 of its bytes as geotag read it (`BLD-drift_confirmation_tracks`): the
  tracks the editor shows for this bucket, and what a confirmation names.
- `user_decision.confirmed` (bool) — the **only** thing that satisfies the gate. `false` (the default)
  blocks. **A "zero scrub" / "the offset was right" must be set explicitly** (`confirmed: true` with an
  empty `corrected_offset_seconds`) — inaction never counts.
- `user_decision.corrected_offset_seconds` — empty for a zero scrub, or the corrected offset itself (a whole
  number of seconds that replaces `current_offset_seconds` for the whole bucket — not a difference from it).
- `user_decision.confirmed_offset_seconds` — the offset the confirmation was made against: the
  `proposal.current_offset_seconds` shown when confirming (the editor writes it). A confirmation holds only
  while it equals the current offset; the offset changed in photos-21 since, the cell is
  `stale_user_decision: true` and asks again until confirmed anew. `confirmed: true` with it empty is a
  located blocker naming the current offset.
- `user_decision.confirmed_against_tracks` — the tracks the confirmation was made against: a copy of
  `proposal.tracks` as shown when confirming (the editor writes it with `confirmed_offset_seconds`; `[]` when
  unconfirmed). A confirmation holds only while every track it names is still under `gpx_root` with the SHA-256
  it names — a track taken out, or replaced by another export, and the cell is `stale_user_decision: true`,
  the decision kept exactly as written, and asks again. A track put in **beside** the named ones does not unseat
  it. A confirmation made where no track was shown names `[]`, and holds only while `proposal.tracks` is still
  empty: a track arriving later is one nobody looked at the photos against. `confirmed: true` without a list
  here is a located blocker.
- `confirmed_tracks_changed` — read-only: the named tracks geotag no longer found under `gpx_root` with the
  SHA-256 named (`[]` when all stand). The editor uses it to tell a confirmation that rests on a track no longer
  shown from one that still holds.
- `effective_drift_offset` — `""` until confirmed, then `{ "offset_seconds": N, "source":
  "gps_drift_validated" }`. Geotag recomputes resolved UTC consuming this; the value does **not**
  mutate the photos-21 decision it refines.

### 5a.3 `date`

Present only when the bucket is per-date (the group spans >1 naive day in this destination, `BLD-offset_buckets`);
omitted for a single-date bucket. `day`, copied from the photos-21 cell, is on every cell whose photos have a
readable date, whatever its key.

---

## 6. Within-cell precedence (which `user_decision` field wins)

A cell can carry more than one decision field; geotag applies them in a fixed order. The editor's
UI should make the *effective* choice obvious and ideally offer them as mutually-exclusive.

- **Timezone:** `manual_iana_timezone` (if valid, and one of `country_zones` with a country in effect) → else
  an `inherited` or `country` proposal, which applies itself (a `config_default` one is only offered). Either
  takes effect only while the destination's photos do not contradict it unanswered (`contradicted_by`,
  `confirmed_despite_recorded_offsets`).
- **Clock offset:** `manual_offset_seconds` (if set & valid; `gpx_anchor_chosen` when it is one of a precise
  GPX proposal's groups, else `manual`) → `accept_proposal` (while `accepted_offset_seconds` is the offset
  proposed; a stale acceptance stops here, the cell asking) → with no human input, in order: the GPX
  self-anchor applying itself under the policy flags (`gpx_anchor_auto`) → the cell's earlier `gpx_anchor_auto`
  offset kept (`kept_from_earlier`, while every `anchored_by` track is unchanged under `gpx_root` and no new
  GPS proposal disagrees, conflicts or is imprecise) → a same-day shared offset that applied itself in its
  own destination (`same_day_auto`) → an offset from the photos' recorded offset or from the timezone, with
  tracks by the photos, sent to photos-22 (`recorded_offset_unconfirmed`, `timezone_unconfirmed`). Setting a manual offset overrides `accept_proposal`. Two GPS-derived offsets of
  one camera and day in different destinations that differ by more than
  `clock_offset_same_day_max_difference_seconds` both lose effect (`conflicts_with`); a manual one is never
  withheld. A `recorded_offset` or `timezone_naive` proposal carrying `far_from_evidence` takes no effect,
  accepted or not: only `manual_offset_seconds` resolves the cell.
- **Drift:** `confirmed` holding for the current offset (`confirmed_offset_seconds` equal to it) and for the
  tracks (`confirmed_against_tracks` each unchanged under `gpx_root`, or `[]` with no track shown) →
  `corrected_offset_seconds` if given, else the current offset; otherwise nothing.
- **Folder fallback:** `fallback_lat`+`fallback_lon` (if both set & valid) → `accept_proposal`.
- **Per-file GPS:** the photo's own GPS (preserved; no decision read) → `manual_lat`+`manual_lon` (if both set
  & valid) → the tracks at its resolved time → the folder fallback → `accept_unlocated`. (If none applies the
  file stays blocked = `no_reliable_gps_source`.)

A bare `""`/`false` everywhere = "no decision yet".

---

## 7. Validation rules for editable values

Mirror these client-side; a value that fails makes geotag reject the whole artifact as a blocker.
(Source: the `_valid_*` helpers in `cartographer/_geotag_calc.py`, `_decision_flag` and the cell builders in
`cartographer/photos_2_geotag.py`.)

| Field(s) | Rule |
|----------|------|
| `country` | `""` (= none), or a code that is a key of the top-level `countries` table; any other value is a blocker, as is any value where the host's zone database has no table of countries (`countries` is `{}`). One chosen inside another country's destination is not a blocker: the next run writes it back `""` (`country_removed`). |
| `manual_iana_timezone` | Must resolve as a real IANA zone in the zone database geotag runs with — never a name standing for the host (`localtime`, `posixrules`, `Factory`). With a country in effect (`country_zones` present), it must be one of `country_zones`. `""` allowed (= unset). |
| `confirmed_despite_recorded_offsets` | A list of whole numbers of seconds; `[]` = not given. |
| `manual_offset_seconds` | A whole number of seconds (an integer, or a float with no fraction), of any size (a clock reset to its factory date is years out). Not a boolean, not a string. `""` allowed. |
| `accepted_offset_seconds` | Required, as a whole number of seconds, whenever `accept_proposal` is `true` (and no manual offset is set): the `proposed_offset_seconds` accepted. `""` with `accept_proposal: false`. |
| `confirmed_offset_seconds` (photos-22) | Required, as a whole number of seconds, whenever `confirmed` is `true`: the `current_offset_seconds` confirmed against. `""` with `confirmed: false`. |
| `confirmed_against_tracks` (photos-22) | Required whenever `confirmed` is `true`: a list (`[]` allowed, only meaning "no track was shown") of `{ "gpx_file": <path under gpx_root>, "sha256": <its SHA-256> }`, each a non-empty string — copied from `proposal.tracks`. `[]` with `confirmed: false`. |
| `corrected_offset_seconds` (photos-22) | `""` (zero scrub) or a whole number of seconds. |
| `fallback_lat` / `fallback_lon`, `manual_lat` / `manual_lon` | Numbers (not booleans, not strings); latitude ∈ [-90, 90], longitude ∈ [-180, 180]. Set both or neither. `""` allowed (= unset). |
| `accept_proposal` / `accept_unlocated` / `confirmed` | `true` or `false` (absent or `null` reads as `false`); anything else — `"false"`, `1`, `"yes"` — is a blocker, never coerced. Default `false`. |

---

## 8. Suggested editor model (non-binding)

A natural shape that satisfies the contract:

1. Load the JSON; index the cells by location (destination path → timezone / fallback cell; → offset or
   drift bucket key; → review item `relative_path`), keeping the `hashes` the load came with (below).
2. Build the to-do list from `requires_user_input: true` (plus surface `stale_user_decision: true` as
   "re-decide"). Show `proposal` + evidence for each.
3. Let the human edit only `user_decision`; validate per §7 live; show a computed preview of the outcome
   if desired (display-only — not written authoritatively).
4. Save by writing the modified `user_decision` blocks back into the loaded JSON (round-trip, preserving
   all other fields and unknown keys) and serialising. The human then re-runs `photos-cartographer geotag plan`,
   which regenerates the artifact, reads back the `user_decision` values, recomputes everything, and validates.

**The save contract (this editor's server).** `GET /api/artifacts` returns `{ "workspace", "demo", "time",
"drift", "gps", "hashes" }` — the three records as loaded, and in `hashes` (`{ "time", "drift", "gps" }`) the
SHA-256 of each record's bytes as read (`null` for a record that is absent). `POST /api/save` takes:

```jsonc
{
  "time":  [ { "dest": "<destination_path>", "kind": "timezone" | "offset", "key": "<bucket key, for offset>",
               "user_decision": { … } } ],
  "drift": [ { "dest": "…", "kind": "drift", "key": "<bucket key>", "user_decision": { … } } ],
  "gps":   [ { "dest": "…", "kind": "fallback" | "review", "path": "<relative_path, for review>",
               "user_decision": { … } } ],
  "hashes": { "time": "…", "drift": "…", "gps": "…" }   // as the editor loaded them
}
```

The save takes the workspace lock for the time it writes and is refused at once while a run holds it, or
when the workspace is sealed. Under the lock it is refused — **nothing written, none of the three** — when:
`hashes` is missing; any record on disk is not the one the editor loaded (its hash differs: a geotag plan
may have rewritten it — reload and edit again); or an edit names a decision its record does not hold (no such
destination, cell, bucket key or review item) or carries no `user_decision` object. Otherwise each named
cell's `user_decision` is **replaced whole** by the one sent (nothing else in the record is touched), each
edited record is written atomically (sorted keys, two-space indent), and the reply is
`{ "ok": true, "written": [<record names>], "hashes": { … } }` — the records' new hashes, which the next save
must carry. A refusal is `{ "ok": false, "error": "…" }`. Demo mode (`--demo`) refuses every save.
