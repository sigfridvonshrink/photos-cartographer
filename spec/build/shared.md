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

## 4. The control records, apart from the media

:::{bld} The control directory's contents
:id: BLD-control_directory_contents
:status: seed
:realises: DEF-control_records, RUL-control_records_together

The control records SHALL be these files in `.photos-ingest/` (shared §13 for the archival and database ones):

```text
.photos-ingest/
  photos-00-config.json            workspace configuration (seeded by prep, Section 4)
  photos-00-workspace-guard        workspace root sentinel: marks the workspace as INITIALIZED (written last by prep on init, prep photos-1-prep-workflow.md Section 3.1)
  photos-00-sealed.json            terminal/sealed marker, written by a successful merge ALONGSIDE the guard (a separate file, not a field inside the guard) — its presence seals the workspace (Section 13.7)
  photos-00-ingest.db              SQLite identity/metadata cache + derived caches (live working DB, Section 13.4)
  photos-00-plan-memo.db           prep-phase scratch: plan-time decode memo (disposable, NOT part of the record, prep photos-1-prep-workflow.md Section 10.3)
  photos-15-prep-ingest.db         prep-phase artifact: DB backup snapshot, end of prep (Section 13.4a)
  journal-*.json                   execution journals
  photos-10-prep-plan.json         prep-phase artifact: prep plan (written by `plan`, consumed by `dry-run`/`execute`; see "Canonical plan persistence" below)
  photos-11-handoff.json           prep-phase artifact: handoff manifest
  photos-15-prep-log.json          prep-phase artifact: end-of-prep audit log (Section 13.3 / prep 16.1)
  photos-21-time-decisions.json    geotag-phase artifact
  photos-22-gps-drift-validation.json  geotag-phase artifact: GPS-drift validation gate (§22a)
  photos-23-gps-decisions.json     geotag-phase artifact
  photos-24-executable-plan.json   geotag-phase artifact
  photos-25-execution-summary.json geotag-phase artifact
  photos-26-complete-log.json      geotag-phase artifact: full transformation log (prep+geotag, at finalize, Section 13.3)
  photos-26-geotag-ingest.db       geotag-phase artifact: DB backup snapshot, end of geotag (Section 13.4a)
  photos-26-archive-manifest.json  geotag-phase artifact: the archival package's manifest, at finalize (Section 13.2)
  photos-30-merge-plan.json        merge-phase artifact: merge plan (written by `plan`, consumed by `dry-run`/`execute`)
  photos-31-merge-summary.json     merge-phase artifact: library-merge summary (Section 13.5)
  photos-35-merge-log.json         merge-phase artifact: full transformation log (prep+geotag+merge, Section 13.3)
  photos-35-merge-ingest.db        merge-phase artifact: DB backup snapshot, end of merge (Section 13.4a)
  photos-35-archive-manifest.json  merge-phase artifact: the re-sealed package's manifest, superseding photos-26's (Section 13.6)
  gpx/                             gpx_root, when configured to live here (Section 8)
```

The section numbers in it are the shared contract's.
:::

:::{bld} An artifact's first digit names the phase that made it
:id: BLD-artifact_numbering
:status: seed
:realises: DEF-control_records

The numbered artifacts SHALL follow this scheme:

```text
0X  workspace infrastructure (phase-neutral): config, guard, live database
1X  prep-phase artifacts        (currently: 10 = prep plan, 11 = handoff, 15 = prep audit log + prep DB snapshot)
2X  geotag-phase artifacts        (currently: 21–26; 26 = complete log + geotag DB snapshot + archive manifest)
3X  merge-phase artifacts        (currently: 30 = merge plan, 31 = merge summary, 35 = merge log + merge DB snapshot + archive manifest)
```

The first digit SHALL mean only the producing phase. The second SHALL be a sequence number within the phase with no
further meaning: an absent number is not reserved, not headroom and not missing, and nothing is to be inferred from a
gap. Sibling end-of-phase records that differ only by extension MAY share a number — `photos-15-prep-log.json` and
`photos-15-prep-ingest.db` are both the end-of-prep record, one the human-readable log and one the database image;
likewise `photos-26-complete-log.json`, `photos-26-geotag-ingest.db` and `photos-26-archive-manifest.json`, and the
three `photos-35` files. The full filename — number, name and
extension — SHALL be the identifier, never the number alone; `photos-0X-*` (and `1X`, `2X`, `3X`) names a band. The
bands are unrelated to the numbered media folders `0-sources`…`6-photos-by-dest`.
:::

:::{bld} What prep skips
:id: BLD-prep_skip_set
:status: seed
:realises: RUL-not_inventoried, RUL-control_records_never_media, RUL-config_never_media, DEF-strays_folder

Prep SHALL skip `.photos-ingest/`, `.photos-ingest-quarantine/` and `.git` as whole subtrees, every dot-prefixed file,
and the strays folder `1-strays/` with all its `<plan-id>` subfolders (prep §3, §3.2). The strays of a run SHALL go to
`1-strays/<plan-id>/`. Hidden dotfiles in a dump area SHALL be swept to the quarantine (prep §3, §15).
:::

:::{bld} The plans' fixed paths
:id: BLD-canonical_plan_paths
:status: seed
:realises: RUL-plan_at_fixed_place, RUL-no_plan_location_option, RUL-no_plan_no_run

The plan and decision artifacts SHALL be prep's `photos-10-prep-plan.json`, geotag's `photos-21`, `photos-23` and
`photos-24`, and merge's `photos-30-merge-plan.json`, in `.photos-ingest/`. Every phase's `plan` SHALL write its file
there; `dry-run` and `execute` SHALL read it there; no command SHALL take a path flag for it.
:::

:::{bld} A superseded plan goes aside under `-NNN`
:id: BLD-plan_backups
:status: seed
:realises: RUL-replanning_keeps_the_prior, RUL-unchanged_replan_writes_nothing

A differing re-plan SHALL first rename the existing artifact under the shared incremental `-NNN` suffix (shared §7.2) —
`photos-10-prep-plan-001.json`, say — and announce where; byte-identical content SHALL write nothing and back up
nothing. A plan carrying a fresh plan id differs every run, so re-planning it always preserves the prior plan. The
per-run journals SHALL keep their `journal-<run_id>.json` naming; this convention governs the plan and decision
artifacts.
:::

:::{bld} The handoff's two hashes
:id: BLD-handoff_hashes
:status: seed
:realises: RUL-handoff_verified_by_content, RUL-run_only_refresh_restales_nothing

The handoff SHALL be `photos-11-handoff.json` in `.photos-ingest/`. Geotag SHALL recompute its `content_fingerprint` —
the content-scoped staleness key prep stamps on it (prep §16.2) — and compare it with the value in geotag's dependency
block (geotag §4). Its whole-file SHA-256 SHALL be kept as an integrity and archival hash (shared §13), never the
dependency check.
:::

:::{bld} The workspace's top level
:id: BLD-top_level_entries
:status: seed
:realises: RUL-top_level_only_managed, RUL-first_dump_at_top_level, RUL-structure_built_once

The top level of an initialized workspace SHALL hold exactly the managed folders `0-sources`…`6-photos-by-dest` and
`.photos-ingest/`, `.photos-ingest-quarantine/`, `.git` and other dotfiles and dot-directories; the inbox SHALL be
`0-sources/`. Prep applies the guard (prep §3.1), geotag at startup (geotag §13), merge as its precondition 0a (merge
§3).
:::

:::{bld} Where each phase applies the shape guards
:id: BLD-shape_guards_by_phase
:status: seed
:realises: RUL-no_links, RUL-who_checks_for_links, RUL-missing_folder_blocks, RUL-shape_checked_first

Links: prep across the tree it walks (prep §6.2 item 3); geotag and merge at the workspace root at startup (geotag §13;
merge precondition 0a), and through the handoff (geotag §7.2; merge precondition 3). Missing managed folders: prep §6.2
item 7, geotag §13, merge precondition 0c.
:::

## 5. Camera groups, derived once

:::{bld} `camera_group_key` and its version
:id: BLD-camera_group_key
:status: seed
:realises: DEF-camera_group, RUL-prep_derives_camera_group, RUL-geotag_reuses_camera_group, RUL-camera_group_derivation_versioned, RUL-known_when_classified

The key SHALL be `camera_group_key`, computed by prep from the serial, make, model and owner fields and emitted in both
the handoff manifest and SQLite (prep §12); geotag consumes and classifies it (geotag §16). Its derivation SHALL be
versioned by `CAMERA_GROUP_KEY_VERSION`, part of the metadata-freshness and dependency fingerprints. A group SHALL be
known when its key is listed under `camera_time_and_timezone_policy.device_groups` — `phones` (mobile) or
`fixed_clock_cameras` (fixed-clock).
:::

## 6. One filename format

:::{bld} `filename_timestamp_format`
:id: BLD-filename_timestamp_format
:status: seed
:realises: RUL-one_filename_format, DEF-timestamp_name

The format SHALL be the configuration key `filename_timestamp_format`, default `"%Y-%m-%d--%H-%M-%S"`, which gives a
timestamp of the form `YYYY-MM-DD--HH-MM-SS`. Both phases SHALL read it; it takes part in the dependency cascade (shared
§9) through the filename-format fingerprint, and a change to it restales prep's by-date organization and geotag's
executable rename plan.
:::

:::{bld} The `-NNN` suffix
:id: BLD-name_suffix
:status: seed
:realises: RUL-suffix_no_clobber, RUL-suffix_choice_by_phase

The names SHALL be `<timestamp>.ext` for the first file with a free base name, `<timestamp>-001.ext` for the first
collision, `<timestamp>-002.ext` for the second, and so on. Each phase specifies its allocation where it plans its
renames: prep §8 and §7.3, geotag §27, merge §7.
:::

:::{bld} Geotag's final name, step by step
:id: BLD-geotag_final_name
:status: seed
:realises: RUL-geotag_name_final

Geotag SHALL compute the final name as resolved UTC → the destination's civil timezone → a local naive datetime → the
format.
:::
