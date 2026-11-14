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

"""Phase 5b (geotag) — the §23 GPS decision tree + photos-23-gps-decisions.json (§25).

Per-file classifier (preserve/manual-locked/interpolation/extrapolation/folder-fallback/
accept-unlocated/blocked), the per-destination summary artifact (paths only for review/blocker
items), and folder_fallback downward inheritance. Decision logic at full coverage. From conftest.py.
"""
import json
from datetime import datetime, timezone

import pytest

import photos_2_geotag as cal
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
    wf = cal.GeotagWorkflow(str(ws))
    wf._gpx_fingerprint = "gfp"
    return wf


def _build(wf, files, rows, gpx, prior=None):
    return wf.build_gps_decisions(files, rows, gpx, prior, "rfp")


def _dd(art, dest):
    return art["destinations"][dest]


# --- classifier branch by branch --------------------------------------------

@pytest.mark.spec("BLD-placement_order", "RUL-geotag_rerun_keeps_settled", "RUL-own_position_kept", "RUL-placement_order", test="TST-geotag_gps_decisions-classify_all_branches")
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
@pytest.mark.spec("RUL-checked_positions_and_times", test="TST-geotag_gps_decisions-valid_coord")
def test_valid_coord(lat, lon, ok):
    assert cal._valid_coord(lat, lon) is ok


# --- the summary artifact ----------------------------------------------------

@pytest.mark.spec("BLD-gps_decisions_record", "RUL-tracks_in_dependencies",
                  test="TST-geotag_gps_decisions-summary_counts_and_review_items")
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
    assert dep["gps_policy_fingerprint"] and dep["handoff"]["content_fingerprint"]


def test_extrapolation_counts_in_summary(tmp_path):
    wf = _wf(tmp_path)
    d = f"{BYDEST}/Trip"
    files = [_file(f"{d}/e.jpg", d)]
    rows = [_row(f"{d}/e.jpg", "2024-07-03T12:02:30Z")]               # 90 s past last point -> extrapolate
    art, _ = _build(wf, files, rows, _gpx())
    assert _dd(art, d)["gps_decisions"]["summary"]["automatic_gpx_extrapolation"] == 1
    assert art["status"] == "complete"


@pytest.mark.spec("RUL-decision_stage_writes_record")
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


@pytest.mark.spec("RUL-fallback_from_nearest", "RUL-other_proposals_need_acceptance", "BLD-folder_fallback_cell", test="TST-geotag_gps_decisions-child_inherits_parent_fallback_as_proposal")
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


@pytest.mark.spec("RUL-fallback_from_nearest",
                  test="TST-geotag_gps_decisions-manual_fallback_reroots_and_grandchild_skips_unconfirmed")
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


@pytest.mark.spec("RUL-invalid_decision_kept")
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


@pytest.mark.spec("RUL-fallback_from_nearest", "RUL-accepted_fallback_follows", "BLD-folder_fallback_cell",
                  test="TST-geotag_gps_decisions-an_accepted_inheritance_follows_the_parent")
def test_an_accepted_inheritance_follows_the_parent(tmp_path):
    # Accepting the inherited fallback is choosing to inherit: the parent's fallback changed, the child follows it.
    wf = _wf(tmp_path)
    p, c = f"{BYDEST}/Trip", f"{BYDEST}/Trip/Sub"
    files = [_file(f"{p}/a.jpg", p), _file(f"{c}/b.jpg", c)]
    prior = {"destinations": {
        p: {"folder_fallback": {"user_decision": {"fallback_lat": 10.0, "fallback_lon": 20.0}}},
        c: {"folder_fallback": {"user_decision": {"accept_proposal": True}}}}}
    prior["destinations"][p]["folder_fallback"]["user_decision"] = {"fallback_lat": 11.0, "fallback_lon": 21.0}
    art, _ = _build(wf, files, [], _gpx(), prior)
    cfb = _dd(art, c)["folder_fallback"]
    assert cfb["effective_fallback"] == {"lat": 11.0, "lon": 21.0} and cfb["stale_user_decision"] is False


@pytest.mark.spec("RUL-fallback_optional", "BLD-folder_fallback_cell",
                  test="TST-geotag_gps_decisions-a_destination_never_waits_on_its_fallback")
def test_a_destination_never_waits_on_its_fallback(tmp_path):
    # No fallback anywhere: no fallback cell asks for anything — a container's included; only the photo nothing
    # places waits, and on its own.
    wf = _wf(tmp_path)
    c = f"{BYDEST}/Trip/Sub"
    art, _ = _build(wf, [_file(f"{c}/b.jpg", c)], [], _gpx(), None)
    for dest in (BYDEST, f"{BYDEST}/Trip", c):
        fb = _dd(art, dest)["folder_fallback"]
        assert fb["requires_user_input"] is False and fb["effective_fallback"] is None, dest
    items = _dd(art, c)["gps_decisions"]["review_items"]
    assert [(i["relative_path"], i["reason"], i["requires_user_input"]) for i in items] == [
        (f"{c}/b.jpg", "no_reliable_gps_source", True)]



def _fp_file(rel, dest, fp):
    return dict(_file(rel, dest), content_fingerprint=fp)


@pytest.mark.spec("RUL-photo_decision_follows_the_photo", "BLD-review_item_identity",
                  test="TST-geotag_gps_decisions-a_photo_s_decision_follows_it_through_its_rename")
def test_a_photo_s_decision_follows_it_through_its_rename(tmp_path):
    """A position the user set for one photo, or their answer to leave it unlocated, is that photo's — found
    again by its fingerprint once geotag has renamed it, never lost with the old name (nor given to another
    photo that takes the name)."""
    wf, d = _wf(tmp_path), f"{BYDEST}/T"
    before = [_fp_file(f"{d}/a.arw", d, "fp-a"), _fp_file(f"{d}/b.arw", d, "fp-b")]
    rows = [_row(f"{d}/a.arw", "2024-07-03T20:00:00Z"), _row(f"{d}/b.arw", "2024-07-03T21:00:00Z")]   # off the track
    art, _ = _build(wf, before, rows, _gpx())
    items = {ri["relative_path"]: ri for ri in _dd(art, d)["gps_decisions"]["review_items"]}
    assert items[f"{d}/a.arw"]["content_fingerprint"] == "fp-a" and items[f"{d}/a.arw"]["requires_user_input"]
    items[f"{d}/a.arw"]["user_decision"].update(manual_lat=51.5, manual_lon=4.5)
    items[f"{d}/b.arw"]["user_decision"]["accept_unlocated"] = True
    # execute renamed both; a new photo took a.arw's old name
    after = [_fp_file(f"{d}/2024-07-03--22-00-00.arw", d, "fp-a"), _fp_file(f"{d}/2024-07-03--23-00-00.arw", d, "fp-b"),
             _fp_file(f"{d}/a.arw", d, "fp-new")]
    rows2 = [_row(after[0]["relative_path"], "2024-07-03T20:00:00Z"), _row(after[1]["relative_path"], "2024-07-03T21:00:00Z"),
             _row(f"{d}/a.arw", "2024-07-03T19:00:00Z")]
    art2, blk = _build(wf, after, rows2, _gpx(), art)
    assert not blk
    got = {ri["content_fingerprint"]: ri for ri in _dd(art2, d)["gps_decisions"]["review_items"]}
    assert got["fp-a"]["reason"] == "manual_locked" and got["fp-a"]["user_decision"]["manual_lat"] == 51.5
    assert got["fp-b"]["reason"] == "accepted_unlocated"
    assert got["fp-new"]["requires_user_input"] and got["fp-new"]["user_decision"]["manual_lat"] == ""
    # a fingerprint taken again with a new value: the decision follows through the pin's key
    retaken = [dict(_fp_file(after[0]["relative_path"], d, "fp-a2"), original_key="fp-a")]
    art3, _ = _build(wf, retaken, rows2[:1], _gpx(), art2)
    assert _dd(art3, d)["gps_decisions"]["review_items"][0]["reason"] == "manual_locked"


@pytest.mark.spec("RUL-unplaced_photo_listed", "RUL-disagreeing_tracks_place_nothing", "BLD-gps_decisions_record",
                  test="TST-geotag_gps_decisions-an_unplaced_photo_is_listed_with_why")
def test_an_unplaced_photo_is_listed_with_why_the_tracks_did_not_place_it(tmp_path):
    """Every photo no source places is listed by itself with why the tracks placed nothing — how far the nearest
    track point is in time — and tracks that cover its time in different places are named, even where a folder
    fallback then places the photo and would hide it."""
    wf, d = _wf(tmp_path), f"{BYDEST}/T"
    files = [_fp_file(f"{d}/late.arw", d, "fp-l")]
    art, _ = _build(wf, files, [_row(f"{d}/late.arw", "2024-07-03T13:01:00Z")], _gpx())    # an hour past the track
    item = _dd(art, d)["gps_decisions"]["review_items"][0]
    assert item["reason"] == "no_reliable_gps_source" and item["tracks"] == {"reason": "outside_track", "seconds_from_track": 3600}
    assert "track_disagreements" not in art
    two = cal.GPXIndex("")
    two.points = [cal.GPXPoint(50.0, 4.0, datetime(2024, 7, 3, 12, 0, s, tzinfo=timezone.utc), "mine.gpx", s) for s in (0, 30)] + \
                 [cal.GPXPoint(51.0, 5.0, datetime(2024, 7, 3, 12, 0, s, tzinfo=timezone.utc), "theirs.gpx", s) for s in (10, 40)]
    prior = {"destinations": {d: {"folder_fallback": {"user_decision": {"fallback_lat": 50.5, "fallback_lon": 4.5}}}}}
    art, _ = _build(wf, [_fp_file(f"{d}/x.arw", d, "fp-x")], [_row(f"{d}/x.arw", "2024-07-03T12:00:20Z")], two, prior)
    assert _dd(art, d)["gps_decisions"]["summary"]["automatic_folder_fallback"] == 1       # the fallback placed it
    assert art["track_disagreements"] == [{"gpx_files": ["mine.gpx", "theirs.gpx"], "photos": 1}]
