# photos-cartographer — what is open

*Every entry stands alone: what it is, why it matters, what blocks it.*

- **What this is:** [`README.md`](README.md). **The record:** [`HISTORY.md`](HISTORY.md).

*Open items: **42** — 2, 3, 4, 5, 6, 7 and 11 to 46.* 🛑 Numbers are never reused; the next is **47**.

---

## Open

### 2. The gap audit — the build against its spec

**Why:** Vasile: *"I am sure the build has some stuff not specced, and there may be stuff specced not built or
incorrectly built."*

**What:** walk the code and the corpus against each other: code behaviour with no
build item (**unspecified**), an intent or build item with no code or no test (**specified, not built**), code that
contradicts its item (**built wrong**). Each finding becomes its own backlog item. 🛑 **A gap is raised, ruled and
written into the spec first, then coded** — the code is never taken as the answer.

**Where it stands:** the conversion (done 2026-11-14) checked every section against the code as it went, so the
direction "specified, not built / built wrong" has had one full pass, its findings fixed. Left: the other direction —
walking the code for behaviour no item states.

---

### 3. The 7 rules no test is asked to verify

**Why:** seven rules are marked `verify: none` — specified, and nothing checks them. Two are **high**:
`RUL-rewrite_in_place_atomic` (an interrupted in-place write leaves the intact original or the whole new file) and
`RUL-stale_takeover_conservative` (only a lock whose owner is provably gone is reclaimed). The rest:
`RUL-camera_classes_not_derivation`, `RUL-control_directory_fixed`, `RUL-filesystem_agnostic`,
`RUL-image_never_working_data` (med) and `RUL-nothing_built_from_merge_records` (low). (Carried over from the clause
index's 37 clauses with no test, most of which a test has asserted since.)

**Do:** a dedicated test for each, marking it `verify: required`, or a ruled reason it needs none.

---

### 4. The 17 rules and invariants only incidentally tested

**Why:** seventeen are marked `verify: incidental` — exercised by tests written for something else, a happy path passing
through them, nothing asserting them, so a regression there passes CI. Five are **high**: `INV-change_only_what_needs`,
`INV-every_change_from_the_record`, `INV-undisturbed_shape`, `RUL-operations_atomic`, `RUL-split_move_never_lost`;
`tools/spec-build`'s `needs.json` lists the rest by their `verify` field.

**Do:** as item 3 — a test that asserts each, or a ruled reason.

---

### 5. The commit-msg hook — publish it, or keep it local

**What:** `.githooks/commit-msg` rejects a commit whose message credits Claude/Anthropic. It is active in this clone,
kept out of the repo by `.git/info/exclude`; the branch `origin/chore/commit-msg-no-ai-attribution` (2026-06-27, one
commit) would add it to `main`.

**Question for Vasile:** merge the branch (the hook then guards every clone), or keep it local and delete the branch?

---

### 6. Check a phone's time against the tracks

**Why:** geotag trusts a phone's clock — a phone takes its time from the network — and resolves each phone photo from
its own offset tag, or failing that from the destination's timezone, with nothing checking it. A phone set to the wrong
zone, a photo whose offset tag is missing while the phone sat in another zone, or a phone's clock that did drift, would
pass unseen and misplace every such photo on the track. Vasile wants the check built.

**What exists:** four settings in the default configuration that nothing reads: `phone_gpx_agreement_tolerance_seconds`
(60), `phone_gpx_conflict_threshold_seconds` (300), `phone_gpx_max_distance_meters` (250) and
`dst_conflict_tolerance_seconds` (120). Configuration loading checks they are numbers; no spec names them. Their names
suggest the shape: where a phone photo carries its own position and a track covers it, compare the photo's time with
the track's time at that position.

**Open:** what the check does on disagreement — inside the agreement tolerance pass silently, beyond the conflict
threshold block or ask, between them warn? — and what the daylight-saving setting guards. To be settled with Vasile
before it is specified.

### 7. One obligation per item, checked by reading

**Why:** every corpus item states one obligation, and `tools/spec-build` refuses an item with more than one SHALL. But
the count cannot see a second obligation folded into one sentence: in the pass that made every item one SHALL, about 90
items had a restating second SHALL reworded into the first, and some of them still carry two obligations under one
SHALL — `RUL-lock_fail_fast`, for one, stops at once, says the workspace is locked and produces nothing;
`RUL-replanning_keeps_the_prior` sets the saved plan aside and tells the user where; `RUL-no_plan_no_run` stops and
tells the user to plan first. From §4's structure: `RUL-structure_built_once`, `RUL-top_level_only_managed`,
`RUL-first_dump_at_top_level`, `RUL-link_named`, `RUL-geotag_merge_check_top_level_links`, `RUL-missing_folder_blocks`,
`RUL-missing_folder_named`, and `RUL-no_links` with its four cases. From §5's camera groups:
`RUL-prep_derives_camera_group` (derive the group, record it in two places) and `RUL-camera_group_derivation_versioned`
(carry a version, have it checked). From §6's filename format: `RUL-one_filename_format` (one format, set by the
configuration, hard-coded by neither phase), `RUL-suffix_no_clobber` (zero-padded, deterministic, compared without
regard to case, checked against the names on disk and those planned), `RUL-prep_name_provisional` (the raw timestamp,
for ordering only, never corrected) and `RUL-geotag_name_final` (work out the final name, rename to it). From §7's tracks: `RUL-tracks_geotag_only` (what
geotag alone does with the tracks, and what prep never does). From §9's loop: `RUL-sort_photos_only` (only photos, and
geotag refuses otherwise), `RUL-rerun_does_what_changed` (exactly what changed requires, and asks only about what is
affected), `RUL-merge_is_terminal` (merge comes last, new media goes to a fresh workspace) and
`RUL-more_dumps_until_merge` (a dump is accepted, the loop resumes from prep). Vasile caught
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

**When:** the conversion is done (2026-11-14); this is the once-over-the-whole-corpus pass Vasile asked for — *"maybe
we can do this at the very end after the full conversion to sphinx-needs?"* — after item 12's renumbering.

### 11. Records keyed by a fingerprint that changed with ImageMagick

**Why:** a new ImageMagick may decode a photo to a new fingerprint value (`RUL-engine_change_is_checked`). Prep
follows the value in its own records — the database and prep's log move to it, across a user's move too — and geotag's
pinned own values follow it through prep's log (`RUL-own_values_follow_new_fingerprint`, geotag §24.2). Geotag's other
records keyed by the old value do not: its complete log and the finalized-media record. So merge, finding a photo whose
fingerprint changed, can only leave it unmerged (`RUL-merge_rechecks_under_new_engine`), and the only remedy today is
the ImageMagick version that prepped the workspace. Found while converting merge §2.

**What to do:** list every record keyed by a fingerprint's value, and decide how it follows a value that changed — a step
that re-keys them, planned and journaled like any change, its records rewritten whole and what depends on them restaled
— or leave the block as the answer. Stop where the old-to-new mapping is not one to one, which would change prep's
duplicate decisions.

**When:** any time — the conversion is done; geotag's pinned values were done with geotag §24.2.

---

### 12. Number the phase documents' sections 1…n, and cite items, not sections

**Why:** the phase documents of the corpus (`spec/intent|rationale|build/{prep,geotag,merge}.md`) number their headings
as in the phase's original spec, so a section with no items of its own has no heading and the numbers skip — `intent/
geotag.md` holds §2 and §5 only. The numbers were the way back to the original documents while they were converted;
those are retired now (kept at the tag `specs-before-corpus`), and the numbers only puzzle a reader. Some 640 comments
in the code and tests, and 74 places in the corpus's own items, cite those original sections — "geotag §24.2" — whose
sub-sections the corpus does not have. Vasile: *"1 now, and add a step (or backlog) after the conversion to renumber."*

**What to do:** renumber each phase document's sections 1…n, the same number for the same section across intent,
rationale and build; rewrite every citation of a section — in the build items, the code and the tests — to the id of
the item it means (`BLD-resolved_utc`), which no renumbering moves; drop the explanatory sentence from each
document's introduction.

**When:** now — the conversion, its philosophy pass included, is done (2026-11-14).

### 13. Keep the track points geotag used in the workspace, sealed with it

**Why:** every `geotag plan` reads every track file under `gpx_root` whole, to hash it, and keeps the parsed points
only in the scratch track memo, which is neither archived nor sealed. The sealed workspace records the GPX fingerprint
and, per photo, the name of the track that placed it — not the points — so once `gpx_root` changes or is gone, the
evidence behind a placement or a clock offset can no longer be seen. Vasile: *"I will have always the gps data used
during the process, in the form used during the decisioning, which would make the workspace truly self-contained."*

**What to do:**

- A geotag region of `photos-00-ingest.db` — the one record database, snapshotted into the archive at finalize and
  merge, so sealed with the workspace — holding a catalogue of every track file under `gpx_root` (path, size,
  modification time, SHA-256, first and last point time) and the points that fall in the window, as decided on (UTC
  time, latitude, longitude, file, index). It replaces the scratch track memo.
- Refresh on every run by size and modification time, as prep's plan memo does: an unchanged file is not read; a new
  or changed one is read and parsed; one gone is dropped **with a warning naming it** — the one reason to take a track
  out is that it records someone else's trip at the same time, and the user should see that it went.
- The window: the union of a window around each photo day — of the photos in photos by destination with a recorded
  time — with a margin of at least `gpx_anchor_max_clock_error_seconds` (2 days by default) each side, since offset
  inference looks that far from a camera's time; and, once `photos-21` is complete, a window around each photo's
  corrected time too, since placement uses it and a manual real time can lie far from the camera's. Sorting photos in,
  or new tracks under `gpx_root`, grows it.
- The GPX fingerprint becomes the hash of the points in the window, so tracks added for another time restale nothing.
- Rule it: this reverses the ruled "every track file is read whole on every run" (geotag §15, `BLD-idempotency`).

**When:** any time — the conversion is done.

### 14. Propose a destination's timezone from its photos' positions

**Why:** a destination's timezone is proposed only from the destination it lies in, or from the configured default
(`RUL-timezone_from_nearest`). The photos' own positions — native GPS, or placed from the tracks — say where they were
taken, and so which timezone; geotag §18 described this as the first of the proposals, never built. A trip's root
would then need no zone set by hand, and a destination that crosses into another zone than its parent's would be
caught.

**What to do:** derive a zone from the positions of a destination's photos — through a timezone-boundary database, a
new dependency — and propose it ahead of the inherited one, with a `proposal_source` of its own; decide whether such a
proposal applies itself like the inherited one, or waits for acceptance, since unlike the tree it can disagree with
the parent's zone.

**When:** any time — the conversion is done.

### 15. Split a day's clock offset where the camera's clock changed

**Why:** geotag keeps one clock offset per camera, destination and day (`RUL-offset_per_camera_destination_day`). A
camera whose clock is changed during the day at one destination — reset, or set to local time at lunch — has two
offsets that day, and no single one fits: its anchored photos split into two groups, one of them reported as agreeing
with none (`conflicting_files`). Today the editor tells the user to read the pattern and, for this one, move the photos
after the change into a sub-folder and re-run prep — changing the folder tree, and so the library, only to work around
the limit. That advice is a stopgap; this item replaces it.

**What to do:** when the photos disagreeing with the agreed offset form one run in time at the start or end of the
day, propose splitting that day's cell at the change: two offsets, each anchored from its own photos. The photos
without GPS between the last of one run and the first of the other are the one ambiguity; the editor asks which was
the first after the change. Rule the change to the per-day model first.

**When:** any time — the conversion is done.

### 16. Photos whose own position the agreed clock offset contradicts

**Why:** a photo with a native GPS position that agrees with none of its camera's anchor groups (`conflicting_files`),
scattered among photos that agree, most likely carries a wrong position of its own — GPS jitter, a fix from minutes
before, a position another program wrote. Geotag never changes a photo's own position, so accepting the agreed offset
corrects its time and leaves the wrong place in it; the editor can only tell the user to read the pattern and fix it
by hand elsewhere. Together with item 15, the user would no longer interpret the disagreeing photos at all.

**What to do:** have geotag tell the two cases apart itself — a run at one end of the day is item 15's clock change,
scattered photos are suspect positions — and for each suspect one, compare its own position with the track's at its
corrected time; where they differ beyond the anchor distance, raise it as a GPS review item in photos-23, the track's
position proposed, the photo's own kept unless the user takes the proposal. Rule first that a photo's own position may
be replaced this way, on the user's answer only — today it never is (`RUL-own_position_kept`) — and drop the editor's
interim advice once both items are built.

**When:** any time — the conversion is done; with or after item 15.

### 17. Redo the user docs, the walkthrough and its screenshots

**Why:** the conversion changed what the user sees and does, and the user docs (`docs/`) and the walkthrough's
screenshots were left as they were until it finished — Vasile: *"I'd just leave it and redo everything that needs
changes when I finish the conversion."* Among the changes: geotag stops on an untimed photo in photos by destination,
and runs prep itself when the inbox is empty; a trip's timezone is answered once, the configured default only offered;
`accept_proposed_timezone` and `manual_real_utc` are gone; a tie between visits, a picked GPS group and a drift
confirmation that holds only for its offset show in the editor; track positions are marked `matched`, `interpolated`
or `extrapolated`; execute stops on a photo edited since the plan, and finalize on a plan no longer current. The
walkthrough's "Geotag won't proceed" step predates geotag running prep itself. From the review of 2026-11-14: an
accepted offset names the offset it accepted and asks again when the proposal changes; a stay of the tracks is said
to fix no time, and its offset goes through the drift check; a photo the tracks did not place says why; tracks that
disagree are warned of; a tracks folder that is not there stops `geotag plan`; finalize prints how every photo was
placed and refuses photos changed since execute.

**What to do:** walk `README.md`, `docs/quickstart.md`, `concepts.md`, `editor.md`, `walkthrough.md` and
`who-is-this-for.md` against the corpus and the code; retake every screenshot that shows something changed, and the
hero GIF if it does.

**When:** now — the conversion is done.

### 18. Merge: check the free space before moving into another filesystem

**Why:** a merge into a library on another filesystem copies each photo before removing it from the workspace. Safety
holds — a full disk fails the one photo, which stays in the workspace, and the run ends `partial` — but nothing warns
before the run that the library cannot hold the batch, so the shortage shows late, one photo at a time. (Found in a
risk review of 2026-06-21; the other half of that finding — temporary copies a hard crash leaves in the library — is
done: merge clears them as its execution starts.)

**What to do:** decide whether merge's plan, or its execute before any move, checks the library's free space against
the batch's size and stops or warns; rule it into the spec, then code it.

**When:** any time; low priority.

### 19. Record the conversion's changes and cut the next release

**Why:** since v2.0.0, the conversion finished geotag and retired the original specs, and changed behaviour on the way
— offsets matched to the right day of a revisited place, a phone's time read by the offset of its own field, files
naming no camera solved alone, a drift confirmation bound to its offset, edits since the plan never written over, the
configured default zone only offered, a fingerprint's new value keeping its pinned values, among others — and removed
two decision fields (`accept_proposed_timezone`, `manual_real_utc`). The review of 2026-11-14 added one,
`accepted_offset_seconds` (an `accept_proposal` without it is now a blocker), made a missing `gpx_root` stop the plan,
reads each track file as a track of its own, and changed the journal (`media_after`) and the plan (`placement`,
`left_unlocated`). None of it is in `HISTORY.md`, and the work is on
the branch `spec-corpus-sphinx-needs`, not on `main`; the tag `specs-before-corpus` is local.

**What to do:** write the `HISTORY.md` entry, refresh `COVERAGE.md`, open the pull request to `main` and, once merged,
tag and publish the release — its version decided then (a workspace decided under the removed fields carries values
nothing reads now).

**When:** once Vasile chooses to release.

### 20. Zone-resolved times of phones and camera-less files are assumed, never asked

**Why:** a camera's "clock was on local time" is a proposal the user must accept, and is then checked against the
tracks. The same assumption is applied silently to a phone photo with no offset tag, to a file naming no camera, and to
a corrected photo whose offset tag is gone — and those photos are then placed on the tracks by it. Two cases make it
wrong by an hour with nothing shown: a local time that occurred twice (the hour daylight saving repeats — the first is
taken) and one that never occurred (the hour it skips). Found in the review of 2026-11-14, confirmed for Europe/Berlin.
Close to item 6, which checks a phone's time against the tracks where it has its own position.

**Open:** whether such photos get a decision of their own (per destination and group: "these N photos carry no offset —
read them as local time?"), ride the drift check, or stay as they are with a warning; and what an ambiguous or
impossible local time does — ask, or block naming the photo. To be ruled before it is specified.

**Added by the time review of 2026-11-14:** the first-occurrence choice in a repeated hour is also made in a
camera's timezone-derived proposal, with nothing in the proposal marking it ambiguous. A phone time in the hour a
zone skips (02:30 on a spring-forward night) is moved an hour, silently. An offset tag that is present and is not an
offset is now read as none — strictly — and the photo then falls to the zone like one with no tag, indistinguishable
in the plan; the log's `time_written` step now names the rule (`destination_timezone`), which is where the
assumption can be seen after the fact.

### 21. Let the user leave one photo unlocated in a folder that has a fallback

**Why:** the placement order puts a destination's fallback above a photo's own `accept_unlocated`, and a photo the
fallback or a track places has no review item — so "leave this one without a position" cannot be said for it, and an
answer given earlier is dropped once a fallback or track covers the photo. The rationale ranks sources by how specific
they are, and the photo's own answer is the most specific there is.

**Open:** whether a per-photo answer outranks the folder's fallback (and a track?), and how the editor offers it for a
photo that is not on the worklist.

### 22. A photo with no recorded time has no way through geotag

**Why:** one untimed photo in photos by destination stops geotag for the whole workspace, and the only cure is to
edit its metadata outside the tool. The promise is every photo on the map, "rough or manual" — a scan could be given
a position by hand or by its folder's fallback and keep its name. The rationale says only that no phase invents a
time, not why a position cannot be set without one.

**Open:** let such a photo be placed by the user or the fallback and left unrenamed; or give it a time decision; or
keep the stop. To be ruled.

### 23. A day's shoot split by the camera's own midnight

**Why:** a cell is a camera's day by its own clock. A camera left on home time abroad, or a night shoot, has its
midnight mid-shoot: the outing becomes two cells, the half without an anchor asks for its offset and then for a
drift confirmation, though the other half of the same outing settled both. Close to item 15 (a clock changed
mid-day), from the other side.

**Open:** whether adjacent days of one camera in one destination with a small gap between their photos are offered
the neighbour's offset — a proposal, to accept — or decided as one. To be ruled.

### 24. A device position that is not a fix

**Why:** a photo counts as having its own position when it has a latitude and a longitude. One at (0, 0), or far
from everything else the camera did that day, is kept as the photo's own, never offered for placement, counted as
placed, and used as an anchor. Item 16 covers positions the agreed offset contradicts; this is the position that is
wrong on its face.

**Open:** what marks a position as no fix (null island; out of range is refused already), and what then — treat the
photo as having none, or ask.

### 25. A photo that cannot be written holds the whole workspace

**Why:** a photo exiftool will not write (a damaged file, a format it reads and cannot write) fails every run; the
execution stays `partial`, and finalize is refused for every other photo. Nothing names the way out — moving the
photo out of photos by destination and running prep and the plan again.

**What to do:** have execute's output and the summary say so for a photo that fails twice the same way; decide
whether the user can instead accept it as it is, which would be a new decision to record.

### 26. What geotag leaves in the other time fields

**Why:** geotag writes `DateTimeOriginal` and `OffsetTimeOriginal`. `CreateDate`, `ModifyDate` and their offsets
keep the camera's uncorrected time, so a corrected photo holds times that disagree, and a program that reads
`CreateDate` shows the old one. No item decides it.

**Open:** write them all to the corrected time, leave them (they are the camera's record), or clear the offsets that
no longer hold. digiKam's reading order decides how much it matters.

**Added by the time review of 2026-11-14:** a real write leaves `XMP:DateCreated` and `IPTC:DateCreated` with the
old time and old offset, and `SubSecTimeOriginal` attached to the new second, so the composite sub-second time reads
as the new second with the old fraction.

### 27. Durability of the control files across a power cut

**Why:** records and journals are written to a temporary file and renamed into place, without being flushed to the
disk first. After a power cut a journal can be empty — read as "nothing applied", which the next run now repairs by
finding the photos done — and a torn `photos-24` is an unhandled error rather than a message. The editor's save of
the three decision records is not all-or-nothing, and keeps no copy of what it replaces.

**What to do:** flush before the rename where a record is the only copy of a decision; make a torn plan a plain
"re-run `geotag plan`"; decide whether the editor's save sets the earlier records aside as a re-plan does.

### 28. Finding anchors and placing photos against years of tracks

**Why:** every anchor candidate search walks every track point inside the two-day clock-error window, and the
skipped-photo reason walks them all. Measured in the review: about half a second per GPS photo at 500 000 points.
Placement was made a bisection per track; anchoring was not. Not a correctness matter. Item 13 (the track points
kept in the workspace, limited to the photos' dates) would cut it at the source.

**What to do:** index points by a coarse grid or by time window per track, behind the same functions and tests.

### 29. Which track is trusted first, by the device that recorded it

**Why:** Vasile records each trip twice — a standalone receiver and the phone — and the phone turns out the more
accurate. *"I want the device track to be used when phone track unavailable."* Today no track outranks another: where
both cover a photo's time the one whose nearest point is closer in time wins, whichever device it came from, and
where they lie farther apart than `gpx_tracks_agree_max_distance_meters` the photo is not placed at all. So the less
accurate track places photos the better one covers, and two tracks of one person can be read as two people.

**What to do:** let a track carry its provenance and the configuration rank provenances; where tracks overlap, the
highest-ranked that places the photo wins, and a lower one is used only where no higher one places it. The same
ranking would settle which track anchors a clock offset. The placement already records the track file used; it would
record the provenance and that a higher-ranked track was absent.

**Open:**
- How a track's provenance is known: the GPX `creator` attribute, a subfolder of `gpx_root`, a filename pattern, or
  a list in the configuration. The file's own `creator` needs no filing discipline but is whatever the app wrote.
- What "unavailable" means for the preferred track: no file for the time, or a file that cannot place the photo — a
  gap, a jump, only a projection past its end. Whether a lower-ranked track's point at the photo's time beats a
  higher-ranked track's interpolation or projection.
- Whether ranked tracks that disagree still place nothing (one of them is wrong, and the rank says which to
  believe), or whether disagreement stops a photo only between tracks of equal rank — keeping the guard for a
  second person's trip.
- Whether a disagreement between the two own devices is reported, as a measure of the lower one's error.
- Whether a preference is a decision of the workspace (recorded with the plan, restaling photos-21 to 23 when
  changed) — it should be, like every other setting that changes what is written.

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
repository is public: a raw track shows where Vasile slept and walked and when, photos carry faces, device serial
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

*Items 33 to 46 come from the adversarial review of time handling, 2026-11-14. Each is a choice between behaviours:
none is coded until ruled. What the review found that was plainly wrong was fixed with it.*

### 33. An inherited timezone applies itself against the destination's own photos

**Why:** a zone set on a trip's folder is inherited by every destination under it with no question
(`RUL-timezone_auto_resolves`). `Trip/{Lisbon, Porto, Madrid}`: Madrid inherits Lisbon's zone though every phone
photo there records +02:00. The phone's instants stay right; their written local time and name are an hour off the
wall clock, and a camera's timezone-derived proposal there is built on the wrong zone. The one zone change of a trip
is the one thing never asked.

**Proposed rule:** an inherited timezone SHALL NOT take effect without the user's answer in a destination holding a
photo whose own recorded offset differs from that timezone's offset at the photo's time.

**Open:** ask, or propose the zone the photos' offsets imply; how many photos must disagree; relation to item 14.

### 34. One camera's day sorted into several destinations is decided several times

**Why:** an offset is per camera, destination and day, drawn only from that destination's evidence
(`RUL-offset_from_own_evidence`). The philosophy says the opposite — *"a clock offset is the camera's for that day,
wherever its photos were sorted"* (`RAT-decisions_cascade`). Museum in the morning, castle in the afternoon: the
museum's cell is anchored at −3 h 02 min, the castle's has no anchor and proposes −2 h from the zone; both accepted,
one clock on one day is written two ways an hour apart, and nothing flags it. The same holds for day two proposing a
value day one's drift check disproved.

**Open:** check only (two offsets of one camera-day farther apart than offsets are told apart may not both take
effect unasked), or also offer the sibling's offset as the proposal — which reverses a ruled rule and removes most of
a trip's questions.

### 35. The time a camera's own GPS recorded is not used as evidence of its clock

**Why:** a native-GPS photo carries the fix's UTC (`GPSDateStamp`, `GPSTimeStamp`); prep reads them, geotag does
not. With no track covering it the cell falls to the zone guess and a question, though the photo states its own
offset. The same evidence would settle phone photos with no offset tag (item 20) and give item 6 its check.

**Open:** a stale fix (a camera reusing its last fix) gives a wrong time — what bounds it; whether such an offset
applies itself as one agreed by several anchors does.

### 36. A camera photo's own recorded offset is ignored

**Why:** a recent body left on home time writes `OffsetTimeOriginal` +01:00 in Japan. The timezone-derived proposal
is built from Japan's zone, eight hours wrong, and offered as the default answer; the tag that says which zone the
clock was on is read only for phones. `TimeZone` is carried into the file model and read by nothing.

**Open:** derive the unanchored proposal from the recorded offset where the camera's photos carry one; what when they
disagree with each other or with a GPS anchor.

### 37. A drift confirmation outlives the tracks it was made against

**Why:** an offset that applied itself rests on its tracks (`RUL-kept_offset_rests_on_its_tracks`); one the user
confirmed by scrubbing a photo along a track does not. That track removed as a companion's and another added, the
confirmation still stands and the day is placed on a track nobody looked at.

**What to do:** the confirmation names the tracks it was made against, as it names its offset — written by the
editor with the confirmation — and holds only while each is there unchanged. Not a choice of behaviour; it needs the
editor to write it, which is why it was not done with the review.

### 38. A time read from the modification or digitisation field is taken for the camera's clock

**Why:** an export whose `DateTimeOriginal` is gone keeps its make and model and a `ModifyDate` written by the
editing computer. It joins the camera's group, its edit date opens a day of its own — a new question — and the
camera's offset is applied to a computer's clock.

**Open:** solve such a photo on its own, never by the camera's offset nor counted in its days; or treat it as
untimed (item 22).

### 39. Two bodies in one camera group

**Why:** two bodies of one model that write no serial are one group. Both with GPS: their anchors disagree for good
and no one offset is right. Only one with GPS that day: its agreed offset applies itself to the other body's photos.
Item 16's planned reading of scattered photos as suspect positions would then propose replacing the second body's
correct ones.

**Open:** a group whose key carries no serial never has an offset from its GPS apply itself; or the user declares a
group split.

### 40. A destination has one timezone — and where a trip's is asked

**Why:** the corrected time is written, and the file named, in the destination's local time (`RUL-corrected_time_written_local`),
for the reason that a morning market should read as morning. A phone photo taken at the home airport and filed
under Japan has a correct local time replaced by Japan's: the rule defeats its own reason. No item says a
destination has exactly one zone, or what a folder for a drive across a zone line does. Separately: a container
never waits, so `Japan/{Kyoto, Tokyo, Nara}` asks three times unless the user knows to answer on the folder that asks
nothing — against *"one answer per trip, at the trip's folder"* (`RAT-home_zone_offered`).

**Open:** one zone per destination whatever a photo records, or a photo with its own offset keeps its own local
time; ask a missing zone once, at the topmost destination that neither has nor inherits one.

### 41. The same offset is asked twice

**Why:** a camera with no GPS and tracks nearby needs its timezone-derived offset accepted (photos-21) and then
confirmed against the tracks (photos-22): two stages, two runs, one number. The confirmation is the stronger act and
names the offset itself. The review counted a typical trip — one camera, one phone, three days, a zone change — at
eight prompts against a floor of about four; three of the eight are these acceptances.

**Open:** ask once, at the check against the tracks, where tracks cover the photos; keep the acceptance where none do.

### 42. A clock reset to its factory date is proposed like any other

**Why:** battery out, camera at 2000-01-01. No anchor is possible; the cell proposes the timezone-derived offset,
acceptable in one answer, which writes the year 2000 into the originals as corrected. The drift check now asks where
tracks lie by the camera's recorded times, which a reset clock's do not. The right answer is a count of seconds over
26 years, worked out by hand.

**Open:** a proposed offset leaving a cell's photos farther than the largest clock error from every track and every
other device's photo of the destination does not take effect on acceptance alone; let the user give the true time of
one photo instead of an offset.

### 43. Videos and set-aside JPEGs keep the uncorrected clock in their names

**Why:** geotag changes photos by destination only, never a video (`RUL-geotag_changes_only_by_dest`). A camera on
home time: its photos are named in destination-local time, its videos of the same minutes eight hours away, and a
RAW no longer shares its name with its set-aside JPEG. No item says the provisional name is final for them.

**Open:** say so, or correct those names from the camera-day's settled offset — a rename, no tag written.

### 44. A time corrected by hand after geotag wrote it is planned back

**Why:** geotag decides from the values pinned before its first write. A user who then fixes the photo's time in
another tool finds, after the next plan, a write putting geotag's value back — now logged with what it replaces, but
neither asked nor refused.

**Open:** a held time that is neither the pinned original nor what geotag wrote blocks, naming the photo; or is taken
as the photo's new recorded time.

### 45. Order and pairs among photos of one second

**Why:** suffixes are given in path order, and `-` sorts before `.`: `T.jpg, T-001.jpg, T-002.jpg` become
`T'-002.jpg, T'.jpg, T'-001.jpg` on geotag's rename, a burst's order rotating, and a RAW can land beside another
frame's JPEG. Sub-second times are read by prep and used nowhere. Two smaller things of the same kind: a filename
format holding `%z` reads differently in prep and geotag, and names in the hour a zone repeats sort against true time.

**Open:** order by sub-second then the suffix already held, one suffix across the extensions of a stem; refuse a
format whose fields read differently with and without a zone.

### 46. Corrected means resolved, so every original is written

**Why:** a phone photo already holding the right local time and its own position gets no time written — and still
gets geotag's mark in `GPSProcessingMethod`, because a time counts as corrected once resolved. Every original is
touched; "corrected" is defined nowhere.

**Open:** define it as resolved (state it), or mark only a photo whose time geotag changed and recognise the others
on a re-run by their unchanged values.
