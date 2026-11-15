"""Unit tests for the console server helpers (assets, state, plan summary, execute gate)."""

import json
import os

import pytest

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


def test_default_jobs_is_at_least_one_and_below_cpu_count():
    assert server._cpu_count() >= 1
    assert server._default_jobs() >= 1
    assert server._default_jobs() <= server._cpu_count()      # default is cpu-1 (or 1), never above cpu


def test_state_exposes_default_jobs_and_cpu_count(tmp_path):
    st = server._state(str(tmp_path))
    assert st["default_jobs"] == server._default_jobs()
    assert st["cpu_count"] == server._cpu_count()


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


def test_prep_dryrun_execute_unlock_after_plan_even_without_guard(tmp_path):
    # Prep `plan` builds a usable plan but does NOT write the guard sentinel (prep `execute` does). So a
    # freshly-planned-but-not-executed workspace is still "uninitialized" yet must offer prep dry-run /
    # execute off the saved plan — the short-circuit only applies when there is NO plan.
    ws = str(tmp_path)
    assert server._state(ws)["initialized"] is False        # no guard
    _write_plan(ws, operations=["move"])                    # clean prep plan, no blockers/staleness
    a = server._state(ws)["actions"]
    assert a["prep/dry-run"]["ok"] is True
    assert a["prep/execute"]["ok"] is True                  # not the "initialize first" reason anymore
    assert "initialize" not in a["prep/execute"]["reason"]


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


@pytest.mark.spec("RUL-one_configuration", test="TST-console_server-staleness_judged_by_the_workspaces_configuration")
def test_staleness_judged_by_the_workspaces_configuration(tmp_path):
    """A workspace whose configuration differs from the built-in defaults (folders renamed, extensions
    edited, a phone listed), planned on the command line, is fresh to a console that has run no phase —
    its CONFIG still the defaults — and its execute is offered, as the command line would run it.
    Judging reads the workspace's file and leaves the process's CONFIG as it was."""
    ws = _init_ws(str(tmp_path))
    cfg = json.loads(json.dumps(U.DEFAULT_CONFIG))
    cfg["folders"] = {r: f"x-{n}" for r, n in U.DEFAULT_FOLDERS.items()}
    cfg["media_extensions"]["image"] = cfg["media_extensions"]["image"] + [".xyz"]
    cfg["camera_time_and_timezone_policy"]["device_groups"]["phones"] = ["Apple|iPhone 15"]
    with open(U.config_path(ws), "w") as f:
        json.dump(cfg, f)
    before = json.loads(json.dumps(U.CONFIG))
    # what a phase records after load_config made this file its CONFIG
    _write_plan(ws, operations=["move"], depends_on={
        "config_fingerprint": U.sha256_file(U.config_path(ws)),
        "folders_fingerprint": U.folders_fingerprint(cfg),
        "media_extensions_fingerprint": U.media_extensions_fingerprint(cfg),
        "filename_format_fingerprint": U.sha256_text(cfg["filename_timestamp_format"]),
        "camera_group_fingerprint": U.sha256_text(
            json.dumps(cfg["camera_time_and_timezone_policy"], sort_keys=True)),
    })
    assert server._plan_summary(ws, "prep", server._current_fingerprints(ws))["stale"] == []
    assert server._state(ws)["phases"]["prep"]["executable"] is True
    assert server._execute_guard(ws, "prep", {"confirm": True}) is None
    assert U.CONFIG == before                                     # CONFIG left as it was
    cfg["folders"]["sources"] = "y-inbox"                         # the workspace's own change restales
    with open(U.config_path(ws), "w") as f:
        json.dump(cfg, f)
    assert "stale" in server._execute_guard(ws, "prep", {"confirm": True})


# --- per-command affordance (actions): pipeline order, sealed, lock --------

def test_merge_plan_needs_geotag_finalized_and_blessed_library(tmp_path):
    from cartographer.photos_2_geotag import complete_log_path
    ws = _init_ws(str(tmp_path))
    # geotag not finalized yet -> merge/plan blocked on geotag
    assert "geotag" in server._state(ws)["actions"]["merge/plan"]["reason"]
    open(complete_log_path(ws), "w").close()                 # geotag finalized
    # config points library_root at an UNblessed dir -> merge/plan now blocked on the library
    lib = tmp_path / "lib"; lib.mkdir()
    cfg = {k: v for k, v in U.default_config().items() if k != "jobs"}
    cfg["merge"]["library_root"] = str(lib)
    with open(U.config_path(ws), "w") as f:
        json.dump(cfg, f)
    mp = server._state(ws)["actions"]["merge/plan"]
    assert mp["ok"] is False and "bless the library" in mp["reason"]
    U.write_library_marker(str(lib))                         # init-library blesses it
    assert server._state(ws)["actions"]["merge/plan"]["ok"] is True


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
    for fn in ("_load_artifacts", "_save", "_photo_preview"):
        assert callable(getattr(server._editor, fn))


def test_edit_tab_reload_after_a_plan_keeps_unsaved_edits():
    # A console geotag plan reloads the Edit tab only when the editor holds no unsaved edits; otherwise the
    # console says the decisions were regenerated and leaves the reload to the user. The editor page answers
    # the question for its same-origin parent, and guards a browser-level reload/close itself.
    js = server._asset("app.js").decode()
    reload_fn = js[js.index("function reloadEditFrame"):js.index("function forceReloadEditFrame")]
    assert "editorHasUnsavedEdits" in reload_fn and "edit-stale-banner" in reload_fn
    html = server._asset("/").decode()
    assert 'id="edit-stale-banner"' in html and 'id="edit-reload"' in html
    editor = server._read_pkg("cartographer.editor", "web", ["app.js"]).decode()
    assert "window.editorHasUnsavedEdits = hasUnsavedEdits" in editor
    assert 'addEventListener("beforeunload"' in editor


def _editor_ws(tmp_path):
    ws = _init_ws(str(tmp_path))
    with open(os.path.join(U.control_dir(ws), "photos-21-time-decisions.json"), "w") as f:
        json.dump({"destinations": {}}, f)
    return ws


@pytest.mark.spec("RUL-editor_refuses_sealed", test="TST-console_server-edit_tab_refuses_a_sealed_workspace")
def test_edit_tab_refuses_a_sealed_workspace(tmp_path):
    # The console's Edit tab holds to the standalone editor's bar: it does not open a sealed workspace,
    # and takes no editor lock there.
    ws = _editor_ws(tmp_path)
    with open(U.sealed_marker_path(ws), "w") as f:
        json.dump({"sealed": True}, f)
    import threading
    import urllib.error
    import urllib.request
    old = server.Handler.workspace
    server.Handler.workspace = ws
    httpd = server._bind("127.0.0.1", 0, server.Handler)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    base = f"http://127.0.0.1:{httpd.server_address[1]}"
    try:
        assert "sealed" in server._editor_refusal(ws)
        try:
            urllib.request.urlopen(base + "/api/artifacts")
            assert False, "the sealed workspace's decisions were served"
        except urllib.error.HTTPError as e:
            assert e.code == 409 and "sealed" in json.loads(e.read())["error"]
        req = urllib.request.Request(base + "/api/save", data=b"{}", method="POST")
        with urllib.request.urlopen(req) as r:
            res = json.loads(r.read())
        assert res["ok"] is False and "sealed" in res["error"]
        assert not os.path.exists(os.path.join(U.control_dir(ws), server._editor.EDITOR_LOCK))
    finally:
        httpd.shutdown()
        httpd.server_close()
        server.Handler.workspace = old
        server._release_editor_locks()


@pytest.mark.spec("BLD-control_directory_contents", "RUL-one_editor_at_a_time", "RUL-editor_kept_until_stopped", "BLD-editor_session_lock", test="TST-console_server-edit_tab_is_one_editor_at_a_time")
def test_edit_tab_is_one_editor_at_a_time(tmp_path):
    # One decision editor at a time: while a standalone editor holds the editor lock, the console's Edit
    # tab is refused (it neither reads nor saves); once the tab has opened, it holds the lock itself and
    # a standalone editor is refused, until the console stops.
    ws = _editor_ws(tmp_path)
    other, _ = server._editor._acquire_editor_lock(ws)
    try:
        assert "another decision editor" in server._editor_refusal(ws)
    finally:
        other.close()
    try:
        assert server._editor_refusal(ws) is None
        assert server._editor_refusal(ws) is None                 # the lock is kept, not retaken
        second, owner = server._editor._acquire_editor_lock(ws)
        assert second is None and owner["pid"] == os.getpid()
    finally:
        server._release_editor_locks()
    again, _ = server._editor._acquire_editor_lock(ws)
    assert again is not None
    again.close()


def test_edit_tab_refuses_an_uninitialized_workspace(tmp_path):
    # Like the standalone editor, the tab opens only an initialized workspace — and creates nothing there.
    ws = str(tmp_path)
    assert "initialized" in server._editor_refusal(ws)
    assert not os.path.exists(U.control_dir(ws))


# --- a run stopped on changes to the workspace: the same list, accepted by the same command ----------------------

@pytest.mark.spec("BLD-accept_changes", test="TST-console_server-a_stop_on_changes_is_offered_for_acceptance")
def test_a_stop_on_changes_is_offered_for_acceptance():
    """The stop's list reaches the console as an event the late-joining page sees too, until the next run starts; the
    Accept button sends the code through the same command — `--accept-changes <code>` on its argv — and the server
    refuses a code for a command that does not check, or anything that is not such a code."""
    from cartographer.reporting import ChangesEvent, Reporter, WebSink
    sink = WebSink()
    Reporter([sink]).emit(ChangesEvent(phase="prep", command="plan", code="0123456789ab", lines=["  appeared, in x:"]))
    _q, snap = sink.subscribe()
    assert snap["changes"] == {"kind": "changes", "phase": "prep", "command": "plan", "code": "0123456789ab",
                               "lines": ["  appeared, in x:"]}
    sink.clear_changes()
    assert sink.snapshot()["changes"] is None
    assert server._accept_extra("prep", "plan", {"accept_changes": "0123456789ab"}) == (
        ["--accept-changes", "0123456789ab"], None)
    assert server._accept_extra("geotag", "finalize", {}) == ([], None)
    assert server._accept_extra("prep", "prune-quarantine", {"accept_changes": "0123456789ab"})[1]
    assert server._accept_extra("merge", "init-library", {"accept_changes": "0123456789ab"})[1]
    assert server._accept_extra("prep", "plan", {"accept_changes": "; rm -rf /"})[1]
    for phase, command in (("prep", "execute"), ("geotag", "finalize"), ("merge", "dry-run")):
        assert callable(server._make_target(phase, command, ["--accept-changes", "0123456789ab"]))
    js = server._asset("app.js").decode()
    assert 'm.kind === "changes"' in js and "accept_changes: m.code" in js
    html = server._asset("/").decode()
    assert 'id="changes-overlay"' in html and 'id="changes-accept"' in html
