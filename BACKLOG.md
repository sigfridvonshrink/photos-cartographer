# photos-cartographer — what is open

*Every entry stands alone: what it is, why it matters, what blocks it.*

- **What this is:** [`README.md`](README.md). **The record:** [`HISTORY.md`](HISTORY.md).

*Open items: **10** — 1, 2, 3, 4, 5, 6, 7, 10, 11 and 12.* 🛑 Numbers are never reused; the next is **13**.

---

## Open

### 1. The spec as one sphinx-needs corpus — intent, build and rationale apart

**Why:** the four specs in `spec/` mix four things — behaviour the tool guarantees, how this build delivers it
(exiftool, ImageMagick `identify`, SQLite, the `photos-NN` artifact names), the justification for a choice, and
operator guidance and history. The clause index over them, `spec/spec-clauses.json` (633 clauses, 542 CI-gated), is a
hand-kept list of paraphrases pointing at whole sections. Vasile wants *"a real spec"*, *"a more disciplined spec like
the heating one"*, with the justifications *"captured and tagged, even if they are not strictly specs."*

**The shape agreed** (the house heating corpus, `~/projects/house/subsystems/heating/spec/conf.py`, as the model):
- **One Sphinx project**, MyST Markdown with sphinx-needs items, **in four documents per level as today** — shared,
  prep, geotag, merge — linked across documents by typed links that the build checks.
- **Two levels:** `intent/` — what cartographer guarantees, naming no tool, file or database (definitions, invariants,
  rules); `build/` — how this build meets each of them (construction requirements, each `realises` what it implements).
- **The justifications as items** (a rationale kind that `justifies` the items it argues for), so nothing narrative
  is lost and every piece is findable. Operator guidance goes to `docs/`, history to `HISTORY.md`.
- **The roots of the rationale:** the user guide's three facts and four choices are items, `FCT` and `CHC`, in
  `rationale/philosophy.md`; nothing follows from them. Every other rationale `follows_from` a root or another
  rationale, and says whether it is `forced` or a judgement; the build fails on a root nothing follows from and on a
  forced rationale whose chain reaches no root. The guide keeps the test of fit and names the roots by id.
- **The other kinds and the levels' direction:** an assumption a user can break is an `ASM`, which rules `assumes`; a
  worked example is an `EXM`, which `illustrates`; a non-goal is an `anti` rule; a summary gets no items, its ledger
  rows naming the items it restates. Intent never links to the build, and no link but `follows_from` names a
  rationale — the build fails on either.
- **Kinds and ids** as heating's (`KIND-name`), extended wherever cartographer needs more; every item `seed` until
  Vasile rules it.
- **Nothing lost:** every sentence of today's specs lands in exactly one place — an item, the rationale, `docs/`,
  `HISTORY.md` — or is dropped with a recorded reason; a word-for-word ledger proves it (`tools/spec-ledger`). The
  old clause ids map onto the new items, so no test breaks mid-move, and the clause index retires when the last
  document is converted.
- **The gate:** the build fails on any warning — a dangling link, an item citing another without a link field, a must-
  verify item with no test — in CI and the pre-push hook. `needs.json` is committed, so a diff shows exactly which items
  changed. The corpus is published to GitHub Pages.
- **AI-DISCLOSURE.md** keeps *the specs are mine* and says the sphinx-needs restructuring is AI-aided, `ruled`
  recording Vasile's approval item by item.

- **The tests as items:** each test declares what it verifies in its existing `@pytest.mark.spec(…)`, extended with an
  explicit, stable test id — `@pytest.mark.spec("INV-no_clobber", test="TST-…")` — and the build makes `TST` items of
  them from pytest's own collection. A mark is part of the function, so it cannot be left behind by an edit, and Python
  parses it.

**Order:** the corpus scaffold and its gate; then one document at a time — the shared contract first (the others lean
on it), then prep, merge, geotag — each proposed section by section and ruled by Vasile; and last, one pass that gives every
converted document's rationale its `follows_from` links into the philosophy.

**Done looks like:** the four specs converted and ruled; `spec/spec-clauses.json` and its registry test retired; the
gate green in CI; the corpus on Pages; `AGENTS.md`, `spec/README.md` and `COVERAGE.md` describing the corpus.

---

### 2. The gap audit — the build against its spec

**Why:** Vasile: *"I am sure the build has some stuff not specced, and there may be stuff specced not built or
incorrectly built."*

**What:** once item 1's build items exist, walk the code and the corpus against each other: code behaviour with no
build item (**unspecified**), an intent or build item with no code or no test (**specified, not built**), code that
contradicts its item (**built wrong**). Each finding becomes its own backlog item. 🛑 **A gap is raised, ruled and
written into the spec first, then coded** — the code is never taken as the answer.

**Blocks it:** item 1, document by document — the audit of a document can start once it is converted.

---

### 3. The 37 clauses no test asserts

**Why:** the clause index marks 37 clauses `coverage: none` — specified, and nothing checks them. Four are **high**:
- `geotag-bydest-no-symlink-1` — symlinks under by-dest are barred, never followed;
- `atomic-inplace-metadata-1` — an in-place metadata write is atomic, so a crash leaves the intact original;
- `authored-no-autonomous-mutation-1` — every mutation traces to a recorded human decision or a deterministic rule;
- `lock-stale-takeover-conservative-1` — only a lock whose owner is provably gone may be reclaimed.

The rest: merge 11, prep 11, shared 9, geotag 6 (21 med, 12 low) — `tools/spec-coverage --verbose` lists them.

**Do:** a dedicated test for each, or a ruled reason it needs none. With item 1 they carry over as the must-verify
items still missing a test, which the gate then names.

---

### 4. The 53 clauses only incidentally tested

**Why:** 53 clauses (prep 19, geotag 16, shared 11, merge 7; 4 high) are exercised by tests written for something
else — a happy path passes through them, nothing asserts them, so a regression there passes CI.

**Do:** as item 3 — a test that asserts each, or a ruled reason.

---

### 5. The commit-msg hook — publish it, or keep it local

**What:** `.githooks/commit-msg` rejects a commit whose message credits Claude/Anthropic. It is active in this clone,
kept out of the repo by `.git/info/exclude`; the branch `origin/chore/commit-msg-no-ai-attribution` (2026-06-27, one
commit) would add it to `main`.

**Question for Vasile:** merge the branch (the hook then guards every clone), or keep it local and delete the branch?

---

### 6. Check a phone's time against the tracks

**Why:** geotag trusts a phone's clock — a phone takes its time from the network — and resolves each phone photo from
its own offset tag, or failing that from the destination's timezone, with nothing checking it. A phone set to the wrong
zone, a photo whose offset tag is missing while the phone sat in another zone, or a phone's clock that did drift, would
pass unseen and misplace every such photo on the track. Vasile wants the check built.

**What exists:** four settings in the default configuration that nothing reads: `phone_gpx_agreement_tolerance_seconds`
(60), `phone_gpx_conflict_threshold_seconds` (300), `phone_gpx_max_distance_meters` (250) and
`dst_conflict_tolerance_seconds` (120). Configuration loading checks they are numbers; no spec names them. Their names
suggest the shape: where a phone photo carries its own position and a track covers it, compare the photo's time with
the track's time at that position.

**Open:** what the check does on disagreement — inside the agreement tolerance pass silently, beyond the conflict
threshold block or ask, between them warn? — and what the daylight-saving setting guards. To be settled with Vasile
before it is specified.

### 7. One obligation per item, checked by reading — after the conversion

**Why:** every corpus item states one obligation, and `tools/spec-build` refuses an item with more than one SHALL. But
the count cannot see a second obligation folded into one sentence: in the pass that made every item one SHALL, about 90
items had a restating second SHALL reworded into the first, and some of them still carry two obligations under one
SHALL — `RUL-lock_fail_fast`, for one, stops at once, says the workspace is locked and produces nothing;
`RUL-replanning_keeps_the_prior` sets the saved plan aside and tells the user where; `RUL-no_plan_no_run` stops and
tells the user to plan first. From §4's structure: `RUL-structure_built_once`, `RUL-top_level_only_managed`,
`RUL-first_dump_at_top_level`, `RUL-link_named`, `RUL-geotag_merge_check_top_level_links`, `RUL-missing_folder_blocks`,
`RUL-missing_folder_named`, and `RUL-no_links` with its four cases. From §5's camera groups:
`RUL-prep_derives_camera_group` (derive the group, record it in two places) and `RUL-camera_group_derivation_versioned`
(carry a version, have it checked). From §6's filename format: `RUL-one_filename_format` (one format, set by the
configuration, hard-coded by neither phase), `RUL-suffix_no_clobber` (zero-padded, deterministic, compared without
regard to case, checked against the names on disk and those planned), `RUL-prep_name_provisional` (the raw timestamp,
for ordering only, never corrected) and `RUL-geotag_name_final` (work out the final name, rename to it). From §7's tracks: `RUL-tracks_geotag_only` (what
geotag alone does with the tracks, and what prep never does). From §9's loop: `RUL-sort_photos_only` (only photos, and
geotag refuses otherwise), `RUL-rerun_does_what_changed` (exactly what changed requires, and asks only about what is
affected), `RUL-merge_is_terminal` (merge comes last, new media goes to a fresh workspace) and
`RUL-more_dumps_until_merge` (a dump is accepted, the loop resumes from prep). Vasile caught
the pattern in a proposed `RUL-failed_operation_clean` and wants the rest found.

**What to do:** read every item against a stricter test — one property per item, which a single test could find broken
in only one way — and split each real second obligation into an item refining the first, the ledger and the tests' marks
following, as `RUL-failed_operation_clean` was split into it, `RUL-failure_recorded` and `RUL-failure_never_done`.

**Blocked by:** item 1. Vasile: *"maybe we can do this at the very end after the full conversion to sphinx-needs? I am
worried that we are piling too much work in one strand and doing it now might break other links, too."* So it waits
until every spec is converted, and is done once, over the whole corpus.

### 10. Files without a camera identity share one camera group

**Why:** a file whose metadata names no serial number, make, model or owner gets the camera-group key `unknown`, and
every such file shares it: screenshots, scans, photos a messaging app stripped. They are not one camera, as a camera
group is defined to be. Classed under `fixed_clock_cameras`, they would all get one clock offset per destination.
Found while ruling §5 of the shared contract.

**What to do:** decide how geotag treats files with no identity — a group of their own that can never be classed, each
file on its own, or as now — state it in the geotag spec, and make the code and a test follow.

**When:** with the conversion of the geotag spec (item 1), where camera groups are classified.

### 11. Records keyed by a fingerprint that changed with ImageMagick

**Why:** a new ImageMagick may decode a photo to a new fingerprint value (`RUL-engine_change_is_checked`). Prep
follows the value in its own records — the database and prep's log move to it, across a user's move too. Geotag's
records keyed by the old value do not: its complete log, `original_values`, the finalized-media record. So merge, finding
a photo whose fingerprint changed, can only leave it unmerged (`RUL-merge_rechecks_under_new_engine`), and the only
remedy today is the ImageMagick version that prepped the workspace. Found while converting merge §2.

**What to do:** list every record keyed by a fingerprint's value, and decide how it follows a value that changed — a step
that re-keys them, planned and journaled like any change, its records rewritten whole and what depends on them restaled
— or leave the block as the answer. Stop where the old-to-new mapping is not one to one, which would change prep's
duplicate decisions.

**When:** with the conversion of the geotag spec (item 1), where those records are converted.

---

### 12. Number the phase documents' sections 1…n

**Why:** the phase documents of the corpus (`spec/intent|rationale|build/{prep,geotag,merge}.md`) number their headings
as in the phase's original spec, so a section with no items of its own has no heading and the numbers skip — `intent/
geotag.md` holds §2 and §5 only. While the original documents are being converted the numbers are the way back to them:
the ledger maps each sentence by section and build items cite "geotag §13.3". Once every document is converted and
retired, they only puzzle a reader. Vasile: *"1 now, and add a step (or backlog) after the conversion to renumber."*

**What to do:** renumber each phase document's sections 1…n, the same number for the same section across intent,
rationale and build; rewrite the section citations in the build items to links or the new numbers; drop the
explanatory sentence from each document's introduction. The ledgers keep the old numbers — they record the old specs.

**When:** after the conversion (item 1) is complete.

