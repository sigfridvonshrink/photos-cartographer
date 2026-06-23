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
from .photos_utils import CONFIG, CAMERA_IDENTITY_FIELDS, folder_name, managed_folder_names, dedup_priority, selected_gpx_root, missing_managed_folders, FOLDER_ROLES
from .reporting import get_reporter
from .photos_utils import (_move_no_clobber, _move_link_unlink, _get_renameat2,
                          WorkspaceCache, WorkspaceLock, ContentHasher,
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
    """Append `entry` to `manifest_dir/manifest.json` — the recoverable quarantine record (prep §15).

    Never silently truncates history: if the existing manifest is unreadable (corrupt JSON, not an
    array, or unreadable), it is PRESERVED under a `.corrupt-<ts>-<rand>` backup before a fresh one is
    started, so the prior records can still be recovered by hand. The write is atomic (temp in the
    same dir → atomic rename, shared §15), so a crash mid-write can never leave the torn manifest that
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
                os.replace(manifest_path, backup)
                get_reporter().warn(f"Warning: quarantine manifest {manifest_path} was unreadable ({e}); preserved "
                                    f"it as {os.path.basename(backup)} and started a fresh manifest.")
            except OSError:
                pass
            existing = []
    existing.append(entry)
    fd, tmp = tempfile.mkstemp(dir=manifest_dir, prefix=".tmp-manifest-", suffix=".json")
    try:
        with os.fdopen(fd, 'w') as mf:
            json.dump(existing, mf, indent=2)
        os.replace(tmp, manifest_path)
    except Exception:
        if os.path.exists(tmp):
            try:
                os.remove(tmp)
            except OSError:
                pass
        raise


def build_prep_log(prior_photos, operations, cache_files, quarantine_evidence, is_init, run_id):
    """Build the per-photo, content-fingerprint-keyed prep transformation log (prep Section 16.1).

    Pure and derived — it introduces no new authority, only consolidating records prep already
    produced: this run's validated plan operations, the final cache rows (for the fingerprint and
    current location), and the run's quarantine evidence — merged onto `prior_photos` (the prior
    log's `photos`, carried forward). Each NEW step is stamped with `run_id` so it is attributable
    to the run that caused it (§16.1 item 2); carried-forward steps keep their original run, so a
    no-op run leaves the log unchanged (§16.1 item 6). Returns (photos_dict, warnings)."""
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
            j["steps"].append(_step("consolidated_into_sources", to=dst))
        elif "Separate redundant JPG" in reason:
            j["steps"].append(_step("redundant_jpeg_separated", to=dst))
        elif "Chronological Organization" in reason:
            j["steps"].append(_step("organized", to=dst.split('/', 1)[0] + "/"))
            j["steps"].append(_step("provisional_rename", to=os.path.basename(dst)))
        path_origin[dst] = origin
        j["current"] = dst

    def _fp(row):
        ch = row.get("content_hash")
        if not ch:
            return None
        try:
            return json.loads(ch).get("value")
        except Exception:
            return None

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

    # 5. Merge onto the prior log carried forward.
    _bands = {folder_name(r) for r in ("missing_metadata", "redundant_jpgs", "videos_by_date", "photos_by_date")}
    photos = {}
    for fp in set(prior_photos) | set(run_steps_by_fp) | set(fp_to_current) | set(quarantined_by_fp):
        prior = prior_photos.get(fp)
        run_steps = run_steps_by_fp.get(fp, [])
        quar = quarantined_by_fp.get(fp)
        current = fp_to_current.get(fp) or (prior.get("final_path") if prior else None)
        if not (prior or run_steps or quar):
            # No prep transformation recorded for this content. In a prep-organized band that
            # means lost history (warn + partial, §13.3a); by-dest/user-curated media is skipped.
            top = current.split('/', 1)[0] if current else ""
            if top in _bands:
                photos[fp] = {"content_sha256": fp, "final_path": current, "journey": [],
                              "partial": True, "note": "prep history incomplete (no retained journey)"}
                warnings.append(f"prep-log: incomplete history for {current}")
            continue
        if prior:
            journey = list(prior.get("journey", [])) + run_steps
            if not run_steps and current and current != prior.get("final_path"):
                # Recognized by-date -> by-dest move (carried-forward identity, no plan op).
                journey.append({"phase": "user", "action": "moved_to_by_dest", "to": current, "run": run_id})
            entry = {**prior, "final_path": current or prior.get("final_path"), "journey": journey}
        else:
            entry = {"content_sha256": fp, "final_path": current, "journey": run_steps}
        if quar:
            entry["deduplicated"] = {"retained": entry.get("final_path"), "quarantined": quar}
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


class PlanValidator:
    @staticmethod
    def validate_plan_preflight(plan: Plan, current_workspace: str):
        """
        Validates the plan just before execution.
        Checks instruction fingerprints and destination clobbering.
        """
        if plan.plan_version != PLAN_SCHEMA_VERSION:
            raise ValueError(f"Stale plan: plan_version {plan.plan_version} is not the supported schema {PLAN_SCHEMA_VERSION}; regenerate the plan.")
        if plan.command != 'prep':
            raise ValueError(f"Plan command '{plan.command}' is not supported by photos-1-prep. Only 'prep' plans are allowed.")
        for op in plan.operations:
            if op.type not in PREP_ALLOWED_OPERATION_TYPES:
                raise ValueError(f"Operation type '{op.type}' is not allowed in photos-1-prep.")
            if op.type in ['move_no_clobber', 'rename_no_clobber', 'quarantine_move']:
                if op.source and op.source.startswith(folder_name('photos_by_dest') + '/'):
                    raise ValueError(f"Operation {op.type} forbidden on source in {folder_name('photos_by_dest')}: {op.source}")
                if op.destination and op.destination.startswith(folder_name('photos_by_dest') + '/'):
                    raise ValueError(f"Operation {op.type} forbidden on destination in {folder_name('photos_by_dest')}: {op.destination}")

        if plan.blockers:
            raise ValueError(f"Plan contains blockers and cannot be executed: {', '.join(plan.blockers)}")

        # Prevalidate metadata dependencies
        if getattr(plan, "metadata_dependencies", None):
            from .photos_utils import (
                get_exiftool_version,
                FIELD_SET_VERSION,
                METADATA_SCHEMA_VERSION,
                CAMERA_GROUP_KEY_VERSION,
                EXTRACTION_OPTIONS_FINGERPRINT
            )
            current_md_deps = {
                "extractor": "exiftool",
                "extractor_version": get_exiftool_version(),
                "field_set_version": FIELD_SET_VERSION,
                "extraction_options_fingerprint": EXTRACTION_OPTIONS_FINGERPRINT,
                "metadata_schema_version": METADATA_SCHEMA_VERSION,
                "camera_group_key_version": CAMERA_GROUP_KEY_VERSION
            }
            if plan.metadata_dependencies != current_md_deps:
                raise ValueError(f"Stale plan: metadata dependencies changed since planning. Expected: {plan.metadata_dependencies}, Current: {current_md_deps}")

        # Config staleness: the workspace config must be byte-identical to what the plan
        # was built against (prep Section 21). load_or_seed_config and _hash_file both
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

        # 1. Check instruction fingerprints
        for rel_path, expected_fp in plan.instruction_fingerprints.items():
            try:
                abs_path = RootGuard.resolve_and_check_path(current_workspace, rel_path)
            except ValueError as e:
                raise ValueError(f"Invalid instruction file path {rel_path}: {e}")

            if not os.path.exists(abs_path):
                raise ValueError(f"Instruction file {rel_path} is missing. Plan is stale.")

            current_fp = OperationPlanner._hash_file(abs_path)
            if current_fp.value != expected_fp.value:
                raise ValueError(f"Instruction file {rel_path} has changed since plan generation. Plan is stale.")


        # 2. Reserve and check destinations
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

# 3. Check preconditions (e.g. source file hasn't changed)
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

class PlanExecutor:
    def __init__(self, workspace_root: str):
        self.workspace_root = workspace_root
        from .photos_utils import ProgressCoordinator
        self.coordinator = ProgressCoordinator()

    def _prune_empty_dirs(self):
        """Remove directory skeletons left empty by structure-preserving moves and dump-dotfile
        quarantine: emptied subtrees under the 0-sources inbox, and any non-managed base entry an
        init move/quarantine emptied — including a hidden dump dir like `.thumbnails/` once its files
        are quarantined. The managed folders (`0`–`6`), the strays tree, and the control directories
        (`.photos-ingest`, `.photos-ingest-quarantine`, `.git`) are **never removed, even when
        empty** — they are explicitly protected by absolute path. Empty-dir removal is pure
        housekeeping; no media is affected.

        Returns a list of (relpath, reason) for non-managed base **dump** dirs that could NOT be
        pruned — still non-empty, or an `rmdir` failure (e.g. no write permission on the workspace
        root) — so the caller can warn the operator rather than leave the folder behind silently."""
        from .photos_utils import managed_folder_names, folder_name, CONTROL_DIR, QUARANTINE_DIR
        ws = self.workspace_root
        sources_path = os.path.join(ws, folder_name('sources'))
        control_top = {CONTROL_DIR, QUARANTINE_DIR, ".git"}
        managed_top = set(managed_folder_names()) | {folder_name('strays')}
        # Explicit guard: a managed/strays/control directory is never pruned even if empty. (0-sources
        # is a managed folder, so this also keeps the inbox itself while its internals are pruned.)
        protected = {os.path.abspath(os.path.join(ws, n)) for n in (managed_top | control_top)}
        # Non-managed base entries are the dump dirs an init move/quarantine should have emptied.
        base_dumps = []
        for f in os.listdir(ws):
            if f in managed_top or f in control_top:
                continue                               # never a prune target (managed/strays/control)
            p = os.path.join(ws, f)
            if os.path.isdir(p) and not os.path.islink(p):
                base_dumps.append(p)
        # Also sweep the by-date bands so a `YYYY-MM-DD/` day folder emptied by a by-dest move (or by
        # re-bucketing) does not linger; the band roots themselves stay protected above.
        targets = [sources_path,
                   os.path.join(ws, folder_name('photos_by_date')),
                   os.path.join(ws, folder_name('videos_by_date'))] + base_dumps
        for base in targets:
            if not os.path.isdir(base):
                continue
            for dirpath, _dirs, _files in os.walk(base, topdown=False):
                if os.path.abspath(dirpath) in protected:
                    continue                           # explicit: never remove a managed/strays/control dir
                try:
                    if not os.listdir(dirpath):
                        os.rmdir(dirpath)
                except OSError:
                    pass                               # surfaced below if the dir is a base dump dir

        # Diagnose any base dump dir that survived, so a leftover is never silent (it answers the
        # "why wasn't this folder deleted?" question directly).
        leftovers = []
        for p in base_dumps:
            if not os.path.isdir(p):
                continue                               # pruned successfully
            rel = os.path.relpath(p, ws)
            try:
                entries = [e for e in os.listdir(p)]
            except OSError as e:
                leftovers.append((rel, f"cannot list it ({e})"))
                continue
            if entries:
                sample = ", ".join(sorted(entries)[:3]) + ("…" if len(entries) > 3 else "")
                leftovers.append((rel, f"still contains: {sample}"))
            else:
                leftovers.append((rel, "it is empty but could not be removed — check write permission "
                                       "on the workspace root (e.g. a group-owned dir without group write)"))
        return leftovers

    def execute(self, plan: Plan, journal_path: str = None):
        # A distinct id for this execution run (vs plan.plan_id which identifies the plan);
        # surfaced in the handoff (prep Section 16).
        self.execution_id = f"{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')}-{uuid.uuid4().hex[:6]}"
        # Workspace lifecycle (prep Section 3.1 / 14.3 step 11): if the sentinel is absent this is
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
        # The workspace lock is held for the whole run by main() (shared contract Section 2);
        # execute() does not acquire it (callers that bypass main() — e.g. tests — run lock-free).
        cache = None
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
                raise

            # 2. Start Journal (version-stamped so a stale/foreign journal is detectable, §5)
            journal = JournalWriter(journal_path)
            journal.start_journal(plan.plan_id, depends_on={
                "tool": "photos-1-prep",
                "execution_id": self.execution_id,
                "plan_schema_version": plan.plan_version,
                "config_fingerprint": plan.config_fingerprint.value,
                "cache_schema_version": CACHE_SCHEMA_VERSION,
                "fingerprint_algorithm_version": FINGERPRINT_ALGORITHM_VERSION,
                "cli_options_fingerprint": plan.summary.get("cli_options_fingerprint"),
            })

            # 3. ZFS Hook (Optional) — pre-mutation snapshot of the workspace dataset (shared helper,
            #    labelled "prep" so it never collides with geotag's "geotag-" snapshot).
            from .photos_utils import take_zfs_snapshot
            snap = take_zfs_snapshot(self.workspace_root, plan.plan_id, "prep")
            if snap is not None:
                if snap["snapshot_name"] is not None:          # a snapshot was attempted -> journal it
                    journal.add_snapshot("workspace", command=snap["command"], exit_code=snap["exit_code"],
                                         stdout=snap["stdout"], stderr=snap["stderr"],
                                         required=snap["required"], snapshot_name=snap["snapshot_name"])
                if not snap["ok"]:
                    if snap["required"]:
                        journal.finish_journal("aborted_before_mutation")
                        raise RuntimeError(f"ZFS snapshot required but failed: {snap['stderr']}")
                    get_reporter().warn(f"Warning: {snap['stderr'] or 'ZFS snapshot failed'}; skipping snapshot.",
                                        stream="stdout")

            # 4. Execute Operations
            if plan.command != 'prep':
                raise ValueError(f"Plan command '{plan.command}' is not supported by photos-1-prep. Only 'prep' plans are allowed.")

            self.coordinator.start_phase("executing - applying operations", len(plan.operations))

            # Apply all post-verification cache effects as one transaction (§14.3.7): create the
            # cache up front and open a batch; commit once after the loop, roll back on failure
            # (the finally below). The filesystem stays the source of truth either way.
            if cache is None:
                cache = WorkspaceCache(self.workspace_root)
            cache.begin_batch()

            for op in plan.operations:
                if op.type not in PREP_ALLOWED_OPERATION_TYPES:
                    raise ValueError(f"Operation type '{op.type}' is not allowed in photos-1-prep.")
                if op.type in ['move_no_clobber', 'rename_no_clobber', 'quarantine_move']:
                    if op.source and op.source.startswith(folder_name('photos_by_dest') + '/'):
                        raise ValueError(f"Operation {op.type} forbidden on source in {folder_name('photos_by_dest')}: {op.source}")
                    if op.destination and op.destination.startswith(folder_name('photos_by_dest') + '/'):
                        raise ValueError(f"Operation {op.type} forbidden on destination in {folder_name('photos_by_dest')}: {op.destination}")

                op_started = datetime.now(timezone.utc).isoformat()
                status = "success"
                details = {}

                try:
                    # Media operations: mutate filesystem
                    if op.type == "mkdir":
                        if op.destination:
                            abs_dest = RootGuard.resolve_and_check_path(self.workspace_root, op.destination)
                            os.makedirs(abs_dest, exist_ok=True)
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
                            # (evidence-before-quarantine, §15): the manifest entry is the only durable
                            # record of WHY a file was quarantined, so writing it first guarantees a
                            # crash never strands a file in quarantine with no record. If the move then
                            # fails/crashes, the file stays at its source and a re-run re-quarantines it
                            # (fresh evidence under a new plan id); the pre-written entry of the
                            # interrupted run becomes a benign, prunable orphan rather than a lost record.
                            if op.type == "quarantine_move":
                                plan_id = op.verification.get("plan_id", "unknown_plan")
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
                                elif fx.get("action") == "rename":
                                    old = fx["old_path"]
                                    new = fx["new_path"]
                                    cache.rename_file(old, new, os.path.join(self.workspace_root, new))
                                    self.coordinator.increment("db_renames_applied")

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
                if status in ["failed", "failed_recovered", "failed_intervention_required"]:
                    break
            # All ops applied + verified -> commit the batched cache effects once.
            cache.commit_batch()
            self.coordinator.finish_phase()

# 5. Finish Journal
            if any(r.status in ["failed", "failed_recovered", "failed_intervention_required"] for r in journal.journal.operations):
                # If operations were skipped due to an abort, or failed mid-flight
                journal.journal.details = getattr(journal.journal, 'details', {})
                journal.save()
                journal.finish_journal("failed_intervention_required")
                failed_ops = [r for r in journal.journal.operations if r.status in ["failed", "failed_intervention_required", "failed_recovered"]]
                raise RuntimeError(f"Execution failed; intervention required. See journal. Failed ops: {failed_ops}")
            else:
                journal.finish_journal("success")

                # Housekeeping: structure-preserving moves + organization empty out the dump's
                # directory skeleton. Prune the empty dirs left under 0-sources and any base dump
                # dir an init move emptied, so 0-sources is left empty and the base holds only the
                # managed folders (prep Section 3.1 / 7). Empty-dir removal loses no media. Any dump
                # dir that could NOT be removed is reported (never left silently).
                for _rel, _why in self._prune_empty_dirs():
                    get_reporter().warn(f"Warning: left the dump folder {_rel}/ in place — {_why}")

                # Update summary with db effects
                if plan.summary and "performance_and_cache" in plan.summary:
                    plan.summary["performance_and_cache"]["db_upserts_applied"] = self.coordinator.counters.get("db_upserts_applied", 0)
                    plan.summary["performance_and_cache"]["db_removes_applied"] = self.coordinator.counters.get("db_removes_applied", 0)
                    plan.summary["performance_and_cache"]["db_renames_applied"] = self.coordinator.counters.get("db_renames_applied", 0)

                # Generate handoff manifest ONLY if success
                if plan.command == "prep":
                    self.coordinator.start_phase("executing - generating handoff manifest")
                    if cache is None:
                        cache = WorkspaceCache(self.workspace_root)

                    # Abort handoff if blockers exist from plan validation or execution issues indicating invalid dependencies
                    if plan.blockers:
                        raise RuntimeError("Cannot generate handoff manifest: plan execution completed but metadata dependencies are invalid due to plan blockers.")


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
                            try:
                                ch_dict = json.loads(record['content_hash'])
                                fp_status = ch_dict.get('status', 'unknown_fingerprint')
                            except Exception:
                                fp_status = "unknown_fingerprint"

                        if record['media_class'] not in ['image', 'video', 'raw']:
                            fp_status = "not_applicable"

                        folder_class = rel_path.split('/')[0] if '/' in rel_path else "root"

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

                                    ts = parsed.get("selected_source_naive_timestamp") or parsed.get("DateTimeOriginal") or parsed.get("CreateDate") or parsed.get("ModifyDate")
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
                                ts = cg_parsed.get("DateTimeOriginal") or cg_parsed.get("CreateDate") or cg_parsed.get("ModifyDate")
                                if ts:
                                    cg["timestamps"].append(ts)

                        filtered_record = {k: v for k, v in record.items() if k not in ["last_seen_ns", "absolute_path"]}
                        if md_record:
                            filtered_md = {k: v for k, v in md_record.items() if k not in ["relative_path", "raw_payload"]}
                            filtered_record["metadata_status"] = filtered_md

                        final_files.append({
                            **filtered_record,
                            "fingerprint_status": fp_status,
                            "folder_class": folder_class
                        })

                    # Real duplicate/conflict evidence from the quarantine ops (prep Section 12.2/16).
                    quarantine_evidence = []
                    for op in plan.operations:
                        if op.type == "quarantine_move":
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

                    # 2. Re-hash journal
                    journal_hash = OperationPlanner._hash_file(journal_path).value

                    # 3. Create handoff payload
                    md_deps = plan.metadata_dependencies if hasattr(plan, "metadata_dependencies") and isinstance(plan.metadata_dependencies, dict) else getattr(plan, "metadata_dependencies", {})
                    from .photos_utils import get_imagemagick_version as _get_imagemagick_version
                    handoff = {
                        "schema_version": 1,
                        "tool": "photos-1-prep",
                        # Per-run identifiers live in run_metadata, separate from the deterministic
                        # content, so they don't perturb content_fingerprint across no-op re-runs (§16).
                        "run_metadata": {"plan_id": plan.plan_id, "execution_id": self.execution_id},
                        "cache_fingerprint": cache_fingerprint,
                        "hash_algorithm": "sha256",
                        # The folders prep actually scans/organizes — `1-strays` is deliberately EXCLUDED:
                        # strays are abandoned once moved there (written, never re-scanned), so they are
                        # not part of the deterministic content downstream phases depend on (§3 / §16.2).
                        "folders_scanned": [
                            {"name": n, "mutable": n != folder_name('photos_by_dest')}
                            for n in managed_folder_names(CONFIG)
                        ],
                        "files": final_files,
                        "camera_groups": camera_groups,
                        "destination_folders": destination_folders,
                        "diagnostics": {
                            "duplicates_or_conflicts": quarantine_evidence,
                            "blockers": plan.blockers,
                            "warnings": plan.warnings,
                            "quarantine_footprint": plan.summary.get("quarantine_footprint"),
                        },
                        "depends_on": {
                            "effective_config": {
                                "fingerprint": plan.config_fingerprint.value,
                                "includes_cli_overrides": True
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
                                "name": md_deps.get("extractor", "exiftool"),
                                "version": md_deps.get("extractor_version", "unknown"),
                                "field_set_version": md_deps.get("field_set_version", 1),
                                "extraction_options_fingerprint": md_deps.get("extraction_options_fingerprint", "unknown"),
                                "metadata_schema_version": md_deps.get("metadata_schema_version", 1),
                                "camera_group_key_version": md_deps.get("camera_group_key_version", 1)
                            },
                            "plan": {
                                "schema_version": plan.plan_version
                            },
                            "cache": {
                                "schema_version": int(cache.get_meta("cache_schema_version") or CACHE_SCHEMA_VERSION),
                                "fingerprint_algorithm_version": cache.get_meta("fingerprint_algorithm_version") or cache.get_meta("hash_algorithm_version") or FINGERPRINT_ALGORITHM_VERSION,
                                "image_engine": "imagemagick",
                                "image_engine_version": _get_imagemagick_version()
                            },
                            "cli_options": {
                                "fingerprint": plan.summary.get("cli_options_fingerprint"),
                                "execution_config": plan.summary.get("execution_config")
                            }
                        }
                    }

                    # Write out atomically AND deterministically (prep §16.2; shared contract §15): route through
                    # write_json_artifact (temp → atomic rename, sort_keys) so the handoff bytes are
                    # byte-stable for a given workspace state. Geotag records a json_dependency on
                    # this file's exact bytes, so a non-deterministic dump (the old indent-only
                    # json.dump) could flip its SHA-256 and spuriously restale photos-21/22/23.
                    from .photos_utils import handoff_path, write_json_artifact, handoff_content_fingerprint
                    # The content fingerprint over the deterministic content (excludes run_metadata +
                    # diagnostics + the journal pointer) — geotag depends on THIS, not the volatile
                    # file bytes, so a no-op re-run does not restale it (§16).
                    handoff["content_fingerprint"] = handoff_content_fingerprint(handoff)
                    target_handoff_path = handoff_path(self.workspace_root)
                    os.makedirs(os.path.dirname(target_handoff_path), exist_ok=True)
                    try:
                        write_json_artifact(target_handoff_path, handoff)
                        # Belt-and-suspenders (§16): the just-written handoff must re-read to the SAME
                        # content_fingerprint, or geotag's recompute would mismatch — which can only
                        # happen if a non-round-trip-stable field crept into the handoff. Fail loudly here
                        # rather than ship a handoff geotag would (silently) treat as forever-stale.
                        with open(target_handoff_path) as _hf:
                            if handoff_content_fingerprint(json.load(_hf)) != handoff["content_fingerprint"]:
                                raise RuntimeError("handoff content_fingerprint is not round-trip stable")
                        if plan.summary and "performance_and_cache" in plan.summary:
                            plan.summary["performance_and_cache"]["handoff_written_after_successful_validation"] = True
                        self.coordinator.finish_phase()
                    except Exception as e:
                        raise RuntimeError(f"Failed to write handoff manifest: {e}")

                    # End-of-prep transformation log (prep Section 16.1 / shared Section 13.3): a
                    # per-photo, content-fingerprint-keyed, human-readable record of everything prep
                    # did — complete and self-sufficient even if no later phase runs. Derived from
                    # this run's plan + quarantine evidence, merged onto the prior log carried forward
                    # (incremental, §16.1 item 6), written atomically at this same success gate.
                    from .photos_utils import prep_log_path
                    plp = prep_log_path(self.workspace_root)
                    prior_photos = {}
                    if os.path.exists(plp):
                        try:
                            with open(plp) as pf:
                                prior_photos = (json.load(pf) or {}).get("photos", {}) or {}
                        except Exception:
                            prior_photos = {}
                    log_photos, log_warnings = build_prep_log(
                        prior_photos, plan.operations, cache.get_all_files(),
                        quarantine_evidence, self._was_uninitialized, plan.plan_id)
                    # No per-run metadata at the top level: the log must be byte-identical on a
                    # no-op run (§16.1 item 6). Run attribution lives per-step (the "run" field).
                    log_obj = {"schema_version": PREP_LOG_SCHEMA_VERSION, "tool": "photos-1-prep",
                               "photos": log_photos}
                    lfd, ltmp = tempfile.mkstemp(dir=os.path.dirname(plp), prefix=".tmp-prep-log-", suffix=".json", text=True)
                    try:
                        with os.fdopen(lfd, 'w') as lf:
                            json.dump(log_obj, lf, indent=2, sort_keys=True)
                        os.replace(ltmp, plp)
                        if plan.summary and "performance_and_cache" in plan.summary:
                            plan.summary["performance_and_cache"]["prep_log_written"] = True
                        for _w in log_warnings:
                            get_reporter().warn(f"  Warning: {_w}")
                    except Exception as e:
                        if os.path.exists(ltmp):
                            try:
                                os.remove(ltmp)
                            except Exception:
                                pass
                        raise RuntimeError(f"Failed to write prep log: {e}")

                # End-of-prep DB backup snapshot (shared contract Section 13.4a): a transactionally
                # consistent image of the live cache, captured at the same success gate as the
                # handoff and written no-clobber + atomically — VACUUM INTO a temp name, then atomic
                # rename. A failed/interrupted capture leaves the prior snapshot intact. This
                # refreshes prep's OWN snapshot only (never another phase's).
                if cache is not None:
                    from .photos_utils import prep_db_snapshot_path, write_db_snapshot
                    write_db_snapshot(cache.conn, prep_db_snapshot_path(self.workspace_root))
                    if plan.summary and "performance_and_cache" in plan.summary:
                        plan.summary["performance_and_cache"]["prep_db_snapshot_written"] = True

                # On an INIT run, write the root sentinel LAST — only after every operation and
                # the handoff have succeeded (prep Section 3.1 / 14.3 step 11). Because it is last,
                # a crash anywhere earlier leaves the workspace uninitialized and the next run
                # safely re-enters the init path. No-op on an already-initialized workspace.
                if self._was_uninitialized:
                    guard = _guard_path(self.workspace_root)
                    os.makedirs(os.path.dirname(guard), exist_ok=True)
                    gfd, gtmp = tempfile.mkstemp(dir=os.path.dirname(guard), prefix=".tmp-guard-")
                    with os.fdopen(gfd, 'w') as gf:
                        gf.write(json.dumps({"initialized": True, "tool": "photos-1-prep",
                                             "initialized_by_run": plan.plan_id}))
                    os.replace(gtmp, guard)

            self.coordinator.print_summary(plan_summary=plan.summary)
        finally:
            if cache is not None:
                # If the apply phase raised before commit_batch, discard the uncommitted
                # cache effects (the filesystem is the source of truth; the next run re-plans).
                if getattr(cache, "_batch_depth", 0) > 0:
                    cache.rollback_batch()
                cache.close()

class JournalWriter:
    def __init__(self, journal_path: str):
        self.journal_path = journal_path
        self.journal: Optional[Journal] = None

    def start_journal(self, plan_id: str, depends_on: Optional[Dict[str, Any]] = None):
        self.journal = Journal(
            journal_version=1,
            plan_id=plan_id,
            started_at=datetime.now(timezone.utc).isoformat(),
            status="started",
            depends_on=depends_on or {}
        )
        self.save()

    def add_snapshot(self, key: str, command: str, exit_code: int, stdout: str, stderr: str, required: bool, snapshot_name: Optional[str] = None):
        if self.journal:
            self.journal.snapshots[key] = {
                "command": command,
                "exit_code": exit_code,
                "stdout": stdout,
                "stderr": stderr,
                "required": required,
                "snapshot_name": snapshot_name
            }
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
        if self.journal:
            with open(self.journal_path, 'w') as f:
                f.write(self.journal.to_json())


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
    def __init__(self, workspace_root: str, cache: WorkspaceCache):
        self.workspace_root = workspace_root
        self.cache = cache
        self.managed_folders = managed_folder_names(CONFIG)
        from .photos_utils import ProgressCoordinator
        self.coordinator = ProgressCoordinator()

    def _allocate_suffix(self, base: str, ext: str, index: set, start_idx: int = 1,
                         bare_first: bool = False) -> str:
        # Delegates to the shared no-clobber suffix convention (photos_utils.allocate_suffix) so prep's
        # by-date de-collision and the merge phase's library-collision rename can never drift.
        # `bare_first` (shared contract §7.2): the by-date timestamp naming takes the bare name first;
        # the init-move / extension-normalize callers leave it False (they run only on a real collision).
        return allocate_suffix(base, ext, index, start_idx, bare_first)

    def _flag_dir_symlinks(self, root, dir_names, blockers):
        """Flag any subdirectory symlink encountered during a walk as a forbidden escape. os.walk does
        not descend into them (followlinks=False), so without this they would be silently ignored
        rather than blocked — the spec forbids symlinks among managed files (prep §6.2 item 3; shared contract §5.3)."""
        for dd in dir_names:
            p = os.path.join(root, dd)
            if os.path.islink(p):
                blockers.append(f"Forbidden symlink detected: {os.path.relpath(p, self.workspace_root)}")

    def _file_datetime(self, f):
        """The source-naive datetime parsed from a file's cached metadata (DateTimeOriginal, else
        CreateDate, else ModifyDate), or None if absent/unparseable. Used both to pick the by-date
        `YYYY-MM-DD/` subfolder and to test whether an already-organized file is in its conforming
        day folder."""
        md = (f.get('metadata') or {}).get('parsed_json')
        if not md:
            return None
        try:
            parsed = json.loads(md)
        except Exception:
            return None
        dt_str = parsed.get('DateTimeOriginal') or parsed.get('CreateDate') or parsed.get('ModifyDate')
        if not dt_str:
            return None
        try:
            return datetime.strptime(dt_str[:19], "%Y:%m:%d %H:%M:%S")
        except ValueError:
            return None

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

    def _recognize_carried_moves(self, files, existing_cache, existing_metadata):
        """Move-aware cache identity (prep §10.1 / 10.2). Recognize a file the user moved from by-date
        into 6-photos-by-dest (or re-sorted between destinations inside by-dest) by a cache-only
        bijective (size, mtime_ns, basename) stat match, and carry its cached hash + metadata forward
        to the new path instead of re-hashing / re-extracting it. By-dest is read-only, so there is no
        filesystem operation: the old (now-missing) row is dropped by ghost-prune and the carried row is
        upserted at the new path. Returns (carried_forward, moved_unmatched). Pure helper — computes the
        two maps; mutates no plan state. (Extracted verbatim from plan().)"""
        import collections as _collections
        _present = set(files)
        _missing_rows = {p: r for p, r in existing_cache.items() if p not in _present}
        _new_by_dest = [f for f in files
                        if f.startswith(folder_name('photos_by_dest') + '/') and f not in existing_cache]
        _src_idx = _collections.defaultdict(list)
        for _p, _r in _missing_rows.items():
            _src_idx[(_r['size'], _r['mtime_ns'], os.path.basename(_p).lower())].append(_p)
        _tgt_idx = _collections.defaultdict(list)
        _tgt_stat = {}
        for _f in _new_by_dest:
            _st = os.stat(os.path.join(self.workspace_root, _f))
            _tgt_stat[_f] = _st
            _tgt_idx[(_st.st_size, _st.st_mtime_ns, os.path.basename(_f).lower())].append(_f)
        carried_forward = {}  # new_by_dest_path -> {"source": old_path, "db_file": carried_db}
        for _key, _tgts in _tgt_idx.items():
            _srcs = _src_idx.get(_key, [])
            if len(_tgts) == 1 and len(_srcs) == 1:  # bijective unique match only
                _old_path, _new_path = _srcs[0], _tgts[0]
                _old_row = existing_cache[_old_path]
                _old_md = existing_metadata.get(_old_path)
                _st = _tgt_stat[_new_path]
                _carried = dict(_old_row,
                                relative_path=_new_path,
                                absolute_path=os.path.join(self.workspace_root, _new_path),
                                size=_st.st_size, mtime_ns=_st.st_mtime_ns, inode=_st.st_ino,
                                last_seen_ns=int(datetime.now(timezone.utc).timestamp() * 1e9))
                _carried["metadata"] = _old_md
                carried_forward[_new_path] = {"source": _old_path, "db_file": _carried}

        # by-dest files that LOOK moved (new under by-dest, uncached) but failed the unique bijective
        # match (ambiguous, basename changed, or stat reset) — they will re-fingerprint. Tagged
        # `moved-unmatched` so this exact, easy-to-miss cause is visible in the re-hash diagnostics.
        moved_unmatched = set(_new_by_dest) - set(carried_forward)
        return carried_forward, moved_unmatched

    def _aggregate_worker_results(self, worker_results, metadata_plan_status, blockers, warnings):
        """Sort + aggregate the per-file worker results on the main thread (deterministic). Appends to the
        passed metadata_plan_status / blockers / warnings; emits the §17.4 re-hash diagnostics. Returns
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

        # Re-hash diagnostics (prep §17.4): always-on when any media was re-fingerprinted. Split the
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

        db_files = [f for f in all_db_files if not f['relative_path'].startswith(folder_name('photos_by_dest') + '/')]
        by_dest_files = [f for f in all_db_files if f['relative_path'].startswith(folder_name('photos_by_dest') + '/')]

        rehash_summary = {
            "total": _total_rehash,
            "new_expected": _new_rehash,
            "unexpected": _unexpected_rehash,
            "by_reason": rehash_reasons,
            "sample": [{"path": p, "reason": r} for p, r in rehash_samples],
        }
        return all_db_files, db_files, by_dest_files, rehash_summary

    def _check_band_and_stray_media(self, all_db_files, blockers, warnings):
        """Band-misplacement guard + stray-media detection (prep §6.1 / §6.2 item 6). Appends to the
        passed `blockers`/`warnings` lists (and logs the stray notices). Verbatim lift from plan() —
        same iteration order, so the appended order is unchanged."""
        # Band-misplacement guard (prep Section 6.1 / 6.2 item 6): photos and videos live in
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

        # Stray-media detection (prep Section 6.1): a dump file prep is about to set aside as a stray
        # (class `other`, in 0-sources) whose extension exiftool reports as image/* or video/* is most
        # likely a media format the workspace's media_extensions config doesn't list. Probe each
        # DISTINCT stray extension once (not per file) and warn — non-blocking — so the operator can add
        # it to media_extensions and re-run to organize those files instead of parking them in 1-strays.
        from .photos_utils import exiftool_mime_type
        _sources_top = folder_name('sources')
        _stray_ext_sample = {}
        for f in all_db_files:
            if f.get('media_class') == 'other' and f['relative_path'].split('/')[0] == _sources_top:
                e = os.path.splitext(f['relative_path'])[1].lower().lstrip('.')
                if e and e not in _stray_ext_sample:
                    _stray_ext_sample[e] = f['absolute_path']
        for e, sample in sorted(_stray_ext_sample.items()):
            mime = exiftool_mime_type(sample)
            if mime and (mime.startswith('image/') or mime.startswith('video/')):
                msg = (f"Dump contains .{e} files that exiftool sees as media ({mime}) but media_extensions "
                       f"config does not list — they will be set aside in {folder_name('strays')}. Add '.{e}' to the "
                       f"right media_extensions class in photos-00-config.json and re-run prep to organize them.")
                warnings.append(msg)
                get_reporter().log(f"  Notice: {msg}")

    def _build_run_report(self, operations, no_op_count, metadata_plan_status, all_db_files,
                          carried_forward, by_dest_files, blockers, warnings, qf,
                          current_exiftool_version, current_field_set_version):
        """Assemble the user-visible run report (prep §19) — pure read-only re-presentation of data
        already on hand (operation/metadata/camera-group/GPS counts). Returns the report dict. Verbatim
        lift from plan(); no state mutated."""
        # User-visible run report (prep Section 19), re-presenting data already on hand.
        import collections as _collections
        _media_op_types = {"mkdir", "move_no_clobber", "rename_no_clobber", "quarantine_move"}
        _q_ops = [op for op in operations if op.type == "quarantine_move"]
        _dup_by_dest = sum(1 for op in _q_ops
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
            "recognized_moves": len(carried_forward),
            "by_dest_files_scanned_read_only": len(by_dest_files),
            "by_dest_mutated": 0,
            "duplicates_against_by_dest": _dup_by_dest,
            "duplicates_against_mutable": len(_q_ops) - _dup_by_dest,
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
        """Recognize orphaned exiftool intermediates/backups (`<media>_exiftool_tmp` / `<media>_original`)
        left by a hard-killed geotag write — pull them out of the media inventory (quarantined below,
        recoverable) rather than mis-inventorying them as `other`. A leftover under read-only by-dest is
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
        """Inventory walk (prep §6 / §0): scan the workspace root + managed folders, bar symlinks,
        skip control / strays / gpx subtrees, and build the sorted `files` list; append
        forbidden-symlink and misplaced-entry blockers. Mutates the passed `files` / `blockers`.
        Verbatim lift from plan()."""
        self.coordinator.start_phase("planning - scanning inventory")
        # 0. Inventory, lifecycle guards, symlink check
        _managed_set = set(self.managed_folders)
        _strays = folder_name('strays')
        _sources = folder_name('sources')
        # Defensive GPX skip (shared contract §8.2 / prep §3): gpx_root resolves OUTSIDE the managed
        # 0-6 tree by design (default `.photos-ingest/gpx/`, already skipped as a dotdir). But should
        # it be MISCONFIGURED to resolve inside a managed folder, prep must skip that subtree so the
        # GPX tracks are never organized/swept to 1-strays. Resolved to a realpath so a relative or
        # symlinked gpx_root matches; empty/outside-the-tree resolves to a no-op.
        _gpx_skip = selected_gpx_root()
        for f in os.listdir(self.workspace_root):
            path = os.path.join(self.workspace_root, f)
            # A symlink at the workspace root is forbidden outright (never followed, prep §6.2 item 2/3;
            # shared contract §5.3) — flagged
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
                # Initialized workspace (prep Section 6.2 item 2): the base holds only the managed
                # folders + control dirs. Any other root entry — file, dotfile, or non-managed
                # folder — is a misplaced dump and a hard block; dumps belong in 0-sources/.
                blockers.append(f"Misplaced entry at workspace root (dumps belong in {_sources}/): {f}")
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
        for d in self.managed_folders:
            folder_path = os.path.join(self.workspace_root, d)
            # A managed folder that is itself a symlink would let os.walk traverse its external
            # target (the same escape as a root dump symlink) — block it before walking.
            if os.path.islink(folder_path):
                blockers.append(f"Forbidden symlink detected: {d}")
                continue
            # gpx_root misconfigured to BE this managed folder — skip it wholesale (§8.2).
            if _gpx_skip and os.path.realpath(folder_path) == _gpx_skip:
                continue
            if os.path.isdir(folder_path):
                for root, _dirs, filenames in os.walk(folder_path):
                    self._flag_dir_symlinks(root, _dirs, blockers)   # nested dir symlinks are forbidden too
                    # Do not descend into hidden subdirs: their files are not managed media (a non-dot
                    # file inside a `.thumbnails/` is still dump junk). In 0-sources those files are
                    # picked up by _collect_dump_dotfiles for quarantine; elsewhere they are skipped.
                    # (Matches the init dump-folder walk, which also prunes dot-subdirs.)
                    _dirs[:] = [dd for dd in _dirs if not dd.startswith('.')]
                    if _gpx_skip:                                    # prune a gpx_root subtree nested here (§8.2)
                        _dirs[:] = [dd for dd in _dirs
                                    if os.path.realpath(os.path.join(root, dd)) != _gpx_skip]
                    for fname in filenames:
                        if not fname.startswith('.'):
                            path = os.path.join(root, fname)
                            rel_path = os.path.relpath(path, self.workspace_root)
                            if os.path.islink(path):
                                blockers.append(f"Forbidden symlink detected: {rel_path}")
                            else:
                                files.append(rel_path)
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

        # Content-hash (pixel signature) freshness: an image/raw content hash is
        # bound to the ImageMagick version that produced it. If magick changed,
        # the cached signature is stale and must be recomputed.
        content_hash_fresh = True
        if media_class in ('image', 'raw') and cached and cached.get('content_hash'):
            try:
                _ch = json.loads(cached['content_hash'])
                _ev = _ch.get('engine_version')
                # Only the version-bound pixel signature can be restaled by an engine
                # change; a record with no recorded engine_version (legacy/mocked) is
                # judged solely by size/mtime, not falsely restaled.
                if _ch.get('status') == 'valid' and _ev is not None and _ev != current_magick_version:
                    content_hash_fresh = False
            except Exception:
                content_hash_fresh = False

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
        # camera-group-key stamp moved), or `engine-changed` (ImageMagick/ffmpeg version bump).
        if media_class in ('image', 'raw', 'video'):
            if cached is None:
                result["rehash_reason"] = "moved-unmatched" if rel_path in moved_unmatched else "new"
            elif cached['size'] != stat.st_size:
                result["rehash_reason"] = "size-changed"
            elif cached['mtime_ns'] != stat.st_mtime_ns:
                result["rehash_reason"] = "mtime-changed"
            elif not md_fresh:
                result["rehash_reason"] = "metadata-stale"
            else:
                result["rehash_reason"] = "engine-changed"

        # Media is identified ONLY by its decoded-content fingerprint (image/raw -> identify,
        # video -> ffmpeg stream MD5). It is never byte-hashed: a whole-file SHA-256 is reserved
        # for artifacts and would change under the EXIF/GPS rewrites a fingerprint must survive
        # (shared contract Section 9.1). Non-media (other-class) is not fingerprinted at all
        # (prep Section 9) — it is moved inert to 1-strays and never enters a content decision.
        file_hash_res = None
        content_hash_res = None
        if media_class in ['image', 'raw']:
            content_hash_res = ContentHasher.fingerprint_image(abs_path)
        elif media_class == 'video':
            content_hash_res = ContentHasher.fingerprint_video(abs_path)

        parent_folder = os.path.dirname(abs_path)

        if parent_folder in failed_metadata_folders:
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
        if meta.get("extraction_status") == "extraction_failed":
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
                "parsed_json": json.dumps({k:v for k,v in meta.items() if k != "raw_payload"}),
                "raw_payload": meta.get("raw_payload", "{}")
            }

        result["db_file"] = {
            "relative_path": rel_path,
            "absolute_path": abs_path,
            "size": stat.st_size,
            "mtime_ns": stat.st_mtime_ns,
            "inode": stat.st_ino,
            "media_class": media_class,
            "hash": json.dumps(file_hash_res) if file_hash_res else None,
            "content_hash": json.dumps(content_hash_res) if content_hash_res else None,
            "last_seen_ns": int(datetime.now(timezone.utc).timestamp() * 1e9),
            "metadata": md_record
        }
        return result

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
        """Init move (prep §7.1): on an init run, move each base-dump entry into 0-sources with
        its structure preserved (no flatten), case-insensitively collision-suffixed. Mutates the
        op-building cluster carried on `st`. Verbatim from plan() with `<cluster> -> st.<cluster>`."""
        for f in db_files:
            rel_path = st.current_paths[f['relative_path']]
            # Init move (prep Section 7.1): move each base-entry file into 0-sources with its
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
                        database_effects_after_verification=[{"action": "remove", "relative_path": rel_path}, {"action": "upsert", "data": dict(f, relative_path=dest, absolute_path=os.path.join(self.workspace_root, dest))}]
                    ))
                    st.current_paths[f['relative_path']] = dest

    def _plan_extension_case(self, st, db_files):
        """Extension-case normalization (prep §6): a file whose extension is not lowercase is
        renamed to lowercase via a two-step temp rename (no-clobber, case-insensitive-collision
        safe). Mutates the op-building cluster on `st`. Verbatim from plan() with `<cluster> ->
        st.<cluster>`."""
        for f in db_files:
            rel_path = st.current_paths[f['relative_path']]
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
                        database_effects_after_verification=[{"action": "remove", "relative_path": rel_path}, {"action": "upsert", "data": dict(f, relative_path=temp_rel, absolute_path=os.path.join(self.workspace_root, temp_rel))}]
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
                        database_effects_after_verification=[{"action": "remove", "relative_path": temp_rel}, {"action": "upsert", "data": dict(f, relative_path=final_rel, absolute_path=os.path.join(self.workspace_root, final_rel))}]
                    ))
                    st.current_paths[f['relative_path']] = final_rel

    def _plan_redundant_jpgs(self, st, db_files):
        """RAW+JPG pairing (prep §6): when a RAW and its same-stem JPG share a folder, move the
        JPG to 3-redundant-jpgs (the RAW is the keeper). Returns paired_jpgs (the set of paired
        JPG rel-paths, consumed by the dedup step). Mutates the op-building cluster on `st`.
        Verbatim from plan() with `<cluster> -> st.<cluster>` + a trailing return."""
        base_groups = {}
        for f in db_files:
            rel_path = st.current_paths[f['relative_path']]
            basename = os.path.basename(rel_path)
            name, _ = os.path.splitext(basename)
            folder = os.path.dirname(rel_path)
            base_groups.setdefault((folder, name), []).append(f)

        paired_jpgs = set()
        # print("BASE GROUPS:", list(base_groups.keys()))
        for (folder, name), group in base_groups.items():
            has_raw = any(f['media_class'] == 'raw' for f in group)
            has_jpg = any(f['media_class'] == 'image' and f['relative_path'].lower().endswith('.jpg') for f in group)
            if has_raw and has_jpg:
                for f in group:
                    if f['media_class'] == 'image':
                        rel_path = st.current_paths[f['relative_path']]
                        paired_jpgs.add(f['relative_path'])
                        if rel_path.startswith(folder_name('sources') + "/"):
                            dest = os.path.join(folder_name('redundant_jpgs'), os.path.basename(rel_path))
                            st.media_mutated_originals.add(f["relative_path"])

                            st.operations.append(Operation(

                                operation_id=f"op-{uuid.uuid4().hex[:8]}",

                                type="move_no_clobber",

                                reason="Separate redundant JPG",
                                source=rel_path,
                                destination=dest,
                                preconditions={"size": f["size"], "mtime_ns": f["mtime_ns"]},
                                verification={},
                                database_effects_after_verification=[{"action": "remove", "relative_path": rel_path}, {"action": "upsert", "data": dict(f, relative_path=dest, absolute_path=os.path.join(self.workspace_root, dest))}]
                            ))
                            st.current_paths[f['relative_path']] = dest
        return paired_jpgs

    def _plan_content_groups(self, db_files, by_dest_files, paired_jpgs, blockers):
        """Content-fingerprint grouping (prep §6/§9): group media by (content_hash, media_class)
        for dedup, skipping paired JPGs and non-media; a missing/invalid fingerprint on a mutable
        file is a blocker (by-dest is exempt). Appends to `blockers`; returns content_groups.
        Verbatim lift from plan() (no op-building cluster touched)."""
        content_groups = {}
        for f in db_files + by_dest_files:
            if f['relative_path'] in paired_jpgs:
                continue
            # Non-media (other-class) is never fingerprinted and never content-deduplicated; it is
            # routed to 1-strays below. The absence of a fingerprint on `other` is never a blocker
            # (prep Section 9 / 3.2).
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
        """Quarantine the scan-recognized non-media artifacts (prep §15): orphaned exiftool
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

    def plan(self) -> Plan:
        operations = []
        blockers = []
        warnings = []
        files = []
        self._all_physical_lower_for_plan = None
        media_mutated_originals = set()

        # Seed photos-00-config.json on first run, then read it as authoritative, before
        # any config-dependent value is used or fingerprinted (shared contract Section 4 / prep Section 3).
        from .photos_utils import load_or_seed_config
        self._config_fingerprint = load_or_seed_config(self.workspace_root)

        # Workspace lifecycle (prep Section 3.1): INITIALIZED once the root sentinel exists.
        from .photos_utils import guard_path, FOLDER_ROLES
        self._initializing = not os.path.exists(guard_path(self.workspace_root))
        if self._initializing:
            # Plan creation of the full 0-6 structure (idempotent mkdir; the sentinel is written
            # last by execute, prep Section 14.3 step 11).
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

        self._scan_inventory(files, blockers)

        # Hidden (dot-prefixed) files arriving in a dump (.DS_Store, .thumbnails/, editor temp) are
        # recoverable junk; collect them from the dump areas (root on init, 0-sources inbox) for
        # quarantine below rather than leaving them to litter the workspace. The control dirs are
        # never touched (see _collect_dump_dotfiles).
        dump_dotfiles = self._collect_dump_dotfiles(blockers)

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

        carried_forward, moved_unmatched = self._recognize_carried_moves(
            files, existing_cache, existing_metadata)

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
        # and portable between machines — there is no requirement to run a given workspace on the same
        # machine each time (determinism, prep spec §17.3). execution_config holds only OUTPUT-AFFECTING
        # CLI options — none today — so its fingerprint is stable.
        execution_config = {}
        cli_options_fingerprint = OperationPlanner._hash_dict(execution_config).value

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
            worker_results, metadata_plan_status, blockers, warnings)

        self._check_band_and_stray_media(all_db_files, blockers, warnings)

        self.coordinator.finish_phase()
        self.coordinator.start_phase("planning - building duplicate groups")

        ghost_prunes = self._build_ghost_prunes()





        current_paths = {f['relative_path']: f['relative_path'] for f in db_files}
        by_dest_paths = {f['relative_path'].lower(): f['relative_path'] for f in by_dest_files}

        global_destinations = set()
        for p in by_dest_paths.keys():
            global_destinations.add(p)

        st = _PlanState(operations, current_paths, by_dest_paths, global_destinations, media_mutated_originals)
        self._plan_init_moves(st, db_files)

        self._plan_extension_case(st, db_files)

        paired_jpgs = self._plan_redundant_jpgs(st, db_files)


        content_groups = self._plan_content_groups(db_files, by_dest_files, paired_jpgs, blockers)

        quarantined = set()
        plan_id_for_quarantine = f"{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')}-{uuid.uuid4().hex[:6]}"

        self._plan_quarantine_artifacts(st, exiftool_leftovers, dump_dotfiles, plan_id_for_quarantine)

        for (ch_str, mc), group in content_groups.items():
            if len(group) > 1:
                def priority(item):
                    p = current_paths.get(item['relative_path'], item['relative_path'])
                    return dedup_priority(p)

                group.sort(key=priority)
                retained = group[0]

                for dup in group[1:]:
                    rel_path = current_paths.get(dup['relative_path'], dup['relative_path'])
                    if rel_path.startswith(folder_name('photos_by_dest') + '/'):
                        # Never mutate by-dest
                        continue

                    quarantine_dest = os.path.join(".photos-ingest-quarantine", plan_id_for_quarantine, rel_path)
                    manifest_payload = {
                        "original_path": rel_path,
                        "quarantine_path": quarantine_dest,
                        "retained_counterpart": current_paths.get(retained['relative_path'], retained['relative_path']),
                        "duplicate_evidence": json.loads(ch_str),
                        "plan_id": plan_id_for_quarantine,
                    }
                    media_mutated_originals.add(dup["relative_path"])

                    operations.append(Operation(

                        operation_id=f"op-{uuid.uuid4().hex[:8]}",

                        type="quarantine_move",
                        reason=f"Duplicate of {current_paths.get(retained['relative_path'], retained['relative_path'])}",
                        source=rel_path,
                        destination=quarantine_dest,
                        preconditions={"size": dup["size"], "mtime_ns": dup["mtime_ns"]},
                        verification=manifest_payload,
                        database_effects_after_verification=[{"action": "remove", "relative_path": rel_path}, {"action": "upsert", "data": dict(dup, relative_path=quarantine_dest, absolute_path=os.path.join(self.workspace_root, quarantine_dest))}]
                    ))
                    quarantined.add(dup['relative_path'])
                    current_paths[dup['relative_path']] = quarantine_dest

        # Pass 1: seed the per-run suffix index with EVERY already-conforming name first, so a
        # newly-organized (or re-located) file never collides with an existing one regardless of
        # iteration order. A single global index suffices even with the new day subfolders: the
        # filename carries the full date (`YYYY-MM-DD--HH-MM-SS`), so two files can share a name only
        # if they share the full timestamp — i.e. the same day, hence the same `YYYY-MM-DD/` folder.
        # Two files in different day folders can never collide on name, so a global basename set is
        # exactly equivalent to per-folder scoping.
        global_index = set()
        to_organize = []
        strays_to_move = []
        _managed = set(managed_folder_names(CONFIG))
        _sources = folder_name('sources')
        _sources_prefix = _sources + '/'
        _by_date_bands = {folder_name('photos_by_date'), folder_name('videos_by_date')}

        for f in db_files:
            if f['relative_path'] in quarantined: continue
            rel_path = current_paths[f['relative_path']]
            # Non-media (other-class): never date-organized. Move it out of the 0-sources inbox
            # into 1-strays/<plan-id>/<rel> (structure preserved), inert and untracked (prep
            # Section 3.2 / 7.6), so 0-sources is left empty. Other-class outside the inbox (it
            # should not occur) is left untouched.
            if f['media_class'] == 'other':
                if rel_path.startswith(_sources_prefix):
                    strays_to_move.append((f, rel_path))
                continue
            top = rel_path.split('/', 1)[0]
            if top != _sources and top in _managed:    # already in a managed band
                if top in _by_date_bands:
                    # By-date files must live under a `band/YYYY-MM-DD/` day folder. One already there
                    # (matching its own timestamp) is conforming -> no-op; a flat or wrong-day file is
                    # re-located into the correct day folder (Section 7.6 migration).
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
            media_mutated_originals.add(f["relative_path"])
            operations.append(Operation(
                operation_id=f"op-{uuid.uuid4().hex[:8]}",
                type="move_no_clobber",
                reason="Move non-media stray out of sources",
                source=rel_path,
                destination=dest,
                preconditions={"size": f["size"], "mtime_ns": f["mtime_ns"]},
                verification={},
                database_effects_after_verification=[{"action": "remove", "relative_path": rel_path}]))
            current_paths[f['relative_path']] = dest

        # Pass 2: place each file still in 0-sources (or being re-located from a non-conforming by-date
        # spot) into its destination directory and allocate its name against that directory's index.
        for f, rel_path in to_organize:
            dt = self._file_datetime(f)
            base, ext = os.path.splitext(os.path.basename(rel_path))
            ext = ext.lstrip('.')

            if dt is not None:
                target_folder = (folder_name('videos_by_date') if f['media_class'] == 'video'
                                 else folder_name('photos_by_date'))
                prefix = dt.strftime(CONFIG["filename_timestamp_format"])
                # Group by-date media into a YYYY-MM-DD/ day subfolder; the filename keeps the full
                # timestamp (Section 8). The day uses the date portion of the source-naive timestamp.
                target_dir = os.path.join(target_folder, dt.strftime("%Y-%m-%d"))
            else:
                target_dir = folder_name('missing_metadata')   # untimestamped -> flat, no day folder
                prefix = f"UNKN_{base}"

            # §7.2: the first file at a given timestamp gets the bare name; the -NNN suffix appears only
            # on a genuine collision (matches geotag's final naming, so an uncorrected file's
            # provisional and final names coincide — §7.3). A same-named file can only be in this same
            # day folder, so the global index is exact (see Pass 1).
            final_name = self._allocate_suffix(prefix, ext, global_index, bare_first=True)
            dest = os.path.join(target_dir, final_name)

            media_mutated_originals.add(f["relative_path"])


            operations.append(Operation(


                operation_id=f"op-{uuid.uuid4().hex[:8]}",


                type="move_no_clobber",


                reason="Chronological Organization",
                source=rel_path,
                destination=dest,
                preconditions={"size": f["size"], "mtime_ns": f["mtime_ns"]},
                verification={},
                database_effects_after_verification=[{"action": "remove", "relative_path": rel_path}, {"action": "upsert", "data": dict(f, relative_path=dest, absolute_path=os.path.join(self.workspace_root, dest))}]
            ))
            current_paths[f['relative_path']] = dest

        cache_upserts = []
        for f in all_db_files:
            original_rel = f["relative_path"]
            planned_rel = current_paths.get(original_rel, original_rel)

            if original_rel in media_mutated_originals:
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

            if (cached and cached["size"] == f["size"] and cached["mtime_ns"] == f["mtime_ns"]
                    and md_fresh and cached.get("content_hash") == f.get("content_hash")):
                continue

            cache_upserts.append({
                "action": "upsert",
                "data": dict(f, relative_path=planned_rel, absolute_path=os.path.join(self.workspace_root, planned_rel)),
                "preconditions": {
                    "size": f["size"],
                    "mtime_ns": f["mtime_ns"]
                }
            })

        # Persist recognized moves: upsert the carried row at the new by-dest path
        # (the file exists there, so the executor's upsert precondition holds). The old
        # row's removal is handled by ghost-prune (its path is now missing).
        for _new_path, _cf in carried_forward.items():
            _cdb = _cf["db_file"]
            cache_upserts.append({
                "action": "upsert",
                "data": _cdb,
                "preconditions": {"size": _cdb["size"], "mtime_ns": _cdb["mtime_ns"]},
            })

        if cache_upserts:
            operations.append(Operation(
                operation_id=f"op-{uuid.uuid4().hex[:8]}",
                type="db_upsert",
                reason="Cache unchanged state",
                source=None,
                destination=None,
                preconditions={},
                verification={},
                database_effects_after_verification=cache_upserts
            ))

        if ghost_prunes:
            operations.append(Operation(
                operation_id=f"op-{uuid.uuid4().hex[:8]}",
                type="db_remove",
                reason="Prune ghosts",
                source=None,
                destination=None,
                preconditions={},
                verification={},
                database_effects_after_verification=ghost_prunes
            ))

        no_op_count = len(files) - len(media_mutated_originals)
        from .photos_utils import quarantine_footprint
        qf = quarantine_footprint(self.workspace_root)

        report = self._build_run_report(operations, no_op_count, metadata_plan_status, all_db_files,
                                        carried_forward, by_dest_files, blockers, warnings, qf,
                                        current_exiftool_version, current_field_set_version)

        # Record passive file state dependencies for idempotency and staleness protection
        workspace_file_preconditions = []
        for f in all_db_files:
            if f["relative_path"] not in media_mutated_originals:
                workspace_file_preconditions.append({
                    "relative_path": f["relative_path"],
                    "size": f["size"],
                    "mtime_ns": f["mtime_ns"],
                    "role": "by_dest_read_only" if f["relative_path"].startswith(folder_name('photos_by_dest') + "/") else "no_op_prepared"
                })

        from .photos_utils import (
            get_exiftool_version,
            FIELD_SET_VERSION,
            METADATA_SCHEMA_VERSION,
            CAMERA_GROUP_KEY_VERSION,
            EXTRACTION_OPTIONS_FINGERPRINT
        )

        # Close the final planning phase ("building duplicate groups") opened above — without this its
        # progress task never gets a FINISH event, so a live observer (the console) would leave the row
        # stuck on screen with a count of 0.
        self.coordinator.finish_phase()

        return Plan(
            plan_version=PLAN_SCHEMA_VERSION,
            plan_id=plan_id_for_quarantine,
            command="prep",
            created_at=datetime.now(timezone.utc).isoformat(),
            workspace_root=self.workspace_root,
            digikam_root=None,
            config_fingerprint=Fingerprint(algorithm="sha256", value=self._config_fingerprint),
            instruction_fingerprints={},
            locks_required=["workspace"],
            summary={
            "message": "Prep Plan generated",
            "no_op_files": no_op_count,
            "operations_planned": len(operations),
            "recognized_moves": len(carried_forward),
            "quarantine_footprint": qf,
            "report": report,
            "blockers_found": len(blockers),
            "metadata_plan_status": metadata_plan_status,
            "execution_config": execution_config,
            "cli_options_fingerprint": cli_options_fingerprint,
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
                "db_renames_applied": 0,
                "dependency_validation_status": "pending",
                "handoff_written_after_successful_validation": False,
                "rehash_summary": rehash_summary,
            }
        },
            blockers=blockers,
            warnings=warnings,
            operations=operations,
            workspace_file_preconditions=workspace_file_preconditions,
            metadata_dependencies={
                "extractor": "exiftool",
                "extractor_version": get_exiftool_version(),
                "field_set_version": FIELD_SET_VERSION,
                "extraction_options_fingerprint": EXTRACTION_OPTIONS_FINGERPRINT,
                "metadata_schema_version": METADATA_SCHEMA_VERSION,
                "camera_group_key_version": CAMERA_GROUP_KEY_VERSION
            }
        )

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


def prune_quarantine(workspace_root, plan_ids=None, older_than_days=None, do_delete=False, prune_all=False):
    """Delete recoverable quarantine — the ONLY operation that ever removes quarantine
    content (prep Section 15.3). Default is a non-destructive dry-run; `do_delete`
    (--yes) actually deletes. Selectable by exact plan-id and/or age; deleting with no
    selector requires `prune_all` (--all). Runs under the workspace lock and only ever
    touches `.photos-ingest-quarantine/`."""
    import shutil
    from datetime import timedelta
    from .photos_utils import quarantine_dir
    reporter = get_reporter()
    base = quarantine_dir(workspace_root)
    if not os.path.isdir(base):
        reporter.log("No quarantine directory; nothing to prune.", stream="stdout")
        return

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
        for d in all_dirs:
            t = _parse_plan_id_time(d)
            if t is not None and t < cutoff:
                selected.add(d)
    if not has_selector:
        selected = set(all_dirs)

    if do_delete and not has_selector and not prune_all:
        raise RuntimeError("Refusing to delete all quarantine without a selector. "
                           "Pass --plan-id / --older-than-days, or --all to confirm.")

    # The workspace lock is held for the whole run by main() (shared contract Section 2).
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
            shutil.rmtree(safe)
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
    "quarantines (recoverably, never deletes), organizes media by date and into by-dest, and builds "
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


def add_arguments(parser):
    """Register prep's `-j` + subcommands on `parser` — the top parser when run standalone
    (`python -m cartographer.photos_1_prep`), or the `prep` subparser in the combined
    `photos-cartographer` CLI. Shared so both invocations expose an identical surface."""
    parser.add_argument("-j", "--jobs", type=positive_int, default=4, help="Number of parallel jobs for processing.")
    subparsers = parser.add_subparsers(dest="command")

    # prep command. plan/dry-run/execute all use the canonical control-dir plan path
    # (photos_utils.prep_plan_path) — `plan` writes it, `dry-run`/`execute` read it — so there are no
    # --output/--plan flags: the phase always knows where its plan lives (shared contract §5).
    subparsers.add_parser("plan", help="Generate the prep plan (saved to .photos-ingest/photos-10-prep-plan.json)")

    subparsers.add_parser("dry-run", help="Validate and display the saved prep plan")

    subparsers.add_parser("execute", help="Execute the saved prep plan")

    prune_parser = subparsers.add_parser("prune-quarantine", help="Delete recoverable quarantine (dry-run by default).")
    prune_parser.add_argument("--plan-id", action="append", dest="plan_ids", help="Quarantine <plan_id> directory to prune (repeatable).")
    prune_parser.add_argument("--older-than-days", type=int, help="Prune quarantine directories older than N days.")
    prune_parser.add_argument("--all", action="store_true", dest="prune_all", help="Confirm deleting ALL quarantine when no selector is given.")
    prune_parser.add_argument("--yes", action="store_true", help="Actually delete (default is a dry-run that only lists).")
    parser.set_defaults(_run=run, _parser=parser)


def _prep_nothing_to_do(workspace_root, reporter) -> bool:
    """True (after logging a friendly notice) when this workspace is already prepped AND there is
    genuinely nothing to apply — initialized (guard present), `0-sources` empty (the steady end-state,
    shared contract §6), AND no pending by-date→by-dest move the handoff hasn't recorded yet. Both
    `dry-run` and `execute` use this to stop fast (exit 0) instead of replaying a now-stale saved plan
    (which would clobber the files it already moved). Returns False — logging nothing — otherwise.

    The by-dest check is essential: after the user moves photos into `6-photos-by-dest`, `0-sources` is
    empty but prep MUST still re-run to record the move and refresh the handoff (geotag refuses until it
    does). Treating that as "nothing to do" would wedge the mandatory re-prep."""
    from .photos_utils import guard_path, folder_name, handoff_path, by_dest_reprep_pending
    src = os.path.join(workspace_root, folder_name('sources'))
    if not os.path.exists(guard_path(workspace_root)):
        return False
    if os.path.isdir(src) and any(fs for _dp, _dn, fs in os.walk(src) if fs):
        return False
    try:
        with open(handoff_path(workspace_root)) as f:
            _handoff = json.load(f)
    except (OSError, ValueError):
        _handoff = {}
    if by_dest_reprep_pending(workspace_root, _handoff) is not None:
        return False                    # a by-dest move still needs recording — not nothing-to-do
    name = folder_name('sources')
    reporter.log(f"Nothing to do: {name} is empty — this workspace is already prepped. "
                 f"Add media to {name} and re-run `prep plan` to ingest more.", stream="stdout")
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


def run(args):
    CONFIG["jobs"] = getattr(args, "jobs", 4)

    workspace_root = os.getcwd()

    # Scrolling status goes through the reporting seam (cartographer/reporting.py). The active
    # reporter is the module global (default TtySink renders identically to the former direct
    # prints); a caller — tests, the future web console — can inject one before calling run().
    reporter = get_reporter()

    # Workspace lifecycle (prep Section 3.1): a workspace is INITIALIZED once the root sentinel
    # photos-00-workspace-guard exists. An uninitialized workspace (no guard) is the deliberate
    # entry point — prep initializes it (plan/execute detect this via guard-absence and create the
    # structure, move the base dump into 0-sources, and write the guard last). So prep does NOT
    # hard-require the sentinel here. A SEALED workspace is refused below (after the lock).

    # Whole-run workspace lock (shared contract Section 2): acquired once here, before any
    # scan/plan/dry-run/execute, held for the entire run, released on exit. Fail-fast.
    run_lock = WorkspaceLock(workspace_root)
    if not run_lock.acquire():
        owner = run_lock.read_owner() or {}
        detail = f" (pid {owner.get('pid')}, since {owner.get('started_at')})" if owner else ""
        reporter.error(f"Workspace is locked by an in-progress run{detail}; try again when it finishes.")
        sys.exit(1)
    reporter.log(f"Lock acquired: {run_lock.lock_path}")

    try:
        # Sealed/terminal-workspace guard (prep Section 6.2 item 1 / shared 13.7): a successful
        # merge seals the workspace. Prep then hard-stops and mutates nothing. Applies to the prep
        # operations (plan/dry-run/execute); prune-quarantine is a separate maintenance command.
        from .photos_utils import is_sealed, folder_name as _folder_name
        if args.command in ("plan", "dry-run", "execute") and is_sealed(workspace_root):
            reporter.error("Workspace is SEALED (already merged): prep will not run. Nothing was touched.")
            _src = os.path.join(workspace_root, _folder_name('sources'))
            _root_files = [f for f in os.listdir(workspace_root)
                           if os.path.isfile(os.path.join(workspace_root, f)) and not f.startswith('.')]
            _src_entries = os.listdir(_src) if os.path.isdir(_src) else []
            if _root_files or _src_entries:
                reporter.log(f"  A likely new dump is present (files at the root or in {_folder_name('sources')}). "
                             "A sealed workspace is final — move new media into a fresh workspace.")
            sys.exit(2)

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
                sys.exit(3)
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

            cache = WorkspaceCache(workspace_root, read_only=True)
            workflow = WorkspacePrepWorkflow(workspace_root, cache)
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
                sys.exit(2)

        elif args.command == "dry-run":
            from .photos_utils import prep_plan_path, PREP_PLAN_ARTIFACT
            pp = prep_plan_path(workspace_root)
            if not os.path.exists(pp):
                reporter.error(f"No {PREP_PLAN_ARTIFACT} found — run `plan` first.")
                sys.exit(2)
            # Same fast, friendly stop as execute: an already-prepped workspace with an empty 0-sources
            # has nothing to validate — the saved plan is stale (its moves are already applied).
            if _prep_nothing_to_do(workspace_root, reporter):
                sys.exit(0)
            with open(pp, "r") as f:
                plan_data = json.load(f)
            plan = Plan.from_dict(plan_data)

            # Use an in-memory database for dry-run
            cache = WorkspaceCache(workspace_root, in_memory=True)
            executor = PlanExecutor(workspace_root)

            try:
                PlanValidator.validate_plan_preflight(plan, workspace_root)
            except ValueError as e:
                reporter.error(f"Preflight validation failed: {e}")
                sys.exit(1)

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

        elif args.command == "execute":
            from .photos_utils import prep_plan_path, PREP_PLAN_ARTIFACT
            pp = prep_plan_path(workspace_root)
            if not os.path.exists(pp):
                reporter.error(f"No {PREP_PLAN_ARTIFACT} found — run `plan` first.")
                sys.exit(2)
            # Fast, friendly stop on an already-prepped workspace (empty 0-sources) — shared with
            # dry-run, gated on a plan existing so a missing plan still takes the "run plan first" path.
            if _prep_nothing_to_do(workspace_root, reporter):
                sys.exit(0)
            with open(pp, "r") as f:
                plan_data = json.load(f)
            plan = Plan.from_dict(plan_data)

            executor = PlanExecutor(workspace_root)

            try:
                executor.execute(plan)
            except Exception as e:
                reporter.error(f"Execution failed: {e}")
                sys.exit(1)

        elif args.command == "prune-quarantine":
            prune_quarantine(
                workspace_root,
                plan_ids=getattr(args, "plan_ids", None),
                older_than_days=getattr(args, "older_than_days", None),
                do_delete=getattr(args, "yes", False),
                prune_all=getattr(args, "prune_all", False),
            )

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
