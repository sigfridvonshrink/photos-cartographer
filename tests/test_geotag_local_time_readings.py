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

"""Geotag — a local time a daylight-saving change skips or repeats, answered in photos-21
(RUL-ambiguous_local_time_answered).

A photo read through its destination's zone at 02:30 on the night clocks change reads two ways. Geotag never guesses:
it asks, per photo, in the time decisions — which reading for a time shown twice, the offset for one never shown —
and the photo resolves by the answer. The answer is the photo's, found again by its fingerprint. In-process, and once
through `geotag plan`.
"""
import json
import sys

import pytest

from _handoff import match_disk, vouched
from _zone import answer_root_zone

import photos_2_geotag as cal
import photos_utils as utils

PHONE = "APPLE|iPhone|p1"
GROUPS = {PHONE: {"camera_group_class": "smartphone"}}
DEST = "6-photos-by-dest/B"
BERLIN = {"destinations": {DEST: {"destination_timezone": {"user_decision": {"manual_iana_timezone": "Europe/Berlin"}}}}}


def _photo(name, naive, offset=None, fp=None):
    return {"relative_path": f"{DEST}/{name}", "destination": DEST, "camera_group_key": PHONE, "native_gps": None,
            "has_native_gps": False, "has_timestamp": True, "source_naive_time": naive,
            "source_time_tag": "EXIF:DateTimeOriginal", "content_fingerprint": fp or "fp-" + name,
            "raw_times": {"OffsetTimeOriginal": offset} if offset else {}}


# A tagged photo of the same phone and day at the zone's offset reads its untagged photos by the zone, unasked.
TWICE = [_photo("twice.jpg", "2026:10:25 02:30:00"), _photo("later.jpg", "2026:10:25 09:00:00", "+01:00")]
SKIP = [_photo("skip.jpg", "2026:03:29 02:30:00"), _photo("later.jpg", "2026:03:29 09:00:00", "+02:00")]


def _wf(tmp_path):
    ws = tmp_path / "ws"
    (ws / ".photos-ingest").mkdir(parents=True, exist_ok=True)
    (ws / ".photos-ingest" / "photos-11-handoff.json").write_text("{}")
    wf = cal.GeotagWorkflow(str(ws))
    wf._gpx_fingerprint = "fp"
    return wf


def _gpx():
    idx = cal.GPXIndex("")
    idx.points = []
    return idx


def _answer(rel, value, fp=None):
    out = json.loads(json.dumps(BERLIN))
    out["destinations"][DEST]["local_time_readings"] = {
        rel: {"content_fingerprint": fp or "fp-" + rel.rsplit("/", 1)[-1], "user_decision": {"utc_offset_seconds": value}}}
    return out


def _build(wf, files, prior=BERLIN):
    art, blockers = wf.build_time_decisions(files, GROUPS, prior, _gpx())
    return art, blockers


@pytest.mark.spec("RUL-ambiguous_local_time_answered", "RUL-ambiguous_local_time_never_guessed", "BLD-local_time_readings",
                  test="TST-geotag_local_time_readings-asked_with_both_readings")
def test_a_time_shown_twice_is_asked_with_both_readings(tmp_path):
    """02:30 on 25 October 2026 happened twice in Berlin: photos-21 asks for the photo, naming both readings, and is
    not complete; the photo resolves to nothing until answered."""
    art, blockers = _build(_wf(tmp_path), TWICE)
    assert not blockers
    cell = art["destinations"][DEST]["local_time_readings"][f"{DEST}/twice.jpg"]
    assert cell["case"] == "repeated" and cell["offsets_seconds"] == [7200, 3600]
    assert cell["readings_utc"] == ["2026-10-25T00:30:00Z", "2026-10-25T01:30:00Z"]
    assert cell["timezone"] == "Europe/Berlin" and cell["camera_time"] == "2026:10:25 02:30:00"
    assert cell["user_decision"] == {"utc_offset_seconds": ""} and cell["requires_user_input"]
    assert art["requires_user_input"] and list(art["destinations"][DEST]["local_time_readings"]) == [f"{DEST}/twice.jpg"]
    rows = {r["relative_path"]: r for r in cal.compute_resolved_utc(TWICE, GROUPS, art)}
    assert rows[f"{DEST}/twice.jpg"]["time_rule_used"] == "local_time_repeated"


@pytest.mark.spec("RUL-ambiguous_local_time_answered", "RUL-repeated_time_answered_by_a_reading", "BLD-local_time_readings",
                  "BLD-resolved_utc", test="TST-geotag_local_time_readings-a_reading_answers_it")
def test_a_reading_answers_a_time_shown_twice_and_no_other_value_does(tmp_path):
    wf = _wf(tmp_path)
    art, _b = _build(wf, TWICE, _answer(f"{DEST}/twice.jpg", 3600))
    cell = art["destinations"][DEST]["local_time_readings"][f"{DEST}/twice.jpg"]
    assert cell["effective_utc_offset_seconds"] == 3600 and not cell["requires_user_input"]
    assert not art["requires_user_input"]
    r = {r["relative_path"]: r for r in cal.compute_resolved_utc(TWICE, GROUPS, art)}[f"{DEST}/twice.jpg"]
    assert (r["resolved_utc"], r["time_rule_used"], r["utc_offset_used"]) == ("2026-10-25T01:30:00Z",
                                                                               "local_time_answered", 3600)
    art, _b = _build(wf, TWICE, _answer(f"{DEST}/twice.jpg", 0))            # not one of its readings
    cell = art["destinations"][DEST]["local_time_readings"][f"{DEST}/twice.jpg"]
    assert cell["stale_user_decision"] and cell["requires_user_input"] and cell["user_decision"]["utc_offset_seconds"] == 0
    _art, blockers = _build(wf, TWICE, _answer(f"{DEST}/twice.jpg", "+01:00"))
    assert any("utc_offset_seconds must be a whole number" in b for b in blockers)


@pytest.mark.spec("RUL-ambiguous_local_time_answered", "BLD-local_time_readings",
                  test="TST-geotag_local_time_readings-an_offset_answers_a_skipped_time")
def test_an_offset_answers_a_time_never_shown(tmp_path):
    """02:30 on 29 March 2026 never happened in Berlin: the photo's offset answers it — either reading, or another."""
    wf = _wf(tmp_path)
    for given, utc in ((3600, "2026-03-29T01:30:00Z"), (7200, "2026-03-29T00:30:00Z"), (0, "2026-03-29T02:30:00Z")):
        art, blockers = _build(wf, SKIP, _answer(f"{DEST}/skip.jpg", given))
        assert not blockers and not art["requires_user_input"]
        r = {r["relative_path"]: r for r in cal.compute_resolved_utc(SKIP, GROUPS, art)}[f"{DEST}/skip.jpg"]
        assert r["resolved_utc"] == utc


@pytest.mark.spec("RUL-ambiguous_local_time_answered", "RUL-photo_decision_never_passes_by_name", "BLD-local_time_readings",
                  test="TST-geotag_local_time_readings-the_answer_is_the_photos")
def test_the_answer_follows_the_photo_never_its_name(tmp_path):
    """Renamed, the photo keeps its answer (its fingerprint); another photo taking its name does not take it."""
    wf = _wf(tmp_path)
    moved = [_photo("renamed.jpg", "2026:10:25 02:30:00", fp="fp-twice.jpg"), TWICE[1]]
    art, _b = _build(wf, moved, _answer(f"{DEST}/twice.jpg", 3600))
    assert art["destinations"][DEST]["local_time_readings"][f"{DEST}/renamed.jpg"]["effective_utc_offset_seconds"] == 3600
    other = [_photo("twice.jpg", "2026:10:25 02:30:00", fp="fp-another"), TWICE[1]]
    art, _b = _build(wf, other, _answer(f"{DEST}/twice.jpg", 3600))
    assert art["destinations"][DEST]["local_time_readings"][f"{DEST}/twice.jpg"]["requires_user_input"]


@pytest.mark.spec("RUL-ambiguous_local_time_answered", "BLD-local_time_readings", "RUL-every_question_answerable_by_hand",
                  "BLD-editor_answers_every_question", test="TST-geotag_local_time_readings-geotag_plan_asks_then_plans")
def test_geotag_plan_asks_in_photos_21_then_plans_once_answered(tmp_path, monkeypatch, capsys):
    """Through `geotag plan`: the phone's photo at 02:30 on the night Berlin's clocks went back is asked about in
    photos-21, nothing past it written; answered there by hand, the plan goes on."""
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
    answer_root_zone(ctl, "Europe/Berlin")

    def rec(rel, dto, offset=None):
        parsed = {"DateTimeOriginal": dto, "selected_source_naive_timestamp": dto,
                  "selected_source_timestamp_tag": "DateTimeOriginal", "camera_group_key": PHONE, "has_timestamp": True}
        if offset:
            parsed["OffsetTimeOriginal"] = offset
        return {"relative_path": rel, "media_class": "image", "folder_class": "6-photos-by-dest",
                "size": 1, "mtime_ns": 1, "content_hash": json.dumps({"value": "fp" + rel, "status": "valid"}),
                "metadata_status": {"camera_group_key_version": utils.CAMERA_GROUP_KEY_VERSION,
                                    "camera_group_key": PHONE, "has_timestamp": True,
                                    "field_set_version": utils.FIELD_SET_VERSION, "parsed_json": json.dumps(parsed)}}

    files = [rec(f"{DEST}/later.jpg", "2026:10:25 09:00:00", "+01:00"), rec(f"{DEST}/twice.jpg", "2026:10:25 02:30:00")]
    for f in files:
        p = ws / f["relative_path"]; p.parent.mkdir(parents=True, exist_ok=True); p.write_bytes(b"x")
    (ctl / "photos-11-handoff.json").write_text(json.dumps(vouched(ctl.parent, {
        "filename_timestamp_format": utils.CONFIG["filename_timestamp_format"], "files": match_disk(ws, files),
        "cache_fingerprint": "pcf",
        "depends_on": {"cache": {"fingerprint_algorithm_version": utils.FINGERPRINT_ALGORITHM_VERSION}}})))
    monkeypatch.chdir(str(ws))
    monkeypatch.setattr(sys, "argv", ["photos-2-geotag", "plan"])

    def plan():
        try:
            cal.main()
        except SystemExit as e:
            return e.code

    plan()
    t = json.loads((ctl / "photos-21-time-decisions.json").read_text())
    assert t["requires_user_input"] and not (ctl / "photos-22-gps-drift-validation.json").exists()
    cell = t["destinations"][DEST]["local_time_readings"][f"{DEST}/twice.jpg"]
    cell["user_decision"]["utc_offset_seconds"] = 7200                          # answered by hand
    (ctl / "photos-21-time-decisions.json").write_text(json.dumps(t))
    plan()
    t = json.loads((ctl / "photos-21-time-decisions.json").read_text())
    assert t["status"] == "complete" and (ctl / "photos-22-gps-drift-validation.json").exists()


CAM = "SONY|ILCE-7M4|42"


@pytest.mark.spec("RUL-camera_zone_offset_for_the_day", "BLD-timezone_naive_offset",
                  test="TST-geotag_local_time_readings-a_cameras_zone_offset_holds_for_its_day")
def test_a_cameras_zone_offset_is_the_one_at_its_days_earliest_time(tmp_path):
    """A camera's photos of 25 October 2026 in Berlin, at 01:00 (summer time) and 05:00 (winter time): the zone's
    offset is proposed at the earliest, −7200, and once accepted every photo of the day takes it — a camera's clock
    does not change at the switch. No photo of the day is asked about as a phone's would be."""
    groups = {CAM: {"camera_group_class": "camera"}}
    files = [dict(_photo("a.arw", "2026:10:25 01:00:00"), camera_group_key=CAM),
             dict(_photo("b.arw", "2026:10:25 05:00:00"), camera_group_key=CAM)]
    prior = json.loads(json.dumps(BERLIN))
    prior["destinations"][DEST]["camera_group_time_decisions"] = {CAM: {"user_decision": {
        "accept_proposal": True, "accepted_offset_seconds": -7200, "manual_offset_seconds": ""}}}
    art, blockers = _wf(tmp_path).build_time_decisions(files, groups, prior, _gpx())
    assert not blockers
    cell = art["destinations"][DEST]["camera_group_time_decisions"][CAM]
    assert cell["proposal"]["proposal_source"] == "timezone_naive" and cell["proposal"]["proposed_offset_seconds"] == -7200
    assert "local_time_readings" not in art["destinations"][DEST]
    rows = cal.compute_resolved_utc(files, groups, art)
    assert [r["resolved_utc"] for r in rows] == ["2026-10-24T23:00:00Z", "2026-10-25T03:00:00Z"]
    assert {r["utc_offset_used"] for r in rows} == {-7200}
