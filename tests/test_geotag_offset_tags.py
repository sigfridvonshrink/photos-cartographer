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

"""Geotag — an offset tag that holds no offset (RUL-unreadable_offset_tag_told).

A photo's `OffsetTimeOriginal` reading `local`, or `+25:00`, is no offset: geotag reads it as no tag, never loosely,
names the photo in its output and keeps it in photos-21. In-process, and once through `geotag plan`.
"""
import json
import sys

import pytest

from _handoff import match_disk, vouched
from _zone import answer_root_zone

import photos_2_geotag as cal
import photos_utils as utils

PHONE = "APPLE|iPhone|p1"
GROUPS = {PHONE: {"camera_group_class": "smartphone"}}
DEST = "6-photos-by-dest/B"
ZONE = {"destinations": {DEST: {"destination_timezone": {"user_decision": {"manual_iana_timezone": "Europe/Brussels"}}}}}


def _photo(name, offset):
    return {"relative_path": f"{DEST}/{name}", "destination": DEST, "camera_group_key": PHONE, "native_gps": None,
            "has_native_gps": False, "has_timestamp": True, "source_naive_time": "2024:07:03 10:00:00",
            "source_time_tag": "EXIF:DateTimeOriginal", "content_fingerprint": "fp-" + name,
            "raw_times": {"OffsetTimeOriginal": offset} if offset is not None else {}}


@pytest.mark.spec("RUL-unreadable_offset_tag_recorded", "RUL-unreadable_offset_tag_is_none", "BLD-unreadable_offset_tags",
                  test="TST-geotag_offset_tags-recorded_and_read_as_none")
def test_an_offset_tag_that_is_no_offset_is_recorded_and_read_as_none(tmp_path):
    ws = tmp_path / "ws"
    (ws / ".photos-ingest").mkdir(parents=True)
    (ws / ".photos-ingest" / "photos-11-handoff.json").write_text("{}")
    wf = cal.GeotagWorkflow(str(ws))
    wf._gpx_fingerprint = "fp"
    gpx = cal.GPXIndex("")
    gpx.points = []
    files = [_photo("a.jpg", "local"), _photo("b.jpg", "+02:00"), _photo("c.jpg", ""), _photo("d.jpg", 9)]
    art, blockers = wf.build_time_decisions(files, GROUPS, ZONE, gpx)
    assert not blockers
    assert art["destinations"][DEST]["unreadable_offset_tags"] == [
        {"relative_path": f"{DEST}/a.jpg", "field": "OffsetTimeOriginal", "value": "local"},
        {"relative_path": f"{DEST}/d.jpg", "field": "OffsetTimeOriginal", "value": "9"}]
    assert [u["relative_path"] for u in wf.unreadable_offset_tags] == [f"{DEST}/a.jpg", f"{DEST}/d.jpg"]
    assert cal._own_offset(files[0]) is None                              # read as no tag


@pytest.mark.spec("RUL-unreadable_offset_tag_told", "BLD-unreadable_offset_tags",
                  test="TST-geotag_offset_tags-named_in_the_output")
def test_geotag_plan_names_the_photo_whose_offset_tag_is_no_offset(tmp_path, monkeypatch, capsys):
    ws = tmp_path / "ws"; ws.mkdir()
    for d in ["0-sources", "1-strays", "2-missing-metadata", "3-redundant-jpgs",
              "4-videos-by-date", "5-photos-by-date", "6-photos-by-dest"]:
        (ws / d).mkdir()
    ctl = ws / ".photos-ingest"; ctl.mkdir()
    (ctl / "photos-00-workspace-guard").touch()
    cfg = {k: v for k, v in utils.CONFIG.items() if k != "jobs"}
    cfg["gpx_root"] = ""
    cfg["camera_time_and_timezone_policy"] = dict(
        cfg["camera_time_and_timezone_policy"], device_groups={"fixed_clock_cameras": [], "phones": [PHONE]})
    (ctl / "photos-00-config.json").write_text(json.dumps(cfg))
    answer_root_zone(ctl, "Europe/Brussels")
    parsed = {"DateTimeOriginal": "2024:07:03 10:00:00", "OffsetTimeOriginal": "local",
              "selected_source_naive_timestamp": "2024:07:03 10:00:00",
              "selected_source_timestamp_tag": "EXIF:DateTimeOriginal", "camera_group_key": PHONE}
    rel = f"{DEST}/odd.jpg"
    files = [{"relative_path": rel, "media_class": "image", "folder_class": "6-photos-by-dest", "size": 1, "mtime_ns": 1,
              "content_hash": json.dumps({"value": "fp" + rel, "status": "valid"}),
              "metadata_status": {"camera_group_key_version": utils.CAMERA_GROUP_KEY_VERSION, "camera_group_key": PHONE,
                                  "has_timestamp": True, "field_set_version": utils.FIELD_SET_VERSION,
                                  "parsed_json": json.dumps(parsed)}}]
    p = ws / rel; p.parent.mkdir(parents=True, exist_ok=True); p.write_bytes(b"x")
    (ctl / "photos-11-handoff.json").write_text(json.dumps(vouched(ctl.parent, {
        "filename_timestamp_format": utils.CONFIG["filename_timestamp_format"], "files": match_disk(ws, files),
        "cache_fingerprint": "pcf",
        "depends_on": {"cache": {"fingerprint_algorithm_version": utils.FINGERPRINT_ALGORITHM_VERSION}}})))
    monkeypatch.chdir(str(ws))
    monkeypatch.setattr(sys, "argv", ["photos-2-geotag", "plan"])
    try:
        cal.main()
    except SystemExit:
        pass
    out = capsys.readouterr()
    said = out.out + out.err
    assert "odd.jpg" in said and "OffsetTimeOriginal" in said and "'local'" in said and "no UTC offset" in said, said
