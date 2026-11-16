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

"""Phase 7 (geotag) — Stage 11 finalize + archive (BLD-archive_manifest): the photos-26
complete log (prep carried forward + geotag steps), the DB snapshot, and the manifest.
Non-destructive. exiftool-write + fingerprint mocked. From conftest.py.
"""
import hashlib
import json
from _handoff import recorded
from _zone import answer_root_zone, with_root_zone
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

@pytest.mark.spec("RUL-database_image_whole", "RUL-images_archived", test="TST-geotag_finalize-write_db_snapshot_is_a_valid_copy")
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


@pytest.mark.spec("RUL-record_whole_each_phase", "BLD-history_kept", "RUL-log_cites_decisions", test="TST-geotag_finalize-complete_log_superset_and_geotag_steps")
def test_complete_log_superset_and_geotag_steps():
    prep = {"fpA": {"content_fingerprint": "fpA", "journey": [{"phase": "prep", "action": "organized"}]}}
    files = [_file(f"{BYDEST}/T/a.arw", "fpA", native=True)]
    rows = [{"relative_path": f"{BYDEST}/T/a.arw", "resolved_utc": "2024-07-03T12:00:00Z",
             "utc_offset_used": -7200, "time_rule_used": "camera_group_offset"}]
    ta = {"destinations": {f"{BYDEST}/T": {"destination_timezone": {"effective_iana_timezone": "Europe/Brussels"}}}}
    plan = {"destinations": {f"{BYDEST}/T": {"operations": [
        {"type": "rename_no_clobber", "relative_path": f"{BYDEST}/T/a.arw", "to": "2024-07-03--14-00-00.arw"}]}}}
    photos = cal.build_complete_log(prep, files, rows, ta, plan)
    actions = [s["action"] for s in photos["fpA"]["journey"]]
    assert actions[0] == "organized"                                     # prep step preserved (superset)
    assert photos["fpA"]["geotag_path"] == f"{BYDEST}/T/2024-07-03--14-00-00.arw"   # the name geotag gave
    assert actions[1:] == ["clock_offset_applied", "resolved_utc", "timezone_resolved",
                           "gps_preserved", "final_rename"]
    off = photos["fpA"]["journey"][1]
    assert off["offset_seconds"] == -7200 and "camera_group_time_decisions" in off["because"]


def test_complete_log_skips_unfingerprinted_and_offsetless():
    files = [_file(f"{BYDEST}/T/a.arw", None, native=True),          # no fingerprint -> skipped
             _file(f"{BYDEST}/T/b.arw", "fpB")]
    rows = [{"relative_path": f"{BYDEST}/T/b.arw", "resolved_utc": "2024-07-03T12:00:00Z",
             "time_rule_used": "camera_group_offset", "utc_offset_used": None}]   # offset None -> no step
    photos = cal.build_complete_log({}, files, rows, {}, {"destinations": {}})
    assert None not in photos and "fpB" in photos
    assert [s["action"] for s in photos["fpB"]["journey"]] == ["resolved_utc"]   # offset skipped


@pytest.mark.spec("RUL-log_records_gps_reverts", test="TST-geotag_finalize-complete_log_gps_written")
def test_complete_log_gps_written():
    files = [_file(f"{BYDEST}/T/m.jpg", "fpM")]
    rows = [{"relative_path": f"{BYDEST}/T/m.jpg", "resolved_utc": "2024-07-03T12:00:00Z"}]
    plan = {"destinations": {f"{BYDEST}/T": {"operations": [
        {"type": "metadata_gps_write", "relative_path": f"{BYDEST}/T/m.jpg", "gps_origin": "apply_manual",
         "writes": {"GPSLatitude": 48.85, "GPSLongitude": 2.35}, "pre_state": {"present": False}},
        {"type": "gps_marker_write", "relative_path": f"{BYDEST}/T/m.jpg", "writes": {"GPSProcessingMethod": "manual_fallback"}}]}}}
    photos = cal.build_complete_log({}, files, rows, {}, plan)
    m = next(s for s in photos["fpM"]["journey"] if s["action"] == "gps_written")
    assert m["lat"] == 48.85 and m["origin"] == "apply_manual" and m["gps_processing_method"] == "manual_fallback"
    assert m["pre_state"] == {"present": False}                          # manual apply records what it replaced
    # a GPS write with no marker op -> gps_processing_method is None (not an error)
    files2 = [_file(f"{BYDEST}/T/n.jpg", "fpN")]
    plan2 = {"destinations": {f"{BYDEST}/T": {"operations": [
        {"type": "metadata_gps_write", "relative_path": f"{BYDEST}/T/n.jpg", "gps_origin": "recompute_automated",
         "writes": {"GPSLatitude": 1, "GPSLongitude": 2}}]}}}
    photos2 = cal.build_complete_log({}, files2, [], {}, plan2)
    assert next(s for s in photos2["fpN"]["journey"] if s["action"] == "gps_written")["gps_processing_method"] is None


@pytest.mark.spec("RUL-log_records_time_replaced", "RUL-log_records_other_times_replaced", "BLD-geotag_log_steps",
                  test="TST-geotag_finalize-a_time_written_is_logged_with_what_it_replaced")
def test_a_time_written_is_logged_with_what_it_replaced_and_how_it_was_found():
    """Two phone photos written alike: one read by the offset its phone recorded, one by assuming the
    destination's zone. The log tells them apart, and says what each held before."""
    def op(rel, rule, held_off):
        f = {"relative_path": rel, "raw_times": {"DateTimeOriginal": "2024:07:03 19:00:00",
                                                 **({"OffsetTimeOriginal": held_off} if held_off else {})}}
        writes = {"DateTimeOriginal": "2024:07:03 12:00:00", "OffsetTimeOriginal": "+02:00"}
        if held_off:                              # another time field it holds, rewritten with it
            f["other_times"] = {"IPTC:TimeCreated": "19:00:00" + held_off}
            writes["IPTC:TimeCreated"] = "12:00:00+02:00"
        return {"type": "metadata_time_write", "relative_path": rel, "operation_id": "t-" + rel,
                "writes": writes,
                "pre_state": cal.held_time_pre_state(f, writes),
                "provenance": {"time_rule_used": rule, "source_time_provenance": "EXIF:DateTimeOriginal"}}
    a, b = f"{BYDEST}/T/a.jpg", f"{BYDEST}/T/b.jpg"
    plan = {"plan_id": "p1", "destinations": {f"{BYDEST}/T": {"operations": [
        op(a, "smartphone_native_offset", "+09:00"), op(b, "destination_timezone", None)]}}}
    photos = cal.build_complete_log({}, [_file(a, "fpA"), _file(b, "fpB")], [], {}, plan)
    wa = next(s for s in photos["fpA"]["journey"] if s["action"] == "time_written")
    wb = next(s for s in photos["fpB"]["journey"] if s["action"] == "time_written")
    assert wa["pre_state"] == {"DateTimeOriginal": "2024:07:03 19:00:00", "OffsetTimeOriginal": "+09:00",
                               "IPTC:TimeCreated": "19:00:00+09:00"}          # every value the write replaced
    assert wb["pre_state"] == {"DateTimeOriginal": "2024:07:03 19:00:00", "OffsetTimeOriginal": None}
    assert (wa["rule"], wb["rule"]) == ("smartphone_native_offset", "destination_timezone")
    assert wa["read_from"] == "EXIF:DateTimeOriginal" and wa["run"] == "p1"
    assert wa["writes"] == {"DateTimeOriginal": "2024:07:03 12:00:00", "OffsetTimeOriginal": "+02:00",
                            "IPTC:TimeCreated": "12:00:00+02:00"}
    # a pass executed earlier logs its time write the same way
    plan["destinations"][f"{BYDEST}/T"]["operations"][0]["preconditions"] = {"content_fingerprint": "fpA"}
    later = cal.build_complete_log({}, [_file(a, "fpA")], [], {}, {"plan_id": "p2", "destinations": {}},
                                   earlier_passes=[(plan, {"t-" + a})])
    step = next(s for s in later["fpA"]["journey"] if s["action"] == "time_written")
    assert (step["rule"], step["run"]) == ("smartphone_native_offset", "p1")
    assert step["pre_state"]["OffsetTimeOriginal"] == "+09:00"


@pytest.mark.spec("RUL-log_records_gps_reverts", "RUL-record_whole_each_phase", test="TST-geotag_finalize-a_cleared_position_is_logged_with_what_it_held")
def test_a_cleared_position_is_logged_with_what_it_held():
    """A position geotag wrote and no longer places is cleared, and the log says so with the position
    the photo held; a manual position records the one it replaced."""
    files = [_file(f"{BYDEST}/T/c.jpg", "fpC"), _file(f"{BYDEST}/T/m.jpg", "fpM")]
    held = {"present": True, "GPSLatitude": 40.0, "GPSLongitude": 3.0, "GPSProcessingMethod": "manual_locked"}
    plan = {"destinations": {f"{BYDEST}/T": {"operations": [
        {"type": "gps_marker_write", "relative_path": f"{BYDEST}/T/c.jpg", "pre_state": held,
         "writes": {"GPSLatitude": "", "GPSLatitudeRef": "", "GPSLongitude": "", "GPSLongitudeRef": "",
                    "GPSProcessingMethod": "+carto-time"}},
        {"type": "metadata_gps_write", "relative_path": f"{BYDEST}/T/m.jpg", "gps_origin": "apply_manual",
         "writes": {"GPSLatitude": 48.85, "GPSLongitude": 2.35}, "pre_state": {"present": False}}]}}}
    photos = cal.build_complete_log({}, files, [], {}, plan)
    c = [s for s in photos["fpC"]["journey"] if s["phase"] == "geotag"]
    assert c == [{"phase": "geotag", "action": "gps_cleared", "pre_state": held,
                  "gps_processing_method": "+carto-time"}]
    m = next(s for s in photos["fpM"]["journey"] if s["action"] == "gps_written")
    assert m["pre_state"] == {"present": False}
    held_file = dict(_file(f"{BYDEST}/T/x.jpg", "fpX"), native_gps={"lat": 40.0, "lon": 3.0},
                     processing_method="manual_locked")
    assert cal.held_pre_state(held_file) == held
    assert cal.held_pre_state(_file(f"{BYDEST}/T/y.jpg", "fpY")) == {"present": False}


@pytest.mark.spec("RUL-log_cites_decisions", "BLD-log_format", test="TST-geotag_finalize-each_step_names_its_exact_decision")
def test_each_step_names_its_exact_decision():
    """The offset names its exact cell — with its day when the camera's photos there span days — or
    the drift confirmation that replaced it; a manual position names the pin or the folder fallback."""
    row = {"camera_group": CAM, "source_naive_time": "2024:07:03 14:00:00"}
    cells = {f"{CAM}@2024-07-02": {}, f"{CAM}@2024-07-03": {}}
    assert cal.offset_decision_pointer(row, f"{BYDEST}/T", cells) == \
        f"photos-21 destinations.{BYDEST}/T.camera_group_time_decisions.{CAM}@2024-07-03"
    assert cal.offset_decision_pointer(dict(row, resolved_utc_provenance="gps_drift_validated"), f"{BYDEST}/T", {CAM: {}}) == \
        f"photos-22 destinations.{BYDEST}/T.drift_decisions.{CAM}"
    assert cal.manual_gps_pointer("manual_locked", f"{BYDEST}/T", f"{BYDEST}/T/m.jpg", None) == \
        f"photos-23 destinations.{BYDEST}/T.gps_decisions.review_items[m.jpg]"
    inherited = {"fallback_source": "inherited", "inherited_from": BYDEST}
    assert cal.manual_gps_pointer("manual_fallback", f"{BYDEST}/T", f"{BYDEST}/T/m.jpg", inherited) == \
        f"photos-23 destinations.{BYDEST}/T.folder_fallback (inherited from {BYDEST})"
    files = [_file(f"{BYDEST}/T/m.jpg", "fpM")]
    plan = {"destinations": {f"{BYDEST}/T": {"operations": [
        {"type": "metadata_gps_write", "relative_path": f"{BYDEST}/T/m.jpg", "gps_origin": "apply_manual",
         "writes": {"GPSLatitude": 48.85, "GPSLongitude": 2.35},
         "provenance": {"because": f"photos-23 destinations.{BYDEST}/T.folder_fallback"}}]}}}
    step = next(s for s in cal.build_complete_log({}, files, [], {}, plan)["fpM"]["journey"] if s["action"] == "gps_written")
    assert step["because"] == f"photos-23 destinations.{BYDEST}/T.folder_fallback"


@pytest.mark.spec("RUL-log_human_readable", test="TST-geotag_finalize-an_offset_is_described_in_words")
def test_an_offset_is_described_in_words():
    assert cal.describe_offset(-6900) == "camera clock 1 h 55 min ahead of UTC"
    assert cal.describe_offset(3612) == "camera clock 1 h 12 s behind UTC"
    assert cal.describe_offset(0) == "camera clock on UTC"
    files = [_file(f"{BYDEST}/T/a.arw", "fpA")]
    rows = [{"relative_path": f"{BYDEST}/T/a.arw", "utc_offset_used": -7200, "time_rule_used": "camera_group_offset"}]
    step = cal.build_complete_log({}, files, rows, {}, {"destinations": {}})["fpA"]["journey"][0]
    assert step["offset_seconds"] == -7200 and step["offset_description"] == "camera clock 2 h ahead of UTC"


# --- finalize: readiness + end-to-end ---------------------------------------

def _ready_ws(tmp_path, monkeypatch, *, folders=None):
    """A workspace as prep leaves it for geotag; `folders` (role -> name), if given, names its folders."""
    bydest = folders["photos_by_dest"] if folders else BYDEST
    ws = tmp_path / "ws"; ws.mkdir()
    for d in (folders.values() if folders else MANAGED):
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
        default_folder_timezone="Europe/Brussels", multi_anchor_auto_apply=True)
    if folders:
        cfg["folders"] = dict(folders)
    (ctl / "photos-00-config.json").write_text(json.dumps(cfg))
    answer_root_zone(ctl)                        # the zone answered once at the root (RUL-timezone_auto_resolves)
    if folders:                                  # ... at the root as these folders name it
        td = json.load(open(ctl / "photos-21-time-decisions.json"))
        td["destinations"] = {bydest: td["destinations"].pop(BYDEST)}
        (ctl / "photos-21-time-decisions.json").write_text(json.dumps(td))
    # a prep log to carry forward
    (ctl / "photos-15-prep-log.json").write_text(json.dumps({"schema_version": 1, "tool": "photos-1-prep",
        "photos": {"fp-" + f"{bydest}/T/a.arw": {"content_fingerprint": "fp-" + f"{bydest}/T/a.arw",
                                                 "journey": [{"phase": "prep", "action": "organized"}]}}}))
    (ctl / "photos-15-prep-ingest.db").write_bytes(b"")   # presence; bundled if present

    def rec(rel, dto, gps):
        parsed = {"DateTimeOriginal": dto, "selected_source_naive_timestamp": dto,
                  "selected_source_timestamp_tag": "DateTimeOriginal", "camera_group_key": CAM,
                  "has_timestamp": True, "has_native_gps": True, "GPSLatitude": gps[0], "GPSLongitude": gps[1]}
        p = ws / rel; p.parent.mkdir(parents=True, exist_ok=True); p.write_bytes(b"img-" + rel.encode())
        st = p.stat()
        return {"relative_path": rel, "media_class": "image", "folder_class": bydest,
                "size": st.st_size, "mtime_ns": st.st_mtime_ns,
                "content_hash": json.dumps({"value": "fp-" + rel, "status": "valid"}),
                "metadata_status": {"camera_group_key_version": utils.CAMERA_GROUP_KEY_VERSION,
                                    "camera_group_key": CAM, "has_timestamp": True, "has_native_gps": True,
                                    "field_set_version": utils.FIELD_SET_VERSION, "parsed_json": json.dumps(parsed)}}
    files = [rec(f"{bydest}/T/a.arw", "2024:07:03 14:00:00", (50.0, 4.0)),
             rec(f"{bydest}/T/b.arw", "2024:07:03 15:00:00", (51.0, 5.0))]
    (ctl / "photos-11-handoff.json").write_text(json.dumps({"filename_timestamp_format": utils.CONFIG["filename_timestamp_format"], "files": files, "cache_fingerprint": "pcf",
        "depends_on": {"prep_log": {"sha256": utils.sha256_file(str(ctl / "photos-15-prep-log.json"))},
                       "cache": {"image_engine_version": utils.get_imagemagick_version(), "fingerprint_algorithm_version": utils.FINGERPRINT_ALGORITHM_VERSION}}}))

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
    (ctl / "photos-21-time-decisions.json").write_text(json.dumps(a))
    _run(monkeypatch, ws, "plan")
    _run(monkeypatch, ws, "execute")


def test_finalize_refuses_before_execute(tmp_path, monkeypatch):
    ws, ctl = _ready_ws(tmp_path, monkeypatch)
    _run(monkeypatch, ws, "plan")                                         # only photos-21 yet
    assert _run(monkeypatch, ws, "finalize") == 2
    assert not (ctl / "photos-26-complete-log.json").exists()


@pytest.mark.spec("RUL-finalize_requires_success", test="TST-geotag_finalize-finalize_refuses_partial_execution")
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


@pytest.mark.spec("RUL-finalize_explicit", "RUL-finalize_non_destructive", "RUL-carry_forward_by_copy",
                  "RUL-package_contents", "RUL-package_self_describing", "RUL-package_lists_contents",
                  "RUL-database_archived",
                  test="TST-geotag_finalize-finalize_assembles_package_and_is_nondestructive")
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


@pytest.mark.spec("RUL-merge_refuses_changed_since_finalize", test="TST-geotag_finalize-finalize_records_each_photo_as_left")
def test_finalize_records_each_photo_as_left(tmp_path, monkeypatch):
    """Finalize records every by-dest photo as geotag left it — under its final, renamed path — by size
    and modification time, so merge can refuse one changed after."""
    ws, ctl = _ready_ws(tmp_path, monkeypatch)
    _to_executed(monkeypatch, ws, ctl)
    assert _run(monkeypatch, ws, "finalize") == 0
    media = json.load(open(ctl / "photos-26-finalized-media.json"))["media"]
    on_disk = sorted(os.path.relpath(os.path.join(r, n), str(ws))
                     for r, _d, fs in os.walk(ws / BYDEST) for n in fs)
    assert sorted(media) == on_disk and not any(p.endswith(("/a.arw", "/b.arw")) for p in media)  # final names
    for rel, rec in media.items():
        st = os.stat(ws / rel)
        assert rec == {"size": st.st_size, "mtime_ns": st.st_mtime_ns}, rel


@pytest.mark.spec("RUL-package_contents", "RUL-package_self_describing", "RUL-images_archived",
                  "RUL-config_archived", "RUL-package_lists_contents", "RUL-scratch_database_not_archived",
                  "RUL-database_archived",
                  test="TST-geotag_finalize-finalize_archives_the_whole_control_directory")
def test_finalize_archives_the_whole_control_directory(tmp_path, monkeypatch):
    """The package is the whole control directory but its transient files — the drift record and every
    journal among it — listed with their hashes in the manifest and archived, manifest included, into
    the control directory itself."""
    import hashlib
    import tarfile
    ws, ctl = _ready_ws(tmp_path, monkeypatch)
    _to_executed(monkeypatch, ws, ctl)
    assert (ctl / "photos-22-gps-drift-validation.json").exists()
    (ctl / "photos-00-plan-memo.db").write_bytes(b"scratch")
    (ctl / "photos-15-prep-ingest.db").write_bytes(b"prep's database image")
    (ctl / "photos-00-workspace-guard").write_text('{"initialized": true, "initialized_by_run": "prep-init-1"}')
    assert _run(monkeypatch, ws, "finalize") == 0
    manifest = json.load(open(ctl / "photos-26-archive-manifest.json"))
    assert manifest["workspace_id"] == "prep-init-1"              # the identity a renamed folder keeps
    listed = set(manifest["contents"])
    assert {"photos-22-gps-drift-validation.json", "photos-00-config.json", "photos-00-ingest.db"} <= listed
    assert {"photos-15-prep-ingest.db", "photos-26-geotag-ingest.db"} <= listed      # every database image
    assert any(n.startswith("journal-") for n in listed)
    assert not any(n.endswith(".lock") or n.startswith(".tmp-") for n in listed)
    assert "photos-00-plan-memo.db" not in listed and "photos-26-archive-manifest.json" not in listed
    with tarfile.open(ctl / "photos-26-archive.tar.gz") as tar:
        archived = {m.name: tar.extractfile(m).read() for m in tar.getmembers()}
    assert set(archived) == {rec["path"] for rec in manifest["contents"].values()} | {
        ".photos-ingest/photos-26-archive-manifest.json"}
    for rec in manifest["contents"].values():                      # the hashes describe what was archived
        assert hashlib.sha256(archived[rec["path"]]).hexdigest() == rec["sha256"], rec["path"]


@pytest.mark.spec("RUL-finalize_explicit")
def test_finalize_bundles_archive_but_performs_no_merge(tmp_path, monkeypatch):
    """RUL-finalize_non_destructive (anti): finalize assembles the archival package (photos-26 complete-log + DB +
    manifest) but NEVER merges into a library — it produces no merge artifacts and moves no media. Snapshot the
    by-dest frames, run finalize, assert the package appears, NO merge artifact (photos-31/photos-35)
    is written, and every by-dest media file is byte-unchanged (finalize moved nothing)."""
    ws, ctl = _ready_ws(tmp_path, monkeypatch)
    _to_executed(monkeypatch, ws, ctl)                                # renames applied by execute
    before = {}
    for dp, _dn, fns in os.walk(ws / BYDEST):
        for fn in fns:
            ap = os.path.join(dp, fn)
            before[os.path.relpath(ap, str(ws / BYDEST))] = open(ap, "rb").read()
    assert before, "expected media frames staged under by-dest"

    assert _run(monkeypatch, ws, "finalize") == 0
    # the archival package was assembled (geotag's own terminal artifact)
    assert (ctl / "photos-26-complete-log.json").exists()
    assert (ctl / "photos-26-archive-manifest.json").exists()
    # ...but NO merge artifacts of any kind were produced by finalize
    for n in ("photos-31-merge-summary.json", "photos-30-merge-plan.json",
              "photos-35-merge-log.json", "photos-35-merge-ingest.db",
              "photos-35-archive-manifest.json", "photos-00-sealed.json"):
        assert not (ctl / n).exists(), n
    assert not list(ctl.glob("photos-35-*"))
    # finalize is non-destructive on media: the by-dest frames are byte-for-byte unchanged
    after = {}
    for dp, _dn, fns in os.walk(ws / BYDEST):
        for fn in fns:
            ap = os.path.join(dp, fn)
            after[os.path.relpath(ap, str(ws / BYDEST))] = open(ap, "rb").read()
    assert after == before


def test_finalize_refuses_without_summary(tmp_path, monkeypatch):
    ws, ctl = _ready_ws(tmp_path, monkeypatch)
    _run(monkeypatch, ws, "plan")
    a = json.load(open(ctl / "photos-21-time-decisions.json"))
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


@pytest.mark.spec("RUL-unchecked_counts_as_changed", "BLD-finalize_checks_prep_log", test="TST-geotag_finalize-finalize_refuses_a_prep_log_the_handoff_does_not_vouch_for")
@pytest.mark.parametrize("damage", ["changed", "missing"])
def test_finalize_refuses_a_prep_log_the_handoff_does_not_vouch_for(tmp_path, monkeypatch, capsys, damage):
    """Finalize copies prep's log only as the handoff records it, by hash: a log changed since — or gone,
    which cannot be checked — stops finalize, nothing written, and sends the user back to prep."""
    ws, ctl = _ready_ws(tmp_path, monkeypatch)
    _to_executed(monkeypatch, ws, ctl)
    log = ctl / "photos-15-prep-log.json"
    if damage == "changed":
        log.write_text("{corrupt")
    else:
        log.unlink()
    capsys.readouterr()
    assert _run(monkeypatch, ws, "finalize") == 2
    assert "prep execute" in "".join(capsys.readouterr())
    assert not (ctl / "photos-26-complete-log.json").exists()


@pytest.mark.spec("RUL-image_untouched_by_other_phase",
                  test="TST-geotag_finalize-geotag_leaves_preps_database_image_as_it_was")
def test_geotag_leaves_preps_database_image_as_it_was(tmp_path, monkeypatch):
    """Geotag — plan, execute and finalize — writes its own image of the database and leaves prep's, byte
    for byte, as prep left it."""
    ws, ctl = _ready_ws(tmp_path, monkeypatch)
    image = ctl / "photos-15-prep-ingest.db"
    image.write_bytes(b"prep's image of the database")
    st = image.stat()
    _to_executed(monkeypatch, ws, ctl)
    assert _run(monkeypatch, ws, "finalize") == 0
    assert (ctl / "photos-26-geotag-ingest.db").read_bytes().startswith(b"SQLite format 3")   # its own: written
    assert image.read_bytes() == b"prep's image of the database"
    assert (image.stat().st_mtime_ns, image.stat().st_ino) == (st.st_mtime_ns, st.st_ino)     # never rewritten


@pytest.mark.spec("RUL-control_directory_fixed",
                  test="TST-geotag_finalize-geotag_keeps_its_records_in_the_one_control_directory")
def test_geotag_keeps_its_records_in_the_one_control_directory(tmp_path, monkeypatch):
    """Where geotag reads and writes its records does not follow the configuration: with the default folders, or
    with every folder renamed, geotag plans, executes and finalizes from the records prep left in `.photos-ingest/`
    and writes its own there, and nowhere else."""
    import copy
    renamed = {role: f"x-{name}" for role, name in copy.deepcopy(utils.DEFAULT_FOLDERS).items()}
    records = ("photos-21-time-decisions.json", "photos-22-gps-drift-validation.json", "photos-23-gps-decisions.json",
               "photos-24-executable-plan.json", "photos-25-execution-summary.json", "photos-26-complete-log.json",
               "photos-26-finalized-media.json", "photos-26-geotag-ingest.db", "photos-26-archive-manifest.json",
               "photos-26-archive.tar.gz", "photos-00-ingest.db")
    for name, folders in (("default", None), ("renamed", renamed)):
        (tmp_path / name).mkdir()
        ws, ctl = _ready_ws(tmp_path / name, monkeypatch, folders=folders)
        utils.CONFIG.clear(); utils.CONFIG.update(utils.default_config())   # a run of its own: nothing read yet
        _to_executed(monkeypatch, ws, ctl)
        assert json.load(open(ctl / "photos-25-execution-summary.json"))["status"] == "success", name
        assert _run(monkeypatch, ws, "finalize") == 0, name
        for rec in records:
            assert (ws / ".photos-ingest" / rec).is_file(), (name, rec)
        plan_id = json.load(open(ctl / "photos-24-executable-plan.json"))["plan_id"]
        assert (ws / ".photos-ingest" / f"journal-{plan_id}.json").is_file(), name
        assert sorted(os.listdir(ws)) == sorted([".photos-ingest", *(folders.values() if folders else MANAGED)]), name
        outside = [os.path.join(r, n) for r, _d, fs in os.walk(ws) if ".photos-ingest" not in r
                   for n in fs if not n.endswith(".arw")]
        assert outside == [], (name, outside)                       # no record anywhere among the media
        bydest = (folders or {}).get("photos_by_dest", BYDEST)
        assert sorted(os.listdir(ws / bydest / "T")) == ["2024-07-03--14-00-00.arw", "2024-07-03--15-00-00.arw"]


@pytest.mark.spec("RUL-image_untouched_by_other_phase",
                  test="TST-geotag_finalize-prep_after_finalize_leaves_geotags_database_image_as_it_was")
def test_prep_after_finalize_leaves_geotags_database_image_as_it_was(tmp_path, monkeypatch):
    """Prep may still run once geotag has finalized, the workspace not yet merged: every command of it — plan, dry
    run, execute, the quarantine's prune — leaves geotag's image of the database, byte for byte, as geotag left it,
    while prep's own image is written anew."""
    import photos_1_prep as prep
    ws, ctl = _ready_ws(tmp_path, monkeypatch)
    _to_executed(monkeypatch, ws, ctl)
    assert _run(monkeypatch, ws, "finalize") == 0
    image = ctl / "photos-26-geotag-ingest.db"
    made, st = image.read_bytes(), image.stat()
    assert made.startswith(b"SQLite format 3")

    def meta(folders, max_workers=4, progress_coordinator=None):    # the time geotag wrote, which names each photo
        stamp = lambda n: "{}:{}:{} {}:{}:{}".format(*n[:20].replace("--", "-").split("-"))
        return {os.path.join(r, n): {"DateTimeOriginal": stamp(n), "extraction_status": "extracted_ok"}
                for folder in folders for r, _d, fs in os.walk(folder) for n in fs if n.endswith(".arw")}, set()
    monkeypatch.setattr(utils.MetadataReader, "read_metadata_concurrently", meta)
    monkeypatch.setattr(utils.ContentHasher, "fingerprint_image", staticmethod(
        lambda p: {"status": "valid", "strategy": "image-content-hash-v2", "value": "fp-" + os.path.basename(p),
                   "engine_version": "t"}))
    (ws / "0-sources" / "note.txt").write_text("a stray, so prep has a sort to do")
    prep.WorkspaceCache(str(ws)).close()          # the cache prep keeps (this workspace was made without prep)

    def prep_run(*argv):
        monkeypatch.setattr(sys, "argv", ["photos-1-prep", *argv])
        try:
            prep.main(); return 0
        except SystemExit as e:
            return e.code if isinstance(e.code, int) else (0 if e.code is None else 1)
    prep_image = ctl / "photos-15-prep-ingest.db"
    prep_before = prep_image.read_bytes()
    for argv in (("plan",), ("dry-run",), ("execute",), ("prune-quarantine",), ("plan",)):
        assert prep_run(*argv) == 0, argv
        assert image.read_bytes() == made, argv
        assert (image.stat().st_mtime_ns, image.stat().st_ino) == (st.st_mtime_ns, st.st_ino), argv
    assert not (ws / "0-sources" / "note.txt").exists()                     # prep did run its sort
    assert prep_image.read_bytes() != prep_before and prep_image.read_bytes().startswith(b"SQLite format 3")


def test_finalize_is_idempotent(tmp_path, monkeypatch):
    ws, ctl = _ready_ws(tmp_path, monkeypatch)
    _to_executed(monkeypatch, ws, ctl)
    assert _run(monkeypatch, ws, "finalize") == 0
    log1 = (ctl / "photos-26-complete-log.json").read_bytes()
    prep1 = (ctl / "photos-15-prep-log.json").read_bytes()
    assert _run(monkeypatch, ws, "finalize") == 0
    assert (ctl / "photos-26-complete-log.json").read_bytes() == log1     # deterministic
    assert (ctl / "photos-15-prep-log.json").read_bytes() == prep1        # prep untouched


@pytest.mark.spec("RUL-image_never_working_data", test="TST-geotag_finalize-geotag_never_reads_a_database_image_back")
def test_geotag_never_reads_a_database_image_back(tmp_path, monkeypatch):
    """No database image is read back as working data: with prep's image, and then geotag's own, holding no
    database at all, geotag plans, executes and finalizes — and finalizes again to the same record — opening
    neither."""
    ws, ctl = _ready_ws(tmp_path, monkeypatch)
    images = ("photos-15-prep-ingest.db", "photos-26-geotag-ingest.db")
    (ctl / images[0]).write_bytes(b"not a database")
    opened, real_connect = [], sqlite3.connect
    def connect(database, *a, **k):
        opened.append(os.path.basename(str(database).split("?")[0]))
        return real_connect(database, *a, **k)
    monkeypatch.setattr(sqlite3, "connect", connect)
    _to_executed(monkeypatch, ws, ctl)
    assert json.load(open(ctl / "photos-25-execution-summary.json"))["status"] == "success"
    assert _run(monkeypatch, ws, "finalize") == 0
    record = {n: (ctl / n).read_bytes() for n in ("photos-26-complete-log.json", "photos-26-finalized-media.json")}
    (ctl / images[1]).write_bytes(b"not a database either")
    assert _run(monkeypatch, ws, "finalize") == 0
    assert {n: (ctl / n).read_bytes() for n in record} == record
    assert (ctl / images[1]).read_bytes().startswith(b"SQLite format 3")      # its own image, made again
    assert "photos-00-ingest.db" in opened and not set(images) & set(opened), opened


@pytest.mark.spec("RUL-log_step_names_run", test="TST-geotag_finalize-every_geotag_step_names_its_run")
def test_every_geotag_step_names_its_run(tmp_path, monkeypatch):
    """Every step geotag adds to a photo's log names the run that made it: the plan that was executed."""
    ws, ctl = _ready_ws(tmp_path, monkeypatch)
    _to_executed(monkeypatch, ws, ctl)
    assert _run(monkeypatch, ws, "finalize") == 0
    plan_id = json.loads((ctl / "photos-24-executable-plan.json").read_text())["plan_id"]
    steps = [s for e in json.loads((ctl / "photos-26-complete-log.json").read_text())["photos"].values()
             for s in e["journey"] if s.get("phase") == "geotag"]
    assert plan_id and steps and all(s.get("run") == plan_id for s in steps), steps


@pytest.mark.spec("RUL-finalize_reads_database", test="TST-geotag_finalize-finalize_only_reads_the_workspace_database")
def test_finalize_only_reads_the_workspace_database(tmp_path, monkeypatch):
    """Finalize reads the workspace's database — it images it — and writes nothing to it: once geotag has executed,
    the database is, byte for byte and row for row, what it was before finalize, and finalize leaves no journal of
    a write beside it; it has been read all the same, into finalize's own image of it."""
    ws, ctl = _ready_ws(tmp_path, monkeypatch)
    _to_executed(monkeypatch, ws, ctl)
    live = ctl / "photos-00-ingest.db"

    def rows():
        conn = sqlite3.connect(f"file:{live}?mode=ro", uri=True)
        try:
            return list(conn.iterdump())
        finally:
            conn.close()
    before, st, dumped = live.read_bytes(), live.stat(), rows()
    assert any(line.startswith('INSERT INTO "resolved_utc_cache"') for line in dumped)   # geotag's rows, to keep
    assert _run(monkeypatch, ws, "finalize") == 0
    assert live.read_bytes() == before
    assert (live.stat().st_mtime_ns, live.stat().st_ino) == (st.st_mtime_ns, st.st_ino)
    assert rows() == dumped
    assert not [n for n in os.listdir(ctl) if n.startswith("photos-00-ingest.db-")]   # no -journal / -wal left
    image = sqlite3.connect(str(ctl / "photos-26-geotag-ingest.db"))
    try:
        assert list(image.iterdump()) == dumped                         # read whole into its image
    finally:
        image.close()


@pytest.mark.spec("RUL-snapshot_optional", "RUL-filesystem_agnostic", test="TST-geotag_finalize-geotag_runs_whole_with_no_zfs")
def test_geotag_runs_whole_with_no_zfs(tmp_path, monkeypatch):
    """With snapshots off, as they are by default, geotag never reaches for a ZFS feature: on a machine with no
    `zfs` at all it plans, executes and finalizes."""
    import subprocess
    calls, real = [], subprocess.Popen
    def popen(args, *a, **k):
        argv = args.split() if isinstance(args, str) else list(args)
        if argv and os.path.basename(str(argv[0])) == "zfs":
            calls.append(argv)
            raise FileNotFoundError(2, "No such file or directory", "zfs")
        return real(args, *a, **k)
    monkeypatch.setattr(subprocess, "Popen", popen)
    ws, ctl = _ready_ws(tmp_path, monkeypatch)
    assert json.load(open(ctl / "photos-00-config.json"))["zfs"]["enabled"] is False
    _to_executed(monkeypatch, ws, ctl)
    assert json.load(open(ctl / "photos-25-execution-summary.json"))["status"] == "success"
    assert _run(monkeypatch, ws, "finalize") == 0
    assert (ctl / "photos-26-archive-manifest.json").exists() and calls == []


@pytest.mark.spec("RUL-finalize_requires_success", "BLD-finalize_preconditions",
                  "RUL-finalize_requires_plan_still_holds", "RUL-dependencies_validated_before_deriving",
                  test="TST-geotag_finalize-a_decision_changed_since_execution_stops_finalize")
def test_a_decision_changed_since_execution_stops_finalize(tmp_path, monkeypatch):
    # Executed, then a decision edited without planning again: the package would record a decision the photos
    # never received, so finalize writes nothing and asks for the plan and execute again.
    ws, ctl = _ready_ws(tmp_path, monkeypatch)
    _to_executed(monkeypatch, ws, ctl)
    p = ctl / "photos-23-gps-decisions.json"
    a = json.loads(p.read_text()); a["note"] = "edited after execute"; p.write_text(json.dumps(a))
    assert _run(monkeypatch, ws, "finalize") == 2
    assert not (ctl / "photos-26-complete-log.json").exists()



# --- what finalize packages is what execution left (RUL-finalize_checks_photos) -----------------------------

@pytest.mark.spec("RUL-finalize_checks_photos", "BLD-finalize_preconditions",
                  test="TST-geotag_finalize-a_photo_not_as_execution_left_it_stops_finalize")
@pytest.mark.parametrize("change", ["edited", "gone", "added"])
def test_a_photo_not_as_execution_left_it_stops_finalize(tmp_path, monkeypatch, capsys, change):
    """Between execute and finalize a photo is edited in another program, deleted, or a new one dropped in.
    Finalize records the photos as geotag's finished work, which merge then trusts: it refuses, naming the
    photo, rather than record the changed state as its own."""
    ws, ctl = _ready_ws(tmp_path, monkeypatch)
    _to_executed(monkeypatch, ws, ctl)
    assert json.load(open(ctl / "photos-25-execution-summary.json"))["status"] == "success"
    photos = sorted((ws / BYDEST / "T").iterdir())
    if change == "edited":
        photos[0].write_bytes(b"retagged by hand, another size")
    elif change == "gone":
        photos[0].unlink()
    else:
        (ws / BYDEST / "T" / "dropped-in.jpg").write_bytes(b"new")
    # An edit or a new file stops every command first, as a change by hand (tests/test_workspace_check.py): taken as
    # the workspace's state here, finalize's own check of the photos is the one that meets it.
    recorded(ws)
    capsys.readouterr()
    assert _run(monkeypatch, ws, "finalize") == 2
    said = capsys.readouterr()
    assert "not as the execution left" in said.out + said.err
    assert not (ctl / "photos-26-finalized-media.json").exists()


@pytest.mark.spec("RUL-finalize_reports_placement", "RUL-plan_counts_placement", "BLD-executable_plan",
                  "RUL-finalize_keeps_placement_count",
                  test="TST-geotag_finalize-finalize_reports_how_every_photo_was_placed")
def test_finalize_reports_how_every_photo_was_placed(tmp_path, monkeypatch, capsys):
    """The measure of a run: every photo counted by how it came by its position — in the plan, in finalize's output,
    and in the package's manifest."""
    ws, ctl = _ready_ws(tmp_path, monkeypatch)
    _to_executed(monkeypatch, ws, ctl)
    plan = json.load(open(ctl / "photos-24-executable-plan.json"))
    assert plan["placement"] == {"native": 2}
    capsys.readouterr()
    assert _run(monkeypatch, ws, "finalize") == 0
    assert "Positions: 2 native — of 2 photo(s)." in capsys.readouterr().out
    assert json.load(open(ctl / "photos-26-archive-manifest.json"))["placement"] == {"native": 2}


@pytest.mark.spec("RUL-log_cites_decisions", "RUL-placement_recorded_with_its_track",
                  test="TST-geotag_finalize-the_log_says_what_placed_a_photo")
def test_the_log_says_what_placed_a_photo():
    """A photo the tracks placed has in its log the track that placed it and the time it was placed at. And a photo
    recorded under its new name by a prep run since the plan keeps the time steps of the row planned under its old
    one."""
    d = f"{BYDEST}/T"
    files = [_file(f"{d}/2024-07-03--14-00-00.arw", "fpT")]
    rows = [{"relative_path": f"{d}/t.arw", "resolved_utc": "2024-07-03T12:00:00Z"}]
    plan = {"destinations": {d: {
        "operations": [
            {"type": "metadata_gps_write", "relative_path": f"{d}/t.arw", "gps_origin": "recompute_automated",
             "preconditions": {"content_fingerprint": "fpT"}, "writes": {"GPSLatitude": 50.0, "GPSLongitude": 4.0},
             "provenance": {"gpx_file": "trip.gpx", "resolved_utc": "2024-07-03T12:00:00Z"}},
            {"type": "rename_no_clobber", "relative_path": f"{d}/t.arw", "preconditions": {"content_fingerprint": "fpT"},
             "from": "t.arw", "to": "2024-07-03--14-00-00.arw"}]}}}
    log = cal.build_complete_log({}, files, rows, {}, plan)
    steps = {s["action"]: s for s in log["fpT"]["journey"]}
    assert steps["gps_written"]["gpx_file"] == "trip.gpx" and steps["gps_written"]["at_utc"] == "2024-07-03T12:00:00Z"
    assert steps["resolved_utc"]["value"] == "2024-07-03T12:00:00Z"            # found under the old name's row
    assert not any(s["action"] == "left_unlocated" for e in log.values() for s in e["journey"])


def _hold(ws, ctl, rel, lat, lon):
    """The handoff, as a prep run since would record it, saying photo `rel` holds (`lat`, `lon`) — None for none."""
    ho = json.load(open(ctl / "photos-11-handoff.json"))
    for r in ho["files"]:
        if r["relative_path"] == rel:
            parsed = json.loads(r["metadata_status"]["parsed_json"])
            parsed.pop("GPSLatitude"); parsed.pop("GPSLongitude")
            if lat is not None:
                parsed.update(GPSLatitude=lat, GPSLongitude=lon)
            r["metadata_status"]["parsed_json"] = json.dumps(parsed)
    (ctl / "photos-11-handoff.json").write_text(json.dumps(ho))
    recorded(str(ws))


@pytest.mark.parametrize("held", [(None, None), (0, 0), (0.0, -0.0)])
@pytest.mark.spec("RUL-finalize_refuses_unplaced", "BLD-no_photo_unplaced", "RUL-null_island_is_no_position",
                  test="TST-geotag_finalize-finalize_refuses_a_photo_holding_no_position")
def test_finalize_refuses_a_photo_holding_no_position(tmp_path, monkeypatch, capsys, held):
    """Finalize reads each photo's position from what it holds — prep's reading of it, and what the executed plan
    wrote it — not from the plan's decisions alone: a photo that holds none, or latitude 0 and longitude 0, stops it,
    named, and nothing is packaged."""
    ws, ctl = _ready_ws(tmp_path, monkeypatch)
    _to_executed(monkeypatch, ws, ctl)
    _hold(ws, ctl, f"{BYDEST}/T/b.arw", *held)
    capsys.readouterr()
    assert _run(monkeypatch, ws, "finalize") == 2
    said = capsys.readouterr()
    out = said.out + said.err
    assert "1 photo(s) in 6-photos-by-dest hold no position" in out and "b.arw" in out and "a.arw" not in out
    # the closing hint defers to the blocker's own fix, never a stale "run geotag execute" for an executed plan
    assert "do what each line above says" in out and "to a successful finish" not in out
    assert not (ctl / "photos-26-complete-log.json").exists()


@pytest.mark.spec("RUL-finalize_refuses_unplaced", "BLD-no_photo_unplaced",
                  test="TST-geotag_finalize-a_position_the_plan_wrote_counts")
def test_a_position_the_plan_wrote_counts():
    """A photo prep read with no position, or at latitude 0 and longitude 0, holds the one the executed plan wrote
    it; a photo whose position the plan cleared holds none; one the plan did not touch holds what prep read."""
    def rec(name, gps):
        parsed = {} if gps is None else {"GPSLatitude": gps[0], "GPSLongitude": gps[1]}
        return {"relative_path": f"{BYDEST}/T/{name}", "folder_class": BYDEST, "media_class": "raw",
                "content_hash": json.dumps({"status": "valid", "value": "fp-" + name}),
                "metadata_status": {"parsed_json": json.dumps(parsed)}}
    def op(name, kind, writes):
        return {"type": kind, "relative_path": f"{BYDEST}/T/{name}", "writes": writes,
                "preconditions": {"content_fingerprint": "fp-" + name}}
    handoff = {"files": [rec("none.arw", None), rec("zero.arw", (0, 0)), rec("own.arw", (50.0, 4.0)),
                         rec("cleared.arw", (50.0, 4.0)), rec("left.arw", None),
                         dict(rec("elsewhere.arw", None), folder_class="5-photos-by-date")]}
    plan = {"destinations": {f"{BYDEST}/T": {"operations": [
        op("none.arw", "metadata_gps_write", {"GPSLatitude": 50.5, "GPSLongitude": 4.5}),
        op("none.arw", "gps_marker_write", {"GPSProcessingMethod": "carto-gpx-interpolated"}),
        op("zero.arw", "metadata_gps_write", {"GPSLatitude": 50.5, "GPSLongitude": 4.5}),
        op("cleared.arw", "gps_marker_write", {"GPSLatitude": "", "GPSLatitudeRef": "", "GPSLongitude": "",
                                               "GPSLongitudeRef": ""})]}}}
    assert utils.photos_without_position(handoff, plan) == [f"{BYDEST}/T/cleared.arw", f"{BYDEST}/T/left.arw"]


@pytest.mark.spec("RUL-finalize_refuses_unplaced", "RUL-merge_refuses_unplaced", "BLD-no_photo_unplaced",
                  test="TST-geotag_finalize-a_copy_in_another_destination_is_placed_on_its_own")
def test_a_copy_in_another_destination_is_placed_on_its_own():
    """One photo copied into two destinations — two records of one fingerprint — the plan placing only one copy: the
    other holds no position, and is named. Each copy is joined to the plan by the path the plan was built on."""
    def rec(dest):
        return {"relative_path": f"{BYDEST}/{dest}/a.arw", "folder_class": BYDEST, "media_class": "raw",
                "content_hash": json.dumps({"status": "valid", "value": "fp-a"}),
                "metadata_status": {"parsed_json": "{}"}}
    handoff = {"files": [rec("Rome"), rec("Paris")]}
    plan = {"destinations": {f"{BYDEST}/Rome": {"operations": [
        {"type": "metadata_gps_write", "relative_path": f"{BYDEST}/Rome/a.arw",
         "writes": {"GPSLatitude": 41.9, "GPSLongitude": 12.5}, "preconditions": {"content_fingerprint": "fp-a"}}]}}}
    assert utils.photos_without_position(handoff, plan) == [f"{BYDEST}/Paris/a.arw"]


@pytest.mark.spec("RUL-finalize_needs_no_metadata_tool", "BLD-geotag_exiftool_needed",
                  test="TST-geotag_finalize-finalize_runs_without_exiftool_plan_and_execute_do_not")
def test_finalize_runs_without_exiftool_plan_and_execute_do_not(tmp_path, monkeypatch, capsys):
    """Finalize runs no tool on a photo, so it packages an execution with exiftool not installed; plan and
    execute, whose plan is written through it, stop without it."""
    ws, ctl = _ready_ws(tmp_path, monkeypatch)
    real = utils.missing_tools
    no_exiftool = lambda tools: [t for t in tools if t == "exiftool"] or real(tools)
    monkeypatch.setattr(utils, "missing_tools", no_exiftool)
    capsys.readouterr()
    assert _run(monkeypatch, ws, "plan") == 2
    out = capsys.readouterr()
    assert "exiftool not found" in out.out + out.err
    monkeypatch.setattr(utils, "missing_tools", real)
    _to_executed(monkeypatch, ws, ctl)
    monkeypatch.setattr(utils, "missing_tools", no_exiftool)
    capsys.readouterr()
    assert _run(monkeypatch, ws, "execute") == 2
    out = capsys.readouterr()
    assert "exiftool not found" in out.out + out.err
    assert _run(monkeypatch, ws, "finalize") == 0
    out = capsys.readouterr()
    assert "exiftool not found" not in out.out + out.err
    assert (ctl / "photos-26-archive-manifest.json").exists()


def _planned(monkeypatch, ws, ctl):
    _run(monkeypatch, ws, "plan")
    _run(monkeypatch, ws, "plan")
    return json.load(open(ctl / "photos-24-executable-plan.json"))["plan_id"]


@pytest.mark.spec("RUL-unreadable_execution_record_stops", "BLD-unreadable_execution_records",
                  test="TST-geotag_finalize-execute_stops_on_an_unreadable_journal_or_summary")
@pytest.mark.parametrize("record", ["journal", "summary"])
def test_execute_stops_on_an_unreadable_journal_or_summary(tmp_path, monkeypatch, capsys, record):
    """A journal or an execution summary of the plan that cannot be read is never taken for none: execute stops
    before it keeps, snapshots or writes anything, naming the file, and leaves the file as it is."""
    ws, ctl = _ready_ws(tmp_path, monkeypatch)
    plan_id = _planned(monkeypatch, ws, ctl)
    journal, summary = ctl / f"journal-{plan_id}.json", ctl / "photos-25-execution-summary.json"
    bad = journal if record == "journal" else summary
    bad.write_text('{"operations": {"x": "confirm')                      # torn: not JSON
    written = []
    monkeypatch.setattr(cal.GeotagWorkflow, "_exiftool_write", lambda self, p, t: written.append(p) or True)
    capsys.readouterr()
    assert _run(monkeypatch, ws, "execute") == 2
    out = capsys.readouterr()
    assert str(bad) in out.out + out.err and "cannot be read" in out.out + out.err
    assert written == [] and not (ctl / "executed").exists()
    assert bad.read_text() == '{"operations": {"x": "confirm'
    assert (journal if record == "summary" else summary).exists() is False


@pytest.mark.spec("RUL-unreadable_execution_record_stops", "BLD-unreadable_execution_records",
                  test="TST-geotag_finalize-finalize_stops_on_an_unreadable_record_of_a_pass")
@pytest.mark.parametrize("record", ["own_journal", "kept_plan", "other_journal", "list_not_object"])
def test_finalize_stops_on_an_unreadable_record_of_a_pass(tmp_path, monkeypatch, capsys, record):
    """The plan's journal, a kept plan or any journal finalize reads to find the earlier passes, unreadable, stops
    finalize writing nothing: no pass is left out of the log unsaid, no photo judged by a baseline it lacks."""
    ws, ctl = _ready_ws(tmp_path, monkeypatch)
    _to_executed(monkeypatch, ws, ctl)
    plan_id = json.load(open(ctl / "photos-24-executable-plan.json"))["plan_id"]
    bad = {"own_journal": ctl / f"journal-{plan_id}.json",
           "kept_plan": ctl / "photos-24-executable-plan-007.json",
           "other_journal": ctl / "journal-0123456789abcdef.json",
           "list_not_object": ctl / "journal-0123456789abcdef.json"}[record]
    bad.write_text("[]" if record == "list_not_object" else "{not json")
    if record == "kept_plan":                                              # one an execution ran, by its summary
        (ctl / "photos-25-execution-summary-009.json").write_text(json.dumps(
            {"plan_id": "0123456789abcdef", "status": "success",
             "summarizes": {"photos-24-executable-plan.json": {"sha256": hashlib.sha256(b"{not json").hexdigest()}}}))
    capsys.readouterr()
    assert _run(monkeypatch, ws, "finalize") == 2
    out = capsys.readouterr()
    assert str(bad) in out.out + out.err and "cannot be read" in out.out + out.err
    assert not list(ctl.glob("photos-26-*"))


_TORN_PLANS = {"torn": '{"plan_id": "abc", "destinations": {', "not_json": "plan", "not_an_object": "[]"}


@pytest.mark.spec("RUL-unreadable_plan_replanned", "BLD-unreadable_plan",
                  test="TST-geotag_finalize-execute_sends_an_unreadable_plan_to_plan_again")
@pytest.mark.parametrize("torn", sorted(_TORN_PLANS))
def test_execute_sends_an_unreadable_plan_to_plan_again(tmp_path, monkeypatch, capsys, torn):
    """A photos-24 that cannot be read — torn, not JSON, not an object — stops execute with exit 2 and the way on,
    `geotag plan`, never a traceback: nothing is written to a photo, no summary or journal is written, and the file is
    left as it is."""
    ws, ctl = _ready_ws(tmp_path, monkeypatch)
    _planned(monkeypatch, ws, ctl)
    plan = ctl / "photos-24-executable-plan.json"
    plan.write_text(_TORN_PLANS[torn])
    written = []
    monkeypatch.setattr(cal.GeotagWorkflow, "_exiftool_write", lambda self, p, t: written.append(p) or True)
    capsys.readouterr()
    assert _run(monkeypatch, ws, "execute") == 2
    out = capsys.readouterr()
    said = out.out + out.err
    assert str(plan) in said and "cannot be read" in said and "`geotag plan` again" in said
    assert "Traceback" not in said
    assert written == [] and not (ctl / "photos-25-execution-summary.json").exists()
    assert not list(ctl.glob("journal-*.json"))
    assert plan.read_text() == _TORN_PLANS[torn]


@pytest.mark.spec("RUL-unreadable_plan_replanned", "BLD-unreadable_plan",
                  test="TST-geotag_finalize-finalize_sends_an_unreadable_plan_to_plan_again")
@pytest.mark.parametrize("torn", sorted(_TORN_PLANS))
def test_finalize_sends_an_unreadable_plan_to_plan_again(tmp_path, monkeypatch, capsys, torn):
    """The executed plan, unreadable at finalize, stops it with exit 2, sending the user to `geotag plan`; no part of
    the package is written."""
    ws, ctl = _ready_ws(tmp_path, monkeypatch)
    _to_executed(monkeypatch, ws, ctl)
    plan = ctl / "photos-24-executable-plan.json"
    plan.write_text(_TORN_PLANS[torn])
    capsys.readouterr()
    assert _run(monkeypatch, ws, "finalize") == 2
    out = capsys.readouterr()
    said = out.out + out.err
    assert str(plan) in said and "`geotag plan` again" in said and "Traceback" not in said
    assert not list(ctl.glob("photos-26-*"))
    assert plan.read_text() == _TORN_PLANS[torn]


@pytest.mark.spec("RUL-unreadable_plan_replanned", "BLD-unreadable_plan",
                  test="TST-geotag_finalize-a_plan_made_again_after_an_unreadable_one_executes")
def test_a_plan_made_again_after_an_unreadable_one_executes(tmp_path, monkeypatch):
    """The way on works: `geotag plan` makes the plan anew — the unreadable one set aside under -NNN, as a re-plan sets
    aside any plan — and execute then carries it out."""
    ws, ctl = _ready_ws(tmp_path, monkeypatch)
    _planned(monkeypatch, ws, ctl)
    plan = ctl / "photos-24-executable-plan.json"
    plan.write_text("[]")
    assert _run(monkeypatch, ws, "plan") == 0
    assert isinstance(json.loads(plan.read_text()), dict)
    assert [p.read_text() for p in ctl.glob("photos-24-executable-plan-*.json")] == ["[]"]
    assert _run(monkeypatch, ws, "execute") == 0
    assert json.load(open(ctl / "photos-25-execution-summary.json"))["status"] == "success"
    assert _run(monkeypatch, ws, "finalize") == 0                         # the copy no execution ran: passed over
    assert [p.read_text() for p in ctl.glob("photos-24-executable-plan-*.json")] == ["[]"]
    listed = json.load(open(ctl / "photos-26-archive-manifest.json"))["contents"]
    assert any(n.startswith("photos-24-executable-plan-") for n in listed)   # and kept, archived


@pytest.mark.spec("RUL-unread_plan_never_run_passed", "BLD-unexecuted_kept_plan_passed",
                  "RUL-unreadable_execution_record_stops",
                  test="TST-geotag_finalize-an_unreadable_kept_plan_is_passed_over_only_if_never_run")
@pytest.mark.parametrize("ran", ["never", "by_summary", "cut_off"])
def test_an_unreadable_kept_plan_is_passed_over_only_if_never_run(tmp_path, monkeypatch, capsys, ran):
    """A kept plan that cannot be read stops finalize unless no execution ran it: one a summary names by its SHA-256,
    or one that may be the plan of a journal with a confirmed operation and no plan finalize can read — a run cut off
    before its summary — still stops it, naming the copy; one neither can be is passed over, and the package
    written."""
    ws, ctl = _ready_ws(tmp_path, monkeypatch)
    _to_executed(monkeypatch, ws, ctl)
    torn = ctl / "photos-24-executable-plan-007.json"
    torn.write_text('{"plan_id": "0123456789abcdef", "destinations": {')
    if ran == "by_summary":
        (ctl / "photos-25-execution-summary-009.json").write_text(json.dumps(
            {"plan_id": "0123456789abcdef", "status": "partial",
             "summarizes": {"photos-24-executable-plan.json": {"sha256": hashlib.sha256(torn.read_bytes()).hexdigest()}}}))
    elif ran == "cut_off":
        (ctl / "journal-0123456789abcdef.json").write_text(json.dumps(
            {"plan_id": "0123456789abcdef", "operations": {"op-1": "confirmed"}}))
    capsys.readouterr()
    code = _run(monkeypatch, ws, "finalize")
    said = "".join(capsys.readouterr())
    if ran == "never":
        assert code == 0 and (ctl / "photos-26-archive-manifest.json").exists()
    else:
        assert code == 2 and str(torn) in said and "cannot be read" in said
        assert not list(ctl.glob("photos-26-*"))
    assert torn.read_text() == '{"plan_id": "0123456789abcdef", "destinations": {'


@pytest.mark.spec("RUL-geotag_run_records_kept", "BLD-geotag_records_versioned",
                  test="TST-geotag_finalize-summary_and_package_made_again_keep_the_earlier")
def test_summary_and_package_made_again_keep_the_earlier(tmp_path, monkeypatch):
    """An execution run again sets the earlier summary aside under -NNN; finalize run again sets the whole earlier
    package aside so, the archive as photos-26-archive-NNN.tar.gz — kept, and never archived again."""
    import tarfile
    ws, ctl = _ready_ws(tmp_path, monkeypatch)
    _to_executed(monkeypatch, ws, ctl)
    first_summary = (ctl / "photos-25-execution-summary.json").read_bytes()
    assert _run(monkeypatch, ws, "execute") == 0                          # nothing left to do: a new summary
    assert (ctl / "photos-25-execution-summary-001.json").read_bytes() == first_summary
    assert _run(monkeypatch, ws, "finalize") == 0
    names = ("photos-26-complete-log.json", "photos-26-finalized-media.json", "photos-26-geotag-ingest.db",
             "photos-26-archive-manifest.json", "photos-26-archive.tar.gz")
    first = {n: (ctl / n).read_bytes() for n in names}
    assert not list(ctl.glob("photos-26-*-001*"))                        # a first package sets nothing aside
    assert _run(monkeypatch, ws, "finalize") == 0
    kept = {"photos-26-complete-log.json": "photos-26-complete-log-001.json",
            "photos-26-finalized-media.json": "photos-26-finalized-media-001.json",
            "photos-26-geotag-ingest.db": "photos-26-geotag-ingest-001.db",
            "photos-26-archive-manifest.json": "photos-26-archive-manifest-001.json",
            "photos-26-archive.tar.gz": "photos-26-archive-001.tar.gz"}
    for n, copy in kept.items():
        assert (ctl / copy).read_bytes() == first[n], copy
    listed = set(json.load(open(ctl / "photos-26-archive-manifest.json"))["contents"])
    assert "photos-26-complete-log-001.json" in listed and "photos-25-execution-summary-001.json" in listed
    assert not any(n.endswith(".tar.gz") for n in listed)
    with tarfile.open(ctl / "photos-26-archive.tar.gz") as tar:
        assert not any(m.name.endswith(".tar.gz") for m in tar.getmembers())


# --- the tracks kept with the workspace (BLD-track_catalogue, BLD-track_window, BLD-withdrawn_track_points) -------

def _track_rows(ctl, sql):
    conn = sqlite3.connect(str(ctl / "photos-00-ingest.db"))
    try:
        return conn.execute(sql).fetchall()
    finally:
        conn.close()


@pytest.mark.spec("RUL-track_points_kept", "RUL-database_archived", "BLD-track_catalogue", "BLD-workspace_database",
                  test="TST-geotag_finalize-the_tracks_decided_by_are_sealed_in_the_archive")
def test_the_tracks_decided_by_are_sealed_in_the_archive(tmp_path, monkeypatch):
    """The track points the plan was decided by are in the database of record from the plan on — no scratch memo
    beside it — and finalize archives them, in the database and in its image."""
    import tarfile
    ws, ctl = _ready_ws(tmp_path, monkeypatch)
    _run(monkeypatch, ws, "plan")
    assert not (ctl / "photos-00-track-memo.db").exists()
    assert _track_rows(ctl, "SELECT f.path, COUNT(*) FROM gpx_track_points JOIN gpx_track_files f USING (track_id) "
                            "GROUP BY f.path") == [("t.gpx", 2)]
    _to_executed(monkeypatch, ws, ctl)
    assert _run(monkeypatch, ws, "finalize") == 0
    image = sqlite3.connect(str(ctl / "photos-26-geotag-ingest.db"))
    try:
        assert image.execute("SELECT lat, lon, time_utc FROM gpx_track_points ORDER BY point_index").fetchall() == [
            (50.0, 4.0, "2024-07-03T12:00:00+00:00"), (51.0, 5.0, "2024-07-03T13:00:00+00:00")]
    finally:
        image.close()
    with tarfile.open(ctl / "photos-26-archive.tar.gz") as tar:
        names = {m.name for m in tar.getmembers()}
    assert any(n.endswith("photos-00-ingest.db") for n in names) and any(n.endswith("photos-26-geotag-ingest.db")
                                                                         for n in names)


@pytest.mark.spec("RUL-withdrawn_track_points_kept", "BLD-withdrawn_track_points", "RUL-gone_track_told",
                  test="TST-geotag_finalize-execute_marks_the_tracks_it_times_photos_by")
def test_execute_marks_the_tracks_it_times_photos_by(tmp_path, monkeypatch):
    """The offset the camera's own GPS gave rests on t.gpx: execute records it as used, and when the file is taken
    out the tracks, catalogued again as a plan does, name it and keep its points, withdrawn."""
    ws, ctl = _ready_ws(tmp_path, monkeypatch)
    _to_executed(monkeypatch, ws, ctl)
    plan = json.load(open(ctl / "photos-24-executable-plan.json"))
    assert _track_rows(ctl, "SELECT u.plan_id, f.path FROM gpx_track_use u JOIN gpx_track_files f USING (track_id)") \
        == [(plan["plan_id"], "t.gpx")]
    gpx = cal.selected_gpx_root()
    os.remove(os.path.join(gpx, "t.gpx"))
    again = cal.GeotagWorkflow(str(ws)).plan_tracks(plan, keep=True)
    assert again.gone == ["t.gpx"] and any("t.gpx" in w and "withdrawn" in w for w in again.warnings)
    assert not again.points
    assert _track_rows(ctl, "SELECT f.withdrawn, COUNT(*) FROM gpx_track_points JOIN gpx_track_files f "
                            "USING (track_id) GROUP BY f.track_id") == [(1, 2)]


@pytest.mark.spec("RUL-sealing_needs_no_tracks", "RUL-finalize_requires_plan_still_holds", "BLD-track_window",
                  test="TST-geotag_finalize-finalize_seals_without_the_tracks_folder")
def test_finalize_seals_without_the_tracks_folder(tmp_path, monkeypatch):
    """Finalize seals what the workspace keeps: with the tracks folder gone after execute it packages all the same,
    and never builds the tracks from gpx_root."""
    ws, ctl = _ready_ws(tmp_path, monkeypatch)
    _to_executed(monkeypatch, ws, ctl)
    gpx = cal.selected_gpx_root()
    os.rename(gpx, gpx + "-unmounted")
    real = cal.GPXIndex.build
    monkeypatch.setattr(cal.GPXIndex, "build", lambda self, *a, **k: (k.get("read") is False or pytest.fail(
        "finalize read gpx_root")) and real(self, *a, **k))
    assert _run(monkeypatch, ws, "finalize") == 0
    assert (ctl / "photos-26-archive.tar.gz").exists()


@pytest.mark.spec("RUL-tracks_elsewhere_restale_nothing", "RUL-tracks_in_dependencies", "BLD-track_window", "BLD-gpx_root_missing",
                  test="TST-geotag_finalize-execute_checks_the_tracks_over_the_plan_s_window")
def test_execute_checks_the_tracks_over_the_plan_s_window(tmp_path, monkeypatch):
    """The plan records the window its tracks' fingerprint is of; execute takes the tracks again over it: a track of
    another year added since stales nothing, a point moved inside it stales the plan."""
    ws, ctl = _ready_ws(tmp_path, monkeypatch)
    _run(monkeypatch, ws, "plan")
    p = ctl / "photos-21-time-decisions.json"; p.write_text(p.read_text())
    _run(monkeypatch, ws, "plan")
    plan = json.load(open(ctl / "photos-24-executable-plan.json"))
    assert cal.valid_window(plan["depends_on"]["gpx_window"])
    gpx = cal.selected_gpx_root()
    with open(os.path.join(gpx, "2019.gpx"), "w") as f:
        f.write('<gpx xmlns="http://www.topografix.com/GPX/1/1"><trk><trkseg>'
                '<trkpt lat="50.0" lon="4.0"><time>2019-07-03T12:00:00Z</time></trkpt></trkseg></trk></gpx>')
    wf = cal.GeotagWorkflow(str(ws)); wf.preflight(for_execute=True)
    assert wf.revalidate_plan(plan, wf.plan_tracks(plan)) == []
    t = os.path.join(gpx, "t.gpx")
    with open(t) as f:
        moved = f.read().replace('lat="51.0"', 'lat="51.5"')
    with open(t, "w") as f:
        f.write(moved)
    assert any("gpx_fingerprint" in s for s in wf.revalidate_plan(plan, wf.plan_tracks(plan)))
    os.rename(gpx, gpx + "-unmounted")                                    # not there: cannot be checked
    assert any("cannot be checked" in s for s in wf.revalidate_plan(plan, wf.plan_tracks(plan)))
    os.rename(gpx + "-unmounted", gpx)
    del plan["depends_on"]["gpx_window"]
    assert any("gpx_window" in s for s in wf.revalidate_plan(plan, wf.plan_tracks(plan)))


@pytest.mark.skipif(hasattr(os, "geteuid") and os.geteuid() == 0, reason="root lists every folder")
@pytest.mark.spec("RUL-unlisted_tracks_stop_geotag", "RUL-unchecked_counts_as_changed", "BLD-track_catalogue",
                  test="TST-geotag_finalize-tracks_that_cannot_be_listed_stop_plan_and_execute")
def test_tracks_that_cannot_be_listed_stop_plan_and_execute(tmp_path, monkeypatch, capsys):
    """A tracks folder that cannot be listed cannot be checked: the plan stops on it, naming it, and execute finds the
    plan stale, changing nothing."""
    ws, ctl = _ready_ws(tmp_path, monkeypatch)
    _run(monkeypatch, ws, "plan")
    p = ctl / "photos-21-time-decisions.json"; p.write_text(p.read_text())
    _run(monkeypatch, ws, "plan")
    gpx = cal.selected_gpx_root()
    plan = (ctl / "photos-24-executable-plan.json").read_bytes()
    before = sorted(os.listdir(ws / BYDEST / "T"))
    os.chmod(gpx, 0)
    try:
        capsys.readouterr()
        assert _run(monkeypatch, ws, "execute") == 2
        assert sorted(os.listdir(ws / BYDEST / "T")) == before
        assert _run(monkeypatch, ws, "plan") == 2
        said = capsys.readouterr()
        assert "cannot be checked" in said.out + said.err and "cannot be seen" in said.out + said.err
    finally:
        os.chmod(gpx, 0o755)
    assert (ctl / "photos-24-executable-plan.json").read_bytes() == plan
