# photos-cartographer — what is open

*Every entry stands alone: what it is, why it matters, what blocks it.*

- **What this is:** [`README.md`](README.md). **The record:** [`HISTORY.md`](HISTORY.md).

*Open items: **5** — 1, 2, 3, 4 and 5.* 🛑 Numbers are never reused; the next is **6**.

---

## Open

### 1. The spec as one sphinx-needs corpus — intent, build and rationale apart

**Why:** the four specs in `spec/` mix four things — behaviour the tool guarantees, how this build delivers it
(exiftool, ImageMagick `identify`, SQLite, the `photos-NN` artifact names), the justification for a choice, and
operator guidance and history. The clause index over them, `spec/spec-clauses.json` (623 clauses, 529 CI-gated), is a
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

### 3. The 39 clauses no test asserts

**Why:** the clause index marks 39 clauses `coverage: none` — specified, and nothing checks them. Four are **high**:
- `geotag-bydest-no-symlink-1` — symlinks under by-dest are barred, never followed;
- `atomic-inplace-metadata-1` — an in-place metadata write is atomic, so a crash leaves the intact original;
- `authored-no-autonomous-mutation-1` — every mutation traces to a recorded human decision or a deterministic rule;
- `lock-stale-takeover-conservative-1` — only a lock whose owner is provably gone may be reclaimed.

The rest: merge 12, prep 11, shared 7, geotag 5 (22 med, 13 low) — `tools/spec-coverage --verbose` lists them.

**Do:** a dedicated test for each, or a ruled reason it needs none. With item 1 they carry over as the must-verify
items still missing a test, which the gate then names.

---

### 4. The 55 clauses only incidentally tested

**Why:** 55 clauses (prep 20, geotag 16, shared 12, merge 7; 4 high) are exercised by tests written for something
else — a happy path passes through them, nothing asserts them, so a regression there passes CI.

**Do:** as item 3 — a test that asserts each, or a ruled reason.

---

### 5. The commit-msg hook — publish it, or keep it local

**What:** `.githooks/commit-msg` rejects a commit whose message credits Claude/Anthropic. It is active in this clone,
kept out of the repo by `.git/info/exclude`; the branch `origin/chore/commit-msg-no-ai-attribution` (2026-06-27, one
commit) would add it to `main`.

**Question for Vasile:** merge the branch (the hook then guards every clone), or keep it local and delete the branch?
