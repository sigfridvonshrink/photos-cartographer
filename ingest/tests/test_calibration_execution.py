"""Phase 6c-1 (calibration) — the `execute` subcommand (§29): apply photos-23, verify content
fingerprints, journal/resume, write photos-24. exiftool + fingerprint are mocked (the suite mocks
all external tools), so the executor logic is driven deterministically. From conftest.py.
"""
import json
import os
import sys
from datetime import datetime, timezone

import pytest

import photos_2_time_gps as cal
import photos_utils as utils

CAM = "SONY|ILCE-6400|123"
MANAGED = ["0-sources", "1-strays", "2-missing-metadata", "3-redundant-jpgs",
           "4-videos-by-date", "5-photos-by-date", "6-photos-by-dest"]


def _ready_ws(tmp_path, monkeypatch, *, zfs=None):
    """A workspace driven through `run` (timezone accepted) so a *ready* photos-23 exists, with real
    media files. Two native-GPS frames -> auto-resolved offset -> time-only ops + renames. `zfs` (if
    given) is baked into the config BEFORE planning so the plan's config fingerprint covers it."""
    ws = tmp_path / "ws"; ws.mkdir()
    for d in MANAGED:
        (ws / d).mkdir()
    ctl = ws / ".photos-ingest"; ctl.mkdir()
    (ctl / "photos-00-workspace-guard").touch()
    gpx = tmp_path / "gpx"; gpx.mkdir()
    (gpx / "t.gpx").write_text(
        '<gpx xmlns="http://www.topografix.com/GPX/1/1"><trk><trkseg>'
        '<trkpt lat="50.0" lon="4.0"><time>2024-07-03T12:00:00Z</time></trkpt>'
        '<trkpt lat="51.0" lon="5.0"><time>2024-07-03T13:00:00Z</time></trkpt>'
        '</trkseg></trk></gpx>')
    cfg = {k: v for k, v in utils.CONFIG.items() if k != "jobs"}
    cfg["gpx_root"] = str(gpx)
    cfg["camera_time_and_timezone_policy"] = dict(
        cfg["camera_time_and_timezone_policy"], device_groups={"fixed_clock_cameras": [CAM], "phones": []},
        default_folder_timezone="Europe/Brussels", multi_anchor_auto_apply=True)
    if zfs is not None:
        cfg["zfs"] = zfs
    (ctl / "photos-00-config.json").write_text(json.dumps(cfg))

    def rec(rel, dto, lat, lon):
        parsed = {"DateTimeOriginal": dto, "selected_source_naive_timestamp": dto,
                  "selected_source_timestamp_tag": "DateTimeOriginal", "camera_group_key": CAM,
                  "has_timestamp": True, "has_native_gps": True, "GPSLatitude": lat, "GPSLongitude": lon}
        p = ws / rel; p.parent.mkdir(parents=True, exist_ok=True); p.write_bytes(b"img-" + rel.encode())
        st = p.stat()
        return {"relative_path": rel, "media_class": "image", "folder_class": "6-photos-by-dest",
                "size": st.st_size, "mtime_ns": st.st_mtime_ns,
                "content_hash": json.dumps({"value": "fp-" + rel, "status": "valid"}),
                "metadata_status": {"camera_group_key": CAM, "has_timestamp": True, "has_native_gps": True,
                                    "field_set_version": 1, "parsed_json": json.dumps(parsed)}}
    files = [rec("6-photos-by-dest/T/a.arw", "2024:07:03 14:00:00", 50.0, 4.0),
             rec("6-photos-by-dest/T/b.arw", "2024:07:03 15:00:00", 51.0, 5.0)]
    ho = {"run_metadata": {"plan_id": "prep-1", "execution_id": "exec-1"},
          "files": files, "cache_fingerprint": "pcf"}
    ho["content_fingerprint"] = utils.handoff_content_fingerprint(ho)
    (ctl / "photos-11-handoff.json").write_text(json.dumps(ho))

    def run():
        monkeypatch.chdir(str(ws))
        monkeypatch.setattr(sys, "argv", ["photos-2-time-gps", "plan"])
        try:
            cal.main()
        except SystemExit:
            pass
    run()
    p = ctl / "photos-21-time-decisions.json"; a = json.load(open(p))
    a["destinations"]["6-photos-by-dest/T"]["destination_timezone"]["user_decision"]["accept_proposed_timezone"] = True
    p.write_text(json.dumps(a))
    run()
    assert (ctl / "photos-23-executable-plan.json").exists()
    return ws, ctl


def _mock_tools(monkeypatch, ws, *, write_ok=True, content_changed=False):
    monkeypatch.setattr(cal.CalibrationWorkflow, "_exiftool_write",
                        lambda self, p, tags: write_ok)

    def fp(path):
        rel = os.path.relpath(path, str(ws))
        return {"status": "valid", "value": ("CHANGED" if content_changed else "fp-" + rel)}
    monkeypatch.setattr(cal.ContentHasher, "fingerprint_image", staticmethod(fp))


def _execute(monkeypatch, ws):
    monkeypatch.chdir(str(ws))
    monkeypatch.setattr(sys, "argv", ["photos-2-time-gps", "execute"])
    try:
        cal.main(); return 0
    except SystemExit as e:
        return e.code if isinstance(e.code, int) else (0 if e.code is None else 1)


def _summary(ctl):
    return json.load(open(ctl / "photos-24-execution-summary.json"))


# --- clean apply -------------------------------------------------------------

def test_clean_execute_applies_and_renames(tmp_path, monkeypatch):
    ws, ctl = _ready_ws(tmp_path, monkeypatch)
    _mock_tools(monkeypatch, ws)
    assert _execute(monkeypatch, ws) == 0
    s = _summary(ctl)
    assert s["status"] == "success" and s["totals"]["metadata_time_writes"] == 2 and s["totals"]["renames"] == 2
    # files renamed to destination-local civil time (resolved 12:00/13:00Z + Brussels summer +2h)
    names = sorted(os.listdir(ws / "6-photos-by-dest" / "T"))
    assert names == ["2024-07-03--14-00-00.arw", "2024-07-03--15-00-00.arw"]


def test_content_changed_write_flags_mismatch(tmp_path, monkeypatch):
    ws, ctl = _ready_ws(tmp_path, monkeypatch)
    _mock_tools(monkeypatch, ws, content_changed=True)
    assert _execute(monkeypatch, ws) == 3                         # partial -> non-zero exit
    s = _summary(ctl)
    assert s["status"] == "partial" and len(s["fingerprint_mismatches"]) == 2
    assert s["fingerprint_mismatches"][0]["user_decision"] == {"accept_fingerprint_change": False}
    # mismatch -> the metadata op is NOT confirmed and the file is NOT renamed
    assert os.path.exists(ws / "6-photos-by-dest" / "T" / "a.arw")


def test_exiftool_failure_records_failure(tmp_path, monkeypatch):
    ws, ctl = _ready_ws(tmp_path, monkeypatch)
    _mock_tools(monkeypatch, ws, write_ok=False)
    assert _execute(monkeypatch, ws) == 3
    s = _summary(ctl)
    assert s["status"] == "partial" and len(s["failures"]) == 2 and s["totals"]["metadata_time_writes"] == 0


# --- resume / idempotency ----------------------------------------------------

def test_resume_skips_confirmed_ops(tmp_path, monkeypatch):
    ws, ctl = _ready_ws(tmp_path, monkeypatch)
    _mock_tools(monkeypatch, ws)
    _execute(monkeypatch, ws)
    # second run: everything already confirmed -> skipped, nothing newly applied
    assert _execute(monkeypatch, ws) == 0
    s = _summary(ctl)
    assert s["resume"]["newly_applied"] == 0 and s["resume"]["already_satisfied_skipped"] == 4
    # skips are also broken down per destination (§29.2 item 4) and sum to the global skip count
    assert s["destinations"]["6-photos-by-dest/T"]["skipped"] == 4
    assert sum(d["skipped"] for d in s["destinations"].values()) == s["resume"]["already_satisfied_skipped"]


# --- reconciliation ----------------------------------------------------------

def test_accept_fingerprint_change_finalizes(tmp_path, monkeypatch):
    ws, ctl = _ready_ws(tmp_path, monkeypatch)
    _mock_tools(monkeypatch, ws, content_changed=True)
    _execute(monkeypatch, ws)                                     # -> partial, 2 mismatches
    # accept both fingerprint changes in photos-24, re-execute
    s = _summary(ctl)
    for m in s["fingerprint_mismatches"]:
        m["user_decision"]["accept_fingerprint_change"] = True
    (ctl / "photos-24-execution-summary.json").write_text(json.dumps(s))
    assert _execute(monkeypatch, ws) == 0
    assert _summary(ctl)["status"] == "success"


# --- stale rejection ---------------------------------------------------------

def test_stale_plan_is_rejected_without_mutation(tmp_path, monkeypatch):
    ws, ctl = _ready_ws(tmp_path, monkeypatch)
    _mock_tools(monkeypatch, ws)
    (ctl / "photos-11-handoff.json").write_text('{"files": [], "cache_fingerprint": "x"}')  # change a dep
    before = sorted(os.listdir(ws / "6-photos-by-dest" / "T"))
    assert _execute(monkeypatch, ws) == 2                         # rejected
    assert sorted(os.listdir(ws / "6-photos-by-dest" / "T")) == before   # nothing mutated
    assert not (ctl / "photos-24-execution-summary.json").exists()


def test_missing_plan_errors(tmp_path, monkeypatch):
    ws, ctl = _ready_ws(tmp_path, monkeypatch)
    os.remove(ctl / "photos-23-executable-plan.json")
    _mock_tools(monkeypatch, ws)
    assert _execute(monkeypatch, ws) == 2


# --- no-clobber recheck + determinism (unit) --------------------------------

def test_target_occupied_recheck(tmp_path):
    wf = cal.CalibrationWorkflow(str(tmp_path))
    (tmp_path / "A.JPG").write_text("x")
    assert wf._target_occupied(str(tmp_path), "a.jpg", "src.arw") is True      # case-insensitive
    assert wf._target_occupied(str(tmp_path), "b.jpg", "src.arw") is False
    assert wf._target_occupied(str(tmp_path), "A.JPG", "A.JPG") is False       # ignores the source itself


# --- unit: _exiftool_write seam --------------------------------------------

def test_exiftool_write_invocation(tmp_path, monkeypatch):
    wf = cal.CalibrationWorkflow(str(tmp_path))
    calls = {}

    class _R:
        def __init__(self, rc): self.returncode = rc
    def _run(cmd, **k):
        calls["cmd"] = cmd
        return _R(0)
    monkeypatch.setattr(cal.subprocess, "run", _run)
    assert wf._exiftool_write("/x.jpg", {"DateTimeOriginal": "2024:07:03 14:00:00"}) is True
    assert calls["cmd"][:3] == ["exiftool", "-overwrite_original", "-n"] and calls["cmd"][-1] == "/x.jpg"
    monkeypatch.setattr(cal.subprocess, "run", lambda cmd, **k: _R(1))
    assert wf._exiftool_write("/x.jpg", {}) is False                  # non-zero exit
    def _boom(*a, **k): raise OSError("no exiftool")
    monkeypatch.setattr(cal.subprocess, "run", _boom)
    assert wf._exiftool_write("/x.jpg", {}) is False                  # tool missing


def test_exiftool_write_unlinks_stale_tmp(tmp_path, monkeypatch):
    """A hard-killed prior write can orphan `<file>_exiftool_tmp`; the writer removes it for THIS
    target before re-invoking exiftool, so the resumed write never trips over the leftover."""
    wf = cal.CalibrationWorkflow(str(tmp_path))
    target = tmp_path / "x.jpg"
    target.write_bytes(b"orig")
    stale = tmp_path / "x.jpg_exiftool_tmp"
    stale.write_bytes(b"partial")

    class _R:
        returncode = 0
    monkeypatch.setattr(cal.subprocess, "run", lambda cmd, **k: _R())
    assert wf._exiftool_write(str(target), {"DateTimeOriginal": "2024:07:03 14:00:00"}) is True
    assert not stale.exists()                 # stale temp cleaned before the write
    assert target.read_bytes() == b"orig"     # the live original is untouched


def test_exiftool_write_no_tmp_is_noop(tmp_path, monkeypatch):
    """The unlink is best-effort: a missing temp (the normal case) is not an error."""
    wf = cal.CalibrationWorkflow(str(tmp_path))
    class _R:
        returncode = 0
    monkeypatch.setattr(cal.subprocess, "run", lambda cmd, **k: _R())
    assert wf._exiftool_write(str(tmp_path / "y.jpg"), {}) is True


def test_target_occupied_bad_directory(tmp_path):
    wf = cal.CalibrationWorkflow(str(tmp_path))
    assert wf._target_occupied(str(tmp_path / "nope"), "a.jpg", "s.jpg") is False  # listdir OSError -> False


# --- unit: _apply_file precondition + resume + rename branches --------------

def _op(oid, typ, rel, **extra):
    return {"operation_id": oid, "type": typ, "relative_path": rel,
            "preconditions": extra.pop("pre", {}), **extra}


def test_apply_file_precondition_and_resume_branches(tmp_path, monkeypatch):
    wf = cal.CalibrationWorkflow(str(tmp_path))
    p = tmp_path / "f.arw"; p.write_bytes(b"data")
    monkeypatch.setattr(cal.CalibrationWorkflow, "_exiftool_write", lambda self, path, t: True)
    # already confirmed -> skipped (no stat, no write)
    r = wf._apply_file("f.arw", [_op("oC", "metadata_time_write", "f.arw")], {"oC": "confirmed"}, set())
    assert r["skipped"] == ["oC"]
    # missing file (no rename) -> blocker
    r = wf._apply_file("gone.arw", [_op("o", "metadata_time_write", "gone.arw")], {}, set())
    assert "missing at execute time" in r["blocker"]
    # size/mtime changed AND the content fingerprint differs -> external change -> blocker
    monkeypatch.setattr(cal.ContentHasher, "fingerprint_image", staticmethod(lambda path: {"value": "OTHER"}))
    r = wf._apply_file("f.arw", [_op("o", "metadata_time_write", "f.arw",
                       pre={"size": 999, "content_fingerprint": "FP"})], {}, set())
    assert "content fingerprint differs" in r["blocker"]
    # size/mtime changed BUT the content fingerprint still matches -> resume: re-apply, no block
    monkeypatch.setattr(cal.ContentHasher, "fingerprint_image", staticmethod(lambda path: {"value": "FP"}))
    r = wf._apply_file("f.arw", [_op("o", "metadata_time_write", "f.arw",
                       pre={"size": 999, "mtime_ns": 1, "content_fingerprint": "FP"},
                       writes={"DateTimeOriginal": "x"})], {}, set())
    assert r["blocker"] is None and r["applied"] == ["o"]


def test_apply_file_rename_skip_and_failure(tmp_path, monkeypatch):
    wf = cal.CalibrationWorkflow(str(tmp_path))
    p = tmp_path / "a.arw"; p.write_bytes(b"x")
    ren = _op("oR", "rename_no_clobber", "a.arw", **{"from": "a.arw", "to": "b.arw"})
    # rename already confirmed -> skipped (file not moved)
    r = wf._apply_file("a.arw", [ren], {"oR": "confirmed"}, set())
    assert r["applied"] == [] and (tmp_path / "a.arw").exists()
    # _move_no_clobber raises -> failure recorded
    monkeypatch.setattr(cal, "_move_no_clobber", lambda s, d: (_ for _ in ()).throw(OSError("xdev")))
    r = wf._apply_file("a.arw", [ren], {}, set())
    assert r["failed"] == ["oR"] and "rename failed" in r["blocker"]


def test_revalidate_detects_each_stale_input(tmp_path, monkeypatch):
    ws, ctl = _ready_ws(tmp_path, monkeypatch)
    wf = cal.CalibrationWorkflow(str(ws)); wf.preflight(for_execute=True)
    plan = json.load(open(ctl / "photos-23-executable-plan.json"))
    gpx = cal.GPXIndex(cal.selected_gpx_root()).build()
    assert wf.revalidate_plan(plan, gpx) == []                        # fresh -> nothing stale
    assert any("not 'ready'" in s for s in wf.revalidate_plan({**plan, "status": "blocked"}, gpx))
    for k in ("config_fingerprint", "filename_format_fingerprint", "camera_group_fingerprint", "gpx_fingerprint"):
        pk = {**plan, "depends_on": {**plan["depends_on"], k: "WRONG"}}
        assert any(k in s for s in wf.revalidate_plan(pk, gpx)), k
    pk = {**plan, "depends_on": {**plan["depends_on"], "planned_operation_fingerprint": "WRONG"}}
    assert any("planned operations changed" in s for s in wf.revalidate_plan(pk, gpx))


def test_corrupt_journal_is_ignored(tmp_path, monkeypatch):
    ws, ctl = _ready_ws(tmp_path, monkeypatch)
    _mock_tools(monkeypatch, ws)
    # a corrupt journal must not crash execution (treated as empty -> a fresh apply)
    plan = json.load(open(ctl / "photos-23-executable-plan.json"))
    with open(utils.journal_path(str(ws), plan["plan_id"]), "w") as f:
        f.write("{corrupt")
    assert _execute(monkeypatch, ws) == 0
    assert _summary(ctl)["status"] == "success"


def test_rename_target_occupied_at_execute_blocks(tmp_path, monkeypatch):
    ws, ctl = _ready_ws(tmp_path, monkeypatch)
    _mock_tools(monkeypatch, ws)
    # occupy a planned rename target AFTER the plan was written -> execute-time no-clobber blocker
    (ws / "6-photos-by-dest" / "T" / "2024-07-03--14-00-00.arw").write_bytes(b"squatter")
    assert _execute(monkeypatch, ws) == 3
    s = _summary(ctl)
    assert s["status"] == "partial" and any("occupied at execute time" in b for b in s["blockers"])
    assert (ws / "6-photos-by-dest" / "T" / "a.arw").exists()      # not clobbered/renamed


def test_apply_file_already_renamed_resumes_without_journal(tmp_path):
    """A crashed prior run that already renamed the file (source gone, planned target present) is
    detected by state and skipped on resume — even with an empty/lost journal — rather than blocking
    on the missing source (§29.1.3)."""
    wf = cal.CalibrationWorkflow(str(tmp_path))
    (tmp_path / "b.arw").write_bytes(b"x")                            # already at its planned target
    ops = [_op("oM", "metadata_time_write", "a.arw", pre={"content_fingerprint": "fp"},
               writes={"DateTimeOriginal": "x"}),
           _op("oR", "rename_no_clobber", "a.arw", **{"from": "a.arw", "to": "b.arw"})]
    r = wf._apply_file("a.arw", ops, {}, set())                       # journal empty, source gone
    assert r["skipped"] == ["oM", "oR"] and not r["applied"]


def test_corrupt_prior_summary_ignored(tmp_path, monkeypatch):
    ws, ctl = _ready_ws(tmp_path, monkeypatch)
    _mock_tools(monkeypatch, ws)
    (ctl / "photos-24-execution-summary.json").write_text("{corrupt")   # unreadable prior reconciliation
    assert _execute(monkeypatch, ws) == 0                              # ignored -> a clean apply
    assert _summary(ctl)["status"] == "success"


def test_execute_on_sealed_workspace_warns_and_blocks(tmp_path, monkeypatch):
    ws = tmp_path / "ws"; ws.mkdir()
    for d in MANAGED:
        (ws / d).mkdir()
    ctl = ws / ".photos-ingest"; ctl.mkdir()
    (ctl / "photos-00-workspace-guard").touch()
    open(utils.sealed_marker_path(str(ws)), "w").close()
    (ws / "loose.jpg").write_bytes(b"x")                              # a dump -> exercises the warning print
    assert _execute(monkeypatch, ws) == 2                             # sealed -> blocked (exit 2)


def test_summary_keeps_run_metadata_separate(tmp_path, monkeypatch):
    ws, ctl = _ready_ws(tmp_path, monkeypatch)
    _mock_tools(monkeypatch, ws)
    wf = cal.CalibrationWorkflow(str(ws)); wf.preflight(for_execute=True)
    s = wf.execute_plan(1, "2024-07-03T00:00:00Z", "exec-1")
    # the volatile bits (timestamps, execution id, jobs) live ONLY in run_metadata, off the
    # fingerprint-bearing body (summarizes / totals / plan_id), per §29.2.
    assert s["run_metadata"] == {"execution_id": "exec-1", "started_at": "2024-07-03T00:00:00Z",
                                 "finished_at": "2024-07-03T00:00:00Z", "jobs": 1}
    body = json.dumps({k: v for k, v in s.items() if k != "run_metadata"})
    assert "2024-07-03T00:00:00Z" not in body and "exec-1" not in body
    assert s["summarizes"][cal.EXECUTABLE_PLAN_ARTIFACT]["sha256"]


# --- pre-mutation ZFS snapshot (§29 step 6, shared helper) -------------------

def _mock_zfs(monkeypatch, *, fail=False):
    import subprocess as _sp
    import types as _t
    monkeypatch.setattr(utils, "detect_zfs_dataset", lambda p: "pool/ws")
    def run(*a, **k):
        if fail:
            raise _sp.CalledProcessError(1, "zfs", stderr="pool busy")
        return _t.SimpleNamespace(returncode=0, stdout="", stderr="")
    monkeypatch.setattr(_sp, "run", run)


def test_execute_records_zfs_snapshot(tmp_path, monkeypatch):
    zfs = {"enabled": True, "snapshots_required": True, "snapshot_prefix": "px-",
           "datasets": {"workspace": "auto"}}
    ws, ctl = _ready_ws(tmp_path, monkeypatch, zfs=zfs)
    _mock_tools(monkeypatch, ws); _mock_zfs(monkeypatch)
    assert _execute(monkeypatch, ws) == 0
    s = _summary(ctl)
    assert s["snapshot"]["ok"] and s["snapshot"]["snapshot_name"] == f"pool/ws@px-calibrate-{s['plan_id']}"


def test_execute_aborts_when_required_snapshot_fails(tmp_path, monkeypatch):
    zfs = {"enabled": True, "snapshots_required": True, "snapshot_prefix": "px-",
           "datasets": {"workspace": "auto"}}
    ws, ctl = _ready_ws(tmp_path, monkeypatch, zfs=zfs)
    _mock_tools(monkeypatch, ws); _mock_zfs(monkeypatch, fail=True)
    before = sorted(os.listdir(ws / "6-photos-by-dest" / "T"))
    assert _execute(monkeypatch, ws) == 2                            # required snapshot failed -> rejected
    assert sorted(os.listdir(ws / "6-photos-by-dest" / "T")) == before   # nothing mutated
    # §29 step 6: the snapshot record is carried into photos-24 even on the abort path
    s = _summary(ctl)
    assert s["status"] == "rejected" and s["snapshot"]["ok"] is False and s["snapshot"]["required"] is True
    assert s["blockers"] and "snapshot failed" in s["blockers"][0]


def test_resume_after_journal_lost_skips_applied_files(tmp_path, monkeypatch):
    """Crash-resume (§29.1.3): a full execute renames + writes the files; deleting the journal
    (simulating a crash before its flush) and re-executing must detect the already-applied files at
    their targets and SKIP them — not block on the changed/missing source."""
    import os as _os
    ws, ctl = _ready_ws(tmp_path, monkeypatch)
    _mock_tools(monkeypatch, ws)
    assert _execute(monkeypatch, ws) == 0
    assert _summary(ctl)["status"] == "success"
    plan = json.load(open(ctl / "photos-23-executable-plan.json"))
    _os.remove(utils.journal_path(str(ws), plan["plan_id"]))          # journal "lost" to a crash

    assert _execute(monkeypatch, ws) == 0                             # resumes cleanly
    s = _summary(ctl)
    assert s["status"] == "success"
    assert s["resume"]["newly_applied"] == 0                          # nothing re-applied
    assert not s["blockers"] and not s["failures"]                    # not blocked on the renamed files


def test_journal_persisted_incrementally_during_run(tmp_path, monkeypatch):
    """The journal is flushed per-file as the run proceeds (not only at the end), so a crash mid-run
    leaves a journal that records the already-applied files."""
    import photos_utils as _u
    ws, ctl = _ready_ws(tmp_path, monkeypatch)
    _mock_tools(monkeypatch, ws)
    flushes = []
    real = _u.write_json_artifact
    def spy(path, obj):
        if "journal_version" in obj:
            flushes.append(len(obj["operations"]))
        return real(path, obj)
    monkeypatch.setattr(cal, "write_json_artifact", spy)
    assert _execute(monkeypatch, ws) == 0
    # two files, each flushing its confirmed ops -> the journal grew across >1 incremental write
    assert len(flushes) >= 2 and flushes == sorted(flushes) and flushes[-1] > flushes[0]


def test_summary_grouped_by_destination(tmp_path, monkeypatch):
    """photos-24 carries a per-destination operation breakdown (§29.2 item 4) that sums to the global
    totals."""
    ws, ctl = _ready_ws(tmp_path, monkeypatch)
    _mock_tools(monkeypatch, ws)
    assert _execute(monkeypatch, ws) == 0
    s = _summary(ctl)
    assert "destinations" in s
    d = s["destinations"]["6-photos-by-dest/T"]
    assert d["metadata_time_writes"] == 2 and d["renames"] == 2
    assert sum(v["metadata_time_writes"] for v in s["destinations"].values()) == s["totals"]["metadata_time_writes"]
    assert sum(v["renames"] for v in s["destinations"].values()) == s["totals"]["renames"]


def test_noop_reprep_does_not_restale_plan(tmp_path, monkeypatch):
    """A no-op prep re-run refreshes only the handoff's run_metadata (and its byte layout); calibration
    depends on the handoff CONTENT fingerprint, so the plan must NOT restale — but a real content change
    (the inventory) does (§16)."""
    import photos_utils as u
    ws, ctl = _ready_ws(tmp_path, monkeypatch)
    _mock_tools(monkeypatch, ws)
    wf = cal.CalibrationWorkflow(str(ws)); wf.preflight(for_execute=True)
    plan = json.load(open(ctl / "photos-23-executable-plan.json"))
    gpx = cal.GPXIndex(cal.selected_gpx_root()).build()
    assert wf.revalidate_plan(plan, gpx) == []                            # fresh
    ho = json.load(open(ctl / "photos-11-handoff.json"))
    ho["run_metadata"] = {"plan_id": "NEW-PLAN", "execution_id": "NEW-EXEC"}   # only run metadata changed
    u.write_json_artifact(str(ctl / "photos-11-handoff.json"), ho)
    assert wf.revalidate_plan(plan, gpx) == []                            # still not stale
    ho["cache_fingerprint"] = "CHANGED-INVENTORY"                         # a real content change
    u.write_json_artifact(str(ctl / "photos-11-handoff.json"), ho)
    assert any("handoff" in s for s in wf.revalidate_plan(plan, gpx))     # now stale
