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

"""A prep re-plan that says what the saved plan says, no execution begun under it, keeps the saved plan: nothing
written, nothing set aside (BLD-prep_replan_unchanged). Prep runs for real, its fingerprint and metadata reading stood
in for, as in test_workspace_check."""
import errno
import json
import os

import pytest

import photos_1_prep as prep
import photos_utils as utils
from test_workspace_check import _fresh, _prep


def _plans(ws):
    return sorted(n for n in os.listdir(ws / ".photos-ingest") if n.startswith("photos-10-prep-plan"))


@pytest.mark.spec("RUL-unchanged_replan_writes_nothing", "BLD-prep_replan_unchanged",
                  test="TST-prep_replan_unchanged-an_unchanged_replan_keeps_the_saved_plan")
def test_an_unchanged_replan_keeps_the_saved_plan(tmp_path, monkeypatch):
    """A dump of two photos and a stray planned, then planned again with nothing changed: the second run reads less
    than the first and would name itself and its operations anew, and the saved plan is kept byte for byte — its id,
    its operations' ids — with no copy set aside. A third file changes what the plan says: it is then written, the
    earlier one set aside."""
    ws = _fresh(monkeypatch, tmp_path)
    for name, content in (("d.jpg", b"DDDD"), ("e.jpg", b"EEEE"), ("note.txt", b"a stray")):
        (ws / "0-sources" / name).write_bytes(content)
    rc, said, _ = _prep(monkeypatch, ws, "plan")
    assert rc == 0, said
    path = utils.prep_plan_path(str(ws))
    saved, stat, before = open(path, "rb").read(), os.stat(path), _plans(ws)
    assert json.loads(saved)["operations"]

    rc, said, _ = _prep(monkeypatch, ws, "plan")
    assert rc == 0 and "Plan unchanged" in said, said
    assert open(path, "rb").read() == saved and os.stat(path).st_mtime_ns == stat.st_mtime_ns
    assert _plans(ws) == before                                              # nothing set aside

    (ws / "0-sources" / "f.jpg").write_bytes(b"FFFF")
    rc, said, _ = _prep(monkeypatch, ws, "plan")
    assert rc == 0 and "Plan unchanged" not in said, said
    (aside,) = set(_plans(ws)) - set(before)
    assert open(ws / ".photos-ingest" / aside, "rb").read() == saved


@pytest.mark.spec("RUL-unchanged_replan_writes_nothing", "BLD-prep_replan_unchanged", "RUL-prep_journal_kept",
                  test="TST-prep_replan_unchanged-a_kept_plan_executed_again_keeps_its_earlier_journal")
def test_a_kept_plan_executed_again_keeps_its_earlier_journal(tmp_path, monkeypatch):
    """A plan whose execution failed at its first move, nothing changed: planned again, the plan says the same and is
    kept, under its id. Executed again it is carried out, and the journal of the execution that failed is set aside
    beside the new one, not written over."""
    ws = _fresh(monkeypatch, tmp_path)
    (ws / "0-sources" / "d.jpg").write_bytes(b"DDDD")
    rc, said, _ = _prep(monkeypatch, ws, "plan")
    assert rc == 0, said
    path = utils.prep_plan_path(str(ws))
    saved, before = open(path, "rb").read(), _plans(ws)
    first = json.loads(saved)

    def move_fails(src, dst):
        raise OSError(errno.EIO, "the move fails")
    with monkeypatch.context() as m:
        m.setattr(prep, "_move_no_clobber", move_fails)
        rc, said, _ = _prep(m, ws, "execute")
    assert rc == 3, said
    journal = utils.journal_path(str(ws), first["plan_id"])
    failed = open(journal, "rb").read()
    assert json.loads(failed)["operations"][-1]["status"] == "failed"

    rc, said, _ = _prep(monkeypatch, ws, "plan")
    assert rc == 0 and "Plan unchanged" in said, said
    assert open(path, "rb").read() == saved and _plans(ws) == before

    rc, said, _ = _prep(monkeypatch, ws, "execute")
    assert rc == 0, said
    assert not (ws / "0-sources" / "d.jpg").exists()
    assert json.load(open(journal))["status"] == "success"
    assert open(journal[:-len(".json")] + "-001.json", "rb").read() == failed
