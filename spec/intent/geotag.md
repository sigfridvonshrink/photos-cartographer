# Geotag — what it guarantees

What the second phase, {need}`DEF-geotag`, guarantees, beyond what [the shared contract](shared.md) binds every phase
to. *Why* each holds is in [the rationale](../rationale/geotag.md); *how this build meets it*, in
[the build](../build/geotag.md).

## 2. Core workflow rule

:::{rul} Time first, then position
:id: RUL-time_before_gps
:status: ruled
:criticality: high
:anti: yes
:verify: required
:uses: DEF-geotag
:aliases: geotag-gps-after-utc-1, geotag-order-time-gps-rename-1

Geotag SHALL plan no photo's position until every photo's true time is resolved.
:::

:::{rul} A photo with no recorded time stops geotag
:id: RUL-untimed_photo_stops_geotag
:status: ruled
:criticality: high
:anti: yes
:verify: required
:refines: RUL-time_before_gps
:uses: DEF-geotag, DEF-managed_folders, DEF-recorded_time

A photo in photos by destination carrying no recorded time SHALL stop geotag before it plans anything, named as
belonging in missing metadata.
:::

## 5. Linear dependency inclusion

:::{rul} The executable plan carries every dependency itself
:id: RUL-geotag_plan_carries_every_dependency
:status: seed
:criticality: high
:anti: yes
:verify: required
:refines: INV-no_stale_use
:uses: DEF-geotag
:aliases: geotag-flattened-deps-1

Geotag's executable plan SHALL carry every dependency it was made from itself — each decision record, the handoff, the
tracks, the configuration, the code and each photo's precondition — never relying on a decision record's own
dependencies to vouch for what came before it.
:::
