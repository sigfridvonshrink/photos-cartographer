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

"""Phase 1 (geotag) — Stage-1 preflight (photos-2-geotag, RUL-geotag_gates).

The lifecycle guards + by-dest scope/re-prep gates that must pass before geotag runs. No
JSON artifacts are produced. photos_2_geotag / photos_utils come from conftest.py.
"""
import json
from _handoff import match_disk, recorded, vouched
import os
import sys

import pytest

import photos_2_geotag as cal
import photos_utils as utils

MANAGED = ["0-sources", "1-strays", "2-missing-metadata", "3-redundant-jpgs",
           "4-videos-by-date", "5-photos-by-date", "6-photos-by-dest"]


def _ws(tmp_path, *, guard=True, sealed=False, config=True, handoff=True,
        bydest=("6-photos-by-dest/Trip/a.jpg",), handoff_files=None):
    ws = tmp_path / "ws"
    ws.mkdir()
    for d in MANAGED:
        (ws / d).mkdir()
    ctl = ws / ".photos-ingest"
    ctl.mkdir()
    if guard:
        (ctl / "photos-00-workspace-guard").touch()
    if sealed:
        (ctl / "photos-00-sealed.json").write_text('{"sealed": true, "merged_run_id": "r1"}')
    if config:
        cfg = {k: v for k, v in utils.CONFIG.items() if k != "jobs"}
        (ctl / "photos-00-config.json").write_text(json.dumps(cfg))
    for rel in bydest:
        p = ws / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(b"img")
    if handoff:
        files = handoff_files if handoff_files is not None else \
            [{"relative_path": rel, "media_class": "image"} for rel in bydest]
        (ctl / "photos-11-handoff.json").write_text(json.dumps(vouched(ctl.parent, {"filename_timestamp_format": utils.CONFIG["filename_timestamp_format"], "files": match_disk(ws, files), "depends_on": {"cache": {"fingerprint_algorithm_version": utils.FINGERPRINT_ALGORITHM_VERSION}}})))
    if not config and (ctl / "photos-00-config.json").exists():
        (ctl / "photos-00-config.json").unlink()        # gone since prep's run seeded it
    return ws


def _pf(ws):
    return cal.GeotagWorkflow(str(ws)).preflight()


# --- happy path --------------------------------------------------------------

def test_clean_workspace_passes(tmp_path):
    blockers, warnings, info = _pf(_ws(tmp_path))
    assert blockers == [], blockers
    assert info["by_dest_photos"] == 1
    assert info["handoff_sha256"]


# --- lifecycle guards --------------------------------------------------------

@pytest.mark.spec("RUL-only_prep_builds_structure", test="TST-geotag_preflight-uninitialized_blocks")
def test_uninitialized_blocks(tmp_path):
    blockers, _, _ = _pf(_ws(tmp_path, guard=False))
    assert any("Not an initialized workspace" in b for b in blockers), blockers


@pytest.mark.spec("RUL-sealed_refuses", test="TST-geotag_preflight-sealed_blocks_and_warns_on_dump")
def test_sealed_blocks_and_warns_on_dump(tmp_path):
    ws = _ws(tmp_path, sealed=True)
    (ws / "0-sources" / "newdump.jpg").write_bytes(b"x")   # likely new dump
    blockers, warnings, _ = _pf(ws)
    assert any("SEALED" in b for b in blockers), blockers
    assert any("new dump" in w.lower() for w in warnings), warnings


@pytest.mark.spec("RUL-top_level_only_managed", test="TST-geotag_preflight-loose_root_file_blocks")
def test_loose_root_file_blocks(tmp_path):
    ws = _ws(tmp_path)
    (ws / "stray.txt").write_text("loose")
    blockers, _, _ = _pf(ws)
    assert any("Misplaced entry at workspace root" in b for b in blockers), blockers


def test_nonmanaged_root_folder_blocks(tmp_path):
    """A misplaced dump drops folders at the root too, not just files — the base must hold only the
    managed 0-6 folders, so a non-managed root folder is blocked like a loose file."""
    ws = _ws(tmp_path)
    (ws / "randomdump").mkdir()
    blockers, _, _ = _pf(ws)
    assert any("Misplaced entry at workspace root" in b for b in blockers), blockers


@pytest.mark.spec("RUL-top_level_only_managed", test="TST-geotag_preflight-root_hidden_file_allowed")
def test_root_hidden_file_allowed(tmp_path):
    """A hidden file at the top level (a file manager's `.directory`) is a hidden entry, not a
    misplaced dump: it blocks nothing (RUL-top_level_only_managed)."""
    ws = _ws(tmp_path)
    (ws / ".directory").write_text("[Dolphin]")
    blockers, _, _ = _pf(ws)
    assert not any("Misplaced entry" in b for b in blockers), blockers


@pytest.mark.spec("RUL-top_level_only_managed", test="TST-geotag_preflight-every_misplaced_root_entry_named")
def test_every_misplaced_root_entry_named(tmp_path):
    """Any other top-level entry blocks, whatever its kind — a named pipe too — and the block names
    every one, not only the first."""
    ws = _ws(tmp_path)
    (ws / "stray.txt").write_text("loose")
    (ws / "randomdump").mkdir()
    os.mkfifo(str(ws / "pipe"))
    blockers, _, _ = _pf(ws)
    hit = [b for b in blockers if "Misplaced entry at workspace root" in b]
    assert hit and all(n in hit[0] for n in ("pipe", "randomdump", "stray.txt")), blockers


@pytest.mark.spec("RUL-geotag_merge_check_links",
                  test="TST-geotag_preflight-directory_symlink_at_root_blocks")
def test_directory_symlink_at_root_blocks(tmp_path):
    """A symlink at the root is barred outright as a forbidden symlink (RUL-no_links), never followed —
    checked before the structural/misplaced-folder guards."""
    ws = _ws(tmp_path)
    import os
    os.symlink(str(tmp_path), str(ws / "evil"))
    blockers, _, _ = _pf(ws)
    assert any("Forbidden symlink at the workspace root" in b for b in blockers), blockers


@pytest.mark.spec("BLD-geotag_untimed_gate", test="TST-geotag_preflight-untimed_photo_passes_the_preflight")
def test_a_photo_with_no_recorded_time_passes_the_preflight(tmp_path):
    """A photo sorted into a destination by hand with no recorded time passes the preflight: its folder's date
    fallback may time it, and where none does photos-21 asks for one and geotag stops there
    (test_geotag_date_fallback)."""
    rels = ("6-photos-by-dest/Trip/timed.jpg", "6-photos-by-dest/Trip/untimed.jpg")
    md = lambda t: {"has_timestamp": t, "camera_group_key_version": cal.CAMERA_GROUP_KEY_VERSION,
                    "field_set_version": cal.FIELD_SET_VERSION}
    files = [{"relative_path": rels[0], "folder_class": "6-photos-by-dest", "media_class": "image",
              "metadata_status": md(1)},
             {"relative_path": rels[1], "folder_class": "6-photos-by-dest", "media_class": "image",
              "metadata_status": md(0)}]
    blockers, _, _ = _pf(_ws(tmp_path, bydest=rels, handoff_files=files))
    assert not [b for b in blockers if "untimed.jpg" in b and "fingerprint" not in b], blockers


# --- config / handoff --------------------------------------------------------

def test_missing_config_blocks(tmp_path):
    blockers, _, _ = _pf(_ws(tmp_path, config=False))
    assert any("config" in b and "photos-cartographer prep" in b for b in blockers), blockers


def test_missing_handoff_blocks(tmp_path):
    blockers, _, _ = _pf(_ws(tmp_path, handoff=False))
    assert any("handoff" in b and "photos-cartographer prep" in b for b in blockers), blockers


@pytest.mark.spec("RUL-camera_group_derivation_versioned", "RUL-handoff_fields_of_this_build",
                  "BLD-handoff_field_set_checked", test="TST-geotag_preflight-handoff_of_another_derivation_version_blocks")
@pytest.mark.parametrize("field", ["camera_group_key_version", "field_set_version"])
def test_handoff_of_another_derivation_version_blocks(tmp_path, field):
    rel = "6-photos-by-dest/Trip/a.jpg"
    (tmp_path / "now").mkdir(); (tmp_path / "old").mkdir()
    md = {"camera_group_key_version": utils.CAMERA_GROUP_KEY_VERSION, "field_set_version": utils.FIELD_SET_VERSION}
    blockers, _, _ = _pf(_ws(tmp_path / "now", handoff_files=[
        {"relative_path": rel, "media_class": "image", "metadata_status": md}]))
    assert blockers == [], blockers                                  # the running version's handoff passes
    blockers, _, _ = _pf(_ws(tmp_path / "old", handoff_files=[
        {"relative_path": rel, "media_class": "image", "metadata_status": dict(md, **{field: 0})}]))
    assert any("another version of cartographer" in b and rel in b and "prep plan" in b
               for b in blockers), blockers


@pytest.mark.spec("RUL-handoff_fields_of_this_build", "RUL-unchecked_counts_as_changed", "BLD-handoff_field_set_checked",
                  test="TST-geotag_preflight-a_photo_s_record_with_no_metadata_is_of_another_version")
def test_a_photo_s_record_with_no_metadata_is_of_another_version(tmp_path):
    """A photo's record in the handoff holding no metadata at all cannot be checked for the version that read it: it
    counts as another version's, and the plan stops, never taking it for this build's."""
    rel = "6-photos-by-dest/Trip/a.jpg"
    blockers, _, _ = _pf(_ws(tmp_path, handoff_files=[
        {"relative_path": rel, "media_class": "image", "folder_class": "6-photos-by-dest"}]))
    assert any("another version of cartographer" in b and rel in b for b in blockers), blockers


@pytest.mark.spec("RUL-format_fixed_once_named", test="TST-geotag_preflight-filename_format_other_than_prep_s_blocks")
def test_filename_format_other_than_prep_s_blocks(tmp_path):
    ws = _ws(tmp_path)
    ho_p = ws / ".photos-ingest" / "photos-11-handoff.json"
    ho = json.loads(ho_p.read_text())
    ho_p.write_text(json.dumps(dict(ho, filename_timestamp_format="%Y%m%d_%H%M%S")))
    blockers, _, _ = _pf(ws)
    assert blockers == [utils.filename_format_changed("%Y%m%d_%H%M%S", utils.CONFIG["filename_timestamp_format"])]
    ho.pop("filename_timestamp_format")
    ho_p.write_text(json.dumps(ho))
    blockers, _, _ = _pf(ws)
    assert len(blockers) == 1 and "records no filename format" in blockers[0], blockers


# --- by-dest scope gates -----------------------------------------------------

@pytest.mark.spec("RUL-geotag_plans_on_current_record", "BLD-reprep_pending",
                  test="TST-geotag_preflight-a_photo_removed_or_changed_since_prep_stops_geotag")
def test_a_photo_removed_or_changed_since_prep_stops_geotag(tmp_path):
    """A by-dest photo prep recorded that is now gone, or differs in size or modification time from its
    record (a time edited in another program, say), stops planning with the re-prep blocker: geotag never
    plans on prep's reading of a file that no longer holds it."""
    ws = _ws(tmp_path, bydest=("6-photos-by-dest/Trip/a.jpg", "6-photos-by-dest/Trip/b.jpg"))
    assert _pf(ws)[0] == []
    a = ws / "6-photos-by-dest" / "Trip" / "a.jpg"
    st = a.stat()
    os.utime(a, ns=(st.st_atime_ns, st.st_mtime_ns + 1_000_000_000))      # same bytes, touched
    blockers, _, _ = _pf(ws)
    assert len(blockers) == 1 and "is out of date" in blockers[0] and "Trip/a.jpg" in blockers[0], blockers
    os.utime(a, ns=(st.st_atime_ns, st.st_mtime_ns))
    (ws / "6-photos-by-dest" / "Trip" / "b.jpg").unlink()                # removed
    blockers, _, _ = _pf(ws)
    assert len(blockers) == 1 and "is out of date" in blockers[0] and "Trip/b.jpg" in blockers[0], blockers


@pytest.mark.spec("RUL-database_regions_disjoint",
                  test="TST-geotag_preflight-reprep_gate_blocks_and_geotag_never_records_the_move")
def test_reprep_gate_blocks_and_geotag_never_records_the_move(tmp_path):
    """Geotag does NO move recognition: a by-dest photo absent from the handoff (prep not re-run after
    the move) trips the re-prep gate. Geotag refuses and FIXES NOTHING — it never edits the handoff to
    record the moved file, and by-dest is left byte-identical. Re-recording is prep's job, not geotag's."""
    ws = _ws(tmp_path, bydest=("6-photos-by-dest/Trip/a.jpg",), handoff_files=[])  # a.jpg unrecorded
    ho_p = ws / ".photos-ingest" / "photos-11-handoff.json"
    bd = ws / "6-photos-by-dest" / "Trip" / "a.jpg"
    ho_before, bd_before = ho_p.read_bytes(), bd.read_bytes()
    blockers, _, _ = _pf(ws)
    assert any("is out of date" in b for b in blockers), blockers
    assert ho_p.read_bytes() == ho_before                       # handoff NOT auto-edited by geotag
    assert bd.read_bytes() == bd_before                         # by-dest untouched
    assert json.loads(ho_p.read_text())["files"] == []          # the move was never recorded


@pytest.mark.spec("RUL-geotag_gates", test="TST-geotag_preflight-0sources_nonempty_blocks")
def test_0sources_nonempty_blocks(tmp_path):
    ws = _ws(tmp_path)
    (ws / "0-sources" / "leftover.jpg").write_bytes(b"x")
    blockers, _, _ = _pf(ws)
    assert any("0-sources/ is not empty" in b for b in blockers), blockers


@pytest.mark.spec("RUL-geotag_gates", test="TST-geotag_preflight-photo_left_in_by_date_blocks")
def test_photo_left_in_by_date_blocks(tmp_path):
    ws = _ws(tmp_path)
    (ws / "5-photos-by-date" / "2023-01-01--00-00-00.jpg").write_bytes(b"x")
    blockers, _, _ = _pf(ws)
    assert any("5-photos-by-date/ still contains" in b for b in blockers), blockers


@pytest.mark.spec("RUL-development_after_merge", test="TST-geotag_preflight-dev_subfolder_blocks")
def test_dev_subfolder_blocks(tmp_path):
    ws = _ws(tmp_path)
    (ws / "6-photos-by-dest" / "Trip" / "jpg").mkdir()       # empty dev subfolder still blocks
    blockers, _, _ = _pf(ws)
    assert any("Development has already started" in b for b in blockers), blockers


@pytest.mark.spec("RUL-development_subfolder_any_case", "BLD-development_subfolder_case",
                  test="TST-geotag_preflight-dev_subfolder_of_any_case_blocks")
@pytest.mark.parametrize("name", ["JPG", "JpG", "Tif"])
def test_dev_subfolder_of_any_case_blocks(tmp_path, name):
    ws = _ws(tmp_path)
    (ws / "6-photos-by-dest" / "Trip" / name).mkdir()
    for execute in (False, True):
        blockers, _, _ = cal.GeotagWorkflow(str(ws)).preflight(for_execute=execute)
        assert any("Development has already started" in b and f"Trip/{name}" in b for b in blockers), blockers


@pytest.mark.spec("BLD-loop_gates", "RUL-development_after_merge", test="TST-geotag_preflight-dev_subfolder_blocks_at_execute")
def test_dev_subfolder_blocks_at_execute(tmp_path):
    # RUL-development_after_merge is presence-strict AND re-checked at execute/finalize: an empty jpg/tif subfolder
    # created between `run` and `execute` must hard-stop execution (the per-op preconditions cannot catch it,
    # because the breakout moved no planned file).
    ws = _ws(tmp_path)
    (ws / "6-photos-by-dest" / "Trip" / "jpg").mkdir()
    blockers, _, _ = cal.GeotagWorkflow(str(ws)).preflight(for_execute=True)
    assert any("Development has already started" in b for b in blockers), blockers


def _plan_renaming(ws, rel, to, via=None, write=False):
    """A photos-24 whose one operation renames `rel` to `to` (by `via` for a change of case alone) — after writing its
    position, with `write`."""
    op = {"operation_id": "op1", "type": "rename_no_clobber", "relative_path": rel,
          "from": os.path.basename(rel), "to": to}
    if via:
        op["via"] = via
    ops = ([{"operation_id": "op0", "type": "gps_write", "relative_path": rel}] if write else []) + [op]
    (ws / ".photos-ingest" / "photos-24-executable-plan.json").write_text(
        json.dumps({"plan_id": "p1", "destinations": {"Trip": {"operations": ops}}}))


@pytest.mark.spec("RUL-geotag_gates", "BLD-loop_gates", test="TST-geotag_preflight-execute_and_finalize_check_every_gate")
@pytest.mark.parametrize("gate", ["inbox", "by_date", "non_photo", "unrecorded"])
def test_execute_and_finalize_check_every_gate(tmp_path, gate):
    """Execution and finalize stop on every gate, as planning does: a dump waiting in the inbox, a photo left in
    photos by date, a file not a photo among the photos, and a photo prep has not recorded there."""
    ws = _ws(tmp_path)
    _plan_renaming(ws, "6-photos-by-dest/Trip/a.jpg", "2024-01-01--10-00-00.jpg")
    assert cal.GeotagWorkflow(str(ws)).preflight(for_execute=True)[0] == []
    said = {"inbox": "0-sources/ is not empty", "by_date": "5-photos-by-date/ still contains",
            "non_photo": "must contain only photos", "unrecorded": "is out of date"}[gate]
    target = {"inbox": "0-sources/leftover.jpg", "by_date": "5-photos-by-date/2023-01-01--00-00-00.jpg",
              "non_photo": "6-photos-by-dest/Trip/notes.txt", "unrecorded": "6-photos-by-dest/Trip/new.jpg"}[gate]
    (ws / target).write_bytes(b"x")
    for needs_exiftool in (True, False):                 # execute, and finalize
        blockers, _, _ = cal.GeotagWorkflow(str(ws)).preflight(for_execute=True, needs_exiftool=needs_exiftool)
        assert any(said in b for b in blockers), blockers


@pytest.mark.spec("RUL-sort_photos_only", "RUL-geotag_gates",
                  test="TST-geotag_preflight-a_hidden_file_among_the_photos_stops_geotag")
def test_a_hidden_file_among_the_photos_stops_geotag(tmp_path):
    """A hidden file — or folder — in photos by destination is no photo: geotag stops on it at plan, execute and
    finalize, naming it, as merge would, rather than pass it by for merge to find after the photos were written."""
    ws = _ws(tmp_path)
    _plan_renaming(ws, "6-photos-by-dest/Trip/a.jpg", "2024-01-01--10-00-00.jpg")
    (ws / "6-photos-by-dest" / "Trip" / ".IMG_9.jpg").write_bytes(b"x")
    (ws / "6-photos-by-dest" / "Trip" / ".thumbs").mkdir()
    for kw in ({}, {"for_execute": True}, {"for_execute": True, "needs_exiftool": False}):
        blockers, _, _ = cal.GeotagWorkflow(str(ws)).preflight(**kw)
        assert any("hidden" in b and "6-photos-by-dest/Trip/.IMG_9.jpg" in b and "6-photos-by-dest/Trip/.thumbs" in b
                   for b in blockers), blockers


@pytest.mark.spec("RUL-geotag_gates", "BLD-loop_gates",
                  test="TST-geotag_preflight-names_the_plan_gives_are_recorded_at_execute")
def test_names_the_plan_gives_are_recorded_at_execute(tmp_path):
    """A photo the plan renamed, under its new name or a case change's temporary one, is not an unrecorded photo to
    execute's resume or to finalize; the leftover of a planned write beside it is the writer's, not a stray file."""
    ws = _ws(tmp_path)
    bd = ws / "6-photos-by-dest" / "Trip"
    _plan_renaming(ws, "6-photos-by-dest/Trip/a.jpg", "A.jpg", via="a.jpg.tmp-case.jpg", write=True)
    (bd / "a.jpg").rename(bd / "A.jpg")
    assert cal.GeotagWorkflow(str(ws)).preflight(for_execute=True)[0] == []
    (bd / "A.jpg").rename(bd / "a.jpg.tmp-case.jpg")
    assert cal.GeotagWorkflow(str(ws)).preflight(for_execute=True)[0] == []
    (bd / "a.jpg.tmp-case.jpg").rename(bd / "a.jpg")
    (bd / "a.jpg_exiftool_tmp").write_bytes(b"partial")
    assert cal.GeotagWorkflow(str(ws)).preflight(for_execute=True)[0] == []
    # the same leftover beside a photo no operation writes stops the command, named, as at planning
    # (BLD-own_leftover_cleared)
    (bd / "a.jpg_exiftool_tmp").rename(bd / "b.jpg_exiftool_tmp")
    blockers, _, _ = cal.GeotagWorkflow(str(ws)).preflight(for_execute=True)
    assert any("interrupted metadata write" in b and "b.jpg_exiftool_tmp" in b for b in blockers), blockers


@pytest.mark.spec("RUL-write_leftover_stops_geotag_plan", "BLD-own_leftover_cleared", "BLD-loop_gates",
                  test="TST-geotag_preflight-a_leftover_beside_a_photo_only_renamed_stops_execute")
def test_a_leftover_beside_a_photo_the_plan_only_renames_stops_execute(tmp_path):
    """The plan renames the photo and writes nothing to it: a `_exiftool_tmp` beside it, under its name before or
    after the rename, is no leftover of this plan's — it stops execute and finalize, named, and is left where it is,
    never orphaned by the rename."""
    ws = _ws(tmp_path)
    bd = ws / "6-photos-by-dest" / "Trip"
    _plan_renaming(ws, "6-photos-by-dest/Trip/a.jpg", "2024-01-01--10-00-00.jpg")
    for name in ("a.jpg_exiftool_tmp", "2024-01-01--10-00-00.jpg_exiftool_tmp"):
        (bd / name).write_bytes(b"someone else's")
        for needs_exiftool in (True, False):
            blockers, _, _ = cal.GeotagWorkflow(str(ws)).preflight(for_execute=True, needs_exiftool=needs_exiftool)
            assert any("interrupted metadata write" in b and name in b for b in blockers), blockers
        assert (bd / name).read_bytes() == b"someone else's"
        (bd / name).unlink()


@pytest.mark.spec("RUL-sort_photos_only", test="TST-geotag_preflight-video_in_by_dest_blocks")
def test_video_in_by_dest_blocks(tmp_path):
    ws = _ws(tmp_path)
    (ws / "6-photos-by-dest" / "Trip" / "clip.mp4").write_bytes(b"v")
    blockers, _, _ = _pf(ws)
    assert any("must contain only photos" in b and "video" in b for b in blockers), blockers


@pytest.mark.spec("RUL-geotag_gates", test="TST-geotag_preflight-other_file_in_by_dest_blocks")
def test_other_file_in_by_dest_blocks(tmp_path):
    ws = _ws(tmp_path)
    (ws / "6-photos-by-dest" / "Trip" / "notes.txt").write_text("hi")
    blockers, _, _ = _pf(ws)
    assert any("must contain only photos" in b and "non-media" in b for b in blockers), blockers


@pytest.mark.spec("RUL-geotag_gates_ignore_history",
                  test="TST-geotag_preflight-what_ran_before_does_not_bear_on_the_gates")
def test_what_ran_before_does_not_bear_on_the_gates(tmp_path):
    """The gates read the workspace as it stands now. The records of any number of earlier prep and sort
    cycles, and of a geotag run carried through execute and finalize, change neither answer: a workspace that
    satisfies the gates passes with them, and one that does not is stopped with them, exactly as without."""
    clean = _pf(_ws(tmp_path))
    (tmp_path / "again").mkdir()
    ws = _ws(tmp_path / "again")
    ctl = ws / ".photos-ingest"
    ho_p = ctl / "photos-11-handoff.json"
    ho = json.loads(ho_p.read_text())
    ho["run_metadata"] = {"plan_id": "prep-7", "execution_id": "exec-7", "started_at": "t7"}   # a seventh prep run
    ho_p.write_text(json.dumps(ho))
    for n in ("photos-10-prep-plan.json", "photos-10-prep-plan-001.json", "photos-10-prep-plan-006.json",
              "journal-exec-1.json", "journal-exec-7.json",
              "photos-21-time-decisions.json", "photos-21-time-decisions-001.json",
              "photos-22-gps-drift-validation.json", "photos-23-gps-decisions.json",
              "photos-24-executable-plan.json", "photos-24-executable-plan-001.json",
              "photos-26-complete-log.json", "photos-26-archive-manifest.json", "photos-26-finalized-media.json"):
        (ctl / n).write_text(json.dumps({"status": "complete", "plan_id": "earlier"}))
    (ctl / "photos-25-execution-summary.json").write_text(json.dumps({"status": "success", "plan_id": "earlier"}))
    blockers, warnings, info = _pf(ws)
    assert blockers == [] and warnings == clean[1]
    assert info["by_dest_photos"] == clean[2]["by_dest_photos"] == 1
    (ws / "0-sources" / "leftover.jpg").write_bytes(b"x")            # a gate not satisfied now still stops it
    blockers, _, _ = _pf(ws)
    assert len(blockers) == 1 and "0-sources/ is not empty" in blockers[0], blockers


def test_every_offending_file_is_named_up_to_five(tmp_path):
    """Output wording, not a rule (geotag preflight: _named): a gate names the files it found — every one up to
    five, then how many more — not one example, so the user can clear them in one pass."""
    ws = _ws(tmp_path)
    for i in range(7):
        (ws / "5-photos-by-date" / f"2023-01-01--00-00-0{i}.jpg").write_bytes(b"x")
    (ws / "6-photos-by-dest" / "Trip" / "notes.txt").write_text("hi")
    (ws / "6-photos-by-dest" / "Trip" / "list.csv").write_text("a")
    (ws / "6-photos-by-dest" / "Trip" / "clip.mp4").write_bytes(b"v")
    blockers, _, _ = _pf(ws)
    by_date = next(b for b in blockers if "5-photos-by-date/ still contains" in b)
    assert all(f"--00-00-0{i}.jpg" in by_date for i in range(5)) and "and 2 more" in by_date
    assert "--00-00-05.jpg" not in by_date
    only = next(b for b in blockers if "must contain only photos" in b)
    assert all(n in only for n in ("notes.txt", "list.csv", "clip.mp4")), only


# --- RUL-prep_records_sort re-prep-after-move gate ----------------------------

@pytest.mark.spec("BLD-reprep_pending", "RUL-prep_records_sort", test="TST-geotag_preflight-unrecorded_by_dest_photo_demands_reprep")
def test_unrecorded_by_dest_photo_demands_reprep(tmp_path):
    ws = _ws(tmp_path)                                        # a.jpg recorded
    (ws / "6-photos-by-dest" / "Trip" / "b.jpg").write_bytes(b"img")   # NOT in the handoff
    blockers, _, _ = _pf(ws)
    assert any("is out of date" in b and "photos-cartographer prep" in b for b in blockers), blockers


@pytest.mark.spec("RUL-prep_records_sort", test="TST-geotag_preflight-missing_by_date_photo_demands_reprep")
def test_missing_by_date_photo_demands_reprep(tmp_path):
    # The handoff still records a 5-photos-by-date photo that is now gone (moved into by-dest).
    files = [{"relative_path": "6-photos-by-dest/Trip/a.jpg", "media_class": "image"},
             {"relative_path": "5-photos-by-date/old.jpg", "media_class": "image"}]
    ws = _ws(tmp_path, handoff_files=files)                   # 5-photos-by-date/old.jpg not on disk
    blockers, _, _ = _pf(ws)
    assert any("is out of date" in b for b in blockers), blockers


# --- BLD-geotag_auto_reprep auto re-prep for a clean by-dest move -------------

import types as _types


class _CollectRep:
    def __init__(self): self.logs, self.errors = [], []
    def log(self, msg, **k): self.logs.append(msg)
    def warn(self, msg, **k): pass
    def error(self, msg, **k): self.errors.append(msg)


# What prep's plan holds when it only records a sort: database records, and the removal of the folder it emptied.
_RECORDS_ONLY = [{"type": "db_upsert", "source": None, "destination": None, "reason": "Cache unchanged state"},
                 {"type": "db_remove", "source": None, "destination": None, "reason": "Prune ghosts"},
                 {"type": "rmdir", "source": "5-photos-by-date/2023-01-01", "destination": None,
                  "reason": "Remove a folder the plan leaves empty"}]


def _write_prep_plan(workspace_root, ops):
    with open(utils.prep_plan_path(workspace_root), "w") as f:
        json.dump({"plan_id": "p", "operations": ops}, f)


def _autoreprep(ws, monkeypatch, *, command="plan", jobs=4, fail=None, plan_ops=_RECORDS_ONLY):
    """Drive the auto-reprep helper with prep's locked body stubbed — its plan saving `plan_ops` — and return (prep
    commands it ran, reporter)."""
    import photos_1_prep as prep
    calls = []
    def fake_prep_run_locked(a, workspace_root, reporter):
        calls.append(a.command)
        if fail is not None and a.command == fail:
            raise SystemExit(2)
        if a.command == "plan":
            _write_prep_plan(workspace_root, plan_ops)
    monkeypatch.setattr(prep, "_run_locked", fake_prep_run_locked)
    rep = _CollectRep()
    _autoreprep.last = (calls, rep)                     # read by a test whose run ends in SystemExit
    cal._auto_reprep_for_clean_move(_types.SimpleNamespace(command=command, jobs=jobs), str(ws), rep)
    return calls, rep


@pytest.mark.spec("BLD-geotag_auto_reprep",
                  test="TST-geotag_preflight-auto_reprep_runs_prep_plan_then_execute_for_clean_move")
def test_auto_reprep_runs_prep_plan_then_execute_for_clean_move(tmp_path, monkeypatch):
    """A clean by-dest move (0-sources empty + an unrecorded by-dest photo) makes geotag plan auto-run the
    REAL prep phases — plan then execute, in order — so the operator goes straight to geotag. prep does
    the mutation; geotag only orchestrates."""
    ws = _ws(tmp_path, bydest=("6-photos-by-dest/Trip/a.jpg",), handoff_files=[])   # a.jpg unrecorded
    calls, rep = _autoreprep(ws, monkeypatch)
    assert calls == ["plan", "execute"], calls
    assert any("running prep plan + execute" in m for m in rep.logs), rep.logs


@pytest.mark.parametrize("defect", ["misplaced", "link", "missing"])
@pytest.mark.spec("RUL-shape_checked_first", "BLD-geotag_auto_reprep",
                  test="TST-geotag_preflight-no_auto_reprep_on_a_disturbed_shape")
def test_no_auto_reprep_on_a_disturbed_shape(tmp_path, monkeypatch, defect):
    """A move that would be re-prepped, in a workspace whose shape is disturbed: geotag runs no prep — nothing is
    scanned or planned before the shape is checked."""
    ws = _ws(tmp_path, bydest=("6-photos-by-dest/Trip/a.jpg",), handoff_files=[])   # a.jpg unrecorded: a clean move
    assert _autoreprep(ws, monkeypatch)[0] == ["plan", "execute"]
    if defect == "misplaced":
        (ws / "loose.txt").write_text("dropped at the top level")
    elif defect == "link":
        os.symlink(str(tmp_path), str(ws / "elsewhere"))
    else:
        os.rmdir(ws / "4-videos-by-date")
    assert _autoreprep(ws, monkeypatch)[0] == []


@pytest.mark.spec("BLD-geotag_auto_reprep", "BLD-reprep_pending",
                  test="TST-geotag_preflight-auto_reprep_runs_prep_for_a_photo_changed_since_prep")
def test_auto_reprep_runs_prep_for_a_photo_changed_since_prep(tmp_path, monkeypatch):
    """A recorded by-dest photo changed since prep (0-sources empty) is brought up to date the same way: geotag
    plan runs prep's plan then execute."""
    ws = _ws(tmp_path)
    a = ws / "6-photos-by-dest" / "Trip" / "a.jpg"
    a.write_bytes(b"img, edited")
    calls, rep = _autoreprep(ws, monkeypatch)
    assert calls == ["plan", "execute"], calls
    assert any("is out of date" in m for m in rep.logs), rep.logs


@pytest.mark.parametrize("fail", [None, "execute"])
def test_auto_reprep_prints_only_geotag_s_next_step(tmp_path, monkeypatch, fail):
    """When geotag plan runs prep's plan and execute itself, prep's own closing `Next:` lines are held back —
    they name prep's next command where geotag goes on, or stops, by itself — and only geotag's is printed."""
    import photos_1_prep as prep
    from cartographer.reporting import emit_next_step
    ws = _ws(tmp_path, bydest=("6-photos-by-dest/Trip/a.jpg",), handoff_files=[])   # a clean move to record

    def fake_prep_run_locked(a, workspace_root, reporter):
        emit_next_step(reporter, f"`prep {a.command}` said so")
        if a.command == "plan":
            _write_prep_plan(workspace_root, _RECORDS_ONLY)
        if a.command == fail:
            raise SystemExit(2)
    monkeypatch.setattr(prep, "_run_locked", fake_prep_run_locked)
    rep = _CollectRep()
    if fail:
        with pytest.raises(SystemExit):
            cal._auto_reprep_for_clean_move(_types.SimpleNamespace(command="plan", jobs=4), str(ws), rep)
    else:
        cal._auto_reprep_for_clean_move(_types.SimpleNamespace(command="plan", jobs=4), str(ws), rep)
    nexts = [m for m in rep.logs if m.lstrip("\n").startswith("Next:")]
    assert not any("said so" in m for m in nexts), nexts
    assert nexts == ([] if fail is None else ["\nNext: resolve what prep reported above, then re-run `geotag plan`."])
    emit_next_step(rep, "after")                                        # held back only while prep runs
    assert rep.logs[-1] == "\nNext: after"


def test_auto_reprep_skips_when_nothing_pending(tmp_path, monkeypatch):
    calls, _ = _autoreprep(_ws(tmp_path), monkeypatch)               # a.jpg recorded → nothing pending
    assert calls == []


@pytest.mark.spec("BLD-geotag_auto_reprep", test="TST-geotag_preflight-auto_reprep_skips_when_sources_nonempty")
def test_auto_reprep_skips_when_sources_nonempty(tmp_path, monkeypatch):
    """0-sources holding a dump is the cheapest hard gate — auto-reprep must NOT silently ingest it; it
    bows out and leaves the in-lock scope gate to report the unprocessed dump."""
    ws = _ws(tmp_path, bydest=("6-photos-by-dest/Trip/a.jpg",), handoff_files=[])
    (ws / "0-sources" / "newdump.jpg").write_bytes(b"x")
    calls, _ = _autoreprep(ws, monkeypatch)
    assert calls == []


def test_auto_reprep_skips_when_sealed(tmp_path, monkeypatch):
    ws = _ws(tmp_path, sealed=True, bydest=("6-photos-by-dest/Trip/a.jpg",), handoff_files=[])
    assert _autoreprep(ws, monkeypatch)[0] == []


def test_auto_reprep_skips_when_uninitialized(tmp_path, monkeypatch):
    ws = _ws(tmp_path, guard=False, bydest=("6-photos-by-dest/Trip/a.jpg",), handoff_files=[])
    assert _autoreprep(ws, monkeypatch)[0] == []


def test_auto_reprep_skips_for_non_plan_command(tmp_path, monkeypatch):
    ws = _ws(tmp_path, bydest=("6-photos-by-dest/Trip/a.jpg",), handoff_files=[])
    assert _autoreprep(ws, monkeypatch, command="execute")[0] == []


def test_auto_reprep_propagates_prep_failure(tmp_path, monkeypatch):
    """If the auto prep fails (e.g. an ambiguous move it can't record), geotag stops — never proceeds on a
    half-done state."""
    ws = _ws(tmp_path, bydest=("6-photos-by-dest/Trip/a.jpg",), handoff_files=[])
    with pytest.raises(SystemExit) as ei:
        _autoreprep(ws, monkeypatch, fail="plan")
    assert ei.value.code == 2


@pytest.mark.parametrize("op", [
    {"type": "rename_no_clobber", "source": "5-photos-by-date/2023-01-01/2023-01-01--00-00-00.JPG",
     "destination": "5-photos-by-date/2023-01-01/2023-01-01--00-00-00.jpg.tmp", "reason": "Normalize extension case (temp)"},
    {"type": "quarantine_move", "source": "5-photos-by-date/2023-01-01/2023-01-01--00-00-00-001.jpg",
     "destination": ".photos-ingest-quarantine/p/x.jpg", "reason": "Duplicate of 5-photos-by-date/2023-01-01/x.jpg"},
    {"type": "move_no_clobber", "source": "5-photos-by-date/2023-01-02/2023-01-01--00-00-00.arw",
     "destination": "5-photos-by-date/2023-01-01/2023-01-01--00-00-00.arw", "reason": "Chronological Organization"}],
    ids=["rename", "quarantine", "move"])
@pytest.mark.spec("RUL-auto_reprep_moves_no_media", "BLD-geotag_auto_reprep",
                  test="TST-geotag_preflight-auto_reprep_never_executes_a_plan_that_touches_media")
def test_auto_reprep_never_executes_a_plan_that_touches_media(tmp_path, monkeypatch, op):
    """Prep's plan for a clean sort that would also rename, quarantine or move a media file — work in the by-date
    folders the user was never shown — is not executed: geotag stops, naming what the plan would do and telling the
    user to review and execute it themselves; the saved plan is left as it is."""
    ws = _ws(tmp_path, bydest=("6-photos-by-dest/Trip/a.jpg",), handoff_files=[])   # a.jpg unrecorded: a clean move
    with pytest.raises(SystemExit) as ei:
        _autoreprep(ws, monkeypatch, plan_ops=_RECORDS_ONLY + [op])
    assert ei.value.code == 2
    calls, rep = _autoreprep.last
    assert calls == ["plan"], calls                                   # prep's execute never ran
    said = "\n".join(rep.errors + rep.logs)
    assert op["type"] in said and op["source"] in said, said
    assert "prep dry-run" in said and "prep execute" in said, said
    assert json.loads(open(utils.prep_plan_path(str(ws))).read())["operations"][-1] == op   # left for the user


@pytest.mark.spec("RUL-auto_reprep_moves_no_media", "BLD-geotag_auto_reprep",
                  test="TST-geotag_preflight-auto_reprep_executes_a_plan_touching_no_media")
def test_auto_reprep_executes_a_plan_touching_no_media(tmp_path, monkeypatch):
    """The nearest safe case: a plan that records the sort and otherwise quarantines only a file that is no media (an
    orphaned exiftool intermediate) is executed as before; one prep saved no readable plan for is not."""
    ws = _ws(tmp_path, bydest=("6-photos-by-dest/Trip/a.jpg",), handoff_files=[])
    leftover = {"type": "quarantine_move", "source": "6-photos-by-dest/Trip/a.jpg_exiftool_tmp",
                "destination": ".photos-ingest-quarantine/p/6-photos-by-dest/Trip/a.jpg_exiftool_tmp",
                "reason": "Orphaned exiftool intermediate/backup from an interrupted metadata write"}
    calls, _ = _autoreprep(ws, monkeypatch, plan_ops=_RECORDS_ONLY + [leftover])
    assert calls == ["plan", "execute"], calls
    with pytest.raises(SystemExit) as ei:
        _autoreprep(ws, monkeypatch, plan_ops="not a list")
    assert ei.value.code == 2 and _autoreprep.last[0] == ["plan"]


@pytest.mark.spec("RUL-auto_reprep_moves_no_media", "BLD-geotag_auto_reprep",
                  test="TST-geotag_preflight-auto_reprep_with_real_prep_executes_only_a_recorded_sort")
def test_auto_reprep_with_real_prep_executes_only_a_recorded_sort(tmp_path, monkeypatch):
    """With prep itself planning (its fingerprint and metadata reading stood in for): the user sorts a photo into a
    destination and goes straight to geotag — prep's plan only records it, and geotag executes it. The user sorts
    another and, by mistake, leaves a copy of a third in the by-date folder — prep's plan would quarantine it, and
    geotag executes nothing: the copy stays where it is, and prep's record is as it was."""
    import hashlib
    import photos_1_prep as prep
    from datetime import datetime as _dt, timedelta as _td
    monkeypatch.setattr(prep.ContentHasher, "fingerprint_image", staticmethod(lambda p: {
        "status": "valid", "strategy": "image-content-hash-v2",
        "value": "sig-" + hashlib.sha256(open(p, "rb").read()).hexdigest(), "engine_version": "t"}))
    def meta(folders, max_workers=4, progress_coordinator=None):
        out = {}
        for folder in folders:
            for r, _d, fs in os.walk(folder):
                for n in fs:
                    p = os.path.join(r, n)
                    k = int(open(p, "rb").read().decode().split("-")[1])          # content "photo-<k>"
                    out[p] = {"extraction_status": "extracted_ok",
                              "DateTimeOriginal": (_dt(2023, 1, 2, 3, 4, 5) + _td(minutes=k)).strftime("%Y:%m:%d %H:%M:%S")}
        return out, set()
    monkeypatch.setattr(utils.MetadataReader, "read_metadata_concurrently", meta)
    ws = tmp_path / "ws"
    ws.mkdir()
    for d in MANAGED:
        (ws / d).mkdir()
    for k in range(3):
        (ws / "0-sources" / f"IMG_{k}.jpg").write_bytes(f"photo-{k}".encode())
    rep = _CollectRep()
    for cmd in ("plan", "execute"):                                   # the first ingest, by prep itself
        try:
            prep._run_locked(_types.SimpleNamespace(command=cmd, jobs=1), str(ws), rep)
        except SystemExit as e:
            assert e.code in (0, None), (cmd, rep.errors)
    day = ws / "5-photos-by-date" / "2023-01-02"
    names = sorted(os.listdir(day))
    assert len(names) == 3, names
    (ws / "6-photos-by-dest" / "Trip").mkdir()
    os.rename(day / names[0], ws / "6-photos-by-dest" / "Trip" / names[0])        # a clean sort
    ho_p = ws / ".photos-ingest" / "photos-11-handoff.json"
    rep = _CollectRep()
    cal._auto_reprep_for_clean_move(_types.SimpleNamespace(command="plan", jobs=1), str(ws), rep)
    assert any("Re-prep complete" in m for m in rep.logs), (rep.logs, rep.errors)
    assert not utils.by_dest_reprep_pending(str(ws), json.loads(ho_p.read_text()))   # executed: the sort is recorded

    os.rename(day / names[1], ws / "6-photos-by-dest" / "Trip" / names[1])        # another sort ...
    copy = day / (os.path.splitext(names[2])[0] + "-001.jpg")
    copy.write_bytes((day / names[2]).read_bytes())                             # ... and a copy left by mistake
    # A file put there by hand stops prep's check first (test_workspace_check); taken as the workspace's state here,
    # what the re-prep does with it is what is under test.
    recorded(ws)
    before = ho_p.read_bytes()
    rep = _CollectRep()
    with pytest.raises(SystemExit) as ei:
        cal._auto_reprep_for_clean_move(_types.SimpleNamespace(command="plan", jobs=1), str(ws), rep)
    assert ei.value.code == 2
    assert copy.exists() and (day / names[2]).exists()                          # nothing quarantined
    assert ho_p.read_bytes() == before                                            # prep's execute never ran
    assert any("quarantine_move" in m for m in rep.errors + rep.logs), (rep.errors, rep.logs)
    plan = json.loads(open(utils.prep_plan_path(str(ws))).read())
    assert any(o["type"] == "quarantine_move" for o in plan["operations"])        # saved, for the user to review


# --- RUL-unfingerprinted_photo_stops_geotag ----------------------------------

def _fingerprinted(value):
    md = {"has_timestamp": 1, "camera_group_key_version": cal.CAMERA_GROUP_KEY_VERSION,
          "field_set_version": cal.FIELD_SET_VERSION}
    ch = json.dumps({"status": "valid" if value else "failed", "strategy": "image-content-hash-v2",
                     "value": value, "engine_version": "t"})
    return lambda rel: {"relative_path": rel, "folder_class": "6-photos-by-dest", "media_class": "image",
                        "metadata_status": md, "content_hash": ch}


@pytest.mark.parametrize("for_execute", [False, True], ids=["plan", "execute_finalize"])
@pytest.mark.spec("RUL-unfingerprinted_photo_stops_geotag",
                  test="TST-geotag_preflight-a_photo_with_no_fingerprint_stops_geotag")
def test_a_photo_with_no_fingerprint_stops_geotag(tmp_path, for_execute):
    """A photo in photos by destination prep could not fingerprint — its record's fingerprint holds no value, or it
    has none — stops geotag at plan, execute and finalize alike, the photo named, with what to do; the photos that
    have one pass unnamed."""
    rels = ("6-photos-by-dest/Trip/good.jpg", "6-photos-by-dest/Trip/broken.jpg", "6-photos-by-dest/Trip/bare.jpg")
    files = [_fingerprinted("sig-good")(rels[0]), _fingerprinted(None)(rels[1]),
             {k: v for k, v in _fingerprinted("x")(rels[2]).items() if k != "content_hash"}]
    blockers, _, _ = cal.GeotagWorkflow(str(_ws(tmp_path, bydest=rels, handoff_files=files))).preflight(
        for_execute=for_execute)
    hit = [b for b in blockers if "no content fingerprint" in b]
    assert len(hit) == 1, blockers
    assert "broken.jpg" in hit[0] and "bare.jpg" in hit[0] and "good.jpg" not in hit[0]
    assert "Move them out of 6-photos-by-dest/" in hit[0] and "prep plan" in hit[0]


@pytest.mark.spec("RUL-unfingerprinted_photo_stops_geotag",
                  test="TST-geotag_preflight-fingerprinted_photos_pass")
def test_fingerprinted_photos_pass(tmp_path):
    """The nearest safe case: every photo in photos by destination fingerprinted — geotag proceeds."""
    rels = ("6-photos-by-dest/Trip/a.jpg", "6-photos-by-dest/Trip/b.jpg")
    files = [_fingerprinted("sig-a")(rels[0]), _fingerprinted("sig-b")(rels[1])]
    ws = _ws(tmp_path, bydest=rels, handoff_files=files)
    for for_execute in (False, True):
        blockers, _, _ = cal.GeotagWorkflow(str(ws)).preflight(for_execute=for_execute)
        assert blockers == [], blockers


@pytest.mark.parametrize("command", ["plan", "execute", "finalize"])
@pytest.mark.spec("RUL-unfingerprinted_photo_stops_geotag",
                  test="TST-geotag_preflight-unfingerprinted_photo_stops_every_geotag_command")
def test_unfingerprinted_photo_stops_every_geotag_command(tmp_path, monkeypatch, capsys, command):
    """Through the command itself: plan, execute and finalize each refuse, naming the photo, and write nothing."""
    rels = ("6-photos-by-dest/Trip/broken.jpg",)
    ws = _ws(tmp_path, bydest=rels, handoff_files=[_fingerprinted(None)(rels[0])])
    ctl = ws / ".photos-ingest"
    before = sorted(os.listdir(ctl))
    monkeypatch.chdir(ws)
    with pytest.raises(SystemExit) as ei:
        cal.run(_types.SimpleNamespace(command=command, jobs=1))
    assert ei.value.code == 2
    out = capsys.readouterr()
    assert "no content fingerprint" in out.out + out.err and "broken.jpg" in out.out + out.err
    assert sorted(n for n in os.listdir(ctl) if not n.startswith("photos-00-")) == \
        sorted(n for n in before if not n.startswith("photos-00-"))


@pytest.mark.parametrize("recorded", ["1", None], ids=["another_method", "no_method_recorded"])
@pytest.mark.parametrize("command", ["plan", "execute", "finalize"])
@pytest.mark.spec("RUL-fingerprint_method_is_the_builds",
                  test="TST-geotag_preflight-a_handoff_of_another_fingerprint_method_stops_geotag")
def test_a_handoff_of_another_fingerprint_method_stops_geotag(tmp_path, monkeypatch, capsys, command, recorded):
    """A handoff whose fingerprints were taken by another method than this build's — or that records no method —
    cannot be compared with the fingerprints geotag takes: plan, execute and finalize each refuse, naming the
    mismatch and telling the user to run prep again, and write nothing."""
    rels = ("6-photos-by-dest/Trip/a.jpg",)
    ws = _ws(tmp_path, bydest=rels, handoff_files=[_fingerprinted("sig-a")(rels[0])])
    ctl = ws / ".photos-ingest"
    ho = json.loads((ctl / "photos-11-handoff.json").read_text())
    if recorded is None:
        del ho["depends_on"]["cache"]["fingerprint_algorithm_version"]
    else:
        ho["depends_on"]["cache"]["fingerprint_algorithm_version"] = recorded
    (ctl / "photos-11-handoff.json").write_text(json.dumps(vouched(ctl.parent, ho)))
    before = sorted(os.listdir(ctl))
    monkeypatch.chdir(ws)
    with pytest.raises(SystemExit) as ei:
        cal.run(_types.SimpleNamespace(command=command, jobs=1))
    assert ei.value.code == 2
    out = capsys.readouterr()
    text = out.out + out.err
    assert "taken by another method" in text and repr(recorded) in text, text
    assert "Run prep again" in text and "prep plan" in text and "prep execute" in text, text
    assert sorted(n for n in os.listdir(ctl) if not n.startswith("photos-00-")) == \
        sorted(n for n in before if not n.startswith("photos-00-"))


# --- main() / lock / exit codes ----------------------------------------------

def _main(monkeypatch, ws):
    monkeypatch.chdir(str(ws))
    monkeypatch.setattr(sys, "argv", ["photos-2-geotag", "plan"])
    try:
        cal.main()
        return 0
    except SystemExit as e:
        return e.code if isinstance(e.code, int) else (0 if e.code is None else 1)


def test_main_clean_passes_and_holds_lock(tmp_path, monkeypatch, capsys):
    # The minimal fixture's handoff records carry no folder_class/metadata, so the by-dest model
    # is empty here (the rich model path is exercised in test_geotag_model.py). Preflight
    # passes and main() advances into the Stage 2-4 build, holding the lock throughout.
    code = _main(monkeypatch, _ws(tmp_path))
    out = capsys.readouterr()
    assert code == 0, out.err
    assert "Lock acquired" in out.err
    assert "Model built" in out.out


def test_main_blocker_exits_2(tmp_path, monkeypatch, capsys):
    code = _main(monkeypatch, _ws(tmp_path, guard=False))
    assert code == 2
    assert "Geotag cannot proceed" in capsys.readouterr().err


@pytest.mark.spec("RUL-no_record_before_decisions", "INV-no_stale_use",
                  test="TST-geotag_preflight-preflight_writes_no_json")
def test_preflight_writes_no_json(tmp_path):
    ws = _ws(tmp_path)
    _pf(ws)
    arts = [f for f in os.listdir(ws / ".photos-ingest") if f.startswith("photos-2")]
    assert arts == []                                        # no geotag JSON in preflight


@pytest.mark.spec("RUL-missing_folder_blocks", "RUL-missing_folder_named",
                  test="TST-geotag_preflight-missing_managed_folder_blocks")
def test_missing_managed_folder_blocks(tmp_path):
    """An activated workspace missing a managed 0-6 folder is non-conforming — hard stop."""
    import shutil
    ws = _ws(tmp_path)
    shutil.rmtree(ws / "4-videos-by-date")
    blockers, _, _ = _pf(ws)
    assert any("non-conforming" in b and "4-videos-by-date" in b for b in blockers), blockers


@pytest.mark.spec("RUL-empty_folder_restores", test="TST-geotag_preflight-an_empty_folder_put_back_restores_a_missing_one")
def test_an_empty_folder_put_back_restores_a_missing_one(tmp_path):
    """An empty folder put back in a missing managed folder's place restores it: geotag's preflight passes."""
    ws = _ws(tmp_path)
    (ws / "4-videos-by-date").rmdir()
    assert any("4-videos-by-date" in b for b in _pf(ws)[0])
    (ws / "4-videos-by-date").mkdir()                                # put back, empty
    assert _pf(ws)[0] == []


@pytest.mark.spec("RUL-missing_folder_remedy_told",
                  test="TST-geotag_preflight-missing_managed_folder_block_tells_to_restore_and_run_again")
def test_missing_managed_folder_block_tells_to_restore_and_run_again(tmp_path):
    """The block gives the remedy, not only the fault: restore the folders, then geotag."""
    ws = _ws(tmp_path)
    (ws / "4-videos-by-date").rmdir()
    blockers, _, _ = _pf(ws)
    block = [b for b in blockers if "4-videos-by-date" in b]
    assert len(block) == 1, blockers
    assert "Restore the 0-6 structure" in block[0] and "before geotagging" in block[0], block[0]


def test_dangling_and_managed_named_root_symlinks_blocked(tmp_path):
    """A dangling root symlink (neither file nor dir) and a symlink NAMED like a managed folder (which
    os.path.isdir would resolve through) are both barred by the lstat-based symlink guard (RUL-no_links)."""
    import os
    ws = _ws(tmp_path)
    os.symlink(str(tmp_path / "nonexistent"), str(ws / "dangling"))
    b1, _, _ = _pf(ws)
    assert any("Forbidden symlink at the workspace root" in b and "dangling" in b for b in b1), b1
    os.remove(ws / "dangling")
    os.rmdir(ws / "5-photos-by-date")
    os.symlink(str(tmp_path), str(ws / "5-photos-by-date"))           # a managed folder that is a symlink
    b2, _, _ = _pf(ws)
    assert any("Forbidden symlink at the workspace root" in b for b in b2), b2


def test_dot_named_root_symlink_blocked(tmp_path):
    """A DOT-named root symlink is barred too: the only legitimate dot entries (.photos-ingest*) are
    real directories, so a dot-named symlink at the root is forbidden, not skipped (RUL-no_links)."""
    import os
    ws = _ws(tmp_path)
    os.symlink(str(tmp_path), str(ws / ".evil"))
    blockers, _, _ = _pf(ws)
    assert any("Forbidden symlink at the workspace root" in b for b in blockers), blockers


@pytest.mark.spec("RUL-only_prep_builds_structure", test="TST-geotag_preflight-geotag_never_repairs_a_missing_folder")
def test_geotag_never_repairs_a_missing_folder(tmp_path):
    import shutil
    ws = _ws(tmp_path)
    shutil.rmtree(ws / "4-videos-by-date")
    blockers, _, _ = _pf(ws)
    assert blockers
    assert not (ws / "4-videos-by-date").exists()             # blocked, never recreated


@pytest.mark.spec("RUL-lock_before_reading", test="TST-geotag_preflight-auto_reprep_runs_inside_geotags_lock")
def test_auto_reprep_runs_inside_geotags_lock(tmp_path, monkeypatch):
    """Geotag takes the workspace lock before it reads anything, and runs prep's plan and execute for a
    clean sort inside that same lock — no read before it, no other run slipping in between."""
    import types as _t
    import photos_1_prep as prep
    ws = _ws(tmp_path, bydest=("6-photos-by-dest/Trip/a.jpg",), handoff_files=[])
    held = []
    def fake_prep_run_locked(a, workspace_root, reporter):
        held.append((a.command, utils.WorkspaceLock(workspace_root, create=False).held_owner() is not None))
        if a.command == "plan":
            _write_prep_plan(workspace_root, _RECORDS_ONLY)
    monkeypatch.setattr(prep, "_run_locked", fake_prep_run_locked)
    def stop(self):
        raise SystemExit(9)                                          # geotag's own planning is not under test
    monkeypatch.setattr(cal.GeotagWorkflow, "preflight", stop)
    monkeypatch.chdir(ws)
    with pytest.raises(SystemExit):
        cal.run(_t.SimpleNamespace(command="plan", jobs=1))
    assert held == [("plan", True), ("execute", True)], held


@pytest.mark.parametrize("kind", ["file", "folder"])
@pytest.mark.parametrize("command", ["plan", "execute", "finalize"])
@pytest.mark.spec("RUL-geotag_merge_check_links", "RUL-no_links", "INV-undisturbed_shape",
                  test="TST-geotag_preflight-a_link_among_the_photos_stops_geotag")
def test_a_link_among_the_photos_stops_geotag(tmp_path, monkeypatch, capsys, command, kind):
    """A photo in photos by destination replaced, since prep, by a link to the same file moved outside the workspace
    — same size, same time, so the handoff's record of it still holds — or a folder of photos linked in: every
    geotag command stops, naming the link, having changed nothing inside the workspace or outside it."""
    import types as _t
    ws = _ws(tmp_path, bydest=("6-photos-by-dest/Trip/a.jpg",))
    outside = tmp_path / "outside"; outside.mkdir()
    if kind == "file":
        os.rename(ws / "6-photos-by-dest" / "Trip" / "a.jpg", outside / "a.jpg")
        os.symlink(str(outside / "a.jpg"), str(ws / "6-photos-by-dest" / "Trip" / "a.jpg"))
        link = "6-photos-by-dest/Trip/a.jpg"
    else:
        (outside / "more").mkdir(); (outside / "more" / "b.jpg").write_bytes(b"elsewhere")
        os.symlink(str(outside / "more"), str(ws / "6-photos-by-dest" / "Trip" / "more"))
        link = "6-photos-by-dest/Trip/more"
    (ws / ".photos-ingest" / "photos-00-workspace.lock").touch()

    def state(root):
        return sorted((str(p.relative_to(root)), os.readlink(p) if p.is_symlink() else
                       (p.read_bytes() if p.is_file() else None))
                      for p in root.rglob("*") if not p.name.endswith(".lock"))
    before = state(ws), state(outside)
    utils.CONFIG.clear(); utils.CONFIG.update(utils.default_config())   # a run of its own: nothing read yet
    monkeypatch.chdir(ws)
    with pytest.raises(SystemExit) as ei:
        cal.run(_t.SimpleNamespace(command=command, jobs=1))
    said = "".join(capsys.readouterr())
    assert ei.value.code == 2 and "Forbidden symlink" in said and link in said, said
    assert (state(ws), state(outside)) == before


@pytest.mark.parametrize("defect", ["misplaced", "link", "missing"])
@pytest.mark.parametrize("command", ["plan", "execute", "finalize"])
@pytest.mark.spec("RUL-shape_checked_first", test="TST-geotag_preflight-the_shape_is_checked_before_anything_else")
def test_the_shape_is_checked_before_anything_else(tmp_path, monkeypatch, capsys, command, defect):
    """Geotag checks the workspace's shape before anything else it checks or does: with its shape disturbed and the
    handoff it would read next missing too, every geotag command stops on the shape alone (exit 2), naming it and not
    the handoff, having written nothing. (That the lock and the seal come first is
    TST-cli-the_lock_and_the_seal_come_before_the_shape.)"""
    import types as _t
    ws = _ws(tmp_path, handoff=False)
    if defect == "misplaced":
        (ws / "loose.jpg").write_bytes(b"dropped at the top level")
    elif defect == "link":
        os.symlink(str(tmp_path), str(ws / "elsewhere"))
    else:
        os.rmdir(ws / "4-videos-by-date")
    (ws / ".photos-ingest" / "photos-00-workspace.lock").touch()     # the lock's record is all a run may change

    def state():
        return sorted((str(p.relative_to(ws)), p.read_bytes() if p.is_file() and not p.is_symlink() else None)
                      for p in ws.rglob("*") if not p.name.endswith(".lock"))
    before = state()
    monkeypatch.chdir(ws)
    with pytest.raises(SystemExit) as ei:
        cal.run(_t.SimpleNamespace(command=command, jobs=1))
    out = capsys.readouterr()
    said = out.out + out.err
    named = {"misplaced": "Misplaced entry at workspace root", "link": "Forbidden symlink at the workspace root",
             "missing": "missing managed folder(s): 4-videos-by-date"}[defect]
    assert ei.value.code == 2 and named in said, said
    assert "handoff" not in said.lower(), said                          # nothing checked after the shape
    assert state() == before


@pytest.mark.spec("RUL-only_prep_builds_structure", test="TST-geotag_preflight-geotag_and_merge_create_nothing_outside_a_workspace")
def test_geotag_and_merge_create_nothing_outside_a_workspace(tmp_path, monkeypatch, capsys):
    """Run in a folder that is not a workspace, geotag and merge stop without creating the control
    directory — not even for their lock file. Only prep creates it."""
    import types as _t
    import photos_3_merge as merge
    d = tmp_path / "not-a-workspace"; d.mkdir()
    monkeypatch.chdir(d)
    with pytest.raises(SystemExit) as ei:
        cal.run(_t.SimpleNamespace(command="plan", jobs=1))
    assert ei.value.code == 2 and "Not an initialized workspace" in capsys.readouterr().err
    assert merge._run_locked_workflow("plan", str(d)) == 2
    assert list(d.iterdir()) == []


@pytest.mark.spec("RUL-one_configuration", test="TST-geotag_preflight-geotag_classifies_by_the_workspaces_extension_lists")
def test_geotag_classifies_by_the_workspaces_extension_lists(tmp_path, monkeypatch):
    """Geotag reads the workspace's own configuration, extension lists included: a `.webp` the user
    listed as an image is a photo in photos by destination, not a file of no media class — whatever
    the built-in lists say."""
    ws = _ws(tmp_path, bydest=("6-photos-by-dest/Trip/a.webp",))
    cfg_p = ws / ".photos-ingest" / "photos-00-config.json"
    cfg = json.loads(cfg_p.read_text())
    cfg["media_extensions"]["image"].append("webp")
    cfg_p.write_text(json.dumps(cfg))
    assert utils.media_class_for_ext(".webp") == "other"            # the built-in lists say other
    blockers, _, _ = _pf(ws)
    assert not any("a.webp" in b for b in blockers), blockers
    assert utils.media_class_for_ext(".webp") == "image"


@pytest.mark.spec("RUL-config_complete", "RUL-missing_setting_named",
                  test="TST-geotag_preflight-a_missing_setting_stops_every_phase")
def test_a_missing_setting_stops_every_phase(tmp_path, monkeypatch):
    """A setting missing from the workspace's configuration is never filled from the program's defaults:
    prep's load, geotag and merge each stop, naming the setting and the value to add."""
    import photos_3_merge as merge
    ws = _ws(tmp_path)
    cfg_p = ws / ".photos-ingest" / "photos-00-config.json"
    cfg = json.loads(cfg_p.read_text())
    del cfg["gpx_extrapolation_max_seconds"]
    del cfg["zfs"]["snapshot_prefix"]
    cfg_p.write_text(json.dumps(cfg))
    with pytest.raises(ValueError) as ei:
        utils.load_or_seed_config(str(ws))                          # prep's path
    assert "gpx_extrapolation_max_seconds" in str(ei.value) and "zfs.snapshot_prefix" in str(ei.value)
    assert json.loads(cfg_p.read_text()) == cfg                     # never filled in
    for blockers in (_pf(ws)[0], merge.MergeWorkflow(str(ws)).preflight()[0]):
        assert any("missing setting" in b and "gpx_extrapolation_max_seconds" in b for b in blockers), blockers


@pytest.mark.spec("RUL-config_no_unknown_settings", "RUL-unknown_setting_named",
                  test="TST-geotag_preflight-an_unknown_setting_stops_every_phase")
@pytest.mark.parametrize("edit, named", [
    (lambda c: c["media_extensions"].__setitem__("audio", ["mp3"]), "media_extensions.audio"),   # a class of one's own
    (lambda c: c["folders"].__setitem__("extra", "9-extra"), "folders.extra"),                     # a role of one's own
    (lambda c: c["zfs"].__setitem__("snapshot_required", True), "zfs.snapshot_required"),          # a misspelling
    (lambda c: c.__setitem__("gpx_rot", "/tmp"), "gpx_rot"),                                       # at the top level
    (lambda c: c["camera_time_and_timezone_policy"].__setitem__("phone_gpx_max_distance_meters", 250),
     "camera_time_and_timezone_policy.phone_gpx_max_distance_meters"),                             # one nothing read
])
def test_an_unknown_setting_stops_every_phase(tmp_path, monkeypatch, edit, named):
    """A setting cartographer does not know is never ignored: prep's load, geotag and merge each stop,
    naming it — the user would otherwise believe it took effect."""
    import photos_3_merge as merge
    ws = _ws(tmp_path)
    cfg_p = ws / ".photos-ingest" / "photos-00-config.json"
    cfg = json.loads(cfg_p.read_text())
    edit(cfg)
    cfg_p.write_text(json.dumps(cfg))
    with pytest.raises(ValueError) as ei:
        utils.load_or_seed_config(str(ws))                          # prep's path
    assert named in str(ei.value) and "does not know" in str(ei.value)
    for blockers in (_pf(ws)[0], merge.MergeWorkflow(str(ws)).preflight()[0]):
        assert any("does not know" in b and named in b for b in blockers), blockers


@pytest.mark.spec("RUL-handoff_fields_of_this_build", "BLD-handoff_field_set_checked",
                  test="TST-geotag_preflight-the_field_set_version_follows_the_fields_read")
def test_the_field_set_version_follows_the_fields_read():
    """The handoff's field-set version names what prep reads from a photo: the fields, the order of the groups they are
    looked for in, where the position's Composite value stands in it, and the other times kept. Pinned here with the
    version they are read under — change any of them and this fails until FIELD_SET_VERSION is raised and the pin taken
    again, so a handoff read by other fields is never taken for this build's."""
    import hashlib
    read = json.dumps([list(utils.METADATA_FIELDS), list(utils.METADATA_GROUP_ORDER), list(utils.OTHER_TIME_FIELDS),
                       utils.POSITION_FIELDS], sort_keys=True)
    assert (utils.FIELD_SET_VERSION, hashlib.sha256(read.encode()).hexdigest()) == \
        (5, "2a0096f07fb55160d77e5e1364e845e73a1040227f6a58d93a87c4e19a9b12ad")
