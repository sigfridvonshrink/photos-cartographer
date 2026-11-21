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

"""Every run checks the workspace is as the last execution left it (BACKLOG 50).

Each checking command first compares the files with the record the last execution wrote — by their entries alone —
and passes what a person is expected to do (a dump in the inbox, sorting, culling, a photo moved back, a time given by
hand in missing metadata, a copy), naming the ones the log should know of; anything else stops the command, naming
each file, until it is undone or accepted once by the code the stop printed. Prep runs for real here, its fingerprint
and metadata reading stood in for, as in test_prep_log."""
import glob
import json
import os
import shutil
import types

import pytest

import photos_1_prep as prep
import photos_2_geotag as cal
import photos_3_merge as merge
import photos_utils as utils
from cartographer.reporting import CaptureSink, ChangesEvent, Reporter, use_reporter

MANAGED = ["0-sources", "1-strays", "2-missing-metadata", "3-redundant-jpgs",
           "4-videos-by-date", "5-photos-by-date", "6-photos-by-dest"]
BY_DATE, BY_DEST = "5-photos-by-date", "6-photos-by-dest"


def _install(monkeypatch):
    prep.CONFIG["zfs"] = {"enabled": False}
    prep.CONFIG["jobs"] = 1

    def hsh(p):
        with open(p, "rb") as f:
            return {"status": "valid", "strategy": "image-content-hash-v2",
                    "value": "sig-" + f.read().hex()[:24], "engine_version": "t"}
    monkeypatch.setattr(prep.ContentHasher, "fingerprint_image", hsh)

    def meta(folders, max_workers=4, progress_coordinator=None):
        res = {}
        for fo in folders:
            for fn in os.listdir(fo):
                p = os.path.join(fo, fn)
                if not os.path.isfile(p):
                    continue
                timed = not open(p, "rb").read().startswith(b"NOTIME")     # a photo with no recorded time
                res[p] = {"extraction_status": "extracted_ok",
                          **({"DateTimeOriginal": "2023:01:02 03:04:05"} if timed else {})}
        return res, set()
    monkeypatch.setattr(utils.MetadataReader, "read_metadata_concurrently", meta)


def _ws(tmp_path):
    ws = tmp_path / "ws"
    ws.mkdir()
    for d in MANAGED:
        (ws / d).mkdir()
    (ws / ".photos-ingest").mkdir()
    (ws / ".photos-ingest" / "photos-00-workspace-guard").touch()
    return ws


def _prep(monkeypatch, ws, command, code=None):
    """Run a prep command as the command line does; (exit status, everything it said, the stop's event or None)."""
    sink = CaptureSink()
    monkeypatch.chdir(ws)
    with use_reporter(Reporter([sink])):
        try:
            prep.run(types.SimpleNamespace(command=command, jobs=1, accept_changes=code))
            rc = 0
        except SystemExit as e:
            rc = e.code or 0
    stops = [e for e in sink.events if isinstance(e, ChangesEvent)]
    return rc, "\n".join(e.msg for e in sink.logs()), (stops[-1] if stops else None)


def _ingest(monkeypatch, ws):
    for cmd in ("plan", "execute"):
        rc, said, _ = _prep(monkeypatch, ws, cmd)
        assert rc == 0, said


def _by_date(ws):
    return sorted(glob.glob(str(ws / BY_DATE / "**" / "*.jpg"), recursive=True))


def _log(ws):
    with open(utils.prep_log_path(str(ws))) as f:
        return json.load(f)


def _fresh(monkeypatch, tmp_path, photos=(b"AAAA", b"BBBB", b"CCCC")):
    _install(monkeypatch)
    ws = _ws(tmp_path)
    for i, content in enumerate(photos):
        (ws / "0-sources" / f"p{i}.jpg").write_bytes(content)
    _ingest(monkeypatch, ws)
    return ws


def _sort(ws, src, dest):
    d = ws / BY_DEST / dest
    d.mkdir(parents=True, exist_ok=True)
    to = d / os.path.basename(src)
    os.rename(src, to)
    return to


# --- what a person is expected to do passes --------------------------------

@pytest.mark.spec("RUL-workspace_checked_first", "RUL-check_covers_media_folders", "RUL-sorting_passes",
                  "BLD-workspace_check", test="TST-workspace_check-what_a_person_is_expected_to_do_passes")
def test_what_a_person_is_expected_to_do_passes(tmp_path, monkeypatch):
    """A dump put into the inbox, photos sorted from photos by date into destinations and moved, a destination's
    folder renamed, the configuration and a decision record edited: the plan goes on, naming none of it."""
    ws = _fresh(monkeypatch, tmp_path)
    p0, p1, _ = _by_date(ws)
    (ws / "0-sources" / "new.jpg").write_bytes(b"DDDD")
    _sort(ws, p0, "Rome")
    moved = _sort(ws, p1, "Paris")
    os.rename(moved, ws / BY_DEST / "Rome" / moved.name)                        # moved within photos by destination
    os.rename(ws / BY_DEST / "Rome", ws / BY_DEST / "Roma")                     # a destination's folder renamed
    cfg = utils.config_path(str(ws))
    with open(cfg) as f:
        c = json.load(f)
    with open(cfg, "w") as f:
        json.dump(c, f, indent=4)                                               # the configuration edited
    (ws / ".photos-ingest" / "photos-21-time-decisions.json").write_text("{}")  # a decision record edited
    rc, said, stop = _prep(monkeypatch, ws, "plan")
    assert rc == 0 and stop is None, said
    assert "Changed by hand" not in said and "--accept-changes" not in said


@pytest.mark.spec("RUL-culling_passes", "RUL-allowed_changes_named", "BLD-workspace_changes_logged",
                  test="TST-workspace_check-a_culled_photo_passes_and_is_named_in_the_log")
def test_a_culled_photo_passes_and_is_named_in_the_log(tmp_path, monkeypatch):
    """Photos deleted by hand in photos by date and in photos by destination: the plan goes on, naming them; the
    execution writes them into prep's log, with the photos' fingerprints; the next run, the record rewritten, names
    them no more."""
    ws = _fresh(monkeypatch, tmp_path)
    p0, p1, _ = _by_date(ws)
    sorted_one = _sort(ws, p1, "Rome")
    _ingest(monkeypatch, ws)                                                    # the sort recorded
    os.remove(p0)
    os.remove(sorted_one)
    gone = sorted(os.path.relpath(p, ws) for p in (p0, sorted_one))
    rc, said, stop = _prep(monkeypatch, ws, "plan")
    assert rc == 0 and stop is None, said
    assert "deleted" in said and all(g in said for g in gone), said
    rc, said, _ = _prep(monkeypatch, ws, "execute")
    assert rc == 0, said
    plan_id = json.load(open(utils.prep_plan_path(str(ws))))["plan_id"]
    named = [c for c in _log(ws)["workspace_changes"] if c["run"] == plan_id]
    assert sorted(c["path"] for c in named) == gone and {c["kind"] for c in named} == {"deleted"}
    assert all(c["content_fingerprint"].startswith("sig-") for c in named)
    rc, said, _ = _prep(monkeypatch, ws, "plan")
    assert rc == 0 and not any(g in said for g in gone), said      # told once, not again


@pytest.mark.parametrize("folder, kind", [
    ("5-photos-by-date", "deleted"), ("6-photos-by-dest", "deleted"), ("4-videos-by-date", "deleted"),
    ("3-redundant-jpgs", "deleted"), ("2-missing-metadata", "removed"), ("1-strays", "removed"),
    (".photos-ingest-quarantine/run-1", "removed")])
@pytest.mark.spec("RUL-culling_passes", "RUL-unexpected_change_stops", "RUL-change_told_by_entries",
                  "RUL-check_covers_media_folders", "BLD-workspace_check",
                  test="TST-workspace_check-a_deletion_is_culling_only_where_a_person_culls")
def test_a_deletion_is_culling_only_where_a_person_culls(tmp_path, folder, kind):
    """A file gone from photos by date or by destination, videos by date or the redundant JPEGs is culling, allowed;
    gone from missing metadata, the strays or the quarantine it is a change no person is expected to make."""
    ws = _ws(tmp_path)
    (ws / folder).mkdir(parents=True, exist_ok=True)
    f = ws / folder / "x.jpg"
    f.write_bytes(b"XXXX")
    utils.write_workspace_record(str(ws))
    f.unlink()
    _id, record = utils.read_workspace_record(str(ws))
    assert utils.compare_workspace(record, utils.workspace_entries(str(ws))) == [
        {"kind": kind, "path": f"{folder}/x.jpg", "now": None}]


@pytest.mark.spec("RUL-moved_back_passes", "RUL-allowed_changes_named", "BLD-workspace_changes_logged",
                  "BLD-prep_log_build", test="TST-workspace_check-a_photo_moved_back_passes_and_is_named")
def test_a_photo_moved_back_passes_and_is_named(tmp_path, monkeypatch):
    """A photo moved back from photos by destination to photos by date: the plan goes on, naming it; the execution
    names it in prep's log, and the photo's journey says where it went."""
    ws = _fresh(monkeypatch, tmp_path)
    p0 = _by_date(ws)[0]
    sorted_one = _sort(ws, p0, "Rome")
    _ingest(monkeypatch, ws)
    os.rename(sorted_one, p0)
    rc, said, stop = _prep(monkeypatch, ws, "plan")
    assert rc == 0 and stop is None and "moved back" in said, said
    rc, said, _ = _prep(monkeypatch, ws, "execute")
    assert rc == 0, said
    log = _log(ws)
    assert [(c["kind"], c["from"], c["path"]) for c in log["workspace_changes"]] == [
        ("moved_back", os.path.relpath(sorted_one, ws), os.path.relpath(p0, ws))]
    entry = next(e for e in log["photos"].values() if e["prep_path"] == os.path.relpath(p0, ws))
    assert entry["journey"][-1]["action"] == "moved_to_by_date"


@pytest.mark.spec("RUL-hand_time_passes", "RUL-allowed_changes_named", "BLD-hand_change_is_work",
                  "RUL-prepped_nothing_to_do", test="TST-workspace_check-a_time_given_by_hand_in_missing_metadata_passes")
def test_a_time_given_by_hand_in_missing_metadata_passes(tmp_path, monkeypatch):
    """A photo prep set aside for want of a time, given one by hand where it lies: the plan goes on, naming it, and
    the execution — a change by hand is work for it, never nothing to do — names it in prep's log."""
    ws = _fresh(monkeypatch, tmp_path, photos=(b"NOTIME-1",))
    (left,) = glob.glob(str(ws / "2-missing-metadata" / "**" / "*.jpg"), recursive=True)
    with open(left, "wb") as f:
        f.write(b"TIMED-1, its time written by hand")
    rc, said, stop = _prep(monkeypatch, ws, "plan")
    assert rc == 0 and stop is None and "changed by hand" in said and os.path.relpath(left, ws) in said, said
    rc, said, _ = _prep(monkeypatch, ws, "execute")
    assert rc == 0, said
    assert [c["kind"] for c in _log(ws)["workspace_changes"]] == ["time_given"]
    rc, said, stop = _prep(monkeypatch, ws, "plan")                             # recorded: named no more
    assert rc == 0 and stop is None and "changed by hand" not in said, said


@pytest.mark.spec("RUL-copy_passes", "RUL-change_told_by_entries", "RUL-allowed_changes_named",
                  test="TST-workspace_check-a_copy_with_new_inodes_passes_and_is_named")
def test_a_copy_with_new_inodes_passes_and_is_named(tmp_path, monkeypatch):
    """A photo restored where it was from a copy, and another sorted by copying it and removing the original: each
    has a new inode but its size and modification time, so each is the same file — the plan goes on, naming both."""
    ws = _fresh(monkeypatch, tmp_path)
    p0, p1, _ = _by_date(ws)
    tmp = str(ws / "restore.tmp")
    shutil.copy2(p0, tmp)
    os.replace(tmp, p0)                                                          # restored in place
    (ws / BY_DEST / "Rome").mkdir()
    copied = ws / BY_DEST / "Rome" / os.path.basename(p1)
    shutil.copy2(p1, copied)
    os.remove(p1)                                                                # sorted by a copy
    _id, record = utils.read_workspace_record(str(ws))
    changes = utils.compare_workspace(record, utils.workspace_entries(str(ws)))
    assert sorted((c["kind"], c["path"]) for c in changes) == sorted(
        [("copied", os.path.relpath(p0, ws)), ("copied", os.path.relpath(copied, ws))])
    rc, said, stop = _prep(monkeypatch, ws, "plan")
    assert rc == 0 and stop is None and "a new inode" in said, said


# --- anything else stops -----------------------------------------------------

def _with_quarantine(monkeypatch, tmp_path):
    """A workspace prep has set a duplicate aside in, and a photo with no time left in missing metadata."""
    ws = _fresh(monkeypatch, tmp_path, photos=(b"AAAA", b"AAAA", b"BBBB", b"NOTIME-1"))
    (q,) = [p for p in glob.glob(str(ws / ".photos-ingest-quarantine" / "**" / "*"), recursive=True)
            if os.path.isfile(p) and not p.endswith("manifest.json")]
    return ws, q


def _change(ws, q, how):
    """Make the change `how`; return the path the stop must name."""
    p0 = _by_date(ws)[0]
    if how == "changed":
        with open(p0, "ab") as f:
            f.write(b" edited")
        return p0
    if how == "replaced":
        os.remove(p0)
        with open(p0, "wb") as f:
            f.write(b"another photo altogether")
        return p0
    if how == "appeared":
        p = os.path.join(os.path.dirname(p0), "put-here.jpg")
        open(p, "wb").write(b"EEEE")
        return p
    if how == "missing_metadata_removed":
        (p,) = glob.glob(str(ws / "2-missing-metadata" / "**" / "*.jpg"), recursive=True)
        os.remove(p)
        return p
    if how == "stray_appeared":
        p = str(ws / "1-strays" / "notes.txt")
        open(p, "w").write("x")
        return p
    if how == "quarantine_changed":
        with open(q, "ab") as f:
            f.write(b"!")
        return q
    if how == "quarantine_removed":
        os.remove(q)
        return q
    if how == "moved_between_folders":
        p = str(ws / "2-missing-metadata" / os.path.basename(p0))
        os.rename(p0, p)
        return p
    raise AssertionError(how)


_UNEXPECTED = ["changed", "replaced", "appeared", "missing_metadata_removed", "stray_appeared", "quarantine_changed",
               "quarantine_removed", "moved_between_folders"]


@pytest.mark.parametrize("how", _UNEXPECTED)
@pytest.mark.spec("RUL-unexpected_change_stops", "RUL-workspace_checked_first", "RUL-change_told_by_entries",
                  "RUL-check_covers_media_folders", "BLD-workspace_check", "BLD-exit_statuses",
                  test="TST-workspace_check-an_unexpected_change_stops_naming_the_file")
def test_an_unexpected_change_stops_naming_the_file(tmp_path, monkeypatch, how):
    """A photo changed in place, or another put at its path; a file appearing outside the inbox; one gone from
    missing metadata; anything in the strays or the quarantine changed; a photo moved where nobody sorts to: the plan
    stops, a refusal, naming the file, having planned nothing."""
    ws, q = _with_quarantine(monkeypatch, tmp_path)
    plan_before = open(utils.prep_plan_path(str(ws)), "rb").read()
    named = os.path.relpath(_change(ws, q, how), ws)
    rc, said, stop = _prep(monkeypatch, ws, "plan")
    assert rc == 2 and stop is not None, said
    assert named in said and "--accept-changes" in said, said
    assert open(utils.prep_plan_path(str(ws)), "rb").read() == plan_before        # nothing planned


@pytest.mark.no_hand_built_record
@pytest.mark.spec("RUL-workspace_checked_first", "BLD-workspace_check",
                  test="TST-workspace_check-every_checking_command_checks")
def test_every_checking_command_checks(tmp_path, monkeypatch):
    """Prep's plan, dry run and execute; geotag's plan, execute and finalize; merge's plan, dry run and execute —
    each stops on the same change before it does anything else."""
    import test_merge_execute as mx
    ws = _fresh(monkeypatch, tmp_path)
    named = os.path.relpath(_change(ws, None, "appeared"), ws)
    for command in ("plan", "dry-run", "execute"):
        rc, said, stop = _prep(monkeypatch, ws, command)
        assert rc == 2 and stop is not None and named in said, (command, said)
    for command in ("plan", "execute", "finalize"):
        sink = CaptureSink()
        with use_reporter(Reporter([sink])), pytest.raises(SystemExit) as ei:
            cal.run(types.SimpleNamespace(command=command, jobs=1, accept_changes=None))
        assert ei.value.code == 2 and any(isinstance(e, ChangesEvent) for e in sink.events), command
    (tmp_path / "m").mkdir()
    mws, _lib = mx._ws(tmp_path / "m", [{"fp": "A", "dest": "Trip", "final_name": "a.jpg"}])
    utils.write_workspace_record(str(mws))
    (mws / "1-strays" / "notes.txt").write_text("x")                           # past merge's own preflight
    for command in ("plan", "dry-run", "execute"):
        sink = CaptureSink()
        with use_reporter(Reporter([sink])):
            assert merge._run_locked_workflow(command, str(mws)) == 2
        assert any(isinstance(e, ChangesEvent) for e in sink.events), command


@pytest.mark.no_hand_built_record
@pytest.mark.spec("RUL-workspace_checked_first", "BLD-workspace_check",
                  test="TST-workspace_check-merge_checks_the_workspace_before_its_preflight_validates")
def test_merge_checks_the_workspace_before_its_preflight_validates(tmp_path):
    """Merge, like geotag, compares the workspace before its preflight validates anything past the workspace's shape:
    with a change by hand to stop on and a library its preflight would refuse, each command stops on the change, and
    the library is never judged."""
    import test_merge_execute as mx
    ws, lib = mx._ws(tmp_path, [{"fp": "A", "dest": "Trip", "final_name": "a.jpg"}])
    utils.write_workspace_record(str(ws))
    (ws / "1-strays" / "notes.txt").write_text("x")                            # a change to stop on
    os.remove(utils.library_marker_path(str(lib)))                              # the preflight would refuse it
    for command in ("plan", "dry-run", "execute"):
        sink = CaptureSink()
        with use_reporter(Reporter([sink])):
            assert merge._run_locked_workflow(command, str(ws)) == 2
        said = "\n".join(e.msg for e in sink.logs())
        assert any(isinstance(e, ChangesEvent) for e in sink.events), (command, said)
        assert "blessed library" not in said, (command, said)


# --- accepting once, by the code -----------------------------------------

@pytest.mark.spec("RUL-stop_gives_acceptance_code", "RUL-code_accepts_only_its_list", "BLD-accept_changes",
                  test="TST-workspace_check-the_code_accepts_only_the_list_it_was_printed_for")
def test_the_code_accepts_only_the_list_it_was_printed_for(tmp_path, monkeypatch):
    """The stop prints the list and the command to run again with its code — a hash of the list as printed. One more
    change since, the old code no longer matches: the command stops again, listing them anew under a new code, which
    then accepts them."""
    ws, q = _with_quarantine(monkeypatch, tmp_path)
    _change(ws, q, "changed")
    rc, said, stop = _prep(monkeypatch, ws, "plan")
    assert rc == 2
    assert stop.code == utils.change_code(stop.lines) and "\n".join(stop.lines) in said
    assert f"photos-cartographer prep plan --accept-changes {stop.code}" in said
    _change(ws, q, "stray_appeared")                                             # one more file since
    rc, said, again = _prep(monkeypatch, ws, "plan", stop.code)
    assert rc == 2 and again.code != stop.code and "accepts another list" in said, said
    assert not os.path.exists(utils.accepted_changes_path(str(ws)))
    rc, said, _ = _prep(monkeypatch, ws, "plan", again.code)
    assert rc == 0, said


@pytest.mark.spec("RUL-acceptance_recorded", "RUL-accepted_change_not_stopped_again", "RUL-accepted_changes_logged",
                  "BLD-accept_changes", "BLD-workspace_changes_logged",
                  test="TST-workspace_check-accepted_changes_are_recorded_and_stop_no_later_run")
def test_accepted_changes_are_recorded_and_stop_no_later_run(tmp_path, monkeypatch):
    """Changes accepted once are recorded with their code, and stop no later command; a second acceptance keeps the
    first record under -001; the execution names every accepted change in prep's log, with its code; the record of
    acceptances goes into the archive with the rest of the control records."""
    ws, q = _with_quarantine(monkeypatch, tmp_path)
    first = os.path.relpath(_change(ws, q, "stray_appeared"), ws)
    _rc, _said, stop = _prep(monkeypatch, ws, "plan")
    rc, said, _ = _prep(monkeypatch, ws, "plan", stop.code)
    assert rc == 0, said
    acc = json.load(open(utils.accepted_changes_path(str(ws))))["acceptances"]
    assert [(a["code"], a["command"], [c["path"] for c in a["changes"]]) for a in acc] == [(stop.code, "plan", [first])]
    rc, said, stop2 = _prep(monkeypatch, ws, "dry-run")
    assert rc == 0 and stop2 is None and "accepted earlier" in said, said
    second = os.path.relpath(_change(ws, q, "quarantine_changed"), ws)
    rc, said, stop3 = _prep(monkeypatch, ws, "execute")
    assert rc == 2 and second in said and first not in "\n".join(stop3.lines), said
    rc, said, _ = _prep(monkeypatch, ws, "execute", stop3.code)
    assert rc == 0, said
    ctl = ws / ".photos-ingest"
    assert len(json.load(open(utils.accepted_changes_path(str(ws))))["acceptances"]) == 2
    assert len(json.load(open(ctl / "photos-01-accepted-changes-001.json"))["acceptances"]) == 1
    logged = {c["path"]: c.get("accepted") for c in _log(ws)["workspace_changes"]}
    assert logged == {first: stop.code, second: stop3.code}
    assert ".photos-ingest/photos-01-accepted-changes.json" in utils.control_archive_members(str(ws))


@pytest.mark.spec("RUL-restored_file_is_new", "RUL-unexpected_change_stops", "RUL-stop_gives_acceptance_code",
                  test="TST-workspace_check-a_file_restored_from_the_quarantine_is_new_once_accepted")
def test_a_file_restored_from_the_quarantine_is_new_once_accepted(tmp_path, monkeypatch):
    """A duplicate the user moves from the quarantine back into the inbox is a change in the quarantine: the plan stops,
    naming it. Accepted by its code, the file is a new file of the dump — still a copy, so set aside again."""
    ws, q = _with_quarantine(monkeypatch, tmp_path)
    back = ws / "0-sources" / os.path.basename(q)
    os.rename(q, back)
    rc, said, stop = _prep(monkeypatch, ws, "plan")
    assert rc == 2 and os.path.relpath(q, ws) in "\n".join(stop.lines), said
    rc, said, _ = _prep(monkeypatch, ws, "plan", stop.code)
    assert rc == 0, said
    rc, said, _ = _prep(monkeypatch, ws, "execute")
    assert rc == 0, said
    assert not back.exists()                                                     # the inbox is empty again ...
    again = [p for p in glob.glob(str(ws / ".photos-ingest-quarantine" / "**" / "*"), recursive=True)
             if os.path.isfile(p) and not p.endswith("manifest.json") and open(p, "rb").read() == b"AAAA"]
    assert len(again) == 1 and again[0] != q, again                              # ... the copy set aside anew
    rc, said, _ = _prep(monkeypatch, ws, "plan")
    assert rc == 0 and "accepted earlier" not in said, said                     # part of the record now


# --- the record each execution leaves ------------------------------------

@pytest.mark.spec("RUL-execution_records_state", "RUL-planning_leaves_record", "BLD-workspace_record",
                  test="TST-workspace_check-an_execution_records_the_state_it_leaves")
def test_an_execution_records_the_state_it_leaves(tmp_path, monkeypatch):
    """Prep's execution records the state it leaves — and so does one that failed partway, so the next run does not
    take its own moves for changes by hand; a plan leaves the record as it was."""
    ws = _fresh(monkeypatch, tmp_path)
    rid, record = utils.read_workspace_record(str(ws))
    assert utils.compare_workspace(record, utils.workspace_entries(str(ws))) == []
    assert {r.split("/")[0] for r in record} == {BY_DATE}
    (ws / "0-sources" / "d.jpg").write_bytes(b"DDDD")
    (ws / "0-sources" / "e.jpg").write_bytes(b"EEEE")
    rc, said, _ = _prep(monkeypatch, ws, "plan")
    assert rc == 0 and utils.read_workspace_record(str(ws))[0] == rid              # planning does not change it
    real_move, moves = prep._move_no_clobber, []

    def second_move_fails(src, dst):
        moves.append(src)
        if len(moves) == 2:
            raise OSError("the second move fails")
        return real_move(src, dst)
    monkeypatch.setattr(prep, "_move_no_clobber", second_move_fails)
    rc, said, _ = _prep(monkeypatch, ws, "execute")
    assert rc == 3 and len(moves) == 2, said
    rid2, record = utils.read_workspace_record(str(ws))
    assert rid2 != rid and utils.compare_workspace(record, utils.workspace_entries(str(ws))) == []
    monkeypatch.setattr(prep, "_move_no_clobber", real_move)
    rc, said, stop = _prep(monkeypatch, ws, "plan")
    assert rc == 0 and stop is None, said


@pytest.mark.spec("RUL-execution_records_state", "BLD-workspace_record",
                  test="TST-workspace_check-geotags_own_writes_never_trip_the_check")
def test_geotags_own_writes_never_trip_the_check(tmp_path, monkeypatch):
    """Geotag writes a photo through a temporary file renamed over it — a new inode, size and time — and renames it:
    its execution records the state it leaves, so the next command finds nothing changed, and each photo keeps its
    fingerprint in the record under its new name."""
    import test_geotag_execution as gx
    ws, ctl = gx._ready_ws(tmp_path, monkeypatch)
    gx._mock_tools(monkeypatch, ws)
    real_write = cal.GeotagWorkflow._exiftool_write

    def rewrite(self, p, tags):                       # as exiftool -o and the rename over the photo do
        tmp = p + "_exiftool_tmp"
        with open(p, "rb") as src, open(tmp, "wb") as dst:
            dst.write(src.read() + b" tagged")
        os.replace(tmp, p)
        return real_write(self, p, tags)
    monkeypatch.setattr(cal.GeotagWorkflow, "_exiftool_write", rewrite)
    handoff = json.load(open(ctl / "photos-11-handoff.json"))
    utils.write_workspace_record(str(ws), cache_rows={f["relative_path"]: f for f in handoff["files"]})   # as prep's
    before = dict(utils.read_workspace_record(str(ws))[1])
    assert all(r["fingerprint"] for p, r in before.items() if p.startswith(BY_DEST))
    assert gx._execute(monkeypatch, ws) == 0
    _rid, record = utils.read_workspace_record(str(ws))
    assert utils.compare_workspace(record, utils.workspace_entries(str(ws))) == []
    renamed = sorted(p for p in record if p.startswith(BY_DEST))
    assert renamed and renamed != sorted(p for p in before if p.startswith(BY_DEST))
    assert {record[p]["fingerprint"] for p in renamed} == {before[p]["fingerprint"] for p in before
                                                           if p.startswith(BY_DEST)}
    sink = CaptureSink()
    with use_reporter(Reporter([sink])):
        assert utils.check_workspace(str(ws), "geotag", "finalize") == ([], None)


@pytest.mark.spec("RUL-execution_records_state", "BLD-workspace_record",
                  test="TST-workspace_check-merges_own_moves_never_trip_the_check")
def test_merges_own_moves_never_trip_the_check(tmp_path, monkeypatch):
    """Merge moves photos out of the workspace, one left behind blocked: its execution records the state it leaves, so
    the next merge finds nothing changed."""
    import test_merge_execute as mx

    def fake(self, abs_path):
        v = mx._parse_fp(abs_path)
        if v and v != "FAIL":
            return {"status": "valid", "value": v, "strategy": "image-content-hash-v2", "engine_version": "test"}
        return {"status": "failed", "value": None, "error": "unreadable", "engine_version": "test"}
    monkeypatch.setattr(merge.MergeWorkflow, "_fingerprint_library_file", fake)
    ws, _lib = mx._ws(tmp_path, [{"fp": "A", "dest": "Trip", "final_name": "a.jpg"},
                                 {"fp": "B", "dest": "Trip", "final_name": "b.jpg"}],
                      library_files=[{"fp": "FAIL", "dest": "Trip", "name": "a.jpg"}])
    merge._run_locked_workflow("plan", str(ws))
    assert merge._run_locked_workflow("execute", str(ws)) == 3
    assert not (ws / BY_DEST / "Trip" / "b.jpg").exists() and (ws / BY_DEST / "Trip" / "a.jpg").exists()
    _rid, record = utils.read_workspace_record(str(ws))
    assert sorted(record) == [f"{BY_DEST}/Trip/a.jpg"]
    sink = CaptureSink()
    with use_reporter(Reporter([sink])):
        assert utils.check_workspace(str(ws), "merge", "plan") == ([], None)


@pytest.mark.no_hand_built_record
@pytest.mark.spec("RUL-record_needed", "BLD-workspace_check", "BLD-exit_statuses",
                  test="TST-workspace_check-geotag_and_merge_refuse_a_workspace_with_no_record")
def test_geotag_and_merge_refuse_a_workspace_with_no_record(tmp_path, monkeypatch):
    """A workspace whose state no execution recorded: geotag and merge refuse it, a refusal, pointing to prep."""
    import test_merge_execute as mx
    ws, _lib = mx._ws(tmp_path, [{"fp": "A", "dest": "Trip", "final_name": "a.jpg"}])
    monkeypatch.chdir(ws)
    for command in ("plan", "execute", "finalize"):
        sink = CaptureSink()
        with use_reporter(Reporter([sink])), pytest.raises(SystemExit) as ei:
            cal.run(types.SimpleNamespace(command=command, jobs=1, accept_changes=None))
        said = "\n".join(e.msg for e in sink.logs())
        assert ei.value.code == 2 and "no record" in said and "prep execute" in said, said
    for command in ("plan", "dry-run", "execute"):
        sink = CaptureSink()
        with use_reporter(Reporter([sink])):
            assert merge._run_locked_workflow(command, str(ws)) == 2
        assert "no record" in "\n".join(e.msg for e in sink.logs())


@pytest.mark.no_hand_built_record
@pytest.mark.spec("RUL-first_prep_compares_nothing", "BLD-workspace_check",
                  test="TST-workspace_check-prep_with_no_record_compares_nothing")
def test_prep_with_no_record_compares_nothing(tmp_path, monkeypatch):
    """Prep's first run — no record yet — compares nothing, whatever the folders hold; its execution writes the
    first record."""
    _install(monkeypatch)
    ws = _ws(tmp_path)
    (ws / BY_DATE / "2023-01-02").mkdir()
    (ws / BY_DATE / "2023-01-02" / "2023-01-02--03-04-05.jpg").write_bytes(b"AAAA")
    (ws / "0-sources" / "b.jpg").write_bytes(b"BBBB")
    assert utils.read_workspace_record(str(ws))[0] is None
    _ingest(monkeypatch, ws)
    assert utils.read_workspace_record(str(ws))[0] is not None


@pytest.mark.no_hand_built_record
@pytest.mark.parametrize("damage", ["table", "file"])
@pytest.mark.spec("RUL-workspace_checked_first", "RUL-first_prep_compares_nothing",
                  test="TST-workspace_check-a_record_that_cannot_be_read_stops_the_check")
def test_a_record_that_cannot_be_read_stops_the_check(tmp_path, monkeypatch, damage):
    """A record of the last execution's state that is there and cannot be read is not the absence of one: prep's
    check stops, 2, naming the database, instead of comparing nothing as on a first run."""
    import sqlite3
    ws = _fresh(monkeypatch, tmp_path)
    db = utils.db_path(str(ws))
    if damage == "table":
        conn = sqlite3.connect(db)
        conn.execute("DROP TABLE workspace_record")              # its id kept, its rows gone
        conn.commit()
        conn.close()
    else:
        with open(db, "r+b") as f:
            f.write(b"not a database" * 8)                        # the header written over
    rc, said, _ = _prep(monkeypatch, ws, "plan")
    assert rc == 2, said
    assert os.path.join(".photos-ingest", "photos-00-ingest.db") in said and "cannot be read" in said


@pytest.mark.no_hand_built_record
@pytest.mark.spec("RUL-workspace_checked_first", "RUL-first_prep_compares_nothing", "BLD-workspace_check",
                  test="TST-workspace_check-prep_after_a_failed_first_execute_compares")
def test_prep_after_a_failed_first_execute_compares(tmp_path, monkeypatch):
    """A first execute that fails part way leaves the workspace uninitialized, but records the state it leaves: the
    next prep compares the workspace with that record, and a photo it filed, edited since, stops it."""
    _install(monkeypatch)
    ws = tmp_path / "ws"
    (ws / "dump").mkdir(parents=True)
    (ws / "dump" / "a.jpg").write_bytes(b"AAAA")
    (ws / "dump" / "b.jpg").write_bytes(b"BBBB")
    moved = prep._move_no_clobber

    def failing(src, dst):
        if src.endswith(os.path.join("0-sources", "dump", "b.jpg")):
            raise OSError("disk gone")
        return moved(src, dst)
    monkeypatch.setattr(prep, "_move_no_clobber", failing)
    assert _prep(monkeypatch, ws, "plan")[0] == 0
    assert _prep(monkeypatch, ws, "execute")[0] == 3
    monkeypatch.setattr(prep, "_move_no_clobber", moved)
    assert not os.path.exists(utils.guard_path(str(ws)))           # not initialized, its state recorded
    assert utils.read_workspace_record(str(ws))[0] is not None
    (filed,) = _by_date(ws)
    with open(filed, "ab") as f:
        f.write(b"edited")
    rc, said, stop = _prep(monkeypatch, ws, "plan")
    assert rc == 2 and stop is not None, said


@pytest.mark.parametrize("command", ["plan", "execute"])
@pytest.mark.spec("RUL-config_seeded_once", "RUL-config_authoritative", "RUL-planning_writes_only_its_records",
                  test="TST-workspace_check-a_configuration_deleted_after_the_first_run_stops_prep")
def test_a_configuration_deleted_after_the_first_run_stops_prep(tmp_path, monkeypatch, command):
    """The configuration deleted from a workspace prep has run in is not seeded again: plan and execute each stop,
    naming it, and write none."""
    _install(monkeypatch)
    ws = _ws(tmp_path)
    (ws / "0-sources" / "a.jpg").write_bytes(b"AAAA")
    _ingest(monkeypatch, ws)
    (ws / "0-sources" / "b.jpg").write_bytes(b"BBBB")
    if command == "execute":
        assert _prep(monkeypatch, ws, "plan")[0] == 0
    cfg = utils.config_path(str(ws))
    os.remove(cfg)
    rc, said, _ = _prep(monkeypatch, ws, command)
    assert rc == 2 and "photos-00-config.json" in said, said
    assert not os.path.exists(cfg)
    if command == "execute":                       # the execution itself reads it, never seeds it
        with open(utils.prep_plan_path(str(ws))) as f:
            plan = prep.Plan.from_dict(json.load(f))
        with pytest.raises(prep.ExecuteRefused, match="photos-00-config.json"):
            prep.PlanExecutor(str(ws)).execute(plan)
        assert not os.path.exists(cfg)
    assert (ws / "0-sources" / "b.jpg").exists()


@pytest.mark.spec("RUL-maintenance_unchecked", "RUL-prune_removals_no_difference", "BLD-workspace_record",
                  test="TST-workspace_check-maintenance_commands_do_not_check")
def test_maintenance_commands_do_not_check(tmp_path, monkeypatch):
    """Pruning the quarantine, setting up the library and the editor run whatever the files show; what a prune
    removes from the quarantine is no change to the next run."""
    from cartographer.editor import server as editor
    ws, q = _with_quarantine(monkeypatch, tmp_path)
    put = _change(ws, q, "appeared")                                 # a change that would stop a checking command

    def no_check(*a, **kw):
        raise AssertionError("checked")
    for mod in (utils, prep, cal, merge):
        monkeypatch.setattr(mod, "check_workspace", no_check)
    rc, said, _ = _prep(monkeypatch, ws, "prune-quarantine")
    assert rc == 0, said
    lib = tmp_path / "lib"
    lib.mkdir()
    sink = CaptureSink()
    with use_reporter(Reporter([sink])):
        assert merge.do_init_library(str(lib), str(ws)) == 0
    assert isinstance(editor._load_artifacts(str(ws)), dict)
    monkeypatch.undo()
    _install(monkeypatch)
    os.remove(put)
    monkeypatch.chdir(ws)
    sink = CaptureSink()
    with use_reporter(Reporter([sink])):
        prep.prune_quarantine(str(ws), do_delete=True, prune_all=True)
    assert not os.path.exists(q)
    rc, said, stop = _prep(monkeypatch, ws, "plan")
    assert rc == 0 and stop is None, said


@pytest.mark.spec("RUL-prune_removals_no_difference", "BLD-workspace_record",
                  test="TST-workspace_check-a_prune_cut_short_is_no_change")
def test_a_prune_cut_short_is_no_change(tmp_path, monkeypatch):
    """A prune whose removal of a run folder stops midway — the duplicate gone, its manifest left — takes what it
    removed out of the record all the same: the next plan goes on."""
    ws, q = _with_quarantine(monkeypatch, tmp_path)

    def cut_short(path, *a, **kw):
        os.remove(q)
        raise OSError("the disk said no")
    monkeypatch.setattr(shutil, "rmtree", cut_short)
    monkeypatch.chdir(ws)
    with use_reporter(Reporter([CaptureSink()])):
        with pytest.raises(OSError):
            prep.prune_quarantine(str(ws), do_delete=True, prune_all=True)
    monkeypatch.undo()
    _install(monkeypatch)
    assert not os.path.exists(q) and glob.glob(str(ws / ".photos-ingest-quarantine" / "*" / "manifest.json"))
    rc, said, stop = _prep(monkeypatch, ws, "plan")
    assert rc == 0 and stop is None, said


@pytest.mark.no_hand_built_record
@pytest.mark.spec("BLD-hand_change_is_work", "RUL-prepped_nothing_to_do",
                  test="TST-workspace_check-a_workspace_with_no_record_is_work_for_prep")
def test_a_workspace_with_no_record_is_work_for_prep(tmp_path):
    """A prepped workspace whose state no execution recorded — one begun under an earlier version — is not "nothing
    to do": prep's execute runs, and writes the first record."""
    ws = _ws(tmp_path)
    ctl = ws / ".photos-ingest"
    (ctl / "photos-15-prep-log.json").write_text('{"photos": {}}')
    (ctl / "photos-11-handoff.json").write_text(json.dumps(
        {"files": [], "depends_on": {"prep_log": {"sha256": utils.sha256_file(str(ctl / "photos-15-prep-log.json"))}}}))
    rep = Reporter([CaptureSink()])
    assert not prep._prep_nothing_to_do(str(ws), rep)
    utils.write_workspace_record(str(ws))
    assert prep._prep_nothing_to_do(str(ws), rep)


# --- an execution interrupted before it recorded its state ---------------

class _Killed(BaseException):
    """The process killed outright: nothing after it runs, so the record an execution's end writes — in its `finally` —
    is left out by hand around it."""


def _killed(*a, **k):
    raise _Killed()


def _kill_prep_at_its_last_move(monkeypatch, ws):
    """Prep's execution killed just after its last move — before that move is journaled, the handoff written or the
    state recorded. Returns the places it moved files to."""
    plan = json.load(open(utils.prep_plan_path(str(ws))))
    n = sum(o["type"] in ("move_no_clobber", "rename_no_clobber", "quarantine_move") for o in plan["operations"])
    real_move, real_record, moves = prep._move_no_clobber, prep.write_workspace_record, []

    def move(src, dst):
        real_move(src, dst)
        moves.append(dst)
        if len(moves) == n:
            raise _Killed()
    monkeypatch.setattr(prep, "_move_no_clobber", move)
    monkeypatch.setattr(prep, "write_workspace_record", lambda *a, **k: None)
    with pytest.raises(_Killed):
        _prep(monkeypatch, ws, "execute")
    monkeypatch.setattr(prep, "_move_no_clobber", real_move)
    monkeypatch.setattr(prep, "write_workspace_record", real_record)
    return [os.path.relpath(m, ws) for m in moves]


def _killed_prep(monkeypatch, tmp_path):
    """A recorded workspace, a new dump planned — a new photo and a duplicate of one prepped — and its execution killed
    after its last move: (workspace, the record's id, the places the run moved files to)."""
    ws = _fresh(monkeypatch, tmp_path)
    (ws / "0-sources" / "d.jpg").write_bytes(b"DDDD")
    (ws / "0-sources" / "again.jpg").write_bytes(b"AAAA")
    rc, said, _ = _prep(monkeypatch, ws, "plan")
    assert rc == 0, said
    rid = utils.read_workspace_record(str(ws))[0]
    moved = _kill_prep_at_its_last_move(monkeypatch, ws)
    assert utils.read_workspace_record(str(ws))[0] == rid                       # nothing recorded
    assert [b["phase"] for b in utils.executions_begun(str(ws), rid)] == ["prep"]
    return ws, rid, moved


@pytest.mark.spec("RUL-interrupted_work_passes", "RUL-allowed_changes_named", "BLD-interrupted_run_recognised",
                  "BLD-workspace_changes_logged", test="TST-workspace_check-a_hard_killed_prep_execution_is_recognised")
def test_a_hard_killed_prep_execution_is_recognised(tmp_path, monkeypatch):
    """Prep's execution killed outright after its moves — a photo filed from the inbox into photos by date, a duplicate
    set aside into the quarantine with its manifest, the last move not even journaled — records nothing. The next plan
    finds each where the killed run's plan put it, with the entry it had: its own work, passing unasked and named; the
    execution after it names it in prep's log and records the state, the note of the killed run cleared with it."""
    ws, rid, moved = _killed_prep(monkeypatch, tmp_path)
    assert any(m.startswith(BY_DATE) for m in moved) and any(m.startswith(".photos-ingest-quarantine") for m in moved)
    rc, said, stop = _prep(monkeypatch, ws, "plan")
    assert rc == 0 and stop is None and "--accept-changes" not in said, said
    assert "interrupted" in said and all(m in said for m in moved), said
    rc, said, _ = _prep(monkeypatch, ws, "execute")
    assert rc == 0, said
    own = [c for c in _log(ws)["workspace_changes"] if c["kind"] == "interrupted_run"]
    assert {c["phase"] for c in own} == {"prep"}
    paths = {c["path"] for c in own}
    assert set(moved) <= paths and any(p.endswith("/manifest.json") for p in paths - set(moved)), own
    rid2, _ = utils.read_workspace_record(str(ws))
    assert rid2 != rid and utils.executions_begun(str(ws), rid2) == []
    rc, said, _ = _prep(monkeypatch, ws, "plan")
    assert rc == 0 and "interrupted" not in said, said


def _killed_geotag(tmp_path, monkeypatch):
    """A geotag execution killed once every photo is written, renamed and journaled, before its summary and the record:
    (workspace, control directory, the record before it)."""
    import test_geotag_execution as gx
    ws, ctl = gx._ready_ws(tmp_path, monkeypatch)
    gx._mock_tools(monkeypatch, ws)
    real_write = cal.GeotagWorkflow._exiftool_write

    def rewrite(self, p, tags):                       # as exiftool -o and the rename over the photo do
        tmp = p + "_exiftool_tmp"
        with open(p, "rb") as src, open(tmp, "wb") as dst:
            dst.write(src.read() + b" tagged")
        os.replace(tmp, p)
        return real_write(self, p, tags)
    monkeypatch.setattr(cal.GeotagWorkflow, "_exiftool_write", rewrite)
    handoff = json.load(open(ctl / "photos-11-handoff.json"))
    utils.write_workspace_record(str(ws), cache_rows={f["relative_path"]: f for f in handoff["files"]})   # as prep's
    rid, before = utils.read_workspace_record(str(ws))
    real_summary, real_record = cal.GeotagWorkflow._build_summary, cal.write_workspace_record
    monkeypatch.setattr(cal.GeotagWorkflow, "_build_summary", _killed)
    monkeypatch.setattr(cal, "write_workspace_record", lambda *a, **k: None)
    with pytest.raises(_Killed):
        gx._execute(monkeypatch, ws)
    monkeypatch.setattr(cal.GeotagWorkflow, "_build_summary", real_summary)
    monkeypatch.setattr(cal, "write_workspace_record", real_record)
    assert utils.read_workspace_record(str(ws))[0] == rid
    return ws, ctl, before


def _check(ws, phase, command):
    sink = CaptureSink()
    with use_reporter(Reporter([sink])):
        out = utils.check_workspace(str(ws), phase, command)
    return out, "\n".join(e.msg for e in sink.logs())


@pytest.mark.spec("RUL-interrupted_work_passes", "RUL-allowed_changes_named", "BLD-interrupted_run_recognised",
                  "BLD-workspace_changes_logged", test="TST-workspace_check-a_hard_killed_geotag_execution_is_recognised")
def test_a_hard_killed_geotag_execution_is_recognised(tmp_path, monkeypatch):
    """Geotag's execution killed outright once its photos are written — each a new inode, size and time — and renamed:
    nothing recorded, the photos are where and as its journal notes it left them, so the next command passes them
    unasked as the killed run's work; the execution that resumes the plan names them in its summary and records them,
    each keeping its fingerprint under its new name."""
    import test_geotag_execution as gx
    ws, ctl, before = _killed_geotag(tmp_path, monkeypatch)
    renamed = sorted(p for p in utils.workspace_entries(str(ws)) if p.startswith(BY_DEST))
    assert renamed and not set(renamed) & set(before)
    (changes, stop), said = _check(ws, "geotag", "finalize")
    assert stop is None and "interrupted" in said, said
    assert sorted(c["path"] for c in changes) == renamed
    assert {(c["kind"], c["phase"]) for c in changes} == {("interrupted_run", "geotag")}
    assert {c["from"] for c in changes} == {p for p in before if p.startswith(BY_DEST)}
    assert gx._execute(monkeypatch, ws) == 0
    summary = json.load(open(ctl / "photos-25-execution-summary.json"))
    assert sorted(c["path"] for c in summary["workspace_changes"] if c["kind"] == "interrupted_run") == renamed
    _rid, record = utils.read_workspace_record(str(ws))
    assert {record[p]["fingerprint"] for p in renamed} == {before[p]["fingerprint"] for p in before
                                                           if p.startswith(BY_DEST)}
    assert _check(ws, "geotag", "finalize")[0] == ([], None)


@pytest.mark.spec("RUL-interrupted_work_passes", "BLD-interrupted_run_recognised",
                  test="TST-workspace_check-a_hard_killed_merge_execution_is_recognised")
def test_a_hard_killed_merge_execution_is_recognised(tmp_path, monkeypatch):
    """Merge's execution killed outright after moving its photos into the library, before the record: the photos gone
    from photos by destination are its journaled moves, named as the killed run's work — not as photos culled."""
    import test_merge_execute as mx

    def fake(self, abs_path):
        v = mx._parse_fp(abs_path)
        return {"status": "valid", "value": v, "strategy": "image-content-hash-v2", "engine_version": "test"}
    monkeypatch.setattr(merge.MergeWorkflow, "_fingerprint_library_file", fake)
    ws, _lib = mx._ws(tmp_path, [{"fp": "A", "dest": "Trip", "final_name": "a.jpg"},
                                 {"fp": "B", "dest": "Trip", "final_name": "b.jpg"}])
    assert merge._run_locked_workflow("plan", str(ws)) == 0
    rid = utils.read_workspace_record(str(ws))[0]
    monkeypatch.setattr(merge.MergeWorkflow, "_build_summary", _killed)
    monkeypatch.setattr(merge, "write_workspace_record", lambda *a, **k: None)
    with pytest.raises(_Killed):
        merge._run_locked_workflow("execute", str(ws))
    assert utils.read_workspace_record(str(ws))[0] == rid
    assert not any(p.startswith(BY_DEST) for p in utils.workspace_entries(str(ws)))
    (changes, stop), said = _check(ws, "merge", "plan")
    assert stop is None and "deleted" not in said, said
    assert [(c["kind"], c["path"]) for c in changes] == [("interrupted_run", f"{BY_DEST}/Trip/a.jpg"),
                                                         ("interrupted_run", f"{BY_DEST}/Trip/b.jpg")]


@pytest.mark.spec("RUL-interrupted_work_exact", "RUL-unexpected_change_stops", "BLD-interrupted_run_recognised",
                  test="TST-workspace_check-a_file_still_in_the_inbox_is_no_work_of_the_killed_run")
def test_a_file_still_in_the_inbox_is_no_work_of_the_killed_run(tmp_path, monkeypatch):
    """After a hard kill, a photo the killed run filed from the inbox that is in the inbox again — copied back with its
    size and time kept — is not gone from where it was: the file at the plan's place is no work of that run, and the
    command stops naming it."""
    ws, _rid, moved = _killed_prep(monkeypatch, tmp_path)
    filed = next(m for m in moved if m.startswith(BY_DATE) and (ws / m).read_bytes() == b"DDDD")
    shutil.copy2(ws / filed, ws / "0-sources" / "d.jpg")          # back where it was, as `cp -p` leaves it
    rc, said, stop = _prep(monkeypatch, ws, "plan")
    assert rc == 2 and stop is not None, said
    assert filed in "\n".join(stop.lines), stop.lines


@pytest.mark.spec("RUL-interrupted_work_exact", "RUL-unexpected_change_stops", "BLD-interrupted_run_recognised",
                  test="TST-workspace_check-a_change_the_killed_run_did_not_leave_still_stops")
def test_a_change_the_killed_run_did_not_leave_still_stops(tmp_path, monkeypatch):
    """After a hard kill, a file not as the killed run's records say it left it — prep's photo with another
    modification time than the plan found it with, geotag's with another size than its journal notes — is no work of
    that run: the command stops, naming that file and only it, the rest of the run's work passing as its own."""
    ws, _rid, moved = _killed_prep(monkeypatch, tmp_path)
    touched = next(m for m in moved if m.startswith(BY_DATE))
    st = os.stat(ws / touched)
    os.utime(ws / touched, ns=(st.st_atime_ns, st.st_mtime_ns + 1_000_000_000))
    rc, said, stop = _prep(monkeypatch, ws, "plan")
    assert rc == 2 and stop is not None, said
    listed = "\n".join(stop.lines)
    assert touched in listed and not any(m in listed for m in moved if m != touched), listed

    (tmp_path / "g").mkdir()
    gws, _ctl, _before = _killed_geotag(tmp_path / "g", monkeypatch)
    edited = sorted(p for p in utils.workspace_entries(str(gws)) if p.startswith(BY_DEST))
    with open(gws / edited[0], "ab") as f:
        f.write(b" edited since")
    (changes, stop), said = _check(gws, "geotag", "finalize")
    stopped_on = said.split("--accept-changes")[0]
    assert changes is None and stop == 2 and edited[0] in stopped_on and edited[1] not in stopped_on, said


_CULL = {"kind": "deleted", "path": f"{BY_DATE}/2023-01-02/culled.jpg", "content_fingerprint": "sig-culled"}


@pytest.mark.spec("BLD-workspace_changes_logged", "RUL-allowed_changes_named", "RUL-geotag_summary_only_for_execution",
                  test="TST-workspace_check-a_geotag_execution_cut_short_names_its_changes_in_its_journal")
def test_a_geotag_execution_cut_short_names_its_changes_in_its_journal(tmp_path, monkeypatch):
    """A geotag execution interrupted after its check passed a cull writes no summary; the cull is named in its plan's
    journal, written as it records the state it leaves — where prep's reading of the culls finds it — and kept there
    by the execution that resumes the plan."""
    import test_geotag_execution as gx
    ws, ctl = gx._ready_ws(tmp_path, monkeypatch)
    gx._mock_tools(monkeypatch, ws)
    monkeypatch.setattr(cal, "check_workspace", lambda *a, **k: ([dict(_CULL)], None))

    def ctrl_c(*a, **k):
        raise KeyboardInterrupt
    real_wave = cal.GeotagWorkflow._apply_wave
    monkeypatch.setattr(cal.GeotagWorkflow, "_apply_wave", ctrl_c)
    assert gx._execute(monkeypatch, ws) == 130
    assert not (ctl / "photos-25-execution-summary.json").exists()
    plan_id = json.load(open(ctl / "photos-24-executable-plan.json"))["plan_id"]
    journal = json.load(open(utils.journal_path(str(ws), plan_id)))
    assert journal["workspace_changes"] == [_CULL]
    assert prep.hand_deletions(str(ws)) == {"sig-culled": _CULL["path"]}
    monkeypatch.setattr(cal.GeotagWorkflow, "_apply_wave", real_wave)
    monkeypatch.setattr(cal, "check_workspace", lambda *a, **k: ([], None))
    assert gx._execute(monkeypatch, ws) == 0
    assert json.load(open(utils.journal_path(str(ws), plan_id)))["workspace_changes"] == [_CULL]


@pytest.mark.spec("BLD-workspace_changes_logged", "RUL-allowed_changes_named", "RUL-merge_summary_only_for_execution",
                  test="TST-workspace_check-a_merge_execution_cut_short_names_its_changes_in_its_journal")
def test_a_merge_execution_cut_short_names_its_changes_in_its_journal(tmp_path, monkeypatch):
    """A merge execution interrupted after its check passed a change writes no summary; the change is named in its
    plan's journal, written as it records the state it leaves, and kept there by the execution that resumes it."""
    import test_merge_execute as mx
    monkeypatch.setattr(merge.MergeWorkflow, "_fingerprint_library_file", lambda self, p: {
        "status": "valid", "value": mx._parse_fp(p), "strategy": "image-content-hash-v2", "engine_version": "test"})
    ws, _lib = mx._ws(tmp_path, [{"fp": "A", "dest": "Trip", "final_name": "a.jpg"},
                                 {"fp": "B", "dest": "Trip", "final_name": "b.jpg"}])
    assert merge._run_locked_workflow("plan", str(ws)) == 0
    plan_id = json.load(open(merge.merge_plan_path(str(ws))))["plan_id"]
    monkeypatch.setattr(merge, "check_workspace", lambda *a, **k: ([dict(_CULL)], None))
    real_move = merge.MergeWorkflow._move_file

    def ctrl_c_at_b(self, ws_, library_root, rec):
        if rec["by_dest_source"].endswith("b.jpg"):
            raise KeyboardInterrupt
        return real_move(self, ws_, library_root, rec)
    monkeypatch.setattr(merge.MergeWorkflow, "_move_file", ctrl_c_at_b)
    assert merge._run_locked_workflow("execute", str(ws), jobs=1) == 130
    assert not os.path.exists(merge.merge_summary_path(str(ws)))
    assert json.load(open(utils.journal_path(str(ws), plan_id)))["workspace_changes"] == [_CULL]
    monkeypatch.setattr(merge.MergeWorkflow, "_move_file", real_move)
    monkeypatch.setattr(merge, "check_workspace", lambda *a, **k: ([], None))
    assert merge._run_locked_workflow("execute", str(ws)) == 0
    assert json.load(open(utils.journal_path(str(ws), plan_id)))["workspace_changes"] == [_CULL]
