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

## 4. The control records, apart from the media

:::{rat} One skipped place instead of a list of names
:id: RAT-one_skipped_place
:status: seed
:justifies: RUL-control_records_together, RUL-control_records_never_media

Skipping the control directory wholesale means a control or artifact file can never be mistaken for a photo. There is
no per-file "ignore list" to maintain — consolidating everything in one skipped directory replaces the basename
registry that earlier designs needed.
:::

:::{rat} A dump leaves no hidden litter
:id: RAT-no_hidden_litter
:status: seed
:justifies: RUL-dump_hidden_files_quarantined

Hidden dotfiles are swept to the recoverable quarantine, not merely skipped, so a dump leaves no hidden litter.
:::

:::{rat} The dry run reads the persisted plan
:id: RAT-dry_run_reads_the_saved_plan
:status: seed
:justifies: RUL-dry_run_summarises_the_real_plan

Because the full plan is a persisted artifact, the dry run reports on the on-disk plan — still not a simulation.
:::

:::{rat} A superseded plan stays recoverable; an unchanged one adds nothing
:id: RAT-superseded_plans_recoverable
:status: seed
:justifies: RUL-replanning_keeps_the_prior, RUL-unchanged_replan_writes_nothing

Setting the prior artifact aside keeps a superseded plan and any authored decisions recoverable; writing nothing on an
unchanged re-run means the iterative decision-editing loop does not accumulate redundant backups.
:::

:::{rat} The handoff is invisible to the scan, yet verified
:id: RAT-handoff_by_content
:status: seed
:justifies: RUL-handoff_verified_by_content, RUL-run_only_refresh_restales_nothing

Living in the skipped directory is independent of the handoff's role as a dependency: it is invisible to prep's media
scan yet fully verified as a dependency by geotag — verified by content, not by exact bytes, so a run-only refresh of
it does not restale downstream.
:::

:::{rat} Every phase relies on the shape when it scans
:id: RAT-phases_rely_on_the_shape
:status: seed
:justifies: INV-undisturbed_shape, RUL-shape_checked_first

The structural facts are shared by every phase because each relies on them when it scans, and a violation of any one
means the workspace was disturbed out-of-band. The guards compose with — but are distinct from — input validation, which
checks *authored values*, and the dependency cascade, which checks *change*: these check the *shape of the workspace
itself*.
:::

:::{rat} A followed link escapes the managed tree
:id: RAT-a_link_escapes_the_tree
:status: seed
:justifies: RUL-no_links

Following a symbolic link would let a planned read or write reach a target **outside** the managed tree — a pipeline
escape that breaks the no-clobber and "originals never lost" guarantees and the closed-world assumption the content
fingerprint and de-duplication rest on.
:::

:::{rat} Prep is the gatekeeper for links under the destination tree
:id: RAT-prep_gatekeeps_links
:status: seed
:justifies: RUL-who_checks_for_links

The destination tree is read-only for prep yet still scanned by it, so prep is also the gatekeeper for links that
appear there; and the mandatory re-prep after any change to it means geotag and merge only ever consume a handoff prep
built with no forbidden link present.
:::

:::{rat} A rebuilt structure could mask a loss
:id: RAT-rebuild_masks_loss
:status: seed
:justifies: RUL-missing_folder_blocks, RUL-structure_built_once

Since prep creates the structure once and never removes a folder, a missing one is evidence the structure was deleted
or moved out-of-band — not a state any phase produces. Silently rebuilding it could mask a real loss: a deleted folder
may have taken organized media with it. Recovering lost media — from an optional pre-mutation snapshot, say — is the
operator's task.
:::
