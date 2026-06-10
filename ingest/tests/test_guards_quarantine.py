"""Phase 3b — band guard, nested-dump flattening, prune-quarantine, footprint.

Mocked hashing/metadata (content-based hash so identical files dedup), fast.
photos_1_prep / photos_utils come from conftest.py.
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
    def spy(p):
        with open(p, "rb") as f:
            return {"status": "valid", "strategy": "image-content-hash-v1",
                    "value": "sig-" + f.read().hex()[:16], "engine_version": "t"}
    monkeypatch.setattr(prep.ContentHasher, "fingerprint_image", spy)
    monkeypatch.setattr(prep.ContentHasher, "fingerprint_video",
                        lambda p: {"status": "valid", "strategy": "video-md5-v1", "value": "vsig"})

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


def _plan(ws):
    prep.CONFIG["jobs"] = 1
    return prep.WorkspacePrepWorkflow(str(ws), prep.WorkspaceCache(str(ws), in_memory=True)).plan()


def _seed_quarantine(ws):
    """Force a content duplicate so one copy is quarantined under a <plan_id> dir."""
    (ws / "0-sources" / "dup1.jpg").write_bytes(b"SAME")
    (ws / "0-sources" / "dup2.jpg").write_bytes(b"SAME")
    prep.PlanExecutor(str(ws)).execute(_plan(ws))
    qbase = utils.quarantine_dir(str(ws))
    pids = [e.name for e in os.scandir(qbase) if e.is_dir()]
    assert pids, "expected a quarantine plan-id dir"
    return pids[0]


# --- band-misplacement guard -------------------------------------------------

def test_band_guard_blocks_video_under_photo_band(tmp_path, monkeypatch):
    _mock(monkeypatch)
    ws = _ws(tmp_path)
    (ws / "5-photos-by-date" / "x.mp4").write_bytes(b"vid")
    plan = _plan(ws)
    assert any("Band misplacement" in b and "x.mp4" in b for b in plan.blockers), plan.blockers


def test_band_guard_blocks_raw_under_video_band(tmp_path, monkeypatch):
    _mock(monkeypatch)
    ws = _ws(tmp_path)
    (ws / "4-videos-by-date" / "x.arw").write_bytes(b"raw")
    plan = _plan(ws)
    assert any("Band misplacement" in b and "x.arw" in b for b in plan.blockers), plan.blockers


def test_band_guard_allows_correct_placement(tmp_path, monkeypatch):
    _mock(monkeypatch)
    ws = _ws(tmp_path)
    (ws / "5-photos-by-date" / "p.jpg").write_bytes(b"img")
    (ws / "4-videos-by-date" / "v.mp4").write_bytes(b"vid")
    plan = _plan(ws)
    assert not any("Band misplacement" in b for b in plan.blockers), plan.blockers


# (nested-dump flattening removed in Phase B: the new model does NOT flatten — an initialized
# workspace blocks a root dump, and an uninitialized one init-moves it into 0-sources with its
# structure preserved. Those paths are covered by test_lifecycle.py.)


# --- prune-quarantine --------------------------------------------------------

def test_prune_dry_run_deletes_nothing(tmp_path, monkeypatch):
    _mock(monkeypatch)
    ws = _ws(tmp_path)
    pid = _seed_quarantine(ws)
    prep.prune_quarantine(str(ws), do_delete=False)
    assert os.path.isdir(os.path.join(utils.quarantine_dir(str(ws)), pid))


def test_prune_yes_with_plan_id_deletes_only_that(tmp_path, monkeypatch):
    _mock(monkeypatch)
    ws = _ws(tmp_path)
    pid = _seed_quarantine(ws)
    qbase = utils.quarantine_dir(str(ws))
    prep.prune_quarantine(str(ws), plan_ids=[pid], do_delete=True)
    assert not os.path.exists(os.path.join(qbase, pid))


def test_prune_yes_without_selector_or_all_refuses(tmp_path, monkeypatch):
    _mock(monkeypatch)
    ws = _ws(tmp_path)
    pid = _seed_quarantine(ws)
    with pytest.raises(RuntimeError, match="Refusing to delete all quarantine"):
        prep.prune_quarantine(str(ws), do_delete=True)
    assert os.path.isdir(os.path.join(utils.quarantine_dir(str(ws)), pid))  # untouched


# --- footprint ---------------------------------------------------------------

def test_footprint_reports_quarantine(tmp_path, monkeypatch):
    _mock(monkeypatch)
    ws = _ws(tmp_path)
    _seed_quarantine(ws)
    qf = _plan(ws).summary["quarantine_footprint"]
    assert qf["plan_id_dirs"] >= 1
    assert qf["total_files"] >= 1
    assert qf["total_bytes"] > 0
    assert qf["oldest_plan_id"] and qf["newest_plan_id"]


# --- quarantine manifest: never silently truncate recoverable history (prep §15) -------------

def test_quarantine_manifest_corruption_is_preserved_not_truncated(tmp_path):
    """A corrupt manifest.json must be preserved under a .corrupt backup (so the prior records stay
    recoverable), not silently overwritten with a fresh single-entry file."""
    mdir = tmp_path / ".photos-ingest-quarantine" / "plan-x"
    mdir.mkdir(parents=True)
    (mdir / "manifest.json").write_text("{ this is not valid json")          # corrupt
    prep._append_quarantine_manifest(str(mdir), {"operation_id": "op-2", "original_path": "b.jpg"})

    backups = list(mdir.glob("manifest.json.corrupt-*"))
    assert len(backups) == 1
    assert backups[0].read_text() == "{ this is not valid json"               # corrupt bytes kept
    assert json.loads((mdir / "manifest.json").read_text()) == \
        [{"operation_id": "op-2", "original_path": "b.jpg"}]                  # fresh, valid manifest


def test_quarantine_manifest_appends_preserving_history(tmp_path):
    """The normal path keeps appending; a valid manifest is never backed up."""
    mdir = tmp_path / "qd"; mdir.mkdir()
    prep._append_quarantine_manifest(str(mdir), {"operation_id": "op-1"})
    prep._append_quarantine_manifest(str(mdir), {"operation_id": "op-2"})
    entries = json.loads((mdir / "manifest.json").read_text())
    assert [e["operation_id"] for e in entries] == ["op-1", "op-2"]           # history intact
    assert not list(mdir.glob("*.corrupt-*"))


def test_quarantine_manifest_non_array_is_treated_as_corrupt(tmp_path):
    """A syntactically-valid manifest that is not a JSON array (e.g. hand-edited to an object) is
    also preserved rather than crashing the append."""
    mdir = tmp_path / "qd"; mdir.mkdir()
    (mdir / "manifest.json").write_text('{"oops": "object not array"}')
    prep._append_quarantine_manifest(str(mdir), {"operation_id": "op-1"})
    assert len(list(mdir.glob("manifest.json.corrupt-*"))) == 1
    assert json.loads((mdir / "manifest.json").read_text()) == [{"operation_id": "op-1"}]
