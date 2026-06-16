import os
import sys

# The decision-editor server is now a package module (`photos_pipeline.editor.server`). Put `ingest/`
# on sys.path so `import photos_pipeline` resolves when pytest runs from the repo root, import the
# server once, and alias it under the historical short name `decision_editor_serve` so the test files
# (`import decision_editor_serve as serve`) and the Handler class attribute they toggle resolve to the
# one shared instance.
_INGEST_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", ".."))
if _INGEST_DIR not in sys.path:
    sys.path.insert(0, _INGEST_DIR)

from photos_pipeline.editor import server as _server  # noqa: E402

sys.modules.setdefault("decision_editor_serve", _server)
