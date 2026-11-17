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

"""Phase 5b (geotag) — the BLD-placement_order GPS decision tree +
photos-23-gps-decisions.json (BLD-gps_decisions_record).

Per-file classifier (preserve/manual-locked/interpolation/extrapolation/folder-fallback/blocked), the
per-destination summary artifact (paths only for review/blocker items and the photos the tracks or the fallback
place), and folder_fallback downward inheritance. Decision logic at full coverage. From conftest.py.
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

@pytest.mark.spec("BLD-placement_order", "RUL-own_position_kept", "RUL-placement_order", "RUL-unplaced_photo_waits",
                  test="TST-geotag_gps_decisions-classify_all_branches")
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
    assert cal.classify_gps(_file("a", "d"), None, g, cfg, None, {})[0] == "blocked"   # waits: never left unplaced


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


@pytest.mark.spec("BLD-decision_record_envelope", test="TST-geotag_gps_decisions-what_photos_23_depends_on")
def test_what_photos_23_depends_on(tmp_path):
    """photos-23's `depends_on`: the resolved-UTC fingerprint, the tracks', the nine placement settings' with the
    distance that contradicts a photo's own position, and the handoff's content fingerprint — and nothing else."""
    wf = _wf(tmp_path)
    art, _ = _build(wf, [_file(f"{BYDEST}/T/n.jpg", f"{BYDEST}/T", native=True)], [], _gpx())
    dep = art["depends_on"]
    assert set(dep) == {"resolved_utc_cache_fingerprint", "gpx_fingerprint", "gps_policy_fingerprint", "handoff"}
    nine = ("gpx_direct_match_max_seconds", "gpx_interpolation_max_gap_seconds",
            "gpx_interpolation_max_distance_meters", "gpx_interpolation_max_speed_kmh",
            "gpx_extrapolation_max_seconds", "gpx_extrapolation_heading_seconds",
            "gpx_extrapolation_max_distance_meters", "gpx_extrapolation_max_speed_kmh",
            "gpx_tracks_agree_max_distance_meters", "gpx_own_position_contradicted_distance_meters")
    assert dep["gps_policy_fingerprint"] == utils.sha256_text(
        json.dumps({k: utils.CONFIG[k] for k in nine}, sort_keys=True))
    assert dep["handoff"]["content_fingerprint"] == utils.handoff_content_fingerprint({})


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


@pytest.mark.parametrize("value", [True, False])
@pytest.mark.spec("RUL-unknown_decision_field_refused", "BLD-geotag_checks_decisions", "RUL-unplaced_photo_waits",
                  test="TST-geotag_gps_decisions-leave_unlocated_is_refused_as_an_unknown_field")
def test_leave_unlocated_is_refused_as_an_unknown_field(tmp_path, value):
    """A photo is never left without a position: `accept_unlocated`, in a photos-23 still holding it, is a field a
    position decision does not have — refused, named, the record left as it is — whatever its value."""
    wf = _wf(tmp_path)
    d = f"{BYDEST}/Trip"
    prior = {"destinations": {d: {"gps_decisions": {"review_items": [
        {"relative_path": f"{d}/b.jpg", "user_decision": {"accept_unlocated": value}}]}}}}
    art, blk = _build(wf, [_file(f"{d}/b.jpg", d)], [], _gpx(), prior)
    assert art is None
    assert blk == [f"{d}/b.jpg: user_decision.accept_unlocated is not a field of a photo's position decision "
                   "(only manual_lat and manual_lon) — remove it."]
    art, blk = _build(wf, [_file(f"{d}/b.jpg", d)], [], _gpx(), None)
    (item,) = _dd(art, d)["gps_decisions"]["review_items"]
    assert item["user_decision"] == {"manual_lat": "", "manual_lon": ""} and item["requires_user_input"]
    assert "no_gps_change_needed" not in _dd(art, d)["gps_decisions"]["summary"]


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


@pytest.mark.spec("RUL-fallback_from_nearest", "RUL-inherited_fallback_applies", "BLD-folder_fallback_cell",
                  test="TST-geotag_gps_decisions-child_inherits_parent_fallback")
def test_child_inherits_parent_fallback(tmp_path):
    # The parent's fallback applies itself beneath it, unasked: the child shows it as inherited, naming the parent,
    # and its photos nothing else places take it.
    wf = _wf(tmp_path)
    p, c = f"{BYDEST}/Trip", f"{BYDEST}/Trip/Sub"
    files = [_file(f"{p}/a.jpg", p), _file(f"{c}/b.jpg", c)]
    art, _ = _build(wf, files, [], _gpx(), _with_fallback(p, 10.0, 20.0))
    pfb = _dd(art, p)["folder_fallback"]
    assert pfb["effective_fallback"] == {"lat": 10.0, "lon": 20.0} and pfb["fallback_source"] == "own"
    cfb = _dd(art, c)["folder_fallback"]
    assert cfb["inherited_fallback"] == {"lat": 10.0, "lon": 20.0, "from": p}
    assert cfb["effective_fallback"] == {"lat": 10.0, "lon": 20.0}
    assert cfb["fallback_source"] == "inherited" and cfb["inherited_from"] == p
    assert cfb["user_decision"] == {"fallback_lat": "", "fallback_lon": ""}       # nothing to accept
    assert _dd(art, c)["gps_decisions"]["summary"]["automatic_folder_fallback"] == 1
    assert art["status"] == "complete"


@pytest.mark.spec("RUL-written_fallback_over_inherited", "RUL-fallback_from_nearest", "BLD-folder_fallback_cell",
                  test="TST-geotag_gps_decisions-written_fallback_outranks_the_inherited")
def test_written_fallback_outranks_the_inherited(tmp_path):
    # A fallback written at the child outranks the one it inherits, for every photo there the fallback places, and is
    # the one the destinations beneath inherit; emptied, the child inherits again.
    wf = _wf(tmp_path)
    p, c, gc = f"{BYDEST}/Trip", f"{BYDEST}/Trip/Sub", f"{BYDEST}/Trip/Sub/Deep"
    files = [_file(f"{p}/a.jpg", p), _file(f"{c}/b.jpg", c), _file(f"{c}/b2.jpg", c), _file(f"{gc}/d.jpg", gc)]
    prior = {"destinations": {
        p: {"folder_fallback": {"user_decision": {"fallback_lat": 10.0, "fallback_lon": 20.0}}},
        c: {"folder_fallback": {"user_decision": {"fallback_lat": 30.0, "fallback_lon": 40.0}}}}}
    art, _ = _build(wf, files, [], _gpx(), prior)
    cfb = _dd(art, c)["folder_fallback"]
    assert cfb["effective_fallback"] == {"lat": 30.0, "lon": 40.0} and cfb["fallback_source"] == "own"
    assert cfb["inherited_fallback"] == {"lat": 10.0, "lon": 20.0, "from": p}   # what emptying it returns to
    assert _dd(art, c)["gps_decisions"]["summary"]["automatic_folder_fallback"] == 2
    gfb = _dd(art, gc)["folder_fallback"]
    assert gfb["inherited_from"] == c and gfb["effective_fallback"] == {"lat": 30.0, "lon": 40.0}
    prior["destinations"][c]["folder_fallback"]["user_decision"] = {"fallback_lat": "", "fallback_lon": ""}
    art, _ = _build(wf, files, [], _gpx(), prior)
    assert _dd(art, c)["folder_fallback"]["effective_fallback"] == {"lat": 10.0, "lon": 20.0}
    assert _dd(art, c)["folder_fallback"]["fallback_source"] == "inherited"
    assert _dd(art, gc)["folder_fallback"]["inherited_from"] == p


def test_grandchild_skips_to_nearest_resolved_ancestor(tmp_path):
    # the child, given no fallback of its own, passes on the one it inherits: the grandchild's comes from the parent
    wf = _wf(tmp_path)
    p, c, gc = f"{BYDEST}/Trip", f"{BYDEST}/Trip/Sub", f"{BYDEST}/Trip/Sub/Deep"
    files = [_file(f"{p}/a.jpg", p), _file(f"{c}/b.jpg", c), _file(f"{gc}/d.jpg", gc)]
    art, _ = _build(wf, files, [], _gpx(), _with_fallback(p, 10.0, 20.0))   # only p written
    assert _dd(art, c)["folder_fallback"]["inherited_from"] == p
    assert _dd(art, gc)["folder_fallback"]["inherited_from"] == p
    assert _dd(art, gc)["folder_fallback"]["effective_fallback"] == {"lat": 10.0, "lon": 20.0}


def test_sibling_fallback_does_not_leak(tmp_path):
    wf = _wf(tmp_path)
    a, b = f"{BYDEST}/Trip/A", f"{BYDEST}/Trip/B"
    files = [_file(f"{a}/x.jpg", a), _file(f"{b}/y.jpg", b)]
    art, _ = _build(wf, files, [], _gpx(), _with_fallback(a, 10.0, 20.0))
    bfb = _dd(art, b)["folder_fallback"]
    assert bfb["inherited_fallback"] is None and bfb["effective_fallback"] is None and bfb["fallback_source"] == "none"


@pytest.mark.spec("RUL-inherited_fallback_applies", "BLD-folder_fallback_cell",
                  test="TST-geotag_gps_decisions-an_inherited_fallback_follows_the_parent")
def test_an_inherited_fallback_follows_the_parent(tmp_path):
    # The parent's fallback changed, the child that writes none of its own follows it, unasked.
    wf = _wf(tmp_path)
    p, c = f"{BYDEST}/Trip", f"{BYDEST}/Trip/Sub"
    files = [_file(f"{p}/a.jpg", p), _file(f"{c}/b.jpg", c)]
    art, _ = _build(wf, files, [], _gpx(), _with_fallback(p, 10.0, 20.0))
    assert _dd(art, c)["folder_fallback"]["effective_fallback"] == {"lat": 10.0, "lon": 20.0}
    art["destinations"][p]["folder_fallback"]["user_decision"] = {"fallback_lat": 11.0, "fallback_lon": 21.0}
    art, _ = _build(wf, files, [], _gpx(), art)
    cfb = _dd(art, c)["folder_fallback"]
    assert cfb["effective_fallback"] == {"lat": 11.0, "lon": 21.0} and cfb["fallback_source"] == "inherited"


@pytest.mark.spec("RUL-fallback_placements_told", "BLD-fallback_placements_printed",
                  test="TST-geotag_gps_decisions-fallback_placements_told_per_destination")
def test_fallback_placements_told_per_destination(tmp_path):
    # Per destination, how many photos the folder fallback placed and whose fallback it is — the destination's own,
    # or inherited, naming the destination it comes from — in photos-23 and in what `geotag plan` prints.
    wf = _wf(tmp_path)
    p, c, o = f"{BYDEST}/Trip", f"{BYDEST}/Trip/Sub", f"{BYDEST}/Other"
    files = [_file(f"{p}/a.jpg", p), _file(f"{c}/b.jpg", c), _file(f"{c}/b2.jpg", c),
             _file(f"{o}/n.jpg", o, native=True)]
    art, _ = _build(wf, files, [], _gpx(), _with_fallback(p, 10.0, 20.0))
    assert _dd(art, c)["gps_decisions"]["summary"]["automatic_folder_fallback"] == 2
    assert (_dd(art, c)["folder_fallback"]["fallback_source"], _dd(art, c)["folder_fallback"]["inherited_from"]) == \
        ("inherited", p)
    assert cal.fallback_placement_lines(art) == [
        f"  {p}: 1 photo(s) placed by its own fallback.",
        f"  {c}: 2 photo(s) placed by the fallback inherited from {p}."]


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


@pytest.mark.spec("RUL-fallback_optional", "BLD-folder_fallback_cell", "RUL-unplaced_photo_waits",
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
                  "RUL-photo_decision_never_passes_by_name", "RUL-decision_kept",
                  test="TST-geotag_gps_decisions-a_photo_s_decision_follows_it_through_its_rename")
def test_a_photo_s_decision_follows_it_through_its_rename(tmp_path):
    """A position the user set for one photo is that photo's — found again by its fingerprint once geotag has renamed
    it, never lost with the old name (nor given to another photo that takes the name)."""
    wf, d = _wf(tmp_path), f"{BYDEST}/T"
    before = [_fp_file(f"{d}/a.arw", d, "fp-a"), _fp_file(f"{d}/b.arw", d, "fp-b")]
    rows = [_row(f"{d}/a.arw", "2024-07-03T20:00:00Z"), _row(f"{d}/b.arw", "2024-07-03T21:00:00Z")]   # off the track
    art, _ = _build(wf, before, rows, _gpx())
    items = {ri["relative_path"]: ri for ri in _dd(art, d)["gps_decisions"]["review_items"]}
    assert items[f"{d}/a.arw"]["content_fingerprint"] == "fp-a" and items[f"{d}/a.arw"]["requires_user_input"]
    items[f"{d}/a.arw"]["user_decision"].update(manual_lat=51.5, manual_lon=4.5)
    items[f"{d}/b.arw"]["user_decision"].update(manual_lat=51.6, manual_lon=4.6)
    # execute renamed both; a new photo took a.arw's old name
    after = [_fp_file(f"{d}/2024-07-03--22-00-00.arw", d, "fp-a"), _fp_file(f"{d}/2024-07-03--23-00-00.arw", d, "fp-b"),
             _fp_file(f"{d}/a.arw", d, "fp-new")]
    rows2 = [_row(after[0]["relative_path"], "2024-07-03T20:00:00Z"), _row(after[1]["relative_path"], "2024-07-03T21:00:00Z"),
             _row(f"{d}/a.arw", "2024-07-03T19:00:00Z")]
    art2, blk = _build(wf, after, rows2, _gpx(), art)
    assert not blk
    got = {ri["content_fingerprint"]: ri for ri in _dd(art2, d)["gps_decisions"]["review_items"]}
    assert got["fp-a"]["reason"] == "manual_locked" and got["fp-a"]["user_decision"]["manual_lat"] == 51.5
    assert got["fp-b"]["reason"] == "manual_locked" and got["fp-b"]["user_decision"]["manual_lat"] == 51.6
    assert got["fp-new"]["requires_user_input"] and got["fp-new"]["user_decision"]["manual_lat"] == ""
    # a fingerprint taken again with a new value: the decision follows through the pin's key
    retaken = [dict(_fp_file(after[0]["relative_path"], d, "fp-a2"), original_key="fp-a")]
    art3, _ = _build(wf, retaken, rows2[:1], _gpx(), art2)
    assert _dd(art3, d)["gps_decisions"]["review_items"][0]["reason"] == "manual_locked"


@pytest.mark.spec("RUL-moved_photo_position_decided_anew", "BLD-review_item_identity",
                  test="TST-geotag_gps_decisions-a_moved_photo_s_position_is_decided_anew")
def test_a_moved_photo_s_position_is_decided_anew(tmp_path):
    """A position typed for a photo was given for the folder it lay in: moved to another destination — or its folder
    renamed — the photo is asked again, though its fingerprint would find the old answer."""
    wf, a, b, renamed = _wf(tmp_path), f"{BYDEST}/A", f"{BYDEST}/B", f"{BYDEST}/A2"
    off = "2024-07-03T20:00:00Z"                                               # off the track: asks
    files = [_fp_file(f"{a}/p.arw", a, "fp-p"), _fp_file(f"{a}/u.arw", a, "fp-u")]
    art, _ = _build(wf, files, [_row(f"{a}/p.arw", off), _row(f"{a}/u.arw", off)], _gpx())
    items = {ri["content_fingerprint"]: ri for ri in _dd(art, a)["gps_decisions"]["review_items"]}
    items["fp-p"]["user_decision"].update(manual_lat=51.5, manual_lon=4.5)
    items["fp-u"]["user_decision"].update(manual_lat=51.6, manual_lon=4.6)
    art, _ = _build(wf, files, [_row(f"{a}/p.arw", off), _row(f"{a}/u.arw", off)], _gpx(), art)
    assert {ri["reason"] for ri in _dd(art, a)["gps_decisions"]["review_items"]} == {"manual_locked"}
    # one photo moved to B, the other's folder renamed: both asked again, nothing of A's answers with them
    moved = [_fp_file(f"{b}/p.arw", b, "fp-p"), _fp_file(f"{renamed}/u.arw", renamed, "fp-u")]
    art2, blk = _build(wf, moved, [_row(f"{b}/p.arw", off), _row(f"{renamed}/u.arw", off)], _gpx(), art)
    assert not blk
    for dest in (b, renamed):
        (item,) = _dd(art2, dest)["gps_decisions"]["review_items"]
        assert item["reason"] == "no_reliable_gps_source" and item["requires_user_input"]
        assert item["user_decision"] == {"manual_lat": "", "manual_lon": ""}


@pytest.mark.spec("RUL-unplaced_photo_listed", "RUL-disagreeing_tracks_place_nothing", "BLD-gps_decisions_record",
                  "RUL-disagreeing_tracks_named", "RUL-unplaced_photo_says_why",
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


# --- a position chosen for a photo the tracks or the fallback place ---------------------------------------------

@pytest.mark.spec("BLD-chosen_position", "BLD-gps_decisions_record", "BLD-placed_photos", "RUL-fallback_photo_says_why",
                  test="TST-geotag_gps_decisions-photos_23_lists_the_photos_tracks_and_fallback_place")
def test_photos_23_lists_the_photos_tracks_and_fallback_place(tmp_path):
    """photos-23 names, per destination, each photo no review item names and how it is placed: by its own position, by
    the tracks (with the track's method) or by the folder fallback (with why the tracks did not place it) — each with
    its camera's day as photos-21 keys its offset cell. A photo that waits is a review item, not among them."""
    wf, d = _wf(tmp_path), f"{BYDEST}/T"
    cam = "SONY|A7|1"
    files = [dict(_fp_file(f"{d}/t.arw", d, "fp-t"), camera_group_key=cam, source_naive_time="2024:07:03 14:00:30"),
             dict(_fp_file(f"{d}/f.arw", d, "fp-f"), camera_group_key=cam, source_naive_time="2024:07:03 22:00:00"),
             dict(_file(f"{d}/n.arw", d, native=True), content_fingerprint="fp-n", camera_group_key="PHONE")]
    rows = [_row(f"{d}/t.arw", "2024-07-03T12:00:30Z"), _row(f"{d}/f.arw", "2024-07-03T20:00:00Z")]
    time = {"destinations": {d: {"camera_group_time_decisions": {cam: {}}}}}
    art = wf.build_gps_decisions(files, rows, _gpx(), _with_fallback(d, 50.5, 4.5), "rfp", time_decisions=time)[0]
    assert _dd(art, d)["gps_decisions"]["placed_photos"] == [
        {"relative_path": f"{d}/f.arw", "content_fingerprint": "fp-f", "placed_by": "folder_fallback",
         "tracks": {"reason": "outside_track", "seconds_from_track": 28740}, "camera_bucket": cam},
        {"relative_path": f"{d}/n.arw", "content_fingerprint": "fp-n", "placed_by": "own_position"},
        {"relative_path": f"{d}/t.arw", "content_fingerprint": "fp-t", "placed_by": "tracks", "method": "direct_match",
         "camera_bucket": cam}]
    time["destinations"][d]["camera_group_time_decisions"] = {f"{cam}@2024-07-03": {}, f"{cam}@2024-07-04": {}}
    art = wf.build_gps_decisions(files[1:2], rows[1:], _gpx(), None, "rfp", time_decisions=time)[0]
    assert _dd(art, d)["gps_decisions"]["review_items"][0]["camera_bucket"] == f"{cam}@2024-07-03"   # by its day
    assert "placed_photos" not in _dd(art, d)["gps_decisions"]


def _chosen(dest, rel, lat, lon):
    return {"destinations": {dest: {"gps_decisions": {"review_items": [
        {"relative_path": rel, "reason": "chosen_by_user", "user_decision": {"manual_lat": lat, "manual_lon": lon}}]}}}}


@pytest.mark.parametrize("by", ["tracks", "folder_fallback"])
@pytest.mark.spec("RUL-chosen_position_honoured", "BLD-chosen_position", "RUL-placement_order",
                  test="TST-geotag_gps_decisions-a_position_chosen_for_a_placed_photo_places_it")
def test_a_position_chosen_for_a_placed_photo_places_it(tmp_path, by):
    """An entry the user adds by hand — the photo's path, `chosen_by_user`, a position — for a photo the tracks or the
    fallback place is honoured: the photo is placed there as `manual_locked`, out of the placed list."""
    wf, d = _wf(tmp_path), f"{BYDEST}/T"
    utc = "2024-07-03T12:00:30Z" if by == "tracks" else "2024-07-03T20:00:00Z"
    files, rows = [_fp_file(f"{d}/p.arw", d, "fp-p")], [_row(f"{d}/p.arw", utc)]
    prior = _chosen(d, f"{d}/p.arw", 48.0, 2.0)
    prior["destinations"][d]["folder_fallback"] = {"user_decision": {"fallback_lat": 50.5, "fallback_lon": 4.5}}
    art, blk = _build(wf, files, rows, _gpx(), prior)
    assert not blk and art["status"] == "complete"
    gd = _dd(art, d)["gps_decisions"]
    (item,) = gd["review_items"]
    assert (item["reason"], item["user_decision"], item["requires_user_input"]) == (
        "manual_locked", {"manual_lat": 48.0, "manual_lon": 2.0}, False)
    assert gd["summary"]["manual_locked"] == 1 and "placed_photos" not in gd
    ru = datetime(2024, 7, 3, 12, 0, 30, tzinfo=timezone.utc) if by == "tracks" else None
    assert cal.classify_gps(files[0], ru, _gpx(), utils.CONFIG, {"lat": 50.5, "lon": 4.5},
                            item["user_decision"]) == ("manual_locked", {"lat": 48.0, "lon": 2.0})


@pytest.mark.spec("RUL-chosen_position_kept", "BLD-chosen_position",
                  test="TST-geotag_gps_decisions-a_position_given_for_one_photo_is_kept_while_it_holds_one")
def test_a_position_given_for_one_photo_is_kept_while_it_holds_one(tmp_path):
    """A position given for one photo stays its own while it holds one — after tracks, then a fallback, come to place
    the photo — and only once the user empties it do the tracks place it again, its item gone."""
    wf, d = _wf(tmp_path), f"{BYDEST}/T"
    files = [_fp_file(f"{d}/p.arw", d, "fp-p")]
    off, on = [_row(f"{d}/p.arw", "2024-07-03T20:00:00Z")], [_row(f"{d}/p.arw", "2024-07-03T12:00:30Z")]
    art, _ = _build(wf, files, off, _gpx())                             # nothing places it: it asks
    _dd(art, d)["gps_decisions"]["review_items"][0]["user_decision"].update(manual_lat=48.0, manual_lon=2.0)
    art, _ = _build(wf, files, on, _gpx(), art)                         # the tracks now cover its time
    art["destinations"][d]["folder_fallback"]["user_decision"].update(fallback_lat=50.5, fallback_lon=4.5)
    art, _ = _build(wf, files, on, _gpx(), art)                         # ... and a fallback is set
    (item,) = _dd(art, d)["gps_decisions"]["review_items"]
    assert item["reason"] == "manual_locked" and item["user_decision"] == {"manual_lat": 48.0, "manual_lon": 2.0}
    item["user_decision"].update(manual_lat="", manual_lon="")
    art, _ = _build(wf, files, on, _gpx(), art)
    gd = _dd(art, d)["gps_decisions"]
    assert gd["review_items"] == [] and gd["placed_photos"][0]["placed_by"] == "tracks"


@pytest.mark.parametrize("rel, why", [("6-photos-by-dest/T/gone.arw", "names no photo of this destination"),
                                      ("6-photos-by-dest/U/q.arw", "names no photo of this destination"),
                                      ("6-photos-by-dest/T/n.arw", "holds a position of its own")])
@pytest.mark.spec("RUL-chosen_position_names_a_photo", "BLD-chosen_position", "RUL-invalid_value_located",
                  test="TST-geotag_gps_decisions-a_chosen_position_naming_no_photo_to_place_is_refused")
def test_a_chosen_position_naming_no_photo_to_place_is_refused(tmp_path, rel, why):
    """A position chosen for a photo names one of its destination's photos holding no position of its own — or the run
    stops on it, naming it: a photo not there, one of another destination, one whose own position geotag keeps."""
    wf, d = _wf(tmp_path), f"{BYDEST}/T"
    files = [_fp_file(f"{d}/p.arw", d, "fp-p"), dict(_file(f"{d}/n.arw", d, native=True), content_fingerprint="fp-n"),
             _fp_file(f"{BYDEST}/U/q.arw", f"{BYDEST}/U", "fp-q")]
    _, blk = _build(wf, files, [_row(f"{d}/p.arw", "2024-07-03T12:00:30Z")], _gpx(), _chosen(d, rel, 48.0, 2.0))
    assert len(blk) == 1 and f"review_items[{rel}]" in blk[0] and why in blk[0], blk


@pytest.mark.parametrize("fp, why", [("fp-stale", "names no photo of this destination"),
                                     ("fp-o", "names another photo than its path")])
@pytest.mark.spec("RUL-chosen_position_names_a_photo", "BLD-chosen_position",
                  test="TST-geotag_gps_decisions-a_chosen_position_s_fingerprint_names_its_photo")
def test_a_chosen_position_whose_fingerprint_names_no_photo_or_another_is_refused(tmp_path, fp, why):
    """An entry whose path names a photo but whose fingerprint names none of the destination's — or another one — would
    be found by neither and the user's position dropped unseen: it stops the run, naming it."""
    wf, d = _wf(tmp_path), f"{BYDEST}/T"
    files = [_fp_file(f"{d}/p.arw", d, "fp-p"), _fp_file(f"{d}/o.arw", d, "fp-o")]
    prior = _chosen(d, f"{d}/p.arw", 48.0, 2.0)
    prior["destinations"][d]["gps_decisions"]["review_items"][0]["content_fingerprint"] = fp
    _, blk = _build(wf, files, [_row(f"{d}/p.arw", "2024-07-03T12:00:30Z")], _gpx(), prior)
    assert len(blk) == 1 and f"review_items[{d}/p.arw]" in blk[0] and why in blk[0], blk
