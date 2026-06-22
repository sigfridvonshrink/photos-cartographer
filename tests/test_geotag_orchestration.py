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

"""Geotag — orchestration + edge-branch coverage for photos-2-geotag: the run()/main CLI
error & exit paths (lock contention, unreadable/invalid config & handoff, blocker reports, the GPS
bad-coord abort), and a few helper edge branches (scans, malformed handoff records, timezone manual/
stale, _valid_iana). Complements the per-stage suites. From conftest.py.
"""
import json
import os
import sys
from datetime import datetime, timezone

import pytest

import photos_2_geotag as cal
import photos_utils as utils

MANAGED = ["0-sources", "1-strays", "2-missing-metadata", "3-redundant-jpgs",
           "4-videos-by-date", "5-photos-by-date", "6-photos-by-dest"]
CAM = "SONY|ILCE-6400|123"


def _init_ws(tmp_path):
    ws = tmp_path / "ws"; ws.mkdir()
    for d in MANAGED:
        (ws / d).mkdir()
    ctl = ws / ".photos-ingest"; ctl.mkdir()
    (ctl / "photos-00-workspace-guard").touch()
    return ws, ctl


def _run(monkeypatch, ws):
    monkeypatch.chdir(str(ws))
    monkeypatch.setattr(sys, "argv", ["photos-2-geotag", "plan"])
    try:
        cal.main(); return 0
    except SystemExit as e:
        return e.code if isinstance(e.code, int) else (0 if e.code is None else 1)


# --- main(): lock + config/handoff error paths ------------------------------

@pytest.mark.spec("geotag-lock-failfast-1")
def test_lock_contention_exits_1(tmp_path, monkeypatch, capsys):
    ws, ctl = _init_ws(tmp_path)
    (ctl / "photos-00-config.json").write_text(json.dumps({k: v for k, v in utils.CONFIG.items() if k != "jobs"}))
    (ctl / "photos-11-handoff.json").write_text(json.dumps({"files": []}))
    held = utils.WorkspaceLock(str(ws))
    assert held.acquire()
    try:
        assert _run(monkeypatch, ws) == 1
        assert "locked" in capsys.readouterr().err
    finally:
        held.release()


def test_invalid_config_blocks(tmp_path, monkeypatch, capsys):
    ws, ctl = _init_ws(tmp_path)
    bad = {k: v for k, v in utils.CONFIG.items() if k != "jobs"}
    bad["gpx_interpolation_max_distance_meters"] = -5            # fails validate_config
    (ctl / "photos-00-config.json").write_text(json.dumps(bad))
    (ctl / "photos-11-handoff.json").write_text(json.dumps({"files": []}))
    assert _run(monkeypatch, ws) == 2
    assert "Invalid workspace config" in capsys.readouterr().err


def test_corrupt_json_config_blocks(tmp_path, monkeypatch, capsys):
    ws, ctl = _init_ws(tmp_path)
    (ctl / "photos-00-config.json").write_text("{not valid json")      # JSONDecodeError is a ValueError
    (ctl / "photos-11-handoff.json").write_text(json.dumps({"files": []}))
    assert _run(monkeypatch, ws) == 2
    assert "Invalid workspace config" in capsys.readouterr().err


def test_unreadable_config_blocks(tmp_path, monkeypatch, capsys):
    ws, ctl = _init_ws(tmp_path)
    (ctl / "photos-00-config.json").mkdir()                            # a dir -> open() raises (not ValueError)
    (ctl / "photos-11-handoff.json").write_text(json.dumps({"files": []}))
    assert _run(monkeypatch, ws) == 2
    assert "could not be read" in capsys.readouterr().err


def test_unreadable_handoff_blocks(tmp_path, monkeypatch, capsys):
    ws, ctl = _init_ws(tmp_path)
    (ctl / "photos-00-config.json").write_text(json.dumps({k: v for k, v in utils.CONFIG.items() if k != "jobs"}))
    (ctl / "photos-11-handoff.json").write_text("}{ broken")
    assert _run(monkeypatch, ws) == 2
    assert "handoff could not be read" in capsys.readouterr().err


# --- helper edge branches ----------------------------------------------------

def test_valid_iana_true_and_false():
    assert cal._valid_iana("Europe/Paris") is True
    assert cal._valid_iana("Nowhere/Nope") is False


def test_timezone_manual_valid_and_accept_without_proposal(tmp_path):
    ws, ctl = _init_ws(tmp_path)
    (ctl / "photos-11-handoff.json").write_text("{}")
    wf = cal.GeotagWorkflow(str(ws))
    # a valid manual override -> effective = the manual zone
    blk = []
    tz = wf._timezone_decision("d", {"user_decision": {"manual_iana_timezone": "Europe/Paris"}}, blk)
    assert tz["effective_iana_timezone"] == "Europe/Paris" and not blk
    # accept with no proposal available (no default_folder_timezone) -> stale, still needs input
    utils.CONFIG["camera_time_and_timezone_policy"]["default_folder_timezone"] = ""
    tz2 = wf._timezone_decision("d", {"user_decision": {"accept_proposed_timezone": True}}, blk)
    assert tz2["stale_user_decision"] is True and tz2["requires_user_input"] is True


def test_build_file_model_tolerates_malformed_records(tmp_path):
    ws, ctl = _init_ws(tmp_path)
    (ctl / "photos-11-handoff.json").write_text("{}")
    wf = cal.GeotagWorkflow(str(ws))
    wf.handoff = {"files": [
        {"relative_path": "6-photos-by-dest/T/a.jpg", "media_class": "image",
         "folder_class": "6-photos-by-dest", "content_hash": "{not json",      # bad content_hash
         "metadata_status": {"parsed_json": "{not json"}},                      # bad parsed_json
        {"relative_path": "6-photos-by-dest/T/b.jpg", "media_class": "image",
         "folder_class": "6-photos-by-dest"},                                   # no metadata_status at all
    ]}
    files = wf.build_file_model()
    assert len(files) == 2 and all(f["content_fingerprint"] is None for f in files)
    assert all(f["camera_group_key"] == "unknown" for f in files)


def test_scans_handle_missing_folder_and_dotfiles(tmp_path):
    ws, ctl = _init_ws(tmp_path)
    wf = cal.GeotagWorkflow(str(ws))
    # a dotfile is skipped by the media scan; a non-existent subfolder yields nothing
    (ws / "5-photos-by-date" / ".DS_Store").write_text("x")
    (ws / "5-photos-by-date" / "real.jpg").write_bytes(b"x")
    scanned = list(wf._scan_media("5-photos-by-date"))
    assert [r for r, _ in scanned] == ["5-photos-by-date/real.jpg"]
    assert list(wf._scan_media("0-sources")) == []                 # empty dir
    assert list(wf._scan_media("no-such-folder")) == []            # missing dir -> early return
    assert wf._scan_by_dest("no-such-folder") == ([], [])          # missing dir -> early return
    # _scan_by_dest: a dotfile is skipped, a non-photo is reported
    (ws / "6-photos-by-dest" / ".hidden").write_text("x")
    (ws / "6-photos-by-dest" / "note.txt").write_text("x")
    dev, nonphoto = wf._scan_by_dest("6-photos-by-dest")
    assert any(p.endswith("note.txt") for p, _ in nonphoto)
    assert all(not p.endswith(".hidden") for p, _ in nonphoto)


def _completable_ws(tmp_path):
    """A workspace whose photos-21 reaches `complete` after the timezone is accepted: a GPX-anchored
    camera (two consistent native-GPS frames -> auto-resolved offset) plus one no-GPS frame whose
    resolved time falls in a wide GPX gap, so it lands as a blocked GPS review item."""
    ws, ctl = _init_ws(tmp_path)
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

    def rec(rel, dto, *, gps=None):
        parsed = {"DateTimeOriginal": dto, "selected_source_naive_timestamp": dto,
                  "selected_source_timestamp_tag": "DateTimeOriginal", "camera_group_key": CAM,
                  "has_timestamp": True, "has_native_gps": bool(gps)}
        if gps:
            parsed.update({"GPSLatitude": gps[0], "GPSLongitude": gps[1]})
        p = ws / rel; p.parent.mkdir(parents=True, exist_ok=True); p.write_bytes(b"x")
        return {"relative_path": rel, "media_class": "image", "folder_class": "6-photos-by-dest",
                "size": 1, "mtime_ns": 1, "content_hash": json.dumps({"value": "fp" + rel, "status": "valid"}),
                "metadata_status": {"camera_group_key": CAM, "has_timestamp": True,
                                    "has_native_gps": bool(gps), "field_set_version": 1,
                                    "parsed_json": json.dumps(parsed)}}
    files = [rec("6-photos-by-dest/T/a.arw", "2024:07:03 14:00:00", gps=(50.0, 4.0)),
             rec("6-photos-by-dest/T/b.arw", "2024:07:03 15:00:00", gps=(51.0, 5.0)),
             rec("6-photos-by-dest/T/c.arw", "2024:07:03 14:30:00")]          # no GPS -> blocked
    (ctl / "photos-11-handoff.json").write_text(json.dumps({"files": files, "cache_fingerprint": "pcf"}))
    return ws, ctl


def _accept_tz(ctl):
    p = ctl / "photos-21-time-decisions.json"
    a = json.load(open(p))
    a["destinations"]["6-photos-by-dest/T"]["destination_timezone"]["user_decision"]["accept_proposed_timezone"] = True
    p.write_text(json.dumps(a))


def test_complete_run_writes_photos22_then_bad_coord_aborts(tmp_path, monkeypatch, capsys):
    ws, ctl = _completable_ws(tmp_path)
    # The timezone auto-resolves (config default, inherited down the nested geography) and the GPX
    # anchor auto-resolves the offset, so a single run reaches status=complete and writes photos-23.
    assert _run(monkeypatch, ws) == 0
    out = capsys.readouterr().out
    assert "Wrote photos-23-gps-decisions.json" in out
    gps = json.load(open(ctl / "photos-23-gps-decisions.json"))
    assert gps["destinations"]["6-photos-by-dest/T"]["gps_decisions"]["summary"]["blocked"] == 1

    # inject a bad manual coord into the blocked file's review item -> run 3 loads the prior
    # photos-22, build_gps_decisions reports a blocker, and main aborts with exit 2 (artifact kept).
    ud = gps["destinations"]["6-photos-by-dest/T"]["gps_decisions"]["review_items"][0]["user_decision"]
    ud["manual_lat"], ud["manual_lon"] = 999, 0                    # out-of-range coord
    (ctl / "photos-23-gps-decisions.json").write_text(json.dumps(gps))
    before = (ctl / "photos-23-gps-decisions.json").read_bytes()
    assert _run(monkeypatch, ws) == 2
    assert "out of range" in capsys.readouterr().err
    assert (ctl / "photos-23-gps-decisions.json").read_bytes() == before     # left unchanged


def test_complete_run_tolerates_corrupt_prior_gps_artifact(tmp_path, monkeypatch):
    ws, ctl = _completable_ws(tmp_path)
    _run(monkeypatch, ws); _accept_tz(ctl); _run(monkeypatch, ws)             # produce both artifacts
    (ctl / "photos-23-gps-decisions.json").write_text("{corrupt")            # corrupt only photos-22
    assert _run(monkeypatch, ws) == 0                                         # prior ignored, regenerated
    assert json.load(open(ctl / "photos-23-gps-decisions.json"))["artifact_type"] == "gps_decisions"


def test_corrupt_prior_time_decisions_tolerated(tmp_path, monkeypatch):
    ws, ctl = _completable_ws(tmp_path)
    _run(monkeypatch, ws)                                                     # writes photos-21
    (ctl / "photos-21-time-decisions.json").write_text("{corrupt")           # corrupt prior
    assert _run(monkeypatch, ws) == 0                                         # prior-load guard -> regenerated
    assert json.load(open(ctl / "photos-21-time-decisions.json"))["artifact_type"] == "time_decisions"


def test_recognize_camera_groups_records_timestamps(tmp_path):
    ws, ctl = _init_ws(tmp_path)
    wf = cal.GeotagWorkflow(str(ws))
    utils.CONFIG["camera_time_and_timezone_policy"]["device_groups"] = {"fixed_clock_cameras": [CAM], "phones": []}
    files = [{"camera_group_key": CAM, "destination": "6-photos-by-dest/T", "has_native_gps": False,
              "has_timestamp": True, "source_naive_time": "2024:07:03 14:00:00", "camera_identity": {}},
             {"camera_group_key": CAM, "destination": "6-photos-by-dest/T", "has_native_gps": False,
              "has_timestamp": False, "source_naive_time": None, "camera_identity": {}},   # missing timestamp
             {"camera_group_key": CAM, "destination": "6-photos-by-dest/T", "has_native_gps": False,
              "has_timestamp": True, "source_naive_time": None, "camera_identity": {}}]     # timestamp flag, no value
    groups, _ = wf.recognize_camera_groups(files)
    assert groups[CAM]["earliest_source_time"] == "2024:07:03 14:00:00"
    assert groups[CAM]["latest_source_time"] == "2024:07:03 14:00:00"
    assert groups[CAM]["missing_timestamp"] == 1


@pytest.mark.spec("geotag-sealed-newdump-warn-1")
def test_sealed_workspace_with_dump_warns_and_blocks(tmp_path, monkeypatch, capsys):
    ws, ctl = _init_ws(tmp_path)
    (ctl / "photos-00-config.json").write_text(json.dumps({k: v for k, v in utils.CONFIG.items() if k != "jobs"}))
    (ctl / "photos-11-handoff.json").write_text(json.dumps({"files": []}))
    open(utils.sealed_marker_path(str(ws)), "w").close()           # seal it
    (ws / "loose.jpg").write_bytes(b"x")                           # a new dump at the root
    assert _run(monkeypatch, ws) == 2                              # sealed -> hard stop
    err = capsys.readouterr().err
    assert "SEALED" in err and "likely new dump" in err           # the warning loop printed
    # a sealed but otherwise-clean workspace blocks WITHOUT the dump warning
    os.remove(ws / "loose.jpg")
    wf = cal.GeotagWorkflow(str(ws))
    blk, warn, _ = wf.preflight()
    assert any("SEALED" in b for b in blk) and not warn


@pytest.mark.spec("geotag-gpx-after-recognition-1")
def test_unknown_group_aborts_before_gpx_ingest(tmp_path, monkeypatch):
    # In-memory camera-group recognition runs BEFORE disk-heavy GPX ingestion, so an unknown-group
    # abort costs no GPX I/O (the next run re-ingests GPX only once recognition passes).
    ws, ctl = _completable_ws(tmp_path)
    called = []
    monkeypatch.setattr(cal.GeotagWorkflow, "recognize_camera_groups",
                        lambda self, files: ({}, ["SONY|ILCE-7|unclassified"]))
    monkeypatch.setattr(cal.GeotagWorkflow, "load_gpx",
                        lambda self: called.append(1))
    assert _run(monkeypatch, ws) == 2          # unknown group -> abort
    assert called == []                        # GPX ingest never reached


@pytest.mark.spec("geotag-unknown-group-snippets-1")
def test_unknown_group_template_is_valid_full_json(tmp_path, monkeypatch, capsys):
    # The cut/paste template must be VALID JSON (no trailing comma -> the ",]" reader-rejection bug)
    # and the COMPLETE final list: each array carries the operator's known groups plus the new one.
    import copy
    ws, ctl = _completable_ws(tmp_path)                       # config: fixed_clock_cameras=[CAM]
    NEW = "NIKON|D750|abc123"
    h = json.load(open(ctl / "photos-11-handoff.json"))
    extra = copy.deepcopy(h["files"][0])
    extra["relative_path"] = "6-photos-by-dest/T/z.nef"
    extra["metadata_status"]["camera_group_key"] = NEW
    parsed = json.loads(extra["metadata_status"]["parsed_json"]); parsed["camera_group_key"] = NEW
    extra["metadata_status"]["parsed_json"] = json.dumps(parsed)
    (ws / "6-photos-by-dest/T/z.nef").write_bytes(b"x")
    h["files"].append(extra)
    (ctl / "photos-11-handoff.json").write_text(json.dumps(h))

    assert _run(monkeypatch, ws) == 2
    err = capsys.readouterr().err
    block = err[err.index('  "phones":'):err.index("\n\nNo geotag")]
    tmpl = json.loads("{" + block + "}")                     # parses iff no trailing comma
    assert NEW in tmpl["phones"]                             # new group offered in both arrays
    assert NEW in tmpl["fixed_clock_cameras"]
    assert CAM in tmpl["fixed_clock_cameras"]                # known group preserved (full list)
