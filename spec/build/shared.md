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
:realises: RUL-config_validated_before_use, RUL-checked_paths, RUL-checked_snapshot_names, RUL-checked_filename_format, RUL-checked_numbers

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

## 7. The tracks, kept outside the managed folders

:::{bld} `gpx_root`
:id: BLD-gpx_root
:status: seed
:realises: DEF-tracks, RUL-tracks_outside_managed_folders

The tracks' location SHALL be the configuration key `gpx_root`: a path, absolute or relative to the workspace, resolved
through links before use; empty means no tracks. It MAY be anywhere outside `0-sources` … `6-photos-by-dest` — on any
disk, or under the control directory, such as `.photos-ingest/gpx/`, which prep's skip of `.photos-ingest/` already keeps
out of the scan. Geotag reads every `*.gpx` file beneath it. The value and the matching thresholds are read by geotag;
their detail is geotag §15 and §19.
:::

:::{bld} `gpx_root` checked against the managed folders
:id: BLD-gpx_root_checked
:status: seed
:realises: RUL-tracks_outside_managed_folders

Configuration validation, in every phase, SHALL resolve `gpx_root` against the workspace, through links, and refuse it
when it is a managed folder, lies inside one, or contains one — the workspace root among them.
:::

:::{bld} A track file
:id: BLD-track_file
:status: seed
:realises: RUL-track_files_block_prep, DEF-tracks

A track file SHALL be a file named `*.gpx`, `*.kml`, `*.kmz`, `*.fit`, `*.tcx`, `*.nmea` or `*.igc`, in any case. Of these geotag reads
only the `*.gpx` files beneath `gpx_root`. Prep SHALL raise one blocker for each it inventories, naming it, and leave it
out of the plan (prep §3, §6.1); and execute SHALL raise the same blocker for one that appeared after planning (prep
§14.3).
:::

:::{bld} The GPX fingerprint
:id: BLD-gpx_fingerprint
:status: seed
:realises: RUL-tracks_in_dependencies

The GPX fingerprint SHALL be a SHA-256 over the resolved `gpx_root`, a version tag, and, in sorted order, each `*.gpx`
file's path relative to the root and the SHA-256 of its bytes. An empty `gpx_root`, and a `gpx_root` that is not a
directory, SHALL each give a fixed value of their own, the second with a warning. It SHALL be recorded as
`gpx_fingerprint` in the `depends_on` of `photos-21-time-decisions.json`, `photos-22-gps-drift-validation.json`,
`photos-23-gps-decisions.json` and `photos-24-executable-plan.json`, and checked before each is used.
:::

## 8. Nothing used once what it came from has changed

:::{bld} Each phase's dependencies, in full
:id: BLD-phase_dependencies
:status: seed
:realises: INV-no_stale_use

Each phase SHALL record a record's dependencies in its `depends_on` block and check them before use, as its own spec
states in full: prep §5; geotag §3–§6; merge §10.3. The cascade consumes media by content fingerprints, records by byte
hashes, and the field-scoped configuration fingerprints (shared §4.2) that keep staleness surgical.
:::

:::{bld} How a fingerprint and a hash are computed
:id: BLD-fingerprint_and_hash
:status: seed
:realises: DEF-fingerprint, DEF-hash, RUL-fingerprint_survives_mutation, RUL-hash_detects_any_change

A photo's fingerprint SHALL be ImageMagick `identify`'s signature — a SHA-256 of the normalized pixel stream; a video's,
the `ffmpeg` stream MD5 (prep §9). A hash SHALL be a SHA-256 over the exact bytes of a numbered JSON record or the
configuration.
:::

## 9. One loop across the phases

:::{bld} The loop's commands
:id: BLD-loop_commands
:status: ruled
:realises: DEF-operator_loop, DEF-finalize, RUL-prep_records_sort

The loop SHALL run as: `prep plan`, `dry-run`, `execute`; the sort, by hand; the prep commands again; `geotag plan`, the
decision editor (`edit`) for what it asks, and `geotag plan` again until `photos-24-executable-plan.json` is ready;
`geotag execute`, which writes `photos-25-execution-summary.json`; `geotag finalize`, which writes
`photos-26-complete-log.json` and the archival package; and `merge plan`, `dry-run`, `execute`. When the only change
prep has not recorded is a sort and the inbox is empty, `geotag plan` SHALL run prep's `plan` and `execute` itself,
saying so, before it plans.
:::

:::{bld} Where the loop's gates are checked
:id: BLD-loop_gates
:status: seed
:realises: RUL-geotag_gates, RUL-sort_photos_only, RUL-development_after_merge

`geotag plan` SHALL check every gate. `geotag execute` and `finalize` SHALL check the development gate and the
workspace's shape, and validate against the plan's own dependencies instead of the scope and re-prep gates (geotag §7,
§13.1). Merge's preflight SHALL check the inbox, the development gate and that photos by destination holds only photos
(merge §3). A development subfolder SHALL be one named in `destination_distribution_subfolders`.
:::

:::{bld} How a re-run recognises what is settled
:id: BLD-rerun_recognition
:status: ruled
:realises: RUL-geotag_rerun_keeps_settled

Geotag SHALL record what it wrote in the file's `GPSProcessingMethod`: the bare value `interpolated`, `manual_locked`
or `manual_fallback` beside each position it writes, and, when it fixes the time and writes no position, the suffix
`+carto-time` appended once to whatever the field held, keeping the device's own value. Any other value is the
device's own, and the GPS beside it native. Before geotag's first write to a file, execution SHALL pin its own time, offset tag, position and
`GPSProcessingMethod` in an original-values ledger keyed by fingerprint, once, unless it already carries geotag's mark;
a later plan SHALL decide about a pinned file from those values and plan only the writes that differ from what it
holds (geotag §24.2). On a re-run, a file with no pinned values carrying a position marker or the suffix SHALL be
resolved from its own time and offset tag with no clock offset, SHALL be no clock anchor and in no drift check, and a
camera group's offset cells SHALL be built from its unmarked files alone. A file with a position marker SHALL count as
having no native GPS and be placed again; one now placed nowhere has geotag's position and marker cleared and carries
the suffix alone. A write SHALL be planned only where the file does not already hold its value, and names are
recomputed from the destination's local time, a file already so named getting no rename (geotag §27, §28.2).
:::

## 10. Change only what needs changing

:::{bld} What each phase reuses and skips
:id: BLD-idempotency
:status: seed
:realises: RUL-reuse_valid_work, RUL-remake_only_what_depends, RUL-mutate_on_difference, RUL-no_op_run

Prep SHALL reuse the cached fingerprint and metadata of a file whose size and modification time are unchanged, and
carry a moved file's identity forward without reading it (prep §10, §13); a plan never executed SHALL leave its
fingerprints and metadata for the next plan to reuse (prep §10.3). Geotag SHALL reuse its resolved-UTC cache while its
inputs are unchanged and keep each decision whose target is unchanged (geotag §9, §22.1). Fingerprinting (ImageMagick
`identify`, `ffmpeg`), metadata extraction (`exiftool`) and GPX parsing SHALL run only for new or changed inputs.
Staleness SHALL follow the field-scoped fingerprints of the dependency cascade (§9). A file's operation SHALL be planned
only where the file does not already hold the target: prep does not move or rename a file already in place, geotag
plans no write a file already holds and recomputes an already-final name to itself (geotag §27, §28.2), and merge
records a photo already in the library as already present (merge §7). A run's summary SHALL count the cache hits and
the files already right. Each phase's own consequences are in its spec: prep §13 and §21, geotag §29.1 and §30, merge
§8.
:::

## 11. Nothing changes that the user did not write down

:::{bld} Where the decisions live, and how a change is traced
:id: BLD-decision_records
:status: ruled
:realises: RUL-user_writes_decisions, RUL-cause_locatable, RUL-decision_revisable, RUL-withdrawal_undoes

The decisions SHALL live in the `user_decision` fields of geotag's `photos-21`, `photos-22` and `photos-23`, each field
created by geotag and preserved across regeneration (geotag §9, §20); the decision editor SHALL write only those
fields. A change SHALL be traced from its decision record through the `depends_on` fingerprints (§9) to the executable
plan and the run's journal (prep §14.3; geotag §4–§6, §29). Merge takes no decision; its placement is a fixed rule over
recorded inputs, recorded the same way (merge §8–§9). Every plan SHALL decide about a photo from its own values, pinned
before geotag first wrote to it (geotag §24.2), so a withdrawn manual position is undone like any decision: the photo is
placed again, or geotag's position cleared; an automatic position is recomputed, never rolled back.
:::

## 12. The record of what was done, kept beyond the workspace

:::{bld} The per-phase logs and records
:id: BLD-phase_logs
:status: ruled
:realises: RUL-record_whole_each_phase, RUL-carry_forward_by_copy

Prep SHALL write `photos-15-prep-log.json` at the end of every prep run (prep §16.1). Geotag's finalize SHALL copy it
to `photos-26-complete-log.json` and append each photo's geotag steps (§13.3); merge SHALL copy that to
`photos-35-merge-log.json` and append its own (§13.5). Each copy SHALL carry the earlier log unchanged — every entry,
every field and every step as it was, a phase only adding — and finalize and merge SHALL check it: a copy that would
change the earlier record is not written, and merge SHALL refuse while `photos-26-complete-log.json` no longer carries
`photos-15-prep-log.json` so, or cannot be read. A prep log missing or unreadable at finalize SHALL be named in the
complete log's `warnings`, the log then `partial`. Each phase's job records — prep's handoff and summary, geotag's
decision, plan and execution-summary records, merge's summary — SHALL stay on disk, as SHALL every pass's plan and
journal and the decision records each execution kept (`BLD-log_format`).
:::

:::{bld} Which phase writes which record
:id: BLD-record_ownership
:status: ruled
:realises: RUL-phase_writes_own_records
:uses: BLD-artifact_numbering, BLD-init_library_writes_library_root

A phase SHALL write only records in its own number band of the numbering scheme: prep `photos-1X`, geotag `photos-2X`,
merge `photos-3X`. The configuration and the database are phase-neutral, each with its own writers' rule: prep seeds
the configuration, which `init-library` may later extend by `library_root` alone (§4), and prep writes the database's
cache and identity rows while geotag and merge write only their own regions of it (§13.4). Bundling copies of every phase's records into the archival package reads them, and is no write.
:::

:::{bld} The package: the control directory, archived with its manifest
:id: BLD-archive_manifest
:status: ruled
:realises: RUL-finalize_non_destructive, RUL-package_contents, RUL-package_self_describing

`geotag finalize` SHALL write `photos-26-complete-log.json` and the database snapshot `photos-26-geotag-ingest.db`, then
list every file of the control directory but the transient ones — locks, `.tmp-` files, SQLite's `-journal` files, the
plan memo `photos-00-plan-memo.db` and any `*-archive.tar.gz` — with its SHA-256 and path in
`photos-26-archive-manifest.json`, recording the workspace's identity — the init run id prep wrote in the guard — with
the folder's name beside it, and the plan and execution ids, and archive
those files and the manifest into `photos-26-archive.tar.gz` in the control directory, by a temporary name and an
atomic rename. It SHALL write nothing else, and requires a ready plan whose execution succeeded (geotag §31). Merge's
re-seal does the same into `photos-35-archive-manifest.json` and `photos-35-archive.tar.gz` (§13.6).
:::

:::{bld} The log's format, and the history it is made from
:id: BLD-log_format
:status: ruled
:realises: RUL-log_entry_grows, RUL-log_keyed_by_fingerprint, RUL-log_cites_decisions, RUL-log_records_gps_reverts, RUL-log_human_readable, RUL-history_retained, RUL-partial_history_shown

Each log SHALL be pretty-printed JSON with sorted keys, its `photos` keyed by the content fingerprint (`content_fingerprint`),
each entry carrying where each phase left the photo — `prep_path`, written by prep and updated by every prep run;
`geotag_path`, by finalize, its by-dest folder under the name its last final rename gave it; `library_path`, by merge —
and a `journey` of steps, each step naming its `phase` and `action`, a move or rename
its `from` and `to` — the first step's `from` being the photo's path in the dump — and, where a decision caused it, a
`because` naming the decision exactly: a clock offset its `photos-21` cell, with its day where the camera's photos
there span days (`camera_group_time_decisions.<group>@<date>`), or the `photos-22` drift confirmation whose validated
offset replaced it; a timezone its destination's cell; a manual position the photo's pin among `photos-23`'s review
items or the destination's folder fallback, with the destination it was accepted from. Geotag's steps SHALL be
`clock_offset_applied` (its `offset_seconds` with an `offset_description` in words, such as "camera clock 1 h 55 min
ahead of UTC"), `resolved_utc`, `timezone_resolved`, `time_written`, `gps_written` (with its origin, method and,
for a manual position, the position it replaced, from the plan), `gps_cleared` (a position geotag wrote
and no longer places, with that position, from the plan, and the method left), `gps_preserved` and `final_rename`,
each naming its `run`;
finalize SHALL take them from every executed pass — each superseded `photos-24` whose journal shows it ran, oldest
first, matched by fingerprint — before the current plan's, from the provenance each time write carries (geotag §31). Each run's journal SHALL be kept as
its own `journal-<run>.json`, and each geotag execution SHALL keep the decision records its plan depended on, verified
by hash, in `executed/<plan id>/`, which a step's `because_record` and `because_record_sha256` name; prep marks its log partial and warns when its history cannot rebuild a journey (prep
§16.1); geotag's finalize marks `partial` the entry of a photo carrying geotag's mark whose own values the workspace
never pinned, with a `history_incomplete` step of its own saying why, and names in the log's `warnings`, the log then `partial`, any pass whose journal is kept
but whose plan is missing (geotag §31).
:::

:::{bld} The database: its file, its writers, its images
:id: BLD-workspace_database
:status: ruled
:realises: RUL-one_database, RUL-database_is_record, RUL-database_regions_disjoint, RUL-database_image_each_phase, RUL-database_image_whole
:uses: BLD-record_ownership

The workspace database SHALL be SQLite, `photos-00-ingest.db` in `.photos-ingest/`. Its writers SHALL be: prep, of the
file and metadata caches (`file_cache`, `metadata_cache`) and their version row (`meta`), through its single-writer
path (prep §14.3); geotag, of the resolved-UTC cache (`resolved_utc_cache`), the values each photo held before geotag
first wrote to it (`original_values`, geotag §24.2); merge, of the library-file fingerprint cache (`library_fingerprint_cache`, keyed by the library file's absolute
path with its size and modification time). Where each photo landed is in merge's JSON records, not the database. Prep's
plan-time decode memo, `photos-00-plan-memo.db`, is the one other database: scratch, re-derivable, deletable at any
time (prep §10.3).

The images SHALL be `photos-15-prep-ingest.db`, written when prep writes its handoff and log; `photos-26-geotag-ingest.db`,
written by finalize with the complete log; and `photos-35-merge-ingest.db`, written when merge succeeds, before it
re-seals. Each SHALL be captured under the workspace lock by `VACUUM INTO` a `.tmp-` name in the control directory,
checked with `PRAGMA quick_check`, then renamed over the phase's earlier image.
:::

## 13. Merge: the library kept, the workspace sealed

:::{bld} Merge's collision check and its library cache
:id: BLD-merge_collision
:status: ruled
:realises: RUL-library_not_scanned, RUL-collision_by_content, RUL-library_file_read_once
:uses: BLD-workspace_database

Merge SHALL map each photo by destination to its place under `library_root`, and list only the folders its photos go
to — for the names taken there — and the library's top folder, for temporary copies a crash of its own left (§15). Where a file is
there, merge SHALL fingerprint it — from `library_fingerprint_cache` when its path, size and modification time match a
row taken by the current ImageMagick version (or recording none), otherwise by decoding it and storing the row — and compare it with the incoming photo's fingerprint from prep. An
incoming photo whose name is taken by different content SHALL take the shared suffix convention's next free suffix
(§7.2), the library's own name keeping its bare form.
:::

:::{bld} The library's mark and its checks
:id: BLD-library_marker
:status: ruled
:realises: RUL-library_known_by_mark, RUL-library_place_checked

A library SHALL be marked by an empty `.photos-library` file in `library_root`, which `is_library` tests with
`os.path.isfile`; `merge init-library` alone SHALL create it, with `O_CREAT|O_EXCL`, leaving one already there as it is
(merge §4). `validate_merge_config` SHALL require `merge.library_root` to be non-empty and to resolve to an existing
directory that is neither the workspace nor inside it. Merge SHALL create a missing destination directory under
`library_root` with `os.makedirs` as it places a photo there.
:::

:::{bld} The library lock
:id: BLD-library_lock
:status: ruled
:realises: RUL-library_lock, RUL-library_lock_fail_fast, RUL-library_confirmed_before_lock

The library lock SHALL be `LibraryLock`: an exclusive, non-blocking `flock` on `.photos-merge.lock` in `library_root`,
recording its holder's `pid`, `started_at` and `host` and nothing else, released by the kernel when its process dies;
the file is never deleted. Merge's `plan`, `dry-run` and `execute` SHALL take it after the workspace lock and after the
preflight's `validate_merge_config` and `is_library` checks, and hold it to their end; one that cannot take it SHALL
stop with exit status 1.
:::

:::{bld} Merge's move: one rename, or copy, verify, rename and remove
:id: BLD-merge_move
:status: ruled
:realises: RUL-library_never_altered, RUL-merge_moves, RUL-merge_resumable

Each photo SHALL move into its place without overwriting it: on the library's own filesystem by a single rename that
refuses an existing name; across filesystems by a copy to a temporary name beside its place, fingerprinted against the
planned content, renamed into the place only if it is still free, and only then removed from photos by destination. The
journal SHALL record each confirmed photo. A re-run SHALL take a place already holding the planned content, fingerprinted
again, as done, removing the workspace copy if it remains. A photo already present SHALL be removed from photos by
destination after the library's copy is fingerprinted again and found to hold its content.
:::

:::{bld} The merge records and the re-seal
:id: BLD-merge_records
:status: ruled
:realises: RUL-merge_records_landing, RUL-merge_reseals, RUL-seal_on_success_only
:uses: BLD-archive_manifest, BLD-workspace_database

Merge SHALL write `photos-31-merge-summary.json` on every outcome but a stale plan or a failed precondition: per photo
and in total, where it landed, whether it was renamed for the library, already present or blocked. Only on success —
every photo placed or already present, none left — SHALL it then, in order, write `photos-35-merge-log.json`,
`photos-35-merge-ingest.db`, the package's `photos-35-archive-manifest.json` and `photos-35-archive.tar.gz`, and last
the seal.
:::

:::{bld} The seal and its checks
:id: BLD-seal_marker
:status: ruled
:realises: RUL-seal_is_authority, RUL-sealed_refuses, RUL-sealed_prune_allowed, RUL-sealed_new_dump_warned

The seal SHALL be `photos-00-sealed.json` in the control directory, its own file beside the workspace guard — which
only prep writes — recording `sealed`, the merge run id (`merged_run_id`) and `library_root`; its presence alone seals.
Prep's `plan`, `dry-run` and `execute`, every geotag command, and merge's `plan`, `dry-run` and `execute` SHALL check it under the workspace
lock before reading anything else, and stop with exit status 2 if it is there, adding the likely-new-dump warning when
`likely_new_dump` finds an entry at the workspace's top level other than its managed folders and hidden entries, or
anything in the inbox. `edit` SHALL refuse to serve a sealed workspace, with the same warning, and its save SHALL write
nothing there. `merge init-library` given a path from inside a workspace, which would record it
as `library_root` in the configuration, SHALL check the seal under the lock the same way, and stop with exit status 2
having blessed nothing; without a path, or from outside any workspace, it writes nothing in the workspace and does not
check. `prune-quarantine` SHALL not check the seal.
:::

## 14. Every value the user writes is checked

:::{bld} Where each phase checks what the user wrote
:id: BLD-authored_checks_by_phase
:status: seed
:realises: INV-authored_values_checked, RUL-checked_shapes, RUL-checked_positions_and_times, RUL-checked_timezones, RUL-invalid_value_stops, RUL-invalid_value_located, RUL-checked_every_run, RUL-invalid_decision_kept
:uses: BLD-config_values_checked

`validate_config` SHALL check the configuration each time it is read: by prep as it seeds and reads it, by geotag and
merge as they load it. Merge SHALL check besides, with `validate_merge_config`, `merge.library_root` and the merge
policy's values. Geotag SHALL check the decisions in `photos-21`, `photos-22` and `photos-23` as it reads them (geotag
§9.2, §20): each blocker SHALL name the artifact, the destination, the cell or the file, and the field, and an artifact
holding one SHALL be left as it is, its plan not written. A decision artifact that cannot be read, does not parse as
JSON or is not a JSON object SHALL be such a blocker, located to where parsing failed — never taken as absent.
:::

## 15. Nothing overwritten, nothing left half-done

:::{bld} One rename that refuses a taken name
:id: BLD-no_clobber_rename
:status: seed
:realises: RUL-target_free_at_execute, RUL-operations_atomic

Every move and rename that carries content SHALL go through `_move_no_clobber`: on one filesystem `renameat2` with
`RENAME_NOREPLACE`, one call that refuses an existing name, or where that is unavailable `os.link` then `os.unlink`;
across filesystems `_move_cross_fs_no_clobber`. A refused name SHALL be a blocker. Merge SHALL also test its target
before moving, and geotag compares names ignoring case (geotag §27). The rename that completes an operation is thus
itself the check that its name is free (prep §14.3–§14.4, geotag §29.1a, merge §11).
:::

:::{bld} Geotag's metadata writes
:id: BLD-metadata_safe_write
:status: seed
:realises: RUL-rewrite_in_place_atomic

Geotag SHALL write metadata with `exiftool -overwrite_original`, which writes a temporary file and renames it over the
original, having first removed a `<file>_exiftool_tmp` an interrupted write left (geotag §29.1a).
:::

:::{bld} The cross-filesystem copy and its sweep
:id: BLD-cross_fs_temp
:status: seed
:realises: RUL-cross_fs_all_or_nothing, RUL-crash_temps_cleared

`_move_cross_fs_no_clobber` SHALL copy to a `.tmp-xdev-<random>.part` file in the destination directory, fingerprint
it against the planned content, sync it, rename it into its place without overwriting, and then remove the source.
Merge's `execute` SHALL, after revalidating its plan and taking its snapshot and before its first move, remove every
`.tmp-xdev-*.part` file directly in `library_root` and in each planned target's directory, and record how many in
`photos-31-merge-summary.json` as `run_metadata.orphan_temps_swept`.
:::

:::{bld} What each phase does with a failed operation
:id: BLD-failed_operation
:status: seed
:realises: RUL-failed_operation_clean

Prep SHALL journal an operation that raised as `failed`, and stop. Geotag SHALL confirm no write whose tool failed or
whose result does not fingerprint as planned. Merge SHALL record a placement that raised as blocked, its photo left in
photos by destination.
:::
