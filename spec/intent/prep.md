# Prep — what it guarantees

What the first phase, {need}`DEF-prep`, guarantees, beyond what [the shared contract](shared.md) binds every phase
to. *Why* each holds is in [the rationale](../rationale/prep.md); *how this build meets it*, in
[the build](../build/prep.md).

## 2. What prep does, and what it leaves alone

:::{rul} Prep corrects no time and no position
:id: RUL-prep_no_time_or_gps
:status: seed
:criticality: high
:anti: yes
:verify: required
:aliases: prep-no-time-gps-correction-1
:uses: DEF-prep

Prep SHALL make no correction to a file's time or position: it plans, infers, writes and applies none.
:::

:::{rul} Prep leaves photos by destination as it finds it
:id: RUL-prep_leaves_by_dest_as_found
:status: seed
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
:status: seed
:criticality: med
:verify: required
:aliases: prep-videos-date-organized-1
:uses: DEF-prep, DEF-managed_folders, DEF-timestamp_name

Prep SHALL put each video it takes in that has a recorded time into videos by date, under its timestamp name.
:::
