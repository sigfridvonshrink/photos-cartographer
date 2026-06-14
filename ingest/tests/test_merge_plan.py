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
    # If prep was re-run after calibration, the handoff already carries the FINAL name; the
    # fingerprint join still resolves it (name-independent).
    wf, cp = _wf([_ho("6-photos-by-dest/Trip/2024-07-03--14-12-21.arw", "A")],
                 [_rename("A", "2024-07-03--14-12-21.arw")])
    [e] = wf.enumerate_finalized(cp, "/lib")
    assert e["by_dest_relpath"] == "6-photos-by-dest/Trip/2024-07-03--14-12-21.arw"
    assert e["library_target"] == "/lib/Trip/2024-07-03--14-12-21.arw"


def test_enumerate_unrenamed_file_keeps_its_name():
    wf, cp = _wf([_ho("6-photos-by-dest/Trip/keep.jpg", "A")], [])
    [e] = wf.enumerate_finalized(cp, "/lib")
    assert e["final_name"] == "keep.jpg"
    assert e["library_target"] == "/lib/Trip/keep.jpg"


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
    (ctl / "photos-23-executable-plan.json").write_text(json.dumps(plan23))
    (ctl / "photos-24-execution-summary.json").write_text(json.dumps({"status": "success"}))
    (ctl / "photos-25-complete-log.json").write_text(json.dumps({"photos": {}}))
    (ctl / "photos-25-archive-manifest.json").write_text(json.dumps({"artifact_name": "m"}))
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


def test_plan_is_deterministic(tmp_path, monkeypatch):
    ws, lib, fp = _build_ws(tmp_path, [{"fp": "A", "dest": "Trip", "final_name": "a.jpg"},
                                       {"fp": "B", "dest": "Spain", "final_name": "b.jpg"}])
    _patch_fp(monkeypatch, fp)
    assert merge._run_locked_workflow("plan", str(ws)) == 0
    first = _plan_of(ws)["plan_id"]
    assert merge._run_locked_workflow("plan", str(ws)) == 0
    assert _plan_of(ws)["plan_id"] == first


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
    p24 = os.path.join(str(ws), ".photos-ingest", "photos-24-execution-summary.json")
    open(p24, "w").write(json.dumps({"status": "success", "touched": True}))
    assert merge._run_locked_workflow("dry-run", str(ws)) == 2
