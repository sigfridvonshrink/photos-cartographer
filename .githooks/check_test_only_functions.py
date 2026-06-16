#!/usr/bin/env python3
"""Guard: fail if any production function is referenced ONLY by tests.

Production code (`ingest/photos-1-prep`, `ingest/photos-2-time-gps`, `ingest/photos_utils.py`) must
not carry APIs that exist only to serve the test suite. This finds every name `def`-ed in those three
files that is referenced somewhere under `ingest/tests/` but NOWHERE in the production sources (other
than its own definition) — i.e. test-only production code — and exits non-zero so the pre-push hook
aborts. Remove the function and rewrite the test to not need it (inline the trivial work, or put a
shared helper in the test layer — conftest.py — never in production).

Run from the repo root:  python3 .githooks/check_test_only_functions.py
"""
import os
import re
import sys

SRC_FILES = ["ingest/photos_pipeline/photos_1_prep.py", "ingest/photos_pipeline/photos_2_time_gps.py",
             "ingest/photos_pipeline/photos_3_merge.py", "ingest/photos_pipeline/photos_utils.py",
             "ingest/photos_pipeline/cli.py"]
TESTS_DIR = "ingest/tests"

# Names that are legitimately definition-only / entry points, not "test-only production code".
# Add a name here (with a comment justifying it) only if it is a genuine exception.
# (The merge-phase shared primitives that were temporarily allowlisted while ingest/photos-3-merge
# was being built are now consumed by it — and the script is in SRC_FILES above — so the sweep sees
# their real callers and no exemption is needed.)
ALLOWLIST = set()


def _defs(path):
    out = []
    with open(path) as f:
        for i, line in enumerate(f, 1):
            m = re.match(r"\s*(?:async def|def)\s+([A-Za-z_]\w*)", line)
            if m:
                out.append((m.group(1), i))
    return out


def _ref_count(name, paths, *, exclude_def):
    """Word-boundary references to `name` across `paths`; optionally skip lines that DEFINE it."""
    pat = re.compile(rf"\b{re.escape(name)}\b")
    def_pat = re.compile(rf"(?:async def|def)\s+{re.escape(name)}\b")
    total, files = 0, set()
    for p in paths:
        try:
            text = open(p).read()
        except OSError:
            continue
        for line in text.splitlines():
            if not pat.search(line):
                continue
            if exclude_def and def_pat.search(line):
                continue
            total += 1
            files.add(p)
    return total, files


def main():
    test_files = [os.path.join(TESTS_DIR, f) for f in sorted(os.listdir(TESTS_DIR))
                  if f.endswith(".py")]
    offenders, seen = [], set()
    for sf in SRC_FILES:
        for name, line in _defs(sf):
            if name in seen or name in ALLOWLIST:
                continue
            if name.startswith("__") or name == "main":   # dunders + the CLI entry point
                continue
            seen.add(name)
            src_refs, _ = _ref_count(name, SRC_FILES, exclude_def=True)
            test_refs, tfiles = _ref_count(name, test_files, exclude_def=False)
            if src_refs == 0 and test_refs > 0:
                offenders.append((name, sf, line, sorted(os.path.basename(t) for t in tfiles)))

    if offenders:
        print("test-only-functions guard: FAILED — these are defined in production but referenced "
              "only by tests:", file=sys.stderr)
        for name, sf, line, tfiles in offenders:
            print(f"  - {name}  ({sf}:{line})  used in: {', '.join(tfiles)}", file=sys.stderr)
        print("\nRemove the function and rewrite the test (inline the work, or add a helper in the "
              "test layer — conftest.py). If it is a genuine exception, add it to ALLOWLIST in "
              ".githooks/check_test_only_functions.py with a justifying comment.", file=sys.stderr)
        return 1
    print("test-only-functions guard: OK (no production function is referenced only by tests).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
