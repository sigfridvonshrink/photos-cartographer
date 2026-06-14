"""Phase 10 — config sanity validation (the "validate human-authored input" principle).

validate_config checks types, ranges, paths, and formats — not merely JSON syntax — and
runs at config load so a malformed config fails loudly before any work. photos_utils comes
from conftest.py.
"""
import copy
import json

import pytest

import photos_utils as utils


def test_default_config_is_valid():
    utils.validate_config(copy.deepcopy(utils.CONFIG))   # the seed template must pass


def _cfg(**overrides):
    c = copy.deepcopy(utils.CONFIG)
    for k, v in overrides.items():
        c[k] = v
    return c


def _pol(**overrides):
    c = copy.deepcopy(utils.CONFIG)
    c["camera_time_and_timezone_policy"].update(overrides)
    return c


@pytest.mark.parametrize("cfg, needle", [
    (_cfg(filename_timestamp_format="%Q"), "filename_timestamp_format"),         # doesn't vary
    (_cfg(filename_timestamp_format=""), "filename_timestamp_format"),           # empty
    (_cfg(filename_timestamp_format="%Y/%m/%d"), "illegal path character"),      # has '/'
    (_cfg(filename_timestamp_format=5), "must be a string"),                     # wrong type
    (_cfg(gpx_direct_match_max_seconds=-1), "gpx_direct_match_max_seconds"),     # negative
    (_cfg(gpx_interpolation_max_distance_meters="far"), "must be a number"),     # wrong type
    (_cfg(gpx_root="a\x00b"), "NUL byte"),                                       # bad path
    (_cfg(zfs={"snapshot_prefix": "bad name!"}), "snapshot_prefix"),             # illegal zfs prefix
    (_pol(enabled="yes"), "enabled must be a boolean"),                          # non-bool flag
    (_pol(default_folder_timezone="Mars/Phobos"), "valid IANA timezone"),        # bad tz
    (_pol(manual_segment_template_count=1.5), "must be an integer"),             # non-int count
    (_pol(phone_gpx_max_distance_meters=-5), "phone_gpx_max_distance_meters"),   # negative
    (_pol(device_groups={"phones": "nope"}), "list of strings"),                # not a list
    (_pol(device_groups={"phones": [1, 2]}), "list of strings"),                # non-string elems
    (_cfg(folders="nope"), "folders must be an object"),                        # folders not a dict
    (_cfg(camera_time_and_timezone_policy="nope"), "must be an object"),        # policy not a dict
    (_pol(device_groups="nope"), "device_groups must be an object"),           # device_groups not a dict
    (_cfg(zfs={"datasets": "nope"}), "zfs.datasets must be an object"),         # zfs.datasets not a dict
])
def test_validate_config_rejects(cfg, needle):
    with pytest.raises(ValueError) as ei:
        utils.validate_config(cfg)
    assert needle in str(ei.value), str(ei.value)


def test_validate_config_rejects_non_object_top_level():
    with pytest.raises(ValueError, match="top level must be a JSON object"):
        utils.validate_config([1, 2, 3])


def test_load_or_seed_config_rejects_non_object_file(tmp_path):
    (tmp_path / ".photos-ingest").mkdir()
    with open(utils.config_path(str(tmp_path)), "w") as f:
        json.dump([1, 2, 3], f)                                # valid JSON, but not an object
    with pytest.raises(ValueError, match="must be a JSON object"):
        utils.load_or_seed_config(str(tmp_path))


def test_valid_edits_pass():
    utils.validate_config(_pol(default_folder_timezone="Europe/Brussels"))
    utils.validate_config(_cfg(gpx_interpolation_max_distance_meters=500.0,
                               gpx_direct_match_max_seconds=0))


# --- destination_distribution_subfolders (calibration §7.1 dev-subfolder gate) ----------------

def test_distribution_subfolders_default_valid():
    assert utils.CONFIG["destination_distribution_subfolders"] == ["jpg", "tif"]
    utils.validate_config(_cfg(destination_distribution_subfolders=["jpg", "tif", "webp"]))


@pytest.mark.parametrize("bad, needle", [
    ("jpg", "non-empty list"),
    ([], "non-empty list"),
    (["a/b"], "single path component"),
    (["jpg", ""], "single path component"),
])
def test_distribution_subfolders_rejects_bad(bad, needle):
    with pytest.raises(ValueError) as ei:
        utils.validate_config({"destination_distribution_subfolders": bad})
    assert needle in str(ei.value), str(ei.value)


# --- library-merge config (G5.4; deep validation is the merge phase's, shared §4.3/§14.1) ----

def test_merge_block_seeded_and_default_valid():
    # library_root is seeded with a deployment default (a non-empty path); the merge phase deep-validates
    # its existence, prep only type-checks it.
    assert isinstance(utils.CONFIG["merge"]["library_root"], str) and utils.CONFIG["merge"]["library_root"]
    assert utils.CONFIG["merge"]["placement_policy"] and utils.CONFIG["merge"]["collision_policy"]
    utils.validate_config(_cfg(merge=dict(utils.CONFIG["merge"], library_root="/srv/library")))


@pytest.mark.parametrize("merge, needle", [
    ("nope", "merge must be an object"),
    ({"library_root": 123}, "merge.library_root must be a string"),
    ({"library_root": "a\x00b"}, "merge.library_root must not contain a NUL"),
    ({"placement_policy": 5}, "merge.placement_policy must be a string"),
])
def test_merge_block_rejects_bad(merge, needle):
    with pytest.raises(ValueError) as ei:
        utils.validate_config({"merge": merge})
    assert needle in str(ei.value), str(ei.value)


def test_config_without_merge_block_still_valid():
    utils.validate_config({"gpx_root": ""})        # legacy config (no merge key) is accepted


def test_load_or_seed_config_rejects_bad_value(tmp_path):
    ws = tmp_path / "ws"
    (ws / ".photos-ingest").mkdir(parents=True)
    bad = copy.deepcopy(utils.CONFIG)
    bad["gpx_interpolation_max_distance_meters"] = -100
    with open(utils.config_path(str(ws)), "w") as f:
        json.dump(bad, f)
    with pytest.raises(ValueError, match="gpx_interpolation_max_distance_meters"):
        utils.load_or_seed_config(str(ws))
