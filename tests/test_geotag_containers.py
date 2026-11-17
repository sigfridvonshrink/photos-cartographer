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

"""Phase 3/5 (geotag) — file-less CONTAINER destinations.

A folder that holds only sub-destinations (no media of its own) is still materialized as a
destination so a human can author timezone / GPS-fallback decisions on it that propagate DOWN to its
children. Such a container:
  * never blocks and stays off the to-do list (it has no media to act on);
  * auto-resolves its timezone by inheritance, while remaining overridable, and propagates a manual
    GPS fallback downward.
Clock OFFSETS, by contrast, do NOT inherit or aggregate (RUL-offset_from_own_evidence): a container exposes NO offset
cells (it has no media to time-correct and offsets never cross destinations). From conftest.py.
"""
import photos_2_geotag as cal
import photos_utils as utils
from datetime import datetime, timezone
import pytest

BYDEST = "6-photos-by-dest"
CAM = "SONY|ILCE-6400|123"
CAM2 = "CANON|EOS-5D|999"
GROUPS = {CAM: {"camera_group_class": "camera"}, CAM2: {"camera_group_class": "camera"}}


def _wf(tmp_path):
    ws = tmp_path / "ws"
    (ws / ".photos-ingest").mkdir(parents=True)
    (ws / ".photos-ingest" / "photos-11-handoff.json").write_text("{}")
    wf = cal.GeotagWorkflow(str(ws))
    wf._gpx_fingerprint = "fp"
    return wf


def _gpx():
    idx = cal.GPXIndex("")
    idx.points = []
    return idx


def _tfile(rel, dest, *, key=CAM, naive="2024:07:03 14:00:00"):
    return {"relative_path": rel, "destination": dest, "camera_group_key": key,
            "native_gps": None, "has_native_gps": False, "has_timestamp": True,
            "source_naive_time": naive}


def _gfile(rel, dest):
    return {"relative_path": rel, "destination": dest, "has_native_gps": False}


# --- enumeration -------------------------------------------------------------

@pytest.mark.spec("DEF-container_destination", "RUL-container_never_waits", test="TST-geotag_containers-container_materialized_with_no_offset_cells")
def test_container_materialized_with_no_offset_cells(tmp_path):
    wf = _wf(tmp_path)
    # CAM lives under Trip/Day1; CAM2 lives two levels down under Trip/Day2/Sub.
    files = [_tfile(f"{BYDEST}/Trip/Day1/a.arw", f"{BYDEST}/Trip/Day1", key=CAM),
             _tfile(f"{BYDEST}/Trip/Day2/Sub/b.arw", f"{BYDEST}/Trip/Day2/Sub", key=CAM2)]
    art, _ = wf.build_time_decisions(files, GROUPS, None, _gpx())
    d = art["destinations"]
    # every ancestor folder is materialized and flagged file-less
    for c in (BYDEST, f"{BYDEST}/Trip", f"{BYDEST}/Trip/Day2"):
        assert d[c]["file_less"] is True
        # containers hold NO offset cells (RUL-offset_per_camera_destination_day)
        assert d[c]["camera_group_time_decisions"] == {}
    # real leaves are not file-less and carry their own group's cell
    assert "file_less" not in d[f"{BYDEST}/Trip/Day1"]
    assert set(d[f"{BYDEST}/Trip/Day1"]["camera_group_time_decisions"]) == {CAM}
    assert set(d[f"{BYDEST}/Trip/Day2/Sub"]["camera_group_time_decisions"]) == {CAM2}


@pytest.mark.spec("RUL-container_never_waits", test="TST-geotag_containers-containers_never_block")
def test_containers_never_block(tmp_path):
    # Nothing below waiting for a zone, a container asks for nothing: no zone, no offset, no fallback.
    wf = _wf(tmp_path)
    files = [_tfile(f"{BYDEST}/Trip/Day1/a.arw", f"{BYDEST}/Trip/Day1")]
    prior = {"destinations": {f"{BYDEST}/Trip/Day1": {"destination_timezone":
             {"user_decision": {"manual_iana_timezone": "Asia/Tokyo"}}}}}
    art, _ = wf.build_time_decisions(files, GROUPS, prior, _gpx())
    trip = art["destinations"][f"{BYDEST}/Trip"]
    assert trip["destination_timezone"]["requires_user_input"] is False
    assert "asked_for" not in trip["destination_timezone"]
    assert trip["camera_group_time_decisions"] == {}         # no offset cell to block on
    gps, _ = wf.build_gps_decisions([_gfile(f"{BYDEST}/Trip/Day1/a.jpg", f"{BYDEST}/Trip/Day1")], [], _gpx(), None, "rfp")
    assert gps["destinations"][f"{BYDEST}/Trip"]["folder_fallback"]["requires_user_input"] is False


# --- auto-resolve + propagation ----------------------------------------------

@pytest.mark.spec("RUL-timezone_from_nearest", "RUL-default_zone_proposed_only", "BLD-timezone_cell",
                  "RUL-no_timezone_to_inherit_waits", "RUL-timezone_auto_resolves",
                  test="TST-geotag_containers-the_default_zone_is_proposed_and_an_answer_cascades")
def test_the_default_zone_is_proposed_and_an_answer_cascades(tmp_path):
    # The configured default is the user's usual zone, true of no trip in particular: it is proposed, never applied —
    # a folder holding a trip is no exception, asked as the destination waiting in it is; once answered there,
    # everything beneath inherits it without asking.
    utils.CONFIG["camera_time_and_timezone_policy"]["default_folder_timezone"] = "Europe/Brussels"
    wf = _wf(tmp_path)
    files = [_tfile(f"{BYDEST}/Trip/Day1/a.arw", f"{BYDEST}/Trip/Day1")]
    art, _ = wf.build_time_decisions(files, GROUPS, None, _gpx())
    trip = art["destinations"][f"{BYDEST}/Trip"]["destination_timezone"]
    assert trip["proposal_source"] == "config_default" and trip["effective_iana_timezone"] == ""
    assert trip["requires_user_input"] is True and trip["asked_for"] == [f"{BYDEST}/Trip/Day1"]
    leaf = art["destinations"][f"{BYDEST}/Trip/Day1"]["destination_timezone"]
    assert leaf["proposal_source"] == "config_default" and leaf["requires_user_input"] is True
    prior = {"destinations": {f"{BYDEST}/Trip": {"destination_timezone":
             {"user_decision": {"manual_iana_timezone": "Asia/Tokyo"}}}}}
    art, _ = wf.build_time_decisions(files, GROUPS, prior, _gpx())
    leaf = art["destinations"][f"{BYDEST}/Trip/Day1"]["destination_timezone"]
    assert leaf["effective_iana_timezone"] == "Asia/Tokyo" and leaf["decision_mode"] == "auto_resolved"
    assert leaf["requires_user_input"] is False
    assert not any(d["destination_timezone"]["requires_user_input"] for d in art["destinations"].values())


@pytest.mark.spec("RUL-timezone_from_nearest", "BLD-timezone_cell", "RUL-no_timezone_to_inherit_waits",
                  test="TST-geotag_containers-manual_timezone_reroots_the_chain")
def test_manual_timezone_reroots_the_chain(tmp_path):
    # A zone set by hand on a trip's folder becomes what every destination beneath it inherits — over the
    # configured default — while a destination outside that trip is offered the default, and asks.
    utils.CONFIG["camera_time_and_timezone_policy"]["default_folder_timezone"] = "Europe/Brussels"
    wf = _wf(tmp_path)
    files = [_tfile(f"{BYDEST}/Japan/Kyoto/a.arw", f"{BYDEST}/Japan/Kyoto"),
             _tfile(f"{BYDEST}/Home/b.arw", f"{BYDEST}/Home")]
    prior = {"destinations": {f"{BYDEST}/Japan": {"destination_timezone":
             {"user_decision": {"manual_iana_timezone": "Asia/Tokyo"}}}}}
    art, blk = wf.build_time_decisions(files, GROUPS, prior, _gpx())
    assert blk == []
    japan = art["destinations"][f"{BYDEST}/Japan"]["destination_timezone"]
    assert japan["effective_iana_timezone"] == "Asia/Tokyo" and "decision_mode" not in japan
    kyoto = art["destinations"][f"{BYDEST}/Japan/Kyoto"]["destination_timezone"]
    assert kyoto["effective_iana_timezone"] == "Asia/Tokyo"
    assert kyoto["proposal_source"] == "inherited" and kyoto["inherited_from"] == f"{BYDEST}/Japan"
    home = art["destinations"][f"{BYDEST}/Home"]["destination_timezone"]
    assert home["proposed_iana_timezone"] == "Europe/Brussels" and home["proposal_source"] == "config_default"
    assert home["effective_iana_timezone"] == "" and home["requires_user_input"] is True


@pytest.mark.spec("RUL-moved_photo_decided_anew", test="TST-geotag_containers-moved_photo_takes_its_new_destinations_offset")
def test_moved_photo_takes_its_new_destinations_offset(tmp_path):
    # A photo re-sorted from A into B is decided under B: B's clock offset for the camera that day, never A's.
    utils.CONFIG["camera_time_and_timezone_policy"]["default_folder_timezone"] = "Europe/Brussels"
    wf = _wf(tmp_path)
    prior = {"destinations": {
        f"{BYDEST}/A": {"camera_group_time_decisions": {CAM: {"user_decision": {"manual_offset_seconds": -3600}}}},
        f"{BYDEST}/B": {"camera_group_time_decisions": {CAM: {"user_decision": {"manual_offset_seconds": 600}}}}}}
    before = [_tfile(f"{BYDEST}/A/x.arw", f"{BYDEST}/A"), _tfile(f"{BYDEST}/B/y.arw", f"{BYDEST}/B")]
    art, _ = wf.build_time_decisions(before, GROUPS, prior, _gpx())
    rows = {r["relative_path"]: r for r in cal.compute_resolved_utc(before, GROUPS, art)}
    assert rows[f"{BYDEST}/A/x.arw"]["utc_offset_used"] == -3600
    after = [_tfile(f"{BYDEST}/B/x.arw", f"{BYDEST}/B"), _tfile(f"{BYDEST}/B/y.arw", f"{BYDEST}/B")]
    art, _ = wf.build_time_decisions(after, GROUPS, art, _gpx())
    rows = {r["relative_path"]: r for r in cal.compute_resolved_utc(after, GROUPS, art)}
    assert rows[f"{BYDEST}/B/x.arw"]["utc_offset_used"] == 600
    assert rows[f"{BYDEST}/B/x.arw"]["resolved_utc"] == "2024-07-03T14:10:00Z"
    assert f"{BYDEST}/A" not in art["destinations"]                        # nothing of A remains


@pytest.mark.spec("RUL-moved_photo_decided_anew", test="TST-geotag_containers-moved_into_a_new_destination_takes_nothing_of_the_old")
def test_a_photo_moved_into_a_new_destination_takes_nothing_of_the_old(tmp_path):
    """A photo moved from A, where its camera's offset was written, into C, a destination no record knows: C is decided
    anew — it asks — and does not take A's offset."""
    wf = _wf(tmp_path)
    prior = {"destinations": {
        f"{BYDEST}/A": {"camera_group_time_decisions": {CAM: {"user_decision": {"manual_offset_seconds": -3600}}}}}}
    art, _ = wf.build_time_decisions([_tfile(f"{BYDEST}/A/x.arw", f"{BYDEST}/A")], GROUPS, prior, _gpx())
    assert art["destinations"][f"{BYDEST}/A"]["camera_group_time_decisions"][CAM]["effective_time_anchor"] == \
        {"offset_seconds": -3600, "source": "manual"}
    prior = {"destinations": {f"{BYDEST}/A": art["destinations"][f"{BYDEST}/A"]}}      # A's record, alone
    art, _ = wf.build_time_decisions([_tfile(f"{BYDEST}/C/x.arw", f"{BYDEST}/C")], GROUPS, prior, _gpx())
    cell = art["destinations"][f"{BYDEST}/C"]["camera_group_time_decisions"][CAM]
    assert cell["effective_time_anchor"] == "" and cell["requires_user_input"]
    assert cell["user_decision"].get("manual_offset_seconds") in ("", None)
    rows = {r["relative_path"]: r for r in cal.compute_resolved_utc([_tfile(f"{BYDEST}/C/x.arw", f"{BYDEST}/C")],
                                                                    GROUPS, art)}
    assert rows[f"{BYDEST}/C/x.arw"].get("utc_offset_used") != -3600


@pytest.mark.spec("RUL-offset_per_camera_destination_day", "RUL-offset_from_own_evidence", test="TST-geotag_containers-child_offset_decision_is_not_pooled_upward")
def test_child_offset_decision_is_not_pooled_upward(tmp_path):
    wf = _wf(tmp_path)
    files = [_tfile(f"{BYDEST}/Trip/Day1/a.arw", f"{BYDEST}/Trip/Day1")]
    prior = {"destinations": {f"{BYDEST}/Trip/Day1": {"camera_group_time_decisions":
             {CAM: {"user_decision": {"manual_offset_seconds": -3600}}}}}}
    art, _ = wf.build_time_decisions(files, GROUPS, prior, _gpx())
    # the child resolved from its own decision
    leaf = art["destinations"][f"{BYDEST}/Trip/Day1"]["camera_group_time_decisions"][CAM]
    assert leaf["effective_time_anchor"]["offset_seconds"] == -3600
    # the parent container exposes NO offset cell at all — offsets never aggregate upward (RUL-offset_from_own_evidence)
    assert art["destinations"][f"{BYDEST}/Trip"]["camera_group_time_decisions"] == {}


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
    assert child["fallback_source"] == "inherited" and child["inherited_from"] == f"{BYDEST}/Trip"
    assert child["effective_fallback"] == {"lat": 50.0, "lon": 4.0}


def test_determinism_with_containers(tmp_path):
    import json
    wf = _wf(tmp_path)
    files = [_tfile(f"{BYDEST}/Trip/Day1/a.arw", f"{BYDEST}/Trip/Day1", key=CAM),
             _tfile(f"{BYDEST}/Trip/Day2/Sub/b.arw", f"{BYDEST}/Trip/Day2/Sub", key=CAM2)]
    a1, _ = wf.build_time_decisions(files, GROUPS, None, _gpx())
    a2, _ = wf.build_time_decisions(files, GROUPS, a1, _gpx())
    assert json.dumps(a1, sort_keys=True) == json.dumps(a2, sort_keys=True)


# --- a timezone asked at every level (RUL-zone_asked_at_every_level) ------------------------------------------------

PHONE = "Apple|iPhone 15|"


def _tz(zone):
    return {"destination_timezone": {"user_decision": {"manual_iana_timezone": zone}}}


def _asking(art):
    """{destination: asked_for or True} for each timezone cell that asks, by its path below the by-dest root."""
    out = {}
    for d, v in art["destinations"].items():
        c = v["destination_timezone"]
        if c["requires_user_input"]:
            out[d[len(BYDEST) + 1:] or "."] = [a[len(BYDEST) + 1:] for a in c["asked_for"]] if "asked_for" in c else True
    return out


@pytest.mark.spec("RUL-zone_asked_at_every_level", "RUL-zone_not_asked_where_one_reaches", "BLD-zone_asked_at_containers",
                  "RUL-container_never_waits",
                  test="TST-geotag_containers-a_zone_is_asked_at_every_level")
def test_a_zone_is_asked_at_every_level(tmp_path):
    """Every folder with no zone above a destination waiting for one asks for it, naming the destinations an answer
    there would reach; answered at any of them, everything below takes it and nothing there asks again — answered at
    every destination, no folder above asks."""
    wf = _wf(tmp_path)
    files = [_tfile(f"{BYDEST}/Japan/Kyoto/a.arw", f"{BYDEST}/Japan/Kyoto"),
             _tfile(f"{BYDEST}/Japan/Tokyo/b.arw", f"{BYDEST}/Japan/Tokyo"),
             _tfile(f"{BYDEST}/Italy/Rome/c.arw", f"{BYDEST}/Italy/Rome")]
    art, blk = wf.build_time_decisions(files, GROUPS, None, _gpx())
    assert blk == []
    assert _asking(art) == {".": ["Italy/Rome", "Japan/Kyoto", "Japan/Tokyo"], "Japan": ["Japan/Kyoto", "Japan/Tokyo"],
                            "Italy": ["Italy/Rome"], "Japan/Kyoto": True, "Japan/Tokyo": True, "Italy/Rome": True}
    # answered on the country's folder: nothing in it asks; the folder above asks for what still waits
    art, _ = wf.build_time_decisions(files, GROUPS, {"destinations": {f"{BYDEST}/Japan": _tz("Asia/Tokyo")}}, _gpx())
    assert _asking(art) == {".": ["Italy/Rome"], "Italy": ["Italy/Rome"], "Italy/Rome": True}
    # answered on the destination itself: the folders above it ask no more
    prior = {"destinations": {f"{BYDEST}/Japan": _tz("Asia/Tokyo"), f"{BYDEST}/Italy/Rome": _tz("Europe/Rome")}}
    art, _ = wf.build_time_decisions(files, GROUPS, prior, _gpx())
    assert _asking(art) == {}
    # answered at the top: everything takes it
    art, _ = wf.build_time_decisions(files, GROUPS, {"destinations": {BYDEST: _tz("Europe/Brussels")}}, _gpx())
    assert _asking(art) == {}
    assert {v["destination_timezone"]["effective_iana_timezone"] for v in art["destinations"].values()} == {"Europe/Brussels"}


@pytest.mark.spec("RUL-zone_asked_at_every_level", "RUL-zone_not_asked_where_one_reaches", "BLD-zone_asked_at_containers",
                  "RUL-country_of_several_gives_none",
                  test="TST-geotag_containers-a_zone_is_asked_only_where_an_answer_reaches")
def test_a_zone_is_asked_only_where_an_answer_reaches(tmp_path):
    """A folder where a country of several timezones is said is not asked — a zone there passes to nothing — nor is
    any folder above it for what lies inside; the asking goes on inside it. A destination below a zone written lower
    down, waiting on its own photos, is no question for the folders above that zone."""
    wf = _wf(tmp_path)
    groups = dict(GROUPS, **{PHONE: {"camera_group_class": "smartphone"}})
    files = [_tfile(f"{BYDEST}/US/California/LA/a.arw", f"{BYDEST}/US/California/LA"),
             _tfile(f"{BYDEST}/US/California/SF/b.arw", f"{BYDEST}/US/California/SF"),
             dict(_tfile(f"{BYDEST}/Trip/Belgium/Ghent/p.jpg", f"{BYDEST}/Trip/Belgium/Ghent", key=PHONE),
                  source_time_tag="EXIF:DateTimeOriginal", raw_times={"OffsetTimeOriginal": "+09:00"})]
    prior = {"destinations": {f"{BYDEST}/US": {"destination_timezone": {"user_decision": {"country": "US"}}},
                              f"{BYDEST}/Trip/Belgium": _tz("Europe/Brussels")}}
    art, blk = wf.build_time_decisions(files, groups, prior, _gpx())
    assert blk == []
    ghent = art["destinations"][f"{BYDEST}/Trip/Belgium/Ghent"]["destination_timezone"]
    assert ghent["requires_user_input"] is True and ghent["contradicted_by"]["recorded_offset_seconds"] == 9 * 3600
    assert _asking(art) == {"US/California": ["US/California/LA", "US/California/SF"],
                            "US/California/LA": True, "US/California/SF": True, "Trip/Belgium/Ghent": True}
