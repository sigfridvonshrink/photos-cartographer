# Merge — why

**Not normative.** Each item here is the reasoning behind the [intent](../intent/merge.md) or [build](../build/merge.md)
items it `justifies`, under the same section numbers. Where the two differ, the intent wins and this is stale.
Sections are numbered as in the phase's original spec; a section whose content lives in the shared contract, or
that only restated others, has no heading here.

## 2. Scope and boundary

:::{rat} One version on both sides of a comparison
:id: RAT-one_version_per_comparison
:status: ruled
:justifies: RUL-merge_rechecks_under_new_engine

Merge compares prep's fingerprint of a photo with one it takes now of the library file in its way. Taken by two
versions of ImageMagick, two fingerprints of the same pixels may differ: the photo would be called new and placed again,
renamed, beside itself — a duplicate in the library, which merge must never make. Taken again under the version now in
use, prep's fingerprint is confirmed and the comparison holds. A photo whose fingerprint did change waits in photos by
destination: what geotag recorded of it is keyed by the old value, and merging it would carry a record that names no
photo into the library's history.
:::

## 3. Preconditions

:::{rat} The workspace may have been touched since geotag
:id: RAT-touched_since_geotag
:status: ruled
:justifies: RUL-merge_rechecks_gates

Geotag's gates held when geotag ran; merge runs later, often much later, and the user may have dropped a new dump into
the inbox, moved a photo back to photos by date, or put a video or a development folder among the photos by
destination in between. Merge is the step after which none of that can be undone cheaply: what it places is in the
library, beside photos it must never disturb. So it asks the workspace again, not geotag's record of it. The folders
the gates leave out are the residue the library never receives; they stay in the workspace, as they would for geotag.
:::

:::{rat} A refused merge leaves nothing to clean up
:id: RAT-refused_merge_clean
:status: ruled
:justifies: RUL-merge_blocked_changes_nothing

The library is the one place the pipeline cannot simply re-plan from: a photo half placed there, or a summary
claiming a merge that did not happen, would have to be found and undone by hand. Checking every precondition before
the first change makes a refusal free — fix the cause, run merge again — and keeps merge's records describing only
merges that ran.
:::

## 6. Destination-to-library mapping

:::{rat} The destination tree is the library's organisation
:id: RAT-destination_tree_is_the_library
:status: ruled
:justifies: RUL-library_mirrors_destinations

The user builds photos by destination as the library should read — country, city, place — and the library, browsed
folder by folder, is that tree grown over many workspaces. Any transform on the way in, a year prefixed or a level
flattened, would be a decision about the library's organisation the user never made, and one a later workspace could
make differently. Kept the same, a photo's place in the library is the place the user chose for it, and the same on
every run, which is what lets an interrupted merge find its own work.
:::

## 8. Idempotency, resume, and non-destructiveness

:::{rat} A partial merge is never a dead end
:id: RAT-partial_merge_no_dead_end
:status: ruled
:justifies: RUL-merge_replan_any_time

A partial merge leaves the cause of its blockers for the user to fix — a library file that could not be read, a photo
changed — and some fixes change what the plan must say. Until the seal, nothing merge has done is final, and its
records describe what happened rather than gate what may happen next; refusing to re-plan would leave the user with a
plan that can no longer finish and no way to make one that can.
:::

:::{rat} The library is the evidence of a move
:id: RAT-library_is_evidence_of_move
:status: ruled
:justifies: RUL-replan_carries_placed, RUL-resume_rechecks_library

The journal is written after a move, so a crash or a Ctrl-C can leave a photo in the library with no entry for it; and
the library is the user's, so a photo a journal entry vouches for may since have been moved or replaced there. Either
way the journal and the library disagree, and only the library says where the photo is. Trusting the journal would
block forever a photo safely placed, or seal a workspace whose merge log names a library file that no longer holds the
photo — a record the user would rely on to find it. Fingerprinting the place again settles it, and costs a read only on
a resume.
:::

## 9. User-visible outputs and the merge summary

:::{rat} The run's end decides what to do next
:id: RAT-merge_outcome_decides_next
:status: ruled
:justifies: RUL-merge_outcome_recorded

What the user does after a merge turns on how it ended: nothing after a whole success, a fix and another run after a
partial one or a failed one, and after a refusal a fix with nothing to undo, the library untouched. Counts alone cannot
tell a refusal from a run that found nothing to do; a recorded outcome says which, long after the terminal has gone.
:::

:::{rat} Merge is the step the user watches
:id: RAT-merge_report_at_the_end
:status: ruled
:justifies: RUL-merge_run_reported

Merge is the step that puts photos where the user will look for them, and the one that ends the workspace. Its report
is the moment the user learns whether the batch is in, which photos are not and what to fix — without opening the
summary — and that the workspace is now finished, so the next dump belongs in a fresh one.
:::
