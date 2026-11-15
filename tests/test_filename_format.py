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

"""Outside the inbox every media file carries the name the pipeline gave it, and the filename format
is fixed once prep has named files in it (RUL-format_fixed_once_named)."""
import hashlib
import json
import os

import pytest

import photos_1_prep as prep
import photos_utils as utils

TIME = "2023:01:02 03:04:05"
NAME = "2023-01-02--03-04-05"


def _ws(tmp_path):
    ws = tmp_path / "ws"
    ws.mkdir()
    for d in ("0-sources", "1-strays", "2-missing-metadata", "3-redundant-jpgs",
              "4-videos-by-date", "5-photos-by-date", "6-photos-by-dest"):
        (ws / d).mkdir()
    (ws / ".photos-ingest").mkdir()
    (ws / ".photos-ingest" / "photos-00-workspace-guard").touch()
    return ws


@pytest.fixture
def mocks(monkeypatch):
    """Every file is recorded at TIME, but for a name holding "notime", which has no recorded time."""
    def fp(p):
        with open(p, "rb") as f:
            return {"status": "valid", "strategy": "image-content-hash-v2",
                    "value": "sig-" + hashlib.sha256(f.read()).hexdigest(), "engine_version": "t"}
    monkeypatch.setattr(prep.ContentHasher, "fingerprint_image", fp)

    def meta(folders, max_workers=4, progress_coordinator=None):
        res = {}
        for folder in folders:
            for f in os.listdir(folder):
                md = {"extraction_status": "extracted_ok"}
                if "notime" not in f:
                    md["DateTimeOriginal"] = TIME
                res[os.path.join(folder, f)] = md
        return res, set()
    monkeypatch.setattr(utils.MetadataReader, "read_metadata_concurrently", meta)
    prep.CONFIG["jobs"] = 1


def _put(ws, rel, content=None):
    p = ws / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_bytes(content if content is not None else rel.encode())


def _plan(ws):
    cache = prep.WorkspaceCache(str(ws))
    try:
        return prep.WorkspacePrepWorkflow(str(ws), cache).plan()
    finally:
        cache.close()


def _misnamed(plan):
    return [b for b in plan.blockers if b.startswith("Misnamed file")]


@pytest.mark.spec("RUL-misnamed_file_stops_prep", "RUL-misnamed_file_named",
                  test="TST-filename_format-misnamed_file_outside_inbox_stops_prep")
def test_misnamed_file_outside_inbox_stops_prep(tmp_path, mocks):
    ws = _ws(tmp_path)
    fine = [f"5-photos-by-date/2023-01-02/{NAME}.jpg", f"5-photos-by-date/2023-01-02/{NAME}-001.jpg",
            f"6-photos-by-dest/Rome/{NAME}-002.jpg", f"3-redundant-jpgs/{NAME}.jpg",
            "2-missing-metadata/UNKN_notime.jpg", "6-photos-by-dest/Rome/UNKN_notime-b.jpg"]
    bad = ["5-photos-by-date/2023-01-02/holiday.jpg",              # renamed by hand
           "6-photos-by-dest/Rome/2023-01-02--03-04-06.jpg",       # another time than its own
           "3-redundant-jpgs/IMG_0001.jpg",                        # a dump name
           "2-missing-metadata/notime.jpg",                        # no untimed mark
           "6-photos-by-dest/Rome/notime-c.jpg"]                   # no time, no mark
    for rel in fine + bad:
        _put(ws, rel)
    found = _misnamed(_plan(ws))
    assert len(found) == len(bad), found
    for rel in bad:                                                # every one named, none of the rest
        assert sum(rel in b for b in found) == 1, (rel, found)


@pytest.mark.spec("RUL-misnamed_file_expected_name",
                  test="TST-filename_format-misnamed_file_given_the_name_it_should_carry")
def test_misnamed_file_given_the_name_it_should_carry(tmp_path, mocks):
    """Each misnamed file is named together with the name it should carry: its recorded time in the
    format with its own extension, or — with no recorded time — its name behind the untimed mark."""
    ws = _ws(tmp_path)
    should_carry = {"5-photos-by-date/2023-01-02/holiday.jpg": f"{NAME}.jpg",
                    "6-photos-by-dest/Rome/IMG_0001.png": f"{NAME}.png",
                    "2-missing-metadata/notime.jpg": "UNKN_notime.jpg",
                    "6-photos-by-dest/Rome/notime-c.jpg": "UNKN_notime-c.jpg"}
    for rel in should_carry:
        _put(ws, rel)
    found = _misnamed(_plan(ws))
    assert len(found) == len(should_carry), found
    for rel, name in should_carry.items():
        mine = [b for b in found if rel in b]
        assert len(mine) == 1 and f"expected {name})" in mine[0], (rel, name, found)


@pytest.mark.spec("RUL-suffix_deterministic", test="TST-filename_format-suffix_allocation_is_deterministic")
def test_suffix_allocation_is_deterministic(tmp_path, mocks, monkeypatch):
    """Which file gets which differentiating suffix does not depend on the order the files are met in:
    the same files, listed by the filesystem in the opposite order, are given the same names."""
    def moves(ws):
        return {op.source: op.destination for op in _plan(ws).operations if op.type == "move_no_clobber"}

    def build(name):
        (tmp_path / name).mkdir()
        ws = _ws(tmp_path / name)
        _put(ws, f"5-photos-by-date/2023-01-02/{NAME}.jpg", b"already there")   # the bare name is taken
        for n in ("c.jpg", "a.jpg", "sub/b.jpg", "d.jpg"):
            _put(ws, "0-sources/" + n)
        return ws

    first = moves(build("one"))
    assert first == {"0-sources/a.jpg": f"5-photos-by-date/2023-01-02/{NAME}-001.jpg",
                     "0-sources/c.jpg": f"5-photos-by-date/2023-01-02/{NAME}-002.jpg",
                     "0-sources/d.jpg": f"5-photos-by-date/2023-01-02/{NAME}-003.jpg",
                     "0-sources/sub/b.jpg": f"5-photos-by-date/2023-01-02/{NAME}-004.jpg"}

    real_walk, real_listdir = os.walk, os.listdir

    def walk(top, *a, **k):
        for root, dirs, files in real_walk(top, *a, **k):
            dirs.sort(reverse=True)
            yield root, dirs, sorted(files, reverse=True)
    monkeypatch.setattr(os, "walk", walk)
    monkeypatch.setattr(os, "listdir", lambda *a: sorted(real_listdir(*a), reverse=True))
    assert moves(build("two")) == first
    monkeypatch.setattr(os, "walk", lambda top, *a, **k: (
        (r, d, sorted(f)) for r, d, f in real_walk(top, *a, **k) if not d.sort()))
    monkeypatch.setattr(os, "listdir", lambda *a: sorted(real_listdir(*a)))
    assert moves(build("three")) == first


@pytest.mark.spec("RUL-no_meaning_from_names", test="TST-filename_format-inbox_name_off_its_time_named_from_metadata")
def test_inbox_name_off_its_time_named_from_metadata(tmp_path, mocks):
    ws = _ws(tmp_path)
    _put(ws, "0-sources/2020-05-05--10-10-10.jpg")                 # looks like another time
    _put(ws, "0-sources/whatever.jpg", b"other")
    plan = _plan(ws)
    assert plan.blockers == [], plan.blockers
    dests = sorted(op.destination for op in plan.operations if op.type == "move_no_clobber")
    assert dests == [f"5-photos-by-date/2023-01-02/{NAME}-001.jpg", f"5-photos-by-date/2023-01-02/{NAME}.jpg"]


@pytest.mark.spec("RUL-misnamed_file_stops_prep", test="TST-filename_format-wrong_day_file_moves_without_blocker")
def test_wrong_day_file_moves_without_blocker(tmp_path, mocks):
    ws = _ws(tmp_path)
    _put(ws, f"5-photos-by-date/2023-01-05/{NAME}.jpg")             # its name is right, its day folder not
    plan = _plan(ws)
    assert plan.blockers == [], plan.blockers
    assert [op.destination for op in plan.operations if op.type == "move_no_clobber"] == \
        [f"5-photos-by-date/2023-01-02/{NAME}.jpg"]


@pytest.mark.spec("RUL-redundant_jpg_timestamp_named", test="TST-filename_format-redundant_jpg_named_from_its_time")
def test_redundant_jpg_named_from_its_time(tmp_path, mocks):
    ws = _ws(tmp_path)
    _put(ws, "0-sources/DSC_1.ARW")
    _put(ws, "0-sources/DSC_1.jpg")
    _put(ws, "0-sources/notime.ARW")
    _put(ws, "0-sources/notime.jpg")
    _put(ws, f"5-photos-by-date/2023-01-02/{NAME}.jpg")             # the timestamp name is taken
    plan = _plan(ws)
    assert plan.blockers == [], plan.blockers
    moved = {op.source: op.destination for op in plan.operations if op.type == "move_no_clobber"}
    assert moved["0-sources/DSC_1.jpg"] == f"3-redundant-jpgs/{NAME}-001.jpg"
    assert moved["0-sources/notime.jpg"] == "3-redundant-jpgs/UNKN_notime.jpg"


def _set_format(ws, fmt):
    p = ws / ".photos-ingest" / "photos-00-config.json"
    cfg = json.loads(p.read_text())
    cfg["filename_timestamp_format"] = fmt
    p.write_text(json.dumps(cfg))


@pytest.mark.spec("RUL-format_fixed_once_named", test="TST-filename_format-format_change_after_naming_stops_prep")
def test_format_change_after_naming_stops_prep(tmp_path, mocks):
    ws = _ws(tmp_path)
    _put(ws, "0-sources/a.jpg")
    _put(ws, "0-sources/b.jpg", b"b")
    prep.PlanExecutor(str(ws)).execute(_plan(ws))
    handoff = json.loads(open(utils.handoff_path(str(ws))).read())
    assert handoff["filename_timestamp_format"] == "%Y-%m-%d--%H-%M-%S"   # the format the names are in
    _set_format(ws, "%Y%m%d_%H%M%S")
    plan = _plan(ws)
    assert _misnamed(plan) == []                                     # one blocker, not one per name
    assert [b for b in plan.blockers if "filename format has changed" in b] == [
        utils.filename_format_changed("%Y-%m-%d--%H-%M-%S", "%Y%m%d_%H%M%S")]


@pytest.mark.spec("RUL-format_fixed_once_named", test="TST-filename_format-format_free_while_nothing_named")
def test_format_free_while_nothing_named(tmp_path, mocks):
    ws = _ws(tmp_path)
    _put(ws, "0-sources/notime.jpg")                                 # untimed: named by its mark only
    prep.PlanExecutor(str(ws)).execute(_plan(ws))
    _set_format(ws, "%Y%m%d_%H%M%S")
    _put(ws, "0-sources/a.jpg")
    plan = _plan(ws)
    assert plan.blockers == [], plan.blockers
    assert any(op.destination == "5-photos-by-date/2023-01-02/20230102_030405.jpg" for op in plan.operations)


@pytest.mark.spec("RUL-prep_name_provisional", test="TST-filename_format-prep_names_from_the_time_as_recorded")
def test_prep_names_from_the_time_as_recorded(tmp_path, monkeypatch):
    """Prep names a photo, and files it by day, from its time as the camera recorded it: not moved by the offset
    from UTC the camera recorded beside it, by its GPS time, by the workspace's default timezone or by the
    machine's own."""
    import time
    def fp(p):
        with open(p, "rb") as f:
            return {"status": "valid", "strategy": "image-content-hash-v2",
                    "value": "sig-" + hashlib.sha256(f.read()).hexdigest(), "engine_version": "t"}
    monkeypatch.setattr(prep.ContentHasher, "fingerprint_image", fp)
    recorded = {"a.jpg": {"DateTimeOriginal": "2023:01:02 03:04:05", "OffsetTimeOriginal": "+09:00",
                          "OffsetTime": "+09:00", "TimeZone": "+09:00", "GPSDateTime": "2023:01:01 18:04:05Z",
                          "GPSDateStamp": "2023:01:01", "GPSTimeStamp": "18:04:05", "Make": "SONY",
                          "Model": "ILCE-6400", "SerialNumber": "123"},
                "b.jpg": {"CreateDate": "2023:07:31 23:30:00", "OffsetTimeDigitized": "-05:00"}}
    def meta(folders, max_workers=4, progress_coordinator=None):
        return {os.path.join(folder, f): dict(recorded[f], extraction_status="extracted_ok")
                for folder in folders for f in os.listdir(folder)}, set()
    monkeypatch.setattr(utils.MetadataReader, "read_metadata_concurrently", meta)
    prep.CONFIG["jobs"] = 1
    ws = _ws(tmp_path)
    cfg = {k: v for k, v in utils.DEFAULT_CONFIG.items() if k != "jobs"}
    cfg["camera_time_and_timezone_policy"] = dict(cfg["camera_time_and_timezone_policy"],
                                                  default_folder_timezone="Pacific/Kiritimati")
    (ws / ".photos-ingest" / "photos-00-config.json").write_text(json.dumps(cfg))
    _put(ws, "0-sources/a.jpg")
    _put(ws, "0-sources/b.jpg")
    machine_zone = os.environ.get("TZ")
    os.environ["TZ"] = "Pacific/Pago_Pago"                           # the machine's zone: UTC-11
    time.tzset()
    try:
        plan = _plan(ws)
    finally:
        if machine_zone is None:
            del os.environ["TZ"]
        else:
            os.environ["TZ"] = machine_zone
        time.tzset()
    assert plan.blockers == [], plan.blockers
    moved = {op.source: op.destination for op in plan.operations if op.type == "move_no_clobber"}
    assert moved == {"0-sources/a.jpg": "5-photos-by-date/2023-01-02/2023-01-02--03-04-05.jpg",
                     "0-sources/b.jpg": "5-photos-by-date/2023-07-31/2023-07-31--23-30-00.jpg"}, moved


@pytest.mark.spec("RUL-one_filename_format", test="TST-filename_format-prep_and_geotag_name_in_the_one_format")
def test_prep_and_geotag_name_in_the_one_format(tmp_path, monkeypatch):
    """Prep's provisional names and geotag's final names are in the one format the workspace's configuration
    sets — here not the built-in one: a photo whose time geotag corrects is renamed in it, and a photo whose time
    needs no correction keeps the name prep gave it."""
    import sys
    from _zone import answer_root_zone
    import photos_2_geotag as cal
    fmt = "%Y%m%d_%H%M%S"
    gpx = tmp_path / "gpx"; gpx.mkdir()
    (gpx / "t.gpx").write_text(
        '<gpx xmlns="http://www.topografix.com/GPX/1/1"><trk><trkseg>'
        '<trkpt lat="50.0" lon="4.0"><time>2024-07-03T12:00:00Z</time></trkpt>'
        '<trkpt lat="51.0" lon="5.0"><time>2024-07-03T13:00:00Z</time></trkpt>'
        '</trkseg></trk></gpx>')
    shots = {"a.arw": ("2024:07:03 14:00:00", "SONY", "123", 50.0, 4.0),        # its clock on Brussels time
             "b.arw": ("2024:07:03 15:00:00", "SONY", "123", 51.0, 5.0),
             "c.arw": ("2024:07:03 15:30:00", "NIKON", "9", 50.0, 4.0),         # its clock an hour fast
             "d.arw": ("2024:07:03 16:30:00", "NIKON", "9", 51.0, 5.0)}
    first = {}
    def meta(folders, max_workers=4, progress_coordinator=None):
        out = {}
        for folder in folders:
            for r, _d, fs in os.walk(folder):
                for n in fs:
                    p = os.path.join(r, n)
                    dto, make, serial, lat, lon = shots[first.setdefault(os.stat(p).st_ino, n)]
                    out[p] = utils.MetadataReader._parse_exiftool_item({
                        "SourceFile": p, "EXIF:DateTimeOriginal": dto, "EXIF:Make": make, "EXIF:Model": "X",
                        "EXIF:SerialNumber": serial, "Composite:GPSLatitude": lat, "Composite:GPSLongitude": lon})
        return out, set()
    monkeypatch.setattr(utils.MetadataReader, "read_metadata_concurrently", meta)
    monkeypatch.setattr(prep.ContentHasher, "fingerprint_image", staticmethod(
        lambda p: {"status": "valid", "strategy": "image-content-hash-v2",
                   "value": "fp-" + first.get(os.stat(p).st_ino, os.path.basename(p)), "engine_version": "t"}))
    monkeypatch.setattr(cal.GeotagWorkflow, "_exiftool_write", lambda self, p, t: True)
    ws = _ws(tmp_path)
    cfg = {k: v for k, v in utils.DEFAULT_CONFIG.items() if k != "jobs"}
    cfg["filename_timestamp_format"] = fmt
    cfg["gpx_root"] = str(gpx)
    cfg["camera_time_and_timezone_policy"] = dict(
        cfg["camera_time_and_timezone_policy"], default_folder_timezone="Europe/Brussels",
        device_groups={"fixed_clock_cameras": ["123|SONY|X", "9|NIKON|X"], "phones": []})
    (ws / ".photos-ingest" / "photos-00-config.json").write_text(json.dumps(cfg))
    for n in shots:
        _put(ws, f"0-sources/{n}", n.encode())

    def run(phase, *argv):
        utils.CONFIG.clear(); utils.CONFIG.update(json.loads(json.dumps(utils.DEFAULT_CONFIG)))     # each a run of its own
        monkeypatch.chdir(ws)
        monkeypatch.setattr(sys, "argv", [phase, *argv])
        try:
            rc = prep.main(list(argv)) if phase == "photos-1-prep" else cal.main()
        except SystemExit as e:
            rc = e.code
        assert rc in (0, None), (phase, argv, rc)
    run("photos-1-prep", "-j", "1", "plan"); run("photos-1-prep", "-j", "1", "execute")
    day = ws / "5-photos-by-date" / "2024-07-03"
    assert sorted(os.listdir(day)) == ["20240703_140000.arw", "20240703_150000.arw",
                                       "20240703_153000.arw", "20240703_163000.arw"]
    (ws / "6-photos-by-dest" / "T").mkdir()
    for n in os.listdir(day):                                        # the user sorts them into a destination
        os.rename(day / n, ws / "6-photos-by-dest" / "T" / n)
    run("photos-1-prep", "-j", "1", "plan"); run("photos-1-prep", "-j", "1", "execute")
    answer_root_zone(ws / ".photos-ingest")
    run("photos-2-geotag", "plan")
    run("photos-2-geotag", "plan")
    plan = json.load(open(ws / ".photos-ingest" / "photos-24-executable-plan.json"))
    renames = {o["from"]: o["to"] for d in plan["destinations"].values() for o in d["operations"]
               if o["type"] == "rename_no_clobber"}
    assert renames == {"20240703_153000.arw": "20240703_140000-001.arw",
                       "20240703_163000.arw": "20240703_150000-001.arw"}, renames
    run("photos-2-geotag", "execute")
    assert sorted(os.listdir(ws / "6-photos-by-dest" / "T")) == [
        "20240703_140000-001.arw", "20240703_140000.arw", "20240703_150000-001.arw", "20240703_150000.arw"]
