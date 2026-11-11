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
that holds one; prep reads the files there for their fingerprint and metadata only (prep §10, §11).
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
:realises: RUL-every_change_journaled

Prep's execute SHALL append each operation's outcome to `journal-<plan-id>.json` as the operation ends, saving the
journal after each.
:::

## 5. What each of prep's records depends on

:::{bld} Prep's dependencies, in full
:id: BLD-prep_dependencies
:status: ruled
:realises: INV-no_stale_use, RUL-unchecked_counts_as_changed
:aliases: prep-artifacts-carry-depends-on-1, prep-record-min-fingerprints-1, prep-fingerprint-algo-recorded-1

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
