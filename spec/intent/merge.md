# Merge — what it guarantees

What the last phase, {need}`DEF-merge`, guarantees, beyond what [the shared contract](shared.md) binds every phase
to — most of merge's rules are there, in its section on the library and the seal. *Why* each holds is in
[the rationale](../rationale/merge.md); *how this build meets it*, in [the build](../build/merge.md).

## 2. Scope and boundary

:::{rul} Merge checks prep's fingerprints under another ImageMagick
:id: RUL-merge_rechecks_under_new_engine
:status: seed
:criticality: high
:anti: yes
:verify: required
:refines: RUL-engine_change_is_checked
:uses: DEF-fingerprint, DEF-library

Under an ImageMagick version other than the one prep's fingerprints were taken by, merge SHALL take each photo's
fingerprint again before comparing it with the library's, a photo whose fingerprint changed left in photos by
destination, unmerged.
:::
