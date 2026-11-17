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

"""What planning leaves as it was: no media file changed — its bytes, size and modification time — nothing written
but the planning command's own records (RUL-planning_writes_only_its_records), and the recorded state of the
workspace's files untouched by a plan, a dry run or finalize (RUL-planning_leaves_record)."""
import os
import re

import pytest

import photos_3_merge as merge
import photos_utils as utils
from _handoff import recorded


def _snapshot(root):
    """{relative path: (bytes, size, mtime_ns)} of every file under `root` but the transient lock files."""
    out = {}
    for r, _dn, fns in os.walk(root):
        for f in fns:
            if f.endswith(".lock"):
                continue
            p = os.path.join(r, f)
            st = os.lstat(p)
            with open(p, "rb") as fh:
                out[os.path.relpath(p, root)] = (fh.read(), st.st_size, st.st_mtime_ns)
    return out


def _changed(before, after):
    return sorted(k for k in set(before) | set(after) if before.get(k) != after.get(k))


def _merge_ws(tmp_path, monkeypatch):
    import test_merge_execute as mx

    def fake(self, abs_path):
        return {"status": "valid", "value": mx._parse_fp(abs_path), "strategy": "image-content-hash-v2",
                "engine_version": "test"}
    monkeypatch.setattr(merge.MergeWorkflow, "_fingerprint_library_file", fake)
    ws, lib = mx._ws(tmp_path, [{"fp": "A", "dest": "Trip", "final_name": "a.jpg"},
                                {"fp": "B", "dest": "Trip", "final_name": "b.jpg"}],
                     library_files=[{"fp": "C", "dest": "Trip", "name": "c.jpg"}])
    return ws, lib


# The records each planning command writes: its plan and decision records (and the version of one it keeps under
# -NNN), and the workspace database, where geotag keeps its track catalogue and merge its library cache.
_MERGE_PLAN_WRITES = re.compile(r"\.photos-ingest/(photos-00-ingest\.db|photos-30-merge-plan(-\d{3,})?\.json)$")
_GEOTAG_PLAN_WRITES = re.compile(r"\.photos-ingest/(photos-00-ingest\.db|photos-2[1-4]-[a-z-]+?(-\d{3,})?\.json)$")


@pytest.mark.spec("RUL-planning_changes_no_media", "RUL-planning_writes_only_its_records",
                  test="TST-planning_leaves_workspace-merge_plan_writes_only_its_records")
def test_merge_plan_writes_only_its_records(tmp_path, monkeypatch):
    """Merge's plan, over a recorded workspace and a library already holding a photo: every file of the workspace —
    media and records alike, by bytes, size and modification time — is as it was but merge's plan and the workspace
    database; the library is as it was, every file of it."""
    ws, lib = _merge_ws(tmp_path, monkeypatch)
    recorded(ws)
    ws_before, lib_before = _snapshot(str(ws)), _snapshot(str(lib))
    assert merge._run_locked_workflow("plan", str(ws)) == 0
    changed = _changed(ws_before, _snapshot(str(ws)))
    assert ".photos-ingest/photos-30-merge-plan.json" in changed
    assert [p for p in changed if not _MERGE_PLAN_WRITES.match(p)] == []
    assert _snapshot(str(lib)) == lib_before


@pytest.mark.spec("RUL-planning_changes_no_media", "RUL-planning_writes_only_its_records",
                  test="TST-planning_leaves_workspace-geotag_plan_writes_only_its_records")
def test_geotag_plan_writes_only_its_records(tmp_path, monkeypatch):
    """Geotag's plan — the first, which writes its decision records, and the one after it, which writes the executable
    plan: every file of the workspace, its photos by bytes, size and modification time among them, is as it was but
    geotag's decision records and plan and the workspace database."""
    import test_geotag_finalize as gf
    ws, ctl = gf._ready_ws(tmp_path, monkeypatch)
    recorded(ws)
    before = _snapshot(str(ws))
    for _ in range(2):
        assert gf._run(monkeypatch, ws, "plan") == 0
    changed = _changed(before, _snapshot(str(ws)))
    assert ".photos-ingest/photos-24-executable-plan.json" in changed
    assert [p for p in changed if not _GEOTAG_PLAN_WRITES.match(p)] == []


# --- the recorded state, after a plan, a dry run or finalize ------------------

def _record_id(ws):
    return utils.read_workspace_record(str(ws))[0]


@pytest.mark.spec("RUL-planning_leaves_record", test="TST-planning_leaves_workspace-merge_plan_and_dry_run_leave_the_record")
def test_merge_plan_and_dry_run_leave_the_record(tmp_path, monkeypatch):
    """Merge's plan and dry run leave the record of the workspace's state as the last execution wrote it."""
    ws, _lib = _merge_ws(tmp_path, monkeypatch)
    rid = _record_id(recorded(ws))
    assert merge._run_locked_workflow("plan", str(ws)) == 0
    assert _record_id(ws) == rid
    assert merge._run_locked_workflow("dry-run", str(ws)) == 0
    assert _record_id(ws) == rid


@pytest.mark.spec("RUL-planning_leaves_record", test="TST-planning_leaves_workspace-geotag_finalize_leaves_the_record")
def test_geotag_finalize_leaves_the_record(tmp_path, monkeypatch):
    """Geotag's finalize leaves the record of the workspace's state as geotag's execution wrote it."""
    import json
    import test_geotag_finalize as gf
    ws, ctl = gf._ready_ws(tmp_path, monkeypatch)
    gf._to_executed(monkeypatch, ws, ctl)
    assert json.load(open(ctl / "photos-25-execution-summary.json"))["status"] == "success"
    rid = _record_id(ws)
    assert rid is not None
    assert gf._run(monkeypatch, ws, "finalize") == 0
    assert (ctl / "photos-26-archive-manifest.json").exists()
    assert _record_id(ws) == rid


@pytest.mark.spec("RUL-planning_leaves_record", test="TST-planning_leaves_workspace-prep_dry_run_leaves_the_record")
def test_prep_dry_run_leaves_the_record(tmp_path, monkeypatch):
    """Prep's plan and dry run over a new dump leave the record of the workspace's state as prep's execution wrote
    it."""
    from test_workspace_check import _fresh, _prep
    ws = _fresh(monkeypatch, tmp_path)
    (ws / "0-sources" / "d.jpg").write_bytes(b"DDDD")
    rid = _record_id(ws)
    for command in ("plan", "dry-run"):
        rc, said, _ = _prep(monkeypatch, ws, command)
        assert rc == 0, said
        assert _record_id(ws) == rid, command
