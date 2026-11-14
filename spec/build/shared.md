# Shared — how this build does it

How this build meets [the shared intent](../intent/shared.md): the files, names, tools and steps. Each item `realises`
the intent it implements. *Why* a choice was made is in [the rationale](../rationale/shared.md).

## 0. The pipeline

:::{bld} The phases are three commands
:id: BLD-phase_commands
:status: ruled
:realises: DEF-prep, DEF-geotag, DEF-merge

The phases SHALL be the commands `photos-cartographer prep`, `geotag` and `merge` — named in the specs, and in their
records, `photos-1-prep`, `photos-2-geotag` and `photos-3-merge`.
:::

## 1. One run at a time

:::{bld} The lock is taken first
:id: BLD-lock_after_guard
:status: ruled
:realises: RUL-lock_before_reading

The lock SHALL be taken as soon as the run's workspace is known, before the guard, `photos-00-workspace-guard`, or
anything else in it is read.
:::

:::{bld} Only prep creates the control directory
:id: BLD-control_dir_by_prep_only
:status: ruled
:realises: RUL-only_prep_builds_structure

`WorkspaceLock` SHALL create the control directory only when prep takes it; every other taker passes `create=False`.
:::

:::{bld} Geotag and merge stop where there is no control directory
:id: BLD-no_control_dir_stops
:status: ruled
:realises: RUL-only_prep_builds_structure

Geotag and merge SHALL check that the control directory exists before they take the lock, and where it does not, stop
with exit status 2, having created nothing.
:::

:::{bld} The editor's save takes the lock
:id: BLD-editor_save_locks
:status: ruled
:realises: RUL-every_command_locks

The decision editor's save SHALL take the workspace lock for the time it writes, refusing at once while a run holds it;
the editor's display reads take none, each record being replaced whole.
:::

:::{bld} The lock records its owner
:id: BLD-lock_owner_record
:status: ruled
:realises: RUL-stale_lock_recovered

The lock SHALL record the identity of the process that owns it and the time it started, so that a lock whose owner is
gone can be told from one whose owner is running.
:::

:::{bld} The phases run inside the run's lock
:id: BLD-phases_inside_lock
:status: ruled
:realises: RUL-lock_through_the_run

Each phase's `plan`, `dry-run` and `execute` SHALL run with the lock taken at start already held, none taking it again
or scoping it on its own ({need}`RUL-lock_through_the_run`; geotag §29).
:::

## 2. A snapshot before changing, optionally

:::{bld} The snapshot is a ZFS snapshot, configured by the `zfs` block
:id: BLD-snapshot_is_zfs
:status: ruled
:realises: RUL-snapshot_optional, RUL-snapshot_off_by_default, RUL-required_snapshot_or_nothing, RUL-snapshot_per_plan

The snapshot SHALL be a ZFS snapshot, configured by the `zfs` block of the workspace configuration,
`photos-00-config.json`; with no `zfs` block, or one not enabled, none is taken. Its name carries the plan id.
`snapshots_required` decides what a failed snapshot means: true, the run aborts before its first change; false, or the
block not configured, it proceeds without one.
:::

:::{bld} Merge's two snapshots
:id: BLD-merge_snapshots
:status: ruled
:realises: RUL-merge_snapshots_library, RUL-no_library_only_snapshot

Merge's `_take_snapshots` SHALL snapshot the workspace's dataset and then, where the library's differs, the library's —
each pinned by `zfs.datasets.workspace` and `zfs.datasets.library` or detected from its path — taking the library's
only after the workspace's has succeeded, and recording both in `photos-31-merge-summary.json` under `snapshot`.
:::

:::{bld} One snapshot mechanism for every phase
:id: BLD-one_snapshot_mechanism
:status: ruled
:realises: RUL-snapshot_optional

The three phases SHALL take their snapshots through one mechanism — prep's execute, geotag §29 and merge §10.3 invoke it,
and none redefines it.
:::

## 3. One configuration, kept in the workspace

:::{bld} The configuration is `photos-00-config.json`, in the control directory
:id: BLD-config_file
:status: ruled
:realises: DEF-configuration, RUL-one_configuration, RUL-config_never_media

The configuration SHALL be the JSON file `photos-00-config.json` in the workspace's control directory, `.photos-ingest/`,
which prep skips wholesale (§5 of the shared contract) — never an in-code global.
:::

:::{bld} Every phase reads the configuration through one loader
:id: BLD-config_loader
:status: ruled
:realises: RUL-one_configuration, RUL-config_complete, RUL-config_no_unknown_settings

Every phase SHALL read the configuration through `load_config`, which refuses a file lacking any setting of the built-in
template, naming each with its default, or holding one the template lacks, and otherwise replaces the in-code `CONFIG` with the file wholesale, the
extension-to-class map rebuilt from it. Seed defaults supplied by a deployment are refused the same way.
:::

:::{bld} Prep seeds from a template a deployment may replace
:id: BLD-config_seed_template
:status: ruled
:realises: RUL-config_seeded_once, RUL-config_authoritative

Prep SHALL seed the configuration from a default template. A deployment MAY supply its own seed defaults; how it does
so is the deployment's concern, not the specification's.
:::

:::{bld} `init-library` may write `library_root`
:id: BLD-init_library_writes_library_root
:status: ruled
:realises: RUL-library_setup_writes_one_setting

The setup command `init-library` (merge §4), run inside a workspace with an explicit library path, MAY write the
`library_root` key into the configuration, and only that key. It is not part of merge's data path.
:::

:::{bld} Field-scoped fingerprints, and one whole-file SHA-256
:id: BLD-config_fingerprints
:status: ruled
:realises: RUL-staleness_by_area, RUL-config_in_dependencies, RUL-organization_settings_restale, RUL-config_digest_recorded

Two things SHALL be derived from the configuration: field-scoped fingerprints — the filename format, the camera-time and
timezone policy, the GPX thresholds, the camera-group-key version, the snapshot policy, the folder-name set, the
media-extension lists, and others — which drive staleness, the folder-set and media-extension fingerprints among the
dependencies of geotag's executable plan and of merge's plan; and one SHA-256 of the whole file, for integrity and
provenance, recorded in the archival manifest.
:::

:::{bld} The whole-file hash is in the executable plan's dependencies
:id: BLD-whole_hash_in_the_plan
:status: ruled
:realises: RUL-any_config_change_replans

The whole-file fingerprint SHALL be carried in the `depends_on` of geotag's executable plan (geotag §28, in the
flattened dependency set of geotag §5) and of merge's plan, `config_fingerprint`, each plan refused when it no longer
matches the file.
:::

:::{bld} The costly caches are keyed on their own areas
:id: BLD-costly_caches_keyed_by_area
:status: ruled
:realises: RUL-costly_results_survive_unrelated_edits, RUL-times_survive_unrelated_config_edits

The costly caches SHALL be keyed on their own areas instead of the whole-file fingerprint: resolved UTC on the
time-policy subset (geotag §22.1), the renames on the filename-format fingerprint.
:::

:::{bld} Prep guards execution with the whole-file hash
:id: BLD-prep_guards_with_the_whole_hash
:status: ruled
:realises: RUL-any_config_change_replans

Prep SHALL re-plan from the filesystem each run and guard execution with the whole-file hash, keeping no folder or
extension fingerprint of its own.
:::

:::{bld} The control directory is always `.photos-ingest/`
:id: BLD-control_directory_fixed
:status: ruled
:realises: RUL-control_directory_fixed

The control directory SHALL be `.photos-ingest/` at the workspace root, in every workspace, no configuration key naming
it.
:::

:::{bld} The configuration's keys
:id: BLD-config_keys
:status: ruled
:realises: DEF-config_areas, RUL-folder_names_not_roles, RUL-camera_classes_not_derivation, RUL-extension_one_class, RUL-folder_found_by_role, RUL-config_lists_extensions, RUL-unlisted_extension_other

The areas SHALL be, at least: the `zfs` block and `snapshots_required` (§2 above);
`camera_time_and_timezone_policy.device_groups`, with `phones` and `fixed_clock_cameras` ({need}`DEF-camera_group`);
`filename_timestamp_format` ({need}`BLD-filename_timestamp_format`); `gpx_root` and the GPX thresholds, such as `gpx_direct_match_max_seconds`,
`gpx_interpolation_max_gap_seconds` and `gpx_interpolation_max_distance_meters` ({need}`DEF-tracks`); the camera-time policy
flags, such as `single_anchor_auto_apply` and `multi_anchor_auto_apply` (geotag); `library_root`
(merge; {need}`DEF-library`); `folders`, a role→name map of the numbered managed folders
`0-sources`…`6-photos-by-dest` ({need}`DEF-managed_folders`, prep §3), whose code finds each folder by its role; and `media_extensions`,
mapping `image`, `raw` and `video` to lists of canonical extensions — lowercase, no leading dot (prep §6.1).
`CAMERA_GROUP_KEY_VERSION` is a code constant, never a configuration field.
:::

:::{bld} What validating the configuration checks
:id: BLD-config_values_checked
:status: ruled
:realises: RUL-config_validated_before_use, RUL-checked_paths, RUL-checked_snapshot_names, RUL-checked_filename_format, RUL-checked_numbers

Validating the configuration SHALL check, among others, that a path resolves sanely, that a ZFS snapshot prefix is a
syntactically valid snapshot component, and that an IANA timezone is a real zone.
:::

## 4. The control records, apart from the media

:::{bld} The control directory's contents
:id: BLD-control_directory_contents
:status: ruled
:realises: DEF-control_records, RUL-control_records_together

The control records SHALL be these files in `.photos-ingest/` ({need}`DEF-archival_package` and {need}`DEF-workspace_database` for the archival and database ones):

```text
.photos-ingest/
  photos-00-config.json            workspace configuration (seeded by prep, Section 4)
  photos-00-workspace.lock         the workspace lock: held by every run while it plans or executes (Section 2)
  photos-00-decision-editor.lock   the decision editor's lock: one editor at a time on a workspace
  photos-00-workspace-guard        workspace root sentinel: marks the workspace as INITIALIZED (written last by prep on init)
  photos-00-sealed.json            terminal/sealed marker, written by a successful merge ALONGSIDE the guard (a separate file, not a field inside the guard) — its presence seals the workspace (Section 13.7)
  photos-00-ingest.db              SQLite identity/metadata cache + derived caches (live working DB, Section 13.4)
  photos-00-plan-memo.db           prep-phase scratch: plan memo, what planning read of each media file (disposable, NOT part of the record)
  photos-00-track-memo.db          geotag-phase scratch: each track file's parsed points, by the SHA-256 of its bytes (disposable, NOT part of the record)
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
  photos-26-finalized-media.json   geotag-phase artifact: each by-dest photo's size and mtime as finalize found it
  photos-26-archive-manifest.json  geotag-phase artifact: the archival package's manifest, at finalize (Section 13.2)
  photos-26-archive.tar.gz         geotag-phase artifact: the archival package, at finalize (Section 13.2)
  photos-30-merge-plan.json        merge-phase artifact: merge plan (written by `plan`, consumed by `dry-run`/`execute`)
  photos-31-merge-summary.json     merge-phase artifact: library-merge summary (Section 13.5)
  photos-35-merge-log.json         merge-phase artifact: full transformation log (prep+geotag+merge, Section 13.3)
  photos-35-merge-ingest.db        merge-phase artifact: DB backup snapshot, end of merge (Section 13.4a)
  photos-35-archive-manifest.json  merge-phase artifact: the re-sealed package's manifest, superseding photos-26's (Section 13.6)
  photos-35-archive.tar.gz         merge-phase artifact: the re-sealed archival package (Section 13.6)
  executed/<plan id>/              geotag: the decision records each executed plan ran against (Section 13.3a)
  <artifact>-NNN.<ext>             a superseded plan or decision record, kept when it was replaced (Section 5)
  gpx/                             gpx_root, when configured to live here (Section 8)
```

The section numbers in it are the shared contract's.
:::

:::{bld} An artifact's first digit names the phase that made it
:id: BLD-artifact_numbering
:status: ruled
:realises: DEF-control_records

The numbered artifacts SHALL follow this scheme:

```text
0X  workspace infrastructure (phase-neutral): config, guard, live database
1X  prep-phase artifacts        (currently: 10 = prep plan, 11 = handoff, 15 = prep audit log + prep DB snapshot)
2X  geotag-phase artifacts        (currently: 21–26; 26 = complete log + geotag DB snapshot + archive manifest)
3X  merge-phase artifacts        (currently: 30 = merge plan, 31 = merge summary, 35 = merge log + merge DB snapshot + archive manifest)
```

The first digit means only the producing phase. The second is a sequence number within the phase with no
further meaning: an absent number is not reserved, not headroom and not missing, and nothing is to be inferred from a
gap. Sibling end-of-phase records that differ only by extension MAY share a number — `photos-15-prep-log.json` and
`photos-15-prep-ingest.db` are both the end-of-prep record, one the human-readable log and one the database image;
likewise `photos-26-complete-log.json`, `photos-26-geotag-ingest.db` and `photos-26-archive-manifest.json`, and the
three `photos-35` files. The full filename — number, name and
extension — is the identifier, never the number alone; `photos-0X-*` (and `1X`, `2X`, `3X`) names a band. The
bands are unrelated to the numbered media folders `0-sources`…`6-photos-by-dest`.
:::

:::{bld} What prep skips
:id: BLD-prep_skip_set
:status: ruled
:realises: RUL-not_inventoried, RUL-control_records_never_media, RUL-config_never_media, DEF-strays_folder, RUL-strays_never_processed

Prep SHALL skip `.photos-ingest/`, `.photos-ingest-quarantine/` and `.git` as whole subtrees, every dot-prefixed file,
and the strays folder `1-strays/` with all its `<plan-id>` subfolders (prep §3, §3.2), the strays of a run going to
`1-strays/<plan-id>/`.
:::

:::{bld} Hidden files in a dump go to the quarantine
:id: BLD-dump_dotfiles_quarantined
:status: ruled
:realises: RUL-dump_hidden_files_quarantined

Hidden dotfiles in a dump area SHALL be swept to the quarantine (prep §3, §15).
:::

:::{bld} The plans' fixed paths
:id: BLD-canonical_plan_paths
:status: ruled
:realises: RUL-plan_at_fixed_place, RUL-no_plan_location_option, RUL-no_plan_no_run

The plan and decision artifacts SHALL be prep's `photos-10-prep-plan.json`, geotag's `photos-21`, `photos-22`,
`photos-23` and `photos-24`, and merge's `photos-30-merge-plan.json`, in `.photos-ingest/`: every phase's `plan` writes its file there,
`dry-run` and `execute` read it there, and no command takes a path flag for it.
:::

:::{bld} A superseded plan goes aside under `-NNN`
:id: BLD-plan_backups
:status: ruled
:realises: RUL-replanning_keeps_the_prior

A differing re-plan SHALL first rename the existing artifact under the shared incremental `-NNN` suffix ({need}`BLD-name_suffix`) —
`photos-10-prep-plan-001.json`, say — and announce where. A plan carrying a fresh plan id differs every run, so
re-planning it always preserves the prior plan. The per-run journals keep their `journal-<run_id>.json` naming; this
convention governs the plan and decision artifacts.
:::

:::{bld} A byte-identical re-plan writes nothing
:id: BLD-identical_replan_writes_nothing
:status: ruled
:realises: RUL-unchanged_replan_writes_nothing

A re-plan whose content is byte-identical to the saved artifact SHALL write nothing and back up nothing.
:::

:::{bld} The handoff's two hashes
:id: BLD-handoff_hashes
:status: ruled
:realises: RUL-handoff_verified_by_content, RUL-run_only_refresh_restales_nothing

The handoff SHALL be `photos-11-handoff.json` in `.photos-ingest/`, which geotag checks by its `content_fingerprint` —
the content-scoped staleness key prep stamps on it ({need}`BLD-handoff_content_fingerprint`) — recomputing it and comparing it with the value in
geotag's dependency block (geotag §4). Its whole-file SHA-256 is kept as an integrity and archival hash ({need}`DEF-archival_package`),
never the dependency check.
:::

:::{bld} The workspace's top level
:id: BLD-top_level_entries
:status: ruled
:realises: RUL-top_level_only_managed, RUL-first_dump_at_top_level, RUL-structure_built_once, RUL-only_prep_builds_structure

The top level of an initialized workspace SHALL hold exactly the managed folders `0-sources`…`6-photos-by-dest` and
`.photos-ingest/`, `.photos-ingest-quarantine/`, `.git` and other dotfiles and dot-directories, the inbox being
`0-sources/`. Prep applies the guard (prep §3.1), geotag at startup (geotag §13), merge as its precondition 0a (merge
§3).
:::

:::{bld} One check of the top level for all three phases
:id: BLD-one_top_level_check
:status: ruled
:realises: RUL-top_level_only_managed

Prep, geotag and merge SHALL find a workspace's misplaced top-level entries with the one function they share,
`photos_utils.misplaced_top_level_entries`, so the three cannot disagree on what belongs there.
:::

:::{bld} Where each phase applies the shape guards
:id: BLD-shape_guards_by_phase
:status: ruled
:realises: RUL-no_links, RUL-who_checks_for_links, RUL-missing_folder_blocks, RUL-shape_checked_first, RUL-link_named, RUL-geotag_merge_check_top_level_links, RUL-missing_folder_named, RUL-empty_inbox_normal

Links: prep across the tree it walks (prep §6.2 item 3); geotag and merge at the workspace root at startup (geotag §13;
merge precondition 0a), and through the handoff (geotag §7.2; merge precondition 3). Missing managed folders: prep §6.2
item 7, geotag §13, merge precondition 0c.
:::

## 5. Camera groups, derived once

:::{bld} `camera_group_key` and its version
:id: BLD-camera_group_key
:status: ruled
:realises: DEF-camera_group, RUL-prep_derives_camera_group, RUL-geotag_reuses_camera_group

The key SHALL be `camera_group_key`, computed by prep from the serial, make, model and owner fields and emitted in both
the handoff manifest and SQLite (prep §12); geotag consumes and classifies it (geotag §16).
:::

:::{bld} `CAMERA_GROUP_KEY_VERSION`
:id: BLD-camera_group_key_version
:status: ruled
:realises: RUL-camera_group_derivation_versioned

The derivation of `camera_group_key` SHALL be versioned by `CAMERA_GROUP_KEY_VERSION`, recorded with each file's
metadata and in each plan's dependencies, and compared with the running code's: by prep's metadata freshness, by geotag's
plan against every file of the handoff, and by geotag's execute against its plan.
:::

:::{bld} A camera group is known when it is listed
:id: BLD-known_camera_group
:status: ruled
:realises: RUL-known_when_classified

A group SHALL be known when its key is listed under `camera_time_and_timezone_policy.device_groups` — `phones` (mobile)
or `fixed_clock_cameras` (fixed-clock).
:::

## 6. One filename format

:::{bld} `filename_timestamp_format`
:id: BLD-filename_timestamp_format
:status: ruled
:realises: RUL-one_filename_format, DEF-timestamp_name

The format SHALL be the configuration key `filename_timestamp_format`, default `"%Y-%m-%d--%H-%M-%S"`, which gives a
timestamp of the form `YYYY-MM-DD--HH-MM-SS`. Both phases read it; geotag's plans also depend on it through the
filename-format fingerprint ({need}`DEF-dependency_cascade`).
:::

:::{bld} The `-NNN` suffix
:id: BLD-name_suffix
:status: ruled
:realises: RUL-suffix_no_clobber, RUL-suffix_choice_by_phase, RUL-merge_suffix_above_highest

The names SHALL be `<timestamp>.ext` for the first file with a free base name, `<timestamp>-001.ext` for the first
collision, `<timestamp>-002.ext` for the second, and so on.
:::

:::{bld} Geotag's final name, step by step
:id: BLD-geotag_final_name
:status: ruled
:realises: RUL-geotag_name_final

Geotag SHALL compute the final name as resolved UTC → the destination's civil timezone → a local naive datetime → the
format.
:::

:::{bld} The `UNKN_` mark
:id: BLD-untimed_mark
:status: ruled
:realises: DEF-untimed_name

The untimed name SHALL be `UNKN_<name it came with>`, with the `-NNN` suffix when that is taken.
:::

:::{bld} What prep checks a name against
:id: BLD-name_check
:status: ruled
:realises: RUL-misnamed_file_stops_prep, RUL-misnamed_file_named

At plan, prep SHALL check the name of every media file in the dated, missing-metadata, redundant-JPG and by-destination
folders: without its extension and `-NNN` suffix, it is the file's recorded time ({need}`RUL-recorded_time_order`)
formatted by `filename_timestamp_format`, or starts with `UNKN_` for a file with no recorded time and for every file in
the missing-metadata folder. A dated file with no recorded time is moved to the missing-metadata folder instead, and the
strays folder is not checked.
:::

:::{bld} The format recorded in the handoff
:id: BLD-format_recorded
:status: ruled
:realises: RUL-format_fixed_once_named

The handoff SHALL record the format prep named the files in as `filename_timestamp_format`; prep compares it with the
configured format at plan once a file outside the inbox carries a timestamp name, and geotag and merge at their start.
:::

## 7. The tracks, kept outside the managed folders

:::{bld} `gpx_root`
:id: BLD-gpx_root
:status: ruled
:realises: DEF-tracks, RUL-tracks_outside_managed_folders

The tracks' location SHALL be the configuration key `gpx_root`: a path, absolute or relative to the workspace, resolved
through links before use; empty means no tracks. It MAY be anywhere outside `0-sources` … `6-photos-by-dest` — on any
disk, or under the control directory, such as `.photos-ingest/gpx/`, which prep's skip of `.photos-ingest/` already keeps
out of the scan. Geotag reads every `*.gpx` file beneath it. The value and the matching thresholds are read by geotag;
their detail is geotag §15 and §19.
:::

:::{bld} `gpx_root` checked against the managed folders
:id: BLD-gpx_root_checked
:status: ruled
:realises: RUL-tracks_outside_managed_folders

Configuration validation, in every phase, SHALL resolve `gpx_root` against the workspace, through links, and refuse it
when it is a managed folder, lies inside one, or contains one — the workspace root among them.
:::

:::{bld} A track file
:id: BLD-track_file
:status: ruled
:realises: DEF-tracks

A track file SHALL be a file named `*.gpx`, `*.kml`, `*.kmz`, `*.fit`, `*.tcx`, `*.nmea` or `*.igc`, in any case. Of
these geotag reads only the `*.gpx` files beneath `gpx_root`.
:::

:::{bld} Prep's blocker for a track file
:id: BLD-track_file_blocker
:status: ruled
:realises: RUL-track_files_block_prep, RUL-track_file_left_in_place

Prep SHALL raise one blocker for each track file it inventories, naming it, and leave it out of the plan (prep §3,
§6.1); execute raises the same blocker for one that appeared after planning ({need}`RUL-new_file_restales_plan`).
:::

:::{bld} The GPX fingerprint
:id: BLD-gpx_fingerprint
:status: ruled
:realises: RUL-tracks_in_dependencies

The GPX fingerprint SHALL be a SHA-256 over the resolved `gpx_root`, a version tag, and, in sorted order, each `*.gpx`
file's path relative to the root and the SHA-256 of its bytes, then every point read from them, in time order. An empty `gpx_root`, and a `gpx_root` that is not a
directory, each give a fixed value of their own, the second with a warning. It is recorded as `gpx_fingerprint` in the
`depends_on` of `photos-21-time-decisions.json`, `photos-22-gps-drift-validation.json`, `photos-23-gps-decisions.json`
and `photos-24-executable-plan.json`, and checked before each is used.
:::

## 8. Nothing used once what it came from has changed

:::{bld} Each phase's dependencies, in full
:id: BLD-phase_dependencies
:status: ruled
:realises: INV-no_stale_use

Each phase SHALL record a record's dependencies in its `depends_on` block and check them before use, as its own spec
states in full: prep in {need}`BLD-prep_dependencies`; geotag in {need}`BLD-geotag_dependencies`; merge in {need}`BLD-merge_plan`. The cascade consumes media by content fingerprints, records by byte
hashes, and the field-scoped configuration fingerprints ({need}`DEF-config_areas`) that keep staleness surgical.
:::

:::{bld} How a fingerprint is computed
:id: BLD-fingerprint
:status: ruled
:realises: DEF-fingerprint, RUL-fingerprint_survives_mutation

A photo's fingerprint SHALL be ImageMagick `identify`'s signature — a SHA-256 of the normalized pixel stream; a video's,
the `ffmpeg` MD5 of its streams as stored, copied out without decoding (`-c copy`).
:::

:::{bld} How a hash is computed
:id: BLD-hash
:status: ruled
:realises: DEF-hash, RUL-hash_detects_any_change, RUL-hash_is_the_dependency_check

A hash SHALL be a SHA-256 over the exact bytes of a numbered JSON record or the configuration.
:::

## 9. One loop across the phases

:::{bld} The loop's commands
:id: BLD-loop_commands
:status: ruled
:realises: DEF-operator_loop, DEF-finalize

The loop SHALL run as: `prep plan`, `dry-run`, `execute`; the sort, by hand; the prep commands again; `geotag plan`, the
decision editor (`edit`) for what it asks, and `geotag plan` again until `photos-24-executable-plan.json` is ready;
`geotag execute`, which writes `photos-25-execution-summary.json`; `geotag finalize`, which writes
`photos-26-complete-log.json` and the archival package; and `merge plan`, `dry-run`, `execute`.
:::

:::{bld} Geotag runs prep itself when the inbox is empty
:id: BLD-geotag_auto_reprep
:status: ruled
:realises: RUL-prep_records_sort, RUL-sort_recorded_by_stat, RUL-geotag_plans_on_current_record

When the only change prep has not recorded is one {need}`BLD-reprep_pending` names and the inbox is empty, `geotag
plan` SHALL run prep's `plan` and `execute` itself, inside its own lock, saying so, before it plans.
:::

:::{bld} What prep has yet to record
:id: BLD-reprep_pending
:status: ruled
:realises: RUL-prep_records_sort, RUL-geotag_plans_on_current_record

`by_dest_reprep_pending` SHALL name, from sizes and modification times alone, a photo in photos by destination the
handoff does not record at its path, one the handoff records in photos by date or by destination that is gone, or one
it records in photos by destination whose size or `mtime_ns` differs from its record: `geotag plan` stops on it with
the one re-prep blocker, and runs prep itself when {need}`BLD-geotag_auto_reprep` allows; prep's nothing-to-do guard
does not stop while it names one.
:::

:::{bld} Where the loop's gates are checked
:id: BLD-loop_gates
:status: ruled
:realises: RUL-geotag_gates, RUL-sort_photos_only, RUL-development_after_merge

The gates SHALL be checked as follows: `geotag plan` checks every gate; `geotag execute` and `finalize` check the
development gate and the workspace's shape, and validate against the plan's own dependencies instead of the scope and
re-prep gates (geotag §7, §13.1); merge's preflight checks the inbox, the development gate and that photos by
destination holds only photos (merge §3). A development subfolder is one named in `destination_distribution_subfolders`.
:::

:::{bld} Geotag marks what it wrote
:id: BLD-rerun_recognition
:status: ruled
:realises: RUL-geotag_rerun_keeps_settled

Geotag SHALL record what it wrote in the file's `GPSProcessingMethod`: the bare value `interpolated`, `manual_locked` or
`manual_fallback` beside each position it writes, and, when it fixes the time and writes no position, the suffix
`+carto-time` appended once to whatever the field held, keeping the device's own value. Any other value is the device's
own, and the GPS beside it native.
:::

:::{bld} A file's own values are pinned before geotag first writes it
:id: BLD-original_values_pinned
:status: ruled
:realises: RUL-geotag_rerun_keeps_settled

Before geotag's first write to a file, execution SHALL pin its own time, offset tag, position and `GPSProcessingMethod`
in an original-values ledger keyed by fingerprint, once, unless it already carries geotag's mark; a later plan decides
about a pinned file from those values and plans only the writes that differ from what it holds (geotag §24.2).
:::

:::{bld} A re-run treats a marked file as geotag's work
:id: BLD-marked_file_rerun
:status: ruled
:realises: RUL-geotag_rerun_keeps_settled

On a re-run, a file with no pinned values carrying a position marker or the suffix SHALL be resolved from its own time
and offset tag with no clock offset, as no clock anchor and in no drift check, a camera group's offset cells being built
from its unmarked files alone. A file with a position marker counts as having no native GPS and is placed again; one now
placed nowhere has geotag's position and marker cleared and carries the suffix alone.
:::

:::{bld} A re-run plans only the writes and renames that differ
:id: BLD-rerun_writes_only_differences
:status: ruled
:realises: RUL-geotag_rerun_keeps_settled

A write SHALL be planned only where the file does not already hold its value, names being recomputed from the
destination's local time, a file already so named getting no rename (geotag §27, §28.2).
:::

:::{bld} Each photo as finalize found it
:id: BLD-finalized_media
:status: ruled
:realises: RUL-merge_refuses_changed_since_finalize

`geotag finalize` SHALL write `photos-26-finalized-media.json`, giving each photo in photos by destination, under its
final path, its size and modification time; merge's preflight refuses when a photo still there differs from it, or the
record is missing.
:::

## 10. Change only what needs changing

:::{bld} What each phase reuses
:id: BLD-idempotency
:status: ruled
:realises: RUL-reuse_valid_work

Each phase SHALL reuse what is still valid: prep, the cached fingerprint and metadata of a file whose size and
modification time are unchanged, carrying a moved file's identity forward without reading it ({need}`RUL-moved_file_carried`), a plan never executed leaving its fingerprints and metadata for the next plan to reuse
({need}`RUL-plan_memo_kept`); geotag reads no photo,
taking every photo's metadata from prep, works out its results again on each run — a result that comes out the same
leaving everything that depends on it as it is — keeps each decision whose target is unchanged (geotag §9, §22.1), and
reads every track file whole for its fingerprint but parses only one whose bytes it has not parsed before, taking the
rest from its track memo, `photos-00-track-memo.db`; merge, a library file's fingerprint while its size and
modification time are unchanged (merge §7). Fingerprinting (ImageMagick `identify`, `ffmpeg`), metadata extraction
(`exiftool`) and GPX parsing thus run only for new or changed inputs. Each phase's own consequences are in its spec:
{need}`RUL-no_op_run` and prep §21, geotag §29.1 and §30, merge §8.
:::

:::{bld} Staleness follows the field-scoped fingerprints
:id: BLD-staleness_by_field_fingerprints
:status: ruled
:realises: RUL-remake_only_what_depends

Staleness SHALL follow the dependencies each record carries ({need}`DEF-dependency_cascade`): a plan depends on the
whole configuration's hash, a costly result on the hash of the areas it reads.
:::

:::{bld} An operation only where the file differs
:id: BLD-operation_only_where_different
:status: ruled
:realises: RUL-mutate_on_difference, RUL-no_op_run

A file's operation SHALL be planned only where the file does not already hold the target: prep does not move or rename a
file already in place, geotag plans no write a file already holds and recomputes an already-final name to itself (geotag
§27, §28.2), and merge records a photo already in the library as already present (merge §7).
:::

:::{bld} A run's summary counts what it reused
:id: BLD-summary_counts_reuse
:status: ruled
:realises: RUL-no_op_run_reports_reuse

Each phase's report SHALL count the files already right, and the work it took from a cache: prep's summary its cache
hits, merge's plan the library fingerprints it reused — in what it prints, never in the plan, which an unchanged
re-plan leaves byte-identical. Geotag keeps no cache of results, so has none to count.
:::

## 11. Nothing changes that the user did not write down

:::{bld} Where the decisions live
:id: BLD-decision_records
:status: ruled
:realises: RUL-user_writes_decisions, RUL-decision_fields_laid_out

The decisions SHALL live in the `user_decision` fields of geotag's `photos-21`, `photos-22` and `photos-23`, each field
created by geotag and preserved across regeneration (geotag §9, §20), the decision editor writing only those fields.
:::

:::{bld} How a change is traced to its decision
:id: BLD-change_traced
:status: ruled
:realises: RUL-cause_locatable, RUL-decision_revisable

A change SHALL be traced from its decision record through the `depends_on` fingerprints (§9) to the executable plan and
the run's journal ({need}`BLD-prep_journal`; geotag §4–§6, §29). Merge takes no decision; its placement is a fixed rule over recorded
inputs, recorded the same way (merge §8–§9).
:::

:::{bld} Every plan decides from a photo's own values
:id: BLD-decided_from_own_values
:status: ruled
:realises: RUL-withdrawal_undoes, RUL-decision_revisable

Every plan SHALL decide about a photo from its own values, pinned before geotag first wrote to it (geotag §24.2), so a
withdrawn manual position is undone like any decision: the photo is placed again, or geotag's position cleared; an
automatic position is recomputed, never rolled back.
:::

## 12. The record of what was done, kept beyond the workspace

:::{bld} The per-phase logs
:id: BLD-phase_logs
:status: ruled
:realises: RUL-record_whole_each_phase, RUL-carry_forward_by_copy

Each phase SHALL write its log: prep `photos-15-prep-log.json` at the end of every prep run ({need}`BLD-prep_log_build`); geotag's
finalize copies it to `photos-26-complete-log.json` and appends each photo's geotag steps (§13.3); merge copies that to
`photos-35-merge-log.json` and appends its own (§13.5).
:::

:::{bld} A copied log carries the earlier one unchanged
:id: BLD-log_copy_checked
:status: ruled
:realises: RUL-carry_forward_by_copy

Each copy SHALL carry the earlier log unchanged — every entry, every field and every step as it was, a phase only adding
— which finalize and merge check: a copy that would change the earlier record is not written, and merge refuses while
`photos-26-complete-log.json` no longer carries `photos-15-prep-log.json` so, or cannot be read.
:::

:::{bld} Prep's log is checked against the handoff
:id: BLD-prep_log_checked
:status: ruled
:realises: RUL-carry_forward_by_copy, RUL-merge_takes_finalized_current

Finalize and merge SHALL stop while `photos-15-prep-log.json` is not the log the handoff vouches for
({need}`BLD-prep_log_vouched`) — missing, unreadable, its SHA-256 other than `depends_on.prep_log`'s, or the handoff
recording none — through the shared `prep_log_blocker`, merge among its gathered preconditions.
:::

:::{bld} The job records stay on disk
:id: BLD-job_records_kept
:status: ruled
:realises: RUL-record_whole_each_phase

Each phase's job records — prep's handoff and summary, geotag's decision, plan and execution-summary records, merge's
summary — SHALL stay on disk, as do every pass's plan and journal and the decision records each execution kept
(`BLD-log_format`).
:::

:::{bld} The code's fingerprint
:id: BLD-code_fingerprint
:status: ruled
:realises: RUL-plan_carried_out_by_its_code

The code's fingerprint, `code_fingerprint`, SHALL be the SHA-256 over the files of the `cartographer` package the
zipapp ships, as loaded — from the zipapp or a checkout, which agree — each one's path and bytes in path order. Prep's
plan records it as `code_fingerprint`, compared at execute and dry run after the plan's schema version and command and
before its operations; geotag's executable plan and merge's plan record it in their `depends_on`, a plan recording
another value or none stale at dry run and execute alike.
:::

:::{bld} Which phase writes which record
:id: BLD-record_ownership
:status: ruled
:realises: RUL-phase_writes_own_records
:uses: BLD-artifact_numbering, BLD-init_library_writes_library_root

A phase SHALL write only records in its own number band of the numbering scheme: prep `photos-1X`, geotag `photos-2X`,
merge `photos-3X`, and on success the seal, `photos-00-sealed.json`, which merge alone writes. The configuration and
the database are phase-neutral, each with its own writers' rule: prep seeds
the configuration, which `init-library` may later extend by `library_root` alone (§4), and prep writes the database's
cache and identity rows while geotag and merge write only their own regions of it (§13.4). Bundling copies of every phase's records into the archival package reads them, and is no write.
:::

:::{bld} The package: the control directory, archived with its manifest
:id: BLD-archive_manifest
:status: ruled
:realises: RUL-finalize_non_destructive, RUL-package_contents, RUL-package_self_describing

`geotag finalize` SHALL write `photos-26-complete-log.json` and the database snapshot `photos-26-geotag-ingest.db`, then
list every file of the control directory but the transient ones — locks, `.tmp-` files, SQLite's `-journal` files, the
plan and track memos `photos-00-plan-memo.db` and `photos-00-track-memo.db`, and any `*-archive.tar.gz` — with its SHA-256 and path in
`photos-26-archive-manifest.json`, recording the workspace's identity — the init run id prep wrote in the guard — with
the folder's name beside it, and the plan and execution ids, and archive those files and the manifest into
`photos-26-archive.tar.gz` in the control directory, by a temporary name and an atomic rename — writing nothing else,
and requiring a ready plan whose execution succeeded (geotag §31). Merge's re-seal does the same into
`photos-35-archive-manifest.json` and `photos-35-archive.tar.gz` (§13.6).
:::

:::{bld} The log's format
:id: BLD-log_format
:status: ruled
:realises: RUL-log_entry_grows, RUL-log_keyed_by_fingerprint, RUL-log_cites_decisions, RUL-log_human_readable, RUL-no_log_entry_for_other

Each log SHALL be pretty-printed JSON with sorted keys, its `photos` keyed by the content fingerprint
(`content_fingerprint`), each entry carrying where each phase left the photo — `prep_path`, written by prep and updated
by every prep run; `geotag_path`, by finalize, its by-dest folder under the name its last final rename gave it;
`library_path`, by merge — and a `journey` of steps, each step naming its `phase` and `action`, a move or rename its
`from` and `to` — the first step's `from` being the photo's path in the dump — and, where a decision caused it, a
`because` naming the decision exactly: a clock offset its `photos-21` cell, with its day where the camera's photos there
span days (`camera_group_time_decisions.<group>@<date>`), or the `photos-22` drift confirmation whose validated offset
replaced it; a timezone its destination's cell; a manual position the photo's pin among `photos-23`'s review items or
the destination's folder fallback, with the destination it was accepted from.
:::

:::{bld} Geotag's steps in the log
:id: BLD-geotag_log_steps
:status: ruled
:realises: RUL-log_entry_grows, RUL-log_records_gps_reverts

Geotag's steps SHALL be `clock_offset_applied` (its `offset_seconds` with an `offset_description` in words, such as
"camera clock 1 h 55 min ahead of UTC"), `resolved_utc`, `timezone_resolved`, `time_written`, `gps_written` (with its
origin, method and, for a manual position, the position it replaced, from the plan), `gps_cleared` (a position geotag
wrote and no longer places, with that position, from the plan, and the method left), `gps_preserved` and `final_rename`,
each naming its `run`; finalize takes them from every executed pass — each superseded `photos-24` whose journal shows it
ran, oldest first, matched by fingerprint — before the current plan's, from the provenance each time write carries
(geotag §31).
:::

:::{bld} The journals and the decisions each execution used are kept
:id: BLD-history_kept
:status: ruled
:realises: RUL-history_retained, RUL-log_cites_decisions

Each run's journal SHALL be kept as its own `journal-<run>.json`, each geotag execution keeping the decision records its
plan depended on, verified by hash, in `executed/<plan id>/`, which a step's `because_record` and
`because_record_sha256` name.
:::

:::{bld} A log that cannot rebuild a journey is marked partial
:id: BLD-partial_log_marked
:status: ruled
:realises: RUL-partial_history_shown

A log whose kept history cannot rebuild a journey SHALL be marked partial: prep marks its log partial and warns when its
history cannot rebuild a journey ({need}`BLD-prep_log_build`); geotag's finalize marks `partial` the entry of a photo carrying geotag's
mark whose own values the workspace never pinned, with a `history_incomplete` step of its own saying why, and names in
the log's `warnings`, the log then `partial`, any pass whose journal is kept but whose plan is missing (geotag §31).
:::

:::{bld} The database: its file and its writers
:id: BLD-workspace_database
:status: ruled
:realises: RUL-one_database, RUL-database_is_record, RUL-database_regions_disjoint, RUL-other_databases_scratch, RUL-finalize_reads_database
:uses: BLD-record_ownership

The workspace database SHALL be SQLite, `photos-00-ingest.db` in `.photos-ingest/`, written by: prep, of the file and
metadata caches (`file_cache`, `metadata_cache`) and their version row (`meta`), through its single-writer path (execute's main
thread); geotag, of the resolved-UTC cache (`resolved_utc_cache`), the values each photo held before geotag first wrote
to it (`original_values`, geotag §24.2); merge, of the library-file fingerprint cache (`library_fingerprint_cache`,
keyed by the library file's absolute path with its size and modification time). Where each photo landed is in merge's
JSON records, not the database. The other databases are scratch, re-derivable and deletable at any time: prep's
plan memo, `photos-00-plan-memo.db` ({need}`BLD-plan_memo`), and geotag's track memo, `photos-00-track-memo.db`.
:::

:::{bld} The database images and how each is captured
:id: BLD-database_images
:status: ruled
:realises: RUL-database_image_each_phase, RUL-database_image_whole, RUL-image_never_working_data, RUL-images_archived, RUL-image_capture_atomic

The images SHALL be `photos-15-prep-ingest.db`, written when prep writes its handoff and log;
`photos-26-geotag-ingest.db`, written by finalize with the complete log; and `photos-35-merge-ingest.db`, written when
merge succeeds, before it re-seals — each captured under the workspace lock by `VACUUM INTO` a `.tmp-` name in the
control directory, checked with `PRAGMA quick_check`, then renamed over the phase's earlier image.
:::

## 13. Merge: the library kept, the workspace sealed

:::{bld} Where merge looks in the library
:id: BLD-merge_collision
:status: ruled
:realises: RUL-library_not_scanned
:uses: BLD-workspace_database

Merge SHALL map each photo by destination to its place under `library_root`, and list only the folders its photos go to
— for the names taken there — and the library's top folder, for temporary copies a crash of its own left (§15).
:::

:::{bld} A library file in the way is fingerprinted, through a cache
:id: BLD-library_file_fingerprinted
:status: ruled
:realises: RUL-collision_by_content, RUL-library_file_read_once, RUL-collision_same_content, RUL-library_file_rechecked_before_removal, RUL-engine_change_is_checked

Where a file is there, merge SHALL fingerprint it — from `library_fingerprint_cache` when its path, size and
modification time match a row taken by this build's photo method under the current, known ImageMagick version,
otherwise by decoding it and storing the row — and compare it with the incoming photo's fingerprint from prep. A file
whose name differs from the target's only in case is such a file: the same content is already present at its name.
Only planning writes these rows; execute fingerprints afresh and writes no row.
:::

:::{bld} A different photo under a taken name takes the next suffix
:id: BLD-collision_suffix
:status: ruled
:realises: RUL-collision_different_content, RUL-merge_suffix_above_highest

An incoming photo whose name is taken by different content SHALL take the shared suffix convention's next free suffix
(§7.2), the library's own name keeping its bare form.
:::

:::{bld} The library's mark
:id: BLD-library_marker
:status: ruled
:realises: RUL-library_known_by_mark, RUL-library_mark_made_by_setup, RUL-library_mark_required

A library SHALL be marked by an empty `.photos-library` file in `library_root`, which `is_library` tests with
`os.path.isfile` and `merge init-library` alone creates, with `O_CREAT|O_EXCL`, leaving one already there as it is
(merge §4).
:::

:::{bld} `validate_merge_config` checks the library's place
:id: BLD-library_root_validated
:status: ruled
:realises: RUL-library_place_checked

`validate_merge_config` SHALL require `merge.library_root` to be non-empty and to resolve to an existing directory that
is neither the workspace nor inside it.
:::

:::{bld} Merge makes a destination's folder as it places a photo
:id: BLD-library_folders_made
:status: ruled
:realises: RUL-library_creates_only_placements

Merge SHALL create a missing destination directory under `library_root` with `os.makedirs` as it places a photo there.
:::

:::{bld} The library lock
:id: BLD-library_lock
:status: ruled
:realises: RUL-library_lock, RUL-library_lock_fail_fast, RUL-library_confirmed_before_lock, RUL-library_lock_holds_only_holder, RUL-library_lock_stale_recovered

The library lock SHALL be `LibraryLock`: an exclusive, non-blocking `flock` on `.photos-merge.lock` in `library_root`,
recording its holder's `pid`, `started_at` and `host` and nothing else, released by the kernel when its process dies,
the file never deleted; merge's `plan`, `dry-run` and `execute` take it after the workspace lock and after the
preflight's `validate_merge_config` and `is_library` checks, and hold it to their end, one that cannot take it stopping
with exit status 1.
:::

:::{bld} Merge's move: one rename, or copy, verify, rename and remove
:id: BLD-merge_move
:status: ruled
:realises: RUL-library_never_altered, RUL-merge_moves, RUL-unplaced_photo_stays, RUL-target_free_at_execute, RUL-collision_same_content

Each photo SHALL move into its place without overwriting it: on the library's own filesystem by a single rename that
refuses an existing name; across filesystems by a copy to a temporary name beside its place, checked byte for byte against
the photo, renamed into the place only if it is still free, the rename made durable, and only then removed from photos
by destination.
A place found taken at execute holding the planned content makes the photo already present; holding other content, it
blocks the photo — the plan's alternative name used only where the plan recorded one.
:::

:::{bld} Merge's journal, and how a re-run resumes
:id: BLD-merge_journal_resume
:status: ruled
:realises: RUL-merge_resumable, RUL-resume_rechecks_library

The journal SHALL record each confirmed photo, a re-run taking a place already holding the planned content,
fingerprinted again, as done, and removing the workspace copy if it remains; a photo whose workspace copy is gone, the
journal confirming it or the plan finding it already present, counts as done only once its place is fingerprinted again
and found to hold it, and is blocked otherwise.
:::

:::{bld} A photo already present is removed once the library's copy is checked
:id: BLD-already_present_removed
:status: ruled
:realises: RUL-merge_moves, RUL-library_file_rechecked_before_removal

A photo already present SHALL be removed from photos by destination after the library's copy is fingerprinted again and
found to hold its content.
:::

:::{bld} The merge summary
:id: BLD-merge_records
:status: ruled
:realises: RUL-merge_records_landing, RUL-nothing_built_from_merge_records, RUL-merge_outcome_recorded
:uses: BLD-archive_manifest, BLD-workspace_database

Merge SHALL write `photos-31-merge-summary.json` on every outcome but a stale plan or a failed precondition: per photo,
grouped by destination, where it landed, whether it was renamed for the library or already present, whether it left
photos by destination, and, blocked, why — with no library path; in total, the photos placed new, renamed, already
present and blocked, the removed the sum of the first three; the status `success`, `partial`, `failed` (every photo
blocked) or `rejected` (a required snapshot not taken, nothing changed); the merge run and plan ids, `library_root`, the
geotag plan and execution ids, the photos it newly moved and those an earlier run had, and the SHA-256 of `photos-24-executable-plan.json`,
`photos-25-execution-summary.json` and `photos-11-handoff.json`; and, apart, the run's times and job count.
:::

:::{bld} What a whole merge writes, and the seal last
:id: BLD-merge_success_sequence
:status: ruled
:realises: RUL-merge_reseals, RUL-seal_on_success_only, RUL-reseal_rederives_nothing

Only on success — every photo placed or already present, none left — SHALL merge then, in order, write
`photos-35-merge-log.json`, `photos-35-merge-ingest.db`, the package's `photos-35-archive-manifest.json` and
`photos-35-archive.tar.gz`, and last the seal.
:::

:::{bld} The seal
:id: BLD-seal_marker
:status: ruled
:realises: RUL-seal_is_authority

The seal SHALL be `photos-00-sealed.json` in the control directory, its own file beside the workspace guard — which only
prep writes — recording `sealed`, the merge run id (`merged_run_id`) and `library_root`; its presence alone seals.
:::

:::{bld} The phases check the seal first
:id: BLD-phases_check_seal
:status: ruled
:realises: RUL-sealed_refuses, RUL-sealed_new_dump_warned, RUL-sealed_new_dump_left

Prep's `plan`, `dry-run` and `execute`, every geotag command, and merge's `plan`, `dry-run` and `execute` SHALL check
the seal under the workspace lock before reading anything else, and stop with exit status 2 if it is there, adding the
likely-new-dump warning when `likely_new_dump` finds an entry at the workspace's top level other than its managed
folders and hidden entries, or anything in the inbox.
:::

:::{bld} The editor checks the seal
:id: BLD-editor_checks_seal
:status: ruled
:realises: RUL-editor_refuses_sealed, RUL-sealed_new_dump_warned, RUL-sealed_new_dump_left

`edit` SHALL refuse to serve a sealed workspace, with the same warning, its save writing nothing there.
:::

:::{bld} `init-library` checks the seal before recording a library
:id: BLD-init_library_checks_seal
:status: ruled
:realises: RUL-sealed_no_library_recorded

`merge init-library` given a path from inside a workspace, which would record it as `library_root` in the configuration,
SHALL check the seal under the lock the same way, and stop with exit status 2 having blessed nothing; without a path, or
from outside any workspace, it writes nothing in the workspace and does not check.
:::

:::{bld} `prune-quarantine` does not check the seal
:id: BLD-prune_ignores_seal
:status: ruled
:realises: RUL-sealed_prune_allowed

`prune-quarantine` SHALL not check the seal.
:::

## 14. Every value the user writes is checked

:::{bld} Where the configuration is checked
:id: BLD-authored_checks_by_phase
:status: ruled
:realises: INV-authored_values_checked, RUL-checked_every_run, RUL-invalid_value_stops, RUL-checked_shapes
:uses: BLD-config_values_checked

`validate_config` SHALL check the configuration each time it is read: by prep as it seeds and reads it, by geotag and
merge as they load it, merge checking besides, with `validate_merge_config`, that `merge.library_root` is an
existing folder neither inside the workspace nor holding it.
:::

:::{bld} Where geotag checks the decisions
:id: BLD-geotag_checks_decisions
:status: ruled
:realises: RUL-checked_shapes, RUL-checked_positions_and_times, RUL-checked_timezones, RUL-invalid_value_stops, RUL-invalid_value_located, RUL-invalid_decision_kept, RUL-invalid_value_never_repaired, RUL-checked_every_run

Geotag SHALL check the decisions in `photos-21`, `photos-22` and `photos-23` as it reads them (geotag §9.2, §20): each
blocker names the artifact, the destination, the cell or the file, and the field, and an artifact holding one is left as
it is, its plan not written. A decision artifact that cannot be read, does not parse as JSON or is not a JSON object is
such a blocker, located to where parsing failed — never taken as absent.
:::

## 15. Nothing overwritten, nothing left half-done

:::{bld} One rename that refuses a taken name
:id: BLD-no_clobber_rename
:status: ruled
:realises: RUL-target_free_at_execute, RUL-operations_atomic, RUL-split_move_never_lost

Every move and rename that carries content SHALL go through `_move_no_clobber`: on one filesystem `renameat2` with
`RENAME_NOREPLACE`, one call that refuses an existing name, or where that is unavailable `os.link` then `os.unlink`;
across filesystems, for merge alone, `_move_cross_fs_no_clobber`. A refused name stops that operation: prep records it
failed and stops; geotag and merge record a blocker and leave the photo where it is. Merge also tests its target before
moving, and geotag compares names ignoring case (geotag §27). The rename that completes an operation is thus itself the
check that its name is free ({need}`RUL-target_free_at_execute`; geotag §29.1a, merge §11).
:::

:::{bld} Each run checks the workspace's devices
:id: BLD-workspace_one_filesystem
:status: ruled
:realises: RUL-workspace_one_filesystem, RUL-one_filesystem_checked_every_run, RUL-spanning_workspace_stops, RUL-spanning_workspace_located

`workspace_volume_breaks` SHALL walk every folder of the workspace without following links, comparing each one's device
with the workspace root's and not descending into a folder found on another; prep's and geotag's `run`, and merge's
plan, dry run, execution and in-workspace `init-library`, call it through `workspace_volume_error` as soon as they hold
the workspace lock and, on a folder found elsewhere, report it and exit 2.
:::

:::{bld} Only merge's moves fall back to a copy
:id: BLD-cross_fs_merge_only
:status: ruled
:realises: RUL-workspace_moves_one_filesystem

`_move_no_clobber` SHALL fall back to a cross-filesystem copy only when its caller passes `cross_fs=True`, which merge
alone does; for prep and geotag the `EXDEV` of a move across filesystems is raised as a failure.
:::

:::{bld} Geotag's metadata writes
:id: BLD-metadata_safe_write
:status: ruled
:realises: RUL-rewrite_in_place_atomic

Geotag SHALL write metadata with `exiftool -overwrite_original`, which writes a temporary file and renames it over the
original, having first removed a `<file>_exiftool_tmp` an interrupted write left (geotag §29.1a).
:::

:::{bld} The cross-filesystem copy
:id: BLD-cross_fs_temp
:status: ruled
:realises: RUL-cross_fs_all_or_nothing, RUL-temp_name_own

`_move_cross_fs_no_clobber` SHALL copy to a `.tmp-xdev-<random>.part` file in the destination directory, check it holds
the source's bytes — the same size, compared byte for byte — sync it, rename it into its place without overwriting, sync
the destination directory, and then remove the source.
:::

:::{bld} Merge's sweep of temporary copies
:id: BLD-temp_sweep
:status: ruled
:realises: RUL-crash_temps_cleared

Merge's `execute` SHALL, after revalidating its plan and taking its snapshot and before its first move, remove every
`.tmp-xdev-*.part` file directly in `library_root` and in each planned target's directory, and record how many in
`photos-31-merge-summary.json` as `run_metadata.orphan_temps_swept`.
:::

:::{bld} Prep's failed operation
:id: BLD-failed_operation
:status: ruled
:realises: RUL-failed_operation_clean, RUL-failure_recorded, RUL-failure_never_done

Prep SHALL journal an operation that raised as `failed`, and stop.
:::

:::{bld} Geotag's failed write
:id: BLD-geotag_failed_write
:status: ruled
:realises: RUL-failed_operation_clean, RUL-failure_recorded, RUL-failure_never_done

Geotag SHALL record a metadata write whose tool failed, or a rename that raised, as failed, confirming neither: a
failed write leaves the file as exiftool found it, a failed rename leaves it under its name.
:::

:::{bld} Merge's failed placement
:id: BLD-merge_failed_placement
:status: ruled
:realises: RUL-failed_operation_clean, RUL-failure_recorded, RUL-failure_never_done

Merge SHALL record a placement that raised as blocked, its photo left in photos by destination.
:::
