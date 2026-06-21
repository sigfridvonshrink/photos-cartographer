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
_REQUIRED = {"id", "area", "criticality", "anti", "title"}


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


def test_every_registered_clause_is_tagged_somewhere():
    """Text-scan tests/ for `mark.spec("<id>")` — so the suite itself fails if a registered clause
    loses its tag, even without running the standalone tools/spec-coverage gate."""
    tagged = set()
    pat = re.compile(r'mark\.spec\("([^"]+)"\)')
    for path in glob.glob(os.path.join(ROOT, "tests", "*.py")):
        with open(path) as f:
            tagged.update(pat.findall(f.read()))
    untagged = [c["id"] for c in _clauses() if c["id"] not in tagged]
    assert not untagged, f"registered clauses with no @pytest.mark.spec tag: {untagged}"
