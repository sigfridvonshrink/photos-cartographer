# Merge — why

**Not normative.** Each item here is the reasoning behind the [intent](../intent/merge.md) or [build](../build/merge.md)
items it `justifies`, under the same section numbers. Where the two differ, the intent wins and this is stale.

## 2. Scope and boundary

:::{rat} One version on both sides of a comparison
:id: RAT-one_version_per_comparison
:status: seed
:justifies: RUL-merge_rechecks_under_new_engine

Merge compares prep's fingerprint of a photo with one it takes now of the library file in its way. Taken by two
versions of ImageMagick, two fingerprints of the same pixels may differ: the photo would be called new and placed again,
renamed, beside itself — a duplicate in the library, which merge must never make. Taken again under the version now in
use, prep's fingerprint is confirmed and the comparison holds. A photo whose fingerprint did change waits in photos by
destination: what geotag recorded of it is keyed by the old value, and merging it would carry a record that names no
photo into the library's history.
:::
