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
:aliases: geotag-gpx-after-recognition-1

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
