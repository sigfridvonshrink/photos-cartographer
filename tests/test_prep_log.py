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

"""Phase C2 — end-of-prep transformation log (photos-15-prep-log.json, BLD-phase_logs).

A per-photo, content-fingerprint-keyed, human-readable record of everything prep did: derived
from the validated plan + quarantine evidence, carried forward incrementally. Mocked hashing/
metadata, fast. From conftest.py.
"""
import glob
import json
import os

import photos_1_prep as prep
import photos_utils as utils
import pytest

MANAGED = ["0-sources", "1-strays", "2-missing-metadata", "3-redundant-jpgs",
           "4-videos-by-date", "5-photos-by-date", "6-photos-by-dest"]


def _ws(tmp_path):
    ws = tmp_path / "ws"
    ws.mkdir()
    for d in MANAGED:
        (ws / d).mkdir()
    (ws / ".photos-ingest").mkdir()
    (ws / ".photos-ingest" / "photos-00-workspace-guard").touch()   # initialized (no init journey)
    return ws


def _install(monkeypatch):
    prep.CONFIG["zfs"] = {"enabled": False}
    prep.CONFIG["jobs"] = 1

    def hsh(p):
        with open(p, "rb") as f:
            return {"status": "valid", "strategy": "image-content-hash-v2",
                    "value": "sig-" + f.read().hex()[:16], "engine_version": "t"}
    monkeypatch.setattr(prep.ContentHasher, "fingerprint_image", hsh)

    def meta(folders, max_workers=4, progress_coordinator=None):
        res = {}
        for fo in folders:
            for fn in os.listdir(fo):
                res[os.path.join(fo, fn)] = {"DateTimeOriginal": "2023:01:02 03:04:05",
                                             "extraction_status": "extracted_ok"}
        return res, set()
    monkeypatch.setattr(utils.MetadataReader, "read_metadata_concurrently", meta)


def _run(ws):
    cache = prep.WorkspaceCache(str(ws))
    plan = prep.WorkspacePrepWorkflow(str(ws), cache).plan()
    cache.close()
    prep.PlanExecutor(str(ws)).execute(plan)


def _log(ws):
    with open(utils.prep_log_path(str(ws))) as f:
        return json.load(f)


@pytest.mark.spec("RUL-log_keyed_by_fingerprint", "RUL-log_carries_name_chain",
                  test="TST-prep_log-media_journey_keyed_by_fingerprint")
def test_media_journey_keyed_by_fingerprint(tmp_path, monkeypatch):
    _install(monkeypatch)
    ws = _ws(tmp_path)
    (ws / "0-sources" / "IMG.JPG").write_bytes(b"AAAA")     # uppercase ext -> lowercased as it is filed
    _run(ws)
    photos = _log(ws)["photos"]
    assert len(photos) == 1
    fp, entry = next(iter(photos.items()))
    assert entry["content_fingerprint"] == fp              # keyed by content fingerprint
    actions = [(s["action"], s.get("to") or s.get("from")) for s in entry["journey"]]
    assert any(a == "organized" for a, _ in actions)
    renames = [(s["from"], s["to"]) for s in entry["journey"] if s["action"] == "provisional_rename"]
    assert renames == [("IMG.JPG", "2023-01-02--03-04-05.jpg")]
    assert not any(a == "extension_normalized" for a, _ in actions)   # one move, not a rename pair
    assert entry["prep_path"].startswith("5-photos-by-date/")
    assert all(s.get("run") for s in entry["journey"])     # each step attributed to its run


@pytest.mark.spec("RUL-prep_log_records_set_aside", "BLD-quarantine_layout", test="TST-prep_log-quarantined_duplicate_recorded")
def test_quarantined_duplicate_recorded(tmp_path, monkeypatch):
    _install(monkeypatch)
    ws = _ws(tmp_path)
    (ws / "0-sources" / "a.jpg").write_bytes(b"SAME")
    (ws / "0-sources" / "b.jpg").write_bytes(b"SAME")      # identical content -> one quarantined
    _run(ws)
    photos = _log(ws)["photos"]
    assert len(photos) == 1                                # one content, one entry
    entry = next(iter(photos.values()))
    assert entry["deduplicated"]["retained"] == entry["prep_path"]   # final location of the kept file
    dq = entry["deduplicated"]["quarantined"]
    assert len(dq) == 1
    assert dq[0]["origin"].startswith("0-sources/")
    assert ".photos-ingest-quarantine/" in dq[0]["quarantine_path"]
    assert dq[0]["retained_counterpart"]                              # the kept file at dedup time


@pytest.mark.spec("RUL-prep_no_time_or_gps")
def test_prep_organizes_by_raw_naive_timestamp_no_tz_or_utc_shift(tmp_path, monkeypatch):
    """RUL-prep_no_time_or_gps (anti): prep organizes by the RAW camera-naive timestamp and never timezone/UTC-corrects
    it (that is geotag's job). Use a late-evening naive time that ANY tz/UTC conversion would push to
    a different date+hour; assert the file lands under that EXACT raw date and time."""
    _install(monkeypatch)
    def meta(folders, max_workers=4, progress_coordinator=None):
        res = {}
        for fo in folders:
            for fn in os.listdir(fo):
                res[os.path.join(fo, fn)] = {"DateTimeOriginal": "2023:03:26 23:45:00",
                                             "extraction_status": "extracted_ok"}
        return res, set()
    monkeypatch.setattr(utils.MetadataReader, "read_metadata_concurrently", meta)
    ws = _ws(tmp_path)
    (ws / "0-sources" / "x.jpg").write_bytes(b"AAAA")
    _run(ws)
    entry = next(iter(_log(ws)["photos"].values()))
    # raw 2023:03:26 23:45:00 -> exact same date folder + civil time, no shift to 21:45 / 03-27 / etc.
    assert entry["prep_path"] == "5-photos-by-date/2023-03-26/2023-03-26--23-45-00.jpg"


@pytest.mark.spec("RUL-record_whole_each_phase")
def test_prep_log_is_complete_and_standalone_without_geotag_or_merge(tmp_path, monkeypatch):
    """RUL-record_whole_each_phase: the prep log (photos-15) is complete and self-sufficient even if geotag/merge never
    run. After a prep-only run, NO geotag (photos-2x) / merge (photos-3x) artifact exists, yet photos-15
    already records the file's full, non-partial journey ending at its organized destination."""
    _install(monkeypatch)
    ws = _ws(tmp_path)
    (ws / "0-sources" / "a.jpg").write_bytes(b"AAAA")
    _run(ws)
    ctl = ws / ".photos-ingest"
    # prep ran in isolation: no downstream phase artifacts were produced.
    later = [n for n in os.listdir(ctl)
             if n.startswith("photos-2") or n.startswith("photos-3")]
    assert later == [], later
    # ...yet the prep log is on disk and self-sufficient: a complete (non-partial) per-photo journey.
    assert os.path.exists(utils.prep_log_path(str(ws)))
    photos = _log(ws)["photos"]
    assert len(photos) == 1
    entry = next(iter(photos.values()))
    assert not entry.get("partial")                                   # complete, nothing missing
    assert entry["prep_path"].startswith("5-photos-by-date/")        # full journey to its destination
    actions = [s["action"] for s in entry["journey"]]
    assert "organized" in actions and "provisional_rename" in actions
    assert all(s.get("run") for s in entry["journey"])                # every step attributed to its run


@pytest.mark.spec("RUL-no_meaning_from_names")
def test_nonconforming_name_is_ignored_timestamp_comes_from_metadata(tmp_path, monkeypatch):
    """RUL-no_meaning_from_names: prep never parses meaning from a non-conforming filename — it re-ingests the file and
    takes the timestamp from metadata. A file whose name MISLEADINGLY encodes 2099 but whose EXIF
    DateTimeOriginal is 2023:01:02 must be organized under the EXIF date (2023-01-02), with a
    provisional name derived from metadata — the bogus '2099' in the name is never honoured."""
    _install(monkeypatch)                                            # meta -> DateTimeOriginal 2023:01:02 03:04:05
    ws = _ws(tmp_path)
    (ws / "0-sources" / "IMG_20991231_2359.jpg").write_bytes(b"AAAA")   # name lies about the date
    _run(ws)
    entry = next(iter(_log(ws)["photos"].values()))
    # Date + provisional name come from EXIF metadata, not the filename.
    assert entry["prep_path"] == "5-photos-by-date/2023-01-02/2023-01-02--03-04-05.jpg"
    assert "2099" not in entry["prep_path"]                        # the misleading name was not parsed


@pytest.mark.spec("RUL-prep_log_derived", test="TST-prep_log-prep_log_entries_are_derived_from_the_validated_plan")
def test_prep_log_entries_are_derived_from_the_validated_plan(tmp_path, monkeypatch):
    """RUL-prep_log_derived: the prep log is DERIVED from the validated plan + journals and introduces no new
    authority — its facts trace back to plan operations. Assert the logged final destination equals a
    destination the plan actually planned, and the extension-normalization step's 'from' name matches
    the plan's rename source — the log records nothing the plan/journal did not establish."""
    _install(monkeypatch)
    ws = _ws(tmp_path)
    day = ws / "5-photos-by-date" / "2023-01-02"; day.mkdir()
    (day / "2023-01-02--03-04-05.JPG").write_bytes(b"AAAA")         # filed, uppercase ext -> a rename op
    cache = prep.WorkspaceCache(str(ws))
    plan = prep.WorkspacePrepWorkflow(str(ws), cache).plan()
    cache.close()
    prep.PlanExecutor(str(ws)).execute(plan)

    op_dests = {op.destination for op in plan.operations if op.destination}
    op_srcs = {op.source for op in plan.operations if op.source}
    planned_names = {os.path.basename(p) for p in op_dests | op_srcs}
    entry = next(iter(_log(ws)["photos"].values()))
    # The log's terminal location is one the plan actually planned — not a fact the log invented.
    assert entry["prep_path"] in op_dests, (entry["prep_path"], sorted(op_dests))
    # The extension-normalization step's 'from' name is the plan's rename source — derived, not new.
    norm = [s for s in entry["journey"] if s["action"] == "extension_normalized"]
    assert norm and norm[0]["from"] == "2023-01-02--03-04-05.JPG"
    assert "2023-01-02--03-04-05.JPG" in planned_names, sorted(planned_names)
    assert os.path.basename(norm[0]["to"]) in planned_names, (norm, sorted(planned_names))


@pytest.mark.spec("RUL-no_log_entry_for_other", test="TST-prep_log-strays_and_other_not_logged")
def test_strays_and_other_not_logged(tmp_path, monkeypatch):
    _install(monkeypatch)
    ws = _ws(tmp_path)
    (ws / "0-sources" / "a.jpg").write_bytes(b"AAAA")
    (ws / "0-sources" / "notes.txt").write_bytes(b"hello")   # stray
    _run(ws)
    photos = _log(ws)["photos"]
    assert len(photos) == 1                                  # only the photo
    assert not any("notes" in json.dumps(e) for e in photos.values())


@pytest.mark.spec("RUL-log_step_names_run", test="TST-prep_log-every_step_names_the_run_that_made_it")
def test_every_step_names_the_run_that_made_it(tmp_path, monkeypatch):
    """Each step prep adds names its run, the plan that made it — the user's own move, the run that found it; a later
    run's steps name that later run, the earlier ones keeping theirs."""
    _install(monkeypatch)
    ws = _ws(tmp_path)
    (ws / "0-sources" / "a.jpg").write_bytes(b"AAAA")
    plans = []
    real_plan = prep.WorkspacePrepWorkflow.plan
    def _plan(self):
        made = real_plan(self)
        plans.append(made.plan_id)
        return made
    monkeypatch.setattr(prep.WorkspacePrepWorkflow, "plan", _plan)
    _run(ws)
    first = next(iter(_log(ws)["photos"].values()))["journey"]
    assert first and all(s.get("run") == plans[0] for s in first), first
    organized = glob.glob(str(ws / "5-photos-by-date" / "**" / "*.jpg"), recursive=True)[0]
    (ws / "6-photos-by-dest" / "Trip").mkdir(parents=True)
    os.rename(organized, ws / "6-photos-by-dest" / "Trip" / os.path.basename(organized))
    _run(ws)
    journey = next(iter(_log(ws)["photos"].values()))["journey"]
    assert journey[:len(first)] == first and len(journey) > len(first)
    assert plans[1] != plans[0] and all(s.get("run") == plans[1] for s in journey[len(first):]), journey


@pytest.mark.spec("RUL-log_entry_append_only", test="TST-prep_log-noop_rerun_leaves_log_byte_identical")
def test_noop_rerun_leaves_log_byte_identical(tmp_path, monkeypatch):
    _install(monkeypatch)
    ws = _ws(tmp_path)
    (ws / "0-sources" / "a.jpg").write_bytes(b"AAAA")
    _run(ws)
    first = open(utils.prep_log_path(str(ws)), "rb").read()
    _run(ws)                                                 # no-op
    assert open(utils.prep_log_path(str(ws)), "rb").read() == first


@pytest.mark.spec("RUL-rewrite_in_place_atomic", test="TST-prep_log-an_interrupted_log_rewrite_leaves_the_log_whole")
def test_an_interrupted_log_rewrite_leaves_the_log_whole(tmp_path, monkeypatch):
    """Prep's log, rewritten in place by a run and interrupted — while the new log is half written, or with it
    written but not yet in the earlier one's place — is the earlier log, whole; the next run puts the new one down
    whole."""
    import tempfile
    _install(monkeypatch)
    ws = _ws(tmp_path)
    (ws / "0-sources" / "a.jpg").write_bytes(b"AAAA")
    _run(ws)
    plp = utils.prep_log_path(str(ws))
    before = open(plp, "rb").read()
    log_fds, real_mkstemp, real_dump, real_replace = set(), tempfile.mkstemp, json.dump, prep.replace_durably

    def mkstemp(*a, **k):                                    # the new log's temp file, told from the others
        fd, path = real_mkstemp(*a, **k)
        if k.get("prefix") == ".tmp-prep-log-":
            log_fds.add(fd)
        return fd, path

    def dump_half(obj, fp, **kw):
        if fp.fileno() not in log_fds:
            return real_dump(obj, fp, **kw)
        text = json.dumps(obj, **kw)
        fp.write(text[:len(text) // 2]); fp.flush()
        raise KeyboardInterrupt

    def rename_not_reached(tmp, path):
        if path == plp:
            raise KeyboardInterrupt
        return real_replace(tmp, path)
    for name, cut in (("b.jpg", lambda m: (m.setattr(tempfile, "mkstemp", mkstemp), m.setattr(json, "dump", dump_half))),
                      ("c.jpg", lambda m: m.setattr(prep, "replace_durably", rename_not_reached))):
        (ws / "0-sources" / name).write_bytes(name.encode() * 4)   # new work, so a new log is written
        with monkeypatch.context() as m:
            cut(m)
            with pytest.raises(KeyboardInterrupt):
                _run(ws)
        assert open(plp, "rb").read() == before, name
    (ws / "0-sources" / "d.jpg").write_bytes(b"DDDD")
    _run(ws)
    assert open(plp, "rb").read() != before and _log(ws)["photos"]   # the new log, whole


@pytest.mark.spec("RUL-log_entry_grows", "RUL-log_entry_append_only",
                  test="TST-prep_log-recognized_move_appends_moved_to_by_dest")
def test_recognized_move_appends_moved_to_by_dest(tmp_path, monkeypatch):
    _install(monkeypatch)
    ws = _ws(tmp_path)
    (ws / "0-sources" / "a.jpg").write_bytes(b"AAAA")
    _run(ws)
    organized = glob.glob(str(ws / "5-photos-by-date" / "**" / "*.jpg"), recursive=True)[0]
    fp_before = next(iter(_log(ws)["photos"]))
    # user moves the photo into by-dest
    dest_dir = ws / "6-photos-by-dest" / "Trip"
    dest_dir.mkdir(parents=True)
    os.rename(organized, dest_dir / os.path.basename(organized))
    _run(ws)                                                 # prep recognizes the move
    entry = _log(ws)["photos"][fp_before]                    # same fingerprint key
    assert entry["prep_path"].startswith("6-photos-by-dest/Trip/")
    moves = [s for s in entry["journey"] if s["action"] == "moved_to_by_dest"]
    assert len(moves) == 1 and moves[0]["to"].startswith("6-photos-by-dest/Trip/")
    # the unmoved prep steps were carried forward, not re-derived (still exactly one organize)
    assert sum(1 for s in entry["journey"] if s["action"] == "organized") == 1


@pytest.mark.spec("RUL-prep_records_on_success", "RUL-log_stably_ordered",
                  test="TST-prep_log-log_is_deterministic_and_in_control_dir")
def test_log_is_deterministic_and_in_control_dir(tmp_path, monkeypatch):
    _install(monkeypatch)
    ws = _ws(tmp_path)
    (ws / "0-sources" / "a.jpg").write_bytes(b"AAAA")
    (ws / "0-sources" / "b.jpg").write_bytes(b"BBBB")
    _run(ws)
    assert os.path.exists(ws / ".photos-ingest" / "photos-15-prep-log.json")
    raw = open(utils.prep_log_path(str(ws))).read()
    assert json.dumps(json.loads(raw)["photos"], sort_keys=True)   # parses; keys are sorted on write
    assert list(_log(ws)["photos"]) == sorted(_log(ws)["photos"])  # fingerprint-sorted


@pytest.mark.spec("RUL-partial_history_shown", test="TST-prep_log-missing_history_warns_and_marks_partial")
def test_missing_history_warns_and_marks_partial(tmp_path, monkeypatch):
    _install(monkeypatch)
    ws = _ws(tmp_path)
    # An already-organized file with no prior prep-log/journal: history is unreconstructable.
    (ws / "5-photos-by-date" / "2023-01-02").mkdir()
    (ws / "5-photos-by-date" / "2023-01-02" / "2023-01-02--03-04-05-001.jpg").write_bytes(b"AAAA")
    _run(ws)
    entry = next(iter(_log(ws)["photos"].values()))
    assert entry.get("partial") is True
    assert "incomplete" in entry.get("note", "")


@pytest.mark.spec("BLD-log_format", "RUL-log_carries_name_chain",
                  test="TST-prep_log-every_move_names_where_it_came_from")
def test_every_move_names_where_it_came_from(tmp_path, monkeypatch):
    """The journey keeps the chain of names and places: each move and rename records where the photo
    came from as well as where it went, so the first step holds its original path in the dump."""
    _install(monkeypatch)
    ws = _ws(tmp_path)
    (ws / "0-sources" / "card").mkdir()
    (ws / "0-sources" / "card" / "DSC01234.jpg").write_bytes(b"AAAA")
    _run(ws)
    organized = glob.glob(str(ws / "5-photos-by-date" / "**" / "*.jpg"), recursive=True)[0]
    (ws / "6-photos-by-dest" / "Trip").mkdir(parents=True)
    os.rename(organized, ws / "6-photos-by-dest" / "Trip" / os.path.basename(organized))
    _run(ws)
    journey = next(iter(_log(ws)["photos"].values()))["journey"]
    by = {s["action"]: s for s in journey}
    assert by["organized"]["from"] == "0-sources/card/DSC01234.jpg"
    assert by["provisional_rename"]["from"] == "DSC01234.jpg"
    assert by["moved_to_by_dest"]["from"].startswith("5-photos-by-date/")
    assert by["moved_to_by_dest"]["to"].startswith("6-photos-by-dest/Trip/")


@pytest.mark.spec("RUL-log_follows_retaken_fingerprint", "BLD-prep_log_build", "RUL-retaken_fingerprint_step_logged",
                  test="TST-prep_log-a_retaken_fingerprint_keeps_the_photos_history")
def test_a_retaken_fingerprint_keeps_the_photos_history(tmp_path, monkeypatch):
    """A photo fingerprinted again by another method, its value changed, keeps its history: the entry
    moves to the new value, with a step saying so — no orphan under the old value, nothing partial."""
    _install(monkeypatch)
    monkeypatch.setattr(utils, "get_imagemagick_version", lambda: "t")
    ws = _ws(tmp_path)
    (ws / "0-sources" / "a.JPG").write_bytes(b"AAAA")
    _run(ws)
    (old,) = _log(ws)["photos"]
    monkeypatch.setattr(prep.ContentHasher, "fingerprint_image", lambda p: {
        "status": "valid", "strategy": "image-content-hash-v2",
        "value": "sig2-" + open(p, "rb").read().hex()[:16], "engine_version": "u"})
    monkeypatch.setattr(utils, "get_imagemagick_version", lambda: "u")
    _run(ws)
    photos = _log(ws)["photos"]
    (new,) = photos
    entry = photos[new]
    assert new != old and entry["content_fingerprint"] == new and "partial" not in entry
    assert [s["action"] for s in entry["journey"]] == ["organized", "provisional_rename", "fingerprint_retaken"]
    assert entry["journey"][-1]["from"] == old


@pytest.mark.spec("RUL-log_follows_retaken_fingerprint", "BLD-prep_log_build", "RUL-moved_file_stale_read_again",
                  "RUL-retaken_fingerprint_step_logged",
                  test="TST-prep_log-a_photo_moved_under_a_new_imagemagick_keeps_its_history")
def test_a_photo_moved_under_a_new_imagemagick_keeps_its_history(tmp_path, monkeypatch):
    """A photo the user sorts into photos by destination while ImageMagick changes, its fingerprint's value
    changing with it, keeps its whole history: the entry moves to the new value and records the user's
    move — none left behind claiming the photo is still where prep put it."""
    _install(monkeypatch)
    monkeypatch.setattr(utils, "get_imagemagick_version", lambda: "t")
    ws = _ws(tmp_path)
    (ws / "0-sources" / "a.JPG").write_bytes(b"AAAA")
    _run(ws)
    (old,) = _log(ws)["photos"]
    organized = _log(ws)["photos"][old]["prep_path"]
    (ws / "6-photos-by-dest" / "Rome").mkdir()
    moved = "6-photos-by-dest/Rome/" + os.path.basename(organized)
    os.rename(ws / organized, ws / moved)
    monkeypatch.setattr(prep.ContentHasher, "fingerprint_image", lambda p: {
        "status": "valid", "strategy": "image-content-hash-v2",
        "value": "sig2-" + open(p, "rb").read().hex()[:16], "engine_version": "u"})
    monkeypatch.setattr(utils, "get_imagemagick_version", lambda: "u")
    _run(ws)
    photos = _log(ws)["photos"]
    (new,) = photos
    entry = photos[new]
    assert new != old and entry["prep_path"] == moved and "partial" not in entry
    assert [s["action"] for s in entry["journey"]] == [
        "organized", "provisional_rename", "fingerprint_retaken", "moved_to_by_dest"]
    assert entry["journey"][-1]["from"] == organized and entry["journey"][-1]["to"] == moved


@pytest.mark.spec("RUL-log_entry_append_only", test="TST-prep_log-an_earlier_runs_duplicates_are_kept")
def test_an_earlier_runs_duplicates_are_kept(tmp_path, monkeypatch):
    """A later run that sets aside another duplicate of a photo adds it to the photo's record of duplicates; the
    earlier run's stay as they were."""
    _install(monkeypatch)
    ws = _ws(tmp_path)
    (ws / "0-sources" / "a.jpg").write_bytes(b"SAME")
    (ws / "0-sources" / "b.jpg").write_bytes(b"SAME")
    _run(ws)
    first = next(iter(_log(ws)["photos"].values()))["deduplicated"]["quarantined"]
    assert len(first) == 1
    (ws / "0-sources" / "c.jpg").write_bytes(b"SAME")          # another copy, in a later run
    _run(ws)
    photos = _log(ws)["photos"]
    assert len(photos) == 1
    dq = next(iter(photos.values()))["deduplicated"]["quarantined"]
    assert dq[:1] == first and len(dq) == 2, dq
    assert dq[1]["origin"] == "0-sources/c.jpg"


_UNREADABLE_LOGS = ["{not json", "[]", '{"schema_version": 1, "tool": "photos-1-prep"}', '{"photos": null}']


@pytest.mark.parametrize("content", _UNREADABLE_LOGS, ids=["not_json", "a_list", "no_photos", "photos_null"])
@pytest.mark.spec("RUL-unreadable_prep_log_stops", "BLD-unreadable_prep_log", test="TST-prep_log-an_unreadable_log_blocks_the_plan")
def test_an_unreadable_log_blocks_the_plan(tmp_path, monkeypatch, content):
    """An earlier log that cannot be read is never taken for an empty one: the plan blocks, naming it, and execute
    refuses the plan before any change — the new photo stays in the inbox and the log as it was."""
    _install(monkeypatch)
    ws = _ws(tmp_path)
    (ws / "0-sources" / "a.jpg").write_bytes(b"AAAA")
    _run(ws)
    plp = utils.prep_log_path(str(ws))
    with open(plp, "w") as f:
        f.write(content)
    (ws / "0-sources" / "b.jpg").write_bytes(b"BBBB")
    cache = prep.WorkspaceCache(str(ws))
    plan = prep.WorkspacePrepWorkflow(str(ws), cache).plan()
    cache.close()
    assert [b for b in plan.blockers if "photos-15-prep-log.json" in b], plan.blockers
    with pytest.raises(ValueError):
        prep.PlanExecutor(str(ws)).execute(plan)
    assert (ws / "0-sources" / "b.jpg").exists()
    assert open(plp).read() == content


@pytest.mark.spec("RUL-unreadable_prep_log_stops", "BLD-unreadable_prep_log", test="TST-prep_log-a_log_unreadable_since_the_plan_is_refused_before_any_change")
def test_a_log_unreadable_since_the_plan_is_refused_before_any_change(tmp_path, monkeypatch):
    """A log that became unreadable after a clean plan is refused by execute's preflight, before any change."""
    _install(monkeypatch)
    ws = _ws(tmp_path)
    (ws / "0-sources" / "a.jpg").write_bytes(b"AAAA")
    _run(ws)
    (ws / "0-sources" / "b.jpg").write_bytes(b"BBBB")
    cache = prep.WorkspaceCache(str(ws))
    plan = prep.WorkspacePrepWorkflow(str(ws), cache).plan()
    cache.close()
    assert not plan.blockers, plan.blockers
    plp = utils.prep_log_path(str(ws))
    with open(plp, "w") as f:
        f.write("{not json")
    with pytest.raises(ValueError, match="photos-15-prep-log.json"):
        prep.PlanExecutor(str(ws)).execute(plan)
    assert (ws / "0-sources" / "b.jpg").exists()
    assert open(plp).read() == "{not json"
