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

def test_uninitialized_blocks(tmp_path):
    blockers, _, _ = _pf(_ws(tmp_path, guard=False))
    assert any("Not an initialized workspace" in b for b in blockers), blockers


def test_sealed_blocks_and_warns_on_dump(tmp_path):
    ws = _ws(tmp_path, sealed=True)
    (ws / "0-sources" / "newdump.jpg").write_bytes(b"x")   # likely new dump
    blockers, warnings, _ = _pf(ws)
    assert any("SEALED" in b for b in blockers), blockers
    assert any("new dump" in w.lower() for w in warnings), warnings


def test_loose_root_file_blocks(tmp_path):
    ws = _ws(tmp_path)
    (ws / "stray.txt").write_text("loose")
    blockers, _, _ = _pf(ws)
    assert any("Loose file at the workspace root" in b for b in blockers), blockers


def test_nonmanaged_root_folder_blocks(tmp_path):
    """A misplaced dump drops folders at the root too, not just files — the base must hold only the
    managed 0-6 folders, so a non-managed root folder is blocked like a loose file."""
    ws = _ws(tmp_path)
    (ws / "randomdump").mkdir()
    blockers, _, _ = _pf(ws)
    assert any("Misplaced folder at the workspace root" in b for b in blockers), blockers


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
    assert any("config" in b and "photos-ingest prep" in b for b in blockers), blockers


def test_missing_handoff_blocks(tmp_path):
    blockers, _, _ = _pf(_ws(tmp_path, handoff=False))
    assert any("handoff" in b and "photos-ingest prep" in b for b in blockers), blockers


# --- by-dest scope gates -----------------------------------------------------

def test_0sources_nonempty_blocks(tmp_path):
    ws = _ws(tmp_path)
    (ws / "0-sources" / "leftover.jpg").write_bytes(b"x")
    blockers, _, _ = _pf(ws)
    assert any("0-sources/ is not empty" in b for b in blockers), blockers


def test_photo_left_in_by_date_blocks(tmp_path):
    ws = _ws(tmp_path)
    (ws / "5-photos-by-date" / "2023-01-01--00-00-00.jpg").write_bytes(b"x")
    blockers, _, _ = _pf(ws)
    assert any("5-photos-by-date/ still contains" in b for b in blockers), blockers


def test_dev_subfolder_blocks(tmp_path):
    ws = _ws(tmp_path)
    (ws / "6-photos-by-dest" / "Trip" / "jpg").mkdir()       # empty dev subfolder still blocks
    blockers, _, _ = _pf(ws)
    assert any("Development has already started" in b for b in blockers), blockers


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


def test_video_in_by_dest_blocks(tmp_path):
    ws = _ws(tmp_path)
    (ws / "6-photos-by-dest" / "Trip" / "clip.mp4").write_bytes(b"v")
    blockers, _, _ = _pf(ws)
    assert any("must contain only photos" in b and "video" in b for b in blockers), blockers


def test_other_file_in_by_dest_blocks(tmp_path):
    ws = _ws(tmp_path)
    (ws / "6-photos-by-dest" / "Trip" / "notes.txt").write_text("hi")
    blockers, _, _ = _pf(ws)
    assert any("must contain only photos" in b and "non-media" in b for b in blockers), blockers


# --- §13.1 re-prep-after-move gate -------------------------------------------

def test_unrecorded_by_dest_photo_demands_reprep(tmp_path):
    ws = _ws(tmp_path)                                        # a.jpg recorded
    (ws / "6-photos-by-dest" / "Trip" / "b.jpg").write_bytes(b"img")   # NOT in the handoff
    blockers, _, _ = _pf(ws)
    assert any("has not yet recorded" in b and "photos-ingest prep" in b for b in blockers), blockers


def test_missing_by_date_photo_demands_reprep(tmp_path):
    # The handoff still records a 5-photos-by-date photo that is now gone (moved into by-dest).
    files = [{"relative_path": "6-photos-by-dest/Trip/a.jpg", "media_class": "image"},
             {"relative_path": "5-photos-by-date/old.jpg", "media_class": "image"}]
    ws = _ws(tmp_path, handoff_files=files)                   # 5-photos-by-date/old.jpg not on disk
    blockers, _, _ = _pf(ws)
    assert any("has not yet recorded" in b for b in blockers), blockers


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


def test_preflight_writes_no_json(tmp_path):
    ws = _ws(tmp_path)
    _pf(ws)
    arts = [f for f in os.listdir(ws / ".photos-ingest") if f.startswith("photos-2")]
    assert arts == []                                        # no geotag JSON in preflight


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
