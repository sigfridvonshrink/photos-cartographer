"""External-tool dependency preflight (shared contract: decline cleanly, never crash mid-run when
exiftool/ffmpeg/magick is absent). Covers the photos_utils helpers, the soft ffmpeg fingerprint
fallback, the exiftool-worker guard, and the phase wiring (prep plan hard-stop, geotag blocker).

photos_utils / photos_1_prep / photos_2_time_gps come from conftest.py.
"""
import json
import types

import pytest

import photos_utils as utils
import photos_1_prep as prep
import photos_2_time_gps as cal

MANAGED = ["0-sources", "1-strays", "2-missing-metadata", "3-redundant-jpgs",
           "4-videos-by-date", "5-photos-by-date", "6-photos-by-dest"]


# --- helpers -----------------------------------------------------------------

def _which(present):
    """A shutil.which stand-in: returns a fake path for names in `present`, else None."""
    return lambda name: ("/usr/bin/" + name) if name in present else None


def _ws(tmp_path, bydest=("6-photos-by-dest/Trip/a.jpg",)):
    ws = tmp_path / "ws"
    ws.mkdir()
    for d in MANAGED:
        (ws / d).mkdir()
    ctl = ws / ".photos-ingest"
    ctl.mkdir()
    (ctl / "photos-00-workspace-guard").touch()
    cfg = {k: v for k, v in utils.CONFIG.items() if k != "jobs"}
    (ctl / "photos-00-config.json").write_text(json.dumps(cfg))
    for rel in bydest:
        p = ws / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(b"img")
    files = [{"relative_path": rel, "media_class": "image"} for rel in bydest]
    (ctl / "photos-11-handoff.json").write_text(json.dumps({"files": files}))
    return ws


# --- photos_utils helpers ----------------------------------------------------

def test_missing_tools_reports_only_absent(monkeypatch):
    monkeypatch.setattr(utils.shutil, "which", _which({"exiftool", "ffmpeg"}))
    assert utils.missing_tools(["exiftool", "magick", "ffmpeg"]) == ["magick"]
    assert utils.missing_tools(["exiftool", "ffmpeg"]) == []


def test_require_tools_raises_listing_all_missing(monkeypatch):
    monkeypatch.setattr(utils.shutil, "which", _which({"exiftool"}))
    with pytest.raises(utils.MissingToolError) as ei:
        utils.require_tools(["exiftool", "magick", "ffmpeg"], context="prep")
    assert ei.value.missing == ["magick", "ffmpeg"]
    assert "magick" in str(ei.value) and "ffmpeg" in str(ei.value) and "prep" in str(ei.value)


def test_require_tools_noop_when_all_present(monkeypatch):
    monkeypatch.setattr(utils.shutil, "which", _which({"exiftool", "magick"}))
    utils.require_tools(["exiftool", "magick"])   # must not raise


# --- ffmpeg soft fallback ----------------------------------------------------

def test_fingerprint_video_declines_when_ffmpeg_absent(monkeypatch):
    def _boom(*a, **k):
        raise FileNotFoundError("ffmpeg")
    monkeypatch.setattr(utils.subprocess, "run", _boom)
    res = utils.ContentHasher.fingerprint_video("/whatever.mp4")
    assert res["status"] == "failed"
    assert res["value"] is None
    assert "ffmpeg not found" in res["error"]


# --- exiftool worker guard (defense-in-depth) --------------------------------

def test_exiftool_worker_raises_clear_error_when_absent(monkeypatch):
    monkeypatch.setattr(utils.shutil, "which", _which(set()))   # nothing on PATH
    with pytest.raises(utils.MissingToolError) as ei:
        utils.PersistentExifToolWorker()
    assert ei.value.missing == ["exiftool"]


# --- phase wiring ------------------------------------------------------------

def test_geotag_preflight_blocks_when_exiftool_absent(tmp_path, monkeypatch):
    monkeypatch.setattr("photos_utils.missing_tools",
                        lambda tools: [t for t in tools if t == "exiftool"])
    blockers, _warnings, _info = cal.GeotagWorkflow(str(_ws(tmp_path))).preflight()
    assert any("exiftool" in b for b in blockers), blockers


def test_prep_plan_exits_when_exiftool_absent(tmp_path, monkeypatch):
    monkeypatch.chdir(_ws(tmp_path))
    monkeypatch.setattr("photos_utils.missing_tools",
                        lambda tools: ["exiftool"] if "exiftool" in tools else [])
    args = types.SimpleNamespace(command="plan", jobs=1)
    with pytest.raises(SystemExit) as ei:
        prep.run(args)
    assert ei.value.code == 3
