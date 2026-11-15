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

"""Geotag — a camera group the configuration names several bodies (BLD-several_bodies_groups).

Two bodies of one model that write no serial are one group. The configuration names such groups in
`camera_time_and_timezone_policy.several_bodies_groups` (by default none: a group is one camera); for a group so
named an offset from its GPS never applies itself, its proposal says the group may be several bodies, and its days in
different destinations are decided apart. From conftest.py.
"""
import copy
from datetime import datetime, timedelta, timezone

import pytest

import photos_2_geotag as cal
import photos_utils as utils
from _zone import with_root_zone

BYDEST = "6-photos-by-dest"
CAM = "SONY|ILCE-6400|"


def _utc(h, m=0, s=0):
    return datetime(2024, 7, 3, h, m, s, tzinfo=timezone.utc)


def _gpx(points):
    idx = cal.GPXIndex("")
    idx.points = list(points)
    idx.file_sha = {"trip.gpx": "sha"}
    return idx


def _wf(tmp_path):
    ws = tmp_path / "ws"
    (ws / ".photos-ingest").mkdir(parents=True)
    (ws / ".photos-ingest" / "photos-11-handoff.json").write_text("{}")
    wf = cal.GeotagWorkflow(str(ws))
    wf._gpx_fingerprint = "fp"
    return wf


def _photo(dest, name, lat, lon, naive, gps=True):
    return {"relative_path": f"{BYDEST}/{dest}/{name}", "destination": f"{BYDEST}/{dest}", "camera_group_key": CAM,
            "native_gps": {"lat": lat, "lon": lon} if gps else None, "has_native_gps": gps, "has_timestamp": True,
            "source_naive_time": naive, "content_fingerprint": "fp-" + name}


def _name_several(*keys):
    pol = utils.CONFIG["camera_time_and_timezone_policy"]
    pol["device_groups"] = {"phones": [], "fixed_clock_cameras": [CAM]}
    pol["several_bodies_groups"] = list(keys)
    pol["multi_anchor_auto_apply"] = True


@pytest.mark.spec("RUL-several_bodies_named_by_configuration", "BLD-several_bodies_groups",
                  test="TST-geotag_several_bodies-the_setting_names_fixed_clock_groups_none_by_default")
def test_the_setting_names_fixed_clock_groups_none_by_default():
    """By default no group is several bodies; the setting is a list of fixed-clock camera groups, each named once — a
    phone's group, an unclassed one, a key named twice or anything but a list is refused."""
    assert utils.DEFAULT_CONFIG["camera_time_and_timezone_policy"]["several_bodies_groups"] == []
    cfg = copy.deepcopy(utils.DEFAULT_CONFIG)
    pol = cfg["camera_time_and_timezone_policy"]
    pol["device_groups"] = {"phones": ["Apple|iPhone|"], "fixed_clock_cameras": [CAM]}
    pol["several_bodies_groups"] = [CAM]
    utils.validate_config(cfg)
    for bad, why in (("x", "list of camera group keys"), ([CAM, CAM], "twice"), (["Apple|iPhone|"], "fixed_clock_cameras"),
                     (["Other|X|"], "fixed_clock_cameras"), ([""], "list of camera group keys")):
        pol["several_bodies_groups"] = bad
        with pytest.raises(ValueError, match=why):
            utils.validate_config(cfg)
    # the camera's groups as geotag sees them: one camera, unless named
    files = [_photo("A", "a.arw", 50.0, 4.0, "2024:07:03 14:00:00")]
    _name_several()
    groups, _ = cal.GeotagWorkflow("/tmp").recognize_camera_groups(files)
    assert "several_bodies" not in groups[CAM]
    _name_several(CAM)
    groups, _ = cal.GeotagWorkflow("/tmp").recognize_camera_groups(files)
    assert groups[CAM]["several_bodies"] is True


@pytest.mark.spec("RUL-several_bodies_offset_never_auto", "RUL-several_bodies_noted", "BLD-several_bodies_groups",
                  test="TST-geotag_several_bodies-an_offset_from_its_gps_is_a_proposal_said_to_be_perhaps_one_bodys")
def test_an_offset_from_its_gps_is_a_proposal_said_to_be_perhaps_one_bodys(tmp_path):
    """Two anchors agreeing would apply themselves for one camera; for a group named several bodies they are a
    proposal, noted as such — taking effect once accepted; so too two GPS fix times."""
    wf = _wf(tmp_path)
    gpx = _gpx([cal.GPXPoint(50.0, 4.0, _utc(12), "trip.gpx", 0), cal.GPXPoint(51.0, 5.0, _utc(13), "trip.gpx", 0)])
    files = [_photo("A", "a.arw", 50.0, 4.0, "2024:07:03 14:00:00"), _photo("A", "b.arw", 51.0, 5.0, "2024:07:03 15:00:00")]
    _name_several()
    groups, _ = wf.recognize_camera_groups(files)
    art, _ = wf.build_time_decisions(files, groups, with_root_zone({"destinations": {}}), gpx)
    cell = art["destinations"][f"{BYDEST}/A"]["camera_group_time_decisions"][CAM]
    assert cell["effective_time_anchor"]["source"] == "gpx_anchor_auto" and "several_bodies" not in cell
    _name_several(CAM)
    groups, _ = wf.recognize_camera_groups(files)
    art, _ = wf.build_time_decisions(files, groups, with_root_zone({"destinations": {}}), gpx)
    cell = art["destinations"][f"{BYDEST}/A"]["camera_group_time_decisions"][CAM]
    assert cell["requires_user_input"] is True and cell["effective_time_anchor"] == ""
    assert cell["several_bodies"] is True and cell["proposal"]["proposed_offset_seconds"] == -7200
    prior = copy.deepcopy(art)
    prior["destinations"][f"{BYDEST}/A"]["camera_group_time_decisions"][CAM]["user_decision"].update(
        accept_proposal=True, accepted_offset_seconds=-7200)
    art, _ = wf.build_time_decisions(files, groups, prior, gpx)
    cell = art["destinations"][f"{BYDEST}/A"]["camera_group_time_decisions"][CAM]
    assert cell["effective_time_anchor"] == {"offset_seconds": -7200, "source": "gpx_anchor_accepted"}
    # the times the fixes recorded: two agreeing would apply themselves, for several bodies they are proposed
    fixes = [dict(f, gps_utc=t) for f, t in zip(files, ("2024-07-03T12:00:00Z", "2024-07-03T13:00:00Z"))]
    art, _ = wf.build_time_decisions(fixes, groups, with_root_zone({"destinations": {}}), _gpx([]))
    cell = art["destinations"][f"{BYDEST}/A"]["camera_group_time_decisions"][CAM]
    assert cell["proposal"]["proposal_source"] == "gps_time" and cell["requires_user_input"] is True
    assert cell["several_bodies"] is True


@pytest.mark.spec("RUL-several_bodies_days_apart", "BLD-several_bodies_groups",
                  test="TST-geotag_several_bodies-its_days_in_two_destinations_are_decided_apart")
def test_its_days_in_two_destinations_are_decided_apart(tmp_path):
    """One body's photos sorted into A, the other's into B, the same day: for one camera the two offsets its GPS gives
    would be one clock read two ways, both withheld; for several bodies each is its destination's own proposal. And a
    destination where the group has no position of its own is offered no offset from the other."""
    wf = _wf(tmp_path)
    gpx = _gpx([cal.GPXPoint(50.0, 4.0, _utc(12), "trip.gpx", 0), cal.GPXPoint(51.0, 5.0, _utc(9), "trip.gpx", 0)])
    files = [_photo("A", "a.arw", 50.0, 4.0, "2024:07:03 14:00:00"), _photo("B", "b.arw", 51.0, 5.0, "2024:07:03 14:00:00"),
             _photo("C", "c.arw", 0, 0, "2024:07:03 16:00:00", gps=False)]
    for f in files:
        f["destination"] = f"{BYDEST}/{f['relative_path'].split('/')[1]}"
    _name_several()
    utils.CONFIG["camera_time_and_timezone_policy"]["single_anchor_auto_apply"] = True
    groups, _ = wf.recognize_camera_groups(files)
    art, _ = wf.build_time_decisions(files, groups, with_root_zone({"destinations": {}}), gpx)
    cells = {d: art["destinations"][f"{BYDEST}/{d}"]["camera_group_time_decisions"][CAM] for d in "ABC"}
    assert cells["A"].get("conflicts_with") and cells["B"].get("conflicts_with")            # one camera: one clock
    _name_several(CAM)
    utils.CONFIG["camera_time_and_timezone_policy"]["single_anchor_auto_apply"] = True
    groups, _ = wf.recognize_camera_groups(files)
    art, _ = wf.build_time_decisions(files, groups, with_root_zone({"destinations": {}}), gpx)
    cells = {d: art["destinations"][f"{BYDEST}/{d}"]["camera_group_time_decisions"][CAM] for d in "ABC"}
    assert "conflicts_with" not in cells["A"] and "conflicts_with" not in cells["B"]
    assert cells["A"]["proposal"]["proposed_offset_seconds"] == -7200
    assert cells["B"]["proposal"]["proposed_offset_seconds"] == -18000
    assert cells["C"]["proposal"]["proposal_source"] != "same_day_elsewhere"
