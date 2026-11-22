# Merge — what it guarantees

What the last phase, {need}`DEF-merge`, guarantees, beyond what [the shared contract](shared.md) binds every phase
to — most of merge's rules are there, in its section on the library and the seal. *Why* each holds is in
[the rationale](../rationale/merge.md); *how this build meets it*, in [the build](../build/merge.md).

## Scope and boundary

:::{rul} Merge checks prep's fingerprints under another image engine
:id: RUL-merge_rechecks_under_new_engine
:status: ruled
:criticality: high
:verify: required
:refines: RUL-engine_change_is_checked
:uses: DEF-fingerprint, DEF-library

Under an image engine version other than the one prep's fingerprints were taken by, merge SHALL take each photo's
fingerprint again before comparing it with the library's.
:::

:::{rul} A photo whose fingerprint changed is merged under its new value
:id: RUL-merge_merges_changed_fingerprint
:status: ruled
:criticality: high
:verify: required
:refines: RUL-merge_rechecks_under_new_engine
:uses: DEF-fingerprint, DEF-library, DEF-finalize, RUL-retaken_fingerprint_same_photo

A photo whose fingerprint, taken again by merge, has changed SHALL be merged under its new value where it is the very
file finalize recorded and its old value and its new are one to one — neither value another photo's under either
version.
:::

:::{rul} Merge records each changed fingerprint, old value to new
:id: RUL-changed_fingerprint_mapping_recorded
:status: ruled
:criticality: high
:verify: required
:refines: RUL-merge_merges_changed_fingerprint
:uses: DEF-fingerprint, RUL-phase_writes_own_records

For each photo merged under a changed fingerprint, merge's own records SHALL hold its old value and its new, each with
the image engine version that took it.
:::

:::{rul} A changed fingerprint not proven one to one is left unmerged
:id: RUL-merge_changed_fingerprint_unmerged
:status: ruled
:criticality: high
:anti: yes
:verify: required
:refines: RUL-merge_rechecks_under_new_engine
:uses: DEF-fingerprint, DEF-library, RUL-merge_merges_changed_fingerprint

A photo whose fingerprint, taken again by merge, has changed, and which {need}`RUL-merge_merges_changed_fingerprint`
does not merge — and a photo whose unchanged value such a photo's new value equals — SHALL be left in photos by
destination, unmerged — photos that moved together from one value to one ({need}`RUL-shared_value_moved_together_merged`)
aside.
:::

:::{rul} Photos held as one value that move together to one are merged
:id: RUL-shared_value_moved_together_merged
:status: ruled
:criticality: high
:verify: required
:excepts: RUL-merge_changed_fingerprint_unmerged
:uses: DEF-fingerprint, DEF-finalize, DEF-managed_folders

Photos in photos by destination that prep held under one fingerprint, each the very file finalize recorded, whose
fingerprints taken again by merge are all one new value that no other photo holds now or held under prep's version,
SHALL each be merged under that new value.
:::

## Preconditions

:::{rul} Merge checks geotag's gates again
:id: RUL-merge_rechecks_gates
:status: ruled
:criticality: high
:anti: yes
:verify: required
:refines: RUL-geotag_gates
:uses: DEF-merge, DEF-managed_folders

Merge SHALL proceed only while the workspace, checked again at merge's own start, satisfies geotag's gates.
:::

:::{rul} A photo without a position stops merge
:id: RUL-merge_refuses_unplaced
:status: ruled
:criticality: high
:anti: yes
:verify: required
:refines: RUL-finalize_refuses_unplaced
:uses: DEF-merge

Merge SHALL refuse while a photo in photos by destination holds no position, checked again at merge's own start as
finalize checks it.
:::

:::{rul} What geotag's gates leave out does not block merge
:id: RUL-merge_gates_leave_out_residue
:status: ruled
:criticality: high
:anti: yes
:verify: required
:refines: RUL-merge_rechecks_gates
:uses: DEF-merge, DEF-managed_folders

What geotag's gates leave out — the videos, the files missing metadata, the redundant JPEGs and the strays — SHALL
block merge no more than geotag.
:::

:::{rul} A merge a precondition stops changes nothing
:id: RUL-merge_blocked_changes_nothing
:status: ruled
:criticality: high
:anti: yes
:verify: required
:uses: DEF-merge, DEF-library

A merge a precondition stops SHALL change nothing in the library, the workspace's photos or merge's records — but for
the record of a stop for want of a required snapshot or of room in the library
({need}`RUL-merge_summary_only_for_execution`).
:::

:::{rul} A photo with no fingerprint stops merge
:id: RUL-unfingerprinted_photo_stops_merge
:status: ruled
:criticality: high
:anti: yes
:verify: required
:uses: DEF-fingerprint, DEF-managed_folders

Merge SHALL NOT plan, dry-run or execute while a photo in photos by destination has no fingerprint.
:::

:::{rul} A hidden entry among the photos stops merge
:id: RUL-hidden_among_photos_stops_merge
:status: ruled
:criticality: high
:anti: yes
:verify: required
:uses: DEF-managed_folders

Merge SHALL NOT plan, dry-run or execute while photos by destination holds a hidden file or folder.
:::

:::{rul} Merge stops without its image engine
:id: RUL-image_engine_absent_stops_merge
:status: ruled
:criticality: high
:anti: yes
:verify: required
:uses: DEF-merge, DEF-fingerprint

Merge SHALL NOT plan, dry-run or execute while the image engine, by which it fingerprints a file, is absent.
:::


:::{rul} What merge needs of the library's filesystem is tried at its start
:id: RUL-library_requirements_tried
:status: ruled
:criticality: high
:verify: required
:uses: DEF-merge, DEF-library, DEF-filesystem_requirements, RUL-filesystem_trial_leaves_nothing

Merge's plan, dry run and execution SHALL try on the library's filesystem what {need}`DEF-filesystem_requirements`
requires of a library's, leaving nothing of the files they try it with ({need}`RUL-filesystem_trial_leaves_nothing`).
:::

:::{rul} The library is tried between its mark and its lock
:id: RUL-library_tried_before_lock
:status: ruled
:criticality: high
:anti: yes
:verify: required
:refines: RUL-library_requirements_tried
:uses: DEF-merge, DEF-library, RUL-library_confirmed_before_lock

Merge SHALL try the library's filesystem only once the library's mark has confirmed it, and before it takes the
library's lock.
:::

:::{rul} A library's filesystem lacking one stops merge
:id: RUL-library_lacking_stops
:status: ruled
:criticality: high
:anti: yes
:verify: required
:refines: RUL-library_requirements_tried

A library whose filesystem fails at one of them SHALL stop merge with nothing changed.
:::

:::{rul} The stop names what the library's filesystem lacks
:id: RUL-library_lacking_named
:status: ruled
:criticality: med
:verify: required
:refines: RUL-library_lacking_stops

The report of a library whose filesystem fails at a requirement SHALL name the requirement.
:::

:::{rul} A library may lie across a network
:id: RUL-library_network_allowed
:status: ruled
:criticality: med
:anti: yes
:verify: required
:uses: DEF-merge, DEF-library

Merge SHALL NOT refuse a library for the kind of filesystem it lies on, a network filesystem among them, while that
filesystem does what merge needs of it.
:::

:::{rul} The library's room on another filesystem is checked before anything moves
:id: RUL-library_space_checked
:status: ruled
:criticality: med
:verify: required
:uses: DEF-merge, DEF-library

Merge's execution SHALL compare, before its first move, the free space of each filesystem other than the workspace's
that it is about to move photos onto — the library's, or one within it — with the room those photos ask.
:::

:::{rul} The room asked of a library holds a margin
:id: RUL-library_space_margin
:status: ruled
:criticality: med
:verify: required
:refines: RUL-library_space_checked

The room merge asks of a filesystem of the library other than the workspace's SHALL be the total size of the photos
it is about to move onto it and a margin on top of it, a share of that size the configuration sets.
:::

:::{rul} A library short of room stops the execution
:id: RUL-library_space_short_stops
:status: ruled
:criticality: med
:anti: yes
:verify: required
:refines: RUL-library_space_checked

An execution that finds the free space of a filesystem of the library short of the room it asks of it SHALL stop with
nothing moved.
:::

:::{rul} The stop names the room needed and the room free
:id: RUL-library_space_short_named
:status: ruled
:criticality: low
:verify: required
:refines: RUL-library_space_short_stops

The report of a library short of room SHALL name the space the photos need and the space free.
:::

:::{rul} Merge's plan warns of a library short of room
:id: RUL-library_space_warned_at_plan
:status: ruled
:criticality: low
:verify: required
:refines: RUL-library_space_checked

Merge's plan SHALL warn of a library its execution would find short of room, the plan written all the same.
:::

:::{rul} Merge runs only on the prep log the handoff vouches for
:id: RUL-merge_on_vouched_log
:status: ruled
:criticality: high
:anti: yes
:verify: required
:uses: RUL-unchecked_counts_as_changed

Merge SHALL NOT plan, dry-run or execute while prep's log is not the one the handoff vouches for.
:::

:::{rul} Merge needs no tracks folder
:id: RUL-merge_needs_no_tracks
:status: ruled
:criticality: med
:verify: required
:uses: DEF-merge, DEF-tracks

Merge SHALL proceed without the tracks folder, on the track points the workspace keeps.
:::

## Destination-to-library mapping

:::{rul} The library mirrors the destination tree
:id: RUL-library_mirrors_destinations
:status: ruled
:criticality: high
:anti: yes
:verify: required
:uses: DEF-library, DEF-managed_folders

Merge SHALL place each photo at the same path under the library as it holds under photos by destination — its folders
as the user built them, its name the one geotag gave it — the name an incoming photo is given on a collision, and the
case of the name under which the library already holds the photo ({need}`RUL-collision_same_content`), the only
changes.
:::

:::{rul} Photos sharing a fingerprint are each merged on their own
:id: RUL-shared_fingerprint_each_merged
:status: ruled
:criticality: high
:verify: required
:uses: DEF-merge, DEF-fingerprint, DEF-managed_folders, DEF-library

Photos in photos by destination that share a fingerprint SHALL each be merged and accounted for as a photo of its own.
:::

## Idempotency, resume, and non-destructiveness

:::{rul} A fresh plan is allowed at any time before the seal
:id: RUL-merge_replan_any_time
:status: ruled
:criticality: med
:verify: required
:refines: RUL-merge_resumable
:uses: DEF-merge, DEF-sealed_workspace

Merge SHALL allow a fresh plan at any time on a workspace not sealed, whatever an earlier run of it left.
:::

:::{rul} A fresh plan carries the photos earlier plans placed
:id: RUL-replan_carries_placed
:status: ruled
:criticality: high
:verify: required
:refines: RUL-merge_resumable
:uses: DEF-merge, DEF-library, DEF-fingerprint, DEF-managed_folders

A fresh plan SHALL carry forward every finalized photo no longer in photos by destination with the library place the
latest earlier plan of the workspace gave it whose place, checked again, holds it — whether or not the journal
recorded the move.
:::

:::{rul} A fresh plan carries every photo an earlier plan placed
:id: RUL-replan_carries_every_placed
:status: ruled
:criticality: high
:verify: required
:refines: RUL-replan_carries_placed
:uses: DEF-merge, DEF-merge_begun, DEF-library, DEF-finalize

A fresh plan SHALL carry forward every photo an earlier merge plan of the workspace placed in the library, whether or
not the workspace's latest finalize recorded it.
:::

:::{rul} A move an execution was stopped before recording is carried all the same
:id: RUL-unjournalled_move_carried
:status: ruled
:criticality: high
:verify: required
:refines: RUL-replan_carries_every_placed
:uses: DEF-merge, DEF-library, DEF-finalize

A fresh plan SHALL carry forward a photo the workspace's latest finalize did not record that an earlier merge execution
moved into the library and was stopped before recording — one that may still be in the workspace
({need}`RUL-unrecorded_place_needs_photo_gone`) aside.
:::

:::{rul} A place no execution recorded is not counted while the photo may still be in the workspace
:id: RUL-unrecorded_place_needs_photo_gone
:status: ruled
:criticality: high
:anti: yes
:verify: required
:excepts: RUL-unjournalled_move_carried
:uses: DEF-merge, DEF-fingerprint, DEF-finalize

A fresh plan SHALL NOT count as placed, on a place no merge execution recorded, a photo whose fingerprint the latest
finalize recorded under a path no earlier merge plan knows.
:::

:::{rul} A plan no execution began placed nothing
:id: RUL-unexecuted_plan_placed_nothing
:status: ruled
:criticality: high
:anti: yes
:verify: required
:refines: RUL-replan_carries_every_placed
:uses: DEF-merge, DEF-finalize

A fresh plan SHALL NOT count as placed a photo the workspace's latest finalize did not record that only merge plans no
execution began hold.
:::

:::{rul} An earlier place is confirmed by the bytes placed there
:id: RUL-placed_bytes_confirm_place
:status: ruled
:criticality: high
:verify: required
:refines: RUL-replan_carries_placed
:uses: DEF-merge, DEF-library, DEF-fingerprint

A library place an earlier execute recorded filling SHALL count as holding its photo while it holds the very bytes
placed there, whatever image engine version now takes the fingerprints.
:::

:::{rul} An earlier place counts only inside this library
:id: RUL-earlier_place_in_this_library
:status: ruled
:criticality: high
:anti: yes
:verify: required
:refines: RUL-replan_carries_placed

Merge SHALL count a photo an earlier plan placed as merged only while it lies inside the library now configured.
:::

:::{rul} A photo moved to its place in this library is carried
:id: RUL-earlier_place_moved_to_this_library
:status: ruled
:criticality: med
:verify: required
:refines: RUL-replan_carries_placed
:uses: DEF-merge, DEF-library

A fresh plan SHALL carry forward a finalized photo an earlier plan placed in another library where the library now
configured holds it at the same place within it.
:::

:::{rul} A photo a fresh plan cannot carry blocks
:id: RUL-replan_blocks_unaccounted
:status: ruled
:criticality: high
:anti: yes
:verify: required
:refines: RUL-replan_carries_placed
:uses: DEF-merge, DEF-library, DEF-fingerprint, DEF-managed_folders

A finalized photo no longer in photos by destination that a fresh plan cannot carry forward SHALL block.
:::

:::{rul} A photo blocked for not being carried is reported with why
:id: RUL-replan_block_names_why
:status: ruled
:criticality: high
:verify: required
:refines: RUL-replan_blocks_unaccounted
:uses: DEF-merge, DEF-library, DEF-fingerprint, DEF-managed_folders

The report of a photo blocked because a fresh plan cannot carry it forward SHALL name why it could not be carried.
:::

:::{rul} A resumed execution checks the library, not the journal
:id: RUL-resume_rechecks_library
:status: ruled
:criticality: high
:anti: yes
:verify: required
:refines: RUL-merge_resumable
:uses: DEF-merge, DEF-library, DEF-fingerprint

Merge's execution SHALL count a photo of its plan gone from photos by destination as merged only while its library
place, checked again, holds it — whatever the journal or the plan says.
:::

:::{rul} A photo gone from both places blocks at execution
:id: RUL-resume_blocks_missing
:status: ruled
:criticality: high
:anti: yes
:verify: required
:refines: RUL-resume_rechecks_library
:uses: DEF-merge, DEF-library, DEF-fingerprint

At merge's execution, a photo of its plan gone from photos by destination whose library place does not hold it SHALL
block.
:::

:::{rul} An execution with a photo gone from both places is never whole
:id: RUL-resume_block_makes_partial
:status: ruled
:criticality: high
:anti: yes
:verify: required
:refines: RUL-resume_blocks_missing
:uses: DEF-merge, DEF-library, DEF-fingerprint

An execution in which a photo gone from photos by destination blocks SHALL NOT end whole: it ends partial, or failed
where every photo was blocked.
:::

:::{rul} A record of merge's own that cannot be read stops it
:id: RUL-merge_unreadable_record_stops
:status: ruled
:criticality: high
:anti: yes
:verify: required
:uses: DEF-merge

Merge SHALL stop, naming the file and changing nothing, on a plan or journal of its own that it cannot read — never
taking it for an empty one.
:::

## User-visible outputs and the merge summary

:::{rul} Merge records how its run ended
:id: RUL-merge_outcome_recorded
:status: ruled
:criticality: med
:verify: required
:uses: DEF-merge

Merge SHALL record whether its execution succeeded whole, in part or not at all, or stopped before its first move for
want of a required snapshot or of room in the library.
:::

:::{rul} No other stop writes merge's summary
:id: RUL-merge_summary_only_for_execution
:status: ruled
:criticality: low
:anti: yes
:verify: required
:refines: RUL-merge_outcome_recorded
:uses: DEF-merge

Merge SHALL write no summary for a run stopped before its execution began by anything but the want of a required
snapshot or of room in the library — a precondition, a plan no longer current, or a plan or journal of its own it cannot
read — nor for a run interrupted, leaving the summary an earlier run wrote as it was.
:::

:::{rul} Merge keeps each execution's summary
:id: RUL-merge_run_records_kept
:status: ruled
:criticality: med
:anti: yes
:verify: required
:uses: DEF-merge

Merge SHALL never overwrite an execution's summary: written again, the earlier one is first set aside, recoverably.
:::

:::{rul} Merge tells what it placed
:id: RUL-merge_run_reported
:status: ruled
:criticality: low
:verify: required
:uses: DEF-merge, DEF-library

At the end of an execution merge SHALL report what it placed in the library.
:::

:::{rul} Merge tells what was already in the library
:id: RUL-merge_reports_already_present
:status: ruled
:criticality: low
:verify: required
:refines: RUL-merge_run_reported
:uses: DEF-merge, DEF-library

At the end of an execution merge SHALL report what was already in the library.
:::

:::{rul} Merge tells each photo it left, with why
:id: RUL-merge_reports_left_with_why
:status: ruled
:criticality: low
:verify: required
:refines: RUL-merge_run_reported
:uses: DEF-merge, DEF-managed_folders

At the end of an execution merge SHALL report each photo left in photos by destination, with why.
:::

:::{rul} Merge tells whether the workspace is sealed
:id: RUL-merge_reports_sealed
:status: ruled
:criticality: low
:verify: required
:refines: RUL-merge_run_reported
:uses: DEF-merge, DEF-sealed_workspace

At the end of an execution merge SHALL report whether the workspace is now sealed.
:::
