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
import photos_2_geotag as geotag
import photos_3_merge as merge
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

@pytest.mark.spec("prep-plan-canonical-path-1", "prep-run-under-single-lock-1")
def test_plan_saves_canonical_and_locks(tmp_path, monkeypatch, capsys):
    ws = _ws(tmp_path)
    code = _main(monkeypatch, ws, "plan")
    out = capsys.readouterr()
    assert code == 0, out.err
    pp = utils.prep_plan_path(str(ws))
    assert os.path.exists(pp)                                  # auto-saved to the canonical path
    assert json.load(open(pp))["command"] == "prep"
    assert "Plan saved to" in out.out                         # and the location is announced
    assert "Lock acquired" in out.err and "Lock released" in out.err


def test_plan_surfaces_blockers_and_exits_nonzero(tmp_path, monkeypatch, capsys):
    # A stray folder at the root of an initialized workspace is a "misplaced entry" blocker; `plan`
    # must surface it (not just silently save the plan) and exit non-zero so the operator sees it now.
    ws = _ws(tmp_path)
    (ws / "test-ingest").mkdir()
    code = _main(monkeypatch, ws, "plan")
    out = capsys.readouterr()
    assert code == 2, out.err
    assert os.path.exists(utils.prep_plan_path(str(ws)))          # plan still saved for inspection
    assert "CANNOT be executed" in out.err
    assert "Misplaced entry at workspace root" in out.err and "test-ingest" in out.err


def test_plan_dryrun_execute_roundtrip(tmp_path, monkeypatch, capsys):
    ws = _ws(tmp_path)
    assert _main(monkeypatch, ws, "plan") == 0                # writes canonical plan
    assert os.path.exists(utils.prep_plan_path(str(ws)))
    assert "Plan saved to" in capsys.readouterr().out
    assert _main(monkeypatch, ws, "dry-run") == 0             # reads it, no flag needed
    assert _main(monkeypatch, ws, "execute") == 0             # reads it, no flag needed


@pytest.mark.spec("prep-dryrun-not-simulation-1", "prep-dryrun-summary-not-dump-1")
def test_dry_run_summarizes_not_dumps(tmp_path, monkeypatch, capsys):
    ws = _ws(tmp_path)
    assert _main(monkeypatch, ws, "plan") == 0
    capsys.readouterr()
    assert _main(monkeypatch, ws, "dry-run") == 0
    out = capsys.readouterr().out
    assert "Dry-run: validated plan" in out
    assert "Full plan:" in out                        # points to the saved artifact for detail
    import pytest as _pt
    with _pt.raises(json.JSONDecodeError):            # a summary, not the full plan JSON
        json.loads(out)


@pytest.mark.spec("prep-replan-never-clobbers-1")
def test_replan_backs_up_previous_plan(tmp_path, monkeypatch, capsys):
    ws = _ws(tmp_path)
    assert _main(monkeypatch, ws, "plan") == 0
    capsys.readouterr()
    assert _main(monkeypatch, ws, "plan") == 0                # re-plan
    assert "Previous plan backed up to" in capsys.readouterr().out
    cd = ws / ".photos-ingest"
    backups = sorted(n for n in os.listdir(cd)
                     if n.startswith("photos-10-prep-plan-") and n.endswith(".json"))
    assert backups == ["photos-10-prep-plan-001.json"]       # incremental -NNN suffix, not clobbered


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

@pytest.mark.spec("prep-sealed-workspace-blocks-1")
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


@pytest.mark.spec("prep-sealed-new-dump-warning-1", "seal-new-dump-warn-1")
def test_sealed_new_dump_is_left_exactly_in_place(tmp_path, monkeypatch, capsys):
    """The sealed-workspace new-dump path only WARNS — it never relocates the dumped file. After the
    refusal the file is byte-identical at its original 0-sources path (the operator must move it to a
    fresh workspace themselves; prep touches nothing)."""
    ws = _ws(tmp_path)
    (ws / ".photos-ingest" / "photos-00-sealed.json").write_text('{"sealed": true}')
    dump = ws / "0-sources" / "newdump.jpg"
    dump.write_bytes(b"original-bytes")
    assert _main(monkeypatch, ws, "plan") == 2
    assert dump.read_bytes() == b"original-bytes"               # left exactly where it is
    assert os.listdir(ws / "0-sources") == ["newdump.jpg"]     # nothing relocated


@pytest.mark.spec("prep-prune-quarantine-exempt-seal-1", "seal-prune-exception-1")
def test_prune_quarantine_is_the_sole_op_allowed_on_a_sealed_workspace(tmp_path, monkeypatch, capsys):
    """The seal blocks ONLY plan/dry-run/execute; prune-quarantine is the sole maintenance op that
    still runs on a sealed (terminal) workspace — quarantine cleanup must survive the seal. Assert it
    is NOT refused with exit-2 SEALED, and that the --yes delete actually clears the quarantine."""
    ws = _ws(tmp_path)
    (ws / ".photos-ingest" / "photos-00-sealed.json").write_text('{"sealed": true}')
    qd = ws / ".photos-ingest-quarantine" / "20260101T000000Z-abc123"
    qd.mkdir(parents=True)
    (qd / "x.jpg").write_bytes(b"dup")
    assert _main(monkeypatch, ws, "prune-quarantine") == 0       # runs despite the seal (not exit-2)
    out = capsys.readouterr()
    assert "dry-run" in out.out and qd.exists()                  # default dry-run preserved it
    assert "SEALED" not in out.err                               # never hit the seal guard
    assert _main(monkeypatch, ws, "prune-quarantine",
                 "--plan-id", "20260101T000000Z-abc123", "--yes") == 0
    assert not qd.exists()                                       # delete worked on the sealed ws


@pytest.mark.spec("merge-sealed-all-scripts-refuse-prune-excepted-1")
def test_seal_refuses_all_three_phases_except_prune_quarantine(tmp_path, monkeypatch, capsys):
    """§9.4 / shared §13.7: once a workspace is SEALED, every media-mutating phase refuses on it —
    prep plan, geotag plan, AND merge plan all hard-stop with exit 2 — with the SOLE exception of prep
    `prune-quarantine`, which still runs so quarantine cleanup survives the seal."""
    lib = tmp_path / "lib"; lib.mkdir()
    cfg = {k: v for k, v in utils.CONFIG.items() if k != "jobs"}
    cfg["zfs"] = {"enabled": False}
    cfg["merge"] = dict(cfg.get("merge") or {}); cfg["merge"]["library_root"] = str(lib)
    ws = _ws(tmp_path, config=cfg)
    utils.write_library_marker(str(lib))
    (ws / ".photos-ingest" / "photos-00-sealed.json").write_text('{"sealed": true}')

    # prep refuses
    assert _main(monkeypatch, ws, "plan") == 2
    assert "SEALED" in capsys.readouterr().err

    # geotag refuses
    monkeypatch.chdir(str(ws))
    monkeypatch.setattr(sys, "argv", ["photos-2-geotag", "plan"])
    try:
        geotag.main(); gcode = 0
    except SystemExit as e:
        gcode = e.code if isinstance(e.code, int) else (0 if e.code is None else 1)
    assert gcode == 2

    # merge refuses
    assert merge._run_locked_workflow("plan", str(ws)) == 2

    # ...but prune-quarantine is the sole exception — it still runs on the sealed workspace.
    qd = ws / ".photos-ingest-quarantine" / "20260101T000000Z-abc123"
    qd.mkdir(parents=True); (qd / "x.jpg").write_bytes(b"dup")
    capsys.readouterr()                          # drain the prior phases' SEALED output first
    assert _main(monkeypatch, ws, "prune-quarantine") == 0
    assert "SEALED" not in capsys.readouterr().err   # prune itself never hit the seal guard


@pytest.mark.spec("prep-quarantine-no-auto-delete-1")
def test_prep_plan_never_auto_deletes_quarantine(tmp_path, monkeypatch, capsys):
    """Quarantine is recoverable and is NEVER auto-purged: an ordinary prep `plan` leaves a populated
    quarantine completely intact (only the explicit `prune-quarantine` command may remove it)."""
    ws = _ws(tmp_path)
    qd = ws / ".photos-ingest-quarantine" / "20260101T000000Z-abc123"
    qd.mkdir(parents=True)
    (qd / "dup.jpg").write_bytes(b"recoverable")
    assert _main(monkeypatch, ws, "plan") == 0
    assert qd.exists() and (qd / "dup.jpg").read_bytes() == b"recoverable"   # untouched by plan


@pytest.mark.spec("prep-prune-no-managed-1")
def test_prune_quarantine_preserves_managed_folders(tmp_path, monkeypatch, capsys):
    """prune-quarantine removes only quarantine contents — the managed 0-6 tree (incl. 6-photos-by-dest)
    is never touched by a prune run."""
    ws = _ws(tmp_path)
    (ws / "6-photos-by-dest" / "Trip").mkdir(parents=True)
    (ws / "6-photos-by-dest" / "Trip" / "keep.jpg").write_bytes(b"keep")
    qd = ws / ".photos-ingest-quarantine" / "20260101T000000Z-abc123"
    qd.mkdir(parents=True)
    (qd / "dup.jpg").write_bytes(b"dup")
    assert _main(monkeypatch, ws, "prune-quarantine",
                 "--plan-id", "20260101T000000Z-abc123", "--yes") == 0
    assert not qd.exists()                                       # quarantine pruned
    for d in ("0-sources", "1-strays", "2-missing-metadata", "3-redundant-jpgs",
              "4-videos-by-date", "5-photos-by-date", "6-photos-by-dest"):
        assert (ws / d).is_dir(), d                              # managed folders survive
    assert (ws / "6-photos-by-dest" / "Trip" / "keep.jpg").read_bytes() == b"keep"


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


@pytest.mark.spec("prep-dryrun-mutates-nothing-1")
def test_dry_run_mutates_nothing_on_disk(tmp_path, monkeypatch, capsys):
    """Dry-run is validation, not simulation, and is strictly read-only: it loads the saved plan,
    validates it against an in-memory DB, and prints a summary. Snapshot the whole control dir + a
    seeded quarantine, run dry-run, assert every on-disk byte is identical (cache, plan, quarantine)."""
    ws = _ws(tmp_path)
    qd = ws / ".photos-ingest-quarantine" / "20260101T000000Z-abc123"
    qd.mkdir(parents=True); (qd / "d.jpg").write_bytes(b"recoverable")
    assert _main(monkeypatch, ws, "plan") == 0                  # writes photos-10 + cache

    def snap(root):
        return {os.path.relpath(os.path.join(r, f), root): open(os.path.join(r, f), "rb").read()
                for r, _dn, fns in os.walk(root) for f in fns if not f.endswith(".lock")}

    before = snap(str(ws / ".photos-ingest")) | snap(str(ws / ".photos-ingest-quarantine"))
    assert _main(monkeypatch, ws, "dry-run") == 0
    after = snap(str(ws / ".photos-ingest")) | snap(str(ws / ".photos-ingest-quarantine"))
    assert after == before                                      # dry-run wrote nothing to disk


@pytest.mark.spec("lock-covers-planning-1", "lock-failfast-1")
def test_locked_workspace_failfast_produces_no_artifact(tmp_path, monkeypatch, capsys):
    """Lock contention is fail-fast and pre-mutation: a `plan` that can't take the workspace lock
    produces NO plan artifact and NO journal — the run never got past lock acquisition."""
    ws = _ws(tmp_path)
    lock = ws / ".photos-ingest" / "photos-00-workspace.lock"
    fd = os.open(str(lock), os.O_RDWR | os.O_CREAT, 0o644)
    fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
    try:
        assert _main(monkeypatch, ws, "plan") == 1
    finally:
        fcntl.flock(fd, fcntl.LOCK_UN); os.close(fd)
    assert not os.path.exists(utils.prep_plan_path(str(ws)))    # no plan written
    assert not (ws / ".photos-ingest" / "journal.json").exists()  # no journal written


@pytest.mark.spec("prep-execute-no-plan-stops-1")
def test_execute_without_saved_plan_exits_nonzero(tmp_path, monkeypatch, capsys):
    code = _main(monkeypatch, _ws(tmp_path), "execute")       # no plan generated yet
    assert code != 0
    assert "run `plan` first" in capsys.readouterr().err


@pytest.mark.spec("prep-config-sanity-validated-1")
def test_invalid_config_rejected_at_load(tmp_path, monkeypatch, capsys):
    bad = {k: v for k, v in utils.CONFIG.items() if k != "jobs"}
    bad = dict(bad); bad["zfs"] = {"enabled": False}
    bad["gpx_interpolation_max_distance_meters"] = -1
    code = _main(monkeypatch, _ws(tmp_path, config=bad), "plan")
    assert code != 0 and "config:" in capsys.readouterr().err


def test_bad_jobs_arg_rejected(tmp_path, monkeypatch):
    assert _main(monkeypatch, _ws(tmp_path), "-j", "0", "plan") != 0
