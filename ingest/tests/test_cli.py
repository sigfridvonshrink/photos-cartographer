"""Phase 11 — CLI coverage: exercise main()'s argparse dispatch, the whole-run lock, and
error exits. main() is invoked in-process (sys.argv + chdir) so coverage traces it; the
rest of the suite bypasses main() entirely by calling the workflow objects directly.

Empty workspaces keep these fast. photos_1_prep / photos_utils come from conftest.py.
"""
import fcntl
import json
import os
import sys

import pytest

import photos_1_prep as prep
import photos_utils as utils


def _ws(tmp_path, *, config=None):
    ws = tmp_path / "ws"
    ws.mkdir()
    for d in ("0-sources", "1-strays", "2-missing-metadata", "3-redundant-jpgs",
              "4-videos-by-date", "5-photos-by-date", "6-photos-by-dest"):
        (ws / d).mkdir()
    (ws / ".photos-ingest").mkdir()
    (ws / ".photos-ingest" / "photos-00-workspace-guard").touch()
    cfg = config if config is not None else {k: v for k, v in utils.CONFIG.items() if k != "jobs"}
    if config is None:
        cfg = dict(cfg); cfg["zfs"] = {"enabled": False}   # never shell out to `zfs snapshot`
    (ws / ".photos-ingest" / "photos-00-config.json").write_text(json.dumps(cfg))
    return ws


def _main(monkeypatch, ws, *argv):
    """Run main() in-process against `ws`; return the exit code (0 if it returns normally)."""
    monkeypatch.chdir(str(ws))
    monkeypatch.setattr(sys, "argv", ["photos-1-prep", *argv])
    try:
        prep.main()
        return 0
    except SystemExit as e:
        return e.code if isinstance(e.code, int) else (0 if e.code is None else 1)


# --- happy path --------------------------------------------------------------

def test_plan_prints_json_and_locks(tmp_path, monkeypatch, capsys):
    code = _main(monkeypatch, _ws(tmp_path), "plan")
    out = capsys.readouterr()
    assert code == 0, out.err
    assert json.loads(out.out)["command"] == "prep"
    assert "Lock acquired" in out.err and "Lock released" in out.err


def test_plan_output_dryrun_execute_roundtrip(tmp_path, monkeypatch, capsys):
    ws = _ws(tmp_path)
    assert _main(monkeypatch, ws, "plan", "--output", "p.json") == 0
    assert (ws / "p.json").exists()
    assert "Plan saved" in capsys.readouterr().out
    assert _main(monkeypatch, ws, "dry-run", "--plan", "p.json") == 0
    assert _main(monkeypatch, ws, "execute", "--plan", "p.json") == 0


def test_prune_quarantine_dry_run_and_delete(tmp_path, monkeypatch, capsys):
    ws = _ws(tmp_path)
    qd = ws / ".photos-ingest-quarantine" / "20260101T000000Z-abc123"
    qd.mkdir(parents=True)
    (qd / "x.jpg").write_bytes(b"dup")
    assert _main(monkeypatch, ws, "prune-quarantine") == 0
    assert "dry-run" in capsys.readouterr().out and qd.exists()
    assert _main(monkeypatch, ws, "prune-quarantine", "--plan-id", "20260101T000000Z-abc123", "--yes") == 0
    assert not qd.exists()


# --- sealed-workspace guard --------------------------------------------------

def test_sealed_workspace_refuses_and_releases_lock(tmp_path, monkeypatch, capsys):
    ws = _ws(tmp_path)
    (ws / ".photos-ingest" / "photos-00-sealed.json").write_text('{"sealed": true}')
    code = _main(monkeypatch, ws, "plan")
    out = capsys.readouterr()
    assert code == 2
    assert "SEALED" in out.err
    assert "Lock released" in out.err           # the lock is still released cleanly


def test_sealed_workspace_warns_on_new_dump(tmp_path, monkeypatch, capsys):
    ws = _ws(tmp_path)
    (ws / ".photos-ingest" / "photos-00-sealed.json").write_text('{"sealed": true}')
    (ws / "0-sources" / "newdump.jpg").write_bytes(b"img")
    assert _main(monkeypatch, ws, "plan") == 2
    assert "new dump" in capsys.readouterr().err.lower()


# --- error exits -------------------------------------------------------------

def test_locked_workspace_fails_fast(tmp_path, monkeypatch, capsys):
    ws = _ws(tmp_path)
    lock = ws / ".photos-ingest" / "photos-00-workspace.lock"
    fd = os.open(str(lock), os.O_RDWR | os.O_CREAT, 0o644)
    fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
    try:
        code = _main(monkeypatch, ws, "plan")
        assert code != 0 and "locked" in capsys.readouterr().err.lower()
    finally:
        fcntl.flock(fd, fcntl.LOCK_UN); os.close(fd)


def test_missing_plan_file_exits_nonzero(tmp_path, monkeypatch):
    assert _main(monkeypatch, _ws(tmp_path), "execute", "--plan", "nope.json") != 0


def test_invalid_config_rejected_at_load(tmp_path, monkeypatch, capsys):
    bad = {k: v for k, v in utils.CONFIG.items() if k != "jobs"}
    bad = dict(bad); bad["zfs"] = {"enabled": False}
    bad["gpx_interpolation_max_distance_meters"] = -1
    code = _main(monkeypatch, _ws(tmp_path, config=bad), "plan")
    assert code != 0 and "config:" in capsys.readouterr().err


def test_bad_jobs_arg_rejected(tmp_path, monkeypatch):
    assert _main(monkeypatch, _ws(tmp_path), "-j", "0", "plan") != 0
