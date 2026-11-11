# Prep — why

**Not normative.** Each item here is the reasoning behind the [intent](../intent/prep.md) or [build](../build/prep.md)
items it `justifies`, under the same section numbers. Where the two differ, the intent wins and this is stale.

## 2. What prep does, and what it leaves alone

:::{rat} Prep has no evidence for a time or a place
:id: RAT-prep_has_no_evidence
:status: ruled
:justifies: RUL-prep_no_time_or_gps

A photo's true time and place need what prep does not have: the camera's clock offset, found by geotag against the
tracks or given by the user, and the timezone of the destination the user sorts the photo into. A correction made
before them would be a guess written into an original; prep leaves time and place whole for geotag.
:::

:::{rat} Photos by destination is the user's sorting
:id: RAT-by_dest_is_the_users
:status: ruled
:justifies: RUL-prep_leaves_by_dest_as_found

Photos by destination is the user's own sorting: where each photo sits is a decision made by hand, which only the user
can make or change. Prep records what it finds there — a new sort included — and changes nothing, so a decision is
never undone by a run that cannot know why it was made.
:::

:::{rat} Videos are kept, not corrected
:id: RAT-videos_kept_not_corrected
:status: ruled
:justifies: RUL-videos_by_date

The pipeline's aim is photos placed in time and on the map. Videos arrive in the same dumps; prep organizes them by date
so they are neither lost nor scattered, not because the pipeline means to correct them — so they keep a folder of their
own, out of the sort.
:::

## 3. The workspace's first run, and the strays

:::{rat} The first gesture bootstraps the workspace
:id: RAT-bootstrap_once
:status: ruled
:justifies: RUL-init_moves_dump_to_inbox

Dropping a dump into a bare folder is the most natural first gesture, so the first run takes it as it comes: it builds
the structure around the dump and moves it into the inbox whole, its folders kept, for a dump's folders often carry
meaning — a trip, a day, a card. Afterwards the workspace has an inbox, and the top level is no place for a dump.
:::

:::{rat} The structure's names are reserved
:id: RAT-structure_names_reserved
:status: ruled
:justifies: RUL-dump_folder_named_as_managed

A managed folder's name is reserved for the structure. Moving a folder of that name into the inbox would nest a managed
folder inside another, where nothing would look for it, and leave its place to be made again empty beside it.
:::

:::{rat} The mark means the workspace is whole
:id: RAT-mark_means_whole
:status: ruled
:justifies: RUL-initialized_marked_last

The mark says the workspace is whole. Written before the folders, a run that died halfway would leave a workspace marked
whole but missing a folder, and every later run would refuse it as disturbed; written last, a dead run leaves no mark,
and the next simply initializes again.
:::

:::{rat} A stray is not the pipeline's to answer for
:id: RAT-strays_not_the_pipelines
:status: ruled
:justifies: RUL-strays_leave_no_trace

A stray is a file cartographer does not understand — a document, a sidecar it has no use for. Recorded beside the media,
it would make cartographer answer for what it cannot reason about; parked whole, it waits for the user to keep or clear
it, and clearing it costs the record nothing.
:::
