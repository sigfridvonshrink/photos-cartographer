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

`geotag plan` SHALL write `photos-21-time-decisions.json`; only once it is complete resolve each photo's true time and
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
