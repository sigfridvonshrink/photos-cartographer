"""Phase 5b (calibration) — the §23 GPS decision tree + photos-23-gps-decisions.json (§25).

Per-file classifier (preserve/manual-locked/interpolation/extrapolation/folder-fallback/
accept-unlocated/blocked), the per-destination summary artifact (paths only for review/blocker
items), and folder_fallback downward inheritance. Decision logic at full coverage. From conftest.py.
"""
import json
from datetime import datetime, timezone

import pytest

import photos_2_time_gps as cal
import photos_utils as utils

BYDEST = "6-photos-by-dest"


def _pt(lat, lon, h, m, s):
    return cal.GPXPoint(lat, lon, datetime(2024, 7, 3, h, m, s, tzinfo=timezone.utc), "trip.gpx", 0)


def _gpx(points=None):
    idx = cal.GPXIndex("")
    idx.points = list(points if points is not None else [_pt(50.0, 4.0, 12, 0, 0), _pt(50.0, 4.001, 12, 1, 0)])
    return idx


def _file(rel, dest, *, native=False):
    return {"relative_path": rel, "destination": dest, "has_native_gps": native}


def _row(rel, utc):
    return {"relative_path": rel, "resolved_utc": utc}


def _wf(tmp_path):
    ws = tmp_path / "ws"
    (ws / ".photos-ingest").mkdir(parents=True)
    (ws / ".photos-ingest" / "photos-11-handoff.json").write_text("{}")
    wf = cal.CalibrationWorkflow(str(ws))
    wf._gpx_fingerprint = "gfp"
    return wf


def _build(wf, files, rows, gpx, prior=None):
    return wf.build_gps_decisions(files, rows, gpx, prior, "rfp")


def _dd(art, dest):
    return art["destinations"][dest]


# --- classifier branch by branch --------------------------------------------

def test_classify_all_branches():
    g = _gpx()
    cfg = utils.CONFIG
    ru = datetime(2024, 7, 3, 12, 0, 30, tzinfo=timezone.utc)          # inside the track
    far = datetime(2024, 7, 3, 13, 0, 0, tzinfo=timezone.utc)          # >> extrapolation window
    near_end = datetime(2024, 7, 3, 12, 2, 30, tzinfo=timezone.utc)    # 90 s past last -> extrapolate
    assert cal.classify_gps(_file("a", "d", native=True), None, g, cfg, None, {})[0] == "preserve_native"
    assert cal.classify_gps(_file("a", "d"), None, g, cfg, None, {"manual_lat": 5, "manual_lon": 6})[0] == "manual_locked"
    assert cal.classify_gps(_file("a", "d"), ru, g, cfg, None, {})[0] == "gpx_interpolation"
    assert cal.classify_gps(_file("a", "d"), near_end, g, cfg, None, {})[0] == "gpx_extrapolation"
    assert cal.classify_gps(_file("a", "d"), far, g, cfg, {"lat": 1, "lon": 2}, {})[0] == "manual_fallback"
    assert cal.classify_gps(_file("a", "d"), None, g, cfg, None, {"accept_unlocated": True})[0] == "no_change"
    assert cal.classify_gps(_file("a", "d"), None, g, cfg, None, {})[0] == "blocked"


@pytest.mark.parametrize("lat, lon, ok", [(50, 4, True), (-90, 180, True), (91, 0, False),
                                          (0, 181, False), ("x", 0, False), (0, True, False)])
def test_valid_coord(lat, lon, ok):
    assert cal._valid_coord(lat, lon) is ok


# --- the summary artifact ----------------------------------------------------

def test_summary_counts_and_review_items(tmp_path):
    wf = _wf(tmp_path)
    d = f"{BYDEST}/Trip"
    files = [_file(f"{d}/n.jpg", d, native=True), _file(f"{d}/i.jpg", d), _file(f"{d}/b.jpg", d)]
    rows = [_row(f"{d}/i.jpg", "2024-07-03T12:00:30Z")]            # i placeable; b has no resolved UTC
    art, blk = _build(wf, files, rows, _gpx())
    assert not blk
    s = _dd(art, d)["gps_decisions"]["summary"]
    assert s["files_total"] == 3 and s["preserve_native_gps"] == 1
    assert s["automatic_gpx_interpolation"] == 1 and s["blocked"] == 1
    paths = [ri["relative_path"] for ri in _dd(art, d)["gps_decisions"]["review_items"]]
    assert paths == [f"{d}/b.jpg"]                                # only the blocker is enumerated
    assert _dd(art, d)["gps_decisions"]["automatic_decision_summary"]["gpx_files_used"] == ["trip.gpx"]
    assert art["status"] == "requires_user_input" and art["requires_user_input"]
    dep = art["depends_on"]
    assert dep["resolved_utc_cache_fingerprint"] == "rfp" and dep["gpx_fingerprint"] == "gfp"
    assert dep["gps_policy_fingerprint"] and dep["handoff"]["sha256"]


def test_extrapolation_counts_in_summary(tmp_path):
    wf = _wf(tmp_path)
    d = f"{BYDEST}/Trip"
    files = [_file(f"{d}/e.jpg", d)]
    rows = [_row(f"{d}/e.jpg", "2024-07-03T12:02:30Z")]               # 90 s past last point -> extrapolate
    art, _ = _build(wf, files, rows, _gpx())
    assert _dd(art, d)["gps_decisions"]["summary"]["automatic_gpx_extrapolation"] == 1
    assert art["status"] == "complete"


def test_all_automatic_is_complete(tmp_path):
    wf = _wf(tmp_path)
    d = f"{BYDEST}/Trip"
    files = [_file(f"{d}/n.jpg", d, native=True), _file(f"{d}/i.jpg", d)]
    art, _ = _build(wf, files, [_row(f"{d}/i.jpg", "2024-07-03T12:00:30Z")], _gpx())
    assert art["status"] == "complete" and art["requires_user_input"] is False
    assert art["decision_mode"] == "no_op_or_auto_resolved"


def test_accept_unlocated_resolves_block(tmp_path):
    wf = _wf(tmp_path)
    d = f"{BYDEST}/Trip"
    files = [_file(f"{d}/b.jpg", d)]
    prior = {"destinations": {d: {"gps_decisions": {"review_items": [
        {"relative_path": f"{d}/b.jpg", "user_decision": {"accept_unlocated": True}}]}}}}
    art, _ = _build(wf, files, [], _gpx(), prior)
    assert _dd(art, d)["gps_decisions"]["summary"]["no_gps_change_needed"] == 1
    assert art["status"] == "complete"


# --- coordinate validation ---------------------------------------------------

def test_bad_review_coord_blocks(tmp_path):
    wf = _wf(tmp_path)
    d = f"{BYDEST}/Trip"
    prior = {"destinations": {d: {"gps_decisions": {"review_items": [
        {"relative_path": f"{d}/b.jpg", "user_decision": {"manual_lat": 999, "manual_lon": 0}}]}}}}
    _, blk = _build(wf, [_file(f"{d}/b.jpg", d)], [], _gpx(), prior)
    assert blk and "manual_lat/lon out of range" in blk[0]


def test_bad_folder_fallback_coord_blocks(tmp_path):
    wf = _wf(tmp_path)
    d = f"{BYDEST}/Trip"
    prior = {"destinations": {d: {"folder_fallback": {"user_decision": {"fallback_lat": 999, "fallback_lon": 0}}}}}
    _, blk = _build(wf, [_file(f"{d}/b.jpg", d)], [], _gpx(), prior)
    assert blk and "fallback_lat/lon out of range" in blk[0]


# --- folder_fallback downward inheritance (mirrors Phase 3c) -----------------

def _with_fallback(parent, lat, lon):
    return {"destinations": {parent: {"folder_fallback": {"user_decision":
            {"fallback_lat": lat, "fallback_lon": lon}}}}}


def test_child_inherits_parent_fallback_as_proposal(tmp_path):
    wf = _wf(tmp_path)
    p, c = f"{BYDEST}/Trip", f"{BYDEST}/Trip/Sub"
    files = [_file(f"{p}/a.jpg", p), _file(f"{c}/b.jpg", c)]
    art, _ = _build(wf, files, [], _gpx(), _with_fallback(p, 10.0, 20.0))
    assert _dd(art, p)["folder_fallback"]["effective_fallback"] == {"lat": 10.0, "lon": 20.0}
    cfb = _dd(art, c)["folder_fallback"]
    assert cfb["proposal"]["proposal_source"] == "inherited" and cfb["proposal"]["inherited_from"] == p
    assert cfb["proposal"]["proposed_fallback"] == {"lat": 10.0, "lon": 20.0}
    assert cfb["effective_fallback"] is None                      # confirmable, not auto-applied


def test_accepting_inherited_fallback_resolves_child_block(tmp_path):
    wf = _wf(tmp_path)
    p, c = f"{BYDEST}/Trip", f"{BYDEST}/Trip/Sub"
    files = [_file(f"{p}/a.jpg", p), _file(f"{c}/b.jpg", c)]
    prior = {"destinations": {
        p: {"folder_fallback": {"user_decision": {"fallback_lat": 10.0, "fallback_lon": 20.0}}},
        c: {"folder_fallback": {"user_decision": {"accept_proposal": True}}}}}
    art, _ = _build(wf, files, [], _gpx(), prior)
    assert _dd(art, c)["folder_fallback"]["effective_fallback"] == {"lat": 10.0, "lon": 20.0}
    assert _dd(art, c)["gps_decisions"]["summary"]["automatic_folder_fallback"] == 1   # b resolved


def test_manual_fallback_reroots_and_grandchild_skips_unconfirmed(tmp_path):
    wf = _wf(tmp_path)
    p, c, gc = f"{BYDEST}/Trip", f"{BYDEST}/Trip/Sub", f"{BYDEST}/Trip/Sub/Deep"
    files = [_file(f"{p}/a.jpg", p), _file(f"{c}/b.jpg", c), _file(f"{gc}/d.jpg", gc)]
    prior = {"destinations": {
        p: {"folder_fallback": {"user_decision": {"fallback_lat": 10.0, "fallback_lon": 20.0}}},
        c: {"folder_fallback": {"user_decision": {"fallback_lat": 30.0, "fallback_lon": 40.0}}}}}
    art, _ = _build(wf, files, [], _gpx(), prior)
    # c has its own manual fallback (re-roots); grandchild inherits c's, not p's
    assert _dd(art, gc)["folder_fallback"]["proposal"]["inherited_from"] == c
    assert _dd(art, gc)["folder_fallback"]["proposal"]["proposed_fallback"] == {"lat": 30.0, "lon": 40.0}


def test_grandchild_skips_to_nearest_resolved_ancestor(tmp_path):
    wf = _wf(tmp_path)
    p, c, gc = f"{BYDEST}/Trip", f"{BYDEST}/Trip/Sub", f"{BYDEST}/Trip/Sub/Deep"
    files = [_file(f"{p}/a.jpg", p), _file(f"{c}/b.jpg", c), _file(f"{gc}/d.jpg", gc)]
    art, _ = _build(wf, files, [], _gpx(), _with_fallback(p, 10.0, 20.0))   # only p resolved
    assert _dd(art, c)["folder_fallback"]["effective_fallback"] is None     # c unconfirmed
    assert _dd(art, gc)["folder_fallback"]["proposal"]["inherited_from"] == p  # skips unconfirmed c


def test_sibling_fallback_does_not_leak(tmp_path):
    wf = _wf(tmp_path)
    a, b = f"{BYDEST}/Trip/A", f"{BYDEST}/Trip/B"
    files = [_file(f"{a}/x.jpg", a), _file(f"{b}/y.jpg", b)]
    art, _ = _build(wf, files, [], _gpx(), _with_fallback(a, 10.0, 20.0))
    assert _dd(art, b)["folder_fallback"]["proposal"] == {"proposal_source": "manual_required"}


def test_accept_with_no_proposal_is_stale(tmp_path):
    wf = _wf(tmp_path)
    d = f"{BYDEST}/Trip"
    prior = {"destinations": {d: {"folder_fallback": {"user_decision": {"accept_proposal": True}}}}}
    art, _ = _build(wf, [_file(f"{d}/b.jpg", d)], [], _gpx(), prior)
    assert _dd(art, d)["folder_fallback"]["stale_user_decision"] is True


# --- rerun preservation / determinism ---------------------------------------

def test_review_decision_preserved_and_resolves(tmp_path):
    wf = _wf(tmp_path)
    d = f"{BYDEST}/Trip"
    files = [_file(f"{d}/b.jpg", d)]
    art1, _ = _build(wf, files, [], _gpx())
    assert art1["status"] == "requires_user_input"
    prior = {"destinations": {d: {"gps_decisions": {"review_items": [
        {"relative_path": f"{d}/b.jpg", "user_decision": {"manual_lat": 12.0, "manual_lon": 13.0}}]}}}}
    art2, _ = _build(wf, files, [], _gpx(), prior)
    assert _dd(art2, d)["gps_decisions"]["summary"]["manual_locked"] == 1
    assert art2["status"] == "complete"


def test_determinism(tmp_path):
    wf = _wf(tmp_path)
    d = f"{BYDEST}/Trip"
    files = [_file(f"{d}/n.jpg", d, native=True), _file(f"{d}/i.jpg", d)]
    rows = [_row(f"{d}/i.jpg", "2024-07-03T12:00:30Z")]
    a1, _ = _build(wf, files, rows, _gpx())
    a2, _ = _build(wf, files, rows, _gpx(), a1)
    assert json.dumps(a1, sort_keys=True) == json.dumps(a2, sort_keys=True)
