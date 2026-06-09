"""Phase C1 — end-of-prep DB backup snapshot (photos-15-prep-ingest.db, shared §13.4a).

A transactionally-consistent image of the live cache, captured at the handoff gate, written
atomically. Mocked hashing/metadata, fast. From conftest.py.
"""
import glob
import os
import sqlite3

import photos_1_prep as prep
import photos_utils as utils

MANAGED = ["0-sources", "1-strays", "2-missing-metadata", "3-redundant-jpgs",
           "4-videos-by-date", "5-photos-by-date", "6-photos-by-dest"]


def _ws(tmp_path):
    ws = tmp_path / "ws"
    ws.mkdir()
    for d in MANAGED:
        (ws / d).mkdir()
    (ws / ".photos-ingest").mkdir()
    (ws / ".photos-ingest" / "photos-00-workspace-guard").touch()
    return ws


def _install(monkeypatch):
    prep.CONFIG["zfs"] = {"enabled": False}
    prep.CONFIG["jobs"] = 1

    def hsh(p):
        with open(p, "rb") as f:
            return {"status": "valid", "strategy": "image-content-hash-v1",
                    "value": "sig-" + f.read().hex()[:16], "engine_version": "t"}
    monkeypatch.setattr(prep.ContentHasher, "fingerprint_image", hsh)

    def meta(folders, max_workers=4, progress_coordinator=None):
        res = {}
        for fo in folders:
            for fn in os.listdir(fo):
                res[os.path.join(fo, fn)] = {"DateTimeOriginal": "2023:01:02 03:04:05",
                                             "extraction_status": "extracted_ok", "raw_payload": "{}"}
        return res, set()
    monkeypatch.setattr(utils.MetadataReader, "read_metadata_concurrently", meta)


def _run(ws):
    cache = prep.WorkspaceCache(str(ws))
    plan = prep.WorkspacePrepWorkflow(str(ws), cache).plan()
    cache.close()
    prep.PlanExecutor(str(ws)).execute(plan)


def _snap(ws):
    return utils.prep_db_snapshot_path(str(ws))


def test_snapshot_written_and_matches_live_cache(tmp_path, monkeypatch):
    _install(monkeypatch)
    ws = _ws(tmp_path)
    (ws / "0-sources" / "a.jpg").write_bytes(b"AAAA")
    _run(ws)
    assert os.path.exists(_snap(ws))
    # valid SQLite whose file_cache matches the live DB
    live = sqlite3.connect(utils.db_path(str(ws)))
    snap = sqlite3.connect(_snap(ws))
    live_rows = sorted(live.execute("SELECT relative_path, content_hash FROM file_cache"))
    snap_rows = sorted(snap.execute("SELECT relative_path, content_hash FROM file_cache"))
    assert snap_rows == live_rows and len(snap_rows) >= 1


def test_snapshot_leaves_no_temp_and_refreshes_on_rerun(tmp_path, monkeypatch):
    _install(monkeypatch)
    ws = _ws(tmp_path)
    (ws / "0-sources" / "a.jpg").write_bytes(b"AAAA")
    _run(ws)
    first = os.path.getmtime(_snap(ws))
    assert not glob.glob(str(ws / ".photos-ingest" / ".tmp-snapshot*"))   # atomic, no temp left
    (ws / "0-sources" / "b.jpg").write_bytes(b"BBBB")                     # new media -> a real second run
    _run(ws)
    snap = sqlite3.connect(_snap(ws))
    rows = [r[0] for r in snap.execute("SELECT relative_path FROM file_cache")]
    assert sum(p.startswith("5-photos-by-date/") for p in rows) == 2     # snapshot refreshed
    assert not glob.glob(str(ws / ".photos-ingest" / ".tmp-snapshot*"))


def test_failed_run_leaves_prior_snapshot_intact(tmp_path, monkeypatch):
    _install(monkeypatch)
    ws = _ws(tmp_path)
    (ws / "0-sources" / "a.jpg").write_bytes(b"AAAA")
    _run(ws)
    assert os.path.exists(_snap(ws))
    before = open(_snap(ws), "rb").read()
    # A second plan whose execution fails after planning must not overwrite the snapshot.
    (ws / "0-sources" / "b.jpg").write_bytes(b"BBBB")
    cache = prep.WorkspaceCache(str(ws))
    plan = prep.WorkspacePrepWorkflow(str(ws), cache).plan()
    cache.close()
    monkeypatch.setattr(prep, "_move_no_clobber",
                        lambda *a, **k: (_ for _ in ()).throw(RuntimeError("boom")))
    try:
        prep.PlanExecutor(str(ws)).execute(plan)
    except Exception:
        pass
    assert open(_snap(ws), "rb").read() == before   # prior snapshot untouched
