# photos-cartographer — what is open

*Every entry stands alone: what it is, why it matters, what blocks it.*

- **What this is:** [`README.md`](README.md). **The record:** [`HISTORY.md`](HISTORY.md).

*Open items: **5** — 30 to 32, 49, 53.* 🛑 Numbers are never reused; the next is **58**.

---

## Open

---

### 30. Measuring the human input a trip costs

**Why:** the tool promises every photo on the map with the least manual work, and nothing counts the work. Each
safety fix turns a silent guess into a question or a refusal — rightly, each time — so the promise can wear away one
question at a time with nobody seeing it. The plan counts photos by how they were placed (completeness); it does not
count what the user had to answer to get there.

**What to do:** have geotag count, per plan and carried into the summary and the archive manifest: the decisions it
asked for, by kind (timezone, clock offset, drift confirmation, photo review, folder fallback, content mismatch);
how many took effect without the user (applied themselves, kept from earlier); how many the user answered; how many
answers went stale and were asked again; and the photos each answer covered. Then photos per answer is the measure,
and a change that adds questions shows as a number.

**Open:**
- What counts as one input: a cell, a save, or a distinct value (one offset accepted for five days shown as one row).
- Whether re-runs count: a plan run three times while the user answers is one trip's work, not three.
- Whether a refusal that sends the user to fix something outside the decision files (a track removed, a folder
  moved) is counted, and how it is known to have happened.
- Whether the count belongs to the record (photos-25, manifest) or is a report only. With the ground-truth set of
  item 32 it becomes a regression figure: questions asked for a fixed set of trips.

### 31. Real trips as fixtures, with the person taken out

**Why:** the tests' tracks and photos are synthetic, built by the same reasoning as the code, so both agree where
both are wrong — which is how the defects of the 2026-11-14 review survived. Real trips are the cure, and the
repository is public: a raw track shows where the owner slept and walked and when, photos carry faces, device serial
numbers and owner names, and a filename or a folder name carries a place and a date.

**What to do:** a tool that turns a real workspace into a fixture that keeps what the pipeline's judgements depend
on and nothing else: metadata without pixels (a stub image carrying the tags); tracks moved as a whole by a fixed
shift in place and in time, kept exact in shape, speed, gaps and their relation to the photos; the stretches round
lodging and home cut; serials, owner, make-specific identifiers and software tags replaced, one for one, so camera
groups still form as they did; folder and file names replaced. The real set stays outside the repository.

**Open:**
- Whether a shift is enough: a track's shape names its city to anyone who looks. Rotation or mirroring would hide
  it and keeps distances; it breaks nothing the code reads except the timezone a place implies, which is given by
  hand anyway.
- Which tags a stub must carry for prep and geotag to treat it as they treat the original, and whether the content
  fingerprint can be honest on a stub (it is of the pixels).
- Whether shifting time keeps DST and day boundaries where they were: a shift of whole weeks does, of hours does not.
- Who checks a fixture before it is committed, and against what list.

### 32. A ground-truth set, and a harness that scores against it

**Why:** 1195 tests show the code does what the corpus says. None shows the corpus yields the right time and place:
whether a value written is the true one has no oracle. Thresholds are tuned by argument, and a regression in
inference shows nowhere. The corpus guards the how; this is the missing guard on the what.

**What to do:** keep a set of real days with the answer known — the camera's true clock offset (a photo of a clock
showing seconds, morning and evening), photos carrying a trusted position that is hidden from the run and then
compared with where the tracks put them, and a second logger held out the same way. A harness runs plan on each
day and scores: offset error, position error by method (point, between two, past an end), photos placed and left
unplaced, wrong auto-applied offsets (the figure that must be zero), and the questions asked (item 30). The scores
are kept, so a change to a threshold or to the inference is read as a difference, not argued.

**Open:**
- Where the set lives: the real one cannot be in the repository (item 31); the harness can, run against a path.
  Whether a depersonalised copy runs in CI.
- The first days: the London trip of late 2026 — museums, a castle, a train out and back, two loggers — recorded
  for this on purpose. One trip is one sample: thresholds tuned on it alone fit London.
- What is scored as wrong: a position within the track's own error is right; the bound needs a figure.
- Whether a threshold change must show its score before it is ruled.

---

*Items 35 to 46 come from the adversarial review of time handling, 2026-11-14 (33, 34 and 41, from the same review, are ruled and built). Each is a choice between behaviours:
none is coded until ruled. What the review found that was plainly wrong was fixed with it.*

### 53. Videos sorted into destinations, and geotagged

**Why:** videos stay in videos by date, never sorted, so geotag gives them no place and no corrected time: their
names keep the camera's clock (stated as final by BACKLOG 43), they carry no position, and merge leaves them out of
the library. A trip's videos are as much the trip as its photos. The owner wants them sorted into destinations and
geotagged as photos are (2026-11-16).

**Ruled 2026-11-16 (the shape; to be built with the London trip's videos as test data):**
- Sorted beside the photos, in the same destination folder: `RUL-sort_photos_only` is reversed.
- MOV and MP4 only, written through exiftool's QuickTime tags; an MTS or AVI sorted into a destination stops geotag,
  its way out being to move it back to videos by date.
- A video's clock is its body's: the photos' camera group when the model and serial match, a group of its own
  otherwise.
- Its time is QuickTime CreateDate, read as UTC as the format says, with a per-camera setting for bodies that write
  local time.
- Its position is its start, as one point.
- Merge takes it into the library beside the photos.

**Open:** split into buildable items once the London trip's videos are in hand — what each step changes in prep's
sorting check, geotag's write path and merge.

---

### 49. Retake the walkthrough and every screenshot

**Why:** `docs/walkthrough.md` is a real run of v2.0.0 in thirty-nine screenshots, and the hero GIF and the shots in
`editor.md` and `concepts.md` are of the same version. The editor and the console show other things now (item 17
lists them), and the walkthrough's "Geotag won't proceed" step predates geotag running prep itself. Split from item 17
on 2026-11-14; until it is done the walkthrough carries a note saying which version it shows.

**What to do:** run a real trip through the current build and retake the walkthrough end to end, the hero GIF, and
each shot in the other guides that shows something changed; then take the note off. The London trip (item 32) is the
natural run to take them from.

**When:** after item 17's text, so the pictures are taken once.
