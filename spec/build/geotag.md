# Geotag — how this build does it

How this build meets [geotag's intent](../intent/geotag.md) and the shared contract's geotag rules: the files, names,
tools and steps. Each item `realises` the intent it implements. *Why* a choice was made is in
[the rationale](../rationale/geotag.md).
Sections are numbered as in the phase's original spec; a section whose content lives in the shared contract, or
that only restated others, has no heading here.

## 2. Core workflow rule

:::{bld} Geotag's planning stages, in order
:id: BLD-geotag_stage_order
:status: ruled
:realises: RUL-time_before_gps, RUL-decision_stage_writes_record, RUL-no_record_before_decisions
:aliases: geotag-gpx-after-recognition-1, geotag-gpx-before-time-1, geotag-no-utc-incomplete-tz-1

`geotag plan` SHALL recognise the camera groups — stopping on an unknown one before reading any track — then read the
tracks, then write `photos-21-time-decisions.json`; only once it is complete resolve each photo's true time and
write `photos-22-gps-drift-validation.json`; only once that is complete write `photos-23-gps-decisions.json`; and only
once all three are complete assemble `photos-24-executable-plan.json`, which refuses any photo without a valid
resolved time.
:::

:::{bld} Geotag's preflight refuses a photo with no recorded time
:id: BLD-geotag_untimed_gate
:status: ruled
:realises: RUL-untimed_photo_stops_geotag

Geotag's preflight for `plan` SHALL block on every handoff record of a photo under `6-photos-by-dest` whose
`metadata_status.has_timestamp` — or, failing it, the `has_timestamp` of its `parsed_json` — is false, naming the
photos and `2-missing-metadata`.
:::

## 3. Artifact dependencies

:::{bld} Geotag's dependencies, recorded and checked
:id: BLD-geotag_dependencies
:status: ruled
:realises: RUL-geotag_plan_carries_every_dependency, INV-no_stale_use, RUL-hash_is_the_dependency_check, RUL-handoff_verified_by_content
:aliases: geotag-transitive-verify-1, geotag-summary-not-dependency-1

`photos-24-executable-plan.json` SHALL record in `depends_on` the SHA-256 of `photos-21`, `photos-22` and `photos-23`;
the handoff's `content_fingerprint`; `config_fingerprint`, `code_fingerprint`, `camera_group_fingerprint`,
`camera_group_key_version`, `gpx_fingerprint`, `metadata_field_set_version`, `filename_format_fingerprint`,
`folders_fingerprint` and `media_extensions_fingerprint`; `resolved_utc_cache_fingerprint` and
`prep_cache_fingerprint`; each photo's `media_preconditions`; and `planned_operation_fingerprint`. Execute recomputes
all but the two cache fingerprints — vouched for by the records and handoff they were derived from, checked where they
are made — before any change, and each photo's preconditions as it applies it. `photos-25-execution-summary.json` is
never checked as a dependency.
:::

## 7. Geotag scope

:::{bld} Geotag's file model
:id: BLD-geotag_file_model
:status: ruled
:realises: RUL-geotag_changes_only_by_dest
:aliases: geotag-inmemory-bydest-only-1

Geotag's `build_file_model` SHALL take, from the handoff, only the records whose `folder_class` is `6-photos-by-dest`
and whose `media_class` is `image` or `raw`; every operation of `photos-24-executable-plan.json` names one of them.
:::

## 9. Human decision field rule

:::{bld} The auto-apply settings
:id: BLD-auto_apply_settings
:status: ruled
:realises: RUL-anchor_offset_auto_as_configured, RUL-timezone_auto_resolves, RUL-other_proposals_need_acceptance

A GPX self-anchor offset SHALL be set as `effective_time_anchor` with `decision_mode: "auto_resolved"` when its
anchors do not conflict and `camera_time_and_timezone_policy.multi_anchor_auto_apply` holds for two or more anchors,
or `single_anchor_auto_apply` for one; a destination's inherited or `default_folder_timezone` proposal is set as its
`effective_iana_timezone` likewise; a `timezone_naive` offset proposal and an `inherited` folder fallback become
effective only with `accept_proposal: true`.
:::

## 10. Per-destination structure

:::{bld} Geotag's destinations
:id: BLD-geotag_destinations
:status: ruled
:realises: DEF-destination, DEF-container_destination, RUL-container_never_waits

A photo's destination SHALL be the `dirname` of its path; the container destinations are every ancestor of a
destination within `6-photos-by-dest` that is not one, `6-photos-by-dest` included, each marked `file_less: true` in the
decision records, its timezone and fallback cells never requiring input and its `camera_group_time_decisions` empty;
destinations are processed parents first.
:::

:::{bld} Offset buckets
:id: BLD-offset_buckets
:status: ruled
:realises: RUL-offset_per_camera_destination_day, RUL-offset_from_own_evidence

Each destination's `camera_group_time_decisions` SHALL hold one cell per camera group present, keyed by its
`camera_group_key`, or — when the group's photos there span more than one naive date — one per date, keyed
`<camera_group_key>@<YYYY-MM-DD>` with a `date` field, the date taken from `source_naive_time`. A cell's proposal is
the GPX self-anchor of that group's native-GPS frames of that date there; else, with the destination's timezone
resolved, `timezone_naive` at the cell's earliest naive time, DST-aware; else `manual_required`. No cell reads another
destination's.
:::

:::{bld} Geotag's records are grouped by destination
:id: BLD-geotag_records_by_destination
:status: ruled
:realises: RUL-decision_fields_laid_out
:aliases: geotag-artifacts-per-destination-1

`photos-21`, `photos-22`, `photos-23` and `photos-24` SHALL each hold a `destinations` object keyed by the
destination's path under `6-photos-by-dest`, every decision of a destination inside its entry.
:::


## 15. Reading the tracks

:::{bld} How track points are read
:id: BLD-track_points
:status: ruled
:realises: RUL-track_time_never_guessed, RUL-unreadable_point_reported
:aliases: geotag-gpx-time-xsd-datetime-1, geotag-gpx-rejected-points-reported-1

Geotag SHALL read every `<trkpt>` of each `*.gpx` file under `gpx_root`, its `<time>` as an `xsd:dateTime` — fractional
seconds optional, the zone `Z` or a numeric offset — normalised to UTC; a point lacking `lat` or `lon`, with one out of
range or not a number, lacking a `<time>`, or with a time unparseable or naive is skipped with a warning naming the
file and the point's index, as is a file that cannot be read or parsed. `geotag plan` prints the count of warnings and
the first `GPX_WARNINGS_SHOWN`, with the number of the rest.
:::


## 16. Camera groups

:::{bld} The classification snippet
:id: BLD-unknown_group_snippet
:status: ruled
:realises: RUL-unknown_group_stops_geotag, RUL-unknown_group_classification_offered

On an unknown camera group, `geotag plan` SHALL print the `device_groups` arrays `fixed_clock_cameras` and `phones`,
in the configuration's own key order, each the configured list with every unknown key appended, as JSON to paste over
the configuration's, and exit with status 2 having written no record and read no track.
:::

:::{bld} Files naming no camera
:id: BLD-unidentified_files
:status: ruled
:realises: RUL-unidentified_files_solved_alone

A file whose `camera_group_key` is `NO_IDENTITY_KEY` (`unknown`), the key prep gives a file with no serial, make, model
or owner, SHALL be classed `unidentified` by `recognize_camera_groups` whatever the configuration lists, never among the
unknown groups, given no offset cell, and resolved as a phone's photo is, its own offset's rule being
`unidentified_native_offset`.
:::


## 18. Destination civil timezone

:::{bld} The timezone cell
:id: BLD-timezone_cell
:status: ruled
:realises: RUL-timezone_from_nearest, RUL-timezone_auto_resolves
:aliases: geotag-timezone-every-destination-1

Each destination's `destination_timezone` in `photos-21-time-decisions.json` SHALL hold `proposed_iana_timezone` with
its `proposal_source` — `inherited`, naming the ancestor in `inherited_from`, or `config_default`, or `none` —
`user_decision.manual_iana_timezone`, `effective_iana_timezone`, `requires_user_input`, `stale_user_decision` and, when
the proposal took effect without the user, `decision_mode: "auto_resolved"`. Destinations are built parent first, so
each takes the `effective_iana_timezone` of its nearest ancestor that has one, `6-photos-by-dest` itself the first,
from `default_folder_timezone`.
:::


## 19. Clock offsets from the camera's own GPS

:::{bld} How anchors are matched and agreed
:id: BLD-anchor_matching
:status: ruled
:realises: RUL-anchor_within_clock_error, RUL-anchor_consensus, RUL-revisit_matched_to_its_day, RUL-indistinct_visits_wait, RUL-chosen_group_is_anchored, RUL-anchor_offset_auto_as_configured
:aliases: geotag-anchor-matching-1, geotag-conflict-triggers-review-1

For each native-GPS photo of a (camera group, destination, day) bucket, `frame_candidates` SHALL take every track
point within `gpx_anchor_max_point_distance_meters` of it and every segment — two consecutive points at most
`gpx_interpolation_max_gap_seconds` apart — within `gpx_anchor_max_segment_distance_meters`, each at a time within
`gpx_anchor_max_clock_error_seconds` of the photo's camera time read as UTC; split them into passes where more than
`gpx_interpolation_max_gap_seconds` separates two in time; and keep each pass's best, a point before a segment, then the
closest. `infer_anchor_proposal` clusters the candidates' offsets within `gpx_anchor_offset_spread_max_seconds` and
proposes the cluster the most photos support, a tie going to the smaller offset, its best-ranked candidate the
representative; its confidence is `review_required` when a photo supports no pass of it or another cluster ties
(`tied`), else `high` when another photo supports it or it is a point match, else `medium`. Only an agreed offset — no
conflicting photo, no tie — applies itself, under `multi_anchor_auto_apply` or `single_anchor_auto_apply`. The proposal
names the photos no pass of which agrees (`conflicting_files`), and each cluster in `groups` with its photo count and a
representative, its track file included; a `manual_offset_seconds` within `gpx_anchor_offset_spread_max_seconds` of a
group's offset takes effect as `gpx_anchor_chosen`, which no drift check follows.
:::

:::{bld} The offset derived from the timezone
:id: BLD-timezone_naive_offset
:status: ruled
:realises: RUL-offset_from_own_evidence, RUL-other_proposals_need_acceptance
:aliases: geotag-tz-derived-offset-calc-1

A bucket with no anchor and a destination timezone SHALL be proposed the offset −(the timezone's UTC offset at the
bucket's earliest camera time), daylight saving included, as `proposal_source: "timezone_naive"` with
`proposed_offset_seconds`, `proposed_real_utc` and `proposed_from_timezone`; it takes effect only once accepted.
:::

## 20. The decision records

:::{bld} What every decision record carries
:id: BLD-decision_record_envelope
:status: ruled
:realises: RUL-decision_stage_writes_record, INV-no_stale_use
:aliases: geotag-config-change-restales-21-1

`photos-21-time-decisions.json`, `photos-22-gps-drift-validation.json` and `photos-23-gps-decisions.json` SHALL each
carry `artifact_type`, `artifact_name`, `status` — `requires_user_input` or `complete` — `requires_user_input`, true
when any of its cells needs the user, `executable: false`, `depends_on`, and, when complete, `decision_mode`:
`no_op_or_auto_resolved` for photos-21 and photos-23, `no_op_or_confirmed` for photos-22. The `depends_on` of photos-21
holds the handoff's content fingerprint, `camera_time_policy_fingerprint` — over the whole
`camera_time_and_timezone_policy`, the camera groups' classes included — `gpx_fingerprint` and
`camera_group_key_version`.
:::


## 22. Resolved UTC

:::{bld} How each photo's true time is resolved
:id: BLD-resolved_utc
:status: ruled
:realises: RUL-phone_time_from_own_offset, RUL-offset_per_camera_destination_day, RUL-time_before_gps
:aliases: geotag-compute-resolved-utc-1, geotag-utc-after-validation-1

`compute_resolved_utc` SHALL resolve each photo of photos by destination to UTC: a camera's photo by the offset of its
cell — `<group>@<date>` where the destination has one for its date, else `<group>` — a corrected offset from
`photos-22-gps-drift-validation.json` taking its place (`camera_group_offset`); a phone's by the offset recorded with
its time's field — `OffsetTimeOriginal` for `DateTimeOriginal`, `OffsetTimeDigitized` for `CreateDate`, `OffsetTime`
for `ModifyDate` (`smartphone_native_offset`) — else its destination's timezone (`destination_timezone`); and a time
geotag already corrected by its own offset, else the timezone (`geotag_corrected`); every other photo `unresolved`.
`geotag plan` writes the rows — `relative_path`, `destination_path`, `destination_timezone`, `camera_group`,
`time_decision_scope` (the cell, `<group>[@<date>]|<destination>`), `source_naive_time`, `source_time_provenance`,
`time_rule_used`, `utc_offset_used`, `resolved_utc`, `resolved_utc_status`, `resolved_utc_provenance` — into the
`resolved_utc_cache` table once photos-22 is complete, replacing the table whole.
:::

:::{bld} The resolved-UTC fingerprint
:id: BLD-resolved_utc_fingerprint
:status: ruled
:realises: INV-no_stale_use, RUL-staleness_by_area, RUL-tracks_in_dependencies
:aliases: geotag-utc-fingerprint-1, geotag-utc-not-restaled-by-unrelated-config-1

`resolved_utc_cache_fingerprint` SHALL be the SHA-256 over the rows ordered by path — each its `relative_path`,
`resolved_utc`, `resolved_utc_status`, `time_rule_used`, `utc_offset_used` and `source_time_provenance` as text — and
the inputs, sorted by name: `camera_time_policy_fingerprint`, `camera_group_key_version`, the SHA-256 of photos-21 and
of photos-22, `prep_cache_fingerprint`, `metadata_field_set_version` and `gpx_fingerprint`, the last whether or not a
track decided anything.
:::


## 22a. The GPS-drift check

:::{bld} The drift check
:id: BLD-drift_validation
:status: ruled
:realises: RUL-unanchored_offset_confirmed, RUL-confirmation_holds_for_its_offset
:aliases: geotag-drift-trigger-1, geotag-drift-gate-position-1, geotag-drift-confirmation-preserved-1, geotag-drift-corrected-validated-1, geotag-drift-not-mutate-21-1, geotag-drift-recompute-utc-1, geotag-drift-withdrawal-rejects-plan-1

Once photos-21 is complete, `geotag plan` SHALL write `photos-22-gps-drift-validation.json` with a cell for each
offset cell whose effective source is `timezone_accepted` or `manual`, none of whose photos not yet corrected anchors on
the tracks, and whose photos' resolved times lie within `gpx_anchor_max_clock_error_seconds` of track points: its
`proposal` holding `current_offset_seconds`, its source, the photos and that track segment; its `user_decision`
`confirmed`, `corrected_offset_seconds` and `confirmed_offset_seconds`. A cell confirmed with `confirmed_offset_seconds`
equal to its current offset takes effect as `gps_drift_validated` — the current offset when no correction is given,
else the correction; confirmed against another offset it is `stale_user_decision` and takes no effect; confirmed
naming none, a blocker. Until every cell has taken effect, photos-23 and photos-24 are not written; then resolved UTC
is computed again with the validated offsets, photos-21 left as it is. photos-22's `depends_on` holds photos-21's
SHA-256, `gpx_fingerprint`, `camera_time_policy_fingerprint` and `camera_group_key_version`.
:::


## 24. Every photo's own values

:::{bld} The pinned values follow a retaken fingerprint
:id: BLD-original_values_follow_fingerprint
:status: ruled
:realises: RUL-own_values_follow_new_fingerprint

`build_file_model` SHALL find a photo's pinned values under its fingerprint or, failing it, under the value it was
taken again from, step by step back through the `fingerprint_retaken` steps of prep's log (`retaken_fingerprints`),
when the handoff vouches for the log; execution then moves the pin to the current value, unless one is held there. A
log holding two steps that give one value two predecessors, or one value two successors, is a blocker of geotag's
preflight.
:::


## 25. Placing each photo

:::{bld} The placement order
:id: BLD-placement_order
:status: ruled
:realises: RUL-own_position_kept, RUL-placement_order
:aliases: geotag-fallback-rank-1, geotag-fallback-is-manual-1

`classify_gps` SHALL return, for each photo, the first of: `preserve_native` for a photo with its own position; its
review item's `manual_lat`/`manual_lon` as `manual_locked`; the tracks at its resolved time as `gpx_interpolation` or
`gpx_extrapolation`; its destination's effective fallback as `manual_fallback`; `no_change` for a photo marked
`accept_unlocated`; else `blocked`. A position from `manual_locked` or `manual_fallback` is written with that marker,
and undone like any manual position.
:::

:::{bld} The GPS decisions record
:id: BLD-gps_decisions_record
:status: ruled
:realises: RUL-placement_order, RUL-decision_fields_laid_out
:aliases: geotag-23-paths-only-review-1, geotag-24-rederive-auto-gps-1

Each destination's entry in `photos-23-gps-decisions.json` SHALL hold its `folder_fallback` cell and `gps_decisions`:
a `summary` counting `files_total`, `preserve_native_gps`, `automatic_gpx_interpolation`,
`automatic_gpx_extrapolation`, `automatic_folder_fallback`, `manual_locked`, `no_gps_change_needed`, `blocked` and
`manual_review_required`; an `automatic_decision_summary` naming the track files used; and `review_items` — one per
photo `blocked` (`no_reliable_gps_source`, requiring input), `manual_locked` or `no_change` (`accepted_unlocated`),
each with `manual_lat`, `manual_lon` and `accept_unlocated`. No other photo is named: the executable plan derives every
automatic position again from its own inputs.
:::

:::{bld} The folder-fallback cell
:id: BLD-folder_fallback_cell
:status: ruled
:realises: RUL-fallback_from_nearest, RUL-fallback_optional, RUL-other_proposals_need_acceptance

Destinations SHALL be built parent first; each one's `folder_fallback` proposes, as `inherited` with `inherited_from`,
the `effective_fallback` of its nearest ancestor that has one, else `manual_required`. Its `effective_fallback` is the
`fallback_lat`/`fallback_lon` written there, else the inherited proposal when `accept_proposal` is true, else none; an
accepted proposal that does not exist is `stale_user_decision`. Its `requires_user_input` is always false.
:::


## 27. Renames

:::{bld} How renames are planned
:id: BLD-rename_planning
:status: seed
:realises: RUL-suffix_no_clobber, RUL-uncorrected_keeps_its_name, RUL-geotag_name_final
:aliases: geotag-plan-renames-1, geotag-no-clobber-planning-1, geotag-case-insensitive-conflict-1, geotag-execute-no-new-rename-1

For each destination, `plan_renames` SHALL count every current name of its photos as taken, case folded, and never
freed by a rename it plans — two photos that would trade names both take a suffix — then, in path order, leave a photo
whose name already carries its timestamp, suffix and all, as it is, and give any other the first free name of its
timestamp by `allocate_suffix`, adding it to the names taken. Execution applies these renames and no other, each by a
no-clobber move.
:::
