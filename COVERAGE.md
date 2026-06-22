# Test coverage

This pipeline mutates irreplaceable originals, so coverage is tracked on **two axes**:

1. **Line / branch** coverage of the production code (`coverage.py`).
2. **Spec-clause** coverage — which behavioral clauses in `spec/*.md` have a dedicated test
   (`tools/spec-coverage` over `spec/spec-clauses.json`). Line/branch can't tell you whether a
   *must-refuse / no-clobber / leaves-untouched* obligation is actually asserted; this can.

Figures below are a snapshot; regenerate with the commands shown. The suite is **870 tests**.

## Line / branch coverage

The geotag phase — the one that writes time and GPS into the originals — is the most heavily tested.
The lighter areas are the two local web servers (console, editor): thin affordance layers over the
same plan/validate/execute core the phases provide, neither of which writes metadata into photos.

| Component | Line | Branch |
|---|---:|---:|
| prep (`photos_1_prep`) | 90.3% | 83.6% |
| geotag (`photos_2_geotag`) | 98.4% | 96.9% |
| merge (`photos_3_merge`) | 86.4% | 83.6% |
| shared (`photos_utils`) | 88.8% | 84.8% |
| reporting (`reporting`) | 93.6% | 74.3% |
| cli | 87.9% | 75.0% |
| console server | 58.3% | 47.0% |
| editor server | 77.8% | 75.0% |
| **Total** | **89.0%** | **84.6%** |

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
| Clauses indexed | 611 |
| **`must_cover` (CI-gated)** | **517** |
| Omitted (tracked, not gated) | 94 |

`must_cover` is the gated subset — every clause a genuine test asserts; each must keep a test tagged
`@pytest.mark.spec("<id>")`, enforced in CI by `tools/spec-coverage`. Gated clauses by area: prep 163,
shared 128, geotag 142, merge 84.

The 94 omitted clauses each carry an `omit_reason`: **55** are `incidental` (exercised by happy-path
tests but with no dedicated assertion) and **39** are `none`. Only **8** omitted clauses are
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
