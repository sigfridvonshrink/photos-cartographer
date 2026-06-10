import os
import sys
import copy
import importlib.machinery
import importlib.util

import pytest

# The prep workflow is an extensionless script (`ingest/photos-1-prep`) plus its
# `photos_utils.py` companion. Each test file used to load the script itself via
# SourceFileLoader under the shared name "photos_1_prep", and some replaced
# sys.modules["photos_1_prep"] outright. In a combined pytest session that made a
# test's captured module reference diverge from what `@patch("photos_1_prep...")`
# resolves at runtime, so patches missed and real hashing ran.
#
# Load each module exactly once here (conftest is imported before the test modules
# in this directory) so every `import photos_1_prep` / `import photos_utils` in the
# tests returns the same, stable instance.
_INGEST_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if _INGEST_DIR not in sys.path:
    sys.path.insert(0, _INGEST_DIR)


def _load_once(module_name, filename):
    if module_name not in sys.modules:
        path = os.path.join(_INGEST_DIR, filename)
        loader = importlib.machinery.SourceFileLoader(module_name, path)
        spec = importlib.util.spec_from_loader(module_name, loader)
        module = importlib.util.module_from_spec(spec)
        sys.modules[module_name] = module
        loader.exec_module(module)
    return sys.modules[module_name]


# Order matters: photos-1-prep does `from photos_utils import ...` at load time.
_load_once("photos_utils", "photos_utils.py")
_load_once("photos_1_prep", "photos-1-prep")
_load_once("photos_2_time_gps", "photos-2-time-gps")   # calibration phase


@pytest.fixture(autouse=True)
def _restore_config():
    """Isolate tests from one another's mutations of the shared global CONFIG.

    Now that all test files share a single photos_utils instance, a test that sets
    e.g. CONFIG["jobs"] would otherwise leak into later tests. Snapshot and restore.
    """
    import photos_utils

    saved = copy.deepcopy(photos_utils.CONFIG)
    try:
        yield
    finally:
        photos_utils.CONFIG.clear()
        photos_utils.CONFIG.update(saved)
