# Quick start

End-to-end: from a downloaded executable to a map-complete shoot — or a whole dump — merged into your library. If a term here
is unfamiliar (camera group, destination, drift check), the [concepts guide](concepts.md) explains the *why*;
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
executable — it's how you retune the defaults a new workspace starts with, without touching the binary.
The commands below are written as `photos-cartographer`: put both files in a folder on your `PATH`, or
call the executable by its path.

The executable is a zipapp: it runs like a plain script but **does not embed Python**, so the host
needs a `python3`. Running bare `photos-cartographer` prints the phase list; `photos-cartographer
<phase>` prints that phase's commands, and `photos-cartographer <phase> <command> -h` its options — the
CLI is self-documenting.

### Prerequisites

The pipeline shells out to a few standard command-line tools (it doesn't bundle them):

| Tool | Used for |
|---|---|
| **python3** | runs the executable (the zipapp doesn't embed Python) |
| **exiftool** | reads/writes photo time & GPS metadata — prep refuses to start without it |
| **ImageMagick** (`magick`, or `identify`) | the photo fingerprint (decoded pixels = stable photo identity) + editor previews |
| **ffmpeg** | the video fingerprint |

Without ImageMagick or ffmpeg, prep warns and the photos or videos it cannot fingerprint stop it, and
merge refuses to start without ImageMagick, so treat both as required. SQLite comes with Python — nothing to install. **ZFS** is optional (it enables
snapshots before each change; the safety model stands without it). The decision editor needs only a
browser; its map tiles and place search use OpenStreetMap at runtime and degrade gracefully offline.

> Just want to look around first? `photos-cartographer edit --demo` opens a read-only tour on bundled
> example data — no workspace, no setup. See the [editor guide](editor.md).

### Upgrading from 3.0.0

Replace both files. A workspace begun under 3.0.0 needs one setting added to its
`.photos-ingest/photos-00-config.json`: `"gpx_track_precedence": []` keeps every track ranked alike, as
before; see [ranking your devices](concepts.md#placing-each-photo) for what to put in it.

Then run `prep plan` and `prep execute` again: prep now reads more of each photo's time fields, and geotag refuses
a workspace prepped without them. A drift check you confirmed under 3.0.0 is asked again, since a confirmation now
names the tracks it was made against.

### Upgrading from 2.0.0

Replace both files: a `photos-config-defaults.json` from 2.0.0 lacks settings this version needs, and a
new workspace would refuse to start from it. A workspace begun under 2.0.0 can be finished, but its
`.photos-ingest/photos-00-config.json` must be updated by hand first — every run names what is wrong:

- **add** the settings that replaced the shared thresholds: `gpx_tracks_agree_max_distance_meters`,
  `gpx_anchor_max_segment_gap_seconds`, `gpx_anchor_same_pass_max_seconds`, `gpx_anchor_stay_max_seconds`,
  `gpx_anchor_stay_distance_meters`, `gpx_anchor_decision_tolerance_seconds`,
  `gpx_extrapolation_heading_seconds`, `gpx_extrapolation_max_distance_meters`,
  `gpx_extrapolation_max_speed_kmh`, `clock_offset_same_day_max_difference_seconds` and
  `drift_check_track_window_seconds` (the error gives each one's default; the new
  `photos-config-defaults.json` has them all);
- **remove** `photo_anchor_interpolation_max_gap_seconds` and `photo_anchor_extrapolation_max_seconds`.

Then run `prep plan` and `prep execute` again: this version fingerprints every file over its whole
content, so the first run fingerprints every file once more (slow on a big workspace; single-frame
photos keep the fingerprint they had). Geotag and merge refuse a workspace until that is done.

Some answers you gave under 2.0.0 are asked again. A clock-offset proposal you accepted then stops
`geotag plan`, naming the field: accept it again in the editor, which now records the offset you
accepted. A timezone you took by ticking "accept proposed" is asked again (that field is gone), unless
the destination inherits it from a folder above; zones you wrote by hand stay. Your library needs nothing.

---

## 2. Initialize a workspace and run prep

Pick an empty working folder (separate from your permanent library) on a single filesystem — every
phase refuses a workspace with a folder mounted from another volume — and drop your raw dump into it.
Then plan:

```bash
cd /path/to/working-folder       # your dump is sitting here
photos-cartographer prep plan    # plan the work (no photo is moved or changed)
```

The first `prep plan` creates the hidden control folder `.photos-ingest/`, seeds the workspace's
configuration in it, and prints a **FIRST RUN** notice: review the configuration *now*, before anything
is executed (next section). Then plan again, inspect, and apply:

```bash
photos-cartographer prep plan    # re-plan under the configuration you reviewed
photos-cartographer prep dry-run # summarize the saved plan that execute will run
photos-cartographer prep execute # apply it
```

The first `prep execute` **initializes** the workspace: it creates the `0`–`6` folders, moves your dump
into `0-sources/`, and organizes it from there.

Every phase follows the same **plan → dry-run → execute** rhythm (geotag has no dry-run; its plan *is*
the review): planning changes nothing but the fingerprints it keeps, dry-run checks and summarizes the
*real* saved plan, and execute applies only that plan, once it still holds. Nothing is deleted
(duplicates go to a recoverable quarantine) and nothing is overwritten.

After this, prep has sorted your media and renamed each file by its recorded time: photos into
`5-photos-by-date/`, videos into `4-videos-by-date/` (both in one folder per day), media with no
recorded time into `2-missing-metadata/`, JPEGs that sit beside a RAW of the same name into
`3-redundant-jpgs/`, and non-media into `1-strays/`. `0-sources/` is left empty.

> From now on, `0-sources/` is the **only** inbox for new dumps — never drop files at the workspace
> root again. Every phase stops on an entry at the top level that doesn't belong there, and names it.

> **Copy each dump so it can't overwrite anything.** The pipeline never overwrites a file — but that
> protection starts when prep runs. If your own copy command replaces a same-named file while you dump
> (`cp a/IMG_1234.jpg 0-sources/` then `cp b/IMG_1234.jpg 0-sources/`), the first file is gone before
> prep ever sees it, and nothing can recover it. Dump each source into its **own subfolder** of
> `0-sources/` (prep then handles same-named files from different subfolders without losing either),
> or copy with `cp -n` / `rsync --ignore-existing`, and check the file counts before running prep.

### Review your configuration (once, at the first plan)

The first `prep plan` seeds `.photos-ingest/photos-00-config.json` from the defaults, then treats that
file as **authoritative for this workspace**. The defaults are *my* choices and may not match yours —
**open it and tune it before you go further.** Worth checking:

- **`media_extensions`** — which extensions count as `image` / `raw` / `video`. Anything not listed is
  treated as non-media and parked in `1-strays/`. The raw list is `cr2`, `cr3`, `nef`, `arw`, `dng`: if
  you shoot another RAW format (e.g. Fuji `raf`, Olympus `orf`), add it — lowercase, without the dot —
  or those files won't be organized or geotagged.
- **`gpx_root`** — the folder geotag reads your tracks from (`*.gpx` files, searched beneath it). The
  default, `/srv/pictures/gpslogs/gpx`, is mine: if that folder doesn't exist on your machine,
  `geotag plan` stops. Point it at your tracks, or set it to `""` to geotag without tracks. It must lie
  outside the managed `0`–`6` folders (inside `.photos-ingest/` is fine). Keep track files (`.gpx`,
  `.kml`, `.kmz`, `.igc`, …) out of the dump: prep stops on one.
- **`camera_time_and_timezone_policy.default_folder_timezone`** — empty by default. Set it to your home
  zone (e.g. `"Europe/Brussels"`) and the editor offers it as a one-click answer; it is never applied on
  its own.
- **`merge.library_root`** — the permanent library merge writes into (default `/srv/pictures/5-finished`).
  You can also set it later with `merge init-library <path>`.
- **`folders`** (the names of the `0`–`6` folders) and the track-matching thresholds (`gpx_*`, each
  bounding one thing; the defaults suit slow, narrow places such as museums and parks).

Prep helps you catch a missing extension: when it sets a file aside as a stray, it asks `exiftool` what
the file actually is, and if that's an image or video it **warns you in the plan output** — e.g.
*"Dump contains .raf files that exiftool sees as media (…) but media_extensions config does not list —
they will be set aside in 1-strays."* It never reclassifies on its own; you edit the config and re-run
`prep plan`.

Config edits are **fingerprinted**: any edit makes every saved plan stale — re-plan before executing —
while costly work (fingerprints, parsed tracks) is redone only where it depends on what you changed.
Every setting must be in the file: a missing one, one cartographer does not know, or an invalid value
stops the run, named.

Re-planning is cheap even before you execute anything: a plan remembers the fingerprints it computed,
so tuning the config and running `prep plan` again reuses them instead of re-reading every photo. Only
`prep execute` makes them permanent, so run it once the plan looks right.

---

## 3. Sort photos into destinations

This is the one step only you can do: move photos from `5-photos-by-date/` into a destination tree
under `6-photos-by-dest/`. Move them, don't rename them — a file outside the inbox whose name isn't the
one prep gave it stops prep, which names the file and the name it should carry. Build a tree of places —
for example `year/country/city/place`:

```
6-photos-by-dest/2026/Belgium/Brussels/Atomium/
6-photos-by-dest/2026/Belgium/Brussels/Grand-Place/
6-photos-by-dest/2026/Belgium/Bruges/Markt/
```

A *destination* is any folder that directly holds photos (a folder may hold photos *and* sub-folders —
that's fine); a folder holding only sub-folders is a container, where you set a timezone, a country or a
GPS fallback once for everything inside. A destination has **one** timezone: photos taken in another
belong in a folder of their own. (See
[Destinations and the by-dest tree](concepts.md#destinations-and-the-by-dest-tree) for why the
hierarchy pays off.) The tree you build is the tree merge creates in your library.

Before geotag can run:

- **every photo must leave `5-photos-by-date/`** — into a destination, or out of the workspace;
- `6-photos-by-dest/` holds **photos only** — videos stay in `4-videos-by-date/`;
- photos with no recorded time stay in `2-missing-metadata/` — one in a destination stops geotag;
- no `jpg` / `tif` development subfolder in a destination, in any case — `JPG` too (development happens in
  the library, after merge).

### Then re-run prep

```bash
photos-cartographer prep plan && photos-cartographer prep execute
```

A prep run **must** come after your most recent move into `6-photos-by-dest/`, before geotag: prep
recognizes the moves (from sizes and times, without re-reading pixels), carries each photo's identity
forward, and refreshes the record geotag works from. If `0-sources/` is empty, `geotag plan` runs this
prep for you — but only when prep's plan just records your moves. If that plan would move, rename or
set aside a file, geotag stops and leaves the plan for you to review with `prep dry-run` and apply with
`prep execute`. If `0-sources/` holds a new dump, geotag stops and tells you to run prep.

---

## 4. Geotag — the iterative loop

Geotag resolves **time first, GPS second**. You converge through a short loop: plan, settle the few
decisions it surfaces in the browser editor, plan again, repeat. Each answer unlocks the next stage.

```bash
photos-cartographer geotag plan   # compute proposals; report what stops it or needs you
photos-cartographer edit          # open the browser editor on this workspace
```

### The first `geotag plan` may stop before the editor

- **The tracks folder is missing** — `Configured gpx_root does not exist or is not a directory`. Fix
  `gpx_root`, or set it to `""` to plan without tracks. Tracks of which not one can be read stop it too.
- **Unknown camera groups** — the first time it sees a camera, geotag stops and prints the two
  `device_groups` lists ready to paste into `camera_time_and_timezone_policy` in your config. A new
  camera is printed in **both**: keep it in `phones` if it is a phone (it records its own timezone), or
  in `fixed_clock_cameras` if it is a camera with a hand-set clock — and delete it from the other.
  Files that name no camera at all are not asked about.
- A photo with no recorded time, or one prep could not fingerprint, in `6-photos-by-dest/`; a link
  among the photos; a time that falls at a daylight-saving change. Each is named, with what to do;
  [What stops a run](concepts.md#what-stops-a-run) lists them all.

### Then the editor

The order is forced (the editor enforces the same gates — **Time → Drift → GPS**):

1. **Timezones and clock offsets** (Time view). For each place, say which **country** it is in — once,
   on the highest folder where it's true (`Belgium` above): a country with one timezone gives it to
   everything inside. In a country of several timezones, each destination picks one of that country's.
   Or write a zone by hand on any folder; folders below inherit it. Your configured default zone is
   offered as one click, never assumed. A destination whose photos record another offset than its zone
   (a phone left on home time) waits until you move them, choose another zone or keep this one for them.
   A camera's clock offset found from its own GPS-tagged photos applies itself when they agree (by
   default, two or more photos); an offset its GPS fixed elsewhere the same day is proposed for its other
   destinations of that day. Otherwise you accept the proposed offset or type one. An accepted proposal
   is asked again if a later run proposes a different offset.
2. **Check drift** (Drift view). Every clock offset the camera's own GPS did not fix — derived from the
   timezone, typed by hand, or from a spot where the track stood still — is checked against the GPX track
   before it places anything: scroll the photo along its track until it lines up, or confirm it as shown.
   An offset derived from the timezone is asked about only here (where no track covers the photos, you
   accept it in the Time view instead). **An untouched
   check blocks the run**; you must confirm even "no change", and a confirmation holds only for the offset
   you confirmed.
3. **Place GPS leftovers** (GPS view). Whatever native GPS and the tracks couldn't place shows up as a
   short worklist, each photo with the reason the tracks didn't place it: set a per-destination fallback
   coordinate, place photos on the map (paste a `lat, lon`, search a place, or pan a crosshair;
   shift-click to place a run at once), or leave a photo unlocated.

The cycle each time is **edit → Save → `geotag plan` → reload**. Repeat until `geotag plan` says the
executable plan is `ready` and points you at `geotag execute`. Full editor mechanics:
[editor guide](editor.md).

---

## 5. Execute, finalize, merge

```bash
photos-cartographer geotag execute    # write the corrected times + positions, rename by local time
photos-cartographer geotag finalize   # write the complete record + archival package
# From here, leave 6-photos-by-dest/ alone: merge refuses a photo changed since finalize.

# One-time, the first time you point at a library:
photos-cartographer merge init-library /path/to/your/library

photos-cartographer merge plan        # plan the merge into the permanent library
photos-cartographer merge dry-run     # summarize it
photos-cartographer merge execute     # move the finished set into the library
```

`geotag execute` never writes over a photo you edited since the plan — re-plan instead. `finalize`
prints how every photo got its position (its own GPS, matched / interpolated / extrapolated along a
track, set by you, its folder's fallback) and refuses if the plan no longer holds or a photo changed
since execute.

`merge init-library` marks the folder as a library (an empty `.photos-library` file) and records it as
`merge.library_root` — every other setting keeps its value, though the file is rewritten with its keys sorted and
non-ASCII characters as `\u` escapes; without a path it marks the configured one and writes nothing. `merge` moves your finalized
`6-photos-by-dest/` tree into the library at the same paths — digiKam, or anything that reads a plain
folder tree — recording per file exactly where it landed and whether it was renamed. No library file is
ever overwritten: a different photo under a taken name gets a numbered name; the same file already
there is not copied twice. The same picture with different metadata (the library's copy lacking the time
and position geotag wrote, say) is held back, both files named, for you to settle. Merge moves only
photos by destination: videos, untimed media, redundant JPEGs and strays stay in the workspace.

When every photo is in the library, the workspace is **sealed** — done; if any photo was held back, fix
it and run `merge plan` and `merge execute` again. New photos start a fresh workspace. The full record of
what was done, and why, is `.photos-ingest/photos-35-archive.tar.gz`: keep it if you want the record when
the workspace goes away.

---

## The loop at a glance

```
dump → prep plan → review config → prep plan / dry-run / execute
     → YOU sort into 6-photos-by-dest → re-prep (or let geotag plan run it)
     → geotag plan ─┐
                    │  classify cameras / fix gpx_root (first run only)
                    │  edit timezones + offsets → Save → geotag plan → reload
                    │  check drift              → Save → geotag plan → reload
                    │  place GPS                → Save → geotag plan → reload
                    └─→ geotag execute → finalize → merge → sealed
```

You can run prep → sort → re-prep over several cycles before geotagging, and add more dumps (via
`0-sources/`) any time before the final merge — after a geotag execute too, which you then plan, execute
and finalize again. See [concepts](concepts.md) for the model underneath all of this, and the
[specification](https://sigfridvonshrink.github.io/photos-cartographer/) for exactly what each phase guarantees: [prep](https://sigfridvonshrink.github.io/photos-cartographer/intent/prep.html),
[geotag](https://sigfridvonshrink.github.io/photos-cartographer/intent/geotag.html), [merge](https://sigfridvonshrink.github.io/photos-cartographer/intent/merge.html).
