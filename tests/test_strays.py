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

"""Phase B2 — strays routing (non-media out of 0-sources into 1-strays).

Non-media (other-class) is never fingerprinted/deduped (RUL-strays_leave_no_trace); it is moved inert into
1-strays/<plan-id>/<rel> with its structure preserved (RUL-inbox_non_media_to_strays), untracked and scan-skipped,
so 0-sources is left empty. Mocked hashing/metadata, fast. From conftest.py.
"""
import glob
import os
import sqlite3

import photos_1_prep as prep
import photos_utils as utils
import pytest

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
            return {"status": "valid", "strategy": "image-content-hash-v2",
                    "value": "sig-" + f.read().hex()[:16], "engine_version": "t"}
    monkeypatch.setattr(prep.ContentHasher, "fingerprint_image", hsh)

    def meta(folders, max_workers=4, progress_coordinator=None):
        res = {}
        for fo in folders:
            for fn in os.listdir(fo):
                res[os.path.join(fo, fn)] = {"DateTimeOriginal": "2023:01:02 03:04:05",
                                             "extraction_status": "extracted_ok"}
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


@pytest.mark.spec("RUL-prep_empties_inbox", "BLD-strays_per_run", "RUL-inbox_non_media_to_strays", test="TST-strays-stray_moved_structure_preserved")
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


@pytest.mark.spec("RUL-unlisted_extension_other", "RUL-strays_leave_no_trace", test="TST-strays-stray_not_fingerprinted_and_not_cached")
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
    log = open(utils.prep_log_path(str(ws))).read()
    assert "notes.txt" not in log                                # in no log


@pytest.mark.spec("RUL-strays_leave_no_trace", "BLD-stray_records", test="TST-strays-a_stray_is_named_only_in_the_plan_that_moves_it")
def test_a_stray_is_named_only_in_the_plan_that_moves_it(tmp_path, monkeypatch):
    """The plan names the stray — it moves it — and nothing else does: not the journal beyond the move's id, not the
    database, the plan memo, the handoff or the log."""
    _install(monkeypatch)
    ws = _ws(tmp_path)
    (ws / "0-sources" / "notes-stray.txt").write_bytes(b"hello")
    (ws / "0-sources" / "real.jpg").write_bytes(b"img")
    plan = _plan(ws)
    assert "0-sources/notes-stray.txt" in plan.inventory
    (move,) = [op for op in plan.operations if op.source == "0-sources/notes-stray.txt"]
    prep.PlanExecutor(str(ws)).execute(plan)
    ctl = ws / ".photos-ingest"
    (journal,) = glob.glob(str(ctl / "journal-*.json"))
    for record in (journal, utils.handoff_path(str(ws)), utils.prep_log_path(str(ws))):
        assert "notes-stray" not in open(record).read(), record
    assert move.operation_id in open(journal).read()
    assert not any("notes-stray" in p for p in _cached_paths(ws))
    memo = utils.plan_memo_db_path(str(ws))
    if os.path.exists(memo):
        conn = sqlite3.connect(memo)
        try:
            assert "notes-stray" not in " ".join(str(r) for r in conn.execute("SELECT * FROM sqlite_master"))
            for (table,) in conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall():
                assert not any("notes-stray" in str(r) for r in conn.execute(f"SELECT * FROM {table}"))
        finally:
            conn.close()


@pytest.mark.spec("RUL-not_inventoried", "RUL-strays_never_processed")
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


def _spy_reads(monkeypatch):
    """Record every file prep fingerprints and every folder whose metadata it reads."""
    fingerprinted, metadata_folders = [], []
    hsh, meta = prep.ContentHasher.fingerprint_image, utils.MetadataReader.read_metadata_concurrently

    def fp(p):
        fingerprinted.append(p)
        return hsh(p)

    def md(folders, max_workers=4, progress_coordinator=None):
        metadata_folders.extend(folders)
        return meta(folders, max_workers, progress_coordinator)
    monkeypatch.setattr(prep.ContentHasher, "fingerprint_image", fp)
    monkeypatch.setattr(utils.MetadataReader, "read_metadata_concurrently", md)
    return fingerprinted, metadata_folders


@pytest.mark.spec("RUL-not_inventoried", test="TST-strays-what_prep_leaves_out_of_its_inventory")
def test_what_prep_leaves_out_of_its_inventory(tmp_path, monkeypatch):
    """Prep leaves out of its inventory of media, each as a whole, the control directory, the quarantine, a `.git`
    directory and the strays folder with everything in it, and every hidden file: photos placed in each are never
    fingerprinted, never read for metadata, in no part of the plan, and never cached — while a photo in the inbox
    beside them is. A hidden file in the inbox is set aside to the quarantine (RUL-dump_hidden_files_quarantined),
    never taken as media."""
    _install(monkeypatch)
    fingerprinted, metadata_folders = _spy_reads(monkeypatch)
    ws = _ws(tmp_path)
    left_out = [".photos-ingest/inside.jpg",
                ".photos-ingest-quarantine/20250101T000000Z-aaaaaa/0-sources/parked.jpg",
                ".git/objects/blob.jpg",
                "1-strays/loose.jpg", "1-strays/20250101T000000Z-aaaaaa/sub/kept.jpg",
                "5-photos-by-date/2023-01-02/.hidden.jpg",
                "6-photos-by-dest/Trip/.edit.jpg"]   # a hidden FOLDER holding files stops prep instead
                                                     # (RUL-hidden_folder_among_photos_blocks, test_hidden_folders)
    for rel in left_out + ["0-sources/.preview.jpg", "0-sources/real.jpg"]:
        (ws / rel).parent.mkdir(parents=True, exist_ok=True)
        (ws / rel).write_bytes(b"img " + rel.encode())
    plan = _plan(ws)
    assert not plan.blockers, plan.blockers
    assert [os.path.relpath(p, ws) for p in fingerprinted] == ["0-sources/real.jpg"]   # only the inbox's photo
    read = {os.path.relpath(f, ws) for f in metadata_folders}
    assert "0-sources" in read
    assert not [f for f in read if f.split("/")[0] in (".photos-ingest", ".photos-ingest-quarantine", ".git",
                                                       "1-strays") or "/." in "/" + f], read
    in_plan = set(plan.inventory) | {p["relative_path"] for p in plan.workspace_file_preconditions}
    named = {op.source for op in plan.operations} | {op.destination for op in plan.operations}
    for rel in left_out:
        assert rel not in in_plan and rel not in named, rel
    assert [(op.type, op.source) for op in plan.operations if op.source == "0-sources/.preview.jpg"] \
        == [("quarantine_move", "0-sources/.preview.jpg")]
    prep.PlanExecutor(str(ws)).execute(plan)
    cached = _cached_paths(ws)
    jpgs = [p for p in cached if p.endswith(".jpg")]
    assert len(jpgs) == 1 and jpgs[0].startswith("5-photos-by-date/") and "/." not in jpgs[0], cached   # the photo
    for rel in left_out:
        assert (ws / rel).read_bytes() == b"img " + rel.encode(), rel                            # all left as they were


@pytest.mark.spec("RUL-strays_never_processed", test="TST-strays-strays_are_never_processed_again")
def test_strays_are_never_processed_again(tmp_path, monkeypatch):
    """Prep writes into the strays folder but never scans it: a stray set aside by one run — even once the
    configuration counts its extension as an image, and beside a photo dropped in the strays folder by hand — is
    never fingerprinted or read again by the runs after, enters no plan, no cache and no handoff (so geotag and
    merge, which read the handoff, never meet it), and stays where it was, byte for byte."""
    import json
    _install(monkeypatch)
    ws = _ws(tmp_path)
    (ws / "0-sources" / "notes.txt").write_bytes(b"hello")
    (ws / "0-sources" / "real.jpg").write_bytes(b"img")
    _run(ws)
    stray = glob.glob(str(ws / "1-strays" / "*" / "notes.txt"))[0]
    rel_stray = os.path.relpath(stray, ws)
    (ws / "1-strays" / "by-hand.jpg").write_bytes(b"a photo")
    cfg_p = ws / ".photos-ingest" / "photos-00-config.json"
    cfg = json.loads(cfg_p.read_text())
    cfg["media_extensions"]["image"] = list(cfg["media_extensions"]["image"]) + ["txt"]
    cfg_p.write_text(json.dumps(cfg))                               # a stray's extension now names an image
    fingerprinted, metadata_folders = _spy_reads(monkeypatch)
    (ws / "0-sources" / "next.jpg").write_bytes(b"next img")       # the next run has a dump of its own
    plan = _run(ws)
    assert "0-sources/next.jpg" in [os.path.relpath(p, ws) for p in fingerprinted]     # the run did read its dump
    assert not [p for p in fingerprinted if os.path.relpath(p, ws).startswith("1-strays")], fingerprinted
    assert not [f for f in metadata_folders if os.path.relpath(f, ws).startswith("1-strays")], metadata_folders
    for rel in (rel_stray, "1-strays/by-hand.jpg"):
        assert rel not in plan.inventory
        assert not [op for op in plan.operations if rel in (op.source, op.destination)], rel
        assert rel not in _cached_paths(ws)
    handoff = json.loads((ws / ".photos-ingest" / "photos-11-handoff.json").read_text())
    assert not [f for f in handoff["files"] if f["relative_path"].startswith("1-strays/")]
    assert open(stray, "rb").read() == b"hello" and (ws / "1-strays" / "by-hand.jpg").read_bytes() == b"a photo"


@pytest.mark.spec("RUL-tracks_geotag_only", "RUL-track_files_block_prep", "RUL-track_file_left_in_place", test="TST-strays-track_file_blocks_prep_and_stays_put")
def test_track_file_blocks_prep_and_stays_put(tmp_path, monkeypatch):
    """RUL-track_files_block_prep: a track is never media. A `.gpx` anywhere prep inventories — the 0-sources
    dump or a managed folder — blocks the plan and is left where it is: no operation moves it (above
    all not into 1-strays, where clearing the strays would delete it), it is never fingerprinted, and
    the blocked plan cannot be executed."""
    _install(monkeypatch)
    seen = {"n": 0}
    orig = prep.ContentHasher.fingerprint_image

    def spy(p):
        if p.lower().endswith(".gpx"):
            seen["n"] += 1
        return orig(p)
    monkeypatch.setattr(prep.ContentHasher, "fingerprint_image", spy)

    ws = _ws(tmp_path)
    (ws / "0-sources" / "track1.gpx").write_text("<gpx><trkpt lat='1' lon='2'/></gpx>")
    (ws / "5-photos-by-date" / "2023-01-02").mkdir()
    (ws / "5-photos-by-date" / "2023-01-02" / "TRACK2.GPX").write_text("<gpx/>")
    (ws / "0-sources" / "photo.jpg").write_bytes(b"img")
    plan = _plan(ws)
    assert any("0-sources/track1.gpx" in b for b in plan.blockers), plan.blockers
    assert any("5-photos-by-date/2023-01-02/TRACK2.GPX" in b for b in plan.blockers), plan.blockers
    assert not [op for op in plan.operations
                if ".gpx" in ((op.source or "") + (op.destination or "")).lower()]
    assert seen["n"] == 0                                           # never fingerprinted
    with pytest.raises(ValueError, match="blockers"):
        prep.PlanExecutor(str(ws)).execute(plan)
    assert (ws / "0-sources" / "track1.gpx").exists()               # left where it was
    assert not glob.glob(str(ws / "1-strays" / "**" / "*.gpx"), recursive=True)


@pytest.mark.spec("RUL-tracks_geotag_only", test="TST-strays-prep_never_reads_the_tracks")
def test_prep_never_reads_the_tracks(tmp_path, monkeypatch):
    """Prep resolves gpx_root to check where it lies, and does nothing more with it: it never lists,
    walks or opens anything beneath it, and never builds geotag's GPX index."""
    import builtins
    import json as _json
    import photos_2_geotag as geo
    _install(monkeypatch)
    ws = _ws(tmp_path)
    tracks = tmp_path / "tracks"
    (tracks / "2023").mkdir(parents=True)
    (tracks / "2023" / "day.gpx").write_text("<gpx><trkpt lat='1' lon='2'/></gpx>")
    _plan(ws)                                                        # seeds the workspace config
    cfg_p = ws / ".photos-ingest" / "photos-00-config.json"
    cfg_p.write_text(_json.dumps(dict(_json.loads(cfg_p.read_text()), gpx_root=str(tracks))))

    root = os.path.realpath(str(tracks))
    touched = []

    def watch(fn):
        def wrapper(path=".", *a, **k):
            if isinstance(path, (str, os.PathLike)) and os.path.realpath(os.fspath(path)).startswith(root):
                touched.append((fn.__name__, os.fspath(path)))
            return fn(path, *a, **k)
        return wrapper
    for name in ("walk", "listdir", "scandir"):
        monkeypatch.setattr(os, name, watch(getattr(os, name)))
    monkeypatch.setattr(builtins, "open", watch(builtins.open))
    monkeypatch.setattr(geo.GPXIndex, "__init__", lambda *a, **k: pytest.fail("prep built the GPX index"))

    (ws / "0-sources" / "photo.jpg").write_bytes(b"img")
    plan = _run(ws)
    assert plan.blockers == [] and not any("gpx" in w.lower() for w in plan.warnings), (plan.blockers, plan.warnings)
    assert prep.CONFIG["gpx_root"] == str(tracks)                    # the run had the tracks configured
    assert touched == []


@pytest.mark.spec("RUL-track_files_block_prep", test="TST-strays-every_track_format_blocks_prep")
@pytest.mark.parametrize("name", ["route.kml", "route.KMZ", "ride.FIT", "run.tcx", "log.nmea", "flight.igc"])
def test_every_track_format_blocks_prep(tmp_path, monkeypatch, name):
    """RUL-track_files_block_prep: a track in any format, not only the GPX geotag reads, is never media — it
    blocks the plan and stays in the dump, never parked in 1-strays."""
    _install(monkeypatch)
    ws = _ws(tmp_path)
    (ws / "0-sources" / name).write_text("track")
    (ws / "0-sources" / "photo.jpg").write_bytes(b"img")
    plan = _plan(ws)
    assert any(f"0-sources/{name}" in b for b in plan.blockers), plan.blockers
    assert not [op for op in plan.operations if name in (op.source or "") + (op.destination or "")]
    with pytest.raises(ValueError, match="blockers"):
        prep.PlanExecutor(str(ws)).execute(plan)
    assert (ws / "0-sources" / name).exists()
    assert not glob.glob(str(ws / "1-strays" / "**" / name), recursive=True)


@pytest.mark.spec("RUL-prep_empties_inbox", test="TST-strays-mixed_media_and_stray")
def test_mixed_media_and_stray(tmp_path, monkeypatch):
    _install(monkeypatch)
    ws = _ws(tmp_path)
    (ws / "0-sources" / "photo.jpg").write_bytes(b"img")
    (ws / "0-sources" / "notes.txt").write_bytes(b"hello")
    _run(ws)
    assert len(glob.glob(str(ws / "5-photos-by-date" / "**" / "*.jpg"), recursive=True)) == 1
    assert glob.glob(str(ws / "1-strays" / "*" / "notes.txt"))
    assert list((ws / "0-sources").iterdir()) == []


@pytest.mark.spec("RUL-stray_media_hinted", "BLD-stray_media_probe", "RUL-stray_media_hint_names_extension",
                  test="TST-strays-stray_media_detection_warns_only_for_media_mime")
def test_stray_media_detection_warns_only_for_media_mime(tmp_path, monkeypatch):
    # An unlisted RAW (.raf) and a real non-media (.txt) both land in strays. exiftool sees the .raf as
    # image/*, the .txt as text/plain -> only the .raf gets the "add to media_extensions" hint, once,
    # from one probe of the extension however many files carry it.
    _install(monkeypatch)
    ws = _ws(tmp_path)
    (ws / "0-sources" / "DSCF1.raf").write_bytes(b"raw")        # not in default media_extensions -> stray
    (ws / "0-sources" / "DSCF2.RAF").write_bytes(b"raw2")       # same extension, other case
    (ws / "0-sources" / "notes.txt").write_bytes(b"hello")      # genuine non-media stray
    mimes = {".raf": "image/x-fujifilm-raf", ".txt": "text/plain"}
    probed = []

    def probe(p):
        probed.append(os.path.splitext(p)[1].lower())
        return mimes.get(probed[-1])
    monkeypatch.setattr(utils, "exiftool_mime_type", probe)
    plan = _plan(ws)
    raf_warn = [w for w in plan.warnings if ".raf" in w]
    assert len(raf_warn) == 1 and "media_extensions" in raf_warn[0], plan.warnings
    assert not any(".txt" in w for w in plan.warnings)
    assert sorted(probed) == [".raf", ".txt"]                    # one probe per distinct extension
    assert not plan.blockers                                     # a hint, never a block


@pytest.mark.spec("RUL-stray_media_hinted", test="TST-strays-stray_media_detection_silent_when_exiftool_absent")
def test_stray_media_detection_silent_when_exiftool_absent(tmp_path, monkeypatch):
    # exiftool unavailable (probe returns None) -> no stray-media warning, never blocks.
    _install(monkeypatch)
    ws = _ws(tmp_path)
    (ws / "0-sources" / "DSCF1.raf").write_bytes(b"raw")
    monkeypatch.setattr(utils, "exiftool_mime_type", lambda p: None)
    plan = _plan(ws)
    assert not any(".raf" in w for w in plan.warnings)


@pytest.mark.spec("RUL-other_outside_inbox_blocks",
                  test="TST-strays-a_file_of_no_media_class_outside_the_inbox_blocks")
@pytest.mark.parametrize("where", ["5-photos-by-date/2023-01-02", "2-missing-metadata", "4-videos-by-date/2023-01-02",
                                   "6-photos-by-dest/Trip"])
def test_a_file_of_no_media_class_outside_the_inbox_blocks(tmp_path, monkeypatch, where):
    """Prep moves a file of no media class to the strays folder only from the inbox. Anywhere else — an
    extension taken off the lists, a file put there by hand — it stops the plan, naming the file, and
    the file stays where it is."""
    _install(monkeypatch)
    ws = _ws(tmp_path)
    folder = ws / where
    folder.mkdir(parents=True, exist_ok=True)
    (folder / "notes.txt").write_bytes(b"hello")
    plan = _plan(ws)
    rel = f"{where}/notes.txt"
    assert [b for b in plan.blockers if rel in b and "no media class" in b], plan.blockers
    assert not any(rel in (op.source or "") for op in plan.operations)



@pytest.mark.spec("RUL-stray_media_hinted", "BLD-stray_media_probe",
                  test="TST-strays-stray_media_hinted_on_the_run_that_initializes")
def test_stray_media_hinted_on_the_run_that_initializes(tmp_path, monkeypatch):
    """On the run that initializes a workspace the dump is still where it was put, beside the folders prep makes;
    its files prep sets aside as strays are probed and hinted as the inbox's are."""
    _install(monkeypatch)
    ws = tmp_path / "ws"
    (ws / "dump").mkdir(parents=True)
    (ws / "dump" / "DSCF1.raf").write_bytes(b"raw")             # not in default media_extensions -> stray
    monkeypatch.setattr(utils, "exiftool_mime_type",
                        lambda p: "image/x-fujifilm-raf" if p.lower().endswith(".raf") else None)
    plan = _plan(ws)
    assert any((op.destination or "").startswith("1-strays/") and op.destination.endswith("DSCF1.raf")
               for op in plan.operations)                         # set aside as a stray
    assert [w for w in plan.warnings if ".raf" in w and "media_extensions" in w], plan.warnings


@pytest.mark.spec("RUL-inbox_non_media_never_blocks",
                  test="TST-strays-a_failed_metadata_read_never_blocks_a_file_of_no_media_class")
def test_a_failed_metadata_read_never_blocks_a_file_of_no_media_class(tmp_path, monkeypatch):
    """exiftool failing for a folder of the inbox blocks its media, never its files of no media class."""
    _install(monkeypatch)
    monkeypatch.setattr(utils.MetadataReader, "read_metadata_concurrently",
                        lambda folders, max_workers=4, progress_coordinator=None: ({}, set(folders)))
    ws = _ws(tmp_path)
    (ws / "0-sources" / "notes.txt").write_bytes(b"hello")
    (ws / "0-sources" / "photo.jpg").write_bytes(b"img")
    plan = _plan(ws)
    assert not [b for b in plan.blockers if "notes.txt" in b], plan.blockers
    assert [b for b in plan.blockers if "photo.jpg" in b], plan.blockers     # media still blocks
