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

"""How a run ended, told by its exit status (RUL-exit_status_says_how_it_ended, BLD-exit_statuses): geotag's
execute here, its workflow stood in for at the seams `run` calls; merge's is in test_merge_execute.

photos_utils / photos_2_geotag come from conftest.py.
"""
import json
import types

import pytest

import photos_utils as utils
import photos_2_geotag as cal

MANAGED = ["0-sources", "1-strays", "2-missing-metadata", "3-redundant-jpgs",
           "4-videos-by-date", "5-photos-by-date", "6-photos-by-dest"]


def _ws(tmp_path):
    ws = tmp_path / "ws"
    ws.mkdir()
    for d in MANAGED:
        (ws / d).mkdir()
    ctl = ws / ".photos-ingest"
    ctl.mkdir()
    (ctl / "photos-00-workspace-guard").touch()
    (ctl / "photos-24-executable-plan.json").write_text(json.dumps({"plan_id": "p"}))
    return ws


def _summary(status):
    return {"status": status, "failures": [], "fingerprint_mismatches": [],
            "totals": {"metadata_time_writes": 0, "metadata_gps_writes": 0, "renames": 0}}


@pytest.mark.parametrize("end, status", [("done", 0), ("locked", 1), ("refused", 2), ("stale", 2), ("partial", 3),
                                         ("failed", 3), ("interrupted", 130)])
@pytest.mark.spec("RUL-exit_status_says_how_it_ended", "BLD-exit_statuses",
                  test="TST-exit_status-each_end_of_a_geotag_execute_has_its_own_exit_status")
def test_each_end_of_a_geotag_execute_has_its_own_exit_status(tmp_path, monkeypatch, end, status):
    """Geotag's execute ends 0 done, 1 with the workspace locked, 2 refused — by a precondition or a stale plan —,
    3 partial or failed and 130 interrupted."""
    ws = _ws(tmp_path)
    monkeypatch.chdir(ws)
    monkeypatch.setattr(cal.GeotagWorkflow, "preflight",
                        lambda self, for_execute=False: ((["a precondition"] if end == "refused" else []), [], {}))

    def execute_plan(self, jobs, now_iso, execution_id):
        if end == "interrupted":
            raise KeyboardInterrupt
        if end == "stale":
            return {"status": "rejected", "stale": ["photos-21 changed"]}
        return _summary({"done": "success"}.get(end, end))
    monkeypatch.setattr(cal.GeotagWorkflow, "execute_plan", execute_plan)
    held = utils.WorkspaceLock(str(ws), create=False) if end == "locked" else None
    if held:
        assert held.acquire() is True
    try:
        cal.run(types.SimpleNamespace(command="execute", jobs=1))
        code = 0
    except SystemExit as e:
        code = e.code
    finally:
        if held:
            held.release()
    assert code == status
