#!/usr/bin/env python3
"""photos-3-merge — library-merge phase (the terminal pipeline step for a workspace).

Merge takes a calibrated, finalized `6-photos-by-dest/` staging tree and moves it into the user's
permanent library at `library_root`, never renaming or overwriting a file already in the library;
on success it re-seals the archival package and seals the workspace. The full behavior is specified
in `ingest/workflows/photos-3-merge-workflow.md` (and the shared contract); this is the workflow
built on top of the shared primitives in `photos_utils.py`.

Subcommands: `init-library` (one-time: bless a directory as the permanent library, §4),
`plan` (map by-dest photos to library targets and resolve collisions → `photos-30-merge-plan.json`,
§6/§7/§10.1), `dry-run` (revalidate + display that plan, §10.2), and `execute` (apply it as the §11
place-then-remove move, then — on full success only — re-seal the archive and seal the workspace,
§9.4/§10.3). Preflight enforces all of preconditions 0/0a/0b/0c/1/1a/2/3/4/5 (§3). The whole run holds
the workspace lock and the library-side lock (§12).

The script sits beside `photos_utils.py` and imports the shared infrastructure from it.
"""
import argparse
import concurrent.futures
import errno
import json
import os
import sys
from datetime import datetime, timezone

from .photos_utils import (
    CONFIG, CONTROL_DIR, config_path, handoff_path, guard_path, is_sealed,
    validate_config, validate_merge_config, sha256_file, sha256_text, media_class_for_ext,
    folder_name, FOLDER_ROLES, missing_managed_folders, handoff_content_fingerprint,
    verify_json_dependency, json_dependency, write_json_artifact, write_versioned_json, is_library, write_library_marker,
    library_marker_path, allocate_suffix, suffix_root, max_suffix, ContentHasher, WorkspaceCache,
    journal_path, take_zfs_snapshot, _move_no_clobber, write_db_snapshot, reseal_archival_package,
    write_sealed_marker, WorkspaceLock, LibraryLock,
)

# Calibration / prep artifacts merge READS (never writes — shared contract §13.0a).
HANDOFF_ARTIFACT = "photos-11-handoff.json"
EXECUTABLE_PLAN_ARTIFACT = "photos-24-executable-plan.json"
EXECUTION_SUMMARY_ARTIFACT = "photos-25-execution-summary.json"
COMPLETE_LOG_ARTIFACT = "photos-26-complete-log.json"
ARCHIVE_MANIFEST_ARTIFACT = "photos-26-archive-manifest.json"
# Merge's own artifacts. The plan (photos-30) precedes the terminal summary/log (31/35).
MERGE_PLAN_ARTIFACT = "photos-30-merge-plan.json"
MERGE_SUMMARY_ARTIFACT = "photos-31-merge-summary.json"
MERGE_LOG_ARTIFACT = "photos-35-merge-log.json"
MERGE_DB_SNAPSHOT = "photos-35-merge-ingest.db"
MERGE_PLAN_SCHEMA_VERSION = 1


def _cd(ws, name):
    return os.path.join(ws, CONTROL_DIR, name)


def executable_plan_path(ws):
    return _cd(ws, EXECUTABLE_PLAN_ARTIFACT)


def execution_summary_path(ws):
    return _cd(ws, EXECUTION_SUMMARY_ARTIFACT)


def complete_log_path(ws):
    return _cd(ws, COMPLETE_LOG_ARTIFACT)


def archive_manifest_path(ws):
    return _cd(ws, ARCHIVE_MANIFEST_ARTIFACT)


def merge_plan_path(ws):
    return _cd(ws, MERGE_PLAN_ARTIFACT)


def merge_summary_path(ws):
    return _cd(ws, MERGE_SUMMARY_ARTIFACT)


def merge_log_path(ws):
    return _cd(ws, MERGE_LOG_ARTIFACT)


def merge_db_snapshot_path(ws):
    return _cd(ws, MERGE_DB_SNAPSHOT)


class MergeWorkflow:
    """Library-merge workflow: preflight (§3), plan/dry-run/execute, and — on full success only — the
    terminal outputs (summary, merge log, DB snapshot, archive re-seal, workspace seal, §9.4)."""

    def __init__(self, workspace_root: str):
        self.workspace_root = workspace_root
        self.handoff = None
        self.calib_plan = None      # photos-24 parsed once in preflight; reused by the plan builder

    # --- preflight (merge spec §3) -------------------------------------------

    def preflight(self):
        """Return (blockers, warnings, info). A non-empty `blockers` means merge cannot proceed; it is
        textual only and writes no JSON. The lifecycle/structural/config/marker/handoff guards
        hard-stop early (each a prerequisite for the checks after it); the remaining preconditions
        (0b, 1, 1a, 2, 3, 4) are gathered so every problem is reported at once.

        NOTE: config validation + the `.photos-library` marker identity check happen HERE, under the
        workspace lock, BEFORE main() acquires the library lock (merge spec §12) — so no
        `.photos-merge.lock` is ever dropped into a directory that is not a blessed library."""
        blockers, warnings, info = [], [], {}
        ws = self.workspace_root

        # 0. Terminal-seal check — sealed means sealed (§3 precond 0; shared contract §13.7).
        if is_sealed(ws):
            blockers.append("Workspace is SEALED (a prior merge fully succeeded): merge will not run. "
                            "Nothing was touched — move any new media into a fresh workspace.")
            if self._root_files() or self._entries(folder_name('sources')):
                warnings.append("A likely new dump is present (files at the workspace root or in "
                                f"{folder_name('sources')}/). A sealed workspace is final; move it into "
                                "a fresh workspace by hand — merge left it exactly where it is.")
            return blockers, warnings, info

        # 0a. Initialized, and no misplaced entry at the workspace root (§3 precond 0a; shared §5.3).
        if not os.path.exists(guard_path(ws)):
            blockers.append("Not an initialized workspace (no photos-00-workspace-guard) — "
                            "run prep first: `photos-ingest prep plan` then `photos-ingest prep execute`.")
            return blockers, warnings, info
        root_syms = self._root_symlinks()
        if root_syms:
            blockers.append(f"Forbidden symlink at the workspace root: {root_syms[0]}. Symlinks are "
                            "never followed; remove it before merging.")
            return blockers, warnings, info
        # 0c. The managed 0-6 structure must be intact (§3 precond 0c) — merge never creates/repairs it.
        struct_missing = missing_managed_folders(ws)
        if struct_missing:
            blockers.append("Workspace is non-conforming: missing managed folder(s): "
                            f"{', '.join(struct_missing)}. Restore the 0-6 structure (merge never "
                            "creates or repairs it) before merging.")
            return blockers, warnings, info
        loose = self._root_files()
        if loose:
            blockers.append(f"Loose file at the workspace root (dumps belong in "
                            f"{folder_name('sources')}/): {loose[0]}. The base must hold only folders.")
            return blockers, warnings, info
        loose_dirs = self._root_nonmanaged_dirs()
        if loose_dirs:
            blockers.append(f"Misplaced folder at the workspace root (dumps belong in "
                            f"{folder_name('sources')}/): {loose_dirs[0]}. The base must hold only "
                            "the managed folders.")
            return blockers, warnings, info

        # Config (read-only) — must exist and be valid; merge's data path never writes it.
        cfg_p = config_path(ws)
        if not os.path.exists(cfg_p):
            blockers.append("Workspace config photos-00-config.json is missing — run prep first: `photos-ingest prep plan` then `photos-ingest prep execute`.")
            return blockers, warnings, info
        try:
            with open(cfg_p) as f:
                cfg = json.load(f)
            validate_config(cfg)
        except ValueError as e:
            blockers.append(f"Invalid workspace config: {e}")
            return blockers, warnings, info
        except Exception as e:
            blockers.append(f"Workspace config could not be read: {e}")
            return blockers, warnings, info
        CONFIG.update(cfg)              # adopt the seeded config as authoritative for this run

        # 5. Config valid + library_root is a blessed library (§3 precond 5; merge spec §4). The
        # deep merge-config validation and the marker check run before the library lock (§12).
        try:
            validate_merge_config(cfg, ws)
        except ValueError as e:
            blockers.append(str(e))
            return blockers, warnings, info
        library_root = cfg["merge"]["library_root"]
        if not is_library(library_root):
            blockers.append(f"{library_root} is not a blessed library (the {os.path.basename(library_marker_path(library_root))} "
                            "marker is absent). Run `photos-ingest merge init-library` to bless it first.")
            return blockers, warnings, info
        info["library_root"] = library_root

        # Handoff (read-only) — needed for the prep-consistency / currency checks below.
        ho_p = handoff_path(ws)
        if not os.path.exists(ho_p):
            blockers.append("Prep handoff photos-11-handoff.json is missing — run prep first: `photos-ingest prep plan` then `photos-ingest prep execute`.")
            return blockers, warnings, info
        try:
            with open(ho_p) as f:
                handoff = json.load(f)
        except Exception as e:
            blockers.append(f"Prep handoff could not be read: {e}")
            return blockers, warnings, info
        info["handoff_sha256"] = sha256_file(ho_p)
        self.handoff = handoff

        # ---- Gathered preconditions (report every problem at once) ----------
        # 0b. 0-sources empty (§3 precond 0b).
        if self._entries(folder_name('sources')):
            blockers.append(f"{folder_name('sources')}/ is not empty — an unprocessed dump is waiting; "
                            "merge requires it empty. Re-run prep to process it: `photos-ingest prep plan` then `photos-ingest prep execute`.")

        # 1 + 1a. Calibration ended successfully, and the finalized record is current with by-dest.
        calib_plan = self._check_calibration_finalized(ws, handoff, blockers)
        self.calib_plan = calib_plan       # stash for the plan builder (plan/dry-run)

        # 2. The workspace was finalized (§3 precond 2).
        if not os.path.exists(complete_log_path(ws)):
            blockers.append("The workspace has not been finalized (photos-26-complete-log.json is "
                            "missing). Run the finalize command (`photos-ingest geotag finalize`) first, "
                            "then merge.")
        if not os.path.exists(archive_manifest_path(ws)):
            blockers.append("The archival package is incomplete (photos-26-archive-manifest.json is "
                            "missing) — run `photos-ingest geotag finalize` before merging.")

        # 3. By-dest is the clean photo-only set (§3 precond 3).
        self._check_by_dest_clean(blockers, info)

        # 4. Prep-consistency against the finalized-name set (§3 precond 4) — needs photos-24. Built on
        # the handoff⨝photos-24 enumeration because calibration renamed by-dest without re-keying it.
        if calib_plan is not None:
            self._check_prep_consistency(handoff, calib_plan, info["library_root"], blockers)

        return blockers, warnings, info

    def _check_calibration_finalized(self, ws, handoff, blockers):
        """Preconditions 1 and 1a. Calibration must have produced an executed plan (photos-24) with a
        successful execution summary (photos-25), and the finalized record must still be current with
        by-dest: the CURRENT handoff's content fingerprint must equal the one photos-24 pinned as a
        dependency. A no-op re-prep (run-metadata only) does not trip this; only a real by-dest content
        change does — that one needs re-calibrate + re-finalize, not just re-prep (distinct from §3.4)."""
        plan_p = executable_plan_path(ws)
        summ_p = execution_summary_path(ws)
        plan = None
        if not os.path.exists(plan_p):
            blockers.append("Calibration has not produced an executable plan "
                            "(photos-24-executable-plan.json is missing) — run `photos-ingest geotag plan` "
                            "then `execute` before merging.")
        else:
            try:
                with open(plan_p) as f:
                    plan = json.load(f)
            except Exception as e:
                blockers.append(f"Calibration plan photos-24-executable-plan.json could not be read: {e}")
        if not os.path.exists(summ_p):
            blockers.append("Calibration was not executed (photos-25-execution-summary.json is missing) "
                            "— run `photos-ingest geotag execute` before merging.")
        else:
            try:
                with open(summ_p) as f:
                    summ = json.load(f)
                if summ.get("status") != "success":
                    blockers.append("Calibration execution did not end successfully "
                                    f"(photos-25 status={summ.get('status')!r}) — resolve it and re-run "
                                    "`photos-ingest geotag execute` before merging.")
            except Exception as e:
                blockers.append(f"Calibration execution summary could not be read: {e}")

        if plan is None:
            return None
        dep = (plan.get("depends_on") or {}).get("handoff")
        if not dep:
            blockers.append("The calibration plan records no handoff dependency — re-calibrate and "
                            "re-finalize before merging.")
            return plan
        if dep.get("dependency_type") == "handoff_content":
            ok = handoff_content_fingerprint(handoff) == dep.get("content_fingerprint")
        else:
            ok = verify_json_dependency(dep, ws)   # legacy byte-hash handoff dependency
        if not ok:
            blockers.append("By-dest has changed since calibration was finalized (the current handoff's "
                            "content fingerprint no longer matches the one photos-24-executable-plan.json "
                            "recorded). Re-calibrate and re-finalize before merging — a present but "
                            "un-calibrated photo must not be merged.")
        return plan

    def _check_by_dest_clean(self, blockers, info):
        """Precondition 3. 5-photos-by-date holds no photos; 6-photos-by-dest holds only image/raw
        (no videos, no non-media), has no jpg/tif development subfolder, and contains no symlinks."""
        by_date = folder_name('photos_by_date')
        by_dest = folder_name('photos_by_dest')
        stray = [rel for rel, mc in self._scan_media(by_date) if mc in ("image", "raw")]
        if stray:
            blockers.append(f"{by_date}/ still contains {len(stray)} photo(s) — by-dest must be the "
                            f"complete set before merging (e.g. {stray[0]}).")
        dev_found, nonphoto = self._scan_by_dest(by_dest)
        if dev_found:
            names = ", ".join(sorted(set(CONFIG.get("destination_distribution_subfolders") or [])))
            blockers.append(f"A development subfolder ({names}) exists under {by_dest}: {dev_found[0]}. "
                            "The jpg/tif breakout is a later library-side phase; merge requires the "
                            "photo-only set.")
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
                            ". Remove or relocate them before merging.")
        syms = self._by_dest_symlinks(by_dest)
        if syms:
            blockers.append(f"Forbidden symlink under {by_dest}: {syms[0]}. Symlinks are never followed "
                            "into or out of the managed tree; remove it before merging.")
        info["by_dest_photos"] = sum(1 for _, mc in self._scan_media(by_dest) if mc in ("image", "raw"))

    # --- finalized-name enumeration + prep-consistency (merge spec §3.4 / §10.1) ---

    def enumerate_finalized(self, calib_plan, library_root):
        """The by-dest photo set to merge, built from the FINALIZED record (not a disk scan): the
        handoff's by-dest photos joined to photos-24's rename ops by content fingerprint. Each entry
        carries its final on-disk by-dest path, its library-relative destination, final name, content
        fingerprint, and library target. Robust to a handoff that carries pre- OR post-rename names —
        the fingerprint join is name-independent (calibration renamed by-dest without re-keying it)."""
        by_dest = folder_name('photos_by_dest')
        final_by_fp = {}
        for dd in (calib_plan.get("destinations") or {}).values():
            for op in dd.get("operations") or []:
                if op.get("type") == "rename_no_clobber":
                    fp = (op.get("preconditions") or {}).get("content_fingerprint")
                    if fp:
                        final_by_fp[fp] = op.get("to")
        entries = []
        for rec in (self.handoff.get("files") or []):
            if rec.get("folder_class") != by_dest or rec.get("media_class") not in ("image", "raw"):
                continue
            fp = _record_fingerprint(rec)
            rel = rec.get("relative_path") or ""
            ddir = os.path.dirname(rel)                       # 6-photos-by-dest/Belgium/Brussels
            lib_dest = os.path.relpath(ddir, by_dest)         # Belgium/Brussels (or "." at by-dest root)
            lib_dest = "" if lib_dest == "." else lib_dest
            final_name = final_by_fp.get(fp) or os.path.basename(rel)
            by_dest_relpath = os.path.join(ddir, final_name)  # workspace-relative on-disk path
            target = (os.path.join(library_root, lib_dest, final_name) if lib_dest
                      else os.path.join(library_root, final_name))
            entries.append({"content_fingerprint": fp, "lib_dest": lib_dest, "final_name": final_name,
                            "by_dest_relpath": by_dest_relpath, "library_target": target})
        entries.sort(key=lambda e: e["by_dest_relpath"])
        return entries

    def _check_prep_consistency(self, handoff, calib_plan, library_root, blockers):
        """Precondition 4: every photo file actually under 6-photos-by-dest must be in the finalized
        set (matched by its final on-disk name). A disk photo with no finalized record means prep was
        not re-run after the latest move into by-dest — a 're-run prep' blocker. The converse (a
        finalized entry whose file is gone) is the already-merged/resume case, not a blocker."""
        by_dest = folder_name('photos_by_dest')
        expected = {e["by_dest_relpath"] for e in self.enumerate_finalized(calib_plan, library_root)}
        unrecorded = sorted(rel for rel, mc in self._scan_media(by_dest)
                            if mc in ("image", "raw") and rel not in expected)
        if unrecorded:
            blockers.append(f"{by_dest} contains {len(unrecorded)} photo(s) the finalized record does "
                            f"not recognize (e.g. {unrecorded[0]}) — the handoff predates the latest "
                            "move into by-dest. Re-run prep to refresh the handoff — `photos-ingest prep execute` (run `photos-ingest prep plan` first only if 0-sources still holds a dump) — then merge.")

    # --- plan builder (merge spec §6 mapping, §7 collision, §10.1 plan) -------

    def build_merge_plan(self, ws, calib_plan, library_root, cache):
        """Map each finalized by-dest photo to its library target and resolve collisions by content
        fingerprint (append-at-max+1). Non-mutating except populating the library-file fingerprint
        cache. Returns the serialized plan dict (the photos-30-merge-plan.json body)."""
        entries = self.enumerate_finalized(calib_plan, library_root)
        # Per-library-dir occupancy: existing library names + this run's whole incoming batch (+ any
        # name allocated so far). max_suffix over it gives max(library, incoming) for append-at-max+1.
        batch_by_dir = {}
        for e in entries:
            batch_by_dir.setdefault(e["lib_dest"], []).append(e["final_name"])
        occ_names, occ_lower = {}, {}

        def _occ(lib_dest):
            if lib_dest not in occ_names:
                d = os.path.join(library_root, lib_dest) if lib_dest else library_root
                existing = list(os.listdir(d)) if os.path.isdir(d) else []
                names = existing + batch_by_dir.get(lib_dest, [])
                occ_names[lib_dest] = list(names)
                occ_lower[lib_dest] = {n.lower() for n in names}
            return occ_names[lib_dest], occ_lower[lib_dest]

        dests, blockers = {}, []
        totals = {"placed_new": 0, "already_present": 0, "renamed_for_library": 0, "blocked": 0}
        for e in entries:
            src_abs = os.path.join(ws, e["by_dest_relpath"])
            if not os.path.exists(src_abs):
                continue                       # finalized entry already moved/absent: resume case
            st = os.stat(src_abs)
            rec = {"by_dest_source": e["by_dest_relpath"], "content_fingerprint": e["content_fingerprint"],
                   "preconditions": {"size": st.st_size, "mtime_ns": st.st_mtime_ns,
                                     "content_fingerprint": e["content_fingerprint"]}}
            target = e["library_target"]
            if not os.path.exists(target):
                rec.update({"disposition": "placed_new", "library_target": target,
                            "resolved_name": e["final_name"], "renamed_for_library": False})
                totals["placed_new"] += 1
            else:
                lib_fp, fp_err = self._library_fingerprint(target, cache)
                if lib_fp is None:
                    reason = f"library file at {target} could not be fingerprinted: {fp_err}"
                    rec.update({"disposition": "blocked", "library_target": target,
                                "resolved_name": e["final_name"], "renamed_for_library": False,
                                "blocked_reason": reason})
                    totals["blocked"] += 1
                    blockers.append(reason + " — left in by-dest.")
                elif lib_fp == e["content_fingerprint"]:
                    rec.update({"disposition": "already_present", "library_target": target,
                                "resolved_name": e["final_name"], "renamed_for_library": False})
                    totals["already_present"] += 1
                else:
                    names, lower = _occ(e["lib_dest"])
                    stem, dot, ext = e["final_name"].rpartition(".")
                    root = suffix_root(stem if dot else e["final_name"])
                    start = max_suffix(root, names) + 1
                    new_name = allocate_suffix(root, ext if dot else "", lower, start_idx=start)
                    names.append(new_name)
                    new_target = (os.path.join(library_root, e["lib_dest"], new_name) if e["lib_dest"]
                                  else os.path.join(library_root, new_name))
                    rec.update({"disposition": "renamed_incoming", "library_target": new_target,
                                "resolved_name": new_name, "renamed_for_library": True,
                                "renamed_from": e["final_name"],
                                "library_collision": {"path": target, "fingerprint": lib_fp}})
                    totals["renamed_for_library"] += 1
            dests.setdefault(e["lib_dest"], {"files": []})["files"].append(rec)

        for d in dests.values():
            d["files"].sort(key=lambda r: r["by_dest_source"])
        depends_on = {
            "photos-24-executable-plan.json": json_dependency(
                EXECUTABLE_PLAN_ARTIFACT, ws, executable_plan_path(ws)),
            "photos-25-execution-summary.json": json_dependency(
                EXECUTION_SUMMARY_ARTIFACT, ws, execution_summary_path(ws)),
            "handoff": {"dependency_type": "handoff_content", "artifact_name": HANDOFF_ARTIFACT,
                        "content_fingerprint": handoff_content_fingerprint(self.handoff)},
            "config_fingerprint": sha256_file(config_path(ws)),
        }
        plan = {
            "artifact_type": "merge_plan", "artifact_name": MERGE_PLAN_ARTIFACT,
            "schema_version": MERGE_PLAN_SCHEMA_VERSION, "library_root": library_root,
            "placement_policy": (CONFIG.get("merge") or {}).get("placement_policy"),
            "collision_policy": (CONFIG.get("merge") or {}).get("collision_policy"),
            "depends_on": depends_on, "destinations": dests, "totals": totals, "blockers": blockers,
        }
        plan["plan_id"] = sha256_text(json.dumps(
            {"depends_on": depends_on, "destinations": dests, "library_root": library_root},
            sort_keys=True))[:16]
        return plan

    def _library_fingerprint(self, abs_path, cache):
        """Content fingerprint of a resident library file, cached by path+size/mtime so it is read at
        most once per run / across re-runs while unchanged (§7). Returns (value, None) on success or
        (None, reason) if it cannot be fingerprinted."""
        try:
            st = os.stat(abs_path)
        except OSError as e:
            return None, str(e)
        hit = cache.get_cached_library_fingerprint(abs_path, st.st_size, st.st_mtime_ns) if cache else None
        if hit and hit.get("value"):
            return hit["value"], None
        fp = self._fingerprint_library_file(abs_path)
        if fp.get("status") == "valid" and fp.get("value"):
            if cache:
                cache.cache_library_fingerprint(abs_path, st.st_size, st.st_mtime_ns, fp)
            return fp["value"], None
        return None, fp.get("error") or "fingerprint failed"

    def _fingerprint_library_file(self, abs_path):
        """The seam tests mock to avoid invoking ImageMagick. Library targets are photos (image/raw),
        so the EXIF-invariant pixel-content hash applies."""
        return ContentHasher.fingerprint_image(abs_path)

    def revalidate_plan_deps(self, ws, plan):
        """Re-check the saved plan's recorded dependencies against current state (non-mutating). A
        non-empty list means the plan is stale and must be re-planned. Full per-file precondition
        revalidation + execute-time no-clobber happen per file in execute (_move_file)."""
        stale = []
        if plan.get("schema_version") != MERGE_PLAN_SCHEMA_VERSION:
            stale.append(f"plan schema_version {plan.get('schema_version')} is not "
                         f"{MERGE_PLAN_SCHEMA_VERSION}")
        dep = plan.get("depends_on") or {}
        for key in ("photos-24-executable-plan.json", "photos-25-execution-summary.json"):
            d = dep.get(key)
            if not (d and verify_json_dependency(d, ws)):
                stale.append(f"{key} changed or missing")
        ho = dep.get("handoff")
        if not (ho and ho.get("dependency_type") == "handoff_content"
                and handoff_content_fingerprint(self.handoff) == ho.get("content_fingerprint")):
            stale.append("handoff content fingerprint changed")
        cfp = dep.get("config_fingerprint")
        if cfp and cfp != sha256_file(config_path(ws)):
            stale.append("config changed")
        return stale

    def do_plan(self, ws, library_root):
        # Don't re-plan over a merge that has already been (partly) applied but not sealed. A prior
        # execute — whether it ended `partial` (a blocker left in by-dest) or `success` but crashed
        # before the seal — already moved some finalized photos into the library (their by-dest
        # sources are gone). Re-planning would `continue` past them (build_merge_plan) and omit them
        # from the merge log a later execute writes — and an already-placed *renamed* file can't be
        # reliably re-located on a fresh plan. The correct resume is `execute`, which reuses the saved
        # photos-30 (still complete) and finishes/seals. (do_plan is only reached on an UNSEALED
        # workspace — precondition 0 blocks a sealed one — so a present summary means an in-flight
        # merge; a `rejected` summary moved nothing, so re-planning after it is safe and allowed.)
        if os.path.exists(merge_plan_path(ws)) and \
                _json_get(merge_summary_path(ws), "status") in ("partial", "success"):
            print(f"A prior merge is in flight but not sealed ({MERGE_SUMMARY_ARTIFACT} present on an "
                  "unsealed workspace): some photos are already in the library. Run `execute` to resume "
                  f"the saved {MERGE_PLAN_ARTIFACT} — it finishes any remaining moves, writes a log "
                  "covering every file, and seals. Re-planning now would drop the already-moved files "
                  f"from the merge log. (To re-plan from scratch instead, remove {MERGE_SUMMARY_ARTIFACT} "
                  "first.)", file=sys.stderr)
            return 2
        cache = WorkspaceCache(ws)
        try:
            plan = self.build_merge_plan(ws, self.calib_plan, library_root, cache)
        finally:
            cache.close()
        mpp = merge_plan_path(ws)
        _, _mp_bak = write_versioned_json(mpp, plan)
        t = plan["totals"]
        print(f"Wrote {MERGE_PLAN_ARTIFACT}: plan {plan['plan_id']} — {t['placed_new']} new, "
              f"{t['already_present']} already-present, {t['renamed_for_library']} renamed, "
              f"{t['blocked']} blocked.")
        print(f"  Plan saved to {mpp}")
        if _mp_bak:
            print(f"  Previous plan backed up to {_mp_bak}")
        print("  Review it, `dry-run` to display, then `execute`.")
        for b in plan["blockers"]:
            print(f"  Blocker: {b}", file=sys.stderr)
        return 0

    def do_dry_run(self, ws):
        p = merge_plan_path(ws)
        if not os.path.exists(p):
            print(f"No {MERGE_PLAN_ARTIFACT} — run `plan` first.", file=sys.stderr)
            return 2
        with open(p) as f:
            plan = json.load(f)
        stale = self.revalidate_plan_deps(ws, plan)
        if stale:
            print("\nThe saved merge plan is stale — re-run `plan`:", file=sys.stderr)
            for s in stale:
                print(f"  - {s}", file=sys.stderr)
            return 2
        # Dry-run validates the REAL saved plan and reports a SUMMARY; the full exact plan is the
        # saved artifact at `p`, so there is no need to dump every move to the terminal.
        n = sum(len(d.get("files", [])) for d in (plan.get("destinations") or {}).values())
        t = plan.get("totals", {})
        print(f"Dry-run: validated plan {plan.get('plan_id')} — {n} move(s).")
        print(f"  new: {t.get('placed_new', 0)}, already-present: {t.get('already_present', 0)}, "
              f"renamed: {t.get('renamed_for_library', 0)}, blocked: {t.get('blocked', 0)}")
        _bl = plan.get("blockers") or []
        if _bl:
            print(f"  BLOCKERS: {len(_bl)} — execute will refuse:")
            for b in _bl[:20]:
                print(f"    - {b}")
            if len(_bl) > 20:
                print(f"    … and {len(_bl) - 20} more")
        print(f"  Full plan: {p}")
        return 0

    # --- execute: place-then-remove, journal, resume, concurrency (§10.3/§11) ---

    def _verify_fp(self, path, expected_fp):
        """True iff `path` fingerprints (via the seam) to `expected_fp`. Used to confirm a library copy
        or a by-dest source is the planned content before removing/finishing a move."""
        r = self._fingerprint_library_file(path)
        return r.get("status") == "valid" and r.get("value") == expected_fp

    def _verify_copy(self, tmp_path, expected_fp):
        """Cross-fs copy-verify hook (§11.2): raise if the temp copy's fingerprint != the planned one
        (a torn / silently-corrupted copy), aborting the move before it is exposed under the target."""
        if not self._verify_fp(tmp_path, expected_fp):
            raise OSError(errno.EIO, f"library copy fingerprint mismatch (torn copy) for {tmp_path}")

    @staticmethod
    def _plan_kind(disp):
        return {"placed_new": "placed_new", "renamed_incoming": "renamed_for_library",
                "already_present": "already_present"}.get(disp, "placed_new")

    def _move_file(self, ws, library_root, rec, journal):
        """Apply one planned move as the §11 place-then-remove, with state-derivation resume (§8.3) and
        execute-time no-clobber. Per-file isolated (touches only this file's source, temp, and target);
        returns a result the executor aggregates — workers never mutate shared state or the journal."""
        src_rel = rec["by_dest_source"]
        src_abs = os.path.join(ws, src_rel)
        target = rec["library_target"]
        fp = rec["content_fingerprint"]
        disp = rec["disposition"]
        out = {"by_dest_source": src_rel, "library_path": target, "content_fingerprint": fp,
               "final_kind": None, "removed": False, "newly": False, "blocker": None}

        if journal.get(src_rel) == "confirmed":           # already terminal in a prior run
            out["final_kind"] = self._plan_kind(disp)
            out["removed"] = True
            return out
        if disp == "blocked":                             # plan-time per-item blocker (un-fingerprintable)
            out["final_kind"] = "blocked"
            out["blocker"] = rec.get("blocked_reason") or f"{src_rel}: blocked at plan time"
            return out

        src_present = os.path.exists(src_abs)

        if disp == "already_present":
            # Library already holds identical content (verified at plan). Re-confirm it still matches,
            # then remove the source — never delete the only copy if the library file changed.
            if not src_present:
                out["final_kind"] = "already_present"
                out["removed"] = True
                return out
            if not self._verify_fp(target, fp):
                out["final_kind"] = "blocked"
                out["blocker"] = (f"{src_rel}: library file {target} no longer matches the planned "
                                  "content (changed since plan); left in by-dest")
                return out
            os.unlink(src_abs)
            out.update({"final_kind": "already_present", "removed": True, "newly": True})
            return out

        # placed_new / renamed_incoming -> move source into the library target.
        if not src_present:
            if os.path.exists(target) and self._verify_fp(target, fp):
                out["final_kind"] = self._plan_kind(disp)   # already moved by a prior run
                out["removed"] = True
                return out
            out["final_kind"] = "blocked"
            out["blocker"] = f"{src_rel}: source missing at execute and not present in the library"
            return out
        if os.path.exists(target):
            if self._verify_fp(target, fp):                 # crash between rename and unlink: finish it
                os.unlink(src_abs)
                out.update({"final_kind": self._plan_kind(disp), "removed": True, "newly": True})
                return out
            out["final_kind"] = "blocked"
            out["blocker"] = f"{src_rel}: target {target} occupied by different content at execute (re-plan)"
            return out

        pre = rec.get("preconditions") or {}
        st = os.stat(src_abs)
        if (pre.get("size") is not None and st.st_size != pre["size"]) or \
           (pre.get("mtime_ns") is not None and st.st_mtime_ns != pre["mtime_ns"]):
            if not self._verify_fp(src_abs, fp):            # size/mtime AND content differ -> changed
                out["final_kind"] = "blocked"
                out["blocker"] = (f"{src_rel}: by-dest file changed since plan "
                                  "(size/mtime + content differ); re-plan")
                return out

        try:
            os.makedirs(os.path.dirname(target) or ".", exist_ok=True)   # additive placement (§6)
            _move_no_clobber(src_abs, target, verify=lambda s, t: self._verify_copy(t, fp))
            out.update({"final_kind": self._plan_kind(disp), "removed": True, "newly": True})
        except FileExistsError:                             # target appeared since planning
            if os.path.exists(target) and self._verify_fp(target, fp):
                os.unlink(src_abs)                          # identical content -> already in library
                out.update({"final_kind": "already_present", "removed": True, "newly": True})
            else:
                out["final_kind"] = "blocked"
                out["blocker"] = f"{src_rel}: target occupied by different content at execute (re-plan)"
        except Exception as e:
            out["final_kind"] = "blocked"
            out["blocker"] = f"{src_rel}: move failed ({e})"
        return out

    def execute_plan(self, ws, library_root, jobs, now_iso, execution_id):
        """Apply photos-30 after revalidating its dependencies, taking the optional library snapshot,
        moving each file (concurrent), journaling confirmed completions (single-writer, main thread),
        and writing photos-31-merge-summary.json. Returns the result dict (status no_plan / rejected /
        success / partial)."""
        p = merge_plan_path(ws)
        if not os.path.exists(p):
            return {"status": "no_plan"}
        with open(p) as f:
            plan = json.load(f)
        stale = self.revalidate_plan_deps(ws, plan)
        if stale:
            return {"status": "rejected", "plan_id": plan.get("plan_id"), "stale": stale}

        # Pre-mutation snapshot of the LIBRARY volume (§10.3 step 3), labelled "merge". A required
        # snapshot that cannot be taken aborts before any placement; the record goes into the summary.
        snapshot = take_zfs_snapshot(ws, plan["plan_id"], "merge",
                                     target_path=library_root, dataset_key="library")
        if snapshot is not None and snapshot["required"] and not snapshot["ok"]:
            reason = f"required ZFS pre-mutation snapshot of the library failed: {snapshot['stderr']}"
            summary = self._build_summary(ws, plan, library_root, [], snapshot, "rejected",
                                          now_iso, execution_id, jobs, extra_failures=[reason])
            write_json_artifact(merge_summary_path(ws), summary)
            return {"status": "rejected", "plan_id": plan.get("plan_id"), "stale": [reason],
                    "snapshot": snapshot}

        jpath = journal_path(ws, plan["plan_id"])
        journal = {}
        if os.path.exists(jpath):
            try:
                journal = (json.load(open(jpath)) or {}).get("operations", {}) or {}
            except Exception:
                journal = {}

        recs = sorted((f for d in plan.get("destinations", {}).values() for f in d.get("files", [])),
                      key=lambda r: r["by_dest_source"])
        results = []
        try:
            with concurrent.futures.ThreadPoolExecutor(max_workers=max(1, jobs)) as ex:
                futs = [ex.submit(self._move_file, ws, library_root, rec, journal) for rec in recs]
                try:
                    for fut in concurrent.futures.as_completed(futs):
                        r = fut.result()
                        results.append(r)
                        # Incremental confirmation journal (§8.3): persist each completion AS IT FINISHES,
                        # in this main thread (workers never touch the journal), so a crash mid-run lets the
                        # next run skip the already-moved files.
                        if r["removed"]:
                            journal[r["by_dest_source"]] = "confirmed"
                            write_json_artifact(jpath, {"journal_version": 1, "plan_id": plan["plan_id"],
                                                        "operations": journal, "updated_at": now_iso})
                except KeyboardInterrupt:
                    # Ctrl-C: drop pending moves and stop waiting instead of letting the `with` exit
                    # drain them (shutdown(wait=True)). Files already moved are confirmed in the journal
                    # above, so the next run resumes from the diff (§8.3). Re-raise to main().
                    ex.shutdown(wait=False, cancel_futures=True)
                    raise
        finally:
            from .photos_utils import PersistentMagickWorker
            PersistentMagickWorker.cleanup_all()      # close the per-thread magick workers (verify pass)

        results.sort(key=lambda r: r["by_dest_source"])
        status = "success" if not any(r["final_kind"] == "blocked" for r in results) else "partial"
        finished_at = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        summary = self._build_summary(ws, plan, library_root, results, snapshot, status,
                                      now_iso, execution_id, jobs, finished_at=finished_at)
        write_json_artifact(merge_summary_path(ws), summary)
        finalized = None
        if status == "success":
            finalized = self._finalize_terminal(ws, plan, library_root, results, execution_id, now_iso)
        return {"status": status, "plan_id": plan.get("plan_id"), "summary": summary, "finalized": finalized,
                "blocked": [r for r in results if r["final_kind"] == "blocked"]}

    def _build_merge_log(self, ws, results):
        """photos-35-merge-log.json (§9.2): photos-26-complete-log.json copied FORWARD with a per-file
        `merge` step appended to each merged photo's journey (final library path + renamed flag). Built
        fresh from photos-26 every run (never from a prior photos-35), so it is deterministic and
        idempotent under resume; photos-26 itself is never edited (§13.0a)."""
        base = {}
        if os.path.exists(complete_log_path(ws)):
            try:
                base = json.load(open(complete_log_path(ws)))
            except Exception:
                base = {}
        photos = json.loads(json.dumps(base.get("photos") or {}))      # deep copy; never touch photos-26
        for r in sorted(results, key=lambda x: x["by_dest_source"]):
            if r["final_kind"] == "blocked" or not r.get("content_fingerprint"):
                continue
            fp = r["content_fingerprint"]
            entry = photos.setdefault(fp, {"content_fingerprint": fp, "journey": []})
            entry.setdefault("journey", []).append({
                "phase": "merge",
                "action": "already_present" if r["final_kind"] == "already_present" else "placed",
                "library_path": r["library_path"],
                "renamed_for_library": r["final_kind"] == "renamed_for_library"})
        return {"schema_version": 1, "tool": "photos-3-merge", "artifact_name": MERGE_LOG_ARTIFACT,
                "photos": photos}

    def _finalize_terminal(self, ws, plan, library_root, results, execution_id, now_iso):
        """Full-success terminal bookkeeping (§9.4 / §10.3 steps 7-10), in order, SEAL LAST. Each step
        is rebuilt from pristine inputs (never from a prior merge artifact), so a crash before the seal
        re-runs cleanly. Runs only when status == success (no blockers, by-dest empty of photos)."""
        # 1. Merge log (copy photos-26 forward + per-file merge step).
        write_json_artifact(merge_log_path(ws), self._build_merge_log(ws, results))
        # 2. End-of-merge DB snapshot of the live workspace DB (captures the library-fingerprint cache).
        cache = WorkspaceCache(ws)
        try:
            write_db_snapshot(cache.conn, merge_db_snapshot_path(ws))
        finally:
            cache.close()
        # 3. Re-seal: merge's own photos-35-archive-manifest.json (supersedes the photos-26 manifest).
        manifest_sha = reseal_archival_package(
            ws, workspace_name=os.path.basename(os.path.abspath(ws)), plan_id=plan.get("plan_id"),
            execution_id=execution_id, merge_run_id=execution_id, generated_at=now_iso)
        # 4. Seal — the LAST write of the run; afterwards every phase hard-stops on this workspace.
        write_sealed_marker(ws, execution_id, library_root)
        return {"sealed": True, "merge_log": MERGE_LOG_ARTIFACT, "db_snapshot": MERGE_DB_SNAPSHOT,
                "archive_manifest": "photos-35-archive-manifest.json", "manifest_sha256": manifest_sha}

    def _build_summary(self, ws, plan, library_root, results, snapshot, status, now_iso,
                       execution_id, jobs, finished_at=None, extra_failures=None):
        kinds = {"placed_new": 0, "already_present": 0, "renamed_for_library": 0, "blocked": 0}
        newly = already_done = 0
        failures = list(extra_failures or [])
        dests = {}
        by_dest = folder_name('photos_by_dest')
        for r in results:
            kinds[r["final_kind"]] = kinds.get(r["final_kind"], 0) + 1
            if r["final_kind"] != "blocked":
                newly += 1 if r["newly"] else 0
                already_done += 0 if r["newly"] else 1
            if r["blocker"]:
                failures.append(r["blocker"])
            dest = os.path.dirname(os.path.relpath(r["by_dest_source"], by_dest))
            dests.setdefault(dest, {"files": []})["files"].append({
                "by_dest_path": r["by_dest_source"], "library_path": r["library_path"],
                "renamed_for_library": r["final_kind"] == "renamed_for_library",
                "already_present": r["final_kind"] == "already_present",
                "removed_from_by_dest": r["removed"]})
        for d in dests.values():
            d["files"].sort(key=lambda f: f["by_dest_path"])
        removed_total = kinds["placed_new"] + kinds["already_present"] + kinds["renamed_for_library"]
        return {
            "artifact_type": "merge_summary", "artifact_name": MERGE_SUMMARY_ARTIFACT,
            "schema_version": MERGE_PLAN_SCHEMA_VERSION, "merge_run_id": execution_id,
            "merge_plan_id": plan.get("plan_id"), "library_root": library_root,
            # §9.1 item 2: identify the calibration run whose finalized output this merged.
            "calibration": {"plan_id": _json_get(executable_plan_path(ws), "plan_id"),
                            "execution_id": _json_get(execution_summary_path(ws),
                                                       "run_metadata", "execution_id")},
            "merged": {
                EXECUTABLE_PLAN_ARTIFACT: {"sha256": sha256_file(executable_plan_path(ws))},
                EXECUTION_SUMMARY_ARTIFACT: {"sha256": sha256_file(execution_summary_path(ws))},
                HANDOFF_ARTIFACT: {"sha256": sha256_file(handoff_path(ws))},
            },
            "totals": {"placed_new": kinds["placed_new"], "already_present": kinds["already_present"],
                       "renamed_for_library": kinds["renamed_for_library"],
                       "removed_from_by_dest": removed_total, "blocked": kinds["blocked"]},
            "resume": {"newly_moved": newly, "already_done_skipped": already_done},
            "failures": failures, "destinations": dests, "status": status, "snapshot": snapshot,
            "run_metadata": {"execution_id": execution_id, "started_at": now_iso,
                             "finished_at": finished_at or now_iso, "jobs": jobs},
        }

    def do_execute(self, ws, library_root, jobs):
        now_iso = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        execution_id = sha256_text(f"{now_iso}|{os.getpid()}")[:12]
        jobs = jobs or CONFIG.get("jobs") or 4
        result = self.execute_plan(ws, library_root, jobs, now_iso, execution_id)
        st = result["status"]
        if st == "no_plan":
            print(f"No {MERGE_PLAN_ARTIFACT} — run `plan` first.", file=sys.stderr)
            return 2
        if st == "rejected":
            print("\nExecution rejected — the merge plan is stale; re-run `plan`:", file=sys.stderr)
            for s in result.get("stale", []):
                print(f"  - {s}", file=sys.stderr)
            return 2
        t = result["summary"]["totals"]
        print(f"Executed {MERGE_PLAN_ARTIFACT}: status={st} — {t['placed_new']} placed, "
              f"{t['already_present']} already-present, {t['renamed_for_library']} renamed, "
              f"{t['blocked']} blocked ({t['removed_from_by_dest']} removed from by-dest). "
              f"Wrote {MERGE_SUMMARY_ARTIFACT}.")
        if st != "success":
            for b in result.get("blocked", []):
                if b.get("blocker"):
                    print(f"  Blocker: {b['blocker']}", file=sys.stderr)
            print("Blocked files were left in by-dest; resolve them and re-run `execute`.", file=sys.stderr)
            return 3
        print(f"Wrote {MERGE_LOG_ARTIFACT} and {MERGE_DB_SNAPSHOT}; re-sealed the archive "
              f"(photos-35-archive-manifest.json); sealed the workspace (photos-00-sealed.json). "
              "No library file was renamed or overwritten — the workspace is now terminal; "
              "process more media in a fresh workspace.")
        return 0

    # --- filesystem helpers (mirrors of calibration's; merge is read-only here) ---

    def _root_files(self):
        ws = self.workspace_root
        return sorted(f for f in os.listdir(ws) if os.path.isfile(os.path.join(ws, f)))

    def _root_nonmanaged_dirs(self):
        ws = self.workspace_root
        managed = {folder_name(r) for r in FOLDER_ROLES}
        return sorted(f for f in os.listdir(ws)
                      if not f.startswith('.') and f not in managed
                      and os.path.isdir(os.path.join(ws, f)))

    def _root_symlinks(self):
        ws = self.workspace_root
        return sorted(f for f in os.listdir(ws) if os.path.islink(os.path.join(ws, f)))

    def _entries(self, rel_folder):
        d = os.path.join(self.workspace_root, rel_folder)
        return sorted(os.listdir(d)) if os.path.isdir(d) else []

    def _scan_media(self, rel_folder):
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

    def _by_dest_symlinks(self, by_dest):
        """File or directory symlinks anywhere under 6-photos-by-dest (barred, never followed)."""
        base = os.path.join(self.workspace_root, by_dest)
        found = []
        if not os.path.isdir(base):
            return found
        for root, dirs, files in os.walk(base):
            for n in list(dirs) + files:
                p = os.path.join(root, n)
                if os.path.islink(p):
                    found.append(os.path.relpath(p, self.workspace_root))
        return sorted(found)


def _json_get(path, *keys):
    """Best-effort read of a JSON file at `path`, walking nested `keys`; None on any miss/error.
    Used to surface the calibration run's plan/execution ids in the merge summary (§9.1 item 2)."""
    try:
        with open(path) as f:
            v = json.load(f)
    except Exception:
        return None
    for k in keys:
        if not isinstance(v, dict):
            return None
        v = v.get(k)
    return v


def _record_fingerprint(rec):
    """The content fingerprint of a handoff file record: the prep cache's content_hash JSON `.value`
    (the cross-phase identity spine). Falls back to a pre-extracted `content_fingerprint` field if
    present. None if absent/unparseable."""
    ch = rec.get("content_hash")
    if ch:
        try:
            return json.loads(ch).get("value")
        except Exception:
            return None
    return rec.get("content_fingerprint")


def _in_workspace(ws):
    """A directory is an (initialized) workspace iff it carries the workspace guard sentinel."""
    return os.path.exists(guard_path(ws))


def do_init_library(path_arg, ws):
    """The one-time `init-library` setup command — the sole creator of the `.photos-library` marker
    (merge spec §4). Behavior depends on workspace context and whether a path was given:

      in workspace + path  -> bless the resolved path AND record library_root in config (the one
                              narrow exception to "prep is the config seeder", shared contract §4.1)
      in workspace, no path -> bless the directory config already names (no config write)
      no workspace + path  -> bless only; advise running from a workspace to record it in config
      no workspace, no path -> error (nothing to bless, no config to read)

    Returns a process exit code."""
    in_ws = _in_workspace(ws)

    if path_arg is None:
        if not in_ws:
            print("init-library needs a library path when run outside a workspace "
                  "(there is no workspace config to read). Pass the library directory, e.g. "
                  "`photos-ingest merge init-library /srv/library`.", file=sys.stderr)
            return 2
        cfg_p = config_path(ws)
        try:
            with open(cfg_p) as f:
                cfg = json.load(f)
        except Exception as e:
            print(f"Workspace config could not be read: {e}", file=sys.stderr)
            return 2
        library_root = ((cfg.get("merge") or {}).get("library_root") or "")
        if not library_root:
            print("No merge.library_root is set in photos-00-config.json — pass a path "
                  "(`photos-ingest merge init-library <path>`) or set it in config first.", file=sys.stderr)
            return 2
        try:
            validate_merge_config(cfg, ws)          # validates library_root (existing, outside ws)
        except ValueError as e:
            print(str(e), file=sys.stderr)
            return 2
        pre = is_library(library_root)
        marker = write_library_marker(library_root)
        print(f"Library {'already blessed' if pre else 'blessed'}: {library_root} "
              f"({os.path.basename(marker)}). Already named in config; no config change.")
        return 0

    # A path was given: resolve to an absolute path and validate it.
    resolved = os.path.abspath(os.path.expanduser(path_arg))
    if not os.path.isdir(resolved):
        print(f"init-library: {resolved} is not an existing directory.", file=sys.stderr)
        return 2

    if not in_ws:
        pre = is_library(resolved)
        marker = write_library_marker(resolved)
        print(f"Library {'already blessed' if pre else 'blessed'}: {resolved} "
              f"({os.path.basename(marker)}). Not run from a workspace, so config was not updated — "
              "re-run this from a workspace if you also want it recorded in that workspace's "
              "photos-00-config.json.")
        return 0

    # In a workspace with an explicit path: bless AND record library_root in config (under the lock).
    ws_real = os.path.realpath(os.path.abspath(ws))
    lib_real = os.path.realpath(resolved)
    if lib_real == ws_real or lib_real.startswith(ws_real + os.sep):
        print(f"init-library: {resolved} must resolve outside the workspace (it must not be the "
              "workspace or any path inside it).", file=sys.stderr)
        return 2
    lock = WorkspaceLock(ws)
    if not lock.acquire():
        owner = lock.read_owner() or {}
        detail = f" (pid {owner.get('pid')}, since {owner.get('started_at')})" if owner else ""
        print(f"Workspace is locked by an in-progress run{detail}; try again when it finishes.",
              file=sys.stderr)
        return 1
    try:
        cfg_p = config_path(ws)
        try:
            with open(cfg_p) as f:
                cfg = json.load(f)
        except Exception as e:
            print(f"Workspace config could not be read: {e}", file=sys.stderr)
            return 2
        # §4.1 item 2: the setup command writes the single library_root key — and ONLY that key. Don't
        # seed placement/collision policy (prep is the config seeder; merge reads those with defaults).
        if not isinstance(cfg.get("merge"), dict):
            cfg["merge"] = {}
        cfg["merge"]["library_root"] = resolved
        try:
            validate_merge_config(cfg, ws)
        except ValueError as e:
            print(str(e), file=sys.stderr)
            return 2
        pre = is_library(resolved)
        marker = write_library_marker(resolved)
        write_json_artifact(cfg_p, cfg)             # the one narrow config write (library_root only)
        print(f"Library {'already blessed' if pre else 'blessed'} and recorded: {resolved} "
              f"({os.path.basename(marker)}). Wrote merge.library_root into photos-00-config.json.")
        return 0
    finally:
        lock.release()


def _run_locked_workflow(command, ws, jobs=None):
    """plan / dry-run / execute: acquire the workspace lock, validate config + the library marker via
    preflight, then acquire the library lock, then dispatch."""
    run_lock = WorkspaceLock(ws)
    if not run_lock.acquire():
        owner = run_lock.read_owner() or {}
        detail = f" (pid {owner.get('pid')}, since {owner.get('started_at')})" if owner else ""
        print(f"Workspace is locked by an in-progress run{detail}; try again when it finishes.",
              file=sys.stderr)
        return 1
    print(f"Lock acquired: {run_lock.lock_path}", file=sys.stderr)
    try:
        wf = MergeWorkflow(ws)
        blockers, warnings, info = wf.preflight()
        for w in warnings:
            print(f"  Warning: {w}", file=sys.stderr)
        if blockers:
            print("\nMerge cannot proceed:", file=sys.stderr)
            for b in blockers:
                print(f"  - {b}", file=sys.stderr)
            print("\nNo files were merged.", file=sys.stderr)
            return 2

        # Preflight confirmed the .photos-library marker — safe to take the library-side lock now
        # (§12: workspace lock, then config+marker, then library lock).
        library_root = info["library_root"]
        lib_lock = LibraryLock(library_root)
        if not lib_lock.acquire():
            owner = lib_lock.read_owner() or {}
            detail = f" (pid {owner.get('pid')}, since {owner.get('started_at')})" if owner else ""
            print(f"Library {library_root} is locked by another merge{detail}; try again when it "
                  "finishes.", file=sys.stderr)
            return 1
        print(f"Library lock acquired: {lib_lock.lock_path}", file=sys.stderr)
        try:
            print(f"Preflight passed: {info.get('by_dest_photos', 0)} by-dest photo(s) ready to merge "
                  f"into {library_root}.", file=sys.stderr)
            if command == "plan":
                return wf.do_plan(ws, library_root)
            if command == "dry-run":
                return wf.do_dry_run(ws)
            return wf.do_execute(ws, library_root, jobs)
        finally:
            lib_lock.release()
    except KeyboardInterrupt:
        # Clean Ctrl-C: plan/dry-run never mutate and execute is journalled/idempotent, so moved
        # files are confirmed and the next run resumes from the diff (§8.3). Exit quietly with the
        # conventional 130 instead of a traceback; the `finally` blocks still release both locks.
        print("\nInterrupted; aborting. Moved files are journalled — safe to rerun.",
              file=sys.stderr)
        return 130
    finally:
        run_lock.release()


MERGE_BLURB = (
    "merge — move the calibrated library into permanent storage (phase 3 of 3, terminal).\n\n"
    "Takes the finalized 6-photos-by-dest tree and moves it into your permanent library "
    "(merge.library_root), never renaming or overwriting a file already there; on success it re-seals "
    "the archive and seals the workspace. `init-library` blesses a directory as the library (one-time); "
    "`plan` maps by-dest photos to library targets (no mutation); `dry-run` displays the placements / "
    "collisions; `execute` applies the move. Run inside the workspace directory.\n\n"
    "Requires geotag to have finalized first. This is the last step for a workspace."
)


def add_arguments(parser):
    """Register merge's `-j` + subcommands (init-library / plan / dry-run / execute) on `parser`.
    Shared by the standalone `python -m photos_pipeline.photos_3_merge` and `photos-ingest merge`."""
    parser.add_argument("-j", "--jobs", type=int, default=None,
                        help="Worker threads for execution (default: config jobs, else 4).")
    sub = parser.add_subparsers(dest="command")
    p_init = sub.add_parser("init-library",
                            help="Bless a directory as the permanent library (writes .photos-library).")
    p_init.add_argument("path", nargs="?", default=None,
                        help="Library directory to bless (default: merge.library_root from config).")
    sub.add_parser("plan", help="Plan the merge: map by-dest photos to library targets (no mutation).")
    sub.add_parser("dry-run", help="Display the exact placements/collisions the plan would execute.")
    sub.add_parser("execute", help="Apply the validated plan: move photos into the library.")
    parser.set_defaults(_run=run, _parser=parser)


def run(args):
    ws = os.getcwd()
    if args.command == "init-library":
        sys.exit(do_init_library(args.path, ws))
    sys.exit(_run_locked_workflow(args.command, ws, getattr(args, "jobs", None)))


def main(argv=None):
    parser = argparse.ArgumentParser(prog="photos_pipeline.photos_3_merge", description=MERGE_BLURB,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    add_arguments(parser)
    args = parser.parse_args(argv)
    if getattr(args, "command", None) is None:
        parser.print_help()
        return 0
    return run(args)


if __name__ == "__main__":
    main()
