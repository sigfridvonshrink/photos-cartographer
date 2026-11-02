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

## 5. Camera groups, derived once

:::{rat} Grouping computed once is never reinvented
:id: RAT-grouping_computed_once
:status: seed
:justifies: RUL-prep_derives_camera_group, RUL-geotag_reuses_camera_group

One derived key identifies a camera or device so that grouping is computed once, by prep, and reused by geotag — never
reinvented.
:::

## 6. One filename format

:::{rat} One key, so the names cannot drift apart
:id: RAT-one_format_no_drift
:status: seed
:justifies: RUL-one_filename_format

With one format key for the whole pipeline, the provisional names prep assigns and the final names geotag assigns are
guaranteed to share the same textual shape and can never drift apart; there is no format divergence to reconcile.
:::

:::{rat} The same shape, a different value, on purpose
:id: RAT-same_shape_different_value
:status: seed
:justifies: RUL-prep_name_provisional, RUL-geotag_name_final, RUL-uncorrected_keeps_its_name

Both phases use the same format, but the **value** differs by phase and that difference is intentional. Because the
shape is identical, a file's name changes between phases only when its timestamp is genuinely corrected; an uncorrected
file's provisional and final names coincide, so geotag plans no needless rename for it.
:::

:::{rat} The first free name makes the two names coincide
:id: RAT-bare_first
:status: seed
:justifies: RUL-suffix_choice_by_phase, RUL-uncorrected_keeps_its_name

Bare-first is what makes an uncorrected file's provisional (prep) and final (geotag) names coincide, so geotag plans no
needless rename; the two phases use the identical rule so they never disagree on a name.
:::

:::{rat} The library is append-only
:id: RAT-merge_appends
:status: seed
:justifies: RUL-suffix_choice_by_phase

Merge appends at `max+1` rather than reusing a freed-up lower number because the library is append-only and a re-run
must reproduce the same name.
:::

## 7. The tracks, kept outside the managed folders

:::{rat} Where the tracks live is what keeps them geotag's
:id: RAT-tracks_kept_outside
:status: seed
:justifies: RUL-tracks_outside_managed_folders, RUL-tracks_geotag_only

The shared rule that makes it safe for geotag alone to own the tracks is where they live. Kept outside the managed
folders, prep's normal scan never encounters them, so they can never be taken for files of no media class, or swept
into the inbox and organized.
:::

:::{rat} A track among the strays could be deleted with them
:id: RAT-tracks_never_strays
:status: seed
:justifies: RUL-track_files_block_prep

Parked among the strays, a track could be deleted when the strays are cleared in bulk, and a lost track is evidence no
re-run can recover. Refusing to run leaves it where the user put it until they move it to the tracks' location.
:::

## 8. Nothing used once what it came from has changed

:::{rat} One source for each shared fact
:id: RAT-one_source_per_fact
:status: seed
:justifies: INV-no_stale_use

The facts the dependencies are built from — the configuration, the control records, the camera-group derivation's
version, the filename format, the tracks, the snapshot mechanism — are each defined once, for every phase, so that a
single change has one authoritative source and a predictable staleness footprint everywhere.
:::

:::{rat} Opposite jobs, so different names
:id: RAT-fingerprint_and_hash_opposite_jobs
:status: seed
:justifies: DEF-fingerprint, DEF-hash

The two words name a value by the role it plays, not by the algorithm underneath, and the two roles are opposite: one
must be invariant under mutation, the other sensitive to it. They keep different names even though a fingerprint is
itself computed with a hash function.
:::

:::{rat} A file's identity outlives its edits
:id: RAT-identity_survives_edits
:status: seed
:justifies: RUL-fingerprint_survives_mutation

A fingerprint is chosen precisely so it stays the same when the pipeline rewrites a photo's metadata or position or
renames the file: a media file's identity must survive those mutations, which is what makes it the identity spine the
transformation log and de-duplication rely on.
:::

:::{rat} Detecting change is a hash's whole purpose
:id: RAT-hash_is_for_change
:status: seed
:justifies: RUL-hash_detects_any_change

A hash is chosen precisely so it changes on any byte change: detecting change is its whole purpose, which is what makes
it the right dependency check for records.
:::

## 9. One loop across the phases

:::{rat} A steady state to return to
:id: RAT-loop_is_steady_state
:status: seed
:justifies: RUL-geotag_gates, RUL-more_dumps_until_merge

The loop is a steady state to return to, not a one-way pipeline: a batch can be imported, sorted, and followed by
another before anything is geotagged. A phase that judged by what ran before would have to forbid that; one that judges
the present state need not.
:::

:::{rat} Bounded by what is true now, not by a flag
:id: RAT-gates_not_history
:status: seed
:justifies: RUL-geotag_gates, RUL-geotag_rerunnable

What bounds geotag's freedom is a small, fixed set of conditions on the workspace, not a "has geotag run before?" flag.
Each gate names a state geotag cannot work correctly from; none says anything about history.
:::

:::{rat} Re-running is safe because nothing settled is redone
:id: RAT-rerun_is_safe
:status: seed
:justifies: RUL-geotag_rerunnable
:follows_from: RUL-geotag_rerun_keeps_settled

Geotag can be re-run freely because a re-run redoes nothing settled: the user's decisions live in geotag's records and
survive their regeneration, what geotag wrote into a file is recognised there, so a corrected time is never corrected
twice and photos added later are corrected beside it, and a name computed from the destination's local time comes out
the same.
:::

:::{rat} The file carries the record of what geotag did
:id: RAT-mark_in_the_file
:status: ruled
:justifies: RUL-geotag_rerun_keeps_settled

What geotag did to a photo is marked in the photo itself rather than kept only in the workspace: the mark survives the
workspace, reaches the library, and is read back wherever the photo turns up again, so a photo corrected once is
recognised as corrected whichever workspace it is in.
:::

:::{rat} New photos never reach geotag behind prep's back
:id: RAT-never_behind_prep
:status: seed
:justifies: RUL-prep_records_sort

Geotag depends on prep's handoff, and a photo prep has not recorded is not in it. Re-prepping after every sort, even
after geotag has run, keeps the handoff the whole truth about photos by destination.
:::

:::{rat} Safe is not frictionless
:id: RAT-rerun_not_frictionless
:status: seed
:justifies: RUL-rerun_does_what_changed

"Freely re-runnable" does not mean "always a no-op". Any change upstream — not only new media — restales exactly what
depends on it, and may raise new questions about the items it touches; a re-run does that work and no more.
:::

:::{rat} Finalize stays apart because geotag is re-run
:id: RAT-finalize_apart
:status: seed
:justifies: RUL-finalize_explicit

Geotag is re-run freely, and assembling the permanent record on each pass would be wasted work. Finalize marks the one
moment the user declares the dump done.
:::

:::{rat} Never a half-geotagged set in the library
:id: RAT-merge_never_half_done
:status: seed
:justifies: RUL-merge_takes_finalized_current

Finalize is a point in time, and photos by destination can change after it. Merge checks the finalized set against the
present one rather than trusting finalize was last, so a half-geotagged set cannot reach the library.
:::

:::{rat} A merged workspace is not a clean slate
:id: RAT-workspace_not_recycled
:status: seed
:justifies: RUL-merge_is_terminal

Even with photos by destination empty, a merged workspace keeps its database, ledgers, caches, snapshots and sealed
record. Starting afresh keeps each workspace's record about one batch.
:::

:::{rat} Corrections would invalidate development
:id: RAT-development_after_corrections
:status: seed
:justifies: RUL-development_after_merge

Distribution copies made before geotag's time and position corrections would be made from uncorrected photos, and the
corrections would invalidate them. Nor is the workspace a place for processing image files at all: that work belongs
to the library. A development folder's presence alone is the signal; nothing guesses whether it really holds output.
:::

## 10. Change only what needs changing

:::{rat} Redoing settled work buys no safety
:id: RAT-no_redo_to_be_safe
:status: ruled
:justifies: INV-change_only_what_needs

Settled work done again "to be safe" makes nothing safer: a file written with what it already holds gains nothing and
risks a failed write, and reading a library's content again can cost hours.
:::

:::{rat} One principle, stated once
:id: RAT-one_idempotency_principle
:status: seed
:justifies: INV-change_only_what_needs

The three phases share one sense of idempotency, stated once for all of them; each phase states only what it means in
its own terms, so the principle cannot drift between them.
:::

## 11. Nothing changes that the user did not write down

:::{rat} A user who distrusts opaque mutation can always ask why
:id: RAT-why_did_this_change
:status: ruled
:justifies: INV-every_change_from_the_record, RUL-cause_locatable, RUL-decision_revisable

For irreplaceable photos, a user who distrusts opaque, automatic change must always be able to answer *why did this
change happen?* — and to change the answer. So the tool proposes and the user decides, the decision stays in a durable
record that the change can be traced back to, and revising the record revises the result.
:::

:::{rat} A time and a name are recomputed, not reverted
:id: RAT-time_name_recomputed
:status: ruled
:justifies: RUL-withdrawal_undoes

A file's time and name are not rolled back when a decision is withdrawn but recomputed in place: reverting them would
un-position a file the user has already organized.
:::

:::{rat} One principle, stated once
:id: RAT-one_authorship_principle
:status: ruled
:justifies: INV-every_change_from_the_record

The three phases share one stance on authorship, stated once; each phase states only how it meets it.
:::

## 12. The record of what was done, kept beyond the workspace

:::{rat} The workspace is transient; the record must not be
:id: RAT-record_outlives_workspace
:status: ruled
:justifies: RUL-record_whole_each_phase

The decisions drive a run, but their lasting value is as the record of what was done to the archive and why — and the
workspace is transient: it is merged and set aside, or set aside at any phase boundary without ever advancing. Decisions
are kept for the future only if preserved beyond it, in one known place, rather than scattered in per-file sidecars or,
as with tools that change files and forget, not recorded at all. Since a workspace may stop at any phase, the record
must be whole at each.
:::

:::{rat} A record no later phase can silently alter
:id: RAT-records_attributable
:status: ruled
:justifies: RUL-phase_writes_own_records, RUL-carry_forward_by_copy

With each phase writing only its own records and carrying earlier ones forward by copy, every phase's output stays a
stable record attributable to it, which no later phase can silently change: complete at its boundary, and evident if
tampered with by what came after. That is why the log is three files, one per phase, not one changed in place. And a
phase that copies its predecessor's record, rather than deriving that history again from other sources, keeps one
account of each phase: a second, rebuilt account could disagree with the first.
:::

:::{rat} A name cannot key the log
:id: RAT-names_cannot_key_the_log
:status: ruled
:justifies: RUL-log_keyed_by_fingerprint

A photo is renamed up to twice in the workspace — a provisional name, then its final one — and may be renamed again on
its way into the library, so no name identifies it across its journey. Its fingerprint does: it survives every rename,
move and metadata write the pipeline makes.
:::

:::{rat} Retention serves the log, nothing more
:id: RAT-retention_serves_the_log
:status: ruled
:justifies: RUL-history_retained, RUL-partial_history_shown

A journey spans many runs — prep, re-prep after moves, repeated geotag passes, merge — so a log rebuilt from the last
run alone would silently lose the rest. What is kept exists to serve the log, and resuming and auditing; it is not an
open-ended store of events.
:::

:::{rat} The database holds what the record cannot rebuild
:id: RAT-database_is_record
:status: ruled
:justifies: RUL-database_is_record, RUL-one_database

The database is not only a cache that makes re-runs cheap: it holds what nothing else does — the values a photo held
before geotag first changed it, which let any change be undone, and each photo's identity across its moves. Discarded
with the workspace, that knowledge would be lost; kept in two places, the two could disagree. The library keeps no
database because it is the user's own collection, organised as they choose, and merge only adds to it.
:::

:::{rat} A database shows only now
:id: RAT-database_shows_only_now
:status: ruled
:justifies: RUL-database_image_each_phase

The live database is one file that every phase changes, so at any moment it shows only the latest state: what prep
knew is overwritten by what geotag learned. An image taken at each phase's end keeps the database's state at every
boundary, to be opened later and compared.
:::

:::{rat} An image is regenerable; a photo is not
:id: RAT-image_replaced_not_kept
:status: ruled
:justifies: RUL-database_image_each_phase, RUL-database_image_whole

Never overwriting guards photos, which cannot be made again. An image can: it is a copy of the live database, and only
the latest end of each phase is worth keeping, so a phase's next successful run replaces its image — whole, so that a
capture interrupted leaves a usable image either way.
:::

## 13. Merge: the library kept, the workspace sealed

:::{rat} The library is the user's, and already in order
:id: RAT-library_is_ground_truth
:status: seed
:justifies: RUL-library_never_altered, RUL-library_not_scanned, RUL-collision_by_content

The library is the user's curated collection: its organisation and names are the ground truth, and other tools and
people rely on them. So merge adds to it and changes nothing in it, and assumes it is in order rather than scanning it:
scanning a whole library to place one batch would cost far more than it saves. Where a name is taken, only the content
tells a copy already present from a different photo sharing a name.
:::

:::{rat} A library file costs a full read
:id: RAT-library_reads_cost
:status: seed
:justifies: RUL-library_file_read_once

Fingerprinting a library file means reading and decoding it whole, and the library may sit across a network. Kept in the workspace, a
fingerprint already taken spares that read on the next run, and stays right while the file is unchanged.
:::

:::{rat} The workspace keeps only what still needs attention
:id: RAT-move_not_copy
:status: seed
:justifies: RUL-merge_moves, RUL-merge_resumable

A copy left in the workspace of a photo already in the library is a duplicate that invites confusion and wastes space,
so merge moves rather than copies, and removes a copy whose content the library already holds. What stays behind is
exactly what still needs attention. Removing the workspace's copy last, once the library's is verified, means an
interruption never loses a photo: running merge again finishes the work.
:::

:::{rat} Merge is the end, so the package is remade at once
:id: RAT-reseal_automatic
:status: seed
:justifies: RUL-merge_reseals

Merge adds to the record finalize packaged, so that package no longer describes the whole journey. Since merge is the
workspace's last act, remaking the package once at its end is what the user always wants. Finalize stays its own
command because geotag is freely re-run, and re-packaging after every pass would be wasted.
:::

:::{rat} An empty folder means two things; a mark means one
:id: RAT-seal_not_folder_state
:status: seed
:justifies: RUL-seal_is_authority, RUL-seal_on_success_only

Photos by destination is empty both in a workspace just sorted and in one merged and finished, so its state cannot say
which a workspace is. A mark written only when merge succeeds whole can — and a merge that left a photo behind writes
none, so it can be finished by running it again.
:::

:::{rat} A finished workspace is read, not reprocessed
:id: RAT-sealed_is_final
:status: seed
:justifies: RUL-sealed_refuses, RUL-sealed_new_dump_warned

A second batch processed in a merged workspace would interleave with the first's database, logs and package, and its
record would no longer describe one dump. So nothing that could change it runs; the records stay readable; and a dump
dropped there is left untouched and pointed out, for the user to move to a fresh workspace by hand — safer than any
automated move inside a finished workspace.
:::

:::{rat} Pruning the quarantine changes nothing controlled
:id: RAT-prune_harms_nothing
:status: seed
:justifies: RUL-sealed_prune_allowed

The quarantine holds only spare copies of duplicates, which a sealed workspace still keeps. Deleting them touches no
photo, library file, record or row of the database, and neither reprocesses the workspace nor adds a batch to it, so
the seal's reasons do not reach it, and the space can be reclaimed.
:::
