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

"""Externalised seed defaults (photos_utils.default_config): a `photos-config-defaults.json` sibling of
the executable — or $PHOTOS_PIPELINE_CONFIG — overrides the built-in DEFAULT_CONFIG, so a detached
deploy retunes new-workspace defaults without editing the zip. From conftest.py."""
import json
import os

import pytest

import photos_utils as u


def test_falls_back_to_builtin(monkeypatch):
    monkeypatch.delenv("PHOTOS_PIPELINE_CONFIG", raising=False)
    monkeypatch.setattr(u.sys, "argv", ["photos-cartographer"])     # no sibling next to a bare prog name
    assert u.default_config()["gpx_root"] == u.DEFAULT_CONFIG["gpx_root"]


def test_env_path_overrides_builtin(tmp_path, monkeypatch):
    cfg = json.loads(json.dumps(u.DEFAULT_CONFIG)); cfg["gpx_root"] = "/custom/gpx"
    p = tmp_path / "ext.json"; p.write_text(json.dumps(cfg))
    monkeypatch.setenv("PHOTOS_PIPELINE_CONFIG", str(p))
    assert u.default_config()["gpx_root"] == "/custom/gpx"


def test_sibling_of_executable_overrides_builtin(tmp_path, monkeypatch):
    monkeypatch.delenv("PHOTOS_PIPELINE_CONFIG", raising=False)
    exe = tmp_path / "photos-cartographer"; exe.write_text("")
    cfg = json.loads(json.dumps(u.DEFAULT_CONFIG)); cfg["gpx_root"] = "/sibling/gpx"
    (tmp_path / "photos-config-defaults.json").write_text(json.dumps(cfg))
    monkeypatch.setattr(u.sys, "argv", [str(exe)])
    assert u.default_config()["gpx_root"] == "/sibling/gpx"


def test_env_beats_sibling(tmp_path, monkeypatch):
    exe = tmp_path / "photos-cartographer"; exe.write_text("")
    sib = json.loads(json.dumps(u.DEFAULT_CONFIG)); sib["gpx_root"] = "/sibling"
    (tmp_path / "photos-config-defaults.json").write_text(json.dumps(sib))
    env = json.loads(json.dumps(u.DEFAULT_CONFIG)); env["gpx_root"] = "/env"
    envp = tmp_path / "env.json"; envp.write_text(json.dumps(env))
    monkeypatch.setattr(u.sys, "argv", [str(exe)])
    monkeypatch.setenv("PHOTOS_PIPELINE_CONFIG", str(envp))
    assert u.default_config()["gpx_root"] == "/env"


def test_invalid_external_is_a_hard_error(tmp_path, monkeypatch):
    bad = tmp_path / "bad.json"; bad.write_text('{"folders": {}}')   # missing required structure
    monkeypatch.setenv("PHOTOS_PIPELINE_CONFIG", str(bad))
    with pytest.raises(ValueError):
        u.default_config()


def test_seed_uses_default_config(tmp_path, monkeypatch):
    cfg = json.loads(json.dumps(u.DEFAULT_CONFIG)); cfg["gpx_root"] = "/seeded/from/external"
    p = tmp_path / "ext.json"; p.write_text(json.dumps(cfg))
    monkeypatch.setenv("PHOTOS_PIPELINE_CONFIG", str(p))
    ws = tmp_path / "ws"; (ws / ".photos-ingest").mkdir(parents=True)
    u.load_or_seed_config(str(ws))
    seeded = json.load(open(ws / ".photos-ingest" / "photos-00-config.json"))
    assert seeded["gpx_root"] == "/seeded/from/external"      # new workspace seeded from the external file
