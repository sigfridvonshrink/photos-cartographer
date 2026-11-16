# Editor guide

The decision editor is a small single-page web app the pipeline serves locally. It's where you answer
the questions geotag can't decide on its own — timezones, clock offsets it won't apply by itself, and
photos nothing could place — each shown with its proposal and the evidence behind it. It writes those
answers back into the decision records geotag reads (`photos-21`, `photos-22` and `photos-23` in
`.photos-ingest/`).

This guide assumes you've reached the geotag loop in the [quick start](quickstart.md); the [concepts
guide](concepts.md) explains the ideas (camera groups, day buckets, drift, cascading) the views act on.

---

## Launching it

```bash
cd /path/to/workspace
photos-cartographer edit
```

Like every phase, `edit` operates on the **current-directory workspace** (no workspace-naming
argument). It refuses to start if the current directory isn't an initialized workspace, or is a sealed
(already merged) one. It serves on port **8765** by default (moving up to the next free port if that one
is busy) and binds all interfaces, so you can reach it from a laptop browser while SSH'd into a server —
it prints a clickable `http://<host>:8765/` link. Use `--host 127.0.0.1` for local-only, `--port N` to
choose a port. When bound to loopback, startup also prints a ready-to-copy `ssh -L …` tunnel command for
reaching it from your local machine. Only one editor can have a workspace open at a time; a second one
is refused and told who holds it. Stop it with Ctrl-C.

### In the console

`photos-cartographer console` has the same editor as its **Edit** tab, so you can plan geotag and edit
its decisions from one browser page. The Edit tab holds to the same rules: it won't open the editor on a
workspace that isn't initialized or is sealed, and it takes the one-editor lock the first time you open
it and keeps it until the console stops — meanwhile `photos-cartographer edit` on the same workspace is
refused, and the other way round.

When a `geotag plan` you started from the console's Geotag tab finishes, the Edit tab reloads by itself
to show the new records. **Save first**: the reload drops edits you haven't saved.

### Demo mode — zero setup

```bash
photos-cartographer edit --demo
```

A read-only tour on bundled example data — **no workspace, nothing written**. The fixtures, web assets,
and map library are all packaged inside the executable, so `--demo` works straight from the downloaded
release: it needs only a `python3` host and a browser. (No photo previews in demo — it touches no
workspace files. Map tiles and place search need internet.) It's the fastest way to see what the three
views look like before you have real data.

---

## The working loop

The editor edits decisions; it does **not** recompute the pipeline. The loop is always:

> **edit → Save → re-run `photos-cartographer geotag plan` → reload the page**

There is **no in-app "re-run" button**. Every gate and stale notice tells you to re-run in a terminal
(or from the console's Geotag tab) and reload. Until you do, anything the editor shows about *outcomes* —
the **Effective (advisory)** box, the inherited badges — is a preview; geotag computes the authoritative
result on the next run.

The editor only ever writes the **`user_decision`** field of each decision, round-tripping every other
field exactly as geotag produced it. The **Save** button is disabled while any field is invalid: a
timezone that isn't one, a zone that isn't one of the chosen country's, an offset that isn't a whole
number of seconds, a coordinate out of range or with only one half. **Reset** in the header throws away
every unsaved edit; the **reset** button on a decision throws away that one.

A save is refused, and **nothing is saved**, when:

- **a run is in progress** on the workspace (a save takes the workspace lock) — save again when it
  finishes;
- **the records changed on disk since the editor loaded them** — typically a `geotag plan` ran in the
  meantime. Your edits were made against decisions that are no longer the ones on disk, so the editor
  won't lay them over the new ones: reload the page to see the decisions as they are now, and make your
  edits again;
- **the workspace is sealed.**

A successful save names the files it wrote and reminds you to run `geotag plan` and reload. Each record
it changes is first copied beside itself under the next free `-NNN` number — `photos-23-gps-decisions-002.json`,
say — in the same series a re-plan's copies are in, so an answer lost to a mistaken save can be found again. The
configuration, when a save writes a camera's class into it, keeps no copy. The records are written one after
another — photos-21, photos-22, photos-23, then photos-25 and the configuration — so a save cut short (a power cut,
the editor killed) leaves the earlier ones saved and the later ones as they were: save again to finish it.

**Coming from 2.0.0:** an offset you accepted under 2.0.0 didn't record which offset it accepted, so
`geotag plan` now stops on it. Open the editor: the decision says it was accepted for another proposal —
accept it again (or set the offset yourself), save, and re-plan.

---

## The views, and why they're gated

The header toggles between **Time → Drift → GPS**, in that order — and the order is enforced — with
**Cameras** before them, for a camera geotag has not met ([below](#cameras-view)), and **Execute** after,
for what `geotag execute` asks ([below](#execute-view)):

- **Time gates Drift** — the Drift view waits until every time decision is answered and geotag has been
  re-run (drift checks offsets that must already exist).
- **Drift gates GPS** — the GPS view waits until every drift check is confirmed (a wrong, unchecked
  offset would place photos at the wrong point on the track).

If you edit a Time or Drift decision, the views after it show a "decisions changed — re-run `geotag
plan` and reload" notice until you do.

In every view each decision carries a status: **needs input**, **resolved**, **auto** (geotag answered it
itself), **stale** (your earlier answer no longer fits — see [How edits reset
things](#how-edits-reset-things)), or **none** (an optional folder fallback left unset). An edit you
haven't saved is badged **edited**, an invalid one **✗ invalid**.

---

## Cameras view

The first time `geotag plan` meets a camera it stops, before it writes any decision, and prints the two
`device_groups` lists to paste into `photos-00-config.json`. The editor opens on the **Cameras** view
while there is such a camera: one row per camera group (its make and model, how many photos, a preview
on hover), and two choices — **a phone** (its clock is the network's, and it records its offset with each
photo) or **a camera with a clock set by hand** (its offset is found per day). Save writes your answer
into `camera_time_and_timezone_policy.device_groups` in `photos-00-config.json` — the same as pasting
the printed lists, every other setting left as it is — then re-run `geotag plan`. Pasting by hand still
works as before.

Below them, under **Cameras with a hand-set clock**, the view lists every camera with a hand-set clock among your
photos, each **one camera** (the default) or **several bodies**. Two bodies of one model that write no serial number
are one camera group: nothing in their photos tells them apart. Mark such a group as several bodies and an offset
its GPS gives is always a proposal for you to accept, noted as perhaps one body's; its days in different
destinations are decided apart; and its photos that disagree with the offset are never offered as wrong positions.
To tell the bodies apart, move one body's photos into a sub-folder and re-run prep — each folder then has offsets
of its own. Save writes the group into `camera_time_and_timezone_policy.several_bodies_groups` (or takes it out);
by hand, edit that list.

---

## Time view

A recursive tree of your destinations. For each one you settle its timezone, and for each camera on each
day its clock offset. Container folders (those holding only sub-destinations) are badged `container` —
they never block; you answer on them only to pass a value down.

![Time view — the destination tree, with a timezone and its inherited badge](screenshots/carto-15-geotag-edit-time-02.png)

*Screenshot from v2.0.0: the "accept proposed" checkbox is gone, an inherited zone shown here as "needs
input" now applies itself unless the destination's photos speak against it, and the panel now also
offers an "In country" choice.*

### Timezone

A destination has **one timezone** for all its photos. You answer it once, high in the tree; everything
beneath inherits it.

Where a destination has no zone, every folder above it with none asks too, naming the destinations inside that wait:
answer at whichever level the zone is true — the country, a region, the place itself. An answer passes down to
everything below, so the questions it settles there turn **resolved** at once, before any re-run; answer each
destination instead and the folders above stop asking. A folder said to be in a country of several timezones is not
asked (a zone there would reach nothing), and the folders inside it are.

- **Inherited** — a destination with no zone of its own takes the one of its nearest ancestor that has
  one, badged `inherited ⟵ <ancestor>`. It applies itself; the badge updates live as you edit
  ancestors.
- **In country** — say which country a folder is in (whatever the folder is called; it needn't be the
  country's own folder). A country with **one** timezone gives it to everything inside. A country with
  **several** gives none and lets none through from above: each destination inside answers for itself,
  and the **Manual timezone** list only offers that country's zones — unless its phone photos settle it:
  where exactly one of the country's zones had, at each photo's time, the offset the photo records, that
  zone applies itself, badged `from its photos`. A country is said **once, at the
  top of its tree**: below a folder that has one, the choice is locked and says where it was made, and
  choosing a country on a folder removes any country chosen inside it (the editor says which). The
  countries are the host's timezone database's own table — or, on a host without one, a copy downloaded for the
  workspace when `prep plan` asked, else the copy carried inside photos-cartographer.
- **The configured default** (`default_folder_timezone`) is only **offered**: a destination with nothing
  to inherit shows it with a **use** button, but it never applies by itself — so a place abroad is never
  timed in your home zone. Inside a country, it is offered only if it is one of that country's zones.
- **Manual timezone** — pick an IANA zone from the dropdown: the zones of the machine geotag runs on, so one
  your browser knows and that machine does not is never offered. It overrides an inherited one and
  **re-roots the chain**: every destination beneath inherits it (until one of them overrides in turn).

**When the photos disagree with the zone.** Phone photos record the offset from UTC they were taken at.
When some of a destination's photos record an offset its zone didn't have at that time, the zone does not
take effect and the destination asks — and nothing inside it inherits through it. The panel says how many
photos, gives one as an example, and names both offsets. Either pick the zone the photos were taken in,
move the photos taken elsewhere into a folder of their own and re-run, or tick **keep `<zone>` for
these photos** if the device was simply set to another zone. That word covers the offsets listed; a photo
arriving later with yet another offset asks again.

### Clock offset

One offset decision per camera group per destination — per **day** when the group spans more than one
day there, since a camera reset each morning has a per-day offset. A phone gets one (its row says
**phone**) only for a day whose own GPS reads its clock otherwise than its photos are read — see below. Offsets **never inherit** — each day stands alone, so no inherited badge appears on
them. See [why grouping is per-day](concepts.md#why-grouping-is-per-day-within-a-destination).

Days of one group with the same proposal are collapsed into one row (e.g. "3 Jul 2024 … 9 Jul 2024
(7 days)"); an answer there applies to every day in it. Click **▸** to show each day and answer one
separately.

You answer in one of two ways:

- **accept proposal (±Xh YYm ZZs)** — the button names the offset, and so does your answer. If a later run
  proposes a different offset, your acceptance no longer holds and the decision asks again: "Accepted when
  the proposal was X; it is now Y — accept it again, or set the offset."
- **manual offset** — your own value (camera time + offset = real UTC), set on the h/m/s spinner (scroll
  or ↑/↓ over a unit), in seconds in the box beside it, or — for a proposal found from GPS — as the
  **anchor real-UTC** of the proposal's example photo. Otherwise, as the **true time of a photo**: the
  decision's earliest photo is named (with a thumbnail) beside its camera time; type when it was really
  taken, in the destination's local time (UTC while the destination has no timezone), and the editor
  works out the offset from it. A time the destination's clocks skipped or showed twice at a
  daylight-saving change gives no single offset and is refused — use another photo's time or the offset.
  This is how a clock reset to its factory date is answered: no need to count the seconds since 2000.

An **Impact** line shows what the offset does to a photo: its camera time → the corrected local time (and
UTC). **clear** removes your answer.

What the proposal panel shows depends on where the offset came from:

- **Found from GPS** — the camera's own geotagged photos matched against your GPX tracks. Up to three
  **correction groups** ("N photos → offset", each with an example photo, the track it matched and its
  corrected local time). The recommended group has **accept**; any other has **use this** — one click,
  for every day in the row. An offset picked from a group counts as found by the camera's GPS, so the
  Drift view won't ask about it. A confident proposal can apply itself (status **auto**) as configured;
  otherwise you're asked, with a note saying why:
  - **a tie between visits** — the photos fit several visits of the tracks equally: pick the group of
    the day you were there;
  - **the tracks stood still** — the GPS says where the photos were but not when; the offset shown is
    one that fits. Accepting it sends it through the Drift view to check;
  - **photos that agree with no group** — named. Where they come one after the other at one end of the day,
    the camera's clock changed: the split is offered (below). Otherwise accept the offset most agree on: a photo
    whose own position it contradicts is then offered the track's position in the GPS view. For a group marked
    several bodies, they are likely the other body's: move that body's photos into a sub-folder.

  Photos skipped for having a track only outside the plausible time window, or none nearby, are counted.
- **The camera's clock changed this day** — the camera's GPS (on the tracks, or its fixes' times) shows two runs of
  photos, one after the other, each agreeing on an offset of its own: the clock was set between them (to local time
  at lunch, say). The panel names both runs and offers **split the day where the clock changed** — one tick settles
  the day, each part corrected by its own photos. Runs are told apart by when the GPS says the photos were taken, so
  a clock set back an hour, whose camera times repeat, is found too. For each photo without GPS that either part
  could have taken (or neither), pick **before** or **after** the change; the others go to their part unasked. If
  the clock did not change, answer the day's offset as usual instead. By hand: `accept_clock_change`,
  `accepted_change_offsets_seconds` and `photo_parts` in the day's cell.
- **From the GPS fixes' own times** — no track passes the photos' places, but their GPS fixes recorded
  the UTC they were taken at: each, less the camera time, is a reading of the offset. The panel lists a few
  ("camera 10:00:00 · fix 00:59:30Z → −9h 00m 30s"). Two or more that agree applied themselves (status
  **auto**); a single one waits for **accept proposal** — a stale fix repeats an old time. Where two fixes
  recorded the same time at different camera times (a stale fix), or their offsets lie too far apart, the
  fixes are not read, and a note says so.
- **Shared from the same day elsewhere** — no photo here has its own position, but the camera's GPS fixed
  its clock that day in another destination — by itself, by your acceptance, or as the group of its GPS
  you picked there. Where it applied itself there it applies here too; otherwise accept it here or set
  another. If the camera's GPS gives two different offsets on one day in
  two destinations, neither takes effect: both are shown, and you set the right offset by hand in the
  one that is wrong. There, **accept** reads **use the proposal as your own offset**: an acceptance would
  be withheld again, so the editor writes the proposal as your own offset (`manual_offset_seconds`) —
  by hand, write the same. A group you picked from the camera's GPS is held against an offset its GPS fixed by
  itself elsewhere that day the same way: if they differ, both are shown and the one fixed by itself
  waits for you, while your pick keeps its effect.
- **The day next to it** — no photo of this day has its own position here, but the camera's GPS fixed its clock the
  day before (or after) in this destination: its midnight fell mid-outing, say. Asked once, like the timezone's
  guess: with tracks by the photos there is nothing to accept here — confirm it in the Drift view, on the tracks; with
  none, **accept proposal** if the clock was not set in between.
- **The offset the photos record** — no GPS evidence, but the camera wrote, with each photo's time, the
  UTC offset its clock was set to, and they all agree (e.g. "2 photos record +01:00 from UTC"): the clock
  offset is its negative. Accept it only if the camera's time was right in that zone — a clock set to the
  wrong hour keeps its zone. Where GPX tracks cover these photos, it goes to the Drift view instead, like a
  local-time proposal. Where the photos record **different** offsets, none is proposed from them: the
  decision lists each offset with a photo of it — the camera's zone setting changed that day, or the tag
  is wrong — and you set the offset, or move the photos of each setting into a sub-folder and re-run.
- **Derived from the local time** — no GPS evidence, so the offset assumes the camera clock showed the
  destination's local time (daylight-saving aware, so summer and winter days differ). Accept it only if
  the camera really tracked local time — a camera left on home time would be wrong. Where GPX tracks
  cover these photos, there is **nothing to accept here**: the decision says to confirm it in the Drift
  view, against the tracks, once.
- **Too far from everything** — a local-time, recorded-offset or GPS-fix-time proposal that would put every photo of the
  day farther than a clock may be wrong (`gpx_anchor_max_clock_error_seconds`, two days by default) from
  every track point and from every photo another device took in this destination. The note says how far
  (e.g. "26.3 years from the nearest photo another device took here"): most likely the camera's clock
  was reset. **accept proposal** is greyed out — accepting would not take effect — so give the true time
  of one of its photos, or set the offset.
- **No proposal** — set the destination's timezone and re-run to get a local-time proposal, or enter the
  offset yourself. No local-time proposal is made when the photos' time falls at a **daylight-saving
  change** in that zone (a time that happened twice, or never): the zone gives two offsets there, and the
  proposal shows `timezone_ambiguous` with both. Set the offset yourself.

- **A phone's day** — the phone's photos with their own position put its clock elsewhere than their
  offset tags (or the zone) read it: say a phone set by hand an hour wrong. The note names both offsets
  and how many photos the day holds. Several photos agreeing applied it themselves (**auto**); one
  photo's waits for **accept proposal**. If the track is someone else's, tick **keep this phone as its
  photos record themselves** — its GPS here is set aside.

- **A phone's photos with no offset tag** — where the phone's tagged photos that day record the zone's
  offset, they are read by the zone and nothing asks. Else the phone's own GPS reads them (applied by
  itself), or — with none — the decision proposes the offset its tagged photos record, or the zone's:
  confirm it in the Drift view where tracks lie by them, or accept it here. The note says which photos.

### Files naming no camera

A destination holding screenshots, scans or stripped photos that record no offset gets one row, **Files
naming no camera** ("2 files"). Tick **read them as local time in `<zone>`** — the answer names the zone
and holds for such files arriving later, until the destination's zone changes. Or move them out, or give
them their offset, and run prep again. By hand: `unidentified_files.user_decision` in photos-21 (see the
[decision-JSON reference](../cartographer/editor/decision-json-reference.md)).

### A time at a clock change

A photo read by its destination's zone whose time falls at a **daylight-saving change** — 02:30 on the
night the clocks went back (it happened twice) or forward (it never happened) — gets a row of its own,
**Time at a clock change**, under its destination, with its thumbnail. Pick which of the two readings it
was (each shown with its UTC instant); for a time that never happened you may type another offset
(`+01:00`). Until each is answered, the time decisions are not complete. By hand, the same answer is
`utc_offset_seconds` in the photo's entry of `local_time_readings` (see the
[decision-JSON reference](../cartographer/editor/decision-json-reference.md)).

### A time changed since geotag wrote it

A photo geotag has written to whose time (`DateTimeOriginal` or its offset) was changed afterwards — in
another tool, or by a slip — gets a row of its own, **Time changed since geotag**, under its destination,
with its thumbnail. The panel names the time it holds, the one geotag wrote and the photo's own from
before geotag. Choose:

- **keep the time it holds** — this is the true local time. Geotag reads it by the destination's
  timezone and applies no camera clock offset to it, now or on any later run; the photo is placed and named
  by it, and its other time fields (`CreateDate`, `XMP:DateCreated`, IPTC) and its offset tag are written to
  match. It is not used to work out the camera's clock offset. A time the timezone shows twice, or never
  (at a daylight-saving change), is then asked like any other. If the photo's offset tag says another
  offset than the timezone's at that time, the panel says so: kept, the timezone wins, so a time set in
  another zone would be off by the difference — answer otherwise, or fix the time first;
- **take back geotag's time** — geotag writes its time again, as it decided it before the change.

The answer is for the time the photo holds now: change the photo's time again and it asks again. Until
answered, the time decisions are not complete. By hand: `keep` (`"new"` or `"geotag"`) and `answered_for`
(a copy of `held_time`) in the photo's entry of `changed_times` (see the
[decision-JSON reference](../cartographer/editor/decision-json-reference.md)).

---

## Drift view

The drift view lists the offsets **the camera's own GPS has not fixed** — written by hand, derived from
the local time, or found from a track that stood still — wherever GPX tracks cover the photos. A wrong
offset there would place every photo of that day at the wrong point on the track, so each must be
**confirmed against the track** before the GPS view opens.

Each row shows the camera group, where its offset came from, the offset and the day. In the panel:

- **Photo** tab — **‹ prev / next ›** chooses the photo that stands for the bucket (with a preview).
- **Track** tab — slide that photo along its GPX track under a fixed crosshair until it lines up:
  **scroll the wheel** over the map to step one track point per notch, or press **`[` / `]`** (one point)
  and **`{` / `}`** (ten). Each step sets the corrected offset for every photo in the bucket and
  confirms it; **clear — offset was right** takes the correction back.
- **corrected offset (seconds)**, or the **true time** of the bucket's photo (the one the Photo tab
  shows, typed in the destination's local time, UTC while it has none) — the correction typed rather than
  scrubbed: an offset you know, or the only way to give one where no track lies by the photos. Either
  confirms the bucket with that correction, as a scrub does. By hand: `corrected_offset_seconds` in the
  bucket's `user_decision`, with `confirmed`, `confirmed_offset_seconds` and `confirmed_against_tracks`
  (see the [decision-JSON reference](../cartographer/editor/decision-json-reference.md)).
- **confirm this bucket (offset is right as shown)** — the "don't move" answer. You **must** actively
  tick it: an untouched bucket **blocks** the run; inaction is never read as "no change."

A confirmation names the offset it confirmed. If that offset changes — you edit the Time decision, or a
re-run proposes another — the bucket asks again: "Confirmed for X; the offset is now Y — check it on the
track and confirm again."

It names the tracks it was made against too — the GPX files shown for the bucket, each by the SHA-256 of its
contents. Take one of them out of the tracks folder (it was a companion's) or replace it with another export of
the day, and the next run asks again: the photos would otherwise be placed on a track nobody looked at them
against. A track merely added beside the ones you saw leaves the confirmation standing. A bucket shown with no
track at all can still be confirmed; that holds only while no track lies by its photos. Your earlier answer is
kept as you wrote it until you confirm again.

Confirming refines the offset without altering your Time decision; the corrected offset feeds the
recomputed times on the next run.

![Drift view — sliding a photo along its GPX track under a fixed crosshair to recover the clock offset](screenshots/carto-22-geotag-edit-drift-track.png)

---

## GPS view

Per destination: a **folder fallback**, a worklist of only the photos nothing automatic could place, and
a summary line — files in total, how many keep their own GPS (`preserve`), are placed on or between
track points (`interp`), past a track's end (`extrap`), by the folder fallback, or still blocked. Geotag
marks every position it writes from the tracks as `matched`, `interpolated` or `extrapolated` in the
photo itself, so a rough position is never taken for a precise one.

Photos are placed in this order: the photo's own GPS → a coordinate you set for it → the tracks → the
folder fallback → otherwise blocked. No photo leaves geotag without a position: a blocked photo waits —
no plan is made — until you give its folder a fallback or it a coordinate, and finalize and merge refuse a
photo that holds none.

**A blocked photo** offers its **folder's fallback first**: **set the folder's fallback** opens that
destination's fallback, and one coordinate there places every photo of the folder nothing else places
(and, once they accept it, the folders inside it). Below it, **or a position for this photo alone**.

**Folder GPS fallback** — a single coordinate that places any photo in that destination nothing above
it could. It cascades downward like the timezone (badged `inherited ⟵ <ancestor>`), but unlike the
timezone it is **never applied by itself and never blocks**: an inherited fallback is a proposal you
*may* take with **accept inherited**. A fallback you set **re-roots the chain** for the destinations
beneath. Photos it places are marked as such (`manual_fallback`), so it's always clear the position
wasn't measured. **clear** takes a fallback back (to *no fallback*; destinations beneath then inherit
from above again).

![GPS view — a per-destination folder fallback](screenshots/carto-25-geotag-edit-gps-fallback.png)

**Why a photo wasn't placed.** A worklist photo says, in one line, why the tracks didn't place it —
your lead to the fix before you reach for the map:

- no tracks to place it by;
- the nearest track point is too far from the photo's time;
- the track has a gap there;
- the track jumps too far, or too fast, between the two points around the photo;
- **tracks disagree** — two track files (or two tracks in one file) cover that time in places too far
  apart, and nothing says which one the camera was with. Take the track that isn't this trip's out of the
  tracks folder and re-run.

**An own position the camera's offset contradicts.** A photo with its own GPS position that agrees with none of
its camera's other photos, once their agreed offset is in effect, is set against the track at its corrected time:
farther apart than an anchor may be, it is listed (`own_position_contradicted`), with both positions and how far
apart. It **asks nothing** — the photo keeps its own position — but most likely its GPS was wrong (a stale fix,
jitter): **take the track's position**, or set another; **keep its own position** takes it back. By hand: write
`manual_lat`/`manual_lon`. Where no track covers its corrected time, nothing is proposed: it keeps its own, and
photos-23 notes it (`contradicted_without_track`).

**Placing individual photos** on the map beside the photo (a thumbnail sits in the decision box; hover a
name in the worklist for a larger preview):

- **Paste `lat, lon`** straight from Google Maps into the coordinate field — it commits on paste and
  jumps the map to that point.
- **Search a place by name** (OpenStreetMap/Nominatim) — submit with Enter or the button; picking a
  result moves the map, then you "use map center" to set it.
- **Pan the crosshair** and "use map center" to drop a point by eye.
- **Copy / paste a location** between photos — "copy location" stashes the coordinate (and writes
  `lat, lon` to your system clipboard); "paste" applies it to the current photo. The next photo opens
  centred where you last placed one.

**A photo the tracks or the fallback already place** can be given a position of its own: under each
destination, a folded list — **N placed — by the tracks, by the fallback** — names those photos, each with
**set position**. A coordinate set there is that photo's alone and outranks both; it stays while it is set,
whatever tracks or fallback come to cover the photo later (**back to the tracks** / **back to the fallback**
takes it away). Saved, it is written as the entry you would write by hand: a `chosen_by_user` review item.

![GPS view — placing a photo on the interactive map beside it](screenshots/carto-26-geotag-edit-gps-per-photo.png)

**Place many at once with shift-click:** click a photo to select it (and set an anchor), then
**shift-click** another *in the same destination* to select the contiguous run between them. One
location you set then applies to every photo in the run. (Shift-clicking into a different destination
starts a fresh selection — runs never cross destinations.)

---

## Execute view

When `geotag execute` writes a photo's tags it takes the photo's content fingerprint again. If the pixels
are no longer what the plan pinned — or no fingerprint can be taken — the photo's writes are not
confirmed, its rename waits, and the run ends **partial**. The Execute view lists each such photo from
`photos-25-execution-summary.json`, with its preview (hover a row, or open it) and the two fingerprints.
Look at it: if it is right as it is, tick **accept this photo's content as it is now**, save, and run
`geotag execute` again — that run takes the new content as the photo's and goes on with it. An acceptance
holds for the content you saw: if the photo changes again, it asks again. By hand, the same answer is
`"accept_fingerprint_change": true` in the photo's entry of `fingerprint_mismatches` (see the
[decision-JSON reference](../cartographer/editor/decision-json-reference.md)).

---

## How edits reset things

Two reset behaviors worth knowing (both take effect on the next run):

- **Re-rooting** — setting a manual **timezone** or **folder fallback** on a folder makes it the new
  basis its descendants inherit, replacing whatever flowed from higher up. A descendant that set its own
  value keeps it (it overrides). A **country** works the same way, but only once per tree: a country
  chosen inside another country's folder is removed by the next run, which says so in the terminal and
  on the folder.
- **Restaling** — changing an upstream timezone, offset, drift confirmation or fallback makes what was
  computed from it (the corrected times, the GPS decisions, the executable plan) out of date;
  `geotag plan` recomputes it. Your decisions are **kept** while what they decide about is unchanged:
  a day's offset is found again by its day, a photo's coordinate by the photo itself, even after geotag
  renamed it. A photo you move to another folder (or whose folder you rename) is asked again: its
  coordinate was given for the folder it was in. An answer whose question has changed is never silently applied to the new one — it is
  marked **stale** and asked again: an acceptance of an offset no longer proposed, a confirmation of an
  offset no longer in effect or made on a track since taken out or changed, an inherited fallback that no longer exists, a zone kept for photos when
  one arrives recording yet another offset.

---

## Quick reference

| Action | How |
|---|---|
| Launch on a workspace | `photos-cartographer edit` (port 8765), or the console's **Edit** tab |
| Zero-setup demo | `photos-cartographer edit --demo` |
| Apply your edits | Save → `photos-cartographer geotag plan` → reload |
| Save refused: records changed | reload the page, make the edits again |
| Say which country a folder is in | Time view → timezone → **In country** (once, at the top of its tree) |
| Answer a clock offset | **accept proposal**, a group's **use this**, or a manual offset |
| Step a photo along the track (Drift) | scroll wheel, or `[` `]` (Shift `{` `}` for ×10) |
| Confirm an offset as it is (Drift) | tick **confirm this bucket** |
| Set a coordinate (GPS) | paste `lat, lon`, place-name search, or pan + "use map center" |
| Place a run of photos | click, then shift-click another in the same destination |
| Copy a location to the next photo | "copy location" → "paste" |

What geotag guarantees about each decision — what applies itself, what waits for you, what is asked again —
is in the [specification](https://sigfridvonshrink.github.io/photos-cartographer/intent/geotag.html); the decision files' fields are in the
[decision-file reference](../cartographer/editor/decision-json-reference.md).
