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

"""Geotag never writes the workspace's configuration — not its first plan, nor any after, nor execute or finalize."""
import json

import pytest

from test_geotag_finalize import _ready_ws, _run


@pytest.mark.spec("RUL-config_writers", test="TST-geotag_leaves_the_config-every_geotag_command_leaves_the_config")
def test_every_geotag_command_leaves_the_config(tmp_path, monkeypatch):
    """The configuration's bytes, taken before geotag's first plan, are the same after that plan, the plan made
    again once its decisions are complete, the execute and the finalize."""
    ws, ctl = _ready_ws(tmp_path, monkeypatch)
    cfg_p = ctl / "photos-00-config.json"
    before = cfg_p.read_bytes()
    _run(monkeypatch, ws, "plan")
    assert cfg_p.read_bytes() == before, "first plan"
    td = ctl / "photos-21-time-decisions.json"
    td.write_text(json.dumps(json.loads(td.read_text())))
    assert _run(monkeypatch, ws, "plan") == 0
    assert (ctl / "photos-24-executable-plan.json").exists()
    assert cfg_p.read_bytes() == before, "plan"
    assert _run(monkeypatch, ws, "execute") == 0
    assert cfg_p.read_bytes() == before, "execute"
    assert _run(monkeypatch, ws, "finalize") == 0
    assert cfg_p.read_bytes() == before, "finalize"
