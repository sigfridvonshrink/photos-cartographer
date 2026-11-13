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
          summary_status="success", prep_log=True, complete_log=True, archive_manifest=True, finalized_media=True,
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

    ho = {"filename_timestamp_format": utils.CONFIG["filename_timestamp_format"], "files": [{"relative_path": rel, "folder_class": "6-photos-by-dest", "media_class": "image",
                     "content_fingerprint": f"fp-{i}"} for i, rel in enumerate(bydest)],
          "content_fingerprint": "whole-file-hash", "run_metadata": {"started_at": "t0"}}
    if prep_log:
        (ctl / "photos-15-prep-log.json").write_text(json.dumps({"photos": {}}))
        ho["depends_on"] = {"prep_log": {"sha256": utils.sha256_file(str(ctl / "photos-15-prep-log.json"))}}
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
    if finalized_media:
        (ctl / "photos-26-finalized-media.json").write_text(json.dumps({"media": {
            rel: {"size": os.stat(ws / rel).st_size, "mtime_ns": os.stat(ws / rel).st_mtime_ns}
            for rel in bydest}}))
    return ws, lib


def _pf(ws):
    return merge.MergeWorkflow(str(ws)).preflight()


@pytest.mark.spec("RUL-merge_refuses_changed_since_finalize", test="TST-merge_preflight-photo_changed_since_finalize_blocks")
def test_photo_changed_since_finalize_blocks(tmp_path):
    ws, _ = _make(tmp_path)
    p = ws / "6-photos-by-dest/Trip/a.jpg"
    st = os.stat(p)
    os.utime(p, ns=(st.st_atime_ns, st.st_mtime_ns + 1_000_000_000))  # a metadata write: same pixels, new mtime
    blockers, _, _ = _pf(ws)
    assert len(blockers) == 1 and "changed since the workspace was finalized" in blockers[0] \
        and "6-photos-by-dest/Trip/a.jpg" in blockers[0], blockers


@pytest.mark.spec("RUL-merge_refuses_changed_since_finalize", test="TST-merge_preflight-no_finalized_media_record_blocks")
def test_no_finalized_media_record_blocks(tmp_path):
    ws, _ = _make(tmp_path, finalized_media=False)
    blockers, _, _ = _pf(ws)
    assert len(blockers) == 1 and "photos-26-finalized-media.json" in blockers[0], blockers


@pytest.mark.spec("RUL-format_fixed_once_named", test="TST-merge_preflight-filename_format_other_than_prep_s_blocks")
def test_filename_format_other_than_prep_s_blocks(tmp_path):
    ws, _ = _make(tmp_path)
    ho_p = _ctl(ws) / "photos-11-handoff.json"
    ho_p.write_text(json.dumps(dict(json.loads(ho_p.read_text()), filename_timestamp_format="%Y%m%d_%H%M%S")))
    blockers, _, _ = _pf(ws)
    assert blockers == [utils.filename_format_changed("%Y%m%d_%H%M%S", utils.CONFIG["filename_timestamp_format"])]


# --- happy path --------------------------------------------------------------

def test_clean_workspace_passes(tmp_path):
    ws, lib = _make(tmp_path)
    blockers, warnings, info = _pf(ws)
    assert blockers == [], blockers
    assert info["library_root"] == str(lib)
    assert info["by_dest_photos"] == 1
    assert info["handoff_sha256"]


# --- lifecycle / structural guards (return early) ----------------------------

@pytest.mark.spec("seal-marker-is-authority-1", test="TST-merge_preflight-sealed_blocks_and_warns_on_dump")
def test_sealed_blocks_and_warns_on_dump(tmp_path):
    ws, _ = _make(tmp_path, sources_files=("newdump.jpg",))
    (_ctl(ws) / "photos-00-sealed.json").write_text('{"sealed": true, "merged_run_id": "r1"}')
    blockers, warnings, _ = _pf(ws)
    assert any("SEALED" in b for b in blockers), blockers
    assert any("new dump" in w.lower() for w in warnings), warnings


@pytest.mark.spec("merge-require-initialized-else-run-prep-1")
def test_uninitialized_blocks(tmp_path):
    ws, _ = _make(tmp_path, guard=False)
    blockers, _, _ = _pf(ws)
    assert any("Not an initialized workspace" in b for b in blockers), blockers


@pytest.mark.spec("RUL-geotag_merge_check_top_level_links", test="TST-merge_preflight-root_symlink_blocks")
def test_root_symlink_blocks(tmp_path):
    ws, _ = _make(tmp_path)
    os.symlink(str(tmp_path), str(ws / "evil"))
    blockers, _, _ = _pf(ws)
    assert any("Forbidden symlink at the workspace root" in b for b in blockers), blockers


@pytest.mark.spec("merge-require-managed-structure-intact-1")
def test_missing_managed_folder_blocks(tmp_path):
    ws, _ = _make(tmp_path)
    os.rmdir(str(ws / "4-videos-by-date"))
    blockers, _, _ = _pf(ws)
    assert any("missing managed folder" in b for b in blockers), blockers


@pytest.mark.spec("merge-block-misplaced-root-entry-1")
def test_loose_root_file_blocks(tmp_path):
    ws, _ = _make(tmp_path)
    (ws / "stray.txt").write_text("loose")
    blockers, _, _ = _pf(ws)
    assert any("Misplaced entry at workspace root" in b for b in blockers), blockers


def test_nonmanaged_root_folder_blocks(tmp_path):
    ws, _ = _make(tmp_path)
    (ws / "randomdump").mkdir()
    blockers, _, _ = _pf(ws)
    assert any("Misplaced entry at workspace root" in b for b in blockers), blockers


@pytest.mark.spec("RUL-top_level_only_managed", test="TST-merge_preflight-root_hidden_file_allowed")
def test_root_hidden_file_allowed(tmp_path):
    """A hidden file at the top level (a file manager's `.directory`) is a hidden entry, not a
    misplaced dump: it blocks nothing (shared contract §4)."""
    ws, _ = _make(tmp_path)
    (ws / ".directory").write_text("[Dolphin]")
    blockers, _, _ = _pf(ws)
    assert not any("Misplaced entry" in b for b in blockers), blockers


@pytest.mark.spec("RUL-top_level_only_managed", test="TST-merge_preflight-every_misplaced_root_entry_named")
def test_every_misplaced_root_entry_named(tmp_path):
    """Any other top-level entry blocks, whatever its kind — a named pipe too — and the block names
    every one, not only the first."""
    ws, _ = _make(tmp_path)
    (ws / "stray.txt").write_text("loose")
    (ws / "randomdump").mkdir()
    os.mkfifo(str(ws / "pipe"))
    blockers, _, _ = _pf(ws)
    hit = [b for b in blockers if "Misplaced entry at workspace root" in b]
    assert hit and all(n in hit[0] for n in ("pipe", "randomdump", "stray.txt")), blockers


# --- config + library identity ----------------------------------------------

def test_missing_config_blocks(tmp_path):
    ws, _ = _make(tmp_path, config=False)
    blockers, _, _ = _pf(ws)
    assert any("photos-00-config.json is missing" in b for b in blockers), blockers


def test_empty_library_root_blocks(tmp_path):
    ws, _ = _make(tmp_path, library_in_config=False)
    blockers, _, _ = _pf(ws)
    assert any("library_root must be a non-empty" in b for b in blockers), blockers


@pytest.mark.spec("merge-require-blessed-library-marker-1", "RUL-library_mark_required", test="TST-merge_preflight-unblessed_library_blocks")
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

@pytest.mark.spec("merge-require-0-sources-empty-1", test="TST-merge_preflight-sources_not_empty_blocks")
def test_sources_not_empty_blocks(tmp_path):
    ws, _ = _make(tmp_path, sources_files=("dump.jpg",))
    blockers, _, _ = _pf(ws)
    assert any("0-sources/ is not empty" in b for b in blockers), blockers


def test_missing_geotag_plan_blocks(tmp_path):
    ws, _ = _make(tmp_path, cal_plan=False)
    blockers, _, _ = _pf(ws)
    assert any("has not produced an executable plan" in b for b in blockers), blockers


@pytest.mark.spec("merge-preconditions-finalized-1", test="TST-merge_preflight-geotag_not_executed_blocks")
def test_geotag_not_executed_blocks(tmp_path):
    ws, _ = _make(tmp_path, cal_summary=False)
    blockers, _, _ = _pf(ws)
    assert any("was not executed" in b for b in blockers), blockers


@pytest.mark.spec("merge-require-geotag-success-1")
def test_geotag_failed_status_blocks(tmp_path):
    ws, _ = _make(tmp_path, summary_status="partial")
    blockers, _, _ = _pf(ws)
    assert any("did not end successfully" in b for b in blockers), blockers


@pytest.mark.spec("merge-post-finalize-currency-check-1")
def test_stale_finalized_record_blocks(tmp_path):
    ws, _ = _make(tmp_path, handoff_current=False)
    blockers, _, _ = _pf(ws)
    assert any("changed since geotag was finalized" in b for b in blockers), blockers
    assert any("re-run geotag and re-finalize" in b.lower() for b in blockers), blockers


@pytest.mark.parametrize("touch", ["edited", "removed", "unvouched"])
@pytest.mark.spec("BLD-prep_log_checked", "RUL-merge_takes_finalized_current",
                  test="TST-merge_preflight-a_prep_log_the_handoff_does_not_vouch_for_blocks")
def test_a_prep_log_the_handoff_does_not_vouch_for_blocks(tmp_path, touch):
    """Prep's log touched after finalize — edited, removed, or a handoff recording no hash of it — stops merge,
    as it stops finalize: photos-26 can no longer be shown to carry prep's record."""
    ws, _ = _make(tmp_path)
    log = _ctl(ws) / "photos-15-prep-log.json"
    if touch == "edited":
        log.write_text(json.dumps({"photos": {"X": {"content_fingerprint": "X", "journey": []}}}))
    elif touch == "removed":
        log.unlink()
    else:
        ho_p = _ctl(ws) / "photos-11-handoff.json"
        ho = json.loads(ho_p.read_text())
        del ho["depends_on"]["prep_log"]
        ho_p.write_text(json.dumps(ho))
    blockers, _, _ = _pf(ws)
    want = {"edited": "is not the one the handoff records", "removed": "is missing or unreadable",
            "unvouched": "records no hash of prep's log"}[touch]
    assert len(blockers) == 1 and want in blockers[0] and "geotag finalize" in blockers[0], blockers


@pytest.mark.spec("loop-finalize-before-merge-1", "merge-require-finalized-else-run-finalize-1", test="TST-merge_preflight-not_finalized_blocks")
def test_not_finalized_blocks(tmp_path):
    ws, _ = _make(tmp_path, complete_log=False)
    blockers, _, _ = _pf(ws)
    assert any("has not been finalized" in b for b in blockers), blockers


def test_missing_archive_manifest_blocks(tmp_path):
    ws, _ = _make(tmp_path, archive_manifest=False)
    blockers, _, _ = _pf(ws)
    assert any("archival package is incomplete" in b for b in blockers), blockers


@pytest.mark.spec("merge-require-by-dest-photo-only-1", test="TST-merge_preflight-video_in_bydest_blocks")
def test_video_in_bydest_blocks(tmp_path):
    ws, _ = _make(tmp_path, bydest=("6-photos-by-dest/Trip/a.jpg", "6-photos-by-dest/Trip/clip.mp4"))
    blockers, _, _ = _pf(ws)
    assert any("must contain only photos" in b and "video" in b for b in blockers), blockers


def test_nonmedia_in_bydest_blocks(tmp_path):
    ws, _ = _make(tmp_path, bydest=("6-photos-by-dest/Trip/a.jpg", "6-photos-by-dest/Trip/notes.txt"))
    blockers, _, _ = _pf(ws)
    assert any("must contain only photos" in b for b in blockers), blockers


@pytest.mark.spec("merge-residual-folders-do-not-block-1", test="TST-merge_preflight-residual_folders_do_not_block")
def test_residual_folders_do_not_block(tmp_path):
    """Geotag's gates leave out the videos, the files missing metadata, the redundant JPEGs and the strays; what
    sits there blocks merge no more than it blocks geotag."""
    ws, _ = _make(tmp_path)
    for rel in ("4-videos-by-date/clip.mp4", "2-missing-metadata/x.jpg", "3-redundant-jpgs/y.jpg", "1-strays/notes.txt"):
        (ws / rel).write_bytes(b"x")
    blockers, _, _ = _pf(ws)
    assert blockers == [], blockers


@pytest.mark.spec("RUL-development_after_merge", test="TST-merge_preflight-dev_subfolder_blocks")
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


@pytest.mark.spec("config-initlib-writes-libroot-only-1", "merge-init-library-inside-with-path-writes-config-1", test="TST-merge_preflight-init_library_in_workspace_with_path_blesses_and_writes_config")
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


@pytest.mark.spec("RUL-sealed_refuses", "RUL-sealed_no_library_recorded", test="TST-merge_preflight-init_library_refuses_to_record_a_library_in_a_sealed_workspace")
def test_init_library_refuses_to_record_a_library_in_a_sealed_workspace(tmp_path):
    ws, lib = _fresh_ws_and_lib(tmp_path)
    cfg_p = ws / ".photos-ingest" / "photos-00-config.json"
    utils.write_sealed_marker(str(ws), "run-1", str(lib))
    before = cfg_p.read_bytes()
    other = tmp_path / "other"
    other.mkdir()

    rc = merge.do_init_library(str(other), str(ws))
    assert rc == 2
    assert not utils.is_library(str(other))              # nothing blessed
    assert cfg_p.read_bytes() == before                  # nothing written

    # Blessing the library the config already names writes nothing in the workspace, so it stays allowed.
    assert merge.do_init_library(None, str(ws)) == 0
    assert cfg_p.read_bytes() == before


@pytest.mark.parametrize("with_path", [True, False])
@pytest.mark.spec("RUL-config_validated_before_use", "BLD-init_library_cases",
                  test="TST-merge_preflight-init_library_reads_the_configuration_checked")
def test_init_library_reads_the_configuration_checked(tmp_path, with_path):
    """init-library reads the workspace's configuration whole and checked, as every command does: a setting
    cartographer does not know stops it before it blesses or writes anything."""
    ws, lib = _fresh_ws_and_lib(tmp_path)
    cfg_p = ws / ".photos-ingest" / "photos-00-config.json"
    cfg = json.loads(cfg_p.read_text())
    cfg["merge"]["placement_policy"] = "preserve_destination_structure"   # no longer a setting
    cfg_p.write_text(json.dumps(cfg))
    before = cfg_p.read_bytes()
    assert merge.do_init_library(str(lib) if with_path else None, str(ws)) == 2
    assert not utils.is_library(str(lib))                # nothing blessed
    assert cfg_p.read_bytes() == before                  # nothing written


@pytest.mark.spec("RUL-library_place_checked", "BLD-init_library_cases",
                  test="TST-merge_preflight-init_library_refuses_a_library_holding_the_workspace")
def test_init_library_refuses_a_library_holding_the_workspace(tmp_path):
    ws, _ = _fresh_ws_and_lib(tmp_path)
    cfg_p = ws / ".photos-ingest" / "photos-00-config.json"
    before = cfg_p.read_bytes()
    assert merge.do_init_library(str(tmp_path), str(ws)) == 2
    assert not utils.is_library(str(tmp_path))           # nothing blessed
    assert cfg_p.read_bytes() == before                  # nothing written


@pytest.mark.spec("merge-init-library-inside-no-path-reads-config-1")
def test_init_library_in_workspace_no_path_uses_config(tmp_path):
    ws, lib = _fresh_ws_and_lib(tmp_path)
    rc = merge.do_init_library(None, str(ws))
    assert rc == 0
    assert utils.is_library(str(lib))


@pytest.mark.spec("RUL-every_command_locks", test="TST-merge_preflight-init_library_without_path_refuses_a_locked_workspace")
def test_init_library_without_path_refuses_a_locked_workspace(tmp_path):
    # Reading the config is reading the workspace: a run holding its lock keeps init-library out.
    ws, lib = _fresh_ws_and_lib(tmp_path)
    held = utils.WorkspaceLock(str(ws))
    assert held.acquire() is True
    try:
        assert merge.do_init_library(None, str(ws)) == 1
        assert not utils.is_library(str(lib))            # nothing blessed
    finally:
        held.release()
    assert merge.do_init_library(None, str(ws)) == 0     # and the lock is released after a run
    held = utils.WorkspaceLock(str(ws))
    assert held.acquire() is True
    held.release()


@pytest.mark.spec("merge-init-library-outside-with-path-bless-only-1")
def test_init_library_outside_workspace_with_path_blesses_only(tmp_path):
    lib = tmp_path / "lib"
    lib.mkdir()
    plain = tmp_path / "not_a_ws"            # no guard -> not a workspace
    plain.mkdir()
    rc = merge.do_init_library(str(lib), str(plain))
    assert rc == 0
    assert utils.is_library(str(lib))


@pytest.mark.spec("merge-init-library-outside-no-path-error-1")
def test_init_library_outside_workspace_no_path_errors(tmp_path):
    plain = tmp_path / "not_a_ws"
    plain.mkdir()
    rc = merge.do_init_library(None, str(plain))
    assert rc == 2


@pytest.mark.spec("merge-init-library-creates-marker-1", "RUL-library_mark_made_by_setup", test="TST-merge_preflight-init_library_idempotent")
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

@pytest.mark.spec("merge-hold-two-locks-1", "merge-library-lock-1", test="TST-merge_preflight-locked_workflow_acquires_both_and_releases")
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


@pytest.mark.spec("merge-fail-lock-or-marker-mutates-nothing-1", "merge-library-lock-failfast-1", test="TST-merge_preflight-locked_workflow_exits_1_if_library_locked")
def test_locked_workflow_exits_1_if_library_locked(tmp_path):
    ws, lib = _make(tmp_path)
    held = utils.LibraryLock(str(lib))                # another workspace's merge holds the library
    assert held.acquire() is True

    def library_state():
        return sorted((str(p.relative_to(lib)), p.read_bytes() if p.is_file() else None, p.stat().st_mtime_ns)
                      for p in lib.rglob("*"))

    before = library_state()                          # the holder's owner record included
    try:
        assert merge._run_locked_workflow("plan", str(ws)) == 1
        assert library_state() == before              # refused at once: the library unchanged
    finally:
        held.release()


@pytest.mark.spec("merge-lock-acquisition-order-1", test="TST-merge_preflight-locked_workflow_exits_2_on_blocker")
def test_locked_workflow_exits_2_on_blocker(tmp_path):
    ws, lib = _make(tmp_path, complete_log=False)     # a precondition fails
    assert merge._run_locked_workflow("plan", str(ws)) == 2
    # The library lock must never have been taken (blocked before it).
    ll = utils.LibraryLock(str(lib))
    assert ll.acquire() is True
    ll.release()


# --- Tier 3: no-mutation / never-follows consequences ------------------------

@pytest.mark.spec("merge-lock-after-marker-1", "merge-marker-check-before-liblock-1", "RUL-library_mark_required", test="TST-merge_preflight-marker_check_precedes_library_lock_no_lockfile_dropped")
def test_marker_check_precedes_library_lock_no_lockfile_dropped(tmp_path):
    """§12 lock order: the .photos-library marker is validated BEFORE the library-side lock is taken.
    Against a marker-less library_root, the run blocks (rc 2) and must NEVER have created the
    .photos-merge.lock dotfile in the library — the lock is reached only after the marker passes."""
    ws, lib = _make(tmp_path, bless_lib=False)                  # library_root exists but is unblessed
    assert merge._run_locked_workflow("plan", str(ws)) == 2
    assert not os.path.exists(utils.library_lock_path(str(lib)))  # no lock dropped on a marker-less lib
    assert not os.path.exists(merge.merge_plan_path(str(ws)))     # and nothing planned


@pytest.mark.spec("gate-no-symlinks-by-dest-1", "merge-nongoal-no-follow-symlink-into-out-1")
def test_bydest_symlink_blocks_run_and_is_never_followed(tmp_path):
    """A symlink anywhere under 6-photos-by-dest blocks the whole run (rc 2) and is NEVER followed:
    its external target is not inventoried/planned and stays untouched. (Preflight only detects the
    link via islink; this asserts the safety consequence end-to-end.)"""
    external = tmp_path / "external"; external.mkdir()
    (external / "victim.jpg").write_bytes(b"PRECIOUS")
    ws, lib = _make(tmp_path)
    os.symlink(str(external), str(ws / "6-photos-by-dest" / "Trip" / "link"))
    assert merge._run_locked_workflow("plan", str(ws)) == 2
    assert not os.path.exists(merge.merge_plan_path(str(ws)))   # nothing planned
    assert (external / "victim.jpg").read_bytes() == b"PRECIOUS"  # target never followed/touched
    assert list(lib.iterdir()) == [lib / ".photos-library"]    # library untouched (marker only)


@pytest.mark.spec("merge-config-validated-1", "validate-fail-closed-1", "RUL-library_place_checked", test="TST-merge_preflight-a_library_holding_the_workspace_blocks_with_no_summary_no_placement")
def test_a_library_holding_the_workspace_blocks_with_no_summary_no_placement(tmp_path):
    """A library_root that holds the workspace is caught in the merge data path (validate_merge_config)
    and surfaces as a preflight blocker: rc 2, no plan, no photos-31 summary, no placement."""
    ws, lib = _make(tmp_path)
    utils.write_library_marker(str(tmp_path))
    cfg = json.loads((_ctl(ws) / "photos-00-config.json").read_text())
    cfg["merge"]["library_root"] = str(tmp_path)                # holds the workspace
    (_ctl(ws) / "photos-00-config.json").write_text(json.dumps(cfg))
    before = sorted(p.name for p in tmp_path.iterdir())
    assert merge._run_locked_workflow("plan", str(ws)) == 2
    assert not os.path.exists(merge.merge_plan_path(str(ws)))   # no plan
    assert not os.path.exists(merge.merge_summary_path(str(ws)))  # no summary
    assert sorted(p.name for p in tmp_path.iterdir()) == before  # nothing placed, no library lock left


@pytest.mark.spec("merge-sealed-newdump-warn-1", "RUL-sealed_new_dump_left", test="TST-merge_preflight-sealed_new_dump_left_in_place_and_library_untouched")
def test_sealed_new_dump_left_in_place_and_library_untouched(tmp_path):
    """The merge sealed-workspace path warns about a new dump but relocates nothing: the dumped file
    stays byte-identical in 0-sources and the library is untouched (only its marker)."""
    ws, lib = _make(tmp_path, sources_files=("newdump.jpg",))
    (ws / "0-sources" / "newdump.jpg").write_bytes(b"keepme")
    (_ctl(ws) / "photos-00-sealed.json").write_text('{"sealed": true, "merged_run_id": "r1"}')
    assert merge._run_locked_workflow("plan", str(ws)) == 2     # SEALED blocker
    assert (ws / "0-sources" / "newdump.jpg").read_bytes() == b"keepme"   # left in place
    assert list(lib.iterdir()) == [lib / ".photos-library"]    # library untouched


@pytest.mark.spec("lock-covers-whole-run-1", test="TST-merge_preflight-lock_contention_covers_execute_not_just_plan")
def test_lock_contention_covers_execute_not_just_plan(tmp_path):
    """The whole-run lock covers EXECUTE, not only plan: with the workspace lock held by another run,
    `execute` fails fast (rc 1) and writes no summary / places nothing."""
    ws, lib = _make(tmp_path)
    held = utils.WorkspaceLock(str(ws))
    assert held.acquire() is True
    try:
        assert merge._run_locked_workflow("execute", str(ws)) == 1   # refused under contention
    finally:
        held.release()
    assert not os.path.exists(merge.merge_summary_path(str(ws)))  # nothing executed
    assert list(lib.iterdir()) == [lib / ".photos-library"]


@pytest.mark.spec("RUL-only_prep_builds_structure", test="TST-merge_preflight-merge_never_repairs_a_missing_folder")
def test_merge_never_repairs_a_missing_folder(tmp_path):
    ws, _ = _make(tmp_path)
    os.rmdir(str(ws / "4-videos-by-date"))
    assert merge._run_locked_workflow("plan", str(ws)) == 2
    assert not (ws / "4-videos-by-date").exists()             # blocked, never recreated
