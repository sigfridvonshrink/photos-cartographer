# Shared — what every phase guarantees

The facts all three phases — prep, geotag and merge — must agree on. Each item says which phases it binds; an item
that names none binds them all. *Why* each holds is in [the rationale](../rationale/shared.md); *how this build meets
it*, in [the build](../build/shared.md).

## 0. The pipeline

:::{def} The workspace
:id: DEF-workspace
:status: seed

A **workspace** is the transient place one ingest happens in: a dump of media enters it, the phases work on it in
turn, and merge empties it into the library. Every run acts on exactly one workspace.
:::

:::{def} The library
:id: DEF-library
:status: seed
:uses: DEF-workspace

The **library** is the permanent, curated collection the media ends in — outside every workspace, and written only by
merge.
:::

:::{def} Prep
:id: DEF-prep
:status: seed
:uses: DEF-workspace

**Prep**, the first phase, takes an unorganized dump and makes it a clean working set: it consolidates the dump,
normalizes extensions, sets duplicates aside (recoverably, never deleting), organizes the media by date, and hands
geotag what it found.
:::

:::{def} Geotag
:id: DEF-geotag
:status: seed
:uses: DEF-prep

**Geotag**, the second phase, resolves each photo to its true time, inferring and correcting each camera's clock
offset; places the photos that carry no position along the recorded tracks; and renames each by its corrected local
time.
:::

:::{def} Merge
:id: DEF-merge
:status: seed
:uses: DEF-geotag, DEF-library

**Merge**, the third phase, runs after a workspace has been geotagged and finalized: it moves the finalized media,
sorted by destination, into the library — never renaming or overwriting anything already there — and then seals the
workspace.
:::

## 1. One run at a time

:::{inv} One run at a time
:id: INV-one_run_at_a_time
:status: seed
:criticality: high
:anti: yes
:verify: required
:aliases: lock-mutual-exclusion-1

At most one cartographer run SHALL act on a workspace at any time — whatever the commands: two runs of one phase, runs
of two phases, a merge, a finalize, or a quarantine prune.
:::

:::{rul} One lock, taken by every command
:id: RUL-every_command_locks
:status: seed
:criticality: med
:verify: incidental
:aliases: lock-every-command-takes-1
:upholds: INV-one_run_at_a_time

A workspace SHALL have exactly one lock, shared by every command. Every command that reads or changes the workspace
SHALL hold it while it does.
:::

:::{rul} The lock comes before anything is read
:id: RUL-lock_before_reading
:status: seed
:criticality: high
:verify: required
:aliases: lock-covers-planning-1
:upholds: INV-one_run_at_a_time

A run SHALL hold the lock before it reads any of the workspace's content — before it plans, scans, fingerprints,
reads metadata, dry-runs or executes. Planning changes nothing, and is inside the lock all the same.
:::

:::{rul} The lock lasts the whole run, and no longer
:id: RUL-lock_through_the_run
:status: seed
:criticality: high
:anti: yes
:verify: required
:aliases: lock-covers-whole-run-1
:upholds: INV-one_run_at_a_time

A run SHALL hold the lock until it ends — through planning, dry run, execution, and every record and artifact it
writes — and SHALL release it then. The lock SHALL NOT outlive its run: between runs, the workspace is unlocked.
:::

:::{rul} A locked workspace is refused at once
:id: RUL-lock_fail_fast
:status: seed
:criticality: high
:anti: yes
:verify: required
:aliases: lock-failfast-1
:upholds: INV-one_run_at_a_time

A run that finds the workspace locked SHALL NOT wait for it. It SHALL stop at once, saying the workspace is locked by a
run in progress, having scanned, planned and changed nothing — and having produced no plan, no dry-run report and no
artifact.
:::

:::{rul} The lock is released however the run ends
:id: RUL-lock_released_on_any_end
:status: seed
:criticality: med
:verify: required
:aliases: lock-release-on-exit-error-1
:refines: RUL-lock_through_the_run

A run SHALL release the lock when it ends, whether it succeeds or fails.
:::

:::{rul} A stale lock is recognised and recovered
:id: RUL-stale_lock_recovered
:status: seed
:criticality: med
:verify: required
:aliases: lock-stale-detectable-1

A lock left behind by a run that died SHALL be recognisable as stale, and recoverable, so that a crash never leaves a
workspace locked for good.
:::

:::{rul} Only a dead owner's lock is taken over
:id: RUL-stale_takeover_conservative
:status: seed
:criticality: high
:anti: yes
:verify: none
:omit_reason: no test asserts it (backlog item 3)
:aliases: lock-stale-takeover-conservative-1
:refines: RUL-stale_lock_recovered

A stale lock SHALL be taken over only when its owner is provably gone. A lock whose owner may still be running SHALL be
left alone.
:::

Merge also takes a lock on the library it writes into, so that two merges into one library — even from two workspaces
— never overlap; that lock is held besides the workspace's, not instead of it. *(Its items come with §15.2 of the
shared contract, when that is converted.)*

## 2. A snapshot before changing, optionally

:::{rul} A snapshot is optional, and nothing rests on it
:id: RUL-snapshot_optional
:status: seed
:criticality: med
:verify: incidental
:aliases: snapshot-optional-1

A phase that changes files MAY first take a snapshot of what it is about to change, from which the whole change can be
rolled back. Cartographer SHALL be complete and safe without one: no guarantee SHALL depend on a snapshot having been
taken.
:::

:::{rul} No snapshot unless configured
:id: RUL-snapshot_off_by_default
:status: seed
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

Nothing in cartographer but the snapshot SHALL depend on a particular filesystem's features; and cartographer SHALL run
fully on a filesystem that has none.
:::

:::{rul} A snapshot names its plan
:id: RUL-snapshot_per_plan
:status: seed
:criticality: low
:verify: required
:aliases: snapshot-keyed-by-plan-1

Each snapshot SHALL be identifiable by the plan whose changes it precedes.
:::

:::{rul} When a snapshot is taken
:id: RUL-snapshot_timing
:status: seed
:criticality: med
:verify: required
:aliases: snapshot-timing-1

A snapshot SHALL be taken after the plan has been validated against its dependencies and the lock is held, and before
the plan's first change.
:::

:::{rul} A required snapshot that fails stops the run
:id: RUL-required_snapshot_or_nothing
:status: seed
:criticality: high
:anti: yes
:verify: required
:aliases: snapshot-required-fatal-1
:refines: RUL-snapshot_timing

When the configuration requires snapshots, a run that cannot take one SHALL stop before it changes anything.
:::

:::{rul} Without a required snapshot, the run goes on
:id: RUL-unrequired_snapshot_proceeds
:status: seed
:criticality: med
:verify: required
:aliases: snapshot-not-required-proceeds-1
:refines: RUL-snapshot_optional

When snapshots are not required, or not configured, a run SHALL proceed without one. Its safety then rests, as it
always does, on the journal, the recoverable quarantine, never overwriting, and the filesystem as the truth.
:::

:::{rul} Merge snapshots the library
:id: RUL-merge_snapshots_library
:status: seed
:criticality: med
:verify: none
:omit_reason: carried by merge's own snapshot items, when merge is converted

Prep's and geotag's snapshot SHALL cover the workspace; merge's SHALL cover the library, where its changes land.
:::

## 3. One configuration, kept in the workspace

:::{def} The configuration
:id: DEF-configuration
:status: seed
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

All three phases SHALL read their settings from the workspace's one configuration, each the settings it needs. No phase
SHALL keep settings of its own, and no setting that governs a run SHALL come from outside the workspace.
:::

:::{rul} Prep seeds the configuration once
:id: RUL-config_seeded_once
:status: seed
:criticality: med
:verify: required
:aliases: config-seeded-by-prep-1

A prep run that finds no configuration SHALL create one from the seed defaults. A prep run that finds one SHALL use it as
it is.
:::

:::{rul} The workspace's configuration governs it, not the defaults
:id: RUL-config_authoritative
:status: seed
:criticality: med
:verify: required
:aliases: config-file-authoritative-1
:refines: RUL-config_seeded_once

The seed defaults SHALL serve only to seed a new workspace. Once a workspace's configuration exists, it SHALL govern
every run in that workspace, whatever the defaults later become.
:::

:::{rul} Who writes the configuration
:id: RUL-config_writers
:status: seed
:criticality: high
:anti: yes
:verify: required
:aliases: config-prep-sole-writer-1, config-merge-readonly-1

The configuration SHALL be written only when prep seeds it, when the user edits it by hand, and by the library setup
below. Geotag SHALL never write it. Merge's planning, dry run and execution SHALL leave it unchanged.
:::

:::{rul} The library setup records one setting
:id: RUL-library_setup_writes_one_setting
:status: seed
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
:status: seed
:criticality: med
:verify: required
:aliases: config-hashed-cascade-1

The configuration SHALL be a dependency of what is derived under it, like every other artifact, so that a change to it
never changes a run without being detected. A digest of its whole content SHALL be recorded for integrity.
:::

:::{rul} The configuration is part of the permanent record
:id: RUL-config_archived
:status: seed
:criticality: med
:verify: none
:omit_reason: carried by the archival package's items, when §13 of the shared contract is converted

The configuration SHALL be part of the archival record the workspace leaves behind.
:::

:::{rul} The configuration is never media
:id: RUL-config_never_media
:status: seed
:criticality: med
:anti: yes
:verify: required
:aliases: config-in-control-dir-skipped-1
:refines: RUL-control_records_never_media

No phase SHALL treat the configuration as media: none SHALL inventory or organize it, and none SHALL fold it into what
identifies the media.
:::

:::{rul} A change to one area restales only what depends on it
:id: RUL-staleness_by_area
:status: seed
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
:status: seed
:criticality: med
:anti: yes
:verify: required
:aliases: config-edit-outside-timepolicy-1
:refines: RUL-staleness_by_area

A result that is costly to rebuild SHALL be made stale only by the areas it depends on. A configuration change outside
the camera-time policy SHALL NOT make stale the true times already resolved.
:::

:::{rul} Any configuration change restales the plan
:id: RUL-any_config_change_replans
:status: ruled
:criticality: med
:verify: required
:aliases: config-wholehash-coarse-replan-1

Any change to the configuration, in whatever area, SHALL make stale every plan made before it — prep's plan, geotag's
executable plan and merge's plan — and none of them SHALL be executed.
:::

:::{rul} A change to the folder names or the media classes restales the plans
:id: RUL-organization_settings_restale
:status: seed
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
workspace. No setting SHALL move it.
:::

:::{def} What the configuration sets
:id: DEF-config_areas
:status: seed
:uses: DEF-configuration

The configuration sets, at least: the snapshot policy; which camera groups are phones and which have fixed clocks; the
filename timestamp format; where the tracks are and the thresholds for matching photos to them; the camera-time policy;
the library and how merge places files in it; the managed folders' names; and which extensions are which class of
media. Each area's detail is in the items of its own section.
:::

:::{rul} The user names the folders; their roles are fixed
:id: RUL-folder_names_not_roles
:status: seed
:criticality: med
:anti: yes
:verify: required
:aliases: config-folder-roles-not-config-1

The configuration SHALL set the managed folders' names. Their roles, and the structure they form, SHALL NOT be
configurable, and every phase SHALL find a managed folder by its role, never by its name.
:::

:::{rul} The user classifies camera groups; how they are derived is fixed
:id: RUL-camera_classes_not_derivation
:status: seed
:criticality: med
:anti: yes
:verify: none
:omit_reason: no test asserts it (backlog item 3)
:aliases: config-camerakey-version-not-config-1

The configuration SHALL say which camera groups are phones and which have fixed clocks — the only part of camera
grouping it sets. How a camera group is derived, and the version of that derivation, SHALL NOT be configurable.
:::

:::{rul} Each extension is one class of media
:id: RUL-extension_one_class
:status: seed
:criticality: med
:verify: required
:aliases: config-ext-one-class-1

The configuration SHALL list which extensions are images, raw files and videos. The classes themselves SHALL NOT be
configurable; an extension not listed SHALL be `other`; and an extension SHALL be in exactly one class.
:::

:::{rul} Every value the user supplies is checked before use
:id: RUL-config_validated_before_use
:status: seed
:criticality: med
:verify: required
:aliases: config-values-validated-1

Every value of the configuration that comes from the user SHALL be validated before it is used (§14 of the shared
contract), as part of reading the configuration — never as a separate, optional pass.
:::

## 4. The control records, apart from the media

:::{def} The control records
:id: DEF-control_records
:status: seed
:uses: DEF-workspace

A workspace's **control records** are everything cartographer keeps in it besides the media: the configuration, the
plans and the decisions, the journals, the end-of-phase records and the databases.
:::

:::{rul} The control records are kept together, apart from the media
:id: RUL-control_records_together
:status: seed
:criticality: med
:verify: required
:aliases: ctrl-all-in-photos-ingest-1
:uses: DEF-control_records

Every control record SHALL be kept in the workspace's one place for them. None SHALL sit among the media or at the
workspace's top level.
:::

:::{rul} The control records' place is never searched for media
:id: RUL-control_records_never_media
:status: seed
:criticality: med
:anti: yes
:verify: required
:aliases: ctrl-prep-skips-wholesale-1
:refines: RUL-control_records_together

No phase SHALL take a control record for media. The place they are kept SHALL be left out of every inventory of media as
a whole — not file by file.
:::

:::{def} The strays folder
:id: DEF-strays_folder
:status: seed
:uses: DEF-prep

The **strays folder** is a media-tree folder at the workspace's top level. It holds the files that are not media which
prep moved out of the inbox, one subfolder for each run, their structure kept. It is neither a control record nor any
phase's output.
:::

:::{rul} What prep never inventories
:id: RUL-not_inventoried
:status: seed
:criticality: med
:verify: incidental
:aliases: ctrl-skip-set-1
:refines: RUL-control_records_never_media
:uses: DEF-strays_folder

Prep SHALL leave out of its inventory of media, each as a whole: the control records' place, the quarantine, a
version-control directory, and the strays folder with everything in it; and every hidden file. Prep SHALL write into the
strays folder but never scan it, and nothing SHALL process its contents again.
:::

:::{rul} Hidden files in a dump are quarantined
:id: RUL-dump_hidden_files_quarantined
:status: seed
:criticality: med
:verify: required
:aliases: ctrl-dotfiles-swept-quarantine-1

Hidden files that arrive in a dump area — the workspace's top level on the run that initializes it, or the inbox — SHALL
be moved to the recoverable quarantine, not merely left out.
:::

:::{rul} Each plan has one fixed place
:id: RUL-plan_at_fixed_place
:status: seed
:criticality: med
:verify: required
:aliases: plan-canonical-path-1

Each phase's plan, and each of its decision records, SHALL have one fixed place among the control records. The phase's
planning SHALL write it there, and its dry run and its execution SHALL read it from there.
:::

:::{rul} No command is told where a plan is
:id: RUL-no_plan_location_option
:status: seed
:criticality: med
:anti: yes
:verify: none
:omit_reason: no test asserts it (backlog item 3)
:aliases: plan-no-path-flag-1
:refines: RUL-plan_at_fixed_place

No command SHALL take an option saying where to put a plan or where to find one; the fixed place is the contract.
:::

:::{rul} No plan, no dry run and no execution
:id: RUL-no_plan_no_run
:status: seed
:criticality: med
:anti: yes
:verify: required
:aliases: plan-missing-stops-1

A dry run or an execution that finds no plan in its place SHALL stop, and tell the user to plan first.
:::

:::{rul} A dry run summarises the real plan
:id: RUL-dry_run_summarises_the_real_plan
:status: seed
:criticality: med
:anti: yes
:verify: required
:aliases: dryrun-summary-not-dump-1

A dry run SHALL validate the saved plan that execution would carry out, and report on that plan — never on a separate
simulation.
:::

:::{rul} Re-planning sets the prior plan aside
:id: RUL-replanning_keeps_the_prior
:status: seed
:criticality: high
:anti: yes
:verify: required
:aliases: plan-replan-no-clobber-1

Re-planning SHALL never overwrite a plan or a decision record. When what it makes differs from what is saved, the saved
one SHALL first be set aside, recoverably, and the user told where.
:::

:::{rul} An unchanged re-plan writes nothing
:id: RUL-unchanged_replan_writes_nothing
:status: seed
:criticality: med
:verify: none
:omit_reason: no test asserts it (backlog item 3)
:aliases: plan-unchanged-no-backup-1
:refines: RUL-replanning_keeps_the_prior

A re-plan whose result is identical to what is saved SHALL write nothing and set nothing aside.
:::

:::{rul} Geotag verifies the handoff by its content
:id: RUL-handoff_verified_by_content
:status: seed
:criticality: med
:verify: required
:aliases: handoff-verified-by-content-1
:refines: RUL-hash_detects_any_change

Geotag SHALL verify prep's handoff before using it, though it lives among the control records: by recomputing the
fingerprint of its content and comparing it with the one its dependencies recorded — by its content, not its exact
bytes.
:::

:::{rul} Refreshing what describes the run restales nothing
:id: RUL-run_only_refresh_restales_nothing
:status: seed
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

:::{rul} Only prep builds the structure, once
:id: RUL-structure_built_once
:status: seed
:criticality: med
:anti: yes
:verify: required
:upholds: INV-undisturbed_shape

Prep SHALL create the full structure of managed folders exactly once, when it initializes the workspace, and SHALL never
remove one. No other phase SHALL create or repair the workspace's structure; the folders merge creates in the library
are placement, not structure.
:::

:::{rul} The top level holds only what belongs there
:id: RUL-top_level_only_managed
:status: seed
:criticality: high
:anti: yes
:verify: required
:aliases: struct-base-folders-only-1
:upholds: INV-undisturbed_shape

The top level of an initialized workspace SHALL hold only the managed folders, the control records' place, the
quarantine and hidden entries. Any other entry — a file, a folder, a link — SHALL be a misplaced dump, and block every
phase alike. The inbox SHALL be the only place a dump belongs.
:::

:::{rul} A new workspace's first dump is at its top level
:id: RUL-first_dump_at_top_level
:status: seed
:criticality: med
:verify: required
:aliases: struct-uninit-exception-1
:refines: RUL-top_level_only_managed

On a workspace not yet initialized, files and folders at the top level SHALL be the first dump, and SHALL start
initialization. A symbolic link there SHALL still block.
:::

:::{rul} No symbolic link is followed, and any link blocks
:id: RUL-no_links
:status: seed
:criticality: high
:anti: yes
:verify: required
:aliases: struct-symlinks-barred-1
:upholds: INV-undisturbed_shape

No phase SHALL follow or organize a symbolic link. A link anywhere among the managed files SHALL block — a link to a
file anywhere; a link to a folder inside a dump or a managed folder, whose mere presence blocks though it is never
entered; a managed folder that is itself a link, before it is walked; a link at the top level — never be skipped
silently. The phase SHALL name the link and produce no executable plan and no artifact after it.
:::

:::{rul} Prep checks the whole tree; the others check the top level
:id: RUL-who_checks_for_links
:status: seed
:criticality: med
:verify: required
:refines: RUL-no_links

Prep SHALL check for links across the whole tree it walks, the destination tree included though prep never changes it.
Geotag and merge SHALL check the top level themselves, and SHALL consume only a handoff prep built with no link present.
:::

:::{rul} A missing managed folder blocks, and is never rebuilt
:id: RUL-missing_folder_blocks
:status: seed
:criticality: high
:anti: yes
:verify: required
:aliases: struct-no-silent-rebuild-1
:upholds: INV-undisturbed_shape

On an initialized workspace, a missing managed folder SHALL block every phase. It SHALL NOT be recreated outside
initialization, and no phase SHALL organize media into a structure it had to rebuild. The block SHALL name the missing
folders, say that something is wrong, and tell the user to restore them and run again; an empty folder restores one.
An empty inbox SHALL be normal — the steady state, not a missing folder.
:::

:::{rul} The shape is checked first
:id: RUL-shape_checked_first
:status: seed
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
:status: seed

A **camera group** is the photos one camera or device took, identified by a key derived from the device-identity
metadata the files carry.
:::

:::{rul} Prep derives the camera group
:id: RUL-prep_derives_camera_group
:status: seed
:criticality: med
:verify: required
:aliases: camera-prep-computes-key-1
:uses: DEF-camera_group

Prep SHALL derive each file's camera group from its device-identity metadata, and record it both in what it hands
geotag and in its own records.
:::

:::{rul} Geotag reuses prep's camera group
:id: RUL-geotag_reuses_camera_group
:status: seed
:criticality: med
:anti: yes
:verify: required
:aliases: camera-geotag-reuses-1
:refines: RUL-prep_derives_camera_group

Geotag SHALL use the camera group prep derived, and SHALL NOT derive a file's identity again.
:::

:::{rul} The derivation carries a version
:id: RUL-camera_group_derivation_versioned
:status: seed
:criticality: med
:anti: yes
:verify: required
:aliases: camera-version-detectable-1
:refines: RUL-prep_derives_camera_group

How camera groups are derived SHALL carry a version, which SHALL take part in the checks of freshness and of
dependencies, so that a change to the derivation is detected and old and new groups are never silently mixed.
:::

:::{rul} A camera group is known once it is classified
:id: RUL-known_when_classified
:status: seed
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
:status: seed
:uses: DEF-prep, DEF-geotag

A file's **timestamp name** is the name prep and geotag give it from its timestamp, in the one format the configuration
sets, followed by a differentiating suffix when that name is taken.
:::

:::{rul} One format, set by the configuration
:id: RUL-one_filename_format
:status: seed
:criticality: med
:verify: incidental
:aliases: fname-single-shared-key-1
:uses: DEF-timestamp_name

Prep and geotag SHALL name files from a timestamp in one format for the whole pipeline, not one for each phase, set by
the configuration; neither SHALL hard-code it.
:::

:::{rul} A taken name gets a suffix, never clobbering
:id: RUL-suffix_no_clobber
:status: seed
:criticality: high
:anti: yes
:verify: required
:aliases: fname-suffix-noclobber-1

A file whose timestamp name is already taken SHALL get a zero-padded differentiating suffix, allocated deterministically
and without clobbering: against every name on disk and every name planned in the run, compared without regard to case,
so that two files never collide.
:::

:::{rul} Which free name each phase takes
:id: RUL-suffix_choice_by_phase
:status: ruled
:criticality: med
:verify: required
:aliases: fname-allocation-per-phase-1
:refines: RUL-suffix_no_clobber

Prep and geotag SHALL take the first free name — the name with no suffix when it is free, otherwise the lowest free
suffix — by one identical rule. Merge SHALL take the suffix above the highest already used for that name, never a lower
one that has come free.
:::

:::{rul} Prep's name is provisional
:id: RUL-prep_name_provisional
:status: seed
:criticality: med
:verify: incidental
:aliases: fname-prep-provisional-1

Prep SHALL derive a file's name from its raw timestamp, as the camera recorded it, for organizing and ordering only.
The name SHALL be provisional: prep SHALL NOT correct it, resolve its timezone or convert it to UTC.
:::

:::{rul} Geotag's name is final
:id: RUL-geotag_name_final
:status: seed
:criticality: med
:verify: required
:aliases: fname-geotag-final-1

Geotag SHALL recompute a file's name from its corrected local time at the destination — its resolved true time, in the
destination's civil timezone — and rename it to that final name.
:::

:::{rul} An uncorrected file keeps its name
:id: RUL-uncorrected_keeps_its_name
:status: seed
:criticality: med
:verify: required
:aliases: fname-uncorrected-no-rename-1
:uses: RUL-prep_name_provisional, RUL-geotag_name_final

A file's name SHALL change between prep and geotag only when its timestamp is corrected. Geotag SHALL plan no rename for
a file whose time is not corrected.
:::

:::{rul} A name off the format is an ordinary dump
:id: RUL-nonconforming_name_is_a_dump
:status: seed
:criticality: med
:anti: yes
:verify: none
:omit_reason: no test asserts it (backlog item 3)
:aliases: fname-nonconforming-redumped-1

A file in the workspace whose name does not follow the format SHALL be treated as any other dump — taken in and named
by the pipeline — never specially migrated or matched against patterns. No phase SHALL read meaning from a file's name:
its timestamp SHALL come from its metadata.
:::

## 7. The tracks, kept outside the managed folders

:::{def} The tracks
:id: DEF-tracks
:status: seed
:uses: DEF-geotag, DEF-configuration

A workspace's **tracks** are the recorded position logs geotag reads as evidence: to propose time anchors, and to place
photos along them by interpolation or extrapolation. The configuration says where they are.
:::

:::{rul} Only geotag reads the tracks
:id: RUL-tracks_geotag_only
:status: seed
:criticality: med
:anti: yes
:verify: required
:aliases: gpx-prep-unaware-1
:uses: DEF-tracks

Geotag SHALL be the only phase that reads the tracks: it scans their location, parses them, fingerprints them and uses
them as evidence. Prep SHALL NOT read, parse, fingerprint or move them, nor otherwise act on them.
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

The tracks' location SHALL lie outside the managed folders — neither inside one nor containing one. Where outside them
is the configuration's choice, not part of this contract. A configuration that places it otherwise SHALL be refused
before any phase uses it.
:::

:::{rul} A track file stops prep, and stays where it is
:id: RUL-track_files_block_prep
:status: ruled
:criticality: high
:anti: yes
:verify: required
:uses: DEF-tracks, DEF-strays_folder

A track file — a recorded position log in any of the usual formats, whether or not geotag reads that format — found
anywhere prep inventories, in the dump or in a managed folder, SHALL block prep's plan. Prep SHALL leave it where it is:
never moving it, to the strays folder or anywhere else, and never treating it as a file of no media class.
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
:status: seed

A media file's **fingerprint** is the identity of its decoded content — a photo's pixels, a video's streams. Unqualified,
*fingerprint* means this.
:::

:::{def} A hash
:id: DEF-hash
:status: seed

A record's **hash** is a digest of its exact bytes — of a numbered record, or of the configuration. Unqualified, *hash*
means this.
:::

:::{def} The dependency cascade
:id: DEF-dependency_cascade
:status: seed
:uses: DEF-fingerprint, DEF-hash, DEF-config_areas

The **dependency cascade** is how the phases keep a record from being used once what it was made from has changed: each
record carries what it depends on — media by their fingerprints, other records by their hashes, and settings by the
fingerprints of the configuration areas it reads — and each use checks them first. Its full name, the
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

No phase SHALL use a record once anything it was derived from has changed. Each phase SHALL validate what it derives
from, then create the record, record those dependencies in it, and refuse its use downstream when any of them has
changed.
:::

:::{rul} A fingerprint survives what the pipeline does to a file
:id: RUL-fingerprint_survives_mutation
:status: seed
:criticality: med
:verify: required
:aliases: dep-fingerprint-invariant-1
:uses: DEF-fingerprint

A media file's fingerprint SHALL stay the same when the pipeline rewrites its metadata or its position, or renames it.
:::

:::{rul} A hash changes with any byte
:id: RUL-hash_detects_any_change
:status: seed
:criticality: med
:verify: required
:aliases: dep-hash-sensitive-1
:uses: DEF-hash

A record's hash SHALL change on any change to its bytes, and SHALL be what checks a record or the configuration as a
dependency. Prep's handoff is the one exception: it is checked by its content.
:::

## 9. One loop across the phases

:::{def} The managed folders
:id: DEF-managed_folders
:status: seed
:uses: DEF-workspace, DEF-strays_folder

The **managed folders** are the workspace's media folders, each with a fixed role: the **inbox**, where a dump arrives;
the strays folder; **missing metadata**, for media with no capture time; **redundant JPEGs**; **videos by date**;
**photos by date**; and **photos by destination**, the staging the user sorts photos into and merge empties into the
library.
:::

:::{def} The operator loop
:id: DEF-operator_loop
:status: seed
:uses: DEF-prep, DEF-geotag, DEF-merge, DEF-managed_folders

The **operator loop** is how the user drives the three phases through one workspace's life: prep organizes a dump; the
user sorts photos into photos by destination; prep records the sort; geotag is re-run, the user deciding what it asks,
until its plan is ready, and executes it; more dumps may follow, each from prep again; finalize closes the workspace's
record; merge moves it into the library. Each phase's own loop is in its own spec; this is the sequence across them.
:::

:::{def} Finalize
:id: DEF-finalize
:status: seed
:uses: DEF-geotag

**Finalize** is geotag's closing command, given once the user judges the workspace's media done: it assembles the
workspace's permanent record and its complete transformation log.
:::

:::{def} Development
:id: DEF-development
:status: seed
:uses: DEF-library

**Development** is the later processing of photos into distribution copies — the JPEG and TIFF breakout — kept in
subfolders of a destination.
:::

:::{rul} Prep leaves the inbox empty
:id: RUL-prep_empties_inbox
:status: seed
:criticality: med
:verify: required
:uses: DEF-managed_folders

A prep execution SHALL leave the inbox empty: photos to photos by date, videos to videos by date, media with no capture
time to missing metadata, and every file of no media class to the strays folder.
:::

:::{rul} Only photos are sorted into photos by destination
:id: RUL-sort_photos_only
:status: seed
:criticality: med
:anti: yes
:verify: required
:aliases: loop-sort-photo-only-1
:uses: DEF-operator_loop, DEF-managed_folders

Photos by destination SHALL hold only photos: videos stay in videos by date, and no file of no media class belongs there.
Geotag SHALL refuse to run while it holds anything else.
:::

:::{rul} Prep records every sort before geotag plans
:id: RUL-prep_records_sort
:status: seed
:criticality: high
:anti: yes
:verify: required
:aliases: loop-reprep-mandatory-1, loop-no-behind-preps-back-1
:uses: DEF-operator_loop, DEF-prep, DEF-geotag

Geotag SHALL NOT plan while photos by destination holds a photo prep has not recorded where it now is. A prep run after
the latest sort SHALL record the moves from the files' sizes and modification times alone, carrying each moved file's
identity forward without reading it again.
:::

:::{rul} Geotag may be re-run until merge
:id: RUL-geotag_rerunnable
:status: seed
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

A geotag re-run SHALL recognise in each file what an earlier run wrote there: a time geotag corrected SHALL NOT be
corrected again, and a position geotag wrote SHALL be derived again and replaced, never kept as the file's own. The
user's decisions, and files already right, it keeps as every run does.
:::

:::{rul} Geotag's gates are the present state, not its history
:id: RUL-geotag_gates
:status: ruled
:criticality: high
:anti: yes
:verify: required
:aliases: loop-geotag-gating-preconditions-1
:uses: DEF-geotag, DEF-managed_folders

Geotag SHALL proceed when, and only when, the workspace now satisfies its gates: photos by date holds no photo; photos by
destination holds only photos and no development subfolder; prep has recorded every photo in it; and the inbox is
empty. Whether, or how often, prep, the sort or geotag ran before SHALL NOT bear on it, so the user may run any number
of prep and sort cycles before geotagging.
:::

:::{rul} A re-run does as much as what changed requires
:id: RUL-rerun_does_what_changed
:status: seed
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
:status: seed
:criticality: med
:verify: required
:uses: DEF-operator_loop, DEF-merge

A new dump SHALL be accepted into the inbox at any point before merge, after a successful geotag too; the loop then
resumes from prep.
:::

:::{rul} Finalize is its own command, and merge requires it
:id: RUL-finalize_explicit
:status: seed
:criticality: med
:anti: yes
:verify: required
:aliases: loop-finalize-before-merge-1, archive-finalize-explicit-1
:uses: DEF-finalize, DEF-merge

Finalize SHALL be a command of its own, never a side effect of geotag's execution. Merge SHALL refuse a workspace that
has not been finalized.
:::

:::{rul} Merge takes only the finalized, current set
:id: RUL-merge_takes_finalized_current
:status: seed
:criticality: high
:anti: yes
:verify: required
:aliases: merge-preconditions-finalized-1, merge-revalidates-current-1
:uses: DEF-finalize, DEF-merge, DEF-managed_folders

Merge SHALL require that geotag's execution succeeded and the workspace was finalized, and SHALL refuse when photos by
destination has changed since finalize — so what reaches the library is always the corrected, named, fully recorded
set. A refresh that changes only what describes a prep run SHALL NOT count as a change.
:::

:::{rul} Merge ends the workspace
:id: RUL-merge_is_terminal
:status: seed
:criticality: high
:anti: yes
:verify: required
:uses: DEF-merge, DEF-workspace

Merge SHALL be the last phase run in a workspace: once it succeeds, more media SHALL go to a fresh workspace, and the
library SHALL accept merges from many workspaces.
:::

:::{rul} Development happens in the library, after merge
:id: RUL-development_after_merge
:status: ruled
:criticality: high
:anti: yes
:verify: required
:aliases: loop-dev-before-geotag-blocks-1
:uses: DEF-development, DEF-managed_folders

Development SHALL happen in the library, after merge. A development subfolder anywhere in photos by destination —
even an empty one — SHALL stop geotag's planning, execution and finalize, and merge.
:::

## 10. Change only what needs changing

:::{inv} A run changes only what its inputs require
:id: INV-change_only_what_needs
:status: ruled
:criticality: high
:anti: yes
:verify: incidental
:uses: DEF-prep, DEF-geotag, DEF-merge

Every phase SHALL change only what its inputs actually require, as far as the work allows: no phase SHALL redo settled
work to be safe, and none SHALL leave a file in a state other than its inputs require.
:::

:::{rul} Valid work is reused
:id: RUL-reuse_valid_work
:status: seed
:criticality: med
:verify: required
:aliases: idem-reuse-not-recompute-1
:refines: INV-change_only_what_needs

Work already done and still valid SHALL be reused, not repeated: a file's content and metadata SHALL be read, and the
tracks parsed, only for inputs that are new or have changed.
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

When an input changes, only the records that depend on it SHALL be made again; every other record SHALL be left as it
is.
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
the run requires of it. A file already in its place, with its name and its metadata, SHALL produce no operation.
:::

:::{rul} A run over unchanged inputs changes nothing
:id: RUL-no_op_run
:status: ruled
:criticality: med
:verify: required
:aliases: idem-no-op-run-1
:refines: INV-change_only_what_needs

A phase run over a workspace whose relevant state has not changed SHALL change nothing, and SHALL produce the same result
— the same operations, fingerprints and names. It SHALL report the work it reused and the files already right, and SHALL
NOT treat earlier work as an error.
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
inputs — never from a choice the tool makes on its own. An execution SHALL act only on a plan made from those.
:::

:::{rul} The user writes the decisions; the tool lays out their fields
:id: RUL-user_writes_decisions
:status: ruled
:criticality: high
:anti: yes
:verify: required
:aliases: authored-fields-not-overwritten-1
:uses: DEF-decision, RUL-decision_kept

A decision field SHALL be written by the user alone, and no phase SHALL overwrite what the user wrote. A phase SHALL
create every field a decision needs, so the user fills in values, never structure.
:::

:::{rul} Prep takes no decision
:id: RUL-prep_takes_no_decision
:status: ruled
:criticality: med
:verify: required
:uses: DEF-prep

Prep SHALL ask the user for no decision: it SHALL organize from the state of the workspace and its configuration alone.
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

A decision SHALL be revised by changing it in the record and running again: the change SHALL reach everything that
depends on it, and no change the tool makes SHALL be irreversible at the level of the decisions. A wrong choice SHALL
never need the mutated files repaired by hand.
:::

:::{rul} Withdrawing a decision undoes it
:id: RUL-withdrawal_undoes
:status: ruled
:criticality: med
:verify: required
:aliases: authored-withdraw-undoes-1
:refines: RUL-decision_revisable

Withdrawing a decision SHALL undo its effect, not merely stop asserting it. A manual position withdrawn SHALL give the
file back the position it held before, or none if it held none; a position derived by the tool SHALL be derived again; a
time and a name SHALL be recomputed where the file stands, never moving it out of its destination.
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
to its files so far: whole whether or not any later phase ever runs, and extended by each phase through its own work. A
phase not yet run SHALL read as the workspace not having advanced, never as a record incomplete.
:::

:::{rul} Each phase writes only its own records
:id: RUL-phase_writes_own_records
:status: ruled
:criticality: high
:anti: yes
:verify: required
:aliases: archive-artifact-ownership-1
:uses: DEF-control_records

Each numbered record SHALL be written by the phase whose number it carries, and by no other. A phase MAY create,
rewrite or extend its own records across its runs; it SHALL read every other phase's records read-only.
:::

:::{rul} An earlier record is carried forward by copying it
:id: RUL-carry_forward_by_copy
:status: ruled
:criticality: high
:anti: yes
:verify: required
:aliases: archive-no-cross-phase-write-1
:refines: RUL-phase_writes_own_records

To carry an earlier phase's record forward, a phase SHALL copy it to a record of its own and extend the copy, leaving
the earlier one untouched; it SHALL NOT derive an earlier phase's history again.
:::

:::{rul} Finalize only reads and records
:id: RUL-finalize_non_destructive
:status: ruled
:criticality: med
:anti: yes
:verify: required
:aliases: archive-finalize-nondestructive-1
:uses: DEF-finalize, DEF-archival_package

Finalize SHALL change nothing in the workspace's media, its other records or the library: it SHALL read the record that
already stands at the end of geotag and write the package from it.
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
them; each phase SHALL only append its own steps, never rewrite an earlier one. The latest phase's log SHALL be the full
record; each earlier log stays its own phase's.
:::

:::{rul} The log is keyed by fingerprint
:id: RUL-log_keyed_by_fingerprint
:status: ruled
:criticality: med
:verify: required
:aliases: log-keyed-by-fingerprint-1
:uses: DEF-transformation_log, DEF-fingerprint

The log SHALL key each photo's entry by its fingerprint and carry the chain of names and places it passed through. A
file of no media class SHALL have no entry.
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

A phase whose kept history cannot rebuild a photo's journey through it SHALL fail, or mark its record plainly partial;
it SHALL NOT write a log that looks whole but reflects only the last run.
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

A workspace SHALL hold exactly one database of record, and the library none. Any other database a phase keeps SHALL be
scratch: holding no decision and no history, safe to delete at any time, and neither journalled nor archived.
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

Each phase SHALL write only its own part of the workspace database; no two phases SHALL write the same rows. Finalize
SHALL only read it.
:::

:::{rul} Each phase keeps an image of the database at its end
:id: RUL-database_image_each_phase
:status: ruled
:criticality: med
:verify: required
:aliases: db-snapshot-per-phase-1, db-snapshot-skip-on-failure-1
:uses: DEF-database_image, DEF-archival_package

Each phase SHALL keep its database image, refreshed by each of its successful runs and left untouched by every other
phase; a run that does not succeed SHALL leave the image as it was. An image SHALL never be read back as working data,
and every image present SHALL be archived in the package.
:::

:::{rul} An image is whole
:id: RUL-database_image_whole
:status: ruled
:criticality: med
:anti: yes
:verify: required
:aliases: db-snapshot-consistent-1, db-snapshot-atomic-replace-1
:uses: DEF-database_image

A database image SHALL be a consistent state of the database, never a copy torn mid-transaction; an interrupted
capture SHALL leave the earlier image or the new one, whole.
:::

## 13. Merge: the library kept, the workspace sealed

:::{def} A sealed workspace
:id: DEF-sealed_workspace
:status: seed
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

Merge SHALL never rename, overwrite, move, delete or change a file already in the library; where an incoming photo's
place is taken, the incoming photo SHALL give way.
:::

:::{rul} Merge reads the library only where it places a photo
:id: RUL-library_not_scanned
:status: seed
:criticality: med
:anti: yes
:verify: required
:uses: DEF-merge, DEF-library

Merge SHALL touch the library only at the places its photos go, and read a library file only when one is already
there. It SHALL NOT scan, index or de-duplicate the library.
:::

:::{rul} A taken place is settled by content
:id: RUL-collision_by_content
:status: seed
:criticality: high
:verify: required
:aliases: merge-collision-same-content-1, merge-collision-diff-content-1
:uses: DEF-merge, DEF-library, DEF-fingerprint
:refines: RUL-library_never_altered

Where an incoming photo's place in the library is taken, merge SHALL compare the two by fingerprint. The same content
SHALL mean the photo is already in the library: nothing is written there, and the workspace's copy is removed. Different
content SHALL mean two photos share a name: the incoming one is placed under a differentiating name.
:::

:::{rul} A library file is read at most once while unchanged
:id: RUL-library_file_read_once
:status: seed
:criticality: low
:verify: required
:aliases: merge-fingerprint-cached-onfly-1
:uses: DEF-library, DEF-fingerprint, DEF-workspace_database

A library file's fingerprint SHALL be computed only when a collision needs it, and kept, so that a library file
unchanged since is never fingerprinted again in the workspace, in that run or a later one.
:::

:::{rul} Merge moves, and a photo leaves the workspace only once safe in the library
:id: RUL-merge_moves
:status: seed
:criticality: high
:anti: yes
:verify: required
:aliases: merge-move-leaves-bydest-empty-1, merge-move-atomic-source-last-1, merge-blocker-left-in-bydest-1
:uses: DEF-merge, DEF-library, DEF-managed_folders

Merge SHALL move each photo it places: the workspace's copy SHALL be removed only once the library's is verified in
place, and a photo already in the library SHALL be removed likewise. A photo merge cannot place SHALL stay where it is,
the run then partial.
:::

:::{rul} Merge resumes, and a merged batch is a no-op
:id: RUL-merge_resumable
:status: seed
:criticality: med
:verify: required
:aliases: merge-idempotent-resumable-1
:uses: DEF-merge
:refines: RUL-no_op_run

A merge interrupted SHALL be finished by running it again, which SHALL apply only what is outstanding; merging a batch
already merged SHALL change nothing.
:::

:::{rul} Merge records where every photo landed
:id: RUL-merge_records_landing
:status: seed
:criticality: low
:verify: required
:aliases: merge-records-summary-1
:uses: DEF-merge, DEF-transformation_log
:refines: RUL-phase_writes_own_records

Merge SHALL record, in its own records, where each photo landed in the library, whether it was renamed there, which
were already present, and what blocked the rest. Nothing SHALL be built from merge's records.
:::

:::{rul} Merge remakes the package as part of its run
:id: RUL-merge_reseals
:status: seed
:criticality: med
:verify: required
:aliases: merge-reseals-automatically-1, merge-reseal-no-rederive-1
:uses: DEF-merge, DEF-archival_package

A merge that succeeds SHALL remake the archival package to hold its own records too, as part of the same run and with
no command of its own, from the records as they stand: it SHALL re-derive nothing of an earlier phase.
:::

:::{rul} Only a whole merge seals
:id: RUL-seal_on_success_only
:status: seed
:criticality: high
:anti: yes
:verify: required
:aliases: seal-success-then-sealed-1, seal-partial-writes-no-marker-1
:uses: DEF-sealed_workspace, DEF-merge

Merge SHALL seal the workspace only when it succeeds whole: every photo by destination placed in the library or found
already there, none left. A partial, failed or interrupted merge SHALL leave the workspace unsealed.
:::

:::{rul} The seal alone says a workspace is finished
:id: RUL-seal_is_authority
:status: seed
:criticality: med
:anti: yes
:verify: required
:aliases: seal-marker-is-authority-1, seal-marker-separate-file-1
:uses: DEF-sealed_workspace, DEF-managed_folders

Whether a workspace is finished SHALL be read from its seal alone, never from the state of its folders.
:::

:::{rul} A sealed workspace is never processed again
:id: RUL-sealed_refuses
:status: seed
:criticality: high
:anti: yes
:verify: required
:aliases: seal-scripts-hardstop-1, edit-sealed-refuses-1
:uses: DEF-sealed_workspace, DEF-decision
:refines: RUL-merge_is_terminal

In a sealed workspace prep, geotag and merge SHALL stop as they start, changing and touching nothing, and the decision
editor SHALL neither open it nor save into it; nor SHALL merge's library setup record a library in its configuration.
Its records MAY still be read.
:::

:::{rul} Pruning the quarantine is still allowed
:id: RUL-sealed_prune_allowed
:status: seed
:criticality: high
:verify: required
:aliases: seal-prune-exception-1
:uses: DEF-sealed_workspace
:refines: RUL-sealed_refuses

Pruning the quarantine SHALL remain allowed in a sealed workspace, and SHALL be the only change allowed there.
:::

:::{rul} A new dump in a sealed workspace is pointed out and left
:id: RUL-sealed_new_dump_warned
:status: seed
:criticality: med
:anti: yes
:verify: required
:aliases: seal-new-dump-warn-1
:uses: DEF-sealed_workspace
:refines: RUL-sealed_refuses

A command refusing a sealed workspace that finds files where a dump would land — the workspace's top level or the
inbox — SHALL say that a new dump is likely there and must go to a fresh workspace, and SHALL leave it exactly where it
is.
:::
