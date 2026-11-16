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

:::{bld} The exit statuses
:id: BLD-exit_statuses
:status: ruled
:realises: RUL-exit_status_says_how_it_ended, RUL-blocked_plan_ends_refused

Prep's plan, dry run, execute and `prune-quarantine`, and geotag's and merge's commands, SHALL exit 0 for a run that did what it was
asked; 1 for a workspace or a library found locked; 2 for a refusal — no control directory, the seal, a change in the
workspace no command made and none a person is expected to make, a workspace whose state no execution recorded (geotag's
and merge's), a record of accepted changes it cannot read, a precondition,
a required tool absent, a plan missing, stale or failing its checks, a plan of prep's own it cannot read, a plan or
journal of merge's own it cannot read, a workspace database of another schema, a required snapshot not taken, a
prune's selection refused, and a plan, or a dry run, that reports a blocker; 3 for an execution that ended partial or failed — an operation failed, or
prep's log or handoff not written after its operations; and 130 for an interrupt. An error the build did not foresee
ends a command with 1, as Python ends it. Prep's execute or dry run with nothing to do ends 0. `merge init-library`
ends 0, 1 or 2 alike, and a phase named with no command prints what it does and ends 0.
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
:realises: RUL-every_command_locks, RUL-save_only_what_was_shown

The decision editor's save SHALL take the workspace lock for the time it writes, refusing at once while a run holds it;
the editor's display reads take none, each record being replaced whole. The editor is given, with each record it loads, the SHA-256 of its bytes, and sends them back with a save; under the lock the save compares them with the records on disk and checks that every edit names a decision its record holds, writing none of the records otherwise, and returns the hashes of what it leaves.
:::

:::{bld} The order of the editor's save
:id: BLD-editor_save_order
:status: ruled
:realises: RUL-save_writes_in_order
:uses: BLD-editor_save_locks

The decision editor's save SHALL write, of the records it changes, `photos-21-time-decisions.json`,
`photos-22-gps-drift-validation.json`, `photos-23-gps-decisions.json`, `photos-25-execution-summary.json` and then
`photos-00-config.json`, in that order, each replaced atomically and synced to disk before the next is begun; a write
that fails ends the save there, the records before it written and those after it as they were.
:::

:::{bld} The editor's save keeps the replaced record under `-NNN`
:id: BLD-editor_keeps_replaced_record
:status: ruled
:realises: RUL-save_keeps_the_replaced
:uses: BLD-plan_backups

Before it writes a record whose new bytes differ from those it loaded, the decision editor's save SHALL copy the record
to its next free `-NNN` sibling through `backup_existing_artifact`, the set-aside {need}`BLD-plan_backups` makes, so a
save's copies and a re-plan's are numbered as one series; a record whose bytes would not change is written with nothing
set aside. The configuration, written through `write_json_artifact`, keeps no copy, as merge's `init-library` keeps
none.
:::

:::{bld} Every question is a decision field the editor answers
:id: BLD-editor_answers_every_question
:status: ruled
:realises: RUL-every_question_in_editor, RUL-every_question_answerable_by_hand

Each question geotag asks SHALL be a `user_decision` of a cell of its record, its fields documented in
`cartographer/editor/decision-json-reference.md`, which geotag reads whether the editor or a hand wrote it. The
editor loads and saves each by its kind: in photos-21, `timezone` (`destination_timezone`), `date` (`date_fallback`,
{need}`BLD-date_fallback_cell`), `offset` (a cell of
`camera_group_time_decisions`, a phone's among them, by its key — a day's split where its clock changed answered on the
day's cell, its parts never), `reading` (an entry of `local_time_readings`, by
its photo's path), `changed` (an entry of `changed_times`, by its photo's path) and `unidentified`
(`unidentified_files`); in photos-22, `drift`; in photos-23, `fallback`, `review` and `chosen` (a photo of a
destination's `placed_photos`, by its path: written as its `chosen_by_user` review item, added where it has none —
{need}`BLD-chosen_position`);
in `photos-25-execution-summary.json`, which `geotag execute` reads, `fingerprint` (an entry of `fingerprint_mismatches`,
by its photo's path); and in the configuration a camera group's class, `camera` ({need}`BLD-editor_lists_new_camera_groups`),
and whether a camera group is several bodies, `bodies` ({need}`BLD-editor_marks_several_bodies`).
The editor writes each answer as geotag takes it: where an offset cell lists `conflicts_with`, a proposal the user takes
there is written as `manual_offset_seconds`, the user's own offset, which keeps its effect
({need}`RUL-chosen_offset_not_withheld`) — never as an acceptance, which geotag withholds there again.
:::

:::{bld} The editor's timezone questions, as the working decisions settle them
:id: BLD-editor_zone_asking
:status: ruled
:realises: RUL-editor_answer_ends_zone_asking

The editor SHALL show a timezone cell that requires input as settled once the decisions being edited give it a zone —
a `manual_iana_timezone` written there, a country of one timezone in effect there, or a zone reaching it from the
folders above as geotag passes one down ({need}`BLD-timezone_cell`, {need}`BLD-country_choice`) — and a container's,
once each destination of its `asked_for` is so settled, or it is given a zone itself.
Settled so, a cell whose photos then speak against the zone asks again on the next run.
:::

:::{bld} The editor's own lock, held for its session
:id: BLD-editor_session_lock
:status: ruled
:realises: RUL-one_editor_at_a_time, RUL-editor_kept_until_stopped

The decision editor SHALL take `photos-00-decision-editor.lock`, an exclusive lock taken without waiting that records
its owner, as `edit` opens a workspace, holding it until `edit` stops; the console's Edit tab takes it on its first
request for a workspace and holds it until the console stops. While another holds it, `edit` refuses to start and the
tab refuses to read or save. It is the editor's alone, apart from the workspace lock its saves take
({need}`BLD-editor_save_locks`).
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
or scoping it on its own ({need}`RUL-lock_through_the_run`).
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

The three phases SHALL take their snapshots through one mechanism — prep's execute, geotag's
({need}`BLD-geotag_execution`) and merge's ({need}`BLD-merge_execute`) invoke it, and none redefines it.
:::

## 3. One configuration, kept in the workspace

:::{bld} The configuration is `photos-00-config.json`, in the control directory
:id: BLD-config_file
:status: ruled
:realises: DEF-configuration, RUL-one_configuration, RUL-config_never_media

The configuration SHALL be the JSON file `photos-00-config.json` in the workspace's control directory, `.photos-ingest/`,
which prep skips wholesale ({need}`BLD-prep_skip_set`) — never an in-code global.
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

The setup command `init-library` ({need}`BLD-init_library_cases`), run inside a workspace with an explicit library path,
MAY write the `library_root` key into the configuration, and only that key, writing the file again whole through
`write_json_artifact`: every other setting keeps its value, while the file's layout — the order of its keys, its
indentation, characters beyond ASCII written as escapes — becomes that of the control records. It is not part of
merge's data path.
:::

:::{bld} The editor lists the camera groups geotag stops on
:id: BLD-editor_lists_new_camera_groups
:status: ruled
:realises: RUL-every_question_in_editor
:uses: BLD-known_camera_group

The decision editor SHALL list, as `cameras`, each camera group of the handoff's photos under photos by destination that
`camera_time_and_timezone_policy.device_groups` lists in neither `phones` nor `fixed_clock_cameras`, or in both — the
groups geotag stops on, keyed as geotag keys them (`unclassified_camera_groups`) — with its photos' count and three of
their paths, and a `user_decision.device_class` it answers: `phones` or `fixed_clock_cameras`. Geotag's stop on such a
group still prints the two arrays, to paste in by hand.
:::

:::{bld} The editor writes a new camera group's class into `device_groups`
:id: BLD-editor_writes_device_groups
:status: ruled
:realises: RUL-editor_classes_camera_group, RUL-every_question_answerable_by_hand
:uses: BLD-editor_lists_new_camera_groups, BLD-editor_save_locks

The decision editor's save of a camera group's class SHALL, under the workspace lock and only while the configuration
is the one it loaded, by its SHA-256, put the group in the array named and take it out of the other, refusing unless the
group is still unclassed and the configuration then passes the checks `load_config` makes, and write the file again
whole through `write_json_artifact`, every other setting keeping its value.
:::

:::{bld} The editor names a camera group several bodies in the configuration
:id: BLD-editor_marks_several_bodies
:status: ruled
:realises: RUL-editor_marks_several_bodies, RUL-every_question_in_editor, RUL-every_question_answerable_by_hand
:uses: BLD-several_bodies_groups, BLD-editor_save_locks

The decision editor SHALL list, as `cameras.bodies`, each camera group of the handoff's photos under photos by
destination that `device_groups` classes `fixed_clock_cameras` alone (`camera_groups_of_class`), with its photos' count,
three of their paths and `user_decision.several_bodies` — whether `several_bodies_groups` names it — never requiring
input; its save of one, `kind: "bodies"`, under the workspace lock and only while the configuration is the one it
loaded, by its SHA-256, puts the key into `camera_time_and_timezone_policy.several_bodies_groups` or takes it out,
refusing unless the group is still such a group of the photos, the answer a boolean, and the configuration then passes
the checks `load_config` makes, and writes the file again whole through `write_json_artifact`, every other setting
keeping its value.
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

The whole-file fingerprint SHALL be carried in the `depends_on` of geotag's executable plan
({need}`BLD-geotag_dependencies`) and of merge's plan, `config_fingerprint`, each plan refused when it no longer matches
the file.
:::

:::{bld} The costly caches are keyed on their own areas
:id: BLD-costly_caches_keyed_by_area
:status: ruled
:realises: RUL-costly_results_survive_unrelated_edits, RUL-times_survive_unrelated_config_edits

The costly caches SHALL be keyed on their own areas instead of the whole-file fingerprint: resolved UTC on the
time-policy subset ({need}`BLD-resolved_utc_fingerprint`), the renames on the filename-format fingerprint.
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
:realises: DEF-config_areas, RUL-folder_names_not_roles, RUL-camera_classes_not_derivation, RUL-extension_one_class, RUL-folder_found_by_role, RUL-config_lists_extensions, RUL-unlisted_extension_other, RUL-setting_bounds_one_thing

The areas SHALL be, at least: the `zfs` block and `snapshots_required` ({need}`BLD-snapshot_is_zfs`);
`camera_time_and_timezone_policy.device_groups`, with `phones` and `fixed_clock_cameras` ({need}`DEF-camera_group`), and
`several_bodies_groups` beside it ({need}`BLD-several_bodies_groups`);
`filename_timestamp_format` ({need}`BLD-filename_timestamp_format`); `gpx_root` and the GPX thresholds, such as `gpx_direct_match_max_seconds`,
`gpx_interpolation_max_gap_seconds` and `gpx_anchor_max_point_distance_meters` ({need}`DEF-tracks`), each read for one judgement only; the camera-time policy
flags, such as `single_anchor_auto_apply` and `multi_anchor_auto_apply` (geotag); `library_root`
(merge; {need}`DEF-library`) and `library_space_margin_percent` beside it ({need}`BLD-library_space`); `folders`, a role→name map of the numbered managed folders
`0-sources`…`6-photos-by-dest` ({need}`DEF-managed_folders`), whose code finds each folder by its role; and
`media_extensions`, mapping `image`, `raw` and `video` to lists of canonical extensions — lowercase, no leading dot
({need}`RUL-checked_extension_lists`). `CAMERA_GROUP_KEY_VERSION` is a code constant, never a configuration field.
:::

:::{bld} What validating the configuration checks
:id: BLD-config_values_checked
:status: ruled
:realises: RUL-config_validated_before_use, RUL-checked_paths, RUL-checked_snapshot_names, RUL-checked_filename_format, RUL-checked_numbers

Validating the configuration SHALL check, among others, that a path resolves sanely, that a ZFS snapshot prefix is a
syntactically valid snapshot component, and that an IANA timezone is a real zone.
:::

:::{bld} A filename format reading a zone is refused
:id: BLD-filename_format_zone_checked
:status: ruled
:realises: RUL-filename_format_zone_free
:uses: BLD-authored_checks_by_phase

`validate_config` SHALL refuse a `filename_timestamp_format` that formats one time differently without a zone and with
a UTC offset of +05:30 — one holding `%z`, `%:z` or `%Z` — saying that prep names files from a time without a zone and
geotag from one with a zone; every phase reads the configuration through it before anything else.
:::

## 4. The control records, apart from the media

:::{bld} The control directory's contents
:id: BLD-control_directory_contents
:status: ruled
:realises: DEF-control_records, RUL-control_records_together

The control records SHALL be these files in `.photos-ingest/` ({need}`DEF-archival_package` and {need}`DEF-workspace_database` for the archival and database ones):

```text
.photos-ingest/
  photos-00-config.json            workspace configuration (seeded by prep, BLD-config_file)
  photos-00-workspace.lock         the workspace lock: held by every run while it plans or executes (RUL-lock_through_the_run)
  photos-00-decision-editor.lock   the decision editor's lock: one editor at a time on a workspace
  photos-00-workspace-guard        workspace root sentinel: marks the workspace as INITIALIZED (written last by prep on init)
  photos-00-sealed.json            terminal/sealed marker, written by a successful merge ALONGSIDE the guard (a separate file, not a field inside the guard) — its presence seals the workspace (BLD-seal_marker)
  photos-00-ingest.db              SQLite identity/metadata cache + derived caches (live working DB, BLD-workspace_database)
  photos-00-plan-memo.db           prep-phase scratch: plan memo, what planning read of each media file (disposable, NOT part of the record)
  photos-01-accepted-changes.json  the changes to the workspace the user accepted, each by its code (BLD-accept_changes); an earlier one kept under -NNN
  photos-15-prep-ingest.db         prep-phase artifact: DB backup snapshot, end of prep (BLD-database_images)
  journal-*.json                   execution journals
  photos-10-prep-plan.json         prep-phase artifact: prep plan (written by `plan`, consumed by `dry-run`/`execute`; see "Canonical plan persistence" below)
  photos-11-handoff.json           prep-phase artifact: handoff manifest
  photos-15-prep-log.json          prep-phase artifact: end-of-prep audit log (BLD-prep_log_build)
  photos-16-prune-record.json      prep-phase artifact: what the latest deleting quarantine prune removed, and when (BLD-prune_record)
  photos-21-time-decisions.json    geotag-phase artifact
  photos-22-gps-drift-validation.json  geotag-phase artifact: GPS-drift validation gate (BLD-drift_validation)
  photos-23-gps-decisions.json     geotag-phase artifact
  photos-24-executable-plan.json   geotag-phase artifact
  photos-25-execution-summary.json geotag-phase artifact
  photos-26-complete-log.json      geotag-phase artifact: full transformation log (prep+geotag, at finalize, BLD-phase_logs)
  photos-26-geotag-ingest.db       geotag-phase artifact: DB backup snapshot, end of geotag (BLD-database_images)
  photos-26-finalized-media.json   geotag-phase artifact: each by-dest photo's size and mtime as finalize found it
  photos-26-archive-manifest.json  geotag-phase artifact: the archival package's manifest, at finalize (BLD-archive_manifest)
  photos-26-archive.tar.gz         geotag-phase artifact: the archival package, at finalize (BLD-archive_manifest)
  photos-30-merge-plan.json        merge-phase artifact: merge plan (written by `plan`, consumed by `dry-run`/`execute`)
  photos-31-merge-summary.json     merge-phase artifact: library-merge summary (BLD-merge_records)
  photos-35-merge-log.json         merge-phase artifact: full transformation log (prep+geotag+merge, BLD-phase_logs)
  photos-35-fingerprint-map.json   merge-phase artifact: each fingerprint another ImageMagick changed, old value to new (BLD-fingerprint_map)
  photos-35-merge-ingest.db        merge-phase artifact: DB backup snapshot, end of merge (BLD-database_images)
  photos-35-archive-manifest.json  merge-phase artifact: the re-sealed package's manifest, superseding photos-26's (BLD-merge_success_sequence)
  photos-35-archive.tar.gz         merge-phase artifact: the re-sealed archival package (BLD-merge_success_sequence)
  executed/<plan id>/              geotag: the decision records each executed plan ran against (BLD-history_kept)
  <artifact>-NNN.<ext>             a superseded plan or decision record, kept when it was replaced (BLD-plan_backups)
  gpx/                             gpx_root, when configured to live here (BLD-gpx_root)
```

The ids in it name the items that govern each entry.
:::

:::{bld} An artifact's first digit names the phase that made it
:id: BLD-artifact_numbering
:status: ruled
:realises: DEF-control_records

The numbered artifacts SHALL follow this scheme:

```text
0X  workspace infrastructure (phase-neutral): config, guard, live database
1X  prep-phase artifacts        (currently: 10 = prep plan, 11 = handoff, 15 = prep audit log + prep DB snapshot, 16 = prune record)
2X  geotag-phase artifacts        (currently: 21–26; 26 = complete log + geotag DB snapshot + archive manifest)
3X  merge-phase artifacts        (currently: 30 = merge plan, 31 = merge summary, 35 = merge log + fingerprint map + merge DB snapshot + archive manifest)
```

The first digit means only the producing phase. The second is a sequence number within the phase with no
further meaning: an absent number is not reserved, not headroom and not missing, and nothing is to be inferred from a
gap. Sibling end-of-phase records that differ only by extension MAY share a number — `photos-15-prep-log.json` and
`photos-15-prep-ingest.db` are both the end-of-prep record, one the human-readable log and one the database image;
likewise `photos-26-complete-log.json`, `photos-26-geotag-ingest.db` and `photos-26-archive-manifest.json`, and the
`photos-35` files. The full filename — number, name and
extension — is the identifier, never the number alone; `photos-0X-*` (and `1X`, `2X`, `3X`) names a band. The
bands are unrelated to the numbered media folders `0-sources`…`6-photos-by-dest`.
:::

:::{bld} What prep skips
:id: BLD-prep_skip_set
:status: ruled
:realises: RUL-not_inventoried, RUL-control_records_never_media, RUL-config_never_media, DEF-strays_folder, RUL-strays_never_processed, RUL-hidden_folder_among_photos_blocks, RUL-user_backup_is_a_stray

Prep SHALL skip `.photos-ingest/`, `.photos-ingest-quarantine/` and `.git` as whole subtrees, every dot-prefixed file,
and the strays folder `1-strays/` with all its `<plan-id>` subfolders ({need}`BLD-strays_per_run`), the strays of a run
going to `1-strays/<plan-id>/`. A hidden folder in a managed folder other than `0-sources` is not read, and one holding any file — a link counted — is a blocker naming it; a file named `<media name>_exiftool_tmp` is the one leftover of a write prep recognises, `<media name>_original` being a file of no media class like any other.
:::

:::{bld} Hidden files in a dump go to the quarantine
:id: BLD-dump_dotfiles_quarantined
:status: ruled
:realises: RUL-dump_hidden_files_quarantined

Hidden dotfiles in a dump area SHALL be swept to the quarantine ({need}`BLD-quarantine_layout`).
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
:realises: RUL-replanning_keeps_the_prior, RUL-record_in_place_while_replaced

A differing re-plan SHALL first copy the existing artifact to the shared incremental `-NNN` suffix ({need}`BLD-name_suffix`) —
`photos-10-prep-plan-001.json`, say, the copy landing under that name only whole — then replace the artifact atomically,
and announce where. A plan carrying a fresh plan id differs every run, so
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
geotag's dependency block ({need}`BLD-geotag_dependencies`). Its whole-file SHA-256 is kept as an integrity and archival
hash ({need}`DEF-archival_package`), never the dependency check.
:::

:::{bld} The workspace's top level
:id: BLD-top_level_entries
:status: ruled
:realises: RUL-top_level_only_managed, RUL-first_dump_at_top_level, RUL-structure_built_once, RUL-only_prep_builds_structure

The top level of an initialized workspace SHALL hold exactly the managed folders `0-sources`…`6-photos-by-dest` and
`.photos-ingest/`, `.photos-ingest-quarantine/`, `.git` and other dotfiles and dot-directories, the inbox being
`0-sources/`. Prep applies the guard, geotag at startup ({need}`RUL-shape_checked_first`), merge in its preflight
({need}`BLD-merge_preflight`).
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
:realises: RUL-no_links, RUL-who_checks_for_links, RUL-missing_folder_blocks, RUL-shape_checked_first, RUL-link_named, RUL-geotag_merge_check_links, RUL-missing_folder_named, RUL-empty_inbox_normal

Links: prep across the tree it walks ({need}`RUL-who_checks_for_links`); geotag and merge at the workspace root and
throughout `6-photos-by-dest` at startup, by a walk that follows nothing and reads no file
({need}`RUL-geotag_merge_check_links`), and through the handoff for the rest. Missing managed folders: prep, geotag and merge alike ({need}`RUL-missing_folder_blocks`).
:::

## 5. Camera groups, derived once

:::{bld} `camera_group_key` and its version
:id: BLD-camera_group_key
:status: ruled
:realises: DEF-camera_group, RUL-prep_derives_camera_group, RUL-geotag_reuses_camera_group

The key SHALL be `camera_group_key`, computed by prep from the serial, make, model and owner fields and emitted in both
the handoff manifest and SQLite ({need}`BLD-metadata_extraction`); geotag consumes and classifies it
({need}`BLD-known_camera_group`).
:::

:::{bld} Blank identity values
:id: BLD-camera_identity_values
:status: ruled
:realises: RUL-prep_derives_camera_group, RUL-unidentified_files_solved_alone
:uses: BLD-camera_group_key

Each identity field a file holds — `BodySerialNumber`, `CameraSerialNumber`, `InternalSerialNumber`, `SerialNumber`,
`Make`, `Model`, `OwnerName`, in that order — SHALL enter `camera_group_key` as its value's text with the blanks
around it stripped, the parts joined by `|`: a blank value is an empty part, so a file whose only identity fields are
blank has a key of empty parts (`""`, `"|"`, …), a camera group like any other; only a file holding none of them has
`NO_IDENTITY_KEY` (`unknown`) — and one whose only field reads `unknown`, which is then taken for a file naming no
camera ({need}`BLD-unidentified_files`).
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
:realises: RUL-geotag_name_final, RUL-names_local_in_repeated_hour

Geotag SHALL compute the final name as resolved UTC → the destination's civil timezone → a local naive datetime → the
format. Two instants of the hour a zone repeats give one local time, and the name is that local time for both.
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
:realises: RUL-misnamed_file_stops_prep, RUL-misnamed_file_named, RUL-set_aside_jpeg_named_as_raw

At plan, prep SHALL check the name of every media file in the dated, missing-metadata, redundant-JPG and by-destination
folders: without its extension and `-NNN` suffix, it is the file's recorded time ({need}`RUL-recorded_time_order`)
formatted by `filename_timestamp_format`, or starts with `UNKN_` for a file with no recorded time and for every file in
the missing-metadata folder. A dated file with no recorded time is moved to the missing-metadata folder instead, and the
strays folder is not checked. A JPEG in the redundant-JPG folder whose name without its extension is that of the raw
file its prep log names ({need}`BLD-set_aside_pair_recorded`), found by its fingerprint, is rightly named.
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
out of the scan. Geotag catalogues every `*.gpx` file beneath it ({need}`BLD-track_catalogue`). The value and the matching thresholds are read by geotag;
their detail is {need}`BLD-track_points` and {need}`BLD-anchor_matching`.
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

Prep SHALL raise one blocker for each track file it inventories, naming it, and leave it out of the plan
({need}`RUL-track_files_block_prep`); execute raises the same blocker for one that appeared after planning
({need}`RUL-new_file_restales_plan`).
:::

:::{bld} The GPX fingerprint
:id: BLD-gpx_fingerprint
:status: ruled
:realises: RUL-tracks_in_dependencies

The GPX fingerprint SHALL be a SHA-256 over a version tag, the ranking of the tracks, and every point in the tracks'
window ({need}`BLD-track_window`), in time order, each with its time, position, file under `gpx_root`, index, track and
segment — so a track file's bytes outside the window, and the root's own path, enter it not at all. An empty
`gpx_root`, a `gpx_root` that is not a directory, and one with a folder that cannot be listed, each give a fixed value
of their own, the last two with a warning. It is recorded as `gpx_fingerprint` in the
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
:realises: DEF-fingerprint, RUL-fingerprint_survives_mutation, RUL-fingerprint_covers_every_frame, RUL-fingerprint_covers_every_stream

A photo's fingerprint SHALL be ImageMagick's signature — a SHA-256 of the normalized pixel stream — of its one frame, or, of a file of several frames, the SHA-256 of every frame's signature, one to a line, in order, the same whichever of the two ways of running ImageMagick took it; a video's, the `ffmpeg` MD5 of all its streams as stored, copied out without decoding (`-map 0 -c copy -copy_unknown`).
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
:realises: RUL-prep_records_sort, RUL-sort_recorded_by_stat, RUL-geotag_plans_on_current_record, RUL-auto_reprep_moves_no_media

When the only change prep has not recorded is one {need}`BLD-reprep_pending` names and the inbox is empty, `geotag
plan` SHALL run prep's `plan` and `execute` itself, inside its own lock, saying so, before it plans. Between the two it reads the plan prep saved and, where that holds a move, a rename or a quarantine of a media file, runs no execute: it stops, the plan left for the user to inspect and carry out.
:::

:::{bld} What prep has yet to record
:id: BLD-reprep_pending
:status: ruled
:realises: RUL-prep_records_sort, RUL-geotag_plans_on_current_record

`by_dest_reprep_pending` SHALL name, from sizes and modification times alone, a photo in photos by destination the
handoff does not record at its path, one the handoff records in photos by date or by destination that is gone, or one
it records in photos by destination whose size or `mtime_ns` differs from its record: `geotag plan` stops on it with
the one re-prep blocker, and runs prep itself when {need}`BLD-geotag_auto_reprep` allows; prep's nothing-to-do guard
does not stop while it names one. It reads no hidden folder, as prep reads none; one holding a file it names itself, so that prep is run and stops on it ({need}`RUL-hidden_folder_among_photos_blocks`).
:::

:::{bld} Where the loop's gates are checked
:id: BLD-loop_gates
:status: ruled
:realises: RUL-geotag_gates, RUL-sort_photos_only, RUL-development_after_merge, RUL-unfingerprinted_photo_stops_geotag

The gates SHALL be checked as follows: `geotag plan` checks every gate; `geotag execute` and `finalize` check the
development gate and the workspace's shape, and validate against the plan's own dependencies instead of the scope and
re-prep gates ({need}`RUL-geotag_gates`, {need}`BLD-reprep_pending`); merge's preflight checks the inbox, the
development gate and that photos by destination holds only photos ({need}`BLD-merge_preflight`). A development subfolder
is one named in `destination_distribution_subfolders`. Geotag's preflight stops as well on a photo in `6-photos-by-dest` whose handoff record holds no fingerprint, named.
:::

:::{bld} A development subfolder's name, case folded
:id: BLD-development_subfolder_case
:status: ruled
:realises: RUL-development_subfolder_any_case
:uses: BLD-loop_gates

Geotag's and merge's preflights SHALL take a folder under `6-photos-by-dest` for a development subfolder when its name,
case folded, is one of `destination_distribution_subfolders`, case folded.
:::

:::{bld} Geotag marks what it wrote
:id: BLD-rerun_recognition
:status: ruled
:realises: RUL-geotag_rerun_keeps_settled, RUL-position_carries_its_method, RUL-only_corrected_time_marked

Geotag SHALL record what it wrote in the file's `GPSProcessingMethod`: the bare value beside each position it writes —
`matched`, `interpolated` or `extrapolated` for one from the tracks, within the direct-match window of a track point,
between two or past a track's end, `manual_locked` or `manual_fallback` for one the user set — and, on a photo whose
time it writes — a `metadata_time_write` in the plan — or whose field already carries its mark from an earlier run, and
to which it writes no position, the suffix `+carto-time` appended once to whatever the field held, keeping the device's
own value. A photo whose time is resolved to what it holds, with no mark, gets no suffix; with no position written
either, no `gps_marker_write` is planned for it but one clearing a no-fix position. Any other value is the device's own,
and the GPS beside it native.
:::

:::{bld} A file's own values are pinned before geotag first writes it
:id: BLD-original_values_pinned
:status: ruled
:realises: RUL-geotag_rerun_keeps_settled

Before geotag's first write to a file, execution SHALL pin its own recorded time, its `DateTimeOriginal` and
`CreateDate` with their offset tags, its position and `GPSProcessingMethod` in an original-values ledger keyed by
fingerprint, once, unless it already carries geotag's mark; a later plan decides about a pinned file from those values
and plans only the writes that differ from what it holds ({need}`BLD-decided_from_own_values`).
:::

:::{bld} The times geotag writes are recorded beside the pin
:id: BLD-time_written_recorded
:status: ruled
:realises: RUL-changed_time_stops_plan
:uses: BLD-original_values_pinned

Before it writes a time to a file whose own values are pinned, execution SHALL record the `DateTimeOriginal` and
`OffsetTimeOriginal` it writes beside the pin in the original-values ledger, keeping every one it has recorded there,
so a write interrupted after it landed is known as geotag's own.
:::

:::{bld} A plan stops on a time changed since geotag wrote it
:id: BLD-changed_time_blocks
:status: ruled
:realises: RUL-changed_time_stops_plan
:uses: BLD-time_written_recorded

The executable plan SHALL be `blocked` by a file with pinned values whose `DateTimeOriginal` and `OffsetTimeOriginal`
are neither the pinned pair — the true time the ledger keeps for it, where it keeps one
({need}`BLD-changed_time_kept_pinned`) — nor one the ledger records geotag writing, and whose question photos-21 holds no answer to
in effect ({need}`BLD-changed_time_question`), its blocker naming the file, the pair it holds, the last pair geotag wrote
to it — or that geotag wrote it no time — and its pinned pair; a file with no pin is not checked, and only those two
fields are compared.
:::

:::{bld} photos-21 asks of each changed time, by its photo
:id: BLD-changed_time_question
:status: ruled
:realises: RUL-changed_time_asked, RUL-every_question_answerable_by_hand
:uses: BLD-changed_time_blocks

Each file such a pair blocks SHALL be asked about in photos-21, in its destination's `changed_times` keyed by its path:
the cell names its `content_fingerprint`, its `held_time`, the last pair geotag wrote (`geotag_wrote`, or null) and its
`own_time` — the pinned pair, or the true time kept for it — and asks `user_decision.keep` — `new`, keep the time it holds, or `geotag`, take back geotag's —
with `answered_for`, the `held_time` it is given for. The answer is found again by the file's fingerprint and is in
effect (`effective_answer`) while `answered_for` is the pair the file holds, and, for `new`, while that pair holds a
time; another `keep`, or an answer with no `answered_for`, is a blocker; one given for another pair is
`stale_user_decision`. While a cell has no answer in effect it requires input, and photos-21 is not complete.
:::

:::{bld} A time kept is resolved by its destination's zone
:id: BLD-changed_time_kept
:status: ruled
:realises: RUL-changed_time_kept_is_true
:uses: BLD-changed_time_question, BLD-resolved_utc, BLD-local_time_readings, BLD-other_time_fields_written

A file whose answer in effect is `new`, or whose pin keeps a true time ({need}`BLD-changed_time_kept_pinned`), SHALL
be resolved from that pair's `DateTimeOriginal`, its recorded time, read by its destination's timezone
(`kept_true_time`) and by no cell's offset — a time the zone skips or repeats asked in `local_time_readings` as any
time the zone reads — its time write, that time with the zone's offset and its other time fields, planned as any
corrected time's.
:::

:::{bld} A time kept is left out of the clock's evidence
:id: BLD-changed_time_kept_not_anchor
:status: ruled
:realises: RUL-kept_time_not_clock_evidence
:uses: BLD-changed_time_kept, BLD-offset_buckets

A file resolved from a kept true time SHALL be left out, as a time geotag corrected is, of the photos its camera
group's offset cells are built from — anchors, fix times and recorded offsets — and of the drift check, of the photos
set against its destination's timezone, of the unreadable offset tags and of the question of files naming no camera.
:::

:::{bld} A kept time's offset tag that its zone does not give
:id: BLD-changed_time_kept_tag_noted
:status: ruled
:realises: RUL-kept_time_tag_disagreement_told, RUL-kept_time_tag_disagreement_recorded
:uses: BLD-changed_time_question

Each `changed_times` cell whose `held_time` holds a time and an `OffsetTimeOriginal` that is an offset, and whose
destination's timezone gives another at that time — neither of its two, at a time it skips or repeats — SHALL hold
`offset_tag_disagrees`: `recorded_offset_seconds`, `timezone` and `timezone_offsets_seconds`; `geotag plan` warns of
each after writing photos-21. Kept, the time is read by the zone still.
:::

:::{bld} A time kept is recorded beside the pin at execution
:id: BLD-changed_time_kept_pinned
:status: ruled
:realises: RUL-changed_time_kept_is_true
:uses: BLD-changed_time_kept, BLD-original_values_pinned

The executable plan SHALL carry each kept pair, with its file's `content_fingerprint`, under `true_times_kept` by the
file's path, which execution writes into the file's pin in the original-values ledger as its `true_time` before any
write, while the file still holds that pair, the pinned own values staying — so every later plan resolves the file
from it, and asks nothing of the file holding it or a pair geotag wrote.
:::

:::{bld} A time taken back is planned like any other
:id: BLD-changed_time_restored_written
:status: ruled
:realises: RUL-changed_time_restored
:uses: BLD-changed_time_question, BLD-decided_from_own_values

A file whose answer in effect is `geotag` SHALL be planned as before the change — from its pinned values, or the true
time its pin keeps — its time write planned over the pair it holds as any write that differs from what a file holds.
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
destination's local time, a file already so named getting no rename ({need}`BLD-rename_planning`,
{need}`BLD-rerun_recognition`).
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
leaving everything that depends on it as it is — keeps each decision whose target is unchanged
({need}`RUL-decision_kept`), and reads only a track file new or changed since the catalogue recorded it, or one the
tracks' window has grown into, taking the rest from the points the catalogue keeps ({need}`BLD-track_catalogue`); merge, a library file's fingerprint while its size and
modification time are unchanged ({need}`BLD-library_file_fingerprinted`). Fingerprinting (ImageMagick `identify`,
`ffmpeg`), metadata extraction (`exiftool`) and GPX parsing thus run only for new or changed inputs. Each phase's own
consequences are in its spec:
{need}`RUL-no_op_run`, {need}`RUL-geotag_execution_resumable` and {need}`RUL-merge_resumable`.
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
file already in place, geotag plans no write a file already holds and recomputes an already-final name to itself
({need}`BLD-rename_planning`, {need}`BLD-rerun_writes_only_differences`), and merge records a photo already in the
library as already present ({need}`RUL-collision_same_content`).
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
created by geotag and preserved across regeneration ({need}`RUL-decision_stage_writes_record`,
{need}`RUL-decision_kept`), the decision editor writing only those fields.
:::

:::{bld} How a change is traced to its decision
:id: BLD-change_traced
:status: ruled
:realises: RUL-cause_locatable, RUL-decision_revisable

A change SHALL be traced from its decision record through the `depends_on` fingerprints ({need}`DEF-dependency_cascade`)
to the executable plan and the run's journal ({need}`BLD-prep_journal`; {need}`BLD-geotag_dependencies`,
{need}`BLD-geotag_execution`). Merge takes no decision; its placement is a fixed rule over recorded inputs, recorded the
same way ({need}`BLD-merge_journal_resume`, {need}`BLD-merge_records`).
:::

:::{bld} Every plan decides from a photo's own values
:id: BLD-decided_from_own_values
:status: ruled
:realises: RUL-withdrawal_undoes, RUL-decision_revisable

Every plan SHALL decide about a photo from its own values, pinned before geotag first wrote to it
({need}`BLD-original_values_pinned`), so a withdrawn manual position is undone like any decision: the photo is placed
again, or geotag's position cleared; an
automatic position is recomputed, never rolled back.
:::

## 12. The record of what was done, kept beyond the workspace

:::{bld} The per-phase logs
:id: BLD-phase_logs
:status: ruled
:realises: RUL-record_whole_each_phase, RUL-carry_forward_by_copy

Each phase SHALL write its log: prep `photos-15-prep-log.json` at the end of every prep run ({need}`BLD-prep_log_build`); geotag's
finalize copies it to `photos-26-complete-log.json` and appends each photo's geotag steps
({need}`BLD-geotag_log_steps`); merge copies that to `photos-35-merge-log.json` and appends its own.
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
the configuration, which `init-library` may later extend by `library_root` alone
({need}`BLD-init_library_writes_library_root`) and the decision editor by a camera group's class alone
({need}`BLD-editor_writes_device_groups`), and prep writes the database's cache and identity rows while geotag and
merge write only their own regions of it ({need}`BLD-workspace_database`). Bundling copies of every phase's records into
the archival package reads them, and is no write.
:::

:::{bld} The package: the control directory, archived with its manifest
:id: BLD-archive_manifest
:status: ruled
:realises: RUL-finalize_non_destructive, RUL-package_contents, RUL-package_self_describing

`geotag finalize` SHALL write `photos-26-complete-log.json` and the database snapshot `photos-26-geotag-ingest.db`, then
list every file of the control directory but the transient ones — locks, `.tmp-` files, SQLite's `-journal` files, the
plan memo `photos-00-plan-memo.db`, and any `*-archive.tar.gz` or its `-NNN` copy — with its SHA-256 and path in
`photos-26-archive-manifest.json`, recording the workspace's identity — the init run id prep wrote in the guard — with
the folder's name beside it, and the plan and execution ids, and archive those files and the manifest into
`photos-26-archive.tar.gz` in the control directory, by a temporary name and an atomic rename — writing nothing else,
and requiring a ready plan whose execution succeeded ({need}`BLD-finalize_preconditions`). Merge's re-seal does the same
into `photos-35-archive-manifest.json` and `photos-35-archive.tar.gz` ({need}`BLD-merge_success_sequence`).
:::

:::{bld} Merge's package manifest
:id: BLD-merge_archive_manifest
:status: ruled
:realises: RUL-package_self_describing, RUL-merge_reseals
:uses: BLD-archive_manifest

`photos-35-archive-manifest.json` SHALL hold `artifact_type` `archive_manifest`, its `artifact_name`, `schema_version`
1, the workspace's folder name as `workspace` and its identity as `workspace_id`, the merge plan's `plan_id`, the merge
run's id as both `execution_id` and `merge_run_id`, `supersedes` naming `photos-26-archive-manifest.json`, `contents` —
each file it lists keyed by its path in the control directory, with its path in the workspace (`path`) and its
`sha256` — and `run_metadata.generated_at`, the merge run's start.
:::

:::{bld} The log's format
:id: BLD-log_format
:status: ruled
:realises: RUL-log_entry_grows, RUL-log_keyed_by_fingerprint, RUL-log_cites_decisions, RUL-log_human_readable, RUL-no_log_entry_for_other

Each log SHALL be pretty-printed JSON with sorted keys, every step naming its `run`, its `photos` keyed by the content fingerprint
(`content_fingerprint`), each entry carrying where each phase left the photo — `prep_path`, written by prep and updated
by every prep run; `geotag_path`, by finalize, its by-dest folder under the name its last final rename gave it;
`library_path`, by merge — and a `journey` of steps, each step naming its `phase` and `action`, a move or rename its
`from` and `to` — the first step's `from` being the photo's path in the dump — and, where a decision caused it, a
`because` naming the decision exactly: a clock offset its `photos-21` cell, with its day where the camera's photos there
span days (`camera_group_time_decisions.<group>@<date>`), or the `photos-22` drift confirmation whose validated offset
replaced it; a time kept as the true time its entry of the destination's `changed_times`
(`changed_times[<path>]`); a time a date fallback gave the `date_fallback` cell of the destination it was written at;
a timezone its destination's cell; a manual position the photo's pin among `photos-23`'s review items or
the destination's folder fallback, with the destination it was accepted from.
:::

:::{bld} Geotag's steps in the log
:id: BLD-geotag_log_steps
:status: ruled
:realises: RUL-log_entry_grows, RUL-log_records_gps_reverts, RUL-log_records_time_replaced, RUL-log_records_other_times_replaced, RUL-log_records_null_island_replaced

Geotag's steps SHALL be `clock_offset_applied` (its `offset_seconds` with an `offset_description` in words, such as
"camera clock 1 h 55 min ahead of UTC"), `resolved_utc`, `timezone_resolved`, `time_written` (with its `writes`, the
`pre_state` it replaced — the value each field it writes held — the field `read_from` and the `rule`, from the plan),
`true_time_kept` (the time the user kept as the photo's true time, its `value`, from the plan's `true_times_kept`),
`date_fallback_applied` (the date fallback that gave a photo with no recorded time its time: its `value` as the user
wrote it, the day it was `filled` to and the cell it was written in as `because`, from the time write's provenance),
`gps_written` (with its
origin, method and, for a manual position or one written over a position the device wrote that is none of the photo's
own, the `pre_state` it replaced, from the plan), `gps_cleared` (a position geotag
wrote and no longer places, with that position, from the plan, and the method left), `gps_preserved` and `final_rename`,
each naming its `run`; finalize takes them from every executed pass — each superseded `photos-24` whose journal shows it
ran, oldest first, matched by fingerprint — before the current plan's, from the provenance each time write carries.
:::

:::{bld} Merge's step in the log
:id: BLD-merge_log_steps
:status: ruled
:realises: RUL-log_entry_grows, RUL-log_step_names_run, RUL-merge_records_landing
:uses: BLD-log_format, BLD-phase_logs

Merge SHALL append to the `journey` of each photo it placed or found already in the library one step: `phase`
`merge`; its `run`, the merge plan that placed it — the earlier one for a photo a re-plan carried forward
({need}`BLD-merge_carry_forward`); `action` `placed`, or `already_present`; `from`, its path in photos by destination;
`library_path`, its place in the library; and `renamed_for_library`, whether it took a name of its own there — setting
the entry's `library_path` to the same place.
:::

:::{bld} The journals and the decisions each execution used are kept
:id: BLD-history_kept
:status: ruled
:realises: RUL-history_retained, RUL-log_cites_decisions, RUL-prep_journal_kept

Each plan's journal SHALL be kept as its own `journal-<plan id>.json` — prep's, where the plan is executed again,
first copied to the next free `journal-<plan id>-NNN.json` (`backup_existing_artifact`) — each geotag execution keeping the decision records its
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
the log's `warnings`, the log then `partial`, any pass whose journal is kept but whose plan is missing.
:::

:::{bld} The database: its file and its writers
:id: BLD-workspace_database
:status: ruled
:realises: RUL-one_database, RUL-database_is_record, RUL-database_regions_disjoint, RUL-other_databases_scratch, RUL-finalize_reads_database
:uses: BLD-record_ownership

The workspace database SHALL be SQLite, `photos-00-ingest.db` in `.photos-ingest/`, written by: prep, of the file and
metadata caches (`file_cache`, `metadata_cache`) and their version row (`meta`), through its single-writer path (execute's main
thread); geotag, of the resolved-UTC cache (`resolved_utc_cache`), the values each photo held before geotag first wrote
to it and the times geotag wrote to it (`original_values`, {need}`BLD-original_values_pinned`,
{need}`BLD-time_written_recorded`), and the catalogue of the tracks with the points kept and the tracks each executed plan
used (`gpx_track_files`, `gpx_track_points`, `gpx_track_use`, {need}`BLD-track_catalogue`); merge, of the library-file fingerprint cache
(`library_fingerprint_cache`, keyed by the library file's absolute path with its size and modification time); and every
execution, of the record of the state it leaves the workspace's files in (`workspace_record`, named by
`meta.workspace_record_id`, {need}`BLD-workspace_record`). Where each
photo landed is in merge's
JSON records, not the database. The other database is scratch, re-derivable and deletable at any time: prep's
plan memo, `photos-00-plan-memo.db` ({need}`BLD-plan_memo`).
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
— for the names taken there — and the library's top folder, for temporary copies a crash of its own left
({need}`BLD-temp_sweep`).
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

:::{bld} A different photo under a taken name takes the suffix above the highest
:id: BLD-collision_suffix
:status: ruled
:realises: RUL-collision_different_content, RUL-merge_suffix_above_highest

An incoming photo whose name is taken by different content SHALL take, in the shared suffix convention
({need}`BLD-name_suffix`), the suffix one above the highest its name's root carries — the root its own name less any
`-NNN` it already carries — among the names in its library folder and those of every incoming photo bound for that
folder, passing over one taken there without regard to case; the library's own name keeps its bare form.
:::

:::{bld} One library file is compared per photo
:id: BLD-one_library_file_compared
:status: ruled
:realises: RUL-collision_by_content

Merge SHALL compare one library file with each photo: the one under the photo's own name where there is one, otherwise
the first, in sorted order, of those whose names differ from it only in case — so that a photo the library holds under
another of those names is not found there, and takes a name of its own beside it.
:::

:::{bld} The library's mark
:id: BLD-library_marker
:status: ruled
:realises: RUL-library_known_by_mark, RUL-library_mark_made_by_setup, RUL-library_mark_required

A library SHALL be marked by an empty `.photos-library` file in `library_root`, which `is_library` tests with
`os.path.isfile` and `merge init-library` alone creates, with `O_CREAT|O_EXCL`, leaving one already there as it is.
:::

:::{bld} `validate_merge_config` checks the library's place
:id: BLD-library_root_validated
:status: ruled
:realises: RUL-library_place_checked, RUL-library_outside_every_workspace

`validate_merge_config` SHALL require `merge.library_root` to be non-empty and to resolve to an existing directory that is neither the workspace nor inside it; `library_workspace_error`, called by merge's preflight and by every `init-library` that blesses, refuses one that is a workspace, lies inside one — any folder above it holding a `.photos-ingest` directory, initialized or not — or holds one among its immediate folders.
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

The journal — one per plan, `journal-<plan id>.json`, a later execute of the same plan carrying the earlier's
confirmations into it and writing it again whole with each of its own, `updated_at` that execute's start — SHALL record
each confirmed photo, a re-run taking a place already holding the planned content, fingerprinted again, as done, and
removing the workspace copy if it remains; a photo whose workspace copy is gone counts as done only once its place is
fingerprinted again and found to hold it, and is blocked otherwise — the journal is the record of what ran, never what
decides it.
:::

:::{bld} A photo already present is removed once the library's copy is checked
:id: BLD-already_present_removed
:status: ruled
:realises: RUL-merge_moves, RUL-library_file_rechecked_before_removal, RUL-same_pixels_other_file_blocks

A photo already present SHALL be removed from photos by destination after the library's copy is fingerprinted again and
found to hold its content. Its bytes are compared with the workspace copy's first, on every path that removes one: a library file of the same fingerprint and other bytes blocks the photo, the plan's record carrying `library_match` (`bytes` or `pixels`) and, for a block, `same_picture` — the two paths and their sizes.
:::

:::{bld} The merge summary
:id: BLD-merge_records
:status: ruled
:realises: RUL-merge_records_landing, RUL-nothing_built_from_merge_records, RUL-merge_outcome_recorded, RUL-merge_summary_only_for_execution
:uses: BLD-archive_manifest, BLD-workspace_database

Merge SHALL write `photos-31-merge-summary.json` when its execute ends — `success`, `partial` or `failed` — or refuses
for a required snapshot, and on no other outcome: not for a failed precondition, a plan missing, unreadable or stale,
a journal unreadable, or an interrupt, the file then left as it was. It holds, per photo,
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
:realises: RUL-merge_reseals, RUL-seal_on_success_only, RUL-reseal_rederives_nothing, RUL-empty_merge_seals

Only on success — every photo placed or already present, none left, a plan of no photo among them — SHALL merge then,
in order, write `photos-35-merge-log.json`, `photos-35-fingerprint-map.json`, `photos-35-merge-ingest.db`, the package's
`photos-35-archive-manifest.json` and `photos-35-archive.tar.gz`, and last the seal.
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
:realises: RUL-checked_shapes, RUL-checked_positions_and_times, RUL-checked_timezones, RUL-invalid_value_stops, RUL-invalid_value_located, RUL-invalid_decision_kept, RUL-invalid_value_never_repaired, RUL-checked_every_run, RUL-unknown_decision_field_refused

Geotag SHALL check the decisions in `photos-21`, `photos-22` and `photos-23` as it reads them: each blocker names the
artifact, the destination, the cell or the file, and the field, and an artifact holding one is left as
it is, its plan not written. A decision artifact that cannot be read, does not parse as JSON or is not a JSON object is
such a blocker, located to where parsing failed — never taken as absent. So is a `photos-23` review item's
`user_decision` holding a field other than `manual_lat` and `manual_lon` (`unknown_review_fields`), one blocker per
field, naming it; the decision editor shows such a `photos-23` as a record it cannot read, with those blockers.
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
moving, and geotag compares names ignoring case ({need}`BLD-rename_planning`). The rename that completes an operation is
thus itself the check that its name is free ({need}`RUL-target_free_at_execute`).
:::

:::{bld} Names that differ only in case are one name, on every filesystem
:id: BLD-names_case_folded
:status: ruled
:realises: RUL-target_free_ignores_case, RUL-suffix_case_insensitive

Every phase SHALL take two names that differ only in case for one, on every filesystem, whether or not it tells them
apart: prep's execute refuses a move onto a name that differs only in case from one there or planned before it;
geotag's renames and merge's placements are planned with names compared ignoring case, merge settling a library file
under such a name by its content ({need}`BLD-library_file_fingerprinted`).
:::

:::{bld} Each run checks the workspace's devices
:id: BLD-workspace_one_filesystem
:status: ruled
:realises: RUL-workspace_one_filesystem, RUL-one_filesystem_checked_every_run, RUL-spanning_workspace_stops, RUL-spanning_workspace_located

`workspace_volume_breaks` SHALL walk every folder of the workspace without following links, comparing each one's device
with the workspace root's and not descending into a folder found on another; prep's and geotag's `run`, and merge's
plan, dry run, execution and in-workspace `init-library`, call it through `workspace_volume_error` once they hold the
workspace lock and have found the workspace not sealed against them ({need}`BLD-phases_check_seal`) and, on a folder
found elsewhere, report it and exit 2.
:::

:::{bld} The workspace's filesystem type, from the mount table
:id: BLD-local_filesystem_types
:status: ruled
:realises: RUL-workspace_local_filesystem, RUL-local_filesystem_checked_first, RUL-not_local_stops, RUL-not_local_named

`filesystem_type` SHALL read `/proc/self/mountinfo`, or else `/proc/mounts`, and take the type of the mount whose
point is the longest prefix of the workspace's real path, the later listed of two at one point; `local_filesystem_error`
accepts the types of `LOCAL_FILESYSTEM_TYPES` — `ext2`, `ext3`, `ext4`, `xfs`, `btrfs`, `zfs`, `f2fs`, `bcachefs`,
`jfs`, `reiserfs`, `nilfs2`, `tmpfs`, `ramfs` and `overlay` — and refuses any other, naming it, and a system with no
mount table to read. `workspace_filesystem_error` asks it, then tries the requirements ({need}`BLD-filesystem_trial`):
prep's and geotag's `run`, merge's plan, dry run, execution and in-workspace `init-library`, and the editor's start and
save, call it before they take the workspace's or the editor's lock — geotag, merge and the editor once they have found
the workspace — and on a refusal report it and exit 2, the editor's save refused.
:::

:::{bld} The filesystem's requirements, tried on scratch files
:id: BLD-filesystem_trial
:status: ruled
:realises: RUL-filesystem_requirements_tried, RUL-filesystem_lacking_stops, RUL-filesystem_lacking_named, RUL-filesystem_trial_leaves_nothing

`filesystem_lacks` SHALL make a folder of its own, `.photos-fs-trial-` and a random suffix, in the folder it is given,
and try in it, in order, each requirement asked: an exclusive non-blocking `flock` taken and let go; `os.replace` onto
a taken name; `_rename_no_clobber_same_fs` refusing a taken name, both files left as they were, and moving to a free
one; `fsync` of a file; `fsync` of the folder — returning the first that fails or raises, then removing its folder and
putting back the given folder's modification time. The workspace's are all five, tried in the control directory, or in
the workspace itself on a first prep run, before the control directory is made.
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

Geotag SHALL write metadata by having `exiftool -o` write the new file beside the photo as `<file>_exiftool_tmp` —
the photo itself untouched — then giving it the photo's permissions, syncing it to disk, renaming it over the photo
and syncing the folder, having first removed a `<file>_exiftool_tmp` an interrupted write left.
:::

:::{bld} A rewritten record is on disk before it replaces the earlier one
:id: BLD-rewrite_synced_before_rename
:status: ruled
:realises: RUL-rewrite_in_place_atomic

Every file cartographer rewrites in the control directory and the quarantine — the configuration's seed, the plans,
decisions and their backups, the journals, the handoff, the logs, the guard, the quarantine manifest, the database
images and the archival package — SHALL be written whole to a temporary file in its folder, synced to disk, renamed
over the earlier one, and the folder then synced.
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


## 17. The workspace as the last execution left it

:::{bld} The record of the workspace's state
:id: BLD-workspace_record
:status: ruled
:realises: RUL-execution_records_state, RUL-planning_leaves_record, RUL-check_covers_media_folders, RUL-quarantine_changed_only_by_prune

The record SHALL be the table `workspace_record` of `photos-00-ingest.db` — each file's `relative_path`, `size`,
`mtime_ns`, `inode` and `fingerprint` (prep's `file_cache.content_hash` where that row still has the file's size and
time, else the earlier record's for the same file: at the path a run of the tool's own moved or rewrote it from, at its
own path unchanged, or anywhere under the same size, time and inode) — named by `meta.workspace_record_id`, of every
file `workspace_entries` finds: in each managed folder but the inbox, hidden entries left out as prep leaves them, and
in `.photos-ingest-quarantine/` whole but the `.tmp-` files of a manifest's rewrite, a link an entry of its own.
`write_workspace_record` rewrites it whole, in one transaction, with a new id: prep's execute after its handoff and
before its database image, or in its `finally` once its operations have begun; geotag's `execute_plan` in a `finally`
once it begins applying photos, each written or renamed photo's fingerprint carried from the path it was planned under;
merge's `execute_plan` in a `finally` once its moves have begun, before its summary, database image and seal. A prune
that deletes takes the run folders it removed out of the record (`forget_in_workspace_record`), the workspace not
sealed. No plan, dry run or finalize writes it.
:::

:::{bld} Recognising the work of an execution killed before its record
:id: BLD-interrupted_run_recognised
:status: ruled
:realises: RUL-interrupted_work_passes, RUL-interrupted_work_exact

Each execution SHALL note itself begun, before its first change, by adding `{phase, plan_id, record_id}` to the list
`meta.executions_unrecorded` of `photos-00-ingest.db` (`note_execution_begun`) — prep's execute before its operations,
geotag's `execute_plan` and merge's `execute_plan` before their photos — nothing noted where no record exists yet; and
`write_workspace_record` deletes the list in the transaction that writes the record. A note left with the current
record's id is therefore an execution begun since that record and never recorded — the interrupted run. The check
(`recognise_interrupted_work`, before `compare_workspace`) finds each such run's plan by its id — `photos-10`, `photos-24`
or `photos-30`, or the version a re-plan kept under `-NNN` — and its journal `journal-<plan id>.json`, and takes into
the record it compares with, over a copy of it: for prep, each file its move, rename and quarantine operations take,
followed through them in plan order, found at exactly one place they take it with the recorded file's size, time and
inode — or, from the inbox, the plan's preconditioned size and time — gone from where it was and at a place no recorded
file holds, and `<quarantine>/<plan id>/manifest.json` where it holds only entries of the plan's quarantine operations;
for geotag, each photo whose rename target (or own path) the journal's `media_after` notes, found there with exactly
that size and time, gone from its recorded path where renamed; for merge, each photo of the plan gone from photos by
destination that the journal confirms, or whose `library_target` has its recorded size and time. Each is returned as
`interrupted_run` with its `phase` and `plan_id`, printed by run and returned with the changes the run names
(BLD-workspace_changes_logged); `write_workspace_record` takes the same copy for the earlier record, so each file keeps
its fingerprint at the place it was taken to. A plan not found, or a plan or journal of another shape, recognises
nothing; whatever is not recognised is compared as any other change.
:::

:::{bld} The check every checking command makes first
:id: BLD-workspace_check
:status: ruled
:realises: RUL-workspace_checked_first, RUL-change_told_by_entries, RUL-sorting_passes, RUL-culling_passes, RUL-moved_back_passes, RUL-hand_time_passes, RUL-copy_passes, RUL-unexpected_change_stops, RUL-record_needed, RUL-first_prep_compares_nothing, RUL-maintenance_unchecked

`check_workspace` SHALL compare `workspace_entries` — each file's `lstat`, no file opened — with the record through
`compare_workspace`, in this order: a file at its recorded path with its recorded size, time and inode is unchanged; one
at a new path with a recorded file's size, time and inode is that file moved; at its own path, the same size and time
under a new inode is `copied`, and a size or time changed is `time_given` in `2-missing-metadata`, `changed` elsewhere;
one of a recorded file's size, time and name under a new inode, the only such pair, is that file moved; a recorded file
left over is `deleted` in photos by date, photos by destination, videos by date and the redundant JPEGs, `removed`
elsewhere; any file left over `appeared`. A move from photos by date into photos by destination, or within the latter,
is `sorted` (`copied` under a new inode), one back from photos by destination into photos by date `moved_back`, any
other `moved`. `changed`, `appeared`, `removed` and `moved` stop the command, exit 2; the others pass. Prep calls it in
`_run_locked` for its plan, dry run and execute once its shape check has passed and the configuration loads, comparing
nothing where there is no record; geotag in `run` for its plan, execute and finalize, before the automatic re-prep,
where its preflight would find the workspace initialized and unsealed, the configuration readable, the top level as it
should be and no link in photos by destination; merge in `_run_locked_workflow` for its plan, dry run and execute once
its preflight has passed. Geotag and merge stop, exit 2, on a workspace with no record. `prune-quarantine`,
`init-library` and the editor never call it.
:::

:::{bld} Accepting a list of changes by its code
:id: BLD-accept_changes
:status: ruled
:realises: RUL-stop_gives_acceptance_code, RUL-code_accepts_only_its_list, RUL-acceptance_recorded, RUL-accepted_change_not_stopped_again

A stop SHALL print `format_changes` of its changes — a line per kind and folder (`in <folder>`, `within <folder>`,
`from <folder> to <folder>`), each file under it — then `photos-cartographer <phase> <command> --accept-changes <code>`,
the code the first 12 hex digits of the SHA-256 of those lines joined by newlines, and emit both as a `ChangesEvent`.
Every checking command takes `--accept-changes <code>`: where the code is that of the list the check would print, the
check adds to `photos-01-accepted-changes.json`, through `write_versioned_json` — the earlier file kept under `-NNN` —
an acceptance holding the code, phase, command, time, the record's id and each change with its entry as found, and the
command goes on; with any other code it stops as without one. A change equal to one an acceptance holds for the current
record's id stops nothing. A `photos-01-accepted-changes.json` that cannot be read stops the command, exit 2, and is
never written over. It lies in the control directory, so the archival package carries it. The console's Accept button
sends the same command with the code (`_accept_extra`), refusing a command that does not check.
:::

:::{bld} Where the changes by hand are named
:id: BLD-workspace_changes_logged
:status: ruled
:realises: RUL-allowed_changes_named, RUL-accepted_changes_logged

The check SHALL print the changes it passes, `sorted` aside, and those accepted, and return them — `kind`, `path`,
`from`, the `accepted` code, an interrupted run's `phase` and `plan_id` and, where the record holds one, the
`content_fingerprint` — for the execution's record:
prep's execute adds them, each with its `run`, to `workspace_changes` of `photos-15-prep-log.json`, after the earlier
runs'; geotag's execute writes them as `workspace_changes` of `photos-25-execution-summary.json`, merge's as
`workspace_changes` of `photos-31-merge-summary.json`. A plan, a dry run and finalize print them.
:::
