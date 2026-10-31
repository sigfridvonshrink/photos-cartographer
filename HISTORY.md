# photos-cartographer — why

*What was decided and why, newest first. A record: never corrected forward. Per-commit detail is `git log`.*

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
  keeping `@pytest.mark.spec`): open, item 1.

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
