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

"""Phase 6c-1 (geotag) — the `execute` subcommand (BLD-geotag_execution): apply photos-23, verify content
fingerprints, journal/resume, write photos-25. exiftool + fingerprint are mocked (the suite mocks
all external tools), so the executor logic is driven deterministically. From conftest.py.
"""
import json
from _handoff import recorded, vouched
from _zone import answer_root_zone, with_root_zone
import os
import shutil
import stat
import sqlite3
import sys
from datetime import datetime, timezone

import pytest

import photos_2_geotag as cal
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
    answer_root_zone(ctl)                        # the zone answered once at the root (RUL-timezone_auto_resolves)

    def rec(rel, dto, lat, lon):
        parsed = {"DateTimeOriginal": dto, "selected_source_naive_timestamp": dto,
                  "selected_source_timestamp_tag": "DateTimeOriginal", "camera_group_key": CAM,
                  "has_timestamp": True, "has_native_gps": True, "GPSLatitude": lat, "GPSLongitude": lon}
        p = ws / rel; p.parent.mkdir(parents=True, exist_ok=True); p.write_bytes(b"img-" + rel.encode())
        st = p.stat()
        return {"relative_path": rel, "media_class": "image", "folder_class": "6-photos-by-dest",
                "size": st.st_size, "mtime_ns": st.st_mtime_ns,
                "content_hash": json.dumps({"value": "fp-" + rel, "status": "valid"}),
                "metadata_status": {"camera_group_key_version": utils.CAMERA_GROUP_KEY_VERSION,
                                    "camera_group_key": CAM, "has_timestamp": True, "has_native_gps": True,
                                    "field_set_version": utils.FIELD_SET_VERSION, "parsed_json": json.dumps(parsed)}}
    files = [rec("6-photos-by-dest/T/a.arw", "2024:07:03 14:00:00", 50.0, 4.0),
             rec("6-photos-by-dest/T/b.arw", "2024:07:03 15:00:00", 51.0, 5.0)]
    ho = {"filename_timestamp_format": utils.CONFIG["filename_timestamp_format"], "run_metadata": {"plan_id": "prep-1", "execution_id": "exec-1"},
          "files": files, "cache_fingerprint": "pcf",
          "depends_on": {"cache": {"image_engine_version": utils.get_imagemagick_version(), "fingerprint_algorithm_version": utils.FINGERPRINT_ALGORITHM_VERSION}}}
    ho["content_fingerprint"] = utils.handoff_content_fingerprint(ho)
    (ctl / "photos-11-handoff.json").write_text(json.dumps(vouched(ctl.parent, ho)))

    def run():
        monkeypatch.chdir(str(ws))
        monkeypatch.setattr(sys, "argv", ["photos-2-geotag", "plan"])
        try:
            cal.main()
        except SystemExit:
            pass
    run()
    p = ctl / "photos-21-time-decisions.json"; a = json.load(open(p))
    p.write_text(json.dumps(a))
    run()
    assert (ctl / "photos-24-executable-plan.json").exists()
    return ws, ctl


def _mock_tools(monkeypatch, ws, *, write_ok=True, content_changed=False):
    """Stand-ins for exiftool and the image fingerprint that behave as the real ones do across a rename: a
    photo keeps its fingerprint and the tags written to it whatever its name becomes (kept by inode)."""
    first_name, held = {}, {}

    def write(self, p, tags):
        if write_ok:
            held.setdefault(os.stat(p).st_ino, {}).update(tags)
        return write_ok
    monkeypatch.setattr(cal.GeotagWorkflow, "_exiftool_write", write)
    monkeypatch.setattr(cal.GeotagWorkflow, "_exiftool_read",
                        lambda self, p, keys: {k: v for k, v in held.get(os.stat(p).st_ino, {}).items() if k in keys})

    def fp(path):
        rel = first_name.setdefault(os.stat(path).st_ino, os.path.relpath(path, str(ws)))
        return {"status": "valid", "value": ("CHANGED" if content_changed else "fp-" + rel)}
    monkeypatch.setattr(cal.ContentHasher, "fingerprint_image", staticmethod(fp))


def _execute(monkeypatch, ws):
    monkeypatch.chdir(str(ws))
    monkeypatch.setattr(sys, "argv", ["photos-2-geotag", "execute"])
    try:
        cal.main(); return 0
    except SystemExit as e:
        return e.code if isinstance(e.code, int) else (0 if e.code is None else 1)


def _summary(ctl):
    return json.load(open(ctl / "photos-25-execution-summary.json"))


# --- clean apply -------------------------------------------------------------

@pytest.mark.spec("BLD-execution_summary")
def test_clean_execute_applies_and_renames(tmp_path, monkeypatch):
    ws, ctl = _ready_ws(tmp_path, monkeypatch)
    _mock_tools(monkeypatch, ws)
    assert _execute(monkeypatch, ws) == 0
    s = _summary(ctl)
    assert s["status"] == "success" and s["totals"]["metadata_time_writes"] == 2 and s["totals"]["renames"] == 2
    # files renamed to destination-local civil time (resolved 12:00/13:00Z + Brussels summer +2h)
    names = sorted(os.listdir(ws / "6-photos-by-dest" / "T"))
    assert names == ["2024-07-03--14-00-00.arw", "2024-07-03--15-00-00.arw"]


@pytest.mark.spec("RUL-operations_atomic", test="TST-geotag_execution-every_geotag_rename_is_one_rename")
def test_every_geotag_rename_is_one_rename(tmp_path, monkeypatch):
    """Where the filesystem allows, each rename geotag makes is one rename — never a hard link and an unlink, or a
    copy and a removal, of the photo."""
    ws, ctl = _ready_ws(tmp_path, monkeypatch)
    _mock_tools(monkeypatch, ws)
    probe = tmp_path / "probe"; probe.write_bytes(b"p")
    fn = utils._get_renameat2()
    if not fn or fn(utils._AT_FDCWD, os.fsencode(str(probe)), utils._AT_FDCWD,
                    os.fsencode(str(tmp_path / "probed")), utils._RENAME_NOREPLACE) != 0:
        pytest.skip("this filesystem has no rename that refuses a taken name")
    split = []
    real_link, real_copy = os.link, shutil.copyfile
    def link(src, dst, *a, **k):
        split.append(("link", str(src)))
        return real_link(src, dst, *a, **k)
    def copyfile(src, dst, *a, **k):
        split.append(("copy", str(src)))
        return real_copy(src, dst, *a, **k)
    monkeypatch.setattr(os, "link", link)
    monkeypatch.setattr(shutil, "copyfile", copyfile)
    utils.CONFIG.clear(); utils.CONFIG.update(json.loads(json.dumps(utils.DEFAULT_CONFIG)))   # a run of its own: nothing read yet
    assert _execute(monkeypatch, ws) == 0
    assert _summary(ctl)["totals"]["renames"] == 2
    assert sorted(os.listdir(ws / "6-photos-by-dest" / "T")) == ["2024-07-03--14-00-00.arw", "2024-07-03--15-00-00.arw"]
    assert [s for s in split if ".photos-ingest" not in s[1]] == [], split


@pytest.mark.spec("RUL-content_changed_write_held", "BLD-execution_summary", "RUL-rename_held_with_write",
                  test="TST-geotag_execution-content_changed_write_flags_mismatch")
def test_content_changed_write_flags_mismatch(tmp_path, monkeypatch):
    ws, ctl = _ready_ws(tmp_path, monkeypatch)
    _mock_tools(monkeypatch, ws, content_changed=True)
    assert _execute(monkeypatch, ws) == 3                         # partial -> non-zero exit
    s = _summary(ctl)
    assert s["status"] == "partial" and len(s["fingerprint_mismatches"]) == 2
    assert s["fingerprint_mismatches"][0]["user_decision"] == {"accept_fingerprint_change": False}
    # mismatch -> the metadata op is NOT confirmed and the file is NOT renamed
    assert os.path.exists(ws / "6-photos-by-dest" / "T" / "a.arw")


@pytest.mark.spec("BLD-geotag_execution", "BLD-execution_summary", "RUL-failure_recorded", test="TST-geotag_execution-exiftool_failure_records_failure")
def test_exiftool_failure_records_failure(tmp_path, monkeypatch):
    ws, ctl = _ready_ws(tmp_path, monkeypatch)
    _mock_tools(monkeypatch, ws, write_ok=False)
    assert _execute(monkeypatch, ws) == 3
    s = _summary(ctl)
    # every write fails and nothing is applied/already-satisfied -> total failure (BLD-execution_summary);
    # two files, each a time write and its time-fixed mark
    assert s["status"] == "failed" and len(s["failures"]) == 4 and s["totals"]["metadata_time_writes"] == 0


# --- resume / idempotency ----------------------------------------------------

@pytest.mark.spec("RUL-geotag_execution_resumable", test="TST-geotag_execution-resume_skips_confirmed_ops")
def test_resume_skips_confirmed_ops(tmp_path, monkeypatch):
    ws, ctl = _ready_ws(tmp_path, monkeypatch)
    _mock_tools(monkeypatch, ws)
    _execute(monkeypatch, ws)
    # second run: everything already confirmed -> skipped, nothing newly applied
    assert _execute(monkeypatch, ws) == 0
    s = _summary(ctl)
    assert s["resume"]["newly_applied"] == 0 and s["resume"]["already_satisfied_skipped"] == 6
    # skips are also broken down per destination (BLD-execution_summary) and sum to the global skip count
    assert s["destinations"]["6-photos-by-dest/T"]["skipped"] == 6
    assert sum(d["skipped"] for d in s["destinations"].values()) == s["resume"]["already_satisfied_skipped"]


# --- reconciliation ----------------------------------------------------------

@pytest.mark.spec("RUL-content_changed_write_held", "BLD-geotag_execution",
                  test="TST-geotag_execution-accept_fingerprint_change_finalizes")
def test_accept_fingerprint_change_finalizes(tmp_path, monkeypatch):
    ws, ctl = _ready_ws(tmp_path, monkeypatch)
    _mock_tools(monkeypatch, ws, content_changed=True)
    _execute(monkeypatch, ws)                                     # -> partial, 2 mismatches
    # accept both fingerprint changes in photos-24, re-execute
    s = _summary(ctl)
    for m in s["fingerprint_mismatches"]:
        m["user_decision"]["accept_fingerprint_change"] = True
    (ctl / "photos-25-execution-summary.json").write_text(json.dumps(s))
    assert _execute(monkeypatch, ws) == 0
    assert _summary(ctl)["status"] == "success"


# --- concurrency equality (Tier 3) -------------------------------------------

def _execute_jobs(monkeypatch, ws, n):
    """Run geotag `execute` with an explicit -j N (top-level arg, before the subcommand)."""
    monkeypatch.chdir(str(ws))
    monkeypatch.setattr(sys, "argv", ["photos-2-geotag", "-j", str(n), "execute"])
    try:
        cal.main(); return 0
    except SystemExit as e:
        return e.code if isinstance(e.code, int) else (0 if e.code is None else 1)


@pytest.mark.spec("RUL-execution_jobs_change_nothing", "BLD-geotag_execution")
def test_execute_j1_and_jN_produce_identical_summary_and_tree(tmp_path, monkeypatch):
    """Concurrency is a performance knob with NO semantic effect: executing the SAME geotag plan under
    -j1 vs -j4 yields a byte-identical photos-25 summary (modulo the volatile run_metadata, which by
    design records jobs/timestamps/execution_id) and an identical on-disk file tree. The plan is built
    once and copied to two workspaces so plan_id/artifacts are identical and only -j differs."""
    base = tmp_path / "base"; base.mkdir()
    ws_a, ctl_a = _ready_ws(base, monkeypatch)                   # one fully-planned workspace
    ws_b = tmp_path / "b-ws"
    shutil.copytree(str(ws_a), str(ws_b))                        # exact copy -> same plan_id + artifacts
    recorded(ws_b)          # the copy's files have inodes of their own: its record, as prep's execution would write it

    def run(ws, n):
        _mock_tools(monkeypatch, ws)                             # rebind fingerprint mock to this ws path
        assert _execute_jobs(monkeypatch, ws, n) == 0
        summ = json.load(open(ws / ".photos-ingest" / "photos-25-execution-summary.json"))
        summ.pop("run_metadata", None)                          # volatile: jobs/timestamps/execution_id
        return summ, sorted(os.listdir(ws / "6-photos-by-dest" / "T"))

    s1, t1 = run(ws_a, 1)
    s4, t4 = run(ws_b, 4)
    assert s1 == s4                                              # identical summary (sans run_metadata)
    assert t1 == t4 == ["2024-07-03--14-00-00.arw", "2024-07-03--15-00-00.arw"]  # identical tree


@pytest.mark.spec("BLD-merge_execute", "BLD-geotag_execution")
def test_journal_writes_only_from_the_main_thread(tmp_path, monkeypatch):
    """Single-writer journal (BLD-geotag_execution): the confirmation journal is persisted ONLY by the main thread —
    worker threads apply per-file ops but never touch the journal. Probe every journal write under -j4
    and assert each originated on MainThread."""
    import threading
    ws, ctl = _ready_ws(tmp_path, monkeypatch)
    _mock_tools(monkeypatch, ws)
    orig = cal.write_json_artifact
    journal_threads = []

    def spy(path, obj, *a, **k):
        if isinstance(obj, dict) and "journal_version" in obj:           # a journal write
            journal_threads.append(threading.current_thread().name)
        return orig(path, obj, *a, **k)

    monkeypatch.setattr(cal, "write_json_artifact", spy)
    assert _execute_jobs(monkeypatch, ws, 4) == 0
    assert journal_threads, "expected at least one journal write"
    assert all(t == "MainThread" for t in journal_threads), journal_threads


@pytest.mark.spec("RUL-control_records_never_media")
def test_geotag_writes_no_artifacts_into_by_dest(tmp_path, monkeypatch):
    """RUL-control_records_never_media (anti): geotag's artifacts (photos-2*.json, plan/summary/journal) live ONLY under
    .photos-ingest/ — NEVER inside the scanned media tree 6-photos-by-dest. Drive a full plan +
    execute, then walk 6-photos-by-dest and assert no geotag artifact file landed there."""
    ws, ctl = _ready_ws(tmp_path, monkeypatch)                   # _ready_ws ran `plan` twice
    _mock_tools(monkeypatch, ws)
    assert _execute(monkeypatch, ws) == 0                        # full execute writes photos-24/25 + journal
    # the artifacts exist where they belong (control dir), proving the run actually produced them
    assert (ctl / "photos-24-executable-plan.json").exists()
    assert (ctl / "photos-25-execution-summary.json").exists()
    # ...but NONE of them (or any json/photos-* artifact) leaked into the media tree
    leaked = []
    for dp, _dn, fns in os.walk(ws / "6-photos-by-dest"):
        for fn in fns:
            if fn.startswith("photos-2") or fn.endswith(".json") or "journal" in fn:
                leaked.append(os.path.join(dp, fn))
    assert leaked == [], leaked
    # the only files under by-dest are the renamed media frames
    names = sorted(os.listdir(ws / "6-photos-by-dest" / "T"))
    assert names == ["2024-07-03--14-00-00.arw", "2024-07-03--15-00-00.arw"]


@pytest.mark.spec("RUL-one_configuration", test="TST-geotag_execution-geotag_reads_its_settings_from_the_workspace_alone")
def test_geotag_reads_its_settings_from_the_workspace_alone(tmp_path, monkeypatch):
    """Geotag takes its settings from the workspace's configuration alone: another configuration in every other
    place — the seed defaults, beside the executable, above the workspace, in the home folder, an environment
    variable per setting — naming other tracks, another format and another zone, changes neither the time it
    resolves nor the name it gives."""
    from _elsewhere import settings_elsewhere
    other = json.loads(json.dumps(utils.DEFAULT_CONFIG))
    gpx = tmp_path / "gpx-elsewhere"; gpx.mkdir()
    (gpx / "t.gpx").write_text(                                     # the same places, an hour later
        '<gpx xmlns="http://www.topografix.com/GPX/1/1"><trk><trkseg>'
        '<trkpt lat="50.0" lon="4.0"><time>2024-07-03T13:00:00Z</time></trkpt>'
        '<trkpt lat="51.0" lon="5.0"><time>2024-07-03T14:00:00Z</time></trkpt>'
        '</trkseg></trk></gpx>')
    other["gpx_root"] = str(gpx)
    other["filename_timestamp_format"] = "%Y%m%d_ELSEWHERE_%H%M%S"
    other["camera_time_and_timezone_policy"]["default_folder_timezone"] = "Asia/Tokyo"
    other["camera_time_and_timezone_policy"]["device_groups"] = {"fixed_clock_cameras": [CAM], "phones": []}
    exe = settings_elsewhere(monkeypatch, tmp_path, other)
    ws, ctl = _ready_ws(tmp_path, monkeypatch)
    _mock_tools(monkeypatch, ws)
    for command in ("plan", "execute"):                             # as the executable beside the defaults runs
        utils.CONFIG.clear(); utils.CONFIG.update(json.loads(json.dumps(utils.DEFAULT_CONFIG)))   # a run of its own
        monkeypatch.setattr(sys, "argv", [str(exe), command])
        try:
            rc = cal.main()
        except SystemExit as e:
            rc = e.code
        assert rc in (0, None), (command, rc)
    assert sorted(os.listdir(ws / "6-photos-by-dest" / "T")) == ["2024-07-03--14-00-00.arw", "2024-07-03--15-00-00.arw"]


@pytest.mark.spec("RUL-config_writers", test="TST-geotag_execution-geotag_leaves_config_byte_identical")
def test_geotag_leaves_config_byte_identical(tmp_path, monkeypatch):
    """Geotag never writes the workspace config (photos-00-config.json is hand-edited, authoritative).
    Snapshot its bytes, drive the full plan + execute, assert byte-for-byte identical (the geotag half
    of config-merge-readonly; the merge half is covered in test_merge_execute)."""
    ws, ctl = _ready_ws(tmp_path, monkeypatch)                   # _ready_ws already ran `plan` twice
    cfg_p = ctl / "photos-00-config.json"
    before = cfg_p.read_bytes()
    _mock_tools(monkeypatch, ws)
    assert _execute(monkeypatch, ws) == 0
    assert cfg_p.read_bytes() == before                          # config untouched across plan+execute


# --- stale rejection ---------------------------------------------------------

@pytest.mark.spec("INV-no_stale_use", "BLD-geotag_execution",
                  test="TST-geotag_execution-stale_plan_is_rejected_without_mutation")
def test_stale_plan_is_rejected_without_mutation(tmp_path, monkeypatch):
    ws, ctl = _ready_ws(tmp_path, monkeypatch)
    _mock_tools(monkeypatch, ws)
    (ctl / "photos-11-handoff.json").write_text('{"files": [], "cache_fingerprint": "x"}')  # change a dep
    before = sorted(os.listdir(ws / "6-photos-by-dest" / "T"))
    assert _execute(monkeypatch, ws) == 2                         # rejected
    assert sorted(os.listdir(ws / "6-photos-by-dest" / "T")) == before   # nothing mutated
    assert not (ctl / "photos-25-execution-summary.json").exists()


@pytest.mark.spec("BLD-track_catalogue", test="TST-geotag_execution-the_kept_tracks_are_no_operation_of_the_plan")
def test_the_kept_tracks_are_no_operation_of_the_plan(tmp_path, monkeypatch):
    """The catalogue of the tracks planning keeps in the record is written outside the plan's operations and leaves no
    entry in the journal: the journal holds the plan's operations and nothing else; execute only checks the tracks."""
    ws, ctl = _ready_ws(tmp_path, monkeypatch)
    conn = sqlite3.connect(str(ctl / "photos-00-ingest.db"))
    catalogue = lambda: conn.execute("SELECT * FROM gpx_track_files ORDER BY track_id").fetchall()
    planned = catalogue()
    assert [r[1] for r in planned] == ["t.gpx"]                           # planning catalogued the tracks...
    assert not any(n.startswith("journal-") for n in os.listdir(ctl))     # ...and journalled nothing
    plan = json.load(open(ctl / "photos-24-executable-plan.json"))
    ops = [o for d in plan["destinations"].values() for o in d["operations"]]
    assert ops and not any("gpx_track" in json.dumps(o) for o in ops)
    _mock_tools(monkeypatch, ws)
    assert _execute(monkeypatch, ws) == 0                                 # execute checks the tracks again
    assert catalogue() == planned
    conn.close()
    jpath = utils.journal_path(str(ws), plan["plan_id"])
    assert [n for n in os.listdir(ctl) if n.startswith("journal-")] == [os.path.basename(jpath)]
    journal = json.load(open(jpath))
    assert sorted(journal["operations"]) == sorted(o["operation_id"] for o in ops)
    assert "gpx_track" not in open(jpath).read()


@pytest.mark.spec("RUL-no_plan_no_run", test="TST-geotag_execution-missing_plan_errors")
def test_missing_plan_errors(tmp_path, monkeypatch):
    ws, ctl = _ready_ws(tmp_path, monkeypatch)
    os.remove(ctl / "photos-24-executable-plan.json")
    _mock_tools(monkeypatch, ws)
    assert _execute(monkeypatch, ws) == 2


# --- no-clobber recheck + determinism (unit) --------------------------------

@pytest.mark.spec("RUL-target_free_at_execute", "RUL-target_free_ignores_case",
                  test="TST-geotag_execution-target_occupied_recheck")
def test_target_occupied_recheck(tmp_path):
    wf = cal.GeotagWorkflow(str(tmp_path))
    (tmp_path / "A.JPG").write_text("x")
    assert wf._target_occupied(str(tmp_path), "a.jpg", "src.arw") is True      # case-insensitive
    assert wf._target_occupied(str(tmp_path), "b.jpg", "src.arw") is False
    assert wf._target_occupied(str(tmp_path), "A.JPG", "A.JPG") is False       # ignores the source itself


# --- unit: _exiftool_write seam --------------------------------------------

def _fake_exiftool(calls=None, rc=0, new=b"rewritten"):
    """Stands in for exiftool: writes the new file where `-o` says, as the real one does."""
    class _R:
        def __init__(self, rc): self.returncode = rc
    def _run(cmd, **k):
        if calls is not None:
            calls.append(cmd)
        if rc == 0:
            with open(cmd[cmd.index("-o") + 1], "wb") as f:
                f.write(new)
        return _R(rc)
    return _run


@pytest.mark.spec("BLD-metadata_safe_write", test="TST-geotag_execution-exiftool_write_invocation")
def test_exiftool_write_invocation(tmp_path, monkeypatch):
    """exiftool is told to write the new file beside the photo, never over it; geotag puts it in the photo's
    place, with the permissions the photo had."""
    wf = cal.GeotagWorkflow(str(tmp_path))
    photo = tmp_path / "x.jpg"; photo.write_bytes(b"orig"); os.chmod(photo, 0o640)
    calls = []
    monkeypatch.setattr(cal.subprocess, "run", _fake_exiftool(calls))
    assert wf._exiftool_write(str(photo), {"DateTimeOriginal": "2024:07:03 14:00:00"}) is True
    cmd = calls[0]
    assert cmd[:2] == ["exiftool", "-n"] and cmd[-3:] == ["-o", str(photo) + "_exiftool_tmp", str(photo)]
    assert not any("overwrite_original" in a for a in cmd)
    assert photo.read_bytes() == b"rewritten" and not (tmp_path / "x.jpg_exiftool_tmp").exists()
    assert os.stat(photo).st_mode & 0o777 == 0o640
    photo.write_bytes(b"orig")
    monkeypatch.setattr(cal.subprocess, "run", _fake_exiftool(rc=1))
    assert wf._exiftool_write(str(photo), {}) is False                # non-zero exit
    def _boom(*a, **k): raise OSError("no exiftool")
    monkeypatch.setattr(cal.subprocess, "run", _boom)
    assert wf._exiftool_write(str(photo), {}) is False                # tool missing
    assert photo.read_bytes() == b"orig" and os.listdir(tmp_path) == ["x.jpg"]


def test_exiftool_write_unlinks_stale_tmp(tmp_path, monkeypatch):
    """An interrupted earlier write can leave `<file>_exiftool_tmp`; the writer removes it for THIS target before
    it runs exiftool, which refuses an output that exists — so the resumed write never trips over the leftover."""
    wf = cal.GeotagWorkflow(str(tmp_path))
    target = tmp_path / "x.jpg"
    target.write_bytes(b"orig")
    stale = tmp_path / "x.jpg_exiftool_tmp"
    stale.write_bytes(b"partial")
    seen = []
    def _run(cmd, **k):
        seen.append(stale.exists())               # what exiftool finds at its output's name
        return _fake_exiftool()(cmd, **k)
    monkeypatch.setattr(cal.subprocess, "run", _run)
    assert wf._exiftool_write(str(target), {"DateTimeOriginal": "2024:07:03 14:00:00"}) is True
    assert seen == [False]                        # the leftover was gone before the write
    assert target.read_bytes() == b"rewritten" and not stale.exists()


@pytest.mark.spec("RUL-rewrite_in_place_atomic", "BLD-metadata_safe_write",
                  test="TST-geotag_execution-the_new_photo_is_on_disk_before_it_replaces_the_old")
def test_the_new_photo_is_on_disk_before_it_replaces_the_old(tmp_path, monkeypatch):
    """A power cut: the new file is synced to disk before the rename that puts it in the photo's place, and the
    folder after — a rename that reaches the disk ahead of its data is how a photo comes back empty."""
    wf = cal.GeotagWorkflow(str(tmp_path))
    photo = tmp_path / "x.jpg"; photo.write_bytes(b"orig")
    monkeypatch.setattr(cal.subprocess, "run", _fake_exiftool())
    steps, real_fsync, real_replace = [], os.fsync, os.replace
    def _fsync(fd):
        st = os.fstat(fd)
        steps.append("sync folder" if stat.S_ISDIR(st.st_mode) else f"sync file of {st.st_size}")
        return real_fsync(fd)
    def _replace(a, b):
        steps.append("rename")
        return real_replace(a, b)
    monkeypatch.setattr(os, "fsync", _fsync)
    monkeypatch.setattr(os, "replace", _replace)
    assert wf._exiftool_write(str(photo), {"DateTimeOriginal": "x"}) is True
    assert steps == [f"sync file of {len(b'rewritten')}", "rename", "sync folder"]


@pytest.mark.spec("RUL-rewrite_in_place_atomic",
                  test="TST-geotag_execution-a_write_interrupted_at_the_rename_leaves_the_photo_whole")
def test_a_write_interrupted_at_the_rename_leaves_the_photo_whole(tmp_path, monkeypatch):
    """Geotag itself stopped at the worst moment — the new file whole beside the photo, about to take its place:
    the photo is as it was, and the resumed write clears the leftover and puts the new one down."""
    wf = cal.GeotagWorkflow(str(tmp_path))
    photo = tmp_path / "x.jpg"; photo.write_bytes(b"orig")
    monkeypatch.setattr(cal.subprocess, "run", _fake_exiftool())
    def _stopped(a, b): raise KeyboardInterrupt
    with monkeypatch.context() as m:
        m.setattr(os, "replace", _stopped)
        with pytest.raises(KeyboardInterrupt):
            wf._exiftool_write(str(photo), {"DateTimeOriginal": "x"})
    assert photo.read_bytes() == b"orig" and (tmp_path / "x.jpg_exiftool_tmp").exists()
    assert wf._exiftool_write(str(photo), {"DateTimeOriginal": "x"}) is True
    assert photo.read_bytes() == b"rewritten" and os.listdir(tmp_path) == ["x.jpg"]


# Loaded into the real exiftool (PERL5OPT), it kills exiftool the moment it has opened the new file it writes
# beside the photo: nothing, or half a file, is there.
_KILL_AT_OUTPUT = r"""package CartoKillAtOutput;
require Image::ExifTool;
no warnings 'redefine';
my $open = \&Image::ExifTool::Open;
*Image::ExifTool::Open = sub {
    my $ok = $open->(@_);
    kill 'KILL', $$ if $ok and defined $_[2] and $_[2] =~ /_exiftool_tmp$/;
    return $ok;
};
1;
"""


@pytest.mark.skipif(shutil.which("exiftool") is None or shutil.which("magick") is None,
                    reason="needs real exiftool + ImageMagick")
@pytest.mark.spec("RUL-rewrite_in_place_atomic", "BLD-metadata_safe_write",
                  test="TST-geotag_execution-an_interrupted_metadata_write_leaves_the_photo_whole")
def test_an_interrupted_metadata_write_leaves_the_photo_whole(tmp_path, monkeypatch):
    """The real exiftool, killed while it writes the new file beside the photo, leaves the photo as it was, byte
    for byte; the write done again puts the new tags down whole, the photo keeping its permissions."""
    import subprocess
    photo = tmp_path / "a.jpg"
    subprocess.run(["magick", "-size", "64x64", "plasma:", str(photo)], check=True, stdin=subprocess.DEVNULL,
                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    os.chmod(photo, 0o640)
    original = photo.read_bytes()
    tags = {"DateTimeOriginal": "2024:07:03 14:00:00", "OffsetTimeOriginal": "+02:00",
            "GPSLatitude": 50.0, "GPSLatitudeRef": "N", "GPSLongitude": 4.0, "GPSLongitudeRef": "E",
            "GPSProcessingMethod": "interpolated"}
    wf = cal.GeotagWorkflow(str(tmp_path))
    (tmp_path / "CartoKillAtOutput.pm").write_text(_KILL_AT_OUTPUT)
    with monkeypatch.context() as m:
        m.setenv("PERL5LIB", str(tmp_path))
        m.setenv("PERL5OPT", "-MCartoKillAtOutput")
        assert wf._exiftool_write(str(photo), tags) is False             # killed mid-write
    assert photo.read_bytes() == original                                # the photo, intact
    assert wf._exiftool_write(str(photo), tags) is True                  # the write done again
    assert not (tmp_path / "a.jpg_exiftool_tmp").exists()
    assert photo.read_bytes() != original and os.stat(photo).st_mode & 0o777 == 0o640
    assert cal._holds_writes(wf._exiftool_read(str(photo), sorted(tags)), tags)
    assert subprocess.run(["magick", "identify", str(photo)], stdin=subprocess.DEVNULL,
                          capture_output=True).returncode == 0           # still a whole image


def test_exiftool_write_no_tmp_is_noop(tmp_path, monkeypatch):
    """Clearing a leftover is best-effort: none there (the normal case) is not an error."""
    wf = cal.GeotagWorkflow(str(tmp_path))
    photo = tmp_path / "y.jpg"; photo.write_bytes(b"orig")
    monkeypatch.setattr(cal.subprocess, "run", _fake_exiftool())
    assert wf._exiftool_write(str(photo), {}) is True


def test_target_occupied_bad_directory(tmp_path):
    wf = cal.GeotagWorkflow(str(tmp_path))
    assert wf._target_occupied(str(tmp_path / "nope"), "a.jpg", "s.jpg") is False  # listdir OSError -> False


# --- unit: _apply_file precondition + resume + rename branches --------------

def _op(oid, typ, rel, **extra):
    return {"operation_id": oid, "type": typ, "relative_path": rel,
            "preconditions": extra.pop("pre", {}), **extra}


@pytest.mark.spec("RUL-hash_is_the_dependency_check", "RUL-geotag_execution_resumable",
                  "RUL-found_applied_never_remade",
                  test="TST-geotag_execution-apply_file_precondition_and_resume_branches")
def test_apply_file_precondition_and_resume_branches(tmp_path, monkeypatch):
    wf = cal.GeotagWorkflow(str(tmp_path))
    p = tmp_path / "f.arw"; p.write_bytes(b"data")
    monkeypatch.setattr(cal.GeotagWorkflow, "_exiftool_write", lambda self, path, t: True)
    # already confirmed -> skipped (no stat, no write)
    r = wf._apply_file("f.arw", [_op("oC", "metadata_time_write", "f.arw")], {"oC": "confirmed"}, {})
    assert r["skipped"] == ["oC"]
    # missing file (no rename) -> blocker
    r = wf._apply_file("gone.arw", [_op("o", "metadata_time_write", "gone.arw")], {}, {})
    assert "missing at execute time" in r["blocker"]
    # size/mtime changed AND the content fingerprint differs -> external change -> blocker
    monkeypatch.setattr(cal.ContentHasher, "fingerprint_image", staticmethod(lambda path: {"value": "OTHER"}))
    r = wf._apply_file("f.arw", [_op("o", "metadata_time_write", "f.arw",
                       pre={"size": 999, "content_fingerprint": "FP"})], {}, {})
    assert "content fingerprint differs" in r["blocker"]
    # size/mtime changed BUT the content fingerprint still matches, and the file holds the planned values ->
    # geotag's own interrupted write: counted applied, written nothing again
    monkeypatch.setattr(cal.ContentHasher, "fingerprint_image", staticmethod(lambda path: {"value": "FP"}))
    written = []
    monkeypatch.setattr(cal.GeotagWorkflow, "_exiftool_write", lambda self, path, t: written.append(t) or True)
    monkeypatch.setattr(cal.GeotagWorkflow, "_exiftool_read", lambda self, path, keys: {"DateTimeOriginal": "x"})
    r = wf._apply_file("f.arw", [_op("o", "metadata_time_write", "f.arw",
                       pre={"size": 999, "mtime_ns": 1, "content_fingerprint": "FP"},
                       writes={"DateTimeOriginal": "x"})], {}, {})
    assert r["blocker"] is None and r["applied"] == ["o"] and written == []


@pytest.mark.spec("RUL-geotag_execution_resumable", "BLD-geotag_execution", "RUL-edit_since_plan_never_overwritten",
                  test="TST-geotag_execution-an_edit_made_since_the_plan_is_never_overwritten")
def test_an_edit_made_since_the_plan_is_never_overwritten(tmp_path, monkeypatch):
    # The photo's metadata changed between plan and execute — its time edited in another program — and its image
    # did not: execute cannot take it for its own interrupted write, since the photo holds none of the planned
    # values; it stops on the photo rather than writing over the edit. A photo with only a rename planned, changed
    # since, was not written by geotag at all, and stops too.
    wf = cal.GeotagWorkflow(str(tmp_path))
    (tmp_path / "f.arw").write_bytes(b"data")
    monkeypatch.setattr(cal.ContentHasher, "fingerprint_image", staticmethod(lambda path: {"value": "FP"}))
    written = []
    monkeypatch.setattr(cal.GeotagWorkflow, "_exiftool_write", lambda self, path, t: written.append(t) or True)
    monkeypatch.setattr(cal.GeotagWorkflow, "_exiftool_read",
                        lambda self, path, keys: {"DateTimeOriginal": "2024:07:03 09:00:00"})
    pre = {"size": 999, "mtime_ns": 1, "content_fingerprint": "FP"}
    r = wf._apply_file("f.arw", [_op("o", "metadata_time_write", "f.arw", pre=pre,
                       writes={"DateTimeOriginal": "2024:07:03 14:25:00"})], {}, {})
    assert "changed since the plan" in r["blocker"] and r["applied"] == [] and written == []
    ren = _op("oR", "rename_no_clobber", "f.arw", pre=pre, **{"from": "f.arw", "to": "g.arw"})
    r = wf._apply_file("f.arw", [ren], {}, {})
    assert "changed since the plan" in r["blocker"] and (tmp_path / "f.arw").exists()
    # the comparison: a coordinate by magnitude (its sign is in the reference tag), a cleared tag absent
    assert cal._holds_writes({"GPSLatitude": 33.865143, "GPSLatitudeRef": "S"},
                             {"GPSLatitude": -33.865143, "GPSLatitudeRef": "S"})
    assert cal._holds_writes({}, {"GPSLatitude": "", "GPSLatitudeRef": ""})
    assert not cal._holds_writes({"GPSLatitude": 33.9}, {"GPSLatitude": 33.865143})


@pytest.mark.spec("BLD-own_write_recognised", test="TST-geotag_execution-planned_tags_held_by_magnitude_text_or_absence")
def test_planned_tags_held_by_magnitude_text_or_absence():
    """The read-back test that tells geotag's own interrupted write from an edit: a coordinate equal in magnitude to
    within a millionth of a degree, its sign left to the reference tag; any other tag equal as text; a tag planned
    empty absent or empty."""
    lat = {"GPSLatitude": 50.123456}
    assert cal._holds_writes({"GPSLatitude": 50.1234569}, lat)                   # 0.9e-6 off: held
    assert cal._holds_writes({"GPSLatitude": "-50.123456"}, lat)                 # sign aside, read as text
    assert not cal._holds_writes({"GPSLatitude": 50.1234575}, lat)               # 1.5e-6 off: not held
    assert not cal._holds_writes({"GPSLatitude": "north"}, lat) and not cal._holds_writes({}, lat)
    t = {"DateTimeOriginal": "2024:07:03 14:00:00", "OffsetTimeOriginal": "+02:00"}
    assert cal._holds_writes(dict(t), t)
    assert not cal._holds_writes(dict(t, OffsetTimeOriginal="+0200"), t)          # text, not meaning
    assert cal._holds_writes({"GPSLatitude": ""}, {"GPSLatitude": ""}) and cal._holds_writes({}, {"GPSLatitude": None})
    assert not cal._holds_writes({"GPSLatitude": 0}, {"GPSLatitude": ""})         # a value where none was planned


def test_apply_file_rename_skip_and_failure(tmp_path, monkeypatch):
    wf = cal.GeotagWorkflow(str(tmp_path))
    p = tmp_path / "a.arw"; p.write_bytes(b"x")
    ren = _op("oR", "rename_no_clobber", "a.arw", **{"from": "a.arw", "to": "b.arw"})
    # rename already confirmed -> skipped (file not moved)
    r = wf._apply_file("a.arw", [ren], {"oR": "confirmed"}, {})
    assert r["applied"] == [] and (tmp_path / "a.arw").exists()
    # _move_no_clobber raises -> failure recorded
    monkeypatch.setattr(cal, "_move_no_clobber", lambda s, d: (_ for _ in ()).throw(OSError("xdev")))
    r = wf._apply_file("a.arw", [ren], {}, {})
    assert r["failed"] == ["oR"] and "rename failed" in r["blocker"]


@pytest.mark.spec("RUL-format_fixed_once_named", "INV-no_stale_use", "RUL-tracks_in_dependencies",
                  "RUL-camera_group_derivation_versioned",
                  test="TST-geotag_execution-revalidate_detects_each_stale_input")
def test_revalidate_detects_each_stale_input(tmp_path, monkeypatch):
    ws, ctl = _ready_ws(tmp_path, monkeypatch)
    wf = cal.GeotagWorkflow(str(ws)); wf.preflight(for_execute=True)
    plan = json.load(open(ctl / "photos-24-executable-plan.json"))
    gpx = wf.plan_tracks(plan)
    assert wf.revalidate_plan(plan, gpx) == []                        # fresh -> nothing stale
    assert any("not 'ready'" in s for s in wf.revalidate_plan({**plan, "status": "blocked"}, gpx))
    for k in ("config_fingerprint", "filename_format_fingerprint", "camera_group_fingerprint",
              "folders_fingerprint", "media_extensions_fingerprint", "gpx_fingerprint",
              "camera_group_key_version", "metadata_field_set_version"):
        pk = {**plan, "depends_on": {**plan["depends_on"], k: "WRONG"}}
        assert any(k in s for s in wf.revalidate_plan(pk, gpx)), k
    pk = {**plan, "depends_on": {**plan["depends_on"], "planned_operation_fingerprint": "WRONG"}}
    assert any("planned operations changed" in s for s in wf.revalidate_plan(pk, gpx))


@pytest.mark.spec("RUL-plan_carried_out_by_its_code", "BLD-code_fingerprint",
                  test="TST-geotag_execution-a_plan_made_by_other_code_is_stale")
def test_a_plan_made_by_other_code_is_stale(tmp_path, monkeypatch):
    """Geotag's executable plan records the code that made it; another build, or a plan recording none,
    makes it stale before any change."""
    ws, ctl = _ready_ws(tmp_path, monkeypatch)
    wf = cal.GeotagWorkflow(str(ws)); wf.preflight(for_execute=True)
    plan = json.load(open(ctl / "photos-24-executable-plan.json"))
    gpx = wf.plan_tracks(plan)
    assert plan["depends_on"]["code_fingerprint"] == utils.code_fingerprint()
    for recorded in ("0" * 64, None):
        pk = {**plan, "depends_on": {**plan["depends_on"], "code_fingerprint": recorded}}
        assert any("code_fingerprint" in s for s in wf.revalidate_plan(pk, gpx)), recorded


def test_corrupt_journal_stops_execution(tmp_path, monkeypatch):
    ws, ctl = _ready_ws(tmp_path, monkeypatch)
    _mock_tools(monkeypatch, ws)
    # a corrupt journal is never taken for an empty one (RUL-unreadable_execution_record_stops)
    plan = json.load(open(ctl / "photos-24-executable-plan.json"))
    with open(utils.journal_path(str(ws), plan["plan_id"]), "w") as f:
        f.write("{corrupt")
    assert _execute(monkeypatch, ws) == 2
    assert not (ctl / "photos-25-execution-summary.json").exists()
    assert open(utils.journal_path(str(ws), plan["plan_id"])).read() == "{corrupt"


@pytest.mark.spec("BLD-rename_planning", "BLD-geotag_execution",
                  test="TST-geotag_execution-rename_target_occupied_at_execute_blocks")
def test_rename_target_occupied_at_execute_blocks(tmp_path, monkeypatch):
    ws, ctl = _ready_ws(tmp_path, monkeypatch)
    _mock_tools(monkeypatch, ws)
    # occupy a planned rename target AFTER the plan was written -> execute-time no-clobber blocker
    (ws / "6-photos-by-dest" / "T" / "2024-07-03--14-00-00.arw").write_bytes(b"squatter")
    recorded(ws)            # a file put there stops every command first (test_workspace_check); taken as the state here
    assert _execute(monkeypatch, ws) == 3
    s = _summary(ctl)
    assert s["status"] == "partial" and any("occupied at execute time" in b for b in s["blockers"])
    assert (ws / "6-photos-by-dest" / "T" / "a.arw").exists()      # not clobbered/renamed


@pytest.mark.spec("RUL-geotag_extension_lowercase", "BLD-case_rename_via", "RUL-target_free_at_execute",
                  test="TST-geotag_execution-a_change_of_case_alone_goes_by_a_temporary_name")
def test_a_change_of_case_alone_goes_by_a_temporary_name(tmp_path, monkeypatch):
    """`X.JPG` to `X.jpg`: on a filesystem that ignores case the new name is the photo's own, which a no-clobber move
    refuses. The rename goes by a free temporary name in two no-clobber moves; interrupted between them, the next run
    finds the photo under the temporary name and completes it, once it is seen to be that photo. A temporary name
    taken blocks the rename, nothing moved."""
    real_move = cal._move_no_clobber

    def case_blind_move(src, dst, **kw):          # a filesystem that ignores case: the photo's own name is taken
        if os.path.basename(src).lower() == os.path.basename(dst).lower() or \
                any(e.lower() == os.path.basename(dst).lower() for e in os.listdir(os.path.dirname(dst))):
            raise FileExistsError(dst)
        return real_move(src, dst, **kw)
    monkeypatch.setattr(cal, "_move_no_clobber", case_blind_move)
    monkeypatch.setattr(cal.ContentHasher, "fingerprint_image", staticmethod(lambda path: {"value": "fp"}))
    wf = cal.GeotagWorkflow(str(tmp_path))
    ren = _op("oR", "rename_no_clobber", "X.JPG", pre={"content_fingerprint": "fp"},
              **{"from": "X.JPG", "to": "X.jpg", "via": "X.carto-case.jpg"})
    (tmp_path / "X.JPG").write_bytes(b"x")
    r = wf._apply_file("X.JPG", [ren], {}, {})
    assert r["applied"] == ["oR"] and r["blocker"] is None and os.listdir(tmp_path) == ["X.jpg"]
    assert r["after"]["relative_path"] == "X.jpg"
    # interrupted between the two moves: the photo waits under the temporary name
    os.rename(tmp_path / "X.jpg", tmp_path / "X.carto-case.jpg")
    r = wf._apply_file("X.JPG", [ren], {}, {})
    assert r["applied"] == ["oR"] and r["blocker"] is None and os.listdir(tmp_path) == ["X.jpg"]
    os.rename(tmp_path / "X.jpg", tmp_path / "X.carto-case.jpg")
    monkeypatch.setattr(cal.ContentHasher, "fingerprint_image", staticmethod(lambda path: {"value": "another"}))
    r = wf._apply_file("X.JPG", [ren], {}, {})                        # another photo there: not taken for it
    assert r["blocker"] and "not this photo" in r["blocker"] and not r["applied"]
    assert os.listdir(tmp_path) == ["X.carto-case.jpg"]
    # the temporary name taken at execute: blocked, the photo left as it was
    os.rename(tmp_path / "X.carto-case.jpg", tmp_path / "X.JPG")
    (tmp_path / "x.CARTO-case.jpg").write_bytes(b"squatter")
    monkeypatch.setattr(cal.ContentHasher, "fingerprint_image", staticmethod(lambda path: {"value": "fp"}))
    r = wf._apply_file("X.JPG", [ren], {}, {})
    assert r["blocker"] and "occupied at execute time" in r["blocker"] and not r["applied"]
    assert sorted(os.listdir(tmp_path)) == ["X.JPG", "x.CARTO-case.jpg"]


@pytest.mark.spec("RUL-geotag_execution_resumable", "RUL-found_applied_never_remade",
                  "RUL-applied_unrecorded_is_recorded",
                  test="TST-geotag_execution-apply_file_already_renamed_resumes_without_journal")
def test_apply_file_already_renamed_resumes_without_journal(tmp_path, monkeypatch):
    """A crashed prior run that already renamed the file (source gone, planned target present) is
    detected by state on resume — even with an empty/lost journal — rather than blocking on the missing
    source (BLD-geotag_execution): once the target is seen to be that photo holding the planned values, its operations
    are recorded as done (never redone), so the run that applied them is in the journal after all. A file
    merely of the target's name is not taken for the photo."""
    wf = cal.GeotagWorkflow(str(tmp_path))
    (tmp_path / "b.arw").write_bytes(b"x")                            # already at its planned target
    ops = [_op("oM", "metadata_time_write", "a.arw", pre={"content_fingerprint": "fp"},
               writes={"DateTimeOriginal": "x"}),
           _op("oR", "rename_no_clobber", "a.arw", **{"from": "a.arw", "to": "b.arw"})]
    monkeypatch.setattr(cal.ContentHasher, "fingerprint_image", staticmethod(lambda path: {"value": "fp"}))
    monkeypatch.setattr(cal.GeotagWorkflow, "_exiftool_read", lambda self, path, keys: {"DateTimeOriginal": "x"})
    r = wf._apply_file("a.arw", ops, {}, {})                          # journal empty, source gone
    assert r["skipped"] == ["oM", "oR"] == r["found"] and not r["applied"] and r["blocker"] is None
    assert r["after"]["relative_path"] == "b.arw"
    monkeypatch.setattr(cal.ContentHasher, "fingerprint_image", staticmethod(lambda path: {"value": "another"}))
    r = wf._apply_file("a.arw", ops, {}, {})                          # another photo under that name
    assert "is not this photo as planned" in r["blocker"] and not r.get("found")
    monkeypatch.setattr(cal.ContentHasher, "fingerprint_image", staticmethod(lambda path: {"value": "fp"}))
    monkeypatch.setattr(cal.GeotagWorkflow, "_exiftool_read", lambda self, path, keys: {"DateTimeOriginal": "other"})
    r = wf._apply_file("a.arw", ops, {}, {})                          # the photo, not holding what was planned
    assert "is not this photo as planned" in r["blocker"]


def test_corrupt_prior_summary_stops_execution(tmp_path, monkeypatch):
    ws, ctl = _ready_ws(tmp_path, monkeypatch)
    _mock_tools(monkeypatch, ws)
    (ctl / "photos-25-execution-summary.json").write_text("{corrupt")   # unreadable: its acceptances unknown
    assert _execute(monkeypatch, ws) == 2                              # never taken for none
    assert (ctl / "photos-25-execution-summary.json").read_text() == "{corrupt"


def test_execute_on_sealed_workspace_warns_and_blocks(tmp_path, monkeypatch):
    ws = tmp_path / "ws"; ws.mkdir()
    for d in MANAGED:
        (ws / d).mkdir()
    ctl = ws / ".photos-ingest"; ctl.mkdir()
    (ctl / "photos-00-workspace-guard").touch()
    open(utils.sealed_marker_path(str(ws)), "w").close()
    (ws / "loose.jpg").write_bytes(b"x")                              # a dump -> exercises the warning print
    assert _execute(monkeypatch, ws) == 2                             # sealed -> blocked (exit 2)


@pytest.mark.spec("BLD-execution_summary")
def test_summary_keeps_run_metadata_separate(tmp_path, monkeypatch):
    ws, ctl = _ready_ws(tmp_path, monkeypatch)
    _mock_tools(monkeypatch, ws)
    wf = cal.GeotagWorkflow(str(ws)); wf.preflight(for_execute=True)
    s = wf.execute_plan(1, "2024-07-03T00:00:00Z", "exec-1")
    # the volatile bits (timestamps, execution id, jobs) live ONLY in run_metadata, off the
    # fingerprint-bearing body (summarizes / totals / plan_id), per BLD-execution_summary.
    assert s["run_metadata"] == {"execution_id": "exec-1", "started_at": "2024-07-03T00:00:00Z",
                                 "finished_at": "2024-07-03T00:00:00Z", "jobs": 1}
    body = json.dumps({k: v for k, v in s.items() if k != "run_metadata"})
    assert "2024-07-03T00:00:00Z" not in body and "exec-1" not in body
    assert s["summarizes"][cal.EXECUTABLE_PLAN_ARTIFACT]["sha256"]


# --- pre-mutation ZFS snapshot (BLD-one_snapshot_mechanism, shared helper) ---

def _mock_zfs(monkeypatch, *, fail=False):
    import subprocess as _sp
    import types as _t
    monkeypatch.setattr(utils, "detect_zfs_dataset", lambda p: "pool/ws")
    def run(*a, **k):
        if fail:
            raise _sp.CalledProcessError(1, "zfs", stderr="pool busy")
        return _t.SimpleNamespace(returncode=0, stdout="", stderr="")
    monkeypatch.setattr(_sp, "run", run)


@pytest.mark.spec("BLD-geotag_execution")
def test_execute_records_zfs_snapshot(tmp_path, monkeypatch):
    zfs = {"enabled": True, "snapshots_required": True, "snapshot_prefix": "px-",
           "datasets": {"workspace": "auto", "library": "auto"}}
    ws, ctl = _ready_ws(tmp_path, monkeypatch, zfs=zfs)
    _mock_tools(monkeypatch, ws); _mock_zfs(monkeypatch)
    assert _execute(monkeypatch, ws) == 0
    s = _summary(ctl)
    assert s["snapshot"]["ok"] and s["snapshot"]["snapshot_name"] == f"pool/ws@px-geotag-{s['plan_id']}"


@pytest.mark.spec("BLD-geotag_execution")
def test_execute_aborts_when_required_snapshot_fails(tmp_path, monkeypatch):
    zfs = {"enabled": True, "snapshots_required": True, "snapshot_prefix": "px-",
           "datasets": {"workspace": "auto", "library": "auto"}}
    ws, ctl = _ready_ws(tmp_path, monkeypatch, zfs=zfs)
    _mock_tools(monkeypatch, ws); _mock_zfs(monkeypatch, fail=True)
    before = sorted(os.listdir(ws / "6-photos-by-dest" / "T"))
    assert _execute(monkeypatch, ws) == 2                            # required snapshot failed -> rejected
    assert sorted(os.listdir(ws / "6-photos-by-dest" / "T")) == before   # nothing mutated
    # BLD-execution_summary: the snapshot record is carried into photos-25 even on the abort path
    s = _summary(ctl)
    assert s["status"] == "rejected" and s["snapshot"]["ok"] is False and s["snapshot"]["required"] is True
    assert s["blockers"] and "snapshot failed" in s["blockers"][0]


@pytest.mark.spec("BLD-execution_summary_written", "RUL-content_acceptance_stays_open",
                  test="TST-geotag_execution-summary_written_only_by_a_run_that_executes")
def test_summary_written_only_by_a_run_that_executes(tmp_path, monkeypatch):
    """photos-25 is written by a run that applied the plan, or whose required snapshot failed — that one carrying
    the mismatches still open, acceptances and all. A preflight refusal, a stale plan or an interrupt writes none:
    the earlier summary stays as it was."""
    zfs = {"enabled": True, "snapshots_required": True, "snapshot_prefix": "px-",
           "datasets": {"workspace": "auto", "library": "auto"}}
    ws, ctl = _ready_ws(tmp_path, monkeypatch, zfs=zfs)
    _mock_tools(monkeypatch, ws, content_changed=True); _mock_zfs(monkeypatch)
    assert _execute(monkeypatch, ws) == 3                                 # applied: written, mismatches in it
    sp = ctl / "photos-25-execution-summary.json"
    s = _summary(ctl)
    assert s["fingerprint_mismatches"]
    for m in s["fingerprint_mismatches"]:
        m["user_decision"]["accept_fingerprint_change"] = True
    sp.write_text(json.dumps(s))
    earlier = sp.read_bytes()

    def unchanged():
        return sp.read_bytes() == earlier and not list(ctl.glob("photos-25-execution-summary-*.json"))

    (ws / "6-photos-by-dest" / "T" / "jpg").mkdir()                         # a preflight refusal
    assert _execute(monkeypatch, ws) == 2 and unchanged()
    (ws / "6-photos-by-dest" / "T" / "jpg").rmdir()
    gd = ctl / "photos-23-gps-decisions.json"
    held = gd.read_bytes()
    gd.write_bytes(held + b" ")                                            # a stale plan
    assert _execute(monkeypatch, ws) == 2 and unchanged()
    gd.write_bytes(held)

    def interrupted(*a, **k):
        raise KeyboardInterrupt
    with monkeypatch.context() as m:                                      # an interrupt while applying
        m.setattr(cal.GeotagWorkflow, "_apply_file_contained", interrupted)
        assert _execute(monkeypatch, ws) == 130 and unchanged()

    _mock_zfs(monkeypatch, fail=True)                                     # a required snapshot that fails
    assert _execute(monkeypatch, ws) == 2
    s = _summary(ctl)
    assert s["status"] == "rejected"
    assert s["fingerprint_mismatches"] == json.loads(earlier)["fingerprint_mismatches"]   # acceptances kept
    assert (ctl / "photos-25-execution-summary-001.json").read_bytes() == earlier


@pytest.mark.spec("RUL-camera_classes_not_derivation",
                  test="TST-geotag_execution-reclassing_a_camera_group_changes_its_treatment_not_its_key")
def test_reclassing_a_camera_group_changes_its_treatment_not_its_key(tmp_path, monkeypatch):
    """Of a camera group the configuration sets only its class: the same group classed as a fixed-clock camera, then
    as a phone, then as a camera again, is treated as each — a clock offset decided for it as a camera, none as a
    phone — and is the same group in geotag's records every time, under the key prep derived."""
    ws, ctl = _ready_ws(tmp_path, monkeypatch)
    cfg_p = ctl / "photos-00-config.json"
    seen = []
    for groups in ({"fixed_clock_cameras": [CAM], "phones": []}, {"fixed_clock_cameras": [], "phones": [CAM]},
                   {"fixed_clock_cameras": [CAM], "phones": []}):
        cfg = json.loads(cfg_p.read_text())
        cfg["camera_time_and_timezone_policy"]["device_groups"] = groups
        cfg_p.write_text(json.dumps(cfg))
        monkeypatch.chdir(str(ws))
        monkeypatch.setattr(sys, "argv", ["photos-2-geotag", "plan"])
        try:
            cal.main()
        except SystemExit as e:
            assert not e.code, groups
        dest = json.load(open(ctl / "photos-21-time-decisions.json"))["destinations"]["6-photos-by-dest/T"]
        cells = dest.get("camera_group_time_decisions") or {}
        cache = cal.GeotagCache(str(ws))
        try:
            keys = sorted({r["camera_group"] for r in cache.get_rows()})   # the group each photo was resolved as
        finally:
            cache.close()
        seen.append((keys, {k: c["camera_group_class"] for k, c in cells.items()}))
        assert json.load(open(ctl / "photos-24-executable-plan.json"))["status"] == "ready", groups
    assert seen == [([CAM], {CAM: "camera"}), ([CAM], {}), ([CAM], {CAM: "camera"})], seen


_SNAPSHOTS_ON = {"enabled": True, "snapshots_required": False, "snapshot_prefix": "px-",
                 "datasets": {"workspace": "auto", "library": "auto"}}


def _fake_snapshot(monkeypatch, probe):
    """Fake geotag's snapshot: each one asked for records `probe()` in the returned list."""
    taken = []

    def take(ws, plan_id, label, **_k):
        taken.append(probe())
        return {"required": False, "ok": True, "snapshot_name": f"pool/ws@px-{label}-{plan_id}",
                "command": "zfs snapshot", "exit_code": 0, "stdout": "", "stderr": ""}
    monkeypatch.setattr(cal, "take_zfs_snapshot", take)
    return taken


@pytest.mark.spec("RUL-snapshot_after_validation",
                  test="TST-geotag_execution-no_snapshot_before_the_plan_is_validated")
def test_no_snapshot_before_the_plan_is_validated(tmp_path, monkeypatch):
    """Geotag's snapshot follows the plan's validation against its dependencies: a plan whose time decisions were
    edited after planning is refused with no snapshot taken at all, and a plan that passes is validated first."""
    ws, ctl = _ready_ws(tmp_path, monkeypatch, zfs=_SNAPSHOTS_ON)
    _mock_tools(monkeypatch, ws)
    events = []
    _fake_snapshot(monkeypatch, lambda: events.append("snapshot"))
    real = cal.GeotagWorkflow.revalidate_plan

    def revalidate(self, *a, **k):
        events.append("revalidate"); return real(self, *a, **k)
    monkeypatch.setattr(cal.GeotagWorkflow, "revalidate_plan", revalidate)

    td = ctl / "photos-21-time-decisions.json"
    decided = td.read_bytes()
    td.write_text(json.dumps(json.loads(decided), indent=1))    # a dependency changed after planning
    before = sorted(os.listdir(ws / "6-photos-by-dest" / "T"))
    assert _execute(monkeypatch, ws) == 2
    assert events == ["revalidate"], events                     # refused, and no snapshot taken
    assert sorted(os.listdir(ws / "6-photos-by-dest" / "T")) == before

    td.write_bytes(decided)
    events.clear()
    assert _execute(monkeypatch, ws) == 0
    assert events[:2] == ["revalidate", "snapshot"], events
    assert _summary(ctl)["snapshot"]["ok"]


@pytest.mark.spec("RUL-snapshot_under_lock", test="TST-geotag_execution-snapshot_is_taken_while_the_lock_is_held")
def test_snapshot_is_taken_while_the_lock_is_held(tmp_path, monkeypatch):
    """Geotag's snapshot is taken while the workspace lock is held: probed, from a file descriptor of its own, at the
    moment the snapshot is asked for."""
    ws, ctl = _ready_ws(tmp_path, monkeypatch, zfs=_SNAPSHOTS_ON)
    _mock_tools(monkeypatch, ws)
    held = _fake_snapshot(monkeypatch, lambda: utils.WorkspaceLock(str(ws), create=False).held_owner() is not None)
    assert _execute(monkeypatch, ws) == 0
    assert held == [True], held
    assert utils.WorkspaceLock(str(ws), create=False).held_owner() is None   # the probe tells held from free


@pytest.mark.spec("RUL-execution_only_the_plan")
def test_execute_applies_recorded_plan_verbatim_no_recalc(tmp_path, monkeypatch):
    """RUL-execution_only_the_plan (anti): execute applies the recorded photos-24 plan VERBATIM and never recalculates a
    decision. Doctor a saved rename target to a value the planner would never derive (re-stamping
    ONLY the plan's own planned-operation fingerprint so the staleness gate still passes — every
    actual decision is untouched), then assert execute renames the file to the DOCTORED target, not
    the local-time name it would have recomputed."""
    ws, ctl = _ready_ws(tmp_path, monkeypatch)
    _mock_tools(monkeypatch, ws)
    pp = ctl / "photos-24-executable-plan.json"
    plan = json.load(open(pp))
    doctored = False
    for dd in plan["destinations"].values():
        for op in dd["operations"]:
            if op["type"] == "rename_no_clobber" and op["relative_path"].endswith("/a.arw"):
                op["to"] = "DOCTORED.arw"
                doctored = True
    assert doctored, "expected a planned rename for a.arw to doctor"
    # Re-stamp ONLY the planned-operation fingerprint (the same flatten revalidate_plan uses) so the
    # tampered plan is accepted by the staleness gate — proving execute applies what is SAVED, not a
    # fresh derivation. No other recorded decision is changed.
    all_ops = [o for d in plan["destinations"].values() for o in d["operations"]]
    plan["depends_on"]["planned_operation_fingerprint"] = cal.sha256_text(json.dumps(all_ops, sort_keys=True))
    pp.write_text(json.dumps(plan))
    assert _execute(monkeypatch, ws) == 0
    # Applied VERBATIM: the doctored target exists; the name execute WOULD have re-derived does not.
    assert (ws / "6-photos-by-dest" / "T" / "DOCTORED.arw").exists()
    assert not (ws / "6-photos-by-dest" / "T" / "2024-07-03--14-00-00.arw").exists()
    assert _summary(ctl)["status"] == "success"


@pytest.mark.spec("BLD-drift_validation")
def test_execute_rejects_when_drift_validation_changed_after_planning(tmp_path, monkeypatch):
    """RUL-geotag_plan_carries_every_dependency (anti): photos-22 (the GPS-drift confirmation) is a recorded plan
    dependency, so an execute whose drift artifact changed after planning is rejected before ANY mutation — the drift
    confirmation can't be withdrawn out from under a saved plan."""
    ws, ctl = _ready_ws(tmp_path, monkeypatch)
    _mock_tools(monkeypatch, ws)
    dvp = ctl / "photos-22-gps-drift-validation.json"
    assert dvp.exists()                                     # the dependency the plan recorded
    art = json.load(open(dvp))
    art["withdrawn_after_planning"] = True                  # mutate the recorded drift dependency
    dvp.write_text(json.dumps(art))
    before = sorted(os.listdir(ws / "6-photos-by-dest" / "T"))
    assert _execute(monkeypatch, ws) == 2                   # rejected as stale
    assert sorted(os.listdir(ws / "6-photos-by-dest" / "T")) == before   # nothing mutated
    assert not (ctl / "photos-25-execution-summary.json").exists()       # pre-mutation abort, no summary


@pytest.mark.spec("RUL-geotag_execution_resumable",
                  test="TST-geotag_execution-resume_after_journal_lost_skips_applied_files")
def test_resume_after_journal_lost_skips_applied_files(tmp_path, monkeypatch):
    """Crash-resume (RUL-geotag_execution_resumable): a full execute renames + writes the files; deleting the journal
    (simulating a crash before its flush) and re-executing must detect the already-applied files at
    their targets and SKIP them — not block on the changed/missing source."""
    import os as _os
    ws, ctl = _ready_ws(tmp_path, monkeypatch)
    _mock_tools(monkeypatch, ws)
    assert _execute(monkeypatch, ws) == 0
    assert _summary(ctl)["status"] == "success"
    plan = json.load(open(ctl / "photos-24-executable-plan.json"))
    _os.remove(utils.journal_path(str(ws), plan["plan_id"]))          # journal "lost" to a crash

    assert _execute(monkeypatch, ws) == 0                             # resumes cleanly
    s = _summary(ctl)
    assert s["status"] == "success"
    assert s["resume"]["newly_applied"] == 0                          # nothing re-applied
    assert not s["blockers"] and not s["failures"]                    # not blocked on the renamed files


@pytest.mark.spec("BLD-geotag_execution")
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


@pytest.mark.spec("BLD-geotag_records_by_destination")
def test_summary_grouped_by_destination(tmp_path, monkeypatch):
    """photos-25 carries a per-destination operation breakdown (BLD-execution_summary) that sums to the global
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


@pytest.mark.spec("RUL-handoff_verified_by_content")
def test_noop_reprep_does_not_restale_plan(tmp_path, monkeypatch):
    """A no-op prep re-run refreshes only the handoff's run_metadata (and its byte layout); geotag
    depends on the handoff CONTENT fingerprint, so the plan must NOT restale — but a real content change
    (the inventory) does (RUL-handoff_verified_by_content)."""
    import photos_utils as u
    ws, ctl = _ready_ws(tmp_path, monkeypatch)
    _mock_tools(monkeypatch, ws)
    wf = cal.GeotagWorkflow(str(ws)); wf.preflight(for_execute=True)
    plan = json.load(open(ctl / "photos-24-executable-plan.json"))
    gpx = wf.plan_tracks(plan)
    assert wf.revalidate_plan(plan, gpx) == []                            # fresh
    ho = json.load(open(ctl / "photos-11-handoff.json"))
    ho["run_metadata"] = {"plan_id": "NEW-PLAN", "execution_id": "NEW-EXEC"}   # only run metadata changed
    u.write_json_artifact(str(ctl / "photos-11-handoff.json"), ho)
    assert wf.revalidate_plan(plan, gpx) == []                            # still not stale
    ho["cache_fingerprint"] = "CHANGED-INVENTORY"                         # a real content change
    u.write_json_artifact(str(ctl / "photos-11-handoff.json"), ho)
    assert any("handoff" in s for s in wf.revalidate_plan(plan, gpx))     # now stale


@pytest.mark.spec("RUL-cause_locatable", test="TST-geotag_execution-every_write_traces_back_to_its_decision")
def test_every_write_traces_back_to_its_decision(tmp_path, monkeypatch):
    """From the journal of what ran, each confirmed operation is found in the plan, and the plan names
    by hash the decision records it was made from, which hold the decision for that photo's destination."""
    ws, ctl = _ready_ws(tmp_path, monkeypatch)
    _mock_tools(monkeypatch, ws)
    assert _execute(monkeypatch, ws) == 0
    plan = json.load(open(ctl / "photos-24-executable-plan.json"))
    journal = json.load(open(utils.journal_path(str(ws), plan["plan_id"])))
    ops = {o["operation_id"]: o for d in plan["destinations"].values() for o in d["operations"]}
    confirmed = [oid for oid, st in journal["operations"].items() if st == "confirmed"]
    assert confirmed and set(confirmed) <= set(ops)                       # journal -> plan
    dep = plan["depends_on"]
    for name in ("time_decisions", "gps_decisions"):                      # plan -> the records, by hash
        assert dep[name]["sha256"] == utils.sha256_file(str(ws / dep[name]["artifact_path"]))
    times = json.load(open(ws / dep["time_decisions"]["artifact_path"]))
    for oid in confirmed:                                                 # record -> the decision
        dest = os.path.dirname(ops[oid]["relative_path"])
        tz = times["destinations"][dest]["destination_timezone"]
        assert tz["effective_iana_timezone"]


# --- what an interrupted or troubled run leaves on the record (BLD-geotag_execution) -----------------------

@pytest.mark.spec("RUL-one_photo_failure_contained", "RUL-every_change_journaled", "BLD-geotag_execution",
                  "RUL-failed_photo_named",
                  test="TST-geotag_execution-one_photo_s_failure_is_its_own")
def test_one_photo_s_failure_is_its_own(tmp_path, monkeypatch):
    """Applying one photo raises (the image engine cannot be started, a disk error): that photo fails, by name —
    and every other photo's result is still journalled and summarised, never applied behind a run that has
    already fallen over."""
    ws, ctl = _ready_ws(tmp_path, monkeypatch)
    _mock_tools(monkeypatch, ws)
    real = cal.GeotagWorkflow._apply_file

    def flaky(self, rel, ops, journal, accepted):
        if rel.endswith("a.arw"):
            raise OSError(24, "Too many open files")
        return real(self, rel, ops, journal, accepted)
    monkeypatch.setattr(cal.GeotagWorkflow, "_apply_file", flaky)
    assert _execute(monkeypatch, ws) == 3
    s = _summary(ctl)
    assert s["status"] == "partial" and len(s["blockers"]) == 1
    assert "a.arw: could not be applied (OSError" in s["blockers"][0]
    plan = json.load(open(ctl / "photos-24-executable-plan.json"))
    journal = json.load(open(utils.journal_path(str(ws), plan["plan_id"])))
    b_ops = [o["operation_id"] for o in plan["destinations"]["6-photos-by-dest/T"]["operations"]
             if o["relative_path"].endswith("b.arw")]
    assert b_ops and all(journal["operations"].get(o) == "confirmed" for o in b_ops)     # the other photo: recorded
    monkeypatch.setattr(cal.GeotagWorkflow, "_apply_file", real)
    assert _execute(monkeypatch, ws) == 0 and _summary(ctl)["status"] == "success"       # and the rest follows


@pytest.mark.spec("RUL-applied_unrecorded_is_recorded", "RUL-every_change_journaled",
                  "RUL-geotag_execution_resumable", "BLD-geotag_execution", "RUL-found_applied_never_remade",
                  test="TST-geotag_execution-what_a_killed_run_applied_is_recorded_by_the_next")
def test_what_a_killed_run_applied_is_recorded_by_the_next(tmp_path, monkeypatch):
    """A run killed after applying photos and before recording them: the next run finds each at its planned name
    holding the planned values, redoes nothing, and records its operations — so the journal names every change
    made, and a later log has the pass. It also records each photo as the run left it."""
    ws, ctl = _ready_ws(tmp_path, monkeypatch)
    _mock_tools(monkeypatch, ws)
    assert _execute(monkeypatch, ws) == 0
    plan = json.load(open(ctl / "photos-24-executable-plan.json"))
    jpath = utils.journal_path(str(ws), plan["plan_id"])
    os.remove(jpath)                                                  # killed before the journal reached the disk
    assert _execute(monkeypatch, ws) == 0
    s, journal = _summary(ctl), json.load(open(jpath))
    assert s["status"] == "success" and s["resume"]["newly_applied"] == 0
    all_ops = [o["operation_id"] for d in plan["destinations"].values() for o in d["operations"]]
    assert all(journal["operations"].get(o) == "confirmed" for o in all_ops)
    after = journal["media_after"]
    assert len(after) == 2 and all(os.stat(ws / rel).st_size == v["size"] for rel, v in after.items())
    assert not any(rel.endswith(("a.arw", "b.arw")) for rel in after)                    # under their new names


@pytest.mark.spec("RUL-content_acceptance_is_of_that_content", "RUL-content_changed_write_held",
                  "BLD-execution_summary", "RUL-content_acceptance_under_its_plan",
                  "RUL-content_acceptance_stays_open",
                  test="TST-geotag_execution-an_acceptance_is_of_the_content_shown")
def test_an_acceptance_of_changed_content_is_of_the_content_shown(tmp_path, monkeypatch):
    """A changed picture is accepted as the fingerprint that was reported, under the plan that reported it: it
    stays there to be accepted through a run that finds the photo still held, and is no acceptance of another
    content, nor under another plan."""
    ws, ctl = _ready_ws(tmp_path, monkeypatch)
    plan = json.load(open(ctl / "photos-24-executable-plan.json"))
    wf = cal.GeotagWorkflow(str(ws))
    mism = {"relative_path": "6-photos-by-dest/T/a.arw", "expected_fingerprint": "X", "actual_fingerprint": "CHANGED-1",
            "user_decision": {"accept_fingerprint_change": True}}
    (ctl / "photos-25-execution-summary.json").write_text(json.dumps(
        {"plan_id": plan["plan_id"], "fingerprint_mismatches": [mism]}))
    assert wf._accepted_mismatches(str(ws), plan["plan_id"]) == {"6-photos-by-dest/T/a.arw": "CHANGED-1"}
    assert wf._accepted_mismatches(str(ws), "another-plan") == {}                        # not that plan's to act on
    # the photo holds another content than the one accepted: still held
    (ws / "6-photos-by-dest/T/a.arw").write_bytes(b"edited since")
    monkeypatch.setattr(cal.ContentHasher, "fingerprint_image", staticmethod(lambda p: {"value": "CHANGED-2"}))
    ops = [o for o in plan["destinations"]["6-photos-by-dest/T"]["operations"] if o["relative_path"].endswith("a.arw")]
    r = wf._apply_file("6-photos-by-dest/T/a.arw", ops, {}, wf._accepted_mismatches(str(ws), plan["plan_id"]))
    assert "content fingerprint differs" in r["blocker"]
    # a run that only finds the photo still held keeps the mismatch, and the answer, on the record
    pending = dict(mism, user_decision={"accept_fingerprint_change": False})
    s = wf._build_summary(plan, [dict(r, relative_path="6-photos-by-dest/T/a.arw")], "now", "x", 1, [pending])
    assert s["fingerprint_mismatches"] == [pending] and s["status"] == "partial"
    # a fingerprint that cannot be taken confirms no write
    monkeypatch.setattr(cal.ContentHasher, "fingerprint_image", staticmethod(lambda p: None))
    monkeypatch.setattr(cal.GeotagWorkflow, "_exiftool_write", lambda self, p, t: True)
    (ws / "6-photos-by-dest/T/b.arw").write_bytes(b"img-6-photos-by-dest/T/b.arw")
    ops_b = [o for o in plan["destinations"]["6-photos-by-dest/T"]["operations"] if o["relative_path"].endswith("b.arw")]
    r = wf._apply_file("6-photos-by-dest/T/b.arw", ops_b, {}, {})
    assert not r["applied"] and (r["mismatch"] or r["blocker"])


@pytest.mark.spec("RUL-engine_checked_before_writes", "BLD-geotag_dependencies",
                  test="TST-geotag_execution-another_image_engine_stops_execute_before_any_write")
def test_another_image_engine_stops_execute_before_any_write(tmp_path, monkeypatch):
    """Every write is checked by taking the photo's fingerprint again. With another image engine than the one
    prep took the fingerprints with, each would come out different: execute stops before writing anything."""
    ws, ctl = _ready_ws(tmp_path, monkeypatch)
    plan = json.load(open(ctl / "photos-24-executable-plan.json"))
    wf = cal.GeotagWorkflow(str(ws))
    gpx = wf.plan_tracks(plan)
    monkeypatch.setattr(cal, "get_imagemagick_version", lambda: "IM-7.1.2")
    ho = json.load(open(ctl / "photos-11-handoff.json"))
    ho["depends_on"] = {"cache": {"image_engine_version": "IM-7.1.2"}}
    (ctl / "photos-11-handoff.json").write_text(json.dumps(vouched(ctl.parent, ho)))
    assert not [s for s in wf.revalidate_plan(plan, gpx) if "image engine" in s]
    monkeypatch.setattr(cal, "get_imagemagick_version", lambda: "IM-7.1.3")
    assert [s for s in wf.revalidate_plan(plan, gpx) if "image engine changed" in s]
    # a handoff that records no engine cannot vouch for it: refused, never passed
    monkeypatch.setattr(cal, "get_imagemagick_version", lambda: "IM-7.1.2")
    ho["depends_on"] = {"cache": {}}
    (ctl / "photos-11-handoff.json").write_text(json.dumps(vouched(ctl.parent, ho)))
    assert [s for s in wf.revalidate_plan(plan, gpx) if "records no image engine" in s]
