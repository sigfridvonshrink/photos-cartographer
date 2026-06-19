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

"""Phase 9 — atomic no-clobber at execution time (prep §4 / §14.3.4).

The executor's move must fail rather than overwrite an existing destination, atomically,
even if planning missed the clobber or the filesystem mutated just before the op.

photos_1_prep / photos_utils come from conftest.py.
"""
import os

import pytest

import photos_1_prep as prep
import photos_utils as utils


# --- the atomic primitive ----------------------------------------------------

def test_move_no_clobber_moves_when_free(tmp_path):
    src = tmp_path / "a"; src.write_bytes(b"SRC")
    dest = tmp_path / "b"
    prep._move_no_clobber(str(src), str(dest))
    assert dest.read_bytes() == b"SRC"
    assert not src.exists()


def test_move_no_clobber_refuses_and_preserves(tmp_path):
    src = tmp_path / "a"; src.write_bytes(b"SRC")
    dest = tmp_path / "b"; dest.write_bytes(b"KEEP")
    with pytest.raises(FileExistsError):
        prep._move_no_clobber(str(src), str(dest))
    assert dest.read_bytes() == b"KEEP"     # not overwritten
    assert src.read_bytes() == b"SRC"       # source untouched


def test_move_link_unlink_fallback_parity(tmp_path):
    # move-when-free
    src = tmp_path / "s1"; src.write_bytes(b"X")
    dest = tmp_path / "d1"
    prep._move_link_unlink(str(src), str(dest))
    assert dest.read_bytes() == b"X" and not src.exists()
    # refuse-and-preserve
    src2 = tmp_path / "s2"; src2.write_bytes(b"Y")
    dest2 = tmp_path / "d2"; dest2.write_bytes(b"KEEP")
    with pytest.raises(FileExistsError):
        prep._move_link_unlink(str(src2), str(dest2))
    assert dest2.read_bytes() == b"KEEP" and src2.read_bytes() == b"Y"


# --- execution-time enforcement ----------------------------------------------

def _ws(tmp_path):
    ws = tmp_path / "ws"
    ws.mkdir()
    for d in ("0-sources", "1-strays", "2-missing-metadata", "3-redundant-jpgs",
              "4-videos-by-date", "5-photos-by-date", "6-photos-by-dest"):
        (ws / d).mkdir()
    (ws / ".photos-ingest").mkdir(exist_ok=True)
    (ws / ".photos-ingest" / "photos-00-workspace-guard").touch()
    return ws


def _install(monkeypatch):
    prep.CONFIG["zfs"] = {"enabled": False}
    monkeypatch.setattr(prep.ContentHasher, "fingerprint_image",
                        lambda p: {"status": "valid", "strategy": "image-content-hash-v1",
                                   "value": "sig-" + os.path.basename(p), "engine_version": "t"})

    def meta(folders, max_workers=4, progress_coordinator=None):
        res = {}
        for folder in folders:
            for f in os.listdir(folder):
                res[os.path.join(folder, f)] = {"DateTimeOriginal": "2023:01:02 03:04:05",
                                                "extraction_status": "extracted_ok", "raw_payload": "{}"}
        return res, set()
    monkeypatch.setattr(utils.MetadataReader, "read_metadata_concurrently", meta)


def test_execute_time_no_clobber_preserves_existing(tmp_path, monkeypatch):
    # The user's "planning somehow failed to catch it" case: bypass the plan-time clobber
    # simulation, place a file at the planned destination, and confirm the executor itself
    # refuses to overwrite it.
    _install(monkeypatch)
    prep.CONFIG["jobs"] = 1
    ws = _ws(tmp_path)
    (ws / "0-sources" / "a.jpg").write_bytes(b"ORIGINAL")
    cache = prep.WorkspaceCache(str(ws))
    plan = prep.WorkspacePrepWorkflow(str(ws), cache).plan()
    cache.close()

    org = [op for op in plan.operations
           if op.type == "move_no_clobber" and op.source == "0-sources/a.jpg"][0]
    dest_abs = ws / org.destination
    dest_abs.parent.mkdir(parents=True, exist_ok=True)
    dest_abs.write_bytes(b"SENTINEL")                       # squatter at the planned dest

    monkeypatch.setattr(prep.PlanValidator, "validate_plan_preflight",
                        staticmethod(lambda *a, **k: None))  # simulate planning missing it

    with pytest.raises(Exception):
        prep.PlanExecutor(str(ws)).execute(plan)

    assert dest_abs.read_bytes() == b"SENTINEL"            # NOT overwritten
    assert (ws / "0-sources" / "a.jpg").read_bytes() == b"ORIGINAL"   # source not moved


# --- RootGuard.resolve_and_check_path (the path-safety primitive) -------------

def test_resolve_rejects_parent_traversal(tmp_path):
    with pytest.raises(ValueError, match="Directory traversal"):
        prep.RootGuard.resolve_and_check_path(str(tmp_path), "a/../../etc/passwd")


def test_resolve_rejects_absolute_when_relative_required(tmp_path):
    with pytest.raises(ValueError, match="must be relative"):
        prep.RootGuard.resolve_and_check_path(str(tmp_path), "/etc/passwd")


def test_resolve_rejects_escape_outside_base(tmp_path):
    # an absolute path that resolves outside base (must_be_relative=False bypasses the abs check)
    outside = tmp_path.parent / "elsewhere"
    with pytest.raises(ValueError, match="escape detected|outside"):
        prep.RootGuard.resolve_and_check_path(str(tmp_path), str(outside), must_be_relative=False)


def test_resolve_accepts_contained_relative(tmp_path):
    got = prep.RootGuard.resolve_and_check_path(str(tmp_path), "sub/x.jpg")
    assert got == os.path.join(os.path.realpath(str(tmp_path)), "sub", "x.jpg")
