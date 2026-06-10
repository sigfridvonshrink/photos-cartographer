"""Phase 3a (calibration) — photos-21-time-decisions.json: per-destination timezone + per-(camera
group, destination) offset cells, with the decision-field / rerun-preservation engine and the
SHA-256 dependency block (spec §17–§21). The GPX offset inference is Phase 3b. From conftest.py.
"""
import json
import os
import sys

import pytest

import photos_2_time_gps as cal
import photos_utils as utils

MANAGED = ["0-sources", "1-strays", "2-missing-metadata", "3-redundant-jpgs",
           "4-videos-by-date", "5-photos-by-date", "6-photos-by-dest"]
CAM = "SONY|ILCE-6400|123"
PHONE = "APPLE|iPhone|p1"


def _hfile(rel, *, key=CAM, dto="2024:07:03 14:12:08"):
    parsed = {"DateTimeOriginal": dto, "selected_source_naive_timestamp": dto,
              "selected_source_timestamp_tag": "DateTimeOriginal", "camera_group_key": key,
              "has_timestamp": True, "Make": "SONY", "Model": "ILCE-6400"}
    return {"relative_path": rel, "media_class": "image", "folder_class": "6-photos-by-dest",
            "size": 100, "mtime_ns": 1,
            "content_hash": json.dumps({"value": "fp-" + rel, "status": "valid"}),
            "metadata_status": {"camera_group_key": key, "has_timestamp": True,
                                "has_native_gps": False, "field_set_version": 1,
                                "parsed_json": json.dumps(parsed)}}


def _ws(tmp_path, *, files, device_groups, default_tz=""):
    ws = tmp_path / "ws"; ws.mkdir()
    for d in MANAGED:
        (ws / d).mkdir()
    ctl = ws / ".photos-ingest"; ctl.mkdir()
    (ctl / "photos-00-workspace-guard").touch()
    cfg = {k: v for k, v in utils.CONFIG.items() if k != "jobs"}
    cfg["camera_time_and_timezone_policy"] = dict(cfg["camera_time_and_timezone_policy"],
                                                  device_groups=device_groups,
                                                  default_folder_timezone=default_tz)
    (ctl / "photos-00-config.json").write_text(json.dumps(cfg))
    for rec in files:
        p = ws / rec["relative_path"]; p.parent.mkdir(parents=True, exist_ok=True); p.write_bytes(b"img")
    (ctl / "photos-11-handoff.json").write_text(json.dumps({"files": files}))
    return ws


def _run(monkeypatch, ws):
    monkeypatch.chdir(str(ws))
    monkeypatch.setattr(sys, "argv", ["photos-2-time-gps", "run"])
    try:
        cal.main(); return 0
    except SystemExit as e:
        return e.code if isinstance(e.code, int) else (0 if e.code is None else 1)


def _artifact(ws):
    with open(ws / ".photos-ingest" / cal.TIME_DECISIONS_ARTIFACT) as f:
        return json.load(f)


def _edit(ws, fn):
    art = _artifact(ws)
    fn(art)
    (ws / ".photos-ingest" / cal.TIME_DECISIONS_ARTIFACT).write_text(json.dumps(art, indent=2, sort_keys=True))


# --- first run ---------------------------------------------------------------

def test_first_run_writes_artifact_requiring_input(tmp_path, monkeypatch):
    ws = _ws(tmp_path, files=[_hfile("6-photos-by-dest/Brussels/a.jpg")],
             device_groups={"fixed_clock_cameras": [CAM], "phones": []})
    assert _run(monkeypatch, ws) == 0
    art = _artifact(ws)
    assert art["artifact_type"] == "time_decisions" and art["executable"] is False
    assert art["status"] == "requires_user_input" and art["requires_user_input"]
    d = art["destinations"]["6-photos-by-dest/Brussels"]
    assert d["destination_timezone"]["requires_user_input"]
    assert list(d["camera_group_time_decisions"]) == [CAM]
    assert d["camera_group_time_decisions"][CAM]["proposal"]["proposal_source"] == "manual_required"
    dep = art["depends_on"]
    assert dep["handoff"]["sha256"] and dep["camera_time_policy_fingerprint"] and dep["gpx_fingerprint"]


def test_smartphone_group_gets_no_offset_cell(tmp_path, monkeypatch):
    ws = _ws(tmp_path, files=[_hfile("6-photos-by-dest/Kyoto/p.jpg", key=PHONE)],
             device_groups={"fixed_clock_cameras": [], "phones": [PHONE]})
    assert _run(monkeypatch, ws) == 0
    d = _artifact(ws)["destinations"]["6-photos-by-dest/Kyoto"]
    assert d["camera_group_time_decisions"] == {}            # smartphones solved per-file
    assert d["destination_timezone"]["requires_user_input"]  # timezone still needs the user


# --- rerun preservation + completion -----------------------------------------

def test_rerun_preserves_decisions_and_completes(tmp_path, monkeypatch):
    ws = _ws(tmp_path, files=[_hfile("6-photos-by-dest/Brussels/a.jpg")],
             device_groups={"fixed_clock_cameras": [CAM], "phones": []}, default_tz="Europe/Brussels")
    _run(monkeypatch, ws)
    # the user accepts the proposed timezone and sets the camera's clock offset
    def fill(art):
        d = art["destinations"]["6-photos-by-dest/Brussels"]
        d["destination_timezone"]["user_decision"]["accept_proposed_timezone"] = True
        d["camera_group_time_decisions"][CAM]["user_decision"]["manual_offset_seconds"] = -7187
    _edit(ws, fill)
    assert _run(monkeypatch, ws) == 0
    art = _artifact(ws)
    d = art["destinations"]["6-photos-by-dest/Brussels"]
    assert d["destination_timezone"]["effective_iana_timezone"] == "Europe/Brussels"
    assert d["camera_group_time_decisions"][CAM]["effective_time_anchor"] == {"offset_seconds": -7187, "source": "manual"}
    assert art["status"] == "complete" and art["requires_user_input"] is False


def test_determinism_unchanged_rerun_is_byte_identical(tmp_path, monkeypatch):
    ws = _ws(tmp_path, files=[_hfile("6-photos-by-dest/Brussels/a.jpg")],
             device_groups={"fixed_clock_cameras": [CAM], "phones": []})
    _run(monkeypatch, ws)
    first = (ws / ".photos-ingest" / cal.TIME_DECISIONS_ARTIFACT).read_bytes()
    _run(monkeypatch, ws)
    assert (ws / ".photos-ingest" / cal.TIME_DECISIONS_ARTIFACT).read_bytes() == first


# --- validation (§9.2) -------------------------------------------------------

def test_bad_timezone_blocks_and_leaves_artifact(tmp_path, monkeypatch, capsys):
    ws = _ws(tmp_path, files=[_hfile("6-photos-by-dest/Brussels/a.jpg")],
             device_groups={"fixed_clock_cameras": [CAM], "phones": []})
    _run(monkeypatch, ws)
    _edit(ws, lambda a: a["destinations"]["6-photos-by-dest/Brussels"]["destination_timezone"]
          ["user_decision"].__setitem__("manual_iana_timezone", "Nowhere/Nope"))
    before = (ws / ".photos-ingest" / cal.TIME_DECISIONS_ARTIFACT).read_bytes()
    assert _run(monkeypatch, ws) == 2
    assert "not a valid IANA timezone" in capsys.readouterr().err
    assert (ws / ".photos-ingest" / cal.TIME_DECISIONS_ARTIFACT).read_bytes() == before   # untouched


def test_bad_offset_blocks(tmp_path, monkeypatch, capsys):
    ws = _ws(tmp_path, files=[_hfile("6-photos-by-dest/Brussels/a.jpg")],
             device_groups={"fixed_clock_cameras": [CAM], "phones": []})
    _run(monkeypatch, ws)
    _edit(ws, lambda a: a["destinations"]["6-photos-by-dest/Brussels"]["camera_group_time_decisions"]
          [CAM]["user_decision"].__setitem__("manual_offset_seconds", "not-a-number"))
    assert _run(monkeypatch, ws) == 2
    assert "manual_offset_seconds" in capsys.readouterr().err


# --- dependency block --------------------------------------------------------

def test_depends_on_reverifies(tmp_path, monkeypatch):
    ws = _ws(tmp_path, files=[_hfile("6-photos-by-dest/Brussels/a.jpg")],
             device_groups={"fixed_clock_cameras": [CAM], "phones": []})
    _run(monkeypatch, ws)
    dep = _artifact(ws)["depends_on"]["handoff"]
    assert utils.verify_json_dependency(dep, str(ws))                 # matches as written
    (ws / ".photos-ingest" / "photos-11-handoff.json").write_text('{"files": []}')
    assert not utils.verify_json_dependency(dep, str(ws))             # change detected


def test_timezone_proposal_inherits_nearest_resolved_ancestor():
    """A destination's timezone proposal prefers the nearest RESOLVED ancestor's timezone (confirmable)
    over the generic global default; a destination with no ancestor tz falls back to the default."""
    utils.CONFIG["camera_time_and_timezone_policy"]["default_folder_timezone"] = "Europe/Brussels"
    wf = cal.CalibrationWorkflow("/tmp/ws")
    blk = []
    # parent "Japan" resolved to Asia/Tokyo -> a deeper child inherits it, not the Brussels default
    eff_tz = {("6-photos-by-dest/Japan", "tz"): "Asia/Tokyo"}
    inh = cal._nearest_ancestor("6-photos-by-dest/Japan/Kyoto", eff_tz, "tz")
    child = wf._timezone_decision("6-photos-by-dest/Japan/Kyoto", {}, blk, inh)
    assert child["proposed_iana_timezone"] == "Asia/Tokyo"
    assert child["proposal_source"] == "inherited" and child["proposal_confidence"] == "review_required"
    assert child["inherited_from"] == "6-photos-by-dest/Japan"
    assert child["requires_user_input"] is True            # inherited is confirmable, never auto-applied
    # accepting the inherited proposal resolves it
    accepted = wf._timezone_decision("6-photos-by-dest/Japan/Kyoto",
                                     {"user_decision": {"accept_proposed_timezone": True}}, blk, inh)
    assert accepted["effective_iana_timezone"] == "Asia/Tokyo"
    # no ancestor tz -> the global default proposal
    top = wf._timezone_decision("6-photos-by-dest/Belgium", {}, blk, None)
    assert top["proposed_iana_timezone"] == "Europe/Brussels" and top["proposal_source"] == "config_default"
    assert "inherited_from" not in top
