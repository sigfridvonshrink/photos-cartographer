# Test coverage

This pipeline mutates irreplaceable originals, so coverage is tracked on **two axes**:

1. **Line / branch** coverage of the production code (`coverage.py`).
2. **Spec** coverage — which items of the specification corpus (`spec/`) a test verifies, checked at every
   build by `tools/spec-build`. Line/branch can't tell you whether a *must-refuse / no-clobber /
   leaves-untouched* obligation is actually asserted; this can.

Figures below are a snapshot; regenerate with the commands shown. The suite has **2352 tests**.

## Line / branch coverage

The geotag phase — the one that writes time and GPS into the originals — is the most heavily tested.
The lighter areas are the two local web servers (console, editor): thin affordance layers over the
same plan/validate/execute core the phases provide, neither of which writes metadata into photos.

| Component | Line | Branch |
|---|---:|---:|
| prep (`photos_1_prep`) | 95.4% | 90.9% |
| prep models (`_prep_models`) | 100.0% | 100.0% |
| geotag (`photos_2_geotag`) | 96.5% | 93.8% |
| geotag calc (`_geotag_calc`) | 97.7% | 94.9% |
| merge (`photos_3_merge`) | 95.0% | 95.1% |
| shared (`photos_utils`) | 92.8% | 91.1% |
| reporting (`reporting`) | 94.7% | 81.8% |
| cli | 91.2% | 83.3% |
| console server | 69.7% | 61.9% |
| editor server | 85.5% | 87.6% |
| **Total** | **93.9%** | **91.4%** |

Regenerate (branch coverage; report scoped to the production code via `.coveragerc`):

```bash
tools/coverage          # bootstraps a local .venv, runs the suite, writes htmlcov/ + the report
```

## Spec coverage

The specification is one corpus of typed items (`spec/`; see `spec/README.md`; published at
[sigfridvonshrink.github.io/photos-cartographer](https://sigfridvonshrink.github.io/photos-cartographer/), its tests at
[`_generated/tests.html`](https://sigfridvonshrink.github.io/photos-cartographer/_generated/tests.html)): 795 rules and invariants, 389
rationales, 352 build items, 47 definitions, the philosophy's 3 facts and 4 choices — and the 1327 tests that name the
items they verify, made items of the corpus from their `@pytest.mark.spec(…, test="TST-…")` marks. All 1590 items are
ruled.

| Rules and invariants | Count |
|---|---:|
| **`verify: required` — a test must name it (gated)** | **788** |
| **`verify: by_rules` — an invariant, verified through the rules that uphold it, each gated** | **3** |
| `verify: incidental` — exercised, not asserted | 0 |
| `verify: none` — nothing checks them | 0 |

`tools/spec-build` fails if any item marked `verify: required` has no test naming it, if a test mark names no item or
carries no test id, if
a rule has no rationale or no build item realising it, if an exception is stated by anything but a rule, if a retired
word is used, or if a link dangles; CI and the pre-push hook run it. This is a **map of which specified
behaviours have a dedicated test, not a quality score**: a mark asserts a test exists; the assertion lives in the test.

```bash
tools/spec-build                 # the corpus gate; rewrites spec/needs.json
```

The corpus was converted from four spec documents and checked against a clause index of 633 clauses; both, with the
conversion ledgers, are in the repository's history, as they stood at the release `v2.0.0`.
