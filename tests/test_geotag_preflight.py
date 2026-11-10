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

"""Phase 1 (geotag) — Stage-1 preflight (photos-2-geotag, spec §7/§13).

The lifecycle guards + by-dest scope/re-prep gates that must pass before geotag runs. No
JSON artifacts are produced. photos_2_geotag / photos_utils come from conftest.py.
"""
import json
import os
import sys

import pytest

import photos_2_geotag as cal
import photos_utils as utils

MANAGED = ["0-sources", "1-strays", "2-missing-metadata", "3-redundant-jpgs",
           "4-videos-by-date", "5-photos-by-date", "6-photos-by-dest"]


def _ws(tmp_path, *, guard=True, sealed=False, config=True, handoff=True,
        bydest=("6-photos-by-dest/Trip/a.jpg",), handoff_files=None):
    ws = tmp_path / "ws"
    ws.mkdir()
    for d in MANAGED:
        (ws / d).mkdir()
    ctl = ws / ".photos-ingest"
    ctl.mkdir()
    if guard:
        (ctl / "photos-00-workspace-guard").touch()
    if sealed:
        (ctl / "photos-00-sealed.json").write_text('{"sealed": true, "merged_run_id": "r1"}')
    if config:
        cfg = {k: v for k, v in utils.CONFIG.items() if k != "jobs"}
        (ctl / "photos-00-config.json").write_text(json.dumps(cfg))
    for rel in bydest:
        p = ws / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(b"img")
    if handoff:
        files = handoff_files if handoff_files is not None else \
            [{"relative_path": rel, "media_class": "image"} for rel in bydest]
        (ctl / "photos-11-handoff.json").write_text(json.dumps({"files": files}))
    return ws


def _pf(ws):
    return cal.GeotagWorkflow(str(ws)).preflight()


# --- happy path --------------------------------------------------------------

def test_clean_workspace_passes(tmp_path):
    blockers, warnings, info = _pf(_ws(tmp_path))
    assert blockers == [], blockers
    assert info["by_dest_photos"] == 1
    assert info["handoff_sha256"]


# --- lifecycle guards --------------------------------------------------------

@pytest.mark.spec("geotag-uninitialized-hardstop-1")
def test_uninitialized_blocks(tmp_path):
    blockers, _, _ = _pf(_ws(tmp_path, guard=False))
    assert any("Not an initialized workspace" in b for b in blockers), blockers


@pytest.mark.spec("geotag-sealed-hardstop-1")
def test_sealed_blocks_and_warns_on_dump(tmp_path):
    ws = _ws(tmp_path, sealed=True)
    (ws / "0-sources" / "newdump.jpg").write_bytes(b"x")   # likely new dump
    blockers, warnings, _ = _pf(ws)
    assert any("SEALED" in b for b in blockers), blockers
    assert any("new dump" in w.lower() for w in warnings), warnings


@pytest.mark.spec("geotag-misplaced-root-hardstop-1")
def test_loose_root_file_blocks(tmp_path):
    ws = _ws(tmp_path)
    (ws / "stray.txt").write_text("loose")
    blockers, _, _ = _pf(ws)
    assert any("Misplaced entry at workspace root" in b for b in blockers), blockers


def test_nonmanaged_root_folder_blocks(tmp_path):
    """A misplaced dump drops folders at the root too, not just files — the base must hold only the
    managed 0-6 folders, so a non-managed root folder is blocked like a loose file."""
    ws = _ws(tmp_path)
    (ws / "randomdump").mkdir()
    blockers, _, _ = _pf(ws)
    assert any("Misplaced entry at workspace root" in b for b in blockers), blockers


@pytest.mark.spec("RUL-top_level_only_managed", test="TST-geotag_preflight-root_hidden_file_allowed")
def test_root_hidden_file_allowed(tmp_path):
    """A hidden file at the top level (a file manager's `.directory`) is a hidden entry, not a
    misplaced dump: it blocks nothing (shared contract §4)."""
    ws = _ws(tmp_path)
    (ws / ".directory").write_text("[Dolphin]")
    blockers, _, _ = _pf(ws)
    assert not any("Misplaced entry" in b for b in blockers), blockers


@pytest.mark.spec("RUL-top_level_only_managed", test="TST-geotag_preflight-every_misplaced_root_entry_named")
def test_every_misplaced_root_entry_named(tmp_path):
    """Any other top-level entry blocks, whatever its kind — a named pipe too — and the block names
    every one, not only the first."""
    ws = _ws(tmp_path)
    (ws / "stray.txt").write_text("loose")
    (ws / "randomdump").mkdir()
    os.mkfifo(str(ws / "pipe"))
    blockers, _, _ = _pf(ws)
    hit = [b for b in blockers if "Misplaced entry at workspace root" in b]
    assert hit and all(n in hit[0] for n in ("pipe", "randomdump", "stray.txt")), blockers


@pytest.mark.spec("RUL-geotag_merge_check_top_level_links", test="TST-geotag_preflight-directory_symlink_at_root_blocks")
def test_directory_symlink_at_root_blocks(tmp_path):
    """A symlink at the root is barred outright as a forbidden symlink (§13), never followed —
    checked before the structural/misplaced-folder guards."""
    ws = _ws(tmp_path)
    import os
    os.symlink(str(tmp_path), str(ws / "evil"))
    blockers, _, _ = _pf(ws)
    assert any("Forbidden symlink at the workspace root" in b for b in blockers), blockers


# --- config / handoff --------------------------------------------------------

def test_missing_config_blocks(tmp_path):
    blockers, _, _ = _pf(_ws(tmp_path, config=False))
    assert any("config" in b and "photos-cartographer prep" in b for b in blockers), blockers


def test_missing_handoff_blocks(tmp_path):
    blockers, _, _ = _pf(_ws(tmp_path, handoff=False))
    assert any("handoff" in b and "photos-cartographer prep" in b for b in blockers), blockers


@pytest.mark.spec("RUL-camera_group_derivation_versioned", test="TST-geotag_preflight-handoff_of_another_derivation_version_blocks")
@pytest.mark.parametrize("field", ["camera_group_key_version", "field_set_version"])
def test_handoff_of_another_derivation_version_blocks(tmp_path, field):
    rel = "6-photos-by-dest/Trip/a.jpg"
    (tmp_path / "now").mkdir(); (tmp_path / "old").mkdir()
    md = {"camera_group_key_version": utils.CAMERA_GROUP_KEY_VERSION, "field_set_version": utils.FIELD_SET_VERSION}
    blockers, _, _ = _pf(_ws(tmp_path / "now", handoff_files=[
        {"relative_path": rel, "media_class": "image", "metadata_status": md}]))
    assert blockers == [], blockers                                  # the running version's handoff passes
    blockers, _, _ = _pf(_ws(tmp_path / "old", handoff_files=[
        {"relative_path": rel, "media_class": "image", "metadata_status": dict(md, **{field: 0})}]))
    assert any("another version of cartographer" in b and rel in b and "prep plan" in b
               for b in blockers), blockers


# --- by-dest scope gates -----------------------------------------------------

@pytest.mark.spec("reprep-geotag-no-fix-1")
def test_reprep_gate_blocks_and_geotag_never_records_the_move(tmp_path):
    """Geotag does NO move recognition: a by-dest photo absent from the handoff (prep not re-run after
    the move) trips the re-prep gate. Geotag refuses and FIXES NOTHING — it never edits the handoff to
    record the moved file, and by-dest is left byte-identical. Re-recording is prep's job, not geotag's."""
    ws = _ws(tmp_path, bydest=("6-photos-by-dest/Trip/a.jpg",), handoff_files=[])  # a.jpg unrecorded
    ho_p = ws / ".photos-ingest" / "photos-11-handoff.json"
    bd = ws / "6-photos-by-dest" / "Trip" / "a.jpg"
    ho_before, bd_before = ho_p.read_bytes(), bd.read_bytes()
    blockers, _, _ = _pf(ws)
    assert any("prep has not yet recorded" in b for b in blockers), blockers
    assert ho_p.read_bytes() == ho_before                       # handoff NOT auto-edited by geotag
    assert bd.read_bytes() == bd_before                         # by-dest untouched
    assert json.loads(ho_p.read_text())["files"] == []          # the move was never recorded


@pytest.mark.spec("geotag-sources-empty-gate-1", "RUL-geotag_gates", test="TST-geotag_preflight-0sources_nonempty_blocks")
def test_0sources_nonempty_blocks(tmp_path):
    ws = _ws(tmp_path)
    (ws / "0-sources" / "leftover.jpg").write_bytes(b"x")
    blockers, _, _ = _pf(ws)
    assert any("0-sources/ is not empty" in b for b in blockers), blockers


@pytest.mark.spec("geotag-bydate-empty-gate-1", "loop-geotag-gating-preconditions-1", test="TST-geotag_preflight-photo_left_in_by_date_blocks")
def test_photo_left_in_by_date_blocks(tmp_path):
    ws = _ws(tmp_path)
    (ws / "5-photos-by-date" / "2023-01-01--00-00-00.jpg").write_bytes(b"x")
    blockers, _, _ = _pf(ws)
    assert any("5-photos-by-date/ still contains" in b for b in blockers), blockers


@pytest.mark.spec("geotag-development-check-strict-empty-1", "loop-dev-before-geotag-blocks-1", test="TST-geotag_preflight-dev_subfolder_blocks")
def test_dev_subfolder_blocks(tmp_path):
    ws = _ws(tmp_path)
    (ws / "6-photos-by-dest" / "Trip" / "jpg").mkdir()       # empty dev subfolder still blocks
    blockers, _, _ = _pf(ws)
    assert any("Development has already started" in b for b in blockers), blockers


@pytest.mark.spec("geotag-development-check-all-phases-1", "RUL-development_after_merge", test="TST-geotag_preflight-dev_subfolder_blocks_at_execute")
def test_dev_subfolder_blocks_at_execute(tmp_path):
    # §7.1 is presence-strict AND re-checked at execute/finalize: an empty jpg/tif subfolder created
    # between `run` and `execute` must hard-stop execution (the per-op preconditions cannot catch it,
    # because the breakout moved no planned file).
    ws = _ws(tmp_path)
    (ws / "6-photos-by-dest" / "Trip" / "jpg").mkdir()
    blockers, _, _ = cal.GeotagWorkflow(str(ws)).preflight(for_execute=True)
    assert any("Development has already started" in b for b in blockers), blockers


def test_execute_preflight_still_skips_planning_scope_gates(tmp_path):
    # Over-blocking guard: only the dev-subfolder presence check was added to the execute path. A
    # planning-only scope gate (a leftover in 0-sources) must NOT block execute.
    ws = _ws(tmp_path)
    (ws / "0-sources" / "leftover.jpg").write_bytes(b"x")
    blockers, _, _ = cal.GeotagWorkflow(str(ws)).preflight(for_execute=True)
    assert not any("0-sources/ is not empty" in b for b in blockers), blockers


@pytest.mark.spec("geotag-bydest-no-video-1", "loop-sort-photo-only-1", test="TST-geotag_preflight-video_in_by_dest_blocks")
def test_video_in_by_dest_blocks(tmp_path):
    ws = _ws(tmp_path)
    (ws / "6-photos-by-dest" / "Trip" / "clip.mp4").write_bytes(b"v")
    blockers, _, _ = _pf(ws)
    assert any("must contain only photos" in b and "video" in b for b in blockers), blockers


@pytest.mark.spec("geotag-bydest-photo-only-1", "RUL-geotag_gates", "RUL-sort_photos_only", test="TST-geotag_preflight-other_file_in_by_dest_blocks")
def test_other_file_in_by_dest_blocks(tmp_path):
    ws = _ws(tmp_path)
    (ws / "6-photos-by-dest" / "Trip" / "notes.txt").write_text("hi")
    blockers, _, _ = _pf(ws)
    assert any("must contain only photos" in b and "non-media" in b for b in blockers), blockers


# --- §13.1 re-prep-after-move gate -------------------------------------------

@pytest.mark.spec("geotag-targeted-reprep-blocker-1", "loop-no-behind-preps-back-1", test="TST-geotag_preflight-unrecorded_by_dest_photo_demands_reprep")
def test_unrecorded_by_dest_photo_demands_reprep(tmp_path):
    ws = _ws(tmp_path)                                        # a.jpg recorded
    (ws / "6-photos-by-dest" / "Trip" / "b.jpg").write_bytes(b"img")   # NOT in the handoff
    blockers, _, _ = _pf(ws)
    assert any("has not yet recorded" in b and "photos-cartographer prep" in b for b in blockers), blockers


@pytest.mark.spec("geotag-prep-after-move-required-1")
def test_missing_by_date_photo_demands_reprep(tmp_path):
    # The handoff still records a 5-photos-by-date photo that is now gone (moved into by-dest).
    files = [{"relative_path": "6-photos-by-dest/Trip/a.jpg", "media_class": "image"},
             {"relative_path": "5-photos-by-date/old.jpg", "media_class": "image"}]
    ws = _ws(tmp_path, handoff_files=files)                   # 5-photos-by-date/old.jpg not on disk
    blockers, _, _ = _pf(ws)
    assert any("has not yet recorded" in b for b in blockers), blockers


# --- §13.1 auto re-prep for a clean by-dest move -----------------------------

import types as _types


class _CollectRep:
    def __init__(self): self.logs, self.errors = [], []
    def log(self, msg, **k): self.logs.append(msg)
    def warn(self, msg, **k): pass
    def error(self, msg, **k): self.errors.append(msg)


def _autoreprep(ws, monkeypatch, *, command="plan", jobs=4, fail=None):
    """Drive the auto-reprep helper with prep's locked body stubbed; return (prep commands it ran, reporter)."""
    import photos_1_prep as prep
    calls = []
    def fake_prep_run_locked(a, workspace_root, reporter):
        calls.append(a.command)
        if fail is not None and a.command == fail:
            raise SystemExit(2)
    monkeypatch.setattr(prep, "_run_locked", fake_prep_run_locked)
    rep = _CollectRep()
    cal._auto_reprep_for_clean_move(_types.SimpleNamespace(command=command, jobs=jobs), str(ws), rep)
    return calls, rep


@pytest.mark.spec("geotag-auto-reprep-clean-move-1")
def test_auto_reprep_runs_prep_plan_then_execute_for_clean_move(tmp_path, monkeypatch):
    """A clean by-dest move (0-sources empty + an unrecorded by-dest photo) makes geotag plan auto-run the
    REAL prep phases — plan then execute, in order — so the operator goes straight to geotag. prep does
    the mutation; geotag only orchestrates."""
    ws = _ws(tmp_path, bydest=("6-photos-by-dest/Trip/a.jpg",), handoff_files=[])   # a.jpg unrecorded
    calls, rep = _autoreprep(ws, monkeypatch)
    assert calls == ["plan", "execute"], calls
    assert any("running prep plan + execute" in m for m in rep.logs), rep.logs


def test_auto_reprep_skips_when_nothing_pending(tmp_path, monkeypatch):
    calls, _ = _autoreprep(_ws(tmp_path), monkeypatch)               # a.jpg recorded → nothing pending
    assert calls == []


@pytest.mark.spec("geotag-auto-reprep-sources-nonempty-skip-1")
def test_auto_reprep_skips_when_sources_nonempty(tmp_path, monkeypatch):
    """0-sources holding a dump is the cheapest hard gate — auto-reprep must NOT silently ingest it; it
    bows out and leaves the in-lock scope gate to report the unprocessed dump."""
    ws = _ws(tmp_path, bydest=("6-photos-by-dest/Trip/a.jpg",), handoff_files=[])
    (ws / "0-sources" / "newdump.jpg").write_bytes(b"x")
    calls, _ = _autoreprep(ws, monkeypatch)
    assert calls == []


def test_auto_reprep_skips_when_sealed(tmp_path, monkeypatch):
    ws = _ws(tmp_path, sealed=True, bydest=("6-photos-by-dest/Trip/a.jpg",), handoff_files=[])
    assert _autoreprep(ws, monkeypatch)[0] == []


def test_auto_reprep_skips_when_uninitialized(tmp_path, monkeypatch):
    ws = _ws(tmp_path, guard=False, bydest=("6-photos-by-dest/Trip/a.jpg",), handoff_files=[])
    assert _autoreprep(ws, monkeypatch)[0] == []


def test_auto_reprep_skips_for_non_plan_command(tmp_path, monkeypatch):
    ws = _ws(tmp_path, bydest=("6-photos-by-dest/Trip/a.jpg",), handoff_files=[])
    assert _autoreprep(ws, monkeypatch, command="execute")[0] == []


def test_auto_reprep_propagates_prep_failure(tmp_path, monkeypatch):
    """If the auto prep fails (e.g. an ambiguous move it can't record), geotag stops — never proceeds on a
    half-done state."""
    ws = _ws(tmp_path, bydest=("6-photos-by-dest/Trip/a.jpg",), handoff_files=[])
    with pytest.raises(SystemExit) as ei:
        _autoreprep(ws, monkeypatch, fail="plan")
    assert ei.value.code == 2


# --- main() / lock / exit codes ----------------------------------------------

def _main(monkeypatch, ws):
    monkeypatch.chdir(str(ws))
    monkeypatch.setattr(sys, "argv", ["photos-2-geotag", "plan"])
    try:
        cal.main()
        return 0
    except SystemExit as e:
        return e.code if isinstance(e.code, int) else (0 if e.code is None else 1)


def test_main_clean_passes_and_holds_lock(tmp_path, monkeypatch, capsys):
    # The minimal fixture's handoff records carry no folder_class/metadata, so the by-dest model
    # is empty here (the rich model path is exercised in test_geotag_model.py). Preflight
    # passes and main() advances into the Stage 2-4 build, holding the lock throughout.
    code = _main(monkeypatch, _ws(tmp_path))
    out = capsys.readouterr()
    assert code == 0, out.err
    assert "Lock acquired" in out.err
    assert "Model built" in out.out


def test_main_blocker_exits_2(tmp_path, monkeypatch, capsys):
    code = _main(monkeypatch, _ws(tmp_path, guard=False))
    assert code == 2
    assert "Geotag cannot proceed" in capsys.readouterr().err


@pytest.mark.spec("geotag-no-json-before-decision-stage-1", "geotag-stale-no-json-1")
def test_preflight_writes_no_json(tmp_path):
    ws = _ws(tmp_path)
    _pf(ws)
    arts = [f for f in os.listdir(ws / ".photos-ingest") if f.startswith("photos-2")]
    assert arts == []                                        # no geotag JSON in preflight


@pytest.mark.spec("geotag-incomplete-structure-hardstop-1")
def test_missing_managed_folder_blocks(tmp_path):
    """An activated workspace missing a managed 0-6 folder is non-conforming — hard stop."""
    import shutil
    ws = _ws(tmp_path)
    shutil.rmtree(ws / "4-videos-by-date")
    blockers, _, _ = _pf(ws)
    assert any("non-conforming" in b and "4-videos-by-date" in b for b in blockers), blockers


def test_dangling_and_managed_named_root_symlinks_blocked(tmp_path):
    """A dangling root symlink (neither file nor dir) and a symlink NAMED like a managed folder (which
    os.path.isdir would resolve through) are both barred by the lstat-based symlink guard (§13)."""
    import os
    ws = _ws(tmp_path)
    os.symlink(str(tmp_path / "nonexistent"), str(ws / "dangling"))
    b1, _, _ = _pf(ws)
    assert any("Forbidden symlink at the workspace root" in b and "dangling" in b for b in b1), b1
    os.remove(ws / "dangling")
    os.rmdir(ws / "5-photos-by-date")
    os.symlink(str(tmp_path), str(ws / "5-photos-by-date"))           # a managed folder that is a symlink
    b2, _, _ = _pf(ws)
    assert any("Forbidden symlink at the workspace root" in b for b in b2), b2


def test_dot_named_root_symlink_blocked(tmp_path):
    """A DOT-named root symlink is barred too: the only legitimate dot entries (.photos-ingest*) are
    real directories, so a dot-named symlink at the root is forbidden, not skipped (§13)."""
    import os
    ws = _ws(tmp_path)
    os.symlink(str(tmp_path), str(ws / ".evil"))
    blockers, _, _ = _pf(ws)
    assert any("Forbidden symlink at the workspace root" in b for b in blockers), blockers


@pytest.mark.spec("RUL-only_prep_builds_structure", test="TST-geotag_preflight-geotag_never_repairs_a_missing_folder")
def test_geotag_never_repairs_a_missing_folder(tmp_path):
    import shutil
    ws = _ws(tmp_path)
    shutil.rmtree(ws / "4-videos-by-date")
    blockers, _, _ = _pf(ws)
    assert blockers
    assert not (ws / "4-videos-by-date").exists()             # blocked, never recreated


@pytest.mark.spec("RUL-lock_before_reading", test="TST-geotag_preflight-auto_reprep_runs_inside_geotags_lock")
def test_auto_reprep_runs_inside_geotags_lock(tmp_path, monkeypatch):
    """Geotag takes the workspace lock before it reads anything, and runs prep's plan and execute for a
    clean sort inside that same lock — no read before it, no other run slipping in between."""
    import types as _t
    import photos_1_prep as prep
    ws = _ws(tmp_path, bydest=("6-photos-by-dest/Trip/a.jpg",), handoff_files=[])
    held = []
    def fake_prep_run_locked(a, workspace_root, reporter):
        held.append((a.command, utils.WorkspaceLock(workspace_root, create=False).held_owner() is not None))
    monkeypatch.setattr(prep, "_run_locked", fake_prep_run_locked)
    def stop(self):
        raise SystemExit(9)                                          # geotag's own planning is not under test
    monkeypatch.setattr(cal.GeotagWorkflow, "preflight", stop)
    monkeypatch.chdir(ws)
    with pytest.raises(SystemExit):
        cal.run(_t.SimpleNamespace(command="plan", jobs=1))
    assert held == [("plan", True), ("execute", True)], held


@pytest.mark.spec("RUL-only_prep_builds_structure", test="TST-geotag_preflight-geotag_and_merge_create_nothing_outside_a_workspace")
def test_geotag_and_merge_create_nothing_outside_a_workspace(tmp_path, monkeypatch, capsys):
    """Run in a folder that is not a workspace, geotag and merge stop without creating the control
    directory — not even for their lock file. Only prep creates it."""
    import types as _t
    import photos_3_merge as merge
    d = tmp_path / "not-a-workspace"; d.mkdir()
    monkeypatch.chdir(d)
    with pytest.raises(SystemExit) as ei:
        cal.run(_t.SimpleNamespace(command="plan", jobs=1))
    assert ei.value.code == 2 and "Not an initialized workspace" in capsys.readouterr().err
    assert merge._run_locked_workflow("plan", str(d)) == 2
    assert list(d.iterdir()) == []


@pytest.mark.spec("RUL-one_configuration", test="TST-geotag_preflight-geotag_classifies_by_the_workspaces_extension_lists")
def test_geotag_classifies_by_the_workspaces_extension_lists(tmp_path, monkeypatch):
    """Geotag reads the workspace's own configuration, extension lists included: a `.webp` the user
    listed as an image is a photo in photos by destination, not a file of no media class — whatever
    the built-in lists say."""
    ws = _ws(tmp_path, bydest=("6-photos-by-dest/Trip/a.webp",))
    cfg_p = ws / ".photos-ingest" / "photos-00-config.json"
    cfg = json.loads(cfg_p.read_text())
    cfg["media_extensions"]["image"].append("webp")
    cfg_p.write_text(json.dumps(cfg))
    assert utils.media_class_for_ext(".webp") == "other"            # the built-in lists say other
    blockers, _, _ = _pf(ws)
    assert not any("a.webp" in b for b in blockers), blockers
    assert utils.media_class_for_ext(".webp") == "image"


@pytest.mark.spec("RUL-config_complete", test="TST-geotag_preflight-a_missing_setting_stops_every_phase")
def test_a_missing_setting_stops_every_phase(tmp_path, monkeypatch):
    """A setting missing from the workspace's configuration is never filled from the program's defaults:
    prep's load, geotag and merge each stop, naming the setting and the value to add."""
    import photos_3_merge as merge
    ws = _ws(tmp_path)
    cfg_p = ws / ".photos-ingest" / "photos-00-config.json"
    cfg = json.loads(cfg_p.read_text())
    del cfg["gpx_extrapolation_max_seconds"]
    del cfg["zfs"]["snapshot_prefix"]
    cfg_p.write_text(json.dumps(cfg))
    with pytest.raises(ValueError) as ei:
        utils.load_or_seed_config(str(ws))                          # prep's path
    assert "gpx_extrapolation_max_seconds" in str(ei.value) and "zfs.snapshot_prefix" in str(ei.value)
    assert json.loads(cfg_p.read_text()) == cfg                     # never filled in
    for blockers in (_pf(ws)[0], merge.MergeWorkflow(str(ws)).preflight()[0]):
        assert any("missing setting" in b and "gpx_extrapolation_max_seconds" in b for b in blockers), blockers


@pytest.mark.spec("RUL-config_no_unknown_settings", test="TST-geotag_preflight-an_unknown_setting_stops_every_phase")
@pytest.mark.parametrize("edit, named", [
    (lambda c: c["media_extensions"].__setitem__("audio", ["mp3"]), "media_extensions.audio"),   # a class of one's own
    (lambda c: c["folders"].__setitem__("extra", "9-extra"), "folders.extra"),                     # a role of one's own
    (lambda c: c["zfs"].__setitem__("snapshot_required", True), "zfs.snapshot_required"),          # a misspelling
    (lambda c: c.__setitem__("gpx_rot", "/tmp"), "gpx_rot"),                                       # at the top level
])
def test_an_unknown_setting_stops_every_phase(tmp_path, monkeypatch, edit, named):
    """A setting cartographer does not know is never ignored: prep's load, geotag and merge each stop,
    naming it — the user would otherwise believe it took effect."""
    import photos_3_merge as merge
    ws = _ws(tmp_path)
    cfg_p = ws / ".photos-ingest" / "photos-00-config.json"
    cfg = json.loads(cfg_p.read_text())
    edit(cfg)
    cfg_p.write_text(json.dumps(cfg))
    with pytest.raises(ValueError) as ei:
        utils.load_or_seed_config(str(ws))                          # prep's path
    assert named in str(ei.value) and "does not know" in str(ei.value)
    for blockers in (_pf(ws)[0], merge.MergeWorkflow(str(ws)).preflight()[0]):
        assert any("does not know" in b and named in b for b in blockers), blockers
