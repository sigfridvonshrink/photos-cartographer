# `spec/` — the authoritative workflow specifications

This directory is the **behavioral source of truth** for the pipeline. Behaviour is defined by the
markdown here, and the code follows it — when a script and its spec disagree, the spec wins and the code
is reconciled to it, not the other way around. When you change pipeline behaviour, update the governing
spec first.

For the project overview, motivation, and safety rationale, see the [main README](../README.md); for who
it's for and the design reasoning, [Who is this for?](../docs/who-is-this-for.md); for a hands-on tour,
the guides under [`../docs/`](../docs/).

## What the pipeline does

Three phases over a transient **workspace**, each on the same plan → validate → execute contract:

- **prep** (`photos-1-prep`) — consolidate an unorganized dump, normalize extensions, dedup (quarantine,
  never delete), date-organize, hand off a clean working set.
- **geotag** (`photos-2-geotag`) — the headline mechanism: resolve each photo to real UTC by
  **automatically inferring and correcting each camera's clock offset** (matching its already-geotagged
  frames against the GPX tracks, ranked by confidence, per camera-group/destination/day), then geotag the
  un-tagged majority by interpolating along the track, and rename by corrected local time.
- **merge** (`photos-3-merge`) — move the finalized `6-photos-by-dest` staging tree into the permanent
  library, never renaming or overwriting anything already there, then seal the workspace.

## The documents

The four documents below are the **authoritative** behavioral specs. Read the shared contract first for
the cross-phase facts, then the per-phase specs in pipeline order.

| Document | Scope |
|---|---|
| [`photos-shared-contract.md`](photos-shared-contract.md) | Facts the phases share: the run lock, the `.photos-ingest/` control dir, `photos-00-config.json`, formats, `gpx_root`, the input-validation discipline, the execute-time no-clobber/atomicity rule, the archival package, the end-to-end operator loop, and the workspace lifecycle (init → strays → sealed terminal state). |
| [`photos-1-prep-workflow.md`](photos-1-prep-workflow.md) | **Phase 1 — prep.** |
| [`photos-2-geotag-workflow.md`](photos-2-geotag-workflow.md) | **Phase 2 — geotag.** |
| [`photos-3-merge-workflow.md`](photos-3-merge-workflow.md) | **Phase 3 — merge.** |

## What belongs here — and what doesn't

The specs carry **behaviour only** — never output wording, UI, log lines, or implementation/comfort
detail. The three kinds of decision have three homes (see [`../docs/design/decisions.md`](../docs/design/decisions.md)):

- **Behaviour the tool guarantees** → here, in `spec/`.
- **A local affordance with one code site** → a comment at that site plus a regression test.
- **A standing or deliberately-rejected affordance** (console/editor sub-decisions, output phrasing) →
  `../docs/design/decisions.md`.

## Downstream, non-authoritative

The decision *editor* that helps a human fill in the JSON the specs describe has its own docs alongside
its code. These are **non-authoritative and downstream** of the specs above — if they ever disagree, the
spec and code win:

- [`../cartographer/editor/decision-json-reference.md`](../cartographer/editor/decision-json-reference.md)
  — the field-level shape of the decision artifacts (`photos-21`/`22`/`23`) the editor reads and writes.
- [`../cartographer/editor/design-notes.md`](../cartographer/editor/design-notes.md) — the editor's
  UI/architecture design notes.
