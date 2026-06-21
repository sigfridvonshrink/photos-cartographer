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

"""merge-no-time-gps-changes-1 — merge placement NEVER edits EXIF time/GPS.

Merge moves bytes (same-fs renameat2 or cross-fs copy+verify) and never invokes exiftool, so a placed
photo's EXIF capture time and GPS coordinates are byte-identical before and after placement. This uses
REAL magick (to mint a JPEG) and REAL exiftool (to set + read tags) — both are present in the dev/CI
environments — so it exercises the actual placement primitives, not a mock. photos_utils from conftest.
"""
import json
import os
import shutil
import subprocess

import pytest

import photos_utils as utils

pytestmark = pytest.mark.skipif(
    shutil.which("exiftool") is None or (shutil.which("magick") is None and shutil.which("convert") is None),
    reason="needs real exiftool + ImageMagick")

GPS_TIME_TAGS = ["DateTimeOriginal", "GPSLatitude", "GPSLongitude", "GPSLatitudeRef", "GPSLongitudeRef"]


def _magick(*args):
    tool = "magick" if shutil.which("magick") else "convert"
    base = [tool] if tool == "convert" else [tool]
    subprocess.run(base + list(args), check=True, stdin=subprocess.DEVNULL,
                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def _make_tagged_jpeg(path):
    """A real 1x1 JPEG with a known capture time + GPS, written via magick then exiftool."""
    _magick("-size", "1x1", "xc:white", str(path))
    subprocess.run(["exiftool", "-overwrite_original",
                    "-DateTimeOriginal=2024:07:03 14:00:00",
                    "-GPSLatitude=50.0", "-GPSLatitudeRef=N",
                    "-GPSLongitude=4.0", "-GPSLongitudeRef=E", str(path)],
                   check=True, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def _read_tags(path):
    out = subprocess.run(["exiftool", "-json", "-n", *(f"-{t}" for t in GPS_TIME_TAGS), str(path)],
                         check=True, capture_output=True, text=True, stdin=subprocess.DEVNULL).stdout
    d = json.loads(out)[0]
    return {t: d.get(t) for t in GPS_TIME_TAGS}


@pytest.mark.spec("merge-no-time-gps-changes-1")
def test_same_fs_placement_preserves_exif_time_and_gps(tmp_path):
    src = tmp_path / "a.jpg"
    _make_tagged_jpeg(src)
    before = _read_tags(src)
    assert before["DateTimeOriginal"] == "2024:07:03 14:00:00" and before["GPSLatitude"] == 50.0
    dst = tmp_path / "lib" / "a.jpg"; (tmp_path / "lib").mkdir()
    utils._move_no_clobber(str(src), str(dst))                 # the same-fs merge placement (renameat2)
    assert _read_tags(dst) == before                           # EXIF time + GPS byte-identical


@pytest.mark.spec("merge-no-time-gps-changes-1")
def test_cross_fs_copy_placement_preserves_exif_time_and_gps(tmp_path):
    src = tmp_path / "a.jpg"
    _make_tagged_jpeg(src)
    before = _read_tags(src)
    dst = tmp_path / "lib" / "a.jpg"; (tmp_path / "lib").mkdir()
    utils._move_cross_fs_no_clobber(str(src), str(dst))        # the cross-fs placement (copy + verify)
    assert _read_tags(dst) == before                           # copy never re-encodes / edits tags
