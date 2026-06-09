"""Phase B2 — strays routing (non-media out of 0-sources into 1-strays).

Non-media (other-class) is never fingerprinted/deduped (§9); it is moved inert into
1-strays/<plan-id>/<rel> with its structure preserved (§3.2/§7.6), untracked and scan-skipped,
so 0-sources is left empty. Mocked hashing/metadata, fast. From conftest.py.
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


def _plan(ws):
    cache = prep.WorkspaceCache(str(ws))
    plan = prep.WorkspacePrepWorkflow(str(ws), cache).plan()
    cache.close()
    return plan


def _run(ws):
    plan = _plan(ws)
    prep.PlanExecutor(str(ws)).execute(plan)
    return plan


def _cached_paths(ws):
    conn = sqlite3.connect(str(ws / ".photos-ingest" / "photos-00-ingest.db"))
    try:
        return {r[0] for r in conn.execute("SELECT relative_path FROM file_cache")}
    finally:
        conn.close()


def test_stray_moved_structure_preserved(tmp_path, monkeypatch):
    _install(monkeypatch)
    ws = _ws(tmp_path)
    (ws / "0-sources" / "notes.txt").write_bytes(b"hello")
    (ws / "0-sources" / "sub").mkdir()
    (ws / "0-sources" / "sub" / "readme.md").write_bytes(b"yo")
    plan = _plan(ws)
    assert not plan.blockers, plan.blockers                       # absence of fingerprint never blocks
    dests = {op.source: op.destination for op in plan.operations
             if op.reason and "stray" in op.reason}
    assert dests["0-sources/notes.txt"].endswith("/notes.txt")
    assert dests["0-sources/sub/readme.md"].endswith("/sub/readme.md")   # structure preserved
    _run(ws)
    assert glob.glob(str(ws / "1-strays" / "*" / "notes.txt"))
    assert glob.glob(str(ws / "1-strays" / "*" / "sub" / "readme.md"))
    assert list((ws / "0-sources").iterdir()) == []               # inbox left empty


def test_stray_not_fingerprinted_and_not_cached(tmp_path, monkeypatch):
    # If fingerprint_image were called on the stray it would raise (so we'd notice).
    _install(monkeypatch)
    boom = {"n": 0}
    orig = prep.ContentHasher.fingerprint_image

    def spy(p):
        if p.endswith("notes.txt"):
            boom["n"] += 1
        return orig(p)
    monkeypatch.setattr(prep.ContentHasher, "fingerprint_image", spy)

    ws = _ws(tmp_path)
    (ws / "0-sources" / "notes.txt").write_bytes(b"hello")
    (ws / "0-sources" / "real.jpg").write_bytes(b"img")
    _run(ws)
    assert boom["n"] == 0                                         # never fingerprinted
    cached = _cached_paths(ws)
    assert not any("notes.txt" in p for p in cached)             # not tracked in the cache
    assert any("5-photos-by-date" in p for p in cached)          # the real photo is


def test_strays_scan_skipped_on_next_run(tmp_path, monkeypatch):
    _install(monkeypatch)
    ws = _ws(tmp_path)
    (ws / "0-sources" / "notes.txt").write_bytes(b"hello")
    _run(ws)                                                      # stray now lives in 1-strays/<id>/
    landed = glob.glob(str(ws / "1-strays" / "*" / "notes.txt"))[0]
    plan2 = _plan(ws)                                             # next run
    assert not plan2.blockers                                    # 1-strays is not a misplaced dump
    assert not any("1-strays" in (op.source or "") or "1-strays" in (op.destination or "")
                   for op in plan2.operations)                   # nothing touches the strays tree
    assert os.path.exists(landed)                                # the stray is left untouched


def test_mixed_media_and_stray(tmp_path, monkeypatch):
    _install(monkeypatch)
    ws = _ws(tmp_path)
    (ws / "0-sources" / "photo.jpg").write_bytes(b"img")
    (ws / "0-sources" / "notes.txt").write_bytes(b"hello")
    _run(ws)
    assert len(glob.glob(str(ws / "5-photos-by-date" / "*.jpg"))) == 1
    assert glob.glob(str(ws / "1-strays" / "*" / "notes.txt"))
    assert list((ws / "0-sources").iterdir()) == []
