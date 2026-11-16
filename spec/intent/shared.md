# Shared — what every phase guarantees

The facts all three phases — prep, geotag and merge — must agree on. Each item says which phases it binds; an item
that names none binds them all. *Why* each holds is in [the rationale](../rationale/shared.md); *how this build meets
it*, in [the build](../build/shared.md).

## 0. The pipeline

:::{def} The workspace
:id: DEF-workspace
:status: ruled

A **workspace** is the transient place one ingest happens in: a dump of media enters it, the phases work on it in
turn, and merge moves its finished photos into the library. A run's workspace is the folder it is started in.
:::

:::{def} The library
:id: DEF-library
:status: ruled
:uses: DEF-workspace

The **library** is the permanent, curated collection the media ends in — outside every workspace, and written by
no phase but merge.
:::

:::{def} Prep
:id: DEF-prep
:status: ruled
:uses: DEF-workspace

**Prep**, the first phase, takes an unorganized dump and makes it a clean working set: it consolidates the dump,
normalizes extensions, sets duplicates aside (recoverably, never deleting), organizes the media by date, and hands
geotag what it found.
:::

:::{def} Geotag
:id: DEF-geotag
:status: ruled
:uses: DEF-prep

**Geotag**, the second phase, resolves each photo to its true time, inferring and correcting each camera's clock
offset; places each photo that carries no position, by the tracks, its destination's fallback or the user's answer;
and renames each by its corrected local time.
:::

:::{def} Merge
:id: DEF-merge
:status: ruled
:uses: DEF-geotag, DEF-library

**Merge**, the third phase, runs after a workspace has been geotagged and finalized, and moves its finished photos,
sorted by destination, into the library.
:::

:::{def} The handoff
:id: DEF-handoff
:status: ruled
:uses: DEF-prep, DEF-geotag

The **handoff** is the record prep's execution leaves for geotag: each media file it leaves, with its place,
fingerprint and metadata, its camera group and destination, and what the record was made from.
:::

:::{def} The quarantine
:id: DEF-quarantine
:status: ruled
:uses: DEF-prep

The **quarantine** is the recoverable place, apart from the managed folders, where prep sets aside the files it
takes out of the media, each with a record of why.
:::

:::{def} A dump
:id: DEF-dump
:status: ruled
:uses: DEF-workspace

A **dump** is a batch of files the user puts into the workspace to be ingested: at its top level on the run that
initializes it, in the inbox after.
:::

:::{def} A file's media class
:id: DEF-media_class
:status: ruled
:uses: DEF-configuration

A file's **media class** — image, raw, video, or `other` — is the one the configuration gives its extension.
:::

:::{def} A blocker
:id: DEF-blocker
:status: ruled

A **blocker** is a reason a plan cannot be carried out as it stands, reported with it.
:::

:::{def} The managed folders
:id: DEF-managed_folders
:status: ruled
:uses: DEF-workspace, DEF-strays_folder

The **managed folders** are the workspace's media folders, each with a fixed role: the **inbox**, where a dump arrives;
the strays folder; **missing metadata**, for media with no recorded time; **redundant JPEGs**; **videos by date**;
**photos by date**; and **photos by destination**, the staging the user sorts photos into and merge empties into the
library.
:::

:::{rul} A command's exit status says how it ended
:id: RUL-exit_status_says_how_it_ended
:status: ruled
:criticality: med
:verify: required
:uses: DEF-prep, DEF-geotag, DEF-merge

Prep's plan, dry run, execute and prune, and each of geotag's and merge's commands, SHALL end with an exit status of its own
for each way a run can end: having done what it was asked; finding the workspace or the library locked; refusing,
having changed nothing; executing with work left undone; ending on an error it did not foresee; and interrupted.
:::

:::{rul} A plan that reports a blocker ends as a refusal
:id: RUL-blocked_plan_ends_refused
:status: ruled
:criticality: med
:verify: required
:refines: RUL-exit_status_says_how_it_ended
:uses: DEF-blocker

A phase's plan that reports a blocker, and a phase's dry run of a plan holding one, SHALL end with the exit status of
a refusal, never with that of a run that did what it was asked.
:::

## 1. One run at a time

:::{inv} One run at a time
:id: INV-one_run_at_a_time
:status: ruled
:criticality: high
:anti: yes
:verify: required

At most one cartographer run SHALL act on a workspace at any time — whatever the commands: two runs of one phase, runs
of two phases, a merge, a finalize, or a quarantine prune.
:::

:::{rul} Every run, and every change, takes the lock
:id: RUL-every_command_locks
:status: ruled
:criticality: med
:verify: required
:upholds: INV-one_run_at_a_time

Every run, and every change to the workspace, SHALL hold the workspace's lock.
:::

:::{rul} A workspace has one lock
:id: RUL-one_workspace_lock
:status: ruled
:criticality: med
:verify: required
:upholds: INV-one_run_at_a_time

A workspace SHALL have exactly one lock, shared by every command.
:::

:::{rul} The lock comes before anything is read
:id: RUL-lock_before_reading
:status: ruled
:criticality: high
:verify: required
:upholds: INV-one_run_at_a_time

A run SHALL hold the lock before it reads any of the workspace's content — before it plans, scans, fingerprints,
reads metadata, dry-runs or executes. Planning, though it changes no media, is inside the lock
all the same.
:::

:::{rul} The lock lasts the whole run, and no longer
:id: RUL-lock_through_the_run
:status: ruled
:criticality: high
:anti: yes
:verify: required
:upholds: INV-one_run_at_a_time

A run SHALL hold the lock until it ends — through planning, dry run, execution, and every record and artifact it
writes.
:::

:::{rul} A locked workspace is refused at once
:id: RUL-lock_fail_fast
:status: ruled
:criticality: high
:anti: yes
:verify: required
:upholds: INV-one_run_at_a_time

A run that finds the workspace locked SHALL stop at once, never waiting for it, having scanned, planned and changed
nothing — and having produced no plan, no dry-run report and no artifact.
:::

:::{rul} A refused run says the workspace is locked
:id: RUL-lock_refusal_says_locked
:status: ruled
:criticality: high
:verify: required
:refines: RUL-lock_fail_fast

A run that stops on a locked workspace SHALL say the workspace is locked by a run in progress.
:::

:::{rul} The lock is released however the run ends
:id: RUL-lock_released_on_any_end
:status: ruled
:criticality: med
:verify: required
:refines: RUL-lock_through_the_run

A run SHALL release the lock when it ends, whether it succeeds or fails, never letting it outlive the run: between
runs, the workspace is unlocked.
:::

:::{rul} A stale lock is recognised and recovered
:id: RUL-stale_lock_recovered
:status: ruled
:criticality: med
:verify: required

A lock left behind by a run that died SHALL be recognisable as stale, and recoverable, so that a crash never leaves a
workspace locked for good.
:::

:::{rul} A lock is taken over only once no running process holds it
:id: RUL-stale_takeover_conservative
:status: ruled
:criticality: high
:anti: yes
:verify: required
:refines: RUL-stale_lock_recovered

A lock SHALL be taken over only once the machine's own system reports that no running process holds it — never on what
the lock's record says of its owner. This guards the runs of one machine; where two machines reach one library over a
network, whether the lock holds between them is that filesystem's doing.
:::

Merge also takes a lock on the library it writes into, so that two merges into one library — even from two workspaces
— never overlap; that lock is held besides the workspace's, not instead of it. Its items are with merge's.

## 2. A snapshot before changing, optionally

:::{rul} A snapshot is optional, and nothing rests on it
:id: RUL-snapshot_optional
:status: ruled
:criticality: med
:verify: required

A phase that changes files MAY first take a snapshot of what it is about to change, from which the whole change can be
rolled back. Cartographer SHALL be complete and safe without one, no guarantee depending on a snapshot having been
taken.
:::

:::{rul} No snapshot unless configured
:id: RUL-snapshot_off_by_default
:status: ruled
:criticality: med
:verify: required
:refines: RUL-snapshot_optional

Snapshots SHALL be off unless the workspace's configuration turns them on.
:::

:::{rul} A snapshot names its plan
:id: RUL-snapshot_per_plan
:status: ruled
:criticality: low
:verify: required

Each snapshot SHALL be identifiable by the plan whose changes it precedes.
:::

:::{rul} When a snapshot is taken
:id: RUL-snapshot_timing
:status: ruled
:criticality: med
:verify: required

A snapshot SHALL be taken before the plan's first change.
:::

:::{rul} A snapshot follows the plan's validation
:id: RUL-snapshot_after_validation
:status: ruled
:criticality: med
:verify: required
:refines: RUL-snapshot_timing

A snapshot SHALL be taken only after the plan has been validated against its dependencies.
:::

:::{rul} A snapshot is taken under the lock
:id: RUL-snapshot_under_lock
:status: ruled
:criticality: med
:verify: required
:refines: RUL-snapshot_timing

A snapshot SHALL be taken only while the lock is held.
:::

:::{rul} A required snapshot that fails stops the run
:id: RUL-required_snapshot_or_nothing
:status: ruled
:criticality: high
:anti: yes
:verify: required
:refines: RUL-snapshot_timing

When the configuration requires snapshots, a run that cannot take one SHALL stop before it changes anything.
:::

:::{rul} Without a required snapshot, the run goes on
:id: RUL-unrequired_snapshot_proceeds
:status: ruled
:criticality: med
:verify: required
:refines: RUL-snapshot_optional

When snapshots are not required, or not configured, a run SHALL proceed without one. Its safety then rests, as it
always does, on the journal, the recoverable quarantine, never overwriting, and the filesystem as the truth.
:::

:::{rul} Merge snapshots the workspace, and the library beside it
:id: RUL-merge_snapshots_library
:status: ruled
:criticality: med
:verify: required

Merge's snapshot SHALL cover the workspace, and the library too where the library can be snapshotted.
:::

:::{rul} Merge takes no snapshot of the library alone
:id: RUL-no_library_only_snapshot
:status: ruled
:criticality: med
:anti: yes
:verify: required
:refines: RUL-merge_snapshots_library

Merge SHALL take no snapshot of the library alone.
:::

## 3. One configuration, kept in the workspace

:::{def} The configuration
:id: DEF-configuration
:status: ruled
:uses: DEF-workspace

A workspace's **configuration** is the one record of the settings its runs read. It is kept in the workspace, beside
what is processed under it, and it is an input the user authors.
:::

:::{rul} One configuration, read by every phase
:id: RUL-one_configuration
:status: ruled
:criticality: med
:verify: required

All three phases SHALL read their settings from the workspace's one configuration alone, each the settings it needs — no
phase keeping settings of its own, and no setting that bears on what a run produces coming from outside the workspace.
What a new workspace's configuration starts as is seeded into it once ({need}`RUL-config_seeded_once`) and read from
there after.
:::

:::{rul} A configuration missing a setting stops the run
:id: RUL-config_complete
:status: ruled
:criticality: high
:anti: yes
:verify: required
:refines: RUL-one_configuration

A configuration that lacks a setting SHALL stop the run — never filled from the program's defaults.
:::

:::{rul} The missing setting is named
:id: RUL-missing_setting_named
:status: ruled
:criticality: high
:verify: required
:refines: RUL-config_complete

A run stopped by a configuration that lacks a setting SHALL name the setting.
:::

:::{rul} A configuration holding an unknown setting stops the run
:id: RUL-config_no_unknown_settings
:status: ruled
:criticality: med
:anti: yes
:verify: required
:refines: RUL-one_configuration

A configuration holding a setting cartographer does not know SHALL stop the run.
:::

:::{rul} The unknown setting is named
:id: RUL-unknown_setting_named
:status: ruled
:criticality: med
:verify: required
:refines: RUL-config_no_unknown_settings

A run stopped by a setting cartographer does not know SHALL name the setting.
:::

:::{rul} Prep seeds the configuration once
:id: RUL-config_seeded_once
:status: ruled
:criticality: med
:verify: required

A prep run SHALL create the configuration from the seed defaults when it finds none.
:::

:::{rul} The workspace's configuration governs it, not the defaults
:id: RUL-config_authoritative
:status: ruled
:criticality: med
:verify: required

Once a workspace's configuration exists, it SHALL govern every run in that workspace, whatever the seed defaults later
become — the defaults serving only to seed a new workspace.
:::

:::{rul} Who writes the configuration
:id: RUL-config_writers
:status: ruled
:criticality: high
:anti: yes
:verify: required

The configuration SHALL be written only when prep seeds it, when the user edits it by hand, by the library setup and by
the decision editor's classing of a camera group and its naming of one as several bodies, below — never by geotag, and
never by merge's planning, dry run or execution.
:::

:::{rul} The library setup records one setting
:id: RUL-library_setup_writes_one_setting
:status: ruled
:criticality: med
:anti: yes
:verify: required
:refines: RUL-config_writers

Merge's one-time library setup, run inside a workspace and given a library, SHALL write in the configuration no
setting but which library this workspace merges into.
:::

:::{rul} The configuration is a dependency of what is made under it
:id: RUL-config_in_dependencies
:status: ruled
:criticality: med
:verify: required

The configuration SHALL be a dependency of what is derived under it, like every other artifact, so that a change to it
never changes a run without being detected.
:::

:::{rul} A digest of the whole configuration is recorded
:id: RUL-config_digest_recorded
:status: ruled
:criticality: med
:verify: required
:refines: RUL-config_in_dependencies

A digest of the configuration's whole content SHALL be recorded for integrity.
:::

:::{rul} The configuration is part of the permanent record
:id: RUL-config_archived
:status: ruled
:criticality: med
:verify: required
:refines: RUL-package_contents

The configuration SHALL be part of the archival record the workspace leaves behind.
:::

:::{rul} The configuration is never media
:id: RUL-config_never_media
:status: ruled
:criticality: med
:anti: yes
:verify: required
:refines: RUL-control_records_never_media

No phase SHALL treat the configuration as media — inventorying or organizing it, or folding it into what identifies the
media.
:::

:::{rul} A change to one area restales only what depends on it
:id: RUL-staleness_by_area
:status: ruled
:criticality: med
:anti: yes
:verify: required
:refines: RUL-remake_only_what_depends

A change to one area of the configuration SHALL make stale only what depends on that area. A change to the track
thresholds restales placement and the plans, not the renames; a change to the filename format restales the renames,
not placement.
:::

:::{rul} Costly results survive edits they do not depend on
:id: RUL-costly_results_survive_unrelated_edits
:status: ruled
:criticality: med
:anti: yes
:verify: required
:refines: RUL-staleness_by_area

A result that is costly to rebuild SHALL be made stale only by the areas it depends on.
:::

:::{rul} Resolved true times survive configuration edits outside the time policy
:id: RUL-times_survive_unrelated_config_edits
:status: ruled
:criticality: med
:anti: yes
:verify: required
:refines: RUL-costly_results_survive_unrelated_edits

A configuration change outside the camera-time policy SHALL NOT make stale the true times already resolved.
:::

:::{rul} Any configuration change restales the plan
:id: RUL-any_config_change_replans
:status: ruled
:criticality: med
:verify: required

Any change to the configuration, in whatever area, SHALL make stale every plan made before it — prep's plan, geotag's
executable plan and merge's plan — so that none of them is executed.
:::

:::{rul} Geotag's and merge's plans depend on the folder names and the media classes
:id: RUL-organization_settings_restale
:status: ruled
:criticality: med
:verify: required
:refines: RUL-config_in_dependencies

Geotag's executable plan and merge's plan SHALL each record the managed folders' names and the extension lists
among their dependencies.
:::

:::{rul} Where the control records live is fixed
:id: RUL-control_directory_fixed
:status: ruled
:criticality: med
:anti: yes
:verify: required

Where a workspace keeps its control records — its configuration among them — SHALL be fixed, the same in every
workspace, no setting moving it.
:::

:::{def} What the configuration sets
:id: DEF-config_areas
:status: ruled
:uses: DEF-configuration

The configuration sets, at least: the snapshot policy; which camera groups are phones and which have fixed clocks; the
filename timestamp format; where the tracks are and the thresholds for matching photos to them; the camera-time policy;
the library and how merge places files in it; the managed folders' names; the names of the development subfolders;
and which extensions are which class of media. Each area's detail is in the items of its own section.
:::

:::{rul} The user names the folders; their roles are fixed
:id: RUL-folder_names_not_roles
:status: ruled
:criticality: med
:anti: yes
:verify: required

The configuration SHALL set the managed folders' names, never their roles or the structure they form.
:::

:::{rul} A managed folder is found by its role
:id: RUL-folder_found_by_role
:status: ruled
:criticality: med
:verify: required
:refines: RUL-folder_names_not_roles

Every phase SHALL find a managed folder by its role, never by its name.
:::

:::{rul} The user classifies camera groups; how they are derived is fixed
:id: RUL-camera_classes_not_derivation
:status: ruled
:criticality: med
:anti: yes
:verify: required

Of camera grouping, the configuration SHALL set only which camera groups are phones and which have fixed clocks — never
how a group is derived, nor the version of that derivation.
:::

:::{rul} Each extension is one class of media
:id: RUL-extension_one_class
:status: ruled
:criticality: med
:verify: required
:uses: DEF-media_class

An extension SHALL be in exactly one class of media.
:::

:::{rul} The configuration lists the extensions, not the classes
:id: RUL-config_lists_extensions
:status: ruled
:criticality: med
:verify: required
:uses: RUL-extension_one_class

The configuration SHALL list which extensions are images, raw files and videos, never the classes themselves.
:::

:::{rul} An extension not listed is other
:id: RUL-unlisted_extension_other
:status: ruled
:criticality: med
:verify: required
:uses: DEF-media_class, RUL-extension_one_class

An extension the configuration does not list SHALL be `other`.
:::

:::{rul} An extension is matched ignoring case
:id: RUL-extension_matched_ignoring_case
:status: ruled
:criticality: med
:verify: required
:refines: RUL-config_lists_extensions

A file's extension SHALL be matched to the configuration's lists ignoring case.
:::

:::{rul} Every value the user supplies is checked before use
:id: RUL-config_validated_before_use
:status: ruled
:criticality: med
:verify: required
:refines: INV-authored_values_checked

Every value of the configuration that comes from the user SHALL be validated before it is used, as part of reading the
configuration — never as a separate, optional pass.
:::

:::{rul} A setting has one purpose
:id: RUL-setting_bounds_one_thing
:status: ruled
:criticality: med
:verify: required

No setting of the configuration SHALL be read for more than one purpose.
:::

## 4. The control records, apart from the media

:::{def} The control records
:id: DEF-control_records
:status: ruled
:uses: DEF-workspace

A workspace's **control records** are everything cartographer keeps in it besides the media: the configuration, the
plans and the decisions, the journals, the end-of-phase records and the databases. The quarantine's manifests are not
control records: each belongs to the quarantine folder whose duplicates it describes.
:::

:::{rul} The control records are kept together, apart from the media
:id: RUL-control_records_together
:status: ruled
:criticality: med
:verify: required
:uses: DEF-control_records

Every control record SHALL be kept in the workspace's one place for them, none among the media or at the workspace's top
level.
:::

:::{rul} The control records' place is never searched for media
:id: RUL-control_records_never_media
:status: ruled
:criticality: med
:anti: yes
:verify: required

The control records' place SHALL be left out of every inventory of media as a whole — not file by file — so that no
phase takes a control record for media.
:::

:::{def} The strays folder
:id: DEF-strays_folder
:status: ruled
:uses: DEF-prep

The **strays folder** is a managed folder at the workspace's top level. It holds the files that are not media which
prep moved out of the inbox, one subfolder for each run, their structure kept. It is neither a control record nor any
phase's output.
:::

:::{rul} What prep never inventories
:id: RUL-not_inventoried
:status: ruled
:criticality: med
:verify: required
:uses: DEF-strays_folder, DEF-quarantine

Prep SHALL leave out of its inventory of media, each as a whole: the control records' place, the quarantine, a
version-control directory, and the strays folder with everything in it; and every hidden file.
:::

:::{rul} A hidden folder holding files stops prep
:id: RUL-hidden_folder_among_photos_blocks
:status: ruled
:criticality: high
:anti: yes
:verify: required

Prep SHALL NOT plan while a hidden folder inside a managed folder other than the inbox holds a file.
:::

:::{rul} The strays folder's contents are never processed again
:id: RUL-strays_never_processed
:status: ruled
:criticality: med
:verify: required
:refines: RUL-not_inventoried

Nothing SHALL process the strays folder's contents again: prep writes into it, but never scans it.
:::

:::{rul} Hidden files in a dump are quarantined
:id: RUL-dump_hidden_files_quarantined
:status: ruled
:criticality: med
:verify: required
:excepts: RUL-init_moves_dump_to_inbox
:uses: DEF-quarantine, DEF-dump

Hidden files and hidden folders that arrive in a dump area — the workspace's top level on the run that initializes it, or the inbox — SHALL
be moved to the recoverable quarantine, not merely left out.
:::

:::{rul} What an interrupted metadata write left is quarantined
:id: RUL-write_leftovers_quarantined
:status: ruled
:criticality: med
:verify: required
:uses: DEF-quarantine

A temporary file that an interrupted metadata write left beside a photo, in a folder prep may change, SHALL
be moved to the recoverable quarantine — never taken for media, never put among the strays.
:::

:::{rul} Such a leftover in photos by destination is left where it is
:id: RUL-write_leftovers_by_dest_warned
:status: ruled
:criticality: low
:verify: required
:excepts: RUL-write_leftovers_quarantined

A temporary file that an interrupted metadata write left in photos by destination, which prep never changes,
SHALL be left where it is.
:::

:::{rul} The user is warned of such a leftover
:id: RUL-write_leftover_in_by_dest_warned
:status: ruled
:criticality: low
:verify: required
:refines: RUL-write_leftovers_by_dest_warned

The user SHALL be warned of each leftover of an interrupted metadata write left in photos by destination.
:::

:::{rul} A backup the user's own edit left is the user's file
:id: RUL-user_backup_is_a_stray
:status: ruled
:criticality: high
:anti: yes
:verify: required

A backup that the user's own edit of a photo left beside it — the photo as it was before that edit — SHALL be treated as any file of no media class, never as what a write of cartographer's left.
:::

:::{rul} Each plan has one fixed place
:id: RUL-plan_at_fixed_place
:status: ruled
:criticality: med
:verify: required

Each phase's plan, and each of its decision records, SHALL have one fixed place among the control records, where the
phase's planning writes it and its dry run and its execution read it.
:::

:::{rul} No command is told where a plan is
:id: RUL-no_plan_location_option
:status: ruled
:criticality: med
:anti: yes
:verify: required
:refines: RUL-plan_at_fixed_place

No command SHALL take an option saying where to put a plan or where to find one; the fixed place is the contract.
:::

:::{rul} No plan, no dry run and no execution
:id: RUL-no_plan_no_run
:status: ruled
:criticality: med
:anti: yes
:verify: required

A dry run or an execution that finds no plan in its place SHALL stop.
:::

:::{rul} The user is told to plan first
:id: RUL-no_plan_says_plan_first
:status: ruled
:criticality: med
:verify: required
:refines: RUL-no_plan_no_run

A dry run or an execution stopped for want of a plan SHALL tell the user to plan first.
:::

:::{rul} A dry run summarises the real plan
:id: RUL-dry_run_summarises_the_real_plan
:status: ruled
:criticality: med
:anti: yes
:verify: required

A dry run SHALL report on the saved plan that execution would carry out — never on a separate simulation.
:::

:::{rul} A dry run changes nothing
:id: RUL-dry_run_changes_nothing
:status: ruled
:criticality: med
:anti: yes
:verify: required
:uses: DEF-workspace, DEF-library

A dry run SHALL change nothing in the workspace or the library but the owner records of the locks it takes and the
acceptance of changes it is given ({need}`RUL-acceptance_recorded`).
:::

:::{rul} A dry run validates the saved plan
:id: RUL-dry_run_validates_saved_plan
:status: ruled
:criticality: med
:verify: required
:refines: RUL-dry_run_summarises_the_real_plan

A dry run SHALL validate the saved plan that execution would carry out.
:::

:::{rul} Re-planning sets the prior plan aside
:id: RUL-replanning_keeps_the_prior
:status: ruled
:criticality: high
:anti: yes
:verify: required

Re-planning SHALL never overwrite a plan or a decision record: when what it makes differs from what is saved, the
saved one is first set aside, recoverably.
:::

:::{rul} The user is told where the prior plan went
:id: RUL-set_aside_plan_reported
:status: ruled
:criticality: med
:verify: required
:refines: RUL-replanning_keeps_the_prior

Re-planning that sets a saved plan or decision record aside SHALL tell the user where.
:::

:::{rul} A record being replaced never leaves its path
:id: RUL-record_in_place_while_replaced
:status: ruled
:criticality: high
:anti: yes
:verify: required

A plan or decision record being replaced, by re-planning or by the editor's save, SHALL be at its path at every instant — the earlier version until the new one is whole — so that a run killed in between finds the decisions, never an empty place.
:::

:::{rul} An unchanged re-plan rewrites none of its records
:id: RUL-unchanged_replan_writes_nothing
:status: ruled
:criticality: med
:verify: required
:refines: RUL-replanning_keeps_the_prior

A re-plan whose result is identical to what is saved SHALL rewrite none of its plan and decision records
and set nothing aside.
:::

:::{rul} Geotag verifies the handoff by its content
:id: RUL-handoff_verified_by_content
:status: ruled
:criticality: med
:verify: required
:excepts: RUL-hash_is_the_dependency_check
:upholds: INV-no_stale_use
:uses: DEF-handoff

Geotag SHALL verify prep's handoff before using it by a hash of its content, what describes the run left out —
recomputed, and compared with the one its dependencies recorded — never by the hash of its bytes.
:::

:::{rul} Refreshing what describes the run restales nothing
:id: RUL-run_only_refresh_restales_nothing
:status: ruled
:criticality: med
:anti: yes
:verify: required
:refines: RUL-handoff_verified_by_content
:uses: DEF-handoff

A rewrite of the handoff that changes only what describes the run, not its content, SHALL NOT make anything downstream
stale.
:::

:::{inv} A disturbed workspace is never processed silently
:id: INV-undisturbed_shape
:status: ruled
:criticality: high
:anti: yes
:verify: by_rules

No phase SHALL process an initialized workspace whose shape was disturbed from outside cartographer — an entry at its
top level that does not belong there, a symbolic link among its files, a managed folder missing — without stopping.
:::

:::{rul} Prep builds the structure once, and never removes a folder
:id: RUL-structure_built_once
:status: ruled
:criticality: med
:anti: yes
:verify: required
:upholds: INV-undisturbed_shape

Prep SHALL create the full structure of managed folders exactly once, when it initializes the workspace.
:::

:::{rul} Prep never removes a managed folder
:id: RUL-managed_folder_never_removed
:status: ruled
:criticality: med
:anti: yes
:verify: required
:refines: RUL-structure_built_once

Prep SHALL never remove a managed folder.
:::

:::{rul} No other phase creates or repairs the structure
:id: RUL-only_prep_builds_structure
:status: ruled
:criticality: high
:anti: yes
:verify: required
:refines: RUL-structure_built_once

No phase but prep SHALL create or repair the workspace's structure; the folders merge creates in the library are
placement, not structure.
:::

:::{rul} The top level holds only what belongs there
:id: RUL-top_level_only_managed
:status: ruled
:criticality: high
:anti: yes
:verify: required
:upholds: INV-undisturbed_shape
:uses: DEF-quarantine, DEF-dump

The top level of an initialized workspace SHALL hold only the managed folders, the control records' place, the
quarantine and hidden entries, hidden files as much as hidden folders: any other entry — a file, a folder, a link, an
entry of any other kind — is a misplaced dump, whose only place is the
inbox, and blocks every phase alike.
:::

:::{rul} A new workspace's first dump is at its top level
:id: RUL-first_dump_at_top_level
:status: ruled
:criticality: med
:verify: required
:uses: DEF-dump

On a workspace not yet initialized, the files and folders at the top level SHALL be the first dump, and start
initialization — a symbolic link there still blocking, as everywhere.
:::

:::{rul} No symbolic link is followed, and any link blocks
:id: RUL-no_links
:status: ruled
:criticality: high
:anti: yes
:verify: required
:upholds: INV-undisturbed_shape

A symbolic link anywhere among the managed files SHALL block, never skipped silently: a link to a file anywhere; a
link to a folder inside a dump or a managed folder; a managed folder that is itself a link; a link at the top level.
:::

:::{rul} No symbolic link is followed
:id: RUL-link_never_followed
:status: ruled
:criticality: high
:anti: yes
:verify: required
:refines: RUL-no_links

A symbolic link among the managed files SHALL never be followed or organized: a link to a folder is never entered, and
a managed folder that is itself a link is never walked.
:::

:::{rul} A blocking link is named, and nothing is made after it
:id: RUL-link_named
:status: ruled
:criticality: med
:verify: required
:refines: RUL-no_links

A phase a link blocks SHALL name the link.
:::

:::{rul} Nothing is made after a blocking link
:id: RUL-link_block_produces_nothing
:status: ruled
:criticality: med
:verify: required
:refines: RUL-link_named

A phase a link blocks SHALL produce no executable plan and no artifact after it.
:::

:::{rul} Prep checks the whole tree for links
:id: RUL-who_checks_for_links
:status: ruled
:criticality: med
:verify: required
:refines: RUL-no_links

Prep SHALL check for links across the whole tree it walks, the destination tree included though prep never changes it.
:::

:::{rul} Geotag and merge check for links where they work
:id: RUL-geotag_merge_check_links
:status: ruled
:criticality: med
:verify: required
:refines: RUL-who_checks_for_links

Geotag and merge SHALL check for links themselves, at the top level and throughout photos by destination — a link put
there since prep is one the handoff cannot know of.
:::

:::{rul} Geotag and merge take only a handoff built with no link
:id: RUL-handoff_built_without_links
:status: ruled
:criticality: med
:verify: required
:refines: RUL-geotag_merge_check_links
:uses: DEF-handoff

Geotag and merge SHALL consume only a handoff prep built with no link present.
:::

:::{rul} A missing managed folder blocks, and is never rebuilt
:id: RUL-missing_folder_blocks
:status: ruled
:criticality: high
:anti: yes
:verify: required
:upholds: INV-undisturbed_shape

On an initialized workspace, a missing managed folder SHALL block every phase.
:::

:::{rul} A missing managed folder is never rebuilt
:id: RUL-missing_folder_never_recreated
:status: ruled
:criticality: high
:anti: yes
:verify: required
:refines: RUL-missing_folder_blocks

A missing managed folder SHALL never be recreated outside initialization: no phase organizes media into a structure it
had to rebuild.
:::

:::{rul} The block names the missing folders
:id: RUL-missing_folder_named
:status: ruled
:criticality: med
:verify: required
:refines: RUL-missing_folder_blocks

The block of a missing managed folder SHALL name the missing folders and say that something is wrong.
:::

:::{rul} The block tells the user to restore the folders
:id: RUL-missing_folder_remedy_told
:status: ruled
:criticality: med
:verify: required
:refines: RUL-missing_folder_named

The block of a missing managed folder SHALL tell the user to restore the folders and run again.
:::

:::{rul} An empty folder restores a missing one
:id: RUL-empty_folder_restores
:status: ruled
:criticality: med
:verify: required
:refines: RUL-missing_folder_blocks

An empty folder put back in a missing managed folder's place SHALL restore it.
:::

:::{rul} An empty inbox is normal
:id: RUL-empty_inbox_normal
:status: ruled
:criticality: med
:anti: yes
:verify: required
:refines: RUL-missing_folder_blocks

An empty inbox SHALL be normal — the steady state, not a missing folder.
:::

:::{rul} The shape is checked first
:id: RUL-shape_checked_first
:status: ruled
:criticality: med
:verify: required
:upholds: INV-undisturbed_shape

Each phase SHALL check the workspace's shape at its start — right after the lock and the seal check, and before the
workspace check ({need}`RUL-workspace_checked_first`), scanning, planning or changing anything.
:::

## 5. Camera groups, derived once

:::{def} A camera group
:id: DEF-camera_group
:status: ruled

A **camera group** is the photos one camera or device took, identified by a key derived from the device-identity
metadata the files carry.
:::

:::{rul} Prep derives the camera group
:id: RUL-prep_derives_camera_group
:status: ruled
:criticality: med
:verify: required
:uses: DEF-camera_group

Prep SHALL derive each file's camera group from its device-identity metadata.
:::

:::{rul} The camera group is in what prep hands geotag
:id: RUL-camera_group_in_handoff
:status: ruled
:criticality: med
:verify: required
:refines: RUL-prep_derives_camera_group
:uses: DEF-camera_group, DEF-handoff

Prep SHALL record each file's camera group in what it hands geotag.
:::

:::{rul} The camera group is in prep's own records
:id: RUL-camera_group_in_prep_records
:status: ruled
:criticality: med
:verify: required
:refines: RUL-prep_derives_camera_group
:uses: DEF-camera_group

Prep SHALL record each file's camera group in its own records.
:::

:::{rul} Geotag reuses prep's camera group
:id: RUL-geotag_reuses_camera_group
:status: ruled
:criticality: med
:anti: yes
:verify: required
:refines: RUL-prep_derives_camera_group

Geotag SHALL use the camera group prep derived, never deriving a file's identity again.
:::

:::{rul} The derivation carries a version
:id: RUL-camera_group_derivation_versioned
:status: ruled
:criticality: med
:anti: yes
:verify: required
:refines: RUL-prep_derives_camera_group

How camera groups are derived SHALL carry a version taking part in the checks of freshness and of dependencies, so that
a change to the derivation is detected and old and new groups are never silently mixed.
:::

:::{rul} A camera group is known once it is classified
:id: RUL-known_when_classified
:status: ruled
:criticality: low
:verify: required
:uses: RUL-camera_classes_not_derivation

A camera group SHALL be known when the configuration classes it as a phone or as a camera with a fixed clock, and
unknown otherwise.
:::

## 6. One filename format

:::{def} A recorded time
:id: DEF-recorded_time
:status: ruled

A file's **recorded time** is the time of its making that its own metadata holds, as the camera's clock read it:
uncorrected, with no timezone.
:::

:::{rul} Which field is the recorded time
:id: RUL-recorded_time_order
:status: ruled
:criticality: med
:verify: required
:uses: DEF-recorded_time

A file's recorded time SHALL be read from the first of its `DateTimeOriginal`, `CreateDate` and `ModifyDate` that
holds a valid time; a field present but holding none is passed over.
:::

:::{def} A timestamp name
:id: DEF-timestamp_name
:status: ruled
:uses: DEF-prep, DEF-geotag

A file's **timestamp name** is the name prep and geotag give it from its timestamp, in the one format the configuration
sets, followed by a differentiating suffix when that name is taken.
:::

:::{rul} One format, set by the configuration
:id: RUL-one_filename_format
:status: ruled
:criticality: med
:verify: required
:uses: DEF-timestamp_name

Prep and geotag SHALL name files from a timestamp in one format for the whole pipeline, not one for each phase.
:::

:::{rul} The format is set by the configuration
:id: RUL-filename_format_configured
:status: ruled
:criticality: med
:verify: required
:refines: RUL-one_filename_format
:uses: DEF-timestamp_name

The filename format SHALL be set by the configuration, hard-coded by neither prep nor geotag.
:::

:::{rul} A taken name gets a suffix, never clobbering
:id: RUL-suffix_no_clobber
:status: ruled
:criticality: high
:anti: yes
:verify: required

A file whose timestamp name is already taken SHALL get a differentiating suffix, allocated without clobbering: against
every name on disk and every name planned in the run, so that two files never collide.
:::

:::{rul} The suffix is zero-padded
:id: RUL-suffix_zero_padded
:status: ruled
:criticality: low
:verify: required
:refines: RUL-suffix_no_clobber

The differentiating suffix SHALL be zero-padded.
:::

:::{rul} The suffix is allocated deterministically
:id: RUL-suffix_deterministic
:status: ruled
:criticality: high
:verify: required
:refines: RUL-suffix_no_clobber

The differentiating suffix SHALL be allocated deterministically.
:::

:::{rul} Names are compared without regard to case
:id: RUL-suffix_case_insensitive
:status: ruled
:criticality: high
:verify: required
:refines: RUL-suffix_no_clobber

A name SHALL be taken when it matches a name on disk or planned in the run without regard to case.
:::

:::{rul} Prep and geotag take the first free name
:id: RUL-suffix_choice_by_phase
:status: ruled
:criticality: med
:verify: required
:refines: RUL-suffix_no_clobber

Prep and geotag SHALL take the first free name — the name with no suffix when it is free, otherwise the lowest free
suffix — by one identical rule.
:::

:::{rul} Merge takes the suffix above the highest used
:id: RUL-merge_suffix_above_highest
:status: ruled
:criticality: med
:verify: required
:refines: RUL-suffix_no_clobber

Merge SHALL take the suffix above the highest already used for a name, never a lower one that has come free.
:::

:::{rul} Prep's name is provisional
:id: RUL-prep_name_provisional
:status: ruled
:criticality: med
:verify: required

Prep SHALL derive a file's name from its raw timestamp, as the camera recorded it, for organizing and ordering only — a
provisional name, which prep never corrects, resolves to a timezone or converts to UTC.
:::

:::{rul} Geotag's name is final
:id: RUL-geotag_name_final
:status: ruled
:criticality: med
:verify: required

Geotag SHALL recompute a file's name from its corrected local time at the destination — its resolved true time, in the
destination's civil timezone — and rename it to that final name.
:::

:::{rul} An uncorrected file keeps its name
:id: RUL-uncorrected_keeps_its_name
:status: ruled
:criticality: med
:verify: required
:uses: RUL-prep_name_provisional, RUL-geotag_name_final

A file's name SHALL change between prep and geotag only when its timestamp is corrected, or its extension is not in
lowercase: geotag plans no rename for a file whose time is not corrected but to lowercase its extension.
:::

:::{def} An untimed name
:id: DEF-untimed_name
:status: ruled
:uses: DEF-prep

A file's **untimed name** is the name prep gives a media file with no recorded time: the name it came with, behind a
mark that says so.
:::

:::{rul} The untimed mark is taken once
:id: RUL-untimed_mark_once
:status: ruled
:criticality: low
:verify: required
:uses: DEF-untimed_name

A file that comes in under a name already carrying the untimed mark SHALL keep that name as its untimed name, the mark
not added again.
:::

:::{rul} A misnamed file outside the inbox stops prep
:id: RUL-misnamed_file_stops_prep
:status: ruled
:criticality: high
:verify: required
:uses: DEF-timestamp_name, DEF-untimed_name

A media file outside the inbox whose name is neither its timestamp name nor, lacking a recorded time, its untimed name
SHALL stop prep.
:::

:::{rul} Every misnamed file is named
:id: RUL-misnamed_file_named
:status: ruled
:criticality: med
:verify: required
:refines: RUL-misnamed_file_stops_prep

Prep SHALL name every misnamed file it finds.
:::

:::{rul} A misnamed file is given the name it should carry
:id: RUL-misnamed_file_expected_name
:status: ruled
:criticality: med
:verify: required
:refines: RUL-misnamed_file_named

Prep SHALL give, with each misnamed file it names, the name the file should carry.
:::

:::{rul} No meaning is read from a file's name
:id: RUL-no_meaning_from_names
:status: ruled
:criticality: med
:anti: yes
:verify: required
:refines: RUL-misnamed_file_stops_prep

No phase SHALL read meaning from a file's name: its timestamp comes from its metadata.
:::

:::{rul} A redundant JPG gets its timestamp name
:id: RUL-redundant_jpg_timestamp_named
:status: ruled
:criticality: low
:verify: required
:uses: DEF-timestamp_name, DEF-untimed_name

A JPG prep sets aside as redundant to its RAW SHALL get its timestamp name, or with no recorded time its untimed name,
as any file prep files does.
:::

:::{rul} A set-aside JPEG may carry its RAW's name
:id: RUL-set_aside_jpeg_named_as_raw
:status: ruled
:criticality: med
:anti: yes
:verify: required
:refines: RUL-misnamed_file_stops_prep
:uses: RUL-set_aside_jpeg_renamed_with_raw

A JPEG set aside beside its RAW that carries that RAW's name, extension aside, SHALL NOT stop prep as misnamed.
:::

:::{rul} The format is fixed once files are named in it
:id: RUL-format_fixed_once_named
:status: ruled
:criticality: med
:verify: required
:uses: RUL-one_filename_format

Once prep has named a workspace's files in a format, a change to the format SHALL stop every phase.
:::

## 7. The tracks, kept outside the managed folders

:::{def} The tracks
:id: DEF-tracks
:status: ruled
:uses: DEF-geotag, DEF-configuration

A workspace's **tracks** are the recorded position logs geotag reads as evidence: to propose time anchors, and to place
photos along them by interpolation or extrapolation. The configuration says where they are.
:::

:::{rul} Only geotag reads the tracks
:id: RUL-tracks_geotag_only
:status: ruled
:criticality: med
:anti: yes
:verify: required
:uses: DEF-tracks

Geotag SHALL be the only phase that reads the tracks — scanning their location, parsing them, fingerprinting them and
using them as evidence; prep never reads, parses, fingerprints or moves them, nor otherwise acts on them.
:::

:::{rul} The tracks lie outside the managed folders
:id: RUL-tracks_outside_managed_folders
:status: ruled
:criticality: med
:anti: yes
:verify: required
:refines: RUL-checked_paths
:uses: DEF-tracks

The tracks' location SHALL lie outside the managed folders — neither inside one nor containing one — a configuration
that places it otherwise being refused before any phase uses it. Where outside them is the configuration's choice, not
part of this contract.
:::

:::{rul} A track file stops prep
:id: RUL-track_files_block_prep
:status: ruled
:criticality: high
:anti: yes
:verify: required
:uses: DEF-tracks

A track file — a recorded position log in any of the usual formats, whether or not geotag reads that format — found
anywhere prep inventories, in the dump or in a managed folder, SHALL block prep's plan.
:::

:::{rul} A track file stays where it is
:id: RUL-track_file_left_in_place
:status: ruled
:criticality: high
:anti: yes
:verify: required
:refines: RUL-track_files_block_prep
:excepts: RUL-inbox_non_media_to_strays

Prep SHALL leave a track file where it is: never moving it, to the strays folder or anywhere else, and never handling it
as a file of no media class is handled.
:::

:::{rul} The tracks are a dependency of what geotag derives from them
:id: RUL-tracks_in_dependencies
:status: ruled
:criticality: med
:verify: required
:uses: DEF-tracks, DEF-dependency_cascade

Geotag SHALL record a hash of the tracks as a dependency of every record it derives with them — the time decisions,
the drift validation, the GPS decisions and the executable plan — so that a change to the tracks makes those records
stale.
:::

## 8. Nothing used once what it came from has changed

:::{def} A fingerprint
:id: DEF-fingerprint
:status: ruled

A media file's **fingerprint** is the identity of its content apart from its metadata — a photo's decoded pixels, a
video's streams. Unqualified, *fingerprint* means this.
:::

:::{def} A hash
:id: DEF-hash
:status: ruled

A record's **hash** is a digest of its exact bytes — of a control record, or of the configuration. Unqualified, *hash*
means this.
:::

:::{def} The dependency cascade
:id: DEF-dependency_cascade
:status: ruled
:uses: DEF-fingerprint, DEF-hash, DEF-config_areas

The **dependency cascade** is how the phases keep a record from being used once what it was made from has changed: each
record carries what it depends on — media by their fingerprints, records and the tracks by their hashes, settings by a hash
of the configuration or of the areas the record reads, and the code and tool versions that made it — and each use checks them first. Its full name, the
*dependency-fingerprint/hash cascade*, says that it tracks both kinds of identity.
:::

:::{inv} No record is used once what it came from has changed
:id: INV-no_stale_use
:status: ruled
:criticality: high
:anti: yes
:verify: required
:uses: DEF-dependency_cascade

No phase SHALL use a record once anything it was derived from has changed.
:::

:::{rul} A phase validates what it derives from first
:id: RUL-dependencies_validated_before_deriving
:status: ruled
:criticality: high
:verify: required
:upholds: INV-no_stale_use
:uses: DEF-dependency_cascade

Each phase SHALL validate what it derives a record from before it creates the record.
:::

:::{rul} A record carries what it was derived from
:id: RUL-dependencies_recorded_in_record
:status: ruled
:criticality: high
:verify: required
:upholds: INV-no_stale_use
:uses: DEF-dependency_cascade

Each phase SHALL record in a record it creates the dependencies it was derived from.
:::

:::{rul} What cannot be checked counts as changed
:id: RUL-unchecked_counts_as_changed
:status: ruled
:criticality: high
:anti: yes
:verify: required
:refines: INV-no_stale_use

A dependency that is missing, or cannot be checked, SHALL count as changed.
:::

:::{rul} A fingerprint survives what the pipeline does to a file
:id: RUL-fingerprint_survives_mutation
:status: ruled
:criticality: med
:verify: required
:uses: DEF-fingerprint

A media file's fingerprint SHALL stay the same when the pipeline rewrites its metadata or its position, or renames it.
:::

:::{rul} Another image decoder is a reason to check a fingerprint
:id: RUL-engine_change_is_checked
:status: ruled
:criticality: high
:verify: required
:uses: DEF-fingerprint

A photo's fingerprint taken under another version of the image decoder SHALL be taken again before a phase relies on it.
:::

:::{rul} A photo's fingerprint covers every frame
:id: RUL-fingerprint_covers_every_frame
:status: ruled
:criticality: high
:verify: required

A photo's fingerprint SHALL be taken over every frame of the file, in their order.
:::

:::{rul} A video's fingerprint covers every stream
:id: RUL-fingerprint_covers_every_stream
:status: ruled
:criticality: med
:verify: required

A video's fingerprint SHALL be taken over every stream of the file.
:::

:::{rul} Fingerprints are compared only within one method
:id: RUL-fingerprint_method_is_the_builds
:status: ruled
:criticality: high
:anti: yes
:verify: required
:uses: DEF-handoff

Geotag and merge SHALL NOT proceed on a handoff whose fingerprints were taken by a method other than the build's own.
:::

:::{rul} A fingerprint taken again is the same photo's
:id: RUL-retaken_fingerprint_same_photo
:status: ruled
:criticality: high
:verify: required
:uses: DEF-fingerprint, RUL-engine_change_is_checked

A fingerprint taken again under another version of the image decoder whose value is new SHALL be read as the same photo's —
never, for a changed version alone, as a different photo's.
:::

:::{rul} A hash changes with any byte
:id: RUL-hash_detects_any_change
:status: ruled
:criticality: med
:verify: required
:uses: DEF-hash

A record's hash SHALL change on any change to its bytes.
:::

:::{rul} A record is checked as a dependency by its hash
:id: RUL-hash_is_the_dependency_check
:status: ruled
:criticality: high
:verify: required
:uses: DEF-hash

A record SHALL be checked as a dependency by its hash — prep's handoff excepted, which is checked by its content.
:::

:::{rul} The same content is written as the same bytes
:id: RUL-records_written_alike
:status: ruled
:criticality: med
:verify: required

A record that another record or a later run depends on SHALL be written as the same bytes whenever its content is the
same, so that its hash changes only when what it says does.
:::

## 9. One loop across the phases

:::{def} The operator loop
:id: DEF-operator_loop
:status: ruled
:uses: DEF-prep, DEF-geotag, DEF-merge, DEF-managed_folders

The **operator loop** is how the user drives the three phases through one workspace's life: prep organizes a dump; the
user sorts photos into photos by destination; prep records the sort; geotag is re-run, the user deciding what it asks,
until its plan is ready, and executes it; more dumps may follow, each from prep again; finalize closes the workspace's
record; merge moves it into the library. Each phase's own loop is in its own spec; this is the sequence across them.
:::

:::{def} Finalize
:id: DEF-finalize
:status: ruled
:uses: DEF-geotag

**Finalize** is geotag's closing command, given once the user judges the workspace's media done: it assembles the
workspace's permanent record and its complete transformation log.
:::

:::{def} Development
:id: DEF-development
:status: ruled
:uses: DEF-library

**Development** is the later processing of photos into distribution copies — the JPEG and TIFF breakout — kept in
subfolders of a destination in the library.
:::

:::{rul} Prep leaves the inbox empty
:id: RUL-prep_empties_inbox
:status: ruled
:criticality: med
:verify: required
:uses: DEF-managed_folders

A prep execution that carries out its whole plan SHALL leave the inbox empty.
:::

:::{rul} Only photos are sorted into photos by destination
:id: RUL-sort_photos_only
:status: ruled
:criticality: med
:anti: yes
:verify: required
:uses: DEF-operator_loop, DEF-managed_folders, DEF-media_class

Geotag and merge SHALL NOT proceed while photos by destination holds a video or a file of no media class.
:::

:::{rul} Geotag does not plan over an unrecorded sort
:id: RUL-prep_records_sort
:status: ruled
:criticality: high
:anti: yes
:verify: required
:uses: DEF-operator_loop, DEF-prep, DEF-geotag

Geotag SHALL NOT plan while photos by destination holds a photo prep has not recorded where it now is.
:::

:::{rul} Prep records a sort from sizes and times alone
:id: RUL-sort_recorded_by_stat
:status: ruled
:criticality: med
:verify: required
:refines: RUL-prep_records_sort

A prep run after the latest sort SHALL record the moves from the files' sizes and modification times alone, carrying
each moved file's identity forward without reading it again.
:::

:::{rul} Geotag plans only on a record that still holds
:id: RUL-geotag_plans_on_current_record
:status: ruled
:criticality: high
:anti: yes
:verify: required
:refines: RUL-prep_records_sort

Geotag SHALL NOT plan while a photo prep recorded in photos by destination is gone, or differs in size or modification
time from prep's record.
:::

:::{rul} Geotag may be re-run until merge
:id: RUL-geotag_rerunnable
:status: ruled
:criticality: med
:verify: required
:uses: DEF-geotag, DEF-merge

Geotag SHALL be re-runnable any number of times — after a successful execution too — for as long as the workspace has
not been merged.
:::

:::{rul} A re-run changes nothing already settled
:id: RUL-geotag_rerun_keeps_settled
:status: ruled
:criticality: high
:anti: yes
:verify: required
:refines: RUL-geotag_rerunnable
:uses: RUL-decision_kept, RUL-mutate_on_difference

A geotag re-run SHALL recognise a time an earlier run corrected, never correcting it again.
:::

:::{rul} A re-run derives again a position geotag wrote
:id: RUL-rerun_rederives_written_position
:status: ruled
:criticality: high
:anti: yes
:verify: required
:refines: RUL-geotag_rerun_keeps_settled
:uses: RUL-decision_kept, RUL-mutate_on_difference

A geotag re-run SHALL derive again and replace a position geotag wrote, never keeping it as the file's own.
:::

:::{rul} A time changed since geotag wrote the photo stops the plan
:id: RUL-changed_time_stops_plan
:status: ruled
:criticality: high
:anti: yes
:verify: required
:refines: RUL-geotag_rerun_keeps_settled
:uses: DEF-geotag, DEF-recorded_time, DEF-own_values

Geotag SHALL NOT plan while a photo it has written to holds a time that is neither the photo's own from before
geotag's first write nor one geotag wrote, and the user has not said which the photo keeps — neither writing its own
time back over it nor taking it as the photo's recorded time unasked.
:::

:::{rul} Geotag asks which time a changed photo keeps
:id: RUL-changed_time_asked
:status: ruled
:criticality: high
:verify: required
:refines: RUL-changed_time_stops_plan
:uses: DEF-decision

Geotag SHALL ask the user, of each photo holding a time changed since geotag wrote it, whether the photo keeps the
time it holds or takes back geotag's.
:::

:::{rul} A time the user keeps is the photo's true local time
:id: RUL-changed_time_kept_is_true
:status: ruled
:criticality: high
:verify: required
:refines: RUL-changed_time_asked
:uses: DEF-recorded_time, DEF-destination, DEF-clock_offset

A time the user keeps SHALL be taken as the photo's true time, local to its destination: read by the destination's
timezone, corrected by no camera's clock offset, and decided from as such on every later run.
:::

:::{rul} A kept time is no reading of the camera's clock
:id: RUL-kept_time_not_clock_evidence
:status: ruled
:criticality: high
:anti: yes
:verify: required
:refines: RUL-changed_time_kept_is_true
:uses: DEF-camera_group, DEF-clock_offset

Geotag SHALL NOT take a time the user kept as evidence of the clock offset of the photo's camera.
:::

:::{rul} A kept time's offset tag that its zone does not give is told
:id: RUL-kept_time_tag_disagreement_told
:status: ruled
:criticality: med
:verify: required
:refines: RUL-changed_time_asked

Geotag SHALL tell the user of each photo whose time it asks about whether to keep, and whose offset tag holds an offset
its destination's timezone does not give at that time, naming the photo.
:::

:::{rul} A kept time's offset tag that its zone does not give is recorded
:id: RUL-kept_time_tag_disagreement_recorded
:status: ruled
:criticality: med
:verify: required
:refines: RUL-changed_time_asked

Each photo whose time geotag asks about whether to keep, and whose offset tag holds an offset its destination's
timezone does not give at that time, SHALL be recorded in the time decisions as such, with the offset its tag holds and
the timezone's.
:::

:::{rul} A time taken back is written again
:id: RUL-changed_time_restored
:status: ruled
:criticality: high
:verify: required
:refines: RUL-changed_time_asked

Where the user takes back geotag's time, geotag SHALL plan to write its time again over the one the photo holds,
decided as before the change: from the photo's own time, or from the true time the user kept for it.
:::

:::{rul} Geotag's gates are the present state, not its history
:id: RUL-geotag_gates
:status: ruled
:criticality: high
:anti: yes
:verify: required
:uses: DEF-geotag, DEF-managed_folders

Geotag SHALL NOT proceed unless the workspace now satisfies its gates: photos by date holds no photo; photos
by destination holds only photos and no development subfolder; prep has recorded every photo in it; and the inbox is
empty.
:::

:::{rul} What ran before does not bear on geotag's gates
:id: RUL-geotag_gates_ignore_history
:status: ruled
:criticality: high
:anti: yes
:verify: required
:refines: RUL-geotag_gates
:uses: DEF-geotag, DEF-managed_folders

Whether, or how often, prep, the sort or geotag ran before SHALL NOT bear on whether geotag proceeds, so the user may
run any number of prep and sort cycles before geotagging.
:::

:::{rul} A re-run does as much as what changed requires
:id: RUL-rerun_does_what_changed
:status: ruled
:criticality: low
:verify: required
:refines: RUL-geotag_rerunnable, RUL-remake_only_what_depends
:uses: DEF-dependency_cascade

A geotag re-run SHALL redo exactly the work its changed inputs require — new media, an edited setting, changed tracks, a
withdrawn or altered decision, a refreshed handoff — and no more.
:::

:::{rul} A re-run asks only about what the change affects
:id: RUL-rerun_asks_only_affected
:status: ruled
:criticality: low
:verify: required
:refines: RUL-rerun_does_what_changed
:uses: DEF-dependency_cascade

A re-run SHALL ask for new decisions only for the items the change affects.
:::

:::{rul} More dumps may follow until merge
:id: RUL-more_dumps_until_merge
:status: ruled
:criticality: med
:verify: required
:uses: DEF-operator_loop, DEF-merge, DEF-dump

A new dump SHALL be accepted into the inbox at any point before merge, after a successful geotag too; the loop then
resumes from prep.
:::

:::{rul} Finalize is its own command
:id: RUL-finalize_explicit
:status: ruled
:criticality: med
:anti: yes
:verify: required
:uses: DEF-finalize

Finalize SHALL be a command of its own, never a side effect of geotag's execution.
:::

:::{rul} Merge requires a finalized workspace
:id: RUL-merge_takes_finalized_current
:status: ruled
:criticality: high
:anti: yes
:verify: required
:uses: DEF-finalize, DEF-merge, DEF-managed_folders

Merge SHALL require that geotag's execution succeeded and the workspace was finalized, and refuse a workspace that was
not.
:::

:::{rul} Merge refuses photos by destination changed since finalize
:id: RUL-merge_refuses_changed_since_finalize
:status: ruled
:criticality: high
:anti: yes
:verify: required
:refines: RUL-merge_takes_finalized_current

Merge SHALL refuse when photos by destination has changed since finalize, so that what reaches the library is always
the corrected, named, fully recorded set.
:::

:::{rul} A refresh describing only a prep run is not a change
:id: RUL-prep_refresh_not_a_change
:status: ruled
:criticality: high
:anti: yes
:verify: required
:refines: RUL-merge_refuses_changed_since_finalize

A rewrite of the handoff that changes only what describes a prep run SHALL NOT count, for merge, as a change since
finalize.
:::

:::{rul} Merge ends the workspace
:id: RUL-merge_is_terminal
:status: ruled
:criticality: high
:anti: yes
:verify: required
:uses: DEF-merge, DEF-workspace

Merge SHALL be the last phase run in a workspace: once it succeeds, more media goes to a fresh workspace.
:::

:::{rul} The library accepts merges from many workspaces
:id: RUL-library_takes_many_workspaces
:status: ruled
:criticality: med
:verify: required

The library SHALL accept merges from many workspaces.
:::

:::{rul} Development happens in the library, after merge
:id: RUL-development_after_merge
:status: ruled
:criticality: high
:anti: yes
:verify: required
:uses: DEF-development, DEF-managed_folders

A development subfolder anywhere in photos by destination — even an empty one — SHALL stop geotag's planning,
execution and finalize, and merge.
:::

:::{rul} A development subfolder is known whatever its case
:id: RUL-development_subfolder_any_case
:status: ruled
:criticality: high
:verify: required
:refines: RUL-development_after_merge
:uses: DEF-development

A folder SHALL count as a development subfolder whatever the case of its name.
:::

## 10. Change only what needs changing

:::{inv} A run changes only what its inputs require
:id: INV-change_only_what_needs
:status: ruled
:criticality: high
:anti: yes
:verify: by_rules
:uses: DEF-prep, DEF-geotag, DEF-merge

Every phase SHALL change only what its inputs actually require, as far as the work allows — redoing no settled work to
be safe, and leaving no file in a state other than its inputs require.
:::

:::{rul} Valid work is reused
:id: RUL-reuse_valid_work
:status: ruled
:criticality: med
:verify: required
:refines: INV-change_only_what_needs

Work already done and still valid SHALL be reused, not repeated — a file's content and metadata read, and the tracks
parsed, only for inputs that are new or have changed.
:::

:::{rul} A decision is kept while its target is unchanged
:id: RUL-decision_kept
:status: ruled
:criticality: high
:anti: yes
:verify: required
:refines: INV-change_only_what_needs

A decision the user made SHALL be kept, by every phase and through every run, while what it decides about is
unchanged.
:::

:::{rul} Only what depends on a change is made again
:id: RUL-remake_only_what_depends
:status: ruled
:criticality: med
:verify: required
:uses: DEF-dependency_cascade
:refines: INV-change_only_what_needs

When an input changes, only the records that depend on it SHALL be made again, every other record left as it is.
:::

:::{rul} A file is changed only where it differs
:id: RUL-mutate_on_difference
:status: ruled
:criticality: med
:anti: yes
:verify: required
:refines: INV-change_only_what_needs

In every phase and every run, a file SHALL be moved, renamed or written only where its current state differs from what
the run requires of it: a file already in its place, with its name and its metadata, produces no operation.
:::

:::{rul} A run over unchanged inputs changes nothing
:id: RUL-no_op_run
:status: ruled
:criticality: med
:verify: required
:refines: INV-change_only_what_needs

A phase run over a workspace whose relevant state has not changed SHALL change nothing.
:::

:::{rul} Planning over unchanged inputs makes the same plan
:id: RUL-no_op_run_same_result
:status: ruled
:criticality: med
:verify: required
:upholds: INV-change_only_what_needs

Planning a workspace whose relevant state has not changed SHALL produce the same plan — the same operations,
fingerprints and names.
:::

:::{rul} A run over unchanged inputs never takes earlier work for an error
:id: RUL-no_op_run_reports_reuse
:status: ruled
:criticality: low
:verify: required
:refines: RUL-no_op_run

A run over unchanged inputs SHALL never treat earlier work as an error.
:::

## 11. Nothing changes that the user did not write down

:::{def} A decision
:id: DEF-decision
:status: ruled
:uses: DEF-geotag

A **decision** is a value the user records in one of geotag's records for the tool to act on — a destination's
timezone, an accepted time anchor, a clock offset, a confirmed drift check, a manual position, a folder fallback, a
content acceptance in the execution summary — among others.
:::

:::{def} A photo's own values
:id: DEF-own_values
:status: ruled
:uses: DEF-geotag, DEF-workspace_database

A photo's **own values** are the time, offset and position it held before geotag first wrote to it, pinned then and
kept in the workspace database; every plan decides from them.
:::

:::{inv} Every change follows from the record
:id: INV-every_change_from_the_record
:status: ruled
:criticality: high
:anti: yes
:verify: by_rules
:uses: DEF-decision

Every change a phase makes SHALL follow from a decision the user recorded, or from a fixed rule applied to recorded
inputs — never from a choice the tool makes on its own. The
tool *proposes*; the user *decides*.
:::

:::{rul} The user writes the decisions
:id: RUL-user_writes_decisions
:status: ruled
:criticality: high
:anti: yes
:verify: required
:upholds: INV-every_change_from_the_record
:uses: DEF-decision, RUL-decision_kept

A decision field's value SHALL be written by the user alone, no phase ever overwriting what the user wrote.
:::

:::{rul} The tool lays out every decision's fields
:id: RUL-decision_fields_laid_out
:status: ruled
:criticality: med
:verify: required

A phase SHALL create every field a decision needs, so the user fills in values, never structure.
:::

:::{rul} Prep takes no decision
:id: RUL-prep_takes_no_decision
:status: ruled
:criticality: med
:verify: required
:upholds: INV-every_change_from_the_record
:uses: DEF-prep

Prep SHALL ask the user for no decision, organizing from the state of the workspace and its configuration alone.
:::

:::{rul} The cause of every change can be found
:id: RUL-cause_locatable
:status: ruled
:criticality: med
:verify: required
:upholds: INV-every_change_from_the_record
:uses: DEF-decision, DEF-dependency_cascade

Every change a phase executes SHALL be traceable in the records, from the decision and the inputs it was made from,
through the plan, to the record of what ran — so a wrong result points at a recorded choice.
:::

:::{rul} A wrong decision is fixed in the record
:id: RUL-decision_revisable
:status: ruled
:criticality: high
:anti: yes
:verify: required
:upholds: INV-every_change_from_the_record
:uses: DEF-decision, DEF-dependency_cascade

A decision SHALL be revised by changing it in the record and running again, the change reaching everything that depends
on it: no change the tool makes is irreversible at the level of the decisions, and a wrong choice never needs the
mutated files repaired by hand.
:::

:::{rul} Withdrawing a decision undoes it
:id: RUL-withdrawal_undoes
:status: ruled
:criticality: med
:verify: required
:refines: RUL-decision_revisable
:uses: DEF-own_values

Withdrawing a decision SHALL undo its effect, not merely stop asserting it: a manual position withdrawn gives the file
the position it would have had without it — its own, one from the tracks or its folder's fallback, or none, the
photo then waiting ({need}`RUL-unplaced_photo_waits`); a position derived by the tool is derived again.
:::

:::{rul} After a withdrawal the time and the name are recomputed in place
:id: RUL-withdrawal_recomputes_time_and_name
:status: ruled
:criticality: med
:verify: required
:refines: RUL-withdrawal_undoes

After a decision is withdrawn, a time and a name SHALL be recomputed where the file stands.
:::

:::{rul} A withdrawal never moves a file out of its destination
:id: RUL-withdrawal_keeps_destination
:status: ruled
:criticality: med
:verify: required
:refines: RUL-withdrawal_undoes

Withdrawing a decision SHALL never move a file out of its destination.
:::

## 12. The record of what was done, kept beyond the workspace

:::{def} The transformation log
:id: DEF-transformation_log
:status: ruled
:uses: DEF-fingerprint

The **transformation log** is the human-readable account, photo by photo and keyed by each photo's fingerprint, of
everything done to it and why. Each phase keeps its own, carrying the previous phase's forward.
:::

:::{def} The archival package
:id: DEF-archival_package
:status: ruled
:uses: DEF-control_records, DEF-transformation_log

The **archival package** is one archive, kept with the control records, holding the complete record of a dump's journey
through the pipeline — what was done to its photos and why. It is what the user keeps when the workspace goes away.
:::

:::{rul} The record is whole at the end of every phase
:id: RUL-record_whole_each_phase
:status: ruled
:criticality: med
:verify: required
:uses: DEF-transformation_log, DEF-control_records

At the end of every phase the workspace SHALL hold a complete, self-sufficient, human-readable record of everything done
to its files so far: whole whether or not any later phase ever runs, extended by each phase through its own work, a
phase not yet run reading as the workspace not having advanced, never as a record incomplete.
:::

:::{rul} Each phase writes only its own records
:id: RUL-phase_writes_own_records
:status: ruled
:criticality: high
:anti: yes
:verify: required
:uses: DEF-control_records

Each phase's records SHALL be written by that phase and by no other phase — the configuration
({need}`RUL-config_writers`) and the database ({need}`RUL-database_regions_disjoint`) under rules of their own: a phase
MAY create, rewrite or extend its own records across its runs, and reads every other phase's records read-only.
:::

:::{rul} An earlier record is carried forward by copying it
:id: RUL-carry_forward_by_copy
:status: ruled
:criticality: high
:anti: yes
:verify: required
:refines: RUL-phase_writes_own_records

To carry an earlier phase's record forward, a phase SHALL copy it to a record of its own and extend the copy — leaving
the earlier one untouched, and never deriving an earlier phase's history again.
:::

:::{rul} Finalize only reads and records
:id: RUL-finalize_non_destructive
:status: ruled
:criticality: med
:anti: yes
:verify: required
:uses: DEF-finalize, DEF-archival_package

Finalize SHALL change nothing in the workspace's media, its other records or the library, only reading the record that
already stands at the end of geotag and writing the package from it.
:::

:::{rul} What the package holds
:id: RUL-package_contents
:status: ruled
:criticality: med
:verify: required
:uses: DEF-archival_package, DEF-transformation_log, DEF-control_records

The archival package SHALL hold every control record but the scratch ones and those a run holds only while it runs, archived together with its own list of
them: the configuration that governed the workspace; every current decision and plan record, exactly as the pipeline
validated it; the database, with each phase's database image; every phase's transformation log; and every
run's journal.
:::

:::{rul} The package describes itself
:id: RUL-package_self_describing
:status: ruled
:criticality: low
:verify: required
:uses: DEF-archival_package

The package SHALL say which workspace it came from and which plan and execution it records.
:::

:::{rul} The package lists its contents with their hashes
:id: RUL-package_lists_contents
:status: ruled
:criticality: low
:verify: required
:refines: RUL-package_self_describing
:uses: DEF-archival_package

The package SHALL list its contents with each item's hash, so its integrity can be checked later.
:::

:::{rul} A photo's entry grows one phase at a time
:id: RUL-log_entry_grows
:status: ruled
:criticality: med
:anti: yes
:verify: required
:uses: DEF-transformation_log

A photo's entry in the log SHALL gather the steps of every phase it passes through and be whole through the latest of
them — so the latest phase's log is the full record.
:::

:::{rul} A phase only appends to a photo's entry
:id: RUL-log_entry_append_only
:status: ruled
:criticality: med
:anti: yes
:verify: required
:refines: RUL-log_entry_grows
:uses: DEF-transformation_log

Each phase SHALL only append its own steps to a photo's entry, never rewriting an earlier one — so each earlier log
stays its own phase's.
:::

:::{rul} The log is keyed by fingerprint
:id: RUL-log_keyed_by_fingerprint
:status: ruled
:criticality: med
:verify: required
:uses: DEF-transformation_log, DEF-fingerprint

The log SHALL key each photo's entry by its fingerprint.
:::

:::{rul} The log carries the chain of names and places
:id: RUL-log_carries_name_chain
:status: ruled
:criticality: med
:verify: required
:refines: RUL-log_keyed_by_fingerprint
:uses: DEF-transformation_log, DEF-fingerprint

A photo's entry in the log SHALL carry the chain of names and places it passed through.
:::

:::{rul} A file of no media class has no log entry
:id: RUL-no_log_entry_for_other
:status: ruled
:criticality: low
:verify: required
:refines: RUL-log_keyed_by_fingerprint

A file of no media class SHALL have no entry in the log.
:::

:::{rul} A step names the decision behind it
:id: RUL-log_cites_decisions
:status: ruled
:criticality: low
:verify: required
:uses: DEF-transformation_log, DEF-decision

A step that followed from a decision SHALL name that decision, so the why stands beside the what.
:::

:::{rul} Each step of a log names the run that made it
:id: RUL-log_step_names_run
:status: ruled
:criticality: med
:verify: required
:uses: DEF-transformation_log

Each step a phase adds to a photo's log SHALL name the run that made it.
:::

:::{rul} A manual position's reversal is logged like its application
:id: RUL-log_records_gps_reverts
:status: ruled
:criticality: med
:verify: required
:uses: DEF-transformation_log

A manual position applied, changed or withdrawn SHALL appear in the log with the position it replaced or restored, or
that there was none.
:::

:::{rul} A position written over latitude 0 and longitude 0 is logged with it
:id: RUL-log_records_null_island_replaced
:status: ruled
:criticality: med
:verify: required
:refines: RUL-log_records_gps_reverts
:uses: DEF-transformation_log

A position geotag writes over a photo's position of latitude 0 and longitude 0 SHALL appear in the log with the
position it replaced.
:::

:::{rul} A time written is logged with what it replaced and how it was found
:id: RUL-log_records_time_replaced
:status: ruled
:criticality: med
:verify: required
:uses: DEF-transformation_log, DEF-recorded_time

A time geotag writes SHALL appear in the log with the time and offset it replaced, the field the photo's time was read
from and the rule that turned it to UTC.
:::

:::{rul} Every other time field written is logged with what it held
:id: RUL-log_records_other_times_replaced
:status: ruled
:criticality: med
:verify: required
:refines: RUL-log_records_time_replaced
:uses: DEF-transformation_log, RUL-other_capture_times_corrected

A time geotag writes into another field in which the photo records when it was made SHALL appear in the log with the
value that field held.
:::

:::{rul} The log reads as it stands
:id: RUL-log_human_readable
:status: ruled
:criticality: low
:verify: required
:uses: DEF-transformation_log

The log SHALL be readable as it stands, with no separate report: with descriptive names, and values as a person reads
them — times, timezones and offsets.
:::

:::{rul} The log is stably ordered
:id: RUL-log_stably_ordered
:status: ruled
:criticality: low
:verify: required
:refines: RUL-log_human_readable
:uses: DEF-transformation_log

The log SHALL be stably ordered.
:::

:::{rul} History is kept across runs, as much as the log needs
:id: RUL-history_retained
:status: ruled
:criticality: med
:anti: yes
:verify: required
:uses: DEF-transformation_log

The records the log is made from SHALL be kept across runs in enough detail to rebuild every photo's history through
each phase — each step, the decision and inputs behind it, and the run that made it — never only the last run's.
Anything beyond that MAY be pruned.
:::

:::{rul} A history too thin to rebuild is never shown as whole
:id: RUL-partial_history_shown
:status: ruled
:criticality: med
:anti: yes
:verify: required
:refines: RUL-history_retained

A phase whose kept history cannot rebuild a photo's journey through it SHALL fail, or mark its record plainly partial —
never writing a log that looks whole but reflects only the last run.
:::

:::{def} The workspace database
:id: DEF-workspace_database
:status: ruled
:uses: DEF-workspace, DEF-control_records

The **workspace database** is the one database of record: what cartographer knows about the workspace's media — each
file's identity and metadata, what each phase derived from them, the values a photo held before geotag first changed
it, the track points geotag decided by, and the fingerprints of library files merge has read.
:::

:::{def} A phase's database image
:id: DEF-database_image
:status: ruled
:uses: DEF-workspace_database

A phase's **database image** is a copy of the workspace database as it stood at the end of that phase's latest
successful execution — geotag's, its finalize.
:::

:::{rul} One database, in the workspace
:id: RUL-one_database
:status: ruled
:criticality: med
:anti: yes
:verify: required
:uses: DEF-workspace_database, DEF-library

A workspace SHALL hold exactly one database of record.
:::

:::{rul} The library holds no database
:id: RUL-library_no_database
:status: ruled
:criticality: med
:anti: yes
:verify: required
:refines: RUL-library_never_altered
:uses: DEF-workspace_database, DEF-library

The library SHALL hold no database of record.
:::

:::{rul} Any other database is scratch
:id: RUL-other_databases_scratch
:status: ruled
:criticality: med
:verify: required
:refines: RUL-one_database

Any database a phase keeps besides the database of record SHALL be scratch: holding no decision and no history, safe
to delete at any time.
:::

:::{rul} A scratch database is not journalled
:id: RUL-scratch_database_not_journalled
:status: ruled
:criticality: med
:verify: required
:refines: RUL-other_databases_scratch

A scratch database SHALL NOT be journalled.
:::

:::{rul} A scratch database is not archived
:id: RUL-scratch_database_not_archived
:status: ruled
:criticality: med
:verify: required
:refines: RUL-other_databases_scratch

A scratch database SHALL NOT be archived.
:::

:::{rul} The database is part of the record
:id: RUL-database_is_record
:status: ruled
:criticality: low
:verify: required
:uses: DEF-workspace_database, DEF-archival_package

The workspace database SHALL be part of the record, never treated as a cache that may be deleted and rebuilt.
:::

:::{rul} The database is archived in the package
:id: RUL-database_archived
:status: ruled
:criticality: low
:verify: required
:refines: RUL-database_is_record
:uses: DEF-workspace_database, DEF-archival_package

The workspace database SHALL be archived in the package.
:::

:::{rul} Each phase writes only its own part of the database
:id: RUL-database_regions_disjoint
:status: ruled
:criticality: med
:anti: yes
:verify: required
:uses: DEF-workspace_database
:refines: RUL-phase_writes_own_records

Each phase SHALL write only its own part of the workspace database, no two phases writing the same rows — but the record
of the state the last execution left the workspace's files in, which every execution rewrites whole
({need}`RUL-execution_records_state`) and a prune trims of what it removes
({need}`RUL-quarantine_changed_only_by_prune`).
:::

:::{rul} Finalize only reads the database
:id: RUL-finalize_reads_database
:status: ruled
:criticality: med
:anti: yes
:verify: required
:refines: RUL-database_regions_disjoint

Finalize SHALL only read the workspace database.
:::

:::{rul} Each phase keeps an image of the database at its end
:id: RUL-database_image_each_phase
:status: ruled
:criticality: med
:verify: required
:uses: DEF-database_image, DEF-archival_package

Each phase SHALL keep its database image, refreshed by each of its successful executions — geotag's by its finalize.
:::

:::{rul} No other phase touches a phase's image
:id: RUL-image_untouched_by_other_phase
:status: ruled
:criticality: med
:verify: required
:refines: RUL-database_image_each_phase
:uses: DEF-database_image

A phase's database image SHALL be left untouched by every other phase.
:::

:::{rul} A run that does not succeed leaves the image as it was
:id: RUL-image_untouched_by_failed_run
:status: ruled
:criticality: med
:verify: required
:refines: RUL-database_image_each_phase
:uses: DEF-database_image

A phase's database image SHALL be left untouched by a run that does not succeed.
:::

:::{rul} A database image is never read back as working data
:id: RUL-image_never_working_data
:status: ruled
:criticality: med
:anti: yes
:verify: required
:refines: RUL-database_image_each_phase

A database image SHALL never be read back as working data.
:::

:::{rul} Every database image is archived
:id: RUL-images_archived
:status: ruled
:criticality: med
:verify: required
:refines: RUL-database_image_each_phase

Every database image present SHALL be archived in the package.
:::

:::{rul} An image is whole
:id: RUL-database_image_whole
:status: ruled
:criticality: med
:anti: yes
:verify: required
:uses: DEF-database_image

A database image SHALL be a consistent state of the database, never a copy torn mid-transaction.
:::

:::{rul} An interrupted capture leaves an image whole
:id: RUL-image_capture_atomic
:status: ruled
:criticality: med
:anti: yes
:verify: required
:refines: RUL-database_image_whole

An interrupted capture of a database image SHALL leave the earlier image or the new one, whole.
:::

## 13. Merge: the library kept, the workspace sealed

:::{def} A sealed workspace
:id: DEF-sealed_workspace
:status: ruled
:uses: DEF-workspace, DEF-merge

A workspace is **sealed** once merge has succeeded in it: marked as finished, by a mark only merge writes.
:::

:::{rul} Merge never alters the library
:id: RUL-library_never_altered
:status: ruled
:criticality: high
:anti: yes
:verify: required
:uses: DEF-merge, DEF-library

Merge SHALL never rename, overwrite, move, delete or change a file already in the library, an incoming photo whose place
is taken giving way instead.
:::

:::{rul} Merge reads the library only where it places a photo
:id: RUL-library_not_scanned
:status: ruled
:criticality: med
:anti: yes
:verify: required
:uses: DEF-merge, DEF-library

Merge SHALL touch the library only at the places its photos go, and read a library file only when one is already there —
never scanning, indexing or de-duplicating the library.
:::

:::{rul} A taken place is settled by content
:id: RUL-collision_by_content
:status: ruled
:criticality: high
:verify: required
:uses: DEF-merge, DEF-library, DEF-fingerprint
:refines: RUL-library_never_altered

Where an incoming photo's place in the library is taken, merge SHALL compare the two by fingerprint.
:::

:::{rul} The same content is already in the library
:id: RUL-collision_same_content
:status: ruled
:criticality: high
:verify: required
:refines: RUL-collision_by_content

A taken place holding the photo itself, byte for byte, SHALL mean the photo is already in the library: nothing is written there.
:::

:::{rul} The workspace's copy of a photo already in the library is removed
:id: RUL-collision_same_content_copy_removed
:status: ruled
:criticality: high
:verify: required
:refines: RUL-collision_same_content

Where a taken place holds the photo itself, byte for byte, the workspace's copy SHALL be removed.
:::

:::{rul} The same picture in another file blocks
:id: RUL-same_pixels_other_file_blocks
:status: ruled
:criticality: high
:anti: yes
:verify: required
:refines: RUL-collision_by_content
:uses: DEF-library, DEF-fingerprint

A photo whose picture the library already holds in a file of other bytes — the same pixels, other metadata — SHALL be
blocked, neither file removed, for the user to settle.
:::

:::{rul} Such a block names both files
:id: RUL-same_pixels_both_named
:status: ruled
:criticality: med
:verify: required
:refines: RUL-same_pixels_other_file_blocks

The report of a photo blocked for the same picture in another library file SHALL name both files.
:::

:::{rul} Different content is placed under a differentiating name
:id: RUL-collision_different_content
:status: ruled
:criticality: high
:anti: yes
:verify: required
:refines: RUL-collision_by_content

A taken place holding different content SHALL mean two photos share a name: the incoming one is placed under a
differentiating name.
:::

:::{rul} A collision that cannot be settled holds the photo back
:id: RUL-unsettled_collision_blocks
:status: ruled
:criticality: high
:anti: yes
:verify: required
:refines: RUL-collision_by_content
:uses: DEF-library

Where the library file in an incoming photo's place cannot be fingerprinted, merge SHALL leave that photo in photos by
destination — neither placing it there nor under another name.
:::

:::{rul} A photo held back does not stop the rest
:id: RUL-unsettled_collision_rest_proceeds
:status: ruled
:criticality: high
:verify: required
:refines: RUL-unsettled_collision_blocks
:uses: DEF-library

Where a collision that cannot be settled holds one photo back, merge SHALL go on with the rest.
:::

:::{rul} A library file is fingerprinted only when a collision needs it
:id: RUL-library_file_read_once
:status: ruled
:criticality: low
:verify: required
:uses: DEF-library, DEF-fingerprint, DEF-workspace_database

A library file's fingerprint SHALL be computed only when a collision needs it.
:::

:::{rul} A library file's fingerprint is kept while the file is unchanged
:id: RUL-library_fingerprint_kept
:status: ruled
:criticality: low
:verify: required
:refines: RUL-library_file_read_once
:uses: DEF-library, DEF-fingerprint, DEF-workspace_database

A library file's fingerprint, once computed, SHALL be kept, so that a library file unchanged since is never
fingerprinted again in the workspace, in that run or a later one, while the way photos are decoded is unchanged too —
save for the one check before a photo is removed from the workspace.
:::

:::{rul} A library file is fingerprinted again before a photo it holds is removed
:id: RUL-library_file_rechecked_before_removal
:status: ruled
:criticality: high
:verify: required
:refines: RUL-library_file_read_once

Before a photo is removed from the workspace because the library already holds it, the library file SHALL be
fingerprinted again, whatever is kept.
:::

:::{rul} The library's place is checked
:id: RUL-library_place_checked
:status: ruled
:criticality: high
:anti: yes
:verify: required
:uses: DEF-library, DEF-workspace
:refines: RUL-checked_paths

Merge SHALL check the library's configured place like every path the user writes, refusing it unless it is an existing
folder that neither lies inside the workspace nor holds it.
:::

:::{rul} The library lies outside every workspace
:id: RUL-library_outside_every_workspace
:status: ruled
:criticality: high
:anti: yes
:verify: required
:uses: DEF-library

A folder SHALL NOT be taken as the library while it is a workspace, lies inside one, or holds one among its own folders.
:::

:::{rul} A library is known by its mark alone
:id: RUL-library_known_by_mark
:status: ruled
:criticality: high
:anti: yes
:verify: required
:uses: DEF-library, DEF-merge

A folder SHALL be taken for a library by one mark in it and by nothing else, merge inspecting no structure of the
library, which has none of a workspace's folders, guard or lifecycle.
:::

:::{rul} Only the library setup makes the mark, once
:id: RUL-library_mark_made_by_setup
:status: ruled
:criticality: med
:verify: required
:refines: RUL-library_known_by_mark

Merge's library setup alone SHALL make the library's mark.
:::

:::{rul} Making the mark again changes nothing
:id: RUL-library_mark_idempotent
:status: ruled
:criticality: med
:verify: required
:refines: RUL-library_mark_made_by_setup

Making the library's mark again SHALL change nothing.
:::

:::{rul} Merge's plan, dry run and execution stop without the mark
:id: RUL-library_mark_required
:status: ruled
:criticality: high
:anti: yes
:verify: required
:refines: RUL-library_known_by_mark

Merge's plan, dry run and execution SHALL stop at once if the library's mark is absent.
:::

:::{rul} Merge creates in the library only what it places
:id: RUL-library_creates_only_placements
:status: ruled
:criticality: med
:anti: yes
:verify: required
:refines: RUL-library_never_altered

Beyond its mark and its lock, merge SHALL create in the library only the photos it places, the folders they go into,
while a photo crosses filesystems its temporary copy, and, while it tries the library's filesystem, the files it tries
it with.
:::

:::{rul} One merge at a time in a library
:id: RUL-library_lock
:status: ruled
:criticality: high
:anti: yes
:verify: required
:uses: DEF-library, DEF-merge

Merge SHALL hold a lock on the library for its whole run, besides the workspace's lock and not instead of it, so that no
two merges write one library at once, even from different workspaces.
:::

:::{rul} The library's lock holds only who holds it
:id: RUL-library_lock_holds_only_holder
:status: ruled
:criticality: low
:verify: required
:refines: RUL-library_lock

The library's lock SHALL hold nothing about the library but who holds it.
:::

:::{rul} A locked library is refused at once
:id: RUL-library_lock_fail_fast
:status: ruled
:criticality: high
:anti: yes
:verify: required
:refines: RUL-library_lock

A merge that finds the library locked SHALL stop at once, having changed nothing in the library.
:::

:::{rul} A dead merge's library lock is recoverable
:id: RUL-library_lock_stale_recovered
:status: ruled
:criticality: med
:verify: required
:refines: RUL-library_lock_fail_fast

A library lock left by a merge that died SHALL be recognisable as stale, and recoverable, as the workspace's lock is.
:::

:::{rul} The library is confirmed before it is locked
:id: RUL-library_confirmed_before_lock
:status: ruled
:criticality: med
:anti: yes
:verify: required
:refines: RUL-library_lock

Merge SHALL take the workspace's lock first, then check the library's place and its mark, and only then take the
library's lock, so that no lock is ever left in a folder that is not a library — a merge stopped at any of these steps
having changed nothing in the library.
:::

:::{rul} Merge moves, not copies
:id: RUL-merge_moves
:status: ruled
:criticality: high
:anti: yes
:verify: required
:uses: DEF-merge, DEF-library, DEF-managed_folders

Merge SHALL move each photo it places, not copy it.
:::

:::{rul} A photo leaves the workspace only once safe in the library
:id: RUL-merge_removes_once_placed
:status: ruled
:criticality: high
:anti: yes
:verify: required
:refines: RUL-merge_moves

Merge SHALL remove the workspace's copy of a photo it places only once the library's copy is verified in place.
:::

:::{rul} A photo merge cannot place stays where it is
:id: RUL-unplaced_photo_stays
:status: ruled
:criticality: high
:anti: yes
:verify: required
:refines: RUL-merge_moves

A photo merge cannot place SHALL stay where it is.
:::

:::{rul} A run that leaves a photo unplaced is never whole
:id: RUL-unplaced_photo_run_partial
:status: ruled
:criticality: high
:verify: required
:refines: RUL-seal_on_success_only

A merge run that leaves a photo unplaced SHALL NOT end whole: recorded partial, or failed where it left every photo
unplaced ({need}`RUL-merge_outcome_recorded`), and leaving the workspace unsealed.
:::

:::{rul} Merge resumes
:id: RUL-merge_resumable
:status: ruled
:criticality: med
:verify: required
:upholds: INV-change_only_what_needs
:uses: DEF-merge

A merge interrupted SHALL be finished by running it again, which applies only what is outstanding.
:::

:::{rul} Merging a merged batch changes nothing
:id: RUL-merged_batch_no_op
:status: ruled
:criticality: med
:verify: required
:refines: RUL-no_op_run
:uses: DEF-merge

Merging a batch already merged SHALL change nothing.
:::

:::{rul} Merge records where every photo landed
:id: RUL-merge_records_landing
:status: ruled
:criticality: low
:verify: required
:refines: RUL-cause_locatable
:uses: DEF-merge, DEF-transformation_log

Merge SHALL record, in its own records, where each photo landed in the library, whether it was renamed there, which were
already present, and what blocked the rest.
:::

:::{rul} Nothing is built from a finished merge's records
:id: RUL-nothing_built_from_merge_records
:status: ruled
:criticality: low
:verify: required
:refines: RUL-merge_is_terminal

Nothing SHALL be built from the records a finished merge leaves — its summary, its log, its database image and its
package. Merge's plan and journal, from which an interrupted merge resumes, are not among these.
:::

:::{rul} Merge remakes the package as part of its run
:id: RUL-merge_reseals
:status: ruled
:criticality: med
:verify: required
:uses: DEF-merge, DEF-archival_package

A merge that succeeds SHALL remake the archival package to hold its own records too, as part of the same run and with no
command of its own.
:::

:::{rul} Remaking the package re-derives nothing
:id: RUL-reseal_rederives_nothing
:status: ruled
:criticality: med
:anti: yes
:verify: required
:refines: RUL-merge_reseals

Merge SHALL remake the package from the records as they stand, re-deriving nothing of an earlier phase.
:::

:::{rul} Only a whole merge seals
:id: RUL-seal_on_success_only
:status: ruled
:criticality: high
:anti: yes
:verify: required
:uses: DEF-sealed_workspace, DEF-merge

Merge SHALL seal the workspace only when it succeeds whole — every photo by destination placed in the library or found
already there, none left — a partial, failed or interrupted merge leaving it unsealed.
:::

:::{rul} A merge of no photos seals
:id: RUL-empty_merge_seals
:status: ruled
:criticality: med
:verify: required
:refines: RUL-seal_on_success_only
:uses: DEF-sealed_workspace, DEF-merge

A merge with no finalized photo to merge SHALL succeed whole and seal the workspace, nothing being left to merge.
:::

:::{rul} The seal alone says a workspace is finished
:id: RUL-seal_is_authority
:status: ruled
:criticality: med
:anti: yes
:verify: required
:uses: DEF-sealed_workspace, DEF-managed_folders

Whether a workspace is finished SHALL be read from its seal alone, never from the state of its folders.
:::

:::{rul} A sealed workspace is never processed again
:id: RUL-sealed_refuses
:status: ruled
:criticality: high
:anti: yes
:verify: required
:refines: RUL-merge_is_terminal
:uses: DEF-sealed_workspace

In a sealed workspace prep, geotag and merge SHALL stop as they start, changing nothing but the owner record of the
workspace lock. Its records MAY still be read.
:::

:::{rul} The decision editor refuses a sealed workspace
:id: RUL-editor_refuses_sealed
:status: ruled
:criticality: high
:anti: yes
:verify: required
:refines: RUL-sealed_refuses

The decision editor SHALL NOT open a sealed workspace.
:::

:::{rul} The decision editor saves nothing into a sealed workspace
:id: RUL-editor_refuses_sealed_save
:status: ruled
:criticality: high
:anti: yes
:verify: required
:refines: RUL-editor_refuses_sealed

The decision editor SHALL NOT save into a sealed workspace.
:::

:::{rul} A sealed workspace's configuration records no library
:id: RUL-sealed_no_library_recorded
:status: ruled
:criticality: med
:anti: yes
:verify: required
:refines: RUL-sealed_refuses

Merge's library setup SHALL NOT record a library in a sealed workspace's configuration.
:::

:::{rul} Pruning the quarantine is still allowed
:id: RUL-sealed_prune_allowed
:status: ruled
:criticality: low
:verify: required
:excepts: RUL-sealed_refuses
:uses: DEF-sealed_workspace

Pruning the quarantine SHALL remain allowed in a sealed workspace — the only change allowed there.
:::

:::{rul} A new dump in a sealed workspace is pointed out
:id: RUL-sealed_new_dump_warned
:status: ruled
:criticality: med
:anti: yes
:verify: required
:uses: DEF-sealed_workspace
:refines: RUL-sealed_refuses

A command refusing a sealed workspace that finds anything where a dump would land — an entry at the workspace's top
level other than its managed folders and hidden entries, or anything in the inbox — SHALL say that a new dump is likely
there and must go to a fresh workspace.
:::

:::{rul} A new dump in a sealed workspace is left where it is
:id: RUL-sealed_new_dump_left
:status: ruled
:criticality: high
:anti: yes
:verify: required
:refines: RUL-sealed_new_dump_warned

A command refusing a sealed workspace SHALL leave a new dump it finds there exactly where it is.
:::

## 14. Every value the user writes is checked

:::{def} An authored value
:id: DEF-authored_value
:status: ruled
:uses: DEF-configuration, DEF-decision

An **authored value** is one the user writes by hand: a setting of the configuration, or a decision.
:::

:::{inv} No value the user writes is used unchecked
:id: INV-authored_values_checked
:status: ruled
:criticality: high
:anti: yes
:verify: required
:uses: DEF-authored_value, DEF-dependency_cascade

Every authored value SHALL be checked to be valid before it is used — besides, not instead of, the dependency cascade's
check that it has not changed.
:::

:::{rul} A configured path is checked
:id: RUL-checked_paths
:status: ruled
:criticality: med
:anti: yes
:verify: required
:uses: DEF-configuration, DEF-managed_folders, DEF-tracks
:refines: INV-authored_values_checked

A path the configuration names SHALL be neither empty nor blank, hold no character the platform forbids, and stay where
it must: the tracks' place outside the managed folders, the library's an existing folder that neither lies inside the workspace nor holds it.
:::

:::{rul} A snapshot's name is checked before any snapshot
:id: RUL-checked_snapshot_names
:status: ruled
:criticality: med
:verify: required
:uses: RUL-snapshot_optional
:refines: INV-authored_values_checked

The settings a snapshot's name is made from SHALL be checked to make a valid snapshot name before any snapshot is
attempted.
:::

:::{rul} The managed folders' names are checked
:id: RUL-checked_folder_names
:status: ruled
:criticality: med
:verify: required
:uses: RUL-folder_names_not_roles
:refines: INV-authored_values_checked

The managed folders' names SHALL each be one part of a path, not hidden, all different, and none the name of the control
records' place or of the quarantine.
:::

:::{rul} The extension lists are checked
:id: RUL-checked_extension_lists
:status: ruled
:criticality: med
:verify: required
:uses: RUL-config_lists_extensions
:refines: INV-authored_values_checked

Each class's list of extensions SHALL be non-empty, and each extension in it lowercase, without its dot, and holding no
separator or space.
:::

:::{rul} A timezone is a real zone
:id: RUL-checked_timezones
:status: ruled
:criticality: med
:verify: required
:refines: INV-authored_values_checked

A timezone the user writes SHALL be a real zone that resolves, never an arbitrary string.
:::

:::{rul} A position is well formed
:id: RUL-checked_positions_and_times
:status: ruled
:criticality: high
:verify: required
:uses: DEF-decision
:refines: INV-authored_values_checked

A position the user writes SHALL be well formed: two numbers — latitude −90 to 90, longitude −180 to 180, both or
neither.
:::

:::{rul} A clock offset is a whole number of seconds
:id: RUL-checked_clock_offsets
:status: ruled
:criticality: high
:verify: required
:refines: INV-authored_values_checked
:uses: DEF-decision

A clock offset the user writes SHALL be well formed: a whole number of seconds, of any size.
:::

:::{rul} The filename format makes a safe name
:id: RUL-checked_filename_format
:status: ruled
:criticality: med
:verify: required
:uses: RUL-one_filename_format
:refines: INV-authored_values_checked

The filename format SHALL make a part of a name that is never empty and is safe on the filesystem: no path separator
and no character a filename may not hold.
:::

:::{rul} The filename format reads no timezone
:id: RUL-filename_format_zone_free
:status: ruled
:criticality: med
:anti: yes
:verify: required
:uses: RUL-one_filename_format
:refines: RUL-checked_filename_format

The filename format SHALL hold no field that reads a time differently with a timezone than without one.
:::

:::{rul} A number is of the right kind and in range
:id: RUL-checked_numbers
:status: ruled
:criticality: med
:verify: required
:uses: DEF-configuration
:refines: INV-authored_values_checked

A number the configuration sets — a threshold, a distance, a duration — SHALL be of the right kind and within
a sane range: a duration or a distance is never negative.
:::

:::{rul} The drift check's window is more than nothing
:id: RUL-drift_window_positive
:status: ruled
:criticality: med
:verify: required
:uses: DEF-configuration
:refines: RUL-checked_numbers

The span of track the drift check looks at SHALL be set greater than zero, a setting of zero being one that switches
the check off without saying so.
:::

:::{rul} A yes-or-no is a yes or a no
:id: RUL-checked_shapes
:status: ruled
:criticality: high
:anti: yes
:verify: required
:uses: DEF-decision, RUL-user_writes_decisions
:refines: INV-authored_values_checked

A yes-or-no SHALL be a yes or a no.
:::

:::{rul} A value from a fixed set is one of that set
:id: RUL-checked_fixed_set
:status: ruled
:criticality: high
:verify: required
:refines: INV-authored_values_checked
:uses: DEF-decision, RUL-user_writes_decisions, DEF-camera_group

A value from a fixed set — a camera group's class among them — SHALL be one of that set.
:::

:::{rul} A decision has its shape
:id: RUL-checked_decision_structure
:status: ruled
:criticality: high
:anti: yes
:verify: required
:refines: INV-authored_values_checked
:uses: DEF-decision, RUL-user_writes_decisions

A decision's structure SHALL be whole: a decision whose structure is broken is an error, never ignored.
:::

:::{rul} A decision holds only its own fields
:id: RUL-unknown_decision_field_refused
:status: ruled
:criticality: med
:anti: yes
:verify: required
:refines: RUL-checked_decision_structure
:uses: DEF-decision

A field written into a decision that the decision does not have SHALL be an error, naming the field.
:::

:::{rul} An invalid value stops the phase before it changes anything
:id: RUL-invalid_value_stops
:status: ruled
:criticality: high
:anti: yes
:verify: required
:uses: INV-no_stale_use
:refines: INV-authored_values_checked

A value found invalid SHALL stop the phase as a stale dependency does, nothing made from it and nothing changed.
:::

:::{rul} An invalid value is named where it was written
:id: RUL-invalid_value_located
:status: ruled
:criticality: med
:anti: yes
:verify: required
:refines: INV-authored_values_checked
:uses: DEF-authored_value

The report of an invalid value SHALL name the record and the field it was written in — for a decision, also the
destination, the camera group or the file it is about.
:::

:::{rul} An invalid value is never repaired
:id: RUL-invalid_value_never_repaired
:status: ruled
:criticality: high
:anti: yes
:verify: required
:refines: INV-authored_values_checked

A value SHALL be used as written or not at all: never repaired.
:::

:::{rul} A value is checked each time it is used
:id: RUL-checked_every_run
:status: ruled
:criticality: med
:anti: yes
:verify: required
:refines: INV-authored_values_checked

A value SHALL be checked every time a run uses it, never taken as valid because an earlier run found it so.
:::

:::{rul} An invalid decision is kept as written
:id: RUL-invalid_decision_kept
:status: ruled
:criticality: med
:anti: yes
:verify: required
:refines: INV-authored_values_checked
:uses: DEF-decision, RUL-decision_kept

A decision found invalid SHALL be kept exactly as the user wrote it — never erased or rewritten.
:::

:::{rul} An invalid decision is reported as needing correction
:id: RUL-invalid_decision_reported
:status: ruled
:criticality: med
:verify: required
:refines: RUL-invalid_decision_kept
:uses: DEF-decision, RUL-decision_kept

A decision found invalid SHALL be reported as needing correction.
:::

## 15. Nothing overwritten, nothing left half-done

:::{rul} Every name is checked free as it is written
:id: RUL-target_free_at_execute
:status: ruled
:criticality: high
:anti: yes
:verify: required
:uses: RUL-suffix_no_clobber, DEF-library

Immediately before each change that gives a file a name — prep's moves, renames and setting duplicates aside, geotag's
renames, merge's placing in the library — execution SHALL check that the name is free, never writing onto a taken name
on the strength of the plan: a name found taken blocks that operation.
:::

:::{rul} A name is checked free ignoring case
:id: RUL-target_free_ignores_case
:status: ruled
:criticality: high
:verify: required
:refines: RUL-target_free_at_execute
:uses: RUL-suffix_no_clobber, DEF-library

Execution's check that a name is free SHALL ignore case where the filesystem does.
:::

:::{rul} An interrupted move leaves the before or the after
:id: RUL-operations_atomic
:status: ruled
:criticality: high
:anti: yes
:verify: required

A move, a rename or a placement SHALL be one indivisible operation where the filesystem allows, so that an interruption
leaves the state before it or the state after, never part of either.
:::

:::{rul} A move that cannot be one operation is never lost
:id: RUL-split_move_never_lost
:status: ruled
:criticality: high
:anti: yes
:verify: required
:refines: RUL-operations_atomic
:excepts: RUL-failed_operation_clean

Where a move cannot be one operation, an interruption, or a failure partway, SHALL leave the file whole under its old
name, its new name or both — never under neither, never part of one.
:::

:::{rul} A file rewritten in place is the old one or the new one
:id: RUL-rewrite_in_place_atomic
:status: ruled
:criticality: high
:anti: yes
:verify: required

A write that rewrites a file in place SHALL leave, if interrupted — the run stopped or killed, or the power lost — the
intact original or the fully written file, never a damaged one between them.
:::

:::{rul} Across filesystems, a placement is still all or nothing
:id: RUL-cross_fs_all_or_nothing
:status: ruled
:criticality: high
:anti: yes
:verify: required
:refines: RUL-operations_atomic

Where merge's placement into the library crosses filesystems and cannot be one operation, it SHALL be made all or
nothing: an interruption leaves no file under that name, or the complete one, never part of one.
:::

:::{rul} A temporary copy a crash left is cleared
:id: RUL-crash_temps_cleared
:status: ruled
:criticality: low
:verify: required
:uses: DEF-merge, DEF-library, RUL-temp_name_own
:refines: RUL-cross_fs_all_or_nothing

Merge SHALL clear, as its execution starts, the temporary copies an interrupted merge left in the folders it places
into.
:::

:::{rul} The temporary copies cleared are counted
:id: RUL-crash_temps_counted
:status: ruled
:criticality: low
:verify: required
:refines: RUL-crash_temps_cleared
:uses: DEF-merge, DEF-library, RUL-temp_name_own

Merge SHALL record how many temporary copies it cleared.
:::

:::{rul} A temporary copy bears a name no photo bears
:id: RUL-temp_name_own
:status: ruled
:criticality: low
:verify: required
:refines: RUL-cross_fs_all_or_nothing

A temporary copy SHALL bear a name of its own, which no photo bears.
:::

:::{rul} A failed operation leaves its file as it was
:id: RUL-failed_operation_clean
:status: ruled
:criticality: high
:anti: yes
:verify: required

An operation that cannot complete SHALL leave its file as it was before it.
:::

:::{rul} A failed operation's failure is recorded
:id: RUL-failure_recorded
:status: ruled
:criticality: high
:verify: required
:refines: RUL-failed_operation_clean

The failure of an operation that cannot complete SHALL be recorded.
:::

:::{rul} A failed operation is never recorded as done
:id: RUL-failure_never_done
:status: ruled
:criticality: high
:anti: yes
:verify: required
:refines: RUL-failed_operation_clean

An operation that cannot complete SHALL never be recorded as done, so that a re-run does it again.
:::

## 16. Nothing changed outside a validated plan

:::{rul} Planning changes no media
:id: RUL-planning_changes_no_media
:status: ruled
:criticality: high
:anti: yes
:verify: required

Planning SHALL change no media file.
:::

:::{rul} Planning writes only its own records
:id: RUL-planning_writes_only_its_records
:status: ruled
:criticality: high
:verify: required
:refines: RUL-planning_changes_no_media

Planning SHALL write nothing but its plan, its decision records, what it keeps so that later runs need not compute it
again, the changes to the workspace the user accepts ({need}`RUL-acceptance_recorded`), the user's answer to whether to
download the table of countries with the table downloaded ({need}`RUL-zone_table_asked_once`), and — on a workspace's
first run — the configuration it seeds; a prep execution that geotag's plan runs
({need}`RUL-auto_reprep_moves_no_media`) being prep's execution, not planning.
:::

:::{rul} Execution carries out the plan, and only the plan
:id: RUL-execution_only_the_plan
:status: ruled
:criticality: high
:anti: yes
:verify: required
:upholds: INV-every_change_from_the_record

Execution SHALL carry out only the operations its plan records, re-deriving no decision.
:::

:::{rul} The job count changes nothing an execution does
:id: RUL-execution_jobs_change_nothing
:status: ruled
:criticality: high
:anti: yes
:verify: required
:refines: RUL-execution_only_the_plan

An execution SHALL change the same files in the same way, and record the same, whatever number of jobs it runs with —
the job count and the run's times in its run metadata the only difference.
:::

:::{rul} A plan is carried out only by the code that made it
:id: RUL-plan_carried_out_by_its_code
:status: ruled
:criticality: high
:verify: required
:refines: INV-no_stale_use

Each phase SHALL carry out or summarise a saved plan only with the code that made it, refusing before any change a plan
made by other code or recording none.
:::

:::{rul} Every change is journaled
:id: RUL-every_change_journaled
:status: ruled
:criticality: med
:verify: required

Every change an execution makes to a media file SHALL be recorded in that run's journal.
:::


## 17. The workspace as the last execution left it

:::{rul} Every run first checks the workspace is as the last execution left it
:id: RUL-workspace_checked_first
:status: ruled
:criticality: high
:verify: required

Every plan, dry run, execution and finalize of every phase SHALL, once its shape is checked and before it plans,
validates or changes anything, compare the workspace's files with the state the last execution left them in, by their
file system entries alone, reading no media file.
:::

:::{rul} The comparison covers the media folders and the quarantine
:id: RUL-check_covers_media_folders
:status: ruled
:criticality: high
:verify: required
:refines: RUL-workspace_checked_first

The comparison SHALL cover every file of the managed folders but the inbox, and of the quarantine — never the inbox,
which is the user's to fill, nor the control records, which keep checks of their own.
:::

:::{rul} A file is told moved, changed or gone by its entry
:id: RUL-change_told_by_entries
:status: ruled
:criticality: high
:verify: required
:refines: RUL-workspace_checked_first

The comparison SHALL take a file at a new path with the size, modification time and file identity a recorded file had
for that file moved, a file at a recorded path whose size or modification time is not the recorded one for that file
changed in place, a recorded file found nowhere for one deleted, and any other file for one that appeared.
:::

:::{rul} Sorting passes
:id: RUL-sorting_passes
:status: ruled
:criticality: high
:verify: required
:refines: RUL-workspace_checked_first

A photo moved from photos by date into photos by destination, or moved within photos by destination — its folder
renamed among them — SHALL pass the comparison.
:::

:::{rul} Culling passes
:id: RUL-culling_passes
:status: ruled
:criticality: med
:verify: required
:refines: RUL-workspace_checked_first

A file deleted by hand from photos by date, photos by destination, videos by date or the redundant JPEGs SHALL pass the
comparison.
:::

:::{rul} A photo moved back passes
:id: RUL-moved_back_passes
:status: ruled
:criticality: med
:verify: required
:refines: RUL-workspace_checked_first

A photo moved back from photos by destination into photos by date SHALL pass the comparison.
:::

:::{rul} A time given by hand in missing metadata passes
:id: RUL-hand_time_passes
:status: ruled
:criticality: med
:verify: required
:refines: RUL-workspace_checked_first

Any file in missing metadata changed in place SHALL pass the comparison, taken for a time given by hand.
:::

:::{rul} A copy of a file is that file
:id: RUL-copy_passes
:status: ruled
:criticality: med
:verify: required
:refines: RUL-change_told_by_entries

A file of a recorded file's size and modification time under a new file identity — at that file's path, or at one a
move of it would pass to under its name — SHALL pass the comparison as that file.
:::

:::{rul} What passes, but sorting, is named in the run's account
:id: RUL-allowed_changes_named
:status: ruled
:criticality: med
:verify: required
:refines: RUL-workspace_checked_first

Each change the comparison passes, sorting aside, SHALL be named in the run's own account — the record
an execution writes, or what a plan, a dry run or a finalize prints.
:::

:::{rul} Anything else stops the command, naming each file
:id: RUL-unexpected_change_stops
:status: ruled
:criticality: high
:anti: yes
:verify: required
:refines: RUL-workspace_checked_first

Any other difference from the state the last execution left — a file changed in place or replaced, one appearing
outside the inbox, one gone from missing metadata, anything in the strays or the quarantine changed, a file moved where
no sorting goes — SHALL stop the command before it plans, validates or changes anything, naming each file.
:::

:::{rul} A prune's removals are no change to the comparison
:id: RUL-quarantine_changed_only_by_prune
:status: ruled
:criticality: med
:verify: required
:excepts: RUL-unexpected_change_stops

What a prune removes from the quarantine SHALL be no difference to the next comparison.
:::

:::{rul} Every execution records the state it leaves
:id: RUL-execution_records_state
:status: ruled
:criticality: high
:verify: required
:refines: RUL-workspace_checked_first

Every execution — prep's, geotag's and merge's alike — SHALL record, at its end, the state it leaves the workspace's
files in, whether or not each of its operations succeeded.
:::

:::{rul} Planning leaves the recorded state as it was
:id: RUL-planning_leaves_record
:status: ruled
:criticality: high
:anti: yes
:verify: required
:refines: RUL-execution_records_state

No plan, dry run or finalize SHALL change the recorded state of the workspace's files — a prep execution that
geotag's plan runs ({need}`RUL-auto_reprep_moves_no_media`) being prep's execution, not planning.
:::

:::{rul} An interrupted execution's own work passes
:id: RUL-interrupted_work_passes
:status: ruled
:criticality: high
:verify: required
:refines: RUL-workspace_checked_first

A change made by an execution that ended before it recorded the state it left — a file where and as that run's plan
or journal says an operation of it leaves the file — SHALL pass the comparison as that run's work.
:::

:::{rul} Only what the interrupted run's records say passes as its work
:id: RUL-interrupted_work_exact
:status: ruled
:criticality: high
:anti: yes
:verify: required
:refines: RUL-interrupted_work_passes

No change SHALL pass as an interrupted execution's work unless it is exactly what an operation of that run's plan or
journal leaves: the file at the path the operation takes it to, with the entry the run's records give it there.
:::

:::{rul} Geotag and merge need a recorded state
:id: RUL-record_needed
:status: ruled
:criticality: high
:verify: required
:refines: RUL-workspace_checked_first

Geotag and merge SHALL refuse a workspace whose state no execution has recorded.
:::

:::{rul} Prep with no recorded state compares nothing
:id: RUL-first_prep_compares_nothing
:status: ruled
:criticality: med
:verify: required
:refines: RUL-workspace_checked_first

Where no execution has recorded the workspace's state, prep SHALL compare nothing.
:::

:::{rul} A stop gives the code that accepts its list
:id: RUL-stop_gives_acceptance_code
:status: ruled
:criticality: high
:verify: required
:refines: RUL-unexpected_change_stops

A stop SHALL give, with the changes it lists, a code made from that list that accepts exactly it, once.
:::

:::{rul} A code accepts only the list it was made from
:id: RUL-code_accepts_only_its_list
:status: ruled
:criticality: high
:anti: yes
:verify: required
:refines: RUL-stop_gives_acceptance_code

A code SHALL accept the changes only where the list the command would print is the one the code was made from; any
other, the command stops again, listing them anew.
:::

:::{rul} An acceptance is recorded and kept
:id: RUL-acceptance_recorded
:status: ruled
:criticality: high
:verify: required
:refines: RUL-stop_gives_acceptance_code
:uses: DEF-archival_package

Each acceptance SHALL be kept in a record of the accepted changes that is never written over and goes into the
archival package with the workspace's other records.
:::

:::{rul} An accepted change stops no later comparison
:id: RUL-accepted_change_not_stopped_again
:status: ruled
:criticality: med
:verify: required
:refines: RUL-stop_gives_acceptance_code

A change once accepted SHALL stop no later comparison.
:::

:::{rul} The changes a run accepts are named in its account
:id: RUL-accepted_changes_logged
:status: ruled
:criticality: med
:verify: required
:refines: RUL-allowed_changes_named

The changes a run accepts, and those accepted since the last execution, SHALL be named in the run's own account —
the record an execution writes, or what a plan, a dry run or a finalize prints.
:::

:::{rul} Pruning, the library's setup and the editor do not compare
:id: RUL-maintenance_unchecked
:status: ruled
:criticality: low
:verify: required
:refines: RUL-workspace_checked_first

Pruning the quarantine, setting up the library and editing the decisions SHALL run without the comparison.
:::

## 18. The workspace's filesystem

:::{def} What cartographer requires of a filesystem
:id: DEF-filesystem_requirements
:status: ruled
:uses: DEF-workspace, DEF-library

What cartographer **requires of a filesystem** is what POSIX filesystems share: file locks, a rename that is atomic,
a move that fails where its target exists, and syncing a file and a folder to disk — of the library's, all but the
atomic rename.
:::

:::{rul} Only the snapshot uses a feature of one particular filesystem
:id: RUL-filesystem_agnostic
:status: ruled
:criticality: med
:verify: required

Nothing in cartographer but the snapshot SHALL use a feature particular to one filesystem.
:::

:::{rul} A workspace lies on a local filesystem
:id: RUL-workspace_local_filesystem
:status: ruled
:criticality: high
:anti: yes
:verify: required
:uses: DEF-workspace

A workspace SHALL lie on a local filesystem — on the machine's own disks or in its memory, never on one reached over a
network — whatever its configuration says.
:::

:::{rul} The workspace's filesystem is checked to be local before anything changes
:id: RUL-local_filesystem_checked_first
:status: ruled
:criticality: high
:anti: yes
:verify: required
:refines: RUL-workspace_local_filesystem

Every run of every phase on a workspace, and every save of the decision editor, SHALL check that the workspace lies on
a local filesystem before it changes anything.
:::

:::{rul} A filesystem not known to be local stops the run
:id: RUL-not_local_stops
:status: ruled
:criticality: high
:anti: yes
:verify: required
:refines: RUL-workspace_local_filesystem

A workspace whose filesystem is not known to be local — one of another kind, or on a system whose filesystems cannot
be told — SHALL stop the run with nothing changed.
:::

:::{rul} The stop names the filesystem's type
:id: RUL-not_local_named
:status: ruled
:criticality: med
:verify: required
:refines: RUL-not_local_stops

The report of a workspace not on a local filesystem SHALL name the filesystem's type, where it can be told.
:::

:::{rul} What a filesystem must do is tried at every run's start
:id: RUL-filesystem_requirements_tried
:status: ruled
:criticality: high
:anti: yes
:verify: required
:refines: RUL-filesystem_agnostic
:uses: DEF-filesystem_requirements

Every run of every phase on a workspace, and every save of the decision editor, SHALL try on the workspace's filesystem
each thing {need}`DEF-filesystem_requirements` names, before it changes anything — never taking it as done because an
earlier run found it so.
:::

:::{rul} A filesystem lacking one stops the run
:id: RUL-filesystem_lacking_stops
:status: ruled
:criticality: high
:anti: yes
:verify: required
:refines: RUL-filesystem_requirements_tried

A filesystem found failing at one of them SHALL stop the run with nothing changed.
:::

:::{rul} The stop names what the filesystem lacks
:id: RUL-filesystem_lacking_named
:status: ruled
:criticality: med
:verify: required
:refines: RUL-filesystem_lacking_stops

The report of a filesystem failing at a requirement SHALL name the requirement.
:::

:::{rul} Trying the filesystem leaves nothing behind
:id: RUL-filesystem_trial_leaves_nothing
:status: ruled
:criticality: med
:anti: yes
:verify: required
:refines: RUL-filesystem_requirements_tried

Trying a filesystem's requirements SHALL leave nothing behind of what it made to try them, in the workspace or the
library.
:::

:::{rul} A workspace lies on one filesystem
:id: RUL-workspace_one_filesystem
:status: ruled
:criticality: high
:anti: yes
:verify: required
:uses: DEF-workspace

A workspace SHALL lie on one filesystem, every folder in it — the control records' and the set-aside duplicates'
among them — on the same one.
:::

:::{rul} The workspace's filesystem is checked each run
:id: RUL-one_filesystem_checked_every_run
:status: ruled
:criticality: high
:anti: yes
:verify: required
:refines: RUL-workspace_one_filesystem

Every run of every phase on a workspace SHALL check, before it reads or changes anything but the lock and the seal,
that the workspace lies on one filesystem — never taking it as whole because an earlier run found it so.
:::

:::{rul} A workspace spanning filesystems stops the run
:id: RUL-spanning_workspace_stops
:status: ruled
:criticality: high
:anti: yes
:verify: required
:refines: RUL-workspace_one_filesystem

A workspace found to span filesystems SHALL stop the run with nothing changed.
:::

:::{rul} The stop names a folder that lies elsewhere
:id: RUL-spanning_workspace_located
:status: ruled
:criticality: med
:verify: required
:refines: RUL-spanning_workspace_stops

The report of a workspace spanning filesystems SHALL name a folder in it that lies on another filesystem.
:::

:::{rul} Prep and geotag never move across filesystems
:id: RUL-workspace_moves_one_filesystem
:status: ruled
:criticality: high
:anti: yes
:verify: required
:uses: DEF-prep, DEF-geotag
:refines: RUL-workspace_one_filesystem

A move by prep or geotag that would cross filesystems SHALL fail, never be made a copy.
:::

## 19. The decision editor

:::{rul} One decision editor at a time
:id: RUL-one_editor_at_a_time
:status: ruled
:criticality: med
:anti: yes
:verify: required
:uses: DEF-decision

A workspace SHALL be open in at most one decision editor at a time, another being refused while it is.
:::

:::{rul} An editor keeps the workspace until it stops
:id: RUL-editor_kept_until_stopped
:status: ruled
:criticality: med
:verify: required
:refines: RUL-one_editor_at_a_time

A decision editor SHALL keep a workspace it has opened as its one editor until the editor itself stops, never giving
it up between one save or display and the next.
:::

:::{rul} The editor saves only over what it showed
:id: RUL-save_only_what_was_shown
:status: ruled
:criticality: high
:anti: yes
:verify: required

The decision editor SHALL NOT save while a record it answers into is not the one it loaded, or while an edit names a decision the record does not hold.
:::

:::{rul} A save writes its records in the order they stand on each other
:id: RUL-save_writes_in_order
:status: ruled
:criticality: med
:verify: required
:uses: DEF-decision

The decision editor SHALL write the records a save changes one after another, each whole: the time decisions, the
drift validation, the GPS decisions — each standing on the ones before it — then the execution's summary and the
configuration, which stand on none of them; so that a save cut short leaves only a leading part of it written.
:::

:::{rul} A save keeps the record it replaces
:id: RUL-save_keeps_the_replaced
:status: ruled
:criticality: high
:anti: yes
:verify: required
:uses: DEF-decision

The decision editor's save SHALL NOT overwrite a record it answers into: each one whose content it changes is first set
aside, recoverably, among the earlier versions a re-plan sets aside — the configuration excepted.
:::

:::{rul} Every question can be answered in the decision editor
:id: RUL-every_question_in_editor
:status: ruled
:criticality: med
:verify: required
:uses: DEF-decision

Every question geotag asks of the user SHALL be answerable in the decision editor.
:::

:::{rul} Every question can be answered by hand
:id: RUL-every_question_answerable_by_hand
:status: ruled
:criticality: med
:verify: required
:uses: DEF-decision

Every question geotag asks of the user SHALL be answerable by hand, in a field of the record it is asked in — a camera
group's class, in the configuration.
:::

:::{rul} A timezone answered in the editor ends the asking below it
:id: RUL-editor_answer_ends_zone_asking
:status: ruled
:criticality: med
:verify: required
:refines: RUL-zone_not_asked_where_one_reaches
:uses: DEF-decision

The decision editor SHALL stop asking for a timezone, as soon as one is answered in it, at every destination that
answer reaches and at every container destination asking for no other.
:::

:::{rul} The decision editor records a camera group's class, and nothing else
:id: RUL-editor_classes_camera_group
:status: ruled
:criticality: med
:anti: yes
:verify: required
:refines: RUL-config_writers
:uses: DEF-camera_group, RUL-known_when_classified

The decision editor, given by the user the class of a camera group the configuration does not class — a phone, or a
camera with a fixed clock — SHALL write in the configuration no setting but that class.
:::

:::{rul} The decision editor records whether a camera group is several bodies, and nothing else
:id: RUL-editor_marks_several_bodies
:status: ruled
:criticality: med
:anti: yes
:verify: required
:refines: RUL-config_writers
:uses: DEF-camera_group, RUL-several_bodies_named_by_configuration

The decision editor, told by the user whether a camera group the configuration classes as a camera with a fixed clock
is several bodies, SHALL write in the configuration no setting but that one.
:::
