# Test coverage

This pipeline mutates irreplaceable originals, so coverage is tracked on **two axes**:

1. **Line / branch** coverage of the production code (`coverage.py`).
2. **Spec-clause** coverage — which behavioral clauses in `spec/*.md` have a dedicated test
   (`tools/spec-coverage` over `spec/spec-clauses.json`). Line/branch can't tell you whether a
   *must-refuse / no-clobber / leaves-untouched* obligation is actually asserted; this can.

Figures below are a snapshot; regenerate with the commands shown. The suite has **1132 tests**.

## Line / branch coverage

The geotag phase — the one that writes time and GPS into the originals — is the most heavily tested.
The lighter areas are the two local web servers (console, editor): thin affordance layers over the
same plan/validate/execute core the phases provide, neither of which writes metadata into photos.

| Component | Line | Branch |
|---|---:|---:|
| prep (`photos_1_prep`) | 92.1% | 86.4% |
| prep models (`_prep_models`) | 100.0% | 100.0% |
| geotag (`photos_2_geotag`) | 96.8% | 95.8% |
| geotag calc (`_geotag_calc`) | 98.1% | 94.8% |
| merge (`photos_3_merge`) | 92.4% | 91.2% |
| shared (`photos_utils`) | 90.6% | 87.4% |
| reporting (`reporting`) | 93.6% | 74.3% |
| cli | 90.9% | 83.3% |
| console server | 58.2% | 47.0% |
| editor server | 78.6% | 77.1% |
| **Total** | **90.9%** | **87.3%** |

Regenerate (branch coverage; report scoped to the production code via `.coveragerc`):

```bash
tools/coverage          # bootstraps a local .venv, runs the suite, writes htmlcov/ + the report
```

## Spec-clause coverage

`spec/spec-clauses.json` is a living index of the behavioral clauses across the four spec files, each
carrying a **spec pointer** (`file` + section heading). A guard test
(`tests/test_spec_coverage_registry.py`) fails if a pointer stops resolving to a real heading, so the
index can't silently drift from the specs.

| | Count |
|---|---:|
| Clauses indexed | 633 |
| **`must_cover` (CI-gated)** | **542** |
| Omitted (tracked, not gated) | 91 |

`must_cover` is the gated subset — every clause a genuine test asserts; each must keep a test tagged
`@pytest.mark.spec("<id>")`, enforced in CI by `tools/spec-coverage`. Gated clauses by area: prep 170,
shared 138, geotag 150, merge 84.

The 91 omitted clauses each carry an `omit_reason`: **53** are `incidental` (exercised by happy-path
tests but with no dedicated assertion), **37** are `none`, and **1** has a tagged test that does not assert it whole. Only **8** omitted clauses are
HIGH-criticality, each for a documented reason — crash-injection atomicity (out of scope; see the
audit doc §4), cross-cutting principles asserted only in aggregate, flock lock-takeover (OS-released,
no reclaim code), a symlink guard delegated to prep, and a concurrency property implied by the `-j1`
vs `-jN` equality test.

Check / regenerate:

```bash
tools/spec-coverage              # report + CI gate (fails if a must_cover clause lost its test)
tools/spec-coverage --verbose    # per-clause table (gate flag, coverage, spec pointer, test count)
```

See also `docs/design/spec-test-coverage-audit.md` — the original clause-by-clause audit and its
follow-up (what each subsequent change closed). This is a **map of which spec behaviours have a
dedicated test, not a quality score**: a tag asserts a test exists; the assertion lives in the test.

## The spec corpus

The specs are being converted into one corpus of typed items (`spec/`; see `spec/README.md`): 300 rules and
invariants, 221 rationales, 155 build items, and the 394 tests that name an item they verify. `tools/spec-build`
fails if any of the **276** rules and invariants marked `verify: required` has no test naming it, if a rule has no
rationale, or if a link dangles; CI runs it. 672 items are ruled; 40 — the philosophy's facts, choices and
rationales — are still at seed. The clause index above keeps gating the clauses of the specs not yet converted.

```bash
tools/spec-build                 # the corpus gate; rewrites spec/needs.json
tools/spec-ledger check          # every sentence of a converted spec accounted for
```

