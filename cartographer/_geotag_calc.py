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
    selected_gpx_root, CAMERA_IDENTITY_FIELDS, FIELD_SET_VERSION, CAMERA_GROUP_KEY_VERSION, FOLDER_ROLES,
    missing_managed_folders, by_dest_reprep_pending,
    json_dependency, verify_json_dependency, handoff_content_fingerprint, write_json_artifact, write_versioned_json, db_path, ensure_control_dir,
    journal_path, ContentHasher, _move_no_clobber,
    prep_log_path, prep_db_snapshot_path, write_db_snapshot, take_zfs_snapshot,
    WorkspaceLock, ProgressCoordinator,
)
from .reporting import get_reporter

__all__ = [
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
    '_MANUAL_GPS_CATEGORIES',
    '_handoff_pre_state',
    '_revert_tags',
    '_walk_ancestors',
    '_nearest_ancestor',
    '_expand_destinations',
    '_dest_label',
    'destination_local_basename',
    '_allocate_name',
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


class GPXIndex:
    """Deterministically ordered, fingerprinted index of all GPX track points under gpx_root.

    Availability is recorded in `status` (disabled / missing / empty / usable). The `fingerprint`
    is a SHA-256 over the root, each file's bytes, and each parsed point — it becomes an upstream
    dependency of the time/GPS artifacts in later phases (§4–§6)."""

    def __init__(self, gpx_root):
        self.gpx_root = gpx_root
        self.points = []
        self.fingerprint = None
        self.status = "disabled"
        self.warnings = []

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
            if f.lower().endswith(".gpx"))

        if coordinator:                       # per-file progress (count + %), named by GPX file
            coordinator.start_phase("loading GPX tracks", len(gpx_files))
        h = hashlib.sha256()
        h.update(self.gpx_root.encode("utf-8"))
        h.update(b"gpx-index-v1")
        for rel, abs_path in gpx_files:
            if coordinator:
                coordinator.set_detail(rel)
            h.update(rel.encode("utf-8"))
            read_ok = True
            try:
                with open(abs_path, "rb") as f:
                    h.update(hashlib.sha256(f.read()).digest())
            except OSError as e:
                self.warnings.append(f"Could not read GPX file {rel}: {e}")
                read_ok = False
            if read_ok:
                self._parse_file(rel, abs_path)
            if coordinator:
                coordinator.increment_completed(1)
        if coordinator:
            coordinator.finish_phase()

        self.points.sort(key=lambda p: (p.time_utc, p.source_file, p.point_index))
        for p in self.points:
            h.update(p.time_utc.isoformat().encode("utf-8"))
            h.update(f"{p.lat}|{p.lon}|{p.source_file}|{p.point_index}".encode("utf-8"))
        self.fingerprint = h.hexdigest()
        self.status = "usable" if self.points else "empty"
        return self

    def _parse_file(self, rel, abs_path):
        try:
            root = ET.parse(abs_path).getroot()
        except ET.ParseError as e:
            self.warnings.append(f"Malformed GPX XML in {rel}: {e}")
            return
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
                    self.warnings.append(f"Out-of-range coordinate in {rel} at trkpt {idx}")
                    idx += 1
                    continue
                ts = time_elem.text.strip()
                if ts.endswith("Z"):
                    dt = datetime.strptime(ts, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
                else:
                    dt = datetime.fromisoformat(ts)
                    if dt.tzinfo is None:
                        self.warnings.append(f"GPX time without timezone in {rel} at trkpt {idx}")
                        idx += 1
                        continue
                    dt = dt.astimezone(timezone.utc)
                self.points.append(GPXPoint(lat, lon, dt, rel, idx))
            except ValueError as e:
                self.warnings.append(f"Bad trkpt in {rel} at index {idx}: {e}")
            idx += 1


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
    """Map a COMPLETE photos-23 to `{(destination, bucket_key): validated_offset_seconds}` for every
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
    (from photos-23, §22a) replaces a bucket's offset with the operator-validated one. Returns
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
        if naive is not None:
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


_MANUAL_GPS_CATEGORIES = ("manual_locked", "manual_fallback")


def _handoff_pre_state(native_gps):
    """A manual GPS override's pre-state from prep's scan (§24.1) — the file's original GPS as the
    handoff recorded it, NOT a re-read at execute time. `native_gps` is {lat, lon, processing_method}
    or None. Returns the pinned ledger value: the prior coordinates, or the 'absent' sentinel."""
    if native_gps and native_gps.get("lat") is not None and native_gps.get("lon") is not None:
        return {"present": True, "GPSLatitude": native_gps["lat"], "GPSLongitude": native_gps["lon"],
                "GPSProcessingMethod": native_gps.get("processing_method") or ""}
    return {"present": False}


def _revert_tags(pre_state):
    """The exiftool tag writes that restore a pinned pre-state: the prior coordinates, or empty
    values that CLEAR the GPS the override added when prep saw no native GPS (§24.1.2)."""
    if pre_state.get("present"):
        return {"GPSLatitude": pre_state["GPSLatitude"], "GPSLongitude": pre_state["GPSLongitude"],
                "GPSProcessingMethod": pre_state.get("GPSProcessingMethod") or ""}
    return {"GPSLatitude": "", "GPSLongitude": "", "GPSProcessingMethod": ""}


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


def _allocate_name(stem, ext, occupied):
    """First free '<stem><ext>' / '<stem>-NNN<ext>' not in `occupied` (compared case-insensitively),
    added to `occupied` and returned — the deterministic no-clobber suffix allocation (§27)."""
    cand = stem + ext
    idx = 0
    while cand.lower() in occupied:
        idx += 1
        cand = f"{stem}-{idx:03d}{ext}"
    occupied.add(cand.lower())
    return cand


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
        if base is None or name.lower() == base.lower():
            out.append({"relative_path": rel, "current_name": name, "planned_name": name, "rename": False})
            continue
        planned = _allocate_name(os.path.splitext(base)[0], ext, occupied)
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


def plan_file_ops(file, resolved_utc, tz, gps_category, gps_coord, rename, cfg):
    """The ordered executable operations for one file (§28): corrected-time metadata write, GPS
    write + provenance marker, and no-clobber rename — each gated by the camera_time policy write
    flags. Returns [] for a file that needs nothing (a no-op)."""
    pol = cfg.get("camera_time_and_timezone_policy") or {}
    rel = file["relative_path"]
    pre = {"content_fingerprint": file.get("content_fingerprint"),
           "size": file.get("size"), "mtime_ns": file.get("mtime_ns")}
    ops = []

    if pol.get("write_corrected_metadata_times", True):
        dto, off = _local_time_and_offset(resolved_utc, tz)
        if dto is not None:
            writes = {"DateTimeOriginal": dto}
            if pol.get("write_corrected_offset_tags", True) and off:
                writes["OffsetTimeOriginal"] = off
            ops.append(_make_op("metadata_time_write", rel, "corrected capture time", {"writes": writes}, pre))

    if gps_category in _GPS_OP_ORIGIN and gps_coord is not None:
        ops.append(_make_op("metadata_gps_write", rel, f"gps:{gps_category}",
                            {"writes": {"GPSLatitude": gps_coord["lat"], "GPSLongitude": gps_coord["lon"]},
                             "gps_origin": _GPS_OP_ORIGIN[gps_category]}, pre))
        ops.append(_make_op("gps_marker_write", rel, "gps provenance",
                            {"writes": {"GPSProcessingMethod": _GPS_OP_MARKER[gps_category]}}, pre))

    if pol.get("write_corrected_filename_times", True) and rename and rename.get("rename"):
        ops.append(_make_op("rename_no_clobber", rel, "destination-local timestamp name",
                            {"from": rename["current_name"], "to": rename["planned_name"]}, pre))
    return ops


# ============================================================================
# Stage 11 — finalize: the photos-26 transformation log (shared contract §13.3).
# Prep's per-photo log carried forward + geotag steps appended. A derived
# consolidation of artifacts already written — no new authority.
# ============================================================================

def build_complete_log(prep_photos, files, resolved_rows, time_artifact, plan, ledger):
    """photos-26-complete-log.json's `photos` (§13.3): a deep copy of prep's per-photo, content-
    fingerprint-keyed journeys with each calibrated photo's `phase:"geotag"` steps APPENDED — a
    strict superset of the prep log, derived from photos-21 / the resolved-UTC cache / photos-24 /
    the ledger. Deterministic, fingerprint-keyed. The prep file itself is never edited."""
    photos = json.loads(json.dumps(prep_photos or {}))            # deep copy; never touch the prep file
    row_by_rel = {r["relative_path"]: r for r in resolved_rows}
    t_dests = (time_artifact or {}).get("destinations") or {}
    pre_by_fp = {e["content_fingerprint"]: e["pre_state"] for e in (ledger or [])}
    ops_by_rel = {}
    for dd in (plan.get("destinations") or {}).values():
        for op in dd.get("operations") or []:
            ops_by_rel.setdefault(op["relative_path"], []).append(op)

    for f in sorted(files, key=lambda x: x["relative_path"]):
        fp = f.get("content_fingerprint")
        if not fp:
            continue
        rel, dest, group = f["relative_path"], f["destination"], f["camera_group_key"]
        entry = photos.setdefault(fp, {"content_fingerprint": fp, "journey": []})
        steps = entry.setdefault("journey", [])
        row = row_by_rel.get(rel) or {}
        ops = ops_by_rel.get(rel) or []

        if row.get("time_rule_used") == "camera_group_offset" and row.get("utc_offset_used") is not None:
            steps.append({"phase": "geotag", "action": "clock_offset_applied",
                          "offset_seconds": row["utc_offset_used"],
                          "because": f"photos-21 destinations.{dest}.camera_group_time_decisions.{group}"})
        if row.get("resolved_utc"):
            steps.append({"phase": "geotag", "action": "resolved_utc", "value": row["resolved_utc"]})
        tz = ((t_dests.get(dest, {}).get("destination_timezone")) or {}).get("effective_iana_timezone")
        if tz:
            steps.append({"phase": "geotag", "action": "timezone_resolved", "value": tz,
                          "because": f"photos-21 destinations.{dest}.destination_timezone"})

        revert_op = next((o for o in ops if o["type"] == "revert_manual_gps"), None)
        gps_op = next((o for o in ops if o["type"] == "metadata_gps_write"), None)
        marker = next((o for o in ops if o["type"] == "gps_marker_write"), None)
        if revert_op is not None:
            steps.append({"phase": "geotag", "action": "gps_reverted",
                          "pre_state": revert_op.get("pre_state") or pre_by_fp.get(fp)})
        elif gps_op is not None:
            w = gps_op.get("writes") or {}
            step = {"phase": "geotag", "action": "gps_written", "lat": w.get("GPSLatitude"),
                    "lon": w.get("GPSLongitude"), "origin": gps_op.get("gps_origin"),
                    "gps_processing_method": (marker.get("writes") or {}).get("GPSProcessingMethod") if marker else None}
            if gps_op.get("gps_origin") == "apply_manual" and fp in pre_by_fp:
                step["pre_state"] = pre_by_fp[fp]
            steps.append(step)
        elif f.get("has_native_gps"):
            steps.append({"phase": "geotag", "action": "gps_preserved"})

        rename_op = next((o for o in ops if o["type"] == "rename_no_clobber"), None)
        if rename_op is not None:
            steps.append({"phase": "geotag", "action": "final_rename", "to": rename_op["to"]})
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


