# Merge — what it guarantees

What the last phase, {need}`DEF-merge`, guarantees, beyond what [the shared contract](shared.md) binds every phase
to — most of merge's rules are there, in its section on the library and the seal. *Why* each holds is in
[the rationale](../rationale/merge.md); *how this build meets it*, in [the build](../build/merge.md).
Sections are numbered as in the phase's original spec; a section whose content lives in the shared contract, or
that only restated others, has no heading here.

## 2. Scope and boundary

:::{rul} Merge checks prep's fingerprints under another ImageMagick
:id: RUL-merge_rechecks_under_new_engine
:status: ruled
:criticality: high
:anti: yes
:verify: required
:refines: RUL-engine_change_is_checked
:uses: DEF-fingerprint, DEF-library
:aliases: merge-only-no-reorganize-1

Under an ImageMagick version other than the one prep's fingerprints were taken by, merge SHALL take each photo's
fingerprint again before comparing it with the library's, a photo whose fingerprint changed left in photos by
destination, unmerged.
:::

## 3. Preconditions

:::{rul} Merge checks geotag's gates again
:id: RUL-merge_rechecks_gates
:status: ruled
:criticality: high
:anti: yes
:verify: required
:refines: RUL-geotag_gates
:uses: DEF-merge, DEF-managed_folders
:aliases: merge-require-0-sources-empty-1, merge-require-by-dest-photo-only-1, merge-prep-consistency-1, merge-residual-folders-do-not-block-1

Merge SHALL proceed only while the workspace, checked again at merge's own start, satisfies geotag's gates — what the
gates leave out, the videos, the files missing metadata, the redundant JPEGs and the strays, blocking merge no more
than geotag.
:::

:::{rul} A merge a precondition stops changes nothing
:id: RUL-merge_blocked_changes_nothing
:status: ruled
:criticality: high
:anti: yes
:verify: required
:uses: DEF-merge, DEF-library
:aliases: merge-precond-fail-no-output-1

A merge a precondition stops SHALL change nothing in the library, the workspace's photos or merge's records.
:::

## 6. Destination-to-library mapping

:::{rul} The library mirrors the destination tree
:id: RUL-library_mirrors_destinations
:status: ruled
:criticality: high
:anti: yes
:verify: required
:uses: DEF-library, DEF-managed_folders
:aliases: merge-map-preserve-destination-structure-1, merge-mapping-deterministic-1, merge-preserve-geotag-final-name-1, merge-no-mutate-by-dest-content-or-name-1

Merge SHALL place each photo at the same path under the library as it holds under photos by destination — its folders
as the user built them, its name the one geotag gave it — the name an incoming photo is given on a collision the only
change.
:::

## 8. Idempotency, resume, and non-destructiveness

:::{rul} A fresh plan is allowed at any time before the seal
:id: RUL-merge_replan_any_time
:status: ruled
:criticality: med
:verify: required
:refines: RUL-merge_resumable
:uses: DEF-merge, DEF-sealed_workspace
:aliases: merge-replan-allowed-after-failed-or-rejected-1

Merge SHALL allow a fresh plan at any time on a workspace not sealed, whatever an earlier run of it left.
:::

:::{rul} A fresh plan carries the photos earlier plans placed
:id: RUL-replan_carries_placed
:status: ruled
:criticality: high
:anti: yes
:verify: required
:refines: RUL-merge_resumable
:uses: DEF-merge, DEF-library, DEF-fingerprint, DEF-managed_folders
:aliases: merge-resume-via-execute-not-plan-1, merge-finalized-entry-absent-not-blocker-1

A fresh plan SHALL account for every finalized photo no longer in photos by destination: carried forward with the
library place the latest earlier plan of the workspace gave it whose place, fingerprinted again, holds it — whether or
not the journal recorded the move — and otherwise blocking, naming why.
:::

:::{rul} A resumed merge checks the library, not the journal
:id: RUL-resume_rechecks_library
:status: ruled
:criticality: high
:anti: yes
:verify: required
:refines: RUL-merge_resumable
:uses: DEF-merge, DEF-library, DEF-fingerprint
:aliases: merge-resume-state-derivation-1

A photo gone from photos by destination SHALL count as merged only while its library place, fingerprinted again, holds
it — whatever the journal or the plan says — and otherwise block, the run then partial.
:::

## 9. User-visible outputs and the merge summary

:::{rul} Merge records how its run ended
:id: RUL-merge_outcome_recorded
:status: ruled
:criticality: med
:verify: required
:refines: RUL-merge_records_landing
:uses: DEF-merge
:aliases: merge-summary-final-status-values-1

Merge SHALL record whether its run succeeded whole, in part or not at all, or was refused before changing anything.
:::

:::{rul} Merge tells how its run ended
:id: RUL-merge_run_reported
:status: ruled
:criticality: low
:verify: required
:uses: DEF-merge, DEF-library, DEF-managed_folders, DEF-sealed_workspace
:aliases: merge-textual-output-separation-1

At the end of an execution merge SHALL report what it placed in the library, what was already there, each photo left in
photos by destination with why, and whether the workspace is now sealed.
:::
