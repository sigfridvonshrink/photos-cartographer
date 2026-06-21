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

"""Increment 4 — execute: the §11 place-then-remove move, journal, state-derivation resume (§8.3),
concurrency (§10.4), and photos-31-merge-summary.json. execute consumes photos-30; the terminal
archival steps (merge-log, DB snapshot, re-seal, seal) are Increment 5.

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

MANAGED = ["0-sources", "1-strays", "2-missing-metadata", "3-redundant-jpgs",
           "4-videos-by-date", "5-photos-by-date", "6-photos-by-dest"]


def _fp_bytes(fp):
    return b"FP=" + fp.encode()


def _parse_fp(path):
    try:
        data = open(path, "rb").read()
    except OSError:
        return None
    return data[3:].decode() if data.startswith(b"FP=") else None


@pytest.fixture(autouse=True)
def _content_fingerprint(monkeypatch):
    """Fingerprint a photo by its content blob (a faithful copy -> same fingerprint as its source)."""
    def fake(self, abs_path):
        v = _parse_fp(abs_path)
        if v and v != "FAIL":
            return {"status": "valid", "value": v, "strategy": "image-content-hash-v1",
                    "engine_version": "test"}
        return {"status": "failed", "value": None, "error": "unreadable", "engine_version": "test"}
    monkeypatch.setattr(merge.MergeWorkflow, "_fingerprint_library_file", fake)


def _ws(tmp_path, photos, library_files=(), name="ws"):
    """A merge-ready workspace + blessed library. photos: {fp, dest, final_name, pre_name?}.
    By-dest files hold their FP blob under FINAL names; the handoff carries pre-rename names + a
    rename op when pre_name != final_name. library_files: {fp, dest, name} ('FAIL' fp -> unreadable)."""
    ws = tmp_path / name
    ws.mkdir()
    lib = tmp_path / (name + "-lib")
    lib.mkdir()
    for d in MANAGED:
        (ws / d).mkdir()
    ctl = ws / ".photos-ingest"
    ctl.mkdir()
    (ctl / "photos-00-workspace-guard").touch()
    utils.write_library_marker(str(lib))

    ho_files, ops = [], []
    for p in photos:
        dest, final = p.get("dest", ""), p["final_name"]
        pre = p.get("pre_name", final)
        ddir = (ws / "6-photos-by-dest" / dest) if dest else (ws / "6-photos-by-dest")
        ddir.mkdir(parents=True, exist_ok=True)
        (ddir / final).write_bytes(_fp_bytes(p["fp"]))
        rel_pre = os.path.join("6-photos-by-dest", dest, pre) if dest else os.path.join("6-photos-by-dest", pre)
        ho_files.append({"relative_path": rel_pre, "folder_class": "6-photos-by-dest",
                         "media_class": "image", "content_fingerprint": p["fp"]})
        if pre != final:
            ops.append({"type": "rename_no_clobber", "to": final,
                        "preconditions": {"content_fingerprint": p["fp"]}})
    for lf in library_files:
        dest = lf.get("dest", "")
        ldir = (lib / dest) if dest else lib
        ldir.mkdir(parents=True, exist_ok=True)
        (ldir / lf["name"]).write_bytes(_fp_bytes(lf["fp"]))

    handoff = {"files": ho_files, "content_fingerprint": "whole", "run_metadata": {"started_at": "t"}}
    (ctl / "photos-11-handoff.json").write_text(json.dumps(handoff))
    cfg = {k: v for k, v in utils.CONFIG.items() if k != "jobs"}
    cfg["merge"] = dict(cfg.get("merge") or {})
    cfg["merge"]["library_root"] = str(lib)
    (ctl / "photos-00-config.json").write_text(json.dumps(cfg))
    (ctl / "photos-24-executable-plan.json").write_text(json.dumps(
        {"status": "ready", "plan_id": "cal-plan-1", "destinations": {"d": {"operations": ops}},
         "depends_on": {"handoff": {"dependency_type": "handoff_content",
                                    "artifact_name": "photos-11-handoff.json",
                                    "content_fingerprint": utils.handoff_content_fingerprint(handoff)}}}))
    (ctl / "photos-25-execution-summary.json").write_text(json.dumps(
        {"status": "success", "run_metadata": {"execution_id": "cal-exec-1"}}))
    (ctl / "photos-26-complete-log.json").write_text(json.dumps({"photos": {}}))
    (ctl / "photos-26-archive-manifest.json").write_text(json.dumps({"artifact_name": "m"}))
    return ws, lib


def _summary(ws):
    return json.loads(open(merge.merge_summary_path(str(ws))).read())


def _src(ws, dest, name):
    return os.path.join(str(ws), "6-photos-by-dest", dest, name)


# --- the four dispositions ---------------------------------------------------

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


def test_execute_already_present_removes_source_no_write(tmp_path):
    ws, lib = _ws(tmp_path, [{"fp": "A", "dest": "Trip", "final_name": "a.jpg"}],
                  library_files=[{"fp": "A", "dest": "Trip", "name": "a.jpg"}])
    assert merge._run_locked_workflow("plan", str(ws)) == 0
    assert merge._run_locked_workflow("execute", str(ws)) == 0
    assert open(os.path.join(str(lib), "Trip", "a.jpg"), "rb").read() == _fp_bytes("A")  # untouched
    assert not os.path.exists(_src(ws, "Trip", "a.jpg"))     # source still removed
    assert _summary(ws)["totals"]["already_present"] == 1


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
    assert merge._run_locked_workflow("plan", str(ws)) == 0
    assert merge._run_locked_workflow("execute", str(ws)) == 3          # blocked -> rc 3
    assert os.path.exists(_src(ws, "Trip", "a.jpg"))                    # left in by-dest
    s = _summary(ws)
    assert s["status"] == "failed"                                      # the only file blocked -> nothing placed
    assert s["totals"]["blocked"] == 1 and s["failures"]


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


def test_execute_required_snapshot_failure_aborts_before_any_placement(tmp_path, monkeypatch):
    """snapshots_required + the library pre-mutation snapshot fails -> abort BEFORE any move:
    status rejected (rc 2), nothing placed, source untouched in by-dest, library empty, workspace
    NOT sealed. The required-snapshot guard is the merge spec §10.3-step-3 promise."""
    ws, lib = _ws(tmp_path, [{"fp": "A", "dest": "Trip", "final_name": "a.jpg"}])
    assert merge._run_locked_workflow("plan", str(ws)) == 0
    monkeypatch.setattr(merge, "take_zfs_snapshot", lambda *a, **k: {
        "required": True, "ok": False, "snapshot_name": "lib@merge-x", "command": "zfs snapshot",
        "exit_code": 1, "stdout": "", "stderr": "pool busy"})
    assert merge._run_locked_workflow("execute", str(ws)) == 2          # rejected -> rc 2
    assert open(_src(ws, "Trip", "a.jpg"), "rb").read() == _fp_bytes("A")  # source untouched
    assert not os.path.exists(os.path.join(str(lib), "Trip", "a.jpg"))  # nothing placed
    assert not utils.is_sealed(str(ws))                                 # no seal
    s = _summary(ws)
    assert s["status"] == "rejected"
    assert s["totals"]["placed_new"] == 0 and s["totals"]["blocked"] == 0


def test_plan_blocks_when_bydest_photo_absent_from_finalized_set(tmp_path):
    """Prep-consistency (precondition 4): a photo physically under 6-photos-by-dest but NOT in the
    finalized record (handoff predates the latest move into by-dest) -> 're-run prep' blocker at plan,
    rc 2, NO plan artifact written, nothing placed. Guards against merging an unrecorded file."""
    ws, lib = _ws(tmp_path, [{"fp": "A", "dest": "Trip", "final_name": "a.jpg"}])
    stray = ws / "6-photos-by-dest" / "Trip" / "stray.jpg"               # on disk, absent from handoff
    stray.write_bytes(_fp_bytes("Z"))
    assert merge._run_locked_workflow("plan", str(ws)) == 2              # preflight blocker -> rc 2
    assert not os.path.exists(merge.merge_plan_path(str(ws)))           # no plan written
    assert stray.exists()                                               # left untouched
    assert not (lib / "Trip").exists()                                 # nothing placed


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


# --- resume (state-derivation, §8.3) -----------------------------------------

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


# --- cross-filesystem path + torn-copy verify (§11.2) ------------------------

def _force_cross_fs(monkeypatch):
    """Make the by-dest source move look cross-filesystem so _move_no_clobber takes the copy-verify
    fallback; the tmp->target rename within the library stays same-fs (real)."""
    real = utils._rename_no_clobber_same_fs

    def patched(src, dest):
        if "6-photos-by-dest" in src:
            raise OSError(errno.EXDEV, "simulated cross-fs", src)
        return real(src, dest)
    monkeypatch.setattr(utils, "_rename_no_clobber_same_fs", patched)


def test_execute_cross_fs_move_verifies_and_completes(tmp_path, monkeypatch):
    _force_cross_fs(monkeypatch)
    ws, lib = _ws(tmp_path, [{"fp": "A", "dest": "Trip", "final_name": "a.jpg"}])
    assert merge._run_locked_workflow("plan", str(ws)) == 0
    assert merge._run_locked_workflow("execute", str(ws)) == 0
    assert open(os.path.join(str(lib), "Trip", "a.jpg"), "rb").read() == _fp_bytes("A")
    assert not os.path.exists(_src(ws, "Trip", "a.jpg"))


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


# --- concurrency determinism + lifecycle errors ------------------------------

def _comparable(s):
    # Determinism = same counts, status, and per-destination file order/flags regardless of job count.
    # The absolute library_path differs between the two scratch libraries, so drop it.
    dests = {d: [(f["by_dest_path"], f["renamed_for_library"], f["already_present"],
                  f["removed_from_by_dest"]) for f in v["files"]]
             for d, v in s["destinations"].items()}
    return {"totals": s["totals"], "resume": s["resume"], "status": s["status"], "dests": dests}


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


def test_execute_without_plan_errors(tmp_path):
    ws, lib = _ws(tmp_path, [{"fp": "A", "dest": "Trip", "final_name": "a.jpg"}])
    assert merge._run_locked_workflow("execute", str(ws)) == 2     # no photos-30


def test_execute_rejects_stale_plan(tmp_path):
    ws, lib = _ws(tmp_path, [{"fp": "A", "dest": "Trip", "final_name": "a.jpg"}])
    assert merge._run_locked_workflow("plan", str(ws)) == 0
    p24 = os.path.join(str(ws), ".photos-ingest", "photos-25-execution-summary.json")
    open(p24, "w").write(json.dumps({"status": "success", "touched": True}))   # dep changed
    assert merge._run_locked_workflow("execute", str(ws)) == 2
    assert not os.path.exists(os.path.join(str(ws.parent), "ws-lib", "Trip"))  # nothing moved


# --- Increment 5: terminal finalization (full-success only) -------------------

def _ctl(ws, name):
    return os.path.join(str(ws), ".photos-ingest", name)


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
    # §9.1 item 2/9: summary carries the merge plan id, the geotag run ids, and a finish time.
    summ = _summary(ws)
    assert summ["merge_plan_id"] == json.loads(open(_ctl(ws, "photos-30-merge-plan.json")).read())["plan_id"]
    assert summ["geotag"] == {"plan_id": "cal-plan-1", "execution_id": "cal-exec-1"}
    assert summ["run_metadata"]["finished_at"] and summ["run_metadata"]["started_at"]
    # The re-seal manifest supersedes geotag's and lists the merge artifacts.
    manifest = json.loads(open(_ctl(ws, "photos-35-archive-manifest.json")).read())
    assert manifest["supersedes"] == "photos-26-archive-manifest.json"
    assert "photos-31-merge-summary.json" in manifest["contents"]
    assert "photos-35-merge-log.json" in manifest["contents"]


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
    assert journey[-1] == {"phase": "merge", "action": "placed",
                           "library_path": os.path.join(str(lib), "Trip", "a.jpg"),
                           "renamed_for_library": False}
    # photos-25 itself must be byte-unchanged (never edited).
    p25 = json.loads(open(_ctl(ws, "photos-26-complete-log.json")).read())
    assert p25["photos"]["A"]["journey"] == [{"phase": "geotag", "action": "renamed"}]


def test_partial_run_does_not_seal_or_finalize(tmp_path):
    ws, lib = _ws(tmp_path, [{"fp": "A", "dest": "Trip", "final_name": "a.jpg"}],
                  library_files=[{"fp": "FAIL", "dest": "Trip", "name": "a.jpg"}])
    assert merge._run_locked_workflow("plan", str(ws)) == 0
    assert merge._run_locked_workflow("execute", str(ws)) == 3          # partial
    assert not utils.is_sealed(str(ws))                                # re-runnable
    for name in ("photos-35-merge-log.json", "photos-35-merge-ingest.db",
                 "photos-35-archive-manifest.json", "photos-00-sealed.json"):
        assert not os.path.exists(_ctl(ws, name)), name
    assert os.path.exists(_ctl(ws, "photos-31-merge-summary.json"))     # summary still written


def test_re_plan_after_partial_is_refused(tmp_path):
    # Re-planning over a partially-applied merge is refused (resume via execute), so an already-moved
    # file can never be dropped from the merge log a later execute writes. The saved plan is untouched.
    # Genuine mixed partial: a.jpg places (target free, source removed), b.jpg blocks (unfingerprintable
    # collision) — so a real moved file exists to protect.
    ws, lib = _ws(tmp_path, [{"fp": "A", "dest": "Trip", "final_name": "a.jpg"},
                             {"fp": "B", "dest": "Trip", "final_name": "b.jpg"}],
                  library_files=[{"fp": "FAIL", "dest": "Trip", "name": "b.jpg"}])
    assert merge._run_locked_workflow("plan", str(ws)) == 0
    assert merge._run_locked_workflow("execute", str(ws)) == 3          # 1 placed, 1 blocked -> partial
    assert _summary(ws)["status"] == "partial"
    assert not os.path.exists(_src(ws, "Trip", "a.jpg"))               # a.jpg was moved (source gone)
    plan_before = open(merge.merge_plan_path(str(ws))).read()
    assert merge._run_locked_workflow("plan", str(ws)) == 2             # re-plan refused
    assert open(merge.merge_plan_path(str(ws))).read() == plan_before   # plan untouched


def test_re_plan_after_failed_is_allowed(tmp_path):
    # An all-blocked run is `failed` — nothing was placed, every source is still in by-dest. Like a
    # `rejected` run, it moved nothing, so re-planning is allowed (no moved file to drop from the log);
    # the re-plan refusal applies only to runs that actually moved files (partial/success).
    ws, lib = _ws(tmp_path, [{"fp": "A", "dest": "Trip", "final_name": "a.jpg"}],
                  library_files=[{"fp": "FAIL", "dest": "Trip", "name": "a.jpg"}])
    assert merge._run_locked_workflow("plan", str(ws)) == 0
    assert merge._run_locked_workflow("execute", str(ws)) == 3          # the only file blocked -> failed
    assert _summary(ws)["status"] == "failed"
    assert os.path.exists(_src(ws, "Trip", "a.jpg"))                    # nothing moved — source remains
    assert merge._run_locked_workflow("plan", str(ws)) == 0             # re-plan allowed


def test_re_plan_allowed_when_no_partial(tmp_path):
    # The guard only fires on an in-flight (unsealed) merge: a plan with no prior summary re-plans fine.
    ws, lib = _ws(tmp_path, [{"fp": "A", "dest": "Trip", "final_name": "a.jpg"}])
    assert merge._run_locked_workflow("plan", str(ws)) == 0
    assert merge._run_locked_workflow("plan", str(ws)) == 0


def test_re_plan_after_crash_before_seal_is_refused(tmp_path, monkeypatch):
    # A crash between the summary write (status=success) and the seal leaves the workspace unsealed
    # with status=success. Re-planning must STILL be refused (resume via execute) so the complete
    # log/summary is not overwritten by an empty re-plan that then seals an incomplete record.
    ws, lib = _ws(tmp_path, [{"fp": "A", "dest": "Trip", "final_name": "a.jpg"}])
    monkeypatch.setattr(merge.MergeWorkflow, "_finalize_terminal", lambda *a, **k: None)  # skip the seal
    assert merge._run_locked_workflow("plan", str(ws)) == 0
    assert merge._run_locked_workflow("execute", str(ws)) == 0       # success, but crashed before seal
    assert _summary(ws)["status"] == "success" and not utils.is_sealed(str(ws))
    assert merge._run_locked_workflow("plan", str(ws)) == 2          # re-plan still refused


def test_sealed_workspace_rerun_hardstops(tmp_path):
    ws, lib = _ws(tmp_path, [{"fp": "A", "dest": "Trip", "final_name": "a.jpg"}])
    assert merge._run_locked_workflow("plan", str(ws)) == 0
    assert merge._run_locked_workflow("execute", str(ws)) == 0
    assert utils.is_sealed(str(ws))
    before = open(os.path.join(str(lib), "Trip", "a.jpg"), "rb").read()
    assert merge._run_locked_workflow("execute", str(ws)) == 2          # sealed -> preflight blocker
    assert open(os.path.join(str(lib), "Trip", "a.jpg"), "rb").read() == before   # untouched
