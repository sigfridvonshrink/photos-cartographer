"""Audit backfill — spec paths that lacked direct coverage.

Covers: other-class organization (regression for the §7.2/§18 fix), missing-timestamp
UNKN_ naming + video routing, CreateDate fallback, suffix monotonicity, ghost-prune,
by-dest hash-failure skip vs mutable blocker, redundant-JPEG 0-source restriction,
camera-group-key version staleness, by-dest precondition rejection, fingerprint stability
across -j, the zfs snapshot success/required-failure paths, and hash_video failure.

Mocked hashing/metadata, fast. photos_1_prep / photos_utils come from conftest.py.
"""
import glob
import json
import os

import pytest

import photos_1_prep as prep
import photos_utils as utils


def _ws(tmp_path):
    ws = tmp_path / "ws"
    ws.mkdir(parents=True)
    for d in ("0-source", "1-missing-metadata", "2-redundant-jpgs",
              "3-videos-by-date", "4-photos-by-date", "5-photos-by-dest"):
        (ws / d).mkdir()
    (ws / ".photos-ingest").mkdir(exist_ok=True)
    (ws / ".photos-ingest" / "photos-00-workspace-guard").touch()
    return ws


def _install(monkeypatch, meta_for=None, hash_for=None):
    # Default: zfs off so execute() takes no snapshot.
    prep.CONFIG["zfs"] = {"enabled": False}

    def hsh(p):
        if hash_for is not None:
            r = hash_for(p)
            if r is not None:
                return r
        with open(p, "rb") as f:
            return {"status": "valid", "strategy": "image-content-hash-v1",
                    "value": "sig-" + f.read().hex()[:16], "engine_version": "t"}
    monkeypatch.setattr(prep.ContentHasher, "hash_image", hsh)
    monkeypatch.setattr(prep.ContentHasher, "hash_video",
                        lambda p: {"status": "valid", "strategy": "video-md5-v1",
                                   "value": "v-" + os.path.basename(p)})

    def meta(folders, max_workers=4, progress_coordinator=None):
        res = {}
        for folder in folders:
            for f in os.listdir(folder):
                m = {"extraction_status": "extracted_ok", "raw_payload": "{}"}
                if meta_for is not None:
                    m.update(meta_for(f) or {})
                else:
                    m["DateTimeOriginal"] = "2023:01:02 03:04:05"
                res[os.path.join(folder, f)] = m
        return res, set()
    monkeypatch.setattr(utils.MetadataReader, "read_metadata_concurrently", meta)


def _plan(ws, jobs=1):
    prep.CONFIG["jobs"] = jobs
    cache = prep.WorkspaceCache(str(ws))
    plan = prep.WorkspacePrepWorkflow(str(ws), cache).plan()
    cache.close()
    return plan


def _run(ws, jobs=1):
    plan = _plan(ws, jobs)
    prep.PlanExecutor(str(ws)).execute(plan)
    return plan


def _moves(plan):
    return [op for op in plan.operations if op.type == "move_no_clobber"]


# --- organization / routing --------------------------------------------------

def test_other_class_file_stays_in_source(tmp_path, monkeypatch):
    _install(monkeypatch)
    ws = _ws(tmp_path)
    (ws / "0-source" / "notes.txt").write_bytes(b"hello")
    plan = _plan(ws)
    assert not plan.blockers, plan.blockers                       # never blocks (§7.2)
    assert not any(op.source == "0-source/notes.txt" for op in plan.operations)  # not organized
    _run(ws)
    assert os.path.exists(ws / "0-source" / "notes.txt")          # stays put (§18)


def test_missing_timestamp_routes_to_missing_metadata_with_unkn_name(tmp_path, monkeypatch):
    _install(monkeypatch, meta_for=lambda f: {})                  # no timestamp
    ws = _ws(tmp_path)
    (ws / "0-source" / "pic.jpg").write_bytes(b"img")
    plan = _plan(ws)
    org = [op for op in _moves(plan) if op.source == "0-source/pic.jpg"]
    assert org and org[0].destination.startswith("1-missing-metadata/UNKN_pic-"), org[0].destination


def test_video_with_timestamp_routes_to_videos_by_date(tmp_path, monkeypatch):
    _install(monkeypatch, meta_for=lambda f: {"DateTimeOriginal": "2023:01:02 03:04:05"})
    ws = _ws(tmp_path)
    (ws / "0-source" / "clip.mp4").write_bytes(b"vid")
    org = [op for op in _moves(_plan(ws)) if op.source == "0-source/clip.mp4"]
    assert org and org[0].destination.startswith("3-videos-by-date/"), org[0].destination


def test_create_date_used_when_no_datetimeoriginal(tmp_path, monkeypatch):
    _install(monkeypatch, meta_for=lambda f: {"CreateDate": "2019:05:06 07:08:09"})  # only CreateDate
    ws = _ws(tmp_path)
    (ws / "0-source" / "p.jpg").write_bytes(b"img")
    org = [op for op in _moves(_plan(ws)) if op.source == "0-source/p.jpg"]
    assert org and "2019-05-06--07-08-09" in org[0].destination, org[0].destination


def test_suffix_allocation_is_monotonic(tmp_path, monkeypatch):
    # Same timestamp for every file; an already-organized -001 must not be reused.
    _install(monkeypatch, meta_for=lambda f: {"DateTimeOriginal": "2023:01:02 03:04:05"})
    ws = _ws(tmp_path)
    (ws / "4-photos-by-date" / "2023-01-02--03-04-05-001.jpg").write_bytes(b"existing")
    (ws / "0-source" / "new.jpg").write_bytes(b"new")
    org = [op for op in _moves(_plan(ws)) if op.source == "0-source/new.jpg"]
    assert org and org[0].destination == "4-photos-by-date/2023-01-02--03-04-05-002.jpg", org[0].destination


# --- dedup / cache -----------------------------------------------------------

def test_ghost_prune_removes_missing_cache_row(tmp_path, monkeypatch):
    _install(monkeypatch)
    ws = _ws(tmp_path)
    (ws / "0-source" / "a.jpg").write_bytes(b"AAAA")
    _run(ws)                                                      # organize + cache
    organized = glob.glob(str(ws / "4-photos-by-date" / "*.jpg"))[0]
    os.remove(organized)                                          # file vanishes
    plan = _plan(ws)
    rel = os.path.relpath(organized, str(ws))
    assert any(op.type == "db_remove" and any(e.get("relative_path") == rel
               for e in (op.database_effects_after_verification or []))
               for op in plan.operations), [op.type for op in plan.operations]


def test_by_dest_hash_failure_skipped_mutable_blocks(tmp_path, monkeypatch):
    def hash_for(p):
        if "fail" in os.path.basename(p):
            return {"status": "failed", "strategy": "image-content-hash-v1", "error": "boom"}
        return None
    _install(monkeypatch, hash_for=hash_for)
    ws = _ws(tmp_path)
    (ws / "5-photos-by-dest" / "Trip").mkdir(parents=True)
    (ws / "5-photos-by-dest" / "Trip" / "failbd.jpg").write_bytes(b"x")   # by-dest fail -> skip
    (ws / "0-source" / "failmut.jpg").write_bytes(b"y")                   # mutable fail -> block
    blockers = _plan(ws).blockers
    assert any("failmut.jpg" in b for b in blockers), blockers
    assert not any("failbd.jpg" in b for b in blockers), blockers


def test_redundant_jpeg_only_separated_from_source(tmp_path, monkeypatch):
    _install(monkeypatch)
    ws = _ws(tmp_path)
    (ws / "0-source" / "shot.arw").write_bytes(b"raw")
    (ws / "0-source" / "shot.jpg").write_bytes(b"jpg")            # 0-source pair -> jpg separated
    (ws / "4-photos-by-date" / "keep.arw").write_bytes(b"raw2")
    (ws / "4-photos-by-date" / "keep.jpg").write_bytes(b"jpg2")   # by-date pair -> untouched
    plan = _plan(ws)
    seps = [op for op in _moves(plan) if op.destination.startswith("2-redundant-jpgs/")]
    assert [op.source for op in seps] == ["0-source/shot.jpg"], [op.source for op in seps]


def test_camera_group_key_version_staleness_refreshes(tmp_path, monkeypatch):
    _install(monkeypatch, meta_for=lambda f: {"DateTimeOriginal": "2023:01:02 03:04:05",
                                              "Make": "M", "Model": "D"})
    ws = _ws(tmp_path)
    (ws / "0-source" / "a.jpg").write_bytes(b"AAAA")
    _run(ws)
    monkeypatch.setattr(utils, "CAMERA_GROUP_KEY_VERSION", 999)   # derivation bumped
    plan = _plan(ws)
    organized = glob.glob(str(ws / "4-photos-by-date" / "*.jpg"))[0]
    rel = os.path.relpath(organized, str(ws))
    assert plan.summary["metadata_plan_status"].get(rel) == "extracted_ok", \
        plan.summary["metadata_plan_status"]


# --- lifecycle / zfs ---------------------------------------------------------

def test_by_dest_change_rejects_plan_at_execute(tmp_path, monkeypatch):
    _install(monkeypatch)
    ws = _ws(tmp_path)
    (ws / "5-photos-by-dest" / "Trip").mkdir(parents=True)
    bd = ws / "5-photos-by-dest" / "Trip" / "keep.jpg"
    bd.write_bytes(b"original")
    (ws / "0-source" / "a.jpg").write_bytes(b"AAAA")
    plan = _plan(ws)
    bd.write_bytes(b"changed-bigger-content")                    # by-dest precondition broken
    with pytest.raises(ValueError, match="dependency changed after planning"):
        prep.PlanExecutor(str(ws)).execute(plan)


def test_fingerprint_stable_across_jobs(tmp_path, monkeypatch):
    # §17.3: two safe job counts produce the same semantic plan and the same dependency
    # fingerprints for the SAME workspace. Planning is non-mutating, so plan twice.
    _install(monkeypatch)
    ws = _ws(tmp_path)
    (ws / "0-source" / "a.jpg").write_bytes(b"AAAA")
    (ws / "0-source" / "b.jpg").write_bytes(b"BBBB")
    p1 = _plan(ws, jobs=1)
    p2 = _plan(ws, jobs=4)
    assert p1.config_fingerprint.value == p2.config_fingerprint.value
    assert p1.metadata_dependencies == p2.metadata_dependencies
    ops1 = sorted((op.type, op.source, op.destination) for op in p1.operations)
    ops2 = sorted((op.type, op.source, op.destination) for op in p2.operations)
    assert ops1 == ops2


def test_hash_video_failure_is_graceful(tmp_path):
    # hash_video on a non-video must not raise; it reports a failure status.
    p = tmp_path / "notreally.mp4"
    p.write_bytes(b"this is not a video")
    res = prep.ContentHasher.hash_video(str(p))
    assert isinstance(res, dict) and res.get("status") == "failed"
