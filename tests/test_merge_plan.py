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

"""Increment 3 — the merge plan: finalized-name enumeration (handoff⨝photos-23 by content
fingerprint), destination→library identity mapping, collision resolution by fingerprint (the
append-at-max+1 suffix scheme), and the plan/dry-run lifecycle (photos-30-merge-plan.json).

`execute` is still stubbed. The library-file fingerprinting seam (_fingerprint_library_file) is
monkeypatched so these run without ImageMagick. photos_3_merge / photos_utils come from conftest.py.
"""
import json
import os

import pytest

import photos_3_merge as merge
import photos_utils as utils
from test_merge_preflight import PLACED

MANAGED =["0-sources", "1-strays", "2-missing-metadata", "3-redundant-jpgs",
           "4-videos-by-date", "5-photos-by-date", "6-photos-by-dest"]


# --- enumerate_finalized: the fingerprint join (no disk needed) --------------

def _wf(handoff_files, rename_ops):
    wf = merge.MergeWorkflow("/ws")
    wf.handoff = {"filename_timestamp_format": utils.CONFIG["filename_timestamp_format"], "files": handoff_files}
    return wf, {"destinations": {"only": {"operations": rename_ops}}}


def _ho(rel, fp):
    return {"relative_path": rel, "folder_class": "6-photos-by-dest", "media_class": "image",
            "content_hash": json.dumps({"status": "valid", "value": fp})}


def _rename(fp, to):
    return {"type": "rename_no_clobber", "to": to, "preconditions": {"content_fingerprint": fp}}


@pytest.mark.spec("BLD-merge_target", test="TST-merge_plan-enumerate_joins_prerename_handoff_to_final_name")
def test_enumerate_joins_prerename_handoff_to_final_name():
    # Handoff carries the PRE-rename name; the rename op (keyed by fingerprint) gives the final name.
    wf, cp = _wf([_ho("6-photos-by-dest/Trip/IMG_1.arw", "A")],
                 [_rename("A", "2024-07-03--14-12-21.arw")])
    [e] = wf.enumerate_finalized(cp, "/lib")
    assert e["final_name"] == "2024-07-03--14-12-21.arw"
    assert e["lib_dest"] == "Trip"
    assert e["by_dest_relpath"] == "6-photos-by-dest/Trip/2024-07-03--14-12-21.arw"
    assert e["library_target"] == "/lib/Trip/2024-07-03--14-12-21.arw"


@pytest.mark.spec("RUL-library_mirrors_destinations", "BLD-merge_target",
                  test="TST-merge_plan-the_library_mirrors_the_destination_tree")
def test_the_library_mirrors_the_destination_tree():
    """Each photo goes to the same path under the library as under photos by destination — nested folders as
    the user built them, the name geotag gave it, or its own where geotag renamed nothing."""
    wf, cp = _wf([_ho("6-photos-by-dest/Belgium/Brussels/Grand Place/x.jpg", "A"),
                  _ho("6-photos-by-dest/Belgium/y.jpg", "B")],
                 [_rename("A", "2024-07-03--14-12-21.jpg")])
    targets = {e["content_fingerprint"]: e["library_target"] for e in wf.enumerate_finalized(cp, "/lib")}
    assert targets == {"A": "/lib/Belgium/Brussels/Grand Place/2024-07-03--14-12-21.jpg",
                       "B": "/lib/Belgium/y.jpg"}


def test_enumerate_robust_to_postrename_handoff():
    # If prep was re-run after geotag, the handoff already carries the FINAL name; the
    # fingerprint join still resolves it (name-independent).
    wf, cp = _wf([_ho("6-photos-by-dest/Trip/2024-07-03--14-12-21.arw", "A")],
                 [_rename("A", "2024-07-03--14-12-21.arw")])
    [e] = wf.enumerate_finalized(cp, "/lib")
    assert e["by_dest_relpath"] == "6-photos-by-dest/Trip/2024-07-03--14-12-21.arw"
    assert e["library_target"] == "/lib/Trip/2024-07-03--14-12-21.arw"


@pytest.mark.spec("RUL-library_mirrors_destinations", test="TST-merge_plan-enumerate_unrenamed_file_keeps_its_name")
def test_enumerate_unrenamed_file_keeps_its_name():
    wf, cp = _wf([_ho("6-photos-by-dest/Trip/keep.jpg", "A")], [])
    [e] = wf.enumerate_finalized(cp, "/lib")
    assert e["final_name"] == "keep.jpg"
    assert e["library_target"] == "/lib/Trip/keep.jpg"


@pytest.mark.spec("RUL-library_mirrors_destinations", test="TST-merge_plan-enumerate_root_level_destination")
def test_enumerate_root_level_destination():
    wf, cp = _wf([_ho("6-photos-by-dest/top.jpg", "A")], [])
    [e] = wf.enumerate_finalized(cp, "/lib")
    assert e["lib_dest"] == ""
    assert e["library_target"] == "/lib/top.jpg"


# --- end-to-end plan / dry-run via the locked workflow -----------------------

def _build_ws(tmp_path, photos, library_files=()):
    """A fully merge-ready workspace + blessed library. `photos`: dicts {fp, dest, final_name,
    pre_name?, bytes?}. `library_files`: dicts {fp, dest, name, bytes?}. By-dest files are placed on disk under their
    FINAL names; the handoff carries pre-rename names + a rename op when pre_name != final_name.
    Returns (ws, lib, fp_by_path) where fp_by_path maps each library file's abs path to its fp."""
    ws = tmp_path / "ws"
    ws.mkdir()
    lib = tmp_path / "lib"
    lib.mkdir()
    for d in MANAGED:
        (ws / d).mkdir()
    ctl = ws / ".photos-ingest"
    ctl.mkdir()
    (ctl / "photos-00-workspace-guard").touch()
    utils.write_library_marker(str(lib))

    ho_files, ops = [], []
    for i, p in enumerate(photos):
        dest, final = p.get("dest", ""), p["final_name"]
        pre = p.get("pre_name", final)
        ddir = (ws / "6-photos-by-dest" / dest) if dest else (ws / "6-photos-by-dest")
        ddir.mkdir(parents=True, exist_ok=True)
        (ddir / final).write_bytes(p.get("bytes", b"img-%d" % i))
        rel_pre = os.path.join("6-photos-by-dest", dest, pre) if dest else os.path.join("6-photos-by-dest", pre)
        ho_files.append({"relative_path": rel_pre, "folder_class": "6-photos-by-dest",
                         "media_class": "image", "content_hash": json.dumps({"status": "valid", "value": p["fp"]}),
                         "metadata_status": PLACED})
        if pre != final:
            ops.append({"type": "rename_no_clobber", "to": final,
                        "preconditions": {"content_fingerprint": p["fp"]}})

    fp_by_path = {}
    for lf in library_files:
        dest = lf.get("dest", "")
        ldir = (lib / dest) if dest else lib
        ldir.mkdir(parents=True, exist_ok=True)
        fpath = ldir / lf["name"]
        fpath.write_bytes(lf.get("bytes", b"library"))   # a photo's own bytes (b"img-<i>") make it that photo
        fp_by_path[str(fpath)] = lf["fp"]

    handoff = {"filename_timestamp_format": utils.CONFIG["filename_timestamp_format"], "files": ho_files, "content_fingerprint": "whole", "run_metadata": {"started_at": "t"},
               "depends_on": {"cache": {"image_engine": "imagemagick", "image_engine_version": "test",
                                        "fingerprint_algorithm_version": utils.FINGERPRINT_ALGORITHM_VERSION}}}
    (ctl / "photos-15-prep-log.json").write_text(json.dumps({"photos": {}}))
    handoff.setdefault("depends_on", {})["prep_log"] = {"sha256": utils.sha256_file(str(ctl / "photos-15-prep-log.json"))}
    (ctl / "photos-11-handoff.json").write_text(json.dumps(handoff))
    cfg = {k: v for k, v in utils.CONFIG.items() if k != "jobs"}
    cfg["merge"] = dict(cfg.get("merge") or {})
    cfg["merge"]["library_root"] = str(lib)
    (ctl / "photos-00-config.json").write_text(json.dumps(cfg))
    plan23 = {"status": "ready", "destinations": {"d": {"operations": ops}},
              "depends_on": {"handoff": {"dependency_type": "handoff_content",
                                         "artifact_name": "photos-11-handoff.json",
                                         "content_fingerprint": utils.handoff_content_fingerprint(handoff)}}}
    (ctl / "photos-24-executable-plan.json").write_text(json.dumps(plan23))
    (ctl / "photos-25-execution-summary.json").write_text(json.dumps({"status": "success"}))
    (ctl / "photos-26-complete-log.json").write_text(json.dumps({"photos": {}}))
    (ctl / "photos-26-archive-manifest.json").write_text(json.dumps({"artifact_name": "m"}))
    _bd = ws / "6-photos-by-dest"          # finalize's record of each by-dest photo as geotag left it
    (ctl / "photos-26-finalized-media.json").write_text(json.dumps({"media": {
        os.path.relpath(os.path.join(r, n), ws): {"size": os.stat(os.path.join(r, n)).st_size,
                                                  "mtime_ns": os.stat(os.path.join(r, n)).st_mtime_ns}
        for r, _d, fs in os.walk(_bd) for n in fs}}))
    return ws, lib, fp_by_path


def _patch_fp(monkeypatch, fp_by_path):
    def fake(self, abs_path):
        v = fp_by_path.get(abs_path) or fp_by_path.get(os.path.realpath(abs_path))
        if v:
            return {"status": "valid", "value": v, "strategy": "image-content-hash-v2",
                    "engine_version": "test"}
        return {"status": "failed", "value": None, "error": "unreadable", "engine_version": "test"}
    monkeypatch.setattr(merge.MergeWorkflow, "_fingerprint_library_file", fake)
    monkeypatch.setattr(merge, "get_imagemagick_version", lambda: "test")   # the fake's engine, prep's too


def _plan_of(ws):
    return json.loads(open(merge.merge_plan_path(str(ws))).read())


def _files(plan):
    return [f for d in plan["destinations"].values() for f in d["files"]]


def test_plan_placed_new(tmp_path, monkeypatch):
    ws, lib, fp = _build_ws(tmp_path, [{"fp": "A", "dest": "Trip", "final_name": "a.jpg"}])
    _patch_fp(monkeypatch, fp)
    assert merge._run_locked_workflow("plan", str(ws)) == 0
    plan = _plan_of(ws)
    assert plan["totals"] == {"placed_new": 1, "already_present": 0, "renamed_for_library": 0,
                              "blocked": 0}
    [f] = _files(plan)
    assert f["disposition"] == "placed_new"
    assert f["library_target"] == os.path.join(str(lib), "Trip", "a.jpg")
    assert f["renamed_for_library"] is False
    assert f["preconditions"]["content_fingerprint"] == "A"


@pytest.mark.spec("RUL-merge_rechecks_under_new_engine",
                  test="TST-merge_plan-plan_reuses_handoff_fingerprint_never_refingerprints_by_dest")
def test_plan_reuses_handoff_fingerprint_never_refingerprints_by_dest(tmp_path, monkeypatch):
    """RUL-merge_rechecks_under_new_engine (anti): under the ImageMagick prep used, merge reuses prep's recorded
    content_fingerprint for each by-dest file and never re-fingerprints / re-organizes / re-dedups by-dest content.
    The handoff records fp "HANDOFF_ONLY"
    while the on-disk by-dest bytes are unrelated — if merge recomputed the by-dest fingerprint the
    plan's precondition would differ. Assert (a) the plan's per-file content_fingerprint is the
    handoff's recorded value verbatim, and (b) the by-dest file is NEVER passed to the (only)
    fingerprint seam — only library collision targets ever are, and here the library is empty."""
    ws, lib, fp = _build_ws(tmp_path, [{"fp": "HANDOFF_ONLY", "dest": "Trip", "final_name": "a.jpg"}])
    fingerprinted = []
    fake = merge.MergeWorkflow._fingerprint_library_file  # the fake the helper would install...

    def spy(self, abs_path):
        fingerprinted.append(abs_path)
        return fake(self, abs_path)
    _patch_fp(monkeypatch, fp)                              # installs the empty-library fake
    inner = merge.MergeWorkflow._fingerprint_library_file
    monkeypatch.setattr(merge.MergeWorkflow, "_fingerprint_library_file",
                        lambda self, p: fingerprinted.append(p) or inner(self, p))
    assert merge._run_locked_workflow("plan", str(ws)) == 0
    [f] = _files(_plan_of(ws))
    # (a) the plan carries prep's recorded fingerprint verbatim — not a recompute of the by-dest bytes.
    assert f["preconditions"]["content_fingerprint"] == "HANDOFF_ONLY"
    # (b) no by-dest file was ever fingerprinted (only library collision targets are, and lib is empty).
    assert not any("6-photos-by-dest" in p for p in fingerprinted), fingerprinted


@pytest.mark.spec("RUL-collision_same_content", test="TST-merge_plan-plan_already_present")
def test_plan_already_present(tmp_path, monkeypatch):
    # Library already holds identical content at the target -> already_present (remove source, no write).
    ws, lib, fp = _build_ws(tmp_path, [{"fp": "A", "dest": "Trip", "final_name": "a.jpg"}],
                            library_files=[{"fp": "A", "dest": "Trip", "name": "a.jpg", "bytes": b"img-0"}])
    _patch_fp(monkeypatch, fp)
    assert merge._run_locked_workflow("plan", str(ws)) == 0
    plan = _plan_of(ws)
    assert plan["totals"]["already_present"] == 1
    [f] = _files(plan)
    assert f["disposition"] == "already_present"
    assert f["renamed_for_library"] is False


@pytest.mark.spec("RUL-no_op_run_reports_reuse", "RUL-unchanged_replan_writes_nothing",
                  "RUL-library_fingerprint_kept",
                  test="TST-merge_plan-replan_reports_library_fingerprints_reused")
def test_replan_reports_library_fingerprints_reused(tmp_path, monkeypatch, capsys):
    """A re-plan says how many library fingerprints it took from the cache — and the plan it writes is
    the same file, the count kept out of it."""
    ws, lib, fp = _build_ws(tmp_path, [{"fp": "A", "dest": "Trip", "final_name": "a.jpg"}],
                            library_files=[{"fp": "A", "dest": "Trip", "name": "a.jpg", "bytes": b"img-0"}])
    _patch_fp(monkeypatch, fp)
    capsys.readouterr()
    assert merge._run_locked_workflow("plan", str(ws)) == 0
    assert "Library files fingerprinted: 1 read, 0 reused from the cache." in capsys.readouterr().out
    first = open(merge.merge_plan_path(str(ws)), "rb").read()
    assert merge._run_locked_workflow("plan", str(ws)) == 0
    assert "Library files fingerprinted: 0 read, 1 reused from the cache." in capsys.readouterr().out
    assert open(merge.merge_plan_path(str(ws)), "rb").read() == first
    assert not [n for n in os.listdir(ws / ".photos-ingest") if n.startswith("photos-30-merge-plan-")]


@pytest.mark.spec("RUL-merge_suffix_above_highest", test="TST-merge_plan-plan_renamed_incoming_append_at_max_plus_one")
def test_plan_renamed_incoming_append_at_max_plus_one(tmp_path, monkeypatch):
    # Different content at the target; library also has root-002 -> incoming becomes root-003.
    ws, lib, fp = _build_ws(
        tmp_path, [{"fp": "NEW", "dest": "Trip", "final_name": "ts.jpg"}],
        library_files=[{"fp": "OLD", "dest": "Trip", "name": "ts.jpg"},
                       {"fp": "OLD2", "dest": "Trip", "name": "ts-002.jpg"}])
    _patch_fp(monkeypatch, fp)
    assert merge._run_locked_workflow("plan", str(ws)) == 0
    plan = _plan_of(ws)
    assert plan["totals"]["renamed_for_library"] == 1
    [f] = _files(plan)
    assert f["disposition"] == "renamed_incoming"
    assert f["resolved_name"] == "ts-003.jpg"
    assert f["renamed_for_library"] is True
    assert f["library_target"] == os.path.join(str(lib), "Trip", "ts-003.jpg")


@pytest.mark.spec("RUL-merge_suffix_above_highest", test="TST-merge_plan-plan_two_incoming_case_variants_resolve_at_plan_time")
def test_plan_two_incoming_case_variants_resolve_at_plan_time(tmp_path, monkeypatch):
    """Case-insensitive no-clobber (RUL-suffix_case_insensitive): two incoming photos whose final names differ ONLY
    in case target the same (empty) library dir. On a case-insensitive library they would collide; the plan
    resolves it now — one placed_new, the other suffix-renamed — instead of letting the second surface
    as an EEXIST blocker at execute."""
    ws, lib, fp = _build_ws(tmp_path, [
        {"fp": "A", "dest": "Trip", "final_name": "image.jpg"},
        {"fp": "B", "dest": "Trip", "final_name": "IMAGE.JPG"}])
    _patch_fp(monkeypatch, fp)
    assert merge._run_locked_workflow("plan", str(ws)) == 0
    plan = _plan_of(ws)
    assert plan["totals"]["placed_new"] == 1 and plan["totals"]["renamed_for_library"] == 1
    names = sorted(f["resolved_name"].lower() for f in _files(plan))
    assert names == ["image-001.jpg", "image.jpg"]              # one kept, one suffixed (no case clash)
    assert len({n.lower() for n in names}) == 2                 # the two targets are case-distinct


@pytest.mark.parametrize("variant_fp, disposition", [("X", "renamed_incoming"), ("A", "already_present")])
@pytest.mark.spec("RUL-collision_by_content", "BLD-library_file_fingerprinted", "BLD-names_case_folded",
                  test="TST-merge_plan-a_case_variant_in_the_library_is_settled_by_content")
def test_a_case_variant_in_the_library_is_settled_by_content(tmp_path, monkeypatch, variant_fp, disposition):
    """A library file whose name differs from the target's only in case takes the place on a case-insensitive
    library and may be the same photo on any: it is fingerprinted like a file at the target itself — the same
    content already present there, different content renamed around."""
    ws, lib, fp = _build_ws(tmp_path, [{"fp": "A", "dest": "Trip", "final_name": "photo.jpg"}],
                            library_files=[{"fp": variant_fp, "dest": "Trip", "name": "PHOTO.JPG", "bytes": b"img-0"}])
    _patch_fp(monkeypatch, fp)
    assert merge._run_locked_workflow("plan", str(ws)) == 0
    [f] = _files(_plan_of(ws))
    assert f["disposition"] == disposition
    if disposition == "already_present":
        assert f["library_target"] == os.path.join(str(lib), "Trip", "PHOTO.JPG")
        assert merge._run_locked_workflow("execute", str(ws)) == 0
        assert sorted(os.listdir(lib / "Trip")) == ["PHOTO.JPG"]          # no second copy
        assert not (ws / "6-photos-by-dest" / "Trip" / "photo.jpg").exists()
    else:
        assert f["resolved_name"] == "photo-001.jpg"
        assert f["library_collision"]["path"] == os.path.join(str(lib), "Trip", "PHOTO.JPG")


@pytest.mark.spec("BLD-collision_suffix", "RUL-merge_suffix_above_highest",
                  test="TST-merge_plan-plan_rename_accounts_for_incoming_suffix")
def test_plan_rename_accounts_for_incoming_suffix(tmp_path, monkeypatch):
    # Incoming already carries -004; library max is -002 -> max(004,002)+1 = 005.
    ws, lib, fp = _build_ws(
        tmp_path, [{"fp": "NEW", "dest": "Trip", "final_name": "ts-004.jpg"}],
        library_files=[{"fp": "OLD", "dest": "Trip", "name": "ts-004.jpg"},
                       {"fp": "OLD2", "dest": "Trip", "name": "ts-002.jpg"}])
    _patch_fp(monkeypatch, fp)
    assert merge._run_locked_workflow("plan", str(ws)) == 0
    [f] = _files(_plan_of(ws))
    assert f["resolved_name"] == "ts-005.jpg"


@pytest.mark.spec("RUL-unsettled_collision_blocks", "RUL-unsettled_collision_rest_proceeds",
                  test="TST-merge_plan-plan_unfingerprintable_library_file_blocks_item")
def test_plan_unfingerprintable_library_file_blocks_item(tmp_path, monkeypatch):
    # Collision but the library file can't be fingerprinted -> per-item blocker, left in by-dest; the rest go on.
    ws, lib, fp = _build_ws(tmp_path, [{"fp": "A", "dest": "Trip", "final_name": "a.jpg"},
                                       {"fp": "B", "dest": "Trip", "final_name": "b.jpg"}],
                            library_files=[{"fp": None, "dest": "Trip", "name": "a.jpg"}])
    _patch_fp(monkeypatch, fp)            # fp None -> mock returns status failed
    assert merge._run_locked_workflow("plan", str(ws)) == 2   # plan still written
    plan = _plan_of(ws)
    assert plan["totals"]["blocked"] == 1 and plan["totals"]["placed_new"] == 1
    assert plan["blockers"]
    disp = {f["by_dest_source"]: f["disposition"] for f in _files(plan)}
    assert disp == {"6-photos-by-dest/Trip/a.jpg": "blocked", "6-photos-by-dest/Trip/b.jpg": "placed_new"}


@pytest.mark.spec("RUL-library_mirrors_destinations", "RUL-no_op_run_same_result",
                  test="TST-merge_plan-plan_is_deterministic")
def test_plan_is_deterministic(tmp_path, monkeypatch):
    ws, lib, fp = _build_ws(tmp_path, [{"fp": "A", "dest": "Trip", "final_name": "a.jpg"},
                                       {"fp": "B", "dest": "Spain", "final_name": "b.jpg"}])
    _patch_fp(monkeypatch, fp)
    assert merge._run_locked_workflow("plan", str(ws)) == 0
    first = _plan_of(ws)["plan_id"]
    assert merge._run_locked_workflow("plan", str(ws)) == 0
    assert _plan_of(ws)["plan_id"] == first


@pytest.mark.spec("RUL-suffix_deterministic",
                  test="TST-merge_plan-collision_suffixes_do_not_depend_on_the_order_photos_are_met")
def test_collision_suffixes_do_not_depend_on_the_order_photos_are_met(tmp_path, monkeypatch):
    """Which incoming photo gets which differentiating suffix around the library's photo does not depend on the
    order the photos are met in: the same photos, recorded in the opposite order and listed by the filesystem in
    the opposite order, are given the same names."""
    photos = [{"fp": "N1", "dest": "Trip", "final_name": "ts.jpg"},
              {"fp": "N2", "dest": "Trip", "final_name": "TS.JPG"},
              {"fp": "N3", "dest": "Trip", "final_name": "Ts.jpg"}]
    library = [{"fp": "OLD", "dest": "Trip", "name": "ts.jpg"}, {"fp": "OLD2", "dest": "Trip", "name": "TS-001.jpg"}]

    def names(name, photos, library):
        (tmp_path / name).mkdir()
        ws, lib, fp = _build_ws(tmp_path / name, photos, library)
        _patch_fp(monkeypatch, fp)
        assert merge._run_locked_workflow("plan", str(ws)) == 0
        return {f["preconditions"]["content_fingerprint"]: (f["disposition"], f["resolved_name"])
                for f in _files(_plan_of(ws))}

    first = names("one", photos, library)
    assert first == {"N2": ("renamed_incoming", "TS-002.JPG"), "N3": ("renamed_incoming", "Ts-003.jpg"),
                     "N1": ("renamed_incoming", "ts-004.jpg")}
    real_listdir = os.listdir
    monkeypatch.setattr(os, "listdir", lambda *a: sorted(real_listdir(*a), reverse=True))
    assert names("two", photos[::-1], library[::-1]) == first
    monkeypatch.setattr(os, "listdir", lambda *a: sorted(real_listdir(*a)))
    assert names("three", photos[1:] + photos[:1], library) == first


@pytest.mark.spec("RUL-dry_run_summarises_the_real_plan", test="TST-merge_plan-dry_run_summarizes_validated_plan")
def test_dry_run_summarizes_validated_plan(tmp_path, monkeypatch, capsys):
    ws, lib, fp = _build_ws(tmp_path, [{"fp": "A", "dest": "Trip", "final_name": "a.jpg"}])
    _patch_fp(monkeypatch, fp)
    assert merge._run_locked_workflow("plan", str(ws)) == 0
    capsys.readouterr()
    assert merge._run_locked_workflow("dry-run", str(ws)) == 0
    out = capsys.readouterr().out
    pid = _plan_of(ws)["plan_id"]
    assert out.strip().startswith("Dry-run:") and pid in out   # a summary, names the validated plan
    assert "Full plan:" in out                                 # points to the saved artifact for detail
    with pytest.raises(json.JSONDecodeError):                  # NOT a full JSON dump anymore
        json.loads(out)


@pytest.mark.spec("RUL-no_plan_no_run", test="TST-merge_plan-dry_run_without_plan_errors")
def test_dry_run_without_plan_errors(tmp_path, monkeypatch):
    ws, lib, fp = _build_ws(tmp_path, [{"fp": "A", "dest": "Trip", "final_name": "a.jpg"}])
    _patch_fp(monkeypatch, fp)
    assert merge._run_locked_workflow("dry-run", str(ws)) == 2    # no photos-30 yet


@pytest.mark.spec("RUL-dry_run_validates_saved_plan", test="TST-merge_plan-dry_run_rejects_stale_plan")
def test_dry_run_rejects_stale_plan(tmp_path, monkeypatch):
    ws, lib, fp = _build_ws(tmp_path, [{"fp": "A", "dest": "Trip", "final_name": "a.jpg"}])
    _patch_fp(monkeypatch, fp)
    assert merge._run_locked_workflow("plan", str(ws)) == 0
    # Change a recorded dependency (photos-24) after planning, keeping status=success so preflight
    # still passes -> the saved plan's recorded photos-24 sha no longer matches: stale.
    p24 = os.path.join(str(ws), ".photos-ingest", "photos-25-execution-summary.json")
    open(p24, "w").write(json.dumps({"status": "success", "touched": True}))
    assert merge._run_locked_workflow("dry-run", str(ws)) == 2


@pytest.mark.spec("RUL-organization_settings_restale", test="TST-merge_plan-merge_plan_records_folder_and_extension_fingerprints")
def test_merge_plan_records_folder_and_extension_fingerprints(tmp_path, monkeypatch):
    ws, lib, fp = _build_ws(tmp_path, [{"fp": "A", "dest": "Trip", "final_name": "a.jpg"}])
    _patch_fp(monkeypatch, fp)
    assert merge._run_locked_workflow("plan", str(ws)) == 0
    plan = json.load(open(os.path.join(str(ws), ".photos-ingest", "photos-30-merge-plan.json")))
    dep = plan["depends_on"]
    # Recorded, and matching the workspace config's field-scoped fingerprints.
    assert dep["folders_fingerprint"] == utils.folders_fingerprint()
    assert dep["media_extensions_fingerprint"] == utils.media_extensions_fingerprint()
    # And revalidation flags a change in either area.
    wf = merge.MergeWorkflow(str(ws))
    wf.handoff = json.load(open(utils.handoff_path(str(ws))))
    for k in ("folders_fingerprint", "media_extensions_fingerprint"):
        doctored = {**plan, "depends_on": {**dep, k: "WRONG"}}
        assert any(k in s for s in wf.revalidate_plan_deps(str(ws), doctored)), k


@pytest.mark.spec("RUL-any_config_change_replans", test="TST-merge_plan-any_config_edit_restales_the_merge_plan")
def test_any_config_edit_restales_the_merge_plan(tmp_path, monkeypatch):
    ws, lib, fp = _build_ws(tmp_path, [{"fp": "A", "dest": "Trip", "final_name": "a.jpg"}])
    _patch_fp(monkeypatch, fp)
    assert merge._run_locked_workflow("plan", str(ws)) == 0
    plan = json.load(open(os.path.join(str(ws), ".photos-ingest", "photos-30-merge-plan.json")))
    wf = merge.MergeWorkflow(str(ws))
    wf.handoff = json.load(open(utils.handoff_path(str(ws))))
    assert wf.revalidate_plan_deps(str(ws), plan) == []
    # An edit in an area merge does not read: the whole-file fingerprint still restales its plan.
    cfg_path = utils.config_path(str(ws))
    cfg = json.load(open(cfg_path))
    cfg["gpx_direct_match_max_seconds"] = cfg.get("gpx_direct_match_max_seconds", 60.0) + 1
    open(cfg_path, "w").write(json.dumps(cfg))
    assert "config changed" in wf.revalidate_plan_deps(str(ws), plan)


def test_dry_run_says_execute_merges_around_blocked_photos(tmp_path, monkeypatch, capsys):
    """Dry run describes what execute does with a plan holding blocked photos: it merges the rest, leaves
    those in photos by destination and ends partial without sealing — it does not refuse."""
    ws, lib, fp = _build_ws(tmp_path, [{"fp": "A", "dest": "Trip", "final_name": "a.jpg"}])
    _patch_fp(monkeypatch, fp)
    assert merge._run_locked_workflow("plan", str(ws)) == 0
    plan = _plan_of(ws)
    plan["blockers"] = ["6-photos-by-dest/Trip/b.jpg: could not be fingerprinted — left in by-dest."]
    with open(merge.merge_plan_path(str(ws)), "w") as f:
        json.dump(plan, f)
    capsys.readouterr()
    assert merge._run_locked_workflow("dry-run", str(ws)) == 2   # a blocker: ends as a refusal (RUL-blocked_plan_ends_refused)
    out = "".join(capsys.readouterr())
    assert "merges the rest, and ends partial without sealing" in out and "will refuse" not in out


@pytest.mark.parametrize("recorded", ["0" * 64, None])
@pytest.mark.spec("RUL-plan_carried_out_by_its_code", "BLD-code_fingerprint",
                  test="TST-merge_plan-a_plan_made_by_other_code_is_refused")
def test_a_plan_made_by_other_code_is_refused(tmp_path, monkeypatch, recorded):
    """Merge's plan records the code that made it; dry run and execute refuse one made by another build, or
    recording none, before any change."""
    ws, lib, fp = _build_ws(tmp_path, [{"fp": "A", "dest": "Trip", "final_name": "a.jpg"}])
    _patch_fp(monkeypatch, fp)
    assert merge._run_locked_workflow("plan", str(ws)) == 0
    plan = _plan_of(ws)
    assert plan["depends_on"]["code_fingerprint"] == utils.code_fingerprint()
    plan["depends_on"]["code_fingerprint"] = recorded
    with open(merge.merge_plan_path(str(ws)), "w") as f:
        json.dump(plan, f)
    before = sorted(os.listdir(lib))
    for command in ("dry-run", "execute"):
        assert merge._run_locked_workflow(command, str(ws)) == 2, command
    assert sorted(os.listdir(lib)) == before                       # nothing placed
    assert not os.path.exists(merge.merge_summary_path(str(ws)))   # no summary from a stale plan


@pytest.mark.spec("BLD-phase_logs", "RUL-log_entry_append_only",
                  test="TST-merge_plan-a_log_edited_after_finalize_blocks_merge")
def test_a_log_edited_after_finalize_blocks_merge(tmp_path, monkeypatch, capsys):
    """Each log carries the one before it unchanged and only adds: an entry of prep's that photos-26 no
    longer carries whole — either edited after finalize — blocks merge; one carried whole does not."""
    ws, lib, fp = _build_ws(tmp_path, [{"fp": "A", "dest": "Trip", "final_name": "a.jpg"}])
    _patch_fp(monkeypatch, fp)
    ctl = ws / ".photos-ingest"
    step = {"phase": "prep", "action": "moved_to_by_date", "from": "a", "to": "b"}
    (ctl / "photos-15-prep-log.json").write_text(json.dumps(
        {"photos": {"A": {"content_fingerprint": "A", "prep_path": "b", "journey": [step]}}}))
    ho = json.loads((ctl / "photos-11-handoff.json").read_text())       # prep vouches for its new log
    ho["depends_on"]["prep_log"] = {"sha256": utils.sha256_file(str(ctl / "photos-15-prep-log.json"))}
    (ctl / "photos-11-handoff.json").write_text(json.dumps(ho))
    carried = {"A": {"content_fingerprint": "A", "prep_path": "b", "partial": True,
                     "journey": [step, {"phase": "geotag", "action": "final_rename", "from": "b", "to": "c"}]}}
    (ctl / "photos-26-complete-log.json").write_text(json.dumps({"photos": carried}))
    assert merge._run_locked_workflow("plan", str(ws)) == 0
    assert not _plan_of(ws)["blockers"]

    carried["A"]["journey"][0] = dict(step, to="elsewhere")
    (ctl / "photos-26-complete-log.json").write_text(json.dumps({"photos": carried}))
    capsys.readouterr()
    assert merge._run_locked_workflow("plan", str(ws)) != 0
    assert "no longer carries prep's record" in "".join(capsys.readouterr())

    (ctl / "photos-26-complete-log.json").write_text("{not json")
    assert merge._run_locked_workflow("plan", str(ws)) != 0
    assert "photos-26-complete-log.json cannot be read" in "".join(capsys.readouterr())


def test_entries_not_carried():
    """Only additions pass: a field changed or dropped, a step changed or dropped, or an entry gone, fails."""
    e = {"content_fingerprint": "A", "prep_path": "b", "journey": [{"action": "x"}]}
    nc = utils.entries_not_carried
    assert nc({"A": e}, {"A": dict(e, partial=True, journey=e["journey"] + [{"action": "y"}])}) == []
    assert nc({"A": e}, {"A": dict(e, prep_path="c")}) == ["A"]
    assert nc({"A": e}, {"A": {k: v for k, v in e.items() if k != "prep_path"}}) == ["A"]
    assert nc({"A": e}, {"A": dict(e, journey=[])}) == ["A"]
    assert nc({"A": e}, {"A": dict(e, journey=[{"action": "z"}, {"action": "x"}])}) == ["A"]
    assert nc({"A": e}, {}) == ["A"]


@pytest.mark.parametrize("value_changed", [False, True])
@pytest.mark.spec("RUL-merge_rechecks_under_new_engine", "RUL-engine_change_is_checked", "BLD-merge_engine_recheck",
                  "RUL-retaken_fingerprint_same_photo", "RUL-merge_merges_changed_fingerprint", "BLD-changed_fingerprint_mapped",
                  test="TST-merge_plan-another_imagemagick_has_prep_fingerprints_checked")
def test_another_imagemagick_has_prep_fingerprints_checked(tmp_path, monkeypatch, capsys, value_changed):
    """Under an ImageMagick other than prep's, merge takes each photo's fingerprint again and compares that value
    with the library's, taken under the same version: the photo is found already in the library whether its value is
    prep's or a new one — a new value mapped from prep's, the photo the file finalize recorded — never called a
    different photo and placed again beside itself."""
    ws, lib, fp = _build_ws(tmp_path, [{"fp": "A", "dest": "Trip", "final_name": "a.jpg"}],
                            library_files=[{"fp": "A2" if value_changed else "A", "dest": "Trip", "name": "a.jpg",
                                            "bytes": b"img-0"}])
    src = str(ws / "6-photos-by-dest" / "Trip" / "a.jpg")
    fp[src] = "A2" if value_changed else "A"                     # the photo's fingerprint under the new version
    _patch_fp(monkeypatch, fp)
    monkeypatch.setattr(merge, "get_imagemagick_version", lambda: "newer")
    capsys.readouterr()
    assert merge._run_locked_workflow("plan", str(ws)) == 0
    plan = _plan_of(ws)
    [f] = _files(plan)
    assert f["disposition"] == "already_present" and not plan["blockers"]
    assert f["content_fingerprint"] == "A"                         # still keyed by prep's value
    if value_changed:
        assert f["engine_mapping"] == {"was": {"content_fingerprint": "A", "image_engine_version": "test"},
                                       "now": {"content_fingerprint": "A2", "image_engine_version": "newer"}}
    else:
        assert "engine_mapping" not in f
    assert "1 photo(s) fingerprinted again" in capsys.readouterr().out
    assert plan["depends_on"]["image_engine_version"] == "newer"


@pytest.mark.parametrize("now, blocked", [
    ({"a": "X", "b": "X"}, {"a", "b"}),          # two photos' new values coincide
    ({"a": "B", "b": "B"}, {"a", "b"}),          # a's new value is b's, unchanged
    ({"a": "B", "b": "C"}, {"a", "b"}),          # a's new value is b's old one, b's changed too
    ({"a": "A2", "b": "B"}, set()),              # one to one: a mapped, b kept
])
@pytest.mark.spec("RUL-merge_changed_fingerprint_unmerged", "RUL-merge_merges_changed_fingerprint",
                  "BLD-changed_fingerprint_mapped", test="TST-merge_plan-a_new_fingerprint_not_one_to_one_is_left_unmerged")
def test_a_new_fingerprint_not_one_to_one_is_left_unmerged(tmp_path, monkeypatch, now, blocked):
    """A new value merge maps from prep's must be one to one with it: where two photos' values now coincide, or a
    photo's new value is another's value under prep's ImageMagick, prep's duplicate decision would differ under the
    new one, and those photos stay in photos by destination, each with its reason; the others are merged."""
    ws, lib, fp = _build_ws(tmp_path, [{"fp": "A", "dest": "Trip", "final_name": "a.jpg"},
                                       {"fp": "B", "dest": "Trip", "final_name": "b.jpg"}])
    for name, value in now.items():
        fp[str(ws / "6-photos-by-dest" / "Trip" / f"{name}.jpg")] = value
    _patch_fp(monkeypatch, fp)
    monkeypatch.setattr(merge, "get_imagemagick_version", lambda: "newer")
    merge._run_locked_workflow("plan", str(ws))
    plan = _plan_of(ws)
    by_name = {os.path.basename(f["by_dest_source"])[0]: f for f in _files(plan)}
    assert {n for n, f in by_name.items() if f["disposition"] == "blocked"} == blocked
    assert len(plan["blockers"]) == len(blocked)
    assert all("ImageMagick newer" in by_name[n]["blocked_reason"] for n in blocked)
    if not blocked:
        assert by_name["a"]["engine_mapping"]["now"]["content_fingerprint"] == "A2"
        assert by_name["b"]["disposition"] == "placed_new" and "engine_mapping" not in by_name["b"]


@pytest.mark.spec("RUL-merge_changed_fingerprint_unmerged", "RUL-merge_merges_changed_fingerprint", "BLD-changed_fingerprint_mapped",
                  test="TST-merge_plan-a_new_fingerprint_on_a_file_finalize_did_not_record_is_left_unmerged")
def test_a_new_fingerprint_on_a_file_finalize_did_not_record_is_left_unmerged(tmp_path, monkeypatch):
    """A new value is mapped from prep's only for the very file finalize recorded — its path, size and modification
    time; a photo not so proven stays in photos by destination with its reason, the map built for none."""
    ws, lib, fp = _build_ws(tmp_path, [{"fp": "A", "dest": "Trip", "final_name": "a.jpg"}])
    src = ws / "6-photos-by-dest" / "Trip" / "a.jpg"
    fp[str(src)] = "A2"
    _patch_fp(monkeypatch, fp)
    monkeypatch.setattr(merge, "get_imagemagick_version", lambda: "newer")
    st = os.stat(src)
    os.utime(src, ns=(st.st_atime_ns, st.st_mtime_ns + 10**9))     # not the file finalize recorded
    wf = merge.MergeWorkflow(str(ws))
    wf.handoff = json.load(open(utils.handoff_path(str(ws))))
    calib = json.load(open(merge.executable_plan_path(str(ws))))
    plan = wf.build_merge_plan(str(ws), calib, str(lib), None)
    [f] = _files(plan)
    assert f["disposition"] == "blocked" and "engine_mapping" not in f
    assert "not the file finalize recorded" in f["blocked_reason"]


@pytest.mark.spec("BLD-merge_engine_recheck", test="TST-merge_plan-a_plan_made_under_another_imagemagick_is_stale")
def test_a_plan_made_under_another_imagemagick_is_stale(tmp_path, monkeypatch):
    """A merge plan records the ImageMagick it was made under; under another, its fingerprint comparisons
    no longer hold, and it is stale."""
    ws, lib, fp = _build_ws(tmp_path, [{"fp": "A", "dest": "Trip", "final_name": "a.jpg"}])
    _patch_fp(monkeypatch, fp)
    assert merge._run_locked_workflow("plan", str(ws)) == 0
    wf = merge.MergeWorkflow(str(ws))
    wf.handoff = json.load(open(utils.handoff_path(str(ws))))
    assert wf.revalidate_plan_deps(str(ws), _plan_of(ws)) == []
    monkeypatch.setattr(merge, "get_imagemagick_version", lambda: "newer")
    assert "ImageMagick version changed" in wf.revalidate_plan_deps(str(ws), _plan_of(ws))


@pytest.mark.spec("RUL-blocked_plan_ends_refused", "BLD-exit_statuses",
                  test="TST-merge_plan-a_plan_reporting_a_blocker_ends_as_a_refusal")
def test_a_plan_reporting_a_blocker_ends_as_a_refusal(tmp_path, monkeypatch):
    """Merge's plan, and its dry run of that plan, end with a refusal's status, 2, while the plan holds a blocker —
    the plan saved all the same — and with 0 once the blocker is gone."""
    ws, lib, fp = _build_ws(tmp_path, [{"fp": "A", "dest": "Trip", "final_name": "a.jpg"}],
                            library_files=[{"fp": None, "dest": "Trip", "name": "a.jpg"}])
    _patch_fp(monkeypatch, fp)                         # the library's a.jpg cannot be fingerprinted
    assert merge._run_locked_workflow("plan", str(ws)) == 2
    assert _plan_of(ws)["blockers"]                    # saved, its blocker in it
    assert merge._run_locked_workflow("dry-run", str(ws)) == 2
    fp[os.path.join(str(lib), "Trip", "a.jpg")] = "Z"  # now another photo: a.jpg is placed under a suffix
    assert merge._run_locked_workflow("plan", str(ws)) == 0
    assert not _plan_of(ws)["blockers"]
    assert merge._run_locked_workflow("dry-run", str(ws)) == 0


@pytest.mark.spec("BLD-collision_suffix", "RUL-merge_suffix_above_highest",
                  test="TST-merge_plan-the_suffix_is_above_the_highest_of_the_library_and_the_batch")
def test_the_suffix_is_above_the_highest_of_the_library_and_the_batch(tmp_path, monkeypatch):
    """A photo whose name the library holds for another takes the suffix above the highest its name's root shows
    among the library folder's names and those of every photo bound for it — here an incoming `ts-007` — not the
    lowest free one."""
    ws, lib, fp = _build_ws(tmp_path, [{"fp": "NEW", "dest": "Trip", "final_name": "ts.jpg"},
                                       {"fp": "SEVEN", "dest": "Trip", "final_name": "ts-007.jpg"}],
                            library_files=[{"fp": "OLD", "dest": "Trip", "name": "ts.jpg"},
                                           {"fp": "OLD2", "dest": "Trip", "name": "ts-002.jpg"}])
    _patch_fp(monkeypatch, fp)
    assert merge._run_locked_workflow("plan", str(ws)) == 0
    names = {f["content_fingerprint"]: f["resolved_name"] for f in _files(_plan_of(ws))}
    assert names == {"NEW": "ts-008.jpg", "SEVEN": "ts-007.jpg"}


@pytest.mark.spec("BLD-one_library_file_compared", "RUL-collision_by_content",
                  test="TST-merge_plan-one_library_file_is_compared_per_photo")
def test_one_library_file_is_compared_per_photo(tmp_path, monkeypatch):
    """With no file at the photo's own name but two whose names differ from it only in case, merge compares the
    first of them in sorted order alone: the photo, held by the second, is not found there and takes a suffix."""
    ws, lib, fp = _build_ws(tmp_path, [{"fp": "A", "dest": "Trip", "final_name": "a.jpg"}],
                            library_files=[{"fp": "OTHER", "dest": "Trip", "name": "A.jpg"},
                                           {"fp": "A", "dest": "Trip", "name": "a.JPG", "bytes": b"img-0"}])
    _patch_fp(monkeypatch, fp)
    assert merge._run_locked_workflow("plan", str(ws)) == 0
    [f] = _files(_plan_of(ws))
    assert f["disposition"] == "renamed_incoming" and f["resolved_name"] == "a-001.jpg"
    assert f["library_collision"]["path"] == os.path.join(str(lib), "Trip", "A.jpg")
