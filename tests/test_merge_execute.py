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


def _tree(root):
    """{relpath: bytes} for every file under `root` — a byte-level snapshot for mutation checks.
    Lock files (`*.lock`) are transient lock-acquire artifacts, not data, so they are excluded."""
    out = {}
    for dp, _dn, fns in os.walk(root):
        for fn in fns:
            if fn.endswith(".lock"):
                continue
            ap = os.path.join(dp, fn)
            out[os.path.relpath(ap, root)] = open(ap, "rb").read()
    return out


# --- the four dispositions ---------------------------------------------------

@pytest.mark.spec("merge-create-library-dest-subdir-1", "merge-move-leaves-bydest-empty-1", "merge-move-placed-out-of-by-dest-1", "merge-summary-counts-partition-1")
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


@pytest.mark.spec("merge-collision-same-content-1", "merge-no-duplicate-of-library-file-1")
def test_execute_already_present_removes_source_no_write(tmp_path):
    ws, lib = _ws(tmp_path, [{"fp": "A", "dest": "Trip", "final_name": "a.jpg"}],
                  library_files=[{"fp": "A", "dest": "Trip", "name": "a.jpg"}])
    assert merge._run_locked_workflow("plan", str(ws)) == 0
    assert merge._run_locked_workflow("execute", str(ws)) == 0
    assert open(os.path.join(str(lib), "Trip", "a.jpg"), "rb").read() == _fp_bytes("A")  # untouched
    assert not os.path.exists(_src(ws, "Trip", "a.jpg"))     # source still removed
    assert _summary(ws)["totals"]["already_present"] == 1


@pytest.mark.spec("merge-collision-diff-content-1", "merge-different-content-rename-incoming-1", "merge-library-file-never-deleted-written-renamed-1")
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


@pytest.mark.spec("exec-noclobber-recheck-1", "merge-execute-no-clobber-at-execute-time-1", "merge-execute-occupied-different-blocker-1", "merge-execute-safe-alt-only-if-planned-1", "merge-library-protected-1")
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


@pytest.mark.spec("merge-nongoal-no-jpg-tif-breakout-1")
def test_merge_never_performs_jpg_tif_development_breakout(tmp_path):
    """§14 item 7 (anti): the jpg/tif development breakout is a later library-side processing phase,
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


@pytest.mark.spec("merge-no-mutate-by-dest-content-or-name-1")
def test_merge_never_mutates_by_dest_name_or_content_only_library_renames(tmp_path):
    """§2.4 (anti): merge never mutates by-dest content or a file's name; ONLY a library collision
    forces an incoming rename — and that rename happens at the LIBRARY target, never in by-dest. The
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


@pytest.mark.spec("lib-never-rescanned-1")
def test_merge_only_inspects_specific_collision_target_never_rescans_library(tmp_path, monkeypatch):
    """§15.1 (anti): merge never rescans the library wholesale — it fingerprints only each incoming
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


@pytest.mark.spec("merge-snapshot-required-aborts-1", "merge-summary-final-status-values-1")
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


@pytest.mark.spec("merge-prep-consistency-1", "merge-revalidates-current-1")
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


@pytest.mark.spec("config-prep-sole-writer-1", "merge-config-readonly-1")
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

@pytest.mark.spec("merge-interrupted-not-sealed-resumes-1", "merge-move-atomic-source-last-1", "merge-resume-state-derivation-1")
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


@pytest.mark.spec("merge-execute-occupied-identical-treat-present-1", "merge-idempotent-resumable-1", "merge-resume-completes-crash-window-1")
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


@pytest.mark.spec("atomic-crossfs-equivalent-1", "merge-move-place-then-remove-no-loss-1")
def test_execute_cross_fs_move_verifies_and_completes(tmp_path, monkeypatch):
    _force_cross_fs(monkeypatch)
    ws, lib = _ws(tmp_path, [{"fp": "A", "dest": "Trip", "final_name": "a.jpg"}])
    assert merge._run_locked_workflow("plan", str(ws)) == 0
    assert merge._run_locked_workflow("execute", str(ws)) == 0
    assert open(os.path.join(str(lib), "Trip", "a.jpg"), "rb").read() == _fp_bytes("A")
    assert not os.path.exists(_src(ws, "Trip", "a.jpg"))


@pytest.mark.spec("exec-failed-op-clean-1", "merge-source-removed-only-after-verified-copy-1", "merge-verify-copy-detect-torn-1")
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


@pytest.mark.spec("merge-concurrency-deterministic-aggregation-1")
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


@pytest.mark.spec("atomic-crossfs-temp-sweep-1", "merge-sweep-stale-temps-1")
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


@pytest.mark.spec("exec-concurrency-no-semantic-change-1")
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


@pytest.mark.spec("merge-moveset-fixed-before-concurrency-1", "snapshot-timing-1")
def test_snapshot_and_revalidation_precede_the_parallel_move_pass(tmp_path, monkeypatch):
    """Sequencing (§10.3): the move-set is fixed BEFORE any concurrent placement — dependency
    revalidation and the pre-mutation snapshot both complete before the FIRST per-file move runs,
    even under -j4. Probe the call order via wrappers."""
    ws, lib = _ws(tmp_path,
                  [{"fp": "A", "dest": "Trip", "final_name": "a.jpg"},
                   {"fp": "B", "dest": "Trip", "final_name": "b.jpg"},
                   {"fp": "C", "dest": "Spain", "final_name": "c.jpg"}])
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

    monkeypatch.setattr(merge.MergeWorkflow, "revalidate_plan_deps", reval)
    monkeypatch.setattr(merge, "take_zfs_snapshot", snap)
    monkeypatch.setattr(merge.MergeWorkflow, "_move_file", move)
    assert merge._run_locked_workflow("execute", str(ws), jobs=4) == 0

    first_move = events.index("move")
    assert events.index("revalidate") < first_move                # move-set fixed before any placement
    assert events.index("snapshot") < first_move
    assert events.count("move") == 3                              # all three files still placed


@pytest.mark.spec("merge-concurrency-library-lock-throughout-1")
def test_library_lock_held_throughout_concurrent_move_pass(tmp_path, monkeypatch):
    """§10.4: the library lock is held for the WHOLE concurrent move pass — concurrency never relaxes
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


@pytest.mark.spec("exec-single-writer-journal-1")
def test_merge_journal_writes_only_from_the_main_thread(tmp_path, monkeypatch):
    """Single-writer journal (§8.3): under -j4 the merge confirmation journal is persisted ONLY by the
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


@pytest.mark.spec("plan-missing-stops-1")
def test_execute_without_plan_errors(tmp_path):
    ws, lib = _ws(tmp_path, [{"fp": "A", "dest": "Trip", "final_name": "a.jpg"}])
    assert merge._run_locked_workflow("execute", str(ws)) == 2     # no photos-30


@pytest.mark.spec("merge-execute-revalidate-reject-stale-1")
def test_execute_rejects_stale_plan(tmp_path):
    ws, lib = _ws(tmp_path, [{"fp": "A", "dest": "Trip", "final_name": "a.jpg"}])
    assert merge._run_locked_workflow("plan", str(ws)) == 0
    p24 = os.path.join(str(ws), ".photos-ingest", "photos-25-execution-summary.json")
    open(p24, "w").write(json.dumps({"status": "success", "touched": True}))   # dep changed
    assert merge._run_locked_workflow("execute", str(ws)) == 2
    assert not os.path.exists(os.path.join(str(ws.parent), "ws-lib", "Trip"))  # nothing moved


# --- no-mutation consequences of non-executing paths (Tier 3) ----------------

@pytest.mark.spec("merge-planning-nonmutating-1")
def test_plan_mutates_nothing_no_terminal_artifacts(tmp_path):
    """Planning never mutates: after `plan`, by-dest + library are byte-identical and NONE of the
    execute-only artifacts (photos-31 summary, photos-35 log/db/manifest, journal, seal) exist."""
    ws, lib = _ws(tmp_path, [{"fp": "A", "dest": "Trip", "final_name": "a.jpg"}])
    before_bd, before_lib = _tree(str(ws / "6-photos-by-dest")), _tree(str(lib))
    assert merge._run_locked_workflow("plan", str(ws)) == 0
    assert _tree(str(ws / "6-photos-by-dest")) == before_bd      # staging untouched
    assert _tree(str(lib)) == before_lib                         # library untouched
    ctl = ws / ".photos-ingest"
    assert not os.path.exists(merge.merge_summary_path(str(ws)))  # no photos-31
    assert not utils.is_sealed(str(ws))                          # no seal
    for n in ("photos-35-merge-log.json", "photos-35-merge-ingest.db"):
        assert not os.path.exists(ctl / n), n


@pytest.mark.spec("merge-no-stale-summary-1")
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


@pytest.mark.spec("merge-precond-fail-no-output-1")
def test_precondition_failure_writes_no_summary_and_no_placement(tmp_path):
    """A preflight blocker stops merge before execute: no photos-31 summary, library byte-unchanged.
    Here the prep handoff is missing — a precondition the preflight gathers and refuses on."""
    ws, lib = _ws(tmp_path, [{"fp": "A", "dest": "Trip", "final_name": "a.jpg"}])
    before_lib = _tree(str(lib))
    os.remove(os.path.join(str(ws), ".photos-ingest", "photos-11-handoff.json"))  # break a precondition
    assert merge._run_locked_workflow("execute", str(ws)) == 2    # preflight blocker -> rc 2
    assert not os.path.exists(merge.merge_summary_path(str(ws)))  # no summary written
    assert _tree(str(lib)) == before_lib                          # nothing placed


@pytest.mark.spec("merge-execute-no-rederive-1")
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


@pytest.mark.spec("merge-journal-confirmed-only-1")
def test_partial_run_journal_holds_only_confirmed_moves(tmp_path):
    """After a partial run (one placed, one blocked), the merge journal records ONLY the confirmed
    move — the blocked file is absent, so the next run resumes from the true diff (§8.3)."""
    ws, lib = _ws(tmp_path,
                  [{"fp": "A", "dest": "Trip", "final_name": "a.jpg"},
                   {"fp": "B", "dest": "Trip", "final_name": "b.jpg"}],
                  library_files=[{"fp": "FAIL", "dest": "Trip", "name": "b.jpg"}])  # b's lib file unreadable
    assert merge._run_locked_workflow("plan", str(ws)) == 0
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


@pytest.mark.spec("merge-execute-db-snapshot-on-success-1", "merge-records-summary-1", "merge-reseal-archive-automatic-1", "merge-reseals-automatically-1", "seal-success-then-sealed-1")
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


@pytest.mark.spec("log-copy-forward-extend-1", "merge-log-copy-26-forward-append-1", "merge-writes-only-own-3x-copies-26-forward-1")
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


@pytest.mark.spec("merge-blocker-left-in-by-dest-partial-1", "merge-blocker-left-in-bydest-1", "merge-seal-only-on-full-success-1", "seal-partial-writes-no-marker-1")
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


@pytest.mark.spec("merge-resume-via-execute-not-plan-1")
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


@pytest.mark.spec("merge-replan-allowed-after-failed-or-rejected-1")
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


@pytest.mark.spec("merge-sealed-hardstop-touch-nothing-1", "seal-scripts-hardstop-1")
def test_sealed_workspace_rerun_hardstops(tmp_path):
    ws, lib = _ws(tmp_path, [{"fp": "A", "dest": "Trip", "final_name": "a.jpg"}])
    assert merge._run_locked_workflow("plan", str(ws)) == 0
    assert merge._run_locked_workflow("execute", str(ws)) == 0
    assert utils.is_sealed(str(ws))
    before = open(os.path.join(str(lib), "Trip", "a.jpg"), "rb").read()
    assert merge._run_locked_workflow("execute", str(ws)) == 2          # sealed -> preflight blocker
    assert open(os.path.join(str(lib), "Trip", "a.jpg"), "rb").read() == before   # untouched
