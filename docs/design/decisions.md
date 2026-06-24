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

- **Clock offset = three mutually-exclusive click-to-activate modes**, with an impact line showing
  camera → corrected local — not a free-text field (#109, #112).
- **Per-date offset buckets**: grouped, collapsible, fan-out edit (#115).
- **GPS panel**: a single lat/lon field, Google-Maps paste that commits + jumps the map, multi-select,
  seed-the-next-photo-from-the-last-pick, map placed above the photo (#117–#122, #132).
- **Drift validation = a scrub-on-track view**, Photo / Track sub-tabs (#124, #129, #131).
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

---

## Decided against  (don't re-propose without a new reason)

- **Console auto-shutdown on tab close / UI auto-close** — NO. `Ctrl-C` stays the only stop; a closed
  browser tab must not kill a running phase.
- **Light / reactive theme** — NO. Dark-only; native controls themed via `color-scheme: dark` (#234).
- **In-app editor "Re-run" button** — REMOVED; the hover preview follows the cursor instead (#133).
- **Reordering the unknown-group snippet** — would reintroduce the dropped-comma / invalid-config bug;
  the regression test guards it (#278, #283).
