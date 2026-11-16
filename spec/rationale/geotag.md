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
:justifies: RUL-untimed_photo_stops_geotag, RUL-untimed_photo_named

A photo with no recorded time has nothing to correct and nothing to look up: its true time is unknown, and no
camera's offset or destination's timezone can supply one. Prep sets such a photo aside in missing metadata for the
user to deal with by hand. Sorted into a destination anyway, it would pass through geotag's decisions with nothing to
ask about it and stop only at the last plan, where nothing the user could decide would clear it. Stopping before any
time is resolved, naming it and the two ways out, makes the fix plain.

Letting such a photo through untimed, placed by hand or by its folder's fallback and left unrenamed, and giving it a
time by a decision for that photo alone, were weighed and set aside: the stop was ruled kept (2026-11-16). The one time
the user can give it is a date for its folder ({need}`RAT-date_fallback_for_scans`) — the user's word, never the
tool's guess; a photo no such date covers stops as before. The stop comes once the time decisions are written, not
before, so that the date can be asked there, in the editor or by hand, like any other question of time.
:::

:::{rat} A folder says when its scans were made
:id: RAT-date_fallback_for_scans
:status: ruled
:forced: no
:follows_from: RAT-folder_gps_fallback, RAT-untimed_set_apart, RAT-no_phase_invents_time
:justifies: RUL-date_fallback_from_nearest, RUL-date_fallback_times_untimed, RUL-date_fallback_fills_to_a_day, RUL-date_fallback_time_written, RUL-date_fallback_names_in_scanner_order, RUL-date_fallback_applies_itself

A scanned print records no time: the scanner's clock says when it was scanned, if anything, never when it was taken.
What does say it is the folder the user sorts it into — "1985", "Christmas 1985" — better than any one photo can. The
owner, first: *"later on I am thinking I might consider setting a date fallback per destination just like I have a
location fallback ... the idea would work for scanned photos"*; and, ruling it (2026-11-16): *"date could be any of Y,
YM, YMD, with missing parts filled as 1; same cascade; what gets written is (a); scanner order ok"*.

So a date is a year, a month or a day, as much as the user knows, its missing parts the first; it passes down the
folders as the position fallback does, the nearest one given covering a photo, and since only the user gives it, it
takes effect without being accepted again below. EXIF has no way to say a time is approximate, so what is written is
the filled day's midnight, as the photo's time, in its destination's local time: the photo then sorts, names and shows
in the library by that day, and the date as the user gave it is kept in geotag's record. Photos of one such date share
one timestamp, so their suffixes follow the only order left, the one they came in from the scanner: the order of their
names.
:::

:::{rat} A filled time is not when the photo was taken
:id: RAT-filled_time_not_when_taken
:status: ruled
:forced: yes
:follows_from: RAT-date_fallback_for_scans, RAT-position_follows_time
:justifies: RUL-date_fallback_only_untimed, RUL-date_fallback_never_placed_by_tracks, RUL-date_fallback_no_clock_evidence, RUL-date_fallback_recorded

The time a date fallback gives is midnight on a day that stands for a year, a month or a day: a filing, not a moment.
A track places a photo where its wearer was at the photo's instant, so placed by this time a scan would land wherever
someone walked that midnight — a precise answer to a question nobody asked. Its position comes from what does know
it: the photo's own GPS, a position set for it, or its folder's fallback; with none it waits, as any unplaced photo
does. For the same reason it is no evidence of a camera's clock, and a photo with a time of its own keeps it: a real
reading is never traded for a filing. Since the written time looks like any other, the record keeps that it came from
the date fallback, and the date as given, so a "1985-01-01" can be told from a photo taken that night.
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

:::{rat} A pair keeps one name
:id: RAT-pair_keeps_one_name
:status: ruled
:forced: no
:follows_from: RAT-redundant_named_like_its_raw, RAT-only_sorted_is_ready
:justifies: RUL-set_aside_jpeg_renamed_with_raw, RUL-set_aside_jpeg_only_renamed, RUL-set_aside_jpeg_named_as_raw, RUL-set_aside_jpeg_catches_up

A JPEG set aside beside its RAW is the same shot, named like it so that the two names show it. Once geotag corrects the
RAW's name, a JPEG left under the camera's time names another moment — eight hours away, for a camera left on home
time — and the pair no longer shows. Prep knows the pair when it sets the JPEG aside, so it records it, and the rename
rests on that record, never on a likeness of names, which a suffix given to one and not the other already breaks. A
rename is all: the JPEG is a copy nobody uses, no time or position is decided for it, and a tag written into it would be
a guess. Renamed so, its name is its RAW's and no longer its own recorded time, and prep takes it as given. A run that
renames the RAW and not its JPEG — the JPEG changed on disk, or its rename not reached — leaves the pair apart, and no
later run renames that RAW again; so the JPEG catches up with the name the RAW holds, or it stays apart for good.
:::

:::{rat} A video has no zone to correct its name by
:id: RAT-video_name_uncorrected
:status: ruled
:forced: no
:follows_from: RAT-only_sorted_is_ready
:justifies: RUL-video_name_stays_uncorrected

A name is corrected to its destination's local time, and a video has no destination: videos are not sorted into
destinations, so there is no zone to read a corrected time in. A zone guessed from the photos of the camera's day goes
wrong on a day spread over two destinations of different zones — the video would be named in the wrong one, under a
name that looks corrected. Its camera's time, uncorrected, is at least what it says it is. Placing videos in
destinations, and then correcting their names, is another piece of work.
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


:::{rat} A field read another way is another reading
:id: RAT-fields_read_one_way
:status: ruled
:forced: yes
:follows_from: RAT-no_chain_of_vouching
:justifies: RUL-handoff_fields_of_this_build

Geotag decides from the fields prep read out of each photo — its times and their offsets, its position, its camera.
A version of cartographer that reads them otherwise — another field kept, another group preferred — may give the same
photo another time to correct or another offset to read it by. Planned from a reading the running version would not
make, the corrections would rest on values neither version would now take for the photo's; prep reads the photos again
first, and the plan then rests on one reading throughout.
:::

## 5. JSON artifact rule

:::{rat} A missing record should mean one thing
:id: RAT-record_means_stage_reached
:status: ruled
:forced: no
:follows_from: RAT-plain_json_record
:justifies: RUL-decision_stage_writes_record, RUL-no_record_before_decisions, RUL-early_stop_said_in_output

The decision records are what the user, the editor and the next stage read. Written at every stage reached — even when
it holds nothing to decide — a record's presence says the stage ran and its status says what is left; its absence can
only mean the stage was not reached. Were an all-automatic stage to write nothing, an absent record would mean either
"nothing to decide" or "never got here", and a record written by a run that stopped at a gate would look like a decision
to act on when there was none. With no record written, the run's output is the one place left to say what stopped it.
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
:justifies: RUL-proposals_need_acceptance, RUL-no_plan_while_a_decision_waits

An offset derived from the timezone assumes the camera was set to local time that day; one read from the offset the
photos record assumes the camera recorded its own. Either is often right and sometimes badly wrong, and nothing in the
photos can tell which. Applied silently, a wrong one would shift a whole day of photos by the hour — and with them every
position the tracks give them — written into the originals with all the look of a measurement; offered for acceptance,
it costs one confirmation. A fallback inherited from the folder above is an assumption too, of another weight, and is
not asked ({need}`RAT-fallback_nested`).
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

:::{rat} The photos say which of the country's zones
:id: RAT-zone_from_photos_in_country
:status: ruled
:forced: no
:follows_from: RAT-country_said_not_guessed, RAT-photos_outrank_inheritance, CHC-ask_only_what_data_cannot_settle
:justifies: RUL-zone_from_photos_in_country, RUL-zone_from_photos_applies

A country of several zones narrows the answer to a handful, and a phone's photo records the offset it was taken at.
Where exactly one of the country's zones had that offset at every such photo's time, the photos and the user's own
word on the country together settle it: asking would be asking what the data already says. It is the same evidence
that stops an inherited zone, read the other way — so it applies itself, as an inherited zone does, and passes down
as any zone in effect does. Where several zones fit (zones that share their offsets), or none, or no photo records an
offset, nothing tells them apart, and the destination asks. Positions would say more, but only through a database of
zone boundaries, a dependency the tool does not carry; the offsets need only the zone database it already reads.
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
offset of their own nothing shows it. The zone database knows which countries those are; it cannot know which country a
folder is in — a name is spelt as its owner spells it, in any language, and some names are two places. So the user says
it, once, by picking the country from the database's own list — of the folder that is the country, or of a city or a
park with no folder for its country above it; being in the country is all that needs saying. The tool does what follows:
a country of one timezone gives it to that folder and everything inside, as an answered zone would; a country of several
gives none, lets none through from above, and holds every zone written there to its own. What lies inside a folder is in
that folder's country, so a country said again inside is a slip or a tree laid out by something other than place: it is
taken out, aloud, rather than left to contradict the one above — the by-destination tree is one of places, and this is
the one place the tool can hold it to that. It is also the one place the tool takes back what the user wrote: the folder
now lies inside the other country, so the country said above it is the right one, and the value inside can only repeat
it or contradict it.
:::

:::{rat} The table of countries is found wherever the host lacks one, and fetched only when the user says so
:id: RAT-zone_table_where_host_lacks
:status: ruled
:forced: no
:follows_from: RAT-country_said_not_guessed, RAT-tracks_kept_with_workspace
:justifies: RUL-zone_table_host_first, RUL-zone_table_zone_known, RUL-zone_table_download_on_word, RUL-zone_table_download_where_missing, RUL-zone_table_refusal_told, RUL-zone_table_asked_once, RUL-unreadable_zone_table_record_stops, RUL-zone_table_downloaded_once, RUL-zone_table_copy_kept, RUL-zone_table_never_stops_prep, RUL-zone_table_checked, RUL-zone_table_failure_told, RUL-zone_table_request_bare, RUL-zone_table_restales_plan

A country is picked from the zone database's own list, and some hosts' zone databases ship without it: there the
choice of a country would be refused. The owner asked: *"can we use OS one if available and some sort of master copy
from web if not, and a bundled version if master copy on web is not available?"* — then ruled: *"build including
download but get permission from user before downloading - this should be during the workspace init. And tell the user
that if he refuses it will use a potentially stale bundled copy"*. The host's own table comes first: it is the one its
zones are read from, and where it has one nothing is asked. Fetching is new for this tool, which otherwise never
reaches the network, so it is done only on the user's word, asked once when the workspace is made, carrying nothing
of the workspace or its user; the answer is kept so the question is not asked again, and the table fetched is kept
with the records — a choice of country rests on it, and a sealed workspace must show what it rested on, as it does the
track points. A kept answer that cannot be read is not no answer: taken for none, the question would come back, the
answer would be written over, and the table in use would change with no one told why — so the run stops on it, named,
as on the other records the workspace keeps. A table fetched is only taken whole and well formed; a failed fetch, a refusal or no one there to answer
leaves the carried copy in use, said aloud, for the question matters only to a choice of country and must never stop
prep. A zone the host cannot read is no country's, whichever table names it. And a choice made from one table may be
wrong by another, so the plan names the table it was made from: another one makes it stale, as a changed decision
does.
:::

:::{rat} A camera that records its offset says which zone its clock was on
:id: RAT-camera_records_its_clock_zone
:status: ruled
:forced: no
:follows_from: RAT-assumptions_need_acceptance, RAT-no_borrowed_offsets
:justifies: RUL-recorded_offset_proposed, RUL-differing_recorded_offsets_propose_none

A recent camera writes, with each time, the UTC offset its clock was set to. That is the clock offset but for the
clock's own error; the destination's zone is only an assumption that the camera was set to local time. A body left on
home time in Japan records +01:00 and is eight hours from the zone's guess, offered as the answer to accept. So the
recorded offset is proposed before the zone. It states a setting, not a measurement — a clock set to the wrong hour
in its right zone records the zone and is still wrong — so it is a proposal like the zone's, accepted or checked
against the tracks the same way, and the camera's own positions, which measure the clock, come before it. Photos of
one day recording two offsets say the setting was changed that day, or that the tag is not to be trusted; which is the
day's is a guess, so neither is proposed, and the offsets are shown for the user to answer.
:::

:::{rat} A guess that leaves the photos where nothing else was is no reading of the clock
:id: RAT-reset_clock_not_accepted
:status: ruled
:forced: no
:follows_from: RAT-assumptions_need_acceptance, CHC-photos_matter
:justifies: RUL-offset_far_from_evidence_asks

A camera whose battery ran out wakes at its factory date, years from the trip. Nothing of its own can anchor it, and
the zone's guess, or the offset it records, moves it a few hours: one acceptance — a click meant to say "the camera
kept local time" — would write that year into the originals as corrected. What the guess cannot see, the
destination's other photos can: a phone, or another camera whose offset is settled, says when the destination was
visited, and the tracks say when the user was out. An offset leaving every photo of a day farther from all of them
than any clock is allowed to be wrong is not a reading of that clock, and accepting it is not an answer; the user is
asked for the offset itself, which the true time of one photo gives. Where no other device's photo is there, nothing
tells a reset clock from a trip with no tracks, and asking every such day would cost an answer the user cannot
improve on; the guess is offered as before. The tracks alone are not that evidence: under a library's worth of them,
a trip with none of its own would be far from all of them too.
:::

:::{rat} One number, one question
:id: RAT-one_number_one_question
:status: ruled
:forced: no
:follows_from: RAT-assumptions_need_acceptance
:justifies: RUL-timezone_offset_asked_once

A timezone's offset, like the one a camera's photos record, is a guess that needs the user's word before it is written. Where tracks lie by the photos the
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


## 7. Per-destination structure

:::{rat} A clock changed during the day shows only on the GPS
:id: RAT-clock_change_seen_by_gps
:status: ruled
:forced: no
:follows_from: RAT-offset_per_camera_destination_day, RAT-anchor_agreement
:justifies: RUL-day_split_into_parts, RUL-clock_change_split_proposed, RUL-clock_change_needs_gps, RUL-alternating_runs_no_clock_change, RUL-clock_change_needs_acceptance, RUL-clock_change_accepted_once, RUL-clock_change_parts_own_evidence, RUL-clock_change_unsettled_photo_asked, RUL-clock_change_settled_photo_not_asked

A day is the unit because a clock is set again overnight; but it is also set at lunch, or reset, and then the day has
two offsets and no one of them fits. Asked to move the photos after the change into a folder of their own, the user
would change the library's folders to work round the tool. The change cannot be read from the photos themselves —
the owner's question, answered yes: *"15 can only be detected using GPS, the photos themselves are not enough.
Correct?"* — their times run on whatever the clock says; only a measurement of the true time, the camera's own
positions on the tracks or its fixes' times, shows the clock jump. A clock set once runs on: taken in the order of
the true times that evidence gives them, its anchored photos fall into two runs, each agreeing on an offset of its
own, and a split there is proposed. The camera's own order would not do: a clock set back shows the hour before the
change a second time, the two runs interleave in camera time, and the day would look like positions gone wrong. A
clock does not go back and forth, so three runs or more in true time are no change — they are positions gone wrong,
or two bodies. The split is the user's to accept, as any proposal is, and accepting it once settles the day: each
part's offset is what its own photos say, nothing borrowed across the change. A photo with no evidence of its own has
only its camera time; read by each part's offset, it may fit one side of the change only, and then it is that part's,
with nothing to ask. But a photo of the hour a clock set back shows twice fits both, and one may fit neither; nothing
says which part took it, and no one camera time divides such photos from each other, since the parts' camera times
overlap — so each is asked its part, of the user, who knows when the clock was set.
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
set once and reach every destination beneath it. Asked for what nothing beneath it waits on, it would add work instead
of saving it; a timezone a destination beneath it waits for is the one question it is the cheaper place to answer.
:::

:::{rat} The clock is the camera's for the day, not the folder's
:id: RAT-clock_is_the_cameras_for_the_day
:status: ruled
:forced: yes
:follows_from: RAT-offset_per_camera_destination_day
:justifies: RUL-offset_shared_within_day, RUL-same_day_offsets_agree

A camera has one clock. Sorting a day's photos into a museum and a castle does not give it two: what its own positions
show of its clock in the morning is the best evidence there is for the afternoon, far better than assuming it kept the
local hour. So a destination with no position of its own that day is offered the offset found elsewhere that day —
applied by itself only where it was sure enough to apply itself there. And where the camera's positions give two
offsets for one day that cannot both be right, one of them rests on a wrong match; neither is written until the user
says which. An offset the user wrote, or accepted on a guess, is not passed on: it is their word about one place, not
evidence. Another day's offset is never passed on by itself either — clocks are set again overnight; the day next to
one with no evidence is only offered ({need}`RAT-neighbour_day_offered`).
:::

:::{rat} The day next door is the best evidence a day without its own can have
:id: RAT-neighbour_day_offered
:status: ruled
:forced: no
:follows_from: RAT-clock_is_the_cameras_for_the_day, RAT-assumptions_need_acceptance, RAT-drift_invisible
:justifies: RUL-neighbour_day_offset_proposed, RUL-neighbour_day_offset_needs_acceptance, RUL-neighbour_day_offset_drift_checked, RUL-neighbour_day_no_gap_bound, RUL-neighbour_day_keeps_its_cell

A day is a camera's day by its own clock, so a camera left on home time abroad, or a night shoot, has its midnight in
the middle of an outing: the outing becomes two days, and the half with no anchor asks for its offset and then for a
drift confirmation, though the other half settled the clock. The offset the camera's own GPS gave the day before or
after, in the same place, is a far better guess than the zone's — but it is another day's, and a clock may have been
set overnight. So it is offered, never applied. But asking for it twice — an acceptance, then a confirmation on the
tracks of the same offset — is the very cost the proposal was to spare, and the second answer is the better one: it is
asked once, as a timezone's guess is. Where tracks lie by the day's photos, it goes to the check against them as it
stands, and the confirmation there, made with the track before the user's eyes, is its acceptance; where none do,
there is nothing to check it against, and the user accepts it as proposed. Bounding the time between the two days
would need a new setting and guess at a night's length; the user's answer and the check are the bound. The day stays
the unit: its decision is its own, and taking the neighbour's offset joins nothing.
:::

:::{rat} A choice from the camera's positions is evidence, and the user's word
:id: RAT-chosen_offset_evidence_and_word
:status: ruled
:forced: no
:follows_from: RAT-clock_is_the_cameras_for_the_day, RAT-decisions_are_the_users
:justifies: RUL-chosen_offset_checked_same_day, RUL-chosen_offset_not_withheld

An offset the user picked from the groups the camera's own positions give rests on those positions, and is passed on
within the day as theirs is. So it can disagree with an offset the positions gave by themselves in another destination
that day exactly as two of those can — one clock read two ways — and the one the positions gave unasked is not written
until the user says which is right. The pick is not withheld in turn: it is the user's word, given with the camera's
evidence in view, and setting it aside for a finding they were never shown would put the tool's reading in place of
their knowledge. Both are shown, each naming the other; and while they disagree neither is passed on, since either
would decide a third destination from one side of an open question.
:::

:::{rat} Accepting a proposal vouches for the reading, not for a number
:id: RAT-accepted_offset_is_the_positions_own
:status: ruled
:forced: no
:follows_from: RAT-chosen_offset_evidence_and_word
:justifies: RUL-accepted_offset_is_the_positions_own

An offset the camera's own positions proposed, accepted as it stood, is still what those positions gave: accepting
says the GPS's reading is fine, not "I chose this number". The user picked nothing against the evidence, so there is
no word of theirs that a disagreement elsewhere that day would set aside unasked — it is held against another
destination's offset as an offset that applied itself is, and waits for the user where those would. The owner's
ruling: *"proposal counts as automatic today - keep it automatic"*.
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

Each track is one device's record, and the tracks folder — or one file of it — may hold several for the same hours: a
phone and a logger in the same pocket, or a companion who spent the afternoon elsewhere. Read as one line through all
the points in time order, two devices five kilometres apart become a zigzag between them, and a photo is placed at
whichever was logged a second nearer — or halfway. Kept apart, two tracks that agree are one party and either serves;
two of one rank that do not are a question only the user can answer, by filing their own track higher or taking out the
one that is not theirs.
:::

:::{rat} The better device is believed first
:id: RAT-better_device_first
:status: ruled
:forced: no
:follows_from: RAT-track_is_one_device, CHC-ask_only_what_data_cannot_settle
:justifies: RUL-tracks_ranked_by_folder, RUL-highest_ranked_track_places, RUL-lower_track_anchors_where_higher_absent, RUL-ranked_folder_missing_told

The owner records each trip twice — a phone and a standalone receiver — and the phone turns out the more accurate: *"I
want the device track to be used when phone track unavailable."* Without a ranking, where both cover a photo the one a
second nearer in time wins, and where they lie apart the photo is not placed at all, so the worse device places photos
the better one covers and two devices of one person read as two people. Which device is better is known to the user,
not to the files, so the user says it once, in the configuration, by where the tracks are filed: a folder is visible
and chosen, where a file's `creator` is whatever the app wrote — and the same for a companion's phone with the same app.
A lower track then serves only where the better one recorded nothing, for an anchor as for a position, so placement and
the clock offset rest on the same evidence. A ranked folder that is not there — misspelt, or not yet created — would
silently rank nothing, so it is said.
:::

:::{rat} The worse device's distance is a measure
:id: RAT-outranked_distance_measured
:status: ruled
:forced: no
:follows_from: RAT-better_device_first, RAT-coordinate_carries_its_method
:justifies: RUL-lower_track_distance_recorded, RUL-lower_track_disagreements_told

Where the better track wins, the other is not wrong evidence to discard but a second reading of the same walk: how far it
puts each photo is the measure of its error, which says how far it can be trusted where it alone recorded. Asking about
it would cost a question for something the ranking has settled; recording and counting it costs nothing.
:::

:::{rat} Missing is not the same as none
:id: RAT-missing_tracks_are_not_no_tracks
:status: ruled
:forced: yes
:follows_from: RAT-folder_gps_fallback, RAT-decisions_reread_cache_only, RAT-a_link_escapes_the_tree
:justifies: RUL-missing_tracks_stop_geotag, RUL-no_tracks_no_stop, RUL-unlisted_tracks_stop_geotag, RUL-unreadable_tracks_stop_geotag, RUL-track_link_never_followed, RUL-track_link_named

A library with no tracks at all is a supported case: every decision falls to its other sources. A tracks folder that is
named and not there is something else — a volume not mounted — and planning on as if there were none would place by
folder fallback every photo the tracks place precisely, and drop the confirmations given against them. Nothing in the
result would show it. Stopping costs one mount command. A folder of the tracks that cannot be listed is the same at
every step — at execute too, where the plan's tracks are checked again: what it holds cannot be seen, and taking it for
empty would withdraw every track in it. And a folder of tracks that cannot be read is not a trip without tracks — it is
one whose tracks are about to be ignored. A link within the folder leads out of it, to recordings the user did not file
there, and is not followed; its tracks, unread, are named as unread rather than taken silently for none.
:::

:::{rat} The evidence stays with what it decided
:id: RAT-tracks_kept_with_workspace
:status: ruled
:forced: no
:follows_from: RAT-database_is_record, CHC-photos_matter
:justifies: RUL-track_points_kept, RUL-withdrawn_track_points_kept, RUL-sealing_needs_no_tracks, RUL-merge_needs_no_tracks

A placement or a clock offset rests on track points, and the tracks folder is the user's, outside the workspace: it is
reorganised, pruned, moved to another disk. A sealed workspace that recorded only a track's fingerprint and name could no
longer show why a photo was put where it was once the folder had changed. The owner: *"I will have always the gps data
used during the process, in the form used during the decisioning, which would make the workspace truly
self-contained."* Kept in the database of record, the points are archived and sealed with every other record, and
sealing then needs nothing outside the workspace. A track taken out after its plan was executed takes nothing out of the
evidence of what was written into the photos: the points stay, withdrawn.
:::

:::{rat} The record holds what the decisions rest on
:id: RAT-kept_points_are_the_windows
:status: ruled
:forced: no
:follows_from: RAT-tracks_kept_with_workspace, RAT-tracks_read_where_reached
:justifies: RUL-unused_points_not_kept

The points are kept because decisions rest on them; a point no decision of the latest planning reaches is evidence of
nothing, and kept it would grow the record by every window a trip's planning ever passed through — a photo sorted
out, a setting tightened. So what lies outside the window the planning reached goes, and is read again from the track
file should a window reach it later. What an executed plan used is the exception: it is evidence of a value written
into an original, and stays, as a withdrawn track's points do. The owner's ruling: *"track points outside window - as
per recommended"*. The planning prunes only once it has stopped, at the window it last reached: mid-run the window
is still to widen, and pruning there would read the same files again on every run.
:::

:::{rat} The tracks are read where the photos reach them
:id: RAT-tracks_read_where_reached
:status: ruled
:forced: no
:follows_from: RAT-tracks_change_the_answers, RAT-surgical_staleness
:justifies: RUL-tracks_elsewhere_restale_nothing

A tracks folder holds years of recordings, and a workspace is one trip. Reading every track file whole on every run,
and fingerprinting it all, makes the whole folder a dependency of the trip: a walk recorded last week restales the
decisions of a holiday three years ago, and every decision asks again for no reason in its evidence. Only the points a
decision can reach change it; a track unchanged since it was last read need not be read again.
:::

:::{rat} The window is what the readers reach, not a setting of its own
:id: RAT-track_window_from_readers
:status: ruled
:forced: no
:follows_from: RAT-tracks_read_where_reached, RAT-setting_read_once
:justifies: RUL-track_window_reaches_every_reader

The window bounds which points are read, and every point a reader of the tracks can reach must be in it — so it is
computed from each reader's own settings, never set by one of its own. The owner asked: *"aren't you reusing a config
value for a different purpose?"* — the window does read the matching, gap and drift settings. But it reads each as that
reader's reach, for that reader: the same judgement the setting is tuned for, not a second one beside it. Retuning
`gpx_interpolation_max_gap_seconds` for a museum widens the window with it, which is what it should do; no other
judgement moves unseen. A window setting of its own would be the second judgement: set smaller than a reader's reach,
it would starve that reader unseen — a photo the gap would bridge left unplaced, an anchor never found, with nothing in
the decisions to say the tracks were cut short — and set larger, it reads what nothing uses.
:::

:::{rat} A track is taken out because it is someone else's
:id: RAT-gone_track_withdrawn
:status: ruled
:forced: no
:follows_from: RAT-track_is_one_device, CHC-ask_only_what_data_cannot_settle
:justifies: RUL-gone_track_told, RUL-gone_track_not_used

The one reason a user takes a track file out of the tracks folder is that it is not this trip's: a companion's phone
recording the same afternoon elsewhere, which keeps photos from being placed. Taking the file out is the user's answer,
and geotag decides as if it never was; but a file that has merely vanished — a folder renamed, a sync gone wrong — would
change positions as silently, so each one gone is named.
:::

:::{rat} A break is where nothing is known
:id: RAT-break_is_unknown
:status: ruled
:forced: no
:follows_from: RAT-track_is_one_device, RAT-track_squeezed
:justifies: RUL-track_is_one_trk, RUL-track_break_never_bridged

A file can hold several devices' tracks, and joined they zig-zag between two people as surely as two files would. A
break between segments is where the recorder was off: where the device was in between is not in the file, and a line
drawn across it is invented.
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
offset no camera of theirs had. Each carries what time it has; read alone, by its own offset, it asks nothing and
borrows nothing — and where it records none, the place's zone is a guess, asked once for the place.
:::

:::{rat} A modification time is another clock's
:id: RAT-modified_time_is_another_clock
:status: ruled
:forced: no
:follows_from: RAT-no_identity_no_group, RAT-offset_per_camera_destination_day
:justifies: RUL-modified_time_solved_alone, RUL-modified_time_no_camera_offset, RUL-modified_time_opens_no_day

A photo's `ModifyDate` is where its time is read from only when neither `DateTimeOriginal` nor `CreateDate` holds one —
an export whose capture time is gone. It is then the time the photo was last saved, by the editing computer's clock,
not the camera's; but the export keeps the camera's make and model, so it would join the camera's group, open a day of
its own on the edit's date — a question about a day the camera never shot — and have the camera's offset applied to a
computer's clock. Read alone, as a file naming no camera is, it asks nothing and borrows nothing. `CreateDate` is the
camera's clock still: a camera writes it as it writes the original. Treating such a photo as untimed instead would stop
geotag on a time that is, at worst, a poor guess the user can see and correct.
:::

:::{rat} Only the user knows a group is two bodies
:id: RAT-several_bodies_said_by_the_user
:status: ruled
:forced: no
:follows_from: RAT-class_decides_time_model, RAT-anchor_agreement
:justifies: RUL-several_bodies_named_by_configuration, RUL-several_bodies_offset_never_auto, RUL-several_bodies_noted, RUL-several_bodies_days_apart, RUL-several_bodies_no_clock_change_split, RUL-several_bodies_positions_not_doubted

Two bodies of one model that write no serial are one camera group: nothing in their photos tells them apart. With GPS
on both, their anchors disagree for good and no one offset is right; with GPS on one that day, its offset would apply
itself to the other's photos; and a day's offset found in one destination would be passed to, or held against, the other
body's in the next. Geotag cannot see this, and treating every group as perhaps two would cost every camera the offsets
that apply themselves. So the configuration says it, a group being one camera unless named — the owner's ruling: *"no,
this needs a workspace setting, default being that it's just one camera. If the setting says multiple cameras, then do
the recommended"*. For a group so named, an offset from its GPS is a proposal, said to be perhaps one body's; its photos
that disagree with it are another body's, their positions right, never offered for replacing; its days in
different destinations are decided apart; and the user tells the bodies apart by sorting one's photos into a folder of
their own — never by a split of the day, for two bodies shooting one after the other look like one clock set at the
change.
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
nothing. And a zone the user sets on a place's folder — a country, a region — should hold for everything beneath it:
one answer for the place, not one per folder.
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
per place, at the folder of the country or region it holds for, everything beneath inheriting it; a place at home
takes it in one click.
:::

:::{rat} A timezone is asked wherever an answer would reach, and asked no more once given
:id: RAT-zone_asked_at_every_level
:status: ruled
:forced: no
:follows_from: RAT-decisions_cascade, RAT-nearest_timezone, RAT-home_zone_offered
:justifies: RUL-zone_asked_at_every_level, RUL-zone_not_asked_where_one_reaches, RUL-editor_answer_ends_zone_asking

Asked only where photos lie, a country of three cities asks three times, unless the user knows to answer on the folder
that asks nothing. The tool cannot tell which folder is the place a zone holds for — a country, a region, a town — so it
asks at each folder above a destination that waits, and the user answers where it is true; the owner: *"the user should
be asked at every level and any choice should propagate to children, with the caveat of multiple timezone countries"*.
An answer passes down to everything below, so the questions it settles go with it: *"This should not multiply choices -
once a time zone is set, children destinations should not ask any longer"*. A folder whose answer would reach nothing —
one said to be in a country of several zones, or one above a zone written lower down — is not asked: its question would
be one no answer settles.
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

:::{rat} A fix's time is a measurement of the clock, unless the fix is stale
:id: RAT-gps_time_measures_the_clock
:status: ruled
:forced: no
:follows_from: RAT-anchor_agreement, RAT-camera_records_its_clock_zone
:justifies: RUL-gps_time_is_clock_evidence, RUL-repeated_gps_time_not_counted, RUL-gps_times_agreeing_apply, RUL-single_gps_time_proposed, RUL-gps_time_far_from_evidence_withheld, RUL-gps_time_rank

A camera with its own GPS writes, beside the position, the UTC its fix was taken at. Less the camera's own time, that is
the clock offset itself — measured, where the offset the camera records only states what its clock was set to and the
zone's guess assumes it. With no track by the photo's place it is all the photo says of its clock. A track anchor still
comes first: a fix's time can be stale, and a stale fix repeats its time while the camera's moves on — so readings count
only where their GPS times all differ and their offsets agree, and then, two or more, they apply themselves as several
anchors do; one is a single chance of a stale fix, and is offered. A camera writing local time into the GPS field shows
a whole-hour difference: a track catches it where there is one, and so does the check against the destination's other
devices that holds back a guess far from all of them.
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
:justifies: RUL-phone_time_from_own_offset, RUL-offset_within_value_before_beside, RUL-offset_within_time_value

A phone's clock is set by its network and it records the offset it was at, beside each time it writes: better evidence
than any zone geotag could assume. But a photo holds several times, each with its offset — when it was taken, digitized,
modified — and an offset describes only the time it was written with; another would be right only by chance. Where the
photo records none for its time, the destination's zone is the best guess left. An offset written within the time's own
value is part of that value; one in a field beside it is paired by convention, and a tool may have written the two apart
— so the one within comes first.
:::

:::{rat} A phone's error is a whole zone, and its own GPS shows it
:id: RAT-phone_error_is_a_zone
:status: ruled
:forced: no
:follows_from: RAT-phone_records_its_offset, RAT-anchor_agreement
:justifies: RUL-phone_anchored_like_camera, RUL-gps_time_checks_phone, RUL-phone_agreeing_anchor_changes_nothing, RUL-phone_disagreeing_anchors_apply, RUL-phone_single_anchor_proposed, RUL-phone_kept_as_recorded

A phone takes its time from the network and was trusted with nothing checking it: a phone set to the wrong zone, a
photo whose tag is missing while the phone sat in another zone, a phone set by hand to the wrong hour, would each pass
unseen and misplace every such photo on the track. Where its photos hold their own position, the tracks — or the
fixes' own times — say what its clock was, exactly as they do for a camera, and by the same settings: no new setting,
for a phone's error is a whole zone, not drift (ruled as recommended, *"otherwise all as recommended"*). Agreeing with how the phone's photos are read,
there is nothing to ask. Several of them agreeing among themselves against it is the evidence a camera's several
anchors are, and applies itself for that phone and day, the cell showing it; one photo could be a coincidence, and is
offered. The user, who knows the track was someone else's, can keep the phone as it records itself (ruled *"all ok"*),
without typing an offset that a drift check would then ask about again.
:::

:::{rat} A time read by the zone is an assumption, asked like one
:id: RAT-zone_reading_is_an_assumption
:status: ruled
:forced: no
:follows_from: RAT-assumptions_need_acceptance, RAT-phone_error_is_a_zone, RAT-one_number_one_question
:justifies: RUL-untagged_phone_photo_read_as_siblings, RUL-untagged_phone_photo_settled_by_evidence, RUL-untagged_phone_photo_asked, RUL-camera_less_files_asked_per_destination, RUL-camera_less_answer_kept

A camera's "clock was on local time" is a proposal the user accepts, and is then checked against the tracks. Read
silently by the zone, a phone's photo with no offset tag and a file naming no camera would be placed on the tracks by an
assumption. So, ruled as recommended, the phone's photo is read as the same phone's tagged photos that day show,
unasked, where those show the zone's offset; else its GPS time or a track settles it; with neither, it rides the drift
check where there are tracks, and is asked where there are none: the phone's own photos that day are the best word on
its clock, its own GPS the next, and only then is it the guess a camera's is, asked once. A file naming no camera has no
siblings to read it by; its question is one per destination — "N files name no camera and no offset: read them as local
time in <zone>?" — answered once and kept (the owner: *"I suppose that happens in the editor, right?"*): a screenshot is
made at the local time of wherever it was made, which the user knows for the folder as a whole, not file by file. The
answer names the zone it was given for, so a zone changed later asks again.
:::

:::{rat} Two readings, answered where the other questions are
:id: RAT-two_readings_answered_in_the_record
:status: ruled
:forced: no
:follows_from: RAT-two_readings_no_guess, RAT-every_question_answerable
:justifies: RUL-ambiguous_local_time_answered, RUL-repeated_time_answered_by_a_reading

A time a daylight-saving change repeats or skips left a stop, could be mended only outside the tool: an offset written
into the original with exiftool, prep run again. The photo still says nothing of which reading is right, but the user
may know — the hour of the party, the flight — and so it is answered in the time decisions, per photo: which reading,
for a repeated time, or the offset, for a skipped one (ruled as recommended). A time shown twice is one of its two
readings and nothing else; a time never shown came from a clock that was not the zone's, so its offset is the user's to
say.
:::

:::{rat} A tag that cannot be read is said, not dropped
:id: RAT-unreadable_tag_said
:status: ruled
:forced: no
:follows_from: RAT-phone_records_its_offset, CHC-photos_matter
:justifies: RUL-unreadable_offset_tag_is_none, RUL-unreadable_offset_tag_told, RUL-unreadable_offset_tag_recorded

An offset tag reading `local`, or `+25:00`, is no offset; read loosely it would turn a photo's time by a guess.
Read as none, the photo falls to the next source of its time — and silently, the user would believe it read by the
offset its device recorded. So it is read as none, and said: named in the run's output and kept in the record, where
it can be seen later and mended.
:::

:::{rat} A camera's clock does not change at a daylight-saving switch
:id: RAT-camera_clock_ignores_dst
:status: ruled
:forced: no
:follows_from: RAT-offset_per_camera_destination_day
:justifies: RUL-camera_zone_offset_for_the_day

A camera's clock is set by hand and keeps its setting through the night clocks change; a phone's follows the
network. So a camera's offset guessed from the zone is the zone's at its day's earliest photo, and holds for the whole
day (ruled as recommended: stated as it is). Reading each of its photos by the zone instead would move the photos after the switch by an hour its
clock never moved.
:::

:::{rat} Two readings, and nothing to choose by
:id: RAT-two_readings_no_guess
:status: ruled
:forced: no
:follows_from: CHC-photos_matter, RAT-assumptions_need_acceptance
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

:::{rat} What was seen was those tracks
:id: RAT-confirmed_on_those_tracks
:status: ruled
:forced: yes
:follows_from: RAT-confirmed_one_offset, RAT-kept_offset_needs_its_evidence
:justifies: RUL-confirmation_rests_on_its_tracks, RUL-changed_tracks_asked_again, RUL-trackless_confirmation_holds_while_none, RUL-stale_confirmation_kept

Confirming is looking at the photos on a track as it was recorded then. The user takes a track out of the folder
because it was someone else's, or puts in another export of the day; an offset that looked right on the first is then
read on a track nobody set the photos against, and carried over, the confirmation would pass a placement nobody
checked. So it names the tracks it was made against, as an offset found from the camera's own GPS names the tracks it
was found from, and holds while they stand. One made where no track lay by the photos saw none: any track that comes
later is one it never saw. The answer that no longer holds is still the user's: it stays as they wrote it, the record
of what they saw, for them to replace.
:::


## 15. Every photo's own values

:::{rat} A new decoder does not make a new photo
:id: RAT-same_photo_new_fingerprint
:status: ruled
:forced: yes
:follows_from: RAT-decision_withdrawable, RAT-decoded_pixel_identity, RAT-new_fingerprint_same_photo
:justifies: RUL-own_values_follow_new_fingerprint, RUL-geotag_plans_on_vouched_log, RUL-geotag_executes_on_vouched_log, RUL-fingerprint_mapping_one_to_one

A new ImageMagick may decode a photo to a new fingerprint; the photo is the same, and so are its own time and
position. Lost with the old value, they would leave geotag taking the photo's corrected time for its own: a changed
offset would never reach it, a withdrawn one never undo. Prep's log says which old value became which new one; where
it does not say so one for one, no photo's values can be told apart, and geotag stops rather than guess. A log the
handoff does not vouch for says nothing that can be trusted of which became which: planned past it, as though no
fingerprint had changed, a photo would lose its pinned values without a word — so geotag stops on it as well, as
finalize and merge do. Execution builds the same model again from the log and moves each pin to its new value; the
log may have changed since the plan was made, so execution asks the same of it, before it changes anything.
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

:::{rat} A position the camera's own clock contradicts is offered, never replaced unasked
:id: RAT-contradicted_position_offered
:status: ruled
:forced: no
:follows_from: RAT-own_position_best, RAT-anchor_agreement, RAT-decisions_are_the_users
:justifies: RUL-own_position_replaced_on_answer, RUL-contradicted_position_reviewed, RUL-contradicted_position_kept_unless_taken, RUL-contradicted_position_without_track_noted, RUL-replaced_own_position_logged

A camera's own position is the best evidence of where a photo was — unless it is wrong. Among photos that agree on the
camera's offset, one whose own position agrees with none of them most likely carries a position that is not its
photo's: GPS jitter, a fix from minutes before, a position another program wrote. Accepting the agreed offset corrects
its time and would leave the wrong place in it, and the user could only read the pattern and mend it elsewhere. The
tracks say where the user was at the photo's corrected time; where that lies farther from the photo's own position than
an anchor may, the two are set side by side, the track's proposed. The photo's own stays unless the user takes
another: it is still a measurement, and only the user can tell a stale fix from a detour the track missed — so nothing
waits on it, and nothing replaces it but their answer. With no track at that time there is nothing to propose; the
photo keeps its own, and the record says it was doubted. A position replaced is a position lost from the photo, so
the record keeps it.
:::

:::{rat} Latitude 0, longitude 0 is a device without a fix
:id: RAT-null_island_no_fix
:status: ruled
:forced: no
:follows_from: RAT-own_position_best, CHC-total_placement, CHC-ask_only_what_data_cannot_settle
:justifies: RUL-null_island_is_no_position, RUL-log_records_null_island_replaced

A device that has no fix and writes a position anyway writes latitude 0 and longitude 0: a point in the Gulf of Guinea
no photo of a trip is taken at. Kept as the photo's own, it would never be placed, be counted as placed, and be matched
against the tracks as evidence of the camera's clock. It was measured nowhere, so it is no measurement to keep: the
photo is placed as one without a position, and asking about each would ask what the data settles. Only the exact
point counts — a position merely near it, or far from the others, may be real. The value the device wrote is replaced,
so the log keeps it, and the photo's history still shows what it carried.
:::

:::{rat} Most specific first
:id: RAT-placement_most_specific_first
:status: ruled
:forced: yes
:follows_from: RAT-track_squeezed, RAT-folder_gps_fallback, RAT-remainder_worklist
:justifies: RUL-placement_order

Each source speaks for fewer photos than the one after it: a position the user set speaks for that photo alone, a track
for the instant it was taken, a fallback for a whole folder. The first that applies is the most specific word on where
the photo was; a photo none of them places is one only the user can answer for — with a place for it, or one for its
folder.
:::

:::{rat} No photo leaves geotag without a position
:id: RAT-no_photo_unlocated
:status: ruled
:forced: no
:follows_from: CHC-total_placement, RAT-folder_gps_fallback, RAT-remainder_worklist
:justifies: RUL-unplaced_photo_waits, RUL-finalize_refuses_unplaced, RUL-merge_refuses_unplaced, RUL-no_plan_while_a_decision_waits

The tool is for a map-complete library, and every photo has some place a person can name: where it was taken, or at
least the place its folder stands for. The owner: *"I explicitly want* no *unlocated photos. this is the role of the
folder fallback."* — and: *"This means that geolocation phase should not be able to close while photos that cannot be
geoplaced are in by-dest."* So a photo nothing places waits for that answer, and the folder's fallback is the one
answer that serves a whole folder of such photos at once. Waiting is not enough on its own: what reaches the library
is the photos as they are, and a photo can hold no position however its plan was decided — a write that never landed,
a device's latitude 0 and longitude 0 read again. So finalize, which signs for the photos, and merge, which takes them
into the library, look at what each photo holds, not at what was decided for it.
:::

:::{rat} An answer given for one photo outranks the tracks and the fallback, and stays
:id: RAT-photo_answer_most_specific
:status: ruled
:forced: no
:follows_from: RAT-placement_most_specific_first, RAT-decisions_are_the_users
:justifies: RUL-chosen_position_honoured, RUL-chosen_position_names_a_photo, RUL-chosen_position_kept

A position the user gives one photo is the most specific word there is on where it was, so it outranks a track and a
fallback — also for a photo they already place, where the user knows better: a track recorded on the way back, a
fallback that stands for the folder and not for this frame. Given, it is their decision, and a track or a fallback
coming later does not take it back; only the user does, by emptying it. An answer that names no photo it could place —
one not in that folder, or one keeping a position of its own — would be passed over in silence, so it stops the run.
:::

:::{rat} A place inside a place is near it, so its fallback applies itself
:id: RAT-fallback_nested
:status: ruled
:forced: no
:follows_from: RAT-folder_gps_fallback, RAT-decisions_cascade, RAT-no_photo_unlocated
:justifies: RUL-fallback_from_nearest, RUL-inherited_fallback_applies, RUL-written_fallback_over_inherited

A destination inside another lies within it, so the place set for the outer one is a fair stand-in for the inner one —
and the nearer the one it is written at, the fairer. The owner: *"My idea was that once a destination gets a fallback
position, it should propagate by default to child destinations, but show up as "inherited" or "propagated", and be
overridable. The idea is not to manually accept it for all children but to manually override if I want for the
children."* — and, ruling it: *"An inherited fallback applies itself - yes but I should be able to be overriden at child
destination level, in one go, not to be overriden at image level."* So the inherited fallback applies itself, and
follows the one above when that changes, as an inherited timezone does; where the user knows better, they write the
child's own, which every photo there the fallback places takes, and the folders beneath inherit — one answer for the
folder, not one per photo; emptied, the child inherits again. An offset is asked where a fallback is not
({need}`RAT-assumptions_need_acceptance`) because the two cost differently when wrong: a fallback claims no precision —
one point for the photos nothing better places, marked in each as the folder's fallback — so a wrong one is a coarse
position the user sees and replaces at the folder, where a wrong offset moves every photo of a day, its time and its
place, with the look of a measurement. And there is no "none" to write in its place: a photo the fallback did not place
would be left with no position, which the tool does not do ({need}`RAT-no_photo_unlocated`).
:::

:::{rat} A fallback that applies itself is shown where it acted
:id: RAT-applied_fallback_shown
:status: ruled
:forced: no
:follows_from: RAT-fallback_nested, RAT-remainder_says_why
:justifies: RUL-fallback_placements_told, RUL-fallback_photo_says_why

An answer applied unasked is cheap only while the user can see where it acted. Told, per destination, how many photos
the fallback placed and whose fallback it was — the destination's own, or the one inherited from a folder named — the
user sees a folder placed by a point meant for another, and writes it its own. And a photo the fallback placed is one
the tracks missed; why they missed it is the lead it is for a photo left unplaced ({need}`RAT-remainder_says_why`): a
day's photos all fallen back, an hour past the end of a track that day, point at a clock, not at the folder — a cure the
fallback would otherwise hide.
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

:::{rat} A photo's position was answered where it lay
:id: RAT-position_answered_for_its_destination
:status: ruled
:forced: no
:follows_from: RAT-destination_is_an_input, RAT-decisions_cascade
:justifies: RUL-moved_photo_position_decided_anew

A position typed for a photo is given looking at the photo where it lies: the place its folder names, the fallback
that folder has or lacks, the tracks that covered it there. Any of these may have been part of the answer — the owner:
*"it may have been decided partially because of the destination"*. Moved, the photo stands among another folder's
answers — a fallback that would place it now, a place it was not — and the old one, carried, could keep it pinned
where the folder says it was not. Asked again, it costs one answer.
:::


## 17. The corrected time

:::{rat} Only a time geotag wrote is marked as corrected
:id: RAT-only_corrected_time_marked
:status: ruled
:forced: no
:follows_from: RAT-no_redo_to_be_safe, RAT-mark_in_the_file
:justifies: RUL-only_corrected_time_marked

An original is touched only where it needs to be. A photo already holding its true time — a phone keeping the
network's local time, beside its own position — needs nothing from geotag; marking it would write to it for nothing,
and the mark would tell digiKam, and every reader after it, that a time was fixed which geotag never touched. So the
mark goes only on a photo whose time geotag writes, or wrote on an earlier run. Left unmarked, the other is decided
from its own values again on every re-run, and comes to the same: nothing to write.
:::

:::{rat} The time a person would have read on the wall
:id: RAT-time_written_as_lived
:status: ruled
:forced: no
:follows_from: CHC-local_folder_library, RAT-offset_per_camera_destination_day
:justifies: RUL-corrected_time_written_local

Once a photo's true instant is known it could be written as UTC, as the camera's home time, or as the time where it was taken. A library is browsed by people: the morning market should read as morning. Written as the destination's local time with its offset beside it, the photo both reads as it was lived and still states its exact instant.
:::

:::{rat} One making, one time, in every field that records it
:id: RAT-every_field_one_time
:status: ruled
:forced: no
:follows_from: RAT-time_written_as_lived, RAT-shutter_time_first
:justifies: RUL-other_capture_times_corrected

A photo can record when it was made in more than one field — EXIF's `CreateDate` beside `DateTimeOriginal`, the
`DateCreated` of XMP and of IPTC — and a program reading any of them should find the corrected time, not the camera's
wrong one beside the right one. Only a field the photo already holds is rewritten: one it never held would be a record
nobody made. `ModifyDate` is not the making but the last edit, and keeps its time. The fractions of a second recorded
beside a time stay as they are: a clock offset is a whole number of seconds, so the fraction is still the right one.
:::


## 18. Renames

:::{rat} Geotag finishes the spelling prep could not
:id: RAT-geotag_finishes_extension_spelling
:status: ruled
:forced: no
:follows_from: RAT-one_extension_spelling, RAT-by_dest_is_the_users
:justifies: RUL-geotag_extension_lowercase

Prep gives every file it files one spelling of its extension, but photos by destination is the user's sorting, which
prep leaves as it finds it — so a photo put there by hand keeps the `.JPG` its camera wrote. Geotag renames the
photos there anyway, and is the last phase to touch them before the library: left to it, the one spelling holds in
the library too, and a name is the same name on every filesystem and in every tool.
:::

:::{rat} A burst is read in the order of its names
:id: RAT-names_in_capture_order
:status: ruled
:forced: no
:follows_from: RAT-geotag_finishes_extension_spelling
:justifies: RUL-suffix_in_capture_order, RUL-pair_named_as_one

Within one second, the suffix is all a folder listing has to order a burst by. Given in path order, where `-` sorts
before `.`, `T`, `T-001` and `T-002` become `T'-002`, `T'` and `T'-001`: the burst rotates. The fraction of a second a
camera records is its own order of the frames, and the suffix prep gave is the order prep had them in; either keeps the
burst as it was shot. A RAW and its JPEG, a HEIC and the other file of its shot, are one shot: named apart, one half
lands beside another frame's other half, and the pair shows a shot that never was — as would a new name another photo
holds under another extension.
:::

:::{rat} A name is the time the place showed
:id: RAT-names_local_in_repeated_hour
:status: ruled
:forced: no
:follows_from: RAT-time_written_as_lived
:justifies: RUL-names_local_in_repeated_hour

A photo's name is the time its destination's clocks showed — the time of a ticket, a timetable, a diary. In the hour a
zone repeats as its clocks go back, those clocks run back, and names taken from them sort against the true order for
that hour. A name of true time — UTC, or an offset in every name — would mislabel every other hour to fix that one.
The true order is kept where it can be read: in the metadata, each time with its offset beside it.
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

:::{rat} A photo that cannot be written is taken out, not let through
:id: RAT-unwritable_photo_taken_out
:status: ruled
:forced: no
:follows_from: RAT-record_covers_broken_runs, CHC-photos_matter
:justifies: RUL-failed_write_reason_recorded, RUL-repeated_write_failure_way_out

A photo the metadata tool will not write — a damaged file, a format it reads and cannot write — fails every execution
the same way; the execution stays partial, and finalize waits on it with every other photo. The tool's own reason is
what tells such a photo from a passing trouble, so it is kept beside the failure. A failure seen twice the same way
will not mend by running again, and nothing else names the way out: take the photo out of what geotag works on — back
into photos by date, a move the workspace check lets pass — and plan again, the rest going on without it. Ruled
2026-11-16: no acceptance of such a photo as it is, and no sidecar. A photo must not reach the library holding a time
or a position other than the one the plan decided for it; and a sidecar is a second record of the photo that digiKam
reads only when set to, while the photo itself goes on holding the old values wherever it is taken.
:::


:::{rat} An execution's record that cannot be read is not an empty one
:id: RAT-unreadable_record_not_empty
:status: ruled
:forced: yes
:follows_from: RAT-record_covers_broken_runs
:justifies: RUL-unreadable_execution_record_stops

A journal says which of a plan's changes were made and how each photo was left; the execution summary holds the
user's acceptance of a changed picture; a kept plan and its journal are a pass the log must tell. Taken as empty, the
first is written over by the next confirmation, the second loses its acceptances, the third drops a pass from the
log without a word — each loss silent, and none recoverable from the photos. A damaged record is the user's to look
at; stopping and naming it keeps it as it is until they have.
:::

:::{rat} A plan is made again, not repaired
:id: RAT-plan_made_again
:status: ruled
:forced: yes
:follows_from: RAT-unreadable_record_not_empty
:justifies: RUL-unreadable_plan_replanned, RUL-unread_plan_never_run_passed

The executable plan holds nothing of its own: geotag makes it from the decision records, the photos and the tracks, all
still there, so planning again makes it whole and nothing is lost — unlike a journal or a summary, which hold what only
a run saw. Read in part, a plan would be carried out in part, or summarised and merged on as if whole; stopped on, it
points the user to the one command that makes it anew. Planning again sets the torn plan aside, as it sets aside every
plan it replaces, and finalize reads the plans set aside for the passes they ran; a torn one there would stop it again,
a second step for a file that recorded nothing. A plan no execution ran is no record of an execution: when every summary
names the plan it ran by its content and every journal belongs to a plan that can be read — so not even a run cut off
before its summary can have been the torn one's — finalize passes it over, and it stays kept and archived. So a plan
made again for one torn before it ran ends in a finalize that needs no hand on the torn copy. Where an execution may
have run it, the torn copy is still a record finalize cannot read, and it stops.
:::

:::{rat} Geotag's summary, too, records an execution
:id: RAT-geotag_summary_records_an_execution
:status: ruled
:forced: no
:follows_from: RAT-summary_records_an_execution, RAT-unreadable_record_not_empty
:justifies: RUL-geotag_summary_only_for_execution

Geotag's summary is what merge's is: the record of an execution, and the one place the user's acceptance of a
changed picture is kept. A run turned away at the door executed nothing, and the terminal has said why; a summary
written for it would put a record of nothing over the last execution's — and with it the acceptances finalize and the
next run read. An interrupted run reached no end to record: its journal holds what it confirmed, and the run that
finishes it writes the summary.
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
:justifies: RUL-finalize_checks_photos, RUL-finalize_reports_placement

Merge refuses a photo changed since finalize, on the strength of what finalize recorded. If finalize records whatever it finds, an edit made between execute and finalize becomes the baseline, and the library receives a photo the log describes as something else. Finalize is given once the user judges the work done, so it is also where they are told how done: how every photo came by its position, and by what means.
:::

:::{rat} What a run reported stays on the record
:id: RAT-run_records_outlive_the_next
:status: ruled
:forced: yes
:follows_from: RAT-superseded_plans_recoverable
:justifies: RUL-geotag_run_records_kept, RUL-prep_journal_kept

An execution's summary is the one account of what that run did — what it applied, what failed, which pictures came
out changed — and a package is what was handed on for keeping. The next execution, or a finalize run again after a
further pass, would otherwise replace them, and with them a failure not yet looked at or the package already copied
to storage, which the workspace could then no longer show as it was. A prep journal is the same account of an attempt: a plan
executed again after a failed or interrupted attempt would otherwise replace the record of what that attempt did. Set
aside, as a superseded plan is, they cost a file each and lose nothing.
:::

:::{rat} A command needs only the tools it runs
:id: RAT-refusal_for_what_is_needed
:status: ruled
:forced: no
:follows_from: RAT-package_answers_later
:justifies: RUL-finalize_needs_no_metadata_tool

Finalize reads records and the photos' sizes and times, and writes only into the control folder; it reads and writes
no photo's metadata. Execution writes every photo's through that tool, and a plan is made to be executed, so those two
stop without it. Refusing it because the metadata tool is not installed — on a machine the workspace was moved to
for archiving, say — would stop the one step that packages work already done, for a tool nothing in it would run, and
send the user to install something they do not need.
:::
