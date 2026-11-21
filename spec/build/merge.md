# Merge — how this build does it

How this build meets [merge's intent](../intent/merge.md) and the shared contract's merge rules: the files, names,
tools and steps. Each item `realises` the intent it implements. *Why* a choice was made is in
[the rationale](../rationale/merge.md).

## Scope and boundary

:::{bld} Merge checks prep's fingerprints against the handoff's ImageMagick
:id: BLD-merge_engine_recheck
:status: ruled
:realises: RUL-merge_rechecks_under_new_engine, RUL-engine_change_is_checked

Merge's plan SHALL compare the ImageMagick version now in use with the handoff's `depends_on.cache.image_engine_version`
— a handoff recording none counting as another — and, where they differ and the current one is known, fingerprint each
by-dest photo it plans to place, one whose value is not the handoff's mapped or blocked ({need}`BLD-changed_fingerprint_mapped`);
the plan records the version in its `depends_on.image_engine_version`, and a plan made under another is stale, at dry
run and execute alike.
:::

:::{bld} A changed fingerprint is mapped in the plan where it is one to one
:id: BLD-changed_fingerprint_mapped
:status: ruled
:realises: RUL-merge_merges_changed_fingerprint, RUL-merge_changed_fingerprint_unmerged, RUL-retaken_fingerprint_same_photo
:uses: BLD-merge_engine_recheck, BLD-finalized_media, BLD-library_file_fingerprinted

Merge's plan SHALL give a by-dest photo whose value taken again differs from the handoff's an `engine_mapping` — `was`
and `now`, each its `content_fingerprint` and `image_engine_version` — its `content_fingerprint` still the handoff's,
only where its path, size and modification time are those `photos-26-finalized-media.json` recorded, no other by-dest
photo holds its new value now, no file of the handoff held it, and no other by-dest photo's new value is its old; and
otherwise block it, naming why, together with a photo whose unchanged value its new value equals. A photo so mapped is
compared with the library's files — fingerprinted under the same version — by its new value: in the plan, at execute,
and when a later plan carries it forward and its place holds other bytes than those recorded as placed there
({need}`BLD-placed_bytes_journalled`).
:::

:::{bld} Merge's package maps each changed fingerprint, old value to new
:id: BLD-fingerprint_map
:status: ruled
:realises: RUL-changed_fingerprint_mapping_recorded, RUL-phase_writes_own_records
:uses: BLD-changed_fingerprint_mapped, BLD-merge_success_sequence

A whole merge SHALL write `photos-35-fingerprint-map.json` — `artifact_type` `fingerprint_map`, its `artifact_name`,
`schema_version` 1, and under `photos`, keyed by its new value, each photo merged with an `engine_mapping`: that
mapping's `was` and `now`, its by-dest path as `from` and its `library_path` — empty where none was; geotag's records,
the log copied forward, are left keyed by the old value, and none is rewritten.
:::

## Preconditions

:::{bld} Merge's preflight
:id: BLD-merge_preflight
:status: ruled
:realises: RUL-merge_rechecks_gates, RUL-merge_blocked_changes_nothing, RUL-merge_takes_finalized_current, RUL-merge_refuses_changed_since_finalize, RUL-unfingerprinted_photo_stops_merge, RUL-hidden_among_photos_stops_merge, RUL-image_engine_absent_stops_merge, RUL-merge_refuses_unplaced, RUL-merge_gates_leave_out_residue, RUL-fingerprint_method_is_the_builds

Merge's `preflight` SHALL run, under the workspace lock and before the library's, stopping at the first that fails: the
seal; the initialization mark; a link at the top level; the configuration, read and checked; a missing managed folder; a
misplaced top-level entry; a link in photos by destination; the library's place and mark; the handoff, read as a JSON
object; its filename format. It then gathers
the rest and reports them together: ImageMagick on the `PATH`, as `magick` or `identify`; the inbox empty;
`photos-24-executable-plan.json` present with `photos-25-execution-summary.json` at `success`, it and the archive
manifest of `photos-24`'s `plan_id`; the handoff's content
fingerprint the one `photos-26-finalized-media.json` holds ({need}`BLD-finalized_media`) — not the one `photos-24`
pinned, which a prep run between execute and finalize leaves behind; prep's log as the handoff vouches for it ({need}`BLD-prep_log_checked`);
`photos-26-complete-log.json` and the archive manifest present, the complete log carrying prep's; photos by date holding
no photo; photos by destination holding only `image` and `raw` files and no development subfolder; every photo
there one of the finalized set — the handoff's photos by destination joined by fingerprint to `photos-24`'s renames,
each under its final name; and each photo of that set still there with the size and modification time
`photos-26-finalized-media.json` recorded, and holding a position ({need}`BLD-no_photo_unplaced`). Any blocker ends the
run with exit status 2 before the library lock, the plan or the summary. It stops, too, on a handoff whose fingerprints
are not of this build's method (`depends_on.cache.fingerprint_algorithm_version`, {need}`BLD-fingerprint_method`), on a
photo in `6-photos-by-dest` whose handoff record holds no fingerprint and on any hidden file or folder there, each
named.
:::

:::{bld} The library's filesystem, tried before its lock
:id: BLD-library_trial
:status: ruled
:realises: RUL-library_requirements_tried, RUL-library_lacking_stops, RUL-library_lacking_named, RUL-library_network_allowed
:uses: BLD-filesystem_trial

Merge's plan, dry run and execute SHALL, after the preflight and the workspace's check and before `LibraryLock`, call
`library_filesystem_error`, which tries through `filesystem_lacks`, in `library_root`, the lock, the move that refuses a
taken name and the two syncs, and checks no filesystem type; one failing stops the run with exit status 2, naming it.
:::

:::{bld} The library's free space against the photos still to move
:id: BLD-library_space
:status: ruled
:realises: RUL-library_space_checked, RUL-library_space_short_stops, RUL-library_space_short_named, RUL-library_space_warned_at_plan, RUL-library_space_margin

`_space_shortfalls` SHALL total the size of each photo of the plan placed new or renamed whose copy is still in photos
by destination and whose place is free, by the filesystem of the nearest existing folder of its place, leaving out the
workspace's own; and compare each total, raised by `merge.library_space_margin_percent` percent of it and rounded up to
a whole byte, with that filesystem's free space as `shutil.disk_usage` gives it, naming the library where it lies there.
Execute calls it after revalidating the plan and reading the journal, before the snapshots, and a shortfall stops it
with exit status 2, the summary written `rejected` with each shortfall among its failures ({need}`BLD-merge_records`);
the plan calls it once written, warning of each.
:::

## Configuration and validation

:::{bld} `init-library`'s four cases
:id: BLD-init_library_cases
:status: ruled
:realises: RUL-library_mark_made_by_setup, RUL-library_setup_writes_one_setting, RUL-library_place_checked, RUL-config_validated_before_use

`merge init-library [path]` SHALL resolve a given path to an absolute one and require an existing directory and refuse
one `library_workspace_error` names ({need}`BLD-library_root_validated`), then: inside a workspace with a path, refuse a
path `library_place_error` names, try the workspace's filesystem ({need}`BLD-local_filesystem_types`) and, under the
lock, check that the workspace lies on one filesystem and the seal, read the configuration through `load_config` and
refuse a top level holding a link, missing a managed folder or holding a misplaced entry, then mark the directory and
record it as `merge.library_root`; inside a workspace without one, try its filesystem and, under the lock, check that it
lies on one filesystem, read the configuration the same way, refuse the same top level, and refuse a `library_root`
that `validate_merge_config` or `library_workspace_error` refuses, else mark it, writing nothing in the workspace;
outside any workspace with a path, mark the directory and write nothing else; outside any workspace without one, stop
with exit status 2. A configuration that cannot be read or fails its checks, or an entry of the mark's name that is not
a file, stops it with exit status 2, nothing marked and nothing written.
:::

## Destination-to-library mapping

:::{bld} A photo's target in the library
:id: BLD-merge_target
:status: ruled
:realises: RUL-library_mirrors_destinations, RUL-geotag_name_final

Merge's `enumerate_finalized` SHALL take each photo of the handoff under `6-photos-by-dest` and give it, as its target,
`library_root` joined to its folder's path relative to `6-photos-by-dest` — empty for a photo directly in it — and its
final name: the target of `photos-24`'s `rename_no_clobber` whose `content_fingerprint` precondition is the photo's, or
its own name where geotag renamed nothing; the entries sorted by their path in the workspace.
:::

## Idempotency, resume, and non-destructiveness

:::{bld} A fresh plan carries forward from the earlier plans
:id: BLD-merge_carry_forward
:status: ruled
:realises: RUL-replan_carries_placed, RUL-earlier_place_in_this_library, RUL-merge_unreadable_record_stops, RUL-replan_blocks_unaccounted, RUL-replan_block_names_why, RUL-earlier_place_moved_to_this_library

Merge's `build_merge_plan` SHALL give a finalized photo no longer under `6-photos-by-dest` the record of the latest
plan — `photos-30-merge-plan.json`, then its `-NNN` backups newest first, by the number of the suffix — holding a record for its content fingerprint
not blocked whose `library_target` holds it ({need}`BLD-placed_bytes_journalled`), adding `carried_from_plan`
(the plan that first placed it); no such record makes it a blocked record whose reason names the places tried, or that
no earlier plan placed it. A record's place counts only inside the configured `library_root`; a photo found at an earlier place outside it blocks, unless it is found at the same place under the configured library, where the user moved it.
One of those plans or their journals that cannot be read, does not parse as a JSON object, lacks its `plan_id` (a plan)
or `operations` (a journal), or is not in the shape of {need}`BLD-merge_record_shape` stops the plan with exit status 2, naming it, no plan written.
:::

:::{bld} The bytes of each placed file are journalled, and confirm its place
:id: BLD-placed_bytes_journalled
:status: ruled
:realises: RUL-placed_bytes_confirm_place, RUL-replan_carries_placed, RUL-resume_rechecks_library
:uses: BLD-merge_journal_resume, BLD-merge_carry_forward

Merge's execute SHALL record in the journal, under `placed_sha256` keyed by the photo's path in the workspace, the
SHA-256 of the library file of each photo it confirms, where that file can be read; a later plan carrying a photo forward gives its record, as
`placed_sha256`, the one the journal of the plan it is carried from holds, else that plan's record's own; and a place
whose file has the record's `placed_sha256` holds the photo, no fingerprint taken — one without it, or whose bytes
differ, holding it only where it fingerprints, through `_fingerprint_library_file`, to the value the photo was placed
under ({need}`BLD-changed_fingerprint_mapped`). Both the plan carrying it forward and the execute finding the photo's
workspace copy gone check the place so.
:::

:::{bld} The shape of merge's plan and journal
:id: BLD-merge_record_shape
:status: ruled
:realises: RUL-merge_unreadable_record_stops

Merge SHALL read as unreadable a plan whose `destinations` is not an object of objects each holding a `files` list of
objects that name their `by_dest_source`, and any `library_target`, as text, or whose `depends_on` or `totals`, where
present, is not an object or `blockers` not a list; and a journal whose `operations`, or `placed_sha256` where present,
is not an object.
:::

## Plan / dry-run / execute lifecycle

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
:realises: RUL-execution_jobs_change_nothing, RUL-execution_only_the_plan, RUL-merge_unreadable_record_stops
:uses: BLD-merge_plan, BLD-merge_move, BLD-merge_journal_resume

Merge's execute SHALL, on its main thread, once the library's filesystem is tried and its lock taken
({need}`BLD-library_trial`), read the plan, revalidate its `depends_on` and read the journal an earlier execute of the
plan left — a plan or journal that cannot be read, does not parse as a JSON object, lacks its `plan_id` or `operations`
or is not in the shape of {need}`BLD-merge_record_shape` stopping it with exit status 2, nothing changed, as such a plan
stops the dry run — then check the library's room ({need}`BLD-library_space`); then take the snapshots and sweep the
temporaries a crash left; then move the photos on a pool of `jobs` workers, each touching only its own photo and
returning a result; the main thread alone writing the journal, as each result arrives, and sorting the results by path
before the summary is built.
:::
