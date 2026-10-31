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
:status: seed
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
:status: seed
:criticality: med
:verify: required
:aliases: config-wholehash-coarse-replan-1

Any change to the configuration, in whatever area, SHALL make geotag's executable plan stale, and SHALL stop prep from
executing a plan made before it.
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
