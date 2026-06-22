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

"""Guards the spec-coverage registry (spec/spec-clauses.json) at the pytest level — a cheap
companion to the `tools/spec-coverage` CI gate. Asserts the registry is well-formed and that every
registered clause is actually tagged by at least one `@pytest.mark.spec("<id>")` somewhere in tests/.
"""
import glob
import json
import os
import re

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
REGISTRY = os.path.join(ROOT, "spec", "spec-clauses.json")
SPEC_DIR = os.path.join(ROOT, "spec")
_REQUIRED = {"id", "area", "criticality", "anti", "title", "spec"}


def _clauses():
    with open(REGISTRY) as f:
        return json.load(f)["clauses"]


def test_registry_is_well_formed():
    clauses = _clauses()
    assert clauses, "the registry must list at least one clause"
    ids = [c["id"] for c in clauses]
    assert len(ids) == len(set(ids)), "clause ids must be unique"
    for c in clauses:
        missing = _REQUIRED - c.keys()
        assert not missing, f"{c.get('id', '?')} is missing fields: {missing}"
        assert c["criticality"] in ("high", "med", "low"), c
        assert isinstance(c["anti"], bool)
        assert {"file", "section"} <= c["spec"].keys(), f"{c['id']} spec needs file+section"


def test_every_clause_spec_pointer_resolves_to_a_real_heading():
    """The sync guard: each clause's spec pointer (file + section) must resolve to an actual `## N` /
    `### N.N` heading in that spec file — so the registry can't silently drift when a spec section is
    renumbered or removed. Caches each spec file's heading set."""
    headings = {}
    for path in glob.glob(os.path.join(SPEC_DIR, "*.md")):
        with open(path) as f:
            headings[os.path.basename(path)] = set(
                re.findall(r'^#{2,3}\s+([0-9]+[0-9a-z]*(?:\.[0-9a-z]+)*)', f.read(), re.M))
    bad = []
    for c in _clauses():
        sp = c["spec"]
        if sp["file"] not in headings:
            bad.append(f"{c['id']}: spec file {sp['file']!r} not found")
        elif str(sp["section"]) not in headings[sp["file"]]:
            bad.append(f"{c['id']}: section {sp['section']!r} not a heading in {sp['file']}")
    assert not bad, "spec pointers that don't resolve (registry drifted from specs):\n  " + "\n  ".join(bad)


def test_every_must_cover_clause_is_tagged_somewhere():
    """Text-scan tests/ for `mark.spec("<id>")` — so the suite itself fails if a MUST-COVER clause
    loses its tag, even without running the standalone tools/spec-coverage gate. (Non-must-cover
    clauses are part of the index but not gated.)"""
    tagged = set()
    call = re.compile(r'mark\.spec\(([^)]*)\)')          # whole marker call (may carry multiple ids)
    for path in glob.glob(os.path.join(ROOT, "tests", "*.py")):
        with open(path) as f:
            for argblock in call.findall(f.read()):
                tagged.update(re.findall(r'"([^"]+)"', argblock))
    untagged = [c["id"] for c in _clauses() if c.get("must_cover") and c["id"] not in tagged]
    assert not untagged, f"must-cover clauses with no @pytest.mark.spec tag: {untagged}"
