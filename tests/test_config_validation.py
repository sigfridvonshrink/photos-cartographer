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
@pytest.mark.spec("config-values-validated-1", "prep-config-validate-gpx-malformed-1", "prep-config-validate-timestamp-format-1", "validate-enum-structure-1", "validate-filename-format-1", "validate-numeric-thresholds-1", "validate-paths-1")
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


# --- destination_distribution_subfolders (geotag §7.1 dev-subfolder gate) ----------------

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


@pytest.mark.spec("prep-config-validation-failure-blocks-1")
def test_load_or_seed_config_rejects_bad_value(tmp_path):
    ws = tmp_path / "ws"
    (ws / ".photos-ingest").mkdir(parents=True)
    bad = copy.deepcopy(utils.CONFIG)
    bad["gpx_interpolation_max_distance_meters"] = -100
    with open(utils.config_path(str(ws)), "w") as f:
        json.dump(bad, f)
    with pytest.raises(ValueError, match="gpx_interpolation_max_distance_meters"):
        utils.load_or_seed_config(str(ws))


# --- media_extensions: classification lists are config (prep §6.1), fingerprinted (shared §4.2) ----

def _mx(image=None, raw=None, video=None):
    """A config whose media_extensions block can be selectively overridden (missing class if None)."""
    c = copy.deepcopy(utils.CONFIG)
    block = {}
    if image is not None: block["image"] = image
    if raw is not None: block["raw"] = raw
    if video is not None: block["video"] = video
    c["media_extensions"] = block
    return c


def test_media_extensions_default_seeded_and_valid():
    assert set(utils.CONFIG["media_extensions"]) == {"image", "raw", "video"}
    assert "jpg" in utils.CONFIG["media_extensions"]["image"]
    utils.validate_config(copy.deepcopy(utils.CONFIG))


@pytest.mark.parametrize("cfg, needle", [
    (_cfg(media_extensions="nope"), "media_extensions must be an object"),
    (_mx(raw=["arw"], video=["mp4"]), "missing class(es): image"),                 # missing class
    (_mx(image=[], raw=["arw"], video=["mp4"]), "must be a non-empty list"),       # empty list
    (_mx(image=["jpg"], raw=["jpg"], video=["mp4"]), "exactly one class"),         # cross-class dup
    (_mx(image=[".jpg"], raw=["arw"], video=["mp4"]), "canonical bare extension"), # leading dot
    (_mx(image=["JPG"], raw=["arw"], video=["mp4"]), "canonical bare extension"),  # uppercase
    (_mx(image=["j pg"], raw=["arw"], video=["mp4"]), "canonical bare extension"), # whitespace
    (_mx(image=[5], raw=["arw"], video=["mp4"]), "must be a non-empty string"),    # wrong type
])
@pytest.mark.spec("prep-config-validate-numeric-lists-1")
def test_media_extensions_rejects_bad(cfg, needle):
    with pytest.raises(ValueError) as ei:
        utils.validate_config(cfg)
    assert needle in str(ei.value), str(ei.value)


@pytest.mark.spec("config-ext-one-class-1", "prep-classify-by-extension-1", "prep-reads-config-authoritative-1")
def test_classification_follows_config_after_load(tmp_path, monkeypatch):
    # A user adds .webp to the image list; after load_or_seed_config it classifies as image, not stray.
    ws = tmp_path / "ws"
    (ws / ".photos-ingest").mkdir(parents=True)
    cfg = copy.deepcopy(utils.CONFIG)
    cfg["media_extensions"]["image"].append("webp")
    with open(utils.config_path(str(ws)), "w") as f:
        json.dump({k: v for k, v in cfg.items() if k != "jobs"}, f)
    assert utils.media_class_for_ext("webp") == "other"     # not yet loaded
    utils.load_or_seed_config(str(ws))
    try:
        assert utils.media_class_for_ext(".WEBP") == "image"   # config now authoritative, case-insensitive
    finally:
        utils.CONFIG.clear(); utils.CONFIG.update(copy.deepcopy(utils.DEFAULT_CONFIG))
        utils._refresh_media_class_map()                       # restore global for other tests


@pytest.mark.spec("config-surgical-staleness-1", "prep-extension-lists-config-1")
def test_field_fingerprints_change_with_their_area():
    base_fol, base_ext = utils.folders_fingerprint(), utils.media_extensions_fingerprint()
    c = copy.deepcopy(utils.CONFIG); c["media_extensions"]["video"].append("webm")
    assert utils.media_extensions_fingerprint(c) != base_ext
    assert utils.folders_fingerprint(c) == base_fol            # extension edit doesn't move the folders fp
    c2 = copy.deepcopy(utils.CONFIG); c2["folders"]["sources"] = "0-inbox"
    assert utils.folders_fingerprint(c2) != base_fol
    assert utils.media_extensions_fingerprint(c2) == base_ext  # folder edit doesn't move the ext fp
