# Shared — why

**Not normative.** Each item here is the reasoning behind the [intent](../intent/shared.md) or [build](../build/shared.md)
items it `justifies`, under the same section numbers. Where the two differ, the intent wins and this is stale.

## 1. One run at a time

:::{rat} A plan made beside another run cannot be trusted
:id: RAT-planning_inside_lock
:status: ruled
:justifies: RUL-lock_before_reading

Planning changes nothing but the fingerprints it keeps for later runs, but it must still not run concurrently: a plan
computed against a workspace another process is reading or changing is untrustworthy, so planning is inside the lock too.
:::

:::{rat} The lock and revalidation guard different things
:id: RAT-lock_and_revalidation
:status: ruled
:justifies: INV-one_run_at_a_time

This whole-run lock is independent of, and stricter than, the dependency-revalidation discipline: revalidation guards
against *stale* inputs across separate runs, while the lock guarantees runs never overlap in the first place.
:::

:::{rat} A crash never locks a workspace for good
:id: RAT-crash_never_locks_for_good
:status: ruled
:justifies: RUL-stale_lock_recovered

Runs can die — a power cut, a killed terminal, the system running out of memory — and a dead run cannot release its
lock. Held for good, it would leave the user to find and delete a control file by hand, the one edit the tool otherwise
never asks of them; recognised as stale, it lets the next run go on.
:::

:::{rat} A live lock is never taken
:id: RAT-live_lock_never_taken
:status: ruled
:justifies: RUL-stale_takeover_conservative

Taking over a lock whose owner is still running would let two runs change the same originals at once — the very thing
the lock exists to stop. Leaving a stale lock alone costs a retry; taking a live one could cost photos. So a doubtful
owner counts as alive.
:::

## 2. A snapshot before changing, optionally

:::{rat} A snapshot is an extra layer, not the safety model
:id: RAT-snapshot_is_extra
:status: ruled
:justifies: RUL-snapshot_optional, RUL-unrequired_snapshot_proceeds

**Snapshots are an optional extra safety layer, not a requirement.** The pipeline operates fully and safely without
them: correctness and recoverability rest on the journal, recoverable quarantine, no-clobber operations, and
filesystem-as-truth reconciliation. Snapshots add a clean-slate rollback path on top of those for operators whose
filesystem supports it; they are not the basis of the safety model.
:::

:::{rat} Why the snapshot alone may touch the filesystem
:id: RAT-one_filesystem_specific_part
:status: ruled
:justifies: RUL-filesystem_agnostic, BLD-snapshot_is_zfs

The mechanism is named for ZFS because that is the reference implementation, but it is deliberately the *only* part
of the pipeline that touches a specific filesystem feature, and it is optional; everything else is filesystem-agnostic.
:::

:::{rat} A rollback point is the state just before the change
:id: RAT-snapshot_just_before
:status: ruled
:justifies: RUL-snapshot_timing

A snapshot restores the state just before a plan's changes. Taken before the plan is validated, it may precede a plan
that is then refused; taken outside the lock, another run may change the workspace between it and the first change;
taken after a change, it no longer restores the state before it.
:::

:::{rat} Required means a condition of changing anything
:id: RAT-required_means_condition
:status: ruled
:justifies: RUL-required_snapshot_or_nothing

An operator who requires snapshots has made a rollback point a condition of any change. Going on without one would break
that condition silently, so the run stops before its first change, when stopping costs nothing.
:::

:::{rat} A rollback is chosen by hand, later
:id: RAT-rollback_chosen_by_hand
:status: ruled
:justifies: RUL-snapshot_per_plan

A rollback is done by hand, often long after the run. The snapshot must say which plan's changes it precedes, so the
operator can find the right one and tell the phases' snapshots apart.
:::

:::{rat} A snapshot of the library alone would lose what merge moved
:id: RAT-library_snapshot_alone_loses
:status: ruled
:justifies: RUL-merge_snapshots_library, RUL-no_library_only_snapshot

Merge's changes land in two places: it adds each photo to the library and removes it from the workspace. Rolled back
alone, a snapshot of the library takes the merged photos out of the library while the workspace no longer holds them —
the rollback loses them, a rollback point that destroys what it should protect. A snapshot of the workspace alone is
safe: rolled back, it gives the photos back to the workspace while the library keeps them, a duplicate the next merge
finds already present. So merge snapshots the workspace always, the library beside it where it can, and never the
library alone; with no snapshot of the workspace it takes none at all, and says this merge has no rollback point.
:::

:::{rat} One mechanism, so the phases cannot diverge
:id: RAT-one_snapshot_mechanism
:status: ruled
:justifies: BLD-one_snapshot_mechanism

Each phase that mutates uses the same mechanism so the phases behave identically and cannot diverge.
:::

## 3. One configuration, kept in the workspace

:::{rat} One place for every setting
:id: RAT-one_place_for_settings
:status: ruled
:justifies: RUL-one_configuration

Settings read from more than one place — a phase's own file, an environment variable, the program's defaults — can
disagree, and a run's result would then depend on where it ran, not on the workspace. With one configuration in the
workspace, everything that governed a run is in one file, hashed, checked and archived with what it governed.
:::

:::{rat} A workspace keeps the settings it started with
:id: RAT-workspace_keeps_its_settings
:status: ruled
:justifies: RUL-config_seeded_once, RUL-config_authoritative

A workspace's runs, spread over days or weeks, must all read the settings it was set up with, or a later run could
process the same files differently from an earlier one. The seed defaults belong to the installed program, which may be
upgraded or redeployed meanwhile; so they are copied once into the workspace, where they can be read, edited and
archived, and from then on the copy governs, not the program.
:::

:::{rat} Every change to the configuration is one someone chose
:id: RAT-config_changes_chosen
:status: ruled
:justifies: RUL-config_writers, RUL-library_setup_writes_one_setting

Prep's seeding happens once, before anything is made under the configuration; the user's own edits are the intended way
to change it; the library setup records only the one answer it was asked for. A phase that rewrote the configuration on
its own would change what governs the workspace with nobody having decided it, and restale every plan with no cause the
user can find.
:::

:::{rat} A configuration in a file is bound to what it governed
:id: RAT-config_is_a_file
:status: ruled
:justifies: DEF-configuration, RUL-config_in_dependencies, RUL-config_archived, RUL-config_digest_recorded

Making the config a file binds it intrinsically to the workspace and to everything processed in it. Hashed and folded
into the dependency cascade, it closes the gap where an ambient config could change a run without leaving a trace; and
archived, it lets a future reader know not only what was decided but **under what configuration**.
:::

:::{rat} Surgical staleness: one hash for everything would restale everything
:id: RAT-surgical_staleness
:status: ruled
:justifies: RUL-staleness_by_area

Collapsing all staleness to a single whole-file hash would needlessly restale unrelated artifacts on any edit, and is
explicitly not done.
:::

:::{rat} A coarse trigger for the cheap plan, a precise one for the costly caches
:id: RAT-coarse_trigger_for_the_cheap_plan
:status: ruled
:justifies: RUL-any_config_change_replans, RUL-costly_results_survive_unrelated_edits, RUL-times_survive_unrelated_config_edits

The whole-file fingerprint restaling the plan is a catch-all guaranteeing no config-driven change is ever silently
missed, even one in an area without its own field-scoped fingerprint. It is intentional belt-and-braces *alongside* the
field-scoped fingerprints, not a contradiction of surgical staleness: they keep the **expensive** derived caches from
restaling on unrelated edits, while the **cheap-to-rebuild** plan simply re-plans on any config change. What surgical
staleness rules out is collapsing the *surgical* caches onto the whole-file hash; using that hash as an additional
coarse trigger for a cheap artifact is consistent with — indeed protective of — surgical staleness.
:::

:::{rat} Folder names and media classes decide which files exist where
:id: RAT-organization_decides_where_files_are
:status: ruled
:justifies: RUL-organization_settings_restale, BLD-prep_guards_with_the_whole_hash

Geotag's and merge's plans locate the destination tree by name and classify the tree, and renaming a managed folder or
moving an extension between media and `other` changes which files exist where. Prep re-plans from the filesystem each
run and guards execution with the whole-file hash, so it needs no separate folder or extension fingerprint of its own.
:::

:::{rat} A file's class decides how it is handled
:id: RAT-class_decides_handling
:status: ruled
:justifies: RUL-extension_one_class, RUL-config_lists_extensions, RUL-unlisted_extension_other

A file's class decides everything the pipeline does with it: a photo is organized by date and geotagged, a video goes to
its own folder, anything else is set aside as a stray. An extension in two classes would leave that undecided; a class
the configuration invented would have no handling, since the phases are written for the classes they know; and an
extension nobody listed is safest set aside, recoverably, rather than guessed at.
:::

:::{rat} The control records are found before anything is read
:id: RAT-control_records_found_first
:status: ruled
:justifies: RUL-control_directory_fixed

Every phase, the editor and the console must find the control records before reading any of them — and the
configuration, which might otherwise name the place, is itself one of them. A fixed place is also what lets prep leave
it out wholesale, and lets anyone opening an old workspace find its record.
:::

:::{rat} A folder's role is pipeline logic
:id: RAT-folder_roles_are_logic
:status: ruled
:justifies: RUL-folder_names_not_roles, RUL-folder_found_by_role

The roles — the inbox, the read-only destination tree, the order in which duplicates are retained, which folders are
the photo and video bands — are pipeline logic, so the user sets the names and never the roles.
:::

:::{rat} The derivation's version must stay the code's
:id: RAT-derivation_version_is_code
:status: ruled
:justifies: RUL-camera_classes_not_derivation

The version of the camera-group derivation takes part in the dependency fingerprints, so a change to the derivation is
detectable; it versions the code that computes the key, so only the code can set it.
:::

## 4. The control records, apart from the media

:::{rat} One skipped place instead of a list of names
:id: RAT-one_skipped_place
:status: ruled
:justifies: RUL-control_records_together, RUL-control_records_never_media

Skipping the control directory wholesale means a control or artifact file can never be mistaken for a photo. There is
no per-file "ignore list" to maintain — consolidating everything in one skipped directory replaces the basename
registry that earlier designs needed.
:::

:::{rat} A duplicate and its explanation are not separated
:id: RAT-quarantine_manifest_beside_duplicates
:status: ruled
:justifies: RUL-control_records_together

A quarantine manifest says why each file beside it was set aside. Kept in the quarantine folder it describes, it cannot
be parted from those files: whoever looks at a duplicate finds its reason next to it, and pruning a folder removes the
files and their manifest together, leaving no record of files that are gone. What each manifest said is kept in the
transformation log, so pruning loses nothing of the record.
:::

:::{rat} A dump leaves no hidden litter
:id: RAT-no_hidden_litter
:status: ruled
:justifies: RUL-dump_hidden_files_quarantined

Hidden dotfiles are swept to the recoverable quarantine, not merely skipped, so a dump leaves no hidden litter.
:::

:::{rat} A plan in one known place is the plan that runs
:id: RAT-one_place_per_plan
:status: ruled
:justifies: RUL-plan_at_fixed_place, RUL-no_plan_location_option

A plan kept in one known place is the plan that runs: the dry run and the execution read exactly what the last planning
wrote, and the user always knows where to review it. An option naming another place would let a run carry out a plan
other than the last one made — an old copy, or another workspace's — and would ask the user to remember where they put
it, in a tool used a few times a year.
:::

:::{rat} Nothing runs that the user could not review
:id: RAT-plan_before_run
:status: ruled
:justifies: RUL-no_plan_no_run

Execution carries out only a plan the user could review first. With none saved, there is nothing reviewed to carry out,
and planning on the spot would skip the review the plan exists for.
:::

:::{rat} The dry run reads the persisted plan
:id: RAT-dry_run_reads_the_saved_plan
:status: ruled
:justifies: RUL-dry_run_summarises_the_real_plan

A simulation is a second path that can disagree with execution: it can pass where execution would fail, or the
reverse. Checking the very plan execution will carry out means what the dry run passed is what runs. A summary is
enough because the whole plan is on disk to read.
:::

:::{rat} A superseded plan stays recoverable; an unchanged one adds nothing
:id: RAT-superseded_plans_recoverable
:status: ruled
:justifies: RUL-replanning_keeps_the_prior, RUL-unchanged_replan_writes_nothing

Setting the prior artifact aside keeps a superseded plan and any authored decisions recoverable; writing nothing on an
unchanged re-run means the iterative decision-editing loop does not accumulate redundant backups.
:::

:::{rat} The handoff is invisible to the scan, yet verified
:id: RAT-handoff_by_content
:status: ruled
:justifies: RUL-handoff_verified_by_content, RUL-run_only_refresh_restales_nothing

Living in the skipped directory is independent of the handoff's role as a dependency: it is invisible to prep's media
scan yet fully verified as a dependency by geotag — verified by content, not by exact bytes, so a run-only refresh of
it does not restale downstream.
:::

:::{rat} Every phase relies on the shape when it scans
:id: RAT-phases_rely_on_the_shape
:status: ruled
:justifies: INV-undisturbed_shape, RUL-shape_checked_first

The structural facts are shared by every phase because each relies on them when it scans, and a violation of any one
means the workspace was disturbed out-of-band. The guards compose with — but are distinct from — input validation, which
checks *authored values*, and the dependency cascade, which checks *change*: these check the *shape of the workspace
itself*.
:::

:::{rat} A followed link escapes the managed tree
:id: RAT-a_link_escapes_the_tree
:status: ruled
:justifies: RUL-no_links, RUL-link_named

Following a symbolic link would let a planned read or write reach a target **outside** the managed tree — a pipeline
escape that breaks the no-clobber and "originals never lost" guarantees and the closed-world assumption the content
fingerprint and de-duplication rest on.
:::

:::{rat} Prep is the gatekeeper for links under the destination tree
:id: RAT-prep_gatekeeps_links
:status: ruled
:justifies: RUL-who_checks_for_links, RUL-geotag_merge_check_top_level_links

The destination tree is read-only for prep yet still scanned by it, so prep is also the gatekeeper for links that
appear there; and the mandatory re-prep after any change to it means geotag and merge only ever consume a handoff prep
built with no forbidden link present.
:::

:::{rat} A rebuilt structure could mask a loss
:id: RAT-rebuild_masks_loss
:status: ruled
:justifies: RUL-missing_folder_blocks, RUL-structure_built_once, RUL-only_prep_builds_structure, RUL-missing_folder_named, RUL-empty_inbox_normal

Since prep creates the structure once and never removes a folder, a missing one is evidence the structure was deleted
or moved out-of-band — not a state any phase produces. Silently rebuilding it could mask a real loss: a deleted folder
may have taken organized media with it. Recovering lost media — from an optional pre-mutation snapshot, say — is the
operator's task.
:::

## 5. Camera groups, derived once

:::{rat} Grouping computed once is never reinvented
:id: RAT-grouping_computed_once
:status: ruled
:justifies: RUL-prep_derives_camera_group, RUL-geotag_reuses_camera_group

Two derivations of a camera's identity could disagree: a file grouped one way by prep and another way by geotag would
get another camera's clock offset. And the user classes groups by the key they see, so it must be the same key
everywhere it appears. One derivation, by prep, recorded with the file and reused by geotag, rules out both.
:::

:::{rat} Only the user knows a group's class
:id: RAT-class_from_the_user
:status: ruled
:justifies: RUL-known_when_classified

Geotag treats the two classes differently: a phone keeps network time and is solved file by file, while a camera's clock
drifts and needs an offset for each group and destination. Guessing the class from a make or a model would be wrong for
some devices, and wrong without anyone noticing. Only the user knows, so a group the configuration does not class stays
unknown and geotag asks.
:::

## 6. One filename format

:::{rat} One key, so the names cannot drift apart
:id: RAT-one_format_no_drift
:status: ruled
:justifies: RUL-one_filename_format

With one format key for the whole pipeline, the provisional names prep assigns and the final names geotag assigns are
guaranteed to share the same textual shape and can never drift apart; there is no format divergence to reconcile.
:::

:::{rat} The same shape, a different value, on purpose
:id: RAT-same_shape_different_value
:status: ruled
:justifies: RUL-prep_name_provisional, RUL-geotag_name_final, RUL-uncorrected_keeps_its_name

Both phases use the same format, but the **value** differs by phase and that difference is intentional. Because the
shape is identical, a file's name changes between phases only when its timestamp is genuinely corrected; an uncorrected
file's provisional and final names coincide, so geotag plans no needless rename for it.
:::

:::{rat} The first free name makes the two names coincide
:id: RAT-bare_first
:status: ruled
:justifies: RUL-suffix_choice_by_phase, RUL-uncorrected_keeps_its_name

Bare-first is what makes an uncorrected file's provisional (prep) and final (geotag) names coincide, so geotag plans no
needless rename; the two phases use the identical rule so they never disagree on a name.
:::

:::{rat} The library is append-only
:id: RAT-merge_appends
:status: ruled
:justifies: RUL-merge_suffix_above_highest

In the library a gap in the numbers is a photo the user deleted; giving its number to a new photo would hand it a name
a backup or an export may still use for the deleted one.
:::

:::{rat} Prep cannot know a photo's true time
:id: RAT-prep_cannot_know_the_time
:status: ruled
:justifies: RUL-prep_name_provisional

Prep runs before anyone knows a photo's true time: the camera's clock offset comes from geotag, by matching against the
tracks or from the user, and the timezone from the destination the user sorts the photo into. All prep has is the time
the camera recorded — enough to put a day's photos in order, not enough for a name to keep.
:::

:::{rat} A name in the time of day where the photo was taken
:id: RAT-name_in_local_time
:status: ruled
:justifies: RUL-geotag_name_final

A name is read by a person looking for a photo, who remembers the time of day where it was taken. A camera's clock may
be off or still on home time, and UTC is nobody's time of day; the corrected time at the destination is the one that
matches the memory.
:::

:::{rat} Outside the inbox, every name is the pipeline's
:id: RAT-misnamed_not_ignored
:status: ruled
:justifies: RUL-misnamed_file_stops_prep

Outside the inbox every name is one the pipeline gave. A name that is not means a file was renamed or put there by
hand, and nothing says which time or which photo it holds; passed over in silence, it would reach the library under a
name that looks trusted. Only the inbox takes files as they come.
:::

:::{rat} The JPG named like its RAW
:id: RAT-redundant_named_like_its_raw
:status: ruled
:justifies: RUL-redundant_jpg_timestamp_named

A redundant JPG is the same shot as the RAW kept in the dated folders: named from the same time, the two names show it,
and the JPG's name is checked like any other outside the inbox.
:::

:::{rat} One format for a workspace's life
:id: RAT-format_fixed_per_workspace
:status: ruled
:justifies: RUL-format_fixed_once_named

Merge never renames a file in the library, so after a change the library holds both formats whatever the workspace
does. Renaming every named file in the workspace would buy consistency for the few weeks a workspace lives, at the cost
of renaming originals in bulk; keeping the format the workspace began with and taking the new one to the next workspace
costs nothing.
:::

:::{rat} Two files never share a name
:id: RAT-names_never_collide
:status: ruled
:justifies: RUL-suffix_no_clobber

Photos taken in the same second — a burst, two cameras — get the same timestamp name, and a name given twice would
overwrite an original. The suffix keeps every one; counting the names already planned as taken stops two files of one
run from claiming the same name, and comparing without case keeps them apart on a filesystem that ignores case.
Allocated deterministically, a re-run gives each file the name it gave before.
:::

## 7. The tracks, kept outside the managed folders

:::{rat} Where the tracks live is what keeps them geotag's
:id: RAT-tracks_kept_outside
:status: ruled
:justifies: RUL-tracks_outside_managed_folders, RUL-tracks_geotag_only

The shared rule that makes it safe for geotag alone to own the tracks is where they live. Kept outside the managed
folders, prep's normal scan never encounters them, so they can never be taken for files of no media class, or swept
into the inbox and organized.
:::

:::{rat} The tracks are geotag's evidence
:id: RAT-tracks_are_geotags_evidence
:status: ruled
:justifies: RUL-tracks_geotag_only

The tracks are evidence for a photo's time and place, and only geotag decides those: prep never plans a time or a
position, so it has no use for them. A phase that read them would also have to treat every change to them as a change
to its own records.
:::

:::{rat} A track among the strays could be deleted with them
:id: RAT-tracks_never_strays
:status: ruled
:justifies: RUL-track_files_block_prep, RUL-track_file_left_in_place

Parked among the strays, a track could be deleted when the strays are cleared in bulk, and a lost track is evidence no
re-run can recover. Refusing to run leaves it where the user put it until they move it to the tracks' location.
:::

:::{rat} Changed tracks can change the answers
:id: RAT-tracks_change_the_answers
:status: ruled
:justifies: RUL-tracks_in_dependencies

The tracks are evidence for the clock offsets and positions geotag proposes, and a track added, corrected or removed can
change them. A decision made against the old tracks, or a plan built from them, could then be wrong while still looking
settled; the tracks' fingerprint in each record turns the change into staleness instead of letting it pass unseen.
:::

## 8. Nothing used once what it came from has changed

:::{rat} One source for each shared fact
:id: RAT-one_source_per_fact
:status: ruled
:justifies: INV-no_stale_use

The facts the dependencies are built from — the configuration, the control records, the camera-group derivation's
version, the filename format, the tracks, the snapshot mechanism — are each defined once, for every phase, so that a
single change has one authoritative source and a predictable staleness footprint everywhere.
:::

:::{rat} Opposite jobs, so different names
:id: RAT-fingerprint_and_hash_opposite_jobs
:status: ruled
:justifies: DEF-fingerprint, DEF-hash

The two words name a value by the role it plays, not by the algorithm underneath, and the two roles are opposite: one
must be invariant under mutation, the other sensitive to it. They keep different names even though a fingerprint is
itself computed with a hash function.
:::

:::{rat} A file's identity outlives its edits
:id: RAT-identity_survives_edits
:status: ruled
:justifies: RUL-fingerprint_survives_mutation

A fingerprint is chosen precisely so it stays the same when the pipeline rewrites a photo's metadata or position or
renames the file: a media file's identity must survive those mutations, which is what makes it the identity spine the
transformation log and de-duplication rely on.
:::

:::{rat} Detecting change is a hash's whole purpose
:id: RAT-hash_is_for_change
:status: ruled
:justifies: RUL-hash_detects_any_change

A hash is chosen precisely so it changes on any byte change: detecting change is its whole purpose.
:::

:::{rat} A record's every byte can matter
:id: RAT-bytes_are_the_safe_check
:status: ruled
:justifies: RUL-hash_is_the_dependency_check

A record is small and every byte of it can matter — a decision, an offset, a timezone — so the safe check is its exact
bytes: comparing chosen fields would let through a change to a field nobody chose. The handoff is the exception because
prep rewrites its run identifiers on every run; checked by its bytes, a run that changed nothing would make everything
after it stale.
:::

:::{rat} Failing to look is no proof that nothing changed
:id: RAT-unknown_is_not_unchanged
:status: seed
:justifies: RUL-unchecked_counts_as_changed

A dependency that cannot be checked gives no assurance either way. Counting it unchanged would let a failure to look
stand for proof that nothing moved: a file deleted since the plan, a record a crash left behind, a plan recording
nothing would all pass. Refusing costs a re-plan; trusting could cost a photo its place or its record.
:::

## 9. One loop across the phases

:::{rat} A steady state to return to
:id: RAT-loop_is_steady_state
:status: ruled
:justifies: RUL-geotag_gates, RUL-more_dumps_until_merge

The loop is a steady state to return to, not a one-way pipeline: a batch can be imported, sorted, and followed by
another before anything is geotagged. A phase that judged by what ran before would have to forbid that; one that judges
the present state need not.
:::

:::{rat} Bounded by what is true now, not by a flag
:id: RAT-gates_not_history
:status: ruled
:justifies: RUL-geotag_gates, RUL-geotag_rerunnable

What bounds geotag's freedom is a small, fixed set of conditions on the workspace, not a "has geotag run before?" flag.
Each gate names a state geotag cannot work correctly from; none says anything about history.
:::

:::{rat} Re-running is safe because nothing settled is redone
:id: RAT-rerun_is_safe
:status: ruled
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

:::{rat} An empty inbox means nothing is waiting
:id: RAT-empty_inbox_means_nothing_waits
:status: ruled
:justifies: RUL-prep_empties_inbox

An empty inbox is the one sign that nothing is waiting to be organized: geotag and merge refuse to run while it holds
something, and the next dump arrives into a clean place, where nothing left from the last one can be taken for part of
it.
:::

:::{rat} Only what geotag treats goes to the library
:id: RAT-only_what_geotag_treats
:status: ruled
:justifies: RUL-sort_photos_only

Geotag corrects only photos: it reads and writes photo metadata and places photos on the map. A video or any other file
in photos by destination would reach the library beside photos geotag treated, itself untreated; refusing keeps the
destination's set one geotag has wholly treated.
:::

:::{rat} New photos never reach geotag behind prep's back
:id: RAT-never_behind_prep
:status: ruled
:justifies: RUL-prep_records_sort, RUL-sort_recorded_by_stat

Geotag depends on prep's handoff, and a photo prep has not recorded is not in it. Re-prepping after every sort, even
after geotag has run, keeps the handoff the whole truth about photos by destination.
:::

:::{rat} Safe is not frictionless
:id: RAT-rerun_not_frictionless
:status: ruled
:justifies: RUL-rerun_does_what_changed

"Freely re-runnable" does not mean "always a no-op". Any change upstream — not only new media — restales exactly what
depends on it, and may raise new questions about the items it touches; a re-run does that work and no more.
:::

:::{rat} Finalize stays apart because geotag is re-run
:id: RAT-finalize_apart
:status: ruled
:justifies: RUL-finalize_explicit

Geotag is re-run freely, and assembling the permanent record on each pass would be wasted work. Finalize marks the one
moment the user declares the dump done.
:::

:::{rat} Never a half-geotagged set in the library
:id: RAT-merge_never_half_done
:status: ruled
:justifies: RUL-merge_takes_finalized_current, RUL-merge_refuses_changed_since_finalize

Finalize is a point in time, and photos by destination can change after it. Merge checks the finalized set against the
present one rather than trusting finalize was last, so a half-geotagged set cannot reach the library.
:::

:::{rat} A merged workspace is not a clean slate
:id: RAT-workspace_not_recycled
:status: ruled
:justifies: RUL-merge_is_terminal, RUL-library_takes_many_workspaces

Even with photos by destination empty, a merged workspace keeps its database, ledgers, caches, snapshots and sealed
record. Starting afresh keeps each workspace's record about one batch.
:::

:::{rat} Corrections would invalidate development
:id: RAT-development_after_corrections
:status: ruled
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

:::{rat} A decision is what only the user knows
:id: RAT-decisions_are_the_users
:status: ruled
:justifies: RUL-user_writes_decisions

A decision is a fact only the user knows — which timezone a trip was in, which offset a camera had, where a photo with
no position was taken. A phase that overwrote one, even with a better-looking guess, would silently put the tool's guess
in place of the user's knowledge; so the tool proposes in fields of its own and never touches the user's.
:::

:::{rat} The tool lays out, the user fills in
:id: RAT-structure_from_the_tool
:status: ruled
:justifies: RUL-decision_fields_laid_out

The user edits these records a few times a year, by hand or in the editor. A field they had to add would need its exact
name and place remembered, and one mistyped would be a decision lost or misread; laid out by the tool, every decision is
one value to fill in, its place already right.
:::

:::{rat} Prep has nothing to ask
:id: RAT-prep_needs_no_answers
:status: ruled
:justifies: RUL-prep_takes_no_decision

Prep's work — sorting by type and date, setting duplicates aside, recording what is where — follows from the files and
the configuration with nothing left to judge. The questions only the user can answer are about time and place, which are
geotag's; a prep that asked would hold up the inbox on questions it does not need answered.
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
:justifies: RUL-log_keyed_by_fingerprint, RUL-no_log_entry_for_other

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
:justifies: RUL-database_is_record, RUL-one_database, RUL-other_databases_scratch

The database is not only a cache that makes re-runs cheap: it holds what nothing else does — the values a photo held
before geotag first changed it, which let any change be undone, and each photo's identity across its moves. Discarded
with the workspace, that knowledge would be lost; kept in two places, the two could disagree. The library keeps no
database because it is the user's own collection, organised as they choose, and merge only adds to it.
:::

:::{rat} A database shows only now
:id: RAT-database_shows_only_now
:status: ruled
:justifies: RUL-database_image_each_phase, RUL-image_never_working_data, RUL-images_archived

The live database is one file that every phase changes, so at any moment it shows only the latest state: what prep
knew is overwritten by what geotag learned. An image taken at each phase's end keeps the database's state at every
boundary, to be opened later and compared.
:::

:::{rat} An image is regenerable; a photo is not
:id: RAT-image_replaced_not_kept
:status: ruled
:justifies: RUL-database_image_each_phase, RUL-database_image_whole, RUL-image_never_working_data, RUL-images_archived, RUL-image_capture_atomic

Never overwriting guards photos, which cannot be made again. An image can: it is a copy of the live database, and only
the latest end of each phase is worth keeping, so a phase's next successful run replaces its image — whole, so that a
capture interrupted leaves a usable image either way.
:::

:::{rat} Finalize records what geotag left
:id: RAT-finalize_only_records
:status: ruled
:justifies: RUL-finalize_non_destructive

Finalize is the moment the user declares the workspace done, and the package must record what geotag actually left. Were
finalize to change anything, the package would record a state that existed only inside finalize, and finalizing again
could record another; reading only, it can be run again at any time and records the same.
:::

:::{rat} The why beside the what
:id: RAT-why_beside_what
:status: ruled
:justifies: RUL-log_cites_decisions

A step alone says what happened to a photo — its time moved by three hours — not why. Years later, the decision behind
it is what tells a right correction from a mistake; named beside the step, it is found without searching records that
may be long gone with the workspace.
:::

:::{rat} Each phase writes only its own steps
:id: RAT-each_phase_owns_its_steps
:status: ruled
:justifies: RUL-log_entry_grows

Each phase knows only its own work, so each appends only its own steps; rewriting an earlier phase's would put words in
its mouth. Kept whole through the latest phase, one log tells a photo's full story, and each earlier log stays the true
record of what its phase saw.
:::

:::{rat} The log is read by people, years on
:id: RAT-log_read_by_people
:status: ruled
:justifies: RUL-log_human_readable

The log outlives the tool that wrote it: it is read by a person, years on, perhaps without cartographer at hand. A
stable order lets two logs be compared line by line; names and values as people say them — a time with its timezone, an
offset in hours and minutes — need no program to decode.
:::

:::{rat} Undoing a position is a step too
:id: RAT-reverts_are_steps_too
:status: ruled
:justifies: RUL-log_records_gps_reverts

Withdrawing a manual position changes the photo as much as applying one: its position goes back to what it held, or to
none. Logged with what it replaced or restored, every position the photo ever carried can be traced; left out, the log
would show a position the photo no longer has.
:::

:::{rat} The package answers what the workspace could
:id: RAT-package_answers_later
:status: ruled
:justifies: RUL-package_contents

The workspace is transient; the package is what remains of it beside the library. It must answer later what the
workspace could: under which settings, by which decisions, from which plans each photo was changed, and what each phase
saw. Anything left out — a journal, a snapshot — is a question no one can answer once the workspace is gone.
:::

:::{rat} The package can be checked without the tool
:id: RAT-package_checks_itself
:status: ruled
:justifies: RUL-package_self_describing

A package moved to long-term storage is parted from the workspace that made it and may sit untouched for years. Naming
its workspace, plan and execution ties it to what it records; listing every item with its hash lets anyone confirm,
without the tool, that nothing in it has decayed or been altered.
:::

## 13. Merge: the library kept, the workspace sealed

:::{rat} The library is the user's, and already in order
:id: RAT-library_is_ground_truth
:status: ruled
:justifies: RUL-library_never_altered, RUL-library_not_scanned, RUL-collision_by_content, RUL-collision_same_content, RUL-collision_different_content

The library is the user's curated collection: its organisation and names are the ground truth, and other tools and
people rely on them. So merge adds to it and changes nothing in it, and assumes it is in order rather than scanning it:
scanning a whole library to place one batch would cost far more than it saves. Where a name is taken, only the content
tells a copy already present from a different photo sharing a name.
:::

:::{rat} A library file costs a full read
:id: RAT-library_reads_cost
:status: ruled
:justifies: RUL-library_file_read_once, RUL-library_file_rechecked_before_removal

Fingerprinting a library file means reading and decoding it whole, and the library may sit across a network. Kept in the workspace, a
fingerprint already taken spares that read on the next run, and stays right while the file is unchanged. A kept
fingerprint is trusted by size and modification time, though, and removing a photo because the library already holds
it cannot be undone: that one decision reads the file again rather than trust what was kept.
:::

:::{rat} One library, many workspaces
:id: RAT-library_shared
:status: ruled
:justifies: RUL-library_lock, RUL-library_lock_fail_fast, RUL-library_lock_holds_only_holder, RUL-library_lock_stale_recovered

Many workspaces merge into one library, each under its own lock. Only a lock on the library itself keeps two of their
merges from writing it at once.
:::

:::{rat} A library has nothing of the tool's to inspect
:id: RAT-library_mark
:status: ruled
:justifies: RUL-library_known_by_mark, RUL-library_confirmed_before_lock, RUL-library_place_checked, RUL-library_mark_made_by_setup, RUL-library_mark_required, RUL-library_creates_only_placements

The library is the user's: it has no structure of the tool's to inspect, so one mark, made once and on purpose, is
all that tells it from any other folder. Checking the mark before anything is written there — the lock included —
keeps the tool from writing into a folder that was never made a library.
:::

:::{rat} The workspace keeps only what still needs attention
:id: RAT-move_not_copy
:status: ruled
:justifies: RUL-merge_moves, RUL-merge_resumable, RUL-unplaced_photo_stays

A copy left in the workspace of a photo already in the library is a duplicate that invites confusion and wastes space,
so merge moves rather than copies, and removes a copy whose content the library already holds. What stays behind is
exactly what still needs attention. Removing the workspace's copy last, once the library's is verified, means an
interruption never loses a photo: running merge again finishes the work.
:::

:::{rat} Merge is the end, so the package is remade at once
:id: RAT-reseal_automatic
:status: ruled
:justifies: RUL-merge_reseals, RUL-reseal_rederives_nothing

Merge adds to the record finalize packaged, so the existing package no longer describes the whole journey. Since merge
is the workspace's last act, remaking the package once at its end is what the user always wants. Finalize stays its own
command because geotag is freely re-run, and re-packaging after every pass would be wasted.
:::

:::{rat} An empty folder means two things; a mark means one
:id: RAT-seal_not_folder_state
:status: ruled
:justifies: RUL-seal_is_authority, RUL-seal_on_success_only

Photos by destination is empty both in a workspace just sorted and in one merged and finished, so its state cannot say
which a workspace is. A mark written only when merge succeeds whole can — and a merge that left a photo behind writes
none, so it can be finished by running it again.
:::

:::{rat} A finished workspace is read, not reprocessed
:id: RAT-sealed_is_final
:status: ruled
:justifies: RUL-sealed_refuses, RUL-sealed_new_dump_warned, RUL-editor_refuses_sealed, RUL-sealed_no_library_recorded, RUL-sealed_new_dump_left

A second batch processed in a merged workspace would interleave with the first's database, logs and package, and its
record would no longer describe one dump. So nothing that could change it runs; the records stay readable; and a dump
dropped there is left untouched and pointed out, for the user to move to a fresh workspace by hand — safer than any
automated move inside a finished workspace.
:::

:::{rat} Pruning the quarantine changes nothing controlled
:id: RAT-prune_harms_nothing
:status: ruled
:justifies: RUL-sealed_prune_allowed

The quarantine holds only spare copies of duplicates, which a sealed workspace still keeps. Deleting them, with the
manifests that list them, touches no photo, library file, control record or row of the database; what each manifest
said is kept in the transformation log and the package. It neither reprocesses the workspace nor adds a batch to it,
so the seal's reasons do not reach it, and the space can be reclaimed.
:::

## 14. Every value the user writes is checked

:::{rat} A current value can still be wrong
:id: RAT-valid_is_not_unchanged
:status: ruled
:justifies: INV-authored_values_checked, RUL-checked_every_run

A fingerprint tells whether a value changed, not whether it makes sense. A value can match its fingerprint and still be
meaningless or dangerous, or be freshly typed and wrong; and a value valid in one run can be edited before the next. So
both checks are needed, every time.
:::

:::{rat} What is typed by hand can be mistyped
:id: RAT-hand_written_fallible
:status: ruled
:justifies: INV-authored_values_checked, RUL-checked_paths, RUL-checked_timezones, RUL-checked_positions_and_times, RUL-checked_filename_format, RUL-checked_numbers, RUL-checked_shapes, RUL-invalid_value_stops, RUL-invalid_value_located, RUL-invalid_value_never_repaired

The user writes the configuration and the decisions by hand, so the tool cannot assume they are well formed. A
mistyped timezone or an unsafe path, reported early as a specific problem in a named place, is fixed at its source;
coerced, half applied or let through, it spoils a later operation, and the change it causes can no longer be
explained. Checking keeps every change explainable and the user its author.
:::

:::{rat} A snapshot fails before anything changes, not midway
:id: RAT-snapshot_name_early
:status: ruled
:justifies: RUL-checked_snapshot_names

A snapshot's name the snapshot tool would refuse is found when the configuration is read, not when the snapshot is
taken, so a bad name never surprises an execution midway.
:::

:::{rat} The user keeps what they wrote
:id: RAT-invalid_decision_shown
:status: ruled
:justifies: RUL-invalid_decision_kept

Erasing an invalid decision would take away the very thing the user must see to correct it. Kept and marked, it shows
what was written and what is wrong with it.
:::

## 15. Nothing overwritten, nothing left half-done

:::{rat} A plan describes the workspace as it was
:id: RAT-plan_can_be_overtaken
:status: ruled
:justifies: RUL-target_free_at_execute

A plan is made from the filesystem at one moment, and the workspace or the library can change before it runs. The
plan's own collision check is the first defence; checking each name as it is written is a second, independent one,
which no plan, however careful, can stand in for.
:::

:::{rat} Safety and resuming rest on the moment of each change
:id: RAT-safe_at_each_change
:status: ruled
:justifies: RUL-operations_atomic, RUL-split_move_never_lost, RUL-rewrite_in_place_atomic, RUL-cross_fs_all_or_nothing, RUL-failed_operation_clean, RUL-failure_recorded, RUL-failure_never_done

That nothing is overwritten, and that an interrupted run is finished by running it again, hold only if each change is
safe when it happens. A half-done move, a half-written file, or a failure recorded as done would break both where no
plan can see it.
:::

:::{rat} Within a workspace, every move is one rename
:id: RAT-workspace_one_filesystem
:status: ruled
:justifies: RUL-workspace_one_filesystem, RUL-one_filesystem_checked_every_run, RUL-workspace_moves_one_filesystem

On one filesystem every move a workspace sees is a single rename: nothing to copy, nothing to verify, no temporary copy
to leave behind. A workspace is one place made for one ingest, so nothing needs it spread over volumes; one that is
would turn prep's ordinary moves into copies, slower and less safe. Only the library is a place apart, and only merge
crosses into it. Checking every run, not once, catches a volume mounted into the workspace since the last.
:::

:::{rat} A temporary copy left behind is debris
:id: RAT-temps_are_debris
:status: ruled
:justifies: RUL-crash_temps_cleared, RUL-temp_name_own

Merge holds the library's lock, so a temporary copy found in a folder it places into was left by an interrupted earlier
merge, never one being written now. It bears no photo's name, so it does no harm either way: clearing it keeps the
library free of litter — hygiene, not safety.
:::

## 16. Nothing changed outside a validated plan

:::{rat} A plan is read before anything moves
:id: RAT-plan_read_before_anything_moves
:status: seed
:justifies: RUL-planning_changes_no_media

A plan is there to be read before anything happens — by the user, and by the dry run that checks it. Planning that
changed a file would leave the workspace neither as it was nor as the plan intends, before anyone agreed to either; and
planning again, which the user may do as often as they like, would change it again. So planning only reads, and writes
only what reading produced: the plan, the decisions it asks for, and what spares the next run reading it all again —
and once, the configuration the plan itself is made under.
:::

:::{rat} What was reviewed is what happens
:id: RAT-what_was_reviewed_happens
:status: seed
:justifies: RUL-execution_only_the_plan

What the user reviewed — the plan, its dry run — is what must happen. An execution that decided afresh would act on a
judgement nobody saw, and a difference between the plan and what was done could not be explained from the record.
Deciding again is planning's work: when the workspace has moved on, the plan is stale and refused, and the user plans
again.
:::

:::{rat} The journal is the run's own account
:id: RAT-journal_is_the_account
:status: seed
:justifies: RUL-every_change_journaled

The journal is the history of a run: what it changed, in what order, and how each change ended. The logs are built from
it and the archival package keeps it, so a change missing from it is a change no record explains — the one thing the
record exists to prevent.
:::
