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

import os
import sys
import copy

import pytest

# The phases live in the `cartographer` package at the repo root. Put the repo root on
# sys.path so `import cartographer` resolves when pytest runs from the repo root, import the modules
# once, then ALIAS them under their historical short names (`photos_1_prep`, `photos_utils`, …). Test
# files keep doing `import photos_1_prep` / `@patch("photos_1_prep....")`, and because the alias is the
# *same module object* as `cartographer.photos_1_prep`, every import and patch resolves identically
# (no SourceFileLoader hack, no divergent instances).
_REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)

from cartographer import photos_utils, photos_1_prep, photos_2_geotag, photos_3_merge  # noqa: E402

for _short, _mod in (("photos_utils", photos_utils), ("photos_1_prep", photos_1_prep),
                     ("photos_2_geotag", photos_2_geotag), ("photos_3_merge", photos_3_merge)):
    sys.modules.setdefault(_short, _mod)


@pytest.fixture(autouse=True)
def _restore_config():
    """Isolate tests from one another's mutations of the shared global CONFIG.

    All test files share the one photos_utils instance, so a test that sets e.g. CONFIG["jobs"] would
    otherwise leak into later tests. Snapshot and restore.
    """
    saved = copy.deepcopy(photos_utils.CONFIG)
    try:
        yield
    finally:
        photos_utils.CONFIG.clear()
        photos_utils.CONFIG.update(saved)
        photos_utils._refresh_media_class_map()   # a test that loaded a workspace's lists leaves none behind


@pytest.fixture
def seed_from_live_config(monkeypatch):
    """Make `load_or_seed_config` seed a fresh workspace from the IN-MEMORY `CONFIG` instead of the
    frozen built-in `DEFAULT_CONFIG`/external file. A few prep e2e tests deliberately mutate `CONFIG`
    (e.g. enable zfs, set a filename format, classify a device group) BEFORE the first prep run and
    expect that to be what gets seeded — request this fixture so seeding honours the configured state.
    """
    monkeypatch.setattr(photos_utils, "default_config",
                        lambda: {k: v for k, v in photos_utils.CONFIG.items() if k != "jobs"})


# --- spec-coverage map dump (see tools/spec-coverage) -----------------------
# A collection-only hook: when `--spec-dump=PATH` is passed, write a JSON map of
# {spec_clause_id: [test nodeids]} gathered from every collected test's `@pytest.mark.spec(...)`
# markers, then the tool cross-refs it against spec/spec-clauses.json. Zero cost in normal runs.
#
# `--spec-marks=PATH` writes the same marks for the spec corpus (spec/_ext/corpus.py), one record per marked test.
def pytest_addoption(parser):
    parser.addoption("--spec-dump", default=None,
                     help="(spec-coverage) write the spec-clause -> test-nodeid map as JSON to this path")
    parser.addoption("--spec-marks", default=None,
                     help="(the spec corpus) write every spec mark -- ids, test id, title, location -- as JSON here")


def _spec_marks(session):
    """One record per marked test: the ids its marks name, the test id one of them declares with `test="TST-..."`,
    a title (the docstring's first paragraph, else the function name) and where the test is."""
    import inspect
    records = []
    for item in session.items:
        marks = list(item.iter_markers(name="spec"))
        if not marks:
            continue
        ids = sorted({str(i) for m in marks for i in m.args})
        tests = sorted({m.kwargs["test"] for m in marks if "test" in m.kwargs})
        doc = inspect.getdoc(getattr(item, "function", None)) or ""
        title = doc.split("\n\n")[0].replace("\n", " ").strip() or item.name.replace("_", " ")
        path, line, _ = item.location
        records.append({"nodeid": item.nodeid, "file": path, "line": line + 1, "ids": ids,
                        "test": tests[0] if len(tests) == 1 else None, "tests": tests, "title": title})
    return records


def pytest_collection_finish(session):
    marks_path = session.config.getoption("--spec-marks")
    if marks_path:
        import json as _json
        with open(marks_path, "w") as f:
            _json.dump(_spec_marks(session), f, indent=1, sort_keys=True)
    path = session.config.getoption("--spec-dump")
    if not path:
        return
    import json as _json
    mapping = {}
    for item in session.items:
        for mark in item.iter_markers(name="spec"):
            for clause in mark.args:
                mapping.setdefault(str(clause), set()).add(item.nodeid)
    out = {k: sorted(v) for k, v in mapping.items()}
    with open(path, "w") as f:
        _json.dump(out, f, indent=2, sort_keys=True)
