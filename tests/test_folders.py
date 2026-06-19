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

"""Phase A — folder names abstracted into config (single source of truth).

The role->name map is config (CONFIG['folders'], validated); roles, dedup order, and band
membership are code. photos_utils comes from conftest.py.
"""
import copy

import pytest

import photos_utils as utils


def test_default_folders_are_the_0_6_names():
    assert utils.CONFIG["folders"] == utils.DEFAULT_FOLDERS
    assert utils.DEFAULT_FOLDERS == {
        "sources": "0-sources", "strays": "1-strays", "missing_metadata": "2-missing-metadata",
        "redundant_jpgs": "3-redundant-jpgs", "videos_by_date": "4-videos-by-date",
        "photos_by_date": "5-photos-by-date", "photos_by_dest": "6-photos-by-dest",
    }


def test_accessors_round_trip():
    assert utils.folder_name("photos_by_dest") == "6-photos-by-dest"
    assert utils.folder_role("6-photos-by-dest") == "photos_by_dest"
    assert utils.folder_role("nope") is None
    # managed = every role except strays, in order (no 1-strays)
    assert utils.managed_folder_names() == [
        "0-sources", "2-missing-metadata", "3-redundant-jpgs",
        "4-videos-by-date", "5-photos-by-date", "6-photos-by-dest",
    ]


def test_dedup_priority_orders_by_dest_highest_strays_excluded():
    p = lambda path: utils.dedup_priority(path)
    assert p("6-photos-by-dest/x") < p("5-photos-by-date/x") < p("4-videos-by-date/x") \
        < p("3-redundant-jpgs/x") < p("2-missing-metadata/x") < p("0-sources/x")
    # strays and unknown folders are never retained (lowest priority = highest number)
    assert p("1-strays/x") == p("9-unknown/x") == len(utils.FOLDER_DEDUP_PRIORITY)


@pytest.mark.parametrize("bad, needle", [
    ({"sources": "0-sources"}, "missing role"),                                  # incomplete
    (dict(utils.DEFAULT_FOLDERS, strays="0-sources"), "both name"),              # duplicate name
    (dict(utils.DEFAULT_FOLDERS, sources="a/b"), "single path component"),       # has '/'
    (dict(utils.DEFAULT_FOLDERS, sources=""), "non-empty"),                      # empty
    (dict(utils.DEFAULT_FOLDERS, sources=".photos-ingest"), "single path"),      # leading dot / control
])
def test_validate_config_rejects_bad_folders(bad, needle):
    with pytest.raises(ValueError) as ei:
        utils.validate_config({"folders": bad})
    assert needle in str(ei.value), str(ei.value)


def test_validate_config_accepts_default_folders():
    utils.validate_config(copy.deepcopy(utils.CONFIG))


def test_missing_managed_folders_detects_absent_and_nondir(tmp_path):
    """All seven 0-6 must exist as directories; absent OR replaced-by-a-file is non-conforming,
    reported in canonical 0-6 order."""
    for d in ("0-sources", "1-strays", "2-missing-metadata", "3-redundant-jpgs",
              "4-videos-by-date", "5-photos-by-date", "6-photos-by-dest"):
        (tmp_path / d).mkdir()
    assert utils.missing_managed_folders(str(tmp_path)) == []          # complete -> none
    (tmp_path / "4-videos-by-date").rmdir()                            # absent
    (tmp_path / "2-missing-metadata").rmdir()
    (tmp_path / "2-missing-metadata").write_text("not a dir")          # replaced by a file
    assert utils.missing_managed_folders(str(tmp_path)) == ["2-missing-metadata", "4-videos-by-date"]
