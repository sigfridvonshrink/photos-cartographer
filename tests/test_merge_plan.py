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

MANAGED = ["0-sources", "1-strays", "2-missing-metadata", "3-redundant-jpgs",
           "4-videos-by-date", "5-photos-by-date", "6-photos-by-dest"]


# --- enumerate_finalized: the fingerprint join (no disk needed) --------------

def _wf(handoff_files, rename_ops):
    wf = merge.MergeWorkflow("/ws")
    wf.handoff = {"files": handoff_files}
    return wf, {"destinations": {"only": {"operations": rename_ops}}}


def _ho(rel, fp):
    return {"relative_path": rel, "folder_class": "6-photos-by-dest", "media_class": "image",
            "content_fingerprint": fp}


def _rename(fp, to):
    return {"type": "rename_no_clobber", "to": to, "preconditions": {"content_fingerprint": fp}}


@pytest.mark.spec("merge-plan-built-from-finalized-record-1")
def test_enumerate_joins_prerename_handoff_to_final_name():
    # Handoff carries the PRE-rename name; the rename op (keyed by fingerprint) gives the final name.
    wf, cp = _wf([_ho("6-photos-by-dest/Trip/IMG_1.arw", "A")],
                 [_rename("A", "2024-07-03--14-12-21.arw")])
    [e] = wf.enumerate_finalized(cp, "/lib")
    assert e["final_name"] == "2024-07-03--14-12-21.arw"
    assert e["lib_dest"] == "Trip"
    assert e["by_dest_relpath"] == "6-photos-by-dest/Trip/2024-07-03--14-12-21.arw"
    assert e["library_target"] == "/lib/Trip/2024-07-03--14-12-21.arw"


def test_enumerate_robust_to_postrename_handoff():
    # If prep was re-run after geotag, the handoff already carries the FINAL name; the
    # fingerprint join still resolves it (name-independent).
    wf, cp = _wf([_ho("6-photos-by-dest/Trip/2024-07-03--14-12-21.arw", "A")],
                 [_rename("A", "2024-07-03--14-12-21.arw")])
    [e] = wf.enumerate_finalized(cp, "/lib")
    assert e["by_dest_relpath"] == "6-photos-by-dest/Trip/2024-07-03--14-12-21.arw"
    assert e["library_target"] == "/lib/Trip/2024-07-03--14-12-21.arw"


@pytest.mark.spec("merge-preserve-geotag-final-name-1")
def test_enumerate_unrenamed_file_keeps_its_name():
    wf, cp = _wf([_ho("6-photos-by-dest/Trip/keep.jpg", "A")], [])
    [e] = wf.enumerate_finalized(cp, "/lib")
    assert e["final_name"] == "keep.jpg"
    assert e["library_target"] == "/lib/Trip/keep.jpg"


@pytest.mark.spec("merge-map-preserve-destination-structure-1")
def test_enumerate_root_level_destination():
    wf, cp = _wf([_ho("6-photos-by-dest/top.jpg", "A")], [])
    [e] = wf.enumerate_finalized(cp, "/lib")
    assert e["lib_dest"] == ""
    assert e["library_target"] == "/lib/top.jpg"


# --- end-to-end plan / dry-run via the locked workflow -----------------------

def _build_ws(tmp_path, photos, library_files=()):
    """A fully merge-ready workspace + blessed library. `photos`: dicts {fp, dest, final_name,
    pre_name?}. `library_files`: dicts {fp, dest, name}. By-dest files are placed on disk under their
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
                         "media_class": "image", "content_fingerprint": p["fp"]})
        if pre != final:
            ops.append({"type": "rename_no_clobber", "to": final,
                        "preconditions": {"content_fingerprint": p["fp"]}})

    fp_by_path = {}
    for lf in library_files:
        dest = lf.get("dest", "")
        ldir = (lib / dest) if dest else lib
        ldir.mkdir(parents=True, exist_ok=True)
        fpath = ldir / lf["name"]
        fpath.write_bytes(b"library")
        fp_by_path[str(fpath)] = lf["fp"]

    handoff = {"files": ho_files, "content_fingerprint": "whole", "run_metadata": {"started_at": "t"}}
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
    return ws, lib, fp_by_path


def _patch_fp(monkeypatch, fp_by_path):
    def fake(self, abs_path):
        v = fp_by_path.get(abs_path) or fp_by_path.get(os.path.realpath(abs_path))
        if v:
            return {"status": "valid", "value": v, "strategy": "image-content-hash-v1",
                    "engine_version": "test"}
        return {"status": "failed", "value": None, "error": "unreadable", "engine_version": "test"}
    monkeypatch.setattr(merge.MergeWorkflow, "_fingerprint_library_file", fake)


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


@pytest.mark.spec("merge-only-no-reorganize-1")
def test_plan_reuses_handoff_fingerprint_never_refingerprints_by_dest(tmp_path, monkeypatch):
    """§2.1 (anti): merge reuses prep's recorded content_fingerprint for each by-dest file and never
    re-fingerprints / re-organizes / re-dedups by-dest content. The handoff records fp "HANDOFF_ONLY"
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


@pytest.mark.spec("merge-same-content-already-present-remove-source-1")
def test_plan_already_present(tmp_path, monkeypatch):
    # Library already holds identical content at the target -> already_present (remove source, no write).
    ws, lib, fp = _build_ws(tmp_path, [{"fp": "A", "dest": "Trip", "final_name": "a.jpg"}],
                            library_files=[{"fp": "A", "dest": "Trip", "name": "a.jpg"}])
    _patch_fp(monkeypatch, fp)
    assert merge._run_locked_workflow("plan", str(ws)) == 0
    plan = _plan_of(ws)
    assert plan["totals"]["already_present"] == 1
    [f] = _files(plan)
    assert f["disposition"] == "already_present"
    assert f["renamed_for_library"] is False


@pytest.mark.spec("merge-suffix-append-at-max-plus-1-1")
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


@pytest.mark.spec("merge-allocation-treats-existing-and-batch-occupied-1")
def test_plan_two_incoming_case_variants_resolve_at_plan_time(tmp_path, monkeypatch):
    """Case-insensitive no-clobber (§7.2): two incoming photos whose final names differ ONLY in case
    target the same (empty) library dir. On a case-insensitive library they would collide; the plan
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


def test_plan_incoming_renamed_around_case_variant_already_in_library(tmp_path, monkeypatch):
    """An incoming name whose case-variant already sits in the library is suffix-renamed at plan time
    (it would clobber on a case-insensitive library), even though no EXACT-case file exists to compare."""
    ws, lib, fp = _build_ws(tmp_path, [{"fp": "A", "dest": "Trip", "final_name": "photo.jpg"}],
                            library_files=[{"fp": "X", "dest": "Trip", "name": "PHOTO.JPG"}])
    _patch_fp(monkeypatch, fp)
    assert merge._run_locked_workflow("plan", str(ws)) == 0
    plan = _plan_of(ws)
    assert plan["totals"] == {"placed_new": 0, "already_present": 0, "renamed_for_library": 1, "blocked": 0}
    [f] = _files(plan)
    assert f["disposition"] == "renamed_incoming" and f["resolved_name"] == "photo-001.jpg"
    assert f["library_collision"]["reason"] == "case-insensitive name clash"


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


@pytest.mark.spec("merge-unfingerprintable-library-file-blocker-1")
def test_plan_unfingerprintable_library_file_blocks_item(tmp_path, monkeypatch):
    # Collision but the library file can't be fingerprinted -> per-item blocker, left in by-dest.
    ws, lib, fp = _build_ws(tmp_path, [{"fp": "A", "dest": "Trip", "final_name": "a.jpg"}],
                            library_files=[{"fp": None, "dest": "Trip", "name": "a.jpg"}])
    _patch_fp(monkeypatch, fp)            # fp None -> mock returns status failed
    assert merge._run_locked_workflow("plan", str(ws)) == 0   # plan still written
    plan = _plan_of(ws)
    assert plan["totals"]["blocked"] == 1
    assert plan["blockers"]
    [f] = _files(plan)
    assert f["disposition"] == "blocked"


@pytest.mark.spec("merge-deterministic-rerun-same-targets-names-1", "merge-mapping-deterministic-1")
def test_plan_is_deterministic(tmp_path, monkeypatch):
    ws, lib, fp = _build_ws(tmp_path, [{"fp": "A", "dest": "Trip", "final_name": "a.jpg"},
                                       {"fp": "B", "dest": "Spain", "final_name": "b.jpg"}])
    _patch_fp(monkeypatch, fp)
    assert merge._run_locked_workflow("plan", str(ws)) == 0
    first = _plan_of(ws)["plan_id"]
    assert merge._run_locked_workflow("plan", str(ws)) == 0
    assert _plan_of(ws)["plan_id"] == first


@pytest.mark.spec("dryrun-summary-not-dump-1", "merge-dryrun-summarizes-real-plan-1")
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


@pytest.mark.spec("merge-dryrun-requires-saved-plan-1")
def test_dry_run_without_plan_errors(tmp_path, monkeypatch):
    ws, lib, fp = _build_ws(tmp_path, [{"fp": "A", "dest": "Trip", "final_name": "a.jpg"}])
    _patch_fp(monkeypatch, fp)
    assert merge._run_locked_workflow("dry-run", str(ws)) == 2    # no photos-30 yet


def test_dry_run_rejects_stale_plan(tmp_path, monkeypatch):
    ws, lib, fp = _build_ws(tmp_path, [{"fp": "A", "dest": "Trip", "final_name": "a.jpg"}])
    _patch_fp(monkeypatch, fp)
    assert merge._run_locked_workflow("plan", str(ws)) == 0
    # Change a recorded dependency (photos-24) after planning, keeping status=success so preflight
    # still passes -> the saved plan's recorded photos-24 sha no longer matches: stale.
    p24 = os.path.join(str(ws), ".photos-ingest", "photos-25-execution-summary.json")
    open(p24, "w").write(json.dumps({"status": "success", "touched": True}))
    assert merge._run_locked_workflow("dry-run", str(ws)) == 2


@pytest.mark.spec("config-folderset-ext-restale-1")
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
