"""Increment 2 — the library-merge skeleton: preflight (merge spec §3), the `init-library` setup
command (§4), and the two-lock acquisition flow (§12).

photos-3-merge writes no artifacts and moves nothing yet (`plan`/`dry-run`/`execute` are stubbed);
these tests exercise the preconditions, init-library's context×path matrix, and lock order.
photos_3_merge / photos_utils come from conftest.py.
"""
import json
import os

import pytest

import photos_3_merge as merge
import photos_utils as utils

MANAGED = ["0-sources", "1-strays", "2-missing-metadata", "3-redundant-jpgs",
           "4-videos-by-date", "5-photos-by-date", "6-photos-by-dest"]


def _ctl(ws):
    return ws / ".photos-ingest"


def _make(tmp_path, *, guard=True, config=True, library_in_config=True, bless_lib=True,
          handoff=True, handoff_current=True, cal_plan=True, cal_summary=True,
          summary_status="success", complete_log=True, archive_manifest=True,
          bydest=("6-photos-by-dest/Trip/a.jpg",), sources_files=()):
    """Build a workspace that PASSES preflight by default, plus a sibling blessed library. Each
    keyword turns off / corrupts one precondition's input so a single check can be isolated."""
    ws = tmp_path / "ws"
    ws.mkdir()
    lib = tmp_path / "library"
    lib.mkdir()
    for d in MANAGED:
        (ws / d).mkdir()
    ctl = _ctl(ws)
    ctl.mkdir()
    if guard:
        (ctl / "photos-00-workspace-guard").touch()
    if bless_lib:
        utils.write_library_marker(str(lib))
    for rel in bydest:
        p = ws / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(b"img")
    for name in sources_files:
        (ws / "0-sources" / name).write_bytes(b"x")

    ho = {"files": [{"relative_path": rel, "folder_class": "6-photos-by-dest", "media_class": "image",
                     "content_fingerprint": f"fp-{i}"} for i, rel in enumerate(bydest)],
          "content_fingerprint": "whole-file-hash", "run_metadata": {"started_at": "t0"}}
    fp = utils.handoff_content_fingerprint(ho)
    if handoff:
        (ctl / "photos-11-handoff.json").write_text(json.dumps(ho))
    if config:
        cfg = {k: v for k, v in utils.CONFIG.items() if k != "jobs"}
        cfg["merge"] = dict(cfg.get("merge") or {})
        cfg["merge"]["library_root"] = str(lib) if library_in_config else ""
        (ctl / "photos-00-config.json").write_text(json.dumps(cfg))
    if cal_plan:
        pinned = fp if handoff_current else ("stale-" + fp)
        plan = {"status": "ready",
                "depends_on": {"handoff": {"dependency_type": "handoff_content",
                                           "artifact_name": "photos-11-handoff.json",
                                           "content_fingerprint": pinned}}}
        (ctl / "photos-24-executable-plan.json").write_text(json.dumps(plan))
    if cal_summary:
        (ctl / "photos-25-execution-summary.json").write_text(json.dumps({"status": summary_status}))
    if complete_log:
        (ctl / "photos-26-complete-log.json").write_text(json.dumps({"photos": {}}))
    if archive_manifest:
        (ctl / "photos-26-archive-manifest.json").write_text(
            json.dumps({"artifact_name": "photos-26-archive-manifest.json"}))
    return ws, lib


def _pf(ws):
    return merge.MergeWorkflow(str(ws)).preflight()


# --- happy path --------------------------------------------------------------

def test_clean_workspace_passes(tmp_path):
    ws, lib = _make(tmp_path)
    blockers, warnings, info = _pf(ws)
    assert blockers == [], blockers
    assert info["library_root"] == str(lib)
    assert info["by_dest_photos"] == 1
    assert info["handoff_sha256"]


# --- lifecycle / structural guards (return early) ----------------------------

def test_sealed_blocks_and_warns_on_dump(tmp_path):
    ws, _ = _make(tmp_path, sources_files=("newdump.jpg",))
    (_ctl(ws) / "photos-00-sealed.json").write_text('{"sealed": true, "merged_run_id": "r1"}')
    blockers, warnings, _ = _pf(ws)
    assert any("SEALED" in b for b in blockers), blockers
    assert any("new dump" in w.lower() for w in warnings), warnings


def test_uninitialized_blocks(tmp_path):
    ws, _ = _make(tmp_path, guard=False)
    blockers, _, _ = _pf(ws)
    assert any("Not an initialized workspace" in b for b in blockers), blockers


def test_root_symlink_blocks(tmp_path):
    ws, _ = _make(tmp_path)
    os.symlink(str(tmp_path), str(ws / "evil"))
    blockers, _, _ = _pf(ws)
    assert any("Forbidden symlink at the workspace root" in b for b in blockers), blockers


def test_missing_managed_folder_blocks(tmp_path):
    ws, _ = _make(tmp_path)
    os.rmdir(str(ws / "4-videos-by-date"))
    blockers, _, _ = _pf(ws)
    assert any("missing managed folder" in b for b in blockers), blockers


def test_loose_root_file_blocks(tmp_path):
    ws, _ = _make(tmp_path)
    (ws / "stray.txt").write_text("loose")
    blockers, _, _ = _pf(ws)
    assert any("Loose file at the workspace root" in b for b in blockers), blockers


def test_nonmanaged_root_folder_blocks(tmp_path):
    ws, _ = _make(tmp_path)
    (ws / "randomdump").mkdir()
    blockers, _, _ = _pf(ws)
    assert any("Misplaced folder at the workspace root" in b for b in blockers), blockers


# --- config + library identity ----------------------------------------------

def test_missing_config_blocks(tmp_path):
    ws, _ = _make(tmp_path, config=False)
    blockers, _, _ = _pf(ws)
    assert any("photos-00-config.json is missing" in b for b in blockers), blockers


def test_empty_library_root_blocks(tmp_path):
    ws, _ = _make(tmp_path, library_in_config=False)
    blockers, _, _ = _pf(ws)
    assert any("library_root must be a non-empty" in b for b in blockers), blockers


def test_unblessed_library_blocks(tmp_path):
    ws, _ = _make(tmp_path, bless_lib=False)
    blockers, _, _ = _pf(ws)
    assert any("init-library" in b for b in blockers), blockers


# --- handoff -----------------------------------------------------------------

def test_missing_handoff_blocks(tmp_path):
    ws, _ = _make(tmp_path, handoff=False)
    blockers, _, _ = _pf(ws)
    assert any("photos-11-handoff.json is missing" in b for b in blockers), blockers


# --- gathered preconditions (0b, 1, 1a, 2, 3) --------------------------------

def test_sources_not_empty_blocks(tmp_path):
    ws, _ = _make(tmp_path, sources_files=("dump.jpg",))
    blockers, _, _ = _pf(ws)
    assert any("0-sources/ is not empty" in b for b in blockers), blockers


def test_missing_geotag_plan_blocks(tmp_path):
    ws, _ = _make(tmp_path, cal_plan=False)
    blockers, _, _ = _pf(ws)
    assert any("has not produced an executable plan" in b for b in blockers), blockers


def test_geotag_not_executed_blocks(tmp_path):
    ws, _ = _make(tmp_path, cal_summary=False)
    blockers, _, _ = _pf(ws)
    assert any("was not executed" in b for b in blockers), blockers


def test_geotag_failed_status_blocks(tmp_path):
    ws, _ = _make(tmp_path, summary_status="partial")
    blockers, _, _ = _pf(ws)
    assert any("did not end successfully" in b for b in blockers), blockers


def test_stale_finalized_record_blocks(tmp_path):
    ws, _ = _make(tmp_path, handoff_current=False)
    blockers, _, _ = _pf(ws)
    assert any("changed since geotag was finalized" in b for b in blockers), blockers
    assert any("re-run geotag and re-finalize" in b.lower() for b in blockers), blockers


def test_not_finalized_blocks(tmp_path):
    ws, _ = _make(tmp_path, complete_log=False)
    blockers, _, _ = _pf(ws)
    assert any("has not been finalized" in b for b in blockers), blockers


def test_missing_archive_manifest_blocks(tmp_path):
    ws, _ = _make(tmp_path, archive_manifest=False)
    blockers, _, _ = _pf(ws)
    assert any("archival package is incomplete" in b for b in blockers), blockers


def test_video_in_bydest_blocks(tmp_path):
    ws, _ = _make(tmp_path, bydest=("6-photos-by-dest/Trip/a.jpg", "6-photos-by-dest/Trip/clip.mp4"))
    blockers, _, _ = _pf(ws)
    assert any("must contain only photos" in b and "video" in b for b in blockers), blockers


def test_nonmedia_in_bydest_blocks(tmp_path):
    ws, _ = _make(tmp_path, bydest=("6-photos-by-dest/Trip/a.jpg", "6-photos-by-dest/Trip/notes.txt"))
    blockers, _, _ = _pf(ws)
    assert any("must contain only photos" in b for b in blockers), blockers


def test_dev_subfolder_blocks(tmp_path):
    ws, _ = _make(tmp_path)
    p = ws / "6-photos-by-dest" / "Trip" / "jpg" / "a__std.jpg"
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_bytes(b"img")
    blockers, _, _ = _pf(ws)
    assert any("development subfolder" in b for b in blockers), blockers


def test_bydest_symlink_blocks(tmp_path):
    ws, _ = _make(tmp_path)
    os.symlink(str(tmp_path), str(ws / "6-photos-by-dest" / "Trip" / "link"))
    blockers, _, _ = _pf(ws)
    assert any("Forbidden symlink under" in b for b in blockers), blockers


def test_bydate_stray_photo_blocks(tmp_path):
    ws, _ = _make(tmp_path)
    (ws / "5-photos-by-date" / "x.jpg").write_bytes(b"img")
    blockers, _, _ = _pf(ws)
    assert any("5-photos-by-date/ still contains" in b for b in blockers), blockers


def test_gathers_multiple_blockers_at_once(tmp_path):
    # A gathered-phase failure (not finalized) and another (sources not empty) both surface.
    ws, _ = _make(tmp_path, complete_log=False, sources_files=("dump.jpg",))
    blockers, _, _ = _pf(ws)
    assert any("has not been finalized" in b for b in blockers), blockers
    assert any("0-sources/ is not empty" in b for b in blockers), blockers


# --- init-library: context × path matrix (merge spec §4) ---------------------

def _fresh_ws_and_lib(tmp_path):
    """A workspace (guard + config naming a NOT-yet-blessed library) plus the library dir."""
    ws, lib = _make(tmp_path, bless_lib=False)       # config names lib, but it is not yet blessed
    assert not utils.is_library(str(lib))
    return ws, lib


def test_init_library_in_workspace_with_path_blesses_and_writes_config(tmp_path):
    ws = tmp_path / "ws"
    ws.mkdir()
    (ws / ".photos-ingest").mkdir()
    (ws / ".photos-ingest" / "photos-00-workspace-guard").touch()
    cfg = {k: v for k, v in utils.CONFIG.items() if k != "jobs"}
    (ws / ".photos-ingest" / "photos-00-config.json").write_text(json.dumps(cfg))
    lib = tmp_path / "lib"
    lib.mkdir()

    rc = merge.do_init_library(str(lib), str(ws))
    assert rc == 0
    assert utils.is_library(str(lib))
    written = json.loads((ws / ".photos-ingest" / "photos-00-config.json").read_text())
    assert written["merge"]["library_root"] == str(lib)   # the one narrow config write


def test_init_library_in_workspace_no_path_uses_config(tmp_path):
    ws, lib = _fresh_ws_and_lib(tmp_path)
    rc = merge.do_init_library(None, str(ws))
    assert rc == 0
    assert utils.is_library(str(lib))


def test_init_library_outside_workspace_with_path_blesses_only(tmp_path):
    lib = tmp_path / "lib"
    lib.mkdir()
    plain = tmp_path / "not_a_ws"            # no guard -> not a workspace
    plain.mkdir()
    rc = merge.do_init_library(str(lib), str(plain))
    assert rc == 0
    assert utils.is_library(str(lib))


def test_init_library_outside_workspace_no_path_errors(tmp_path):
    plain = tmp_path / "not_a_ws"
    plain.mkdir()
    rc = merge.do_init_library(None, str(plain))
    assert rc == 2


def test_init_library_idempotent(tmp_path):
    lib = tmp_path / "lib"
    lib.mkdir()
    plain = tmp_path / "p"
    plain.mkdir()
    marker = utils.library_marker_path(str(lib))
    assert merge.do_init_library(str(lib), str(plain)) == 0
    with open(marker, "w") as f:
        f.write("sentinel")                  # prove a second run does NOT clobber
    assert merge.do_init_library(str(lib), str(plain)) == 0
    assert open(marker).read() == "sentinel"


def test_init_library_nonexistent_path_errors(tmp_path):
    plain = tmp_path / "p"
    plain.mkdir()
    rc = merge.do_init_library(str(tmp_path / "missing"), str(plain))
    assert rc == 2


def test_init_library_path_inside_workspace_errors(tmp_path):
    ws, _ = _make(tmp_path)
    inside = ws / "6-photos-by-dest"
    rc = merge.do_init_library(str(inside), str(ws))
    assert rc == 2
    assert not utils.is_library(str(inside))


def test_init_library_resolves_relative_path(tmp_path):
    lib = tmp_path / "lib"
    lib.mkdir()
    plain = tmp_path / "p"
    plain.mkdir()
    cwd = os.getcwd()
    os.chdir(str(tmp_path))
    try:
        rc = merge.do_init_library("lib", str(plain))     # relative -> abspath
    finally:
        os.chdir(cwd)
    assert rc == 0
    assert utils.is_library(str(lib))


# --- locking flow (merge spec §12) -------------------------------------------

def test_locked_workflow_acquires_both_and_releases(tmp_path):
    ws, lib = _make(tmp_path)
    rc = merge._run_locked_workflow("plan", str(ws))
    assert rc == 0                                    # preflight passed; stub returns success
    # Both locks must be free again after the run.
    wl = utils.WorkspaceLock(str(ws))
    assert wl.acquire() is True
    wl.release()
    ll = utils.LibraryLock(str(lib))
    assert ll.acquire() is True
    ll.release()


def test_locked_workflow_exits_1_if_workspace_locked(tmp_path):
    ws, _ = _make(tmp_path)
    held = utils.WorkspaceLock(str(ws))
    assert held.acquire() is True
    try:
        assert merge._run_locked_workflow("plan", str(ws)) == 1
    finally:
        held.release()


def test_locked_workflow_exits_1_if_library_locked(tmp_path):
    ws, lib = _make(tmp_path)
    held = utils.LibraryLock(str(lib))                # another workspace's merge holds the library
    assert held.acquire() is True
    try:
        assert merge._run_locked_workflow("plan", str(ws)) == 1
    finally:
        held.release()


def test_locked_workflow_exits_2_on_blocker(tmp_path):
    ws, lib = _make(tmp_path, complete_log=False)     # a precondition fails
    assert merge._run_locked_workflow("plan", str(ws)) == 2
    # The library lock must never have been taken (blocked before it).
    ll = utils.LibraryLock(str(lib))
    assert ll.acquire() is True
    ll.release()
