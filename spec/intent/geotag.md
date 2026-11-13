# Geotag — what it guarantees

What the second phase, {need}`DEF-geotag`, guarantees, beyond what [the shared contract](shared.md) binds every phase
to. *Why* each holds is in [the rationale](../rationale/geotag.md); *how this build meets it*, in
[the build](../build/geotag.md).
Sections are numbered as in the phase's original spec; a section whose content lives in the shared contract, or
that only restated others, has no heading here.

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
:status: ruled
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

## 7. Geotag scope

:::{rul} Geotag changes only the photos sorted into destinations
:id: RUL-geotag_changes_only_by_dest
:status: ruled
:criticality: high
:anti: yes
:verify: required
:uses: DEF-geotag, DEF-managed_folders
:aliases: geotag-scope-bydest-only-1, geotag-never-touch-video-1

Geotag SHALL change only the photos in photos by destination — never a video, and never a file in any other folder.
:::

## 8. JSON artifact rule

:::{rul} A decision stage reached writes its record
:id: RUL-decision_stage_writes_record
:status: ruled
:criticality: med
:verify: required
:uses: DEF-geotag, DEF-decision
:aliases: geotag-always-produce-decision-artifact-1

Each decision stage geotag reaches SHALL write its record, even when nothing in it needs the user.
:::

:::{rul} No record before the first decision stage
:id: RUL-no_record_before_decisions
:status: ruled
:criticality: med
:anti: yes
:verify: required
:uses: DEF-geotag
:aliases: geotag-no-json-before-decision-stage-1, geotag-first-artifact-21-1

A geotag plan stopped before its first decision stage SHALL write no record of its own, saying what stopped it only in
its output.
:::

## 9. Human decision field rule

:::{rul} A camera's offset from its own GPS applies itself only as configured
:id: RUL-anchor_offset_auto_as_configured
:status: seed
:criticality: high
:verify: required
:uses: DEF-geotag, DEF-decision
:aliases: geotag-autoresolve-config-gated-1

A clock offset proposed from a camera's own GPS positions SHALL take effect without the user's answer only as the
configuration's settings for one anchor and for several allow, and never while its anchors disagree.
:::

:::{rul} A destination's timezone applies itself
:id: RUL-timezone_auto_resolves
:status: seed
:criticality: med
:verify: required
:uses: DEF-geotag, DEF-decision
:aliases: geotag-timezone-autoresolve-1, geotag-no-proposal-requires-input-1

A destination's proposed timezone — inherited from the destination it lies in, or the configured default — SHALL take
effect without the user's answer, a timezone the user writes overriding it; a destination with no proposal waits for the
user.
:::

:::{rul} Every other proposal waits for the user's acceptance
:id: RUL-other_proposals_need_acceptance
:status: seed
:criticality: high
:anti: yes
:verify: required
:uses: DEF-geotag, DEF-decision
:aliases: geotag-no-autonomous-mutation-1

Every other proposal — a clock offset derived from the destination's timezone, a folder fallback position inherited
from the destination it lies in — SHALL take effect only once the user accepts it.
:::
