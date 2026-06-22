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

"""Phase C2 — end-of-prep transformation log (photos-15-prep-log.json, prep §16.1 / shared §13.3).

A per-photo, content-fingerprint-keyed, human-readable record of everything prep did: derived
from the validated plan + quarantine evidence, carried forward incrementally. Mocked hashing/
metadata, fast. From conftest.py.
"""
import glob
import json
import os

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
    (ws / ".photos-ingest" / "photos-00-workspace-guard").touch()   # initialized (no init journey)
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


def _log(ws):
    with open(utils.prep_log_path(str(ws))) as f:
        return json.load(f)


@pytest.mark.spec("log-keyed-by-fingerprint-1", "prep-log-per-photo-fingerprint-keyed-1", "prep-log-records-journey-1")
def test_media_journey_keyed_by_fingerprint(tmp_path, monkeypatch):
    _install(monkeypatch)
    ws = _ws(tmp_path)
    (ws / "0-sources" / "IMG.JPG").write_bytes(b"AAAA")     # uppercase ext -> normalized
    _run(ws)
    photos = _log(ws)["photos"]
    assert len(photos) == 1
    fp, entry = next(iter(photos.items()))
    assert entry["content_sha256"] == fp                   # keyed by content fingerprint
    actions = [(s["action"], s.get("to") or s.get("from")) for s in entry["journey"]]
    assert ("extension_normalized", "IMG.JPG") in [(s["action"], s.get("from")) for s in entry["journey"]]
    assert any(a == "organized" for a, _ in actions)
    assert any(a == "provisional_rename" for a, _ in actions)
    assert entry["final_path"].startswith("5-photos-by-date/")
    assert all(s.get("run") for s in entry["journey"])     # each step attributed to its run


@pytest.mark.spec("prep-log-records-quarantine-dups-1", "prep-quarantine-recoverable-manifest-1")
def test_quarantined_duplicate_recorded(tmp_path, monkeypatch):
    _install(monkeypatch)
    ws = _ws(tmp_path)
    (ws / "0-sources" / "a.jpg").write_bytes(b"SAME")
    (ws / "0-sources" / "b.jpg").write_bytes(b"SAME")      # identical content -> one quarantined
    _run(ws)
    photos = _log(ws)["photos"]
    assert len(photos) == 1                                # one content, one entry
    entry = next(iter(photos.values()))
    assert entry["deduplicated"]["retained"] == entry["final_path"]   # final location of the kept file
    dq = entry["deduplicated"]["quarantined"]
    assert len(dq) == 1
    assert dq[0]["origin"].startswith("0-sources/")
    assert ".photos-ingest-quarantine/" in dq[0]["quarantine_path"]
    assert dq[0]["retained_counterpart"]                              # the kept file at dedup time


@pytest.mark.spec("prep-no-timestamp-correction-1")
def test_prep_organizes_by_raw_naive_timestamp_no_tz_or_utc_shift(tmp_path, monkeypatch):
    """§7.6 (anti): prep organizes by the RAW camera-naive timestamp and never timezone/UTC-corrects
    it (that is geotag's job). Use a late-evening naive time that ANY tz/UTC conversion would push to
    a different date+hour; assert the file lands under that EXACT raw date and time."""
    _install(monkeypatch)
    def meta(folders, max_workers=4, progress_coordinator=None):
        res = {}
        for fo in folders:
            for fn in os.listdir(fo):
                res[os.path.join(fo, fn)] = {"DateTimeOriginal": "2023:03:26 23:45:00",
                                             "extraction_status": "extracted_ok", "raw_payload": "{}"}
        return res, set()
    monkeypatch.setattr(utils.MetadataReader, "read_metadata_concurrently", meta)
    ws = _ws(tmp_path)
    (ws / "0-sources" / "x.jpg").write_bytes(b"AAAA")
    _run(ws)
    entry = next(iter(_log(ws)["photos"].values()))
    # raw 2023:03:26 23:45:00 -> exact same date folder + civil time, no shift to 21:45 / 03-27 / etc.
    assert entry["final_path"] == "5-photos-by-date/2023-03-26/2023-03-26--23-45-00.jpg"


@pytest.mark.spec("prep-log-self-sufficient-1")
def test_prep_log_is_complete_and_standalone_without_geotag_or_merge(tmp_path, monkeypatch):
    """§16.1: the prep log (photos-15) is complete and self-sufficient even if geotag/merge never run.
    After a prep-only run, NO geotag (photos-2x) / merge (photos-3x) artifact exists, yet photos-15
    already records the file's full, non-partial journey ending at its organized destination."""
    _install(monkeypatch)
    ws = _ws(tmp_path)
    (ws / "0-sources" / "a.jpg").write_bytes(b"AAAA")
    _run(ws)
    ctl = ws / ".photos-ingest"
    # prep ran in isolation: no downstream phase artifacts were produced.
    later = [n for n in os.listdir(ctl)
             if n.startswith("photos-2") or n.startswith("photos-3")]
    assert later == [], later
    # ...yet the prep log is on disk and self-sufficient: a complete (non-partial) per-photo journey.
    assert os.path.exists(utils.prep_log_path(str(ws)))
    photos = _log(ws)["photos"]
    assert len(photos) == 1
    entry = next(iter(photos.values()))
    assert not entry.get("partial")                                   # complete, nothing missing
    assert entry["final_path"].startswith("5-photos-by-date/")        # full journey to its destination
    actions = [s["action"] for s in entry["journey"]]
    assert "organized" in actions and "provisional_rename" in actions
    assert all(s.get("run") for s in entry["journey"])                # every step attributed to its run


@pytest.mark.spec("prep-no-parse-nonconforming-name-1")
def test_nonconforming_name_is_ignored_timestamp_comes_from_metadata(tmp_path, monkeypatch):
    """§8: prep never parses meaning from a non-conforming filename — it re-ingests the file and takes
    the timestamp from metadata. A file whose name MISLEADINGLY encodes 2099 but whose EXIF
    DateTimeOriginal is 2023:01:02 must be organized under the EXIF date (2023-01-02), with a
    provisional name derived from metadata — the bogus '2099' in the name is never honoured."""
    _install(monkeypatch)                                            # meta -> DateTimeOriginal 2023:01:02 03:04:05
    ws = _ws(tmp_path)
    (ws / "0-sources" / "IMG_20991231_2359.jpg").write_bytes(b"AAAA")   # name lies about the date
    _run(ws)
    entry = next(iter(_log(ws)["photos"].values()))
    # Date + provisional name come from EXIF metadata, not the filename.
    assert entry["final_path"] == "5-photos-by-date/2023-01-02/2023-01-02--03-04-05.jpg"
    assert "2099" not in entry["final_path"]                        # the misleading name was not parsed


@pytest.mark.spec("prep-log-derived-no-new-authority-1")
def test_prep_log_entries_are_derived_from_the_validated_plan(tmp_path, monkeypatch):
    """§16.1 item 4: the prep log is DERIVED from the validated plan + journals and introduces no new
    authority — its facts trace back to plan operations. Assert the logged final destination equals a
    destination the plan actually planned, and the extension-normalization step's 'from' name matches
    the plan's rename source — the log records nothing the plan/journal did not establish."""
    _install(monkeypatch)
    ws = _ws(tmp_path)
    (ws / "0-sources" / "IMG.JPG").write_bytes(b"AAAA")             # uppercase ext -> a rename op
    cache = prep.WorkspaceCache(str(ws))
    plan = prep.WorkspacePrepWorkflow(str(ws), cache).plan()
    cache.close()
    prep.PlanExecutor(str(ws)).execute(plan)

    op_dests = {op.destination for op in plan.operations if op.destination}
    op_srcs = {op.source for op in plan.operations if op.source}
    planned_names = {os.path.basename(p) for p in op_dests | op_srcs}
    entry = next(iter(_log(ws)["photos"].values()))
    # The log's terminal location is one the plan actually planned — not a fact the log invented.
    assert entry["final_path"] in op_dests, (entry["final_path"], sorted(op_dests))
    # The extension-normalization step's 'from' name is the plan's rename source — derived, not new.
    norm = [s for s in entry["journey"] if s["action"] == "extension_normalized"]
    assert norm and norm[0]["from"] == "IMG.JPG"
    assert "IMG.JPG" in planned_names, sorted(planned_names)
    # The provisional rename's target filename is the basename of a path the plan planned.
    prov = [s for s in entry["journey"] if s["action"] == "provisional_rename"]
    assert prov and os.path.basename(prov[0]["to"]) in planned_names, (prov, sorted(planned_names))


def test_strays_and_other_not_logged(tmp_path, monkeypatch):
    _install(monkeypatch)
    ws = _ws(tmp_path)
    (ws / "0-sources" / "a.jpg").write_bytes(b"AAAA")
    (ws / "0-sources" / "notes.txt").write_bytes(b"hello")   # stray
    _run(ws)
    photos = _log(ws)["photos"]
    assert len(photos) == 1                                  # only the photo
    assert not any("notes" in json.dumps(e) for e in photos.values())


@pytest.mark.spec("prep-log-incremental-1")
def test_noop_rerun_leaves_log_byte_identical(tmp_path, monkeypatch):
    _install(monkeypatch)
    ws = _ws(tmp_path)
    (ws / "0-sources" / "a.jpg").write_bytes(b"AAAA")
    _run(ws)
    first = open(utils.prep_log_path(str(ws)), "rb").read()
    _run(ws)                                                 # no-op
    assert open(utils.prep_log_path(str(ws)), "rb").read() == first


@pytest.mark.spec("log-entry-append-only-1")
def test_recognized_move_appends_moved_to_by_dest(tmp_path, monkeypatch):
    _install(monkeypatch)
    ws = _ws(tmp_path)
    (ws / "0-sources" / "a.jpg").write_bytes(b"AAAA")
    _run(ws)
    organized = glob.glob(str(ws / "5-photos-by-date" / "**" / "*.jpg"), recursive=True)[0]
    fp_before = next(iter(_log(ws)["photos"]))
    # user moves the photo into by-dest
    dest_dir = ws / "6-photos-by-dest" / "Trip"
    dest_dir.mkdir(parents=True)
    os.rename(organized, dest_dir / os.path.basename(organized))
    _run(ws)                                                 # prep recognizes the move
    entry = _log(ws)["photos"][fp_before]                    # same fingerprint key
    assert entry["final_path"].startswith("6-photos-by-dest/Trip/")
    moves = [s for s in entry["journey"] if s["action"] == "moved_to_by_dest"]
    assert len(moves) == 1 and moves[0]["to"].startswith("6-photos-by-dest/Trip/")
    # the unmoved prep steps were carried forward, not re-derived (still exactly one organize)
    assert sum(1 for s in entry["journey"] if s["action"] == "organized") == 1


@pytest.mark.spec("log-human-readable-json-1", "prep-prep-log-on-success-1")
def test_log_is_deterministic_and_in_control_dir(tmp_path, monkeypatch):
    _install(monkeypatch)
    ws = _ws(tmp_path)
    (ws / "0-sources" / "a.jpg").write_bytes(b"AAAA")
    (ws / "0-sources" / "b.jpg").write_bytes(b"BBBB")
    _run(ws)
    assert os.path.exists(ws / ".photos-ingest" / "photos-15-prep-log.json")
    raw = open(utils.prep_log_path(str(ws))).read()
    assert json.dumps(json.loads(raw)["photos"], sort_keys=True)   # parses; keys are sorted on write
    assert list(_log(ws)["photos"]) == sorted(_log(ws)["photos"])  # fingerprint-sorted


@pytest.mark.spec("log-fail-if-insufficient-1", "prep-log-fail-if-history-insufficient-1")
def test_missing_history_warns_and_marks_partial(tmp_path, monkeypatch):
    _install(monkeypatch)
    ws = _ws(tmp_path)
    # An already-organized file with no prior prep-log/journal: history is unreconstructable.
    (ws / "5-photos-by-date" / "2023-01-02").mkdir()
    (ws / "5-photos-by-date" / "2023-01-02" / "2023-01-02--03-04-05-001.jpg").write_bytes(b"AAAA")
    _run(ws)
    entry = next(iter(_log(ws)["photos"].values()))
    assert entry.get("partial") is True
    assert "incomplete" in entry.get("note", "")
