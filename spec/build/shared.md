# Shared — how this build does it

How this build meets [the shared intent](../intent/shared.md): the files, names, tools and steps. Each item `realises`
the intent it implements. *Why* a choice was made is in [the rationale](../rationale/shared.md).

## 1. One run at a time

:::{bld} The lock follows the workspace guard
:id: BLD-lock_after_guard
:status: seed
:realises: RUL-lock_before_reading

The lock SHALL be taken at process start, immediately after the workspace root is resolved and its sentinel,
`photos-00-workspace-guard`, is verified.
:::

:::{bld} The lock records its owner
:id: BLD-lock_owner_record
:status: seed
:realises: RUL-stale_lock_recovered

The lock SHALL record the identity of the process that owns it and the time it started, so that a lock whose owner is
gone can be told from one whose owner is running.
:::

:::{bld} The phases run inside the run's lock
:id: BLD-phases_inside_lock
:status: seed
:realises: RUL-lock_through_the_run

Each phase's `plan`, `dry-run` and `execute` SHALL run with the lock taken at start already held; none SHALL take it
again or scope it on its own (prep §14, geotag §29).
:::

## 2. A snapshot before changing, optionally

:::{bld} The snapshot is a ZFS snapshot, configured by the `zfs` block
:id: BLD-snapshot_is_zfs
:status: seed
:realises: RUL-snapshot_optional, RUL-snapshot_off_by_default, RUL-required_snapshot_or_nothing, RUL-snapshot_per_plan

The snapshot SHALL be a ZFS snapshot, configured by the `zfs` block of the workspace configuration,
`photos-00-config.json`; with no `zfs` block, or one not enabled, none is taken. Its name SHALL carry the plan id.
`snapshots_required` decides what a failed snapshot means: true, the run aborts before its first change; false, or the
block not configured, it proceeds without one.
:::

:::{bld} One snapshot mechanism for every phase
:id: BLD-one_snapshot_mechanism
:status: seed
:realises: RUL-snapshot_optional

The three phases SHALL take their snapshots through one mechanism — prep §14.3, geotag §29 and merge §10.3 invoke it,
and none redefines it.
:::
