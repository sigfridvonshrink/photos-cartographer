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

"""A link among the managed files is never followed: a link to a folder is never entered, and a managed folder that is
itself a link is never walked — nothing under its target is read, inventoried or found."""
import os

import pytest

import photos_1_prep as prep
import photos_utils as utils

MANAGED = ("0-sources", "1-strays", "2-missing-metadata", "3-redundant-jpgs",
           "4-videos-by-date", "5-photos-by-date", "6-photos-by-dest")


def _initialized_ws(tmp_path):
    ws = tmp_path / "ws"; ws.mkdir()
    (ws / ".photos-ingest").mkdir(); (ws / ".photos-ingest" / "photos-00-workspace-guard").touch()
    for d in MANAGED:
        (ws / d).mkdir()
    return ws


def _plan_reading(monkeypatch, ws):
    """Prep's plan of `ws`, its scan run in-process; returns the plan and every path its fingerprinting and its
    metadata reading were given."""
    read = []

    def metadata(folders, max_workers=4, progress_coordinator=None):
        read.extend(folders)
        return {}, set()

    def fingerprint(p):
        read.append(p)
        return {"status": "valid", "value": "sig-" + os.path.basename(p), "strategy": "image-content-hash-v2",
                "engine_version": "t"}
    monkeypatch.setattr(utils.MetadataReader, "read_metadata_concurrently", staticmethod(metadata))
    monkeypatch.setattr(prep.ContentHasher, "fingerprint_image", staticmethod(fingerprint))
    monkeypatch.setattr(prep.ContentHasher, "fingerprint_video", staticmethod(fingerprint))
    prep.CONFIG["jobs"] = 1
    cache = prep.WorkspaceCache(str(ws), in_memory=True)
    try:
        plan = prep.WorkspacePrepWorkflow(str(ws), cache).plan()
    finally:
        cache.close()
    return plan, read


def _external(tmp_path):
    """A folder outside the workspace, holding a photo and a folder with another."""
    ext = tmp_path / "external"; (ext / "deeper").mkdir(parents=True)
    (ext / "outside.jpg").write_bytes(b"PRECIOUS")
    (ext / "deeper" / "further.jpg").write_bytes(b"PRECIOUS TOO")
    return ext


def _under(paths, ws, link_rel, ext):
    """The paths among `paths` that lie under the link `link_rel` or its target `ext`."""
    link = os.path.join(str(ws), link_rel)
    return [p for p in paths
            if os.path.realpath(os.path.join(str(ws), p)).startswith(os.path.realpath(str(ext)) + os.sep)
            or os.path.join(str(ws), p).startswith(link + os.sep)]


@pytest.mark.parametrize("where", ["0-sources/inbox-link", "5-photos-by-date/2024-07-03/day-link",
                                   "6-photos-by-dest/Trip/trip-link"])
@pytest.mark.spec("RUL-link_never_followed", test="TST-links_never_followed-a_link_to_a_folder_is_never_entered")
def test_a_link_to_a_folder_is_never_entered(tmp_path, monkeypatch, where):
    """A link to a folder inside a managed folder is never entered: prep's plan finds the link and blocks on it, but
    nothing under its target is inventoried, fingerprinted or read for its metadata — while the photo beside it is."""
    ext = _external(tmp_path)
    ws = _initialized_ws(tmp_path)
    beside = os.path.join(os.path.dirname(where), "beside.jpg")
    (ws / os.path.dirname(where)).mkdir(parents=True, exist_ok=True)
    (ws / beside).write_bytes(b"a photo of the workspace")
    os.symlink(str(ext), str(ws / where))
    plan, read = _plan_reading(monkeypatch, ws)
    assert any("Forbidden symlink detected" in b and where in b for b in plan.blockers), plan.blockers
    assert beside in plan.inventory, plan.inventory                       # the scan did run beside it
    assert _under(plan.inventory, ws, where, ext) == [], plan.inventory
    assert _under([os.path.relpath(p, str(ws)) for p in read], ws, where, ext) == [], read


@pytest.mark.parametrize("folder", ["0-sources", "5-photos-by-date", "6-photos-by-dest"])
@pytest.mark.spec("RUL-link_never_followed", test="TST-links_never_followed-a_managed_folder_that_is_a_link_is_never_walked")
def test_a_managed_folder_that_is_a_link_is_never_walked(tmp_path, monkeypatch, folder):
    """A managed folder that is itself a link is never walked: the plan blocks on it, and nothing under its target is
    inventoried, fingerprinted or read for its metadata."""
    ext = _external(tmp_path)
    ws = _initialized_ws(tmp_path)
    (ws / "2-missing-metadata" / "kept.jpg").write_bytes(b"a photo of the workspace")
    os.rmdir(ws / folder)
    os.symlink(str(ext), str(ws / folder))
    plan, read = _plan_reading(monkeypatch, ws)
    assert any(b.endswith(f"Forbidden symlink detected: {folder}") for b in plan.blockers), plan.blockers
    assert "2-missing-metadata/kept.jpg" in plan.inventory, plan.inventory
    assert _under(plan.inventory, ws, folder, ext) == [], plan.inventory
    assert _under([os.path.relpath(p, str(ws)) for p in read], ws, folder, ext) == [], read


@pytest.mark.spec("RUL-link_never_followed", test="TST-links_never_followed-the_links_check_never_enters_a_linked_folder")
def test_the_links_check_never_enters_a_linked_folder(tmp_path):
    """Geotag's and merge's check for links among the photos by destination names a link to a folder and never enters
    it: a link inside its target is not found through it."""
    ext = _external(tmp_path)
    os.symlink(str(ext / "deeper"), str(ext / "inner-link"))              # a link inside the target
    ws = _initialized_ws(tmp_path)
    (ws / "6-photos-by-dest" / "Trip").mkdir()
    (ws / "6-photos-by-dest" / "Trip" / "a.jpg").write_bytes(b"a photo")
    os.symlink(str(ext), str(ws / "6-photos-by-dest" / "Trip" / "trip-link"))
    assert utils.links_under(str(ws), "6-photos-by-dest") == ["6-photos-by-dest/Trip/trip-link"]
