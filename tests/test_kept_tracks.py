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

"""The tracks geotag decides by, kept in the record (BLD-track_catalogue, BLD-track_window,
BLD-withdrawn_track_points): a catalogue of every track file, the points of each in the window the photos reach, a
file unchanged since it was read not read again, and the points an executed plan rested on kept when the file goes."""
import json
import os
import sqlite3
import sys
from datetime import datetime, timezone

import pytest
from _handoff import match_disk, vouched

import photos_2_geotag as cal
import photos_utils as utils


def _pt(t, lat=50.0, lon=4.0):
    return f'<trkpt lat="{lat}" lon="{lon}"><time>{t}</time></trkpt>'


def _gpx(*pts):
    return '<gpx xmlns="http://www.topografix.com/GPX/1/1"><trk><trkseg>' + "".join(pts) + '</trkseg></trk></gpx>'


def _at(s):
    return datetime.fromisoformat(s.replace("Z", "+00:00"))


JULY = [cal.around(_at("2024-07-03T12:00:00Z"), 3600)]           # the window: an hour each side of noon, 3 July


@pytest.fixture
def tracks(tmp_path):
    root = tmp_path / "gpx"
    (root / "2024").mkdir(parents=True)
    (root / "2024" / "a.gpx").write_text(_gpx(_pt("2024-07-03T12:00:00Z"), _pt("2024-07-03T12:10:00.250Z", 50.1),
                                              _pt("2024-07-03T12:11:00Z", 91, 4)))      # out of range: a warning
    (root / "b.gpx").write_text(_gpx(_pt("2024-07-03T11:30:00Z", 51.0, 5.0)))
    (root / "c.GPX").write_text("<gpx><trk")                                          # malformed
    return root


def _build(root, record, window=JULY, **kw):
    return cal.GPXIndex(str(root), str(record), ["2024"]).build(window=window, **kw)


def _seen(idx):
    return (idx.fingerprint, idx.status, [(p.lat, p.lon, p.time_utc, p.source_file, p.point_index, p.track,
                                           p.segment) for p in idx.points], sorted(idx.warnings), idx.file_sha)


def _rows(record, sql, *args):
    conn = sqlite3.connect(str(record))
    try:
        return conn.execute(sql, args).fetchall()
    finally:
        conn.close()


# --- reading only what is new or changed ----------------------------------------------------------------

@pytest.mark.spec("BLD-track_catalogue", "RUL-reuse_valid_work", test="TST-kept_tracks-an_unchanged_track_is_not_read_again")
def test_an_unchanged_track_is_not_read_again(tracks, tmp_path):
    """A track file whose size, modification time and inode are as the catalogue has them is not read again: its
    points, warnings and SHA-256 come from the record, exactly as reading it would give them."""
    record = tmp_path / "record.db"
    first = _build(tracks, record)
    assert first.read == 3
    again = _build(tracks, record)
    assert again.read == 0
    assert _seen(again) == _seen(first) == _seen(cal.GPXIndex(str(tracks), None, ["2024"]).build(window=JULY))
    assert any("Out-of-range" in w and "2024/a.gpx" in w for w in again.warnings)
    assert again.unreadable and again.unreadable[0][0] == "c.GPX"                  # still unreadable, not read
    assert first.status == again.status == "usable"
    # bytes changed behind an unchanged size, time and inode are not looked for: the stamp is what is checked
    st = os.stat(tracks / "b.gpx")
    (tracks / "b.gpx").write_text(_gpx(_pt("2024-07-03T11:30:00Z", 52.0, 5.0)))
    os.utime(tracks / "b.gpx", ns=(st.st_atime_ns, st.st_mtime_ns))
    assert _build(tracks, record).read == 0


@pytest.mark.spec("BLD-track_catalogue", "RUL-tracks_in_dependencies", test="TST-kept_tracks-a_changed_track_is_read_again")
def test_a_changed_track_is_read_again(tracks, tmp_path):
    """A changed file is read and parsed again: its new points are decided by, and its earlier entry, which no executed
    plan used, leaves the record. A file touched without a change is read, and keeps its entry."""
    record = tmp_path / "record.db"
    first = _build(tracks, record)
    (tracks / "b.gpx").write_text(_gpx(_pt("2024-07-03T11:30:00Z", 51.5, 5.0)))
    again = _build(tracks, record)
    assert again.read == 1 and again.fingerprint != first.fingerprint
    assert _seen(again) == _seen(cal.GPXIndex(str(tracks), None, ["2024"]).build(window=JULY))
    assert _rows(record, "SELECT COUNT(*) FROM gpx_track_files WHERE path = 'b.gpx'") == [(1,)]
    ids = _rows(record, "SELECT track_id FROM gpx_track_files ORDER BY path")
    os.utime(tracks / "b.gpx", ns=(1, 1))                                      # touched: same bytes
    touched = _build(tracks, record)
    assert touched.read == 1 and touched.fingerprint == again.fingerprint
    assert _rows(record, "SELECT track_id FROM gpx_track_files ORDER BY path") == ids


@pytest.mark.spec("BLD-track_catalogue", test="TST-kept_tracks-a_new_track_is_read")
def test_a_new_track_is_read(tracks, tmp_path):
    record = tmp_path / "record.db"
    _build(tracks, record)
    (tracks / "2024" / "d.gpx").write_text(_gpx(_pt("2024-07-03T12:30:00Z", 50.5, 4.5)))
    idx = _build(tracks, record)
    assert idx.read == 1 and "2024/d.gpx" in {p.source_file for p in idx.points}


# --- the record holds the catalogue and the points ---------------------------------------------------------

@pytest.mark.spec("RUL-track_points_kept", "BLD-track_catalogue", test="TST-kept_tracks-the_catalogue_and_the_window_s_points_are_kept")
def test_the_catalogue_and_the_window_s_points_are_kept(tracks, tmp_path):
    """Every track file is catalogued — path, its rank's folder, size, modification time, inode, SHA-256, first and last
    point time — and the points in the window are kept as decided on; points outside it are not."""
    (tracks / "b.gpx").write_text(_gpx(_pt("2024-07-03T11:30:00Z", 51.0, 5.0), _pt("2019-01-01T00:00:00Z")))
    record = tmp_path / "record.db"
    idx = _build(tracks, record)
    rows = {r[0]: r[1:] for r in _rows(record, "SELECT path, rank_folder, size, mtime_ns, inode, sha256, first_utc, "
                                                "last_utc, unreadable, withdrawn FROM gpx_track_files")}
    assert set(rows) == {"2024/a.gpx", "b.gpx", "c.GPX"}
    st = os.stat(tracks / "b.gpx")
    assert rows["b.gpx"][:5] == ("", st.st_size, st.st_mtime_ns, st.st_ino, idx.file_sha["b.gpx"])
    assert rows["b.gpx"][5:7] == ("2019-01-01T00:00:00+00:00", "2024-07-03T11:30:00+00:00")
    assert rows["2024/a.gpx"][0] == "2024" and rows["c.GPX"][7] and not any(r[8] for r in rows.values())
    kept = _rows(record, "SELECT f.path, p.point_index, p.time_utc, p.lat, p.lon, p.track, p.segment "
                         "FROM gpx_track_points p JOIN gpx_track_files f USING (track_id) ORDER BY f.path, p.point_index")
    assert kept == [("2024/a.gpx", 0, "2024-07-03T12:00:00+00:00", 50.0, 4.0, 0, 0),
                    ("2024/a.gpx", 1, "2024-07-03T12:10:00.250000+00:00", 50.1, 4.0, 0, 0),
                    ("b.gpx", 0, "2024-07-03T11:30:00+00:00", 51.0, 5.0, 0, 0)]   # not the 2019 point


@pytest.mark.spec("RUL-tracks_elsewhere_restale_nothing", "BLD-gpx_fingerprint", "BLD-track_window",
                  test="TST-kept_tracks-tracks_of_another_time_leave_the_fingerprint")
def test_tracks_of_another_time_leave_the_fingerprint(tracks, tmp_path):
    """Tracks added, or a track file grown, at times no photo reaches change nothing the tracks decide: the fingerprint
    is of the window's points. A point added inside the window changes it, as does the ranking."""
    record = tmp_path / "record.db"
    first = _build(tracks, record)
    fp = first.fingerprint
    (tracks / "2019.gpx").write_text(_gpx(_pt("2019-05-01T10:00:00Z")))
    (tracks / "b.gpx").write_text(_gpx(_pt("2024-07-03T11:30:00Z", 51.0, 5.0), _pt("2024-08-01T10:00:00Z")))
    again = _build(tracks, record)
    assert again.fingerprint == fp
    assert again.file_sha["b.gpx"] != first.file_sha["b.gpx"]          # its bytes changed: a confirmation sees it
    (tracks / "b.gpx").write_text(_gpx(_pt("2024-07-03T11:30:00Z", 51.0, 5.0), _pt("2024-07-03T11:40:00Z")))
    assert _build(tracks, record).fingerprint != fp
    assert cal.GPXIndex(str(tracks), str(record), []).build(window=JULY).fingerprint != _build(tracks, record).fingerprint


@pytest.mark.spec("BLD-track_window", "BLD-track_catalogue", test="TST-kept_tracks-a_wider_window_reads_the_files_it_meets")
def test_a_wider_window_reads_the_files_it_meets(tracks, tmp_path):
    """The window grown — a photo sorted in, a setting widened — reads again each file whose span from its first
    point to its last meets the new part, and only those: the points there are then kept and decided by."""
    (tracks / "2024" / "a.gpx").write_text(_gpx(_pt("2024-07-03T12:00:00Z"), _pt("2024-07-04T12:00:00Z", 50.2)))
    record = tmp_path / "record.db"
    narrow = _build(tracks, record)
    assert [p.time_utc for p in narrow.points if p.source_file == "2024/a.gpx"] == [_at("2024-07-03T12:00:00Z")]
    wide = _build(tracks, record, window=cal.window_union(JULY, [cal.around(_at("2024-07-04T12:00:00Z"), 60)]))
    assert wide.read == 1                                       # a.gpx alone reaches into the new part
    assert {p.time_utc for p in wide.points if p.source_file == "2024/a.gpx"} == {_at("2024-07-03T12:00:00Z"),
                                                                                    _at("2024-07-04T12:00:00Z")}
    assert _build(tracks, record, window=JULY).read == 0          # narrower again: what is kept serves
    assert _build(tracks, record, window=JULY).fingerprint == narrow.fingerprint


def _files(*times, dest="T", group="CAM", native=False):
    return [{"relative_path": f"6/{dest}/{i}.arw", "destination": dest, "camera_group_key": group,
             "source_naive_time": t, "has_native_gps": native} for i, t in enumerate(times)]


@pytest.mark.spec("BLD-track_window", test="TST-kept_tracks-the_window_grows_with_the_photos_and_the_settings")
def test_the_window_grows_with_the_photos_and_the_settings(monkeypatch):
    """The window is each reader's own reach: a photo sorted in widens it to its camera time, a setting widened widens
    it by as much, the corrected times widen it for the drift check and for placement."""
    monkeypatch.setitem(utils.CONFIG, "gpx_anchor_max_clock_error_seconds", 3600)
    monkeypatch.setitem(utils.CONFIG, "drift_check_track_window_seconds", 600)
    gap = max(utils.CONFIG["gpx_direct_match_max_seconds"], utils.CONFIG["gpx_interpolation_max_gap_seconds"])
    noon = _at("2024-07-03T12:00:00Z").timestamp()
    one = cal.GeotagWorkflow.camera_window(_files("2024:07:03 12:00:00"))
    assert one == [(noon - 3600 - gap, noon + 3600 + gap)]
    two = cal.GeotagWorkflow.camera_window(_files("2024:07:03 12:00:00", "2024:07:05 12:00:00"))
    assert len(two) == 2 and two[0] == one[0]                                       # a photo sorted in
    monkeypatch.setitem(utils.CONFIG, "gpx_anchor_max_clock_error_seconds", 7200)
    assert cal.GeotagWorkflow.camera_window(_files("2024:07:03 12:00:00")) == [(noon - 7200 - gap, noon + 7200 + gap)]
    # a day's photos from first to last, give or take the drift window, where the drift check falls back on them
    monkeypatch.setitem(utils.CONFIG, "gpx_anchor_max_clock_error_seconds", 0)
    monkeypatch.setitem(utils.CONFIG, "gpx_interpolation_max_gap_seconds", 0)
    monkeypatch.setitem(utils.CONFIG, "gpx_direct_match_max_seconds", 0)
    day = cal.GeotagWorkflow.camera_window(_files("2024:07:03 08:00:00", "2024:07:03 20:00:00"))
    assert day == [(noon - 4 * 3600 - 600, noon + 8 * 3600 + 600)]
    # placement: each photo it places, at its corrected time, give or take its farthest reach
    rows = [{"relative_path": "6/T/0.arw", "resolved_utc": "2024-07-03T12:00:00Z", "resolved_utc_status": "valid"},
            {"relative_path": "6/T/1.arw", "resolved_utc": "2024-07-09T12:00:00Z", "resolved_utc_status": "valid"}]
    reach = max(utils.CONFIG["gpx_interpolation_max_gap_seconds"], utils.CONFIG["gpx_direct_match_max_seconds"],
                utils.CONFIG["gpx_extrapolation_max_seconds"] + utils.CONFIG["gpx_extrapolation_heading_seconds"])
    assert cal.GeotagWorkflow.placement_window(_files("x", "y"), rows) == [
        (noon - reach, noon + reach), (noon + 6 * 86400 - reach, noon + 6 * 86400 + reach)]
    native = _files("x", "y"); native[1]["has_native_gps"] = True                    # its own position: not placed
    assert cal.GeotagWorkflow.placement_window(native, rows) == [(noon - reach, noon + reach)]


@pytest.mark.spec("BLD-track_window", test="TST-kept_tracks-the_drift_check_s_reach_is_its_buckets")
def test_the_drift_check_s_reach_is_its_buckets(monkeypatch):
    """The drift check sets a bucket's photos, at their corrected times from the first to the last, against the tracks
    the drift window either side: the window holds all of it, the hours between two photos of the day included."""
    monkeypatch.setitem(utils.CONFIG, "drift_check_track_window_seconds", 600)
    files = _files("2024:07:03 08:00:00", "2024:07:03 20:00:00")
    art = {"destinations": {"T": {"camera_group_time_decisions": {"CAM": {
        "camera_group": "CAM", "effective_time_anchor": {"offset_seconds": 0, "source": "timezone_accepted"}}}}}}
    rows0 = [{"relative_path": f["relative_path"], "resolved_utc_status": "valid",
              "resolved_utc": f["source_naive_time"].replace(":", "-", 2).replace(" ", "T") + "Z"} for f in files]
    noon = _at("2024-07-03T12:00:00Z").timestamp()
    assert cal.GeotagWorkflow(".").drift_window(files, art, rows0) == [(noon - 4 * 3600 - 600, noon + 8 * 3600 + 600)]


# --- a track file gone -----------------------------------------------------------------------------------

@pytest.mark.spec("RUL-gone_track_told", "RUL-gone_track_not_used", "BLD-track_catalogue",
                  test="TST-kept_tracks-a_track_gone_is_told_and_not_used")
def test_a_track_gone_is_told_and_not_used(tracks, tmp_path):
    """A track file taken out is named, and decided by no longer; no executed plan used it, so its entry and points
    leave the record."""
    record = tmp_path / "record.db"
    _build(tracks, record)
    (tracks / "b.gpx").unlink()
    idx = _build(tracks, record)
    assert idx.gone == ["b.gpx"] and any("gone" in w and "b.gpx" in w for w in idx.warnings)
    assert "b.gpx" not in {p.source_file for p in idx.points} and "b.gpx" not in idx.file_sha
    assert _rows(record, "SELECT COUNT(*) FROM gpx_track_files WHERE path = 'b.gpx'") == [(0,)]
    assert not _build(tracks, record).gone                                            # told once, as it went


@pytest.mark.spec("RUL-withdrawn_track_points_kept", "BLD-withdrawn_track_points",
                  test="TST-kept_tracks-the_points_an_executed_plan_used_stay_withdrawn")
def test_the_points_an_executed_plan_used_stay_withdrawn(tracks, tmp_path):
    """A track an executed plan placed or timed photos by keeps its points in the record, withdrawn, when it is taken
    out or changed: the evidence of what was written into the photos survives. Back with the same bytes, it is the
    file's again."""
    record = tmp_path / "record.db"
    _build(tracks, record)
    cal.GPXIndex.mark_used(str(record), "plan-1", ["b.gpx", "2024/a.gpx"], JULY)
    data = (tracks / "b.gpx").read_text()
    (tracks / "b.gpx").unlink()
    (tracks / "2024" / "a.gpx").write_text(_gpx(_pt("2024-07-03T12:05:00Z")))           # changed
    idx = _build(tracks, record)
    assert any("b.gpx" in w and "withdrawn" in w for w in idx.warnings)
    assert {p.source_file for p in idx.points} == {"2024/a.gpx"} and len(idx.points) == 1
    withdrawn = _rows(record, "SELECT f.path, COUNT(p.point_index) FROM gpx_track_files f LEFT JOIN gpx_track_points p "
                              "USING (track_id) WHERE f.withdrawn = 1 GROUP BY f.path ORDER BY f.path")
    assert withdrawn == [("2024/a.gpx", 2), ("b.gpx", 1)]
    (tracks / "b.gpx").write_text(data)                                               # back, the same bytes
    back = _build(tracks, record)
    assert "b.gpx" in {p.source_file for p in back.points}
    assert _rows(record, "SELECT COUNT(*) FROM gpx_track_files WHERE path = 'b.gpx'") == [(1,)]


# --- what cannot be checked ------------------------------------------------------------------------------

@pytest.mark.skipif(hasattr(os, "geteuid") and os.geteuid() == 0, reason="root lists every folder")
@pytest.mark.spec("RUL-unlisted_tracks_stop_geotag", "BLD-track_catalogue",
                  test="TST-kept_tracks-a_folder_that_cannot_be_listed_withdraws_nothing")
def test_a_folder_that_cannot_be_listed_withdraws_nothing(tracks, tmp_path):
    """A folder of the tracks that cannot be listed is no folder of no tracks: the index says it cannot see them, and
    nothing it holds is taken for gone."""
    record = tmp_path / "record.db"
    _build(tracks, record)
    os.chmod(tracks / "2024", 0)
    try:
        idx = _build(tracks, record)
    finally:
        os.chmod(tracks / "2024", 0o755)
    assert idx.status == "unlisted" and idx.unlisted[0][0] == "2024" and not idx.gone
    assert _rows(record, "SELECT COUNT(*) FROM gpx_track_files WHERE path = '2024/a.gpx'") == [(1,)]


@pytest.mark.spec("BLD-track_catalogue", test="TST-kept_tracks-execute_leaves_the_catalogue_as_it_was")
def test_execute_leaves_the_catalogue_as_it_was(tracks, tmp_path):
    """Checking the tracks keeps nothing: a changed file is read, and the record is as planning left it."""
    record = tmp_path / "record.db"
    _build(tracks, record)
    before = _rows(record, "SELECT * FROM gpx_track_files ORDER BY track_id")
    (tracks / "b.gpx").write_text(_gpx(_pt("2024-07-03T11:31:00Z", 51.0, 5.0)))
    (tracks / "2024" / "a.gpx").unlink()
    checked = _build(tracks, record, keep=False)
    assert checked.read == 1 and _rows(record, "SELECT * FROM gpx_track_files ORDER BY track_id") == before


@pytest.mark.spec("RUL-sealing_needs_no_tracks", "BLD-track_window", test="TST-kept_tracks-the_kept_points_are_read_without_the_tracks")
def test_the_kept_points_are_read_without_the_tracks(tracks, tmp_path):
    """The points the record keeps give the same index, fingerprint and all, with the tracks folder gone."""
    record = tmp_path / "record.db"
    planned = _build(tracks, record)
    os.rename(tracks, tmp_path / "elsewhere")
    kept = _build(tracks, record, read=False)
    assert kept.status == "kept" and kept.fingerprint == planned.fingerprint
    assert [(p.source_file, p.point_index) for p in kept.points] == [(p.source_file, p.point_index) for p in planned.points]


@pytest.mark.spec("BLD-track_window", "BLD-anchor_matching", "BLD-track_placement",
                  test="TST-kept_tracks-the_window_holds_every_point_a_decision_reaches")
def test_the_window_holds_every_point_a_decision_reaches(tmp_path, monkeypatch):
    """Anchoring and placement decide the same over the window as over every point there is: a week of tracks from two
    ranked devices, broken and sparse, the photos' candidates and placements compared one by one."""
    monkeypatch.setitem(utils.CONFIG, "gpx_anchor_max_clock_error_seconds", 3 * 3600)
    root = tmp_path / "gpx"
    (root / "phone").mkdir(parents=True)
    week = [f"2024-07-{d:02d}T{h:02d}:{m:02d}:00Z" for d in range(1, 9) for h in range(24) for m in (0, 20, 40)
            if not (d == 3 and 13 <= h < 15)]                       # a gap of two hours on the 3rd
    (root / "logger.gpx").write_text(_gpx(*(_pt(t, 50 + i * 1e-4, 4 + i * 1e-4) for i, t in enumerate(week))))
    (root / "phone" / "p.gpx").write_text(
        '<gpx xmlns="http://www.topografix.com/GPX/1/1"><trk><trkseg>'
        + "".join(_pt(f"2024-07-03T{h:02d}:{m:02d}:00Z", 50.1, 4.1) for h in (10, 11) for m in range(0, 60, 5))
        + '</trkseg><trkseg>' + _pt("2024-07-03T12:30:00Z", 50.2, 4.2) + '</trkseg></trk></gpx>')
    prec = ["phone"]
    full = cal.GPXIndex(str(root), None, prec).build()
    # by the phone; by the phone past a break; by the logger at its gap's edge; by the logger at a time the phone
    # covers (no candidate); by the logger only days before (none in the window either)
    times = ["2024:07:03 10:00:00", "2024:07:03 12:10:00", "2024:07:03 14:05:00", "2024:07:03 11:00:00",
             "2024:07:03 12:00:00"]
    files = _files(*times, native=True)
    for f, (lat, lon) in zip(files, [(50.1, 4.1), (50.2, 4.2), (50.0183, 4.0183), (50.0175, 4.0175), (50.0, 4.0)]):
        f["native_gps"] = {"lat": lat, "lon": lon}
    anchoring = cal.GPXIndex(str(root), None, prec).build(window=cal.GeotagWorkflow.camera_window(files))
    assert len(anchoring.points) < len(full.points)
    found = [cal.frame_candidates(f, full, utils.CONFIG) for f in files]
    assert [len(c) for c in found] == [1, 1, 2, 0, 0]
    assert [cal.frame_candidates(f, anchoring, utils.CONFIG) for f in files] == found
    targets = [_at(t) for t in ("2024-07-03T10:31:00Z", "2024-07-03T12:31:00Z", "2024-07-03T13:02:00Z",
                                "2024-07-03T14:59:00Z", "2024-07-05T03:33:20Z", "2024-07-08T23:44:00Z")]
    rows = [{"relative_path": f"6/T/{i}.arw", "resolved_utc_status": "valid",
             "resolved_utc": t.strftime("%Y-%m-%dT%H:%M:%SZ")} for i, t in enumerate(targets)]
    placing = cal.GPXIndex(str(root), None, prec).build(
        window=cal.GeotagWorkflow.placement_window(_files(*["x"] * len(targets)), rows))
    assert len(placing.points) < len(full.points)
    placed = [cal.place_gps(t, full, utils.CONFIG) for t in targets]
    assert [p and p["method"] for p in placed] == ["direct_match", "direct_match", None, "direct_match",
                                                   "interpolated", "extrapolated"]
    assert [cal.place_gps(t, placing, utils.CONFIG) for t in targets] == placed


@pytest.mark.spec("BLD-track_points", "RUL-track_is_one_trk", "RUL-track_break_never_bridged",
                  test="TST-kept_tracks-a_kept_point_keeps_its_track_and_segment")
def test_a_kept_point_keeps_its_track_and_segment(tmp_path):
    """A point read from the record is the point parsing gave: its <trk> and its <trkseg> with it."""
    root = tmp_path / "gpx"
    root.mkdir()
    pt = lambda m: _pt(f"2024-07-03T12:{m:02d}:00Z")
    (root / "t.gpx").write_text('<gpx xmlns="http://www.topografix.com/GPX/1/1"><trk><trkseg>' + pt(0)
                                + '</trkseg><trkseg>' + pt(1) + '</trkseg></trk><trk><trkseg>' + pt(2)
                                + '</trkseg></trk></gpx>')
    record = tmp_path / "record.db"
    idx = cal.GPXIndex(str(root), str(record)).build(window=JULY)
    again = cal.GPXIndex(str(root), str(record)).build(window=JULY)
    assert again.read == 0
    assert [(p.track, p.segment) for p in again.points] == [(p.track, p.segment) for p in idx.points] \
        == [(0, 0), (0, 1), (1, 0)]


# --- points outside the window are not kept ---------------------------------------------------------------

FOURTH = [cal.around(_at("2024-07-04T12:00:00Z"), 3600)]            # a second window, a day later


def _kept(record):
    return _rows(record, "SELECT f.path, p.time_utc FROM gpx_track_points p JOIN gpx_track_files f USING (track_id) "
                         "ORDER BY f.path, p.point_index")


@pytest.fixture
def two_days(tmp_path):
    root = tmp_path / "gpx2"
    root.mkdir()
    (root / "a.gpx").write_text(_gpx(_pt("2024-07-03T12:00:00Z"), _pt("2024-07-04T12:00:00Z", 50.2)))
    (root / "b.gpx").write_text(_gpx(_pt("2024-07-03T11:30:00Z", 51.0, 5.0), _pt("2024-07-04T11:30:00Z", 51.2, 5.0)))
    return root


@pytest.mark.spec("RUL-track_points_kept", "RUL-unused_points_not_kept", "BLD-track_catalogue",
                  test="TST-kept_tracks-a_narrower_window_prunes_the_points_outside_it")
def test_a_narrower_window_prunes_the_points_outside_it(two_days, tmp_path):
    """A plan whose window narrows — a photo moved out, a setting tightened — leaves the record holding only its
    window's points: those outside it go, the fingerprint is the one the narrow window gives, and the file is read
    again if a later window reaches there."""
    record = tmp_path / "record.db"
    wide = _build(two_days, record, window=cal.window_union(JULY, FOURTH))
    wide.prune()
    assert len(_kept(record)) == 4                                     # its own window: nothing goes
    narrow = _build(two_days, record, window=JULY)
    fp = narrow.fingerprint
    narrow.prune()
    assert _kept(record) == [("a.gpx", "2024-07-03T12:00:00+00:00"), ("b.gpx", "2024-07-03T11:30:00+00:00")]
    again = _build(two_days, record, window=JULY)
    assert again.read == 0 and again.fingerprint == fp                 # the window's points untouched
    assert cal.GPXIndex(str(two_days), None, ["2024"]).build(window=JULY).fingerprint == fp
    assert _build(two_days, record, window=FOURTH).read == 2           # pruned, so read again when reached


@pytest.mark.spec("RUL-unused_points_not_kept", "RUL-withdrawn_track_points_kept", "BLD-track_catalogue", "BLD-withdrawn_track_points",
                  test="TST-kept_tracks-points_an_executed_plan_used_survive_a_narrower_window")
def test_points_an_executed_plan_used_survive_a_narrower_window(two_days, tmp_path):
    """The points of a track an executed plan placed or timed photos by, in the window that plan was made in, stay
    when a later plan's window no longer reaches them: they are the evidence of what was written into the photos. A
    track it did not use is pruned."""
    record = tmp_path / "record.db"
    both = cal.window_union(JULY, FOURTH)
    _build(two_days, record, window=both)
    cal.GPXIndex.mark_used(str(record), "plan-1", ["a.gpx"], both)
    narrow = _build(two_days, record, window=JULY)
    narrow.prune()
    assert _kept(record) == [("a.gpx", "2024-07-03T12:00:00+00:00"), ("a.gpx", "2024-07-04T12:00:00+00:00"),
                             ("b.gpx", "2024-07-03T11:30:00+00:00")]
    assert [p.time_utc for p in narrow.points if p.source_file == "a.gpx"] == [_at("2024-07-03T12:00:00Z")]
    assert _build(two_days, record, window=JULY).fingerprint == narrow.fingerprint
    # what the executed plan used is kept for finalize, which reads no track
    os.rename(two_days, tmp_path / "elsewhere")
    kept = _build(two_days, record, window=both, read=False)
    assert {(p.source_file, p.time_utc) for p in kept.points} >= {("a.gpx", _at("2024-07-04T12:00:00Z"))}


@pytest.mark.spec("BLD-track_catalogue", test="TST-kept_tracks-a_build_that_kept_nothing_prunes_nothing")
def test_a_build_that_kept_nothing_prunes_nothing(two_days, tmp_path):
    """Execute's check keeps nothing, and prunes nothing: the record is as planning left it."""
    record = tmp_path / "record.db"
    _build(two_days, record, window=cal.window_union(JULY, FOURTH))
    _build(two_days, record, window=JULY, keep=False).prune()
    assert len(_kept(record)) == 4


MANAGED = ["0-sources", "1-strays", "2-missing-metadata", "3-redundant-jpgs",
           "4-videos-by-date", "5-photos-by-date", "6-photos-by-dest"]
CAM = "SONY|ILCE-6400|123"


@pytest.mark.parametrize("how", ["asks", "blocked", "interrupted"])
@pytest.mark.spec("BLD-track_catalogue", test="TST-kept_tracks-geotag_plan_prunes_once_it_has_stopped")
def test_geotag_plan_prunes_once_it_has_stopped(tmp_path, monkeypatch, how):
    """`geotag plan` prunes the record to the window it reached once it has stopped — at a decision for the user, or
    at a blocker — never mid-run, where a window still to widen would read its files again, and never when
    interrupted."""
    ws = tmp_path / "ws"; ws.mkdir()
    for m in MANAGED:
        (ws / m).mkdir()
    ctl = ws / ".photos-ingest"; ctl.mkdir()
    (ctl / "photos-00-workspace-guard").touch()
    root = tmp_path / "gpx"; root.mkdir()
    (root / "t.gpx").write_text(_gpx(_pt("2019-05-01T10:00:00Z"), _pt("2024-07-03T12:00:00Z")))
    cfg = {k: v for k, v in utils.CONFIG.items() if k != "jobs"}
    cfg["gpx_root"] = str(root)
    cfg["camera_time_and_timezone_policy"] = dict(
        cfg["camera_time_and_timezone_policy"], device_groups={"fixed_clock_cameras": [CAM], "phones": []})
    (ctl / "photos-00-config.json").write_text(json.dumps(cfg))
    rel = "6-photos-by-dest/T/a.arw"
    dto = "2024:07:03 12:00:00"
    parsed = {"DateTimeOriginal": dto, "selected_source_naive_timestamp": dto,
              "selected_source_timestamp_tag": "EXIF:DateTimeOriginal", "camera_group_key": CAM, "has_timestamp": True}
    files = [{"relative_path": rel, "media_class": "image", "folder_class": "6-photos-by-dest", "size": 1,
              "mtime_ns": 1, "content_hash": json.dumps({"value": "fp-a", "status": "valid"}),
              "metadata_status": {"camera_group_key_version": utils.CAMERA_GROUP_KEY_VERSION,
                                  "camera_group_key": CAM, "has_timestamp": True, "has_native_gps": False,
                                  "field_set_version": utils.FIELD_SET_VERSION, "parsed_json": json.dumps(parsed)}}]
    (ws / rel).parent.mkdir(parents=True); (ws / rel).write_bytes(b"x")
    (ctl / "photos-11-handoff.json").write_text(json.dumps(vouched(ctl.parent, {
        "filename_timestamp_format": utils.CONFIG["filename_timestamp_format"], "files": match_disk(ws, files),
        "depends_on": {"cache": {"fingerprint_algorithm_version": utils.FINGERPRINT_ALGORITHM_VERSION}}})))
    record = utils.db_path(str(ws))
    cal.GPXIndex(str(root), record, []).build()                        # an earlier window held every point
    assert len(_kept(record)) == 2
    if how != "asks":
        def stop(*a, **k):
            raise KeyboardInterrupt if how == "interrupted" else SystemExit(2)
        monkeypatch.setattr(cal.GeotagWorkflow, "build_time_decisions", stop)
    monkeypatch.chdir(str(ws))
    monkeypatch.setattr(sys, "argv", ["photos-2-geotag", "plan"])
    with pytest.raises(SystemExit) as e:
        cal.main()
        raise SystemExit(0)
    assert e.value.code == {"asks": 0, "blocked": 2, "interrupted": 130}[how]
    assert _kept(record) == ([("t.gpx", "2019-05-01T10:00:00+00:00"), ("t.gpx", "2024-07-03T12:00:00+00:00")]
                             if how == "interrupted" else [("t.gpx", "2024-07-03T12:00:00+00:00")])
