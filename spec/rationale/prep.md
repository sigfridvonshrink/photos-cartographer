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

## 6. What prep refuses to work on

:::{rat} Photos and videos go separate ways
:id: RAT-bands_never_mix
:status: ruled
:justifies: RUL-band_misplacement_blocks

Photos are sorted into destinations and geotagged; videos are kept by date and not corrected. A file in the other kind's
folder would be handled as what it is not — a video sorted where geotag cannot place it, a photo kept where it is never
corrected. Prep never puts one there, so one found there was moved by hand, and only the user knows where it belongs.
:::

:::{rat} A sidecar would be orphaned
:id: RAT-sidecar_orphaned
:status: ruled
:justifies: RUL-sidecar_blocks

A sidecar is tied to its photo by name. Prep renames and moves photos, so the sidecar would be left behind under the old
name, its development lost without a word. Development belongs in the library, after merge
({need}`RUL-development_after_merge`); a sidecar arriving with the dump is the user's to keep or discard before prep
goes on.
:::

:::{rat} A non-media file outside the inbox got there another way
:id: RAT-other_outside_inbox_is_the_users
:status: ruled
:justifies: RUL-other_outside_inbox_blocks

Prep sets files of no media class aside only from the inbox, where a dump arrives mixed. Outside it, such a file got
there another way: an extension the user has since taken off the lists, which turns organized photos into files of no
class, or a file the user put there by hand. Moving it would guess which; leaving it unsaid would keep among the media a
file nothing accounts for. Stopping names it, and the user decides — as for a misnamed file.
:::

:::{rat} All the problems at once
:id: RAT-every_blocker_at_once
:status: ruled
:justifies: RUL-blockers_all_reported

A blocker skipped would let a file be left out with nobody knowing. Reporting every one, not the first found, spares the
user a run for each problem: a dump with three is fixed in one pass.
:::

:::{rat} A format the lists missed is noticed
:id: RAT-unlisted_media_noticed
:status: ruled
:justifies: RUL-stray_media_hinted

The media lists are the user's configuration, and a camera may write a format they never listed. Its photos would be set
aside as strays, recoverably but without a word. Asking the files' content what they are catches that, and leaves the
choice — to list the extension and plan again — with the user; the warning blocks nothing and changes no list.
:::

