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

The **library** is the permanent, curated collection the media ends in — outside every workspace, and written only by
merge.
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
offset; places the photos that carry no position along the recorded tracks; and renames each by its corrected local
time.
:::

:::{def} Merge
:id: DEF-merge
:status: ruled
:uses: DEF-geotag, DEF-library

**Merge**, the third phase, runs after a workspace has been geotagged and finalized, and moves its finished photos,
sorted by destination, into the library.
:::

## 1. One run at a time

:::{inv} One run at a time
:id: INV-one_run_at_a_time
:status: ruled
:criticality: high
:anti: yes
:verify: required
:aliases: lock-mutual-exclusion-1

At most one cartographer run SHALL act on a workspace at any time — whatever the commands: two runs of one phase, runs
of two phases, a merge, a finalize, or a quarantine prune.
:::

:::{rul} Every run, and every change, takes the lock
:id: RUL-every_command_locks
:status: ruled
:criticality: med
:verify: incidental
:aliases: lock-every-command-takes-1
:upholds: INV-one_run_at_a_time

Every run, and every change to the workspace, SHALL hold the workspace's lock.
:::

:::{rul} A workspace has one lock
:id: RUL-one_workspace_lock
:status: ruled
:criticality: med
:verify: incidental
:refines: RUL-every_command_locks

A workspace SHALL have exactly one lock, shared by every command.
:::

:::{rul} The lock comes before anything is read
:id: RUL-lock_before_reading
:status: ruled
:criticality: high
:verify: required
:aliases: lock-covers-planning-1
:upholds: INV-one_run_at_a_time

A run SHALL hold the lock before it reads any of the workspace's content — before it plans, scans, fingerprints,
reads metadata, dry-runs or executes. Planning changes nothing but the fingerprints it keeps for later runs, and is
inside the lock all the same.
:::

:::{rul} The lock lasts the whole run, and no longer
:id: RUL-lock_through_the_run
:status: ruled
:criticality: high
:anti: yes
:verify: required
:aliases: lock-covers-whole-run-1
:upholds: INV-one_run_at_a_time

A run SHALL hold the lock until it ends — through planning, dry run, execution, and every record and artifact it writes
— and release it then, never letting it outlive the run: between runs, the workspace is unlocked.
:::

:::{rul} A locked workspace is refused at once
:id: RUL-lock_fail_fast
:status: ruled
:criticality: high
:anti: yes
:verify: required
:aliases: lock-failfast-1
:upholds: INV-one_run_at_a_time

A run that finds the workspace locked SHALL stop at once, never waiting for it, saying the workspace is locked by a run
in progress, having scanned, planned and changed nothing — and having produced no plan, no dry-run report and no
artifact.
:::

:::{rul} The lock is released however the run ends
:id: RUL-lock_released_on_any_end
:status: ruled
:criticality: med
:verify: required
:aliases: lock-release-on-exit-error-1
:refines: RUL-lock_through_the_run

A run SHALL release the lock when it ends, whether it succeeds or fails.
:::

:::{rul} A stale lock is recognised and recovered
:id: RUL-stale_lock_recovered
:status: ruled
:criticality: med
:verify: required
:aliases: lock-stale-detectable-1

A lock left behind by a run that died SHALL be recognisable as stale, and recoverable, so that a crash never leaves a
workspace locked for good.
:::

:::{rul} Only a dead owner's lock is taken over
:id: RUL-stale_takeover_conservative
:status: ruled
:criticality: high
:anti: yes
:verify: none
:omit_reason: no test asserts it (backlog item 3)
:aliases: lock-stale-takeover-conservative-1
:refines: RUL-stale_lock_recovered

A stale lock SHALL be taken over only when its owner is provably gone; a lock whose owner may still be running is left
alone.
:::

Merge also takes a lock on the library it writes into, so that two merges into one library — even from two workspaces
— never overlap; that lock is held besides the workspace's, not instead of it. Its items are with merge's.

## 2. A snapshot before changing, optionally

:::{rul} A snapshot is optional, and nothing rests on it
:id: RUL-snapshot_optional
:status: ruled
:criticality: med
:verify: incidental
:aliases: snapshot-optional-1

A phase that changes files MAY first take a snapshot of what it is about to change, from which the whole change can be
rolled back. Cartographer SHALL be complete and safe without one, no guarantee depending on a snapshot having been
taken.
:::

:::{rul} No snapshot unless configured
:id: RUL-snapshot_off_by_default
:status: ruled
:criticality: med
:verify: required
:aliases: snapshot-disabled-default-1
:refines: RUL-snapshot_optional

Snapshots SHALL be off unless the workspace's configuration turns them on.
:::

:::{rul} Only the snapshot depends on the filesystem
:id: RUL-filesystem_agnostic
:status: ruled
:criticality: med
:verify: none
:omit_reason: a design constraint over the whole code; the gap audit (backlog item 2) checks it

Nothing in cartographer but the snapshot SHALL depend on a particular filesystem's features, so that cartographer runs
fully on a filesystem that has none.
:::

:::{rul} A snapshot names its plan
:id: RUL-snapshot_per_plan
:status: ruled
:criticality: low
:verify: required
:aliases: snapshot-keyed-by-plan-1

Each snapshot SHALL be identifiable by the plan whose changes it precedes.
:::

:::{rul} When a snapshot is taken
:id: RUL-snapshot_timing
:status: ruled
:criticality: med
:verify: required
:aliases: snapshot-timing-1

A snapshot SHALL be taken after the plan has been validated against its dependencies and the lock is held, and before
the plan's first change.
:::

:::{rul} A required snapshot that fails stops the run
:id: RUL-required_snapshot_or_nothing
:status: ruled
:criticality: high
:anti: yes
:verify: required
:aliases: snapshot-required-fatal-1
:refines: RUL-snapshot_timing

When the configuration requires snapshots, a run that cannot take one SHALL stop before it changes anything.
:::

:::{rul} Without a required snapshot, the run goes on
:id: RUL-unrequired_snapshot_proceeds
:status: ruled
:criticality: med
:verify: required
:aliases: snapshot-not-required-proceeds-1
:refines: RUL-snapshot_optional

When snapshots are not required, or not configured, a run SHALL proceed without one. Its safety then rests, as it
always does, on the journal, the recoverable quarantine, never overwriting, and the filesystem as the truth.
:::

:::{rul} Merge snapshots the workspace, and the library beside it
:id: RUL-merge_snapshots_library
:status: ruled
:criticality: high
:verify: required

Merge's snapshot SHALL cover the workspace, and the library too where the library can be snapshotted.
:::

:::{rul} Merge takes no snapshot of the library alone
:id: RUL-no_library_only_snapshot
:status: ruled
:criticality: high
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
:verify: incidental
:aliases: config-single-shared-1

All three phases SHALL read their settings from the workspace's one configuration alone, each the settings it needs — no
phase keeping settings of its own, and no setting that governs a run coming from outside the workspace.
:::

:::{rul} A configuration missing a setting stops the run
:id: RUL-config_complete
:status: ruled
:criticality: high
:anti: yes
:verify: required
:refines: RUL-one_configuration

A configuration that lacks a setting SHALL stop the run, naming the setting — never filled from the program's defaults.
:::

:::{rul} A configuration holding an unknown setting stops the run
:id: RUL-config_no_unknown_settings
:status: ruled
:criticality: med
:anti: yes
:verify: required
:refines: RUL-one_configuration

A configuration holding a setting cartographer does not know SHALL stop the run, naming the setting.
:::

:::{rul} Prep seeds the configuration once
:id: RUL-config_seeded_once
:status: ruled
:criticality: med
:verify: required
:aliases: config-seeded-by-prep-1

A prep run SHALL create the configuration from the seed defaults when it finds none, and only then: a configuration it
finds, it uses as it is.
:::

:::{rul} The workspace's configuration governs it, not the defaults
:id: RUL-config_authoritative
:status: ruled
:criticality: med
:verify: required
:aliases: config-file-authoritative-1
:refines: RUL-config_seeded_once

Once a workspace's configuration exists, it SHALL govern every run in that workspace, whatever the seed defaults later
become — the defaults serving only to seed a new workspace.
:::

:::{rul} Who writes the configuration
:id: RUL-config_writers
:status: ruled
:criticality: high
:anti: yes
:verify: required
:aliases: config-prep-sole-writer-1, config-merge-readonly-1

The configuration SHALL be written only when prep seeds it, when the user edits it by hand, and by the library setup
below — never by geotag, and never by merge's planning, dry run or execution.
:::

:::{rul} The library setup records one setting
:id: RUL-library_setup_writes_one_setting
:status: ruled
:criticality: med
:anti: yes
:verify: required
:aliases: config-initlib-writes-libroot-only-1
:refines: RUL-config_writers

Merge's one-time library setup, run inside a workspace and given a library, MAY record in the configuration which
library this workspace merges into — that setting, and no other.
:::

:::{rul} The configuration is a dependency of what is made under it
:id: RUL-config_in_dependencies
:status: ruled
:criticality: med
:verify: required
:aliases: config-hashed-cascade-1

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

The configuration SHALL be part of the archival record the workspace leaves behind.
:::

:::{rul} The configuration is never media
:id: RUL-config_never_media
:status: ruled
:criticality: med
:anti: yes
:verify: required
:aliases: config-in-control-dir-skipped-1
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
:aliases: config-surgical-staleness-1

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
:aliases: config-edit-outside-timepolicy-1
:refines: RUL-costly_results_survive_unrelated_edits

A configuration change outside the camera-time policy SHALL NOT make stale the true times already resolved.
:::

:::{rul} Any configuration change restales the plan
:id: RUL-any_config_change_replans
:status: ruled
:criticality: med
:verify: required
:aliases: config-wholehash-coarse-replan-1

Any change to the configuration, in whatever area, SHALL make stale every plan made before it — prep's plan, geotag's
executable plan and merge's plan — so that none of them is executed.
:::

:::{rul} A change to the folder names or the media classes restales the plans
:id: RUL-organization_settings_restale
:status: ruled
:criticality: med
:verify: required
:aliases: config-folderset-ext-restale-1
:refines: RUL-staleness_by_area

A change to the managed folders' names, or to which extensions are which class of media, SHALL make stale geotag's
executable plan and merge's plan.
:::

:::{rul} Where the control records live is fixed
:id: RUL-control_directory_fixed
:status: ruled
:criticality: med
:anti: yes
:verify: none
:omit_reason: no test asserts it yet

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
:aliases: config-folder-roles-not-config-1

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
:verify: none
:omit_reason: no test asserts it (backlog item 3)
:aliases: config-camerakey-version-not-config-1

Of camera grouping, the configuration SHALL set only which camera groups are phones and which have fixed clocks — never
how a group is derived, nor the version of that derivation.
:::

:::{rul} Each extension is one class of media
:id: RUL-extension_one_class
:status: ruled
:criticality: med
:verify: required
:aliases: config-ext-one-class-1

An extension SHALL be in exactly one class of media.
:::

:::{rul} The configuration lists the extensions, not the classes
:id: RUL-config_lists_extensions
:status: ruled
:criticality: med
:verify: required
:refines: RUL-extension_one_class

The configuration SHALL list which extensions are images, raw files and videos, never the classes themselves.
:::

:::{rul} An extension not listed is other
:id: RUL-unlisted_extension_other
:status: ruled
:criticality: med
:verify: required
:refines: RUL-extension_one_class

An extension the configuration does not list SHALL be `other`.
:::

:::{rul} Every value the user supplies is checked before use
:id: RUL-config_validated_before_use
:status: ruled
:criticality: med
:verify: required
:aliases: config-values-validated-1
:refines: INV-authored_values_checked

Every value of the configuration that comes from the user SHALL be validated before it is used, as part of reading the
configuration — never as a separate, optional pass.
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
:aliases: ctrl-all-in-photos-ingest-1
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
:aliases: ctrl-prep-skips-wholesale-1
:refines: RUL-control_records_together

The control records' place SHALL be left out of every inventory of media as a whole — not file by file — so that no
phase takes a control record for media.
:::

:::{def} The strays folder
:id: DEF-strays_folder
:status: ruled
:uses: DEF-prep

The **strays folder** is a media-tree folder at the workspace's top level. It holds the files that are not media which
prep moved out of the inbox, one subfolder for each run, their structure kept. It is neither a control record nor any
phase's output.
:::

:::{rul} What prep never inventories
:id: RUL-not_inventoried
:status: ruled
:criticality: med
:verify: incidental
:aliases: ctrl-skip-set-1
:refines: RUL-control_records_never_media
:uses: DEF-strays_folder

Prep SHALL leave out of its inventory of media, each as a whole: the control records' place, the quarantine, a
version-control directory, and the strays folder with everything in it; and every hidden file.
:::

:::{rul} The strays folder's contents are never processed again
:id: RUL-strays_never_processed
:status: ruled
:criticality: med
:verify: incidental
:refines: RUL-not_inventoried

Nothing SHALL process the strays folder's contents again: prep writes into it, but never scans it.
:::

:::{rul} Hidden files in a dump are quarantined
:id: RUL-dump_hidden_files_quarantined
:status: ruled
:criticality: med
:verify: required
:aliases: ctrl-dotfiles-swept-quarantine-1

Hidden files that arrive in a dump area — the workspace's top level on the run that initializes it, or the inbox — SHALL
be moved to the recoverable quarantine, not merely left out.
:::

:::{rul} Each plan has one fixed place
:id: RUL-plan_at_fixed_place
:status: ruled
:criticality: med
:verify: required
:aliases: plan-canonical-path-1

Each phase's plan, and each of its decision records, SHALL have one fixed place among the control records, where the
phase's planning writes it and its dry run and its execution read it.
:::

:::{rul} No command is told where a plan is
:id: RUL-no_plan_location_option
:status: ruled
:criticality: med
:anti: yes
:verify: required
:aliases: plan-no-path-flag-1
:refines: RUL-plan_at_fixed_place

No command SHALL take an option saying where to put a plan or where to find one; the fixed place is the contract.
:::

:::{rul} No plan, no dry run and no execution
:id: RUL-no_plan_no_run
:status: ruled
:criticality: med
:anti: yes
:verify: required
:aliases: plan-missing-stops-1

A dry run or an execution that finds no plan in its place SHALL stop, and tell the user to plan first.
:::

:::{rul} A dry run summarises the real plan
:id: RUL-dry_run_summarises_the_real_plan
:status: ruled
:criticality: med
:anti: yes
:verify: required
:aliases: dryrun-summary-not-dump-1

A dry run SHALL validate the saved plan that execution would carry out, and report on that plan — never on a separate
simulation.
:::

:::{rul} Re-planning sets the prior plan aside
:id: RUL-replanning_keeps_the_prior
:status: ruled
:criticality: high
:anti: yes
:verify: required
:aliases: plan-replan-no-clobber-1

Re-planning SHALL never overwrite a plan or a decision record: when what it makes differs from what is saved, the saved
one is first set aside, recoverably, and the user told where.
:::

:::{rul} An unchanged re-plan writes nothing
:id: RUL-unchanged_replan_writes_nothing
:status: ruled
:criticality: med
:verify: required
:aliases: plan-unchanged-no-backup-1
:refines: RUL-replanning_keeps_the_prior

A re-plan whose result is identical to what is saved SHALL write nothing and set nothing aside.
:::

:::{rul} Geotag verifies the handoff by its content
:id: RUL-handoff_verified_by_content
:status: ruled
:criticality: med
:verify: required
:aliases: handoff-verified-by-content-1
:refines: RUL-hash_detects_any_change

Geotag SHALL verify prep's handoff before using it by the fingerprint of its content — recomputed, and compared with
the one its dependencies recorded — never by the file's exact bytes.
:::

:::{rul} Refreshing what describes the run restales nothing
:id: RUL-run_only_refresh_restales_nothing
:status: ruled
:criticality: med
:anti: yes
:verify: required
:aliases: handoff-runonly-refresh-no-restale-1, dep-handoff-dual-key-1
:refines: RUL-handoff_verified_by_content

A rewrite of the handoff that changes only what describes the run, not its content, SHALL NOT make anything downstream
stale.
:::

:::{inv} A disturbed workspace is never processed silently
:id: INV-undisturbed_shape
:status: ruled
:criticality: high
:anti: yes
:verify: incidental

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

Prep SHALL create the full structure of managed folders exactly once, when it initializes the workspace, and never
remove one.
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
:aliases: struct-base-folders-only-1
:upholds: INV-undisturbed_shape

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
:aliases: struct-uninit-exception-1
:refines: RUL-top_level_only_managed

On a workspace not yet initialized, the files and folders at the top level SHALL be the first dump, and start
initialization — a symbolic link there still blocking, as everywhere.
:::

:::{rul} No symbolic link is followed, and any link blocks
:id: RUL-no_links
:status: ruled
:criticality: high
:anti: yes
:verify: required
:aliases: struct-symlinks-barred-1
:upholds: INV-undisturbed_shape

A symbolic link anywhere among the managed files SHALL block, never followed, organized or skipped silently: a link to a
file anywhere; a link to a folder inside a dump or a managed folder, whose mere presence blocks though it is never
entered; a managed folder that is itself a link, before it is walked; a link at the top level.
:::

:::{rul} A blocking link is named, and nothing is made after it
:id: RUL-link_named
:status: ruled
:criticality: med
:verify: required
:refines: RUL-no_links

A phase a link blocks SHALL name the link, and produce no executable plan and no artifact after it.
:::

:::{rul} Prep checks the whole tree for links
:id: RUL-who_checks_for_links
:status: ruled
:criticality: med
:verify: required
:refines: RUL-no_links

Prep SHALL check for links across the whole tree it walks, the destination tree included though prep never changes it.
:::

:::{rul} Geotag and merge check the top level for links
:id: RUL-geotag_merge_check_top_level_links
:status: ruled
:criticality: med
:verify: required
:refines: RUL-who_checks_for_links

Geotag and merge SHALL check the top level for links themselves, and consume only a handoff prep built with no link
present.
:::

:::{rul} A missing managed folder blocks, and is never rebuilt
:id: RUL-missing_folder_blocks
:status: ruled
:criticality: high
:anti: yes
:verify: required
:aliases: struct-no-silent-rebuild-1
:upholds: INV-undisturbed_shape

On an initialized workspace, a missing managed folder SHALL block every phase, never recreated outside initialization:
no phase organizes media into a structure it had to rebuild.
:::

:::{rul} The block names the missing folders
:id: RUL-missing_folder_named
:status: ruled
:criticality: med
:verify: required
:refines: RUL-missing_folder_blocks

The block of a missing managed folder SHALL name the missing folders, say that something is wrong, and tell the user to
restore them and run again; an empty folder restores one.
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
:verify: incidental
:aliases: struct-guards-at-startup-1
:upholds: INV-undisturbed_shape

Each phase SHALL check the workspace's shape at its start — right after the lock and the seal check, before it scans,
plans or changes anything.
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
:aliases: camera-prep-computes-key-1
:uses: DEF-camera_group

Prep SHALL derive each file's camera group from its device-identity metadata, and record it both in what it hands
geotag and in its own records.
:::

:::{rul} Geotag reuses prep's camera group
:id: RUL-geotag_reuses_camera_group
:status: ruled
:criticality: med
:anti: yes
:verify: required
:aliases: camera-geotag-reuses-1
:refines: RUL-prep_derives_camera_group

Geotag SHALL use the camera group prep derived, never deriving a file's identity again.
:::

:::{rul} The derivation carries a version
:id: RUL-camera_group_derivation_versioned
:status: ruled
:criticality: med
:anti: yes
:verify: required
:aliases: camera-version-detectable-1
:refines: RUL-prep_derives_camera_group

How camera groups are derived SHALL carry a version taking part in the checks of freshness and of dependencies, so that
a change to the derivation is detected and old and new groups are never silently mixed.
:::

:::{rul} A camera group is known once it is classified
:id: RUL-known_when_classified
:status: ruled
:criticality: low
:verify: required
:aliases: camera-known-when-classified-1
:uses: RUL-camera_classes_not_derivation

A camera group SHALL be known when the configuration classes it as a phone or as a camera with a fixed clock, and
unknown otherwise.
:::

## 6. One filename format

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
:verify: incidental
:aliases: fname-single-shared-key-1
:uses: DEF-timestamp_name

Prep and geotag SHALL name files from a timestamp in one format for the whole pipeline, not one for each phase, set by
the configuration and hard-coded by neither.
:::

:::{rul} A taken name gets a suffix, never clobbering
:id: RUL-suffix_no_clobber
:status: ruled
:criticality: high
:anti: yes
:verify: required
:aliases: fname-suffix-noclobber-1

A file whose timestamp name is already taken SHALL get a zero-padded differentiating suffix, allocated deterministically
and without clobbering: against every name on disk and every name planned in the run, compared without regard to case,
so that two files never collide.
:::

:::{rul} Prep and geotag take the first free name
:id: RUL-suffix_choice_by_phase
:status: ruled
:criticality: med
:verify: required
:aliases: fname-allocation-per-phase-1
:refines: RUL-suffix_no_clobber

Prep and geotag SHALL take the first free name — the name with no suffix when it is free, otherwise the lowest free
suffix — by one identical rule.
:::

:::{rul} Merge takes the suffix above the highest used
:id: RUL-merge_suffix_above_highest
:status: ruled
:criticality: med
:verify: required
:refines: RUL-suffix_choice_by_phase

Merge SHALL take the suffix above the highest already used for a name, never a lower one that has come free.
:::

:::{rul} Prep's name is provisional
:id: RUL-prep_name_provisional
:status: ruled
:criticality: med
:verify: incidental
:aliases: fname-prep-provisional-1

Prep SHALL derive a file's name from its raw timestamp, as the camera recorded it, for organizing and ordering only — a
provisional name, which prep never corrects, resolves to a timezone or converts to UTC.
:::

:::{rul} Geotag's name is final
:id: RUL-geotag_name_final
:status: ruled
:criticality: med
:verify: required
:aliases: fname-geotag-final-1

Geotag SHALL recompute a file's name from its corrected local time at the destination — its resolved true time, in the
destination's civil timezone — and rename it to that final name.
:::

:::{rul} An uncorrected file keeps its name
:id: RUL-uncorrected_keeps_its_name
:status: ruled
:criticality: med
:verify: required
:aliases: fname-uncorrected-no-rename-1
:uses: RUL-prep_name_provisional, RUL-geotag_name_final

A file's name SHALL change between prep and geotag only when its timestamp is corrected: geotag plans no rename for a
file whose time is not corrected.
:::

:::{def} An untimed name
:id: DEF-untimed_name
:status: ruled
:uses: DEF-prep

A file's **untimed name** is the name prep gives a media file with no recorded time: the name it came with, behind a
mark that says so.
:::

:::{rul} A misnamed file outside the inbox stops prep
:id: RUL-misnamed_file_stops_prep
:status: ruled
:criticality: high
:verify: required
:aliases: fname-nonconforming-redumped-1
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

Prep SHALL name every misnamed file it finds, with the name the file should carry.
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
:uses: DEF-timestamp_name

A JPG prep sets aside as redundant to its RAW SHALL get its timestamp name, as a dated file does.
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
:aliases: gpx-prep-unaware-1
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
:aliases: gpx-root-outside-tree-1, gpx-prep-defensive-skip-1
:uses: DEF-tracks
:refines: RUL-config_validated_before_use

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
:uses: DEF-tracks, DEF-strays_folder

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

Prep SHALL leave a track file where it is: never moving it, to the strays folder or anywhere else, and never treating it
as a file of no media class.
:::

:::{rul} The tracks are a dependency of what geotag derives from them
:id: RUL-tracks_in_dependencies
:status: ruled
:criticality: med
:verify: required
:aliases: gpx-geotag-fingerprint-cascade-1
:uses: DEF-tracks, DEF-dependency_cascade

Geotag SHALL record the tracks' fingerprint as a dependency of every record it derives with them — the time decisions,
the drift validation, the GPS decisions and the executable plan — so that a change to the tracks makes those records
stale.
:::

## 8. Nothing used once what it came from has changed

:::{def} A fingerprint
:id: DEF-fingerprint
:status: ruled

A media file's **fingerprint** is the identity of its decoded content — a photo's pixels, a video's streams. Unqualified,
*fingerprint* means this.
:::

:::{def} A hash
:id: DEF-hash
:status: ruled

A record's **hash** is a digest of its exact bytes — of a numbered record, or of the configuration. Unqualified, *hash*
means this.
:::

:::{def} The dependency cascade
:id: DEF-dependency_cascade
:status: ruled
:uses: DEF-fingerprint, DEF-hash, DEF-config_areas

The **dependency cascade** is how the phases keep a record from being used once what it was made from has changed: each
record carries what it depends on — media by their fingerprints, other records by their hashes, and settings by a hash
of the configuration or of the areas the record reads — and each use checks them first. Its full name, the
*dependency-fingerprint/hash cascade*, says that it tracks both kinds of identity.
:::

:::{inv} No record is used once what it came from has changed
:id: INV-no_stale_use
:status: ruled
:criticality: high
:anti: yes
:verify: required
:aliases: dep-cascade-reject-stale-1
:uses: DEF-dependency_cascade

No phase SHALL use a record once anything it was derived from has changed: each phase validates what it derives from,
then creates the record, records those dependencies in it, and refuses its use downstream when any of them has changed.
:::

:::{rul} A fingerprint survives what the pipeline does to a file
:id: RUL-fingerprint_survives_mutation
:status: ruled
:criticality: med
:verify: required
:aliases: dep-fingerprint-invariant-1
:uses: DEF-fingerprint

A media file's fingerprint SHALL stay the same when the pipeline rewrites its metadata or its position, or renames it.
:::

:::{rul} A hash changes with any byte
:id: RUL-hash_detects_any_change
:status: ruled
:criticality: med
:verify: required
:aliases: dep-hash-sensitive-1
:uses: DEF-hash

A record's hash SHALL change on any change to its bytes.
:::

:::{rul} A record is checked as a dependency by its hash
:id: RUL-hash_is_the_dependency_check
:status: ruled
:criticality: high
:verify: required
:refines: RUL-hash_detects_any_change

A record SHALL be checked as a dependency by its hash — prep's handoff excepted, which is checked by its content.
:::

## 9. One loop across the phases

:::{def} The managed folders
:id: DEF-managed_folders
:status: ruled
:uses: DEF-workspace, DEF-strays_folder

The **managed folders** are the workspace's media folders, each with a fixed role: the **inbox**, where a dump arrives;
the strays folder; **missing metadata**, for media with no capture time; **redundant JPEGs**; **videos by date**;
**photos by date**; and **photos by destination**, the staging the user sorts photos into and merge empties into the
library.
:::

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
subfolders of a destination.
:::

:::{rul} Prep leaves the inbox empty
:id: RUL-prep_empties_inbox
:status: ruled
:criticality: med
:verify: required
:uses: DEF-managed_folders

A prep execution SHALL leave the inbox empty.
:::

:::{rul} Only photos are sorted into photos by destination
:id: RUL-sort_photos_only
:status: ruled
:criticality: med
:anti: yes
:verify: required
:aliases: loop-sort-photo-only-1
:uses: DEF-operator_loop, DEF-managed_folders

Photos by destination SHALL hold only photos — videos stay in videos by date, and no file of no media class belongs
there — geotag refusing to run while it holds anything else.
:::

:::{rul} Geotag does not plan over an unrecorded sort
:id: RUL-prep_records_sort
:status: ruled
:criticality: high
:anti: yes
:verify: required
:aliases: loop-no-behind-preps-back-1
:uses: DEF-operator_loop, DEF-prep, DEF-geotag

Geotag SHALL NOT plan while photos by destination holds a photo prep has not recorded where it now is.
:::

:::{rul} Prep records a sort from sizes and times alone
:id: RUL-sort_recorded_by_stat
:status: ruled
:criticality: med
:verify: required
:aliases: loop-reprep-mandatory-1
:refines: RUL-prep_records_sort

A prep run after the latest sort SHALL record the moves from the files' sizes and modification times alone, carrying
each moved file's identity forward without reading it again.
:::

:::{rul} Geotag may be re-run until merge
:id: RUL-geotag_rerunnable
:status: ruled
:criticality: med
:verify: required
:aliases: loop-geotag-rerunnable-1
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
:aliases: loop-geotag-rerun-safe-1
:refines: RUL-geotag_rerunnable
:uses: RUL-decision_kept, RUL-mutate_on_difference

A geotag re-run SHALL recognise in each file what an earlier run wrote there — never correcting again a time geotag
corrected, and deriving again and replacing a position geotag wrote, never keeping it as the file's own. The user's
decisions, and files already right, it keeps as every run does.
:::

:::{rul} Geotag's gates are the present state, not its history
:id: RUL-geotag_gates
:status: ruled
:criticality: high
:anti: yes
:verify: required
:aliases: loop-geotag-gating-preconditions-1
:uses: DEF-geotag, DEF-managed_folders

Geotag SHALL proceed when, and only when, the workspace now satisfies its gates: photos by date holds no photo; photos
by destination holds only photos and no development subfolder; prep has recorded every photo in it; and the inbox is
empty — whether, or how often, prep, the sort or geotag ran before not bearing on it, so the user may run any number of
prep and sort cycles before geotagging.
:::

:::{rul} A re-run does as much as what changed requires
:id: RUL-rerun_does_what_changed
:status: ruled
:criticality: low
:verify: required
:aliases: loop-rerun-may-need-decisions-1
:uses: DEF-dependency_cascade
:refines: RUL-geotag_rerunnable

A re-run SHALL redo exactly the work its changed inputs require — new media, an edited setting, changed tracks, a
withdrawn or altered decision, a refreshed handoff — and no more. It MAY ask for new decisions, but only for the items
the change affects.
:::

:::{rul} More dumps may follow until merge
:id: RUL-more_dumps_until_merge
:status: ruled
:criticality: med
:verify: required
:uses: DEF-operator_loop, DEF-merge

A new dump SHALL be accepted into the inbox at any point before merge, after a successful geotag too; the loop then
resumes from prep.
:::

:::{rul} Finalize is its own command
:id: RUL-finalize_explicit
:status: ruled
:criticality: med
:anti: yes
:verify: required
:aliases: archive-finalize-explicit-1
:uses: DEF-finalize, DEF-merge

Finalize SHALL be a command of its own, never a side effect of geotag's execution.
:::

:::{rul} Merge requires a finalized workspace
:id: RUL-merge_takes_finalized_current
:status: ruled
:criticality: high
:anti: yes
:verify: required
:aliases: merge-preconditions-finalized-1, loop-finalize-before-merge-1
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
:aliases: merge-revalidates-current-1
:refines: RUL-merge_takes_finalized_current

Merge SHALL refuse when photos by destination has changed since finalize — a refresh that changes only what describes a
prep run not counting as a change — so that what reaches the library is always the corrected, named, fully recorded set.
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
:refines: RUL-merge_is_terminal

The library SHALL accept merges from many workspaces.
:::

:::{rul} Development happens in the library, after merge
:id: RUL-development_after_merge
:status: ruled
:criticality: high
:anti: yes
:verify: required
:aliases: loop-dev-before-geotag-blocks-1
:uses: DEF-development, DEF-managed_folders

Development SHALL happen in the library, after merge: a development subfolder anywhere in photos by destination — even
an empty one — stops geotag's planning, execution and finalize, and merge.
:::

## 10. Change only what needs changing

:::{inv} A run changes only what its inputs require
:id: INV-change_only_what_needs
:status: ruled
:criticality: high
:anti: yes
:verify: incidental
:uses: DEF-prep, DEF-geotag, DEF-merge

Every phase SHALL change only what its inputs actually require, as far as the work allows — redoing no settled work to
be safe, and leaving no file in a state other than its inputs require.
:::

:::{rul} Valid work is reused
:id: RUL-reuse_valid_work
:status: seed
:criticality: med
:verify: required
:aliases: idem-reuse-not-recompute-1
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
:status: seed
:criticality: med
:verify: required
:aliases: idem-recompute-staleness-only-1
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
:aliases: idem-mutate-on-real-diff-1
:refines: INV-change_only_what_needs

In every phase and every run, a file SHALL be moved, renamed or written only where its current state differs from what
the run requires of it: a file already in its place, with its name and its metadata, produces no operation.
:::

:::{rul} A run over unchanged inputs changes nothing
:id: RUL-no_op_run
:status: ruled
:criticality: med
:verify: required
:aliases: idem-no-op-run-1
:refines: INV-change_only_what_needs

A phase run over a workspace whose relevant state has not changed SHALL change nothing, and produce the same result —
the same operations, fingerprints and names.
:::

:::{rul} A run over unchanged inputs reports what it reused, never an error
:id: RUL-no_op_run_reports_reuse
:status: ruled
:criticality: low
:verify: required
:refines: RUL-no_op_run

A run over unchanged inputs SHALL report the work it reused and the files already right, never treating earlier work as
an error.
:::

## 11. Nothing changes that the user did not write down

:::{def} A decision
:id: DEF-decision
:status: ruled
:uses: DEF-geotag

A **decision** is a value the user records in one of geotag's records for the tool to act on — a destination's
timezone, an accepted time anchor, a clock offset, a confirmed drift check, a manual position, a folder fallback. The
tool *proposes*; the user *decides*.
:::

:::{inv} Every change follows from the record
:id: INV-every_change_from_the_record
:status: ruled
:criticality: high
:anti: yes
:verify: incidental
:aliases: authored-no-autonomous-mutation-1
:uses: DEF-decision

Every change a phase makes SHALL follow from a decision the user recorded, or from a fixed rule applied to recorded
inputs — never from a choice the tool makes on its own; an execution acts only on a plan made from those.
:::

:::{rul} The user writes the decisions
:id: RUL-user_writes_decisions
:status: ruled
:criticality: high
:anti: yes
:verify: required
:aliases: authored-fields-not-overwritten-1
:uses: DEF-decision, RUL-decision_kept

A decision field SHALL be written by the user alone, no phase ever overwriting what the user wrote.
:::

:::{rul} The tool lays out every decision's fields
:id: RUL-decision_fields_laid_out
:status: ruled
:criticality: med
:verify: required
:refines: RUL-user_writes_decisions

A phase SHALL create every field a decision needs, so the user fills in values, never structure.
:::

:::{rul} Prep takes no decision
:id: RUL-prep_takes_no_decision
:status: ruled
:criticality: med
:verify: required
:uses: DEF-prep

Prep SHALL ask the user for no decision, organizing from the state of the workspace and its configuration alone.
:::

:::{rul} The cause of every change can be found
:id: RUL-cause_locatable
:status: ruled
:criticality: med
:verify: required
:aliases: authored-locatable-cause-1
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
:aliases: authored-withdraw-undoes-1
:refines: RUL-decision_revisable

Withdrawing a decision SHALL undo its effect, not merely stop asserting it: a manual position withdrawn gives the file
back the position it held before, or none if it held none; a position derived by the tool is derived again; a time and a
name are recomputed where the file stands, never moving it out of its destination.
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
:aliases: archive-complete-each-phase-1
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
:aliases: archive-artifact-ownership-1
:uses: DEF-control_records

Each numbered record SHALL be written by the phase whose number it carries, and by no other: a phase MAY create, rewrite
or extend its own records across its runs, and reads every other phase's records read-only.
:::

:::{rul} An earlier record is carried forward by copying it
:id: RUL-carry_forward_by_copy
:status: ruled
:criticality: high
:anti: yes
:verify: required
:aliases: archive-no-cross-phase-write-1
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
:aliases: archive-finalize-nondestructive-1
:uses: DEF-finalize, DEF-archival_package

Finalize SHALL change nothing in the workspace's media, its other records or the library, only reading the record that
already stands at the end of geotag and writing the package from it.
:::

:::{rul} What the package holds
:id: RUL-package_contents
:status: ruled
:criticality: med
:verify: required
:aliases: archive-package-contents-1, archive-whole-control-dir-1
:uses: DEF-archival_package, DEF-transformation_log, DEF-control_records

The archival package SHALL hold every control record but the transient ones, archived together with its own list of
them: the configuration that governed the workspace; every current decision and plan record, exactly as the pipeline
validated it; the database, with its snapshot from the end of each phase; every phase's transformation log; and every
run's journal.
:::

:::{rul} The package describes itself
:id: RUL-package_self_describing
:status: ruled
:criticality: low
:verify: required
:aliases: archive-self-describing-manifest-1
:uses: DEF-archival_package

The package SHALL say which workspace it came from and which plan and execution it records, and list its contents with
each item's hash, so its integrity can be checked later.
:::

:::{rul} A photo's entry grows one phase at a time
:id: RUL-log_entry_grows
:status: ruled
:criticality: med
:anti: yes
:verify: required
:aliases: log-entry-append-only-1
:uses: DEF-transformation_log

A photo's entry in the log SHALL gather the steps of every phase it passes through and be whole through the latest of
them, each phase only appending its own steps, never rewriting an earlier one — so the latest phase's log is the full
record, and each earlier log stays its own phase's.
:::

:::{rul} The log is keyed by fingerprint
:id: RUL-log_keyed_by_fingerprint
:status: ruled
:criticality: med
:verify: required
:aliases: log-keyed-by-fingerprint-1
:uses: DEF-transformation_log, DEF-fingerprint

The log SHALL key each photo's entry by its fingerprint and carry the chain of names and places it passed through.
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
:aliases: log-decision-provenance-1
:uses: DEF-transformation_log, DEF-decision

A step that followed from a decision SHALL name that decision, so the why stands beside the what.
:::

:::{rul} A manual position's reversal is logged like its application
:id: RUL-log_records_gps_reverts
:status: ruled
:criticality: med
:verify: required
:aliases: log-records-gps-revert-1
:uses: DEF-transformation_log

A manual position applied, changed or withdrawn SHALL appear in the log with the position it replaced or restored, or
that there was none.
:::

:::{rul} The log reads as it stands
:id: RUL-log_human_readable
:status: ruled
:criticality: low
:verify: required
:aliases: log-human-readable-json-1
:uses: DEF-transformation_log

The log SHALL be readable as it stands, with no separate report: stably ordered, with descriptive names, and values as a
person reads them — times, timezones and offsets.
:::

:::{rul} History is kept across runs, as much as the log needs
:id: RUL-history_retained
:status: ruled
:criticality: med
:anti: yes
:verify: required
:aliases: log-retention-across-runs-1
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
:aliases: log-fail-if-insufficient-1
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
it, and the fingerprints of library files merge has read.
:::

:::{def} A phase's database image
:id: DEF-database_image
:status: ruled
:uses: DEF-workspace_database

A phase's **database image** is a copy of the workspace database as it stood at the end of that phase's latest
successful run.
:::

:::{rul} One database, in the workspace
:id: RUL-one_database
:status: ruled
:criticality: med
:anti: yes
:verify: required
:aliases: db-single-workspace-1
:uses: DEF-workspace_database, DEF-library

A workspace SHALL hold exactly one database of record, and the library none.
:::

:::{rul} Any other database is scratch
:id: RUL-other_databases_scratch
:status: ruled
:criticality: med
:verify: required
:refines: RUL-one_database

Any database a phase keeps besides the database of record SHALL be scratch: holding no decision and no history, safe to
delete at any time, and neither journalled nor archived.
:::

:::{rul} The database is part of the record
:id: RUL-database_is_record
:status: ruled
:criticality: low
:verify: required
:aliases: db-durable-artifact-1
:uses: DEF-workspace_database, DEF-archival_package

The workspace database SHALL be kept with the control records and archived in the package, never discarded with the
workspace as a cache would be.
:::

:::{rul} Each phase writes only its own part of the database
:id: RUL-database_regions_disjoint
:status: ruled
:criticality: med
:anti: yes
:verify: required
:aliases: db-disjoint-writers-1
:uses: DEF-workspace_database
:refines: RUL-phase_writes_own_records

Each phase SHALL write only its own part of the workspace database, no two phases writing the same rows.
:::

:::{rul} Finalize only reads the database
:id: RUL-finalize_reads_database
:status: ruled
:criticality: med
:anti: yes
:verify: incidental
:refines: RUL-database_regions_disjoint

Finalize SHALL only read the workspace database.
:::

:::{rul} Each phase keeps an image of the database at its end
:id: RUL-database_image_each_phase
:status: ruled
:criticality: med
:verify: required
:aliases: db-snapshot-per-phase-1, db-snapshot-skip-on-failure-1
:uses: DEF-database_image, DEF-archival_package

Each phase SHALL keep its database image, refreshed by each of its successful runs alone, and left untouched by every
other phase and by a run that does not succeed.
:::

:::{rul} A database image is never read back as working data
:id: RUL-image_never_working_data
:status: ruled
:criticality: med
:anti: yes
:verify: none
:omit_reason: no test asserts it (backlog item 3)
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
:aliases: db-snapshot-consistent-1
:uses: DEF-database_image

A database image SHALL be a consistent state of the database, never a copy torn mid-transaction.
:::

:::{rul} An interrupted capture leaves an image whole
:id: RUL-image_capture_atomic
:status: ruled
:criticality: high
:anti: yes
:verify: required
:aliases: db-snapshot-atomic-replace-1
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
:aliases: merge-library-protected-1
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
:aliases: merge-collision-same-content-1
:refines: RUL-collision_by_content

A taken place holding the same content SHALL mean the photo is already in the library: nothing is written there, and the
workspace's copy is removed.
:::

:::{rul} Different content is placed under a differentiating name
:id: RUL-collision_different_content
:status: ruled
:criticality: high
:anti: yes
:verify: required
:aliases: merge-collision-diff-content-1
:refines: RUL-collision_by_content

A taken place holding different content SHALL mean two photos share a name: the incoming one is placed under a
differentiating name.
:::

:::{rul} A library file is read at most once while unchanged
:id: RUL-library_file_read_once
:status: ruled
:criticality: low
:verify: required
:aliases: merge-fingerprint-cached-onfly-1
:uses: DEF-library, DEF-fingerprint, DEF-workspace_database

A library file's fingerprint SHALL be computed only when a collision needs it, and kept, so that a library file
unchanged since is never fingerprinted again in the workspace, in that run or a later one, while the way photos are
decoded is unchanged too — save for the one check before a photo is removed from the workspace.
:::

:::{rul} A library file is fingerprinted again before a photo it holds is removed
:id: RUL-library_file_rechecked_before_removal
:status: ruled
:criticality: high
:anti: yes
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
:aliases: lib-root-validated-outside-1
:uses: DEF-library, DEF-workspace
:refines: RUL-checked_paths

Merge SHALL check the library's configured place like every path the user writes, refusing it unless it is an existing
folder outside the workspace.
:::

:::{rul} A library is known by its mark alone
:id: RUL-library_known_by_mark
:status: ruled
:criticality: high
:anti: yes
:verify: required
:aliases: lib-marker-only-identity-1
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

Merge's library setup alone SHALL make the library's mark — once, making it again changing nothing.
:::

:::{rul} Merge's plan, dry run and execution stop without the mark
:id: RUL-library_mark_required
:status: ruled
:criticality: high
:anti: yes
:verify: required
:refines: RUL-library_known_by_mark

Merge's plan, dry run and execution SHALL only read the library's mark, and stop at once if it is absent.
:::

:::{rul} Merge creates in the library only what it places
:id: RUL-library_creates_only_placements
:status: ruled
:criticality: med
:anti: yes
:verify: required
:refines: RUL-library_known_by_mark

Beyond its mark and its lock, merge SHALL create in the library only the photos it places, the folders they go into,
and, while a photo crosses filesystems, its temporary copy.
:::

:::{rul} One merge at a time in a library
:id: RUL-library_lock
:status: ruled
:criticality: high
:anti: yes
:verify: required
:aliases: merge-library-lock-1
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
:aliases: merge-library-lock-failfast-1
:refines: RUL-library_lock

A merge that finds the library locked SHALL stop at once, having changed nothing in the library.
:::

:::{rul} A dead merge's library lock is recoverable
:id: RUL-library_lock_stale_recovered
:status: ruled
:criticality: med
:verify: incidental
:refines: RUL-library_lock_fail_fast

A library lock left by a merge that died SHALL be recognisable as stale, and recoverable, as the workspace's lock is.
:::

:::{rul} The library is confirmed before it is locked
:id: RUL-library_confirmed_before_lock
:status: ruled
:criticality: med
:anti: yes
:verify: required
:aliases: merge-lock-after-marker-1
:refines: RUL-library_lock

Merge SHALL take the workspace's lock first, then check the library's place and its mark, and only then take the
library's lock, so that no lock is ever left in a folder that is not a library — a merge stopped at any of these steps
having changed nothing in the library.
:::

:::{rul} Merge moves, and a photo leaves the workspace only once safe in the library
:id: RUL-merge_moves
:status: ruled
:criticality: high
:anti: yes
:verify: required
:aliases: merge-move-leaves-bydest-empty-1, merge-move-atomic-source-last-1
:uses: DEF-merge, DEF-library, DEF-managed_folders

Merge SHALL move each photo it places, removing the workspace's copy only once the library's is verified in place — and
a photo already in the library likewise.
:::

:::{rul} A photo merge cannot place stays where it is
:id: RUL-unplaced_photo_stays
:status: ruled
:criticality: high
:anti: yes
:verify: required
:aliases: merge-blocker-left-in-bydest-1
:refines: RUL-merge_moves

A photo merge cannot place SHALL stay where it is, the run then partial.
:::

:::{rul} Merge resumes, and a merged batch is a no-op
:id: RUL-merge_resumable
:status: ruled
:criticality: med
:verify: required
:aliases: merge-idempotent-resumable-1
:uses: DEF-merge
:refines: RUL-no_op_run

A merge interrupted SHALL be finished by running it again, which applies only what is outstanding — merging a batch
already merged changing nothing.
:::

:::{rul} Merge records where every photo landed
:id: RUL-merge_records_landing
:status: ruled
:criticality: low
:verify: required
:aliases: merge-records-summary-1
:uses: DEF-merge, DEF-transformation_log
:refines: RUL-phase_writes_own_records

Merge SHALL record, in its own records, where each photo landed in the library, whether it was renamed there, which were
already present, and what blocked the rest.
:::

:::{rul} Nothing is built from merge's records
:id: RUL-nothing_built_from_merge_records
:status: ruled
:criticality: low
:verify: none
:omit_reason: no test asserts it (backlog item 3)
:refines: RUL-merge_records_landing

Nothing SHALL be built from merge's records.
:::

:::{rul} Merge remakes the package as part of its run
:id: RUL-merge_reseals
:status: ruled
:criticality: med
:verify: required
:aliases: merge-reseals-automatically-1
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
:aliases: merge-reseal-no-rederive-1
:refines: RUL-merge_reseals

Merge SHALL remake the package from the records as they stand, re-deriving nothing of an earlier phase.
:::

:::{rul} Only a whole merge seals
:id: RUL-seal_on_success_only
:status: ruled
:criticality: high
:anti: yes
:verify: required
:aliases: seal-success-then-sealed-1, seal-partial-writes-no-marker-1
:uses: DEF-sealed_workspace, DEF-merge

Merge SHALL seal the workspace only when it succeeds whole — every photo by destination placed in the library or found
already there, none left — a partial, failed or interrupted merge leaving it unsealed.
:::

:::{rul} The seal alone says a workspace is finished
:id: RUL-seal_is_authority
:status: ruled
:criticality: med
:anti: yes
:verify: required
:aliases: seal-marker-is-authority-1, seal-marker-separate-file-1
:uses: DEF-sealed_workspace, DEF-managed_folders

Whether a workspace is finished SHALL be read from its seal alone, never from the state of its folders.
:::

:::{rul} A sealed workspace is never processed again
:id: RUL-sealed_refuses
:status: ruled
:criticality: high
:anti: yes
:verify: required
:aliases: seal-scripts-hardstop-1
:uses: DEF-sealed_workspace, DEF-decision
:refines: RUL-merge_is_terminal

In a sealed workspace prep, geotag and merge SHALL stop as they start, changing nothing but the owner record of the
workspace lock. Its records MAY still be read.
:::

:::{rul} The decision editor refuses a sealed workspace
:id: RUL-editor_refuses_sealed
:status: ruled
:criticality: high
:anti: yes
:verify: required
:aliases: edit-sealed-refuses-1
:refines: RUL-sealed_refuses

The decision editor SHALL neither open a sealed workspace nor save into it.
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
:criticality: high
:verify: required
:aliases: seal-prune-exception-1
:uses: DEF-sealed_workspace
:refines: RUL-sealed_refuses

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
:aliases: seal-new-dump-warn-1
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
:aliases: validate-everything-authored-1
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
:aliases: validate-paths-1
:uses: DEF-configuration, DEF-managed_folders, DEF-tracks
:refines: INV-authored_values_checked

A path the configuration names SHALL be neither empty nor blank, hold no character the platform forbids, and stay where
it must: the tracks' place outside the managed folders, the library's an existing folder outside the workspace.
:::

:::{rul} A snapshot's name is checked before any snapshot
:id: RUL-checked_snapshot_names
:status: ruled
:criticality: med
:verify: required
:aliases: validate-zfs-prefix-1
:uses: RUL-snapshot_optional
:refines: INV-authored_values_checked

The settings a snapshot's name is made from SHALL be checked to make a valid snapshot name before any snapshot is
attempted.
:::

:::{rul} A timezone is a real zone
:id: RUL-checked_timezones
:status: ruled
:criticality: med
:verify: required
:aliases: validate-timezone-1
:refines: INV-authored_values_checked

A timezone the user writes SHALL be a real zone that resolves, never an arbitrary string.
:::

:::{rul} A position, an offset and a true time are in range
:id: RUL-checked_positions_and_times
:status: ruled
:criticality: high
:verify: required
:aliases: validate-coords-offsets-1
:uses: DEF-decision
:refines: INV-authored_values_checked

A position, a clock offset or a true time the user writes SHALL be in range: a position two well-formed numbers —
latitude −90 to 90, longitude −180 to 180, both or neither; a clock offset a number within a day either way; a true time
a date and time that parses.
:::

:::{rul} The filename format makes a safe name
:id: RUL-checked_filename_format
:status: ruled
:criticality: med
:verify: required
:aliases: validate-filename-format-1
:uses: RUL-one_filename_format
:refines: INV-authored_values_checked

The filename format SHALL make a part of a name that is never empty and is safe on the filesystem: no path separator
and no character a filename may not hold.
:::

:::{rul} A number is of the right kind and in range
:id: RUL-checked_numbers
:status: ruled
:criticality: med
:verify: required
:aliases: validate-numeric-thresholds-1
:uses: DEF-configuration
:refines: INV-authored_values_checked

A number the configuration sets — a threshold, a distance, a duration — SHALL be of the right kind and within
a sane range: a duration or a distance is never negative.
:::

:::{rul} A choice is one of its choices, and a decision has its shape
:id: RUL-checked_shapes
:status: ruled
:criticality: high
:anti: yes
:verify: required
:aliases: validate-enum-structure-1
:uses: DEF-decision, RUL-user_writes_decisions
:refines: INV-authored_values_checked

A yes-or-no SHALL be a yes or a no, a value from a fixed set — a device group's class among them — one of that set, and
a decision's structure whole: a decision whose structure is broken is an error, never ignored.
:::

:::{rul} An invalid value stops the phase before it changes anything
:id: RUL-invalid_value_stops
:status: ruled
:criticality: high
:anti: yes
:verify: required
:aliases: validate-fail-closed-1
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
:aliases: validate-locate-no-repair-1
:uses: DEF-authored_value, RUL-cause_locatable
:refines: INV-authored_values_checked

The report of an invalid value SHALL name the record and the field it was written in — for a decision, also the
destination, the camera group or the file it is about.
:::

:::{rul} An invalid value is never repaired
:id: RUL-invalid_value_never_repaired
:status: ruled
:criticality: high
:anti: yes
:verify: required
:refines: RUL-invalid_value_located

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

:::{rul} An invalid decision is kept, and marked
:id: RUL-invalid_decision_kept
:status: ruled
:criticality: med
:anti: yes
:verify: required
:aliases: validate-preserve-invalid-1
:uses: DEF-decision, RUL-decision_kept
:refines: RUL-invalid_value_stops

A decision found invalid SHALL be kept exactly as the user wrote it, and reported as needing correction — never erased
or rewritten.
:::

## 15. Nothing overwritten, nothing left half-done

:::{rul} Every name is checked free as it is written
:id: RUL-target_free_at_execute
:status: ruled
:criticality: high
:anti: yes
:verify: required
:aliases: exec-noclobber-recheck-1, exec-noclobber-all-content-ops-1
:uses: RUL-suffix_no_clobber, DEF-library

Immediately before each change that gives a file a name — prep's moves, renames and setting duplicates aside, geotag's
renames, merge's placing in the library — execution SHALL check that the name is free, ignoring case where the
filesystem does, never writing onto a taken name on the strength of the plan: a name found taken blocks that operation.
:::

:::{rul} An interrupted move leaves the before or the after
:id: RUL-operations_atomic
:status: ruled
:criticality: high
:anti: yes
:verify: incidental
:aliases: atomic-operations-1

A move, a rename or a placement SHALL be one indivisible operation where the filesystem allows, so that an interruption
leaves the state before it or the state after, never part of either.
:::

:::{rul} A move that cannot be one operation is never lost
:id: RUL-split_move_never_lost
:status: ruled
:criticality: high
:anti: yes
:verify: incidental
:refines: RUL-operations_atomic
:excepts: RUL-failed_operation_clean

Where a move cannot be one operation, an interruption, or a failure partway, SHALL leave the file whole under its old
name, its new name or both — never under neither, never part of one.
:::

:::{rul} A workspace lies on one filesystem
:id: RUL-workspace_one_filesystem
:status: ruled
:criticality: high
:anti: yes
:verify: required
:uses: DEF-workspace
:refines: RUL-operations_atomic

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

Every run of every phase on a workspace SHALL check, before it reads or changes anything, that the workspace lies on
one filesystem — never taking it as whole because an earlier run found it so.
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
:uses: RUL-cause_locatable
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

:::{rul} A file rewritten in place is the old one or the new one
:id: RUL-rewrite_in_place_atomic
:status: ruled
:criticality: high
:anti: yes
:verify: none
:omit_reason: crash-injection testing is out of scope; the guarantee rests on how the file is written
:aliases: atomic-inplace-metadata-1
:refines: RUL-operations_atomic

A write that rewrites a file in place SHALL leave, if interrupted, the intact original or the fully written file —
never a damaged one between them.
:::

:::{rul} Across filesystems, a placement is still all or nothing
:id: RUL-cross_fs_all_or_nothing
:status: ruled
:criticality: high
:anti: yes
:verify: required
:aliases: atomic-crossfs-equivalent-1
:refines: RUL-operations_atomic

Where merge's placement into the library crosses filesystems and cannot be one operation, it SHALL be made equivalent:
the file copied under a temporary name beside its place, verified, and only then given its name, if that is still free —
so that an interruption leaves no file under that name, or the complete one, never part of one.
:::

:::{rul} A temporary copy a crash left is cleared
:id: RUL-crash_temps_cleared
:status: ruled
:criticality: low
:verify: required
:aliases: atomic-crossfs-temp-sweep-1
:uses: DEF-merge, DEF-library, RUL-temp_name_own
:refines: RUL-cross_fs_all_or_nothing

Merge SHALL clear, as its execution starts, the temporary copies an interrupted merge left in the folders it places
into, and record how many.
:::

:::{rul} A temporary copy bears a name no photo bears
:id: RUL-temp_name_own
:status: ruled
:criticality: low
:verify: incidental
:refines: RUL-cross_fs_all_or_nothing

A temporary copy SHALL bear a name of its own, which no photo bears.
:::

:::{rul} A failed operation leaves its file as it was
:id: RUL-failed_operation_clean
:status: ruled
:criticality: high
:anti: yes
:verify: required
:aliases: exec-failed-op-clean-1

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
