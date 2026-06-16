import os
import sys
import copy

import pytest

# The phases now live in the `photos_pipeline` package (`ingest/photos_pipeline/`). Put `ingest/` on
# sys.path so `import photos_pipeline` resolves when pytest runs from the repo root, import the modules
# once, then ALIAS them under their historical short names (`photos_1_prep`, `photos_utils`, …). Test
# files keep doing `import photos_1_prep` / `@patch("photos_1_prep....")`, and because the alias is the
# *same module object* as `photos_pipeline.photos_1_prep`, every import and patch resolves identically
# (no SourceFileLoader hack, no divergent instances).
_INGEST_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if _INGEST_DIR not in sys.path:
    sys.path.insert(0, _INGEST_DIR)

from photos_pipeline import photos_utils, photos_1_prep, photos_2_time_gps, photos_3_merge  # noqa: E402

for _short, _mod in (("photos_utils", photos_utils), ("photos_1_prep", photos_1_prep),
                     ("photos_2_time_gps", photos_2_time_gps), ("photos_3_merge", photos_3_merge)):
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
