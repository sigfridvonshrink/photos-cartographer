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

"""Geotag reads every track whole on every run — the fingerprint checks its bytes — but parses only
a track whose bytes it has not parsed before; the memo it keeps for that is scratch (shared §10)."""
import os
import sqlite3

import pytest

import photos_2_geotag as cal
import photos_utils as utils

TRK = ('<gpx xmlns="http://www.topografix.com/GPX/1/1"><trk><trkseg>'
       '<trkpt lat="50.8467" lon="4.3525"><time>2024-07-03T12:12:21.250Z</time></trkpt>'
       '<trkpt lat="91" lon="4"><time>2024-07-03T12:13:00Z</time></trkpt>'
       '<trkpt lat="50.8480" lon="4.3540"><time>{t}</time></trkpt>'
       '</trkseg></trk></gpx>')


def _build(root, memo):
    return cal.GPXIndex(str(root), str(memo)).build()


def _seen(idx):
    return (idx.fingerprint, idx.status, [(p.lat, p.lon, p.time_utc, p.source_file, p.point_index)
                                          for p in idx.points], idx.warnings)


@pytest.fixture
def tracks(tmp_path):
    root = tmp_path / "gpx"
    (root / "2024").mkdir(parents=True)
    (root / "2024" / "a.gpx").write_text(TRK.format(t="2024-07-03T12:14:21Z"))
    (root / "b.GPX").write_text("<gpx><trk")                                  # malformed
    return root


@pytest.mark.spec("RUL-reuse_valid_work", test="TST-track_memo-unchanged_track_is_not_parsed_again")
def test_unchanged_track_is_not_parsed_again(tracks, tmp_path):
    memo = tmp_path / "memo.db"
    first = _build(tracks, memo)
    assert (first.parsed, first.reused) == (2, 0)
    again = _build(tracks, memo)
    assert (again.parsed, again.reused) == (0, 2)
    assert _seen(again) == _seen(first)                                      # literally no difference
    assert _seen(first) == _seen(cal.GPXIndex(str(tracks)).build())          # nor from no memo at all
    assert any("Out-of-range" in w and "2024/a.gpx" in w for w in first.warnings)
    assert any("Malformed" in w and "b.GPX" in w for w in first.warnings)


@pytest.mark.spec("RUL-reuse_valid_work", "RUL-tracks_in_dependencies", test="TST-track_memo-changed_track_is_parsed_again")
def test_changed_track_is_parsed_again(tracks, tmp_path):
    memo = tmp_path / "memo.db"
    first = _build(tracks, memo)
    (tracks / "2024" / "a.gpx").write_text(TRK.format(t="2024-07-03T12:15:00Z"))
    again = _build(tracks, memo)
    assert (again.parsed, again.reused) == (1, 1)
    assert again.fingerprint != first.fingerprint
    assert _seen(again) == _seen(cal.GPXIndex(str(tracks)).build())


@pytest.mark.spec("RUL-other_databases_scratch", test="TST-track_memo-memo_is_scratch")
def test_memo_is_scratch(tracks, tmp_path):
    memo = tmp_path / "memo.db"
    first = _build(tracks, memo)
    (tracks / "b.GPX").unlink()                                              # a track gone: its entry follows
    _build(tracks, memo)
    assert sqlite3.connect(memo).execute("SELECT COUNT(*) FROM track_memo").fetchone()[0] == 1
    memo.unlink()                                                            # deleting it loses nothing
    assert _build(tracks, memo).fingerprint == cal.GPXIndex(str(tracks)).build().fingerprint
    memo.write_bytes(b"not a database")                                      # a broken one is replaced
    assert _build(tracks, memo).fingerprint == cal.GPXIndex(str(tracks)).build().fingerprint
    assert _build(tracks, memo).reused == 1
    assert first.fingerprint != _build(tracks, memo).fingerprint             # (b.GPX is gone)
    ws = tmp_path / "ws"
    assert utils._not_archived(os.path.basename(utils.track_memo_db_path(str(ws))))


@pytest.mark.spec("RUL-reuse_valid_work", test="TST-track_memo-geotag_keeps_the_memo_in_the_control_directory")
def test_geotag_keeps_the_memo_in_the_control_directory(tracks, tmp_path, monkeypatch):
    ws = tmp_path / "ws"
    (ws / ".photos-ingest").mkdir(parents=True)
    monkeypatch.setitem(utils.CONFIG, "gpx_root", str(tracks))
    wf = cal.GeotagWorkflow(str(ws))
    assert wf.load_gpx().parsed == 2
    assert os.path.exists(utils.track_memo_db_path(str(ws)))
    assert wf.load_gpx().reused == 2
