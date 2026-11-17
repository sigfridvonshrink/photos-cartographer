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

"""The comparison with the recorded state, told by entries (BLD-workspace_check): a file edited in place keeping its
size is changed, sorting within photos by destination passes, and an interrupted execution's work passes only where
it is exactly what that run's records say (BLD-interrupted_run_recognised) — the interrupted runs built here from
their plans and journals written as the runs write them."""
import json
import os
import shutil

import pytest

import photos_3_merge as merge
import photos_utils as utils
from cartographer.reporting import CaptureSink, ChangesEvent, Reporter, use_reporter
from test_workspace_check import BY_DATE, BY_DEST, _by_date, _fresh, _ingest, _prep, _sort, _ws


def _check(ws, phase="prep", command="plan"):
    """The check as a command makes it: (entries for the run's log or None, the stop or None, the lines it stopped
    on)."""
    sink = CaptureSink()
    with use_reporter(Reporter([sink])):
        out, stop = utils.check_workspace(str(ws), phase, command)
    lines = [line for e in sink.events if isinstance(e, ChangesEvent) for line in e.lines]
    return out, stop, "\n".join(lines)


def _write(path, data):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "wb") as f:
        f.write(data)


# --- what the entries tell ---------------------------------------------------

@pytest.mark.spec("RUL-change_told_by_entries", "RUL-unexpected_change_stops",
                  test="TST-workspace_check_entries-an_edit_keeping_the_size_is_a_change")
def test_an_edit_keeping_the_size_is_a_change(tmp_path, monkeypatch):
    """A photo rewritten in place with other bytes of the same size — its modification time moved on, its inode
    kept — is changed in place, not a copy: the plan stops, naming it."""
    ws = _fresh(monkeypatch, tmp_path)
    p0 = _by_date(ws)[0]
    st = os.stat(p0)
    with open(p0, "r+b") as f:
        f.write(b"Z" * st.st_size)
    os.utime(p0, ns=(st.st_atime_ns, st.st_mtime_ns + 1_000_000_000))
    _id, record = utils.read_workspace_record(str(ws))
    assert utils.compare_workspace(record, utils.workspace_entries(str(ws))) == [
        {"kind": "changed", "path": os.path.relpath(p0, ws), "now": list(utils.workspace_entries(str(ws))[
            os.path.relpath(p0, ws)])}]
    rc, said, stop = _prep(monkeypatch, ws, "plan")
    assert rc == 2 and stop is not None and os.path.relpath(p0, ws) in "\n".join(stop.lines), said


@pytest.mark.spec("RUL-sorting_passes", test="TST-workspace_check_entries-sorting_within_photos_by_destination_passes")
def test_sorting_within_photos_by_destination_passes(tmp_path, monkeypatch):
    """A workspace whose sorting was recorded — photos in two destinations — then sorted on: a photo moved from one
    destination to another, and a destination's folder renamed. Each is sorting: the plan goes on, stopping on none."""
    ws = _fresh(monkeypatch, tmp_path)
    p0, p1, _ = _by_date(ws)
    _sort(ws, p0, "Rome")
    in_paris = _sort(ws, p1, "Paris")
    _ingest(monkeypatch, ws)                                                    # the sorting recorded
    os.rename(in_paris, ws / BY_DEST / "Rome" / in_paris.name)                  # from one destination to another
    os.rename(ws / BY_DEST / "Rome", ws / BY_DEST / "Roma")                     # a destination's folder renamed
    _id, record = utils.read_workspace_record(str(ws))
    changes = utils.compare_workspace(record, utils.workspace_entries(str(ws)))
    assert len(changes) == 2 and {c["kind"] for c in changes} == {"sorted"}, changes
    rc, said, stop = _prep(monkeypatch, ws, "plan")
    assert rc == 0 and stop is None and "--accept-changes" not in said, said


# --- an interrupted execution's work, and only it -------------------------

def _interrupted_prep(tmp_path, operations, plan_id="prep-killed"):
    """A recorded workspace and prep's plan `operations`, its execution noted begun and never recorded."""
    ws = _ws(tmp_path)
    return ws, lambda: (_save_prep_plan(ws, plan_id, operations), utils.note_execution_begun(str(ws), "prep", plan_id))


def _save_prep_plan(ws, plan_id, operations):
    with open(utils.prep_plan_path(str(ws)), "w") as f:
        json.dump({"plan_id": plan_id, "operations": operations}, f)


@pytest.mark.parametrize("left_by", ["a_rename", "a_copy"])
@pytest.mark.spec("RUL-interrupted_work_exact", "RUL-interrupted_work_passes", "BLD-interrupted_run_recognised",
                  test="TST-workspace_check_entries-a_recorded_photo_at_its_plan_place_passes_only_as_that_file")
def test_a_recorded_photo_at_its_plan_place_passes_only_as_that_file(tmp_path, left_by):
    """A recorded photo the interrupted run's plan moves, gone from where it was and found at the place the plan
    takes it: moved there — the same file, its inode kept — it passes as the run's work; a copy there, of the same size
    and time under another inode, is no file the run moved, and the check stops naming it."""
    src, dst = f"{BY_DATE}/2023/a.jpg", f"{BY_DATE}/2024/a.jpg"
    ws, begin = _interrupted_prep(tmp_path, [{"operation_id": "op-1", "type": "move_no_clobber", "source": src,
                                              "destination": dst}])
    _write(str(ws / src), b"AAAA")
    utils.write_workspace_record(str(ws))
    begin()
    os.makedirs(ws / BY_DATE / "2024")
    if left_by == "a_rename":
        os.rename(ws / src, ws / dst)
    else:
        shutil.copy2(ws / src, ws / dst)                                        # its size and time kept
        os.remove(ws / src)
        assert os.stat(ws / dst).st_mtime_ns == utils.read_workspace_record(str(ws))[1][src]["mtime_ns"]
    out, stop, listed = _check(ws)
    if left_by == "a_rename":
        assert stop is None and [(e["kind"], e["path"]) for e in out] == [("interrupted_run", dst)]
    else:
        assert stop == 2 and dst in listed, listed


@pytest.mark.parametrize("found_at", ["one_place", "two_places"])
@pytest.mark.spec("RUL-interrupted_work_exact", "RUL-interrupted_work_passes", "BLD-interrupted_run_recognised",
                  test="TST-workspace_check_entries-a_photo_found_at_two_of_its_plan_places_is_no_work_of_the_run")
def test_a_photo_found_at_two_of_its_plan_places_is_no_work_of_the_run(tmp_path, found_at):
    """A photo the interrupted run's plan files from the inbox and then renames, gone from the inbox: found with the
    size and time the plan found it with at one of the places the plan takes it, it passes as the run's work; found
    so at two of them, neither is exactly what the run left, and the check stops naming both."""
    src, mid, end = "0-sources/d.jpg", f"{BY_DATE}/2023/d.jpg", f"{BY_DATE}/2023/d2.jpg"
    ws = _ws(tmp_path)
    _write(str(ws / src), b"DDDD")
    st = os.stat(ws / src)
    pre = {"size": st.st_size, "mtime_ns": st.st_mtime_ns}
    utils.write_workspace_record(str(ws))
    _save_prep_plan(ws, "prep-killed", [
        {"operation_id": "op-1", "type": "move_no_clobber", "source": src, "destination": mid, "preconditions": pre},
        {"operation_id": "op-2", "type": "rename_no_clobber", "source": mid, "destination": end}])
    utils.note_execution_begun(str(ws), "prep", "prep-killed")
    os.makedirs(ws / BY_DATE / "2023")
    if found_at == "two_places":
        shutil.copy2(ws / src, ws / mid)
    shutil.copy2(ws / src, ws / end)
    os.remove(ws / src)
    out, stop, listed = _check(ws)
    if found_at == "one_place":
        assert stop is None and [(e["kind"], e["path"]) for e in out] == [("interrupted_run", end)]
    else:
        assert stop == 2 and mid in listed and end in listed, listed


def _interrupted_merge(tmp_path, journal_says):
    """A recorded workspace holding one photo in photos by destination, merge's plan placing it in the library, its
    execution noted begun and never recorded, the journal saying `journal_says` of it (None: no journal)."""
    ws = _ws(tmp_path)
    lib = tmp_path / "lib"
    src = f"{BY_DEST}/Trip/a.jpg"
    _write(str(ws / src), b"FP=A")
    utils.write_workspace_record(str(ws))
    target = str(lib / "Trip" / "a.jpg")
    with open(merge.merge_plan_path(str(ws)), "w") as f:
        json.dump({"plan_id": "merge-killed", "destinations": {"Trip": {"files": [
            {"by_dest_source": src, "library_target": target}]}}}, f)
    if journal_says:
        with open(utils.journal_path(str(ws), "merge-killed"), "w") as f:
            json.dump({"operations": {src: journal_says}}, f)
    utils.note_execution_begun(str(ws), "merge", "merge-killed")
    return ws, src, target


@pytest.mark.parametrize("target_holds", ["the_photo", "another_size"])
@pytest.mark.spec("RUL-interrupted_work_exact", "RUL-interrupted_work_passes", "BLD-interrupted_run_recognised",
                  test="TST-workspace_check_entries-a_photo_gone_from_by_dest_is_merges_only_as_its_target_says")
def test_a_photo_gone_from_by_dest_is_merges_only_as_its_target_says(tmp_path, target_holds):
    """A photo gone from photos by destination that the interrupted merge's journal does not confirm moved: where its
    library place holds a file of its recorded size and time it passes as the run's work; where the file there is of
    another size it is no work of the run, but a photo culled, as any other photo gone from there."""
    ws, src, target = _interrupted_merge(tmp_path, None)
    os.makedirs(os.path.dirname(target))
    if target_holds == "the_photo":
        os.rename(ws / src, target)
    else:
        _write(target, b"FP=A, and more")
        os.remove(ws / src)
    out, stop, _ = _check(ws, "merge", "plan")
    assert stop is None
    kind = "interrupted_run" if target_holds == "the_photo" else "deleted"
    assert [(e["kind"], e["path"]) for e in out] == [(kind, src)]


@pytest.mark.spec("RUL-interrupted_work_passes", "BLD-interrupted_run_recognised",
                  test="TST-workspace_check_entries-a_journal_confirmed_move_passes_though_its_target_changed_since")
def test_a_journal_confirmed_move_passes_though_its_target_changed_since(tmp_path):
    """A photo the interrupted merge's journal confirms moved into the library passes as that run's work, though the
    file at its library place has been changed since — the journal says what the run did."""
    ws, src, target = _interrupted_merge(tmp_path, "confirmed")
    os.makedirs(os.path.dirname(target))
    os.rename(ws / src, target)
    with open(target, "ab") as f:
        f.write(b" touched in the library since")
    out, stop, _ = _check(ws, "merge", "plan")
    assert stop is None
    assert [(e["kind"], e["path"]) for e in out] == [("interrupted_run", src)]
