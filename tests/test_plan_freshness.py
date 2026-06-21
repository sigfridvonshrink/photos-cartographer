"""Tests for photos_utils.plan_dependencies_fresh — the shared, cheap, read-only artifact-dependency
freshness check (the subset shared by the per-phase staleness checks). Safety-critical: covered
exhaustively, and pinned to agree with the real MergeWorkflow.revalidate_plan_deps so the shared
helper can never diverge from the check execute enforces."""

import json
import os
from types import SimpleNamespace

import photos_utils as U


def _art(ws, name, body):
    """Write a control-dir JSON artifact and return its json_artifact dependency entry."""
    cd = os.path.join(ws, U.CONTROL_DIR)
    os.makedirs(cd, exist_ok=True)
    p = os.path.join(cd, name)
    with open(p, "w") as f:
        json.dump(body, f)
    return U.json_dependency(name, ws, p)


# --- direct unit tests ----------------------------------------------------

def test_empty_depends_on_is_fresh(tmp_path):
    assert U.plan_dependencies_fresh(str(tmp_path), {}) == []
    assert U.plan_dependencies_fresh(str(tmp_path), None) == []


def test_json_artifact_dep_fresh_changed_missing(tmp_path):
    ws = str(tmp_path)
    dep = {"photos-24-executable-plan.json": _art(ws, "photos-24-executable-plan.json", {"v": 1})}
    assert U.plan_dependencies_fresh(ws, dep) == []                       # unchanged → fresh
    # mutate the artifact's bytes → stale
    with open(os.path.join(ws, U.CONTROL_DIR, "photos-24-executable-plan.json"), "w") as f:
        json.dump({"v": 2}, f)
    assert U.plan_dependencies_fresh(ws, dep) == ["photos-24-executable-plan.json changed or missing"]
    # delete it → stale
    os.remove(os.path.join(ws, U.CONTROL_DIR, "photos-24-executable-plan.json"))
    assert U.plan_dependencies_fresh(ws, dep) == ["photos-24-executable-plan.json changed or missing"]


def test_handoff_dep_checked_only_when_current_supplied(tmp_path):
    dep = {"handoff": {"dependency_type": "handoff_content", "content_fingerprint": "abc"}}
    # not supplied → not checked (quick-pass scope is caller's choice)
    assert U.plan_dependencies_fresh(str(tmp_path), dep) == []
    # supplied + matches → fresh
    assert U.plan_dependencies_fresh(str(tmp_path), dep, {"handoff": "abc"}) == []
    # supplied + differs → stale
    assert U.plan_dependencies_fresh(str(tmp_path), dep, {"handoff": "xyz"}) == \
        ["handoff content fingerprint changed"]


def test_scalar_fingerprint_checked_only_when_current_supplied(tmp_path):
    dep = {"config_fingerprint": "C1", "folders_fingerprint": "F1"}
    assert U.plan_dependencies_fresh(str(tmp_path), dep) == []            # nothing supplied → skipped
    assert U.plan_dependencies_fresh(str(tmp_path), dep,
                                     {"config_fingerprint": "C1", "folders_fingerprint": "F1"}) == []
    out = U.plan_dependencies_fresh(str(tmp_path), dep,
                                    {"config_fingerprint": "C2", "folders_fingerprint": "F1"})
    assert out == ["config_fingerprint changed"]


def test_multiple_changes_all_reported(tmp_path):
    ws = str(tmp_path)
    dep = {
        "photos-24-executable-plan.json": _art(ws, "photos-24-executable-plan.json", {"v": 1}),
        "config_fingerprint": "C1",
    }
    with open(os.path.join(ws, U.CONTROL_DIR, "photos-24-executable-plan.json"), "w") as f:
        json.dump({"v": 9}, f)
    out = U.plan_dependencies_fresh(ws, dep, {"config_fingerprint": "C2"})
    assert "photos-24-executable-plan.json changed or missing" in out and "config_fingerprint changed" in out


# --- equivalence with the real MergeWorkflow.revalidate_plan_deps ----------

def _merge_setup(tmp_path):
    """A workspace + a merge-shaped plan whose deps all currently verify (fresh)."""
    from cartographer import photos_3_merge as merge
    ws = str(tmp_path)
    cd = os.path.join(ws, U.CONTROL_DIR)
    os.makedirs(cd, exist_ok=True)
    with open(U.config_path(ws), "w") as f:
        json.dump({"x": 1}, f)
    handoff = {"inventory": ["a", "b"], "run_metadata": {"ignored": True}}
    depends_on = {
        "photos-24-executable-plan.json": _art(ws, "photos-24-executable-plan.json", {"plan": 1}),
        "photos-25-execution-summary.json": _art(ws, "photos-25-execution-summary.json", {"sum": 1}),
        "handoff": {"dependency_type": "handoff_content", "artifact_name": "photos-11-handoff.json",
                    "content_fingerprint": U.handoff_content_fingerprint(handoff)},
        "config_fingerprint": U.sha256_file(U.config_path(ws)),
        "folders_fingerprint": U.folders_fingerprint(),
        "media_extensions_fingerprint": U.media_extensions_fingerprint(),
    }
    plan = {"schema_version": merge.MERGE_PLAN_SCHEMA_VERSION, "depends_on": depends_on}
    # current values the helper compares against (what merge recomputes internally)
    cur = {
        "handoff": U.handoff_content_fingerprint(handoff),
        "config_fingerprint": U.sha256_file(U.config_path(ws)),
        "folders_fingerprint": U.folders_fingerprint(),
        "media_extensions_fingerprint": U.media_extensions_fingerprint(),
    }
    return merge, ws, handoff, plan, cur


def _merge_verdict(merge, handoff, ws, plan):
    # revalidate_plan_deps only uses self.handoff — drive it without building the whole workflow.
    return merge.MergeWorkflow.revalidate_plan_deps(SimpleNamespace(handoff=handoff), ws, plan)


def test_helper_matches_merge_when_fresh(tmp_path):
    merge, ws, handoff, plan, cur = _merge_setup(tmp_path)
    assert _merge_verdict(merge, handoff, ws, plan) == []                 # merge: fresh
    assert U.plan_dependencies_fresh(ws, plan["depends_on"], cur) == []   # helper: fresh — agree


def test_helper_matches_merge_for_each_single_mutation(tmp_path):
    merge, ws, handoff, plan, cur = _merge_setup(tmp_path)

    scenarios = []
    # 1. a json artifact changes
    def mutate_artifact():
        with open(os.path.join(ws, U.CONTROL_DIR, "photos-25-execution-summary.json"), "w") as f:
            json.dump({"sum": 99}, f)
    scenarios.append(("artifact", mutate_artifact, dict(cur)))
    # 2. handoff content changes (pass a different current fingerprint, and a new handoff to merge)
    scenarios.append(("handoff", None, {**cur, "handoff": "DIFFERENT"}))
    # 3. config changes
    scenarios.append(("config", None, {**cur, "config_fingerprint": "DIFFERENT"}))

    for name, mutate, helper_cur in scenarios:
        merge2, ws2, handoff2, plan2, cur2 = _merge_setup(tmp_path / name)
        # rebuild helper_cur relative to this fresh setup, applying the same delta
        hc = dict(cur2)
        if name == "handoff":
            handoff2 = {"inventory": ["CHANGED"]}            # merge will recompute a different fp
            hc["handoff"] = "DIFFERENT"
        if name == "config":
            with open(U.config_path(ws2), "w") as f:
                json.dump({"x": 999}, f)                     # merge recomputes sha256_file → differs
            hc["config_fingerprint"] = U.sha256_file(U.config_path(ws2))
        if name == "artifact":
            with open(os.path.join(ws2, U.CONTROL_DIR, "photos-25-execution-summary.json"), "w") as f:
                json.dump({"sum": 99}, f)

        m = _merge_verdict(merge2, handoff2, ws2, plan2)
        h = U.plan_dependencies_fresh(ws2, plan2["depends_on"], hc)
        assert (len(m) > 0) and (len(h) > 0), f"{name}: merge={m} helper={h}"   # both detect stale
        assert len(m) == len(h) == 1, f"{name}: merge={m} helper={h}"           # exactly the one dep
