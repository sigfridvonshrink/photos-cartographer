# Merge — why

**Not normative.** Each item here is the reasoning behind the [intent](../intent/merge.md) or [build](../build/merge.md)
items it `justifies`, under the same section numbers. Where the two differ, the intent wins and this is stale.

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
:status: seed
:justifies: RUL-library_mirrors_destinations

The user builds photos by destination as the library should read — country, city, place — and the library, browsed
folder by folder, is that tree grown over many workspaces. Any transform on the way in, a year prefixed or a level
flattened, would be a decision about the library's organisation the user never made, and one a later workspace could
make differently. Kept the same, a photo's place in the library is the place the user chose for it, and the same on
every run, which is what lets an interrupted merge find its own work.
:::
