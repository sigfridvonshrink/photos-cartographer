# Prep — what it guarantees

What the first phase, {need}`DEF-prep`, guarantees, beyond what [the shared contract](shared.md) binds every phase
to. *Why* each holds is in [the rationale](../rationale/prep.md); *how this build meets it*, in
[the build](../build/prep.md).

## 2. What prep does, and what it leaves alone

:::{rul} Prep corrects no time and no position
:id: RUL-prep_no_time_or_gps
:status: ruled
:criticality: high
:anti: yes
:verify: required
:aliases: prep-no-time-gps-correction-1
:uses: DEF-prep

Prep SHALL make no correction to a file's time or position: it plans, infers, writes and applies none.
:::

:::{rul} Prep leaves photos by destination as it finds it
:id: RUL-prep_leaves_by_dest_as_found
:status: ruled
:criticality: high
:anti: yes
:verify: required
:aliases: prep-by-dest-readonly-1, prep-no-perform-bydest-move-1
:uses: DEF-prep, DEF-managed_folders

Prep SHALL leave photos by destination as it finds it: never moving a file into it, out of it or within it, nor
renaming, quarantining, deleting or writing one there.
:::

:::{rul} Prep puts videos by date
:id: RUL-videos_by_date
:status: ruled
:criticality: med
:verify: required
:aliases: prep-videos-date-organized-1
:uses: DEF-prep, DEF-managed_folders, DEF-timestamp_name

Prep SHALL put each video it takes in that has a recorded time into videos by date, under its timestamp name.
:::

## 3. The workspace's first run, and the strays

:::{rul} Initializing, prep moves the dump into the inbox
:id: RUL-init_moves_dump_to_inbox
:status: ruled
:criticality: high
:verify: required
:aliases: prep-init-moves-base-into-sources-1, prep-init-excludes-managed-from-move-1
:uses: RUL-first_dump_at_top_level, DEF-managed_folders, DEF-control_records

Initializing a workspace, prep SHALL move every entry at its top level that is not a managed folder or the control
records' place — files and whole folders alike, their structure kept — into the inbox.
:::

:::{rul} A dump folder named as a managed folder is that folder
:id: RUL-dump_folder_named_as_managed
:status: ruled
:criticality: med
:verify: required
:aliases: prep-reserved-names-not-moved-1
:refines: RUL-init_moves_dump_to_inbox

Initializing, prep SHALL take a folder at the top level named as a managed folder for that managed folder, never moving
it into the inbox.
:::

:::{rul} A workspace is marked initialized last
:id: RUL-initialized_marked_last
:status: ruled
:criticality: high
:verify: required
:aliases: prep-sentinel-written-last-1
:uses: RUL-structure_built_once

Prep SHALL mark a workspace initialized only once its initializing run has succeeded, every managed folder and the
control records' place in it.
:::

:::{rul} An interrupted initialization is taken up again
:id: RUL-init_taken_up_again
:status: ruled
:criticality: med
:verify: required
:aliases: prep-crash-init-reenters-harmlessly-1
:refines: RUL-initialized_marked_last

A run that finds a workspace not marked initialized SHALL initialize it, keeping what an interrupted initialization
already did: the folders it made, and the dump already in the inbox.
:::

:::{rul} A stray leaves no trace but its move
:id: RUL-strays_leave_no_trace
:status: ruled
:criticality: med
:anti: yes
:verify: required
:aliases: prep-strays-inert-1
:uses: DEF-strays_folder

A file prep moves to the strays folder SHALL be recorded nowhere but in the journal of that move: no fingerprint, no row
in the workspace database, no entry in any log, no place in the archival package.
:::
