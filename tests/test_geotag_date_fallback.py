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

"""Geotag — a date fallback per destination, for photos with no recorded time (scans, above all).

A destination may be given a date — a year, a year and month, or a day — in photos-21's `date_fallback`. A photo with no
recorded time takes the one given at the nearest folder up, its own included: the day's midnight, local to its
destination, written into it as its corrected time and named by it, photos sharing it suffixed in the order of their
names. A photo with a time of its own keeps it. The filled time is not when the photo was taken, so no track places it
and it is no camera's evidence. An untimed photo no date covers stops geotag at photos-21, named. In-process, and
through `geotag plan`.
"""
import json
import sys
from datetime import datetime, timezone

import pytest

from _handoff import match_disk, vouched
from _zone import answer_root_zone

import photos_2_geotag as cal
import photos_utils as utils
from cartographer import _geotag_calc as _calc

ROOT = "6-photos-by-dest"
SCANS = f"{ROOT}/Scans"
DEST = f"{SCANS}/1985"
PHONE = "APPLE|iPhone|p1"
SCANNER = "EPSON|Perfection V600|"          # a group no configuration classes: a scan's carries no clock
GROUPS = {PHONE: {"camera_group_class": "smartphone"}, cal.NO_IDENTITY_KEY: {"camera_group_class": "unidentified"}}


def _untimed(name, dest=DEST):
    return {"relative_path": f"{dest}/{name}", "destination": dest, "camera_group_key": cal.NO_IDENTITY_KEY,
            "has_timestamp": False, "source_naive_time": None, "source_time_tag": None, "native_gps": None,
            "has_native_gps": False, "content_fingerprint": "fp-" + name, "raw_times": {}}


def _timed(name, naive, offset, dest=DEST):
    return {"relative_path": f"{dest}/{name}", "destination": dest, "camera_group_key": PHONE, "has_timestamp": True,
            "source_naive_time": naive, "source_time_tag": "EXIF:DateTimeOriginal", "native_gps": None,
            "has_native_gps": False, "content_fingerprint": "fp-" + name, "raw_times": {"OffsetTimeOriginal": offset}}


def _prior(dates, tz="Europe/Brussels"):
    """A photos-21 with the zone written at the root and each {destination: date} given as its date fallback."""
    out = {"destinations": {ROOT: {"destination_timezone": {"user_decision": {"manual_iana_timezone": tz}}}}}
    for dest, date in dates.items():
        out["destinations"].setdefault(dest, {})["date_fallback"] = {"user_decision": {"date": date}}
    return out


def _wf(tmp_path):
    ws = tmp_path / "ws"
    (ws / ".photos-ingest").mkdir(parents=True, exist_ok=True)
    (ws / ".photos-ingest" / "photos-11-handoff.json").write_text("{}")
    wf = cal.GeotagWorkflow(str(ws))
    wf._gpx_fingerprint = "fp"
    return wf


def _gpx(points=()):
    idx = cal.GPXIndex("")
    idx.points = list(points)
    return idx


@pytest.mark.spec("RUL-date_fallback_fills_to_a_day", "RUL-date_fallback_checked", "BLD-date_fallback_cell",
                  test="TST-geotag_date_fallback-a_year_a_month_or_a_day")
def test_a_date_fallback_is_a_year_a_month_or_a_day_the_rest_the_first():
    assert cal.date_fallback_day("1985") == datetime(1985, 1, 1)
    assert cal.date_fallback_day("1985-06") == datetime(1985, 6, 1)
    assert cal.date_fallback_day("1985-06-14") == datetime(1985, 6, 14)
    assert cal.date_fallback_day("2024-02-29") == datetime(2024, 2, 29)
    for bad in ("1985-02-30", "1985-13", "1985-00", "0000", "85", "1985-6", "1985/06", "1985-06-14 00:00",
                "１９８５", 1985, None, ["1985"]):
        assert cal.date_fallback_day(bad) is None, bad


@pytest.mark.spec("RUL-date_fallback_checked", "RUL-invalid_value_stops", "BLD-date_fallback_cell",
                  test="TST-geotag_date_fallback-a_bad_date_is_refused_named")
@pytest.mark.parametrize("bad", ["1985-02-30", "June 1985", 1985, "1985-6"])
def test_a_date_that_is_no_date_is_refused_naming_it(tmp_path, bad):
    _art, blockers = _wf(tmp_path).build_time_decisions([_untimed("scan1.jpg")], GROUPS, _prior({DEST: bad}), _gpx())
    assert len(blockers) == 1 and DEST in blockers[0] and "date_fallback.user_decision.date" in blockers[0]
    assert repr(bad) in blockers[0]


@pytest.mark.spec("RUL-date_fallback_from_nearest", "RUL-date_fallback_applies_itself", "RUL-untimed_photo_stops_geotag",
                  "BLD-date_fallback_cell",
                  test="TST-geotag_date_fallback-the_nearest_date_up_covers_it")
def test_the_date_given_nearest_up_covers_a_folder_and_no_acceptance_is_asked(tmp_path):
    """Given at `Scans`, a container, the date covers `Scans/1985` inside it unasked; one given at `Scans/1985` itself
    wins over it. A folder holding a photo with no time and no date in effect asks; one holding none never does."""
    files = [_untimed("scan1.jpg"), _timed("a.jpg", "2026:07:01 10:00:00", "+02:00", dest=f"{ROOT}/Trip")]
    wf = _wf(tmp_path)
    art, blockers = wf.build_time_decisions(files, GROUPS, _prior({SCANS: "1985"}), _gpx())
    assert not blockers and not art["requires_user_input"]
    cell = art["destinations"][DEST]["date_fallback"]
    assert cell["effective_date"] == {"date": "1985", "filled": "1985-01-01", "set_at": SCANS}
    assert cell["inherited_from"] == SCANS and cell["user_decision"] == {"date": ""}
    assert cell["untimed_photos"] == [f"{DEST}/scan1.jpg"] and not cell["requires_user_input"]
    assert art["destinations"][f"{ROOT}/Trip"]["date_fallback"] == {
        "user_decision": {"date": ""}, "effective_date": None, "requires_user_input": False, "stale_user_decision": False}
    art, _b = wf.build_time_decisions(files, GROUPS, _prior({SCANS: "1985", DEST: "1985-06-14"}), _gpx())
    assert art["destinations"][DEST]["date_fallback"]["effective_date"] == {
        "date": "1985-06-14", "filled": "1985-06-14", "set_at": DEST}
    art, _b = wf.build_time_decisions(files, GROUPS, _prior({}), _gpx())
    cell = art["destinations"][DEST]["date_fallback"]
    assert cell["requires_user_input"] and cell["effective_date"] is None and art["requires_user_input"]


@pytest.mark.spec("RUL-date_fallback_times_untimed", "RUL-date_fallback_fills_to_a_day", "RUL-date_fallback_only_untimed",
                  "BLD-date_fallback_cell", "BLD-resolved_utc",
                  test="TST-geotag_date_fallback-the_untimed_photo_takes_its_days_midnight")
def test_a_photo_with_no_time_takes_its_day_at_midnight_local_and_a_timed_one_keeps_its_own(tmp_path):
    files = [_untimed("scan1.jpg"), _timed("a.jpg", "2026:07:01 10:00:00", "+02:00")]
    art, _b = _wf(tmp_path).build_time_decisions(files, GROUPS, _prior({DEST: "1985-06"}), _gpx())
    rows = {r["relative_path"]: r for r in cal.compute_resolved_utc(files, GROUPS, art)}
    scan = rows[f"{DEST}/scan1.jpg"]                 # 1 June 1985, midnight in Brussels, on summer time
    assert (scan["resolved_utc"], scan["time_rule_used"], scan["resolved_utc_status"]) == (
        "1985-05-31T22:00:00Z", "date_fallback", "valid")
    own = rows[f"{DEST}/a.jpg"]
    assert own["resolved_utc"] == "2026-07-01T08:00:00Z" and own["time_rule_used"] == "smartphone_native_offset"
    # with no date in effect it stays unresolved, as before
    art, _b = _wf(tmp_path).build_time_decisions(files, GROUPS, _prior({}), _gpx())
    assert {r["relative_path"]: r for r in cal.compute_resolved_utc(files, GROUPS, art)}[f"{DEST}/scan1.jpg"][
        "resolved_utc_status"] == "unresolved"


@pytest.mark.spec("RUL-date_fallback_times_untimed", "RUL-ambiguous_local_time_never_guessed", "BLD-date_fallback_cell",
                  "BLD-local_time_readings", test="TST-geotag_date_fallback-a_midnight_its_zone_skips_is_asked")
def test_a_midnight_the_zone_skips_is_asked_never_guessed(tmp_path):
    """São Paulo's clocks went forward at midnight on 2 November 1985: that day has no 00:00. The scan is asked about
    as any time its zone skips, and resolves by the answer."""
    files = [_untimed("scan1.jpg")]
    prior = _prior({DEST: "1985-11-02"}, tz="America/Sao_Paulo")
    wf = _wf(tmp_path)
    art, _b = wf.build_time_decisions(files, GROUPS, prior, _gpx())
    cell = art["destinations"][DEST]["local_time_readings"][f"{DEST}/scan1.jpg"]
    assert cell["case"] == "skipped" and cell["camera_time"] == "1985:11:02 00:00:00" and art["requires_user_input"]
    prior["destinations"][DEST]["local_time_readings"] = {
        f"{DEST}/scan1.jpg": {"content_fingerprint": "fp-scan1.jpg", "user_decision": {"utc_offset_seconds": -10800}}}
    art, _b = wf.build_time_decisions(files, GROUPS, prior, _gpx())
    row = cal.compute_resolved_utc(files, GROUPS, art)[0]
    assert (row["resolved_utc"], row["time_rule_used"]) == ("1985-11-02T03:00:00Z", "local_time_answered")


@pytest.mark.spec("RUL-date_fallback_never_placed_by_tracks", "RUL-unplaced_photo_says_why", "BLD-date_fallback_cell",
                  test="TST-geotag_date_fallback-no_track_places_it_by_its_filled_time")
def test_no_track_places_a_photo_by_the_time_its_date_fallback_gave_it():
    """A track that covers the filled instant exactly places the timed photo, never the scan: the scan falls to its
    folder's fallback, else waits, saying why the tracks did not place it."""
    at = datetime(1985, 5, 31, 22, 0, 0, tzinfo=timezone.utc)
    gpx = _gpx([cal.GPXPoint(50.0, 4.0, at, "t.gpx", 0)])
    timed = dict(_timed("a.jpg", "1985:06:01 00:00:00", "+02:00"))
    assert cal.classify_gps(timed, at, gpx, utils.CONFIG, None, {})[0] == "gpx_interpolation"
    why = {}
    assert cal.classify_gps(_untimed("scan1.jpg"), at, gpx, utils.CONFIG, None, {}, why) == ("blocked", None)
    assert why == {"reason": "time_from_date_fallback"}
    assert cal.classify_gps(_untimed("scan1.jpg"), at, gpx, utils.CONFIG, {"lat": 1.0, "lon": 2.0}, {}) == (
        "manual_fallback", {"lat": 1.0, "lon": 2.0})
    assert cal.GeotagWorkflow.placement_window(
        [_untimed("scan1.jpg")], [{"relative_path": f"{DEST}/scan1.jpg", "resolved_utc_status": "valid",
                                   "resolved_utc": "1985-05-31T22:00:00Z"}]) == []


@pytest.mark.spec("RUL-date_fallback_no_clock_evidence", "BLD-date_fallback_cell",
                  test="TST-geotag_date_fallback-it_is_no_cameras_evidence")
def test_a_photo_with_no_time_reads_no_clock_and_is_in_no_cameras_offset(tmp_path):
    """A scan names its scanner as a camera group: having no time, it reads no clock — solved alone, never in a camera's
    offset cell, and its group is no class question."""
    assert cal.clock_group_key({"camera_group_key": SCANNER, "has_timestamp": False}) == cal.NO_IDENTITY_KEY
    assert cal.clock_group_key({"camera_group_key": SCANNER, "has_timestamp": True}) == SCANNER
    groups, unknown = _wf(tmp_path).recognize_camera_groups([_untimed("scan1.jpg")])
    assert unknown == [] and groups[cal.NO_IDENTITY_KEY]["camera_group_class"] == "unidentified"
    art, _b = _wf(tmp_path).build_time_decisions([_untimed("scan1.jpg")], GROUPS, _prior({DEST: "1985"}), _gpx())
    d = art["destinations"][DEST]
    assert d["camera_group_time_decisions"] == {} and "unidentified_files" not in d


@pytest.mark.spec("RUL-date_fallback_names_in_name_order", "BLD-rename_planning",
                  test="TST-geotag_date_fallback-suffixed_in_the_order_of_their_names")
def test_photos_sharing_the_filled_date_are_suffixed_in_the_order_of_their_names():
    """Three scans of one date take its name and suffixes in the order of the names they hold — compared as text, so
    `scan10` comes before `scan2`, as a listing shows them."""
    fmt = utils.CONFIG["filename_timestamp_format"]
    rows = [{"relative_path": f"{DEST}/{n}", "resolved_utc": "1985-05-31T22:00:00Z", "destination_timezone":
             "Europe/Brussels", "sub_second": None, "source_naive_time": None}
            for n in ("scan2.jpg", "scan10.jpg", "scan1.jpg")]
    named = {r["current_name"]: r["planned_name"] for r in cal.plan_renames(rows, fmt)}
    stem = "1985-06-01--00-00-00"
    assert named == {"scan1.jpg": f"{stem}.jpg", "scan10.jpg": f"{stem}-001.jpg", "scan2.jpg": f"{stem}-002.jpg"}


@pytest.mark.spec("RUL-date_fallback_recorded", "BLD-geotag_log_steps", "BLD-log_format",
                  test="TST-geotag_date_fallback-the_log_records_the_date_as_given")
def test_the_log_records_the_date_fallback_as_given_and_where():
    op = {"type": "metadata_time_write", "relative_path": f"{DEST}/scan1.jpg",
          "preconditions": {"content_fingerprint": "fp-scan1.jpg"},
          "writes": {"DateTimeOriginal": "1985:06:01 00:00:00", "OffsetTimeOriginal": "+02:00"},
          "provenance": {"resolved_utc": "1985-05-31T22:00:00Z", "time_rule_used": "date_fallback",
                         "because": f"photos-21 destinations.{SCANS}.date_fallback",
                         "date_fallback": {"date": "1985-06", "filled": "1985-06-01", "set_at": SCANS}}}
    plan = {"plan_id": "p1", "destinations": {DEST: {"operations": [op]}}, "depends_on": {}}
    rows = [{"relative_path": f"{DEST}/scan1.jpg", "resolved_utc": "1985-05-31T22:00:00Z",
             "time_rule_used": "date_fallback"}]
    photos = cal.build_complete_log({}, [_untimed("scan1.jpg")], rows, {}, plan)
    step = next(s for s in photos["fp-scan1.jpg"]["journey"] if s["action"] == "date_fallback_applied")
    assert step == {"phase": "geotag", "action": "date_fallback_applied", "value": "1985-06", "filled": "1985-06-01",
                    "because": f"photos-21 destinations.{SCANS}.date_fallback", "run": "p1"}
    # an earlier executed pass's write says it too
    op["operation_id"] = "op1"
    earlier = _calc._earlier_pass_steps(plan, {"op1"})
    assert any(s["action"] == "date_fallback_applied" and s["value"] == "1985-06" for s in earlier["fp-scan1.jpg"])


@pytest.mark.spec("RUL-date_fallback_times_untimed", "BLD-decided_from_own_values", "BLD-date_fallback_cell",
                  test="TST-geotag_date_fallback-a_written_scan_is_decided_from_its_own_values")
def test_a_scan_geotag_wrote_is_decided_again_from_its_own_values_untimed(tmp_path):
    """Once written, the scan holds the filled time — but geotag decides it from the values pinned before its first
    write, which held none: the date fallback times it again, and the time it holds is geotag's, asked nothing."""
    pair = {"DateTimeOriginal": "1985:06:01 00:00:00", "OffsetTimeOriginal": "+02:00"}
    now = dict(_timed("scan1.jpg", pair["DateTimeOriginal"], pair["OffsetTimeOriginal"]),
               camera_group_key=SCANNER, raw_times=dict(pair), processing_method="")
    original = {"selected_source_naive_timestamp": None, "selected_source_timestamp_tag": None}
    f = dict(cal.from_originals(now, original), times_written=[pair])
    assert cal.untimed(f) and cal.clock_group_key(f) == cal.NO_IDENTITY_KEY and cal.changed_time(f) is None
    art, _b = _wf(tmp_path).build_time_decisions([dict(f, camera_group_key=cal.NO_IDENTITY_KEY)], GROUPS,
                                                 _prior({DEST: "1985-06"}), _gpx())
    assert cal.date_fallback_time(f, art["destinations"][DEST]) == datetime(1985, 6, 1)


# --- through `geotag plan` -----------------------------------------------------------------------------------

def _workspace(tmp_path):
    ws = tmp_path / "ws"; ws.mkdir()
    for d in ["0-sources", "1-strays", "2-missing-metadata", "3-redundant-jpgs",
              "4-videos-by-date", "5-photos-by-date", "6-photos-by-dest"]:
        (ws / d).mkdir()
    ctl = ws / ".photos-ingest"; ctl.mkdir()
    (ctl / "photos-00-workspace-guard").touch()
    cfg = {k: v for k, v in utils.CONFIG.items() if k != "jobs"}
    cfg["gpx_root"] = ""
    cfg["camera_time_and_timezone_policy"] = dict(
        cfg["camera_time_and_timezone_policy"], device_groups={"fixed_clock_cameras": [], "phones": [PHONE]})
    (ctl / "photos-00-config.json").write_text(json.dumps(cfg))
    answer_root_zone(ctl, "Europe/Brussels")

    def rec(rel, dto=None, offset=None, group=PHONE):
        parsed = {"camera_group_key": group, "has_timestamp": dto is not None}
        if dto:
            parsed.update({"DateTimeOriginal": dto, "selected_source_naive_timestamp": dto,
                           "selected_source_timestamp_tag": "DateTimeOriginal", "OffsetTimeOriginal": offset})
        return {"relative_path": rel, "media_class": "image", "folder_class": ROOT,
                "size": 1, "mtime_ns": 1, "content_hash": json.dumps({"value": "fp" + rel, "status": "valid"}),
                "metadata_status": {"camera_group_key_version": utils.CAMERA_GROUP_KEY_VERSION,
                                    "camera_group_key": group, "has_timestamp": dto is not None,
                                    "field_set_version": utils.FIELD_SET_VERSION, "parsed_json": json.dumps(parsed)}}

    files = [rec(f"{DEST}/a.jpg", "2026:07:01 10:00:00", "+02:00"),
             rec(f"{DEST}/scan2.jpg", group=SCANNER), rec(f"{DEST}/scan10.jpg", group=SCANNER)]
    for f in files:
        p = ws / f["relative_path"]; p.parent.mkdir(parents=True, exist_ok=True); p.write_bytes(b"x")
    (ctl / "photos-11-handoff.json").write_text(json.dumps(vouched(ctl.parent, {
        "filename_timestamp_format": utils.CONFIG["filename_timestamp_format"], "files": match_disk(ws, files),
        "cache_fingerprint": "pcf",
        "depends_on": {"cache": {"fingerprint_algorithm_version": utils.FINGERPRINT_ALGORITHM_VERSION}}})))
    return ws, ctl


def _plan(monkeypatch, ws):
    monkeypatch.chdir(str(ws))
    monkeypatch.setattr(sys, "argv", ["photos-2-geotag", "plan"])
    try:
        cal.main()
    except SystemExit as e:
        return e.code
    return 0


def _edit(path, fn):
    rec = json.loads(path.read_text())
    fn(rec)
    path.write_text(json.dumps(rec))


@pytest.mark.spec("RUL-time_before_gps", "RUL-untimed_photo_stops_geotag", "RUL-untimed_photo_named",
                  "RUL-every_question_answerable_by_hand",
                  "RUL-date_fallback_time_written", "RUL-date_fallback_recorded", "RUL-date_fallback_only_untimed",
                  "RUL-date_fallback_names_in_name_order", "RUL-date_fallback_never_placed_by_tracks",
                  "BLD-geotag_untimed_gate", "BLD-date_fallback_cell", "BLD-editor_answers_every_question",
                  test="TST-geotag_date_fallback-geotag_plan_asks_then_writes_the_date")
def test_geotag_plan_stops_on_a_photo_with_no_time_then_writes_the_date_given_its_folder(tmp_path, monkeypatch, capsys):
    """Two scans with no time beside a phone's photo: the first plan writes photos-21, asks for their folder's date and
    stops, naming them, nothing past photos-21 written. The date given by hand at the folder above, the plan goes on;
    their position given by the folder fallback, photos-24 writes each scan's filled time — local, with its offset —
    and names them by it in the order of their names, the date as given recorded with the write. The phone's photo
    keeps its own time."""
    ws, ctl = _workspace(tmp_path)
    assert _plan(monkeypatch, ws) == 2
    err = capsys.readouterr().err
    assert "no recorded time" in err and "scan10.jpg" in err and "scan2.jpg" in err and "a.jpg" not in err.replace(
        "scan2.jpg", "").replace("scan10.jpg", "")
    assert "date fallback" in err and "2-missing-metadata" in err
    t21 = ctl / "photos-21-time-decisions.json"
    cell = json.loads(t21.read_text())["destinations"][DEST]["date_fallback"]
    assert cell["requires_user_input"] and cell["untimed_photos"] == [f"{DEST}/scan10.jpg", f"{DEST}/scan2.jpg"]
    assert not (ctl / "photos-22-gps-drift-validation.json").exists()

    _edit(t21, lambda r: r["destinations"][SCANS]["date_fallback"]["user_decision"].update(date="1985-06"))
    _plan(monkeypatch, ws)
    t = json.loads(t21.read_text())
    assert t["status"] == "complete"
    assert t["destinations"][DEST]["date_fallback"]["effective_date"] == {
        "date": "1985-06", "filled": "1985-06-01", "set_at": SCANS}
    g23 = ctl / "photos-23-gps-decisions.json"
    g = json.loads(g23.read_text())
    reasons = {ri["relative_path"]: (ri.get("tracks") or {}).get("reason")
               for ri in g["destinations"][DEST]["gps_decisions"]["review_items"]}
    assert reasons[f"{DEST}/scan2.jpg"] == "time_from_date_fallback"
    _edit(g23, lambda r: r["destinations"][DEST]["folder_fallback"]["user_decision"].update(
        fallback_lat=50.85, fallback_lon=4.35))
    _plan(monkeypatch, ws)
    plan = json.loads((ctl / "photos-24-executable-plan.json").read_text())
    assert plan["status"] == "ready", plan.get("blockers")
    ops = plan["destinations"][DEST]["operations"]
    times = {o["relative_path"]: o for o in ops if o["type"] == "metadata_time_write"}
    scan = times[f"{DEST}/scan2.jpg"]
    assert scan["writes"]["DateTimeOriginal"] == "1985:06:01 00:00:00" and scan["writes"]["OffsetTimeOriginal"] == "+02:00"
    assert scan["provenance"]["time_rule_used"] == "date_fallback"
    assert scan["provenance"]["date_fallback"] == {"date": "1985-06", "filled": "1985-06-01", "set_at": SCANS}
    assert scan["provenance"]["because"] == f"photos-21 destinations.{SCANS}.date_fallback"
    assert f"{DEST}/a.jpg" not in times                       # its own time, held already: nothing to write
    renames = {o["relative_path"].rsplit("/", 1)[1]: o["to"] for o in ops if o["type"] == "rename_no_clobber"}
    assert (renames["scan10.jpg"], renames["scan2.jpg"]) == ("1985-06-01--00-00-00.jpg", "1985-06-01--00-00-00-001.jpg")
    assert renames["a.jpg"] == "2026-07-01--10-00-00.jpg"
    gps = {o["relative_path"]: o for o in ops if o["type"] == "metadata_gps_write"}
    assert gps[f"{DEST}/scan2.jpg"]["gps_origin"] == "apply_manual"
