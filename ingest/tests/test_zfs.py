"""Phase 8 — ZFS auto-detect + structured config + config validation.

Validation of human-authored config (the legal-prefix check), workspace-dataset detection
via `zfs list -H -o name <abspath>`, and the execute() snapshot path (success + required
failure). subprocess is mocked so no real `zfs` runs. Helpers come from conftest.py.
"""
import glob
import json
import os
import subprocess
import types

import pytest

import photos_1_prep as prep
import photos_utils as utils


def _ws(tmp_path):
    ws = tmp_path / "ws"
    ws.mkdir(parents=True)
    for d in ("0-sources", "2-missing-metadata", "3-redundant-jpgs",
              "4-videos-by-date", "5-photos-by-date", "6-photos-by-dest"):
        (ws / d).mkdir()
    (ws / ".photos-ingest").mkdir(exist_ok=True)
    (ws / ".photos-ingest" / "photos-00-workspace-guard").touch()
    return ws


def _mock_media(monkeypatch):
    monkeypatch.setattr(prep.ContentHasher, "hash_image",
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


def _intercept_zfs_snapshot(monkeypatch, fail=False):
    """Let everything run except `zfs snapshot ...`, which we fake (success or failure)."""
    real = prep.subprocess.run

    def fake(cmd, *a, **k):
        if isinstance(cmd, list) and cmd[:2] == ["zfs", "snapshot"]:
            if fail:
                raise subprocess.CalledProcessError(1, cmd, output="", stderr="boom")
            return types.SimpleNamespace(returncode=0, stdout="", stderr="")
        return real(cmd, *a, **k)
    monkeypatch.setattr(prep.subprocess, "run", fake)


# --- config validation (the "validate human-authored input" principle) -------

def test_validate_config_accepts_valid_zfs():
    utils.validate_config({"zfs": {"enabled": True, "snapshots_required": False,
                                   "snapshot_prefix": "photos-ingest-",
                                   "datasets": {"workspace": "auto", "library": "pool/lib"}}})


@pytest.mark.parametrize("bad", [
    {"zfs": {"snapshot_prefix": "bad name!"}},          # illegal char in prefix
    {"zfs": {"snapshot_prefix": "a/b"}},                # '/' not allowed in a snapshot name
    {"zfs": {"datasets": {"workspace": "has space"}}},  # illegal dataset
    {"zfs": {"enabled": "yes"}},                         # not a bool
    {"zfs": "nope"},                                     # not an object
])
def test_validate_config_rejects_illegal(bad):
    with pytest.raises(ValueError):
        utils.validate_config(bad)


def test_load_or_seed_config_rejects_illegal_zfs(tmp_path):
    ws = _ws(tmp_path)
    cfg = utils.config_path(str(ws))
    with open(cfg, "w") as f:
        json.dump({"zfs": {"snapshot_prefix": "bad prefix!"}}, f)
    with pytest.raises(ValueError, match="snapshot_prefix"):
        utils.load_or_seed_config(str(ws))


# --- dataset detection -------------------------------------------------------

def test_detect_zfs_dataset_uses_absolute_path(monkeypatch):
    captured = {}

    def fake(cmd, *a, **k):
        captured["cmd"] = list(cmd)
        return types.SimpleNamespace(returncode=0, stdout="pool/ds\n", stderr="")
    monkeypatch.setattr(subprocess, "run", fake)
    assert utils.detect_zfs_dataset(".") == "pool/ds"
    assert captured["cmd"][:4] == ["zfs", "list", "-H", "-o"]
    assert os.path.isabs(captured["cmd"][-1]) and captured["cmd"][-1] != "."   # never bare "."


def test_detect_zfs_dataset_returns_none_on_failure(monkeypatch):
    def fake(cmd, *a, **k):
        raise subprocess.CalledProcessError(1, cmd)
    monkeypatch.setattr(subprocess, "run", fake)
    assert utils.detect_zfs_dataset("/tmp") is None


# --- execute() snapshot path -------------------------------------------------

def _plan(ws):
    prep.CONFIG["jobs"] = 1
    cache = prep.WorkspaceCache(str(ws))
    plan = prep.WorkspacePrepWorkflow(str(ws), cache).plan()
    cache.close()
    return plan


def test_snapshot_taken_with_detected_dataset_and_prefix(tmp_path, monkeypatch):
    _mock_media(monkeypatch)
    monkeypatch.setattr(utils, "detect_zfs_dataset", lambda p: "pool/ws")
    _intercept_zfs_snapshot(monkeypatch, fail=False)
    prep.CONFIG["zfs"] = {"enabled": True, "snapshots_required": True,
                          "snapshot_prefix": "photos-ingest-", "datasets": {"workspace": "auto"}}
    ws = _ws(tmp_path)
    (ws / "0-sources" / "a.jpg").write_bytes(b"AAAA")
    plan = _plan(ws)
    prep.PlanExecutor(str(ws)).execute(plan)
    j = json.load(open(glob.glob(str(ws / ".photos-ingest" / "journal-*.json"))[0]))
    snap = j["snapshots"]["workspace"]
    assert snap["exit_code"] == 0
    assert snap["snapshot_name"] == f"pool/ws@photos-ingest-{plan.plan_id}"


def test_required_snapshot_with_no_dataset_aborts(tmp_path, monkeypatch):
    _mock_media(monkeypatch)
    monkeypatch.setattr(utils, "detect_zfs_dataset", lambda p: None)   # workspace not on zfs
    prep.CONFIG["zfs"] = {"enabled": True, "snapshots_required": True,
                          "snapshot_prefix": "photos-ingest-", "datasets": {"workspace": "auto"}}
    ws = _ws(tmp_path)
    (ws / "0-sources" / "a.jpg").write_bytes(b"AAAA")
    plan = _plan(ws)
    with pytest.raises(RuntimeError, match="no dataset found"):
        prep.PlanExecutor(str(ws)).execute(plan)
    assert os.path.exists(ws / "0-sources" / "a.jpg")                  # no mutation
