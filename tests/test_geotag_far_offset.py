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

"""Geotag — a guessed clock offset that puts a day's photos where nothing else was (RUL-offset_far_from_evidence_asks).

A camera whose battery ran out reads its factory date. The timezone's guess, or the offset it records, moves it a few
hours; accepted, it would write the year 2000 into the originals. Set against the destination's photos of other
devices whose time is known, and the track points, such a guess does not take effect on acceptance: the cell asks for
an offset of the user's own. With no other device's photo there, nothing can tell, and nothing changes. In-process.
"""
from datetime import datetime, timezone

import pytest

import photos_2_geotag as cal
import photos_utils as utils

CAM, OTHER, PHONE, NOBODY = "CANON|EOS 5D|7", "SONY|ILCE-6400|9", "Apple|iPhone 15|", "unknown"
GROUPS = {CAM: {"camera_group_class": "camera"}, OTHER: {"camera_group_class": "camera"},
          PHONE: {"camera_group_class": "smartphone"}, NOBODY: {"camera_group_class": "unidentified"}}
DEST = "6-photos-by-dest/Bruges"
ZONE = {"destination_timezone": {"user_decision": {"manual_iana_timezone": "Europe/Brussels"}}}


def _gpx(points=()):
    idx = cal.GPXIndex("")
    idx.points = list(points)
    return idx


def _pt(when):
    return cal.GPXPoint(51.2, 3.2, when, "t.gpx", 0)


def _photo(name, naive, key=CAM, offset=None):
    return {"relative_path": f"{DEST}/{name}", "destination": DEST, "camera_group_key": key, "native_gps": None,
            "has_native_gps": False, "has_timestamp": True, "source_naive_time": naive,
            "source_time_tag": "EXIF:DateTimeOriginal",
            "raw_times": {"OffsetTimeOriginal": offset} if offset else {}}


RESET = [_photo("a.cr2", "2000:01:01 10:00:00"), _photo("b.cr2", "2000:01:01 10:20:00")]
PHONE_THEN = [_photo("p.heic", "2026:05:01 14:00:00", PHONE, "+02:00")]


def _wf(tmp_path):
    ws = tmp_path / "ws"
    (ws / ".photos-ingest").mkdir(parents=True)
    (ws / ".photos-ingest" / "photos-11-handoff.json").write_text("{}")
    wf = cal.GeotagWorkflow(str(ws))
    wf._gpx_fingerprint = "fp"
    return wf


def _prior(**cells):
    d = dict(ZONE)
    if cells:
        d["camera_group_time_decisions"] = {k: {"user_decision": ud} for k, ud in cells.items()}
    return {"destinations": {DEST: d}}


def _accept(offset):
    return {"accept_proposal": True, "accepted_offset_seconds": offset, "manual_offset_seconds": ""}


def _cell(wf, files, prior, gpx=None, key=CAM):
    art, blockers = wf.build_time_decisions(files, GROUPS, prior, gpx or _gpx())
    assert not blockers, blockers
    return art["destinations"][DEST]["camera_group_time_decisions"][key], art


@pytest.mark.spec("RUL-offset_far_from_evidence_asks", "BLD-offset_far_from_evidence",
                  test="TST-geotag_far_offset-a_reset_clock_asks_for_an_offset")
def test_a_reset_clock_s_accepted_guess_asks_for_an_offset(tmp_path):
    """The camera reads 2000-01-01; a phone's photo of Bruges says 2026. The zone's guess, accepted, does not take
    effect: the cell asks, its proposal still shown with why. An offset the user writes takes effect as ever."""
    wf = _wf(tmp_path)
    cell, art = _cell(wf, RESET + PHONE_THEN, _prior(**{CAM: _accept(-3600)}))
    p = cell["proposal"]
    assert p["proposal_source"] == "timezone_naive" and p["proposed_offset_seconds"] == -3600
    assert cell["effective_time_anchor"] == "" and cell["requires_user_input"] and art["requires_user_input"]
    assert not cell["stale_user_decision"] and cell["user_decision"]["accept_proposal"] is True   # left as written
    why = p["far_from_evidence"]
    assert why["other_photos"] == 1 and why["nearest_other_photo"] == f"{DEST}/p.heic"
    assert why["max_clock_error_seconds"] == utils.CONFIG["gpx_anchor_max_clock_error_seconds"]
    assert why["nearest_other_photo_seconds"] > 26 * 365 * 86400 and why["nearest_track_seconds"] == ""
    # the true time of one photo, as an offset of the user's own
    manual = 820_000_000
    cell, _ = _cell(wf, RESET + PHONE_THEN, _prior(**{CAM: {"accept_proposal": False, "accepted_offset_seconds": "",
                                                            "manual_offset_seconds": manual}}))
    assert cell["effective_time_anchor"] == {"offset_seconds": manual, "source": "manual"}
    assert "far_from_evidence" in cell["proposal"]          # still says why it was not to be accepted


@pytest.mark.spec("RUL-offset_far_from_evidence_asks", "BLD-offset_far_from_evidence",
                  test="TST-geotag_far_offset-a_recorded_offset_far_from_all_asks")
def test_the_recorded_offset_and_the_track_check_are_held_the_same_way(tmp_path):
    """The offset a reset camera records is held like the zone's: accepted, it does not take effect. And a guess bound
    for the check against the tracks, with tracks by its recorded times but none by the times it gives, is withdrawn
    too — the check is an acceptance, and acceptance is not enough here."""
    wf = _wf(tmp_path)
    recorded = [dict(f, raw_times={"OffsetTimeOriginal": "+09:00"}) for f in RESET]
    cell, _ = _cell(wf, recorded + PHONE_THEN, _prior(**{CAM: _accept(-32400)}))
    assert cell["proposal"]["proposal_source"] == "recorded_offset" and cell["effective_time_anchor"] == ""
    assert cell["proposal"]["far_from_evidence"]["other_photos"] == 1
    utils.CONFIG["gpx_anchor_max_clock_error_seconds"] = 3600.0
    utils.CONFIG["drift_check_track_window_seconds"] = 7200.0
    track = [_pt(datetime(2000, 1, 1, 10, 0, tzinfo=timezone.utc))]       # by the camera times read as UTC only
    cell, _ = _cell(wf, recorded + PHONE_THEN, _prior(), _gpx(track))
    assert cell["effective_time_anchor"] == "" and "decision_mode" not in cell and cell["requires_user_input"]
    assert cell["proposal"]["far_from_evidence"]["nearest_track_seconds"] == 8 * 3600 + 40 * 60   # b.cr2, at 01:20Z


@pytest.mark.spec("RUL-offset_far_from_evidence_asks", "BLD-offset_far_from_evidence",
                  test="TST-geotag_far_offset-near_any_evidence_unchanged")
def test_a_guess_near_any_evidence_takes_effect_as_before(tmp_path):
    """A phone's photo within the largest clock error, or a track point there, is enough: the accepted guess takes
    effect, the proposal unmarked."""
    wf = _wf(tmp_path)
    day = [_photo("a.cr2", "2026:05:01 10:00:00"), _photo("b.cr2", "2026:05:01 11:00:00")]
    near_phone = [_photo("p.heic", "2026:05:02 20:00:00", PHONE, "+02:00")]
    cell, _ = _cell(wf, day + near_phone, _prior(**{CAM: _accept(-7200)}))
    assert cell["effective_time_anchor"] == {"offset_seconds": -7200, "source": "timezone_accepted"}
    assert "far_from_evidence" not in cell["proposal"]
    # the phone far, but a track by the times the guess gives
    far_phone = [_photo("p.heic", "2026:08:01 12:00:00", PHONE, "+02:00")]
    track = [_pt(datetime(2026, 5, 2, 9, 0, tzinfo=timezone.utc))]
    cell, _ = _cell(wf, day + far_phone, _prior(**{CAM: _accept(-7200)}), _gpx(track))
    assert cell["effective_time_anchor"]["source"] in ("timezone_accepted", "timezone_unconfirmed")
    assert "far_from_evidence" not in cell["proposal"]


@pytest.mark.spec("RUL-offset_far_from_evidence_asks", "BLD-offset_far_from_evidence",
                  test="TST-geotag_far_offset-no_evidence_nothing_changes")
def test_with_no_other_device_s_photo_nothing_can_tell(tmp_path):
    """No other device's photo of the destination whose time is known: a reset clock is not told from a trip with no
    tracks — tracks of other years lying far from both — and the guess is taken on acceptance, as before. A file
    naming no device, and another camera whose offset is only a guess, are no such photo; a camera whose offset the
    user wrote is."""
    wf = _wf(tmp_path)
    old_tracks = _gpx([_pt(datetime(2019, 6, 1, 12, 0, tzinfo=timezone.utc))])
    cell, _ = _cell(wf, RESET, _prior(**{CAM: _accept(-3600)}), old_tracks)
    assert cell["effective_time_anchor"] == {"offset_seconds": -3600, "source": "timezone_accepted"}
    nobody = [_photo("x.jpg", "2026:05:01 14:00:00", NOBODY, "+02:00")]
    guessed = [_photo("o.arw", "2026:05:01 15:00:00", OTHER)]
    files = RESET + nobody + guessed
    cell, _ = _cell(wf, files, _prior(**{CAM: _accept(-3600), OTHER: _accept(-7200)}))
    assert cell["effective_time_anchor"] == {"offset_seconds": -3600, "source": "timezone_accepted"}
    other, _ = _cell(wf, files, _prior(**{CAM: _accept(-3600), OTHER: _accept(-7200)}), key=OTHER)
    assert other["effective_time_anchor"]["source"] == "timezone_accepted"   # nor is the reset camera evidence for it
    settled = {"accept_proposal": False, "accepted_offset_seconds": "", "manual_offset_seconds": -7200}
    cell, _ = _cell(wf, files, _prior(**{CAM: _accept(-3600), OTHER: settled}))
    assert cell["effective_time_anchor"] == "" and cell["proposal"]["far_from_evidence"]["nearest_other_photo"] == f"{DEST}/o.arw"


@pytest.mark.spec("BLD-offset_far_from_evidence", test="TST-geotag_far_offset-measures_the_nearest_of_each")
def test_far_from_evidence_measures_the_nearest_of_each():
    """The pure check: nothing to tell by → None; anything within the bound → None; else how far the nearest lies."""
    t = lambda *a: datetime(*a, tzinfo=timezone.utc)
    times = [t(2000, 1, 1, 9), t(2000, 1, 1, 10)]
    others = [("p", t(2026, 5, 1, 12)), ("q", t(2000, 1, 5, 10))]
    assert cal.far_from_evidence(times, [], [t(2000, 1, 1, 9)], 3600) is None
    assert cal.far_from_evidence(times, others, [t(2000, 1, 1, 10, 30)], 3600) is None
    why = cal.far_from_evidence(times, others, [t(1999, 12, 30, 9)], 3600)
    assert why["nearest_other_photo"] == "q" and why["nearest_other_photo_seconds"] == 4 * 86400
    assert why["nearest_track_seconds"] == 2 * 86400 and why["other_photos"] == 2
    assert cal.far_from_evidence(times, others, [], 4 * 86400) is None
