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
:aliases: handoff-runonly-refresh-no-restale-1
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
