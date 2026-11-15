# Test coverage

This pipeline mutates irreplaceable originals, so coverage is tracked on **two axes**:

1. **Line / branch** coverage of the production code (`coverage.py`).
2. **Spec** coverage — which items of the specification corpus (`spec/`) a test verifies, checked at every
   build by `tools/spec-build`. Line/branch can't tell you whether a *must-refuse / no-clobber /
   leaves-untouched* obligation is actually asserted; this can.

Figures below are a snapshot; regenerate with the commands shown. The suite has **1538 tests**.

## Line / branch coverage

The geotag phase — the one that writes time and GPS into the originals — is the most heavily tested.
The lighter areas are the two local web servers (console, editor): thin affordance layers over the
same plan/validate/execute core the phases provide, neither of which writes metadata into photos.

| Component | Line | Branch |
|---|---:|---:|
| prep (`photos_1_prep`) | 94.2% | 88.7% |
| prep models (`_prep_models`) | 100.0% | 100.0% |
| geotag (`photos_2_geotag`) | 96.0% | 95.4% |
| geotag calc (`_geotag_calc`) | 98.1% | 96.7% |
| merge (`photos_3_merge`) | 94.0% | 94.2% |
| shared (`photos_utils`) | 91.2% | 88.5% |
| reporting (`reporting`) | 93.6% | 74.3% |
| cli | 90.9% | 83.3% |
| console server | 66.5% | 56.8% |
| editor server | 81.9% | 81.7% |
| **Total** | **92.4%** | **89.7%** |

Regenerate (branch coverage; report scoped to the production code via `.coveragerc`):

```bash
tools/coverage          # bootstraps a local .venv, runs the suite, writes htmlcov/ + the report
```

## Spec coverage

The specification is one corpus of typed items (`spec/`; see `spec/README.md`; published at
[sigfridvonshrink.github.io/photos-cartographer](https://sigfridvonshrink.github.io/photos-cartographer/), its tests at
[`_generated/tests.html`](https://sigfridvonshrink.github.io/photos-cartographer/_generated/tests.html)): 521 rules and invariants, 290
rationales, 191 build items, 32 definitions, the philosophy's 3 facts and 4 choices — and the 708 tests that name the
items they verify, made items of the corpus from their `@pytest.mark.spec(…, test="TST-…")` marks. 1040 items are
ruled; one is at seed: `RUL-disagreeing_tracks_place_nothing`, held for BACKLOG 29.

| Rules and invariants | Count |
|---|---:|
| **`verify: required` — a test must name it (gated)** | **518** |
| **`verify: by_rules` — an invariant, verified through the rules that uphold it, each gated** | **3** |
| `verify: incidental` — exercised, not asserted | 0 |
| `verify: none` — nothing checks them | 0 |

`tools/spec-build` fails if any item marked `verify: required` has no test naming it, if a test mark names no item, if
a rule has no rationale, or if a link dangles; CI and the pre-push hook run it. This is a **map of which specified
behaviours have a dedicated test, not a quality score**: a mark asserts a test exists; the assertion lives in the test.

```bash
tools/spec-build                 # the corpus gate; rewrites spec/needs.json
```

The corpus was converted from four spec documents and checked against a clause index of 633 clauses; both, with the
conversion ledgers, are kept at the git tag `specs-before-corpus`.
