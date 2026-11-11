# Prep — what it guarantees

What the first phase, {need}`DEF-prep`, guarantees, beyond what [the shared contract](shared.md) binds every phase
to. *Why* each holds is in [the rationale](../rationale/prep.md); *how this build meets it*, in
[the build](../build/prep.md).

## 2. What prep does, and what it leaves alone

:::{rul} Prep corrects no time and no position
:id: RUL-prep_no_time_or_gps
:status: ruled
:criticality: high
:anti: yes
:verify: required
:aliases: prep-no-time-gps-correction-1, prep-no-timestamp-correction-1
:uses: DEF-prep

Prep SHALL make no correction to a file's time or position: it plans, infers, writes and applies none.
:::

:::{rul} Prep leaves photos by destination as it finds it
:id: RUL-prep_leaves_by_dest_as_found
:status: ruled
:criticality: high
:anti: yes
:verify: required
:aliases: prep-by-dest-readonly-1, prep-no-perform-bydest-move-1, prep-bydest-never-quarantined-1, prep-scan-split-inventory-1, prep-move-recognition-no-mutate-bydest-1
:uses: DEF-prep, DEF-managed_folders

Prep SHALL leave photos by destination as it finds it: never moving a file into it, out of it or within it, nor
renaming, quarantining, deleting or writing one there.
:::

:::{rul} Prep puts videos by date
:id: RUL-videos_by_date
:status: ruled
:criticality: med
:verify: required
:aliases: prep-videos-date-organized-1
:uses: DEF-prep, DEF-managed_folders, DEF-timestamp_name

Prep SHALL put each video it takes in that has a recorded time into videos by date, under its timestamp name.
:::

## 3. The workspace's first run, and the strays

:::{rul} Initializing, prep moves the dump into the inbox
:id: RUL-init_moves_dump_to_inbox
:status: ruled
:criticality: high
:verify: required
:aliases: prep-init-moves-base-into-sources-1, prep-init-excludes-managed-from-move-1
:uses: RUL-first_dump_at_top_level, DEF-managed_folders, DEF-control_records

Initializing a workspace, prep SHALL move every entry at its top level that is not a managed folder or the control
records' place — files and whole folders alike, their structure kept — into the inbox.
:::

:::{rul} A dump folder named as a managed folder is that folder
:id: RUL-dump_folder_named_as_managed
:status: ruled
:criticality: med
:verify: required
:aliases: prep-reserved-names-not-moved-1
:refines: RUL-init_moves_dump_to_inbox

Initializing, prep SHALL take a folder at the top level named as a managed folder for that managed folder, never moving
it into the inbox.
:::

:::{rul} A workspace is marked initialized last
:id: RUL-initialized_marked_last
:status: ruled
:criticality: high
:verify: required
:aliases: prep-sentinel-written-last-1
:uses: RUL-structure_built_once

Prep SHALL mark a workspace initialized only once its initializing run has succeeded, every managed folder and the
control records' place in it.
:::

:::{rul} An interrupted initialization is taken up again
:id: RUL-init_taken_up_again
:status: ruled
:criticality: med
:verify: required
:aliases: prep-crash-init-reenters-harmlessly-1
:refines: RUL-initialized_marked_last

A run that finds a workspace not marked initialized SHALL initialize it, keeping what an interrupted initialization
already did: the folders it made, and the dump already in the inbox.
:::

:::{rul} A stray leaves no trace but its move
:id: RUL-strays_leave_no_trace
:status: ruled
:criticality: med
:anti: yes
:verify: required
:aliases: prep-strays-inert-1
:uses: DEF-strays_folder

A file prep moves to the strays folder SHALL be recorded nowhere but in the journal of that move: no fingerprint, no row
in the workspace database, no entry in any log, no place in the archival package.
:::

## 6. What prep refuses to work on

:::{rul} A file in the other kind's folder blocks prep
:id: RUL-band_misplacement_blocks
:status: ruled
:criticality: high
:anti: yes
:verify: required
:aliases: prep-band-misplacement-blocks-1, prep-video-only-in-videos-band-1

A video in photos by date or photos by destination, or a photo in videos by date, SHALL block prep's plan.
:::

:::{rul} An editing sidecar blocks prep
:id: RUL-sidecar_blocks
:status: ruled
:criticality: high
:anti: yes
:verify: required
:aliases: prep-forbidden-sidecar-blocks-1

An editing sidecar — a file holding a photo's development beside it — found anywhere prep inventories SHALL block
prep's plan.
:::

:::{rul} A file of no media class outside the inbox blocks prep
:id: RUL-other_outside_inbox_blocks
:status: ruled
:criticality: med
:anti: yes
:verify: required

A file of no media class found in a managed folder other than the inbox SHALL block prep's plan, named.
:::

:::{rul} Every blocker is reported
:id: RUL-blockers_all_reported
:status: ruled
:criticality: med
:anti: yes
:verify: required
:aliases: prep-blockers-reported-not-skipped-1

Prep SHALL report every blocker it finds, each naming what blocks, never skipping one silently.
:::

:::{rul} Media set aside as strays is pointed out
:id: RUL-stray_media_hinted
:status: ruled
:criticality: low
:verify: required
:aliases: prep-stray-media-warning-1, prep-stray-media-warning-advisory-1

When files prep is about to set aside as strays are images or videos by their content, prep SHALL warn, naming their
extension.
:::


## 7. The prep pipeline

:::{rul} A dump keeps its folders in the inbox
:id: RUL-inbox_kept_as_dumped
:status: ruled
:criticality: med
:anti: yes
:verify: required
:aliases: prep-no-flatten-sources-1
:uses: DEF-managed_folders

Prep SHALL move no file from one place in the inbox to another: a dump's folders stay as they arrived until each file
leaves the inbox.
:::

:::{rul} A filed media file stays in its folder
:id: RUL-filed_file_stays
:status: ruled
:criticality: med
:anti: yes
:verify: required
:aliases: prep-files-in-managed-left-1
:uses: DEF-managed_folders

A media file outside the inbox SHALL stay in the folder it is in, unless prep sets it aside as a duplicate or it is a
dated file outside its day folder.
:::

:::{rul} A dated file lies in its day folder
:id: RUL-by_date_in_day_folder
:status: ruled
:criticality: med
:verify: required
:aliases: prep-day-subfolder-grouping-1, prep-relocate-misfiled-bydate-1
:uses: DEF-managed_folders, DEF-recorded_time

Each file in photos by date or videos by date SHALL lie in the folder of its recorded time's day, directly under its
band; prep moves one that does not into it — or, with no recorded time, into missing metadata.
:::

:::{rul} Prep puts photos by date
:id: RUL-photos_by_date
:status: ruled
:criticality: med
:verify: required
:aliases: prep-route-by-class-timestamp-1
:uses: DEF-prep, DEF-managed_folders, DEF-timestamp_name, DEF-recorded_time

Prep SHALL put each photo it takes in that has a recorded time into photos by date, under its timestamp name.
:::

:::{rul} Media with no recorded time goes to missing metadata
:id: RUL-untimed_to_missing_metadata
:status: ruled
:criticality: med
:verify: required
:aliases: prep-missing-metadata-flat-1
:uses: DEF-managed_folders, DEF-untimed_name, DEF-recorded_time

Prep SHALL put each media file it takes in with no recorded time directly into missing metadata, no day folder between,
under its untimed name.
:::

:::{rul} Non-media leaves the inbox for the strays folder, as it came
:id: RUL-inbox_non_media_to_strays
:status: ruled
:criticality: med
:verify: required
:uses: DEF-strays_folder, DEF-managed_folders

Prep SHALL move each file of no media class in the inbox into the strays folder's subfolder for the run, at its place
under the inbox and with its name unchanged.
:::

:::{rul} A file in missing metadata stays there
:id: RUL-missing_metadata_stays
:status: ruled
:criticality: low
:anti: yes
:verify: required
:aliases: prep-missing-metadata-no-special-path-1
:uses: DEF-managed_folders, DEF-recorded_time

Prep SHALL leave a file in missing metadata where it is, though it has since gained a recorded time: only the user
moving it back into the inbox takes it through prep again.
:::

:::{rul} A media file's extension is lowercase
:id: RUL-media_extension_lowercase
:status: ruled
:criticality: low
:verify: required
:aliases: prep-normalize-extension-case-1
:uses: DEF-managed_folders

Each media file prep files, or finds outside the inbox, SHALL end with its extension in lowercase.
:::

:::{rul} A duplicate is set aside as it was found
:id: RUL-duplicate_set_aside_as_found
:status: ruled
:criticality: med
:anti: yes
:verify: required
:uses: DEF-fingerprint

Prep SHALL quarantine a duplicate from the place and under the name it had when planned, no other stage of the plan
moving or renaming it first.
:::

:::{rul} A JPEG beside its RAW is set aside
:id: RUL-redundant_jpeg_set_aside
:status: ruled
:criticality: med
:verify: required
:aliases: prep-separate-redundant-jpeg-1
:uses: DEF-managed_folders

Prep SHALL move into redundant JPEGs each JPEG in the inbox that shares its folder and its name, extension aside, with a
raw file — and no other file with it.
:::

:::{rul} Of identical media, one copy is kept
:id: RUL-duplicates_quarantined
:status: ruled
:criticality: high
:verify: required
:aliases: prep-quarantine-extra-copies-1, prep-group-by-fingerprint-class-1
:uses: DEF-fingerprint, DEF-managed_folders

Of the media files prep inventories that share one fingerprint and one media class, prep SHALL keep one and quarantine
every other copy outside photos by destination.
:::

:::{rul} The copy kept is the best filed
:id: RUL-copy_kept_by_folder
:status: ruled
:criticality: med
:verify: required
:aliases: prep-retain-by-folder-priority-1
:refines: RUL-duplicates_quarantined
:uses: DEF-managed_folders

The copy prep keeps SHALL be the one first in this order of the folders the copies lie in when planned — photos by
destination, photos by date, videos by date, redundant JPEGs, missing metadata, the inbox — and, among copies in one
folder, the first by path.
:::

:::{rul} The workspace database matches the files
:id: RUL-database_matches_files
:status: ruled
:criticality: med
:verify: required
:aliases: prep-cache-upsert-stale-1, prep-ghost-prune-1
:uses: DEF-workspace_database

A prep execution SHALL leave the workspace database current: a row for each media file prep inventoried, describing the
file as it now is and where it now is, and no row for a file that is gone.
:::


## 9. Content fingerprinting and cache reuse

:::{rul} A new or changed file is fingerprinted afresh
:id: RUL-fingerprint_taken_afresh
:status: ruled
:criticality: high
:verify: required
:aliases: prep-fingerprint-compute-if-absent-1, prep-fingerprint-recompute-on-change-1
:uses: DEF-fingerprint, DEF-workspace_database

Prep SHALL fingerprint a media file afresh when the workspace database holds no fingerprint for it at its path, or holds
one taken when the file had another size or modification time.
:::

:::{rul} A fingerprint is reused only from the method in use
:id: RUL-fingerprint_method_matches
:status: ruled
:criticality: high
:verify: required
:refines: RUL-reuse_valid_work
:uses: DEF-fingerprint

Prep SHALL reuse a cached fingerprint only when the method that took it is the one now in use for the file's class,
taking again one that does not record its method in full.
:::

:::{rul} A file read again is read whole
:id: RUL-reread_whole
:status: ruled
:criticality: med
:verify: required
:uses: DEF-fingerprint

A media file whose metadata prep reads again — the way metadata is read having changed — SHALL be fingerprinted again
with it.
:::

:::{rul} A database of another schema is not migrated
:id: RUL-cache_schema_not_migrated
:status: ruled
:criticality: high
:verify: required
:uses: DEF-workspace_database

Prep SHALL stop on a workspace database whose recorded schema is not the one it uses, migrating none.
:::


## 10. Files the user moves, and the plan memo

:::{rul} A file the user moved is recognized
:id: RUL-move_recognized
:status: ruled
:criticality: med
:verify: required
:aliases: prep-recognize-bydest-resort-1, prep-ambiguous-move-rescan-1, prep-content-change-overrides-carry-1, prep-cache-distinguish-cases-1
:uses: DEF-workspace_database

Prep SHALL recognize as moved a file new to photos by destination whose size, modification time and name are those of
a file the workspace database holds and that is gone from its path — one only, matched by no other such file and by no
other new file in photos by destination.
:::

:::{rul} A moved file's identity is carried, not read again
:id: RUL-moved_file_carried
:status: ruled
:criticality: high
:verify: required
:aliases: prep-recognize-bydate-to-bydest-move-1, prep-move-carry-forward-drop-old-1
:refines: RUL-reuse_valid_work
:uses: DEF-fingerprint, DEF-workspace_database

Prep SHALL carry a moved file's fingerprint and metadata to its new path, reading nothing of the file but its size and
time, when its row at the old path would have been reused there.
:::

:::{rul} A quarantined file leaves the database
:id: RUL-quarantined_leaves_database
:status: ruled
:criticality: med
:verify: required
:refines: RUL-database_matches_files
:uses: DEF-workspace_database

A file prep has quarantined SHALL be in neither the workspace database nor the handoff.
:::

:::{def} The plan memo
:id: DEF-plan_memo
:status: ruled
:uses: DEF-fingerprint

The **plan memo** is the scratch database where prep's planning keeps what it read of each media file — its fingerprint
and metadata — with the path, size and modification time it read them at.
:::

:::{rul} A plan keeps what it read
:id: RUL-plan_memo_kept
:status: ruled
:criticality: low
:verify: required
:aliases: prep-plan-memo-reuse-1, prep-plan-memo-not-the-cache-1
:refines: RUL-reuse_valid_work
:uses: DEF-plan_memo

Prep's planning SHALL keep in the plan memo the fingerprint and metadata of each media file it read, for a later plan
to reuse.
:::

:::{rul} The database outranks the memo
:id: RUL-database_over_memo
:status: ruled
:criticality: med
:verify: required
:aliases: prep-plan-memo-subordinate-1
:uses: DEF-plan_memo, DEF-workspace_database

Prep SHALL take a file's fingerprint and metadata from the plan memo only where the workspace database holds no row for
its path.
:::

:::{rul} A memo entry passes the database's tests
:id: RUL-memo_entry_same_tests
:status: ruled
:criticality: high
:verify: required
:aliases: prep-plan-memo-freshness-1
:uses: DEF-plan_memo

Prep SHALL reuse an entry of the plan memo only when a row of the workspace database holding it would be reused.
:::

:::{rul} The memo proves no move
:id: RUL-memo_proves_no_move
:status: ruled
:criticality: med
:verify: required
:uses: DEF-plan_memo, DEF-workspace_database

Prep SHALL recognize a moved file from the workspace database alone, never from the plan memo.
:::

:::{rul} The memo never changes the plan
:id: RUL-memo_never_changes_plan
:status: ruled
:criticality: high
:verify: required
:aliases: prep-plan-memo-disposable-1
:uses: DEF-plan_memo

The plan prep makes SHALL be the same whatever the plan memo holds — entries reused, none, or a file that cannot be
read.
:::

:::{rul} The memo holds what the latest plan read
:id: RUL-memo_tracks_workspace
:status: ruled
:criticality: low
:verify: required
:aliases: prep-plan-memo-pruned-1
:uses: DEF-plan_memo

The plan memo SHALL hold entries only for paths the latest plan read.
:::


## 11. Duplicates and failures beside photos by destination

:::{rul} A failed fingerprint matches nothing
:id: RUL-failed_fingerprint_no_duplicate
:status: seed
:criticality: high
:anti: yes
:verify: required
:aliases: prep-unknown-fingerprint-no-dup-1
:uses: DEF-fingerprint

A media file whose fingerprint failed SHALL be found the duplicate of no file, and no file its duplicate.
:::

:::{rul} A failed fingerprint outside photos by destination blocks
:id: RUL-failed_fingerprint_blocks
:status: seed
:criticality: high
:verify: required
:aliases: prep-fingerprint-failure-blocks-1
:uses: DEF-fingerprint

A media file outside photos by destination whose fingerprint failed SHALL block prep's plan.
:::

:::{rul} A failed fingerprint is taken again
:id: RUL-failed_fingerprint_retried
:status: seed
:criticality: high
:verify: required
:uses: DEF-fingerprint

Prep SHALL take a media file's fingerprint again at every run while it has failed.
:::

:::{rul} A duplicate is recorded with the copy kept
:id: RUL-duplicate_recorded_with_kept
:status: seed
:criticality: med
:verify: required
:aliases: prep-dup-against-bydest-quarantine-mutable-1
:refines: RUL-duplicates_quarantined

Prep SHALL record each duplicate it quarantines with the copy it kept, in the quarantine manifest and the handoff.
:::
