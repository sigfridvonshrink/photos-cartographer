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
from pathlib import Path
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

    def execute_plan(self, jobs, now_iso, execution_id, workspace_changes=()):
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


@pytest.mark.spec("RUL-every_question_in_editor", "RUL-every_question_answerable_by_hand",
                  test="TST-exit_status-a_changed_photo_s_execute_names_the_editor_and_the_field")
def test_a_changed_photo_s_execute_names_the_editor_and_the_field(tmp_path, monkeypatch, capsys):
    """An execution that found a photo's content changed when written ends partial, and says where its one question is
    answered: the decision editor, or the field of photos-25 by hand."""
    ws = _ws(tmp_path)
    monkeypatch.chdir(ws)
    monkeypatch.setattr(cal.GeotagWorkflow, "preflight", lambda self, for_execute=False: ([], [], {}))
    monkeypatch.setattr(cal, "prep_log_blocker", lambda ws, handoff: None)
    summary = dict(_summary("partial"), fingerprint_mismatches=[{"relative_path": "6-photos-by-dest/A/x.jpg",
                                                                  "expected_fingerprint": "a", "actual_fingerprint": "b",
                                                                  "user_decision": {"accept_fingerprint_change": False}}])
    monkeypatch.setattr(cal.GeotagWorkflow, "execute_plan", lambda self, *a, **k: summary)
    with pytest.raises(SystemExit) as e:
        cal.run(types.SimpleNamespace(command="execute", jobs=1))
    assert e.value.code == 3
    out = capsys.readouterr()
    said = out.out + out.err
    assert "photos-cartographer edit" in said and "accept_fingerprint_change" in said


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


@pytest.mark.parametrize("argv", [["prune-quarantine", "--yes"], ["prune-quarantine", "--older-than-days", "0"]])
@pytest.mark.spec("RUL-exit_status_says_how_it_ended", "BLD-exit_statuses",
                  test="TST-exit_status-a_refused_prune_ends_as_a_refusal")
def test_a_refused_prune_ends_as_a_refusal(tmp_path, monkeypatch, argv):
    """`prune-quarantine` refusing its selection — a delete naming nothing without `--all`, an age below one day —
    ends 2, a refusal, not 1, which says the workspace is locked; nothing in quarantine is removed."""
    ws = _prep_ws(tmp_path)
    run = Path(utils.quarantine_dir(str(ws))) / "20240101T000000Z-aaaa"
    run.mkdir(parents=True)
    (run / "x.jpg").write_text("x")
    monkeypatch.chdir(str(ws))
    monkeypatch.setattr(sys, "argv", ["photos-1-prep", *argv])
    with pytest.raises(SystemExit) as e:
        prep.main()
    assert e.value.code == 2
    assert (run / "x.jpg").exists()


@pytest.mark.parametrize("phase", ["prep", "prep_execute", "geotag", "merge", "cli"])
@pytest.mark.spec("RUL-exit_status_says_how_it_ended", "BLD-exit_statuses",
                  test="TST-exit_status-an_unforeseen_error_ends_with_a_status_of_its_own")
def test_an_unforeseen_error_ends_with_a_status_of_its_own(tmp_path, monkeypatch, capsys, phase):
    """An error no command foresaw ends prep, geotag, merge — and any command run through the combined entry — with
    4, never 1, which says the workspace is locked; it is named, and the workspace's lock is free again after."""
    import photos_3_merge as merge
    from cartographer import cli
    from cartographer.editor import server as editor

    def boom(*a, **k):
        raise RuntimeError("an error no one foresaw")
    if phase == "prep":
        ws = _prep_ws(tmp_path)
        monkeypatch.setattr(prep.WorkspacePrepWorkflow, "plan", boom)
        code = _prep(monkeypatch, ws, "plan")
    elif phase == "prep_execute":
        ws = _prep_ws(tmp_path)
        assert _prep(monkeypatch, ws, "plan") == 0
        monkeypatch.setattr(prep.PlanExecutor, "execute", boom)
        code = _prep(monkeypatch, ws, "execute")
    else:
        ws = _ws(tmp_path)
        monkeypatch.chdir(ws)
        try:
            if phase == "geotag":
                monkeypatch.setattr(cal.GeotagWorkflow, "preflight", lambda self, for_execute=False: ([], [], {}))
                monkeypatch.setattr(cal, "prep_log_blocker", lambda ws, handoff: None)
                monkeypatch.setattr(cal.GeotagWorkflow, "execute_plan", boom)
                cal.run(types.SimpleNamespace(command="execute", jobs=1))
            elif phase == "merge":
                monkeypatch.setattr(merge, "_run_locked_workflow", boom)
                merge.run(types.SimpleNamespace(command="plan", jobs=None, accept_changes=None))
            else:
                monkeypatch.setattr(editor, "run", boom)
                cli.main(["edit"])
            code = 0
        except SystemExit as e:
            code = e.code
    assert code == utils.UNFORESEEN_ERROR_EXIT == 4
    assert "an error no one foresaw" in capsys.readouterr().err
    lock = utils.WorkspaceLock(str(ws), create=False)
    assert lock.acquire() is True
    lock.release()


@pytest.mark.skipif(os.geteuid() == 0, reason="root opens a file whatever its permissions")
@pytest.mark.parametrize("phase", ["prep", "geotag", "merge"])
@pytest.mark.spec("RUL-exit_status_says_how_it_ended", "BLD-exit_statuses",
                  test="TST-exit_status-a_lock_file_that_cannot_be_opened_is_a_refusal")
def test_a_lock_file_that_cannot_be_opened_is_a_refusal(tmp_path, monkeypatch, capsys, phase):
    """A workspace lock file the run may not open ends prep, geotag and merge with 2, a refusal naming the file — never
    1, which would say another run holds the lock."""
    import photos_3_merge as merge
    ws = _prep_ws(tmp_path) if phase == "prep" else _ws(tmp_path)
    lock = Path(utils.lock_path(str(ws)))
    lock.touch()
    lock.chmod(0)
    try:
        if phase == "prep":
            code = _prep(monkeypatch, ws, "plan")
        else:
            monkeypatch.chdir(ws)
            try:
                if phase == "geotag":
                    cal.run(types.SimpleNamespace(command="execute", jobs=1))
                else:
                    merge.run(types.SimpleNamespace(command="plan", jobs=None, accept_changes=None))
                code = 0
            except SystemExit as e:
                code = e.code
    finally:
        lock.chmod(0o644)
    assert code == 2
    err = capsys.readouterr().err
    assert str(lock) in err and "locked by an in-progress run" not in err
