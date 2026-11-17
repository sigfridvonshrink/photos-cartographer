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

"""A plan or a dry run names, file by file, the changes accepted earlier since the last execution, which no record of
its own names — the owner's preference (docs/design/decisions.md, "The owner's preferences")."""
import os

import pytest

from test_workspace_check import _change, _prep, _with_quarantine


@pytest.mark.spec("BLD-workspace_changes_logged", test="TST-accepted_changes_named-a_dry_run_names_each_change_accepted_earlier")
def test_a_dry_run_names_each_change_accepted_earlier(tmp_path, monkeypatch):
    ws, q = _with_quarantine(monkeypatch, tmp_path)
    stray = os.path.relpath(_change(ws, q, "stray_appeared"), ws)
    _rc, _said, stop = _prep(monkeypatch, ws, "plan")
    rc, said, _ = _prep(monkeypatch, ws, "plan", stop.code)
    assert rc == 0, said
    rc, said, again = _prep(monkeypatch, ws, "dry-run")
    assert rc == 0 and again is None, said
    tail = said.split("accepted earlier since the last execution", 1)[1]
    assert stray in tail, said
