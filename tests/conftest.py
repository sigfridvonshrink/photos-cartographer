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


@pytest.fixture
def seed_from_live_config(monkeypatch):
    """Make `load_or_seed_config` seed a fresh workspace from the IN-MEMORY `CONFIG` instead of the
    frozen built-in `DEFAULT_CONFIG`/external file. A few prep e2e tests deliberately mutate `CONFIG`
    (e.g. enable zfs, set a filename format, classify a device group) BEFORE the first prep run and
    expect that to be what gets seeded — request this fixture so seeding honours the configured state.
    """
    monkeypatch.setattr(photos_utils, "default_config",
                        lambda: {k: v for k, v in photos_utils.CONFIG.items() if k != "jobs"})
