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

"""Prep's operation that raised is journalled `failed` and the execution stops there (BLD-failed_operation): its
failure recorded, never recorded as done, its file left where it was. Prep runs for real, its fingerprint and metadata
reading stood in for, as in test_workspace_check."""
import errno
import json

import pytest

import photos_1_prep as prep
import photos_utils as utils
from test_workspace_check import _fresh, _prep


@pytest.mark.spec("RUL-failure_recorded", "RUL-failure_never_done", "RUL-failed_operation_clean",
                  "BLD-failed_operation", test="TST-prep_failed_operation-a_raised_operation_is_journalled_failed")
def test_a_raised_operation_is_journalled_failed(tmp_path, monkeypatch):
    """A new dump of three photos planned; the move of the second raises. The journal holds the first as done, the
    second as failed with the error it raised, and nothing after it — the execution stopped there — and the photo whose
    move failed is still in the inbox, as it was."""
    ws = _fresh(monkeypatch, tmp_path)
    for name, content in (("d.jpg", b"DDDD"), ("e.jpg", b"EEEE"), ("f.jpg", b"FFFF")):
        (ws / "0-sources" / name).write_bytes(content)
    rc, said, _ = _prep(monkeypatch, ws, "plan")
    assert rc == 0, said
    plan = json.load(open(utils.prep_plan_path(str(ws))))
    real_move, moves = prep._move_no_clobber, []

    def second_move_fails(src, dst):
        moves.append(src)
        if len(moves) == 2:
            raise OSError(errno.EIO, "the second move fails")
        return real_move(src, dst)
    monkeypatch.setattr(prep, "_move_no_clobber", second_move_fails)
    rc, said, _ = _prep(monkeypatch, ws, "execute")
    assert rc == 3 and len(moves) == 2, said

    journal = json.load(open(utils.journal_path(str(ws), plan["plan_id"])))
    statuses = [r["status"] for r in journal["operations"]]
    assert statuses[-1] == "failed" and "the second move fails" in journal["operations"][-1]["details"]["error"]
    assert "failed" not in statuses[:-1]                                     # nothing journalled after the failure
    failed_op = next(o for o in plan["operations"] if o["operation_id"] == journal["operations"][-1]["operation_id"])
    assert failed_op["source"] == "0-sources/" + moves[1].rsplit("/", 1)[-1]
    assert (ws / failed_op["source"]).exists() and not (ws / failed_op["destination"]).exists()
    assert len(journal["operations"]) < len(plan["operations"])             # the execution stopped there
    assert journal["status"] != "success"
