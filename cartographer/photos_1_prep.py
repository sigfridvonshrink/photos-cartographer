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

"""
photos-1-prep: prep-only workspace organization, cache update, and handoff generation
"""

import os
import sys
import json
import hashlib
import tempfile
import subprocess
import select
import socket
import fcntl
from dataclasses import dataclass, field, asdict
from typing import Dict, List, Optional, Any
from datetime import datetime, timezone
import uuid
import sqlite3
import threading
import contextlib
import ctypes
import errno

# ==============================================================================
# CONFIGURATION BLOCK
# ==============================================================================
from .photos_utils import CONFIG, CAMERA_IDENTITY_FIELDS, folder_name, managed_folder_names, dedup_priority, is_track_file, missing_managed_folders, misplaced_top_level_entries, FOLDER_ROLES, UNTIMED_PREFIX, untimed_stem, carries_stem, filename_format_changed, code_fingerprint, hidden_folder_holds_files
from .photos_utils import (add_accept_changes_argument, add_zone_table_argument, check_workspace, read_workspace_record, write_workspace_record,
                          forget_in_workspace_record, note_execution_begun)
from .reporting import get_reporter, emit_next_step
from .photos_utils import (replace_durably, _move_no_clobber, _move_link_unlink, _get_renameat2,
                          WorkspaceCache, WorkspaceLock, ContentHasher, PlanFingerprintMemo,
                          CACHE_SCHEMA_VERSION, FINGERPRINT_ALGORITHM_VERSION,
                          allocate_suffix)






from ._prep_models import *  # noqa: F401,F403 — re-export plan/journal models (keeps photos_1_prep.<Model> resolvable for the workflow, tests, and patches)

class RootGuard:
    @staticmethod
    def resolve_and_check_path(base_dir: str, target_path: str, must_be_relative: bool = True) -> str:
        """
        Resolves a path safely.
        Rejects absolute paths if expected to be relative.
        Rejects .. traversal.
        Rejects symlink escapes.
        Proves containment within base_dir.
        """
        if must_be_relative and os.path.isabs(target_path):
            raise ValueError(f"Path must be relative, but absolute path provided: {target_path}")

        # Check for .. traversal explicitly in the raw string
        if ".." in target_path.split(os.sep):
            raise ValueError(f"Directory traversal (..) not allowed in path: {target_path}")

        full_path = os.path.join(base_dir, target_path)
        resolved_path = os.path.realpath(full_path)
        resolved_base = os.path.realpath(base_dir)

        try:
            common = os.path.commonpath([resolved_base, resolved_path])
        except ValueError:
            raise ValueError(f"Path validation failed: {target_path} is not on the same mount as {base_dir}")

        if common != resolved_base:
            raise ValueError(f"Path escape detected: {target_path} resolves outside {base_dir}")

        return resolved_path


import concurrent.futures

# ContentHasher now lives in photos_utils (the cross-phase content-fingerprint spine, shared with
# geotag); re-exported below so existing references and tests resolve unchanged.

PREP_LOG_SCHEMA_VERSION = 1


def _append_quarantine_manifest(manifest_dir, entry):
    """Append `entry` to `manifest_dir/manifest.json` — the recoverable quarantine record (BLD-quarantine_layout).

    Never silently truncates history: if the existing manifest is unreadable (corrupt JSON, not an
    array, or unreadable), it is PRESERVED under a `.corrupt-<ts>-<rand>` backup before a fresh one is
    started, so the prior records can still be recovered by hand. The write is atomic (temp in the
    same dir → atomic rename, BLD-quarantine_layout), so a crash mid-write can never leave the torn manifest that
    the recovery path otherwise has to clean up after."""
    os.makedirs(manifest_dir, exist_ok=True)
    manifest_path = os.path.join(manifest_dir, "manifest.json")
    existing = []
    if os.path.exists(manifest_path):
        try:
            with open(manifest_path, 'r') as mf:
                existing = json.load(mf)
            if not isinstance(existing, list):
                raise ValueError("manifest is not a JSON array")
        except (json.JSONDecodeError, ValueError, OSError) as e:
            backup = (f"{manifest_path}.corrupt-{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')}"
                      f"-{uuid.uuid4().hex[:6]}")
            try:
                replace_durably(manifest_path, backup)
            except OSError as set_aside_error:
                # A manifest that can be neither read nor set aside is never written over: it is the only record
                # of why the files already here were quarantined (RUL-unreadable_manifest_kept). The move fails
                # before the file is touched.
                raise RuntimeError(f"quarantine manifest {manifest_path} is unreadable ({e}) and could not be set "
                                   f"aside ({set_aside_error}); nothing was written over it") from set_aside_error
            get_reporter().warn(f"Warning: quarantine manifest {manifest_path} was unreadable ({e}); preserved "
                                f"it as {os.path.basename(backup)} and started a fresh manifest.")
            existing = []
    existing.append(entry)
    fd, tmp = tempfile.mkstemp(dir=manifest_dir, prefix=".tmp-manifest-", suffix=".json")
    try:
        with os.fdopen(fd, 'w') as mf:
            json.dump(existing, mf, indent=2)
        replace_durably(tmp, manifest_path)
    except Exception:
        if os.path.exists(tmp):
            try:
                os.remove(tmp)
            except OSError:
                pass
        raise


def read_prior_prep_log(workspace_root):
    """The earlier prep log's `photos`, {} where there is no log yet. A log that exists and cannot be read — not
    readable, not JSON, or no `photos` object — is never taken for an empty one (RUL-unreadable_prep_log_stops): it
    raises ValueError naming the file, which the plan records as a blocker and execute refuses on."""
    from .photos_utils import prep_log_path
    plp = prep_log_path(workspace_root)
    if not os.path.exists(plp):
        return {}
    try:
        with open(plp) as pf:
            photos = json.load(pf).get("photos")
        if not isinstance(photos, dict):
            raise ValueError("it holds no photos record")
    except (OSError, ValueError, AttributeError) as e:
        raise ValueError(f"Prep's log {os.path.relpath(plp, workspace_root)} cannot be read ({e}); prep will not "
                         "take it for an empty log and rewrite it from this run alone. Restore it, or remove it "
                         "to start the log afresh, then plan again.")
    return photos


def _fingerprint_value(content_hash):
    """The fingerprint value a database row's `content_hash` holds, or None."""
    if not content_hash:
        return None
    try:
        return json.loads(content_hash).get("value")
    except Exception:
        return None


def set_aside_partners(log_photos) -> dict:
    """{fingerprint of a JPEG set aside beside its RAW: that RAW's fingerprint}, from the prep log's photos
    (BLD-set_aside_pair_recorded): each JPEG's latest `redundant_jpeg_separated` step that names its RAW."""
    out = {}
    for fp, entry in (log_photos or {}).items():
        for step in (entry or {}).get("journey") or []:
            if step.get("action") == "redundant_jpeg_separated" and step.get("raw_fingerprint"):
                out[fp] = step["raw_fingerprint"]
    return out


def hand_deletions(workspace_root, workspace_changes=()) -> dict:
    """{fingerprint: the path it was deleted at} of every file a workspace check found deleted by hand — a cull
    (RUL-culling_passes) — whichever run's check found it: this run's (`workspace_changes`), an earlier prep run's, as
    prep's log keeps it, or a geotag execution's, as its summary and the summaries kept under -NNN keep it
    (BLD-workspace_changes_logged). A record that cannot be read adds nothing: its own reader reports it
    (BLD-culled_raw_found)."""
    import glob as _glob
    from .photos_utils import prep_log_path, CONTROL_DIR
    sources = [list(workspace_changes or [])]

    def kept_changes(path):
        try:
            with open(path) as f:
                changes = json.load(f).get("workspace_changes")
        except (OSError, ValueError, AttributeError):
            return []
        return changes if isinstance(changes, list) else []
    sources.append(kept_changes(prep_log_path(workspace_root)))
    summary = os.path.join(workspace_root, CONTROL_DIR, "photos-25-execution-summary")
    for p in [summary + ".json"] + sorted(_glob.glob(_glob.escape(summary) + "-[0-9][0-9][0-9]*.json")):
        sources.append(kept_changes(p))
    out = {}
    for changes in sources:
        for c in changes:
            if isinstance(c, dict) and c.get("kind") == "deleted" and c.get("content_fingerprint"):
                out.setdefault(c["content_fingerprint"], c.get("path"))
    return out


def read_prior_workspace_changes(workspace_root) -> list:
    """The earlier prep log's `workspace_changes` — the changes by hand earlier runs named or accepted
    (BLD-workspace_changes_logged) — [] where there is no log yet. Read after `read_prior_prep_log` has found the log
    readable."""
    from .photos_utils import prep_log_path
    plp = prep_log_path(workspace_root)
    if not os.path.exists(plp):
        return []
    with open(plp) as pf:
        changes = json.load(pf).get("workspace_changes")
    return [c for c in changes if isinstance(c, dict)] if isinstance(changes, list) else []


def _fingerprint_method(content_hash_json):
    """The method a recorded fingerprint was taken by — its strategy and engine version — or None."""
    try:
        ch = json.loads(content_hash_json)
        return (ch.get("strategy"), ch.get("engine_version"))
    except (TypeError, ValueError, AttributeError):
        return None


def build_prep_log(prior_photos, operations, cache_files, quarantine_evidence, run_id, prior_record=None):
    """Build the per-photo, content-fingerprint-keyed prep transformation log (BLD-prep_log_build).

    Pure and derived — it introduces no new authority, only consolidating records prep already
    produced: this run's validated plan operations, the final cache rows (for the fingerprint and
    current location), and the run's quarantine evidence — merged onto `prior_photos` (the prior
    log's `photos`, carried forward). Each NEW step is stamped with `run_id` so it is attributable
    to the run that caused it; carried-forward steps keep their original run, so a
    no-op run leaves the log unchanged (RUL-no_op_run). Returns (photos_dict, warnings)."""
    warnings = []

    def _step(action, **kw):
        return {"phase": "prep", "action": action, "run": run_id, **kw}

    # 1. Replay this run's move/rename ops in order into per-origin journeys (the same chain the
    #    planner's current_paths builds). Strays / structural / cache ops carry no media journey.
    journeys = {}          # origin path -> {"steps": [...], "current": path}
    path_origin = {}       # a file's current path -> its origin key
    pending_extnorm = {}   # origin -> original basename (first half of the two-step ext-norm)
    for op in operations:
        if op.type not in ("move_no_clobber", "rename_no_clobber"):
            continue
        src, dst, reason = op.source, op.destination, (op.reason or "")
        if not src or not dst or "stray" in reason:    # non-media -> 1-strays is never logged
            continue
        origin = path_origin.get(src, src)
        j = journeys.setdefault(origin, {"steps": [], "current": src})
        if "Normalize extension case (temp)" in reason:
            pending_extnorm.setdefault(origin, os.path.basename(src))   # collapse the two-step
        elif "Normalize extension case" in reason:
            frm = pending_extnorm.pop(origin, os.path.basename(src))
            j["steps"].append(_step("extension_normalized", **{"from": frm, "to": os.path.basename(dst)}))
        elif "Initialize: move base dump into sources" in reason:
            j["steps"].append(_step("consolidated_into_sources", **{"from": src, "to": dst}))
        elif "Separate redundant JPG" in reason:
            # the RAW it was set aside beside, by fingerprint: the pair, known exactly (BLD-set_aside_pair_recorded)
            raw = (op.verification or {}).get("raw_fingerprint")
            j["steps"].append(_step("redundant_jpeg_separated", **{"from": src, "to": dst},
                                    **({"raw_fingerprint": raw} if raw else {})))
        elif "Chronological Organization" in reason:
            # every move and rename names where the photo came from as well as where it went (BLD-log_format)
            j["steps"].append(_step("organized", **{"from": src, "to": dst.split('/', 1)[0] + "/"}))
            j["steps"].append(_step("provisional_rename", **{"from": os.path.basename(src), "to": os.path.basename(dst)}))
        path_origin[dst] = origin
        j["current"] = dst

    def _fp(row):
        return _fingerprint_value(row.get("content_hash"))

    # 2. Index the final cache rows by fingerprint -> current path (media only).
    fp_to_current = {}
    for rel, row in cache_files.items():
        if row.get("media_class") in ("image", "raw", "video"):
            fp = _fp(row)
            if fp:
                fp_to_current[fp] = rel

    # 3. This run's journey steps, keyed by the fingerprint of each journey's final cache row.
    run_steps_by_fp = {}
    for origin, j in journeys.items():
        row = cache_files.get(j["current"])
        if not row:                                    # ended outside the cache (e.g. quarantined)
            continue
        fp = _fp(row)
        if fp:
            run_steps_by_fp.setdefault(fp, []).extend(j["steps"])

    # 3a. A JPEG set aside beside a RAW the user culled, quarantined by this run: its step names the RAW by where it
    #     was and by its fingerprint, and the photo is left where the quarantine holds it (RUL-culled_raw_jpeg_logged).
    culled_to = {}
    for op in operations:
        v = op.verification or {}
        if op.type == "quarantine_move" and v.get("kind") == "raw_culled" and v.get("content_fingerprint"):
            run_steps_by_fp.setdefault(v["content_fingerprint"], []).append(_step(
                "raw_culled", **{"from": op.source, "to": op.destination, "raw_path": v.get("raw_path"),
                                 "raw_fingerprint": v.get("raw_fingerprint")}))
            culled_to[v["content_fingerprint"]] = op.destination

    # 4. Quarantined duplicates, keyed by content fingerprint (same content as the retained file).
    quarantined_by_fp = {}
    for ev in (quarantine_evidence or []):
        fp = ev.get("content_hash")
        if not fp:
            continue
        quarantined_by_fp.setdefault(fp, []).append({
            "origin": ev.get("original_path"),
            "quarantine_path": ev.get("quarantine_path"),
            "retained_counterpart": ev.get("retained_counterpart"),
        })

    # 5. A photo whose fingerprint was taken again by another method has a new value: its entry, found by
    #    the path it was left at — or, for a file the user moved, the path it was moved from — moves to the
    #    new value, provided the old value is no longer anywhere in the workspace and no step of this run
    #    already speaks for the new one.
    moved_from = {fx["data"]["relative_path"]: fx["moved_from"]
                  for op in operations if op.type == "db_upsert"
                  for fx in (op.database_effects_after_verification or []) if fx.get("moved_from")}
    prior_photos = dict(prior_photos)
    _old_by_path = {e.get("prep_path"): old for old, e in prior_photos.items()
                    if old not in fp_to_current and e.get("prep_path")}

    def _same_file_retaken(left_at, path):
        # Only the file the earlier record describes, unchanged — the same size, modification time and inode — with
        # its fingerprint taken by another method, is that photo; a different file at the path is a new photo, and the
        # gone one's entry stays as it was (RUL-retake_only_unchanged_file).
        rec, row = (prior_record or {}).get(left_at), cache_files.get(path) or {}
        if rec is None or (rec["size"], rec["mtime_ns"], rec["inode"]) != (row.get("size"), row.get("mtime_ns"),
                                                                           row.get("inode")):
            return False
        before, now = _fingerprint_method(rec.get("fingerprint")), _fingerprint_method(row.get("content_hash"))
        return before is not None and now is not None and before != now

    for new_fp, path in fp_to_current.items():
        left_at = path if path in _old_by_path else moved_from.get(path)
        old = _old_by_path.get(left_at)
        # A file this run moved or renamed is a photo of this run's own, never the old entry's (RUL-gone_photo_entry_carried).
        if (new_fp not in prior_photos and old in prior_photos and new_fp not in run_steps_by_fp
                and _same_file_retaken(left_at, path)):
            entry = prior_photos.pop(old)
            prior_photos[new_fp] = dict(entry, content_fingerprint=new_fp, journey=list(entry.get("journey", [])) + [
                _step("fingerprint_retaken", **{"from": old, "to": new_fp})])

    # 6. Merge onto the prior log carried forward.
    _bands = {folder_name(r) for r in ("missing_metadata", "redundant_jpgs", "videos_by_date", "photos_by_date")}
    photos = {}
    for fp in set(prior_photos) | set(run_steps_by_fp) | set(fp_to_current) | set(quarantined_by_fp):
        prior = prior_photos.get(fp)
        run_steps = run_steps_by_fp.get(fp, [])
        quar = quarantined_by_fp.get(fp)
        current = fp_to_current.get(fp) or culled_to.get(fp) or (prior.get("prep_path") if prior else None)
        if not (prior or run_steps or quar):
            # No prep transformation recorded for this content. In a prep-organized band that
            # means lost history (warn + partial, RUL-partial_history_shown); by-dest/user-curated media is skipped.
            top = current.split('/', 1)[0] if current else ""
            if top in _bands:
                photos[fp] = {"content_fingerprint": fp, "prep_path": current, "journey": [],
                              "partial": True, "note": "prep history incomplete (no retained journey)"}
                warnings.append(f"prep-log: incomplete history for {current}")
            continue
        if prior:
            journey = list(prior.get("journey", [])) + run_steps
            if not run_steps and current and current != prior.get("prep_path"):
                # Recognized by-date -> by-dest move (carried-forward identity, no plan op) — or a photo moved back
                # from photos by destination, which the user may do too (RUL-moved_back_passes).
                back = not current.startswith(folder_name('photos_by_dest') + "/")
                journey.append({"phase": "user", "action": "moved_to_by_date" if back else "moved_to_by_dest",
                                "from": prior.get("prep_path"), "to": current, "run": run_id})
            entry = {**prior, "prep_path": current or prior.get("prep_path"), "journey": journey}
        else:
            entry = {"content_fingerprint": fp, "prep_path": current, "journey": run_steps}
        if quar:
            # This run's duplicates are added after an earlier run's, never in their place
            # (RUL-log_entry_append_only).
            earlier = (entry.get("deduplicated") or {}).get("quarantined", [])
            entry["deduplicated"] = {"retained": entry.get("prep_path"), "quarantined": earlier + quar}
        photos[fp] = entry
    return photos, warnings


# ==============================================================================
# PLAN & EXECUTE LIFECYCLE
# ==============================================================================

class OperationPlanner:
    @staticmethod
    def _hash_file(filepath: str) -> Fingerprint:
        h = hashlib.sha256()
        with open(filepath, 'rb') as f:
            while chunk := f.read(8192):
                h.update(chunk)
        return Fingerprint(algorithm="sha256", value=h.hexdigest())

    @staticmethod
    def _hash_dict(d: dict) -> Fingerprint:
        s = json.dumps(d, sort_keys=True).encode('utf-8')
        return Fingerprint(algorithm="sha256", value=hashlib.sha256(s).hexdigest())

    @staticmethod
    def compute_index_fingerprint(rows: list) -> str:
        canonical_rows = sorted(rows, key=lambda r: r["relative_path"])
        return OperationPlanner._hash_dict(canonical_rows).value


def current_metadata_dependencies() -> dict:
    """What prep's metadata reading depends on, as of now: the extractor and its version, and the versions
    of the field set, extraction options, metadata schema and camera-group derivation. A plan records it;
    execution recomputes it and refuses the plan if it differs (BLD-prep_dependencies)."""
    from .photos_utils import (get_exiftool_version, FIELD_SET_VERSION, METADATA_SCHEMA_VERSION,
                               CAMERA_GROUP_KEY_VERSION, EXTRACTION_OPTIONS_FINGERPRINT)
    return {
        "extractor": "exiftool",
        "extractor_version": get_exiftool_version(),
        "field_set_version": FIELD_SET_VERSION,
        "extraction_options_fingerprint": EXTRACTION_OPTIONS_FINGERPRINT,
        "metadata_schema_version": METADATA_SCHEMA_VERSION,
        "camera_group_key_version": CAMERA_GROUP_KEY_VERSION,
    }


class PlanValidator:
    @staticmethod
    def validate_plan_preflight(plan: Plan, current_workspace: str):
        """
        Validates the plan just before execution.
        Checks the plan's dependencies and destination clobbering.
        """
        if plan.plan_version != PLAN_SCHEMA_VERSION:
            raise ValueError(f"Stale plan: plan_version {plan.plan_version} is not the supported schema {PLAN_SCHEMA_VERSION}; regenerate the plan.")
        if plan.command != 'prep':
            raise ValueError(f"Plan command '{plan.command}' is not supported by photos-1-prep. Only 'prep' plans are allowed.")
        # A plan is carried out only by the code that made it: another build may plan otherwise, and a plan
        # recording no code is unverifiable, hence stale.
        from .photos_utils import code_fingerprint
        if plan.code_fingerprint != code_fingerprint():
            raise ValueError("Stale plan: it was made by another build of cartographer; regenerate the plan.")
        for op in plan.operations:
            if op.type not in PREP_ALLOWED_OPERATION_TYPES:
                raise ValueError(f"Operation type '{op.type}' is not allowed in photos-1-prep.")
            if op.type == "rmdir" and not _removable_folder(op.source, current_workspace):
                raise ValueError(f"Operation rmdir forbidden on {op.source}: not a folder prep may remove.")
            if op.type in ['move_no_clobber', 'rename_no_clobber', 'quarantine_move']:
                if op.source and op.source.startswith(folder_name('photos_by_dest') + '/'):
                    raise ValueError(f"Operation {op.type} forbidden on source in {folder_name('photos_by_dest')}: {op.source}")
                if op.destination and op.destination.startswith(folder_name('photos_by_dest') + '/'):
                    raise ValueError(f"Operation {op.type} forbidden on destination in {folder_name('photos_by_dest')}: {op.destination}")

        if plan.blockers:
            raise ValueError(f"Plan contains blockers and cannot be executed: {', '.join(plan.blockers)}")

        # The earlier log, which execute's log is merged onto, must be readable now as it was at planning
        # (RUL-unreadable_prep_log_stops): refused before any change, never read as empty at the end.
        read_prior_prep_log(current_workspace)

        # Metadata dependencies: an absent or empty record is unverifiable, hence stale — never skipped.
        current_md_deps = current_metadata_dependencies()
        if plan.metadata_dependencies != current_md_deps:
            raise ValueError(f"Stale plan: metadata dependencies changed since planning. Expected: {plan.metadata_dependencies}, Current: {current_md_deps}")

        # Config staleness: the workspace config must be byte-identical to what the plan
        # was built against (BLD-prep_dependencies). load_or_seed_config and _hash_file both
        # sha256 the raw file bytes, so this compares like-for-like.
        from .photos_utils import config_path
        cfg = config_path(current_workspace)
        if not os.path.exists(cfg):
            raise ValueError("Stale plan: workspace config photos-00-config.json is missing; regenerate the plan.")
        if OperationPlanner._hash_file(cfg).value != plan.config_fingerprint.value:
            raise ValueError("Stale plan: workspace config changed since planning; regenerate the plan.")

        # RootGuard is already in photos-1-prep
        # Prevalidate all implicit file dependencies
        for precond in getattr(plan, 'workspace_file_preconditions', []):
            rel_path = precond.get("relative_path")
            if not rel_path:
                raise ValueError("Stale plan: missing relative_path in workspace_file_preconditions")
            abs_path = RootGuard.resolve_and_check_path(current_workspace, rel_path)
            if not os.path.exists(abs_path):
                raise ValueError(f"Stale plan: dependency missing or changed after planning: {rel_path}")
            stat = os.stat(abs_path)
            if stat.st_size != precond.get("size") or stat.st_mtime_ns != precond.get("mtime_ns"):
                raise ValueError(f"Stale plan: dependency changed after planning: {rel_path}")

        # Prevalidate all db_remove ghost-prune effects before any mutation
        for op in plan.operations:
            if op.type == "db_remove":
                for fx in op.database_effects_after_verification:
                    if fx.get("action") == "remove" and fx.get("preconditions", {}).get("must_be_missing") is True:
                        rel_path = fx.get("relative_path")
                        if not rel_path:
                            raise ValueError("Stale plan: ghost-prune target missing relative_path")
                        abs_path = RootGuard.resolve_and_check_path(current_workspace, rel_path)
                        if os.path.exists(abs_path):
                            raise ValueError(f"Stale plan: ghost-prune target reappeared after planning: {rel_path}")

        # Prevalidate all db_upsert effects before any mutation
        for op in plan.operations:
            if op.type == "db_upsert":
                for fx in op.database_effects_after_verification:
                    if fx.get("action") == "upsert":
                        data = fx.get("data", {})
                        rel_path = data.get("relative_path")
                        if not rel_path:
                            raise ValueError("Stale plan: cache-upsert target missing relative_path")

                        abs_path = RootGuard.resolve_and_check_path(current_workspace, rel_path)
                        if not os.path.exists(abs_path):
                            raise ValueError(f"Stale plan: cache-upsert target missing or changed after planning: {rel_path}")

                        stat = os.stat(abs_path)
                        precond = fx.get("preconditions")
                        if precond:
                            if stat.st_size != precond.get("size") or stat.st_mtime_ns != precond.get("mtime_ns"):
                                raise ValueError(f"Stale plan: cache-upsert target changed after planning: {rel_path}")

        # 1. Reserve and check destinations
        # We simulate the plan sequentially to detect clobbers correctly without false positives from temporary renaming states.
        virtual_fs = set()
        for root, dirs, files in os.walk(current_workspace):
            for file in files:
                virtual_fs.add(os.path.join(root, file).lower())

        for op in plan.operations:
            if op.source and op.destination:
                resolved_src = RootGuard.resolve_and_check_path(current_workspace, op.source)
                resolved_dest = RootGuard.resolve_and_check_path(current_workspace, op.destination)

                if resolved_dest.lower() in virtual_fs and resolved_src.lower() != resolved_dest.lower():
                    # Destination exists and it's not a case-only rename of itself
                    raise ValueError(f"Destination case-insensitive clobber risk: {op.destination}")

                virtual_fs.discard(resolved_src.lower())
                virtual_fs.add(resolved_dest.lower())

            elif op.destination:
                resolved_dest = RootGuard.resolve_and_check_path(current_workspace, op.destination)
                if resolved_dest.lower() in virtual_fs:
                    raise ValueError(f"Destination case-insensitive clobber risk: {op.destination}")
                virtual_fs.add(resolved_dest.lower())

        # 2. Check preconditions (e.g. source file hasn't changed)
        # Only check original files on disk. Intermediate files created by the plan won't exist yet!
        created_in_plan = set()
        checked_sources = set()
        for op in plan.operations:
            if op.destination:
                created_in_plan.add(op.destination)

            if op.source and op.preconditions and op.source not in checked_sources and op.source not in created_in_plan:
                resolved_source = RootGuard.resolve_and_check_path(current_workspace, op.source)
                if not os.path.exists(resolved_source):
                    raise ValueError(f"Precondition failed: source {op.source} is missing.")

                stat = os.stat(resolved_source)
                expected_size = op.preconditions.get('size')
                expected_mtime = op.preconditions.get('mtime_ns')

                if expected_size is not None and stat.st_size != expected_size:
                    raise ValueError(f"Precondition failed: size changed for {op.source}.")
                if expected_mtime is not None and stat.st_mtime_ns != expected_mtime:
                    raise ValueError(f"Precondition failed: mtime changed for {op.source}.")

                checked_sources.add(op.source)

        # 3. Inventory (RUL-new_file_restales_plan): a file that appeared anywhere prep scans since planning is
        # unplanned — the plan neither moves nor records it — so the plan is stale and a new plan
        # incorporates it. (A planned file that vanished already fails its precondition above.)
        current, scan_blockers = _rescan_inventory(current_workspace)
        if scan_blockers:
            raise ValueError(f"Stale plan: the workspace changed since planning: {scan_blockers[0]}")
        appeared = sorted(set(current) - set(plan.inventory))
        if appeared:
            raise ValueError(f"Stale plan: {len(appeared)} file(s) appeared since planning ({_first_few(appeared)}); "
                             "re-plan to include them.")


def _first_few(paths, n=3):
    shown = ", ".join(paths[:n])
    return shown if len(paths) <= n else f"{shown}, and {len(paths) - n} more"


def _rescan_inventory(workspace_root):
    """Re-run prep's inventory scan (the media scan plus the dump dotfiles bound for quarantine) without
    planning anything: (sorted paths, blockers). The plan records the same list as `inventory`."""
    from .photos_utils import load_or_seed_config, guard_path
    load_or_seed_config(workspace_root)
    wf = WorkspacePrepWorkflow(workspace_root, cache=None)
    wf._initializing = not os.path.exists(guard_path(workspace_root))
    files, blockers = [], []
    wf._scan_inventory(files, blockers)
    return sorted(files + wf._collect_dump_dotfiles(blockers)), blockers


class ExecuteRefused(ValueError):
    """Prep's execute stopped before changing anything: its plan failed its checks, or a snapshot it requires was
    not taken. The command ends as a refusal (BLD-exit_statuses)."""


class PruneRefused(RuntimeError):
    """`prune-quarantine` refused its selection, having listed or removed nothing: an age below one day, or a delete
    naming nothing without `--all`. The command ends as a refusal (BLD-exit_statuses)."""


class ExecuteFailed(RuntimeError):
    """Prep's execute began carrying out its plan and did not finish it: an operation failed, or the records that
    close the run could not be written. The command ends as an execution that failed (BLD-exit_statuses)."""


class PlanExecutor:
    def __init__(self, workspace_root: str, workspace_changes=None):
        self.workspace_root = workspace_root
        # The changes by hand the run's check named or accepted, for prep's log (BLD-workspace_changes_logged).
        self.workspace_changes = list(workspace_changes or [])
        from .photos_utils import ProgressCoordinator
        self.coordinator = ProgressCoordinator()

    def execute(self, plan: Plan, journal_path: str = None):
        # A distinct id for this execution run (vs plan.plan_id which identifies the plan);
        # surfaced in the handoff (BLD-handoff_content).
        self.execution_id = f"{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')}-{uuid.uuid4().hex[:6]}"
        # Workspace lifecycle (RUL-initialized_marked_last): if the sentinel is absent this is
        # an INIT run — the plan creates the structure and moves the base dump into 0-sources, and
        # the sentinel is written LAST (below, only on full success), so a crash re-enters init.
        from .photos_utils import guard_path as _guard_path
        self._was_uninitialized = not os.path.exists(_guard_path(self.workspace_root))
        # Read the authoritative workspace config (zfs block, etc.) from photos-00-config.json
        # before applying the plan. (Config-staleness rejection against the plan is Phase 4.)
        from .photos_utils import load_or_seed_config
        load_or_seed_config(self.workspace_root)
        # Per-run journal under the control directory (retained, not overwritten),
        # unless a caller supplies an explicit path.
        if journal_path is None:
            from .photos_utils import journal_path as _journal_path
            journal_path = _journal_path(self.workspace_root, plan.plan_id)
        # The workspace lock is held for the whole run by main() (RUL-lock_through_the_run);
        # execute() does not acquire it (callers that bypass main() — e.g. tests — run lock-free).
        cache = None
        # The state the last execution left, read before anything changes: the log tells a fingerprint taken again
        # from a different file at the path by it (RUL-retake_only_unchanged_file), and this run rewrites it with the
        # state it leaves, whether or not its operations all succeed (RUL-execution_records_state).
        prior_record = read_workspace_record(self.workspace_root)[1]
        self._changing, self._recorded, self._changes_logged = False, False, False
        try:
            # 1. Preflight validation
            self.coordinator.start_phase("executing - preflight validation")
            try:
                PlanValidator.validate_plan_preflight(plan, self.workspace_root)
                if plan.summary and "performance_and_cache" in plan.summary:
                    plan.summary["performance_and_cache"]["dependency_validation_status"] = "success"
                self.coordinator.finish_phase()
            except ValueError as e:
                get_reporter().error(f"Preflight validation failed: {e}", stream="stdout")
                raise ExecuteRefused(str(e)) from e

            # 2. Start Journal (version-stamped so a stale/foreign journal is detectable, BLD-prep_dependencies)
            journal = JournalWriter(journal_path)
            journal.start_journal(plan.plan_id, depends_on={
                "plan_schema_version": plan.plan_version,
                "config_fingerprint": plan.config_fingerprint.value,
                "cache_schema_version": CACHE_SCHEMA_VERSION,
                "fingerprint_algorithm_version": FINGERPRINT_ALGORITHM_VERSION,
            })

            # 3. ZFS Hook (Optional) — pre-mutation snapshot of the workspace dataset (shared helper,
            #    labelled "prep" so it never collides with geotag's "geotag-" snapshot).
            from .photos_utils import take_zfs_snapshot
            snap = take_zfs_snapshot(self.workspace_root, plan.plan_id, "prep")
            if snap is not None:
                if not snap["ok"]:
                    if snap["required"]:
                        journal.finish_journal("aborted_before_mutation")
                        raise ExecuteRefused(f"ZFS snapshot required but failed: {snap['stderr']}")
                    get_reporter().warn(f"Warning: {snap['stderr'] or 'ZFS snapshot failed'}; skipping snapshot.",
                                        stream="stdout")

            # 4. Execute Operations. The preflight above has refused a plan of another command, an operation of a
            #    kind prep does not carry out or one in photos by destination, and a plan holding a blocker.
            self.coordinator.start_phase("executing - applying operations", len(plan.operations))
            # Noted as begun before the first change, so a hard kill's work is recognised by the next check from this
            # plan (BLD-interrupted_run_recognised); the record this run's end writes clears the note.
            note_execution_begun(self.workspace_root, "prep", plan.plan_id)
            self._changing = True

            # Apply all post-verification cache effects as one transaction (BLD-workspace_database): create the
            # cache up front and open a batch; commit once after the loop, roll back on failure
            # (the finally below). The filesystem stays the source of truth either way.
            if cache is None:
                cache = WorkspaceCache(self.workspace_root)
            cache.begin_batch()
            # The database's version row describes the rows this execute leaves (BLD-cache_versions).
            cache.set_meta("cache_schema_version", str(CACHE_SCHEMA_VERSION))
            cache.set_meta("fingerprint_algorithm_version", FINGERPRINT_ALGORITHM_VERSION)

            for op in plan.operations:
                op_started = datetime.now(timezone.utc).isoformat()
                status = "success"
                details = {}

                try:
                    # Media operations: mutate filesystem
                    if op.type == "mkdir":
                        if op.destination:
                            abs_dest = RootGuard.resolve_and_check_path(self.workspace_root, op.destination)
                            os.makedirs(abs_dest, exist_ok=True)
                    elif op.type == "rmdir":
                        # A folder the plan leaves empty is removed only if it is empty now; one that is
                        # not (or cannot be removed) is left, skipped and reported — never emptied.
                        abs_dir = RootGuard.resolve_and_check_path(self.workspace_root, op.source)
                        if not os.path.isdir(abs_dir):
                            status, details["reason"] = "skipped", "already gone"
                        else:
                            try:
                                os.rmdir(abs_dir)
                            except OSError as e:
                                left = sorted(os.listdir(abs_dir)) if os.path.isdir(abs_dir) else []
                                status = "skipped"
                                details["reason"] = (f"still contains: {', '.join(left[:3])}{'…' if len(left) > 3 else ''}"
                                                     if left else f"could not be removed ({e.strerror}) — check write "
                                                     "permission on its parent folder")
                    elif op.type in ["move_no_clobber", "rename_no_clobber", "quarantine_move"]:
                        if op.source and op.destination:
                            abs_src = RootGuard.resolve_and_check_path(self.workspace_root, op.source)
                            abs_dest = RootGuard.resolve_and_check_path(self.workspace_root, op.destination)

                            if not os.path.exists(abs_src):
                                raise FileNotFoundError(f"Source missing: {abs_src}")

                            if op.preconditions:
                                stat = os.stat(abs_src)
                                expected_size = op.preconditions.get('size')
                                expected_mtime = op.preconditions.get('mtime_ns')

                                if expected_size is not None and stat.st_size != expected_size:
                                    raise ValueError(f"Precondition failed: size changed for {op.source}.")
                                if expected_mtime is not None and stat.st_mtime_ns != expected_mtime:
                                    raise ValueError(f"Precondition failed: mtime changed for {op.source}.")

                            # Quarantine records its evidence BEFORE moving the file
                            # (RUL-evidence_before_quarantine): the manifest entry is the only durable
                            # record of WHY a file was quarantined, so writing it first guarantees a
                            # crash never strands a file in quarantine with no record. If the move then
                            # fails/crashes, the file stays at its source and a re-run re-quarantines it
                            # (fresh evidence under a new plan id); the pre-written entry of the
                            # interrupted run becomes a benign, prunable orphan rather than a lost record.
                            if op.type == "quarantine_move":
                                plan_id = op.verification["plan_id"]
                                manifest_dir = os.path.join(self.workspace_root, ".photos-ingest-quarantine", plan_id)
                                manifest_entry = op.verification.copy()
                                manifest_entry["operation_id"] = op.operation_id
                                _append_quarantine_manifest(manifest_dir, manifest_entry)

                            # Atomic, race-free no-clobber: fails (FileExistsError) rather than
                            # overwriting if the destination exists at the moment of the move.
                            os.makedirs(os.path.dirname(abs_dest), exist_ok=True)
                            _move_no_clobber(abs_src, abs_dest)

                        # Apply DB effects
                        if op.database_effects_after_verification:
                            self.coordinator.increment("db_effects_seen", len(op.database_effects_after_verification))
                            if cache is None:
                                cache = WorkspaceCache(self.workspace_root)
                            for fx in op.database_effects_after_verification:
                                if fx.get("action") == "upsert":
                                    cache.upsert_file(fx["data"])
                                    self.coordinator.increment("db_upserts_applied")
                                elif fx.get("action") == "remove":
                                    cache.remove_file(fx["relative_path"])
                                    self.coordinator.increment("db_removes_applied")

                    # Cache-only operations: update SQLite state without mutating media files
                    elif op.type == "db_remove":
                        if op.database_effects_after_verification:
                            self.coordinator.increment("db_effects_seen", len(op.database_effects_after_verification))
                            if cache is None:
                                cache = WorkspaceCache(self.workspace_root)
                            for fx in op.database_effects_after_verification:
                                if fx.get("action") == "remove":
                                    if fx.get("preconditions", {}).get("must_be_missing") is True:
                                        rel_path = fx["relative_path"]
                                        abs_path = RootGuard.resolve_and_check_path(self.workspace_root, rel_path)
                                        if os.path.exists(abs_path):
                                            raise RuntimeError(f"Stale plan: ghost-prune target reappeared before cache remove: {rel_path}")
                                    cache.remove_file(fx["relative_path"])
                                    self.coordinator.increment("db_removes_applied")

                    elif op.type == "db_upsert":
                        if op.database_effects_after_verification:
                            self.coordinator.increment("db_effects_seen", len(op.database_effects_after_verification))
                            if cache is None:
                                cache = WorkspaceCache(self.workspace_root)
                            for fx in op.database_effects_after_verification:
                                if fx.get("action") == "upsert":
                                    rel_path = fx["data"].get("relative_path")
                                    abs_path = RootGuard.resolve_and_check_path(self.workspace_root, rel_path)
                                    if not os.path.exists(abs_path):
                                        raise RuntimeError("Stale plan: file size or mtime changed before cache upsert")
                                    stat = os.stat(abs_path)
                                    if fx.get("preconditions"):
                                        if stat.st_size != fx["preconditions"].get("size") or stat.st_mtime_ns != fx["preconditions"].get("mtime_ns"):
                                            raise RuntimeError("Stale plan: file size or mtime changed before cache upsert")
                                    cache.upsert_file(fx["data"])
                                    self.coordinator.increment("db_upserts_applied")

                    else:
                        raise NotImplementedError(f"Operation primitive {op.type} not yet fully implemented")
                except Exception as e:
                    status = "failed"
                    details["error"] = str(e)

                op_finished = datetime.now(timezone.utc).isoformat()
                journal.add_operation_result(JournalOperationResult(
                    operation_id=op.operation_id,
                    status=status,
                    started_at=op_started,
                    finished_at=op_finished,
                    details=details
                ))
                self.coordinator.increment_completed()

                # Abort further execution on first failure to prevent cascading issues
                if status == "failed":
                    break
            # Commit the batched cache effects once, only when every op was carried out and checked; a
            # failed run's are rolled back (the finally below), leaving the database as the earlier run
            # left it (BLD-database_effects_one_transaction).
            failed_ops = [r for r in journal.journal.operations if r.status == "failed"]
            if not failed_ops:
                cache.commit_batch()
            self.coordinator.finish_phase()

# 5. Finish Journal
            if failed_ops:
                journal.journal.details = getattr(journal.journal, 'details', {})
                journal.save()
                journal.finish_journal("failed_intervention_required")
                raise ExecuteFailed(f"Execution failed; intervention required. See journal. Failed ops: {failed_ops}")
            else:
                journal.finish_journal("success")

                # A folder the plan meant to remove but found not empty, or could not remove, is
                # reported — never left silently.
                _by_id = {o.operation_id: o for o in plan.operations}
                for r in journal.journal.operations:
                    _o = _by_id.get(r.operation_id)
                    if _o is not None and _o.type == "rmdir" and r.status == "skipped" \
                            and r.details.get("reason") != "already gone":
                        get_reporter().warn(f"Warning: left the folder {_o.source}/ in place — {r.details['reason']}")

                # Update summary with db effects
                if plan.summary and "performance_and_cache" in plan.summary:
                    plan.summary["performance_and_cache"]["db_upserts_applied"] = self.coordinator.counters.get("db_upserts_applied", 0)
                    plan.summary["performance_and_cache"]["db_removes_applied"] = self.coordinator.counters.get("db_removes_applied", 0)

                # Generate handoff manifest ONLY if success
                if plan.command == "prep":
                    self.coordinator.start_phase("executing - generating handoff manifest")
                    if cache is None:
                        cache = WorkspaceCache(self.workspace_root)

                    # 1. Gather files and metadata
                    all_files = cache.get_all_files()
                    all_metadata = cache.get_all_metadata()
                    final_files = []
                    camera_groups_acc = {}
                    dest_folders_acc = {}

                    for rel_path, record in all_files.items():
                        # The per-file status reports the media content FINGERPRINT (media is never
                        # byte-hashed). Non-media has no fingerprint and is not applicable.
                        fp_status = "not_applicable"
                        if record.get('content_hash'):
                            fp_status = json.loads(record['content_hash'])['status']

                        if record['media_class'] not in ['image', 'video', 'raw']:
                            fp_status = "not_applicable"

                        folder_class = rel_path.split('/')[0]

                        md_record = all_metadata.get(rel_path)

                        # Accumulate Destination Folders
                        if folder_class == folder_name('photos_by_dest'):
                            dest_folder = os.path.dirname(rel_path)
                            if dest_folder not in dest_folders_acc:
                                dest_folders_acc[dest_folder] = {
                                    "path": dest_folder,
                                    "scanned_files": 0,
                                    "camera_groups": set(),
                                    "has_native_gps": 0,
                                    "missing_gps": 0,
                                    "has_gps_processing_method": 0,
                                    "timestamps": [],
                                    "cache_freshness": empty_cache_freshness_counts()
                                }
                            df = dest_folders_acc[dest_folder]
                            df["scanned_files"] += 1
                            if md_record:
                                cg_key = md_record.get("camera_group_key")
                                if cg_key and cg_key != "unknown":
                                    df["camera_groups"].add(cg_key)

                                plan_status = plan.summary.get("metadata_plan_status", {}).get(rel_path, md_record.get("extraction_status", "metadata_missing"))
                                df["cache_freshness"]["total_files"] += 1
                                df["cache_freshness"][STATUS_TO_CACHE_FRESHNESS_KEY.get(plan_status, "metadata_missing")] += 1

                                if md_record.get("has_native_gps"):
                                    df["has_native_gps"] += 1
                                else:
                                    df["missing_gps"] += 1

                                try:
                                    parsed = json.loads(md_record.get("parsed_json", "{}"))
                                    if parsed.get("GPSProcessingMethod"):
                                        df["has_gps_processing_method"] += 1

                                    ts = parsed.get("selected_source_naive_timestamp")
                                    if ts:
                                        df["timestamps"].append(ts)
                                except Exception:
                                    pass

                        # Accumulate Camera Groups
                        if md_record and record['media_class'] in ['image', 'raw', 'video']:
                            cg_key = md_record.get("camera_group_key", "unknown")
                            if cg_key not in camera_groups_acc:
                                camera_groups_acc[cg_key] = {
                                    "group_key": cg_key,
                                    "files": [],
                                    "file_count": 0,
                                    "has_native_gps": 0,
                                    "missing_gps": 0,
                                    "missing_timestamps": 0,
                                    "timestamps": [],
                                    "identity": {},
                                    "cache_freshness": empty_cache_freshness_counts()
                                }
                            cg = camera_groups_acc[cg_key]
                            cg["files"].append(rel_path)
                            cg["file_count"] += 1
                            try:
                                cg_parsed = json.loads(md_record.get("parsed_json", "{}"))
                            except Exception:
                                cg_parsed = {}
                            # The identity fields are identical across a group by construction
                            # (they compose the key), so capture them once from any member.
                            if not cg["identity"]:
                                cg["identity"] = {f: cg_parsed[f] for f in CAMERA_IDENTITY_FIELDS
                                                  if cg_parsed.get(f) is not None}

                            plan_status = plan.summary.get("metadata_plan_status", {}).get(rel_path, md_record.get("extraction_status", "metadata_missing"))
                            cg["cache_freshness"]["total_files"] += 1
                            cg["cache_freshness"][STATUS_TO_CACHE_FRESHNESS_KEY.get(plan_status, "metadata_missing")] += 1
                            if md_record.get("has_native_gps"):
                                cg["has_native_gps"] += 1
                            else:
                                cg["missing_gps"] += 1

                            if not md_record.get("has_timestamp"):
                                cg["missing_timestamps"] += 1
                            else:
                                ts = cg_parsed.get("selected_source_naive_timestamp")
                                if ts:
                                    cg["timestamps"].append(ts)

                        filtered_record = {k: v for k, v in record.items() if k != "last_seen_ns"}
                        if md_record:
                            filtered_md = {k: v for k, v in md_record.items() if k != "relative_path"}
                            filtered_record["metadata_status"] = filtered_md

                        final_files.append({
                            **filtered_record,
                            "fingerprint_status": fp_status,
                            "folder_class": folder_class
                        })

                    # Real duplicate/conflict evidence from the quarantine ops (BLD-handoff_grouping_facts).
                    # Only a duplicate is recorded as one; a file set aside for another reason is listed apart, with
                    # its kind (RUL-only_duplicates_recorded_as_duplicates).
                    quarantine_evidence = []
                    quarantined_other = []
                    for op in plan.operations:
                        if op.type == "quarantine_move" and (op.verification or {}).get("kind") != "duplicate":
                            v = op.verification or {}
                            quarantined_other.append({"kind": v.get("kind"), "original_path": v.get("original_path"),
                                                      "quarantine_path": v.get("quarantine_path")})
                        elif op.type == "quarantine_move":
                            v = op.verification or {}
                            ev = v.get("duplicate_evidence") or {}
                            retained = v.get("retained_counterpart", "") or ""
                            quarantine_evidence.append({
                                "original_path": v.get("original_path"),
                                "retained_counterpart": retained,
                                "content_hash": ev.get("value"),
                                "hash_strategy": ev.get("strategy"),
                                "quarantine_path": v.get("quarantine_path"),
                                "against": "by-dest" if str(retained).startswith(folder_name('photos_by_dest') + "/") else "mutable",
                            })

                    # Format accumulated summaries
                    _device_groups = CONFIG.get("camera_time_and_timezone_policy", {}).get("device_groups", {}) or {}
                    _phones = _device_groups.get("phones", []) or []
                    _fixed = _device_groups.get("fixed_clock_cameras", []) or []
                    camera_groups = []
                    for k in sorted(camera_groups_acc.keys()):
                        cg = camera_groups_acc[k]
                        timestamps = sorted(cg.pop("timestamps"))
                        cg["earliest_timestamp"] = timestamps[0] if timestamps else None
                        cg["latest_timestamp"] = timestamps[-1] if timestamps else None
                        if "files" in cg:
                            cg["files"] = sorted(cg["files"])
                        cg["contributing_identity_fields"] = cg.pop("identity", {})
                        cg["device_class"] = "phone" if k in _phones else ("fixed_clock" if k in _fixed else "unknown")
                        camera_groups.append(cg)

                    destination_folders = []
                    for k in sorted(dest_folders_acc.keys()):
                        df = dest_folders_acc[k]
                        timestamps = sorted(df.pop("timestamps"))
                        df["earliest_timestamp"] = timestamps[0] if timestamps else None
                        df["latest_timestamp"] = timestamps[-1] if timestamps else None
                        df["camera_groups"] = sorted(list(df["camera_groups"]))
                        df["conflicts_or_duplicates"] = [
                            e for e in quarantine_evidence
                            if str(e["retained_counterpart"]).startswith(k + "/")
                        ]
                        destination_folders.append(df)

                    # Ensure deterministic sorting
                    final_files.sort(key=lambda x: x["relative_path"])

                    cache_fingerprint = OperationPlanner.compute_index_fingerprint(final_files)

                    # End-of-prep transformation log (BLD-prep_log_build): a
                    # per-photo, content-fingerprint-keyed, human-readable record of everything prep
                    # did — complete and self-sufficient even if no later phase runs. Derived from
                    # this run's plan + quarantine evidence, merged onto the prior log carried forward
                    # (incremental, BLD-prep_log_build). Written BEFORE the handoff, which records its hash:
                    # a crash between the two leaves a handoff that does not vouch for the log, so
                    # finalize refuses it and prep's next run rewrites both.
                    from .photos_utils import prep_log_path
                    plp = prep_log_path(self.workspace_root)
                    try:
                        prior_photos = read_prior_prep_log(self.workspace_root)
                    except ValueError as e:
                        raise ExecuteFailed(str(e))
                    log_photos, log_warnings = build_prep_log(
                        prior_photos, plan.operations, cache.get_all_files(),
                        quarantine_evidence, plan.plan_id, prior_record)
                    # Each set-aside JPEG's record names the RAW it was set aside beside, by fingerprint, for geotag
                    # to rename it with that RAW (BLD-set_aside_pair_recorded).
                    _partners = set_aside_partners(log_photos)
                    for rec in final_files:
                        _raw = _partners.get(_fingerprint_value(rec.get("content_hash")))
                        if rec.get("folder_class") == folder_name('redundant_jpgs') and _raw:
                            rec["raw_fingerprint"] = _raw
                    # No per-run metadata at the top level: the log must be byte-identical on a
                    # no-op run (RUL-no_op_run). Run attribution lives per-step (the "run" field). The changes by
                    # hand the run's check named or accepted are added after the earlier runs'
                    # (BLD-workspace_changes_logged) — none on a no-op run.
                    log_obj = {"schema_version": PREP_LOG_SCHEMA_VERSION, "tool": "photos-1-prep",
                               "photos": log_photos,
                               "workspace_changes": read_prior_workspace_changes(self.workspace_root)
                               + [dict(c, run=plan.plan_id) for c in self.workspace_changes]}
                    try:
                        _write_prep_log(plp, log_obj)
                        self._changes_logged = True
                        if plan.summary and "performance_and_cache" in plan.summary:
                            plan.summary["performance_and_cache"]["prep_log_written"] = True
                        for _w in log_warnings:
                            get_reporter().warn(f"  Warning: {_w}")
                    except Exception as e:
                        raise ExecuteFailed(f"Failed to write prep log: {e}")

                    # 2. Re-hash journal
                    journal_hash = OperationPlanner._hash_file(journal_path).value

                    # 3. Create handoff payload
                    md_deps = plan.metadata_dependencies
                    from .photos_utils import get_imagemagick_version as _get_imagemagick_version
                    handoff = {
                        "schema_version": 1,
                        "tool": "photos-1-prep",
                        # Per-run identifiers live in run_metadata, separate from the deterministic
                        # content, so they don't perturb content_fingerprint across no-op re-runs
                        # (RUL-handoff_deterministic).
                        "run_metadata": {"plan_id": plan.plan_id, "execution_id": self.execution_id},
                        "cache_fingerprint": cache_fingerprint,
                        # The folders prep actually scans/organizes — `1-strays` is deliberately EXCLUDED:
                        # strays are abandoned once moved there (written, never re-scanned), so they are
                        # not part of the deterministic content downstream phases depend on (BLD-handoff_content).
                        "folders_scanned": [
                            {"name": n, "mutable": n != folder_name('photos_by_dest')}
                            for n in managed_folder_names(CONFIG)
                        ],
                        "files": final_files,
                        # The format prep named the files in: fixed for the workspace from here
                        # (RUL-format_fixed_once_named).
                        "filename_timestamp_format": CONFIG["filename_timestamp_format"],
                        "camera_groups": camera_groups,
                        "destination_folders": destination_folders,
                        "diagnostics": {
                            "duplicates_or_conflicts": quarantine_evidence,
                            "quarantined_not_duplicates": quarantined_other,
                            "blockers": plan.blockers,
                            "warnings": plan.warnings,
                            "quarantine_footprint": plan.summary.get("quarantine_footprint"),
                        },
                        "depends_on": {
                            "effective_config": {
                                "fingerprint": plan.config_fingerprint.value
                            },
                            "prep_log": {
                                "path": os.path.relpath(plp, self.workspace_root),
                                "sha256": OperationPlanner._hash_file(plp).value
                            },
                            "execution_journal": {
                                "path": os.path.relpath(journal_path, self.workspace_root),
                                "sha256": journal_hash,
                                "status": "success"
                            },
                            "final_workspace_inventory": {
                                "content_fingerprint": cache_fingerprint
                            },
                            "metadata_extractor": {
                                "name": md_deps["extractor"],
                                "version": md_deps["extractor_version"],
                                "field_set_version": md_deps["field_set_version"],
                                "extraction_options_fingerprint": md_deps["extraction_options_fingerprint"],
                                "metadata_schema_version": md_deps["metadata_schema_version"],
                                "camera_group_key_version": md_deps["camera_group_key_version"]
                            },
                            "plan": {
                                "schema_version": plan.plan_version
                            },
                            "cache": {
                                "schema_version": int(cache.get_meta("cache_schema_version")),
                                "fingerprint_algorithm_version": cache.get_meta("fingerprint_algorithm_version"),
                                "image_engine": "imagemagick",
                                "image_engine_version": _get_imagemagick_version()
                            }
                        }
                    }

                    # Write out atomically AND deterministically (RUL-handoff_deterministic, BLD-handoff_content):
                    # route through write_json_artifact (temp → atomic rename, sort_keys) so the handoff bytes are
                    # byte-stable for a given workspace state. Geotag records a json_dependency on
                    # this file's exact bytes, so a non-deterministic dump (the old indent-only
                    # json.dump) could flip its SHA-256 and spuriously restale photos-21/22/23.
                    from .photos_utils import handoff_path, write_json_artifact, handoff_content_fingerprint
                    # The content fingerprint over the deterministic content (excludes run_metadata +
                    # diagnostics + the journal pointer) — geotag depends on THIS, not the volatile
                    # file bytes, so a no-op re-run does not restale it (RUL-run_only_refresh_restales_nothing).
                    handoff["content_fingerprint"] = handoff_content_fingerprint(handoff)
                    target_handoff_path = handoff_path(self.workspace_root)
                    os.makedirs(os.path.dirname(target_handoff_path), exist_ok=True)
                    try:
                        write_json_artifact(target_handoff_path, handoff)
                        # Belt-and-suspenders (RUL-handoff_verified_by_content): the just-written handoff must re-read
                        # to the SAME content_fingerprint, or geotag's recompute would mismatch — which can only
                        # happen if a non-round-trip-stable field crept into the handoff. Fail loudly here
                        # rather than ship a handoff geotag would (silently) treat as forever-stale.
                        with open(target_handoff_path) as _hf:
                            if handoff_content_fingerprint(json.load(_hf)) != handoff["content_fingerprint"]:
                                raise RuntimeError("handoff content_fingerprint is not round-trip stable")
                        if plan.summary and "performance_and_cache" in plan.summary:
                            plan.summary["performance_and_cache"]["handoff_written_after_successful_validation"] = True
                        self.coordinator.finish_phase()
                    except Exception as e:
                        raise ExecuteFailed(f"Failed to write handoff manifest: {e}")
                # End-of-prep DB backup snapshot (BLD-database_images): a transactionally
                # consistent image of the live cache, captured at the same success gate as the
                # handoff and written atomically over the earlier one — VACUUM INTO a temp name, then atomic
                # rename. A failed/interrupted capture leaves the prior snapshot intact. This
                # refreshes prep's OWN snapshot only (never another phase's).
                # The state this run leaves, recorded before the database's image is taken (BLD-workspace_record).
                write_workspace_record(self.workspace_root,
                                       cache_rows=cache.get_all_files() if cache is not None else None)
                self._recorded = True
                if cache is not None:
                    from .photos_utils import prep_db_snapshot_path, write_db_snapshot
                    write_db_snapshot(cache.conn, prep_db_snapshot_path(self.workspace_root))
                    if plan.summary and "performance_and_cache" in plan.summary:
                        plan.summary["performance_and_cache"]["prep_db_snapshot_written"] = True

                # On an INIT run, write the root sentinel LAST — only after every operation and
                # the handoff have succeeded (RUL-initialized_marked_last). Because it is last,
                # a crash anywhere earlier leaves the workspace uninitialized and the next run
                # safely re-enters the init path. No-op on an already-initialized workspace.
                if self._was_uninitialized:
                    guard = _guard_path(self.workspace_root)
                    os.makedirs(os.path.dirname(guard), exist_ok=True)
                    gfd, gtmp = tempfile.mkstemp(dir=os.path.dirname(guard), prefix=".tmp-guard-")
                    with os.fdopen(gfd, 'w') as gf:
                        gf.write(json.dumps({"initialized": True, "tool": "photos-1-prep",
                                             "initialized_by_run": plan.plan_id}))
                    replace_durably(gtmp, guard)

            self.coordinator.print_summary(plan_summary=plan.summary)
        finally:
            if cache is not None:
                # If the apply phase raised before commit_batch, discard the uncommitted
                # cache effects (the filesystem is the source of truth; the next run re-plans).
                if getattr(cache, "_batch_depth", 0) > 0:
                    cache.rollback_batch()
            if self._changing and not self._recorded:
                # A run that changed something and ended short of its end still leaves a state: recorded, so the
                # next run's check does not take this run's own work for a change by hand (RUL-execution_records_state).
                # The changes by hand its check passed are logged first, as a run that finishes logs them: the record
                # no longer shows them, and a cull among them is still to take its set-aside JPEG
                # (BLD-workspace_changes_logged).
                if not self._changes_logged:
                    self._log_changes_of_unfinished_run(plan.plan_id)
                write_workspace_record(self.workspace_root,
                                       cache_rows=cache.get_all_files() if cache is not None else None)
            if cache is not None:
                cache.close()

    def _log_changes_of_unfinished_run(self, run_id):
        """Add this run's changes by hand to `workspace_changes` of prep's log, the rest of the log as it was, for a run
        that ends short of writing the log itself (BLD-workspace_changes_logged). A log that cannot be read is left
        alone: the next plan stops on it (RUL-unreadable_prep_log_stops)."""
        from .photos_utils import prep_log_path
        if not self.workspace_changes:
            return
        plp = prep_log_path(self.workspace_root)
        try:
            read_prior_prep_log(self.workspace_root)
            if os.path.exists(plp):
                with open(plp) as pf:
                    log_obj = json.load(pf)
            else:
                log_obj = {"schema_version": PREP_LOG_SCHEMA_VERSION, "tool": "photos-1-prep", "photos": {}}
            log_obj["workspace_changes"] = (read_prior_workspace_changes(self.workspace_root)
                                            + [dict(c, run=run_id) for c in self.workspace_changes])
            _write_prep_log(plp, log_obj)
        except (OSError, ValueError) as e:
            get_reporter().warn(f"Warning: the changes by hand this run passed could not be added to prep's log ({e}).")


def _write_prep_log(plp, log_obj):
    """Write prep's log over the earlier one durably: a temporary file beside it, then renamed into place."""
    lfd, ltmp = tempfile.mkstemp(dir=os.path.dirname(plp), prefix=".tmp-prep-log-", suffix=".json", text=True)
    try:
        with os.fdopen(lfd, 'w') as lf:
            json.dump(log_obj, lf, indent=2, sort_keys=True)
        replace_durably(ltmp, plp)
    except BaseException:
        if os.path.exists(ltmp):
            try:
                os.remove(ltmp)
            except OSError:
                pass
        raise


class JournalWriter:
    def __init__(self, journal_path: str):
        self.journal_path = journal_path
        self.journal: Optional[Journal] = None

    def start_journal(self, plan_id: str, depends_on: Optional[Dict[str, Any]] = None):
        # A plan executed again keeps the earlier attempt's journal under -NNN, never written over
        # (RUL-prep_journal_kept).
        from .photos_utils import backup_existing_artifact
        backup_existing_artifact(self.journal_path)
        self.journal = Journal(
            journal_version=1,
            plan_id=plan_id,
            started_at=datetime.now(timezone.utc).isoformat(),
            status="started",
            depends_on=depends_on or {}
        )
        self.save()

    def add_operation_result(self, result: JournalOperationResult):
        if self.journal:
            self.journal.operations.append(result)
            self.save()

    def finish_journal(self, status: str):
        if self.journal:
            self.journal.status = status
            self.journal.finished_at = datetime.now(timezone.utc).isoformat()
            self.save()

    def save(self):
        """Replace the journal whole (temporary file, then rename): a crash mid-save leaves the journal as
        it was after the previous operation, never truncated."""
        if self.journal:
            from .photos_utils import _atomic_write_text
            _atomic_write_text(self.journal_path, self.journal.to_json())


class _PlanState:
    """Mutable carrier for plan()'s op-building cluster — the shared state threaded across the
    op-building steps. Its fields ALIAS plan()'s locals (same objects) during the incremental
    migration, so a migrated step (mutating st.X) and a not-yet-migrated inline block (mutating the
    bare local) act on the same object."""
    def __init__(self, operations, current_paths, by_dest_paths, global_destinations, media_mutated_originals):
        self.operations = operations
        self.current_paths = current_paths
        self.by_dest_paths = by_dest_paths
        self.global_destinations = global_destinations
        self.media_mutated_originals = media_mutated_originals


class WorkspacePrepWorkflow:
    def __init__(self, workspace_root: str, cache: WorkspaceCache, workspace_changes=None):
        self.workspace_root = workspace_root
        self.cache = cache
        # The changes by hand the run's check found: a RAW deleted among them takes its set-aside JPEG
        # (BLD-culled_raw_found).
        self.workspace_changes = list(workspace_changes or [])
        self.managed_folders = managed_folder_names(CONFIG)
        from .photos_utils import ProgressCoordinator
        self.coordinator = ProgressCoordinator()
        self._raw_partners = {}             # set-aside JPEG -> its RAW, by fingerprint: read from the log at plan
        self._hand_deleted = {}             # fingerprint -> path of each file a check found deleted by hand

    def _allocate_suffix(self, base: str, ext: str, index: set, start_idx: int = 1,
                         bare_first: bool = False) -> str:
        # Delegates to the shared no-clobber suffix convention (photos_utils.allocate_suffix) so prep's
        # by-date de-collision and the merge phase's library-collision rename can never drift.
        # `bare_first` (RUL-suffix_choice_by_phase): the by-date timestamp naming takes the bare name first;
        # the init-move / extension-normalize callers leave it False (they run only on a real collision).
        return allocate_suffix(base, ext, index, start_idx, bare_first)

    def _flag_dir_symlinks(self, root, dir_names, blockers):
        """Flag any subdirectory symlink encountered during a walk as a forbidden escape. os.walk does
        not descend into them (followlinks=False), so without this they would be silently ignored
        rather than blocked — the spec forbids symlinks among managed files (RUL-no_links)."""
        for dd in dir_names:
            p = os.path.join(root, dd)
            if os.path.islink(p):
                blockers.append(f"Forbidden symlink detected: {os.path.relpath(p, self.workspace_root)}")

    def _file_datetime(self, f):
        """The file's recorded time (shared `recorded_time`: the first of DateTimeOriginal, CreateDate,
        ModifyDate holding a valid time) from its cached metadata, as a naive datetime, or None. Used both
        to pick the by-date `YYYY-MM-DD/` subfolder and to test whether an already-organized file is in
        its conforming day folder."""
        from .photos_utils import recorded_time, parse_naive_time
        md = (f.get('metadata') or {}).get('parsed_json')
        if not md:
            return None
        try:
            parsed = json.loads(md)
        except Exception:
            return None
        return parse_naive_time(recorded_time(parsed)[1])

    def _collect_dump_dotfiles(self, blockers):
        """Hidden (dot-prefixed) files arriving as part of a dump — OS metadata (`.DS_Store`),
        thumbnail caches (`.thumbnails/`), editor temp files — are recoverable junk that should not
        silently litter the workspace. Collect them from the DUMP AREAS so they can be quarantined
        (recoverable, never deleted): the workspace root on an init run, and the `0-sources/` inbox on
        any run. The workspace's own control directories (`.photos-ingest`, `.photos-ingest-quarantine`,
        `.git`) are NEVER touched; managed bands, `1-strays/`, and the read-only `6-photos-by-dest`
        tree are not dump areas and are left alone. A file is "hidden" if its own name is dot-prefixed,
        if any ancestor directory below the dump area is dot-prefixed, or if the whole dump entry it
        came in under is dot-prefixed. A dot-symlink is forbidden like any symlink (flagged, not
        quarantined). Returns workspace-relative file paths. (Hashing/inventory never see these — like
        the exiftool-leftover sweep, they bypass the media pipeline straight to quarantine.)"""
        from .photos_utils import CONTROL_DIR, QUARANTINE_DIR, folder_name, managed_folder_names
        ws = self.workspace_root
        out = []

        def _walk_hidden(root_abs, all_hidden):
            for r, _dirs, fnames in os.walk(root_abs):
                rel_to_root = os.path.relpath(r, root_abs)
                under_hidden = all_hidden or any(
                    part.startswith('.') for part in rel_to_root.split(os.sep) if part not in ('.', ''))
                for fn in fnames:
                    if not (under_hidden or fn.startswith('.')):
                        continue                       # a plain file in a plain dir — the main scan owns it
                    p = os.path.join(r, fn)
                    rel = os.path.relpath(p, ws)
                    if os.path.islink(p):
                        blockers.append(f"Forbidden symlink detected: {rel}")
                    else:
                        out.append(rel)

        # 0-sources inbox (every run): hidden files anywhere under it.
        src = os.path.join(ws, folder_name('sources'))
        if os.path.isdir(src) and not os.path.islink(src):
            _walk_hidden(src, all_hidden=False)

        # Workspace root dump (init run only): hidden root-level entries, and hidden files nested in
        # non-dot dump folders. The control dirs and managed/strays folders are excluded outright.
        if self._initializing:
            skip_top = {CONTROL_DIR, QUARANTINE_DIR, ".git"}
            managed = set(managed_folder_names()) | {folder_name('strays')}
            for f in os.listdir(ws):
                if f in skip_top or f in managed:
                    continue
                p = os.path.join(ws, f)
                if os.path.islink(p):
                    continue                           # symlinks are flagged by the main scan
                if os.path.isdir(p):
                    # A dot dump dir (e.g. `.thumbnails`) -> everything under it is hidden; a plain dump
                    # dir -> only its name-hidden / under-a-dot-subdir files.
                    _walk_hidden(p, all_hidden=f.startswith('.'))
                elif f.startswith('.'):
                    out.append(f)                      # a root-level dump dotfile
        out.sort()
        return out

    def _recognize_carried_moves(self, files, existing_cache, existing_metadata,
                                 current_metadata_context, current_magick_version):
        """Move-aware cache identity (RUL-move_recognized). Recognize a file the user moved from by-date
        into 6-photos-by-dest (or re-sorted between destinations inside by-dest) by a cache-only
        bijective (size, mtime_ns, basename) stat match, and carry its cached hash + metadata forward
        to the new path instead of re-hashing / re-extracting it. By-dest is read-only, so there is no
        filesystem operation: the old (now-missing) row is dropped by ghost-prune and the carried row is
        upserted at the new path. A row is carried whole only if it would be reused where it was — its
        fingerprint taken by this build's method and its metadata fresh (BLD-carried_row). A stale row's move is
        still recognized — an ImageMagick or exiftool change is a reason to check what the row says, not
        to forget whose it is — and the file is read whole at its new path, starting from that row.
        Returns (carried_forward, relocated, moved_unmatched), relocated mapping each such file's new
        path to its old. Pure helper — computes the maps; mutates no plan state."""
        import collections as _collections
        from .photos_utils import is_metadata_cache_fresh, fingerprint_reusable, media_class_for_ext

        def _row_reusable(path, row, md):
            record = {'relative_path': path, 'size': row['size'], 'mtime_ns': row['mtime_ns']}
            if row.get('content_hash'):
                record['content_hash'] = row['content_hash']
                media_class = media_class_for_ext(os.path.splitext(path)[1].lower().lstrip('.'))
                if not fingerprint_reusable(row['content_hash'], media_class, current_magick_version):
                    return False
            return is_metadata_cache_fresh(record, md, current_metadata_context)

        _present = set(files)
        _missing_rows = {p: r for p, r in existing_cache.items() if p not in _present}
        _new_by_dest = [f for f in files
                        if f.startswith(folder_name('photos_by_dest') + '/') and f not in existing_cache]
        _src_idx = _collections.defaultdict(list)
        for _p, _r in _missing_rows.items():
            _src_idx[(_r['size'], _r['mtime_ns'], os.path.basename(_p))].append(_p)
        _tgt_idx = _collections.defaultdict(list)
        _tgt_stat = {}
        for _f in _new_by_dest:
            _st = os.stat(os.path.join(self.workspace_root, _f))
            _tgt_stat[_f] = _st
            _tgt_idx[(_st.st_size, _st.st_mtime_ns, os.path.basename(_f))].append(_f)
        carried_forward = {}  # new_by_dest_path -> {"source": old_path, "db_file": carried_db}
        relocated = {}        # new_by_dest_path -> old_path, for a recognized move whose row is stale
        for _key, _tgts in _tgt_idx.items():
            _srcs = _src_idx.get(_key, [])
            if len(_tgts) == 1 and len(_srcs) == 1:  # bijective unique match only
                _old_path, _new_path = _srcs[0], _tgts[0]
                _old_row = existing_cache[_old_path]
                _old_md = existing_metadata.get(_old_path)
                if not _row_reusable(_old_path, _old_row, _old_md):
                    relocated[_new_path] = _old_path
                    continue
                _st = _tgt_stat[_new_path]
                _carried = dict(_old_row,
                                relative_path=_new_path,
                                size=_st.st_size, mtime_ns=_st.st_mtime_ns, inode=_st.st_ino,
                                last_seen_ns=int(datetime.now(timezone.utc).timestamp() * 1e9))
                _carried["metadata"] = _old_md
                carried_forward[_new_path] = {"source": _old_path, "db_file": _carried}

        # by-dest files that LOOK moved (new under by-dest, uncached) but failed the unique bijective
        # match (ambiguous, basename changed, or stat reset) — they will re-fingerprint. Tagged
        # `moved-unmatched` so this exact, easy-to-miss cause is visible in the re-hash diagnostics.
        moved_unmatched = set(_new_by_dest) - set(carried_forward) - set(relocated)
        return carried_forward, relocated, moved_unmatched

    def _aggregate_worker_results(self, worker_results, metadata_plan_status, blockers, warnings,
                                  unpersisted_prior_plan=False, memo_paths=frozenset()):
        """Sort + aggregate the per-file worker results on the main thread (deterministic). Appends to the
        passed metadata_plan_status / blockers / warnings; emits the re-hash diagnostics (RUL-rehash_explained). Returns
        (all_db_files, db_files, by_dest_files, rehash_summary) — the last is the dict that goes verbatim
        into performance_and_cache. Verbatim lift from plan(); iteration order unchanged."""
        # 1. Collect and sort all worker results by workspace-relative path
        worker_results.sort(key=lambda x: x['relative_path'])

        # 2. Build metadata_plan_status, warnings and db_files sequentially and deterministically on the main thread
        all_db_files = []
        rehash_reasons = {}          # reason -> count, over media files that were re-fingerprinted this run
        rehash_samples = []          # first 5 UNEXPECTED re-hashes (path, reason) — a sample for investigation
        for res in worker_results:   # worker_results is sorted by path, so the sample is deterministic
            rel_path = res["relative_path"]
            metadata_plan_status[rel_path] = res["metadata_plan_status"]
            warnings.extend(res["warnings"])
            if "blockers" in res and res["blockers"]:
                blockers.extend(res["blockers"])
            all_db_files.append(res["db_file"])
            _rr = res.get("rehash_reason")
            if _rr:
                rehash_reasons[_rr] = rehash_reasons.get(_rr, 0) + 1
                if _rr != "new" and len(rehash_samples) < 5:
                    rehash_samples.append((rel_path, _rr))

        # What the decode memo actually SAVED (RUL-rehash_memo_count_reported): an entry the memo offered still has
        # to clear the freshness gate, so entries offered and decodes avoided are different numbers.
        memo_hits = sum(1 for res in worker_results
                        if res.get("cache_reused") and res["relative_path"] in memo_paths)
        if memo_hits:
            get_reporter().log(f"Reused {memo_hits} fingerprint(s) from the previous plan "
                               "(not yet executed, so not in the cache).")

        # Re-hash diagnostics (RUL-rehash_explained): always-on when any media was re-fingerprinted. Split the
        # EXPECTED new-file hashes from previously-cached files that re-hashed, name the reason buckets,
        # and show a small first-N sample of the unexpected ones (a flag would be useless — by the time
        # you know you want it, the re-hash already happened). The full per-reason counts go to the run
        # report (performance_and_cache.rehash_summary).
        _total_rehash = sum(rehash_reasons.values())
        _new_rehash = rehash_reasons.get("new", 0)
        _unexpected_rehash = _total_rehash - _new_rehash
        if _total_rehash:
            _by = ", ".join(f"{k} {v}" for k, v in sorted(rehash_reasons.items()) if k != "new")
            get_reporter().log(
                f"Re-fingerprinted {_total_rehash} media file(s): {_new_rehash} new (expected), "
                + (f"{_unexpected_rehash} previously-cached re-hashed — {_by}." if _unexpected_rehash
                   else "0 previously-cached re-hashed."))
            if rehash_samples:
                get_reporter().log(f"  First {len(rehash_samples)} unexpected re-hash(es) "
                                   "(incomplete — sample for investigation):")
                for _p, _r in rehash_samples:
                    get_reporter().log(f"    {_r}: {_p}")
            # A cache-less re-plan counts every file as `new`, which reads like a first ingest when it
            # is really work being redone. Name the cause instead of leaving the operator to infer it.
            # The decode memo (RUL-plan_memo_kept) normally absorbs this, so by the time the note fires the memo has
            # missed too — it was cleared, or this is the first plan since the memo was introduced.
            if unpersisted_prior_plan and _new_rehash and not memo_hits:
                get_reporter().log(
                    "  These count as new because nothing was carried over: a previous plan exists but "
                    "was never executed, so its fingerprints never reached the cache (only `execute` "
                    "writes it), and the plan memo did not cover them either. Running `execute` makes "
                    "this plan's fingerprints permanent; re-planning first reuses them from the memo.")

        db_files = [f for f in all_db_files if not f['relative_path'].startswith(folder_name('photos_by_dest') + '/')]
        by_dest_files = [f for f in all_db_files if f['relative_path'].startswith(folder_name('photos_by_dest') + '/')]

        rehash_summary = {
            "total": _total_rehash,
            "new_expected": _new_rehash,
            "unexpected": _unexpected_rehash,
            "by_reason": rehash_reasons,
            "sample": [{"path": p, "reason": r} for p, r in rehash_samples],
            "unpersisted_prior_plan": bool(unpersisted_prior_plan),
            "memo_reused": memo_hits,
        }
        return all_db_files, db_files, by_dest_files, rehash_summary

    def _check_band_and_stray_media(self, all_db_files, blockers, warnings):
        """Band-misplacement guard + stray-media detection (RUL-band_misplacement_blocks, RUL-stray_media_hinted).
        Appends to the passed `blockers`/`warnings` lists (and logs the stray notices). Verbatim lift from plan() —
        same iteration order, so the appended order is unchanged."""
        # Band-misplacement guard (RUL-band_misplacement_blocks): photos and videos live in
        # separate bands. A video under the photo bands (5-photos-by-date / 6-photos-by-dest),
        # or an image/raw under the video band (4-videos-by-date), is a hand-introduced break
        # prep never creates itself — hard-block, do not proceed.
        _photo_bands = (folder_name('photos_by_date'), folder_name('photos_by_dest'))
        _video_band = folder_name('videos_by_date')
        for f in all_db_files:
            top = f['relative_path'].split('/')[0]
            mc = f.get('media_class')
            if top in _photo_bands and mc == 'video':
                blockers.append(f"Band misplacement: video under {top}: {f['relative_path']}")
            elif top == _video_band and mc in ('image', 'raw'):
                blockers.append(f"Band misplacement: {mc} under {_video_band}: {f['relative_path']}")

        # Stray-media detection (BLD-stray_media_probe): a dump file prep is about to set aside as a stray
        # (class `other`, in 0-sources) whose extension exiftool reports as image/* or video/* is most
        # likely a media format the workspace's media_extensions config doesn't list. Probe each
        # DISTINCT stray extension once (not per file) and warn — non-blocking — so the operator can add
        # it to media_extensions and re-run to organize those files instead of parking them in 1-strays.
        # On the run that initializes the workspace the dump is still outside the managed folders, bound for
        # 0-sources, so its files are the inbox's too (RUL-stray_media_hinted).
        from .photos_utils import exiftool_mime_type
        _sources_top = folder_name('sources')
        _stray_ext_sample = {}
        for f in all_db_files:
            _top = f['relative_path'].split('/')[0]
            if f.get('media_class') == 'other' and (
                    _top == _sources_top or (self._initializing and _top not in self.managed_folders)):
                e = os.path.splitext(f['relative_path'])[1].lower().lstrip('.')
                if e and e not in _stray_ext_sample:
                    _stray_ext_sample[e] = os.path.join(self.workspace_root, f['relative_path'])
        for e, sample in sorted(_stray_ext_sample.items()):
            mime = exiftool_mime_type(sample)
            if mime and (mime.startswith('image/') or mime.startswith('video/')):
                msg = (f"Dump contains .{e} files that exiftool sees as media ({mime}) but media_extensions "
                       f"config does not list — they will be set aside in {folder_name('strays')}. Add '{e}' (lowercase, no "
                       f"dot) to the right media_extensions class in photos-00-config.json and re-run prep to organize them.")
                warnings.append(msg)
                get_reporter().log(f"  Notice: {msg}")

    def _build_run_report(self, operations, no_op_count, metadata_plan_status, all_db_files,
                          recognized_moves, by_dest_files, blockers, warnings, qf,
                          current_exiftool_version, current_field_set_version):
        """Assemble the user-visible run report (RUL-prep_run_summarised) — pure read-only re-presentation of data
        already on hand (operation/metadata/camera-group/GPS counts). Returns the report dict. Verbatim
        lift from plan(); no state mutated."""
        # User-visible run report (RUL-prep_run_summarised), re-presenting data already on hand.
        import collections as _collections
        _media_op_types = {"mkdir", "move_no_clobber", "rename_no_clobber", "quarantine_move"}
        _q_ops = [op for op in operations if op.type == "quarantine_move"]
        # Each quarantine move is counted by its reason; only a duplicate counts as one (RUL-set_aside_counted_by_reason,
        # RUL-only_duplicates_recorded_as_duplicates).
        _by_reason = _collections.Counter((op.verification or {}).get("kind") for op in _q_ops)
        _dup_ops = [op for op in _q_ops if (op.verification or {}).get("kind") == "duplicate"]
        _dup_by_dest = sum(1 for op in _dup_ops
                           if str((op.verification or {}).get("retained_counterpart", "")).startswith(folder_name('photos_by_dest') + "/"))
        _md_counts = _collections.Counter(metadata_plan_status.values())
        _cg_keys = set()
        _native_gps = 0
        _missing_ts = 0
        for _f in all_db_files:
            _md = _f.get("metadata") or {}
            _k = _md.get("camera_group_key")
            if _k and _k != "unknown":
                _cg_keys.add(_k)
            if _md.get("has_native_gps"):
                _native_gps += 1
            if _md.get("has_timestamp") is False:
                _missing_ts += 1
        report = {
            "media_operations": sum(1 for op in operations if op.type in _media_op_types),
            "cache_operations": sum(1 for op in operations if op.type in ("db_upsert", "db_remove")),
            "no_op_already_correct": no_op_count,
            "recognized_moves": len(recognized_moves),
            "by_dest_files_scanned_read_only": len(by_dest_files),
            "duplicates_against_by_dest": _dup_by_dest,
            "duplicates_against_mutable": len(_dup_ops) - _dup_by_dest,
            "quarantined_by_reason": {k: _by_reason.get(k, 0) for k in QUARANTINE_KINDS},
            "metadata_reused": _md_counts.get("reused_from_cache", 0),
            "metadata_extracted": _md_counts.get("extracted_ok", 0),
            "metadata_carried_forward": _md_counts.get("carried_forward", 0),
            "metadata_failed": _md_counts.get("extraction_failed", 0),
            "metadata_not_applicable": _md_counts.get("not_applicable", 0),
            "camera_groups_found": len(_cg_keys),
            "native_gps_files": _native_gps,
            "missing_timestamp_files": _missing_ts,
            "blockers": len(blockers),
            "warnings": len(warnings),
            "quarantine_footprint": qf,
            "extractor": "exiftool",
            "extractor_version": current_exiftool_version,
            "field_set_version": current_field_set_version,
        }
        return report

    def _recognize_exiftool_leftovers(self, files, warnings):
        """Recognize orphaned exiftool intermediates (`<media>_exiftool_tmp`) left by a hard-killed geotag
        write — pull them out of the media inventory (quarantined below, recoverable) rather than
        mis-inventorying them as `other`. A `<media>_original` is a user's own backup, not a leftover, and
        stays in the inventory as a file of no media class (RUL-user_backup_is_a_stray). A leftover under read-only by-dest is
        left untouched (only warned). Returns (kept_files, exiftool_leftovers). Verbatim lift from plan()."""
        from .photos_utils import exiftool_artifact_base
        _bydest_prefix = folder_name('photos_by_dest') + '/'
        exiftool_leftovers = []
        _kept = []
        for rel in files:
            if exiftool_artifact_base(os.path.basename(rel)) is None:
                _kept.append(rel)
            elif rel.startswith(_bydest_prefix):
                warnings.append(f"Exiftool leftover under read-only by-dest left untouched: {rel}")
            else:
                exiftool_leftovers.append(rel)
        return _kept, exiftool_leftovers

    def _scan_inventory(self, files, blockers):
        """Inventory walk (RUL-no_links, BLD-prep_skip_set): scan the workspace root + managed folders, bar symlinks,
        skip control / strays / gpx subtrees, and build the sorted `files` list; append
        forbidden-symlink and misplaced-entry blockers. Mutates the passed `files` / `blockers`.
        Verbatim lift from plan()."""
        # 0. Inventory, lifecycle guards, symlink check
        _managed_set = set(self.managed_folders)
        _strays = folder_name('strays')
        _sources = folder_name('sources')
        for f in os.listdir(self.workspace_root):
            path = os.path.join(self.workspace_root, f)
            # A symlink at the workspace root is forbidden outright (never followed, RUL-no_links) — flagged
            # BEFORE the isdir-gated skips/walk. os.path.isdir() FOLLOWS a directory symlink, so a
            # dot-named symlink-to-directory would otherwise be skipped as if it were the control dir
            # (.photos-ingest*, which are always real directories, never symlinks), and a non-dot one
            # would let os.walk traverse the link's external target and inventory (and plan a move
            # for) files outside the workspace — a pipeline escape the spec forbids.
            if os.path.islink(path):
                blockers.append(f"Forbidden symlink detected: {f}")
                continue
            is_dir = os.path.isdir(path)
            # Control/skip dirs (.photos-ingest*, .git, any dotdir), the strays tree, and the
            # managed folders are never inventoried as base dumps (managed are walked below).
            if is_dir and (f.startswith('.') or f == _strays or f in _managed_set):
                continue
            # Everything else at the base is a dump entry.
            if not self._initializing:
                # Initialized workspace (RUL-top_level_only_managed): the base holds only the managed folders
                # and hidden entries. Every other root entry — a file, a non-managed folder, a named
                # pipe — is a misplaced dump and a hard block, found by the check every phase shares
                # (below); a hidden file is left where it is, never inventoried.
                continue
            # Init run: inventory this base entry so Stage 1 moves it into 0-sources (no flatten).
            if f.startswith('.'):
                continue  # dotfiles are excluded from the init move (left in place)
            if is_dir:
                for root, _dirs, filenames in os.walk(path):
                    self._flag_dir_symlinks(root, _dirs, blockers)   # nested dir symlinks are forbidden too
                    _dirs[:] = [dd for dd in _dirs if not dd.startswith('.')]
                    for fname in filenames:
                        if fname.startswith('.'):
                            continue
                        fpath = os.path.join(root, fname)
                        rel_path = os.path.relpath(fpath, self.workspace_root)
                        if os.path.islink(fpath):
                            blockers.append(f"Forbidden symlink detected: {rel_path}")
                        else:
                            files.append(rel_path)
            else:
                files.append(f)
        if not self._initializing:
            blockers.extend(f"Misplaced entry at workspace root (dumps belong in {_sources}/): {f}"
                            for f in misplaced_top_level_entries(self.workspace_root))
        for d in self.managed_folders:
            folder_path = os.path.join(self.workspace_root, d)
            # A managed folder that is itself a symlink would let os.walk traverse its external
            # target (the same escape as a root dump symlink) — block it before walking.
            if os.path.islink(folder_path):
                blockers.append(f"Forbidden symlink detected: {d}")
                continue
            if os.path.isdir(folder_path):
                for root, _dirs, filenames in os.walk(folder_path):
                    self._flag_dir_symlinks(root, _dirs, blockers)   # nested dir symlinks are forbidden too
                    # Do not descend into hidden subdirs: their files are not managed media (a non-dot
                    # file inside a `.thumbnails/` is still dump junk). In 0-sources those files are
                    # picked up by _collect_dump_dotfiles for quarantine. Elsewhere a hidden folder holding
                    # files stops the plan, naming it: its files would never be inventoried, fingerprinted,
                    # link-checked or handed on, and would stay behind in the workspace
                    # (RUL-hidden_folder_among_photos_blocks); an empty one is left to the walk as today.
                    # (Matches the init dump-folder walk, which also prunes dot-subdirs.)
                    if d != _sources:
                        for dd in sorted(_dirs):
                            hp = os.path.join(root, dd)
                            if dd.startswith('.') and not os.path.islink(hp) and hidden_folder_holds_files(hp):
                                blockers.append(
                                    f"Hidden folder holding files: {os.path.relpath(hp, self.workspace_root)}. "
                                    "Prep does not read a hidden folder, so the files in it would be neither "
                                    "checked nor handed on, and would stay behind in the workspace. Move them "
                                    "into a folder whose name does not start with a dot (or remove the folder "
                                    "if they are not wanted), then re-plan.")
                    _dirs[:] = [dd for dd in _dirs if not dd.startswith('.')]
                    for fname in filenames:
                        if not fname.startswith('.'):
                            path = os.path.join(root, fname)
                            rel_path = os.path.relpath(path, self.workspace_root)
                            if os.path.islink(path):
                                blockers.append(f"Forbidden symlink detected: {rel_path}")
                            else:
                                files.append(rel_path)
        # A track file is never media (RUL-track_files_block_prep): anywhere prep inventories it, the plan is
        # blocked and the file left where it is — never parked in 1-strays, where clearing the strays
        # would delete it. Tracks belong under gpx_root.
        for rel_path in [f for f in files if is_track_file(f)]:
            blockers.append(f"Track file in the workspace: {rel_path}. Tracks are never processed as "
                            "media — move it under gpx_root, then re-plan.")
            files.remove(rel_path)
        files.sort()

    def _process_file(self, rel_path, _ctx):
        """Per-file worker (runs in the fingerprint/metadata thread pool): decide reuse-vs-rehash via
        the freshness gate, fingerprint media if stale, attach metadata, and return the per-file result.
        Was a closure in plan(); now a method taking the captured plan() locals as a context tuple (all
        read-only inside) so the body is unchanged. (Verbatim lift, de-indented.)"""
        (carried_forward, existing_cache, existing_metadata, current_metadata_context,
         current_exiftool_version, current_magick_version, current_field_set_version,
         current_extraction_options_fingerprint, failed_metadata_folders, metadata_results,
         moved_unmatched) = _ctx
        from .photos_utils import METADATA_SCHEMA_VERSION, CAMERA_GROUP_KEY_VERSION
        if rel_path in carried_forward:
            # Recognized move into by-dest: carry the cached identity forward; do
            # not re-read the file beyond the stat already taken during recognition.
            return {
                "relative_path": rel_path,
                "warnings": [],
                "blockers": [],
                "metadata_plan_status": "carried_forward",
                "db_file": carried_forward[rel_path]["db_file"],
                "cache_reused": True,
            }
        abs_path = os.path.join(self.workspace_root, rel_path)
        stat = os.stat(abs_path)
        ext = os.path.splitext(rel_path)[1].lower().lstrip('.')

        cached = existing_cache.get(rel_path)
        cached_md = existing_metadata.get(rel_path)

        file_record = {
            'relative_path': rel_path,
            'size': stat.st_size,
            'mtime_ns': stat.st_mtime_ns,
        }
        if cached and cached.get('content_hash'):
            file_record['content_hash'] = cached.get('content_hash')

        from .photos_utils import media_class_for_ext
        media_class = media_class_for_ext(ext)

        # Check metadata freshness
        from .photos_utils import is_metadata_cache_fresh
        md_fresh = is_metadata_cache_fresh(file_record, cached_md, current_metadata_context)

        # A cached fingerprint is fresh only when taken by this build's method for its class: the
        # strategy, and for a photo the ImageMagick version (BLD-fingerprint_method).
        from .photos_utils import fingerprint_reusable, fingerprint_valid
        # A media file's cached fingerprint must be one this build would reuse; a file of no media class
        # has none to judge.
        content_hash_fresh = (media_class not in ('image', 'raw', 'video')
                              or fingerprint_reusable((cached or {}).get('content_hash'), media_class,
                                                      current_magick_version))

        result = {
            "relative_path": rel_path,
            "warnings": [],
            "blockers": [],
            "metadata_plan_status": None,
            "db_file": None,
            "cache_reused": False,
            "rehash_reason": None,
        }

        if cached and cached['size'] == stat.st_size and cached['mtime_ns'] == stat.st_mtime_ns and md_fresh and content_hash_fresh:
            # Do not mutate the original cached dict here in the worker thread
            new_cached = dict(cached)
            new_cached['last_seen_ns'] = int(datetime.now(timezone.utc).timestamp() * 1e9)
            new_cached['metadata'] = cached_md

            if media_class == "other":
                result["metadata_plan_status"] = "not_applicable"
            else:
                result["metadata_plan_status"] = "reused_from_cache"

            result["cache_reused"] = True
            result["db_file"] = new_cached
            return result

        # Re-fingerprint diagnostics: this file fell through the freshness gate and (if media) will be
        # decoded. Classify WHY so an unexpected re-hash is visible — `new` (first ingest, expected),
        # else a previously-cached file restaled by `moved-unmatched` (a by-dest move that missed the
        # bijective match), `size-changed`, `mtime-changed`, `metadata-stale` (an exiftool/field-set/
        # camera-group-key stamp moved), `failed-before` (a failed fingerprint, taken again on every
        # run), or `engine-changed` (ImageMagick/ffmpeg version bump).
        if media_class in ('image', 'raw', 'video'):
            if cached is None:
                result["rehash_reason"] = "moved-unmatched" if rel_path in moved_unmatched else "new"
            elif cached['size'] != stat.st_size:
                result["rehash_reason"] = "size-changed"
            elif cached['mtime_ns'] != stat.st_mtime_ns:
                result["rehash_reason"] = "mtime-changed"
            elif not md_fresh:
                result["rehash_reason"] = "metadata-stale"
            elif not fingerprint_valid(cached.get('content_hash')):
                result["rehash_reason"] = "failed-before"
            else:
                result["rehash_reason"] = "engine-changed"

        # Media is identified ONLY by its decoded-content fingerprint (image/raw -> identify,
        # video -> ffmpeg stream MD5). It is never byte-hashed: a whole-file SHA-256 is reserved
        # for artifacts and would change under the EXIF/GPS rewrites a fingerprint must survive
        # (RUL-fingerprint_survives_mutation). Non-media (other-class) is not fingerprinted at all
        # (RUL-strays_leave_no_trace) — it is moved inert to 1-strays and never enters a content decision.
        content_hash_res = None
        if media_class in ['image', 'raw']:
            content_hash_res = ContentHasher.fingerprint_image(abs_path)
        elif media_class == 'video':
            content_hash_res = ContentHasher.fingerprint_video(abs_path)

        parent_folder = os.path.dirname(abs_path)

        if media_class == "other" and parent_folder in failed_metadata_folders:
            # A file of no media class has no metadata prep needs: exiftool failing for its folder leaves it not
            # applicable, never a blocker (RUL-inbox_non_media_never_blocks).
            meta = {"extraction_status": "not_applicable"}
            result["metadata_plan_status"] = "not_applicable"
        elif parent_folder in failed_metadata_folders:
            meta = {}
            meta["extraction_status"] = "extraction_failed"
            meta["extraction_error"] = "folder_metadata_extraction_failed"
            result["metadata_plan_status"] = "extraction_failed"
            result["blockers"].append(
                f"Metadata tool execution failed completely for {rel_path}"
            )
        elif abs_path in metadata_results:
            meta = metadata_results[abs_path]
            if meta.get("extraction_status"):
                result["metadata_plan_status"] = meta["extraction_status"]
            else:
                result["metadata_plan_status"] = "extracted_ok"
        elif media_class != "other" and md_fresh:
            # Fingerprinted again (another method) but its metadata was fresh, so it was not read again:
            # the cached record is reused as it is (RUL-reuse_valid_work).
            meta = None
            result["metadata_plan_status"] = "reused_from_cache"
        else:
            meta = {}
            if media_class == "other":
                meta["extraction_status"] = "not_applicable"
                result["metadata_plan_status"] = "not_applicable"
            else:
                meta["extraction_status"] = "extraction_failed"
                meta["extraction_error"] = "missing_from_exiftool_batch_result"
                result["metadata_plan_status"] = "extraction_failed"
                result["warnings"].append(f"Metadata extraction failed or returned empty for {rel_path}")

        md_record = None
        if meta is None:
            md_record = cached_md
        elif meta.get("extraction_status") == "extraction_failed":
            if cached_md and is_metadata_cache_fresh(file_record, cached_md, current_metadata_context):
                md_record = cached_md
            else:
                md_record = None
                result["blockers"].append(f"Metadata extraction failed and no valid cache exists for {rel_path}")
        else:
            md_record = {
                "extractor": "exiftool",
                "extractor_version": current_exiftool_version,
                "field_set_version": current_field_set_version,
                "extraction_options_fingerprint": current_extraction_options_fingerprint,
                "metadata_schema_version": METADATA_SCHEMA_VERSION,
                "camera_group_key_version": CAMERA_GROUP_KEY_VERSION,
                "camera_group_key": meta.get("camera_group_key", "unknown"),
                "has_native_gps": meta.get("has_native_gps", False),
                "has_timestamp": meta.get("has_timestamp", False),
                "extraction_status": meta.get("extraction_status", "extracted_ok"),
                "extraction_error": meta.get("extraction_error", None),
                "parsed_json": json.dumps(meta),
            }

        result["db_file"] = {
            "relative_path": rel_path,
            "size": stat.st_size,
            "mtime_ns": stat.st_mtime_ns,
            "inode": stat.st_ino,
            "media_class": media_class,
            "content_hash": json.dumps(content_hash_res) if content_hash_res else None,
            "last_seen_ns": int(datetime.now(timezone.utc).timestamp() * 1e9),
            "metadata": md_record
        }
        return result

    def _overlay_plan_memo(self, existing_cache, existing_metadata):
        """Lay the plan-time decode memo (RUL-database_over_memo) UNDER the workspace cache: memo rows fill in paths
        the cache has no row for, cache rows always win. Returns (files, metadata, memo_hit_count).

        Splitting each memo record back into its file part and its metadata-row part means every
        downstream freshness check — the metadata-scan decision and the per-file reuse gate — sees a
        memo-sourced entry in exactly the shape a cache-sourced one has, and applies the same
        size/mtime/engine/field-set tests to it. There is no memo-specific reuse path to keep in sync.

        A memo failure is never fatal: it is an accelerator, so a missing/locked/corrupt memo database
        degrades to the pre-memo behaviour (decode everything) rather than failing the plan."""
        try:
            memo = PlanFingerprintMemo(self.workspace_root)
            try:
                records = memo.load()
            finally:
                memo.close()
        except Exception as e:
            get_reporter().warn(f"Plan memo unavailable ({e}); fingerprints will be recomputed.")
            return existing_cache, existing_metadata, set()

        memo_files, memo_metadata = {}, {}
        for rel_path, rec in records.items():
            if rel_path in existing_cache:
                continue                                  # the executed state is authoritative
            md = rec.get("metadata")
            memo_files[rel_path] = {k: v for k, v in rec.items() if k != "metadata"}
            if md:
                # metadata_cache rows carry the identity columns that upsert_file adds on write; a memo
                # stores the extractor's own dict, so re-attach them or is_metadata_cache_fresh rejects
                # every memo row on a size/mtime/content_hash mismatch against None.
                memo_metadata[rel_path] = dict(md, relative_path=rel_path, size=rec.get("size"),
                                               mtime_ns=rec.get("mtime_ns"),
                                               content_hash=rec.get("content_hash"))
        if not memo_files:
            return existing_cache, existing_metadata, set()
        return ({**memo_files, **existing_cache},
                {**memo_metadata, **existing_metadata},
                set(memo_files))

    def _save_plan_memo(self, all_db_files):
        """Persist this run's observations to the decode memo (RUL-memo_tracks_workspace) and drop paths it no longer
        saw. Every entry is a file observed at its CURRENT path — nothing here anticipates a planned
        move, which is what keeps this outside the plan/execute op model (RUL-planning_writes_only_its_records):
        there is no speculative post-move state on disk, only a record of bytes already read."""
        try:
            memo = PlanFingerprintMemo(self.workspace_root)
            try:
                return memo.replace_all([f for f in all_db_files if f])
            finally:
                memo.close()
        except Exception as e:
            get_reporter().warn(f"Plan memo not written ({e}); the next plan will re-fingerprint.")
            return 0

    def _build_ghost_prunes(self):
        """Build the ghost-prune list — a `remove` cache effect for every cached row whose file no longer
        exists on disk (e.g. by-date sources moved into by-dest, deletions). Returns the list; it is
        emitted later as a db_remove op. Verbatim lift from plan()."""
        ghost_prunes = []
        for row in self.cache.get_all_files().values():
            if not os.path.exists(os.path.join(self.workspace_root, row['relative_path'])):
                ghost_prunes.append({
                    "action": "remove",
                    "relative_path": row['relative_path'],
                    "preconditions": {
                        "must_be_missing": True
                    }
                })
        return ghost_prunes

    def _plan_init_moves(self, st, db_files):
        """Init move (RUL-init_moves_dump_to_inbox): on an init run, move each base-dump entry into 0-sources with
        its structure preserved (no flatten), case-insensitively collision-suffixed. Mutates the
        op-building cluster carried on `st`. Verbatim from plan() with `<cluster> -> st.<cluster>`."""
        for f in db_files:
            rel_path = st.current_paths[f['relative_path']]
            # Init move (RUL-init_moves_dump_to_inbox): move each base-entry file into 0-sources with its
            # STRUCTURE PRESERVED — no flatten (MyDump/sub/a.jpg -> 0-sources/MyDump/sub/a.jpg).
            # On an initialized workspace, base entries are hard-blocked at scan, so this fires
            # only on an init run (no-flatten holds afterward).
            if rel_path.split('/')[0] not in self.managed_folders:
                _sources = folder_name('sources')
                dest_base = os.path.join(_sources, rel_path)
                dest = dest_base
                # Avoid collisions case-insensitively, suffixing within the preserved subdir
                while dest.lower() in [v.lower() for k,v in st.current_paths.items() if k != f['relative_path']] or dest.lower() in st.global_destinations:
                    name, ext = os.path.splitext(os.path.basename(dest))
                    dest = os.path.join(os.path.dirname(dest_base), self._allocate_suffix(name, ext.lstrip('.'), st.global_destinations))

                st.global_destinations.add(dest.lower())
                if rel_path != dest:
                    st.media_mutated_originals.add(f["relative_path"])

                    st.operations.append(Operation(

                        operation_id=f"op-{uuid.uuid4().hex[:8]}",

                        type="move_no_clobber",

                        reason="Initialize: move base dump into sources",
                        source=rel_path,
                        destination=dest,
                        preconditions={"size": f["size"], "mtime_ns": f["mtime_ns"]},
                        verification={},
                        database_effects_after_verification=[{"action": "remove", "relative_path": rel_path}, {"action": "upsert", "data": dict(f, relative_path=dest)}]
                    ))
                    st.current_paths[f['relative_path']] = dest

    def _plan_extension_case(self, st, db_files, quarantined):
        """Extension-case normalization (RUL-media_extension_lowercase): a media file outside the inbox
        whose extension is not lowercase is renamed to lowercase via a two-step temp rename (no-clobber,
        case-insensitive-collision safe). An inbox file takes its lowercase extension in the move that
        files it; a duplicate and a stray keep their names. Mutates the op-building cluster on `st`."""
        _sources_prefix = folder_name('sources') + '/'
        for f in db_files:
            if f['relative_path'] in quarantined or f['media_class'] == 'other':
                continue
            rel_path = st.current_paths[f['relative_path']]
            if rel_path.startswith(_sources_prefix):
                continue
            basename = os.path.basename(rel_path)
            name, ext = os.path.splitext(basename)
            if ext and ext != ext.lower():
                new_ext = ext.lower()
                final_name = f"{name}{new_ext}"
                final_rel = os.path.join(os.path.dirname(rel_path), final_name)

                if final_rel.lower() in [v.lower() for k, v in st.current_paths.items() if k != f['relative_path']] or final_rel.lower() in st.global_destinations:
                    final_name = self._allocate_suffix(name, new_ext.lstrip('.'), st.global_destinations)
                    final_rel = os.path.join(os.path.dirname(rel_path), final_name)

# Generate a deterministic temp name strictly through allocation
                # Create a specific start name
                temp_name_base = f"{name}.__photos_ingest_tmp_extnorm__"
                temp_name = f"{temp_name_base}{new_ext}"
                idx = 1

                # Full physical inventory check for case-insensitive collisions (re-evaluate every plan())
                try:
                    all_physical_lower = getattr(self, "_all_physical_lower_for_plan", None)
                    if all_physical_lower is None:
                        raise AttributeError
                except AttributeError:
                    all_physical_lower = set()
                    for root, _, filenames in os.walk(self.workspace_root):
                        for fn in filenames:
                            all_physical_lower.add(os.path.relpath(os.path.join(root, fn), self.workspace_root).lower())
                    self._all_physical_lower_for_plan = all_physical_lower

                while True:
                    temp_rel = os.path.join(os.path.dirname(rel_path), temp_name)
                    temp_rel_lower = temp_rel.lower()

                    if temp_rel_lower not in [v.lower() for k, v in st.current_paths.items() if k != f['relative_path']] and temp_rel_lower not in st.global_destinations and temp_rel_lower not in all_physical_lower and not os.path.exists(os.path.join(self.workspace_root, temp_rel)):
                        break
                    temp_name = f"{temp_name_base}-{idx:03d}{new_ext}"
                    idx += 1
                self._all_physical_lower_for_plan.add(temp_rel.lower())

                st.global_destinations.add(temp_rel.lower())
                st.global_destinations.add(final_rel.lower())

                if rel_path != final_rel:
                    st.media_mutated_originals.add(f["relative_path"])

                    st.operations.append(Operation(

                        operation_id=f"op-{uuid.uuid4().hex[:8]}",

                        type="rename_no_clobber",
                        reason="Normalize extension case (temp)",
                        source=rel_path,
                        destination=temp_rel,
                        preconditions={"size": f["size"], "mtime_ns": f["mtime_ns"]},
                        verification={},
                        database_effects_after_verification=[{"action": "remove", "relative_path": rel_path}, {"action": "upsert", "data": dict(f, relative_path=temp_rel)}]
                    ))
                    st.media_mutated_originals.add(f["relative_path"])

                    st.operations.append(Operation(

                        operation_id=f"op-{uuid.uuid4().hex[:8]}",

                        type="rename_no_clobber",
                        reason="Normalize extension case",
                        source=temp_rel,
                        destination=final_rel,
                        preconditions={},
                        verification={},
                        database_effects_after_verification=[{"action": "remove", "relative_path": temp_rel}, {"action": "upsert", "data": dict(f, relative_path=final_rel)}]
                    ))
                    st.current_paths[f['relative_path']] = final_rel

    def _plan_redundant_jpgs(self, st, db_files, quarantined):
        """RAW+JPEG pairing (RUL-redundant_jpeg_set_aside): when a RAW and a same-stem JPEG (`.jpg` or `.jpeg`) share an
        inbox folder, move the JPEG — and only the JPEG — to 3-redundant-jpgs (the RAW is the keeper).
        Mutates the op-building cluster on `st`."""
        base_groups = {}
        for f in db_files:
            if f['relative_path'] in quarantined:
                continue
            rel_path = st.current_paths[f['relative_path']]
            basename = os.path.basename(rel_path)
            name, _ = os.path.splitext(basename)
            folder = os.path.dirname(rel_path)
            base_groups.setdefault((folder, name), []).append(f)

        # A redundant JPG is named from its timestamp like a dated file (RUL-redundant_jpg_timestamp_named),
        # against every name already outside the inbox, so it can never collide with one wherever either is moved later.
        _src = folder_name('sources') + "/"
        taken = {os.path.basename(st.current_paths[f['relative_path']]).lower() for f in db_files
                 if f['relative_path'] not in quarantined
                 and not st.current_paths[f['relative_path']].startswith(_src)}

        def is_jpeg(f):
            return (f['media_class'] == 'image'
                    and os.path.splitext(st.current_paths[f['relative_path']])[1].lower() in ('.jpg', '.jpeg'))

        for (folder, name), group in base_groups.items():
            if any(f['media_class'] == 'raw' for f in group):
                # The RAW it is set aside beside, recorded by fingerprint where there is one RAW of that name: geotag
                # renames the JPEG with it (BLD-set_aside_pair_recorded). Beside two, which is its own is not known.
                raws = [f for f in group if f['media_class'] == 'raw']
                raw_fp = _fingerprint_value(raws[0].get('content_hash')) if len(raws) == 1 else None
                for f in group:
                    if is_jpeg(f):
                        rel_path = st.current_paths[f['relative_path']]
                        if rel_path.startswith(_src):
                            base, ext = os.path.splitext(os.path.basename(rel_path))
                            ext = ext.lower()
                            dt = self._file_datetime(f)
                            stem = (dt.strftime(CONFIG["filename_timestamp_format"]) if dt is not None
                                    else untimed_stem(base))
                            dest = os.path.join(folder_name('redundant_jpgs'),
                                                self._allocate_suffix(stem, ext.lstrip('.'), taken, bare_first=True))
                            st.media_mutated_originals.add(f["relative_path"])

                            st.operations.append(Operation(

                                operation_id=f"op-{uuid.uuid4().hex[:8]}",

                                type="move_no_clobber",

                                reason="Separate redundant JPG",
                                source=rel_path,
                                destination=dest,
                                preconditions={"size": f["size"], "mtime_ns": f["mtime_ns"]},
                                verification={"raw_fingerprint": raw_fp} if raw_fp else {},
                                database_effects_after_verification=[{"action": "remove", "relative_path": rel_path}, {"action": "upsert", "data": dict(f, relative_path=dest)}]
                            ))
                            st.current_paths[f['relative_path']] = dest

    def _plan_content_groups(self, db_files, by_dest_files, blockers):
        """Content-fingerprint grouping (RUL-duplicates_quarantined): group media by (content_hash, media_class)
        for dedup, skipping non-media; a missing/invalid fingerprint on a mutable file is a blocker
        (by-dest is exempt). A RAW and its JPEG never share a group: their classes differ. Appends to
        `blockers`; returns content_groups."""
        content_groups = {}
        for f in db_files + by_dest_files:
            # Non-media (other-class) is never fingerprinted and never content-deduplicated; it is
            # routed to 1-strays below. The absence of a fingerprint on `other` is never a blocker
            # (RUL-strays_leave_no_trace).
            if f['media_class'] == 'other':
                continue

            ch_str = f['content_hash']           # media identity == the content fingerprint
            if not ch_str:
                if f['relative_path'].startswith(folder_name('photos_by_dest') + '/'):
                    pass
                else:
                    blockers.append(f"Hash failure for {f['relative_path']}")
                continue

            ch_dict = json.loads(ch_str)
            if ch_dict.get("status") != "valid":
                if f['relative_path'].startswith(folder_name('photos_by_dest') + '/'):
                    pass
                else:
                    blockers.append(f"Hash failure for {f['relative_path']}: {ch_dict.get('error')}")
                continue

            content_groups.setdefault((ch_str, f['media_class']), []).append(f)
        return content_groups

    def _plan_quarantine_artifacts(self, st, exiftool_leftovers, dump_dotfiles, plan_id_for_quarantine):
        """Quarantine the scan-recognized non-media artifacts (BLD-quarantine_layout): orphaned exiftool
        intermediates/backups and hidden dump dotfiles — evidence-before-quarantine quarantine_move
        ops, recoverable, never deleted (no cache row, empty db effects). Mutates st.operations.
        Verbatim from plan() with `operations -> st.operations`."""
        # Quarantine the orphaned exiftool artifacts recognized during the scan. They were never
        # hashed/inventoried (excluded from `files`), so there is no cache row to remove (empty db
        # effects); the move records evidence-before-quarantine like any other quarantine_move, so the
        # artifact is recoverable, never deleted. A precondition stat guards against the file changing
        # between plan and execute.
        for rel in exiftool_leftovers:
            try:
                _st = os.stat(os.path.join(self.workspace_root, rel))
            except OSError:
                continue   # vanished between scan and planning — nothing to quarantine
            q_dest = os.path.join(".photos-ingest-quarantine", plan_id_for_quarantine, rel)
            st.operations.append(Operation(
                operation_id=f"op-{uuid.uuid4().hex[:8]}",
                type="quarantine_move",
                reason="Orphaned exiftool intermediate/backup from an interrupted metadata write",
                source=rel,
                destination=q_dest,
                preconditions={"size": _st.st_size, "mtime_ns": _st.st_mtime_ns},
                verification={"original_path": rel, "quarantine_path": q_dest,
                              "plan_id": plan_id_for_quarantine, "kind": "exiftool_leftover"},
                database_effects_after_verification=[]))

        # Quarantine hidden dump files (same recoverable, evidence-before-quarantine discipline). Like
        # the exiftool leftovers, they never entered the media inventory, so there is no cache row to
        # remove. Their emptied dot-dir skeletons are pruned by _prune_empty_dirs on success.
        for rel in dump_dotfiles:
            try:
                _st = os.stat(os.path.join(self.workspace_root, rel))
            except OSError:
                continue   # vanished between scan and planning — nothing to quarantine
            q_dest = os.path.join(".photos-ingest-quarantine", plan_id_for_quarantine, rel)
            st.operations.append(Operation(
                operation_id=f"op-{uuid.uuid4().hex[:8]}",
                type="quarantine_move",
                reason="Hidden dump file (recoverable; not organized as media)",
                source=rel,
                destination=q_dest,
                preconditions={"size": _st.st_size, "mtime_ns": _st.st_mtime_ns},
                verification={"original_path": rel, "quarantine_path": q_dest,
                              "plan_id": plan_id_for_quarantine, "kind": "dump_dotfile"},
                database_effects_after_verification=[]))

    def _plan_dedup(self, st, content_groups, quarantined, plan_id_for_quarantine):
        """Content dedup (RUL-copy_kept_by_folder): within each (content_hash, media_class) group keep the file in the
        highest-priority folder — where it lies before this plan moves anything, ties by path — and
        quarantine the rest (evidence-before-quarantine quarantine_move, recoverable; by-dest never
        mutated). Records each quarantined rel-path in `quarantined` (every later stage skips it).
        Mutates the op-building cluster on `st`."""
        for (ch_str, mc), group in content_groups.items():
            if len(group) > 1:
                def priority(item):
                    p = st.current_paths.get(item['relative_path'], item['relative_path'])
                    return (dedup_priority(p), p)

                group.sort(key=priority)
                retained = group[0]

                for dup in group[1:]:
                    rel_path = st.current_paths.get(dup['relative_path'], dup['relative_path'])
                    if rel_path.startswith(folder_name('photos_by_dest') + '/'):
                        # Never mutate by-dest
                        continue

                    quarantine_dest = os.path.join(".photos-ingest-quarantine", plan_id_for_quarantine, rel_path)
                    manifest_payload = {
                        "original_path": rel_path,
                        "quarantine_path": quarantine_dest,
                        "retained_counterpart": st.current_paths.get(retained['relative_path'], retained['relative_path']),
                        "duplicate_evidence": json.loads(ch_str),
                        "plan_id": plan_id_for_quarantine,
                        "kind": "duplicate",
                    }
                    st.media_mutated_originals.add(dup["relative_path"])

                    st.operations.append(Operation(

                        operation_id=f"op-{uuid.uuid4().hex[:8]}",

                        type="quarantine_move",
                        reason=f"Duplicate of {st.current_paths.get(retained['relative_path'], retained['relative_path'])}",
                        source=rel_path,
                        destination=quarantine_dest,
                        preconditions={"size": dup["size"], "mtime_ns": dup["mtime_ns"]},
                        verification=manifest_payload,
                        database_effects_after_verification=[{"action": "remove", "relative_path": rel_path}]
                    ))
                    quarantined.add(dup['relative_path'])
                    st.current_paths[dup['relative_path']] = quarantine_dest

    def _plan_culled_raw_jpegs(self, st, all_db_files, db_files, quarantined, plan_id_for_quarantine):
        """A JPEG set aside beside a RAW the user has culled goes to the quarantine (RUL-culled_raw_takes_its_jpeg,
        BLD-culled_raw_found). The RAW is known culled by its fingerprint, never its path: the one the prep log records
        as the JPEG's partner, held by no file prep scanned — inbox and photos by destination included — and found
        deleted by hand by a workspace check. A RAW moved or renamed still holds it; a JPEG whose pair was never
        recorded has no partner; a video is never a partner. Records each JPEG in `quarantined`, so no later stage
        moves it or checks its name. Mutates the op-building cluster on `st`."""
        if not self._raw_partners or not self._hand_deleted:
            return
        held = {_fingerprint_value(f.get('content_hash')) for f in all_db_files} - {None}
        aside = folder_name('redundant_jpgs') + '/'
        for f in db_files:
            if f['relative_path'] in quarantined or f['media_class'] != 'image':
                continue
            rel_path = st.current_paths[f['relative_path']]
            jpeg_fp = _fingerprint_value(f.get('content_hash'))
            raw_fp = self._raw_partners.get(jpeg_fp)
            if not rel_path.startswith(aside) or not raw_fp or raw_fp in held or raw_fp not in self._hand_deleted:
                continue
            q_dest = os.path.join(".photos-ingest-quarantine", plan_id_for_quarantine, rel_path)
            st.media_mutated_originals.add(f["relative_path"])
            st.operations.append(Operation(
                operation_id=f"op-{uuid.uuid4().hex[:8]}",
                type="quarantine_move",
                reason=f"Set-aside JPEG whose RAW was culled ({self._hand_deleted[raw_fp]})",
                source=rel_path,
                destination=q_dest,
                preconditions={"size": f["size"], "mtime_ns": f["mtime_ns"]},
                verification={"original_path": rel_path, "quarantine_path": q_dest, "plan_id": plan_id_for_quarantine,
                              "kind": "raw_culled", "content_fingerprint": jpeg_fp,
                              "raw_path": self._hand_deleted[raw_fp], "raw_fingerprint": raw_fp},
                database_effects_after_verification=[{"action": "remove", "relative_path": rel_path}]))
            quarantined.add(f['relative_path'])
            st.current_paths[f['relative_path']] = q_dest

    def _recorded_filename_format(self):
        """The filename format the last prep execute named this workspace's files in, from the handoff
        it wrote; None when there is none yet."""
        from .photos_utils import handoff_path
        try:
            with open(handoff_path(self.workspace_root)) as f:
                return json.load(f).get("filename_timestamp_format")
        except (OSError, ValueError, AttributeError):
            return None

    def _expected_name(self, rel_path, top, dt):
        """The name a media file outside the inbox should carry when its own does not (BLD-name_check): its
        recorded time in the format, suffix aside, or — with no recorded time, or in the
        missing-metadata folder — its dump name behind the untimed mark. None when the name fits, and
        for a dated file with no time, which prep moves to the missing-metadata folder and names."""
        name = os.path.basename(rel_path)
        base, ext = os.path.splitext(name)
        if top == folder_name('missing_metadata') or dt is None:
            if dt is None and top in (folder_name('photos_by_date'), folder_name('videos_by_date')):
                return None
            return None if name.startswith(UNTIMED_PREFIX) else UNTIMED_PREFIX + name
        stem = dt.strftime(CONFIG["filename_timestamp_format"])
        return None if carries_stem(name, stem) else stem + ext

    def _named_as_its_raw(self, f, rel_path, raw_names):
        """Whether a JPEG in redundant JPEGs carries the name of the RAW it was set aside beside, extension aside: the
        name geotag gives it with its RAW (BLD-name_check). The pair is the prep log's; the RAW is found by its
        fingerprint."""
        partner = self._raw_partners.get(_fingerprint_value(f.get('content_hash')))
        raw = raw_names.get(partner) if partner else None
        return raw is not None and os.path.splitext(os.path.basename(rel_path))[0] == os.path.splitext(raw)[0]

    @staticmethod
    def _not_media_blocker(rel_path):
        """The blocker for a file of no media class outside the inbox (RUL-other_outside_inbox_blocks)."""
        ext = os.path.splitext(rel_path)[1].lower().lstrip('.')
        return (f"File of no media class outside {folder_name('sources')}/: {rel_path}. Move it out of the "
                f"workspace, or add '{ext}' to the right media_extensions class if it is media.")

    @staticmethod
    def _misnamed_blocker(rel_path, expected):
        sources = folder_name('sources')
        return (f"Misnamed file outside {sources}/: {rel_path} — its name is not its recorded time in the "
                f"filename format (expected {expected}). Rename it so, or move it into {sources}/ for prep "
                "to name it.")

    def _plan_organize(self, st, db_files, quarantined, plan_id_for_quarantine, blockers, by_dest_files=()):
        """Organize pass (RUL-photos_by_date, RUL-by_date_in_day_folder): classify each non-quarantined file
        as already-conforming (no-op) vs to-organize vs non-media stray; move strays into 1-strays/<plan-id>/ and place
        each to-organize file into its date band (`band/YYYY-MM-DD/`, or missing-metadata for the
        untimestamped) with a collision-suffixed name. A missing-metadata file that has gained a recorded time
        is to-organize like an inbox file (RUL-time_given_filed_on). Mutates the op-building cluster on `st`.
        Verbatim from plan() with `<cluster> -> st.<cluster>`."""
        global_index = set()
        to_organize = []
        strays_to_move = []
        _managed = set(managed_folder_names(CONFIG))
        _sources = folder_name('sources')
        _sources_prefix = _sources + '/'
        _by_date_bands = {folder_name('photos_by_date'), folder_name('videos_by_date')}
        _missing = folder_name('missing_metadata')
        # The format is fixed once files are named in it (RUL-format_fixed_once_named): a change stops the plan
        # as a whole rather than calling every name it would invalidate misnamed.
        _fmt = CONFIG["filename_timestamp_format"]
        recorded_fmt = self._recorded_filename_format()
        fmt_changed = recorded_fmt is not None and recorded_fmt != _fmt
        named_in_format = 0
        # every file's name outside the inbox by its fingerprint: a set-aside JPEG's RAW is found by it
        raw_names = {_fingerprint_value(f.get('content_hash')): os.path.basename(st.current_paths.get(
                         f['relative_path'], f['relative_path']))
                     for f in list(by_dest_files) + list(db_files) if f.get('media_class') == 'raw'}

        # By-dest is never organized by prep, but its names are checked like the rest.
        for f in by_dest_files:
            if f['media_class'] == 'other':
                blockers.append(self._not_media_blocker(f['relative_path']))
                continue
            dt_named = self._file_datetime(f)
            named_in_format += dt_named is not None
            expected = None if fmt_changed else self._expected_name(f['relative_path'], folder_name('photos_by_dest'), dt_named)
            if expected is not None:
                blockers.append(self._misnamed_blocker(f['relative_path'], expected))

        for f in db_files:
            if f['relative_path'] in quarantined: continue
            rel_path = st.current_paths[f['relative_path']]
            # Non-media (other-class): never date-organized. Move it out of the 0-sources inbox
            # into 1-strays/<plan-id>/<rel> (structure preserved), inert and untracked
            # (RUL-inbox_non_media_to_strays), so 0-sources is left empty. Outside the inbox one stops the plan: an
            # extension taken off the media lists, or a file put there by hand — only the user knows which.
            if f['media_class'] == 'other':
                if rel_path.startswith(_sources_prefix):
                    strays_to_move.append((f, rel_path))
                else:
                    blockers.append(self._not_media_blocker(rel_path))
                continue
            top = rel_path.split('/', 1)[0]
            if top == _missing and self._file_datetime(f) is not None:
                # Given a time by hand where it lies: filed on as a file of a new dump is — its day folder, its
                # timestamp name, a suffix on a clash (RUL-time_given_filed_on). Still untimed, it stays (below).
                to_organize.append((f, rel_path))
                continue
            if top != _sources and top in _managed:    # already in a managed band
                # Outside the inbox every name is one the pipeline gave: one that is not stops the plan.
                dt_named = self._file_datetime(f)
                if dt_named is not None:
                    named_in_format += 1
                expected = None if fmt_changed else self._expected_name(rel_path, top, dt_named)
                if expected is not None and top == folder_name('redundant_jpgs') and \
                        self._named_as_its_raw(f, rel_path, raw_names):
                    expected = None                        # renamed by geotag with its RAW (RUL-set_aside_jpeg_named_as_raw)
                if expected is not None:
                    blockers.append(self._misnamed_blocker(rel_path, expected))
                if top in _by_date_bands:
                    # By-date files must live under a `band/YYYY-MM-DD/` day folder. One already there
                    # (matching its own timestamp) is conforming -> no-op; a flat or wrong-day file is
                    # re-located into the correct day folder (RUL-by_date_in_day_folder).
                    dt = self._file_datetime(f)
                    parts = rel_path.split('/')
                    if dt is not None and len(parts) == 3 and parts[1] == dt.strftime("%Y-%m-%d"):
                        global_index.add(os.path.basename(rel_path).lower())   # conforming day placement
                    else:
                        to_organize.append((f, rel_path))
                else:
                    global_index.add(os.path.basename(rel_path).lower())       # by-dest / missing-metadata / redundant-jpgs
            else:
                to_organize.append((f, rel_path))

        for f, rel_path in strays_to_move:
            rel_under = rel_path[len(_sources_prefix):]
            dest = os.path.join(folder_name('strays'), plan_id_for_quarantine, rel_under)
            st.media_mutated_originals.add(f["relative_path"])
            st.operations.append(Operation(
                operation_id=f"op-{uuid.uuid4().hex[:8]}",
                type="move_no_clobber",
                reason="Move non-media stray out of sources",
                source=rel_path,
                destination=dest,
                preconditions={"size": f["size"], "mtime_ns": f["mtime_ns"]},
                verification={},
                database_effects_after_verification=[{"action": "remove", "relative_path": rel_path}]))
            st.current_paths[f['relative_path']] = dest

        if fmt_changed and named_in_format:
            blockers.append(filename_format_changed(recorded_fmt, _fmt))

        # Pass 2: place each file still in 0-sources (or being re-located from a non-conforming by-date
        # spot) into its destination directory and allocate its name against that directory's index.
        for f, rel_path in to_organize:
            dt = self._file_datetime(f)
            base, ext = os.path.splitext(os.path.basename(rel_path))
            ext = ext.lstrip('.').lower()     # the move that files it lowercases its extension
                                              # (BLD-two_step_case_rename)

            if dt is not None:
                target_folder = (folder_name('videos_by_date') if f['media_class'] == 'video'
                                 else folder_name('photos_by_date'))
                prefix = dt.strftime(CONFIG["filename_timestamp_format"])
                # Group by-date media into a YYYY-MM-DD/ day subfolder; the filename keeps the full
                # timestamp (BLD-day_folder_name). The day uses the date portion of the source-naive timestamp.
                target_dir = os.path.join(target_folder, dt.strftime("%Y-%m-%d"))
            else:
                target_dir = folder_name('missing_metadata')   # untimestamped -> flat, no day folder
                prefix = untimed_stem(base)

            # RUL-suffix_choice_by_phase: the first file at a given timestamp gets the bare name; the -NNN suffix
            # appears only on a genuine collision (matches geotag's final naming, so an uncorrected file's
            # provisional and final names coincide — RUL-uncorrected_keeps_its_name). A same-named file can only be
            # in this same day folder, so the global index is exact (see Pass 1).
            final_name = self._allocate_suffix(prefix, ext, global_index, bare_first=True)
            dest = os.path.join(target_dir, final_name)

            st.media_mutated_originals.add(f["relative_path"])


            st.operations.append(Operation(


                operation_id=f"op-{uuid.uuid4().hex[:8]}",


                type="move_no_clobber",


                reason="Chronological Organization",
                source=rel_path,
                destination=dest,
                preconditions={"size": f["size"], "mtime_ns": f["mtime_ns"]},
                verification={},
                database_effects_after_verification=[{"action": "remove", "relative_path": rel_path}, {"action": "upsert", "data": dict(f, relative_path=dest)}]
            ))
            st.current_paths[f['relative_path']] = dest

    def _plan_folder_removals(self, st):
        """Plan the removal of every folder the plan leaves empty (BLD-folder_removals): under the inbox and the two
        by-date folders, and — on the first run — the dump's own folders at the top level. The plan's
        moves are replayed over the files on disk (hidden ones included); a folder holding none of the
        files left — on disk now, or made by a move on its way — is removed, deepest first. Execute removes
        each only if it is then empty."""
        ws = self.workspace_root
        roots = [folder_name('sources'), folder_name('photos_by_date'), folder_name('videos_by_date')]
        if self._initializing:
            roots += sorted(e for e in os.listdir(ws) if _removable_folder(e, ws))
        present, folders = set(), []
        for root in roots:
            base = os.path.join(ws, root)
            if not os.path.isdir(base) or os.path.islink(base):
                continue
            for dirpath, dirnames, filenames in os.walk(base):
                rel = os.path.relpath(dirpath, ws).replace(os.sep, '/')
                if _removable_folder(rel, ws):
                    folders.append(rel)
                present.update(f"{rel}/{n}" for n in filenames)
                present.update(f"{rel}/{d}" for d in dirnames if os.path.islink(os.path.join(dirpath, d)))
        folders = set(folders)
        for op in st.operations:
            if op.type in ("move_no_clobber", "rename_no_clobber", "quarantine_move"):
                present.discard(op.source)
                present.add(op.destination)
                # a folder a move creates on its way is the plan's too, to remove if left empty
                parts = op.destination.split('/')
                folders.update(f for f in ('/'.join(parts[:i]) for i in range(1, len(parts)))
                               if f.split('/')[0] in roots and _removable_folder(f, ws))
        held = set()
        for p in present:
            parts = p.split('/')
            held.update('/'.join(parts[:i]) for i in range(1, len(parts)))
        for rel in sorted((f for f in folders if f not in held), key=lambda f: (-f.count('/'), f)):
            st.operations.append(Operation(
                operation_id=f"op-{uuid.uuid4().hex[:8]}",
                type="rmdir", reason="Remove a folder the plan leaves empty",
                source=rel, destination=None,
                preconditions={}, verification={}, database_effects_after_verification=[]))

    def _plan_cache_effects(self, st, all_db_files, carried_forward, existing_cache, existing_metadata, current_metadata_context, ghost_prunes,
                            recognized_moves):
        """Cache effects (BLD-database_ops): a db_upsert op reconciling unchanged-state cache rows
        (skipping mutated/carried/relocated files and rows already fresh) plus the recognized-move
        carried upserts, and a db_remove op for the ghost prunes. Mutates st.operations. Verbatim
        from plan() with `<cluster> -> st.<cluster>`."""
        cache_upserts = []
        for f in all_db_files:
            original_rel = f["relative_path"]
            planned_rel = st.current_paths.get(original_rel, original_rel)

            if original_rel in st.media_mutated_originals:
                continue

            # Recognized moves are persisted by their own carried upsert below (the old
            # row is dropped by ghost-prune), not by the unchanged-state reconciliation.
            if original_rel in carried_forward:
                continue

            if planned_rel != original_rel:
                continue

            cached = existing_cache.get(planned_rel)
            cached_md = existing_metadata.get(planned_rel)

            file_record = {
                'relative_path': planned_rel,
                'size': f['size'],
                'mtime_ns': f['mtime_ns']
            }
            if cached and cached.get('content_hash'):
                file_record['content_hash'] = cached.get('content_hash')

            from .photos_utils import is_metadata_cache_fresh
            md_fresh = is_metadata_cache_fresh(file_record, cached_md, current_metadata_context)

            # A moved file's row is not yet at its new path, however like the old one it reads.
            if (planned_rel not in recognized_moves
                    and cached and cached["size"] == f["size"] and cached["mtime_ns"] == f["mtime_ns"]
                    and md_fresh and cached.get("content_hash") == f.get("content_hash")):
                continue

            upsert = {
                "action": "upsert",
                "data": dict(f, relative_path=planned_rel),
                "preconditions": {
                    "size": f["size"],
                    "mtime_ns": f["mtime_ns"]
                }
            }
            if planned_rel in recognized_moves:
                upsert["moved_from"] = recognized_moves[planned_rel]     # the user's move, for prep's log
            cache_upserts.append(upsert)

        # Persist recognized moves: upsert the carried row at the new by-dest path
        # (the file exists there, so the executor's upsert precondition holds). The old
        # row's removal is handled by ghost-prune (its path is now missing).
        for _new_path, _cf in carried_forward.items():
            _cdb = _cf["db_file"]
            cache_upserts.append({
                "action": "upsert",
                "data": _cdb,
                "preconditions": {"size": _cdb["size"], "mtime_ns": _cdb["mtime_ns"]},
                "moved_from": _cf["source"],
            })

        if cache_upserts:
            st.operations.append(Operation(
                operation_id=f"op-{uuid.uuid4().hex[:8]}",
                type="db_upsert",
                reason="Cache unchanged state",
                source=None,
                destination=None,
                preconditions={},
                verification={},
                database_effects_after_verification=cache_upserts
            ))

        # A path a planned move fills again is not a ghost: the move's upsert replaces its row there
        # (a file the user sent back to the inbox, refiled under the name it had).
        _refilled = {op.destination for op in st.operations if op.destination}
        ghost_prunes = [g for g in ghost_prunes if g["relative_path"] not in _refilled]
        if ghost_prunes:
            st.operations.append(Operation(
                operation_id=f"op-{uuid.uuid4().hex[:8]}",
                type="db_remove",
                reason="Prune ghosts",
                source=None,
                destination=None,
                preconditions={},
                verification={},
                database_effects_after_verification=ghost_prunes
            ))

    def plan(self) -> Plan:
        from .photos_utils import cache_schema_mismatch
        _schema_stop = cache_schema_mismatch(self.cache)
        if _schema_stop:
            raise ValueError(_schema_stop)
        operations = []
        blockers = []
        warnings = []
        files = []
        self._all_physical_lower_for_plan = None
        media_mutated_originals = set()

        # Seed photos-00-config.json on first run, then read it as authoritative, before
        # any config-dependent value is used or fingerprinted (BLD-seed_before_fingerprints).
        from .photos_utils import load_or_seed_config
        self._config_fingerprint = load_or_seed_config(self.workspace_root)

        # Workspace lifecycle (BLD-workspace_guard): INITIALIZED once the root sentinel exists.
        from .photos_utils import guard_path, FOLDER_ROLES
        self._initializing = not os.path.exists(guard_path(self.workspace_root))
        if self._initializing:
            # Plan creation of the full 0-6 structure (idempotent mkdir; the sentinel is written
            # last by execute, BLD-workspace_guard).
            for _r in FOLDER_ROLES:
                operations.append(Operation(
                    operation_id=f"op-{uuid.uuid4().hex[:8]}",
                    type="mkdir", reason="Initialize workspace structure",
                    source=None, destination=folder_name(_r),
                    preconditions={}, verification={}, database_effects_after_verification=[]))
        else:
            # Activated workspace (guard present): the full 0-6 structure must already exist. A managed
            # folder that is missing or no longer a directory means the root is non-conforming — almost
            # always an inadvertent user deletion, which may have taken irreplaceable media with it — so
            # HARD STOP rather than silently recreating it and masking the loss.
            _missing = missing_managed_folders(self.workspace_root)
            if _missing:
                blockers.append(
                    "Workspace is non-conforming: missing managed folder(s): "
                    f"{', '.join(_missing)}. They were likely removed inadvertently; restore them (or "
                    "move the remaining media into a fresh workspace) before running — prep will not "
                    "recreate them.")

        # An earlier log that cannot be read stops the plan, naming it (RUL-unreadable_prep_log_stops).
        try:
            # each set-aside JPEG's RAW, by fingerprint: one geotag renamed with its RAW carries its name (BLD-name_check)
            self._raw_partners = set_aside_partners(read_prior_prep_log(self.workspace_root))
        except ValueError as e:
            self._raw_partners = {}
            blockers.append(str(e))
        # the files a check found deleted by hand, by fingerprint: a culled RAW among them (BLD-culled_raw_found)
        self._hand_deleted = hand_deletions(self.workspace_root, self.workspace_changes) if self._raw_partners else {}

        self.coordinator.start_phase("planning - scanning inventory")
        self._scan_inventory(files, blockers)

        # Hidden (dot-prefixed) files arriving in a dump (.DS_Store, .thumbnails/, editor temp) are
        # recoverable junk; collect them from the dump areas (root on init, 0-sources inbox) for
        # quarantine below rather than leaving them to litter the workspace. The control dirs are
        # never touched (see _collect_dump_dotfiles).
        dump_dotfiles = self._collect_dump_dotfiles(blockers)
        # Everything scanned, recorded so execute can refuse a workspace that changed since
        # (RUL-new_file_restales_plan).
        inventory = sorted(files + dump_dotfiles)

        files, exiftool_leftovers = self._recognize_exiftool_leftovers(files, warnings)

        self.coordinator.increment("files_scanned", len(files))
        self.coordinator.finish_phase()

        self.coordinator.start_phase("planning - checking cache freshness")

# Detect forbidden sidecars and block if needed
        forbidden_sidecars = []
        for rel_path in files:
            ext = os.path.splitext(rel_path)[1].lower()
            if ext in ['.xmp', '.dop', '.pp3']:
                forbidden_sidecars.append(rel_path)

        if forbidden_sidecars:
            blockers.append(f"Forbidden sidecar files detected: {', '.join(forbidden_sidecars)}")

        existing_cache = self.cache.get_all_files()
        existing_metadata = self.cache.get_all_metadata()

        # Cache rows are written by EXECUTE only (planning never mutates, RUL-planning_writes_only_its_records). So a
        # plan that was never executed throws its fingerprints away, and the next plan re-hashes everything as `new`
        # — technically accurate per file, but misleading at the run level. An empty cache alongside an
        # existing plan artifact is exactly that situation; record it so the summary (BLD-rehash_summary) can say so.
        from .photos_utils import prep_plan_path
        unpersisted_prior_plan = (not existing_cache) and os.path.exists(prep_plan_path(self.workspace_root))

        from .photos_utils import MetadataReader, ProgressCoordinator, get_exiftool_version, get_imagemagick_version, FIELD_SET_VERSION, EXTRACTION_OPTIONS_FINGERPRINT, METADATA_SCHEMA_VERSION, CAMERA_GROUP_KEY_VERSION
        current_exiftool_version = get_exiftool_version()
        current_magick_version = get_imagemagick_version()
        current_field_set_version = FIELD_SET_VERSION
        current_extraction_options_fingerprint = EXTRACTION_OPTIONS_FINGERPRINT

        current_metadata_context = {
            "extractor": "exiftool",
            "extractor_version": current_exiftool_version,
            "field_set_version": current_field_set_version,
            "extraction_options_fingerprint": current_extraction_options_fingerprint,
            "metadata_schema_version": METADATA_SCHEMA_VERSION,
            "camera_group_key_version": CAMERA_GROUP_KEY_VERSION,
        }

        carried_forward, relocated, moved_unmatched = self._recognize_carried_moves(
            files, existing_cache, existing_metadata, current_metadata_context, current_magick_version)
        # A recognized move whose row is stale: the row follows the file to its new path, where the
        # freshness gate finds what is stale and takes it again (an engine change: the fingerprint; a
        # metadata change: the whole file). The old row is still pruned as a ghost.
        existing_cache, existing_metadata = dict(existing_cache), dict(existing_metadata)
        for _new, _old in relocated.items():
            existing_cache[_new] = dict(existing_cache[_old], relative_path=_new)
            if existing_metadata.get(_old):
                existing_metadata[_new] = dict(existing_metadata[_old], relative_path=_new)
        recognized_moves = {**{n: cf["source"] for n, cf in carried_forward.items()}, **relocated}

        # Plan-time decode memo (RUL-memo_proves_no_move). Move recognition above deliberately runs against the
        # EXECUTED state only — a memo row proves nothing about where prep has put a file — so the
        # overlay happens after it, and cache rows always win over memo rows.
        existing_cache, existing_metadata, memo_paths = self._overlay_plan_memo(
            existing_cache, existing_metadata)

        folders_to_scan = set()
        for f in files:
            if f in carried_forward:
                # Carried-forward move: identity comes from the cache, no re-extract.
                self.coordinator.increment("metadata_hits")
                continue
            cached = existing_cache.get(f)
            cached_md = existing_metadata.get(f)
            stat = os.stat(os.path.join(self.workspace_root, f))
            file_record = {
                'relative_path': f,
                'size': stat.st_size,
                'mtime_ns': stat.st_mtime_ns,
            }
            if cached and cached.get('content_hash'):
                file_record['content_hash'] = cached.get('content_hash')

            from .photos_utils import is_metadata_cache_fresh

            if not cached or not is_metadata_cache_fresh(file_record, cached_md, current_metadata_context):
                folders_to_scan.add(os.path.dirname(os.path.join(self.workspace_root, f)))
                self.coordinator.increment("metadata_misses")
            else:
                self.coordinator.increment("metadata_hits")

        self.coordinator.finish_phase()

        metadata_results = {}
        failed_metadata_folders = set()
        if folders_to_scan:
            self.coordinator.start_phase("planning - extracting metadata", len(folders_to_scan))
            metadata_results, failed_metadata_folders = MetadataReader.read_metadata_concurrently(list(folders_to_scan), max_workers=CONFIG.get("jobs", 4), progress_coordinator=self.coordinator)
            self.coordinator.finish_phase()

        metadata_plan_status = {}

        # The -j/--jobs count is a transient, machine-dependent runtime knob: it is NOT recorded in the
        # plan (nor in the config file, nor the handoff), so a plan is byte-identical across job counts
        # and portable between machines (determinism, RUL-jobs_change_nothing, RUL-jobs_recorded_nowhere).
        # No command option affects what prep plans, so the plan records none.

        self.coordinator.start_phase("planning - hashing files", len(files))

        worker_results = []
        try:
            with concurrent.futures.ThreadPoolExecutor(max_workers=CONFIG.get('jobs', 4)) as executor:
                _ctx = (carried_forward, existing_cache, existing_metadata, current_metadata_context,
                        current_exiftool_version, current_magick_version, current_field_set_version,
                        current_extraction_options_fingerprint, failed_metadata_folders, metadata_results,
                        moved_unmatched)
                future_to_file = {executor.submit(self._process_file, f, _ctx): f for f in files}
                try:
                    for future in concurrent.futures.as_completed(future_to_file):
                        worker_results.append(future.result())
                        self.coordinator.increment_completed()
                except KeyboardInterrupt:
                    # Ctrl-C: drop every not-yet-started future immediately and stop waiting.
                    # The default `with` exit calls shutdown(wait=True), which would instead keep
                    # processing all remaining files before the interrupt could propagate — the
                    # cause of the "have to mash Ctrl-C several times" behavior. In-flight workers
                    # unblock on their own because the exiftool/magick children share our process
                    # group and receive the same SIGINT. Re-raise so main() exits cleanly.
                    executor.shutdown(wait=False, cancel_futures=True)
                    raise
        finally:
            from .photos_utils import PersistentMagickWorker
            PersistentMagickWorker.cleanup_all()       # close the per-thread magick workers

        all_db_files, db_files, by_dest_files, rehash_summary = self._aggregate_worker_results(
            worker_results, metadata_plan_status, blockers, warnings, unpersisted_prior_plan, memo_paths)

        # Remember what this run decoded, so a re-plan before execute does not pay for it again.
        rehash_summary["memo_rows"] = self._save_plan_memo(all_db_files)

        self._check_band_and_stray_media(all_db_files, blockers, warnings)

        self.coordinator.finish_phase()
        self.coordinator.start_phase("planning - building duplicate groups")

        ghost_prunes = self._build_ghost_prunes()





        # The op-building cluster now lives on `st` (the _plan_* steps mutate it in order). operations +
        # media_mutated_originals were seeded at the top of plan(); the path/destination maps are built
        # here and handed straight to the carrier — no separate bare locals to drift out of sync.
        _by_dest_paths = {f['relative_path'].lower(): f['relative_path'] for f in by_dest_files}
        st = _PlanState(
            operations,
            {f['relative_path']: f['relative_path'] for f in db_files},
            _by_dest_paths,
            set(_by_dest_paths),
            media_mutated_originals)
        self._plan_init_moves(st, db_files)

        # Duplicates are set aside first, from where they lie (RUL-duplicate_set_aside_as_found): no later stage moves
        # or renames a file this plan quarantines, so its record keeps its dump path and name.
        content_groups = self._plan_content_groups(db_files, by_dest_files, blockers)

        quarantined = set()
        plan_id_for_quarantine = f"{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')}-{uuid.uuid4().hex[:6]}"

        self._plan_quarantine_artifacts(st, exiftool_leftovers, dump_dotfiles, plan_id_for_quarantine)

        self._plan_dedup(st, content_groups, quarantined, plan_id_for_quarantine)

        self._plan_culled_raw_jpegs(st, all_db_files, db_files, quarantined, plan_id_for_quarantine)

        self._plan_extension_case(st, db_files, quarantined)

        self._plan_redundant_jpgs(st, db_files, quarantined)

        # Pass 1: seed the per-run suffix index with EVERY already-conforming name first, so a
        # newly-organized (or re-located) file never collides with an existing one regardless of
        # iteration order. A single global index suffices even with the new day subfolders: the
        # filename carries the full date (`YYYY-MM-DD--HH-MM-SS`), so two files can share a name only
        # if they share the full timestamp — i.e. the same day, hence the same `YYYY-MM-DD/` folder.
        # Two files in different day folders can never collide on name, so a global basename set is
        # exactly equivalent to per-folder scoping.
        self._plan_organize(st, db_files, quarantined, plan_id_for_quarantine, blockers, by_dest_files)

        self._plan_cache_effects(st, all_db_files, carried_forward, existing_cache, existing_metadata, current_metadata_context, ghost_prunes,
                                 recognized_moves)

        self._plan_folder_removals(st)

        no_op_count = len(files) - len(st.media_mutated_originals)
        from .photos_utils import quarantine_footprint
        qf = quarantine_footprint(self.workspace_root)

        report = self._build_run_report(st.operations, no_op_count, metadata_plan_status, all_db_files,
                                        recognized_moves, by_dest_files, blockers, warnings, qf,
                                        current_exiftool_version, current_field_set_version)

        # Record passive file state dependencies for idempotency and staleness protection
        workspace_file_preconditions = []
        for f in all_db_files:
            if f["relative_path"] not in st.media_mutated_originals:
                workspace_file_preconditions.append({
                    "relative_path": f["relative_path"],
                    "size": f["size"],
                    "mtime_ns": f["mtime_ns"],
                    "role": "by_dest_read_only" if f["relative_path"].startswith(folder_name('photos_by_dest') + "/") else "no_op_prepared"
                })

        # Close the final planning phase ("building duplicate groups") opened above — without this its
        # progress task never gets a FINISH event, so a live observer (the console) would leave the row
        # stuck on screen with a count of 0.
        self.coordinator.finish_phase()

        return Plan(
            plan_version=PLAN_SCHEMA_VERSION,
            plan_id=plan_id_for_quarantine,
            command="prep",
            created_at=datetime.now(timezone.utc).isoformat(),
            config_fingerprint=Fingerprint(algorithm="sha256", value=self._config_fingerprint),
            summary={
            "message": "Prep Plan generated",
            "no_op_files": no_op_count,
            "operations_planned": len(st.operations),
            "recognized_moves": len(recognized_moves),
            "quarantine_footprint": qf,
            "report": report,
            "blockers_found": len(blockers),
            "metadata_plan_status": metadata_plan_status,
            "performance_and_cache": {
                "progress_mode": "quiet" if self.coordinator.quiet else "plain",
                "worker_crashes": self.coordinator.counters.get("worker_crashes", 0),
                "worker_restarts": self.coordinator.counters.get("worker_restarts", 0),
                "metadata_extracted": self.coordinator.counters.get("metadata_extracted", 0),
                "metadata_reused": self.coordinator.counters.get("metadata_hits", 0),
                "metadata_failed": len(failed_metadata_folders) + sum(1 for b in blockers if "Metadata" in b),
                "hashes_computed": self.coordinator.counters.get("hashes_computed", 0),
                "hashes_reused": self.coordinator.counters.get("hashes_reused", 0),
                "hashes_failed": self.coordinator.counters.get("hashes_failed", 0),
                "db_effects_seen": len([fx for op in operations for fx in (op.database_effects_after_verification or [])]),
                "db_upserts_applied": 0,
                "db_removes_applied": 0,
                "dependency_validation_status": "pending",
                "handoff_written_after_successful_validation": False,
                "rehash_summary": rehash_summary,
            }
        },
            blockers=blockers,
            warnings=warnings,
            operations=operations,
            workspace_file_preconditions=workspace_file_preconditions,
            inventory=inventory,
            metadata_dependencies=current_metadata_dependencies(),
            code_fingerprint=code_fingerprint()
        )

def _removable_folder(rel, ws):
    """Whether prep may remove the folder `rel` (workspace-relative) once empty: one under the inbox or a
    by-date folder, or a dump's folder at the top level — never a managed folder itself, the strays
    folder, photos by destination, or a control directory."""
    from .photos_utils import managed_folder_names, CONTROL_DIR, QUARANTINE_DIR
    if not rel or rel.startswith('/') or '..' in rel.split('/'):
        return False
    top = rel.split('/')[0]
    if top in (CONTROL_DIR, QUARANTINE_DIR, ".git", folder_name('strays'), folder_name('photos_by_dest')):
        return False
    if top in (folder_name('sources'), folder_name('photos_by_date'), folder_name('videos_by_date')):
        return '/' in rel
    if top in managed_folder_names():
        return False
    p = os.path.join(ws, rel)
    return os.path.isdir(p) and not os.path.islink(p)


def _parse_plan_id_time(plan_id: str):
    """The quarantine <plan_id> dir name starts with the run's UTC timestamp."""
    ts = plan_id.split('-', 1)[0]
    try:
        return datetime.strptime(ts, "%Y%m%dT%H%M%SZ").replace(tzinfo=timezone.utc)
    except ValueError:
        return None


def _quarantine_dir_footprint(dpath: str):
    files_n = 0
    bytes_n = 0
    for root, _d, fnames in os.walk(dpath):
        for fn in fnames:
            if fn == "manifest.json":
                continue
            try:
                bytes_n += os.path.getsize(os.path.join(root, fn))
                files_n += 1
            except OSError:
                pass
    return files_n, bytes_n


def _prune_record(base, run_dirs, plan_ids, older_than_days, prune_all):
    """The record of a prune that deletes (BLD-prune_record): when, by which selectors, and for each quarantine run
    folder it removes, every file in it with its bytes and what the folder's manifest said (None where it cannot be
    read)."""
    removed = []
    for d in run_dirs:
        dpath = os.path.join(base, d)
        files = []
        for root, dirs, fnames in os.walk(dpath):
            dirs.sort()
            for fn in sorted(fnames):
                rel = os.path.relpath(os.path.join(root, fn), dpath)
                if rel == "manifest.json":
                    continue
                try:
                    size = os.path.getsize(os.path.join(root, fn))
                except OSError:
                    size = None
                files.append({"path": rel, "bytes": size})
        try:
            with open(os.path.join(dpath, "manifest.json")) as mf:
                manifest = json.load(mf)
        except (OSError, ValueError):
            manifest = None
        removed.append({"quarantine_run": d, "files": files, "manifest": manifest})
    return {
        "schema_version": 1,
        "tool": "photos-1-prep",
        "pruned_at": datetime.now(timezone.utc).isoformat(),
        "selectors": {"plan_ids": sorted(plan_ids or []), "older_than_days": older_than_days, "all": bool(prune_all)},
        "removed": removed,
    }


def prune_quarantine(workspace_root, plan_ids=None, older_than_days=None, do_delete=False, prune_all=False):
    """Delete recoverable quarantine — the ONLY operation that ever removes quarantine
    content (RUL-prune_explicit). Default is a non-destructive dry-run; `do_delete`
    (--yes) actually deletes. Selectable by exact plan-id and/or age; deleting with no
    selector requires `prune_all` (--all). Runs under the workspace lock and only ever
    touches `.photos-ingest-quarantine/`, but for the record of what a deleting prune removes
    (`photos-16-prune-record.json`, RUL-prune_recorded)."""
    import shutil
    from datetime import timedelta
    from .photos_utils import quarantine_dir
    reporter = get_reporter()
    base = quarantine_dir(workspace_root)
    if not os.path.isdir(base):
        reporter.log("No quarantine directory; nothing to prune.", stream="stdout")
        return

    # An age below one day would select every dated run — the whole quarantine — while looking like a
    # selector (RUL-prune_age_at_least_one_day). The command line refuses it when parsing; the console reaches
    # here without that parsing, so it is refused here too, before anything is listed or removed.
    if older_than_days is not None and older_than_days < 1:
        raise PruneRefused(f"--older-than-days must be at least 1 (got {older_than_days}); nothing was removed.")

    all_dirs = [e.name for e in os.scandir(base) if e.is_dir()]
    has_selector = bool(plan_ids) or older_than_days is not None
    selected = set()
    if plan_ids:
        for pid in plan_ids:
            if pid in all_dirs:
                selected.add(pid)
            else:
                reporter.warn(f"Warning: plan-id not found in quarantine: {pid}")
    if older_than_days is not None:
        cutoff = datetime.now(timezone.utc) - timedelta(days=older_than_days)
        for d in sorted(all_dirs):
            t = _parse_plan_id_time(d)
            if t is None:
                # Its name gives no age, so age never selects it (RUL-prune_age_at_least_one_day); listed so
                # the user sees it was passed over, and why.
                reporter.log(f"Not selected by age: {d} — its name gives no age", stream="stdout")
            elif t < cutoff:
                selected.add(d)
    if not has_selector:
        selected = set(all_dirs)

    if do_delete and not has_selector and not prune_all:
        raise PruneRefused("Refusing to delete all quarantine without a selector. "
                           "Pass --plan-id / --older-than-days, or --all to confirm.")

    # The workspace lock is held for the whole run by main() (RUL-lock_through_the_run).
    if do_delete and selected:
        # What is about to be deleted, and when, is recorded before anything goes (RUL-prune_recorded); an earlier
        # prune's record is set aside under -NNN, never written over (RUL-prune_record_kept).
        from .photos_utils import prune_record_path, write_versioned_json
        record = _prune_record(base, sorted(selected), plan_ids, older_than_days, prune_all)
        _sha, _prior = write_versioned_json(prune_record_path(workspace_root), record)
        reporter.log(f"Recorded what this prune removes in {os.path.basename(prune_record_path(workspace_root))}"
                     + (f" (the earlier record kept as {os.path.basename(_prior)})" if _prior else "") + ".",
                     stream="stdout")
    total_files = 0
    total_bytes = 0
    for d in sorted(selected):
        files_n, bytes_n = _quarantine_dir_footprint(os.path.join(base, d))
        total_files += files_n
        total_bytes += bytes_n
        reporter.log(f"{'Removing' if do_delete else 'Would remove'} {d}: {files_n} files, {bytes_n} bytes",
                     stream="stdout")
        if do_delete:
            safe = RootGuard.resolve_and_check_path(base, d)  # containment within quarantine
            try:
                shutil.rmtree(safe)
            finally:
                # What prune removes is no change to the next check (RUL-quarantine_changed_only_by_prune): out of the
                # record too, each file gone, a removal cut short midway too. A sealed workspace is checked no more,
                # and its database is left as merge sealed it.
                from .photos_utils import QUARANTINE_DIR, is_sealed
                if not is_sealed(workspace_root):
                    forget_in_workspace_record(workspace_root, [f"{QUARANTINE_DIR}/{d}"])
    reporter.log(f"{'Removed' if do_delete else 'Would remove'} total: "
                 f"{len(selected)} plan(s), {total_files} files, {total_bytes} bytes", stream="stdout")
    if not do_delete:
        reporter.log("(dry-run; pass --yes to delete)", stream="stdout")


import argparse

# One-paragraph role blurb shown by the combined CLI when `photos-cartographer prep` is run with no
# subcommand (and as this phase's standalone --help description).
PREP_BLURB = (
    "prep — get a raw photo dump workspace-ready (phase 1 of 3).\n\n"
    "Consolidates a dump into the managed 0-6 folders: normalizes extensions, de-duplicates and "
    "quarantines (recoverably, never deletes), organizes media by date, records the photos you sort into by-dest, and builds "
    "the hash cache + handoff that the next phase consumes. Planning never mutates; execution applies "
    "only a validated plan. Run inside the workspace directory.\n\n"
    "Next: `photos-cartographer geotag` to place photos in time + on the map."
)


def positive_int(value):
    try:
        parsed = int(value)
    except ValueError:
        raise argparse.ArgumentTypeError("jobs must be a positive integer")
    if parsed < 1:
        raise argparse.ArgumentTypeError("jobs must be a positive integer")
    return parsed


def _days_at_least_one(value):
    """`--older-than-days`: a whole number of days, at least 1 (RUL-prune_age_at_least_one_day). Argparse names
    the option in its refusal."""
    try:
        parsed = int(value)
    except ValueError:
        raise argparse.ArgumentTypeError(f"must be a whole number of days, at least 1 (got {value!r})")
    if parsed < 1:
        raise argparse.ArgumentTypeError(f"must be at least 1 day (got {parsed}); a smaller age would select "
                                         "the whole quarantine")
    return parsed


def add_arguments(parser):
    """Register prep's `-j` + subcommands on `parser` — the top parser when run standalone
    (`python -m cartographer.photos_1_prep`), or the `prep` subparser in the combined
    `photos-cartographer` CLI. Shared so both invocations expose an identical surface."""
    parser.add_argument("-j", "--jobs", type=positive_int, default=4, help="Number of parallel jobs for processing.")
    subparsers = parser.add_subparsers(dest="command")

    # prep command. plan/dry-run/execute all use the canonical control-dir plan path
    # (photos_utils.prep_plan_path) — `plan` writes it, `dry-run`/`execute` read it — so there are no
    # --output/--plan flags: the phase always knows where its plan lives (RUL-plan_at_fixed_place).
    checking = [subparsers.add_parser("plan", help="Generate the prep plan (saved to .photos-ingest/photos-10-prep-plan.json)"),
                subparsers.add_parser("dry-run", help="Validate and display the saved prep plan"),
                subparsers.add_parser("execute", help="Execute the saved prep plan")]
    for p in checking:
        add_accept_changes_argument(p)
    add_zone_table_argument(checking[0])

    prune_parser = subparsers.add_parser("prune-quarantine", help="Delete recoverable quarantine (dry-run by default).")
    prune_parser.add_argument("--plan-id", action="append", dest="plan_ids", help="Quarantine <plan_id> directory to prune (repeatable).")
    prune_parser.add_argument("--older-than-days", type=_days_at_least_one,
                              help="Prune quarantine directories older than N days (N at least 1).")
    prune_parser.add_argument("--all", action="store_true", dest="prune_all", help="Confirm deleting ALL quarantine when no selector is given.")
    prune_parser.add_argument("--yes", action="store_true", help="Actually delete (default is a dry-run that only lists).")
    parser.set_defaults(_run=run, _parser=parser)


def _prep_nothing_to_do(workspace_root, reporter, workspace_changes=()) -> bool:
    """True (after logging a friendly notice) when this workspace is already prepped AND there is
    genuinely nothing to apply — initialized (guard present), `0-sources` holding nothing at all (the
    steady end-state, RUL-prepped_nothing_to_do: an empty folder left there is work, a planned removal), AND no pending by-date→by-dest move the handoff hasn't recorded yet. Both
    `dry-run` and `execute` use this to stop fast (exit 0) instead of replaying a now-stale saved plan
    (which would clobber the files it already moved). Returns False — logging nothing — otherwise.

    The by-dest check is essential: after the user moves photos into `6-photos-by-dest`, `0-sources` is
    empty but prep MUST still re-run to record the move and refresh the handoff (geotag refuses until it
    does). Treating that as "nothing to do" would wedge the mandatory re-prep."""
    from .photos_utils import guard_path, folder_name, handoff_path, by_dest_reprep_pending, prep_log_blocker
    src = os.path.join(workspace_root, folder_name('sources'))
    if not os.path.exists(guard_path(workspace_root)):
        return False
    if os.path.isdir(src) and os.listdir(src):
        return False                    # any entry, a leftover folder too: geotag's gate counts them all
    try:
        with open(handoff_path(workspace_root)) as f:
            _handoff = json.load(f)
    except (OSError, ValueError):
        _handoff = {}
    if by_dest_reprep_pending(workspace_root, _handoff) is not None:
        return False                    # a by-dest move still needs recording — not nothing-to-do
    if prep_log_blocker(workspace_root, _handoff) is not None:
        return False                    # the log is not the one the handoff vouches for — rewrite both
    if workspace_changes or read_workspace_record(workspace_root)[0] is None:
        return False                    # a change by hand since the last execution — a time given in missing
                                        # metadata, a deletion, an acceptance — is this run's to apply and record,
                                        # and so is the first record of the workspace's state (BLD-hand_change_is_work)
    name = folder_name('sources')
    reporter.log(f"Nothing to do: {name} is empty — this workspace is already prepped.", stream="stdout")
    emit_next_step(reporter, f"sort photos into {folder_name('photos_by_dest')}, then `geotag plan` — or "
                             f"add media to {name} and re-run `prep plan` to ingest more.")
    return True


def _emit_first_run_config_notice(workspace_root, plan, reporter):
    """On the FIRST prep plan — the run that seeds `photos-00-config.json` from the built-in defaults —
    prompt the operator (loudly, but advisory, not a blocker) to review and tune the config before
    trusting the plan. The seeded defaults decide how every file is classified; in particular
    `media_extensions` decides what is treated as a photo/video (organized) vs everything else (set
    aside inert in strays), with big downstream consequences. Cites how many files THIS plan would
    sideline as non-media, so the warning is concrete rather than abstract. CLI + console both see it
    (it goes through the shared reporter)."""
    from .photos_utils import folder_name, config_path
    strays = folder_name('strays')
    strays_n = sum(1 for op in plan.operations
                   if op.destination and op.destination.startswith(strays + '/'))
    reporter.warn("")
    reporter.warn("⚠  FIRST RUN — the workspace config was just created with DEFAULT values:")
    reporter.warn(f"     {config_path(workspace_root)}")
    reporter.warn("   These defaults decide how every file is classified. In particular `media_extensions` "
                  f"decides what is treated as a photo/video (organized) vs everything else (set aside "
                  f"inert in {strays}) — wrong defaults silently misfile real media.")
    reporter.warn(f"   This plan would set aside {strays_n} file(s) as non-media into {strays}.")
    if strays_n:
        reporter.warn("   → If any of those are really photos/videos, add their extension to the right "
                      "media_extensions class in the config, then RE-RUN `prep plan`.")
    reporter.warn("   Take a good look at the config now and tune it — it has big consequences downstream "
                  "(time / place / library layout). Then re-run `prep plan` before dry-run / execute.")
    reporter.warn("")


def _zone_table_answer(args, workspace_root, reporter):
    """The answer to the question of downloading the table of countries (BLD-zone_table_question): the one the command
    gives (`--download-zone-table`), else — while the question is unanswered and a person is at a terminal to answer
    it — theirs, asked as y/N; else None. Never asked where no terminal reads the answer: the console gives it with
    the run, and a run with no one to answer goes on with the carried copy (RUL-zone_table_never_stops_prep)."""
    from .photos_utils import zone_table_question_pending, zone_table_question, bundled_zone_table
    from .reporting import TtySink
    given = getattr(args, "download_zone_table", None)
    if given is not None or not zone_table_question_pending(workspace_root):
        return given
    if not (sys.stdin.isatty() and any(isinstance(s, TtySink) for s in reporter.sinks)):
        return None
    reporter.warn(zone_table_question(bundled_zone_table()["tzdata_version"]))
    try:
        said = input("Download it? [y/N] ")
    except EOFError:
        return None
    return "yes" if said.strip().lower() in ("y", "yes") else "no"


def run(args):
    workspace_root = os.getcwd()

    # Scrolling status goes through the reporting seam (cartographer/reporting.py). The active
    # reporter is the module global (default TtySink renders identically to the former direct
    # prints); a caller — tests, the future web console — can inject one before calling run().
    reporter = get_reporter()

    # Workspace lifecycle (BLD-workspace_guard): a workspace is INITIALIZED once the root sentinel
    # photos-00-workspace-guard exists. An uninitialized workspace (no guard) is the deliberate
    # entry point — prep initializes it (plan/execute detect this via guard-absence and create the
    # structure, move the base dump into 0-sources, and write the guard last). So prep does NOT
    # hard-require the sentinel here. A SEALED workspace is refused below (after the lock).

    # The workspace's filesystem, before anything else is done — the lock included, which on a filesystem without
    # locks would read as a run in progress: local (RUL-local_filesystem_checked_first), and doing what cartographer
    # needs of it (RUL-filesystem_requirements_tried).
    from .photos_utils import workspace_filesystem_error
    fs_err = workspace_filesystem_error(workspace_root)
    if fs_err:
        reporter.error(fs_err)
        sys.exit(2)

    # Whole-run workspace lock (RUL-lock_before_reading, RUL-lock_fail_fast): acquired once here, before any
    # scan/plan/dry-run/execute, held for the entire run, released on exit. Fail-fast.
    run_lock = WorkspaceLock(workspace_root)
    if not run_lock.acquire():
        owner = run_lock.read_owner() or {}
        detail = f" (pid {owner.get('pid')}, since {owner.get('started_at')})" if owner else ""
        reporter.error(f"Workspace is locked by an in-progress run{detail}; try again when it finishes.")
        sys.exit(1)
    reporter.log(f"Lock acquired: {run_lock.lock_path}")

    try:
        _run_locked(args, workspace_root, reporter)
    except KeyboardInterrupt:
        # Clean Ctrl-C: planning never mutates and execute is journalled/idempotent, so an
        # interrupted run leaves nothing partially applied. Exit quietly with the conventional
        # 130 instead of dumping a traceback. The `finally` below still releases the lock.
        reporter.log("\nInterrupted; aborting. Nothing was partially applied — safe to rerun.")
        sys.exit(130)
    except Exception as e:
        reporter.error(f"Error: {e}")
        sys.exit(1)
    finally:
        run_lock.release()
        reporter.log("Lock released.")


def _read_saved_plan(pp, reporter) -> Plan:
    """The saved plan a dry run or an execute carries out; one that cannot be read refuses the command, nothing
    changed (BLD-exit_statuses)."""
    try:
        with open(pp, "r") as f:
            return Plan.from_dict(json.load(f))
    except Exception as e:
        reporter.error(f"The saved plan {os.path.basename(pp)} cannot be read ({e}). Nothing was changed.")
        emit_next_step(reporter, "re-run `prep plan` to rebuild the plan.")
        sys.exit(2)


def _shape_blockers(workspace_root) -> list:
    """What is wrong with an initialized workspace's shape, as its top level shows it (RUL-shape_checked_first);
    [] for one not yet initialized, whose first run builds the shape, or one whose configuration cannot be read —
    the plan says that."""
    from .photos_utils import guard_path, config_path, load_config, top_level_links
    if not (os.path.exists(guard_path(workspace_root)) and os.path.exists(config_path(workspace_root))):
        return []
    try:
        load_config(workspace_root)             # the folders are named by the workspace's configuration
    except Exception:
        return []
    out = [f"Forbidden symlink detected: {f}" for f in top_level_links(workspace_root)]
    missing = missing_managed_folders(workspace_root)
    if missing:
        out.append("Workspace is non-conforming: missing managed folder(s): "
                   f"{', '.join(missing)}. They were likely removed inadvertently; restore them (or "
                   "move the remaining media into a fresh workspace) before running — prep will not "
                   "recreate them.")
    out.extend(f"Misplaced entry at workspace root (dumps belong in {folder_name('sources')}/): {f}"
               for f in misplaced_top_level_entries(workspace_root))
    return out


def _check_workspace(args, workspace_root) -> list:
    """Prep's check of the workspace against the state its last execution left (BLD-workspace_check): on an
    initialized workspace whose configuration loads — the folders are known by it — and where a record was written; a
    first run, with none, compares nothing (RUL-first_prep_compares_nothing), and a configuration that cannot be read is
    the plan's to report. Returns the changes this run names in its log; exits 2 on a stop."""
    from .photos_utils import guard_path, load_config
    if not os.path.exists(guard_path(workspace_root)):
        return []
    try:
        load_config(workspace_root)
    except Exception:
        return []
    changes, stop = check_workspace(workspace_root, "prep", args.command, getattr(args, "accept_changes", None),
                                    record_required=False)
    if stop:
        sys.exit(stop)
    return changes


def _run_locked(args, workspace_root, reporter):
    """Prep's command, its workspace lock already held: by `run` above, or by geotag's run when it
    records a sort itself (BLD-geotag_auto_reprep) — one lock for the whole run, taken before anything is read
    (RUL-lock_before_reading)."""
    CONFIG["jobs"] = getattr(args, "jobs", 4)
    # A workspace lies on one filesystem (RUL-workspace_one_filesystem), so every move in it is one rename.
    # Checked on every invocation, prune-quarantine included, before anything else is read or changed — but for
    # the seal, which a command it refuses checks first and reads nothing more (BLD-phases_check_seal).
    from .photos_utils import workspace_volume_error, is_sealed as _is_sealed
    _refused_sealed = args.command in ("plan", "dry-run", "execute") and _is_sealed(workspace_root)
    vol_err = None if _refused_sealed else workspace_volume_error(workspace_root)
    if vol_err:
        reporter.error(vol_err)
        sys.exit(2)

    # Sealed/terminal-workspace guard (RUL-sealed_refuses): a successful
    # merge seals the workspace. Prep then hard-stops and mutates nothing. Applies to the prep
    # operations (plan/dry-run/execute); prune-quarantine is a separate maintenance command.
    from .photos_utils import is_sealed, likely_new_dump, folder_name as _folder_name
    if args.command in ("plan", "dry-run", "execute") and is_sealed(workspace_root):
        reporter.error("Workspace is SEALED (already merged): prep will not run. Nothing was touched.")
        if likely_new_dump(workspace_root):
            reporter.log(f"  A likely new dump is present (at the workspace root or in {_folder_name('sources')}). "
                         "A sealed workspace is final — move new media into a fresh workspace.")
        sys.exit(2)

    # The shape of an initialized workspace, checked before anything is scanned, planned or changed
    # (RUL-shape_checked_first): what the top level alone shows — a link there, a managed folder missing, an
    # entry that does not belong. A link deeper in the tree is found by the scan, which is what finds it.
    if args.command in ("plan", "dry-run", "execute"):
        _shape = _shape_blockers(workspace_root)
        if _shape:
            reporter.error("\nPrep cannot proceed:")
            for b in _shape:
                reporter.error(f"  - {b}")
            reporter.log("Nothing was scanned, planned or changed.")
            sys.exit(2)

    # The workspace as the last execution left it (RUL-workspace_checked_first): compared before anything is
    # scanned, planned or changed, dry runs included; a change no person is expected to make stops the command.
    workspace_changes = []
    if args.command in ("plan", "dry-run", "execute"):
        workspace_changes = _check_workspace(args, workspace_root)

    if args.command == "plan":
        # External-tool preflight (shared contract: decline cleanly, don't crash mid-scan).
        # exiftool is hard-required — planning extracts metadata from every file through it and
        # there is no graceful fallback. magick/ffmpeg are SOFT: their absence degrades content
        # fingerprinting (image/video files are reported fingerprint-failed) but does not abort,
        # so they are a warning, not a blocker.
        from .photos_utils import missing_tools
        miss = missing_tools(["exiftool"])
        if miss:
            reporter.error(f"Required external tool not found on PATH: {', '.join(miss)}. "
                           "Install exiftool and re-run `photos-cartographer prep plan`.")
            sys.exit(2)                                     # a refusal (BLD-exit_statuses)
        soft = missing_tools(["magick", "ffmpeg"])
        if soft:
            reporter.warn(f"Warning: {', '.join(soft)} not found on PATH — content fingerprinting will be "
                          "degraded (affected files reported as fingerprint-failed): "
                          "magick→images, ffmpeg→videos.")

        # Whether the workspace config already existed BEFORE this plan — `plan()` seeds it from
        # defaults on first run, so a previously-absent config means this is the first plan and the
        # operator should review the (default) config before trusting the plan (notice below).
        from .photos_utils import config_path as _config_path
        _config_was_seeded = not os.path.exists(_config_path(workspace_root))

        # Where the host's zone database has no table of countries, the user is asked — once, before anything is
        # downloaded — whether to download it (BLD-zone_table_question); asked here, before the scan, so the answer
        # is not waited for at its end. Settled once the plan is saved, the control directory then there.
        _zone_answer = _zone_table_answer(args, workspace_root, reporter)

        cache = WorkspaceCache(workspace_root, read_only=True)
        # A database of another schema is never migrated: the plan is refused, nothing planned (BLD-exit_statuses).
        from .photos_utils import cache_schema_mismatch
        _schema_stop = cache_schema_mismatch(cache)
        if _schema_stop:
            cache.close()
            reporter.error(_schema_stop)
            sys.exit(2)
        workflow = WorkspacePrepWorkflow(workspace_root, cache, workspace_changes=workspace_changes)
        plan = workflow.plan()
        cache.close()

        _qf = plan.summary.get("quarantine_footprint", {}) or {}
        reporter.log(f"Quarantine footprint: {_qf.get('total_files', 0)} files, "
                     f"{_qf.get('total_bytes', 0)} bytes across {_qf.get('plan_id_dirs', 0)} plan(s).")

        # Auto-save to the canonical control-dir path; a prior plan is backed up under an
        # incremental -NNN suffix (never clobbered), and we tell the operator both locations so
        # the plan can be reviewed without hunting for it.
        from .photos_utils import prep_plan_path, write_versioned_json
        pp = prep_plan_path(workspace_root)
        _sha, _bak = write_versioned_json(pp, asdict(plan))
        reporter.log(f"Plan saved to {pp}", stream="stdout")
        if _bak:
            reporter.log(f"  Previous plan backed up to {_bak}", stream="stdout")
        from .photos_utils import settle_zone_table
        settle_zone_table(workspace_root, _zone_answer, reporter)

        # First plan on this workspace: the config was just seeded with defaults — prompt the
        # operator to review/tune it (esp. media_extensions) before trusting the plan. Advisory.
        if _config_was_seeded:
            _emit_first_run_config_notice(workspace_root, plan, reporter)

        # Surface blockers immediately: the plan is still saved (for inspection), but it cannot be
        # executed as-is, so don't let "Plan saved" read as all-clear — print each blocker and exit
        # non-zero. (A common one: a stray folder at the workspace root — "dumps belong in
        # 0-sources/" — which prep never auto-removes; the operator must move it into 0-sources or
        # delete it.) dry-run/execute would otherwise be where the operator first learns of it.
        if plan.blockers:
            reporter.error(f"\nThis plan CANNOT be executed — {len(plan.blockers)} blocker(s) must be "
                           "resolved first:")
            for b in plan.blockers:
                reporter.error(f"  - {b}")
            emit_next_step(reporter, "fix the blocker(s) above, then re-run `prep plan`.")
            sys.exit(2)

        emit_next_step(reporter, "`prep dry-run` to review the plan, or `prep execute` to apply.")

    elif args.command == "dry-run":
        from .photos_utils import prep_plan_path, PREP_PLAN_ARTIFACT
        pp = prep_plan_path(workspace_root)
        if not os.path.exists(pp):
            reporter.error(f"No {PREP_PLAN_ARTIFACT} found — run `plan` first.")
            sys.exit(2)
        # Same fast, friendly stop as execute: an already-prepped workspace with an empty 0-sources
        # has nothing to validate — the saved plan is stale (its moves are already applied).
        if _prep_nothing_to_do(workspace_root, reporter, workspace_changes):
            sys.exit(0)
        plan = _read_saved_plan(pp, reporter)

        try:
            PlanValidator.validate_plan_preflight(plan, workspace_root)
        except ValueError as e:
            reporter.error(f"Preflight validation failed: {e}")
            emit_next_step(reporter, "re-run `prep plan` to rebuild the plan against the current state.")
            sys.exit(2)                                     # a refusal (BLD-exit_statuses)

        # Dry-run is not a simulation: it validates the REAL saved plan (no virtual-filesystem
        # walk) and reports a SUMMARY of it. The full exact plan is the saved artifact at `pp`,
        # so there is no need to flood the terminal with every operation.
        op_counts = {}
        for op in plan.operations:
            op_counts[op.type] = op_counts.get(op.type, 0) + 1
        reporter.log(f"Dry-run: validated plan {plan.plan_id} — {len(plan.operations)} operation(s).",
                     stream="stdout")
        for t in sorted(op_counts):
            reporter.log(f"  {t}: {op_counts[t]}", stream="stdout")
        reporter.log(f"  no-op / already-correct files: {plan.summary.get('no_op_files', 0)}",
                     stream="stdout")
        if plan.warnings:
            reporter.log(f"  warnings: {len(plan.warnings)}", stream="stdout")
            for w in plan.warnings[:20]:
                reporter.log(f"    - {w}", stream="stdout")
            if len(plan.warnings) > 20:
                reporter.log(f"    … and {len(plan.warnings) - 20} more", stream="stdout")
        if plan.blockers:
            reporter.log(f"  BLOCKERS: {len(plan.blockers)} — execute will refuse:", stream="stdout")
            for b in plan.blockers[:20]:
                reporter.log(f"    - {b}", stream="stdout")
            if len(plan.blockers) > 20:
                reporter.log(f"    … and {len(plan.blockers) - 20} more", stream="stdout")
        reporter.log(f"  Full plan: {pp}", stream="stdout")
        if plan.blockers:
            emit_next_step(reporter, "fix the blocker(s) shown above, then re-run `prep plan`.")
        else:
            emit_next_step(reporter, "`prep execute` to apply the plan.")

    elif args.command == "execute":
        from .photos_utils import prep_plan_path, PREP_PLAN_ARTIFACT
        pp = prep_plan_path(workspace_root)
        if not os.path.exists(pp):
            reporter.error(f"No {PREP_PLAN_ARTIFACT} found — run `plan` first.")
            sys.exit(2)
        # Fast, friendly stop on an already-prepped workspace (empty 0-sources) — shared with
        # dry-run, gated on a plan existing so a missing plan still takes the "run plan first" path.
        if _prep_nothing_to_do(workspace_root, reporter, workspace_changes):
            sys.exit(0)
        plan = _read_saved_plan(pp, reporter)

        executor = PlanExecutor(workspace_root, workspace_changes=workspace_changes)

        # How execute ended decides its exit status (BLD-exit_statuses): refused before anything changed, 2; an
        # operation failed or the run's closing records could not be written, 3; an error not foreseen, 1.
        try:
            executor.execute(plan)
        except ExecuteRefused as e:
            reporter.error(f"Execution refused: {e}. Nothing was changed.")
            emit_next_step(reporter, "resolve the error above — for a stale plan, re-run `prep plan` — then "
                                     "re-run `prep execute`.")
            sys.exit(2)
        except Exception as e:
            reporter.error(f"Execution failed: {e}")
            emit_next_step(reporter, "resolve the error above and re-run `prep execute` "
                                     "(execute is idempotent — safe to re-run).")
            sys.exit(3 if isinstance(e, ExecuteFailed) else 1)

        # Next step depends on whether sorting is still pending: an empty by-dest means this was a
        # first ingest (sort, re-prep, then geotag); a populated by-dest means the move is recorded
        # and geotag can run.
        from .photos_utils import media_class_for_ext as _mc
        _bd = folder_name('photos_by_dest')
        _bd_has_media = any(_mc(os.path.splitext(fn)[1]) in ("image", "raw")
                            for _root, _dirs, _fs in os.walk(os.path.join(workspace_root, _bd))
                            for fn in _fs)
        if _bd_has_media:
            emit_next_step(reporter, f"`geotag plan` (or sort more photos into {_bd} first).")
        else:
            emit_next_step(reporter, f"sort photos from {folder_name('photos_by_date')} into {_bd}, then "
                                     f"re-run `prep plan` + `prep execute`, then `geotag plan`.")

    elif args.command == "prune-quarantine":
        try:
            prune_quarantine(
                workspace_root,
                plan_ids=getattr(args, "plan_ids", None),
                older_than_days=getattr(args, "older_than_days", None),
                do_delete=getattr(args, "yes", False),
                prune_all=getattr(args, "prune_all", False),
            )
        except PruneRefused as e:
            reporter.error(f"Error: {e}")
            sys.exit(2)                                     # a refusal (BLD-exit_statuses)
        if getattr(args, "yes", False):
            emit_next_step(reporter, "quarantine pruned — continue with the pipeline "
                                     "(`geotag plan` if prep is complete).")
        else:
            emit_next_step(reporter, "re-run with `--yes` to actually delete the listed quarantine.")


def main(argv=None):
    parser = argparse.ArgumentParser(prog="cartographer.photos_1_prep", description=PREP_BLURB,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    add_arguments(parser)
    args = parser.parse_args(argv)
    if getattr(args, "command", None) is None:        # no subcommand -> show the role blurb, not an error
        parser.print_help()
        return 0
    return run(args)


if __name__ == '__main__':
    main()
