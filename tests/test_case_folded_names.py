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

"""Two names that differ only in case are one name, on every filesystem (BLD-names_case_folded): prep's execute,
geotag's renames — merge's placements are in test_merge_plan — on the case-sensitive filesystem the tests run on.

photos_utils / photos_1_prep / photos_2_geotag come from conftest.py.
"""
import os

import pytest

import photos_utils as utils
import photos_1_prep as prep
import photos_2_geotag as cal

MANAGED = ["0-sources", "1-strays", "2-missing-metadata", "3-redundant-jpgs",
           "4-videos-by-date", "5-photos-by-date", "6-photos-by-dest"]


def _case_sensitive(d):
    probe = d / "Probe"
    probe.write_bytes(b"")
    try:
        return not os.path.exists(d / "probe")
    finally:
        probe.unlink()


@pytest.mark.spec("BLD-names_case_folded", "RUL-target_free_ignores_case",
                  test="TST-case_folded_names-prep_refuses_a_move_onto_a_name_taken_in_another_case")
def test_prep_refuses_a_move_onto_a_name_taken_in_another_case(tmp_path):
    """On a filesystem that tells `x.jpg` from `X.JPG`, prep's execute still refuses a move onto `X.JPG` while
    `x.jpg` is there, before it changes anything."""
    ws = tmp_path / "ws"
    ws.mkdir()
    assert _case_sensitive(ws)
    (ws / ".photos-ingest").mkdir()
    (ws / ".photos-ingest" / "photos-00-workspace-guard").touch()
    for d in MANAGED:
        (ws / d).mkdir()
    (ws / "0-sources" / "new.jpg").write_bytes(b"a photo")
    (ws / "5-photos-by-date" / "x.jpg").write_bytes(b"another photo")
    cfg_sha = utils.load_or_seed_config(str(ws))
    plan = prep.Plan(
        plan_version=prep.PLAN_SCHEMA_VERSION, code_fingerprint=prep.code_fingerprint(), plan_id="p",
        command="prep", created_at="now", workspace_root=str(ws),
        config_fingerprint=prep.Fingerprint("sha256", cfg_sha), summary={}, blockers=[], warnings=[],
        metadata_dependencies=prep.current_metadata_dependencies(),
        operations=[prep.Operation(operation_id="op-1", type="move_no_clobber", reason="test",
                                   source="0-sources/new.jpg", destination="5-photos-by-date/X.JPG",
                                   preconditions={}, verification={}, database_effects_after_verification=[])])
    with pytest.raises(ValueError, match="case-insensitive clobber risk"):
        prep.PlanValidator.validate_plan_preflight(plan, str(ws))
    assert sorted(os.listdir(ws / "5-photos-by-date")) == ["x.jpg"]


@pytest.mark.spec("BLD-names_case_folded", "RUL-suffix_case_insensitive",
                  test="TST-case_folded_names-geotag_never_plans_two_names_that_differ_only_in_case")
def test_geotag_never_plans_two_names_that_differ_only_in_case():
    """Geotag's rename planning asks nothing of the filesystem: a photo's name taken in another case by another's
    gives it a suffix, wherever the workspace lies."""
    def f(rel, utc):
        return {"relative_path": rel, "resolved_utc": utc, "destination_timezone": "Europe/Brussels"}
    fmt = utils.CONFIG["filename_timestamp_format"]
    rows = cal.plan_renames([f("6-photos-by-dest/T/2024-07-03--14-00-00.JPG", None),
                             f("6-photos-by-dest/T/b.jpg", "2024-07-03T12:00:00Z")], fmt)
    planned = {r["current_name"]: r["planned_name"] for r in rows}
    assert planned["b.jpg"].lower() == "2024-07-03--14-00-00-001.jpg", planned
