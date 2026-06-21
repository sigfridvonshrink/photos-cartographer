"""Unit tests for the console server helpers (asset serving, state, run gating)."""

from cartographer.console import server


def test_asset_serves_console_spa_and_shared_tokens():
    assert server._asset("/")[:9] == b"<!doctype"           # index.html default
    assert server._asset("index.html")[:9] == b"<!doctype"
    assert b"--accent" in server._asset("tokens.css")        # shared from the editor package
    assert server._asset("app.js") is not None


def test_asset_rejects_path_traversal_and_missing():
    assert server._asset("../jobs.py") is None
    assert server._asset("vendor/../../secret") is None
    assert server._asset("does-not-exist.css") is None


def test_only_non_mutating_prep_commands_are_allowed():
    assert ("prep", "plan") in server._ALLOWED
    assert ("prep", "dry-run") in server._ALLOWED
    assert ("prep", "execute") not in server._ALLOWED       # execute gated to v2.2
    assert ("merge", "execute") not in server._ALLOWED


def test_make_target_builds_a_callable_without_running():
    target = server._make_target("prep", "plan")
    assert callable(target)                                  # building it must not invoke run()


def test_state_reports_workspace_idle_job_and_allowed(tmp_path):
    st = server._state(str(tmp_path))
    assert st["workspace"] == str(tmp_path)
    assert st["job"]["state"] == "idle"
    assert "prep/plan" in st["allowed"]
    assert st["phases"]["prep"]["plan_exists"] is False
