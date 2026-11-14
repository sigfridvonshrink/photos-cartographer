# Merge — how this build does it

How this build meets [merge's intent](../intent/merge.md) and the shared contract's merge rules: the files, names,
tools and steps. Each item `realises` the intent it implements. *Why* a choice was made is in
[the rationale](../rationale/merge.md).
Sections are numbered as in the phase's original spec; a section whose content lives in the shared contract, or
that only restated others, has no heading here.

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

## 4. Configuration and validation

:::{bld} `init-library`'s four cases
:id: BLD-init_library_cases
:status: ruled
:realises: RUL-library_mark_made_by_setup, RUL-library_setup_writes_one_setting, RUL-library_place_checked, RUL-config_validated_before_use

`merge init-library [path]` SHALL resolve a given path to an absolute one and require an existing directory, then:
inside a workspace with a path, refuse a path `library_place_error` names and, under the lock, check the workspace's
filesystem and the seal, read the configuration through `load_config`, mark the directory and record it as
`merge.library_root`; inside a workspace without one, under the lock, read the configuration the same way and mark the
`library_root` it names, writing nothing in the workspace; outside any workspace with a path, mark the directory and
write nothing else; outside any workspace without one, stop with exit status 2. A configuration that cannot be read or
fails its checks stops it with exit status 2, nothing marked and nothing written.
:::

## 6. Destination-to-library mapping

:::{bld} A photo's target in the library
:id: BLD-merge_target
:status: ruled
:realises: RUL-library_mirrors_destinations, RUL-geotag_name_final

Merge's `enumerate_finalized` SHALL take each photo of the handoff under `6-photos-by-dest` and give it, as its target,
`library_root` joined to its folder's path relative to `6-photos-by-dest` — empty for a photo directly in it — and its
final name: the target of `photos-24`'s `rename_no_clobber` whose `content_fingerprint` precondition is the photo's, or
its own name where geotag renamed nothing; the entries sorted by their path in the workspace.
:::

## 8. Idempotency, resume, and non-destructiveness

:::{bld} A fresh plan carries forward from the earlier plans
:id: BLD-merge_carry_forward
:status: ruled
:realises: RUL-replan_carries_placed

Merge's `build_merge_plan` SHALL give a finalized photo no longer under `6-photos-by-dest` the record of the latest
plan — `photos-30-merge-plan.json`, then its `-NNN` backups newest first — holding a record for its content fingerprint
not blocked whose `library_target` fingerprints, through `_fingerprint_library_file`, to it, adding `carried_from_plan`
(the plan that first placed it); no such record makes it a blocked record whose reason names the places tried, or that
no earlier plan placed it.
:::

## 10. Plan / dry-run / execute lifecycle

:::{bld} Merge's plan
:id: BLD-merge_plan
:status: ruled
:realises: RUL-execution_only_the_plan, RUL-plan_carried_out_by_its_code
:uses: BLD-merge_target

`photos-30-merge-plan.json` SHALL hold the plan id, schema version and `library_root`; per destination, each photo's
record — its path in the workspace, content fingerprint, library target and disposition (`placed_new`,
`renamed_incoming` with its new name, `already_present`, or `blocked` with why), and as preconditions its fingerprint
and its size and modification time as they stand at planning; the blockers and the totals; and `depends_on`: the
SHA-256 of `photos-24` and `photos-25`, the handoff's content fingerprint, the configuration's SHA-256, the code
fingerprint, the ImageMagick version, and the fingerprints of the folder names and media extensions.
:::

:::{bld} Merge's execute, in order
:id: BLD-merge_execute
:status: ruled
:realises: RUL-execution_jobs_change_nothing, RUL-execution_only_the_plan
:uses: BLD-merge_plan, BLD-merge_move, BLD-merge_journal_resume

Merge's execute SHALL, on its main thread, revalidate the plan's `depends_on`, take the snapshots and sweep the
temporaries a crash left; then move the photos on a pool of `jobs` workers, each touching only its own photo and
returning a result; the main thread alone writing the journal, as each result arrives, and sorting the results by path
before the summary is built.
:::
