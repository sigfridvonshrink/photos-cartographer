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
(§7/§13), the in-memory by-dest model (Stage 2), the GPX index (§15), camera-group recognition
(§16), the time/drift/GPS-decision artifacts `photos-21`/`photos-22`/`photos-23` (§20/§22a/§25),
resolved-UTC computation (§22), the executable plan `photos-24` (§28), `execute` of that plan into
`photos-25` (§29), and `finalize` of the archival package `photos-26` + DB snapshot + manifest (§31).
Subcommands: `plan`, `execute`, `finalize`.

The script sits beside `photos_utils.py` and imports the shared infrastructure from it.
"""
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

TIME_DECISIONS_ARTIFACT = "photos-21-time-decisions.json"
DRIFT_VALIDATION_ARTIFACT = "photos-22-gps-drift-validation.json"
GPS_DECISIONS_ARTIFACT = "photos-23-gps-decisions.json"
EXECUTABLE_PLAN_ARTIFACT = "photos-24-executable-plan.json"
EXECUTION_SUMMARY_ARTIFACT = "photos-25-execution-summary.json"
COMPLETE_LOG_ARTIFACT = "photos-26-complete-log.json"
GEOTAG_DB_SNAPSHOT = "photos-26-geotag-ingest.db"
ARCHIVE_MANIFEST_ARTIFACT = "photos-26-archive-manifest.json"



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


def archive_manifest_path(ws):
    return os.path.join(ws, CONTROL_DIR, ARCHIVE_MANIFEST_ARTIFACT)


# ============================================================================
# Stage 3 — GPX index (geotag spec §15). GPX is geotag-only — prep is GPX-unaware
# (shared contract §8.2). Stdlib xml.etree only; no new dependency.
# ============================================================================

class GeotagCache:
    """Geotag's own region of the shared photos-00-ingest.db (shared contract §13.4) — the
    resolved-UTC cache here, the manual-GPS pre-state ledger later. Disjoint from prep's tables."""

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
            "CREATE TABLE IF NOT EXISTS manual_gps_ledger ("
            "content_fingerprint TEXT PRIMARY KEY, relative_path TEXT, pre_state TEXT, captured_at TEXT)")
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

    # --- manual-GPS pre-state ledger (§24.1): reversibility for manual GPS only ----------
    def ledger_get(self, fp):
        cur = self.conn.execute(
            "SELECT content_fingerprint, relative_path, pre_state, captured_at "
            "FROM manual_gps_ledger WHERE content_fingerprint=?", (fp,))
        row = cur.fetchone()
        return None if row is None else {"content_fingerprint": row[0], "relative_path": row[1],
                                         "pre_state": json.loads(row[2]), "captured_at": row[3]}

    def ledger_pin(self, fp, rel, pre_state, captured_at):
        """Pin a file's pre-override GPS ONCE — never overwritten (§24.1.1/3), so a later changed
        manual value still reverts to the true original."""
        with self.conn:
            self.conn.execute(
                "INSERT OR IGNORE INTO manual_gps_ledger "
                "(content_fingerprint, relative_path, pre_state, captured_at) VALUES (?,?,?,?)",
                (fp, rel, json.dumps(pre_state, sort_keys=True), captured_at))

    def ledger_consume(self, fp):
        with self.conn:
            self.conn.execute("DELETE FROM manual_gps_ledger WHERE content_fingerprint=?", (fp,))

    def ledger_all(self):
        cur = self.conn.execute(
            "SELECT content_fingerprint, relative_path, pre_state, captured_at "
            "FROM manual_gps_ledger ORDER BY content_fingerprint")
        return [{"content_fingerprint": r[0], "relative_path": r[1],
                 "pre_state": json.loads(r[2]), "captured_at": r[3]} for r in cur.fetchall()]

    def close(self):
        self.conn.close()


# ============================================================================
# GeotagWorkflow — the geotag orchestrator (Stages 1–11), the I/O + decision-
# artifact layer. The pure GPS-placement helpers it calls (place_gps,
# _interp/_extrapolate, classify_gps) now live in _geotag_calc.py (geotag §23/§25).
# ============================================================================

class GeotagWorkflow:
    """Stages 1–11: validate the workspace, build the model, produce photos-21/22/23 decision artifacts,
    compute resolved UTC, assemble photos-24-executable-plan.json (when decisions are complete),
    execute it into photos-25 (§29), and finalize the archival package photos-26 (§31)."""

    def __init__(self, workspace_root: str):
        self.workspace_root = workspace_root
        self.handoff = None
        self._gpx_fingerprint = None
        # Live progress for the long phases (TTY: in-place bar; piped: a line every ~10 s; tests: quiet).
        self.coordinator = ProgressCoordinator()

    # --- preflight (geotag spec §7 / §13) -------------------------------

    def preflight(self, for_execute=False):
        """Return (blockers, warnings, info). A non-empty `blockers` means geotag cannot
        proceed. Textual only — writes no JSON. The lifecycle guards (sealed / uninitialized /
        loose-root-file) and the §7.1 development-started gate hard-stop early; the remaining by-dest
        scope and re-prep gates are collected so the rest are reported at once. `for_execute` keeps the
        lifecycle guards, the §7.1 development gate, and the config/handoff load, but SKIPS the
        planning-phase scope and re-prep gates: execution validates against the plan's own dependency
        fingerprints + per-op preconditions, and the by-dest filenames it renames would otherwise trip
        the re-prep gate (§13.1 is a planning concern). The §7.1 gate is the exception — it is
        re-checked at execute/finalize too (a breakout begun after planning moves no planned file)."""
        blockers, warnings, info = [], [], {}
        ws = self.workspace_root

        # 1. Lifecycle guards (shared contract §13.7), evaluated under the run lock by main().
        if is_sealed(ws):
            blockers.append("Workspace is SEALED (already merged): geotag will not run. "
                            "Nothing was touched — move new media into a fresh workspace.")
            if self._root_files() or self._entries(folder_name('sources')):
                warnings.append("A likely new dump is present (files at the root or in "
                                f"{folder_name('sources')}/). A sealed workspace is final; move it "
                                "into a fresh workspace by hand.")
            return blockers, warnings, info
        if not os.path.exists(guard_path(ws)):
            blockers.append("Not an initialized workspace (no photos-00-workspace-guard) — "
                            "run prep first: `photos-cartographer prep plan` then `photos-cartographer prep execute`.")
            return blockers, warnings, info
        # A symlink at the workspace root is barred outright (§13) and never followed — including a
        # dangling link (neither file nor dir) or one named like a managed folder (which os.path.isdir
        # would otherwise resolve through). Checked before the structural/loose-entry guards below.
        root_syms = self._root_symlinks()
        if root_syms:
            blockers.append(f"Forbidden symlink at the workspace root: {root_syms[0]}. Symlinks are "
                            "never followed; remove it before geotagging.")
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
        loose = self._root_files()
        if loose:
            blockers.append(f"Loose file at the workspace root (dumps belong in "
                            f"{folder_name('sources')}/): {loose[0]}. The base must hold only folders.")
            return blockers, warnings, info
        # A misplaced dump drops folders at the root too, not just files. The base must hold ONLY the
        # managed 0-6 folders (+ dot/control dirs); any other root folder — including a directory
        # symlink — is a misplaced dump, blocked exactly like a loose file.
        loose_dirs = self._root_nonmanaged_dirs()
        if loose_dirs:
            blockers.append(f"Misplaced folder at the workspace root (dumps belong in "
                            f"{folder_name('sources')}/): {loose_dirs[0]}. The base must hold only "
                            "the managed folders.")
            return blockers, warnings, info

        # 2. Config (read-only) + handoff — both must exist; geotag never seeds/writes config.
        cfg_p = config_path(ws)
        if not os.path.exists(cfg_p):
            blockers.append("Workspace config photos-00-config.json is missing — run prep first: `photos-cartographer prep plan` then `photos-cartographer prep execute`.")
            return blockers, warnings, info
        try:
            with open(cfg_p) as f:
                cfg = json.load(f)
            validate_config(cfg)            # sanity-validate human-authored config (§9.2)
        except ValueError as e:
            blockers.append(f"Invalid workspace config: {e}")
            return blockers, warnings, info
        except Exception as e:
            blockers.append(f"Workspace config could not be read: {e}")
            return blockers, warnings, info
        CONFIG.update(cfg)                  # adopt the seeded config as authoritative for this run

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

        # External-tool preflight: geotag reads existing EXIF GPS/time through exiftool and WRITES the
        # corrected tags through it at execute/finalize. There is no graceful fallback for the write, so
        # a missing exiftool is a hard blocker (checked for plan AND execute, before any heavy work).
        from .photos_utils import missing_tools
        if missing_tools(["exiftool"]):
            blockers.append("exiftool not found on PATH — geotag reads and writes EXIF GPS/time "
                            "through it. Install exiftool and re-run.")
            return blockers, warnings, info

        by_dest = folder_name('photos_by_dest')
        # §7.1 development-started guard — PRESENCE-STRICT and re-checked at execute/finalize too, not
        # just planning: the mere existence of a jpg/tif distribution subfolder under by-dest (even an
        # empty one) hard-stops. A breakout begun between `plan` and `execute` moves no planned file, so
        # the per-op media preconditions (§29) would not catch it; this existence check is what does.
        dev_found, nonphoto = self._scan_by_dest(by_dest)
        if dev_found:
            names = ", ".join(sorted(set(CONFIG.get("destination_distribution_subfolders") or [])))
            blockers.append(f"Development has already started — a distribution subfolder ({names}) "
                            f"exists under {by_dest}: {dev_found[0]}. Time/GPS calibration must run "
                            "BEFORE development; roll the breakout back first.")
            return blockers, warnings, info

        if for_execute:                 # execution skips the planning-phase scope/re-prep gates
            return blockers, warnings, info

        sources = folder_name('sources')
        by_date = folder_name('photos_by_date')

        # 3. Scope gates.
        if self._entries(sources):
            blockers.append(f"{sources}/ is not empty — prep leaves it empty after every run; an "
                            "unprocessed dump is waiting. Re-run prep to process it: `photos-cartographer prep plan` then `photos-cartographer prep execute`.")

        stray = [rel for rel, mc in self._scan_media(by_date) if mc in ("image", "raw")]
        if stray:
            blockers.append(f"{by_date}/ still contains {len(stray)} photo(s) — finish moving them "
                            f"into {by_dest}/ before geotagging (e.g. {stray[0]}).")

        if nonphoto:
            videos = [p for p, mc in nonphoto if mc == "video"]
            others = [p for p, mc in nonphoto if mc != "video"]
            parts = []
            if others:
                parts.append(f"{len(others)} non-media file(s) (e.g. {others[0]})")
            if videos:
                parts.append(f"{len(videos)} video(s) (e.g. {videos[0]} — belongs in "
                             f"{folder_name('videos_by_date')}/)")
            blockers.append(f"{by_dest}/ must contain only photos. Found " + " and ".join(parts) +
                            ". Remove or relocate them before geotagging.")

        # 4. Re-prep-after-move gate (§13.1): a prep run must follow the latest by-date→by-dest move.
        self._check_reprep_gate(handoff, by_dest, by_date, blockers)

        info["by_dest_photos"] = sum(1 for _, mc in self._scan_media(by_dest) if mc in ("image", "raw"))
        return blockers, warnings, info

    # --- filesystem helpers --------------------------------------------------

    def _root_files(self):
        ws = self.workspace_root
        return sorted(f for f in os.listdir(ws) if os.path.isfile(os.path.join(ws, f)))

    def _root_nonmanaged_dirs(self):
        """Root entries that are directories (a directory symlink counts) but are neither one of the
        managed 0-6 folders nor a dot/control dir — i.e. misplaced dump folders."""
        ws = self.workspace_root
        managed = {folder_name(r) for r in FOLDER_ROLES}
        return sorted(f for f in os.listdir(ws)
                      if not f.startswith('.') and f not in managed
                      and os.path.isdir(os.path.join(ws, f)))

    def _entries(self, rel_folder):
        d = os.path.join(self.workspace_root, rel_folder)
        return sorted(os.listdir(d)) if os.path.isdir(d) else []

    def _root_symlinks(self):
        """Any entry at the workspace root that is a symlink (file, directory, or dangling) — barred
        outright, never followed (§13). Dot-named ones included: the only legitimate dot entries
        (.photos-ingest*) are real directories, never symlinks, so a dot-named symlink is forbidden too."""
        ws = self.workspace_root
        return sorted(f for f in os.listdir(ws)
                      if os.path.islink(os.path.join(ws, f)))

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
            blockers.append(
                f"{by_dest} contains photos prep has not yet recorded (the handoff predates your most "
                f"recent move from {by_date} into {by_dest}; e.g. {ex}). Re-run prep to record the move "
                "and refresh the handoff: run `photos-cartographer prep plan` then "
                "`photos-cartographer prep execute` (the move is recognized stat-only — no re-fingerprint, "
                "no re-read). Then geotag can proceed.")

    # --- Stage 2: in-memory by-dest file model (geotag spec §14) --------

    def build_file_model(self):
        """One object per by-dest photo, built from the handoff's records (+ the EXIF prep already
        extracted into metadata_status.parsed_json). Geotag never re-reads the file — a stale
        handoff was already blocked (§13.1)."""
        by_dest = folder_name('photos_by_dest')
        files = []
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
            ch = rec.get("content_hash")
            try:
                fp = json.loads(ch).get("value") if ch else None
            except Exception:
                fp = None
            rel = rec.get("relative_path")
            files.append({
                "relative_path": rel,
                "destination": os.path.dirname(rel),         # immediate containing folder (§10.1)
                "size": rec.get("size"),
                "mtime_ns": rec.get("mtime_ns"),
                "content_fingerprint": fp,
                "media_class": rec.get("media_class"),
                "camera_group_key": md.get("camera_group_key") or parsed.get("camera_group_key") or "unknown",
                "camera_identity": {k: parsed.get(k) for k in CAMERA_IDENTITY_FIELDS if parsed.get(k) is not None},
                "source_naive_time": parsed.get("selected_source_naive_timestamp"),
                "source_time_tag": parsed.get("selected_source_timestamp_tag"),
                "raw_times": {k: parsed.get(k) for k in
                              ("DateTimeOriginal", "CreateDate", "ModifyDate",
                               "OffsetTimeOriginal", "OffsetTime", "TimeZone") if parsed.get(k) is not None},
                "has_timestamp": bool(md.get("has_timestamp") if md.get("has_timestamp") is not None
                                      else parsed.get("has_timestamp")),
                "native_gps": ({"lat": parsed.get("GPSLatitude"), "lon": parsed.get("GPSLongitude"),
                                "processing_method": parsed.get("GPSProcessingMethod")}
                               if (md.get("has_native_gps") or parsed.get("has_native_gps")) else None),
                "has_native_gps": bool(md.get("has_native_gps") if md.get("has_native_gps") is not None
                                       else parsed.get("has_native_gps")),
                "metadata_field_set_version": md.get("field_set_version", FIELD_SET_VERSION),
                "folder_class": rec.get("folder_class"),
                "planned_filename": None,                    # set during the rename lookahead (Phase 6)
            })
        files.sort(key=lambda f: f["relative_path"])
        return files

    # --- Stage 3: GPX index (geotag spec §15) ---------------------------

    def load_gpx(self):
        idx = GPXIndex(selected_gpx_root()).build(self.coordinator)
        self._gpx_fingerprint = idx.fingerprint
        return idx

    # --- Stage 4: camera-group recognition + classification (§16) ------------

    def recognize_camera_groups(self, files):
        """Group the file objects by camera_group_key; classify each via config device_groups.
        Returns (groups_by_key, unknown_keys). A camera_group_key listed in `phones` is a
        smartphone (solved per-file); in `fixed_clock_cameras` a camera (needs a per-(group,
        destination) offset); otherwise it is unknown and must be classified before geotag."""
        dg = (CONFIG.get("camera_time_and_timezone_policy") or {}).get("device_groups") or {}
        phones = set(dg.get("phones") or [])
        fixed = set(dg.get("fixed_clock_cameras") or [])
        groups = {}
        for f in files:
            key = f["camera_group_key"]
            g = groups.get(key)
            if g is None:
                cls = "smartphone" if key in phones else ("camera" if key in fixed else "unknown")
                g = groups[key] = {
                    "camera_group_key": key, "camera_group_class": cls,
                    "contributing_identity_fields": dict(f["camera_identity"]),
                    "file_count": 0, "destinations": set(),
                    "has_native_gps": 0, "missing_timestamp": 0, "timestamps": [],
                }
            g["file_count"] += 1
            g["destinations"].add(f["destination"])
            if f["has_native_gps"]:
                g["has_native_gps"] += 1
            if not f["has_timestamp"]:
                g["missing_timestamp"] += 1
            elif f["source_naive_time"]:
                g["timestamps"].append(f["source_naive_time"])
        for g in groups.values():
            ts = sorted(g.pop("timestamps"))
            g["destinations"] = sorted(g["destinations"])
            g["earliest_source_time"] = ts[0] if ts else None
            g["latest_source_time"] = ts[-1] if ts else None
        unknown = sorted(k for k, g in groups.items() if g["camera_group_class"] == "unknown")
        return groups, unknown

    # --- Stages 5–6: time decisions (photos-21, §17–§21) ---------------------

    def build_time_decisions(self, files, groups, prior, gpx):
        """Build/regenerate the photos-21 content: per-destination civil timezone (§18) + per-
        (camera group, destination) clock-offset cells (§10.2), through the decision-field /
        auto-resolution / rerun-preservation engine (§9). The offset cell's proposal is the §19
        GPX self-anchor when one can be inferred (else manual-required). Returns (artifact,
        blockers); blockers come from sanity-validating preserved authored values (§9.2) and mean
        "do not overwrite — fix first"."""
        blockers = []
        prior_dests = ((prior or {}).get("destinations")) or {}
        by_dest = {}
        for f in files:
            by_dest.setdefault(f["destination"], []).append(f)

        destinations = {}
        # Process destinations PARENT-FIRST so an ancestor's effective TIMEZONE is known before a child
        # inherits it (§18). `eff_tz` maps (destination, "tz") -> resolved effective timezone. Clock
        # offsets do NOT inherit across destinations (§10.2): each (group, date) bucket proposes its own.
        eff_tz = {}
        ordered, containers = _expand_destinations(by_dest)
        self.coordinator.start_phase("calibrating clock offsets", len(ordered))
        for dest in ordered:
            self.coordinator.set_detail(_dest_label(dest))   # name the destination so heavy ones are visible
            is_container = dest in containers       # a file-less folder: holds a timezone/fallback, no offsets
            prior_d = prior_dests.get(dest, {})
            inherited_tz = _nearest_ancestor(dest, eff_tz, "tz")        # confirmable basis if no default
            tz_block = self._timezone_decision(dest, prior_d.get("destination_timezone") or {},
                                               blockers, inherited_tz, file_less=is_container)
            eff_tz[(dest, "tz")] = tz_block["effective_iana_timezone"] or None   # what children inherit
            tz = tz_block["effective_iana_timezone"] or None
            prior_cells = prior_d.get("camera_group_time_decisions") or {}
            cells, present = {}, []
            # Containers hold no media → no offset cells. A real destination gets one offset cell per
            # camera group, SPLIT per naive calendar date when the group spans >1 day there (§10.2): the
            # camera is set to local time each morning, so the offset is constant only within a day. The
            # bucket key is the bare group for a single day, else `<group>@<YYYY-MM-DD>`.
            for group in (sorted({f["camera_group_key"] for f in by_dest[dest]}) if not is_container else []):
                present.append(group)
                g = groups.get(group) or {}
                if g.get("camera_group_class") != "camera":
                    continue                       # smartphones are solved per-file; no offset cell
                gframes = [f for f in by_dest[dest] if f["camera_group_key"] == group]
                dates = sorted({d for f in gframes if (d := _naive_date(f.get("source_naive_time")))})
                for date in (dates if len(dates) > 1 else [None]):
                    sel = gframes if date is None else [f for f in gframes if _naive_date(f.get("source_naive_time")) == date]
                    anchor_frames = [f for f in sel if f.get("native_gps")]
                    rep_naive = min((f.get("source_naive_time") for f in sel
                                     if _parse_camera_naive(f.get("source_naive_time"))), default=None)
                    bucket = group if date is None else f"{group}@{date}"
                    cells[bucket] = self._offset_cell(dest, group, g, prior_cells.get(bucket) or {},
                                                      anchor_frames, gpx, blockers, tz=tz, rep_naive=rep_naive, date=date)
            destinations[dest] = {
                "destination_path": dest,
                "destination_timezone": tz_block,
                "camera_groups_present": present,
                "camera_group_time_decisions": cells,
            }
            if is_container:
                destinations[dest]["file_less"] = True
            self.coordinator.increment_completed(1)
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
        }
        if not requires:
            artifact["decision_mode"] = "no_op_or_auto_resolved"
        return artifact, blockers

    def _timezone_decision(self, dest, prior_tz, blockers, inherited=None, file_less=False):
        # Proposal precedence (§18): the nearest RESOLVED ancestor destination's timezone (a more
        # specific signal than the generic global default — e.g. a Japan/Kyoto leaf inheriting Japan's
        # Asia/Tokyo over a Europe/Brussels home default) wins; else the config default; else none.
        # Destinations are geographically NESTED — a child sits inside its parent, so it can scarcely
        # cross a timezone boundary the parent didn't — so a timezone proposal (inherited or config
        # default) auto-resolves without per-destination confirmation, staying overridable by a manual
        # entry. Only a destination with NO proposal at all (no ancestor, no default) blocks.
        default = (CONFIG.get("camera_time_and_timezone_policy") or {}).get("default_folder_timezone") or None
        if inherited is not None:
            anc_path, anc_tz = inherited
            proposed, source, confidence, inherited_from = anc_tz, "inherited", "review_required", anc_path
        elif default:
            proposed, source, confidence, inherited_from = default, "config_default", "high", None
        else:
            proposed, source, confidence, inherited_from = None, "none", "none", None
        ud = prior_tz.get("user_decision") or {}
        manual = ud.get("manual_iana_timezone", "") or ""
        accept = bool(ud.get("accept_proposed_timezone", False))
        effective, stale = "", False
        if manual:
            if _valid_iana(manual):
                effective = manual
            else:
                blockers.append(f"{dest}: destination_timezone.user_decision.manual_iana_timezone "
                                f"{manual!r} is not a valid IANA timezone.")
        elif accept:
            if proposed:
                effective = proposed
            else:
                stale = True                       # accepted a proposal that no longer exists
        # Any destination with a proposal auto-adopts it (and re-propagates it downward) without
        # demanding confirmation — inherited or config-default, container or real — because the nested
        # geography makes the parent's timezone the right default for the child. A manual entry still
        # overrides. (File-less containers always took this path; real destinations now do too.)
        auto = effective == "" and not manual and bool(proposed)
        if auto:
            effective = proposed
        block = {
            "proposed_iana_timezone": proposed,
            "proposal_source": source,
            "proposal_confidence": confidence,
            "user_decision": {"manual_iana_timezone": manual, "accept_proposed_timezone": accept},
            "effective_iana_timezone": effective,
            "requires_user_input": effective == "" and not file_less,   # a container never blocks
            "stale_user_decision": stale,
        }
        if auto:
            block["decision_mode"] = "auto_resolved"
        if inherited_from:
            block["inherited_from"] = inherited_from
        return block

    def _offset_cell(self, dest, key, g, prior_cell, frames, gpx, blockers, tz=None, rep_naive=None, date=None):
        # One (camera group, destination[, date]) clock-offset bucket. Proposal precedence (§10.2 rule 4):
        # GPX self-anchor → timezone-derived (camera assumed on local time; DST-aware, §19.4) → manual.
        # Clock offsets do not inherit across destinations. `date` (YYYY-MM-DD) is set when the group
        # spans >1 naive day here; the bucket key is `<key>@<date>` and is the blocker location.
        loc = key if date is None else f"{key}@{date}"
        proposal = infer_anchor_proposal(frames, gpx, CONFIG)
        if proposal is None and (tzr := _timezone_naive_offset(rep_naive, tz)) is not None:
            off_s, real_iso = tzr
            proposal = {"proposal_source": "timezone_naive", "proposed_offset_seconds": off_s,
                        "proposed_real_utc": real_iso, "proposed_from_timezone": tz,
                        "confidence": "review_required", "rank": "timezone_derived"}
        elif proposal is None:
            proposal = {"proposal_source": "manual_required"}
        is_gpx = proposal.get("proposal_source") == "gpx_self_anchor"
        has_offset = "proposed_offset_seconds" in proposal
        conflicting = proposal.get("conflicting_count", 0) > 0
        policy = CONFIG.get("camera_time_and_timezone_policy") or {}

        ud = prior_cell.get("user_decision") or {}
        accept = bool(ud.get("accept_proposal", False))
        manual_off = ud.get("manual_offset_seconds", "")
        manual_utc = ud.get("manual_real_utc", "") or ""
        effective, stale, decision_mode = "", False, None

        if manual_off != "" and manual_off is not None:
            if _valid_offset(manual_off):
                effective = {"offset_seconds": int(manual_off), "source": "manual"}
            else:
                blockers.append(f"{dest}: camera_group_time_decisions[{loc}].user_decision."
                                "manual_offset_seconds must be a number within +/-86400.")
        elif manual_utc:
            dt = _parse_utc(manual_utc)
            if dt is None:
                blockers.append(f"{dest}: camera_group_time_decisions[{loc}].user_decision."
                                f"manual_real_utc {manual_utc!r} is not a valid UTC datetime.")
            elif is_gpx and proposal["anchors"]:
                # derive the offset from the recommended anchor's camera naive time
                # (guaranteed parseable — match_frame_to_gpx rejects frames with an unparseable time)
                naive = _parse_camera_naive(proposal["anchors"][0]["camera_source_naive_time"])
                effective = {"offset_seconds": round((dt.replace(tzinfo=None) - naive).total_seconds()),
                             "source": "manual_real_utc"}
        elif accept:
            if has_offset:                         # accept a GPX self-anchor or a timezone-derived proposal
                effective = {"offset_seconds": proposal["proposed_offset_seconds"],
                             "source": "gpx_anchor_accepted" if is_gpx else "timezone_accepted"}
            else:
                stale = True                       # accepted a proposal that does not exist
        elif is_gpx and not conflicting:
            # auto-resolution under the config flags (§9.1) — GPX-self-anchor only; a timezone-derived
            # proposal is confirmable, never auto-applied (the local-clock assumption can be wrong).
            n = proposal["anchor_count"]
            if (n >= 2 and policy.get("multi_anchor_auto_apply", True)) or \
               (n == 1 and policy.get("single_anchor_auto_apply", False)):
                effective = {"offset_seconds": proposal["proposed_offset_seconds"], "source": "gpx_anchor_auto"}
                decision_mode = "auto_resolved"

        cell = {
            "camera_group": key,
            "camera_group_class": g.get("camera_group_class", "camera"),
            "proposal": proposal,
            "user_decision": {"accept_proposal": accept,
                              "manual_offset_seconds": manual_off if manual_off is not None else "",
                              "manual_real_utc": manual_utc},
            "effective_time_anchor": effective,
            "requires_user_input": effective == "",
            "stale_user_decision": stale,
        }
        if date is not None:
            cell["date"] = date                    # this bucket covers only that naive calendar date
        if decision_mode:
            cell["decision_mode"] = decision_mode
        return cell

    def _handoff_dependency(self, ws):
        """The handoff dependency is its deterministic CONTENT fingerprint (prep §16.2), not the
        volatile file bytes — so a no-op prep re-run (which only refreshes run_metadata) does not
        restale this plan. Falls back to a plain byte-hash dependency for a legacy handoff with no
        content_fingerprint."""
        with open(handoff_path(ws)) as f:
            ho = json.load(f)
        if "content_fingerprint" in ho:
            return {"dependency_type": "handoff_content", "artifact_name": "photos-11-handoff.json",
                    "artifact_path": os.path.relpath(handoff_path(ws), ws),
                    "content_fingerprint": handoff_content_fingerprint(ho)}
        return json_dependency("photos-11-handoff.json", ws, handoff_path(ws))   # legacy

    @staticmethod
    def _verify_handoff_dependency(dep, ws):
        if dep.get("dependency_type") != "handoff_content":
            return verify_json_dependency(dep, ws)                                # legacy byte-hash
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

    # --- Stage 7a: GPS-drift validation (photos-22, §22a) -------------------
    # The highest-danger gap: a (group, dest, date) bucket whose clock offset is manual/timezone-
    # derived (NOT a GPX self-anchor) and that has NO native-GPS anchor is placed in phase 23 purely
    # from its resolved UTC — a wrong offset silently lands the whole batch at the wrong track point.
    # 22 flags every such bucket that GPX *could* validate, blocks until the operator explicitly
    # confirms each (a zero-scrub "offset was right" must be actively confirmed, never implied), and
    # carries the corrected/validated offset that compute_resolved_utc then re-consumes (§22a).

    _DRIFT_TRIGGER_SOURCES = ("timezone_accepted", "manual", "manual_real_utc")

    def build_drift_validation(self, files, time_artifact, rows0, gpx, prior):
        """Build/regenerate photos-22 from the COMPLETE photos-21 + the resolved UTC under the
        current offsets (`rows0`). One review item per at-risk bucket (manual/tz-derived offset, no
        native-GPS anchor, and GPX coverage over its plausible time window). Authored confirmations
        are preserved across reruns; a confirmation whose bucket no longer triggers is stale-flagged.
        Returns (artifact, blockers); a bad authored value is a blocker (leave the artifact as-is)."""
        blockers = []
        cfg = CONFIG
        window = cfg.get("gpx_anchor_max_clock_error_seconds")
        by_dest_group = {}
        for f in files:
            by_dest_group.setdefault((f["destination"], f["camera_group_key"]), []).append(f)
        resolved_by_path = {r["relative_path"]: r["resolved_utc"] for r in rows0
                            if r["resolved_utc_status"] == "valid"}
        prior_dests = ((prior or {}).get("destinations")) or {}
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
                if any(f.get("native_gps") and match_frame_to_gpx(f, gpx, cfg) for f in frames):
                    continue                                  # has a native-GPS anchor -> reliably placeable
                times = [t for f in frames if (t := _parse_utc(resolved_by_path.get(f["relative_path"])))]
                if not times:
                    continue                                  # nothing resolves -> not a drift case
                lo, hi = min(times), max(times)
                seg = [p for p in gpx.points
                       if (window is None or (lo - timedelta(seconds=window)) <= p.time_utc
                           <= (hi + timedelta(seconds=window)))]
                if not seg:
                    continue                                  # no GPX coverage -> phase 23 fallback/lost
                cells[bucket] = self._drift_cell(dest, bucket, cell, seg, frames,
                                                 prior_cells.get(bucket) or {}, blockers, date=date)
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

    def _drift_cell(self, dest, bucket, time_cell, track_segment, frames, prior_cell, blockers, date=None):
        """One drift-validation bucket: the current offset, the covering GPX track + the bucket's
        frames (evidence the editor scrubs a photo along), the operator's explicit confirmation, and
        the validated/corrected offset compute_resolved_utc consumes. requires_user_input until
        `confirmed` is actively set (a zero-scrub counts only when the operator confirms it — inaction
        never satisfies the gate, §22a)."""
        eff = time_cell.get("effective_time_anchor") or {}
        current = eff.get("offset_seconds")
        loc = bucket
        prior_ud = prior_cell.get("user_decision") or {}
        confirmed = bool(prior_ud.get("confirmed", False))
        corrected = prior_ud.get("corrected_offset_seconds", "")
        effective = ""
        if confirmed:
            if corrected == "" or corrected is None:
                effective = {"offset_seconds": current, "source": "gps_drift_validated"}   # zero scrub
            elif _valid_offset(corrected):
                effective = {"offset_seconds": int(corrected), "source": "gps_drift_validated"}
            else:
                blockers.append(f"{dest}: drift_decisions[{loc}].user_decision.corrected_offset_seconds "
                                "must be empty or a number within +/-86400.")
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
            },
            "user_decision": {"confirmed": confirmed,
                              "corrected_offset_seconds": corrected if corrected is not None else ""},
            "effective_drift_offset": effective,
            "requires_user_input": effective == "",
            "stale_user_decision": False,
        }
        if date is not None:
            cell["date"] = date
        return cell

    def _drift_depends_on(self):
        policy = json.dumps((CONFIG.get("camera_time_and_timezone_policy") or {}), sort_keys=True)
        return {
            "photos_21_sha256": sha256_file(time_decisions_path(self.workspace_root)),
            "gpx_fingerprint": self._gpx_fingerprint,
            "camera_time_policy_fingerprint": sha256_text(policy),
            "camera_group_key_version": CAMERA_GROUP_KEY_VERSION,
        }

    # --- Stage 8: GPS decisions (photos-23, §23/§25) -------------------------

    _SUMMARY_KEYS = ("files_total", "preserve_native_gps", "automatic_gpx_interpolation",
                     "automatic_gpx_extrapolation", "automatic_folder_fallback", "manual_locked",
                     "manual_review_required", "blocked", "no_gps_change_needed")

    def build_gps_decisions(self, files, resolved_rows, gpx, prior, resolved_fp):
        """Build/regenerate photos-23 (§25): the §23 decision per by-dest file, grouped by
        destination as automatic-category SUMMARIES with file paths only for review/blocker items.
        Destinations are processed parent-first so a folder_fallback inherits its nearest resolved
        ancestor's effective fallback (§25, mirroring §10.2). Returns (artifact, blockers)."""
        blockers = []
        prior_dests = ((prior or {}).get("destinations")) or {}
        utc_by_path = {r["relative_path"]: r["resolved_utc"] for r in resolved_rows}
        by_dest = {}
        for f in files:
            by_dest.setdefault(f["destination"], []).append(f)

        destinations = {}
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

            prior_reviews = {ri["relative_path"]: ri for ri in
                             ((prior_d.get("gps_decisions") or {}).get("review_items") or [])}
            counts = {k: 0 for k in self._SUMMARY_KEYS}
            review_items, gpx_files = [], set()
            for f in sorted(by_dest.get(dest, []), key=lambda x: x["relative_path"]):
                rel = f["relative_path"]
                ru = _parse_utc(utc_by_path.get(rel)) if utc_by_path.get(rel) else None
                fd = (prior_reviews.get(rel) or {}).get("user_decision") or {}
                self._validate_review_decision(dest, rel, fd, blockers)
                cat, coord = classify_gps(f, ru, gpx, CONFIG, eff_fb, fd)
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
                    review_items.append(self._review_item(rel, "manual_locked", fd, False))
                elif cat == "no_change":
                    counts["no_gps_change_needed"] += 1
                    review_items.append(self._review_item(rel, "accepted_unlocated", fd, False))
                else:                                          # blocked
                    counts["blocked"] += 1
                    review_items.append(self._review_item(rel, "no_reliable_gps_source", fd, True))
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
        return artifact, blockers

    def _folder_fallback_cell(self, dest, prior_fb, inherited, blockers):
        ud = prior_fb.get("user_decision") or {}
        flat, flon = ud.get("fallback_lat", ""), ud.get("fallback_lon", "")
        accept = bool(ud.get("accept_proposal", False))
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
        if mlat not in (None, "") and mlon not in (None, "") and not _valid_coord(mlat, mlon):
            blockers.append(f"{dest}/{os.path.basename(rel)}: review manual_lat/lon out of range.")

    def _review_item(self, rel, reason, ud, requires):
        return {
            "relative_path": rel, "reason": reason,
            "user_decision": {"manual_lat": ud.get("manual_lat", ""), "manual_lon": ud.get("manual_lon", ""),
                              "accept_unlocated": bool(ud.get("accept_unlocated", False))},
            "requires_user_input": requires,
            "stale_user_decision": False,
        }

    def _gps_depends_on(self, resolved_fp):
        gps_policy = json.dumps({k: CONFIG[k] for k in (
            "gpx_direct_match_max_seconds", "gpx_interpolation_max_gap_seconds",
            "gpx_interpolation_max_distance_meters", "gpx_interpolation_max_speed_kmh",
            "gpx_extrapolation_max_seconds")}, sort_keys=True)
        return {
            # 22 is covered transitively: resolved_fp folds in photos_22_sha256 (§22.1), so a changed
            # drift confirmation already restales this. No separate 22 dep needed here.
            "resolved_utc_cache_fingerprint": resolved_fp,
            "gpx_fingerprint": self._gpx_fingerprint,
            "gps_policy_fingerprint": sha256_text(gps_policy),
            "handoff": self._handoff_dependency(self.workspace_root),
        }

    # --- Stage 9: executable plan (photos-24, §28) ---------------------------

    def build_executable_plan(self, files, resolved_rows, time_artifact, gps_artifact, gpx,
                              resolved_fp, ledger_entries=None):
        """Assemble photos-24 (§28): per-destination operations (corrected-time / GPS / marker /
        rename, plus revert-manual-GPS for withdrawn overrides §24.1) for execution to apply, the
        readiness gate, and the flattened dependency cascade. Automatic GPS is re-derived from
        inputs, never read from the photos-23 summary. Deterministic. Returns (plan, blockers)."""
        cfg = CONFIG
        fmt = cfg["filename_timestamp_format"]
        utc_by_path = {r["relative_path"]: r for r in resolved_rows}
        t_dests = time_artifact.get("destinations") or {}
        g_dests = gps_artifact.get("destinations") or {}

        blockers = []
        if time_artifact.get("status") != "complete":
            blockers.append("photos-21-time-decisions.json is not complete.")
        if gps_artifact.get("status") != "complete":
            blockers.append("photos-23-gps-decisions.json is not complete.")
        # Defensive: main() never reaches here unless 22 is complete, but assert it so a plan can
        # never assemble while a GPS-drift bucket is unconfirmed (§22a gate).
        dvp = drift_validation_path(self.workspace_root)
        if os.path.exists(dvp):
            try:
                with open(dvp) as _df:
                    if (json.load(_df) or {}).get("status") != "complete":
                        blockers.append(f"{DRIFT_VALIDATION_ARTIFACT} is not complete.")
            except Exception:
                blockers.append(f"{DRIFT_VALIDATION_ARTIFACT} is unreadable.")
        for f in files:
            row = utc_by_path.get(f["relative_path"])
            if not row or row.get("resolved_utc_status") != "valid":
                blockers.append(f"{f['relative_path']}: no valid resolved UTC.")

        by_dest = {}
        for f in files:
            by_dest.setdefault(f["destination"], []).append(f)

        destinations, all_ops, media_pre = {}, [], []
        cat_by_rel = {}                                   # rel -> (category, destination, file) for revert detection
        for dest in sorted(by_dest):
            g_d = g_dests.get(dest, {})
            eff_fb = (g_d.get("folder_fallback") or {}).get("effective_fallback")
            reviews = {ri["relative_path"]: (ri.get("user_decision") or {})
                       for ri in ((g_d.get("gps_decisions") or {}).get("review_items") or [])}
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
                cat_by_rel[rel] = (cat, dest, f)
                fops = plan_file_ops(f, ru, tz, cat, coord, renames.get(rel), cfg)
                if fops:
                    ops.extend(fops)
                else:
                    no_ops.append(rel)
                media_pre.append({"relative_path": rel, "content_fingerprint": f.get("content_fingerprint"),
                                  "size": f.get("size"), "mtime_ns": f.get("mtime_ns")})
            destinations[dest] = {"destination_path": dest, "operations": ops, "no_ops": no_ops}

        # Revert-manual-GPS (§24.1): a ledger'd file whose current decision is no longer manual had
        # its override withdrawn -> restore the pinned pre-state. A vanished file's entry is kept,
        # never reverted; a still-manual file re-asserts via its apply_manual write (no revert).
        for entry in (ledger_entries or []):
            rel = entry["relative_path"]
            cur = cat_by_rel.get(rel)
            if cur is None or cur[0] in _MANUAL_GPS_CATEGORIES:
                continue
            _cat, dest, f = cur
            op = _make_op("revert_manual_gps", rel, "revert withdrawn manual GPS",
                          {"writes": _revert_tags(entry["pre_state"]), "pre_state": entry["pre_state"],
                           "content_fingerprint": entry["content_fingerprint"]},
                          {"content_fingerprint": f.get("content_fingerprint"),
                           "size": f.get("size"), "mtime_ns": f.get("mtime_ns")})
            destinations[dest]["operations"].append(op)

        for dest, dd in destinations.items():
            ops = dd["operations"]
            all_ops.extend(ops)
            dd["summary"] = {
                "operations_total": len(ops), "no_ops": len(dd["no_ops"]),
                "metadata_time_writes": sum(1 for o in ops if o["type"] == "metadata_time_write"),
                "metadata_gps_writes": sum(1 for o in ops if o["type"] == "metadata_gps_write"),
                "gps_marker_writes": sum(1 for o in ops if o["type"] == "gps_marker_write"),
                "renames": sum(1 for o in ops if o["type"] == "rename_no_clobber"),
                "manual_gps_reverts": sum(1 for o in ops if o["type"] == "revert_manual_gps"),
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

    # --- Stage 10: execution (photos-25, §29) --------------------------------

    _META_OP_TYPES = ("metadata_time_write", "metadata_gps_write", "gps_marker_write")
    _OP_TOTAL_KEY = {"metadata_time_write": "metadata_time_writes", "metadata_gps_write": "metadata_gps_writes",
                     "gps_marker_write": "gps_marker_writes", "rename_no_clobber": "renames",
                     "revert_manual_gps": "manual_gps_reverts"}

    def _exiftool_write(self, abs_path, tags):
        """Apply a file's batched tag writes atomically (exiftool -overwrite_original = temp + atomic
        rename). Returns True on success. The single seam the tests mock to avoid invoking exiftool."""
        # A hard kill (SIGKILL/OOM/power loss) during a prior run can orphan exiftool's
        # `<file>_exiftool_tmp` intermediate; a clean SIGINT is self-cleaned by exiftool, so this only
        # matters for the un-graceful case. Geotag re-applies every un-confirmed file on resume,
        # and the only file that can hold an orphan is the one killed mid-write (never confirmed, so
        # revisited here) — so removing a stale temp for THIS target right before we rewrite it cleans
        # exactly the orphan that can exist. Safe: the original is untouched (the atomic rename never
        # happened) and the temp is a partial exiftool artifact, never user media.
        try:
            os.remove(abs_path + "_exiftool_tmp")
        except OSError:
            pass  # absent (the normal case) or unremovable — exiftool will surface a write error
        cmd = (["exiftool", "-overwrite_original", "-n"]
               + [f"-{k}={v}" for k, v in sorted(tags.items())] + [abs_path])
        try:
            return subprocess.run(cmd, capture_output=True, text=True, stdin=subprocess.DEVNULL).returncode == 0
        except Exception:
            return False

    def revalidate_plan(self, plan, gpx):
        """§29 steps 2-4: recompute every dependency fingerprint and return the stale reasons. A
        non-empty list means reject the plan before ANY mutation (the user re-runs to replan)."""
        ws = self.workspace_root
        dep = plan.get("depends_on") or {}
        stale = []
        if plan.get("status") != "ready":
            stale.append(f"plan status is {plan.get('status')!r}, not 'ready'")
        for key in ("time_decisions", "drift_validation", "gps_decisions"):
            if not (dep.get(key) and verify_json_dependency(dep[key], ws)):
                stale.append(f"{key} dependency changed or missing")
        if not (dep.get("handoff") and self._verify_handoff_dependency(dep["handoff"], ws)):
            stale.append("handoff dependency changed or missing")   # content fingerprint, not file bytes
        policy = json.dumps(CONFIG.get("camera_time_and_timezone_policy") or {}, sort_keys=True)
        for k, cur in (("config_fingerprint", sha256_file(config_path(ws))),
                       ("filename_format_fingerprint", sha256_text(CONFIG["filename_timestamp_format"])),
                       ("folders_fingerprint", folders_fingerprint()),
                       ("media_extensions_fingerprint", media_extensions_fingerprint()),
                       ("camera_group_fingerprint", sha256_text(policy)),
                       ("gpx_fingerprint", gpx.fingerprint)):
            if dep.get(k) != cur:
                stale.append(f"{k} changed")
        all_ops = [o for d in plan["destinations"].values() for o in d["operations"]]
        if dep.get("planned_operation_fingerprint") != sha256_text(json.dumps(all_ops, sort_keys=True)):
            stale.append("planned operations changed (plan tampered)")
        return stale

    @staticmethod
    def _target_occupied(directory, target_name, source_name):
        """Execute-time no-clobber recheck (§29.1a): is `target_name` already present
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

        Crash-resumable (§29.1.3): a file already applied by a crashed prior run is detected by its
        target state — its planned rename target in place (source gone), or its decoded-content
        fingerprint still matching the plan despite a changed size/mtime (a metadata write only) — and
        is skipped or re-applied idempotently rather than tripping the size/mtime precondition."""
        abs_path = os.path.join(self.workspace_root, rel)
        res = {"relative_path": rel, "applied": [], "skipped": [], "failed": [], "blocker": None,
               "mismatch": None, "reverted_fps": []}
        if all(journal.get(o["operation_id"]) == "confirmed" for o in ops):
            res["skipped"] = [o["operation_id"] for o in ops]
            return res
        pre = ops[0].get("preconditions") or {}
        rename_ops = [o for o in ops if o["type"] == "rename_no_clobber"]

        if not os.path.exists(abs_path):
            # Already-applied resume: the source is gone but the planned rename target is in place, so
            # a crashed prior run fully applied this file — skip it (don't block on the missing source).
            if rename_ops and os.path.exists(os.path.join(os.path.dirname(abs_path), rename_ops[-1]["to"])):
                res["skipped"] = [o["operation_id"] for o in ops]
                return res
            res["blocker"] = f"{rel}: file is missing at execute time"
            return res

        st = os.stat(abs_path)
        if (pre.get("size") is not None and st.st_size != pre["size"]) or \
           (pre.get("mtime_ns") is not None and st.st_mtime_ns != pre["mtime_ns"]):
            # The file differs from plan time. If its decoded-content fingerprint still matches, the
            # change is a metadata write — ours from a crashed prior run, or a benign touch — so the
            # ops are re-applied idempotently. If the content fingerprint differs, the image itself
            # changed externally: block (unless the operator already accepted this file's new identity).
            cur_fp = (ContentHasher.fingerprint_image(abs_path) or {}).get("value")
            if cur_fp != pre.get("content_fingerprint") and rel not in accepted_mismatches:
                res["blocker"] = f"{rel}: size/mtime changed and content fingerprint differs since planning"
                return res

        # metadata + revert-manual-GPS ops both produce a single batched, idempotent exiftool tag write
        write_ops = [o for o in ops if o["type"] in self._META_OP_TYPES or o["type"] == "revert_manual_gps"]
        if write_ops:
            tags = {}
            for o in write_ops:
                tags.update(o.get("writes") or {})
            if not self._exiftool_write(abs_path, tags):
                res["failed"] = [o["operation_id"] for o in write_ops]
                return res                          # tool failure: leave file as-is, never confirm
            new_fp = (ContentHasher.fingerprint_image(abs_path) or {}).get("value")
            if new_fp == pre.get("content_fingerprint") or rel in accepted_mismatches:
                res["applied"].extend(o["operation_id"] for o in write_ops)
                res["reverted_fps"] = [o["content_fingerprint"] for o in write_ops
                                       if o["type"] == "revert_manual_gps"]   # consume on restore
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

    def execute_plan(self, jobs, now_iso, execution_id):
        """Stage 10 (§29): apply photos-24 after re-validating every dependency, journaling for
        idempotent resume, verifying content fingerprints, and writing photos-25. now_iso /
        execution_id are injected so the fingerprint-bearing body stays reproducible. Returns the
        summary dict (status 'rejected' with stale reasons if the plan no longer applies)."""
        ws = self.workspace_root
        with open(executable_plan_path(ws)) as f:
            plan = json.load(f)
        gpx = GPXIndex(selected_gpx_root()).build(self.coordinator)
        stale = self.revalidate_plan(plan, gpx)
        if stale:
            return {"status": "rejected", "plan_id": plan.get("plan_id"), "stale": stale}

        # Optional pre-mutation ZFS snapshot (§29 step 6), labelled "geotag" so it never collides
        # with prep's "prep-" snapshot. A REQUIRED snapshot that cannot be taken aborts before any
        # mutation; the record is carried into photos-25 either way.
        snapshot = take_zfs_snapshot(ws, plan["plan_id"], "geotag")
        if snapshot is not None and snapshot["required"] and not snapshot["ok"]:
            reason = f"required ZFS pre-mutation snapshot failed: {snapshot['stderr']}"
            # Nothing was mutated, but §29 step 6 requires the snapshot record be carried into photos-25
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
        journal = {}
        if os.path.exists(jpath):
            try:
                journal = (json.load(open(jpath)) or {}).get("operations", {}) or {}
            except Exception:
                journal = {}
        accepted = self._accepted_mismatches(ws)

        by_file = {}
        for dd in plan["destinations"].values():
            for op in dd["operations"]:
                by_file.setdefault(op["relative_path"], []).append(op)

        cache = GeotagCache(ws)
        try:
            # Capture-before-write (§24.1 / §29.1a.3): pin each manual GPS override's pre-state —
            # prep's original GPS, NOT a re-read — once, BEFORE any write, keyed by content fingerprint.
            captured = 0
            pre_by_fp = {f.get("content_fingerprint"): (f["relative_path"], _handoff_pre_state(f.get("native_gps")))
                         for f in self.build_file_model()}
            for ops in by_file.values():
                for op in ops:
                    if op.get("gps_origin") == "apply_manual":
                        fp = (op.get("preconditions") or {}).get("content_fingerprint")
                        if fp and cache.ledger_get(fp) is None and fp in pre_by_fp:
                            rel_fp, pre = pre_by_fp[fp]
                            cache.ledger_pin(fp, rel_fp, pre, now_iso)
                            captured += 1

            results = []
            self.coordinator.start_phase("applying calibration", len(by_file))
            with concurrent.futures.ThreadPoolExecutor(max_workers=max(1, jobs)) as ex:
                futs = [ex.submit(self._apply_file, rel, ops, journal, accepted)
                        for rel, ops in sorted(by_file.items())]
                try:
                    for fut in concurrent.futures.as_completed(futs):
                        r = fut.result()
                        results.append(r)
                        self.coordinator.increment_completed(1)
                        # Incremental confirmation journal (§29.1a): persist each file's confirmed ops AS
                        # IT COMPLETES (in this main thread — workers never touch the journal), so a crash
                        # mid-run leaves a journal that lets the next run skip the already-applied files.
                        if r["applied"]:
                            for oid in r["applied"]:
                                journal[oid] = "confirmed"
                            write_json_artifact(jpath, {"journal_version": 1, "plan_id": plan["plan_id"],
                                                        "operations": journal, "updated_at": now_iso})
                except KeyboardInterrupt:
                    # Ctrl-C: drop pending file writes and stop waiting instead of letting the `with`
                    # exit drain them (shutdown(wait=True)). Files already applied are confirmed in the
                    # journal above, so the next run resumes from the diff (§29.1a). Re-raise to main().
                    ex.shutdown(wait=False, cancel_futures=True)
                    raise
            self.coordinator.finish_phase()

            # Consume-on-restore (§24.1.4): a successfully-reverted present file's pin is removed.
            reverted = 0
            for r in results:
                for fp in r.get("reverted_fps") or []:
                    cache.ledger_consume(fp)
                    reverted += 1
        finally:
            cache.close()
            from .photos_utils import PersistentMagickWorker
            PersistentMagickWorker.cleanup_all()       # close the per-thread magick workers (verify pass)

        # The journal was persisted incrementally as each file completed (above); nothing more to flush.
        summary = self._build_summary(plan, results, now_iso, execution_id, jobs)
        summary["totals"]["manual_gps_pre_states_captured"] = captured   # reverts counted by _build_summary
        summary["snapshot"] = snapshot                                   # the pre-mutation ZFS record (or None)
        write_json_artifact(execution_summary_path(ws), summary)
        return summary

    @staticmethod
    def _accepted_mismatches(ws):
        """File paths whose prior photos-25 fingerprint mismatch the user marked accept=true."""
        p = execution_summary_path(ws)
        if not os.path.exists(p):
            return set()
        try:
            prior = json.load(open(p))
        except Exception:
            return set()
        return {m["relative_path"] for m in (prior.get("fingerprint_mismatches") or [])
                if (m.get("user_decision") or {}).get("accept_fingerprint_change")}

    def _build_summary(self, plan, results, now_iso, execution_id, jobs):
        ws = self.workspace_root
        op_type, op_dest = {}, {}
        for dest, dd in plan["destinations"].items():
            for o in dd["operations"]:
                op_type[o["operation_id"]] = o["type"]
                op_dest[o["operation_id"]] = dest
        totals = {v: 0 for v in self._OP_TOTAL_KEY.values()}
        # Per-destination operation counts (§29.2 item 4 — applied/no-op/skipped per destination + global total).
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

    # --- Stage 11: finalize + archive (§31 / shared §13) ---------------------

    _ARCHIVE_ITEMS = ["photos-00-config.json", "photos-11-handoff.json", "photos-15-prep-log.json",
                      "photos-15-prep-ingest.db", TIME_DECISIONS_ARTIFACT, GPS_DECISIONS_ARTIFACT,
                      EXECUTABLE_PLAN_ARTIFACT, EXECUTION_SUMMARY_ARTIFACT, COMPLETE_LOG_ARTIFACT,
                      GEOTAG_DB_SNAPSHOT, "photos-00-ingest.db"]

    def finalize_package(self, now_iso):
        """Stage 11 (§31): assemble the durable archival package — the photos-26 transformation log,
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

        files = self.build_file_model()
        cache = GeotagCache(ws)
        try:
            rows, ledger = cache.get_rows(), cache.ledger_all()
        finally:
            cache.close()
        time_artifact = json.load(open(time_decisions_path(ws)))
        prep_photos = {}
        if os.path.exists(prep_log_path(ws)):
            try:
                prep_photos = (json.load(open(prep_log_path(ws))) or {}).get("photos", {}) or {}
            except Exception:
                prep_photos = {}
        photos = build_complete_log(prep_photos, files, rows, time_artifact, plan, ledger)
        write_json_artifact(complete_log_path(ws),
                            {"schema_version": 1, "tool": "photos-2-geotag", "photos": photos})

        conn = sqlite3.connect(db_path(ws))
        try:
            write_db_snapshot(conn, geotag_db_snapshot_path(ws))   # §13.4a: consistent, atomic
        finally:
            conn.close()

        write_json_artifact(archive_manifest_path(ws), self._archive_manifest(plan, summary, now_iso))
        return []

    def _archive_manifest(self, plan, summary, now_iso):
        ws = self.workspace_root
        contents = {}
        for name in self._ARCHIVE_ITEMS:
            p = os.path.join(ws, CONTROL_DIR, name)
            if os.path.exists(p):
                contents[name] = {"path": os.path.relpath(p, ws), "sha256": sha256_file(p)}
        return {
            "artifact_type": "archive_manifest", "artifact_name": ARCHIVE_MANIFEST_ARTIFACT,
            "schema_version": 1,
            "workspace": os.path.basename(os.path.abspath(ws)),
            "plan_id": plan.get("plan_id"),
            "execution_id": (summary.get("run_metadata") or {}).get("execution_id"),
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


def add_arguments(parser):
    """Register geotag's `-j` + subcommands (plan / execute / finalize) on `parser`. Shared by the
    standalone `python -m cartographer.photos_2_geotag` and the combined `photos-cartographer geotag`."""
    parser.add_argument("-j", "--jobs", type=int, default=None,
                        help="Worker threads for execution (default: config jobs, else 4).")
    sub = parser.add_subparsers(dest="command")
    sub.add_parser("plan", help="Plan the geotag pass: produce photos-21/22/23/24 (no mutation).")
    sub.add_parser("execute", help="Apply photos-24 to the originals (metadata writes + renames).")
    sub.add_parser("finalize", help="Bundle the durable archival package (photos-26; non-destructive).")
    parser.set_defaults(_run=run, _parser=parser)


def _auto_reprep_for_clean_move(args, workspace_root, reporter):
    """Geotag §13.1.1 — auto re-prep for a clean by-dest move, run BEFORE geotag takes the whole-run lock.

    The common operator flow is: move photos from by-date into the by-dest tree, then go straight to
    geotag. That move leaves the handoff stale (geotag derives each file's calibration `destination`
    from the handoff), so geotag would otherwise hard-stop and tell you to re-run prep by hand. Instead,
    for the *clean* case — workspace initialized, `0-sources` already empty (so this is the stat-only
    move refresh: no media is moved, `by_dest_mutated: 0`), and a by-date→by-dest move is the one thing
    the handoff hasn't recorded — run the real prep phases (`plan` then `execute`) for the operator,
    announcing what and why. Everything else is left untouched for the in-lock gates to report:
    sealed/uninitialized, a non-empty `0-sources` dump (the cheapest hard gate — a bigger op the
    operator should launch knowingly), or nothing pending. prep takes and releases its own whole-run
    lock, so this MUST run pre-lock to avoid self-deadlock; geotag's own `_check_reprep_gate` then
    re-validates under the lock as the fallback (a race or a non-clean move still hard-stops)."""
    if args.command != "plan":
        return
    if is_sealed(workspace_root) or not os.path.exists(guard_path(workspace_root)):
        return
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
    reporter.log(f"{by_dest}/ has photo(s) prep hasn't recorded yet (e.g. {example}), and {sources}/ is "
                 f"empty — recording your move before geotag: running prep plan + execute "
                 f"(stat-only, no media moved)…")
    import types
    from . import photos_1_prep
    for cmd in ("plan", "execute"):
        prep_args = types.SimpleNamespace(command=cmd, jobs=getattr(args, "jobs", 4))
        try:
            photos_1_prep.run(prep_args)
        except SystemExit as e:
            if e.code not in (0, None):
                reporter.error(f"Auto prep {cmd} did not succeed (exit {e.code}). Resolve it and re-run "
                               "geotag — nothing was geotagged.")
                sys.exit(2)
    reporter.log("Re-prep complete; continuing with geotag.")


def run(args):
    workspace_root = os.getcwd()
    reporter = get_reporter()

    # §13.1.1: auto re-prep a clean by-dest move so the operator can go straight to geotag. Runs BEFORE
    # the lock (prep takes its own); the in-lock _check_reprep_gate stays as the re-validation fallback.
    _auto_reprep_for_clean_move(args, workspace_root, reporter)

    # Whole-run workspace lock (shared contract §2): one lock across every phase; fail-fast.
    run_lock = WorkspaceLock(workspace_root)
    if not run_lock.acquire():
        owner = run_lock.read_owner() or {}
        detail = f" (pid {owner.get('pid')}, since {owner.get('started_at')})" if owner else ""
        reporter.log(f"Workspace is locked by an in-progress run{detail}; try again when it finishes.")
        sys.exit(1)
    reporter.log(f"Lock acquired: {run_lock.lock_path}")
    try:
        if args.command == "plan":
            wf = GeotagWorkflow(workspace_root)
            blockers, warnings, info = wf.preflight()
            for w in warnings:
                reporter.warn(f"  Warning: {w}")
            if blockers:
                reporter.error("\nGeotag cannot proceed:")
                for b in blockers:
                    reporter.log(f"  - {b}")
                reporter.log("\nNo geotag JSON was written.")
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
                dg = (CONFIG.get("camera_time_and_timezone_policy") or {}).get("device_groups") or {}
                labels = ("phones", "fixed_clock_cameras")
                for i, label in enumerate(labels):
                    existing = list(dg.get(label) or [])
                    merged = existing + [k for k in unknown if k not in existing]
                    tail = "," if i < len(labels) - 1 else ""
                    if merged:
                        items = ",\n".join(f"    {json.dumps(k)}" for k in merged)
                        reporter.log(f'  "{label}": [\n{items}\n  ]{tail}')
                    else:
                        reporter.log(f'  "{label}": []{tail}')
                reporter.log("\nNo geotag JSON was written.")
                sys.exit(2)

            gpx = wf.load_gpx()      # disk-heavy: only after the in-memory checks above have passed
            n_dest = len({f["destination"] for f in files})
            by_class = {}
            for g in groups.values():
                by_class[g["camera_group_class"]] = by_class.get(g["camera_group_class"], 0) + 1
            cls_summary = ", ".join(f"{n} {c}" for c, n in sorted(by_class.items())) or "none"
            reporter.log(f"Model built: {len(files)} photo(s) across {n_dest} destination(s); "
                  f"{len(groups)} camera group(s) ({cls_summary}); "
                  f"GPX {gpx.status} ({len(gpx.points)} point(s), fp {(gpx.fingerprint or '')[:12]}).",
                  stream="stdout")

            # Stages 5–6: time decisions (photos-21). Regenerate from current inputs while
            # preserving authored decisions (§9); a sanity-validation failure on a preserved value
            # is a hard blocker that leaves the user's artifact untouched to be fixed (§9.2).
            tdp = time_decisions_path(workspace_root)
            prior = None
            if os.path.exists(tdp):
                try:
                    with open(tdp) as f:
                        prior = json.load(f)
                except Exception:
                    prior = None
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
                # (rows0). This drives drift detection (§22a) and, once 22 is clean, is recomputed
                # with the operator-validated offsets before anything downstream consumes it.
                rows0 = compute_resolved_utc(files, groups, artifact)

                # Stage 7a: GPS-drift validation (photos-22, §22a) — the gate before phase 23. A
                # manual/timezone-derived offset with no native-GPS anchor is placed purely from its
                # resolved UTC, so a wrong offset silently mis-places the whole batch; 22 makes the
                # operator confirm each such bucket (a zero-scrub must be explicit) before GPS is built.
                dvp = drift_validation_path(workspace_root)
                prior_drift = None
                if os.path.exists(dvp):
                    try:
                        with open(dvp) as f:
                            prior_drift = json.load(f)
                    except Exception:
                        prior_drift = None
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
                    # and report the deterministic fingerprint downstream stages depend on (§22).
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
                        ledger_entries = cache.ledger_all()    # to plan revert ops for withdrawn overrides
                    finally:
                        cache.close()
                    fp = resolved_utc_fingerprint(rows, input_fps)
                    n_valid = sum(1 for r in rows if r["resolved_utc_status"] == "valid")
                    reporter.log(f"Resolved UTC for {n_valid}/{len(rows)} photo(s) "
                          f"(resolved_utc_cache_fingerprint {fp[:12]}).", stream="stdout")

                    # Stage 8: GPS decisions (photos-23). Regenerate from the resolved rows + GPX,
                    # preserving authored GPS decisions; a bad authored coord leaves the artifact as-is.
                    gdp = gps_decisions_path(workspace_root)
                    prior_gps = None
                    if os.path.exists(gdp):
                        try:
                            with open(gdp) as f:
                                prior_gps = json.load(f)
                        except Exception:
                            prior_gps = None
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

                    # Stage 9: assemble photos-24 only when ALL decision artifacts are complete (§28).
                    if (artifact["status"] == "complete" and drift_artifact["status"] == "complete"
                            and gps_artifact["status"] == "complete"):
                        plan, _ = wf.build_executable_plan(files, rows, artifact, gps_artifact, gpx, fp,
                                                           ledger_entries)
                        epp = executable_plan_path(workspace_root)
                        _, _ep_bak = write_versioned_json(epp, plan)
                        n_ops = sum(d["summary"]["operations_total"] for d in plan["destinations"].values())
                        reporter.log(f"Wrote {EXECUTABLE_PLAN_ARTIFACT}: status={plan['status']} "
                              f"(plan {plan['plan_id']}, {n_ops} operation(s)).", stream="stdout")
                        reporter.log(f"  Plan saved to {epp}", stream="stdout")
                        if _ep_bak:
                            reporter.log(f"  Previous plan backed up to {_ep_bak}", stream="stdout")
                        reporter.log("  Review it, then run `execute` to apply.", stream="stdout")

        elif args.command == "execute":
            wf = GeotagWorkflow(workspace_root)
            blockers, warnings, info = wf.preflight(for_execute=True)
            for w in warnings:
                reporter.warn(f"  Warning: {w}")
            if blockers:
                reporter.error("\nExecution cannot proceed:")
                for b in blockers:
                    reporter.log(f"  - {b}")
                sys.exit(2)
            if not os.path.exists(executable_plan_path(workspace_root)):
                reporter.log(f"No {EXECUTABLE_PLAN_ARTIFACT} — run `plan` first.")
                sys.exit(2)
            now_iso = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
            execution_id = sha256_text(f"{now_iso}|{os.getpid()}")[:12]
            jobs = args.jobs or CONFIG.get("jobs") or 4
            summary = wf.execute_plan(jobs, now_iso, execution_id)
            if summary.get("status") == "rejected":
                reporter.error("\nExecution rejected — the plan is stale; re-run `run` to replan:")
                for s in summary["stale"]:
                    reporter.log(f"  - {s}")
                sys.exit(2)
            t = summary["totals"]
            reporter.log(f"Executed {EXECUTABLE_PLAN_ARTIFACT}: status={summary['status']} "
                  f"({t['metadata_time_writes']} time, {t['metadata_gps_writes']} gps, "
                  f"{t['renames']} rename(s); {len(summary['fingerprint_mismatches'])} fingerprint "
                  f"mismatch(es), {len(summary['failures'])} failure(s)). Wrote {EXECUTION_SUMMARY_ARTIFACT}.",
                  stream="stdout")
            if summary["status"] != "success":
                reporter.log(f"Review {EXECUTION_SUMMARY_ARTIFACT} and re-run `execute` once resolved.")
                sys.exit(3)

        elif args.command == "finalize":
            wf = GeotagWorkflow(workspace_root)
            blockers, warnings, info = wf.preflight(for_execute=True)
            for w in warnings:
                reporter.warn(f"  Warning: {w}")
            if blockers:
                reporter.error("\nFinalize cannot proceed:")
                for b in blockers:
                    reporter.log(f"  - {b}")
                sys.exit(2)
            now_iso = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
            fin_blockers = wf.finalize_package(now_iso)
            if fin_blockers:
                reporter.error("\nCannot finalize — geotag has not ended successfully:")
                for b in fin_blockers:
                    reporter.log(f"  - {b}")
                sys.exit(2)
            reporter.log(f"Finalized: wrote {COMPLETE_LOG_ARTIFACT}, {GEOTAG_DB_SNAPSHOT}, and "
                  f"{ARCHIVE_MANIFEST_ARTIFACT} to {CONTROL_DIR}/. The archival package is ready to "
                  "copy to permanent storage (geotag does not seal or merge).", stream="stdout")
    except KeyboardInterrupt:
        # Clean Ctrl-C: planning never mutates and execute is journalled/idempotent, so applied
        # files are confirmed and the next run resumes from the diff (§29.1a). Exit quietly with
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
