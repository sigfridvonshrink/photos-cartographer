# Prep — how this build does it

How this build meets [prep's intent](../intent/prep.md): the files, names, tools and steps. Each item `realises` the
intent it implements. *Why* a choice was made is in [the rationale](../rationale/prep.md).

## 1. What prep does, and what it leaves alone

:::{bld} Prep's operations hold no metadata write
:id: BLD-prep_operation_kinds
:status: ruled
:realises: RUL-prep_no_time_or_gps

Prep's execute SHALL carry out only folder creations, moves, renames, quarantine moves and database writes, refusing a
plan that holds any other operation — a metadata write among them.
:::

:::{bld} No operation touches `6-photos-by-dest`
:id: BLD-by_dest_ops_refused
:status: ruled
:realises: RUL-prep_leaves_by_dest_as_found

Prep's plan SHALL hold no operation whose source or destination lies in `6-photos-by-dest`, its execute refusing a plan
that holds one; prep reads the files there for their fingerprint and metadata only ({need}`RUL-move_recognized`, {need}`RUL-copy_kept_by_folder`).
:::

## 2. The workspace's first run, and the strays

:::{bld} The mark is `photos-00-workspace-guard`, written last
:id: BLD-workspace_guard
:status: ruled
:realises: RUL-initialized_marked_last

The mark SHALL be the file `photos-00-workspace-guard` in `.photos-ingest/`, which the initializing run's execute writes
after every other operation has succeeded; the managed folders it creates are `0-sources` … `6-photos-by-dest`. It
holds `initialized`, `tool` and `initialized_by_run`, the initializing plan's id, which the archival package's manifest
records as the workspace's identity ({need}`BLD-archive_manifest`).
:::

:::{bld} A taken inbox path takes the next `-NNN`
:id: BLD-init_move_suffix
:status: ruled
:realises: RUL-init_taken_place_suffixed

The initializing run's move of a dump file SHALL go to `0-sources/<its path>`, and where that path, ignoring case, is
another file's current or planned path, to the same folder under `<name>-NNN.<ext>` with the first `NNN` from `001` so
free ({need}`BLD-name_suffix`), the extension kept as it was; the suffixed name is the one the later stages name the
file from.
:::

:::{bld} A run's strays go to `1-strays/<plan-id>/`
:id: BLD-strays_per_run
:status: ruled
:realises: RUL-inbox_non_media_to_strays

Prep SHALL move a run's strays into `1-strays/<plan-id>/`, each at its path under `0-sources/`, so that no two runs
share a folder there.
:::

:::{bld} Where a stray is named
:id: BLD-stray_records
:status: ruled
:realises: RUL-strays_leave_no_trace

A stray SHALL be named in `photos-10-prep-plan.json` alone — in its `inventory` and `metadata_plan_status`, and in the
move that sets it aside (on the first run, the move into `0-sources` too) with its size and `mtime_ns` — and in the
journal only by that move's id; it has no fingerprint, no row in `photos-00-ingest.db` or the plan memo, and no entry in
the handoff or `photos-15-prep-log.json`, the archival package holding it only within the plans it carries.
:::

:::{bld} The configuration is seeded before it is fingerprinted
:id: BLD-seed_before_fingerprints
:status: ruled
:realises: RUL-config_seeded_once

Prep SHALL seed the configuration at the start of its run, before any fingerprint of it is taken, so that every
fingerprint, the handoff's recorded hash among them, is of the file as it stands in the workspace.
:::

## 3. The plan, validated, then carried out

:::{bld} Prep's execute replays the saved plan
:id: BLD-prep_execute_replays
:status: ruled
:realises: RUL-execution_only_the_plan

Prep's execute SHALL apply the operations of `photos-10-prep-plan.json` in their recorded order, to the destinations
recorded there, running no step of planning.
:::

:::{bld} Prep journals each operation as it ends
:id: BLD-prep_journal
:status: ruled
:realises: RUL-every_change_journaled, RUL-journal_never_torn

Prep's execute SHALL append each operation's outcome to `journal-<plan-id>.json` as the operation ends, saving the
journal after each by replacing it whole — written to a temporary file in its folder, then renamed over it.
:::

## 4. What each of prep's records depends on

:::{bld} Prep's dependencies, in full
:id: BLD-prep_dependencies
:status: ruled
:realises: INV-no_stale_use, RUL-unchecked_counts_as_changed

Prep's records SHALL carry their dependencies so:

- **The plan** records its schema version, the configuration's hash, its metadata dependencies — exiftool and its
  version, and the versions of the field set, the extraction options, the metadata schema and the camera-group
  derivation — and the size and mtime of every file it reads without changing, those in `6-photos-by-dest` among them.
  Execute recomputes each and refuses the plan when one differs or is absent.
- **The journal**'s `depends_on` records the plan's schema version, the configuration's hash, and the cache's schema and
  fingerprint-algorithm versions.
- **The handoff**'s `depends_on` records the configuration's hash, the metadata dependencies, the plan's and the cache's
  schema versions, the fingerprint algorithm and the image engine with its version, the journal's hash, the prep log's
  hash ({need}`BLD-prep_log_vouched`), and the fingerprint of the final inventory.
- **The workspace database** records its schema and fingerprint-algorithm versions in its `meta` table.

A run's inventory and freshness maps are its own working state, recorded nowhere. No command option affects what prep
plans, so no record carries one.
:::

:::{bld} The handoff vouches for prep's log
:id: BLD-prep_log_vouched
:status: ruled
:realises: INV-no_stale_use

Prep's execute SHALL write `photos-15-prep-log.json` before the handoff, and record the log's SHA-256 in the handoff's
`depends_on.prep_log`, outside its content fingerprint.
:::

:::{bld} Finalize copies only the log the handoff vouches for
:id: BLD-finalize_checks_prep_log
:status: ruled
:realises: INV-no_stale_use, RUL-unchecked_counts_as_changed

Geotag's finalize SHALL copy prep's log only when its bytes hash to the value {need}`BLD-prep_log_vouched` records, and
stop otherwise — the log missing or unreadable, or the handoff recording no hash, among the cases.
:::

:::{bld} A change by hand is not "nothing to do"
:id: BLD-hand_change_is_work
:status: ruled
:realises: RUL-prepped_nothing_to_do, RUL-allowed_changes_named

Prep's stop on an already-prepped workspace SHALL not apply while the run's check of the workspace
({need}`BLD-workspace_check`) named or accepted a change since the last execution, or no execution has recorded the
workspace's state yet ({need}`BLD-workspace_record`), so that prep's execute records it.
:::

:::{bld} A log not vouched for is not "nothing to do"
:id: BLD-prep_fast_stop_checks_log
:status: ruled
:realises: RUL-unchecked_counts_as_changed

Prep's stop on an already-prepped workspace SHALL not apply while the log's hash differs from what the handoff records,
so that prep's next execute rewrites both.
:::

## 5. What prep refuses to work on

:::{bld} The sidecars prep refuses
:id: BLD-sidecar_extensions
:status: ruled
:realises: RUL-sidecar_blocks

The editing sidecars SHALL be the files ending `.xmp`, `.dop` or `.pp3`, matched ignoring case — a fixed list, not
configuration.
:::

:::{bld} One probe per stray extension
:id: BLD-stray_media_probe
:status: ruled
:realises: RUL-stray_media_hinted

Prep's plan SHALL ask exiftool the `MIMEType` of one file for each distinct extension among the inbox's files of no
media class, and warn for each whose type is `image/*` or `video/*`; with exiftool absent, it warns of none.
:::

:::{bld} A plan holding a blocker is refused
:id: BLD-blocked_plan_refused
:status: ruled
:realises: RUL-band_misplacement_blocks, RUL-sidecar_blocks, RUL-other_outside_inbox_blocks, RUL-blockers_all_reported

Prep's dry-run and execute SHALL refuse, before any change, a plan whose `blockers` list — where planning records every
blocker it finds, the plan still saved — is not empty.
:::


## 6. The prep pipeline

:::{bld} The stages run in a fixed order
:id: BLD-prep_stage_order
:status: ruled
:realises: RUL-duplicate_set_aside_as_found, RUL-copy_kept_by_folder

Prep's planning SHALL run its stages in this order: initialization and inventory; duplicates; extension case; redundant
JPEGs; organization by class and time; database reconciliation.
:::

:::{bld} Each stage works from the paths the stages before it planned
:id: BLD-planned_paths_tracked
:status: ruled
:realises: RUL-suffix_no_clobber, RUL-inbox_kept_as_dumped

Each stage of prep's planning SHALL work from the path the stages before it gave each file, allocating every name
against the names on disk and those already planned.
:::

:::{bld} A timed file in missing metadata is organized with the inbox's
:id: BLD-time_given_organized
:status: ruled
:realises: RUL-time_given_filed_on, RUL-filed_file_stays

Prep's organization stage SHALL take each file in `2-missing-metadata` whose metadata gives a recorded time with the
inbox's files to be filed — one `move_no_clobber` of reason `Chronological Organization` into its day folder of
`5-photos-by-date` or `4-videos-by-date`, its name allocated against the names already planned — after the duplicates
stage has set aside any copy of it, and leave one with no recorded time where and as it lies. A JPEG set aside beside
its RAW in `3-redundant-jpgs` keeps its name when the RAW is so filed: the two cannot be paired there (the pairing
rests on their sharing a dump folder), and the set-aside copy is never used.
:::

:::{bld} A filed file's extension is lowercased in two renames
:id: BLD-two_step_case_rename
:status: ruled
:realises: RUL-media_extension_lowercase

A filed media file's extension SHALL be lowercased by two no-clobber renames in its folder, through a temporary name
free on disk and in the plan; an inbox file's, in the move that files it.
:::

:::{bld} What counts as a JPEG and a raw file
:id: BLD-jpeg_extensions
:status: ruled
:realises: RUL-redundant_jpeg_set_aside

A JPEG SHALL be a file of the `image` class ending `.jpg` or `.jpeg`, matched ignoring case; a raw file, one of the
`raw` class.
:::

:::{bld} A JPEG pairs with its RAW by its name, with case
:id: BLD-raw_jpeg_pair_by_exact_name
:status: ruled
:realises: RUL-redundant_jpeg_set_aside, RUL-redundant_jpeg_only

A JPEG and a raw file SHALL be a pair only where, in one inbox folder, their names before the extension are the same
with case — `IMG_1.JPG` pairs with `IMG_1.cr2`, never with `img_1.cr2` — the extensions matched ignoring case
({need}`BLD-jpeg_extensions`).
:::

:::{bld} The pair, recorded by prep
:id: BLD-set_aside_pair_recorded
:status: ruled
:realises: RUL-set_aside_jpeg_renamed_with_raw, RUL-set_aside_jpeg_named_as_raw

Prep's move of a JPEG into `3-redundant-jpgs` SHALL carry, where its inbox folder holds one raw file of its name, that
raw file's fingerprint as `raw_fingerprint`: the JPEG's `redundant_jpeg_separated` step in the prep log keeps it, and
each prep execution writes the latest one of each JPEG into its record of the handoff. Beside two raw files of its name,
a JPEG names neither.
:::

:::{bld} A culled RAW, found by its fingerprint
:id: BLD-culled_raw_found
:status: ruled
:realises: RUL-culled_raw_takes_its_jpeg, RUL-culled_raw_known_by_content, RUL-culled_raw_jpeg_logged, RUL-culled_raw_jpeg_recorded
:uses: BLD-set_aside_pair_recorded, BLD-workspace_changes_logged

At plan, after duplicates are set aside and before any name is checked, prep SHALL plan a `quarantine_move` of kind
`raw_culled` for each JPEG in `3-redundant-jpgs` whose `raw_fingerprint` in the prep log
({need}`BLD-set_aside_pair_recorded`) no file prep scanned holds — the inbox and `6-photos-by-dest` among them — and
which a workspace check found `deleted`: this run's, an earlier prep run's as `workspace_changes` of
`photos-15-prep-log.json` keeps it, or a geotag execution's as `photos-25-execution-summary.json` or a `-NNN` copy of it
keeps it ({need}`BLD-workspace_changes_logged`). The move carries the JPEG's `content_fingerprint`, and the RAW's
`raw_path` — the path the check found it deleted at — and `raw_fingerprint`, into the quarantine manifest; the JPEG's
entry in the prep log gains the step `raw_culled` with `from`, `to`, `raw_path` and `raw_fingerprint`, its `prep_path`
the quarantine path; and the execution's workspace record holds the JPEG in the quarantine like any file prep
quarantined.
:::

:::{bld} The database is reconciled by planned operations
:id: BLD-database_ops
:status: ruled
:realises: RUL-database_matches_files

Prep's plan SHALL refresh a stale database row with a `db_upsert`, and remove with a `db_remove` the row of a file gone
that no move explains and whose path no planned move fills again — that row is the move's to replace.
:::


## 7. Naming conventions

:::{bld} A day's folder is named `YYYY-MM-DD`
:id: BLD-day_folder_name
:status: ruled
:realises: RUL-by_date_in_day_folder

A day's folder SHALL be named `YYYY-MM-DD` from its recorded time's date, whatever `filename_timestamp_format` is.
:::


## 8. Content fingerprinting and cache reuse

:::{bld} The database's version row
:id: BLD-cache_versions
:status: ruled
:realises: RUL-cache_schema_not_migrated

The workspace database's `meta` table SHALL hold `cache_schema_version` and `fingerprint_algorithm_version`, written by
each prep execute; prep's plan stops before reading the database when `cache_schema_version` is present and not this
build's.
:::

:::{bld} A fingerprint records its method
:id: BLD-fingerprint_method
:status: ruled
:realises: RUL-fingerprint_method_matches, RUL-fingerprint_method_is_the_builds

Each fingerprint SHALL record its strategy — `image-content-hash-v2` for a photo, `video-md5-v2` for a video — and a
photo's the ImageMagick version that took it; a cached photo fingerprint is reused when both match the build's, a video's
when its strategy does. The handoff carries the method's version (`depends_on.cache.fingerprint_algorithm_version`); geotag's and merge's preflight stop on one that is not the build's.
:::


## 9. Files the user moves, and the plan memo

:::{bld} The move is matched on size, time and name
:id: BLD-move_match
:status: ruled
:realises: RUL-move_recognized, RUL-memo_proves_no_move

Prep's plan SHALL match, before laying the plan memo under the database, the rows of the workspace database whose path
is not in the inventory against the inventoried files under `6-photos-by-dest` that have no row, by size, `mtime_ns`
and exact basename; a triple held by more than one row or more than one file matches nothing.
:::

:::{bld} A recognized move is a database write
:id: BLD-carried_row
:status: ruled
:realises: RUL-moved_file_carried, RUL-log_follows_retaken_fingerprint

Prep's plan SHALL carry a matched row whose fingerprint passes {need}`BLD-fingerprint_method` and whose metadata is
fresh as a `db_upsert` of it at the new path with the file's size, `mtime_ns` and inode; a matched stale row moves to
the new path in the planning's working state, where the freshness gate judges it as any row and the file's `db_upsert`
there is planned whatever it holds; each recognized move's `db_upsert` names the path it came from (`moved_from`), by
which prep's log finds the entry of a photo whose fingerprint changed with the move. The old path is left to the ghost
prunes; an unmatched row is a ghost, and its file is read as new.
:::

:::{bld} A planned move carries its row
:id: BLD-move_row_effects
:status: ruled
:realises: RUL-reuse_valid_work, RUL-database_matches_files, RUL-quarantined_leaves_database

Each move or rename in prep's plan SHALL carry its database effects — the row of its source removed and, but for a
quarantine move, the file's row with its fingerprint and metadata written at its destination — applied by execute once
the operation succeeds.
:::

:::{bld} A run's database effects are one transaction
:id: BLD-database_effects_one_transaction
:status: ruled
:realises: RUL-database_matches_files

Execute SHALL apply the database effects of all its operations in one transaction, committed once every operation
has been carried out and checked, and rolled back where the run fails before that — the files being what the next
plan reads, the database is then as the earlier run left it.
:::

:::{bld} The plan memo is `photos-00-plan-memo.db`
:id: BLD-plan_memo
:status: ruled
:realises: RUL-plan_memo_kept, RUL-database_over_memo, RUL-memo_entry_same_tests, RUL-memo_never_changes_plan, RUL-memo_tracks_workspace

The plan memo SHALL be the SQLite file `photos-00-plan-memo.db` in `.photos-ingest/`, one row per path with its size,
`mtime_ns` and the file's row as read, replaced whole by each plan with its media files holding both a fingerprint and a
metadata record; read, its entries lie under the database's rows and pass the same reuse tests, and failing to open,
read or write it warns and goes on.
:::


## 10. Duplicates and failures beside photos by destination

:::{bld} A failed fingerprint is recorded as failed
:id: BLD-failed_fingerprint
:status: ruled
:realises: RUL-failed_fingerprint_no_duplicate, RUL-failed_fingerprint_blocks, RUL-failed_fingerprint_retried

A fingerprint that could not be taken SHALL be recorded with the status `failed` and no value; prep's duplicate grouping
passes it over, its plan records a blocker for each such file outside `6-photos-by-dest`, and neither the workspace
database nor the plan memo offers it for reuse.
:::

:::{bld} The handoff names each duplicate's kept copy
:id: BLD-duplicate_evidence
:status: ruled
:realises: RUL-duplicate_recorded_with_kept

Each duplicate's quarantine move SHALL carry its evidence — its path, the copy kept and the shared fingerprint — which
the quarantine manifest and the handoff record, the handoff also under the destination folder of a kept copy in
`6-photos-by-dest`.
:::

:::{bld} Each quarantine move names its kind
:id: BLD-quarantine_reasons
:status: ruled
:realises: RUL-only_duplicates_recorded_as_duplicates, RUL-set_aside_counted_by_reason

Each quarantine move SHALL carry its `kind` — `duplicate`, `exiftool_leftover`, `dump_dotfile` or `raw_culled`
({need}`BLD-culled_raw_found`) — into its manifest entry; the plan's report counts the moves by kind in
`quarantined_by_reason`, its duplicate counts taking only `duplicate`; the handoff's `diagnostics.duplicates_or_conflicts`
and each destination folder's duplicates hold the duplicates alone, the others listed under
`diagnostics.quarantined_not_duplicates` with their kind; and prep's log records the duplicates alone as duplicates.
:::


## 11. The metadata prep keeps for geotag

:::{bld} Metadata is read by exiftool, by group
:id: BLD-metadata_extraction
:status: ruled
:realises: RUL-metadata_kept_for_geotag, RUL-metadata_group_order, RUL-metadata_freshness

Prep SHALL read metadata with `exiftool -json -n -a -G0`, taking each field from the first group holding it in the
order `EXIF`, `XMP`, `MakerNotes`, `IPTC`, `QuickTime`, `File` — `Composite` first for the GPS position — and a time
field from the first group holding a valid time in it; it keeps the fields in `metadata_cache.parsed_json` with the
recorded time's field and group, stamped with `exiftool`, its version, the field-set version, the SHA-256 of the
options, the metadata-schema version and the camera-group-key version.
:::

:::{bld} A metadata read that failed is a blocker
:id: BLD-metadata_failure_blocker
:status: ruled
:realises: RUL-metadata_failure_blocks

A media file whose folder exiftool's batch failed on, or which is missing from its batch's result, SHALL have its
metadata recorded `extraction_failed`, and prep's plan records a blocker naming it, `6-photos-by-dest` included: for a
file whose folder's batch failed, always; for one missing from the result, unless the database holds a fresh record of
its metadata ({need}`BLD-metadata_extraction`), which is kept.
:::

:::{bld} The other time fields are kept by their group
:id: BLD-other_time_fields_read
:status: ruled
:realises: RUL-metadata_kept_for_geotag, RUL-other_capture_times_corrected

Prep SHALL keep in `parsed_json`, each under its group-qualified name and from that group alone, `EXIF:CreateDate`,
`EXIF:OffsetTimeDigitized`, `XMP:DateCreated`, `IPTC:DateCreated` and `IPTC:TimeCreated`, so geotag knows which of the
time fields it rewrites a photo holds.
:::

:::{bld} The handoff's camera groups and destination folders
:id: BLD-handoff_grouping_facts
:status: ruled
:realises: RUL-grouping_facts_reported

The handoff SHALL carry `camera_groups` — each group's key, files and count, identity fields, earliest and latest
recorded time, native-GPS, missing-GPS and missing-time counts, cache freshness and the device class the configuration
gives it — and `destination_folders` — each folder's path, files scanned, camera groups, time range, native-GPS,
missing-GPS and `GPSProcessingMethod` counts, cache freshness, and the duplicates whose kept copy it holds.
:::


## 12. Plan, dry run, execution

:::{bld} What prep's plan records
:id: BLD-prep_plan_contents
:status: ruled
:realises: RUL-plan_carried_out_by_its_code, RUL-new_file_restales_plan

`photos-10-prep-plan.json` SHALL record its id, its schema version, its command, the configuration's hash, the
fingerprint of the code that made it ({need}`BLD-code_fingerprint`), its operations in order, its blockers and warnings,
the size and modification time of each file it leaves as it is, its metadata dependencies, every path its scan found,
and a summary.
:::

:::{bld} Folder removals are `rmdir` operations
:id: BLD-folder_removals
:status: ruled
:realises: RUL-emptied_folders_removed

Prep's plan SHALL end with an `rmdir` for each folder it leaves holding no file — under `0-sources`,
`4-videos-by-date` and `5-photos-by-date`, and on the first run the dump's own top-level folders — found by replaying
its moves over the files on disk, hidden ones included, deepest folder first; execute removes one only if it is then
empty, journals a folder found not empty or not removable as skipped, and warns of it.
:::


## 13. The quarantine

:::{bld} The quarantine's layout and manifest
:id: BLD-quarantine_layout
:status: ruled
:realises: RUL-evidence_before_quarantine, RUL-unreadable_manifest_kept

A quarantined file SHALL go to `.photos-ingest-quarantine/<plan-id>/` at its workspace path, its entry — original path,
quarantine path, the copy kept, the fingerprint and the plan id — appended to that folder's `manifest.json` before the
move; the manifest is replaced whole at each append, and one found unreadable is set aside as
`manifest.json.corrupt-<time>-<random>` and a new one begun — or, where it cannot be set aside, the quarantine move
fails before the file is moved, the manifest left as it was.
:::

:::{bld} The prune's record is `photos-16-prune-record.json`
:id: BLD-prune_record
:status: ruled
:realises: RUL-prune_recorded, RUL-prune_record_kept

`prep prune-quarantine --yes` SHALL, before it removes anything and when it selects at least one run, write
`photos-16-prune-record.json` in `.photos-ingest/` through {need}`BLD-plan_backups`' set-aside: its time, its selectors,
and for each `<plan-id>` folder it removes, every file in it with its bytes and the folder's `manifest.json` as it
read it (null where it cannot be read). A listing prune writes none.
:::

:::{bld} `prune-quarantine` and its selectors
:id: BLD-prune_command
:status: ruled
:realises: RUL-prune_explicit, RUL-quarantine_footprint_reported, RUL-prune_age_at_least_one_day

`prep prune-quarantine` SHALL remove whole `<plan-id>` folders of the quarantine, selected by `--plan-id` (repeatable)
or `--older-than-days` — a run's age taken from the time in its plan id, the two selecting the runs either names —
listing them with their files and bytes and deleting only with `--yes`, and with no selector only with `--all` too; the
plan's summary carries the quarantine's footprint. An age below one day is refused; a folder whose name gives no time is never selected by age, and is listed as such.
:::


## 14. The handoff and prep's log

:::{bld} What the handoff holds
:id: BLD-handoff_content
:status: ruled
:realises: RUL-handoff_describes_workspace, RUL-prep_records_on_success

Prep's execute SHALL write `photos-11-handoff.json` last but for the database image and the mark, through a temporary
file renamed over it, holding: `schema_version`, `tool`, `run_metadata` (plan and execution ids), `cache_fingerprint`,
`folders_scanned` (the managed folders but `1-strays`, each with whether prep may change it), `files` (sorted, each with
its path, size, `mtime_ns`, `inode` — as the file's database row last recorded it — media class, fingerprint and its
status, folder and metadata),
`filename_timestamp_format`, `camera_groups`, `destination_folders` ({need}`BLD-handoff_grouping_facts`),
`diagnostics` (duplicates, the other files quarantined, blockers, warnings, quarantine footprint), `depends_on` (configuration, prep log, journal,
final inventory, metadata extractor, plan and database versions, image engine) and `content_fingerprint`.
:::

:::{bld} The handoff's content fingerprint
:id: BLD-handoff_content_fingerprint
:status: ruled
:realises: RUL-handoff_deterministic

`content_fingerprint` SHALL be the SHA-256 of the handoff serialized with sorted keys, without the keys `run_metadata`,
`diagnostics`, `execution_journal`, `prep_log`, `content_fingerprint`, `cache_freshness` and `conflicts_or_duplicates`
wherever they appear — the last two being each camera group's and destination folder's run-scoped counts and
duplicates. Each file's `inode` is in what it covers, as it is in `cache_fingerprint`: a file whose row is written again
at another inode changes both, though its size, time and fingerprint do not.
:::

:::{bld} An unreadable `photos-15-prep-log.json` is a blocker
:id: BLD-unreadable_prep_log
:status: ruled
:realises: RUL-unreadable_prep_log_stops

Where `photos-15-prep-log.json` exists and is not readable JSON holding a `photos` object, prep's plan SHALL record a
blocker naming it, execute's preflight refuses on the same before any change, and the log's rebuild fails the run
rather than read it as empty; with no such file, the earlier log is empty.
:::

:::{bld} How prep's log is built
:id: BLD-prep_log_build
:status: ruled
:realises: RUL-prep_log_derived, RUL-prep_log_records_set_aside, RUL-log_follows_retaken_fingerprint, RUL-partial_history_shown

Prep's execute SHALL build `photos-15-prep-log.json` from the plan's moves and renames replayed per file, the
quarantine evidence and the final database rows, merged onto the prior log by fingerprint: an entry whose old value is
nowhere in the workspace and whose `prep_path` holds a file of a new value that this run's plan gives no step moves to
it with a `fingerprint_retaken` step, the same file unchanged ({need}`BLD-retake_same_file`); an entry whose file is elsewhere with no step of this run gains a `user` step `moved_to_by_dest` — `moved_to_by_date` where the file is not in photos by destination; and a file in
a prep-organized folder with no recorded history gets an entry marked `partial`, with a warning.
:::


## 15. Concurrency, determinism, and what a run shows

:::{bld} A retaken fingerprint is the same file's
:id: BLD-retake_same_file
:status: ruled
:realises: RUL-retake_only_unchanged_file

A `fingerprint_retaken` step SHALL be given only where the record of the workspace's state ({need}`BLD-workspace_record`)
read as the execute begins has, at the path the entry was left at — or the path the user moved the file from — the size,
`mtime_ns` and inode of the file's new database row, and a fingerprint whose strategy or engine version is not the new
one's.
:::

:::{bld} A gone photo's entry is copied unchanged
:id: BLD-gone_photo_entry
:status: ruled
:realises: RUL-gone_photo_entry_carried

An entry of the prior `photos-15-prep-log.json` whose fingerprint no database row holds, which this run's plan gives no
step and no quarantine record, and which no `fingerprint_retaken` claims ({need}`BLD-prep_log_build`), SHALL be written
into the new log unchanged, `prep_path` included.
:::

:::{bld} The tools' workers
:id: BLD-tool_workers
:status: ruled
:realises: RUL-tool_failure_retried

Prep SHALL read metadata through persistent `exiftool -stay_open` workers and fingerprint photos through a persistent
`magick -script -` process per thread — each file read, given `-colorspace sRGB -depth 8`, its `%#` printed, then
`-delete 0--1`, a `{ready}` line closing its reply — falling back to `identify` per file where `magick` is absent; it
starts `ffmpeg` per video. Each tool gets two attempts per file, a dead worker restarted between them.
:::

:::{bld} A silent `identify` is killed after ten seconds
:id: BLD-identify_silence_limit
:status: ruled
:realises: RUL-tool_failure_retried, RUL-tool_failure_never_valid

Where `magick` is absent, each per-file `identify` attempt SHALL be killed once ten seconds pass with no output from it,
the attempt counting as failed — so a photo whose decode is slower than that fails both attempts and its fingerprint is
recorded as failed; the persistent `magick` worker has no such limit.
:::

:::{bld} Planning in a fixed order
:id: BLD-planning_order
:status: ruled
:realises: RUL-jobs_change_nothing

Prep SHALL walk the workspace and take its files' sizes and times on one thread, sorted, before any parallel work, and
gather the workers' results by path; two plans of one workspace differ only in `plan_id`, `created_at` and the
operations' ids.
:::

:::{bld} The re-fingerprint summary
:id: BLD-rehash_summary
:status: ruled
:realises: RUL-rehash_explained

The plan's `performance_and_cache.rehash_summary` SHALL count the media files fingerprinted this run by reason — `new`,
`moved-unmatched`, `size-changed`, `mtime-changed`, `metadata-stale`, `failed-before`, `engine-changed` — with a sample
of the unexpected ones, and the fingerprints reused from the plan memo.
:::
