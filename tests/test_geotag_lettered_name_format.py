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

"""Geotag's names under a filename format that writes a letter: a name is taken whatever its case."""
import pytest

import photos_2_geotag as cal

FMT = "%Y%m%dT%H%M%S"                 # a letter in every name: 20240703T140000
T = "6-photos-by-dest/T/"


@pytest.mark.parametrize("held", ["20240703T140000.jpg", "20240703t140000.jpg", "20240703T140000.JPG",
                                  "20240703t140000.ARW"])
@pytest.mark.spec("RUL-suffix_case_insensitive", test="TST-geotag_lettered_name_format-a_name_held_in_any_case_is_taken")
def test_a_name_held_in_any_case_is_taken(held):
    """Under a format whose names hold a letter, a photo held by another under its timestamp's name — in that case or
    another, under any extension — is given the next free suffix, never the name held."""
    rows = {r["relative_path"]: r for r in cal.plan_renames([
        {"relative_path": T + held, "resolved_utc": None, "destination_timezone": "Europe/Brussels"},   # keeps its name
        {"relative_path": T + "IMG_2.jpg", "resolved_utc": "2024-07-03T12:00:00Z",
         "destination_timezone": "Europe/Brussels"},
    ], FMT)}
    assert not rows[T + held]["rename"]
    assert rows[T + "IMG_2.jpg"]["planned_name"] == "20240703T140000-001.jpg", rows
