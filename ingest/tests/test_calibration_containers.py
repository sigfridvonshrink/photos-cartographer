"""Phase 3/5 (calibration) — file-less CONTAINER destinations.

A folder that holds only sub-destinations (no media of its own) is still materialized as a
destination so a human can author timezone / GPS-fallback / clock-offset decisions on it that
propagate DOWN to its children. Such a container:
  * never blocks and stays off the to-do list (it has no media to act on);
  * auto-resolves its timezone/offset by inheritance, while remaining overridable;
  * exposes offset cells for the camera groups found ANYWHERE in its subtree (recursively), so one
    offset set on the parent reaches every child — but a child's own decision is never pooled upward.
From conftest.py.
"""
import photos_2_time_gps as cal
import photos_utils as utils
from datetime import datetime, timezone

BYDEST = "6-photos-by-dest"
CAM = "SONY|ILCE-6400|123"
CAM2 = "CANON|EOS-5D|999"
GROUPS = {CAM: {"camera_group_class": "camera"}, CAM2: {"camera_group_class": "camera"}}


def _wf(tmp_path):
    ws = tmp_path / "ws"
    (ws / ".photos-ingest").mkdir(parents=True)
    (ws / ".photos-ingest" / "photos-11-handoff.json").write_text("{}")
    wf = cal.CalibrationWorkflow(str(ws))
    wf._gpx_fingerprint = "fp"
    return wf


def _gpx():
    idx = cal.GPXIndex("")
    idx.points = []
    return idx


def _tfile(rel, dest, *, key=CAM, naive="2024:07:03 14:00:00"):
    return {"relative_path": rel, "destination": dest, "camera_group_key": key,
            "native_gps": None, "has_native_gps": False, "has_timestamp": True,
            "source_naive_time": naive, "camera_identity": {}}


def _gfile(rel, dest):
    return {"relative_path": rel, "destination": dest, "has_native_gps": False}


# --- enumeration -------------------------------------------------------------

def test_container_materialized_with_recursive_groups(tmp_path):
    wf = _wf(tmp_path)
    # CAM lives under Trip/Day1; CAM2 lives two levels down under Trip/Day2/Sub.
    files = [_tfile(f"{BYDEST}/Trip/Day1/a.arw", f"{BYDEST}/Trip/Day1", key=CAM),
             _tfile(f"{BYDEST}/Trip/Day2/Sub/b.arw", f"{BYDEST}/Trip/Day2/Sub", key=CAM2)]
    art, _ = wf.build_time_decisions(files, GROUPS, None, _gpx())
    d = art["destinations"]
    # every ancestor folder is materialized and flagged file-less
    for c in (BYDEST, f"{BYDEST}/Trip", f"{BYDEST}/Trip/Day2"):
        assert d[c]["file_less"] is True
    # real leaves are not file-less
    assert "file_less" not in d[f"{BYDEST}/Trip/Day1"]
    # RECURSIVE aggregation: Trip (grandparent of Sub) speaks for BOTH cameras in its subtree
    assert set(d[f"{BYDEST}/Trip"]["camera_group_time_decisions"]) == {CAM, CAM2}
    # an intermediate container speaks only for the groups beneath IT
    assert set(d[f"{BYDEST}/Trip/Day2"]["camera_group_time_decisions"]) == {CAM2}
    assert set(d[f"{BYDEST}/Trip/Day1"]["camera_group_time_decisions"]) == {CAM}


def test_containers_never_block(tmp_path):
    wf = _wf(tmp_path)
    files = [_tfile(f"{BYDEST}/Trip/Day1/a.arw", f"{BYDEST}/Trip/Day1")]
    art, _ = wf.build_time_decisions(files, GROUPS, None, _gpx())
    trip = art["destinations"][f"{BYDEST}/Trip"]
    assert trip["destination_timezone"]["requires_user_input"] is False
    assert trip["camera_group_time_decisions"][CAM]["requires_user_input"] is False


# --- auto-resolve + propagation ----------------------------------------------

def test_container_timezone_autoresolves_from_default(tmp_path):
    utils.CONFIG["camera_time_and_timezone_policy"]["default_folder_timezone"] = "Europe/Brussels"
    wf = _wf(tmp_path)
    files = [_tfile(f"{BYDEST}/Trip/Day1/a.arw", f"{BYDEST}/Trip/Day1")]
    art, _ = wf.build_time_decisions(files, GROUPS, None, _gpx())
    trip = art["destinations"][f"{BYDEST}/Trip"]["destination_timezone"]
    assert trip["effective_iana_timezone"] == "Europe/Brussels"
    assert trip["decision_mode"] == "auto_resolved" and trip["requires_user_input"] is False
    # the real leaf still must confirm (it has photos)
    assert art["destinations"][f"{BYDEST}/Trip/Day1"]["destination_timezone"]["requires_user_input"] is True


def test_manual_container_offset_propagates_to_children(tmp_path):
    wf = _wf(tmp_path)
    files = [_tfile(f"{BYDEST}/Trip/Day1/a.arw", f"{BYDEST}/Trip/Day1"),
             _tfile(f"{BYDEST}/Trip/Day2/b.arw", f"{BYDEST}/Trip/Day2")]
    prior = {"destinations": {f"{BYDEST}/Trip": {"camera_group_time_decisions":
             {CAM: {"user_decision": {"manual_offset_seconds": -3600}}}}}}
    art, _ = wf.build_time_decisions(files, GROUPS, prior, _gpx())
    trip = art["destinations"][f"{BYDEST}/Trip"]["camera_group_time_decisions"][CAM]
    assert trip["effective_time_anchor"] == {"offset_seconds": -3600, "source": "manual"}
    for child in (f"{BYDEST}/Trip/Day1", f"{BYDEST}/Trip/Day2"):
        c = art["destinations"][child]["camera_group_time_decisions"][CAM]
        assert c["proposal"]["proposal_source"] == "inherited"
        assert c["proposal"]["inherited_from"] == f"{BYDEST}/Trip"
        assert c["proposal"]["proposed_offset_seconds"] == -3600


def test_child_decision_is_not_pooled_upward(tmp_path):
    wf = _wf(tmp_path)
    files = [_tfile(f"{BYDEST}/Trip/Day1/a.arw", f"{BYDEST}/Trip/Day1")]
    prior = {"destinations": {f"{BYDEST}/Trip/Day1": {"camera_group_time_decisions":
             {CAM: {"user_decision": {"manual_offset_seconds": -3600}}}}}}
    art, _ = wf.build_time_decisions(files, GROUPS, prior, _gpx())
    # the child resolved from its own decision
    leaf = art["destinations"][f"{BYDEST}/Trip/Day1"]["camera_group_time_decisions"][CAM]
    assert leaf["effective_time_anchor"]["offset_seconds"] == -3600
    # the parent container has a cell for CAM (gathered from the subtree) but it stays UNSET
    trip = art["destinations"][f"{BYDEST}/Trip"]["camera_group_time_decisions"][CAM]
    assert trip["effective_time_anchor"] == "" and trip["requires_user_input"] is False


# --- GPS fallback ------------------------------------------------------------

def test_container_fallback_propagates_to_children(tmp_path):
    wf = _wf(tmp_path)
    files = [_gfile(f"{BYDEST}/Trip/Day1/a.jpg", f"{BYDEST}/Trip/Day1")]
    prior = {"destinations": {f"{BYDEST}/Trip": {"folder_fallback":
             {"user_decision": {"fallback_lat": 50.0, "fallback_lon": 4.0}}}}}
    art, _ = wf.build_gps_decisions(files, [], _gpx(), prior, "rfp")
    d = art["destinations"]
    assert d[f"{BYDEST}/Trip"]["file_less"] is True
    assert d[f"{BYDEST}/Trip"]["gps_decisions"]["summary"]["files_total"] == 0
    assert d[f"{BYDEST}/Trip"]["folder_fallback"]["effective_fallback"] == {"lat": 50.0, "lon": 4.0}
    child = d[f"{BYDEST}/Trip/Day1"]["folder_fallback"]
    assert child["proposal"]["proposal_source"] == "inherited"
    assert child["proposal"]["inherited_from"] == f"{BYDEST}/Trip"
    assert child["proposal"]["proposed_fallback"] == {"lat": 50.0, "lon": 4.0}


def test_determinism_with_containers(tmp_path):
    import json
    wf = _wf(tmp_path)
    files = [_tfile(f"{BYDEST}/Trip/Day1/a.arw", f"{BYDEST}/Trip/Day1", key=CAM),
             _tfile(f"{BYDEST}/Trip/Day2/Sub/b.arw", f"{BYDEST}/Trip/Day2/Sub", key=CAM2)]
    a1, _ = wf.build_time_decisions(files, GROUPS, None, _gpx())
    a2, _ = wf.build_time_decisions(files, GROUPS, a1, _gpx())
    assert json.dumps(a1, sort_keys=True) == json.dumps(a2, sort_keys=True)
