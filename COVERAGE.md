# Test coverage

This pipeline mutates irreplaceable originals, so coverage is tracked on **two axes**:

1. **Line / branch** coverage of the production code (`coverage.py`).
2. **Spec** coverage — which items of the specification corpus (`spec/`) a test verifies, checked at every
   build by `tools/spec-build`. Line/branch can't tell you whether a *must-refuse / no-clobber /
   leaves-untouched* obligation is actually asserted; this can.

Figures below are a snapshot; regenerate with the commands shown. The suite has **1187 tests**.

## Line / branch coverage

The geotag phase — the one that writes time and GPS into the originals — is the most heavily tested.
The lighter areas are the two local web servers (console, editor): thin affordance layers over the
same plan/validate/execute core the phases provide, neither of which writes metadata into photos.

| Component | Line | Branch |
|---|---:|---:|
| prep (`photos_1_prep`) | 92.1% | 86.4% |
| prep models (`_prep_models`) | 100.0% | 100.0% |
| geotag (`photos_2_geotag`) | 95.6% | 94.5% |
| geotag calc (`_geotag_calc`) | 98.1% | 94.7% |
| merge (`photos_3_merge`) | 92.4% | 91.2% |
| shared (`photos_utils`) | 90.6% | 87.2% |
| reporting (`reporting`) | 93.6% | 74.3% |
| cli | 90.9% | 83.3% |
| console server | 58.2% | 47.0% |
| editor server | 78.6% | 77.1% |
| **Total** | **90.9%** | **87.3%** |

Regenerate (branch coverage; report scoped to the production code via `.coveragerc`):

```bash
tools/coverage          # bootstraps a local .venv, runs the suite, writes htmlcov/ + the report
```

## Spec coverage

The specification is one corpus of typed items (`spec/`; see `spec/README.md`): 365 rules and invariants, 266
rationales, 187 build items, 31 definitions, the philosophy's 3 facts and 4 choices — and the 484 tests that name the
items they verify, made items of the corpus from their `@pytest.mark.spec(…, test="TST-…")` marks. 799 items are
ruled; 57 — the items the geotag review of 2026-11-14 added or changed — are at seed, awaiting a ruling.

| Rules and invariants | Count |
|---|---:|
| **`verify: required` (gated)** | **341** |
| `verify: incidental` — exercised, not asserted (BACKLOG 4) | 17 |
| `verify: none` — nothing checks them (BACKLOG 3) | 7 |

`tools/spec-build` fails if any item marked `verify: required` has no test naming it, if a test mark names no item, if
a rule has no rationale, or if a link dangles; CI and the pre-push hook run it. This is a **map of which specified
behaviours have a dedicated test, not a quality score**: a mark asserts a test exists; the assertion lives in the test.

```bash
tools/spec-build                 # the corpus gate; rewrites spec/needs.json
```

The corpus was converted from four spec documents and checked against a clause index of 633 clauses; both, with the
conversion ledgers, are kept at the git tag `specs-before-corpus`.
