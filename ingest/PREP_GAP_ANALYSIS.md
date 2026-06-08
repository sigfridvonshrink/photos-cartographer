# `photos-1-prep` — Compliance Gap Analysis

Comparison of the current `ingest/photos-1-prep` (+ `ingest/photos_utils.py`) implementation
against the authoritative workflow specs:

- `ingest/workflows/10_photos-1-prep-workflow.md` (prep spec, §1–22)
- `ingest/workflows/10_photos-shared-contract.md` (shared contract, §1–13)

Severity: **High** = blocks correct/real-world operation or breaks the calibration contract ·
**Med** = real deviation, non-blocking · **Low** = polish/cleanup.

All line references are to the state of `main` at the time of analysis.

> **Direction of every finding:** the code is *behind* the spec. There is **no case where the code does
> something better that warrants changing the spec.** The metadata extraction is richer than the spec's
> minimum (a superset, not a conflict) and the non-goals are cleanly enforced — neither is a reason to
> amend the spec. So this is a one-way "bring code up to spec" exercise.

---

## 0. Headline: prep is currently non-functional on real photos, and the tests hide it

Two High bugs compound so that **a workspace containing any real image cannot produce an executable plan**,
and the test suite is green only because it mocks around both:

1. **`ContentHasher.hash_image` is a permanent stub** (`photos-1-prep:491-493`) — it always returns
   `status: "failed", error: "ImageMagick disabled"`. Dedup prefers `content_hash` over the valid file
   sha256 (`:1666`), so every mutable-side image/raw becomes a §6.2(3)/§11.3 hash-failure **blocker** →
   no plan. Only `video`/`other` dedup works in production.
2. **The filename timestamp format is hardcoded and the wrong shape** (`:1759`): `%Y%m%d_%H%M%S`
   (e.g. `20230101_120000-001.jpg`) instead of the spec's `%Y-%m-%d--%H-%M-%S`, and it is **not** read
   from the shared `filename_timestamp_format` config key (shared §7).
3. **The tests encode the divergence.** `test_workspace_prep.py` / `test_idempotency_cache.py` monkeypatch
   `hash_image` to a real sha256, and assert the wrong `YYYYMMDD_HHMMSS` name shape. So **green CI does
   not mean spec-compliant** — the tests must be fixed alongside the code, and at least one un-mocked
   end-to-end test added.

---

## 1. Blocking correctness bugs (Phase 0 — unblock real use)

| # | Requirement (spec §) | Status | Evidence | Action (code + tests) | Sev |
|---|---|---|---|---|---|
| 1 | Content hashing backs dedup; hash failure ≠ equality (§9, §7.5, §11) | Divergent (stub) | `photos-1-prep:491-493`; dedup `:1666` | Implement a real image content hash, or fall back to file sha256; stop treating every image as a hash failure | High |
| 2 | Filename timestamp shape `YYYY-MM-DD--HH-MM-SS`, read from config `filename_timestamp_format` (§8; shared §7) | Divergent + Missing key | `photos-1-prep:1759`; key absent from `photos_utils.CONFIG:5-39` | Add `filename_timestamp_format` (default `%Y-%m-%d--%H-%M-%S`) to config; read it in Stage 5; fold into config fingerprint | High |
| 3 | Tests must assert spec behavior, not the divergence | — | `test_workspace_prep.py:35,57-58,76,124`; `test_idempotency_cache.py:66-72` | Fix name-shape assertions; add ≥1 un-mocked smoke test that hashes a real image end-to-end | High |

---

## 2. Missing capabilities (whole features absent)

| # | Requirement (spec §) | Status | Evidence | Action (code + tests) | Sev |
|---|---|---|---|---|---|
| 4 | **Config file lifecycle**: seed `photos-00-config.json` on first run from `photos_utils.CONFIG`, then read as authoritative; field-scoped fingerprints + whole-file SHA derived from the file, before other fingerprints (prep §3; shared §4) | Missing | no `photos-00-config` token anywhere; runs off in-code `CONFIG` (`photos-1-prep:23,560,1880`) | Seed-on-first-run into `.photos-ingest/`; load as authoritative; derive field-scoped + whole-file fingerprints from the file; archive whole-file SHA | High |
| 5 | **Move-aware identity** §10.1 (by-date→by-dest) and §10.2 (re-sort within by-dest): stat-only match (size+mtime_ns+basename), unique-match carry hash+metadata forward, drop old row, **no** fs op; ambiguous→rescan. Also = §13 item 7. | Missing | unconditional ghost-prune `:1496-1505`; new by-dest files fully re-hashed via `process_file`; confirmed by `test_idempotency_cache.py:337-385` | Implement the stat-only matcher before ghost-pruning; carry forward; update handoff destination (so calibration re-evaluates re-sorts); tests for move (no rehash), ambiguity (rescan), content-change override | High |
| 6 | **`prune-quarantine` command** (select by plan_id/age, default dry-run, `--yes`, quarantine-only, under lock) (§15.3) | Missing | subparsers only `plan`/`dry-run`/`execute` (`:1937-1947`) | Add the subcommand; tests for dry-run default, `--yes` deletes only selected, refuses paths outside quarantine, takes the lock | High |
| 7 | **Band-misplacement guard** §6.2(4): video under `4`/`5`, or image/raw under `3`, is a hard block | Missing | no such check; only the folder list `:1230` | Stage-0 guard comparing media_class vs top-level folder; append blocker; tests | High |
| 8 | **Nested-dump flattening** §7.1/§7.2: dumped folder *trees* at the workspace root must be walked and flattened into `0-source` | Divergent | Stage-0 inventory is `os.listdir`+managed folders only (`:1256-1274`); only root-level loose files consolidated (`:1518-1546`) | Walk all non-managed/non-control root subtrees; flatten into `0-source` no-clobber; nested-dump test | High |
| 9 | **Quarantine footprint reporting every run** (total files, size, #distinct plan_id dirs, oldest/newest) (§15.3, §19.12) | Missing | no footprint computation anywhere | Walk `.photos-ingest-quarantine/`; compute + surface in summary/handoff each run; test | Med |

---

## 3. Naming & control-directory divergence (Phase 1 — foundational; calibration-contract-breaking)

The spec puts **everything** under `.photos-ingest/` with fixed names; the code scatters control files at the
workspace root with non-spec names and relies on a per-filename allow-list instead of skipping the control
dir wholesale. The handoff name is **contract-breaking**: calibration consumes `photos-11-handoff.json` by exact path.

| # | Spec name / rule | Current | Evidence | Sev |
|---|---|---|---|---|
| 10 | `.photos-ingest/photos-11-handoff.json` | `.photos-ingest/photos-1-prep-handoff.json` | `:1156` | High |
| 11 | `.photos-ingest/photos-00-ingest.db` | `.photos_ingest.db` at workspace root | `:153,156`; skip `photos_utils.py:409` | High |
| 12 | `.photos-ingest/photos-00-workspace-guard` | `.photos-ingest-root` / `.photos-1-prep-root` at root | `:377-379` | Med |
| 13 | `.photos-ingest/journal-<run>.json`, per-run retained (shared §13.3a) | `.photos-ingest-journal.json` at root, single overwritten file | `:1995`, `JournalWriter.save:1220-1223` | Med |
| 14 | lock file under `.photos-ingest/` | `.photos-ingest.lock` at workspace root | (WorkspaceLock `:350`) | Low |
| 15 | Skip `.photos-ingest/` **wholesale** as a subtree (shared §5) | per-filename allow-list; `.photos-ingest/` not pruned (only `-quarantine`, `-backups`, `.git`) | `:428-438`; `photos_utils.py:394-411` | Med |

> Note (#13): per-run journal retention is also required by shared §13.3a so the finalize step can build the
> transformation log across many runs. The current single overwritten journal keeps only the last run.

---

## 4. Safety & lifecycle partials (Phase 4 — hardening)

| # | Requirement (spec §) | Status | Evidence | Action | Sev |
|---|---|---|---|---|---|
| 16 | Lock is **whole-run**: acquired at startup before any scan/plan/dry-run (shared §2.1) | Divergent | `WorkspaceLock` (fcntl, fail-fast) is acquired only inside `PlanExecutor.execute:728-731`; `main()` runs `plan`/`dry-run` unlocked (`:1957-1987`) | Acquire in `main()` after sentinel check; hold for all three commands; release in `finally`; tests for concurrent plan blocked | High |
| 17 | Stale-lock detection/conservative takeover (shared §2.4) | Partial | relies on `flock` kernel auto-release; no recorded pid/start-time | Record owner identity + liveness for takeover, or document flock-auto-release explicitly; stale-lock test | Med |
| 18 | Config edit rejects a previously-generated plan at execute (§5, §21) | Missing | `config_fingerprint` recorded (`:1880`) but never recompared in `validate_plan_preflight` | Recompute current config fingerprint in preflight; reject on mismatch; test per §21 | High |
| 19 | Reject foreign/wrong-version/schema plan (§14.3.2) | Partial | only `command=='prep'` checked (`:576-577`); `plan_version`/schema/tool not checked | Add plan_version + tool/schema-id checks; test | Med |
| 20 | §5 required fingerprints in depends_on across plan/journal/cache/handoff | Partial | handoff depends_on `:1130-1151`; **journal** has none (`:130-139`); **SQLite** stores no schema/cache version; handoff missing SQLite schema version + CLI-options fingerprint | Add SQLite schema/cache-version + hash-algo-version to handoff; version-stamp journal + a DB meta row; tests | Med |
| 21 | Cache update as a single post-verification transaction (§14.3.7) | Partial | per-op writes interleaved with fs mutation (`:860-875`, `upsert_file:271`) | Optional: wrap cache effects in one transaction committed after fs verified (tolerated today by FS-as-truth) | Low |
| 22 | Phase log lines incl. lock/release (§17) | Partial | scan/hash/extract/dedup/apply/handoff phases emitted; lock acquire/release silent | Add lock/release phase lines | Low |

---

## 5. Metadata, handoff & output partials (Phase 5 — the substance is strong)

Passive metadata extraction is **fully compliant** — §12(1)–(5), §12.1 freshness, and shared §6
`camera_group_key` (versioned, emitted in handoff + SQLite) are all correctly implemented, including the
QuickTime/Track/Media family, sub-second/offset/TZ fields, the full native-GPS set, and the raw payload.
The gaps are in grouping facts and how things are surfaced.

| # | Requirement (spec §) | Status | Evidence | Action | Sev |
|---|---|---|---|---|---|
| 23 | §12.2 per-camera-group facts incl. "contributing identity fields" + config-derived phone/camera class; per-by-dest conflicts/duplicates field | Partial | groups `:1033-1088`; dest `:990-1097` | Add identity-field breakdown + class (when known from `device_groups`); add per-dest conflicts/duplicates | Med |
| 24 | §16 handoff: all 9 items, real duplicate/conflict evidence, execution id | Partial | `duplicates_or_conflicts` is just `plan.blockers` placeholder (`:1126-1129`); no execution id | Populate real dup/conflict evidence; add execution id | Med |
| 25 | §19 user-visible summary — all 12 categories | Partial | `print_summary` is a flat perf list (`photos_utils.py:524-542`) | Add: no-op/already-correct, moves recognized, dup split (mutable vs by-dest), group/GPS/timestamp counts, quarantine footprint | Med |
| 26 | Media-class table defined once | Cleanup | triplicated `:465-469`, `:1362-1367` | Extract one shared table in `photos_utils.py` | Low |

---

## Suggested sequencing

The order is chosen so foundational changes land before the work that depends on them, and so the suite
becomes genuinely meaningful early.

- **Phase 0 — Unblock & de-greenwash:** #1 real image hash, #2 config-driven correct filename format,
  #3 fix tests + add an un-mocked smoke test. After this, "green" means something.
- **Phase 1 — Control-dir & config foundation:** #10–#15 (names/locations, wholesale subtree skip) and
  #4 (config seeding + file-rooted fingerprints). Everything downstream fingerprints/handoffs depends on these.
- **Phase 2 — Core idempotency capability:** #5 move-aware identity (with #13 per-run journals).
- **Phase 3 — Missing guards/commands:** #6 prune-quarantine, #7 band guard, #8 nested dumps, #9 footprint.
- **Phase 4 — Lifecycle hardening:** #16 whole-run lock, #18 config revalidation, #19 plan-version checks,
  #17 stale-lock, #20 fingerprint coverage, #21/#22 polish.
- **Phase 5 — Reporting:** #23 grouping facts, #24 handoff evidence, #25 summary categories, #26 cleanup.

Each phase should land its own tests and keep the combined `pytest` green (and spec-accurate) before the next.
