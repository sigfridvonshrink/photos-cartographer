# Geotag — why

**Not normative.** Each item here is the reasoning behind the [intent](../intent/geotag.md) or [build](../build/geotag.md)
items it `justifies`, under the same section numbers. Where the two differ, the intent wins and this is stale.

## 1. Core workflow rule

:::{rat} A position is looked up by time
:id: RAT-position_follows_time
:status: ruled
:forced: yes
:follows_from: RAT-track_squeezed, RAT-offset_per_camera_destination_day
:justifies: RUL-time_before_gps

A photo with no position of its own is placed where the track was at the moment it was taken — its true time, after
the camera's clock is corrected. Placed before that time is settled, it would be placed at the wrong moment of the
track, possibly kilometres off, and every position would have to be planned again once the time changed. So the time
is settled for every photo first, and only then is any position planned.
:::

:::{rat} No phase invents a time
:id: RAT-no_phase_invents_time
:status: ruled
:forced: no
:follows_from: RAT-untimed_set_apart, CHC-ask_only_what_data_cannot_settle
:justifies: RUL-untimed_photo_stops_geotag

A photo with no recorded time has nothing to correct and nothing to look up: its true time is unknown, and no
camera's offset or destination's timezone can supply one. Prep sets such a photo aside in missing metadata for the
user to deal with by hand. Sorted into a destination anyway, it would pass through geotag's decisions with nothing to
ask about it and stop only at the last plan, where nothing the user could decide would clear it. Stopping at the start,
naming it and where it belongs, makes the one possible fix plain.
:::

## 3. Linear dependency inclusion

:::{rat} A chain is only as fresh as its weakest link
:id: RAT-no_chain_of_vouching
:status: ruled
:forced: yes
:follows_from: RAT-no_mutation_outside_plan
:justifies: RUL-geotag_plan_carries_every_dependency

The decision records are files the user edits between runs, in the editor or by hand. If the plan named only the last
of them and trusted it to name the rest, a change upstream of it — a track added, an earlier record edited after the
later one was written — would pass unseen whenever the later record happened not to be rewritten. Carried in the plan
itself, every input is checked against what it is now, at the one moment that matters: just before anything changes.
:::

## 4. Geotag scope

:::{rat} Only what the user sorted is ready
:id: RAT-only_sorted_is_ready
:status: ruled
:forced: yes
:follows_from: RAT-piggyback_on_the_destination_sort
:justifies: RUL-geotag_changes_only_by_dest

A photo's destination is what geotag corrects it by: the timezone of the place, the offset of that camera on that
day, the fallback position of the folder. A photo not yet sorted has none of these, and a file in the other folders is
not a photo to place — a stray, one missing metadata, a JPEG set aside beside its RAW. Videos stay where prep put them:
the pipeline does not place them, and a tag written into one would be a guess. Sorting a photo into a destination is
the user's statement that it is ready.
:::

:::{rat} No identity, no change
:id: RAT-no_identity_no_change
:status: ruled
:forced: no
:follows_from: RAT-recoverable_core
:justifies: RUL-unfingerprinted_photo_stops_geotag, RUL-unfingerprinted_photo_stops_merge

A photo's own values are kept under its fingerprint before geotag first writes to it, and every later step finds the photo by it. One prep could not fingerprint cannot have its values kept, cannot be recognised after a write, and cannot be looked for in the library: writing to it or merging it is a change nothing can check or undo.
:::

:::{rat} Running prep for the user is a convenience, not a decision
:id: RAT-auto_reprep_only_records
:status: ruled
:forced: no
:follows_from: RAT-recoverable_core
:justifies: RUL-auto_reprep_moves_no_media

Geotag runs prep itself so that sorting photos and going straight to geotag works. That is safe while prep only records the sort. Where prep's plan would rename or set aside a file, the user has not seen that plan, and geotag running it would be a change nobody asked for.
:::


## 5. JSON artifact rule

:::{rat} A missing record should mean one thing
:id: RAT-record_means_stage_reached
:status: ruled
:forced: no
:follows_from: RAT-plain_json_record
:justifies: RUL-decision_stage_writes_record, RUL-no_record_before_decisions

The decision records are what the user, the editor and the next stage read. Written at every stage reached — even
when it holds nothing to decide — a record's presence says the stage ran and its status says what is left; its absence
can only mean the stage was not reached. Were an all-automatic stage to write nothing, an absent record would mean either
"nothing to decide" or "never got here", and a record written by a run that stopped at a gate would look like a
decision to act on when there was none.
:::

## 6. Human decision field rule

:::{rat} The camera's own GPS is evidence; the user decides how much
:id: RAT-anchor_evidence_trusted_as_configured
:status: ruled
:forced: no
:follows_from: RAT-minimal_cascading_asks, RAT-clustering_details
:justifies: RUL-anchor_offset_auto_as_configured

An offset measured from the camera's own positions against the tracks is evidence, not a guess: several frames agreeing
on it is hard to get by accident; one frame could be a coincidence of a slow walk. How much of that to accept without a
look is the user's choice, made once in the configuration rather than asked for every camera on every day. Anchors that
disagree mean something is off — a clock reset in the day, a wrong track — and no setting should paper over that.
:::

:::{rat} A nested place is in its parent's timezone
:id: RAT-nested_place_same_timezone
:status: ruled
:forced: no
:follows_from: RAT-decisions_cascade, RAT-destination_tree_is_a_hierarchy
:justifies: RUL-timezone_auto_resolves

Destinations nest geographically — a city in a country, a museum in a city — so one inside a destination of known
timezone can scarcely lie in another. Asking the user to confirm it for every folder would be asking what the tree
already says. Where the tree says nothing — no ancestor and no default — there is nothing to propose, and the user must
answer.
:::

:::{rat} An assumption is the user's to accept
:id: RAT-assumptions_need_acceptance
:status: ruled
:forced: yes
:follows_from: CHC-ask_only_what_data_cannot_settle, CHC-photos_matter
:justifies: RUL-proposals_need_acceptance

An offset derived from the timezone assumes the camera was set to local time that day; a fallback inherited from a
parent folder assumes the photos were taken near the parent's point. Both are often right and sometimes badly wrong,
and nothing in the photos can tell which. Applied silently, a wrong one would place a whole day of photos in the wrong
place or the wrong hour, written into the originals; offered for acceptance, it costs one confirmation.
:::

:::{rat} What the photos record outranks what the folder assumes
:id: RAT-photos_outrank_inheritance
:status: ruled
:forced: yes
:follows_from: RAT-nested_place_same_timezone, RAT-phone_records_its_offset
:justifies: RUL-inherited_timezone_yields_to_photos

A place inside another is nearly always in its timezone; that is an assumption about folders. A phone's photo that
records +02:00 where the inherited zone was at +01:00 is evidence, in the photo, that the assumption fails here — a
country spanning zones, a border crossed, a folder that groups a trip instead of a place. Adopted unasked, the wrong
zone names and times every photo there an hour out, and proposes a camera's clock from the wrong hour. One photo is
enough to ask: a phone does not record another zone's offset by accident, and the answer costs one choice. A camera's
offset tag is not such evidence — it says what the clock was set to, and a camera left on home time would stop every
destination abroad.
:::

:::{rat} One timezone, because that is what can be checked
:id: RAT-one_zone_can_be_checked
:status: ruled
:forced: yes
:follows_from: RAT-nested_place_same_timezone, RAT-photos_outrank_inheritance
:justifies: RUL-destination_has_one_timezone, RUL-zone_against_photos_needs_word

A destination's photos are written and named in its timezone, so it can have only one. That is all the tree is asked
to be: a folder holding no photo may lie above destinations of any zones — a year, a country of several — because it
has no time of its own to get wrong; what it is given passes down only as far as the photos below agree. Whether a
folder is a place or a trip the tool cannot read off its name, and need not: the harm of a tree that is not one of
places is a zone applied where it is false, and that shows in the photos. So a zone, written or inherited, is set
against what the destination's own photos record; where they record another offset the user moves them, picks their
zone, or keeps it by a word that names the offsets it was given for — a phone left on another zone is real, and rare
enough to be said.
:::

:::{rat} The user says which country a folder is in; the zone database says the rest
:id: RAT-country_said_not_guessed
:status: ruled
:forced: no
:follows_from: RAT-one_zone_can_be_checked, RAT-nested_place_same_timezone
:justifies: RUL-country_gives_its_timezone, RUL-country_chosen_once

A zone passed down from a country of several is false for most of what lies inside it, and where the photos record no
offset of their own nothing shows it. The zone database knows which countries those are; it cannot know which country
a folder is in — a name is spelt as its owner spells it, in any language, and some names are two places. So the user
says it, once, by picking the country from the database's own list — of the folder that is the country, or of a city
or a park with no folder for its country above it; being in the country is all that needs saying. The tool does what
follows: a country of one timezone gives it to that folder and everything inside, as an answered zone would; a
country of several gives none, lets none through from above, and holds every zone written there to its own. What lies
inside a folder is in that folder's country, so a country said again inside is a slip or a tree laid out by something
other than place: it is taken out, aloud, rather than left to contradict the one above — the by-destination tree is
one of places, and this is the one place the tool can hold it to that.
:::

:::{rat} The clock is the camera's for the day, not the folder's
:id: RAT-clock_is_the_cameras_for_the_day
:status: ruled
:forced: yes
:follows_from: RAT-offset_per_day_and_place
:justifies: RUL-offset_shared_within_day, RUL-same_day_offsets_agree

A camera has one clock. Sorting a day's photos into a museum and a castle does not give it two: what its own positions
show of its clock in the morning is the best evidence there is for the afternoon, far better than assuming it kept the
local hour. So a destination with no position of its own that day is offered the offset found elsewhere that day —
applied by itself only where it was sure enough to apply itself there. And where the camera's positions give two
offsets for one day that cannot both be right, one of them rests on a wrong match; neither is written until the user
says which. An offset the user wrote, or accepted on a guess, is not passed on: it is their word about one place, not
evidence. Another day's offset is never passed on either — clocks are set again overnight.
:::

:::{rat} One number, one question
:id: RAT-one_number_one_question
:status: ruled
:forced: no
:follows_from: RAT-assumptions_need_acceptance
:justifies: RUL-timezone_offset_asked_once

A timezone's offset is a guess that needs the user's word before it is written. Where tracks lie by the photos the
user gives that word at the check against the tracks, looking at where the offset puts a photo; asking them to accept
the same number first, in another file and another run, adds a question and no safety — the check is the stronger
act and names the offset itself. Where no track covers the photos there is no check, and acceptance is the word.
:::

:::{rat} An acceptance is of what was shown
:id: RAT-acceptance_is_of_what_was_shown
:status: ruled
:forced: yes
:follows_from: RAT-editor_writes_only_decisions, RAT-decision_withdrawable
:justifies: RUL-acceptance_holds_for_its_proposal, RUL-content_acceptance_is_of_that_content

A user accepts a proposal by looking at it: this offset, for this camera, on this evidence. Kept as a bare yes, the acceptance would pass to whatever is proposed next — an offset from another timezone once the zone above changes, one from GPS that two photos tie on — and a value the user never saw would take effect over their name. So the acceptance names what it accepted, and holds for that. A changed picture is accepted the same way: as the content that was reported, under the plan that reported it.
:::

:::{rat} An accepted fallback follows, where an accepted offset does not
:id: RAT-fallback_acceptance_follows
:status: ruled
:forced: no
:follows_from: RAT-assumptions_need_acceptance, RAT-acceptance_is_of_what_was_shown
:justifies: RUL-accepted_fallback_follows

Accepting an offset accepts a number, and holds only for that number. Accepting an inherited fallback is another kind
of answer: not "this coordinate" but "this folder is placed like the one above". A fallback is coarse by nature — one
point for every photo nothing better places — so a correction to the point above is as right for the folder that
follows it as for its own; and pinning the coordinate shown would make one edit high in the tree ask again at every
folder beneath, for no gain in precision. So the two acceptances differ, on purpose: the offset's is of a value, the
fallback's of a relation.
:::


## 7. Per-destination structure

:::{rat} A clock is wrong by its own amount, day by day
:id: RAT-offset_per_day_and_place
:status: ruled
:forced: yes
:follows_from: RAT-offset_per_camera_destination_day
:justifies: RUL-offset_per_camera_destination_day

A camera's clock drifts, and is set again — to local time, on a trip, often each morning. Its error is one amount for
one day's shooting and another the next, and destinations are where the user went, not when; one offset per camera, or
per destination over several days, would be wrong for every day but one. A day in one place is the unit within which
the error stays put, so it is the unit decided.
:::

:::{rat} One place's clock evidence says nothing of another's
:id: RAT-no_borrowed_offsets
:status: ruled
:forced: yes
:follows_from: RAT-offset_per_camera_destination_day, RAT-decisions_cascade
:justifies: RUL-offset_from_own_evidence

Folders nest by geography, which is why a timezone or a fallback position can pass down them; a clock's error does not
follow geography. A museum visited inside a city trip may be another day, the camera reset in between; a parent
folder's offset averaged from its children would be right for none of them. An offset borrowed would look measured
while it is not — so each is proposed from the camera's own positions that day, or from the timezone, and labelled as
such.
:::

:::{rat} A container is a place to put defaults
:id: RAT-container_holds_defaults
:status: ruled
:forced: yes
:follows_from: RAT-decisions_cascade, RAT-destination_tree_is_a_hierarchy
:justifies: RUL-container_never_waits

A folder holding only other destinations has no photo to correct: it exists so a timezone or a fallback position can be
set once and reach every destination beneath it. If it asked for anything, it would add work instead of saving it.
:::


## 8. Reading the tracks

:::{rat} A track is evidence only where it can be read
:id: RAT-track_points_read_exactly
:status: ruled
:forced: no
:follows_from: CHC-photos_matter, RAT-remainder_worklist
:justifies: RUL-track_time_never_guessed, RUL-unreadable_point_reported, RUL-unreadable_point_skipped

A track's points become positions and clock offsets; a time read an hour wrong, or in a zone guessed, would place
photos and correct cameras by that hour, and look like evidence. Recorders write the same instant in several valid
forms, so each is read as the instant it is; one stating no zone could be any of them and is not used. Skipping a
point silently would let a track whose every point was rejected pass for an empty one, and the user would never learn
why the photos it should have placed were not.
:::

:::{rat} A track is where one device was
:id: RAT-track_is_one_device
:status: ruled
:forced: yes
:follows_from: FCT-partial_track_coverage, CHC-photos_matter
:justifies: RUL-tracks_never_joined, RUL-disagreeing_tracks_place_nothing

Each track file is one device's record, and the tracks folder may hold several for the same hours: a phone and a logger in the same pocket, or a companion who spent the afternoon elsewhere. Read as one line through all the points in time order, two devices five kilometres apart become a zigzag between them, and a photo is placed at whichever was logged a second nearer — or halfway. Kept apart, two tracks that agree are one party and either serves; two that do not are a question only the user can answer, by taking out the track that is not theirs.
:::

:::{rat} Missing is not the same as none
:id: RAT-missing_tracks_are_not_no_tracks
:status: ruled
:forced: yes
:follows_from: RAT-folder_gps_fallback, RAT-decisions_reread_cache_only
:justifies: RUL-missing_tracks_stop_geotag, RUL-no_tracks_no_stop

A library with no tracks at all is a supported case: every decision falls to its other sources. A tracks folder that is named and not there is something else — a volume not mounted — and planning on as if there were none would place by folder fallback every photo the tracks place precisely, and drop the confirmations given against them. Nothing in the result would show it. Stopping costs one mount command.
:::

:::{rat} A break is where nothing is known
:id: RAT-break_is_unknown
:status: ruled
:forced: no
:follows_from: RAT-safe_at_each_change
:justifies: RUL-track_is_one_trk, RUL-track_break_never_bridged, RUL-unreadable_tracks_stop_geotag

A file can hold several devices' tracks, and joined they zig-zag between two people as surely as two files would. A break between segments is where the recorder was off: where the device was in between is not in the file, and a line drawn across it is invented. And a folder of tracks that cannot be read is not a trip without tracks — it is one whose tracks are about to be ignored.
:::


## 9. Camera groups

:::{rat} The class decides how a photo's time is found
:id: RAT-class_decides_time_model
:status: ruled
:forced: yes
:follows_from: RAT-camera_groups_generated, RAT-offset_per_camera_destination_day
:justifies: RUL-unknown_group_stops_geotag, RUL-unknown_group_classification_offered

A phone's clock is set by its network and its zone recorded or found per photo, so each photo is solved alone; a
camera's clock is set by hand, wrong by its own amount each day, so geotag finds one offset per destination and day.
Treat a camera as a phone and its error is never corrected; a phone as a camera and a correct clock is offset. Nothing
in a file's metadata tells them apart reliably, so geotag asks rather than guesses — and writes the classification
out, so only the judgement is the user's.
:::

:::{rat} No camera, no clock to correct
:id: RAT-no_identity_no_group
:status: ruled
:forced: yes
:follows_from: RAT-offset_per_camera_destination_day, RAT-minimal_cascading_asks
:justifies: RUL-unidentified_files_solved_alone

Screenshots, scans and photos a messaging app stripped name no camera, and share nothing but that. Taken for one camera,
they would be asked to be classed as one and, classed a camera, given one clock offset per destination and day — an
offset no camera of theirs had. Each carries what time it has; read alone, as a phone's photo is, by its own offset or
the place's zone, it asks nothing and borrows nothing.
:::


## 10. Destination civil timezone

:::{rat} The nearest place says the most
:id: RAT-nearest_timezone
:status: ruled
:forced: yes
:follows_from: RAT-decisions_cascade, RAT-destination_tree_is_a_hierarchy
:justifies: RUL-timezone_from_nearest

The destination a place lies in is the most specific word on its timezone: Kyoto inside Japan is in Japan's zone. The
configured default is the user's usual zone, true of no trip in particular, so it is offered only where the tree says
nothing. And a zone the user sets on a trip's folder should hold for everything beneath it — one answer for the trip,
not one per folder.
:::

:::{rat} The home zone is right for no trip in particular
:id: RAT-home_zone_offered
:status: ruled
:forced: yes
:follows_from: RAT-assumptions_need_acceptance
:justifies: RUL-default_zone_proposed_only

The configured default is the zone the user usually lives in, and a trip is where they went. Applied by itself to a
trip abroad, it would name every photo in home time and turn the times of photos that record no offset by the hours
between the two zones — written into the originals, with no sign anything is off. Offered instead, it costs one answer
per trip, at the trip's folder, everything beneath inheriting it; a trip at home takes it in one click.
:::

:::{rat} The destination is an input to the time
:id: RAT-destination_is_an_input
:status: ruled
:forced: yes
:follows_from: RAT-offset_per_camera_destination_day, RAT-decisions_cascade
:justifies: RUL-moved_photo_decided_anew

A photo's true time and its name come from its destination's timezone and from the clock offset found for its camera
there. A photo is moved to fix a mis-sort; carrying its old destination's answers with it would keep the mistake in
its time and its name, now hidden under the right folder.
:::


## 11. Clock offsets from the camera's own GPS

:::{rat} The same place on another trip is not evidence
:id: RAT-clock_error_window
:status: ruled
:forced: yes
:follows_from: RAT-offset_per_camera_destination_day
:justifies: RUL-anchor_within_clock_error

A track is matched to a photo by place, and places are revisited: the spot a photo was taken may lie on a track from
years before. Closest by distance, that track would "correct" the camera by years. A camera's clock is wrong by its
zone and its drift — hours, not years — so only track times that close to the camera's own count. The window cannot
be the destination's zone: the camera may have been left on home time, and that is exactly what the offset corrects.
:::

:::{rat} Agreement is the evidence
:id: RAT-anchor_agreement
:status: ruled
:forced: yes
:follows_from: RAT-offset_per_camera_destination_day, RAT-minimal_cascading_asks
:justifies: RUL-anchor_consensus

A camera's clock is wrong by the same amount all day, so every photo it took with a position agrees on the offset —
and the offset is what they agree on. One photo's closest match can be a coincidence: the same walk on the day before,
a hotel passed morning and evening. Counting every pass by each photo's place, the true offset is the one every photo
supports, a coincidence the one only some do. An average of disagreeing offsets is supported by no photo at all. When
nothing tells two offsets apart, the photos do not say which is right, and the user must.
:::

:::{rat} A trip comes back to its places
:id: RAT-trips_revisit
:status: ruled
:forced: yes
:follows_from: RAT-anchor_agreement, RAT-minimal_cascading_asks
:justifies: RUL-revisit_matched_to_its_day, RUL-indistinct_visits_wait

A trip often comes back to its places: a town visited from the same hotel day after day, a square crossed morning and
evening, with a track for every one. Any of those visits passes where a photo was taken, and which passed closest is
chance. Matched to the wrong visit, a whole day's photos are corrected by a day, or by hours — written into the
originals, named by the wrong time, placed on the wrong walk — with no sign anything is off. When the photos cannot
say which visit is theirs, only the user, who remembers the day, can.
:::

:::{rat} The evidence is the same whichever offset the user takes
:id: RAT-chosen_offset_has_evidence
:status: ruled
:forced: yes
:follows_from: RAT-anchor_agreement, RAT-minimal_cascading_asks
:justifies: RUL-chosen_group_is_anchored

Where the photos support several offsets, the user picks the one for the day they were there. That offset is backed
by the camera's own positions on the tracks as much as the recommended one; checking it against the tracks again
would ask the user to confirm on a map what those photos already show — work added to the one case that already
needed them.
:::

:::{rat} A place only tells the time while the track is moving
:id: RAT-stay_tells_no_time
:status: ruled
:forced: yes
:follows_from: FCT-clocks_drift, RAT-clustering_details
:justifies: RUL-stay_fixes_no_clock

An anchor reads the time off the track where the photo's own position lies on it. That works while the track moves: it passes the place once, at one moment. Where it stood still — a museum, a lunch, a viewpoint — every minute of the stay is at that place, and the nearest point is whichever the receiver's jitter happened to put closest. Two photos taken there agree with each other perfectly and say nothing: the offset they yield can be wrong by the length of the stay, and would then slide every untagged photo of the day along the track by as much. Such evidence narrows the offset without fixing it, so it is offered, checked against the track, and never applied by itself.
:::

:::{rat} A kept offset is only as good as what it stood on
:id: RAT-kept_offset_needs_its_evidence
:status: ruled
:forced: yes
:follows_from: RAT-day_offset_is_the_cameras, RAT-decision_withdrawable
:justifies: RUL-kept_offset_rests_on_its_tracks

The offset is kept because it was read from the camera's own GPS against the tracks, and the photos that gave it can no longer give it again. But the user takes a track out of the folder for one reason — it was someone else's — and an offset read against it goes with it; and a photo arriving later with its own position is new evidence about the same clock. Kept past either, the offset would be the one decision in the record nobody could withdraw and nothing still supported.
:::


## 13. Resolved UTC

:::{rat} A phone says its own offset
:id: RAT-phone_records_its_offset
:status: ruled
:forced: yes
:follows_from: RAT-class_decides_time_model
:justifies: RUL-phone_time_from_own_offset

A phone's clock is set by its network and it records the offset it was at, beside each time it writes: better
evidence than any zone geotag could assume. But a photo holds several times, each with its offset — when it was
taken, digitized, modified — and an offset describes only the time it was written with; another would be right only by
chance. Where the photo records none for its time, the destination's zone is the best guess left.
:::

:::{rat} Two readings, and nothing to choose by
:id: RAT-two_readings_no_guess
:status: ruled
:forced: no
:follows_from: RAT-safe_at_each_change
:justifies: RUL-ambiguous_local_time_never_guessed

A local time that happened twice, or never, has two readings an hour apart, and the photo says nothing of which. Either is written into the original as its time and decides where on the track it falls. A guess here is wrong half the time and looks exactly like a right answer.
:::


## 14. The GPS-drift check

:::{rat} A wrong offset moves a whole day along the track
:id: RAT-drift_invisible
:status: ruled
:forced: yes
:follows_from: RAT-position_follows_time, CHC-photos_matter
:justifies: RUL-unanchored_offset_confirmed

A photo with no position of its own is placed where the track was at its resolved time. With an offset the camera's
GPS measured, that time is evidence; with one assumed from the timezone or written by hand, nothing has checked it.
Wrong by an hour, it slides the whole day's photos an hour along the track — each to a real place on the route, so
none looks wrong — and writes those places into the originals. Seeing a photo against the track at its time is the
check; leaving it unseen must never pass for having seen it.
:::

:::{rat} What was seen was one offset
:id: RAT-confirmed_one_offset
:status: ruled
:forced: yes
:follows_from: RAT-drift_invisible
:justifies: RUL-confirmation_holds_for_its_offset

Confirming is looking at the photos on the track at the times one offset gives. Another offset puts them elsewhere,
and that has not been looked at: carried over, the confirmation would pass an offset nobody checked, or let a
correction found for the old one override the user's new decision.
:::


## 15. Every photo's own values

:::{rat} A new decoder does not make a new photo
:id: RAT-same_photo_new_fingerprint
:status: ruled
:forced: yes
:follows_from: RAT-decision_withdrawable, RAT-decoded_pixel_identity
:justifies: RUL-own_values_follow_new_fingerprint

A new ImageMagick may decode a photo to a new fingerprint; the photo is the same, and so are its own time and
position. Lost with the old value, they would leave geotag taking the photo's corrected time for its own: a changed
offset would never reach it, a withdrawn one never undo. Prep's log says which old value became which new one; where
it does not say so one for one, no photo's values can be told apart, and geotag stops rather than guess.
:::


## 16. Placing each photo

:::{rat} The camera measured where it was
:id: RAT-own_position_best
:status: ruled
:forced: yes
:follows_from: RAT-total_coverage_cascade, CHC-photos_matter
:justifies: RUL-own_position_kept

A position the camera wrote was measured where the photo was taken. Everything geotag can offer instead is derived —
from a track and a corrected time, from a folder — and so weaker evidence: replacing the measurement with it would make
the photo less right, not more.
:::

:::{rat} Most specific first
:id: RAT-placement_most_specific_first
:status: ruled
:forced: yes
:follows_from: RAT-track_squeezed, RAT-folder_gps_fallback, RAT-remainder_worklist
:justifies: RUL-placement_order

Each source speaks for fewer photos than the one after it: a position the user set speaks for that photo alone, a track
for the instant it was taken, a fallback for a whole folder. The first that applies is the most specific word on where
the photo was; a photo none of them places is one only the user can answer for — with a place, or by leaving it
unlocated.
:::

:::{rat} A place inside a place is near it
:id: RAT-fallback_nested
:status: ruled
:forced: yes
:follows_from: RAT-folder_gps_fallback, RAT-assumptions_need_acceptance
:justifies: RUL-fallback_from_nearest

A destination inside another lies within it, so the place set for the outer one is a fair guess for the inner one —
and the nearer the ancestor, the fairer. It is only a guess, so it waits for the user's acceptance; once accepted, the
user has chosen to inherit, and a fallback changed above flows down to it, as a timezone does.
:::

:::{rat} A fallback is a convenience, not a gate
:id: RAT-fallback_optional
:status: ruled
:forced: yes
:follows_from: RAT-folder_gps_fallback, RAT-minimal_cascading_asks
:justifies: RUL-fallback_optional

The fallback saves answering, photo by photo, for a folder the tracks miss. A destination whose photos the tracks all
place needs none, and one that does can still be answered photo by photo; to make every destination ask for one would
add the work it exists to save.
:::

:::{rat} A projection is the roughest reading, so it is the most bounded
:id: RAT-projection_bounded
:status: ruled
:forced: yes
:follows_from: RAT-track_squeezed, RAT-coordinate_carries_its_method
:justifies: RUL-track_placement_bounded, RUL-track_evidence_order

Squeezing the track means using it wherever it says something: at a point, between two, and a little past where a recording stops — each track's own stop, since a logger switched off at the car is an end whatever was recorded the month after. Past an end there is only a heading, and a heading read off the last two points is mostly receiver jitter: twenty metres in one second, carried five minutes, is six kilometres. So the heading is read over the track's last stretch, and a projection that still lands farther or faster than the configuration lets one go is dropped for the end itself — rough, marked as such, and wrong by no more than the user allowed.
:::

:::{rat} The remainder is a worklist only if it says why
:id: RAT-remainder_says_why
:status: ruled
:forced: no
:follows_from: RAT-remainder_worklist, CHC-ask_only_what_data_cannot_settle
:justifies: RUL-unplaced_photo_listed, RUL-plan_counts_placement

A photo the tracks did not place is one of a few cases with different cures: taken an hour after the logger stopped, taken across a gap the configuration will not bridge, or caught between two tracks that disagree. Listed bare, each sends the user to the map to work out which. Listed with the reason and the distance, most are settled at a glance — and the count of how every photo was placed is the one number that says whether the run did what the tool is for.
:::

:::{rat} A decision belongs to the photo, not to its name
:id: RAT-decision_keyed_by_identity
:status: ruled
:forced: yes
:follows_from: RAT-decoded_pixel_identity, RAT-decisions_reread_cache_only
:justifies: RUL-photo_decision_follows_the_photo, RUL-answer_follows_its_day

Geotag's last act on a photo is to rename it, and a destination's cells are named by day once it holds two. A decision found again only by the name it was filed under is lost to geotag's own work: the position set by hand asks again after the rename, the first day's offset after the second day's photos arrive. What the user decided about is the photo, and the camera's day — so that is what the decision is found by.
:::

:::{rat} The method travels with the photo
:id: RAT-method_in_the_photo
:status: ruled
:forced: yes
:follows_from: RAT-coordinate_carries_its_method
:justifies: RUL-position_carries_its_method, RUL-placement_recorded_with_its_track

Completeness is bought with precision that varies: one photo sits on a track point, the next was projected five minutes past a track's end, a third shares its folder's one coordinate. In the library, years on, only the photo is there to say which — so the method is written into it — and the workspace's record adds what the photo cannot hold: which track, at what instant.
:::


## 17. The corrected time

:::{rat} The time a person would have read on the wall
:id: RAT-time_written_as_lived
:status: ruled
:forced: no
:follows_from: CHC-local_folder_library, RAT-offset_per_camera_destination_day
:justifies: RUL-corrected_time_written_local

Once a photo's true instant is known it could be written as UTC, as the camera's home time, or as the time where it was taken. A library is browsed by people: the morning market should read as morning. Written as the destination's local time with its offset beside it, the photo both reads as it was lived and still states its exact instant.
:::


## 19. The executable plan

:::{rat} Half a position is a wrong one
:id: RAT-position_whole
:status: ruled
:forced: yes
:follows_from: CHC-photos_matter
:justifies: RUL-position_written_whole

EXIF stores a latitude and a longitude without their signs: the hemisphere is in a field of its own. A coordinate
written without it is read as no location at all, or put north and east of where it was — a photo from Sydney placed
in the Pacific off Japan. Left behind when the coordinate is cleared, the reference is half a position that some
reader will complete. Whole or not at all is the only safe write.
:::

:::{rat} The offset is the camera's that day, not the photos'
:id: RAT-day_offset_is_the_cameras
:status: ruled
:forced: yes
:follows_from: RAT-offset_per_camera_destination_day, RAT-decisions_reread_cache_only
:justifies: RUL-day_offset_kept_for_later_photos

A clock offset belongs to the camera on that day; every photo it took that day shares it, however many arrive later.
Once the photos that gave it are corrected, they no longer anchor anything — dropping the offset then would ask again a
question already settled, or leave the later photos an offset nobody checked.
:::


## 20. Execution

:::{rat} A crash leaves work, not damage
:id: RAT-execution_resumable
:status: ruled
:forced: yes
:follows_from: RAT-discrete_stages, RAT-idempotent_reruns
:justifies: RUL-geotag_execution_resumable

Execution writes into hundreds of originals one after another, and anything can stop it partway. Run again, it must
know what is done and do only the rest — writing nothing twice, choosing no other name — or a crash would leave a
day half corrected or corrected twice. And what it finds changed since the plan may be its own interrupted write or
the user's edit: only the first is its to finish.
:::

:::{rat} Metadata never moves a pixel
:id: RAT-content_changed_held
:status: ruled
:forced: yes
:follows_from: RAT-decoded_pixel_identity, CHC-photos_matter
:justifies: RUL-content_changed_write_held

Writing a time or a position changes a photo's metadata and nothing it shows; its fingerprint, taken over the decoded
picture, holds through it — which is why every phase can follow a photo by it. A write after which the picture
differs is something wrong — a tool, a format — that the user must see, not something to record as done; and the
photo's identity is at stake, so only the user can take the new content for it.
:::

:::{rat} The record must cover what a broken run did
:id: RAT-record_covers_broken_runs
:status: ruled
:forced: yes
:follows_from: RAT-recoverable_core, RAT-consolidated_log
:justifies: RUL-one_photo_failure_contained, RUL-applied_unrecorded_is_recorded, RUL-engine_checked_before_writes

The journal is what later says which run changed which photo. A run that falls over on one photo while others are in flight, or is killed between a write and its record, leaves photos changed and unrecorded; a next run that merely finds them done and moves on leaves them so for good, and the log built from the journals then shows a photo holding a position no pass ever gave it. So one photo's failure stays its own, and what is found done is checked and written down. The image engine is checked first for the same reason: with another one every write would be made and then held as changed, a whole plan of photos half applied.
:::


## 21. Finalize

:::{rat} The package records what was done
:id: RAT-package_records_what_was_done
:status: ruled
:forced: yes
:follows_from: RAT-consolidated_log, RAT-record_outlives_workspace
:justifies: RUL-finalize_requires_success

The archival package is what outlives the workspace: the account of what geotag did to each photo and why. Made
from an execution that did not finish, it would record changes the photos lack; made after a decision was edited
and not executed, it would record a decision they never received. Either way the record would lie about the
library.
:::

:::{rat} Finalize is where geotag signs for the photos
:id: RAT-finalize_signs_for_the_photos
:status: ruled
:forced: yes
:follows_from: RAT-safety_not_on_the_plan, CHC-photos_matter
:justifies: RUL-finalize_checks_photos, RUL-finalize_reports_placement, RUL-unlocated_logged

Merge refuses a photo changed since finalize, on the strength of what finalize recorded. If finalize records whatever it finds, an edit made between execute and finalize becomes the baseline, and the library receives a photo the log describes as something else. Finalize is given once the user judges the work done, so it is also where they are told how done: how many photos have a position and by what means, how many were left without one — each of those by their own recorded answer.
:::
