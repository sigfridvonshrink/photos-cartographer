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

"""Phase 7 (geotag) — Stage 11 finalize + archive (§31 / shared §13): the photos-25
transformation log (prep carried forward + geotag steps), the DB snapshot, and the manifest.
Non-destructive. exiftool-write + fingerprint mocked. From conftest.py.
"""
import json
import os
import sqlite3
import sys

import pytest

import photos_2_geotag as cal
import photos_utils as utils

CAM = "SONY|ILCE-6400|123"
BYDEST = "6-photos-by-dest"
MANAGED = ["0-sources", "1-strays", "2-missing-metadata", "3-redundant-jpgs",
           "4-videos-by-date", "5-photos-by-date", "6-photos-by-dest"]


# --- shared write_db_snapshot helper ----------------------------------------

def test_write_db_snapshot_is_a_valid_copy(tmp_path):
    src = tmp_path / "live.db"
    conn = sqlite3.connect(str(src))
    conn.execute("CREATE TABLE t (k TEXT)"); conn.execute("INSERT INTO t VALUES ('v')"); conn.commit()
    dest = tmp_path / "snap.db"
    utils.write_db_snapshot(conn, str(dest))
    conn.close()
    assert dest.exists() and not list(tmp_path.glob(".tmp-snapshot-*"))   # atomic: temp cleaned
    snap = sqlite3.connect(str(dest))
    assert snap.execute("SELECT k FROM t").fetchone() == ("v",)          # consistent copy
    snap.close()


# --- build_complete_log -----------------------------------------------------

def _file(rel, fp, *, native=False, group=CAM):
    return {"relative_path": rel, "content_fingerprint": fp, "destination": f"{BYDEST}/T",
            "camera_group_key": group, "has_native_gps": native}


def test_complete_log_superset_and_geotag_steps():
    prep = {"fpA": {"content_fingerprint": "fpA", "journey": [{"phase": "prep", "action": "organized"}]}}
    files = [_file(f"{BYDEST}/T/a.arw", "fpA", native=True)]
    rows = [{"relative_path": f"{BYDEST}/T/a.arw", "resolved_utc": "2024-07-03T12:00:00Z",
             "utc_offset_used": -7200, "time_rule_used": "camera_group_offset"}]
    ta = {"destinations": {f"{BYDEST}/T": {"destination_timezone": {"effective_iana_timezone": "Europe/Brussels"}}}}
    plan = {"destinations": {f"{BYDEST}/T": {"operations": [
        {"type": "rename_no_clobber", "relative_path": f"{BYDEST}/T/a.arw", "to": "2024-07-03--14-00-00.arw"}]}}}
    photos = cal.build_complete_log(prep, files, rows, ta, plan, [])
    actions = [s["action"] for s in photos["fpA"]["journey"]]
    assert actions[0] == "organized"                                     # prep step preserved (superset)
    assert actions[1:] == ["clock_offset_applied", "resolved_utc", "timezone_resolved",
                           "gps_preserved", "final_rename"]
    off = photos["fpA"]["journey"][1]
    assert off["offset_seconds"] == -7200 and "camera_group_time_decisions" in off["because"]


def test_complete_log_skips_unfingerprinted_and_offsetless():
    files = [_file(f"{BYDEST}/T/a.arw", None, native=True),          # no fingerprint -> skipped
             _file(f"{BYDEST}/T/b.arw", "fpB")]
    rows = [{"relative_path": f"{BYDEST}/T/b.arw", "resolved_utc": "2024-07-03T12:00:00Z",
             "time_rule_used": "camera_group_offset", "utc_offset_used": None}]   # offset None -> no step
    photos = cal.build_complete_log({}, files, rows, {}, {"destinations": {}}, [])
    assert None not in photos and "fpB" in photos
    assert [s["action"] for s in photos["fpB"]["journey"]] == ["resolved_utc"]   # offset skipped


def test_complete_log_gps_written_and_reverted():
    files = [_file(f"{BYDEST}/T/m.jpg", "fpM"), _file(f"{BYDEST}/T/r.jpg", "fpR")]
    rows = [{"relative_path": f"{BYDEST}/T/m.jpg", "resolved_utc": "2024-07-03T12:00:00Z"},
            {"relative_path": f"{BYDEST}/T/r.jpg", "resolved_utc": "2024-07-03T12:00:00Z"}]
    plan = {"destinations": {f"{BYDEST}/T": {"operations": [
        {"type": "metadata_gps_write", "relative_path": f"{BYDEST}/T/m.jpg", "gps_origin": "apply_manual",
         "writes": {"GPSLatitude": 48.85, "GPSLongitude": 2.35}},
        {"type": "gps_marker_write", "relative_path": f"{BYDEST}/T/m.jpg", "writes": {"GPSProcessingMethod": "manual_fallback"}},
        {"type": "revert_manual_gps", "relative_path": f"{BYDEST}/T/r.jpg", "writes": {"GPSLatitude": ""},
         "pre_state": {"present": False}}]}}}
    photos = cal.build_complete_log({}, files, rows, {}, plan, [{"content_fingerprint": "fpM", "pre_state": {"present": False}}])
    m = next(s for s in photos["fpM"]["journey"] if s["action"] == "gps_written")
    assert m["lat"] == 48.85 and m["origin"] == "apply_manual" and m["gps_processing_method"] == "manual_fallback"
    assert m["pre_state"] == {"present": False}                          # manual apply records pre-state
    r = next(s for s in photos["fpR"]["journey"] if s["action"] == "gps_reverted")
    assert r["pre_state"] == {"present": False}                          # revert records the pinned pre-state
    # a GPS write with no marker op -> gps_processing_method is None (not an error)
    files2 = [_file(f"{BYDEST}/T/n.jpg", "fpN")]
    plan2 = {"destinations": {f"{BYDEST}/T": {"operations": [
        {"type": "metadata_gps_write", "relative_path": f"{BYDEST}/T/n.jpg", "gps_origin": "recompute_automated",
         "writes": {"GPSLatitude": 1, "GPSLongitude": 2}}]}}}
    photos2 = cal.build_complete_log({}, files2, [], {}, plan2, [])
    assert next(s for s in photos2["fpN"]["journey"] if s["action"] == "gps_written")["gps_processing_method"] is None


# --- finalize: readiness + end-to-end ---------------------------------------

def _ready_ws(tmp_path, monkeypatch):
    ws = tmp_path / "ws"; ws.mkdir()
    for d in MANAGED:
        (ws / d).mkdir()
    ctl = ws / ".photos-ingest"; ctl.mkdir(); (ctl / "photos-00-workspace-guard").touch()
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
        default_folder_timezone="Europe/Brussels", multi_anchor_auto_apply=True,
        write_corrected_filename_times=False)
    (ctl / "photos-00-config.json").write_text(json.dumps(cfg))
    # a prep log to carry forward
    (ctl / "photos-15-prep-log.json").write_text(json.dumps({"schema_version": 1, "tool": "photos-1-prep",
        "photos": {"fp-" + f"{BYDEST}/T/a.arw": {"content_fingerprint": "fp-" + f"{BYDEST}/T/a.arw",
                                                 "journey": [{"phase": "prep", "action": "organized"}]}}}))
    (ctl / "photos-15-prep-ingest.db").write_bytes(b"")   # presence; bundled if present

    def rec(rel, dto, gps):
        parsed = {"DateTimeOriginal": dto, "selected_source_naive_timestamp": dto,
                  "selected_source_timestamp_tag": "DateTimeOriginal", "camera_group_key": CAM,
                  "has_timestamp": True, "has_native_gps": True, "GPSLatitude": gps[0], "GPSLongitude": gps[1]}
        p = ws / rel; p.parent.mkdir(parents=True, exist_ok=True); p.write_bytes(b"img-" + rel.encode())
        st = p.stat()
        return {"relative_path": rel, "media_class": "image", "folder_class": "6-photos-by-dest",
                "size": st.st_size, "mtime_ns": st.st_mtime_ns,
                "content_hash": json.dumps({"value": "fp-" + rel, "status": "valid"}),
                "metadata_status": {"camera_group_key": CAM, "has_timestamp": True, "has_native_gps": True,
                                    "field_set_version": 1, "parsed_json": json.dumps(parsed)}}
    files = [rec(f"{BYDEST}/T/a.arw", "2024:07:03 14:00:00", (50.0, 4.0)),
             rec(f"{BYDEST}/T/b.arw", "2024:07:03 15:00:00", (51.0, 5.0))]
    (ctl / "photos-11-handoff.json").write_text(json.dumps({"files": files, "cache_fingerprint": "pcf"}))

    monkeypatch.setattr(cal.GeotagWorkflow, "_exiftool_write", lambda self, p, t: True)
    monkeypatch.setattr(cal.ContentHasher, "fingerprint_image",
                        staticmethod(lambda p: {"value": "fp-" + os.path.relpath(p, str(ws))}))
    return ws, ctl


def _run(monkeypatch, ws, cmd):
    monkeypatch.chdir(str(ws))
    monkeypatch.setattr(sys, "argv", ["photos-2-geotag", cmd])
    try:
        cal.main(); return 0
    except SystemExit as e:
        return e.code if isinstance(e.code, int) else (0 if e.code is None else 1)


def _to_executed(monkeypatch, ws, ctl):
    _run(monkeypatch, ws, "plan")
    a = json.load(open(ctl / "photos-21-time-decisions.json"))
    a["destinations"][f"{BYDEST}/T"]["destination_timezone"]["user_decision"]["accept_proposed_timezone"] = True
    (ctl / "photos-21-time-decisions.json").write_text(json.dumps(a))
    _run(monkeypatch, ws, "plan")
    _run(monkeypatch, ws, "execute")


def test_finalize_refuses_before_execute(tmp_path, monkeypatch):
    ws, ctl = _ready_ws(tmp_path, monkeypatch)
    _run(monkeypatch, ws, "plan")                                         # only photos-21 yet
    assert _run(monkeypatch, ws, "finalize") == 2
    assert not (ctl / "photos-26-complete-log.json").exists()


def test_finalize_refuses_partial_execution(tmp_path, monkeypatch):
    ws, ctl = _ready_ws(tmp_path, monkeypatch)
    _to_executed(monkeypatch, ws, ctl)
    s = json.load(open(ctl / "photos-25-execution-summary.json")); s["status"] = "partial"
    (ctl / "photos-25-execution-summary.json").write_text(json.dumps(s))
    assert _run(monkeypatch, ws, "finalize") == 2
    assert not (ctl / "photos-26-complete-log.json").exists()


def test_finalize_refuses_plan_id_mismatch(tmp_path, monkeypatch):
    ws, ctl = _ready_ws(tmp_path, monkeypatch)
    _to_executed(monkeypatch, ws, ctl)
    s = json.load(open(ctl / "photos-25-execution-summary.json")); s["plan_id"] = "stale"
    (ctl / "photos-25-execution-summary.json").write_text(json.dumps(s))
    assert _run(monkeypatch, ws, "finalize") == 2


def test_finalize_assembles_package_and_is_nondestructive(tmp_path, monkeypatch):
    ws, ctl = _ready_ws(tmp_path, monkeypatch)
    _to_executed(monkeypatch, ws, ctl)
    before = {n: (ctl / n).read_bytes() for n in
              ("photos-21-time-decisions.json", "photos-23-gps-decisions.json",
               "photos-24-executable-plan.json", "photos-25-execution-summary.json",
               "photos-15-prep-log.json")}
    assert _run(monkeypatch, ws, "finalize") == 0
    # the three package files appear
    assert (ctl / "photos-26-complete-log.json").exists()
    assert (ctl / "photos-26-geotag-ingest.db").exists()
    manifest = json.load(open(ctl / "photos-26-archive-manifest.json"))
    # non-destructive: upstream artifacts byte-unchanged
    after = {n: (ctl / n).read_bytes() for n in before}
    assert after == before
    # complete-log is a superset: prep photo preserved + geotag steps appended
    log = json.load(open(ctl / "photos-26-complete-log.json"))
    j = log["photos"]["fp-" + f"{BYDEST}/T/a.arw"]["journey"]
    assert j[0]["action"] == "organized" and any(s["phase"] == "geotag" for s in j)
    # manifest: identity + ids + every present item with a correct sha256
    assert manifest["plan_id"] == json.load(open(ctl / "photos-24-executable-plan.json"))["plan_id"]
    assert manifest["execution_id"] and manifest["workspace"] == "ws"
    for name, rec in manifest["contents"].items():
        assert rec["sha256"] == utils.sha256_file(str(ctl / name)), name
    assert "photos-26-complete-log.json" in manifest["contents"] and "photos-00-ingest.db" in manifest["contents"]


def test_finalize_refuses_without_summary(tmp_path, monkeypatch):
    ws, ctl = _ready_ws(tmp_path, monkeypatch)
    _run(monkeypatch, ws, "plan")
    a = json.load(open(ctl / "photos-21-time-decisions.json"))
    a["destinations"][f"{BYDEST}/T"]["destination_timezone"]["user_decision"]["accept_proposed_timezone"] = True
    (ctl / "photos-21-time-decisions.json").write_text(json.dumps(a))
    _run(monkeypatch, ws, "plan")                                         # photos-23 ready, NOT executed
    assert (ctl / "photos-24-executable-plan.json").exists()
    assert _run(monkeypatch, ws, "finalize") == 2                        # no photos-24 yet
    assert not (ctl / "photos-26-complete-log.json").exists()


def test_finalize_refuses_unready_plan(tmp_path, monkeypatch):
    ws, ctl = _ready_ws(tmp_path, monkeypatch)
    _to_executed(monkeypatch, ws, ctl)
    p = json.load(open(ctl / "photos-24-executable-plan.json")); p["status"] = "blocked"
    (ctl / "photos-24-executable-plan.json").write_text(json.dumps(p))
    assert _run(monkeypatch, ws, "finalize") == 2                        # plan not 'ready'


def test_finalize_sealed_workspace_blocks(tmp_path, monkeypatch):
    ws, ctl = _ready_ws(tmp_path, monkeypatch)
    _to_executed(monkeypatch, ws, ctl)
    open(utils.sealed_marker_path(str(ws)), "w").close()
    (ws / "loose.jpg").write_bytes(b"x")                                 # a dump -> the warning path
    assert _run(monkeypatch, ws, "finalize") == 2                        # sealed -> preflight blocks


def test_finalize_tolerates_corrupt_prep_log(tmp_path, monkeypatch):
    ws, ctl = _ready_ws(tmp_path, monkeypatch)
    _to_executed(monkeypatch, ws, ctl)
    (ctl / "photos-15-prep-log.json").write_text("{corrupt")             # unreadable prior -> ignored
    assert _run(monkeypatch, ws, "finalize") == 0
    assert (ctl / "photos-26-complete-log.json").exists()


def test_finalize_is_idempotent(tmp_path, monkeypatch):
    ws, ctl = _ready_ws(tmp_path, monkeypatch)
    _to_executed(monkeypatch, ws, ctl)
    assert _run(monkeypatch, ws, "finalize") == 0
    log1 = (ctl / "photos-26-complete-log.json").read_bytes()
    prep1 = (ctl / "photos-15-prep-log.json").read_bytes()
    assert _run(monkeypatch, ws, "finalize") == 0
    assert (ctl / "photos-26-complete-log.json").read_bytes() == log1     # deterministic
    assert (ctl / "photos-15-prep-log.json").read_bytes() == prep1        # prep untouched
