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

"""Geotag's own GPSProcessingMethod markers on a re-run (geotag §30, shared contract §10.1).

A geotag marker means the file's time is already corrected; a position marker also means its
position is geotag's, ignored until placed again. A device's own GPSProcessingMethod value is native.
Execution is simulated: each plan's writes are folded into the handoff the way a re-prep would read
them back, so the re-run sees what the files hold. From conftest.py.
"""
import json
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
            "metadata_status": {"camera_group_key": key, "has_timestamp": True, "has_native_gps": bool(gps),
                                "field_set_version": 1, "parsed_json": json.dumps(parsed)}}


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
    _write_handoff(ws, [r(ws) for r in recs])
    return ws


def _write_handoff(ws, files):
    ho = {"run_metadata": {"plan_id": "prep-1", "execution_id": "exec-1"}, "files": files,
          "cache_fingerprint": "pcf"}
    ho["content_fingerprint"] = utils.handoff_content_fingerprint(ho)
    (ws / ".photos-ingest" / "photos-11-handoff.json").write_text(json.dumps(ho))


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
    """Confirm the GPS-drift check a manual offset with track coverage triggers (§22a)."""
    p = ws / ".photos-ingest" / "photos-22-gps-drift-validation.json"
    a = json.loads(p.read_text())
    a["destinations"][T]["drift_decisions"][bucket]["user_decision"].update(
        confirmed=True, corrected_offset_seconds=offset)
    p.write_text(json.dumps(a))


def _ops(ws):
    """{relative_path: {"writes": merged tag writes, "types": [...], "to": rename target}} of photos-24."""
    plan = json.loads((ws / ".photos-ingest" / "photos-24-executable-plan.json").read_text())
    assert plan["status"] == "ready", plan.get("blockers")
    out = {}
    for d in plan["destinations"].values():
        for op in sorted(d["operations"], key=lambda o: o["type"] != "revert_manual_gps"):
            e = out.setdefault(op["relative_path"], {"writes": {}, "types": [], "to": None})
            e["types"].append(op["type"])
            e["writes"].update(op.get("writes") or {})
            if op["type"] == "rename_no_clobber":
                e["to"] = op["to"]
    return out


def _executed_and_reprepped(ws, renamed_on_disk=False):
    """Fold photos-24's writes and renames into the handoff, as a re-prep reads the files back.
    `renamed_on_disk`: a real execute already renamed the files."""
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
        if e["to"]:
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
    assert a["writes"]["GPSLatitude"] == pytest.approx(50.003) and a["writes"]["GPSProcessingMethod"] == "interpolated"
    _executed_and_reprepped(ws)
    return ws


@pytest.mark.spec("loop-geotag-rerun-safe-1", "geotag-marker-time-corrected-1", "geotag-held-write-noop-1", "RUL-geotag_rerun_keeps_settled", "RUL-no_op_run", test="TST-geotag_rerun_markers-manual_offset_is_not_applied_twice")
def test_manual_offset_is_not_applied_twice(tmp_path, monkeypatch):
    ws = _first_round(tmp_path, monkeypatch)
    _plan(monkeypatch, ws)
    assert _ops(ws) == {}                                    # time, fix and name all held already
    t = json.loads((ws / ".photos-ingest" / cal.TIME_DECISIONS_ARTIFACT).read_text())
    cell = t["destinations"][T]["camera_group_time_decisions"][CAM]          # nothing asked, answer kept
    assert cell["effective_time_anchor"]["offset_seconds"] == SLOW and not cell["requires_user_input"]


@pytest.mark.spec("geotag-marker-time-corrected-1", "geotag-offset-kept-1", "RUL-geotag_rerun_keeps_settled", test="TST-geotag_rerun_markers-new_photo_joins_corrected_ones")
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


@pytest.mark.spec("geotag-position-marker-not-native-1", "RUL-geotag_rerun_keeps_settled", test="TST-geotag_rerun_markers-geotag_position_is_placed_again")
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


@pytest.mark.spec("geotag-time-only-marker-1", "RUL-geotag_rerun_keeps_settled", test="TST-geotag_rerun_markers-own_gps_camera_is_marked_time_fixed")
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


@pytest.mark.spec("geotag-offset-kept-1", test="TST-geotag_rerun_markers-gps_derived_offset_is_kept_for_later_photos")
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


@pytest.mark.spec("geotag-device-marker-native-1", test="TST-geotag_rerun_markers-a_devices_own_marker_is_native")
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


@pytest.mark.spec("geotag-position-marker-not-native-1", test="TST-geotag_rerun_markers-unlocated_geotag_position_is_cleared")
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


@pytest.mark.spec("RUL-decision_revisable", "geotag-originals-pinned-1", test="TST-geotag_rerun_markers-changed_offset_after_execute_reaches_the_photo")
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
    assert _cell(ws)["requires_user_input"] and _cell(ws)["effective_time_anchor"] == ""


@pytest.mark.spec("geotag-originals-pinned-1", test="TST-geotag_rerun_markers-originals_are_pinned_once_and_complete")
def test_originals_are_pinned_once_and_complete(tmp_path, monkeypatch):
    ws = _executed_round(tmp_path, monkeypatch)
    pinned = _originals(ws)
    assert pinned == {"fp-a.arw": {"DateTimeOriginal": "2024:07:03 14:20:00", "OffsetTimeOriginal": None,
                                   "GPSLatitude": None, "GPSLongitude": None, "GPSProcessingMethod": None,
                                   "has_native_gps": False,
                                   "selected_source_naive_timestamp": "2024:07:03 14:20:00",
                                   "selected_source_timestamp_tag": "DateTimeOriginal"}}
    _confirm_drift(ws, SLOW - 60)
    _plan(monkeypatch, ws)
    _execute(monkeypatch, ws)
    assert _originals(ws) == pinned                          # never overwritten


@pytest.mark.spec("geotag-originals-pinned-1", test="TST-geotag_rerun_markers-a_marked_photo_is_not_pinned")
def test_a_marked_photo_is_not_pinned(tmp_path, monkeypatch):
    """A photo geotag marked before (elsewhere) holds no original values: nothing is pinned, and its time
    is taken as fixed."""
    ws = _ws(tmp_path, [lambda ws: _rec(ws, f"{T}/2024-07-03--14-30-00.arw", "2024:07:03 14:30:00",
                                        gps=(40.0, 3.0), method="interpolated")])
    _plan(monkeypatch, ws)
    assert f"{T}/2024-07-03--14-30-00.arw" in _ops(ws)       # re-placed from the track
    _execute(monkeypatch, ws)
    assert _originals(ws) == {}


@pytest.mark.spec("geotag-originals-pinned-1", test="TST-geotag_rerun_markers-own_gps_camera_anchors_again_after_execute")
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


def _finalize(monkeypatch, ws):
    monkeypatch.chdir(str(ws))
    monkeypatch.setattr(sys, "argv", ["photos-2-geotag", "finalize"])
    try:
        cal.main()
    except SystemExit as e:
        assert e.code in (0, None), e.code
    return json.loads((ws / ".photos-ingest" / "photos-26-complete-log.json").read_text())["photos"]


@pytest.mark.spec("RUL-log_entry_grows", "RUL-partial_history_shown", "RUL-history_retained", "log-every-geotag-pass-1", "log-decision-version-kept-1", test="TST-geotag_rerun_markers-the_log_keeps_every_geotag_pass")
def test_the_log_keeps_every_geotag_pass(tmp_path, monkeypatch):
    """Finalize logs what every executed pass did, in order and matched by fingerprint — not only the
    latest plan's operations: a photo corrected, then corrected again, then left alone shows all three."""
    ws = _executed_round(tmp_path, monkeypatch)                          # pass 1: placed and renamed
    _confirm_drift(ws, SLOW - 300)
    _plan(monkeypatch, ws)
    _execute(monkeypatch, ws)                                            # pass 2: corrected again
    _plan(monkeypatch, ws)
    _execute(monkeypatch, ws)                                            # pass 3: nothing left to write
    steps = _finalize(monkeypatch, ws)["fp-a.arw"]["journey"]
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


@pytest.mark.spec("RUL-partial_history_shown", "log-fail-if-insufficient-1", "log-partial-geotag-history-1", test="TST-geotag_rerun_markers-a_history_too_thin_is_marked_partial")
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


@pytest.mark.spec("BLD-phase_logs", "RUL-partial_history_shown", "log-carried-unchanged-1", test="TST-geotag_rerun_markers-finalize_carries_prep_s_record_unchanged")
def test_finalize_carries_prep_s_record_unchanged(tmp_path, monkeypatch):
    """Finalize's log carries prep's every field and step unchanged, a note of prep's among them, and adds
    only its own: geotag's note goes in a step of its own. A prep log gone is said, never passed over."""
    ws = _ws(tmp_path, [lambda ws: _rec(ws, f"{T}/2024-07-03--14-30-00.arw", "2024:07:03 14:30:00",
                                        gps=(40.0, 3.0), method="interpolated")])
    p = ws / ".photos-ingest" / "photos-11-handoff.json"
    ho = json.loads(p.read_text())
    parsed = json.loads(ho["files"][0]["metadata_status"]["parsed_json"])
    parsed["OffsetTimeOriginal"] = "+02:00"
    ho["files"][0]["metadata_status"]["parsed_json"] = json.dumps(parsed)
    _write_handoff(ws, ho["files"])
    fp = "fp-2024-07-03--14-30-00.arw"
    prep = {fp: {"content_fingerprint": fp, "final_path": "x", "partial": True,
                 "note": "prep history incomplete (no retained journey)",
                 "journey": [{"phase": "prep", "action": "moved_to_by_date", "from": "a", "to": "b"}]}}
    (ws / ".photos-ingest" / "photos-15-prep-log.json").write_text(json.dumps({"photos": prep}))
    _plan(monkeypatch, ws)
    _execute(monkeypatch, ws)
    entry = _finalize(monkeypatch, ws)[fp]
    assert {k: entry[k] for k in prep[fp] if k != "journey"} == {k: v for k, v in prep[fp].items() if k != "journey"}
    assert entry["journey"][:1] == prep[fp]["journey"]
    assert any(s["action"] == "history_incomplete" for s in entry["journey"][1:])
    log = json.loads((ws / ".photos-ingest" / "photos-26-complete-log.json").read_text())
    assert not any("prep's log" in w for w in log["warnings"])

    (ws / ".photos-ingest" / "photos-15-prep-log.json").unlink()
    _finalize(monkeypatch, ws)
    log = json.loads((ws / ".photos-ingest" / "photos-26-complete-log.json").read_text())
    assert log["partial"] and any("prep's log" in w and "missing" in w for w in log["warnings"])


@pytest.mark.spec("BLD-phase_logs", test="TST-geotag_rerun_markers-a_copy_that_would_alter_prep_s_record_is_refused")
def test_a_copy_that_would_alter_prep_s_record_is_refused(tmp_path, monkeypatch, capsys):
    """Were finalize's copy to change prep's record, finalize writes nothing and says so."""
    ws = _executed_round(tmp_path, monkeypatch)
    fp = "fp-prep-only"
    (ws / ".photos-ingest" / "photos-15-prep-log.json").write_text(json.dumps(
        {"photos": {fp: {"content_fingerprint": fp, "final_path": "x", "journey": []}}}))
    real = cal.build_complete_log

    def altering(*a, **k):
        photos = real(*a, **k)
        photos[fp]["final_path"] = "elsewhere"
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
