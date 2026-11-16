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

"""What cartographer needs of a filesystem, asked at every run's start: the workspace on a local filesystem
(RUL-workspace_local_filesystem), each requirement of RUL-filesystem_agnostic tried on scratch files in the workspace
and, for merge, in the library (RUL-filesystem_requirements_tried, RUL-library_requirements_tried); and the library's
free space where merge copies into another filesystem (RUL-library_space_checked).

The filesystem's type is faked through `photos_utils._mount_table`, a failing requirement by patching the one call the
trial makes for it, another filesystem by `photos_3_merge._device` and its free space by `photos_3_merge._free_bytes` —
no disk is filled, nothing is mounted."""
import json
import os
import types

import pytest

import photos_1_prep as prep
import photos_2_geotag as geotag
import photos_3_merge as merge
import photos_utils as utils
from test_cli import _EVERY_COMMAND, _ws as _cli_ws
from test_merge_execute import _ws as _merge_ws, _content_fingerprint, _fp_bytes, _src, _summary  # noqa: F401


def _mounted(monkeypatch, *table):
    """Make the system's mount table `table`: (mount point, type) pairs, in the order listed."""
    monkeypatch.setattr(utils, "_mount_table", lambda: [(os.path.realpath(str(p)), t) for p, t in table])


def _state(root, but=()):
    return sorted((str(p.relative_to(root)), p.read_bytes() if p.is_file() else None, p.stat().st_mtime_ns)
                  for p in root.rglob("*") if p.name not in but)


# --- the workspace's filesystem type -----------------------------------------------------------------------------

@pytest.mark.spec("BLD-local_filesystem_types", test="TST-filesystem_checks-type_from_the_mount_table")
def test_the_type_is_the_longest_mount_point_holding_the_path(tmp_path, monkeypatch):
    """The mount table is read as the system writes it — escapes and all — and the workspace's type is that of the
    mount whose point is the longest prefix of its real path, the later of two at one point."""
    ws = tmp_path / "my photos" / "ws"; ws.mkdir(parents=True)
    other = tmp_path / "my photos-other"; other.mkdir()
    base = os.path.realpath(str(tmp_path)).replace(" ", "\\040")
    info = tmp_path / "mountinfo"
    info.write_text(
        "22 1 0:21 / / rw,relatime shared:1 - ext4 /dev/sda1 rw\n"
        f"30 22 0:30 / {base}/my\\040photos rw shared:2 - nfs4 server:/photos rw\n"
        f"31 30 0:31 / {base}/my\\040photos rw shared:3 - xfs /dev/sdb1 rw\n"
        f"32 22 0:32 / {base}/my\\040photos-other rw - cifs //nas/x rw\n")
    monkeypatch.setattr(utils, "MOUNT_TABLES", (str(tmp_path / "absent"), str(info)))
    assert utils.filesystem_type(str(ws)) == "xfs"                   # the later of two at one point
    assert utils.filesystem_type(str(other)) == "cifs"               # not taken for a folder under "my photos"
    assert utils.filesystem_type(str(tmp_path)) == "ext4"
    mounts = tmp_path / "mounts"
    mounts.write_text(f"/dev/sda1 / ext4 rw 0 0\nserver:/x {base}/my\\040photos nfs rw 0 0\n")
    monkeypatch.setattr(utils, "MOUNT_TABLES", (str(mounts),))
    assert utils.filesystem_type(str(ws)) == "nfs"
    monkeypatch.setattr(utils, "MOUNT_TABLES", (str(tmp_path / "absent"),))
    assert utils.filesystem_type(str(ws)) is None


@pytest.mark.spec("RUL-workspace_local_filesystem", "RUL-not_local_named", test="TST-filesystem_checks-local_types")
@pytest.mark.parametrize("fstype,local", [("ext4", True), ("zfs", True), ("btrfs", True), ("tmpfs", True),
                                          ("overlay", True), ("nfs4", False), ("cifs", False),
                                          ("fuse.sshfs", False), ("vfat", False), ("exfat", False)])
def test_only_a_filesystem_known_to_be_local_holds_a_workspace(tmp_path, monkeypatch, fstype, local):
    _mounted(monkeypatch, ("/", fstype))
    err = utils.local_filesystem_error(str(tmp_path))
    if local:
        assert err is None
    else:
        assert fstype in err and "not known to be local" in err


@pytest.mark.spec("RUL-not_local_stops", test="TST-filesystem_checks-no_mount_table_refused")
def test_a_system_with_no_mount_table_is_refused(tmp_path, monkeypatch, capsys):
    """Where the filesystem's kind cannot be told — no mount table, not Linux — the workspace is not known to be
    local, and a run stops having made nothing."""
    monkeypatch.setattr(utils, "MOUNT_TABLES", (str(tmp_path / "no-mountinfo"),))
    ws = tmp_path / "ws"; ws.mkdir()
    (ws / "a.jpg").write_bytes(b"x")
    monkeypatch.chdir(ws)
    with pytest.raises(SystemExit) as ei:
        prep.run(types.SimpleNamespace(command="plan", jobs=1, delete=False, plan_id=None))
    assert ei.value.code == 2 and "no mount table" in capsys.readouterr().err
    assert sorted(os.listdir(ws)) == ["a.jpg"]


@pytest.mark.spec("RUL-local_filesystem_checked_first", "RUL-not_local_stops", "RUL-not_local_named",
                  test="TST-filesystem_checks-every_command_refuses_a_network_workspace")
@pytest.mark.parametrize("command", _EVERY_COMMAND, ids=[" ".join(c[:2]) + (" <path>" if "<library>" in c else "")
                                                         for c in _EVERY_COMMAND])
def test_every_command_refuses_a_workspace_on_a_network_filesystem(tmp_path, monkeypatch, capsys, command):
    """Every command of every phase, and the editor's save, stops on a workspace on a network filesystem, naming its
    type, before anything else — the lock included: a free lock is not taken, and nothing changes."""
    import cartographer.cli as cli
    from cartographer.editor import server as editor
    lib = tmp_path / "lib"; lib.mkdir()
    cfg = {k: v for k, v in utils.CONFIG.items() if k != "jobs"}
    cfg["zfs"] = {"enabled": False}
    cfg["merge"] = dict(cfg.get("merge") or {}); cfg["merge"]["library_root"] = str(lib)
    ws = _cli_ws(tmp_path, config=cfg)
    (ws / "0-sources" / "a.jpg").write_bytes(b"a dump to plan")
    (ws / ".photos-ingest" / "photos-21-time-decisions.json").write_text('{"destinations": {}}')
    _mounted(monkeypatch, ("/", "ext4"), (ws, "nfs4"))
    taken = []
    real_acquire = utils._FlockLock.acquire
    monkeypatch.setattr(utils._FlockLock, "acquire", lambda self: taken.append(self.lock_path) or real_acquire(self))
    before = _state(tmp_path)
    monkeypatch.chdir(str(ws))
    if command[0] == "edit":
        res = editor._save(str(ws), {"time": [{"dest": "6-photos-by-dest/T", "kind": "timezone",
                                               "user_decision": {"manual_iana_timezone": "Asia/Tokyo"}}]})
        assert res["ok"] is False and "nfs4" in res["error"], res
    else:
        with pytest.raises(SystemExit) as ei:
            cli.main([str(lib) if a == "<library>" else a for a in command])
        assert ei.value.code == 2, (command, capsys.readouterr())
        assert "nfs4" in capsys.readouterr().err
    assert taken == []                                              # asked before the lock
    assert _state(tmp_path) == before
    assert not utils.is_library(str(lib))


@pytest.mark.spec("RUL-local_filesystem_checked_first", test="TST-filesystem_checks-editor_refuses_to_open")
def test_the_editor_does_not_open_on_a_network_workspace(tmp_path, monkeypatch, capsys):
    from cartographer.editor import server as editor
    ws = _cli_ws(tmp_path)
    _mounted(monkeypatch, ("/", "nfs4"))
    monkeypatch.setattr(editor, "_bind", lambda *a, **k: pytest.fail("the editor was served"))
    with pytest.raises(SystemExit) as ei:
        editor.serve(str(ws))
    assert ei.value.code == 2 and "nfs4" in capsys.readouterr().err
    assert not (ws / ".photos-ingest" / editor.EDITOR_LOCK).exists()


# --- the workspace's requirements, tried ---------------------------------------------------------------------------

def _fail_locks(monkeypatch):
    def flock(fd, op):
        raise OSError(37, "No locks available")
    monkeypatch.setattr(utils.fcntl, "flock", flock)


def _fail_atomic_rename(monkeypatch):
    def replace(a, b):
        raise OSError(1, "Operation not permitted")
    monkeypatch.setattr(utils.os, "replace", replace)


def _fail_no_clobber(monkeypatch):
    monkeypatch.setattr(utils, "_rename_no_clobber_same_fs", lambda a, b: os.rename(a, b))   # overwrites


def _fail_file_sync(monkeypatch):
    def fsync(fd):
        raise OSError(22, "Invalid argument")
    monkeypatch.setattr(utils.os, "fsync", fsync)


def _fail_folder_sync(monkeypatch):
    def fsync_dir(path):
        raise OSError(22, "Invalid argument")
    monkeypatch.setattr(utils, "_fsync_dir", fsync_dir)


_FAILURES = {utils.FS_LOCKS: _fail_locks, utils.FS_ATOMIC_RENAME: _fail_atomic_rename,
             utils.FS_NO_CLOBBER_MOVE: _fail_no_clobber, utils.FS_FILE_SYNC: _fail_file_sync,
             utils.FS_FOLDER_SYNC: _fail_folder_sync}


@pytest.mark.spec("RUL-filesystem_requirements_tried", "RUL-filesystem_lacking_named", "RUL-filesystem_trial_leaves_nothing",
                  test="TST-filesystem_checks-each_requirement_tried")
@pytest.mark.parametrize("requirement", list(_FAILURES))
def test_each_requirement_is_tried_and_the_missing_one_named(tmp_path, monkeypatch, requirement):
    folder = tmp_path / "ctl"; folder.mkdir()
    (folder / "kept").write_text("kept")
    before = _state(tmp_path)
    assert utils.filesystem_lacks(str(folder), utils.WORKSPACE_FS_REQUIREMENTS) is None   # this one does them all
    assert _state(tmp_path) == before                               # nothing left behind, the folder's time kept
    _FAILURES[requirement](monkeypatch)
    assert utils.filesystem_lacks(str(folder), utils.WORKSPACE_FS_REQUIREMENTS) == requirement
    monkeypatch.undo()
    assert _state(tmp_path) == before


@pytest.mark.spec("RUL-filesystem_lacking_stops", "RUL-filesystem_lacking_named", "RUL-filesystem_trial_leaves_nothing",
                  test="TST-filesystem_checks-phases_stop_on_a_missing_requirement")
@pytest.mark.parametrize("phase", ["prep-first", "prep", "geotag", "merge"])
def test_a_phase_stops_on_a_missing_requirement_before_its_lock(tmp_path, monkeypatch, capsys, phase):
    """A filesystem without locks stops each phase naming them — never read as a run in progress — and leaves the
    workspace as it was; prep's first run tries them in the workspace itself, its control directory not yet made."""
    if phase == "prep-first":
        ws = tmp_path / "ws"; ws.mkdir(); (ws / "a.jpg").write_bytes(b"x")
    else:
        ws = _cli_ws(tmp_path)
    before = _state(tmp_path)
    _fail_locks(monkeypatch)
    monkeypatch.chdir(ws)
    with pytest.raises(SystemExit) as ei:
        if phase.startswith("prep"):
            prep.run(types.SimpleNamespace(command="plan", jobs=1, delete=False, plan_id=None))
        elif phase == "geotag":
            geotag.run(types.SimpleNamespace(command="plan", jobs=1))
        else:
            merge.run(types.SimpleNamespace(command="plan", jobs=1))
    err = capsys.readouterr().err
    assert ei.value.code == 2 and utils.FS_LOCKS in err and "locked" not in err
    monkeypatch.undo()
    assert _state(tmp_path) == before


@pytest.mark.spec("RUL-filesystem_requirements_tried", test="TST-filesystem_checks-trial_in_the_control_directory")
def test_the_workspace_is_tried_in_its_control_directory(tmp_path, monkeypatch):
    ws = _cli_ws(tmp_path)
    where = []
    real = utils.filesystem_lacks
    monkeypatch.setattr(utils, "filesystem_lacks", lambda folder, reqs: where.append((folder, reqs)) or real(folder, reqs))
    assert utils.workspace_filesystem_error(str(ws)) is None
    assert where == [(utils.control_dir(str(ws)), utils.WORKSPACE_FS_REQUIREMENTS)]


# --- the library's requirements, tried -----------------------------------------------------------------------------

@pytest.mark.spec("RUL-library_requirements_tried", "RUL-library_lacking_stops", "RUL-library_lacking_named",
                  "RUL-filesystem_trial_leaves_nothing", test="TST-filesystem_checks-library_tried_before_its_lock")
@pytest.mark.parametrize("command", ["plan", "dry-run", "execute"])
def test_merge_stops_on_a_library_that_cannot_refuse_a_move(tmp_path, monkeypatch, capsys, command):
    """A library whose filesystem cannot refuse a move onto a taken name stops merge, naming it, before the library's
    lock is taken; the library, the workspace's photos and merge's records stay as they were."""
    ws, lib = _merge_ws(tmp_path, [{"fp": "A", "dest": "Trip", "final_name": "a.jpg"}])
    if command != "plan":
        assert merge._run_locked_workflow("plan", str(ws)) == 0
    lib_before, ws_before = _state(lib), _state(ws / "6-photos-by-dest")
    plan_before = open(merge.merge_plan_path(str(ws))).read() if command != "plan" else None
    real = utils._rename_no_clobber_same_fs
    monkeypatch.setattr(utils, "_rename_no_clobber_same_fs",
                        lambda a, b: os.rename(a, b) if str(lib) in a else real(a, b))   # the library's clobbers
    assert merge._run_locked_workflow(command, str(ws)) == 2
    assert utils.FS_NO_CLOBBER_MOVE in capsys.readouterr().err
    assert _state(lib) == lib_before                                # no trial left, the lock never taken
    assert os.path.exists(utils.library_lock_path(str(lib))) == (command != "plan")
    assert _state(ws / "6-photos-by-dest") == ws_before
    assert not os.path.exists(merge.merge_summary_path(str(ws)))
    if plan_before is None:
        assert not os.path.exists(merge.merge_plan_path(str(ws)))
    else:
        assert open(merge.merge_plan_path(str(ws))).read() == plan_before


@pytest.mark.spec("RUL-library_network_allowed", test="TST-filesystem_checks-library_on_a_network_filesystem")
def test_a_library_on_a_network_filesystem_is_merged_into(tmp_path, monkeypatch):
    ws, lib = _merge_ws(tmp_path, [{"fp": "A", "dest": "Trip", "final_name": "a.jpg"}])
    _mounted(monkeypatch, ("/", "ext4"), (lib, "nfs4"))
    assert merge._run_locked_workflow("plan", str(ws)) == 0
    assert merge._run_locked_workflow("execute", str(ws)) == 0
    assert open(os.path.join(str(lib), "Trip", "a.jpg"), "rb").read() == _fp_bytes("A")
    assert not any(n.startswith(utils.FS_TRIAL_PREFIX) for n in os.listdir(lib))


# --- the library's free space ---------------------------------------------------------------------------------------

def _library_elsewhere(monkeypatch, lib, free):
    """Make the library lie on another filesystem than the workspace, with `free` bytes free on it."""
    real = merge._device
    lib = os.path.realpath(str(lib))
    monkeypatch.setattr(merge, "_device", lambda p: -7 if os.path.realpath(p).startswith(lib) else real(p))
    asked = []
    monkeypatch.setattr(merge, "_free_bytes", lambda p: asked.append(p) or free)
    return asked


_TWO = [{"fp": "A" * 40, "dest": "Trip", "final_name": "a.jpg"}, {"fp": "B" * 40, "dest": "Trip", "final_name": "b.jpg"}]
_NEED = 2 * len(_fp_bytes("A" * 40))                                 # 86 bytes: both photos


@pytest.mark.spec("RUL-library_space_checked", "RUL-library_space_short_stops", "RUL-library_space_short_named",
                  test="TST-filesystem_checks-execute_stops_short_of_room")
def test_execute_stops_with_nothing_moved_when_the_library_is_short_of_room(tmp_path, monkeypatch, capsys):
    ws, lib = _merge_ws(tmp_path, _TWO)
    assert merge._run_locked_workflow("plan", str(ws)) == 0
    asked = _library_elsewhere(monkeypatch, lib, _NEED - 1)
    lib_before = _state(lib, but=(".photos-merge.lock",))
    assert merge._run_locked_workflow("execute", str(ws)) == 2
    out = capsys.readouterr()
    assert f"{_NEED - 1} bytes free" in out.err + out.out and f"need {_NEED} bytes" in out.err + out.out
    assert asked == [str(lib)]
    assert _state(lib, but=(".photos-merge.lock",)) == lib_before   # nothing moved
    assert os.path.exists(_src(ws, "Trip", "a.jpg")) and os.path.exists(_src(ws, "Trip", "b.jpg"))
    assert not os.path.exists(merge.merge_summary_path(str(ws)))


@pytest.mark.spec("RUL-library_space_checked", test="TST-filesystem_checks-execute_counts_only_what_is_left")
def test_execute_counts_only_the_photos_still_to_move(tmp_path, monkeypatch):
    """A photo an earlier run moved, or whose place already holds a file, takes no room: with room for the one
    left, execute goes on and places it."""
    ws, lib = _merge_ws(tmp_path, _TWO)
    assert merge._run_locked_workflow("plan", str(ws)) == 0
    os.makedirs(lib / "Trip")
    os.rename(_src(ws, "Trip", "a.jpg"), lib / "Trip" / "a.jpg")    # as an interrupted run left it
    _library_elsewhere(monkeypatch, lib, _NEED // 2)
    assert merge._run_locked_workflow("execute", str(ws)) == 0
    assert _summary(ws)["status"] == "success"
    assert open(lib / "Trip" / "b.jpg", "rb").read() == _fp_bytes("B" * 40)


@pytest.mark.spec("RUL-library_space_warned_at_plan", test="TST-filesystem_checks-plan_warns_short_of_room")
def test_the_plan_warns_of_a_library_short_of_room_and_is_written(tmp_path, monkeypatch, capsys):
    ws, lib = _merge_ws(tmp_path, _TWO)
    _library_elsewhere(monkeypatch, lib, 10)
    assert merge._run_locked_workflow("plan", str(ws)) == 0
    out = capsys.readouterr()
    assert "Warning" in out.err and "10 bytes free" in out.err and f"need {_NEED} bytes" in out.err
    plan = json.loads(open(merge.merge_plan_path(str(ws))).read())
    assert plan["totals"]["placed_new"] == 2


@pytest.mark.spec("RUL-library_space_checked", test="TST-filesystem_checks-same_filesystem_not_checked")
def test_on_the_workspaces_own_filesystem_no_room_is_asked(tmp_path, monkeypatch, capsys):
    ws, lib = _merge_ws(tmp_path, _TWO)
    monkeypatch.setattr(merge, "_free_bytes", lambda p: pytest.fail("free space asked on one filesystem"))
    assert merge._run_locked_workflow("plan", str(ws)) == 0
    assert merge._run_locked_workflow("execute", str(ws)) == 0
    assert "Warning" not in capsys.readouterr().err
