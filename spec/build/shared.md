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
recorded inputs, recorded the same way (merge §8–§9). A withdrawn manual position SHALL be restored from the pinned
pre-state ledger (geotag §24.1); an automatic position is recomputed, never rolled back.
:::

## 12. The record of what was done, kept beyond the workspace

:::{bld} The per-phase logs and records
:id: BLD-phase_logs
:status: seed
:realises: RUL-record_whole_each_phase, RUL-carry_forward_by_copy

Prep SHALL write `photos-15-prep-log.json` at the end of every prep run (prep §16.1). Geotag's finalize SHALL copy it
to `photos-26-complete-log.json` and append each photo's geotag steps (§13.3); merge SHALL copy that to
`photos-35-merge-log.json` and append its own (§13.5). Each phase's job records — prep's handoff and summary, geotag's
decision, plan and execution-summary records, merge's summary — SHALL stay on disk.
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
