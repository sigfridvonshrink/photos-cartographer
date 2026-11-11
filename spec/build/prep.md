# Prep — how this build does it

How this build meets [prep's intent](../intent/prep.md): the files, names, tools and steps. Each item `realises` the
intent it implements. *Why* a choice was made is in [the rationale](../rationale/prep.md).

## 2. What prep does, and what it leaves alone

:::{bld} Prep's operations hold no metadata write
:id: BLD-prep_operation_kinds
:status: ruled
:aliases: prep-allowed-op-types-1
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

## 3. The workspace's first run, and the strays

:::{bld} The mark is `photos-00-workspace-guard`, written last
:id: BLD-workspace_guard
:status: ruled
:realises: RUL-initialized_marked_last

The mark SHALL be the file `photos-00-workspace-guard` in `.photos-ingest/`, which the initializing run's execute writes
after every other operation has succeeded; the managed folders it creates are `0-sources` … `6-photos-by-dest`.
:::

:::{bld} A run's strays go to `1-strays/<plan-id>/`
:id: BLD-strays_per_run
:status: ruled
:realises: RUL-inbox_non_media_to_strays
:aliases: prep-strays-per-run-subfolder-1, prep-strays-no-collision-across-runs-1

Prep SHALL move a run's strays into `1-strays/<plan-id>/`, each at its path under `0-sources/`, so that no two runs
share a folder there.
:::

:::{bld} The configuration is seeded before it is fingerprinted
:id: BLD-seed_before_fingerprints
:status: ruled
:realises: RUL-config_seeded_once
:aliases: prep-seed-before-fingerprint-1

Prep SHALL seed the configuration at the start of its run, before any fingerprint of it is taken, so that every
fingerprint, the handoff's recorded hash among them, is of the file as it stands in the workspace.
:::

## 4. The plan, validated, then carried out

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

## 5. What each of prep's records depends on

:::{bld} Prep's dependencies, in full
:id: BLD-prep_dependencies
:status: ruled
:realises: INV-no_stale_use, RUL-unchecked_counts_as_changed
:aliases: prep-artifacts-carry-depends-on-1, prep-record-min-fingerprints-1, prep-fingerprint-algo-recorded-1, prep-bydest-precondition-recorded-1

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

:::{bld} A log not vouched for is not "nothing to do"
:id: BLD-prep_fast_stop_checks_log
:status: ruled
:realises: RUL-unchecked_counts_as_changed

Prep's stop on an already-prepped workspace SHALL not apply while the log's hash differs from what the handoff records,
so that prep's next execute rewrites both.
:::

## 6. What prep refuses to work on

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


## 7. The prep pipeline

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
:aliases: prep-collision-resolved-in-memory-1

Each stage of prep's planning SHALL work from the path the stages before it gave each file, allocating every name
against the names on disk and those already planned.
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

:::{bld} The database is reconciled by planned operations
:id: BLD-database_ops
:status: ruled
:realises: RUL-database_matches_files

Prep's plan SHALL refresh a stale database row with a `db_upsert`, and remove with a `db_remove` the row of a file gone
that no move explains and whose path no planned move fills again — that row is the move's to replace.
:::


## 8. Naming conventions

:::{bld} A day's folder is named `YYYY-MM-DD`
:id: BLD-day_folder_name
:status: ruled
:realises: RUL-by_date_in_day_folder
:aliases: prep-date-name-format-1

A day's folder SHALL be named `YYYY-MM-DD` from its recorded time's date, whatever `filename_timestamp_format` is.
:::


## 9. Content fingerprinting and cache reuse

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
:realises: RUL-fingerprint_method_matches

Each fingerprint SHALL record its strategy — `image-content-hash-v1` for a photo, `video-md5-v1` for a video — and a
photo's the ImageMagick version that took it; a cached photo fingerprint is reused when both match the build's, a video's
when its strategy does.
:::


## 10. Files the user moves, and the plan memo

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
:realises: RUL-moved_file_carried
:aliases: prep-move-recognition-before-ghost-1

Prep's plan SHALL carry a matched row whose fingerprint passes {need}`BLD-fingerprint_method` and whose metadata is
fresh as a `db_upsert` of it at the new path with the file's size, `mtime_ns` and inode, its old path left to the
ghost prunes; an unmatched or stale row is a ghost, and its file is read as new.
:::

:::{bld} A planned move carries its row
:id: BLD-move_row_effects
:status: ruled
:realises: RUL-reuse_valid_work, RUL-database_matches_files, RUL-quarantined_leaves_database
:aliases: prep-fingerprint-carry-forward-move-1, prep-move-row-carries-facts-1, prep-cache-update-from-validated-plan-1, prep-cache-write-after-fs-verified-1

Each move or rename in prep's plan SHALL carry its database effects — the row of its source removed and, but for a
quarantine move, the file's row with its fingerprint and metadata written at its destination — applied by execute once
the operation succeeds.
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


## 11. Duplicates and failures beside photos by destination

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


## 12. The metadata prep keeps for geotag

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

:::{bld} The handoff's camera groups and destination folders
:id: BLD-handoff_grouping_facts
:status: ruled
:realises: RUL-grouping_facts_reported

The handoff SHALL carry `camera_groups` — each group's key, files and count, identity fields, earliest and latest
recorded time, native-GPS, missing-GPS and missing-time counts, cache freshness and the device class the configuration
gives it — and `destination_folders` — each folder's path, files scanned, camera groups, time range, native-GPS,
missing-GPS and `GPSProcessingMethod` counts, cache freshness, and the duplicates whose kept copy it holds.
:::


## 14. Plan, dry run, execution

:::{bld} What prep's plan records
:id: BLD-prep_plan_contents
:status: ruled
:realises: RUL-plan_carried_out_by_its_code, RUL-new_file_restales_plan
:aliases: prep-plan-serialized-contents-1

`photos-10-prep-plan.json` SHALL record its id, its schema version, its command, the configuration's hash, the
fingerprint of the code that made it ({need}`BLD-code_fingerprint`), its operations in order, its blockers and warnings,
the size and modification time of each file it leaves as it is, its metadata dependencies, every path its scan found,
and a summary.
:::

:::{bld} The code's fingerprint
:id: BLD-code_fingerprint
:status: ruled
:realises: RUL-plan_carried_out_by_its_code

The code's fingerprint SHALL be the SHA-256 over the files of the `cartographer` package the zipapp ships, as loaded —
from the zipapp or a checkout, which agree — each one's path and bytes in path order; execute and dry run compare
the plan's with the running code's, after its schema version and command and before its operations.
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
