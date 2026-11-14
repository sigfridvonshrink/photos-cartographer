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

"""Phase 3b — band guard, nested-dump flattening, prune-quarantine, footprint.

Mocked hashing/metadata (content-based hash so identical files dedup), fast.
photos_1_prep / photos_utils come from conftest.py.
"""
import json
import os

import pytest

import photos_1_prep as prep
import photos_utils as utils


def _ws(tmp_path):
    ws = tmp_path / "ws"
    ws.mkdir()
    for d in ("0-sources", "1-strays", "2-missing-metadata", "3-redundant-jpgs",
              "4-videos-by-date", "5-photos-by-date", "6-photos-by-dest"):
        (ws / d).mkdir()
    (ws / ".photos-ingest").mkdir(exist_ok=True)
    (ws / ".photos-ingest" / "photos-00-workspace-guard").touch()
    return ws


def _mock(monkeypatch):
    def spy(p):
        with open(p, "rb") as f:
            return {"status": "valid", "strategy": "image-content-hash-v1",
                    "value": "sig-" + f.read().hex()[:16], "engine_version": "t"}
    monkeypatch.setattr(prep.ContentHasher, "fingerprint_image", spy)
    monkeypatch.setattr(prep.ContentHasher, "fingerprint_video",
                        lambda p: {"status": "valid", "strategy": "video-md5-v1", "value": "vsig"})

    def meta(folders, max_workers=4, progress_coordinator=None):
        res = {}
        for folder in folders:
            for f in os.listdir(folder):
                res[os.path.join(folder, f)] = {
                    "DateTimeOriginal": "2023:01:02 03:04:05",
                    "extraction_status": "extracted_ok",
                }
        return res, set()
    monkeypatch.setattr(utils.MetadataReader, "read_metadata_concurrently", meta)


def _plan(ws):
    prep.CONFIG["jobs"] = 1
    return prep.WorkspacePrepWorkflow(str(ws), prep.WorkspaceCache(str(ws), in_memory=True)).plan()


def _seed_quarantine(ws):
    """Force a content duplicate so one copy is quarantined under a <plan_id> dir."""
    (ws / "0-sources" / "dup1.jpg").write_bytes(b"SAME")
    (ws / "0-sources" / "dup2.jpg").write_bytes(b"SAME")
    prep.PlanExecutor(str(ws)).execute(_plan(ws))
    qbase = utils.quarantine_dir(str(ws))
    pids = [e.name for e in os.scandir(qbase) if e.is_dir()]
    assert pids, "expected a quarantine plan-id dir"
    return pids[0]


# --- band-misplacement guard -------------------------------------------------

@pytest.mark.spec("RUL-band_misplacement_blocks", test="TST-guards_quarantine-band_guard_blocks_video_under_photo_band")
def test_band_guard_blocks_video_under_photo_band(tmp_path, monkeypatch):
    _mock(monkeypatch)
    ws = _ws(tmp_path)
    (ws / "5-photos-by-date" / "x.mp4").write_bytes(b"vid")
    plan = _plan(ws)
    assert any("Band misplacement" in b and "x.mp4" in b for b in plan.blockers), plan.blockers


@pytest.mark.spec("RUL-band_misplacement_blocks", test="TST-guards_quarantine-band_guard_blocks_raw_under_video_band")
def test_band_guard_blocks_raw_under_video_band(tmp_path, monkeypatch):
    _mock(monkeypatch)
    ws = _ws(tmp_path)
    (ws / "4-videos-by-date" / "x.arw").write_bytes(b"raw")
    plan = _plan(ws)
    assert any("Band misplacement" in b and "x.arw" in b for b in plan.blockers), plan.blockers


def test_band_guard_allows_correct_placement(tmp_path, monkeypatch):
    _mock(monkeypatch)
    ws = _ws(tmp_path)
    (ws / "5-photos-by-date" / "p.jpg").write_bytes(b"img")
    (ws / "4-videos-by-date" / "v.mp4").write_bytes(b"vid")
    plan = _plan(ws)
    assert not any("Band misplacement" in b for b in plan.blockers), plan.blockers


# (nested-dump flattening removed in Phase B: the new model does NOT flatten — an initialized
# workspace blocks a root dump, and an uninitialized one init-moves it into 0-sources with its
# structure preserved. Those paths are covered by test_lifecycle.py.)


# --- prune-quarantine --------------------------------------------------------

@pytest.mark.spec("BLD-prune_command", "RUL-prune_explicit", test="TST-guards_quarantine-prune_dry_run_deletes_nothing")
def test_prune_dry_run_deletes_nothing(tmp_path, monkeypatch):
    _mock(monkeypatch)
    ws = _ws(tmp_path)
    pid = _seed_quarantine(ws)
    prep.prune_quarantine(str(ws), do_delete=False)
    assert os.path.isdir(os.path.join(utils.quarantine_dir(str(ws)), pid))


@pytest.mark.spec("BLD-prune_command", "RUL-prune_explicit", test="TST-guards_quarantine-prune_yes_with_plan_id_deletes_only_that")
def test_prune_yes_with_plan_id_deletes_only_that(tmp_path, monkeypatch):
    _mock(monkeypatch)
    ws = _ws(tmp_path)
    pid = _seed_quarantine(ws)
    qbase = utils.quarantine_dir(str(ws))
    prep.prune_quarantine(str(ws), plan_ids=[pid], do_delete=True)
    assert not os.path.exists(os.path.join(qbase, pid))


@pytest.mark.spec("BLD-prune_command", "RUL-prune_explicit", test="TST-guards_quarantine-prune_yes_without_selector_or_all_refuses")
def test_prune_yes_without_selector_or_all_refuses(tmp_path, monkeypatch):
    _mock(monkeypatch)
    ws = _ws(tmp_path)
    pid = _seed_quarantine(ws)
    with pytest.raises(RuntimeError, match="Refusing to delete all quarantine"):
        prep.prune_quarantine(str(ws), do_delete=True)
    assert os.path.isdir(os.path.join(utils.quarantine_dir(str(ws)), pid))  # untouched


@pytest.mark.spec("BLD-prune_command", test="TST-guards_quarantine-prune_by_age_reads_the_plan_id_time")
def test_prune_by_age_reads_the_plan_id_time(tmp_path):
    """A run's age is the time in its plan id; --plan-id and --older-than-days together select the runs
    either names."""
    ws = _ws(tmp_path)
    qbase = utils.quarantine_dir(str(ws))
    old, new, named = "20200101T000000Z-aaaaaa", "20991231T000000Z-bbbbbb", "20991230T000000Z-cccccc"
    for pid in (old, new, named):
        os.makedirs(os.path.join(qbase, pid))
        with open(os.path.join(qbase, pid, "x.jpg"), "wb") as f:
            f.write(b"x")
        os.utime(os.path.join(qbase, pid), (0, 0))         # file times play no part
    prep.prune_quarantine(str(ws), plan_ids=[named], older_than_days=30, do_delete=True)
    assert sorted(os.listdir(qbase)) == [new]



# --- footprint ---------------------------------------------------------------

@pytest.mark.spec("RUL-quarantine_footprint_reported", test="TST-guards_quarantine-footprint_reports_quarantine")
def test_footprint_reports_quarantine(tmp_path, monkeypatch):
    _mock(monkeypatch)
    ws = _ws(tmp_path)
    _seed_quarantine(ws)
    qf = _plan(ws).summary["quarantine_footprint"]
    assert qf["plan_id_dirs"] >= 1
    assert qf["total_files"] >= 1
    assert qf["total_bytes"] > 0
    assert qf["oldest_plan_id"] and qf["newest_plan_id"]


# --- quarantine manifest: never silently truncate recoverable history (prep §15) -------------

def test_quarantine_manifest_corruption_is_preserved_not_truncated(tmp_path):
    """A corrupt manifest.json must be preserved under a .corrupt backup (so the prior records stay
    recoverable), not silently overwritten with a fresh single-entry file."""
    mdir = tmp_path / ".photos-ingest-quarantine" / "plan-x"
    mdir.mkdir(parents=True)
    (mdir / "manifest.json").write_text("{ this is not valid json")          # corrupt
    prep._append_quarantine_manifest(str(mdir), {"operation_id": "op-2", "original_path": "b.jpg"})

    backups = list(mdir.glob("manifest.json.corrupt-*"))
    assert len(backups) == 1
    assert backups[0].read_text() == "{ this is not valid json"               # corrupt bytes kept
    assert json.loads((mdir / "manifest.json").read_text()) == \
        [{"operation_id": "op-2", "original_path": "b.jpg"}]                  # fresh, valid manifest


def test_quarantine_manifest_appends_preserving_history(tmp_path):
    """The normal path keeps appending; a valid manifest is never backed up."""
    mdir = tmp_path / "qd"; mdir.mkdir()
    prep._append_quarantine_manifest(str(mdir), {"operation_id": "op-1"})
    prep._append_quarantine_manifest(str(mdir), {"operation_id": "op-2"})
    entries = json.loads((mdir / "manifest.json").read_text())
    assert [e["operation_id"] for e in entries] == ["op-1", "op-2"]           # history intact
    assert not list(mdir.glob("*.corrupt-*"))


def test_quarantine_manifest_non_array_is_treated_as_corrupt(tmp_path):
    """A syntactically-valid manifest that is not a JSON array (e.g. hand-edited to an object) is
    also preserved rather than crashing the append."""
    mdir = tmp_path / "qd"; mdir.mkdir()
    (mdir / "manifest.json").write_text('{"oops": "object not array"}')
    prep._append_quarantine_manifest(str(mdir), {"operation_id": "op-1"})
    assert len(list(mdir.glob("manifest.json.corrupt-*"))) == 1
    assert json.loads((mdir / "manifest.json").read_text()) == [{"operation_id": "op-1"}]


# --- dump dotfile quarantine + managed-folder prune protection -----------------

def _dump_dotfile_ops(plan):
    return sorted(op.source for op in plan.operations
                  if op.type == "quarantine_move" and op.verification.get("kind") == "dump_dotfile")


@pytest.mark.spec("RUL-dump_hidden_files_quarantined", test="TST-guards_quarantine-0sources_dotfiles_quarantined")
def test_0sources_dotfiles_quarantined(tmp_path, monkeypatch):
    _mock(monkeypatch)
    ws = _ws(tmp_path)
    (ws / "0-sources" / ".DS_Store").write_bytes(b"junk")
    (ws / "0-sources" / ".thumbnails").mkdir()
    (ws / "0-sources" / ".thumbnails" / "t.jpg").write_bytes(b"thumb")
    (ws / "0-sources" / "real.jpg").write_bytes(b"img")        # genuine media still organized
    # control dir and read-only by-dest must be left alone
    (ws / ".photos-ingest" / ".hidden").write_bytes(b"keep")
    (ws / "6-photos-by-dest" / ".DS_Store").write_bytes(b"keep")

    plan = _plan(ws)
    assert _dump_dotfile_ops(plan) == ["0-sources/.DS_Store", "0-sources/.thumbnails/t.jpg"]
    assert not any(".photos-ingest" in op.source or op.source.startswith("6-photos-by-dest")
                   for op in plan.operations if op.source)

    prep.PlanExecutor(str(ws)).execute(plan)
    assert not (ws / "0-sources" / ".DS_Store").exists()
    assert not (ws / "0-sources" / ".thumbnails").exists()     # emptied dot-dir skeleton pruned
    assert (ws / ".photos-ingest" / ".hidden").exists()        # control dir untouched
    assert (ws / "6-photos-by-dest" / ".DS_Store").exists()    # read-only by-dest untouched
    moved = [f for _r, _d, fs in os.walk(utils.quarantine_dir(str(ws))) for f in fs]
    assert ".DS_Store" in moved and "t.jpg" in moved


@pytest.mark.spec("RUL-dump_hidden_files_quarantined")
def test_init_root_dotfiles_quarantined(tmp_path, monkeypatch):
    _mock(monkeypatch)
    ws = tmp_path / "ws"; ws.mkdir()                           # uninitialized (no guard / no 0-6)
    (ws / ".DS_Store").write_bytes(b"junk")
    (ws / ".cache").mkdir(); (ws / ".cache" / "c.dat").write_bytes(b"x")
    (ws / "Dump").mkdir(); (ws / "Dump" / ".hiddennote").write_bytes(b"n")   # nested hidden in plain dump dir
    (ws / "Dump" / "real.jpg").write_bytes(b"img")

    plan = _plan(ws)
    assert _dump_dotfile_ops(plan) == [".DS_Store", ".cache/c.dat", "Dump/.hiddennote"]

    prep.PlanExecutor(str(ws)).execute(plan)
    assert not (ws / ".DS_Store").exists()
    assert not (ws / ".cache").exists()                        # emptied dump dot-dir pruned
    assert (ws / ".photos-ingest" / "photos-00-workspace-guard").exists()    # init completed


def test_prune_never_removes_managed_folders_even_when_empty(tmp_path, monkeypatch):
    _mock(monkeypatch)
    ws = _ws(tmp_path)                                          # initialized, all 0-6 empty
    plan = _plan(ws)
    prep.PlanExecutor(str(ws)).execute(plan)                    # success path runs _prune_empty_dirs
    for d in ("0-sources", "1-strays", "2-missing-metadata", "3-redundant-jpgs",
              "4-videos-by-date", "5-photos-by-date", "6-photos-by-dest"):
        assert (ws / d).is_dir(), f"managed folder {d} must survive pruning even when empty"


def _rmdirs(plan):
    return [op.source for op in plan.operations if op.type == "rmdir"]


@pytest.mark.spec("RUL-emptied_folders_removed", "BLD-folder_removals",
                  test="TST-guards_quarantine-folders_left_empty_are_planned_removals")
def test_folders_left_empty_are_planned_removals(tmp_path, monkeypatch):
    """The folders a plan leaves empty — emptied by its moves, or empty already — are planned removals,
    deepest first, journaled as they run; a folder holding a file the plan leaves is not."""
    _mock(monkeypatch)
    ws = _ws(tmp_path)
    (ws / "0-sources" / "card" / "DCIM").mkdir(parents=True)
    (ws / "0-sources" / "card" / "DCIM" / "a.jpg").write_bytes(b"img")
    (ws / "0-sources" / "empty").mkdir()
    (ws / "5-photos-by-date" / "2020-01-01").mkdir()
    plan = _plan(ws)
    assert _rmdirs(plan) == ["0-sources/card/DCIM", "0-sources/card", "0-sources/empty",
                             "5-photos-by-date/2020-01-01"]
    prep.PlanExecutor(str(ws)).execute(plan)
    assert os.listdir(ws / "0-sources") == []
    assert not (ws / "5-photos-by-date" / "2020-01-01").exists()
    journal = json.load(open(utils.journal_path(str(ws), plan.plan_id)))
    ids = {op.operation_id for op in plan.operations if op.type == "rmdir"}
    assert {o["operation_id"] for o in journal["operations"] if o["status"] == "success"} >= ids


@pytest.mark.spec("RUL-emptied_folders_removed", test="TST-guards_quarantine-a_folder_not_empty_at_execute_is_left")
def test_a_folder_not_empty_at_execute_is_left(tmp_path, monkeypatch, capsys):
    """A planned removal finding its folder not empty leaves it, skipped in the journal and reported; the
    run still succeeds."""
    _mock(monkeypatch)
    ws = _ws(tmp_path)
    (ws / "0-sources" / "empty").mkdir()
    plan = _plan(ws)
    assert _rmdirs(plan) == ["0-sources/empty"]
    (ws / "0-sources" / "empty" / "late").mkdir()               # no file: the plan is still current
    prep.PlanExecutor(str(ws)).execute(plan)
    assert (ws / "0-sources" / "empty" / "late").is_dir()
    journal = json.load(open(utils.journal_path(str(ws), plan.plan_id)))
    (r,) = [o for o in journal["operations"] if o["operation_id"] == plan.operations[-1].operation_id]
    assert r["status"] == "skipped" and "still contains: late" in r["details"]["reason"]
    out = capsys.readouterr()
    assert "left the folder 0-sources/empty/ in place" in out.err + out.out
    assert os.path.exists(utils.handoff_path(str(ws)))


@pytest.mark.spec("RUL-emptied_folders_removed", "BLD-folder_removals",
                  test="TST-guards_quarantine-a_hidden_top_level_folder_is_the_users")
def test_a_hidden_top_level_folder_is_the_users(tmp_path, monkeypatch):
    """Once the workspace is initialized, an empty hidden folder at the top level is the user's: no plan
    removes it."""
    _mock(monkeypatch)
    ws = _ws(tmp_path)
    (ws / ".mine").mkdir()
    plan = _plan(ws)
    assert _rmdirs(plan) == []
    prep.PlanExecutor(str(ws)).execute(plan)
    assert (ws / ".mine").is_dir()
