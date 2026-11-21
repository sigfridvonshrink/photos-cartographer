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

"""What a plan tells and where it stops: prep's summary with each plan, a link that leaves no plan behind, and the
remedy for a missing managed folder wherever one is blocked. Prep runs for real, its fingerprint and metadata reading
stood in for, as in test_workspace_check."""
import os

import pytest

import photos_3_merge as merge
import photos_utils as utils
from test_merge_preflight import _make
from test_workspace_check import _fresh, _prep


@pytest.mark.spec("RUL-prep_run_summarised", "BLD-prep_run_report",
                  test="TST-plan_told_and_stopped-prep_reports_its_summary_with_each_plan")
def test_prep_reports_its_summary_with_each_plan(tmp_path, monkeypatch):
    """`prep plan` prints its summary, not only saves it: what it would change apart from what it only read, without
    the lines that tell what an execution applied and wrote (the execution's own report is test_report's)."""
    ws = _fresh(monkeypatch, tmp_path)
    (ws / "0-sources" / "d.jpg").write_bytes(b"DDDD")
    rc, said, _ = _prep(monkeypatch, ws, "plan")
    assert rc == 0, said
    assert "=== Prep plan summary ===" in said and "Media operations planned" in said
    for told in ("No-op / already-correct", "Recognized moves", "By-dest files scanned read-only",
                 "Duplicates -> quarantine", "Metadata reused/extracted/carried/failed", "Blockers / warnings"):
        assert told in said, told
    for of_an_execution in ("Cache effects applied", "Dependency validation", "End-of-prep audit record"):
        assert of_an_execution not in said, of_an_execution


@pytest.mark.spec("RUL-link_block_produces_nothing", "RUL-link_named", "BLD-link_blocks_before_records",
                  test="TST-plan_told_and_stopped-a_link_below_the_top_level_leaves_no_plan")
def test_a_link_below_the_top_level_leaves_no_plan(tmp_path, monkeypatch):
    """A link inside the inbox stops `prep plan`, named: no plan is saved — the earlier one stays as it was, none set
    aside — and nothing else is written, the plan memo among it."""
    ws = _fresh(monkeypatch, tmp_path)
    (ws / "0-sources" / "d.jpg").write_bytes(b"DDDD")
    ctl = ws / ".photos-ingest"
    (tmp_path / "outside.jpg").write_bytes(b"OUT")
    os.symlink(str(tmp_path / "outside.jpg"), str(ws / "0-sources" / "link.jpg"))

    def state():
        return {n: (os.stat(ctl / n).st_size, os.stat(ctl / n).st_mtime_ns) for n in sorted(os.listdir(ctl))
                if not n.endswith(".lock")}
    before = state()
    rc, said, _ = _prep(monkeypatch, ws, "plan")
    assert rc == 2 and "No plan was saved" in said and "0-sources/link.jpg" in said, said
    assert state() == before                                         # no plan, no copy set aside, no memo
    (ws / "0-sources" / "link.jpg").unlink()
    rc, said, _ = _prep(monkeypatch, ws, "plan")
    assert rc == 0 and state() != before, said                       # the link gone, the plan is made and saved


@pytest.mark.spec("RUL-missing_folder_remedy_told", "BLD-missing_folder_check",
                  test="TST-plan_told_and_stopped-prep_execute_tells_to_restore_a_folder_gone_since_the_plan")
def test_prep_execute_tells_to_restore_a_folder_gone_since_the_plan(tmp_path, monkeypatch):
    """A managed folder removed after the plan was made: the execute that stops on it tells the user to restore it
    and plan again, as the plan's own block does."""
    import photos_1_prep as prep
    ws = _fresh(monkeypatch, tmp_path)
    (ws / "0-sources" / "d.jpg").write_bytes(b"DDDD")
    rc, said, _ = _prep(monkeypatch, ws, "plan")
    assert rc == 0, said
    plan = prep.Plan.from_dict(__import__("json").load(open(utils.prep_plan_path(str(ws)))))
    (ws / "2-missing-metadata").rmdir()
    with pytest.raises(ValueError) as stop:
        prep.PlanValidator.validate_plan_preflight(plan, str(ws))
    assert "2-missing-metadata" in str(stop.value) and "Restore them" in str(stop.value), str(stop.value)
    assert "run `prep plan` again" in str(stop.value)


@pytest.mark.spec("RUL-missing_folder_remedy_told", "BLD-missing_folder_check",
                  test="TST-plan_told_and_stopped-init_library_tells_to_restore_a_missing_folder")
def test_init_library_tells_to_restore_a_missing_folder(tmp_path):
    """`merge init-library` refusing a workspace with a managed folder missing tells the user to restore it and run
    again."""
    ws, _ = _make(tmp_path)
    (ws / "1-strays").rmdir()
    told = []
    reporter = type("R", (), {"error": lambda self, m, **k: told.append(m), "log": lambda self, m, **k: told.append(m)})()
    assert merge._shape_refusal(str(ws), reporter) is True
    assert "1-strays" in told[0] and "Restore the missing folder(s)" in told[0] and "run again" in told[0], told
