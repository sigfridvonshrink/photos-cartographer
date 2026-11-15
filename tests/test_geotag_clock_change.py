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

"""Geotag — a camera's clock changed during the day (BLD-clock_change_split).

A camera set to local time at lunch has two offsets that day. Its photos holding their own position, in camera-time
order, form two consecutive runs each agreeing on its own offset: geotag proposes splitting the day's cell at the
change; accepted once, the day is decided as two parts, each by its own photos, and the photos with no GPS between
the runs are asked about — which was the first after the change. From conftest.py.
"""
import copy
from datetime import datetime, timedelta, timezone

import pytest

import photos_2_geotag as cal
import photos_utils as utils
from _zone import with_root_zone

BYDEST = "6-photos-by-dest"
DEST = f"{BYDEST}/Kyoto"
CAM = "SONY|ILCE-6400|123"
GROUPS = {CAM: {"camera_group_key": CAM, "camera_group_class": "camera"}}


def _gpx(points):
    idx = cal.GPXIndex("")
    idx.points = list(points)
    idx.file_sha = {"trip.gpx": "sha"}
    return idx


def _wf(tmp_path):
    ws = tmp_path / "ws"
    (ws / ".photos-ingest").mkdir(parents=True)
    (ws / ".photos-ingest" / "photos-11-handoff.json").write_text("{}")
    wf = cal.GeotagWorkflow(str(ws))
    wf._gpx_fingerprint = "fp"
    return wf


def _cam(utc, offset):
    """The camera time a photo taken at `utc` shows on a clock `offset` seconds from UTC (camera + offset = UTC)."""
    return (utc - timedelta(seconds=offset)).strftime("%Y:%m:%d %H:%M:%S")


def _day(offsets, between=(), day=3):
    """A walk, one track point every half hour from 08:00 UTC on 3 July 2024 (each 1 km from the last), a photo at each
    point taken on a clock at the given offset — `None` for a pause of three hours with no point — and photos with no
    position at the camera times in `between`. Returns (track, photos)."""
    pts, photos, t, n = [], [], datetime(2024, 7, day, 8, 0, tzinfo=timezone.utc), 0
    for off in offsets:
        if off is None:
            t += timedelta(hours=3)
            continue
        lat, lon = 35.0 + n * 0.01, 135.0 + (day - 3) * 0.5      # each day a walk of its own
        pts.append(cal.GPXPoint(lat, lon, t, "trip.gpx", 0))
        photos.append({"relative_path": f"{DEST}/p{day}-{n:02d}.arw", "destination": DEST, "camera_group_key": CAM,
                       "native_gps": {"lat": lat, "lon": lon}, "has_native_gps": True, "has_timestamp": True,
                       "source_naive_time": _cam(t, off), "content_fingerprint": f"fp{day}-{n}"})
        t += timedelta(minutes=30)
        n += 1
    for i, naive in enumerate(between):
        photos.append({"relative_path": f"{DEST}/q{day}-{i:02d}.arw", "destination": DEST, "camera_group_key": CAM,
                       "native_gps": None, "has_native_gps": False, "has_timestamp": True,
                       "source_naive_time": naive, "content_fingerprint": f"fq{day}-{i}"})
    return pts, photos


HOME, LOCAL = -3600, -32400          # the camera on home time (UTC+1), then set to Japan's (UTC+9) at lunch


def _plan(wf, files, gpx, prior=None):
    art, blockers = wf.build_time_decisions(files, GROUPS, with_root_zone(prior or {"destinations": {}}, "Asia/Tokyo"),
                                            gpx)
    return art, blockers


def _cells(art):
    return art["destinations"][DEST]["camera_group_time_decisions"]


def _accept(art, key=CAM, first=""):
    prior = copy.deepcopy(art)
    cell = _cells(prior)[key]
    cell["user_decision"].update(accept_clock_change=True, first_after_change=first,
                                 accepted_change_offsets_seconds=[r["offset_seconds"] for r in cell["clock_change"]["runs"]])
    return prior


@pytest.mark.spec("RUL-clock_change_split_proposed", "BLD-clock_change_split",
                  test="TST-geotag_clock_change-two_runs_propose_a_split")
def test_two_runs_propose_a_split(tmp_path):
    """Three photos on home time, then three set to local time: two consecutive runs, each agreeing on its own
    offset. The day's cell proposes splitting at the change, naming each run's offset and its first and last photo,
    and the photos between the runs; it asks, as a day whose anchors disagree always did."""
    pts, files = _day([HOME, HOME, HOME, None, LOCAL, LOCAL, LOCAL], between=["2024:07:03 11:30:00"])
    art, blockers = _plan(_wf(tmp_path), files, _gpx(pts))
    assert blockers == []
    cell = _cells(art)[CAM]
    change = cell["clock_change"]
    assert change["evidence"] == "gpx_self_anchor"
    assert [r["offset_seconds"] for r in change["runs"]] == [HOME, LOCAL] and [r["photos"] for r in change["runs"]] == [3, 3]
    assert change["runs"][0]["last"]["source_file"] == f"{DEST}/p3-02.arw"
    assert change["runs"][1]["first"]["source_file"] == f"{DEST}/p3-03.arw"
    assert change["between"] == [{"source_file": f"{DEST}/q3-00.arw", "camera_source_naive_time": "2024:07:03 11:30:00"}]
    assert cell["requires_user_input"] is True and set(_cells(art)) == {CAM}
    assert cell["user_decision"]["accept_clock_change"] is False


@pytest.mark.spec("RUL-clock_change_needs_acceptance", "RUL-clock_change_accepted_once", "RUL-day_split_into_parts",
                  "RUL-clock_change_parts_own_evidence", "RUL-clock_change_first_after_asked", "BLD-clock_change_split",
                  "BLD-resolved_utc",
                  test="TST-geotag_clock_change-an_accepted_split_decides_the_day_in_two_parts")
def test_an_accepted_split_decides_the_day_in_two_parts(tmp_path):
    """Accepted, with no word of which photo between the runs was the first after the change, the day still asks;
    told, the day's cell asks nothing and the day is two parts, each anchored by its own photos at the offset accepted
    for it, nothing asked of them. Each photo takes the part its camera time falls in — the photo between, said to be
    the first after the change, the second's."""
    wf, (pts, files) = _wf(tmp_path), _day([HOME, HOME, HOME, None, LOCAL, LOCAL, LOCAL], between=["2024:07:03 11:30:00"])
    gpx = _gpx(pts)
    art, _ = _plan(wf, files, gpx)
    asked, _ = _plan(wf, files, gpx, _accept(art))
    assert set(_cells(asked)) == {CAM} and _cells(asked)[CAM]["requires_user_input"] is True
    split, blockers = _plan(wf, files, gpx, _accept(art, first="2024:07:03 11:30:00"))
    assert blockers == []
    cells = _cells(split)
    assert set(cells) == {CAM, f"{CAM}#1", f"{CAM}#2"}
    day = cells[CAM]
    assert day["requires_user_input"] is False and day["effective_time_anchor"] == ""
    assert day["clock_change"]["effective_split"] == {"first_after_change": "2024:07:03 11:30:00",
                                                      "parts": [f"{CAM}#1", f"{CAM}#2"]}
    one, two = cells[f"{CAM}#1"], cells[f"{CAM}#2"]
    assert one["effective_time_anchor"] == {"offset_seconds": HOME, "source": "gpx_anchor_accepted"}
    assert two["effective_time_anchor"] == {"offset_seconds": LOCAL, "source": "gpx_anchor_accepted"}
    assert one["proposal"]["anchor_count"] == 3 and one["proposal"]["conflicting_count"] == 0
    assert two["clock_change_part"] == {"of": CAM, "part": 2, "from": "2024:07:03 11:30:00", "until": ""}
    assert not one["requires_user_input"] and not two["requires_user_input"] and split["status"] == "complete"
    rows = {r["relative_path"]: r for r in cal.compute_resolved_utc(files, GROUPS, split)}
    assert rows[f"{DEST}/p3-00.arw"]["utc_offset_used"] == HOME and rows[f"{DEST}/p3-00.arw"]["time_decision_scope"] == f"{CAM}#1|{DEST}"
    assert rows[f"{DEST}/q3-00.arw"]["utc_offset_used"] == LOCAL
    assert rows[f"{DEST}/p3-05.arw"]["time_decision_scope"] == f"{CAM}#2|{DEST}"
    # the record cites the part a photo's offset came from
    assert cal.offset_decision_pointer(rows[f"{DEST}/q3-00.arw"], DEST, cells) == \
        f"photos-21 destinations.{DEST}.camera_group_time_decisions.{CAM}#2"
    # said before the photo between: the photo is the first part's
    split2, _ = _plan(wf, files, gpx, _accept(art, first=files[3]["source_naive_time"]))
    rows = {r["relative_path"]: r for r in cal.compute_resolved_utc(files, GROUPS, split2)}
    assert rows[f"{DEST}/q3-00.arw"]["utc_offset_used"] == HOME
    # said outside the runs: asked again, the answer kept as written
    out, _ = _plan(wf, files, gpx, _accept(art, first="2024:07:03 08:00:00"))
    assert _cells(out)[CAM]["stale_user_decision"] is True and _cells(out)[CAM]["requires_user_input"] is True
    assert _cells(out)[CAM]["user_decision"]["first_after_change"] == "2024:07:03 08:00:00"


@pytest.mark.spec("RUL-clock_change_first_after_not_asked", "BLD-clock_change_split",
                  test="TST-geotag_clock_change-no_photo_between_is_split_at_the_second_run")
def test_no_photo_between_is_split_at_the_second_run(tmp_path):
    """With no photo between the runs, nothing is asked of where the change was: accepted, the day splits at the first
    photo of the second run."""
    wf, (pts, files) = _wf(tmp_path), _day([HOME, HOME, None, LOCAL, LOCAL])
    gpx = _gpx(pts)
    art, _ = _plan(wf, files, gpx)
    assert _cells(art)[CAM]["clock_change"]["between"] == []
    split, _ = _plan(wf, files, gpx, _accept(art))
    assert _cells(split)[CAM]["clock_change"]["effective_split"]["first_after_change"] == files[2]["source_naive_time"]
    assert split["status"] == "complete"


@pytest.mark.spec("RUL-clock_change_needs_acceptance", "RUL-stale_acceptance_kept", "BLD-clock_change_split",
                  test="TST-geotag_clock_change-an_acceptance_holds_for_the_offsets_it_accepted")
def test_an_acceptance_holds_for_the_offsets_it_accepted(tmp_path):
    """Unaccepted, nothing splits; an acceptance naming other offsets than the runs now give splits nothing, is kept as
    written and asks; one naming none is a blocker."""
    wf, (pts, files) = _wf(tmp_path), _day([HOME, HOME, None, LOCAL, LOCAL])
    gpx = _gpx(pts)
    art, _ = _plan(wf, files, gpx)
    prior = _accept(art)
    _cells(prior)[CAM]["user_decision"]["accepted_change_offsets_seconds"] = [HOME, -36000]
    stale, _ = _plan(wf, files, gpx, prior)
    assert set(_cells(stale)) == {CAM} and _cells(stale)[CAM]["stale_user_decision"] is True
    assert _cells(stale)[CAM]["user_decision"]["accepted_change_offsets_seconds"] == [HOME, -36000]
    _cells(prior)[CAM]["user_decision"]["accepted_change_offsets_seconds"] = ""
    _, blockers = _plan(wf, files, gpx, prior)
    assert blockers and "accepted_change_offsets_seconds" in blockers[0]


@pytest.mark.spec("RUL-alternating_runs_no_clock_change", "RUL-clock_change_split_proposed", "BLD-clock_change_split",
                  test="TST-geotag_clock_change-alternating_or_agreeing_photos_propose_no_split")
def test_alternating_or_agreeing_photos_propose_no_split(tmp_path):
    """Photos whose offsets go back and forth in camera-time order — three runs or more, as two bodies' photos taken in
    turn are — are no clock change; nor is a day whose photos agree."""
    near = HOME - 600                                   # ten minutes off: its photos fall between the others'
    for offsets in ([HOME, near, HOME, near], [HOME, HOME, near, HOME, HOME], [HOME, HOME, HOME]):
        pts, files = _day(offsets)
        art, _ = _plan(_wf(tmp_path), files, _gpx(pts))
        assert "clock_change" not in _cells(art)[CAM]
        tmp_path = tmp_path / "x"


@pytest.mark.spec("RUL-clock_change_needs_gps", "BLD-clock_change_split",
                  test="TST-geotag_clock_change-a_change_is_seen_only_from_the_cameras_gps")
def test_a_change_is_seen_only_from_the_cameras_gps(tmp_path):
    """The times the GPS fixes recorded show a change as the tracks do, where no track anchors the day; the photos
    alone — their recorded times, the offsets they record — show none."""
    pts, files = _day([HOME, HOME, None, LOCAL, LOCAL])
    for f, p in zip(files, pts):
        f["gps_utc"] = p.time_utc.strftime("%Y-%m-%dT%H:%M:%SZ")
    wf = _wf(tmp_path)
    art, _ = _plan(wf, files, _gpx([]))
    change = _cells(art)[CAM]["clock_change"]
    assert change["evidence"] == "gps_time" and [r["offset_seconds"] for r in change["runs"]] == [HOME, LOCAL]
    split, _ = _plan(wf, files, _gpx([]), _accept(art))
    assert _cells(split)[f"{CAM}#2"]["effective_time_anchor"] == {"offset_seconds": LOCAL, "source": "gps_time_accepted"}
    # no GPS at all: the offsets the photos record differ, and that is all — no change is proposed
    bare = [dict(f, has_native_gps=False, native_gps=None, gps_utc=None,
                 raw_times={"OffsetTimeOriginal": "+01:00" if i < 2 else "+09:00"},
                 source_time_tag="EXIF:DateTimeOriginal") for i, f in enumerate(files)]
    art, _ = _plan(wf, bare, _gpx([]))
    assert "clock_change" not in _cells(art)[CAM] and _cells(art)[CAM].get("recorded_offsets_differ")


@pytest.mark.spec("RUL-several_bodies_no_clock_change_split", "BLD-clock_change_split",
                  test="TST-geotag_clock_change-several_bodies_are_never_split_at_a_change")
def test_several_bodies_are_never_split_at_a_change(tmp_path):
    """For a group the configuration names several bodies, two runs are two bodies as likely as one clock changed:
    no split is proposed — the bodies are told apart by their destinations."""
    pts, files = _day([HOME, HOME, None, LOCAL, LOCAL])
    groups = {CAM: dict(GROUPS[CAM], several_bodies=True)}
    art, _ = _wf(tmp_path).build_time_decisions(files, groups, with_root_zone({"destinations": {}}, "Asia/Tokyo"),
                                                 _gpx(pts))
    assert "clock_change" not in _cells(art)[CAM]


@pytest.mark.spec("RUL-answer_follows_its_day", "RUL-day_split_into_parts", "BLD-clock_change_split",
                  test="TST-geotag_clock_change-the_split_follows_its_day_when_another_day_arrives")
def test_the_split_follows_its_day_when_another_day_arrives(tmp_path):
    """The split is answered on the day's cell: when another day's photos arrive and the day's key takes its dated
    form, the answer follows the day, its parts keyed after it."""
    wf, (pts, files) = _wf(tmp_path), _day([HOME, HOME, None, LOCAL, LOCAL])
    gpx = _gpx(pts)
    art, _ = _plan(wf, files, gpx)
    split, _ = _plan(wf, files, gpx, _accept(art))
    pts4, files4 = _day([HOME, HOME], day=4)
    both, _ = _plan(wf, files + files4, _gpx(pts + pts4), split)
    cells = _cells(both)
    assert {f"{CAM}@2024-07-03#1", f"{CAM}@2024-07-03#2", f"{CAM}@2024-07-03", f"{CAM}@2024-07-04"} == set(cells)
    assert cells[f"{CAM}@2024-07-03#2"]["effective_time_anchor"]["offset_seconds"] == LOCAL
