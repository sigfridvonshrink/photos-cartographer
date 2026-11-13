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
:status: ruled
:criticality: high
:verify: required
:uses: DEF-geotag, DEF-decision
:aliases: geotag-autoresolve-config-gated-1

A clock offset proposed from a camera's own GPS positions SHALL take effect without the user's answer only as the
configuration's settings for one anchor and for several allow, and never while its anchors disagree.
:::

:::{rul} A destination's timezone applies itself
:id: RUL-timezone_auto_resolves
:status: ruled
:criticality: med
:verify: required
:uses: DEF-geotag, DEF-decision
:aliases: geotag-timezone-autoresolve-1, geotag-no-proposal-requires-input-1, geotag-timezone-unresolved-requires-input-1

A destination's proposed timezone — inherited from the destination it lies in, or the configured default — SHALL take
effect without the user's answer, a timezone the user writes overriding it; a destination with no proposal waits for the
user.
:::

:::{rul} Every other proposal waits for the user's acceptance
:id: RUL-other_proposals_need_acceptance
:status: ruled
:criticality: high
:anti: yes
:verify: required
:uses: DEF-geotag, DEF-decision
:aliases: geotag-no-autonomous-mutation-1

Every other proposal — a clock offset derived from the destination's timezone, a folder fallback position inherited
from the destination it lies in — SHALL take effect only once the user accepts it.
:::

## 10. Per-destination structure

:::{def} A destination
:id: DEF-destination
:status: ruled
:uses: DEF-managed_folders
:aliases: geotag-destination-definition-1

A **destination** is the folder in photos by destination that directly holds a photo; a folder nested in it that holds
photos is a destination of its own.
:::

:::{def} A container destination
:id: DEF-container_destination
:status: ruled
:uses: DEF-destination
:aliases: geotag-container-destination-1

A **container destination** is a folder in photos by destination that holds destinations but no photo of its own —
photos by destination itself among them, when it holds no photo directly.
:::

:::{rul} One clock offset per camera, destination and day
:id: RUL-offset_per_camera_destination_day
:status: ruled
:criticality: high
:verify: required
:uses: DEF-geotag, DEF-destination, DEF-camera_group
:aliases: geotag-offset-per-date-bucket-1, geotag-offset-per-group-dest-1, geotag-container-no-offset-1

Geotag SHALL decide a camera's clock offset once for each destination and each day it took photos there, by the
camera's own clock — a container destination, holding no photo, having none.
:::

:::{rul} An offset is proposed from its own evidence only
:id: RUL-offset_from_own_evidence
:status: ruled
:criticality: high
:anti: yes
:verify: required
:refines: RUL-offset_per_camera_destination_day
:aliases: geotag-offset-anchored-locally-1, geotag-offset-no-inherit-1, geotag-offset-no-rollup-1, geotag-bucket-no-inherit-1, geotag-bucket-proposal-priority-1

Each offset SHALL be proposed only from that camera's own positions in that destination on that day, or from the
destination's timezone — never from the offset of another destination, whether one it lies in, one in it, or one beside
it.
:::

:::{rul} A container destination never waits for the user
:id: RUL-container_never_waits
:status: ruled
:criticality: med
:verify: required
:uses: DEF-container_destination
:aliases: geotag-container-no-block-1

A container destination's decisions SHALL never wait for the user.
:::


## 15. Reading the tracks

:::{rul} A track point's time is the instant it states
:id: RUL-track_time_never_guessed
:status: ruled
:criticality: high
:anti: yes
:verify: required
:uses: DEF-tracks

Geotag SHALL take a track point's time as the instant it states — whatever its precision or the offset it is written
with — never guessing the zone of one that states none.
:::

:::{rul} A track point geotag cannot use is reported
:id: RUL-unreadable_point_reported
:status: ruled
:criticality: med
:verify: required
:uses: DEF-tracks

A track point geotag cannot use — no position or one out of range, no time, an unreadable time, or one stating no
zone — SHALL be skipped and reported to the user, naming its file and point.
:::


## 16. Camera groups

:::{rul} An unknown camera group stops geotag
:id: RUL-unknown_group_stops_geotag
:status: ruled
:criticality: high
:anti: yes
:verify: required
:aliases: geotag-incomplete-classification-block-1
:uses: RUL-known_when_classified

Geotag SHALL NOT decide anything while a camera group in photos by destination is unknown.
:::

:::{rul} The classification is offered ready to paste
:id: RUL-unknown_group_classification_offered
:status: ruled
:criticality: low
:verify: required
:aliases: geotag-unknown-group-snippets-1
:refines: RUL-unknown_group_stops_geotag

Geotag SHALL offer the classification of every unknown camera group ready to paste into the configuration, every
group already classed kept as it is.
:::


## 18. Destination civil timezone

:::{rul} A destination takes the nearest timezone it lies in
:id: RUL-timezone_from_nearest
:status: ruled
:criticality: med
:verify: required
:aliases: geotag-timezone-inherit-parentfirst-1, geotag-timezone-inherit-priority-1, geotag-timezone-manual-reroot-1
:refines: RUL-timezone_auto_resolves

A destination's proposed timezone SHALL be the one in effect at the nearest destination it lies in that has one —
however it was reached there — and the configured default only where none has.
:::

:::{rul} A moved photo is decided where it now is
:id: RUL-moved_photo_decided_anew
:status: ruled
:criticality: high
:anti: yes
:verify: required
:aliases: move-reevaluate-dest-1
:uses: DEF-destination

A photo moved to another destination SHALL be decided under that destination's timezone and clock offset, nothing of
its old destination carried with it.
:::


## 19. Clock offsets from the camera's own GPS

:::{rul} A track anchors a clock only within the plausible error
:id: RUL-anchor_within_clock_error
:status: ruled
:criticality: high
:anti: yes
:verify: required
:aliases: geotag-clock-error-window-1, geotag-window-tz-independent-1
:uses: DEF-tracks

A track SHALL anchor a camera's clock only at times within the largest clock error the configuration allows of the
camera's own time, whatever timezone the camera was set to.
:::

:::{rul} The offset is the one most photos agree on
:id: RUL-anchor_consensus
:status: ruled
:criticality: high
:anti: yes
:verify: required
:aliases: geotag-consensus-cluster-1
:refines: RUL-offset_from_own_evidence

The offset proposed from a camera's GPS SHALL be the one the most of its photos agree on — each photo counting every
time the tracks passed where it was taken — never an average, and never one photo's closest match outvoting the rest.
:::

:::{rul} A place visited on several days is matched to the photo's day
:id: RUL-revisit_matched_to_its_day
:status: ruled
:criticality: high
:anti: yes
:verify: required
:refines: RUL-anchor_consensus

Photos of a place the tracks passed on several visits — the same destination on consecutive days, a place passed
morning and evening — SHALL anchor their camera's clock by the visit the camera's photos agree on, never by another
visit's track because it passed closer.
:::

:::{rul} Visits the photos cannot tell apart wait for the user
:id: RUL-indistinct_visits_wait
:status: ruled
:criticality: high
:anti: yes
:verify: required
:refines: RUL-revisit_matched_to_its_day

Where a camera's photos support two visits equally, its clock offset SHALL NOT take effect without the user's answer.
:::

:::{rul} An offset the camera's GPS supports is anchored, however chosen
:id: RUL-chosen_group_is_anchored
:status: ruled
:criticality: med
:verify: required
:refines: RUL-indistinct_visits_wait

A clock offset the user sets that the camera's own GPS positions support SHALL count as anchored by them, as an
accepted proposal does — never asked to be checked against the tracks again.
:::


## 22. Resolved UTC

:::{rul} A phone's time is read by the offset recorded with it
:id: RUL-phone_time_from_own_offset
:status: ruled
:criticality: high
:anti: yes
:verify: required
:uses: DEF-camera_group

A phone's photo SHALL take its true time from the offset recorded with the time it was read from, else from its
destination's timezone.
:::
