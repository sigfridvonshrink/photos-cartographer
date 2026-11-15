# Geotag — what it guarantees

What the second phase, {need}`DEF-geotag`, guarantees, beyond what [the shared contract](shared.md) binds every phase
to. *Why* each holds is in [the rationale](../rationale/geotag.md); *how this build meets it*, in
[the build](../build/geotag.md).

## 1. Core workflow rule

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

A photo in photos by destination carrying no recorded time SHALL stop geotag before it plans anything.
:::

:::{rul} A photo with no recorded time is named
:id: RUL-untimed_photo_named
:status: ruled
:criticality: high
:anti: yes
:verify: required
:refines: RUL-untimed_photo_stops_geotag
:uses: DEF-geotag, DEF-managed_folders, DEF-recorded_time

A photo that stops geotag for carrying no recorded time SHALL be named to the user as belonging in missing metadata.
:::

## 3. Linear dependency inclusion

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

## 4. Geotag scope

:::{rul} Geotag changes only the photos sorted into destinations
:id: RUL-geotag_changes_only_by_dest
:status: ruled
:criticality: high
:anti: yes
:verify: required
:uses: DEF-geotag, DEF-managed_folders

Geotag SHALL change only files in photos by destination — never a file in any other folder.
:::

:::{rul} A photo with no fingerprint stops geotag
:id: RUL-unfingerprinted_photo_stops_geotag
:status: ruled
:criticality: high
:anti: yes
:verify: required

Geotag SHALL NOT plan, execute or finalize while a photo in photos by destination has no fingerprint.
:::

:::{rul} Geotag plans only from metadata read as this build reads it
:id: RUL-handoff_fields_of_this_build
:status: ruled
:criticality: med
:anti: yes
:verify: required
:uses: DEF-geotag

Geotag SHALL NOT plan from prep's record of a photo whose metadata was read as another version of cartographer reads
it — another set of fields, or another order of finding them.
:::

:::{rul} Geotag runs prep itself only to record a sort
:id: RUL-auto_reprep_moves_no_media
:status: ruled
:criticality: high
:anti: yes
:verify: required

Geotag SHALL run prep's execution itself only where prep's plan moves, renames or sets aside no media file.
:::

:::{rul} Geotag changes no video
:id: RUL-video_never_changed
:status: ruled
:criticality: high
:anti: yes
:verify: required
:refines: RUL-geotag_changes_only_by_dest
:uses: DEF-geotag, DEF-managed_folders

Geotag SHALL never change a video.
:::

## 5. JSON artifact rule

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

A geotag plan stopped before its first decision stage SHALL write no record of its own.
:::

:::{rul} An early stop says why in its output
:id: RUL-early_stop_said_in_output
:status: ruled
:criticality: med
:verify: required
:refines: RUL-no_record_before_decisions
:uses: DEF-geotag

A geotag plan stopped before its first decision stage SHALL say what stopped it in its output.
:::

## 6. Human decision field rule

:::{rul} A camera's offset from its own GPS applies itself only as configured
:id: RUL-anchor_offset_auto_as_configured
:status: ruled
:criticality: high
:verify: required
:uses: DEF-geotag, DEF-decision

A clock offset proposed from a camera's own GPS positions SHALL take effect without the user's answer only as the
configuration's settings for one anchor and for several allow.
:::

:::{rul} Anchors that disagree apply nothing by themselves
:id: RUL-disagreeing_anchors_never_auto
:status: ruled
:criticality: high
:verify: required
:refines: RUL-anchor_offset_auto_as_configured
:uses: DEF-geotag, DEF-decision

A clock offset proposed from a camera's own GPS positions SHALL NOT take effect without the user's answer while its
anchors disagree.
:::

:::{rul} An inherited timezone applies itself
:id: RUL-timezone_auto_resolves
:status: ruled
:criticality: med
:verify: required
:uses: DEF-geotag, DEF-decision

A timezone a destination inherits from the destination it lies in SHALL take effect without the user's answer — save
where the destination's own photos speak against it ({need}`RUL-inherited_timezone_yields_to_photos`).
:::

:::{rul} A written timezone outranks an inherited one
:id: RUL-written_timezone_over_inherited
:status: ruled
:criticality: med
:verify: required
:refines: RUL-timezone_auto_resolves
:uses: DEF-geotag, DEF-decision

A timezone the user writes for a destination SHALL take effect over the one it inherits.
:::

:::{rul} A destination with no timezone to inherit waits
:id: RUL-no_timezone_to_inherit_waits
:status: ruled
:criticality: med
:verify: required
:refines: RUL-timezone_auto_resolves
:uses: DEF-geotag, DEF-decision

A destination with no timezone to inherit SHALL wait for the user.
:::

:::{rul} An inherited timezone yields to the destination's own photos
:id: RUL-inherited_timezone_yields_to_photos
:status: ruled
:criticality: high
:anti: yes
:verify: required
:uses: DEF-geotag, DEF-decision

An inherited timezone SHALL NOT take effect without the user's answer in a destination holding a photo, read by the
offset recorded with its time, whose offset is not that timezone's at the photo's time — one such photo being enough.
:::

:::{rul} A timezone the photos speak against is not passed down
:id: RUL-inherited_zone_stops_within
:status: ruled
:criticality: high
:anti: yes
:verify: required
:refines: RUL-inherited_timezone_yields_to_photos
:uses: DEF-geotag, DEF-decision

A timezone a destination's own photos speak against SHALL NOT take effect without the user's answer in a destination
lying within that one.
:::

:::{rul} A destination has one timezone
:id: RUL-destination_has_one_timezone
:status: ruled
:criticality: high
:verify: required
:uses: DEF-geotag

A destination holding photos SHALL have one timezone for all of them.
:::

:::{rul} A country gives its timezone, or none
:id: RUL-country_gives_its_timezone
:status: ruled
:criticality: high
:verify: required
:uses: DEF-geotag, DEF-decision

A destination the user says is in a country SHALL take that country's timezone, with every destination within it,
where the country has one.
:::

:::{rul} A country of several timezones gives none
:id: RUL-country_of_several_gives_none
:status: ruled
:criticality: high
:verify: required
:refines: RUL-country_gives_its_timezone
:uses: DEF-geotag, DEF-decision

A destination the user says is in a country of several timezones SHALL be given none, it and each destination within
answering for themselves.
:::

:::{rul} A timezone answered in a country is one of its own
:id: RUL-zone_among_countrys_only
:status: ruled
:criticality: high
:verify: required
:refines: RUL-country_gives_its_timezone
:uses: DEF-geotag, DEF-decision

A timezone answered for a destination in a country of several timezones SHALL be one of that country's timezones.
:::

:::{rul} A country is said once, at the top of its tree
:id: RUL-country_chosen_once
:status: ruled
:criticality: med
:verify: required
:refines: RUL-country_gives_its_timezone

A country said of a destination within one already said to be in a country SHALL be taken out of the decision.
:::

:::{rul} A country taken out is told, with why
:id: RUL-country_removal_told
:status: ruled
:criticality: med
:verify: required
:refines: RUL-country_chosen_once

The user SHALL be told of a country taken out of a decision, and why.
:::

:::{rul} A timezone stands against the photos only on the user's word
:id: RUL-zone_against_photos_needs_word
:status: ruled
:criticality: high
:anti: yes
:verify: required
:refines: RUL-destination_has_one_timezone

A destination's timezone, written or inherited, SHALL NOT take effect while a photo there, read by the offset recorded
with its time, records an offset that timezone does not have at the photo's time — until the user confirms the
timezone for the offsets those photos record.
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

:::{rul} A proposal waits for the user's acceptance
:id: RUL-proposals_need_acceptance
:status: ruled
:criticality: high
:anti: yes
:verify: required
:uses: DEF-geotag, DEF-decision

A proposal geotag makes SHALL take effect only once the user accepts it, save one a rule says takes effect without the
user's answer. A clock offset derived from the destination's timezone, or from the offset a camera's photos record with
their times, is such a proposal, and so is a folder fallback position inherited from the destination the folder lies
in.
:::

:::{rul} A confirmation against the tracks is an acceptance
:id: RUL-track_confirmation_is_acceptance
:status: ruled
:criticality: high
:verify: required
:refines: RUL-proposals_need_acceptance
:uses: DEF-geotag, DEF-decision

A timezone's offset, or one a camera's photos record, that the user confirms against the tracks SHALL count as
accepted by that confirmation ({need}`RUL-timezone_offset_asked_once`).
:::

:::{rul} A guessed offset is asked about once
:id: RUL-timezone_offset_asked_once
:status: ruled
:criticality: med
:verify: required
:uses: DEF-geotag, DEF-decision

A clock offset derived from the destination's timezone, or from the offset the camera's photos record, SHALL be asked
about once: at the check against the tracks where tracks lie by its photos, and by acceptance where none do.
:::

:::{rul} An acceptance holds for the proposal it accepted
:id: RUL-acceptance_holds_for_its_proposal
:status: ruled
:criticality: high
:anti: yes
:verify: required
:refines: RUL-proposals_need_acceptance

An acceptance of a proposed clock offset SHALL hold only while the offset proposed is the one that was accepted.
:::

:::{rul} A proposal that has become another is asked about again
:id: RUL-changed_proposal_asked_again
:status: ruled
:criticality: high
:verify: required
:refines: RUL-acceptance_holds_for_its_proposal

A proposal that has become another since it was accepted SHALL be asked about again.
:::

:::{rul} Geotag leaves the user's answer in place when its proposal changes
:id: RUL-stale_acceptance_kept
:status: ruled
:criticality: high
:anti: yes
:verify: required
:refines: RUL-acceptance_holds_for_its_proposal

When a proposal has become another since the user accepted it, geotag SHALL leave the user's earlier acceptance in the
decision exactly as the user wrote it, for the user to replace.
:::

:::{rul} A written value outranks an accepted proposal
:id: RUL-written_value_over_acceptance
:status: ruled
:criticality: med
:verify: required
:refines: RUL-proposals_need_acceptance

A value the user writes for a decision SHALL take effect over a proposal accepted for the same decision.
:::

:::{rul} A guessed offset that puts the photos where nothing else was is not taken on acceptance
:id: RUL-offset_far_from_evidence_asks
:status: ruled
:criticality: high
:anti: yes
:verify: required
:refines: RUL-proposals_need_acceptance
:uses: DEF-clock_offset, DEF-tracks

A clock offset proposed from the destination's timezone, or from the offset a camera's photos record, SHALL NOT take
effect without an offset the user writes where it would put every photo of its day farther than the largest clock
error the configuration allows from every track point and from the true time of every photo of the destination taken
by another device whose true time is known, at least one such photo being there.
:::


## 7. Per-destination structure

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

Each offset SHALL be proposed only from that camera's own positions on that day — in that destination, else in
another ({need}`RUL-offset_shared_within_day`) — or from the offset its photos there record with their times
({need}`RUL-recorded_offset_proposed`), or from the destination's timezone; never from another day's offset, nor from
one the user wrote or accepted on a guess in another destination.
:::

:::{rul} A day's offset is the camera's wherever its photos were sorted
:id: RUL-offset_shared_within_day
:status: ruled
:criticality: high
:verify: required
:refines: RUL-offset_per_camera_destination_day

A camera's photos of a day in a destination where none has its own position SHALL be proposed the offset the camera's
own positions gave that day in another destination, in place of the one their times record and the timezone's.
:::

:::{rul} A camera's offset is proposed from the offset its photos record
:id: RUL-recorded_offset_proposed
:status: ruled
:criticality: high
:verify: required
:refines: RUL-offset_per_camera_destination_day
:uses: DEF-clock_offset

A camera's photos of a day in a destination where none has its own position, and where every one of them recording an
offset with its time records the same one, SHALL be proposed the clock offset of a clock set to that offset, in place
of the timezone's.
:::

:::{rul} Photos recording different offsets propose none
:id: RUL-differing_recorded_offsets_propose_none
:status: ruled
:criticality: high
:anti: yes
:verify: required
:refines: RUL-recorded_offset_proposed

Geotag SHALL NOT propose a camera's clock offset of a day in a destination from the offsets its photos there record
with their times where they record different ones.
:::

:::{rul} A shared offset applies itself only where it did there
:id: RUL-shared_offset_auto_only_as_there
:status: ruled
:criticality: high
:verify: required
:refines: RUL-offset_shared_within_day

An offset proposed from another destination of the same day SHALL take effect by itself only where it did there.
:::

:::{rul} One clock is not read two ways in one day
:id: RUL-same_day_offsets_agree
:status: ruled
:criticality: high
:anti: yes
:verify: required
:refines: RUL-offset_per_camera_destination_day

Two offsets a camera's own positions gave on one day in different destinations, farther apart than the configuration
allows, SHALL NOT take effect until the user writes which is right.
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
:status: ruled
:criticality: high
:anti: yes
:verify: required
:refines: RUL-decision_kept
:uses: DEF-destination

An answer given for a camera's day in a destination SHALL stay that day's answer when photos of another day arrive there or leave.
:::


## 8. Reading the tracks

:::{rul} A track point's time is the instant it states
:id: RUL-track_time_never_guessed
:status: ruled
:criticality: high
:anti: yes
:verify: required
:uses: DEF-tracks

Geotag SHALL take a track point's time as the instant it states, whatever its precision or the offset it is written
with.
:::

:::{rul} A track point geotag cannot use is skipped
:id: RUL-unreadable_point_skipped
:status: ruled
:criticality: med
:verify: required
:uses: DEF-tracks

A track point geotag cannot use — no position or one out of range, no time, an unreadable time, or one stating no
zone — SHALL be skipped.
:::

:::{rul} A track point geotag skips is reported
:id: RUL-unreadable_point_reported
:status: ruled
:criticality: med
:verify: required
:refines: RUL-unreadable_point_skipped
:uses: DEF-tracks

A track point geotag skips SHALL be reported to the user, naming its file and point.
:::

:::{rul} Tracks that are configured and not there stop geotag
:id: RUL-missing_tracks_stop_geotag
:status: ruled
:criticality: high
:anti: yes
:verify: required
:uses: DEF-tracks

Geotag SHALL NOT plan while the tracks folder the configuration names is not there.
:::

:::{rul} Tracks none of which can be read stop geotag
:id: RUL-unreadable_tracks_stop_geotag
:status: ruled
:criticality: high
:anti: yes
:verify: required
:uses: DEF-tracks

Geotag SHALL NOT plan while its tracks folder holds track files of which not one can be read.
:::

:::{rul} Geotag runs without tracks
:id: RUL-no_tracks_no_stop
:status: ruled
:criticality: med
:verify: required
:uses: DEF-tracks

Geotag SHALL proceed where no tracks folder is configured or the folder holds no track, each decision resting on its other sources.
:::

:::{rul} A photo is placed from one track file only
:id: RUL-tracks_never_joined
:status: ruled
:criticality: high
:anti: yes
:verify: required
:uses: DEF-tracks

Geotag SHALL never place a photo from a point of one track file taken with a point of another, whether between the
two points or beyond them.
:::

:::{rul} No clock is anchored between two tracks
:id: RUL-tracks_never_joined_to_anchor
:status: ruled
:criticality: high
:anti: yes
:verify: required
:refines: RUL-tracks_never_joined
:uses: DEF-tracks

Geotag SHALL never join a point of one track file to a point of another to anchor a clock on the line between them.
:::

:::{rul} Each track of a file is a track of its own
:id: RUL-track_is_one_trk
:status: ruled
:criticality: high
:anti: yes
:verify: required
:refines: RUL-tracks_never_joined
:uses: DEF-tracks

Geotag SHALL treat each track a track file holds as a track of its own, never joined to another of the same file.
:::

:::{rul} A break in a recording is never bridged
:id: RUL-track_break_never_bridged
:status: ruled
:criticality: high
:anti: yes
:verify: required
:uses: DEF-tracks

Geotag SHALL NOT place a photo or anchor a clock across a break between two segments of one track.
:::

:::{rul} A track ranks by the folder it is filed in
:id: RUL-tracks_ranked_by_folder
:status: ruled
:criticality: high
:verify: required
:uses: DEF-tracks, DEF-configuration

Where the configuration ranks folders of the tracks, each track SHALL rank as the folder it is filed in, a track in no
ranked folder below every ranked one, and tracks of one rank alike.
:::

:::{rul} A ranked folder the tracks lack is told
:id: RUL-ranked_folder_missing_told
:status: ruled
:criticality: med
:verify: required
:refines: RUL-tracks_ranked_by_folder

The user SHALL be told of each folder the configuration ranks that the tracks do not hold.
:::

:::{rul} The ranking is a dependency of what the tracks decide
:id: RUL-track_ranking_in_dependencies
:status: ruled
:criticality: high
:verify: required
:refines: RUL-tracks_in_dependencies

Geotag SHALL record the ranking of the tracks with their fingerprint, so that a change to the ranking makes stale every
record a change to the tracks would.
:::


## 9. Camera groups

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

Geotag SHALL offer the classification of every unknown camera group ready to paste into the configuration.
:::

:::{rul} The offer keeps every group already classed
:id: RUL-classed_groups_kept_in_offer
:status: ruled
:criticality: low
:verify: required
:refines: RUL-unknown_group_classification_offered

The classification geotag offers SHALL keep every group already classed as it is.
:::

:::{rul} A file naming no camera is solved on its own
:id: RUL-unidentified_files_solved_alone
:status: ruled
:criticality: med
:anti: yes
:verify: required
:uses: DEF-camera_group

A file whose metadata names no camera SHALL be solved on its own — by the offset recorded with its time, else its
destination's timezone.
:::

:::{rul} A file naming no camera is never asked to be classed
:id: RUL-unidentified_never_classed
:status: ruled
:criticality: med
:anti: yes
:verify: required
:refines: RUL-unidentified_files_solved_alone
:uses: DEF-camera_group

A file whose metadata names no camera SHALL never be asked to be classed.
:::

:::{rul} A file naming no camera takes no camera's offset
:id: RUL-unidentified_no_camera_offset
:status: ruled
:criticality: med
:anti: yes
:verify: required
:refines: RUL-unidentified_files_solved_alone
:uses: DEF-camera_group

A file whose metadata names no camera SHALL never be given a camera's clock offset.
:::

:::{rul} A photo timed by its modification is solved on its own
:id: RUL-modified_time_solved_alone
:status: ruled
:criticality: high
:anti: yes
:verify: required
:uses: DEF-recorded_time, DEF-camera_group, RUL-recorded_time_order

A photo whose recorded time is read from its `ModifyDate` SHALL be solved on its own, as a file naming no camera is,
whatever camera its metadata names.
:::

:::{rul} A photo timed by its modification takes no camera's offset
:id: RUL-modified_time_no_camera_offset
:status: ruled
:criticality: high
:anti: yes
:verify: required
:refines: RUL-modified_time_solved_alone
:uses: DEF-clock_offset

A photo whose recorded time is read from its `ModifyDate` SHALL never be given its camera's clock offset.
:::

:::{rul} A photo timed by its modification is in none of its camera's days
:id: RUL-modified_time_opens_no_day
:status: ruled
:criticality: med
:anti: yes
:verify: required
:refines: RUL-modified_time_solved_alone
:uses: RUL-offset_per_camera_destination_day

A photo whose recorded time is read from its `ModifyDate` SHALL never open a day of its camera's clock offsets, nor be
counted in one.
:::

:::{rul} A group classed both ways is unknown
:id: RUL-group_classed_twice_is_unknown
:status: ruled
:criticality: high
:anti: yes
:verify: required
:refines: RUL-unknown_group_stops_geotag

Geotag SHALL NOT plan while the configuration classes a camera group as both a phone and a camera.
:::


## 10. Destination civil timezone

:::{rul} A destination takes the nearest timezone it lies in
:id: RUL-timezone_from_nearest
:status: ruled
:criticality: med
:verify: required
:refines: RUL-timezone_auto_resolves

A destination's proposed timezone SHALL be the one in effect at the nearest destination it lies in that has one —
however it was reached there.
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


## 11. Clock offsets from the camera's own GPS

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

:::{rul} A lower-ranked track anchors only where no higher one recorded
:id: RUL-lower_track_anchors_where_higher_absent
:status: ruled
:criticality: high
:anti: yes
:verify: required
:refines: RUL-tracks_ranked_by_folder

A lower-ranked track SHALL anchor a camera's clock at a time only where no higher-ranked track has a point at that
time or two around it that a photo could be placed between.
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
:status: ruled
:criticality: high
:anti: yes
:verify: required
:refines: RUL-anchor_consensus

An offset the camera's photos fix only to within a stay of the tracks at their place — longer than the configuration
counts as a moment — SHALL NOT take effect without the user's answer.
:::

:::{rul} An offset from a stay is never anchored
:id: RUL-stay_offset_never_anchored
:status: ruled
:criticality: high
:anti: yes
:verify: required
:refines: RUL-stay_fixes_no_clock

An offset fixed only to within a stay of the tracks SHALL NOT count as anchored once accepted.
:::

:::{rul} A proposal from GPS is recorded with its evidence
:id: RUL-anchor_proposal_carries_evidence
:status: ruled
:criticality: med
:verify: required
:refines: RUL-anchor_consensus

A clock offset proposed from a camera's own GPS SHALL be recorded with the photos that support it, the photos that do not, and the track each was matched to.
:::


## 13. Resolved UTC

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

:::{rul} An offset inside the time's own value is recorded with it
:id: RUL-offset_within_time_value
:status: ruled
:criticality: high
:anti: yes
:verify: required
:refines: RUL-phone_time_from_own_offset

An offset written within the value of a time field itself SHALL count as the offset recorded with that time.
:::

:::{rul} An offset inside the value comes before one beside it
:id: RUL-offset_within_value_before_beside
:status: ruled
:criticality: high
:verify: required
:refines: RUL-offset_within_time_value

An offset written within a time's value SHALL be taken before one in a field beside it.
:::

:::{rul} A time a daylight-saving change skips or repeats is never guessed
:id: RUL-ambiguous_local_time_never_guessed
:status: ruled
:criticality: high
:anti: yes
:verify: required

Geotag SHALL NOT resolve by a timezone a local time which that timezone skips or repeats at a daylight-saving change.
:::

:::{def} A clock offset
:id: DEF-clock_offset
:status: ruled
:uses: DEF-recorded_time, DEF-camera_group

A camera's **clock offset** is the whole number of seconds added to its recorded time to give UTC: the timezone its
clock was set to and the clock's own error, together. A camera keeping exact Brussels summer time has −7200, not 0.
:::


## 14. The GPS-drift check

:::{rul} An offset the camera's GPS does not support is confirmed before photos are placed by it
:id: RUL-unanchored_offset_confirmed
:status: ruled
:criticality: high
:anti: yes
:verify: required
:uses: DEF-tracks

Photos SHALL NOT be placed by the tracks on a clock offset the camera's own GPS does not support until the user has
confirmed that offset against the tracks.
:::

:::{rul} An untouched check confirms nothing
:id: RUL-untouched_check_confirms_nothing
:status: ruled
:criticality: high
:anti: yes
:verify: required
:refines: RUL-unanchored_offset_confirmed
:uses: DEF-tracks

A check against the tracks left untouched SHALL never count as a confirmation.
:::

:::{rul} A confirmation holds for the offset it confirmed
:id: RUL-confirmation_holds_for_its_offset
:status: ruled
:criticality: high
:anti: yes
:verify: required
:refines: RUL-unanchored_offset_confirmed

A confirmation SHALL hold only for the offset it confirmed.
:::

:::{rul} A changed offset is asked about again
:id: RUL-changed_offset_asked_again
:status: ruled
:criticality: high
:verify: required
:refines: RUL-confirmation_holds_for_its_offset

An offset changed since it was confirmed SHALL be asked about again.
:::

:::{rul} A confirmation rests on the tracks it was made against
:id: RUL-confirmation_rests_on_its_tracks
:status: ruled
:criticality: high
:anti: yes
:verify: required
:refines: RUL-unanchored_offset_confirmed
:uses: DEF-tracks

A confirmation SHALL hold only while every track it was made against is there unchanged.
:::

:::{rul} A changed track is asked about again
:id: RUL-changed_tracks_asked_again
:status: ruled
:criticality: high
:verify: required
:refines: RUL-confirmation_rests_on_its_tracks
:uses: DEF-tracks

A check whose confirmation was made against a track since removed or changed SHALL be asked about again.
:::

:::{rul} A confirmation made with no track holds while there is none
:id: RUL-trackless_confirmation_holds_while_none
:status: ruled
:criticality: high
:anti: yes
:verify: required
:refines: RUL-confirmation_rests_on_its_tracks
:uses: DEF-tracks

A confirmation made where no track lay by the photos SHALL hold only while none lies by them.
:::

:::{rul} Geotag leaves a confirmation asked about again as the user wrote it
:id: RUL-stale_confirmation_kept
:status: ruled
:criticality: high
:anti: yes
:verify: required
:refines: RUL-unanchored_offset_confirmed

When a check is asked about again, geotag SHALL leave the user's earlier confirmation in the decision exactly as the
user wrote it, for the user to replace.
:::


## 15. Every photo's own values

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


## 16. Placing each photo

:::{rul} A photo's own position is kept
:id: RUL-own_position_kept
:status: ruled
:criticality: high
:anti: yes
:verify: required

Geotag SHALL never replace a photo's own GPS position.
:::

:::{rul} A position at latitude 0 and longitude 0 is none
:id: RUL-null_island_is_no_position
:status: ruled
:criticality: high
:verify: required
:refines: RUL-own_position_kept

A photo whose position is latitude 0 and longitude 0 SHALL count, wherever geotag judges a photo's own position, as
having none.
:::

:::{rul} A photo is placed by the most specific source it has
:id: RUL-placement_order
:status: ruled
:criticality: high
:verify: required
:refines: RUL-own_position_kept

A photo with no position of its own SHALL be placed by the first that applies: a position the user set for it, the
tracks at its resolved time, its destination's folder fallback.
:::

:::{rul} A photo nothing places waits for the user
:id: RUL-unplaced_photo_waits
:status: ruled
:criticality: high
:verify: required
:refines: RUL-placement_order

A photo none of these places SHALL wait for the user to set a position or to leave it unlocated.
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

A destination SHALL never wait on its folder fallback.
:::

:::{rul} The tracks place a photo only within the configured limits
:id: RUL-track_placement_bounded
:status: ruled
:criticality: high
:anti: yes
:verify: required
:refines: RUL-placement_order
:uses: DEF-tracks

A track SHALL place a photo only within the limits the configuration sets — never across a gap in time, a distance or a speed beyond them, and never farther past its end than they allow.
:::

:::{rul} A track's closest evidence is used first
:id: RUL-track_evidence_order
:status: ruled
:criticality: med
:verify: required
:refines: RUL-track_placement_bounded

Of the ways a track can place a photo, geotag SHALL take the first that applies: a track point at its time, the place between the two points around it, the place past an end of the track — an end being where that track's own recording starts, stops or breaks off.
:::

:::{rul} The highest-ranked track that covers a photo places it
:id: RUL-highest_ranked_track_places
:status: ruled
:criticality: high
:anti: yes
:verify: required
:refines: RUL-tracks_ranked_by_folder

Of the tracks that place a photo, the highest-ranked SHALL place it, whatever a lower-ranked track says — a track that
places it only past its end counting where no track places it on a point or between two.
:::

:::{rul} Tracks of one rank in two places place nothing
:id: RUL-disagreeing_tracks_place_nothing
:status: ruled
:criticality: high
:anti: yes
:verify: required
:refines: RUL-track_placement_bounded

Where tracks of the highest rank that cover a photo's time put it in places farther apart than the configuration lets
tracks differ, the tracks SHALL NOT place it.
:::

:::{rul} Tracks that disagree are named
:id: RUL-disagreeing_tracks_named
:status: ruled
:criticality: high
:verify: required
:refines: RUL-disagreeing_tracks_place_nothing

The user SHALL be told which tracks disagree over a photo's place.
:::

:::{rul} A position says how it was found
:id: RUL-position_carries_its_method
:status: ruled
:criticality: high
:verify: required

Every position geotag writes SHALL say, in the photo itself, how it was found: on a track point, between two, past a track's end, set for the photo, or its folder's fallback.
:::

:::{rul} A position from the tracks is recorded with its track
:id: RUL-placement_recorded_with_its_track
:status: ruled
:criticality: med
:verify: required
:refines: RUL-cause_locatable

A position the tracks give a photo SHALL be recorded in the workspace's record with the track that gave it and the
time it was placed at.
:::

:::{rul} A position is recorded with how far the lower-ranked tracks put it
:id: RUL-lower_track_distance_recorded
:status: ruled
:criticality: med
:verify: required
:refines: RUL-placement_recorded_with_its_track

A position the tracks give a photo SHALL be recorded with each lower-ranked track that placed it the same way and how far
from the position that track put it.
:::

:::{rul} Lower-ranked tracks that disagree are counted
:id: RUL-lower_track_disagreements_told
:status: ruled
:criticality: med
:verify: required
:refines: RUL-lower_track_distance_recorded

The user SHALL be told, for each lower-ranked track, how many photos it put farther from where a higher-ranked track
placed them than the configuration lets tracks differ.
:::

:::{rul} The track is not written in the photo
:id: RUL-track_never_written_in_photo
:status: ruled
:criticality: med
:verify: required
:refines: RUL-placement_recorded_with_its_track

The track that gave a photo its position SHALL NOT be written in the photo.
:::

:::{rul} An unplaced photo is listed with why
:id: RUL-unplaced_photo_listed
:status: ruled
:criticality: high
:verify: required
:refines: RUL-placement_order

Every photo no source places SHALL be listed for the user by itself, until a position is set for it or it is left
unlocated.
:::

:::{rul} An unplaced photo is listed with why
:id: RUL-unplaced_photo_says_why
:status: ruled
:criticality: high
:verify: required
:refines: RUL-unplaced_photo_listed

A photo listed as unplaced SHALL be listed with why the tracks did not place it.
:::

:::{rul} A photo's decision follows the photo
:id: RUL-photo_decision_follows_the_photo
:status: ruled
:criticality: high
:anti: yes
:verify: required
:refines: RUL-decision_kept

A decision made for one photo SHALL stay that photo's when geotag renames it or its fingerprint is taken again.
:::

:::{rul} A photo's decision never passes with its name
:id: RUL-photo_decision_never_passes_by_name
:status: ruled
:criticality: high
:anti: yes
:verify: required
:refines: RUL-photo_decision_follows_the_photo

A decision made for one photo SHALL never pass to another photo that takes its name.
:::

:::{rul} An accepted inherited fallback follows the one above
:id: RUL-accepted_fallback_follows
:status: ruled
:criticality: med
:verify: required
:refines: RUL-fallback_from_nearest

A destination whose inherited fallback the user accepted SHALL take the fallback then in effect above it, a later change there included.
:::


## 17. The corrected time

:::{rul} The corrected time is written as the destination's local time
:id: RUL-corrected_time_written_local
:status: ruled
:criticality: high
:verify: required
:uses: DEF-geotag, DEF-destination

Geotag SHALL write each photo's true time into it as its destination's local time.
:::

:::{rul} The time's offset is written beside it
:id: RUL-time_offset_written_beside
:status: ruled
:criticality: high
:verify: required
:refines: RUL-corrected_time_written_local
:uses: DEF-geotag, DEF-destination

Geotag SHALL write beside each time it writes that time's offset from UTC.
:::

:::{rul} Every field recording the making holds the corrected time
:id: RUL-other_capture_times_corrected
:status: ruled
:criticality: med
:verify: required
:refines: RUL-corrected_time_written_local
:uses: DEF-geotag, DEF-destination

Geotag SHALL write each photo's true time, as its destination's local time, also into every other field in which the
photo already records when it was made, adding none it does not hold.
:::


## 19. The executable plan

:::{rul} A position is written whole
:id: RUL-position_written_whole
:status: ruled
:criticality: high
:anti: yes
:verify: required

A position geotag writes SHALL be written whole — latitude, longitude and their hemisphere references together.
:::

:::{rul} A position is cleared whole
:id: RUL-position_cleared_whole
:status: ruled
:criticality: high
:verify: required
:refines: RUL-position_written_whole

A position geotag clears SHALL be cleared whole.
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
:status: ruled
:criticality: high
:anti: yes
:verify: required
:refines: RUL-day_offset_kept_for_later_photos

An offset found from a camera's own GPS SHALL be kept for later photos only while every track it was found from is
there unchanged.
:::

:::{rul} A kept offset yields to a photo that says otherwise
:id: RUL-kept_offset_yields_to_new_photo
:status: ruled
:criticality: high
:anti: yes
:verify: required
:refines: RUL-kept_offset_rests_on_its_tracks

An offset found from a camera's own GPS SHALL be kept for later photos only while no photo that has arrived since says
otherwise.
:::

:::{rul} No plan while anything waits
:id: RUL-no_plan_while_a_decision_waits
:status: ruled
:criticality: high
:anti: yes
:verify: required
:refines: RUL-time_before_gps
:uses: DEF-decision

Geotag SHALL make no executable plan while a decision waits for the user or a photo is neither placed nor left unlocated by the user.
:::

:::{rul} The plan counts how every photo is placed
:id: RUL-plan_counts_placement
:status: ruled
:criticality: med
:verify: required
:uses: DEF-geotag

The executable plan SHALL count its photos by how each comes by its position — its own, each way the tracks or the user give one — those left without one among them.
:::


## 20. Execution

:::{rul} An interrupted execution is finished by running it again
:id: RUL-geotag_execution_resumable
:status: ruled
:criticality: high
:verify: required
:uses: DEF-geotag

A geotag execution interrupted SHALL be finished by running it again, which applies only what is outstanding — a fully
applied plan changing nothing.
:::

:::{rul} An edit made since the plan is never written over
:id: RUL-edit_since_plan_never_overwritten
:status: ruled
:criticality: high
:verify: required
:refines: RUL-geotag_execution_resumable
:uses: DEF-geotag

An execution run again SHALL never write over an edit made to a photo since the plan.
:::

:::{rul} A write that changes the picture is held back
:id: RUL-content_changed_write_held
:status: ruled
:criticality: high
:anti: yes
:verify: required
:refines: RUL-fingerprint_survives_mutation

A write after which a photo's decoded content differs SHALL NOT count as done until the user accepts the new content.
:::

:::{rul} A held write holds the rename back
:id: RUL-rename_held_with_write
:status: ruled
:criticality: high
:verify: required
:refines: RUL-content_changed_write_held

A photo's rename SHALL be held back while a write to it is not counted as done.
:::

:::{rul} One photo's failure is its own
:id: RUL-one_photo_failure_contained
:status: ruled
:criticality: high
:anti: yes
:verify: required
:refines: RUL-every_change_journaled

A photo whose planned changes cannot be made SHALL fail alone: every other photo's result is still recorded.
:::

:::{rul} A photo that fails is named
:id: RUL-failed_photo_named
:status: ruled
:criticality: high
:verify: required
:refines: RUL-one_photo_failure_contained

A photo whose planned changes cannot be made SHALL be reported by name.
:::

:::{rul} What an interrupted run changed is recorded by the next
:id: RUL-applied_unrecorded_is_recorded
:status: ruled
:criticality: high
:verify: required
:refines: RUL-every_change_journaled

Changes an interrupted execution made to a photo and did not record SHALL be recorded as made by the next — once the
photo is seen to be that photo, holding what was planned.
:::

:::{rul} What an interrupted run changed is never made again
:id: RUL-found_applied_never_remade
:status: ruled
:criticality: high
:verify: required
:refines: RUL-applied_unrecorded_is_recorded

Changes an interrupted execution made to a photo and did not record SHALL never be made again.
:::

:::{rul} An acceptance of changed content is of that content
:id: RUL-content_acceptance_is_of_that_content
:status: ruled
:criticality: high
:anti: yes
:verify: required
:refines: RUL-content_changed_write_held

An acceptance of a photo's changed content SHALL hold only for the content it was given for.
:::

:::{rul} An acceptance of changed content is under its plan
:id: RUL-content_acceptance_under_its_plan
:status: ruled
:criticality: high
:verify: required
:refines: RUL-content_acceptance_is_of_that_content

An acceptance of a photo's changed content SHALL hold only under the plan that reported it.
:::

:::{rul} Changed content stays open to accept
:id: RUL-content_acceptance_stays_open
:status: ruled
:criticality: high
:verify: required
:refines: RUL-content_acceptance_is_of_that_content

A photo's changed content SHALL stay open to accept until the photo's changes are made.
:::

:::{rul} Another image engine stops execution before it writes
:id: RUL-engine_checked_before_writes
:status: ruled
:criticality: high
:anti: yes
:verify: required
:refines: RUL-content_changed_write_held

Geotag SHALL NOT write to a photo while the image engine is not the one the photos' fingerprints were taken with.
:::

:::{rul} A record of an earlier execution that cannot be read stops geotag
:id: RUL-unreadable_execution_record_stops
:status: ruled
:criticality: high
:anti: yes
:verify: required
:refines: RUL-every_change_journaled
:uses: DEF-geotag

Geotag's execution and finalize SHALL NOT take a record of an earlier execution that they cannot read for none: they
stop before they change or write anything, naming it.
:::


## 21. Finalize

:::{rul} Finalize packages only an execution that succeeded and still holds
:id: RUL-finalize_requires_success
:status: ruled
:criticality: high
:anti: yes
:verify: required
:uses: DEF-finalize

Finalize SHALL refuse unless geotag's current plan was executed successfully.
:::

:::{rul} Finalize packages only a plan that still holds
:id: RUL-finalize_requires_plan_still_holds
:status: ruled
:criticality: high
:verify: required
:refines: RUL-finalize_requires_success
:uses: DEF-finalize

Finalize SHALL refuse unless the plan that was executed still holds.
:::

:::{rul} Finalize packages the photos as execution left them
:id: RUL-finalize_checks_photos
:status: ruled
:criticality: high
:anti: yes
:verify: required
:refines: RUL-finalize_requires_success
:uses: DEF-finalize

Finalize SHALL refuse while a photo in photos by destination is not as the execution left it — gone, changed since, or never in the plan.
:::

:::{rul} Finalize reports how every photo was placed
:id: RUL-finalize_reports_placement
:status: ruled
:criticality: med
:verify: required
:refines: RUL-plan_counts_placement
:uses: DEF-finalize

Finalize SHALL report the plan's count of how every photo came by its position.
:::

:::{rul} Finalize keeps the placement count in the package
:id: RUL-finalize_keeps_placement_count
:status: ruled
:criticality: med
:verify: required
:refines: RUL-finalize_reports_placement
:uses: DEF-finalize

Finalize SHALL keep the plan's count of how every photo came by its position in the package.
:::

:::{rul} A photo left unlocated is logged as such
:id: RUL-unlocated_logged
:status: ruled
:criticality: med
:verify: required
:refines: RUL-log_cites_decisions

A photo the user left unlocated SHALL have that in its log, with the decision that left it so.
:::

:::{rul} Finalize needs no tool it never runs
:id: RUL-finalize_needs_no_metadata_tool
:status: ruled
:criticality: med
:anti: yes
:verify: required
:uses: DEF-finalize

Finalize SHALL NOT refuse for want of the tool geotag reads and writes photos' metadata with, which it never runs.
:::
