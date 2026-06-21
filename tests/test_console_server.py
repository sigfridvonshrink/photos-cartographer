"""Unit tests for the console server helpers (assets, state, plan summary, execute gate)."""

import json
import os

from cartographer import photos_utils as U
from cartographer.console import server


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
                 ("merge", "plan"), ("merge", "dry-run"), ("merge", "execute")):
        assert pair in server._RUNNABLE
    assert ("geotag", "dry-run") not in server._RUNNABLE     # geotag has no dry-run subcommand
    assert ("merge", "init-library") not in server._RUNNABLE  # needs a path arg — not wired yet


def test_make_target_builds_a_callable_without_running():
    assert callable(server._make_target("prep", "execute"))


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
    ws = str(tmp_path)
    a = server._state(ws)["actions"]
    assert a["prep/plan"]["ok"] is True
    assert a["prep/dry-run"]["ok"] is False and "prep plan" in a["prep/dry-run"]["reason"]
    assert a["geotag/plan"]["ok"] is False        # prep not executed (no handoff)
    assert a["merge/plan"]["ok"] is False          # geotag not finalized
    _write_plan(ws, operations=["move"])           # clean prep plan
    a2 = server._state(ws)["actions"]
    assert a2["prep/dry-run"]["ok"] is True and a2["prep/execute"]["ok"] is True


def test_geotag_plan_opens_once_prep_handoff_exists(tmp_path):
    ws = str(tmp_path)
    assert server._state(ws)["actions"]["geotag/plan"]["ok"] is False
    hp = U.handoff_path(ws)
    os.makedirs(os.path.dirname(hp), exist_ok=True)
    open(hp, "w").write("{}")
    assert server._state(ws)["actions"]["geotag/plan"]["ok"] is True


def test_actions_all_blocked_when_sealed(tmp_path, monkeypatch):
    monkeypatch.setattr(server.U, "is_sealed", lambda ws: True)
    a = server._state(str(tmp_path))["actions"]
    assert all(not v["ok"] for v in a.values())
    assert "sealed" in a["prep/plan"]["reason"]
