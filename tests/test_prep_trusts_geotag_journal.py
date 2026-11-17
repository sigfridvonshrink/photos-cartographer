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

"""Prep takes geotag's word from its journal (RUL-geotag_left_fingerprint_carried): a photo geotag's execution wrote
and confirmed, or renamed, is not fingerprinted again by the prep plan that follows while it is as that execution left
it — its metadata, which geotag wrote, is read again.

The whole flow runs for real — prep's plan and execute, geotag's plan and execute, and geotag's next plan with its
automatic re-prep — with the tools stood in for: the image fingerprint hashes what a photo held before any tag was
written to it (as the real one hashes the decoded pixels), and a tag write appends to the file, changing its size and
time. From conftest.py.
"""
import hashlib
import json
import os
import sys
import types

import pytest

from _handoff import recorded
from _zone import answer_root_zone
import photos_1_prep as prep
import photos_2_geotag as cal
import photos_utils as utils

CAM = "SONY|ILCE-6400|123"                    # its clock 5 minutes fast: geotag corrects its photos' time and name
CAM2 = "SONY|ILCE-7M3|456"                    # its clock right: its photos are written where they are
MANAGED = ["0-sources", "1-strays", "2-missing-metadata", "3-redundant-jpgs",
           "4-videos-by-date", "5-photos-by-date", "6-photos-by-dest"]
T = "6-photos-by-dest/T/"
# path -> (camera time, latitude, longitude, camera), each at a point of the track at its true time
PHOTOS = {T + "2024-07-03--14-05-00.arw": ("2024:07:03 14:05:00", 50.0, 4.0, CAM),
          T + "2024-07-03--15-05-00.arw": ("2024:07:03 15:05:00", 51.0, 5.0, CAM),
          T + "2024-07-03--14-15-00.arw": ("2024:07:03 14:15:00", 50.25, 4.25, CAM2),
          T + "2024-07-03--14-45-00.arw": ("2024:07:03 14:45:00", 50.75, 4.75, CAM2)}
RENAMED = {T + "2024-07-03--14-05-00.arw": T + "2024-07-03--14-00-00.arw",
           T + "2024-07-03--15-05-00.arw": T + "2024-07-03--15-00-00.arw"}
IN_PLACE = [T + "2024-07-03--14-15-00.arw", T + "2024-07-03--14-45-00.arw"]
LEFT = list(RENAMED.values()) + IN_PLACE       # where geotag's execution leaves the four


class _Rep:
    def __init__(self): self.logs, self.warns, self.errors = [], [], []
    def log(self, msg, **k): self.logs.append(msg)
    def warn(self, msg, **k): self.warns.append(msg)
    def error(self, msg, **k): self.errors.append(msg)


def _tags_of(path):
    with open(path, "rb") as f:
        parts = f.read().split(b"|")
    held = {}
    for p in parts[1:]:
        held.update(json.loads(p))
    return held


def _tools(monkeypatch, calls, altered=()):
    """The stand-ins; `calls` gets the name of each photo fingerprinted. A photo first put at a path in `altered` has
    its content changed by a tag write (its fingerprint after it is another)."""
    for mod in (utils, cal, prep):
        if hasattr(mod, "get_imagemagick_version"):
            monkeypatch.setattr(mod, "get_imagemagick_version", lambda: "t")

    def fingerprint(path):
        calls.append(os.path.basename(path))
        with open(path, "rb") as f:
            data = f.read()
        pixels = data.split(b"|")[0]                    # what the photo held before any tag was written
        if pixels.decode() in altered and b"|" in data:
            pixels += b"-altered"
        return {"status": "valid", "strategy": "image-content-hash-v2",
                "value": "sig-" + hashlib.sha256(pixels).hexdigest(), "engine_version": "t"}
    monkeypatch.setattr(utils.ContentHasher, "fingerprint_image", staticmethod(fingerprint))

    def write(self, path, tags):
        with open(path, "ab") as f:
            f.write(b"|" + json.dumps(tags).encode())
        return True
    monkeypatch.setattr(cal.GeotagWorkflow, "_exiftool_write", write)
    monkeypatch.setattr(cal.GeotagWorkflow, "_exiftool_read",
                        lambda self, p, keys: {k: v for k, v in _tags_of(p).items() if k in keys})

    def meta(folders, max_workers=4, progress_coordinator=None):
        out = {}
        for folder in folders:
            for name in os.listdir(folder):
                p = os.path.join(folder, name)
                with open(p, "rb") as f:
                    first = f.read().split(b"|")[0].decode()   # each photo holds the path it was first put at
                dto, lat, lon, cam = PHOTOS[first]
                dto = _tags_of(p).get("DateTimeOriginal", dto)  # the time geotag wrote, once it has
                out[p] = {"extraction_status": "extracted_ok", "DateTimeOriginal": dto,
                          "selected_source_naive_timestamp": dto, "selected_source_timestamp_tag": "DateTimeOriginal",
                          "camera_group_key": cam, "has_timestamp": True, "has_native_gps": True,
                          "GPSLatitude": lat, "GPSLongitude": lon}
        return out, set()
    monkeypatch.setattr(utils.MetadataReader, "read_metadata_concurrently", meta)


def _prep(ws, cmd):
    rep = _Rep()
    try:
        prep._run_locked(types.SimpleNamespace(command=cmd, jobs=1, accept_changes=None), str(ws), rep)
    except SystemExit as e:
        assert e.code in (0, None), (cmd, rep.errors)
    return rep


def _geotag(monkeypatch, ws, cmd):
    monkeypatch.chdir(str(ws))
    monkeypatch.setattr(sys, "argv", ["photos-2-geotag", cmd])
    try:
        cal.main()
    except SystemExit as e:
        return e.code if isinstance(e.code, int) else (0 if e.code is None else 1)
    return 0


def _executed(tmp_path, monkeypatch, calls, altered=()):
    """A workspace prep has recorded and geotag's execution has changed: two photos written and renamed to their
    corrected time, two written where they are. Returns (ws, the rows prep's database held before)."""
    _tools(monkeypatch, calls, altered)
    ws = tmp_path / "ws"; ws.mkdir()
    for d in MANAGED:
        (ws / d).mkdir()
    ctl = ws / ".photos-ingest"; ctl.mkdir()
    (ctl / "photos-00-workspace-guard").touch()
    gpx = tmp_path / "gpx"; gpx.mkdir()
    (gpx / "t.gpx").write_text(
        '<gpx xmlns="http://www.topografix.com/GPX/1/1"><trk><trkseg>'
        '<trkpt lat="50.0" lon="4.0"><time>2024-07-03T12:00:00Z</time></trkpt>'
        '<trkpt lat="50.25" lon="4.25"><time>2024-07-03T12:15:00Z</time></trkpt>'
        '<trkpt lat="50.75" lon="4.75"><time>2024-07-03T12:45:00Z</time></trkpt>'
        '<trkpt lat="51.0" lon="5.0"><time>2024-07-03T13:00:00Z</time></trkpt>'
        '</trkseg></trk></gpx>')
    cfg = {k: v for k, v in utils.CONFIG.items() if k != "jobs"}
    cfg["gpx_root"] = str(gpx)
    cfg["zfs"] = dict(cfg["zfs"], enabled=False)
    cfg["camera_time_and_timezone_policy"] = dict(
        cfg["camera_time_and_timezone_policy"], device_groups={"fixed_clock_cameras": [CAM, CAM2], "phones": []},
        default_folder_timezone="Europe/Brussels", multi_anchor_auto_apply=True)
    (ctl / "photos-00-config.json").write_text(json.dumps(cfg))
    answer_root_zone(ctl)
    for rel in PHOTOS:
        p = ws / rel; p.parent.mkdir(parents=True, exist_ok=True); p.write_bytes(rel.encode())
    _prep(ws, "plan"); _prep(ws, "execute")
    before = prep.WorkspaceCache(str(ws)).get_all_files()
    assert _geotag(monkeypatch, ws, "plan") == 0
    _geotag(monkeypatch, ws, "execute")
    calls.clear()
    return ws, before


def _fp(row):
    return json.loads(row["content_hash"])["value"]


@pytest.mark.spec("RUL-geotag_left_fingerprint_carried", "RUL-geotag_left_metadata_read", "BLD-geotag_journal_carried",
                  "BLD-media_after_identity", "RUL-fingerprint_taken_afresh", "BLD-geotag_auto_reprep",
                  test="TST-prep_trusts_geotag_journal-a_photo_geotag_left_is_not_fingerprinted_again")
def test_a_photo_geotag_left_is_not_fingerprinted_again(tmp_path, monkeypatch):
    """Geotag's execution writes four photos' time, renaming two to their corrected time. Geotag's next plan finds
    prep's record of them out of date and re-preps: prep fingerprints none of them, carrying each one's fingerprint
    from the row of the file geotag found — and reads again the metadata geotag wrote."""
    calls = []
    ws, before = _executed(tmp_path, monkeypatch, calls)
    assert sorted(os.listdir(ws / T)) == sorted(os.path.basename(p) for p in LEFT)
    plan = json.loads(open(utils.prep_plan_path(str(ws))).read())
    rep = _Rep()
    cal._auto_reprep_for_clean_move(types.SimpleNamespace(command="plan", jobs=1), str(ws), rep)
    assert any("Re-prep complete" in m for m in rep.logs), (rep.logs, rep.errors)
    assert calls == []                                                    # not one photo decoded again
    assert json.loads(open(utils.prep_plan_path(str(ws))).read())["plan_id"] != plan["plan_id"]
    rows = prep.WorkspaceCache(str(ws)).get_all_files()
    md = prep.WorkspaceCache(str(ws)).get_all_metadata()
    for old, new in list(RENAMED.items()) + [(p, p) for p in IN_PLACE]:
        st = os.stat(ws / new)
        assert (rows[new]["size"], rows[new]["mtime_ns"]) == (st.st_size, st.st_mtime_ns)
        assert _fp(rows[new]) == _fp(before[old])                          # the fingerprint geotag confirmed
        assert st.st_size != before[old]["size"]                           # though geotag wrote to it
        assert json.loads(md[new]["parsed_json"])["DateTimeOriginal"] == _tags_of(ws / new)["DateTimeOriginal"]
    assert not set(RENAMED) & set(rows)                                    # the names geotag left are gone


@pytest.mark.spec("RUL-geotag_left_fingerprint_carried", "BLD-geotag_journal_carried",
                  test="TST-prep_trusts_geotag_journal-a_photo_changed_since_geotag_left_it_is_fingerprinted_again")
def test_a_photo_changed_since_geotag_left_it_is_fingerprinted_again(tmp_path, monkeypatch):
    """A photo changed by hand after geotag's execution — renamed or written by it — no longer has the size and time
    the journal records, so prep fingerprints it again; the others it carries."""
    calls = []
    ws, _ = _executed(tmp_path, monkeypatch, calls)
    renamed, in_place = list(RENAMED.values())[0], IN_PLACE[0]
    for rel in (renamed, in_place):
        st = os.stat(ws / rel)
        os.utime(ws / rel, ns=(st.st_atime_ns, st.st_mtime_ns + 10**9))  # changed since
    recorded(ws)                                                            # taken as the workspace's state
    _prep(ws, "plan")
    assert sorted(calls) == sorted(os.path.basename(p) for p in (renamed, in_place))


@pytest.mark.spec("RUL-unreadable_geotag_journal_vouches_nothing", "BLD-geotag_journal_carried",
                  test="TST-prep_trusts_geotag_journal-an_unreadable_journal_vouches_for_nothing")
def test_an_unreadable_journal_vouches_for_nothing(tmp_path, monkeypatch, capsys):
    """Geotag's journal cannot be read: prep fingerprints every photo it records again, says why, and plans on."""
    calls = []
    ws, _ = _executed(tmp_path, monkeypatch, calls)
    (journal,) = [n for n in os.listdir(ws / ".photos-ingest") if n.startswith("journal-")
                  and "media_after" in open(ws / ".photos-ingest" / n).read()]
    (ws / ".photos-ingest" / journal).write_text("{ torn")
    capsys.readouterr()
    _prep(ws, "plan")                                                       # not stopped
    assert sorted(calls) == sorted(os.path.basename(p) for p in LEFT)
    out = capsys.readouterr()
    assert journal in out.out + out.err


@pytest.mark.spec("RUL-geotag_left_fingerprint_carried", "BLD-geotag_journal_carried", "BLD-media_after_identity",
                  test="TST-prep_trusts_geotag_journal-an_unconfirmed_write_is_fingerprinted_again")
def test_an_unconfirmed_write_is_fingerprinted_again(tmp_path, monkeypatch):
    """A write whose fingerprint geotag found changed is not confirmed: the journal records nothing of the photo, and
    prep fingerprints it again. An entry whose fingerprint is not the one prep holds carries nothing either."""
    calls = []
    ws, _ = _executed(tmp_path, monkeypatch, calls, altered=(IN_PLACE[0],))
    jpath = [os.path.join(ws, ".photos-ingest", n) for n in os.listdir(ws / ".photos-ingest")
             if n.startswith("journal-") and "media_after" in open(ws / ".photos-ingest" / n).read()][0]
    journal = json.loads(open(jpath).read())
    assert IN_PLACE[0] not in journal["media_after"]                        # held back, unconfirmed
    journal["media_after"][IN_PLACE[1]]["fingerprint"] = "sig-another"      # not the photo prep fingerprinted
    utils.write_json_artifact(jpath, journal)
    _prep(ws, "plan")
    assert sorted(calls) == sorted(os.path.basename(p) for p in IN_PLACE)


@pytest.mark.spec("RUL-geotag_left_fingerprint_carried", "RUL-fingerprint_method_matches", "BLD-geotag_journal_carried",
                  test="TST-prep_trusts_geotag_journal-another_image_engine_takes_every_fingerprint_again")
def test_another_image_engine_takes_every_fingerprint_again(tmp_path, monkeypatch):
    """The image engine changed since geotag's execution: the row prep holds would not be reused where geotag found the
    photo, so geotag's word carries nothing and every photo is fingerprinted again."""
    calls = []
    ws, _ = _executed(tmp_path, monkeypatch, calls)
    for mod in (utils, cal, prep):
        if hasattr(mod, "get_imagemagick_version"):
            monkeypatch.setattr(mod, "get_imagemagick_version", lambda: "t2")
    _prep(ws, "plan")
    assert sorted(calls) == sorted(os.path.basename(p) for p in LEFT)
