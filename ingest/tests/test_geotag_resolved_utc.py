"""Phase 4 (geotag) — Stage 7 resolved UTC per file + the resolved-UTC cache fingerprint
(spec §22/§22.1). Time-correctness code, so the computation gets full branch coverage: camera
offset, smartphone native offset, destination-timezone fallback (DST-correct), and the unresolved
branches; plus the SQLite cache round-trip and the deterministic fingerprint. From conftest.py.
"""
import json
import sqlite3
import sys

import pytest

import photos_2_time_gps as cal
import photos_utils as utils

CAM = "SONY|ILCE-6400|123"
PHONE = "APPLE|iPhone|p1"
GROUPS = {CAM: {"camera_group_class": "camera"}, PHONE: {"camera_group_class": "smartphone"}}


def _art(*, tz="Europe/Brussels", offset=-7187):
    cell = {} if offset is None else {"effective_time_anchor": {"offset_seconds": offset, "source": "gpx_anchor_auto"}}
    return {"destinations": {"6-photos-by-dest/B": {
        "destination_timezone": {"effective_iana_timezone": tz},
        "camera_group_time_decisions": {CAM: cell}}}}


def _file(rel, key, naive, *, offset_tag=None):
    return {"relative_path": rel, "destination": "6-photos-by-dest/B", "camera_group_key": key,
            "source_naive_time": naive, "source_time_tag": "DateTimeOriginal",
            "raw_times": ({"OffsetTimeOriginal": offset_tag} if offset_tag else {})}


def _one(file, art=None):
    return cal.compute_resolved_utc([file], GROUPS, art or _art())[0]


# --- the computation, branch by branch --------------------------------------

def test_camera_offset():
    r = _one(_file("6-photos-by-dest/B/a.arw", CAM, "2024:07:03 14:12:08"))
    assert r["resolved_utc"] == "2024-07-03T12:12:21Z" and r["resolved_utc_status"] == "valid"
    assert r["time_rule_used"] == "camera_group_offset" and r["utc_offset_used"] == -7187
    assert r["time_decision_scope"] == f"{CAM}|6-photos-by-dest/B"


def test_camera_offset_missing_is_unresolved():
    r = _one(_file("6-photos-by-dest/B/a.arw", CAM, "2024:07:03 14:12:08"), _art(offset=None))
    assert r["resolved_utc"] is None and r["resolved_utc_status"] == "unresolved"
    assert r["time_rule_used"] == "offset_missing"


def test_smartphone_native_offset():
    r = _one(_file("6-photos-by-dest/B/p.jpg", PHONE, "2024:07:03 14:00:00", offset_tag="+02:00"))
    assert r["resolved_utc"] == "2024-07-03T12:00:00Z" and r["time_rule_used"] == "smartphone_native_offset"
    assert r["utc_offset_used"] == 7200


def test_smartphone_destination_timezone_dst():
    summer = _one(_file("6-photos-by-dest/B/s.jpg", PHONE, "2024:07:03 14:00:00"))   # CEST = UTC+2
    assert summer["resolved_utc"] == "2024-07-03T12:00:00Z" and summer["time_rule_used"] == "destination_timezone"
    winter = _one(_file("6-photos-by-dest/B/w.jpg", PHONE, "2024:01:03 14:00:00"))   # CET = UTC+1
    assert winter["resolved_utc"] == "2024-01-03T13:00:00Z"


def test_smartphone_no_offset_no_timezone_is_unresolved():
    r = _one(_file("6-photos-by-dest/B/n.jpg", PHONE, "2024:07:03 14:00:00"), _art(tz=""))
    assert r["resolved_utc"] is None and r["time_rule_used"] == "timezone_missing"


def test_missing_timestamp_is_unresolved():
    r = _one(_file("6-photos-by-dest/B/x.jpg", CAM, "garbage"))
    assert r["resolved_utc"] is None and r["time_rule_used"] == "missing_timestamp"


def test_rows_are_path_sorted():
    files = [_file("6-photos-by-dest/B/z.arw", CAM, "2024:07:03 14:00:00"),
             _file("6-photos-by-dest/B/a.arw", CAM, "2024:07:03 14:00:00")]
    rows = cal.compute_resolved_utc(files, GROUPS, _art())
    assert [r["relative_path"] for r in rows] == ["6-photos-by-dest/B/a.arw", "6-photos-by-dest/B/z.arw"]


# --- pure helpers -----------------------------------------------------------

@pytest.mark.parametrize("s, secs", [
    ("+02:00", 7200), ("-05:30", -19800), ("+00:00", 0), ("-00:00", 0),
    ("xx", None), ("+2:00", None), ("", None), (None, None), ("+0200", None), (1234, None),
    ("+ab:cd", None), ("+123456", None)])   # passes the length/prefix guard but fails int/split parse
def test_parse_iso_offset(s, secs):
    assert cal._parse_iso_offset(s) == secs


def test_local_to_utc_dst_and_standard():
    from datetime import datetime
    assert cal._local_to_utc(datetime(2024, 7, 3, 14, 0, 0), "Europe/Brussels").hour == 12   # +2
    assert cal._local_to_utc(datetime(2024, 1, 3, 14, 0, 0), "Europe/Brussels").hour == 13   # +1


# --- SQLite cache + fingerprint ---------------------------------------------

def _rows():
    return cal.compute_resolved_utc(
        [_file("6-photos-by-dest/B/a.arw", CAM, "2024:07:03 14:12:08")], GROUPS, _art())


def test_cache_round_trips_and_replaces(tmp_path):
    ws = tmp_path / "ws"; (ws / ".photos-ingest").mkdir(parents=True)
    c = cal.GeotagCache(str(ws))
    c.replace_all(_rows())
    got = c.get_rows()
    assert len(got) == 1 and got[0]["resolved_utc"] == "2024-07-03T12:12:21Z"
    c.replace_all([])                                # a recompute fully replaces the prior set
    assert c.get_rows() == []
    c.close()


def test_fingerprint_stable_and_sensitive():
    rows = _rows()
    inp = {"photos_21_sha256": "abc", "gpx_fingerprint": "g"}
    base = cal.resolved_utc_fingerprint(rows, inp)
    assert base == cal.resolved_utc_fingerprint(rows, inp)                       # stable
    changed = [dict(rows[0], resolved_utc="2024-07-03T00:00:00Z")]
    assert cal.resolved_utc_fingerprint(changed, inp) != base                    # row change
    assert cal.resolved_utc_fingerprint(rows, {**inp, "gpx_fingerprint": "g2"}) != base  # input change


# --- end-to-end through run -------------------------------------------------

def test_run_populates_cache_when_complete(tmp_path, monkeypatch, capsys):
    MANAGED = ["0-sources", "1-strays", "2-missing-metadata", "3-redundant-jpgs",
               "4-videos-by-date", "5-photos-by-date", "6-photos-by-dest"]
    ws = tmp_path / "ws"; ws.mkdir()
    for d in MANAGED:
        (ws / d).mkdir()
    ctl = ws / ".photos-ingest"; ctl.mkdir()
    (ctl / "photos-00-workspace-guard").touch()
    gpx_dir = tmp_path / "gpx"; gpx_dir.mkdir()
    (gpx_dir / "t.gpx").write_text(
        '<gpx xmlns="http://www.topografix.com/GPX/1/1"><trk><trkseg>'
        '<trkpt lat="50.8467" lon="4.3525"><time>2024-07-03T12:12:21Z</time></trkpt>'
        '<trkpt lat="50.8480" lon="4.3540"><time>2024-07-03T12:13:21Z</time></trkpt>'
        '</trkseg></trk></gpx>')
    cfg = {k: v for k, v in utils.CONFIG.items() if k != "jobs"}
    cfg["gpx_root"] = str(gpx_dir)
    cfg["camera_time_and_timezone_policy"] = dict(
        cfg["camera_time_and_timezone_policy"], device_groups={"fixed_clock_cameras": [CAM], "phones": []},
        default_folder_timezone="Europe/Brussels", multi_anchor_auto_apply=True)
    (ctl / "photos-00-config.json").write_text(json.dumps(cfg))

    def rec(rel, lat, lon, dto):
        parsed = {"DateTimeOriginal": dto, "selected_source_naive_timestamp": dto,
                  "selected_source_timestamp_tag": "DateTimeOriginal", "camera_group_key": CAM,
                  "has_timestamp": True, "has_native_gps": True, "GPSLatitude": lat, "GPSLongitude": lon}
        return {"relative_path": rel, "media_class": "image", "folder_class": "6-photos-by-dest",
                "size": 1, "mtime_ns": 1, "content_hash": json.dumps({"value": "fp" + rel, "status": "valid"}),
                "metadata_status": {"camera_group_key": CAM, "has_timestamp": True, "has_native_gps": True,
                                    "field_set_version": 1, "parsed_json": json.dumps(parsed)}}
    files = [rec("6-photos-by-dest/B/a.arw", 50.8467, 4.3525, "2024:07:03 14:12:08"),
             rec("6-photos-by-dest/B/b.arw", 50.8480, 4.3540, "2024:07:03 14:13:08")]
    for f in files:
        p = ws / f["relative_path"]; p.parent.mkdir(parents=True, exist_ok=True); p.write_bytes(b"x")
    # the timezone must be accepted for status=complete
    (ctl / "photos-11-handoff.json").write_text(json.dumps({"files": files, "cache_fingerprint": "pcf"}))

    def run():
        monkeypatch.chdir(str(ws))
        monkeypatch.setattr(sys, "argv", ["photos-2-time-gps", "plan"])
        try:
            cal.main()
        except SystemExit as e:
            assert e.code in (0, None)

    def cache_rows():
        conn = sqlite3.connect(str(ctl / "photos-00-ingest.db"))
        try:
            if not conn.execute("SELECT name FROM sqlite_master WHERE type='table' "
                                "AND name='resolved_utc_cache'").fetchone():
                return None
            cur = conn.execute("SELECT relative_path, resolved_utc, time_rule_used "
                               "FROM resolved_utc_cache ORDER BY relative_path")
            return cur.fetchall()
        finally:
            conn.close()

    # The GPX anchor auto-resolves the offset and the timezone auto-resolves from the config default
    # (inherited down the nested geography), so status=complete on the FIRST run and the resolved-UTC
    # cache is populated immediately — no separate timezone-accept step is needed.
    run()
    out = capsys.readouterr().out
    assert "resolved_utc_cache_fingerprint" in out
    tz = json.load(open(ctl / "photos-21-time-decisions.json"))[
        "destinations"]["6-photos-by-dest/B"]["destination_timezone"]
    assert tz["requires_user_input"] is False and tz["decision_mode"] == "auto_resolved"
    rows = cache_rows()
    assert rows == [("6-photos-by-dest/B/a.arw", "2024-07-03T12:12:21Z", "camera_group_offset"),
                    ("6-photos-by-dest/B/b.arw", "2024-07-03T12:13:21Z", "camera_group_offset")]
