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

"""A RAW the user culls takes the JPEG prep set aside beside it into the quarantine (RUL-culled_raw_takes_its_jpeg):
known culled by its fingerprint — gone from every file prep scans, and found deleted by hand by a workspace check —
never by its path. Prep runs end to end with metadata and fingerprints mocked; the check is the real one."""
import json
import os

import pytest

import photos_1_prep as prep
import photos_utils as utils

MANAGED = ["0-sources", "1-strays", "2-missing-metadata", "3-redundant-jpgs",
           "4-videos-by-date", "5-photos-by-date", "6-photos-by-dest"]
QUARANTINE = ".photos-ingest-quarantine"


def _ws(tmp_path):
    ws = tmp_path / "ws"
    ws.mkdir()
    for d in MANAGED:
        (ws / d).mkdir()
    (ws / ".photos-ingest").mkdir()
    (ws / ".photos-ingest" / "photos-00-workspace-guard").touch()
    return ws


def _install(monkeypatch):
    prep.CONFIG["zfs"] = {"enabled": False}
    prep.CONFIG["jobs"] = 1

    def hsh(p):
        with open(p, "rb") as f:
            return {"status": "valid", "strategy": "image-content-hash-v2",
                    "value": "sig-" + f.read().hex()[:16], "engine_version": "t"}
    monkeypatch.setattr(prep.ContentHasher, "fingerprint_image", hsh)
    monkeypatch.setattr(prep.ContentHasher, "fingerprint_video", lambda p: dict(hsh(p), strategy="video"))
    times = {b"RAW1": "2023:01:02 03:04:05", b"JPG1": "2023:01:02 03:04:05", b"MOV1": "2023:01:02 03:04:05",
             b"RAW2": "2023:01:02 05:00:00", b"DNG2": "2023:01:02 05:00:00", b"JPG2": "2023:01:02 05:00:00",
             b"RAW3": "2023:01:02 07:00:00", b"JPG3": "2023:01:02 07:00:00"}

    def meta(folders, max_workers=4, progress_coordinator=None):
        res = {}
        for fo in folders:
            for fn in os.listdir(fo):
                with open(os.path.join(fo, fn), "rb") as f:
                    t = times.get(f.read(4), "2023:01:02 09:00:00")
                res[os.path.join(fo, fn)] = {"DateTimeOriginal": t, "extraction_status": "extracted_ok"}
        return res, set()
    monkeypatch.setattr(utils.MetadataReader, "read_metadata_concurrently", meta)


def _sig(content):
    return "sig-" + content.hex()[:16]


def _check(ws):
    changes, stop = utils.check_workspace(str(ws), "prep", "plan")
    assert stop is None
    return changes


def _plan(ws, changes=()):
    cache = prep.WorkspaceCache(str(ws))
    try:
        return prep.WorkspacePrepWorkflow(str(ws), cache, workspace_changes=changes).plan()
    finally:
        cache.close()


def _run(ws, changes=()):
    plan = _plan(ws, changes)
    assert not plan.blockers, plan.blockers
    prep.PlanExecutor(str(ws), workspace_changes=changes).execute(plan)
    return plan


def _find(ws, folder, content):
    for root, _dirs, names in os.walk(ws / folder):
        for n in names:
            p = os.path.join(root, n)
            with open(p, "rb") as f:
                if f.read() == content:
                    return os.path.relpath(p, str(ws))
    return None


def _culled_ops(plan):
    return [op for op in plan.operations if op.type == "quarantine_move"
            and (op.verification or {}).get("kind") == "raw_culled"]


def _dumped(tmp_path, monkeypatch):
    """A dump of a RAW+JPEG pair, its camera's live video beside it, a JPEG beside two RAWs of its name — a pair prep
    records for neither — and a third pair; prepped."""
    _install(monkeypatch)
    ws = _ws(tmp_path)
    for folder, name, content in (("a", "DSC_1.ARW", b"RAW1"), ("a", "DSC_1.JPG", b"JPG1"), ("a", "DSC_1.MOV", b"MOV1"),
                                  ("b", "DSC_2.ARW", b"RAW2"), ("b", "DSC_2.DNG", b"DNG2"), ("b", "DSC_2.JPG", b"JPG2"),
                                  ("c", "DSC_3.ARW", b"RAW3"), ("c", "DSC_3.JPG", b"JPG3")):
        (ws / "0-sources" / folder).mkdir(exist_ok=True)
        (ws / "0-sources" / folder / name).write_bytes(content)
    _run(ws)
    assert _find(ws, "3-redundant-jpgs", b"JPG1") and _find(ws, "4-videos-by-date", b"MOV1")
    return ws


@pytest.mark.spec("RUL-culled_raw_takes_its_jpeg", "RUL-culled_raw_known_by_content", "RUL-culled_raw_jpeg_logged",
                  "RUL-culled_raw_jpeg_recorded", "BLD-culled_raw_found", "BLD-quarantine_reasons", "RUL-quarantine_never_auto_deleted",
                  test="TST-culled_raw-culled_in_photos_by_date_takes_its_jpeg")
def test_culled_in_photos_by_date_takes_its_jpeg(tmp_path, monkeypatch):
    """A RAW deleted by hand from photos by date: the next plan quarantines its set-aside JPEG — recoverable, with its
    evidence — and nothing else; prep's log records the JPEG's step as its RAW culled, naming the RAW by path and
    fingerprint; the execution records the move as its own, so the next check finds no change. The RAW's video and a
    JPEG whose pair was never recorded stay where they are, their RAWs culled too."""
    ws = _dumped(tmp_path, monkeypatch)
    raw = _find(ws, "5-photos-by-date", b"RAW1")
    jpeg = _find(ws, "3-redundant-jpgs", b"JPG1")
    unpaired = _find(ws, "3-redundant-jpgs", b"JPG2")
    video = _find(ws, "4-videos-by-date", b"MOV1")
    for gone in (raw, _find(ws, "5-photos-by-date", b"RAW2"), _find(ws, "5-photos-by-date", b"DNG2")):
        os.remove(ws / gone)                                       # culled by hand

    changes = _check(ws)
    assert {c["path"] for c in changes if c["kind"] == "deleted"} >= {raw}
    plan = _run(ws, changes)
    [op] = _culled_ops(plan)
    assert op.source == jpeg and op.destination.startswith(QUARANTINE + "/")
    assert (op.verification["raw_path"], op.verification["raw_fingerprint"]) == (raw, _sig(b"RAW1"))
    assert not [b for b in plan.blockers if "Misnamed" in b]

    assert not (ws / jpeg).exists() and (ws / op.destination).read_bytes() == b"JPG1"   # quarantined, not deleted
    assert (ws / unpaired).exists() and (ws / video).exists() and _find(ws, "3-redundant-jpgs", b"JPG3")
    with open(ws / QUARANTINE / op.destination.split("/")[1] / "manifest.json") as f:
        manifest = json.load(f)                                    # its evidence, written before it was moved
    assert [(e["kind"], e["original_path"], e["raw_path"], e["raw_fingerprint"]) for e in manifest] == \
        [("raw_culled", jpeg, raw, _sig(b"RAW1"))]

    with open(utils.prep_log_path(str(ws))) as f:
        entry = json.load(f)["photos"][_sig(b"JPG1")]
    step = entry["journey"][-1]
    assert (step["action"], step["from"], step["to"], step["raw_path"], step["raw_fingerprint"]) == \
        ("raw_culled", jpeg, op.destination, raw, _sig(b"RAW1"))
    assert entry["prep_path"] == op.destination

    with open(utils.handoff_path(str(ws))) as f:
        handoff = json.load(f)
    assert {"kind": "raw_culled", "original_path": jpeg, "quarantine_path": op.destination} in \
        handoff["diagnostics"]["quarantined_not_duplicates"]

    record_id, record = utils.read_workspace_record(str(ws))
    assert utils.compare_workspace(record, utils.workspace_entries(str(ws))) == []   # the move is the run's own
    assert _check(ws) == []
    assert not _culled_ops(_plan(ws))                              # planned again: nothing more to take


@pytest.mark.spec("RUL-culled_raw_takes_its_jpeg", "RUL-culled_raw_known_by_content", "BLD-culled_raw_found",
                  test="TST-culled_raw-a_raw_moved_and_renamed_takes_nothing")
def test_a_raw_moved_and_renamed_takes_nothing(tmp_path, monkeypatch):
    """A RAW sorted into photos by destination and renamed there, or copied there under a new name and the original
    deleted, is not culled: its fingerprint is still held, so its JPEG stays. Taken back into the inbox, it is held
    there too."""
    ws = _dumped(tmp_path, monkeypatch)
    raw1, raw3 = _find(ws, "5-photos-by-date", b"RAW1"), _find(ws, "5-photos-by-date", b"RAW3")
    (ws / "6-photos-by-dest" / "Trip").mkdir()
    os.rename(ws / raw1, ws / "6-photos-by-dest" / "Trip" / "kept.arw")              # sorted and renamed
    (ws / "0-sources" / "back").mkdir()
    (ws / "0-sources" / "back" / "again.arw").write_bytes(b"RAW3")                     # a copy in the inbox ...
    os.remove(ws / raw3)                                                               # ... the original deleted
    changes = _check(ws)
    assert raw3 in {c["path"] for c in changes if c["kind"] == "deleted"}
    plan = _plan(ws, changes)
    assert not _culled_ops(plan)
    assert _find(ws, "3-redundant-jpgs", b"JPG1") and _find(ws, "3-redundant-jpgs", b"JPG3")


@pytest.mark.spec("RUL-culled_raw_moved_out", "RUL-culled_raw_takes_its_jpeg", "BLD-culled_raw_found",
                  test="TST-culled_raw-a_raw_moved_out_of_the_workspace_takes_its_jpeg")
@pytest.mark.parametrize("folder", ["5-photos-by-date", "6-photos-by-dest"])
def test_a_raw_moved_out_of_the_workspace_takes_its_jpeg(tmp_path, monkeypatch, folder):
    """A RAW moved out of the workspace — kept whole elsewhere, under its own inode — is culled as surely as one
    deleted: the check finds it gone, no file prep scans holds it, and its set-aside JPEG goes to the quarantine."""
    ws = _dumped(tmp_path, monkeypatch)
    raw = _find(ws, "5-photos-by-date", b"RAW1")
    if folder == "6-photos-by-dest":
        (ws / "6-photos-by-dest" / "Trip").mkdir()
        name = raw.rsplit("/", 1)[-1]
        os.rename(ws / raw, ws / "6-photos-by-dest" / "Trip" / name)     # sorted first
        raw = "6-photos-by-dest/Trip/" + name
        _run(ws, _check(ws))
    outside = tmp_path / "elsewhere"
    outside.mkdir()
    inode = os.stat(ws / raw).st_ino
    os.rename(ws / raw, outside / "kept.arw")                      # moved out, not deleted
    assert os.stat(outside / "kept.arw").st_ino == inode

    changes = _check(ws)
    plan = _run(ws, changes)
    [op] = _culled_ops(plan)
    assert (ws / op.destination).read_bytes() == b"JPG1" and not _find(ws, "3-redundant-jpgs", b"JPG1")
    assert (op.verification["raw_path"], op.verification["raw_fingerprint"]) == (raw, _sig(b"RAW1"))
    assert (outside / "kept.arw").read_bytes() == b"RAW1"          # the RAW itself is never touched


@pytest.mark.spec("RUL-culled_raw_takes_its_jpeg", "RUL-culled_raw_known_by_content", "BLD-culled_raw_found",
                  test="TST-culled_raw-a_raw_gone_unseen_by_a_check_takes_nothing")
def test_a_raw_gone_unseen_by_a_check_takes_nothing(tmp_path, monkeypatch):
    """A RAW's fingerprint held by no file is not enough: without a check that found it deleted by hand — a
    fingerprint taken again another way leaves the same absence — the JPEG stays."""
    ws = _dumped(tmp_path, monkeypatch)
    os.remove(ws / _find(ws, "5-photos-by-date", b"RAW1"))
    assert not _culled_ops(_plan(ws, changes=()))


@pytest.mark.spec("RUL-culled_raw_takes_its_jpeg", "RUL-culled_raw_known_by_content", "BLD-culled_raw_found",
                  test="TST-culled_raw-a_cull_seen_by_an_earlier_run_still_takes_the_jpeg")
def test_a_cull_seen_by_an_earlier_run_still_takes_the_jpeg(tmp_path, monkeypatch):
    """A cull a geotag execution's check found, recorded since in its summary, still takes the JPEG at the next prep
    plan, when that plan's own check no longer sees it."""
    ws = _dumped(tmp_path, monkeypatch)
    raw = _find(ws, "5-photos-by-date", b"RAW1")
    os.remove(ws / raw)
    changes = _check(ws)
    summary = ws / ".photos-ingest" / "photos-25-execution-summary.json"
    summary.write_text(json.dumps({"plan_id": "g1", "status": "success", "workspace_changes": changes}))
    utils.write_workspace_record(str(ws))                          # that execution recorded the state it left
    assert _check(ws) == []
    [op] = _culled_ops(_plan(ws, changes=()))
    assert op.verification["raw_path"] == raw


@pytest.mark.spec("RUL-culled_raw_takes_its_jpeg", "RUL-allowed_changes_named", "BLD-workspace_changes_logged",
                  "BLD-culled_raw_found", test="TST-culled_raw-a_cull_passed_by_a_failed_execute_still_takes_the_jpeg")
def test_a_cull_passed_by_a_failed_execute_still_takes_the_jpeg(tmp_path, monkeypatch):
    """An execute whose check passed a cull, and whose quarantine move then fails, still logs the cull in prep's log
    before recording the state it leaves: the next check sees nothing, and the next plan quarantines the JPEG."""
    ws = _dumped(tmp_path, monkeypatch)
    raw = _find(ws, "5-photos-by-date", b"RAW1")
    jpeg = _find(ws, "3-redundant-jpgs", b"JPG1")
    os.remove(ws / raw)                                            # culled by hand
    changes = _check(ws)
    plan = _plan(ws, changes)
    assert len(_culled_ops(plan)) == 1

    def fail(src, dst):
        raise OSError("the disk said no")
    monkeypatch.setattr(prep, "_move_no_clobber", fail)
    with pytest.raises(prep.ExecuteFailed):
        prep.PlanExecutor(str(ws), workspace_changes=changes).execute(plan)
    monkeypatch.undo()
    _install(monkeypatch)

    assert (ws / jpeg).exists()                                    # the move failed: the JPEG is where it was
    assert _check(ws) == []                                        # the failed run recorded the state it left ...
    with open(utils.prep_log_path(str(ws))) as f:
        logged = json.load(f)["workspace_changes"]
    assert [(c["kind"], c["path"], c["run"]) for c in logged if c["kind"] == "deleted"] == \
        [("deleted", raw, plan.plan_id)]                           # ... and logged the cull its check passed
    [op] = _culled_ops(_plan(ws, changes=()))
    assert op.source == jpeg and op.verification["raw_path"] == raw
