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

## 3. Preconditions

:::{bld} Merge's preflight
:id: BLD-merge_preflight
:status: ruled
:realises: RUL-merge_rechecks_gates, RUL-merge_blocked_changes_nothing, RUL-merge_takes_finalized_current, RUL-merge_refuses_changed_since_finalize

Merge's `preflight` SHALL run, under the workspace lock and before the library's, stopping at the first that fails:
the seal; the initialization mark; a link at the top level; a missing managed folder; a misplaced top-level entry; the
configuration, read and checked; the library's place and mark; the handoff, read; its filename format. It then gathers
the rest and reports them together: the inbox empty; `photos-24-executable-plan.json` present with
`photos-25-execution-summary.json` at `success`; the handoff's content fingerprint the one `photos-24` pinned; prep's
log as the handoff vouches for it ({need}`BLD-prep_log_checked`); `photos-26-complete-log.json` and the archive
manifest present, the complete log carrying prep's; photos by date holding no photo; photos by destination holding
only `image` and `raw` files, no development subfolder and no link; every photo there one of the finalized set — the
handoff's photos by destination joined by fingerprint to `photos-24`'s renames, each under its final name; and each
photo of that set still there with the size and modification time `photos-26-finalized-media.json` recorded. Any
blocker ends the run with exit status 2 before the library lock, the plan or the summary.
:::
