# Shared — how this build does it

How this build meets [the shared intent](../intent/shared.md): the files, names, tools and steps. Each item `realises`
the intent it implements. *Why* a choice was made is in [the rationale](../rationale/shared.md).

## 0. The pipeline

:::{bld} The phases are three commands
:id: BLD-phase_commands
:status: seed
:realises: DEF-prep, DEF-geotag, DEF-merge

The phases SHALL be the commands `photos-cartographer prep`, `geotag` and `merge` — named in the specs, and in their
records, `photos-1-prep`, `photos-2-geotag` and `photos-3-merge`.
:::

## 1. One run at a time

:::{bld} The lock follows the workspace guard
:id: BLD-lock_after_guard
:status: seed
:realises: RUL-lock_before_reading

The lock SHALL be taken at process start, immediately after the workspace root is resolved and its sentinel,
`photos-00-workspace-guard`, is verified.
:::

:::{bld} The lock records its owner
:id: BLD-lock_owner_record
:status: seed
:realises: RUL-stale_lock_recovered

The lock SHALL record the identity of the process that owns it and the time it started, so that a lock whose owner is
gone can be told from one whose owner is running.
:::

:::{bld} The phases run inside the run's lock
:id: BLD-phases_inside_lock
:status: seed
:realises: RUL-lock_through_the_run

Each phase's `plan`, `dry-run` and `execute` SHALL run with the lock taken at start already held; none SHALL take it
again or scope it on its own (prep §14, geotag §29).
:::

## 2. A snapshot before changing, optionally

:::{bld} The snapshot is a ZFS snapshot, configured by the `zfs` block
:id: BLD-snapshot_is_zfs
:status: seed
:realises: RUL-snapshot_optional, RUL-snapshot_off_by_default, RUL-required_snapshot_or_nothing, RUL-snapshot_per_plan

The snapshot SHALL be a ZFS snapshot, configured by the `zfs` block of the workspace configuration,
`photos-00-config.json`; with no `zfs` block, or one not enabled, none is taken. Its name SHALL carry the plan id.
`snapshots_required` decides what a failed snapshot means: true, the run aborts before its first change; false, or the
block not configured, it proceeds without one.
:::

:::{bld} One snapshot mechanism for every phase
:id: BLD-one_snapshot_mechanism
:status: seed
:realises: RUL-snapshot_optional

The three phases SHALL take their snapshots through one mechanism — prep §14.3, geotag §29 and merge §10.3 invoke it,
and none redefines it.
:::

## 3. One configuration, kept in the workspace

:::{bld} The configuration is `photos-00-config.json`, in the control directory
:id: BLD-config_file
:status: seed
:realises: DEF-configuration, RUL-one_configuration, RUL-config_never_media

The configuration SHALL be the JSON file `photos-00-config.json` in the workspace's control directory, `.photos-ingest/`,
which prep skips wholesale (§5 of the shared contract) — never an in-code global.
:::

:::{bld} Prep seeds from a template a deployment may replace
:id: BLD-config_seed_template
:status: seed
:realises: RUL-config_seeded_once, RUL-config_authoritative

Prep SHALL seed the configuration from a default template. A deployment MAY supply its own seed defaults; how it does
so is the deployment's concern, not the specification's.
:::

:::{bld} `init-library` may write `library_root`
:id: BLD-init_library_writes_library_root
:status: seed
:realises: RUL-library_setup_writes_one_setting

The setup command `init-library` (merge §4), run inside a workspace with an explicit library path, MAY write the
`library_root` key into the configuration, and only that key. It is not part of merge's data path.
:::

:::{bld} Field-scoped fingerprints, and one whole-file SHA-256
:id: BLD-config_fingerprints
:status: seed
:realises: RUL-staleness_by_area, RUL-config_in_dependencies, RUL-organization_settings_restale

Two things SHALL be derived from the configuration: field-scoped fingerprints — the filename format, the camera-time and
timezone policy, the GPX thresholds, the camera-group-key version, the snapshot policy, the folder-name set, the
media-extension lists, and others — which drive staleness; and one SHA-256 of the whole file, for integrity and
provenance, recorded in the archival manifest. The folder-set and media-extension fingerprints SHALL be among the
dependencies of geotag's executable plan and of merge's plan.
:::

:::{bld} The whole-file hash is in the executable plan's dependencies
:id: BLD-whole_hash_in_the_plan
:status: seed
:realises: RUL-any_config_change_replans, RUL-costly_results_survive_unrelated_edits

The whole-file fingerprint SHALL be carried in the `depends_on` of geotag's executable plan (geotag §28, in the
flattened dependency set of geotag §5) and of merge's plan, `config_fingerprint`, and each SHALL be refused when it no
longer matches the file. The costly caches SHALL be keyed on their own areas instead: resolved UTC on the
time-policy subset (geotag §22.1), the renames on the filename-format fingerprint.
:::

:::{bld} Prep guards execution with the whole-file hash
:id: BLD-prep_guards_with_the_whole_hash
:status: seed
:realises: RUL-any_config_change_replans

Prep SHALL re-plan from the filesystem each run and guard execution with the whole-file hash; it SHALL keep no folder
or extension fingerprint of its own.
:::

:::{bld} The control directory is always `.photos-ingest/`
:id: BLD-control_directory_fixed
:status: seed
:realises: RUL-control_directory_fixed

The control directory SHALL be `.photos-ingest/` at the workspace root, in every workspace. No configuration key SHALL
name it.
:::

:::{bld} The configuration's keys
:id: BLD-config_keys
:status: seed
:realises: DEF-config_areas, RUL-folder_names_not_roles, RUL-camera_classes_not_derivation, RUL-extension_one_class

The areas SHALL be, at least: the `zfs` block and `snapshots_required` (§2 above);
`camera_time_and_timezone_policy.device_groups`, with `phones` and `fixed_clock_cameras` (shared §6); `filename_timestamp_format`
(shared §7); `gpx_root` and the GPX thresholds, such as `gpx_direct_match_max_seconds`, `gpx_interpolation_max_gap_seconds` and
`gpx_interpolation_max_distance_meters` (shared §8); the camera-time policy flags, such as `single_anchor_auto_apply` and
`multi_anchor_auto_apply` (geotag); `library_root` and merge's collision and placement policy (merge; shared §13.5); `folders`,
a role→name map of the numbered managed folders `0-sources`…`6-photos-by-dest` (shared §5, prep §3), whose code finds each
folder by its role; and `media_extensions`, mapping `image`, `raw` and `video` to lists of canonical extensions —
lowercase, no leading dot (prep §6.1). `CAMERA_GROUP_KEY_VERSION` SHALL be a code constant, never a configuration field.
:::

:::{bld} What validating the configuration checks
:id: BLD-config_values_checked
:status: seed
:realises: RUL-config_validated_before_use

Validating the configuration SHALL check, among others, that a path resolves sanely, that a ZFS snapshot prefix is a
syntactically valid snapshot component, and that an IANA timezone is a real zone.
:::
