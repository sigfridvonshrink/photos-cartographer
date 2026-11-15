# photos-cartographer — what is open

*Every entry stands alone: what it is, why it matters, what blocks it.*

- **What this is:** [`README.md`](README.md). **The record:** [`HISTORY.md`](HISTORY.md).

*Open items: **28** — 2, 6 to 7, 11, 13 to 16, 18, 20 to 23, 25, 27, 28, 30 to 32, 35, 39, 40, 43, 45 to 49.* 🛑 Numbers are never reused; the next is **50**.

---

## Open

### 2. The gap audit — the build against its spec

**Why:** The owner: *"I am sure the build has some stuff not specced, and there may be stuff specced not built or
incorrectly built."*

**What:** walk the code and the corpus against each other: code behaviour with no
build item (**unspecified**), an intent or build item with no code or no test (**specified, not built**), code that
contradicts its item (**built wrong**). Each finding becomes its own backlog item. 🛑 **A gap is raised, ruled and
written into the spec first, then coded** — the code is never taken as the answer.

**Where it stands:** the conversion (done 2026-11-14) checked every section against the code as it went, so the
direction "specified, not built / built wrong" has had one full pass, its findings fixed. Left: the other direction —
walking the code for behaviour no item states.

**Found and ruled (2026-11-14):** eight behaviours the code had and no item stated, met while citations were
rewritten to item ids. Six are items now, each with its test — `RUL-write_leftovers_quarantined`,
`RUL-write_leftovers_by_dest_warned`, `BLD-database_effects_one_transaction`, `RUL-log_step_names_run` (merge's
steps did not name their run; they do), `RUL-records_written_alike`, `RUL-handoff_read_back`,
`RUL-inbox_non_media_never_blocks`; `RUL-prep_run_summarised` speaks of the plan as well as the execution; the
editor's note of frames left out of a proposal is in `docs/design/decisions.md`.

**The walk (2026-11-14):** every function of the three phases, the calculation layer and the shared library was read
against the corpus, some ninety-five findings. Done since, needing no ruling: the fourteen places where the code
contradicted a ruled rule are fixed, each with a test (a failed execute rolls its database effects back; merge never
moves or removes a photo changed after the plan, and one photo's error blocks it alone; the console judges a plan
by the workspace's own configuration and its editor tab holds to the editor's rules; exiftool gets its two attempts;
a plan's existing snapshot counts as taken; the seal is checked before the workspace is walked), and the dead code
is removed.

**Ruled and built (2026-11-15) — safety:** the thirteen matters of safety the walk found are rules now, each
built and tested: a photo with no fingerprint stops geotag and merge; a fingerprint covers every frame and every
stream, and one of another method is never compared; the same picture in a library file of other bytes blocks,
neither removed (*"if library copy is same pixels, stop and let user sort"*); the user's own `_original` backup is
a stray; a hidden folder holding files stops prep, and any hidden entry among the photos stops merge; each `<trk>`
is a track and a `<trkseg>` break is never bridged; a time a daylight-saving change skips or repeats is never
guessed; geotag runs prep itself only where prep's plan touches no media; pruning by age takes a day or more; a
library lies outside every workspace; an earlier place counts only inside the library now configured; the editor
saves only over what it loaded; tracks none of which can be read stop geotag.

**Awaiting ruling — the rest**, each a behaviour to state as it is, change, or drop:
- *decisions:* a photo moved to another destination loses its own position decision; exiftool's absence stops
  finalize, which never runs it; a handoff of another field-set version is refused; a development subfolder is
  matched with case; an unvouched prep log is passed over at plan; the `+carto-time` mark is written to a photo
  whose time was already right; a merge of no photos seals; ImageMagick's absence is a warning for merge;
  `init-library <path>` rewrites the whole configuration file; a media file whose metadata read failed blocks, in
  photos by destination too; the first run renames a dump file whose inbox path is taken; the console's editor tab
  holds the editor lock until the console stops.
- *records:* when geotag's summary and merge's are not written (a refusal, an interrupt); an unreadable journal or
  earlier pass is taken as empty; photos-25 and the photos-26 package are replaced in place; prep takes an
  unreadable log for none and writes over an unreadable quarantine manifest it could not set aside; a prune is
  recorded nowhere; a log entry of a photo gone from the workspace is carried as it was; every quarantine move is
  counted a duplicate; strays' paths are in the plan though `RUL-strays_leave_no_trace` says nowhere; merge's
  journal is per plan, not per run; and fields no item names — the anchor proposal's `anchors` and `anchor_count`,
  photos-23's `depends_on`, the merge log's step, the photos-35 manifest's, the handoff's `inode` (which enters its
  fingerprint), fields nothing reads (`proposal_confidence`, `camera_groups_present`, `rank`,
  `fingerprint_algorithm_version`).
- *limits:* the tolerance in recognising geotag's own interrupted write; how anchor offsets are clustered and a tie
  falls; a projection with no heading point lands on the track's end; coordinates rounded to six places; track
  times parsed as the host's Python parses them; a decode killed after ten seconds; blank camera-identity values;
  what counts as a photo's own position beyond (0, 0), which is none (`RUL-null_island_is_no_position`); one library file compared per photo; the suffix above the
  highest of library and batch (`BLD-collision_suffix` says "next free"); case-only collisions refused on every
  filesystem; a redundant JPEG paired with case; an uppercase extension left in photos by destination; and the
  exit statuses (1 locked, 2 refused, 3 partial or failed, 130 interrupted; merge's plan and dry run exit 0 with
  blockers).

**Found while the user guides were redone (2026-11-15), to be ruled or fixed:**
- the editor checks a timezone with the browser's zone list and geotag with the host's: a name one knows and the
  other does not (`US/Eastern` on a host without the legacy names) is saved by the editor and refused by the plan;
- a drift cell's `corrected_offset_seconds` that is not a number is named only once the cell is confirmed, and a
  `confirmed_offset_seconds` beside `confirmed: false` is never checked;
- `confirmed_despite_recorded_offsets: null` is a blocker, where `null` reads as "no answer" in every other field;
- when `geotag plan` runs prep itself, prep's own closing "Next:" lines print as well as geotag's — three of them,
  disagreeing, where geotag then stops;
- `BLD-offset_shared_within_day` names an offset the user chose from a group among those shared within a day, and
  also requires that no offset was written by hand — the code never shares such a one;
- `phone_gpx_agreement_tolerance_seconds`, `phone_gpx_conflict_threshold_seconds`, `phone_gpx_max_distance_meters`
  and `dst_conflict_tolerance_seconds` are still settings nothing reads, kept for item 6.

---

### 6. Check a phone's time against the tracks

**Why:** geotag trusts a phone's clock — a phone takes its time from the network — and resolves each phone photo from
its own offset tag, or failing that from the destination's timezone, with nothing checking it. A phone set to the wrong
zone, a photo whose offset tag is missing while the phone sat in another zone, or a phone's clock that did drift, would
pass unseen and misplace every such photo on the track. The owner wants the check built.

**What exists:** four settings in the default configuration that nothing reads: `phone_gpx_agreement_tolerance_seconds`
(60), `phone_gpx_conflict_threshold_seconds` (300), `phone_gpx_max_distance_meters` (250) and
`dst_conflict_tolerance_seconds` (120). Configuration loading checks they are numbers; no spec names them. Their names
suggest the shape: where a phone photo carries its own position and a track covers it, compare the photo's time with
the track's time at that position.

**Open:** what the check does on disagreement — inside the agreement tolerance pass silently, beyond the conflict
threshold block or ask, between them warn? — and what the daylight-saving setting guards. To be settled with the owner
before it is specified.

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

### 13. Keep the track points geotag used in the workspace, sealed with it

**Why:** every `geotag plan` reads every track file under `gpx_root` whole, to hash it, and keeps the parsed points
only in the scratch track memo, which is neither archived nor sealed. The sealed workspace records the GPX fingerprint
and, per photo, the name of the track that placed it — not the points — so once `gpx_root` changes or is gone, the
evidence behind a placement or a clock offset can no longer be seen. The owner: *"I will have always the gps data used
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
- Rule it: this reverses the ruled "every track file is read whole on every run" (`BLD-idempotency`).

**When:** any time — the conversion is done.

### 14. Propose a destination's timezone from its photos' positions

**Why:** a destination's timezone is proposed only from the destination it lies in, or from the configured default
(`RUL-timezone_from_nearest`). The photos' own positions — native GPS, or placed from the tracks — say where they were
taken, and so which timezone; the original geotag spec described this as the first of the proposals, never built. A trip's root
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

### 18. Merge: check the free space before moving into another filesystem

**Why:** a merge into a library on another filesystem copies each photo before removing it from the workspace. Safety
holds — a full disk fails the one photo, which stays in the workspace, and the run ends `partial` — but nothing warns
before the run that the library cannot hold the batch, so the shortage shows late, one photo at a time. (Found in a
risk review of 2026-06-21; the other half of that finding — temporary copies a hard crash leaves in the library — is
done: merge clears them as its execution starts.)

**What to do:** decide whether merge's plan, or its execute before any move, checks the library's free space against
the batch's size and stops or warns; rule it into the spec, then code it.

**When:** any time; low priority.

### 20. Zone-resolved times of phones and camera-less files are assumed, never asked

**Settled in part (2026-11-15):** a local time the zone skips or repeats at a daylight-saving change is never
resolved by the zone (`RUL-ambiguous_local_time_never_guessed`): the photo stops geotag, named with both readings,
and a camera's timezone-derived proposal at such a time is not made — the cell asks for the offset.

**Why, for what remains:** a camera's "clock was on local time" is a proposal the user must accept, and is then
checked against the tracks. The same assumption is applied silently to a phone photo with no offset tag, to a file
naming no camera, and to a corrected photo whose offset tag is gone — and those photos are then placed on the tracks
by it. Close to item 6, which checks a phone's time against the tracks where it has its own position.

**Open:** whether such photos get a decision of their own (per destination and group: "these N photos carry no
offset — read them as local time?"), ride the drift check, or stay as they are with a warning; and whether a photo
at a skipped or repeated time can be answered in the decision files rather than fixed outside them. An offset tag
that is present and is not an offset is read as none, and the photo then falls to the zone like one with no tag,
indistinguishable in the plan; the log's `time_written` step names the rule (`destination_timezone`), which is where
the assumption can be seen after the fact. The camera's proposal is checked at its cell's earliest time only.

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

### 25. A photo that cannot be written holds the whole workspace

**Why:** a photo exiftool will not write (a damaged file, a format it reads and cannot write) fails every run; the
execution stays `partial`, and finalize is refused for every other photo. Nothing names the way out — moving the
photo out of photos by destination and running prep and the plan again.

**What to do:** have execute's output and the summary say so for a photo that fails twice the same way; decide
whether the user can instead accept it as it is, which would be a new decision to record.

### 27. A torn plan, and the editor's save of three records

**Why:** every rewrite is now synced to disk before it replaces the earlier file (`BLD-rewrite_synced_before_rename`,
2026-11-14), which settles the power cut. Two things remain of this item: a `photos-24` that cannot be read is an
unhandled error rather than a message; and the editor's save of the three decision records is not all-or-nothing
across the three, and keeps no copy of what it replaces.

**What to do:** make an unreadable plan a plain "re-run `geotag plan`"; decide whether the editor's save sets the
earlier records aside as a re-plan does, and whether the three are saved as one.

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

### 35. The time a camera's own GPS recorded is not used as evidence of its clock

**Why:** a native-GPS photo carries the fix's UTC (`GPSDateStamp`, `GPSTimeStamp`); prep reads them, geotag does
not. With no track covering it the cell falls to the zone guess and a question, though the photo states its own
offset. The same evidence would settle phone photos with no offset tag (item 20) and give item 6 its check.

**Open:** a stale fix (a camera reusing its last fix) gives a wrong time — what bounds it; whether such an offset
applies itself as one agreed by several anchors does.

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

**Ruled 2026-11-14:** one zone per destination, whatever a photo records (`RUL-destination_has_one_timezone`); a photo
recording another offset stops the zone until the user moves it, picks its zone or confirms the destination's.

**Open:** ask a missing zone once, at the topmost destination that neither has nor inherits one.

### 43. Videos and set-aside JPEGs keep the uncorrected clock in their names

**Why:** geotag changes photos by destination only, never a video (`RUL-geotag_changes_only_by_dest`). A camera on
home time: its photos are named in destination-local time, its videos of the same minutes eight hours away, and a
RAW no longer shares its name with its set-aside JPEG. No item says the provisional name is final for them.

**Open:** say so, or correct those names from the camera-day's settled offset — a rename, no tag written.

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

### 48. Say at the start that a filesystem cannot hold a workspace or a library

**Why:** `RUL-filesystem_agnostic` names what cartographer requires of a filesystem: file locks, an atomic rename, a
move that fails where its target exists, syncing a file and a folder to disk. A filesystem without them — a FAT or
exFAT card, some network shares — is not checked for: a run there fails at its first lock or move, with that call's
error and no word of why. The owner, 2026-11-14: backlog it.

**What:** at a run's start, on the workspace's filesystem and, for merge, the library's: try each requirement on a
scratch file in the control directory and stop, naming the one that is missing, before anything else is done. To be
ruled with it: whether a network filesystem, where the lock guards one machine only
(`RUL-stale_takeover_conservative`), is refused, warned of, or left to the user.

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

