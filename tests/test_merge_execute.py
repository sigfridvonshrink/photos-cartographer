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

    handoff = {"filename_timestamp_format": utils.CONFIG["filename_timestamp_format"], "files": ho_files, "content_fingerprint": "whole", "run_metadata": {"started_at": "t"}}
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
    _bd = ws / "6-photos-by-dest"          # finalize's record of each by-dest photo as geotag left it
    (ctl / "photos-26-finalized-media.json").write_text(json.dumps({"media": {
        os.path.relpath(os.path.join(r, n), ws): {"size": os.stat(os.path.join(r, n)).st_size,
                                                  "mtime_ns": os.stat(os.path.join(r, n)).st_mtime_ns}
        for r, _d, fs in os.walk(_bd) for n in fs}}))
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

@pytest.mark.spec("merge-create-library-dest-subdir-1", "merge-move-leaves-bydest-empty-1", "merge-move-placed-out-of-by-dest-1", "merge-summary-counts-partition-1", test="TST-merge_execute-execute_placed_new_moves_into_library")
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


@pytest.mark.spec("merge-collision-same-content-1", "merge-no-duplicate-of-library-file-1", test="TST-merge_execute-execute_already_present_removes_source_no_write")
def test_execute_already_present_removes_source_no_write(tmp_path):
    ws, lib = _ws(tmp_path, [{"fp": "A", "dest": "Trip", "final_name": "a.jpg"}],
                  library_files=[{"fp": "A", "dest": "Trip", "name": "a.jpg"}])
    assert merge._run_locked_workflow("plan", str(ws)) == 0
    assert merge._run_locked_workflow("execute", str(ws)) == 0
    assert open(os.path.join(str(lib), "Trip", "a.jpg"), "rb").read() == _fp_bytes("A")  # untouched
    assert not os.path.exists(_src(ws, "Trip", "a.jpg"))     # source still removed
    assert _summary(ws)["totals"]["already_present"] == 1


@pytest.mark.spec("RUL-library_file_read_once", "RUL-collision_by_content", "RUL-library_file_rechecked_before_removal", test="TST-merge_execute-the_library_file_is_read_again_before_a_photo_already_there_is_removed")
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


@pytest.mark.spec("merge-collision-diff-content-1", "merge-different-content-rename-incoming-1", "merge-library-file-never-deleted-written-renamed-1", test="TST-merge_execute-execute_renamed_incoming_places_under_safe_name")
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


@pytest.mark.spec("exec-noclobber-recheck-1", "merge-execute-no-clobber-at-execute-time-1", "merge-execute-occupied-different-blocker-1", "merge-execute-safe-alt-only-if-planned-1", "merge-library-protected-1", test="TST-merge_execute-execute_occupied_by_different_content_at_execute_blocks_no_clobber")
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


@pytest.mark.spec("lib-never-rescanned-1", test="TST-merge_execute-merge_only_inspects_specific_collision_target_never_rescans_library")
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


@pytest.mark.spec("merge-snapshot-required-aborts-1", "merge-summary-final-status-values-1")
def test_execute_required_snapshot_failure_aborts_before_any_placement(tmp_path, monkeypatch):
    """snapshots_required + the library pre-mutation snapshot fails -> abort BEFORE any move:
    status rejected (rc 2), nothing placed, source untouched in by-dest, library empty, workspace
    NOT sealed. The required-snapshot guard is the merge spec §10.3-step-3 promise."""
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


@pytest.mark.spec("merge-prep-consistency-1", "merge-revalidates-current-1", test="TST-merge_execute-plan_blocks_when_bydest_photo_absent_from_finalized_set")
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


@pytest.mark.spec("config-prep-sole-writer-1", "merge-config-readonly-1", test="TST-merge_execute-config_is_byte_identical_across_plan_dryrun_execute")
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

@pytest.mark.spec("merge-interrupted-not-sealed-resumes-1", "merge-move-atomic-source-last-1", "merge-resume-state-derivation-1", test="TST-merge_execute-execute_resume_after_crash_before_seal")
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


@pytest.mark.spec("merge-execute-occupied-identical-treat-present-1", "merge-idempotent-resumable-1", "merge-resume-completes-crash-window-1", test="TST-merge_execute-execute_resume_finishes_crash_window")
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


@pytest.mark.spec("atomic-crossfs-equivalent-1", "merge-move-place-then-remove-no-loss-1", test="TST-merge_execute-execute_cross_fs_move_verifies_and_completes")
def test_execute_cross_fs_move_verifies_and_completes(tmp_path, monkeypatch):
    _force_cross_fs(monkeypatch)
    ws, lib = _ws(tmp_path, [{"fp": "A", "dest": "Trip", "final_name": "a.jpg"}])
    assert merge._run_locked_workflow("plan", str(ws)) == 0
    assert merge._run_locked_workflow("execute", str(ws)) == 0
    assert open(os.path.join(str(lib), "Trip", "a.jpg"), "rb").read() == _fp_bytes("A")
    assert not os.path.exists(_src(ws, "Trip", "a.jpg"))


@pytest.mark.spec("exec-failed-op-clean-1", "merge-source-removed-only-after-verified-copy-1", "merge-verify-copy-detect-torn-1", "RUL-failure_recorded", test="TST-merge_execute-execute_torn_copy_blocks_and_keeps_source")
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


@pytest.mark.spec("atomic-crossfs-temp-sweep-1", "merge-sweep-stale-temps-1", test="TST-merge_execute-execute_sweeps_crash_orphaned_cross_fs_temps")
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


@pytest.mark.spec("merge-moveset-fixed-before-concurrency-1", "snapshot-timing-1", test="TST-merge_execute-snapshot_and_revalidation_precede_the_parallel_move_pass")
def test_snapshot_and_revalidation_precede_the_parallel_move_pass(tmp_path, monkeypatch):
    """Sequencing (§10.3): the move-set is fixed BEFORE any concurrent placement — dependency
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


@pytest.mark.spec("plan-missing-stops-1", test="TST-merge_execute-execute_without_plan_errors")
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


@pytest.mark.spec("merge-execute-db-snapshot-on-success-1", "merge-records-summary-1", "merge-reseal-archive-automatic-1", "merge-reseals-automatically-1", "seal-success-then-sealed-1", test="TST-merge_execute-full_success_writes_terminal_artifacts_and_seals")
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


@pytest.mark.spec("BLD-log_format", "log-copy-forward-extend-1", "merge-log-copy-26-forward-append-1", "merge-writes-only-own-3x-copies-26-forward-1")
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
    assert journey[-1] == {"phase": "merge", "action": "placed", "from": "6-photos-by-dest/Trip/a.jpg",
                           "library_path": os.path.join(str(lib), "Trip", "a.jpg"),
                           "renamed_for_library": False}
    # photos-25 itself must be byte-unchanged (never edited).
    p25 = json.loads(open(_ctl(ws, "photos-26-complete-log.json")).read())
    assert p25["photos"]["A"]["journey"] == [{"phase": "geotag", "action": "renamed"}]


@pytest.mark.spec("merge-blocker-left-in-by-dest-partial-1", "merge-blocker-left-in-bydest-1", "merge-seal-only-on-full-success-1", "seal-partial-writes-no-marker-1", test="TST-merge_execute-partial_run_does_not_seal_or_finalize")
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


@pytest.mark.spec("merge-resume-via-execute-not-plan-1", "RUL-merge_resumable", test="TST-merge_execute-a_re_plan_after_a_partial_merge_carries_what_was_moved")
def test_a_re_plan_after_a_partial_merge_carries_what_was_moved(tmp_path):
    """A partial merge — a.jpg moved, b.jpg blocked — is re-planned once the blocker is cleared. The new
    plan carries a.jpg forward from the plan that moved it, and the merge that finishes logs both."""
    ws, lib = _ws(tmp_path, [{"fp": "A", "dest": "Trip", "final_name": "a.jpg"},
                             {"fp": "B", "dest": "Trip", "final_name": "b.jpg"}],
                  library_files=[{"fp": "FAIL", "dest": "Trip", "name": "b.jpg"}])
    assert merge._run_locked_workflow("plan", str(ws)) == 0
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


def test_a_photo_moved_earlier_but_gone_from_its_place_blocks_the_re_plan(tmp_path):
    ws, lib = _ws(tmp_path, [{"fp": "A", "dest": "Trip", "final_name": "a.jpg"},
                             {"fp": "B", "dest": "Trip", "final_name": "b.jpg"}],
                  library_files=[{"fp": "FAIL", "dest": "Trip", "name": "b.jpg"}])
    assert merge._run_locked_workflow("plan", str(ws)) == 0
    assert merge._run_locked_workflow("execute", str(ws)) == 3
    with open(os.path.join(str(lib), "Trip", "a.jpg"), "wb") as f:
        f.write(_fp_bytes("X"))                                          # a.jpg's place no longer holds it
    merge._run_locked_workflow("plan", str(ws))
    plan = json.load(open(merge.merge_plan_path(str(ws))))
    a = next(r for d in plan["destinations"].values() for r in d["files"] if r["by_dest_source"].endswith("a.jpg"))
    assert a["disposition"] == "blocked" and "no longer holds it" in a["blocked_reason"]


def test_a_photo_gone_from_the_workspace_that_no_merge_moved_blocks_the_plan(tmp_path):
    ws, lib = _ws(tmp_path, [{"fp": "A", "dest": "Trip", "final_name": "a.jpg"}])
    os.remove(_src(ws, "Trip", "a.jpg"))                                # gone by other means
    merge._run_locked_workflow("plan", str(ws))
    plan = json.load(open(merge.merge_plan_path(str(ws))))
    a = next(r for d in plan["destinations"].values() for r in d["files"])
    assert a["disposition"] == "blocked" and "no earlier merge" in a["blocked_reason"]


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


@pytest.mark.spec("merge-sealed-hardstop-touch-nothing-1", "seal-scripts-hardstop-1", test="TST-merge_execute-sealed_workspace_rerun_hardstops")
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


@pytest.mark.spec("archive-whole-control-dir-1", test="TST-merge_execute-reseal_archives_the_control_directory_with_merges_records")
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
    conn.execute("INSERT INTO original_values VALUES ('NEW', '6-photos-by-dest/Trip/ts.jpg', '{}', 't')")
    conn.execute("INSERT INTO meta VALUES ('a-prep-row', 'v')")
    conn.commit()
    conn.close()
    before = _rows(db, skip=("library_fingerprint_cache",))
    assert merge._run_locked_workflow("plan", str(ws)) == 0
    assert merge._run_locked_workflow("execute", str(ws)) == 0
    assert _rows(db, skip=("library_fingerprint_cache",)) == before
    assert _rows(db)["library_fingerprint_cache"]                      # its own part: written


@pytest.mark.spec("RUL-one_database", "RUL-other_databases_scratch", test="TST-merge_execute-one_database_in_the_workspace_none_in_the_library")
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
    assert set(listed) <= {"Trip", "."} and not walked     # the top folder: only for merge's own temporaries
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
def test_merge_snapshots_the_workspace_and_the_library(tmp_path, monkeypatch, datasets, expected):
    """Merge snapshots the workspace — it removes what it places from there — and the library beside
    it where the library can be snapshotted; a library that cannot be only narrows the snapshot, with a
    warning, and the merge proceeds."""
    ws, lib = _ws(tmp_path, [{"fp": "A", "dest": "Trip", "final_name": "a.jpg"}])
    taken = _zfs(monkeypatch, ws, datasets=datasets)
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
