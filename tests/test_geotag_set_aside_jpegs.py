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

"""The names outside photos by destination: a JPEG prep set aside beside its RAW is renamed with that RAW, and nothing
else is done to it (RUL-set_aside_jpeg_renamed_with_raw); a video keeps the name prep gave it
(RUL-video_name_stays_uncorrected). Geotag is driven through `plan` and `execute` with exiftool and the image
fingerprint mocked; prep then plans over what geotag left."""
import json
import os
import sys

import pytest

from _handoff import vouched
from _zone import answer_root_zone
import photos_1_prep as prep
import photos_2_geotag as cal
import photos_utils as utils

CAM = "SONY|ILCE-6400|123"
MANAGED = ["0-sources", "1-strays", "2-missing-metadata", "3-redundant-jpgs",
           "4-videos-by-date", "5-photos-by-date", "6-photos-by-dest"]
AWAY = "2024-07-03--15-00-00"          # camera time of the first RAW: its clock an hour ahead of Brussels
HOME = "2024-07-03--14-00-00"          # its true time at the destination


def _record(ws, rel, media_class, folder_class, parsed=None):
    p = ws / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_bytes(b"img-" + rel.encode())
    st = p.stat()
    rec = {"relative_path": rel, "media_class": media_class, "folder_class": folder_class,
           "size": st.st_size, "mtime_ns": st.st_mtime_ns,
           "content_hash": json.dumps({"value": "fp-" + rel, "status": "valid"})}
    if parsed is not None:
        rec["metadata_status"] = {"camera_group_key_version": utils.CAMERA_GROUP_KEY_VERSION, "camera_group_key": CAM,
                                  "has_timestamp": True, "has_native_gps": True,
                                  "field_set_version": utils.FIELD_SET_VERSION, "parsed_json": json.dumps(parsed)}
    return rec


def _photo(ws, rel, dto, lat, lon):
    return _record(ws, rel, "raw", "6-photos-by-dest", {
        "DateTimeOriginal": dto, "selected_source_naive_timestamp": dto,
        "selected_source_timestamp_tag": "DateTimeOriginal", "camera_group_key": CAM,
        "has_timestamp": True, "has_native_gps": True, "GPSLatitude": lat, "GPSLongitude": lon})


def _workspace(tmp_path, monkeypatch, extra=(), raws=None):
    """Two RAWs in a destination whose native positions put the camera's clock an hour ahead — or the RAWs `raws`
    makes of the workspace; beside the first, the JPEG prep set aside under its camera time; and the files of `extra`
    — (relative path, media class, raw partner's relative path or None). Planned through to a ready photos-24.
    Returns (ws, control dir)."""
    ws = tmp_path / "ws"; ws.mkdir()
    for d in MANAGED:
        (ws / d).mkdir()
    ctl = ws / ".photos-ingest"; ctl.mkdir()
    (ctl / "photos-00-workspace-guard").touch()
    gpx = tmp_path / "gpx"; gpx.mkdir()
    (gpx / "t.gpx").write_text(
        '<gpx xmlns="http://www.topografix.com/GPX/1/1"><trk><trkseg>'
        '<trkpt lat="50.0" lon="4.0"><time>2024-07-03T12:00:00Z</time></trkpt>'
        '<trkpt lat="51.0" lon="5.0"><time>2024-07-03T13:00:00Z</time></trkpt>'
        '</trkseg></trk></gpx>')
    cfg = {k: v for k, v in utils.CONFIG.items() if k != "jobs"}
    cfg["gpx_root"] = str(gpx)
    cfg["camera_time_and_timezone_policy"] = dict(
        cfg["camera_time_and_timezone_policy"], device_groups={"fixed_clock_cameras": [CAM], "phones": []},
        default_folder_timezone="Europe/Brussels", multi_anchor_auto_apply=True)
    (ctl / "photos-00-config.json").write_text(json.dumps(cfg))
    answer_root_zone(ctl)

    raws = raws(ws) if raws else [
        _photo(ws, f"6-photos-by-dest/T/{AWAY}.arw", "2024:07:03 15:00:00", 50.0, 4.0),
        _photo(ws, "6-photos-by-dest/T/2024-07-03--16-00-00.arw", "2024:07:03 16:00:00", 51.0, 5.0)]
    aside = [(f"3-redundant-jpgs/{AWAY}.jpg", "image", raws[0]["relative_path"])] + list(extra)
    files, log = list(raws), {}
    for rel, media_class, partner in aside:
        rec = _record(ws, rel, media_class, rel.split("/", 1)[0])
        files.append(rec)
        if partner:
            # prep's record of the pair: the JPEG's own entry names the RAW it was set aside beside
            rec["raw_fingerprint"] = "fp-" + partner
            log["fp-" + rel] = {"content_fingerprint": "fp-" + rel, "journey": [
                {"phase": "prep", "action": "redundant_jpeg_separated", "run": "prep-1",
                 "from": "0-sources/DSC_1.JPG", "to": rel, "raw_fingerprint": "fp-" + partner}]}
    (ctl / "photos-15-prep-log.json").write_text(json.dumps({"photos": log}))
    ho = {"filename_timestamp_format": utils.CONFIG["filename_timestamp_format"],
          "run_metadata": {"plan_id": "prep-1", "execution_id": "exec-1"}, "files": files, "cache_fingerprint": "pcf",
          "depends_on": {"cache": {"image_engine_version": utils.get_imagemagick_version(),
                                   "fingerprint_algorithm_version": utils.FINGERPRINT_ALGORITHM_VERSION}}}
    ho["content_fingerprint"] = utils.handoff_content_fingerprint(ho)
    (ctl / "photos-11-handoff.json").write_text(json.dumps(vouched(ctl.parent, ho)))
    utils.write_workspace_record(str(ws))
    _geotag(monkeypatch, ws, "plan")
    _geotag(monkeypatch, ws, "plan")
    assert (ctl / "photos-24-executable-plan.json").exists()
    return ws, ctl


def _geotag(monkeypatch, ws, command):
    monkeypatch.chdir(str(ws))
    monkeypatch.setattr(sys, "argv", ["photos-2-geotag", command])
    try:
        cal.main()
        return 0
    except SystemExit as e:
        return e.code if isinstance(e.code, int) else (0 if e.code is None else 1)


def _tools(monkeypatch, ws):
    """exiftool and the image fingerprint as the real ones behave across a rename (kept by inode); returns the tags
    written, by inode."""
    first_name, held = {}, {}
    for d in MANAGED:                              # each file's fingerprint is the one its record holds
        for root, _dirs, names in os.walk(ws / d):
            for n in names:
                first_name[os.stat(os.path.join(root, n)).st_ino] = os.path.relpath(os.path.join(root, n), str(ws))

    def write(self, p, tags):
        held.setdefault(os.stat(p).st_ino, {}).update(tags)
        return True
    monkeypatch.setattr(cal.GeotagWorkflow, "_exiftool_write", write)
    monkeypatch.setattr(cal.GeotagWorkflow, "_exiftool_read",
                        lambda self, p, keys: {k: v for k, v in held.get(os.stat(p).st_ino, {}).items() if k in keys})

    def fp(path):
        rel = first_name.setdefault(os.stat(path).st_ino, os.path.relpath(path, str(ws)))
        return {"status": "valid", "strategy": utils.IMAGE_FINGERPRINT_STRATEGY, "value": "fp-" + rel,
                "engine_version": utils.get_imagemagick_version()}
    monkeypatch.setattr(cal.ContentHasher, "fingerprint_image", staticmethod(fp))
    return held


def _ops(ctl):
    plan = json.load(open(ctl / "photos-24-executable-plan.json"))
    return [o for d in plan["destinations"].values() for o in d["operations"]]


@pytest.mark.spec("RUL-set_aside_jpeg_renamed_with_raw", "RUL-set_aside_jpeg_only_renamed",
                  "BLD-set_aside_renamed_with_raw", "BLD-set_aside_pair_recorded",
                  test="TST-geotag_set_aside_jpegs-renamed_with_its_raw_and_nothing_else")
def test_renamed_with_its_raw_and_nothing_else(tmp_path, monkeypatch):
    """The JPEG set aside beside a RAW geotag renames takes the RAW's new name, its own extension kept: one rename,
    planned after the RAW's, and no tag written to it. One whose RAW is not in photos by destination, and one prep
    recorded no RAW for, are left as they are."""
    ws, ctl = _workspace(tmp_path, monkeypatch, extra=[
        ("3-redundant-jpgs/2024-07-03--09-00-00.jpg", "image", "5-photos-by-date/2024-07-03/2024-07-03--09-00-00.arw"),
        ("3-redundant-jpgs/2024-07-03--10-00-00.jpg", "image", None)])
    ops = _ops(ctl)
    raw = next(o for o in ops if o["type"] == "rename_no_clobber" and o["relative_path"].endswith(f"{AWAY}.arw"))
    assert raw["to"] == f"{HOME}.arw"
    outside = [o for o in ops if not o["relative_path"].startswith("6-photos-by-dest/")]
    assert [(o["type"], o["relative_path"], o["to"], o["follows"]) for o in outside] == [
        ("rename_no_clobber", f"3-redundant-jpgs/{AWAY}.jpg", f"{HOME}.jpg", raw["operation_id"])]

    held = _tools(monkeypatch, ws)
    jpeg_inode = (ws / "3-redundant-jpgs" / f"{AWAY}.jpg").stat().st_ino
    assert _geotag(monkeypatch, ws, "execute") == 0
    assert json.load(open(ctl / "photos-25-execution-summary.json"))["status"] == "success"
    assert (ws / "6-photos-by-dest" / "T" / f"{HOME}.arw").exists()
    assert sorted(os.listdir(ws / "3-redundant-jpgs")) == ["2024-07-03--09-00-00.jpg", "2024-07-03--10-00-00.jpg",
                                                           f"{HOME}.jpg"]
    assert (ws / "3-redundant-jpgs" / f"{HOME}.jpg").stat().st_ino == jpeg_inode
    assert jpeg_inode not in held                                  # a rename only: no tag written to it

    assert _geotag(monkeypatch, ws, "finalize") == 0               # the rename in the JPEG's own record
    entry = json.load(open(ctl / "photos-26-complete-log.json"))["photos"][f"fp-3-redundant-jpgs/{AWAY}.jpg"]
    assert [(s["action"], s.get("from"), s.get("to")) for s in entry["journey"] if s["phase"] == "geotag"] == [
        ("final_rename", f"{AWAY}.jpg", f"{HOME}.jpg")]
    assert entry["geotag_path"] == f"3-redundant-jpgs/{HOME}.jpg"


@pytest.mark.spec("RUL-set_aside_jpeg_renamed_with_raw", "BLD-set_aside_renamed_with_raw",
                  test="TST-geotag_set_aside_jpegs-a_held_raw_holds_its_jpeg")
def test_a_held_raw_holds_its_jpeg(tmp_path, monkeypatch):
    """A RAW whose rename does not happen keeps its JPEG's name with it: the JPEG is renamed only once its RAW's
    rename is confirmed."""
    ws, ctl = _workspace(tmp_path, monkeypatch)
    _tools(monkeypatch, ws)
    real = cal.GeotagWorkflow._apply_file

    def held_back(self, rel, ops, journal, accepted):
        if rel.endswith(f"{AWAY}.arw"):
            return {"relative_path": rel, "applied": [], "skipped": [], "failed": [o["operation_id"] for o in ops],
                    "blocker": f"{rel}: held", "mismatch": None, "error": "held"}
        return real(self, rel, ops, journal, accepted)
    monkeypatch.setattr(cal.GeotagWorkflow, "_apply_file", held_back)
    _geotag(monkeypatch, ws, "execute")
    assert (ws / "3-redundant-jpgs" / f"{AWAY}.jpg").exists() and (ws / "6-photos-by-dest" / "T" / f"{AWAY}.arw").exists()
    monkeypatch.setattr(cal.GeotagWorkflow, "_apply_file", real)
    assert _geotag(monkeypatch, ws, "execute") == 0                  # run again: the pair renamed together
    assert (ws / "3-redundant-jpgs" / f"{HOME}.jpg").exists() and (ws / "6-photos-by-dest" / "T" / f"{HOME}.arw").exists()


@pytest.mark.spec("RUL-set_aside_jpeg_catches_up", "BLD-set_aside_jpeg_catches_up", "RUL-set_aside_jpeg_only_renamed",
                  test="TST-geotag_set_aside_jpegs-a_jpeg_left_behind_takes_its_raws_name")
def test_a_jpeg_left_behind_takes_the_name_its_corrected_raw_holds(tmp_path, monkeypatch):
    """An earlier run renamed the RAW without its JPEG: the RAW holds its corrected time and name and geotag's mark,
    the JPEG is still under the camera's time. The plan renames nothing in photos by destination, and the JPEG to the
    name its RAW holds — a rename only, after no other — and the pair keeps one name."""
    def corrected(ws):
        rec = _record(ws, f"6-photos-by-dest/T/{HOME}.arw", "raw", "6-photos-by-dest", {
            "DateTimeOriginal": "2024:07:03 14:00:00", "OffsetTimeOriginal": "+02:00",
            "selected_source_naive_timestamp": "2024:07:03 14:00:00",
            "selected_source_timestamp_tag": "DateTimeOriginal", "camera_group_key": CAM, "has_timestamp": True,
            "has_native_gps": True, "GPSLatitude": 50.0, "GPSLongitude": 4.0, "GPSProcessingMethod": "+carto-time"})
        return [rec]
    ws, ctl = _workspace(tmp_path, monkeypatch, raws=corrected)
    ops = _ops(ctl)
    assert not [o for o in ops if o["type"] == "rename_no_clobber" and o["relative_path"].startswith("6-")]
    outside = [o for o in ops if not o["relative_path"].startswith("6-photos-by-dest/")]
    assert [(o["type"], o["relative_path"], o["to"], o["with_raw"], o.get("follows")) for o in outside] == [
        ("rename_no_clobber", f"3-redundant-jpgs/{AWAY}.jpg", f"{HOME}.jpg", f"6-photos-by-dest/T/{HOME}.arw", None)]

    held = _tools(monkeypatch, ws)
    jpeg_inode = (ws / "3-redundant-jpgs" / f"{AWAY}.jpg").stat().st_ino
    assert _geotag(monkeypatch, ws, "execute") == 0
    assert os.listdir(ws / "3-redundant-jpgs") == [f"{HOME}.jpg"]
    assert (ws / "3-redundant-jpgs" / f"{HOME}.jpg").stat().st_ino == jpeg_inode and jpeg_inode not in held
    assert _geotag(monkeypatch, ws, "finalize") == 0               # the rename in the JPEG's own record
    entry = json.load(open(ctl / "photos-26-complete-log.json"))["photos"][f"fp-3-redundant-jpgs/{AWAY}.jpg"]
    assert [(s["action"], s.get("to")) for s in entry["journey"] if s["phase"] == "geotag"] == [
        ("final_rename", f"{HOME}.jpg")]
    assert entry["geotag_path"] == f"3-redundant-jpgs/{HOME}.jpg"


@pytest.mark.spec("RUL-set_aside_jpeg_named_as_raw", "BLD-name_check", "RUL-execution_records_state",
                  test="TST-geotag_set_aside_jpegs-prep_after_geotag_takes_the_renamed_jpeg_as_named")
def test_prep_after_geotag_takes_the_renamed_jpeg_as_named(tmp_path, monkeypatch):
    """After geotag's execution the renamed JPEG is no change to the workspace check — the execution recorded it — and
    prep's next plan takes its name, its RAW's, as rightly given: no misnamed stop, and nothing moved or renamed. The
    same JPEG under a name of neither its time nor its RAW's still stops prep."""
    ws, ctl = _workspace(tmp_path, monkeypatch)
    held = _tools(monkeypatch, ws)
    assert _geotag(monkeypatch, ws, "execute") == 0
    record_id, record = utils.read_workspace_record(str(ws))
    assert utils.compare_workspace(record, utils.workspace_entries(str(ws))) == []

    times = {}                                     # each file's recorded time: geotag's written one, else the camera's
    for p in (ws / "6-photos-by-dest" / "T").iterdir():
        times[p.stat().st_ino] = (held.get(p.stat().st_ino) or {}).get("DateTimeOriginal")
    jpeg = ws / "3-redundant-jpgs" / f"{HOME}.jpg"
    times[jpeg.stat().st_ino] = "2024:07:03 15:00:00"           # no tag written: still the camera's time

    def meta(folders, max_workers=4, progress_coordinator=None):
        out = {}
        for folder in folders:
            for n in os.listdir(folder):
                p = os.path.join(folder, n)
                out[p] = {"DateTimeOriginal": times.get(os.stat(p).st_ino), "extraction_status": "extracted_ok"}
        return out, set()
    monkeypatch.setattr(utils.MetadataReader, "read_metadata_concurrently", meta)
    prep.CONFIG["jobs"] = 1

    def plan():
        cache = prep.WorkspaceCache(str(ws))
        try:
            return prep.WorkspacePrepWorkflow(str(ws), cache).plan()
        finally:
            cache.close()
    p = plan()
    assert not [b for b in p.blockers if b.startswith("Misnamed")], p.blockers
    assert not [op for op in p.operations if op.type in ("move_no_clobber", "rename_no_clobber", "quarantine_move")]

    os.rename(jpeg, ws / "3-redundant-jpgs" / "2024-07-03--13-00-00.jpg")   # neither its time nor its RAW's
    assert [b for b in plan().blockers if "3-redundant-jpgs/2024-07-03--13-00-00.jpg" in b]


@pytest.mark.spec("RUL-culled_raw_takes_its_jpeg", "RUL-culled_raw_jpeg_logged", "RUL-culled_raw_jpeg_recorded",
                  "BLD-culled_raw_found",
                  test="TST-geotag_set_aside_jpegs-a_raw_culled_after_geotag_takes_its_renamed_jpeg")
def test_a_raw_culled_after_geotag_takes_its_renamed_jpeg(tmp_path, monkeypatch):
    """A RAW culled from photos by destination after geotag renamed it and its JPEG: prep's next plan does not stop on
    the JPEG as misnamed — it quarantines it, its step naming the RAW by the path it was culled at and by
    fingerprint — and the execution leaves a workspace the next check finds unchanged."""
    ws, ctl = _workspace(tmp_path, monkeypatch)
    with open(ctl / "photos-11-handoff.json") as f:                 # the record prep's execution would have written
        utils.write_workspace_record(str(ws), cache_rows={r["relative_path"]: r for r in json.load(f)["files"]})
    held = _tools(monkeypatch, ws)
    assert _geotag(monkeypatch, ws, "execute") == 0
    jpeg = ws / "3-redundant-jpgs" / f"{HOME}.jpg"
    assert jpeg.exists()
    os.remove(ws / "6-photos-by-dest" / "T" / f"{HOME}.arw")                         # culled by hand

    times = {jpeg.stat().st_ino: "2024:07:03 15:00:00"}
    for p in (ws / "6-photos-by-dest" / "T").iterdir():
        times[p.stat().st_ino] = (held.get(p.stat().st_ino) or {}).get("DateTimeOriginal")

    def meta(folders, max_workers=4, progress_coordinator=None):
        out = {}
        for folder in folders:
            for n in os.listdir(folder):
                p = os.path.join(folder, n)
                out[p] = {"DateTimeOriginal": times.get(os.stat(p).st_ino), "extraction_status": "extracted_ok"}
        return out, set()
    monkeypatch.setattr(utils.MetadataReader, "read_metadata_concurrently", meta)
    prep.CONFIG["jobs"] = 1
    prep.CONFIG["zfs"] = {"enabled": False}

    changes, stop = utils.check_workspace(str(ws), "prep", "plan")
    assert stop is None
    cache = prep.WorkspaceCache(str(ws))
    try:
        plan = prep.WorkspacePrepWorkflow(str(ws), cache, workspace_changes=changes).plan()
    finally:
        cache.close()
    assert not [b for b in plan.blockers if b.startswith("Misnamed")], plan.blockers
    [op] = [op for op in plan.operations if op.type == "quarantine_move"]
    assert op.source == f"3-redundant-jpgs/{HOME}.jpg" and op.verification["kind"] == "raw_culled"
    assert (op.verification["raw_path"], op.verification["raw_fingerprint"]) == \
        (f"6-photos-by-dest/T/{HOME}.arw", f"fp-6-photos-by-dest/T/{AWAY}.arw")
    assert not plan.blockers, plan.blockers
    prep.PlanExecutor(str(ws), workspace_changes=changes).execute(plan)
    assert not jpeg.exists() and (ws / op.destination).exists()
    steps = json.load(open(ctl / "photos-15-prep-log.json"))["photos"][f"fp-3-redundant-jpgs/{AWAY}.jpg"]["journey"]
    assert (steps[-1]["action"], steps[-1]["raw_path"]) == ("raw_culled", f"6-photos-by-dest/T/{HOME}.arw")
    assert utils.check_workspace(str(ws), "prep", "plan") == ([], None)


@pytest.mark.spec("RUL-video_name_stays_uncorrected", "RUL-video_never_changed",
                  test="TST-geotag_set_aside_jpegs-a_video_keeps_its_name")
def test_a_video_keeps_its_name(tmp_path, monkeypatch):
    """A video keeps the name prep gave it from its camera's clock, uncorrected, while geotag corrects the names of
    the photos the same camera took in the same minutes."""
    ws, ctl = _workspace(tmp_path, monkeypatch, extra=[(f"4-videos-by-date/2024-07-03/{AWAY}.mp4", "video", None)])
    assert not [o for o in _ops(ctl) if o["relative_path"].endswith(".mp4")]
    _tools(monkeypatch, ws)
    assert _geotag(monkeypatch, ws, "execute") == 0
    assert (ws / "4-videos-by-date" / "2024-07-03" / f"{AWAY}.mp4").exists()
    assert (ws / "6-photos-by-dest" / "T" / f"{HOME}.arw").exists()          # the photo of that minute renamed
