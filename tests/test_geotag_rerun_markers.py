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

"""Geotag's own GPSProcessingMethod markers on a re-run (BLD-rerun_recognition).

A geotag marker means the file's time is already corrected; a position marker also means its
position is geotag's, ignored until placed again. A device's own GPSProcessingMethod value is native.
Execution is simulated: each plan's writes are folded into the handoff the way a re-prep would read
them back, so the re-run sees what the files hold. From conftest.py.
"""
import json
from _handoff import vouched
from _zone import answer_root_zone, with_root_zone
import os
import sys

import pytest

import photos_2_geotag as cal
import photos_utils as utils

CAM = "SONY|ILCE-6400|123"
PHONE = "Google|Pixel|p1"
MANAGED = ["0-sources", "1-strays", "2-missing-metadata", "3-redundant-jpgs",
           "4-videos-by-date", "5-photos-by-date", "6-photos-by-dest"]
T = "6-photos-by-dest/T"
SLOW = -6600       # the camera reads local (+02:00) time ten minutes slow: naive + SLOW = UTC


def _rec(ws, rel, dto, *, key=CAM, gps=None, method=None):
    parsed = {"DateTimeOriginal": dto, "selected_source_naive_timestamp": dto,
              "selected_source_timestamp_tag": "DateTimeOriginal", "camera_group_key": key, "has_timestamp": True}
    if gps:
        parsed.update(GPSLatitude=gps[0], GPSLongitude=gps[1], has_native_gps=True)
    if method:
        parsed["GPSProcessingMethod"] = method
    p = ws / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_bytes(b"img-" + rel.encode())
    st = p.stat()
    return {"relative_path": rel, "media_class": "image", "folder_class": "6-photos-by-dest",
            "size": st.st_size, "mtime_ns": st.st_mtime_ns,
            "content_hash": json.dumps({"value": "fp-" + os.path.basename(rel), "status": "valid"}),
            "metadata_status": {"camera_group_key_version": utils.CAMERA_GROUP_KEY_VERSION,
                                "camera_group_key": key, "has_timestamp": True, "has_native_gps": bool(gps),
                                "field_set_version": utils.FIELD_SET_VERSION, "parsed_json": json.dumps(parsed)}}


def _ws(tmp_path, recs):
    ws = tmp_path / "ws"; ws.mkdir()
    for d in MANAGED:
        (ws / d).mkdir()
    ctl = ws / ".photos-ingest"; ctl.mkdir()
    (ctl / "photos-00-workspace-guard").touch()
    gpx = tmp_path / "gpx"; gpx.mkdir()
    (gpx / "t.gpx").write_text(                  # 12:00Z-13:00Z, a point every ten minutes
        '<gpx xmlns="http://www.topografix.com/GPX/1/1"><trk><trkseg>'
        + "".join(f'<trkpt lat="{50 + i / 1000:.3f}" lon="4.0"><time>2024-07-03T12:{i}0:00Z</time></trkpt>'
                  for i in range(6))
        + '<trkpt lat="50.006" lon="4.0"><time>2024-07-03T13:00:00Z</time></trkpt>'
        '</trkseg></trk></gpx>')
    cfg = {k: v for k, v in utils.CONFIG.items() if k != "jobs"}
    cfg["gpx_root"] = str(gpx)
    cfg["camera_time_and_timezone_policy"] = dict(
        cfg["camera_time_and_timezone_policy"], device_groups={"fixed_clock_cameras": [CAM], "phones": [PHONE]},
        default_folder_timezone="Europe/Brussels", multi_anchor_auto_apply=True)
    (ctl / "photos-00-config.json").write_text(json.dumps(cfg))
    answer_root_zone(ctl)                        # the zone answered once at the root (RUL-timezone_auto_resolves)
    _write_handoff(ws, [r(ws) for r in recs])
    return ws


def _write_handoff(ws, files):
    ho = {"filename_timestamp_format": utils.CONFIG["filename_timestamp_format"], "run_metadata": {"plan_id": "prep-1", "execution_id": "exec-1"}, "files": files,
          "cache_fingerprint": "pcf", "depends_on": {"cache": {"image_engine_version": utils.get_imagemagick_version(), "fingerprint_algorithm_version": utils.FINGERPRINT_ALGORITHM_VERSION}}}
    ho["content_fingerprint"] = utils.handoff_content_fingerprint(ho)
    (ws / ".photos-ingest" / "photos-11-handoff.json").write_text(json.dumps(vouched(ws, ho)))


def _plan(monkeypatch, ws):
    monkeypatch.chdir(str(ws))
    monkeypatch.setattr(sys, "argv", ["photos-2-geotag", "plan"])
    try:
        cal.main()
    except SystemExit:
        pass


def _set_offset(ws, offset, bucket=CAM):
    p = ws / ".photos-ingest" / cal.TIME_DECISIONS_ARTIFACT
    a = json.loads(p.read_text())
    a["destinations"][T]["camera_group_time_decisions"][bucket]["user_decision"]["manual_offset_seconds"] = offset
    p.write_text(json.dumps(a))


def _confirm_drift(ws, offset, bucket=CAM):
    """Confirm the GPS-drift check a manual offset with track coverage triggers (BLD-drift_validation)."""
    p = ws / ".photos-ingest" / "photos-22-gps-drift-validation.json"
    a = json.loads(p.read_text())
    cell = a["destinations"][T]["drift_decisions"][bucket]
    cell["user_decision"].update(confirmed=True, corrected_offset_seconds=offset,
                                 confirmed_offset_seconds=cell["proposal"]["current_offset_seconds"],
                                 confirmed_against_tracks=cell["proposal"]["tracks"])
    p.write_text(json.dumps(a))


def _ops(ws):
    """{relative_path: {"writes": merged tag writes, "types": [...], "to": rename target}} of photos-24."""
    plan = json.loads((ws / ".photos-ingest" / "photos-24-executable-plan.json").read_text())
    assert plan["status"] == "ready", plan.get("blockers")
    out = {}
    for d in plan["destinations"].values():
        for op in d["operations"]:
            e = out.setdefault(op["relative_path"], {"writes": {}, "types": [], "to": None})
            e["types"].append(op["type"])
            e["writes"].update(op.get("writes") or {})
            if op["type"] == "rename_no_clobber":
                e["to"] = op["to"]
    return out


def _executed_and_reprepped(ws, renamed_on_disk=False, renamed=True):
    """Fold photos-24's writes and renames into the handoff, as a re-prep reads the files back.
    `renamed_on_disk`: a real execute already renamed the files; not `renamed`: the writes landed, the renames not."""
    ops = _ops(ws)
    ho = json.loads((ws / ".photos-ingest" / "photos-11-handoff.json").read_text())
    for f in ho["files"]:
        e = ops.get(f["relative_path"])
        if not e:
            continue
        ms = f["metadata_status"]
        parsed = json.loads(ms["parsed_json"])
        for k, v in e["writes"].items():
            if k in ("GPSLatitudeRef", "GPSLongitudeRef"):
                continue
            if v == "":
                parsed.pop(k, None)
            else:
                parsed[k] = v
        parsed["selected_source_naive_timestamp"] = parsed["DateTimeOriginal"]
        has = parsed.get("GPSLatitude") is not None
        parsed["has_native_gps"] = ms["has_native_gps"] = has
        ms["parsed_json"] = json.dumps(parsed)
        if e["to"] and renamed:
            old = ws / f["relative_path"]
            f["relative_path"] = os.path.join(os.path.dirname(f["relative_path"]), e["to"])
            if not renamed_on_disk:
                os.rename(old, ws / f["relative_path"])
        st = (ws / f["relative_path"]).stat()
        f["size"], f["mtime_ns"] = st.st_size, st.st_mtime_ns
    _write_handoff(ws, ho["files"])


def _execute(monkeypatch, ws):
    """A real `execute` with exiftool and the fingerprint mocked (each photo keeps its identity), so the
    original-values ledger is pinned as in a real run; then the re-prep is folded into the handoff."""
    ho = json.loads((ws / ".photos-ingest" / "photos-11-handoff.json").read_text())
    fps = {os.path.basename(f["relative_path"]): json.loads(f["content_hash"])["value"] for f in ho["files"]}
    monkeypatch.setattr(cal.GeotagWorkflow, "_exiftool_write", lambda self, p, tags: True)
    monkeypatch.setattr(cal.ContentHasher, "fingerprint_image",
                        staticmethod(lambda p: {"status": "valid", "value": fps.get(os.path.basename(p))}))
    monkeypatch.chdir(str(ws))
    monkeypatch.setattr(sys, "argv", ["photos-2-geotag", "execute"])
    try:
        cal.main()
    except SystemExit as e:
        assert e.code in (0, None), e.code
    summary = json.loads((ws / ".photos-ingest" / "photos-25-execution-summary.json").read_text())
    assert summary["status"] == "success", summary
    _executed_and_reprepped(ws, renamed_on_disk=True)


def _originals(ws):
    db = cal.GeotagCache(str(ws))
    try:
        return db.originals_all()
    finally:
        db.close()


def _cell(ws, bucket=CAM):
    t = json.loads((ws / ".photos-ingest" / cal.TIME_DECISIONS_ARTIFACT).read_text())
    return t["destinations"][T]["camera_group_time_decisions"].get(bucket)


def _executed_round(tmp_path, monkeypatch):
    """`_first_round`'s photo, ten minutes slow under a manual offset, but executed for real."""
    ws = _ws(tmp_path, [lambda ws: _rec(ws, f"{T}/a.arw", "2024:07:03 14:20:00")])
    _plan(monkeypatch, ws)
    _set_offset(ws, SLOW)
    _plan(monkeypatch, ws)
    _confirm_drift(ws, SLOW)
    _plan(monkeypatch, ws)
    _execute(monkeypatch, ws)
    return ws


def _first_round(tmp_path, monkeypatch):
    """A camera without GPS, ten minutes slow, placed from the track under a manual offset."""
    ws = _ws(tmp_path, [lambda ws: _rec(ws, f"{T}/a.arw", "2024:07:03 14:20:00")])
    _plan(monkeypatch, ws)
    _set_offset(ws, SLOW)
    _plan(monkeypatch, ws)
    _confirm_drift(ws, SLOW)
    _plan(monkeypatch, ws)
    a = _ops(ws)[f"{T}/a.arw"]
    assert a["writes"]["DateTimeOriginal"] == "2024:07:03 14:30:00"      # 12:30Z, Brussels summer
    assert a["writes"]["GPSLatitude"] == pytest.approx(50.003) and a["writes"]["GPSProcessingMethod"] == "matched"  # on a point
    _executed_and_reprepped(ws)
    return ws


@pytest.mark.spec("RUL-track_never_written_in_photo", test="TST-geotag_rerun_markers-the_track_is_not_written_in_the_photo")
def test_the_track_is_not_written_in_the_photo(tmp_path, monkeypatch):
    """A photo the track placed is recorded with the track; what execute writes into the photo — its time, its
    position and how it was found — names no track."""
    ws = _ws(tmp_path, [lambda ws: _rec(ws, f"{T}/a.arw", "2024:07:03 14:20:00")])
    os.rename(tmp_path / "gpx" / "t.gpx", tmp_path / "gpx" / "brussels-walk.gpx")
    _plan(monkeypatch, ws)
    _set_offset(ws, SLOW)
    _plan(monkeypatch, ws)
    _confirm_drift(ws, SLOW)
    _plan(monkeypatch, ws)
    plan = json.loads((ws / ".photos-ingest" / "photos-24-executable-plan.json").read_text())
    gps = [o for d in plan["destinations"].values() for o in d["operations"] if o["type"] == "metadata_gps_write"]
    assert [o["provenance"]["gpx_file"] for o in gps] == ["brussels-walk.gpx"]     # the record has the track

    written = []
    fp = json.loads(json.loads((ws / ".photos-ingest" / "photos-11-handoff.json").read_text())
                    ["files"][0]["content_hash"])["value"]
    monkeypatch.setattr(cal.GeotagWorkflow, "_exiftool_write", lambda self, p, tags: written.append(tags) or True)
    monkeypatch.setattr(cal.ContentHasher, "fingerprint_image", staticmethod(lambda p: {"status": "valid", "value": fp}))
    monkeypatch.chdir(str(ws))
    monkeypatch.setattr(sys, "argv", ["photos-2-geotag", "execute"])
    try:
        cal.main()
    except SystemExit as e:
        assert e.code in (0, None), e.code
    assert len(written) == 1 and written[0]["GPSProcessingMethod"] == "matched"    # placed from the track
    assert not any("brussels-walk" in f"{k}={v}" for k, v in written[0].items()), written[0]


@pytest.mark.spec("RUL-geotag_rerun_keeps_settled", "BLD-marked_file_rerun", "BLD-executable_plan", "RUL-no_op_run",
                  test="TST-geotag_rerun_markers-manual_offset_is_not_applied_twice")
def test_manual_offset_is_not_applied_twice(tmp_path, monkeypatch):
    ws = _first_round(tmp_path, monkeypatch)
    _plan(monkeypatch, ws)
    assert _ops(ws) == {}                                    # time, fix and name all held already
    t = json.loads((ws / ".photos-ingest" / cal.TIME_DECISIONS_ARTIFACT).read_text())
    cell = t["destinations"][T]["camera_group_time_decisions"][CAM]          # nothing asked, answer kept
    assert cell["effective_time_anchor"]["offset_seconds"] == SLOW and not cell["requires_user_input"]


@pytest.mark.spec("BLD-marked_file_rerun", "RUL-day_offset_kept_for_later_photos", "RUL-geotag_rerun_keeps_settled",
                  test="TST-geotag_rerun_markers-new_photo_joins_corrected_ones")
def test_new_photo_joins_corrected_ones(tmp_path, monkeypatch):
    """Same camera, same day: the earlier answer — offset and drift confirmation — is kept through a
    run where every photo was already corrected, and applied to the new photo alone."""
    ws = _first_round(tmp_path, monkeypatch)
    _plan(monkeypatch, ws)                                   # every photo corrected: nothing asked
    ho = json.loads((ws / ".photos-ingest" / "photos-11-handoff.json").read_text())
    _write_handoff(ws, ho["files"] + [_rec(ws, f"{T}/c.arw", "2024:07:03 14:50:00")])
    _plan(monkeypatch, ws)
    ops = _ops(ws)
    assert list(ops) == [f"{T}/c.arw"]
    assert ops[f"{T}/c.arw"]["writes"]["DateTimeOriginal"] == "2024:07:03 15:00:00"


@pytest.mark.spec("BLD-marked_file_rerun", "RUL-rerun_rederives_written_position",
                  test="TST-geotag_rerun_markers-geotag_position_is_placed_again")
def test_geotag_position_is_placed_again(tmp_path, monkeypatch):
    """A position geotag wrote is not the file's own: the re-run places the file from the track again
    and overwrites a fix that no longer agrees, and it is never a clock anchor."""
    ws = _ws(tmp_path, [lambda ws: _rec(ws, f"{T}/2024-07-03--14-30-00.arw", "2024:07:03 14:30:00",
                                        gps=(40.0, 3.0), method="interpolated")])
    p = ws / ".photos-ingest" / "photos-11-handoff.json"
    ho = json.loads(p.read_text())
    parsed = json.loads(ho["files"][0]["metadata_status"]["parsed_json"])
    parsed["OffsetTimeOriginal"] = "+02:00"
    ho["files"][0]["metadata_status"]["parsed_json"] = json.dumps(parsed)
    _write_handoff(ws, ho["files"])
    _plan(monkeypatch, ws)
    e = _ops(ws)[f"{T}/2024-07-03--14-30-00.arw"]
    assert e["types"] == ["metadata_gps_write", "gps_marker_write"]          # no time write, no rename
    assert e["writes"]["GPSLatitude"] == pytest.approx(50.003)


@pytest.mark.spec("BLD-rerun_recognition", "RUL-geotag_rerun_keeps_settled",
                  test="TST-geotag_rerun_markers-own_gps_camera_is_marked_time_fixed")
def test_own_gps_camera_is_marked_time_fixed(tmp_path, monkeypatch):
    """A camera with its own GPS has its time corrected from that GPS, keeps the position, and is
    marked time-fixed; the re-run then neither corrects it again nor uses it as an anchor."""
    ws = _ws(tmp_path, [lambda ws: _rec(ws, f"{T}/a.arw", "2024:07:03 13:50:00", gps=(50.0, 4.0)),
                        lambda ws: _rec(ws, f"{T}/b.arw", "2024:07:03 14:40:00", gps=(50.005, 4.0))])
    _plan(monkeypatch, ws)
    a = _ops(ws)[f"{T}/a.arw"]
    assert a["writes"] == {"DateTimeOriginal": "2024:07:03 14:00:00", "OffsetTimeOriginal": "+02:00",
                           "GPSProcessingMethod": "+carto-time"}
    _executed_and_reprepped(ws)
    _plan(monkeypatch, ws)
    assert _ops(ws) == {}


@pytest.mark.spec("RUL-day_offset_kept_for_later_photos", "BLD-day_offset_kept", test="TST-geotag_rerun_markers-gps_derived_offset_is_kept_for_later_photos")
def test_gps_derived_offset_is_kept_for_later_photos(tmp_path, monkeypatch):
    """An offset found from the camera's own GPS stays the camera's offset for the day once those
    photos are corrected, so a later photo without GPS needs no answer."""
    ws = _ws(tmp_path, [lambda ws: _rec(ws, f"{T}/a.arw", "2024:07:03 13:50:00", gps=(50.0, 4.0)),
                        lambda ws: _rec(ws, f"{T}/b.arw", "2024:07:03 14:40:00", gps=(50.005, 4.0))])
    _plan(monkeypatch, ws)
    _executed_and_reprepped(ws)
    ho = json.loads((ws / ".photos-ingest" / "photos-11-handoff.json").read_text())
    _write_handoff(ws, ho["files"] + [_rec(ws, f"{T}/c.arw", "2024:07:03 14:50:00")])
    _plan(monkeypatch, ws)
    ops = _ops(ws)
    assert list(ops) == [f"{T}/c.arw"]
    assert ops[f"{T}/c.arw"]["writes"]["DateTimeOriginal"] == "2024:07:03 15:00:00"


@pytest.mark.spec("BLD-rerun_recognition", test="TST-geotag_rerun_markers-a_devices_own_marker_is_native")
def test_a_devices_own_marker_is_native(tmp_path, monkeypatch):
    """A phone's own GPSProcessingMethod is not geotag's: its position is kept and its time is not
    taken as corrected. Geotag's time mark is appended to the phone's value, never replacing it, and
    read back the phone's GPS is still native while its time is fixed."""
    assert cal.geotag_marker("fused") is None and cal.geotag_marker(" interpolated ") == "interpolated"
    assert cal.geotag_marker("fused+carto-time") == cal.geotag_marker("+carto-time") == "+carto-time"
    assert cal.with_time_fixed("fused") == cal.with_time_fixed("fused+carto-time") == "fused+carto-time"
    assert cal.with_time_fixed("") == cal.with_time_fixed(None) == "+carto-time"
    ws = _ws(tmp_path, [lambda ws: _rec(ws, f"{T}/p.jpg", "2024:07:03 14:30:00", key=PHONE,
                                        gps=(48.0, 2.0), method="fused")])
    _plan(monkeypatch, ws)
    p = _ops(ws)[f"{T}/p.jpg"]
    assert "GPSLatitude" not in p["writes"]                                   # native position kept
    assert p["writes"]["DateTimeOriginal"] == "2024:07:03 14:30:00"
    assert p["writes"]["GPSProcessingMethod"] == "fused+carto-time"
    _executed_and_reprepped(ws)
    wf = cal.GeotagWorkflow(str(ws))
    wf.handoff = json.loads((ws / ".photos-ingest" / "photos-11-handoff.json").read_text())
    (f,) = wf.build_file_model()                                    # renamed by now
    assert f["has_native_gps"] and f["geotag_marker"] == "+carto-time"
    _plan(monkeypatch, ws)
    assert _ops(ws) == {}


@pytest.mark.spec("BLD-marked_file_rerun", test="TST-geotag_rerun_markers-unlocated_geotag_position_is_cleared")
def test_unlocated_geotag_position_is_cleared(tmp_path, monkeypatch):
    """A file geotag once placed, now off the track and accepted as unlocated, loses geotag's old
    fix: kept, it would read as the file's own next time."""
    ws = _ws(tmp_path, [lambda ws: _rec(ws, f"{T}/2024-07-03--18-00-00.arw", "2024:07:03 18:00:00",
                                        gps=(40.0, 3.0), method="interpolated")])
    p = ws / ".photos-ingest" / "photos-11-handoff.json"
    ho = json.loads(p.read_text())
    parsed = json.loads(ho["files"][0]["metadata_status"]["parsed_json"])
    parsed["OffsetTimeOriginal"] = "+02:00"
    ho["files"][0]["metadata_status"]["parsed_json"] = json.dumps(parsed)
    _write_handoff(ws, ho["files"])
    _plan(monkeypatch, ws)
    g = ws / ".photos-ingest" / "photos-23-gps-decisions.json"
    a = json.loads(g.read_text())
    for ri in a["destinations"][T]["gps_decisions"]["review_items"]:
        ri["user_decision"]["accept_unlocated"] = True
    g.write_text(json.dumps(a))
    _plan(monkeypatch, ws)
    e = _ops(ws)[f"{T}/2024-07-03--18-00-00.arw"]
    assert e["writes"]["GPSLatitude"] == "" and e["writes"]["GPSProcessingMethod"] == "+carto-time"
    plan = json.loads((ws / ".photos-ingest" / "photos-24-executable-plan.json").read_text())
    clear = next(o for d in plan["destinations"].values() for o in d["operations"] if o["type"] == "gps_marker_write")
    assert clear["pre_state"] == {"present": True, "GPSLatitude": 40.0, "GPSLongitude": 3.0,
                                  "GPSProcessingMethod": "interpolated"}   # what it clears, for the log


@pytest.mark.spec("RUL-decision_revisable", "BLD-original_values_pinned", test="TST-geotag_rerun_markers-changed_offset_after_execute_reaches_the_photo")
def test_changed_offset_after_execute_reaches_the_photo(tmp_path, monkeypatch):
    """A wrong offset, once executed, is fixed in the record: the re-run works from the photo's own
    camera time and corrects it once, under the new offset."""
    ws = _executed_round(tmp_path, monkeypatch)
    _confirm_drift(ws, SLOW - 300)                           # the camera was fifteen minutes slow, not ten
    _plan(monkeypatch, ws)
    e = _ops(ws)[f"{T}/2024-07-03--14-30-00.arw"]
    assert e["writes"]["DateTimeOriginal"] == "2024:07:03 14:25:00"      # 14:20 camera + 1:55 = 12:25Z
    assert e["to"] == "2024-07-03--14-25-00.arw"
    assert e["writes"]["GPSLatitude"] == pytest.approx(50.0025)          # placed again at the new time


@pytest.mark.spec("RUL-withdrawal_undoes", test="TST-geotag_rerun_markers-withdrawn_offset_after_execute_asks_again")
def test_withdrawn_offset_after_execute_asks_again(tmp_path, monkeypatch):
    ws = _executed_round(tmp_path, monkeypatch)
    _set_offset(ws, "")
    _plan(monkeypatch, ws)
    # With tracks by the photo the timezone's guess is asked about where it can be checked: at the drift
    # check, whose earlier confirmation was of the withdrawn offset and confirms nothing now.
    assert _cell(ws)["effective_time_anchor"]["source"] == "timezone_unconfirmed"
    drift = json.loads((ws / ".photos-ingest" / "photos-22-gps-drift-validation.json").read_text())
    asked = drift["destinations"][T]["drift_decisions"][CAM]
    assert drift["requires_user_input"] and asked["requires_user_input"] and asked["stale_user_decision"]
    assert asked["effective_drift_offset"] == ""


@pytest.mark.spec("RUL-withdrawal_recomputes_time_and_name",
                  test="TST-geotag_rerun_markers-withdrawn_offset_after_execute_recomputes_time_and_name_in_place")
def test_withdrawn_offset_after_execute_recomputes_time_and_name_in_place(tmp_path, monkeypatch):
    """A manual offset, five minutes off what the camera's own GPS photos give, is executed: the photo is
    corrected and named under it. Withdrawn, the offset gives way to the one the tool derives, and the photo's
    time and name are computed again from its own camera time — for the file where it now stands, under the
    name the withdrawn decision gave it, and within its destination."""
    ws = _ws(tmp_path, [lambda ws: _rec(ws, f"{T}/a.arw", "2024:07:03 13:50:00", gps=(50.0, 4.0)),
                        lambda ws: _rec(ws, f"{T}/b.arw", "2024:07:03 14:40:00", gps=(50.005, 4.0)),
                        lambda ws: _rec(ws, f"{T}/c.arw", "2024:07:03 14:20:00")])
    _plan(monkeypatch, ws)
    _set_offset(ws, SLOW - 300)
    _plan(monkeypatch, ws)
    _confirm_drift(ws, SLOW - 300)
    _plan(monkeypatch, ws)
    assert _ops(ws)[f"{T}/c.arw"]["to"] == "2024-07-03--14-25-00.arw"    # 14:20 camera + 1:55 = 12:25Z
    _execute(monkeypatch, ws)
    assert (ws / T / "2024-07-03--14-25-00.arw").exists() and not (ws / T / "c.arw").exists()
    _set_offset(ws, "")                                      # the decision withdrawn
    _plan(monkeypatch, ws)
    assert _cell(ws)["effective_time_anchor"] == {"offset_seconds": SLOW, "source": "gpx_anchor_auto"}
    ops = _ops(ws)
    e = ops[f"{T}/2024-07-03--14-25-00.arw"]                 # the file where it stands
    assert e["writes"]["DateTimeOriginal"] == "2024:07:03 14:30:00"      # 14:20 camera + 1:50 = 12:30Z
    assert e["to"] == "2024-07-03--14-30-00.arw"             # a name, not a path: within its destination
    assert {"metadata_time_write", "rename_no_clobber"} <= set(e["types"])
    assert all(os.path.exists(ws / rel) for rel in ops)      # every operation is on a file as it stands


@pytest.mark.spec("BLD-original_values_pinned", test="TST-geotag_rerun_markers-originals_are_pinned_once_and_complete")
def test_originals_are_pinned_once_and_complete(tmp_path, monkeypatch):
    ws = _executed_round(tmp_path, monkeypatch)
    pinned = _originals(ws)
    assert pinned == {"fp-a.arw": {"DateTimeOriginal": "2024:07:03 14:20:00", "OffsetTimeOriginal": None,
                                   "CreateDate": None, "OffsetTimeDigitized": None, "GPSLatitude": None, "GPSLongitude": None, "GPSProcessingMethod": None,
                                   "has_native_gps": False,
                                   "selected_source_naive_timestamp": "2024:07:03 14:20:00",
                                   "selected_source_timestamp_tag": "DateTimeOriginal"}}
    _confirm_drift(ws, SLOW - 60)
    _plan(monkeypatch, ws)
    _execute(monkeypatch, ws)
    assert _originals(ws) == pinned                          # never overwritten


@pytest.mark.spec("BLD-original_values_pinned", test="TST-geotag_rerun_markers-a_marked_photo_is_not_pinned")
def test_a_marked_photo_is_not_pinned(tmp_path, monkeypatch):
    """A photo geotag marked before (elsewhere) holds no original values: nothing is pinned, and its time
    is taken as fixed."""
    ws = _ws(tmp_path, [lambda ws: _rec(ws, f"{T}/2024-07-03--14-30-00.arw", "2024:07:03 14:30:00",
                                        gps=(40.0, 3.0), method="interpolated")])
    _plan(monkeypatch, ws)
    assert f"{T}/2024-07-03--14-30-00.arw" in _ops(ws)       # re-placed from the track
    _execute(monkeypatch, ws)
    assert _originals(ws) == {}


@pytest.mark.spec("BLD-original_values_pinned", test="TST-geotag_rerun_markers-own_gps_camera_anchors_again_after_execute")
def test_own_gps_camera_anchors_again_after_execute(tmp_path, monkeypatch):
    """With their own values pinned, a GPS camera's photos give the offset again on a re-run, as on the
    first: nothing is kept from earlier, and nothing is written."""
    ws = _ws(tmp_path, [lambda ws: _rec(ws, f"{T}/a.arw", "2024:07:03 13:50:00", gps=(50.0, 4.0)),
                        lambda ws: _rec(ws, f"{T}/b.arw", "2024:07:03 14:40:00", gps=(50.005, 4.0))])
    _plan(monkeypatch, ws)
    _execute(monkeypatch, ws)
    _plan(monkeypatch, ws)
    assert _ops(ws) == {}
    assert _cell(ws)["decision_mode"] == "auto_resolved" and _cell(ws)["effective_time_anchor"]["offset_seconds"] == SLOW


@pytest.mark.spec("RUL-user_writes_decisions", test="TST-geotag_rerun_markers-the_record_follows_the_decision")
def test_the_record_follows_the_decision(tmp_path, monkeypatch):
    """Where every photo is marked and none has its own values pinned, the kept answer is derived from the
    decision, so the record never shows an effective value the decision no longer says."""
    ws = _first_round(tmp_path, monkeypatch)                 # simulated execute: nothing pinned
    _plan(monkeypatch, ws)
    _set_offset(ws, SLOW - 60)
    _plan(monkeypatch, ws)
    assert _cell(ws)["effective_time_anchor"]["offset_seconds"] == SLOW - 60
    assert not _cell(ws)["requires_user_input"]


def _vouch_prep_log(ws):
    """Stand in for prep: record in the handoff the hash of prep's log as it now is (an empty one if none),
    as prep's execution does when it writes them. The pointer is outside the handoff's content, so this
    makes nothing of geotag's stale."""
    ctl = ws / ".photos-ingest"
    log = ctl / "photos-15-prep-log.json"
    if not log.exists():
        log.write_text(json.dumps({"photos": {}}))
    p = ctl / "photos-11-handoff.json"
    ho = json.loads(p.read_text())
    ho.setdefault("depends_on", {})["prep_log"] = {"sha256": utils.sha256_file(str(log))}
    p.write_text(json.dumps(ho))


def _finalize(monkeypatch, ws, vouch=True):
    if vouch:
        _vouch_prep_log(ws)
    monkeypatch.chdir(str(ws))
    monkeypatch.setattr(sys, "argv", ["photos-2-geotag", "finalize"])
    try:
        cal.main()
    except SystemExit as e:
        assert e.code in (0, None), e.code
    return json.loads((ws / ".photos-ingest" / "photos-26-complete-log.json").read_text())["photos"]


@pytest.mark.spec("RUL-log_entry_grows", "RUL-partial_history_shown", "RUL-history_retained", "BLD-log_format",
                  "BLD-history_kept",
                  test="TST-geotag_rerun_markers-the_log_keeps_every_geotag_pass")
def test_the_log_keeps_every_geotag_pass(tmp_path, monkeypatch):
    """Finalize logs what every executed pass did, in order and matched by fingerprint — not only the
    latest plan's operations: a photo corrected, then corrected again, then left alone shows all three."""
    ws = _executed_round(tmp_path, monkeypatch)                          # pass 1: placed and renamed
    _confirm_drift(ws, SLOW - 300)
    _plan(monkeypatch, ws)
    _execute(monkeypatch, ws)                                            # pass 2: corrected again
    _plan(monkeypatch, ws)
    _execute(monkeypatch, ws)                                            # pass 3: nothing left to write
    entry = _finalize(monkeypatch, ws)["fp-a.arw"]
    steps = entry["journey"]
    assert entry["geotag_path"] == f"{T}/2024-07-03--14-25-00.arw"       # where the last pass left it
    runs = list(dict.fromkeys(s["run"] for s in steps))
    assert len(runs) == 3
    renames = [s["to"] for s in steps if s["action"] == "final_rename"]
    assert renames == ["2024-07-03--14-30-00.arw", "2024-07-03--14-25-00.arw"]
    assert [s["from"] for s in steps if s["action"] == "final_rename"] == ["a.arw", "2024-07-03--14-30-00.arw"]
    offsets = [s for s in steps if s["action"] == "clock_offset_applied"]
    assert [s["offset_seconds"] for s in offsets] == [SLOW, SLOW - 300, SLOW - 300]
    # the offset applied is the drift check's validated one, so each step names that confirmation
    assert all(s["because"] == f"photos-22 destinations.{T}.drift_decisions.{CAM}" for s in offsets)
    # and names the exact version of the record it followed, which execution kept, though the record
    # was edited in place between passes
    for s in offsets:
        assert cal.sha256_file(str(ws / s["because_record"])) == s["because_record_sha256"]
    current = cal.sha256_file(str(ws / ".photos-ingest" / "photos-22-gps-drift-validation.json"))
    assert offsets[0]["because_record_sha256"] != current and offsets[-1]["because_record_sha256"] == current
    assert sum(s["action"] == "gps_written" for s in steps) == 2


@pytest.mark.spec("RUL-partial_history_shown", test="TST-geotag_rerun_markers-a_history_too_thin_is_marked_partial")
def test_a_history_too_thin_is_marked_partial(tmp_path, monkeypatch):
    """Finalize never shows as whole what it cannot rebuild: a photo carrying geotag's mark that no pass
    here first corrected is marked partial, and a pass whose plan is gone is named in a warning."""
    ws = _ws(tmp_path, [lambda ws: _rec(ws, f"{T}/2024-07-03--14-30-00.arw", "2024:07:03 14:30:00",
                                        gps=(40.0, 3.0), method="interpolated")])
    p = ws / ".photos-ingest" / "photos-11-handoff.json"
    ho = json.loads(p.read_text())
    parsed = json.loads(ho["files"][0]["metadata_status"]["parsed_json"])
    parsed["OffsetTimeOriginal"] = "+02:00"
    ho["files"][0]["metadata_status"]["parsed_json"] = json.dumps(parsed)
    _write_handoff(ws, ho["files"])
    _plan(monkeypatch, ws)
    _execute(monkeypatch, ws)
    entry = _finalize(monkeypatch, ws)["fp-2024-07-03--14-30-00.arw"]
    assert entry["partial"]
    assert any(s["action"] == "history_incomplete" and "made elsewhere" in s["note"] for s in entry["journey"])

    (tmp_path / "two").mkdir()
    ws2 = _executed_round(tmp_path / "two", monkeypatch)                 # a pass, then a second one
    _confirm_drift(ws2, SLOW - 300)
    _plan(monkeypatch, ws2)
    _execute(monkeypatch, ws2)
    first = json.loads(next((ws2 / ".photos-ingest").glob("photos-24-executable-plan-0*.json")).read_text())["plan_id"]
    for kept in (ws2 / ".photos-ingest").glob("photos-24-executable-plan-0*.json"):
        kept.unlink()                                                    # the first pass's plan is lost
    _finalize(monkeypatch, ws2)
    log = json.loads((ws2 / ".photos-ingest" / "photos-26-complete-log.json").read_text())
    assert log["partial"] and any(first in w for w in log["warnings"])
    assert "partial" not in log["photos"]["fp-a.arw"]                    # its own values were pinned here


@pytest.mark.spec("BLD-phase_logs", "RUL-partial_history_shown", "RUL-log_entry_append_only",
                  test="TST-geotag_rerun_markers-finalize_carries_prep_s_record_unchanged")
def test_finalize_carries_prep_s_record_unchanged(tmp_path, monkeypatch):
    """Finalize's log carries prep's every field and step unchanged, a note of prep's among them, and adds
    only its own: geotag's note goes in a step of its own."""
    ws = _ws(tmp_path, [lambda ws: _rec(ws, f"{T}/2024-07-03--14-30-00.arw", "2024:07:03 14:30:00",
                                        gps=(40.0, 3.0), method="interpolated")])
    p = ws / ".photos-ingest" / "photos-11-handoff.json"
    ho = json.loads(p.read_text())
    parsed = json.loads(ho["files"][0]["metadata_status"]["parsed_json"])
    parsed["OffsetTimeOriginal"] = "+02:00"
    ho["files"][0]["metadata_status"]["parsed_json"] = json.dumps(parsed)
    _write_handoff(ws, ho["files"])
    fp = "fp-2024-07-03--14-30-00.arw"
    prep = {fp: {"content_fingerprint": fp, "prep_path": "x", "partial": True,
                 "note": "prep history incomplete (no retained journey)",
                 "journey": [{"phase": "prep", "action": "moved_to_by_date", "from": "a", "to": "b"}]}}
    (ws / ".photos-ingest" / "photos-15-prep-log.json").write_text(json.dumps({"photos": prep}))
    _vouch_prep_log(ws)
    _plan(monkeypatch, ws)
    _execute(monkeypatch, ws)
    entry = _finalize(monkeypatch, ws)[fp]
    assert {k: entry[k] for k in prep[fp] if k != "journey"} == {k: v for k, v in prep[fp].items() if k != "journey"}
    assert entry["journey"][:1] == prep[fp]["journey"]
    assert any(s["action"] == "history_incomplete" for s in entry["journey"][1:])
    log = json.loads((ws / ".photos-ingest" / "photos-26-complete-log.json").read_text())
    assert not any("prep's log" in w for w in log["warnings"])



@pytest.mark.spec("BLD-phase_logs", test="TST-geotag_rerun_markers-a_copy_that_would_alter_prep_s_record_is_refused")
def test_a_copy_that_would_alter_prep_s_record_is_refused(tmp_path, monkeypatch, capsys):
    """Were finalize's copy to change prep's record, finalize writes nothing and says so."""
    ws = _executed_round(tmp_path, monkeypatch)
    fp = "fp-prep-only"
    (ws / ".photos-ingest" / "photos-15-prep-log.json").write_text(json.dumps(
        {"photos": {fp: {"content_fingerprint": fp, "prep_path": "x", "journey": []}}}))
    _vouch_prep_log(ws)
    real = cal.build_complete_log

    def altering(*a, **k):
        photos = real(*a, **k)
        photos[fp]["prep_path"] = "elsewhere"
        return photos
    monkeypatch.setattr(cal, "build_complete_log", altering)
    before = sorted(os.listdir(ws / ".photos-ingest"))
    monkeypatch.chdir(str(ws))
    monkeypatch.setattr(sys, "argv", ["photos-2-geotag", "finalize"])
    capsys.readouterr()
    with pytest.raises(SystemExit) as e:
        cal.main()
    assert e.value.code not in (0, None)
    assert "would not carry prep's record unchanged for 1 photo" in "".join(capsys.readouterr())
    assert sorted(os.listdir(ws / ".photos-ingest")) == before


@pytest.mark.spec("RUL-database_regions_disjoint", test="TST-geotag_rerun_markers-geotag_writes_only_its_own_part_of_the_database")
def test_geotag_writes_only_its_own_part_of_the_database(tmp_path, monkeypatch):
    """Geotag's plan, execution and finalize leave prep's part of the database exactly as it was, and
    merge's untouched."""
    import sqlite3
    ws = _ws(tmp_path, [lambda ws: _rec(ws, f"{T}/a.arw", "2024:07:03 14:20:00")])
    utils.WorkspaceCache(str(ws)).close()
    db = str(ws / ".photos-ingest" / "photos-00-ingest.db")
    conn = sqlite3.connect(db)
    conn.execute("INSERT INTO meta VALUES ('a-prep-row', 'v')")
    conn.execute("INSERT INTO library_fingerprint_cache VALUES ('/lib/x.jpg', 1, 2, 'fp', 's', 'e')")
    conn.commit()
    others = ("meta", "file_cache", "metadata_cache", "library_fingerprint_cache")

    def rows():
        return {t: sorted(map(repr, conn.execute(f"SELECT * FROM {t}"))) for t in others}
    before = rows()
    _plan(monkeypatch, ws)
    _set_offset(ws, SLOW)
    _plan(monkeypatch, ws)
    _confirm_drift(ws, SLOW)
    _plan(monkeypatch, ws)
    _execute(monkeypatch, ws)
    _finalize(monkeypatch, ws)
    assert rows() == before
    conn.close()


def _retake_fingerprint(ws, old, new, *, also=None):
    """A new ImageMagick gave the photo fingerprinted `old` the value `new`: the handoff holds `new`, and prep's log —
    vouched for by the handoff — records the step (`also`: one more step, to make the mapping not one to one)."""
    ctl = ws / ".photos-ingest"
    ho = json.loads((ctl / "photos-11-handoff.json").read_text())
    for f in ho["files"]:
        if json.loads(f["content_hash"])["value"] == old:
            f["content_hash"] = json.dumps({"value": new, "status": "valid"})
    steps = [{"phase": "prep", "action": "fingerprint_retaken", "run": "r2", "from": old, "to": new}]
    if also:
        steps.append({"phase": "prep", "action": "fingerprint_retaken", "run": "r2", "from": also, "to": new})
    (ctl / "photos-15-prep-log.json").write_text(json.dumps({"photos": {new: {"journey": steps}}}))
    ho.setdefault("depends_on", {})["prep_log"] = {"sha256": utils.sha256_file(str(ctl / "photos-15-prep-log.json"))}
    _write_handoff(ws, ho["files"])
    ho2 = json.loads((ctl / "photos-11-handoff.json").read_text())
    ho2["depends_on"] = ho["depends_on"]
    (ctl / "photos-11-handoff.json").write_text(json.dumps(vouched(ctl.parent, ho2)))


@pytest.mark.spec("RUL-own_values_follow_new_fingerprint", "BLD-original_values_follow_fingerprint",
                  test="TST-geotag_rerun_markers-a_photo_whose_fingerprint_changed_keeps_its_own_values")
def test_a_photo_whose_fingerprint_changed_keeps_its_own_values(tmp_path, monkeypatch):
    # After an ImageMagick upgrade the photo's fingerprint has a new value: geotag still decides from the values it
    # pinned under the old one — a changed offset reaches the photo from its own camera time — and execute moves
    # the pin to the new value.
    ws = _executed_round(tmp_path, monkeypatch)
    pinned = _originals(ws)["fp-a.arw"]
    _retake_fingerprint(ws, "fp-a.arw", "fp-new")
    _confirm_drift(ws, SLOW - 300)
    _plan(monkeypatch, ws)
    e = _ops(ws)[f"{T}/2024-07-03--14-30-00.arw"]
    assert e["writes"]["DateTimeOriginal"] == "2024:07:03 14:25:00"          # from its own 14:20, once
    _execute(monkeypatch, ws)
    assert _originals(ws) == {"fp-new": pinned}                               # the pin followed the value


@pytest.mark.spec("RUL-own_values_follow_new_fingerprint", "BLD-original_values_follow_fingerprint",
                  test="TST-geotag_rerun_markers-a_fingerprint_mapping_not_one_to_one_stops_geotag")
def test_a_fingerprint_mapping_not_one_to_one_stops_geotag(tmp_path, monkeypatch):
    ws = _executed_round(tmp_path, monkeypatch)
    _retake_fingerprint(ws, "fp-a.arw", "fp-new", also="fp-other")
    blockers, _, _ = cal.GeotagWorkflow(str(ws)).preflight()
    assert any("more than one value" in b and "re-run prep" in b for b in blockers), blockers
    earlier, problem = utils.retaken_fingerprints({"photos": {"x": {"journey": [
        {"action": "fingerprint_retaken", "from": "a", "to": "b"}, {"action": "fingerprint_retaken", "from": "b", "to": "c"}]}}})
    assert earlier == {"b": "a", "c": "b"} and problem is None                # a chain is one to one


@pytest.mark.spec("RUL-geotag_plans_on_vouched_log", "BLD-original_values_follow_fingerprint",
                  test="TST-geotag_rerun_markers-an_unvouched_prep_log_stops_the_plan")
@pytest.mark.parametrize("spoil", ["changed", "missing", "no_hash"])
def test_an_unvouched_prep_log_stops_the_plan(tmp_path, monkeypatch, capsys, spoil):
    """Prep's log says which photo's fingerprint was taken again from which; one the handoff does not vouch for says
    nothing to trust of it. The plan stops, writing nothing, and sends the user to prep — never planning as though
    no fingerprint had changed, which would lose a photo's pinned values."""
    ws = _executed_round(tmp_path, monkeypatch)
    _retake_fingerprint(ws, "fp-a.arw", "fp-new")
    ctl = ws / ".photos-ingest"
    log, ho_p = ctl / "photos-15-prep-log.json", ctl / "photos-11-handoff.json"
    if spoil == "changed":
        log.write_text(json.dumps({"photos": {}}))
    elif spoil == "missing":
        log.unlink()
    else:
        ho = json.loads(ho_p.read_text())
        del ho["depends_on"]["prep_log"]
        ho_p.write_text(json.dumps(ho))
    plan_p = ctl / "photos-24-executable-plan.json"
    before = plan_p.read_bytes()
    blockers, _, _ = cal.GeotagWorkflow(str(ws)).preflight()
    assert any("prep's log" in b.lower() and "`prep plan` and `prep execute`" in b for b in blockers), blockers
    capsys.readouterr()
    monkeypatch.chdir(str(ws))
    monkeypatch.setattr(sys, "argv", ["photos-2-geotag", "plan"])
    with pytest.raises(SystemExit) as ei:
        cal.main()
    out = capsys.readouterr()
    assert ei.value.code == 2 and "prep's log" in (out.out + out.err).lower()
    assert plan_p.read_bytes() == before                                     # nothing planned past it
    assert not cal.GeotagWorkflow(str(ws)).preflight(for_execute=True)[0]    # the plan alone stops on it


@pytest.mark.spec("BLD-original_values_follow_fingerprint",
                  test="TST-geotag_rerun_markers-a_fingerprint_taken_back_to_an_earlier_value_ends_the_walk")
def test_a_fingerprint_taken_back_to_an_earlier_value_ends_the_walk(tmp_path, monkeypatch):
    """The image engine upgraded and then put back: a photo's fingerprint goes A → B → A. For a photo with no
    pin, the walk back through its earlier values comes round to where it started — and stops there, pinless,
    rather than going round for ever."""
    ws = _executed_round(tmp_path, monkeypatch)
    wf = cal.GeotagWorkflow(str(ws))
    wf.preflight()
    monkeypatch.setattr(cal.GeotagCache, "originals_all", lambda self: {})
    monkeypatch.setattr(cal.GeotagWorkflow, "_retaken", lambda self: {"fp-a.arw": "fp-old", "fp-old": "fp-a.arw"})
    files = wf.build_file_model()
    assert files and not any(f.get("original_key") for f in files)


@pytest.mark.spec("BLD-original_values_pinned", "BLD-decided_from_own_values", "BLD-other_time_fields_written",
                  test="TST-geotag_rerun_markers-a_time_read_from_createdate_is_decided_from_its_pinned_offset")
def test_a_time_read_from_createdate_is_decided_from_its_pinned_offset():
    """Geotag rewrites a photo's CreateDate and its offset with the corrected time, so both are pinned: a phone
    photo whose time was read from CreateDate is resolved again by the offset its phone recorded, never by the
    destination's offset geotag wrote — and the comparison side keeps what the photo holds now."""
    parsed = {"selected_source_naive_timestamp": "2024:07:03 21:00:00", "selected_source_timestamp_tag": "EXIF:CreateDate",
              "CreateDate": "2024:07:03 21:00:00", "OffsetTimeDigitized": "+09:00", "has_native_gps": False}
    original = cal.own_values(parsed)
    assert (original["CreateDate"], original["OffsetTimeDigitized"]) == ("2024:07:03 21:00:00", "+09:00")
    now = {"relative_path": f"{T}/p.jpg", "raw_times": {"DateTimeOriginal": "2024:07:03 14:00:00",
                                                        "OffsetTimeOriginal": "+02:00",
                                                        "CreateDate": "2024:07:03 14:00:00", "OffsetTimeDigitized": "+02:00"},
           "other_times": {"EXIF:CreateDate": "2024:07:03 14:00:00", "EXIF:OffsetTimeDigitized": "+02:00"}}
    f = cal.from_originals(now, original)
    assert f["raw_times"] == {"CreateDate": "2024:07:03 21:00:00", "OffsetTimeDigitized": "+09:00"}
    assert cal._own_offset(f) == 9 * 3600
    assert cal.held_values(f)["EXIF:OffsetTimeDigitized"] == "+02:00"                    # what it holds now


# --- a time changed in the photo since geotag wrote it (BLD-changed_time_blocks) ----------------

def _times_written(ws):
    db = cal.GeotagCache(str(ws))
    try:
        return db.times_written_all()
    finally:
        db.close()


def _hand_set_time(ws, dto, off):
    """The photo's time set in another tool after geotag wrote it, as the next re-prep reads it back."""
    ho = json.loads((ws / ".photos-ingest" / "photos-11-handoff.json").read_text())
    (f,) = ho["files"]
    parsed = json.loads(f["metadata_status"]["parsed_json"])
    parsed.update(DateTimeOriginal=dto, OffsetTimeOriginal=off, selected_source_naive_timestamp=dto)
    f["metadata_status"]["parsed_json"] = json.dumps(parsed)
    _write_handoff(ws, ho["files"])


def _plan_record(ws):
    return json.loads((ws / ".photos-ingest" / "photos-24-executable-plan.json").read_text())


@pytest.mark.parametrize("dto, off", [("2024:07:03 14:45:00", "+02:00"),      # the time put right by hand
                                      ("2024:07:03 14:30:00", "+01:00")])     # or only its offset
@pytest.mark.spec("RUL-changed_time_stops_plan", "BLD-changed_time_blocks",
                  test="TST-geotag_rerun_markers-a_time_changed_since_geotag_wrote_it_stops_the_plan")
def test_a_time_changed_since_geotag_wrote_it_stops_the_plan(tmp_path, monkeypatch, dto, off):
    """A photo geotag corrected to 14:30 +02:00 from its own 14:20, then changed in another tool: the plan is
    blocked on it, naming the photo, the time it holds, the time geotag wrote and its own — neither writing geotag's
    time back nor deciding from the new one."""
    ws = _executed_round(tmp_path, monkeypatch)
    _hand_set_time(ws, dto, off)
    _plan(monkeypatch, ws)
    plan = _plan_record(ws)
    assert plan["status"] == "blocked" and not plan["executable"]
    (b,) = [b for b in plan["blockers"] if "2024-07-03--14-30-00.arw" in b]
    assert f"{dto} {off}" in b and "2024:07:03 14:30:00 +02:00" in b and "2024:07:03 14:20:00 with no offset" in b
    rows = cal.GeotagCache(str(ws))
    try:
        (row,) = rows.get_rows()
    finally:
        rows.close()
    assert row["source_naive_time"] == "2024:07:03 14:20:00"          # still decided from its own time


@pytest.mark.spec("RUL-changed_time_stops_plan", "BLD-time_written_recorded", "BLD-changed_time_blocks",
                  test="TST-geotag_rerun_markers-a_photo_holding_what_geotag_wrote_plans_on")
def test_a_photo_holding_what_geotag_wrote_plans_on(tmp_path, monkeypatch):
    """The time geotag writes is recorded beside the pin before it is written; a re-plan of a photo holding it,
    or holding its own time put back, is not blocked — and a changed decision after execute still reaches it."""
    ws = _executed_round(tmp_path, monkeypatch)
    assert _times_written(ws) == {"fp-a.arw": [{"DateTimeOriginal": "2024:07:03 14:30:00",
                                                "OffsetTimeOriginal": "+02:00"}]}
    _plan(monkeypatch, ws)
    assert _ops(ws) == {}                                    # ready, and nothing to write
    _hand_set_time(ws, "2024:07:03 14:20:00", None)          # its own time, put back
    _plan(monkeypatch, ws)
    assert _ops(ws)[f"{T}/2024-07-03--14-30-00.arw"]["writes"]["DateTimeOriginal"] == "2024:07:03 14:30:00"
    _hand_set_time(ws, "2024:07:03 14:30:00", "+02:00")
    _confirm_drift(ws, SLOW - 300)                           # a new decision: fifteen minutes slow
    _plan(monkeypatch, ws)
    _execute(monkeypatch, ws)
    assert _times_written(ws)["fp-a.arw"] == [{"DateTimeOriginal": "2024:07:03 14:30:00", "OffsetTimeOriginal": "+02:00"},
                                              {"DateTimeOriginal": "2024:07:03 14:25:00", "OffsetTimeOriginal": "+02:00"}]
    _plan(monkeypatch, ws)
    assert _ops(ws) == {}


@pytest.mark.spec("RUL-changed_time_stops_plan", "BLD-time_written_recorded",
                  test="TST-geotag_rerun_markers-an_interrupted_time_write_is_geotags_own")
def test_an_interrupted_time_write_is_geotags_own(tmp_path, monkeypatch):
    """A write that landed but was never confirmed — the photo's fingerprint could not be taken after it — leaves
    the photo holding geotag's time with no record in the journal. The time was recorded before the write, so the
    re-plan takes it as geotag's: not blocked, the time not written again, the rename still to do."""
    ws = _ws(tmp_path, [lambda ws: _rec(ws, f"{T}/a.arw", "2024:07:03 14:20:00")])
    _plan(monkeypatch, ws)
    _set_offset(ws, SLOW)
    _plan(monkeypatch, ws)
    _confirm_drift(ws, SLOW)
    _plan(monkeypatch, ws)
    monkeypatch.setattr(cal.GeotagWorkflow, "_exiftool_write", lambda self, p, tags: True)
    monkeypatch.setattr(cal.ContentHasher, "fingerprint_image",
                        staticmethod(lambda p: {"status": "error", "value": None}))
    monkeypatch.chdir(str(ws))
    monkeypatch.setattr(sys, "argv", ["photos-2-geotag", "execute"])
    try:
        cal.main()
    except SystemExit:
        pass
    summary = json.loads((ws / ".photos-ingest" / "photos-25-execution-summary.json").read_text())
    assert summary["status"] == "partial" and summary["fingerprint_mismatches"]
    _executed_and_reprepped(ws, renamed=False)               # the photo holds the planned time, under its old name
    _plan(monkeypatch, ws)
    e = _ops(ws)[f"{T}/a.arw"]
    assert "metadata_time_write" not in e["types"] and e["to"] == "2024-07-03--14-30-00.arw"
