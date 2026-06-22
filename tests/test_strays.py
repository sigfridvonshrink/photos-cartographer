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

Non-media (other-class) is never fingerprinted/deduped (§9); it is moved inert into
1-strays/<plan-id>/<rel> with its structure preserved (§3.2/§7.6), untracked and scan-skipped,
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


@pytest.mark.spec("prep-sources-empty-after-stage5-1", "prep-strays-per-run-subfolder-1")
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


@pytest.mark.spec("prep-other-not-fingerprinted-1", "prep-strays-inert-1")
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


@pytest.mark.spec("prep-scan-skips-control-subtrees-1", "prep-strays-excluded-from-scan-1")
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
    assert len(glob.glob(str(ws / "5-photos-by-date" / "**" / "*.jpg"), recursive=True)) == 1
    assert glob.glob(str(ws / "1-strays" / "*" / "notes.txt"))
    assert list((ws / "0-sources").iterdir()) == []


@pytest.mark.spec("prep-stray-media-warning-1")
def test_stray_media_detection_warns_only_for_media_mime(tmp_path, monkeypatch):
    # An unlisted RAW (.raf) and a real non-media (.txt) both land in strays. exiftool sees the .raf as
    # image/*, the .txt as text/plain -> only the .raf gets the "add to media_extensions" hint.
    _install(monkeypatch)
    ws = _ws(tmp_path)
    (ws / "0-sources" / "DSCF1.raf").write_bytes(b"raw")        # not in default media_extensions -> stray
    (ws / "0-sources" / "notes.txt").write_bytes(b"hello")      # genuine non-media stray
    mimes = {".raf": "image/x-fujifilm-raf", ".txt": "text/plain"}
    monkeypatch.setattr(utils, "exiftool_mime_type",
                        lambda p: mimes.get(os.path.splitext(p)[1].lower()))
    plan = _plan(ws)
    raf_warn = [w for w in plan.warnings if ".raf" in w]
    assert raf_warn and "media_extensions" in raf_warn[0], plan.warnings
    assert not any(".txt" in w for w in plan.warnings)


@pytest.mark.spec("prep-stray-media-warning-advisory-1")
def test_stray_media_detection_silent_when_exiftool_absent(tmp_path, monkeypatch):
    # exiftool unavailable (probe returns None) -> no stray-media warning, never blocks.
    _install(monkeypatch)
    ws = _ws(tmp_path)
    (ws / "0-sources" / "DSCF1.raf").write_bytes(b"raw")
    monkeypatch.setattr(utils, "exiftool_mime_type", lambda p: None)
    plan = _plan(ws)
    assert not any(".raf" in w for w in plan.warnings)
