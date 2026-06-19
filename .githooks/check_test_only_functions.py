#!/usr/bin/env python3
# Copyright 2026 sigfridvonshrink
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

"""Guard: fail if any production function is referenced ONLY by tests.

Production code (`photos-1-prep`, `photos-2-geotag`, `photos_utils.py`) must
not carry APIs that exist only to serve the test suite. This finds every name `def`-ed in those three
files that is referenced somewhere under `tests/` but NOWHERE in the production sources (other
than its own definition) — i.e. test-only production code — and exits non-zero so the pre-push hook
aborts. Remove the function and rewrite the test to not need it (inline the trivial work, or put a
shared helper in the test layer — conftest.py — never in production).

Run from the repo root:  python3 .githooks/check_test_only_functions.py
"""
import os
import re
import sys

SRC_FILES = ["photos_pipeline/photos_1_prep.py", "photos_pipeline/photos_2_geotag.py",
             "photos_pipeline/photos_3_merge.py", "photos_pipeline/photos_utils.py",
             "photos_pipeline/cli.py"]
TESTS_DIR = "tests"

# Names that are legitimately definition-only / entry points, not "test-only production code".
# Add a name here (with a comment justifying it) only if it is a genuine exception.
# (The merge-phase shared primitives that were temporarily allowlisted while photos-3-merge
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
