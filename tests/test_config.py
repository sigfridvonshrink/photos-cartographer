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

"""Phase 2 — photos-00-config.json lifecycle.

Verifies that prep seeds the per-workspace config on first run, reads it as
authoritative thereafter, derives the config fingerprint from the file, and never
persists the runtime `jobs` override.

Uses mocked hashing/metadata so these are fast and need no external tools.
photos_1_prep / photos_utils are loaded once by conftest.py into sys.modules.
"""
import hashlib
import json
import os

import pytest

import photos_1_prep as prep
import photos_utils as utils


def _ws(tmp_path):
    ws = tmp_path / "ws"
    ws.mkdir()
    for d in ("0-sources", "1-strays", "2-missing-metadata", "3-redundant-jpgs",
              "4-videos-by-date", "5-photos-by-date", "6-photos-by-dest"):
        (ws / d).mkdir()
    (ws / ".photos-ingest").mkdir(exist_ok=True)
    (ws / ".photos-ingest" / "photos-00-workspace-guard").touch()
    return ws


def _mock(monkeypatch):
    monkeypatch.setattr(
        prep.ContentHasher, "fingerprint_image",
        lambda p: {"status": "valid", "strategy": "image-content-hash-v1",
                   "value": "sig-" + os.path.basename(p), "engine_version": "t"},
    )

    def meta(folders, max_workers=4, progress_coordinator=None):
        res = {}
        for folder in folders:
            for f in os.listdir(folder):
                res[os.path.join(folder, f)] = {
                    "DateTimeOriginal": "2023:01:02 03:04:05",
                    "extraction_status": "extracted_ok", "raw_payload": "{}",
                }
        return res, set()

    monkeypatch.setattr(utils.MetadataReader, "read_metadata_concurrently", meta)


def _plan(ws):
    return prep.WorkspacePrepWorkflow(str(ws), prep.WorkspaceCache(str(ws), in_memory=True)).plan()


def test_first_plan_seeds_config_without_jobs(tmp_path, monkeypatch):
    _mock(monkeypatch)
    ws = _ws(tmp_path)
    prep.CONFIG["jobs"] = 1
    assert not os.path.exists(utils.config_path(str(ws)))

    _plan(ws)

    cfg_path = utils.config_path(str(ws))
    assert os.path.exists(cfg_path)
    with open(cfg_path) as f:
        seeded = json.load(f)
    assert "jobs" not in seeded
    # The seeded file equals the in-code template minus the runtime jobs override.
    assert seeded == {k: v for k, v in utils.CONFIG.items() if k != "jobs"}


def test_rerun_does_not_rewrite_config(tmp_path, monkeypatch):
    _mock(monkeypatch)
    ws = _ws(tmp_path)
    prep.CONFIG["jobs"] = 1

    _plan(ws)
    raw1 = open(utils.config_path(str(ws)), "rb").read()
    _plan(ws)
    raw2 = open(utils.config_path(str(ws)), "rb").read()
    assert raw1 == raw2  # prep is the sole writer and seeds only once


def test_handwritten_config_is_authoritative(tmp_path, monkeypatch):
    _mock(monkeypatch)
    ws = _ws(tmp_path)
    prep.CONFIG["jobs"] = 1
    # Pre-write a config with a custom filename format; the file must win over the in-code dict.
    cfg = {k: v for k, v in utils.CONFIG.items() if k != "jobs"}
    cfg["filename_timestamp_format"] = "%Y%m%d__%H%M%S"
    with open(utils.config_path(str(ws)), "w") as f:
        json.dump(cfg, f)
    (ws / "0-sources" / "a.jpg").write_text("aaa")

    plan = _plan(ws)
    dests = [op.destination for op in plan.operations if op.destination]
    # DateTimeOriginal 2023:01:02 03:04:05 under the custom format.
    assert any("5-photos-by-date/2023-01-02/20230102__030405" in d for d in dests), dests


def test_config_fingerprint_is_file_sha_and_in_handoff(tmp_path, monkeypatch):
    _mock(monkeypatch)
    ws = _ws(tmp_path)
    prep.CONFIG["jobs"] = 1
    (ws / "0-sources" / "a.jpg").write_text("aaa")

    cache = prep.WorkspaceCache(str(ws))
    plan = prep.WorkspacePrepWorkflow(str(ws), cache).plan()
    cache.close()

    file_sha = hashlib.sha256(open(utils.config_path(str(ws)), "rb").read()).hexdigest()
    assert plan.config_fingerprint.algorithm == "sha256"
    assert plan.config_fingerprint.value == file_sha

    prep.PlanExecutor(str(ws)).execute(plan)
    with open(utils.handoff_path(str(ws))) as f:
        handoff = json.load(f)
    assert handoff["depends_on"]["effective_config"]["fingerprint"] == file_sha


def test_malformed_config_raises(tmp_path):
    ws = _ws(tmp_path)
    with open(utils.config_path(str(ws)), "w") as f:
        f.write("{ this is not valid json ")
    with pytest.raises(ValueError, match="not valid JSON"):
        utils.load_or_seed_config(str(ws))
