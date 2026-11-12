# Merge — what it guarantees

What the last phase, {need}`DEF-merge`, guarantees, beyond what [the shared contract](shared.md) binds every phase
to — most of merge's rules are there, in its section on the library and the seal. *Why* each holds is in
[the rationale](../rationale/merge.md); *how this build meets it*, in [the build](../build/merge.md).

## 2. Scope and boundary

:::{rul} Merge checks prep's fingerprints under another ImageMagick
:id: RUL-merge_rechecks_under_new_engine
:status: ruled
:criticality: high
:anti: yes
:verify: required
:refines: RUL-engine_change_is_checked
:uses: DEF-fingerprint, DEF-library

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
:aliases: merge-map-preserve-destination-structure-1, merge-mapping-deterministic-1, merge-preserve-geotag-final-name-1

Merge SHALL place each photo at the same path under the library as it holds under photos by destination — its folders
as the user built them, its name the one geotag gave it — the name an incoming photo is given on a collision the only
change.
:::
