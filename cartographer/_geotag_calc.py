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
import concurrent.futures
import hashlib
import json
import math
import os
import sqlite3
import subprocess
import sys
import xml.etree.ElementTree as ET
import zoneinfo
from datetime import datetime, timedelta, timezone

from .photos_utils import (
    CONFIG, CONTROL_DIR, config_path, handoff_path, guard_path, is_sealed,
    validate_config, sha256_file, sha256_text, media_class_for_ext, folder_name,
    folders_fingerprint, media_extensions_fingerprint,
    selected_gpx_root, is_gpx_file, CAMERA_IDENTITY_FIELDS, FIELD_SET_VERSION, CAMERA_GROUP_KEY_VERSION, FOLDER_ROLES,
    missing_managed_folders, by_dest_reprep_pending,
    json_dependency, verify_json_dependency, handoff_content_fingerprint, write_json_artifact, write_versioned_json, db_path, ensure_control_dir,
    journal_path, ContentHasher, _move_no_clobber, allocate_suffix, carries_stem, track_memo_db_path,
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
    'POSITION_MARKERS',
    'TIME_FIXED_SUFFIX',
    'geotag_marker',
    'with_time_fixed',
    'time_fixed_marker_op',
    'haversine',
    'GPXPoint',
    'GPXIndex',
    '_valid_iana',
    '_valid_offset',
    '_parse_camera_naive',
    '_naive_date',
    '_parse_utc',
    '_equirect_xy',
    '_point_to_segment',
    '_candidate',
    'match_frame_to_gpx',
    '_frame_skip_reason',
    '_timezone_naive_offset',
    'infer_anchor_proposal',
    '_parse_iso_offset',
    '_local_to_utc',
    'drift_offset_overrides',
    'compute_resolved_utc',
    'resolved_utc_fingerprint',
    '_interp',
    '_extrapolate',
    'place_gps',
    '_valid_coord',
    '_GPS_PLACE_CATEGORY',
    'classify_gps',
    'held_pre_state',
    '_coordinate_tags',
    '_CLEARED_POSITION',
    '_walk_ancestors',
    '_nearest_ancestor',
    '_expand_destinations',
    '_dest_label',
    'destination_local_basename',
    'plan_renames',
    '_GPS_OP_ORIGIN',
    '_GPS_OP_MARKER',
    '_local_time_and_offset',
    '_make_op',
    'plan_file_ops',
    'build_complete_log',
    'geotag_execution_status',
]

def haversine(lat1, lon1, lat2, lon2):
    """Great-circle distance between two lat/lon points, in metres."""
    R = 6371000.0
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlmb = math.radians(lon2 - lon1)
    a = math.sin(dphi / 2.0) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(dlmb / 2.0) ** 2
    return R * (2.0 * math.atan2(math.sqrt(a), math.sqrt(1 - a)))


class GPXPoint:
    __slots__ = ("lat", "lon", "time_utc", "source_file", "point_index")

    def __init__(self, lat, lon, time_utc, source_file, point_index):
        self.lat = lat
        self.lon = lon
        self.time_utc = time_utc          # timezone-aware UTC datetime
        self.source_file = source_file
        self.point_index = point_index


_REL = "\x00rel\x00"            # stands for the file's path in a memoized warning: the memo is keyed by bytes
GPX_PARSE_VERSION = "gpx-parse-v1"   # bump when the parse below changes what it yields


class GPXIndex:
    """Deterministically ordered, fingerprinted index of all GPX track points under gpx_root.

    Availability is recorded in `status` (disabled / missing / empty / usable). The `fingerprint`
    is a SHA-256 over the root, each file's bytes, and each parsed point — it becomes an upstream
    dependency of the time/GPS artifacts in later phases (§4–§6).

    Every file is read whole on every build — its bytes are what the fingerprint checks — but with a
    `memo_path` a file whose bytes were parsed before is not parsed again: its points come from the
    track memo (shared §10), which yields exactly what parsing would."""

    def __init__(self, gpx_root, memo_path=None):
        self.gpx_root = gpx_root
        self.memo_path = memo_path
        self.points = []
        self.fingerprint = None
        self.status = "disabled"
        self.warnings = []
        self.parsed = self.reused = 0      # files parsed this build / taken from the memo

    def build(self, coordinator=None):
        if not self.gpx_root:
            self.status = "disabled"
            self.fingerprint = hashlib.sha256(b"gpx-disabled-v1").hexdigest()
            return self
        if not os.path.isdir(self.gpx_root):
            self.status = "missing"
            self.warnings.append(f"Configured gpx_root does not exist or is not a directory: {self.gpx_root}")
            self.fingerprint = hashlib.sha256(("gpx-missing|" + self.gpx_root).encode()).hexdigest()
            return self

        gpx_files = sorted(
            (os.path.relpath(os.path.join(r, f), self.gpx_root), os.path.join(r, f))
            for r, _d, files in os.walk(self.gpx_root) for f in files
            if is_gpx_file(f))

        memo = self._open_memo()
        seen = set()
        if coordinator:                       # per-file progress (count + %), named by GPX file
            coordinator.start_phase("loading GPX tracks", len(gpx_files))
        h = hashlib.sha256()
        h.update(self.gpx_root.encode("utf-8"))
        h.update(b"gpx-index-v1")
        for rel, abs_path in gpx_files:
            if coordinator:
                coordinator.set_detail(rel)
            h.update(rel.encode("utf-8"))
            try:
                with open(abs_path, "rb") as f:
                    data = f.read()
            except OSError as e:
                self.warnings.append(f"Could not read GPX file {rel}: {e}")
                data = None
            if data is not None:
                digest = hashlib.sha256(data).digest()
                h.update(digest)
                seen.add(digest.hex())
                parsed = self._memo_get(memo, digest.hex())
                if parsed is None:
                    parsed = self._parse_bytes(data)
                    self._memo_put(memo, digest.hex(), parsed)
                    self.parsed += 1
                else:
                    self.reused += 1
                points, warnings = parsed
                self.points.extend(GPXPoint(lat, lon, datetime.fromisoformat(t), rel, idx)
                                   for lat, lon, t, idx in points)
                self.warnings.extend(w.replace(_REL, rel) for w in warnings)
            if coordinator:
                coordinator.increment_completed(1)
        if coordinator:
            coordinator.finish_phase()
        self._close_memo(memo, seen)

        self.points.sort(key=lambda p: (p.time_utc, p.source_file, p.point_index))
        for p in self.points:
            h.update(p.time_utc.isoformat().encode("utf-8"))
            h.update(f"{p.lat}|{p.lon}|{p.source_file}|{p.point_index}".encode("utf-8"))
        self.fingerprint = h.hexdigest()
        self.status = "usable" if self.points else "empty"
        return self

    # --- the track memo: scratch, so any failure only means parsing again -----------------

    def _open_memo(self):
        if not self.memo_path:
            return None
        for attempt in (1, 2):                 # a memo that is not a database is replaced: it is scratch
            conn = None
            try:
                conn = sqlite3.connect(self.memo_path)
                conn.execute("CREATE TABLE IF NOT EXISTS track_memo (sha256 TEXT PRIMARY KEY, "
                             "parse_version TEXT, parsed_json TEXT)")
                return conn
            except sqlite3.Error:
                if conn is not None:
                    conn.close()
                if attempt == 2:
                    return None
                try:
                    os.remove(self.memo_path)
                except OSError:
                    return None
        return None

    @staticmethod
    def _memo_get(conn, sha):
        if conn is None:
            return None
        try:
            row = conn.execute("SELECT parsed_json FROM track_memo WHERE sha256 = ? AND parse_version = ?",
                               (sha, GPX_PARSE_VERSION)).fetchone()
            return tuple(json.loads(row[0])) if row else None
        except (sqlite3.Error, ValueError):
            return None

    @staticmethod
    def _memo_put(conn, sha, parsed):
        if conn is None:
            return
        try:
            with conn:
                conn.execute("INSERT OR REPLACE INTO track_memo VALUES (?, ?, ?)",
                             (sha, GPX_PARSE_VERSION, json.dumps(parsed)))
        except sqlite3.Error:
            pass

    @staticmethod
    def _close_memo(conn, seen):
        """Drop the entries of tracks no longer under gpx_root, so the memo follows the tracks."""
        if conn is None:
            return
        try:
            with conn:
                for (sha,) in conn.execute("SELECT sha256 FROM track_memo").fetchall():
                    if sha not in seen:
                        conn.execute("DELETE FROM track_memo WHERE sha256 = ?", (sha,))
        except sqlite3.Error:
            pass
        finally:
            conn.close()

    @staticmethod
    def _parse_bytes(data):
        """A track file's points as [lat, lon, UTC time (ISO), index] and its warnings, the file's path
        written as _REL — what the memo keeps for the file's bytes, wherever the file lies."""
        points, warnings = [], []
        try:
            root = ET.fromstring(data)
        except ET.ParseError as e:
            return points, [f"Malformed GPX XML in {_REL}: {e}"]
        idx = 0
        for elem in root.iter():
            if not elem.tag.endswith("trkpt"):
                continue
            lat_s, lon_s = elem.attrib.get("lat"), elem.attrib.get("lon")
            time_elem = next((c for c in elem if c.tag.endswith("time")), None)
            if not lat_s or not lon_s or time_elem is None or not time_elem.text:
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
                points.append([lat, lon, dt.astimezone(timezone.utc).isoformat(), idx])
            except ValueError as e:
                warnings.append(f"Bad trkpt in {_REL} at index {idx}: {e}")
            idx += 1
        return points, warnings


def _valid_iana(tz):
    """True iff `tz` resolves to a real IANA timezone (geotag §9.2)."""
    try:
        zoneinfo.ZoneInfo(tz)
        return True
    except (zoneinfo.ZoneInfoNotFoundError, ValueError, TypeError):
        return False


def _valid_offset(v):
    """True iff `v` is a finite number of seconds within +/- one day (geotag §9.2)."""
    return isinstance(v, (int, float)) and not isinstance(v, bool) and abs(v) <= 86400


# ============================================================================
# Stage 5 — GPX/native-GPS time-anchor inference (geotag §19). Pure helpers
# (plain inputs, no I/O) so the geometry/ranking is exhaustively unit-testable.
# ============================================================================

def _parse_camera_naive(s):
    """The camera's naive capture time ('YYYY:MM:DD HH:MM:SS') as a naive datetime, or None."""
    try:
        return datetime.strptime((s or "")[:19], "%Y:%m:%d %H:%M:%S")
    except (ValueError, TypeError):
        return None


def _naive_date(s):
    """The camera naive timestamp's calendar date as 'YYYY-MM-DD', or None — the per-day offset bucket
    key within a destination (§10.2: a clock set to local time each morning is constant only per day)."""
    dt = _parse_camera_naive(s)
    return dt.strftime("%Y-%m-%d") if dt else None


def _parse_utc(s):
    """An ISO-8601 UTC datetime (trailing Z accepted) as an aware datetime, or None."""
    try:
        return datetime.fromisoformat((s or "").replace("Z", "+00:00"))
    except (ValueError, AttributeError):
        return None


def _equirect_xy(lat, lon, lat0, lon0):
    """Local equirectangular projection of (lat,lon) to metres about (lat0,lon0)."""
    R = 6371000.0
    x = math.radians(lon - lon0) * math.cos(math.radians(lat0)) * R
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


def _candidate(match_type, gpx_time, distance, src, naive, dur):
    offset = round((gpx_time.replace(tzinfo=None) - naive).total_seconds())
    return {"match_type": match_type, "gpx_time": gpx_time, "distance_m": round(distance, 2),
            "gpx_file": src, "offset_seconds": int(offset),
            "segment_duration_seconds": (round(dur) if dur is not None else None)}


def match_frame_to_gpx(frame, gpx, cfg):
    """Best GPX time-anchor candidate for one native-GPS frame (§19.1), or None. Prefers a close
    GPX point; else the closest valid short segment (time interpolated by position projection)."""
    ng = frame.get("native_gps") or {}
    naive = _parse_camera_naive(frame.get("source_naive_time"))
    if ng.get("lat") is None or ng.get("lon") is None or naive is None or not gpx.points:
        return None
    flat, flon = float(ng["lat"]), float(ng["lon"])
    pt_max = cfg["gpx_anchor_max_point_distance_meters"]
    seg_max = cfg["gpx_anchor_max_segment_distance_meters"]
    gap_max = cfg["gpx_interpolation_max_gap_seconds"]
    # Plausible-clock-error window: a GPX time may anchor this frame only if it is within `window` of the
    # frame's naive time (read as UTC). Applied DURING the spatial search so a same-place/other-trip point
    # is skipped even when it is the spatially closest — fixing the years-off false match. None = no bound
    # (unit tests that omit the knob); real configs always set it (§19.1).
    window = cfg.get("gpx_anchor_max_clock_error_seconds")
    in_window = lambda gt: window is None or abs((gt.replace(tzinfo=None) - naive).total_seconds()) <= window

    best_pt = None
    for p in gpx.points:
        if not in_window(p.time_utc):
            continue
        d = haversine(flat, flon, p.lat, p.lon)
        if d <= pt_max and (best_pt is None or d < best_pt[0]):
            best_pt = (d, p)
    if best_pt is not None:
        d, p = best_pt
        return _candidate("gpx_point_match", p.time_utc, d, p.source_file, naive, None)

    best_seg = None
    pts = gpx.points
    for i in range(len(pts) - 1):
        a, b = pts[i], pts[i + 1]
        dur = (b.time_utc - a.time_utc).total_seconds()
        if dur <= 0 or dur > gap_max:
            continue
        dist, t = _point_to_segment(flat, flon, a.lat, a.lon, b.lat, b.lon)
        seg_time = a.time_utc + timedelta(seconds=t * dur)
        if dist <= seg_max and in_window(seg_time) and (best_seg is None or dist < best_seg[0]):
            best_seg = (dist, seg_time, a.source_file, dur)
    if best_seg is not None:
        dist, seg_time, src, dur = best_seg
        return _candidate("gpx_segment_interpolation", seg_time, dist, src, naive, dur)
    return None


def _frame_skip_reason(frame, gpx, cfg):
    """Why `match_frame_to_gpx` returned no anchor for `frame`: 'outside_time_window' if a GPX point is
    spatially close but only at an implausible time (a different trip/year), else 'no_nearby_track'.
    Drives the editor's skipped-frames note (§19.3) so a windowed-out match is explained, not hidden."""
    ng = frame.get("native_gps") or {}
    naive = _parse_camera_naive(frame.get("source_naive_time"))
    if ng.get("lat") is None or ng.get("lon") is None or naive is None or not gpx.points:
        return "no_nearby_track"
    flat, flon, pt_max = float(ng["lat"]), float(ng["lon"]), cfg["gpx_anchor_max_point_distance_meters"]
    if any(haversine(flat, flon, p.lat, p.lon) <= pt_max for p in gpx.points):
        return "outside_time_window"
    return "no_nearby_track"


def _timezone_naive_offset(naive_str, tz):
    """Timezone-derived clock-offset (§19.4): when a (camera group, destination) has no GPX anchor and no
    ancestor to inherit from, assume the camera clock was set to the destination's civil timezone, so the
    offset is -(that timezone's UTC offset at this naive instant) — DST-aware via zoneinfo. Returns
    (offset_seconds, real_utc_iso), or None if `tz`/`naive_str` is missing or unresolvable. A confirmable
    proposal only (the local-clock assumption can be wrong, e.g. a camera left on home time)."""
    dt = _parse_camera_naive(naive_str)
    if dt is None or not tz:
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
    recommended clock-offset proposal (§19.2/§19.3), or None if nothing anchors. The frames' offsets
    are clustered (a camera's clock error is ~constant across a destination), and the CONSENSUS — the
    largest agreeing cluster — wins (point-before-segment then closest as the within-cluster tiebreak),
    so a lone spurious match can't outvote the crowd. Frames with no in-window match are summarized as
    `skipped`; the clusters are summarized as `groups` for a collapsed editor view."""
    cands, skipped = [], {"no_nearby_track": 0, "outside_time_window": 0, "examples": []}
    for f in frames:
        c = match_frame_to_gpx(f, gpx, cfg)
        if c:
            cands.append(dict(c, source_file=f.get("relative_path"), native_gps=f.get("native_gps"),
                              camera_source_naive_time=f.get("source_naive_time")))
        else:
            reason = _frame_skip_reason(f, gpx, cfg)
            skipped[reason] += 1
            if len(skipped["examples"]) < 3:
                skipped["examples"].append({"source_file": f.get("relative_path"), "reason": reason})
    if not cands:
        return None
    # rank: point-before-segment, then closest, then path (deterministic); first in a cluster is its rep
    cands.sort(key=lambda c: (0 if c["match_type"] == "gpx_point_match" else 1,
                              c["distance_m"], c["source_file"] or ""))
    spread = cfg["gpx_anchor_offset_spread_max_seconds"]
    clusters = []                                   # each: {"offset", "rep", "members": [...]}
    for c in cands:                                 # rank order → each cluster's rep is its best match
        g = next((g for g in clusters if abs(c["offset_seconds"] - g["offset"]) <= spread), None)
        if g is None:
            clusters.append({"offset": c["offset_seconds"], "rep": c, "members": [c]})
        else:
            g["members"].append(c)
    # consensus: largest cluster wins; ties → the earliest (its rep ranks best, since cands are sorted)
    chosen = max(range(len(clusters)), key=lambda i: (len(clusters[i]["members"]), -i))
    g = clusters[chosen]
    best, members = g["rep"], g["members"]
    supporting_count = len(members) - 1
    conflicting_count = len(cands) - len(members)
    if conflicting_count:
        confidence = "review_required"
    elif supporting_count or best["match_type"] == "gpx_point_match":
        confidence = "high"
    else:
        confidence = "medium"
    ordered = [best] + [c for c in cands if c is not best]    # anchors[0] is the chosen representative
    anchors = [{"proposal_id": f"anchor-{i + 1:03d}", "source_file": c["source_file"],
                "camera_source_naive_time": c["camera_source_naive_time"], "native_gps": c["native_gps"],
                "gpx_match": {"match_type": c["match_type"], "gpx_file": c["gpx_file"],
                              "distance_m": c["distance_m"],
                              "segment_duration_seconds": c["segment_duration_seconds"]},
                "proposed_offset_seconds": c["offset_seconds"]} for i, c in enumerate(ordered)]
    groups = sorted(({"offset_seconds": gg["offset"], "count": len(gg["members"]),
                      "representative": {"source_file": gg["rep"]["source_file"],
                                         "camera_source_naive_time": gg["rep"]["camera_source_naive_time"],
                                         "real_utc": gg["rep"]["gpx_time"].strftime("%Y-%m-%dT%H:%M:%SZ"),
                                         "match_type": gg["rep"]["match_type"],
                                         "distance_m": gg["rep"]["distance_m"]}}
                     for gg in clusters), key=lambda x: (-x["count"], x["offset_seconds"]))
    return {
        "proposal_source": "gpx_self_anchor",
        "proposed_offset_seconds": best["offset_seconds"],
        "proposed_real_utc": best["gpx_time"].strftime("%Y-%m-%dT%H:%M:%SZ"),
        "confidence": confidence,
        "rank": "recommended",
        "recommended_gpx_match": {"match_type": best["match_type"], "gpx_file": best["gpx_file"],
                                  "distance_m": best["distance_m"],
                                  "segment_duration_seconds": best["segment_duration_seconds"]},
        "anchor_count": len(cands), "supporting_count": supporting_count,
        "conflicting_count": conflicting_count, "anchors": anchors,
        "groups": groups, "skipped": skipped,
    }


# ============================================================================
# Stage 7 — resolved UTC per file (geotag §22). Pure computation + the
# geotag-owned SQLite cache and its deterministic fingerprint (§22.1).
# ============================================================================

def _parse_iso_offset(s):
    """A UTC offset like '+02:00' / '-05:30' as seconds, or None if malformed."""
    if not isinstance(s, str) or len(s) < 6 or s[0] not in "+-":
        return None
    try:
        hh, mm = s[1:].split(":")[:2]
        secs = int(hh) * 3600 + int(mm) * 60
    except (ValueError, IndexError):
        return None
    return -secs if s[0] == "-" else secs


def _local_to_utc(naive, tz):
    """Interpret a naive local datetime as wall time in IANA `tz` -> aware UTC (DST-correct)."""
    return naive.replace(tzinfo=zoneinfo.ZoneInfo(tz)).astimezone(timezone.utc)


def drift_offset_overrides(drift_artifact):
    """Map a COMPLETE photos-22 to `{(destination, bucket_key): validated_offset_seconds}` for every
    confirmed bucket, so compute_resolved_utc can re-resolve those photos under the operator-validated
    offset (§22a). The bucket_key matches the photos-21 cell key it was built from."""
    out = {}
    for dest, d in ((drift_artifact or {}).get("destinations") or {}).items():
        for bucket, cell in (d.get("drift_decisions") or {}).items():
            eff = cell.get("effective_drift_offset")
            if isinstance(eff, dict) and "offset_seconds" in eff:
                out[(dest, bucket)] = eff["offset_seconds"]
    return out


def compute_resolved_utc(files, groups, artifact, offset_overrides=None):
    """Resolve every by-dest photo to real UTC from the completed time decisions (§22). Camera
    groups use their (group, destination) effective offset (absolute camera->UTC correction);
    smartphones use their own EXIF offset, else the destination timezone. `offset_overrides`
    (from photos-22, §22a) replaces a bucket's offset with the operator-validated one. Returns
    per-file rows (the §22 fields), path-sorted and deterministic."""
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
        if naive is not None and f.get("geotag_marker"):
            # geotag corrected this time already: it is destination-local, offset tag beside it
            own_off = _parse_iso_offset((f.get("raw_times") or {}).get("OffsetTimeOriginal"))
            if own_off is not None:
                offset_used, resolved = own_off, naive - timedelta(seconds=own_off)
                status, rule = "valid", "geotag_corrected"
            elif tz:
                resolved = _local_to_utc(naive, tz)
                status, rule, prov = "valid", "geotag_corrected", tz
            else:
                status, rule = "unresolved", "timezone_missing"
        elif naive is not None:
            if cls == "camera":
                # per-date offset bucket: a destination split over >1 naive date keys cells
                # `group@YYYY-MM-DD`; the single-date common case keeps the bare `group` key.
                cells = d.get("camera_group_time_decisions") or {}
                date = _naive_date(f.get("source_naive_time"))
                bucket_key = f"{key}@{date}" if f"{key}@{date}" in cells else key
                cell = cells.get(bucket_key) or {}
                eff = cell.get("effective_time_anchor")
                if (dest, bucket_key) in overrides:        # §22a: operator-validated offset wins
                    offset_used = overrides[(dest, bucket_key)]
                    resolved = naive + timedelta(seconds=offset_used)
                    status, rule, prov = "valid", "camera_group_offset", "gps_drift_validated"
                elif isinstance(eff, dict) and "offset_seconds" in eff:
                    offset_used = eff["offset_seconds"]
                    resolved = naive + timedelta(seconds=offset_used)
                    status, rule, prov = "valid", "camera_group_offset", eff.get("source")
                else:
                    status, rule = "unresolved", "offset_missing"
            else:                                       # smartphone (unknown groups were hard-stopped)
                native_off = _parse_iso_offset((f.get("raw_times") or {}).get("OffsetTimeOriginal"))
                if native_off is not None:
                    offset_used, resolved = native_off, naive - timedelta(seconds=native_off)
                    status, rule = "valid", "smartphone_native_offset"
                elif tz:
                    resolved = _local_to_utc(naive, tz)
                    status, rule, prov = "valid", "destination_timezone", tz
                else:
                    status, rule = "unresolved", "timezone_missing"
        rows.append({
            "relative_path": f["relative_path"], "destination_path": dest, "destination_timezone": tz,
            "camera_group": key, "time_decision_scope": f"{key}|{dest}",
            "source_naive_time": f.get("source_naive_time"), "source_time_provenance": f.get("source_time_tag"),
            "time_rule_used": rule, "utc_offset_used": offset_used,
            "resolved_utc": (resolved.strftime("%Y-%m-%dT%H:%M:%SZ") if resolved is not None else None),
            "resolved_utc_status": status, "resolved_utc_provenance": prov,
        })
    return rows


def resolved_utc_fingerprint(rows, input_fingerprints):
    """§22.1: a SHA-256 over the path-sorted per-file resolved facts plus the input fingerprints
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
    """Linear time-fraction interpolation of (lat, lon) between GPX points `a` and `b` at `target`.
    `target` outside [a.time, b.time] extrapolates the a->b vector (ratio <0 or >1)."""
    span = (b.time_utc - a.time_utc).total_seconds()
    if span == 0:
        return a.lat, a.lon
    r = (target - a.time_utc).total_seconds() / span
    return a.lat + r * (b.lat - a.lat), a.lon + r * (b.lon - a.lon)


def _extrapolate(other, anchor, target, gpx_file):
    """Project the `other`->`anchor` velocity vector to `target` (past the track end). A missing or
    zero-span partner falls back to the anchor's own coordinates."""
    if other is None or other.time_utc == anchor.time_utc:
        lat, lon = anchor.lat, anchor.lon
    else:
        lat, lon = _interp(other, anchor, target)
    return {"lat": round(lat, 6), "lon": round(lon, 6), "method": "extrapolated", "gpx_file": gpx_file}


def place_gps(target_utc, gpx, cfg):
    """Place a photo at its resolved UTC against the GPX track (§23 options 4/5), or None when no
    reliable placement exists (option 6, blocked). Direct match -> interpolation -> velocity
    extrapolation past an end, each gated by the gpx_* config thresholds."""
    pts = gpx.points
    if not pts:
        return None
    before = after = None
    for p in pts:
        if p.time_utc <= target_utc:
            before = p
        elif after is None:
            after = p

    # 1. direct match: the nearer bracket within the direct-match window.
    best = None
    for p in (before, after):
        if p is not None:
            d = abs((p.time_utc - target_utc).total_seconds())
            if best is None or d < best[0]:
                best = (d, p)
    if best is not None and best[0] <= cfg["gpx_direct_match_max_seconds"]:
        p = best[1]
        return {"lat": p.lat, "lon": p.lon, "method": "direct_match", "gpx_file": p.source_file}

    # 2. interpolation between two brackets, gated by gap / distance / implied speed.
    if before is not None and after is not None:
        gap = (after.time_utc - before.time_utc).total_seconds()   # > 0: before <= target < after
        dist = haversine(before.lat, before.lon, after.lat, after.lon)
        speed_kmh = dist / gap * 3.6
        if (gap <= cfg["gpx_interpolation_max_gap_seconds"]
                and dist <= cfg["gpx_interpolation_max_distance_meters"]
                and speed_kmh <= cfg["gpx_interpolation_max_speed_kmh"]):
            lat, lon = _interp(before, after, target_utc)
            return {"lat": round(lat, 6), "lon": round(lon, 6), "method": "interpolated",
                    "gpx_file": before.source_file, "gpx_after_file": after.source_file}
        return None                                  # low-confidence interpolation -> blocked

    # 3. extrapolation past an end, within the extrapolation window, via the endpoint velocity.
    extrap_max = cfg["gpx_extrapolation_max_seconds"]
    if before is not None:                           # target after the last point -> project forward
        if (target_utc - before.time_utc).total_seconds() <= extrap_max:
            return _extrapolate(pts[-2] if len(pts) >= 2 else None, before, target_utc, before.source_file)
        return None
    # after is not None: target before the first point -> project backward
    if (after.time_utc - target_utc).total_seconds() <= extrap_max:
        return _extrapolate(pts[1] if len(pts) >= 2 else None, after, target_utc, after.source_file)
    return None


def _valid_coord(lat, lon):
    """True iff (lat, lon) is a numeric coordinate in range (geotag §9.2 / §25)."""
    return (isinstance(lat, (int, float)) and not isinstance(lat, bool) and -90 <= lat <= 90
            and isinstance(lon, (int, float)) and not isinstance(lon, bool) and -180 <= lon <= 180)


# place_gps method -> §25 automatic GPS category.
_GPS_PLACE_CATEGORY = {"direct_match": "gpx_interpolation", "interpolated": "gpx_interpolation",
                       "extrapolated": "gpx_extrapolation"}


def classify_gps(file, resolved_utc, gpx, cfg, effective_fallback, file_decision):
    """The §23 seven-option GPS decision for one file, as (category, coord|None). Resolves in
    priority order: preserve native -> per-file manual lock -> GPX interpolation/extrapolation at the
    resolved UTC -> the destination's effective folder fallback -> accept-unlocated -> blocked.
    Authored coordinates are assumed already range-validated by the caller (§9.2)."""
    fd = file_decision or {}
    if file.get("has_native_gps"):
        return "preserve_native", None
    mlat, mlon = fd.get("manual_lat", ""), fd.get("manual_lon", "")
    if mlat not in (None, "") and mlon not in (None, ""):
        return "manual_locked", {"lat": mlat, "lon": mlon}
    if resolved_utc is not None:
        p = place_gps(resolved_utc, gpx, cfg)
        if p is not None:
            return _GPS_PLACE_CATEGORY[p["method"]], p
    if effective_fallback is not None:
        return "manual_fallback", effective_fallback
    if fd.get("accept_unlocated"):
        return "no_change", None
    return "blocked", None


def held_pre_state(file):
    """The position `file` holds now, in the pre-state shape the log records beside a write that replaces
    or clears it (shared contract §13.3): the coordinates with their GPSProcessingMethod, or 'absent'."""
    h = held_values(file)
    if h.get("lat") is not None and h.get("lon") is not None:
        return {"present": True, "GPSLatitude": h["lat"], "GPSLongitude": h["lon"],
                "GPSProcessingMethod": h.get("method") or ""}
    return {"present": False}


def _coordinate_tags(lat, lon):
    """The complete EXIF coordinate tag set for a signed decimal position (§28.1).

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
    None. Shared by the §10.2 clock-offset and the §25 folder-fallback downward inheritance: `eff`
    maps (destination, key) -> resolved value; only already-processed, resolved ancestors qualify."""
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


def _dest_label(dest):
    """A destination's path relative to the by-dest root (the root itself shows as '(root)') — the
    progress label, so the heavy destination currently being worked on is recognizable."""
    rel = os.path.relpath(dest, folder_name('photos_by_dest'))
    return "(root)" if rel == "." else rel


# ============================================================================
# Stage 9 — no-clobber timestamp rename planning (geotag §26/§27). Pure,
# exhaustively unit-tested. Filenames are destination-LOCAL civil time, never
# raw camera time or UTC; every on-disk + planned name is permanently occupied.
# ============================================================================

def destination_local_basename(resolved_utc, tz, fmt, ext):
    """The destination-local timestamp filename '<stamp><ext>' for a file (§26), or None when it can
    not be positioned (no valid resolved UTC, or no destination timezone). The stamp is resolved UTC
    converted to the destination civil timezone and formatted with `fmt` (the shared
    filename_timestamp_format). `ext` is the file's current extension, including the leading dot."""
    dt = _parse_utc(resolved_utc)
    if dt is None or not tz:
        return None
    return _parse_utc(resolved_utc).astimezone(zoneinfo.ZoneInfo(tz)).strftime(fmt) + (ext or "")


def plan_renames(files, fmt):
    """Plan no-clobber timestamp renames for the files of ONE destination (§27). Returns
    {relative_path, current_name, planned_name, rename} per file, in relative_path order. EVERY
    file's current name is seeded as permanently occupied and never freed — a name a file will
    vacate is still treated as taken, so two files that would trade timestamps both land on distinct
    suffixed names rather than risking a clobber. A file with no positionable timestamp keeps its
    name (no rename); the unplaceable case is surfaced as a blocker by the executable-plan stage."""
    occupied = {os.path.basename(f["relative_path"]).lower() for f in files}
    out = []
    for f in sorted(files, key=lambda x: x["relative_path"]):
        rel = f["relative_path"]
        name = os.path.basename(rel)
        ext = os.path.splitext(name)[1]
        base = destination_local_basename(f.get("resolved_utc"), f.get("destination_timezone"), fmt, ext)
        # A name already carrying the timestamp keeps its suffix: renaming it to another suffix of the
        # same time would change nothing, and on the next run back again.
        if base is None or carries_stem(name, os.path.splitext(base)[0]):
            out.append({"relative_path": rel, "current_name": name, "planned_name": name, "rename": False})
            continue
        # The first free name, by the one rule prep also uses (shared §6).
        planned = allocate_suffix(os.path.splitext(base)[0], ext.lstrip("."), occupied, bare_first=True)
        out.append({"relative_path": rel, "current_name": name, "planned_name": planned, "rename": True})
    return out


# ============================================================================
# Stage 9 — executable plan operations (geotag §28). Pure op builders so
# the op list is deterministic and exhaustively unit-testable. Automatic GPS is
# RE-DERIVED here from inputs (classify_gps/place_gps), never read from the
# photos-23 summary (§25). Execution (§29, Phase 6c) only applies these ops.
# ============================================================================

_GPS_OP_ORIGIN = {"gpx_interpolation": "recompute_automated", "gpx_extrapolation": "recompute_automated",
                  "manual_locked": "apply_manual", "manual_fallback": "apply_manual"}
_GPS_OP_MARKER = {"gpx_interpolation": "interpolated", "gpx_extrapolation": "interpolated",
                  "manual_locked": "manual_locked", "manual_fallback": "manual_fallback"}
# What geotag records in GPSProcessingMethod. A bare position marker means geotag set the position
# and so fixed the time too; a re-run ignores the position and places the file again. The suffix,
# appended to whatever the field held (the device's own value, or nothing), means geotag fixed the
# time and kept the device's GPS or has set none. Anything else is the device's own: GPS native.
POSITION_MARKERS = ("interpolated", "manual_locked", "manual_fallback")
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


# What the original-values ledger pins of a file before geotag first writes to it (geotag §24.2).
ORIGINAL_KEYS = ("selected_source_naive_timestamp", "selected_source_timestamp_tag", "DateTimeOriginal",
                 "OffsetTimeOriginal", "GPSLatitude", "GPSLongitude", "GPSProcessingMethod", "has_native_gps")


def own_values(parsed):
    """A file's own time, offset tag, position and GPSProcessingMethod, from prep's parsed metadata, in
    the shape the original-values ledger pins."""
    return {k: parsed.get(k) for k in ORIGINAL_KEYS}


def from_originals(file, original):
    """`file` decided from its pinned `original` values — as the device left it, before geotag's first
    write — while `held` keeps what it holds now, for the comparison. Pure; returns a new dict."""
    f = dict(file, held=held_values(file), from_originals=True)
    rt = {k: v for k, v in (file.get("raw_times") or {}).items() if k not in ("DateTimeOriginal", "OffsetTimeOriginal")}
    for k in ("DateTimeOriginal", "OffsetTimeOriginal"):
        if original.get(k) is not None:
            rt[k] = original[k]
    method = original.get("GPSProcessingMethod")
    has_gps = bool(original.get("has_native_gps")) and geotag_marker(method) not in POSITION_MARKERS
    f.update(raw_times=rt, source_naive_time=original.get("selected_source_naive_timestamp"),
             source_time_tag=original.get("selected_source_timestamp_tag"),
             has_timestamp=original.get("selected_source_naive_timestamp") is not None,
             native_gps=({"lat": original.get("GPSLatitude"), "lon": original.get("GPSLongitude"),
                          "processing_method": method} if original.get("has_native_gps") else None),
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
            "lat": ng.get("lat"), "lon": ng.get("lon"), "method": file.get("processing_method")}


def _local_time_and_offset(resolved_utc, tz):
    """(DateTimeOriginal 'YYYY:MM:DD HH:MM:SS', OffsetTimeOriginal '+HH:MM') for a resolved UTC in the
    destination timezone, or (None, None) if unpositionable. The corrected time is destination-local
    civil time (§26)."""
    dt = _parse_utc(resolved_utc)
    if dt is None or not tz:
        return None, None
    local = dt.astimezone(zoneinfo.ZoneInfo(tz))
    z = local.strftime("%z")
    return local.strftime("%Y:%m:%d %H:%M:%S"), (z[:3] + ":" + z[3:] if z else "")


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


def plan_file_ops(file, resolved_utc, tz, gps_category, gps_coord, rename):
    """The ordered executable operations for one file (§28): corrected-time metadata write, GPS
    write + provenance marker, and no-clobber rename — each only where the file does not already
    hold it. Returns [] for a file that needs nothing (a no-op)."""
    rel = file["relative_path"]
    pre = {"content_fingerprint": file.get("content_fingerprint"),
           "size": file.get("size"), "mtime_ns": file.get("mtime_ns")}
    ops = []

    held = held_values(file)                      # what the file holds now: the comparison side
    marker = file.get("geotag_marker")            # the decision side: geotag's mark on the basis values
    time_corrected = bool(marker)                 # geotag wrote this file's time on an earlier run
    dto, off = _local_time_and_offset(resolved_utc, tz)
    if dto is not None:
        writes = {"DateTimeOriginal": dto}
        if off:
            writes["OffsetTimeOriginal"] = off
        time_corrected = True
        if any(held.get(k) != v for k, v in writes.items()):         # already held -> nothing to write
            ops.append(_make_op("metadata_time_write", rel, "corrected capture time", {"writes": writes}, pre))

    if gps_category in _GPS_OP_ORIGIN and gps_coord is not None:
        new_marker = _GPS_OP_MARKER[gps_category]
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
        ops.append(_make_op("rename_no_clobber", rel, "destination-local timestamp name",
                            {"from": rename["current_name"], "to": rename["planned_name"]}, pre))
    return ops


# ============================================================================
# Stage 11 — finalize: the photos-26 transformation log (shared contract §13.3).
# Prep's per-photo log carried forward + geotag steps appended. A derived
# consolidation of artifacts already written — no new authority.
# ============================================================================

def describe_offset(seconds):
    """A clock offset as a person reads it (§13.3 item 5). The offset is what is added to the camera's
    time to reach UTC, so a negative one means the camera's clock ran ahead of UTC."""
    if not seconds:
        return "camera clock on UTC"
    s = abs(int(seconds))
    parts = [f"{v} {u}" for v, u in ((s // 3600, "h"), (s % 3600 // 60, "min"), (s % 60, "s")) if v]
    return f"camera clock {' '.join(parts)} {'ahead of' if seconds < 0 else 'behind'} UTC"


def offset_decision_pointer(row, dest, cells):
    """Where the clock offset applied to a photo was decided: its exact (camera group, destination[,
    day]) cell in photos-21, or — when the drift check's validated offset replaced it — the matching
    confirmation in photos-22 (§13.3 item 3)."""
    group = row.get("camera_group")
    date = _naive_date(row.get("source_naive_time"))
    bucket = f"{group}@{date}" if f"{group}@{date}" in (cells or {}) else group
    if row.get("resolved_utc_provenance") == "gps_drift_validated":
        return f"photos-22 destinations.{dest}.drift_decisions.{bucket}"
    return f"photos-21 destinations.{dest}.camera_group_time_decisions.{bucket}"


def manual_gps_pointer(category, dest, rel, fallback_cell):
    """Where a manual position was decided: the photo's own pin among photos-23's review items, or the
    destination's folder fallback (with the destination it was inherited from, when accepted from one)."""
    if category == "manual_locked":
        return f"photos-23 destinations.{dest}.gps_decisions.review_items[{os.path.basename(rel)}]"
    p = f"photos-23 destinations.{dest}.folder_fallback"
    prop = (fallback_cell or {}).get("proposal") or {}
    if prop.get("proposal_source") == "inherited" and ((fallback_cell or {}).get("user_decision") or {}).get("accept_proposal"):
        p += f" (accepted from {prop.get('inherited_from')})"
    return p


_DECISION_RECORD_DEP = {"photos-21": "time_decisions", "photos-22": "drift_validation", "photos-23": "gps_decisions"}
DECISION_RECORD_DEPS = tuple(_DECISION_RECORD_DEP.values())


def _with_record_hashes(steps, plan):
    """Each step naming a decision also names the exact version of the decision record its pass
    followed: the copy execution kept of it (`executed/<plan id>/`) and its hash, the one the pass's
    plan depended on — so the why stays findable after the live record is edited (§13.3a)."""
    deps = plan.get("depends_on") or {}
    for s in steps:
        dep = deps.get(_DECISION_RECORD_DEP.get((s.get("because") or "")[:9]) or "") or {}
        if dep.get("sha256"):
            s["because_record_sha256"] = dep["sha256"]
            if dep.get("artifact_name") and plan.get("plan_id"):
                s["because_record"] = f"{CONTROL_DIR}/executed/{plan['plan_id']}/{dep['artifact_name']}"
    return steps


def _earlier_pass_steps(plan, confirmed):
    """{fingerprint: [steps]} for one earlier executed pass: what its confirmed operations did to each
    photo, matched by the fingerprint the operation was planned against, each step naming the run."""
    run = plan.get("plan_id")
    ops_by_fp = {}
    for dd in (plan.get("destinations") or {}).values():
        for op in dd.get("operations") or []:
            fp = (op.get("preconditions") or {}).get("content_fingerprint") or op.get("content_fingerprint")
            if fp and (confirmed is None or op.get("operation_id") in confirmed):
                ops_by_fp.setdefault(fp, []).append(op)
    out = {}
    for fp, ops in ops_by_fp.items():
        steps = []
        time_op = next((o for o in ops if o["type"] == "metadata_time_write"), None)
        if time_op is not None:
            prov = time_op.get("provenance") or {}
            if prov.get("time_rule_used") == "camera_group_offset" and prov.get("utc_offset_used") is not None:
                steps.append({"phase": "geotag", "action": "clock_offset_applied", "offset_seconds": prov["utc_offset_used"],
                              "offset_description": describe_offset(prov["utc_offset_used"]),
                              "because": prov.get("because")})
            if prov.get("resolved_utc"):
                steps.append({"phase": "geotag", "action": "resolved_utc", "value": prov["resolved_utc"]})
            if prov.get("destination_timezone"):
                steps.append({"phase": "geotag", "action": "timezone_resolved", "value": prov["destination_timezone"],
                              **({"because": prov["timezone_because"]} if prov.get("timezone_because") else {})})
            steps.append({"phase": "geotag", "action": "time_written", "writes": time_op.get("writes")})
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
        if gps_op.get("gps_origin") == "apply_manual" and gps_op.get("pre_state") is not None:
            step["pre_state"] = gps_op["pre_state"]
        if (gps_op.get("provenance") or {}).get("because"):
            step["because"] = gps_op["provenance"]["because"]
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
    """photos-26-complete-log.json's `photos` (§13.3): a deep copy of prep's per-photo, content-
    fingerprint-keyed journeys with each calibrated photo's `phase:"geotag"` steps APPENDED — a
    strict superset of the prep log, derived from photos-21 / the resolved-UTC cache / photos-24.
    `earlier_passes` — [(plan, confirmed operation ids)], oldest first — are the geotag
    passes executed before the current plan's: their steps come first, so a photo written in an
    earlier pass keeps the record of it however later passes went. Deterministic, fingerprint-keyed.
    The prep file itself is never edited."""
    photos = json.loads(json.dumps(prep_photos or {}))            # deep copy; never touch the prep file
    row_by_rel = {r["relative_path"]: r for r in resolved_rows}
    t_dests = (time_artifact or {}).get("destinations") or {}
    ops_by_fp = {}
    fp_by_rel = {f["relative_path"]: f.get("content_fingerprint") for f in files}
    for dd in (plan.get("destinations") or {}).values():
        for op in dd.get("operations") or []:
            fp = (op.get("preconditions") or {}).get("content_fingerprint") or fp_by_rel.get(op["relative_path"])
            ops_by_fp.setdefault(fp, []).append(op)
    earlier = [_earlier_pass_steps(p, confirmed) for p, confirmed in earlier_passes]
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

        if row.get("time_rule_used") == "camera_group_offset" and row.get("utc_offset_used") is not None:
            cells = (t_dests.get(dest) or {}).get("camera_group_time_decisions") or {}
            steps.append({"phase": "geotag", "action": "clock_offset_applied",
                          "offset_seconds": row["utc_offset_used"],
                          "offset_description": describe_offset(row["utc_offset_used"]),
                          "because": offset_decision_pointer(dict(row, camera_group=row.get("camera_group") or group),
                                                             dest, cells)})
        if row.get("resolved_utc"):
            steps.append({"phase": "geotag", "action": "resolved_utc", "value": row["resolved_utc"]})
        tz = ((t_dests.get(dest, {}).get("destination_timezone")) or {}).get("effective_iana_timezone")
        if tz:
            steps.append({"phase": "geotag", "action": "timezone_resolved", "value": tz,
                          "because": f"photos-21 destinations.{dest}.destination_timezone"})

        steps.extend(_gps_and_rename_steps(ops, native=f.get("has_native_gps")))
        if not f.get("from_originals") and geotag_marker(held_values(f).get("method")):
            # geotag's mark is on the photo, but this workspace never held its own values: its time was
            # fixed elsewhere, or that history is lost — say so rather than look whole (§13.3a). The
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
    return photos


def geotag_execution_status(newly, skipped_n, failures, mismatches, blockers):
    """Terminal status of a geotag execution (§29.2 item 7): `success` (no failures, mismatches, or
    blockers); `failed` (degraded by failures/blockers with nothing applied this run, nothing
    already-satisfied, and no held-back mismatch — i.e. nothing was achieved); otherwise `partial`.
    A non-empty mismatch list always forces `partial` (a write occurred but is held back, §29.1a),
    never `failed`. Pre-mutation aborts are `rejected`, decided elsewhere."""
    if not (failures or mismatches or blockers):
        return "success"
    if mismatches or newly > 0 or skipped_n > 0:
        return "partial"
    return "failed"


