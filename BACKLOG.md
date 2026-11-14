# photos-cartographer — what is open

*Every entry stands alone: what it is, why it matters, what blocks it.*

- **What this is:** [`README.md`](README.md). **The record:** [`HISTORY.md`](HISTORY.md).

*Open items: **15** — 2, 3, 4, 5, 6, 7, 11, 12, 13, 14, 15, 16, 17, 18 and 19.* 🛑 Numbers are never reused; the next is **20**.

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
walkthrough's "Geotag won't proceed" step predates geotag running prep itself.

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
two decision fields (`accept_proposed_timezone`, `manual_real_utc`). None of it is in `HISTORY.md`, and the work is on
the branch `spec-corpus-sphinx-needs`, not on `main`; the tag `specs-before-corpus` is local.

**What to do:** write the `HISTORY.md` entry, refresh `COVERAGE.md`, open the pull request to `main` and, once merged,
tag and publish the release — its version decided then (a workspace decided under the removed fields carries values
nothing reads now).

**When:** once Vasile chooses to release.

