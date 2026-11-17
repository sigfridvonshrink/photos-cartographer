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

"""photos-2-geotag — geotag phase.

Geotag takes a prepped, user-curated `6-photos-by-dest/` and: infers each camera's clock
offset by matching its geotagged frames against GPX tracks, resolves every photo to real UTC,
places GPS for the un-tagged majority, and renames files to destination-local civil time — all on
the same plan/validate/execute, fingerprinted-dependency, authored-decisions discipline as prep.

It implements the full geotag workflow (Stages 1–11): the preflight lifecycle/by-dest gates
(RUL-geotag_gates, BLD-loop_gates), the in-memory by-dest model (Stage 2), the GPX index (BLD-track_points),
camera-group recognition (BLD-known_camera_group), the time/drift/GPS-decision artifacts
`photos-21`/`photos-22`/`photos-23` (BLD-decision_record_envelope), resolved-UTC computation (BLD-resolved_utc),
the executable plan `photos-24` (BLD-executable_plan), `execute` of that plan into `photos-25`
(BLD-geotag_execution), and `finalize` of the archival package `photos-26` + DB snapshot + manifest
(BLD-archive_manifest).
Subcommands: `plan`, `execute`, `finalize`.

The script sits beside `photos_utils.py` and imports the shared infrastructure from it.
"""
import argparse
import concurrent.futures
import glob
import hashlib
import json
import math
import os
import shutil
import sqlite3
import stat
import subprocess
import sys
import threading
import xml.etree.ElementTree as ET
import zoneinfo
from datetime import datetime, timedelta, timezone

from .photos_utils import (ends_unforeseen_error_apart, fingerprint_method_blocker, links_under, replace_durably,
    exiftool_artifact_base,
    country_table, zone_table_record_error,
    zone_table,
    code_fingerprint,
    CONFIG, CONTROL_DIR, control_dir, FINALIZED_MEDIA_ARTIFACT, finalized_media_path, workspace_volume_error, workspace_filesystem_error, config_path, handoff_path, guard_path, is_sealed, likely_new_dump,
    validate_config, load_config, sha256_file, sha256_text, media_class_for_ext, folder_name,
    folders_fingerprint, media_extensions_fingerprint,
    selected_gpx_root, NO_IDENTITY_KEY, has_own_position, photos_without_position,FIELD_SET_VERSION, CAMERA_GROUP_KEY_VERSION, FOLDER_ROLES,
    missing_managed_folders, top_level_links, misplaced_top_level_entries, by_dest_reprep_pending,
    json_dependency, verify_json_dependency, handoff_content_fingerprint, handoff_filename_format_blocker, write_json_artifact, write_versioned_json, backup_existing_artifact,
    db_path, ensure_control_dir,
    journal_path, ContentHasher, _move_no_clobber, get_imagemagick_version,
    prep_log_path, prep_log_blocker, entries_not_carried, retaken_fingerprints, write_db_snapshot, take_zfs_snapshot,
    control_archive_members, write_control_archive, workspace_id,
    WorkspaceLock, LockFileError, ProgressCoordinator,
    add_accept_changes_argument, check_workspace, write_workspace_record, note_execution_begun, journal_add_changes,
    journal_kept_changes,
)
from .reporting import get_reporter, emit_next_step, next_steps_muted

TIME_DECISIONS_ARTIFACT = "photos-21-time-decisions.json"
DRIFT_VALIDATION_ARTIFACT = "photos-22-gps-drift-validation.json"
GPS_DECISIONS_ARTIFACT = "photos-23-gps-decisions.json"
EXECUTABLE_PLAN_ARTIFACT = "photos-24-executable-plan.json"
EXECUTION_SUMMARY_ARTIFACT = "photos-25-execution-summary.json"
COMPLETE_LOG_ARTIFACT = "photos-26-complete-log.json"
GEOTAG_DB_SNAPSHOT = "photos-26-geotag-ingest.db"
ARCHIVE_MANIFEST_ARTIFACT = "photos-26-archive-manifest.json"
ARCHIVE_ARTIFACT = "photos-26-archive.tar.gz"
# The fields of a day's offset cell that answer a proposed change of the camera's clock (BLD-clock_change_split).
CLOCK_CHANGE_FIELDS = ("accept_clock_change", "accepted_change_offsets_seconds", "photo_parts")
EXECUTED_DIR = "executed"            # executed/<plan id>/: the decision records each executed plan ran against
GPX_WARNINGS_SHOWN = 10     # geotag plan prints at most this many GPX load warnings, then a count
UNREADABLE_TAGS_SHOWN = 20  # geotag plan names at most this many photos whose offset tag holds no offset, then a count



from ._geotag_calc import *  # noqa: F401,F403 — re-export the pure calc layer (keeps photos_2_geotag.<fn> resolvable for GeotagWorkflow, tests, and patches)

def time_decisions_path(ws):
    return os.path.join(ws, CONTROL_DIR, TIME_DECISIONS_ARTIFACT)


def drift_validation_path(ws):
    return os.path.join(ws, CONTROL_DIR, DRIFT_VALIDATION_ARTIFACT)


def gps_decisions_path(ws):
    return os.path.join(ws, CONTROL_DIR, GPS_DECISIONS_ARTIFACT)


def executable_plan_path(ws):
    return os.path.join(ws, CONTROL_DIR, EXECUTABLE_PLAN_ARTIFACT)


def execution_summary_path(ws):
    return os.path.join(ws, CONTROL_DIR, EXECUTION_SUMMARY_ARTIFACT)


def complete_log_path(ws):
    return os.path.join(ws, CONTROL_DIR, COMPLETE_LOG_ARTIFACT)


def geotag_db_snapshot_path(ws):
    return os.path.join(ws, CONTROL_DIR, GEOTAG_DB_SNAPSHOT)


def archive_path(ws):
    return os.path.join(ws, CONTROL_DIR, ARCHIVE_ARTIFACT)


def archive_manifest_path(ws):
    return os.path.join(ws, CONTROL_DIR, ARCHIVE_MANIFEST_ARTIFACT)


# ============================================================================
# Stage 3 — GPX index (BLD-track_points). GPX is geotag-only — prep is GPX-unaware
# (RUL-tracks_geotag_only). Stdlib xml.etree only; no new dependency.
# ============================================================================

class GeotagCache:
    """Geotag's own region of the shared photos-00-ingest.db (BLD-workspace_database) — the
    resolved-UTC cache and the original-values ledger. Disjoint from prep's tables."""

    COLUMNS = ["relative_path", "destination_path", "destination_timezone", "camera_group",
               "time_decision_scope", "source_naive_time", "source_time_provenance", "time_rule_used",
               "utc_offset_used", "resolved_utc", "resolved_utc_status", "resolved_utc_provenance"]

    def __init__(self, ws):
        ensure_control_dir(ws)
        self.conn = sqlite3.connect(db_path(ws))
        self.conn.execute(
            "CREATE TABLE IF NOT EXISTS resolved_utc_cache ("
            "relative_path TEXT PRIMARY KEY, destination_path TEXT, destination_timezone TEXT, "
            "camera_group TEXT, time_decision_scope TEXT, source_naive_time TEXT, "
            "source_time_provenance TEXT, time_rule_used TEXT, utc_offset_used INTEGER, "
            "resolved_utc TEXT, resolved_utc_status TEXT, resolved_utc_provenance TEXT)")
        self.conn.execute(
            "CREATE TABLE IF NOT EXISTS original_values ("
            "content_fingerprint TEXT PRIMARY KEY, relative_path TEXT, original TEXT, captured_at TEXT, "
            "times_written TEXT)")
        self.conn.commit()

    def replace_all(self, rows):
        with self.conn:
            self.conn.execute("DELETE FROM resolved_utc_cache")
            self.conn.executemany(
                f"INSERT INTO resolved_utc_cache ({','.join(self.COLUMNS)}) "
                f"VALUES ({','.join('?' * len(self.COLUMNS))})",
                [[r.get(c) for c in self.COLUMNS] for r in rows])

    def get_rows(self):
        cur = self.conn.execute(
            f"SELECT {','.join(self.COLUMNS)} FROM resolved_utc_cache ORDER BY relative_path")
        return [dict(zip(self.COLUMNS, row)) for row in cur.fetchall()]

    # --- original-values ledger (BLD-original_values_pinned): a file's own values, pinned before geotag's first write
    def originals_pin(self, fp, rel, original, captured_at):
        """Pin a file's own values ONCE — never overwritten, so every later run decides from them."""
        with self.conn:
            self.conn.execute(
                "INSERT OR IGNORE INTO original_values (content_fingerprint, relative_path, original, captured_at) "
                "VALUES (?,?,?,?)", (fp, rel, json.dumps(original, sort_keys=True), captured_at))

    def originals_rekey(self, old, new):
        """Move a pin to the value a photo's fingerprint was taken again with, unless one is held there."""
        with self.conn:
            self.conn.execute(
                "UPDATE original_values SET content_fingerprint = ? WHERE content_fingerprint = ? "
                "AND NOT EXISTS (SELECT 1 FROM original_values WHERE content_fingerprint = ?)", (new, old, new))

    def originals_all(self):
        cur = self.conn.execute("SELECT content_fingerprint, original FROM original_values")
        return {r[0]: json.loads(r[1]) for r in cur.fetchall()}

    def originals_true_time(self, fp, kept):
        """Record beside the pinned file's own values the time the user kept as its true local time
        (BLD-changed_time_kept_pinned): its `true_time`, `kept`'s DateTimeOriginal and OffsetTimeOriginal, every pinned
        own value staying, so every later run resolves the photo from that time by its destination's zone. A file with
        no pin is not touched."""
        with self.conn:
            row = self.conn.execute("SELECT original FROM original_values WHERE content_fingerprint = ?",
                                    (fp,)).fetchone()
            if row is None:
                return
            original = dict(json.loads(row[0]), true_time={k: kept.get(k) for k in TIME_PAIR})
            self.conn.execute("UPDATE original_values SET original = ? WHERE content_fingerprint = ?",
                              (json.dumps(original, sort_keys=True), fp))

    def originals_drop_true_time(self, fp):
        """Take out of the pinned file's own values the time the user kept as its true one, once their answer to keep
        it is withdrawn and answered otherwise (BLD-changed_time_kept_pinned). A file with no pin, or none kept, is
        not touched."""
        with self.conn:
            row = self.conn.execute("SELECT original FROM original_values WHERE content_fingerprint = ?",
                                    (fp,)).fetchone()
            if row is None:
                return
            original = json.loads(row[0])
            if original.pop("true_time", None) is not None:
                self.conn.execute("UPDATE original_values SET original = ? WHERE content_fingerprint = ?",
                                  (json.dumps(original, sort_keys=True), fp))

    def time_written_record(self, fp, pair):
        """Record, beside a pinned file's own values, a time and offset geotag is about to write to it
        (BLD-time_written_recorded): every one is kept, so a re-plan knows each time the photo can hold from geotag.
        A file with no pin is not recorded."""
        with self.conn:
            row = self.conn.execute("SELECT times_written FROM original_values WHERE content_fingerprint = ?",
                                    (fp,)).fetchone()
            if row is None:
                return
            times = json.loads(row[0] or "[]")
            if pair not in times:
                self.conn.execute("UPDATE original_values SET times_written = ? WHERE content_fingerprint = ?",
                                  (json.dumps(times + [pair], sort_keys=True), fp))

    def times_written_all(self):
        cur = self.conn.execute("SELECT content_fingerprint, times_written FROM original_values")
        return {r[0]: json.loads(r[1] or "[]") for r in cur.fetchall()}

    def close(self):
        self.conn.close()


# ============================================================================
# GeotagWorkflow — the geotag orchestrator (Stages 1–11), the I/O + decision-
# artifact layer. The pure GPS-placement helpers it calls (place_gps,
# _interp/_extrapolate, classify_gps) now live in _geotag_calc.py (BLD-track_placement, BLD-placement_order).
# ============================================================================

def _decision_shape_blockers(prior, kind):
    """Where a prior decision artifact's structure is broken, as located blockers (RUL-checked_decision_structure,
    RUL-invalid_value_located). The user fills values, never structure: every container the builders walk to
    reach a user_decision — the destinations, each destination, its decision blocks and cells, and each
    user_decision — must be an object (review_items a list of objects), or the run stops on it, never
    passing over it. `kind` is "time" (photos-21), "drift" (photos-22) or "gps" (photos-23)."""
    out = []
    dests = (prior or {}).get("destinations")
    if dests is None:
        return out
    if not isinstance(dests, dict):
        return ["destinations must be an object."]

    def obj(container, key, where):
        v = container.get(key)
        if v is None or isinstance(v, dict):
            return v or {}
        out.append(f"{where} must be an object.")
        return {}

    def cells(d, key, dest):
        for bucket, cell in obj(d, key, f"{dest}: {key}").items():
            if not isinstance(cell, dict):
                out.append(f"{dest}: {key}[{bucket}] must be an object.")
            else:
                obj(cell, "user_decision", f"{dest}: {key}[{bucket}].user_decision")

    for dest, d in dests.items():
        if not isinstance(d, dict):
            out.append(f"{dest}: the destination's entry must be an object.")
            continue
        if kind == "time":
            obj(obj(d, "destination_timezone", f"{dest}: destination_timezone"), "user_decision",
                f"{dest}: destination_timezone.user_decision")
            cells(d, "camera_group_time_decisions", dest)
            cells(d, "local_time_readings", dest)
            cells(d, "changed_times", dest)
            obj(obj(d, "unidentified_files", f"{dest}: unidentified_files"), "user_decision",
                f"{dest}: unidentified_files.user_decision")
            obj(obj(d, "date_fallback", f"{dest}: date_fallback"), "user_decision",
                f"{dest}: date_fallback.user_decision")
        elif kind == "drift":
            cells(d, "drift_decisions", dest)
        else:
            obj(obj(d, "folder_fallback", f"{dest}: folder_fallback"), "user_decision",
                f"{dest}: folder_fallback.user_decision")
            items = obj(d, "gps_decisions", f"{dest}: gps_decisions").get("review_items")
            if items is None:
                continue
            if not isinstance(items, list):
                out.append(f"{dest}: gps_decisions.review_items must be a list.")
                continue
            for i, ri in enumerate(items):
                if not isinstance(ri, dict) or not isinstance(ri.get("relative_path"), str):
                    out.append(f"{dest}: gps_decisions.review_items[{i}] must be an object with its relative_path.")
                else:
                    obj(ri, "user_decision", f"{dest}/{os.path.basename(ri['relative_path'])}: user_decision")
    out += unknown_decision_fields(prior, kind)
    return out


# The fields of a photo's position decision in photos-23 (BLD-geotag_checks_decisions): a position the user sets for it.
REVIEW_DECISION_FIELDS = ("manual_lat", "manual_lon")

# The fields each kind of decision has, by the record (`kind`) and the block or cell family that holds its
# `user_decision` (RUL-unknown_decision_field_refused): those geotag lays out and reads, every variant of the block's
# included — a phone's `keep_as_recorded`, a day's clock-change answer — so a cell whose variant changed is never
# refused for a field its earlier one had.
DECISION_FIELDS = {
    "time": {
        "destination_timezone": ("a destination's timezone decision",
                                 ("manual_iana_timezone", "country", "confirmed_despite_recorded_offsets")),
        "camera_group_time_decisions": ("a camera's clock-offset decision",
                                        ("accept_proposal", "accepted_offset_seconds", "manual_offset_seconds",
                                         "keep_as_recorded") + CLOCK_CHANGE_FIELDS),
        "local_time_readings": ("a photo's reading of its local time", ("utc_offset_seconds",)),
        "changed_times": ("a changed time's answer", ("keep", "answered_for")),
        "unidentified_files": ("the decision of the files naming no camera", ("accept_proposal", "accepted_timezone")),
        "date_fallback": ("a destination's date fallback", ("date",)),
    },
    "drift": {
        "drift_decisions": ("a drift validation", ("confirmed", "corrected_offset_seconds", "confirmed_offset_seconds",
                                                   "confirmed_against_tracks")),
    },
    "gps": {
        "folder_fallback": ("a destination's fallback position", ("fallback_lat", "fallback_lon")),
        "gps_decisions": ("a photo's position decision", REVIEW_DECISION_FIELDS),
    },
    # photos-25: a photo's changed content accepted (BLD-geotag_checks_decisions)
    "execution": {
        "fingerprint_mismatches": ("a photo's content acceptance", ("accept_fingerprint_change",)),
    },
}
# The blocks of one decision per destination; the others are cell families, one decision per cell.
_SINGLE_DECISION_BLOCKS = ("destination_timezone", "unidentified_files", "date_fallback", "folder_fallback")


def unknown_decision_fields(record, kind):
    """Where a `user_decision` of a decision record holds a field its decision does not have, one located blocker per
    field, naming it (RUL-unknown_decision_field_refused): a field geotag does not read, left in, would say what
    geotag does not do — a misspelt `acept_proposal` read as no answer, or `accept_unlocated`, from when a photo could
    be left without a position. `kind` is "time" (photos-21), "drift" (photos-22) or "gps" (photos-23). A structure
    broken on the way is left to `_decision_shape_blockers`; the decision editor shows a record holding such a field
    as one it cannot read."""
    out = []
    dests = record.get("destinations") if isinstance(record, dict) else None
    for dest, d in (dests.items() if isinstance(dests, dict) else ()):
        if not isinstance(d, dict):
            continue
        for block, (what, fields) in DECISION_FIELDS[kind].items():
            held = d.get(block)
            if not isinstance(held, dict):
                continue
            if block in _SINGLE_DECISION_BLOCKS:
                found = [(f"{dest}: {block}", held)]
            elif block == "gps_decisions":
                items = held.get("review_items")
                found = [(f"{dest}/{os.path.basename(str(ri.get('relative_path')))}", ri)
                         for ri in (items if isinstance(items, list) else ()) if isinstance(ri, dict)]
            else:
                found = [(f"{dest}: {block}[{cell}]", c) for cell, c in held.items() if isinstance(c, dict)]
            for where, decision in found:
                ud = decision.get("user_decision")
                if not isinstance(ud, dict):
                    continue
                only = fields[0] if len(fields) == 1 else f"{', '.join(fields[:-1])} and {fields[-1]}"
                for k in sorted(k for k in ud if k not in fields):
                    out.append(f"{where}: user_decision.{k} is not a field of {what} (only {only}) — remove it.")
    return out


def _camera_bucket(cells, f):
    """The key of the photos-21 offset cell of `f`'s camera on its day, among its destination's `cells`
    (BLD-placed_photos): `<group>@<date>` where the destination keys the camera by day, else `<group>` — None where
    the camera has no offset cell there, or the photo no time its camera recorded (a date fallback's photo)."""
    group, date = f.get("camera_group_key"), _naive_date(f.get("source_naive_time"))
    if date is None:
        return None
    key = f"{group}@{date}"
    key = key if key in cells else group
    return key if key in cells else None


def fallback_placement_lines(gps_artifact):
    """For each destination of photos-23 whose folder fallback placed photos, a line saying how many, and whose
    fallback it is — the destination's own, or inherited from the destination named (RUL-fallback_placements_told,
    BLD-fallback_placements_printed)."""
    out = []
    for dest, d in sorted(((gps_artifact or {}).get("destinations") or {}).items()):
        n = ((d.get("gps_decisions") or {}).get("summary") or {}).get("automatic_folder_fallback") or 0
        if not n:
            continue
        fb = d.get("folder_fallback") or {}
        whose = (f"the fallback inherited from {fb.get('inherited_from')}" if fb.get("fallback_source") == "inherited"
                 else "its own fallback")
        out.append(f"  {dest}: {n} photo(s) placed by {whose}.")
    return out


def _decision_flag(ud, field, where, blockers):
    """A yes-or-no the user writes: absent (or null) means no; true or false as written; anything else
    — "false", 1, "yes" — is a located blocker, never coerced (RUL-checked_shapes)."""
    v = ud.get(field)
    if v is None or isinstance(v, bool):
        return bool(v)
    blockers.append(f"{where}.{field} must be true or false, not {v!r}.")
    return False


def _half_position(lat, lon):
    """True iff exactly one of a position's two numbers is filled in."""
    return (lat in (None, "")) != (lon in (None, ""))


def _prior_day_cell(prior_cells, group, bucket, day):
    """The earlier answer for a camera's day in a destination: the cell under this key, else the one the
    same day was recorded under while the key had its other form — a camera's only day there is keyed by
    the group alone, and by `<group>@<day>` once a second day arrives (BLD-offset_buckets). The day, not the key, is
    what an answer was given for, so it follows the day."""
    cell = prior_cells.get(bucket)
    if day is None:
        return cell or {}
    if cell and cell.get("day") in (None, day):
        return cell
    # the cell under this key was another day's (its photos gone, another day's put here): not this day's
    other = prior_cells.get(group if bucket != group else f"{group}@{day}") or {}
    return other if other.get("day") == day else {}


def _prior_review(prior_items, file):
    """The earlier decision made for one photo: found by its content fingerprint — which geotag's own
    rename, and a fingerprint taken again, leave pointing at the same photo — else by its path."""
    by_fp, by_path = prior_items
    for key in _decision_keys(file):
        if key in by_fp:
            return by_fp[key]
    return by_path.get(file["relative_path"]) or {}


def _decision_keys(file):
    """The fingerprints a decision made for one photo can be recorded under, in order: its fingerprint now, the one its
    pin is kept under, and each it had before it was taken again (BLD-review_item_identity)."""
    keys = [file.get("content_fingerprint"), file.get("original_key"), *(file.get("earlier_fingerprints") or [])]
    return [k for i, k in enumerate(keys) if k is not None and k not in keys[:i]]


def _earlier_decision(earlier, file):
    """The decision `earlier` ({fingerprint: cell}) holds for `file`, by any of its fingerprints, or {}."""
    return next((earlier[k] for k in _decision_keys(file) if k in earlier), {})


def _stop_on_tracks(reporter, gpx, written):
    """Stop the plan, exit 2, on tracks it cannot plan by: configured and not there, a folder of them that cannot be
    listed, or track files of which not one can be read. `written` says what the plan has written so far."""
    if gpx.status == "missing":
        # Tracks that are configured but not there — a volume not mounted — are not "no tracks":
        # planning on would place by folder fallback what the tracks place, and drop every
        # answer given about them (RUL-missing_tracks_stop_geotag).
        reporter.error(f"\nGeotag cannot proceed: {gpx.warnings[0]}")
        reporter.log(f"\n{written}")
        emit_next_step(reporter, "make the tracks available (or set gpx_root to \"\" in "
                                 "photos-00-config.json to plan without tracks), then re-run `geotag plan`.")
        sys.exit(2)
    if gpx.status == "unlisted":
        # A folder of the tracks that cannot be listed: what it holds cannot be checked, so it counts as changed
        # (RUL-unlisted_tracks_stop_geotag) — never as a folder of no tracks.
        reporter.error(f"\nGeotag cannot proceed: under gpx_root {gpx.gpx_root}, what is in "
                       f"{len(gpx.unlisted)} folder(s) cannot be seen:")
        for where, why in gpx.unlisted:
            reporter.log(f"  - {where}: {why}")
        reporter.log(f"\n{written}")
        emit_next_step(reporter, "make the folder(s) readable, then re-run `geotag plan`.")
        sys.exit(2)
    if gpx.status == "unreadable":
        # Track files there and not one read: planning on would place by folder fallback what the
        # tracks place, as if there were none (RUL-unreadable_tracks_stop_geotag).
        reporter.error(f"\nGeotag cannot proceed: not one of the {len(gpx.unreadable)} track file(s) under "
                       f"gpx_root {gpx.gpx_root} can be read:")
        for rel, why in gpx.unreadable:              # every one, each with why: the user's to repair
            reporter.log(f"  - {rel}: {why}")
        for w in gpx.told:                           # each link, missing ranked folder, gone file: named
            reporter.warn(f"  Warning: {w}")
        reporter.log(f"\n{written}")
        emit_next_step(reporter, "repair or replace the track files (or set gpx_root to \"\" in "
                                 "photos-00-config.json to plan without tracks), then re-run `geotag plan`.")
        sys.exit(2)


def _named(paths, shown=5):
    """A gate's list of the files it found: every one up to `shown`, then how many more (output wording —
    a user clears them in one pass rather than one per run; test_every_offending_file_is_named_up_to_five)."""
    return ", ".join(paths[:shown]) + (f" and {len(paths) - shown} more" if len(paths) > shown else "")


def _has_recorded_time(rec):
    """Whether a handoff record's photo carries a recorded time, as prep extracted it."""
    md = rec.get("metadata_status") or {}
    if md.get("has_timestamp") is not None:
        return bool(md["has_timestamp"])
    try:
        parsed = json.loads(md["parsed_json"]) if md.get("parsed_json") else {}
    except Exception:
        parsed = {}
    return bool(parsed.get("has_timestamp"))


def _recorded_fingerprint(rec):
    """The content fingerprint value a handoff record holds, or None — no `content_hash`, one that does not
    parse, or one holding no value (prep could not take it)."""
    ch = rec.get("content_hash")
    try:
        fp = json.loads(ch).get("value") if ch else None
    except Exception:
        fp = None
    return fp or None


def _holds_writes(held, writes):
    """Whether a file's read-back tags (`held`) already are the planned `writes`: an empty write means the tag is
    gone; a coordinate is compared by magnitude — EXIF keeps its sign in the reference tag — to a millionth."""
    for k, want in writes.items():
        got = held.get(k)
        if want == "" or want is None:
            if got not in (None, ""):
                return False
        elif isinstance(want, (int, float)) and not isinstance(want, bool):
            try:
                if abs(abs(float(got)) - abs(float(want))) > 1e-6:
                    return False
            except (TypeError, ValueError):
                return False
        elif str(got) != str(want):
            return False
    return True


class UnreadableRecord(Exception):
    """A record of an earlier execution — a journal, the execution summary, a kept plan — that is there and cannot
    be read: geotag stops, naming it, rather than take it for none (RUL-unreadable_execution_record_stops)."""

    def __init__(self, path, why):
        super().__init__(f"{path} cannot be read ({why})")
        self.path, self.why = path, why


def _read_record(path):
    """The JSON object at `path`, or None when there is no file (BLD-unreadable_execution_records). One there that
    cannot be opened or parsed, or is not an object, raises UnreadableRecord naming it."""
    try:
        with open(path) as f:
            obj = json.load(f)
    except FileNotFoundError:
        return None
    except (OSError, ValueError) as e:
        raise UnreadableRecord(path, e)
    if not isinstance(obj, dict):
        raise UnreadableRecord(path, "not a JSON object")
    return obj


class UnreadablePlan(Exception):
    """The executable plan photos-24, there and unreadable — torn, not JSON, not an object. It is made from records
    still on disk, so the way on is to plan again (RUL-unreadable_plan_replanned, BLD-unreadable_plan)."""

    def __init__(self, path, why):
        super().__init__(f"{path} cannot be read ({why})")
        self.path = path


REPLAN_ADVICE = "run `geotag plan` again to make it anew"


def read_executable_plan(ws):
    """photos-24 as a JSON object, or None when there is none; UnreadablePlan when it is there and cannot be read
    (BLD-unreadable_plan)."""
    try:
        return _read_record(executable_plan_path(ws))
    except UnreadableRecord as e:
        raise UnreadablePlan(e.path, e.why)


def _country_table_dependency(ws):
    """Where the table of countries a plan reads came from, and its SHA-256 (BLD-country_table_dependency)."""
    t = zone_table(ws)
    return {"source": t["source"], "sha256": t["sha256"]}


class GeotagWorkflow:
    """Stages 1–11: validate the workspace, build the model, produce photos-21/22/23 decision artifacts,
    compute resolved UTC, assemble photos-24-executable-plan.json (when decisions are complete),
    execute it into photos-25 (BLD-geotag_execution), and finalize the archival package photos-26
    (BLD-archive_manifest)."""

    def __init__(self, workspace_root: str):
        self.workspace_root = workspace_root
        self.handoff = None
        self._gpx_fingerprint = None
        self.planned_tracks = None        # the tracks `geotag plan` indexed (load_gpx)
        # (destination, camera group) -> the content fingerprints of the group's photos there, corrected ones
        # included: what an offset kept from its photos' fixes is checked against (BLD-day_offset_kept)
        self.fingerprints_here = {}
        # Live progress for the long phases (TTY: in-place bar; piped: a line every ~10 s; tests: quiet).
        self.coordinator = ProgressCoordinator()
        # The execution's journal is written by the main thread as photos complete and by a worker as it begins a
        # photo's write (BLD-own_leftover_cleared): one lock orders the two. `_journal_out` persists it, set by the
        # execution for its run; without one the journal is kept in memory alone.
        self._journal_lock = threading.Lock()
        self._journal_out = None

    # --- preflight (RUL-geotag_gates, BLD-loop_gates) ------------------

    def preflight(self, for_execute=False, needs_exiftool=True):
        """Return (blockers, warnings, info). A non-empty `blockers` means geotag cannot
        proceed. Textual only — writes no JSON. The lifecycle guards (sealed / uninitialized /
        loose-root-file) and the development-started gate (RUL-development_after_merge) hard-stop early; the remaining
        by-dest scope and re-prep gates are collected so the rest are reported at once. `for_execute` (execute and
        finalize) checks every gate too — the inbox, photos by date, photos by destination holding only photos, and
        that prep recorded every photo there — but the last against the handoff and the plan's renames together:
        the by-dest names the plan gives would otherwise trip the re-prep gate, and prep's other checks of its
        record are the plan's own dependency fingerprints and per-op preconditions there (BLD-loop_gates).
        `needs_exiftool` is false for finalize alone, which runs no tool on a photo."""
        blockers, warnings, info = [], [], {}
        ws = self.workspace_root

        # 1. Lifecycle guards (RUL-sealed_refuses, BLD-phases_check_seal), evaluated under the run lock by main().
        if is_sealed(ws):
            blockers.append("Workspace is SEALED (already merged): geotag will not run. "
                            "Nothing was touched — move new media into a fresh workspace.")
            if likely_new_dump(ws):
                warnings.append("A likely new dump is present (at the workspace root or in "
                                f"{folder_name('sources')}/). A sealed workspace is final; move it "
                                "into a fresh workspace by hand.")
            return blockers, warnings, info
        if not os.path.exists(guard_path(ws)):
            blockers.append("Not an initialized workspace (no photos-00-workspace-guard) — "
                            "run prep first: `photos-cartographer prep plan` then `photos-cartographer prep execute`.")
            return blockers, warnings, info
        # A symlink at the workspace root is barred outright (RUL-no_links) and never followed — including a
        # dangling link (neither file nor dir) or one named like a managed folder (which os.path.isdir
        # would otherwise resolve through). Checked before the structural/loose-entry guards below.
        root_syms = top_level_links(ws)
        if root_syms:
            blockers.append(f"Forbidden symlink at the workspace root: {', '.join(root_syms)}. Symlinks are "
                            "never followed; remove it before geotagging.")
            return blockers, warnings, info
        # The configuration is read first: it names the managed folders the checks below look for
        # (RUL-control_directory_fixed — it is found without knowing any of them).
        cfg_p = config_path(ws)
        if not os.path.exists(cfg_p):
            blockers.append("Workspace config photos-00-config.json is missing — run prep first: `photos-cartographer prep plan` then `photos-cartographer prep execute`.")
            return blockers, warnings, info
        try:
            load_config(ws)                 # the workspace's file, whole and checked, replaces CONFIG
        except ValueError as e:
            blockers.append(f"Invalid workspace config: {e}")
            return blockers, warnings, info
        except Exception as e:
            blockers.append(f"Workspace config could not be read: {e}")
            return blockers, warnings, info
        # The activated workspace must have its full 0-6 structure. A managed folder that is missing or
        # no longer a directory means the root is non-conforming — almost always an inadvertent user
        # deletion (possibly of irreplaceable media) — so HARD STOP; geotag never creates folders.
        struct_missing = missing_managed_folders(ws)
        if struct_missing:
            blockers.append("Workspace is non-conforming: missing managed folder(s): "
                            f"{', '.join(struct_missing)}. Restore the 0-6 structure (or move the "
                            "media into a fresh workspace and re-run prep there — `photos-cartographer prep plan` then `photos-cartographer prep execute`) before geotagging.")
            return blockers, warnings, info
        misplaced = misplaced_top_level_entries(ws)
        if misplaced:
            blockers.append(f"Misplaced entry at workspace root (dumps belong in "
                            f"{folder_name('sources')}/): {', '.join(misplaced)}. The top level holds only "
                            "the managed folders and hidden entries.")
            return blockers, warnings, info
        # A link among the photos geotag works on (RUL-geotag_merge_check_links): put there since prep, the handoff
        # cannot know of it, and a write through it would land in a file outside the workspace.
        linked = links_under(ws, folder_name('photos_by_dest'))
        if linked:
            more = f" (and {len(linked) - 1} more)" if len(linked) > 1 else ""
            blockers.append(f"Forbidden symlink under {folder_name('photos_by_dest')}: {linked[0]}{more}. Symlinks "
                            "are never followed; put the file itself there, or remove the link, before geotagging.")
            return blockers, warnings, info

        cfg = CONFIG

        ho_p = handoff_path(ws)
        if not os.path.exists(ho_p):
            blockers.append("Prep handoff photos-11-handoff.json is missing — run prep first: `photos-cartographer prep plan` then `photos-cartographer prep execute`.")
            return blockers, warnings, info
        try:
            with open(ho_p) as f:
                handoff = json.load(f)
        except Exception as e:
            blockers.append(f"Prep handoff could not be read: {e}")
            return blockers, warnings, info
        info["handoff_sha256"] = sha256_file(ho_p)
        self.handoff = handoff          # stashed for the model/group stages (Phase 2)

        # The filename format is fixed once prep has named the files in it (RUL-format_fixed_once_named).
        fmt_blocker = handoff_filename_format_blocker(handoff)
        if fmt_blocker:
            blockers.append(fmt_blocker)
            return blockers, warnings, info

        # External-tool preflight (BLD-geotag_exiftool_needed): execute reads and writes the photos' tags through
        # exiftool, with no fallback, and a plan is made to be executed — so a missing exiftool stops plan and
        # execute before any heavy work. Finalize runs no tool on a photo and does not look for it
        # (RUL-finalize_needs_no_metadata_tool).
        from .photos_utils import missing_tools
        if needs_exiftool and missing_tools(["exiftool"]):
            blockers.append("exiftool not found on PATH — geotag reads and writes EXIF GPS/time "
                            "through it. Install exiftool and re-run.")
            return blockers, warnings, info

        by_dest = folder_name('photos_by_dest')
        # Development-started guard (RUL-development_after_merge) — PRESENCE-STRICT and re-checked at execute/finalize
        # too, not just planning: the mere existence of a jpg/tif distribution subfolder under by-dest (even an
        # empty one) hard-stops. A breakout begun between `plan` and `execute` moves no planned file, so
        # the per-op media preconditions (BLD-geotag_execution) would not catch it; this existence check is what does.
        dev_found, nonphoto, hidden = self._scan_by_dest(by_dest)
        if hidden:
            # A hidden file or folder among the photos is a file that is no photo (RUL-sort_photos_only, RUL-geotag_gates):
            # geotag would pass it by, and merge stop on it only after the photos were written.
            blockers.append(f"{by_dest}/ holds {len(hidden)} hidden file(s) or folder(s): {_named(hidden)}. "
                            "Geotag never places a hidden entry and merge would refuse it — remove each, or give a "
                            "photo among them a name without its leading dot and run prep; then re-run geotag.")
        if dev_found:
            names = ", ".join(sorted(set(CONFIG.get("destination_distribution_subfolders") or [])))
            blockers.append(f"Development has already started — a distribution subfolder ({names}) "
                            f"exists under {by_dest}: {dev_found[0]}. Time/GPS calibration must run "
                            "BEFORE development; roll the breakout back first.")
            return blockers, warnings, info

        # Fingerprints taken by another method than this build's (RUL-fingerprint_method_is_the_builds): geotag
        # compares the fingerprint it takes of a photo with the handoff's, so the two must be of one method.
        blockers.extend(fingerprint_method_blocker(handoff))
        if blockers:
            return blockers, warnings, info

        # A photo prep could not fingerprint (RUL-unfingerprinted_photo_stops_geotag): geotag keeps a photo's
        # original values under its fingerprint before it first writes to it, and checks the fingerprint again
        # before every write — with none, its own values could not be pinned and the check could never pass.
        # Checked at plan, execute and finalize alike: the handoff, not the plan, is what says it.
        unfingerprinted = sorted(rec.get("relative_path") or "" for rec in (handoff.get("files") or [])
                                 if rec.get("folder_class") == by_dest
                                 and rec.get("media_class") in ("image", "raw")
                                 and not _recorded_fingerprint(rec))
        if unfingerprinted:
            blockers.append(f"{len(unfingerprinted)} photo(s) in {by_dest}/ have no content fingerprint — prep "
                            f"could not take one: {_named(unfingerprinted)}. Geotag keeps a photo's own values "
                            "by its fingerprint, so it will not write to one without it. Move them out of "
                            f"{by_dest}/ (or repair them so ImageMagick can read them), then re-run prep — "
                            "`photos-cartographer prep plan` then `photos-cartographer prep execute`.")

        sources = folder_name('sources')
        by_date = folder_name('photos_by_date')

        # 3. Scope gates — at plan, execute and finalize alike (RUL-geotag_gates, BLD-loop_gates).
        if self._entries(sources):
            blockers.append(f"{sources}/ is not empty — prep leaves it empty after every run; an "
                            "unprocessed dump is waiting. Re-run prep to process it: `photos-cartographer prep plan` then `photos-cartographer prep execute`.")

        stray = sorted(rel for rel, mc in self._scan_media(by_date) if mc in ("image", "raw"))
        if stray:
            blockers.append(f"{by_date}/ still contains {len(stray)} photo(s) — finish moving them "
                            f"into {by_dest}/ before geotagging: {_named(stray)}.")

        if nonphoto and for_execute:
            # The leftover of a write this plan makes to a photo is the writer's to judge (BLD-metadata_safe_write,
            # BLD-own_leftover_cleared), not a file put among the photos.
            nonphoto = [(p, mc) for p, mc in nonphoto if not self._planned_write_leftover(p)]
        # Any other leftover of an interrupted metadata write stops the command, named and left where it is — the plan
        # stops on every one: only an execution whose own journal shows it began that write clears one
        # (BLD-own_leftover_cleared).
        leftovers = sorted(p for p, _mc in nonphoto if exiftool_artifact_base(os.path.basename(p)))
        if leftovers:
            blockers.append(f"{len(leftovers)} leftover(s) of an interrupted metadata write in {by_dest}/: "
                            f"{_named(leftovers)}. Geotag clears only the one its own execution left, when that "
                            "execution is resumed (`geotag execute` of the same plan); any other may be the only whole "
                            "copy of something, so it is left where it is — move it out of the workspace, then re-run "
                            "`geotag plan`.")
            nonphoto = [(p, mc) for p, mc in nonphoto if p not in leftovers]
        if nonphoto:
            videos = sorted(p for p, mc in nonphoto if mc == "video")
            others = sorted(p for p, mc in nonphoto if mc != "video")
            parts = []
            if others:
                parts.append(f"{len(others)} non-media file(s): {_named(others)}")
            if videos:
                parts.append(f"{len(videos)} video(s), which belong in {folder_name('videos_by_date')}/: "
                             f"{_named(videos)}")
            blockers.append(f"{by_dest}/ must contain only photos. Found " + " and ".join(parts) +
                            ". Remove or relocate them before geotagging.")

        if for_execute:
            # Execution and finalize work from the plan, which renamed what it renamed: a photo there that neither
            # prep recorded nor the plan names is one sorted since (RUL-geotag_gates). Prep's other checks of its
            # record are the plan's own dependencies here (BLD-loop_gates) — but for its log's mapping of the
            # fingerprints taken again, which neither plan nor execute takes unless one to one
            # (RUL-fingerprint_mapping_one_to_one).
            self._check_unrecorded_at_execute(handoff, by_dest, by_date, blockers)
            problem = self._fingerprint_mapping_problem()
            if problem:
                blockers.append(f"{problem.capitalize()}, which prep never writes: re-run prep — `photos-cartographer "
                                "prep plan` then `photos-cartographer prep execute` — then `geotag plan`.")
            return blockers, warnings, info

        # 4. Re-prep-after-move gate (RUL-prep_records_sort): a prep run must follow the latest by-date→by-dest move.
        self._check_reprep_gate(handoff, by_dest, by_date, blockers)

        # 5. The handoff's camera-group keys and extracted fields must come from this version of
        # cartographer: a key derived the old way would be matched against a config written for the new, and a
        # field set read the old way would be planned from as this one would not read it
        # (RUL-camera_group_derivation_versioned, BLD-handoff_field_set_checked).
        self._check_derivation_versions(handoff, blockers)

        # 5b. A photo whose fingerprint was taken again keeps its pinned values only through a mapping that is
        # one to one; one that is not leaves geotag unable to say whose values are whose
        # (BLD-original_values_follow_fingerprint). A log the handoff does not vouch for says nothing trustworthy
        # of the mapping: the plan stops, as finalize and merge do, rather than plan as though no fingerprint
        # had changed (RUL-geotag_plans_on_vouched_log).
        log_blk = prep_log_blocker(ws, handoff)
        if log_blk:
            blockers.append(f"{log_blk[0].upper() + log_blk[1:]}, then `geotag plan`.")
        else:
            problem = self._fingerprint_mapping_problem()
            if problem:
                blockers.append(f"{problem.capitalize()}, which prep never writes: re-run prep — `photos-cartographer prep plan` then `photos-cartographer prep execute`.")

        # A photo with no recorded time passes here: its folder's date fallback times it, or photos-21 asks for one
        # and geotag stops there (BLD-geotag_untimed_gate).

        info["by_dest_photos"] = sum(1 for _, mc in self._scan_media(by_dest) if mc in ("image", "raw"))
        return blockers, warnings, info

    def _fingerprint_mapping_problem(self):
        """What is wrong with prep's log's mapping of the fingerprints it took again — None where it maps one to one,
        or where there is no log to read (BLD-original_values_follow_fingerprint)."""
        try:
            with open(prep_log_path(self.workspace_root)) as f:
                return retaken_fingerprints(json.load(f))[1]
        except (OSError, ValueError):
            return None

    # --- filesystem helpers --------------------------------------------------

    def _entries(self, rel_folder):
        d = os.path.join(self.workspace_root, rel_folder)
        return sorted(os.listdir(d)) if os.path.isdir(d) else []

    def _scan_media(self, rel_folder):
        """Yield (workspace-relative path, media_class) for non-dot files under rel_folder."""
        base = os.path.join(self.workspace_root, rel_folder)
        if not os.path.isdir(base):
            return
        for root, _dirs, files in os.walk(base):
            for f in files:
                if f.startswith('.'):
                    continue
                rel = os.path.relpath(os.path.join(root, f), self.workspace_root)
                yield rel, media_class_for_ext(os.path.splitext(f)[1])

    def _scan_by_dest(self, by_dest):
        """Return (dev_subfolders_found, non_photo_files, hidden_entries) under 6-photos-by-dest. A hidden entry is any
        file or folder named with a leading dot, at any depth; hidden folders are still walked."""
        # matched case folded: `JPG/` is the breakout as much as `jpg/` (BLD-development_subfolder_case)
        dev_names = {n.casefold() for n in CONFIG.get("destination_distribution_subfolders") or []}
        base = os.path.join(self.workspace_root, by_dest)
        dev_found, nonphoto, hidden = [], [], []
        if not os.path.isdir(base):
            return dev_found, nonphoto, hidden
        for root, dirs, files in os.walk(base):
            for d in dirs:
                if d.casefold() in dev_names:
                    dev_found.append(os.path.relpath(os.path.join(root, d), self.workspace_root))
                if d.startswith('.'):
                    hidden.append(os.path.relpath(os.path.join(root, d), self.workspace_root))
            for f in files:
                if f.startswith('.'):
                    hidden.append(os.path.relpath(os.path.join(root, f), self.workspace_root))
                    continue
                mc = media_class_for_ext(os.path.splitext(f)[1])
                if mc not in ("image", "raw"):
                    nonphoto.append((os.path.relpath(os.path.join(root, f), self.workspace_root), mc))
        return sorted(dev_found), nonphoto, sorted(hidden)

    def _check_reprep_gate(self, handoff, by_dest, by_date, blockers):
        # Shared with prep's nothing-to-do guard so the two never disagree on whether a move is pending.
        from .photos_utils import by_dest_reprep_pending
        ex = by_dest_reprep_pending(self.workspace_root, handoff)
        if ex:
            # One message for a photo moved in, removed or changed: the remedy is the same re-prep.
            blockers.append(
                f"Prep's record of {by_dest} is out of date — a photo was moved there from {by_date}, or "
                f"one it recorded has since been removed or changed (e.g. {ex}). Re-run prep to record "
                "it and refresh the handoff: run `photos-cartographer prep plan` then "
                "`photos-cartographer prep execute`. Then geotag can proceed.")

    def _planned_paths(self):
        """(written, named, written_named) from photos-24: the workspace-relative paths of the photos its operations
        write, every name its renames give a photo — the final name and a case change's temporary one — and those of
        them given to a photo it writes. None when there is no readable plan: execute and finalize then stop on that
        themselves (BLD-unreadable_plan)."""
        if not hasattr(self, "_planned_paths_memo"):
            try:
                plan = read_executable_plan(self.workspace_root)
            except UnreadablePlan:
                plan = None
            if not isinstance(plan, dict):
                self._planned_paths_memo = None
            else:
                written, names = set(), {}
                for d in (plan.get("destinations") or {}).values():
                    for op in (d.get("operations") or []) if isinstance(d, dict) else []:
                        rel = op.get("relative_path") if isinstance(op, dict) else None
                        if not isinstance(rel, str):
                            continue
                        if op.get("type") == "rename_no_clobber":
                            for key in ("to", "via"):
                                if isinstance(op.get(key), str):
                                    names.setdefault(rel, set()).add(os.path.join(os.path.dirname(rel), op[key]))
                        else:
                            written.add(rel)        # a rename writes nothing: no leftover beside it is its own
                named = {n for ns in names.values() for n in ns}
                written_named = {n for rel in written for n in names.get(rel, ())}
                self._planned_paths_memo = (written, named, written_named)
        return self._planned_paths_memo

    def _planned_write_leftover(self, rel):
        """Whether `rel` is `<photo>_exiftool_tmp` beside a photo the plan writes, under its name before or after
        the plan's rename (BLD-metadata_safe_write)."""
        base = exiftool_artifact_base(os.path.basename(rel))
        paths = self._planned_paths() if base else None
        if not paths:
            return False
        photo = os.path.join(os.path.dirname(rel), base)
        return photo in paths[0] or photo in paths[2]

    def _check_unrecorded_at_execute(self, handoff, by_dest, by_date, blockers):
        """At execute and finalize: a photo in photos by destination that prep's handoff does not record and the
        plan's renames do not name was sorted there since — the gate that prep has recorded every photo there
        (RUL-geotag_gates, BLD-loop_gates). Skipped with no readable plan, which stops the command anyway."""
        paths = self._planned_paths()
        if paths is None:
            return
        recorded = {f.get("relative_path") for f in (handoff.get("files") or [])} | paths[1]
        unrecorded = sorted(rel for rel, mc in self._scan_media(by_dest)
                            if mc in ("image", "raw") and rel not in recorded)
        if unrecorded:
            blockers.append(
                f"Prep's record of {by_dest} is out of date — {len(unrecorded)} photo(s) were put there since the "
                f"plan was made: {_named(unrecorded)}. Move them back to {by_date}/, or re-run prep to record "
                "them (`photos-cartographer prep plan` then `photos-cartographer prep execute`) and then "
                "`geotag plan`.")

    @staticmethod
    def _check_derivation_versions(handoff, blockers):
        by_dest = folder_name('photos_by_dest')
        # a photo there whose record holds no metadata at all cannot be checked: it counts as another version's
        # (RUL-unchecked_counts_as_changed, RUL-handoff_fields_of_this_build)
        unchecked = lambda rec: rec.get("folder_class") == by_dest and rec.get("media_class") in ("image", "raw") \
            and not isinstance(rec.get("metadata_status"), dict)
        for field, current, what in (("camera_group_key_version", CAMERA_GROUP_KEY_VERSION, "camera-group keys"),
                                     ("field_set_version", FIELD_SET_VERSION, "metadata fields")):
            other = sorted(rec.get("relative_path") or "" for rec in (handoff.get("files") or [])
                           if unchecked(rec) or (isinstance(rec.get("metadata_status"), dict)
                                                 and rec["metadata_status"]
                                                 and rec["metadata_status"].get(field) != current))
            if other:
                blockers.append(
                    f"The handoff's {what} were derived by another version of cartographer "
                    f"({len(other)} file(s), e.g. {other[0]}; this version is {current}). Re-run prep "
                    "to derive them again: `photos-cartographer prep plan` then `photos-cartographer prep execute`.")

    # --- Stage 2: in-memory by-dest file model (BLD-geotag_file_model) ---

    def _retaken(self):
        """{new: old} fingerprint values from prep's log — only one the handoff vouches for, and only one to
        one — so a photo whose fingerprint a new ImageMagick changed keeps its pinned values
        (BLD-original_values_follow_fingerprint)."""
        if not self.handoff or prep_log_blocker(self.workspace_root, self.handoff):
            return {}
        try:
            with open(prep_log_path(self.workspace_root)) as f:
                earlier, _problem = retaken_fingerprints(json.load(f))
        except (OSError, ValueError):
            return {}
        return earlier

    def build_file_model(self, prior_time=None):
        """One object per by-dest photo, built from the handoff's records (+ the EXIF prep already
        extracted into metadata_status.parsed_json). Geotag never re-reads the file — a stale
        handoff was already blocked (BLD-reprep_pending). Given the prior photos-21, a photo holding a time changed
        since geotag wrote it carries the user's answer there (`changed_time`, BLD-changed_time_question); one kept, or
        whose pin keeps a true time (BLD-changed_time_kept_pinned), is decided from that time as its true local time
        (BLD-changed_time_kept)."""
        answers = _changed_time_answers(prior_time)
        by_dest = folder_name('photos_by_dest')
        files = []
        cache = GeotagCache(self.workspace_root)
        try:
            originals, written = cache.originals_all(), cache.times_written_all()
        finally:
            cache.close()
        earlier = self._retaken()
        for rec in (self.handoff.get("files") or []):
            if rec.get("folder_class") != by_dest or rec.get("media_class") not in ("image", "raw"):
                continue
            md = rec.get("metadata_status") or {}
            parsed = _parsed_record(rec)
            fp = _recorded_fingerprint(rec)   # the preflight stops on a photo without one
            rel = rec.get("relative_path")
            # its own position, by the one test (BLD-own_position_test): latitude 0 and longitude 0 is none
            own_gps = has_own_position(parsed.get("GPSLatitude"), parsed.get("GPSLongitude"))
            held_gps = parsed.get("GPSLatitude") is not None and parsed.get("GPSLongitude") is not None
            files.append({
                "relative_path": rel,
                "destination": os.path.dirname(rel),         # immediate containing folder (BLD-geotag_destinations)
                "size": rec.get("size"),
                "mtime_ns": rec.get("mtime_ns"),
                "content_fingerprint": fp,
                "media_class": rec.get("media_class"),
                "camera_group_key": md.get("camera_group_key") or parsed.get("camera_group_key") or NO_IDENTITY_KEY,
                "source_naive_time": parsed.get("selected_source_naive_timestamp"),
                "source_time_tag": parsed.get("selected_source_timestamp_tag"),
                # the fraction of a second it records: the order of a burst's names (RUL-suffix_in_capture_order)
                "sub_second": recorded_sub_second(parsed),
                "raw_times": {k: parsed.get(k) for k in
                              ("DateTimeOriginal", "CreateDate", "ModifyDate",
                               "OffsetTimeOriginal", "OffsetTimeDigitized", "OffsetTime", "TimeZone")
                              if parsed.get(k) is not None},
                "has_timestamp": _has_recorded_time(rec),
                # what the file holds — a position that is none included, for the comparison and the log
                "native_gps": ({"lat": parsed.get("GPSLatitude"), "lon": parsed.get("GPSLongitude"),
                                "processing_method": parsed.get("GPSProcessingMethod")}
                               if held_gps else None),
                # A position geotag wrote is not the file's own: a re-run places the file again.
                "has_native_gps": own_gps
                                  and geotag_marker(parsed.get("GPSProcessingMethod")) not in POSITION_MARKERS,
                # the UTC its own GPS fix recorded: evidence of the clock (BLD-gps_time_proposal)
                "gps_utc": gps_fix_utc(parsed) if own_gps else None,
                "geotag_marker": geotag_marker(parsed.get("GPSProcessingMethod")),
                "processing_method": parsed.get("GPSProcessingMethod"),   # the value a time mark extends
                "other_times": held_other_times(parsed),     # what a time write rewrites (BLD-other_time_fields_written)
                "own_values": own_values(dict(parsed, has_native_gps=own_gps)),
                "metadata_field_set_version": md.get("field_set_version"),
                "folder_class": rec.get("folder_class"),
                "planned_filename": None,                    # set during the rename lookahead (Phase 6)
            })
            # every value the photo's fingerprint had before it was taken again, latest first: a decision made for
            # it under any of them is still its own (RUL-photo_decision_follows_the_photo) — a photo geotag never
            # wrote, and so never pinned, included
            chain, link = [], earlier.get(fp)
            while link is not None and link != fp and link not in chain:
                chain.append(link)
                link = earlier.get(link)
            files[-1]["earlier_fingerprints"] = chain
            key, walked = fp, set()
            # a fingerprint taken again: the pin before it. One taken back to a value it had before ends
            # the walk where it started.
            while key is not None and key not in originals and key not in walked:
                walked.add(key)
                key = earlier.get(key)
            if key in walked:
                key = None
            if key is not None:                        # decide from the file's own values (BLD-decided_from_own_values)
                files[-1] = dict(from_originals(files[-1], originals[key]), original_key=key,
                                 times_written=written.get(key) or [])   # the times geotag wrote (BLD-time_written_recorded)
                if isinstance(originals[key].get("true_time"), dict):
                    # a time the user kept on an earlier pass: its true local time from then on — while their answer
                    # stands. Withdrawn in photos-21, it is decided from as such no longer: the photo's time is asked
                    # about again, nothing written back until answered (BLD-changed_time_kept_pinned)
                    # Withdrawn: the answer for the kept time no longer "new", or cleared — not an answer about a time
                    # changed again since, which names that time
                    kept = {k: originals[key]["true_time"].get(k) for k in TIME_PAIR}
                    standing = _earlier_decision(answers, files[-1]).get("user_decision")
                    standing = standing if isinstance(standing, dict) else None
                    if standing is not None and standing.get("keep") != "new" \
                            and standing.get("answered_for") in ("", None, kept):
                        files[-1]["kept_time_withdrawn"] = dict(originals[key]["true_time"])
                    else:
                        files[-1] = dict(keep_true_time(files[-1], originals[key]["true_time"]),
                                         kept_from_pin=dict(originals[key]["true_time"]))
                ch = changed_time(files[-1])
                if ch is not None:
                    # its time changed since geotag wrote it: the user's answer, found by its fingerprint
                    ud = _earlier_decision(answers, files[-1]).get("user_decision")
                    answer = _changed_time_answer(ud if isinstance(ud, dict) else {}, ch)
                    if answer == "new":
                        # kept: the photo's true local time (BLD-changed_time_kept), its pin's at execution
                        files[-1] = dict(keep_true_time(files[-1], ch["held_time"]), time_kept=dict(ch["held_time"]))
                    files[-1]["changed_time"] = dict(ch, answer=answer)
            # a time read from ModifyDate is no camera's clock: solved on its own (BLD-modified_time_files)
            files[-1]["camera_group_key"] = clock_group_key(files[-1])
        files.sort(key=lambda f: f["relative_path"])
        return files

    # --- Stage 3: GPX index (BLD-track_points) ---------------------------

    def load_gpx(self, files):
        """The tracks in the window the photos' camera times reach (BLD-track_window), catalogued and kept in the
        record (BLD-track_catalogue)."""
        idx = GPXIndex(selected_gpx_root(), db_path(self.workspace_root), CONFIG["gpx_track_precedence"])
        idx.build(self.coordinator, window=self.camera_window(files))
        self._gpx_fingerprint = idx.fingerprint
        self.planned_tracks = idx         # pruned to its window once the planning has stopped (BLD-track_catalogue)
        return idx

    def widen_tracks(self, gpx, spans):
        """Grow the tracks' window by `spans` (BLD-track_window): a track file whose span meets the new part is read
        again. The fingerprint is then of the wider window's points."""
        wider = window_union(gpx.window, spans)
        if wider != gpx.window:
            gpx.build(self.coordinator, window=wider)
            self._gpx_fingerprint = gpx.fingerprint
        return gpx

    def plan_tracks(self, plan, keep=False, read=True):
        """The tracks in the window `plan` was made in, as they are now (`read`) or as the record keeps them —
        none when the plan records no window, which `revalidate_plan` then finds stale (BLD-track_window)."""
        window = valid_window(((plan or {}).get("depends_on") or {}).get("gpx_window"))
        idx = GPXIndex(selected_gpx_root(), db_path(self.workspace_root), CONFIG["gpx_track_precedence"])
        return idx.build(self.coordinator, window=window or [], keep=keep, read=read)

    @staticmethod
    def camera_window(files):
        """The tracks' window before any time is corrected (BLD-track_window): each photo's camera time, read as UTC,
        give or take how far anchoring reaches — `gpx_anchor_max_clock_error_seconds`, and from a candidate there
        the placement a higher-ranked track would cover it by — and each camera day's photos, from the first to
        the last, give or take `drift_check_track_window_seconds`, where the drift check falls back to them."""
        reach = CONFIG["gpx_anchor_max_clock_error_seconds"] + max(CONFIG["gpx_direct_match_max_seconds"],
                                                                   CONFIG["gpx_interpolation_max_gap_seconds"])
        drift = _drift_reach()
        spans, days = [], {}
        for f in files:
            t = _parse_camera_naive(f.get("source_naive_time"))
            if t is None:
                continue
            t = t.replace(tzinfo=timezone.utc)
            spans.append(around(t, reach))
            key = (f["destination"], f["camera_group_key"], t.date())
            lo, hi = days.get(key, (t, t))
            days[key] = (min(lo, t), max(hi, t))
        spans.extend((around(lo, drift)[0], around(hi, drift)[1]) for lo, hi in days.values())
        return window_union(spans)

    def drift_window(self, files, time_artifact, rows0):
        """What the drift check reaches past the camera window (BLD-track_window): each bucket's photos at their
        corrected times, from the first to the last, give or take what the drift check reaches (_drift_reach)."""
        drift = _drift_reach()
        return [(around(min(times), drift)[0], around(max(times), drift)[1])
                for _dest, _bucket, _cell, _frames, times in self._drift_cases(files, time_artifact, rows0) if times]

    @staticmethod
    def placement_window(files, rows, contradicted=()):
        """What placement reaches (BLD-track_window): each photo it places, at its corrected time, give or take the
        farthest a point can lie that places it — the direct match, the interpolation gap, or the extrapolation
        reach and the stretch its heading is taken over."""
        reach = _placement_reach()
        # a photo's own position is set against the tracks only where its offset contradicts it
        # (BLD-contradicted_position)
        native = {f["relative_path"] for f in files if f.get("has_native_gps")} - set(contradicted)
        # a time a date fallback gave is no time the tracks place by (RUL-date_fallback_never_placed_by_tracks)
        native |= {f["relative_path"] for f in files if untimed(f)}
        return [around(t, reach) for r in rows if r["resolved_utc_status"] == "valid"
                and r["relative_path"] not in native and (t := _parse_utc(r["resolved_utc"]))]

    # --- Stage 4: camera-group recognition + classification (BLD-known_camera_group) ---

    def recognize_camera_groups(self, files):
        """Group the file objects by camera_group_key and classify each via config device_groups.
        Returns (groups_by_key, unknown_keys), each group holding its key and `camera_group_class`. A key
        listed in `phones` is a smartphone (solved per-file); in `fixed_clock_cameras` a camera (needs a
        per-(group, destination, day) offset); otherwise it is unknown and must be classified before geotag.
        The class is all geotag needs of a group: its facts — files, span, positions — are prep's to report,
        in the handoff's `camera_groups`."""
        policy = CONFIG.get("camera_time_and_timezone_policy") or {}
        dg = policy.get("device_groups") or {}
        several = set(policy.get("several_bodies_groups") or [])
        groups = {}
        for key in sorted({f["camera_group_key"] for f in files}):
            groups[key] = {"camera_group_key": key, "camera_group_class": camera_group_class(key, dg)}
            if key in several and groups[key]["camera_group_class"] == "camera":
                # the configuration says this group is several bodies of one model (BLD-several_bodies_groups)
                groups[key]["several_bodies"] = True
        unknown = [k for k, g in groups.items() if g["camera_group_class"] == "unknown"]
        return groups, unknown

    # --- Stages 5–6: time decisions (photos-21, BLD-timezone_cell, BLD-offset_buckets) ---------------------

    # How many passes over photos-21 the tracks' window may grow by before it stands (BLD-track_window).
    _TIME_WINDOW_PASSES = 4

    def build_time_decisions(self, files, groups, prior, gpx):
        """Build/regenerate the photos-21 content: per-destination civil timezone (BLD-timezone_cell) + per-
        (camera group, destination) clock-offset cells (BLD-offset_buckets), through the decision-field /
        auto-resolution / rerun-preservation engine (RUL-decision_kept). The offset cell's proposal is the
        GPX self-anchor (BLD-anchor_matching) when one can be inferred (else manual-required). Returns (artifact,
        blockers); blockers come from sanity-validating preserved authored values (RUL-invalid_decision_kept) and mean
        "do not overwrite — fix first".

        A proposal that is not the camera's own GPS's is set against the tracks at the times it corrects the photos
        to — the far-from-evidence check, and whether a guess goes to the drift check — which an offset of hours
        carries past the camera window: the tracks are widened over those times and the record made again, until the
        window stands (BLD-track_window, RUL-track_window_reaches_every_reader)."""
        for _ in range(self._TIME_WINDOW_PASSES):
            artifact, blockers = self._time_decisions_pass(files, groups, prior, gpx)
            if artifact is None or not gpx.gpx_root or gpx.status not in ("usable", "empty"):
                break
            before = list(gpx.window)
            self.widen_tracks(gpx, self._guess_spans)
            if gpx.window == before:
                break
        return artifact, blockers

    def _time_decisions_pass(self, files, groups, prior, gpx):
        """One pass of build_time_decisions over the tracks' window as it is."""
        blockers = _decision_shape_blockers(prior, "time")
        if blockers:
            return None, blockers
        prior_dests = ((prior or {}).get("destinations")) or {}
        by_dest = {}
        for f in files:
            by_dest.setdefault(f["destination"], []).append(f)

        destinations = {}
        # Process destinations PARENT-FIRST so an ancestor's effective TIMEZONE is known before a child
        # inherits it (RUL-timezone_from_nearest). `eff_tz` maps (destination, "tz") -> resolved effective timezone.
        # Clock offsets do NOT inherit from the destination above (RUL-offset_from_own_evidence): each (group, date)
        # bucket proposes its own, or takes the one the camera's own positions gave that day in another destination
        # (RUL-offset_shared_within_day).
        eff_tz = {}
        # The date fallback in effect at each destination, given there or at the nearest one above it
        # (RUL-date_fallback_from_nearest): (destination, "date") -> {"date", "filled", "set_at"}.
        eff_date = {}
        recall = {}                                  # (destination, bucket) -> what its cell was built from
        # A country is chosen once, at the top of its tree (RUL-country_chosen_once): `eff_country` maps a destination
        # to (code, the destination it was chosen at) for itself and everything inside it.
        eff_country, table = {}, country_table(self.workspace_root)
        self.country_removals = []
        self.fingerprints_here = {}
        # where a zone written above stops reaching down: a folder with a zone written, or a country chosen
        # (RUL-zone_asked_at_every_level)
        zone_stops = set()
        self.unreadable_offset_tags = []
        self.kept_tag_disagreements = []
        ordered, containers = _expand_destinations(by_dest)
        self.coordinator.start_phase("calibrating clock offsets", len(ordered))
        for dest in ordered:
            self.coordinator.set_detail(_dest_label(dest))   # name the destination so heavy ones are visible
            is_container = dest in containers       # a file-less folder: holds a timezone/fallback, no offsets
            prior_d = prior_dests.get(dest, {})
            inherited_tz = _nearest_ancestor(dest, eff_tz, "tz")        # confirmable basis if no default
            waits_at = None
            if inherited_tz is not None and inherited_tz[1] is _ZONE_WAITS:
                waits_at = inherited_tz[0]
                inherited_tz = None                 # the destination above waits on its own photos: so does this
            prior_ud = (prior_d.get("destination_timezone") or {}).get("user_decision") or {}
            own_country, removed = prior_ud.get("country", ""), None
            own_country = "" if own_country is None else own_country
            if not isinstance(own_country, str):
                # A value that is not a country's code at all — a list, a number, false — is named like any other the
                # user wrote that cannot be taken, never read as no answer (RUL-checked_shapes).
                blockers.append(f"{dest}: destination_timezone.user_decision.country must be a country's code "
                                f"written as text, not {own_country!r}")
                own_country = ""
            above = next((eff_country[a] for a in _walk_ancestors(dest) if a in eff_country), None)
            if own_country and above:
                # What lies inside a destination is in that destination's country: the one said above stands, this one is taken out
                # of the decision — said aloud, and left in the record of this run.
                removed = {"country": own_country, "because": above[1], "country_there": above[0]}
                self.country_removals.append(dict(removed, destination=dest))
                own_country = ""
            if own_country and own_country not in table:
                blockers.append(f"{dest}: destination_timezone.user_decision.country {own_country!r} is not a "
                                + ("country code of the zone database (two letters, such as \"US\")." if table else
                                   "choice this host can read: its zone database knows no zone of the table of "
                                   "countries."))
                own_country = ""
            country = (own_country, dest) if own_country else above
            if country:
                eff_country[dest] = country
            zones = table.get(country[0], {}).get("zones", []) if country else []
            if len(zones) == 1 and not (waits_at and country[1] != dest
                                        and (waits_at == country[1] or waits_at.startswith(country[1] + "/"))):
                # a country of one timezone: that is the zone — as an inherited zone, it stops at a destination
                # within the country whose own photos speak against it (RUL-inherited_zone_stops_within)
                inherited_tz = (country[1], zones[0])
            elif zones and inherited_tz is not None and (own_country or inherited_tz[1] not in zones):
                inherited_tz = None                         # a zone from above the country is none of its own
            # in a country of several timezones, with none reaching it, the one zone of the country its photos'
            # recorded offsets fit (BLD-zone_from_photos_in_country)
            fitted = (_zone_from_photos(by_dest[dest], groups, zones)
                      if len(zones) > 1 and inherited_tz is None and not is_container else None)
            # A destination holding photos has one timezone for all of them (RUL-inherited_timezone_yields_to_photos):
            # the zone it would take — the one written for it, else the one it inherits — is set against what its own
            # photos record.
            written = prior_ud.get("manual_iana_timezone")
            written = written if isinstance(written, str) else None     # one not text is a blocker below
            candidate = written if written and _valid_iana(written) else (inherited_tz[1] if inherited_tz else None)
            against = _offsets_against_zone(by_dest[dest], groups, candidate) if candidate and not is_container else None
            if written or own_country:
                zone_stops.add(dest)
            tz_block = self._timezone_decision(dest, prior_d.get("destination_timezone") or {},
                                               blockers, inherited_tz, file_less=is_container, against=against,
                                               country=country, zones=zones, own_country=own_country,
                                               removed=removed, fitted=fitted)
            # what children inherit: the zone in effect; or, where this destination's own photos speak
            # against the zone it would inherit and the user has not answered, that it waits — a
            # destination inside it does not reach past it to the zone its photos contradict
            eff_tz[(dest, "tz")] = tz_block["effective_iana_timezone"] or (_ZONE_WAITS if against else None)
            if tz_block["effective_iana_timezone"] == "" and against:
                tz_block["requires_user_input"] = True
            if own_country and len(zones) > 1:
                # A country of several timezones gives none to what lies inside it, whatever zone its own
                # photos are in, and lets none through from above: each destination below answers for itself.
                eff_tz[(dest, "tz")] = _ZONE_WAITS
            tz = tz_block["effective_iana_timezone"] or None
            date_cell = self._date_fallback_cell(dest, prior_d.get("date_fallback") or {},
                                                 _nearest_ancestor(dest, eff_date, "date"),
                                                 [] if is_container else by_dest[dest], blockers)
            eff_date[(dest, "date")] = date_cell["effective_date"]
            prior_cells = prior_d.get("camera_group_time_decisions") or {}
            cells = {}
            # Containers hold no media → no offset cells. A real destination gets one offset cell per
            # camera group, SPLIT per naive calendar date when the group spans >1 day there (BLD-offset_buckets): the
            # camera is set to local time each morning, so the offset is constant only within a day. The
            # bucket key is the bare group for a single day, else `<group>@<YYYY-MM-DD>`.
            for group in (sorted({f["camera_group_key"] for f in by_dest[dest]}) if not is_container else []):
                g = groups.get(group) or {}
                phone = g.get("camera_group_class") == "smartphone"
                if g.get("camera_group_class") != "camera" and not phone:
                    continue                       # a file naming no camera is solved on its own; no offset cell
                # Days are counted over every photo of the group here, corrected ones too, so a bucket keeps
                # its key as photos arrive; only the photos not yet corrected are asked about or offset.
                gframes = [f for f in by_dest[dest] if f["camera_group_key"] == group]
                self.fingerprints_here[(dest, group)] = {fp for f in gframes if (fp := f.get("content_fingerprint"))}
                dates = sorted({d for f in gframes if (d := _naive_date(f.get("source_naive_time")))})
                for date in (dates if len(dates) > 1 else [None]):
                    # a time the user kept as the true one is no reading of the camera's clock
                    # (BLD-changed_time_kept_not_anchor)
                    sel = [f for f in gframes if not f.get("geotag_marker") and not f.get("true_time")
                           and (date is None or _naive_date(f.get("source_naive_time")) == date)]
                    bucket = group if date is None else f"{group}@{date}"
                    day = date or (dates[0] if dates else None)
                    prior_cell = _prior_day_cell(prior_cells, group, bucket, day)
                    if phone:
                        # A phone's day here has a cell only where its own GPS, or what it does not record, asks
                        # one (BLD-phone_offset_cell); its photos are read by their own offsets otherwise.
                        built = self._phone_cell(dest, group, g, prior_cell, sel, gpx, blockers, tz, date, day)
                        if built is not None:
                            cells[bucket], recall_entry = built
                            if recall_entry is not None:
                                recall[(dest, bucket)] = recall_entry
                        continue
                    if not sel:
                        # Every time here is corrected already and none has its own values pinned (a photo
                        # geotag marked elsewhere), or was kept as the true one, so nothing asks. A resolved
                        # answer is kept for photos of the same camera and day arriving later — derived again from the decision, never
                        # copied, so the record always says what the decision now says.
                        if prior_cell:
                            cell = self._offset_cell(dest, group, g, prior_cell, [], gpx, blockers,
                                                     tz=tz, rep_naive=None, date=date, day=day)
                            if cell["effective_time_anchor"]:
                                cell["requires_user_input"] = False
                                cells[bucket] = cell
                        continue
                    anchor_frames = [f for f in sel if f.get("has_native_gps")]
                    rep_naive = min((f.get("source_naive_time") for f in sel
                                     if _parse_camera_naive(f.get("source_naive_time"))), default=None)
                    cells[bucket] = self._offset_cell(dest, group, g, prior_cell,
                                                      anchor_frames, gpx, blockers, tz=tz, rep_naive=rep_naive,
                                                      date=date, day=day, photos=sel)
                    recall[(dest, bucket)] = (group, g, prior_cell, anchor_frames, rep_naive, date, day, sel, tz)
                    # A camera's clock changed during the day (BLD-clock_change_split): proposed from its own GPS, and,
                    # accepted, the day split at the change into parts — never for a group of several bodies, whose
                    # bodies are told apart by their destinations (RUL-several_bodies_no_clock_change_split).
                    if not g.get("several_bodies"):
                        parts = self._clock_change(dest, group, g, bucket, cells[bucket], prior_cell, anchor_frames,
                                                   sel, gpx, blockers, tz, date, day)
                        if parts:
                            cells.update(parts)
                            recall.pop((dest, bucket), None)     # decided by its parts: shared with no other day
            destinations[dest] = {
                "destination_path": dest,
                "destination_timezone": tz_block,
                "date_fallback": date_cell,
                "camera_group_time_decisions": cells,
            }
            if is_container:
                destinations[dest]["file_less"] = True
            else:
                # an offset tag holding no offset is read as none — named, and kept in the record
                # (BLD-unreadable_offset_tags)
                bad = [{"relative_path": f["relative_path"], "field": u[0], "value": u[1]}
                       for f in sorted(by_dest[dest], key=lambda x: x["relative_path"])
                       if not f.get("geotag_marker") and not f.get("true_time") and (u := unreadable_offset_tag(f))]
                if bad:
                    destinations[dest]["unreadable_offset_tags"] = bad
                    self.unreadable_offset_tags.extend(bad)
                # files naming no camera and recording no offset: one question for the destination
                # (BLD-unidentified_files_question)
                nameless = [f for f in by_dest[dest] if not f.get("geotag_marker") and not f.get("true_time")
                            and (groups.get(f["camera_group_key"]) or {}).get("camera_group_class") == "unidentified"
                            and _parse_camera_naive(f.get("source_naive_time")) and _own_offset(f) is None]
                if nameless:
                    destinations[dest]["unidentified_files"] = self._unidentified_cell(
                        dest, nameless, tz, prior_d.get("unidentified_files") or {}, blockers)
            self.coordinator.increment_completed(1)
        _ask_zone_at_containers(destinations, containers, zone_stops)
        self._share_offsets_within_a_day(destinations, recall, gpx, blockers)
        # the offsets the photos' own fixes gave are judged before a neighbour day is offered one, so no day is
        # offered an offset this pass withdraws (BLD-neighbour_day_proposal); the guesses after
        self._withhold_far_offsets(destinations, recall, by_dest, groups, gpx, fixes=True)
        self._offer_neighbour_days(destinations, recall, gpx, blockers)
        self._withhold_far_offsets(destinations, recall, by_dest, groups, gpx, fixes=False)
        self._ask_local_time_readings(destinations, by_dest, groups, prior_dests, blockers)
        self._ask_changed_times(destinations, by_dest, prior_dests, blockers)
        self.coordinator.finish_phase()
        self._guess_spans = self._guess_window(destinations, recall)

        requires = (any(d["destination_timezone"]["requires_user_input"] for d in destinations.values())
                    or any(c["requires_user_input"] for d in destinations.values()
                           for c in d["camera_group_time_decisions"].values())
                    or any(c["requires_user_input"] for d in destinations.values()
                           for c in (d.get("local_time_readings") or {}).values())
                    or any(c["requires_user_input"] for d in destinations.values()
                           for c in (d.get("changed_times") or {}).values())
                    or any((d.get("unidentified_files") or {}).get("requires_user_input") for d in destinations.values())
                    or any(d["date_fallback"]["requires_user_input"] for d in destinations.values()))
        artifact = {
            "artifact_type": "time_decisions",
            "artifact_name": TIME_DECISIONS_ARTIFACT,
            "status": "requires_user_input" if requires else "complete",
            "requires_user_input": requires,
            "executable": False,
            "destinations": destinations,
            "depends_on": self._time_depends_on(),
            # the countries a destination can be said to lie in, with their timezones, as the zone database
            # this run read has them: what a choice of country was made from, and rested on
            "countries": table,
        }
        if not requires:
            artifact["decision_mode"] = "no_op_or_auto_resolved"
        return artifact, blockers

    def _date_fallback_cell(self, dest, prior_df, inherited, files, blockers):
        """A destination's `date_fallback` cell in photos-21 (BLD-date_fallback_cell): the date the user gave it —
        `user_decision.date`, a year, a year and month or a day, checked (RUL-date_fallback_checked) — else the one in
        effect at the nearest destination above it (`inherited`, (path, effective)), taking effect unasked
        (RUL-date_fallback_from_nearest); its photos with no recorded time (`untimed_photos`); and, where one of
        them is there and no date is in effect, a question (RUL-untimed_photo_stops_geotag)."""
        ud = prior_df.get("user_decision") or {}
        given = ud.get("date", "")
        given = "" if given is None else given
        effective = None
        if given != "":
            day = date_fallback_day(given)
            if day is None:
                blockers.append(f"{dest}: date_fallback.user_decision.date {given!r} is not a date — write a year "
                                "(\"1985\"), a year and month (\"1985-06\") or a day (\"1985-06-14\").")
            else:
                effective = {"date": given, "filled": day.strftime("%Y-%m-%d"), "set_at": dest}
        elif inherited is not None:
            effective = dict(inherited[1])
        cell = {"user_decision": {"date": given}, "effective_date": effective}
        if inherited is not None:
            cell["inherited_from"] = inherited[0]
        here = sorted(f["relative_path"] for f in files if untimed(f))
        if here:
            cell["untimed_photos"] = here
        cell["requires_user_input"] = bool(here) and effective is None
        cell["stale_user_decision"] = False
        return cell

    def _clock_change(self, dest, group, g, bucket, cell, prior_cell, frames, sel, gpx, blockers, tz, date, day):
        """A change of the camera's clock during its day here (BLD-clock_change_split), on the day's cell `cell`: the
        proposal `clock_change_proposal` makes from the photos' own GPS, recorded as `clock_change`, and the user's
        answer — `accept_clock_change`, `accepted_change_offsets_seconds` (the two offsets accepted, in order) and, for
        each photo the runs leave unsettled, `photo_parts` (by its source file: 1 or 2, the part it belongs to). Accepted
        while the two runs' offsets are those accepted, within `gpx_anchor_decision_tolerance_seconds`, and every
        unsettled photo given its part, the day is split into its parts, returned as {key: cell} — `<bucket>#1` before
        the change and `<bucket>#2` after it — each built from its own photos, its offset the one accepted for its run;
        the day's cell asking nothing, its photos read by the parts (`offset_cell_key`). Else None, the day's cell as
        built — asking the part of each unsettled photo not given one."""
        found = clock_change_proposal(frames, sel, gpx, CONFIG)
        change, settled = found if found is not None else (None, {})
        ud = prior_cell.get("user_decision") if isinstance(prior_cell.get("user_decision"), dict) else {}
        if change is None and not any(k in ud for k in CLOCK_CHANGE_FIELDS):
            return None
        where = f"{dest}: camera_group_time_decisions[{bucket}].user_decision"
        accept = _decision_flag(ud, "accept_clock_change", where, blockers)
        offs = ud.get("accepted_change_offsets_seconds", "")
        offs = "" if offs is None else offs
        answers = ud.get("photo_parts", {})
        answers = {} if answers in (None, "") else answers
        now =(" — the ones now proposed are " + " and ".join(str(r["offset_seconds"]) for r in change["runs"]) + "."
               if change else "; no change is proposed now, so clear accept_clock_change.")
        if offs != "" and not (isinstance(offs, list) and len(offs) == 2
                               and all(_valid_offset(o) and not isinstance(o, bool) for o in offs)):
            blockers.append(f"{where}.accepted_change_offsets_seconds must be the two offsets accepted, in order, as "
                            "whole numbers of seconds" + now)
            offs = ""
        elif accept and offs == "":
            blockers.append(f"{where}.accepted_change_offsets_seconds must be the two offsets accepted" + now)
        if not (isinstance(answers, dict) and all(isinstance(k, str) and v in (1, 2) and not isinstance(v, bool)
                                                  for k, v in answers.items())):
            blockers.append(f"{where}.photo_parts must give each photo, by its source file, the part it belongs to: "
                            "1 (before the change) or 2 (after it).")
            answers = {}
        cell["user_decision"].update(accept_clock_change=accept, accepted_change_offsets_seconds=offs,
                                     photo_parts=answers)
        if change is not None:
            cell["clock_change"] = change
        if not accept or offs == "":
            return None
        tolerance = CONFIG["gpx_anchor_decision_tolerance_seconds"]
        if change is None or any(abs(int(o) - r["offset_seconds"]) > tolerance for o, r in zip(offs, change["runs"])):
            cell["stale_user_decision"] = True      # accepted a change that is no longer the one proposed
            return None
        if ud.get("manual_offset_seconds") not in ("", None):
            return None                             # one offset written for the whole day outranks the change
        # a photo with no evidence of its own that either part could have taken — a clock set back repeats camera
        # times — or neither: its part is the user's to say (RUL-clock_change_unsettled_photo_asked)
        if any(answers.get(p["source_file"]) not in (1, 2) for p in change["unsettled"]):
            cell["effective_time_anchor"], cell["requires_user_input"] = "", True
            cell.pop("decision_mode", None)
            return None
        photo_parts = dict(settled, **{p["source_file"]: answers[p["source_file"]] for p in change["unsettled"]})
        keys = [f"{bucket}#1", f"{bucket}#2"]
        parts = {}
        for i, key in enumerate(keys):
            psel = [f for f in sel if photo_parts.get(f["relative_path"]) == i + 1]
            rep = min((f.get("source_naive_time") for f in psel), default=None)
            accepted = {"user_decision": {"accept_proposal": True, "accepted_offset_seconds": int(offs[i]),
                                          "manual_offset_seconds": ""}}
            part = self._offset_cell(dest, group, g, accepted, [f for f in psel if f.get("has_native_gps")], gpx,
                                     blockers, tz=tz, rep_naive=rep, date=date, day=day, photos=psel)
            # a part of the day, its offset its own photos' (RUL-clock_change_parts_own_evidence), answered by the
            # acceptance on the day's cell
            part["clock_change_part"] = {"of": bucket, "part": i + 1, "photos": len(psel)}
            parts[key] = part
        cell["clock_change"]["effective_split"] = {"parts": keys, "photo_parts": dict(sorted(photo_parts.items()))}
        cell["effective_time_anchor"], cell["requires_user_input"], cell["stale_user_decision"] = "", False, False
        cell.pop("decision_mode", None)
        return parts

    def _phone_cell(self, dest, key, g, prior_cell, sel, gpx, blockers, tz, date, day):
        """A phone's clock for one destination and day (BLD-phone_offset_cell), as (cell, recall entry), or None
        where nothing asks one. The phone's photos holding their own position are anchored as a camera's are, else
        read by their fixes' times (RUL-phone_anchored_like_camera, RUL-gps_time_checks_phone); that offset is set
        against the one each of those photos is read by now — its own offset tag, else the zone's. Disagreeing, it is
        the cell's proposal for every photo of the day: applying itself as several anchors do, one photo's a proposal
        to accept (RUL-phone_disagreeing_anchors_apply, RUL-phone_single_anchor_proposed). Agreeing, the tagged photos
        are read by their tags (RUL-phone_agreeing_anchor_changes_nothing), and the photos recording no offset —
        read by the zone unasked only where the tagged ones that day show the zone's offset
        (RUL-untagged_phone_photo_read_as_siblings) — by that offset (RUL-untagged_phone_photo_settled_by_evidence);
        with no such evidence they are asked about once, as a camera's guessed offset is
        (RUL-untagged_phone_photo_asked)."""
        if not sel:
            return None
        frames = [f for f in sel if f.get("has_native_gps")]
        evidence = infer_anchor_proposal(frames, gpx, CONFIG) or gps_time_proposal(frames, CONFIG)[0]
        timed = [f for f in sel if _parse_camera_naive(f.get("source_naive_time"))]
        tagged = [f for f in timed if _own_offset(f) is not None]
        untagged = [f for f in timed if _own_offset(f) is None]
        read = []
        if evidence is not None:
            tolerance = CONFIG["gpx_anchor_decision_tolerance_seconds"]
            found = evidence["proposed_offset_seconds"]
            by_path = {f["relative_path"]: f for f in frames}
            if evidence["proposal_source"] == "gpx_self_anchor":
                spread = CONFIG["gpx_anchor_offset_spread_max_seconds"]
                support = [a["source_file"] for a in evidence["anchors"]
                           if abs(a["proposed_offset_seconds"] - found) <= spread]
            else:
                # every reading of the fixes' times, not only those the record lists (BLD-phone_offset_cell)
                support = [r["source_file"] for r in gps_readings(frames)]
            read = sorted({r for p in support if p in by_path for r in [_read_offset(by_path[p], tz)]},
                          key=lambda r: (r is None, r or 0))
            # a photo that cannot be read — no zone yet, or an hour skipped or repeated — says nothing either way;
            # none read at all disagrees (RUL-phone_agreeing_anchor_changes_nothing)
            readable = [r for r in read if r is not None]
            agrees = bool(readable) and all(abs(r - found) <= tolerance for r in readable)
        else:
            agrees = True                          # nothing says otherwise of the tagged photos
        if agrees:
            # the tagged photos stand; the untagged ones are read by the zone unasked only where the tagged ones that
            # day show the zone's offset
            if not untagged or (tagged and _offsets_against_zone(tagged, {}, tz) is None and _valid_iana(tz)):
                return None
            applies, covered = "untagged_photos", untagged
        else:
            applies, covered = "every_photo", sel
        rep_naive = min((f.get("source_naive_time") for f in covered
                         if _parse_camera_naive(f.get("source_naive_time"))), default=None)
        cell = self._offset_cell(dest, key, g, prior_cell, frames, gpx, blockers, tz=tz, rep_naive=rep_naive,
                                 date=date, day=day, photos=covered, phone=True, recorded_from=tagged,
                                 settles=agrees and evidence is not None)
        cell["phone"] = {"applies_to": applies, "photos": len(covered),
                         "read_by_offsets": [r for r in read if r is not None]}
        # a guess the far-from-evidence check sets against the destination's other devices (BLD-offset_far_from_evidence)
        return cell, (key, g, prior_cell, frames, rep_naive, date, day, covered, tz)

    def _unidentified_cell(self, dest, nameless, tz, prior, blockers):
        """The one question of a destination's files naming no camera and recording no offset
        (BLD-unidentified_files_question): read them as local time in the destination's zone? The answer names the zone
        it was given for, and holds for every such file there, later ones too, while that is the zone
        (RUL-camera_less_files_asked_per_destination, RUL-camera_less_answer_kept)."""
        where = f"{dest}: unidentified_files.user_decision"
        ud = prior.get("user_decision") if isinstance(prior.get("user_decision"), dict) else {}
        accept = _decision_flag(ud, "accept_proposal", where, blockers)
        named = ud.get("accepted_timezone", "")
        named = "" if named is None else named
        effective, stale = "", False
        if not isinstance(named, str):
            blockers.append(f"{where}.accepted_timezone must be the timezone accepted, written as text.")
        elif named and not _valid_iana(named):
            # checked like every timezone the user writes (RUL-checked_timezones)
            blockers.append(f"{where}.accepted_timezone {named!r} is not a valid IANA timezone.")
        elif accept and not named:
            blockers.append(f"{where}.accepted_timezone must be the timezone accepted"
                            + (f" — the one now proposed is {tz}." if tz else "; no timezone is in effect here now."))
        elif accept:
            if tz and named == tz:
                effective = tz
            else:
                stale = True                       # accepted for another zone than the one now in effect
        paths = sorted(f["relative_path"] for f in nameless)
        return {"files": len(paths), "examples": paths[:3], "proposed_iana_timezone": tz or "",
                "user_decision": {"accept_proposal": accept, "accepted_timezone": named},
                "effective_iana_timezone": effective, "requires_user_input": effective == "",
                "stale_user_decision": stale}

    def _ask_changed_times(self, destinations, by_dest, prior_dests, blockers):
        """Each photo holding a time changed since geotag wrote it is asked about here, alone
        (BLD-changed_time_question): keep the time it holds — its true local time — or take back geotag's. An
        answer is the photo's, found again by its fingerprint, and holds for the time it was given for; until answered
        the photo is unresolved and photos-21 asks (RUL-changed_time_asked). An offset tag held beside the time that its
        destination's zone does not give then is recorded with the question and told
        (BLD-changed_time_kept_tag_noted)."""
        for dest, d in destinations.items():
            if d.get("file_less"):
                continue
            tz = (d.get("destination_timezone") or {}).get("effective_iana_timezone") or ""
            earlier = {}
            for cell in ((prior_dests.get(dest) or {}).get("changed_times") or {}).values():
                if isinstance(cell, dict) and isinstance(cell.get("content_fingerprint"), str):
                    earlier.setdefault(cell["content_fingerprint"], cell)
            out = {}
            for f in sorted(by_dest.get(dest) or [], key=lambda x: x["relative_path"]):
                ch = f.get("changed_time")
                if not ch and f.get("kept_from_pin"):
                    # a time kept on an earlier pass: its answer stays in the record while it stands, for the user to
                    # withdraw it there (RUL-kept_time_holds_while_answer_stands)
                    kept = {k: f["kept_from_pin"].get(k) for k in TIME_PAIR}
                    written_ = f.get("times_written") or []
                    d.setdefault("changed_times", {})[f["relative_path"]] = {
                        "content_fingerprint": f.get("content_fingerprint"), "held_time": kept,
                        "geotag_wrote": dict(written_[-1]) if written_ else None,
                        "own_time": {k: (f.get("own_time") or {}).get(k) for k in TIME_PAIR},
                        "user_decision": {"keep": "new", "answered_for": kept}, "effective_answer": "new",
                        "requires_user_input": False, "stale_user_decision": False}
                    continue
                if not ch:
                    continue
                rel = f["relative_path"]
                where = f"{dest}: changed_times[{rel}].user_decision"
                prior = _earlier_decision(earlier, f)
                ud = prior.get("user_decision") if isinstance(prior.get("user_decision"), dict) else {}
                keep = ud.get("keep", "")
                keep = "" if keep is None else keep
                answered = ud.get("answered_for", "")
                answered = "" if answered is None else answered
                stale = False
                if keep not in ("",) + CHANGED_TIME_ANSWERS:
                    blockers.append(f"{where}.keep must be \"new\" (keep the time it holds as the true local time), "
                                    "\"geotag\" (write geotag's time back) or \"\" (not answered).")
                elif keep and not (isinstance(answered, dict) and set(answered) == set(TIME_PAIR)):
                    blockers.append(f"{where}.answered_for must be the time answered for, as held_time gives it — the "
                                    f"one held now is {json.dumps(ch['held_time'], sort_keys=True)}.")
                elif keep == "new" and answered == ch["held_time"] and \
                        _parse_camera_naive(ch["held_time"]["DateTimeOriginal"]) is None:
                    blockers.append(f"{where}.keep: the photo holds no time to keep — answer \"geotag\", or give it "
                                    "a time and run prep again.")
                elif keep:
                    stale = answered != ch["held_time"]          # answered for another time than the one it holds now
                answer = ch.get("answer")
                out[rel] = {
                    "content_fingerprint": f.get("content_fingerprint"),
                    "held_time": ch["held_time"], "geotag_wrote": ch["geotag_wrote"], "own_time": ch["own_time"],
                    "user_decision": {"keep": keep, "answered_for": answered},
                    "effective_answer": answer or "",
                    "requires_user_input": not answer,
                    "stale_user_decision": stale,
                }
                disagrees = kept_tag_disagreement(ch["held_time"], tz)
                if disagrees is not None:
                    out[rel]["offset_tag_disagrees"] = disagrees
                    self.kept_tag_disagreements.append(dict(disagrees, relative_path=rel, answer=answer or ""))
            if out:
                d["changed_times"] = dict(sorted({**(d.get("changed_times") or {}), **out}.items()))

    def _ask_local_time_readings(self, destinations, by_dest, groups, prior_dests, blockers):
        """Each photo read by its destination's zone at a time the zone skips or repeats is asked about here, alone
        (BLD-local_time_readings): which of the two readings, for a time shown twice — its UTC offset, one of the
        two; for a time never shown, its UTC offset, any a time is recorded with. An answer is the photo's: found
        again by its fingerprint, never by its name. Until answered the photo is unresolved and photos-21 asks."""
        for dest, d in destinations.items():
            if d.get("file_less"):
                continue
            rows = compute_resolved_utc(by_dest[dest], groups, {"destinations": {dest: d}})
            asked = [r for r in rows if r["time_rule_used"] in AMBIGUOUS_RULES.values()]
            if not asked:
                continue
            files = {f["relative_path"]: f for f in by_dest[dest]}
            earlier = {}
            for cell in ((prior_dests.get(dest) or {}).get("local_time_readings") or {}).values():
                if isinstance(cell, dict) and isinstance(cell.get("content_fingerprint"), str):
                    earlier.setdefault(cell["content_fingerprint"], cell)
            out = {}
            for r in asked:
                f = files[r["relative_path"]]
                tz = r["destination_timezone"]
                # a photo's own time, or the midnight its folder's date fallback gives it (BLD-date_fallback_cell)
                local = _parse_camera_naive(f.get("source_naive_time")) or date_fallback_time(f, d)
                amb = _zone_ambiguity(local, tz)
                prior = _earlier_decision(earlier, f)
                ud = prior.get("user_decision") if isinstance(prior.get("user_decision"), dict) else {}
                given = ud.get("utc_offset_seconds", "")
                given = "" if given is None else given
                effective, stale = "", False
                if given != "":
                    if not _valid_offset(given) or isinstance(given, bool) or abs(int(given)) > 14 * 3600:
                        blockers.append(f"{dest}: local_time_readings[{f['relative_path']}].user_decision."
                                        "utc_offset_seconds must be a whole number of seconds within ±14 hours.")
                    elif amb["case"] == "repeated" and int(given) not in amb["offsets_seconds"]:
                        stale = True               # a time shown twice is one of its two readings, no other
                    else:
                        effective = int(given)
                out[f["relative_path"]] = {
                    "content_fingerprint": f.get("content_fingerprint"),
                    "camera_time": f.get("source_naive_time") or local.strftime("%Y:%m:%d %H:%M:%S"), "timezone": tz,
                    "case": amb["case"], "offsets_seconds": amb["offsets_seconds"],
                    "readings_utc": [(local - timedelta(seconds=o))
                                     .strftime("%Y-%m-%dT%H:%M:%SZ") for o in amb["offsets_seconds"]],
                    "user_decision": {"utc_offset_seconds": given},
                    "effective_utc_offset_seconds": effective,
                    "requires_user_input": effective == "",
                    "stale_user_decision": stale,
                }
            d["local_time_readings"] = out

    # Offsets a camera's own GPS gave: the only ones another destination's cell of the same day may take.
    _OWN_GPS_SOURCES = ("gpx_anchor_auto", "gpx_anchor_accepted", "gpx_anchor_chosen")

    def _share_offsets_within_a_day(self, destinations, recall, gpx, blockers):
        """A clock offset is the camera's for the day, wherever its photos were sorted (RUL-offset_shared_within_day).
        So, over the cells of one camera on one day in different destinations: (1) two offsets its own GPS gave that lie
        farther apart than `clock_offset_same_day_max_difference_seconds` are one clock read two ways —
        neither takes effect, both ask. An offset the user picked from the camera's own GPS groups
        (`gpx_anchor_chosen`) is held against them alike: one farther than the limit from it is withheld and
        asks, both naming the other, while the user's choice — their word — keeps its effect. (2) A cell with
        no GPS evidence of its own is proposed the offset the camera's GPS gave that day elsewhere, in place
        of the timezone's guess: applied by itself where it applied itself there, else for the user to accept.
        A `gpx_anchor_chosen` offset rests on the camera's own GPS, and is passed on like the others
        (BLD-offset_shared_within_day)."""
        limit = CONFIG["clock_offset_same_day_max_difference_seconds"]
        # a group of several bodies has a clock per body: its days in different destinations are decided apart
        # (RUL-several_bodies_days_apart, BLD-several_bodies_groups)
        several = set(CONFIG["camera_time_and_timezone_policy"].get("several_bodies_groups") or [])
        by_day, split = {}, {}
        for dest, d in destinations.items():
            for bucket, cell in d["camera_group_time_decisions"].items():
                # a phone's day is read in each destination on its own: its clock is the network's, set again
                # wherever it went (BLD-phone_offset_cell); a day split at a clock change has two offsets, and
                # neither is the day's to pass on — but each is held against the day's offsets elsewhere
                # (BLD-clock_change_split)
                if not (cell.get("day") and cell.get("camera_group_class") == "camera"
                        and cell.get("camera_group") not in several):
                    continue
                if "clock_change_part" in cell:
                    if isinstance(cell.get("effective_time_anchor"), dict):
                        split.setdefault((cell["camera_group"], cell["day"]), []).append((dest, bucket, cell))
                elif not (cell.get("clock_change") or {}).get("effective_split"):
                    by_day.setdefault((cell["camera_group"], cell["day"]), []).append((dest, bucket, cell))
        for (group, day), members in sorted(by_day.items()):
            hand = lambda c: (c.get("user_decision") or {}).get("manual_offset_seconds") not in ("", None)
            off = lambda c: c["effective_time_anchor"]["offset_seconds"]
            parts = split.get((group, day)) or []
            if parts:
                # The day split elsewhere at a change of the clock: an offset the camera's GPS gave here by itself
                # that lies beyond the limit from each part's is one of them resting on a wrong match — withheld,
                # asking, naming the parts; the parts, the user's accepted split, keep their effect.
                for dest, bucket, c in members:
                    if isinstance(c.get("effective_time_anchor"), dict) and not hand(c) \
                            and c["effective_time_anchor"].get("source") in self._OWN_GPS_SOURCES \
                            and all(abs(off(c) - off(p)) > limit for _d, _b, p in parts):
                        c["conflicts_with"] = [{"destination": d2, "bucket": b2, "offset_seconds": off(p),
                                                "chosen": False} for d2, b2, p in parts]
                        c["effective_time_anchor"], c["requires_user_input"] = "", True
                        c.pop("decision_mode", None)
            if len(members) < 2:
                continue
            donors = [(dest, bucket, c) for dest, bucket, c in sorted(members, key=lambda m: (m[0], m[1]))
                      if isinstance(c.get("effective_time_anchor"), dict)
                      and c["effective_time_anchor"].get("source") in self._OWN_GPS_SOURCES]
            # what the GPS alone gave — a proposal accepted as it stood among them: accepting vouches for the
            # reading, it chooses no number (RUL-accepted_offset_is_the_positions_own)
            found = [m for m in donors if not hand(m[2])]
            chosen = [m for m in donors if hand(m[2])]         # what the user picked from it
            # An offset the user chose is held against what the GPS gave by itself, as two of those are against
            # each other (RUL-chosen_offset_checked_same_day); two the user chose are both their word, and are not.
            against = [m for m in chosen if any(abs(off(m[2]) - off(f[2])) > limit for f in found)]
            offs = [off(c) for _d, _b, c in found]
            if against or (offs and max(offs) - min(offs) > limit):
                party = found + against
                for dest, bucket, c in party:
                    c["conflicts_with"] = [{"destination": d2, "bucket": b2, "offset_seconds": off(c2), "chosen": hand(c2)}
                                           for d2, b2, c2 in party if c2 is not c]
                # What the GPS gave by itself is withheld and asks; the user's choice keeps its effect, never set
                # aside by an offset it was not asked about (RUL-chosen_offset_not_withheld).
                for _dest, _bucket, c in found:
                    c["effective_time_anchor"], c["requires_user_input"] = "", True
                    c.pop("decision_mode", None)
                continue                              # one clock read two ways: nothing to pass on
            if not donors:
                continue
            # the donor: one that applied itself before one the user accepted, then by path
            dest0, bucket0, donor = min(donors, key=lambda m: (m[2]["effective_time_anchor"]["source"] != "gpx_anchor_auto",
                                                               m[0], m[1]))
            shared = {"offset_seconds": donor["effective_time_anchor"]["offset_seconds"],
                      "destination": dest0, "bucket": bucket0,
                      "applied_itself": donor["effective_time_anchor"]["source"] == "gpx_anchor_auto"}
            for dest, bucket, c in members:
                if (c.get("proposal") or {}).get("proposal_source") not in ("recorded_offset", "timezone_naive",
                                                                            "manual_required") \
                        or (dest, bucket) not in recall:
                    continue
                group, g, prior_cell, anchor_frames, rep_naive, date, day, sel, tz = recall[(dest, bucket)]
                destinations[dest]["camera_group_time_decisions"][bucket] = self._offset_cell(
                    dest, group, g, prior_cell, anchor_frames, gpx, blockers, tz=tz, rep_naive=rep_naive,
                    date=date, day=day, photos=sel, shared=shared)

    # Offsets of a day the camera's own GPS anchored, which the day before or after it in the same destination is offered.
    _ANCHORED_SOURCES = _OWN_GPS_SOURCES + ("gps_time_auto", "gps_time_accepted")

    def _offer_neighbour_days(self, destinations, recall, gpx, blockers):
        """A camera's day in a destination with no anchor of its own — its proposal would be `recorded_offset`,
        `timezone_naive` or `manual_required`, none shared from the same day elsewhere — is proposed the offset of the day
        before, else the day after, of the same camera in the same destination where that day's offset was anchored by
        the camera's own GPS (BLD-neighbour_day_proposal): on its tracks, or by its fixes' times; of a day split at a
        change of the clock, the part next to it. However far apart in time; asked about once, as a timezone's guess
        is — with tracks by the day's photos at the drift check, else by acceptance here
        (RUL-neighbour_day_offset_drift_checked). The day keeps its own cell."""
        for (dest, bucket), (group, g, prior_cell, anchor_frames, rep_naive, date, day, sel, tz) in sorted(recall.items()):
            cells = destinations[dest]["camera_group_time_decisions"]
            cell = cells.get(bucket) or {}
            if cell.get("camera_group_class") != "camera" or not day or (cell.get("proposal") or {}).get(
                    "proposal_source") not in ("recorded_offset", "timezone_naive", "manual_required"):
                continue
            neighbour = None
            for step, part in ((-1, 2), (1, 1)):
                try:
                    other = (datetime.strptime(day, "%Y-%m-%d") + timedelta(days=step)).strftime("%Y-%m-%d")
                except ValueError:
                    break
                key = f"{group}@{other}"
                split = ((cells.get(key) or {}).get("clock_change") or {}).get("effective_split")
                if isinstance(split, dict):
                    key = split["parts"][part - 1]          # the part of a split day next to this one
                eff = (cells.get(key) or {}).get("effective_time_anchor")
                if isinstance(eff, dict) and eff.get("source") in self._ANCHORED_SOURCES:
                    neighbour = {"day": other, "bucket": key, "offset_seconds": eff["offset_seconds"]}
                    break
            if neighbour is None:
                continue
            cells[bucket] = self._offset_cell(dest, group, g, prior_cell, anchor_frames, gpx, blockers, tz=tz,
                                              rep_naive=rep_naive, date=date, day=day, photos=sel,
                                              neighbour=neighbour)

    # Offsets that say when a camera's photos were taken, for another camera's guessed offset to be set against: its own
    # GPS's, the same day's elsewhere, the user's. Never another guess (BLD-offset_far_from_evidence).
    _SETTLED_SOURCES = ("gpx_anchor_auto", "gpx_anchor_accepted", "gpx_anchor_chosen", "gpx_anchor_imprecise",
                        "same_day_auto", "same_day_accepted", "manual")
    # Proposals that guess a camera's clock: from the offset its photos record, or from the destination's zone.
    _GUESSED_PROPOSALS = ("recorded_offset", "timezone_naive")
    # What a guessed offset takes effect as, without or with the user's acceptance.
    _GUESSED_SOURCES = ("recorded_offset_unconfirmed", "recorded_offset_accepted",
                        "timezone_unconfirmed", "timezone_accepted")
    # The offset the fixes' own times give, and what it takes effect as: set against the same evidence, for a fix
    # that wrote local time is hours out (RUL-gps_time_far_from_evidence_withheld).
    _FAR_CHECKED_PROPOSALS = _GUESSED_PROPOSALS + ("gps_time",)
    _FAR_CHECKED_SOURCES = _GUESSED_SOURCES + ("gps_time_auto", "gps_time_accepted")

    def _withhold_far_offsets(self, destinations, recall, by_dest, groups, gpx, fixes):
        """A guessed offset that puts a cell's photos where nothing else was does not take effect by acceptance
        (RUL-offset_far_from_evidence_asks): set against the destination's photos of other devices whose time is
        known, and the track points, a cell whose every photo lies farther than `gpx_anchor_max_clock_error_seconds`
        from all of them — there being such a photo — asks for an offset of the user's own; its proposal, still
        shown, says why. A clock reset to its factory date is the case. With no other device's photo there,
        nothing can tell, and the guess stands as it is.

        The fixes' own times are judged first (`fixes` True), in rounds, each against what the rounds before left,
        until a round withdraws none — a phone's fix offset withdrawn is no evidence for a later round; then
        (`fixes` False) the guesses, all against what is left (BLD-offset_far_from_evidence)."""
        checked = [(dest, bucket, entry) for (dest, bucket), entry in sorted(recall.items())
                   if ((destinations[dest]["camera_group_time_decisions"].get(bucket) or {}).get("proposal") or {})
                   .get("proposal_source") in self._FAR_CHECKED_PROPOSALS]
        source = lambda c: destinations[c[0]]["camera_group_time_decisions"][c[1]]["proposal"]["proposal_source"]
        track_times = sorted(p.time_utc for p in gpx.points) if checked else []
        if fixes:
            fixed = [c for c in checked if source(c) == "gps_time"]
            while fixed:
                known = {}
                withdrawn = [c for c in fixed if self._withhold_if_far(c, destinations, known, by_dest, groups,
                                                                        track_times)]
                if not withdrawn:
                    break
                fixed = [c for c in fixed if c not in withdrawn]
            return
        known = {}
        for c in checked:
            if source(c) != "gps_time":
                self._withhold_if_far(c, destinations, known, by_dest, groups, track_times)

    def _guess_window(self, destinations, recall):
        """What the readers of photos-21 reach past the camera window (BLD-track_window): each cell's photos whose
        proposal is not the camera's own GPS's on the tracks — a guess, a neighbour day's offset, the fixes' times — at
        the times the proposal corrects them to, from the first to the last, give or take the farther of the
        far-from-evidence check's `gpx_anchor_max_clock_error_seconds` and the drift check's reach."""
        reach = max(CONFIG["gpx_anchor_max_clock_error_seconds"], _drift_reach())
        spans = []
        for (dest, bucket), entry in sorted(recall.items()):
            proposal = (destinations[dest]["camera_group_time_decisions"].get(bucket) or {}).get("proposal") or {}
            if proposal.get("proposal_source") not in self._FAR_CHECKED_PROPOSALS + ("neighbour_day",) \
                    or not _valid_offset(proposal.get("proposed_offset_seconds")):
                continue
            times = []
            for f in entry[7]:
                if (t := _parse_camera_naive(f.get("source_naive_time"))) is not None:
                    try:
                        times.append(t.replace(tzinfo=timezone.utc) + timedelta(seconds=proposal["proposed_offset_seconds"]))
                    except OverflowError:
                        continue
            if times:
                spans.append((around(min(times), reach)[0], around(max(times), reach)[1]))
        return spans

    def _withhold_if_far(self, checked, destinations, known, by_dest, groups, track_times):
        """Judge one far-checked cell against its destination's evidence as `known` holds it (worked out once per
        destination); mark its proposal far, or unmark it, and withdraw an offset it took effect by. True when an
        offset was withdrawn."""
        dest, bucket, (group, _g, _p, _a, _rep, _date, _day, sel, _tz) = checked
        cell = destinations[dest]["camera_group_time_decisions"][bucket]
        proposal = cell["proposal"]
        if dest not in known:
            rows = compute_resolved_utc(by_dest[dest], groups, {"destinations": {dest: destinations[dest]}})
            # what another device says of when the destination was visited: a phone's photo, by its own
            # offset or the zone; a camera's, by its cell's settled offset only — never one corrected before,
            # whose offset no record here vouches for, nor a file naming no device, whose time may be any
            known[dest] = [(r["camera_group"], r["relative_path"], t) for r in rows
                           if r["resolved_utc_status"] == "valid" and (t := _parse_utc(r["resolved_utc"]))
                           and ((cls := (groups.get(r["camera_group"]) or {}).get("camera_group_class"))
                                == "smartphone"
                                or (cls == "camera" and r["time_rule_used"] == "camera_group_offset"
                                    and r["resolved_utc_provenance"] in self._SETTLED_SOURCES))]
        others = [(p, t) for g2, p, t in known[dest] if g2 != group]
        off = proposal["proposed_offset_seconds"]
        times = []
        for f in sel:
            if (t := _parse_camera_naive(f.get("source_naive_time"))) is not None:
                try:
                    times.append(t.replace(tzinfo=timezone.utc) + timedelta(seconds=off))
                except OverflowError:
                    continue
        why = far_from_evidence(times, others, track_times, CONFIG["gpx_anchor_max_clock_error_seconds"]) \
            if others else None
        if why is None:
            proposal.pop("far_from_evidence", None)
            return False
        proposal["far_from_evidence"] = why
        eff = cell.get("effective_time_anchor")
        # an offset kept from an earlier run is not this proposal's, and is not withdrawn for it
        if isinstance(eff, dict) and eff.get("source") in self._FAR_CHECKED_SOURCES \
                and cell.get("decision_mode") != "kept_from_earlier":
            cell["effective_time_anchor"], cell["requires_user_input"] = "", True
            cell.pop("decision_mode", None)
            return True
        return False

    def _tracks_by(self, gpx, times, frames):
        """The track points the drift check sets a bucket's photos against: those within
        `drift_check_track_window_seconds` of the photos' resolved `times` — or as far as placement reaches, where
        that is farther, so the tracks never place a photo on an offset the drift check did not confirm
        (RUL-unanchored_offset_confirmed); or, none lying there, of the times the camera recorded — an offset days
        out carries the photos away from their own tracks, and is checked against those, not waved through."""
        window = _drift_reach()
        near = lambda a, z: [p for p in gpx.points if (a - timedelta(seconds=window)) <= p.time_utc
                             <= (z + timedelta(seconds=window))]
        seg = near(min(times), max(times)) if times else []
        if not seg:
            clock = [t.replace(tzinfo=timezone.utc) for f in frames
                     if (t := _parse_camera_naive(f.get("source_naive_time")))]
            seg = near(min(clock), max(clock)) if clock else []
        return seg

    def _timezone_decision(self, dest, prior_tz, blockers, inherited=None, file_less=False, against=None,
                           country=None, zones=(), own_country="", removed=None, fitted=None):
        # Proposal precedence (BLD-timezone_cell): the nearest RESOLVED ancestor destination's timezone (a more
        # specific signal than the generic global default — e.g. a Japan/Kyoto leaf inheriting Japan's
        # Asia/Tokyo over a Europe/Brussels home default) wins; else, in a country of several timezones, the one its
        # photos' recorded offsets fit (BLD-zone_from_photos_in_country); else the config default; else none.
        # Destinations are geographically NESTED — a child sits inside its parent, so it can scarcely
        # cross a timezone boundary the parent didn't — so a timezone proposal (inherited or config
        # default) auto-resolves without per-destination confirmation, staying overridable by a manual
        # entry. Only a destination with NO proposal at all (no ancestor, no default) blocks.
        default = (CONFIG.get("camera_time_and_timezone_policy") or {}).get("default_folder_timezone") or None
        if country and default not in zones:
            default = None                          # the usual zone is no zone of the country chosen here
        if inherited is not None and country and len(zones) == 1 and inherited[1] == zones[0]:
            proposed, source, inherited_from = zones[0], "country", None
        elif inherited is not None:
            anc_path, anc_tz = inherited
            proposed, source, inherited_from = anc_tz, "inherited", anc_path
        elif fitted:
            # the photos' own offsets, within the country the user said (BLD-zone_from_photos_in_country)
            proposed, source, inherited_from = fitted, "photos_in_country", None
        elif default:
            proposed, source, inherited_from = default, "config_default", None
        else:
            proposed, source, inherited_from = None, "none", None
        ud = prior_tz.get("user_decision") or {}
        manual = ud.get("manual_iana_timezone", "")
        manual = "" if manual is None else manual
        if not isinstance(manual, str):
            # false, 0 or [] is no zone, and no "no answer" either: named, never read as empty (RUL-checked_shapes)
            blockers.append(f"{dest}: destination_timezone.user_decision.manual_iana_timezone must be a timezone "
                            f"written as text, not {manual!r}.")
            manual = ""
        # The photos here that record another offset than the zone has: the zone stands against them only
        # on the user's explicit word, which names the offsets it was given for — a photo arriving with yet
        # another offset was never spoken for, and asks again.
        despite = ud.get("confirmed_despite_recorded_offsets")
        if despite is None:                 # absent or null: no answer given, as in every other field
            despite = []
        if not (isinstance(despite, list) and all(_valid_offset(o) for o in despite)):
            blockers.append(f"{dest}: destination_timezone.user_decision.confirmed_despite_recorded_offsets "
                            "must be a list of whole numbers of seconds.")
            despite = []
        spoken_for = bool(against) and set(against["recorded_offsets"]) <= {int(o) for o in despite}
        if spoken_for:
            against = dict(against, confirmed=True)
        unanswered = against if against and not spoken_for else None
        effective = ""
        if manual:
            if not _valid_iana(manual):
                blockers.append(f"{dest}: destination_timezone.user_decision.manual_iana_timezone "
                                f"{manual!r} is not a valid IANA timezone.")
            elif country and zones and manual not in zones:
                blockers.append(f"{dest}: destination_timezone.user_decision.manual_iana_timezone {manual!r} is "
                                f"not a timezone of {country[0]}, the country chosen at {country[1]}: "
                                + ", ".join(zones) + ".")
            elif not unanswered:
                effective = manual
        # An inherited zone is adopted (and re-propagated downward) without the user's answer — container or
        # real — because the nested geography makes the parent's timezone the right one for the child. The
        # configured default is only proposed: it is the user's usual zone, true of no trip in particular, and
        # applied to a place abroad it would name and time its photos in the wrong zone; it is answered once, on
        # the folder of the country or region it holds for, everything beneath inheriting. A manual entry overrides either, and is the one decision
        # the user makes here (BLD-timezone_cell).
        # ...unless this destination's own photos say otherwise: a phone's photo here that records an offset
        # the inherited zone does not have at that time was taken in another zone, and the one zone change
        # of a trip is not adopted unasked. The user writes the zone — the inherited one, if it is right.
        auto = not manual and bool(proposed) and source in ("inherited", "country", "photos_in_country") and not unanswered
        if auto:
            effective = proposed
        block = {
            "proposed_iana_timezone": proposed,
            "proposal_source": source,
            "user_decision": {"manual_iana_timezone": manual, "country": own_country,
                              "confirmed_despite_recorded_offsets": [int(o) for o in despite]},
            "effective_iana_timezone": effective,
            # a container asks only for the destinations waiting within it (_ask_zone_at_containers)
            "requires_user_input": effective == "" and not file_less,
            # a word given for other offsets than the photos now record is kept as written, and speaks for none
            "stale_user_decision": bool(despite) and bool(unanswered),
        }
        if auto:
            block["decision_mode"] = "auto_resolved"
        if inherited_from:
            block["inherited_from"] = inherited_from
        if against:
            block["contradicted_by"] = against
        if country:
            block["country"] = country[0]           # the country in effect here, and where it was chosen
            if country[1] != dest:
                block["country_from"] = country[1]
            block["country_zones"] = list(zones)
        if removed:
            block["country_removed"] = removed
        return block

    def _offset_cell(self, dest, key, g, prior_cell, frames, gpx, blockers, tz=None, rep_naive=None, date=None,
                     day=None, photos=(), shared=None, phone=False, recorded_from=None, settles=False, neighbour=None):
        # One (camera group, destination[, date]) clock-offset bucket — a phone's too, where one is asked
        # (`phone`, BLD-phone_offset_cell); `recorded_from` are the photos whose recorded offset is proposed, where
        # they are not the ones offset; `settles`: the phone's own GPS agrees with how its tagged photos are read, and
        # reads its untagged ones by itself (RUL-untagged_phone_photo_settled_by_evidence). Proposal precedence (BLD-offset_buckets):
        # GPX self-anchor → the times the photos' own fixes recorded (BLD-gps_time_proposal) → the same day's
        # elsewhere → the offset its photos record (BLD-recorded_offset_proposal) →
        # timezone-derived (camera assumed on local time; DST-aware, BLD-timezone_naive_offset) → manual. Clock
        # offsets do not inherit from the destination above. `date` (YYYY-MM-DD) is set when the group spans >1
        # naive day here; the bucket key is `<key>@<date>` and is the blocker location.
        loc = key if date is None else f"{key}@{date}"
        proposal = infer_anchor_proposal(frames, gpx, CONFIG)
        set_aside = None
        if proposal is None:
            # no track by the photos' own positions: the UTC their own fixes recorded, below a track's anchor and
            # above the offset the photos record and the zone's guess (RUL-gps_time_is_clock_evidence)
            proposal, set_aside = gps_time_proposal(frames, CONFIG)
        if proposal is None and shared is not None:
            # no GPS evidence here, and the camera's own GPS fixed its clock that day in another destination
            proposal = {"proposal_source": "same_day_elsewhere", "proposed_offset_seconds": shared["offset_seconds"],
                        "shared_from": {"destination": shared["destination"], "bucket": shared["bucket"]},
                        "confidence": "high" if shared["applied_itself"] else "review_required"}
        if proposal is None and neighbour is not None:
            # no GPS evidence of its own that day, none shared from the same day: the offset the camera's own GPS
            # gave the day before or after it here, asked about once: at the drift check where tracks lie by the
            # photos, else by acceptance (BLD-neighbour_day_proposal)
            proposal = {"proposal_source": "neighbour_day", "proposed_offset_seconds": neighbour["offset_seconds"],
                        "neighbour_day": {"day": neighbour["day"], "bucket": neighbour["bucket"]},
                        "confidence": "review_required"}
        differ = None
        if proposal is None and photos:
            # the zone the camera's clock was set to, as its photos record it: better than assuming local time
            proposal, differ = recorded_offset_proposal(photos if recorded_from is None else recorded_from, rep_naive)
        if proposal is None and (tzr := _timezone_naive_offset(rep_naive, tz)) is not None:
            off_s, real_iso = tzr
            proposal = {"proposal_source": "timezone_naive", "proposed_offset_seconds": off_s,
                        "proposed_real_utc": real_iso, "proposed_from_timezone": tz,
                        "confidence": "review_required"}
        elif proposal is None:
            proposal = {"proposal_source": "manual_required"}
            # The bucket's earliest camera time is one its timezone repeats or skips: the zone gives two offsets
            # there, and none is proposed (RUL-ambiguous_local_time_never_guessed) — the cell says why it asks.
            amb = _zone_ambiguity(_parse_camera_naive(rep_naive), tz) if _valid_iana(tz) else None
            if amb is not None:
                proposal["timezone_ambiguous"] = {"camera_time": rep_naive, "timezone": tz, **amb}
        is_gpx = proposal.get("proposal_source") == "gpx_self_anchor"
        is_shared = proposal.get("proposal_source") == "same_day_elsewhere"
        is_recorded = proposal.get("proposal_source") == "recorded_offset"
        is_gps_time = proposal.get("proposal_source") == "gps_time"
        is_neighbour = proposal.get("proposal_source") == "neighbour_day"
        has_offset = "proposed_offset_seconds" in proposal
        conflicting = proposal.get("conflicting_count", 0) > 0 or bool(proposal.get("tied"))   # anchors disagree
        imprecise = bool(proposal.get("imprecise_seconds"))    # the tracks stood still: no photo says when
        spread = CONFIG["gpx_anchor_offset_spread_max_seconds"]          # anchors this close agree
        tolerance = CONFIG["gpx_anchor_decision_tolerance_seconds"]      # a proposal this close is the one decided
        policy = CONFIG["camera_time_and_timezone_policy"]      # whole: the loader refuses one lacking a setting
        # a group the configuration names several bodies: no offset from its GPS applies itself
        # (RUL-several_bodies_offset_never_auto, BLD-several_bodies_groups)
        several = bool(g.get("several_bodies"))

        ud = prior_cell.get("user_decision") or {}
        accept = _decision_flag(ud, "accept_proposal", f"{dest}: camera_group_time_decisions[{loc}].user_decision", blockers)
        manual_off = ud.get("manual_offset_seconds", "")
        accepted_off = ud.get("accepted_offset_seconds", "")
        # A phone's photos kept as they record themselves, its own GPS set aside (BLD-phone_offset_cell) — the value
        # checked on every offset cell, a camera's too, never passed over (RUL-checked_shapes).
        keep = _decision_flag(ud, "keep_as_recorded",
                              f"{dest}: camera_group_time_decisions[{loc}].user_decision", blockers) and phone
        effective, stale, decision_mode = "", False, None

        if manual_off != "" and manual_off is not None:
            if _valid_offset(manual_off):
                # An offset the camera's own GPS supports — one of the proposal's groups, picked instead
                # of the recommended one — is anchored like an accepted proposal, so no drift check asks
                # again what its photos already show (RUL-chosen_group_is_anchored).
                chosen = is_gpx and not imprecise and any(abs(int(manual_off) - gg["offset_seconds"]) <= spread
                                        for gg in proposal.get("groups") or [])
                effective = {"offset_seconds": int(manual_off), "source": "gpx_anchor_chosen" if chosen else "manual"}
            else:
                blockers.append(f"{dest}: camera_group_time_decisions[{loc}].user_decision."
                                "manual_offset_seconds must be a whole number of seconds.")
        elif keep:
            # the user's word that the phone's own reading is right and its GPS here is not: what it sets aside is
            # its GPS's finding, so it holds while there is one (RUL-phone_kept_as_recorded)
            if is_gpx or is_gps_time:
                effective = {"source": "as_recorded"}
            else:
                stale = True
        elif accept:
            # An acceptance names the offset it accepted, and holds only while that is what is proposed
            # (RUL-acceptance_holds_for_its_proposal): a proposal that has become another one — the timezone changed,
            # the tracks changed, photos arrived whose GPS says otherwise — was never accepted, and asks.
            where = f"{dest}: camera_group_time_decisions[{loc}].user_decision.accepted_offset_seconds"
            if accepted_off in ("", None):
                blockers.append(f"{where} must be the offset accepted"
                                + (f" — the one now proposed is {proposal['proposed_offset_seconds']}." if has_offset
                                   else "; nothing is proposed now, so clear accept_proposal."))
            elif not _valid_offset(accepted_off):
                blockers.append(f"{where} must be a whole number of seconds.")
            # within the tolerance where the camera's own GPS proposed it — here, or the same day elsewhere, or the
            # day next to it — the same finding; a guess holds only for the very offset accepted
            elif not has_offset or abs(int(accepted_off) - proposal["proposed_offset_seconds"]) > \
                    (tolerance if is_gpx or is_gps_time or is_shared or is_neighbour else 0):
                stale = True                       # accepted a proposal that is no longer the one made
            else:
                # An offset no photo pins within the tracks' stay is supported by the camera's GPS, not
                # anchored by it: the drift check still asks (BLD-drift_validation).
                # What takes effect is the offset the user accepted: a proposal a few seconds from it is
                # the same finding, and no reason to move photos already corrected by the first.
                effective = {"offset_seconds": int(accepted_off),
                             "source": ("gpx_anchor_imprecise" if imprecise else "gpx_anchor_accepted") if is_gpx
                             else "same_day_accepted" if is_shared
                             else "neighbour_day_accepted" if is_neighbour
                             else "gps_time_accepted" if is_gps_time
                             else "recorded_offset_accepted" if is_recorded else "timezone_accepted"}
        elif is_gps_time and not several and ((proposal["gps_time_count"] >= 2 and policy["multi_anchor_auto_apply"])
                                              or settles):
            # two fixes or more, their times all different and their offsets agreeing, apply themselves as several
            # anchors do; one is a proposal to accept (RUL-gps_times_agreeing_apply, RUL-single_gps_time_proposed)
            effective = {"offset_seconds": proposal["proposed_offset_seconds"], "source": "gps_time_auto"}
            decision_mode = "auto_resolved"
        elif is_gpx and not conflicting and not imprecise and not several:
            # auto-resolution under the config flags (RUL-anchor_offset_auto_as_configured) — GPX-self-anchor only; a
            # timezone-derived proposal is confirmable, never auto-applied (the local-clock assumption can be wrong).
            n = proposal["anchor_count"]
            if (n >= 2 and policy["multi_anchor_auto_apply"]) or settles or \
               (n == 1 and policy["single_anchor_auto_apply"] and not phone):   # one phone photo: a proposal
                effective = {"offset_seconds": proposal["proposed_offset_seconds"], "source": "gpx_anchor_auto"}
                decision_mode = "auto_resolved"
        anchored_by = fixed_by = None
        if isinstance(effective, dict) and effective["source"] == "gpx_anchor_auto":
            # the tracks the offset rests on, as they are now: what keeping it later is checked against
            anchored_by = [{"gpx_file": f, "sha256": gpx.file_sha.get(f)} for f in
                           sorted({a["gpx_match"]["gpx_file"] for a in proposal["anchors"]
                                   if abs(a["proposed_offset_seconds"] - effective["offset_seconds"]) <= spread})]
        elif isinstance(effective, dict) and effective["source"] == "gps_time_auto":
            # the photos whose fixes' times gave it, by their content: what keeping it later is checked against
            fixed_by = sorted({fp for f in frames if (fp := f.get("content_fingerprint"))
                               for r in gps_readings([f])
                               if abs(r["offset_seconds"] - effective["offset_seconds"]) <= spread})
        if effective == "" and not stale and manual_off in ("", None) and not accept and not keep and not several:
            # An offset found from the camera's own GPS — its tracks, or its photos' fixes — stays this camera's
            # offset for the day when the photos that gave it are corrected and later ones bring no GPS of their
            # own (RUL-day_offset_kept_for_later_photos) — while what it rested on still stands: every track that
            # anchored it is under gpx_root unchanged (RUL-kept_offset_rests_on_its_tracks), or every photo whose
            # fix gave it is still among the camera's photos here (RUL-kept_offset_rests_on_its_fixes); and no
            # proposal its own GPS now gives says otherwise (RUL-kept_offset_yields_to_new_photo). A user's answer
            # needs no such keeping: it is preserved as their decision, and withdrawing it takes effect.
            earlier = prior_cell.get("effective_time_anchor")
            was = earlier.get("source") if isinstance(earlier, dict) else None
            rests_on, fixed = prior_cell.get("anchored_by"), prior_cell.get("fixed_by")
            here = self.fingerprints_here.get((dest, key), set())
            stands = (was == "gpx_anchor_auto" and isinstance(rests_on, list) and rests_on
                      and all(isinstance(t, dict) and t.get("gpx_file") in gpx.file_sha
                              and gpx.file_sha[t["gpx_file"]] == t.get("sha256") for t in rests_on)) \
                or (was == "gps_time_auto" and isinstance(fixed, list) and fixed
                    and all(isinstance(fp, str) and fp in here for fp in fixed))
            if stands and not ((is_gpx and (conflicting or imprecise)) or (
                    (is_gpx or is_gps_time)
                    and abs(proposal["proposed_offset_seconds"] - earlier.get("offset_seconds", 0)) > tolerance)):
                effective, decision_mode = earlier, "kept_from_earlier"
                anchored_by, fixed_by = (rests_on, None) if was == "gpx_anchor_auto" else (None, fixed)
        if effective != "" or stale or manual_off not in ("", None) or accept or keep:
            pass                                   # decided above, or the user's to decide
        elif is_shared and shared["applied_itself"]:
            effective = {"offset_seconds": proposal["proposed_offset_seconds"], "source": "same_day_auto"}
            decision_mode = "auto_resolved"
        elif (proposal.get("proposal_source") in self._GUESSED_PROPOSALS or is_neighbour) and photos:
            # A guess — the timezone's, the offset the photos record, or the day next to it's — is asked about once,
            # where it can be checked: with tracks by the photos it goes to the drift check as it stands, and the
            # confirmation there is its acceptance (BLD-timezone_naive_offset, BLD-recorded_offset_proposal,
            # BLD-neighbour_day_proposal) — nothing is planned until then. With no track to check it against, it is
            # accepted here.
            times = [t.replace(tzinfo=timezone.utc) + timedelta(seconds=proposal["proposed_offset_seconds"])
                     for f in photos if (t := _parse_camera_naive(f.get("source_naive_time")))]
            if self._tracks_by(gpx, times, photos):
                effective = {"offset_seconds": proposal["proposed_offset_seconds"],
                             "source": "recorded_offset_unconfirmed" if is_recorded
                             else "neighbour_day_unconfirmed" if is_neighbour else "timezone_unconfirmed"}
                decision_mode = "to_be_confirmed_against_tracks"

        cell = {
            "camera_group": key,
            "camera_group_class": g.get("camera_group_class", "camera"),
            "proposal": proposal,
            "user_decision": {"accept_proposal": accept,
                              "accepted_offset_seconds": accepted_off if accepted_off is not None else "",
                              "manual_offset_seconds": manual_off if manual_off is not None else "",
                              **({"keep_as_recorded": keep} if phone else {})},
            "effective_time_anchor": effective,
            "requires_user_input": effective == "",
            "stale_user_decision": stale,
        }
        if anchored_by:
            cell["anchored_by"] = anchored_by
        if fixed_by:
            cell["fixed_by"] = fixed_by
        if differ:
            cell["recorded_offsets_differ"] = differ   # the photos record more than one: none is proposed from them
        if set_aside and not is_gpx:
            cell["gps_time_set_aside"] = set_aside     # the fixes' times, and why they say nothing of the clock
        rep = min(((f.get("source_naive_time"), f["relative_path"]) for f in photos
                   if _parse_camera_naive(f.get("source_naive_time"))), default=None)
        if rep:
            # the photo a true time can be given for, to set the offset by (the editor's, never a decision field)
            cell["representative"] = {"source_file": rep[1], "camera_source_naive_time": rep[0]}
        if date is not None:
            cell["date"] = date                    # this bucket covers only that naive calendar date
        if day is not None:
            cell["day"] = day                      # the day its photos are of, whatever its key
        if decision_mode:
            cell["decision_mode"] = decision_mode
        if several and (is_gpx or is_gps_time or is_shared or is_neighbour):
            cell["several_bodies"] = True          # the offset its GPS gives may be one body's (RUL-several_bodies_noted)
        if is_gpx and not imprecise and not phone and not several and isinstance(effective, dict) \
                and effective.get("source") in self._OWN_GPS_SOURCES \
                and (conflicting or effective["offset_seconds"] != proposal["proposed_offset_seconds"]):
            # the photos holding their own position that the offset agreed from the camera's GPS contradicts: their
            # positions are set against the tracks once the photos are placed (BLD-contradicted_position) — never a
            # group of several bodies', whose disagreeing photos are another body's (RUL-several_bodies_positions_not_doubted)
            against = contradicted_frames(frames, gpx, CONFIG, effective["offset_seconds"])
            if against:
                cell["positions_contradicted"] = against
        return cell

    def _handoff_dependency(self, ws):
        """The handoff dependency is its deterministic CONTENT fingerprint (RUL-handoff_verified_by_content), recomputed
        from the handoff, never the volatile file bytes — so a no-op prep re-run (which only refreshes
        run_metadata) does not restale this plan."""
        with open(handoff_path(ws)) as f:
            ho = json.load(f)
        return {"dependency_type": "handoff_content", "artifact_name": "photos-11-handoff.json",
                "artifact_path": os.path.relpath(handoff_path(ws), ws),
                "content_fingerprint": handoff_content_fingerprint(ho)}

    @staticmethod
    def _verify_handoff_dependency(dep, ws):
        p = os.path.join(ws, dep.get("artifact_path", ""))
        try:
            with open(p) as f:
                return handoff_content_fingerprint(json.load(f)) == dep.get("content_fingerprint")
        except Exception:
            return False

    def _time_depends_on(self):
        policy = json.dumps((CONFIG.get("camera_time_and_timezone_policy") or {}), sort_keys=True)
        return {
            "handoff": self._handoff_dependency(self.workspace_root),
            "camera_time_policy_fingerprint": sha256_text(policy),
            "gpx_fingerprint": self._gpx_fingerprint,
            "camera_group_key_version": CAMERA_GROUP_KEY_VERSION,
        }

    # --- Stage 7a: GPS-drift validation (photos-22, BLD-drift_validation) ---
    # The highest-danger gap: a (group, dest, date) bucket whose clock offset is manual/timezone-
    # derived (NOT a GPX self-anchor) and that has NO native-GPS anchor is placed in phase 23 purely
    # from its resolved UTC — a wrong offset silently lands the whole batch at the wrong track point.
    # 22 flags every such bucket that GPX *could* validate, blocks until the operator explicitly
    # confirms each (a zero-scrub "offset was right" must be actively confirmed, never implied), and
    # carries the corrected/validated offset that compute_resolved_utc then re-consumes (BLD-resolved_utc).

    _DRIFT_TRIGGER_SOURCES = ("timezone_accepted", "timezone_unconfirmed", "recorded_offset_accepted",
                              "recorded_offset_unconfirmed", "manual", "gpx_anchor_imprecise",
                              # another day's clock, checked on this day's tracks
                              "neighbour_day_accepted", "neighbour_day_unconfirmed")
    # A guess nobody has accepted: always given its drift cell, for the confirmation there is its acceptance.
    _UNCONFIRMED_SOURCES = ("timezone_unconfirmed", "recorded_offset_unconfirmed", "neighbour_day_unconfirmed")

    def build_drift_validation(self, files, time_artifact, rows0, gpx, prior):
        """Build/regenerate photos-22 from the COMPLETE photos-21 + the resolved UTC under the
        current offsets (`rows0`). One review item per at-risk bucket (manual/tz-derived offset, no
        native-GPS anchor, and GPX coverage over its plausible time window). Authored confirmations
        are preserved across reruns, each holding only for the offset it confirmed and while the tracks it
        names stand — a changed offset or track makes it stale; one whose bucket no longer triggers is
        dropped, nothing being left to check.
        Returns (artifact, blockers); a bad authored value is a blocker (leave the artifact as-is)."""
        blockers = _decision_shape_blockers(prior, "drift")
        if blockers:
            return None, blockers
        prior_dests = ((prior or {}).get("destinations")) or {}
        track_sha = gpx.file_sha if gpx is not None else {}
        destinations = {}
        for dest, bucket, cell, frames, times in self._drift_cases(files, time_artifact, rows0):
            eff = cell["effective_time_anchor"]
            group, date = cell.get("camera_group"), cell.get("date")
            prior_cells = (prior_dests.get(dest, {}).get("drift_decisions")) or {}
            prior_drift = _prior_day_cell(prior_cells, group, bucket, cell.get("day"))
            cells = destinations.setdefault(dest, {"destination_path": dest, "drift_decisions": {}})["drift_decisions"]
            if not frames:
                # every photo here is corrected already: keep the confirmation for later arrivals,
                # derived again from the decision and the current offset, never copied
                if prior_drift:
                    kept = self._drift_cell(dest, bucket, cell, [], [], prior_drift, blockers, date=date,
                                            track_sha=track_sha)
                    if kept["effective_drift_offset"]:
                        kept["requires_user_input"] = False
                        cells[bucket] = kept
                continue
            if not times and eff.get("source") not in self._UNCONFIRMED_SOURCES:
                continue                                  # nothing resolves -> not a drift case
            seg = self._tracks_by(gpx, times, frames)
            # An offset nobody has accepted is never passed over: it is here to be confirmed, tracks
            # or none.
            if not seg and eff.get("source") not in self._UNCONFIRMED_SOURCES:
                continue                                  # no GPX coverage -> phase 23 fallback/lost
            cells[bucket] = self._drift_cell(dest, bucket, cell, seg, frames,
                                             prior_drift, blockers, date=date, track_sha=track_sha)
        destinations = {dest: d for dest, d in destinations.items() if d["drift_decisions"]}
        requires = any(c["requires_user_input"] for d in destinations.values()
                       for c in d["drift_decisions"].values())
        artifact = {
            "artifact_type": "gps_drift_validation",
            "artifact_name": DRIFT_VALIDATION_ARTIFACT,
            "status": "requires_user_input" if requires else "complete",
            "requires_user_input": requires,
            "executable": False,
            "destinations": destinations,
            "depends_on": self._drift_depends_on(),
        }
        if not requires:
            artifact["decision_mode"] = "no_op_or_confirmed"
        return artifact, blockers

    def _drift_cases(self, files, time_artifact, rows0):
        """Each offset cell the drift check looks at — one whose offset is not the camera's own GPS's — as
        (destination, bucket, cell, its photos not yet corrected, their corrected times under `rows0`)."""
        by_dest_group = {}
        for f in files:
            if not f.get("geotag_marker") and not f.get("true_time"):   # a corrected or kept time: no drift to check
                by_dest_group.setdefault((f["destination"], f["camera_group_key"]), []).append(f)
        resolved_by_path = {r["relative_path"]: r["resolved_utc"] for r in rows0
                            if r["resolved_utc_status"] == "valid"}
        for dest, d in (time_artifact.get("destinations") or {}).items():
            for bucket, cell in (d.get("camera_group_time_decisions") or {}).items():
                eff = cell.get("effective_time_anchor")
                if not (isinstance(eff, dict) and eff.get("source") in self._DRIFT_TRIGGER_SOURCES):
                    continue                                  # gpx-anchored (or unresolved) -> reliable / N/A
                group, date = cell.get("camera_group"), cell.get("date")
                frames = [f for f in by_dest_group.get((dest, group), [])
                          if date is None or _naive_date(f.get("source_naive_time")) == date]
                if (cell.get("phone") or {}).get("applies_to") == "untagged_photos":
                    frames = [f for f in frames if _own_offset(f) is None]     # the photos the cell offsets
                times = [t for f in frames if (t := _parse_utc(resolved_by_path.get(f["relative_path"])))]
                yield dest, bucket, cell, frames, times

    def _drift_cell(self, dest, bucket, time_cell, track_segment, frames, prior_cell, blockers, date=None,
                    track_sha=None):
        """One drift-validation bucket: the current offset, the covering GPX track + the bucket's
        frames (evidence the editor scrubs a photo along), the operator's explicit confirmation, and
        the validated/corrected offset compute_resolved_utc consumes. requires_user_input until
        `confirmed` is actively set (a zero-scrub counts only when the operator confirms it — inaction
        never satisfies the gate, RUL-untouched_check_confirms_nothing). `track_sha` is each track file's SHA-256
        by its path under gpx_root, as the tracks are now (GPXIndex.file_sha)."""
        track_sha = track_sha or {}
        eff = time_cell.get("effective_time_anchor") or {}
        current = eff.get("offset_seconds")
        loc = bucket
        prior_ud = prior_cell.get("user_decision") or {}
        confirmed = _decision_flag(prior_ud, "confirmed", f"{dest}: drift_decisions[{loc}].user_decision", blockers)
        corrected = prior_ud.get("corrected_offset_seconds", "")
        against = prior_ud.get("confirmed_offset_seconds", "")
        # The tracks shown: what a confirmation made now is made against, and what the editor writes with it
        # (BLD-drift_confirmation_tracks).
        shown = [{"gpx_file": f, "sha256": track_sha.get(f)} for f in sorted({p.source_file for p in track_segment})]
        named = prior_ud.get("confirmed_against_tracks")
        named_ok = isinstance(named, list) and all(
            isinstance(t, dict) and isinstance(t.get("gpx_file"), str) and t["gpx_file"]
            and isinstance(t.get("sha256"), str) and t["sha256"] for t in named)
        # A confirmation rests on the tracks it was made against (RUL-confirmation_rests_on_its_tracks): each still
        # under gpx_root with the SHA-256 it names. One made where no track was shown saw none, and holds only while
        # none is shown (RUL-trackless_confirmation_holds_while_none).
        changed = sorted({t["gpx_file"] for t in named if track_sha.get(t["gpx_file"]) != t["sha256"]}) \
            if named_ok else []
        tracks_hold = named_ok and (not shown if not named else not changed)
        if confirmed and not named_ok:
            blockers.append(f"{dest}: drift_decisions[{loc}].user_decision.confirmed_against_tracks must name the "
                            "tracks the confirmation was made against, each with its gpx_file and sha256.")
        effective, stale = "", False
        # Each offset written here is checked as written, the cell confirmed or not (RUL-checked_clock_offsets): one that
        # is no whole number of seconds is named now, not only once a confirmation would make it count.
        written = lambda v: v not in ("", None)
        bad_correction = written(corrected) and not _valid_offset(corrected)
        if bad_correction:
            blockers.append(f"{dest}: drift_decisions[{loc}].user_decision.corrected_offset_seconds "
                            "must be empty or a whole number of seconds.")
        # A confirmation names the offset it was made against (RUL-confirmation_holds_for_its_offset), and holds only
        # while that is the offset: changed in photos-21 since, it is stale — kept as written, applied to nothing, the
        # bucket asking again until confirmed anew. One naming none confirms nothing: a zero scrub is never implied.
        if written(against) and not _valid_offset(against):
            blockers.append(f"{dest}: drift_decisions[{loc}].user_decision.confirmed_offset_seconds "
                            "must be a whole number of seconds.")
            confirmed_ok = False
        elif confirmed and not written(against):
            blockers.append(f"{dest}: drift_decisions[{loc}].user_decision.confirmed_offset_seconds must be the "
                            f"offset confirmed — the current one is {current}.")
            confirmed_ok = False
        else:
            # a changed offset or changed tracks: the check asks again, the confirmation kept as written
            # (RUL-changed_offset_asked_again, RUL-changed_tracks_asked_again, RUL-stale_confirmation_kept)
            stale = bool(confirmed) and named_ok and (int(against) != current or not tracks_hold)
            confirmed_ok = bool(confirmed) and named_ok and not stale
        if confirmed_ok and not bad_correction:
            if not written(corrected):
                effective = {"offset_seconds": current, "source": "gps_drift_validated"}   # zero scrub
            else:
                effective = {"offset_seconds": int(corrected), "source": "gps_drift_validated"}
        # The editor scrubs a representative photo along the track: corrected_offset = (chosen track
        # time) - (that photo's camera naive). Expose every bucket frame (earliest first) so it can
        # default to one and let the operator cross-check others; re-extracted every run with the track.
        frame_rows = sorted(({"source_file": f.get("relative_path"),
                              "camera_naive": f.get("source_naive_time")} for f in frames),
                            key=lambda r: (r["camera_naive"] or "", r["source_file"] or ""))
        cell = {
            "camera_group": time_cell.get("camera_group"),
            "proposal": {
                "proposal_source": eff.get("source"),
                "current_offset_seconds": current,
                "frames": frame_rows,
                "track_segment": [{"lat": p.lat, "lon": p.lon,
                                   "time_utc": p.time_utc.strftime("%Y-%m-%dT%H:%M:%SZ")}
                                  for p in track_segment],
                "tracks": shown,
            },
            "user_decision": {"confirmed": confirmed,
                              "corrected_offset_seconds": corrected if corrected is not None else "",
                              "confirmed_offset_seconds": against if against is not None else "",
                              "confirmed_against_tracks": named if named is not None else []},
            # the named tracks no longer there with the SHA-256 named: the editor's view of what geotag found
            "confirmed_tracks_changed": changed,
            "effective_drift_offset": effective,
            "requires_user_input": effective == "",
            "stale_user_decision": stale,
        }
        if date is not None:
            cell["date"] = date
        if time_cell.get("day") is not None:
            cell["day"] = time_cell["day"]
        return cell

    def _drift_depends_on(self):
        policy = json.dumps((CONFIG.get("camera_time_and_timezone_policy") or {}), sort_keys=True)
        return {
            "photos_21_sha256": sha256_file(time_decisions_path(self.workspace_root)),
            "gpx_fingerprint": self._gpx_fingerprint,
            "camera_time_policy_fingerprint": sha256_text(policy),
            "camera_group_key_version": CAMERA_GROUP_KEY_VERSION,
        }

    # --- Stage 8: GPS decisions (photos-23, BLD-gps_decisions_record) --------

    _SUMMARY_KEYS = ("files_total", "preserve_native_gps", "automatic_gpx_interpolation",
                     "automatic_gpx_extrapolation", "automatic_folder_fallback", "manual_locked",
                     "manual_review_required", "blocked")

    # The reason of a review item the user adds for a photo the tracks or a fallback place, to give it a position of
    # its own choosing (BLD-chosen_position); geotag keeps it as a `manual_locked` item.
    _CHOSEN = "chosen_by_user"

    def build_gps_decisions(self, files, resolved_rows, gpx, prior, resolved_fp, contradicted=(), time_decisions=None):
        """Build/regenerate photos-23 (BLD-gps_decisions_record): the BLD-placement_order decision per by-dest file,
        grouped by destination: a summary of counts, the photos that ask or were answered as `review_items`, every
        other photo in `placed_photos` (BLD-placed_photos). Destinations are processed parent-first so a
        folder_fallback inherits its nearest ancestor's effective fallback (BLD-folder_fallback_cell). `contradicted`
        are the photos whose own position the offset agreed from their camera's GPS contradicts
        (`contradicted_positions`): each is set against the tracks at its corrected time (BLD-contradicted_position).
        `time_decisions` is photos-21, whose offset cells name each photo's camera bucket. Returns (artifact,
        blockers)."""
        contradicted = set(contradicted)
        time_dests = (time_decisions or {}).get("destinations") or {}
        reach = CONFIG["gpx_own_position_contradicted_distance_meters"]      # a setting of its own (RUL-setting_bounds_one_thing)
        blockers = _decision_shape_blockers(prior, "gps")
        if blockers:
            return None, blockers
        prior_dests = ((prior or {}).get("destinations")) or {}
        utc_by_path = {r["relative_path"]: r["resolved_utc"] for r in resolved_rows}
        by_dest = {}
        for f in files:
            by_dest.setdefault(f["destination"], []).append(f)

        destinations = {}
        disagreeing = {}                                      # (track, track) -> photos they place apart
        outranked = {}                                        # (lower track, the one placing) -> photos apart
        fallback_eff = {}                                     # (dest, None) -> the fallback written there
        ordered, containers = _expand_destinations(by_dest)
        self.coordinator.start_phase("deciding GPS placement", len(files))
        for dest in ordered:
            self.coordinator.set_detail(_dest_label(dest))
            is_container = dest in containers       # a file-less folder: its fallback only seeds children
            prior_d = prior_dests.get(dest, {})
            inherited = _nearest_ancestor(dest, fallback_eff, None)
            fb_cell = self._folder_fallback_cell(dest, prior_d.get("folder_fallback") or {}, inherited, blockers)
            eff_fb = fb_cell["effective_fallback"]
            if fb_cell["fallback_source"] == "own":
                # only a written fallback is one to inherit from: one inherited passes through, naming where it is written
                fallback_eff[(dest, None)] = eff_fb

            items = (prior_d.get("gps_decisions") or {}).get("review_items") or []
            prior_reviews = ({ri["content_fingerprint"]: ri for ri in items if ri.get("content_fingerprint")},
                             {ri["relative_path"]: ri for ri in items if not ri.get("content_fingerprint")})
            self._check_chosen_items(dest, items, by_dest.get(dest, []), blockers)
            cells = (time_dests.get(dest) or {}).get("camera_group_time_decisions") or {}
            counts = {k: 0 for k in self._SUMMARY_KEYS}
            review_items, gpx_files, untracked, placed = [], set(), [], []
            for f in sorted(by_dest.get(dest, []), key=lambda x: x["relative_path"]):
                rel = f["relative_path"]
                ru = _parse_utc(utc_by_path.get(rel)) if utc_by_path.get(rel) else None
                earlier = _prior_review(prior_reviews, f)
                fd = earlier.get("user_decision") or {}
                self._validate_review_decision(dest, rel, fd, blockers)
                own = None
                if f.get("has_native_gps"):
                    # an own position the camera's agreed offset contradicts (BLD-contradicted_position), or one the
                    # user replaced so on an earlier run — their answer kept while they keep it
                    answered = earlier.get("reason") == self._OWN_CONTRADICTED and \
                        fd.get("manual_lat") not in (None, "") and fd.get("manual_lon") not in (None, "")
                    if rel in contradicted or answered:
                        own = self._contradicted_position(f, ru, gpx, reach, answered)
                        if own is None:
                            untracked.append({"relative_path": rel, "content_fingerprint": f.get("content_fingerprint")})
                        elif own is self._WITHIN_REACH:
                            own = None              # the tracks place it by its own position: nothing contradicts it
                why = {}
                cat, coord = classify_gps(f, ru, gpx, CONFIG, eff_fb, fd, why, replace_own=own is not None)
                if why.get("reason") == "tracks_disagree":
                    disagreeing[tuple(why["gpx_files"])] = disagreeing.get(tuple(why["gpx_files"]), 0) + 1
                for lt in (coord or {}).get("lower_tracks") or []:
                    # a lower-ranked track farther from the place than tracks may differ: counted, never asked
                    # (RUL-lower_track_disagreements_told)
                    if lt["apart_meters"] > CONFIG["gpx_tracks_agree_max_distance_meters"]:
                        k = (lt["gpx_file"], coord["gpx_file"])
                        outranked[k] = outranked.get(k, 0) + 1
                counts["files_total"] += 1
                bucket = _camera_bucket(cells, f)
                n_review, n_placed = len(review_items), len(placed)
                if own is not None:
                    # the photo's own position kept, or replaced by the position the user set — the item asks nothing
                    # (RUL-contradicted_position_kept_unless_taken)
                    counts["preserve_native_gps" if cat == "preserve_native" else "manual_locked"] += 1
                    review_items.append(dict(self._review_item(f, self._OWN_CONTRADICTED, fd, False), **own))
                elif cat == "preserve_native":
                    counts["preserve_native_gps"] += 1
                    placed.append(self._placed_photo(f, "own_position"))
                elif cat in ("gpx_interpolation", "gpx_extrapolation"):
                    counts[f"automatic_{cat}"] += 1; gpx_files.add(coord.get("gpx_file"))
                    placed.append(dict(self._placed_photo(f, "tracks"), method=coord["method"]))
                elif cat == "manual_fallback":
                    # placed by the fallback: recorded with why the tracks did not (RUL-fallback_photo_says_why)
                    counts["automatic_folder_fallback"] += 1
                    placed.append(dict(self._placed_photo(f, "folder_fallback"), **({"tracks": why} if why else {})))
                elif cat == "manual_locked":
                    # a position the user set for it — on a photo nothing else placed, or one they chose over the
                    # tracks or the fallback (`chosen_by_user`): kept while it holds one (RUL-chosen_position_kept)
                    counts["manual_locked"] += 1
                    review_items.append(self._review_item(f, "manual_locked", fd, False))
                else:                                          # blocked
                    counts["blocked"] += 1
                    review_items.append(self._review_item(f, "no_reliable_gps_source", fd, True, why))
                if bucket is not None:
                    # the photo's camera day, as photos-21 keys its offset cell (BLD-placed_photos)
                    for entry in review_items[n_review:] + placed[n_placed:]:
                        entry["camera_bucket"] = bucket
                self.coordinator.increment_completed(1)
            counts["manual_review_required"] = sum(1 for ri in review_items if ri["requires_user_input"])
            destinations[dest] = {
                "destination_path": dest,
                "folder_fallback": fb_cell,
                "gps_decisions": {
                    "summary": counts,
                    "automatic_decision_summary": {
                        "gpx_files_used": sorted(g for g in gpx_files if g),
                    },
                    "review_items": review_items,
                },
            }
            if untracked:
                # contradicted, with no track to propose a position from: kept, and noted
                # (RUL-contradicted_position_without_track_noted)
                destinations[dest]["gps_decisions"]["contradicted_without_track"] = untracked
            if placed:
                # every photo no review item names, by path and how it is placed (BLD-placed_photos) — what a position
                # chosen for one of them names (BLD-chosen_position); never read by the plan, which places them again
                # from its own inputs
                destinations[dest]["gps_decisions"]["placed_photos"] = placed
            if is_container:
                destinations[dest]["file_less"] = True
        self.coordinator.finish_phase()

        requires = any(ri["requires_user_input"]
                       for d in destinations.values() for ri in d["gps_decisions"]["review_items"])
        artifact = {
            "artifact_type": "gps_decisions",
            "artifact_name": GPS_DECISIONS_ARTIFACT,
            "status": "requires_user_input" if requires else "complete",
            "requires_user_input": requires,
            "executable": False,
            "destinations": destinations,
            "depends_on": self._gps_depends_on(resolved_fp),
        }
        if not requires:
            artifact["decision_mode"] = "no_op_or_auto_resolved"
        # Tracks that put the same instant in different places placed none of these photos — each fell to
        # its folder's fallback or asks. Said out loud, since a fallback would otherwise hide it
        # (RUL-disagreeing_tracks_named).
        self.track_disagreements = [{"gpx_files": list(k), "photos": n} for k, n in sorted(disagreeing.items())]
        if self.track_disagreements:
            artifact["track_disagreements"] = self.track_disagreements
        # A lower-ranked track the placing one outranked, where it put photos farther away than tracks may differ:
        # the measure of the worse device's error, told and kept, never a question (RUL-lower_track_disagreements_told).
        self.lower_track_disagreements = [{"gpx_file": k[0], "outranked_by": k[1], "photos": n}
                                          for k, n in sorted(outranked.items())]
        if self.lower_track_disagreements:
            artifact["lower_track_disagreements"] = self.lower_track_disagreements
        return artifact, blockers

    # The reason of a review item for a photo whose own position its camera's agreed offset contradicts.
    _OWN_CONTRADICTED = "own_position_contradicted"
    # What _contradicted_position says of a photo the tracks place within reach of its own position.
    _WITHIN_REACH = object()

    def _contradicted_position(self, f, ru, gpx, reach, answered):
        """What a review item of a photo whose own position its camera's agreed clock offset contradicts carries
        (BLD-contradicted_position): `own_position`, `proposed_position` — where the tracks place it at its corrected
        time `ru` (`lat`, `lon`, `method`, `gpx_file`) — and `apart_meters`; None where the tracks place it nowhere,
        `_WITHIN_REACH` where they place it within `reach` of its own position
        (`gpx_own_position_contradicted_distance_meters`) — but for one the user `answered` on an earlier run, whose
        item stays while their answer does."""
        mine = {"lat": (f.get("native_gps") or {}).get("lat"), "lon": (f.get("native_gps") or {}).get("lon")}
        p = place_gps(ru, gpx, CONFIG) if ru is not None else None
        if p is None:
            return {"own_position": mine, "proposed_position": None, "apart_meters": None} if answered else None
        apart = round(haversine(float(mine["lat"]), float(mine["lon"]), p["lat"], p["lon"]))
        if apart <= reach and not answered:
            return self._WITHIN_REACH
        return {"own_position": mine, "apart_meters": apart,
                "proposed_position": {"lat": p["lat"], "lon": p["lon"], "method": p["method"], "gpx_file": p["gpx_file"]}}

    def authored_value_blockers(self, files, prior_drift, prior_gps):
        """Located blockers for the values the user wrote in photos-22 and photos-23 (BLD-geotag_checks_decisions),
        found before any decision record is written, so an invalid one stops the plan with nothing changed
        (RUL-invalid_value_stops) — each record's structure and fields, its drift answers' offsets and flags, its
        fallback and review positions, and the photos its chosen positions name. What these values decide is worked
        out by their stages, later; whether each can be taken at all does not wait for them."""
        out = []
        drift = _decision_shape_blockers(prior_drift, "drift")
        out += drift
        if not drift:
            for dest, d in sorted(((prior_drift or {}).get("destinations") or {}).items()):
                for loc, cell in sorted((d.get("drift_decisions") or {}).items()):
                    ud = cell.get("user_decision") or {}
                    where = f"{dest}: drift_decisions[{loc}].user_decision"
                    confirmed = _decision_flag(ud, "confirmed", where, out)
                    written = lambda v: v not in ("", None)
                    if written(ud.get("corrected_offset_seconds")) and not _valid_offset(ud["corrected_offset_seconds"]):
                        out.append(f"{where}.corrected_offset_seconds must be empty or a whole number of seconds.")
                    against = ud.get("confirmed_offset_seconds")
                    if written(against) and not _valid_offset(against):
                        out.append(f"{where}.confirmed_offset_seconds must be a whole number of seconds.")
                    elif confirmed and not written(against):
                        out.append(f"{where}.confirmed_offset_seconds must be the offset confirmed.")
                    named = ud.get("confirmed_against_tracks")
                    if confirmed and not (isinstance(named, list) and all(
                            isinstance(t, dict) and isinstance(t.get("gpx_file"), str) and t["gpx_file"]
                            and isinstance(t.get("sha256"), str) and t["sha256"] for t in named)):
                        out.append(f"{where}.confirmed_against_tracks must name the tracks the confirmation was "
                                   "made against, each with its gpx_file and sha256.")
        gps = _decision_shape_blockers(prior_gps, "gps")
        out += gps
        if not gps:
            by_dest = {}
            for f in files:
                by_dest.setdefault(f["destination"], []).append(f)
            for dest, d in sorted(((prior_gps or {}).get("destinations") or {}).items()):
                self._folder_fallback_cell(dest, d.get("folder_fallback") or {}, None, out)
                items = (d.get("gps_decisions") or {}).get("review_items") or []
                for ri in items:
                    self._validate_review_decision(dest, ri["relative_path"], ri.get("user_decision") or {}, out)
                self._check_chosen_items(dest, items, by_dest.get(dest, []), out)
        return out

    def _folder_fallback_cell(self, dest, prior_fb, inherited, blockers):
        """A destination's `folder_fallback` (BLD-folder_fallback_cell): the fallback it inherits from the nearest
        destination above it that has one written, applied by itself (RUL-inherited_fallback_applies), unless a
        position is written for the destination, which outranks it there and passes to the destinations beneath
        (RUL-written_fallback_over_inherited); emptied, the inherited one applies again. `inherited` is
        (ancestor, coordinate) or None. Never asks (RUL-fallback_optional)."""
        ud = prior_fb.get("user_decision") or {}
        flat, flon = ud.get("fallback_lat", ""), ud.get("fallback_lon", "")
        if _half_position(flat, flon):
            blockers.append(f"{dest}: folder_fallback.user_decision fallback_lat/lon must both be set, or neither.")
        cell = {
            "inherited_fallback": ({**inherited[1], "from": inherited[0]} if inherited is not None else None),
            "user_decision": {"fallback_lat": flat, "fallback_lon": flon},
            "effective_fallback": None,
            "fallback_source": "none",
            "requires_user_input": False,                     # the fallback is optional, never blocks
        }
        if flat not in (None, "") and flon not in (None, ""):
            if _valid_coord(flat, flon):
                cell["effective_fallback"], cell["fallback_source"] = {"lat": flat, "lon": flon}, "own"
            else:
                blockers.append(f"{dest}: folder_fallback.user_decision fallback_lat/lon out of range.")
        elif inherited is not None:
            cell["effective_fallback"], cell["fallback_source"] = dict(inherited[1]), "inherited"
            cell["inherited_from"] = inherited[0]
        return cell

    def _validate_review_decision(self, dest, rel, ud, blockers):
        mlat, mlon = ud.get("manual_lat", ""), ud.get("manual_lon", "")
        where = f"{dest}/{os.path.basename(rel)}"
        if _half_position(mlat, mlon):
            blockers.append(f"{where}: review manual_lat/lon must both be set, or neither.")
        elif mlat not in (None, "") and not _valid_coord(mlat, mlon):
            blockers.append(f"{where}: review manual_lat/lon out of range.")

    def _check_chosen_items(self, dest, items, files, blockers):
        """A review item the user added for a photo the tracks or the fallback place (`reason: "chosen_by_user"`,
        BLD-chosen_position) names a photo of this destination holding no position of its own — by its path, or its
        fingerprint — or is a blocker naming it (RUL-chosen_position_names_a_photo): an answer that would place nothing
        is never passed over."""
        by_path = {f["relative_path"]: f for f in files}
        # a photo is named by any fingerprint a decision for it can be recorded under (BLD-review_item_identity)
        by_fp = {k: f for f in files for k in _decision_keys(f)}
        for ri in items:
            if ri.get("reason") != self._CHOSEN:
                continue
            at_path, by_value = by_path.get(ri["relative_path"]), by_fp.get(ri.get("content_fingerprint"))
            f = at_path or by_value
            where = f"{dest}: gps_decisions.review_items[{ri['relative_path']}]"
            if f is None:
                blockers.append(f"{where}: a {self._CHOSEN} position names no photo of this destination — give the "
                                "path of one of its photos, or remove the entry.")
            elif ri.get("content_fingerprint") and by_value is not f:
                # an answer whose path and fingerprint name different photos — or whose fingerprint names none — would
                # be found by neither and dropped unseen (BLD-chosen_position)
                blockers.append(f"{where}: a {self._CHOSEN} position whose content_fingerprint names "
                                + ("no photo of this destination" if by_value is None else "another photo than its path")
                                + " — give the photo's own fingerprint, or remove the fingerprint and keep the path.")
            elif f.get("has_native_gps"):
                blockers.append(f"{where}: this photo holds a position of its own, which geotag keeps — remove the "
                                f"{self._CHOSEN} entry.")

    def _placed_photo(self, f, placed_by):
        """A photo its own position, the tracks or the folder fallback place, as photos-23's `placed_photos` lists it
        (BLD-placed_photos)."""
        return {"relative_path": f["relative_path"], "content_fingerprint": f.get("content_fingerprint"),
                "placed_by": placed_by}

    def _review_item(self, f, reason, ud, requires, why=None):
        item = {
            "relative_path": f["relative_path"], "content_fingerprint": f.get("content_fingerprint"),
            "reason": reason,
            "user_decision": {"manual_lat": ud.get("manual_lat", ""), "manual_lon": ud.get("manual_lon", "")},
            "requires_user_input": requires,
            "stale_user_decision": False,
        }
        if why:
            item["tracks"] = why                   # why the tracks placed nothing: the user's lead to a fix
        return item

    def _gps_depends_on(self, resolved_fp):
        gps_policy = json.dumps({k: CONFIG[k] for k in (
            "gpx_direct_match_max_seconds", "gpx_interpolation_max_gap_seconds",
            "gpx_interpolation_max_distance_meters", "gpx_interpolation_max_speed_kmh",
            "gpx_extrapolation_max_seconds", "gpx_extrapolation_heading_seconds",
            "gpx_extrapolation_max_distance_meters", "gpx_extrapolation_max_speed_kmh",
            "gpx_tracks_agree_max_distance_meters", "gpx_own_position_contradicted_distance_meters")}, sort_keys=True)
        return {
            # 22 is covered transitively: resolved_fp folds in photos_22_sha256 (BLD-resolved_utc_fingerprint), so a
            # changed drift confirmation already restales this. No separate 22 dep needed here.
            "resolved_utc_cache_fingerprint": resolved_fp,
            "gpx_fingerprint": self._gpx_fingerprint,
            "gps_policy_fingerprint": sha256_text(gps_policy),
            "handoff": self._handoff_dependency(self.workspace_root),
        }

    # --- Stage 9: executable plan (photos-24, BLD-executable_plan) -----------

    def build_executable_plan(self, files, resolved_rows, time_artifact, gps_artifact, gpx,
                              resolved_fp):
        """Assemble photos-24 (BLD-executable_plan): per-destination operations (corrected-time / GPS / marker /
        rename) for execution to apply, the
        readiness gate, and the flattened dependency cascade. Automatic GPS is re-derived from
        inputs, never read from the photos-23 summary. Deterministic. Returns (plan, blockers)."""
        cfg = CONFIG
        fmt = cfg["filename_timestamp_format"]
        utc_by_path = {r["relative_path"]: r for r in resolved_rows}
        t_dests = time_artifact.get("destinations") or {}
        g_dests = gps_artifact.get("destinations") or {}

        # Called only once photos-21, -22 and -23 are all complete (BLD-geotag_stage_order): run() gates it.
        blockers = []
        for f in files:
            row = utc_by_path.get(f["relative_path"])
            if not row or row.get("resolved_utc_status") != "valid":
                blockers.append(f"{f['relative_path']}: no valid resolved UTC.")
            changed = changed_time_blocker(f)     # a time put in the photo since geotag wrote it (BLD-changed_time_blocks)
            if changed:
                blockers.append(changed)

        by_dest = {}
        for f in files:
            by_dest.setdefault(f["destination"], []).append(f)
        aside_by_raw, aside_taken = self._set_aside_jpegs()

        destinations, all_ops, media_pre = {}, [], []
        placement = {}                                # how each photo comes by its position: the measure of the run
        for dest in sorted(by_dest):
            g_d = g_dests.get(dest, {})
            eff_fb = (g_d.get("folder_fallback") or {}).get("effective_fallback")
            reviews = {ri["relative_path"]: ri for ri in ((g_d.get("gps_decisions") or {}).get("review_items") or [])}
            track_of, lower_of = {}, {}
            tz = ((t_dests.get(dest, {}).get("destination_timezone")) or {}).get("effective_iana_timezone") or ""
            rename_inputs = [{"relative_path": f["relative_path"],
                              "resolved_utc": (utc_by_path.get(f["relative_path"]) or {}).get("resolved_utc"),
                              "destination_timezone": tz, "sub_second": f.get("sub_second"),
                              "source_naive_time": f.get("source_naive_time")} for f in by_dest[dest]]
            renames = {r["relative_path"]: r for r in plan_renames(rename_inputs, fmt)}

            ops, no_ops = [], []
            for f in sorted(by_dest[dest], key=lambda x: x["relative_path"]):
                rel = f["relative_path"]
                ru = (utc_by_path.get(rel) or {}).get("resolved_utc")
                item = reviews.get(rel) or {}
                cat, coord = classify_gps(f, _parse_utc(ru) if ru else None, gpx, cfg, eff_fb, item.get("user_decision"),
                                          replace_own=item.get("reason") == self._OWN_CONTRADICTED)
                if coord and coord.get("gpx_file"):
                    track_of[rel] = coord["gpx_file"]
                    lower_of[rel] = coord.get("lower_tracks")
                how = "native" if cat == "preserve_native" else _TRACK_MARKER.get((coord or {}).get("method")) or cat
                placement[how] = placement.get(how, 0) + 1
                fops = plan_file_ops(f, ru, tz, cat, coord, renames.get(rel))
                row = utc_by_path.get(rel) or {}
                cells = (t_dests.get(dest) or {}).get("camera_group_time_decisions") or {}
                for o in fops:
                    # what this pass established and which decision it followed, kept with the write so a
                    # later finalize can log it once a later pass has replaced the resolved-UTC cache
                    # (BLD-geotag_log_steps)
                    if o["type"] == "metadata_time_write":
                        o["provenance"] = {
                            "resolved_utc": row.get("resolved_utc"), "time_rule_used": row.get("time_rule_used"),
                            "utc_offset_used": row.get("utc_offset_used"), "destination_timezone": tz,
                            "source_time_provenance": row.get("source_time_provenance"),
                            "timezone_because": f"photos-21 destinations.{dest}.destination_timezone",
                            "because": offset_decision_pointer(
                                dict(row, camera_group=row.get("camera_group") or f.get("camera_group_key")), dest, cells)}
                        if f.get("true_time"):
                            # no clock offset decided it: the user's word that this is its true time, given in this
                            # photos-21, or on an earlier pass and kept beside its pin (BLD-log_format)
                            o["provenance"].pop("because")
                            if f.get("time_kept"):
                                o["provenance"]["because"] = f"photos-21 destinations.{dest}.changed_times[{rel}]"
                        elif untimed(f):
                            # no time of its own: its folder's date fallback, as given and where it was given
                            # (RUL-date_fallback_recorded)
                            eff = ((t_dests.get(dest) or {}).get("date_fallback") or {}).get("effective_date") or {}
                            o["provenance"]["because"] = f"photos-21 destinations.{eff.get('set_at')}.date_fallback"
                            o["provenance"]["date_fallback"] = {k: eff.get(k) for k in ("date", "filled", "set_at")}
                        o["pre_state"] = held_time_pre_state(f, o["writes"])   # every value it replaces, for the log
                    elif o["type"] == "metadata_gps_write" and o.get("gps_origin") == "recompute_automated":
                        # the track that placed it, and the instant it was placed at: what the position rests on
                        o["provenance"] = {"gpx_file": track_of.get(rel), "resolved_utc": ru}
                        if lower_of.get(rel):
                            # how far each lower-ranked track put it (RUL-lower_track_distance_recorded)
                            o["provenance"]["lower_tracks"] = lower_of[rel]
                        if holds_no_fix(f):                   # the device's no-fix value it replaces, for the log
                            o["pre_state"] = held_pre_state(f)   # (RUL-log_records_null_island_replaced)
                    elif o["type"] == "metadata_gps_write" and o.get("gps_origin") == "apply_manual":
                        o["provenance"] = {"because": manual_gps_pointer(cat, dest, rel, g_d.get("folder_fallback"))}
                        o["pre_state"] = held_pre_state(f)        # the position it replaces, for the log
                    elif o["type"] == "metadata_gps_write" and o.get("gps_origin") == "restore_own":
                        # its own position given back: the log keeps the one it replaces (RUL-log_records_gps_reverts)
                        o["pre_state"] = held_pre_state(f)
                    elif o["type"] == "gps_marker_write" and (o.get("writes") or {}).get("GPSLatitude") == "":
                        o["pre_state"] = held_pre_state(f)        # the position it clears, for the log
                if fops:
                    ops.extend(fops)
                else:
                    no_ops.append(rel)
                # The JPEG prep set aside beside this RAW is renamed with it, and nothing else is done to it: the one
                # change geotag makes outside photos by destination (RUL-set_aside_jpeg_renamed_with_raw). One an earlier
                # run left behind its corrected RAW takes the name the RAW holds (RUL-set_aside_jpeg_catches_up).
                # The mark is the one the RAW holds: a RAW geotag wrote and pinned is decided from its own values,
                # which hold none (BLD-set_aside_jpeg_catches_up).
                raw_rename = next((o for o in fops if o["type"] == "rename_no_clobber"), None)
                raw_name, follows = ((raw_rename["to"], raw_rename["operation_id"]) if raw_rename
                                     else (os.path.basename(rel), None)
                                     if geotag_marker(held_values(f).get("method")) else (None, None))
                for j in (aside_by_raw.get(f.get("content_fingerprint")) or []) if raw_name else []:
                    jop = plan_set_aside_rename(rel, raw_name, j, aside_taken, follows)
                    if jop is not None:
                        ops.append(jop)
                        media_pre.append({k: j.get(k) for k in ("relative_path", "content_fingerprint", "size",
                                                                "mtime_ns")})
                media_pre.append({"relative_path": rel, "content_fingerprint": f.get("content_fingerprint"),
                                  "size": f.get("size"), "mtime_ns": f.get("mtime_ns")})
            destinations[dest] = {"destination_path": dest, "operations": ops, "no_ops": no_ops}

        for dest, dd in destinations.items():
            ops = dd["operations"]
            all_ops.extend(ops)
            dd["summary"] = {
                "operations_total": len(ops), "no_ops": len(dd["no_ops"]),
                "metadata_time_writes": sum(1 for o in ops if o["type"] == "metadata_time_write"),
                "metadata_gps_writes": sum(1 for o in ops if o["type"] == "metadata_gps_write"),
                "gps_marker_writes": sum(1 for o in ops if o["type"] == "gps_marker_write"),
                "renames": sum(1 for o in ops if o["type"] == "rename_no_clobber"),
            }

        planned_op_fp = sha256_text(json.dumps(all_ops, sort_keys=True))
        depends_on = self._exec_depends_on(resolved_fp, media_pre, planned_op_fp)
        # the window the tracks' fingerprint is of: execute and finalize take it again over the same times
        # (BLD-track_window)
        depends_on["gpx_window"] = [list(span) for span in (gpx.window if gpx is not None else [])]
        plan = {
            "artifact_type": "executable_plan",
            "artifact_name": EXECUTABLE_PLAN_ARTIFACT,
            "plan_id": sha256_text(json.dumps(depends_on, sort_keys=True))[:16],
            "status": "blocked" if blockers else "ready",
            "executable": not blockers,
            "blockers": blockers,
            "placement": dict(sorted(placement.items())),
            # the times the user kept as the photos' true ones, which execution records beside their pins
            # (BLD-changed_time_kept_pinned)
            "true_times_kept": {f["relative_path"]: dict(f["time_kept"],
                                                         content_fingerprint=f.get("content_fingerprint"))
                                for f in sorted(files, key=lambda x: x["relative_path"]) if f.get("time_kept")},
            # the kept times whose answer was withdrawn and answered otherwise, which execution takes out of the pins
            "true_times_dropped": sorted(f["relative_path"] for f in files
                                         if f.get("kept_time_withdrawn") and not f.get("time_kept")),
            "destinations": destinations,
            "depends_on": depends_on,
        }
        return plan, blockers

    def _set_aside_jpegs(self):
        """`(by RAW, taken)`: the JPEGs prep set aside beside a RAW, from the handoff, by their RAW's fingerprint
        (BLD-set_aside_pair_recorded) — each one still on disk as the handoff recorded it; one gone or changed since is
        left as it is — and every name in redundant JPEGs, case folded (BLD-set_aside_renamed_with_raw)."""
        aside = folder_name('redundant_jpgs')
        by_raw, taken = {}, set()
        for rec in (self.handoff or {}).get("files") or []:
            if rec.get("folder_class") != aside:
                continue
            rel = rec.get("relative_path") or ""
            taken.add(os.path.basename(rel).lower())
            if not rec.get("raw_fingerprint"):
                continue
            try:
                st = os.stat(os.path.join(self.workspace_root, rel))
            except OSError:
                continue
            if (st.st_size, st.st_mtime_ns) != (rec.get("size"), rec.get("mtime_ns")):
                continue
            by_raw.setdefault(rec["raw_fingerprint"], []).append({
                "relative_path": rel, "content_fingerprint": _recorded_fingerprint(rec),
                "size": rec.get("size"), "mtime_ns": rec.get("mtime_ns")})
        return by_raw, taken

    def _exec_depends_on(self, resolved_fp, media_pre, planned_op_fp):
        ws = self.workspace_root
        cam = json.dumps(CONFIG.get("camera_time_and_timezone_policy") or {}, sort_keys=True)
        return {
            "time_decisions": json_dependency(TIME_DECISIONS_ARTIFACT, ws, time_decisions_path(ws)),
            "drift_validation": json_dependency(DRIFT_VALIDATION_ARTIFACT, ws, drift_validation_path(ws)),
            "gps_decisions": json_dependency(GPS_DECISIONS_ARTIFACT, ws, gps_decisions_path(ws)),
            "resolved_utc_cache_fingerprint": resolved_fp,
            "config_fingerprint": sha256_file(config_path(ws)),
            "code_fingerprint": code_fingerprint(),   # carried out only by the code that made it
            "camera_group_fingerprint": sha256_text(cam),
            "camera_group_key_version": CAMERA_GROUP_KEY_VERSION,
            "handoff": self._handoff_dependency(ws),
            "prep_cache_fingerprint": (self.handoff or {}).get("cache_fingerprint"),
            "gpx_fingerprint": self._gpx_fingerprint,
            "metadata_field_set_version": FIELD_SET_VERSION,
            "filename_format_fingerprint": sha256_text(CONFIG["filename_timestamp_format"]),
            "folders_fingerprint": folders_fingerprint(),
            "media_extensions_fingerprint": media_extensions_fingerprint(),
            "media_preconditions": media_pre,
            "planned_operation_fingerprint": planned_op_fp,
            # the table of countries the decisions were made from, and where it came from (BLD-country_table_dependency)
            "country_table": _country_table_dependency(ws),
        }

    # --- Stage 10: execution (photos-25, BLD-geotag_execution) ---------------

    _META_OP_TYPES = ("metadata_time_write", "metadata_gps_write", "gps_marker_write")
    _OP_TOTAL_KEY = {"metadata_time_write": "metadata_time_writes", "metadata_gps_write": "metadata_gps_writes",
                     "gps_marker_write": "gps_marker_writes", "rename_no_clobber": "renames"}

    def _exiftool_write(self, abs_path, tags):
        """Apply a file's batched tag writes so that an interruption at any moment — a kill or a power cut — leaves
        the photo as it was or wholly rewritten (BLD-metadata_safe_write): exiftool writes the new file beside the
        photo as `<file>_exiftool_tmp`, never touching the photo; that file is synced to disk, then renamed over the
        photo, then the folder synced. Returns True on success; otherwise the reason it could not write — exiftool's
        own message, or the error that stopped it — kept beside the photo's failure (BLD-write_failure_reason). The
        single seam the tests mock to avoid invoking exiftool.

        A `<file>_exiftool_tmp` already beside the photo is never removed here: the caller clears geotag's own
        (`_clear_own_leftover`), and any other is left where it is, the write failing as exiftool would
        (BLD-own_leftover_cleared)."""
        tmp = abs_path + "_exiftool_tmp"
        if os.path.lexists(tmp):
            return f"{os.path.basename(tmp)} is beside it and was left where it is"
        cmd = (["exiftool", "-n"] + [f"-{k}={v}" for k, v in sorted(tags.items())] + ["-o", tmp, abs_path])
        try:
            out = subprocess.run(cmd, capture_output=True, text=True, stdin=subprocess.DEVNULL)
            if out.returncode != 0:
                # exiftool's own words, which tell a damaged file from a passing trouble (BLD-write_failure_reason)
                said = " ".join(((out.stderr or "").strip() or (out.stdout or "").strip()).split())
                failure = said or f"exiftool exited with status {out.returncode}"
                try:
                    os.remove(tmp)
                except OSError:
                    pass
                return failure
            st = os.stat(abs_path)
            os.chmod(tmp, stat.S_IMODE(st.st_mode))          # the photo keeps the permissions it had
            try:
                os.chown(tmp, st.st_uid, st.st_gid)
            except OSError:
                pass                                         # not ours to give: the photo becomes the user's own
            replace_durably(tmp, abs_path)
            return True
        except Exception as e:
            try:
                os.remove(tmp)
            except OSError:
                pass
            return f"{type(e).__name__}: {e}"

    def _exiftool_read(self, abs_path, keys):
        """The file's current values of `keys`, numeric (-n), as exiftool reports them; {} if it cannot be read.
        The seam the tests mock, beside `_exiftool_write`."""
        # A key naming its group (`IPTC:DateCreated`) is read by group, every group apart (-a -G0), so it is reported
        # under that name; a plain one as exiftool's own choice among the groups holding it.
        held = {}
        try:
            for ks, opts in (([k for k in keys if ":" not in k], []), ([k for k in keys if ":" in k], ["-a", "-G0"])):
                if not ks:
                    continue
                out = subprocess.run(["exiftool", "-j", "-n"] + opts + [f"-{k}" for k in ks] + [abs_path],
                                     capture_output=True, text=True, stdin=subprocess.DEVNULL)
                if out.returncode != 0:
                    return {}
                held.update((json.loads(out.stdout) or [{}])[0])
            return held
        except Exception:
            return {}

    def revalidate_plan(self, plan, gpx, *, with_handoff=True):
        """BLD-geotag_execution's revalidation: recompute every dependency fingerprint and return the stale reasons. A
        non-empty list means reject the plan before ANY mutation (the user re-runs to replan)."""
        ws = self.workspace_root
        dep = plan.get("depends_on") or {}
        stale = []
        if plan.get("status") != "ready":
            stale.append(f"plan status is {plan.get('status')!r}, not 'ready'")
        for key in ("time_decisions", "drift_validation", "gps_decisions"):
            if not (dep.get(key) and verify_json_dependency(dep[key], ws)):
                stale.append(f"{key} dependency changed or missing")
        if with_handoff and not (dep.get("handoff") and self._verify_handoff_dependency(dep["handoff"], ws)):
            stale.append("handoff dependency changed or missing")   # content fingerprint, not file bytes
        policy = json.dumps(CONFIG.get("camera_time_and_timezone_policy") or {}, sort_keys=True)
        for k, cur in (("code_fingerprint", code_fingerprint()),
                       ("config_fingerprint", sha256_file(config_path(ws))),
                       ("filename_format_fingerprint", sha256_text(CONFIG["filename_timestamp_format"])),
                       ("folders_fingerprint", folders_fingerprint()),
                       ("media_extensions_fingerprint", media_extensions_fingerprint()),
                       ("camera_group_fingerprint", sha256_text(policy)),
                       ("camera_group_key_version", CAMERA_GROUP_KEY_VERSION),
                       ("metadata_field_set_version", FIELD_SET_VERSION),
                       ("gpx_fingerprint", gpx.fingerprint),
                       ("country_table", _country_table_dependency(ws))):
            if dep.get(k) != cur:
                stale.append(f"{k} changed")
        # The tracks that cannot be checked count as changed (RUL-unchecked_counts_as_changed): a gpx_root not
        # there or a folder of it that cannot be listed, or a plan naming no window to check them over.
        if gpx.status in ("missing", "unlisted"):
            stale.append("the tracks cannot be checked: " + gpx.warnings[-1])
        if valid_window(dep.get("gpx_window")) is None:
            stale.append("gpx_window missing or malformed: the tracks cannot be checked")
        all_ops = [o for d in plan["destinations"].values() for o in d["operations"]]
        if dep.get("planned_operation_fingerprint") != sha256_text(json.dumps(all_ops, sort_keys=True)):
            stale.append("planned operations changed (plan tampered)")
        # Every write is checked by taking the photo's fingerprint again: with another image engine than
        # the one prep took them with, every photo would be written and then held as changed
        # (RUL-engine_checked_before_writes). Prep always records its engine: a handoff that names none cannot
        # vouch for the engine, so it stops execution like another engine would.
        if with_handoff and all_ops:
            try:
                with open(handoff_path(ws)) as hf:
                    engine = (((json.load(hf) or {}).get("depends_on") or {}).get("cache") or {}).get("image_engine_version")
            except (OSError, ValueError):
                engine = None
            if engine is None:
                stale.append("the handoff records no image engine the photos were fingerprinted with "
                             "— run `prep plan` and `prep execute` first")
            elif engine != get_imagemagick_version():
                stale.append(f"the image engine changed since prep fingerprinted the photos ({engine} -> "
                             f"{get_imagemagick_version()}) — run `prep plan` and `prep execute` first")
        return stale

    @staticmethod
    def _target_occupied(directory, target_name, source_name):
        """Execute-time no-clobber recheck (RUL-target_free_at_execute): is `target_name` already present
        (case-insensitively) in `directory`, ignoring the source file being renamed away?"""
        low = target_name.lower()
        try:
            return any(e.lower() == low and e != source_name for e in os.listdir(directory))
        except OSError:
            # a folder that cannot be listed cannot be checked: its target counts as taken
            # (RUL-unchecked_counts_as_changed)
            return True

    def _apply_file(self, rel, ops, journal, accepted_mismatches):
        """Apply one file's operations: its metadata writes batched into a single exiftool call, then
        its rename — with execute-time precondition + no-clobber rechecks and a post-write content-
        fingerprint verify. Returns a per-file result the caller merges (no shared-state mutation).

        Crash-resumable (BLD-geotag_execution): a file already applied by a crashed prior run is detected by its
        target state — its planned rename target in place (source gone), or its decoded-content
        fingerprint still matching the plan despite a changed size/mtime (a metadata write only) — and
        is skipped or re-applied idempotently rather than tripping the size/mtime precondition."""
        abs_path = os.path.join(self.workspace_root, rel)
        res = {"relative_path": rel, "applied": [], "skipped": [], "failed": [], "blocker": None,
               "mismatch": None}
        if all(journal.get(o["operation_id"]) == "confirmed" for o in ops):
            res["skipped"] = [o["operation_id"] for o in ops]
            return res
        pre = ops[0].get("preconditions") or {}
        rename_ops = [o for o in ops if o["type"] == "rename_no_clobber"]
        write_ops = [o for o in ops if o["type"] in self._META_OP_TYPES]
        tags = {}
        for o in write_ops:
            tags.update(o.get("writes") or {})
        final_abs = os.path.join(os.path.dirname(abs_path), rename_ops[-1]["to"]) if rename_ops else abs_path

        def done(path):
            st = os.stat(path)
            res["after"] = {"relative_path": os.path.relpath(path, self.workspace_root),
                            "size": st.st_size, "mtime_ns": st.st_mtime_ns}
            return res

        if not os.path.exists(abs_path):
            # Already-applied resume: the source is gone and the planned rename target is in place — an
            # interrupted run applied this file and never got to record it. It is recorded now, once it
            # is seen to be that photo holding what was planned: a file merely of that name is not it.
            if rename_ops and os.path.exists(final_abs):
                cur_fp = (ContentHasher.fingerprint_image(final_abs) or {}).get("value")
                if (cur_fp is None or (cur_fp != pre.get("content_fingerprint") and accepted_mismatches.get(rel) != cur_fp)
                        or (tags and not _holds_writes(self._exiftool_read(final_abs, sorted(tags)), tags))):
                    res["blocker"] = (f"{rel}: gone, and {rename_ops[-1]['to']!r} in its place is not this photo "
                                      "as planned — re-run `geotag plan`")
                    return res
                res["skipped"] = res["found"] = [o["operation_id"] for o in ops]   # done before: recorded, not redone
                return done(final_abs)
            # A change of case alone interrupted between its two moves: the photo sits under the temporary name.
            # Once seen to be this photo holding what was planned, the second move completes it (BLD-case_rename_via).
            via = next((o for o in rename_ops if o.get("via")), None)
            via_abs = os.path.join(os.path.dirname(abs_path), via["via"]) if via else None
            if via_abs and os.path.exists(via_abs) and not os.path.exists(final_abs):
                cur_fp = (ContentHasher.fingerprint_image(via_abs) or {}).get("value")
                if (cur_fp is None or (cur_fp != pre.get("content_fingerprint") and accepted_mismatches.get(rel) != cur_fp)
                        or (tags and not _holds_writes(self._exiftool_read(via_abs, sorted(tags)), tags))):
                    res["blocker"] = (f"{rel}: gone, and {via['via']!r} in its place is not this photo "
                                      "as planned — re-run `geotag plan`")
                    return res
                try:
                    _move_no_clobber(via_abs, final_abs)
                except Exception as e:
                    res["failed"].append(via["operation_id"])
                    res["error"] = f"{type(e).__name__}: {e}"
                    res["blocker"] = f"{rel}: rename failed ({e})"
                    return res
                res["found"] = [o["operation_id"] for o in ops if o is not via]
                res["applied"].append(via["operation_id"])
                return done(final_abs)
            res["blocker"] = f"{rel}: file is missing at execute time"
            return res

        st = os.stat(abs_path)
        already_written = False
        if (pre.get("size") is not None and st.st_size != pre["size"]) or \
           (pre.get("mtime_ns") is not None and st.st_mtime_ns != pre["mtime_ns"]):
            # The file differs from plan time. A differing decoded-content fingerprint is the image itself
            # changed: block (unless the operator already accepted this file's new identity). Otherwise its
            # metadata changed — geotag's own write from an interrupted run, which left it holding the planned
            # values, or an edit made since the plan, which would be overwritten: read the tags back and tell
            # them apart (RUL-applied_unrecorded_is_recorded). A file with no write planned was not written by
            # geotag at all.
            cur_fp = (ContentHasher.fingerprint_image(abs_path) or {}).get("value")
            if cur_fp is None or (cur_fp != pre.get("content_fingerprint") and accepted_mismatches.get(rel) != cur_fp):
                res["blocker"] = f"{rel}: size/mtime changed and content fingerprint differs since planning"
                return res
            if not tags or not _holds_writes(self._exiftool_read(abs_path, sorted(tags)), tags):
                res["blocker"] = (f"{rel}: its metadata changed since the plan was made — re-run `geotag plan` "
                                  "to plan from what it holds now")
                return res
            already_written = True                    # geotag's own interrupted write: apply nothing again

        # the metadata ops produce a single batched, idempotent exiftool tag write
        if write_ops and already_written:
            res["applied"].extend(o["operation_id"] for o in write_ops)
        elif write_ops:
            # A leftover of an interrupted write beside the photo is cleared only where this plan's journal shows its
            # write begun and never confirmed — the one geotag's own write leaves. Any other may be the only whole copy
            # of something: the photo is held back, the leftover named and left where it is (BLD-own_leftover_cleared).
            own = any(journal.get(o["operation_id"]) == "begun" for o in write_ops)
            leftover = abs_path + "_exiftool_tmp"
            if not own and os.path.lexists(leftover):
                res["blocker"] = (f"{rel}_exiftool_tmp: an interrupted metadata write's leftover beside {rel}, which "
                                  "this plan's execution did not leave — it may be the only whole copy of something, "
                                  "so it was left where it is. Move it out of the workspace, then run `geotag plan`")
                return res
            if own:
                self._clear_own_leftover(leftover)
            self._note_writes_begun(journal, [o["operation_id"] for o in write_ops])
            written = self._exiftool_write(abs_path, tags)
            if written is not True:
                res["failed"] = [o["operation_id"] for o in write_ops]
                res["error"] = written              # exiftool's reason, kept beside the failure (BLD-write_failure_reason)
                return res                          # tool failure: leave file as-is, never confirm
            new_fp = (ContentHasher.fingerprint_image(abs_path) or {}).get("value")
            # a fingerprint that cannot be taken proves nothing: the write is not confirmed by it
            if new_fp is not None and (new_fp == pre.get("content_fingerprint") or accepted_mismatches.get(rel) == new_fp):
                res["applied"].extend(o["operation_id"] for o in write_ops)
            else:
                res["mismatch"] = {"relative_path": rel, "expected_fingerprint": pre.get("content_fingerprint"),
                                   "actual_fingerprint": new_fp}
                return res                          # content altered & not accepted: no confirm, no rename

        for o in rename_ops:
            d = os.path.dirname(abs_path)
            if self._target_occupied(d, o["to"], o["from"]):
                res["blocker"] = f"{rel}: rename target {o['to']!r} is occupied at execute time"
                return res
            if o.get("via") and self._target_occupied(d, o["via"], o["from"]):
                res["blocker"] = f"{rel}: rename target {o['via']!r} is occupied at execute time"
                return res
            try:
                if o.get("via"):
                    # a change of case alone, in two no-clobber moves by the free temporary name (BLD-case_rename_via)
                    _move_no_clobber(abs_path, os.path.join(d, o["via"]))
                    _move_no_clobber(os.path.join(d, o["via"]), os.path.join(d, o["to"]))
                else:
                    _move_no_clobber(abs_path, os.path.join(d, o["to"]))
                res["applied"].append(o["operation_id"])
            except Exception as e:
                res["failed"].append(o["operation_id"])
                res["error"] = f"{type(e).__name__}: {e}"
                res["blocker"] = f"{rel}: rename failed ({e})"
                return res
        return done(final_abs)

    @staticmethod
    def _clear_own_leftover(leftover):
        """Remove the leftover geotag's own interrupted write left beside a photo (BLD-own_leftover_cleared): the
        photo is whole — the write puts the new file in its place only once it is complete — and the leftover a
        partial copy of it."""
        try:
            os.remove(leftover)
        except FileNotFoundError:
            pass                                    # the write was begun, its output never opened

    def _note_writes_begun(self, journal, oids):
        """Note in the journal, before a photo's tags are written, that its write operations are begun, and persist it
        (BLD-own_leftover_cleared): a leftover an interruption leaves beside the photo is then known as geotag's own.
        An operation already confirmed is left so."""
        with self._journal_lock:
            for oid in oids:
                if journal.get(oid) != "confirmed":
                    journal[oid] = "begun"
            if self._journal_out is not None:
                self._journal_out(journal)

    def _apply_file_contained(self, rel, ops, journal, accepted_mismatches):
        """`_apply_file`, with anything it raises turned into that photo's failure: one photo's trouble
        never takes the run down around the others still being applied, whose results would then go
        unrecorded (RUL-one_photo_failure_contained). What was written before the failure is found again by the
        next run."""
        try:
            return self._apply_file(rel, ops, journal, accepted_mismatches)
        except Exception as e:
            return {"relative_path": rel, "applied": [], "skipped": [], "mismatch": None,
                    "failed": [o["operation_id"] for o in ops if journal.get(o["operation_id"]) != "confirmed"],
                    "error": f"{type(e).__name__}: {e}",
                    "blocker": f"{rel}: could not be applied ({type(e).__name__}: {e})"}

    def execute_plan(self, jobs, now_iso, execution_id, workspace_changes=()):
        """Stage 10 (BLD-geotag_execution): apply photos-24 after re-validating every dependency, journaling for
        idempotent resume, verifying content fingerprints, and writing photos-25. now_iso /
        execution_id are injected so the fingerprint-bearing body stays reproducible. Returns the
        summary dict (status 'rejected' with stale reasons if the plan no longer applies)."""
        ws = self.workspace_root
        # a plan there that cannot be read raises UnreadablePlan before anything is read or written (BLD-unreadable_plan)
        plan = read_executable_plan(ws)
        if plan is None:
            raise UnreadablePlan(executable_plan_path(ws), "it is not there")
        # the tracks over the plan's window as they are now, the record left as it is (BLD-track_window)
        gpx = self.plan_tracks(plan)
        stale = self.revalidate_plan(plan, gpx)
        if stale:
            return {"status": "rejected", "plan_id": plan.get("plan_id"), "stale": stale}
        # The records of this plan's earlier runs are read before anything is kept, snapshotted or written: one
        # that cannot be read stops the run (UnreadableRecord), never taken for none — the journal's confirmations
        # and the summary's acceptances would be written over (RUL-unreadable_execution_record_stops).
        jpath = journal_path(ws, plan["plan_id"])
        _j = _read_record(jpath) or {}
        journal, media_after = _j.get("operations") or {}, _j.get("media_after") or {}
        self._journal_changes = journal_kept_changes(jpath)    # carried over by each write (BLD-workspace_changes_logged)
        # the user's acceptances of changed content are checked as every decision is, before anything is done
        # (BLD-geotag_checks_decisions): an invalid one stops the run, located, the record left as it is
        invalid = self._mismatch_decision_blockers(ws, plan["plan_id"])
        if invalid:
            return {"status": "rejected", "plan_id": plan.get("plan_id"), "stale": invalid, "invalid": True}
        accepted = self._accepted_mismatches(ws, plan["plan_id"])
        # the failures the previous execution of this plan recorded: a write failing again the same way is told
        # with its way out (BLD-repeated_write_failure)
        prior_failures = self._prior_failures(ws, plan["plan_id"])

        # Optional pre-mutation ZFS snapshot (BLD-geotag_execution), labelled "geotag" so it never collides
        # with prep's "prep-" snapshot. A REQUIRED snapshot that cannot be taken aborts before any
        # mutation; the record is carried into photos-25 either way.
        snapshot = take_zfs_snapshot(ws, plan["plan_id"], "geotag")
        if snapshot is not None and snapshot["required"] and not snapshot["ok"]:
            reason = f"required ZFS pre-mutation snapshot failed: {snapshot['stderr']}"
            # Nothing was mutated, but BLD-execution_summary requires the snapshot record be carried into photos-25
            # either way, so the abort is auditable like any other run; the earlier summary is set aside under
            # -NNN, never written over (BLD-geotag_records_versioned).
            write_versioned_json(execution_summary_path(ws), {
                "artifact_type": "execution_summary", "artifact_name": EXECUTION_SUMMARY_ARTIFACT,
                "schema_version": 1, "plan_id": plan.get("plan_id"), "status": "rejected",
                "snapshot": snapshot, "blockers": [reason], "failures": [], "repeated_failures": [],
                # the mismatches still open, the user's acceptances with them, stay readable where the next run
                # looks for them (BLD-execution_summary_written, RUL-content_acceptance_stays_open)
                "fingerprint_mismatches": self._prior_mismatches(ws, plan.get("plan_id")),
                "run_metadata": {"execution_id": execution_id, "started_at": now_iso,
                                 "finished_at": now_iso, "jobs": jobs},
            })
            return {"status": "rejected", "plan_id": plan.get("plan_id"),
                    "stale": [reason], "snapshot": snapshot}
        # Only a run that goes on to change photos keeps its decisions and records its tracks: one a required snapshot
        # ended executed nothing (BLD-geotag_execution, BLD-withdrawn_track_points).
        self._keep_executed_decisions(plan)
        # the tracks this plan places and times photos by stay in the record if they leave gpx_root
        # (RUL-withdrawn_track_points_kept), their points in its window whatever a later plan's reaches
        GPXIndex.mark_used(db_path(ws), plan["plan_id"], self._tracks_used(plan),
                           valid_window((plan.get("depends_on") or {}).get("gpx_window")) or [])

        by_file = {}
        for dd in plan["destinations"].values():
            for op in dd["operations"]:
                by_file.setdefault(op["relative_path"], []).append(op)

        results = []
        # Noted as begun before the first photo is touched, so a hard kill's work is recognised by the next check from
        # this plan's journal (BLD-interrupted_run_recognised); the record the finally writes clears the note.
        note_execution_begun(ws, "geotag", plan["plan_id"])
        ended = False
        try:
            summary = self._apply_plan(plan, gpx, journal, media_after, jpath, accepted, prior_failures, by_file,
                                       results, snapshot, jobs, now_iso, execution_id, workspace_changes)
            ended = True
            return summary
        finally:
            # The state this run leaves, whether or not each photo was applied (RUL-execution_records_state): geotag's
            # writes give a photo a new inode, size and time, and its renames a new name — recorded, they are no change
            # to the next check. A photo's fingerprint follows it from the name it was planned under.
            write_workspace_record(ws, carried={r["after"]["relative_path"]: r["relative_path"]
                                                for r in results if r.get("after")})
            if not ended:
                # A run cut short writes no summary (BLD-execution_summary_written): the changes by hand its check
                # named or accepted go to its plan's journal, in the same step (BLD-workspace_changes_logged).
                journal_add_changes(ws, plan["plan_id"], workspace_changes)

    def _apply_plan(self, plan, gpx, journal, media_after, jpath, accepted, prior_failures, by_file, results, snapshot,
                    jobs, now_iso, execution_id, workspace_changes):
        """execute_plan's part that changes the photos — its originals pinned, each photo's operations applied and
        journaled, the summary written — into `results`, which the caller reads whatever happens here."""
        ws = self.workspace_root
        cache = GeotagCache(ws)
        try:
            # Capture-before-write (BLD-original_values_pinned): pin each file's own values — prep's record, NOT a
            # re-read — before geotag's first write to it, keyed by content fingerprint. A file already carrying
            # geotag's mark holds no original values any more, so it is not pinned.
            model = self.build_file_model()
            kept_times = plan.get("true_times_kept") or {}
            for f in model:
                fp = f.get("content_fingerprint")
                if fp and f.get("original_key") not in (None, fp):
                    # the pin follows the new value (BLD-original_values_follow_fingerprint)
                    cache.originals_rekey(f["original_key"], fp)
                if f["relative_path"] in (plan.get("true_times_dropped") or []) and f.get("from_originals"):
                    # an answer to keep the time withdrawn, and answered otherwise (BLD-changed_time_kept_pinned)
                    cache.originals_drop_true_time(f["original_key"])
                kept = kept_times.get(f["relative_path"])
                if kept and f.get("from_originals") and \
                        {k: held_values(f).get(k) for k in TIME_PAIR} == {k: kept.get(k) for k in TIME_PAIR}:
                    # a time the user kept as the photo's true one, recorded beside its pin before anything is
                    # written to it (BLD-changed_time_kept_pinned): every later plan resolves the photo from it
                    cache.originals_true_time(fp, kept)
                    cache.originals_true_time(f["original_key"], kept)
                if (fp and f["relative_path"] in by_file and not f.get("from_originals")
                        and geotag_marker(held_values(f).get("method")) is None):
                    cache.originals_pin(fp, f["relative_path"], f["own_values"], now_iso)
                # and, before it is written, the time geotag writes to it (BLD-time_written_recorded): whether the write
                # lands or is interrupted, a re-plan knows the time as geotag's own
                for o in by_file.get(f["relative_path"]) or []:
                    if fp and o["type"] == "metadata_time_write" and journal.get(o["operation_id"]) != "confirmed":
                        cache.time_written_record(fp, {k: o["writes"].get(k) for k in TIME_PAIR})

            # A JPEG set aside beside its RAW is renamed after its RAW, and only once the RAW's rename is confirmed: a run
            # never leaves the one renamed and the other not (BLD-set_aside_renamed_with_raw).
            followers = {rel for rel, ops in by_file.items() if any(o.get("follows") for o in ops)}
            kept = getattr(self, "_journal_changes", None) or []
            self._journal_out = lambda j: write_json_artifact(jpath, {
                "journal_version": 1, "plan_id": plan["plan_id"], "operations": j, "media_after": media_after,
                "updated_at": now_iso, **({"workspace_changes": kept} if kept else {})})
            self.coordinator.start_phase("applying calibration", len(by_file))
            with concurrent.futures.ThreadPoolExecutor(max_workers=max(1, jobs)) as ex:
                for wave in (sorted(set(by_file) - followers), sorted(followers)):
                    self._apply_wave(ex, wave, by_file, journal, media_after, accepted, jpath, plan, now_iso, results)
            self.coordinator.finish_phase()

        finally:
            self._journal_out = None
            cache.close()
            from .photos_utils import PersistentMagickWorker
            PersistentMagickWorker.cleanup_all()       # close the per-thread magick workers (verify pass)

        # The journal was persisted incrementally as each file completed (above); nothing more to flush.
        summary = self._build_summary(plan, results, now_iso, execution_id, jobs,
                                      self._prior_mismatches(ws, plan["plan_id"]), prior_failures)
        summary["snapshot"] = snapshot                                   # the pre-mutation ZFS record (or None)
        # the changes by hand this run's check named or accepted (BLD-workspace_changes_logged)
        summary["workspace_changes"] = list(workspace_changes or [])
        write_versioned_json(execution_summary_path(ws), summary)        # the earlier one kept as -NNN
        # (BLD-geotag_records_versioned)
        return summary

    def _apply_wave(self, ex, wave, by_file, journal, media_after, accepted, jpath, plan, now_iso, results):
        """Apply the photos of `wave` on the pool `ex`, journalling each as it completes. A file whose operations follow
        another's (`follows`) is applied only where every one followed is confirmed by now."""
        wave = [rel for rel in wave if all(journal.get(o["follows"]) == "confirmed"
                                           for o in by_file[rel] if o.get("follows"))]
        futs = [ex.submit(self._apply_file_contained, rel, by_file[rel], journal, accepted) for rel in wave]
        try:
            for fut in concurrent.futures.as_completed(futs):
                r = fut.result()
                results.append(r)
                self.coordinator.increment_completed(1)
                # Incremental confirmation journal (BLD-geotag_execution): persist each file's confirmed ops AS
                # IT COMPLETES, so a crash mid-run leaves a journal that lets the next run skip the already-applied
                # files. A worker only notes a write begun, under the same lock (BLD-own_leftover_cleared).
                if r["applied"] or r.get("found"):
                    with self._journal_lock:
                        for oid in r["applied"] + (r.get("found") or []):
                            journal[oid] = "confirmed"
                        if r.get("after"):            # the photo as this run left it: finalize's baseline
                            a = r["after"]
                            media_after[a["relative_path"]] = {"size": a["size"], "mtime_ns": a["mtime_ns"]}
                        self._journal_out(journal)
        except KeyboardInterrupt:
            # Ctrl-C: drop pending file writes and stop waiting instead of letting the `with`
            # exit drain them (shutdown(wait=True)). Files already applied are confirmed in the
            # journal above, so the next run resumes from the diff (RUL-geotag_execution_resumable). Re-raise
            # to main().
            ex.shutdown(wait=False, cancel_futures=True)
            raise

    @staticmethod
    def _prior_mismatches(ws, plan_id):
        """The fingerprint mismatches the last execution of THIS plan reported, as written — the user's
        acceptances among them. Another plan's are not this plan's to act on. None there is none; one that cannot
        be read raises UnreadableRecord (RUL-unreadable_execution_record_stops)."""
        prior = _read_record(execution_summary_path(ws))
        if prior is None or prior.get("plan_id") != plan_id:
            return []
        return [m for m in (prior.get("fingerprint_mismatches") or []) if isinstance(m, dict)]

    @staticmethod
    def _prior_failures(ws, plan_id):
        """The failures the previous execution of THIS plan recorded (BLD-repeated_write_failure): the latest summary
        — photos-25, else the copies set aside under -NNN, newest first — that tried the photos, a `rejected` one passed
        over; none when the latest that did is another plan's. One that cannot be read raises UnreadableRecord
        (RUL-unreadable_execution_record_stops)."""
        path = execution_summary_path(ws)
        stem, ext = os.path.splitext(path)
        kept = sorted((p for p in glob.glob(glob.escape(stem) + "-[0-9][0-9][0-9]*" + ext)
                       if p[len(stem) + 1:-len(ext)].isdigit()),
                      key=lambda p: int(p[len(stem) + 1:-len(ext)]), reverse=True)
        for p in [path] + kept:
            prior = _read_record(p)
            if prior is None or prior.get("status") == "rejected":
                continue
            if prior.get("plan_id") != plan_id:
                return []
            return [f for f in (prior.get("failures") or []) if isinstance(f, dict)]
        return []

    @staticmethod
    def _mismatch_decision_blockers(ws, plan_id):
        """Located blockers for photos-25's content acceptances of this plan (RUL-checked_shapes,
        RUL-unknown_decision_field_refused): each entry an object whose `user_decision` is an object holding
        `accept_fingerprint_change` true or false, and no other field."""
        prior = _read_record(execution_summary_path(ws))
        if prior is None or prior.get("plan_id") != plan_id:
            return []
        out = []
        held = prior.get("fingerprint_mismatches")
        if held is None:
            return out
        if not isinstance(held, list):
            return [f"{EXECUTION_SUMMARY_ARTIFACT}: fingerprint_mismatches must be a list."]
        what, fields = DECISION_FIELDS["execution"]["fingerprint_mismatches"]
        for i, m in enumerate(held):
            where = f"{EXECUTION_SUMMARY_ARTIFACT}: fingerprint_mismatches[" + (
                str(m.get("relative_path")) if isinstance(m, dict) else str(i)) + "]"
            ud = m.get("user_decision") if isinstance(m, dict) else None
            if not isinstance(ud, dict):
                out.append(f"{where}: must be an object holding user_decision, an object.")
                continue
            _decision_flag(ud, "accept_fingerprint_change", f"{where}.user_decision", out)
            out.extend(f"{where}.user_decision.{k}: {what} has no such field — remove it." for k in ud
                       if k not in fields)
        return out

    @classmethod
    def _accepted_mismatches(cls, ws, plan_id):
        """{path: accepted fingerprint} for the mismatches of this plan the user accepted: an acceptance
        is of the content that was shown — the fingerprint the write left — never of whatever the photo
        holds later."""
        return {m.get("relative_path"): m.get("actual_fingerprint") for m in cls._prior_mismatches(ws, plan_id)
                if (m.get("user_decision") or {}).get("accept_fingerprint_change") is True
                and m.get("actual_fingerprint")}

    def _build_summary(self, plan, results, now_iso, execution_id, jobs, prior_mismatches=(), prior_failures=()):
        ws = self.workspace_root
        op_type, op_dest = {}, {}
        for dest, dd in plan["destinations"].items():
            for o in dd["operations"]:
                op_type[o["operation_id"]] = o["type"]
                op_dest[o["operation_id"]] = dest
        totals = {v: 0 for v in self._OP_TOTAL_KEY.values()}
        # Per-destination operation counts (BLD-execution_summary — applied/no-op/skipped per destination + global
        # total).
        per_dest = {dest: {**{v: 0 for v in self._OP_TOTAL_KEY.values()}, "skipped": 0}
                    for dest in plan["destinations"]}
        newly, skipped_n = 0, 0
        failures, mismatches, blockers = [], [], []
        for r in sorted(results, key=lambda x: x["relative_path"]):
            for oid in r["applied"]:
                key = self._OP_TOTAL_KEY.get(op_type.get(oid))
                if key:
                    totals[key] += 1
                    d = op_dest.get(oid)
                    if d in per_dest:
                        per_dest[d][key] += 1
                newly += 1
            for oid in r["skipped"]:                       # already-satisfied ops, attributed per destination
                d = op_dest.get(oid)
                if d in per_dest:
                    per_dest[d]["skipped"] += 1
            skipped_n += len(r["skipped"])
            # each failure with its operation's kind and the reason it failed (BLD-write_failure_reason)
            failures.extend({"operation_id": oid, "relative_path": r["relative_path"], "type": op_type.get(oid),
                             "error": r.get("error")} for oid in r["failed"])
            if r["mismatch"]:
                mismatches.append({**r["mismatch"], "user_decision": {"accept_fingerprint_change": False}})
            if r["blocker"]:
                blockers.append(r["blocker"])
        # A mismatch stays on the record, the user's answer with it, until its photo is applied: a run that
        # only finds the photo still held must not take away the one place the change can be accepted.
        held = {r["relative_path"] for r in results if r["blocker"]}
        reported = {m["relative_path"]: m for m in mismatches}
        for m in prior_mismatches:
            rel = m.get("relative_path")
            if rel in reported:
                if reported[rel]["actual_fingerprint"] == m.get("actual_fingerprint"):
                    reported[rel]["user_decision"] = m.get("user_decision") or reported[rel]["user_decision"]
            elif rel in held:
                mismatches.append(m)
        mismatches.sort(key=lambda m: m.get("relative_path") or "")
        for dest, dd in plan["destinations"].items():
            per_dest[dest]["no_ops"] = len(dd.get("no_ops") or [])
        totals["no_ops"] = sum(len(dd.get("no_ops") or []) for dd in plan["destinations"].values())
        status = geotag_execution_status(newly, skipped_n, failures, mismatches, blockers)
        return {
            "artifact_type": "execution_summary", "artifact_name": EXECUTION_SUMMARY_ARTIFACT,
            "schema_version": 1, "plan_id": plan["plan_id"],
            "summarizes": {EXECUTABLE_PLAN_ARTIFACT: {"sha256": sha256_file(executable_plan_path(ws))},
                           "upstream": plan.get("depends_on")},
            "totals": totals,
            "destinations": {d: per_dest[d] for d in sorted(per_dest)},   # per-destination breakdown
            "resume": {"newly_applied": newly, "already_satisfied_skipped": skipped_n},
            "failures": failures, "repeated_failures": repeated_write_failures(failures, prior_failures),
            "blockers": blockers, "fingerprint_mismatches": mismatches,
            "status": status,
            "run_metadata": {"execution_id": execution_id, "started_at": now_iso, "finished_at": now_iso, "jobs": jobs},
        }

    # --- Stage 11: finalize + archive (RUL-finalize_explicit, BLD-archive_manifest) ---

    def finalize_package(self, now_iso):
        """Stage 11 (BLD-archive_manifest): assemble the durable archival package — the photos-26 transformation log,
        an end-of-geotag DB snapshot, and a manifest. Non-destructive (only NEW files; never
        mutates an artifact, photo, or the live DB). Returns blockers (empty = package written). A record of an
        earlier execution that cannot be read is one, naming it (RUL-unreadable_execution_record_stops)."""
        try:
            return self._finalize_package(now_iso)
        except UnreadablePlan as e:
            # made from records still there: planned again, never repaired (BLD-unreadable_plan)
            return [f"{e} — {REPLAN_ADVICE}, then `geotag execute` and `geotag finalize`; nothing was written."]
        except UnreadableRecord as e:
            return [f"{e} — repair it, or move it out of {CONTROL_DIR}/ if it cannot be repaired; nothing was "
                    "written."]

    def _finalize_package(self, now_iso):
        ws = self.workspace_root
        plan = read_executable_plan(ws)
        if plan is None:
            return [f"No {EXECUTABLE_PLAN_ARTIFACT} — run `plan` then `execute` first."]
        if not os.path.exists(execution_summary_path(ws)):
            return [f"No {EXECUTION_SUMMARY_ARTIFACT} — `execute` the plan first."]
        summary = _read_record(execution_summary_path(ws))
        blk = []
        if plan.get("status") != "ready":
            blk.append(f"{EXECUTABLE_PLAN_ARTIFACT} status is {plan.get('status')!r}, not 'ready'.")
        if summary.get("status") != "success":
            blk.append(f"{EXECUTION_SUMMARY_ARTIFACT} status is {summary.get('status')!r}, not 'success' "
                       "— resolve execution first.")
        if plan.get("plan_id") != summary.get("plan_id"):
            blk.append(f"{EXECUTION_SUMMARY_ARTIFACT} does not summarize the current "
                       f"{EXECUTABLE_PLAN_ARTIFACT} (plan_id mismatch) — re-execute.")
        if blk:
            return blk
        # The executed plan must still hold (RUL-finalize_requires_plan_still_holds): a decision, the configuration or
        # the tracks changed since would leave the package recording decisions the photos never received. The
        # handoff is left out: a
        # prep run after execute records geotag's own writes and renames in it, and that is the loop, not a
        # change of decision.
        # The tracks are those the record keeps: finalize seals what is kept and never reads gpx_root
        # (RUL-sealing_needs_no_tracks).
        gpx = self.plan_tracks(plan, read=False)
        stale = self.revalidate_plan(plan, gpx, with_handoff=False)
        if stale:
            return [f"The executed plan no longer holds ({'; '.join(stale)}) — re-run `geotag plan` and "
                    "`geotag execute` first."]

        changed = self._changed_since_execution(plan)
        if changed:
            # a photo of photos by destination, or a JPEG set aside that the plan renamed with its RAW
            # (BLD-finalize_preconditions): each named under the folder it is in
            where = " and ".join(sorted({c.split(os.sep, 1)[0] for c in changed}))
            return [f"{len(changed)} file(s) in {where} are not as the execution left "
                    f"them ({_named(changed)}) — re-run `geotag plan` and `geotag execute` first (after "
                    "`prep plan` and `prep execute`, if geotag asks)."]
        # No photo leaves geotag without a position (RUL-finalize_refuses_unplaced): checked from what each photo
        # holds, as prep read it and the executed plan wrote it — not from the plan's decisions alone.
        unplaced = photos_without_position(self.handoff, plan)
        if unplaced:
            return [f"{len(unplaced)} photo(s) in {folder_name('photos_by_dest')} hold no position "
                    f"({_named(unplaced)}) — give each a position, or its folder a fallback, in "
                    f"{GPS_DECISIONS_ARTIFACT}, then re-run `geotag plan` and `geotag execute`."]

        files = self.build_file_model()
        cache = GeotagCache(ws)
        try:
            rows = cache.get_rows()
        finally:
            cache.close()
        time_artifact = json.load(open(time_decisions_path(ws)))
        prep_photos = (json.load(open(prep_log_path(ws))) or {}).get("photos", {}) or {}
        photos = build_complete_log(prep_photos, files, rows, time_artifact, plan,
                                    earlier_passes=self._earlier_passes(plan.get("plan_id")))
        not_carried = entries_not_carried(prep_photos, photos)
        if not_carried:
            # a defect, not a state of the workspace: the copy would misstate prep's record (BLD-log_copy_checked)
            return [f"{COMPLETE_LOG_ARTIFACT} would not carry prep's record unchanged for {len(not_carried)} "
                    "photo(s); nothing was written."]
        self.finalize_warnings = []
        self.finalize_warnings += [f"geotag pass {pid} ran (its journal is kept) but its plan is missing: "
                                   "its steps are not in the log" for pid in self._passes_without_a_plan(plan.get("plan_id"))]
        self.finalize_warnings += [f"{e.get('geotag_path') or e.get('prep_path') or fp}: {s['note']}" for fp, e in sorted(photos.items())
                                   for s in e.get("journey") or [] if s.get("action") == "history_incomplete"]
        log = {"schema_version": 1, "tool": "photos-2-geotag", "photos": photos}
        if self.finalize_warnings:
            log["partial"] = True
            log["warnings"] = self.finalize_warnings
        # A package made again sets the earlier one aside first, file by file under the next -NNN, never writing
        # over it (BLD-geotag_records_versioned); the copies are records, archived with the rest — the earlier
        # archive itself excepted.
        for p in (complete_log_path(ws), finalized_media_path(ws), geotag_db_snapshot_path(ws),
                  archive_manifest_path(ws), archive_path(ws)):
            backup_existing_artifact(p)
        write_json_artifact(complete_log_path(ws), log)
        write_json_artifact(finalized_media_path(ws), self._finalized_media(files, plan))

        conn = sqlite3.connect(db_path(ws))
        try:
            write_db_snapshot(conn, geotag_db_snapshot_path(ws))   # BLD-database_images: consistent, atomic
        finally:
            conn.close()

        # The package (BLD-archive_manifest): the whole control directory but its transient files, listed with their
        # hashes in the manifest, then archived together with it into the control directory itself.
        members = control_archive_members(ws, exclude=(ARCHIVE_MANIFEST_ARTIFACT,))
        write_json_artifact(archive_manifest_path(ws), self._archive_manifest(plan, summary, now_iso, members))
        write_control_archive(ws, archive_path(ws), members + [os.path.relpath(archive_manifest_path(ws), ws)])
        return []

    def _changed_since_execution(self, plan):
        """The photos in photos by destination that are not as the plan's execution left them
        (RUL-finalize_checks_photos): one gone, one whose size or modification time is no longer what the run
        recorded as it confirmed it (or, for a photo the plan had nothing to do to, what the plan was made from),
        and one the plan never knew. What finalize packages is what merge trusts as geotag's work, so it is checked, not
        taken from whatever is on disk."""
        ws = self.workspace_root
        after = (_read_record(journal_path(ws, plan["plan_id"])) or {}).get("media_after") or {}
        final = {}
        for dd in (plan.get("destinations") or {}).values():
            for op in dd.get("operations") or []:
                if op["type"] == "rename_no_clobber":
                    final[op["relative_path"]] = os.path.join(os.path.dirname(op["relative_path"]), op["to"])
        with_ops = {op["relative_path"] for dd in (plan.get("destinations") or {}).values()
                    for op in dd.get("operations") or []}
        expected = {}
        for m in (plan.get("depends_on") or {}).get("media_preconditions") or []:
            rel = m["relative_path"]
            now = final.get(rel, rel)
            expected[now] = after.get(now) if rel in with_ops else {"size": m.get("size"), "mtime_ns": m.get("mtime_ns")}
        changed = []
        for rel, want in sorted(expected.items()):
            try:
                st = os.stat(os.path.join(ws, rel))
            except OSError:
                changed.append(rel)
                continue
            if not want or (want.get("size"), want.get("mtime_ns")) != (st.st_size, st.st_mtime_ns):
                changed.append(rel)
        base = os.path.join(ws, folder_name('photos_by_dest'))
        for root, _dirs, names in os.walk(base):
            for n in sorted(names):
                rel = os.path.relpath(os.path.join(root, n), ws)
                if not n.startswith('.') and rel not in expected \
                        and media_class_for_ext(os.path.splitext(n)[1]) in ("image", "raw"):
                    changed.append(rel)
        return sorted(changed)

    def _keep_executed_decisions(self, plan):
        """Keep, once per plan, the exact decision records the plan was made from and is now executed
        against (BLD-history_kept) — `executed/<plan id>/` in the control directory — so a later finalize's log
        can name the precise version a pass followed after the live records have been edited in place.
        Revalidation has just proven the live records are the ones the plan depends on."""
        ws = self.workspace_root
        keep = os.path.join(ws, CONTROL_DIR, EXECUTED_DIR, plan["plan_id"])
        for key in DECISION_RECORD_DEPS:
            dep = (plan.get("depends_on") or {}).get(key) or {}
            src = os.path.join(ws, dep["artifact_path"]) if dep.get("artifact_path") else None
            if not src or not os.path.exists(src) or sha256_file(src) != dep.get("sha256"):
                continue
            dst = os.path.join(keep, os.path.basename(src))
            if not os.path.exists(dst):
                os.makedirs(keep, exist_ok=True)
                tmp = os.path.join(keep, ".tmp-" + os.path.basename(src))
                shutil.copyfile(src, tmp)
                replace_durably(tmp, dst)

    def _tracks_used(self, plan):
        """The track files `plan` places or times photos by (BLD-withdrawn_track_points): the track each GPS write
        rests on; for each offset the camera's own GPS gave, the tracks of its anchors that agree with it — or of
        every anchor where none does, as where the tracks stood still — and the tracks it was kept by; and the
        tracks each drift confirmation in effect was made against. Read after revalidation has proven the records
        are the plan's."""
        ws = self.workspace_root
        used = {(o.get("provenance") or {}).get("gpx_file") for d in plan["destinations"].values()
                for o in d["operations"] if o["type"] == "metadata_gps_write"}
        spread = CONFIG["gpx_anchor_offset_spread_max_seconds"]
        for d in ((_read_record(time_decisions_path(ws)) or {}).get("destinations") or {}).values():
            for cell in (d.get("camera_group_time_decisions") or {}).values():
                eff = cell.get("effective_time_anchor")
                if not (isinstance(eff, dict) and str(eff.get("source")).startswith("gpx_anchor")):
                    continue
                used |= {t.get("gpx_file") for t in cell.get("anchored_by") or [] if isinstance(t, dict)}
                anchors = [a for a in (cell.get("proposal") or {}).get("anchors") or [] if isinstance(a, dict)]
                agree = [a for a in anchors if isinstance(a.get("proposed_offset_seconds"), (int, float))
                         and abs(a["proposed_offset_seconds"] - eff.get("offset_seconds", 0)) <= spread]
                used |= {(a.get("gpx_match") or {}).get("gpx_file") for a in agree or anchors}
        for d in ((_read_record(drift_validation_path(ws)) or {}).get("destinations") or {}).values():
            for cell in (d.get("drift_decisions") or {}).values():
                if isinstance(cell.get("effective_drift_offset"), dict):
                    used |= {t.get("gpx_file") for t in (cell.get("proposal") or {}).get("tracks") or []
                             if isinstance(t, dict)}
        return sorted(f for f in used if isinstance(f, str) and f)

    def _earlier_passes(self, current_plan_id):
        """[(plan, confirmed operation ids)] of every geotag pass executed before the current plan,
        oldest first: each superseded plan (kept as photos-24-...-NNN.json, numbered in the order they
        were set aside) whose journal shows it ran (BLD-geotag_log_steps). A kept plan or journal that cannot be read
        raises UnreadableRecord: a pass is never left out of the log unsaid (RUL-unreadable_execution_record_stops)."""
        ws = self.workspace_root
        out, seen = [], {current_plan_id}
        for plan in self._kept_plans(current_plan_id):
            pid = plan.get("plan_id")
            jp = journal_path(ws, pid) if pid else None
            if pid in seen or not jp or not os.path.exists(jp):
                continue
            seen.add(pid)
            ops = (_read_record(jp) or {}).get("operations") or {}
            out.append((plan, {oid for oid, st in ops.items() if st == "confirmed"}))
        return out

    def _passes_without_a_plan(self, current_plan_id):
        """Ids of geotag passes whose journal shows they ran but whose plan is neither current nor kept
        — their steps cannot be rebuilt (BLD-partial_log_marked). A geotag journal maps operation ids to their status;
        prep's lists its operations."""
        known = {current_plan_id} | {plan.get("plan_id") for plan in self._kept_plans(current_plan_id)}
        return self._journals_outside(known)

    def _journals_outside(self, known):
        """Plan ids of the geotag journals with a confirmed operation whose plan is not in `known`. A journal that
        cannot be read raises UnreadableRecord (RUL-unreadable_execution_record_stops)."""
        missing = []
        for jp in sorted(glob.glob(os.path.join(self.workspace_root, CONTROL_DIR, "journal-*.json"))):
            j = _read_record(jp) or {}
            ops = j.get("operations")
            if isinstance(ops, dict) and any(st == "confirmed" for st in ops.values()) and j.get("plan_id") not in known:
                missing.append(j.get("plan_id"))
        return missing

    def _kept_plans(self, current_plan_id):
        """The plans set aside under -NNN, in the order they were set aside, as read. One that cannot be read is
        passed over only when no execution ran it (RUL-unread_plan_never_run_passed, BLD-unexecuted_kept_plan_passed):
        no execution summary — photos-25 or a copy kept under -NNN — names its SHA-256, and every geotag journal with
        a confirmed operation is the current plan's or a readable kept plan's, so not even a run cut off before its
        summary can be its. Otherwise it raises UnreadableRecord, as does a summary that cannot be read
        (RUL-unreadable_execution_record_stops)."""
        ws = self.workspace_root
        stem = os.path.splitext(EXECUTABLE_PLAN_ARTIFACT)[0]
        backups = sorted(glob.glob(os.path.join(ws, CONTROL_DIR, f"{stem}-[0-9][0-9][0-9]*.json")),
                         key=lambda p: int(os.path.basename(p)[len(stem) + 1:-len(".json")] or 0))
        plans, unread = [], []
        for p in backups:
            try:
                plans.append(_read_record(p) or {})
            except UnreadableRecord as e:
                unread.append((p, e))
        if unread:
            ran = self._executed_plan_shas()
            cut_off = self._journals_outside({current_plan_id} | {plan.get("plan_id") for plan in plans})
            for p, e in unread:
                try:
                    sha = sha256_file(p)
                except OSError:
                    raise e
                if cut_off or sha in ran:
                    raise e
        return plans

    def _executed_plan_shas(self):
        """The SHA-256 of photos-24 each execution summary — photos-25 and the copies kept under -NNN — records it
        ran (BLD-execution_summary). One that cannot be read raises UnreadableRecord."""
        path = execution_summary_path(self.workspace_root)
        stem, ext = os.path.splitext(path)
        shas = set()
        for p in [path] + glob.glob(glob.escape(stem) + "-[0-9][0-9][0-9]*" + ext):
            s = _read_record(p) or {}
            sha = ((s.get("summarizes") or {}).get(EXECUTABLE_PLAN_ARTIFACT) or {}).get("sha256")
            if isinstance(sha, str):
                shas.add(sha)
        return shas

    def _finalized_media(self, files, plan):
        """Each by-dest photo as geotag left it — its final path, size and modification time — for merge
        to refuse one changed since (RUL-merge_refuses_changed_since_finalize). The final path is the plan's
        rename target, if any."""
        renamed = {op["relative_path"]: op["to"] for d in (plan.get("destinations") or {}).values()
                   for op in d.get("operations") or [] if op.get("type") == "rename_no_clobber"}
        media = {}
        for f in files:
            rel = f["relative_path"]
            final = os.path.join(os.path.dirname(rel), renamed[rel]) if rel in renamed else rel
            try:
                st = os.stat(os.path.join(self.workspace_root, final))
            except OSError:
                continue
            media[final] = {"size": st.st_size, "mtime_ns": st.st_mtime_ns}
        return {"artifact_type": "finalized_media", "artifact_name": FINALIZED_MEDIA_ARTIFACT,
                "schema_version": 1, "plan_id": plan.get("plan_id"), "media": dict(sorted(media.items()))}

    def _archive_manifest(self, plan, summary, now_iso, members):
        ws = self.workspace_root
        contents = {os.path.relpath(rel, CONTROL_DIR): {"path": rel, "sha256": sha256_file(os.path.join(ws, rel))}
                    for rel in members}
        return {
            "artifact_type": "archive_manifest", "artifact_name": ARCHIVE_MANIFEST_ARTIFACT,
            "schema_version": 1,
            "workspace": os.path.basename(os.path.abspath(ws)),       # for a person to read
            "workspace_id": workspace_id(ws),                          # the identity (RUL-package_self_describing)
            "plan_id": plan.get("plan_id"),
            "execution_id": (summary.get("run_metadata") or {}).get("execution_id"),
            "placement": plan.get("placement") or {},                  # how every photo came by its position
            "contents": contents,
            "run_metadata": {"generated_at": now_iso},
        }


GEOTAG_BLURB = (
    "geotag — place every photo in time and on the map (phase 2 of 3).\n\n"
    "Infers each camera's clock offset from its already-geotagged frames against your GPX tracks, then "
    "geotags the un-tagged majority by interpolating along the track; you resolve the residual time / "
    "GPS / drift decisions in `photos-cartographer edit` between `plan` runs. `plan` (re-runnable) produces "
    "the decision + executable-plan artifacts and mutates nothing; `execute` applies them to the "
    "originals (corrected times + GPS, renames); `finalize` bundles the durable archive. Run inside "
    "the workspace directory.\n\n"
    "Loop: plan -> edit -> plan -> ... -> execute -> finalize. Next: `photos-cartographer merge`."
)


def _changed_time_answers(prior_time):
    """{content fingerprint: cell} of the prior photos-21's `changed_times` cells (BLD-changed_time_question)."""
    out = {}
    for d in (((prior_time or {}).get("destinations")) or {}).values():
        if not isinstance(d, dict) or not isinstance(d.get("changed_times"), dict):
            continue
        for cell in d["changed_times"].values():
            if isinstance(cell, dict) and isinstance(cell.get("content_fingerprint"), str):
                out.setdefault(cell["content_fingerprint"], cell)
    return out


def _changed_time_answer(ud, ch):
    """The answer in effect for a time changed since geotag wrote it — "new" (kept as the photo's true local time) or
    "geotag" (geotag's written back) — or None: an answer holds for the time it was given for (`answered_for`), and
    keeping needs a time to keep (BLD-changed_time_question). Its values are checked where the cell is built."""
    keep, answered = ud.get("keep", ""), ud.get("answered_for")
    if keep not in CHANGED_TIME_ANSWERS or not isinstance(answered, dict):
        return None
    if {k: answered.get(k) for k in TIME_PAIR} != ch["held_time"] or set(answered) - set(TIME_PAIR):
        return None
    if keep == "new" and _parse_camera_naive(ch["held_time"]["DateTimeOriginal"]) is None:
        return None
    return keep


def _placement_reach():
    """The farthest a track point can lie from a photo's time and place it (BLD-track_placement): the direct match,
    the interpolation gap, or the extrapolation reach with the stretch its heading is taken over."""
    return max(CONFIG["gpx_direct_match_max_seconds"], CONFIG["gpx_interpolation_max_gap_seconds"],
               CONFIG["gpx_extrapolation_max_seconds"] + CONFIG["gpx_extrapolation_heading_seconds"])


def _drift_reach():
    """How far from a bucket's photos the drift check looks for tracks (BLD-drift_validation):
    `drift_check_track_window_seconds`, or placement's reach where that is farther."""
    return max(CONFIG["drift_check_track_window_seconds"], _placement_reach())


def contradicted_positions(time_artifact):
    """The photos whose own position the clock offset in effect for their cell, agreed from their camera's own GPS,
    contradicts — the cells' `positions_contradicted` in photos-21 (BLD-contradicted_position), sorted."""
    out = set()
    for d in ((time_artifact or {}).get("destinations") or {}).values():
        for c in (d.get("camera_group_time_decisions") or {}).values():
            eff = c.get("effective_time_anchor")
            if isinstance(eff, dict) and eff.get("source") in GeotagWorkflow._OWN_GPS_SOURCES:
                out.update(c.get("positions_contradicted") or [])
    return sorted(out)


def camera_group_class(key, device_groups):
    """The class the configuration's `device_groups` gives camera group `key` (BLD-known_camera_group): `smartphone`
    (listed in `phones`), `camera` (in `fixed_clock_cameras`), `unidentified` for files naming no camera — solved on
    their own, never asked about (BLD-unidentified_files) — else `unknown`. One listed as both is classed as neither:
    the two are solved in opposite ways, and picking one here would be geotag's guess (the offered classification
    lists a new group under both)."""
    phones = set(device_groups.get("phones") or [])
    fixed = set(device_groups.get("fixed_clock_cameras") or [])
    if key == NO_IDENTITY_KEY:
        return "unidentified"
    if key in phones and key in fixed:
        return "unknown"
    return "smartphone" if key in phones else ("camera" if key in fixed else "unknown")


def _parsed_record(rec):
    """Prep's parsed metadata of a handoff record, or {} when it holds none that parses."""
    md = rec.get("metadata_status") or {}
    try:
        return json.loads(md["parsed_json"]) if md.get("parsed_json") else {}
    except Exception:
        return {}


def unclassified_camera_groups(handoff, cfg):
    """{camera group: its photos' paths} for each group of the handoff's photos under photos by destination that the
    configuration `cfg` does not class — the groups geotag stops on (BLD-known_camera_group). What the decision editor
    asks the class of (BLD-editor_lists_new_camera_groups)."""
    return camera_groups_of_class(handoff, cfg, "unknown")


def camera_groups_of_class(handoff, cfg, cls):
    """{camera group: its photos' paths} for each group of the handoff's photos under photos by destination that the
    configuration `cfg` classes `cls` (`camera_group_class`), keyed from prep's record as `build_file_model` keys a
    photo with no pinned values. Of class `camera`, the groups the decision editor lets the user name as several
    bodies (BLD-editor_marks_several_bodies)."""
    by_dest = ((cfg or {}).get("folders") or {}).get("photos_by_dest") or folder_name("photos_by_dest")
    dg = ((cfg or {}).get("camera_time_and_timezone_policy") or {}).get("device_groups") or {}
    out = {}
    for rec in ((handoff or {}).get("files") or []):
        if rec.get("folder_class") != by_dest or rec.get("media_class") not in ("image", "raw"):
            continue
        md, parsed = rec.get("metadata_status") or {}, _parsed_record(rec)
        key = clock_group_key({"camera_group_key": md.get("camera_group_key") or parsed.get("camera_group_key")
                               or NO_IDENTITY_KEY, "source_time_tag": parsed.get("selected_source_timestamp_tag"),
                               "has_timestamp": _has_recorded_time(rec)})
        if camera_group_class(key, dg) == cls:
            out.setdefault(key, []).append(rec.get("relative_path"))
    return {k: sorted(p for p in v if p) for k, v in sorted(out.items())}


def _load_prior_decisions(path):
    """The user's prior decision artifact at `path`, as (artifact, problem). (None, None) when there is
    none yet. A file that cannot be read or parsed, or that is not a JSON object, is never ignored or
    regenerated over (RUL-checked_decision_structure, RUL-invalid_decision_kept): it comes back as (None, problem), the
    problem located to where parsing failed, for the caller to stop on with the file left as it is."""
    if not os.path.exists(path):
        return None, None
    name = os.path.basename(path)
    try:
        with open(path) as f:
            prior = json.load(f)
    except json.JSONDecodeError as e:
        return None, f"{name} is not valid JSON (line {e.lineno}, column {e.colno}: {e.msg})."
    except (OSError, UnicodeDecodeError) as e:
        return None, f"{name} could not be read: {e}"
    if not isinstance(prior, dict):
        return None, f"{name} must be a JSON object, not {type(prior).__name__}."
    return prior, None


def _split_authored(wf, files, later):
    """(photos-22's blockers, photos-23's) of `wf.authored_value_blockers`, apart, for each to be named under its
    record."""
    drift = wf.authored_value_blockers(files, later[DRIFT_VALIDATION_ARTIFACT], None)
    gps = wf.authored_value_blockers(files, None, later[GPS_DECISIONS_ARTIFACT])
    return drift, gps


def _stop_on_unreadable_decisions(reporter, problem):
    """A decision artifact that does not parse stops geotag before anything is made from it."""
    reporter.error("\nGeotag cannot proceed: a decision artifact cannot be read:")
    reporter.log(f"  - {problem}")
    reporter.log("\nFix the file (or restore it from a -NNN backup) and re-run; it was left unchanged.")
    sys.exit(2)


def add_arguments(parser):
    """Register geotag's `-j` + subcommands (plan / execute / finalize) on `parser`. Shared by the
    standalone `python -m cartographer.photos_2_geotag` and the combined `photos-cartographer geotag`."""
    parser.add_argument("-j", "--jobs", type=int, default=None,
                        help="Worker threads for execution (default: 4). A setting of the run, recorded nowhere.")
    sub = parser.add_subparsers(dest="command")
    for p in (sub.add_parser("plan", help="Plan the geotag pass: produce photos-21/22/23/24 (no mutation)."),
              sub.add_parser("execute", help="Apply photos-24 to the originals (metadata writes + renames)."),
              sub.add_parser("finalize", help="Bundle the durable archival package (photos-26; non-destructive).")):
        add_accept_changes_argument(p)
    parser.set_defaults(_run=run, _parser=parser)


def _check_workspace(args, workspace_root):
    """Geotag's check of the workspace against the state the last execution left (BLD-workspace_check), before
    anything is planned or changed — before the automatic re-prep, which runs prep's commands under this run's lock.
    Made where the preflight would find the workspace initialized, unsealed, its configuration readable and its top
    level as it should be; otherwise the preflight refuses, naming why. A workspace with no record is refused
    (RUL-record_needed). Returns the changes this run names; exits 2 on a stop."""
    if is_sealed(workspace_root) or not os.path.exists(guard_path(workspace_root)):
        return []
    try:
        load_config(workspace_root)
    except Exception:
        return []
    if top_level_links(workspace_root) or missing_managed_folders(workspace_root) \
            or misplaced_top_level_entries(workspace_root) or links_under(workspace_root, folder_name('photos_by_dest')):
        return []
    changes, stop = check_workspace(workspace_root, "geotag", args.command, getattr(args, "accept_changes", None))
    if stop:
        sys.exit(stop)
    return changes


def _auto_reprep_for_clean_move(args, workspace_root, reporter):
    """BLD-geotag_auto_reprep — auto re-prep for a clean by-dest move, run inside geotag's whole-run lock.

    The common operator flow is: move photos from by-date into the by-dest tree, then go straight to
    geotag. That move leaves the handoff stale (geotag derives each file's calibration `destination`
    from the handoff), so geotag would otherwise hard-stop and tell you to re-run prep by hand. Instead,
    for the *clean* case — workspace initialized, `0-sources` already empty (so no media is moved), and
    what the handoff no longer records truly (a move, or a by-dest photo removed or changed since, per
    `by_dest_reprep_pending`) the one thing pending — run the real prep phases (`plan` then `execute`) for the operator,
    announcing what and why. Everything else is left untouched for the in-lock gates to report:
    sealed/uninitialized, a non-empty `0-sources` dump (the cheapest hard gate — a bigger op the
    operator should launch knowingly), or nothing pending. Prep's commands run through
    `photos_1_prep._run_locked`, under the lock geotag already holds, so nothing is read before the lock
    and no other run can slip in between prep and geotag; `_check_reprep_gate` then re-validates (a
    non-clean move still hard-stops)."""
    if args.command != "plan":
        return
    if is_sealed(workspace_root) or not os.path.exists(guard_path(workspace_root)):
        return
    try:
        load_config(workspace_root)     # the folders are named by the workspace's configuration
    except Exception:
        return                          # missing or invalid — the preflight says so
    if (top_level_links(workspace_root) or missing_managed_folders(workspace_root)
            or misplaced_top_level_entries(workspace_root)
            or links_under(workspace_root, folder_name('photos_by_dest'))):
        return                          # a disturbed shape stops geotag before anything is scanned or planned
                                        # (RUL-shape_checked_first) — the preflight says which
    sources = folder_name('sources')
    src = os.path.join(workspace_root, sources)
    if os.path.isdir(src) and os.listdir(src):
        return                          # 0-sources holds a dump — cheapest hard gate; left to the scope gate
    ho_p = handoff_path(workspace_root)
    if not os.path.exists(ho_p):
        return
    try:
        with open(ho_p) as f:
            handoff = json.load(f)
    except (OSError, ValueError):
        return                          # unreadable handoff — let the normal flow surface it under the lock
    example = by_dest_reprep_pending(workspace_root, handoff)
    if not example:
        return                          # nothing pending — straight to geotag
    by_dest = folder_name('photos_by_dest')
    reporter.log(f"Prep's record of {by_dest}/ is out of date (e.g. {example}), and {sources}/ is "
                 f"empty — bringing it up to date before geotag: running prep plan + execute "
                 f"(executed only if the plan moves, renames or quarantines no media file)…")
    import types
    from . import photos_1_prep
    for cmd in ("plan", "execute"):
        # Geotag's own check has run, and recorded what it accepted: prep's finds the same workspace.
        prep_args = types.SimpleNamespace(command=cmd, jobs=getattr(args, "jobs", 4), accept_changes=None)
        try:
            # Prep's own closing `Next:` lines are held back: they name prep's next command where geotag goes on
            # (or stops) by itself, so only geotag's says what to do (output affordance;
            # test_auto_reprep_prints_only_geotag_s_next_step).
            with next_steps_muted():
                photos_1_prep._run_locked(prep_args, workspace_root, reporter)   # under geotag's lock
        except SystemExit as e:
            if e.code not in (0, None):
                reporter.error(f"Auto prep {cmd} did not succeed (exit {e.code}). Resolve it and re-run "
                               "geotag — nothing was geotagged.")
                emit_next_step(reporter, "resolve what prep reported above, then re-run `geotag plan`.")
                sys.exit(2)
        except Exception as e:
            reporter.error(f"Auto prep {cmd} failed: {e}. Resolve it and re-run geotag — nothing was geotagged.")
            emit_next_step(reporter, "resolve what prep reported above, then re-run `geotag plan`.")
            sys.exit(2)
        if cmd == "plan":
            _stop_unless_prep_plan_records_only(workspace_root, reporter)
    reporter.log("Re-prep complete; continuing with geotag.")


# The operations of prep's plan that touch no media file: its database records, and the removal of a folder
# the plan leaves empty — the whole of a plan that records a move the user made (RUL-auto_reprep_moves_no_media).
_PREP_FILE_OPS = ("move_no_clobber", "rename_no_clobber", "quarantine_move")


def _stop_unless_prep_plan_records_only(workspace_root, reporter):
    """Between the automatic re-prep's plan and its execute (RUL-auto_reprep_moves_no_media): prep's execute runs
    only when the plan it saved moves, renames or quarantines no media file. Recording the user's own move takes
    only database records (and the removal of the folders the move emptied); anything more — a rename or a
    quarantine in the by-date folders, say — is prep's work the user was never shown, so geotag stops, leaving
    the saved plan for the user to review and execute. A plan that cannot be read is not executed either."""
    from .photos_utils import prep_plan_path
    pp = prep_plan_path(workspace_root)
    try:
        with open(pp) as f:
            ops = json.load(f).get("operations")
        if not isinstance(ops, list):
            raise ValueError("no list of operations")
        media_ops = [op for op in ops if op.get("type") in _PREP_FILE_OPS
                     and media_class_for_ext(os.path.splitext(op.get("source") or "")[1]) in ("image", "raw", "video")]
    except (OSError, ValueError, AttributeError) as e:
        reporter.error(f"\nGeotag cannot proceed: prep's plan {pp} could not be read ({e}), so prep's execute "
                       "was not run. No media file was touched; nothing was geotagged.")
        emit_next_step(reporter, "`photos-cartographer prep plan` then `photos-cartographer prep execute`, "
                                 "then re-run `geotag plan`.")
        sys.exit(2)
    if not media_ops:
        return
    counts = {}
    for op in media_ops:
        counts[op["type"]] = counts.get(op["type"], 0) + 1
    reporter.error("\nGeotag cannot proceed: prep's plan does more than record the move — it would "
                   + ", ".join(f"{n} {t}" for t, n in sorted(counts.items())) + " of media file(s), e.g.:")
    for op in media_ops[:5]:
        reporter.log(f"  - {op['type']}: {op.get('source')} -> {op.get('destination')} ({op.get('reason')})")
    if len(media_ops) > 5:
        reporter.log(f"  ... and {len(media_ops) - 5} more.")
    reporter.log(f"\nGeotag runs prep's execute itself only when it moves, renames or quarantines no media file; "
                 f"this one it did not run. No media file was touched; the plan is saved at {pp}.")
    emit_next_step(reporter, "review it with `photos-cartographer prep dry-run`, apply it with "
                             "`photos-cartographer prep execute`, then re-run `geotag plan`.")
    sys.exit(2)


@ends_unforeseen_error_apart        # an error not foreseen ends with a status of its own (BLD-exit_statuses)
def run(args):
    workspace_root = os.getcwd()
    reporter = get_reporter()

    # Only prep creates the control directory (BLD-no_control_dir_stops): a folder without one is not a
    # workspace, and geotag stops there having created nothing — not even its lock file.
    if not os.path.isdir(control_dir(workspace_root)):
        reporter.error(f"Not an initialized workspace (no {CONTROL_DIR}/) — run prep first: "
                       "`photos-cartographer prep plan` then `photos-cartographer prep execute`. Nothing was created.")
        sys.exit(2)

    # The workspace's filesystem, before anything else is done, the lock included (RUL-local_filesystem_checked_first,
    # RUL-filesystem_requirements_tried).
    fs_err = workspace_filesystem_error(workspace_root)
    if fs_err:
        reporter.error(fs_err)
        sys.exit(2)

    # Whole-run workspace lock (RUL-one_workspace_lock, RUL-lock_before_reading): one lock across every phase, taken
    # before anything in the workspace is read; fail-fast.
    run_lock = WorkspaceLock(workspace_root, create=False)
    try:
        locked = run_lock.acquire()
    except LockFileError as e:      # a refusal, not "locked" (RUL-exit_status_says_how_it_ended)
        reporter.error(str(e))
        sys.exit(2)
    if not locked:
        owner = run_lock.read_owner() or {}
        detail = f" (pid {owner.get('pid')}, since {owner.get('started_at')})" if owner else ""
        reporter.log(f"Workspace is locked by an in-progress run{detail}; try again when it finishes.")
        sys.exit(1)
    reporter.log(f"Lock acquired: {run_lock.lock_path}")
    wf = None
    try:
        # The seal is checked before anything else is read (BLD-phases_check_seal), the walk over every folder
        # for its device included: a sealed workspace goes straight to the preflight, whose first check refuses it.
        vol_err = None if is_sealed(workspace_root) else workspace_volume_error(workspace_root)   # RUL-workspace_one_filesystem
        if vol_err:
            reporter.error(vol_err)
            sys.exit(2)
        # The workspace as the last execution left it (RUL-workspace_checked_first), before anything else is read.
        workspace_changes = _check_workspace(args, workspace_root) if args.command in ("plan", "execute", "finalize") \
            else []
        # The record of the table of countries, where the host has none of its own, read for the plan and its
        # staleness: one that cannot be read stops the run, naming it, before anything changes
        # (RUL-unreadable_zone_table_record_stops). A sealed workspace is refused on its seal, with nothing else read
        # (BLD-phases_check_seal).
        zone_err = None if is_sealed(workspace_root) else zone_table_record_error(workspace_root)
        if zone_err:
            reporter.error(f"\n{zone_err} Nothing was changed.")
            sys.exit(2)
        # BLD-geotag_auto_reprep: auto re-prep a clean by-dest move so the operator can go straight to geotag — prep's
        # plan and execute run inside this run's lock; the _check_reprep_gate below re-validates after.
        _auto_reprep_for_clean_move(args, workspace_root, reporter)
        if args.command == "plan":
            _plan_ready = False    # set once the executable plan (photos-24) is assembled
            wf = GeotagWorkflow(workspace_root)
            blockers, warnings, info = wf.preflight()
            for w in warnings:
                reporter.warn(f"  Warning: {w}")
            if blockers:
                reporter.error("\nGeotag cannot proceed:")
                for b in blockers:
                    reporter.log(f"  - {b}")
                reporter.log("\nNo geotag JSON was written.")
                emit_next_step(reporter, "resolve the blocker(s) above, then re-run `geotag plan`.")
                sys.exit(2)

            # Stages 2–4: build the in-memory model geotag reasons over — with the answers photos-21 holds to times
            # changed since geotag wrote them (BLD-changed_time_question); one that cannot be read is stopped on below.
            tdp = time_decisions_path(workspace_root)
            prior, problem = _load_prior_decisions(tdp)
            files = wf.build_file_model(prior if problem is None else None)
            # Order matters: run the IN-MEMORY camera-group recognition (which can abort on an unknown
            # group) BEFORE the disk-heavy GPX ingestion, so aborting to let the operator classify a
            # group doesn't waste the GPX parse — the next run re-ingests GPX only once this passes.
            # (Recognition needs only the file model, not GPX.)
            groups, unknown = wf.recognize_camera_groups(files)

            if unknown:
                reporter.error("\nGeotag cannot proceed: unknown camera group(s). In photos-00-config.json "
                      "under camera_time_and_timezone_policy.device_groups, REPLACE both arrays below "
                      "(phones = smartphone, auto timezone; fixed_clock_cameras = camera with a manual "
                      "clock), then re-run. Each array is the complete final list (your known groups plus "
                      "the new one(s)); the new group(s) appear in BOTH — keep each in only ONE array and "
                      "delete it from the other:\n")
                dg = CONFIG["camera_time_and_timezone_policy"]["device_groups"]
                # Emit the two arrays in the config file's OWN key order (the seed is written
                # sort_keys=True, so fixed_clock_cameras precedes phones) — a whole-block paste-over then
                # keeps the inter-array comma intact instead of pasting them in the reverse order and
                # dropping it. The loader refuses a configuration lacking either array or holding another
                # (RUL-config_complete), so the block holds exactly these two.
                labels = list(dg)
                for i, label in enumerate(labels):
                    existing = list(dg[label])
                    merged = existing + [k for k in unknown if k not in existing]
                    tail = "," if i < len(labels) - 1 else ""
                    if merged:
                        items = ",\n".join(f"    {json.dumps(k)}" for k in merged)
                        reporter.log(f'  "{label}": [\n{items}\n  ]{tail}')
                    else:
                        reporter.log(f'  "{label}": []{tail}')
                reporter.log("\nNo geotag JSON was written. Or class each in the decision editor "
                             "(`photos-cartographer edit`, its Cameras view), which writes the same arrays.")
                emit_next_step(reporter, "paste the array(s) above into photos-00-config.json (or class them in "
                                         "`photos-cartographer edit`), then re-run `geotag plan`.")
                sys.exit(2)

            gpx = wf.load_gpx(files)      # disk-heavy: only after the in-memory checks above have passed
            _stop_on_tracks(reporter, gpx, "No geotag JSON was written.")
            n_dest = len({f["destination"] for f in files})
            by_class = {}
            for g in groups.values():
                by_class[g["camera_group_class"]] = by_class.get(g["camera_group_class"], 0) + 1
            cls_summary = ", ".join(f"{n} {c}" for c, n in sorted(by_class.items())) or "none"
            reporter.log(f"Model built: {len(files)} photo(s) across {n_dest} destination(s); "
                  f"{len(groups)} camera group(s) ({cls_summary}); "
                  f"GPX {gpx.status} ({len(gpx.points)} point(s), fp {(gpx.fingerprint or '')[:12]}).",
                  stream="stdout")
            # Surface why GPX points were dropped, so an unparseable track never reads as a silently
            # "empty" one. Capped: one bad file can reject every one of its thousands of trkpts.
            # A link not followed, a ranked folder not there and a track file gone are each named, apart from the
            # cap (RUL-gone_track_told): the catalogue forgets a gone file once this plan keeps it.
            capped = [w for w in gpx.warnings if w not in gpx.told]
            if gpx.warnings:
                reporter.warn(f"GPX loading reported {len(gpx.warnings)} warning(s):")
                for w in gpx.told + capped[:GPX_WARNINGS_SHOWN]:
                    reporter.warn(f"  - {w}")
                if len(capped) > GPX_WARNINGS_SHOWN:
                    reporter.warn(f"  ... and {len(capped) - GPX_WARNINGS_SHOWN} more.")

            # Stages 5–6: time decisions (photos-21). Regenerate from current inputs while
            # preserving authored decisions (RUL-decision_kept); a sanity-validation failure on a preserved value
            # is a hard blocker that leaves the user's artifact untouched to be fixed (RUL-invalid_decision_kept).
            if problem:
                _stop_on_unreadable_decisions(reporter, problem)
            artifact, td_blockers = wf.build_time_decisions(files, groups, prior, gpx)
            # the tracks as widened for photos-21's readers (BLD-track_window)
            _stop_on_tracks(reporter, gpx, "No geotag JSON was written.")
            # photos-22 and photos-23 as the user left them, checked now: an invalid value in any of the three stops
            # the plan before any of them is written (BLD-geotag_checks_decisions, RUL-invalid_value_stops)
            later = {}
            for path, name in ((drift_validation_path(workspace_root), DRIFT_VALIDATION_ARTIFACT),
                               (gps_decisions_path(workspace_root), GPS_DECISIONS_ARTIFACT)):
                later[name], problem = _load_prior_decisions(path)
                if problem:
                    _stop_on_unreadable_decisions(reporter, problem)
            found = [(TIME_DECISIONS_ARTIFACT, td_blockers)] + [
                (name, blk) for name, blk in zip((DRIFT_VALIDATION_ARTIFACT, GPS_DECISIONS_ARTIFACT),
                                                 _split_authored(wf, files, later))]
            if any(blk for _n, blk in found):
                for name, blk in found:
                    if blk:
                        reporter.error(f"\nGeotag cannot proceed: invalid value(s) in {name}:")
                        for b in blk:
                            reporter.log(f"  - {b}")
                reporter.log("\nFix the field(s) and re-run; nothing was changed — no decision record was written.")
                sys.exit(2)
            # Back up any prior hand-edited decision file before regenerating it (incremental -NNN),
            # so an authored decision is always recoverable.
            _, _td_bak = write_versioned_json(tdp, artifact)
            if _td_bak:
                reporter.log(f"  Previous {TIME_DECISIONS_ARTIFACT} backed up to {_td_bak}")
            # an offset tag that holds no offset is read as none, and said (RUL-unreadable_offset_tag_told)
            for i, u in enumerate(wf.unreadable_offset_tags):
                if i == UNREADABLE_TAGS_SHOWN:
                    reporter.warn(f"  ... and {len(wf.unreadable_offset_tags) - i} more photo(s) whose offset tag "
                                  f"holds no offset (each listed in {TIME_DECISIONS_ARTIFACT}).")
                    break
                reporter.warn(f"  Warning: {u['relative_path']}: its {u['field']} holds {u['value']!r}, which is no UTC "
                              "offset — it is read as no offset tag.")
            # an offset tag beside a time asked whether to keep that the zone does not give
            # (BLD-changed_time_kept_tag_noted)
            for kd in wf.kept_tag_disagreements:
                reporter.warn(f"  Warning: {kd['relative_path']}: its offset tag says "
                              f"{utc_offset_text(kd['recorded_offset_seconds'])}, but {kd['timezone']} is "
                              f"{' or '.join(utc_offset_text(o) for o in kd['timezone_offsets_seconds'])} at the time "
                              "it holds. Kept as the true local time, it is read by the timezone, and the tag is "
                              "written to match.")
            for cr in wf.country_removals:
                reporter.warn(f"  Warning: {cr['destination']}: the country said there ({cr['country']}) was removed — "
                              f"{cr['because']}, which it lies in, is in {cr['country_there']}, and so is everything "
                              "inside it. A country is said once, at the top of its tree: that is how "
                              f"{folder_name('photos_by_dest')} must be laid out.")
            need_tz = sum(1 for d in artifact["destinations"].values()
                          if d["destination_timezone"]["requires_user_input"])
            need_off = sum(1 for d in artifact["destinations"].values()
                           for c in d["camera_group_time_decisions"].values() if c["requires_user_input"])
            need_changed = sum(1 for d in artifact["destinations"].values()
                               for c in (d.get("changed_times") or {}).values() if c["requires_user_input"])
            if artifact["requires_user_input"]:
                reporter.log(f"Wrote {TIME_DECISIONS_ARTIFACT}: status={artifact['status']} "
                      f"({need_tz} timezone + {need_off} clock-offset decision(s) need input"
                      + (f"; {need_changed} photo(s) hold a time changed since geotag wrote it — keep it as the "
                         "true local time, or take back geotag's" if need_changed else "")
                      + "). Edit the user_decision fields and re-run.", stream="stdout")
                # A photo with no recorded time that no date fallback covers stops geotag here, before any time is
                # resolved, named with its two ways out (RUL-untimed_photo_stops_geotag, RUL-untimed_photo_named).
                untimed_left = sorted(p for d in artifact["destinations"].values()
                                      if d["date_fallback"]["requires_user_input"]
                                      for p in d["date_fallback"].get("untimed_photos") or [])
                if untimed_left:
                    by_dest = folder_name('photos_by_dest')
                    reporter.error(f"\nGeotag cannot proceed: {len(untimed_left)} photo(s) in {by_dest}/ have no "
                                   f"recorded time, and no date fallback covers them: {_named(untimed_left)}. Give "
                                   "their folder (or a folder above it) a date fallback — a year, a year and month, "
                                   "or a day — in `photos-cartographer edit`, or as date_fallback.user_decision.date in "
                                   f"{TIME_DECISIONS_ARTIFACT}. Otherwise they belong in "
                                   f"{folder_name('missing_metadata')}/: give one a time there and prep files it into "
                                   f"{folder_name('photos_by_date')}/, to sort again.")
                    emit_next_step(reporter, "give their folder a date fallback (or move them out), then re-run "
                                             "`geotag plan`.")
                    sys.exit(2)
            else:
                reporter.log(f"Wrote {TIME_DECISIONS_ARTIFACT}: status=complete — all time decisions resolved.", stream="stdout")

                # Stage 7: time decisions are complete -> resolve UTC under the CURRENT offsets
                # (rows0). This drives drift detection (BLD-drift_validation) and, once 22 is clean, is recomputed
                # with the operator-validated offsets before anything downstream consumes it.
                # (A photo whose local time its zone repeats or skips is asked about in photos-21 itself, which is
                # not complete until each is answered: BLD-local_time_readings.)
                rows0 = compute_resolved_utc(files, groups, artifact)
                # the drift check reaches the photos' corrected times (BLD-track_window)
                wf.widen_tracks(gpx, wf.drift_window(files, artifact, rows0))
                _stop_on_tracks(reporter, gpx, f"No geotag JSON was written past {TIME_DECISIONS_ARTIFACT}.")

                # Stage 7a: GPS-drift validation (photos-22, RUL-unanchored_offset_confirmed) — the gate before phase
                # 23. A manual/timezone-derived offset with no native-GPS anchor is placed purely from its
                # resolved UTC, so a wrong offset silently mis-places the whole batch; 22 makes the
                # operator confirm each such bucket (a zero-scrub must be explicit) before GPS is built.
                dvp = drift_validation_path(workspace_root)
                prior_drift, problem = _load_prior_decisions(dvp)
                if problem:
                    _stop_on_unreadable_decisions(reporter, problem)
                drift_artifact, drift_blockers = wf.build_drift_validation(files, artifact, rows0, gpx, prior_drift)
                if drift_blockers:
                    reporter.error(f"\nGeotag cannot proceed: invalid value(s) in {DRIFT_VALIDATION_ARTIFACT}:")
                    for b in drift_blockers:
                        reporter.log(f"  - {b}")
                    reporter.log("\nFix the field(s) and re-run; the artifact was left unchanged.")
                    sys.exit(2)
                _, _dv_bak = write_versioned_json(dvp, drift_artifact)
                if _dv_bak:
                    reporter.log(f"  Previous {DRIFT_VALIDATION_ARTIFACT} backed up to {_dv_bak}")
                need_drift = sum(1 for d in drift_artifact["destinations"].values()
                                 for c in d["drift_decisions"].values() if c["requires_user_input"])
                if drift_artifact["requires_user_input"]:
                    reporter.log(f"Wrote {DRIFT_VALIDATION_ARTIFACT}: status={drift_artifact['status']} "
                          f"({need_drift} GPS-drift bucket(s) need confirmation). "
                          "Confirm each (a zero-scrub must be set explicitly) and re-run.", stream="stdout")
                elif drift_artifact["destinations"]:
                    reporter.log(f"Wrote {DRIFT_VALIDATION_ARTIFACT}: status=complete — all GPS-drift buckets confirmed.", stream="stdout")

                if not drift_artifact["requires_user_input"]:
                    # Stage 7b: re-resolve UTC consuming 22's validated offsets, persist the cache,
                    # and report the deterministic fingerprint downstream stages depend on
                    # (BLD-resolved_utc_fingerprint).
                    rows = compute_resolved_utc(files, groups, artifact, drift_offset_overrides(drift_artifact))
                    # placement reaches the photos' corrected times (BLD-track_window)
                    contradicted = contradicted_positions(artifact)
                    wf.widen_tracks(gpx, wf.placement_window(files, rows, contradicted))
                    _stop_on_tracks(reporter, gpx, f"No geotag JSON was written past {DRIFT_VALIDATION_ARTIFACT}.")
                    input_fps = {
                        "camera_time_policy_fingerprint": artifact["depends_on"]["camera_time_policy_fingerprint"],
                        "camera_group_key_version": CAMERA_GROUP_KEY_VERSION,
                        "photos_21_sha256": sha256_file(tdp),
                        "photos_22_sha256": sha256_file(dvp),
                        "prep_cache_fingerprint": (wf.handoff or {}).get("cache_fingerprint"),
                        "metadata_field_set_version": FIELD_SET_VERSION,
                        "gpx_fingerprint": gpx.fingerprint,
                    }
                    cache = GeotagCache(workspace_root)
                    try:
                        cache.replace_all(rows)
                    finally:
                        cache.close()
                    fp = resolved_utc_fingerprint(rows, input_fps)
                    n_valid = sum(1 for r in rows if r["resolved_utc_status"] == "valid")
                    reporter.log(f"Resolved UTC for {n_valid}/{len(rows)} photo(s) "
                          f"(resolved_utc_cache_fingerprint {fp[:12]}).", stream="stdout")

                    # Stage 8: GPS decisions (photos-23). Regenerate from the resolved rows + GPX,
                    # preserving authored GPS decisions; a bad authored coord leaves the artifact as-is.
                    gdp = gps_decisions_path(workspace_root)
                    prior_gps, problem = _load_prior_decisions(gdp)
                    if problem:
                        _stop_on_unreadable_decisions(reporter, problem)
                    gps_artifact, gps_blockers = wf.build_gps_decisions(files, rows, gpx, prior_gps, fp, contradicted,
                                                                        time_decisions=artifact)
                    if gps_blockers:
                        reporter.error("\nGeotag cannot proceed: invalid value(s) in "
                              f"{GPS_DECISIONS_ARTIFACT}:")
                        for b in gps_blockers:
                            reporter.log(f"  - {b}")
                        reporter.log("\nFix the field(s) and re-run; the artifact was left unchanged.")
                        sys.exit(2)
                    _, _gd_bak = write_versioned_json(gdp, gps_artifact)
                    if _gd_bak:
                        reporter.log(f"  Previous {GPS_DECISIONS_ARTIFACT} backed up to {_gd_bak}")
                    tot = {k: sum(d["gps_decisions"]["summary"][k] for d in gps_artifact["destinations"].values())
                           for k in ("automatic_gpx_interpolation", "automatic_gpx_extrapolation",
                                     "automatic_folder_fallback", "preserve_native_gps", "blocked")}
                    reporter.log(f"Wrote {GPS_DECISIONS_ARTIFACT}: status={gps_artifact['status']} "
                          f"({tot['preserve_native_gps']} native, {tot['automatic_gpx_interpolation']} interp, "
                          f"{tot['automatic_gpx_extrapolation']} extrap, {tot['automatic_folder_fallback']} fallback, "
                          f"{tot['blocked']} blocked).", stream="stdout")
                    for line in fallback_placement_lines(gps_artifact):
                        reporter.log(line, stream="stdout")
                    for ld in wf.lower_track_disagreements:
                        reporter.log(f"  Track {ld['gpx_file']} put {ld['photos']} photo(s) more than "
                                     f"{CONFIG['gpx_tracks_agree_max_distance_meters']:g} m from where the "
                                     f"higher-ranked {ld['outranked_by']} placed them; the higher-ranked placed them.")
                    for td in wf.track_disagreements:
                        # two tracks of one file (RUL-track_is_one_trk) are taken out of the file, not gpx_root
                        where = ("its file" if all(" (track " in n for n in td["gpx_files"]) else "gpx_root")
                        reporter.warn(f"  Warning: tracks {' and '.join(td['gpx_files'])} cover the same time in "
                                      f"different places, so neither placed {td['photos']} photo(s). If one is "
                                      f"not this trip's, take it out of {where} and re-run `geotag plan`.")

                    # Stage 9: assemble photos-24 only when ALL decision artifacts are complete
                    # (BLD-geotag_stage_order).
                    if (artifact["status"] == "complete" and drift_artifact["status"] == "complete"
                            and gps_artifact["status"] == "complete"):
                        plan, _ = wf.build_executable_plan(files, rows, artifact, gps_artifact, gpx, fp)
                        epp = executable_plan_path(workspace_root)
                        _, _ep_bak = write_versioned_json(epp, plan)
                        n_ops = sum(d["summary"]["operations_total"] for d in plan["destinations"].values())
                        reporter.log(f"Wrote {EXECUTABLE_PLAN_ARTIFACT}: status={plan['status']} "
                              f"(plan {plan['plan_id']}, {n_ops} operation(s)).", stream="stdout")
                        reporter.log(f"  Plan saved to {epp}", stream="stdout")
                        if _ep_bak:
                            reporter.log(f"  Previous plan backed up to {_ep_bak}", stream="stdout")
                        if plan["blockers"]:
                            reporter.error("\nThe plan cannot be executed:")
                            for b in plan["blockers"]:
                                reporter.log(f"  - {b}")
                            emit_next_step(reporter, "resolve the blocker(s) above, then re-run `geotag plan`.")
                            sys.exit(2)
                        _plan_ready = True
                        emit_next_step(reporter, "`geotag execute` to apply the plan.")

            if not _plan_ready:
                emit_next_step(reporter, "open the editor (`photos-cartographer edit`) to settle the "
                                         "worklist, then re-run `geotag plan`; when it reports the plan is "
                                         "complete, `geotag execute`.")

        elif args.command == "execute":
            wf = GeotagWorkflow(workspace_root)
            blockers, warnings, info = wf.preflight(for_execute=True)
            for w in warnings:
                reporter.warn(f"  Warning: {w}")
            if blockers:
                reporter.error("\nExecution cannot proceed:")
                for b in blockers:
                    reporter.log(f"  - {b}")
                emit_next_step(reporter, "resolve the blocker(s) above, then re-run `geotag execute`.")
                sys.exit(2)
            # Execution builds its file model from prep's log, carrying a photo's pinned values to a retaken
            # fingerprint: a log the handoff does not vouch for says nothing trustworthy of that, so execute
            # stops on it before any change — before the snapshot, before keeping decisions
            # (RUL-geotag_executes_on_vouched_log).
            log_blk = prep_log_blocker(workspace_root, wf.handoff)
            if log_blk:
                reporter.error("\nExecution cannot proceed:")
                reporter.log(f"  - {log_blk[0].upper() + log_blk[1:]}.")
                emit_next_step(reporter, "`prep plan` and `prep execute`, then `geotag plan`, then "
                                         "`geotag execute`.")
                sys.exit(2)
            if not os.path.exists(executable_plan_path(workspace_root)):
                reporter.log(f"No {EXECUTABLE_PLAN_ARTIFACT} — run `plan` first.")
                emit_next_step(reporter, "`geotag plan` first to build the executable plan.")
                sys.exit(2)
            now_iso = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
            execution_id = sha256_text(f"{now_iso}|{os.getpid()}")[:12]
            jobs = args.jobs or CONFIG.get("jobs") or 4
            try:
                summary = wf.execute_plan(jobs, now_iso, execution_id, workspace_changes=workspace_changes)
            except UnreadablePlan as e:
                # made from records still there: planned again, never repaired (BLD-unreadable_plan)
                reporter.error(f"\nExecution cannot proceed: {e}. Nothing was changed.")
                emit_next_step(reporter, f"{REPLAN_ADVICE}, then `geotag execute`.")
                sys.exit(2)
            except UnreadableRecord as e:
                reporter.error(f"\nExecution cannot proceed: {e}. Nothing was changed.")
                emit_next_step(reporter, f"repair it (or move it out of {CONTROL_DIR}/ if it cannot be "
                                         "repaired), then re-run `geotag execute`.")
                sys.exit(2)
            if summary.get("invalid"):
                reporter.error(f"\nExecution cannot proceed: invalid value(s) in {EXECUTION_SUMMARY_ARTIFACT}:")
                for s in summary["stale"]:
                    reporter.log(f"  - {s}")
                reporter.log("\nFix the field(s) and re-run; nothing was changed.")
                emit_next_step(reporter, f"fix the field(s) in {EXECUTION_SUMMARY_ARTIFACT}, then re-run `geotag execute`.")
                sys.exit(2)
            if summary.get("status") == "rejected":
                reporter.error("\nExecution rejected — the plan is stale; re-run `geotag plan` to replan:")
                for s in summary["stale"]:
                    reporter.log(f"  - {s}")
                emit_next_step(reporter, "re-run `geotag plan` to rebuild the plan, then `geotag execute`.")
                sys.exit(2)
            t = summary["totals"]
            reporter.log(f"Executed {EXECUTABLE_PLAN_ARTIFACT}: status={summary['status']} "
                  f"({t['metadata_time_writes']} time, {t['metadata_gps_writes']} gps, "
                  f"{t['renames']} rename(s); {len(summary['fingerprint_mismatches'])} fingerprint "
                  f"mismatch(es), {len(summary['failures'])} failure(s)). Wrote {EXECUTION_SUMMARY_ARTIFACT}.",
                  stream="stdout")
            if summary["status"] != "success":
                for f in summary.get("repeated_failures") or []:
                    # failed twice the same way: running again will not mend it (BLD-repeated_write_failure)
                    reporter.error(f"{f['relative_path']}: its write failed again as in the previous execution "
                                   f"({f['error']}); running again will not mend it — {f['way_out']}.")
                if summary["fingerprint_mismatches"]:
                    # the one question of photos-25, answerable in the editor and by hand (RUL-every_question_in_editor)
                    reporter.log(f"{len(summary['fingerprint_mismatches'])} photo(s) changed content when written: "
                                 "look at each and accept the ones right as they are — in the decision editor "
                                 "(`photos-cartographer edit`, its Execute view), or by hand in "
                                 f"{EXECUTION_SUMMARY_ARTIFACT}: fingerprint_mismatches[*].user_decision."
                                 "accept_fingerprint_change = true.")
                reporter.log(f"Review {EXECUTION_SUMMARY_ARTIFACT} and re-run `execute` once resolved.")
                emit_next_step(reporter, f"review {EXECUTION_SUMMARY_ARTIFACT}, resolve the issues, then "
                                         "re-run `geotag execute`.")
                sys.exit(3)
            emit_next_step(reporter, "`geotag finalize` to seal the geotag phase.")

        elif args.command == "finalize":
            wf = GeotagWorkflow(workspace_root)
            blockers, warnings, info = wf.preflight(for_execute=True, needs_exiftool=False)
            for w in warnings:
                reporter.warn(f"  Warning: {w}")
            if blockers:
                reporter.error("\nFinalize cannot proceed:")
                for b in blockers:
                    reporter.log(f"  - {b}")
                emit_next_step(reporter, "resolve the blocker(s) above, then re-run `geotag finalize`.")
                sys.exit(2)
            # Prep's log is copied only as the handoff vouches for it, by hash: missing, unreadable or
            # changed, it cannot be checked, and finalize stops rather than copy a stale record.
            with open(handoff_path(workspace_root)) as hf:
                log_blk = prep_log_blocker(workspace_root, json.load(hf))
            if log_blk:
                reporter.error("\nFinalize cannot proceed:")
                reporter.log(f"  - {log_blk[0].upper() + log_blk[1:]}.")
                emit_next_step(reporter, "`prep plan` and `prep execute`, then `geotag plan` onward as it asks, "
                                         "then `geotag finalize`.")
                sys.exit(2)
            now_iso = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
            fin_blockers = wf.finalize_package(now_iso)
            if fin_blockers:
                # each blocker names its own fix (an execution not yet successful, a photo with no position, …)
                reporter.error("\nCannot finalize:")
                for b in fin_blockers:
                    reporter.log(f"  - {b}")
                emit_next_step(reporter, "do what each line above says, then `geotag finalize`.")
                sys.exit(2)
            for w in getattr(wf, "finalize_warnings", []):
                reporter.warn(f"  partial record: {w}")
            placed = (read_executable_plan(workspace_root) or {}).get("placement") or {}   # read whole by finalize
            if placed:
                # the measure of the run: every photo, by how it came by its position — and those with none
                reporter.log("Positions: " + ", ".join(f"{n} {how.replace('_', ' ')}" for how, n in placed.items())
                             + f" — of {sum(placed.values())} photo(s).", stream="stdout")
            reporter.log(f"Finalized: wrote {COMPLETE_LOG_ARTIFACT}, {GEOTAG_DB_SNAPSHOT}, and "
                  f"{ARCHIVE_MANIFEST_ARTIFACT} to {CONTROL_DIR}/. The archival package is ready to "
                  "copy to permanent storage (geotag does not seal or merge).", stream="stdout")
            emit_next_step(reporter, "bless the library with `merge init-library` (if not already), then "
                                     "`merge plan` → `merge dry-run` → `merge execute`.")
    except KeyboardInterrupt:
        # Clean Ctrl-C: planning never mutates and execute is journalled/idempotent, so applied
        # files are confirmed and the next run resumes from the diff (RUL-geotag_execution_resumable). Exit quietly with
        # the conventional 130 instead of a traceback; the `finally` still releases the lock.
        reporter.log("\nInterrupted; aborting. Applied files are journalled — safe to rerun.")
        sys.exit(130)
    except SystemExit:
        _prune_planned_tracks(args, wf)       # a plan stopped where it must: its window is the last it reached
        raise
    else:
        _prune_planned_tracks(args, wf)
    finally:
        run_lock.release()


def _prune_planned_tracks(args, wf):
    """Once `geotag plan` has stopped — done, or at a decision or a blocker, never interrupted — the record keeps
    only the points of the window it reached, and those an executed plan used (BLD-track_catalogue)."""
    if args.command == "plan" and wf is not None and wf.planned_tracks is not None:
        wf.planned_tracks.prune()


def main(argv=None):
    parser = argparse.ArgumentParser(prog="cartographer.photos_2_geotag", description=GEOTAG_BLURB,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    add_arguments(parser)
    args = parser.parse_args(argv)
    if getattr(args, "command", None) is None:
        parser.print_help()
        return 0
    return run(args)


if __name__ == "__main__":
    main()
