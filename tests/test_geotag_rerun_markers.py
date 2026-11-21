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
from _handoff import recorded, vouched
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


def _rec(ws, rel, dto, *, key=CAM, gps=None, method=None, offset=None):
    parsed = {"DateTimeOriginal": dto, "selected_source_naive_timestamp": dto,
              "selected_source_timestamp_tag": "DateTimeOriginal", "camera_group_key": key, "has_timestamp": True}
    if offset:
        parsed["OffsetTimeOriginal"] = offset
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
    recorded(ws)                                 # the state prep's execution records with its handoff


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


@pytest.mark.spec("BLD-rerun_recognition", "RUL-geotag_rerun_keeps_settled", "RUL-only_corrected_time_marked",
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


def _fixed(ws, rel, dto, fix_utc):
    """A photo holding its own position far from every track, and the UTC its own fix recorded."""
    rec = _rec(ws, rel, dto, gps=(35.0, 135.7))
    parsed = json.loads(rec["metadata_status"]["parsed_json"])
    parsed["GPSDateTime"] = fix_utc
    rec["metadata_status"]["parsed_json"] = json.dumps(parsed)
    return rec


@pytest.mark.spec("RUL-day_offset_kept_for_later_photos", "RUL-kept_offset_rests_on_its_fixes",
                  "RUL-kept_offset_yields_to_new_photo", "BLD-day_offset_kept",
                  test="TST-geotag_rerun_markers-fix_time_offset_is_kept_for_later_photos")
def test_an_offset_from_the_fixes_times_is_kept_for_later_photos(tmp_path, monkeypatch):
    """Two photos' own fixes agree on the clock (−1 h 50 min) and apply themselves. Once they are corrected, a later photo
    of that camera and day with no GPS takes the same offset unasked — while the photos whose fixes gave it are there,
    and no fix that arrives since puts the clock elsewhere."""
    ws = _ws(tmp_path, [lambda ws: _fixed(ws, f"{T}/a.arw", "2024:07:03 10:00:00", "2024:07:03 08:10:00Z"),
                        lambda ws: _fixed(ws, f"{T}/b.arw", "2024:07:03 10:30:00", "2024:07:03 08:40:01Z")])
    record = ws / ".photos-ingest" / cal.TIME_DECISIONS_ARTIFACT
    cell_of = lambda: json.loads(record.read_text())["destinations"][T]["camera_group_time_decisions"][CAM]
    _plan(monkeypatch, ws)
    cell = cell_of()
    assert cell["effective_time_anchor"] == {"offset_seconds": -6600, "source": "gps_time_auto"}
    assert cell["fixed_by"] == ["fp-a.arw", "fp-b.arw"]
    _executed_and_reprepped(ws)
    done = json.loads((ws / ".photos-ingest" / "photos-11-handoff.json").read_text())["files"]

    def replan(files, prior=None):
        if prior is not None:
            record.write_text(prior)                         # each case planned from the kept record
        _write_handoff(ws, files)
        _plan(monkeypatch, ws)
        return cell_of()

    later = _rec(ws, f"{T}/c.arw", "2024:07:03 14:50:00")         # 13:00Z: on the track
    kept = replan(done + [later])
    assert kept["decision_mode"] == "kept_from_earlier" and not kept["requires_user_input"]
    assert kept["effective_time_anchor"]["offset_seconds"] == -6600 and kept["fixed_by"] == cell["fixed_by"]
    assert _ops(ws)[f"{T}/c.arw"]["writes"]["DateTimeOriginal"] == "2024:07:03 15:00:00"
    kept_record = record.read_text()
    # a fix arriving since that puts the clock an hour from it, beyond the tolerance: the day asks
    far = _fixed(ws, f"{T}/d.arw", "2024:07:03 10:55:00", "2024:07:03 07:55:00Z")
    asked = replan(done + [later, far], kept_record)
    assert asked["requires_user_input"] and asked["effective_time_anchor"] == ""
    assert asked["proposal"]["proposed_offset_seconds"] == -10800
    # a photo whose fix gave it taken out of the workspace: what the offset rested on is gone, and the day is decided
    # again as one with no GPS — here the zone's guess, sent to the check against the tracks
    os.remove(ws / far["relative_path"])
    (a,) = [f for f in done if "fp-a.arw" in f["content_hash"]]
    os.remove(ws / a["relative_path"])
    gone = replan([f for f in done if f is not a] + [later], kept_record)
    assert gone["effective_time_anchor"] == {"offset_seconds": -7200, "source": "timezone_unconfirmed"}
    assert "fixed_by" not in gone


@pytest.mark.spec("BLD-rerun_recognition", test="TST-geotag_rerun_markers-a_devices_own_marker_is_native")
def test_a_devices_own_marker_is_native(tmp_path, monkeypatch):
    """A phone's own GPSProcessingMethod is not geotag's: its position is kept and its time is not
    taken as corrected. Its time standing as it is, geotag writes no mark of a corrected time into it — only
    its name changes — and read back the phone's GPS is still native, its own value unmarked."""
    assert cal.geotag_marker("fused") is None and cal.geotag_marker(" interpolated ") == "interpolated"
    assert cal.geotag_marker("fused+carto-time") == cal.geotag_marker("+carto-time") == "+carto-time"
    assert cal.with_time_fixed("fused") == cal.with_time_fixed("fused+carto-time") == "fused+carto-time"
    assert cal.with_time_fixed("") == cal.with_time_fixed(None) == "+carto-time"
    ws = _ws(tmp_path, [lambda ws: _rec(ws, f"{T}/p.jpg", "2024:07:03 14:30:00", key=PHONE,
                                        gps=(48.0, 2.0), method="fused", offset="+02:00")])
    _plan(monkeypatch, ws)
    p = _ops(ws)[f"{T}/p.jpg"]
    # the phone records its offset, the zone's: its time stands as it is, and is not marked corrected
    assert p["types"] == ["rename_no_clobber"] and p["writes"] == {}
    _executed_and_reprepped(ws)
    wf = cal.GeotagWorkflow(str(ws))
    wf.handoff = json.loads((ws / ".photos-ingest" / "photos-11-handoff.json").read_text())
    (f,) = wf.build_file_model()                                    # renamed by now
    assert f["has_native_gps"] and f["geotag_marker"] is None
    _plan(monkeypatch, ws)
    assert _ops(ws) == {}


@pytest.mark.spec("RUL-only_corrected_time_marked", "BLD-rerun_recognition", "DEF-corrected_time",
                  test="TST-geotag_rerun_markers-a_phone_holding_its_true_time_is_not_touched")
def test_a_phone_holding_its_true_time_is_not_touched(tmp_path, monkeypatch):
    """A phone photo holding the right local time, its offset and its own position, under the name geotag would give
    it, needs nothing: no operation at all — no mark of a corrected time geotag never wrote — and a re-run decides
    it from its own values again, with the same result."""
    ws = _ws(tmp_path, [lambda ws: _rec(ws, f"{T}/2024-07-03--14-30-00.jpg", "2024:07:03 14:30:00", key=PHONE,
                                        gps=(48.0, 2.0), method="fused", offset="+02:00")])
    _plan(monkeypatch, ws)
    assert _ops(ws) == {}
    plan = json.loads((ws / ".photos-ingest" / "photos-24-executable-plan.json").read_text())
    assert plan["destinations"][T]["no_ops"] == [f"{T}/2024-07-03--14-30-00.jpg"]     # held as planned already
    _plan(monkeypatch, ws)
    assert _ops(ws) == {}


@pytest.mark.spec("RUL-only_corrected_time_marked", "BLD-rerun_recognition",
                  test="TST-geotag_rerun_markers-only_a_written_time_carries_the_mark")
def test_only_a_written_time_carries_the_mark(tmp_path):
    """The suffix goes on a photo whose time this plan writes, or whose field already carries geotag's mark; a photo
    whose time is resolved to what it holds gets none."""
    def model(rel, dto, off, method, lat=48.0, lon=2.0):
        return {"relative_path": rel, "content_fingerprint": "fp-" + rel, "size": 1, "mtime_ns": 1,
                "raw_times": {"DateTimeOriginal": dto, "OffsetTimeOriginal": off},
                "native_gps": {"lat": lat, "lon": lon, "processing_method": method}, "processing_method": method}
    utc, tz = "2024-07-03T12:30:00Z", "Europe/Brussels"                          # 14:30:00 +02:00
    assert cal.plan_file_ops(model("a.jpg", "2024:07:03 14:30:00", "+02:00", "fused"),
                             utc, tz, "preserve_native", None, None) == []        # held already: nothing
    written = cal.plan_file_ops(model("b.jpg", "2024:07:03 13:30:00", "+01:00", "fused"),
                                utc, tz, "preserve_native", None, None)
    assert [o["type"] for o in written] == ["metadata_time_write", "gps_marker_write"]
    assert written[1]["writes"] == {"GPSProcessingMethod": "fused+carto-time"}  # written: marked
    assert cal.plan_file_ops(model("c.jpg", "2024:07:03 14:30:00", "+02:00", "fused+carto-time"),
                             utc, tz, "preserve_native", None, None) == []        # written before: mark kept


@pytest.mark.spec("BLD-marked_file_rerun", "RUL-unplaced_photo_waits",
                  test="TST-geotag_rerun_markers-geotag_position_off_the_track_waits_then_gives_way")
def test_geotag_position_off_the_track_waits_then_gives_way(tmp_path, monkeypatch):
    """A file geotag once placed, now off the track: geotag's old fix is not taken as its own — it waits for the
    user, no plan made, and once its folder has a fallback it is placed there, the old fix written over and kept for
    the log."""
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
    (item,) = a["destinations"][T]["gps_decisions"]["review_items"]
    assert item["reason"] == "no_reliable_gps_source" and item["requires_user_input"]
    assert not (ws / ".photos-ingest" / "photos-24-executable-plan.json").exists()
    a["destinations"][T]["folder_fallback"]["user_decision"].update(fallback_lat=41.0, fallback_lon=2.0)
    g.write_text(json.dumps(a))
    _plan(monkeypatch, ws)
    e = _ops(ws)[f"{T}/2024-07-03--18-00-00.arw"]
    assert e["writes"]["GPSLatitude"] == 41.0 and e["writes"]["GPSProcessingMethod"] == "manual_fallback"
    plan = json.loads((ws / ".photos-ingest" / "photos-24-executable-plan.json").read_text())
    w = next(o for d in plan["destinations"].values() for o in d["operations"] if o["type"] == "metadata_gps_write")
    assert w["pre_state"] == {"present": True, "GPSLatitude": 40.0, "GPSLongitude": 3.0,
                              "GPSProcessingMethod": "interpolated"}   # what it replaces, for the log


@pytest.mark.spec("RUL-decision_revisable", "RUL-wrong_choice_needs_no_hand_repair", "BLD-original_values_pinned",
                  "RUL-geotag_rerun_keeps_settled", test="TST-geotag_rerun_markers-changed_offset_after_execute_reaches_the_photo")
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


@pytest.mark.spec("RUL-withdrawal_recomputes_time_and_name", "RUL-withdrawn_derived_position_derived_again",
                  test="TST-geotag_rerun_markers-withdrawn_offset_after_execute_recomputes_time_and_name_in_place")
def test_withdrawn_offset_after_execute_recomputes_time_and_name_in_place(tmp_path, monkeypatch):
    """A manual offset, five minutes off what the camera's own GPS photos give, is executed: the photo is
    corrected and named under it. Withdrawn, the offset gives way to the one the tool derives, and the photo's
    time and name are computed again from its own camera time — for the file where it now stands, under the
    name the withdrawn decision gave it, and within its destination; the position the tool derived from the tracks at
    the withdrawn time is derived again, at the new one."""
    ws = _ws(tmp_path, [lambda ws: _rec(ws, f"{T}/a.arw", "2024:07:03 13:50:00", gps=(50.0, 4.0)),
                        lambda ws: _rec(ws, f"{T}/b.arw", "2024:07:03 14:40:00", gps=(50.005, 4.0)),
                        lambda ws: _rec(ws, f"{T}/c.arw", "2024:07:03 14:20:00")])
    _plan(monkeypatch, ws)
    _set_offset(ws, SLOW - 300)
    _plan(monkeypatch, ws)
    _confirm_drift(ws, SLOW - 300)
    _plan(monkeypatch, ws)
    assert _ops(ws)[f"{T}/c.arw"]["to"] == "2024-07-03--14-25-00.arw"    # 14:20 camera + 1:55 = 12:25Z
    assert _ops(ws)[f"{T}/c.arw"]["writes"]["GPSLatitude"] == pytest.approx(50.0025)   # the track at 12:25Z
    _execute(monkeypatch, ws)
    assert (ws / T / "2024-07-03--14-25-00.arw").exists() and not (ws / T / "c.arw").exists()
    _set_offset(ws, "")                                      # the decision withdrawn
    _plan(monkeypatch, ws)
    assert _cell(ws)["effective_time_anchor"] == {"offset_seconds": SLOW, "source": "gpx_anchor_auto"}
    ops = _ops(ws)
    e = ops[f"{T}/2024-07-03--14-25-00.arw"]                 # the file where it stands
    assert e["writes"]["DateTimeOriginal"] == "2024:07:03 14:30:00"      # 14:20 camera + 1:50 = 12:30Z
    assert e["to"] == "2024-07-03--14-30-00.arw"             # a name, not a path: within its destination
    assert e["writes"]["GPSLatitude"] == pytest.approx(50.003)           # the track at 12:30Z: derived again
    assert {"metadata_time_write", "rename_no_clobber"} <= set(e["types"])
    assert all(os.path.exists(ws / rel) for rel in ops)      # every operation is on a file as it stands


def _contradicted_ws(tmp_path, monkeypatch):
    """Five camera photos on the track's points, agreeing on the camera's offset, and `s.arw`, taken at 12:25Z, holding
    the position the track reaches at 13:00Z: its own position, 390 m from where the track was at its true time, is
    contradicted by the accepted offset and offered the track's (BLD-contradicted_position)."""
    recs = [(lambda i: lambda ws: _rec(ws, f"{T}/p{i}.arw", f"2024:07:03 {13 + (50 + 10 * i) // 60}:"
                                       f"{(50 + 10 * i) % 60:02d}:00", gps=(50 + i / 1000, 4.0)))(i) for i in range(5)]
    ws = _ws(tmp_path, recs + [lambda ws: _rec(ws, f"{T}/s.arw", "2024:07:03 14:15:00", gps=(50.006, 4.0))])
    _plan(monkeypatch, ws)
    p = ws / ".photos-ingest" / cal.TIME_DECISIONS_ARTIFACT
    a = json.loads(p.read_text())
    cell = a["destinations"][T]["camera_group_time_decisions"][CAM]
    cell["user_decision"].update(accept_proposal=True, accepted_offset_seconds=cell["proposal"]["proposed_offset_seconds"])
    p.write_text(json.dumps(a))
    _plan(monkeypatch, ws)
    return ws


def _answer_contradicted(ws, lat, lon):
    """Set (or, with "", withdraw) the user's answer to the contradicted own position."""
    p = ws / ".photos-ingest" / "photos-23-gps-decisions.json"
    g = json.loads(p.read_text())
    item = next(ri for ri in g["destinations"][T]["gps_decisions"]["review_items"]
                if ri["reason"] == "own_position_contradicted")
    item["user_decision"].update(manual_lat=lat, manual_lon=lon)
    p.write_text(json.dumps(g))


def _held(ws, rel):
    ho = json.loads((ws / ".photos-ingest" / "photos-11-handoff.json").read_text())
    return json.loads(next(f for f in ho["files"] if f["relative_path"] == rel)["metadata_status"]["parsed_json"])


@pytest.mark.spec("RUL-withdrawal_undoes", "RUL-own_position_kept", "RUL-log_records_gps_reverts",
                  "RUL-finalize_refuses_unplaced", "BLD-decided_from_own_values", "BLD-placement_order",
                  "BLD-executable_plan", "BLD-geotag_log_steps",
                  test="TST-geotag_rerun_markers-a_withdrawn_answer_gives_the_photo_back_its_own_position")
def test_a_withdrawn_answer_gives_the_photo_back_its_own_position(tmp_path, monkeypatch):
    """The user takes the track's position for a photo whose own position the camera's offset contradicts; withdrawn
    before execution, nothing of it is planned. Executed, then withdrawn, the next plan writes the photo's own position
    back, with the device's GPSProcessingMethod and the mark of the time geotag corrected, the log keeping the position
    it replaces: the photo ends as if the answer had never been given, finalize takes it, and a plan after that has
    nothing left to do."""
    ws = _contradicted_ws(tmp_path, monkeypatch)
    _answer_contradicted(ws, 50.0025, 4.0)
    _plan(monkeypatch, ws)
    assert _ops(ws)[f"{T}/s.arw"]["writes"]["GPSProcessingMethod"] == "manual_locked"
    _answer_contradicted(ws, "", "")                         # withdrawn before it was executed: nothing to restore
    _plan(monkeypatch, ws)
    e = _ops(ws)[f"{T}/s.arw"]
    assert "metadata_gps_write" not in e["types"] and "GPSLatitude" not in e["writes"]
    assert e["writes"]["GPSProcessingMethod"] == "+carto-time"

    _answer_contradicted(ws, 50.0025, 4.0)
    _plan(monkeypatch, ws)
    _execute(monkeypatch, ws)
    stray = f"{T}/2024-07-03--14-25-00.arw"
    assert _held(ws, stray)["GPSLatitude"] == pytest.approx(50.0025)
    assert _held(ws, stray)["GPSProcessingMethod"] == "manual_locked"
    _plan(monkeypatch, ws)
    assert _ops(ws) == {}                                    # the answer holds: nothing to write again
    _answer_contradicted(ws, "", "")                         # the answer withdrawn
    _plan(monkeypatch, ws)
    plan = json.loads((ws / ".photos-ingest" / "photos-24-executable-plan.json").read_text())
    ops = [o for d in plan["destinations"].values() for o in d["operations"] if o["relative_path"] == stray]
    assert [o["type"] for o in ops] == ["metadata_gps_write", "gps_marker_write"]
    assert ops[0]["writes"] == {"GPSLatitude": 50.006, "GPSLatitudeRef": "N", "GPSLongitude": 4.0, "GPSLongitudeRef": "E"}
    assert ops[0]["gps_origin"] == "restore_own"
    assert ops[0]["pre_state"] == {"present": True, "GPSLatitude": 50.0025, "GPSLongitude": 4.0,
                                   "GPSProcessingMethod": "manual_locked"}
    assert ops[1]["writes"] == {"GPSProcessingMethod": "+carto-time"}      # its time stays corrected
    assert utils.photos_without_position(json.loads((ws / ".photos-ingest" / "photos-11-handoff.json").read_text()),
                                         plan) == []
    _execute(monkeypatch, ws)
    held = _held(ws, stray)
    assert (held["GPSLatitude"], held["GPSLongitude"], held["GPSProcessingMethod"]) == (50.006, 4.0, "+carto-time")
    _plan(monkeypatch, ws)
    assert _ops(ws) == {}                                    # its own position, kept: nothing more
    _execute(monkeypatch, ws)
    steps = _finalize(monkeypatch, ws)["fp-s.arw"]["journey"]
    gps = [s for s in steps if s["action"] == "gps_written"]
    assert [(s["lat"], s["origin"], s["gps_processing_method"]) for s in gps] == [
        (pytest.approx(50.0025), "apply_manual", "manual_locked"), (50.006, "restore_own", "+carto-time")]
    assert gps[1]["pre_state"]["GPSLatitude"] == pytest.approx(50.0025)


@pytest.mark.spec("RUL-withdrawal_undoes", "RUL-own_position_kept", "RUL-only_corrected_time_marked",
                  "BLD-rerun_recognition",
                  test="TST-geotag_rerun_markers-a_withdrawn_answer_marks_no_time_geotag_never_wrote")
def test_a_withdrawn_answer_marks_no_time_geotag_never_wrote(tmp_path):
    """A camera photo whose time geotag never wrote — it held its true time — and whose own position an answer replaced:
    withdrawn, its own position comes back with the device's own GPSProcessingMethod, no mark of a corrected time; one
    holding its own coordinates already gets only the method back. A photo with no position of its own that nothing
    places now has geotag's position cleared, likewise with no time mark."""
    own_time = {"DateTimeOriginal": "2024:07:03 14:25:00", "OffsetTimeOriginal": "+02:00"}
    original = {"selected_source_naive_timestamp": "2024:07:03 14:25:00",
                "selected_source_timestamp_tag": "EXIF:DateTimeOriginal", **own_time,
                "GPSLatitude": 50.006, "GPSLongitude": 4.0, "GPSProcessingMethod": "GPS", "has_native_gps": True}

    def held(lat, method):
        f = {"relative_path": f"{T}/s.arw", "destination": T, "raw_times": dict(own_time),
             "native_gps": {"lat": lat, "lon": 4.0}, "processing_method": method,
             "content_fingerprint": "fp", "size": 1, "mtime_ns": 1}
        return dict(cal.from_originals(f, original), times_written=[])

    f = held(50.0025, "manual_locked")
    cat, coord = cal.classify_gps(f, None, None, {}, None, {}, replace_own=True)
    assert cat == "preserve_native"
    ops = cal.plan_file_ops(f, "2024-07-03T12:25:00Z", "Europe/Brussels", cat, coord, None)
    assert [(o["type"], o["writes"]) for o in ops] == [
        ("metadata_gps_write", {"GPSLatitude": 50.006, "GPSLatitudeRef": "N", "GPSLongitude": 4.0,
                                "GPSLongitudeRef": "E"}),
        ("gps_marker_write", {"GPSProcessingMethod": "GPS"})]
    ops = cal.plan_file_ops(held(50.006, "manual_locked"), "2024-07-03T12:25:00Z", "Europe/Brussels", cat, coord, None)
    assert [(o["type"], o["writes"]) for o in ops] == [("gps_marker_write", {"GPSProcessingMethod": "GPS"})]

    f = dict(held(50.0025, "manual_locked"), has_native_gps=False, native_gps=None, processing_method=None)
    ops = cal.plan_file_ops(f, "2024-07-03T12:25:00Z", "Europe/Brussels", "blocked", None, None)
    assert [o["writes"] for o in ops] == [{"GPSLatitude": "", "GPSLatitudeRef": "", "GPSLongitude": "",
                                           "GPSLongitudeRef": "", "GPSProcessingMethod": ""}]


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


@pytest.mark.spec("BLD-original_values_pinned", "RUL-geotag_rerun_keeps_settled",
                  test="TST-geotag_rerun_markers-own_gps_camera_anchors_again_after_execute")
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
        # The record of the workspace's state is every execution's to rewrite (RUL-execution_records_state): left out.
        return {t: sorted(map(repr, conn.execute(f"SELECT * FROM {t}" + (" WHERE key != 'workspace_record_id'"
                                                                            if t == "meta" else ""))))
                for t in others}
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


@pytest.mark.spec("RUL-photo_decision_follows_the_photo", "BLD-review_item_identity",
                  test="TST-geotag_rerun_markers-a_decision_follows_a_photo_geotag_never_wrote_through_a_retake")
def test_a_decision_follows_a_photo_geotag_never_wrote_through_a_retake(tmp_path, monkeypatch):
    """A position the user chose for a photo geotag has not written — so holds no pin — is kept under the photo's
    fingerprint; prep then takes the fingerprint again with a new ImageMagick. The decision is still the photo's: the
    next plan finds it by the value before, never dropping it."""
    ws = _ws(tmp_path, [lambda ws: _rec(ws, f"{T}/a.arw", "2024:07:03 14:20:00")])
    _plan(monkeypatch, ws)
    _set_offset(ws, SLOW)
    _plan(monkeypatch, ws)
    _confirm_drift(ws, SLOW)
    _plan(monkeypatch, ws)
    ctl = ws / ".photos-ingest"
    gp = ctl / "photos-23-gps-decisions.json"
    gps = json.loads(gp.read_text())
    gps["destinations"][T]["gps_decisions"]["review_items"].append(
        {"relative_path": f"{T}/a.arw", "content_fingerprint": "fp-a.arw", "reason": "chosen_by_user",
         "user_decision": {"manual_lat": 45.5, "manual_lon": 6.5}})
    gp.write_text(json.dumps(gps))
    _plan(monkeypatch, ws)
    assert _originals(ws) == {}                                              # never written: no pin
    _retake_fingerprint(ws, "fp-a.arw", "fp-new")
    _plan(monkeypatch, ws)
    items = json.loads(gp.read_text())["destinations"][T]["gps_decisions"]["review_items"]
    assert [(i["reason"], i["user_decision"]) for i in items if i["relative_path"] == f"{T}/a.arw"] == [
        ("manual_locked", {"manual_lat": 45.5, "manual_lon": 6.5})], items
    assert _ops(ws)[f"{T}/a.arw"]["writes"]["GPSLatitude"] == pytest.approx(45.5)


@pytest.mark.spec("RUL-fingerprint_mapping_one_to_one", "BLD-original_values_follow_fingerprint",
                  test="TST-geotag_rerun_markers-a_fingerprint_mapping_not_one_to_one_stops_geotag")
def test_a_fingerprint_mapping_not_one_to_one_stops_geotag(tmp_path, monkeypatch):
    ws = _executed_round(tmp_path, monkeypatch)
    _retake_fingerprint(ws, "fp-a.arw", "fp-new", also="fp-other")
    blockers, _, _ = cal.GeotagWorkflow(str(ws)).preflight()
    assert any("more than one value" in b and "re-run prep" in b for b in blockers), blockers
    # neither plan nor execute: execution and finalize stop on it too
    for needs_exiftool in (True, False):
        blockers, _, _ = cal.GeotagWorkflow(str(ws)).preflight(for_execute=True, needs_exiftool=needs_exiftool)
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


@pytest.mark.spec("RUL-geotag_executes_on_vouched_log", "BLD-original_values_follow_fingerprint",
                  test="TST-geotag_rerun_markers-an_unvouched_prep_log_stops_execution")
@pytest.mark.parametrize("spoil", ["changed", "missing", "no_hash"])
def test_an_unvouched_prep_log_stops_execution(tmp_path, monkeypatch, capsys, spoil):
    """A plan made on a vouched log, the log then changed under it: execution would carry the pinned values by a
    mapping nothing vouches for. It stops before any change — no snapshot, no decision kept, no write, no pin
    moved — exits 2, and sends the user to prep, then to plan again."""
    ws = _executed_round(tmp_path, monkeypatch)
    pinned = _originals(ws)
    _retake_fingerprint(ws, "fp-a.arw", "fp-new")
    _confirm_drift(ws, SLOW - 300)
    _plan(monkeypatch, ws)
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

    def state():
        return {p.relative_to(ws).as_posix(): p.read_bytes() for p in sorted(ws.rglob("*"))
                if p.is_file() and not p.name.startswith("photos-00-")}
    before = state()

    def untouchable(*a, **k):
        raise AssertionError("execution went past an unvouched log")
    monkeypatch.setattr(cal, "take_zfs_snapshot", untouchable)
    monkeypatch.setattr(cal.GeotagWorkflow, "_exiftool_write", untouchable)
    monkeypatch.setattr(cal.GeotagWorkflow, "_keep_executed_decisions", untouchable)
    monkeypatch.chdir(str(ws))
    monkeypatch.setattr(sys, "argv", ["photos-2-geotag", "execute"])
    capsys.readouterr()
    with pytest.raises(SystemExit) as ei:
        cal.main()
    out = capsys.readouterr()
    said = (out.out + out.err).lower()
    assert ei.value.code == 2
    assert "prep's log" in said and "`prep plan` and `prep execute`, then `geotag plan`" in said
    assert state() == before
    assert _originals(ws) == pinned                                          # the pin did not move


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


def _hand_set_time(ws, dto, off, name=None):
    """The photo's time set in another tool after geotag wrote it, as the next re-prep reads it back — the one photo,
    or the one named."""
    ho = json.loads((ws / ".photos-ingest" / "photos-11-handoff.json").read_text())
    (f,) = [f for f in ho["files"] if name is None or os.path.basename(f["relative_path"]) == name]
    parsed = json.loads(f["metadata_status"]["parsed_json"])
    parsed.update(DateTimeOriginal=dto, OffsetTimeOriginal=off, selected_source_naive_timestamp=dto)
    f["metadata_status"]["parsed_json"] = json.dumps(parsed)
    _write_handoff(ws, ho["files"])


def _plan_record(ws):
    return json.loads((ws / ".photos-ingest" / "photos-24-executable-plan.json").read_text())


def _changed_cell(ws, rel=None):
    a = json.loads((ws / ".photos-ingest" / cal.TIME_DECISIONS_ARTIFACT).read_text())
    cells = a["destinations"][T].get("changed_times") or {}
    return a, (cells[rel] if rel else next(iter(cells.values()), None))


def _answer_changed(ws, keep, answered_for=None):
    """The user's answer to a time changed since geotag wrote it, as the editor writes it in photos-21."""
    p = ws / ".photos-ingest" / cal.TIME_DECISIONS_ARTIFACT
    a = json.loads(p.read_text())
    (cell,) = a["destinations"][T]["changed_times"].values()
    cell["user_decision"] = {"keep": keep, "answered_for": cell["held_time"] if answered_for is None else answered_for}
    p.write_text(json.dumps(a))


WROTE = "2024-07-03--14-30-00.arw"       # the name geotag gave the photo, from the time it wrote


@pytest.mark.parametrize("dto, off", [("2024:07:03 14:45:00", "+02:00"),      # the time put right by hand
                                      ("2024:07:03 14:30:00", "+01:00")])     # or only its offset
@pytest.mark.spec("RUL-changed_time_stops_plan", "RUL-changed_time_asked", "BLD-changed_time_blocks",
                  "BLD-changed_time_question",
                  test="TST-geotag_rerun_markers-a_time_changed_since_geotag_wrote_it_stops_the_plan")
def test_a_time_changed_since_geotag_wrote_it_stops_the_plan(tmp_path, monkeypatch, dto, off):
    """A photo geotag corrected to 14:30 +02:00 from its own 14:20, then changed in another tool: photos-21 asks about
    it — naming the time it holds, the time geotag wrote and its own — and nothing is planned past it: geotag neither
    writes its time back nor decides from the new one unasked."""
    ws = _executed_round(tmp_path, monkeypatch)
    plan_before = _plan_record(ws)
    _hand_set_time(ws, dto, off)
    _plan(monkeypatch, ws)
    art, cell = _changed_cell(ws, f"{T}/{WROTE}")
    assert art["requires_user_input"] and cell["requires_user_input"]
    assert cell["held_time"] == {"DateTimeOriginal": dto, "OffsetTimeOriginal": off}
    assert cell["geotag_wrote"] == {"DateTimeOriginal": "2024:07:03 14:30:00", "OffsetTimeOriginal": "+02:00"}
    assert cell["own_time"] == {"DateTimeOriginal": "2024:07:03 14:20:00", "OffsetTimeOriginal": None}
    assert cell["user_decision"] == {"keep": "", "answered_for": ""} and cell["content_fingerprint"] == "fp-a.arw"
    assert _plan_record(ws)["plan_id"] == plan_before["plan_id"]       # no plan made past the question
    rows = cal.GeotagCache(str(ws))
    try:
        (row,) = rows.get_rows()
    finally:
        rows.close()
    assert row["source_naive_time"] == "2024:07:03 14:20:00"          # still decided from its own time


@pytest.mark.spec("RUL-changed_time_restored", "BLD-changed_time_restored_written", "BLD-changed_time_question",
                  "RUL-every_question_answerable_by_hand",
                  test="TST-geotag_rerun_markers-a_changed_time_restored_has_geotag_s_written_back")
def test_a_changed_time_restored_has_geotag_s_written_back(tmp_path, monkeypatch):
    """Answered `geotag`, the photo is planned as any photo whose time is not the one geotag decides: geotag's time is
    written back over the one it holds, decided from its own time as before."""
    ws = _executed_round(tmp_path, monkeypatch)
    _hand_set_time(ws, "2024:07:03 14:45:00", "+02:00")
    _plan(monkeypatch, ws)
    _answer_changed(ws, "geotag")
    _plan(monkeypatch, ws)
    _, cell = _changed_cell(ws)
    assert cell["effective_answer"] == "geotag" and not cell["requires_user_input"]
    plan = _plan_record(ws)
    assert plan["status"] == "ready" and plan["true_times_kept"] == {}
    w = _ops(ws)[f"{T}/{WROTE}"]["writes"]
    assert (w["DateTimeOriginal"], w["OffsetTimeOriginal"]) == ("2024:07:03 14:30:00", "+02:00")


def _rows(ws):
    db = cal.GeotagCache(str(ws))
    try:
        return {r["relative_path"]: r for r in db.get_rows()}
    finally:
        db.close()


KEPT = "2024-07-03--14-45-00.arw"        # the name the kept time gives it


@pytest.mark.spec("RUL-changed_time_kept_is_true", "BLD-changed_time_kept", "BLD-changed_time_kept_pinned",
                  "BLD-changed_time_question", "RUL-other_capture_times_corrected", "BLD-resolved_utc",
                  test="TST-geotag_rerun_markers-a_changed_time_kept_is_the_photo_s_true_local_time")
def test_a_changed_time_kept_is_the_photo_s_true_local_time(tmp_path, monkeypatch):
    """Answered `new`, the time the photo holds is its true local time: read by its destination's zone, the camera's
    ten minutes slow not applied to it again, the photo placed and named by it and its other time fields brought into
    line; execution records it beside the pin, its own values staying, so the next plan asks nothing and writes
    nothing — and goes on reading it as the true time."""
    ws = _executed_round(tmp_path, monkeypatch)
    ho = json.loads((ws / ".photos-ingest" / "photos-11-handoff.json").read_text())
    parsed = json.loads(ho["files"][0]["metadata_status"]["parsed_json"])
    parsed["XMP:DateCreated"] = "2024:07:03 14:30:00+02:00"         # geotag's time, in a field the tool left
    ho["files"][0]["metadata_status"]["parsed_json"] = json.dumps(parsed)
    _write_handoff(ws, ho["files"])
    _hand_set_time(ws, "2024:07:03 14:45:00", "+02:00")
    _plan(monkeypatch, ws)
    _answer_changed(ws, "new")
    _plan(monkeypatch, ws)
    _, cell = _changed_cell(ws)
    assert cell["effective_answer"] == "new" and not cell["requires_user_input"]
    assert "offset_tag_disagrees" not in cell                        # +02:00 is Brussels' then
    plan = _plan_record(ws)
    assert plan["status"] == "ready", plan["blockers"]
    assert plan["true_times_kept"] == {f"{T}/{WROTE}": {
        "DateTimeOriginal": "2024:07:03 14:45:00", "OffsetTimeOriginal": "+02:00", "content_fingerprint": "fp-a.arw"}}
    row = _rows(ws)[f"{T}/{WROTE}"]
    assert (row["time_rule_used"], row["resolved_utc"], row["utc_offset_used"]) == \
        ("kept_true_time", "2024-07-03T12:45:00Z", None)                # by the zone: no clock offset on it
    e = _ops(ws)[f"{T}/{WROTE}"]
    w = e["writes"]
    assert w["DateTimeOriginal"] == "2024:07:03 14:45:00" and w["OffsetTimeOriginal"] == "+02:00"   # not rewritten
    assert w["XMP:DateCreated"] == "2024:07:03 14:45:00+02:00"         # the other field in line with it
    assert w["GPSLatitude"] == pytest.approx(50.0045)                   # placed at 12:45Z, between two points
    assert e["to"] == KEPT
    (op,) = [o for d in plan["destinations"].values() for o in d["operations"] if o["type"] == "metadata_time_write"]
    assert op["provenance"]["because"] == f"photos-21 destinations.{T}.changed_times[{T}/{WROTE}]"
    _execute(monkeypatch, ws)
    (pin,) = _originals(ws).values()
    assert pin["true_time"] == {"DateTimeOriginal": "2024:07:03 14:45:00", "OffsetTimeOriginal": "+02:00"}
    assert (pin["DateTimeOriginal"], pin["selected_source_naive_timestamp"]) == \
        ("2024:07:03 14:20:00", "2024:07:03 14:20:00")                  # its own values stay
    _plan(monkeypatch, ws)
    art, cell = _changed_cell(ws)
    assert not art["requires_user_input"] and _ops(ws) == {}                     # decided: nothing asked or written
    # the answer stays in the record while it stands, there to be withdrawn
    assert cell["user_decision"]["keep"] == "new" and cell["effective_answer"] == "new" and not cell["requires_user_input"]
    row = _rows(ws)[f"{T}/{KEPT}"]
    assert (row["time_rule_used"], row["resolved_utc"]) == ("kept_true_time", "2024-07-03T12:45:00Z")


@pytest.mark.spec("RUL-changed_time_restored", "BLD-changed_time_restored_written", "BLD-changed_time_kept_pinned",
                  "BLD-changed_time_blocks",
                  test="TST-geotag_rerun_markers-a_time_changed_after_one_was_kept_restores_the_kept_one")
def test_a_time_changed_after_one_was_kept_restores_the_kept_one(tmp_path, monkeypatch):
    """A time kept and executed is the one geotag decides from: the photo's time changed by hand again, the question
    names the kept time as the photo's own, and taking back geotag's writes the kept time back — never the camera's
    own time corrected again."""
    ws = _executed_round(tmp_path, monkeypatch)
    _hand_set_time(ws, "2024:07:03 14:45:00", "+02:00")
    _plan(monkeypatch, ws)
    _answer_changed(ws, "new")
    _plan(monkeypatch, ws)
    _execute(monkeypatch, ws)
    _hand_set_time(ws, "2024:07:03 16:00:00", "+02:00")
    _plan(monkeypatch, ws)
    _, cell = _changed_cell(ws)
    assert cell["requires_user_input"]
    assert cell["own_time"] == {"DateTimeOriginal": "2024:07:03 14:45:00", "OffsetTimeOriginal": "+02:00"}
    _answer_changed(ws, "geotag")
    _plan(monkeypatch, ws)
    w = _ops(ws)[f"{T}/{KEPT}"]["writes"]
    assert (w["DateTimeOriginal"], w["OffsetTimeOriginal"]) == ("2024:07:03 14:45:00", "+02:00")


@pytest.mark.spec("RUL-kept_time_holds_while_answer_stands", "BLD-changed_time_kept_pinned",
                  test="TST-geotag_rerun_markers-a_withdrawn_keep_asks_again")
def test_a_withdrawn_keep_answer_asks_the_question_again(tmp_path, monkeypatch):
    """A time kept and executed: the answer stays in photos-21. Withdrawn there, the kept time is decided from no
    longer — the question is asked again, and nothing is written back unasked. Answered then to take back geotag's
    time, the plan writes it, and execution takes the kept time out of the pin: the next plan asks nothing."""
    ws = _executed_round(tmp_path, monkeypatch)
    _hand_set_time(ws, "2024:07:03 14:45:00", "+02:00")
    _plan(monkeypatch, ws)
    _answer_changed(ws, "new")
    _plan(monkeypatch, ws)
    _execute(monkeypatch, ws)
    _plan(monkeypatch, ws)
    _, cell = _changed_cell(ws)
    assert cell["user_decision"]["keep"] == "new" and not cell["requires_user_input"]
    p = ws / ".photos-ingest" / cal.TIME_DECISIONS_ARTIFACT
    a = json.loads(p.read_text())
    (cell,) = a["destinations"][T]["changed_times"].values()
    cell["user_decision"] = {"keep": "", "answered_for": ""}                 # withdrawn, as the editor clears it
    p.write_text(json.dumps(a))
    plan_before = _plan_record(ws)
    _plan(monkeypatch, ws)
    art, cell = _changed_cell(ws)
    assert cell["requires_user_input"] and art["requires_user_input"]        # asked again
    assert cell["held_time"] == {"DateTimeOriginal": "2024:07:03 14:45:00", "OffsetTimeOriginal": "+02:00"}
    assert _plan_record(ws) == plan_before                                   # nothing planned, nothing written back
    (pin,) = _originals(ws).values()
    assert "true_time" in pin                                                # nothing reverted unasked
    _answer_changed(ws, "geotag")
    _plan(monkeypatch, ws)
    plan = _plan_record(ws)
    assert plan["status"] == "ready" and plan["true_times_dropped"] == [f"{T}/{KEPT}"], plan
    w = _ops(ws)[f"{T}/{KEPT}"]["writes"]
    assert (w["DateTimeOriginal"], w["OffsetTimeOriginal"]) == ("2024:07:03 14:30:00", "+02:00")
    _execute(monkeypatch, ws)
    (pin,) = _originals(ws).values()
    assert "true_time" not in pin
    _plan(monkeypatch, ws)
    art, cell = _changed_cell(ws)
    assert cell is None and not art["requires_user_input"] and _ops(ws) == {}


@pytest.mark.spec("RUL-kept_time_not_clock_evidence", "BLD-changed_time_kept_not_anchor",
                  test="TST-geotag_rerun_markers-a_kept_time_is_no_anchor_of_its_camera")
def test_a_kept_time_is_no_anchor_of_its_camera(tmp_path, monkeypatch):
    """A camera with its own GPS, its clock found from its positions on the track. One photo's time set by hand to the
    true time and kept: its position, against the kept time, would read the clock two minutes otherwise — it is no
    reading of the camera's clock, so the cell's offset rests on the other photo alone, and is applied to it alone."""
    ws = _ws(tmp_path, [lambda ws: _rec(ws, f"{T}/a.arw", "2024:07:03 13:50:00", gps=(50.0, 4.0)),
                        lambda ws: _rec(ws, f"{T}/b.arw", "2024:07:03 14:40:00", gps=(50.005, 4.0))])
    _plan(monkeypatch, ws)
    _execute(monkeypatch, ws)                     # a at 14:00 +02:00, b at 14:50 +02:00, both pinned
    before = _cell(ws)
    _hand_set_time(ws, "2024:07:03 14:52:00", "+02:00", name="2024-07-03--14-50-00.arw")
    _plan(monkeypatch, ws)
    _answer_changed(ws, "new")
    _plan(monkeypatch, ws)
    plan = _plan_record(ws)
    assert plan["status"] == "ready", plan["blockers"]
    cell = _cell(ws)
    assert cell["effective_time_anchor"]["offset_seconds"] == before["effective_time_anchor"]["offset_seconds"] == -6600
    assert (before["proposal"]["anchor_count"], cell["proposal"]["anchor_count"]) == (2, 1)   # the kept one is none
    assert "2024-07-03--14-50-00.arw" not in json.dumps(cell["proposal"])
    rows = _rows(ws)
    assert rows[f"{T}/2024-07-03--14-50-00.arw"]["time_rule_used"] == "kept_true_time"
    assert rows[f"{T}/2024-07-03--14-00-00.arw"]["time_rule_used"] == "camera_group_offset"
    assert _ops(ws) == {f"{T}/2024-07-03--14-50-00.arw": {"writes": {}, "types": ["rename_no_clobber"],
                                                         "to": "2024-07-03--14-52-00.arw"}}


@pytest.mark.spec("RUL-kept_time_tag_disagreement_told", "RUL-kept_time_tag_disagreement_recorded",
                  "BLD-changed_time_kept_tag_noted", "RUL-changed_time_kept_is_true", "BLD-changed_time_kept",
                  test="TST-geotag_rerun_markers-a_kept_time_s_offset_tag_its_zone_does_not_give_is_told")
def test_a_kept_time_s_offset_tag_its_zone_does_not_give_is_told(tmp_path, monkeypatch, capsys):
    """The time set by hand with an offset tag Brussels did not have then (+09:00): the question records the tag and the
    zone's offset and the plan says so, naming the photo. Kept, the time is read by the zone, not by the tag, and the
    tag is written to the zone's."""
    ws = _executed_round(tmp_path, monkeypatch)
    _hand_set_time(ws, "2024:07:03 14:45:00", "+09:00")
    capsys.readouterr()
    _plan(monkeypatch, ws)
    out = capsys.readouterr()
    said = out.out + out.err
    _, cell = _changed_cell(ws)
    assert cell["offset_tag_disagrees"] == {"recorded_offset_seconds": 9 * 3600, "timezone": "Europe/Brussels",
                                            "timezone_offsets_seconds": [7200]}
    assert f"{WROTE}: its offset tag says +09:00, but Europe/Brussels is +02:00" in said
    _answer_changed(ws, "new")
    _plan(monkeypatch, ws)
    assert _rows(ws)[f"{T}/{WROTE}"]["resolved_utc"] == "2024-07-03T12:45:00Z"    # by the zone, not 05:45Z
    w = _ops(ws)[f"{T}/{WROTE}"]["writes"]
    assert (w["DateTimeOriginal"], w["OffsetTimeOriginal"]) == ("2024:07:03 14:45:00", "+02:00")


@pytest.mark.spec("RUL-ambiguous_local_time_answered", "BLD-local_time_readings", "RUL-changed_time_kept_is_true",
                  "BLD-changed_time_kept",
                  test="TST-geotag_rerun_markers-a_kept_time_the_zone_repeats_is_asked")
def test_a_kept_time_the_zone_repeats_is_asked(tmp_path, monkeypatch):
    """A time kept as the true local time that Brussels shows twice — 02:30 on the night the clocks go back — is asked
    which of its two readings it is, as any time the zone reads; answered, it is read by that one."""
    ws = _executed_round(tmp_path, monkeypatch)
    _hand_set_time(ws, "2024:10:27 02:30:00", "+02:00")
    _plan(monkeypatch, ws)
    _answer_changed(ws, "new")
    _plan(monkeypatch, ws)
    a = json.loads((ws / ".photos-ingest" / cal.TIME_DECISIONS_ARTIFACT).read_text())
    reading = a["destinations"][T]["local_time_readings"][f"{T}/{WROTE}"]
    assert (reading["case"], reading["offsets_seconds"], reading["requires_user_input"]) == ("repeated", [7200, 3600], True)
    assert a["requires_user_input"] and "offset_tag_disagrees" not in a["destinations"][T]["changed_times"][f"{T}/{WROTE}"]
    reading["user_decision"]["utc_offset_seconds"] = 3600
    (ws / ".photos-ingest" / cal.TIME_DECISIONS_ARTIFACT).write_text(json.dumps(a))
    _plan(monkeypatch, ws)
    row = _rows(ws)[f"{T}/{WROTE}"]
    assert (row["time_rule_used"], row["resolved_utc"]) == ("local_time_answered", "2024-10-27T01:30:00Z")


@pytest.mark.spec("RUL-log_cites_decisions", "BLD-geotag_log_steps", "BLD-log_format",
                  test="TST-geotag_rerun_markers-a_kept_time_is_logged_with_its_decision")
def test_a_kept_time_is_logged_with_its_decision():
    """The log records a time kept as the photo's true time, naming the photos-21 entry that kept it, for the pass
    being finalized and for an earlier one alike — and no clock offset applied."""
    rel = f"{T}/a.arw"
    kept = {rel: {"DateTimeOriginal": "2024:07:03 14:45:00", "OffsetTimeOriginal": "+02:00", "content_fingerprint": "fp"}}
    plan = {"plan_id": "p2", "true_times_kept": kept, "destinations": {},
            "depends_on": {"time_decisions": {"sha256": "abc", "artifact_name": cal.TIME_DECISIONS_ARTIFACT}}}
    files = [{"relative_path": rel, "destination": T, "camera_group_key": CAM, "content_fingerprint": "fp"}]
    rows = [{"relative_path": rel, "time_rule_used": "kept_true_time", "resolved_utc": "2024-07-03T12:45:00Z"}]
    because = f"photos-21 destinations.{T}.changed_times[{rel}]"
    for earlier, current in (((), plan), (((plan, set()),), dict(plan, plan_id="p3", true_times_kept={}))):
        log = cal.build_complete_log({}, files, rows, {}, current, earlier_passes=earlier)
        steps = log["fp"]["journey"]
        (step,) = [s for s in steps if s["action"] == "true_time_kept"]
        assert (step["value"], step["because"], step["run"], step["because_record_sha256"]) == \
            ("2024:07:03 14:45:00", because, "p2", "abc")
        assert not any(s["action"] == "clock_offset_applied" for s in steps)


@pytest.mark.spec("RUL-changed_time_asked", "BLD-changed_time_question",
                  test="TST-geotag_rerun_markers-a_changed_time_s_answer_holds_for_the_time_it_was_given_for")
def test_a_changed_time_s_answer_holds_for_the_time_it_was_given_for(tmp_path, monkeypatch):
    """An answer names the time it was given for: the photo's time changed again, it is stale and asks again; a value
    that is no answer is a blocker naming the field, the record left as it is."""
    ws = _executed_round(tmp_path, monkeypatch)
    _hand_set_time(ws, "2024:07:03 14:45:00", "+02:00")
    _plan(monkeypatch, ws)
    _answer_changed(ws, "new", {"DateTimeOriginal": "2024:07:03 14:40:00", "OffsetTimeOriginal": "+02:00"})
    _plan(monkeypatch, ws)
    _, cell = _changed_cell(ws)
    assert cell["stale_user_decision"] and cell["requires_user_input"] and cell["effective_answer"] == ""
    assert cell["user_decision"]["keep"] == "new"                       # kept as written
    _answer_changed(ws, "both")
    before = (ws / ".photos-ingest" / cal.TIME_DECISIONS_ARTIFACT).read_text()
    _plan(monkeypatch, ws)
    assert (ws / ".photos-ingest" / cal.TIME_DECISIONS_ARTIFACT).read_text() == before


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
