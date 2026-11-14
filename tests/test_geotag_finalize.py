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


@pytest.mark.spec("RUL-log_records_time_replaced", "BLD-geotag_log_steps",
                  test="TST-geotag_finalize-a_time_written_is_logged_with_what_it_replaced")
def test_a_time_written_is_logged_with_what_it_replaced_and_how_it_was_found():
    """Two phone photos written alike: one read by the offset its phone recorded, one by assuming the
    destination's zone. The log tells them apart, and says what each held before."""
    def op(rel, rule, held_off):
        f = {"relative_path": rel, "raw_times": {"DateTimeOriginal": "2024:07:03 19:00:00",
                                                 **({"OffsetTimeOriginal": held_off} if held_off else {})}}
        return {"type": "metadata_time_write", "relative_path": rel,
                "writes": {"DateTimeOriginal": "2024:07:03 12:00:00", "OffsetTimeOriginal": "+02:00"},
                "pre_state": cal.held_time_pre_state(f),
                "provenance": {"time_rule_used": rule, "source_time_provenance": "EXIF:DateTimeOriginal"}}
    a, b = f"{BYDEST}/T/a.jpg", f"{BYDEST}/T/b.jpg"
    plan = {"plan_id": "p1", "destinations": {f"{BYDEST}/T": {"operations": [
        op(a, "smartphone_native_offset", "+09:00"), op(b, "destination_timezone", None)]}}}
    photos = cal.build_complete_log({}, [_file(a, "fpA"), _file(b, "fpB")], [], {}, plan)
    wa = next(s for s in photos["fpA"]["journey"] if s["action"] == "time_written")
    wb = next(s for s in photos["fpB"]["journey"] if s["action"] == "time_written")
    assert wa["pre_state"] == {"DateTimeOriginal": "2024:07:03 19:00:00", "OffsetTimeOriginal": "+09:00"}
    assert wb["pre_state"] == {"DateTimeOriginal": "2024:07:03 19:00:00", "OffsetTimeOriginal": None}
    assert (wa["rule"], wb["rule"]) == ("smartphone_native_offset", "destination_timezone")
    assert wa["read_from"] == "EXIF:DateTimeOriginal" and wa["run"] == "p1"
    assert wa["writes"] == {"DateTimeOriginal": "2024:07:03 12:00:00", "OffsetTimeOriginal": "+02:00"}
    # a pass executed earlier logs its time write the same way
    plan["destinations"][f"{BYDEST}/T"]["operations"][0]["preconditions"] = {"content_fingerprint": "fpA"}
    later = cal.build_complete_log({}, [_file(a, "fpA")], [], {}, {"plan_id": "p2", "destinations": {}},
                                   earlier_passes=[(plan, None)])
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
    inherited = {"proposal": {"proposal_source": "inherited", "inherited_from": BYDEST},
                 "user_decision": {"accept_proposal": True}}
    assert cal.manual_gps_pointer("manual_fallback", f"{BYDEST}/T", f"{BYDEST}/T/m.jpg", inherited) == \
        f"photos-23 destinations.{BYDEST}/T.folder_fallback (accepted from {BYDEST})"
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
        default_folder_timezone="Europe/Brussels", multi_anchor_auto_apply=True)
    (ctl / "photos-00-config.json").write_text(json.dumps(cfg))
    answer_root_zone(ctl)                        # the zone answered once at the root (§18)
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
                "metadata_status": {"camera_group_key_version": utils.CAMERA_GROUP_KEY_VERSION,
                                    "camera_group_key": CAM, "has_timestamp": True, "has_native_gps": True,
                                    "field_set_version": utils.FIELD_SET_VERSION, "parsed_json": json.dumps(parsed)}}
    files = [rec(f"{BYDEST}/T/a.arw", "2024:07:03 14:00:00", (50.0, 4.0)),
             rec(f"{BYDEST}/T/b.arw", "2024:07:03 15:00:00", (51.0, 5.0))]
    (ctl / "photos-11-handoff.json").write_text(json.dumps({"filename_timestamp_format": utils.CONFIG["filename_timestamp_format"], "files": files, "cache_fingerprint": "pcf",
        "depends_on": {"prep_log": {"sha256": utils.sha256_file(str(ctl / "photos-15-prep-log.json"))}}}))

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


@pytest.mark.spec("RUL-finalize_requires_success")
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


@pytest.mark.spec("RUL-finalize_explicit", "RUL-finalize_non_destructive", "RUL-carry_forward_by_copy", "RUL-package_contents", "RUL-package_self_describing", "RUL-database_is_record", test="TST-geotag_finalize-finalize_assembles_package_and_is_nondestructive")
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


@pytest.mark.spec("RUL-package_contents", "RUL-package_self_describing", "RUL-other_databases_scratch", "RUL-images_archived", "RUL-config_archived", test="TST-geotag_finalize-finalize_archives_the_whole_control_directory")
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
    """§31 (anti): finalize assembles the archival package (photos-26 complete-log + DB + manifest)
    but NEVER merges into a library — it produces no merge artifacts and moves no media. Snapshot the
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


def test_finalize_is_idempotent(tmp_path, monkeypatch):
    ws, ctl = _ready_ws(tmp_path, monkeypatch)
    _to_executed(monkeypatch, ws, ctl)
    assert _run(monkeypatch, ws, "finalize") == 0
    log1 = (ctl / "photos-26-complete-log.json").read_bytes()
    prep1 = (ctl / "photos-15-prep-log.json").read_bytes()
    assert _run(monkeypatch, ws, "finalize") == 0
    assert (ctl / "photos-26-complete-log.json").read_bytes() == log1     # deterministic
    assert (ctl / "photos-15-prep-log.json").read_bytes() == prep1        # prep untouched


@pytest.mark.spec("RUL-finalize_requires_success", "BLD-finalize_preconditions",
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



# --- what finalize packages is what execution left (§31) ---------------------------------------------

@pytest.mark.spec("RUL-finalize_checks_photos", "RUL-finalize_requires_success", "BLD-finalize_preconditions",
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
    capsys.readouterr()
    assert _run(monkeypatch, ws, "finalize") == 2
    said = capsys.readouterr()
    assert "not as the execution left" in said.out + said.err
    assert not (ctl / "photos-26-finalized-media.json").exists()


@pytest.mark.spec("RUL-finalize_reports_placement", "RUL-plan_counts_placement", "BLD-executable_plan",
                  test="TST-geotag_finalize-finalize_reports_how_every_photo_was_placed")
def test_finalize_reports_how_every_photo_was_placed(tmp_path, monkeypatch, capsys):
    """The measure of a run: every photo counted by how it came by its position, those left without one among
    them — in the plan, in finalize's output, and in the package's manifest."""
    ws, ctl = _ready_ws(tmp_path, monkeypatch)
    _to_executed(monkeypatch, ws, ctl)
    plan = json.load(open(ctl / "photos-24-executable-plan.json"))
    assert plan["placement"] == {"native": 2}
    capsys.readouterr()
    assert _run(monkeypatch, ws, "finalize") == 0
    assert "Positions: 2 native — of 2 photo(s)." in capsys.readouterr().out
    assert json.load(open(ctl / "photos-26-archive-manifest.json"))["placement"] == {"native": 2}


@pytest.mark.spec("RUL-unlocated_logged", "RUL-log_cites_decisions", "RUL-placement_recorded_with_its_track",
                  test="TST-geotag_finalize-the_log_says_what_placed_a_photo_or_that_nothing_did")
def test_the_log_says_what_placed_a_photo_or_that_nothing_did():
    """A photo the user left unlocated has that in its log, with the decision; one the tracks placed has the
    track that placed it and the time it was placed at. And a photo recorded under its new name by a prep run
    since the plan keeps the time steps of the row planned under its old one."""
    d = f"{BYDEST}/T"
    files = [_file(f"{d}/u.arw", "fpU"), _file(f"{d}/2024-07-03--14-00-00.arw", "fpT")]
    rows = [{"relative_path": f"{d}/t.arw", "resolved_utc": "2024-07-03T12:00:00Z"}]
    plan = {"destinations": {d: {
        "left_unlocated": [{"relative_path": f"{d}/u.arw", "content_fingerprint": "fpU",
                            "because": f"photos-23 destinations.{d}.gps_decisions.review_items[u.arw]"}],
        "operations": [
            {"type": "metadata_gps_write", "relative_path": f"{d}/t.arw", "gps_origin": "recompute_automated",
             "preconditions": {"content_fingerprint": "fpT"}, "writes": {"GPSLatitude": 50.0, "GPSLongitude": 4.0},
             "provenance": {"gpx_file": "trip.gpx", "resolved_utc": "2024-07-03T12:00:00Z"}},
            {"type": "rename_no_clobber", "relative_path": f"{d}/t.arw", "preconditions": {"content_fingerprint": "fpT"},
             "from": "t.arw", "to": "2024-07-03--14-00-00.arw"}]}}}
    log = cal.build_complete_log({}, files, rows, {}, plan)
    assert {"phase": "geotag", "action": "left_unlocated",
            "because": f"photos-23 destinations.{d}.gps_decisions.review_items[u.arw]"} in log["fpU"]["journey"]
    steps = {s["action"]: s for s in log["fpT"]["journey"]}
    assert steps["gps_written"]["gpx_file"] == "trip.gpx" and steps["gps_written"]["at_utc"] == "2024-07-03T12:00:00Z"
    assert steps["resolved_utc"]["value"] == "2024-07-03T12:00:00Z"            # found under the old name's row
