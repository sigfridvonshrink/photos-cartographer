# Shared — why

**Not normative.** Each item here is the reasoning behind the [intent](../intent/shared.md) or [build](../build/shared.md)
items it `justifies`, under the same section numbers. Where the two differ, the intent wins and this is stale.

## 1. One run at a time

:::{rat} A plan made beside another run cannot be trusted
:id: RAT-planning_inside_lock
:status: seed
:justifies: RUL-lock_before_reading

Planning is non-mutating, but it must still not run concurrently: a plan computed against a workspace another process
is reading or mutating is untrustworthy, so planning is inside the lock too.
:::

:::{rat} The lock and revalidation guard different things
:id: RAT-lock_and_revalidation
:status: seed
:justifies: INV-one_run_at_a_time

This whole-run lock is independent of, and stricter than, the dependency-revalidation discipline: revalidation guards
against *stale* inputs across separate runs, while the lock guarantees runs never overlap in the first place.
:::

## 2. A snapshot before changing, optionally

:::{rat} A snapshot is an extra layer, not the safety model
:id: RAT-snapshot_is_extra
:status: seed
:justifies: RUL-snapshot_optional, RUL-unrequired_snapshot_proceeds

**Snapshots are an optional extra safety layer, not a requirement.** The pipeline operates fully and safely without
them: correctness and recoverability rest on the journal, recoverable quarantine, no-clobber operations, and
filesystem-as-truth reconciliation. Snapshots add a clean-slate rollback path on top of those for operators whose
filesystem supports it; they are not the basis of the safety model.
:::

:::{rat} Why the snapshot alone may touch the filesystem
:id: RAT-one_filesystem_specific_part
:status: seed
:justifies: RUL-filesystem_agnostic, BLD-snapshot_is_zfs

The mechanism is named for ZFS because that is the reference implementation, but it is deliberately the *only* part
of the pipeline that touches a specific filesystem feature, and it is optional; everything else is filesystem-agnostic.
:::

:::{rat} One mechanism, so the phases cannot diverge
:id: RAT-one_snapshot_mechanism
:status: seed
:justifies: BLD-one_snapshot_mechanism

Each phase that mutates uses the same mechanism so the phases behave identically and cannot diverge.
:::

## 3. One configuration, kept in the workspace

:::{rat} A configuration in a file is bound to what it governed
:id: RAT-config_is_a_file
:status: seed
:justifies: DEF-configuration, RUL-config_in_dependencies, RUL-config_archived

Making the config a file binds it intrinsically to the workspace and to everything processed in it. Hashed and folded
into the dependency cascade, it closes the gap where an ambient config could change a run without leaving a trace; and
archived, it lets a future reader know not only what was decided but **under what configuration**.
:::

:::{rat} Surgical staleness: one hash for everything would restale everything
:id: RAT-surgical_staleness
:status: seed
:justifies: RUL-staleness_by_area

Collapsing all staleness to a single whole-file hash would needlessly restale unrelated artifacts on any edit, and is
explicitly not done.
:::

:::{rat} A coarse trigger for the cheap plan, a precise one for the costly caches
:id: RAT-coarse_trigger_for_the_cheap_plan
:status: seed
:justifies: RUL-any_config_change_replans, RUL-costly_results_survive_unrelated_edits

The whole-file fingerprint restaling the plan is a catch-all guaranteeing no config-driven change is ever silently
missed, even one in an area without its own field-scoped fingerprint. It is intentional belt-and-braces *alongside* the
field-scoped fingerprints, not a contradiction of surgical staleness: they keep the **expensive** derived caches from
restaling on unrelated edits, while the **cheap-to-rebuild** plan simply re-plans on any config change. What surgical
staleness rules out is collapsing the *surgical* caches onto the whole-file hash; using that hash as an additional
coarse trigger for a cheap artifact is consistent with — indeed protective of — surgical staleness.
:::

:::{rat} Folder names and media classes decide which files exist where
:id: RAT-organization_decides_where_files_are
:status: seed
:justifies: RUL-organization_settings_restale, BLD-prep_guards_with_the_whole_hash

Geotag's and merge's plans locate the destination tree by name and classify the tree, and renaming a managed folder or
moving an extension between media and `other` changes which files exist where. Prep re-plans from the filesystem each
run and guards execution with the whole-file hash, so it needs no separate folder or extension fingerprint of its own.
:::

:::{rat} A folder's role is pipeline logic
:id: RAT-folder_roles_are_logic
:status: seed
:justifies: RUL-folder_names_not_roles

The roles — the inbox, the read-only destination tree, the order in which duplicates are retained, which folders are
the photo and video bands — are pipeline logic, so the user sets the names and never the roles.
:::

:::{rat} The derivation's version must stay the code's
:id: RAT-derivation_version_is_code
:status: seed
:justifies: RUL-camera_classes_not_derivation

The version of the camera-group derivation takes part in the dependency fingerprints, so a change to the derivation is
detectable; it versions the code that computes the key, so only the code can set it.
:::
