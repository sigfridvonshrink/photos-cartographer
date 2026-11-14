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
        cfg = dict(cfg); cfg["zfs"] = dict(cfg["zfs"], enabled=False)   # never shell out to `zfs snapshot`
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

@pytest.mark.spec("RUL-plan_at_fixed_place", "RUL-lock_through_the_run",
                  test="TST-cli-plan_saves_canonical_and_locks")
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


@pytest.mark.parametrize("command", ["plan", "dry-run", "execute"])
@pytest.mark.parametrize("defect", ["misplaced", "link", "missing"])
@pytest.mark.spec("RUL-shape_checked_first", "INV-undisturbed_shape",
                  test="TST-cli-prep_stops_on_a_disturbed_shape_before_it_scans")
def test_prep_stops_on_a_disturbed_shape_before_it_scans(tmp_path, monkeypatch, capsys, command, defect):
    """An initialized workspace whose top level was disturbed: every prep command stops at once, naming what is
    wrong, having read no file, written no plan and no memo — even where there would otherwise be nothing to do."""
    ws = _ws(tmp_path)
    (ws / "0-sources" / "note.txt").write_text("work to do")
    if command != "plan":
        assert _main(monkeypatch, ws, "plan") == 0            # a plan a dry run or an execute would take up
    if defect == "misplaced":
        (ws / "test-ingest").mkdir()
    elif defect == "link":
        os.symlink(str(tmp_path), str(ws / "elsewhere"))
    else:
        os.rmdir(ws / "4-videos-by-date")
    read = []
    monkeypatch.setattr(prep.WorkspacePrepWorkflow, "_scan_inventory", lambda self, *a, **k: read.append("scan"))
    capsys.readouterr()

    def state():
        return sorted((str(p.relative_to(ws)), p.read_bytes() if p.is_file() and not p.is_symlink() else None)
                      for p in ws.rglob("*") if not p.name.endswith(".lock"))
    before = state()
    code = _main(monkeypatch, ws, command)
    out = capsys.readouterr()
    named = {"misplaced": "Misplaced entry at workspace root", "link": "Forbidden symlink detected: elsewhere",
             "missing": "missing managed folder(s): 4-videos-by-date"}[defect]
    assert code == 2 and named in out.err, out.err
    assert read == [] and state() == before


def test_plan_dryrun_execute_roundtrip(tmp_path, monkeypatch, capsys):
    ws = _ws(tmp_path)
    (ws / "0-sources" / "note.txt").write_text("stray")       # real work so it isn't a nothing-to-do
    assert _main(monkeypatch, ws, "plan") == 0                # writes canonical plan
    assert os.path.exists(utils.prep_plan_path(str(ws)))
    assert "Plan saved to" in capsys.readouterr().out
    assert _main(monkeypatch, ws, "dry-run") == 0             # reads it, no flag needed
    assert _main(monkeypatch, ws, "execute") == 0             # reads it, no flag needed


@pytest.mark.spec("RUL-prep_dry_run_changes_nothing", test="TST-cli-dry_run_summarizes_not_dumps")
def test_dry_run_summarizes_not_dumps(tmp_path, monkeypatch, capsys):
    ws = _ws(tmp_path)
    (ws / "0-sources" / "note.txt").write_text("stray")       # a real plan to summarize (not nothing-to-do)
    assert _main(monkeypatch, ws, "plan") == 0
    capsys.readouterr()
    assert _main(monkeypatch, ws, "dry-run") == 0
    out = capsys.readouterr().out
    assert "Dry-run: validated plan" in out
    assert "Full plan:" in out                        # points to the saved artifact for detail
    import pytest as _pt
    with _pt.raises(json.JSONDecodeError):            # a summary, not the full plan JSON
        json.loads(out)


def _validations(monkeypatch, events):
    """Record in `events` each validation of a plan against its dependencies, by the plan's id."""
    real = prep.PlanValidator.validate_plan_preflight

    def validate(plan, current_workspace):
        events.append(("validate", plan.plan_id))
        return real(plan, current_workspace)
    monkeypatch.setattr(prep.PlanValidator, "validate_plan_preflight", staticmethod(validate))


@pytest.mark.spec("RUL-dry_run_validates_saved_plan", test="TST-cli-prep_dry_run_validates_the_saved_plan")
def test_prep_dry_run_validates_the_saved_plan(tmp_path, monkeypatch, capsys):
    """Prep's dry run validates the plan saved for execute, as saved: it passes the saved plan and names it, refuses it
    once a dependency of it has changed since planning, and refuses it once the saved plan itself would be refused —
    as execute refuses it."""
    ws = _ws(tmp_path)
    (ws / "0-sources" / "note.txt").write_text("stray")       # a real plan (not nothing-to-do)
    assert _main(monkeypatch, ws, "plan") == 0
    pp = utils.prep_plan_path(str(ws))
    saved = open(pp).read()
    pid = json.loads(saved)["plan_id"]
    events = []
    _validations(monkeypatch, events)
    capsys.readouterr()
    assert _main(monkeypatch, ws, "dry-run") == 0
    assert events == [("validate", pid)] and pid in capsys.readouterr().out

    cfg_p = ws / ".photos-ingest" / "photos-00-config.json"
    cfg = cfg_p.read_text()
    cfg_p.write_text(cfg + "\n")                               # a dependency changed after planning
    assert _main(monkeypatch, ws, "dry-run") == 1
    assert "workspace config changed" in capsys.readouterr().err
    cfg_p.write_text(cfg)

    doctored = json.loads(saved)
    doctored["blockers"] = ["a blocker written into the saved plan"]
    open(pp, "w").write(json.dumps(doctored))                  # the saved plan itself no longer passes
    assert _main(monkeypatch, ws, "dry-run") == 1
    assert "a blocker written into the saved plan" in capsys.readouterr().err
    assert _main(monkeypatch, ws, "execute") == 1              # the plan execute would refuse too
    assert (ws / "0-sources" / "note.txt").exists()
    open(pp, "w").write(saved)
    assert _main(monkeypatch, ws, "dry-run") == 0


def _fake_snapshots(monkeypatch, ws, probe):
    """Snapshots on in the workspace's configuration (before `plan`, which depends on it) and `zfs snapshot` faked:
    each snapshot asked for records `probe()` in the returned list."""
    cfg_p = ws / ".photos-ingest" / "photos-00-config.json"
    cfg = json.loads(cfg_p.read_text())
    cfg["zfs"] = dict(cfg["zfs"], enabled=True)
    cfg_p.write_text(json.dumps(cfg))
    taken = []

    def take(ws_root, plan_id, label, **_k):
        taken.append(probe())
        return {"required": False, "ok": True, "snapshot_name": f"pool/ws@{label}-{plan_id}",
                "command": "zfs snapshot", "exit_code": 0, "stdout": "", "stderr": ""}
    monkeypatch.setattr(utils, "take_zfs_snapshot", take)
    return taken


@pytest.mark.spec("RUL-snapshot_after_validation", test="TST-cli-prep_takes_no_snapshot_before_the_plan_is_validated")
def test_prep_takes_no_snapshot_before_the_plan_is_validated(tmp_path, monkeypatch, capsys):
    """Prep's snapshot follows the plan's validation against its dependencies: a plan whose configuration changed
    after planning is refused with no snapshot taken at all, and a plan that passes is validated first."""
    ws = _ws(tmp_path)
    (ws / "0-sources" / "note.txt").write_text("stray")
    events = []
    _fake_snapshots(monkeypatch, ws, lambda: events.append("snapshot"))
    assert _main(monkeypatch, ws, "plan") == 0
    pid = json.load(open(utils.prep_plan_path(str(ws))))["plan_id"]
    _validations(monkeypatch, events)

    cfg_p = ws / ".photos-ingest" / "photos-00-config.json"
    cfg = cfg_p.read_text()
    cfg_p.write_text(cfg + "\n")                               # a dependency changed after planning
    assert _main(monkeypatch, ws, "execute") == 1
    assert events == [("validate", pid)]                       # refused, and no snapshot taken
    assert (ws / "0-sources" / "note.txt").exists()

    cfg_p.write_text(cfg)
    events.clear()
    assert _main(monkeypatch, ws, "execute") == 0
    assert events == [("validate", pid), "snapshot"], events
    assert not (ws / "0-sources" / "note.txt").exists()        # and the plan was carried out


@pytest.mark.spec("RUL-snapshot_under_lock", test="TST-cli-prep_snapshot_is_taken_while_the_lock_is_held")
def test_prep_snapshot_is_taken_while_the_lock_is_held(tmp_path, monkeypatch, capsys):
    """Prep's snapshot is taken while the workspace lock is held: probed, from a file descriptor of its own, at the
    moment the snapshot is asked for."""
    ws = _ws(tmp_path)
    (ws / "0-sources" / "note.txt").write_text("stray")
    held = _fake_snapshots(monkeypatch, ws,
                           lambda: utils.WorkspaceLock(str(ws), create=False).held_owner() is not None)
    assert _main(monkeypatch, ws, "plan") == 0
    assert _main(monkeypatch, ws, "execute") == 0
    assert held == [True], held
    assert utils.WorkspaceLock(str(ws), create=False).held_owner() is None   # the probe tells held from free


@pytest.mark.spec("RUL-replanning_keeps_the_prior", "RUL-set_aside_plan_reported",
                  test="TST-cli-replan_backs_up_previous_plan")
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

@pytest.mark.spec("RUL-sealed_refuses")
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


@pytest.mark.spec("RUL-sealed_new_dump_left", test="TST-cli-sealed_new_dump_is_left_exactly_in_place")
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


@pytest.mark.spec("RUL-sealed_prune_allowed", test="TST-cli-prune_quarantine_is_the_sole_op_allowed_on_a_sealed_workspace")
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


@pytest.mark.spec("RUL-sealed_refuses")
def test_seal_refuses_all_three_phases_except_prune_quarantine(tmp_path, monkeypatch, capsys):
    """RUL-sealed_refuses / RUL-sealed_prune_allowed: once a workspace is SEALED, every media-mutating phase refuses
    on it — prep plan, geotag plan, AND merge plan all hard-stop with exit 2 — with the SOLE exception of prep
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


@pytest.mark.spec("RUL-quarantine_never_auto_deleted", test="TST-cli-prep_plan_never_auto_deletes_quarantine")
def test_prep_plan_never_auto_deletes_quarantine(tmp_path, monkeypatch, capsys):
    """Quarantine is recoverable and is NEVER auto-purged: an ordinary prep `plan` leaves a populated
    quarantine completely intact (only the explicit `prune-quarantine` command may remove it)."""
    ws = _ws(tmp_path)
    qd = ws / ".photos-ingest-quarantine" / "20260101T000000Z-abc123"
    qd.mkdir(parents=True)
    (qd / "dup.jpg").write_bytes(b"recoverable")
    assert _main(monkeypatch, ws, "plan") == 0
    assert qd.exists() and (qd / "dup.jpg").read_bytes() == b"recoverable"   # untouched by plan


@pytest.mark.spec("RUL-prune_only_quarantine", test="TST-cli-prune_quarantine_preserves_managed_folders")
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


@pytest.mark.spec("RUL-prep_dry_run_changes_nothing", test="TST-cli-dry_run_mutates_nothing_on_disk")
def test_dry_run_mutates_nothing_on_disk(tmp_path, monkeypatch, capsys):
    """Dry-run is validation, not simulation, and is strictly read-only: it loads the saved plan,
    validates it against an in-memory DB, and prints a summary. Snapshot the whole control dir + a
    seeded quarantine, run dry-run, assert every on-disk byte is identical (cache, plan, quarantine)."""
    ws = _ws(tmp_path)
    (ws / "0-sources" / "note.txt").write_text("stray")        # real plan so dry-run actually summarizes
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


@pytest.mark.spec("RUL-lock_before_reading", "RUL-lock_fail_fast",
                  test="TST-cli-locked_workspace_failfast_produces_no_artifact")
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


_EVERY_COMMAND = [("prep", "plan"), ("prep", "dry-run"), ("prep", "execute"),
                  ("prep", "prune-quarantine", "--plan-id", "20260101T000000Z-abc123", "--yes"),
                  ("geotag", "plan"), ("geotag", "execute"), ("geotag", "finalize"),
                  ("merge", "init-library"), ("merge", "init-library", "<library>"),
                  ("merge", "plan"), ("merge", "dry-run"), ("merge", "execute"),
                  ("edit", "save")]


@pytest.mark.parametrize("command", _EVERY_COMMAND, ids=[" ".join(c[:2]) + (" <path>" if "<library>" in c else "")
                                                         for c in _EVERY_COMMAND])
@pytest.mark.spec("RUL-every_command_locks", "RUL-one_workspace_lock",
                  test="TST-cli-every_command_waits_for_the_one_workspace_lock")
def test_every_command_waits_for_the_one_workspace_lock(tmp_path, monkeypatch, capsys, command):
    """Every command of every phase, and the editor's save, takes the workspace's lock — the one lock, the same for
    all: while another run holds it, each command, run as the command line runs it, refuses with exit 1 and leaves
    the workspace and the library exactly as they were (the quarantine a prune would delete, the library
    init-library would bless, the decisions a save would rewrite)."""
    import cartographer.cli as cli
    from cartographer.editor import server as serve
    lib = tmp_path / "lib"; lib.mkdir()
    cfg = {k: v for k, v in utils.CONFIG.items() if k != "jobs"}
    cfg["zfs"] = {"enabled": False}
    cfg["merge"] = dict(cfg.get("merge") or {}); cfg["merge"]["library_root"] = str(lib)
    ws = _ws(tmp_path, config=cfg)
    (ws / "0-sources" / "a.jpg").write_bytes(b"a dump to plan")
    qd = ws / ".photos-ingest-quarantine" / "20260101T000000Z-abc123"
    qd.mkdir(parents=True); (qd / "dup.jpg").write_bytes(b"recoverable")
    (ws / ".photos-ingest" / "photos-21-time-decisions.json").write_text('{"destinations": {}}')

    def state():
        return sorted((str(p.relative_to(tmp_path)), p.read_bytes() if p.is_file() else None, p.stat().st_mtime_ns)
                      for p in tmp_path.rglob("*"))

    held = utils.WorkspaceLock(str(ws), create=False)              # another run, holding the workspace's lock
    assert held.acquire() is True
    before = state()
    monkeypatch.chdir(str(ws))
    try:
        if command[0] == "edit":
            res = serve._save(str(ws), {"time": [{"dest": "6-photos-by-dest/T", "kind": "timezone",
                                                  "user_decision": {"manual_iana_timezone": "Asia/Tokyo"}}]})
            assert res["ok"] is False and "run is in progress" in res["error"], res
        else:
            argv = [str(lib) if a == "<library>" else a for a in command]
            with pytest.raises(SystemExit) as ei:
                cli.main(argv)
            assert ei.value.code == 1, (command, capsys.readouterr())
            assert "locked" in capsys.readouterr().err.lower()
        assert state() == before, command                          # nothing read into a record, nothing changed
        assert not utils.is_library(str(lib))
    finally:
        held.release()


_SHAPE_DEFECTS = {"misplaced": "Misplaced entry", "link": "symlink", "missing": "missing managed folder"}


def _disturb(ws, tmp_path, defect):
    if defect == "misplaced":
        (ws / "loose.jpg").write_bytes(b"dropped at the top level")
    elif defect == "link":
        os.symlink(str(tmp_path), str(ws / "elsewhere"))
    else:
        os.rmdir(ws / "4-videos-by-date")


@pytest.mark.parametrize("defect", sorted(_SHAPE_DEFECTS))
@pytest.mark.parametrize("command", [("prep", "plan"), ("prep", "dry-run"), ("prep", "execute"),
                                     ("geotag", "plan"), ("geotag", "execute"), ("geotag", "finalize"),
                                     ("merge", "plan"), ("merge", "dry-run"), ("merge", "execute")],
                         ids=lambda c: " ".join(c))
@pytest.mark.spec("RUL-shape_checked_first", test="TST-cli-the_lock_and_the_seal_come_before_the_shape")
def test_the_lock_and_the_seal_come_before_the_shape(tmp_path, monkeypatch, capsys, command, defect):
    """Each phase takes the lock, then checks the seal, and only then the workspace's shape: on a sealed workspace
    whose shape is disturbed, a run that cannot take the lock stops on the lock (exit 1) and one that can stops on
    the seal (exit 2), saying the workspace is sealed and nothing of its shape — and neither changes anything but the
    lock's owner record. The shape check's own place, before everything else, is asserted per phase
    (TST-geotag_preflight-the_shape_is_checked_before_anything_else, TST-merge_preflight-the_shape_is_checked_before_anything_else)."""
    import cartographer.cli as cli
    lib = tmp_path / "lib"; lib.mkdir()
    utils.write_library_marker(str(lib))
    cfg = {k: v for k, v in utils.CONFIG.items() if k != "jobs"}
    cfg["zfs"] = {"enabled": False}
    cfg["merge"] = dict(cfg.get("merge") or {}); cfg["merge"]["library_root"] = str(lib)
    ws = _ws(tmp_path, config=cfg)
    (ws / ".photos-ingest" / "photos-00-sealed.json").write_text('{"sealed": true}')
    _disturb(ws, tmp_path, defect)
    monkeypatch.chdir(str(ws))

    def state():
        return sorted((str(p.relative_to(tmp_path)), p.read_bytes() if p.is_file() and not p.is_symlink() else None,
                       p.lstat().st_mtime_ns)
                      for p in tmp_path.rglob("*") if not p.name.endswith(".lock"))

    def run():
        with pytest.raises(SystemExit) as ei:
            cli.main(list(command))
        out = capsys.readouterr()
        return ei.value.code, out.out + out.err

    held = utils.WorkspaceLock(str(ws), create=False)
    assert held.acquire() is True
    before = state()
    try:
        code, said = run()
    finally:
        held.release()
    assert code == 1 and "locked" in said.lower() and "SEALED" not in said, said           # the lock first
    assert state() == before
    code, said = run()
    assert code == 2 and "SEALED" in said, said                                            # then the seal
    assert _SHAPE_DEFECTS[defect].lower() not in said.lower(), said                       # ...before the shape
    assert state() == before


@pytest.mark.spec("RUL-no_plan_no_run", "RUL-no_plan_says_plan_first",
                  test="TST-cli-execute_without_saved_plan_exits_nonzero")
def test_execute_without_saved_plan_exits_nonzero(tmp_path, monkeypatch, capsys):
    code = _main(monkeypatch, _ws(tmp_path), "execute")       # no plan generated yet
    assert code != 0
    assert "run `plan` first" in capsys.readouterr().err


@pytest.mark.spec("RUL-config_validated_before_use")
def test_invalid_config_rejected_at_load(tmp_path, monkeypatch, capsys):
    bad = {k: v for k, v in utils.CONFIG.items() if k != "jobs"}
    bad = dict(bad); bad["zfs"] = dict(bad["zfs"], enabled=False)
    bad["gpx_interpolation_max_distance_meters"] = -1
    code = _main(monkeypatch, _ws(tmp_path, config=bad), "plan")
    assert code != 0 and "config:" in capsys.readouterr().err


def test_bad_jobs_arg_rejected(tmp_path, monkeypatch):
    assert _main(monkeypatch, _ws(tmp_path), "-j", "0", "plan") != 0
