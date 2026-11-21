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

"""Increment 4 — execute: the BLD-merge_move place-then-remove move, journal, state-derivation resume
(BLD-merge_journal_resume), concurrency (BLD-merge_execute), and photos-31-merge-summary.json. execute consumes
photos-30; the terminal archival steps (merge-log, DB snapshot, re-seal, seal) are Increment 5.

The library-file fingerprint seam is monkeypatched to fingerprint by FILE CONTENT (a "FP=<value>"
blob), so a faithful temp copy fingerprints to its source's value — letting the cross-fs verify path
be exercised without ImageMagick. photos_3_merge / photos_utils come from conftest.py.
"""
import errno
import json
import os
import shutil

import pytest

import photos_3_merge as merge
import photos_utils as utils
from test_merge_preflight import PLACED

MANAGED =["0-sources", "1-strays", "2-missing-metadata", "3-redundant-jpgs",
           "4-videos-by-date", "5-photos-by-date", "6-photos-by-dest"]


def _fp_bytes(fp):
    return b"FP=" + fp.encode()


def _parse_fp(path):
    try:
        data = open(path, "rb").read()
    except OSError:
        return None
    # The blob's first line is its "pixels"; any line after it is "metadata" — the same picture in other bytes.
    return data[3:].split(b"\n")[0].decode() if data.startswith(b"FP=") else None


@pytest.fixture(autouse=True)
def _content_fingerprint(monkeypatch):
    """Fingerprint a photo by its content blob (a faithful copy -> same fingerprint as its source)."""
    def fake(self, abs_path):
        v = _parse_fp(abs_path)
        if v and v != "FAIL":
            return {"status": "valid", "value": v, "strategy": "image-content-hash-v2",
                    "engine_version": "test"}
        return {"status": "failed", "value": None, "error": "unreadable", "engine_version": "test"}
    monkeypatch.setattr(merge.MergeWorkflow, "_fingerprint_library_file", fake)


def _ws(tmp_path, photos, library_files=(), name="ws", folders=None):
    """A merge-ready workspace + blessed library. photos: {fp, dest, final_name, pre_name?}.
    By-dest files hold their FP blob under FINAL names; the handoff carries pre-rename names + a
    rename op when pre_name != final_name; `content_hash`, if given, is the handoff's record of it in place of a
    valid fingerprint. library_files: {fp, dest, name, meta?} ('FAIL' fp -> unreadable; `meta` -> the same
    picture in other bytes). `folders` (role -> name), if given, names the workspace's folders."""
    bd = folders["photos_by_dest"] if folders else "6-photos-by-dest"
    ws = tmp_path / name
    ws.mkdir()
    lib = tmp_path / (name + "-lib")
    lib.mkdir()
    for d in (folders.values() if folders else MANAGED):
        (ws / d).mkdir()
    ctl = ws / ".photos-ingest"
    ctl.mkdir()
    (ctl / "photos-00-workspace-guard").touch()
    utils.write_library_marker(str(lib))

    ho_files, ops = [], []
    for p in photos:
        dest, final = p.get("dest", ""), p["final_name"]
        pre = p.get("pre_name", final)
        ddir = (ws / bd / dest) if dest else (ws / bd)
        ddir.mkdir(parents=True, exist_ok=True)
        (ddir / final).write_bytes(_fp_bytes(p["fp"]))
        rel_pre = os.path.join(bd, dest, pre) if dest else os.path.join(bd, pre)
        ho_files.append({"relative_path": rel_pre, "folder_class": bd,
                         "media_class": "image",
                         "content_hash": p.get("content_hash", json.dumps({"status": "valid", "value": p["fp"]})),
                         "metadata_status": PLACED})
        if pre != final:
            ops.append({"type": "rename_no_clobber", "to": final,
                        "preconditions": {"content_fingerprint": p["fp"]}})
    for lf in library_files:
        dest = lf.get("dest", "")
        ldir = (lib / dest) if dest else lib
        ldir.mkdir(parents=True, exist_ok=True)
        (ldir / lf["name"]).write_bytes(_fp_bytes(lf["fp"]) + (b"\n" + lf["meta"] if lf.get("meta") else b""))

    handoff = {"filename_timestamp_format": utils.CONFIG["filename_timestamp_format"], "files": ho_files, "content_fingerprint": "whole", "run_metadata": {"started_at": "t"},
               "depends_on": {"cache": {"fingerprint_algorithm_version": utils.FINGERPRINT_ALGORITHM_VERSION}}}
    (ctl / "photos-15-prep-log.json").write_text(json.dumps({"photos": {}}))
    handoff.setdefault("depends_on", {})["prep_log"] = {"sha256": utils.sha256_file(str(ctl / "photos-15-prep-log.json"))}
    (ctl / "photos-11-handoff.json").write_text(json.dumps(handoff))
    cfg = {k: v for k, v in utils.CONFIG.items() if k != "jobs"}
    cfg["merge"] = dict(cfg.get("merge") or {})
    cfg["merge"]["library_root"] = str(lib)
    if folders:
        cfg["folders"] = dict(folders)
    (ctl / "photos-00-config.json").write_text(json.dumps(cfg))
    (ctl / "photos-24-executable-plan.json").write_text(json.dumps(
        {"status": "ready", "plan_id": "cal-plan-1", "destinations": {"d": {"operations": ops}},
         "depends_on": {"handoff": {"dependency_type": "handoff_content",
                                    "artifact_name": "photos-11-handoff.json",
                                    "content_fingerprint": utils.handoff_content_fingerprint(handoff)}}}))
    (ctl / "photos-25-execution-summary.json").write_text(json.dumps(
        {"status": "success", "plan_id": "cal-plan-1", "run_metadata": {"execution_id": "cal-exec-1"}}))
    (ctl / "photos-26-complete-log.json").write_text(json.dumps({"photos": {}}))
    (ctl / "photos-26-archive-manifest.json").write_text(json.dumps({"artifact_name": "m", "plan_id": "cal-plan-1"}))
    _bd = ws / bd                          # finalize's record of each by-dest photo as geotag left it
    (ctl / "photos-26-finalized-media.json").write_text(json.dumps({
        "handoff_content_fingerprint": utils.handoff_content_fingerprint(handoff), "media": {
        os.path.relpath(os.path.join(r, n), ws): {"size": os.stat(os.path.join(r, n)).st_size,
                                                  "mtime_ns": os.stat(os.path.join(r, n)).st_mtime_ns}
        for r, _d, fs in os.walk(_bd) for n in fs}}))
    return ws, lib


def _summary(ws):
    return json.loads(open(merge.merge_summary_path(str(ws))).read())


def _src(ws, dest, name):
    return os.path.join(str(ws), "6-photos-by-dest", dest, name)


def _tree(root, times=False):
    """{relpath: bytes} for every file under `root` — a byte-level snapshot for mutation checks; with `times`,
    {relpath: (bytes, size, mtime_ns)}, a file's modification time being part of it.
    Lock files (`*.lock`) are transient lock-acquire artifacts, not data, so they are excluded."""
    out = {}
    for dp, _dn, fns in os.walk(root):
        for fn in fns:
            if fn.endswith(".lock"):
                continue
            ap = os.path.join(dp, fn)
            data = open(ap, "rb").read()
            if times:
                st = os.lstat(ap)
                data = (data, st.st_size, st.st_mtime_ns)
            out[os.path.relpath(ap, root)] = data
    return out


@pytest.mark.spec("RUL-merge_needs_no_tracks", "BLD-track_window", test="TST-merge_execute-merge_needs_no_tracks_folder")
def test_merge_needs_no_tracks_folder(tmp_path, monkeypatch):
    """Merge seals what the workspace keeps: with the configured tracks folder not there, it plans and executes, and
    never builds the tracks."""
    import photos_2_geotag as geo
    ws, lib = _ws(tmp_path, [{"fp": "A", "dest": "Trip", "final_name": "a.jpg"}])
    cfg_p = ws / ".photos-ingest" / "photos-00-config.json"
    cfg = json.loads(cfg_p.read_text()); cfg["gpx_root"] = str(tmp_path / "tracks-not-mounted")
    cfg_p.write_text(json.dumps(cfg))
    monkeypatch.setattr(geo.GPXIndex, "build", lambda *a, **k: pytest.fail("merge read the tracks"))
    assert merge._run_locked_workflow("plan", str(ws)) == 0
    assert merge._run_locked_workflow("execute", str(ws)) == 0
    assert _summary(ws)["status"] == "success"


@pytest.mark.spec("RUL-target_free_ignores_case", "RUL-target_free_at_execute",
                  test="TST-merge_execute-a_place_taken_in_another_case_since_the_plan_is_not_placed_beside")
def test_a_place_taken_in_another_case_since_the_plan_is_not_placed_beside(tmp_path):
    """A library file of the photo's planned name in another case appears after planning: on any filesystem, merge
    does not place the photo beside it — the photo is blocked, left in the workspace, the library file untouched."""
    ws, lib = _ws(tmp_path, [{"fp": "A", "dest": "Trip", "final_name": "a.jpg"}])
    assert merge._run_locked_workflow("plan", str(ws)) == 0
    (lib / "Trip").mkdir(exist_ok=True)
    (lib / "Trip" / "A.JPG").write_bytes(_fp_bytes("OTHER"))
    assert merge._run_locked_workflow("execute", str(ws)) == 3
    assert sorted(os.listdir(lib / "Trip")) == ["A.JPG"]
    assert os.path.exists(_src(ws, "Trip", "a.jpg"))
    assert _summary(ws)["totals"]["blocked"] == 1


# --- the four dispositions ---------------------------------------------------

@pytest.mark.spec("RUL-library_creates_only_placements", "RUL-merge_moves", "BLD-merge_records", test="TST-merge_execute-execute_placed_new_moves_into_library")
def test_execute_placed_new_moves_into_library(tmp_path):
    ws, lib = _ws(tmp_path, [{"fp": "A", "dest": "Trip", "final_name": "a.jpg"}])
    assert merge._run_locked_workflow("plan", str(ws)) == 0
    assert merge._run_locked_workflow("execute", str(ws)) == 0
    placed = os.path.join(str(lib), "Trip", "a.jpg")
    assert open(placed, "rb").read() == _fp_bytes("A")        # in the library
    assert not os.path.exists(_src(ws, "Trip", "a.jpg"))      # source removed last
    s = _summary(ws)
    assert s["status"] == "success"
    assert s["totals"] == {"placed_new": 1, "already_present": 0, "renamed_for_library": 0,
                           "removed_from_by_dest": 1, "blocked": 0}
    assert s["resume"] == {"newly_moved": 1, "already_done_skipped": 0}


@pytest.mark.spec("RUL-collision_same_content", "RUL-collision_same_content_copy_removed",
                  test="TST-merge_execute-execute_already_present_removes_source_no_write")
def test_execute_already_present_removes_source_no_write(tmp_path):
    ws, lib = _ws(tmp_path, [{"fp": "A", "dest": "Trip", "final_name": "a.jpg"}],
                  library_files=[{"fp": "A", "dest": "Trip", "name": "a.jpg"}])
    assert merge._run_locked_workflow("plan", str(ws)) == 0
    assert merge._run_locked_workflow("execute", str(ws)) == 0
    assert open(os.path.join(str(lib), "Trip", "a.jpg"), "rb").read() == _fp_bytes("A")  # untouched
    assert not os.path.exists(_src(ws, "Trip", "a.jpg"))     # source still removed
    assert _summary(ws)["totals"]["already_present"] == 1


@pytest.mark.spec("RUL-merge_records_landing", test="TST-merge_execute-the_summary_says_where_each_photo_landed_or_why_it_did_not")
def test_the_summary_says_where_each_photo_landed_or_why_it_did_not(tmp_path):
    """Each entry of the summary: where the photo landed, renamed or already present, removed from the
    workspace — or, blocked, no place in the library and the reason."""
    ws, lib = _ws(tmp_path, [{"fp": "A", "dest": "Trip", "final_name": "a.jpg"},
                             {"fp": "B", "dest": "Trip", "final_name": "b.jpg"},
                             {"fp": "C", "dest": "Trip", "final_name": "c.jpg"},
                             {"fp": "D", "dest": "Trip", "final_name": "d.jpg"}],
                  library_files=[{"fp": "B", "dest": "Trip", "name": "b.jpg"},
                                 {"fp": "X", "dest": "Trip", "name": "c.jpg"},
                                 {"fp": "FAIL", "dest": "Trip", "name": "d.jpg"}])
    assert merge._run_locked_workflow("plan", str(ws)) == 2   # a blocker: ends as a refusal (RUL-blocked_plan_ends_refused)
    assert merge._run_locked_workflow("execute", str(ws)) == 3
    files = {os.path.basename(f["by_dest_path"]): f for f in _summary(ws)["destinations"]["Trip"]["files"]}
    t = os.path.join(str(lib), "Trip")
    assert files["a.jpg"] == {"by_dest_path": "6-photos-by-dest/Trip/a.jpg", "library_path": os.path.join(t, "a.jpg"),
                              "renamed_for_library": False, "already_present": False,
                              "removed_from_by_dest": True, "blocked_reason": None}
    assert files["b.jpg"]["already_present"] and files["b.jpg"]["library_path"] == os.path.join(t, "b.jpg")
    assert files["c.jpg"]["renamed_for_library"] and files["c.jpg"]["library_path"] == os.path.join(t, "c-001.jpg")
    d = files["d.jpg"]
    assert d["library_path"] is None and not d["removed_from_by_dest"]
    assert "could not be fingerprinted" in d["blocked_reason"]


@pytest.mark.spec("RUL-merge_run_reported", test="TST-merge_execute-the_run_reports_what_it_placed_and_what_stayed")
def test_the_run_reports_what_it_placed_and_what_stayed(tmp_path, capsys):
    """A partial run tells what it placed, what was already there, and each photo that stayed with its
    reason, and that nothing is sealed; the run that finishes tells that the workspace is sealed."""
    ws, lib = _ws(tmp_path, [{"fp": "A", "dest": "Trip", "final_name": "a.jpg"},
                             {"fp": "B", "dest": "Trip", "final_name": "b.jpg"},
                             {"fp": "C", "dest": "Trip", "final_name": "c.jpg"}],
                  library_files=[{"fp": "B", "dest": "Trip", "name": "b.jpg"},
                                 {"fp": "FAIL", "dest": "Trip", "name": "c.jpg"}])
    assert merge._run_locked_workflow("plan", str(ws)) == 2   # a blocker: ends as a refusal (RUL-blocked_plan_ends_refused)
    capsys.readouterr()
    assert merge._run_locked_workflow("execute", str(ws)) == 3
    out = capsys.readouterr()
    text = out.out + out.err
    assert "1 placed" in text and "1 already-present" in text and "1 blocked" in text
    assert "c.jpg" in text and "could not be fingerprinted" in text and "left in by-dest" in text
    assert "sealed the workspace" not in text
    with open(os.path.join(str(lib), "Trip", "c.jpg"), "wb") as f:
        f.write(_fp_bytes("OLD"))
    assert merge._run_locked_workflow("plan", str(ws)) == 0
    capsys.readouterr()
    assert merge._run_locked_workflow("execute", str(ws)) == 0
    assert "sealed the workspace" in capsys.readouterr().out


@pytest.mark.spec("RUL-collision_by_content", "RUL-library_file_rechecked_before_removal",
                  "RUL-library_fingerprint_kept", "RUL-unplaced_photo_stays",
                  test="TST-merge_execute-the_library_file_is_read_again_before_a_photo_already_there_is_removed")
def test_the_library_file_is_read_again_before_a_photo_already_there_is_removed(tmp_path):
    """The cache trusts size and modification time; removing the workspace's copy cannot be undone. A
    library file changed since the plan without either moving is still caught: the photo stays."""
    ws, lib = _ws(tmp_path, [{"fp": "A", "dest": "Trip", "final_name": "a.jpg"}],
                  library_files=[{"fp": "A", "dest": "Trip", "name": "a.jpg"}])
    assert merge._run_locked_workflow("plan", str(ws)) == 0             # fingerprint cached at plan
    target = os.path.join(str(lib), "Trip", "a.jpg")
    st = os.stat(target)
    with open(target, "wb") as f:
        f.write(_fp_bytes("B"))                                         # same size, other content
    os.utime(target, ns=(st.st_atime_ns, st.st_mtime_ns))               # same modification time
    assert merge._run_locked_workflow("execute", str(ws)) != 0
    assert os.path.exists(_src(ws, "Trip", "a.jpg"))                    # the photo stays in the workspace
    assert open(target, "rb").read() == _fp_bytes("B")                  # the library file untouched


@pytest.mark.spec("RUL-collision_different_content", "RUL-library_never_altered", test="TST-merge_execute-execute_renamed_incoming_places_under_safe_name")
def test_execute_renamed_incoming_places_under_safe_name(tmp_path):
    ws, lib = _ws(tmp_path, [{"fp": "NEW", "dest": "Trip", "final_name": "ts.jpg"}],
                  library_files=[{"fp": "OLD", "dest": "Trip", "name": "ts.jpg"}])
    assert merge._run_locked_workflow("plan", str(ws)) == 0
    assert merge._run_locked_workflow("execute", str(ws)) == 0
    assert open(os.path.join(str(lib), "Trip", "ts.jpg"), "rb").read() == _fp_bytes("OLD")    # untouched
    assert open(os.path.join(str(lib), "Trip", "ts-001.jpg"), "rb").read() == _fp_bytes("NEW")  # incoming
    assert not os.path.exists(_src(ws, "Trip", "ts.jpg"))
    assert _summary(ws)["totals"]["renamed_for_library"] == 1


def test_execute_unfingerprintable_library_blocks_and_keeps_source(tmp_path):
    ws, lib = _ws(tmp_path, [{"fp": "A", "dest": "Trip", "final_name": "a.jpg"}],
                  library_files=[{"fp": "FAIL", "dest": "Trip", "name": "a.jpg"}])
    assert merge._run_locked_workflow("plan", str(ws)) == 2   # a blocker: ends as a refusal (RUL-blocked_plan_ends_refused)
    assert merge._run_locked_workflow("execute", str(ws)) == 3          # blocked -> rc 3
    assert os.path.exists(_src(ws, "Trip", "a.jpg"))                    # left in by-dest
    s = _summary(ws)
    assert s["status"] == "failed"                                      # the only file blocked -> nothing placed
    assert s["totals"]["blocked"] == 1 and s["failures"]


@pytest.mark.spec("RUL-target_free_at_execute", "BLD-merge_move", "RUL-library_never_altered",
                  "RUL-unplaced_photo_stays",
                  test="TST-merge_execute-execute_occupied_by_different_content_at_execute_blocks_no_clobber")
def test_execute_occupied_by_different_content_at_execute_blocks_no_clobber(tmp_path):
    """TOCTOU clobber guard: target FREE at plan (placed_new), then a *different-content* file appears
    at the planned target before execute. The execute-time recheck must refuse — rc 3, source left in
    by-dest, the irreplaceable library byte UNCHANGED. (The identical-content sibling is covered above
    by ...renamed/already-present; this dangerous different-content path was previously unexercised.)"""
    ws, lib = _ws(tmp_path, [{"fp": "A", "dest": "Trip", "final_name": "a.jpg"}])
    assert merge._run_locked_workflow("plan", str(ws)) == 0             # planned as placed_new (lib empty)
    target = lib / "Trip" / "a.jpg"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(_fp_bytes("X"))                                  # different content appears post-plan
    assert merge._run_locked_workflow("execute", str(ws)) == 3          # no-clobber refuses -> rc 3
    assert open(target, "rb").read() == _fp_bytes("X")                  # library byte UNCHANGED (no clobber)
    assert open(_src(ws, "Trip", "a.jpg"), "rb").read() == _fp_bytes("A")  # source preserved in by-dest
    s = _summary(ws)
    assert s["status"] == "failed"
    assert s["totals"]["blocked"] == 1 and s["totals"]["placed_new"] == 0
    assert s["failures"]


@pytest.mark.spec("RUL-development_after_merge",
                  test="TST-merge_execute-merge_never_performs_jpg_tif_development_breakout")
def test_merge_never_performs_jpg_tif_development_breakout(tmp_path):
    """RUL-development_after_merge (anti): the jpg/tif development breakout is a later library-side processing phase,
    NOT merge's job. test_dev_subfolder_blocks proves a PRE-EXISTING dev subfolder blocks the run;
    this proves merge never CREATES one itself. A plain by-dest photo is placed FLAT under its
    destination (Trip/a.jpg) — merge spawns no `jpg/` or `tif/` development subfolder anywhere in the
    library, and does no such content reorganization."""
    ws, lib = _ws(tmp_path, [{"fp": "A", "dest": "Trip", "final_name": "a.jpg"}])
    assert merge._run_locked_workflow("plan", str(ws)) == 0
    assert merge._run_locked_workflow("execute", str(ws)) == 0
    # The photo landed FLAT at its destination, not broken out into a development subfolder.
    assert open(os.path.join(str(lib), "Trip", "a.jpg"), "rb").read() == _fp_bytes("A")
    assert not os.path.exists(os.path.join(str(lib), "Trip", "jpg", "a.jpg"))
    assert not os.path.exists(os.path.join(str(lib), "Trip", "tif"))
    # No `jpg`/`tif` development subfolder was created ANYWHERE in the library tree.
    for dp, dns, _fns in os.walk(str(lib)):
        assert "jpg" not in dns and "tif" not in dns, (dp, dns)


@pytest.mark.spec("RUL-library_mirrors_destinations",
                  test="TST-merge_execute-merge_never_mutates_by_dest_name_or_content_only_library_renames")
def test_merge_never_mutates_by_dest_name_or_content_only_library_renames(tmp_path):
    """RUL-library_mirrors_destinations (anti): merge never mutates by-dest content or a file's name; ONLY a library
    collision forces an incoming rename — and that rename happens at the LIBRARY target, never in by-dest. The
    incoming `ts.jpg` collides with a different-content library `ts.jpg`, so it is placed as
    `ts-001.jpg` IN THE LIBRARY while its by-dest source is removed under its ORIGINAL name (never
    renamed in place), with content carried over byte-for-byte."""
    ws, lib = _ws(tmp_path, [{"fp": "NEW", "dest": "Trip", "final_name": "ts.jpg"}],
                  library_files=[{"fp": "OLD", "dest": "Trip", "name": "ts.jpg"}])
    bd = ws / "6-photos-by-dest" / "Trip"
    assert _tree(str(bd)) == {"ts.jpg": _fp_bytes("NEW")}            # by-dest source, original name
    assert merge._run_locked_workflow("plan", str(ws)) == 0
    assert merge._run_locked_workflow("execute", str(ws)) == 0
    # The library: OLD untouched at ts.jpg; the incoming placed under a SAFE name with its exact bytes.
    assert open(os.path.join(str(lib), "Trip", "ts.jpg"), "rb").read() == _fp_bytes("OLD")
    assert open(os.path.join(str(lib), "Trip", "ts-001.jpg"), "rb").read() == _fp_bytes("NEW")
    # by-dest: source removed under its ORIGINAL name; never renamed in place (no ts-001 leftover), empty.
    assert _tree(str(bd)) == {}
    assert not (bd / "ts-001.jpg").exists()
    # The merge journal confirms the source by its ORIGINAL by-dest path — its name was never mutated
    # in by-dest; the only rename was choosing the library target name.
    plan_id = json.loads(open(merge.merge_plan_path(str(ws))).read())["plan_id"]
    journal = (json.load(open(merge.journal_path(str(ws), plan_id))) or {}).get("operations", {})
    assert journal == {"6-photos-by-dest/Trip/ts.jpg": "confirmed"}


@pytest.mark.spec("RUL-library_not_scanned", "RUL-library_file_read_once",
                  test="TST-merge_execute-merge_only_inspects_specific_collision_target_never_rescans_library")
def test_merge_only_inspects_specific_collision_target_never_rescans_library(tmp_path, monkeypatch):
    """RUL-library_not_scanned (anti): merge never rescans the library wholesale — it fingerprints only each incoming
    file's specific collision target, never a library-wide index. Seed the library with the collision
    target PLUS unrelated files (same dir and another dir); probe the fingerprint seam and assert the
    unrelated files are NEVER fingerprinted, only the exact target the incoming would land on."""
    ws, lib = _ws(tmp_path, [{"fp": "A", "dest": "Trip", "final_name": "a.jpg"}],
                  library_files=[{"fp": "A", "dest": "Trip", "name": "a.jpg"},          # the collision target
                                 {"fp": "X", "dest": "Trip", "name": "unrelated.jpg"},  # unrelated, same dir
                                 {"fp": "Y", "dest": "Spain", "name": "q.jpg"}])        # unrelated, other dir
    seen = []
    orig = merge.MergeWorkflow._fingerprint_library_file        # the fake installed by the autouse fixture

    def spy(self, abs_path):
        seen.append(abs_path)
        return orig(self, abs_path)

    monkeypatch.setattr(merge.MergeWorkflow, "_fingerprint_library_file", spy)
    assert merge._run_locked_workflow("plan", str(ws)) == 0
    assert merge._run_locked_workflow("execute", str(ws)) == 0      # identical content -> already_present
    assert seen, "the specific collision target must have been fingerprinted"
    # only the incoming's own target (Trip/a.jpg) is ever inspected — no wholesale rescan.
    assert all(os.path.basename(p) == "a.jpg" and os.path.join("Trip", "a.jpg") in p for p in seen), seen
    assert not any("unrelated.jpg" in p for p in seen)              # unrelated same-dir file untouched
    assert not any(os.path.join("Spain", "q.jpg") in p for p in seen)  # other-dir file untouched


def _zfs(monkeypatch, ws, *, required=False, datasets=("ws", "lib"), fail=()):
    """Turn snapshots on in the workspace's configuration — before `plan`, which the configuration is a
    dependency of — with the workspace on dataset `datasets[0]` and the library on `datasets[1]` (None:
    not snapshottable), and fake `zfs snapshot`, failing for the datasets named in `fail`. Returns the
    list of datasets snapshotted, in order."""
    taken = []
    cfg_path = utils.config_path(str(ws))
    cfg = json.load(open(cfg_path))
    cfg["zfs"] = dict(cfg.get("zfs") or {}, enabled=True, snapshots_required=required)
    json.dump(cfg, open(cfg_path, "w"))

    def dataset(ws, *, target_path=None, dataset_key="workspace"):
        return datasets[0] if dataset_key == "workspace" else datasets[1]

    def take(ws, plan_id, label, *, target_path=None, dataset_key="workspace"):
        ds = dataset(ws, target_path=target_path, dataset_key=dataset_key)
        ok = ds not in fail
        if ok:
            taken.append(ds)
        return {"required": required, "ok": ok, "snapshot_name": f"{ds}@{label}-{plan_id}",
                "command": "zfs snapshot", "exit_code": 0 if ok else 1, "stdout": "",
                "stderr": "" if ok else "pool busy"}
    monkeypatch.setattr(merge, "zfs_dataset", dataset)
    monkeypatch.setattr(merge, "take_zfs_snapshot", take)
    return taken


@pytest.mark.spec("RUL-required_snapshot_or_nothing", "RUL-merge_outcome_recorded", test="TST-merge_execute-execute_required_snapshot_failure_aborts_before_any_placement")
def test_execute_required_snapshot_failure_aborts_before_any_placement(tmp_path, monkeypatch):
    """snapshots_required + the library pre-mutation snapshot fails -> abort BEFORE any move:
    status rejected (rc 2), nothing placed, source untouched in by-dest, library empty, workspace
    NOT sealed. The required-snapshot guard is the RUL-required_snapshot_or_nothing promise."""
    ws, lib = _ws(tmp_path, [{"fp": "A", "dest": "Trip", "final_name": "a.jpg"}])
    _zfs(monkeypatch, ws, required=True, fail={"lib"})
    assert merge._run_locked_workflow("plan", str(ws)) == 0
    assert merge._run_locked_workflow("execute", str(ws)) == 2          # rejected -> rc 2
    assert open(_src(ws, "Trip", "a.jpg"), "rb").read() == _fp_bytes("A")  # source untouched
    assert not os.path.exists(os.path.join(str(lib), "Trip", "a.jpg"))  # nothing placed
    assert not utils.is_sealed(str(ws))                                 # no seal
    s = _summary(ws)
    assert s["status"] == "rejected"
    assert s["totals"]["placed_new"] == 0 and s["totals"]["blocked"] == 0


def test_a_snapshot_refusal_is_not_reported_as_a_stale_plan(tmp_path, monkeypatch, capsys):
    """A required snapshot that cannot be taken is told as such, with the fix that clears it — never as
    a stale plan, which a re-plan would not cure."""
    ws, lib = _ws(tmp_path, [{"fp": "A", "dest": "Trip", "final_name": "a.jpg"}])
    _zfs(monkeypatch, ws, required=True, fail={"lib"})
    assert merge._run_locked_workflow("plan", str(ws)) == 0
    capsys.readouterr()
    assert merge._run_locked_workflow("execute", str(ws)) == 2
    out = capsys.readouterr()
    text = out.out + out.err
    assert "stale" not in text and "snapshot" in text and "pool busy" in text
    assert "merge execute" in text


@pytest.mark.spec("RUL-merge_rechecks_gates", "RUL-merge_refuses_changed_since_finalize",
                  test="TST-merge_execute-plan_blocks_when_bydest_photo_absent_from_finalized_set")
def test_plan_blocks_when_bydest_photo_absent_from_finalized_set(tmp_path):
    """Prep-consistency (RUL-merge_refuses_changed_since_finalize): a photo physically under 6-photos-by-dest but NOT in
    the finalized record (handoff predates the latest move into by-dest) -> 're-run prep' blocker at plan,
    rc 2, NO plan artifact written, nothing placed. Guards against merging an unrecorded file."""
    ws, lib = _ws(tmp_path, [{"fp": "A", "dest": "Trip", "final_name": "a.jpg"}])
    stray = ws / "6-photos-by-dest" / "Trip" / "stray.jpg"               # on disk, absent from handoff
    stray.write_bytes(_fp_bytes("Z"))
    assert merge._run_locked_workflow("plan", str(ws)) == 2              # preflight blocker -> rc 2
    assert not os.path.exists(merge.merge_plan_path(str(ws)))           # no plan written
    assert stray.exists()                                               # left untouched
    assert not (lib / "Trip").exists()                                 # nothing placed


@pytest.mark.spec("RUL-config_writers", test="TST-merge_execute-config_is_byte_identical_across_plan_dryrun_execute")
def test_config_is_byte_identical_across_plan_dryrun_execute(tmp_path):
    """Merge never writes the workspace config (photos-00-config.json is hand-edited, authoritative).
    Snapshot its bytes, run the full plan -> dry-run -> execute cycle, assert byte-for-byte identical."""
    ws, lib = _ws(tmp_path, [{"fp": "A", "dest": "Trip", "final_name": "a.jpg"}])
    cfg_p = os.path.join(str(ws), ".photos-ingest", "photos-00-config.json")
    before = open(cfg_p, "rb").read()
    assert merge._run_locked_workflow("plan", str(ws)) == 0
    assert merge._run_locked_workflow("dry-run", str(ws)) == 0
    assert merge._run_locked_workflow("execute", str(ws)) == 0
    assert open(cfg_p, "rb").read() == before                           # config byte-identical


# --- resume (state-derivation, BLD-merge_journal_resume) ---------------------

@pytest.mark.spec("RUL-seal_on_success_only", "RUL-merge_moves", "RUL-resume_rechecks_library",
                  "RUL-merge_resumable",
                  test="TST-merge_execute-execute_resume_after_crash_before_seal")
def test_execute_resume_after_crash_before_seal(tmp_path, monkeypatch):
    # Full success seals the workspace, so the genuine resume case is a crash AFTER the moves/journal
    # but BEFORE the seal: the re-run must recognize the already-moved files (state-derivation) and
    # complete the terminal bookkeeping + seal.
    ws, lib = _ws(tmp_path, [{"fp": "A", "dest": "Trip", "final_name": "a.jpg"}])
    assert merge._run_locked_workflow("plan", str(ws)) == 0
    real = merge.MergeWorkflow._finalize_terminal
    calls = []

    def maybe_finalize(self, *a, **k):
        calls.append(1)
        return None if len(calls) == 1 else real(self, *a, **k)   # skip seal on the first run only
    monkeypatch.setattr(merge.MergeWorkflow, "_finalize_terminal", maybe_finalize)

    assert merge._run_locked_workflow("execute", str(ws)) == 0     # moved, but crashed before seal
    assert os.path.exists(os.path.join(str(lib), "Trip", "a.jpg"))
    assert not os.path.exists(_src(ws, "Trip", "a.jpg"))
    assert not utils.is_sealed(str(ws))                            # not sealed yet -> re-runnable

    assert merge._run_locked_workflow("execute", str(ws)) == 0     # resume -> success -> seal
    assert utils.is_sealed(str(ws))
    s = _summary(ws)
    assert s["resume"]["already_done_skipped"] == 1                # the moved file recognized as done
    assert open(os.path.join(str(lib), "Trip", "a.jpg"), "rb").read() == _fp_bytes("A")


@pytest.mark.spec("BLD-merge_move", "RUL-merge_resumable",
                  test="TST-merge_execute-execute_resume_finishes_crash_window")
def test_execute_resume_finishes_crash_window(tmp_path):
    # Simulate a crash AFTER the library copy is in place but BEFORE the source was removed: both
    # present + fingerprints match -> resume finishes the source removal (no duplicate kept).
    ws, lib = _ws(tmp_path, [{"fp": "A", "dest": "Trip", "final_name": "a.jpg"}])
    assert merge._run_locked_workflow("plan", str(ws)) == 0
    (lib / "Trip").mkdir(parents=True, exist_ok=True)
    (lib / "Trip" / "a.jpg").write_bytes(_fp_bytes("A"))         # library copy already present
    assert os.path.exists(_src(ws, "Trip", "a.jpg"))            # source still there
    assert merge._run_locked_workflow("execute", str(ws)) == 0
    assert not os.path.exists(_src(ws, "Trip", "a.jpg"))        # removal completed
    assert open(os.path.join(str(lib), "Trip", "a.jpg"), "rb").read() == _fp_bytes("A")
    t = _summary(ws)["totals"]                                  # a place found holding it: already present
    assert (t["already_present"], t["placed_new"]) == (1, 0), t


@pytest.mark.spec("BLD-merge_move",
                  test="TST-merge_execute-a_place_taken_by_the_planned_content_during_the_move_is_already_present")
def test_a_place_taken_by_the_planned_content_during_the_move_is_already_present(tmp_path, monkeypatch):
    """The planned content appearing at the place while the photo moves makes it already present — as when
    it is found there just before the move."""
    ws, lib = _ws(tmp_path, [{"fp": "A", "dest": "Trip", "final_name": "a.jpg"}])
    assert merge._run_locked_workflow("plan", str(ws)) == 0

    def raced(src, dst, **k):
        with open(dst, "wb") as f:
            f.write(_fp_bytes("A"))                             # someone else placed the same photo
        raise FileExistsError(dst)
    monkeypatch.setattr(merge, "_move_no_clobber", raced)
    assert merge._run_locked_workflow("execute", str(ws)) == 0
    assert not os.path.exists(_src(ws, "Trip", "a.jpg"))
    t = _summary(ws)["totals"]
    assert (t["already_present"], t["placed_new"]) == (1, 0), t


@pytest.mark.spec("RUL-merge_refuses_changed_since_finalize",
                  test="TST-merge_execute-a_photo_touched_after_the_plan_is_refused_at_execute")
def test_a_photo_touched_after_the_plan_is_refused_at_execute(tmp_path, monkeypatch):
    """A photo whose modification time changes once execute's preconditions have passed — its pixels, and
    so its fingerprint, the same, as after a metadata write — is refused and named, left where it is; the
    others are merged."""
    ws, lib = _ws(tmp_path, [{"fp": "A", "dest": "Trip", "final_name": "a.jpg"},
                             {"fp": "B", "dest": "Trip", "final_name": "b.jpg"}])
    assert merge._run_locked_workflow("plan", str(ws)) == 0
    src = _src(ws, "Trip", "a.jpg")
    real_sweep = merge.MergeWorkflow._sweep_orphan_temps

    def sweep_then_touch(self, *a, **k):                         # after the preconditions, before the moves
        st = os.stat(src)
        os.utime(src, ns=(st.st_atime_ns, st.st_mtime_ns + 10**9))   # touched; same bytes
        return real_sweep(self, *a, **k)
    monkeypatch.setattr(merge.MergeWorkflow, "_sweep_orphan_temps", sweep_then_touch)
    assert merge._run_locked_workflow("execute", str(ws)) == 3
    assert open(src, "rb").read() == _fp_bytes("A")              # left in by-dest
    assert not os.path.exists(os.path.join(str(lib), "Trip", "a.jpg"))
    assert os.path.exists(os.path.join(str(lib), "Trip", "b.jpg"))
    s = _summary(ws)
    assert s["totals"]["blocked"] == 1 and s["totals"]["placed_new"] == 1
    assert any("Trip/a.jpg" in f for f in s["failures"]), s["failures"]


@pytest.mark.spec("RUL-merge_refuses_changed_since_finalize",
                  test="TST-merge_execute-a_photo_touched_after_the_plan_is_not_removed_as_already_present")
def test_a_photo_touched_after_the_plan_is_not_removed_as_already_present(tmp_path, monkeypatch):
    """The library already holds the photo's pixels, so merge would remove the workspace's copy — but that copy
    was written to since the plan (same pixels, as after a metadata write): it is refused and left where it is,
    the edit not lost."""
    ws, lib = _ws(tmp_path, [{"fp": "A", "dest": "Trip", "final_name": "a.jpg"}],
                  library_files=[{"fp": "A", "dest": "Trip", "name": "a.jpg"}])
    assert merge._run_locked_workflow("plan", str(ws)) == 0
    src = _src(ws, "Trip", "a.jpg")
    real_sweep = merge.MergeWorkflow._sweep_orphan_temps

    def sweep_then_touch(self, *a, **k):                         # after the preconditions, before the removals
        st = os.stat(src)
        os.utime(src, ns=(st.st_atime_ns, st.st_mtime_ns + 10**9))
        return real_sweep(self, *a, **k)
    monkeypatch.setattr(merge.MergeWorkflow, "_sweep_orphan_temps", sweep_then_touch)
    assert merge._run_locked_workflow("execute", str(ws)) == 3
    assert os.path.exists(src)                                   # still in by-dest
    s = _summary(ws)
    assert s["totals"]["blocked"] == 1 and any("Trip/a.jpg" in f for f in s["failures"]), s


@pytest.mark.spec("RUL-merge_outcome_recorded", "BLD-merge_failed_placement", "RUL-failure_recorded",
                  test="TST-merge_execute-an_error_placing_one_photo_blocks_it_alone")
def test_an_error_placing_one_photo_blocks_it_alone(tmp_path, monkeypatch):
    """An error anywhere in one photo's placement — here its removal from by-dest after the library's copy
    is checked — blocks that photo alone: the others are placed and the run records how it ended."""
    ws, lib = _ws(tmp_path, [{"fp": "A", "dest": "Trip", "final_name": "a.jpg"},
                             {"fp": "B", "dest": "Trip", "final_name": "b.jpg"}],
                  library_files=[{"fp": "A", "dest": "Trip", "name": "a.jpg"}])   # a.jpg already present
    assert merge._run_locked_workflow("plan", str(ws)) == 0
    real_unlink, src_a = os.unlink, _src(ws, "Trip", "a.jpg")

    def unlink(path, *a, **k):
        if os.fspath(path) == src_a:
            raise PermissionError(errno.EACCES, "Permission denied", path)
        return real_unlink(path, *a, **k)
    monkeypatch.setattr(merge.os, "unlink", unlink)
    assert merge._run_locked_workflow("execute", str(ws)) == 3
    monkeypatch.undo()
    assert os.path.exists(src_a)                                  # left in by-dest
    assert os.path.exists(os.path.join(str(lib), "Trip", "b.jpg"))
    s = _summary(ws)
    assert s["status"] == "partial"
    assert s["totals"]["blocked"] == 1 and s["totals"]["placed_new"] == 1
    assert any("Trip/a.jpg" in f for f in s["failures"]), s["failures"]


@pytest.mark.spec("RUL-operations_atomic", test="TST-merge_execute-a_placement_on_one_filesystem_is_one_rename")
def test_a_placement_on_one_filesystem_is_one_rename(tmp_path, monkeypatch):
    """Where the library lies on the workspace's filesystem, each placement is one rename — never a hard link and
    an unlink, or a copy and a removal, of the photo."""
    probe = tmp_path / "probe"; probe.write_bytes(b"p")
    fn = utils._get_renameat2()
    if not fn or fn(utils._AT_FDCWD, os.fsencode(str(probe)), utils._AT_FDCWD,
                    os.fsencode(str(tmp_path / "probed")), utils._RENAME_NOREPLACE) != 0:
        pytest.skip("this filesystem has no rename that refuses a taken name")
    ws, lib = _ws(tmp_path, [{"fp": "A", "dest": "Trip", "final_name": "a.jpg"},
                             {"fp": "B", "dest": "Trip", "final_name": "b.jpg"}],
                  library_files=[{"fp": "C", "dest": "Trip", "name": "a.jpg"}])
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
    for command in ("plan", "execute"):
        utils.CONFIG.clear(); utils.CONFIG.update(json.loads(json.dumps(utils.DEFAULT_CONFIG)))   # each a run of its own
        assert merge._run_locked_workflow(command, str(ws)) == 0, command
    assert sorted(os.listdir(lib / "Trip")) == ["a-001.jpg", "a.jpg", "b.jpg"]
    assert _summary(ws)["status"] == "success"
    assert [s for s in split if ".photos-ingest" not in s[1]] == [], split


@pytest.mark.spec("RUL-one_configuration", test="TST-merge_execute-merge_reads_its_settings_from_the_workspace_alone")
def test_merge_reads_its_settings_from_the_workspace_alone(tmp_path, tmp_path_factory, monkeypatch):
    """Merge takes its settings from the workspace's configuration alone: another configuration in every other
    place — the seed defaults, beside the executable, above the workspace, in the home folder, an environment
    variable per setting — naming another library, also set up as one, never draws a photo into it."""
    from _elsewhere import settings_elsewhere
    other_lib = tmp_path / "other-lib"; other_lib.mkdir()
    utils.write_library_marker(str(other_lib))
    other = json.loads(json.dumps(utils.DEFAULT_CONFIG))
    other["merge"]["library_root"] = str(other_lib)
    other["filename_timestamp_format"] = "%Y%m%d_ELSEWHERE_%H%M%S"
    settings_elsewhere(monkeypatch, tmp_path, other)
    ws, lib = _ws(tmp_path, [{"fp": "A", "dest": "Trip", "final_name": "a.jpg"}])
    # The folder above holds a control directory, so it is a workspace too: the library lies outside it
    # (RUL-library_outside_every_workspace).
    lib = tmp_path_factory.mktemp("lib")
    utils.write_library_marker(str(lib))
    _point_library_at(ws, lib)
    marker = sorted(os.listdir(other_lib))
    for command in ("plan", "dry-run", "execute"):
        utils.CONFIG.clear(); utils.CONFIG.update(json.loads(json.dumps(utils.DEFAULT_CONFIG)))   # a run of its own
        assert merge._run_locked_workflow(command, str(ws)) == 0, command
    assert open(os.path.join(str(lib), "Trip", "a.jpg"), "rb").read() == _fp_bytes("A")
    assert sorted(os.listdir(other_lib)) == marker


# --- cross-filesystem path + torn-copy verify (BLD-cross_fs_temp) -------------

def _force_cross_fs(monkeypatch):
    """Make the by-dest source move look cross-filesystem so _move_no_clobber takes the copy-verify
    fallback; the tmp->target rename within the library stays same-fs (real)."""
    real = utils._rename_no_clobber_same_fs

    def patched(src, dest):
        if "6-photos-by-dest" in src:
            raise OSError(errno.EXDEV, "simulated cross-fs", src)
        return real(src, dest)
    monkeypatch.setattr(utils, "_rename_no_clobber_same_fs", patched)


@pytest.mark.spec("RUL-cross_fs_all_or_nothing", "BLD-merge_move", test="TST-merge_execute-execute_cross_fs_move_verifies_and_completes")
def test_execute_cross_fs_move_verifies_and_completes(tmp_path, monkeypatch):
    _force_cross_fs(monkeypatch)
    ws, lib = _ws(tmp_path, [{"fp": "A", "dest": "Trip", "final_name": "a.jpg"}])
    assert merge._run_locked_workflow("plan", str(ws)) == 0
    assert merge._run_locked_workflow("execute", str(ws)) == 0
    assert open(os.path.join(str(lib), "Trip", "a.jpg"), "rb").read() == _fp_bytes("A")
    assert not os.path.exists(_src(ws, "Trip", "a.jpg"))


@pytest.mark.spec("RUL-failed_operation_clean", "RUL-merge_moves", "RUL-merge_removes_once_placed", "BLD-cross_fs_temp", "RUL-failure_recorded", test="TST-merge_execute-execute_torn_copy_blocks_and_keeps_source")
def test_execute_torn_copy_blocks_and_keeps_source(tmp_path, monkeypatch):
    _force_cross_fs(monkeypatch)
    monkeypatch.setattr(utils.shutil, "copyfile",
                        lambda src, dst: open(dst, "wb").write(b"FP=TORN"))   # corrupt the copy
    ws, lib = _ws(tmp_path, [{"fp": "A", "dest": "Trip", "final_name": "a.jpg"}])
    assert merge._run_locked_workflow("plan", str(ws)) == 0
    assert merge._run_locked_workflow("execute", str(ws)) == 3
    assert os.path.exists(_src(ws, "Trip", "a.jpg"))            # source preserved on a torn copy
    assert not os.path.exists(os.path.join(str(lib), "Trip", "a.jpg"))   # nothing under the final name
    assert _summary(ws)["totals"]["blocked"] == 1


@pytest.mark.spec("RUL-merge_moves", "RUL-merge_removes_once_placed", "BLD-merge_move", test="TST-merge_execute-a_copy_damaged_where_the_fingerprint_cannot_see_is_refused")
def test_a_copy_damaged_where_the_fingerprint_cannot_see_is_refused(tmp_path, monkeypatch):
    """The content fingerprint reads the decoded image, blind to metadata by design. A cross-filesystem
    copy damaged only there — same size, same fingerprint, other bytes — is refused all the same: the
    photo stays in the workspace, nothing under its name in the library."""
    _force_cross_fs(monkeypatch)
    def pixels_only(self, abs_path):        # the fingerprint ignores case, as pixels ignore EXIF
        v = _parse_fp(abs_path)
        return {"status": "valid", "value": v.upper(), "strategy": "image-content-hash-v2",
                "engine_version": "test"}
    monkeypatch.setattr(merge.MergeWorkflow, "_fingerprint_library_file", pixels_only)
    monkeypatch.setattr(utils.shutil, "copyfile",
                        lambda src, dst: open(dst, "wb").write(b"FP=a"))   # same size, one byte off
    ws, lib = _ws(tmp_path, [{"fp": "A", "dest": "Trip", "final_name": "a.jpg"}])
    assert merge._run_locked_workflow("plan", str(ws)) == 0
    assert merge._run_locked_workflow("execute", str(ws)) == 3
    assert open(_src(ws, "Trip", "a.jpg"), "rb").read() == _fp_bytes("A")
    assert not os.path.exists(os.path.join(str(lib), "Trip", "a.jpg"))
    assert not list((lib / "Trip").glob(".tmp-xdev-*"))


# --- concurrency determinism + lifecycle errors ------------------------------

def _comparable(s):
    # Determinism = same counts, status, and per-destination file order/flags regardless of job count.
    # The absolute library_path differs between the two scratch libraries, so drop it.
    dests = {d: [(f["by_dest_path"], f["renamed_for_library"], f["already_present"],
                  f["removed_from_by_dest"]) for f in v["files"]]
             for d, v in s["destinations"].items()}
    return {"totals": s["totals"], "resume": s["resume"], "status": s["status"], "dests": dests}


@pytest.mark.spec("BLD-merge_execute", "RUL-execution_jobs_change_nothing", test="TST-merge_execute-execute_jobs_determinism")
def test_execute_jobs_determinism(tmp_path):
    photos = [{"fp": "A", "dest": "Trip", "final_name": "a.jpg"},
              {"fp": "B", "dest": "Trip", "final_name": "b.jpg"},
              {"fp": "C", "dest": "Spain", "final_name": "c.jpg"}]
    ws1, _ = _ws(tmp_path, photos, name="w1")
    ws2, _ = _ws(tmp_path, photos, name="w2")
    assert merge._run_locked_workflow("plan", str(ws1)) == 0
    assert merge._run_locked_workflow("plan", str(ws2)) == 0
    assert merge._run_locked_workflow("execute", str(ws1), jobs=1) == 0
    assert merge._run_locked_workflow("execute", str(ws2), jobs=4) == 0
    assert _comparable(_summary(ws1)) == _comparable(_summary(ws2))


@pytest.mark.spec("RUL-execution_jobs_change_nothing", "BLD-merge_execute",
                  test="TST-merge_execute-photos_blocked_at_execute_are_reported_alike_under_any_job_count")
def test_photos_blocked_at_execute_are_reported_alike_under_any_job_count(tmp_path, monkeypatch):
    """Two photos whose library places were taken after the plan block at execute; the summary's failures are the
    same under -j1 and -j4, though under -j4 the first photo's move is made to finish after the second's."""
    import threading
    photos = [{"fp": "A", "dest": "Trip", "final_name": "a.jpg"},
              {"fp": "B", "dest": "Trip", "final_name": "b.jpg"}]
    summaries = []
    for name, jobs in (("j1", 1), ("j4", 4)):
        ws, lib = _ws(tmp_path, photos, name=name)
        assert merge._run_locked_workflow("plan", str(ws)) == 0
        (lib / "Trip").mkdir()
        for n in ("a.jpg", "b.jpg"):                                   # each place taken after the plan
            (lib / "Trip" / n).write_bytes(_fp_bytes("OTHER-" + n))
        real_move, b_done = merge.MergeWorkflow._move_file, threading.Event()

        def move(self, ws_, library_root, rec, real_move=real_move, b_done=b_done, jobs=jobs):
            if jobs > 1 and rec["by_dest_source"].endswith("a.jpg"):
                b_done.wait(timeout=10)                                # a.jpg finishes after b.jpg
            r = real_move(self, ws_, library_root, rec)
            if rec["by_dest_source"].endswith("b.jpg"):
                b_done.set()
            return r
        with monkeypatch.context() as m:
            m.setattr(merge.MergeWorkflow, "_move_file", move)
            assert merge._run_locked_workflow("execute", str(ws), jobs=jobs) == 3
        s = _summary(ws)
        assert s["totals"]["blocked"] == 2, s["totals"]
        summaries.append(s)
    one, four = ([f.replace(str(tmp_path), "").replace("/j1", "/W").replace("/j4", "/W") for f in s["failures"]]
                 for s in summaries)
    assert len(one) == 2 and one == four, (one, four)


@pytest.mark.spec("RUL-crash_temps_cleared", "BLD-temp_sweep", "RUL-crash_temps_counted",
                  test="TST-merge_execute-execute_sweeps_crash_orphaned_cross_fs_temps")
def test_execute_sweeps_crash_orphaned_cross_fs_temps(tmp_path):
    """A prior interrupted run can leave a cross-fs copy temp (.tmp-xdev-*.part) in a library dir.
    Because merge holds the library lock (no concurrent merge), execute safely sweeps such orphans
    from the dirs it targets before placing — they never accumulate in the precious library tree."""
    ws, lib = _ws(tmp_path, [{"fp": "A", "dest": "Trip", "final_name": "a.jpg"}])
    assert merge._run_locked_workflow("plan", str(ws)) == 0
    (lib / "Trip").mkdir(parents=True, exist_ok=True)
    orphan = lib / "Trip" / (utils.XDEV_TMP_PREFIX + "deadbeef" + utils.XDEV_TMP_SUFFIX)
    orphan.write_bytes(b"half-copied debris")
    keep = lib / "Trip" / "unrelated.txt"; keep.write_bytes(b"keep")   # a non-temp file is never touched
    assert merge._run_locked_workflow("execute", str(ws)) == 0
    assert not orphan.exists()                                         # crash debris swept
    assert keep.read_bytes() == b"keep"                               # ordinary files untouched
    assert _summary(ws)["run_metadata"]["orphan_temps_swept"] >= 1


@pytest.mark.spec("RUL-execution_jobs_change_nothing", test="TST-merge_execute-execute_jobs_identical_library_file_tree")
def test_execute_jobs_identical_library_file_tree(tmp_path):
    """Beyond the summary, the placed LIBRARY file tree is byte-identical under -j1 vs -j4 — the
    move pass has no concurrency-dependent semantics (relative paths + bytes match exactly)."""
    photos = [{"fp": "A", "dest": "Trip", "final_name": "a.jpg"},
              {"fp": "B", "dest": "Trip", "final_name": "b.jpg"},
              {"fp": "C", "dest": "Spain", "final_name": "c.jpg"}]
    ws1, lib1 = _ws(tmp_path, photos, name="t1")
    ws2, lib2 = _ws(tmp_path, photos, name="t2")
    assert merge._run_locked_workflow("plan", str(ws1)) == 0
    assert merge._run_locked_workflow("plan", str(ws2)) == 0
    assert merge._run_locked_workflow("execute", str(ws1), jobs=1) == 0
    assert merge._run_locked_workflow("execute", str(ws2), jobs=4) == 0
    assert _tree(str(lib1)) == _tree(str(lib2))                    # identical placed tree (ignores *.lock)


@pytest.mark.spec("BLD-merge_execute", "RUL-snapshot_timing",
                  test="TST-merge_execute-snapshot_and_revalidation_precede_the_parallel_move_pass")
def test_snapshot_and_revalidation_precede_the_parallel_move_pass(tmp_path, monkeypatch):
    """Sequencing (BLD-merge_execute): the move-set is fixed BEFORE any concurrent placement — dependency
    revalidation and the pre-mutation snapshot both complete before the FIRST per-file move runs,
    even under -j4. Probe the call order via wrappers."""
    ws, lib = _ws(tmp_path,
                  [{"fp": "A", "dest": "Trip", "final_name": "a.jpg"},
                   {"fp": "B", "dest": "Trip", "final_name": "b.jpg"},
                   {"fp": "C", "dest": "Spain", "final_name": "c.jpg"}])
    _zfs(monkeypatch, ws)                                         # snapshots on, both sides snapshottable
    assert merge._run_locked_workflow("plan", str(ws)) == 0

    events = []
    orig_reval = merge.MergeWorkflow.revalidate_plan_deps
    orig_snap = merge.take_zfs_snapshot
    orig_move = merge.MergeWorkflow._move_file

    def reval(self, *a, **k):
        events.append("revalidate"); return orig_reval(self, *a, **k)

    def snap(*a, **k):
        events.append("snapshot"); return orig_snap(*a, **k)

    def move(self, *a, **k):
        events.append("move"); return orig_move(self, *a, **k)

    orig_snap = merge.take_zfs_snapshot
    monkeypatch.setattr(merge.MergeWorkflow, "revalidate_plan_deps", reval)
    monkeypatch.setattr(merge, "take_zfs_snapshot", snap)
    monkeypatch.setattr(merge.MergeWorkflow, "_move_file", move)
    assert merge._run_locked_workflow("execute", str(ws), jobs=4) == 0

    first_move = events.index("move")
    assert events.index("revalidate") < first_move                # move-set fixed before any placement
    assert events.index("snapshot") < first_move
    assert events.count("move") == 3                              # all three files still placed


@pytest.mark.spec("RUL-snapshot_after_validation",
                  test="TST-merge_execute-no_snapshot_before_the_plan_is_validated")
def test_no_snapshot_before_the_plan_is_validated(tmp_path, monkeypatch):
    """A snapshot follows the plan's validation against its dependencies: a plan that fails it is
    rejected with no snapshot taken at all, and a plan that passes is validated first."""
    photos = [{"fp": "A", "dest": "Trip", "final_name": "a.jpg"}]
    stale_ws, _ = _ws(tmp_path, photos, name="stale")
    taken = _zfs(monkeypatch, stale_ws)
    assert merge._run_locked_workflow("plan", str(stale_ws)) == 0
    open(os.path.join(str(stale_ws), ".photos-ingest", "photos-25-execution-summary.json"), "w").write(
        json.dumps({"status": "success", "touched": True}))      # a dependency changed after planning
    assert merge._run_locked_workflow("execute", str(stale_ws)) == 2
    assert taken == []                                            # rejected before any snapshot

    ws, _ = _ws(tmp_path, photos)
    taken = _zfs(monkeypatch, ws)
    assert merge._run_locked_workflow("plan", str(ws)) == 0
    events = []
    orig_reval, faked_snap = merge.MergeWorkflow.revalidate_plan_deps, merge.take_zfs_snapshot

    def reval(self, *a, **k):
        events.append("revalidate"); return orig_reval(self, *a, **k)

    def snap(*a, **k):
        events.append("snapshot"); return faked_snap(*a, **k)

    monkeypatch.setattr(merge.MergeWorkflow, "revalidate_plan_deps", reval)
    monkeypatch.setattr(merge, "take_zfs_snapshot", snap)
    assert merge._run_locked_workflow("execute", str(ws)) == 0
    assert taken and events[0] == "revalidate" and "snapshot" in events, events


@pytest.mark.spec("RUL-snapshot_under_lock", test="TST-merge_execute-snapshot_is_taken_while_the_lock_is_held")
def test_snapshot_is_taken_while_the_lock_is_held(tmp_path, monkeypatch):
    """Every snapshot of a merge is taken while the workspace lock is held: probed, from a file
    descriptor of its own, at the moment each snapshot is asked for."""
    ws, lib = _ws(tmp_path, [{"fp": "A", "dest": "Trip", "final_name": "a.jpg"}])
    _zfs(monkeypatch, ws)
    assert merge._run_locked_workflow("plan", str(ws)) == 0
    faked_snap = merge.take_zfs_snapshot
    held = []

    def snap(*a, **k):
        held.append(utils.WorkspaceLock(str(ws), create=False).held_owner() is not None)
        return faked_snap(*a, **k)

    monkeypatch.setattr(merge, "take_zfs_snapshot", snap)
    assert merge._run_locked_workflow("execute", str(ws)) == 0
    assert held == [True, True], held                             # the workspace's and the library's
    assert utils.WorkspaceLock(str(ws), create=False).held_owner() is None   # the probe tells held from free


@pytest.mark.spec("BLD-library_lock", test="TST-merge_execute-library_lock_held_throughout_concurrent_move_pass")
def test_library_lock_held_throughout_concurrent_move_pass(tmp_path, monkeypatch):
    """BLD-library_lock: the library lock is held for the WHOLE concurrent move pass — concurrency never relaxes
    cross-run exclusion. Probe by wrapping _move_file (the per-file placement that runs during the
    parallel pass): on its first invocation, a fresh LibraryLock on the same library_root must FAIL to
    acquire (rc False) because the running merge already holds it. Then call through to the original."""
    photos = [{"fp": "A", "dest": "Trip", "final_name": "a.jpg"},
              {"fp": "B", "dest": "Trip", "final_name": "b.jpg"},
              {"fp": "C", "dest": "Spain", "final_name": "c.jpg"}]
    ws, lib = _ws(tmp_path, photos)
    assert merge._run_locked_workflow("plan", str(ws)) == 0

    orig_move = merge.MergeWorkflow._move_file
    probed = []

    def probe(self, *a, **k):
        if not probed:                                            # only on the first move call
            probe_lock = utils.LibraryLock(str(lib))
            got = probe_lock.acquire()
            if got:                                               # defensive cleanup; should never happen
                probe_lock.release()
            assert got is False, "library lock was NOT held during the move pass"
            probed.append(True)
        return orig_move(self, *a, **k)

    monkeypatch.setattr(merge.MergeWorkflow, "_move_file", probe)
    assert merge._run_locked_workflow("execute", str(ws), jobs=4) == 0
    assert probed, "the _move_file probe never ran"
    assert _summary(ws)["status"] == "success"


@pytest.mark.spec("BLD-merge_execute", test="TST-merge_execute-merge_journal_writes_only_from_the_main_thread")
def test_merge_journal_writes_only_from_the_main_thread(tmp_path, monkeypatch):
    """Single-writer journal (BLD-merge_execute): under -j4 the merge confirmation journal is persisted ONLY by the
    main thread; worker threads move files but never touch the journal. Probe every journal write."""
    import threading
    ws, lib = _ws(tmp_path,
                  [{"fp": "A", "dest": "Trip", "final_name": "a.jpg"},
                   {"fp": "B", "dest": "Trip", "final_name": "b.jpg"},
                   {"fp": "C", "dest": "Spain", "final_name": "c.jpg"}])
    assert merge._run_locked_workflow("plan", str(ws)) == 0
    orig = merge.write_json_artifact
    journal_threads = []

    def spy(path, obj, *a, **k):
        if isinstance(obj, dict) and "journal_version" in obj:
            journal_threads.append(threading.current_thread().name)
        return orig(path, obj, *a, **k)

    monkeypatch.setattr(merge, "write_json_artifact", spy)
    assert merge._run_locked_workflow("execute", str(ws), jobs=4) == 0
    assert journal_threads, "expected at least one journal write"
    assert all(t == "MainThread" for t in journal_threads), journal_threads


@pytest.mark.spec("RUL-no_plan_no_run", test="TST-merge_execute-execute_without_plan_errors")
def test_execute_without_plan_errors(tmp_path):
    ws, lib = _ws(tmp_path, [{"fp": "A", "dest": "Trip", "final_name": "a.jpg"}])
    assert merge._run_locked_workflow("execute", str(ws)) == 2     # no photos-30


@pytest.mark.spec("INV-no_stale_use", test="TST-merge_execute-execute_rejects_stale_plan")
def test_execute_rejects_stale_plan(tmp_path):
    ws, lib = _ws(tmp_path, [{"fp": "A", "dest": "Trip", "final_name": "a.jpg"}])
    assert merge._run_locked_workflow("plan", str(ws)) == 0
    p24 = os.path.join(str(ws), ".photos-ingest", "photos-25-execution-summary.json")
    open(p24, "w").write(json.dumps({"status": "success", "touched": True}))   # dep changed
    assert merge._run_locked_workflow("execute", str(ws)) == 2
    assert not os.path.exists(os.path.join(str(ws.parent), "ws-lib", "Trip"))  # nothing moved


# --- no-mutation consequences of non-executing paths (Tier 3) ----------------

@pytest.mark.spec("RUL-planning_changes_no_media", "RUL-planning_writes_only_its_records",
                  test="TST-merge_execute-plan_mutates_nothing_no_terminal_artifacts")
def test_plan_mutates_nothing_no_terminal_artifacts(tmp_path):
    """Planning never mutates: after `plan`, by-dest + library are identical — bytes, size and modification time —
    and NONE of the execute-only artifacts (photos-31 summary, photos-35 log/db/manifest, journal, seal) exist."""
    ws, lib = _ws(tmp_path, [{"fp": "A", "dest": "Trip", "final_name": "a.jpg"}])
    before_bd, before_lib = _tree(str(ws / "6-photos-by-dest"), times=True), _tree(str(lib), times=True)
    assert merge._run_locked_workflow("plan", str(ws)) == 0
    assert _tree(str(ws / "6-photos-by-dest"), times=True) == before_bd      # staging untouched, times too
    assert _tree(str(lib), times=True) == before_lib                         # library untouched
    ctl = ws / ".photos-ingest"
    assert not os.path.exists(merge.merge_summary_path(str(ws)))  # no photos-31
    assert not utils.is_sealed(str(ws))                          # no seal
    for n in ("photos-35-merge-log.json", "photos-35-merge-ingest.db"):
        assert not os.path.exists(ctl / n), n


@pytest.mark.spec("BLD-merge_records", test="TST-merge_execute-stale_plan_rejection_writes_no_summary")
def test_stale_plan_rejection_writes_no_summary(tmp_path):
    """A stale-plan rejection is a pre-mutation abort: it must write NO photos-31 summary at all
    (distinct from a required-snapshot abort, which records a `rejected` summary) and move nothing."""
    ws, lib = _ws(tmp_path, [{"fp": "A", "dest": "Trip", "final_name": "a.jpg"}])
    assert merge._run_locked_workflow("plan", str(ws)) == 0
    before_lib = _tree(str(lib))
    # Mutate a recorded dependency after planning -> the saved plan is stale.
    open(os.path.join(str(ws), ".photos-ingest", "photos-25-execution-summary.json"), "w").write(
        json.dumps({"status": "success", "touched": True}))
    assert merge._run_locked_workflow("execute", str(ws)) == 2
    assert not os.path.exists(merge.merge_summary_path(str(ws)))  # NO summary on stale rejection
    assert _tree(str(lib)) == before_lib                          # library untouched
    assert open(_src(ws, "Trip", "a.jpg"), "rb").read() == _fp_bytes("A")


@pytest.mark.spec("RUL-merge_blocked_changes_nothing", test="TST-merge_execute-precondition_failure_writes_no_summary_and_no_placement")
def test_precondition_failure_writes_no_summary_and_no_placement(tmp_path):
    """A preflight blocker stops merge before execute: no photos-31 summary, library byte-unchanged.
    Here the prep handoff is missing — a precondition the preflight gathers and refuses on."""
    ws, lib = _ws(tmp_path, [{"fp": "A", "dest": "Trip", "final_name": "a.jpg"}])
    before_lib = _tree(str(lib))
    os.remove(os.path.join(str(ws), ".photos-ingest", "photos-11-handoff.json"))  # break a precondition
    assert merge._run_locked_workflow("execute", str(ws)) == 2    # preflight blocker -> rc 2
    assert not os.path.exists(merge.merge_summary_path(str(ws)))  # no summary written
    assert _tree(str(lib)) == before_lib                          # nothing placed
    assert open(_src(ws, "Trip", "a.jpg"), "rb").read() == _fp_bytes("A")   # the photo left where it was


@pytest.mark.spec("RUL-merge_blocked_changes_nothing",
                  test="TST-merge_execute-an_execute_a_precondition_stops_after_a_clean_plan_changes_nothing")
def test_an_execute_a_precondition_stops_after_a_clean_plan_changes_nothing(tmp_path):
    """A clean plan saved, then a photo put in the inbox: execute's preconditions stop it (exit 2) with the plan
    there to carry out, and it changes nothing — nothing placed, no photo moved, no journal, no summary."""
    ws, lib = _ws(tmp_path, [{"fp": "A", "dest": "Trip", "final_name": "a.jpg"}])
    assert merge._run_locked_workflow("plan", str(ws)) == 0
    plan_id = json.load(open(merge.merge_plan_path(str(ws))))["plan_id"]
    (ws / "0-sources" / "new.jpg").write_bytes(b"a new dump")
    before = _tree(str(ws)), _tree(str(lib))
    assert merge._run_locked_workflow("execute", str(ws)) == 2
    assert (_tree(str(ws)), _tree(str(lib))) == before
    assert not os.path.exists(merge.journal_path(str(ws), plan_id))
    assert not os.path.exists(merge.merge_summary_path(str(ws)))


@pytest.mark.spec("RUL-execution_only_the_plan",
                  test="TST-merge_execute-execute_applies_saved_plan_verbatim_no_rederive")
def test_execute_applies_saved_plan_verbatim_no_rederive(tmp_path):
    """Execute consumes the saved photos-30 disposition/target VERBATIM — it never re-derives the
    placement from the handoff/scan. Doctor the saved target name; execute must place the file under
    the DOCTORED name, not re-compute the original."""
    ws, lib = _ws(tmp_path, [{"fp": "A", "dest": "Trip", "final_name": "a.jpg"}])
    assert merge._run_locked_workflow("plan", str(ws)) == 0
    pp = merge.merge_plan_path(str(ws))
    plan = json.loads(open(pp).read())
    rec = plan["destinations"]["Trip"]["files"][0]
    assert rec["disposition"] == "placed_new"
    rec["library_target"] = os.path.join(str(lib), "Trip", "DOCTORED.jpg")   # doctor the saved target
    rec["resolved_name"] = "DOCTORED.jpg"
    open(pp, "w").write(json.dumps(plan))
    assert merge._run_locked_workflow("execute", str(ws)) == 0
    assert open(os.path.join(str(lib), "Trip", "DOCTORED.jpg"), "rb").read() == _fp_bytes("A")  # verbatim
    assert not os.path.exists(os.path.join(str(lib), "Trip", "a.jpg"))       # NOT re-derived


@pytest.mark.spec("BLD-merge_journal_resume", "RUL-failure_never_done",
                  test="TST-merge_execute-partial_run_journal_holds_only_confirmed_moves")
def test_partial_run_journal_holds_only_confirmed_moves(tmp_path):
    """After a partial run (one placed, one blocked), the merge journal records ONLY the confirmed
    move — the blocked file is absent, so the next run resumes from the true diff (BLD-merge_journal_resume)."""
    ws, lib = _ws(tmp_path,
                  [{"fp": "A", "dest": "Trip", "final_name": "a.jpg"},
                   {"fp": "B", "dest": "Trip", "final_name": "b.jpg"}],
                  library_files=[{"fp": "FAIL", "dest": "Trip", "name": "b.jpg"}])  # b's lib file unreadable
    assert merge._run_locked_workflow("plan", str(ws)) == 2   # a blocker: ends as a refusal (RUL-blocked_plan_ends_refused)
    assert merge._run_locked_workflow("execute", str(ws)) == 3            # partial -> rc 3
    s = _summary(ws)
    assert s["status"] == "partial"
    plan_id = json.loads(open(merge.merge_plan_path(str(ws))).read())["plan_id"]
    journal = (json.load(open(merge.journal_path(str(ws), plan_id))) or {}).get("operations", {})
    assert journal == {"6-photos-by-dest/Trip/a.jpg": "confirmed"}        # only the placed file
    assert "6-photos-by-dest/Trip/b.jpg" not in journal                  # blocked file absent


# --- Increment 5: terminal finalization (full-success only) -------------------

def _ctl(ws, name):
    return os.path.join(str(ws), ".photos-ingest", name)


@pytest.mark.spec("BLD-merge_success_sequence", "RUL-merge_records_landing", "RUL-merge_reseals", "RUL-seal_on_success_only", test="TST-merge_execute-full_success_writes_terminal_artifacts_and_seals")
def test_full_success_writes_terminal_artifacts_and_seals(tmp_path):
    ws, lib = _ws(tmp_path, [{"fp": "A", "dest": "Trip", "final_name": "a.jpg"}])
    assert merge._run_locked_workflow("plan", str(ws)) == 0
    assert merge._run_locked_workflow("execute", str(ws)) == 0
    for name in ("photos-31-merge-summary.json", "photos-35-merge-log.json",
                 "photos-35-merge-ingest.db", "photos-35-archive-manifest.json",
                 "photos-00-sealed.json"):
        assert os.path.exists(_ctl(ws, name)), name
    sealed = json.loads(open(_ctl(ws, "photos-00-sealed.json")).read())
    assert sealed["sealed"] is True and sealed["library_root"] == str(lib)
    # BLD-merge_records: summary carries the merge plan id, the geotag run ids, and a finish time.
    summ = _summary(ws)
    assert summ["merge_plan_id"] == json.loads(open(_ctl(ws, "photos-30-merge-plan.json")).read())["plan_id"]
    assert summ["geotag"] == {"plan_id": "cal-plan-1", "execution_id": "cal-exec-1"}
    assert summ["run_metadata"]["finished_at"] and summ["run_metadata"]["started_at"]
    # The re-seal manifest supersedes geotag's and lists the merge artifacts.
    manifest = json.loads(open(_ctl(ws, "photos-35-archive-manifest.json")).read())
    assert manifest["supersedes"] == "photos-26-archive-manifest.json"
    assert "photos-31-merge-summary.json" in manifest["contents"]
    assert "photos-35-merge-log.json" in manifest["contents"]


@pytest.mark.spec("BLD-log_format", "RUL-record_whole_each_phase", "BLD-phase_logs", "RUL-phase_writes_own_records",
                  "RUL-log_step_names_run", "RUL-carry_forward_by_copy",
                  test="TST-merge_execute-merge_log_copies_the_complete_log_forward_and_appends")
def test_merge_log_copies_photos25_forward_and_appends(tmp_path):
    ws, lib = _ws(tmp_path, [{"fp": "A", "dest": "Trip", "final_name": "a.jpg"}])
    # Seed photos-25 with a prior geotag journey for fingerprint A.
    open(_ctl(ws, "photos-26-complete-log.json"), "w").write(json.dumps(
        {"schema_version": 1, "tool": "photos-2-geotag",
         "photos": {"A": {"content_fingerprint": "A",
                          "journey": [{"phase": "geotag", "action": "renamed"}]}}}))
    assert merge._run_locked_workflow("plan", str(ws)) == 0
    assert merge._run_locked_workflow("execute", str(ws)) == 0
    log = json.loads(open(_ctl(ws, "photos-35-merge-log.json")).read())
    assert log["tool"] == "photos-3-merge"
    journey = log["photos"]["A"]["journey"]
    assert journey[0]["phase"] == "geotag"                      # carried forward
    assert log["photos"]["A"]["library_path"] == os.path.join(str(lib), "Trip", "a.jpg")   # where it now is
    plan_id = json.loads(open(_ctl(ws, "photos-30-merge-plan.json")).read())["plan_id"]
    assert plan_id and journey[-1] == {"phase": "merge", "run": plan_id, "action": "placed",
                           "from": "6-photos-by-dest/Trip/a.jpg",
                           "library_path": os.path.join(str(lib), "Trip", "a.jpg"),
                           "renamed_for_library": False}
    # photos-25 itself must be byte-unchanged (never edited).
    p25 = json.loads(open(_ctl(ws, "photos-26-complete-log.json")).read())
    assert p25["photos"]["A"]["journey"] == [{"phase": "geotag", "action": "renamed"}]


@pytest.mark.spec("RUL-seal_on_success_only", "RUL-unplaced_photo_run_partial",
                  test="TST-merge_execute-partial_run_does_not_seal_or_finalize")
def test_partial_run_does_not_seal_or_finalize(tmp_path):
    ws, lib = _ws(tmp_path, [{"fp": "A", "dest": "Trip", "final_name": "a.jpg"}],
                  library_files=[{"fp": "FAIL", "dest": "Trip", "name": "a.jpg"}])
    assert merge._run_locked_workflow("plan", str(ws)) == 2   # a blocker: ends as a refusal (RUL-blocked_plan_ends_refused)
    assert merge._run_locked_workflow("execute", str(ws)) == 3          # partial
    assert not utils.is_sealed(str(ws))                                # re-runnable
    for name in ("photos-35-merge-log.json", "photos-35-merge-ingest.db",
                 "photos-35-archive-manifest.json", "photos-00-sealed.json"):
        assert not os.path.exists(_ctl(ws, name)), name
    assert os.path.exists(_ctl(ws, "photos-31-merge-summary.json"))     # summary still written


@pytest.mark.spec("RUL-replan_carries_placed", "RUL-merge_resumable",
                  test="TST-merge_execute-a_re_plan_after_a_partial_merge_carries_what_was_moved")
def test_a_re_plan_after_a_partial_merge_carries_what_was_moved(tmp_path):
    """A partial merge — a.jpg moved, b.jpg blocked — is re-planned once the blocker is cleared. The new
    plan carries a.jpg forward from the plan that moved it, and the merge that finishes logs both."""
    ws, lib = _ws(tmp_path, [{"fp": "A", "dest": "Trip", "final_name": "a.jpg"},
                             {"fp": "B", "dest": "Trip", "final_name": "b.jpg"}],
                  library_files=[{"fp": "FAIL", "dest": "Trip", "name": "b.jpg"}])
    assert merge._run_locked_workflow("plan", str(ws)) == 2   # a blocker: ends as a refusal (RUL-blocked_plan_ends_refused)
    assert merge._run_locked_workflow("execute", str(ws)) == 3          # 1 placed, 1 blocked -> partial
    assert _summary(ws)["status"] == "partial"
    assert not os.path.exists(_src(ws, "Trip", "a.jpg"))               # a.jpg was moved (source gone)
    with open(os.path.join(str(lib), "Trip", "b.jpg"), "wb") as f:
        f.write(_fp_bytes("OLD"))                                        # the blocker cleared
    assert merge._run_locked_workflow("plan", str(ws)) == 0             # re-plan allowed
    plan = json.load(open(merge.merge_plan_path(str(ws))))
    recs = {r["by_dest_source"]: r for d in plan["destinations"].values() for r in d["files"]}
    assert recs["6-photos-by-dest/Trip/a.jpg"].get("carried_from_plan")
    assert merge._run_locked_workflow("execute", str(ws)) == 0
    assert utils.is_sealed(str(ws))
    log = json.loads(open(_ctl(ws, "photos-35-merge-log.json")).read())
    assert log["photos"]["A"]["library_path"] == os.path.join(str(lib), "Trip", "a.jpg")
    assert log["photos"]["B"]["library_path"] == os.path.join(str(lib), "Trip", "b-001.jpg")


@pytest.mark.parametrize("older,later", [(1, 2), (999, 1000)], ids=["oldest_first", "past_999"])
@pytest.mark.spec("RUL-replan_carries_placed", test="TST-merge_execute-the_latest_earlier_plan_s_place_is_carried")
def test_the_latest_earlier_plan_s_place_is_carried(tmp_path, older, later):
    """Two plans set aside each placed one photo, at two places the library both holds it at: the re-plan carries the
    place of the latest of them — by the number of its suffix, so `-1000` is later than `-999`."""
    ws, lib = _ws(tmp_path, [{"fp": "A", "dest": "Trip", "final_name": "a.jpg"}],
                  library_files=[{"fp": "A", "dest": "Trip", "name": "x.jpg"},
                                 {"fp": "A", "dest": "Trip", "name": "y.jpg"}])
    os.remove(_src(ws, "Trip", "a.jpg"))                                # placed by an earlier merge
    stem, ext = os.path.splitext(merge.merge_plan_path(str(ws)))
    for n, place in ((older, "x.jpg"), (later, "y.jpg")):
        with open(f"{stem}-{n:03d}{ext}", "w") as f:
            json.dump({"plan_id": f"p{n}", "destinations": {"Trip": {"files": [
                {"by_dest_source": "6-photos-by-dest/Trip/a.jpg", "content_fingerprint": "A", "disposition": "placed_new",
                 "library_target": os.path.join(str(lib), "Trip", place)}]}}}, f)
    assert merge._run_locked_workflow("plan", str(ws)) == 0
    plan = json.load(open(merge.merge_plan_path(str(ws))))
    (rec,) = [r for d in plan["destinations"].values() for r in d["files"]]
    assert rec["carried_from_plan"] == f"p{later}"
    assert rec["library_target"] == os.path.join(str(lib), "Trip", "y.jpg")


@pytest.mark.spec("RUL-merge_run_records_kept", "BLD-merge_records",
                  test="TST-merge_execute-an_earlier_merge_summary_is_kept_aside")
def test_an_earlier_merge_summary_is_kept_aside(tmp_path):
    """Each execute's summary sets the one before it aside under `-NNN`, as geotag's are: a partial merge's summary,
    and the hand changes it names, outlive the execute that finishes the merge."""
    ws, lib = _ws(tmp_path, [{"fp": "A", "dest": "Trip", "final_name": "a.jpg"},
                             {"fp": "B", "dest": "Trip", "final_name": "b.jpg"}],
                  library_files=[{"fp": "FAIL", "dest": "Trip", "name": "b.jpg"}])
    assert merge._run_locked_workflow("plan", str(ws)) == 2
    assert merge._run_locked_workflow("execute", str(ws)) == 3
    partial = open(merge.merge_summary_path(str(ws)), "rb").read()
    with open(os.path.join(str(lib), "Trip", "b.jpg"), "wb") as f:
        f.write(_fp_bytes("OLD"))                                        # the blocker cleared
    assert merge._run_locked_workflow("plan", str(ws)) == 0
    assert merge._run_locked_workflow("execute", str(ws)) == 0
    stem, ext = os.path.splitext(merge.merge_summary_path(str(ws)))
    assert open(f"{stem}-001{ext}", "rb").read() == partial
    assert _summary(ws)["status"] == "success"


@pytest.mark.spec("RUL-log_step_names_run",
                  test="TST-merge_execute-a_carried_photos_merge_step_names_the_plan_that_placed_it")
def test_a_carried_photos_merge_step_names_the_plan_that_placed_it(tmp_path):
    """A photo placed under one plan and carried forward by the next: its merge step names the plan
    that placed it, not the one that only carried it; a photo the later plan placed names that one."""
    ws, lib = _ws(tmp_path, [{"fp": "A", "dest": "Trip", "final_name": "a.jpg"},
                             {"fp": "B", "dest": "Trip", "final_name": "b.jpg"}],
                  library_files=[{"fp": "FAIL", "dest": "Trip", "name": "b.jpg"}])
    assert merge._run_locked_workflow("plan", str(ws)) == 2   # a blocker: ends as a refusal (RUL-blocked_plan_ends_refused)
    first = json.load(open(merge.merge_plan_path(str(ws))))["plan_id"]
    assert merge._run_locked_workflow("execute", str(ws)) == 3          # a.jpg placed, b.jpg blocked
    with open(os.path.join(str(lib), "Trip", "b.jpg"), "wb") as f:
        f.write(_fp_bytes("OLD"))                                        # the blocker cleared
    assert merge._run_locked_workflow("plan", str(ws)) == 0
    second = json.load(open(merge.merge_plan_path(str(ws))))["plan_id"]
    assert merge._run_locked_workflow("execute", str(ws)) == 0
    log = json.loads(open(_ctl(ws, "photos-35-merge-log.json")).read())
    assert first != second
    assert log["photos"]["A"]["journey"][-1]["run"] == first
    assert log["photos"]["B"]["journey"][-1]["run"] == second


@pytest.mark.spec("RUL-replan_carries_placed",
                  test="TST-merge_execute-a_re_plan_carries_a_photo_moved_but_never_journalled")
def test_a_re_plan_carries_a_photo_moved_but_never_journalled(tmp_path):
    """A move that finished without its journal entry — a crash just after it, or a Ctrl-C while it
    ran — is carried by the re-plan on the evidence: its earlier plan's place, fingerprinted again,
    holds it."""
    ws, lib = _ws(tmp_path, [{"fp": "A", "dest": "Trip", "final_name": "a.jpg"},
                             {"fp": "B", "dest": "Trip", "final_name": "b.jpg"}],
                  library_files=[{"fp": "FAIL", "dest": "Trip", "name": "b.jpg"}])
    assert merge._run_locked_workflow("plan", str(ws)) == 2   # a blocker: ends as a refusal (RUL-blocked_plan_ends_refused)
    pid = json.load(open(merge.merge_plan_path(str(ws))))["plan_id"]
    assert merge._run_locked_workflow("execute", str(ws)) == 3          # a.jpg moved, b.jpg blocked
    os.remove(utils.journal_path(str(ws), pid))                         # the confirmation never written
    with open(os.path.join(str(lib), "Trip", "b.jpg"), "wb") as f:
        f.write(_fp_bytes("OLD"))                                        # the blocker cleared
    assert merge._run_locked_workflow("plan", str(ws)) == 0
    plan = json.load(open(merge.merge_plan_path(str(ws))))
    recs = {r["by_dest_source"]: r for d in plan["destinations"].values() for r in d["files"]}
    assert recs["6-photos-by-dest/Trip/a.jpg"].get("carried_from_plan") == pid
    assert merge._run_locked_workflow("execute", str(ws)) == 0
    assert utils.is_sealed(str(ws))
    log = json.loads(open(_ctl(ws, "photos-35-merge-log.json")).read())
    assert log["photos"]["A"]["library_path"] == os.path.join(str(lib), "Trip", "a.jpg")


@pytest.mark.spec("RUL-resume_rechecks_library", "RUL-resume_blocks_missing", "RUL-resume_block_makes_partial",
                  test="TST-merge_execute-a_resumed_execute_checks_a_journalled_photo_is_still_in_the_library")
def test_a_resumed_execute_checks_a_journalled_photo_is_still_in_the_library(tmp_path):
    """The journal says a.jpg was moved; its library place no longer holds it. Execute run again
    blocks it rather than counting it done, and the workspace is not sealed."""
    ws, lib = _ws(tmp_path, [{"fp": "A", "dest": "Trip", "final_name": "a.jpg"},
                             {"fp": "B", "dest": "Trip", "final_name": "b.jpg"}],
                  library_files=[{"fp": "FAIL", "dest": "Trip", "name": "b.jpg"}])
    assert merge._run_locked_workflow("plan", str(ws)) == 2   # a blocker: ends as a refusal (RUL-blocked_plan_ends_refused)
    assert merge._run_locked_workflow("execute", str(ws)) == 3
    with open(os.path.join(str(lib), "Trip", "a.jpg"), "wb") as f:
        f.write(_fp_bytes("X"))                                          # a.jpg's place replaced
    assert merge._run_locked_workflow("execute", str(ws)) == 3
    s = _summary(ws)
    assert s["totals"]["placed_new"] == 0 and s["totals"]["blocked"] == 2
    assert any("a.jpg" in f and "no longer holds it" in f for f in s["failures"])
    assert not utils.is_sealed(str(ws))


@pytest.mark.spec("RUL-resume_rechecks_library", "RUL-resume_blocks_missing", "RUL-resume_block_makes_partial",
                  test="TST-merge_execute-a_photo_already_present_whose_copy_is_gone_is_checked_in_the_library")
def test_a_photo_already_present_whose_copy_is_gone_is_checked_in_the_library(tmp_path):
    """A photo planned as already present whose workspace copy is gone counts as done only while the
    library still holds it."""
    ws, lib = _ws(tmp_path, [{"fp": "A", "dest": "Trip", "final_name": "a.jpg"}],
                  library_files=[{"fp": "A", "dest": "Trip", "name": "a.jpg"}])
    assert merge._run_locked_workflow("plan", str(ws)) == 0
    os.remove(_src(ws, "Trip", "a.jpg"))
    with open(os.path.join(str(lib), "Trip", "a.jpg"), "wb") as f:
        f.write(_fp_bytes("X"))
    assert merge._run_locked_workflow("execute", str(ws)) == 3
    assert _summary(ws)["totals"]["blocked"] == 1
    assert not utils.is_sealed(str(ws))


@pytest.mark.spec("RUL-resume_rechecks_library",
                  "RUL-replan_blocks_unaccounted", "RUL-replan_block_names_why",
                  test="TST-merge_execute-a_photo_moved_earlier_but_gone_from_its_place_blocks_the_re_plan")
def test_a_photo_moved_earlier_but_gone_from_its_place_blocks_the_re_plan(tmp_path):
    ws, lib = _ws(tmp_path, [{"fp": "A", "dest": "Trip", "final_name": "a.jpg"},
                             {"fp": "B", "dest": "Trip", "final_name": "b.jpg"}],
                  library_files=[{"fp": "FAIL", "dest": "Trip", "name": "b.jpg"}])
    assert merge._run_locked_workflow("plan", str(ws)) == 2   # a blocker: ends as a refusal (RUL-blocked_plan_ends_refused)
    assert merge._run_locked_workflow("execute", str(ws)) == 3
    with open(os.path.join(str(lib), "Trip", "a.jpg"), "wb") as f:
        f.write(_fp_bytes("X"))                                          # a.jpg's place no longer holds it
    merge._run_locked_workflow("plan", str(ws))
    plan = json.load(open(merge.merge_plan_path(str(ws))))
    a = next(r for d in plan["destinations"].values() for r in d["files"] if r["by_dest_source"].endswith("a.jpg"))
    assert a["disposition"] == "blocked" and "no longer holds it" in a["blocked_reason"]


@pytest.mark.spec("RUL-replan_blocks_unaccounted", "RUL-replan_block_names_why",
                  test="TST-merge_execute-a_photo_gone_from_the_workspace_that_no_merge_moved_blocks_the_plan")
def test_a_photo_gone_from_the_workspace_that_no_merge_moved_blocks_the_plan(tmp_path):
    ws, lib = _ws(tmp_path, [{"fp": "A", "dest": "Trip", "final_name": "a.jpg"}])
    os.remove(_src(ws, "Trip", "a.jpg"))                                # gone by other means
    merge._run_locked_workflow("plan", str(ws))
    plan = json.load(open(merge.merge_plan_path(str(ws))))
    a = next(r for d in plan["destinations"].values() for r in d["files"])
    assert a["disposition"] == "blocked" and "no earlier merge" in a["blocked_reason"]


@pytest.mark.parametrize("case", ["its place no longer holds it", "no merge moved it"])
@pytest.mark.spec("RUL-replan_block_names_why", test="TST-merge_execute-a_re_plan_block_says_why_in_the_plan_and_on_screen")
def test_a_re_plan_block_says_why_in_the_plan_and_on_screen(tmp_path, capsys, case):
    """A photo gone from the workspace that the re-plan cannot account for blocks it, and the plan's blockers and
    what `merge plan` prints say why — not only the photo's record in the plan."""
    if case == "no merge moved it":
        ws, lib = _ws(tmp_path, [{"fp": "A", "dest": "Trip", "final_name": "a.jpg"}])
        os.remove(_src(ws, "Trip", "a.jpg"))                            # gone by other means
        why = "no earlier merge plan placed it in the library"
    else:
        ws, lib = _ws(tmp_path, [{"fp": "A", "dest": "Trip", "final_name": "a.jpg"},
                                 {"fp": "B", "dest": "Trip", "final_name": "b.jpg"}],
                      library_files=[{"fp": "FAIL", "dest": "Trip", "name": "b.jpg"}])
        assert merge._run_locked_workflow("plan", str(ws)) == 2
        assert merge._run_locked_workflow("execute", str(ws)) == 3
        with open(os.path.join(str(lib), "Trip", "a.jpg"), "wb") as f:
            f.write(_fp_bytes("X"))                                      # a.jpg's place no longer holds it
        why = f"the library place an earlier merge plan gave it ({os.path.join(str(lib), 'Trip', 'a.jpg')}) " \
              "no longer holds it"
    capsys.readouterr()
    assert merge._run_locked_workflow("plan", str(ws)) == 2
    out = capsys.readouterr()
    plan = json.load(open(merge.merge_plan_path(str(ws))))
    assert any("Trip/a.jpg" in b and why in b for b in plan["blockers"]), plan["blockers"]
    assert why in out.out + out.err, out


@pytest.mark.spec("RUL-merge_replan_any_time", test="TST-merge_execute-re_plan_after_failed_is_allowed")
def test_re_plan_after_failed_is_allowed(tmp_path):
    # An all-blocked run is `failed` — nothing was placed, every source is still in by-dest. Like a
    # `rejected` run, it moved nothing, so re-planning is allowed (no moved file to drop from the log);
    # the re-plan refusal applies only to runs that actually moved files (partial/success).
    ws, lib = _ws(tmp_path, [{"fp": "A", "dest": "Trip", "final_name": "a.jpg"}],
                  library_files=[{"fp": "FAIL", "dest": "Trip", "name": "a.jpg"}])
    assert merge._run_locked_workflow("plan", str(ws)) == 2   # a blocker: ends as a refusal (RUL-blocked_plan_ends_refused)
    assert merge._run_locked_workflow("execute", str(ws)) == 3          # the only file blocked -> failed
    assert _summary(ws)["status"] == "failed"
    assert os.path.exists(_src(ws, "Trip", "a.jpg"))                    # nothing moved — source remains
    assert merge._run_locked_workflow("plan", str(ws)) == 2             # re-plan allowed


def test_re_plan_allowed_when_no_partial(tmp_path):
    # A plan with no prior summary re-plans fine.
    ws, lib = _ws(tmp_path, [{"fp": "A", "dest": "Trip", "final_name": "a.jpg"}])
    assert merge._run_locked_workflow("plan", str(ws)) == 0
    assert merge._run_locked_workflow("plan", str(ws)) == 0


def test_a_re_plan_after_a_crash_before_the_seal_finishes_and_seals(tmp_path, monkeypatch):
    # A crash between the summary write (status=success) and the seal leaves the workspace unsealed
    # with every photo already moved. A re-plan carries them all forward, so the merge that follows
    # writes a log naming every photo, then seals.
    ws, lib = _ws(tmp_path, [{"fp": "A", "dest": "Trip", "final_name": "a.jpg"}])
    real = merge.MergeWorkflow._finalize_terminal
    monkeypatch.setattr(merge.MergeWorkflow, "_finalize_terminal", lambda *a, **k: None)  # skip the seal
    assert merge._run_locked_workflow("plan", str(ws)) == 0
    assert merge._run_locked_workflow("execute", str(ws)) == 0       # success, but crashed before seal
    assert _summary(ws)["status"] == "success" and not utils.is_sealed(str(ws))
    monkeypatch.setattr(merge.MergeWorkflow, "_finalize_terminal", real)
    assert merge._run_locked_workflow("plan", str(ws)) == 0
    assert merge._run_locked_workflow("execute", str(ws)) == 0
    assert utils.is_sealed(str(ws))
    log = json.loads(open(_ctl(ws, "photos-35-merge-log.json")).read())
    assert log["photos"]["A"]["library_path"] == os.path.join(str(lib), "Trip", "a.jpg")


@pytest.mark.spec("RUL-sealed_refuses", test="TST-merge_execute-sealed_workspace_rerun_hardstops")
def test_sealed_workspace_rerun_hardstops(tmp_path):
    ws, lib = _ws(tmp_path, [{"fp": "A", "dest": "Trip", "final_name": "a.jpg"}])
    assert merge._run_locked_workflow("plan", str(ws)) == 0
    assert merge._run_locked_workflow("execute", str(ws)) == 0
    assert utils.is_sealed(str(ws))
    before = open(os.path.join(str(lib), "Trip", "a.jpg"), "rb").read()
    assert merge._run_locked_workflow("execute", str(ws)) == 2          # sealed -> preflight blocker
    assert open(os.path.join(str(lib), "Trip", "a.jpg"), "rb").read() == before   # untouched


@pytest.mark.spec("RUL-merge_is_terminal", "RUL-library_takes_many_workspaces", test="TST-merge_execute-library_takes_a_second_workspace_after_the_first_is_sealed")
def test_library_takes_a_second_workspace_after_the_first_is_sealed(tmp_path):
    """Merge ends its workspace — sealed, it refuses to merge again — and more media reaches the same
    library through a fresh workspace."""
    ws1, lib = _ws(tmp_path, [{"fp": "A", "dest": "Trip", "final_name": "a.jpg"}], name="w1")
    assert merge._run_locked_workflow("plan", str(ws1)) == 0
    assert merge._run_locked_workflow("execute", str(ws1)) == 0
    assert utils.is_sealed(str(ws1))
    assert merge._run_locked_workflow("plan", str(ws1)) == 2

    ws2, _ = _ws(tmp_path, [{"fp": "B", "dest": "Trip", "final_name": "b.jpg"}], name="w2")
    cfg_p = ws2 / ".photos-ingest" / "photos-00-config.json"
    cfg = json.loads(cfg_p.read_text())
    cfg["merge"]["library_root"] = str(lib)
    cfg_p.write_text(json.dumps(cfg))
    assert merge._run_locked_workflow("plan", str(ws2)) == 0
    assert merge._run_locked_workflow("execute", str(ws2)) == 0
    assert utils.is_sealed(str(ws2))
    assert sorted(os.listdir(os.path.join(str(lib), "Trip"))) == ["a.jpg", "b.jpg"]


@pytest.mark.spec("RUL-package_contents", test="TST-merge_execute-reseal_archives_the_control_directory_with_merges_records")
def test_reseal_archives_the_control_directory_with_merges_records(tmp_path):
    """Merge's re-seal makes the package again: the whole control directory, merge's own records among
    it, listed in photos-35's manifest and archived with it."""
    import tarfile
    ws, lib = _ws(tmp_path, [{"fp": "A", "dest": "Trip", "final_name": "a.jpg"}])
    assert merge._run_locked_workflow("plan", str(ws)) == 0
    assert merge._run_locked_workflow("execute", str(ws)) == 0
    ctl = ws / ".photos-ingest"
    manifest = json.loads((ctl / "photos-35-archive-manifest.json").read_text())
    assert {"photos-31-merge-summary.json", "photos-35-merge-log.json", "photos-26-complete-log.json"} <= set(manifest["contents"])
    with tarfile.open(ctl / "photos-35-archive.tar.gz") as tar:
        names = set(tar.getnames())
    assert names == {rec["path"] for rec in manifest["contents"].values()} | {".photos-ingest/photos-35-archive-manifest.json"}


def _changed_under_new_engine(p, now):
    """A photo prep fingerprinted as p["fp"] whose file another ImageMagick now reads as `now`."""
    return dict(p, fp=now, content_hash=json.dumps({"status": "valid", "value": p["fp"]}))


@pytest.mark.spec("RUL-merge_rechecks_under_new_engine", "BLD-merge_engine_recheck",
                  "RUL-merge_merges_changed_fingerprint", "RUL-changed_fingerprint_mapping_recorded",
                  "BLD-fingerprint_map", "RUL-phase_writes_own_records", "BLD-merge_success_sequence",
                  test="TST-merge_execute-a_new_fingerprint_is_merged_and_mapped_in_merges_package")
def test_a_new_fingerprint_is_merged_and_mapped_in_merges_package(tmp_path, monkeypatch):
    """A photo whose fingerprint another ImageMagick changed, the file finalize recorded, is merged; merge's package
    maps its old value to its new, with both versions and where it was and is, beside the records keyed by the old —
    which, geotag's among them, are copied or read, never rewritten. A photo whose value held maps nothing."""
    import tarfile
    ws, lib = _ws(tmp_path, [_changed_under_new_engine({"fp": "A", "dest": "Trip", "final_name": "a.jpg"}, "A2"),
                             {"fp": "B", "dest": "Trip", "final_name": "b.jpg"}])
    monkeypatch.setattr(merge, "get_imagemagick_version", lambda: "newer")
    complete_before = open(_ctl(ws, "photos-26-complete-log.json"), "rb").read()
    finalized_before = open(_ctl(ws, "photos-26-finalized-media.json"), "rb").read()
    assert merge._run_locked_workflow("plan", str(ws)) == 0
    assert merge._run_locked_workflow("execute", str(ws)) == 0
    assert utils.is_sealed(str(ws))
    a_lib = os.path.join(str(lib), "Trip", "a.jpg")
    fmap = json.loads(open(_ctl(ws, "photos-35-fingerprint-map.json")).read())
    assert fmap["photos"] == {"A2": {"was": {"content_fingerprint": "A", "image_engine_version": None},
                                     "now": {"content_fingerprint": "A2", "image_engine_version": "newer"},
                                     "from": "6-photos-by-dest/Trip/a.jpg", "library_path": a_lib}}
    log = json.loads(open(_ctl(ws, "photos-35-merge-log.json")).read())
    assert log["photos"]["A"]["library_path"] == a_lib and "A2" not in log["photos"]    # keyed by prep's value
    assert open(_ctl(ws, "photos-26-complete-log.json"), "rb").read() == complete_before
    assert open(_ctl(ws, "photos-26-finalized-media.json"), "rb").read() == finalized_before
    manifest = json.loads(open(_ctl(ws, "photos-35-archive-manifest.json")).read())
    assert "photos-35-fingerprint-map.json" in manifest["contents"]
    with tarfile.open(_ctl(ws, "photos-35-archive.tar.gz")) as tar:
        assert ".photos-ingest/photos-35-fingerprint-map.json" in tar.getnames()


@pytest.mark.parametrize("journalled", [True, False], ids=["journalled", "never_journalled"])
@pytest.mark.spec("BLD-fingerprint_map", "BLD-changed_fingerprint_mapped", "RUL-replan_carries_placed", "RUL-merge_merges_changed_fingerprint",
                  "RUL-changed_fingerprint_mapping_recorded",
                  test="TST-merge_execute-a_photo_merged_under_a_new_fingerprint_is_carried_forward_by_it")
def test_a_photo_merged_under_a_new_fingerprint_is_carried_forward_by_it(tmp_path, monkeypatch, journalled):
    """A partial merge moved a photo under its new value; the re-plan finds it in the library — by the bytes the
    journal recorded placing, or, the move never journalled, by that new value — carries it forward, and the merge
    that finishes maps it."""
    ws, lib = _ws(tmp_path, [_changed_under_new_engine({"fp": "A", "dest": "Trip", "final_name": "a.jpg"}, "A2"),
                             {"fp": "B", "dest": "Trip", "final_name": "b.jpg"}],
                  library_files=[{"fp": "FAIL", "dest": "Trip", "name": "b.jpg"}])
    monkeypatch.setattr(merge, "get_imagemagick_version", lambda: "newer")
    assert merge._run_locked_workflow("plan", str(ws)) == 2
    pid = json.load(open(merge.merge_plan_path(str(ws))))["plan_id"]
    assert merge._run_locked_workflow("execute", str(ws)) == 3          # a moved, b blocked
    assert not os.path.exists(_src(ws, "Trip", "a.jpg"))
    if not journalled:
        os.remove(utils.journal_path(str(ws), pid))                     # the confirmation never written
    open(os.path.join(str(lib), "Trip", "b.jpg"), "wb").write(_fp_bytes("OTHER"))
    assert merge._run_locked_workflow("plan", str(ws)) == 0
    [a] = [f for d in json.loads(open(_ctl(ws, "photos-30-merge-plan.json")).read())["destinations"].values()
           for f in d["files"] if f["content_fingerprint"] == "A"]
    assert a["carried_from_plan"] and a["engine_mapping"]["now"]["content_fingerprint"] == "A2"
    assert merge._run_locked_workflow("execute", str(ws)) == 0
    fmap = json.loads(open(_ctl(ws, "photos-35-fingerprint-map.json")).read())
    assert list(fmap["photos"]) == ["A2"]


@pytest.mark.spec("RUL-placed_bytes_confirm_place", "BLD-placed_bytes_journalled", "RUL-retaken_fingerprint_same_photo",
                  "RUL-replan_carries_placed", "RUL-resume_rechecks_library",
                  test="TST-merge_execute-a_photo_placed_before_imagemagick_changed_is_confirmed_by_its_bytes")
def test_a_photo_placed_before_imagemagick_changed_is_confirmed_by_its_bytes(tmp_path, monkeypatch):
    """A partial merge placed a.jpg; ImageMagick is then upgraded, and the new version reads every photo to another
    value. The re-plan confirms a.jpg's place by the bytes the execute recorded placing there — not by a fingerprint
    the new version takes differently — carries it forward, and the merge that finishes seals."""
    ws, lib = _ws(tmp_path, [{"fp": "A", "dest": "Trip", "final_name": "a.jpg"},
                             {"fp": "B", "dest": "Trip", "final_name": "b.jpg"}],
                  library_files=[{"fp": "FAIL", "dest": "Trip", "name": "b.jpg"}])
    version = {"now": "older"}
    monkeypatch.setattr(merge, "get_imagemagick_version", lambda: version["now"])
    assert merge._run_locked_workflow("plan", str(ws)) == 2
    first = json.load(open(merge.merge_plan_path(str(ws))))["plan_id"]
    assert merge._run_locked_workflow("execute", str(ws)) == 3          # a.jpg placed, b.jpg blocked
    a_lib = os.path.join(str(lib), "Trip", "a.jpg")
    journal = json.load(open(utils.journal_path(str(ws), first)))
    assert journal["placed_sha256"] == {"6-photos-by-dest/Trip/a.jpg": utils.sha256_file(a_lib)}

    by_content = merge.MergeWorkflow._fingerprint_library_file

    def upgraded(self, abs_path):                                       # the new version: every value another
        r = by_content(self, abs_path)
        return dict(r, value=r["value"] + "'") if r.get("value") else r
    version["now"] = "newer"
    monkeypatch.setattr(merge.MergeWorkflow, "_fingerprint_library_file", upgraded)
    with open(os.path.join(str(lib), "Trip", "b.jpg"), "wb") as f:
        f.write(_fp_bytes("OTHER"))                                      # b.jpg's own blocker cleared
    assert merge._run_locked_workflow("plan", str(ws)) == 0
    plan = json.load(open(merge.merge_plan_path(str(ws))))
    assert not plan["blockers"], plan["blockers"]
    a = next(r for d in plan["destinations"].values() for r in d["files"] if r["by_dest_source"].endswith("a.jpg"))
    assert a["carried_from_plan"] == first and a["placed_sha256"] == utils.sha256_file(a_lib)
    assert merge._run_locked_workflow("execute", str(ws)) == 0
    assert utils.is_sealed(str(ws))
    log = json.loads(open(_ctl(ws, "photos-35-merge-log.json")).read())
    assert log["photos"]["A"]["library_path"] == a_lib


@pytest.mark.spec("RUL-merge_merges_changed_fingerprint", "BLD-changed_fingerprint_mapped", "BLD-merge_move",
                  test="TST-merge_execute-a_mapped_photo_whose_place_holds_it_at_execute_is_already_present")
def test_a_mapped_photo_whose_place_holds_it_at_execute_is_already_present(tmp_path, monkeypatch):
    """A photo merged under its new value whose place is found taken at execute by the very same file is compared with
    it by that new value: already present, its workspace copy removed, the merge whole — never blocked as other
    content for a value the library's file was not fingerprinted under."""
    ws, lib = _ws(tmp_path, [_changed_under_new_engine({"fp": "A", "dest": "Trip", "final_name": "a.jpg"}, "A2")])
    monkeypatch.setattr(merge, "get_imagemagick_version", lambda: "newer")
    assert merge._run_locked_workflow("plan", str(ws)) == 0
    a_lib = os.path.join(str(lib), "Trip", "a.jpg")
    os.makedirs(os.path.dirname(a_lib), exist_ok=True)
    shutil.copyfile(_src(ws, "Trip", "a.jpg"), a_lib)                    # the place taken by the same bytes since
    assert merge._run_locked_workflow("execute", str(ws)) == 0
    assert _summary(ws)["totals"]["already_present"] == 1
    assert not os.path.exists(_src(ws, "Trip", "a.jpg")) and utils.is_sealed(str(ws))


def _rows(db, skip=()):
    """{table: sorted rows} of every table in the SQLite file `db` but those in `skip`."""
    import sqlite3
    conn = sqlite3.connect(db)
    try:
        tables = [r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")]
        return {t: sorted(map(repr, conn.execute(f"SELECT * FROM {t}"))) for t in tables if t not in skip}
    finally:
        conn.close()


@pytest.mark.spec("RUL-database_regions_disjoint", test="TST-merge_execute-merge_writes_only_its_own_part_of_the_database")
def test_merge_writes_only_its_own_part_of_the_database(tmp_path):
    """Merge writes the library-file fingerprint cache and nothing else of the database: prep's and
    geotag's rows stand exactly as they were."""
    import sqlite3
    import photos_2_geotag as geotag
    ws, lib = _ws(tmp_path, [{"fp": "NEW", "dest": "Trip", "final_name": "ts.jpg"}],
                  library_files=[{"fp": "OLD", "dest": "Trip", "name": "ts.jpg"}])
    utils.WorkspaceCache(str(ws)).close()
    geotag.GeotagCache(str(ws)).close()
    db = os.path.join(str(ws), ".photos-ingest", "photos-00-ingest.db")
    conn = sqlite3.connect(db)
    conn.execute("INSERT INTO original_values VALUES ('NEW', '6-photos-by-dest/Trip/ts.jpg', '{}', 't', '[]')")
    conn.execute("INSERT INTO meta VALUES ('a-prep-row', 'v')")
    conn.commit()
    conn.close()
    # The record of the workspace's state is every execution's to rewrite (RUL-execution_records_state): left out.
    skip = ("library_fingerprint_cache", "workspace_record")

    def others():
        rows = _rows(db, skip=skip)
        rows["meta"] = [r for r in rows["meta"] if "workspace_record_id" not in r]
        return rows
    before = others()
    assert merge._run_locked_workflow("plan", str(ws)) == 0
    assert merge._run_locked_workflow("execute", str(ws)) == 0
    assert others() == before
    assert _rows(db)["library_fingerprint_cache"]                      # its own part: written


@pytest.mark.spec("RUL-image_untouched_by_other_phase",
                  test="TST-merge_execute-merge_leaves_the_other_phases_database_images_as_they_were")
def test_merge_leaves_the_other_phases_database_images_as_they_were(tmp_path):
    """A whole merge writes its own image of the database and leaves prep's and geotag's, byte for byte, as
    those phases left them."""
    ws, lib = _ws(tmp_path, [{"fp": "A", "dest": "Trip", "final_name": "a.jpg"}])
    images = {"photos-15-prep-ingest.db": b"prep's image", "photos-26-geotag-ingest.db": b"geotag's image"}
    stats = {}
    for name, data in images.items():
        with open(_ctl(ws, name), "wb") as f:
            f.write(data)
        stats[name] = (os.stat(_ctl(ws, name)).st_mtime_ns, os.stat(_ctl(ws, name)).st_ino)
    assert merge._run_locked_workflow("plan", str(ws)) == 0
    assert merge._run_locked_workflow("dry-run", str(ws)) == 0
    assert merge._run_locked_workflow("execute", str(ws)) == 0
    with open(_ctl(ws, "photos-35-merge-ingest.db"), "rb") as f:
        assert f.read(16) == b"SQLite format 3\x00"                    # its own image: written
    for name, data in images.items():
        assert open(_ctl(ws, name), "rb").read() == data, name
        assert (os.stat(_ctl(ws, name)).st_mtime_ns, os.stat(_ctl(ws, name)).st_ino) == stats[name], name


@pytest.mark.spec("RUL-control_directory_fixed",
                  test="TST-merge_execute-merge_keeps_its_records_in_the_one_control_directory")
def test_merge_keeps_its_records_in_the_one_control_directory(tmp_path):
    """Where merge reads and writes its records does not follow the configuration: with the default folders, or
    with every folder renamed, merge plans and merges from the records geotag left in `.photos-ingest/` and writes
    its own there — the seal among them — and nowhere else, in the workspace or in the library."""
    import copy
    renamed = {role: f"x-{name}" for role, name in copy.deepcopy(utils.DEFAULT_FOLDERS).items()}
    records = ("photos-30-merge-plan.json", "photos-31-merge-summary.json", "photos-35-merge-log.json",
               "photos-35-merge-ingest.db", "photos-35-archive-manifest.json", "photos-35-archive.tar.gz",
               "photos-00-sealed.json")
    for name, folders in (("default", None), ("renamed", renamed)):
        ws, lib = _ws(tmp_path, [{"fp": "A", "dest": "Trip", "final_name": "a.jpg"}], name=name, folders=folders)
        utils.CONFIG.clear(); utils.CONFIG.update(utils.default_config())   # a run of its own: nothing read yet
        assert merge._run_locked_workflow("plan", str(ws)) == 0, name
        assert merge._run_locked_workflow("execute", str(ws)) == 0, name
        for rec in records:
            assert (ws / ".photos-ingest" / rec).is_file(), (name, rec)
        plan_id = json.load(open(_ctl(ws, "photos-30-merge-plan.json")))["plan_id"]
        assert (ws / ".photos-ingest" / f"journal-{plan_id}.json").is_file(), name
        assert sorted(os.listdir(ws)) == sorted([".photos-ingest", *(folders.values() if folders else MANAGED)]), name
        outside = [os.path.join(r, n) for r, _d, fs in os.walk(ws) if ".photos-ingest" not in r for n in fs]
        assert outside == [], (name, outside)                      # the photo merged, no record among the folders
        assert sorted(os.listdir(lib)) == [".photos-library", ".photos-merge.lock", "Trip"], name
        assert os.listdir(lib / "Trip") == ["a.jpg"], name


@pytest.mark.spec("RUL-image_never_working_data", test="TST-merge_execute-merge_never_reads_a_database_image_back")
def test_merge_never_reads_a_database_image_back(tmp_path, monkeypatch):
    """No database image is read back as working data: with prep's and geotag's images holding no database at
    all, merge plans, dry-runs and merges whole, opening neither — nor its own, once made, on the runs after."""
    import sqlite3
    ws, lib = _ws(tmp_path, [{"fp": "A", "dest": "Trip", "final_name": "a.jpg"}])
    images = ("photos-15-prep-ingest.db", "photos-26-geotag-ingest.db", "photos-35-merge-ingest.db")
    for name in images[:2]:
        with open(_ctl(ws, name), "wb") as f:
            f.write(b"not a database")
    opened, real_connect = [], sqlite3.connect
    def connect(database, *a, **k):
        opened.append(os.path.basename(str(database).split("?")[0]))
        return real_connect(database, *a, **k)
    monkeypatch.setattr(sqlite3, "connect", connect)
    for command in ("plan", "dry-run", "execute"):
        assert merge._run_locked_workflow(command, str(ws)) == 0, command
    assert _summary(ws)["status"] == "success" and os.path.exists(os.path.join(str(lib), "Trip", "a.jpg"))
    with open(_ctl(ws, images[2]), "rb") as f:
        assert f.read(16) == b"SQLite format 3\x00"                    # its own image: made
    for command in ("plan", "dry-run", "execute"):
        merge._run_locked_workflow(command, str(ws))
    assert "photos-00-ingest.db" in opened and not set(images) & set(opened), opened


@pytest.mark.spec("RUL-snapshot_optional", "RUL-filesystem_agnostic", test="TST-merge_execute-merge_runs_whole_with_no_zfs")
def test_merge_runs_whole_with_no_zfs(tmp_path, monkeypatch):
    """With snapshots off, as they are by default, merge never reaches for a ZFS feature: on a machine with no
    `zfs` at all it plans, dry-runs and merges whole, and seals the workspace."""
    import subprocess
    calls, real = [], subprocess.Popen
    def popen(args, *a, **k):
        argv = args.split() if isinstance(args, str) else list(args)
        if argv and os.path.basename(str(argv[0])) == "zfs":
            calls.append(argv)
            raise FileNotFoundError(2, "No such file or directory", "zfs")
        return real(args, *a, **k)
    monkeypatch.setattr(subprocess, "Popen", popen)
    ws, lib = _ws(tmp_path, [{"fp": "A", "dest": "Trip", "final_name": "a.jpg"}],
                  library_files=[{"fp": "B", "dest": "Trip", "name": "a.jpg"}])
    assert utils.CONFIG["zfs"]["enabled"] is False
    for command in ("plan", "dry-run", "execute"):
        assert merge._run_locked_workflow(command, str(ws)) == 0, command
    assert _summary(ws)["status"] == "success" and utils.is_sealed(str(ws)) and calls == []


@pytest.mark.spec("BLD-merge_carry_forward", "RUL-log_step_names_run",
                  "RUL-nothing_built_from_merge_records",
                  test="TST-merge_execute-nothing_is_built_from_merges_records")
def test_nothing_is_built_from_merges_records(tmp_path):
    """Nothing is built from merge's records: after a merge that left a photo blocked, the next merge plans and
    merges the same — the same plan, the same outcome — whether merge's summary stands as written, is garbled or
    is gone."""
    ws, lib = _ws(tmp_path, [{"fp": "A", "dest": "Trip", "final_name": "a.jpg"},
                             {"fp": "B", "dest": "Trip", "final_name": "b.jpg"}],
                  library_files=[{"fp": "FAIL", "dest": "Trip", "name": "b.jpg"}])
    assert merge._run_locked_workflow("plan", str(ws)) == 2   # a blocker: ends as a refusal (RUL-blocked_plan_ends_refused)
    assert merge._run_locked_workflow("execute", str(ws)) == 3            # b blocked: not sealed, run again
    assert _summary(ws)["status"] == "partial" and not utils.is_sealed(str(ws))

    def plan_body():
        with open(merge.merge_plan_path(str(ws))) as f:
            p = json.load(f)
        return {k: p.get(k) for k in ("destinations", "totals", "blockers", "warnings")}
    runs = []
    for damage in ("as written", "garbled", "gone"):
        if damage == "garbled":
            with open(merge.merge_summary_path(str(ws)), "w") as f:
                f.write("{not a summary")
        elif damage == "gone":
            os.remove(merge.merge_summary_path(str(ws)))
        assert merge._run_locked_workflow("plan", str(ws)) == 2, damage
        plan = plan_body()
        assert merge._run_locked_workflow("execute", str(ws)) == 3, damage
        runs.append((plan, _comparable(_summary(ws))))
    assert runs[0][0]["destinations"] and runs[0] == runs[1] == runs[2]


@pytest.mark.spec("RUL-merged_batch_no_op", test="TST-merge_execute-merging_a_merged_batch_changes_nothing")
def test_merging_a_merged_batch_changes_nothing(tmp_path):
    """A batch merged whole, then merged again — plan, dry-run and execute: every file of the workspace, its
    records among them, and every file of the library stands byte for byte as the first merge left it."""
    ws, lib = _ws(tmp_path, [{"fp": "A", "dest": "Trip", "final_name": "a.jpg"},
                             {"fp": "B", "dest": "Trip", "final_name": "b.jpg"}],
                  library_files=[{"fp": "B", "dest": "Trip", "name": "b.jpg"}])
    assert merge._run_locked_workflow("plan", str(ws)) == 0
    assert merge._run_locked_workflow("execute", str(ws)) == 0
    assert sorted(os.listdir(os.path.join(str(lib), "Trip"))) == ["a.jpg", "b.jpg"]
    ws_before, lib_before = _tree(str(ws)), _tree(str(lib))
    for command in ("plan", "dry-run", "execute"):
        merge._run_locked_workflow(command, str(ws))
        assert _tree(str(ws)) == ws_before, command
        assert _tree(str(lib)) == lib_before, command


@pytest.mark.spec("RUL-one_database", "RUL-library_no_database", "RUL-database_is_record",
                  test="TST-merge_execute-one_database_in_the_workspace_none_in_the_library")
def test_one_database_in_the_workspace_none_in_the_library(tmp_path):
    """After a whole merge the workspace holds one database of record, besides the phase images and
    prep's scratch memo, and the library holds no database at all."""
    ws, lib = _ws(tmp_path, [{"fp": "NEW", "dest": "Trip", "final_name": "ts.jpg"}],
                  library_files=[{"fp": "OLD", "dest": "Trip", "name": "ts.jpg"}])
    assert merge._run_locked_workflow("plan", str(ws)) == 0
    assert merge._run_locked_workflow("execute", str(ws)) == 0

    def sqlite_files(root):
        out = []
        for dp, _dn, fns in os.walk(root):
            for fn in fns:
                with open(os.path.join(dp, fn), "rb") as f:
                    if f.read(16) == b"SQLite format 3\x00":
                        out.append(os.path.relpath(os.path.join(dp, fn), root))
        return sorted(out)
    images = {"photos-15-prep-ingest.db", "photos-26-geotag-ingest.db", "photos-35-merge-ingest.db",
              "photos-00-plan-memo.db"}
    found = sqlite_files(str(ws))
    assert os.path.join(".photos-ingest", "photos-00-ingest.db") in found
    assert {os.path.basename(f) for f in found} - images == {"photos-00-ingest.db"}
    assert sqlite_files(str(lib)) == []


@pytest.mark.spec("RUL-library_not_scanned", test="TST-merge_execute-merge_reads_the_library_only_where_it_places_a_photo")
def test_merge_reads_the_library_only_where_it_places_a_photo(tmp_path, monkeypatch):
    """Merge lists only the folders its photos go to — and the library's top folder, for temporary copies
    a crash of its own left — never walks the library, and fingerprints a library file only where an
    incoming photo's place is taken."""
    ws, lib = _ws(tmp_path, [{"fp": "NEW", "dest": "Trip", "final_name": "ts.jpg"}],
                  library_files=[{"fp": "OLD", "dest": "Trip", "name": "ts.jpg"},
                                 {"fp": "SIB", "dest": "Trip", "name": "sibling.jpg"},
                                 {"fp": "FAR", "dest": "Elsewhere", "name": "far.jpg"}])
    root = str(lib)
    listed, walked, read = [], [], []
    real_listdir, real_walk, real_scandir = os.listdir, os.walk, os.scandir
    real_fp = merge.MergeWorkflow._fingerprint_library_file

    def listdir(p="."):
        if str(p).startswith(root):
            listed.append(os.path.relpath(str(p), root))
        return real_listdir(p)

    def walk(p, *a, **k):
        if str(p).startswith(root):
            walked.append(str(p))
        return real_walk(p, *a, **k)

    def scandir(p="."):
        if str(p).startswith(root):
            walked.append(str(p))
        return real_scandir(p)

    def fp(self, abs_path):
        if abs_path.startswith(root):
            read.append(os.path.relpath(abs_path, root))
        return real_fp(self, abs_path)
    monkeypatch.setattr(os, "listdir", listdir)
    monkeypatch.setattr(os, "walk", walk)
    monkeypatch.setattr(os, "scandir", scandir)
    monkeypatch.setattr(merge.MergeWorkflow, "_fingerprint_library_file", fp)
    assert merge._run_locked_workflow("plan", str(ws)) == 0
    assert merge._run_locked_workflow("execute", str(ws)) == 0
    # The top folder: only for merge's own temporaries, and for a workspace among its folders
    # (RUL-library_outside_every_workspace), each looked at by its name alone.
    assert set(listed) <= {"Trip", "."} and not walked
    assert "Trip/sibling.jpg" not in read and not any(r.startswith("Elsewhere") for r in read)
    assert "Trip/ts.jpg" in read


def _refusals(ws, lib, capsys, monkeypatch):
    """Run every command that refuses a sealed workspace; return {command: (exit, output)}."""
    from cartographer import cli
    monkeypatch.chdir(ws)
    out = {}
    for argv in (["prep", "plan"], ["prep", "dry-run"], ["prep", "execute"],
                 ["geotag", "plan"], ["geotag", "execute"], ["geotag", "finalize"],
                 ["merge", "plan"], ["merge", "dry-run"], ["merge", "execute"],
                 ["merge", "init-library", str(lib)]):
        try:
            rc = cli.main(argv)
        except SystemExit as e:
            rc = e.code
        cap = capsys.readouterr()
        out[" ".join(argv[:2])] = (rc, cap.out + cap.err)
    return out


@pytest.mark.spec("RUL-sealed_new_dump_warned", "RUL-sealed_new_dump_left", test="TST-merge_execute-a_folder_dropped_into_a_sealed_workspace_is_pointed_out_and_left")
def test_a_folder_dropped_into_a_sealed_workspace_is_pointed_out_and_left(tmp_path, capsys, monkeypatch):
    """A dump copied in as a whole folder lands at the top level: every command refusing the sealed
    workspace says a new dump is likely there, and leaves the folder exactly as it was."""
    ws, _lib = _ws(tmp_path, [{"fp": "A", "dest": "Trip", "final_name": "a.jpg"}])
    assert merge._run_locked_workflow("plan", str(ws)) == 0
    assert merge._run_locked_workflow("execute", str(ws)) == 0
    dump = ws / "DCIM"
    dump.mkdir()
    (dump / "IMG_0001.JPG").write_bytes(b"card")
    for cmd, (rc, text) in _refusals(ws, _lib, capsys, monkeypatch).items():
        assert rc == 2, cmd
        assert "new dump" in text.lower(), cmd
    assert os.listdir(dump) == ["IMG_0001.JPG"] and (dump / "IMG_0001.JPG").read_bytes() == b"card"


@pytest.mark.spec("RUL-sealed_new_dump_warned", test="TST-merge_execute-a_hidden_file_alone_is_not_a_new_dump")
def test_a_hidden_file_alone_is_not_a_new_dump(tmp_path, capsys, monkeypatch):
    """A hidden file at the top level, such as one a file browser leaves, is not a dump: no command
    refusing the sealed workspace warns of one."""
    ws, _lib = _ws(tmp_path, [{"fp": "A", "dest": "Trip", "final_name": "a.jpg"}])
    assert merge._run_locked_workflow("plan", str(ws)) == 0
    assert merge._run_locked_workflow("execute", str(ws)) == 0
    (ws / ".DS_Store").write_bytes(b"x")
    for cmd, (rc, text) in _refusals(ws, _lib, capsys, monkeypatch).items():
        assert rc == 2, cmd
        assert "new dump" not in text.lower(), cmd


@pytest.mark.spec("RUL-library_creates_only_placements", test="TST-merge_execute-merge_creates_in_the_library_only_what_it_places")
def test_merge_creates_in_the_library_only_what_it_places(tmp_path):
    """Beyond its mark and its lock, a merge leaves in the library only the photos it placed and the
    folders they went into — no record, cache, temporary copy or database of its own."""
    ws, lib = _ws(tmp_path, [{"fp": "A", "dest": "Trip", "final_name": "a.jpg"},
                             {"fp": "B", "dest": "Spain/Madrid", "final_name": "b.jpg"}])
    assert merge._run_locked_workflow("plan", str(ws)) == 0
    assert merge._run_locked_workflow("execute", str(ws)) == 0
    found = set()
    for dp, dns, fns in os.walk(str(lib)):
        for n in dns + fns:
            found.add(os.path.relpath(os.path.join(dp, n), str(lib)))
    found -= {".photos-library", ".photos-merge.lock"}
    assert found == {"Trip", os.path.join("Trip", "a.jpg"), "Spain", os.path.join("Spain", "Madrid"),
                     os.path.join("Spain", "Madrid", "b.jpg")}


@pytest.mark.spec("RUL-failure_never_done", test="TST-merge_execute-failed_placement_is_done_by_the_next_run")
def test_failed_placement_is_done_by_the_next_run(tmp_path, monkeypatch):
    """A placement that failed is never recorded as done: once its cause is gone, running execute again
    places the photo and the run succeeds."""
    _force_cross_fs(monkeypatch)
    ws, lib = _ws(tmp_path, [{"fp": "A", "dest": "Trip", "final_name": "a.jpg"}])
    assert merge._run_locked_workflow("plan", str(ws)) == 0
    with monkeypatch.context() as m:
        m.setattr(utils.shutil, "copyfile", lambda src, dst: open(dst, "wb").write(b"FP=TORN"))
        assert merge._run_locked_workflow("execute", str(ws)) == 3      # torn copy -> blocked
    assert _summary(ws)["totals"]["blocked"] == 1
    assert merge._run_locked_workflow("execute", str(ws)) == 0          # the next run does it
    assert open(os.path.join(str(lib), "Trip", "a.jpg"), "rb").read() == _fp_bytes("A")
    assert not os.path.exists(_src(ws, "Trip", "a.jpg"))
    assert _summary(ws)["totals"]["blocked"] == 0


@pytest.mark.spec("RUL-merge_snapshots_library", test="TST-merge_execute-merge_snapshots_the_workspace_and_the_library")
@pytest.mark.parametrize("datasets, expected", [(("ws", "lib"), ["ws", "lib"]),     # both, each its own
                                                (("pool", "pool"), ["pool"]),        # one dataset: one snapshot
                                                (("ws", None), ["ws"])])             # library not snapshottable
@pytest.mark.parametrize("required", [False, True], ids=["optional", "required"])
def test_merge_snapshots_the_workspace_and_the_library(tmp_path, monkeypatch, datasets, expected, required):
    """Merge snapshots the workspace — it removes what it places from there — and the library beside
    it where the library can be snapshotted; a library that cannot be only narrows the snapshot, with a
    warning, and the merge proceeds — snapshots required or not."""
    ws, lib = _ws(tmp_path, [{"fp": "A", "dest": "Trip", "final_name": "a.jpg"}])
    taken = _zfs(monkeypatch, ws, datasets=datasets, required=required)
    assert merge._run_locked_workflow("plan", str(ws)) == 0
    assert merge._run_locked_workflow("execute", str(ws)) == 0
    assert taken == expected
    assert os.path.exists(os.path.join(str(lib), "Trip", "a.jpg"))


@pytest.mark.spec("RUL-no_library_only_snapshot", test="TST-merge_execute-merge_takes_no_snapshot_of_the_library_alone")
@pytest.mark.parametrize("datasets, fail", [((None, "lib"), ()),          # workspace not snapshottable
                                            (("ws", "lib"), {"ws"})])    # workspace snapshot fails
def test_merge_takes_no_snapshot_of_the_library_alone(tmp_path, monkeypatch, capsys, datasets, fail):
    """Without the workspace's snapshot, merge takes none of the library either — rolled back alone it
    would lose the photos merge removed from the workspace. Not required, the merge warns that it has no
    rollback point, and proceeds."""
    ws, lib = _ws(tmp_path, [{"fp": "A", "dest": "Trip", "final_name": "a.jpg"}])
    taken = _zfs(monkeypatch, ws, datasets=datasets, fail=fail)
    assert merge._run_locked_workflow("plan", str(ws)) == 0
    assert merge._run_locked_workflow("execute", str(ws)) == 0
    assert "lib" not in taken
    assert "no rollback point" in capsys.readouterr().err
    assert os.path.exists(os.path.join(str(lib), "Trip", "a.jpg"))


# --- a photo with no fingerprint (RUL-unfingerprinted_photo_stops_merge) -------

_NO_FP = json.dumps({"status": "failed", "value": None, "error": "unreadable"})


@pytest.mark.parametrize("command", ["plan", "execute"])
@pytest.mark.spec("RUL-unfingerprinted_photo_stops_merge", test="TST-merge_execute-a_photo_without_a_fingerprint_stops_merge")
def test_a_photo_without_a_fingerprint_stops_merge(tmp_path, capsys, command):
    """A photo in photos by destination that the handoff records with no content fingerprint has no identity
    to merge by — none to find it in the library with, nor to carry it forward once moved: merge refuses to plan
    or execute, naming it, and nothing in the workspace or the library is changed."""
    ws, lib = _ws(tmp_path, [{"fp": "A", "dest": "Trip", "final_name": "a.jpg"},
                             {"fp": "B", "dest": "Trip", "final_name": "b.jpg", "content_hash": _NO_FP}])
    by_dest, library = _tree(str(ws / "6-photos-by-dest")), _tree(str(lib))
    capsys.readouterr()
    assert merge._run_locked_workflow(command, str(ws)) == 2
    text = "".join(capsys.readouterr())
    assert "6-photos-by-dest/Trip/b.jpg" in text and "no content fingerprint" in text, text
    assert "Trip/a.jpg" not in text.split("no content fingerprint")[1].split("\n")[0]   # only b.jpg is named
    assert not os.path.exists(merge.merge_plan_path(str(ws)))
    assert _tree(str(ws / "6-photos-by-dest")) == by_dest and _tree(str(lib)) == library


@pytest.mark.spec("RUL-unfingerprinted_photo_stops_merge",
                  test="TST-merge_execute-a_file_without_a_fingerprint_elsewhere_does_not_stop_merge")
def test_a_file_without_a_fingerprint_elsewhere_does_not_stop_merge(tmp_path):
    """Only photos by destination are merged: a file the handoff records with no fingerprint in another folder
    — one geotag left out — does not stop merge."""
    ws, lib = _ws(tmp_path, [{"fp": "A", "dest": "Trip", "final_name": "a.jpg"}])
    ctl = ws / ".photos-ingest"
    ho = json.loads((ctl / "photos-11-handoff.json").read_text())
    ho["files"].append({"relative_path": "2-missing-metadata/x.jpg", "folder_class": "2-missing-metadata",
                        "media_class": "image", "content_hash": _NO_FP})
    (ws / "2-missing-metadata" / "x.jpg").write_bytes(b"x")
    (ctl / "photos-11-handoff.json").write_text(json.dumps(ho))
    p24 = json.loads((ctl / "photos-24-executable-plan.json").read_text())
    p24["depends_on"]["handoff"]["content_fingerprint"] = utils.handoff_content_fingerprint(ho)
    (ctl / "photos-24-executable-plan.json").write_text(json.dumps(p24))
    finalized = json.loads((ctl / "photos-26-finalized-media.json").read_text())      # as finalize would have found it
    finalized["handoff_content_fingerprint"] = utils.handoff_content_fingerprint(ho)
    (ctl / "photos-26-finalized-media.json").write_text(json.dumps(finalized))
    assert merge._run_locked_workflow("plan", str(ws)) == 0
    assert merge._run_locked_workflow("execute", str(ws)) == 0
    assert os.path.exists(os.path.join(str(lib), "Trip", "a.jpg"))


# --- the same picture in other bytes (RUL-same_pixels_other_file_blocks) -----------

@pytest.mark.spec("RUL-same_pixels_other_file_blocks", "RUL-same_pixels_both_named",
                  test="TST-merge_execute-the_same_picture_with_other_metadata_blocks_and_both_stay")
def test_the_same_picture_with_other_metadata_blocks_and_both_stay(tmp_path):
    """The library holds the incoming photo's pixels in other bytes — the same picture without the time and
    position geotag wrote, say. Neither is removed: the photo is blocked, the block naming both files with their
    sizes and saying they hold the same picture with different metadata; the rest is merged."""
    ws, lib = _ws(tmp_path, [{"fp": "A", "dest": "Trip", "final_name": "a.jpg"},
                             {"fp": "B", "dest": "Trip", "final_name": "b.jpg"}],
                  library_files=[{"fp": "A", "dest": "Trip", "name": "a.jpg", "meta": b"no time, no position"}])
    src, held = _src(ws, "Trip", "a.jpg"), os.path.join(str(lib), "Trip", "a.jpg")
    src_bytes, held_bytes = open(src, "rb").read(), open(held, "rb").read()
    assert merge._run_locked_workflow("plan", str(ws)) == 2   # a blocker: ends as a refusal (RUL-blocked_plan_ends_refused)
    plan = json.load(open(merge.merge_plan_path(str(ws))))
    a = next(r for d in plan["destinations"].values() for r in d["files"] if r["by_dest_source"].endswith("a.jpg"))
    same = {"by_dest_path": "6-photos-by-dest/Trip/a.jpg", "by_dest_size": len(src_bytes),
            "library_path": held, "library_size": len(held_bytes)}
    assert a["disposition"] == "blocked" and a["library_match"] == "pixels" and a["same_picture"] == same
    assert a["content_fingerprint"] == "A"
    [b] = [b for b in plan["blockers"] if "a.jpg" in b]
    assert "6-photos-by-dest/Trip/a.jpg" in b and held in b and "same picture with different metadata" in b
    assert str(len(src_bytes)) in b and str(len(held_bytes)) in b
    assert plan["totals"]["blocked"] == 1 and plan["totals"]["already_present"] == 0

    assert merge._run_locked_workflow("execute", str(ws)) == 3
    assert open(src, "rb").read() == src_bytes and open(held, "rb").read() == held_bytes   # neither removed
    assert os.path.exists(os.path.join(str(lib), "Trip", "b.jpg"))
    s = _summary(ws)
    entry = next(f for f in s["destinations"]["Trip"]["files"] if f["by_dest_path"].endswith("a.jpg"))
    assert entry["same_picture"] == same and "same picture" in entry["blocked_reason"]
    assert not entry["removed_from_by_dest"] and not utils.is_sealed(str(ws))


@pytest.mark.spec("RUL-same_pixels_other_file_blocks", "RUL-collision_same_content",
                  test="TST-merge_execute-a_byte_identical_library_copy_makes_the_photo_already_present")
def test_a_byte_identical_library_copy_makes_the_photo_already_present(tmp_path):
    """Only a library file that is the incoming photo byte for byte makes it already present: the plan says so,
    and its workspace copy is removed."""
    ws, lib = _ws(tmp_path, [{"fp": "A", "dest": "Trip", "final_name": "a.jpg"}],
                  library_files=[{"fp": "A", "dest": "Trip", "name": "a.jpg"}])
    assert merge._run_locked_workflow("plan", str(ws)) == 0
    [a] = [r for d in json.load(open(merge.merge_plan_path(str(ws))))["destinations"].values() for r in d["files"]]
    assert a["disposition"] == "already_present" and a["library_match"] == "bytes" and "same_picture" not in a
    assert merge._run_locked_workflow("execute", str(ws)) == 0
    assert not os.path.exists(_src(ws, "Trip", "a.jpg"))


@pytest.mark.parametrize("when", ["planned_already_present", "found_at_the_place", "appeared_during_the_move"])
@pytest.mark.spec("RUL-same_pixels_other_file_blocks", "RUL-library_file_rechecked_before_removal",
                  test="TST-merge_execute-the_bytes_are_checked_again_before_a_workspace_copy_is_removed")
def test_the_bytes_are_checked_again_before_a_workspace_copy_is_removed(tmp_path, monkeypatch, when):
    """Wherever execute would remove a photo's workspace copy because the library holds it, it compares the two
    files' bytes again first: a library file that came to hold the same picture in other bytes after the plan —
    the planned copy rewritten, or one found at the place, or appearing there during the move — blocks the photo,
    and both files stay."""
    other = _fp_bytes("A") + b"\nno time, no position"
    lib_files = [{"fp": "A", "dest": "Trip", "name": "a.jpg"}] if when == "planned_already_present" else []
    ws, lib = _ws(tmp_path, [{"fp": "A", "dest": "Trip", "final_name": "a.jpg"}], library_files=lib_files)
    assert merge._run_locked_workflow("plan", str(ws)) == 0
    held = os.path.join(str(lib), "Trip", "a.jpg")
    if when == "appeared_during_the_move":
        def raced(src, dst, **k):
            with open(dst, "wb") as f:
                f.write(other)
            raise FileExistsError(dst)
        monkeypatch.setattr(merge, "_move_no_clobber", raced)
    else:
        os.makedirs(os.path.dirname(held), exist_ok=True)
        with open(held, "wb") as f:
            f.write(other)
    assert merge._run_locked_workflow("execute", str(ws)) == 3
    assert open(_src(ws, "Trip", "a.jpg"), "rb").read() == _fp_bytes("A")      # the workspace copy stays
    assert open(held, "rb").read() == other                                   # and the library's
    [f] = _summary(ws)["failures"]
    assert "same picture with different metadata" in f and held in f, f


# --- a hidden entry among the photos (RUL-hidden_among_photos_stops_merge) ----------

@pytest.mark.parametrize("hidden, is_dir", [("Trip/.b.jpg", False), ("Trip/.thumbs", True), (".DS_Store", False)])
@pytest.mark.spec("RUL-hidden_among_photos_stops_merge", test="TST-merge_execute-a_hidden_entry_among_the_photos_stops_merge")
def test_a_hidden_entry_among_the_photos_stops_merge(tmp_path, capsys, hidden, is_dir):
    """A hidden file — a photo named with a leading dot among them — or a hidden folder, even empty, under photos
    by destination is neither merged nor would it be reported, and the workspace sealed around it would keep it:
    merge stops, naming it, and places nothing."""
    ws, lib = _ws(tmp_path, [{"fp": "A", "dest": "Trip", "final_name": "a.jpg"}])
    p = ws / "6-photos-by-dest" / hidden
    if is_dir:
        p.mkdir()
    else:
        p.write_bytes(_fp_bytes("H"))
    capsys.readouterr()
    assert merge._run_locked_workflow("plan", str(ws)) == 2
    text = "".join(capsys.readouterr())
    assert os.path.join("6-photos-by-dest", hidden) in text and "hidden" in text, text
    assert not os.path.exists(merge.merge_plan_path(str(ws)))
    assert not os.path.exists(os.path.join(str(lib), "Trip"))


# --- an earlier place outside the library now named (RUL-earlier_place_in_this_library) ---

def _point_library_at(ws, path):
    cfg_p = ws / ".photos-ingest" / "photos-00-config.json"
    cfg = json.loads(cfg_p.read_text())
    cfg["merge"]["library_root"] = str(path)
    cfg_p.write_text(json.dumps(cfg))


@pytest.mark.spec("RUL-replan_blocks_unaccounted",
                  "RUL-earlier_place_in_this_library",
                  test="TST-merge_execute-a_photo_placed_in_a_library_since_pointed_away_from_blocks")
def test_a_photo_placed_in_a_library_since_pointed_away_from_blocks(tmp_path):
    """A partial merge placed a.jpg in one library; the setting is then pointed at another. a.jpg is not counted
    merged — the workspace would seal naming the new library while it sits in the old: the re-plan blocks it,
    naming the photo, where it is and the library now configured, and the two ways out."""
    ws, lib = _ws(tmp_path, [{"fp": "A", "dest": "Trip", "final_name": "a.jpg"},
                             {"fp": "B", "dest": "Trip", "final_name": "b.jpg"}],
                  library_files=[{"fp": "FAIL", "dest": "Trip", "name": "b.jpg"}])
    assert merge._run_locked_workflow("plan", str(ws)) == 2   # a blocker: ends as a refusal (RUL-blocked_plan_ends_refused)
    assert merge._run_locked_workflow("execute", str(ws)) == 3          # a.jpg placed, b.jpg blocked
    lib2 = tmp_path / "lib2"
    lib2.mkdir()
    utils.write_library_marker(str(lib2))
    _point_library_at(ws, lib2)
    assert merge._run_locked_workflow("plan", str(ws)) == 2
    plan = json.load(open(merge.merge_plan_path(str(ws))))
    a = next(r for d in plan["destinations"].values() for r in d["files"] if r["by_dest_source"].endswith("a.jpg"))
    assert a["disposition"] == "blocked" and not a.get("carried_from_plan")
    reason = a["blocked_reason"]
    for named in ("6-photos-by-dest/Trip/a.jpg", os.path.join(str(lib), "Trip", "a.jpg"), str(lib2),
                  "library_root", os.path.join(str(lib2), "Trip", "a.jpg")):
        assert named in reason, (named, reason)
    assert merge._run_locked_workflow("execute", str(ws)) == 3
    assert not utils.is_sealed(str(ws))
    assert open(os.path.join(str(lib), "Trip", "a.jpg"), "rb").read() == _fp_bytes("A")   # left where it is


@pytest.mark.parametrize("way_out", ["library_pointed_back", "photo_moved_by_hand"])
@pytest.mark.spec("RUL-earlier_place_in_this_library", "RUL-replan_carries_placed",
                  test="TST-merge_execute-either_way_out_of_a_library_pointed_away_from_finishes_the_merge")
def test_either_way_out_of_a_library_pointed_away_from_finishes_the_merge(tmp_path, way_out):
    """Either way out the block names lets the merge finish: point library_root back at the library holding the
    photo, or move the photo by hand to its place in the new library — the re-plan carries it forward from there."""
    ws, lib = _ws(tmp_path, [{"fp": "A", "dest": "Trip", "final_name": "a.jpg"},
                             {"fp": "B", "dest": "Trip", "final_name": "b.jpg"}],
                  library_files=[{"fp": "FAIL", "dest": "Trip", "name": "b.jpg"}])
    assert merge._run_locked_workflow("plan", str(ws)) == 2   # a blocker: ends as a refusal (RUL-blocked_plan_ends_refused)
    first = json.load(open(merge.merge_plan_path(str(ws))))["plan_id"]
    assert merge._run_locked_workflow("execute", str(ws)) == 3
    lib2 = tmp_path / "lib2"
    lib2.mkdir()
    utils.write_library_marker(str(lib2))
    _point_library_at(ws, lib2)
    assert merge._run_locked_workflow("plan", str(ws)) == 2               # a.jpg blocked (above)
    if way_out == "library_pointed_back":
        _point_library_at(ws, lib)
        with open(os.path.join(str(lib), "Trip", "b.jpg"), "wb") as f:
            f.write(_fp_bytes("OLD"))                                      # b.jpg's own blocker cleared
        home = lib
    else:
        (lib2 / "Trip").mkdir()
        os.rename(os.path.join(str(lib), "Trip", "a.jpg"), os.path.join(str(lib2), "Trip", "a.jpg"))
        home = lib2
    assert merge._run_locked_workflow("plan", str(ws)) == 0
    plan = json.load(open(merge.merge_plan_path(str(ws))))
    assert not plan["blockers"], plan["blockers"]
    a = next(r for d in plan["destinations"].values() for r in d["files"] if r["by_dest_source"].endswith("a.jpg"))
    assert a["carried_from_plan"] == first and a["library_target"] == os.path.join(str(home), "Trip", "a.jpg")
    assert merge._run_locked_workflow("execute", str(ws)) == 0
    assert utils.is_sealed(str(ws))
    log = json.loads(open(_ctl(ws, "photos-35-merge-log.json")).read())
    assert log["photos"]["A"]["library_path"] == os.path.join(str(home), "Trip", "a.jpg")


_MERGE_PLAN_READS = [("earlier plan", "plan"), ("set-aside plan", "plan"), ("plan", "dry-run"), ("plan", "execute")]
_MERGE_JOURNAL_READS = [("journal", "execute"), ("journal", "plan"), ("set-aside plan's journal", "plan")]


def _merge_record_to_damage(tmp_path, record):
    """A workspace whose first merge placed a.jpg and blocked b.jpg, and the path of `record` in it: the saved plan
    (read as the earlier plan by a re-plan, or by dry-run and execute), the plan a re-plan set aside as -001, or the
    first plan's journal — read by execute, or by a re-plan while its plan is the saved one or one set aside."""
    ws, lib = _ws(tmp_path, [{"fp": "A", "dest": "Trip", "final_name": "a.jpg"},
                             {"fp": "B", "dest": "Trip", "final_name": "b.jpg"}],
                  library_files=[{"fp": "FAIL", "dest": "Trip", "name": "b.jpg"}])
    assert merge._run_locked_workflow("plan", str(ws)) == 2                   # b.jpg blocked
    assert merge._run_locked_workflow("execute", str(ws)) == 3                # a.jpg placed and journalled
    plan_id = json.load(open(merge.merge_plan_path(str(ws))))["plan_id"]
    if record.startswith("set-aside plan"):
        assert merge._run_locked_workflow("plan", str(ws)) == 2               # the first set aside as -001
    if record.endswith("journal"):
        target = merge.journal_path(str(ws), plan_id)
    elif record == "set-aside plan":
        target = os.path.splitext(merge.merge_plan_path(str(ws)))[0] + "-001.json"
    else:
        target = merge.merge_plan_path(str(ws))
    return ws, lib, target


def _stops_naming_it_and_changes_nothing(ws, lib, target, command, capsys):
    capsys.readouterr()

    def state():
        return _tree(str(ws)), _tree(str(lib))
    before = state()
    assert merge._run_locked_workflow(command, str(ws)) == 2
    out = capsys.readouterr()
    assert target in out.out + out.err, out
    assert state() == before                                                  # the record, and all else, as it was


@pytest.mark.parametrize("record, command", _MERGE_PLAN_READS + _MERGE_JOURNAL_READS)
@pytest.mark.parametrize("damage", ["garbled", "not an object", "another shape"])
@pytest.mark.spec("RUL-merge_unreadable_record_stops", "BLD-merge_carry_forward", "BLD-merge_journal_resume",
                  "BLD-merge_record_shape", "BLD-merge_execute",
                  test="TST-merge_execute-a_record_of_merges_own_it_cannot_read_stops_it")
def test_a_record_of_merges_own_it_cannot_read_stops_it(tmp_path, capsys, record, command, damage):
    """A plan of merge's own — the saved one, or one a re-plan set aside — or its journal that cannot be read, or
    that parses in another shape than merge reads it in, stops the command reading it (exit 2), naming the file, which
    is left as it was: never taken for an empty one, nothing moved, no plan or summary written, no traceback."""
    ws, lib, target = _merge_record_to_damage(tmp_path, record)
    if damage == "another shape":           # parses, its plan id or operations there, in a shape merge cannot read
        obj = json.load(open(target))
        obj.update({"placed_sha256": []} if record.endswith("journal") else {"destinations": []})
        text = json.dumps(obj)
    else:
        text = "{torn" if damage == "garbled" else "[]"
    with open(target, "w") as f:
        f.write(text)
    _stops_naming_it_and_changes_nothing(ws, lib, target, command, capsys)


_PLAN_SHAPES = {"files not a list": {"destinations": {"Trip": {"files": {}}}},
                "a file record of another shape": {"destinations": {"Trip": {"files": [{"by_dest_source": 1}]}}},
                "depends_on not an object": {"depends_on": []}}
_JOURNAL_SHAPES = {"operations not an object": {"operations": []}}


@pytest.mark.parametrize("record, command, shape",
                         [(r, c, s) for r, c in _MERGE_PLAN_READS for s in _PLAN_SHAPES]
                         + [(r, c, s) for r, c in _MERGE_JOURNAL_READS for s in _JOURNAL_SHAPES])
@pytest.mark.spec("RUL-merge_unreadable_record_stops", "BLD-merge_record_shape",
                  test="TST-merge_execute-each_shape_check_of_merges_records_stops_it")
def test_each_shape_check_of_merges_records_stops_it(tmp_path, capsys, record, command, shape):
    """Each part of the shape merge reads its records in is checked wherever the record is read: a plan whose
    destination's files are not a list, whose file record names no by-dest path as text, or whose depends_on is not
    an object, and a journal whose operations are not an object, each stop the command reading it (exit 2), naming
    the file, nothing changed."""
    ws, lib, target = _merge_record_to_damage(tmp_path, record)
    obj = json.load(open(target))
    obj.update({**_PLAN_SHAPES, **_JOURNAL_SHAPES}[shape])
    with open(target, "w") as f:
        json.dump(obj, f)
    _stops_naming_it_and_changes_nothing(ws, lib, target, command, capsys)


@pytest.mark.parametrize("stop", ["precondition", "no plan", "stale plan", "unreadable journal", "interrupted"])
@pytest.mark.spec("RUL-merge_summary_only_for_execution", "BLD-merge_records",
                  test="TST-merge_execute-a_run_that_never_executes_or_is_interrupted_writes_no_summary")
def test_a_run_that_never_executes_or_is_interrupted_writes_no_summary(tmp_path, monkeypatch, stop):
    """An execute stopped before it begins — by a precondition, a plan missing or stale, a journal it cannot read —
    or interrupted writes no summary: the one an earlier execute wrote stays as it was."""
    ws, lib = _ws(tmp_path, [{"fp": "A", "dest": "Trip", "final_name": "a.jpg"},
                             {"fp": "B", "dest": "Trip", "final_name": "b.jpg"}],
                  library_files=[{"fp": "FAIL", "dest": "Trip", "name": "b.jpg"}])
    assert merge._run_locked_workflow("plan", str(ws)) == 2
    assert merge._run_locked_workflow("execute", str(ws)) == 3                # the earlier run's summary: partial
    earlier = open(merge.merge_summary_path(str(ws)), "rb").read()
    plan_id = json.load(open(merge.merge_plan_path(str(ws))))["plan_id"]
    if stop == "precondition":
        (ws / "0-sources" / "new.jpg").write_bytes(b"a new dump")
    elif stop == "no plan":
        os.remove(merge.merge_plan_path(str(ws)))
    elif stop == "stale plan":
        with open(_ctl(ws, "photos-25-execution-summary.json"), "w") as f:
            f.write(json.dumps({"status": "success", "touched": True}))
    elif stop == "unreadable journal":
        with open(merge.journal_path(str(ws), plan_id), "w") as f:
            f.write("{torn")
    else:
        def ctrl_c(self, ws_, library_root, rec):
            raise KeyboardInterrupt
        monkeypatch.setattr(merge.MergeWorkflow, "_move_file", ctrl_c)
    assert merge._run_locked_workflow("execute", str(ws)) == (130 if stop == "interrupted" else 2)
    assert open(merge.merge_summary_path(str(ws)), "rb").read() == earlier


@pytest.mark.spec("BLD-merge_journal_resume", "BLD-history_kept", "RUL-history_retained",
                  test="TST-merge_execute-one_journal_per_plan_keeps_every_executes_confirmations")
def test_one_journal_per_plan_keeps_every_executes_confirmations(tmp_path):
    """Merge's journal is its plan's, not its run's: a second execute of the same plan writes the same
    `journal-<plan id>.json`, carrying the first's confirmations into it with its own."""
    ws, lib = _ws(tmp_path, [{"fp": "A", "dest": "Trip", "final_name": "a.jpg"},
                             {"fp": "B", "dest": "Trip", "final_name": "b.jpg"}])
    assert merge._run_locked_workflow("plan", str(ws)) == 0
    plan_id = json.load(open(merge.merge_plan_path(str(ws))))["plan_id"]
    (lib / "Trip").mkdir()
    (lib / "Trip" / "b.jpg").write_bytes(_fp_bytes("OTHER"))               # b.jpg's place taken after the plan
    assert merge._run_locked_workflow("execute", str(ws)) == 3              # a.jpg placed, b.jpg blocked
    jpath = merge.journal_path(str(ws), plan_id)
    assert json.load(open(jpath))["operations"] == {"6-photos-by-dest/Trip/a.jpg": "confirmed"}
    os.remove(lib / "Trip" / "b.jpg")                                       # the place free again
    assert merge._run_locked_workflow("execute", str(ws)) == 0              # the same plan, run again
    journals = sorted(n for n in os.listdir(ws / ".photos-ingest") if n.startswith("journal-"))
    assert journals == [os.path.basename(jpath)]
    assert json.load(open(jpath))["operations"] == {"6-photos-by-dest/Trip/a.jpg": "confirmed",
                                                    "6-photos-by-dest/Trip/b.jpg": "confirmed"}


@pytest.mark.spec("BLD-merge_log_steps", "RUL-merge_records_landing",
                  test="TST-merge_execute-merges_step_says_how_each_photo_reached_the_library")
def test_merges_step_says_how_each_photo_reached_the_library(tmp_path):
    """Each photo merged gains one step — placed, placed under a name of its own, or already present — naming the
    plan, where it came from and where it is, its entry's library_path set to the same place."""
    ws, lib = _ws(tmp_path, [{"fp": "A", "dest": "Trip", "final_name": "a.jpg"},
                             {"fp": "B", "dest": "Trip", "final_name": "b.jpg"},
                             {"fp": "C", "dest": "Trip", "final_name": "c.jpg"}],
                  library_files=[{"fp": "OTHER", "dest": "Trip", "name": "b.jpg"},     # another photo: b renamed
                                 {"fp": "C", "dest": "Trip", "name": "c.jpg"}])        # c itself, byte for byte
    assert merge._run_locked_workflow("plan", str(ws)) == 0
    plan_id = json.load(open(merge.merge_plan_path(str(ws))))["plan_id"]
    assert merge._run_locked_workflow("execute", str(ws)) == 0
    photos = json.loads(open(_ctl(ws, "photos-35-merge-log.json")).read())["photos"]
    trip = os.path.join(str(lib), "Trip")
    for fp, action, place, renamed in (("A", "placed", "a.jpg", False), ("B", "placed", "b-001.jpg", True),
                                       ("C", "already_present", "c.jpg", False)):
        assert photos[fp]["journey"] == [{"phase": "merge", "run": plan_id, "action": action,
                                          "from": f"6-photos-by-dest/Trip/{fp.lower()}.jpg",
                                          "library_path": os.path.join(trip, place),
                                          "renamed_for_library": renamed}], fp
        assert photos[fp]["library_path"] == os.path.join(trip, place)


@pytest.mark.spec("BLD-merge_archive_manifest", "RUL-package_self_describing",
                  test="TST-merge_execute-merges_package_manifest_says_what_it_holds_and_whence")
def test_merges_package_manifest_says_what_it_holds_and_whence(tmp_path):
    """photos-35's manifest names the workspace and the merge run, supersedes geotag's, and lists every file it
    archives with its path and SHA-256."""
    ws, lib = _ws(tmp_path, [{"fp": "A", "dest": "Trip", "final_name": "a.jpg"}])
    with open(_ctl(ws, "photos-00-workspace-guard"), "w") as f:
        f.write(json.dumps({"initialized": True, "initialized_by_run": "init-run-1"}))
    assert merge._run_locked_workflow("plan", str(ws)) == 0
    assert merge._run_locked_workflow("execute", str(ws)) == 0
    m = json.loads(open(_ctl(ws, "photos-35-archive-manifest.json")).read())
    summary = _summary(ws)
    assert set(m) == {"artifact_type", "artifact_name", "schema_version", "workspace", "workspace_id", "plan_id",
                      "execution_id", "merge_run_id", "supersedes", "contents", "run_metadata"}
    assert (m["artifact_type"], m["artifact_name"], m["schema_version"]) == \
        ("archive_manifest", "photos-35-archive-manifest.json", 1)
    assert (m["workspace"], m["workspace_id"]) == ("ws", "init-run-1")
    assert m["plan_id"] == summary["merge_plan_id"]
    assert m["execution_id"] == m["merge_run_id"] == summary["merge_run_id"]
    assert m["supersedes"] == "photos-26-archive-manifest.json"
    assert m["run_metadata"] == {"generated_at": summary["run_metadata"]["started_at"]}
    for key, rec in m["contents"].items():
        assert rec["path"] == os.path.join(".photos-ingest", key)
        assert rec["sha256"] == utils.sha256_file(os.path.join(str(ws), rec["path"])), key


@pytest.mark.spec("RUL-empty_merge_seals", "BLD-merge_success_sequence",
                  test="TST-merge_execute-a_merge_of_no_photos_seals")
def test_a_merge_of_no_photos_seals(tmp_path):
    """A workspace whose finalized set holds no photo is merged whole: nothing is left to merge, so execute succeeds,
    writes its records and seals, the library untouched but for its lock."""
    ws, lib = _ws(tmp_path, [])
    before = _tree(str(lib))
    assert merge._run_locked_workflow("plan", str(ws)) == 0
    assert merge._run_locked_workflow("execute", str(ws)) == 0
    s = _summary(ws)
    assert s["status"] == "success" and s["totals"]["removed_from_by_dest"] == 0 and s["totals"]["blocked"] == 0
    assert utils.is_sealed(str(ws))
    assert os.path.exists(_ctl(ws, "photos-35-merge-log.json"))
    assert _tree(str(lib)) == before


@pytest.mark.parametrize("end, status", [("done", 0), ("workspace locked", 1), ("library locked", 1),
                                         ("refused", 2), ("partial", 3), ("interrupted", 130)])
@pytest.mark.spec("RUL-exit_status_says_how_it_ended", "BLD-exit_statuses",
                  test="TST-merge_execute-each_end_of_a_merge_has_its_own_exit_status")
def test_each_end_of_a_merge_has_its_own_exit_status(tmp_path, monkeypatch, end, status):
    """Merge's execute ends with a status of its own for each way it can end: done 0, the workspace or the library
    locked 1, refused 2 (here a stale plan), partial 3, interrupted 130."""
    ws, lib = _ws(tmp_path, [{"fp": "A", "dest": "Trip", "final_name": "a.jpg"},
                             {"fp": "B", "dest": "Trip", "final_name": "b.jpg"}],
                  library_files=[{"fp": "FAIL", "dest": "Trip", "name": "b.jpg"}] if end == "partial" else ())
    assert merge._run_locked_workflow("plan", str(ws)) == (2 if end == "partial" else 0)
    held = None
    if end == "workspace locked":
        held = utils.WorkspaceLock(str(ws))
    elif end == "library locked":
        held = utils.LibraryLock(str(lib))
    if held:
        assert held.acquire() is True
    if end == "refused":
        with open(_ctl(ws, "photos-25-execution-summary.json"), "w") as f:
            f.write(json.dumps({"status": "success", "touched": True}))      # the plan is stale now
    if end == "interrupted":
        def ctrl_c(self, ws_, library_root, rec):
            raise KeyboardInterrupt
        monkeypatch.setattr(merge.MergeWorkflow, "_move_file", ctrl_c)
    try:
        assert merge._run_locked_workflow("execute", str(ws)) == status
    finally:
        if held:
            held.release()
