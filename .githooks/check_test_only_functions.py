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

# NOTE: when the merge phase `ingest/photos-3-merge` is built, add it here so the same guard covers
# it too (the merge script must not carry test-only production functions either).
SRC_FILES = ["ingest/photos-1-prep", "ingest/photos-2-time-gps", "ingest/photos_utils.py"]
TESTS_DIR = "ingest/tests"

# Names that are legitimately definition-only / entry points, not "test-only production code".
# Add a name here (with a comment justifying it) only if it is a genuine exception.
ALLOWLIST = {
    # Merge-phase shared primitives, built ahead of their consumer in photos_utils.py (Increment 1).
    # They have unit tests but no production caller YET because ingest/photos-3-merge is not written
    # (Increments 2-5). Remove each from this set as the merge script wires it in (and add
    # photos-3-merge to SRC_FILES then — see the note above).
    "is_library",                      # merge preflight: library identity check (the .photos-library marker)
    "write_library_marker",            # `merge init-library`: bless a directory as a library
    "write_sealed_marker",             # merge §9.4: seal the workspace terminal on full success
    "suffix_root", "max_suffix",       # merge §7: append-at-max+1 collision-rename suffix scheme
    "reseal_archival_package",         # merge §9.4: re-seal the archive (photos-35-archive-manifest.json)
    "validate_merge_config",           # merge §4: deep-validate library_root + placement/collision policy
    "cache_library_fingerprint",       # merge §7: cache a resident library file's content fingerprint
    "get_cached_library_fingerprint",  # merge §7: read that cache (path+size+mtime keyed)
}


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
