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


## 7. The prep pipeline

:::{rat} A dump's folders say where it came from
:id: RAT-dump_folders_kept
:status: ruled
:justifies: RUL-inbox_kept_as_dumped

A dump's folders are the only trace of where each file came from — a card, a phone, a friend's share — and two files of
one name from different sources sit apart only by them. Lifting the files up into one folder would throw that away and
make the names collide; each file instead leaves the inbox once, straight for where it is filed, under a name made free
in the plan.
:::

:::{rat} What is filed is settled
:id: RAT-filed_is_settled
:status: ruled
:justifies: RUL-filed_file_stays

A file outside the inbox was filed by an earlier run or moved there by the user. Moving it again on a later run would
undo either for nothing and churn the names the user and later phases know it by. Only two things move it: a copy of it
found to be better filed, and its own recorded time no longer matching its day.
:::

:::{rat} A day of photos is one folder
:id: RAT-day_folder
:status: ruled
:justifies: RUL-by_date_in_day_folder

The user sorts photos by date into destinations, and a day is the unit they think in: a day's folder holds what was
shot that day and nothing else. A file's day comes from its recorded time, so a file whose time changed — corrected by
the user — belongs to another day, and one whose time is gone belongs to no day at all.
:::

:::{rat} Photos wait by date for the user's sort
:id: RAT-photos_wait_by_date
:status: ruled
:justifies: RUL-photos_by_date

The user sorts photos into destinations from photos by date; ordered by their recorded time, the photos of one trip and
one day sit together, ready to be moved as a block. The timestamp name keeps that order however a folder is listed.
:::

:::{rat} A file with no time cannot be dated
:id: RAT-untimed_set_apart
:status: ruled
:justifies: RUL-untimed_to_missing_metadata

Prep cannot invent a time, and a file with none has no day to be filed under: it waits apart, flat, until the user
gives it one. Its untimed name keeps the name it came with, the user's only way to tell which file it was.
:::

:::{rat} A stray is the user's, untouched
:id: RAT-stray_as_it_came
:status: ruled
:justifies: RUL-inbox_non_media_to_strays

A file of no media class is not the pipeline's to process ({need}`RAT-strays_not_the_pipelines`); it leaves the inbox
so that the inbox ends empty, and goes where the user can find it as it was — at the place it had in the dump, under the
name it came with, in the run's own folder so no two runs' strays meet.
:::

:::{rat} The user's fix goes through the inbox
:id: RAT-fix_through_inbox
:status: ruled
:justifies: RUL-missing_metadata_stays

The user gives a file in missing metadata its time with their own tools, whenever they choose. Moving it back into the
inbox says that they are done; it then goes through prep like any file of a new dump, and no second way into the
pipeline needs keeping in step with the first.
:::

:::{rat} One spelling of each extension
:id: RAT-one_extension_spelling
:status: ruled
:justifies: RUL-media_extension_lowercase

Cameras write `.JPG` and `.ARW`; tools and the library match names exactly on many filesystems. One spelling across the
workspace means a name is the same name in every folder and every phase, and two files differing only in an
extension's case are seen as the one name they are.
:::

:::{rat} A duplicate's record names where it was
:id: RAT-duplicate_found_as_it_was
:status: ruled
:justifies: RUL-duplicate_set_aside_as_found

Quarantine keeps a duplicate to be recovered. Its record must give the path and the name it had when found, or a
restore puts back a file the user never had; and moving or renaming it before setting it aside would be work for
nothing, with a crash between leaving it where no run expects it. Setting duplicates aside before any other stage also
lets the copy kept be chosen from where the copies really are.
:::

:::{rat} The RAW is the master
:id: RAT-raw_is_master
:status: ruled
:justifies: RUL-redundant_jpeg_set_aside

A camera shooting RAW and JPEG together writes one name with two extensions in one folder. The RAW holds everything the
JPEG does and more, so the JPEG is redundant — kept, not deleted, but set apart from what the user sorts. Only that
evidence is trusted: a name shared within a folder, as the camera wrote it. Another image under the same name is not
the camera's JPEG, and a JPEG and a RAW in different folders, or matched only by time, may be two shots.
:::

:::{rat} Identical media is kept once
:id: RAT-identical_kept_once
:status: ruled
:justifies: RUL-duplicates_quarantined

Dumps overlap: the same card copied twice, a phone's backup next to its export. Two copies of one photo would be sorted,
geotagged and merged twice. The fingerprint is over the decoded content, so copies are found whatever their name or
metadata; the media class keeps a RAW and the JPEG from it apart, though they show one picture. The copies beyond the
first go to quarantine, recoverable, and photos by destination is never touched.
:::

:::{rat} The copy kept is the one further along
:id: RAT-keep_further_along
:status: ruled
:justifies: RUL-copy_kept_by_folder

A copy in photos by destination carries the user's sort, and one already filed has been named and placed; keeping the
copy furthest along saves redoing that and never moves what the user arranged. The folders are taken as they are before
the plan moves anything, so a new dump never displaces a file already filed, and the order by path makes the choice the
same on every run.
:::

:::{rat} The database is what the next run trusts
:id: RAT-database_trusted_next
:status: ruled
:justifies: RUL-database_matches_files

The next run reuses the database's fingerprints and metadata for every file whose size and time are unchanged. A row
left stale or pointing at a file that is gone would be reused for what it no longer describes; refreshing and pruning at
each execution keeps reuse safe.
:::
