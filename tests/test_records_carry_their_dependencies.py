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

"""Each record a phase creates names, in its `depends_on`, every dependency it was derived from — each one its build
lists (BLD-decision_record_envelope, BLD-geotag_dependencies, BLD-merge_plan)."""
import json
import os

import pytest

import photos_3_merge as merge
from test_geotag_finalize import _ready_ws, _run
from test_merge_plan import _build_ws, _patch_fp

# BLD-decision_record_envelope
TIME_DECISIONS = {"handoff", "camera_time_policy_fingerprint", "gpx_fingerprint", "camera_group_key_version"}
GPS_DECISIONS = {"resolved_utc_cache_fingerprint", "gpx_fingerprint", "gps_policy_fingerprint", "handoff"}
# BLD-geotag_dependencies: photos-21, -22 and -23 by their SHA-256, the handoff, and the rest by name
EXECUTABLE_PLAN = {"time_decisions", "drift_validation", "gps_decisions", "handoff", "config_fingerprint",
                   "code_fingerprint", "camera_group_fingerprint", "camera_group_key_version", "gpx_fingerprint",
                   "metadata_field_set_version", "filename_format_fingerprint", "folders_fingerprint",
                   "media_extensions_fingerprint", "resolved_utc_cache_fingerprint", "prep_cache_fingerprint",
                   "media_preconditions", "planned_operation_fingerprint", "country_table"}
# BLD-merge_plan
MERGE_PLAN = {"photos-24-executable-plan.json", "photos-25-execution-summary.json", "handoff", "config_fingerprint",
              "code_fingerprint", "image_engine_version", "folders_fingerprint", "media_extensions_fingerprint"}


def _depends_on(ctl, name):
    return json.load(open(os.path.join(str(ctl), name)))["depends_on"]


def _missing(dep, keys):
    return sorted(k for k in keys if dep.get(k) is None)


@pytest.mark.spec("RUL-dependencies_recorded_in_record",
                  test="TST-records_carry_their_dependencies-geotag_s_records_name_every_dependency")
def test_geotag_s_records_name_every_dependency(tmp_path, monkeypatch):
    """Geotag's decision records and its executable plan each record every dependency their build lists, none of
    them empty: the time decisions the tracks they were made against, the plan the decision records by their hash."""
    ws, ctl = _ready_ws(tmp_path, monkeypatch)
    _run(monkeypatch, ws, "plan")
    assert _run(monkeypatch, ws, "plan") == 0
    assert _missing(_depends_on(ctl, "photos-21-time-decisions.json"), TIME_DECISIONS) == []
    assert _missing(_depends_on(ctl, "photos-23-gps-decisions.json"), GPS_DECISIONS) == []
    assert isinstance(_depends_on(ctl, "photos-22-gps-drift-validation.json"), dict)
    plan_dep = _depends_on(ctl, "photos-24-executable-plan.json")
    assert _missing(plan_dep, EXECUTABLE_PLAN) == []
    assert isinstance(plan_dep.get("gpx_window"), list)                  # the window the tracks' fingerprint is of
    for record in ("time_decisions", "drift_validation", "gps_decisions"):
        assert plan_dep[record].get("sha256"), (record, plan_dep[record])


@pytest.mark.spec("RUL-dependencies_recorded_in_record",
                  test="TST-records_carry_their_dependencies-merge_s_plan_names_every_dependency")
def test_merge_s_plan_names_every_dependency(tmp_path, monkeypatch):
    """Merge's plan records every dependency its build lists, none of them empty."""
    ws, _lib, fp = _build_ws(tmp_path, [{"fp": "A", "dest": "Trip", "final_name": "a.jpg"}])
    _patch_fp(monkeypatch, fp)
    assert merge._run_locked_workflow("plan", str(ws)) == 0
    assert _missing(_depends_on(ws / ".photos-ingest", "photos-30-merge-plan.json"), MERGE_PLAN) == []
