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

Geotag SHALL change only the photos in photos by destination — never a video, and never a file in any other folder.
:::

## 8. JSON artifact rule

:::{rul} A decision stage reached writes its record
:id: RUL-decision_stage_writes_record
:status: ruled
:criticality: med
:verify: required
:uses: DEF-geotag, DEF-decision

Each decision stage geotag reaches SHALL write its record, even when nothing in it needs the user.
:::

:::{rul} No record before the first decision stage
:id: RUL-no_record_before_decisions
:status: ruled
:criticality: med
:anti: yes
:verify: required
:uses: DEF-geotag

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

A clock offset proposed from a camera's own GPS positions SHALL take effect without the user's answer only as the
configuration's settings for one anchor and for several allow, and never while its anchors disagree.
:::

:::{rul} An inherited timezone applies itself
:id: RUL-timezone_auto_resolves
:status: ruled
:criticality: med
:verify: required
:uses: DEF-geotag, DEF-decision

A timezone a destination inherits from the destination it lies in SHALL take effect without the user's answer, a
timezone the user writes overriding it; a destination with none to inherit waits for the user.
:::

:::{rul} The configured default zone is offered, never applied
:id: RUL-default_zone_proposed_only
:status: ruled
:criticality: high
:anti: yes
:verify: required
:refines: RUL-timezone_auto_resolves

The configured default timezone SHALL be offered to a destination with no zone to inherit, never applied without the
user's answer.
:::

:::{rul} Every other proposal waits for the user's acceptance
:id: RUL-other_proposals_need_acceptance
:status: ruled
:criticality: high
:anti: yes
:verify: required
:uses: DEF-geotag, DEF-decision

Every other proposal — a clock offset derived from the destination's timezone, a folder fallback position inherited
from the destination it lies in — SHALL take effect only once the user accepts it.
:::

:::{rul} An acceptance holds for the proposal it accepted
:id: RUL-acceptance_holds_for_its_proposal
:status: seed
:criticality: high
:anti: yes
:verify: required
:refines: RUL-other_proposals_need_acceptance

An acceptance of a proposed clock offset SHALL hold only while the offset proposed is the one that was accepted; a proposal that has become another is asked about again, the acceptance kept as written.
:::

:::{rul} A written value outranks an accepted proposal
:id: RUL-written_value_over_acceptance
:status: seed
:criticality: med
:verify: required
:refines: RUL-other_proposals_need_acceptance

A value the user writes for a decision SHALL take effect over a proposal accepted for the same decision.
:::


## 10. Per-destination structure

:::{def} A destination
:id: DEF-destination
:status: ruled
:uses: DEF-managed_folders

A **destination** is the folder in photos by destination that directly holds a photo; a folder nested in it that holds
photos is a destination of its own.
:::

:::{def} A container destination
:id: DEF-container_destination
:status: ruled
:uses: DEF-destination

A **container destination** is a folder in photos by destination that holds destinations but no photo of its own —
photos by destination itself among them, when it holds no photo directly.
:::

:::{rul} One clock offset per camera, destination and day
:id: RUL-offset_per_camera_destination_day
:status: ruled
:criticality: high
:verify: required
:uses: DEF-geotag, DEF-destination, DEF-camera_group

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

A container destination's decisions SHALL never wait for the user.
:::

:::{rul} An answer follows its day
:id: RUL-answer_follows_its_day
:status: seed
:criticality: high
:anti: yes
:verify: required
:refines: RUL-decision_kept
:uses: DEF-destination

An answer given for a camera's day in a destination SHALL stay that day's answer when photos of another day arrive there or leave.
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

:::{rul} Tracks that are configured and not there stop geotag
:id: RUL-missing_tracks_stop_geotag
:status: seed
:criticality: high
:anti: yes
:verify: required
:uses: DEF-tracks

Geotag SHALL NOT plan while the tracks folder the configuration names is not there.
:::

:::{rul} Geotag runs without tracks
:id: RUL-no_tracks_no_stop
:status: seed
:criticality: med
:verify: required
:uses: DEF-tracks

Geotag SHALL proceed where no tracks folder is configured or the folder holds no track, each decision resting on its other sources.
:::

:::{rul} A track is one device's record
:id: RUL-tracks_never_joined
:status: seed
:criticality: high
:anti: yes
:verify: required
:uses: DEF-tracks

Geotag SHALL never join a point of one track file to a point of another — to place a photo between them, or to anchor a clock on the line between them.
:::


## 16. Camera groups

:::{rul} An unknown camera group stops geotag
:id: RUL-unknown_group_stops_geotag
:status: ruled
:criticality: high
:anti: yes
:verify: required
:uses: RUL-known_when_classified

Geotag SHALL NOT decide anything while a camera group in photos by destination is unknown.
:::

:::{rul} The classification is offered ready to paste
:id: RUL-unknown_group_classification_offered
:status: ruled
:criticality: low
:verify: required
:refines: RUL-unknown_group_stops_geotag

Geotag SHALL offer the classification of every unknown camera group ready to paste into the configuration, every
group already classed kept as it is.
:::

:::{rul} A file naming no camera is solved on its own
:id: RUL-unidentified_files_solved_alone
:status: ruled
:criticality: med
:anti: yes
:verify: required
:uses: DEF-camera_group

A file whose metadata names no camera SHALL be solved on its own — by the offset recorded with its time, else its
destination's timezone — never asked to be classed, nor given a camera's clock offset.
:::

:::{rul} A group classed both ways is unknown
:id: RUL-group_classed_twice_is_unknown
:status: seed
:criticality: high
:anti: yes
:verify: required
:refines: RUL-unknown_group_stops_geotag

A camera group the configuration classes as both a phone and a camera SHALL count as unknown.
:::


## 18. Destination civil timezone

:::{rul} A destination takes the nearest timezone it lies in
:id: RUL-timezone_from_nearest
:status: ruled
:criticality: med
:verify: required
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

:::{rul} Where the tracks stood still, a place says no time
:id: RUL-stay_fixes_no_clock
:status: seed
:criticality: high
:anti: yes
:verify: required
:refines: RUL-anchor_consensus

An offset the camera's photos fix only to within a stay of the tracks at their place — longer than offsets are told apart by — SHALL NOT take effect without the user's answer, nor count as anchored once accepted.
:::

:::{rul} A proposal from GPS is recorded with its evidence
:id: RUL-anchor_proposal_carries_evidence
:status: seed
:criticality: med
:verify: required
:refines: RUL-anchor_consensus

A clock offset proposed from a camera's own GPS SHALL be recorded with the photos that support it, the photos that do not, and the track each was matched to.
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


## 22a. The GPS-drift check

:::{rul} An offset the camera's GPS does not support is confirmed before photos are placed by it
:id: RUL-unanchored_offset_confirmed
:status: ruled
:criticality: high
:anti: yes
:verify: required
:uses: DEF-tracks

Photos SHALL NOT be placed by the tracks on a clock offset the camera's own GPS does not support until the user has
confirmed that offset against the tracks — an untouched check never counting as a confirmation.
:::

:::{rul} A confirmation holds for the offset it confirmed
:id: RUL-confirmation_holds_for_its_offset
:status: ruled
:criticality: high
:anti: yes
:verify: required
:refines: RUL-unanchored_offset_confirmed

A confirmation SHALL hold only for the offset it confirmed; a changed offset is asked about again.
:::


## 24. Every photo's own values

:::{rul} A photo's own values follow its fingerprint's new value
:id: RUL-own_values_follow_new_fingerprint
:status: ruled
:criticality: high
:anti: yes
:verify: required
:refines: RUL-geotag_rerun_keeps_settled

A photo whose fingerprint is taken again with a new value SHALL keep the own values geotag pinned for it under the old
one, so long as the change maps one value to one.
:::


## 25. Placing each photo

:::{rul} A photo's own position is kept
:id: RUL-own_position_kept
:status: ruled
:criticality: high
:anti: yes
:verify: required

Geotag SHALL never replace a photo's own GPS position.
:::

:::{rul} A photo is placed by the most specific source it has
:id: RUL-placement_order
:status: ruled
:criticality: high
:verify: required
:refines: RUL-own_position_kept

A photo with no position of its own SHALL be placed by the first that applies: a position the user set for it, the
tracks at its resolved time, its destination's folder fallback; one none places waits for the user to set one or to
leave it unlocated.
:::

:::{rul} A destination's fallback is the nearest one it lies in
:id: RUL-fallback_from_nearest
:status: ruled
:criticality: med
:verify: required
:refines: RUL-placement_order

A destination's folder-fallback proposal SHALL be the fallback in effect at the nearest destination it lies in that
has one.
:::

:::{rul} No destination waits on its fallback
:id: RUL-fallback_optional
:status: ruled
:criticality: low
:verify: required
:refines: RUL-placement_order

A destination SHALL never wait on its folder fallback: without one, its photos the tracks cannot place each ask on
their own.
:::

:::{rul} The tracks place a photo only within the configured limits
:id: RUL-track_placement_bounded
:status: seed
:criticality: high
:anti: yes
:verify: required
:refines: RUL-placement_order
:uses: DEF-tracks

A track SHALL place a photo only within the limits the configuration sets — never across a gap in time, a distance or a speed beyond them, and never farther past its end than they allow.
:::

:::{rul} A track's closest evidence is used first
:id: RUL-track_evidence_order
:status: seed
:criticality: med
:verify: required
:refines: RUL-track_placement_bounded

Of the ways a track can place a photo, geotag SHALL take the first that applies: a track point at its time, the place between the two points around it, the place past an end of the track — an end being where that track's own recording starts, stops or breaks off.
:::

:::{rul} Tracks in two places place nothing
:id: RUL-disagreeing_tracks_place_nothing
:status: seed
:criticality: high
:anti: yes
:verify: required
:refines: RUL-track_placement_bounded

Where tracks that cover a photo's time put it in places farther apart than the configuration joins points across, the tracks SHALL NOT place it, and the user is told which tracks disagree.
:::

:::{rul} A position says how it was found
:id: RUL-position_carries_its_method
:status: seed
:criticality: high
:verify: required

Every position geotag writes SHALL say, in the photo itself, how it was found: on a track point, between two, past a track's end, set for the photo, or its folder's fallback.
:::

:::{rul} A position from the tracks is recorded with its track
:id: RUL-placement_recorded_with_its_track
:status: seed
:criticality: med
:verify: required
:refines: RUL-cause_locatable

A position the tracks give a photo SHALL be recorded with the track that gave it and the time it was placed at.
:::

:::{rul} An unplaced photo is listed with why
:id: RUL-unplaced_photo_listed
:status: seed
:criticality: high
:verify: required
:refines: RUL-placement_order

Every photo no source places SHALL be listed for the user by itself, with why the tracks did not place it, until a position is set for it or it is left unlocated.
:::

:::{rul} A photo's decision follows the photo
:id: RUL-photo_decision_follows_the_photo
:status: seed
:criticality: high
:anti: yes
:verify: required
:refines: RUL-decision_kept

A decision made for one photo SHALL stay that photo's when geotag renames it or its fingerprint is taken again, and never pass to another photo that takes its name.
:::

:::{rul} An accepted inherited fallback follows the one above
:id: RUL-accepted_fallback_follows
:status: seed
:criticality: med
:verify: required
:refines: RUL-fallback_from_nearest

A destination whose inherited fallback the user accepted SHALL take the fallback then in effect above it, a later change there included.
:::


## 26. The corrected time

:::{rul} The corrected time is written as the destination's local time
:id: RUL-corrected_time_written_local
:status: seed
:criticality: high
:verify: required
:uses: DEF-geotag, DEF-destination

Geotag SHALL write each photo's true time into it as its destination's local time, with that time's offset from UTC beside it.
:::


## 28. The executable plan

:::{rul} A position is written whole
:id: RUL-position_written_whole
:status: ruled
:criticality: high
:anti: yes
:verify: required

A position geotag writes SHALL be written whole — latitude, longitude and their hemisphere references together — and
one it clears cleared whole.
:::

:::{rul} A camera's offset for a day holds for its later photos
:id: RUL-day_offset_kept_for_later_photos
:status: ruled
:criticality: high
:verify: required
:refines: RUL-offset_per_camera_destination_day

A camera's clock offset for a day, once resolved, SHALL stay that day's offset for photos of that camera arriving
later — one found from its own GPS included, though the later photos bring no anchor.
:::

:::{rul} A kept offset rests on what it was found from
:id: RUL-kept_offset_rests_on_its_tracks
:status: seed
:criticality: high
:anti: yes
:verify: required
:refines: RUL-day_offset_kept_for_later_photos

An offset found from a camera's own GPS SHALL be kept for later photos only while every track it was found from is there unchanged and no photo that has arrived since says otherwise.
:::

:::{rul} No plan while anything waits
:id: RUL-no_plan_while_a_decision_waits
:status: seed
:criticality: high
:anti: yes
:verify: required
:refines: RUL-time_before_gps
:uses: DEF-decision

Geotag SHALL make no executable plan while a decision waits for the user or a photo is neither placed nor left unlocated by the user.
:::

:::{rul} The plan counts how every photo is placed
:id: RUL-plan_counts_placement
:status: seed
:criticality: med
:verify: required
:uses: DEF-geotag

The executable plan SHALL count its photos by how each comes by its position — its own, each way the tracks or the user give one — those left without one among them.
:::


## 29. Execution

:::{rul} An interrupted execution is finished by running it again
:id: RUL-geotag_execution_resumable
:status: ruled
:criticality: high
:verify: required
:uses: DEF-geotag

A geotag execution interrupted SHALL be finished by running it again, which applies only what is outstanding — a
fully applied plan changing nothing, and an edit made to a photo since the plan never written over.
:::

:::{rul} A write that changes the picture is held back
:id: RUL-content_changed_write_held
:status: ruled
:criticality: high
:anti: yes
:verify: required
:refines: RUL-fingerprint_survives_mutation

A write after which a photo's decoded content differs SHALL NOT count as done — its rename held back with it — until
the user accepts the new content.
:::

:::{rul} One photo's failure is its own
:id: RUL-one_photo_failure_contained
:status: seed
:criticality: high
:anti: yes
:verify: required
:refines: RUL-every_change_journaled

A photo that cannot be applied SHALL fail alone, by name: every other photo's result is still recorded.
:::

:::{rul} What an interrupted run applied is recorded by the next
:id: RUL-applied_unrecorded_is_recorded
:status: seed
:criticality: high
:verify: required
:refines: RUL-every_change_journaled

A photo an interrupted execution applied and did not record SHALL be recorded as applied by the next — once seen to be that photo, holding what was planned — and never applied again.
:::

:::{rul} An acceptance of changed content is of that content
:id: RUL-content_acceptance_is_of_that_content
:status: seed
:criticality: high
:anti: yes
:verify: required
:refines: RUL-content_changed_write_held

An acceptance of a photo's changed content SHALL hold only for the content it was given for, under the plan that reported it — and stay open to give until the photo is applied.
:::

:::{rul} Another image engine stops execution before it writes
:id: RUL-engine_checked_before_writes
:status: seed
:criticality: high
:anti: yes
:verify: required
:refines: RUL-content_changed_write_held

Geotag SHALL NOT write to a photo while the image engine is not the one the photos' fingerprints were taken with.
:::


## 31. Finalize

:::{rul} Finalize packages only an execution that succeeded and still holds
:id: RUL-finalize_requires_success
:status: ruled
:criticality: high
:anti: yes
:verify: required
:uses: DEF-finalize

Finalize SHALL refuse unless geotag's current plan was executed successfully and still holds.
:::

:::{rul} Finalize packages the photos as execution left them
:id: RUL-finalize_checks_photos
:status: seed
:criticality: high
:anti: yes
:verify: required
:refines: RUL-finalize_requires_success
:uses: DEF-finalize

Finalize SHALL refuse while a photo in photos by destination is not as the execution left it — gone, changed since, or never in the plan.
:::

:::{rul} Finalize reports how every photo was placed
:id: RUL-finalize_reports_placement
:status: seed
:criticality: med
:verify: required
:refines: RUL-plan_counts_placement
:uses: DEF-finalize

Finalize SHALL report the plan's count of how every photo came by its position, and keep it in the package.
:::

:::{rul} A photo left unlocated is logged as such
:id: RUL-unlocated_logged
:status: seed
:criticality: med
:verify: required
:refines: RUL-log_cites_decisions

A photo the user left unlocated SHALL have that in its log, with the decision that left it so.
:::
