# Merge — how this build does it

How this build meets [merge's intent](../intent/merge.md) and the shared contract's merge rules: the files, names,
tools and steps. Each item `realises` the intent it implements. *Why* a choice was made is in
[the rationale](../rationale/merge.md).

## 2. Scope and boundary

:::{bld} Merge checks prep's fingerprints against the handoff's ImageMagick
:id: BLD-merge_engine_recheck
:status: ruled
:realises: RUL-merge_rechecks_under_new_engine, RUL-engine_change_is_checked

Merge's plan SHALL compare the ImageMagick version now in use with the handoff's `depends_on.cache.image_engine_version`
— a handoff recording none counting as another — and, where they differ and the current one is known, fingerprint each
by-dest photo it plans to place, blocking one whose value is not the handoff's; the plan records the version in its
`depends_on.image_engine_version`, and a plan made under another is stale, at dry run and execute alike.
:::
