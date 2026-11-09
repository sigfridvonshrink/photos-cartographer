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

"""A workspace lies on one filesystem (shared contract §15): every phase checks it on every
invocation and stops, nothing touched, when a folder in the workspace lies on another volume.

A second volume is faked by patching photos_utils._dev_of — the one seam the check reads devices
through — so a chosen folder reports a different device than the workspace root."""
import os
import types

import pytest

import photos_1_prep as prep
import photos_2_geotag as geotag
import photos_3_merge as merge
import photos_utils as utils


def _other_volume(monkeypatch, *folders):
    """Make each given absolute folder report a device other than everything else's."""
    real = utils._dev_of
    marked = {os.path.abspath(str(f)) for f in folders}
    monkeypatch.setattr(utils, "_dev_of",
                        lambda p: -1 if os.path.abspath(p) in marked else real(p))


def _ws(tmp_path):
    ws = tmp_path / "ws"
    (ws / "0-sources" / "trip").mkdir(parents=True)
    (ws / "5-photos-by-date").mkdir()
    return ws


@pytest.mark.spec("RUL-workspace_one_filesystem", test="TST-workspace_one_filesystem-breaks_found_anywhere")
def test_breaks_found_anywhere_without_descending(tmp_path, monkeypatch):
    ws = _ws(tmp_path)
    (ws / ".photos-ingest").mkdir()
    (ws / "0-sources" / "trip" / "deep").mkdir()
    assert utils.workspace_volume_breaks(str(ws)) == []
    assert utils.workspace_volume_error(str(ws)) is None
    _other_volume(monkeypatch, ws / "0-sources" / "trip", ws / ".photos-ingest")
    # the nested mount and the control directory are both found; nothing below a mount is listed
    assert utils.workspace_volume_breaks(str(ws)) == [".photos-ingest", os.path.join("0-sources", "trip")]
    err = utils.workspace_volume_error(str(ws))
    assert "more than one filesystem" in err and os.path.join("0-sources", "trip") + "/" in err


@pytest.mark.spec("RUL-workspace_one_filesystem", test="TST-workspace_one_filesystem-prep_refuses")
@pytest.mark.parametrize("command", ["plan", "dry-run", "execute", "prune-quarantine"])
def test_prep_refuses_a_workspace_on_two_volumes(tmp_path, monkeypatch, capsys, command):
    ws = tmp_path / "ws"; ws.mkdir()
    (ws / "dump").mkdir()
    (ws / "dump" / "a.jpg").write_bytes(b"x")                  # an uninitialized workspace with a dump
    _other_volume(monkeypatch, ws / "dump")
    monkeypatch.chdir(ws)
    with pytest.raises(SystemExit) as ei:
        prep.run(types.SimpleNamespace(command=command, jobs=1, delete=False, plan_id=None))
    assert ei.value.code == 2 and "more than one filesystem" in capsys.readouterr().err
    assert (ws / "dump" / "a.jpg").read_bytes() == b"x"        # nothing moved
    assert not (ws / "0-sources").exists()                     # nothing initialized
    assert not os.path.exists(utils.prep_plan_path(str(ws)))   # no plan written


@pytest.mark.spec("RUL-workspace_one_filesystem", test="TST-workspace_one_filesystem-geotag_refuses")
@pytest.mark.parametrize("command", ["plan", "execute", "finalize"])
def test_geotag_refuses_a_workspace_on_two_volumes(tmp_path, monkeypatch, capsys, command):
    ws = _ws(tmp_path)
    _other_volume(monkeypatch, ws / "5-photos-by-date")
    monkeypatch.chdir(ws)
    before = sorted(os.listdir(ws))
    with pytest.raises(SystemExit) as ei:
        geotag.run(types.SimpleNamespace(command=command, jobs=1))
    assert ei.value.code == 2 and "more than one filesystem" in capsys.readouterr().err
    assert not any(n.startswith("photos-2") for n in os.listdir(ws / ".photos-ingest"))   # no artifact
    assert [n for n in sorted(os.listdir(ws)) if n != ".photos-ingest"] == before


@pytest.mark.spec("RUL-workspace_one_filesystem", test="TST-workspace_one_filesystem-merge_refuses")
@pytest.mark.parametrize("command", ["plan", "dry-run", "execute"])
def test_merge_refuses_a_workspace_on_two_volumes(tmp_path, monkeypatch, capsys, command):
    ws = _ws(tmp_path)
    _other_volume(monkeypatch, ws / "0-sources")
    assert merge._run_locked_workflow(command, str(ws)) == 2
    assert "more than one filesystem" in capsys.readouterr().err
    assert not os.path.exists(merge.merge_plan_path(str(ws)))
    assert not os.path.exists(merge.merge_summary_path(str(ws)))


@pytest.mark.spec("RUL-workspace_one_filesystem", test="TST-workspace_one_filesystem-init_library_refuses")
@pytest.mark.parametrize("with_path", [False, True])
def test_init_library_in_a_workspace_on_two_volumes_refuses(tmp_path, monkeypatch, capsys, with_path):
    ws = _ws(tmp_path)
    (ws / ".photos-ingest").mkdir()
    open(utils.guard_path(str(ws)), "w").close()               # an initialized workspace
    lib = tmp_path / "lib"; lib.mkdir()
    _other_volume(monkeypatch, ws / "5-photos-by-date")
    assert merge.do_init_library(str(lib) if with_path else None, str(ws)) == 2
    assert "more than one filesystem" in capsys.readouterr().err
    assert not (lib / ".photos-library").exists()              # nothing blessed
