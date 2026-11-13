# Geotag — why

**Not normative.** Each item here is the reasoning behind the [intent](../intent/geotag.md) or [build](../build/geotag.md)
items it `justifies`, under the same section numbers. Where the two differ, the intent wins and this is stale.
Sections are numbered as in the phase's original spec; a section whose content lives in the shared contract, or
that only restated others, has no heading here.

## 2. Core workflow rule

:::{rat} A position is looked up by time
:id: RAT-position_follows_time
:status: ruled
:justifies: RUL-time_before_gps

A photo with no position of its own is placed where the track was at the moment it was taken — its true time, after
the camera's clock is corrected. Placed before that time is settled, it would be placed at the wrong moment of the
track, possibly kilometres off, and every position would have to be planned again once the time changed. So the time
is settled for every photo first, and only then is any position planned.
:::

:::{rat} No phase invents a time
:id: RAT-no_phase_invents_time
:status: ruled
:justifies: RUL-untimed_photo_stops_geotag

A photo with no recorded time has nothing to correct and nothing to look up: its true time is unknown, and no
camera's offset or destination's timezone can supply one. Prep sets such a photo aside in missing metadata for the
user to deal with by hand. Sorted into a destination anyway, it would pass through geotag's decisions with nothing to
ask about it and stop only at the last plan, where nothing the user could decide would clear it. Stopping at the start,
naming it and where it belongs, makes the one possible fix plain.
:::

## 5. Linear dependency inclusion

:::{rat} A chain is only as fresh as its weakest link
:id: RAT-no_chain_of_vouching
:status: ruled
:justifies: RUL-geotag_plan_carries_every_dependency

The decision records are files the user edits between runs, in the editor or by hand. If the plan named only the last
of them and trusted it to name the rest, a change upstream of it — a track added, an earlier record edited after the
later one was written — would pass unseen whenever the later record happened not to be rewritten. Carried in the plan
itself, every input is checked against what it is now, at the one moment that matters: just before anything changes.
:::

## 7. Geotag scope

:::{rat} Only what the user sorted is ready
:id: RAT-only_sorted_is_ready
:status: ruled
:justifies: RUL-geotag_changes_only_by_dest

A photo's destination is what geotag corrects it by: the timezone of the place, the offset of that camera on that
day, the fallback position of the folder. A photo not yet sorted has none of these, and a file in the other folders is
not a photo to place — a stray, one missing metadata, a JPEG set aside beside its RAW. Videos stay where prep put them:
the pipeline does not place them, and a tag written into one would be a guess. Sorting a photo into a destination is
the user's statement that it is ready.
:::

## 8. JSON artifact rule

:::{rat} A missing record should mean one thing
:id: RAT-record_means_stage_reached
:status: ruled
:justifies: RUL-decision_stage_writes_record, RUL-no_record_before_decisions

The decision records are what the user, the editor and the next stage read. Written at every stage reached — even
when it holds nothing to decide — a record's presence says the stage ran and its status says what is left; its absence
can only mean the stage was not reached. Were an all-automatic stage to write nothing, an absent record would mean either
"nothing to decide" or "never got here", and a record written by a run that stopped at a gate would look like a
decision to act on when there was none.
:::

## 9. Human decision field rule

:::{rat} The camera's own GPS is evidence; the user decides how much
:id: RAT-anchor_evidence_trusted_as_configured
:status: ruled
:justifies: RUL-anchor_offset_auto_as_configured

An offset measured from the camera's own positions against the tracks is evidence, not a guess: several frames agreeing
on it is hard to get by accident; one frame could be a coincidence of a slow walk. How much of that to accept without a
look is the user's choice, made once in the configuration rather than asked for every camera on every day. Anchors that
disagree mean something is off — a clock reset in the day, a wrong track — and no setting should paper over that.
:::

:::{rat} A nested place is in its parent's timezone
:id: RAT-nested_place_same_timezone
:status: ruled
:justifies: RUL-timezone_auto_resolves

Destinations nest geographically — a city in a country, a museum in a city — so one inside a destination of known
timezone can scarcely lie in another. Asking the user to confirm it for every folder would be asking what the tree
already says. Where the tree says nothing — no ancestor and no default — there is nothing to propose, and the user must
answer.
:::

:::{rat} An assumption is the user's to accept
:id: RAT-assumptions_need_acceptance
:status: ruled
:justifies: RUL-other_proposals_need_acceptance

An offset derived from the timezone assumes the camera was set to local time that day; a fallback inherited from a
parent folder assumes the photos were taken near the parent's point. Both are often right and sometimes badly wrong,
and nothing in the photos can tell which. Applied silently, a wrong one would place a whole day of photos in the wrong
place or the wrong hour, written into the originals; offered for acceptance, it costs one confirmation.
:::

## 10. Per-destination structure

:::{rat} A clock is wrong by its own amount, day by day
:id: RAT-offset_per_day_and_place
:status: ruled
:justifies: RUL-offset_per_camera_destination_day

A camera's clock drifts, and is set again — to local time, on a trip, often each morning. Its error is one amount for
one day's shooting and another the next, and destinations are where the user went, not when; one offset per camera, or
per destination over several days, would be wrong for every day but one. A day in one place is the unit within which
the error stays put, so it is the unit decided.
:::

:::{rat} One place's clock evidence says nothing of another's
:id: RAT-no_borrowed_offsets
:status: ruled
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
:justifies: RUL-container_never_waits

A folder holding only other destinations has no photo to correct: it exists so a timezone or a fallback position can be
set once and reach every destination beneath it. If it asked for anything, it would add work instead of saving it.
:::


## 15. Reading the tracks

:::{rat} A track is evidence only where it can be read
:id: RAT-track_points_read_exactly
:status: seed
:justifies: RUL-track_time_never_guessed, RUL-unreadable_point_reported

A track's points become positions and clock offsets; a time read an hour wrong, or in a zone guessed, would place
photos and correct cameras by that hour, and look like evidence. Recorders write the same instant in several valid
forms, so each is read as the instant it is; one stating no zone could be any of them and is not used. Skipping a
point silently would let a track whose every point was rejected pass for an empty one, and the user would never learn
why the photos it should have placed were not.
:::
