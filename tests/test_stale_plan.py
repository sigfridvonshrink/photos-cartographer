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

"""Phase 4a — stale-plan rejection at execute.

A plan must be rejected before any mutation if the workspace config changed since
planning (prep Section 21) or the plan schema/version differs (Section 14.3.2).

Mocked hashing/metadata, fast. photos_1_prep / photos_utils come from conftest.py.
"""
import json
import os

import pytest

import photos_1_prep as prep
import photos_utils as utils


def _ws(tmp_path):
    ws = tmp_path / "ws"
    ws.mkdir()
    for d in ("0-sources", "1-strays", "2-missing-metadata", "3-redundant-jpgs",
              "4-videos-by-date", "5-photos-by-date", "6-photos-by-dest"):
        (ws / d).mkdir()
    (ws / ".photos-ingest").mkdir(exist_ok=True)
    (ws / ".photos-ingest" / "photos-00-workspace-guard").touch()
    return ws


def _mock(monkeypatch):
    monkeypatch.setattr(
        prep.ContentHasher, "fingerprint_image",
        lambda p: {"status": "valid", "strategy": "image-content-hash-v1",
                   "value": "sig-" + os.path.basename(p), "engine_version": "t"},
    )

    def meta(folders, max_workers=4, progress_coordinator=None):
        res = {}
        for folder in folders:
            for f in os.listdir(folder):
                res[os.path.join(folder, f)] = {
                    "DateTimeOriginal": "2023:01:02 03:04:05",
                    "extraction_status": "extracted_ok",
                }
        return res, set()
    monkeypatch.setattr(utils.MetadataReader, "read_metadata_concurrently", meta)


def _build_plan(ws):
    prep.CONFIG["jobs"] = 1
    cache = prep.WorkspaceCache(str(ws))
    plan = prep.WorkspacePrepWorkflow(str(ws), cache).plan()
    cache.close()
    return plan


@pytest.mark.spec("RUL-any_config_change_replans", test="TST-stale_plan-config_change_rejects_plan_at_execute")
def test_config_change_rejects_plan_at_execute(tmp_path, monkeypatch):
    _mock(monkeypatch)
    ws = _ws(tmp_path)
    (ws / "0-sources" / "a.jpg").write_bytes(b"AAAA")
    plan = _build_plan(ws)

    # Hand-edit the workspace config after planning.
    cfg = utils.config_path(str(ws))
    data = json.load(open(cfg))
    data["filename_timestamp_format"] = "%Y%m%d"
    with open(cfg, "w") as f:
        json.dump(data, f)

    with pytest.raises(ValueError, match="config changed"):
        prep.PlanExecutor(str(ws)).execute(plan)
    # No mutation: the source is still in 0-sources.
    assert os.path.exists(ws / "0-sources" / "a.jpg")


def test_plan_version_mismatch_rejected(tmp_path, monkeypatch):
    _mock(monkeypatch)
    ws = _ws(tmp_path)
    (ws / "0-sources" / "a.jpg").write_bytes(b"AAAA")
    plan = _build_plan(ws)
    plan.plan_version = 99
    with pytest.raises(ValueError, match="plan_version"):
        prep.PlanExecutor(str(ws)).execute(plan)


def test_unchanged_config_executes(tmp_path, monkeypatch):
    _mock(monkeypatch)
    ws = _ws(tmp_path)
    (ws / "0-sources" / "a.jpg").write_bytes(b"AAAA")
    plan = _build_plan(ws)
    prep.PlanExecutor(str(ws)).execute(plan)  # same config it was built from -> passes
    assert list(os.scandir(ws / "5-photos-by-date")), "the file should have been organized"


@pytest.mark.spec("RUL-new_file_restales_plan", test="TST-stale_plan-new_file_since_planning_rejects_plan")
@pytest.mark.parametrize("rel", ["0-sources/b.jpg", "0-sources/sub/b.jpg", "0-sources/.DS_Store",
                                 "5-photos-by-date/2023-01-02/b.jpg", "6-photos-by-dest/Rome/b.jpg"])
def test_new_file_since_planning_rejects_plan(tmp_path, monkeypatch, rel):
    """Prep §14.3 item 2: a file that appears anywhere prep scans between plan and execute is unplanned,
    so the plan is stale — refused before any mutation, the planned file and the newcomer left in place."""
    _mock(monkeypatch)
    ws = _ws(tmp_path)
    (ws / "0-sources" / "a.jpg").write_bytes(b"AAAA")
    plan = _build_plan(ws)
    assert not plan.blockers, plan.blockers
    (ws / rel).parent.mkdir(parents=True, exist_ok=True)
    (ws / rel).write_bytes(b"BBBB")
    with pytest.raises(ValueError, match=r"appeared since planning \(" + rel.replace(".", r"\.")):
        prep.PlanExecutor(str(ws)).execute(plan)
    assert os.path.exists(ws / "0-sources" / "a.jpg")
    assert os.path.exists(ws / rel)


@pytest.mark.spec("RUL-new_file_restales_plan", test="TST-stale_plan-track_file_since_planning_rejects_plan")
def test_track_file_since_planning_rejects_plan(tmp_path, monkeypatch):
    """A track dropped in after planning is refused like at planning: the rescan blocks on it."""
    _mock(monkeypatch)
    ws = _ws(tmp_path)
    (ws / "0-sources" / "a.jpg").write_bytes(b"AAAA")
    plan = _build_plan(ws)
    (ws / "0-sources" / "t.gpx").write_text("<gpx/>")
    with pytest.raises(ValueError, match="Track file in the workspace: 0-sources/t.gpx"):
        prep.PlanExecutor(str(ws)).execute(plan)
    assert os.path.exists(ws / "0-sources" / "t.gpx")


@pytest.mark.spec("RUL-new_file_restales_plan", "RUL-plan_memo_kept", "RUL-reuse_valid_work",
                  test="TST-stale_plan-replan_incorporates_new_file_reading_only_it")
def test_replan_incorporates_new_file_reading_only_it(tmp_path, monkeypatch):
    """After the refusal a new plan takes the newcomer in, fingerprinting only it: the refused plan's
    fingerprints are reused from the memo (prep §10.3). Metadata is read a folder at a time, so a file
    is re-read only when it shares a folder with one that needs reading; here they are apart."""
    _mock(monkeypatch)
    monkeypatch.setattr(utils, "get_imagemagick_version", lambda: "t")   # match the mock's engine_version
    read, hashed = [], []
    meta = utils.MetadataReader.read_metadata_concurrently

    def spy_meta(folders, max_workers=4, progress_coordinator=None):
        res, failed = meta(folders, max_workers, progress_coordinator)
        read.extend(os.path.basename(p) for p in res)
        return res, failed
    monkeypatch.setattr(utils.MetadataReader, "read_metadata_concurrently", spy_meta)
    fp = prep.ContentHasher.fingerprint_image
    monkeypatch.setattr(prep.ContentHasher, "fingerprint_image",
                        lambda p: (hashed.append(os.path.basename(p)), fp(p))[1])

    ws = _ws(tmp_path)
    (ws / "0-sources" / "trip1").mkdir()
    (ws / "0-sources" / "trip1" / "a.jpg").write_bytes(b"AAAA")
    plan = _build_plan(ws)
    (ws / "0-sources" / "trip2").mkdir()
    (ws / "0-sources" / "trip2" / "b.jpg").write_bytes(b"BBBB")
    with pytest.raises(ValueError, match="appeared since planning"):
        prep.PlanExecutor(str(ws)).execute(plan)

    read.clear(); hashed.clear()
    plan = _build_plan(ws)
    assert "0-sources/trip2/b.jpg" in plan.inventory
    assert read == ["b.jpg"] and hashed == ["b.jpg"]
    prep.PlanExecutor(str(ws)).execute(plan)
    assert not os.listdir(ws / "0-sources")


@pytest.mark.spec("RUL-plan_carried_out_by_its_code", "BLD-code_fingerprint",
                  test="TST-stale_plan-a_plan_made_by_other_code_is_refused")
def test_a_plan_made_by_other_code_is_refused(tmp_path, monkeypatch):
    """A saved plan records the code that made it; execute refuses it once the code differs — or when it
    records none — before any change."""
    _mock(monkeypatch)
    ws = _ws(tmp_path)
    (ws / "0-sources" / "a.jpg").write_bytes(b"AAAA")
    plan = _build_plan(ws)
    assert plan.code_fingerprint == utils.code_fingerprint()
    for recorded in ("0" * 64, ""):
        plan.code_fingerprint = recorded
        with pytest.raises(ValueError, match="another build"):
            prep.PlanExecutor(str(ws)).execute(plan)
        assert (ws / "0-sources" / "a.jpg").exists()


@pytest.mark.spec("RUL-journal_never_torn", "BLD-prep_journal",
                  test="TST-stale_plan-a_failed_journal_save_leaves_the_last_one_whole")
def test_a_failed_journal_save_leaves_the_last_one_whole(tmp_path, monkeypatch):
    """The journal is replaced whole: a save that fails partway leaves the journal as the previous save
    wrote it."""
    path = tmp_path / "journal.json"
    jw = prep.JournalWriter(str(path))
    jw.start_journal("p1")
    before = path.read_text()
    real_replace = os.replace
    monkeypatch.setattr(os, "replace", lambda *a: (_ for _ in ()).throw(OSError("disk full")))
    with pytest.raises(OSError):
        jw.finish_journal("success")
    monkeypatch.setattr(os, "replace", real_replace)
    assert path.read_text() == before and json.loads(before)["status"] == "started"
    assert [p.name for p in tmp_path.iterdir()] == ["journal.json"]          # no temporary left


@pytest.mark.spec("BLD-code_fingerprint", test="TST-stale_plan-the_build_and_its_checkout_have_one_fingerprint")
def test_the_build_and_its_checkout_have_one_fingerprint(tmp_path):
    """The code's fingerprint is the same whether the package runs from its checkout or from the zipapp
    built from it, and changes with any file the zipapp ships."""
    import importlib.util, subprocess, sys
    from importlib.machinery import SourceFileLoader
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    loader = SourceFileLoader("build_pyz", os.path.join(root, "tools", "build-pyz"))
    build = importlib.util.module_from_spec(importlib.util.spec_from_loader("build_pyz", loader))
    loader.exec_module(build)
    pyz = tmp_path / "pc.pyz"
    pyz.write_bytes(build.build_pyz_bytes())
    probe = "import sys; sys.path.insert(0, sys.argv[1]); from cartographer.photos_utils import code_fingerprint; print(code_fingerprint())"
    run = lambda path: subprocess.run([sys.executable, "-c", probe, path], capture_output=True, text=True,
                                      check=True, cwd=tmp_path).stdout.strip()
    assert run(str(pyz)) == run(root) == utils.code_fingerprint()
    pyz.write_bytes(build.build_pyz_bytes(version="9.9.9"))
    assert run(str(pyz)) != utils.code_fingerprint()
