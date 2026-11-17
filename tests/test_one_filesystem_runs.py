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

"""A workspace lies on one filesystem (RUL-workspace_one_filesystem), and the runs hold to it: a workspace found to
span filesystems stops the run at the check itself, over a workspace every later step would accept
(RUL-spanning_workspace_stops); and a move by prep or geotag that would cross filesystems fails, never made a copy
(RUL-workspace_moves_one_filesystem). A second volume is faked at the seams the code reads it through:
photos_utils._dev_of for a folder's device, photos_utils._rename_no_clobber_same_fs for a rename refused with EXDEV."""
import errno
import glob
import json
import os
import types

import pytest

import photos_1_prep as prep
import photos_2_geotag as geotag
import photos_3_merge as merge
import photos_utils as utils
from _handoff import recorded
from test_workspace_one_filesystem import _other_volume

MANAGED = ["0-sources", "1-strays", "2-missing-metadata", "3-redundant-jpgs",
           "4-videos-by-date", "5-photos-by-date", "6-photos-by-dest"]


class _PastTheCheck(Exception):
    """Raised by the step a run takes right after the filesystem check: the run went on."""


def _past(*a, **k):
    raise _PastTheCheck()


def _ws(tmp_path):
    """An initialized workspace — guard, configuration, the state its last execution left recorded — that every
    step after the filesystem check would take up."""
    ws = tmp_path / "ws"
    ws.mkdir()
    for d in MANAGED:
        (ws / d).mkdir()
    (ws / ".photos-ingest").mkdir()
    (ws / ".photos-ingest" / "photos-00-workspace-guard").touch()
    cfg = {k: v for k, v in utils.CONFIG.items() if k != "jobs"}
    cfg["zfs"] = dict(cfg["zfs"], enabled=False)
    (ws / ".photos-ingest" / "photos-00-config.json").write_text(json.dumps(cfg))
    return recorded(ws)


@pytest.mark.parametrize("command", ["plan", "dry-run", "execute"])
@pytest.mark.spec("RUL-spanning_workspace_stops", "RUL-one_filesystem_checked_every_run",
                  test="TST-one_filesystem_runs-merge_stops_at_the_filesystem_check")
def test_merge_stops_at_the_filesystem_check(tmp_path, monkeypatch, capsys, command):
    """Merge over an initialized, recorded workspace one folder of which lies on another volume stops at the check,
    a refusal, going no further."""
    ws = _ws(tmp_path)
    _other_volume(monkeypatch, ws / "5-photos-by-date")
    monkeypatch.setattr(merge, "MergeWorkflow", _past)
    assert merge._run_locked_workflow(command, str(ws)) == 2
    assert "more than one filesystem" in capsys.readouterr().err


@pytest.mark.parametrize("command", ["plan", "execute", "finalize"])
@pytest.mark.spec("RUL-spanning_workspace_stops", "RUL-one_filesystem_checked_every_run",
                  test="TST-one_filesystem_runs-geotag_stops_at_the_filesystem_check")
def test_geotag_stops_at_the_filesystem_check(tmp_path, monkeypatch, capsys, command):
    """Geotag over an initialized, recorded workspace one folder of which lies on another volume stops at the check,
    a refusal, going no further — not even to the check of the workspace against its record."""
    ws = _ws(tmp_path)
    _other_volume(monkeypatch, ws / "5-photos-by-date")
    monkeypatch.setattr(geotag, "_check_workspace", _past)
    monkeypatch.chdir(ws)
    with pytest.raises(SystemExit) as ei:
        geotag.run(types.SimpleNamespace(command=command, jobs=1, accept_changes=None))
    assert ei.value.code == 2 and "more than one filesystem" in capsys.readouterr().err


@pytest.mark.spec("RUL-spanning_workspace_stops", "RUL-one_filesystem_checked_every_run",
                  test="TST-one_filesystem_runs-init_library_with_a_path_stops_at_the_filesystem_check")
def test_init_library_with_a_path_stops_at_the_filesystem_check(tmp_path, monkeypatch, capsys):
    """`init-library <path>` in an initialized workspace one folder of which lies on another volume stops at the check,
    a refusal: the configuration is not read, nothing blessed."""
    ws = _ws(tmp_path)
    lib = tmp_path / "lib"
    lib.mkdir()
    _other_volume(monkeypatch, ws / "5-photos-by-date")
    monkeypatch.setattr(merge, "_read_checked_config", _past)
    assert merge.do_init_library(str(lib), str(ws)) == 2
    assert "more than one filesystem" in capsys.readouterr().err
    assert not utils.is_library(str(lib))


# --- a move that would cross filesystems fails --------------------------------

def _exdev_on_every_move(monkeypatch, folder):
    """Every move of a file in `folder` reports EXDEV — the destination on another filesystem; a rename of the
    cross-filesystem copy's temporary file into place would succeed, as would the runs' own trials of the filesystem
    on scratch files of the control directory. Returns the moves tried."""
    real, tried = utils._rename_no_clobber_same_fs, []

    def rename(src, dst):
        if not os.path.abspath(src).startswith(str(folder) + os.sep) \
                or os.path.basename(src).startswith(utils.XDEV_TMP_PREFIX):
            return real(src, dst)
        tried.append((src, dst))
        raise OSError(errno.EXDEV, "Invalid cross-device link", src)
    monkeypatch.setattr(utils, "_rename_no_clobber_same_fs", rename)
    return tried


def _temps(root):
    return glob.glob(os.path.join(str(root), "**", utils.XDEV_TMP_PREFIX + "*"), recursive=True)


@pytest.mark.spec("RUL-workspace_moves_one_filesystem", "RUL-failure_recorded",
                  test="TST-one_filesystem_runs-prep_move_across_filesystems_fails")
def test_prep_move_across_filesystems_fails(tmp_path, monkeypatch):
    """Prep's execution whose move of a new photo would cross filesystems: the move fails, recorded as failed in the
    journal, the photo still in the inbox, nothing — not even a temporary copy — at its destination."""
    from test_workspace_check import _fresh, _prep
    ws = _fresh(monkeypatch, tmp_path)
    (ws / "0-sources" / "d.jpg").write_bytes(b"DDDD")
    rc, said, _ = _prep(monkeypatch, ws, "plan")
    assert rc == 0, said
    plan = json.load(open(utils.prep_plan_path(str(ws))))
    tried = _exdev_on_every_move(monkeypatch, ws / "0-sources")
    rc, said, _ = _prep(monkeypatch, ws, "execute")
    assert rc == 3 and tried, said
    journal = json.load(open(utils.journal_path(str(ws), plan["plan_id"])))
    failed = [r for r in journal["operations"] if r["status"] == "failed"]
    assert len(failed) == 1 and "cross-device" in failed[0]["details"]["error"]
    op = next(o for o in plan["operations"] if o["operation_id"] == failed[0]["operation_id"])
    assert (ws / op["source"]).read_bytes() == b"DDDD"
    assert not (ws / op["destination"]).exists() and _temps(ws) == []


@pytest.mark.spec("RUL-workspace_moves_one_filesystem", "RUL-failure_recorded",
                  test="TST-one_filesystem_runs-geotag_rename_across_filesystems_fails")
def test_geotag_rename_across_filesystems_fails(tmp_path, monkeypatch):
    """Geotag's execution whose renames would cross filesystems: each rename fails, recorded as failed, every photo
    still under its own name and nothing — not even a temporary copy — under the new one."""
    import test_geotag_execution as gx
    ws, ctl = gx._ready_ws(tmp_path, monkeypatch)
    gx._mock_tools(monkeypatch, ws)
    before = sorted(os.listdir(ws / "6-photos-by-dest" / "T"))
    tried = _exdev_on_every_move(monkeypatch, ws / "6-photos-by-dest")
    assert gx._execute(monkeypatch, ws) != 0
    assert tried
    s = gx._summary(ctl)
    assert s["status"] != "success" and s["totals"]["renames"] == 0
    assert sorted(os.listdir(ws / "6-photos-by-dest" / "T")) == before
    assert _temps(ws) == []
    named = json.dumps(s["failures"]) + json.dumps(s.get("blockers"))
    assert all(os.path.basename(src) in named for src, _dst in tried), named
