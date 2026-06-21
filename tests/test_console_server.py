"""Unit tests for the console server helpers (assets, state, plan summary, execute gate)."""

import json
import os

from cartographer import photos_utils as U
from cartographer.console import server


def _write_plan(workspace, *, plan_id="prep-1", operations=(), blockers=(), no_op=0, warnings=()):
    pp = U.prep_plan_path(workspace)
    os.makedirs(os.path.dirname(pp), exist_ok=True)
    with open(pp, "w") as f:
        json.dump({"plan_id": plan_id,
                   "operations": [{"type": t} for t in operations],
                   "blockers": list(blockers),
                   "warnings": list(warnings),
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

def test_runnable_set_includes_execute_but_only_prep():
    assert ("prep", "plan") in server._RUNNABLE
    assert ("prep", "dry-run") in server._RUNNABLE
    assert ("prep", "execute") in server._RUNNABLE          # allowed — but only via the gate
    assert ("merge", "execute") not in server._RUNNABLE


def test_make_target_builds_a_callable_without_running():
    assert callable(server._make_target("prep", "execute"))


# --- plan summary ---------------------------------------------------------

def test_plan_summary_absent_then_counts_ops(tmp_path):
    assert server._plan_summary(str(tmp_path)) == {"exists": False}
    _write_plan(str(tmp_path), operations=["move", "move", "mkdir"], no_op=7, warnings=["w"])
    s = server._plan_summary(str(tmp_path))
    assert s["exists"] and s["plan_id"] == "prep-1" and s["operations"] == 3
    assert s["op_counts"] == {"move": 2, "mkdir": 1}
    assert s["no_op"] == 7 and s["warnings"] == 1 and s["blockers"] == []


# --- execute gate ---------------------------------------------------------

def test_execute_guard_requires_confirmation(tmp_path):
    _write_plan(str(tmp_path), operations=["move"])
    assert server._execute_guard(str(tmp_path), {}) == "execute requires explicit confirmation"


def test_execute_guard_allows_clean_confirmed_plan(tmp_path):
    _write_plan(str(tmp_path), plan_id="p9", operations=["move"])
    assert server._execute_guard(str(tmp_path), {"confirm": True}) is None
    assert server._execute_guard(str(tmp_path), {"confirm": True, "plan_id": "p9"}) is None


def test_execute_guard_refuses_blockers_missing_and_changed_plan(tmp_path):
    # no plan yet
    assert "no saved plan" in server._execute_guard(str(tmp_path), {"confirm": True})
    # plan with a blocker
    _write_plan(str(tmp_path), plan_id="p9", operations=["move"], blockers=["nonconforming"])
    assert "blocker" in server._execute_guard(str(tmp_path), {"confirm": True})
    # clean plan but the reviewed id no longer matches
    _write_plan(str(tmp_path), plan_id="p10", operations=["move"])
    assert "changed" in server._execute_guard(str(tmp_path), {"confirm": True, "plan_id": "p9"})


# --- state ----------------------------------------------------------------

def test_state_executable_flag_tracks_plan(tmp_path):
    st = server._state(str(tmp_path))
    assert st["phases"]["prep"]["executable"] is False      # no plan
    _write_plan(str(tmp_path), operations=["move"], blockers=["x"])
    assert server._state(str(tmp_path))["phases"]["prep"]["executable"] is False   # has blocker
    _write_plan(str(tmp_path), operations=["move"])
    s2 = server._state(str(tmp_path))
    assert s2["phases"]["prep"]["executable"] is True and s2["phases"]["prep"]["blockers"] == 0
    assert "prep/execute" in s2["runnable"]
