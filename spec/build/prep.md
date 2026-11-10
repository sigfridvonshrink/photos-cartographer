# Prep — how this build does it

How this build meets [prep's intent](../intent/prep.md): the files, names, tools and steps. Each item `realises` the
intent it implements. *Why* a choice was made is in [the rationale](../rationale/prep.md).

## 2. What prep does, and what it leaves alone

:::{bld} Prep's operations hold no metadata write
:id: BLD-prep_operation_kinds
:status: ruled
:realises: RUL-prep_no_time_or_gps

Prep's execute SHALL carry out only folder creations, moves, renames, quarantine moves and database writes, refusing a
plan that holds any other operation — a metadata write among them.
:::

:::{bld} No operation touches `6-photos-by-dest`
:id: BLD-by_dest_ops_refused
:status: ruled
:realises: RUL-prep_leaves_by_dest_as_found

Prep's plan SHALL hold no operation whose source or destination lies in `6-photos-by-dest`, its execute refusing a plan
that holds one; prep reads the files there for their fingerprint and metadata only (prep §10, §11).
:::

## 3. The workspace's first run, and the strays

:::{bld} The mark is `photos-00-workspace-guard`, written last
:id: BLD-workspace_guard
:status: seed
:realises: RUL-initialized_marked_last

The mark SHALL be the file `photos-00-workspace-guard` in `.photos-ingest/`, which the initializing run's execute writes
after every other operation has succeeded; the managed folders it creates are `0-sources` … `6-photos-by-dest`.
:::

:::{bld} A run's strays go to `1-strays/<plan-id>/`
:id: BLD-strays_per_run
:status: seed
:realises: DEF-strays_folder
:aliases: prep-strays-per-run-subfolder-1, prep-strays-no-collision-across-runs-1

Prep SHALL move a run's strays into `1-strays/<plan-id>/`, each at its path under `0-sources/`, so that no two runs
share a folder there.
:::

:::{bld} The configuration is seeded before it is fingerprinted
:id: BLD-seed_before_fingerprints
:status: seed
:realises: RUL-config_seeded_once
:aliases: prep-seed-before-fingerprint-1

Prep SHALL seed the configuration at the start of its run, before any fingerprint of it is taken, so that every
fingerprint, the handoff's recorded hash among them, is of the file as it stands in the workspace.
:::
