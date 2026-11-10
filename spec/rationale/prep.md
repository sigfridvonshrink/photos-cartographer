# Prep — why

**Not normative.** Each item here is the reasoning behind the [intent](../intent/prep.md) or [build](../build/prep.md)
items it `justifies`, under the same section numbers. Where the two differ, the intent wins and this is stale.

## 2. What prep does, and what it leaves alone

:::{rat} Prep has no evidence for a time or a place
:id: RAT-prep_has_no_evidence
:status: seed
:justifies: RUL-prep_no_time_or_gps

A photo's true time and place need what prep does not have: the camera's clock offset, found by geotag against the
tracks or given by the user, and the timezone of the destination the user sorts the photo into. A correction made
before them would be a guess written into an original; prep leaves time and place whole for geotag.
:::

:::{rat} Photos by destination is the user's sorting
:id: RAT-by_dest_is_the_users
:status: seed
:justifies: RUL-prep_leaves_by_dest_as_found

Photos by destination is the user's own sorting: where each photo sits is a decision made by hand, which only the user
can make or change. Prep records what it finds there — a new sort included — and changes nothing, so a decision is
never undone by a run that cannot know why it was made.
:::

:::{rat} Videos are kept, not corrected
:id: RAT-videos_kept_not_corrected
:status: seed
:justifies: RUL-videos_by_date

The pipeline's aim is photos placed in time and on the map. Videos arrive in the same dumps; prep organizes them by date
so they are neither lost nor scattered, not because the pipeline means to correct them — so they keep a folder of their
own, out of the sort.
:::
