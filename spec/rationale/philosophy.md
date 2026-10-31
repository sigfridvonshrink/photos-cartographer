# Philosophy — the roots, and what they force

**Not normative.** The design's reasons, from the bottom up: three **facts** about photos (`FCT`), which nobody chooses,
and four **choices** (`CHC`), which can be argued with. Nothing follows from anything before them. Every other item here
is a rationale that `follows from` them, or from another rationale; one marked `forced: yes` could not reasonably be
otherwise given what it follows from, and the build checks that its chain reaches a root. One marked `forced: no` is a
judgement, fair game for ordinary debate. For who the tool is for, and how to read the roots, see
[Who is this for?](https://github.com/sigfridvonshrink/photos-cartographer/blob/main/docs/who-is-this-for.md).

```{needflow}
:filter: docname == "rationale/philosophy"
:link_types: follows_from
```

## The roots

### Facts

:::{fct} A photo batch is large — thousands of frames, several cameras
:id: FCT-large_batches
:status: seed
:aliases: F1

A trip dump or a years-deep library is big and mixed: many RAW/JPEG frames across multiple cameras and phones.

*Where one has met it:* The card one keeps meaning to deal with; the decade of folders; or *"I'll geotag these
someday."*
:::

:::{fct} Camera clocks drift — independently, and from day to day
:id: FCT-clocks_drift
:status: seed
:aliases: F2

Each body's clock is wrong by its own amount, and that amount changes between days (drift, manual resets to local time
in the morning, missed DST). There is no single global offset to find.

*Where one has met it:* The import that landed an hour early; the shots an hour off after a border; a day's frames
scattered because the clock was never set — blamed on negligence or forgetfulness, not on a category.
:::

:::{fct} GPX coverage is partial
:id: FCT-partial_track_coverage
:status: seed
:aliases: F3

The logger's tracks reach *some* of the library, never all of it — so the track alone can never place every frame; the
rest needs fallbacks.

*Where one has met it:* The half-tagged library; the map view with holes where phone-sync missed; the frames that came
with a pin and the many that didn't.
:::

### Choices

:::{chc} Photos matter; they are irreplaceable, so they deserve care
:id: CHC-photos_matter
:status: seed
:choice_kind: value
:aliases: P1

Because they matter, no original may be lost or silently altered — correctness beats convenience.
:::

:::{chc} A local, owned, folder-based library
:id: CHC-local_folder_library
:status: seed
:choice_kind: choice
:aliases: P2

The destination is a plain directory tree on disk (feeds digiKam or Immich), not a cloud service or proprietary
catalog.
:::

:::{chc} Ask only what the data can't settle
:id: CHC-ask_only_what_data_cannot_settle
:status: seed
:choice_kind: design-value
:aliases: P3

Resolve everything derivable automatically; ask only real judgment questions, and make each one cheap to answer.
:::

:::{chc} 100% placement, even under GPS scarcity
:id: CHC-total_placement
:status: seed
:choice_kind: goal
:aliases: P4

Every photo ends up on the map — precise where tracks allow, rough or manual where they don't — so the result is a
*map-complete* library, not just the frames that came with a location.
:::

### Not roots

:::{rat} Linux and open-source are not roots
:id: RAT-linux_and_open_source_not_roots
:status: seed
:forced: no
:follows_from: CHC-photos_matter, CHC-local_folder_library

This is built and run on Linux, but Linux is not a root — the design is plain Python shelling out to `exiftool`,
ImageMagick, and `ffmpeg`, all cross-platform, so it would port with little structural change. Open-source is likewise
a downstream expression of the "local, owned" ethos (P1, P2), not a structural driver. Neither forces anything below.
:::

## What they force

### From P1 — irreplaceable originals

:::{rat} Non-destructive core
:id: RAT-non_destructive_core
:status: seed
:forced: yes
:follows_from: CHC-photos_matter

plan / validate / execute; atomic no-clobber; quarantine, not delete; pre-state ledger.
:::

:::{rat} No mutation outside a validated plan
:id: RAT-no_mutation_outside_plan
:status: seed
:forced: yes
:follows_from: RAT-non_destructive_core

**plan → validate → execute**; the dry-run *is* the serialized plan; stale plans are rejected against current state.
:::

:::{rat} Safety cannot rest on the plan being correct
:id: RAT-safety_not_on_the_plan
:status: seed
:forced: yes
:follows_from: RAT-non_destructive_core

No-clobber **re-verified atomically at the moment of each write**, not just at plan time.
:::

:::{rat} Deletion is never automatic
:id: RAT-no_automatic_deletion
:status: seed
:forced: yes
:follows_from: RAT-non_destructive_core

Duplicates are **quarantined**, never removed; pruning is an explicit, separate act.
:::

:::{rat} A decision must be withdrawable
:id: RAT-decision_withdrawable
:status: seed
:forced: yes
:follows_from: RAT-non_destructive_core

A **pre-state ledger** records what a file held before a manual override, so deleting the decision *restores* the
prior state.
:::

### From F2 + P3 — drift makes the decisions intricate; P3 keeps them cheap

:::{rat} Drift is per-camera and per-day, so no global offset is correct
:id: RAT-offset_per_camera_destination_day
:status: seed
:forced: yes
:follows_from: FCT-clocks_drift

Start with the fact. Because each camera's clock is wrong by its own amount, and that amount changes from day to day
(F2), there is no single offset to discover — the correct answer is **per (camera group, destination, day)**. *That*
granularity is the entire source of the decisions' "complexity": it is a consequence of real, time-varying drift, not a
premise.

The offset is **inferred and applied per (camera group, destination, day)**; corrections fall *between* destinations,
never within one — which is why **one destination = one coherent shoot**.
:::

:::{rat} Intricate, evidence-specific decisions are too error-prone to hand-edit
:id: RAT-format_editor_split
:status: seed
:forced: yes
:follows_from: FCT-clocks_drift

**Format + editor split**: JSON is the record; the Time/Drift/GPS app is what writes it.
:::

:::{rat} The record must stay an honest statement of *intent*, not a mutable scratchpad
:id: RAT-editor_writes_only_decisions
:status: seed
:forced: yes
:follows_from: RAT-format_editor_split

The editor writes **only the `user_decision` field** — never derived or evidence fields.
:::

:::{rat} Minimal, cascading asks
:id: RAT-minimal_cascading_asks
:status: seed
:forced: yes
:follows_from: FCT-clocks_drift, CHC-ask_only_what_data_cannot_settle, CHC-local_folder_library

Such intricacy would be brutal to enter by hand, so P3 (ask only what the data can't settle) governs how it is
collected — and introduces the document's central trade.
:::

:::{rat} Asking per-photo would be thousands of short-reaching chores
:id: RAT-decisions_cascade
:status: seed
:forced: yes
:follows_from: RAT-minimal_cascading_asks

Decisions **cascade**: *one far-reaching choice high in the tree is traded for many short-reaching ones* — inherit
unless overridden, remembered across re-runs. (This is where "far-reaching" comes from — a chosen trade, not an
inherent property.)
:::

:::{rat} Inheritance needs an axis to travel along
:id: RAT-destination_tree_is_a_hierarchy
:status: seed
:forced: yes
:follows_from: RAT-decisions_cascade

The destination tree must be a **hierarchy** — the cascade rides on folder nesting, so a flat or tag-based layout can't
inherit at all, and every value would fall back to per-photo entry.
:::

:::{rat} The unavoidable human act should pay for itself
:id: RAT-piggyback_on_the_destination_sort
:status: seed
:forced: yes
:follows_from: RAT-minimal_cascading_asks

Timezone, clock offset, and GPS fallback are **piggybacked on the destination sort** one would do anyway for real albums
(P2).
:::

:::{rat} The tedious part of a judgment call should be pre-computed
:id: RAT-camera_groups_generated
:status: seed
:forced: yes
:follows_from: RAT-minimal_cascading_asks

**Camera groups are generated for the user**, ready to paste — leaving only the judgment, not the derivation.
:::

### From P1 + F3 — recoverable, and resumable on incremental input

:::{rat} Recoverable core
:id: RAT-recoverable_core
:status: seed
:forced: yes
:follows_from: CHC-photos_matter, FCT-partial_track_coverage

Crash-recovery follows from P1 (an interrupted run must never strand an original half-changed); the diff-based
idempotency also answers F3 — because coverage is partial, one adds more tracks or photos later and re-runs, so a run
must act only on what actually changed.
:::

:::{rat} A crash must be recoverable
:id: RAT-discrete_stages
:status: seed
:forced: yes
:follows_from: RAT-recoverable_core

**Discrete, inspectable stages** (the numbered pipeline) — each a real checkpoint; the **filesystem is treated as
truth**.
:::

:::{rat} Re-runs must not redo settled work or cause churn
:id: RAT-idempotent_reruns
:status: seed
:forced: yes
:follows_from: RAT-recoverable_core

**Idempotent, diff-based** re-runs; a run over unchanged state is a no-op.
:::

:::{rat} Identity must survive EXIF rewrites and renames
:id: RAT-decoded_pixel_identity
:status: seed
:forced: yes
:follows_from: RAT-recoverable_core

A **decoded-pixel fingerprint** (ImageMagick/ffmpeg), not file bytes, as each photo's stable identity.
:::

### From P4 — total placement under GPS scarcity

:::{rat} Total-coverage cascade
:id: RAT-total_coverage_cascade
:status: seed
:forced: yes
:follows_from: CHC-total_placement, FCT-partial_track_coverage

This choice fights F3: tracks cover only *part* of the library, but the output must be *whole*. That gap is what forces
the fallback machinery to exist: without P4, tracks alone would be the entire story and everything below would be
unnecessary.
:::

:::{rat} Placement cannot depend on the track alone
:id: RAT-folder_gps_fallback
:status: seed
:forced: yes
:follows_from: RAT-total_coverage_cascade

A **cascading folder-level GPS fallback** — set one coordinate at a trip's root and it is inherited down the tree (P3
makes this cheap; one answer covers many photos).
:::

:::{rat} The true unplaceable set must be surfaced, never silently dropped
:id: RAT-remainder_worklist
:status: seed
:forced: yes
:follows_from: RAT-total_coverage_cascade

An explicit, short **remainder worklist** — what no evidence can locate is collected for a manual pin, not left off the
map.
:::

:::{rat} Every placeable point of the track must be squeezed out
:id: RAT-track_squeezed
:status: seed
:forced: yes
:follows_from: RAT-total_coverage_cascade

**Direct match → interpolation between points → bounded extrapolation off the ends**, each used before falling back to
manual.
:::

:::{rat} Completeness means precision now *varies* across the library
:id: RAT-coordinate_carries_its_method
:status: seed
:forced: yes
:follows_from: RAT-total_coverage_cascade, RAT-consolidated_log

Completeness means precision now *varies* across the library — so each placement must declare how trustworthy it is
(via the **traceability** the multi-session reality forces — see below).

**Every coordinate carries its derivation method** — native / GPX direct-match / interpolated / extrapolated / manual
— so a rough pin is never mistaken for a precise one.

*Why it is kept:* "I still want to be able to know, at a later date, how that GPS position was assigned - maybe I want
to refine it by image/place recognition for example." A new track needs no tag: it changes the GPX folder, which makes
the GPS decisions stale, and they are regenerated.

*The traceability:* "every decision must be traced, and by incorporating the precision, I allow it even in the final
library."
:::

### From F1 + P4 — total coverage at scale becomes a multi-session job

:::{rat} A multi-session job
:id: RAT-multi_session_job
:status: seed
:forced: yes
:follows_from: FCT-large_batches, CHC-total_placement

This is a **two-level chain**: a fact and a choice together force an intermediate consequence, and that consequence
forces the record machinery. It is the part most easily mistaken for an arbitrary choice.

Neither root does it alone. Scale (F1) without the 100%-coverage goal (P4) is fast: prep is automated, one keeps the
native-GPS frames, lets the track cover the easy matches, and stops — plausibly one sitting, because the long tail is
never chased. The goal without scale is also trivial: placing ten photos completely takes minutes. Only *total
coverage across a large, mixed batch* produces a long tail of per-(camera, destination, day) offset confirmations and
hand-placed remainder that cannot be finished in one sitting.

Note: not all of that elapsed time is P4's. The album **sort** into a destination tree is owed to **P2** — one would
drag photos into folders even with no geotagging at all — so P2 contributes session-spanning human time on its own.
What F1 + P4 *specifically* add is the **long tail of confirmations and manual placement** that has no automated
escape. Either way, the job likely spans multiple sessions.

**Intermediate consequence — a multi-session job.** The machine cannot hold one's decisions in its head between
sittings.
:::

:::{rat} Durable, resumable record
:id: RAT-durable_record
:status: seed
:forced: yes
:follows_from: RAT-multi_session_job

That, in turn, forces the record machinery — and note what is *not* a driver here: auditability and decade-longevity,
are **zero-cost benefits** that fall out of building for resumability.
:::

:::{rat} Decisions can't live in the tool between sessions, so they must persist outside it
:id: RAT-plain_json_record
:status: seed
:forced: yes
:follows_from: RAT-durable_record

**Plain JSON** decision artifacts — the durable external record, read back at the start of each session.
:::

:::{rat} Resuming must not mean re-deciding
:id: RAT-decisions_reread_cache_only
:status: seed
:forced: yes
:follows_from: RAT-durable_record

Decisions are **idempotently re-read each run**; the fast store is **SQLite as a cache only** — derived, rebuildable,
never the source of truth.
:::

:::{rat} A choice made weeks earlier must still explain itself on return
:id: RAT-consolidated_log
:status: seed
:forced: yes
:follows_from: RAT-durable_record

A **consolidated, self-describing log in one kept folder** — *traceability arrived at, not chosen* (and it is this
traceability that lets the provenance tag above mean anything).
:::

:::{rat} Built to survive a three-week gap, it survives a thirty-year one
:id: RAT-longevity_is_free
:status: seed
:forced: no
:follows_from: RAT-durable_record

*(zero-cost benefit)* Decade-longevity and "open one folder years later" come free — incidental, never the driver.
:::

## What is *not* forced (the residue)

These are real choices but only details.

:::{rat} The exact decomposition into stages
:id: RAT-stage_cut_points
:status: seed
:forced: no
:follows_from: RAT-discrete_stages

**The exact decomposition into seven stages** rather than six or eight. The *principle* of discrete inspectable
checkpoints is forced (P1+F3); the specific cut points are judgment.
:::

:::{rat} The consensus-clustering details
:id: RAT-clustering_details
:status: seed
:forced: no
:follows_from: RAT-offset_per_camera_destination_day

**The consensus-clustering details** of clock-offset inference — clustering rather than averaging is forced by
robustness, but the spread thresholds, the tie-breaks, and the confidence grades are choices.
:::

:::{rat} The downstream library, not the tree
:id: RAT-which_folder_library
:status: seed
:forced: no
:follows_from: RAT-destination_tree_is_a_hierarchy, CHC-local_folder_library

**The downstream library, not the tree.** A *hierarchical* destination tree is **forced**, not chosen: the timezone /
offset / GPS-fallback cascade rides on the folder nesting, so a flat or tag-based layout would make inheritance
impossible and drive the per-photo workload straight back up. What is actually free is only *which* folder-based
library consumes the result — digiKam, or any other — and the cosmetic naming of the levels.
:::

:::{rat} Defaults that are offered, not imposed
:id: RAT-configurable_folder_names
:status: seed
:forced: no
:follows_from: RAT-discrete_stages

**Defaults that are offered, not imposed.** Folder names (`0-sources … 6-photos-by-dest`) are configurable, not
hardcoded — the seven-stage *structure* is the invariant, the *labels* are the operator's. The rigidity is structural
where it must be and accommodating where it can afford to be.
:::
