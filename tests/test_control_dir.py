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

"""Phase 1 — control-directory layout.

Verifies that every pipeline control/artifact file lands under `.photos-ingest/`
with the spec names, that journals are per-run and retained, that the media scan
skips the control directory wholesale, and that the workspace guard is enforced.

Uses mocked hashing/metadata so these are fast and need no external tools.
photos_1_prep / photos_utils are loaded once by conftest.py into sys.modules.
"""
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
                    "extraction_status": "extracted_ok", "raw_payload": "{}",
                }
        return res, set()

    monkeypatch.setattr(utils.MetadataReader, "read_metadata_concurrently", meta)


@pytest.mark.spec("config-in-control-dir-skipped-1", "ctrl-all-in-photos-ingest-1", "plan-canonical-path-1")
def test_control_files_land_under_control_dir(tmp_path, monkeypatch):
    _mock(monkeypatch)
    ws = _ws(tmp_path)
    (ws / "0-sources" / "a.jpg").write_text("aaa")
    prep.CONFIG["jobs"] = 1

    cache = prep.WorkspaceCache(str(ws))
    plan = prep.WorkspacePrepWorkflow(str(ws), cache).plan()
    cache.close()
    prep.PlanExecutor(str(ws)).execute(plan)  # no journal arg -> default control-dir location

    assert os.path.exists(utils.db_path(str(ws)))          # .photos-ingest/photos-00-ingest.db
    assert os.path.exists(utils.handoff_path(str(ws)))     # .photos-ingest/photos-11-handoff.json
    assert os.path.exists(utils.journal_path(str(ws), plan.plan_id))  # .photos-ingest/journal-<id>.json

    # Nothing pipeline-related sits at the workspace root.
    root_entries = set(os.listdir(str(ws)))
    assert ".photos_ingest.db" not in root_entries
    assert "photos-11-handoff.json" not in root_entries
    assert not any(e.endswith(".photos-ingest/journal.json") or e.startswith("journal") for e in root_entries)


@pytest.mark.spec("log-retention-across-runs-1")
def test_journals_are_per_run_and_retained(tmp_path, monkeypatch):
    _mock(monkeypatch)
    ws = _ws(tmp_path)
    (ws / "0-sources" / "a.jpg").write_text("aaa")
    prep.CONFIG["jobs"] = 1

    p1 = prep.WorkspacePrepWorkflow(str(ws), prep.WorkspaceCache(str(ws))).plan()
    prep.PlanExecutor(str(ws)).execute(p1)
    p2 = prep.WorkspacePrepWorkflow(str(ws), prep.WorkspaceCache(str(ws))).plan()
    prep.PlanExecutor(str(ws)).execute(p2)

    assert p1.plan_id != p2.plan_id
    # The first run's journal is not overwritten by the second.
    assert os.path.exists(utils.journal_path(str(ws), p1.plan_id))
    assert os.path.exists(utils.journal_path(str(ws), p2.plan_id))


@pytest.mark.spec("prep-sole-config-writer-1")
def test_prep_seeds_config_once_then_never_rewrites_it(tmp_path, monkeypatch):
    """§3.2: prep is the SOLE writer of photos-00-config.json and only SEEDS it once — it never edits
    it thereafter. After the first run seeds the config, a second prep run leaves the on-disk
    photos-00-config.json byte-for-byte identical (no rewrite, no reformat, no fingerprint churn)."""
    _mock(monkeypatch)
    ws = _ws(tmp_path)
    (ws / "0-sources" / "a.jpg").write_text("aaa")
    prep.CONFIG["jobs"] = 1
    cfg_p = ws / ".photos-ingest" / "photos-00-config.json"

    p1 = prep.WorkspacePrepWorkflow(str(ws), prep.WorkspaceCache(str(ws))).plan()
    prep.PlanExecutor(str(ws)).execute(p1)
    assert cfg_p.exists()                                            # seeded on the first run
    after_seed = cfg_p.read_bytes()

    (ws / "0-sources" / "b.jpg").write_text("bbb")                  # genuine new work for the 2nd run
    p2 = prep.WorkspacePrepWorkflow(str(ws), prep.WorkspaceCache(str(ws))).plan()
    prep.PlanExecutor(str(ws)).execute(p2)
    assert cfg_p.read_bytes() == after_seed                         # config never rewritten after seeding


def test_backup_existing_artifact_uses_incremental_suffix(tmp_path):
    """The shared backup primitive (used by every phase's canonical plan/decision save) renames a
    pre-existing artifact aside under the `-NNN` suffix and never clobbers it."""
    p = tmp_path / "photos-10-prep-plan.json"
    assert utils.backup_existing_artifact(str(p)) is None      # nothing to back up yet
    p.write_text('{"v": 1}')
    b1 = utils.backup_existing_artifact(str(p))
    assert os.path.basename(b1) == "photos-10-prep-plan-001.json"
    assert not p.exists() and os.path.exists(b1)               # moved aside, original byte-preserved
    p.write_text('{"v": 2}')
    b2 = utils.backup_existing_artifact(str(p))
    assert os.path.basename(b2) == "photos-10-prep-plan-002.json"   # second backup advances the index
    import json as _json
    assert _json.load(open(b1))["v"] == 1 and _json.load(open(b2))["v"] == 2


@pytest.mark.spec("plan-replan-no-clobber-1")
def test_write_versioned_json_backs_up_then_writes(tmp_path):
    p = tmp_path / "photos-30-merge-plan.json"
    sha1, bak1 = utils.write_versioned_json(str(p), {"plan": "a"})
    assert bak1 is None and sha1                               # first write: nothing to back up
    sha2, bak2 = utils.write_versioned_json(str(p), {"plan": "b"})
    assert os.path.basename(bak2) == "photos-30-merge-plan-001.json"
    import json as _json
    assert _json.load(open(p))["plan"] == "b"                  # canonical holds the new content
    assert _json.load(open(bak2))["plan"] == "a"              # prior content preserved in the backup


@pytest.mark.spec("ctrl-prep-skips-wholesale-1")
def test_media_inside_control_dir_is_not_inventoried(tmp_path, monkeypatch):
    _mock(monkeypatch)
    ws = _ws(tmp_path)
    (ws / ".photos-ingest" / "sneaky.jpg").write_text("x")  # must be skipped wholesale
    (ws / "0-sources" / "real.jpg").write_text("aaa")
    prep.CONFIG["jobs"] = 1

    plan = prep.WorkspacePrepWorkflow(str(ws), prep.WorkspaceCache(str(ws), in_memory=True)).plan()
    touched = [op.source for op in plan.operations if op.source] + \
              [op.destination for op in plan.operations if op.destination]
    assert not any("sneaky" in (p or "") for p in touched), touched
    assert plan.blockers == [], plan.blockers
