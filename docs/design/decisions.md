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
  named — five at most — with how to read them: scattered, their own positions are off; the last of the
  day, the camera's clock changed. Code site `offsetProposalBlock` / `groupChoice` / `proposalNotes` in
  `web/app.js`, tested in `app_offset_buckets.test.mjs`.
- **Per-date offset buckets**: grouped, collapsible, fan-out edit (#115).
- **A clock changed during the day is one tick on the day's row**: the offset panel names both runs and offers
  "split the day where the clock changed"; where photos without GPS lie between the runs, a choice of which was the
  first after the change (or none of them). The parts the split makes are never rows of their own — they are
  geotag's, answered by the day's tick — and a day with a proposed change is never collapsed with other days. Code
  site `clockChangeControls` / `clockChangeHolds` / `offsetGroups` in `web/app.js`, tested in
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
- **Folder GPS fallback modelled as presence/absence** — no enum; an unset fallback reads `none`, not
  `resolved`, so it cannot falsely propagate; a **Clear** button resets to none (#241–#243).
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
  not a simulation (#194, #196).
- **Bound to 127.0.0.1**; prints a copy-paste `ssh -L` tunnel hint on loopback startup (#216).
- **Editor folded in as the 4th tab** via an iframe at `/edit/` — one origin (so one tunnel suffices),
  zero editor changes (#199).
- **In-page Jobs (`-j`) control** — a transient, machine-dependent knob (#227, #229). (That it stays
  out of the saved plan and config is *contract*, not affordance — #228.)
- **Stop/interrupt**: async-raise `KeyboardInterrupt` + kill worker children. Safe only because phases
  are crash-safe / idempotent / resumable (#226).
- Opens on an **uninitialized** workspace (prep `plan` only) (#225).
- **A stop on changes to the workspace is offered for acceptance in a dialog** (BACKLOG 50): the same
  list the command printed, grouped as printed, and an **Accept these** button that re-sends the same run
  (an execute's confirmation and reviewed plan id included) with the stop's code as `--accept-changes`.
  The list arrives as its own `changes` event — not parsed out of log lines — and is kept for a page
  that joins late until the next run starts. No per-file picking: the code accepts the whole list or
  nothing, as on the command line. (Hand-editing a file of acceptances was rejected by the owner as
  tedious; that is behaviour, in the spec — `RAT-accept_once_by_code`.)

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

---

## Decided against  (don't re-propose without a new reason)

- **Console auto-shutdown on tab close / UI auto-close** — NO. `Ctrl-C` stays the only stop; a closed
  browser tab must not kill a running phase.
- **Light / reactive theme** — NO. Dark-only; native controls themed via `color-scheme: dark` (#234).
- **In-app editor "Re-run" button** — REMOVED; the hover preview follows the cursor instead (#133).
- **Reordering the unknown-group snippet** — would reintroduce the dropped-comma / invalid-config bug;
  the regression test guards it (#278, #283).
