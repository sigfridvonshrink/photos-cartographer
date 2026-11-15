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
execute here, its workflow stood in for at the seams `run` calls, and prep's plan and execute, run whole; merge's is
in test_merge_execute.

photos_utils / photos_1_prep / photos_2_geotag come from conftest.py.
"""
import json
import os
import sys
import types

import pytest

import photos_utils as utils
import photos_1_prep as prep
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
    monkeypatch.setattr(cal, "prep_log_blocker", lambda ws, handoff: None)     # the log vouched for

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


def _prep_ws(tmp_path):
    """An initialized workspace with snapshots off and a stray in 0-sources: a plan with one move to carry out."""
    ws = tmp_path / "ws"
    ws.mkdir()
    for d in MANAGED:
        (ws / d).mkdir()
    ctl = ws / ".photos-ingest"
    ctl.mkdir()
    (ctl / "photos-00-workspace-guard").touch()
    cfg = {k: v for k, v in utils.CONFIG.items() if k != "jobs"}
    cfg["zfs"] = dict(cfg["zfs"], enabled=False)
    (ctl / "photos-00-config.json").write_text(json.dumps(cfg))
    (ws / "0-sources" / "note.txt").write_text("stray")
    return ws


def _prep(monkeypatch, ws, command, held=False):
    """Prep's `command` run in `ws`, the workspace lock held by another run if `held`; its exit status."""
    monkeypatch.chdir(str(ws))
    monkeypatch.setattr(sys, "argv", ["photos-1-prep", command])
    lock = utils.WorkspaceLock(str(ws)) if held else None
    if lock:
        assert lock.acquire() is True
    try:
        prep.main()
        return 0
    except SystemExit as e:
        return e.code
    finally:
        if lock:
            lock.release()


@pytest.mark.parametrize("end, status", [("done", 0), ("locked", 1), ("stale", 2), ("unreadable", 2),
                                         ("snapshot", 2), ("failed", 3), ("interrupted", 130)])
@pytest.mark.spec("RUL-exit_status_says_how_it_ended", "BLD-exit_statuses",
                  test="TST-exit_status-each_end_of_a_prep_execute_has_its_own_exit_status")
def test_each_end_of_a_prep_execute_has_its_own_exit_status(tmp_path, monkeypatch, end, status):
    """Prep's execute ends 0 done, 1 with the workspace locked, 2 refused with nothing changed — its plan stale or
    unreadable, or a required snapshot not taken —, 3 when an operation fails and 130 interrupted."""
    ws = _prep_ws(tmp_path)
    assert _prep(monkeypatch, ws, "plan") == 0
    if end == "stale":
        cfg_p = ws / ".photos-ingest" / "photos-00-config.json"
        cfg_p.write_text(cfg_p.read_text() + "\n")            # a dependency changed after planning
    elif end == "unreadable":
        open(utils.prep_plan_path(str(ws)), "w").write("{ not json")
    elif end == "snapshot":
        monkeypatch.setattr(utils, "take_zfs_snapshot", lambda *a, **k: {
            "required": True, "ok": False, "snapshot_name": None, "command": "zfs snapshot", "exit_code": 1,
            "stdout": "", "stderr": "no dataset found"})
    elif end in ("failed", "interrupted"):
        def move(src, dst):
            raise KeyboardInterrupt if end == "interrupted" else OSError("disk gone")
        monkeypatch.setattr(prep, "_move_no_clobber", move)
    assert _prep(monkeypatch, ws, "execute", held=end == "locked") == status
    assert (ws / "0-sources" / "note.txt").exists() is (end != "done")


@pytest.mark.parametrize("end, status", [("done", 0), ("locked", 1), ("no_exiftool", 2), ("blocked", 2),
                                         ("other_schema", 2), ("interrupted", 130)])
@pytest.mark.spec("RUL-exit_status_says_how_it_ended", "RUL-blocked_plan_ends_refused", "BLD-exit_statuses",
                  test="TST-exit_status-each_end_of_a_prep_plan_has_its_own_exit_status")
def test_each_end_of_a_prep_plan_has_its_own_exit_status(tmp_path, monkeypatch, end, status):
    """Prep's plan ends 0 done, 1 with the workspace locked, 2 refused — exiftool absent, a blocker reported, a
    database of another schema — and 130 interrupted."""
    ws = _prep_ws(tmp_path)
    if end == "no_exiftool":
        monkeypatch.setattr("photos_utils.missing_tools", lambda tools: [t for t in tools if t == "exiftool"])
    elif end == "blocked":
        os.symlink("note.txt", ws / "0-sources" / "link.txt")  # a link among the photos blocks the plan
    elif end == "other_schema":
        cache = prep.WorkspaceCache(str(ws))
        cache.set_meta("cache_schema_version", "999")
        cache.close()
    elif end == "interrupted":
        def plan(self):
            raise KeyboardInterrupt
        monkeypatch.setattr(prep.WorkspacePrepWorkflow, "plan", plan)
    assert _prep(monkeypatch, ws, "plan", held=end == "locked") == status
