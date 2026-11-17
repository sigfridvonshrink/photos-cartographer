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

A camera set to local time at lunch has two offsets that day. Its photos holding their own position, in the order of
the true time their GPS gives them, form two consecutive runs each agreeing on its own offset: geotag proposes
splitting the day's cell at the change; accepted once, the day is decided as two parts, each by its own photos. A photo
with no GPS that only one part could have taken is that part's; one either part could have taken — a clock set back
repeats its camera times — or neither is asked about: which part it belongs to. From conftest.py.
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


def _accept(art, key=CAM, parts=None):
    prior = copy.deepcopy(art)
    cell = _cells(prior)[key]
    cell["user_decision"].update(accept_clock_change=True, photo_parts=dict(parts or {}),
                                 accepted_change_offsets_seconds=[r["offset_seconds"] for r in cell["clock_change"]["runs"]])
    return prior


# Photos with no position, by their camera times, on the day of `_day([HOME, HOME, HOME, None, LOCAL, LOCAL, LOCAL])`:
# its first run taken from 08:00 to 09:00 UTC, its second from 12:30. At 11:30 only the first part could have taken a
# photo — by the second's offset it would be 02:30 UTC, before the first run's end; at 15:00 neither could — 14:00 UTC by
# the first, after the second run began, 06:00 by the second, before the first ended; at 21:00, only the second.
SETTLED_FIRST, NEITHER, SETTLED_SECOND = "2024:07:03 11:30:00", "2024:07:03 15:00:00", "2024:07:03 21:00:00"


@pytest.mark.spec("RUL-clock_change_split_proposed", "BLD-clock_change_split",
                  test="TST-geotag_clock_change-two_runs_propose_a_split")
def test_two_runs_propose_a_split(tmp_path):
    """Three photos on home time, then three set to local time: two consecutive runs, each agreeing on its own
    offset. The day's cell proposes splitting at the change, naming each run's offset and its first and last photo in
    true time, and the photos without GPS whose part the runs leave unsettled; it asks, as a day whose anchors disagree
    always did."""
    pts, files = _day([HOME, HOME, HOME, None, LOCAL, LOCAL, LOCAL], between=[SETTLED_FIRST, NEITHER])
    art, blockers = _plan(_wf(tmp_path), files, _gpx(pts))
    assert blockers == []
    cell = _cells(art)[CAM]
    change = cell["clock_change"]
    assert change["evidence"] == "gpx_self_anchor"
    assert [r["offset_seconds"] for r in change["runs"]] == [HOME, LOCAL] and [r["photos"] for r in change["runs"]] == [3, 3]
    assert change["runs"][0]["last"] == {"source_file": f"{DEST}/p3-02.arw", "camera_source_naive_time": "2024:07:03 10:00:00",
                                         "real_utc": "2024-07-03T09:00:00Z"}
    assert change["runs"][1]["first"]["source_file"] == f"{DEST}/p3-03.arw"
    assert change["runs"][1]["first"]["real_utc"] == "2024-07-03T12:30:00Z"
    assert change["unsettled"] == [{"source_file": f"{DEST}/q3-01.arw", "camera_source_naive_time": NEITHER}]
    assert cell["requires_user_input"] is True and set(_cells(art)) == {CAM}
    assert cell["user_decision"]["accept_clock_change"] is False and cell["user_decision"]["photo_parts"] == {}


@pytest.mark.spec("RUL-clock_change_needs_acceptance", "RUL-clock_change_accepted_once", "RUL-day_split_into_parts",
                  "RUL-clock_change_parts_own_evidence", "RUL-clock_change_unsettled_photo_asked",
                  "RUL-clock_change_settled_photo_not_asked", "BLD-clock_change_split", "BLD-resolved_utc",
                  test="TST-geotag_clock_change-an_accepted_split_decides_the_day_in_two_parts")
def test_an_accepted_split_decides_the_day_in_two_parts(tmp_path):
    """Accepted, with no word of the part of the photo the runs leave unsettled, the day still asks; told, the day's
    cell asks nothing and the day is two parts, each anchored by its own photos at the offset accepted for it, nothing
    asked of them. Each photo takes its part: a run's photo its run's, the one only the first part could have taken the
    first's, the unsettled one the part it was given. A part written other than 1 or 2 is a blocker."""
    wf = _wf(tmp_path)
    pts, files = _day([HOME, HOME, HOME, None, LOCAL, LOCAL, LOCAL], between=[SETTLED_FIRST, NEITHER])
    gpx = _gpx(pts)
    art, _ = _plan(wf, files, gpx)
    asked, _ = _plan(wf, files, gpx, _accept(art))
    assert set(_cells(asked)) == {CAM} and _cells(asked)[CAM]["requires_user_input"] is True
    q0, q1 = f"{DEST}/q3-00.arw", f"{DEST}/q3-01.arw"
    split, blockers = _plan(wf, files, gpx, _accept(art, parts={q1: 2}))
    assert blockers == []
    cells = _cells(split)
    assert set(cells) == {CAM, f"{CAM}#1", f"{CAM}#2"}
    day = cells[CAM]
    assert day["requires_user_input"] is False and day["effective_time_anchor"] == ""
    effective = day["clock_change"]["effective_split"]
    assert effective["parts"] == [f"{CAM}#1", f"{CAM}#2"]
    assert effective["photo_parts"] == {**{f"{DEST}/p3-{n:02d}.arw": 1 + (n >= 3) for n in range(6)}, q0: 1, q1: 2}
    one, two = cells[f"{CAM}#1"], cells[f"{CAM}#2"]
    assert one["effective_time_anchor"] == {"offset_seconds": HOME, "source": "gpx_anchor_accepted"}
    assert two["effective_time_anchor"] == {"offset_seconds": LOCAL, "source": "gpx_anchor_accepted"}
    assert one["proposal"]["anchor_count"] == 3 and one["proposal"]["conflicting_count"] == 0
    assert two["clock_change_part"] == {"of": CAM, "part": 2, "photos": 4}
    assert not one["requires_user_input"] and not two["requires_user_input"] and split["status"] == "complete"
    rows = {r["relative_path"]: r for r in cal.compute_resolved_utc(files, GROUPS, split)}
    assert rows[f"{DEST}/p3-00.arw"]["utc_offset_used"] == HOME and rows[f"{DEST}/p3-00.arw"]["time_decision_scope"] == f"{CAM}#1|{DEST}"
    assert rows[q0]["utc_offset_used"] == HOME and rows[q1]["utc_offset_used"] == LOCAL
    assert rows[f"{DEST}/p3-05.arw"]["time_decision_scope"] == f"{CAM}#2|{DEST}"
    # the record cites the part a photo's offset came from
    assert cal.offset_decision_pointer(rows[q1], DEST, cells) == \
        f"photos-21 destinations.{DEST}.camera_group_time_decisions.{CAM}#2"
    # given the first part instead: the photo is read by it
    split1, _ = _plan(wf, files, gpx, _accept(art, parts={q1: 1}))
    rows = {r["relative_path"]: r for r in cal.compute_resolved_utc(files, GROUPS, split1)}
    assert rows[q1]["utc_offset_used"] == HOME
    # a part that is neither: a blocker, and nothing splits
    bad, blockers = _plan(wf, files, gpx, _accept(art, parts={q1: 3}))
    assert any("photo_parts" in b for b in blockers) and f"{CAM}#1" not in _cells(bad)


@pytest.mark.spec("RUL-split_day_held_against_same_day", "RUL-split_day_passes_no_offset", "BLD-clock_change_split",
                  test="TST-geotag_clock_change-a_split_day_is_held_against_the_same_day_elsewhere")
@pytest.mark.parametrize("there", [-18000, LOCAL], ids=["far_from_both", "one_part_s"])
def test_a_split_day_is_held_against_the_same_day_elsewhere(tmp_path, monkeypatch, there):
    """The day in Kyoto split at the change, its parts on home time and on local time. The same camera's photos that
    day in Osaka anchor on the tracks by themselves. An offset there far from both parts' is one of them resting on a
    wrong match: it is withheld and asks, naming the parts, which keep theirs. One that is a part's stands. Nara, with
    no position that day, is offered neither part's offset."""
    monkeypatch.setitem(utils.CONFIG["camera_time_and_timezone_policy"], "multi_anchor_auto_apply", True)
    wf = _wf(tmp_path)
    pts, files = _day([HOME, HOME, HOME, None, LOCAL, LOCAL, LOCAL])
    osaka = f"{BYDEST}/Osaka"
    for n, t in enumerate((datetime(2024, 7, 3, 13, 0, tzinfo=timezone.utc), datetime(2024, 7, 3, 13, 30, tzinfo=timezone.utc))):
        pts.append(cal.GPXPoint(34.7 + n * 0.01, 135.5, t, "osaka.gpx", n))
        files.append({"relative_path": f"{osaka}/o{n}.arw", "destination": osaka, "camera_group_key": CAM,
                      "native_gps": {"lat": 34.7 + n * 0.01, "lon": 135.5}, "has_native_gps": True, "has_timestamp": True,
                      "source_naive_time": _cam(t, there), "content_fingerprint": f"fo{n}"})
    nara = f"{BYDEST}/Nara"
    files.append({"relative_path": f"{nara}/n.arw", "destination": nara, "camera_group_key": CAM, "native_gps": None,
                  "has_native_gps": False, "has_timestamp": True, "source_naive_time": "2024:07:03 18:00:00",
                  "content_fingerprint": "fn"})
    gpx = _gpx(pts)
    art, _ = _plan(wf, files, gpx)
    split, blockers = _plan(wf, files, gpx, _accept(art))
    assert blockers == []
    cells = _cells(split)
    assert cells[f"{CAM}#1"]["effective_time_anchor"]["offset_seconds"] == HOME
    assert cells[f"{CAM}#2"]["effective_time_anchor"]["offset_seconds"] == LOCAL
    o = split["destinations"][osaka]["camera_group_time_decisions"][CAM]
    assert o["proposal"]["proposed_offset_seconds"] == there
    n = split["destinations"][nara]["camera_group_time_decisions"][CAM]["proposal"]
    assert (n.get("shared_from") or {}).get("destination") != DEST, n
    if there == LOCAL:
        assert o["effective_time_anchor"] == {"offset_seconds": LOCAL, "source": "gpx_anchor_auto"}
        assert "conflicts_with" not in o
    else:
        assert o["effective_time_anchor"] == "" and o["requires_user_input"]
        assert o["conflicts_with"] == [{"destination": DEST, "bucket": f"{CAM}#1", "offset_seconds": HOME, "chosen": False},
                                       {"destination": DEST, "bucket": f"{CAM}#2", "offset_seconds": LOCAL, "chosen": False}]


@pytest.mark.spec("RUL-clock_change_settled_photo_not_asked", "BLD-clock_change_split",
                  test="TST-geotag_clock_change-photos_one_part_alone_could_have_taken_are_not_asked")
def test_photos_one_part_alone_could_have_taken_are_not_asked(tmp_path):
    """With every photo without GPS one that only one part could have taken, nothing is asked of them: accepted, the
    day splits, each such photo in its part."""
    wf = _wf(tmp_path)
    pts, files = _day([HOME, HOME, HOME, None, LOCAL, LOCAL, LOCAL], between=[SETTLED_FIRST, SETTLED_SECOND])
    gpx = _gpx(pts)
    art, _ = _plan(wf, files, gpx)
    assert _cells(art)[CAM]["clock_change"]["unsettled"] == []
    split, _ = _plan(wf, files, gpx, _accept(art))
    assert split["status"] == "complete"
    rows = {r["relative_path"]: r for r in cal.compute_resolved_utc(files, GROUPS, split)}
    assert rows[f"{DEST}/q3-00.arw"]["utc_offset_used"] == HOME and rows[f"{DEST}/q3-01.arw"]["utc_offset_used"] == LOCAL


BACK = LOCAL + 3600                  # the camera's clock set back an hour: from UTC+9 to UTC+8


@pytest.mark.spec("RUL-clock_change_split_proposed", "RUL-clock_change_unsettled_photo_asked",
                  "RUL-clock_change_settled_photo_not_asked", "RUL-day_split_into_parts",
                  "RUL-contradicted_position_reviewed", "BLD-clock_change_split", "BLD-contradicted_position",
                  test="TST-geotag_clock_change-a_clock_set_back_is_split_and_its_repeated_hour_asked")
def test_a_clock_set_back_is_split_and_its_repeated_hour_asked(tmp_path):
    """Four photos on a clock at UTC+9, then four after it was set back an hour: in camera time the two runs
    interleave — 18:00 and 18:30 each shown twice — and only by the true times the tracks give do they follow one
    another. A split is proposed; a photo without GPS in the repeated hour, which either part could have taken, is
    asked its part, one before or after it is not. Split so, every photo of each part agrees with its offset: no own
    position is doubted, and photos-23 raises no review item for any."""
    wf = _wf(tmp_path)
    wf.handoff = {"cache_fingerprint": "pcf"}
    early, repeated, late = "2024:07:03 17:15:00", ["2024:07:03 18:15:00", "2024:07:03 18:45:00"], "2024:07:03 19:15:00"
    pts, files = _day([LOCAL] * 4 + [BACK] * 4, between=[early, *repeated, late])
    for f in files:
        f.update(size=1, mtime_ns=1)
    gpx = _gpx(pts)
    assert files[2]["source_naive_time"] == files[4]["source_naive_time"] == "2024:07:03 18:00:00"
    art, _ = _plan(wf, files, gpx)
    change = _cells(art)[CAM]["clock_change"]
    assert [r["offset_seconds"] for r in change["runs"]] == [LOCAL, BACK] and [r["photos"] for r in change["runs"]] == [4, 4]
    assert change["runs"][0]["last"]["source_file"] == f"{DEST}/p3-03.arw"      # 18:30 by the camera, 09:30 UTC
    assert change["runs"][1]["first"]["source_file"] == f"{DEST}/p3-04.arw"     # 18:00 by the camera, 10:00 UTC
    assert [u["camera_source_naive_time"] for u in change["unsettled"]] == repeated
    split, blockers = _plan(wf, files, gpx, _accept(art, parts={f"{DEST}/q3-01.arw": 1, f"{DEST}/q3-02.arw": 2}))
    assert blockers == [] and split["status"] == "complete"
    cells = _cells(split)
    assert cells[f"{CAM}#1"]["effective_time_anchor"] == {"offset_seconds": LOCAL, "source": "gpx_anchor_accepted"}
    assert cells[f"{CAM}#2"]["effective_time_anchor"] == {"offset_seconds": BACK, "source": "gpx_anchor_accepted"}
    rows = cal.compute_resolved_utc(files, GROUPS, split)
    used = {r["relative_path"].rsplit("/", 1)[1]: r["utc_offset_used"] for r in rows}
    assert used == {**{f"p3-{n:02d}.arw": LOCAL if n < 4 else BACK for n in range(8)},
                    "q3-00.arw": LOCAL, "q3-01.arw": LOCAL, "q3-02.arw": BACK, "q3-03.arw": BACK}
    # each run's photos agree with their part's offset: none is set against the tracks as a wrong position
    assert all("positions_contradicted" not in c for c in cells.values())
    assert cal.contradicted_positions(split) == []
    gps, blockers = wf.build_gps_decisions(files, rows, gpx, None, "rfp", cal.contradicted_positions(split))
    assert not blockers
    assert not [ri for ri in gps["destinations"][DEST]["gps_decisions"]["review_items"]
                if ri.get("reason") == "own_position_contradicted"]


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
    """Photos whose offsets go back and forth in the order of their true times — three runs or more, as two bodies'
    photos taken in turn are — are no clock change; nor is a day whose photos agree."""
    near = HOME - 600                                   # ten minutes off: its photos fall between the others'
    for offsets in ([HOME, near, HOME, near], [HOME, HOME, near, HOME, HOME], [HOME, HOME, HOME]):
        pts, files = _day(offsets)
        art, _ = _plan(_wf(tmp_path), files, _gpx(pts))
        assert "clock_change" not in _cells(art)[CAM]
        tmp_path = tmp_path / "x"


@pytest.mark.spec("RUL-alternating_runs_no_clock_change", "BLD-clock_change_split",
                  test="TST-geotag_clock_change-two_places_to_cut_propose_no_split")
def test_two_places_to_cut_the_day_propose_no_split():
    """The walk passes one place twice, at 09:00 and at 17:00: a photo taken there agrees with the home-time run before
    it and with the local-time run after it alike. The day can be cut on either side of it, each cut leaving two runs
    that agree — not one place where the clock changed, so no split is proposed."""
    t = lambda h, m=0: datetime(2024, 7, 3, h, m, tzinfo=timezone.utc)
    here = lambda n: (35.0 + n * 0.01, 135.0)
    track = [(t(8), 0), (t(8, 30), 1), (t(9), 2), (t(9, 30), 3), (t(16, 30), 4), (t(17), 2), (t(17, 30), 5),
             (t(18), 6)]
    pts = [cal.GPXPoint(*here(n), when, "trip.gpx", i) for i, (when, n) in enumerate(track)]

    def photo(name, n, utc, off):
        lat, lon = here(n)
        return {"relative_path": f"{DEST}/{name}.arw", "destination": DEST, "camera_group_key": CAM,
                "native_gps": {"lat": lat, "lon": lon}, "has_native_gps": True, "has_timestamp": True,
                "source_naive_time": _cam(utc, off), "content_fingerprint": "fp-" + name}
    photos = [photo("a", 0, t(8), HOME), photo("b", 1, t(8, 30), HOME),
              photo("m", 2, t(17), HOME),                       # 18:00 on the camera: 17:00 at home time, 09:00 at local
              photo("y", 5, t(17, 30), LOCAL), photo("z", 6, t(18), LOCAL)]
    assert cal.clock_change_proposal(photos, photos, _gpx(pts), utils.CONFIG) is None
    # without the photo both sides take, the one cut is a change
    rest = [p for p in photos if not p["relative_path"].endswith("m.arw")]
    assert cal.clock_change_proposal(rest, rest, _gpx(pts), utils.CONFIG) is not None


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
