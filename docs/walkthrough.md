# See it work — a full run, end to end

This is **a real run** on a real trip dump, start to finish, in pictures — a dump turned into a
map-complete library. Every step is a screenshot from the browser console (the same phases run from
the command line — see the [quick start](quickstart.md)). Concepts are introduced as they come up,
each linked to the deeper explanation in [Concepts](concepts.md).

The shape of the whole thing: **prep** (organize the dump) → **you sort** photos into destinations →
**re-prep** → **geotag** (infer time, fix the clock, place on the map) → **merge** into your permanent
library. Nothing is deleted, and nothing is written without a plan you can inspect first.

```mermaid
flowchart TD
    A["Drop the dump into 0-sources"] --> P["Prep: plan, dry-run, execute"]
    P --> SORT["You sort photos into the destination tree<br/>(6-photos-by-dest) — the one step only you can do"]
    SORT --> RP["Re-prep (mandatory): recognizes the moves"]
    RP --> GP["Geotag plan"]

    subgraph EDIT ["Geotag edit loop — gated, in order, each as many rounds as needed"]
      direction TB
      GP --> TZ{"Timezones all resolved?"}
      TZ -->|no| TE["Time view: set / confirm, then re-plan"]
      TE --> TZ
      TZ -->|yes| DF{"Clock drift all resolved?"}
      DF -->|no| DE["Drift view: scrub photo on the track, then re-plan"]
      DE --> DF
      DF -->|yes| GS{"GPS all placed?"}
      GS -->|no| GE["GPS view: map / fallback, then re-plan"]
      GE --> GS
    end

    GS -->|yes| EX["Geotag: execute, then finalize"]
    EX --> IL{"Library blessed?"}
    IL -->|no| BL["merge init-library"]
    BL --> MG
    IL -->|yes| MG["Merge: plan, dry-run, execute"]
    MG --> SEALED(["Workspace SEALED — terminal"])
```

The geotag editor is **gated and in order**: you settle all the timezones, then all the clock-drift
corrections, then all the GPS placements — each is its own loop of *edit → re-plan → re-check*, with as
many rounds as you need, before the next opens.

> Tip: click any screenshot to view it full-resolution.

---

## 1. Prep — consolidate and organize, safely

Prep takes the raw dump in `0-sources/` and date-organizes it. It is a strict **plan → dry-run →
execute** pipeline: planning never touches a file.

**Plan.** Prep scans the dump and builds a plan — every move, rename, and dedup is an explicit
operation. Nothing has moved yet.

![Prep planning](screenshots/carto-01-prep-planning.png)

**Planned.** The plan is saved. On the **first** run the config was just seeded from defaults — prep
loudly suggests you review it (above all `media_extensions`, which decides what counts as a photo vs.
what gets set aside), because it has big downstream consequences. Each phase reports its timing.
→ *[Configuration](concepts.md#configuration)*

![Prep planned](screenshots/carto-02-prep-planned.png)

**Dry-run.** A summary of the **real** saved plan — operation counts, no-ops, warnings, blockers —
without touching anything. (It summarizes the actual plan on disk; it is not a separate simulation.)

![Prep dry-run](screenshots/carto-03-prep-dry-run.png)

**Execute.** Now it applies the plan: photos into `5-photos-by-date/`, videos into `4-videos-by-date/`,
non-media set aside in `1-strays/`, duplicates quarantined (recoverable, never deleted). `0-sources/`
is left empty.

![Before execute](screenshots/carto-04-prep-exec-before.png)
![Executing](screenshots/carto-05-prep-executing.png)
![Executed](screenshots/carto-06-prep-executed.png)

**Quarantine is recoverable.** Duplicates go to a quarantine you can inspect; pruning it is a separate,
explicit step — never automatic.

![Prune quarantine — before](screenshots/carto-07-prep-prune-quarantine-before.png)
![Prune quarantine — after](screenshots/carto-08-prep-prune-quarantine-after.png)

---

## 2. Sort into destinations — the one step only you can do

Now you move the photos from `5-photos-by-date/` into a **destination tree** under `6-photos-by-dest/`
(e.g. `2026/Belgium/Bruges/`). This is the one creative decision the tool can't make — and it's
**load-bearing**: a photo's destination decides its timezone, its clock-offset correction, its GPS
fallback, and where it lands in the library. → *[Destinations and the by-dest tree](concepts.md#destinations-and-the-by-dest-tree)*

**Geotag won't proceed yet.** The handoff prep wrote predates your move, so geotag refuses — it tells
you exactly what to do.

![Geotag plan denied](screenshots/carto-09-geotag-plan-denied.png)

> Aside — the console notices if the server stops (e.g. you Ctrl-C it or the SSH tunnel drops) and says
> so, rather than looking frozen.
>
> ![Connection lost](screenshots/carto-10-connection-lost.png)

**Re-prep (mandatory).** Run prep again. It recognizes the moves (stat-only — no re-reading the files),
carries each photo's identity forward, and refreshes the handoff. Now geotag can proceed.

![Prepped again](screenshots/carto-11-prepped-again.png)

---

## 3. Geotag — infer the time, fix the clock, place on the map

Geotag resolves everything it can on its own and collects the rest into a short worklist you settle in
the browser editor. → *[Editor guide](editor.md)*

**Unknown cameras.** The first time it meets a camera it can't classify, geotag stops with a
ready-to-paste config snippet — is this a phone (correct clock) or a camera (clock to be inferred)?
→ *[Camera groups](concepts.md#camera-groups)*

![New camera groups](screenshots/carto-12-new-camera-groups.png)

**Plan → worklist.** A geotag plan produces the decisions to make, grouped by destination and camera.

![Geotag plan](screenshots/carto-13-geotag-plan-01.png)

### Time view — establish each destination's timezone

Set or accept each destination's timezone; a value cascades **down** the tree, so you author it once at
the top and override only where a place differs. → *[What cascades](concepts.md#what-cascades-down-the-tree-and-what-doesnt)*

![Time view](screenshots/carto-14-geotag-edit-time-01.png)
![Time view — editing](screenshots/carto-15-geotag-edit-time-02.png)

Re-run to recompute everything downstream, then continue settling the remaining timezones.

![Geotag plan again](screenshots/carto-16-geotag-plan-02.png)
![Time view — more](screenshots/carto-17-geotag-edit-time-03.png)
![Time view — done](screenshots/carto-18-geotag-edit-time-04.png)
![Time resolved](screenshots/carto-19-geotag-plan-after-time-finished.png)

### Drift view — correct a camera's clock against the track

The headline trick: for a camera whose clock was wrong, **scroll the photo along its GPX track** under a
fixed crosshair until it lines up — the editor reads the corrected offset straight off the track. No
typing offsets by hand. → *[Clock offset vs. GPS drift](concepts.md#clock-offset-vs-gps-drift)*

![Drift — start](screenshots/carto-20-geotag-edit-drift-start.png)
![Drift — the photo](screenshots/carto-21-geotag-edit-drift-photo.png)
![Drift — scrub along the track](screenshots/carto-22-geotag-edit-drift-track.png)
![Drift — done](screenshots/carto-23-geotag-edit-drift-done.png)
![Drift resolved](screenshots/carto-24-geotag-plan-after-drift-finished.png)

### GPS view — place whatever the track couldn't

A worklist of only the photos no automatic source could locate, plus a per-destination **folder
fallback**. Place a photo on the map, paste a `lat, lon` from Google Maps, or set one fallback
coordinate that a whole destination (and its children) can inherit.

![GPS — folder fallback](screenshots/carto-25-geotag-edit-gps-fallback.png)
![GPS — place a photo on the map](screenshots/carto-26-geotag-edit-gps-per-photo.png)
![GPS — inherited fallback](screenshots/carto-27-geotag-edit-gps-fallback-inherit.png)

### Execute & finalize

When the executable plan is clean, execute writes the time and GPS into the originals — journaled and
idempotent, so it's safe to re-run.

![Geotag planned (clean)](screenshots/carto-28-geotag-planned.png)
![Pre-execute](screenshots/carto-29-geotag-pre-execute.png)
![Executing](screenshots/carto-30-geotag-executing.png)
![Geotag done](screenshots/carto-31-geotag-done.png)

**Finalize** bundles the durable archival package and the full transformation log — required before
merge.

![Finalized](screenshots/carto-32-geotag-finalized.png)

---

## 4. Merge — into the permanent library

**Bless the library first.** Merge refuses until the target library is initialized; *Init library*
marks it, which enables *Plan*.

![Merge — before library init](screenshots/carto-33-merge-before-library-init-1.png)
![Merge — before library init](screenshots/carto-34-merge-before-library-init-2.png)
![Merge — after library init](screenshots/carto-35-merge-after-library-init.png)

**Plan → dry-run.** Merge maps the curated `6-photos-by-dest/` tree into the library, preserving your
structure, with no-clobber collision handling.

![Merge planned](screenshots/carto-36-merge-planned.png)
![Merge dry-run](screenshots/carto-37-merge-dry-runned.png)

**Execute → sealed.** It moves the finalized photos into the permanent library, then **seals** the
workspace: it is terminal — every phase refuses to touch it, and new media goes into a fresh workspace.
(An optional ZFS snapshot of the library is taken first, if configured.)

![Merge — before](screenshots/carto-38-merge-before.png)
![Merge — after, sealed](screenshots/carto-39-merge-after-sealed.png)

---

## Where to go next

- **[Quick start](quickstart.md)** — the same run as copy-paste commands.
- **[Concepts](concepts.md)** — the *why*: camera groups, per-day offsets, the by-dest tree, what
  cascades.
- **[Editor guide](editor.md)** — the three views in depth.
- **[`spec/`](../spec/)** — the authoritative behavioral contract.
