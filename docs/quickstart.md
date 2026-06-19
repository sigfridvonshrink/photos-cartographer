# Quick start

End-to-end: from a downloaded executable to a geotagged shoot merged into your library. If a term here
is unfamiliar (camera group, destination, drift), the [concepts guide](concepts.md) explains the *why*;
the [editor guide](editor.md) covers the browser UI in depth.

---

## 1. Get the tool

photos-cartographer ships as a single self-contained executable, attached to each
[GitHub Release](https://github.com/sigfridvonshrink/photos-cartographer/releases/latest).

```bash
# Download the latest release's two files (executable + editable config defaults)
gh release download --repo sigfridvonshrink/photos-cartographer --pattern 'photos-cartographer' --pattern 'photos-config-defaults.json'
chmod +x photos-cartographer
./photos-cartographer --version
```

(Or download both files from the Releases page by hand.) Keep `photos-config-defaults.json` next to the
executable — it's how you retune defaults without touching the binary.

The executable is a zipapp: it runs like a plain script but **does not embed Python**, so the host
needs a `python3`. Running bare `./photos-cartographer` prints the phase list; `./photos-cartographer
<phase>` prints that phase's subcommands — the CLI is self-documenting.

### Prerequisites

The pipeline shells out to a few standard command-line tools (it doesn't bundle them):

| Tool | Used for |
|---|---|
| **python3** | runs the executable (the zipapp doesn't embed Python) |
| **exiftool** | reads/writes photo time & GPS metadata |
| **ImageMagick** (`magick` / `identify`) | decoded-pixel fingerprint (stable photo identity) + editor previews |
| **ffmpeg** | video fingerprint for date-organizing/dedup |

SQLite comes with Python — nothing to install. **ZFS** is optional (enables pre-mutation snapshots; the
safety model stands without it). The decision editor needs only a browser; its map tiles and place
search use OpenStreetMap at runtime and degrade gracefully offline.

> Just want to look around first? `./photos-cartographer edit --demo` opens a read-only tour on bundled
> example data — no workspace, no setup. See the [editor guide](editor.md).

---

## 2. Initialize a workspace and run prep

Pick an empty working folder (separate from your permanent library), drop your raw dump into it, and run
`prep`. The first run **initializes** the workspace: it creates the `0`–`6` folders and the
`.photos-ingest/` control dir, moves your dump into `0-sources/`, and seeds the config.

```bash
cd /path/to/working-folder       # your dump can already be sitting here
photos-cartographer prep plan    # plan the work (writes nothing yet)
photos-cartographer prep dry-run # inspect the exact plan that execute will run
photos-cartographer prep execute # apply it
```

Every phase follows the same **plan → dry-run → execute** rhythm: planning never mutates, dry-run shows
the *real* serialized plan, and execute applies only a validated plan. Nothing is deleted (duplicates
go to a recoverable quarantine) and nothing is overwritten.

After this, `prep` has sorted your media: photos into `5-photos-by-date/`, videos into
`4-videos-by-date/`, untimestamped media into `2-missing-metadata/`, redundant JPEGs (RAW siblings)
into `3-redundant-jpgs/`, and non-media into `1-strays/`. `0-sources/` is left empty.

> From now on, `0-sources/` is the **only** inbox for new dumps — never drop files at the workspace
> root again (prep will hard-block on a misplaced entry).

### Review your config (do this once, at the start)

The first `prep` run seeds `.photos-ingest/photos-00-config.json` from built-in defaults, then treats
that file as **authoritative for this workspace**. The defaults are *my* choices and may not match
yours — **open it and tune it before you go further.** Worth checking:

- **`media_extensions`** — which extensions count as `image` / `raw` / `video`. Anything not listed is
  treated as non-media and parked in `1-strays/`. If you shoot a RAW format that isn't in the list
  (e.g. Fuji `.raf`, Olympus `.orf`), add it here or those files won't be organized or geotagged.
- **`gpx_root`** — where geotag looks for your GPX tracks.
- **`merge.library_root`** — the permanent library merge writes into.
- **folder names**, timezone defaults, and the GPX matching thresholds.

Prep helps you catch the common mistake: when it sets a file aside as a stray, it asks `exiftool` what
the file actually is, and if that's an image or video it **warns you in the plan output** — e.g.
*"Dump contains .raf files that exiftool sees as media … add '.raf' to media_extensions and re-run."*
It never reclassifies on its own; you decide, edit the config, and re-run `prep`.

Config edits are **fingerprinted**: changing the extension or folder settings restales exactly the
downstream stages that depend on them, so a later re-run recomputes what's needed and nothing else.

---

## 3. Sort photos into destinations

This is the one step only you can do: move photos from `5-photos-by-date/` into a destination tree
under `6-photos-by-dest/`. Use a geographic hierarchy — ideally `year/country/city/location`:

```
6-photos-by-dest/2026/Belgium/Brussels/Atomium/
6-photos-by-dest/2026/Belgium/Brussels/Grand-Place/
6-photos-by-dest/2026/Belgium/Bruges/Markt/
```

A *destination* is just any folder that directly holds photos; the intermediate folders become
propagation points for timezone and GPS-fallback decisions. (See
[Destinations and the by-dest tree](concepts.md#destinations-and-the-by-dest-tree) for why the
hierarchy pays off.) Videos stay in `4-videos-by-date/` — `6-photos-by-dest/` is photo-only.

### Then re-run prep — mandatory

```bash
photos-cartographer prep plan && photos-cartographer prep execute
```

A prep run **must** happen after your most recent by-date → by-dest move, before geotag. It's a hard
requirement, not advice: prep recognizes the moves (stat-only, no re-reading pixels), carries identity
forward, and refreshes the handoff geotag depends on. Skip it and geotag hard-stops, telling you to
re-run prep.

---

## 4. Geotag — the iterative loop

Geotag resolves **time first, GPS second**. You converge through a short loop: run, fix the few
decisions it surfaces in the browser editor, re-run, repeat. Each fix unlocks the next stage.

```bash
photos-cartographer geotag plan   # compute proposals; report blockers/decisions
photos-cartographer edit          # open the browser editor on this workspace
```

The order is forced (the editor enforces the same gates — **Time → Drift → GPS**):

1. **Resolve timezones** (Time view). Most destinations auto-resolve by inheritance; you only touch the
   ones with no proposal. Save, then re-run `geotag plan` and reload.
2. **Validate drift** (Drift view). Any clock offset that wasn't measured against the track (manual or
   timezone-derived, no GPS-anchored frame) must be confirmed against the GPX track before placement —
   scrub the photo along its track segment until it lines up. **An untouched at-risk bucket blocks the
   run**; you must affirm even "no change." Save → re-run `geotag plan` → reload.
3. **Place GPS leftovers** (GPS view). Whatever the track and native GPS couldn't place shows up as a
   short worklist: drop a per-destination fallback coordinate, or place individual photos on the map
   (paste a `lat, lon`, search a place, or pan a crosshair; shift-click to place a run at once). Save →
   re-run `geotag plan` → reload.

The cycle each time is **edit → Save → `geotag plan` → reload**. Repeat until `geotag plan` reports the
executable plan is ready and clean. Full editor mechanics: [editor guide](editor.md).

---

## 5. Execute, finalize, merge

```bash
photos-cartographer geotag execute    # apply the validated time/GPS plan to the photos
photos-cartographer geotag finalize   # seal the audit record + archival package

# One-time, the first time you point at a library:
photos-cartographer merge init-library /path/to/your/library

photos-cartographer merge plan        # plan the merge into the permanent library
photos-cartographer merge dry-run     # inspect it
photos-cartographer merge execute     # move the finished set into the library
```

`merge` joins your finalized `6-photos-by-dest/` set into a permanent folder-based library (digiKam, or
anything that reads a plain folder tree), recording per file exactly where it landed and whether it was
renamed to avoid a collision. No library file is ever overwritten.

After a successful merge the workspace is **sealed** — done. New photos start a fresh workspace.

---

## The loop at a glance

```
dump → prep (plan/dry-run/execute) → YOU sort into 6-photos-by-dest → re-prep
     → geotag plan ─┐
                    │  edit timezones → Save → geotag plan → reload
                    │  validate drift  → Save → geotag plan → reload
                    │  place GPS       → Save → geotag plan → reload
                    └─→ geotag execute → finalize → merge → sealed
```

You can run prep → sort → re-prep over several cycles before geotagging, and add more dumps (via
`0-sources/`) any time before the final merge. See [concepts](concepts.md) for the model underneath all
of this.
