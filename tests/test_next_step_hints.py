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

"""Closing 'Next: …' operator guidance (shared contract Section 10).

Every phase command ends its output with a single `Next: …` line stating the next action for the
state it produced. These tests drive prep's `run()` and assert the line for the success, blocked, and
nothing-to-do outcomes; the geotag/merge equivalents are asserted in their own phase test files.
"""
import os
import types

import photos_1_prep as prep
import photos_utils as utils

MANAGED = ["0-sources", "1-strays", "2-missing-metadata", "3-redundant-jpgs",
           "4-videos-by-date", "5-photos-by-date", "6-photos-by-dest"]


def _initialized(tmp_path):
    ws = tmp_path / "ws"
    ws.mkdir()
    for d in MANAGED:
        (ws / d).mkdir()
    (ws / ".photos-ingest").mkdir()
    (ws / ".photos-ingest" / "photos-00-workspace-guard").touch()
    return ws


def _install(monkeypatch):
    prep.CONFIG["zfs"] = {"enabled": False}
    prep.CONFIG["jobs"] = 1

    def hsh(p):
        with open(p, "rb") as f:
            return {"status": "valid", "strategy": "image-content-hash-v1",
                    "value": "sig-" + f.read().hex()[:16], "engine_version": "t"}
    monkeypatch.setattr(prep.ContentHasher, "fingerprint_image", hsh)

    def meta(folders, max_workers=4, progress_coordinator=None):
        res = {}
        for fo in folders:
            for fn in os.listdir(fo):
                res[os.path.join(fo, fn)] = {"DateTimeOriginal": "2023:01:02 03:04:05",
                                             "extraction_status": "extracted_ok", "raw_payload": "{}"}
        return res, set()
    monkeypatch.setattr(utils.MetadataReader, "read_metadata_concurrently", meta)


def _run(monkeypatch, ws, command):
    from cartographer.reporting import Reporter, CaptureSink, use_reporter
    monkeypatch.chdir(ws)
    cap = CaptureSink()
    with use_reporter(Reporter([cap])):
        try:
            prep.run(types.SimpleNamespace(command=command, jobs=1))
        except SystemExit:
            pass
    return "\n".join(e.msg for e in cap.logs())


def test_prep_plan_clean_hints_dry_run_or_execute(tmp_path, monkeypatch):
    # A clean plan (a single media file, no blockers) ends by pointing at the two ways forward.
    _install(monkeypatch)
    ws = _initialized(tmp_path)
    (ws / "0-sources" / "a.jpg").write_bytes(b"\xff\xd8\xff\xd9")
    blob = _run(monkeypatch, ws, "plan")
    assert "Next: `prep dry-run` to review the plan, or `prep execute` to apply." in blob


def test_prep_plan_blocked_hints_fix_then_replan(tmp_path, monkeypatch):
    # A stray directory at the workspace root is a blocker; the closing line tells the operator to fix
    # it and re-run `prep plan`, not to proceed to dry-run/execute.
    _install(monkeypatch)
    ws = _initialized(tmp_path)
    (ws / "0-sources" / "a.jpg").write_bytes(b"\xff\xd8\xff\xd9")
    (ws / "stray-dir").mkdir()                      # belongs in 0-sources -> blocker
    blob = _run(monkeypatch, ws, "plan")
    assert "Next: fix the blocker(s) above, then re-run `prep plan`." in blob
    assert "`prep dry-run` to review" not in blob   # the clean hint must NOT also appear


def test_prep_nothing_to_do_hints_sort_then_geotag(tmp_path, monkeypatch):
    # An already-prepped workspace with an empty 0-sources is "nothing to do" — the next move is to
    # sort into by-dest and run geotag, so the hint points there.
    _install(monkeypatch)
    ws = _initialized(tmp_path)                     # empty 0-sources
    (ws / ".photos-ingest" / "photos-10-prep-plan.json").write_text(
        '{"plan_id": "stale", "command": "prep", "operations": []}')
    blob = _run(monkeypatch, ws, "execute")
    bd = utils.folder_name("photos_by_dest")
    assert f"Next: sort photos into {bd}, then `geotag plan`" in blob
