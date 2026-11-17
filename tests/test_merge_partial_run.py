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

"""A merge that places one photo and leaves another unplaced is partial, never whole (RUL-unplaced_photo_run_partial),
and only a whole merge seals (RUL-seal_on_success_only): the run ends partial, the workspace stays unsealed and merge's
terminal records are not made."""
import os

import pytest

import photos_3_merge as merge
import photos_utils as utils
from test_merge_execute import _content_fingerprint, _fp_bytes, _src, _summary, _ws  # noqa: F401 (autouse fixture)


@pytest.mark.spec("RUL-unplaced_photo_run_partial", "RUL-seal_on_success_only",
                  test="TST-merge_partial_run-one_placed_one_blocked_is_partial_and_unsealed")
def test_one_placed_one_blocked_is_partial_and_unsealed(tmp_path):
    ws, lib = _ws(tmp_path, [{"fp": "A", "dest": "Trip", "final_name": "a.jpg"},
                             {"fp": "B", "dest": "Trip", "final_name": "b.jpg"}],
                  library_files=[{"fp": "FAIL", "dest": "Trip", "name": "b.jpg"}])
    assert merge._run_locked_workflow("plan", str(ws)) == 2             # b.jpg blocked
    assert merge._run_locked_workflow("execute", str(ws)) == 3          # not a success
    assert _summary(ws)["status"] == "partial"
    # a.jpg was placed, b.jpg was not: the run left a photo unplaced
    assert open(os.path.join(str(lib), "Trip", "a.jpg"), "rb").read() == _fp_bytes("A")
    assert not os.path.exists(_src(ws, "Trip", "a.jpg"))
    assert os.path.exists(_src(ws, "Trip", "b.jpg"))
    assert not utils.is_sealed(str(ws))
    ctl = os.path.join(str(ws), ".photos-ingest")
    assert not os.path.exists(os.path.join(ctl, "photos-00-sealed.json"))
    assert not [n for n in os.listdir(ctl) if n.startswith("photos-35-")], os.listdir(ctl)
