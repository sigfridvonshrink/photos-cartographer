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

# The decision-editor server is now a package module (`photos_pipeline.editor.server`). Put the repo
# root on sys.path so `import photos_pipeline` resolves when pytest runs from the repo root, import the
# server once, and alias it under the historical short name `decision_editor_serve` so the test files
# (`import decision_editor_serve as serve`) and the Handler class attribute they toggle resolve to the
# one shared instance.
_REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", ".."))
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)

from photos_pipeline.editor import server as _server  # noqa: E402

sys.modules.setdefault("decision_editor_serve", _server)
