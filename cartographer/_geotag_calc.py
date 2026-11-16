#!/usr/bin/env python3
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

"""Pure geotag calculations — GPX geometry/indexing, time/UTC resolution, GPS placement, and
op/rename builders. Stateless functions (+ the GPXPoint/GPXIndex value objects), extracted from
photos_2_geotag.py; the GeotagWorkflow orchestration + CLI stay there and re-export these via
`from ._geotag_calc import *`. Imports the shared infra from photos_utils, exactly as the phase
module does."""

import argparse
import bisect
import concurrent.futures
import hashlib
import json
import math
import os
import re
import sqlite3
import subprocess
import sys
import xml.etree.ElementTree as ET
import zoneinfo
from datetime import datetime, timedelta, timezone

from .photos_utils import (
    valid_iana_timezone,
    CONFIG, CONTROL_DIR, config_path, handoff_path, guard_path, is_sealed,
    validate_config, sha256_file, sha256_text, media_class_for_ext, folder_name,
    folders_fingerprint, media_extensions_fingerprint,
    selected_gpx_root, is_gpx_file, FIELD_SET_VERSION, CAMERA_GROUP_KEY_VERSION, FOLDER_ROLES,
    parse_naive_time, has_own_position, NO_IDENTITY_KEY, OTHER_TIME_FIELDS,
    missing_managed_folders, by_dest_reprep_pending,
    json_dependency, verify_json_dependency, handoff_content_fingerprint, write_json_artifact, write_versioned_json, db_path, ensure_control_dir,
    journal_path, ContentHasher, _move_no_clobber, allocate_suffix, allocate_stem, carries_stem,
    prep_log_path, write_db_snapshot, take_zfs_snapshot,
    WorkspaceLock, ProgressCoordinator,
)
from .reporting import get_reporter

__all__ = [
    'DECISION_RECORD_DEPS',
    'describe_offset',
    'offset_decision_pointer',
    'manual_gps_pointer',
    'ORIGINAL_KEYS',
    'own_values',
    'from_originals',
    'device_method',
    'held_values',
    'TIME_PAIR',
    'held_other_times',
    'changed_time_blocker',
    'changed_time',
    'keep_true_time',
    'kept_tag_disagreement',
    'utc_offset_text',
    'CHANGED_TIME_ANSWERS',
    'POSITION_MARKERS',
    'TIME_FIXED_SUFFIX',
    'geotag_marker',
    'with_time_fixed',
    'time_fixed_marker_op',
    'haversine',
    'GPXPoint',
    'GPXIndex',
    'window_union',
    'valid_window',
    'around',
    'open_track_record',
    '_valid_iana',
    '_offsets_against_zone',
    '_zone_from_photos',
    '_ZONE_WAITS',
    '_valid_offset',
    '_parse_camera_naive',
    '_naive_date',
    'date_fallback_day',
    'untimed',
    'date_fallback_time',
    '_parse_utc',
    '_equirect_xy',
    '_point_to_segment',
    '_candidate',
    'frame_candidates',
    '_frame_skip_reason',
    '_timezone_naive_offset',
    '_zone_ambiguity',
    'unreadable_offset_tag',
    'AMBIGUOUS_RULES',
    'infer_anchor_proposal',
    'contradicted_frames',
    'clock_change_proposal',
    'offset_cell_key',
    'gps_readings',
    '_parse_iso_offset',
    '_local_to_utc',
    'drift_offset_overrides',
    'OFFSET_TAG_FOR',
    'clock_group_key',
    '_own_offset',
    '_read_offset',
    'recorded_offset_proposal',
    'gps_fix_utc',
    'gps_time_proposal',
    'GPS_TIMES_SHOWN',
    'far_from_evidence',
    'compute_resolved_utc',
    'resolved_utc_fingerprint',
    '_interp',
    '_extrapolate',
    'place_gps',
    '_valid_coord',
    '_GPS_PLACE_CATEGORY',
    'classify_gps',
    'held_pre_state',
    'holds_no_fix',
    'held_time_pre_state',
    '_coordinate_tags',
    '_CLEARED_POSITION',
    '_walk_ancestors',
    '_nearest_ancestor',
    '_expand_destinations',
    '_ask_zone_at_containers',
    '_dest_label',
    'destination_local_basename',
    'plan_renames',
    'plan_set_aside_rename',
    'recorded_sub_second',
    '_GPS_OP_ORIGIN',
    '_GPS_OP_MARKER',
    '_TRACK_MARKER',
    '_local_time_and_offset',
    '_make_op',
    'plan_file_ops',
    'build_complete_log',
    'geotag_execution_status',
    'repeated_write_failures',
]

def haversine(lat1, lon1, lat2, lon2):
    """Great-circle distance between two lat/lon points, in metres."""
    R = 6371000.0
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlmb = math.radians(lon2 - lon1)
    a = math.sin(dphi / 2.0) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(dlmb / 2.0) ** 2
    a = min(1.0, a)                        # rounding can carry an antipodal pair a hair past 1
    return R * (2.0 * math.atan2(math.sqrt(a), math.sqrt(1 - a)))


class GPXPoint:
    __slots__ = ("lat", "lon", "time_utc", "source_file", "point_index", "track", "segment")

    def __init__(self, lat, lon, time_utc, source_file, point_index, track=0, segment=0):
        self.lat = lat
        self.lon = lon
        self.time_utc = time_utc          # timezone-aware UTC datetime
        self.source_file = source_file
        self.point_index = point_index
        # which <trk> of its file the point is of, and which <trkseg> of that track (RUL-track_is_one_trk,
        # RUL-track_break_never_bridged); -1 for a point outside any
        self.track = track
        self.segment = segment


_EARTH_RADIUS_M = 6371000.0
_GRID_PER_DEGREE = 200                    # a grid cell is 1/200 degree a side: some 550 m north to south
_GRID_COLUMNS = 360 * _GRID_PER_DEGREE
_GRID_MAX_CELLS = 64                      # a point or segment reaching over more cells is looked at from everywhere


def _grid_cell(lat, lon):
    """The grid cell of a place, its longitude in [-180, 180]."""
    return math.floor(lat * _GRID_PER_DEGREE), math.floor(lon * _GRID_PER_DEGREE) % _GRID_COLUMNS


def _grid_enter(cells, i, lat0, lat1, lon0, lon1):
    """Enter `i` in every cell the box [lat0, lat1] x [lon0, lon1] (degrees; longitude unwrapped) reaches into;
    False, entering nothing, when that is more than `_GRID_MAX_CELLS`."""
    r0, r1 = math.floor(lat0 * _GRID_PER_DEGREE), math.floor(lat1 * _GRID_PER_DEGREE)
    c0, c1 = math.floor(lon0 * _GRID_PER_DEGREE), math.floor(lon1 * _GRID_PER_DEGREE)
    if (r1 - r0 + 1) * (c1 - c0 + 1) > _GRID_MAX_CELLS:
        return False
    for r in range(r0, r1 + 1):
        for c in range(c0, c1 + 1):
            hits = cells.setdefault((r, c % _GRID_COLUMNS), [])
            if not hits or hits[-1] != i:
                hits.append(i)
    return True


def _on_globe(*pts):
    return all(math.isfinite(p.lat) and math.isfinite(p.lon) and -90.0 <= p.lat <= 90.0 for p in pts)


def _proximity_grid(pts, pt_max, seg_max):
    """`(cells, wide)` for one track's points in time order: `cells` maps a grid cell to the sorted indices `i`
    whose point lies within `pt_max` metres — by `haversine` — of some place in the cell, or whose segment to point
    `i + 1` of the same `<trkseg>` within `seg_max` — by `_point_to_segment` — of one; `wide`, the sorted indices of
    the points and segments too wide to enter, which every place may touch. Each box is a bound the measure cannot
    exceed, widened past rounding: a place a point or segment is within reach of is always in a cell it entered."""
    cells, wide = {}, []
    widen, pad = 1.001, 1e-7
    half = pt_max / (2.0 * _EARTH_RADIUS_M)
    sin_half = math.sin(half) if 0.0 <= half <= math.pi / 2 else None
    dlat_pt = math.degrees(pt_max / _EARTH_RADIUS_M) * widen + pad
    dlat_seg = math.degrees(seg_max / _EARTH_RADIUS_M) * widen + pad
    for i, p in enumerate(pts):
        ok = sin_half is not None and _on_globe(p)
        if ok:
            # haversine within pt_max: the latitudes differ by at most dlat_pt, and
            # cos(lat1)·cos(lat2)·sin²(Δlon/2) <= sin²(pt_max / 2R), each cosine at least that of |lat| + dlat_pt
            top = abs(p.lat) + dlat_pt
            cos_top = math.cos(math.radians(top)) if top < 90.0 else 0.0
            ok = cos_top > 0.0 and sin_half / cos_top < 1.0
            if ok:
                dlon = math.degrees(2.0 * math.asin(sin_half / cos_top)) * widen + pad
                lon = _wrap_lon(p.lon)
                ok = _grid_enter(cells, i, p.lat - dlat_pt, p.lat + dlat_pt, lon - dlon, lon + dlon)
        if not ok:
            wide.append(i)
        if i + 1 < len(pts) and pts[i + 1].segment == p.segment:
            b = pts[i + 1]
            ok = seg_max >= 0.0 and _on_globe(p, b)
            if ok:
                # in the plane about p, a place within seg_max of the segment is within seg_max of a point of it
                # on each axis: its latitude, and its longitude scaled by cos(p.lat)
                cos_a = math.cos(math.radians(p.lat))
                ok = cos_a > 1e-3
                if ok:
                    dlon = math.degrees(seg_max / (_EARTH_RADIUS_M * cos_a)) * widen + pad
                    step, lon = _lon_delta(p.lon, b.lon), _wrap_lon(p.lon)
                    ok = _grid_enter(cells, i, min(p.lat, b.lat) - dlat_seg, max(p.lat, b.lat) + dlat_seg,
                                     lon + min(0.0, step) - dlon, lon + max(0.0, step) + dlon)
            if not ok and (not wide or wide[-1] != i):
                wide.append(i)
    return cells, wide


_REL = "\x00rel\x00"            # stands for the file's path in a parse's warnings: a parse is of bytes, wherever they lie
GPX_PARSE_VERSION = "gpx-parse-v3"   # bump when the parse below changes what it yields: a track file kept under
                                     # another version is read and parsed again, as a new entry of the catalogue

# Every instant there is, in seconds: the window of an index built without one.
ALL_TIME = [(-(2 ** 62), 2 ** 62)]


def window_union(*windows):
    """The union of windows — each a list of (start, end), whole seconds since the epoch in UTC, both ends in it —
    as one sorted list of disjoint spans (BLD-track_window)."""
    out = []
    for a, b in sorted((int(a), int(b)) for w in windows for a, b in (w or ()) if a <= b):
        if out and a <= out[-1][1]:
            out[-1] = (out[-1][0], max(out[-1][1], b))
        else:
            out.append((a, b))
    return out


def window_minus(window, kept):
    """The parts of `window` outside `kept` (both unions), their ends included."""
    out = []
    for a, b in window:
        cur = a
        for c, d in kept:
            if d < cur or c > b:
                continue
            if c > cur:
                out.append((cur, c))
            cur = max(cur, d)
            if cur >= b:
                break
        if cur < b:
            out.append((cur, b))
    return out


def window_intersect(a, b):
    """The instants in both `a` and `b` (both unions), as a union."""
    out = []
    for x, y in a:
        for c, d in b:
            lo, hi = max(x, c), min(y, d)
            if lo <= hi:
                out.append((lo, hi))
    return window_union(out)


def around(t, reach):
    """The span `reach` seconds each side of the instant `t` (an aware datetime), widened to whole seconds."""
    x = t.timestamp()
    return (math.floor(x - reach), math.ceil(x + reach))


def _within(window, x):
    """Whether the instant `x` (seconds since the epoch) lies in `window`, a union."""
    i = bisect.bisect_right(window, (x, float("inf"))) - 1
    return i >= 0 and window[i][0] <= x <= window[i][1]


def valid_window(w):
    """`w` as a union, when it is a list of [start, end] whole seconds with start <= end; else None."""
    if not isinstance(w, list):
        return None
    out = []
    for span in w:
        if not (isinstance(span, (list, tuple)) and len(span) == 2
                and all(isinstance(x, int) and not isinstance(x, bool) for x in span) and span[0] <= span[1]):
            return None
        out.append(tuple(span))
    return window_union(out)


_TRACK_TABLES = (
    # the catalogue (BLD-track_catalogue): one entry per track file as it was read — its path under gpx_root, the
    # folder directly under gpx_root it is filed in (its rank's), the size, modification time and inode it was read
    # at, the SHA-256 of its bytes, the parse that read it, the first and last of its points' times, the window its
    # kept points cover, its warnings, why it could not be parsed (none: it was), and whether it is withdrawn
    "CREATE TABLE IF NOT EXISTS gpx_track_files (track_id INTEGER PRIMARY KEY, path TEXT NOT NULL, "
    "rank_folder TEXT NOT NULL, size INTEGER, mtime_ns INTEGER, inode INTEGER, sha256 TEXT NOT NULL, "
    "parse_version TEXT NOT NULL, first_utc TEXT, last_utc TEXT, covered TEXT NOT NULL, warnings TEXT NOT NULL, "
    "unreadable TEXT, withdrawn INTEGER NOT NULL DEFAULT 0, UNIQUE (path, sha256, parse_version))",
    # the points of each entry that fall in the window it covers, as decided on
    "CREATE TABLE IF NOT EXISTS gpx_track_points (track_id INTEGER NOT NULL, point_index INTEGER NOT NULL, "
    "time_utc TEXT NOT NULL, lat REAL NOT NULL, lon REAL NOT NULL, track INTEGER NOT NULL, "
    "segment INTEGER NOT NULL, PRIMARY KEY (track_id, point_index))",
    # the entries each executed plan placed or timed photos by, with the window it was made in
    # (BLD-withdrawn_track_points): their points in it stay whatever later windows reach (BLD-track_catalogue)
    "CREATE TABLE IF NOT EXISTS gpx_track_use (plan_id TEXT NOT NULL, track_id INTEGER NOT NULL, "
    "window TEXT NOT NULL, PRIMARY KEY (plan_id, track_id))",
)


def open_track_record(record):
    """A connection to the track region of the database of record (BLD-track_catalogue), its tables made; `record`
    None is a database of no file, gone with the connection."""
    conn = sqlite3.connect(record or ":memory:")
    conn.row_factory = sqlite3.Row
    for ddl in _TRACK_TABLES:
        conn.execute(ddl)
    conn.commit()
    return conn


def _epoch(iso):
    return datetime.fromisoformat(iso).timestamp()


class GPXIndex:
    """The track points geotag decides by — those in its window (BLD-track_window) — and their fingerprint.

    Availability is recorded in `status` (disabled / missing / unlisted / unreadable / empty / usable / kept). The
    `fingerprint` is a SHA-256 over the ranking and each point in the window (BLD-gpx_fingerprint) — it becomes an
    upstream dependency of the time/GPS artifacts (RUL-tracks_in_dependencies), and tracks of other times leave it as
    it is (RUL-tracks_elsewhere_restale_nothing).

    The record keeps a catalogue of every track file under gpx_root and the points of each in the window
    (BLD-track_catalogue): a file whose size, modification time and inode are as the catalogue has them is not read
    again, unless the window has grown into its span; a new or changed one is read and parsed. `record` None keeps
    nothing past the build: every file is read."""

    def __init__(self, gpx_root, record=None, precedence=()):
        self.gpx_root = gpx_root
        self.record = record
        # the folders under gpx_root, best device first (RUL-tracks_ranked_by_folder)
        self.precedence = list(precedence or ())
        self.points = []
        self.fingerprint = None
        self.status = "disabled"
        self.warnings = []
        self.window = []
        self.read = 0                      # track files read this build
        self.catalogued = False            # whether this build kept the catalogue over its window
        self._tracks = None
        self._grids = None                 # (key, [(cells, wide)] per track) — see nearby()
        self._any_points = False
        self.file_sha = {}                 # each track file's SHA-256, by its path under gpx_root
        self.unreadable = []               # [(file, why)] of the track files that could not be read or parsed
        self.unlisted = []                 # [(folder, why)] of the folders under gpx_root that could not be listed
        self.gone = []                     # the track files the catalogue had and gpx_root no longer holds

    def tracks(self):
        """The points as separate tracks — `[(file, points in time order, their times)]`, by file name, then by
        the track's place in it. Each `<trk>` is one device's record of where it was (RUL-track_is_one_trk): two
        that overlap in time — two files, or two tracks of one export — are two devices, perhaps two people, so
        no placement and no anchor ever joins a point of one to a point of another. Within a track, a point
        keeps its `<trkseg>`: nothing is placed or anchored across a break between two (RUL-track_break_never_bridged)."""
        if self._tracks is None or self._tracks[0] != (id(self.points), len(self.points)):
            by_track = {}
            for p in sorted(self.points, key=lambda p: (p.time_utc, p.point_index)):
                by_track.setdefault((p.source_file, p.track), []).append(p)
            self._tracks = ((id(self.points), len(self.points)),
                            [(f, pts, [p.time_utc for p in pts]) for (f, _t), pts in sorted(by_track.items())])
        return self._tracks[1]

    def nearby(self, lat, lon, pt_max, seg_max, spans=None):
        """For each track of `tracks()`, in its order, the sorted indices of its points a photo at (`lat`, `lon`)
        can touch — a point within `pt_max` metres of it, a segment from one point to the next within `seg_max` —
        and the indices on either side, within that track's `(lo, hi)` of `spans` (None: all its points); every
        index left out it touches nothing at. None when the place is no place on the globe: then any index can.
        Read from a grid of each track's points and segments, built once per radius pair, so an anchor search
        measures only what passes by the photo's place, not every point of its window (BLD-anchor_matching)."""
        if not (math.isfinite(lat) and math.isfinite(lon) and -90.0 <= lat <= 90.0):
            return None
        tracks = self.tracks()
        key = (self._tracks[0], pt_max, seg_max)
        if self._grids is None or self._grids[0] != key:
            self._grids = (key, [_proximity_grid(pts, pt_max, seg_max) for _f, pts, _t in tracks])
        cell = _grid_cell(lat, _wrap_lon(lon))
        out = []
        for k, (cells, wide) in enumerate(self._grids[1]):
            lo, hi = spans[k] if spans is not None else (0, len(tracks[k][1]))
            near = set()
            for hits in (cells.get(cell, ()), wide):
                # one index either side of the span: its neighbour inside may be the one touched
                near.update(hits[bisect.bisect_left(hits, lo - 1):bisect.bisect_right(hits, hi)])
            out.append(sorted({j for i in near for j in (i - 1, i, i + 1) if lo <= j < hi}))
        return out

    def rank(self, rel):
        """The rank of the track file at `rel` under gpx_root (RUL-tracks_ranked_by_folder): the place of the
        folder directly under gpx_root it is filed in among `precedence`, 0 the best; a file in no ranked
        folder ranks below every ranked one, all such files alike."""
        top = rel.split("/", 1)[0] if "/" in rel else None
        return self.precedence.index(top) if top in self.precedence else len(self.precedence)

    def ranked(self):
        """True when the tracks are of more than one rank — where precedence matters at all."""
        return len({self.rank(f) for f, _p, _t in self.tracks()}) > 1

    def build(self, coordinator=None, window=None, keep=True, read=True):
        """Index the points in `window` (a list of (start, end) whole seconds; None: every point). `keep` False
        leaves the record as it was: execute checks the tracks, planning keeps them. `read` False reads nothing
        under gpx_root — the points are those the record keeps (finalize, RUL-sealing_needs_no_tracks)."""
        self.window = window_union(window) if window is not None else list(ALL_TIME)
        self.points, self.warnings, self.file_sha, self.unreadable, self.unlisted = [], [], {}, [], []
        self.read, self._any_points, self.catalogued = 0, False, False
        if not self.gpx_root:
            self.status = "disabled"
            self.fingerprint = hashlib.sha256(b"gpx-disabled-v1").hexdigest()
            return self
        if not read:
            conn = open_track_record(self.record)
            try:
                for row in conn.execute("SELECT * FROM gpx_track_files WHERE withdrawn = 0 ORDER BY path").fetchall():
                    self._take(conn, dict(row))
            finally:
                conn.close()
            self._finish()
            self.status = "kept"
            return self
        if not os.path.isdir(self.gpx_root):
            self.status = "missing"
            self.warnings.append(f"Configured gpx_root does not exist or is not a directory: {self.gpx_root}")
            self.fingerprint = hashlib.sha256(("gpx-missing|" + self.gpx_root).encode()).hexdigest()
            return self

        # a ranked folder that is not there ranks nothing, and is said (RUL-ranked_folder_missing_told)
        self.warnings.extend(f"gpx_track_precedence names {name!r}, which is not a folder directly under gpx_root: "
                             f"no track ranks by it" for name in self.precedence
                             if not os.path.isdir(os.path.join(self.gpx_root, name))
                             or os.path.islink(os.path.join(self.gpx_root, name)))
        gpx_files, linked = [], []

        def unlisted(e):
            where = os.path.relpath(e.filename, self.gpx_root) if getattr(e, "filename", None) else "."
            self.unlisted.append((where, e.strerror or str(e)))
        for r, dirs, files in os.walk(self.gpx_root, onerror=unlisted):
            gpx_files.extend((os.path.relpath(os.path.join(r, f), self.gpx_root), os.path.join(r, f))
                             for f in files if is_gpx_file(f))
            # the walk never follows a linked folder: the tracks in it are not read, and that is said
            # (RUL-unreadable_tracks_stop_geotag)
            linked.extend(os.path.relpath(os.path.join(r, d), self.gpx_root) for d in dirs
                          if os.path.islink(os.path.join(r, d)))
        if self.unlisted:
            # a folder of the tracks that cannot be listed: what is in it cannot be checked, and counts as changed
            # (RUL-unlisted_tracks_stop_geotag) — nothing in the record is withdrawn for not being seen
            self.status = "unlisted"
            self.warnings.extend(f"Could not list {where!r} under gpx_root: {why}" for where, why in self.unlisted)
            self.fingerprint = hashlib.sha256(("gpx-unlisted|" + self.gpx_root).encode()).hexdigest()
            return self
        gpx_files.sort()
        self.warnings.extend(f"Linked folder under gpx_root not followed — any tracks in it were not read: {rel}"
                             for rel in sorted(linked))

        conn = open_track_record(self.record)
        try:
            current = {row["path"]: dict(row) for row in
                       conn.execute("SELECT * FROM gpx_track_files WHERE withdrawn = 0").fetchall()}
            if coordinator:                       # per-file progress (count + %), named by GPX file
                coordinator.start_phase("loading GPX tracks", len(gpx_files))
            taken = {}
            for rel, abs_path in gpx_files:
                if coordinator:
                    coordinator.set_detail(rel)
                entry = self._file(conn, rel, abs_path, current.get(rel))
                if entry is not None:
                    taken[rel] = entry["track_id"]
                    self._take(conn, entry)
                if coordinator:
                    coordinator.increment_completed(1)
            if coordinator:
                coordinator.finish_phase()
            listed = {rel for rel, _a in gpx_files}
            for rel, row in sorted(current.items()):
                if taken.get(rel) != row["track_id"]:
                    self._retire(conn, row, gone=rel not in listed)
            if keep:
                conn.commit()
                self.catalogued = True        # the record is the tracks' as they are, over this window
            else:
                conn.rollback()
        finally:
            conn.close()
        self._finish()
        # Track files there, and not one of them read: the tracks are not there to plan by, whatever
        # "no tracks" would plan (RUL-unreadable_tracks_stop_geotag). A folder of no track file at all is empty.
        self.status = ("unreadable" if gpx_files and len(self.unreadable) == len(gpx_files) else
                       "usable" if self._any_points else "empty")
        return self

    def _finish(self):
        """Order the points and take their fingerprint (BLD-gpx_fingerprint)."""
        self.points.sort(key=lambda p: (p.time_utc, p.source_file, p.point_index))
        h = hashlib.sha256(b"gpx-window-v1")
        # the ranking decides which track places and anchors: a change to it is a change to the tracks
        # (RUL-track_ranking_in_dependencies)
        h.update(("precedence|" + json.dumps(self.precedence)).encode("utf-8"))
        for p in self.points:
            h.update(p.time_utc.isoformat().encode("utf-8"))
            h.update(f"{p.lat}|{p.lon}|{p.source_file}|{p.point_index}|{p.track}|{p.segment}".encode("utf-8"))
        self.fingerprint = h.hexdigest()

    # --- the catalogue (BLD-track_catalogue) -----------------------------------------------------------------

    def _wants(self, row):
        """Whether the window reaches into the entry's span past the window its kept points cover."""
        if not row["first_utc"]:
            return False
        first, last = math.floor(_epoch(row["first_utc"])), math.ceil(_epoch(row["last_utc"]))
        return any(a <= last and b >= first
                   for a, b in window_minus(self.window, valid_window(json.loads(row["covered"])) or []))

    def _file(self, conn, rel, abs_path, row):
        """The catalogue's entry for the track file at `rel` as it is now — read and parsed when it is new or
        changed, or when the window reaches into its span past what is kept — or None when it cannot be read."""
        try:
            st = os.stat(abs_path)
        except OSError as e:
            return self._cannot_read(rel, e)
        stamp = (st.st_size, st.st_mtime_ns, st.st_ino)
        if row is not None and row["parse_version"] == GPX_PARSE_VERSION \
                and (row["size"], row["mtime_ns"], row["inode"]) == stamp \
                and (row["unreadable"] is not None or not self._wants(row)):
            return row                        # as it was read: not read again
        try:
            with open(abs_path, "rb") as f:
                data = f.read()
        except OSError as e:
            return self._cannot_read(rel, e)
        self.read += 1
        sha = hashlib.sha256(data).hexdigest()
        found = conn.execute("SELECT * FROM gpx_track_files WHERE path = ? AND sha256 = ? AND parse_version = ?",
                             (rel, sha, GPX_PARSE_VERSION)).fetchone()
        return self._keep(conn, rel, sha, stamp, self._parse_bytes(data), dict(found) if found else None)

    def _cannot_read(self, rel, e):
        self.warnings.append(f"Could not read GPX file {rel}: {e}")
        self.unreadable.append((rel, str(e)))
        return None

    def _keep(self, conn, rel, sha, stamp, parsed, entry):
        """Keep the parse of the bytes `sha` of the file at `rel` as its current entry: its points in the window
        the entry covered, grown by this build's."""
        points, warnings, malformed = parsed
        times = sorted((_epoch(p[2]), p[2]) for p in points)
        covered = window_union(valid_window(json.loads(entry["covered"])) if entry else [], self.window)
        values = (rel.split("/", 1)[0] if "/" in rel else "", stamp[0], stamp[1], stamp[2],
                  times[0][1] if times else None, times[-1][1] if times else None,
                  json.dumps(covered), json.dumps(warnings), malformed)
        if entry:
            tid = entry["track_id"]
            conn.execute("UPDATE gpx_track_files SET rank_folder = ?, size = ?, mtime_ns = ?, inode = ?, first_utc = ?, "
                         "last_utc = ?, covered = ?, warnings = ?, unreadable = ?, withdrawn = 0 WHERE track_id = ?",
                         values + (tid,))
            conn.execute("DELETE FROM gpx_track_points WHERE track_id = ?", (tid,))
        else:
            tid = conn.execute("INSERT INTO gpx_track_files (rank_folder, size, mtime_ns, inode, first_utc, last_utc, "
                               "covered, warnings, unreadable, path, sha256, parse_version) "
                               "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                               values + (rel, sha, GPX_PARSE_VERSION)).lastrowid
        conn.executemany("INSERT INTO gpx_track_points VALUES (?, ?, ?, ?, ?, ?, ?)",
                         [(tid, idx, t, lat, lon, trk, seg) for lat, lon, t, idx, trk, seg in points
                          if _within(covered, _epoch(t))])
        return dict(conn.execute("SELECT * FROM gpx_track_files WHERE track_id = ?", (tid,)).fetchone())

    def _take(self, conn, entry):
        """Index the entry's kept points in the window, with its SHA-256 and its warnings."""
        rel = entry["path"]
        self.file_sha[rel] = entry["sha256"]
        self.warnings.extend(w.replace(_REL, rel) for w in json.loads(entry["warnings"] or "[]"))
        if entry["unreadable"] is not None:
            self.unreadable.append((rel, entry["unreadable"]))
            return
        self._any_points = self._any_points or bool(entry["first_utc"])
        for idx, t, lat, lon, trk, seg in conn.execute(
                "SELECT point_index, time_utc, lat, lon, track, segment FROM gpx_track_points WHERE track_id = ?",
                (entry["track_id"],)).fetchall():
            at = datetime.fromisoformat(t)
            if _within(self.window, at.timestamp()):
                self.points.append(GPXPoint(lat, lon, at, rel, idx, trk, seg))

    def _retire(self, conn, row, gone):
        """An entry no longer the file's: kept, withdrawn, where an executed plan placed or timed photos by it
        (RUL-withdrawn_track_points_kept); else taken out of the record with its points. A file gone is told
        (RUL-gone_track_told)."""
        used = conn.execute("SELECT 1 FROM gpx_track_use WHERE track_id = ? LIMIT 1", (row["track_id"],)).fetchone()
        if used:
            conn.execute("UPDATE gpx_track_files SET withdrawn = 1 WHERE track_id = ?", (row["track_id"],))
        else:
            conn.execute("DELETE FROM gpx_track_points WHERE track_id = ?", (row["track_id"],))
            conn.execute("DELETE FROM gpx_track_files WHERE track_id = ?", (row["track_id"],))
        if gone:
            self.gone.append(row["path"])
            self.warnings.append(f"Track file gone from gpx_root, no longer used: {row['path']}"
                                 + (" — its points stay in the record, withdrawn: an executed plan placed or "
                                    "timed photos by it" if used else ""))

    def prune(self):
        """Take out of the record the kept points outside this build's window, the planning's last: the record holds
        the points the decisions rest on (BLD-track_catalogue). An entry's points an executed plan used, in the
        window that plan was made in, stay — evidence of what was written into the photos — and a withdrawn entry's
        all stay (RUL-withdrawn_track_points_kept). Only after a build that kept the catalogue; the window's own
        points, and so the fingerprint, are untouched."""
        if not (self.record and self.catalogued):
            return
        conn = open_track_record(self.record)
        try:
            with conn:
                for row in conn.execute("SELECT track_id, covered FROM gpx_track_files WHERE withdrawn = 0").fetchall():
                    tid = row["track_id"]
                    used = [valid_window(json.loads(w)) or [] for (w,) in
                            conn.execute("SELECT window FROM gpx_track_use WHERE track_id = ?", (tid,)).fetchall()]
                    keep = window_union(self.window, *used)
                    covered = valid_window(json.loads(row["covered"])) or []
                    narrowed = window_intersect(covered, keep)
                    if narrowed == covered:
                        continue
                    drop = [(tid, idx) for idx, t in conn.execute(
                        "SELECT point_index, time_utc FROM gpx_track_points WHERE track_id = ?", (tid,)).fetchall()
                        if not _within(keep, _epoch(t))]
                    conn.executemany("DELETE FROM gpx_track_points WHERE track_id = ? AND point_index = ?", drop)
                    conn.execute("UPDATE gpx_track_files SET covered = ? WHERE track_id = ?",
                                 (json.dumps(narrowed), tid))
        finally:
            conn.close()

    @staticmethod
    def mark_used(record, plan_id, paths, window):
        """Record that the plan `plan_id`, executed, placed or timed photos by the track files at `paths` — by
        their current entries — with the window it was made in (BLD-withdrawn_track_points)."""
        conn = open_track_record(record)
        try:
            with conn:
                for rel in sorted(set(paths)):
                    row = conn.execute("SELECT track_id FROM gpx_track_files WHERE path = ? AND withdrawn = 0",
                                       (rel,)).fetchone()
                    if row is not None:
                        conn.execute("INSERT OR IGNORE INTO gpx_track_use VALUES (?, ?, ?)",
                                     (plan_id, row["track_id"], json.dumps(window_union(window))))
        finally:
            conn.close()

    @staticmethod
    def _trkpts(root):
        """Every `<trkpt>` under `root` in document order, with the index of the `<trk>` it is in and of the
        `<trkseg>` within that track (-1 for none): a track and its breaks are the file's own
        (RUL-track_is_one_trk, RUL-track_break_never_bridged)."""
        out, trk_n = [], 0
        stack = [(root, -1, -1, [0])]                 # (element, track, segment, the track's segment counter)
        while stack:
            elem, trk, seg, segs = stack.pop()
            name = elem.tag.rsplit("}", 1)[-1] if isinstance(elem.tag, str) else ""
            if name == "trkpt":
                out.append((elem, trk, seg))
                continue
            if name == "trk":
                trk, seg, segs, trk_n = trk_n, -1, [0], trk_n + 1
            elif name == "trkseg":
                seg, segs[0] = segs[0], segs[0] + 1
            stack.extend((c, trk, seg, segs) for c in reversed(list(elem)))
        return out

    @staticmethod
    def _parse_bytes(data):
        """A track file's points as [lat, lon, UTC time (ISO), index, track, segment], its warnings, the file's
        path written as _REL, and why it could not be parsed (None when it was) — what the memo keeps for the
        file's bytes, wherever the file lies."""
        points, warnings = [], []
        try:
            root = ET.fromstring(data)
        except ET.ParseError as e:
            return points, [f"Malformed GPX XML in {_REL}: {e}"], f"malformed GPX XML: {e}"
        idx = 0
        for elem, trk, seg in GPXIndex._trkpts(root):
            lat_s, lon_s = elem.attrib.get("lat"), elem.attrib.get("lon")
            time_elem = next((c for c in elem if c.tag.endswith("time")), None)
            if not lat_s or not lon_s:
                warnings.append(f"GPX point without a position in {_REL} at trkpt {idx}")
                idx += 1
                continue
            if time_elem is None or not (time_elem.text or "").strip():
                # Reported like every unusable point, so a track whose points all lack a time never
                # reads as merely an empty track (RUL-unreadable_point_reported).
                warnings.append(f"GPX point without a time in {_REL} at trkpt {idx}")
                idx += 1
                continue
            try:
                lat, lon = float(lat_s), float(lon_s)
                if not (-90.0 <= lat <= 90.0 and -180.0 <= lon <= 180.0):
                    warnings.append(f"Out-of-range coordinate in {_REL} at trkpt {idx}")
                    idx += 1
                    continue
                ts = time_elem.text.strip()
                # xsd:dateTime: fractional seconds are optional (Garmin writes `...:SS.000Z`), and a
                # `Z` suffix is spelled out as +00:00 so fromisoformat takes it on every Python 3.
                if ts[-1:] in ("Z", "z"):
                    ts = ts[:-1] + "+00:00"
                dt = datetime.fromisoformat(ts)
                if dt.tzinfo is None:
                    warnings.append(f"GPX time without timezone in {_REL} at trkpt {idx}")
                    idx += 1
                    continue
                points.append([lat, lon, dt.astimezone(timezone.utc).isoformat(), idx, trk, seg])
            except ValueError as e:
                warnings.append(f"Bad trkpt in {_REL} at index {idx}: {e}")
            idx += 1
        return points, warnings, None


def _valid_iana(tz):
    """True iff `tz` names a real IANA timezone (RUL-checked_timezones): a place's zone, never one of the names a
    zone database keeps for the machine it is on — `localtime` resolves to wherever the run happens."""
    return valid_iana_timezone(tz)


def _valid_offset(v):
    """True iff `v` is a whole number of seconds (RUL-checked_clock_offsets) — of any size: a clock reset to its factory
    date is years out, and a typo shows in the corrected time the editor previews and in the drift check
    every manual offset goes through."""
    return (isinstance(v, int) and not isinstance(v, bool)) or (isinstance(v, float) and v.is_integer())


# ============================================================================
# Stage 5 — GPX/native-GPS time-anchor inference (BLD-anchor_matching). Pure helpers
# (plain inputs, no I/O) so the geometry/ranking is exhaustively unit-testable.
# ============================================================================

def _parse_camera_naive(s):
    """The camera's naive capture time ('YYYY:MM:DD HH:MM:SS') as a naive datetime, or None — the same
    reading prep gives a recorded time (`parse_naive_time`)."""
    return parse_naive_time(s)


def _naive_date(s):
    """The camera naive timestamp's calendar date as 'YYYY-MM-DD', or None — the per-day offset bucket
    key within a destination (RUL-offset_per_camera_destination_day: a clock set to local time each morning
    is constant only per day)."""
    dt = _parse_camera_naive(s)
    return dt.strftime("%Y-%m-%d") if dt else None


# A destination's date fallback as photos-21 holds it (BLD-date_fallback_cell): a year, a year and month, or a day.
_DATE_FALLBACK = re.compile(r"([0-9]{4})(?:-([0-9]{2})(?:-([0-9]{2}))?)?")


def date_fallback_day(value):
    """The day a date fallback stands for — `YYYY`, `YYYY-MM` or `YYYY-MM-DD`, the month and day it leaves out taken as
    the first (RUL-date_fallback_fills_to_a_day) — as a naive datetime at midnight; None where `value` is no such
    date: another form, or a day the calendar has not (RUL-date_fallback_checked)."""
    m = _DATE_FALLBACK.fullmatch(value) if isinstance(value, str) else None
    if m is None:
        return None
    try:
        return datetime(int(m[1]), int(m[2] or 1), int(m[3] or 1))
    except ValueError:
        return None


def untimed(f):
    """Whether photo `f` carries no recorded time (DEF-recorded_time): the one kind of photo a date fallback times
    (RUL-date_fallback_only_untimed)."""
    return not f.get("has_timestamp", True)


def date_fallback_time(f, d):
    """The time the date fallback in effect at destination record `d` gives photo `f` — its day at midnight, local to
    the destination (RUL-date_fallback_times_untimed) — or None: a photo with a recorded time of its own is never timed
    by one (RUL-date_fallback_only_untimed), and one no fallback covers has none."""
    if not untimed(f):
        return None
    eff = (d.get("date_fallback") or {}).get("effective_date")
    return date_fallback_day(eff.get("date")) if isinstance(eff, dict) else None


def _parse_utc(s):
    """An ISO-8601 UTC datetime (trailing Z accepted) as an aware datetime, or None."""
    try:
        return datetime.fromisoformat((s or "").replace("Z", "+00:00"))
    except (ValueError, AttributeError):
        return None


def _lon_delta(a, b):
    """The signed degrees of longitude from `a` to `b` the short way round, so a track crossing the
    antimeridian (179.99 → -179.99) is a step of 0.02°, never one of 359.98° back across the world."""
    return (b - a + 180.0) % 360.0 - 180.0


def _wrap_lon(lon):
    return (lon + 180.0) % 360.0 - 180.0 if not -180.0 <= lon <= 180.0 else lon


def _equirect_xy(lat, lon, lat0, lon0):
    """Local equirectangular projection of (lat,lon) to metres about (lat0,lon0)."""
    R = 6371000.0
    x = math.radians(_lon_delta(lon0, lon)) * math.cos(math.radians(lat0)) * R
    y = math.radians(lat - lat0) * R
    return x, y


def _point_to_segment(plat, plon, alat, alon, blat, blon):
    """Distance (metres) from point P to segment A-B, and the clamped projection fraction t∈[0,1]
    (0 at A, 1 at B), in a local plane about A. A zero-length segment yields the distance to A."""
    bx, by = _equirect_xy(blat, blon, alat, alon)
    px, py = _equirect_xy(plat, plon, alat, alon)
    seg2 = bx * bx + by * by
    if seg2 == 0.0:
        return math.hypot(px, py), 0.0
    t = max(0.0, min(1.0, (px * bx + py * by) / seg2))
    return math.hypot(px - t * bx, py - t * by), t


def _candidate(match_type, gpx_time, distance, src, naive, dur, span=0.0):
    offset = round((gpx_time.replace(tzinfo=None) - naive).total_seconds())
    return {"match_type": match_type, "gpx_time": gpx_time, "distance_m": round(distance, 2),
            "gpx_file": src, "offset_seconds": int(offset),
            "segment_duration_seconds": (round(dur) if dur is not None else None),
            "time_span_seconds": int(round(span))}


def frame_candidates(frame, gpx, cfg):
    """Every GPX time-anchor candidate for one native-GPS frame (BLD-anchor_matching): one per PASS of a track by the
    place it was taken — the best match of each pass, a close point before a close short segment, then the
    closest. A pass is an unbroken run of ONE track within the anchor distance of the place: a track that
    leaves and comes back passed twice, so an out-and-back walk, the same walk on two days, or a place
    visited morning and evening each yield one candidate per visit, and the consensus over the camera's
    frames (infer_anchor_proposal) says which visit is the photo's. Passes closer in time than
    `gpx_anchor_same_pass_max_seconds` are one. A candidate's `time_span_seconds` is how long the track
    stayed as close as its best match, give or take `gpx_anchor_stay_distance_meters`: where the track
    stood still the place says only that
    the photo was taken some time during the stay, not when. Only matches within the plausible-clock-error
    window of the frame's naive time count. Candidates come in time order; [] if nothing anchors."""
    ng = frame.get("native_gps") or {}
    naive = _parse_camera_naive(frame.get("source_naive_time"))
    if ng.get("lat") is None or ng.get("lon") is None or naive is None or not gpx.points:
        return []
    flat, flon = float(ng["lat"]), float(ng["lon"])
    pt_max = cfg["gpx_anchor_max_point_distance_meters"]
    seg_max = cfg["gpx_anchor_max_segment_distance_meters"]
    gap_max = cfg["gpx_anchor_max_segment_gap_seconds"]
    same_pass = cfg["gpx_anchor_same_pass_max_seconds"]
    stay_dist = cfg["gpx_anchor_stay_distance_meters"]
    # Plausible-clock-error window: a GPX time may anchor this frame only if it is within `window` of the
    # frame's naive time (read as UTC). Applied DURING the search so a same-place/other-trip point is
    # skipped even when it is the spatially closest — fixing the years-off false match (BLD-anchor_matching).
    window = cfg["gpx_anchor_max_clock_error_seconds"]
    naive_utc = naive.replace(tzinfo=timezone.utc)
    out = []
    tracks = gpx.tracks()
    # only the stretch of each track inside the window
    spans = [(bisect.bisect_left(times, naive_utc - timedelta(seconds=window)),
              bisect.bisect_right(times, naive_utc + timedelta(seconds=window))) for _s, _p, times in tracks]
    # and of it only the points by the place and those either side: at any other point there is no pass to
    # extend or end, so the walk below does nothing there
    nearby = gpx.nearby(flat, flon, pt_max, seg_max, spans)
    for k, (src, pts, times) in enumerate(tracks):
        lo, hi = spans[k]
        passes, run = [], []                          # a pass: [(gpx time, rank, distance, segment duration)]
        for i in (nearby[k] if nearby is not None else range(lo, hi)):
            p = pts[i]
            d = haversine(flat, flon, p.lat, p.lon)
            near = d <= pt_max
            if near:
                run.append((p.time_utc, 0, d, None))
            seg_near = False
            # a segment is two consecutive points of one <trkseg>: never the two sides of a break in the
            # recording (RUL-track_break_never_bridged)
            joined = i + 1 < hi and pts[i + 1].segment == p.segment
            if joined:
                b = pts[i + 1]
                dur = (b.time_utc - p.time_utc).total_seconds()
                if 0 < dur <= gap_max:
                    dist, t = _point_to_segment(flat, flon, p.lat, p.lon, b.lat, b.lon)
                    if dist <= seg_max:
                        seg_near = True
                        run.append((p.time_utc + timedelta(seconds=t * dur), 1, dist, dur))
            if run and not seg_near and not (joined and haversine(flat, flon, pts[i + 1].lat,
                                                                  pts[i + 1].lon) <= pt_max
                                             and (pts[i + 1].time_utc - p.time_utc).total_seconds() <= gap_max):
                passes.append(run)                    # the track has left the place (or stopped recording)
                run = []
        if run:
            passes.append(run)
        merged = []
        for r in passes:
            if merged and (min(m[0] for m in r) - max(m[0] for m in merged[-1])).total_seconds() <= same_pass:
                merged[-1].extend(r)
            else:
                merged.append(r)
        for r in merged:
            gt, rank, dist, dur = min(r, key=lambda m: (m[1], m[2], m[0]))
            as_close = [m[0] for m in r if m[2] <= dist + stay_dist]
            out.append(_candidate("gpx_point_match" if rank == 0 else "gpx_segment_interpolation", gt, dist, src,
                                  naive, dur, (max(as_close) - min(as_close)).total_seconds()))
    if out and gpx.ranked():
        # a lower-ranked track anchors only at a time no higher-ranked one recorded
        # (RUL-lower_track_anchors_where_higher_absent)
        out = [c for c in out if not any(gpx.rank(f) < gpx.rank(c["gpx_file"]) and _covers(p, t, c["gpx_time"], cfg)
                                         for f, p, t in tracks)]
    out.sort(key=lambda c: (c["gpx_time"], c["gpx_file"] or ""))
    return out


def _covers(pts, times, instant, cfg):
    """True when one track has a point at `instant`, or two around it a photo could be placed between, within the
    placement limits (BLD-track_placement) — the track recorded where its device was then."""
    p, _why = _place_on_track(pts, times, instant, cfg)
    return p is not None and p["method"] != "extrapolated"


def _frame_skip_reason(frame, gpx, cfg):
    """Why `frame_candidates` found no anchor for `frame`: 'outside_time_window' if a GPX point is
    spatially close but only at an implausible time (a different trip/year), else 'no_nearby_track'.
    Drives the editor's skipped-frames note so a windowed-out match is explained, not hidden."""
    ng = frame.get("native_gps") or {}
    naive = _parse_camera_naive(frame.get("source_naive_time"))
    if ng.get("lat") is None or ng.get("lon") is None or naive is None or not gpx.points:
        return "no_nearby_track"
    flat, flon, pt_max = float(ng["lat"]), float(ng["lon"]), cfg["gpx_anchor_max_point_distance_meters"]
    nearby = gpx.nearby(flat, flon, pt_max, cfg["gpx_anchor_max_segment_distance_meters"])
    if nearby is None:
        near = any(haversine(flat, flon, p.lat, p.lon) <= pt_max for p in gpx.points)
    else:                                   # only the points by the place can be within reach
        near = any(haversine(flat, flon, pts[i].lat, pts[i].lon) <= pt_max
                   for (_s, pts, _t), idx in zip(gpx.tracks(), nearby) for i in idx)
    if near:
        return "outside_time_window"
    return "no_nearby_track"


def _zone_ambiguity(naive, tz):
    """How a naive local time `naive` reads in IANA zone `tz` at a daylight-saving change
    (RUL-ambiguous_local_time_never_guessed): None when it names one instant; else `{"case": "repeated" | "skipped",
    "offsets_seconds": [the offset before the change, the one after]}` — a repeated time is two instants, a skipped
    time was never shown on a clock there. The two folds give two offsets only at a change; a skipped time is the
    one that does not come back from UTC as itself."""
    if naive is None or not tz:
        return None
    try:
        zone = zoneinfo.ZoneInfo(tz)
        first, second = naive.replace(tzinfo=zone, fold=0), naive.replace(tzinfo=zone, fold=1)
        off0, off1 = first.utcoffset(), second.utcoffset()
        if off0 is None or off1 is None or off0 == off1:
            return None
        back = first.astimezone(timezone.utc).astimezone(zone).replace(tzinfo=None)
    except (zoneinfo.ZoneInfoNotFoundError, ValueError, TypeError, OverflowError, OSError):
        return None
    return {"case": "repeated" if back == naive else "skipped",
            "offsets_seconds": [int(off0.total_seconds()), int(off1.total_seconds())]}


def _timezone_naive_offset(naive_str, tz):
    """Timezone-derived clock-offset (BLD-timezone_naive_offset): when a (camera group, destination) has no GPX anchor,
    assume the camera clock was set to the destination's civil timezone, so the
    offset is -(that timezone's UTC offset at this naive instant) — DST-aware via zoneinfo. Returns
    (offset_seconds, real_utc_iso), or None if `tz`/`naive_str` is missing or unresolvable. A confirmable
    proposal only (the local-clock assumption can be wrong, e.g. a camera left on home time). None too for a time
    the zone repeats or skips at a daylight-saving change: the zone gives it two offsets, and none is proposed
    (RUL-ambiguous_local_time_never_guessed) — `_zone_ambiguity` says which."""
    dt = _parse_camera_naive(naive_str)
    if dt is None or not tz:
        return None
    if _zone_ambiguity(dt, tz) is not None:
        return None
    try:
        off = dt.replace(tzinfo=zoneinfo.ZoneInfo(tz)).utcoffset()
    except (zoneinfo.ZoneInfoNotFoundError, ValueError, TypeError):
        return None
    if off is None:
        return None
    return -int(off.total_seconds()), (dt - off).strftime("%Y-%m-%dT%H:%M:%SZ")


def infer_anchor_proposal(frames, gpx, cfg):
    """Turn all native-GPS frames' GPX matches for one (camera group, destination) into a single
    recommended clock-offset proposal (RUL-anchor_consensus), or None if nothing anchors. Each frame offers one
    candidate per pass of the tracks by its place (frame_candidates); the candidates' offsets are clustered
    (a camera's clock error is ~constant across a destination's day) and the CONSENSUS wins — the cluster
    the most FRAMES support, each frame counted once however many of its passes fall in it — so a lone
    spurious match can't outvote the crowd, and the same route walked on two days is settled by the photos
    that only one day's track explains. Two clusters equally supported are a disagreement: the smaller
    clock error is recommended, for review. Within the chosen cluster the representative is its best match
    (point before segment, then closest). Frames with no in-window match are summarized as `skipped`; the
    clusters as `groups` for a collapsed editor view."""
    by_frame, skipped = _anchor_candidates(frames, gpx, cfg)
    return _anchor_consensus(by_frame, skipped, cfg)


def _anchor_candidates(frames, gpx, cfg):
    """Each anchoring frame's candidates (`frame_candidates`), as (by_frame, skipped): by_frame a list, one entry per
    frame that matched a pass, of its candidates — each knowing its frame's index, path, position and camera time; and
    the frames that matched none, counted by reason, with up to three examples."""
    by_frame, skipped = [], {"no_nearby_track": 0, "outside_time_window": 0, "examples": []}
    for f in frames:
        cs = frame_candidates(f, gpx, cfg)
        if cs:
            n = len(by_frame)                       # the frame's own index: each frame votes once
            by_frame.append([dict(c, frame=n, source_file=f.get("relative_path"), native_gps=f.get("native_gps"),
                                  camera_source_naive_time=f.get("source_naive_time")) for c in cs])
        else:
            reason = _frame_skip_reason(f, gpx, cfg)
            skipped[reason] += 1
            if len(skipped["examples"]) < 3:
                skipped["examples"].append({"source_file": f.get("relative_path"), "reason": reason})
    return by_frame, skipped


def _anchor_consensus(by_frame, skipped, cfg):
    """The proposal `infer_anchor_proposal` makes from frames' candidates (`_anchor_candidates`), or None for none."""
    if not by_frame:
        return None
    spread = cfg["gpx_anchor_offset_spread_max_seconds"]
    # A candidate whose track stood still by the place for longer than `gpx_anchor_stay_max_seconds` says
    # only that the photo was taken some time during the stay: it supports any offset in that span, and
    # names none.
    stay_max = cfg["gpx_anchor_stay_max_seconds"]
    vague = lambda c: c.get("time_span_seconds", 0) > stay_max
    rank = lambda c: (vague(c), 0 if c["match_type"] == "gpx_point_match" else 1, c["distance_m"],
                      c["source_file"] or "", c["offset_seconds"])

    def agrees(c, offset):
        if not vague(c):
            return abs(c["offset_seconds"] - offset) <= spread
        return abs(c["offset_seconds"] - offset) <= c["time_span_seconds"] + spread
    cands = sorted((c for cs in by_frame for c in cs), key=rank)
    clusters = []                                   # each: {"offset", "rep", "members": [...], "frames": set}
    for c in cands:                                 # rank order → each cluster's rep is its best match
        g = next((g for g in clusters if agrees(c, g["offset"])), None)
        if g is None:
            clusters.append({"offset": c["offset_seconds"], "rep": c, "members": [c], "frames": {c["frame"]}})
        else:
            g["members"].append(c)
            g["frames"].add(c["frame"])
    # consensus: most supporting frames; a tie → the smaller clock error, then the best-ranked rep
    order = sorted(range(len(clusters)), key=lambda i: (-len(clusters[i]["frames"]), abs(clusters[i]["offset"]), i))
    g = clusters[order[0]]
    tied = len(order) > 1 and len(clusters[order[1]]["frames"]) == len(g["frames"])
    best = g["rep"]
    support = g["frames"]
    supporting_count = len(support) - 1
    conflicting = sorted({cs[0]["source_file"] or "" for n, cs in enumerate(by_frame) if n not in support})
    conflicting_count = len(by_frame) - len(support)        # frames no pass of which agrees
    imprecise = best["time_span_seconds"] if vague(best) else 0     # no photo fixes the offset within the stay
    if conflicting_count or tied or imprecise:
        confidence = "review_required"
    elif supporting_count or best["match_type"] == "gpx_point_match":
        confidence = "high"
    else:
        confidence = "medium"
    # one anchor per frame: its candidate in the chosen cluster, else its best; the representative first
    chosen = {}
    for c in g["members"]:
        chosen.setdefault(c["frame"], c)
    per_frame = [chosen.get(n) or min(cs, key=rank) for n, cs in enumerate(by_frame)]
    ordered = [best] + sorted((c for c in per_frame if c is not best), key=rank)
    anchors = [{"proposal_id": f"anchor-{i + 1:03d}", "source_file": c["source_file"],
                "camera_source_naive_time": c["camera_source_naive_time"], "native_gps": c["native_gps"],
                "gpx_match": {"match_type": c["match_type"], "gpx_file": c["gpx_file"],
                              "distance_m": c["distance_m"],
                              "segment_duration_seconds": c["segment_duration_seconds"]},
                "proposed_offset_seconds": c["offset_seconds"]} for i, c in enumerate(ordered)]
    groups = sorted(({"offset_seconds": gg["offset"], "count": len(gg["frames"]),
                      "representative": {"source_file": gg["rep"]["source_file"],
                                         "camera_source_naive_time": gg["rep"]["camera_source_naive_time"],
                                         "real_utc": gg["rep"]["gpx_time"].strftime("%Y-%m-%dT%H:%M:%SZ"),
                                         "match_type": gg["rep"]["match_type"],
                                         "gpx_file": gg["rep"]["gpx_file"],
                                         "distance_m": gg["rep"]["distance_m"]}}
                     for gg in clusters), key=lambda x: (-x["count"], abs(x["offset_seconds"]), x["offset_seconds"]))
    return {
        "proposal_source": "gpx_self_anchor",
        "proposed_offset_seconds": best["offset_seconds"],
        "proposed_real_utc": best["gpx_time"].strftime("%Y-%m-%dT%H:%M:%SZ"),
        "confidence": confidence,
        "recommended_gpx_match": {"match_type": best["match_type"], "gpx_file": best["gpx_file"],
                                  "distance_m": best["distance_m"],
                                  "segment_duration_seconds": best["segment_duration_seconds"]},
        "anchor_count": len(by_frame), "supporting_count": supporting_count,
        "conflicting_count": conflicting_count, "conflicting_files": conflicting, "tied": tied,
        "imprecise_seconds": imprecise,
        "acceptance_tolerance_seconds": cfg["gpx_anchor_decision_tolerance_seconds"], "anchors": anchors,
        "groups": groups, "skipped": skipped,
    }


def contradicted_frames(frames, gpx, cfg, offset):
    """The paths of the frames whose own position the clock offset `offset` contradicts (BLD-contradicted_position):
    each matched a pass of the tracks by its place (`frame_candidates`), and no pass agrees with the offset — within
    `gpx_anchor_offset_spread_max_seconds`, and the stay as well for a pass the tracks stood still on, as clustering
    agrees (`infer_anchor_proposal`). A frame no pass matches says nothing of the offset."""
    spread, stay_max = cfg["gpx_anchor_offset_spread_max_seconds"], cfg["gpx_anchor_stay_max_seconds"]
    out = []
    for f in frames:
        cs = frame_candidates(f, gpx, cfg)
        if cs and not any(abs(c["offset_seconds"] - offset)
                          <= (c["time_span_seconds"] if c["time_span_seconds"] > stay_max else 0) + spread for c in cs):
            out.append(f.get("relative_path"))
    return sorted(p for p in out if p)


def _reindexed(by_frame):
    """Frames' candidates (`_anchor_candidates`) numbered again from 0, for a consensus over some of them."""
    return [[dict(c, frame=n) for c in cs] for n, cs in enumerate(by_frame)]


def _naive_key(time_text, path):
    """A photo's place in camera-time order: its camera time, then its path."""
    return (_parse_camera_naive(time_text) or datetime.min, path or "")


def clock_change_proposal(frames, photos, gpx, cfg):
    """Where the camera's clock was changed during the day (BLD-clock_change_split): the photos its own GPS anchors —
    on the tracks (`infer_anchor_proposal`), else by their fixes' times (`gps_readings`) — taken in the order of the
    true time their GPS gives each — the track time its anchor matched, else its fix's time — form two consecutive
    runs, each agreeing within itself on an offset of its own — a run on the tracks proposing with no photo against it,
    no tie and no stay; a run of fix times within `gpx_anchor_offset_spread_max_seconds` of each other, the first's
    offset the run's — the two offsets farther apart than that spread. A clock set back, its two runs interleaved in
    camera time, shows so as one set forward does. Nothing changes where the day's photos already agree, where no split, or more than one, makes two
    such runs, as three or more alternating runs never do, or where the runs, each photo at the true time its own run's
    offset gives it, do not follow one another a second or more apart.

    Returns None, or (proposal, settled). The proposal: `evidence` (`gpx_self_anchor` or `gps_time`), `runs` — each its
    `offset_seconds`, `photos` (how many) and its `first` and `last` in true time (`source_file`,
    `camera_source_naive_time`, `real_utc`) — `unsettled` — each of `photos` that is none of the runs' and whose part
    the runs do not settle, in camera-time order — and `acceptance_tolerance_seconds`. `settled` gives the part, 1 or 2,
    of every other photo of `photos` holding a camera time: a run's photo its run's; another the one part that could
    have taken it — the first where the first run's offset puts it before the second run's first photo, the second
    where the second run's offset puts it after the first run's last; a photo either part could have taken, or
    neither, is unsettled."""
    spread = cfg["gpx_anchor_offset_spread_max_seconds"]
    by_frame, skipped = _anchor_candidates(frames, gpx, cfg) if gpx is not None and gpx.points else ([], None)
    if by_frame:
        whole = _anchor_consensus(by_frame, skipped, cfg)
        if not (whole["conflicting_count"] or whole["tied"]):
            return None                                 # the day's photos agree: no change
        none = {"no_nearby_track": 0, "outside_time_window": 0, "examples": []}

        def true_times(proposal):
            # each anchor's true time: the track time it matched — its camera time and its offset
            return {a["source_file"]: _parse_camera_naive(a["camera_source_naive_time"])
                    + timedelta(seconds=a["proposed_offset_seconds"]) for a in proposal["anchors"]}
        matched = true_times(whole)
        items = sorted(by_frame, key=lambda cs: (matched[cs[0]["source_file"]], cs[0]["source_file"] or ""))
        path = lambda cs: cs[0]["source_file"]
        naive_text = lambda cs: cs[0]["camera_source_naive_time"]

        def agreed(run):
            p = _anchor_consensus(_reindexed(run), none, cfg)
            return None if p["conflicting_count"] or p["tied"] or p["imprecise_seconds"] else p["proposed_offset_seconds"]

        def placed(run):
            # each photo of a run at the track time of its pass that agrees with the run's offset
            return true_times(_anchor_consensus(_reindexed(run), none, cfg))
        evidence = "gpx_self_anchor"
    else:
        readings = gps_readings(frames)
        offs = [r["offset_seconds"] for r in readings]
        fix_times = [r["gps_utc"] for r in readings]
        if len(readings) < 2 or len(set(fix_times)) < len(fix_times) or max(offs) - min(offs) <= spread:
            return None                                 # a stale fix, or readings that agree: no change seen
        fix = lambda r: _parse_utc(r["gps_utc"]).replace(tzinfo=None)
        items = sorted(readings, key=lambda r: (fix(r), r["source_file"]))
        path = lambda r: r["source_file"]
        naive_text = lambda r: r["camera_source_naive_time"]

        def agreed(run):
            o = [r["offset_seconds"] for r in run]
            return o[0] if max(o) - min(o) <= spread else None

        def placed(run):
            return {r["source_file"]: fix(r) for r in run}
        evidence = "gps_time"
    splits = []
    for k in range(1, len(items)):
        a, b = agreed(items[:k]), agreed(items[k:])
        if a is not None and b is not None and abs(a - b) > spread:
            splits.append((k, a, b))
    if len(splits) != 1:
        return None                                     # no two runs, or no one place they meet
    k, a, b = splits[0]
    sides = (items[:k], items[k:])
    at = [placed(side) for side in sides]
    lo, hi = max(at[0].values()), min(at[1].values())   # the first run's last photo, the second's first, in true time
    if hi <= lo:
        return None                                     # the runs do not follow one another: no change between them
    # each photo the runs' GPS places, by its run: a reading of the fixes' times stands for every photo giving it
    run_of = {path(x): n + 1 for n, side in enumerate(sides) for x in side}
    if evidence == "gps_time":
        reading = {(r["gps_utc"], _parse_camera_naive(r["camera_source_naive_time"])): run_of[r["source_file"]]
                   for r in items}
        for f in frames:
            gps, naive = _parse_utc(f.get("gps_utc")), _parse_camera_naive(f.get("source_naive_time"))
            if f.get("has_native_gps") and gps is not None and naive is not None:
                n = reading.get((gps.strftime("%Y-%m-%dT%H:%M:%SZ"), naive))
                if n is not None:
                    run_of.setdefault(f["relative_path"], n)
    settled, unsettled = {}, []
    for f in photos:
        rel, t = f["relative_path"], _parse_camera_naive(f.get("source_naive_time"))
        if rel in run_of:
            settled[rel] = run_of[rel]
            continue
        if t is None:
            continue
        could = [n for n, fits in ((1, t + timedelta(seconds=a) < hi), (2, t + timedelta(seconds=b) > lo)) if fits]
        if len(could) == 1:
            settled[rel] = could[0]                     # only one part could have taken it
        else:
            unsettled.append({"source_file": rel, "camera_source_naive_time": f.get("source_naive_time")})
    unsettled.sort(key=lambda x: _naive_key(x["camera_source_naive_time"], x["source_file"]))

    def run(off, side, times):
        ordered = sorted(side, key=lambda x: (times[path(x)], path(x) or ""))
        end = lambda x: {"source_file": path(x), "camera_source_naive_time": naive_text(x),
                         "real_utc": times[path(x)].strftime("%Y-%m-%dT%H:%M:%SZ")}
        return {"offset_seconds": off, "photos": len(side), "first": end(ordered[0]), "last": end(ordered[-1])}
    proposal = {"evidence": evidence, "runs": [run(a, sides[0], at[0]), run(b, sides[1], at[1])],
                "unsettled": unsettled, "acceptance_tolerance_seconds": cfg["gpx_anchor_decision_tolerance_seconds"]}
    return proposal, settled


def offset_cell_key(cells, group, naive_text, path=None):
    """The key of the offset cell a camera's photo `path` of `group` at camera time `naive_text` is read by, among a
    destination's `cells` (BLD-offset_buckets): `<group>@<date>` where the destination has one for its date, else
    `<group>`; and where that day's cell is split at a clock change (BLD-clock_change_split), the part the split gives
    the photo (`effective_split.photo_parts`) — none given, the day's own, which offsets nothing."""
    cells = cells or {}
    date = _naive_date(naive_text)
    key = f"{group}@{date}" if f"{group}@{date}" in cells else group
    split = ((cells.get(key) or {}).get("clock_change") or {}).get("effective_split")
    if isinstance(split, dict):
        n = (split.get("photo_parts") or {}).get(path)
        if n in (1, 2):
            key = split["parts"][n - 1]
    return key


# ============================================================================
# Stage 7 — resolved UTC per file (BLD-resolved_utc). Pure computation + the
# geotag-owned SQLite cache and its deterministic fingerprint (BLD-resolved_utc_fingerprint).
# ============================================================================

_OFFSET_RE = re.compile(r"^([+-])(\d\d):?([0-5]\d)$")


def _parse_iso_offset(s):
    """A UTC offset — '+02:00', '-05:30', '+0200' or 'Z' — as seconds, or None for anything else: a value
    that is not an offset is no offset, never one read loosely."""
    if not isinstance(s, str):
        return None
    s = s.strip()
    if s == "Z":
        return 0
    m = _OFFSET_RE.match(s)
    if not m or int(m.group(2)) > 14:
        return None
    secs = int(m.group(2)) * 3600 + int(m.group(3)) * 60
    return -secs if m.group(1) == "-" else secs


# In the map of zones in effect: a destination that waits on its own photos, which nothing inside inherits past.
_ZONE_WAITS = "\x00waits"


def _recorded_readings(files, groups):
    """The photos of `files` read by the offset recorded with their time — a phone's, a file's naming no camera; never
    a camera's, whose offset tag says what its clock was set to, not where it was; nor one geotag corrected, nor a
    kept true time, read by the zone, its tag told apart (BLD-changed_time_kept_not_anchor) — as (path, camera time,
    offset), by path."""
    for f in sorted(files, key=lambda x: x["relative_path"]):
        if (groups.get(f["camera_group_key"]) or {}).get("camera_group_class") == "camera" or f.get("geotag_marker") \
                or f.get("true_time"):
            continue
        naive, own = _parse_camera_naive(f.get("source_naive_time")), _own_offset(f)
        if naive is not None and own is not None:
            yield f["relative_path"], naive, own


def _zone_offset_there(zone, naive, own):
    """`zone`'s UTC offset, in whole seconds, at the instant a photo whose camera time is `naive` recorded with offset
    `own` was taken; None where that instant is out of range."""
    try:
        return int((naive - timedelta(seconds=own)).replace(tzinfo=timezone.utc).astimezone(zone).utcoffset()
                   .total_seconds())
    except OverflowError:
        return None


def _offsets_against_zone(files, groups, tz):
    """What a destination's own photos say against the timezone `tz` it would inherit: the photos read by
    the offset recorded with their time (`_recorded_readings`) whose offset is not `tz`'s at that time.
    None when none speaks against it; else how many, and one of them."""
    if not _valid_iana(tz):
        return None
    zone, out = zoneinfo.ZoneInfo(tz), []
    for rel, naive, own in _recorded_readings(files, groups):
        there = _zone_offset_there(zone, naive, own)
        if there is not None and round(there / 60) * 60 != own:
            out.append((rel, own, there))
    if not out:
        return None
    rel, own, there = out[0]
    return {"photos": len(out), "example": rel, "recorded_offset_seconds": own,
            "recorded_offsets": sorted({o for _r, o, _t in out}),
            "timezone": tz, "timezone_offset_seconds": there}


def _zone_from_photos(files, groups, zones):
    """The one zone of `zones` — a country's — whose offset at each photo's time is the offset the photo records with
    it (`_recorded_readings`), or None: where no photo records one, or none or several of the zones fit them all
    (RUL-zone_from_photos_in_country, BLD-zone_from_photos_in_country)."""
    readings = list(_recorded_readings(files, groups))
    if not readings:
        return None
    fit = []
    for tz in zones:
        if not _valid_iana(tz):
            continue
        zone = zoneinfo.ZoneInfo(tz)
        if all((there := _zone_offset_there(zone, naive, own)) is not None and round(there / 60) * 60 == own
               for _rel, naive, own in readings):
            fit.append(tz)
    return fit[0] if len(fit) == 1 else None


def _local_to_utc(naive, tz):
    """Interpret a naive local datetime as wall time in IANA `tz` -> aware UTC (DST-correct). Only for a time that
    names one instant there: a repeated or skipped one (`_zone_ambiguity`) is the caller's to refuse."""
    return naive.replace(tzinfo=zoneinfo.ZoneInfo(tz)).astimezone(timezone.utc)


# The rule of a photo whose local time the zone repeats or skips (RUL-ambiguous_local_time_never_guessed): unresolved.
_AMBIGUOUS_RULES = {"repeated": "local_time_repeated", "skipped": "local_time_skipped"}
AMBIGUOUS_RULES = _AMBIGUOUS_RULES


def _resolve_by_zone(naive, tz, answer=None):
    """A photo's local time read through its destination's zone, as (resolved UTC, status, rule suffix, offset used):
    the one instant it names; for a time the zone repeats or skips, the reading the user answered for the photo in
    photos-21 (`answer`, its UTC offset, BLD-local_time_readings: rule `local_time_answered`), else (None,
    "unresolved", the case's rule) — never one of its readings guessed (RUL-ambiguous_local_time_never_guessed)."""
    amb = _zone_ambiguity(naive, tz)
    if amb is not None:
        if _valid_offset(answer) and not isinstance(answer, bool):
            return naive - timedelta(seconds=int(answer)), "valid", "local_time_answered", int(answer)
        return None, "unresolved", _AMBIGUOUS_RULES[amb["case"]], None
    return _local_to_utc(naive, tz), "valid", None, None


def _reading_answer(f, d):
    """The UTC offset the user answered for photo `f`'s time, which its zone skips or repeats, as photos-21 holds it in
    effect for its destination `d` (BLD-local_time_readings), or None."""
    cell = (d.get("local_time_readings") or {}).get(f["relative_path"]) or {}
    eff = cell.get("effective_utc_offset_seconds")
    return eff if _valid_offset(eff) and eff != "" else None


def unreadable_offset_tag(f):
    """The offset field paired with the one `f`'s time was read from, where it holds something that is no offset
    (BLD-unreadable_offset_tags): (field, value as text), else None. Read as no tag (`_own_offset`); a blank one is
    no tag at all."""
    tag = OFFSET_TAG_FOR.get((f.get("source_time_tag") or "").rsplit(":", 1)[-1])
    v = (f.get("raw_times") or {}).get(tag) if tag else None
    if v is None or (isinstance(v, str) and not v.strip()):
        return None
    return None if _parse_iso_offset(v) is not None else (tag, str(v))


def drift_offset_overrides(drift_artifact):
    """Map a COMPLETE photos-22 to `{(destination, bucket_key): validated_offset_seconds}` for every
    confirmed bucket, so compute_resolved_utc can re-resolve those photos under the operator-validated
    offset (BLD-resolved_utc). The bucket_key matches the photos-21 cell key it was built from."""
    out = {}
    for dest, d in ((drift_artifact or {}).get("destinations") or {}).items():
        for bucket, cell in (d.get("drift_decisions") or {}).items():
            eff = cell.get("effective_drift_offset")
            if isinstance(eff, dict) and "offset_seconds" in eff:
                out[(dest, bucket)] = eff["offset_seconds"]
    return out


# EXIF pairs each time field with the offset field recorded with it (BLD-resolved_utc): a time read from one is
# turned to UTC by its own offset, never by another field's.
OFFSET_TAG_FOR = {"DateTimeOriginal": "OffsetTimeOriginal", "CreateDate": "OffsetTimeDigitized",
                  "ModifyDate": "OffsetTime"}


def clock_group_key(f):
    """The camera group `f`'s time is solved under (BLD-modified_time_files): prep's, unless its time was read from
    `ModifyDate` — the editing computer's clock, not the camera's — then `NO_IDENTITY_KEY`, solved on its own as a
    file naming no camera is (RUL-modified_time_solved_alone). `CreateDate` is the camera's clock still. A photo with
    no recorded time reads no clock at all: `NO_IDENTITY_KEY` too, in no camera's offset or class question
    (RUL-date_fallback_no_clock_evidence)."""
    if untimed(f) or (f.get("source_time_tag") or "").rsplit(":", 1)[-1] == "ModifyDate":
        return NO_IDENTITY_KEY
    return f["camera_group_key"]


def _own_offset(f):
    """The offset, in seconds, recorded with the field `f`'s time was read from, or None. Prep names the field
    with its group (`EXIF:DateTimeOriginal`, BLD-metadata_extraction); the offset is the paired field's, from its own
    group."""
    value = f.get("source_naive_time")
    if isinstance(value, str) and len(value) > 19:
        # an offset written in the time's own value (XMP: `…10:00:00+02:00`, `…10:00:00.5Z`) is the one
        # recorded with it, before any field beside it
        within = _parse_iso_offset(re.sub(r"^\.\d+", "", value[19:]))
        if within is not None:
            return within
    tag = OFFSET_TAG_FOR.get((f.get("source_time_tag") or "").rsplit(":", 1)[-1])
    return _parse_iso_offset((f.get("raw_times") or {}).get(tag)) if tag else None


def _read_offset(f, tz):
    """The clock offset a phone's photo `f` is read by without a cell of its own (BLD-phone_offset_cell): −(the offset
    recorded with its time), else −(its destination zone `tz`'s at its time); None with neither, or at a time the zone
    skips or repeats."""
    own = _own_offset(f)
    if own is not None:
        return -own
    z = _timezone_naive_offset(f.get("source_naive_time"), tz) if _valid_iana(tz) else None
    return z[0] if z else None


def recorded_offset_proposal(photos, rep_naive):
    """A camera bucket's offset from the offset its photos record with their times (BLD-recorded_offset_proposal), as
    (proposal, differ). The offset is the one recorded with the field each photo's time was read from (`_own_offset`;
    a value that is no offset is none). Every photo recording one recording the same: its clock was on that UTC
    offset, so the proposal is −(it) — `differ` None. Photos recording different ones propose nothing: `differ` holds
    each offset recorded, its count and one photo. No photo recording one: (None, None)."""
    seen = {}
    for f in sorted(photos, key=lambda x: x["relative_path"]):
        own = _own_offset(f)
        if own is not None:
            seen.setdefault(own, []).append(f["relative_path"])
    if not seen:
        return None, None
    if len(seen) > 1:
        return None, [{"recorded_offset_seconds": o, "photos": len(seen[o]), "example": seen[o][0]}
                      for o in sorted(seen)]
    (own, paths), = seen.items()
    proposal = {"proposal_source": "recorded_offset", "proposed_offset_seconds": -own,
                "recorded_offset_seconds": own, "recorded_by": len(paths), "example": paths[0],
                "confidence": "review_required"}
    naive = _parse_camera_naive(rep_naive)
    if naive is not None:
        try:
            proposal["proposed_real_utc"] = (naive - timedelta(seconds=own)).strftime("%Y-%m-%dT%H:%M:%SZ")
        except OverflowError:
            pass                                # a time at the calendar's edge: no instant to name
    return proposal, None


_GPS_TIME_RE = re.compile(r"^(\d{4}:\d\d:\d\d \d\d:\d\d:\d\d)(?:\.\d+)?(Z|[+-]\d\d:?\d\d)?$")
_GPS_CLOCK_RE = re.compile(r"^(\d{1,2}):(\d{1,2}):(\d{1,2})(?:\.\d+)?$")


def gps_fix_utc(parsed):
    """The UTC time the photo's GPS fix recorded (BLD-gps_time_proposal), as 'YYYY-MM-DDTHH:MM:SSZ', or None: its
    `GPSDateTime` (exiftool's composite of the two fields below, or XMP's own), else `GPSDateStamp` with
    `GPSTimeStamp`. A fix's time is UTC; a fraction of a second is dropped. A value that is no time is none."""
    v = parsed.get("GPSDateTime")
    if isinstance(v, str) and (m := _GPS_TIME_RE.match(v.strip())):
        t = parse_naive_time(m.group(1))
        off = _parse_iso_offset(m.group(2)) if m.group(2) else 0
        if t is not None and off is not None:
            try:
                return (t - timedelta(seconds=off)).strftime("%Y-%m-%dT%H:%M:%SZ")
            except OverflowError:
                return None
    d, c = parsed.get("GPSDateStamp"), parsed.get("GPSTimeStamp")
    if isinstance(d, str) and isinstance(c, str) and (m := _GPS_CLOCK_RE.match(c.strip())):
        h, mi, s = (int(x) for x in m.groups())
        t = parse_naive_time(f"{d.strip()[:10]} {h:02d}:{mi:02d}:{s:02d}")
        if t is not None:
            return t.strftime("%Y-%m-%dT%H:%M:%SZ")
    return None


def gps_time_proposal(frames, cfg):
    """A clock offset from the times the frames' own GPS fixes recorded (BLD-gps_time_proposal), as (proposal,
    set_aside). Each frame holding its own position and a fix time gives the fix's UTC less its camera time; frames
    giving the same fix time and the same camera time are one reading (a burst). The readings count only while
    their fix times all differ — a stale fix repeats its time while the camera's moves on — and their offsets agree
    within `gpx_anchor_offset_spread_max_seconds`: then the proposal is the earliest reading's offset (`gps_time`);
    else nothing is proposed, `set_aside` saying why. No frame with a fix time: (None, None)."""
    rows = gps_readings(frames)
    if not rows:
        return None, None
    fix_times = [r["gps_utc"] for r in rows]
    offs = [r["offset_seconds"] for r in rows]
    if len(set(fix_times)) < len(fix_times):
        twice = next(r for r in rows if fix_times.count(r["gps_utc"]) > 1)
        return None, {"reason": "repeated_gps_time", "gps_time_count": len(rows), "example": twice["source_file"]}
    if max(offs) - min(offs) > cfg["gpx_anchor_offset_spread_max_seconds"]:
        far = max(rows, key=lambda r: abs(r["offset_seconds"] - offs[0]))
        return None, {"reason": "offsets_disagree", "gps_time_count": len(rows), "example": far["source_file"],
                      "offsets_seconds": [min(offs), max(offs)]}
    rep = rows[0]
    return {"proposal_source": "gps_time", "proposed_offset_seconds": rep["offset_seconds"],
            "proposed_real_utc": rep["gps_utc"], "gps_time_count": len(rows),
            "confidence": "high" if len(rows) > 1 else "review_required",
            "acceptance_tolerance_seconds": cfg["gpx_anchor_decision_tolerance_seconds"],
            "gps_times": rows[:GPS_TIMES_SHOWN]}, None


def gps_readings(frames):
    """The readings of the clock the frames' own GPS fixes give (BLD-gps_time_proposal), in camera-time order: each
    frame holding its own position and a fix time gives `{source_file, camera_source_naive_time, gps_utc,
    offset_seconds}` — the fix's UTC less its camera time — frames giving the same fix time and the same camera time
    being one reading (a burst)."""
    readings = {}
    for f in sorted(frames, key=lambda x: x["relative_path"]):
        gps, naive = _parse_utc(f.get("gps_utc")), _parse_camera_naive(f.get("source_naive_time"))
        if not f.get("has_native_gps") or gps is None or naive is None:
            continue
        readings.setdefault((gps, naive), f)
    ordered = sorted(readings.items(), key=lambda kv: (kv[0][1], kv[1]["relative_path"]))
    return [{"source_file": f["relative_path"], "camera_source_naive_time": f.get("source_naive_time"),
             "gps_utc": gps.strftime("%Y-%m-%dT%H:%M:%SZ"),
             "offset_seconds": int(round((gps.replace(tzinfo=None) - naive).total_seconds()))}
            for (gps, naive), f in ordered]


# How many of a GPS-time proposal's readings its record lists (the count says how many there are).
GPS_TIMES_SHOWN = 20


def far_from_evidence(times, others, track_times, bound):
    """Whether a guessed offset leaves a cell's photos where nothing else was (BLD-offset_far_from_evidence): None
    where there is no other device's photo to tell (`others` empty), or a photo of the cell at `times` lies within
    `bound` seconds of one of `others` [(path, aware UTC)] or of a track point (`track_times`, sorted). Else the
    reason: how far the nearest of each lies."""
    if not others or not times:
        return None
    other_times = sorted((t, p) for p, t in others)
    keys = [t for t, _p in other_times]

    def nearest(sorted_times, t):
        i = bisect.bisect_left(sorted_times, t)
        return min((abs((sorted_times[j] - t).total_seconds()), j) for j in (i - 1, i) if 0 <= j < len(sorted_times))
    near_other = min(nearest(keys, t) for t in times)
    near_track = min((nearest(track_times, t)[0] for t in times), default=None) if track_times else None
    if near_other[0] <= bound or (near_track is not None and near_track <= bound):
        return None
    return {"max_clock_error_seconds": bound, "other_photos": len(others),
            "nearest_other_photo": other_times[near_other[1]][1],
            "nearest_other_photo_seconds": int(near_other[0]),
            "nearest_track_seconds": int(near_track) if near_track is not None else ""}


def compute_resolved_utc(files, groups, artifact, offset_overrides=None):
    """Resolve every by-dest photo to real UTC from the completed time decisions (BLD-resolved_utc). Camera
    groups use their (group, destination) effective offset (absolute camera->UTC correction);
    smartphones the offset recorded with the field their time was read from, else the destination
    timezone. `offset_overrides`
    (from photos-22) replaces a bucket's offset with the operator-validated one. Returns
    per-file rows (the BLD-resolved_utc fields), path-sorted and deterministic."""
    dests = artifact.get("destinations") or {}
    overrides = offset_overrides or {}
    rows = []
    for f in sorted(files, key=lambda x: x["relative_path"]):
        dest, key = f["destination"], f["camera_group_key"]
        d = dests.get(dest, {})
        tz = (d.get("destination_timezone") or {}).get("effective_iana_timezone") or ""
        cls = (groups.get(key) or {}).get("camera_group_class")
        naive = _parse_camera_naive(f.get("source_naive_time"))
        resolved, status, rule, offset_used, prov = None, "unresolved", "missing_timestamp", None, None
        scope = key
        try:
            resolved, status, rule, offset_used, prov, scope = _resolve_one(f, d, cls, naive, tz, key, dest, overrides)
        except OverflowError:
            # a time at the edge of the calendar (year 1, year 9999) that its offset carries past it
            resolved, status, rule = None, "unresolved", "time_out_of_range"
        rows.append({
            "relative_path": f["relative_path"], "destination_path": dest, "destination_timezone": tz,
            "camera_group": key, "time_decision_scope": f"{scope}|{dest}",
            "source_naive_time": f.get("source_naive_time"), "source_time_provenance": f.get("source_time_tag"),
            "time_rule_used": rule, "utc_offset_used": offset_used,
            "resolved_utc": (resolved.strftime("%Y-%m-%dT%H:%M:%SZ") if resolved is not None else None),
            "resolved_utc_status": status, "resolved_utc_provenance": prov,
        })
    return rows


def _resolve_one(f, d, cls, naive, tz, key, dest, overrides):
    """One photo's (resolved UTC, status, rule, offset used, provenance, decision scope) — see
    compute_resolved_utc."""
    resolved, status, rule, offset_used, prov = None, "unresolved", "missing_timestamp", None, None
    scope = key
    fill = date_fallback_time(f, d) if naive is None else None
    if fill is not None:
        # no recorded time: its destination's date fallback, its day at midnight, read by the zone like any local
        # time — a midnight it skips or repeats as the user answered (BLD-date_fallback_cell) — never by a clock offset
        if tz:
            resolved, status, amb_rule, offset_used = _resolve_by_zone(fill, tz, _reading_answer(f, d))
            rule, prov = amb_rule or "date_fallback", tz
        else:
            status, rule = "unresolved", "timezone_missing"
    elif naive is not None and f.get("true_time"):
        # the user kept this time as the photo's true one, local to its destination (BLD-changed_time_kept): read by the
        # zone — a time it skips or repeats as the user answered — never by a clock offset
        if tz:
            resolved, status, amb_rule, offset_used = _resolve_by_zone(naive, tz, _reading_answer(f, d))
            rule, prov = amb_rule or "kept_true_time", tz
        else:
            status, rule = "unresolved", "timezone_missing"
    elif naive is not None and f.get("geotag_marker"):
        # geotag corrected this time already: it is destination-local, offset tag beside it
        own_off = _own_offset(f)
        if own_off is not None:
            offset_used, resolved = own_off, naive - timedelta(seconds=own_off)
            status, rule = "valid", "geotag_corrected"
        elif tz:
            resolved, status, amb_rule, offset_used = _resolve_by_zone(naive, tz, _reading_answer(f, d))
            rule, prov = amb_rule or "geotag_corrected", tz
        else:
            status, rule = "unresolved", "timezone_missing"
    elif naive is not None:
        if cls == "camera":
            # per-date offset bucket: a destination split over >1 naive date keys cells
            # `group@YYYY-MM-DD`; the single-date common case keeps the bare `group` key.
            cells = d.get("camera_group_time_decisions") or {}
            bucket_key = offset_cell_key(cells, key, f.get("source_naive_time"), f["relative_path"])   # a split day: its part
            scope = bucket_key                         # the cell this photo's offset comes from
            cell = cells.get(bucket_key) or {}
            eff = cell.get("effective_time_anchor")
            if (dest, bucket_key) in overrides:        # BLD-resolved_utc: operator-validated offset wins
                offset_used = overrides[(dest, bucket_key)]
                resolved = naive + timedelta(seconds=offset_used)
                status, rule, prov = "valid", "camera_group_offset", "gps_drift_validated"
            elif isinstance(eff, dict) and "offset_seconds" in eff:
                offset_used = eff["offset_seconds"]
                resolved = naive + timedelta(seconds=offset_used)
                status, rule, prov = "valid", "camera_group_offset", eff.get("source")
            else:
                status, rule = "unresolved", "offset_missing"
        elif cls in ("smartphone", "unidentified"):   # a phone, or a file naming no camera, each solved on its own
            native_off = _own_offset(f)
            cells = (d.get("camera_group_time_decisions") or {}) if cls == "smartphone" else {}
            bucket_key = f"{key}@{_naive_date(f.get('source_naive_time'))}"
            bucket_key = bucket_key if bucket_key in cells else key
            cell = cells.get(bucket_key) or {}
            eff = cell.get("effective_time_anchor")
            applies = (cell.get("phone") or {}).get("applies_to")
            if cell and (applies == "every_photo" or (applies == "untagged_photos" and native_off is None)) \
                    and not (isinstance(eff, dict) and eff.get("source") == "as_recorded"):
                # the phone's own GPS says its clock was otherwise that day here (BLD-phone_offset_cell)
                scope = bucket_key
                by_zone = isinstance(eff, dict) and eff.get("source") in ("timezone_accepted", "timezone_unconfirmed")
                if by_zone and overrides.get((dest, bucket_key), eff.get("offset_seconds")) == eff.get("offset_seconds"):
                    # the zone's reading accepted, or confirmed as it stood: each photo by the zone at its own time — a
                    # phone's clock follows a daylight-saving change (BLD-phone_offset_cell)
                    resolved, status, amb_rule, offset_used = _resolve_by_zone(naive, tz, _reading_answer(f, d)) \
                        if tz else (None, "unresolved", "timezone_missing", None)
                    rule, prov = amb_rule or "destination_timezone", eff.get("source")
                elif (dest, bucket_key) in overrides:
                    offset_used = overrides[(dest, bucket_key)]
                    resolved = naive + timedelta(seconds=offset_used)
                    status, rule, prov = "valid", "camera_group_offset", "gps_drift_validated"
                elif isinstance(eff, dict) and "offset_seconds" in eff:
                    offset_used = eff["offset_seconds"]
                    resolved = naive + timedelta(seconds=offset_used)
                    status, rule, prov = "valid", "camera_group_offset", eff.get("source")
                else:
                    status, rule = "unresolved", "offset_missing"
            elif native_off is not None:
                offset_used, resolved = native_off, naive - timedelta(seconds=native_off)
                status = "valid"
                rule = "unidentified_native_offset" if cls == "unidentified" else "smartphone_native_offset"
            elif cls == "unidentified" and not tz:
                status, rule = "unresolved", "timezone_missing"
            elif cls == "unidentified" and (d.get("unidentified_files") or {}).get("effective_iana_timezone") != tz:
                # read as local time only once the user said so for the destination (BLD-unidentified_files_question)
                status, rule = "unresolved", "local_time_unconfirmed"
            elif tz:
                resolved, status, amb_rule, offset_used = _resolve_by_zone(naive, tz, _reading_answer(f, d))
                rule, prov = amb_rule or "destination_timezone", tz
            else:
                status, rule = "unresolved", "timezone_missing"
        else:
            # A group classed neither phone nor camera stops geotag before this (RUL-unknown_group_stops_geotag); were
            # one ever to reach here it stays unresolved — never solved as a phone would be (BLD-resolved_utc).
            status, rule = "unresolved", "camera_group_unclassified"
    return resolved, status, rule, offset_used, prov, scope


def resolved_utc_fingerprint(rows, input_fingerprints):
    """BLD-resolved_utc_fingerprint: a SHA-256 over the path-sorted per-file resolved facts plus the input fingerprints
    that produced them — stable across unchanged-input reruns, re-verifiable downstream like a JSON
    artifact's SHA-256."""
    parts = []
    for r in sorted(rows, key=lambda x: x["relative_path"]):
        parts.append("|".join(str(r.get(k)) for k in
                     ("relative_path", "resolved_utc", "resolved_utc_status",
                      "time_rule_used", "utc_offset_used", "source_time_provenance")))
    parts.append("INPUTS|" + "|".join(f"{k}={input_fingerprints[k]}" for k in sorted(input_fingerprints)))
    return sha256_text("\n".join(parts))


def _interp(a, b, target):
    """Linear time-fraction interpolation of (lat, lon) between GPX points `a` and `b` at `target`, the short
    way round in longitude. `target` outside [a.time, b.time] extrapolates the a->b vector (ratio <0 or >1)."""
    span = (b.time_utc - a.time_utc).total_seconds()
    if span == 0:
        return a.lat, a.lon
    r = (target - a.time_utc).total_seconds() / span
    return a.lat + r * (b.lat - a.lat), _wrap_lon(a.lon + r * _lon_delta(a.lon, b.lon))


def _extrapolate(pts, end, step, target, cfg):
    """A photo past a track's end `pts[end]` (`step` -1: the track goes on backwards from it, i.e. the photo
    is after its last point; +1: before its first), placed along the track's heading there. The heading is
    taken over the track's last stretch (`gpx_extrapolation_heading_seconds`) — never over its last two
    points alone, whose jitter a five-minute projection would turn into kilometres. A projection farther
    than `gpx_extrapolation_max_distance_meters`, or from a track moving faster than
    `gpx_extrapolation_max_speed_kmh`, is no reading of where the photo was: the photo is placed at the
    track's end. The heading is the end's own segment's: a point past a break in the recording is none of it
    (RUL-track_break_never_bridged)."""
    anchor = pts[end]
    lat, lon = anchor.lat, anchor.lon
    other, i = None, end + step
    while 0 <= i < len(pts) and pts[i].segment == anchor.segment \
            and abs((pts[i].time_utc - anchor.time_utc).total_seconds()) <= cfg["gpx_extrapolation_heading_seconds"]:
        other, i = pts[i], i + step
    if other is not None and other.time_utc != anchor.time_utc:
        plat, plon = _interp(other, anchor, target)
        dist = haversine(anchor.lat, anchor.lon, plat, plon) if -90.0 <= plat <= 90.0 else float("inf")
        base = abs((anchor.time_utc - other.time_utc).total_seconds())
        speed_kmh = haversine(other.lat, other.lon, anchor.lat, anchor.lon) / base * 3.6
        if dist <= cfg["gpx_extrapolation_max_distance_meters"] and speed_kmh <= cfg["gpx_extrapolation_max_speed_kmh"]:
            lat, lon = plat, plon
    return {"lat": round(lat, 6), "lon": round(lon, 6), "method": "extrapolated", "gpx_file": anchor.source_file,
            "gpx_track": anchor.track, "seconds_from_track": abs((target - anchor.time_utc).total_seconds())}


def _place_on_track(pts, times, target, cfg):
    """One track's placement of an instant (BLD-track_placement): a point within the direct-match window, else between
    the two points around it within the interpolation caps, else past an end of the track within the
    extrapolation window. A track's end is its first or last point, either side of a gap longer than
    points are joined across, or either side of a break between two of its `<trkseg>`, which nothing is placed
    across however short (RUL-track_break_never_bridged). Returns (placement | None, why not)."""
    i = bisect.bisect_right(times, target)            # pts[i-1].time <= target < pts[i].time
    before = pts[i - 1] if i else None
    after = pts[i] if i < len(pts) else None
    near = [(abs((p.time_utc - target).total_seconds()), n, p) for n, p in enumerate((before, after)) if p is not None]
    d, _n, p = min(near, key=lambda x: (x[0], x[1]))
    if d <= cfg["gpx_direct_match_max_seconds"]:
        return {"lat": p.lat, "lon": p.lon, "method": "direct_match", "gpx_file": p.source_file,
                "gpx_track": p.track, "seconds_from_track": d}, None
    why = {"reason": "outside_track", "seconds_from_track": d}
    if before is not None and after is not None and before.segment != after.segment:
        # the recording broke between them: a gap in the track, whatever its length
        why = {"reason": "track_gap", "seconds_from_track": d,
               "gap_seconds": round((after.time_utc - before.time_utc).total_seconds()), "segment_break": True}
    elif before is not None and after is not None:
        gap = (after.time_utc - before.time_utc).total_seconds()   # > 0: before <= target < after
        if gap <= cfg["gpx_interpolation_max_gap_seconds"]:
            dist = haversine(before.lat, before.lon, after.lat, after.lon)
            if dist <= cfg["gpx_interpolation_max_distance_meters"] \
                    and dist / gap * 3.6 <= cfg["gpx_interpolation_max_speed_kmh"]:
                lat, lon = _interp(before, after, target)
                return {"lat": round(lat, 6), "lon": round(lon, 6), "method": "interpolated",
                        "gpx_file": before.source_file, "gpx_track": before.track, "seconds_from_track": d}, None
            return None, {"reason": "track_jump", "seconds_from_track": d, "jump_meters": round(dist)}
        why = {"reason": "track_gap", "seconds_from_track": d, "gap_seconds": round(gap)}
    if d <= cfg["gpx_extrapolation_max_seconds"]:     # past an end of the track, or of its recording
        if p is before:
            return _extrapolate(pts, i - 1, -1, target, cfg), None
        return _extrapolate(pts, i, +1, target, cfg), None
    return None, why


_METHOD_RANK = {"direct_match": 0, "interpolated": 1, "extrapolated": 2}


def place_gps(target_utc, gpx, cfg, why=None):
    """Place a photo at its resolved UTC against the GPX tracks (BLD-track_placement), or None when no reliable
    placement exists. Each track places it on its own (_place_on_track). A projection past one track's end is no
    witness against a track that covers the instant, so the projections count only where no track covers it. Of
    those that count, the highest-ranked tracks decide (RUL-highest_ranked_track_places), and of them the closest
    evidence wins: a point at its time before the place between two, before a projection past an end; then the
    track nearest in time. Tracks of that rank that put the photo in different places — farther apart than
    `gpx_tracks_agree_max_distance_meters` — are two devices in two places, and nothing here says which carried the
    camera: the photo is not placed (RUL-disagreeing_tracks_place_nothing). A lower-ranked track never stops it; how
    far each put it is kept with the placement, as `lower_tracks` (RUL-lower_track_distance_recorded). `why`, a
    dict, is filled with the reason when nothing places it."""
    placed, missed = [], []
    for src, pts, times in gpx.tracks():
        p, w = _place_on_track(pts, times, target_utc, cfg)
        if p is not None:
            p["rank"] = gpx.rank(src)
            placed.append(p)
        else:
            missed.append(w)
    if not placed:
        if why is not None:
            why.update(min(missed, key=lambda w: w["seconds_from_track"]) if missed else {"reason": "no_tracks"})
            if "seconds_from_track" in why:
                why["seconds_from_track"] = round(why["seconds_from_track"])
        return None
    pool = [p for p in placed if p["method"] != "extrapolated"] or placed
    top = min(p["rank"] for p in pool)
    ranked = sorted((p for p in pool if p["rank"] == top),
                    key=lambda p: (_METHOD_RANK[p["method"]], p["seconds_from_track"], p["gpx_file"], p["gpx_track"]))
    best = ranked[0]
    for p in ranked[1:]:
        apart = haversine(best["lat"], best["lon"], p["lat"], p["lon"])
        if apart > cfg["gpx_tracks_agree_max_distance_meters"]:
            if why is not None:
                # two tracks of one file are named by their place in it (RUL-track_is_one_trk)
                same = best["gpx_file"] == p["gpx_file"]
                name = lambda q: f"{q['gpx_file']} (track {q['gpx_track'] + 1})" if same else q["gpx_file"]
                why.update({"reason": "tracks_disagree", "gpx_files": sorted((name(best), name(p))),
                            "apart_meters": round(apart)})
            return None
    out = {k: v for k, v in best.items() if k not in ("seconds_from_track", "gpx_track", "rank")}
    lower = sorted((p for p in pool if p["rank"] > top), key=lambda p: (p["gpx_file"], p["gpx_track"]))
    if lower:
        files = [p["gpx_file"] for p in lower]
        out["lower_tracks"] = [{"gpx_file": (f"{p['gpx_file']} (track {p['gpx_track'] + 1})"
                                             if files.count(p["gpx_file"]) > 1 else p["gpx_file"]),
                                "apart_meters": round(haversine(best["lat"], best["lon"], p["lat"], p["lon"]))}
                               for p in lower]
    return out


def _valid_coord(lat, lon):
    """True iff (lat, lon) is a numeric coordinate in range (RUL-checked_positions_and_times)."""
    return (isinstance(lat, (int, float)) and not isinstance(lat, bool) and -90 <= lat <= 90
            and isinstance(lon, (int, float)) and not isinstance(lon, bool) and -180 <= lon <= 180)


# place_gps method -> BLD-placement_order automatic GPS category.
_GPS_PLACE_CATEGORY = {"direct_match": "gpx_interpolation", "interpolated": "gpx_interpolation",
                       "extrapolated": "gpx_extrapolation"}


def classify_gps(file, resolved_utc, gpx, cfg, effective_fallback, file_decision, why=None, replace_own=False):
    """The GPS decision for one file (BLD-placement_order), as (category, coord|None). Resolves in
    priority order: preserve native -> per-file manual lock -> GPX interpolation/extrapolation at the
    resolved UTC -> the destination's effective folder fallback -> blocked: a photo none of these places waits for
    the user (RUL-unplaced_photo_waits), never left without a position. A photo's own
    position gives way only to a position the user set for it, where `replace_own` says its review item is of an own
    position its clock offset contradicts (RUL-own_position_replaced_on_answer).
    Authored coordinates are assumed already range-validated by the caller (RUL-checked_positions_and_times)."""
    fd = file_decision or {}
    mlat, mlon = fd.get("manual_lat", ""), fd.get("manual_lon", "")
    manual = mlat not in (None, "") and mlon not in (None, "")
    if file.get("has_native_gps"):
        if replace_own and manual:
            return "manual_locked", {"lat": mlat, "lon": mlon}
        return "preserve_native", None
    if manual:
        return "manual_locked", {"lat": mlat, "lon": mlon}
    if untimed(file):
        # timed by its folder's date fallback: that time is not when it was taken, so no track places it by it
        # (RUL-date_fallback_never_placed_by_tracks)
        if why is not None:
            why["reason"] = "time_from_date_fallback"
    elif resolved_utc is not None:
        p = place_gps(resolved_utc, gpx, cfg, why)
        if p is not None:
            return _GPS_PLACE_CATEGORY[p["method"]], p
    if effective_fallback is not None:
        return "manual_fallback", effective_fallback
    return "blocked", None


def held_pre_state(file):
    """The position `file` holds now, in the pre-state shape the log records beside a write that replaces
    or clears it (BLD-geotag_log_steps): the coordinates with their GPSProcessingMethod, or 'absent'."""
    h = held_values(file)
    if h.get("lat") is not None and h.get("lon") is not None:
        return {"present": True, "GPSLatitude": h["lat"], "GPSLongitude": h["lon"],
                "GPSProcessingMethod": h.get("method") or ""}
    return {"present": False}


def holds_no_fix(file):
    """Whether `file` holds a position that is none of its own — latitude 0 and longitude 0
    (RUL-null_island_is_no_position): a position written over it is logged with it
    (RUL-log_records_null_island_replaced)."""
    h = held_values(file)
    return h.get("lat") is not None and h.get("lon") is not None and not has_own_position(h["lat"], h["lon"])


def _coordinate_tags(lat, lon):
    """The complete EXIF coordinate tag set for a signed decimal position (BLD-position_tags).

    EXIF stores latitude/longitude as UNSIGNED magnitudes; the hemisphere lives in the separate
    GPSLatitudeRef/GPSLongitudeRef tags. Writing the coordinate alone leaves the fix half-written:
    exiftool does not derive the ref, and a reader that follows the spec (exiv2/digiKam, PIL,
    Lightroom) reports NO location at all. Worse, `exiftool -n` stores a negative coordinate as its
    absolute value, so a southern/western position silently reads back in the opposite hemisphere.
    Always emit all four tags together."""
    return {"GPSLatitude": lat, "GPSLatitudeRef": "N" if lat >= 0 else "S",
            "GPSLongitude": lon, "GPSLongitudeRef": "E" if lon >= 0 else "W"}


# The tag writes that clear a position geotag wrote. The hemisphere refs go too — a ref left behind
# without its coordinate is a torn fix.
_CLEARED_POSITION = {"GPSLatitude": "", "GPSLatitudeRef": "", "GPSLongitude": "", "GPSLongitudeRef": ""}


def _walk_ancestors(dest):
    """Yield `dest`'s ancestor destination paths within 6-photos-by-dest, nearest first."""
    root = folder_name('photos_by_dest')
    d = os.path.dirname(dest)
    while d == root or d.startswith(root + "/"):
        yield d
        if d == root:
            break
        d = os.path.dirname(d)


def _nearest_ancestor(dest, eff, key):
    """The deepest ancestor of `dest` with a RESOLVED value in `eff` for `key`, as (path, value), or
    None. Shared by the two facts that cascade downward — the destination timezone (RUL-timezone_from_nearest) and the
    folder GPS fallback (RUL-fallback_from_nearest); a clock offset never does (RUL-offset_from_own_evidence). `eff`
    maps (destination, key) -> resolved value; only already-processed, resolved ancestors qualify, so an unconfirmed
    one is reached past."""
    for d in _walk_ancestors(dest):
        v = eff.get((d, key))
        if v is not None:
            return d, v
    return None


def _expand_destinations(by_dest):
    """Enumerate the destinations to decide on, given {real_dest: [files]}.

    Returns (ordered, containers):
      * `ordered` — the real (media-bearing) destinations PLUS every ancestor folder within the
        by-dest tree, sorted parent-first (so an ancestor's effective timezone/fallback is known before
        a child inherits it).
      * `containers` — the file-less ancestors (folders that hold only sub-destinations). A container
        carries a timezone and a GPS-fallback decision purely so a human can set defaults that propagate
        DOWN to its children; it has no media, so it carries no clock-offset cells."""
    real = set(by_dest)
    containers = set()
    for dest in by_dest:
        for anc in _walk_ancestors(dest):
            if anc not in real:
                containers.add(anc)
    ordered = sorted(real | containers, key=lambda d: (d.count('/'), d))
    return ordered, containers


def _ask_zone_at_containers(destinations, containers, stops):
    """Ask a timezone at every container destination with none, written or inherited, above a destination that waits
    for one a zone written at the container would reach (RUL-zone_asked_at_every_level, BLD-zone_asked_at_containers):
    the container's cell names those destinations in `asked_for` and requires input while it names any. A zone written
    there stops at a folder in `stops` — one with a zone written, or a country chosen — and passes nothing from a
    container where a country of several timezones is chosen. Answered there, or each destination answered below, the
    question is gone on the next run. Mutates the cells of `destinations`."""
    for c in containers:
        cell = destinations[c]["destination_timezone"]
        if cell["effective_iana_timezone"] or c in stops:
            continue                     # a zone reaches it, or one written or a country chosen here answers for it
        asked = []
        for d, v in destinations.items():
            if (d in containers or not d.startswith(c + "/")
                    or not v["destination_timezone"]["requires_user_input"]):
                continue
            way = [d] + [a for a in _walk_ancestors(d) if a.startswith(c + "/")]
            if not any(a in stops for a in way):
                asked.append(d)
        if asked:
            cell["asked_for"] = sorted(asked)
            cell["requires_user_input"] = True


def _dest_label(dest):
    """A destination's path relative to the by-dest root (the root itself shows as '(root)') — the
    progress label, so the heavy destination currently being worked on is recognizable."""
    rel = os.path.relpath(dest, folder_name('photos_by_dest'))
    return "(root)" if rel == "." else rel


# ============================================================================
# Stage 9 — no-clobber timestamp rename planning (BLD-rename_planning). Pure,
# exhaustively unit-tested. Filenames are destination-LOCAL civil time, never
# raw camera time or UTC; every on-disk + planned name is permanently occupied.
# ============================================================================

def destination_local_basename(resolved_utc, tz, fmt, ext):
    """The destination-local timestamp filename '<stamp><ext>' for a file (BLD-geotag_final_name), or None when it can
    not be positioned (no valid resolved UTC, or no destination timezone). The stamp is resolved UTC
    converted to the destination civil timezone and formatted with `fmt` (the shared
    filename_timestamp_format). `ext` is the file's current extension, including the leading dot."""
    dt = _parse_utc(resolved_utc)
    if dt is None or not tz:
        return None
    return _parse_utc(resolved_utc).astimezone(zoneinfo.ZoneInfo(tz)).strftime(fmt) + (ext or "")


# The mark of the temporary name a rename that changes only the case of a name passes through (BLD-case_rename_via).
CASE_RENAME_MARK = ".carto-case"


# The field that holds the fraction of a second beside each recorded-time field, as prep reads them.
_SUB_SECOND_FIELD = {"DateTimeOriginal": "SubSecTimeOriginal", "CreateDate": "SubSecTimeDigitized",
                     "ModifyDate": "SubSecTime"}


def recorded_sub_second(parsed):
    """The fraction of a second a photo records with its recorded time, as a number below 1, or None where it records
    none (RUL-suffix_in_capture_order): the fraction written in the recorded time itself, else the digits of the
    sub-second field beside that time (`SubSecTimeOriginal`, `"045"` is .045) (BLD-sub_second_read)."""
    value = parsed.get("selected_source_naive_timestamp")
    tag = (parsed.get("selected_source_timestamp_tag") or "").rsplit(":", 1)[-1]
    frac = re.match(r"\.(\d+)", str(value)[19:]) if parse_naive_time(value) else None
    sub = parsed.get(_SUB_SECOND_FIELD.get(tag, ""))
    if frac is None and sub is not None:
        frac = re.fullmatch(r"(\d+)", str(sub).strip())
    return float("0." + frac.group(1)) if frac else None


def plan_renames(files, fmt):
    """Plan no-clobber timestamp renames for the files of ONE destination (BLD-rename_planning). Returns
    {relative_path, current_name, planned_name, rename[, via]} per file, in relative_path order. EVERY
    file's current name is seeded as permanently occupied and never freed — a name a file will
    vacate is still treated as taken, so two files that would trade timestamps both land on distinct
    suffixed names rather than risking a clobber. Every planned name ends with its extension in lowercase
    (RUL-geotag_extension_lowercase): a name already carrying its timestamp keeps it, its extension alone
    lowercased. A rename that changes only the case of the name carries `via`, a free temporary name it
    passes through (BLD-case_rename_via). A file with no positionable timestamp keeps its
    name (no rename); the unplaceable case is surfaced as a blocker by the executable-plan stage.

    The photos given a new name of one timestamp take its suffixes in the order they were taken
    (RUL-suffix_in_capture_order): by true time, then by the fraction of a second they record (`sub_second`, where
    they record one), then by the suffix their names already hold — none first. Photos sharing a name, extension aside
    (a RAW and its JPEG), and given one timestamp are named as one: one name, one suffix, each its own extension
    (RUL-pair_named_as_one)."""
    occupied = {os.path.basename(f["relative_path"]).lower() for f in files}
    # every name held, its extension aside: a new name is free only where no photo holds it under any extension, so a
    # photo never lands beside another photo's RAW or JPEG (RUL-pair_named_as_one)
    stems = {os.path.splitext(n)[0] for n in occupied}
    held = {}                                         # each name, case folded: how many photos hold it
    for f in files:
        k = os.path.basename(f["relative_path"]).lower()
        held[k] = held.get(k, 0) + 1
    rows, groups = {}, {}
    for f in sorted(files, key=lambda x: x["relative_path"]):
        rel = f["relative_path"]
        name = os.path.basename(rel)
        ext = os.path.splitext(name)[1].lower()
        base = destination_local_basename(f.get("resolved_utc"), f.get("destination_timezone"), fmt, ext)
        stem = None if base is None else os.path.splitext(base)[0]
        if base is None or (carries_stem(name, stem) and name.endswith(ext)):
            # A name already carrying the timestamp keeps its suffix: renaming it to another suffix of the
            # same time would change nothing, and on the next run back again.
            rows[rel] = {"relative_path": rel, "current_name": name, "planned_name": name, "rename": False}
            continue
        if carries_stem(name, stem) and held[name.lower()] == 1:
            rows[rel] = _rename_row(f, os.path.splitext(name)[0] + ext, occupied)   # its own name, extension lowercased
            continue
        # To be given the first free name of its timestamp, with the photos it shares a name with, extension aside.
        groups.setdefault((stem, os.path.splitext(name)[0].lower()), []).append(f)
    named = []
    for (stem, _own), members in groups.items():
        exts = [os.path.splitext(f["relative_path"])[1].lower() for f in members]
        # one name for photos of different extensions only: two of one extension are two photos
        named.extend([(stem, members)] if len(set(exts)) == len(exts) else [(stem, [f]) for f in members])
    for stem, members in sorted(named, key=lambda g: (g[0],) + _capture_order(g[1], fmt)):
        # The first free name, by the one rule prep also uses (RUL-suffix_choice_by_phase): free under every extension.
        new = allocate_stem(stem, [""], stems, bare_first=True)
        for f in members:
            planned = new + os.path.splitext(f["relative_path"])[1].lower()
            occupied.add(planned.lower())
            rows[f["relative_path"]] = _rename_row(f, planned, occupied)
    return [rows[rel] for rel in sorted(rows)]


def _rename_row(f, planned, occupied):
    """The rename of `f` to `planned`: through a temporary name where only the case changes (BLD-case_rename_via)."""
    name = os.path.basename(f["relative_path"])
    ext = os.path.splitext(name)[1].lower()
    row = {"relative_path": f["relative_path"], "current_name": name, "planned_name": planned, "rename": True}
    if planned.lower() == name.lower():
        # Only the case changes: on a filesystem that ignores case the new name is the file's own, and a
        # no-clobber move refuses it — so it goes by a temporary name free here and in the plan.
        row["via"] = allocate_suffix(os.path.splitext(planned)[0] + CASE_RENAME_MARK, ext.lstrip("."),
                                     occupied, bare_first=True)
    return row


def _capture_order(members, fmt):
    """The key that orders photos given new names of one timestamp as they were taken (RUL-suffix_in_capture_order):
    the true time, then the fraction of a second recorded — a photo recording none after those that do — then the
    suffix its name holds after the timestamp prep named it by (`source_naive_time`), none first, then its path."""
    def held_suffix(f):
        name = os.path.splitext(os.path.basename(f["relative_path"]))[0]
        t = parse_naive_time(f.get("source_naive_time"))
        stem = t.strftime(fmt) if t is not None else None
        rest = name[len(stem) + 1:] if stem and carries_stem(name, stem) and name.lower() != stem.lower() else ""
        return int(rest) if rest.isdigit() else 0
    utcs = [_parse_utc(f.get("resolved_utc")) for f in members]
    subs = [f.get("sub_second") for f in members if f.get("sub_second") is not None]
    return (min(u for u in utcs if u is not None), not subs, min(subs) if subs else 0,
            min(held_suffix(f) for f in members), min(f["relative_path"] for f in members))


def plan_set_aside_rename(raw_rel, raw_name, jpeg, taken, follows=None):
    """The rename of a JPEG prep set aside beside the RAW at `raw_rel` to that RAW's name `raw_name`, extension aside,
    the JPEG's own extension in lowercase — a rename only, naming its RAW (`with_raw`): the new name the RAW's rename
    operation `follows` gives, which it is applied after (BLD-set_aside_renamed_with_raw); with none, the name the RAW
    holds since an earlier run renamed it without the JPEG (BLD-set_aside_jpeg_catches_up). None where the JPEG holds
    that name already, or where a file in redundant JPEGs holds it or is given it (`taken`, case folded, the name
    added once given): the JPEG is then left as it is."""
    rel = jpeg["relative_path"]
    name = os.path.basename(rel)
    to = os.path.splitext(raw_name)[0] + os.path.splitext(name)[1].lower()
    if to.lower() == name.lower() or to.lower() in taken:
        return None
    taken.add(to.lower())
    pre = {"content_fingerprint": jpeg.get("content_fingerprint"),
           "size": jpeg.get("size"), "mtime_ns": jpeg.get("mtime_ns")}
    semantic = {"from": name, "to": to, "with_raw": raw_rel}
    if follows:
        semantic["follows"] = follows
    return _make_op("rename_no_clobber", rel, "renamed with its RAW", semantic, pre)


# ============================================================================
# Stage 9 — executable plan operations (BLD-executable_plan). Pure op builders so
# the op list is deterministic and exhaustively unit-testable. Automatic GPS is
# RE-DERIVED here from inputs (classify_gps/place_gps), never read from the
# photos-23 summary (BLD-gps_decisions_record). Execution (RUL-execution_only_the_plan, Phase 6c) only applies
# these ops.
# ============================================================================

_GPS_OP_ORIGIN = {"gpx_interpolation": "recompute_automated", "gpx_extrapolation": "recompute_automated",
                  "manual_locked": "apply_manual", "manual_fallback": "apply_manual"}
_GPS_OP_MARKER = {"gpx_interpolation": "interpolated", "gpx_extrapolation": "extrapolated",
                  "manual_locked": "manual_locked", "manual_fallback": "manual_fallback"}
# A position from the tracks says how it was derived, so a rough pin is never taken for a precise one, in the
# workspace or in the library: on a track point (`matched`), between two (`interpolated`), or past a track's end
# (`extrapolated`). Keyed by place_gps's method.
_TRACK_MARKER = {"direct_match": "matched", "interpolated": "interpolated", "extrapolated": "extrapolated"}
# What geotag records in GPSProcessingMethod. A bare position marker means geotag set the position
# at the photo's true time — written, or already held; a re-run ignores the position and places the file again.
# The suffix, appended to whatever the field held (the device's own value, or nothing), means geotag wrote the
# time and kept the device's GPS or has set none — never on a photo whose time it did not write
# (RUL-only_corrected_time_marked). Anything else is the device's own: GPS native.
POSITION_MARKERS = ("matched", "interpolated", "extrapolated", "manual_locked", "manual_fallback")
TIME_FIXED_SUFFIX = "+carto-time"   # EXIF sets no length on the field; a JPEG's whole EXIF block is 64 KB


def geotag_marker(processing_method):
    """What geotag's mark in a GPSProcessingMethod value says: the bare position marker, the suffix
    (time fixed, no geotag position), or None for a device's own value or none."""
    v = processing_method.strip() if isinstance(processing_method, str) else ""
    if v in POSITION_MARKERS:
        return v
    return TIME_FIXED_SUFFIX if v.endswith(TIME_FIXED_SUFFIX) else None


def with_time_fixed(processing_method):
    """`processing_method` with the time-fixed suffix appended once (the device's value is kept)."""
    v = processing_method.strip() if isinstance(processing_method, str) else ""
    return v if v.endswith(TIME_FIXED_SUFFIX) else v + TIME_FIXED_SUFFIX


def device_method(processing_method):
    """The device's own GPSProcessingMethod within a value: geotag's suffix and position markers removed."""
    v = processing_method.strip() if isinstance(processing_method, str) else ""
    if v in POSITION_MARKERS:
        return ""
    return v[:-len(TIME_FIXED_SUFFIX)] if v.endswith(TIME_FIXED_SUFFIX) else v


# What the original-values ledger pins of a file before geotag first writes to it (BLD-original_values_pinned): its
# recorded time, and each time field geotag writes that a phone's time is resolved by, with its offset.
ORIGINAL_KEYS = ("selected_source_naive_timestamp", "selected_source_timestamp_tag", "DateTimeOriginal",
                 "OffsetTimeOriginal", "CreateDate", "OffsetTimeDigitized", "GPSLatitude", "GPSLongitude",
                 "GPSProcessingMethod", "has_native_gps")
_PINNED_TIMES = ("DateTimeOriginal", "OffsetTimeOriginal", "CreateDate", "OffsetTimeDigitized")
# The time a photo holds, as a re-plan compares it with its own and with what geotag wrote (BLD-changed_time_blocks).
TIME_PAIR = ("DateTimeOriginal", "OffsetTimeOriginal")


def own_values(parsed):
    """A file's own time, offset tag, position and GPSProcessingMethod, from prep's parsed metadata, in
    the shape the original-values ledger pins."""
    return {k: parsed.get(k) for k in ORIGINAL_KEYS}


def from_originals(file, original):
    """`file` decided from its pinned `original` values — as the device left it, before geotag's first
    write — while `held` keeps what it holds now, for the comparison. Pure; returns a new dict."""
    f = dict(file, held=held_values(file), from_originals=True, own_time={k: original.get(k) for k in TIME_PAIR})
    rt = {k: v for k, v in (file.get("raw_times") or {}).items() if k not in _PINNED_TIMES}
    for k in _PINNED_TIMES:
        if original.get(k) is not None:
            rt[k] = original[k]
    method = original.get("GPSProcessingMethod")
    # A pin is taken only of a file carrying no geotag mark (BLD-original_values_pinned): its position is the
    # device's — its own by the one test (BLD-own_position_test), latitude 0 and longitude 0 being none.
    has_gps = has_own_position(original.get("GPSLatitude"), original.get("GPSLongitude"))
    f.update(raw_times=rt, source_naive_time=original.get("selected_source_naive_timestamp"),
             source_time_tag=original.get("selected_source_timestamp_tag"),
             has_timestamp=original.get("selected_source_naive_timestamp") is not None,
             native_gps=({"lat": original.get("GPSLatitude"), "lon": original.get("GPSLongitude"),
                          "processing_method": method} if has_gps else None),
             has_native_gps=has_gps, geotag_marker=geotag_marker(method), processing_method=method)
    return f


def held_values(file):
    """What `file` holds now, as the comparison side of planning: its time, offset tag, position and
    GPSProcessingMethod. Differs from the file's decision basis only where the original-values ledger
    gave the basis the file's own values from before geotag's first write."""
    if file.get("held") is not None:
        return file["held"]
    rt, ng = file.get("raw_times") or {}, file.get("native_gps") or {}
    return {"DateTimeOriginal": rt.get("DateTimeOriginal"), "OffsetTimeOriginal": rt.get("OffsetTimeOriginal"),
            "lat": ng.get("lat"), "lon": ng.get("lon"), "method": file.get("processing_method"),
            **(file.get("other_times") or {})}


def held_other_times(parsed):
    """The other time fields a photo holds, by their group (BLD-other_time_fields_read): those geotag rewrites
    to the corrected time when it writes one."""
    return {k: parsed[k] for k in OTHER_TIME_FIELDS if parsed.get(k) is not None}


def _time_text(pair):
    """A time and its offset as a person reads them."""
    if not pair or pair.get("DateTimeOriginal") is None:
        return "no time"
    off = pair.get("OffsetTimeOriginal")
    return f"{pair['DateTimeOriginal']} {off}" if off else f"{pair['DateTimeOriginal']} with no offset"


# The answers to a time changed since geotag wrote it (BLD-changed_time_question): keep the time the photo holds — its
# true local time (BLD-changed_time_kept) — or take back geotag's.
CHANGED_TIME_ANSWERS = ("new", "geotag")


def changed_time(file):
    """What `file` holds of a time changed since geotag wrote it, or None (BLD-changed_time_blocks): a photo geotag wrote
    to — its own values pinned — holding a time and offset which are neither its own from before geotag's first write
    (the true time kept for it, where its pin keeps one: BLD-changed_time_kept_pinned) nor one geotag wrote.
    {"held_time", "geotag_wrote" (the last pair geotag wrote, or None), "own_time"}, each a
    {DateTimeOriginal, OffsetTimeOriginal}. A photo with no pin was never written by geotag here, and is not concerned."""
    if not file.get("from_originals"):
        return None
    h = held_values(file)
    held = {k: h.get(k) for k in TIME_PAIR}
    written = file.get("times_written") or []
    own = {k: (file.get("true_time") or file.get("own_time") or {}).get(k) for k in TIME_PAIR}
    if held == own or held in written:
        return None
    return {"held_time": held, "geotag_wrote": dict(written[-1]) if written else None, "own_time": own}


def keep_true_time(file, pair):
    """`file` decided from `pair` — a time the user kept as the photo's true time, local to its destination
    (BLD-changed_time_kept): its recorded time read from that DateTimeOriginal, with that offset tag, and `true_time`
    set, so it is resolved by its destination's zone, no clock offset applied, and kept out of its camera's evidence
    (BLD-changed_time_kept_not_anchor). Its own pinned values stay. Pure; returns a new dict."""
    pair = {k: pair.get(k) for k in TIME_PAIR}
    tag = file.get("source_time_tag") or ""
    tag = tag if tag.rsplit(":", 1)[-1] == "DateTimeOriginal" else "EXIF:DateTimeOriginal"
    rt = dict(file.get("raw_times") or {}, **{k: v for k, v in pair.items() if v is not None})
    if pair.get("OffsetTimeOriginal") is None:
        rt.pop("OffsetTimeOriginal", None)
    return dict(file, true_time=pair, raw_times=rt, source_naive_time=pair["DateTimeOriginal"], source_time_tag=tag,
                has_timestamp=_parse_camera_naive(pair["DateTimeOriginal"]) is not None)


def kept_tag_disagreement(pair, tz):
    """Where `pair` — a time the user is asked whether to keep as the true local time — holds an offset tag that its
    destination's zone `tz` does not give at that time (BLD-changed_time_kept_tag_noted): {"recorded_offset_seconds",
    "timezone", "timezone_offsets_seconds"} — the zone's offset there, or its two at a time it skips or repeats —
    else None. A tag holding no offset, or no time or zone to set it against, disagrees with nothing."""
    pair = pair or {}
    naive, own = _parse_camera_naive(pair.get("DateTimeOriginal")), _parse_iso_offset(pair.get("OffsetTimeOriginal"))
    if naive is None or own is None or not _valid_iana(tz):
        return None
    amb = _zone_ambiguity(naive, tz)
    if amb is not None:
        offsets = amb["offsets_seconds"]
    else:
        try:
            offsets = [int(_local_to_utc(naive, tz).astimezone(zoneinfo.ZoneInfo(tz)).utcoffset().total_seconds())]
        except OverflowError:
            return None
    if any(round(o / 60) * 60 == own for o in offsets):
        return None
    return {"recorded_offset_seconds": own, "timezone": tz, "timezone_offsets_seconds": offsets}


def changed_time_blocker(file):
    """Why the plan stops on `file`, or None (BLD-changed_time_blocks): a photo holding a time changed since geotag wrote
    it (`changed_time`) that the user has not answered for in photos-21 (BLD-changed_time_question). Geotag neither
    writes its own time back over it nor takes it as the photo's recorded time unasked. One kept is decided from its
    new time as its true local time; one whose answer is geotag's time is planned to have it written back."""
    if (file.get("changed_time") or {}).get("answer") in CHANGED_TIME_ANSWERS:
        return None
    ch = changed_time(file)
    if ch is None:
        return None
    held, written = ch["held_time"], file.get("times_written") or []
    wrote = _time_text(written[-1]) if written else "no time"
    return (f"{file['relative_path']}: holds the time {_time_text(held)}, but geotag wrote {wrote} to it, and its "
            f"own time before geotag was {_time_text(ch['own_time'])}. Its time was changed since geotag "
            "wrote to it: geotag neither writes its time back nor takes this one as the photo's unasked. Say which "
            "it keeps in photos-21 (changed_times, or the decision editor) and run `geotag plan` again — or put "
            "one of those back into the photo, then run `prep plan`, `prep execute` and `geotag plan` again.")


def _local_time_and_offset(resolved_utc, tz):
    """(DateTimeOriginal 'YYYY:MM:DD HH:MM:SS', OffsetTimeOriginal '+HH:MM') for a resolved UTC in the
    destination timezone, or (None, None) if unpositionable. The corrected time is destination-local
    civil time (RUL-corrected_time_written_local)."""
    dt = _parse_utc(resolved_utc)
    if dt is None or not tz:
        return None, None
    local = dt.astimezone(zoneinfo.ZoneInfo(tz))
    # The offset field holds hours and minutes. A zone's offset before it kept standard time has seconds
    # (Amsterdam in 1935: +00:19:32): it is written to the nearest minute, the local time exact.
    return local.strftime("%Y:%m:%d %H:%M:%S"), utc_offset_text(local.utcoffset().total_seconds())


def utc_offset_text(seconds):
    """A UTC offset in seconds as the offset field writes it, '+HH:MM' — to the nearest minute."""
    minutes = round(seconds / 60)
    return f"{'-' if minutes < 0 else '+'}{abs(minutes) // 60:02d}:{abs(minutes) % 60:02d}"


def _make_op(typ, rel, reason, semantic, preconditions):
    """An executable-plan operation with a deterministic operation_id (SHA-256 over its identity:
    type + path + semantic fields, NOT the verification preconditions)."""
    op = {"operation_id": sha256_text(json.dumps([typ, rel, semantic], sort_keys=True))[:16],
          "type": typ, "relative_path": rel, "reason": reason, "preconditions": preconditions}
    op.update(semantic)
    return op


def time_fixed_marker_op(file, method, clear_position=False):
    """The marker write recording that geotag fixed `file`'s time and wrote no position: `method`, the
    device's own GPSProcessingMethod with the suffix appended. With `clear_position`, the position an
    earlier geotag run wrote is cleared too."""
    pre = {"content_fingerprint": file.get("content_fingerprint"),
           "size": file.get("size"), "mtime_ns": file.get("mtime_ns")}
    writes = {"GPSProcessingMethod": method}
    if clear_position:
        writes = {**_CLEARED_POSITION, **writes}
    return _make_op("gps_marker_write", file["relative_path"], "time provenance", {"writes": writes}, pre)


def _other_time_writes(held, dto, off):
    """The corrected local time `dto` with its offset `off`, for each other field recording the photo's making
    that the photo already holds (BLD-other_time_fields_written), each in its own format — never a field it does
    not hold. ModifyDate and OffsetTime are the last edit's, and stay. A sub-second field stays too: a clock offset
    is whole seconds, so the fraction beside the time is still right — and one within XMP's value is kept in it."""
    w = {}
    if held.get("EXIF:CreateDate") is not None:
        w["EXIF:CreateDate"] = dto
        if held.get("EXIF:OffsetTimeDigitized") is not None:
            w["EXIF:OffsetTimeDigitized"] = off
    xmp = held.get("XMP:DateCreated")
    if xmp is not None:
        frac = re.match(r"\.\d+", str(xmp)[19:]) if parse_naive_time(xmp) else None
        w["XMP:DateCreated"] = dto + (frac.group(0) if frac else "") + off
    if held.get("IPTC:DateCreated") is not None:
        w["IPTC:DateCreated"] = dto[:10]
    if held.get("IPTC:TimeCreated") is not None:
        w["IPTC:TimeCreated"] = dto[11:] + off
    return w


def plan_file_ops(file, resolved_utc, tz, gps_category, gps_coord, rename):
    """The ordered executable operations for one file (BLD-executable_plan): corrected-time metadata write, GPS
    write + provenance marker, and no-clobber rename — each only where the file does not already
    hold it. Returns [] for a file that needs nothing (a no-op)."""
    rel = file["relative_path"]
    pre = {"content_fingerprint": file.get("content_fingerprint"),
           "size": file.get("size"), "mtime_ns": file.get("mtime_ns")}
    ops = []

    held = held_values(file)                      # what the file holds now: the comparison side
    # Corrected is the time geotag writes, never merely the one resolved (DEF-corrected_time): marked only when this
    # plan writes it, or when the field the photo holds already carries geotag's mark from an earlier run. A photo
    # holding its true time already is decided from its own values again on a re-run, with the same result: nothing
    # to write (RUL-only_corrected_time_marked).
    time_corrected = geotag_marker(held.get("method")) is not None
    dto, off = _local_time_and_offset(resolved_utc, tz)
    if dto is not None:
        writes = {"DateTimeOriginal": dto, "OffsetTimeOriginal": off}   # a local time always comes with its offset
        writes.update(_other_time_writes(held, dto, off))
        if any(held.get(k) != v for k, v in writes.items()):         # already held -> nothing to write
            ops.append(_make_op("metadata_time_write", rel, "corrected capture time", {"writes": writes}, pre))
            time_corrected = True

    if gps_category in _GPS_OP_ORIGIN and gps_coord is not None:
        new_marker = _TRACK_MARKER.get(gps_coord.get("method")) or _GPS_OP_MARKER[gps_category]
        same_fix = ((held.get("method") or "").strip() == new_marker
                    and isinstance(held.get("lat"), (int, float)) and isinstance(held.get("lon"), (int, float))
                    and round(held["lat"], 6) == round(gps_coord["lat"], 6)
                    and round(held["lon"], 6) == round(gps_coord["lon"], 6))
        if not same_fix:                          # a re-placed file already holding this fix: no write
            ops.append(_make_op("metadata_gps_write", rel, f"gps:{gps_category}",
                                {"writes": _coordinate_tags(gps_coord["lat"], gps_coord["lon"]),
                                 "gps_origin": _GPS_OP_ORIGIN[gps_category]}, pre))
            ops.append(_make_op("gps_marker_write", rel, "gps provenance",
                                {"writes": {"GPSProcessingMethod": new_marker}}, pre))
    elif time_corrected:
        target = with_time_fixed(device_method(file.get("processing_method")))
        if geotag_marker(held.get("method")) in POSITION_MARKERS:
            ops.append(time_fixed_marker_op(file, target, clear_position=True))   # geotag's old fix: not kept
        elif (held.get("method") or "").strip() != target:
            ops.append(time_fixed_marker_op(file, target))

    if rename and rename.get("rename"):
        semantic = {"from": rename["current_name"], "to": rename["planned_name"]}
        if rename.get("via"):
            semantic["via"] = rename["via"]           # a change of case alone: by a temporary name
        ops.append(_make_op("rename_no_clobber", rel, "destination-local timestamp name", semantic, pre))
    return ops


# ============================================================================
# Stage 11 — finalize: the photos-26 transformation log (BLD-phase_logs).
# Prep's per-photo log carried forward + geotag steps appended. A derived
# consolidation of artifacts already written — no new authority.
# ============================================================================

def describe_offset(seconds):
    """A clock offset as a person reads it (BLD-geotag_log_steps). The offset is what is added to the camera's
    time to reach UTC, so a negative one means the camera's clock ran ahead of UTC."""
    if not seconds:
        return "camera clock on UTC"
    s = abs(int(seconds))
    parts = [f"{v} {u}" for v, u in ((s // 3600, "h"), (s % 3600 // 60, "min"), (s % 60, "s")) if v]
    return f"camera clock {' '.join(parts)} {'ahead of' if seconds < 0 else 'behind'} UTC"


def offset_decision_pointer(row, dest, cells):
    """Where the clock offset applied to a photo was decided: its exact (camera group, destination[,
    day]) cell in photos-21, or — when the drift check's validated offset replaced it — the matching
    confirmation in photos-22 (BLD-log_format)."""
    bucket = offset_cell_key(cells, row.get("camera_group"), row.get("source_naive_time"), row.get("relative_path"))
    if row.get("resolved_utc_provenance") == "gps_drift_validated":
        return f"photos-22 destinations.{dest}.drift_decisions.{bucket}"
    return f"photos-21 destinations.{dest}.camera_group_time_decisions.{bucket}"


def manual_gps_pointer(category, dest, rel, fallback_cell):
    """Where a manual position was decided: the photo's own pin among photos-23's review items, or the
    destination's folder fallback (with the destination it is inherited from, when inherited — BLD-log_format)."""
    if category == "manual_locked":
        return f"photos-23 destinations.{dest}.gps_decisions.review_items[{os.path.basename(rel)}]"
    p = f"photos-23 destinations.{dest}.folder_fallback"
    if (fallback_cell or {}).get("fallback_source") == "inherited":
        p += f" (inherited from {fallback_cell.get('inherited_from')})"
    return p


_DECISION_RECORD_DEP = {"photos-21": "time_decisions", "photos-22": "drift_validation", "photos-23": "gps_decisions"}
DECISION_RECORD_DEPS = tuple(_DECISION_RECORD_DEP.values())


def _with_record_hashes(steps, plan):
    """Each step naming a decision also names the exact version of the decision record its pass
    followed: the copy execution kept of it (`executed/<plan id>/`) and its hash, the one the pass's
    plan depended on — so the why stays findable after the live record is edited (BLD-history_kept)."""
    deps = plan.get("depends_on") or {}
    for s in steps:
        dep = deps.get(_DECISION_RECORD_DEP.get((s.get("because") or "")[:9]) or "") or {}
        if dep.get("sha256"):
            s["because_record_sha256"] = dep["sha256"]
            if dep.get("artifact_name") and plan.get("plan_id"):
                s["because_record"] = f"{CONTROL_DIR}/executed/{plan['plan_id']}/{dep['artifact_name']}"
    return steps


def held_time_pre_state(file, writes):
    """What `file` holds now in each field of a time write, `writes` — its time, the offset beside it and every
    other time field the write replaces — in the shape the log records beside it (BLD-geotag_log_steps)."""
    h = held_values(file)
    return {k: h.get(k) for k in writes}


def _time_written_step(time_op):
    """The log's step for a time geotag wrote: what was written, what it replaced, the field the photo's
    time was read from and the rule that turned it to UTC — a time taken from the photo's own offset and
    one assumed from the destination's zone are told apart here, and nowhere else in the record."""
    prov = time_op.get("provenance") or {}
    step = {"phase": "geotag", "action": "time_written", "writes": time_op.get("writes")}
    for k, v in (("pre_state", time_op.get("pre_state")), ("read_from", prov.get("source_time_provenance")),
                 ("rule", prov.get("time_rule_used"))):
        if v is not None:
            step[k] = v
    return step


def _true_time_steps(plan):
    """{fingerprint: step} of the times the user kept as their photos' true times in `plan` (BLD-geotag_log_steps), each
    naming the photos-21 entry that kept it (BLD-log_format)."""
    out = {}
    for rel, kept in sorted((plan.get("true_times_kept") or {}).items()):
        if isinstance(kept, dict) and kept.get("content_fingerprint"):
            out[kept["content_fingerprint"]] = {
                "phase": "geotag", "action": "true_time_kept", "value": kept.get("DateTimeOriginal"),
                "because": f"photos-21 destinations.{os.path.dirname(rel)}.changed_times[{rel}]"}
    return out


def _date_fallback_steps(time_op):
    """The log's step for a time a date fallback gave a photo with none of its own (BLD-geotag_log_steps): the fallback
    as the user gave it (`value`, such as "1985-06"), the day it was filled to, and the photos-21 cell it was given in —
    from the provenance of the plan's time write. [] for any other time."""
    df = ((time_op or {}).get("provenance") or {}).get("date_fallback")
    if not isinstance(df, dict):
        return []
    return [{"phase": "geotag", "action": "date_fallback_applied", "value": df.get("date"), "filled": df.get("filled"),
             "because": time_op["provenance"].get("because")}]


def _earlier_pass_steps(plan, confirmed):
    """{fingerprint: [steps]} for one earlier executed pass: what its confirmed operations did to each
    photo, matched by the fingerprint the operation was planned against, and the true times it kept, each step
    naming the run."""
    run = plan.get("plan_id")
    ops_by_fp = {}
    for dd in (plan.get("destinations") or {}).values():
        for op in dd.get("operations") or []:
            fp = (op.get("preconditions") or {}).get("content_fingerprint")
            if fp and op.get("operation_id") in confirmed:
                ops_by_fp.setdefault(fp, []).append(op)
    kept = _true_time_steps(plan)
    out = {}
    for fp in sorted(set(ops_by_fp) | set(kept)):
        ops = ops_by_fp.get(fp) or []
        steps = [dict(kept[fp])] if fp in kept else []
        time_op = next((o for o in ops if o["type"] == "metadata_time_write"), None)
        if time_op is not None:
            prov = time_op.get("provenance") or {}
            if prov.get("time_rule_used") == "camera_group_offset" and prov.get("utc_offset_used") is not None:
                steps.append({"phase": "geotag", "action": "clock_offset_applied", "offset_seconds": prov["utc_offset_used"],
                              "offset_description": describe_offset(prov["utc_offset_used"]),
                              "because": prov.get("because")})
            steps += _date_fallback_steps(time_op)
            if prov.get("resolved_utc"):
                steps.append({"phase": "geotag", "action": "resolved_utc", "value": prov["resolved_utc"]})
            if prov.get("destination_timezone"):
                steps.append({"phase": "geotag", "action": "timezone_resolved", "value": prov["destination_timezone"],
                              **({"because": prov["timezone_because"]} if prov.get("timezone_because") else {})})
            steps.append(_time_written_step(time_op))
        steps += _gps_and_rename_steps(ops, native=False)
        out[fp] = _with_record_hashes([dict(s, run=run) for s in steps], plan)
    return out


def _gps_and_rename_steps(ops, native):
    """The GPS and rename steps of one photo's operations in one pass."""
    steps = []
    gps_op = next((o for o in ops if o["type"] == "metadata_gps_write"), None)
    marker = next((o for o in ops if o["type"] == "gps_marker_write"), None)
    if gps_op is not None:
        w = gps_op.get("writes") or {}
        step = {"phase": "geotag", "action": "gps_written", "lat": w.get("GPSLatitude"),
                "lon": w.get("GPSLongitude"), "origin": gps_op.get("gps_origin"),
                "gps_processing_method": (marker.get("writes") or {}).get("GPSProcessingMethod") if marker else None}
        if gps_op.get("pre_state") is not None:     # a manual position's, or one written over no fix
            step["pre_state"] = gps_op["pre_state"]
        if (gps_op.get("provenance") or {}).get("because"):
            step["because"] = gps_op["provenance"]["because"]
        if (gps_op.get("provenance") or {}).get("gpx_file"):         # the track that placed it, and when
            step["gpx_file"] = gps_op["provenance"]["gpx_file"]
            step["at_utc"] = gps_op["provenance"].get("resolved_utc")
        steps.append(step)
    elif marker is not None and (marker.get("writes") or {}).get("GPSLatitude") == "":
        # geotag's old position cleared: the decision now places none
        steps.append({"phase": "geotag", "action": "gps_cleared", "pre_state": marker.get("pre_state"),
                      "gps_processing_method": marker["writes"].get("GPSProcessingMethod")})
    elif native:
        steps.append({"phase": "geotag", "action": "gps_preserved"})
    rename_op = next((o for o in ops if o["type"] == "rename_no_clobber"), None)
    if rename_op is not None:
        steps.append({"phase": "geotag", "action": "final_rename", "from": rename_op.get("from"), "to": rename_op["to"]})
    return steps


def build_complete_log(prep_photos, files, resolved_rows, time_artifact, plan, earlier_passes=()):
    """photos-26-complete-log.json's `photos` (BLD-phase_logs): a deep copy of prep's per-photo, content-
    fingerprint-keyed journeys with each calibrated photo's `phase:"geotag"` steps APPENDED — a
    strict superset of the prep log, derived from photos-21 / the resolved-UTC cache / photos-24.
    `earlier_passes` — [(plan, confirmed operation ids)], oldest first — are the geotag
    passes executed before the current plan's: their steps come first, so a photo written in an
    earlier pass keeps the record of it however later passes went. Deterministic, fingerprint-keyed.
    The prep file itself is never edited."""
    photos = json.loads(json.dumps(prep_photos or {}))            # deep copy; never touch the prep file
    row_by_rel = {r["relative_path"]: r for r in resolved_rows}
    for dd in (plan.get("destinations") or {}).values():
        for op in dd.get("operations") or []:
            # The rows are keyed by each photo's path when the plan was made; a prep run since records the
            # photo under the name the plan gave it. Either way it is the same photo's row.
            if op.get("type") == "rename_no_clobber" and op["relative_path"] in row_by_rel:
                row_by_rel.setdefault(os.path.join(os.path.dirname(op["relative_path"]), op["to"]),
                                      row_by_rel[op["relative_path"]])
    t_dests = (time_artifact or {}).get("destinations") or {}
    ops_by_fp = {}
    fp_by_rel = {f["relative_path"]: f.get("content_fingerprint") for f in files}
    for dd in (plan.get("destinations") or {}).values():
        for op in dd.get("operations") or []:
            fp = (op.get("preconditions") or {}).get("content_fingerprint") or fp_by_rel.get(op["relative_path"])
            ops_by_fp.setdefault(fp, []).append(op)
    earlier = [_earlier_pass_steps(p, confirmed) for p, confirmed in earlier_passes]
    kept = _true_time_steps(plan)
    run = plan.get("plan_id")

    for f in sorted(files, key=lambda x: x["relative_path"]):
        fp = f.get("content_fingerprint")
        if not fp:
            continue
        rel, dest, group = f["relative_path"], f["destination"], f["camera_group_key"]
        entry = photos.setdefault(fp, {"content_fingerprint": fp, "journey": []})
        steps = entry.setdefault("journey", [])
        for past in earlier:
            steps.extend(past.get(fp) or [])
        row = row_by_rel.get(rel) or {}
        ops = ops_by_fp.get(fp) or []
        start = len(steps)

        if fp in kept:                          # the user's own answer: this is the photo's true time
            steps.append(dict(kept[fp]))
        if row.get("time_rule_used") == "camera_group_offset" and row.get("utc_offset_used") is not None:
            cells = (t_dests.get(dest) or {}).get("camera_group_time_decisions") or {}
            steps.append({"phase": "geotag", "action": "clock_offset_applied",
                          "offset_seconds": row["utc_offset_used"],
                          "offset_description": describe_offset(row["utc_offset_used"]),
                          "because": offset_decision_pointer(dict(row, camera_group=row.get("camera_group") or group),
                                                             dest, cells)})
        time_op = next((o for o in ops if o["type"] == "metadata_time_write"), None)
        steps += _date_fallback_steps(time_op)
        if row.get("resolved_utc"):
            steps.append({"phase": "geotag", "action": "resolved_utc", "value": row["resolved_utc"]})
        tz = ((t_dests.get(dest, {}).get("destination_timezone")) or {}).get("effective_iana_timezone")
        if tz:
            steps.append({"phase": "geotag", "action": "timezone_resolved", "value": tz,
                          "because": f"photos-21 destinations.{dest}.destination_timezone"})

        if time_op is not None:
            steps.append(_time_written_step(time_op))
        steps.extend(_gps_and_rename_steps(ops, native=f.get("has_native_gps")))
        if not f.get("from_originals") and geotag_marker(held_values(f).get("method")):
            # geotag's mark is on the photo, but this workspace never held its own values: its time was
            # fixed elsewhere, or that history is lost — say so rather than look whole (BLD-partial_log_marked). The
            # note is a step of geotag's own: prep's fields, a note among them, are carried unchanged.
            entry["partial"] = True
            steps.append({"phase": "geotag", "action": "history_incomplete",
                          "note": "geotag's mark is on this photo but no pass in this workspace's record "
                                  "first corrected it: its correction was made elsewhere, or that history "
                                  "is lost"})
        if run:
            steps[start:] = [dict(s, run=run) for s in steps[start:]]
        _with_record_hashes(steps[start:], plan)
        # where geotag left the photo: its by-dest folder, under the name its last final rename gave it
        renamed = [s["to"] for s in steps if s.get("phase") == "geotag" and s.get("action") == "final_rename"
                   and s.get("to")]
        entry["geotag_path"] = os.path.join(os.path.dirname(rel), renamed[-1]) if renamed else rel

    # A JPEG set aside beside its RAW and renamed with it: its renames, this pass's and the earlier ones', in its own
    # record (BLD-set_aside_renamed_with_raw).
    in_model = {f.get("content_fingerprint") for f in files}
    aside = {}
    for p in [p for p, _confirmed in earlier_passes] + [plan]:
        for dd in (p.get("destinations") or {}).values():
            for op in dd.get("operations") or []:
                fp = (op.get("preconditions") or {}).get("content_fingerprint")
                if op.get("with_raw") and fp and fp not in in_model:
                    aside[fp] = op["relative_path"]
    for fp, rel in sorted(aside.items()):
        entry = photos.setdefault(fp, {"content_fingerprint": fp, "journey": []})
        steps = entry.setdefault("journey", [])
        for past in earlier:
            steps.extend(past.get(fp) or [])
        start = len(steps)
        steps.extend(_gps_and_rename_steps(ops_by_fp.get(fp) or [], native=False))
        if run:
            steps[start:] = [dict(s, run=run) for s in steps[start:]]
        renamed = [s["to"] for s in steps if s.get("phase") == "geotag" and s.get("action") == "final_rename"]
        if renamed:
            entry["geotag_path"] = os.path.join(os.path.dirname(rel), renamed[-1])
    return photos


def geotag_execution_status(newly, skipped_n, failures, mismatches, blockers):
    """Terminal status of a geotag execution (BLD-execution_summary): `success` (no failures, mismatches, or
    blockers); `failed` (degraded by failures/blockers with nothing applied this run, nothing
    already-satisfied, and no held-back mismatch — i.e. nothing was achieved); otherwise `partial`.
    A non-empty mismatch list always forces `partial` (a write occurred but is held back,
    RUL-content_changed_write_held), never `failed`. Pre-mutation aborts are `rejected`, decided elsewhere."""
    if not (failures or mismatches or blockers):
        return "success"
    if mismatches or newly > 0 or skipped_n > 0:
        return "partial"
    return "failed"


_WRITE_OP_TYPES = ("metadata_time_write", "metadata_gps_write", "gps_marker_write")


def repeated_write_failures(failures, prior_failures):
    """The photos whose metadata write failed in this execution as in the previous execution of the same plan — the
    same operation kinds, the same reason (BLD-repeated_write_failure) — each with the way out: running again will not
    mend it, so the photo goes back into photos by date, a move the workspace check passes (`moved_back`,
    BLD-workspace_check), and prep and geotag are planned again without it."""
    def by_photo(fs):
        out = {}
        for f in fs:
            if f.get("type") in _WRITE_OP_TYPES and f.get("error"):
                out.setdefault(f.get("relative_path"), set()).add((f["type"], f["error"]))
        return out
    now, before = by_photo(failures), by_photo(prior_failures)
    way_out = (f"move it from {folder_name('photos_by_dest')} into {folder_name('photos_by_date')}, then run "
               "`prep plan`, `prep execute` and `geotag plan` again")
    return [{"relative_path": rel, "types": sorted(t for t, _ in kinds), "error": sorted(e for _, e in kinds)[0],
             "way_out": way_out}
            for rel, kinds in sorted(now.items()) if before.get(rel) == kinds]


