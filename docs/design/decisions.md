# Design decisions — affordance & UX

This log records **affordance decisions**: comfort / presentation / ergonomics choices that are *not*
part of the behavioural contract. It exists because the three kinds of decision have three different
homes, and this is the home for the third:

- **Behaviour the tool guarantees** → `spec/` (the authoritative contract). Output wording, UI, log
  lines, and implementation detail must never live there.
- **Local affordance with a single code site** → a comment at the site + a regression test. The test
  is the guard a spec clause would otherwise be: revert it → red. No entry here needed unless it is
  also a standing or rejected call.
- **Standing or rejected affordance with no single code site** → *this file*. These are the ones that
  get silently re-proposed, because there is nothing to comment and often nothing to test.

Append-only, newest-last within a section. Each entry: the call, why, status, PR.

---

## Macro: the web layer exists at all

The **CLI is the contract** — each phase's `run()`. The **console and editor are pure affordance** over
it: the web layer never owns behaviour, it triggers the same `run()` and observes the same reporting
seam (`cartographer/reporting.py`). This is a deliberate, costed choice — a whole UI to maintain —
justified by the tool being run a few times a year by hand: a browser is friendlier than recalling
eleven subcommands and reading JSON. The non-negotiable that falls out of it: **the web layer must
never diverge from, or re-implement, the CLI.** Core behaviour lives in the shared phase `run()`; the
web layer is affordance only (PR #188 event/sink seam; governing rule across every console PR).

### Decision editor  (PRs #86–#93, #101–#133, #191, #199, #241–#243)

A local web UI to author the geotag decision JSON. The contract only requires the `user_decision`
fields edited (and that the editor write *only* those — that part is spec); *how* they are edited is
affordance.

- **Clock offset = two mutually-exclusive choices** — accept the proposal, or an offset of your own, typed on
  an h/m/s spinner or picked as the anchor photo's real time (both store `manual_offset_seconds`) — with an
  impact line showing camera → corrected local; not a free-text field (#109, #112).
- **A GPS proposal's correction groups are choices**: each names its track file and the corrected date, and
  "use this" picks it in one click for every day bundled with it (the recommended group is "accept"). A tie
  between visits gets one line asking for the day the user was there, and photos agreeing with no group are
  named — five at most — with what geotag does with them: a clock change offered as a split of the day, else
  their positions offered the track's in the GPS view, or for a group of several bodies the other body's. The
  interim advice to move the photos after a clock change into a sub-folder went once geotag split the day and
  reviewed contradicted positions itself (BACKLOG 15, 16). Code site `offsetProposalBlock` / `groupChoice` /
  `proposalNotes` in `web/app.js`, tested in `app_offset_buckets.test.mjs` and `app_clock_change.test.mjs`.
- **Per-date offset buckets**: grouped, collapsible, fan-out edit (#115).
- **A contradicted own position is a review that waits on nothing**: the GPS worklist lists it in the folded
  **Placed** bucket, a sub-group of its own (**camera GPS its offset doubts**), both positions and the distance said, with **take the track's position** (writing it as
  `manual_lat`/`manual_lon`) and **keep its own position** — no third choice, no photo being left without a
  position. Code site `contradictedNote` / `takeTrackPosition` in `web/app.js`, tested in
  `app_clock_change.test.mjs` (BACKLOG 16).
- **A clock changed during the day is one tick on the day's row**: the offset panel names both runs and offers
  "split the day where the clock changed"; for each photo without GPS whose part the runs leave unsettled, a choice
  of before or after the change, one row per photo — not one "first after the change" pick, which a clock set back
  (its camera times overlapping) cannot express. The parts the split makes are never rows of their own — they are
  geotag's, answered by the day's tick — and a day with a proposed change is never collapsed with other days. Code
  site `clockChangeControls` / `clockChangeHolds` / `clockChangePart` / `offsetGroups` in `web/app.js`, tested in
  `app_clock_change.test.mjs` (BACKLOG 15).
- **One camera or several bodies, in the Cameras view**: under the new groups, every fixed-clock camera group of the
  photos is listed with two choices — one camera (the default), several bodies — saved into
  `several_bodies_groups` like a new group's class, never a question that waits or opens the view. Why: the owner
  ruled the setting answerable in the configuration and in the editor's camera view (BACKLOG 39). Code site
  `renderBodies` / `bodiesControls` in `web/app.js`, tested in `app_save.test.mjs`.
- **The true time of a photo sets the offset**: for a decision with no anchor frame, a fourth view of the
  self-set offset names the cell's representative photo (photos-21 `representative`, its earliest; with a
  thumbnail) and takes the time it was really taken, typed in the destination's zone (UTC with none); the
  editor computes `manual_offset_seconds` = that − its camera time. A time the zone skips or repeats is
  refused, never read one way. No decision field of its own: `manual_real_utc` was removed on purpose and
  stays removed — the offset is the one stored value. Where accepting is not enough (`far_from_evidence`),
  **accept** is greyed out and a click on a self-set view opens it empty instead of seeding it with the
  proposal, so a reset clock's guess is never written by a stray click. Code site `offsetEditor` /
  `offsetFromTrueTime` / `zonedWallToUtcMs` in `web/app.js`, tested in `app_datetime.test.mjs`.
- **A GPS proposal says which frames it left out**: beside the proposal, a note counts the camera's own-position
  frames that took no part in it — those whose only track lies outside the plausible time window (most likely
  another trip or year), and those with no track at all — so a proposal resting on few frames is not read as
  resting on all. Shown, never decided on: the plan's record carries the counts (`skipped`), the editor words
  them. Code site `offsetProposalBlock` in `web/app.js`.
- **GPS panel**: a single lat/lon field, Google-Maps paste that commits + jumps the map, multi-select,
  seed-the-next-photo-from-the-last-pick, map placed above the photo (#117–#122, #132).
- **Drift validation = a scrub-on-track view**, Photo / Track sub-tabs (#124, #129, #131).
- **A drift correction can be typed as well as scrubbed**: beside the confirm box, a corrected offset in seconds, or
  the true time of the bucket's photo shown on the Photo tab (in the destination's zone, UTC with none; a time the
  zone skips or repeats is refused). Both write what a scrub writes — confirmed against the offset and tracks shown,
  with `corrected_offset_seconds` — so a known offset needs no scrubbing, and a bucket with no track to scrub along
  (an unconfirmed offset is listed with or without one) can still be corrected, not only confirmed. Why: the owner
  ruled every question answerable in the editor (BACKLOG 52); a scrub alone left a trackless bucket's correction to
  the hand. Code site `driftTyped` / `driftCorrectionFields` in `web/app.js`, tested in `app_drift.test.mjs`.
- **Timezones are the host's, never the browser's**: the zone drop-down offers, and the editor checks a
  zone against, the list of zones geotag's plan accepts on the machine it runs on — sent by the server with
  the decisions (`zones`, every zone of the host's database that `valid_iana_timezone` takes) — not the browser's
  own `Intl` list. Why: the plan is what judges a zone; a name one side knows and the other does not (`US/Eastern`
  on a host without the legacy names) would be saved by the editor and then refused by the plan, the user finding
  out a run later. Code site `setHostZones` / `validTz` in `web/app.js` and `_host_zones` in `server.py`, tested
  in `app_validation.test.mjs` and `test_serve.py`.
- **A record that does not parse is shown as its error, not as no file**: where photos-21, -22, -23 or -25 is there
  but cannot be read (the server's `_error`, with where parsing failed), its view says so — a warning naming the error
  and how to repair it — in place of "No photos-2x". Why: a record a hand broke still holds the user's answers; "no
  file" sends them to re-plan, and geotag stops on the same record anyway, leaving it as it is. Saving into it stays
  refused. Code site `recordAbsent` / `recordAbsentText` in `web/app.js`, tested in `app_save.test.mjs` (BACKLOG 52).
- **A photo nothing places is offered its folder's fallback first**: its review item leads with **set the folder's
  fallback**, which opens that destination's fallback cell (saying what is set there, if anything), and only below it
  **or a position for this photo alone**. Why: the owner ruled no photo leaves geotag unlocated, the folder fallback
  being the answer for such photos (BACKLOG 21) — one coordinate there places every photo of the folder nothing else
  places, where a position typed per photo places one. The order is presentation; what places a photo is the
  placement order, in the spec. Code site `reviewOffers` / `controls` in `web/app.js`, tested in
  `app_placement.test.mjs`.
- **The editor's views are grouped by what can differ**: four rules, the same in every view —
  1. a level exists only where its members can carry different answers;
  2. a level with one member folds into its parent (`Placed (212) · between points`, never a group of one — a
     photo alone in its kind is listed under the bucket with its kind beside it);
  3. what waits for an answer is open and sorted first; what is settled is folded;
  4. the same order everywhere: destination tree → the destination's own decisions → per-camera ones → single
     photos.

  Per view: **GPS** — the destination tree; each destination's first row is its fallback (its point, **own** or
  **inherited ⟵ <destination>**, the map to write its own); under it two buckets, **Fallback** (the photos the
  fallback placed, by why the tracks missed them) and **Placed** (camera GPS, camera GPS its offset doubts, track
  point, between points, past track end, set by hand) — or, where no fallback is in effect here or above, **Unplaced** (by why), open and first, in
  place of Fallback (the two cannot meet: a fallback in effect places every photo nothing else does). No camera
  level: a camera day whose photos in the destination all fell back or wait, while the tracks had points that day —
  some photo's nearest track point under a day away, its reason not "no tracks" nor a date fallback's time — is named
  on that bucket as a chip linking to its offset row in the Time view, the cure being its clock rather than a
  position. **Time** — the tree; per destination its timezone, date fallback, then the offset rows of the cameras
  that ask or that the user answered, the cameras the photos settle themselves (an offset in effect, nothing asked,
  nothing written) folded into one **settled by the photos (<cameras>)** line, openable and still answerable; a
  camera's days split only where their answers differ, and a camera is a level of its own only beside other
  cameras. **Drift**, **Cameras**, **Execution** — unchanged (a drift check is per camera day already, each a
  confirmation). Photos stay hover-previewable, and those the tracks or the fallback place keep **set position**,
  which writes what a hand would: a `chosen_by_user` review item with the photo's path and position (the one save
  that adds an entry rather than filling a `user_decision`, since a photo placed automatically has no item to fill).
  The editor computes nothing geotag does not record: photos-23 lists every photo with how it is placed, why the
  tracks missed one the fallback placed, and its camera day (`placed_photos`, `camera_bucket`). Why: the owner —
  *"I would like the "fallback" photos to be seen as a macro group in the editor. By macro group I mean that for
  each destination the editor should start with two big buckets - inherited and placed - and only then break them
  down further."* — and *"the per camera buckets should be showed only if there are decisions that might be
  different for different cameras."*; the four rules were put to the owner and taken ("yes"). The flat list it
  replaced mixed the tracks and the fallback in one fold and showed camera-GPS photos only as a count. Code site
  `gpsBuckets` / `fellBackCameras` / `renderGpsNode` / `offsetSections` / `renderOffsetRows` in `web/app.js`,
  tested in `app_grouping.test.mjs` (BACKLOG 56).
- **A photos-23 holding a field a position decision does not have is shown as unreadable**: the server reads it with
  geotag's own check (`unknown_review_fields`) and shows it as a record that does not parse, naming the field —
  `accept_unlocated` from an older record among them — rather than show answers geotag refuses (BACKLOG 21).
- **Folder GPS fallback modelled as presence/absence** — no enum; a destination with none written here or above reads
  `none`, not `resolved`. An inherited one applies itself (behaviour, `RUL-inherited_fallback_applies`): the
  accept-inherited checkbox is gone, and the one button takes a written fallback away — **back to the inherited
  (lat, lon)**, or **clear** where nothing above has one (#241–#243, BACKLOG 56).
- Served as **package data via importlib.resources, no bundler**; folded into the package as the `edit`
  subcommand (#93, #127); operates on the **cwd workspace**, with `--demo` the only no-workspace mode
  (#137).
- Shared design tokens / instrument identity reskin (#191).

### Operational console  (PRs #187–#200, #214, #216, #225–#244)

Run **and monitor** all eleven phase commands from a browser over the cwd workspace, on the reporting
event/sink seam.

- **UI shape**: tabs, no dashboard, a persistent bottom log (#192).
- **Affordance-only, never diverges from the CLI**: it triggers `run()` in-process (single slot) and
  observes status over SSE — one mutation path, never re-implemented. Buttons are **precondition- and
  staleness-aware**, but the core still validates in depth and refuses; the gating is the cheap shared
  subset (`plan_dependencies_fresh`), not a second source of truth (#193, #198, #230, #244).
- **Execute behind a per-phase 2-step confirm gate** that summarises the *real* saved plan artifact,
  not a simulation (#194, #196). The confirmation sends the id of the plan the gate showed — never one a state poll
  brought in while it was open — and the server refuses an execute naming none, so a plan made again meanwhile meets
  its "plan changed since you reviewed it" refusal.
- **Bound to 127.0.0.1**; prints a copy-paste `ssh -L` tunnel hint on loopback startup (#216).
- **Editor folded in as the 4th tab** via an iframe at `/edit/` — one origin (so one tunnel suffices),
  zero editor changes (#199).
- **In-page Jobs (`-j`) control** — a transient, machine-dependent knob (#227, #229). (That it stays
  out of the saved plan and config is *contract*, not affordance — #228.)
- **Stop/interrupt**: async-raise `KeyboardInterrupt` + kill worker children. Safe only because phases
  are crash-safe / idempotent / resumable (#226).
- Opens on an **uninitialized** workspace (prep `plan` only) (#225).
- **A plan the console cannot read names its way on in its one blocker.** Prep's and geotag's name planning again,
  since their planning sets such a plan aside (`_read_plan`). Merge's names repairing the file or restoring it from a
  `-NNN` copy beside it, never `merge plan`, since merge's planning stops on an unreadable plan of its own too
  (`_merge_summary`). That the summary shows the plan with that blocker and offers no execution is one of the
  owner's preferences (below).
- **A stop on changes to the workspace is offered for acceptance in a dialog** (BACKLOG 50): the same
  list the command printed, grouped as printed, and an **Accept these** button that re-sends the same run
  (an execute's confirmation and reviewed plan id included) with the stop's code as `--accept-changes`.
  Where the page holds no run to re-send — reloaded, or another tab, the stop shown from the snapshot — a plan or
  dry run is sent with the code at once, but an execute is not: Accept opens the execute gate on the saved plan, the
  code attached, and only the confirmation given there sends it. A confirmation is never made up for a gate the user
  never saw (the server's "plan changed since you reviewed it" check would be empty with the current plan's id).
  The list arrives as its own `changes` event — not parsed out of log lines — and is kept for a page
  that joins late until the next run starts. No per-file picking: the code accepts the whole list or
  nothing, as on the command line. (Hand-editing a file of acceptances was rejected by the owner as
  tedious; that is behaviour, in the spec — `RAT-accept_once_by_code`.)
- **The question of downloading the table of countries is asked by the prep Plan button** (BACKLOG 47 (e)): while
  the host's zone database has no `zone.tab` and the workspace has not answered, Plan opens a dialog with the same
  words `prep plan` asks in on a terminal — **Download once** / **Use the carried copy** / Cancel — and sends the
  answer with the run as `--download-zone-table`, so the console's run is the CLI's. Asked *before* the run, as the
  library path is for `init-library`, not after it like an acceptance: the answer is wanted before the scan, never
  after it, and a run never waits on it. On a terminal the CLI asks y/N, the default no; where nobody can answer (a
  pipe) it says how to answer and goes on with the carried copy — that it never stops prep is behaviour, in the
  spec (`RUL-zone_table_never_stops_prep`).
- **The decision editor shows the same question at the head of its Time view** while it is open — a row of its own,
  answered *download it* / *keep the carried copy* and saved with the other answers, marked `unanswered`, never
  `needs input`, since it holds nothing up. The Time view, because the table serves the choice of a destination's
  country there; at its head, because the question stands before any destination's. That the editor answers it at all
  is behaviour (`RUL-zone_table_answered_in_editor`).

---

## Standalone affordance decisions

- **`Next: …` closing operator hint** on every phase command — what to do next from the state it just
  produced. Emitted via the shared `reporting.emit_next_step`, identical in the CLI and the console;
  out of spec (#282).
- **Unknown-group config snippet emits its arrays in the config file's own key order**
  (`fixed_clock_cameras` before `phones`, the sorted-seed order) so a whole-block paste-over preserves
  the comma between them. Out of spec (the rationale was removed from the spec in #283) but **kept as a
  regression test** — the wrong order silently produced invalid config (#278).
- **First-run config notice** — the first `prep plan` warns (advisory) to review the seeded defaults
  (esp. `media_extensions`); first-run only (#238).
- **User-facing messages use `folder_name(role)`**, never hardcoded `0-sources` etc. — workspace folder
  names are configurable, so blurbs/docstrings/spec are exempt but runtime messages are not (#232).
- **Self-documenting CLI** — bare `photos-cartographer` prints the role + phase list; bare `<phase>`
  prints that phase's subcommands (the tool is used a few times a year).
- **A planning command prints the path it saved the plan to**, so the operator can review the artifact
  without hunting for it. Out of spec; the spec keeps only the plan's fixed place.
- **`dry-run` prints a concise summary, not the plan** — operation/move counts by type, blockers, and the
  path to the full plan; the full plan is the saved artifact. Out of spec; the spec keeps that a dry run
  reports on the real saved plan, never a simulation.
- **A stop on unexpected workspace changes lists them grouped by kind and by folder**, then the command to run
  again with `--accept-changes <code>` to accept them once (`format_changes`, `BLD-accept_changes`). Out of spec; the
  spec keeps only that a stop gives a code accepting exactly its list (`RUL-stop_gives_acceptance_code`).
- **The decision editor shows a decision record holding a field its decision does not have as a record it cannot
  read**, naming each such field as geotag's blocker does, and saves nothing into it. Out of spec; the spec keeps that
  such a field is refused (`RUL-unknown_decision_field_refused`).

---

## The owner's preferences

Choices that change nothing that counts, ruled by the owner as preferences, out of the spec. In the owner's words:
*"this does not affect the behaviour that counts in the sense that it can happen before or after without affecting
what matters. Such choices are build choices and should be ruled under a separate heading as my preferences."*

- **The console's summary of a plan the phase cannot read** shows it as a plan with one blocker naming the file, and
  offers no execution for it; the blocker names the way on. The execution itself refuses an unreadable plan in every
  case (`RUL-unreadable_plan_replanned`).
- **The workspace's filesystem is checked to be local, and its requirements tried, before the lock is taken**, so
  that a filesystem that cannot lock is named for what it lacks, never taken for a run in progress. Before or after
  the lock, the run stops before it changes anything, and the trial leaves nothing behind
  (`RUL-filesystem_trial_leaves_nothing`).
- **What a report counts as reused**: each phase's report counts the files already right and the work it reused —
  prep its cache hits, merge the library fingerprints it reused; geotag reuses no result of an earlier plan, its
  resolved-UTC table being written again by each, so counts none. The spec keeps only that earlier work is never
  treated as an error (`RUL-no_op_run_reports_reuse`).
- **Where merge reads in the library**: only at the folders its photos go to and its top folder, besides its mark,
  lock and trial files, and a library file only when one is there — never scanning or indexing it. The spec keeps
  only that merge looks for an incoming photo at its own place, never de-duplicating the library as a whole
  (`RUL-library_not_scanned`).

---

## Decided against  (don't re-propose without a new reason)

- **Console auto-shutdown on tab close / UI auto-close** — NO. `Ctrl-C` stays the only stop; a closed
  browser tab must not kill a running phase.
- **Light / reactive theme** — NO. Dark-only; native controls themed via `color-scheme: dark` (#234).
- **In-app editor "Re-run" button** — REMOVED; the hover preview follows the cursor instead (#133).
- **"Leave unlocated (accept no GPS)"** — REMOVED, the checkbox and the decision field with it: the owner wants no
  unlocated photos, the folder fallback being their answer (BACKLOG 21; behaviour in the spec,
  `RAT-no_photo_unlocated`).
- **Reordering the unknown-group snippet** — would reintroduce the dropped-comma / invalid-config bug;
  the regression test guards it (#278, #283).
