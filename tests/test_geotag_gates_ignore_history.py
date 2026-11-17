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

"""What ran before — any number of prep and sort cycles, a geotag run carried through execute and finalize — bears
on none of geotag's gates: each one a workspace fails stops it exactly as it stops one with no history."""
import json
import os

import pytest

import photos_2_geotag as cal
from test_geotag_preflight import _ws


def _with_history(ws):
    """The records an earlier seven prep runs and a finalized geotag run leave in the control directory."""
    ctl = ws / ".photos-ingest"
    ho_p = ctl / "photos-11-handoff.json"
    ho = json.loads(ho_p.read_text())
    ho["run_metadata"] = {"plan_id": "prep-7", "execution_id": "exec-7", "started_at": "t7"}
    ho_p.write_text(json.dumps(ho))
    for n in ("photos-10-prep-plan.json", "photos-10-prep-plan-001.json", "photos-10-prep-plan-006.json",
              "journal-exec-1.json", "journal-exec-7.json",
              "photos-21-time-decisions.json", "photos-21-time-decisions-001.json",
              "photos-22-gps-drift-validation.json", "photos-23-gps-decisions.json",
              "photos-24-executable-plan-001.json",
              "photos-26-complete-log.json", "photos-26-archive-manifest.json"):
        (ctl / n).write_text(json.dumps({"status": "complete", "plan_id": "earlier"}))
    (ctl / "photos-25-execution-summary.json").write_text(json.dumps({"status": "success", "plan_id": "earlier"}))
    (ctl / "photos-26-finalized-media.json").write_text(json.dumps(
        {"plan_id": "earlier", "media": {"6-photos-by-dest/Trip/a.jpg": {"size": 3, "mtime_ns": 1}}}))


def _fail(ws, gate):
    """Make `ws` fail `gate`, as the workspace stands now."""
    trip = ws / "6-photos-by-dest" / "Trip"
    if gate == "inbox":
        (ws / "0-sources" / "leftover.jpg").write_bytes(b"x")
    elif gate == "photos by date":
        (ws / "5-photos-by-date" / "2024-07-03").mkdir()
        (ws / "5-photos-by-date" / "2024-07-03" / "left.jpg").write_bytes(b"x")
    elif gate == "only photos":
        (trip / "notes.txt").write_text("hi")
    elif gate == "no video":
        (trip / "clip.mp4").write_bytes(b"v")
    elif gate == "no development":
        (trip / "jpg").mkdir()
    elif gate == "recorded by prep":
        (trip / "b.jpg").write_bytes(b"not recorded")


GATES = ["inbox", "photos by date", "only photos", "no video", "no development", "recorded by prep"]


@pytest.mark.parametrize("gate", GATES)
@pytest.mark.spec("RUL-geotag_gates_ignore_history",
                  test="TST-geotag_gates_ignore_history-every_gate_stops_whatever_ran_before")
def test_every_gate_stops_whatever_ran_before(tmp_path, gate):
    """Each gate a workspace fails stops geotag's plan, and its execute and finalize, with the same blockers whether
    or not the records of earlier prep cycles and of a finalized geotag run are there."""
    (tmp_path / "fresh").mkdir(); (tmp_path / "again").mkdir()
    fresh, again = _ws(tmp_path / "fresh"), _ws(tmp_path / "again")
    _with_history(again)
    for ws in (fresh, again):
        # the plan an execute or a finalize would carry out, the same in both
        (ws / ".photos-ingest" / "photos-24-executable-plan.json").write_text(
            json.dumps({"status": "complete", "plan_id": "current"}))
        _fail(ws, gate)
    for for_execute in (False, True):
        without = cal.GeotagWorkflow(str(fresh)).preflight(for_execute=for_execute)[0]
        with_history = cal.GeotagWorkflow(str(again)).preflight(for_execute=for_execute)[0]
        assert without, (gate, for_execute)                                  # the gate stops it
        assert [b.replace(os.sep + "again" + os.sep, os.sep) for b in with_history] == \
            [b.replace(os.sep + "fresh" + os.sep, os.sep) for b in without], (gate, for_execute)
