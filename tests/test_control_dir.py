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

"""Phase 1 — control-directory layout.

Verifies that every pipeline control/artifact file lands under `.photos-ingest/`
with the spec names, that journals are per-run and retained, that the media scan
skips the control directory wholesale, and that the workspace guard is enforced.

Uses mocked hashing/metadata so these are fast and need no external tools.
photos_1_prep / photos_utils are loaded once by conftest.py into sys.modules.
"""
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
    monkeypatch.setattr(
        prep.ContentHasher, "fingerprint_image",
        lambda p: {"status": "valid", "strategy": "image-content-hash-v2",
                   "value": "sig-" + os.path.basename(p), "engine_version": "t"},
    )

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


@pytest.mark.spec("RUL-config_never_media", "RUL-control_records_together", "RUL-plan_at_fixed_place", test="TST-control_dir-control_files_land_under_control_dir")
def test_control_files_land_under_control_dir(tmp_path, monkeypatch):
    _mock(monkeypatch)
    ws = _ws(tmp_path)
    (ws / "0-sources" / "a.jpg").write_text("aaa")
    prep.CONFIG["jobs"] = 1

    cache = prep.WorkspaceCache(str(ws))
    plan = prep.WorkspacePrepWorkflow(str(ws), cache).plan()
    cache.close()
    prep.PlanExecutor(str(ws)).execute(plan)  # no journal arg -> default control-dir location

    assert os.path.exists(utils.db_path(str(ws)))          # .photos-ingest/photos-00-ingest.db
    assert os.path.exists(utils.handoff_path(str(ws)))     # .photos-ingest/photos-11-handoff.json
    assert os.path.exists(utils.journal_path(str(ws), plan.plan_id))  # .photos-ingest/journal-<id>.json

    # Nothing pipeline-related sits at the workspace root.
    root_entries = set(os.listdir(str(ws)))
    assert ".photos_ingest.db" not in root_entries
    assert "photos-11-handoff.json" not in root_entries
    assert not any(e.endswith(".photos-ingest/journal.json") or e.startswith("journal") for e in root_entries)


@pytest.mark.spec("RUL-history_retained", test="TST-control_dir-journals_are_per_run_and_retained")
def test_journals_are_per_run_and_retained(tmp_path, monkeypatch):
    _mock(monkeypatch)
    ws = _ws(tmp_path)
    (ws / "0-sources" / "a.jpg").write_text("aaa")
    prep.CONFIG["jobs"] = 1

    p1 = prep.WorkspacePrepWorkflow(str(ws), prep.WorkspaceCache(str(ws))).plan()
    prep.PlanExecutor(str(ws)).execute(p1)
    p2 = prep.WorkspacePrepWorkflow(str(ws), prep.WorkspaceCache(str(ws))).plan()
    prep.PlanExecutor(str(ws)).execute(p2)

    assert p1.plan_id != p2.plan_id
    # The first run's journal is not overwritten by the second.
    assert os.path.exists(utils.journal_path(str(ws), p1.plan_id))
    assert os.path.exists(utils.journal_path(str(ws), p2.plan_id))


@pytest.mark.spec("RUL-config_writers")
def test_prep_seeds_config_once_then_never_rewrites_it(tmp_path, monkeypatch):
    """RUL-config_writers: prep is the SOLE writer of photos-00-config.json and only SEEDS it once — it never edits
    it thereafter. After the first run seeds the config, a second prep run leaves the on-disk
    photos-00-config.json byte-for-byte identical (no rewrite, no reformat, no fingerprint churn)."""
    _mock(monkeypatch)
    ws = _ws(tmp_path)
    (ws / "0-sources" / "a.jpg").write_text("aaa")
    prep.CONFIG["jobs"] = 1
    cfg_p = ws / ".photos-ingest" / "photos-00-config.json"

    p1 = prep.WorkspacePrepWorkflow(str(ws), prep.WorkspaceCache(str(ws))).plan()
    prep.PlanExecutor(str(ws)).execute(p1)
    assert cfg_p.exists()                                            # seeded on the first run
    after_seed = cfg_p.read_bytes()

    (ws / "0-sources" / "b.jpg").write_text("bbb")                  # genuine new work for the 2nd run
    p2 = prep.WorkspacePrepWorkflow(str(ws), prep.WorkspaceCache(str(ws))).plan()
    prep.PlanExecutor(str(ws)).execute(p2)
    assert cfg_p.read_bytes() == after_seed                         # config never rewritten after seeding


@pytest.mark.spec("RUL-record_in_place_while_replaced", test="TST-control_dir-a_record_being_replaced_never_leaves_its_path")
def test_backup_existing_artifact_uses_incremental_suffix(tmp_path):
    """The shared backup primitive (used by every phase's canonical plan/decision save) copies a
    pre-existing artifact aside under the `-NNN` suffix and never clobbers it — the artifact itself stays
    in place, so a run killed before the new version is written still finds the decisions at their path."""
    p = tmp_path / "photos-10-prep-plan.json"
    assert utils.backup_existing_artifact(str(p)) is None      # nothing to back up yet
    p.write_text('{"v": 1}')
    b1 = utils.backup_existing_artifact(str(p))
    assert os.path.basename(b1) == "photos-10-prep-plan-001.json"
    assert p.read_text() == '{"v": 1}' and os.path.exists(b1)  # copied aside; the artifact never leaves its path
    p.write_text('{"v": 2}')
    b2 = utils.backup_existing_artifact(str(p))
    assert os.path.basename(b2) == "photos-10-prep-plan-002.json"   # second backup advances the index
    import json as _json
    assert _json.load(open(b1))["v"] == 1 and _json.load(open(b2))["v"] == 2


@pytest.mark.spec("RUL-replanning_keeps_the_prior", test="TST-control_dir-write_versioned_json_backs_up_then_writes")
def test_write_versioned_json_backs_up_then_writes(tmp_path):
    p = tmp_path / "photos-30-merge-plan.json"
    sha1, bak1 = utils.write_versioned_json(str(p), {"plan": "a"})
    assert bak1 is None and sha1                               # first write: nothing to back up
    sha2, bak2 = utils.write_versioned_json(str(p), {"plan": "b"})
    assert os.path.basename(bak2) == "photos-30-merge-plan-001.json"
    import json as _json
    assert _json.load(open(p))["plan"] == "b"                  # canonical holds the new content
    assert _json.load(open(bak2))["plan"] == "a"              # prior content preserved in the backup


class _CutOffMidWrite:
    """A text file whose first write puts down half of what it was given and is then interrupted."""
    def __init__(self, f):
        self.f = f
    def write(self, s):
        self.f.write(s[:len(s) // 2]); self.f.flush()
        raise KeyboardInterrupt
    def __enter__(self):
        return self
    def __exit__(self, *exc):
        self.f.close()
    def __getattr__(self, name):
        return getattr(self.f, name)


@pytest.mark.parametrize("write", [utils.write_versioned_json, utils.write_json_artifact],
                         ids=["versioned", "artifact"])
@pytest.mark.spec("RUL-records_written_alike", test="TST-control_dir-the_same_content_is_written_as_the_same_bytes")
def test_the_same_content_is_written_as_the_same_bytes(tmp_path, write):
    """A record's bytes follow from its content alone: built in another order, on another run, the same content is
    the same file — and so the same hash to whatever depends on it; another content is another file."""
    one = {"b": {"z": 1, "a": [3, 1, 2]}, "a": "é", "c": None}
    same = {"c": None, "a": "é", "b": {"a": [3, 1, 2], "z": 1}}
    (tmp_path / "x").mkdir(); (tmp_path / "y").mkdir()
    write(str(tmp_path / "x" / "r.json"), one)
    write(str(tmp_path / "y" / "r.json"), same)
    assert (tmp_path / "x" / "r.json").read_bytes() == (tmp_path / "y" / "r.json").read_bytes()
    write(str(tmp_path / "y" / "r.json"), {**same, "c": 0})
    assert (tmp_path / "x" / "r.json").read_bytes() != (tmp_path / "y" / "r.json").read_bytes()


@pytest.mark.spec("RUL-rewrite_in_place_atomic", "BLD-rewrite_synced_before_rename",
                  test="TST-control_dir-a_rewritten_record_is_on_disk_before_it_replaces_the_earlier")
def test_a_rewritten_record_is_on_disk_before_it_replaces_the_earlier(tmp_path, monkeypatch):
    """A power cut: the new record is synced to disk whole before the rename that puts it in the earlier one's
    place, and the folder after."""
    import json
    import stat
    rec = tmp_path / "photos-21-time-decisions.json"
    utils.write_json_artifact(str(rec), {"v": 1})
    steps, real_fsync, real_replace = [], os.fsync, os.replace
    def _fsync(fd):
        st = os.fstat(fd)
        steps.append("sync folder" if stat.S_ISDIR(st.st_mode) else ("sync file" if st.st_size else "sync EMPTY file"))
        return real_fsync(fd)
    def _replace(a, b):
        steps.append("rename")
        return real_replace(a, b)
    monkeypatch.setattr(os, "fsync", _fsync)
    monkeypatch.setattr(os, "replace", _replace)
    utils.write_json_artifact(str(rec), {"v": 2})
    assert steps == ["sync file", "rename", "sync folder"]
    assert json.loads(rec.read_text()) == {"v": 2}


@pytest.mark.parametrize("rewrite", [utils.write_versioned_json, utils.write_json_artifact],
                         ids=["versioned", "artifact"])
@pytest.mark.spec("RUL-rewrite_in_place_atomic", test="TST-control_dir-an_interrupted_record_rewrite_leaves_the_record_whole")
def test_an_interrupted_record_rewrite_leaves_the_record_whole(tmp_path, monkeypatch, rewrite):
    """A record rewritten in place and interrupted holds its old content whole — whether the interruption
    comes while the new text is half written or just before it takes the record's place — and the next
    write puts the new content down whole."""
    import builtins
    import json as _json
    p = tmp_path / "photos-23-gps-decisions.json"
    rewrite(str(p), {"plan": "a"})
    before = p.read_bytes()
    new = {"plan": "b" * 100_000}

    real_open, real_fdopen = builtins.open, os.fdopen
    def cut(opener):
        def _open(file, mode="r", *a, **k):
            f = opener(file, mode, *a, **k)
            return _CutOffMidWrite(f) if ("w" in mode and "b" not in mode) else f
        return _open
    with monkeypatch.context() as m:                           # interrupted mid-write of the new text
        m.setattr(builtins, "open", cut(real_open))
        m.setattr(os, "fdopen", cut(real_fdopen))
        with pytest.raises(KeyboardInterrupt):
            rewrite(str(p), new)
    assert p.read_bytes() == before

    def interrupted_rename(*a, **k):
        raise KeyboardInterrupt
    with monkeypatch.context() as m:                           # interrupted with the new text written, not yet in place
        m.setattr(os, "replace", interrupted_rename)
        m.setattr(os, "rename", interrupted_rename)
        with pytest.raises(KeyboardInterrupt):
            rewrite(str(p), new)
    assert p.read_bytes() == before

    rewrite(str(p), new)                                       # uninterrupted: the new record, whole
    assert _json.loads(p.read_text()) == new


@pytest.mark.spec("RUL-rewrite_in_place_atomic",
                  test="TST-control_dir-an_interrupted_editor_save_leaves_the_decision_file_whole")
def test_an_interrupted_editor_save_leaves_the_decision_file_whole(tmp_path, monkeypatch):
    """A decision file the editor rewrites, interrupted — while the new text is half written, or with it written but
    not yet in the file's place — holds its earlier content whole. The temp file such an interruption leaves is no
    record: the archival package does not carry it, and the next save writes over it and puts the new content down
    whole."""
    import builtins
    import json as _json
    from cartographer.editor import server as editor
    cd = tmp_path / ".photos-ingest"; cd.mkdir()
    p = cd / "photos-21-time-decisions.json"
    left = cd / "photos-21-time-decisions.json.tmp"
    editor._write_json(str(p), {"v": 1})
    before = p.read_bytes()
    new = {"v": "x" * 100_000}
    real_open = builtins.open

    def open_cut(file, mode="r", *a, **k):
        f = real_open(file, mode, *a, **k)
        return _CutOffMidWrite(f) if (str(file) == str(left) and "w" in mode) else f

    def interrupted_rename(*a, **k):
        raise KeyboardInterrupt
    for cut in (lambda m: m.setattr(builtins, "open", open_cut),
                lambda m: (m.setattr(os, "replace", interrupted_rename), m.setattr(os, "rename", interrupted_rename))):
        with monkeypatch.context() as m:
            cut(m)
            with pytest.raises(KeyboardInterrupt):
                editor._write_json(str(p), new)
        assert p.read_bytes() == before
        assert left.exists()                                   # what the interruption leaves behind ...
        assert utils.control_archive_members(str(tmp_path)) == [".photos-ingest/photos-21-time-decisions.json"]
    editor._write_json(str(p), new)                            # ... the next save writes over
    assert _json.loads(p.read_text()) == new and not left.exists()


@pytest.mark.spec("RUL-control_records_never_media", test="TST-control_dir-media_inside_control_dir_is_not_inventoried")
def test_media_inside_control_dir_is_not_inventoried(tmp_path, monkeypatch):
    _mock(monkeypatch)
    ws = _ws(tmp_path)
    (ws / ".photos-ingest" / "sneaky.jpg").write_text("x")  # must be skipped wholesale
    (ws / "0-sources" / "real.jpg").write_text("aaa")
    prep.CONFIG["jobs"] = 1

    plan = prep.WorkspacePrepWorkflow(str(ws), prep.WorkspaceCache(str(ws), in_memory=True)).plan()
    touched = [op.source for op in plan.operations if op.source] + \
              [op.destination for op in plan.operations if op.destination]
    assert not any("sneaky" in (p or "") for p in touched), touched
    assert plan.blockers == [], plan.blockers
