# Prep — what it guarantees

What the first phase, {need}`DEF-prep`, guarantees, beyond what [the shared contract](shared.md) binds every phase
to. *Why* each holds is in [the rationale](../rationale/prep.md); *how this build meets it*, in
[the build](../build/prep.md).

## 1. What prep does, and what it leaves alone

:::{rul} Prep corrects no time and no position
:id: RUL-prep_no_time_or_gps
:status: ruled
:criticality: high
:anti: yes
:verify: required
:uses: DEF-prep

Prep SHALL make no correction to a file's time or position: it plans, infers, writes and applies none.
:::

:::{rul} Prep leaves photos by destination as it finds it
:id: RUL-prep_leaves_by_dest_as_found
:status: ruled
:criticality: high
:anti: yes
:verify: required
:uses: DEF-prep, DEF-managed_folders

Prep SHALL leave photos by destination as it finds it: never moving a file into it, out of it or within it, nor
renaming, quarantining, deleting or writing one there.
:::

## 2. The workspace's first run, and the strays

:::{rul} Initializing, prep moves the dump into the inbox
:id: RUL-init_moves_dump_to_inbox
:status: ruled
:criticality: high
:verify: required
:uses: RUL-first_dump_at_top_level, DEF-managed_folders, DEF-control_records

Initializing a workspace, prep SHALL move every entry at its top level that is not a managed folder, the control
records' place or hidden ({need}`RUL-dump_hidden_files_quarantined`) — files and whole folders alike, their
structure kept — into the inbox.
:::

:::{rul} A dump folder named as a managed folder is that folder
:id: RUL-dump_folder_named_as_managed
:status: ruled
:criticality: med
:verify: required
:refines: RUL-init_moves_dump_to_inbox

Initializing, prep SHALL take a folder at the top level named as a managed folder for that managed folder, never moving
it into the inbox.
:::

:::{rul} A dump file whose place in the inbox is taken is suffixed
:id: RUL-init_taken_place_suffixed
:status: ruled
:criticality: high
:anti: yes
:verify: required
:refines: RUL-init_moves_dump_to_inbox
:uses: RUL-suffix_no_clobber

Initializing, prep SHALL move a dump file whose place in the inbox is already taken — by a file there or one planned
there, ignoring case — into the same folder of the inbox under its name with a differentiating suffix, never over the
file holding that place.
:::

:::{rul} A workspace is marked initialized last
:id: RUL-initialized_marked_last
:status: ruled
:criticality: high
:verify: required
:uses: RUL-structure_built_once

Prep SHALL mark a workspace initialized only once its initializing run has succeeded, every managed folder and the
control records' place in it.
:::

:::{rul} An interrupted initialization is taken up again
:id: RUL-init_taken_up_again
:status: ruled
:criticality: med
:verify: required
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
:uses: DEF-strays_folder, DEF-archival_package

A file prep moves to the strays folder SHALL be recorded nowhere but in the plan that moves it, the journal of that move
and the record of the workspace's state ({need}`RUL-execution_records_state`) — no fingerprint, no row of the files the
workspace database describes, no entry in the handoff or any log — the archival package holding it only as it holds that
plan and that record.
:::

## 5. What prep refuses to work on

:::{rul} A file in the other kind's folder blocks prep
:id: RUL-band_misplacement_blocks
:status: ruled
:criticality: high
:anti: yes
:verify: required
:uses: DEF-managed_folders

A video in photos by date or photos by destination, or a photo in videos by date, SHALL block prep's plan.
:::

:::{rul} An editing sidecar blocks prep
:id: RUL-sidecar_blocks
:status: ruled
:criticality: high
:anti: yes
:verify: required
:excepts: RUL-inbox_non_media_never_blocks
:uses: DEF-development

An editing sidecar — a file holding a photo's development beside it — found anywhere prep inventories SHALL block
prep's plan.
:::

:::{rul} A file of no media class outside the inbox blocks prep
:id: RUL-other_outside_inbox_blocks
:status: ruled
:criticality: med
:anti: yes
:verify: required
:uses: DEF-managed_folders

A file of no media class found in a managed folder other than the inbox SHALL block prep's plan.
:::

:::{rul} Every blocker is reported
:id: RUL-blockers_all_reported
:status: ruled
:criticality: med
:anti: yes
:verify: required

Prep SHALL report every blocker it finds, never skipping one silently.
:::

:::{rul} A blocker names what blocks
:id: RUL-blocker_names_what_blocks
:status: ruled
:criticality: med
:verify: required
:refines: RUL-blockers_all_reported

Each blocker prep reports SHALL name what blocks.
:::

:::{rul} Media set aside as strays is pointed out
:id: RUL-stray_media_hinted
:status: ruled
:criticality: low
:verify: required

When files prep is about to set aside as strays are images or videos by their content, prep SHALL warn.
:::

:::{rul} The warning names the strays' extension
:id: RUL-stray_media_hint_names_extension
:status: ruled
:criticality: low
:verify: required
:refines: RUL-stray_media_hinted

The warning that strays are images or videos SHALL name their extension.
:::


## 6. The prep pipeline

:::{rul} A dump keeps its folders in the inbox
:id: RUL-inbox_kept_as_dumped
:status: ruled
:criticality: med
:anti: yes
:verify: required
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
:uses: DEF-managed_folders

A media file outside the inbox SHALL stay in the folder it is in, unless prep sets it aside as a duplicate or as the
JPEG of a culled RAW, it is a dated file outside its day folder or with no recorded time, or it lies in missing
metadata and has gained a recorded time.
:::

:::{rul} A dated file lies in its day folder
:id: RUL-by_date_in_day_folder
:status: ruled
:criticality: med
:verify: required
:uses: DEF-managed_folders, DEF-recorded_time

Each file in photos by date or videos by date SHALL lie in the folder of its recorded time's day, directly under its
band; prep moves one that does not into it.
:::

:::{rul} A dated folder's file with no recorded time goes to missing metadata
:id: RUL-by_date_untimed_to_missing_metadata
:status: ruled
:criticality: med
:verify: required
:refines: RUL-by_date_in_day_folder
:excepts: RUL-filed_file_stays
:uses: DEF-managed_folders, DEF-recorded_time

Prep SHALL move a file in photos by date or videos by date that has no recorded time into missing metadata.
:::

:::{rul} Prep puts photos by date
:id: RUL-photos_by_date
:status: ruled
:criticality: med
:verify: required
:uses: DEF-prep, DEF-managed_folders, DEF-timestamp_name, DEF-recorded_time

Prep SHALL put each photo it takes in that has a recorded time into photos by date, under its timestamp name.
:::

:::{rul} Prep puts videos by date
:id: RUL-videos_by_date
:status: ruled
:criticality: med
:verify: required
:uses: DEF-prep, DEF-managed_folders, DEF-timestamp_name

Prep SHALL put each video it takes in that has a recorded time into videos by date, under its timestamp name.
:::

:::{rul} Media with no recorded time goes to missing metadata
:id: RUL-untimed_to_missing_metadata
:status: ruled
:criticality: med
:verify: required
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

:::{rul} Non-media in the inbox never blocks
:id: RUL-inbox_non_media_never_blocks
:status: ruled
:criticality: med
:anti: yes
:verify: required
:refines: RUL-inbox_non_media_to_strays

A file of no media class in the inbox SHALL NOT block a run for being of no media class, nor for a failed read of
its metadata — an editing sidecar ({need}`RUL-sidecar_blocks`) and a track file ({need}`RUL-track_files_block_prep`)
excepted.
:::

:::{rul} A file given a time in missing metadata is filed on
:id: RUL-time_given_filed_on
:status: ruled
:criticality: med
:verify: required
:uses: DEF-managed_folders, DEF-recorded_time, DEF-timestamp_name, RUL-photos_by_date, RUL-videos_by_date

Prep SHALL file each media file in missing metadata that has gained a recorded time as it files one of a new dump: a
photo into photos by date, a video into videos by date, in its day's folder under its timestamp name.
:::

:::{rul} A media file's extension is lowercase
:id: RUL-media_extension_lowercase
:status: ruled
:criticality: low
:verify: required
:uses: DEF-managed_folders

Each media file prep files, or finds outside the inbox and photos by destination, SHALL end with its extension in
lowercase.
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
:uses: DEF-managed_folders

Prep SHALL move into redundant JPEGs each JPEG in the inbox that shares its folder and its name, with case, extension
aside, with a raw file.
:::

:::{rul} Only a JPEG beside its RAW is set aside
:id: RUL-redundant_jpeg_only
:status: ruled
:criticality: med
:verify: required
:refines: RUL-redundant_jpeg_set_aside
:uses: DEF-managed_folders

Prep SHALL move into redundant JPEGs no file but a JPEG in the inbox that shares its folder and its name, extension
aside, with a raw file.
:::

:::{rul} A culled RAW takes its set-aside JPEG
:id: RUL-culled_raw_takes_its_jpeg
:status: ruled
:criticality: med
:verify: required
:excepts: RUL-filed_file_stays
:uses: DEF-managed_folders, DEF-fingerprint

When the user culls a RAW beside which prep set a JPEG aside — from photos by date or photos by destination, at any
time before the workspace is sealed — prep's next plan SHALL quarantine that JPEG.
:::

:::{rul} A RAW is culled only when its content is gone by hand
:id: RUL-culled_raw_known_by_content
:status: ruled
:criticality: high
:anti: yes
:verify: required
:refines: RUL-culled_raw_takes_its_jpeg
:uses: DEF-managed_folders, DEF-fingerprint

Prep SHALL NOT take a set-aside JPEG with a RAW unless it recorded the two as a pair, no file in the managed folders
holds the RAW's fingerprint, and a comparison with a recorded state found the RAW deleted by hand — so a RAW moved or
renamed within the workspace, under any name, is never taken for culled.
:::

:::{rul} A RAW moved out of the workspace is culled
:id: RUL-culled_raw_moved_out
:status: ruled
:criticality: med
:verify: required
:refines: RUL-culled_raw_takes_its_jpeg
:uses: DEF-managed_folders

A RAW the user moves out of the workspace, kept whole elsewhere, SHALL take its set-aside JPEG as one deleted does.
:::

:::{rul} Prep's log says the JPEG went with its culled RAW
:id: RUL-culled_raw_jpeg_logged
:status: ruled
:criticality: med
:verify: required
:refines: RUL-culled_raw_takes_its_jpeg
:uses: DEF-transformation_log, DEF-fingerprint

Prep's log SHALL record the quarantine of a JPEG taken with its culled RAW as that, naming the RAW by the place it was
culled from and by its fingerprint.
:::

:::{rul} The JPEG's move is recorded as prep's own
:id: RUL-culled_raw_jpeg_recorded
:status: ruled
:criticality: med
:verify: required
:refines: RUL-culled_raw_takes_its_jpeg

Prep's execution SHALL record the move of a JPEG taken with its culled RAW as its own change, so that the next
comparison with the recorded state finds no change in it.
:::

:::{rul} Of identical media, prep quarantines every copy outside photos by destination but one
:id: RUL-duplicates_quarantined
:status: ruled
:criticality: high
:verify: required
:uses: DEF-fingerprint, DEF-managed_folders

Of the media files prep inventories that share one fingerprint and one media class, prep SHALL keep one and quarantine
every other copy outside photos by destination.
:::

:::{rul} The copy kept is the best filed
:id: RUL-copy_kept_by_folder
:status: ruled
:criticality: med
:verify: required
:refines: RUL-duplicates_quarantined
:uses: DEF-managed_folders

The copy prep keeps SHALL be the one first in this order of the folders the copies lie in when planned — photos by
destination, photos by date, videos by date, redundant JPEGs, missing metadata, the inbox.
:::

:::{rul} Of copies in one folder, the first by path is kept
:id: RUL-copy_kept_first_by_path
:status: ruled
:criticality: med
:verify: required
:refines: RUL-copy_kept_by_folder
:uses: DEF-managed_folders

Among copies in one folder, the copy prep keeps SHALL be the first by path.
:::

:::{rul} The workspace database matches the files
:id: RUL-database_matches_files
:status: ruled
:criticality: med
:verify: required
:uses: DEF-workspace_database

A prep execution SHALL leave in the workspace database a row for each media file prep inventoried, describing the file
as it now is and where it now is.
:::

:::{rul} The database holds no row for a file that is gone
:id: RUL-no_row_for_gone_file
:status: ruled
:criticality: med
:verify: required
:refines: RUL-database_matches_files
:uses: DEF-workspace_database

A prep execution SHALL leave in the workspace database no row for a file that is gone.
:::


## 8. Content fingerprinting and cache reuse

:::{rul} A new or changed file is fingerprinted afresh
:id: RUL-fingerprint_taken_afresh
:status: ruled
:criticality: high
:verify: required
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

Prep SHALL reuse a cached fingerprint only when the method that took it is the one now in use for the file's class.
:::

:::{rul} A fingerprint that does not record its method is taken again
:id: RUL-fingerprint_method_unrecorded_retaken
:status: ruled
:criticality: high
:verify: required
:refines: RUL-fingerprint_method_matches
:uses: DEF-fingerprint

Prep SHALL take again a cached fingerprint that does not record its method in full.
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
:anti: yes
:verify: required
:uses: DEF-workspace_database

Prep SHALL stop on a workspace database whose recorded schema is not the one it uses, migrating none.
:::


## 9. Files the user moves, and the plan memo

:::{rul} A file the user moved is recognized
:id: RUL-move_recognized
:status: ruled
:criticality: med
:verify: required
:uses: DEF-workspace_database, DEF-managed_folders

Prep SHALL recognize as moved a file new to photos by destination whose size, modification time and name are those of
a file the workspace database holds and that is gone from its path — one only, matched by no other such file and by no
other new file in photos by destination.
:::

:::{rul} A moved file's identity is carried, not read again
:id: RUL-moved_file_carried
:status: ruled
:criticality: high
:verify: required
:refines: RUL-reuse_valid_work
:uses: DEF-fingerprint, DEF-workspace_database

Prep SHALL carry a moved file's row to its new path, reading nothing of the file but its size and time when the row
would have been reused at the old path.
:::

:::{rul} A moved file whose row is stale is read again where it now is
:id: RUL-moved_file_stale_read_again
:status: ruled
:criticality: high
:verify: required
:refines: RUL-moved_file_carried
:uses: DEF-fingerprint, DEF-workspace_database

Prep SHALL read a moved file again at its new path, as it would have been read at the old, when its row would not have
been reused there.
:::

:::{rul} A quarantined file leaves the database
:id: RUL-quarantined_leaves_database
:status: ruled
:criticality: med
:verify: required
:refines: RUL-database_matches_files
:uses: DEF-workspace_database

A file prep has quarantined SHALL NOT be in the workspace database.
:::

:::{rul} A quarantined file leaves the handoff
:id: RUL-quarantined_leaves_handoff
:status: ruled
:criticality: med
:verify: required
:refines: RUL-handoff_describes_workspace
:uses: DEF-workspace_database, DEF-handoff

A file prep has quarantined SHALL NOT be in the handoff.
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
:uses: DEF-plan_memo, DEF-workspace_database

Prep SHALL take a file's fingerprint and metadata from the plan memo only where the workspace database holds no row for
its path.
:::

:::{rul} A memo entry passes the database's tests
:id: RUL-memo_entry_same_tests
:status: ruled
:criticality: high
:verify: required
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
:uses: DEF-plan_memo

The plan prep makes SHALL be the same whatever the plan memo holds — entries reused, none, or a file that cannot be
read.
:::

:::{rul} The memo holds what the latest plan read
:id: RUL-memo_tracks_workspace
:status: ruled
:criticality: low
:verify: required
:uses: DEF-plan_memo

The plan memo SHALL hold entries only for paths the latest plan read.
:::


## 10. Duplicates and failures beside photos by destination

:::{rul} A failed fingerprint matches nothing
:id: RUL-failed_fingerprint_no_duplicate
:status: ruled
:criticality: high
:anti: yes
:verify: required
:uses: DEF-fingerprint

A media file whose fingerprint failed SHALL be found the duplicate of no file, and no file its duplicate.
:::

:::{rul} A failed fingerprint outside photos by destination blocks
:id: RUL-failed_fingerprint_blocks
:status: ruled
:criticality: high
:verify: required
:uses: DEF-fingerprint, DEF-managed_folders

A media file outside photos by destination whose fingerprint failed SHALL block prep's plan.
:::

:::{rul} A failed fingerprint is taken again
:id: RUL-failed_fingerprint_retried
:status: ruled
:criticality: high
:verify: required
:uses: DEF-fingerprint

Prep SHALL take a media file's fingerprint again at every run while it has failed.
:::

:::{rul} Metadata that could not be read blocks, in photos by destination too
:id: RUL-metadata_failure_blocks
:status: ruled
:criticality: high
:verify: required
:uses: DEF-workspace_database, DEF-managed_folders

A media file whose metadata prep could not read, and of which it keeps no record still valid, SHALL block prep's plan
wherever it lies, photos by destination included.
:::

:::{rul} A duplicate is recorded with the copy kept
:id: RUL-duplicate_recorded_with_kept
:status: ruled
:criticality: med
:verify: required
:refines: RUL-duplicates_quarantined

Prep SHALL record each duplicate it quarantines with the copy it kept, in the handoff.
:::

:::{rul} Only a duplicate is recorded as one
:id: RUL-only_duplicates_recorded_as_duplicates
:status: ruled
:criticality: med
:anti: yes
:verify: required
:refines: RUL-duplicate_recorded_with_kept

A file prep quarantines for another reason than being a copy — a leftover of an interrupted write, a hidden file of a
dump, the JPEG of a culled RAW — SHALL be recorded as no duplicate: neither in its summary, nor its handoff, nor its
log.
:::

:::{rul} The quarantine manifest records a duplicate with the copy kept
:id: RUL-duplicate_in_manifest_with_kept
:status: ruled
:criticality: med
:verify: required
:refines: RUL-evidence_before_quarantine

Prep SHALL record each duplicate it quarantines with the copy it kept, in the quarantine manifest.
:::


## 11. The metadata prep keeps for geotag

:::{rul} Prep keeps the metadata geotag needs
:id: RUL-metadata_kept_for_geotag
:status: ruled
:criticality: high
:verify: required
:uses: DEF-workspace_database

Prep SHALL keep in the workspace database, for each media file it reads, the metadata geotag works from — the camera's
identity, the times and the native GPS position as recorded, and the file's dimensions, orientation and duration.
:::

:::{rul} A field is taken from the camera's own record first
:id: RUL-metadata_group_order
:status: ruled
:criticality: high
:verify: required

Prep SHALL take each metadata field from the file's EXIF where EXIF holds it, else from its XMP, before any other
place the file records it.
:::

:::{rul} A time field is taken from the first place holding a valid time
:id: RUL-time_field_first_valid
:status: ruled
:criticality: high
:verify: required
:refines: RUL-metadata_group_order

Prep SHALL take a time field from the first of those places holding a valid time in it.
:::

:::{rul} Cached metadata is reused only while read the same way
:id: RUL-metadata_freshness
:status: ruled
:criticality: high
:verify: required
:refines: RUL-reuse_valid_work
:uses: DEF-workspace_database

Prep SHALL reuse a file's cached metadata only while the file's path, size, modification time and fingerprint, and the
way the metadata was read — the extractor and its version, the fields, the options and the record's form — are as they
were when it was read.
:::

:::{rul} The handoff reports what the groups hold
:id: RUL-grouping_facts_reported
:status: ruled
:criticality: med
:verify: required

Prep's handoff SHALL report, for each camera group and each folder of photos by destination, facts of the files in it —
their count, their time range, how many carry a GPS position — inferring nothing from them.
:::


## 12. Plan, dry run, execution

:::{rul} A file that appeared since planning restales the plan
:id: RUL-new_file_restales_plan
:status: ruled
:criticality: high
:verify: required
:refines: INV-no_stale_use

A file found, at execution, anywhere prep scans that its plan did not record SHALL make the plan stale, refused before
any change.
:::

:::{rul} A dry run changes nothing
:id: RUL-prep_dry_run_changes_nothing
:status: ruled
:criticality: med
:anti: yes
:verify: required
:refines: RUL-dry_run_changes_nothing

Prep's dry run SHALL change nothing in the workspace.
:::

:::{rul} A prepped workspace has nothing to do
:id: RUL-prepped_nothing_to_do
:status: ruled
:criticality: med
:verify: required

On an initialized workspace whose inbox holds nothing — no file, and no folder — where nothing the user moved, removed
or changed since the last run waits to be recorded and prep's log is the one its handoff vouches for, prep's dry run and
execution SHALL stop, changing nothing, and not carry out the saved plan.
:::

:::{rul} The journal is never left torn
:id: RUL-journal_never_torn
:status: ruled
:criticality: high
:anti: yes
:verify: required
:refines: RUL-every_change_journaled

An interruption SHALL leave prep's journal as its last save left it, never part-written.
:::

:::{rul} A folder left empty is removed
:id: RUL-emptied_folders_removed
:status: ruled
:criticality: med
:verify: required

Prep SHALL remove a folder its plan leaves empty — in the inbox or a by-date folder, or a dump's folder on the first
run.
:::

:::{rul} A folder is removed only as planned
:id: RUL-folder_removed_only_as_planned
:status: ruled
:criticality: med
:verify: required
:refines: RUL-emptied_folders_removed, RUL-execution_only_the_plan

Prep SHALL remove a folder only as a planned operation.
:::

:::{rul} A folder is removed only while it is empty
:id: RUL-emptied_folder_removed_only_empty
:status: ruled
:criticality: med
:verify: required
:refines: RUL-emptied_folders_removed

Prep SHALL remove a folder its plan leaves empty only while the folder is empty.
:::

:::{rul} An interrupted execution is planned again, not resumed
:id: RUL-prep_replans
:status: ruled
:criticality: high
:verify: required

After an interrupted execution, prep SHALL never resume the interrupted plan from its journal: it carries out only a
plan the workspace as it stands still matches, and plans again where it does not.
:::

:::{rul} A plan executed again keeps the earlier attempt's journal
:id: RUL-prep_journal_kept
:status: ruled
:criticality: med
:anti: yes
:verify: required
:uses: DEF-prep

A prep execution of a plan an earlier execution already began SHALL never overwrite the earlier attempt's journal: it is
first set aside, recoverably.
:::


## 13. The quarantine

:::{rul} A quarantined file's reason is recorded before it is moved
:id: RUL-evidence_before_quarantine
:status: ruled
:criticality: high
:verify: required
:refines: RUL-duplicates_quarantined

Prep SHALL record why it quarantines a file — its path and its reason, and for a duplicate the copy kept and the
shared fingerprint — before it moves the file into the quarantine.
:::

:::{rul} An unreadable quarantine record is never written over
:id: RUL-unreadable_manifest_kept
:status: ruled
:criticality: high
:anti: yes
:verify: required
:refines: RUL-evidence_before_quarantine

Prep SHALL stop rather than write over a quarantine record it cannot read and cannot set aside, the file it was to
quarantine left where it was.
:::

:::{rul} No run deletes from the quarantine
:id: RUL-quarantine_never_auto_deleted
:status: ruled
:criticality: high
:anti: yes
:verify: required

No prep plan, dry run or execution SHALL remove anything from the quarantine, however often it runs and however
old the quarantine is.
:::

:::{rul} Only the user's prune deletes
:id: RUL-prune_explicit
:status: ruled
:criticality: high
:anti: yes
:verify: required

Prep SHALL delete quarantined files only by its prune command.
:::

:::{rul} The prune lists what it would delete unless told to delete
:id: RUL-prune_lists_unless_told
:status: ruled
:criticality: high
:verify: required
:refines: RUL-prune_explicit

Prep's prune command SHALL list what it would delete, deleting nothing, unless told to delete.
:::

:::{rul} An age to prune by is at least a day
:id: RUL-prune_age_at_least_one_day
:status: ruled
:criticality: high
:anti: yes
:verify: required

Pruning the quarantine by age SHALL refuse an age of less than one day.
:::

:::{rul} The prune touches nothing outside the quarantine
:id: RUL-prune_only_quarantine
:status: ruled
:criticality: high
:verify: required
:refines: RUL-prune_explicit

Prep's prune command SHALL touch nothing outside the quarantine but its own record of what it deletes
({need}`RUL-prune_recorded`) and the workspace's record, from which it takes what it deleted
({need}`RUL-quarantine_changed_only_by_prune`).
:::

:::{rul} A prune that deletes is recorded
:id: RUL-prune_recorded
:status: ruled
:criticality: high
:verify: required
:refines: RUL-prune_explicit
:uses: DEF-control_records

Prep's prune command, told to delete, SHALL record among the control records what it deletes and when, before it
deletes it.
:::

:::{rul} An earlier prune's record is kept
:id: RUL-prune_record_kept
:status: ruled
:criticality: med
:anti: yes
:verify: required
:refines: RUL-prune_recorded

A prune's record SHALL never be written over by a later prune's: the earlier is set aside, recoverably.
:::

:::{rul} A file restored from the quarantine is a new file
:id: RUL-restored_file_is_new
:status: ruled
:criticality: med
:verify: required

A file the user moves from the quarantine back into the inbox SHALL, once its leaving the
quarantine is accepted ({need}`RUL-stop_gives_acceptance_code`), be handled as a new file of the dump.
:::

:::{rul} A restored file's quarantine record is left as it is
:id: RUL-restored_file_record_kept
:status: ruled
:criticality: med
:verify: required
:refines: RUL-restored_file_is_new

The earlier quarantine record of a file the user moves back into the inbox SHALL be left as it is.
:::

:::{rul} The quarantine's size is reported
:id: RUL-quarantine_footprint_reported
:status: ruled
:criticality: low
:verify: required

Each prep plan SHALL report the quarantine's size — its files, their bytes, and the runs that filled it, oldest and
newest.
:::


## 14. The handoff and prep's log

:::{rul} Prep's records are written only by an execution that succeeded
:id: RUL-prep_records_on_success
:status: ruled
:criticality: high
:verify: required

Prep SHALL write its log and its handoff only at the end of an execution all of whose operations succeeded.
:::

:::{rul} A failed prep execution still logs the changes by hand it passed
:id: RUL-failed_prep_logs_hand_changes
:status: ruled
:criticality: med
:verify: required
:refines: RUL-allowed_changes_named
:excepts: RUL-prep_records_on_success

A prep execution that fails SHALL still add to prep's log the changes by hand its check passed, the rest of the log left
as it was.
:::

:::{rul} Prep's records are written whole
:id: RUL-prep_records_written_whole
:status: ruled
:criticality: high
:verify: required
:refines: RUL-prep_records_on_success

Prep's log and its handoff SHALL each be written whole, never edited in place.
:::

:::{rul} The handoff describes the workspace geotag works on
:id: RUL-handoff_describes_workspace
:status: ruled
:criticality: high
:verify: required

Prep's handoff SHALL describe the workspace as prep leaves it: every media file with its place, its fingerprint's state
and its metadata; the camera groups and the destination folders; the folders prep organizes and which of them it may
change; and what the handoff was made from.
:::

:::{rul} One workspace state, one handoff content
:id: RUL-handoff_deterministic
:status: ruled
:criticality: high
:verify: required
:refines: RUL-run_only_refresh_restales_nothing

Prep's handoff SHALL hold the same content for the same workspace state, whatever run wrote it — what describes the run
kept apart from it.
:::

:::{rul} Prep checks the handoff it wrote
:id: RUL-handoff_read_back
:status: ruled
:criticality: high
:verify: required
:refines: RUL-handoff_deterministic

Prep SHALL read back the handoff it has written and fail the run where what it reads does not give the content
fingerprint the handoff records.
:::

:::{rul} Prep's log is made from prep's own records
:id: RUL-prep_log_derived
:status: ruled
:criticality: med
:verify: required

Prep's log SHALL be made from prep's plans, journals, quarantine evidence and database alone, holding nothing they do
not.
:::

:::{rul} An unreadable log stops prep
:id: RUL-unreadable_prep_log_stops
:status: ruled
:criticality: high
:anti: yes
:verify: required
:refines: RUL-partial_history_shown
:uses: DEF-transformation_log

Prep SHALL stop, before any change and naming the file, where its earlier log exists and cannot be read — never taking
it for an empty log.
:::

:::{rul} A photo gone from the workspace keeps its entry as it was
:id: RUL-gone_photo_entry_carried
:status: ruled
:criticality: med
:verify: required
:refines: RUL-log_entry_append_only
:uses: DEF-transformation_log

An entry of prep's log whose photo is no longer anywhere in the workspace, and which no photo takes up as its own
under a fingerprint taken again ({need}`RUL-log_follows_retaken_fingerprint`), SHALL be carried into each later log as
it was — its steps, and the place prep last left it — neither dropped nor given a step of its going.
:::

:::{rul} Prep's log records each duplicate with the copy kept
:id: RUL-prep_log_records_set_aside
:status: ruled
:criticality: med
:verify: required
:refines: RUL-duplicates_quarantined

Prep's log SHALL record each duplicate prep quarantined — where it was, where it went, and the copy kept — with the kept
copy's entry.
:::

:::{rul} A photo keeps its history when its fingerprint is taken again
:id: RUL-log_follows_retaken_fingerprint
:status: ruled
:criticality: high
:verify: required
:refines: RUL-log_keyed_by_fingerprint

A photo whose fingerprint is taken again with a new value SHALL keep its history in the log, under the new value.
:::

:::{rul} Only the same file, unchanged, has its fingerprint taken again
:id: RUL-retake_only_unchanged_file
:status: ruled
:criticality: high
:anti: yes
:verify: required
:refines: RUL-log_follows_retaken_fingerprint
:uses: DEF-transformation_log

A fingerprint SHALL count as taken again only for a file unchanged since the last execution — its size, modification
time and file identity those recorded — whose fingerprint was taken by another method; a different file at the path is
a new photo, and the gone photo's entry stays as it was.
:::

:::{rul} A fingerprint taken again is a step in the log
:id: RUL-retaken_fingerprint_step_logged
:status: ruled
:criticality: high
:verify: required
:refines: RUL-log_follows_retaken_fingerprint

The log SHALL record a step for the change when a photo's fingerprint is taken again with a new value.
:::


## 15. Concurrency, determinism, and what a run shows

:::{rul} The job count changes nothing planned
:id: RUL-jobs_change_nothing
:status: ruled
:criticality: high
:anti: yes
:verify: required
:refines: RUL-no_op_run_same_result

Prep's plan of a workspace SHALL be the same whatever number of jobs it runs with: the same operations, names and
fingerprints.
:::

:::{rul} The job count is recorded nowhere
:id: RUL-jobs_recorded_nowhere
:status: ruled
:criticality: low
:verify: required

The number of jobs SHALL be recorded in no plan, configuration or handoff.
:::

:::{rul} A tool's failure is retried before it counts
:id: RUL-tool_failure_retried
:status: ruled
:criticality: med
:verify: required
:refines: RUL-tool_failure_never_valid

A tool that fails or crashes on a file SHALL be restarted and tried again a bounded number of times before the file's
fingerprint or metadata is recorded as failed.
:::

:::{rul} A tool's failure is never recorded as valid
:id: RUL-tool_failure_never_valid
:status: ruled
:criticality: med
:verify: required

A file's fingerprint or metadata SHALL never be recorded as valid when the tool failed or crashed on it.
:::

:::{rul} A fingerprint taken again is explained
:id: RUL-rehash_explained
:status: ruled
:criticality: low
:verify: required

Each prep plan SHALL report how many media files it fingerprinted again, and why — deciding nothing by it.
:::

:::{rul} A plan reports the fingerprints it took from the memo
:id: RUL-rehash_memo_count_reported
:status: ruled
:criticality: low
:verify: required
:refines: RUL-rehash_explained

Each prep plan SHALL report how many fingerprints it took from the plan memo.
:::

## 16. What prep reports

:::{rul} Prep's run is summarised
:id: RUL-prep_run_summarised
:status: ruled
:criticality: low
:verify: required

With each plan, and again at the end of its execution, prep SHALL report a summary telling what it changes apart from
what it only reads: its media
operations, the files already in place, the moves it recognized, the files of photos by destination it read, the
duplicates of files it may change apart from those of photos by destination, the metadata reused, extracted, carried
and failed, the blockers and warnings, and which records it wrote.
:::

:::{rul} What prep quarantines is counted by why
:id: RUL-set_aside_counted_by_reason
:status: ruled
:criticality: low
:verify: required
:refines: RUL-prep_run_summarised

Prep's summary SHALL count the files it quarantines by the reason for each — duplicates, leftovers of an interrupted
write, hidden files of a dump, the JPEG of a culled RAW — apart.
:::
