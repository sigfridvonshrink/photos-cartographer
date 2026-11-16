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

"""Phase 6a (geotag) — no-clobber timestamp rename planning (BLD-rename_planning).

Destination-local filename computation + the deterministic suffix allocator that treats every
on-disk and already-planned name as permanently occupied. Safety-critical naming, so full branch
coverage. Pure functions, unit-tested directly. From conftest.py.
"""
import os

import pytest

import photos_2_geotag as cal
import photos_utils as utils

FMT = "%Y-%m-%d--%H-%M-%S"
TZ = "Europe/Brussels"


def _f(rel, utc, tz=TZ):
    return {"relative_path": rel, "resolved_utc": utc, "destination_timezone": tz}


def _names(rows):
    return [(r["current_name"], r["planned_name"], r["rename"]) for r in rows]


# --- destination_local_basename ---------------------------------------------

@pytest.mark.spec("RUL-geotag_name_final", test="TST-geotag_rename_planning-local_basename_dst_and_standard")
def test_local_basename_dst_and_standard():
    assert cal.destination_local_basename("2024-07-03T12:12:21Z", TZ, FMT, ".jpg") == "2024-07-03--14-12-21.jpg"  # +2
    assert cal.destination_local_basename("2024-01-03T12:00:00Z", TZ, FMT, ".arw") == "2024-01-03--13-00-00.arw"  # +1


@pytest.mark.spec("RUL-filename_format_configured",
                  test="TST-geotag_rename_planning-local_basename_custom_format_and_ext_preserved")
def test_local_basename_custom_format_and_ext_preserved():
    assert cal.destination_local_basename("2024-07-03T12:00:00Z", TZ, "%Y%m%d_%H%M%S", ".JPG") == "20240703_140000.JPG"
    assert cal.destination_local_basename("2024-07-03T12:00:00Z", TZ, FMT, "") == "2024-07-03--14-00-00"


def test_local_basename_unpositionable_is_none():
    assert cal.destination_local_basename(None, TZ, FMT, ".jpg") is None              # no resolved UTC
    assert cal.destination_local_basename("bad", TZ, FMT, ".jpg") is None             # unparseable
    assert cal.destination_local_basename("2024-07-03T12:00:00Z", "", FMT, ".jpg") is None  # no timezone


# --- the shared first-free allocation geotag uses ----------------------------------------------------------

@pytest.mark.spec("RUL-suffix_choice_by_phase")
def test_allocate_name_suffix_progression():
    occ = set()
    assert utils.allocate_suffix("2024-07-03--14-00-00", "jpg", occ, bare_first=True) == "2024-07-03--14-00-00.jpg"
    assert utils.allocate_suffix("2024-07-03--14-00-00", "jpg", occ, bare_first=True) == "2024-07-03--14-00-00-001.jpg"
    assert utils.allocate_suffix("2024-07-03--14-00-00", "jpg", occ, bare_first=True) == "2024-07-03--14-00-00-002.jpg"


@pytest.mark.spec("RUL-suffix_choice_by_phase", test="TST-geotag_rename_planning-first_free_suffix_fills_a_gap")
def test_first_free_suffix_fills_a_gap():
    # Geotag takes the FIRST free name, by the same rule as prep: with the bare name and -002 taken,
    # the next is -001, never -003 (merge alone appends at max+1).
    occ = {"2024-07-03--14-00-00.jpg", "2024-07-03--14-00-00-002.jpg"}
    assert utils.allocate_suffix("2024-07-03--14-00-00", "jpg", occ, bare_first=True) == "2024-07-03--14-00-00-001.jpg"
    assert utils.allocate_suffix("2024-07-03--14-00-00", "jpg", occ, bare_first=True) == "2024-07-03--14-00-00-003.jpg"


def test_allocate_name_case_insensitive():
    occ = {"stamp.jpg"}
    assert utils.allocate_suffix("STAMP", "JPG", occ, bare_first=True) == "STAMP-001.JPG"                # collides with stamp.jpg


# --- plan_renames ------------------------------------------------------------

@pytest.mark.spec("RUL-uncorrected_keeps_its_name", "BLD-rename_planning", "RUL-mutate_on_difference",
                  test="TST-geotag_rename_planning-already_correctly_named_is_no_rename")
def test_already_correctly_named_is_no_rename():
    rows = cal.plan_renames([_f("6-photos-by-dest/T/2024-07-03--14-12-21.jpg", "2024-07-03T12:12:21Z")], FMT)
    assert _names(rows) == [("2024-07-03--14-12-21.jpg", "2024-07-03--14-12-21.jpg", False)]


@pytest.mark.spec("RUL-uncorrected_keeps_its_name", "BLD-rename_planning", test="TST-geotag_rename_planning-suffixed_name_of_the_right_time_kept")
def test_suffixed_name_of_the_right_time_kept():
    # A burst prep named 12-00-00 and 12-00-00-001, its time not corrected: neither is renamed, run
    # after run. (Before, -001 went to -002, and on the next run back to -001.)
    names = ["2024-07-03--14-00-00.jpg", "2024-07-03--14-00-00-001.jpg"]
    for _run in range(3):
        rows = cal.plan_renames([_f("6-photos-by-dest/T/" + n, "2024-07-03T12:00:00Z") for n in names], FMT)
        assert not any(r["rename"] for r in rows), rows
    # A lone -001 whose sibling went elsewhere keeps its suffix too: its time is not corrected.
    rows = cal.plan_renames([_f("6-photos-by-dest/T/2024-07-03--14-00-00-001.jpg", "2024-07-03T12:00:00Z")], FMT)
    assert _names(rows) == [("2024-07-03--14-00-00-001.jpg", "2024-07-03--14-00-00-001.jpg", False)]


@pytest.mark.spec("RUL-geotag_name_final", test="TST-geotag_rename_planning-only_a_numeric_suffix_counts")
def test_only_a_numeric_suffix_counts():
    # Another time that merely starts with the right one, or a non-numeric tail, is renamed.
    for name in ("2024-07-03--14-00-00-x.jpg", "2024-07-03--14-00-00-01.jpg", "2024-07-03--14-00-00copy.jpg"):
        rows = cal.plan_renames([_f("6-photos-by-dest/T/" + name, "2024-07-03T12:00:00Z")], FMT)
        assert rows[0]["rename"] and rows[0]["planned_name"] == "2024-07-03--14-00-00.jpg", name


@pytest.mark.spec("RUL-moved_photo_decided_anew",
                  test="TST-geotag_rename_planning-move_between_destinations_reevaluates_under_new_tz_no_carry")
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


@pytest.mark.spec("BLD-rename_planning", test="TST-geotag_rename_planning-name_trade_neither_clobbers")
def test_name_trade_neither_clobbers():
    # f1 (->15-00-00) and f2 (->13-00-00); f1's target name is f2's CURRENT name -> f1 must suffix.
    rows = cal.plan_renames([_f("6-photos-by-dest/T/2024-07-03--14-00-00.jpg", "2024-07-03T13:00:00Z"),
                             _f("6-photos-by-dest/T/2024-07-03--15-00-00.jpg", "2024-07-03T11:00:00Z")], FMT)
    planned = {r["current_name"]: r["planned_name"] for r in rows}
    assert planned["2024-07-03--14-00-00.jpg"] == "2024-07-03--15-00-00-001.jpg"      # occupied by f2's current
    assert planned["2024-07-03--15-00-00.jpg"] == "2024-07-03--13-00-00.jpg"          # free
    assert len({v.lower() for v in planned.values()}) == 2                            # distinct, no clobber


@pytest.mark.spec("BLD-rename_planning", "RUL-suffix_case_insensitive",
                  test="TST-geotag_rename_planning-case_insensitive_collision_suffixes")
def test_case_insensitive_collision_suffixes():
    # a file currently named with different case than another's planned target must still not clobber
    rows = cal.plan_renames([_f("6-photos-by-dest/T/A.JPG", "2024-07-03T12:00:00Z"),
                             _f("6-photos-by-dest/T/keep.jpg", "2024-07-03T12:00:00Z")], FMT)
    targets = {r["planned_name"].lower() for r in rows}
    assert len(targets) == 2                                                          # case-insensitively distinct


@pytest.mark.spec("RUL-geotag_extension_lowercase", "BLD-rename_planning", "BLD-case_rename_via",
                  "RUL-uncorrected_keeps_its_name",
                  test="TST-geotag_rename_planning-every_planned_name_ends_with_a_lowercase_extension")
def test_every_planned_name_ends_with_a_lowercase_extension():
    """A photo put in photos by destination by hand keeps the `.JPG` its camera wrote, prep leaving that folder as it
    finds it: geotag lowercases it. One whose name already carries its timestamp is renamed for its extension alone —
    by a temporary name, the change being one of case only — and one whose lowercase name another photo there holds
    (two names differing in case, on a filesystem that tells them apart) takes the next free suffix."""
    T = "6-photos-by-dest/T/"
    rows = {r["relative_path"]: r for r in cal.plan_renames([
        _f(T + "IMG_1.JPG", "2024-07-03T10:00:00Z"),                 # renamed for its time: lowercase too
        _f(T + "2024-07-03--14-00-00.JPG", "2024-07-03T12:00:00Z"),  # its time right: the extension alone
        _f(T + "2024-07-03--15-00-00.jpg", "2024-07-03T13:00:00Z"),  # nothing to do
        _f(T + "2024-07-03--16-00-00.ARW", "2024-07-03T14:00:00Z"),  # a case twin with...
        _f(T + "2024-07-03--16-00-00.arw", "2024-07-03T14:00:00Z"),  # ...the lowercase name already
    ], FMT)}
    assert rows[T + "IMG_1.JPG"]["planned_name"] == "2024-07-03--12-00-00.jpg" and "via" not in rows[T + "IMG_1.JPG"]
    own = rows[T + "2024-07-03--14-00-00.JPG"]
    assert own["rename"] and own["planned_name"] == "2024-07-03--14-00-00.jpg"
    assert own["via"] == "2024-07-03--14-00-00.carto-case.jpg"
    assert not rows[T + "2024-07-03--15-00-00.jpg"]["rename"] and not rows[T + "2024-07-03--16-00-00.arw"]["rename"]
    twin = rows[T + "2024-07-03--16-00-00.ARW"]
    assert twin["planned_name"] == "2024-07-03--16-00-00-001.arw" and "via" not in twin
    names = [r["planned_name"] for r in rows.values()] + [own["via"]]
    assert len({n.lower() for n in names}) == len(names)                             # all distinct, case folded
    assert all(os.path.splitext(n)[1] == os.path.splitext(n)[1].lower() for n in names)
    # the change of case alone reaches the plan as one rename by the temporary name
    f = {"relative_path": T + "2024-07-03--14-00-00.JPG", "content_fingerprint": "fp"}
    (op,) = [o for o in cal.plan_file_ops(f, None, "Europe/Brussels", None, None, own) if o["type"] == "rename_no_clobber"]
    assert (op["from"], op["to"], op["via"]) == ("2024-07-03--14-00-00.JPG", "2024-07-03--14-00-00.jpg",
                                                 "2024-07-03--14-00-00.carto-case.jpg")


def test_unpositionable_file_keeps_name():
    rows = cal.plan_renames([_f("6-photos-by-dest/T/x.jpg", None)], FMT)              # no resolved UTC
    assert _names(rows) == [("x.jpg", "x.jpg", False)]


@pytest.mark.spec("BLD-format_recorded")
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


@pytest.mark.spec("RUL-suffix_deterministic",
                  test="TST-geotag_rename_planning-suffixes_do_not_depend_on_the_order_photos_are_met")
def test_suffixes_do_not_depend_on_the_order_photos_are_met():
    """Which photo of a destination gets which differentiating suffix does not depend on the order the photos are met
    in: the same photos, presented in every order, are given the same names."""
    import itertools
    files = [_f("6-photos-by-dest/T/c.jpg", "2024-07-03T12:00:00Z"),
             _f("6-photos-by-dest/T/2024-07-03--14-00-00.jpg", "2024-07-03T13:00:00Z"),   # holds the bare name
             _f("6-photos-by-dest/T/a.jpg", "2024-07-03T12:00:00Z"),
             _f("6-photos-by-dest/T/B.JPG", "2024-07-03T12:00:00Z")]

    def names(order):
        return {r["relative_path"]: r["planned_name"] for r in cal.plan_renames(list(order), FMT)}
    first = names(files)
    assert first == {"6-photos-by-dest/T/2024-07-03--14-00-00.jpg": "2024-07-03--15-00-00.jpg",
                     "6-photos-by-dest/T/B.JPG": "2024-07-03--14-00-00-001.jpg",     # its extension lowercased
                     "6-photos-by-dest/T/a.jpg": "2024-07-03--14-00-00-002.jpg",
                     "6-photos-by-dest/T/c.jpg": "2024-07-03--14-00-00-003.jpg"}
    for order in itertools.permutations(files):
        assert names(order) == first, [f["relative_path"] for f in order]


# --- the order and the pairs among photos of one second --------------------------------------------------------------

CAMERA = "2024-07-03--13-00-00"              # prep's name: the camera's clock, an hour behind Brussels
TRUE = "2024-07-03--14-00-00"                # the corrected local time at the destination


def _burst(name, sub=None, utc="2024-07-03T12:00:00Z"):
    return dict(_f("6-photos-by-dest/T/" + name, utc), source_naive_time="2024:07:03 13:00:00", sub_second=sub)


def _planned(files):
    return {r["current_name"]: r["planned_name"] for r in cal.plan_renames(files, FMT)}


@pytest.mark.spec("RUL-suffix_in_capture_order", "BLD-rename_planning",
                  test="TST-geotag_rename_planning-burst_keeps_its_order_by_the_suffix_held")
def test_burst_keeps_its_order_by_the_suffix_held():
    """A burst prep named T, T-001, T-002 keeps that order under its corrected time — never path order, where `-`
    sorts before `.` and the bare name would come last."""
    assert _planned([_burst(f"{CAMERA}.jpg"), _burst(f"{CAMERA}-001.jpg"), _burst(f"{CAMERA}-002.jpg")]) == {
        f"{CAMERA}.jpg": f"{TRUE}.jpg", f"{CAMERA}-001.jpg": f"{TRUE}-001.jpg", f"{CAMERA}-002.jpg": f"{TRUE}-002.jpg"}


@pytest.mark.spec("RUL-suffix_in_capture_order", "BLD-rename_planning",
                  test="TST-geotag_rename_planning-sub_second_orders_first")
def test_sub_second_orders_first():
    """Where the photos record a fraction of a second, it orders them before the suffix they hold; a photo recording
    none comes after those that do. Photos of one local second an hour apart — the hour a zone repeats — go by their
    true time first."""
    assert _planned([_burst(f"{CAMERA}.jpg", 0.9), _burst(f"{CAMERA}-001.jpg", 0.1),
                     _burst(f"{CAMERA}-002.jpg", 0.5), _burst(f"{CAMERA}-003.jpg")]) == {
        f"{CAMERA}-001.jpg": f"{TRUE}.jpg", f"{CAMERA}-002.jpg": f"{TRUE}-001.jpg", f"{CAMERA}.jpg": f"{TRUE}-002.jpg",
        f"{CAMERA}-003.jpg": f"{TRUE}-003.jpg"}
    # 00:30 UTC and 01:30 UTC on the night clocks go back both read 02:30 in Brussels: the earlier takes the bare name
    late, early = (dict(_f(f"6-photos-by-dest/T/{n}.jpg", u), sub_second=0.1 if n == "b" else 0.9)
                   for n, u in (("b", "2024-10-27T01:30:00Z"), ("a", "2024-10-27T00:30:00Z")))
    assert _planned([late, early]) == {"a.jpg": "2024-10-27--02-30-00.jpg", "b.jpg": "2024-10-27--02-30-00-001.jpg"}


@pytest.mark.spec("RUL-pair_named_as_one", "BLD-rename_planning",
                  test="TST-geotag_rename_planning-a_pair_takes_one_name")
def test_a_pair_takes_one_name():
    """A RAW and its JPEG, a HEIC and another of its stem, take one name with one suffix, each its own extension —
    the first name no other photo holds under any extension, so a photo never lands beside another photo's RAW or
    JPEG. Two photos of one extension sharing a stem are two photos; members whose corrected times differ are each
    named by their own."""
    files = [_burst(f"{CAMERA}.jpg", 0.2),                     # a lone JPEG, taken first: the bare name
             _burst(f"{CAMERA}-001.arw", 0.5), _burst(f"{CAMERA}-001.jpg", 0.5),     # a pair
             _burst(f"{CAMERA}-002.heic", 0.7), _burst(f"{CAMERA}-002.dng", 0.7)]
    assert _planned(files) == {
        f"{CAMERA}.jpg": f"{TRUE}.jpg",
        f"{CAMERA}-001.arw": f"{TRUE}-001.arw", f"{CAMERA}-001.jpg": f"{TRUE}-001.jpg",
        f"{CAMERA}-002.heic": f"{TRUE}-002.heic", f"{CAMERA}-002.dng": f"{TRUE}-002.dng"}
    # the bare name is held by another photo as a .jpg: neither half of the pair takes it, nor does a lone RAW
    files = [_burst(f"{CAMERA}.arw", 0.5), _burst(f"{CAMERA}.jpg", 0.5), _burst("DSC_9.arw", 0.6),
             dict(_f(f"6-photos-by-dest/T/{TRUE}.jpg", "2024-07-03T12:00:00Z"))]     # already so named, kept
    assert _planned(files) == {f"{CAMERA}.arw": f"{TRUE}-001.arw", f"{CAMERA}.jpg": f"{TRUE}-001.jpg",
                               "DSC_9.arw": f"{TRUE}-002.arw", f"{TRUE}.jpg": f"{TRUE}.jpg"}
    # a pair of two cameras whose clocks are corrected differently: each takes the name of its own time
    assert _planned([_burst("IMG_1.arw"), _burst("IMG_1.jpg", utc="2024-07-03T12:00:05Z")]) == {
        "IMG_1.arw": f"{TRUE}.arw", "IMG_1.jpg": "2024-07-03--14-00-05.jpg"}
    # two photos of one extension whose names differ only in case are two photos, not a pair
    twins = _planned([_burst("IMG_2.JPG"), _burst("img_2.jpg")])
    assert sorted(twins.values()) == [f"{TRUE}-001.jpg", f"{TRUE}.jpg"]


@pytest.mark.spec("RUL-names_local_in_repeated_hour", "RUL-geotag_name_final", "BLD-geotag_final_name",
                  test="TST-geotag_rename_planning-repeated_hour_names_sort_by_local_time")
def test_repeated_hour_names_sort_by_local_time():
    """In the hour Brussels repeats as its clocks go back, names are its local time: a photo taken at 00:45 UTC
    (02:45 summer time) is named after one taken half an hour later at 01:15 UTC (02:15 winter time), and sorts
    after it. The true order is in the metadata."""
    first = _f("6-photos-by-dest/T/first.jpg", "2024-10-27T00:45:00Z")
    second = _f("6-photos-by-dest/T/second.jpg", "2024-10-27T01:15:00Z")
    planned = _planned([first, second])
    assert planned == {"first.jpg": "2024-10-27--02-45-00.jpg", "second.jpg": "2024-10-27--02-15-00.jpg"}
    assert sorted(planned, key=planned.get) == ["second.jpg", "first.jpg"]


@pytest.mark.spec("RUL-suffix_in_capture_order", "BLD-sub_second_read",
                  test="TST-geotag_rename_planning-sub_second_read_from_the_record")
def test_sub_second_read_from_the_record():
    """The fraction of a second is read from prep's record: written in the recorded time itself, else from the
    EXIF sub-second field beside it — its digits; none where neither holds one."""
    rec = {"selected_source_naive_timestamp": "2024:07:03 12:00:00",
           "selected_source_timestamp_tag": "EXIF:DateTimeOriginal"}
    assert cal.recorded_sub_second(dict(rec, SubSecTimeOriginal="045")) == 0.045
    assert cal.recorded_sub_second(dict(rec, SubSecTimeOriginal=7)) == 0.7
    assert cal.recorded_sub_second(dict(rec, selected_source_naive_timestamp="2024:07:03 12:00:00.25",
                                        SubSecTimeOriginal="9")) == 0.25
    created = dict(rec, selected_source_timestamp_tag="EXIF:CreateDate")
    assert cal.recorded_sub_second(dict(created, SubSecTimeDigitized="6", SubSecTimeOriginal="9")) == 0.6
    assert cal.recorded_sub_second(dict(created, SubSecTime="9")) is None              # ModifyDate's, not this one's
    assert cal.recorded_sub_second(dict(rec, selected_source_timestamp_tag="QuickTime:ModifyDate",
                                        SubSecTime=" 25 ")) == 0.25
    assert cal.recorded_sub_second(dict(created, SubSecTimeDigitized="2024:07:03 12:00:00.6")) is None  # no digits
    assert cal.recorded_sub_second(rec) is None
    assert cal.recorded_sub_second(dict(rec, SubSecTimeOriginal="")) is None
    assert cal.recorded_sub_second({}) is None
