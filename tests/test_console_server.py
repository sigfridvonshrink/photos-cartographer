"""Unit tests for the console server helpers (assets, state, plan summary, execute gate)."""

import json
import os

from cartographer import photos_utils as U
from cartographer.console import server


def _init_ws(workspace):
    """Mark a workspace initialized by writing the guard sentinel — most console affordances are only
    offered once the workspace exists (an uninitialized cwd offers prep/plan only)."""
    g = U.guard_path(workspace)
    os.makedirs(os.path.dirname(g), exist_ok=True)
    with open(g, "w") as f:
        json.dump({"initialized": True}, f)
    return workspace


def _write_plan(workspace, *, plan_id="prep-1", operations=(), blockers=(), no_op=0, warnings=(),
                depends_on=None):
    pp = U.prep_plan_path(workspace)
    os.makedirs(os.path.dirname(pp), exist_ok=True)
    with open(pp, "w") as f:
        json.dump({"plan_id": plan_id,
                   "operations": [{"type": t} for t in operations],
                   "blockers": list(blockers),
                   "warnings": list(warnings),
                   "depends_on": depends_on or {},
                   "summary": {"no_op_files": no_op}}, f)
    return pp


# --- assets ---------------------------------------------------------------

def test_asset_serves_console_spa_and_shared_tokens():
    assert server._asset("/")[:9] == b"<!doctype"
    assert b"--accent" in server._asset("tokens.css")        # shared from the editor package
    assert server._asset("app.js") is not None


def test_asset_rejects_path_traversal_and_missing():
    assert server._asset("../jobs.py") is None
    assert server._asset("vendor/../../secret") is None
    assert server._asset("nope.css") is None


# --- runnable set + target ------------------------------------------------

def test_runnable_set_covers_all_phases_execute_via_gate():
    for pair in (("prep", "plan"), ("prep", "dry-run"), ("prep", "execute"),
                 ("geotag", "plan"), ("geotag", "execute"),
                 ("merge", "init-library"), ("merge", "plan"), ("merge", "dry-run"), ("merge", "execute")):
        assert pair in server._RUNNABLE
    assert ("geotag", "dry-run") not in server._RUNNABLE     # geotag has no dry-run subcommand


def test_make_target_builds_a_callable_without_running():
    assert callable(server._make_target("prep", "execute"))
    assert callable(server._make_target("merge", "init-library", ["/srv/library"]))   # optional path arg


def test_jobs_argv_validates_and_clamps():
    assert server._jobs_argv(8) == ["-j", "8"]
    assert server._jobs_argv("4") == ["-j", "4"]      # numeric string accepted
    assert server._jobs_argv(1) == ["-j", "1"]
    assert server._jobs_argv(None) == []              # unset -> phase default
    assert server._jobs_argv(0) == []                 # below range -> ignored
    assert server._jobs_argv(server._JOBS_MAX + 1) == []
    assert server._jobs_argv("nope") == []


def test_default_jobs_is_at_least_one():
    assert server._default_jobs() >= 1


def test_state_exposes_default_jobs(tmp_path):
    assert server._state(str(tmp_path))["default_jobs"] == server._default_jobs()


def test_make_target_accepts_jobs_before_subcommand_for_all_phases():
    # -j lives on each phase's parent parser, so it must precede the subcommand. _make_target parses
    # eagerly, so a wrong placement would SystemExit here rather than return a callable.
    assert callable(server._make_target("prep", "plan", None, ["-j", "8"]))
    assert callable(server._make_target("geotag", "execute", None, ["-j", "2"]))
    assert callable(server._make_target("merge", "execute", None, ["-j", "3"]))
    # composes with a subcommand positional (merge init-library path)
    assert callable(server._make_target("merge", "init-library", ["/srv/library"], ["-j", "5"]))


# --- full CLI parity: geotag finalize + prep prune-quarantine (v2.5) -------

def test_runnable_set_has_full_cli_parity():
    # Every phase command is now driveable from the console — the two that were CLI-only are present.
    assert ("geotag", "finalize") in server._RUNNABLE
    assert ("prep", "prune-quarantine") in server._RUNNABLE
    assert server._RUNNABLE == {
        ("prep", "plan"), ("prep", "dry-run"), ("prep", "execute"), ("prep", "prune-quarantine"),
        ("geotag", "plan"), ("geotag", "execute"), ("geotag", "finalize"),
        ("merge", "init-library"), ("merge", "plan"), ("merge", "dry-run"), ("merge", "execute")}


def test_make_target_builds_finalize_and_prune_callables():
    assert callable(server._make_target("geotag", "finalize"))
    assert callable(server._make_target("prep", "prune-quarantine",
                                        ["--plan-id", "20260101T000000Z-abc", "--yes"]))


def test_prune_extra_builds_argv_dry_run_vs_delete():
    assert server._prune_extra({}) == []                                    # nothing selected = dry-run
    assert server._prune_extra({"prune": {"plan_ids": ["p1", "p2"]}}) == \
        ["--plan-id", "p1", "--plan-id", "p2"]                              # dry-run, no --yes
    assert server._prune_extra({"prune": {"all": True, "delete": True}}) == ["--all", "--yes"]
    assert server._prune_extra({"prune": {"older_than_days": 30, "delete": True}}) == \
        ["--older-than-days", "30", "--yes"]


def test_prune_guard_allows_dry_run_but_gates_destructive_delete():
    assert server._prune_guard({"prune": {"plan_ids": ["p1"]}}) is None     # dry-run: always allowed
    # a delete needs confirmation AND a selector — never a one-click unscoped purge
    assert "confirmation" in server._prune_guard({"prune": {"all": True, "delete": True}})
    assert "select" in server._prune_guard({"confirm": True, "prune": {"delete": True}})
    assert server._prune_guard({"confirm": True, "prune": {"all": True, "delete": True}}) is None
    assert server._prune_guard({"confirm": True, "prune": {"plan_ids": ["p1"], "delete": True}}) is None


def test_only_prep_plan_enabled_when_uninitialized(tmp_path):
    # Fresh cwd, no guard: the console opens but offers prep/plan only — it is prep's own entry point,
    # and the rest stays disabled (with a guiding reason) until the workspace is initialized.
    a = server._state(str(tmp_path))["actions"]
    assert server._state(str(tmp_path))["initialized"] is False
    assert a["prep/plan"]["ok"] is True and a["prep/plan"]["reason"] == ""
    for cmd in ("prep/execute", "geotag/plan", "merge/init-library", "prep/prune-quarantine"):
        assert a[cmd]["ok"] is False
    assert "initialize" in a["geotag/plan"]["reason"]


def test_prune_quarantine_is_the_only_action_enabled_when_sealed(tmp_path, monkeypatch):
    _init_ws(str(tmp_path))
    monkeypatch.setattr(server.U, "is_sealed", lambda ws: True)
    a = server._state(str(tmp_path))["actions"]
    assert a["prep/prune-quarantine"]["ok"] is True and a["prep/prune-quarantine"]["reason"] == ""
    assert a["prep/plan"]["ok"] is False and a["geotag/finalize"]["ok"] is False


def test_finalize_action_enabled_only_after_successful_execute_and_before_finalize(tmp_path):
    from cartographer.photos_2_geotag import execution_summary_path, complete_log_path
    ctl = tmp_path / ".photos-ingest"; ctl.mkdir()
    _init_ws(str(tmp_path))
    # before geotag execute: finalize is not offered
    assert server._state(str(tmp_path))["actions"]["geotag/finalize"]["ok"] is False
    # geotag executed successfully -> finalize becomes available
    with open(execution_summary_path(str(tmp_path)), "w") as f:
        json.dump({"status": "success", "plan_id": "cal-1"}, f)
    assert server._state(str(tmp_path))["actions"]["geotag/finalize"]["ok"] is True
    # once finalized (complete-log written) -> no longer offered
    with open(complete_log_path(str(tmp_path)), "w") as f:
        json.dump({"photos": {}}, f)
    fin = server._state(str(tmp_path))["actions"]["geotag/finalize"]
    assert fin["ok"] is False and "already" in fin["reason"]


def test_init_library_action_runnable_anytime(tmp_path):
    # init-library is a one-time setup step — offered even with no prep/geotag/merge plan yet
    _init_ws(str(tmp_path))
    a = server._state(str(tmp_path))["actions"]
    assert a["merge/init-library"]["ok"] is True


# --- plan summary ---------------------------------------------------------

def test_prep_plan_summary_absent_then_lines(tmp_path):
    assert server._plan_summary(str(tmp_path), "prep") == {"exists": False}
    _write_plan(str(tmp_path), operations=["move", "move", "mkdir"], no_op=7, warnings=["w"])
    s = server._plan_summary(str(tmp_path), "prep")
    assert s["exists"] and s["plan_id"] == "prep-1" and s["operations"] == 3 and s["blockers"] == []
    body = "\n".join(s["lines"])
    assert "move 2" in body and "mkdir 1" in body and "no-op / already-correct 7" in body


def test_geotag_and_merge_plan_summaries(tmp_path):
    from cartographer.photos_2_geotag import executable_plan_path
    from cartographer.photos_3_merge import merge_plan_path
    import os as _os
    g = executable_plan_path(str(tmp_path)); _os.makedirs(_os.path.dirname(g), exist_ok=True)
    json.dump({"plan_id": "g1", "status": "ready", "blockers": [],
               "destinations": {"A": {"operations": [1, 2]}, "B": {"operations": [3]}}}, open(g, "w"))
    gs = server._plan_summary(str(tmp_path), "geotag")
    assert gs["exists"] and gs["plan_id"] == "g1" and gs["operations"] == 3   # 2 + 1 ops

    m = merge_plan_path(str(tmp_path))
    json.dump({"plan_id": "m1", "blockers": [],
               "totals": {"placed_new": 5, "already_present": 2, "renamed_for_library": 1, "blocked": 0},
               "destinations": {}}, open(m, "w"))
    ms = server._plan_summary(str(tmp_path), "merge")
    assert ms["exists"] and ms["plan_id"] == "m1" and ms["operations"] == 5   # placed_new


# --- execute gate (generic, per phase) ------------------------------------

def test_execute_guard_requires_confirmation(tmp_path):
    _write_plan(str(tmp_path), operations=["move"])
    assert server._execute_guard(str(tmp_path), "prep", {}) == "execute requires explicit confirmation"


def test_execute_guard_allows_clean_confirmed_plan(tmp_path):
    _write_plan(str(tmp_path), plan_id="p9", operations=["move"])
    assert server._execute_guard(str(tmp_path), "prep", {"confirm": True}) is None
    assert server._execute_guard(str(tmp_path), "prep", {"confirm": True, "plan_id": "p9"}) is None


def test_execute_guard_refuses_blockers_missing_and_changed_plan(tmp_path):
    assert "no saved plan" in server._execute_guard(str(tmp_path), "prep", {"confirm": True})
    _write_plan(str(tmp_path), plan_id="p9", operations=["move"], blockers=["nonconforming"])
    assert "blocker" in server._execute_guard(str(tmp_path), "prep", {"confirm": True})
    _write_plan(str(tmp_path), plan_id="p10", operations=["move"])
    assert "changed" in server._execute_guard(str(tmp_path), "prep", {"confirm": True, "plan_id": "p9"})


# --- state ----------------------------------------------------------------

def test_state_executable_flag_tracks_plan(tmp_path):
    st = server._state(str(tmp_path))
    assert st["phases"]["prep"]["executable"] is False      # no plan
    _write_plan(str(tmp_path), operations=["move"], blockers=["x"])
    assert server._state(str(tmp_path))["phases"]["prep"]["executable"] is False   # has blocker
    _write_plan(str(tmp_path), operations=["move"])
    s2 = server._state(str(tmp_path))
    assert s2["phases"]["prep"]["executable"] is True and s2["phases"]["prep"]["blockers"] == 0


def test_state_reports_all_three_phases(tmp_path):
    st = server._state(str(tmp_path))
    for ph in ("prep", "geotag", "merge"):
        assert st["phases"][ph]["plan_exists"] is False and st["phases"][ph]["executable"] is False
    for r in ("geotag/execute", "merge/execute", "merge/dry-run"):
        assert r in st["runnable"]


def test_stale_lock_file_does_not_wedge_actions(tmp_path):
    # A finished/interrupted CLI run leaves the owner file populated but the flock free. The console
    # must NOT treat that as an in-progress run — Plan (and the rest) must stay enabled.
    _init_ws(str(tmp_path))
    lock = U.WorkspaceLock(str(tmp_path))
    assert lock.acquire() is True
    lock.release()                                   # flock free, owner file still on disk
    st = server._state(str(tmp_path))
    assert st["lock_owner"] is None                  # not reported as locked
    assert st["actions"]["prep/plan"]["ok"] is True  # Plan clickable again


# --- staleness gating (uses the shared plan_dependencies_fresh helper) -----

_STALE_DEP = {"upstream": {"dependency_type": "json_artifact", "artifact_name": "u.json",
                          "artifact_path": ".photos-ingest/u.json", "sha256": "deadbeef"}}


def test_stale_plan_flagged_and_execute_refused(tmp_path):
    ws = str(tmp_path)
    _write_plan(ws, operations=["move"], depends_on=_STALE_DEP)   # upstream missing -> stale
    s = server._plan_summary(ws, "prep", server._current_fingerprints(ws))
    assert s["stale"]                                            # flagged stale
    st = server._state(ws)
    assert st["phases"]["prep"]["stale"] > 0
    assert st["phases"]["prep"]["executable"] is False           # stale -> not executable
    assert "stale" in server._execute_guard(ws, "prep", {"confirm": True})   # gate refuses


# --- per-command affordance (actions): pipeline order, sealed, lock --------

def test_actions_enforce_pipeline_order(tmp_path):
    ws = _init_ws(str(tmp_path))
    a = server._state(ws)["actions"]
    assert a["prep/plan"]["ok"] is True
    assert a["prep/dry-run"]["ok"] is False and "prep plan" in a["prep/dry-run"]["reason"]
    assert a["geotag/plan"]["ok"] is False        # prep not executed (no handoff)
    assert a["merge/plan"]["ok"] is False          # geotag not finalized
    _write_plan(ws, operations=["move"])           # clean prep plan
    a2 = server._state(ws)["actions"]
    assert a2["prep/dry-run"]["ok"] is True and a2["prep/execute"]["ok"] is True


def test_geotag_plan_opens_once_prep_handoff_exists(tmp_path):
    ws = _init_ws(str(tmp_path))
    assert server._state(ws)["actions"]["geotag/plan"]["ok"] is False
    hp = U.handoff_path(ws)
    os.makedirs(os.path.dirname(hp), exist_ok=True)
    open(hp, "w").write("{}")
    assert server._state(ws)["actions"]["geotag/plan"]["ok"] is True


def test_actions_all_blocked_when_sealed_except_prune(tmp_path, monkeypatch):
    _init_ws(str(tmp_path))
    monkeypatch.setattr(server.U, "is_sealed", lambda ws: True)
    a = server._state(str(tmp_path))["actions"]
    # prune-quarantine is the SOLE op a sealed workspace permits; everything else is refused.
    assert a["prep/prune-quarantine"]["ok"] is True
    assert all(not v["ok"] for k, v in a.items() if k != "prep/prune-quarantine")
    assert "sealed" in a["prep/plan"]["reason"]


# --- folded-in editor (v2.4) ----------------------------------------------

def test_editor_is_folded_in():
    # editor assets are reachable as package data (the console serves them under /edit/)
    assert server._read_pkg("cartographer.editor", "web", ["index.html"])[:9] == b"<!doctype"
    assert server._read_pkg("cartographer.editor", "web", ["app.js"]) is not None
    # editor API functions are wired for delegation through the console origin
    for fn in ("_load_artifacts", "_save", "_rerun", "_photo_preview"):
        assert callable(getattr(server._editor, fn))
