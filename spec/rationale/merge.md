# Merge — why

**Not normative.** Each item here is the reasoning behind the [intent](../intent/merge.md) or [build](../build/merge.md)
items it `justifies`. Where the two differ, the intent wins and this is stale.

## Scope and boundary

:::{rat} One version on both sides of a comparison
:id: RAT-one_version_per_comparison
:status: ruled
:forced: yes
:follows_from: RAT-decoded_pixel_identity, RAT-fingerprint_same_method
:justifies: RUL-merge_rechecks_under_new_engine

Merge compares prep's fingerprint of a photo with one it takes now of the library file in its way. Taken by two
versions of ImageMagick, two fingerprints of the same pixels may differ: the photo would be called new and placed again,
renamed, beside itself — a duplicate in the library, the very thing comparing by content is there to prevent. Taken
again under the version now in use, prep's fingerprint is confirmed and the comparison holds. A photo whose fingerprint
did change is compared by its new value, which is the one the library's files are fingerprinted under
({need}`RAT-changed_fingerprint_mapped`).
:::

:::{rat} The archive outlives any one ImageMagick
:id: RAT-changed_fingerprint_mapped
:status: ruled
:forced: no
:follows_from: RAT-one_version_per_comparison, RAT-new_version_may_change_nothing
:justifies: RUL-merge_merges_changed_fingerprint, RUL-changed_fingerprint_mapping_recorded, RUL-merge_changed_fingerprint_unmerged

What prep and geotag recorded of a photo is keyed by its fingerprint under the ImageMagick that prepped the workspace,
and finalize sealed those records into the package. A newer ImageMagick may read the same photo to another value; held
back for that alone, the photo could reach the library only under the version that prepped it, which in time is gone.
The archive outlives any one ImageMagick. So merge does not rewrite what is sealed — geotag's records stay as finalize
left them, keyed by the old value — and writes, in its own package, the old value beside the new, each with its
version: the records stay readable from either side.

A mapping is only as good as the proof that the two values are one photo's. Finalize's record of each photo's path,
size and modification time proves the file merge reads is the one geotag treated, and a new value that no other photo
holds, now or under prep's version, leaves every record pointing at one photo. Where two photos' values meet under the
new version, or one's new value is another's old one, prep's duplicate decisions would not be the same under it: no
mapping can settle which photo a value names, and those photos wait in photos by destination, as any photo merge
cannot prove.
:::

:::{rat} One value moved whole to one value is still one to one
:id: RAT-shared_value_moved_whole
:status: ruled
:forced: no
:follows_from: RAT-changed_fingerprint_mapped, RAT-shared_fingerprint_two_photos
:justifies: RUL-shared_value_moved_together_merged

Photos prep held under one value are, to prep and to every record keyed by that value, one picture — the same picture
the user sorted into more than one destination. Where every one of them reads as one new value under the new version,
and no other photo holds it, the mapping between values is still one to one: the old value to the new, and back. What
the one-to-one test guards against is two pictures prep told apart collapsing into one value, or one value splitting in
two, so that a record keyed by a value would come to name another picture; neither happens here. Held back, each such
photo would wait in photos by destination for a reason no record shows, as long as that version is in use.
:::

## Preconditions

:::{rat} The workspace may have been touched since geotag
:id: RAT-touched_since_geotag
:status: ruled
:forced: yes
:follows_from: RAT-discrete_stages, RAT-non_destructive_core
:justifies: RUL-merge_rechecks_gates, RUL-merge_gates_leave_out_residue

Geotag's gates held when geotag ran; merge runs later, often much later, and the user may have dropped a new dump into
the inbox, moved a photo back to photos by date, or put a video or a development folder among the photos by
destination in between. Merge is the step after which none of that can be undone cheaply: what it places is in the
library, beside photos it must never disturb. So it asks the workspace again, not geotag's record of it. The folders
the gates leave out are the residue the library never receives; they stay in the workspace, as they would for geotag.
:::

:::{rat} A refused merge leaves nothing to clean up
:id: RAT-refused_merge_clean
:status: ruled
:forced: yes
:follows_from: RAT-no_mutation_outside_plan, RAT-recoverable_core
:justifies: RUL-merge_blocked_changes_nothing

The library is the one place the pipeline cannot simply re-plan from: a photo half placed there, or a summary
claiming a merge that did not happen, would have to be found and undone by hand. Checking every precondition before
the first change makes a refusal free — fix the cause, run merge again — and keeps merge's records describing only
merges that ran.
:::

:::{rat} Without its fingerprints merge can settle nothing
:id: RAT-merge_needs_its_fingerprints
:status: ruled
:forced: yes
:follows_from: RAT-decoded_pixel_identity, RAT-library_is_evidence_of_move
:justifies: RUL-image_engine_absent_stops_merge

A place merge finds taken is settled by fingerprinting the file there, and a photo gone from the workspace counts as
merged only once its place is read again — by the digest of the bytes merge placed there, else by its fingerprint.
Without ImageMagick no fingerprint can be taken: every collision would block, a photo already moved whose place no
digest vouches for could not be confirmed, and a merge left half done might never be finished. Run so, it
would turn a merge that could be whole into a partial one; stopped, it changes nothing until the tool is back.
:::

:::{rat} A library may lie across a network, and two machines merging at once is the user's to avoid
:id: RAT-library_across_network
:status: ruled
:forced: no
:follows_from: RAT-library_shared, RAT-live_lock_never_taken
:justifies: RUL-library_network_allowed

A library is often kept on a server, shared by the machines that read it; refusing one there would refuse the common
case. Its lock then may guard the merges of one machine only, on some network filesystems, and which ones cannot be
told reliably from a run. Running merges from two machines into one library at once is therefore the user's to avoid.
What it would cost is bounded: every placement is a move that fails where its target exists, so a photo the other
merge placed first under the same name is found there and settled by its content — the same photo already present,
another one blocked — and never overwritten. The worst is one photo failing and staying in the workspace — its place
taken by the other merge's photo, or its temporary copy cleared by the other merge as debris — or, where the two saw
the library differently, a photo placed under two names.
:::

:::{rat} A library short of room is found before the first photo moves
:id: RAT-library_room_before_moving
:status: ruled
:forced: no
:follows_from: RAT-refused_merge_clean, RAT-safe_at_each_change
:justifies: RUL-library_space_checked, RUL-library_space_short_stops, RUL-library_space_short_named, RUL-library_space_warned_at_plan, RUL-library_space_margin

Into a library on another filesystem merge copies each photo before removing it from the workspace. A full disk is
safe — the photo it fails stays in the workspace and the run ends partial — but the shortage shows late, one photo at a
time, after part of the batch has moved. Comparing the free space with the batch first turns it into a refusal that
says how much room is needed, before anything moved; the plan says it as a warning, since room can be made before
execute. On the workspace's own filesystem a move is a rename and takes no room, so there is nothing to compare.

The comparison asks for more than the photos' own size: a filesystem filled to its last byte slows and fragments, and
the library is not merge's alone — digiKam writes its thumbnails and sidecars beside the photos. The owner, ruling it
(2026-11-16): *"I think a safety margin is needed. Configurable, too, default say 5% on top of by-dest size?"*
:::

## Destination-to-library mapping

:::{rat} The destination tree is the library's organisation
:id: RAT-destination_tree_is_the_library
:status: ruled
:forced: yes
:follows_from: RAT-piggyback_on_the_destination_sort, CHC-local_folder_library
:justifies: RUL-library_mirrors_destinations

The user builds photos by destination as the library should read — country, city, place — and the library, browsed
folder by folder, is that tree grown over many workspaces. Any transform on the way in, a year prefixed or a level
flattened, would be a decision about the library's organisation the user never made, and one a later workspace could
make differently. Kept the same, a photo's place in the library is the place the user chose for it, and the same on
every run, which is what lets an interrupted merge find its own work.
:::

:::{rat} The same picture in two destinations is two photos
:id: RAT-shared_fingerprint_two_photos
:status: ruled
:forced: yes
:follows_from: RAT-destination_tree_is_the_library, RAT-library_is_evidence_of_move
:justifies: RUL-shared_fingerprint_each_merged

The user may sort one picture into two destinations on purpose — a view of the Louvre belongs under Paris and under the
Louvre — and prep, which leaves photos by destination as the user sorted it, keeps both. They share a fingerprint, but
each has its own place in the workspace, its own name from geotag and its own place in the library. A record of one
says nothing of where the other is: taken one for the other, a copy would be given the other's name, a copy deleted
from the library would be carried on the record of the one still there, and the workspace would seal with that photo
in neither place, its merge log naming one copy twice and the other never.
:::

## Idempotency, resume, and non-destructiveness

:::{rat} A partial merge is never a dead end
:id: RAT-partial_merge_no_dead_end
:status: ruled
:forced: yes
:follows_from: RAT-recoverable_core, RAT-idempotent_reruns
:justifies: RUL-merge_replan_any_time

A partial merge leaves the cause of each blocked photo for the user to fix — a library file that could not be read, a
photo changed — and some fixes change what the plan must say. Until the seal, nothing merge has done is final, and its
records describe what happened rather than gate what may happen next; refusing to re-plan would leave the user with a
plan that can no longer finish and no way to make one that can.
:::

:::{rat} Prep and geotag stay open in a merge begun
:id: RAT-merge_begun_stays_open
:status: ruled
:forced: yes
:follows_from: RAT-partial_merge_no_dead_end, RAT-loop_is_steady_state
:justifies: RUL-geotag_rerunnable, RUL-more_dumps_until_merge

Some fixes for a photo a partial merge blocked are prep's or geotag's: a photo changed since finalize, a position to
give, a photo to rename and record again. Refusing prep and geotag once merge had moved a photo would strand every
such photo in photos by destination, with nothing the user could do but start over; only the seal, after which the
workspace holds nothing more to merge, closes the loop.
:::

:::{rat} A photo merge placed stays the workspace's
:id: RAT-placed_photo_stays_the_workspaces
:status: ruled
:forced: yes
:follows_from: RAT-merge_begun_stays_open, RAT-library_is_evidence_of_move
:justifies: RUL-replan_carries_every_placed

Prep and geotag, run again in a merge begun, see only what is still in photos by destination; finalize then records
only those, and a photo merge already placed would drop out of the plan that seals — neither carried nor blocked —
leaving the sealed record with no place for a photo the workspace put in the library. The sealed record must say where
every photo of the workspace went, and a photo merge placed is the workspace's whatever geotag was run on afterwards:
so a fresh plan takes it from the earlier plan that placed it, its place checked again like that of any photo carried
forward.
:::

:::{rat} A move is known by more than its record
:id: RAT-unrecorded_move_known_by_its_traces
:status: ruled
:forced: no
:follows_from: RAT-placed_photo_stays_the_workspaces, RAT-library_is_evidence_of_move
:justifies: RUL-unjournalled_move_carried, RUL-unrecorded_place_needs_photo_gone, RUL-unexecuted_plan_placed_nothing

A move is recorded just after it is made, so an execution killed between the two leaves a photo in the library that no
record says it placed; were prep and geotag then run again, the photo would be in no finalized set either, and the
sealed record would miss it. The place holding the picture is not proof enough alone: a photo already in the library
was there before any execution, so a plan never executed proves nothing by it; and a photo renamed or sorted elsewhere
since is still in the workspace under a path no earlier plan knows, to be merged as itself. With an execution of the
plan begun, the place it gave the photo holding it, and the photo nowhere the workspace could still hold it, the move
is taken as made.
:::

:::{rat} The library is the evidence of a move
:id: RAT-library_is_evidence_of_move
:status: ruled
:forced: yes
:follows_from: RAT-discrete_stages, RAT-decoded_pixel_identity
:justifies: RUL-replan_carries_placed, RUL-resume_rechecks_library

The journal is written after a move, so a crash or a Ctrl-C can leave a photo in the library with no entry for it; and
the library is the user's, so a photo a journal entry vouches for may since have been moved or replaced there. Either
way the journal and the library disagree, and only the library says where the photo is. Trusting the journal would
block forever a photo safely placed, or seal a workspace whose merge log names a library file that no longer holds the
photo — a record the user would rely on to find it. Reading the place again settles it — by the digest of the bytes
merge placed there, where merge recorded one, else by its fingerprint — and costs a read only on a resume.
:::

:::{rat} A placed file is known by its bytes, which no ImageMagick reads differently
:id: RAT-placed_bytes_outlive_engine
:status: ruled
:forced: no
:follows_from: RAT-library_is_evidence_of_move, RAT-one_version_per_comparison
:justifies: RUL-placed_bytes_confirm_place

A merge left partial may be finished months later, and ImageMagick may be upgraded in between — the very case merge
takes prep's fingerprints again for. A photo already placed is then fingerprinted under the new version and compared
with the value the earlier plan recorded under the old; where the upgrade changed it, the photo would block as gone from
its place, a reason that is not true, and the workspace could never seal while that version is in use. Merge placed the
file itself, so it can know it by what no version reads differently: the digest of its bytes, taken as it lands. A
place still holding those bytes holds the photo. Where no digest was recorded — a move that finished without its
journal entry — or the library's copy has since been rewritten, the fingerprint is the evidence left, as before.
:::

:::{rat} A record that cannot be read is not an empty one
:id: RAT-merge_unreadable_record_not_empty
:status: ruled
:forced: yes
:follows_from: RAT-library_is_evidence_of_move, RAT-durable_record
:justifies: RUL-merge_unreadable_record_stops

Merge's earlier plans say where its photos went, and its journal what it confirmed. Read as empty, an earlier plan
drops out and a photo it placed blocks for a reason that is not true — that no merge placed it; a journal read as
empty is written over by the run's first confirmation, and what it held is gone. Stopped, merge names the file to
repair or restore, and has lost nothing.
:::

:::{rat} A photo the user moved into this library is in it
:id: RAT-moved_into_this_library
:status: ruled
:forced: no
:follows_from: RAT-merged_means_in_this_library, RAT-library_is_evidence_of_move
:justifies: RUL-earlier_place_moved_to_this_library

A photo left in a library the setting has since been pointed away from blocks, and there are two ways on: point the
setting back, or move the photo to its place in the library now named. The second is the user's own move of a photo
merge had placed and checked. Found there, the photo itself, it is in the library the seal will name — which is all
that counting it merged ever meant — and a plan that still blocked it would leave moving it back as the only way to
finish.
:::

:::{rat} Another library's photos are not in this one
:id: RAT-merged_means_in_this_library
:status: ruled
:forced: no
:follows_from: RAT-non_destructive_core, RAT-library_is_evidence_of_move, RAT-seal_not_folder_state
:justifies: RUL-earlier_place_in_this_library

The seal says the workspace's photos are in the library it names. A photo placed where the setting used to point is somewhere else, and counting it would seal the workspace over a library that does not hold it.
:::


## User-visible outputs and the merge summary

:::{rat} The run's end decides what to do next
:id: RAT-merge_outcome_decides_next
:status: ruled
:forced: yes
:follows_from: RAT-consolidated_log
:justifies: RUL-merge_outcome_recorded

What the user does after a merge turns on how it ended: nothing after a whole success, a fix and another run after a
partial one or a failed one, and after a refusal a fix with nothing to undo, the library untouched. Counts alone cannot
tell a refusal from a run that found nothing to do; a recorded outcome says which, long after the terminal has gone.
:::

:::{rat} The summary records an execution
:id: RAT-summary_records_an_execution
:status: ruled
:forced: no
:follows_from: RAT-merge_outcome_decides_next, RAT-refused_merge_clean
:justifies: RUL-merge_summary_only_for_execution

The summary is the record of an execution: what it placed, what it left and how it ended. An execution that took its
plan as current and then could not make its first move — no required snapshot, no room in the library — was refused for
what the machine lacked, not for what the plan or the workspace held; its summary records the refusal and its reason, so
a fix with nothing to undo is told from a run that found nothing to do. A run stopped at the door — its plan stale or
unreadable, its preflight refused — executed nothing, and the terminal has said why; a summary written for it would put
a record of nothing over that of the last merge that ran. An interrupted run reached no end to record: its journal holds
what it confirmed, and the run that finishes it writes the summary.
:::

:::{rat} Merge is the step the user watches
:id: RAT-merge_report_at_the_end
:status: ruled
:forced: no
:follows_from: RAT-remainder_worklist, RAT-workspace_not_recycled
:justifies: RUL-merge_run_reported, RUL-merge_reports_left_with_why, RUL-merge_reports_sealed

Merge is the step that puts photos where the user will look for them, and the one that ends the workspace. Its report
is the moment the user learns whether the batch is in, which photos are not and what to fix — without opening the
summary — and that the workspace is now finished, so the next dump belongs in a fresh one.
:::
