# photos-cartographer — what is open

*Every entry stands alone: what it is, why it matters, what blocks it.*

- **What this is:** [`README.md`](README.md). **The record:** [`HISTORY.md`](HISTORY.md).

*Open items: **12** — 7, 11, 22, 28, 30 to 32, 40, 47, 49, 53, 55.* 🛑 Numbers are never reused; the next is **56**.

---

## Open

### 7. One obligation per item, checked by reading

**Why:** every corpus item states one obligation, and `tools/spec-build` refuses an item with more than one SHALL. But
the count cannot see a second obligation folded into one sentence: in the pass that made every item one SHALL, about 90
items had a restating second SHALL reworded into the first, and some of them still carry two obligations under one
SHALL — `RUL-lock_fail_fast`, for one, stops at once, says the workspace is locked and produces nothing;
`RUL-replanning_keeps_the_prior` sets the saved plan aside and tells the user where; `RUL-no_plan_no_run` stops and
tells the user to plan first. From §4's structure: `RUL-structure_built_once`, `RUL-top_level_only_managed`,
`RUL-first_dump_at_top_level`, `RUL-link_named`, `RUL-geotag_merge_check_links`, `RUL-missing_folder_blocks`,
`RUL-missing_folder_named`, and `RUL-no_links` with its four cases. From §5's camera groups:
`RUL-prep_derives_camera_group` (derive the group, record it in two places) and `RUL-camera_group_derivation_versioned`
(carry a version, have it checked). From §6's filename format: `RUL-one_filename_format` (one format, set by the
configuration, hard-coded by neither phase), `RUL-suffix_no_clobber` (zero-padded, deterministic, compared without
regard to case, checked against the names on disk and those planned), `RUL-prep_name_provisional` (the raw timestamp,
for ordering only, never corrected) and `RUL-geotag_name_final` (work out the final name, rename to it). From §7's tracks: `RUL-tracks_geotag_only` (what
geotag alone does with the tracks, and what prep never does). From §9's loop: `RUL-sort_photos_only` (only photos, and
geotag refuses otherwise), `RUL-rerun_does_what_changed` (exactly what changed requires, and asks only about what is
affected), `RUL-merge_is_terminal` (merge comes last, new media goes to a fresh workspace) and
`RUL-more_dumps_until_merge` (a dump is accepted, the loop resumes from prep). The owner caught
the pattern in a proposed `RUL-failed_operation_clean` and wants the rest found.

**What to do:** read every item against a stricter test — one property per item, which a single test could find broken
in only one way — and split each real second obligation into an item refining the first, the tests' marks following, as
`RUL-failed_operation_clean` was split into it, `RUL-failure_recorded` and `RUL-failure_never_done`.

The same reading should settle what the rationale-link pass (2026-11-14) noticed:
- rationales that justify rules of different kinds, some forced and some a judgement, so one `forced` verdict fits them
  badly — candidates for splitting: `RAT-library_is_ground_truth`, `RAT-library_reads_cost`, `RAT-move_not_copy`,
  `RAT-sealed_is_final`, `RAT-superseded_plans_recoverable`;
- `RAT-offset_per_day_and_place` largely repeats the philosophy's `RAT-offset_per_camera_destination_day`;
- `RUL-merge_run_reported` (and `RAT-merge_report_at_the_end`) may be output — an affordance — rather than behaviour;
- `RUL-jobs_change_nothing` refines `RUL-no_op_run`, a loose parent for "the job count changes nothing".

**Where it stands (2026-11-14): done for rules and invariants.** All 377 were read against that test; 124 carried
more than one obligation. Split: 110 of them, into 115 new items, each refining (or, for an invariant's mechanism,
upholding) its parent, the tests' marks moved to the part each asserts. Where a second clause only repeated another
item it was dropped and nothing made. Left whole, by ruling: "stops, having changed nothing" (one obligation; saying
why is a second); a second clause that is the scope or manner of the first; an enumeration of one record's contents.
Parents and new items were ruled 2026-11-14, three reworded and twenty given the test they lacked. Build items are not read this way (ruled). The proposals, as data, and
the script that applied them are kept outside the repository. The rationale questions below are untouched.

**When:** the conversion is done (2026-11-14); this is the once-over-the-whole-corpus pass the owner asked for — *"maybe
we can do this at the very end after the full conversion to sphinx-needs?"* (the sections were renumbered after it, 2026-11-14).

### 11. Records keyed by a fingerprint that changed with ImageMagick

**Why:** a new ImageMagick may decode a photo to a new fingerprint value (`RUL-engine_change_is_checked`). Prep
follows the value in its own records — the database and prep's log move to it, across a user's move too — and geotag's
pinned own values follow it through prep's log (`RUL-own_values_follow_new_fingerprint`, `BLD-original_values_pinned`). Geotag's other
records keyed by the old value do not: its complete log and the finalized-media record. So merge, finding a photo whose
fingerprint changed, can only leave it unmerged (`RUL-merge_rechecks_under_new_engine`), and the only remedy today is
the ImageMagick version that prepped the workspace. Found while converting merge's scope section.

**What to do:** list every record keyed by a fingerprint's value, and decide how it follows a value that changed — a step
that re-keys them, planned and journaled like any change, its records rewritten whole and what depends on them restaled
— or leave the block as the answer. Stop where the old-to-new mapping is not one to one, which would change prep's
duplicate decisions.

**When:** any time — the conversion is done; geotag's pinned values are done (`BLD-original_values_pinned`).

---

### 22. A date fallback per destination, for photos with no recorded time

**Why:** one untimed photo in photos by destination stops geotag for the whole workspace, and the only cure is to
edit its metadata outside the tool. Ruled 2026-11-16: the stop is kept for now (`RUL-untimed_photo_stops_geotag`);
letting such a photo through untimed, or giving it a time by a per-photo decision, were set aside. The way the owner
is considering instead: a date given per destination, as a position is by the folder's fallback — for scanned
photos above all, whose folder says when they were made better than any one photo can.

**Open:** what the date is (a day, a month, a year?) and how a photo carries a date that is a range, since EXIF has
no way to say a time is approximate; whether it passes down to subfolders as the position fallback does; whether it
is written into the photo or recorded only; the name such a photo is given; and what it does to a photo that has a
time of its own. Not to be built until ruled.

### 28. Finding anchors and placing photos against years of tracks

**Why:** every anchor candidate search walks every track point inside the two-day clock-error window, and the
skipped-photo reason walks them all. Measured in the review: about half a second per GPS photo at 500 000 points.
Placement was made a bisection per track; anchoring was not. Not a correctness matter. Item 13 (the track points
kept in the workspace, limited to the photos' dates) would cut it at the source.

**What to do:** index points by a coarse grid or by time window per track, behind the same functions and tests.

### 30. Measuring the human input a trip costs

**Why:** the tool promises every photo on the map with the least manual work, and nothing counts the work. Each
safety fix turns a silent guess into a question or a refusal — rightly, each time — so the promise can wear away one
question at a time with nobody seeing it. The plan counts photos by how they were placed (completeness); it does not
count what the user had to answer to get there.

**What to do:** have geotag count, per plan and carried into the summary and the archive manifest: the decisions it
asked for, by kind (timezone, clock offset, drift confirmation, photo review, folder fallback, content mismatch);
how many took effect without the user (applied themselves, kept from earlier); how many the user answered; how many
answers went stale and were asked again; and the photos each answer covered. Then photos per answer is the measure,
and a change that adds questions shows as a number.

**Open:**
- What counts as one input: a cell, a save, or a distinct value (one offset accepted for five days shown as one row).
- Whether re-runs count: a plan run three times while the user answers is one trip's work, not three.
- Whether a refusal that sends the user to fix something outside the decision files (a track removed, a folder
  moved) is counted, and how it is known to have happened.
- Whether the count belongs to the record (photos-25, manifest) or is a report only. With the ground-truth set of
  item 32 it becomes a regression figure: questions asked for a fixed set of trips.

### 31. Real trips as fixtures, with the person taken out

**Why:** the tests' tracks and photos are synthetic, built by the same reasoning as the code, so both agree where
both are wrong — which is how the defects of the 2026-11-14 review survived. Real trips are the cure, and the
repository is public: a raw track shows where the owner slept and walked and when, photos carry faces, device serial
numbers and owner names, and a filename or a folder name carries a place and a date.

**What to do:** a tool that turns a real workspace into a fixture that keeps what the pipeline's judgements depend
on and nothing else: metadata without pixels (a stub image carrying the tags); tracks moved as a whole by a fixed
shift in place and in time, kept exact in shape, speed, gaps and their relation to the photos; the stretches round
lodging and home cut; serials, owner, make-specific identifiers and software tags replaced, one for one, so camera
groups still form as they did; folder and file names replaced. The real set stays outside the repository.

**Open:**
- Whether a shift is enough: a track's shape names its city to anyone who looks. Rotation or mirroring would hide
  it and keeps distances; it breaks nothing the code reads except the timezone a place implies, which is given by
  hand anyway.
- Which tags a stub must carry for prep and geotag to treat it as they treat the original, and whether the content
  fingerprint can be honest on a stub (it is of the pixels).
- Whether shifting time keeps DST and day boundaries where they were: a shift of whole weeks does, of hours does not.
- Who checks a fixture before it is committed, and against what list.

### 32. A ground-truth set, and a harness that scores against it

**Why:** 1195 tests show the code does what the corpus says. None shows the corpus yields the right time and place:
whether a value written is the true one has no oracle. Thresholds are tuned by argument, and a regression in
inference shows nowhere. The corpus guards the how; this is the missing guard on the what.

**What to do:** keep a set of real days with the answer known — the camera's true clock offset (a photo of a clock
showing seconds, morning and evening), photos carrying a trusted position that is hidden from the run and then
compared with where the tracks put them, and a second logger held out the same way. A harness runs plan on each
day and scores: offset error, position error by method (point, between two, past an end), photos placed and left
unplaced, wrong auto-applied offsets (the figure that must be zero), and the questions asked (item 30). The scores
are kept, so a change to a threshold or to the inference is read as a difference, not argued.

**Open:**
- Where the set lives: the real one cannot be in the repository (item 31); the harness can, run against a path.
  Whether a depersonalised copy runs in CI.
- The first days: the London trip of late 2026 — museums, a castle, a train out and back, two loggers — recorded
  for this on purpose. One trip is one sample: thresholds tuned on it alone fit London.
- What is scored as wrong: a position within the track's own error is right; the bound needs a figure.
- Whether a threshold change must show its score before it is ruled.

---

*Items 35 to 46 come from the adversarial review of time handling, 2026-11-14 (33, 34 and 41, from the same review, are ruled and built). Each is a choice between behaviours:
none is coded until ruled. What the review found that was plainly wrong was fixed with it.*

### 40. A destination has one timezone — and where a trip's is asked

**Why:** the corrected time is written, and the file named, in the destination's local time (`RUL-corrected_time_written_local`),
for the reason that a morning market should read as morning. A phone photo taken at the home airport and filed
under Japan has a correct local time replaced by Japan's: the rule defeats its own reason. No item says a
destination has exactly one zone, or what a folder for a drive across a zone line does. Separately: a container
never waits, so `Japan/{Kyoto, Tokyo, Nara}` asks three times unless the user knows to answer on the folder that asks
nothing — against *"one answer per trip, at the trip's folder"* (`RAT-home_zone_offered`).

**Ruled 2026-11-14:** one zone per destination, whatever a photo records (`RUL-destination_has_one_timezone`); a photo
recording another offset stops the zone until the user moves it, picks its zone or confirms the destination's.

**Open:** ask a missing zone once, at the topmost destination that neither has nor inherits one.

### 53. Videos sorted into destinations, and geotagged

**Why:** videos stay in videos by date, never sorted, so geotag gives them no place and no corrected time: their
names keep the camera's clock (stated as final by BACKLOG 43), they carry no position, and merge leaves them out of
the library. A trip's videos are as much the trip as its photos. The owner wants them sorted into destinations and
geotagged as photos are (2026-11-16).

**Ruled 2026-11-16 (the shape; to be built with the London trip's videos as test data):**
- Sorted beside the photos, in the same destination folder: `RUL-sort_photos_only` is reversed.
- MOV and MP4 only, written through exiftool's QuickTime tags; an MTS or AVI sorted into a destination stops geotag,
  its way out being to move it back to videos by date.
- A video's clock is its body's: the photos' camera group when the model and serial match, a group of its own
  otherwise.
- Its time is QuickTime CreateDate, read as UTC as the format says, with a per-camera setting for bodies that write
  local time.
- Its position is its start, as one point.
- Merge takes it into the library beside the photos.

**Open:** split into buildable items once the London trip's videos are in hand — what each step changes in prep's
sorting check, geotag's write path and merge.

### 55. Sub-second times for photos timed by CreateDate or ModifyDate

**Why:** a burst's order within one second follows the sub-second time (BACKLOG 45). Prep reads
`SubSecTimeOriginal`; `SubSecCreateDate` and `SubSecModifyDate` are in its field list, but exiftool gives them only as
Composite tags, which prep never reads — so a photo timed by `CreateDate` or `ModifyDate` gets a fraction only where
the time value itself holds one. Reading `SubSecTimeDigitized` and `SubSecTime` needs a field-set version bump, which
makes prep read every file again once.

**When:** any time; low priority.

### 47. What the country choice leaves open

**Built 2026-11-14:** a destination holding photos has one timezone (`RUL-destination_has_one_timezone`); a folder
is said to be in a country by the user, by code, from the zone database's own list (`RUL-country_gives_its_timezone`):
one timezone — given to everything inside; several — none given, none let through from above, every zone written
inside held to the country's. A country is chosen once, at the top of its tree; one chosen inside another is taken
out with a warning (`RUL-country_chosen_once`). Recognising a country by its folder's name was rejected: names are
spelt as their owner spells them, in any language.

**Open:**
- A destination under a country of several timezones could be *proposed* its zone where its photos say: the one
  zone of that country that fits the offsets its phone photos record. Today it only asks.
- A tree with no country chosen anywhere behaves as before: a zone answered on a container passes down unchecked to
  destinations of camera photos alone. Whether a zone answered on a container should itself ask "is this a country"
  where the zone belongs to a country of several.
- The wording of ruled items that speak of a trip's folder — `RAT-home_zone_offered` ("one answer per trip, at the
  trip's folder"), `RAT-decisions_cascade` ("set once at a trip's root") — and the docs' `year/country/city/location`,
  to be put in terms of places and countries.
- Regions that are not countries and span zones (an island group, a cross-border park): nothing to pick them from.
- A host whose zone database ships without `zone.tab` (some minimal images): the choice is refused there; whether
  the table should travel inside the executable.

---

---

### 49. Retake the walkthrough and every screenshot

**Why:** `docs/walkthrough.md` is a real run of v2.0.0 in thirty-nine screenshots, and the hero GIF and the shots in
`editor.md` and `concepts.md` are of the same version. The editor and the console show other things now (item 17
lists them), and the walkthrough's "Geotag won't proceed" step predates geotag running prep itself. Split from item 17
on 2026-11-14; until it is done the walkthrough carries a note saying which version it shows.

**What to do:** run a real trip through the current build and retake the walkthrough end to end, the hero GIF, and
each shot in the other guides that shows something changed; then take the note off. The London trip (item 32) is the
natural run to take them from.

**When:** after item 17's text, so the pictures are taken once.
