# Geotag — how this build does it

How this build meets [geotag's intent](../intent/geotag.md) and the shared contract's geotag rules: the files, names,
tools and steps. Each item `realises` the intent it implements. *Why* a choice was made is in
[the rationale](../rationale/geotag.md).

## 1. Core workflow rule

:::{bld} Geotag's planning stages, in order
:id: BLD-geotag_stage_order
:status: ruled
:realises: RUL-time_before_gps, RUL-decision_stage_writes_record, RUL-no_record_before_decisions

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

## 2. Artifact dependencies

:::{bld} Geotag's dependencies, recorded and checked
:id: BLD-geotag_dependencies
:status: ruled
:realises: RUL-geotag_plan_carries_every_dependency, INV-no_stale_use, RUL-hash_is_the_dependency_check, RUL-handoff_verified_by_content

`photos-24-executable-plan.json` SHALL record in `depends_on` the SHA-256 of `photos-21`, `photos-22` and `photos-23`;
the handoff's `content_fingerprint`; `config_fingerprint`, `code_fingerprint`, `camera_group_fingerprint`,
`camera_group_key_version`, `gpx_fingerprint`, `metadata_field_set_version`, `filename_format_fingerprint`,
`folders_fingerprint` and `media_extensions_fingerprint`; `resolved_utc_cache_fingerprint` and
`prep_cache_fingerprint`; each photo's `media_preconditions`; and `planned_operation_fingerprint`. Execute recomputes
all but the two cache fingerprints — vouched for by the records and handoff they were derived from, checked where they
are made — before any change, and each photo's preconditions as it applies it. `photos-25-execution-summary.json` is
never checked as a dependency.
:::

## 4. Geotag scope

:::{bld} Geotag's file model
:id: BLD-geotag_file_model
:status: ruled
:realises: RUL-geotag_changes_only_by_dest

Geotag's `build_file_model` SHALL take, from the handoff, only the records whose `folder_class` is `6-photos-by-dest`
and whose `media_class` is `image` or `raw`; every operation of `photos-24-executable-plan.json` names one of them.
:::

## 6. Human decision field rule

:::{bld} The auto-apply settings
:id: BLD-auto_apply_settings
:status: ruled
:realises: RUL-anchor_offset_auto_as_configured, RUL-timezone_auto_resolves, RUL-proposals_need_acceptance

A GPX self-anchor offset SHALL be set as `effective_time_anchor` with `decision_mode: "auto_resolved"` when its
anchors do not conflict and `camera_time_and_timezone_policy.multi_anchor_auto_apply` holds for two or more anchors,
or `single_anchor_auto_apply` for one; a destination's `inherited` timezone proposal is set as its
`effective_iana_timezone` likewise, a `config_default` one never; a `recorded_offset` or `timezone_naive` offset proposal
and an `inherited` folder fallback become effective only with `accept_proposal: true`.
:::

:::{bld} How an offset is accepted
:id: BLD-offset_acceptance
:status: ruled
:realises: RUL-acceptance_holds_for_its_proposal, RUL-written_value_over_acceptance, RUL-proposals_need_acceptance

An offset cell's `user_decision` SHALL hold `accept_proposal`, `accepted_offset_seconds` — the `proposed_offset_seconds` that was accepted — and `manual_offset_seconds`. A `manual_offset_seconds` takes effect first. Else an acceptance takes effect while `accepted_offset_seconds` equals the offset now proposed, or lies within `gpx_anchor_decision_tolerance_seconds` of one proposed from GPS (the proposal carries that tolerance as `acceptance_tolerance_seconds`); and what takes effect is the offset accepted, not the one now proposed; naming another offset, or with nothing proposed, the cell is `stale_user_decision` and asks; naming none, or not a whole number, a blocker.
:::


## 7. Per-destination structure

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
:realises: RUL-offset_per_camera_destination_day, RUL-offset_from_own_evidence, RUL-answer_follows_its_day

Each destination's `camera_group_time_decisions` SHALL hold one cell per camera group present, keyed by its `camera_group_key`, or — when the group's photos there span more than one naive date — one per date, keyed `<camera_group_key>@<YYYY-MM-DD>` with a `date` field, the date taken from `source_naive_time`; every cell names the day its photos are of in `day`, whatever its key. A cell's earlier answer is the cell under its key when that names the same `day`, else the one under the key's other form whose `day` is the same; a drift cell's likewise. A cell's proposal is the GPX self-anchor of that group's native-GPS frames of that date there; else the offset shared from the same day elsewhere ({need}`BLD-offset_shared_within_day`); else `recorded_offset` ({need}`BLD-recorded_offset_proposal`); else, with the destination's timezone resolved, `timezone_naive` at the cell's earliest naive time, DST-aware; else `manual_required`. A cell with photos not yet corrected names the earliest of them in `representative` (`source_file`, `camera_source_naive_time`). No cell reads the destination above it for an offset; the one case of a cell taking another destination's is {need}`BLD-offset_shared_within_day`.
:::

:::{bld} Geotag's records are grouped by destination
:id: BLD-geotag_records_by_destination
:status: ruled
:realises: RUL-decision_fields_laid_out

`photos-21`, `photos-22`, `photos-23` and `photos-24` SHALL each hold a `destinations` object keyed by the
destination's path under `6-photos-by-dest`, every decision of a destination inside its entry.
:::


## 8. Reading the tracks

:::{bld} How track points are read
:id: BLD-track_points
:status: ruled
:realises: RUL-track_time_never_guessed, RUL-unreadable_point_reported, RUL-track_is_one_trk, RUL-unreadable_tracks_stop_geotag

Geotag SHALL read every `<trkpt>` of each `*.gpx` file under `gpx_root`, its `<time>` as an `xsd:dateTime` — fractional
seconds optional, the zone `Z` or a numeric offset — normalised to UTC; a point lacking `lat` or `lon`, with one out of
range or not a number, lacking a `<time>`, or with a time unparseable or naive is skipped with a warning naming the
file and the point's index, as is a file that cannot be read or parsed. `geotag plan` prints the count of warnings and
the first `GPX_WARNINGS_SHOWN`, with the number of the rest. A point keeps the index of its `<trk>` and of its `<trkseg>`: the points of one `<trk>` of one file are one track. A file that cannot be opened, or is not well-formed, is unreadable; a folder holding track files all of them unreadable stops the plan, each named with why, and a linked folder under `gpx_root` is named in a warning and not followed.
:::

:::{bld} Tracks kept apart, and a root that is not there
:id: BLD-gpx_root_missing
:status: ruled
:realises: RUL-missing_tracks_stop_geotag, RUL-no_tracks_no_stop, RUL-tracks_never_joined

`geotag plan` SHALL stop before its first record, exit 2, when `gpx_root` is set and is not a directory; an empty `gpx_root`, or one holding no track, plans without tracks. The index keeps each file's points as a track of its own (`GPXIndex.tracks()`) and its SHA-256 (`file_sha`); placement and anchoring read the tracks one by one.
:::

:::{bld} How tracks are ranked
:id: BLD-track_precedence
:status: ruled
:realises: RUL-tracks_ranked_by_folder, RUL-ranked_folder_missing_told, RUL-track_ranking_in_dependencies

`gpx_track_precedence` SHALL be a list of folder names directly under `gpx_root`, best first, each once, a single path component not starting with `.` — else the configuration is refused; empty, every track ranks alike. `GPXIndex.rank` gives a track file the place of the first folder of its path under `gpx_root` in that list, and a file in no listed folder the list's length. A listed folder that is not a directory under `gpx_root`, or is a link, is the index's first warning. The list, as JSON, enters the tracks' `fingerprint`.
:::


## 9. Camera groups

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

:::{bld} A group in both lists
:id: BLD-group_in_both_lists
:status: ruled
:realises: RUL-group_classed_twice_is_unknown

A `camera_group_key` listed in both `phones` and `fixed_clock_cameras` SHALL be classed `unknown`.
:::

:::{bld} Photos timed by their modification
:id: BLD-modified_time_files
:status: ruled
:realises: RUL-modified_time_solved_alone, RUL-modified_time_no_camera_offset, RUL-modified_time_opens_no_day

`build_file_model` SHALL give a photo whose `source_time_tag` names `ModifyDate` — the pinned one, for a photo with
pinned values — the `camera_group_key` `NO_IDENTITY_KEY` in place of prep's, so that, as {need}`BLD-unidentified_files`
has it, it is classed `unidentified`, is in no group's offset cell or drift check, and is resolved by `OffsetTime`
(`unidentified_native_offset`), else its destination's timezone; prep's camera group and its report are left as derived.
:::


## 10. Destination civil timezone

:::{bld} The timezone cell
:id: BLD-timezone_cell
:status: ruled
:realises: RUL-timezone_from_nearest, RUL-timezone_auto_resolves, RUL-default_zone_proposed_only, RUL-inherited_timezone_yields_to_photos, RUL-destination_has_one_timezone, RUL-zone_against_photos_needs_word

Each destination's `destination_timezone` in `photos-21-time-decisions.json` SHALL hold `proposed_iana_timezone` with
its `proposal_source` — `inherited`, naming the ancestor in `inherited_from`, or `config_default`, or `none` —
`user_decision.manual_iana_timezone`, `effective_iana_timezone`, `requires_user_input`, `stale_user_decision` and, when
the proposal took effect without the user, `decision_mode: "auto_resolved"`. Destinations are built parent first, so
each takes the `effective_iana_timezone` of its nearest ancestor that has one; one with none is offered
`default_folder_timezone`, as `config_default`, which takes effect only once written as its `manual_iana_timezone`. Where a photo of the destination that is no camera's, not yet corrected, records with its time an offset that is not the zone's — the one written, else the one inherited — at that time, the zone does not take effect: the cell asks, holding `contradicted_by` — `photos`, an `example`, `recorded_offset_seconds`, `recorded_offsets` (each distinct one), `timezone` and `timezone_offset_seconds` — and a destination within it inherits nothing through it, until another zone is written that the photos agree with or `user_decision.confirmed_despite_recorded_offsets` lists every one of `recorded_offsets`; then the zone takes effect, `contradicted_by` kept with `confirmed: true`. A list that does not cover them is `stale_user_decision`, kept as written; one that is not a list of whole seconds, a blocker.
:::


## 11. Clock offsets from the camera's own GPS

:::{bld} How anchors are matched and agreed
:id: BLD-anchor_matching
:status: ruled
:realises: RUL-anchor_within_clock_error, RUL-lower_track_anchors_where_higher_absent, RUL-anchor_consensus, RUL-revisit_matched_to_its_day, RUL-indistinct_visits_wait, RUL-chosen_group_is_anchored, RUL-anchor_offset_auto_as_configured, RUL-stay_fixes_no_clock, RUL-anchor_proposal_carries_evidence, RUL-tracks_never_joined

For each native-GPS photo of a (camera group, destination, day) bucket, `frame_candidates` SHALL take, track by track, every point within `gpx_anchor_max_point_distance_meters` of it and every segment — two consecutive points of that track at most `gpx_anchor_max_segment_gap_seconds` apart — within `gpx_anchor_max_segment_distance_meters`, each at a time within `gpx_anchor_max_clock_error_seconds` of the photo's camera time read as UTC; a pass is an unbroken run of them along the track, passes of one track closer in time than `gpx_anchor_same_pass_max_seconds` being one; and keep each pass's best, a point before a segment, then the closest — dropped where a track of a better rank places a photo at its time by a point or between two (`BLD-track_placement`) — with `time_span_seconds` — the time from the first to the last match of the pass no farther than the best by `gpx_anchor_stay_distance_meters`. A candidate whose span exceeds `gpx_anchor_stay_max_seconds` agrees with any offset within that span, and the spread, of its own, and ranks after every other. `infer_anchor_proposal` clusters the candidates' offsets within the spread, `gpx_anchor_offset_spread_max_seconds`, and proposes the cluster the most photos support, a tie going to the smaller offset, its best-ranked candidate the representative; its confidence is `review_required` when a photo supports no pass of it, another cluster ties (`tied`), or its representative's span exceeds `gpx_anchor_stay_max_seconds` (`imprecise_seconds`), else `high` when another photo supports it or it is a point match, else `medium`. Only an agreed offset — no conflicting photo, no tie, not imprecise — applies itself, under `multi_anchor_auto_apply` or `single_anchor_auto_apply`; an imprecise one, accepted, takes effect as `gpx_anchor_imprecise`. The proposal names the photos no pass of which agrees (`conflicting_files`), and each cluster in `groups` with its photo count and a representative, its track file included; a `manual_offset_seconds` within the spread of a group's offset of a proposal that is not imprecise takes effect as `gpx_anchor_chosen`, which no drift check follows.
:::

:::{bld} The country a destination is in
:id: BLD-country_choice
:status: ruled
:realises: RUL-country_gives_its_timezone, RUL-country_chosen_once

A destination's `destination_timezone.user_decision.country` — the country it is in — SHALL hold an ISO 3166 code of `country_table` — every country of the zone database's `zone.tab`, named from `iso3166.tab`, with its timezones — or be empty; another value, or any where the host's database has no such table, is a blocker. The topmost country chosen above or at a destination is in effect there, recorded as `country`, with `country_from` where it was chosen above and `country_zones`. One chosen within it is written back empty, the cell holding `country_removed` (`country`, `because`, `country_there`) for that run, and `geotag plan` warns of each. A country of one timezone proposes it as `proposal_source: "country"`, taking effect like an inherited zone, over any zone from above. A country of several gives its own destination's zone to nothing within it and lets none through from above; within it a `manual_iana_timezone` that is none of `country_zones` is a blocker, and the configured default is proposed only where it is one. `photos-21-time-decisions.json` holds the table read as `countries`.
:::

:::{bld} The offset derived from the timezone
:id: BLD-timezone_naive_offset
:status: ruled
:realises: RUL-offset_from_own_evidence, RUL-proposals_need_acceptance, RUL-timezone_offset_asked_once, RUL-ambiguous_local_time_never_guessed

A bucket with no anchor and a destination timezone SHALL be proposed the offset −(the timezone's UTC offset at the
bucket's earliest camera time), daylight saving included, as `proposal_source: "timezone_naive"` with
`proposed_offset_seconds`, `proposed_real_utc` and `proposed_from_timezone`. Where track points lie within
`drift_check_track_window_seconds` of the bucket's photos — by the times the offset gives, else by the times the camera
recorded — and no decision is given, it takes effect as `timezone_unconfirmed`, `decision_mode:
"to_be_confirmed_against_tracks"`, asking nothing in photos-21 and always asked in photos-22; elsewhere it takes effect
only once accepted, as `timezone_accepted`. A camera time the zone skips or repeats gives no offset: the cell asks for one, its proposal carrying `timezone_ambiguous` — the time, the zone, which case, and the two offsets.
:::

:::{bld} The offset the photos record
:id: BLD-recorded_offset_proposal
:status: ruled
:realises: RUL-recorded_offset_proposed, RUL-differing_recorded_offsets_propose_none, RUL-offset_from_own_evidence, RUL-proposals_need_acceptance, RUL-timezone_offset_asked_once, RUL-track_confirmation_is_acceptance

A camera group's bucket with no anchor and no offset shared from the same day elsewhere, whose photos not yet corrected record at least one offset with their times — each read as `_own_offset` reads it, the offset recorded with the field its time was read from, a value that is no offset being none — and all the same one, SHALL be proposed −(that offset) as `proposal_source: "recorded_offset"`, ahead of `timezone_naive`, with `proposed_offset_seconds`, `recorded_offset_seconds`, `recorded_by` (how many photos record it), an `example` of them and `proposed_real_utc` at the bucket's earliest camera time. It takes effect as a `timezone_naive` proposal does ({need}`BLD-timezone_naive_offset`): as `recorded_offset_unconfirmed`, `decision_mode: "to_be_confirmed_against_tracks"`, where track points lie by its photos and no decision is given, else only once accepted, as `recorded_offset_accepted`. Photos recording more than one offset give no such proposal; the cell holds `recorded_offsets_differ`, each offset recorded with how many photos record it and an `example`.
:::

:::{bld} A guessed offset far from all evidence
:id: BLD-offset_far_from_evidence
:status: ruled
:realises: RUL-offset_far_from_evidence_asks

After the offsets shared within a day, `build_time_decisions` SHALL withdraw the effective offset of a cell whose proposal is `recorded_offset` or `timezone_naive` and whose effective source is that proposal's (`recorded_offset_unconfirmed`, `recorded_offset_accepted`, `timezone_unconfirmed` or `timezone_accepted`), the cell asking, where the destination holds a photo of another camera group whose resolved UTC is known — a smartphone's, resolved as `compute_resolved_utc` resolves it, or a camera's not yet corrected whose cell's effective source is `gpx_anchor_auto`, `gpx_anchor_accepted`, `gpx_anchor_chosen`, `gpx_anchor_imprecise`, `same_day_auto`, `same_day_accepted` or `manual` — and every photo of the cell not yet corrected, at the time the proposal gives, lies farther than `gpx_anchor_max_clock_error_seconds` from each such photo's resolved UTC and from every track point. Such a proposal, whatever the cell's decision, holds `far_from_evidence`: `max_clock_error_seconds`, `other_photos` (how many), `nearest_other_photo`, `nearest_other_photo_seconds` and `nearest_track_seconds` (empty with no track).
:::

:::{bld} A day's offset shared between destinations
:id: BLD-offset_shared_within_day
:status: ruled
:realises: RUL-offset_shared_within_day, RUL-same_day_offsets_agree, RUL-offset_from_own_evidence

Over the cells of one camera group naming the same `day` in different destinations, `build_time_decisions` SHALL take as donors those whose effective source is `gpx_anchor_auto`, `gpx_anchor_accepted` or `gpx_anchor_chosen` and whose `manual_offset_seconds` is empty. Donors whose offsets differ by more than `clock_offset_same_day_max_difference_seconds` each lose their effective offset, ask, and list the others in `conflicts_with` (`destination`, `bucket`, `offset_seconds`); nothing is shared. Otherwise a cell whose own proposal would be `recorded_offset`, `timezone_naive` or `manual_required` is proposed the donor's offset — a `gpx_anchor_auto` donor first, then by path — as `proposal_source: "same_day_elsewhere"` with `shared_from` (`destination`, `bucket`): taking effect as `same_day_auto` where the donor's source is `gpx_anchor_auto`, else once accepted, naming the offset, as `same_day_accepted`. An offset the cell keeps from its own earlier GPS comes first. Neither source is followed by a drift check.
:::

## 12. The decision records

:::{bld} What every decision record carries
:id: BLD-decision_record_envelope
:status: ruled
:realises: RUL-decision_stage_writes_record, INV-no_stale_use

`photos-21-time-decisions.json`, `photos-22-gps-drift-validation.json` and `photos-23-gps-decisions.json` SHALL each
carry `artifact_type`, `artifact_name`, `status` — `requires_user_input` or `complete` — `requires_user_input`, true
when any of its cells needs the user, `executable: false`, `depends_on`, and, when complete, `decision_mode`:
`no_op_or_auto_resolved` for photos-21 and photos-23, `no_op_or_confirmed` for photos-22. The `depends_on` of photos-21
holds the handoff's content fingerprint, `camera_time_policy_fingerprint` — over the whole
`camera_time_and_timezone_policy`, the camera groups' classes included — `gpx_fingerprint` and
`camera_group_key_version`.
:::


## 13. Resolved UTC

:::{bld} How each photo's true time is resolved
:id: BLD-resolved_utc
:status: ruled
:realises: RUL-phone_time_from_own_offset, RUL-offset_within_time_value, RUL-offset_per_camera_destination_day, RUL-time_before_gps, RUL-ambiguous_local_time_never_guessed

`compute_resolved_utc` SHALL resolve each photo of photos by destination to UTC: a camera's photo by the offset of its
cell — `<group>@<date>` where the destination has one for its date, else `<group>` — a corrected offset from
`photos-22-gps-drift-validation.json` taking its place (`camera_group_offset`); a phone's by the offset recorded with
its time — one written within the time's own value, after the seconds and any fraction of them, else its field's:
`OffsetTimeOriginal` for `DateTimeOriginal`, `OffsetTimeDigitized` for `CreateDate`, `OffsetTime`
for `ModifyDate` (`smartphone_native_offset`) — else its destination's timezone (`destination_timezone`); and a time
geotag already corrected by its own offset, else the timezone (`geotag_corrected`); every other photo `unresolved` —
one whose time its offset carries past the calendar's first or last year as `time_out_of_range`. An offset is `Z`, or a
sign, two digits of hours up to 14 and two of minutes up to 59, with or without a colon between; anything else is none.
`geotag plan` writes the rows — `relative_path`, `destination_path`, `destination_timezone`, `camera_group`,
`time_decision_scope` (the cell, `<group>[@<date>]|<destination>`), `source_naive_time`, `source_time_provenance`,
`time_rule_used`, `utc_offset_used`, `resolved_utc`, `resolved_utc_status`, `resolved_utc_provenance` — into the
`resolved_utc_cache` table once photos-22 is complete, replacing the table whole. A time that must be read by the zone and which the zone skips or repeats is left unresolved — rule `local_time_skipped` or `local_time_repeated` — and `geotag plan` stops on it, naming the photo, the time, the zone and both readings.
:::

:::{bld} The resolved-UTC fingerprint
:id: BLD-resolved_utc_fingerprint
:status: ruled
:realises: INV-no_stale_use, RUL-staleness_by_area, RUL-tracks_in_dependencies

`resolved_utc_cache_fingerprint` SHALL be the SHA-256 over the rows ordered by path — each its `relative_path`,
`resolved_utc`, `resolved_utc_status`, `time_rule_used`, `utc_offset_used` and `source_time_provenance` as text — and
the inputs, sorted by name: `camera_time_policy_fingerprint`, `camera_group_key_version`, the SHA-256 of photos-21 and
of photos-22, `prep_cache_fingerprint`, `metadata_field_set_version` and `gpx_fingerprint`, the last whether or not a
track decided anything.
:::


## 14. The GPS-drift check

:::{bld} The drift check
:id: BLD-drift_validation
:status: ruled
:realises: RUL-unanchored_offset_confirmed, RUL-confirmation_holds_for_its_offset, RUL-stay_fixes_no_clock

Once photos-21 is complete, `geotag plan` SHALL write `photos-22-gps-drift-validation.json` with a cell for each offset cell whose effective source is `timezone_accepted`, `timezone_unconfirmed`, `recorded_offset_accepted`, `recorded_offset_unconfirmed`, `manual` or `gpx_anchor_imprecise` and whose photos' resolved times lie within `drift_check_track_window_seconds` of track points, or, none lying there, whose photos' recorded times read as UTC do — whether or not a photo of the cell anchors on the tracks: its `proposal` holding `current_offset_seconds`, its source, the photos and that track segment; its `user_decision` `confirmed`, `corrected_offset_seconds` and `confirmed_offset_seconds`. A cell confirmed with `confirmed_offset_seconds` equal to its current offset takes effect as `gps_drift_validated` — the current offset when no correction is given, else the correction; confirmed against another offset it is `stale_user_decision` and takes no effect; confirmed naming none, a blocker. Until every cell has taken effect, photos-23 and photos-24 are not written; then resolved UTC is computed again with the validated offsets, photos-21 left as it is. photos-22's `depends_on` holds photos-21's SHA-256, `gpx_fingerprint`, `camera_time_policy_fingerprint` and `camera_group_key_version`. A `timezone_unconfirmed` or `recorded_offset_unconfirmed` cell is always given its drift cell, whatever track lies by it.
:::

:::{bld} A drift confirmation names its tracks
:id: BLD-drift_confirmation_tracks
:status: ruled
:realises: RUL-confirmation_rests_on_its_tracks, RUL-changed_tracks_asked_again, RUL-trackless_confirmation_holds_while_none, RUL-stale_confirmation_kept

A drift cell's `proposal` SHALL hold `tracks`, each track file its `track_segment` is drawn from with its SHA-256, by name, and the editor writes them with a confirmation as its `user_decision`'s `confirmed_against_tracks`. A confirmation takes effect only while every track it names is under `gpx_root` with the SHA-256 it names — naming none, only while `tracks` is empty; else the cell is `stale_user_decision`, its `user_decision` kept as written and taking no effect, and its `confirmed_tracks_changed` names the tracks no longer there with the SHA-256 named. Confirmed without a list of tracks, each a `gpx_file` and a `sha256`, a blocker.
:::


## 15. Every photo's own values

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


## 16. Placing each photo

:::{bld} The placement order
:id: BLD-placement_order
:status: ruled
:realises: RUL-own_position_kept, RUL-placement_order

`classify_gps` SHALL return, for each photo, the first of: `preserve_native` for a photo with its own position; its
review item's `manual_lat`/`manual_lon` as `manual_locked`; the tracks at its resolved time as `gpx_interpolation` or
`gpx_extrapolation`; its destination's effective fallback as `manual_fallback`; `no_change` for a photo marked
`accept_unlocated`; else `blocked`. A position from `manual_locked` or `manual_fallback` is written with that marker,
and undone like any manual position.
:::

:::{bld} One test of a photo's own position
:id: BLD-own_position_test
:status: ruled
:realises: RUL-null_island_is_no_position

A photo SHALL have a position of its own exactly when `photos_utils.has_own_position` holds of its `GPSLatitude` and
`GPSLongitude` as `exiftool -n` reads them: both present, and not both equal to 0 as numbers — `0`, `0.0` and `-0.0`,
never a value merely near it. Prep's `has_native_gps`, and geotag's file model — from the handoff's values and from the
pinned ones — take it from that test alone, so a photo at latitude 0 and longitude 0 is placed again, never
`preserve_native`, never an anchor frame and never counted in `preserve_native_gps`.
:::

:::{bld} The GPS decisions record
:id: BLD-gps_decisions_record
:status: ruled
:realises: RUL-placement_order, RUL-decision_fields_laid_out

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
:realises: RUL-fallback_from_nearest, RUL-fallback_optional, RUL-proposals_need_acceptance, RUL-accepted_fallback_follows

Destinations SHALL be built parent first; each one's `folder_fallback` proposes, as `inherited` with `inherited_from`,
the `effective_fallback` of its nearest ancestor that has one, else `manual_required`. Its `effective_fallback` is the
`fallback_lat`/`fallback_lon` written there, else the inherited proposal when `accept_proposal` is true, else none; an
accepted proposal that does not exist is `stale_user_decision`. Its `requires_user_input` is always false.
:::

:::{bld} How a track places a photo
:id: BLD-track_placement
:status: ruled
:realises: RUL-track_placement_bounded, RUL-track_evidence_order, RUL-tracks_never_joined, RUL-disagreeing_tracks_place_nothing, RUL-track_break_never_bridged, RUL-highest_ranked_track_places

`place_gps` SHALL place a photo on each track by itself, taking the first of: the nearer in time of the two points around its resolved time, within `gpx_direct_match_max_seconds` (`direct_match`); the place between those two, linear in time and the short way round in longitude, when they are at most `gpx_interpolation_max_gap_seconds`, `gpx_interpolation_max_distance_meters` and `gpx_interpolation_max_speed_kmh` apart (`interpolated`); past the nearer point when it is within `gpx_extrapolation_max_seconds` and is an end — the track's first or last point, or a side of a gap longer than `gpx_interpolation_max_gap_seconds` (`extrapolated`). The projection follows the heading from the farthest point of the track within `gpx_extrapolation_heading_seconds` of the end, and falls back to the end itself when it lands farther than `gpx_extrapolation_max_distance_meters` from it or the heading is faster than `gpx_extrapolation_max_speed_kmh`. Of the tracks that place the photo, those placing it by a point or between two count, and only where there is none the projections; of those, the tracks of the best rank (`BLD-track_precedence`), of which the best wins — by method in that order, then the nearest in time, then the file name; but when another of that rank lies more than `gpx_tracks_agree_max_distance_meters` from it, none places the photo, the reason `tracks_disagree` naming both files. Each counted track of a lower rank is kept with the placement in `lower_tracks`: its file — with the track's number where the file gives two — and `apart_meters` from the position. Two points either side of a `<trkseg>` break are never interpolated between — each is an end of its segment, the reason `track_gap` carrying `segment_break` — and a heading is taken from the end's own segment; two disagreeing tracks of one file are named by the file and the track's number.
:::

:::{bld} A review item is its photo's
:id: BLD-review_item_identity
:status: ruled
:realises: RUL-photo_decision_follows_the_photo, RUL-unplaced_photo_listed, RUL-disagreeing_tracks_place_nothing, RUL-moved_photo_position_decided_anew

Each of photos-23's `review_items` SHALL carry its photo's `content_fingerprint`, and a photo's earlier decision is the item, among its own destination's earlier `review_items` alone, with its fingerprint, or with the fingerprint its own values are pinned under, else — for an item carrying none — the item at its path. An item of a photo the tracks did not place carries `tracks`: the `reason` (`no_tracks`, `outside_track`, `track_gap`, `track_jump`, `tracks_disagree`) with `seconds_from_track`, `gap_seconds`, `jump_meters` or the `gpx_files` and `apart_meters` that go with it. The record's `track_disagreements` lists each pair of tracks that placed photos apart and how many, which `geotag plan` also warns of.
:::

:::{bld} What a lower-ranked track said
:id: BLD-lower_tracks_recorded
:status: ruled
:realises: RUL-lower_track_distance_recorded, RUL-lower_track_disagreements_told

A position write of photos-24 whose placement has `lower_tracks` SHALL carry them in its `provenance`, beside `gpx_file`. photos-23's `lower_track_disagreements` lists, per lower-ranked track (`gpx_file`) and the track that placed the photos (`outranked_by`), the photos it put more than `gpx_tracks_agree_max_distance_meters` from their position, which `geotag plan` prints; nothing in it asks.
:::


## 18. Renames

:::{bld} How renames are planned
:id: BLD-rename_planning
:status: ruled
:realises: RUL-suffix_no_clobber, RUL-uncorrected_keeps_its_name, RUL-geotag_name_final

For each destination, `plan_renames` SHALL count every current name of its photos as taken, case folded, and never
freed by a rename it plans — two photos that would trade names both take a suffix — then, in path order, leave a photo
whose name already carries its timestamp, suffix and all, as it is, and give any other the first free name of its
timestamp by `allocate_suffix`, adding it to the names taken. Execution applies these renames and no other, each by a
no-clobber move.
:::


## 19. The executable plan

:::{bld} The executable plan
:id: BLD-executable_plan
:status: ruled
:realises: RUL-time_before_gps, RUL-execution_only_the_plan, RUL-mutate_on_difference, RUL-no_plan_while_a_decision_waits, RUL-plan_counts_placement, RUL-placement_recorded_with_its_track, RUL-corrected_time_written_local

`photos-24-executable-plan.json` SHALL hold `status` — `ready`, or `blocked` with the plan's `blockers`, which `geotag plan` prints, exiting 2 — `executable`, `depends_on`, `plan_id` (the first 16 hex digits of the SHA-256 of `depends_on`), `placement` — its photos counted as `native`, `matched`, `interpolated`, `extrapolated`, `manual_locked`, `manual_fallback` or `unlocated` — and per destination its `operations`, `no_ops` (the photos it holds already as planned), `left_unlocated` (each photo marked `accept_unlocated`, with the decision) and a `summary`. An operation is `metadata_time_write`, carrying the resolved time, its rule, offset and timezone, and the decision it followed; `metadata_gps_write`, its origin `apply_manual` — with the decision and the position it replaces — or `recompute_automated`, with the track file that placed it and the resolved time it was placed at; `gps_marker_write`, one that clears geotag's position carrying the position it removes; or `rename_no_clobber`. A write the photo already holds is not planned. A time is written as `DateTimeOriginal` with `OffsetTimeOriginal` as a sign, hours and minutes — an offset with seconds, as a zone's before it kept standard time, to the nearest minute — and its operation carries in `pre_state` the value each field it writes held and in `provenance` the field its time was read from.
:::

:::{bld} The other time fields are written with the time
:id: BLD-other_time_fields_written
:status: ruled
:realises: RUL-other_capture_times_corrected
:uses: BLD-executable_plan, BLD-other_time_fields_read

A time write SHALL carry as well, of the fields the photo holds, `EXIF:CreateDate` as `DateTimeOriginal` is written,
with `EXIF:OffsetTimeDigitized` as `OffsetTimeOriginal` when the photo holds it too; `XMP:DateCreated` as the local time
followed by any fraction of a second its value held and the offset, `YYYY:MM:DD HH:MM:SS[.ff]+HH:MM` as `exiftool -n`
takes it; `IPTC:DateCreated` as the local date, `YYYY:MM:DD`; and `IPTC:TimeCreated` as the local time and offset,
`HH:MM:SS+HH:MM` — never a field the photo does not hold. `ModifyDate` and `OffsetTime`, the last edit's, and the
sub-second fields are left as they are, a clock offset being whole seconds.
:::

:::{bld} Position tags
:id: BLD-position_tags
:status: ruled
:realises: RUL-position_written_whole

Every position geotag writes SHALL carry, in the same operation, `GPSLatitude`, `GPSLatitudeRef` (`N` or `S` by the
sign), `GPSLongitude` and `GPSLongitudeRef` (`E` or `W`); clearing one empties all four.
:::

:::{bld} A day's offset kept
:id: BLD-day_offset_kept
:status: ruled
:realises: RUL-day_offset_kept_for_later_photos, RUL-kept_offset_rests_on_its_tracks

A cell's dates SHALL be counted over all its group's photos in the destination, corrected ones included. A cell whose offset applied itself from the camera's own GPS (`gpx_anchor_auto`) records in `anchored_by` the track files of the anchors that agree with it, each with its SHA-256. A cell that would ask, its decision not given, takes the previous run's effective offset when that was `gpx_anchor_auto`, every file in its `anchored_by` is under `gpx_root` with that SHA-256, and no GPS proposal now made for it conflicts, ties, is imprecise or lies beyond `gpx_anchor_decision_tolerance_seconds` of it — as `decision_mode: "kept_from_earlier"`, `anchored_by` carried on; a cell whose photos are all corrected keeps its decision and its drift confirmation, the effective values derived again each run.
:::


## 20. Execution

:::{bld} How execution applies the plan
:id: BLD-geotag_execution
:status: ruled
:realises: RUL-geotag_execution_resumable, RUL-content_changed_write_held, RUL-execution_only_the_plan, RUL-every_change_journaled, RUL-one_photo_failure_contained, RUL-applied_unrecorded_is_recorded, RUL-engine_checked_before_writes

`geotag execute` SHALL, under the workspace lock: revalidate every dependency of photos-24 — and, when it holds an operation, that the image engine is the handoff's `depends_on.cache.image_engine_version` — and stop before any change if one moved; keep photos-21, -22 and -23 in `executed/<plan id>/`; take the snapshot labelled `geotag`, a required one that fails ending the run as `rejected`; pin and move the own values, single-threaded; then, per photo and under `-j`, skip one whose operations the journal confirms; take one gone from its path with its rename target in place as applied before — its operations recorded, not redone — once the target has the planned fingerprint (or the accepted one) and holds the planned tags, else block; and for one whose size or modification time changed since the plan block if its decoded content differs and is not accepted, else read its tags back — holding the planned values it is counted applied, otherwise, or with only a rename planned, it blocks as edited since the plan. Otherwise it writes the photo's tags in one `exiftool` call ({need}`BLD-metadata_safe_write`), retakes its fingerprint — a changed one, not accepted, or one that cannot be taken, a mismatch that holds the photo's writes and rename back — and renames it, the target checked free. Anything a photo's application raises is that photo's failure and blocker. The results merge in path order into the journal, kept per plan id — each confirmed photo's final path, size and modification time under `media_after` — and photos-25.
:::

:::{bld} The execution summary
:id: BLD-execution_summary
:status: ruled
:realises: RUL-content_changed_write_held, RUL-failure_recorded, RUL-content_acceptance_is_of_that_content

`photos-25-execution-summary.json` SHALL record the plan and execution ids, the SHA-256 of photos-24 and the dependencies it was validated against, counts per destination and in total, what was newly applied and what found satisfied, failures and blockers, `fingerprint_mismatches` — each with its expected and actual fingerprint and `user_decision.accept_fingerprint_change`, the one field a later execution reads — the snapshot, and run metadata apart; its `status` is `success`, `partial` (anything outstanding, a mismatch always), `failed` (nothing applied) or `rejected` (stopped before any change). An acceptance is read only from the summary of the same `plan_id` and holds for the `actual_fingerprint` it stands beside; a mismatch whose photo a later run of that plan finds still blocked is carried into the new summary as written. It is never a dependency.
:::


## 21. Finalize

:::{bld} What finalize checks first
:id: BLD-finalize_preconditions
:status: ruled
:realises: RUL-finalize_requires_success, RUL-finalize_checks_photos, RUL-finalize_reports_placement, RUL-unlocated_logged, RUL-placement_recorded_with_its_track

`geotag finalize` SHALL refuse, writing nothing, unless `photos-24-executable-plan.json` is `ready`, `photos-25-execution-summary.json` is `success` for the same `plan_id`, every dependency of the plan but the handoff still holds — the handoff left out because prep, run after execute, records geotag's own writes and renames in it — and every photo under `6-photos-by-dest` is one of the plan's, at its final path, with the size and modification time the journal's `media_after` records for it, or the plan's `media_preconditions` for a photo the plan had nothing to do to. It prints the plan's `placement` and writes it into the archive manifest; the log gives each photo in `left_unlocated` a `left_unlocated` step citing its decision, and each position from the tracks its `gpx_file` and `at_utc`.
:::
