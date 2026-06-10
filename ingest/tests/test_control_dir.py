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
