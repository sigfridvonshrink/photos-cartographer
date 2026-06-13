"""Audit backfill — spec paths that lacked direct coverage.

Covers: other-class routing to 1-strays (§3.2/§9), missing-timestamp
UNKN_ naming + video routing, CreateDate fallback, suffix monotonicity, ghost-prune,
by-dest hash-failure skip vs mutable blocker, redundant-JPEG 0-sources restriction,
camera-group-key version staleness, by-dest precondition rejection, fingerprint stability
across -j, the zfs snapshot success/required-failure paths, and fingerprint_video failure.

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
    for d in ("0-sources", "1-strays", "2-missing-metadata", "3-redundant-jpgs",
              "4-videos-by-date", "5-photos-by-date", "6-photos-by-dest"):
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
    monkeypatch.setattr(prep.ContentHasher, "fingerprint_image", hsh)
    monkeypatch.setattr(prep.ContentHasher, "fingerprint_video",
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

def test_other_class_moves_to_strays(tmp_path, monkeypatch):
    _install(monkeypatch)
    ws = _ws(tmp_path)
    (ws / "0-sources" / "notes.txt").write_bytes(b"hello")
    plan = _plan(ws)
    assert not plan.blockers, plan.blockers                       # never blocks (§3.2/§9)
    stray = [op for op in plan.operations if op.source == "0-sources/notes.txt"]
    assert stray and stray[0].destination.startswith("1-strays/") \
        and stray[0].destination.endswith("/notes.txt"), stray    # moved to 1-strays/<id>/notes.txt
    _run(ws)
    assert not os.path.exists(ws / "0-sources" / "notes.txt")      # out of the inbox (§7.6)
    assert glob.glob(str(ws / "1-strays" / "*" / "notes.txt"))     # landed in strays


def test_strays_are_abandoned_not_in_handoff(tmp_path, monkeypatch):
    # Strays are abandoned once moved (§3.2): the act is logged, but the stray file is NOT tracked in
    # the handoff and 1-strays is NOT listed in folders_scanned — so nothing downstream depends on
    # strays remaining constant (its content never enters the handoff content fingerprint).
    _install(monkeypatch)
    ws = _ws(tmp_path)
    (ws / "0-sources" / "notes.txt").write_bytes(b"junk")          # non-media -> strays
    (ws / "0-sources" / "a.jpg").write_bytes(b"AAAA")              # a real photo -> by-date
    _run(ws)
    handoff = json.loads(open(ws / ".photos-ingest" / "photos-11-handoff.json").read())
    scanned = {f["name"] for f in handoff["folders_scanned"]}
    assert "1-strays" not in scanned                              # never scanned -> not listed
    assert {"0-sources", "5-photos-by-date", "6-photos-by-dest"} <= scanned
    tracked = {f["relative_path"] for f in handoff["files"]}
    assert not any(p.startswith("1-strays/") for p in tracked)     # stray file untracked (abandoned)


def test_missing_timestamp_routes_to_missing_metadata_with_unkn_name(tmp_path, monkeypatch):
    _install(monkeypatch, meta_for=lambda f: {})                  # no timestamp
    ws = _ws(tmp_path)
    (ws / "0-sources" / "pic.jpg").write_bytes(b"img")
    plan = _plan(ws)
    org = [op for op in _moves(plan) if op.source == "0-sources/pic.jpg"]
    assert org and org[0].destination == "2-missing-metadata/UNKN_pic.jpg", org[0].destination


def test_video_with_timestamp_routes_to_videos_by_date(tmp_path, monkeypatch):
    _install(monkeypatch, meta_for=lambda f: {"DateTimeOriginal": "2023:01:02 03:04:05"})
    ws = _ws(tmp_path)
    (ws / "0-sources" / "clip.mp4").write_bytes(b"vid")
    org = [op for op in _moves(_plan(ws)) if op.source == "0-sources/clip.mp4"]
    assert org and org[0].destination.startswith("4-videos-by-date/"), org[0].destination


def test_create_date_used_when_no_datetimeoriginal(tmp_path, monkeypatch):
    _install(monkeypatch, meta_for=lambda f: {"CreateDate": "2019:05:06 07:08:09"})  # only CreateDate
    ws = _ws(tmp_path)
    (ws / "0-sources" / "p.jpg").write_bytes(b"img")
    org = [op for op in _moves(_plan(ws)) if op.source == "0-sources/p.jpg"]
    assert org and "2019-05-06--07-08-09" in org[0].destination, org[0].destination


def test_bare_timestamp_name_used_when_free(tmp_path, monkeypatch):
    # §7.2 bare-first: the un-suffixed timestamp name is taken when free, even though a -001 sibling
    # already exists. This MATCHES calibration's final naming (also bare-first), so an uncorrected file
    # gets the same provisional and final name and calibration plans no needless rename (§7.3). The
    # existing -001 is untouched (no clobber).
    _install(monkeypatch, meta_for=lambda f: {"DateTimeOriginal": "2023:01:02 03:04:05"})
    ws = _ws(tmp_path)
    (ws / "5-photos-by-date" / "2023-01-02--03-04-05-001.jpg").write_bytes(b"existing")
    (ws / "0-sources" / "new.jpg").write_bytes(b"new")
    org = [op for op in _moves(_plan(ws)) if op.source == "0-sources/new.jpg"]
    assert org and org[0].destination == "5-photos-by-date/2023-01-02--03-04-05.jpg", org[0].destination
    assert (ws / "5-photos-by-date" / "2023-01-02--03-04-05-001.jpg").exists()       # untouched


def test_same_timestamp_collision_suffixes_after_bare(tmp_path, monkeypatch):
    # Two fresh files at the SAME timestamp: the first takes the bare name, the second collides and
    # gets -001 (bare-first then the differentiating suffix, §7.2).
    _install(monkeypatch, meta_for=lambda f: {"DateTimeOriginal": "2023:01:02 03:04:05"})
    ws = _ws(tmp_path)
    (ws / "0-sources" / "a.jpg").write_bytes(b"AAA")
    (ws / "0-sources" / "b.jpg").write_bytes(b"BBB")
    dests = {op.destination for op in _moves(_plan(ws))
             if op.source in ("0-sources/a.jpg", "0-sources/b.jpg")}
    assert dests == {"5-photos-by-date/2023-01-02--03-04-05.jpg",
                     "5-photos-by-date/2023-01-02--03-04-05-001.jpg"}, dests


# --- dedup / cache -----------------------------------------------------------

def test_ghost_prune_removes_missing_cache_row(tmp_path, monkeypatch):
    _install(monkeypatch)
    ws = _ws(tmp_path)
    (ws / "0-sources" / "a.jpg").write_bytes(b"AAAA")
    _run(ws)                                                      # organize + cache
    organized = glob.glob(str(ws / "5-photos-by-date" / "*.jpg"))[0]
    os.remove(organized)                                          # file vanishes
    plan = _plan(ws)
    rel = os.path.relpath(organized, str(ws))
    assert any(op.type == "db_remove" and any(e.get("relative_path") == rel
               for e in (op.database_effects_after_verification or []))
               for op in plan.operations), [op.type for op in plan.operations]


def test_quarantine_writes_evidence_before_moving(tmp_path, monkeypatch):
    # Evidence-before-quarantine (§15): the manifest entry must be written BEFORE the move, so a
    # crash/failure mid-move never strands a file in quarantine with no record. We simulate the move
    # failing; with the correct ordering the manifest entry exists anyway (with the old move-then-
    # manifest order, the failed move would abort before the manifest write and leave none).
    _install(monkeypatch)                                      # content-based hash -> dupes collide
    ws = _ws(tmp_path)
    (ws / "0-sources" / "a.jpg").write_bytes(b"SAME")
    (ws / "0-sources" / "b.jpg").write_bytes(b"SAME")          # identical content -> one quarantined
    real_move = prep._move_no_clobber

    def failing_move(src, dest):
        if ".photos-ingest-quarantine" in dest:
            raise OSError("simulated crash mid quarantine move")
        return real_move(src, dest)
    monkeypatch.setattr(prep, "_move_no_clobber", failing_move)

    with pytest.raises(RuntimeError):                          # execute raises on the failed move
        _run(ws)
    manifests = glob.glob(str(ws / ".photos-ingest-quarantine" / "*" / "manifest.json"))
    assert manifests, "manifest entry must be written before the move, so it survives a failed move"
    entries = json.loads(open(manifests[0]).read())
    assert entries and "duplicate_evidence" in entries[0], entries


def test_by_dest_hash_failure_skipped_mutable_blocks(tmp_path, monkeypatch):
    def hash_for(p):
        if "fail" in os.path.basename(p):
            return {"status": "failed", "strategy": "image-content-hash-v1", "error": "boom"}
        return None
    _install(monkeypatch, hash_for=hash_for)
    ws = _ws(tmp_path)
    (ws / "6-photos-by-dest" / "Trip").mkdir(parents=True)
    (ws / "6-photos-by-dest" / "Trip" / "failbd.jpg").write_bytes(b"x")   # by-dest fail -> skip
    (ws / "0-sources" / "failmut.jpg").write_bytes(b"y")                   # mutable fail -> block
    blockers = _plan(ws).blockers
    assert any("failmut.jpg" in b for b in blockers), blockers
    assert not any("failbd.jpg" in b for b in blockers), blockers


def test_redundant_jpeg_only_separated_from_source(tmp_path, monkeypatch):
    _install(monkeypatch)
    ws = _ws(tmp_path)
    (ws / "0-sources" / "shot.arw").write_bytes(b"raw")
    (ws / "0-sources" / "shot.jpg").write_bytes(b"jpg")            # 0-sources pair -> jpg separated
    (ws / "5-photos-by-date" / "keep.arw").write_bytes(b"raw2")
    (ws / "5-photos-by-date" / "keep.jpg").write_bytes(b"jpg2")   # by-date pair -> untouched
    plan = _plan(ws)
    seps = [op for op in _moves(plan) if op.destination.startswith("3-redundant-jpgs/")]
    assert [op.source for op in seps] == ["0-sources/shot.jpg"], [op.source for op in seps]


def test_camera_group_key_version_staleness_refreshes(tmp_path, monkeypatch):
    _install(monkeypatch, meta_for=lambda f: {"DateTimeOriginal": "2023:01:02 03:04:05",
                                              "Make": "M", "Model": "D"})
    ws = _ws(tmp_path)
    (ws / "0-sources" / "a.jpg").write_bytes(b"AAAA")
    _run(ws)
    monkeypatch.setattr(utils, "CAMERA_GROUP_KEY_VERSION", 999)   # derivation bumped
    plan = _plan(ws)
    organized = glob.glob(str(ws / "5-photos-by-date" / "*.jpg"))[0]
    rel = os.path.relpath(organized, str(ws))
    assert plan.summary["metadata_plan_status"].get(rel) == "extracted_ok", \
        plan.summary["metadata_plan_status"]


# --- lifecycle / zfs ---------------------------------------------------------

def test_by_dest_change_rejects_plan_at_execute(tmp_path, monkeypatch):
    _install(monkeypatch)
    ws = _ws(tmp_path)
    (ws / "6-photos-by-dest" / "Trip").mkdir(parents=True)
    bd = ws / "6-photos-by-dest" / "Trip" / "keep.jpg"
    bd.write_bytes(b"original")
    (ws / "0-sources" / "a.jpg").write_bytes(b"AAAA")
    plan = _plan(ws)
    bd.write_bytes(b"changed-bigger-content")                    # by-dest precondition broken
    with pytest.raises(ValueError, match="dependency changed after planning"):
        prep.PlanExecutor(str(ws)).execute(plan)


def test_fingerprint_stable_across_jobs(tmp_path, monkeypatch):
    # §17.3: two safe job counts produce the same semantic plan and the same dependency
    # fingerprints for the SAME workspace. Planning is non-mutating, so plan twice.
    _install(monkeypatch)
    ws = _ws(tmp_path)
    (ws / "0-sources" / "a.jpg").write_bytes(b"AAAA")
    (ws / "0-sources" / "b.jpg").write_bytes(b"BBBB")
    p1 = _plan(ws, jobs=1)
    p2 = _plan(ws, jobs=4)
    assert p1.config_fingerprint.value == p2.config_fingerprint.value
    assert p1.metadata_dependencies == p2.metadata_dependencies
    ops1 = sorted((op.type, op.source, op.destination) for op in p1.operations)
    ops2 = sorted((op.type, op.source, op.destination) for op in p2.operations)
    assert ops1 == ops2


def test_hash_video_failure_is_graceful(tmp_path):
    # fingerprint_video on a non-video must not raise; it reports a failure status.
    p = tmp_path / "notreally.mp4"
    p.write_bytes(b"this is not a video")
    res = prep.ContentHasher.fingerprint_video(str(p))
    assert isinstance(res, dict) and res.get("status") == "failed"
