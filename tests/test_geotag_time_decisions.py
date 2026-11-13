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

"""Phase 3a (geotag) — photos-21-time-decisions.json: per-destination timezone + per-(camera
group, destination) offset cells, with the decision-field / rerun-preservation engine and the
SHA-256 dependency block (spec §17–§21). The GPX offset inference is Phase 3b. From conftest.py.
"""
import json
from _handoff import match_disk
import os
import sys
from datetime import datetime, timezone

import pytest

import photos_2_geotag as cal
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
            "metadata_status": {"camera_group_key_version": utils.CAMERA_GROUP_KEY_VERSION,
                                "camera_group_key": key, "has_timestamp": True,
                                "has_native_gps": False, "field_set_version": utils.FIELD_SET_VERSION,
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
    (ctl / "photos-11-handoff.json").write_text(json.dumps({"filename_timestamp_format": utils.CONFIG["filename_timestamp_format"], "files": match_disk(ws, files)}))
    return ws


def _run(monkeypatch, ws):
    monkeypatch.chdir(str(ws))
    monkeypatch.setattr(sys, "argv", ["photos-2-geotag", "plan"])
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

@pytest.mark.spec("geotag-timezone-every-destination-1")
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
    assert dep["handoff"]["content_fingerprint"] and dep["camera_time_policy_fingerprint"] and dep["gpx_fingerprint"]


def test_smartphone_group_gets_no_offset_cell(tmp_path, monkeypatch):
    ws = _ws(tmp_path, files=[_hfile("6-photos-by-dest/Kyoto/p.jpg", key=PHONE)],
             device_groups={"fixed_clock_cameras": [], "phones": [PHONE]})
    assert _run(monkeypatch, ws) == 0
    d = _artifact(ws)["destinations"]["6-photos-by-dest/Kyoto"]
    assert d["camera_group_time_decisions"] == {}            # smartphones solved per-file
    assert d["destination_timezone"]["requires_user_input"]  # timezone still needs the user


# --- rerun preservation + completion -----------------------------------------

@pytest.mark.spec("authored-fields-not-overwritten-1", "geotag-decision-fields-precreated-1", "geotag-preserve-user-decisions-1", "loop-geotag-rerun-safe-1", "RUL-decision_kept", "RUL-decision_fields_laid_out", test="TST-geotag_time_decisions-rerun_preserves_decisions_and_completes")
def test_rerun_preserves_decisions_and_completes(tmp_path, monkeypatch):
    ws = _ws(tmp_path, files=[_hfile("6-photos-by-dest/Brussels/a.jpg")],
             device_groups={"fixed_clock_cameras": [CAM], "phones": []}, default_tz="Europe/Brussels")
    _run(monkeypatch, ws)
    # the user sets the camera's clock offset (the proposed timezone applies itself)
    def fill(art):
        d = art["destinations"]["6-photos-by-dest/Brussels"]
        d["camera_group_time_decisions"][CAM]["user_decision"]["manual_offset_seconds"] = -7187
    _edit(ws, fill)
    assert _run(monkeypatch, ws) == 0
    art = _artifact(ws)
    d = art["destinations"]["6-photos-by-dest/Brussels"]
    assert d["destination_timezone"]["effective_iana_timezone"] == "Europe/Brussels"
    assert d["camera_group_time_decisions"][CAM]["effective_time_anchor"] == {"offset_seconds": -7187, "source": "manual"}
    assert art["status"] == "complete" and art["requires_user_input"] is False


@pytest.mark.spec("RUL-geotag_rerunnable", "loop-geotag-rerunnable-1", test="TST-geotag_time_decisions-rerun_after_success_admitted_until_sealed")
def test_rerun_after_success_admitted_until_sealed(tmp_path, monkeypatch):
    """A successful execution and a finalize leave geotag re-runnable; only merge's seal stops it."""
    ws = _ws(tmp_path, files=[_hfile("6-photos-by-dest/Brussels/a.jpg")],
             device_groups={"fixed_clock_cameras": [CAM], "phones": []}, default_tz="Europe/Brussels")
    ctl = ws / ".photos-ingest"
    (ctl / "photos-25-execution-summary.json").write_text('{"status": "success"}')
    (ctl / "photos-26-complete-log.json").write_text('{"photos": {}}')
    (ctl / "photos-26-archive-manifest.json").write_text('{"artifact_name": "m"}')
    assert _run(monkeypatch, ws) == 0
    first = _artifact(ws)
    assert _run(monkeypatch, ws) == 0 and _artifact(ws) == first
    (ctl / "photos-00-sealed.json").write_text('{"sealed": true, "merged_run_id": "r1"}')
    (ctl / cal.TIME_DECISIONS_ARTIFACT).unlink()
    assert _run(monkeypatch, ws) == 2
    assert not (ctl / cal.TIME_DECISIONS_ARTIFACT).exists()


@pytest.mark.spec("RUL-rerun_does_what_changed", "loop-rerun-may-need-decisions-1", "RUL-decision_kept", test="TST-geotag_time_decisions-new_destination_asks_only_its_own_decisions")
def test_new_destination_asks_only_its_own_decisions(tmp_path, monkeypatch):
    """Media added to a new destination asks for that destination's decisions alone; every settled
    decision elsewhere stays as the user left it."""
    ws = _ws(tmp_path, files=[_hfile("6-photos-by-dest/Brussels/a.jpg")],
             device_groups={"fixed_clock_cameras": [CAM], "phones": []}, default_tz="Europe/Brussels")
    _run(monkeypatch, ws)
    def fill(art):
        d = art["destinations"]["6-photos-by-dest/Brussels"]
        d["camera_group_time_decisions"][CAM]["user_decision"]["manual_offset_seconds"] = -7187
    _edit(ws, fill)
    assert _run(monkeypatch, ws) == 0 and _artifact(ws)["status"] == "complete"
    settled = _artifact(ws)["destinations"]["6-photos-by-dest/Brussels"]

    ho_p = ws / ".photos-ingest" / "photos-11-handoff.json"
    ho = json.loads(ho_p.read_text())
    (ws / "6-photos-by-dest" / "Rome").mkdir()
    (ws / "6-photos-by-dest" / "Rome" / "b.jpg").write_bytes(b"img")
    ho["files"].append(_hfile("6-photos-by-dest/Rome/b.jpg"))
    ho_p.write_text(json.dumps({**ho, "files": match_disk(ws, ho["files"])}))
    assert _run(monkeypatch, ws) == 0
    art = _artifact(ws)
    assert art["destinations"]["6-photos-by-dest/Brussels"] == settled
    rome = art["destinations"]["6-photos-by-dest/Rome"]
    assert rome["camera_group_time_decisions"][CAM]["requires_user_input"]
    assert art["status"] == "requires_user_input"


@pytest.mark.spec("geotag-recalc-only-affected-1")
def test_determinism_unchanged_rerun_is_byte_identical(tmp_path, monkeypatch):
    ws = _ws(tmp_path, files=[_hfile("6-photos-by-dest/Brussels/a.jpg")],
             device_groups={"fixed_clock_cameras": [CAM], "phones": []})
    _run(monkeypatch, ws)
    first = (ws / ".photos-ingest" / cal.TIME_DECISIONS_ARTIFACT).read_bytes()
    _run(monkeypatch, ws)
    assert (ws / ".photos-ingest" / cal.TIME_DECISIONS_ARTIFACT).read_bytes() == first


# --- validation (§9.2) -------------------------------------------------------

@pytest.mark.spec("geotag-invalid-preserved-1", "geotag-validation-hard-blocker-1", "validate-everything-authored-1", "validate-preserve-invalid-1", "validate-timezone-1", "RUL-invalid_value_never_repaired", test="TST-geotag_time_decisions-bad_timezone_blocks_and_leaves_artifact")
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


@pytest.mark.spec("geotag-sanity-validate-1", "validate-locate-no-repair-1", test="TST-geotag_time_decisions-bad_offset_blocks")
def test_bad_offset_blocks(tmp_path, monkeypatch, capsys):
    ws = _ws(tmp_path, files=[_hfile("6-photos-by-dest/Brussels/a.jpg")],
             device_groups={"fixed_clock_cameras": [CAM], "phones": []})
    _run(monkeypatch, ws)
    _edit(ws, lambda a: a["destinations"]["6-photos-by-dest/Brussels"]["camera_group_time_decisions"]
          [CAM]["user_decision"].__setitem__("manual_offset_seconds", "not-a-number"))
    assert _run(monkeypatch, ws) == 2
    assert "manual_offset_seconds" in capsys.readouterr().err


# --- dependency block --------------------------------------------------------

@pytest.mark.spec("geotag-dep-cascade-1", "geotag-rehash-before-use-1")
def test_depends_on_reverifies(tmp_path, monkeypatch):
    ws = _ws(tmp_path, files=[_hfile("6-photos-by-dest/Brussels/a.jpg")],
             device_groups={"fixed_clock_cameras": [CAM], "phones": []})
    _run(monkeypatch, ws)
    dep = _artifact(ws)["depends_on"]["handoff"]
    assert cal.GeotagWorkflow._verify_handoff_dependency(dep, str(ws))   # matches as written
    (ws / ".photos-ingest" / "photos-11-handoff.json").write_text('{"files": []}')
    assert not cal.GeotagWorkflow._verify_handoff_dependency(dep, str(ws))   # change detected


@pytest.mark.spec("geotag-timezone-autoresolve-1", "geotag-timezone-inherit-priority-1", "geotag-timezone-unresolved-requires-input-1", "RUL-timezone_auto_resolves", test="TST-geotag_time_decisions-timezone_proposal_inherits_nearest_resolved_ancestor")
def test_timezone_proposal_inherits_nearest_resolved_ancestor():
    """A destination's timezone proposal prefers the nearest RESOLVED ancestor's timezone over the
    generic global default; an inherited (or config-default) proposal auto-resolves without per-
    destination confirmation (nested geography), staying overridable."""
    utils.CONFIG["camera_time_and_timezone_policy"]["default_folder_timezone"] = "Europe/Brussels"
    wf = cal.GeotagWorkflow("/tmp/ws")
    blk = []
    # parent "Japan" resolved to Asia/Tokyo -> a deeper child inherits it, not the Brussels default
    eff_tz = {("6-photos-by-dest/Japan", "tz"): "Asia/Tokyo"}
    inh = cal._nearest_ancestor("6-photos-by-dest/Japan/Kyoto", eff_tz, "tz")
    child = wf._timezone_decision("6-photos-by-dest/Japan/Kyoto", {}, blk, inh)
    assert child["proposed_iana_timezone"] == "Asia/Tokyo"
    assert child["proposal_source"] == "inherited"
    assert child["inherited_from"] == "6-photos-by-dest/Japan"
    # inherited auto-resolves: effective set, no input demanded, marked auto_resolved
    assert child["effective_iana_timezone"] == "Asia/Tokyo"
    assert child["requires_user_input"] is False
    assert child["decision_mode"] == "auto_resolved"
    # a manual override still wins over the auto-adopted inheritance
    overridden = wf._timezone_decision("6-photos-by-dest/Japan/Kyoto",
                                       {"user_decision": {"manual_iana_timezone": "America/New_York"}}, blk, inh)
    assert overridden["effective_iana_timezone"] == "America/New_York" and "decision_mode" not in overridden
    # no ancestor tz -> the global default proposal, also auto-resolved
    top = wf._timezone_decision("6-photos-by-dest/Belgium", {}, blk, None)
    assert top["proposed_iana_timezone"] == "Europe/Brussels" and top["proposal_source"] == "config_default"
    assert top["effective_iana_timezone"] == "Europe/Brussels" and top["requires_user_input"] is False
    assert "inherited_from" not in top
    # no proposal at all (no ancestor, no default) -> blank, blocks
    utils.CONFIG["camera_time_and_timezone_policy"]["default_folder_timezone"] = None
    blank = wf._timezone_decision("6-photos-by-dest/Belgium", {}, blk, None)
    assert blank["effective_iana_timezone"] == "" and blank["requires_user_input"] is True


# --- §22a.3: the drift offset lives in photos-22, never edits photos-21 ------

DRIFT_DEST = "6-photos-by-dest/D"


def _drift_wf(tmp_path):
    ws = tmp_path / "ws"
    (ws / ".photos-ingest").mkdir(parents=True, exist_ok=True)
    (ws / ".photos-ingest" / "photos-11-handoff.json").write_text("{}")
    wf = cal.GeotagWorkflow(str(ws))
    wf._gpx_fingerprint = "fp"
    return wf


def _drift_gpx(points):
    idx = cal.GPXIndex("")
    idx.points = [cal.GPXPoint(lat, lon, t, "trip.gpx", i) for i, (lat, lon, t) in enumerate(points)]
    return idx


@pytest.mark.spec("geotag-drift-not-mutate-21-1")
def test_build_drift_validation_leaves_photos21_byte_unmutated(tmp_path):
    """§22a.3: building photos-22 (GPS-drift validation) refines a manual/tz-derived offset, but the
    validated drift offset is recorded in photos-22 — building it must NOT touch the photos-21
    time-decisions artifact it reads. Set up a manual-offset bucket with no native-GPS anchor and GPX
    coverage (the drift trigger), write photos-21 to disk as the real run does, then build photos-22
    and assert photos-21 is byte-for-byte identical."""
    wf = _drift_wf(tmp_path)
    files = [{"relative_path": f"{DRIFT_DEST}/a.arw", "destination": DRIFT_DEST,
              "camera_group_key": CAM, "native_gps": None, "has_native_gps": False,
              "has_timestamp": True, "source_naive_time": "2024:07:03 14:00:00",
              "source_time_tag": "DateTimeOriginal"}]
    groups = {CAM: {"camera_group_class": "camera"}}
    gpx = _drift_gpx([(50.0, 4.0, datetime(2024, 7, 3, 12, 0, 0, tzinfo=timezone.utc))])
    utils.CONFIG["camera_time_and_timezone_policy"]["default_folder_timezone"] = "Europe/Brussels"
    prior = {"destinations": {DRIFT_DEST: {
        "camera_group_time_decisions": {CAM: {"user_decision": {"manual_offset_seconds": 0}}}}}}
    art, blk = wf.build_time_decisions(files, groups, prior, gpx)
    assert not blk
    # build_drift_validation hashes the on-disk photos-21 (the real run writes it first).
    tdp = cal.time_decisions_path(wf.workspace_root)
    utils.write_json_artifact(tdp, art)
    before = open(tdp, "rb").read()

    rows0 = cal.compute_resolved_utc(files, groups, art)
    drift, dblk = wf.build_drift_validation(files, art, rows0, gpx, None)
    assert not dblk
    assert CAM in drift["destinations"][DRIFT_DEST]["drift_decisions"]   # it IS a drift case
    # the offset to refine lives in photos-22, not photos-21:
    assert drift["destinations"][DRIFT_DEST]["drift_decisions"][CAM]["proposal"]["current_offset_seconds"] == 0

    assert open(tdp, "rb").read() == before                             # photos-21 untouched
    # the in-memory photos-21 cell is likewise not mutated by the drift build
    assert art["destinations"][DRIFT_DEST]["camera_group_time_decisions"][CAM][
        "effective_time_anchor"] == {"offset_seconds": 0, "source": "manual"}


@pytest.mark.spec("BLD-decision_record_envelope", "INV-no_stale_use",
                  test="TST-geotag_time_decisions-classifying_a_camera_again_restales_the_time_decisions")
def test_classifying_a_camera_again_restales_the_time_decisions(tmp_path, monkeypatch):
    # The record says what it is and what it was made from; classing the camera a phone changes that, and the
    # record follows: no offset cell, complete, nothing asked.
    ws = _ws(tmp_path, files=[_hfile("6-photos-by-dest/Brussels/a.jpg")],
             device_groups={"fixed_clock_cameras": [CAM], "phones": []}, default_tz="Europe/Brussels")
    assert _run(monkeypatch, ws) == 0
    before = _artifact(ws)
    assert {k: before[k] for k in ("artifact_type", "artifact_name", "status", "requires_user_input", "executable")} == \
        {"artifact_type": "time_decisions", "artifact_name": "photos-21-time-decisions.json",
         "status": "requires_user_input", "requires_user_input": True, "executable": False}
    cfg_p = ws / ".photos-ingest" / "photos-00-config.json"
    cfg = json.loads(cfg_p.read_text())
    cfg["camera_time_and_timezone_policy"]["device_groups"] = {"fixed_clock_cameras": [], "phones": [CAM]}
    cfg_p.write_text(json.dumps(cfg))
    assert _run(monkeypatch, ws) == 0
    after = _artifact(ws)
    assert after["depends_on"]["camera_time_policy_fingerprint"] != before["depends_on"]["camera_time_policy_fingerprint"]
    assert after["destinations"]["6-photos-by-dest/Brussels"]["camera_group_time_decisions"] == {}
    assert after["status"] == "complete" and after["decision_mode"] == "no_op_or_auto_resolved"
