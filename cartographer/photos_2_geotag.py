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
import xml.etree.ElementTree as ET
import zoneinfo
from datetime import datetime, timedelta, timezone

from .photos_utils import (fingerprint_method_blocker, links_under, replace_durably,
    country_table,
    code_fingerprint,
    CONFIG, CONTROL_DIR, control_dir, FINALIZED_MEDIA_ARTIFACT, track_memo_db_path, finalized_media_path, workspace_volume_error, config_path, handoff_path, guard_path, is_sealed, likely_new_dump,
    validate_config, load_config, sha256_file, sha256_text, media_class_for_ext, folder_name,
    folders_fingerprint, media_extensions_fingerprint,
    selected_gpx_root, NO_IDENTITY_KEY, FIELD_SET_VERSION, CAMERA_GROUP_KEY_VERSION, FOLDER_ROLES,
    missing_managed_folders, top_level_links, misplaced_top_level_entries, by_dest_reprep_pending,
    json_dependency, verify_json_dependency, handoff_content_fingerprint, handoff_filename_format_blocker, write_json_artifact, write_versioned_json, db_path, ensure_control_dir,
    journal_path, ContentHasher, _move_no_clobber, get_imagemagick_version,
    prep_log_path, prep_log_blocker, entries_not_carried, retaken_fingerprints, write_db_snapshot, take_zfs_snapshot,
    control_archive_members, write_control_archive, workspace_id,
    WorkspaceLock, ProgressCoordinator,
)
from .reporting import get_reporter, emit_next_step

TIME_DECISIONS_ARTIFACT = "photos-21-time-decisions.json"
DRIFT_VALIDATION_ARTIFACT = "photos-22-gps-drift-validation.json"
GPS_DECISIONS_ARTIFACT = "photos-23-gps-decisions.json"
EXECUTABLE_PLAN_ARTIFACT = "photos-24-executable-plan.json"
EXECUTION_SUMMARY_ARTIFACT = "photos-25-execution-summary.json"
COMPLETE_LOG_ARTIFACT = "photos-26-complete-log.json"
GEOTAG_DB_SNAPSHOT = "photos-26-geotag-ingest.db"
ARCHIVE_MANIFEST_ARTIFACT = "photos-26-archive-manifest.json"
ARCHIVE_ARTIFACT = "photos-26-archive.tar.gz"
EXECUTED_DIR = "executed"            # executed/<plan id>/: the decision records each executed plan ran against
GPX_WARNINGS_SHOWN = 10     # geotag plan prints at most this many GPX load warnings, then a count



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
            "content_fingerprint TEXT PRIMARY KEY, relative_path TEXT, original TEXT, captured_at TEXT)")
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
    for key in (file.get("content_fingerprint"), file.get("original_key")):
        if key is not None and key in by_fp:
            return by_fp[key]
    return by_path.get(file["relative_path"]) or {}


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


class GeotagWorkflow:
    """Stages 1–11: validate the workspace, build the model, produce photos-21/22/23 decision artifacts,
    compute resolved UTC, assemble photos-24-executable-plan.json (when decisions are complete),
    execute it into photos-25 (BLD-geotag_execution), and finalize the archival package photos-26
    (BLD-archive_manifest)."""

    def __init__(self, workspace_root: str):
        self.workspace_root = workspace_root
        self.handoff = None
        self._gpx_fingerprint = None
        # Live progress for the long phases (TTY: in-place bar; piped: a line every ~10 s; tests: quiet).
        self.coordinator = ProgressCoordinator()

    # --- preflight (RUL-geotag_gates, BLD-loop_gates) ------------------

    def preflight(self, for_execute=False):
        """Return (blockers, warnings, info). A non-empty `blockers` means geotag cannot
        proceed. Textual only — writes no JSON. The lifecycle guards (sealed / uninitialized /
        loose-root-file) and the development-started gate (RUL-development_after_merge) hard-stop early; the remaining
        by-dest scope and re-prep gates are collected so the rest are reported at once. `for_execute` keeps the
        lifecycle guards, the development gate, and the config/handoff load, but SKIPS the
        planning-phase scope and re-prep gates: execution validates against the plan's own dependency
        fingerprints + per-op preconditions, and the by-dest filenames it renames would otherwise trip
        the re-prep gate (BLD-loop_gates: it is a planning concern). The development gate is the exception — it is
        re-checked at execute/finalize too (a breakout begun after planning moves no planned file)."""
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

        # External-tool preflight: geotag reads existing EXIF GPS/time through exiftool and WRITES the
        # corrected tags through it at execute/finalize. There is no graceful fallback for the write, so
        # a missing exiftool is a hard blocker (checked for plan AND execute, before any heavy work).
        from .photos_utils import missing_tools
        if missing_tools(["exiftool"]):
            blockers.append("exiftool not found on PATH — geotag reads and writes EXIF GPS/time "
                            "through it. Install exiftool and re-run.")
            return blockers, warnings, info

        by_dest = folder_name('photos_by_dest')
        # Development-started guard (RUL-development_after_merge) — PRESENCE-STRICT and re-checked at execute/finalize
        # too, not just planning: the mere existence of a jpg/tif distribution subfolder under by-dest (even an
        # empty one) hard-stops. A breakout begun between `plan` and `execute` moves no planned file, so
        # the per-op media preconditions (BLD-geotag_execution) would not catch it; this existence check is what does.
        dev_found, nonphoto = self._scan_by_dest(by_dest)
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

        if for_execute:                 # execution skips the planning-phase scope/re-prep gates
            return blockers, warnings, info

        sources = folder_name('sources')
        by_date = folder_name('photos_by_date')

        # 3. Scope gates.
        if self._entries(sources):
            blockers.append(f"{sources}/ is not empty — prep leaves it empty after every run; an "
                            "unprocessed dump is waiting. Re-run prep to process it: `photos-cartographer prep plan` then `photos-cartographer prep execute`.")

        stray = sorted(rel for rel, mc in self._scan_media(by_date) if mc in ("image", "raw"))
        if stray:
            blockers.append(f"{by_date}/ still contains {len(stray)} photo(s) — finish moving them "
                            f"into {by_dest}/ before geotagging: {_named(stray)}.")

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

        # 4. Re-prep-after-move gate (RUL-prep_records_sort): a prep run must follow the latest by-date→by-dest move.
        self._check_reprep_gate(handoff, by_dest, by_date, blockers)

        # 5. The handoff's camera-group keys and extracted fields must come from this version of
        # cartographer: a key derived the old way would be matched against a config written for the new.
        self._check_derivation_versions(handoff, blockers)

        # 5b. A photo whose fingerprint was taken again keeps its pinned values only through a mapping that is
        # one to one; one that is not leaves geotag unable to say whose values are whose
        # (BLD-original_values_follow_fingerprint).
        if not prep_log_blocker(ws, handoff):
            try:
                with open(prep_log_path(ws)) as f:
                    _earlier, problem = retaken_fingerprints(json.load(f))
            except (OSError, ValueError):
                problem = None
            if problem:
                blockers.append(f"{problem.capitalize()}, which prep never writes: re-run prep — `photos-cartographer prep plan` then `photos-cartographer prep execute`.")

        # 6. Every photo must carry a recorded time: one with none can never be resolved to its true
        # time, and no decision of geotag's could supply one (prep sends such a photo to missing
        # metadata; one sorted into a destination by hand stops geotag here, before any planning).
        untimed = sorted(rec.get("relative_path") or "" for rec in (handoff.get("files") or [])
                         if rec.get("folder_class") == by_dest and rec.get("media_class") in ("image", "raw")
                         and not _has_recorded_time(rec))
        if untimed:
            blockers.append(f"{len(untimed)} photo(s) in {by_dest}/ have no recorded time, so their true "
                            f"time cannot be resolved: {_named(untimed)}. They belong in "
                            f"{folder_name('missing_metadata')}/ — move them there (or give them a time "
                            "and re-run prep), then re-run geotag.")

        info["by_dest_photos"] = sum(1 for _, mc in self._scan_media(by_dest) if mc in ("image", "raw"))
        return blockers, warnings, info

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
        """Return (dev_subfolders_found, non_photo_files) under 6-photos-by-dest."""
        dev_names = set(CONFIG.get("destination_distribution_subfolders") or [])
        base = os.path.join(self.workspace_root, by_dest)
        dev_found, nonphoto = [], []
        if not os.path.isdir(base):
            return dev_found, nonphoto
        for root, dirs, files in os.walk(base):
            for d in dirs:
                if d in dev_names:
                    dev_found.append(os.path.relpath(os.path.join(root, d), self.workspace_root))
            for f in files:
                if f.startswith('.'):
                    continue
                mc = media_class_for_ext(os.path.splitext(f)[1])
                if mc not in ("image", "raw"):
                    nonphoto.append((os.path.relpath(os.path.join(root, f), self.workspace_root), mc))
        return sorted(dev_found), nonphoto

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

    @staticmethod
    def _check_derivation_versions(handoff, blockers):
        for field, current, what in (("camera_group_key_version", CAMERA_GROUP_KEY_VERSION, "camera-group keys"),
                                     ("field_set_version", FIELD_SET_VERSION, "metadata fields")):
            other = sorted(rec.get("relative_path") or "" for rec in (handoff.get("files") or [])
                           if rec.get("metadata_status") and rec["metadata_status"].get(field) != current)
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

    def build_file_model(self):
        """One object per by-dest photo, built from the handoff's records (+ the EXIF prep already
        extracted into metadata_status.parsed_json). Geotag never re-reads the file — a stale
        handoff was already blocked (BLD-reprep_pending)."""
        by_dest = folder_name('photos_by_dest')
        files = []
        cache = GeotagCache(self.workspace_root)
        try:
            originals = cache.originals_all()
        finally:
            cache.close()
        earlier = self._retaken()
        for rec in (self.handoff.get("files") or []):
            if rec.get("folder_class") != by_dest or rec.get("media_class") not in ("image", "raw"):
                continue
            md = rec.get("metadata_status") or {}
            parsed = {}
            if md.get("parsed_json"):
                try:
                    parsed = json.loads(md["parsed_json"])
                except Exception:
                    parsed = {}
            fp = _recorded_fingerprint(rec)   # the preflight stops on a photo without one
            rel = rec.get("relative_path")
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
                "raw_times": {k: parsed.get(k) for k in
                              ("DateTimeOriginal", "CreateDate", "ModifyDate",
                               "OffsetTimeOriginal", "OffsetTimeDigitized", "OffsetTime", "TimeZone")
                              if parsed.get(k) is not None},
                "has_timestamp": _has_recorded_time(rec),
                "native_gps": ({"lat": parsed.get("GPSLatitude"), "lon": parsed.get("GPSLongitude"),
                                "processing_method": parsed.get("GPSProcessingMethod")}
                               if (md.get("has_native_gps") or parsed.get("has_native_gps")) else None),
                # A position geotag wrote is not the file's own: a re-run places the file again.
                "has_native_gps": bool(md.get("has_native_gps") if md.get("has_native_gps") is not None
                                       else parsed.get("has_native_gps"))
                                  and geotag_marker(parsed.get("GPSProcessingMethod")) not in POSITION_MARKERS,
                "geotag_marker": geotag_marker(parsed.get("GPSProcessingMethod")),
                "processing_method": parsed.get("GPSProcessingMethod"),   # the value a time mark extends
                "own_values": own_values(dict(parsed, has_native_gps=bool(md.get("has_native_gps")
                                                                           or parsed.get("has_native_gps")))),
                "metadata_field_set_version": md.get("field_set_version", FIELD_SET_VERSION),
                "folder_class": rec.get("folder_class"),
                "planned_filename": None,                    # set during the rename lookahead (Phase 6)
            })
            key, walked = fp, set()
            # a fingerprint taken again: the pin before it. One taken back to a value it had before ends
            # the walk where it started.
            while key is not None and key not in originals and key not in walked:
                walked.add(key)
                key = earlier.get(key)
            if key in walked:
                key = None
            if key is not None:                        # decide from the file's own values (BLD-decided_from_own_values)
                files[-1] = dict(from_originals(files[-1], originals[key]), original_key=key)
        files.sort(key=lambda f: f["relative_path"])
        return files

    # --- Stage 3: GPX index (BLD-track_points) ---------------------------

    def load_gpx(self):
        idx = GPXIndex(selected_gpx_root(), track_memo_db_path(self.workspace_root), CONFIG["gpx_track_precedence"]).build(self.coordinator)
        self._gpx_fingerprint = idx.fingerprint
        return idx

    # --- Stage 4: camera-group recognition + classification (BLD-known_camera_group) ---

    def recognize_camera_groups(self, files):
        """Group the file objects by camera_group_key and classify each via config device_groups.
        Returns (groups_by_key, unknown_keys), each group holding its key and `camera_group_class`. A key
        listed in `phones` is a smartphone (solved per-file); in `fixed_clock_cameras` a camera (needs a
        per-(group, destination, day) offset); otherwise it is unknown and must be classified before geotag.
        The class is all geotag needs of a group: its facts — files, span, positions — are prep's to report,
        in the handoff's `camera_groups`."""
        dg = (CONFIG.get("camera_time_and_timezone_policy") or {}).get("device_groups") or {}
        phones = set(dg.get("phones") or [])
        fixed = set(dg.get("fixed_clock_cameras") or [])
        groups = {}
        for key in sorted({f["camera_group_key"] for f in files}):
            # A file naming no camera is no group to class: solved on its own, never asked about
            # (BLD-unidentified_files).
            # One listed as both is classed as neither: the two are solved in opposite ways, and picking one
            # here would be geotag's guess (the offered classification lists a new group under both).
            cls = "unidentified" if key == NO_IDENTITY_KEY else \
                "unknown" if key in phones and key in fixed else \
                "smartphone" if key in phones else ("camera" if key in fixed else "unknown")
            groups[key] = {"camera_group_key": key, "camera_group_class": cls}
        unknown = [k for k, g in groups.items() if g["camera_group_class"] == "unknown"]
        return groups, unknown

    # --- Stages 5–6: time decisions (photos-21, BLD-timezone_cell, BLD-offset_buckets) ---------------------

    def build_time_decisions(self, files, groups, prior, gpx):
        """Build/regenerate the photos-21 content: per-destination civil timezone (BLD-timezone_cell) + per-
        (camera group, destination) clock-offset cells (BLD-offset_buckets), through the decision-field /
        auto-resolution / rerun-preservation engine (RUL-decision_kept). The offset cell's proposal is the
        GPX self-anchor (BLD-anchor_matching) when one can be inferred (else manual-required). Returns (artifact,
        blockers); blockers come from sanity-validating preserved authored values (RUL-invalid_decision_kept) and mean
        "do not overwrite — fix first"."""
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
        recall = {}                                  # (destination, bucket) -> what its cell was built from
        # A country is chosen once, at the top of its tree (RUL-country_chosen_once): `eff_country` maps a destination
        # to (code, the destination it was chosen at) for itself and everything inside it.
        eff_country, table = {}, country_table()
        self.country_removals = []
        ordered, containers = _expand_destinations(by_dest)
        self.coordinator.start_phase("calibrating clock offsets", len(ordered))
        for dest in ordered:
            self.coordinator.set_detail(_dest_label(dest))   # name the destination so heavy ones are visible
            is_container = dest in containers       # a file-less folder: holds a timezone/fallback, no offsets
            prior_d = prior_dests.get(dest, {})
            inherited_tz = _nearest_ancestor(dest, eff_tz, "tz")        # confirmable basis if no default
            if inherited_tz is not None and inherited_tz[1] is _ZONE_WAITS:
                inherited_tz = None                 # the destination above waits on its own photos: so does this
            prior_ud = (prior_d.get("destination_timezone") or {}).get("user_decision") or {}
            own_country, removed = prior_ud.get("country", "") or "", None
            above = next((eff_country[a] for a in _walk_ancestors(dest) if a in eff_country), None)
            if own_country and above:
                # What lies inside a destination is in that destination's country: the one said above stands, this one is taken out
                # of the decision — said aloud, and left in the record of this run.
                removed = {"country": own_country, "because": above[1], "country_there": above[0]}
                self.country_removals.append(dict(removed, destination=dest))
                own_country = ""
            if own_country and not isinstance(own_country, str):
                # A value that is not a country's code at all — a list, a number — is named like any other
                # the user wrote that cannot be taken (RUL-checked_timezones' neighbours: every value is checked).
                blockers.append(f"{dest}: destination_timezone.user_decision.country must be a country's code "
                                f"written as text, not {type(own_country).__name__}")
                own_country = ""
            if own_country and own_country not in table:
                blockers.append(f"{dest}: destination_timezone.user_decision.country {own_country!r} is not a "
                                + ("country code of the zone database (two letters, such as \"US\")." if table else
                                   "choice this host can read: its zone database has no table of countries."))
                own_country = ""
            country = (own_country, dest) if own_country else above
            if country:
                eff_country[dest] = country
            zones = table.get(country[0], {}).get("zones", []) if country else []
            if len(zones) == 1:
                inherited_tz = (country[1], zones[0])       # a country of one timezone: that is the zone
            elif zones and inherited_tz is not None and (own_country or inherited_tz[1] not in zones):
                inherited_tz = None                         # a zone from above the country is none of its own
            # A destination holding photos has one timezone for all of them (RUL-inherited_timezone_yields_to_photos):
            # the zone it would take — the one written for it, else the one it inherits — is set against what its own
            # photos record.
            written = prior_ud.get("manual_iana_timezone")
            candidate = written if written and _valid_iana(written) else (inherited_tz[1] if inherited_tz else None)
            against = _offsets_against_zone(by_dest[dest], groups, candidate) if candidate and not is_container else None
            tz_block = self._timezone_decision(dest, prior_d.get("destination_timezone") or {},
                                               blockers, inherited_tz, file_less=is_container, against=against,
                                               country=country, zones=zones, own_country=own_country,
                                               removed=removed)
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
            prior_cells = prior_d.get("camera_group_time_decisions") or {}
            cells, present = {}, []
            # Containers hold no media → no offset cells. A real destination gets one offset cell per
            # camera group, SPLIT per naive calendar date when the group spans >1 day there (BLD-offset_buckets): the
            # camera is set to local time each morning, so the offset is constant only within a day. The
            # bucket key is the bare group for a single day, else `<group>@<YYYY-MM-DD>`.
            for group in (sorted({f["camera_group_key"] for f in by_dest[dest]}) if not is_container else []):
                present.append(group)
                g = groups.get(group) or {}
                if g.get("camera_group_class") != "camera":
                    continue                       # smartphones are solved per-file; no offset cell
                # Days are counted over every photo of the group here, corrected ones too, so a bucket keeps
                # its key as photos arrive; only the photos not yet corrected are asked about or offset.
                gframes = [f for f in by_dest[dest] if f["camera_group_key"] == group]
                dates = sorted({d for f in gframes if (d := _naive_date(f.get("source_naive_time")))})
                for date in (dates if len(dates) > 1 else [None]):
                    sel = [f for f in gframes if not f.get("geotag_marker")
                           and (date is None or _naive_date(f.get("source_naive_time")) == date)]
                    bucket = group if date is None else f"{group}@{date}"
                    day = date or (dates[0] if dates else None)
                    prior_cell = _prior_day_cell(prior_cells, group, bucket, day)
                    if not sel:
                        # Every time here is corrected already and none has its own values pinned (a photo
                        # geotag marked elsewhere), so nothing asks. A resolved answer is kept for photos of
                        # the same camera and day arriving later — derived again from the decision, never
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
            destinations[dest] = {
                "destination_path": dest,
                "destination_timezone": tz_block,
                "camera_groups_present": present,
                "camera_group_time_decisions": cells,
            }
            if is_container:
                destinations[dest]["file_less"] = True
            self.coordinator.increment_completed(1)
        self._share_offsets_within_a_day(destinations, recall, gpx, blockers)
        self.coordinator.finish_phase()

        requires = (any(d["destination_timezone"]["requires_user_input"] for d in destinations.values())
                    or any(c["requires_user_input"] for d in destinations.values()
                           for c in d["camera_group_time_decisions"].values()))
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

    # Offsets a camera's own GPS gave: the only ones another destination's cell of the same day may take.
    _OWN_GPS_SOURCES = ("gpx_anchor_auto", "gpx_anchor_accepted", "gpx_anchor_chosen")

    def _share_offsets_within_a_day(self, destinations, recall, gpx, blockers):
        """A clock offset is the camera's for the day, wherever its photos were sorted (RUL-offset_shared_within_day).
        So, over the cells of one camera on one day in different destinations: (1) two offsets its own GPS gave that lie
        farther apart than `clock_offset_same_day_max_difference_seconds` are one clock read two ways —
        neither takes effect, both ask; a hand-written offset is the user's word, and is neither withheld nor
        counted. (2) A cell with no GPS evidence of its own is proposed the offset the camera's GPS gave
        that day elsewhere, in place of the timezone's guess: applied by itself where it applied itself
        there, else for the user to accept."""
        limit = CONFIG["clock_offset_same_day_max_difference_seconds"]
        by_day = {}
        for dest, d in destinations.items():
            for bucket, cell in d["camera_group_time_decisions"].items():
                if cell.get("day"):
                    by_day.setdefault((cell["camera_group"], cell["day"]), []).append((dest, bucket, cell))
        for (_group, _day), members in sorted(by_day.items()):
            if len(members) < 2:
                continue
            hand = lambda c: (c.get("user_decision") or {}).get("manual_offset_seconds") not in ("", None)
            donors = [(dest, bucket, c) for dest, bucket, c in sorted(members, key=lambda m: (m[0], m[1]))
                      if isinstance(c.get("effective_time_anchor"), dict) and not hand(c)
                      and c["effective_time_anchor"].get("source") in self._OWN_GPS_SOURCES]
            offs = [c["effective_time_anchor"]["offset_seconds"] for _d, _b, c in donors]
            if offs and max(offs) - min(offs) > limit:
                for dest, bucket, c in donors:
                    c["conflicts_with"] = [{"destination": d2, "bucket": b2,
                                            "offset_seconds": c2["effective_time_anchor"]["offset_seconds"]}
                                           for d2, b2, c2 in donors if c2 is not c]
                for _dest, _bucket, c in donors:
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
                if (c.get("proposal") or {}).get("proposal_source") not in ("timezone_naive", "manual_required") \
                        or (dest, bucket) not in recall:
                    continue
                group, g, prior_cell, anchor_frames, rep_naive, date, day, sel, tz = recall[(dest, bucket)]
                destinations[dest]["camera_group_time_decisions"][bucket] = self._offset_cell(
                    dest, group, g, prior_cell, anchor_frames, gpx, blockers, tz=tz, rep_naive=rep_naive,
                    date=date, day=day, photos=sel, shared=shared)

    def _tracks_by(self, gpx, times, frames):
        """The track points the drift check sets a bucket's photos against: those within
        `drift_check_track_window_seconds` of the photos' resolved `times`; or, none lying there, of the
        times the camera recorded — an offset days out carries the photos away from their own tracks, and
        is checked against those, not waved through."""
        window = CONFIG["drift_check_track_window_seconds"]
        near = lambda a, z: [p for p in gpx.points if (a - timedelta(seconds=window)) <= p.time_utc
                             <= (z + timedelta(seconds=window))]
        seg = near(min(times), max(times)) if times else []
        if not seg:
            clock = [t.replace(tzinfo=timezone.utc) for f in frames
                     if (t := _parse_camera_naive(f.get("source_naive_time")))]
            seg = near(min(clock), max(clock)) if clock else []
        return seg

    def _timezone_decision(self, dest, prior_tz, blockers, inherited=None, file_less=False, against=None,
                           country=None, zones=(), own_country="", removed=None):
        # Proposal precedence (BLD-timezone_cell): the nearest RESOLVED ancestor destination's timezone (a more
        # specific signal than the generic global default — e.g. a Japan/Kyoto leaf inheriting Japan's
        # Asia/Tokyo over a Europe/Brussels home default) wins; else the config default; else none.
        # Destinations are geographically NESTED — a child sits inside its parent, so it can scarcely
        # cross a timezone boundary the parent didn't — so a timezone proposal (inherited or config
        # default) auto-resolves without per-destination confirmation, staying overridable by a manual
        # entry. Only a destination with NO proposal at all (no ancestor, no default) blocks.
        default = (CONFIG.get("camera_time_and_timezone_policy") or {}).get("default_folder_timezone") or None
        if country and default not in zones:
            default = None                          # the usual zone is no zone of the country chosen here
        if inherited is not None and country and len(zones) == 1 and inherited[1] == zones[0]:
            proposed, source, confidence, inherited_from = zones[0], "country", "high", None
        elif inherited is not None:
            anc_path, anc_tz = inherited
            proposed, source, confidence, inherited_from = anc_tz, "inherited", "review_required", anc_path
        elif default:
            proposed, source, confidence, inherited_from = default, "config_default", "high", None
        else:
            proposed, source, confidence, inherited_from = None, "none", "none", None
        ud = prior_tz.get("user_decision") or {}
        manual = ud.get("manual_iana_timezone", "") or ""
        # The photos here that record another offset than the zone has: the zone stands against them only
        # on the user's explicit word, which names the offsets it was given for — a photo arriving with yet
        # another offset was never spoken for, and asks again.
        despite = ud.get("confirmed_despite_recorded_offsets", [])
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
        # applied to a trip abroad it would name and time its photos in the wrong zone; each top-level trip
        # answers once, everything beneath inheriting. A manual entry overrides either, and is the one decision
        # the user makes here (BLD-timezone_cell).
        # ...unless this destination's own photos say otherwise: a phone's photo here that records an offset
        # the inherited zone does not have at that time was taken in another zone, and the one zone change
        # of a trip is not adopted unasked. The user writes the zone — the inherited one, if it is right.
        auto = not manual and bool(proposed) and source in ("inherited", "country") and not unanswered
        if auto:
            effective = proposed
        block = {
            "proposed_iana_timezone": proposed,
            "proposal_source": source,
            "proposal_confidence": confidence,
            "user_decision": {"manual_iana_timezone": manual, "country": own_country,
                              "confirmed_despite_recorded_offsets": [int(o) for o in despite]},
            "effective_iana_timezone": effective,
            "requires_user_input": effective == "" and not file_less,   # a container never blocks
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
                     day=None, photos=(), shared=None):
        # One (camera group, destination[, date]) clock-offset bucket. Proposal precedence (BLD-offset_buckets):
        # GPX self-anchor → timezone-derived (camera assumed on local time; DST-aware, BLD-timezone_naive_offset) →
        # manual. Clock offsets do not inherit from the destination above. `date` (YYYY-MM-DD) is set when the group
        # spans >1 naive day here; the bucket key is `<key>@<date>` and is the blocker location.
        loc = key if date is None else f"{key}@{date}"
        proposal = infer_anchor_proposal(frames, gpx, CONFIG)
        if proposal is None and shared is not None:
            # no GPS evidence here, and the camera's own GPS fixed its clock that day in another destination
            proposal = {"proposal_source": "same_day_elsewhere", "proposed_offset_seconds": shared["offset_seconds"],
                        "shared_from": {"destination": shared["destination"], "bucket": shared["bucket"]},
                        "confidence": "high" if shared["applied_itself"] else "review_required",
                        "rank": "same_day"}
        if proposal is None and (tzr := _timezone_naive_offset(rep_naive, tz)) is not None:
            off_s, real_iso = tzr
            proposal = {"proposal_source": "timezone_naive", "proposed_offset_seconds": off_s,
                        "proposed_real_utc": real_iso, "proposed_from_timezone": tz,
                        "confidence": "review_required", "rank": "timezone_derived"}
        elif proposal is None:
            proposal = {"proposal_source": "manual_required"}
            # The bucket's earliest camera time is one its timezone repeats or skips: the zone gives two offsets
            # there, and none is proposed (RUL-ambiguous_local_time_never_guessed) — the cell says why it asks.
            amb = _zone_ambiguity(_parse_camera_naive(rep_naive), tz) if _valid_iana(tz) else None
            if amb is not None:
                proposal["timezone_ambiguous"] = {"camera_time": rep_naive, "timezone": tz, **amb}
        is_gpx = proposal.get("proposal_source") == "gpx_self_anchor"
        is_shared = proposal.get("proposal_source") == "same_day_elsewhere"
        has_offset = "proposed_offset_seconds" in proposal
        conflicting = proposal.get("conflicting_count", 0) > 0 or bool(proposal.get("tied"))   # anchors disagree
        imprecise = bool(proposal.get("imprecise_seconds"))    # the tracks stood still: no photo says when
        spread = CONFIG["gpx_anchor_offset_spread_max_seconds"]          # anchors this close agree
        tolerance = CONFIG["gpx_anchor_decision_tolerance_seconds"]      # a proposal this close is the one decided
        policy = CONFIG["camera_time_and_timezone_policy"]      # whole: the loader refuses one lacking a setting

        ud = prior_cell.get("user_decision") or {}
        accept = _decision_flag(ud, "accept_proposal", f"{dest}: camera_group_time_decisions[{loc}].user_decision", blockers)
        manual_off = ud.get("manual_offset_seconds", "")
        accepted_off = ud.get("accepted_offset_seconds", "")
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
            elif not has_offset or abs(int(accepted_off) - proposal["proposed_offset_seconds"]) > (tolerance if is_gpx else 0):
                stale = True                       # accepted a proposal that is no longer the one made
            else:
                # An offset no photo pins within the tracks' stay is supported by the camera's GPS, not
                # anchored by it: the drift check still asks (BLD-drift_validation).
                # What takes effect is the offset the user accepted: a proposal a few seconds from it is
                # the same finding, and no reason to move photos already corrected by the first.
                effective = {"offset_seconds": int(accepted_off),
                             "source": ("gpx_anchor_imprecise" if imprecise else "gpx_anchor_accepted") if is_gpx
                             else "same_day_accepted" if is_shared else "timezone_accepted"}
        elif is_gpx and not conflicting and not imprecise:
            # auto-resolution under the config flags (RUL-anchor_offset_auto_as_configured) — GPX-self-anchor only; a
            # timezone-derived proposal is confirmable, never auto-applied (the local-clock assumption can be wrong).
            n = proposal["anchor_count"]
            if (n >= 2 and policy["multi_anchor_auto_apply"]) or \
               (n == 1 and policy["single_anchor_auto_apply"]):
                effective = {"offset_seconds": proposal["proposed_offset_seconds"], "source": "gpx_anchor_auto"}
                decision_mode = "auto_resolved"
        anchored_by = None
        if isinstance(effective, dict) and effective["source"] == "gpx_anchor_auto":
            # the tracks the offset rests on, as they are now: what keeping it later is checked against
            anchored_by = [{"gpx_file": f, "sha256": gpx.file_sha.get(f)} for f in
                           sorted({a["gpx_match"]["gpx_file"] for a in proposal["anchors"]
                                   if abs(a["proposed_offset_seconds"] - effective["offset_seconds"]) <= spread})]
        if effective == "" and not stale and manual_off in ("", None) and not accept:
            # An offset found from the camera's own GPS stays this camera's offset for the day when the
            # photos that gave it are corrected and later ones bring no anchor — while what it rested on
            # still stands: every track that anchored it is under gpx_root unchanged, and no photo that has
            # arrived since says otherwise. A user's answer needs no such keeping: it is preserved as their
            # decision, and withdrawing it takes effect.
            earlier = prior_cell.get("effective_time_anchor")
            rests_on = prior_cell.get("anchored_by")
            if isinstance(earlier, dict) and earlier.get("source") == "gpx_anchor_auto" \
                    and isinstance(rests_on, list) and rests_on \
                    and all(isinstance(t, dict) and t.get("gpx_file") in gpx.file_sha
                            and gpx.file_sha[t["gpx_file"]] == t.get("sha256") for t in rests_on) \
                    and not (is_gpx and (conflicting or imprecise
                                         or abs(proposal["proposed_offset_seconds"] - earlier.get("offset_seconds", 0)) > tolerance)):
                effective, decision_mode, anchored_by = earlier, "kept_from_earlier", rests_on
        if effective != "" or stale or manual_off not in ("", None) or accept:
            pass                                   # decided above, or the user's to decide
        elif is_shared and shared["applied_itself"]:
            effective = {"offset_seconds": proposal["proposed_offset_seconds"], "source": "same_day_auto"}
            decision_mode = "auto_resolved"
        elif proposal.get("proposal_source") == "timezone_naive" and photos:
            # A timezone's guess is asked about once, where it can be checked: with tracks by the photos it
            # goes to the drift check as it stands, and the confirmation there is its acceptance
            # (BLD-timezone_naive_offset) — nothing is planned until then. With no track to check it against, it is
            # accepted here.
            times = [t.replace(tzinfo=timezone.utc) + timedelta(seconds=proposal["proposed_offset_seconds"])
                     for f in photos if (t := _parse_camera_naive(f.get("source_naive_time")))]
            if self._tracks_by(gpx, times, photos):
                effective = {"offset_seconds": proposal["proposed_offset_seconds"], "source": "timezone_unconfirmed"}
                decision_mode = "to_be_confirmed_against_tracks"

        cell = {
            "camera_group": key,
            "camera_group_class": g.get("camera_group_class", "camera"),
            "proposal": proposal,
            "user_decision": {"accept_proposal": accept,
                              "accepted_offset_seconds": accepted_off if accepted_off is not None else "",
                              "manual_offset_seconds": manual_off if manual_off is not None else ""},
            "effective_time_anchor": effective,
            "requires_user_input": effective == "",
            "stale_user_decision": stale,
        }
        if anchored_by:
            cell["anchored_by"] = anchored_by
        if date is not None:
            cell["date"] = date                    # this bucket covers only that naive calendar date
        if day is not None:
            cell["day"] = day                      # the day its photos are of, whatever its key
        if decision_mode:
            cell["decision_mode"] = decision_mode
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

    _DRIFT_TRIGGER_SOURCES = ("timezone_accepted", "timezone_unconfirmed", "manual", "gpx_anchor_imprecise")

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
        by_dest_group = {}
        for f in files:
            if not f.get("geotag_marker"):                # a corrected time has no drift left to check
                by_dest_group.setdefault((f["destination"], f["camera_group_key"]), []).append(f)
        resolved_by_path = {r["relative_path"]: r["resolved_utc"] for r in rows0
                            if r["resolved_utc_status"] == "valid"}
        prior_dests = ((prior or {}).get("destinations")) or {}
        track_sha = gpx.file_sha if gpx is not None else {}
        destinations = {}
        for dest, d in (time_artifact.get("destinations") or {}).items():
            prior_cells = (prior_dests.get(dest, {}).get("drift_decisions")) or {}
            cells = {}
            for bucket, cell in (d.get("camera_group_time_decisions") or {}).items():
                eff = cell.get("effective_time_anchor")
                if not (isinstance(eff, dict) and eff.get("source") in self._DRIFT_TRIGGER_SOURCES):
                    continue                                  # gpx-anchored (or unresolved) -> reliable / N/A
                group, date = cell.get("camera_group"), cell.get("date")
                frames = [f for f in by_dest_group.get((dest, group), [])
                          if date is None or _naive_date(f.get("source_naive_time")) == date]
                prior_drift = _prior_day_cell(prior_cells, group, bucket, cell.get("day"))
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
                times = [t for f in frames if (t := _parse_utc(resolved_by_path.get(f["relative_path"])))]
                if not times and eff.get("source") != "timezone_unconfirmed":
                    continue                                  # nothing resolves -> not a drift case
                seg = self._tracks_by(gpx, times, frames)
                # An offset nobody has accepted is never passed over: it is here to be confirmed, tracks
                # or none.
                if not seg and eff.get("source") != "timezone_unconfirmed":
                    continue                                  # no GPX coverage -> phase 23 fallback/lost
                cells[bucket] = self._drift_cell(dest, bucket, cell, seg, frames,
                                                 prior_drift, blockers, date=date, track_sha=track_sha)
            if cells:
                destinations[dest] = {"destination_path": dest, "drift_decisions": cells}
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
        # A confirmation names the offset it was made against (RUL-confirmation_holds_for_its_offset), and holds only
        # while that is the offset: changed in photos-21 since, it is stale — kept as written, applied to nothing, the
        # bucket asking again until confirmed anew. One naming none confirms nothing: a zero scrub is never implied.
        if confirmed and (against == "" or against is None):
            blockers.append(f"{dest}: drift_decisions[{loc}].user_decision.confirmed_offset_seconds must be the "
                            f"offset confirmed — the current one is {current}.")
            confirmed_ok = False
        elif confirmed and not _valid_offset(against):
            blockers.append(f"{dest}: drift_decisions[{loc}].user_decision.confirmed_offset_seconds "
                            "must be a whole number of seconds.")
            confirmed_ok = False
        else:
            # a changed offset or changed tracks: the check asks again, the confirmation kept as written
            # (RUL-changed_offset_asked_again, RUL-changed_tracks_asked_again, RUL-stale_confirmation_kept)
            stale = bool(confirmed) and named_ok and (int(against) != current or not tracks_hold)
            confirmed_ok = bool(confirmed) and named_ok and not stale
        if confirmed_ok:
            if corrected == "" or corrected is None:
                effective = {"offset_seconds": current, "source": "gps_drift_validated"}   # zero scrub
            elif _valid_offset(corrected):
                effective = {"offset_seconds": int(corrected), "source": "gps_drift_validated"}
            else:
                blockers.append(f"{dest}: drift_decisions[{loc}].user_decision.corrected_offset_seconds "
                                "must be empty or a whole number of seconds.")
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
                     "manual_review_required", "blocked", "no_gps_change_needed")

    def build_gps_decisions(self, files, resolved_rows, gpx, prior, resolved_fp):
        """Build/regenerate photos-23 (BLD-gps_decisions_record): the BLD-placement_order decision per by-dest file,
        grouped by destination as automatic-category SUMMARIES with file paths only for review/blocker items.
        Destinations are processed parent-first so a folder_fallback inherits its nearest resolved
        ancestor's effective fallback (BLD-folder_fallback_cell). Returns (artifact, blockers)."""
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
        fallback_eff = {}                                     # (dest, None) -> effective fallback coord
        ordered, containers = _expand_destinations(by_dest)
        self.coordinator.start_phase("deciding GPS placement", len(files))
        for dest in ordered:
            self.coordinator.set_detail(_dest_label(dest))
            is_container = dest in containers       # a file-less folder: its fallback only seeds children
            prior_d = prior_dests.get(dest, {})
            inherited = _nearest_ancestor(dest, fallback_eff, None)
            fb_cell = self._folder_fallback_cell(dest, prior_d.get("folder_fallback") or {}, inherited, blockers)
            eff_fb = fb_cell["effective_fallback"]
            fallback_eff[(dest, None)] = eff_fb

            items = (prior_d.get("gps_decisions") or {}).get("review_items") or []
            prior_reviews = ({ri["content_fingerprint"]: ri for ri in items if ri.get("content_fingerprint")},
                             {ri["relative_path"]: ri for ri in items if not ri.get("content_fingerprint")})
            counts = {k: 0 for k in self._SUMMARY_KEYS}
            review_items, gpx_files = [], set()
            for f in sorted(by_dest.get(dest, []), key=lambda x: x["relative_path"]):
                rel = f["relative_path"]
                ru = _parse_utc(utc_by_path.get(rel)) if utc_by_path.get(rel) else None
                fd = _prior_review(prior_reviews, f).get("user_decision") or {}
                self._validate_review_decision(dest, rel, fd, blockers)
                why = {}
                cat, coord = classify_gps(f, ru, gpx, CONFIG, eff_fb, fd, why)
                if why.get("reason") == "tracks_disagree":
                    disagreeing[tuple(why["gpx_files"])] = disagreeing.get(tuple(why["gpx_files"]), 0) + 1
                for lt in (coord or {}).get("lower_tracks") or []:
                    # a lower-ranked track farther from the place than tracks may differ: counted, never asked
                    # (RUL-lower_track_disagreements_told)
                    if lt["apart_meters"] > CONFIG["gpx_tracks_agree_max_distance_meters"]:
                        k = (lt["gpx_file"], coord["gpx_file"])
                        outranked[k] = outranked.get(k, 0) + 1
                counts["files_total"] += 1
                if cat == "preserve_native":
                    counts["preserve_native_gps"] += 1
                elif cat == "gpx_interpolation":
                    counts["automatic_gpx_interpolation"] += 1; gpx_files.add(coord.get("gpx_file"))
                elif cat == "gpx_extrapolation":
                    counts["automatic_gpx_extrapolation"] += 1; gpx_files.add(coord.get("gpx_file"))
                elif cat == "manual_fallback":
                    counts["automatic_folder_fallback"] += 1
                elif cat == "manual_locked":
                    counts["manual_locked"] += 1
                    review_items.append(self._review_item(f, "manual_locked", fd, False))
                elif cat == "no_change":
                    counts["no_gps_change_needed"] += 1
                    review_items.append(self._review_item(f, "accepted_unlocated", fd, False, why))
                else:                                          # blocked
                    counts["blocked"] += 1
                    review_items.append(self._review_item(f, "no_reliable_gps_source", fd, True, why))
                self.coordinator.increment_completed(1)
            counts["manual_review_required"] = sum(1 for ri in review_items if ri["requires_user_input"])
            destinations[dest] = {
                "destination_path": dest,
                "folder_fallback": fb_cell,
                "gps_decisions": {
                    "summary": counts,
                    "automatic_decision_summary": {
                        "gpx_files_used": sorted(g for g in gpx_files if g),
                        "max_interpolation_gap_seconds": CONFIG["gpx_interpolation_max_gap_seconds"],
                        "max_distance_to_track_m": CONFIG["gpx_interpolation_max_distance_meters"],
                        "confidence": "mixed" if counts["blocked"] else "automatic",
                        "notes": ["Automatic decisions are summarized here; exact file-level write "
                                  "operations are listed only in photos-24-executable-plan.json."],
                    },
                    "review_items": review_items,
                },
            }
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

    def _folder_fallback_cell(self, dest, prior_fb, inherited, blockers):
        ud = prior_fb.get("user_decision") or {}
        flat, flon = ud.get("fallback_lat", ""), ud.get("fallback_lon", "")
        accept = _decision_flag(ud, "accept_proposal", f"{dest}: folder_fallback.user_decision", blockers)
        if _half_position(flat, flon):
            blockers.append(f"{dest}: folder_fallback.user_decision fallback_lat/lon must both be set, or neither.")
        if inherited is not None:
            anc_path, anc_coord = inherited
            proposal = {"proposal_source": "inherited", "proposed_fallback": anc_coord,
                        "inherited_from": anc_path}
        else:
            proposal = {"proposal_source": "manual_required"}
        effective, stale = None, False
        if flat not in (None, "") and flon not in (None, ""):
            if _valid_coord(flat, flon):
                effective = {"lat": flat, "lon": flon}
            else:
                blockers.append(f"{dest}: folder_fallback.user_decision fallback_lat/lon out of range.")
        elif accept:
            if proposal["proposal_source"] == "inherited":
                effective = proposal["proposed_fallback"]
            else:
                stale = True                                  # accepted a fallback that does not exist
        return {
            "proposal": proposal,
            "user_decision": {"fallback_lat": flat, "fallback_lon": flon, "accept_proposal": accept},
            "effective_fallback": effective,
            "requires_user_input": False,                     # the fallback is optional, never blocks
            "stale_user_decision": stale,
        }

    def _validate_review_decision(self, dest, rel, ud, blockers):
        mlat, mlon = ud.get("manual_lat", ""), ud.get("manual_lon", "")
        where = f"{dest}/{os.path.basename(rel)}"
        if _half_position(mlat, mlon):
            blockers.append(f"{where}: review manual_lat/lon must both be set, or neither.")
        elif mlat not in (None, "") and not _valid_coord(mlat, mlon):
            blockers.append(f"{where}: review manual_lat/lon out of range.")
        _decision_flag(ud, "accept_unlocated", f"{where}: user_decision", blockers)

    def _review_item(self, f, reason, ud, requires, why=None):
        item = {
            "relative_path": f["relative_path"], "content_fingerprint": f.get("content_fingerprint"),
            "reason": reason,
            "user_decision": {"manual_lat": ud.get("manual_lat", ""), "manual_lon": ud.get("manual_lon", ""),
                              "accept_unlocated": bool(ud.get("accept_unlocated", False))},
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
            "gpx_tracks_agree_max_distance_meters")}, sort_keys=True)
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

        by_dest = {}
        for f in files:
            by_dest.setdefault(f["destination"], []).append(f)

        destinations, all_ops, media_pre = {}, [], []
        placement = {}                                # how each photo comes by its position: the measure of the run
        for dest in sorted(by_dest):
            g_d = g_dests.get(dest, {})
            eff_fb = (g_d.get("folder_fallback") or {}).get("effective_fallback")
            reviews = {ri["relative_path"]: (ri.get("user_decision") or {})
                       for ri in ((g_d.get("gps_decisions") or {}).get("review_items") or [])}
            track_of, lower_of = {}, {}
            unlocated = []
            tz = ((t_dests.get(dest, {}).get("destination_timezone")) or {}).get("effective_iana_timezone") or ""
            rename_inputs = [{"relative_path": f["relative_path"],
                              "resolved_utc": (utc_by_path.get(f["relative_path"]) or {}).get("resolved_utc"),
                              "destination_timezone": tz} for f in by_dest[dest]]
            renames = {r["relative_path"]: r for r in plan_renames(rename_inputs, fmt)}

            ops, no_ops = [], []
            for f in sorted(by_dest[dest], key=lambda x: x["relative_path"]):
                rel = f["relative_path"]
                ru = (utc_by_path.get(rel) or {}).get("resolved_utc")
                cat, coord = classify_gps(f, _parse_utc(ru) if ru else None, gpx, cfg,
                                          eff_fb, reviews.get(rel))
                if coord and coord.get("gpx_file"):
                    track_of[rel] = coord["gpx_file"]
                    lower_of[rel] = coord.get("lower_tracks")
                how = ("native" if cat == "preserve_native" else "unlocated" if coord is None
                       else _TRACK_MARKER.get(coord.get("method")) or cat)
                placement[how] = placement.get(how, 0) + 1
                if cat == "no_change":
                    # left without a position by the user's own answer: recorded with the plan, so the
                    # log can say so and cite the decision (RUL-log_cites_decisions)
                    unlocated.append({"relative_path": rel, "content_fingerprint": f.get("content_fingerprint"),
                                      "because": manual_gps_pointer("manual_locked", dest, rel, None)})
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
                        o["pre_state"] = held_time_pre_state(f)   # the time and offset it replaces, for the log
                    elif o["type"] == "metadata_gps_write" and o.get("gps_origin") == "recompute_automated":
                        # the track that placed it, and the instant it was placed at: what the position rests on
                        o["provenance"] = {"gpx_file": track_of.get(rel), "resolved_utc": ru}
                        if lower_of.get(rel):
                            # how far each lower-ranked track put it (RUL-lower_track_distance_recorded)
                            o["provenance"]["lower_tracks"] = lower_of[rel]
                    elif o["type"] == "metadata_gps_write" and o.get("gps_origin") == "apply_manual":
                        o["provenance"] = {"because": manual_gps_pointer(cat, dest, rel, g_d.get("folder_fallback"))}
                        o["pre_state"] = held_pre_state(f)        # the position it replaces, for the log
                    elif o["type"] == "gps_marker_write" and (o.get("writes") or {}).get("GPSLatitude") == "":
                        o["pre_state"] = held_pre_state(f)        # the position it clears, for the log
                if fops:
                    ops.extend(fops)
                else:
                    no_ops.append(rel)
                media_pre.append({"relative_path": rel, "content_fingerprint": f.get("content_fingerprint"),
                                  "size": f.get("size"), "mtime_ns": f.get("mtime_ns")})
            destinations[dest] = {"destination_path": dest, "operations": ops, "no_ops": no_ops}
            if unlocated:
                destinations[dest]["left_unlocated"] = unlocated

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
        plan = {
            "artifact_type": "executable_plan",
            "artifact_name": EXECUTABLE_PLAN_ARTIFACT,
            "plan_id": sha256_text(json.dumps(depends_on, sort_keys=True))[:16],
            "status": "blocked" if blockers else "ready",
            "executable": not blockers,
            "blockers": blockers,
            "placement": dict(sorted(placement.items())),
            "destinations": destinations,
            "depends_on": depends_on,
        }
        return plan, blockers

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
        }

    # --- Stage 10: execution (photos-25, BLD-geotag_execution) ---------------

    _META_OP_TYPES = ("metadata_time_write", "metadata_gps_write", "gps_marker_write")
    _OP_TOTAL_KEY = {"metadata_time_write": "metadata_time_writes", "metadata_gps_write": "metadata_gps_writes",
                     "gps_marker_write": "gps_marker_writes", "rename_no_clobber": "renames"}

    def _exiftool_write(self, abs_path, tags):
        """Apply a file's batched tag writes so that an interruption at any moment — a kill or a power cut — leaves
        the photo as it was or wholly rewritten (BLD-metadata_safe_write): exiftool writes the new file beside the
        photo as `<file>_exiftool_tmp`, never touching the photo; that file is synced to disk, then renamed over the
        photo, then the folder synced. Returns True on success. The single seam the tests mock to avoid invoking
        exiftool."""
        # An interrupted earlier write can have left `<file>_exiftool_tmp`. Geotag re-applies every un-confirmed
        # file on resume, and the only file that can hold one is the one interrupted mid-write (never confirmed, so
        # revisited here) — so removing the leftover for THIS target right before rewriting it cleans exactly the one
        # that can exist. Safe: the photo is untouched (the rename never happened) and the leftover is a partial
        # copy, never user media.
        tmp = abs_path + "_exiftool_tmp"
        try:
            os.remove(tmp)
        except OSError:
            pass  # absent (the normal case) or unremovable — exiftool refuses an output that exists
        cmd = (["exiftool", "-n"] + [f"-{k}={v}" for k, v in sorted(tags.items())] + ["-o", tmp, abs_path])
        try:
            if subprocess.run(cmd, capture_output=True, text=True, stdin=subprocess.DEVNULL).returncode != 0:
                raise OSError("exiftool refused the write")
            st = os.stat(abs_path)
            os.chmod(tmp, stat.S_IMODE(st.st_mode))          # the photo keeps the permissions it had
            try:
                os.chown(tmp, st.st_uid, st.st_gid)
            except OSError:
                pass                                         # not ours to give: the photo becomes the user's own
            replace_durably(tmp, abs_path)
            return True
        except Exception:
            try:
                os.remove(tmp)
            except OSError:
                pass
            return False

    def _exiftool_read(self, abs_path, keys):
        """The file's current values of `keys`, numeric (-n), as exiftool reports them; {} if it cannot be read.
        The seam the tests mock, beside `_exiftool_write`."""
        try:
            out = subprocess.run(["exiftool", "-j", "-n"] + [f"-{k}" for k in keys] + [abs_path],
                                 capture_output=True, text=True, stdin=subprocess.DEVNULL)
            return (json.loads(out.stdout) or [{}])[0] if out.returncode == 0 else {}
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
                       ("gpx_fingerprint", gpx.fingerprint)):
            if dep.get(k) != cur:
                stale.append(f"{k} changed")
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
            return False

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
            if not self._exiftool_write(abs_path, tags):
                res["failed"] = [o["operation_id"] for o in write_ops]
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
            try:
                _move_no_clobber(abs_path, os.path.join(d, o["to"]))
                res["applied"].append(o["operation_id"])
            except Exception as e:
                res["failed"].append(o["operation_id"])
                res["blocker"] = f"{rel}: rename failed ({e})"
                return res
        return done(final_abs)

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
                    "blocker": f"{rel}: could not be applied ({type(e).__name__}: {e})"}

    def execute_plan(self, jobs, now_iso, execution_id):
        """Stage 10 (BLD-geotag_execution): apply photos-24 after re-validating every dependency, journaling for
        idempotent resume, verifying content fingerprints, and writing photos-25. now_iso /
        execution_id are injected so the fingerprint-bearing body stays reproducible. Returns the
        summary dict (status 'rejected' with stale reasons if the plan no longer applies)."""
        ws = self.workspace_root
        with open(executable_plan_path(ws)) as f:
            plan = json.load(f)
        gpx = GPXIndex(selected_gpx_root(), track_memo_db_path(ws), CONFIG["gpx_track_precedence"]).build(self.coordinator)
        stale = self.revalidate_plan(plan, gpx)
        if stale:
            return {"status": "rejected", "plan_id": plan.get("plan_id"), "stale": stale}
        self._keep_executed_decisions(plan)

        # Optional pre-mutation ZFS snapshot (BLD-geotag_execution), labelled "geotag" so it never collides
        # with prep's "prep-" snapshot. A REQUIRED snapshot that cannot be taken aborts before any
        # mutation; the record is carried into photos-25 either way.
        snapshot = take_zfs_snapshot(ws, plan["plan_id"], "geotag")
        if snapshot is not None and snapshot["required"] and not snapshot["ok"]:
            reason = f"required ZFS pre-mutation snapshot failed: {snapshot['stderr']}"
            # Nothing was mutated, but BLD-execution_summary requires the snapshot record be carried into photos-25
            # either way, so the abort is auditable like any other run.
            write_json_artifact(execution_summary_path(ws), {
                "artifact_type": "execution_summary", "artifact_name": EXECUTION_SUMMARY_ARTIFACT,
                "schema_version": 1, "plan_id": plan.get("plan_id"), "status": "rejected",
                "snapshot": snapshot, "blockers": [reason], "failures": [], "fingerprint_mismatches": [],
                "run_metadata": {"execution_id": execution_id, "started_at": now_iso,
                                 "finished_at": now_iso, "jobs": jobs},
            })
            return {"status": "rejected", "plan_id": plan.get("plan_id"),
                    "stale": [reason], "snapshot": snapshot}

        jpath = journal_path(ws, plan["plan_id"])
        journal, media_after = {}, {}
        if os.path.exists(jpath):
            try:
                _j = json.load(open(jpath)) or {}
                journal, media_after = _j.get("operations", {}) or {}, _j.get("media_after", {}) or {}
            except Exception:
                journal, media_after = {}, {}
        accepted = self._accepted_mismatches(ws, plan["plan_id"])

        by_file = {}
        for dd in plan["destinations"].values():
            for op in dd["operations"]:
                by_file.setdefault(op["relative_path"], []).append(op)

        cache = GeotagCache(ws)
        try:
            # Capture-before-write (BLD-original_values_pinned): pin each file's own values — prep's record, NOT a
            # re-read — before geotag's first write to it, keyed by content fingerprint. A file already carrying
            # geotag's mark holds no original values any more, so it is not pinned.
            model = self.build_file_model()
            for f in model:
                fp = f.get("content_fingerprint")
                if fp and f.get("original_key") not in (None, fp):
                    # the pin follows the new value (BLD-original_values_follow_fingerprint)
                    cache.originals_rekey(f["original_key"], fp)
                if (fp and f["relative_path"] in by_file and not f.get("from_originals")
                        and geotag_marker(held_values(f).get("method")) is None):
                    cache.originals_pin(fp, f["relative_path"], f["own_values"], now_iso)

            results = []
            self.coordinator.start_phase("applying calibration", len(by_file))
            with concurrent.futures.ThreadPoolExecutor(max_workers=max(1, jobs)) as ex:
                futs = [ex.submit(self._apply_file_contained, rel, ops, journal, accepted)
                        for rel, ops in sorted(by_file.items())]
                try:
                    for fut in concurrent.futures.as_completed(futs):
                        r = fut.result()
                        results.append(r)
                        self.coordinator.increment_completed(1)
                        # Incremental confirmation journal (BLD-geotag_execution): persist each file's confirmed ops AS
                        # IT COMPLETES (in this main thread — workers never touch the journal), so a crash
                        # mid-run leaves a journal that lets the next run skip the already-applied files.
                        if r["applied"] or r.get("found"):
                            for oid in r["applied"] + (r.get("found") or []):
                                journal[oid] = "confirmed"
                            if r.get("after"):            # the photo as this run left it: finalize's baseline
                                a = r["after"]
                                media_after[a["relative_path"]] = {"size": a["size"], "mtime_ns": a["mtime_ns"]}
                            write_json_artifact(jpath, {"journal_version": 1, "plan_id": plan["plan_id"],
                                                        "operations": journal, "media_after": media_after,
                                                        "updated_at": now_iso})
                except KeyboardInterrupt:
                    # Ctrl-C: drop pending file writes and stop waiting instead of letting the `with`
                    # exit drain them (shutdown(wait=True)). Files already applied are confirmed in the
                    # journal above, so the next run resumes from the diff (RUL-geotag_execution_resumable). Re-raise
                    # to main().
                    ex.shutdown(wait=False, cancel_futures=True)
                    raise
            self.coordinator.finish_phase()

        finally:
            cache.close()
            from .photos_utils import PersistentMagickWorker
            PersistentMagickWorker.cleanup_all()       # close the per-thread magick workers (verify pass)

        # The journal was persisted incrementally as each file completed (above); nothing more to flush.
        summary = self._build_summary(plan, results, now_iso, execution_id, jobs,
                                      self._prior_mismatches(ws, plan["plan_id"]))
        summary["snapshot"] = snapshot                                   # the pre-mutation ZFS record (or None)
        write_json_artifact(execution_summary_path(ws), summary)
        return summary

    @staticmethod
    def _prior_mismatches(ws, plan_id):
        """The fingerprint mismatches the last execution of THIS plan reported, as written — the user's
        acceptances among them. Another plan's are not this plan's to act on."""
        try:
            with open(execution_summary_path(ws)) as f:
                prior = json.load(f)
        except (OSError, ValueError):
            return []
        if not isinstance(prior, dict) or prior.get("plan_id") != plan_id:
            return []
        return [m for m in (prior.get("fingerprint_mismatches") or []) if isinstance(m, dict)]

    @classmethod
    def _accepted_mismatches(cls, ws, plan_id):
        """{path: accepted fingerprint} for the mismatches of this plan the user accepted: an acceptance
        is of the content that was shown — the fingerprint the write left — never of whatever the photo
        holds later."""
        return {m.get("relative_path"): m.get("actual_fingerprint") for m in cls._prior_mismatches(ws, plan_id)
                if (m.get("user_decision") or {}).get("accept_fingerprint_change") is True
                and m.get("actual_fingerprint")}

    def _build_summary(self, plan, results, now_iso, execution_id, jobs, prior_mismatches=()):
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
            failures.extend({"operation_id": oid, "relative_path": r["relative_path"]} for oid in r["failed"])
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
            "failures": failures, "blockers": blockers, "fingerprint_mismatches": mismatches,
            "status": status,
            "run_metadata": {"execution_id": execution_id, "started_at": now_iso, "finished_at": now_iso, "jobs": jobs},
        }

    # --- Stage 11: finalize + archive (RUL-finalize_explicit, BLD-archive_manifest) ---

    def finalize_package(self, now_iso):
        """Stage 11 (BLD-archive_manifest): assemble the durable archival package — the photos-26 transformation log,
        an end-of-geotag DB snapshot, and a manifest. Non-destructive (only NEW files; never
        mutates an artifact, photo, or the live DB). Returns blockers (empty = package written)."""
        ws = self.workspace_root
        if not os.path.exists(executable_plan_path(ws)):
            return [f"No {EXECUTABLE_PLAN_ARTIFACT} — run `plan` then `execute` first."]
        if not os.path.exists(execution_summary_path(ws)):
            return [f"No {EXECUTION_SUMMARY_ARTIFACT} — `execute` the plan first."]
        plan = json.load(open(executable_plan_path(ws)))
        summary = json.load(open(execution_summary_path(ws)))
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
        gpx = GPXIndex(selected_gpx_root(), track_memo_db_path(ws), CONFIG["gpx_track_precedence"]).build(self.coordinator)
        stale = self.revalidate_plan(plan, gpx, with_handoff=False)
        if stale:
            return [f"The executed plan no longer holds ({'; '.join(stale)}) — re-run `geotag plan` and "
                    "`geotag execute` first."]

        changed = self._changed_since_execution(plan)
        if changed:
            return [f"{len(changed)} photo(s) in {folder_name('photos_by_dest')} are not as the execution left "
                    f"them ({_named(changed)}) — re-run `geotag plan` and `geotag execute` first (after "
                    "`prep plan` and `prep execute`, if geotag asks)."]

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
        try:
            with open(journal_path(ws, plan["plan_id"])) as f:
                after = (json.load(f) or {}).get("media_after") or {}
        except (OSError, ValueError):
            after = {}
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

    def _earlier_passes(self, current_plan_id):
        """[(plan, confirmed operation ids)] of every geotag pass executed before the current plan,
        oldest first: each superseded plan (kept as photos-24-...-NNN.json, numbered in the order they
        were set aside) whose journal shows it ran (BLD-geotag_log_steps)."""
        ws = self.workspace_root
        stem = os.path.splitext(EXECUTABLE_PLAN_ARTIFACT)[0]
        backups = sorted(glob.glob(os.path.join(ws, CONTROL_DIR, f"{stem}-[0-9][0-9][0-9]*.json")),
                         key=lambda p: int(os.path.basename(p)[len(stem) + 1:-len(".json")] or 0))
        out, seen = [], {current_plan_id}
        for p in backups:
            try:
                plan = json.load(open(p))
            except (OSError, ValueError):
                continue
            pid = plan.get("plan_id")
            jp = journal_path(ws, pid) if pid else None
            if pid in seen or not jp or not os.path.exists(jp):
                continue
            seen.add(pid)
            try:
                ops = (json.load(open(jp)) or {}).get("operations") or {}
            except (OSError, ValueError):
                continue
            out.append((plan, {oid for oid, st in ops.items() if st == "confirmed"}))
        return out

    def _passes_without_a_plan(self, current_plan_id):
        """Ids of geotag passes whose journal shows they ran but whose plan is neither current nor kept
        — their steps cannot be rebuilt (BLD-partial_log_marked). A geotag journal maps operation ids to their status;
        prep's lists its operations."""
        ws = self.workspace_root
        stem = os.path.splitext(EXECUTABLE_PLAN_ARTIFACT)[0]
        known = {current_plan_id}
        for p in glob.glob(os.path.join(ws, CONTROL_DIR, f"{stem}-[0-9][0-9][0-9]*.json")):
            try:
                known.add(json.load(open(p)).get("plan_id"))
            except (OSError, ValueError):
                continue
        missing = []
        for jp in sorted(glob.glob(os.path.join(ws, CONTROL_DIR, "journal-*.json"))):
            try:
                j = json.load(open(jp)) or {}
            except (OSError, ValueError):
                continue
            ops = j.get("operations")
            if isinstance(ops, dict) and any(st == "confirmed" for st in ops.values()) and j.get("plan_id") not in known:
                missing.append(j.get("plan_id"))
        return missing

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
    sub.add_parser("plan", help="Plan the geotag pass: produce photos-21/22/23/24 (no mutation).")
    sub.add_parser("execute", help="Apply photos-24 to the originals (metadata writes + renames).")
    sub.add_parser("finalize", help="Bundle the durable archival package (photos-26; non-destructive).")
    parser.set_defaults(_run=run, _parser=parser)


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
        prep_args = types.SimpleNamespace(command=cmd, jobs=getattr(args, "jobs", 4))
        try:
            photos_1_prep._run_locked(prep_args, workspace_root, reporter)   # under geotag's lock
        except SystemExit as e:
            if e.code not in (0, None):
                reporter.error(f"Auto prep {cmd} did not succeed (exit {e.code}). Resolve it and re-run "
                               "geotag — nothing was geotagged.")
                sys.exit(2)
        except Exception as e:
            reporter.error(f"Auto prep {cmd} failed: {e}. Resolve it and re-run geotag — nothing was geotagged.")
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


def run(args):
    workspace_root = os.getcwd()
    reporter = get_reporter()

    # Only prep creates the control directory (BLD-no_control_dir_stops): a folder without one is not a
    # workspace, and geotag stops there having created nothing — not even its lock file.
    if not os.path.isdir(control_dir(workspace_root)):
        reporter.error(f"Not an initialized workspace (no {CONTROL_DIR}/) — run prep first: "
                       "`photos-cartographer prep plan` then `photos-cartographer prep execute`. Nothing was created.")
        sys.exit(2)

    # Whole-run workspace lock (RUL-one_workspace_lock, RUL-lock_before_reading): one lock across every phase, taken
    # before anything in the workspace is read; fail-fast.
    run_lock = WorkspaceLock(workspace_root, create=False)
    if not run_lock.acquire():
        owner = run_lock.read_owner() or {}
        detail = f" (pid {owner.get('pid')}, since {owner.get('started_at')})" if owner else ""
        reporter.log(f"Workspace is locked by an in-progress run{detail}; try again when it finishes.")
        sys.exit(1)
    reporter.log(f"Lock acquired: {run_lock.lock_path}")
    try:
        # The seal is checked before anything else is read (BLD-phases_check_seal), the walk over every folder
        # for its device included: a sealed workspace goes straight to the preflight, whose first check refuses it.
        vol_err = None if is_sealed(workspace_root) else workspace_volume_error(workspace_root)   # RUL-workspace_one_filesystem
        if vol_err:
            reporter.error(vol_err)
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

            # Stages 2–4: build the in-memory model geotag reasons over.
            files = wf.build_file_model()
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
                reporter.log("\nNo geotag JSON was written.")
                emit_next_step(reporter, "paste the array(s) above into photos-00-config.json, then "
                                         "re-run `geotag plan`.")
                sys.exit(2)

            gpx = wf.load_gpx()      # disk-heavy: only after the in-memory checks above have passed
            if gpx.status == "missing":
                # Tracks that are configured but not there — a volume not mounted — are not "no tracks":
                # planning on would place by folder fallback what the tracks place, and drop every
                # answer given about them (RUL-missing_tracks_stop_geotag).
                reporter.error(f"\nGeotag cannot proceed: {gpx.warnings[0]}")
                reporter.log("\nNo geotag JSON was written.")
                emit_next_step(reporter, "make the tracks available (or set gpx_root to \"\" in "
                                         "photos-00-config.json to plan without tracks), then re-run `geotag plan`.")
                sys.exit(2)
            if gpx.status == "unreadable":
                # Track files there and not one read: planning on would place by folder fallback what the
                # tracks place, as if there were none (RUL-unreadable_tracks_stop_geotag).
                reporter.error(f"\nGeotag cannot proceed: not one of the {len(gpx.unreadable)} track file(s) under "
                               f"gpx_root {gpx.gpx_root} can be read:")
                for rel, why in gpx.unreadable:              # every one, each with why: the user's to repair
                    reporter.log(f"  - {rel}: {why}")
                for w in gpx.warnings:
                    if w.startswith("Linked folder under gpx_root"):
                        reporter.warn(f"  Warning: {w}")
                reporter.log("\nNo geotag JSON was written.")
                emit_next_step(reporter, "repair or replace the track files (or set gpx_root to \"\" in "
                                         "photos-00-config.json to plan without tracks), then re-run `geotag plan`.")
                sys.exit(2)
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
            if gpx.warnings:
                reporter.warn(f"GPX loading reported {len(gpx.warnings)} warning(s):")
                for w in gpx.warnings[:GPX_WARNINGS_SHOWN]:
                    reporter.warn(f"  - {w}")
                if len(gpx.warnings) > GPX_WARNINGS_SHOWN:
                    reporter.warn(f"  ... and {len(gpx.warnings) - GPX_WARNINGS_SHOWN} more.")

            # Stages 5–6: time decisions (photos-21). Regenerate from current inputs while
            # preserving authored decisions (RUL-decision_kept); a sanity-validation failure on a preserved value
            # is a hard blocker that leaves the user's artifact untouched to be fixed (RUL-invalid_decision_kept).
            tdp = time_decisions_path(workspace_root)
            prior, problem = _load_prior_decisions(tdp)
            if problem:
                _stop_on_unreadable_decisions(reporter, problem)
            artifact, td_blockers = wf.build_time_decisions(files, groups, prior, gpx)
            if td_blockers:
                reporter.error("\nGeotag cannot proceed: invalid value(s) in photos-21-time-decisions.json:")
                for b in td_blockers:
                    reporter.log(f"  - {b}")
                reporter.log("\nFix the field(s) and re-run; the artifact was left unchanged.")
                sys.exit(2)
            # Back up any prior hand-edited decision file before regenerating it (incremental -NNN),
            # so an authored decision is always recoverable.
            _, _td_bak = write_versioned_json(tdp, artifact)
            if _td_bak:
                reporter.log(f"  Previous {TIME_DECISIONS_ARTIFACT} backed up to {_td_bak}")
            for cr in wf.country_removals:
                reporter.warn(f"  Warning: {cr['destination']}: the country said there ({cr['country']}) was removed — "
                              f"{cr['because']}, which it lies in, is in {cr['country_there']}, and so is everything "
                              "inside it. A country is said once, at the top of its tree: that is how "
                              f"{folder_name('photos_by_dest')} must be laid out.")
            need_tz = sum(1 for d in artifact["destinations"].values()
                          if d["destination_timezone"]["requires_user_input"])
            need_off = sum(1 for d in artifact["destinations"].values()
                           for c in d["camera_group_time_decisions"].values() if c["requires_user_input"])
            if artifact["requires_user_input"]:
                reporter.log(f"Wrote {TIME_DECISIONS_ARTIFACT}: status={artifact['status']} "
                      f"({need_tz} timezone + {need_off} clock-offset decision(s) need input). "
                      "Edit the user_decision fields and re-run.", stream="stdout")
            else:
                reporter.log(f"Wrote {TIME_DECISIONS_ARTIFACT}: status=complete — all time decisions resolved.", stream="stdout")

                # Stage 7: time decisions are complete -> resolve UTC under the CURRENT offsets
                # (rows0). This drives drift detection (BLD-drift_validation) and, once 22 is clean, is recomputed
                # with the operator-validated offsets before anything downstream consumes it.
                rows0 = compute_resolved_utc(files, groups, artifact)
                # A photo whose local time its zone repeats or skips is never given one of its two readings
                # (RUL-ambiguous_local_time_never_guessed): geotag stops, naming each, before anything is built on it.
                amb = ambiguous_time_blockers(rows0)
                if amb:
                    reporter.error("\nGeotag cannot proceed: a photo's time falls at a daylight-saving change, "
                                   "where its destination's timezone gives it two readings:")
                    for b in amb:
                        reporter.log(f"  - {b}")
                    reporter.log(f"\nNo geotag JSON was written past {TIME_DECISIONS_ARTIFACT}.")
                    emit_next_step(reporter, "give each photo's time its offset (or move it out), then re-run "
                                             "`prep plan` + `prep execute` and `geotag plan`.")
                    sys.exit(2)

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
                    gps_artifact, gps_blockers = wf.build_gps_decisions(files, rows, gpx, prior_gps, fp)
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
                                     "preserve_native_gps", "blocked")}
                    reporter.log(f"Wrote {GPS_DECISIONS_ARTIFACT}: status={gps_artifact['status']} "
                          f"({tot['preserve_native_gps']} native, {tot['automatic_gpx_interpolation']} interp, "
                          f"{tot['automatic_gpx_extrapolation']} extrap, {tot['blocked']} blocked).", stream="stdout")
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
            if not os.path.exists(executable_plan_path(workspace_root)):
                reporter.log(f"No {EXECUTABLE_PLAN_ARTIFACT} — run `plan` first.")
                emit_next_step(reporter, "`geotag plan` first to build the executable plan.")
                sys.exit(2)
            now_iso = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
            execution_id = sha256_text(f"{now_iso}|{os.getpid()}")[:12]
            jobs = args.jobs or CONFIG.get("jobs") or 4
            summary = wf.execute_plan(jobs, now_iso, execution_id)
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
                reporter.log(f"Review {EXECUTION_SUMMARY_ARTIFACT} and re-run `execute` once resolved.")
                emit_next_step(reporter, f"review {EXECUTION_SUMMARY_ARTIFACT}, resolve the issues, then "
                                         "re-run `geotag execute`.")
                sys.exit(3)
            emit_next_step(reporter, "`geotag finalize` to seal the geotag phase.")

        elif args.command == "finalize":
            wf = GeotagWorkflow(workspace_root)
            blockers, warnings, info = wf.preflight(for_execute=True)
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
                reporter.error("\nCannot finalize — geotag has not ended successfully:")
                for b in fin_blockers:
                    reporter.log(f"  - {b}")
                emit_next_step(reporter, "run `geotag execute` to a successful finish first, then "
                                         "`geotag finalize`.")
                sys.exit(2)
            for w in getattr(wf, "finalize_warnings", []):
                reporter.warn(f"  partial record: {w}")
            with open(executable_plan_path(workspace_root)) as pf:
                placed = (json.load(pf) or {}).get("placement") or {}
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
    finally:
        run_lock.release()


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
