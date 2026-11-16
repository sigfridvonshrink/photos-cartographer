# Merge — what it guarantees

What the last phase, {need}`DEF-merge`, guarantees, beyond what [the shared contract](shared.md) binds every phase
to — most of merge's rules are there, in its section on the library and the seal. *Why* each holds is in
[the rationale](../rationale/merge.md); *how this build meets it*, in [the build](../build/merge.md).

## 1. Scope and boundary

:::{rul} Merge checks prep's fingerprints under another ImageMagick
:id: RUL-merge_rechecks_under_new_engine
:status: ruled
:criticality: high
:anti: yes
:verify: required
:refines: RUL-engine_change_is_checked
:uses: DEF-fingerprint, DEF-library

Under an ImageMagick version other than the one prep's fingerprints were taken by, merge SHALL take each photo's
fingerprint again before comparing it with the library's.
:::

:::{rul} A photo whose fingerprint changed is left unmerged
:id: RUL-merge_changed_fingerprint_unmerged
:status: ruled
:criticality: high
:verify: required
:refines: RUL-merge_rechecks_under_new_engine
:uses: DEF-fingerprint, DEF-library

A photo whose fingerprint, taken again by merge, has changed SHALL be left in photos by destination, unmerged.
:::

## 2. Preconditions

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

:::{rul} Merge takes no photo without a position
:id: RUL-merge_refuses_unplaced
:status: ruled
:criticality: high
:anti: yes
:verify: required
:refines: RUL-merge_rechecks_gates
:uses: DEF-merge, RUL-finalize_refuses_unplaced

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

A merge a precondition stops SHALL change nothing in the library, the workspace's photos or merge's records.
:::

:::{rul} A photo with no fingerprint stops merge
:id: RUL-unfingerprinted_photo_stops_merge
:status: ruled
:criticality: high
:anti: yes
:verify: required

Merge SHALL NOT plan or execute while a photo in photos by destination has no fingerprint.
:::

:::{rul} A hidden entry among the photos stops merge
:id: RUL-hidden_among_photos_stops_merge
:status: ruled
:criticality: high
:anti: yes
:verify: required

Merge SHALL NOT proceed while photos by destination holds a hidden file or folder.
:::

:::{rul} Merge stops without ImageMagick
:id: RUL-imagemagick_absent_stops_merge
:status: ruled
:criticality: high
:anti: yes
:verify: required
:uses: DEF-merge, DEF-fingerprint

Merge SHALL NOT plan, dry-run or execute while ImageMagick, by which it fingerprints a file, is absent.
:::


:::{rul} What merge needs of the library's filesystem is tried at its start
:id: RUL-library_requirements_tried
:status: ruled
:criticality: high
:anti: yes
:verify: required
:refines: RUL-filesystem_agnostic
:uses: DEF-merge, DEF-library, RUL-library_confirmed_before_lock

Merge's plan, dry run and execution SHALL try on the library's filesystem its lock, the move that fails where its
target exists, and syncing a file and a folder — once the library's mark has confirmed it, and before its lock is
taken.
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

:::{rul} A library on another filesystem is checked for room before anything moves
:id: RUL-library_space_checked
:status: ruled
:criticality: med
:verify: required
:uses: DEF-merge, DEF-library

Where the library lies on another filesystem than the workspace, merge's execution SHALL compare, before its first
move, the library's free space with the total size of the photos it is about to move into it.
:::

:::{rul} The room asked of a library holds a margin
:id: RUL-library_space_margin
:status: ruled
:criticality: med
:verify: required
:refines: RUL-library_space_checked

The room merge asks of a library on another filesystem SHALL be the photos' total size and a margin on top of it, a
share of that size the configuration sets.
:::

:::{rul} A library short of room stops the execution
:id: RUL-library_space_short_stops
:status: ruled
:criticality: med
:anti: yes
:verify: required
:refines: RUL-library_space_checked

An execution that finds the library's free space short of the photos it is about to move SHALL stop with nothing
moved.
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

## 4. Destination-to-library mapping

:::{rul} The library mirrors the destination tree
:id: RUL-library_mirrors_destinations
:status: ruled
:criticality: high
:anti: yes
:verify: required
:uses: DEF-library, DEF-managed_folders

Merge SHALL place each photo at the same path under the library as it holds under photos by destination — its folders
as the user built them, its name the one geotag gave it — the name an incoming photo is given on a collision the only
change.
:::

## 5. Idempotency, resume, and non-destructiveness

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
:anti: yes
:verify: required
:refines: RUL-merge_resumable
:uses: DEF-merge, DEF-library, DEF-fingerprint, DEF-managed_folders

A fresh plan SHALL carry forward every finalized photo no longer in photos by destination with the library place the
latest earlier plan of the workspace gave it whose place, fingerprinted again, holds it — whether or not the journal
recorded the move.
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

:::{rul} The blocker for a photo not carried names why
:id: RUL-replan_block_names_why
:status: ruled
:criticality: high
:verify: required
:refines: RUL-replan_blocks_unaccounted
:uses: DEF-merge, DEF-library, DEF-fingerprint, DEF-managed_folders

The blocker for a photo a fresh plan cannot carry forward SHALL name why.
:::

:::{rul} A resumed merge checks the library, not the journal
:id: RUL-resume_rechecks_library
:status: ruled
:criticality: high
:anti: yes
:verify: required
:refines: RUL-merge_resumable
:uses: DEF-merge, DEF-library, DEF-fingerprint

A photo gone from photos by destination SHALL count as merged only while its library place, fingerprinted again, holds
it — whatever the journal or the plan says.
:::

:::{rul} A photo gone from both places blocks
:id: RUL-resume_blocks_missing
:status: ruled
:criticality: high
:verify: required
:refines: RUL-resume_rechecks_library
:uses: DEF-merge, DEF-library, DEF-fingerprint

A photo gone from photos by destination whose library place does not hold it SHALL block.
:::

:::{rul} A run with a photo gone from both places is partial
:id: RUL-resume_block_makes_partial
:status: ruled
:criticality: high
:verify: required
:refines: RUL-resume_blocks_missing
:uses: DEF-merge, DEF-library, DEF-fingerprint

A run in which a photo gone from photos by destination blocks SHALL be partial.
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

## 6. User-visible outputs and the merge summary

:::{rul} Merge records how its run ended
:id: RUL-merge_outcome_recorded
:status: ruled
:criticality: med
:verify: required
:refines: RUL-merge_records_landing
:uses: DEF-merge

Merge SHALL record whether its run succeeded whole, in part or not at all, or was refused before changing anything.
:::

:::{rul} Merge's summary is written only for an execution
:id: RUL-merge_summary_only_for_execution
:status: ruled
:criticality: low
:verify: required
:refines: RUL-merge_outcome_recorded
:uses: DEF-merge

Merge SHALL write no summary for a run stopped before its execution began — by a precondition, or a plan or journal it
would not use — nor for a run interrupted, leaving the summary an earlier run wrote as it was.
:::

:::{rul} Merge tells how its run ended
:id: RUL-merge_run_reported
:status: ruled
:criticality: low
:verify: required
:uses: DEF-merge, DEF-library, DEF-managed_folders, DEF-sealed_workspace

At the end of an execution merge SHALL report what it placed in the library, what was already there, each photo left in
photos by destination with why, and whether the workspace is now sealed.
:::
