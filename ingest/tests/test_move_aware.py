"""Phase 3a — move-aware cache identity (prep Section 10.1 / 10.2).

When the user moves a file from by-date into 6-photos-by-dest (or re-sorts one
between destinations inside by-dest), prep must recognize the move cache-only and
carry the cached hash + metadata forward without re-hashing/re-extracting, with no
filesystem operation (by-dest is read-only).

Hashing/metadata are mocked; `hash_image` is a spy so we can assert a recognized
move is NOT re-hashed. photos_1_prep / photos_utils come from conftest.py.
"""
import glob
import json
import os
import shutil

import photos_1_prep as prep
import photos_utils as utils


def _ws(tmp_path):
    ws = tmp_path / "ws"
    ws.mkdir()
    for d in ("0-sources", "2-missing-metadata", "3-redundant-jpgs",
              "4-videos-by-date", "5-photos-by-date", "6-photos-by-dest"):
        (ws / d).mkdir()
    (ws / ".photos-ingest").mkdir(exist_ok=True)
    (ws / ".photos-ingest" / "photos-00-workspace-guard").touch()
    return ws


def _install_mocks(monkeypatch, hash_calls):
    def spy(p):
        hash_calls.append(p)
        with open(p, "rb") as f:
            return {"status": "valid", "strategy": "image-content-hash-v1",
                    "value": "sig-" + f.read().hex()[:16], "engine_version": "t"}
    monkeypatch.setattr(prep.ContentHasher, "hash_image", spy)

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
    cache = prep.WorkspaceCache(str(ws))
    plan = prep.WorkspacePrepWorkflow(str(ws), cache).plan()
    cache.close()
    return plan


def _seed_one(ws, content=b"AAAA"):
    """Run prep once so a 0-sources file is organized into 5-photos-by-date and cached."""
    (ws / "0-sources" / "a.jpg").write_bytes(content)
    prep.CONFIG["jobs"] = 1
    plan = _plan(ws)
    prep.PlanExecutor(str(ws)).execute(plan)
    organized = glob.glob(str(ws / "5-photos-by-date" / "*.jpg"))
    assert len(organized) == 1, organized
    return organized[0]  # absolute path


def _media_ops(plan):
    return [op for op in plan.operations
            if op.type in ("move_no_clobber", "rename_no_clobber", "quarantine_move")]


def test_by_date_to_by_dest_move_is_recognized(tmp_path, monkeypatch):
    hash_calls = []
    _install_mocks(monkeypatch, hash_calls)
    ws = _ws(tmp_path)
    organized = _seed_one(ws)

    # User moves the file into by-dest (os.rename preserves size + mtime).
    dest_dir = ws / "6-photos-by-dest" / "Belgium"
    dest_dir.mkdir(parents=True)
    new_abs = dest_dir / os.path.basename(organized)
    os.rename(organized, new_abs)

    hash_calls.clear()
    plan2 = _plan(ws)

    # Recognized: not re-hashed, reported as a move, no filesystem op touches by-dest.
    assert hash_calls == [], hash_calls
    assert plan2.summary["recognized_moves"] == 1
    assert all("6-photos-by-dest" not in (op.source or "")
               and "6-photos-by-dest" not in (op.destination or "")
               for op in _media_ops(plan2))

    prep.PlanExecutor(str(ws)).execute(plan2)
    rows = prep.WorkspaceCache(str(ws)).get_all_files()
    new_rel = "6-photos-by-dest/Belgium/" + os.path.basename(organized)
    old_rel = os.path.relpath(organized, str(ws))
    assert new_rel in rows and old_rel not in rows           # carried forward, old dropped
    assert rows[new_rel]["content_hash"]                     # hash carried, not None
    handoff = json.load(open(utils.handoff_path(str(ws))))
    assert any(f["relative_path"] == new_rel for f in handoff["files"])


def test_re_sort_between_destinations_is_recognized(tmp_path, monkeypatch):
    hash_calls = []
    _install_mocks(monkeypatch, hash_calls)
    ws = _ws(tmp_path)
    organized = _seed_one(ws)
    name = os.path.basename(organized)

    # First land it in by-dest and cache it there.
    (ws / "6-photos-by-dest" / "Brussels").mkdir(parents=True)
    os.rename(organized, ws / "6-photos-by-dest" / "Brussels" / name)
    prep.PlanExecutor(str(ws)).execute(_plan(ws))

    # Now re-sort Brussels -> Bruges (§10.2).
    (ws / "6-photos-by-dest" / "Bruges").mkdir(parents=True)
    os.rename(ws / "6-photos-by-dest" / "Brussels" / name,
              ws / "6-photos-by-dest" / "Bruges" / name)
    hash_calls.clear()
    plan3 = _plan(ws)

    assert hash_calls == [], hash_calls
    assert plan3.summary["recognized_moves"] == 1

    prep.PlanExecutor(str(ws)).execute(plan3)
    rows = prep.WorkspaceCache(str(ws)).get_all_files()
    assert "6-photos-by-dest/Bruges/" + name in rows
    assert "6-photos-by-dest/Brussels/" + name not in rows
    handoff = json.load(open(utils.handoff_path(str(ws))))
    assert any(df["path"] == "6-photos-by-dest/Bruges" for df in handoff["destination_folders"])


def test_ambiguous_match_is_rescanned_not_carried(tmp_path, monkeypatch):
    hash_calls = []
    _install_mocks(monkeypatch, hash_calls)
    ws = _ws(tmp_path)
    organized = _seed_one(ws)
    name = os.path.basename(organized)

    # Move into A, and plant an identical-stat twin (same size+mtime+basename) in B.
    (ws / "6-photos-by-dest" / "A").mkdir(parents=True)
    (ws / "6-photos-by-dest" / "B").mkdir(parents=True)
    a = ws / "6-photos-by-dest" / "A" / name
    b = ws / "6-photos-by-dest" / "B" / name
    os.rename(organized, a)
    st = os.stat(a)
    shutil.copyfile(a, b)
    os.utime(b, ns=(st.st_atime_ns, st.st_mtime_ns))  # make B ambiguous with A

    hash_calls.clear()
    plan2 = _plan(ws)
    # Two targets for one source -> not unique -> not recognized -> both rescanned.
    assert plan2.summary["recognized_moves"] == 0
    assert len(hash_calls) >= 2


def test_content_change_is_rescanned_not_carried(tmp_path, monkeypatch):
    hash_calls = []
    _install_mocks(monkeypatch, hash_calls)
    ws = _ws(tmp_path)
    organized = _seed_one(ws)

    dest_dir = ws / "6-photos-by-dest" / "Trip"
    dest_dir.mkdir(parents=True)
    new_abs = dest_dir / os.path.basename(organized)
    os.rename(organized, new_abs)
    with open(new_abs, "ab") as f:           # content (size) changed -> stat differs
        f.write(b"XXXX")

    hash_calls.clear()
    plan2 = _plan(ws)
    assert plan2.summary["recognized_moves"] == 0
    assert len(hash_calls) >= 1              # rescanned, not carried
