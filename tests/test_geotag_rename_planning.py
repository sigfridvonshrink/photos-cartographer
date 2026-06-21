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

"""Phase 6a (geotag) — no-clobber timestamp rename planning (spec §26/§27).

Destination-local filename computation + the deterministic suffix allocator that treats every
on-disk and already-planned name as permanently occupied. Safety-critical naming, so full branch
coverage. Pure functions, unit-tested directly. From conftest.py.
"""
import pytest

import photos_2_geotag as cal

FMT = "%Y-%m-%d--%H-%M-%S"
TZ = "Europe/Brussels"


def _f(rel, utc, tz=TZ):
    return {"relative_path": rel, "resolved_utc": utc, "destination_timezone": tz}


def _names(rows):
    return [(r["current_name"], r["planned_name"], r["rename"]) for r in rows]


# --- destination_local_basename ---------------------------------------------

def test_local_basename_dst_and_standard():
    assert cal.destination_local_basename("2024-07-03T12:12:21Z", TZ, FMT, ".jpg") == "2024-07-03--14-12-21.jpg"  # +2
    assert cal.destination_local_basename("2024-01-03T12:00:00Z", TZ, FMT, ".arw") == "2024-01-03--13-00-00.arw"  # +1


def test_local_basename_custom_format_and_ext_preserved():
    assert cal.destination_local_basename("2024-07-03T12:00:00Z", TZ, "%Y%m%d_%H%M%S", ".JPG") == "20240703_140000.JPG"
    assert cal.destination_local_basename("2024-07-03T12:00:00Z", TZ, FMT, "") == "2024-07-03--14-00-00"


def test_local_basename_unpositionable_is_none():
    assert cal.destination_local_basename(None, TZ, FMT, ".jpg") is None              # no resolved UTC
    assert cal.destination_local_basename("bad", TZ, FMT, ".jpg") is None             # unparseable
    assert cal.destination_local_basename("2024-07-03T12:00:00Z", "", FMT, ".jpg") is None  # no timezone


# --- _allocate_name ----------------------------------------------------------

def test_allocate_name_suffix_progression():
    occ = set()
    assert cal._allocate_name("2024-07-03--14-00-00", ".jpg", occ) == "2024-07-03--14-00-00.jpg"
    assert cal._allocate_name("2024-07-03--14-00-00", ".jpg", occ) == "2024-07-03--14-00-00-001.jpg"
    assert cal._allocate_name("2024-07-03--14-00-00", ".jpg", occ) == "2024-07-03--14-00-00-002.jpg"


def test_allocate_name_case_insensitive():
    occ = {"stamp.jpg"}
    assert cal._allocate_name("STAMP", ".JPG", occ) == "STAMP-001.JPG"                # collides with stamp.jpg


# --- plan_renames ------------------------------------------------------------

def test_already_correctly_named_is_no_rename():
    rows = cal.plan_renames([_f("6-photos-by-dest/T/2024-07-03--14-12-21.jpg", "2024-07-03T12:12:21Z")], FMT)
    assert _names(rows) == [("2024-07-03--14-12-21.jpg", "2024-07-03--14-12-21.jpg", False)]


@pytest.mark.spec("move-reevaluate-dest-1")
def test_move_between_destinations_reevaluates_under_new_tz_no_carry():
    """Moving a photo to a new destination re-evaluates its name under the NEW dest's timezone — the
    old destination's local time is never carried. geotag re-derives every run from the handoff (it
    keeps no cross-run resolution cache), so the same resolved UTC under Brussels vs Tokyo yields
    different destination-local names."""
    utc = "2024-07-03T12:00:00Z"
    in_brussels = cal.plan_renames([_f("6-photos-by-dest/Brussels/a.arw", utc, "Europe/Brussels")], FMT)
    in_tokyo = cal.plan_renames([_f("6-photos-by-dest/Tokyo/a.arw", utc, "Asia/Tokyo")], FMT)
    assert _names(in_brussels) == [("a.arw", "2024-07-03--14-00-00.arw", True)]   # +2 (summer)
    assert _names(in_tokyo) == [("a.arw", "2024-07-03--21-00-00.arw", True)]      # +9, re-evaluated
    # the Tokyo name carries nothing from the Brussels evaluation
    assert in_tokyo[0]["planned_name"] != in_brussels[0]["planned_name"]


def test_collision_gets_suffix():
    rows = cal.plan_renames([_f("6-photos-by-dest/T/a.jpg", "2024-07-03T12:12:21Z"),
                             _f("6-photos-by-dest/T/b.jpg", "2024-07-03T12:12:21Z")], FMT)
    assert _names(rows) == [("a.jpg", "2024-07-03--14-12-21.jpg", True),
                            ("b.jpg", "2024-07-03--14-12-21-001.jpg", True)]


def test_name_trade_neither_clobbers():
    # f1 (->15-00-00) and f2 (->13-00-00); f1's target name is f2's CURRENT name -> f1 must suffix.
    rows = cal.plan_renames([_f("6-photos-by-dest/T/2024-07-03--14-00-00.jpg", "2024-07-03T13:00:00Z"),
                             _f("6-photos-by-dest/T/2024-07-03--15-00-00.jpg", "2024-07-03T11:00:00Z")], FMT)
    planned = {r["current_name"]: r["planned_name"] for r in rows}
    assert planned["2024-07-03--14-00-00.jpg"] == "2024-07-03--15-00-00-001.jpg"      # occupied by f2's current
    assert planned["2024-07-03--15-00-00.jpg"] == "2024-07-03--13-00-00.jpg"          # free
    assert len({v.lower() for v in planned.values()}) == 2                            # distinct, no clobber


def test_case_insensitive_collision_suffixes():
    # a file currently named with different case than another's planned target must still not clobber
    rows = cal.plan_renames([_f("6-photos-by-dest/T/A.JPG", "2024-07-03T12:00:00Z"),
                             _f("6-photos-by-dest/T/keep.jpg", "2024-07-03T12:00:00Z")], FMT)
    targets = {r["planned_name"].lower() for r in rows}
    assert len(targets) == 2                                                          # case-insensitively distinct


def test_unpositionable_file_keeps_name():
    rows = cal.plan_renames([_f("6-photos-by-dest/T/x.jpg", None)], FMT)              # no resolved UTC
    assert _names(rows) == [("x.jpg", "x.jpg", False)]


def test_extension_preserved_in_rename():
    rows = cal.plan_renames([_f("6-photos-by-dest/T/raw.arw", "2024-07-03T12:00:00Z")], FMT)
    assert rows[0]["planned_name"] == "2024-07-03--14-00-00.arw"


def test_deterministic_order():
    files = [_f("6-photos-by-dest/T/z.jpg", "2024-07-03T12:00:00Z"),
             _f("6-photos-by-dest/T/a.jpg", "2024-07-03T12:00:00Z")]
    a = cal.plan_renames(files, FMT)
    b = cal.plan_renames(list(reversed(files)), FMT)
    assert _names(a) == _names(b)                                                     # input order irrelevant
    # processed by relative_path: a.jpg first -> base name, z.jpg -> suffix
    planned = {r["current_name"]: r["planned_name"] for r in a}
    assert planned["a.jpg"] == "2024-07-03--14-00-00.jpg" and planned["z.jpg"] == "2024-07-03--14-00-00-001.jpg"
