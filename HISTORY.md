# photos-cartographer — why

*What was decided and why, newest first. A record: never corrected forward. Per-commit detail is `git log`.*

## 2026-11-01 — a fixed time is a suffix on the device's own value

`time_only` replaced the field's whole value, so a phone's own `GPSProcessingMethod` — `fused`, `GPS` — was lost when
geotag fixed its time. Vasile: *"why not add a suffix like "_to" maybe to the original content? Maybe make this a rule
and instead of time_only we use _to everywhere, as an addon (suffix)?"* Asked whether positions should carry it too:
*"not sure we need the suffix because if the GPS was set, the time must have also been fixed. This also maintains
compatibility with what I have in my library. So the suffix would mean time fixed and gps kept or not yet set."* Asked
whether a field length limit restricts the tag: none in practice — EXIF bounds the value only by the segment holding
it, and a JPEG's whole EXIF block must fit in 64 KB; values to 1,000 characters round-tripped through exiftool in a
JPEG and an ARW, and exiv2 read `fused+carto-time` back from both. Of the suffixes offered: *"+carto-time is ok"*. The
bare position markers stay as they were; the suffix is appended once to whatever the field holds.

## 2026-11-01 — finalize copies prep's log; what it reads is not specified

Answered: the intent states the result, not the sources, except that an earlier record is copied forward rather than
derived again — one account per phase, which a history rebuilt from the journals could contradict. The journals stay,
for resuming and auditing, and go into the archival package. Vasile: *"agree"*.

## 2026-11-01 — the shared contract §13.0–§13.0a, the per-phase record: two points ruled

Proposed as intent §12, its rationale and build. Ownership stated by number band, the contract's per-phase file lists
being incomplete (prep's and merge's plans, merge's re-sealed manifest missing): *"ok"*. "Whole at the end of every
phase", tested only from geotag's side: *"please"* — a prep-only workspace's record now has a test of its own. On the
contract's finalize reading prep's journals as well as its log, which the code does not: *"only if there's a need - the
code seems to not need to read the journals, but I am not sure i can exclude them. Do we actually need to specify what
finalize uses? If yes, why?"*

## 2026-11-01 — the shared contract §12, authored decisions: ruled

Proposed as intent §11, its rationale and build; with the original-values ledger the code keeps the batch's last two
rules — a wrong decision fixed in the record, a withdrawn one undone. Vasile: *"all ruled"*.

## 2026-11-01 — every photo's own values kept, so a decision can always be revised

Converting the shared contract §12 found the marker rule had made a clock offset a one-way door: once executed, a
photo's time counted as correct and geotag never revisited it, so a corrected offset reached nothing, and a bucket of
corrected photos copied its old record forward, its effective offset left beside a decision that no longer said it.
Proposed: pin each photo's own camera time before geotag first writes it. Vasile: *"yes, but in the same vein, maybe
also store the pre-GPS and pre-GPSProcessingMethod so we have the complete original values just in case?"* — the
original-values ledger pins the capture time and its tag, the offset tag, the position and `GPSProcessingMethod`, once,
before the first write; later plans decide from them and write only what differs. Geotag's mark now governs only a
photo with nothing pinned. Asked whether geotag should refuse to plan while a record contradicts its decision: *"how do
you suggest this is solved? The solution should fix the root cause and, if not possible, at least fix it well, not just
refuse to run."* The root cause was a derived value copied forward; it is now derived from the decision on every run.
The two §12 rules with no test of their own — prep takes no decision, every change's cause can be found: *"yes, they
should if feasible"* — both have one.

## 2026-11-01 — decisions kept, and files changed only where they differ, in every phase

Shown the re-run rule of intent §9 whole, which the new §10 rules overlapped twice, Vasile: *"why not just mandate "A
decision the user made SHALL be kept while its target is unchanged" covering everything? and Written only where it
differs could also be made globally applicable?"* Both are §10 rules for every phase and run; the re-run rule keeps only
what is geotag's own — recognising what an earlier run wrote.

## 2026-11-01 — the shared contract §11, idempotency: three points ruled

Proposed as intent §10, its rationale and build. A no-op run giving "the same plan", where each new plan carries a fresh
id: written as the same operations, fingerprints and names — *"yes"*. Why settled work is not redone "to be safe":
*"can't remember where "to be safe" comes from but I agree with gains nothing and risks a failed write, and might cost
hours."* The invariant verified only through its four rules: *"ok"*. Whether the reuse rule should repeat that a
decision is kept while its target is unchanged, which the re-run rule of intent §9 also says, waits on reading that
rule whole.

## 2026-11-01 — geotag always writes the corrected time and name; the phone check to the backlog

Three switches in the default configuration — `write_corrected_metadata_times`, `write_corrected_offset_tags` and
`write_corrected_filename_times` — let geotag skip writing the corrected time, its offset tag, or the timestamp name. No
spec named them; they came with the repository's 2026-06-08 restructure. With the time switched off geotag still wrote
its position markers, so a re-run would have taken an uncorrected time for a corrected one. Vasile, recalling them: *"I
think I remember, it should be a per camera setting and I think that it should be set for real phones - they take their
time from the network and therefore the time is trustworthy."* That trust is the device classification: a phone's time
is resolved from its own offset tag, or the destination's timezone, with no offset and no question; the switches were
global and decided only what was written. On removing them: *"YES"*. Four phone settings nothing reads —
`phone_gpx_agreement_tolerance_seconds`, `phone_gpx_conflict_threshold_seconds`, `phone_gpx_max_distance_meters`,
`dst_conflict_tolerance_seconds` — suggest a check of a phone's time against the tracks: *"I want it, it needs to go to
backlog."* It is item 6; the settings stay for it. An existing workspace's configuration keeps the three switch keys,
now ignored.

## 2026-11-01 — a camera's offset for a day is kept for later photos

Once every photo of a camera on a day was corrected, its offset question went away, and photos of that camera and day
arriving later were asked it again. Vasile: *"earlier answer kept, because if the same camera same day then its offset
is obviously the same."* The bucket keeps its resolved decision and its drift confirmation through runs where it has
nothing to correct; an offset found from the camera's own GPS stays when later photos bring no anchor; a bucket's days
are counted over all the camera's photos there, so its key holds.

## 2026-11-01 — geotag's marker: a corrected time is never corrected twice

The contract said geotag recognises its own GPS "via the `GPSProcessingMethod` marker"; the code did not read the
marker at all. Once prep had read a file again, any position counted as the device's own, and the camera's offset was
applied to a time geotag had already corrected. An offset re-derived from the camera's own GPS came out the same, but
a manual or validated offset moved the photo a second time: a test now shows the old code renaming a photo from 14:30
to 14:40 on a re-run. Vasile: *"If a photo is reprocessed, its GPSProcessingMethod should be interpreted as "no GPS".
In other words, GPSProcessingMethod should cause the script to ignore its position until its position is (re)calculated,
at which time its position should be overwritten with the recalculated position. In addition, GPSProcessingMethod being
there should mean that the photo has the right datetime already (so (re)processing should not update it). And if it
does not have GPSProcessingMethod but has GPS, then it's datetime is anyway used as is AFAICR. This should also, I
think, cover new photos - if they have GPS and no GPSProcessingMethod, it's OK, if they don't have GPS then their
datetime must be fixed."* Phones write the field themselves; asked which values count: *"only geotag’s own values"*. A
camera with its own GPS has its time corrected from that GPS, which "used as is" did not cover; asked whether to keep
correcting it: *"yes"*. Such a photo, and one accepted as unlocated, had its time corrected with nothing written to say
so; offered a new marker value or a record kept in the workspace: *"New marker value please. And I think it can go in
GPSProcessingMethod, too"* — it is `time_only`. A photo geotag once placed and now places nowhere has geotag's old
position cleared, so it is never read back as its own. A write the file already holds is no longer planned, so a re-run
with nothing changed writes nothing.

The §10 items had all been marked ruled; only those ruled on keep it — the gates, development, the automatic re-prep
and the re-run recognition — as the earlier batches did.

## 2026-11-01 — the shared contract §10, the operator loop: five points ruled

Proposed as intent §9, its rationale and build. The empty inbox as a fifth gate on geotag, which the code applied and
the contract did not list: *"yes"*. Development barred from photos by destination at every point up to and including
merge, where the contract said only "before geotag is settled": *"Yes. The script does not admit someone processing
image files."* — his reason joins the rationale. Geotag's plan running prep itself when the only unrecorded change is a
sort: *"yes, the idea is that if plan knows that after it there should be a re-prep, then why bother the user."* The
four loop rules exercised only in passing — re-runnable until merge, a re-run does what changed, more dumps until
merge, merge ends the workspace: *"yes they should get 4 tests"*. The decision editor, which had no sealed check and
could still change a merged workspace's decisions: *"it should."* — it now refuses to open a sealed workspace, and a
save reaching it through the console writes nothing. How a re-run recognises what geotag already wrote stays open.

## 2026-11-01 — two more track formats

`.fit` is also the extension of FITS astronomy images, which would then block prep: *"I don't use FITS"*. Asked whether
zipped KML and IGC flight logs should block like the other track formats: *"add kmz and .igc"* — they do.

## 2026-11-01 — a prep plan goes stale when a file appears; every track format blocks

Before this, a file added between prep's plan and its execute went unnoticed: execute checked only the files the plan
had found, the newcomer stayed in the dump, and only geotag's plan and merge refused afterwards. Asked whether only the
dump should count or every place prep scans: *"every place prep scans"* — the plan now records everything its scan
found, and execute refuses a plan when a file has appeared since, or when the scan would now block. Asked whether
geotag's execute and finalize, which do not check the dump, should refuse too: *"leave them as they are"*. Asked whether
track formats other than GPX should block like it: *"forgot about these - yes, and add nmea, too."* — `.kml`, `.fit`,
`.tcx` and `.nmea` now block prep wherever it scans; geotag still reads only GPX. A new plan reuses the refused plan's
fingerprints; metadata is read a folder at a time, so a known file that shares a folder with a new one is read again.

## 2026-11-01 — the shared contract §8–§9, the tracks and the dependency cascade: four points ruled

Proposed as intent §7 and §8, their rationale and build. The tracks' fingerprint recorded as a dependency always and in
all four geotag records, where the contract said "when GPX is used" and named three: *"agree"*. "No record is used once
what it came from has changed" stated for every phase, where the contract said "both phases": *"agree"*. A `gpx_root`
configured inside the managed folders, which prep skipped and nothing refused: *"should refuse"* — configuration
validation now refuses it in every phase, and the skip is gone. A track file found in the dump, which prep moved to the
strays like any non-media file: *"tracks in the dump: this is a serious problem because it opens the possibility that
tracks are bulk deleted by the user. tracks in the dump should always cause the script to refuse to run."* — a track
file anywhere prep inventories now blocks the plan and is left where it is. With it, on new files in the dump: *"Also, I
don't remember if this is the case but new files in the dump showing up should stale it and they should be incorporated
by a new prep (avoiding metadata re-read for matching files)"*. On the stale comment in prep's skip, which gave the
default track location as `.photos-ingest/gpx/`: *"fix it"* — it went with the skip; the same claim in `AGENTS.md` is
corrected.

## 2026-11-01 — the shared contract §6–§7, camera groups and the filename format: three points ruled

Proposed as intent §5 and §6, their rationale and build. The old key name `geotag_filename_timestamp_format`, which no
code reads, sent to history rather than kept as an alias rule: *"yes"*. Which free name each phase takes — prep and
geotag the first free, merge the one above the highest used — tested for merge's half only: *"yes"*, prep's and
geotag's half get their own test — each now fills a gap below a higher suffix. The §1 two-phase passage, marked history
in the sample but never written here, now beside the old key name: *"ok"*.

## 2026-11-01 — what the shared contract recorded of its own past

Two passages of the shared contract are history, not specification, and leave it for here as they were written. From §1:
*"Most of this contract was written for the two-phase (prep + geotag) pipeline and continues to govern it; where a fact
applies only to merge, that is called out explicitly (e.g. Sections 5, 10, 13, the library facts in Section 15)."* From
§7.1: *"The geotag specification historically referred to this key as `geotag_filename_timestamp_format`. It is the
**same** key as `filename_timestamp_format` defined here; the phase-neutral name is authoritative because the key is
shared, and any remaining phase-specific name is an alias for it."* No code reads the old name.

## 2026-11-01 — the shared contract §5, the control directory: four points ruled

Proposed as intent §4, its rationale and build. The numbering block disagreed with the listing and the code (geotag
"21–25; 25 = complete log", where both say 26; merge's 30 missing; three files the code writes not listed): *"fix
numbering block to match code"* — both now match the code. The new invariant, a disturbed workspace never processed
silently: *"yes"*. The two rules with no clause of their own — prep alone builds the structure, once; prep checks the
whole tree for links, geotag and merge the top level — verified only in passing: *"they need their own tests"* — four
new tests, and the existing root-link tests of geotag and merge, now verify them. The printed plan path and the dry-run
summary's contents, output in a spec that carries none: *"move to design decisions"* — they are in
`docs/design/decisions.md`; the spec keeps the fixed place and that a dry run reports on the real plan.

## 2026-10-31 — the shared contract §4, the configuration: four points ruled

Proposed as intent §3, its rationale and build. Vasile, on whether any configuration edit should restale merge's plan
too, or only a change to the folder names or the extensions: *"any edit also restale merge’s plan"* — merge already
carried and checked the whole-file hash, untested; a test now asserts it. On the control directory, listed as a config
area though no key sets it: *"the location is fixed - make it explicitly fixed in the corpus."* On "no setting that
governs a run comes from outside the workspace", generalised from *"not an ambient in-code global"*: *"agree"*. On
linking the shared rationale into the philosophy batch by batch or at the end: *"done one pass at the end"*.

## 2026-10-31 — the method tag carries the traceability into the library

Asked whether the guide's *"via the traceability the multi-session reality forces"* should stay, the link to the
consolidated log having been dropped: *"By "traceability the multi-session reality forces" I meant that every decision
must be traced, and by incorporating the precision, I allow it even in the final library."* The tag follows from the
consolidated log again, beside the total-coverage cascade, and his meaning is in its text.

## 2026-10-31 — the per-coordinate method tag: kept for later refinement

Proposed: the tag lets a re-run with a newly found track replace a rough pin only by a more precise one, so it follows
from the recoverable core; and a rule for it, for the gap audit. Vasile: *"yes, you get it, but I think the stale gpx
point makes it not needed, at least not for that reason. However, I still want to be able to know, at a later date, how
that GPS position was assigned - maybe I want to refine it by image/place recognition for example."* On the rule:
*"I don't think that is a gap. The algorithm should do it by its own, and you are right that stale gpx will
regenerate positions"*. The tag now follows from the total-coverage cascade alone, the link to the consolidated log
dropped, and Vasile's reason is in its text; no rule, no audit item.

## 2026-10-31 — the philosophy's links: two ruled, one reopened

On the per-(camera group, destination, day) offset following from clock drift alone: *"1 ok"*. On the total-coverage
cascade, drawn from 100% placement alone though its text says it *"fights F3"* (the sentence is in the guide's first
upload, `23882e5`; no earlier draft survives): *"if GPS had full coverage, there would have been no need for cascade,
and if there was no need for 100% coverage, the incomplete GPS would be enough. So the cascade follows from *both*"* —
it now follows from 100% placement and from partial GPX coverage. On the per-coordinate method tag, linked to the
total-coverage cascade and the consolidated log: *"total coverage by itself does NOT justify adding the precision.
Imagine I find a new track that I misplaced. If I am to apply it, I will need the precision for each photo which will
allow me to know if I should replace or not."* Its links are open until Vasile confirms the reading.

## 2026-10-31 — the philosophy in the corpus; the remaining kinds and the gates ruled

Vasile, on the proposals (ASM, EXM, non-goals as anti rules, summaries in the ledger only, `choice_kind`, `forced`,
`follows_from`, the F/P numbers as aliases, the direction and root gates, `needflow`, the corpus owning the tables):
*"All yes"*. Built:
- **`rationale/philosophy.md`**: 3 `FCT`, 4 `CHC`, and 33 rationale items — each table row of the guide's entailment
  one item, under a node for each consequence the guide's diagram names (non-destructive core, recoverable core,
  format + editor split, minimal cascading asks, total-coverage cascade, multi-session job, durable record), whose
  text is that node's mechanism list or the section's own introduction. The links follow the diagram's edges. Three
  links are readings, for Vasile to confirm: the per-(camera group, destination, day) offset follows from F2 alone (the
  diagram routes no edge to it); the total-coverage cascade from P4 alone, as drawn, though its text says it *"fights
  F3"*; the per-coordinate method tag also from the consolidated log, which its text names. Linux and open-source are
  one item, as the guide's note is one.
- **The guide** keeps its framing, the test of fit and *"Using this document"*, names the roots by id, and points to
  the corpus for the rest; both diagrams are gone from it, the corpus's `needflow` drawing the graph from the links.
- **The ledger** reads a frozen copy of the guide (`spec/conversion/sources/`), not a commit: CI checks out shallow,
  and a squash merge would lose the commit. The same will serve each old spec once it is converted and removed.
- **The gates** were proved by breaking the corpus: an intent item naming a build item, a rule naming a rationale, a
  rule with `follows_from`, a fact nothing follows from, and a forced rationale whose chain loops without a root each
  failed the build.

## 2026-10-31 — the granularity ruled; the philosophy to enter the corpus as facts and choices

On the granularity — one item per obligation a test can pass or fail on its own, a refinement or an exception its
own item (`RUL-stale_lock_recovered` refined by `RUL-stale_takeover_conservative`): *"Also the granularity is ok"*.
On the philosophy's home — `docs/who-is-this-for.md`'s root layer as corpus items, its facts and choices as two new
kinds, `FCT` and `CHC`, each entailment a rationale that follows from them: *"FCT and CHC yes. Anything else?"* Proposed
in answer, not yet ruled: `ASM` (an assumption a user can break, geotag §7.0a) and `EXM` (a worked example, prep §21,
merge §13) as kinds; the non-goals as `anti` rules; the summaries mapped in the ledger to the items they restate;
`choice_kind` on `CHC`, `forced` on `RAT`, a `follows_from` link and the F/P numbers as aliases; gate checks on link
direction, on roots nothing follows from and on forced rationale tracing to no root; the philosophy graph generated
by `needflow`; and the corpus, not the user guide, owning the F/P tables.

## 2026-10-31 — the sample reviewed: the style ruled, the phases defined

Vasile, on the sample's five questions: the intent rewritten in SHALL form, naming no tool or file, the rationale kept
verbatim — *"yes"*; *only the snapshot depends on the filesystem*, made a rule from what the old spec gave as
reasoning — *"is a rule"* (`RUL-filesystem_agnostic`, the first item `ruled`); the build items carried over from the
old text and checked against the code by the gap audit — *"OK"*. On the old §1 being dropped as structure: *"the phases
and philosophy still need to exist somewhere IMO"* — so the phases, the workspace and the library are now definitions
(`DEF-prep`, `DEF-geotag`, `DEF-merge`, `DEF-workspace`, `DEF-library`), and the command names a build item; the
philosophy's home is open (`docs/who-is-this-for.md`'s root layer, proposed as rationale). On the granularity: *"where
should I look for a good example?"*

## 2026-10-31 — the corpus scaffold, and the shared contract §1–§3 as a sample

Vasile: *"please get started then"*. Built, item 1's first step:
- **Three levels, one Sphinx project**: `spec/intent/`, `spec/rationale/`, `spec/build/`, each to hold the four
  documents; sphinx-needs 9.1 (heating runs 8.5; 9.1 wants a `type` in every field schema). Kinds `DEF` `INV` `RUL`
  `RAT` `BLD` `TST`; links `uses` `refines` `excepts` `upholds` `realises` `justifies` `verifies`; fields `status`,
  `criticality`, `anti`, `verify` (`required` · `incidental` · `none` with `omit_reason`), `aliases`.
- **The tests as items, from pytest's own collection**, not from comment markers: `--spec-marks` in `conftest.py`
  dumps every mark; `spec/_ext/corpus.py` writes the `tst` items before the build reads. A parametrized test is one
  item. `add_need` was not used: it is deprecated in 9.1, and a deprecation warning would fail the gate.
- **Aliases for the move**: each item lists the clause ids it replaces, resolved when the tests page is written, so
  the suite's marks keep their clause ids and `tools/spec-coverage` keeps gating the clauses not yet converted. Only the
  marks of converted tests gain `test="TST-…"`.
- **The gate** is `tools/spec-build` (`spec/build/` being the build level): warnings fail it — proved by a must-verify
  item with no test and by a test naming a missing item, both exit 1 — and `spec/needs.json` comes out byte-identical
  build to build.
- **The ledger**: each converted sentence of an old spec, verbatim, with where it went (`tools/spec-ledger`); a
  missing sentence fails it. `defer:<part>` holds a sentence whose items belong to a part not yet converted.

The sample, every item `seed`: §2 (the lock) and §3 (the snapshots) as 16 intent items, 5 rationale, 5 build, 10
tests linked; §1 (purpose and status) is document structure and scope narration, dropped with reasons, but for one
line of history and the merge phase's definition, deferred to merge. Two items have no clause behind them: the rule
that only the snapshot may depend on a filesystem (from a sentence the old spec gave as reasoning) and that merge
snapshots the library.

## 2026-10-31 — BACKLOG and HISTORY; the spec to become a sphinx-needs corpus

Vasile: *"Move cartographer to sphinx-needs from the current manual requirements setup. And build the same
backlog/history (readme is there already I think)."* — the house's shape: `README.md` what it is, `BACKLOG.md` what is
open, `HISTORY.md` why. The release history moved here from `AGENTS.md` word for word, under each tag's date.

On the corpus, two placements were offered — the clauses beside the specs, or inline in them — and Vasile: *"We need to
discuss this, I'm not my happy with either"*, then:

> *"regarding my prose. I am not very happy with it because I think that in reality it combines narration with specs,
> and not only that but the specs are really two levels i think: generic and build. in addition, I am sure the build
> has some stuff not specced, and there may be stuff specced not built or incorrectly built. What i want is to have a
> real spec - I don't really care about keeping the specs as they are today if the result is a more disciplined spec
> like the heating one. the only thing I would want is to have the narrative (justifications for choices) parts in the
> current spec also captured and tagged, even if they are not strictly specs."*

So the target is the house heating corpus's shape (`~/projects/house/subsystems/heating/`, `spec/conf.py`): intent and
build apart, the justifications as tagged items, every item `seed` until ruled. On the points raised after it:
- the gate — *"I agree"*: warnings fail the build, in CI and pre-push; `needs.json` committed; published to GitHub
  Pages;
- the ids and kinds — *"only if it covers our needs completely, if not then extend. I don't really want to lose
  anything in the current specs, but I also want it as a maintainable, structured corpus."*;
- the documents — *"like today but ensure they are still making one corpus. What I mean is that links between them
  should still work and be tracked. I think this makes them easier to maintain, too."*;
- the disclosure — *"we can keep the specs as today, and describe the sphinx-needs adoption as ai-aided or something
  like that"*;
- the tests — *"isn't (b) more precise and less prone to drift?"* (heating's `# @test` comment markers, against
  keeping `@pytest.mark.spec`). Not more precise, and more prone to drift: a comment can be separated from its test by
  an edit and a stray comma drops it, while a mark is part of the function; but its explicit, stable id is an advantage
  the existing mark lacks. Vasile: *"updated (a) then."* — the existing mark, extended with an explicit test id.

## 2026-09-30 — v1.5.2

bug fix: **GPX track-point times with fractional seconds now parse** (#301). A `<time>`
is read as a full `xsd:dateTime` — fractional seconds optional, `Z` or a numeric offset — so Garmin's
`…:SS.000Z` loads alongside `…:SSZ`. Previously a `Z`-suffixed time went through a strict
whole-seconds format, every point of such a file was rejected, and the GPX set reported as `empty`.
`geotag plan` also prints the GPX load warnings now (at most 10, then a remainder count): the parser
recorded one per rejected point but nothing surfaced them, which is why a fully rejected file read as
silently empty (geotag §15). Patch only; no CLI or workspace break — a track that previously loaded
empty now yields points, so its GPX fingerprint changes and existing geotag plans restale; re-run
`geotag plan`.

## 2026-08-09 — v1.5.1

bug fix: **a planned GPS write now lands a readable fix.** EXIF stores latitude and
longitude as unsigned magnitudes with the hemisphere in the separate `GPSLatitudeRef`/`GPSLongitudeRef`
fields, but the plan's `metadata_gps_write` carried the coordinates alone — so every geotagged photo
read as having NO location to exiv2/digiKam, PIL, and Lightroom (exiftool's lenient composite still
showed a number, which masked it), and because `exiftool -n` stores a negative coordinate as its
magnitude, a southern or western position would have been written into the opposite hemisphere. GPS
writes now emit all four tags together, derived from the coordinate's sign, and a manual-override
revert restores or clears the refs alongside the coordinates (geotag §28.1 — new). Note for an
affected workspace: a re-plan alone does not repair it — the coordinate-only files now read as native
GPS (`has_native_gps` keys on coordinate presence), so `classify_gps` returns `preserve_native` and
plans no write; recover from the pre-execute snapshot, then re-plan and re-execute. Patch only; no CLI
or workspace break, and plans restale normally on the changed operation fingerprint.

## 2026-08-08 — v1.5.0

**a plan no longer throws its decode work away.** Cache rows are written by `execute`
only (planning never mutates the cache — `plan` opens it read-only), so a plan that was never executed
discarded every fingerprint it computed and the next plan re-decoded the whole workspace: hours on a
real library whenever the operator re-plans first (a config edit, a corrected folder, an interrupted
run). Planning now keeps those observations in a **decode memo** in its own database
(`.photos-ingest/photos-00-plan-memo.db`, prep §10.3 — new), consulted only where the cache misses and
always outranked by it. Entries are laid *under* the cache and split back into their file and metadata
parts, so both freshness gates apply the same size/mtime/engine/field-set tests they apply to a cache
row — there is no memo-specific reuse path; move recognition still runs against executed state alone;
and a missing or corrupt memo degrades to re-decoding rather than failing a plan. A 39-file re-plan
drops from 4.5s to 0.2s with an identical plan. Alongside it, the §17.4 re-hash report accounts for
memo reuse and names the cause when a re-plan re-hashes with nothing carried over, and the dead
`camera_time_and_timezone_policy.enabled` config flag (seeded and validated, never read) is gone from
the seed template. Additive; no CLI or workspace break — existing workspaces gain a memo on their next
plan, and configs carrying the removed flag are unaffected.

## 2026-06-24 — v1.4.0

every phase command closes its output with a single `Next: …` line stating the operator's
next action for the state it produced: the next command on success (prep `plan` → `dry-run`/`execute`;
a complete geotag plan → `geotag execute`; geotag `finalize` → `merge init-library`/`plan`; merge
`execute` → a sealed workspace), or the corrective action when it stops on a blocker, a stale plan,
decisions still needing the editor, or an unmet precondition. Emitted from the shared phase `run()`, so
the CLI and the console show identical guidance (`reporting.emit_next_step`). The hints are an
affordance, not part of the behavioural contract — the specs stay silent on output wording (see
`docs/design/decisions.md`). Additive; no CLI or workspace break.

## 2026-06-24 — v1.3.1

bug fix: the unknown-camera-group config snippet emitted its `device_groups` arrays in
the wrong order (`phones` before `fixed_clock_cameras`), but the seeded config stores them sorted
(`fixed_clock_cameras` first), so a first-run whole-block paste-over dropped the comma between the two
arrays and produced invalid config. The snippet now follows the config file's own `device_groups` key
order (geotag §16). Patch only.

## 2026-06-23 — v1.3.0

**geotag auto-re-preps a clean by-dest move** (§13.1.1: after sorting into
`6-photos-by-dest`, go straight to geotag — when `0-sources` is empty it runs the real `prep plan` +
`execute` for you before locking; a non-empty `0-sources` is still the hard gate) and **always-on
re-hash diagnostics** (prep §17.4: when any media is re-fingerprinted, a per-reason summary —
`moved-unmatched`/`mtime-changed`/`engine-changed`/… — splits expected new hashes from unexpected
previously-cached ones, with a first-N sample + `performance_and_cache.rehash_summary` in the run
report). Plus a screenshot-driven docs overhaul (`docs/walkthrough.md` + the hero GIF + a USP reframe)
and a large **internal maintainability refactor** — the geotag pure-calc layer extracted to
`_geotag_calc.py`, prep models to `_prep_models.py` (façade re-exports keep the import/patch surface),
and `WorkspacePrepWorkflow.plan()` decomposed into ordered `_plan_*` steps over a `_PlanState` carrier
— all behaviour-unchanged, gated by the new `tools/plan-differential` harness. Additive/internal; no
CLI or workspace break.

## 2026-06-22 — v1.2.0

the **operational web console** (`photos-cartographer console`): run *and monitor* every
one of the eleven phase commands from a browser over the cwd workspace, with the decision editor folded
in as the 4th tab — built on the shared **reporting event/sink seam** (`cartographer/reporting.py`),
with execute behind a per-phase confirm gate and precondition/staleness-aware action enablement. Plus
the **`-j`/jobs** control, **spec-clause coverage tooling** (`tools/spec-coverage` + the clause index),
and assorted prep/console robustness fixes (Stop/interrupt, stale-lock probe, nothing-to-do fast-stop,
first-run config notice). Additive; the CLI and existing workspaces are unchanged.

## 2026-06-20 — v1.1.1

docs fix: correct the destination model in `docs/concepts.md` (an intermediate folder
may hold photos *and* sub-destinations; only folders with no direct media are `container` nodes).
Docs-only; the binary is unchanged from v1.1.0 (docs are not bundled).

## 2026-06-19 — v1.1.0

**media extensions are now workspace config** (`media_extensions`, seeded then
authoritative); folder-set and media-extension changes get field-scoped config fingerprints so they
surgically restale the geotag/merge plans. Prep `plan` now **warns on dump files exiftool sees as
media** (`image/*`/`video/*`) that aren't listed, suggesting a config add. Added user guides under
`docs/`. Renames: package `photos_pipeline` → `cartographer`, `workflows/` → `spec/`, and the
config-override env var `PHOTOS_PIPELINE_CONFIG` → `PHOTOS_CARTOGRAPHER_CONFIG` (the only
deploy-facing break; the CLI is unchanged and existing workspaces keep working).

## 2026-06-19 — v1.0.1

flatten `ingest/` into the repo root (`photos_pipeline/`, `tests/`, `workflows/`);
README destination-folder-format update. No behavioral change.

## 2026-06-19 — v1.0.0

first release: the unified `photos-cartographer` executable (renamed from `photos-ingest`).
