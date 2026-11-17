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

"""A time the user kept as a photo's true time is no reading of its camera's clock (RUL-kept_time_not_clock_evidence):
it is left out of the photos set against its destination's timezone (BLD-changed_time_kept_not_anchor), so an offset
tag it holds that the zone does not give neither proposes a zone nor speaks against one."""
import pytest

import photos_2_geotag as cal

PHONE = "APPLE|iPhone|p1"
PAIR = {"DateTimeOriginal": "2024:07:03 14:45:00", "OffsetTimeOriginal": "+05:00"}   # Brussels gives +02:00 then


def _photo():
    return {"relative_path": "6-photos-by-dest/Brussels/a.jpg", "camera_group_key": PHONE,
            "source_naive_time": PAIR["DateTimeOriginal"], "source_time_tag": "EXIF:DateTimeOriginal",
            "raw_times": dict(PAIR)}


@pytest.mark.spec("RUL-kept_time_not_clock_evidence", "BLD-changed_time_kept_not_anchor",
                  test="TST-geotag_kept_time_zone-a_kept_time_s_tag_neither_proposes_nor_contradicts_the_zone")
def test_a_kept_time_s_tag_neither_proposes_nor_contradicts_the_zone():
    recorded, kept = _photo(), cal.keep_true_time(_photo(), PAIR)
    zones = ["Asia/Karachi", "Europe/Brussels"]          # a country's zones: +05:00 is Karachi's
    # the photo read as recorded: its +05:00 speaks against Brussels and picks Karachi
    assert cal._offsets_against_zone([recorded], {}, "Europe/Brussels")["recorded_offsets"] == [5 * 3600]
    assert cal._zone_from_photos([recorded], {}, zones) == "Asia/Karachi"
    # the same time kept as true: its tag is no evidence either way
    assert cal._offsets_against_zone([kept], {}, "Europe/Brussels") is None
    assert cal._zone_from_photos([kept], {}, zones) is None
