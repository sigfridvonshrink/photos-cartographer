"""Phase 5b — handoff enrichment: real conflict evidence, grouping facts, execution id.

Mocked hashing/metadata (content-based hash so identical files dedup; identity fields so
the handoff can surface contributing_identity_fields). photos_1_prep / photos_utils come
from conftest.py.
"""
import json
import os

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

    def meta(folders, max_workers=4, progress_coordinator=None):
        res = {}
        for folder in folders:
            for f in os.listdir(folder):
                res[os.path.join(folder, f)] = {
                    "DateTimeOriginal": "2023:01:02 03:04:05",
                    "Make": "TestMake", "Model": "TestModel",
                    "camera_group_key": "test-cam",
                    "has_native_gps": False, "has_timestamp": True,
                    "extraction_status": "extracted_ok", "raw_payload": "{}",
                }
        return res, set()
    monkeypatch.setattr(utils.MetadataReader, "read_metadata_concurrently", meta)


def _run(ws):
    prep.CONFIG["jobs"] = 1
    cache = prep.WorkspaceCache(str(ws))
    plan = prep.WorkspacePrepWorkflow(str(ws), cache).plan()
    cache.close()
    prep.PlanExecutor(str(ws)).execute(plan)
    return plan


def _handoff(ws):
    with open(utils.handoff_path(str(ws))) as f:
        return json.load(f)


def test_execution_id_present_and_distinct(tmp_path, monkeypatch):
    _mock(monkeypatch)
    ws = _ws(tmp_path)
    (ws / "0-sources" / "a.jpg").write_bytes(b"AAAA")
    plan = _run(ws)
    h = _handoff(ws)
    # the per-run ids now live in run_metadata, off the deterministic content (§16)
    rm = h["run_metadata"]
    assert rm["execution_id"]
    assert rm["execution_id"] != rm["plan_id"] == plan.plan_id
    assert "plan_id" not in h and "execution_id" not in h        # not at the top level
    assert h["content_fingerprint"]                              # the content fingerprint is present


def test_real_duplicate_evidence_against_mutable(tmp_path, monkeypatch):
    _mock(monkeypatch)
    ws = _ws(tmp_path)
    (ws / "0-sources" / "x.jpg").write_bytes(b"SAME")
    (ws / "0-sources" / "y.jpg").write_bytes(b"SAME")   # exact duplicate -> one quarantined
    _run(ws)
    diag = _handoff(ws)["diagnostics"]
    dups = diag["duplicates_or_conflicts"]
    assert len(dups) == 1
    e = dups[0]
    assert e["original_path"] and e["retained_counterpart"]
    assert e["content_hash"] and e["against"] == "mutable"
    assert diag["blockers"] == []


def test_conflict_attributed_to_by_dest_folder(tmp_path, monkeypatch):
    _mock(monkeypatch)
    ws = _ws(tmp_path)
    (ws / "6-photos-by-dest" / "Trip").mkdir(parents=True)
    (ws / "6-photos-by-dest" / "Trip" / "keep.jpg").write_bytes(b"SAME")  # retained
    (ws / "0-sources" / "dup.jpg").write_bytes(b"SAME")                   # mutable duplicate
    _run(ws)
    h = _handoff(ws)
    dups = h["diagnostics"]["duplicates_or_conflicts"]
    assert any(e["against"] == "by-dest" for e in dups)
    trip = [df for df in h["destination_folders"] if df["path"] == "6-photos-by-dest/Trip"][0]
    assert len(trip["conflicts_or_duplicates"]) == 1
    assert trip["conflicts_or_duplicates"][0]["original_path"] == "0-sources/dup.jpg"


def test_grouping_facts_identity_and_device_class(tmp_path, monkeypatch):
    _mock(monkeypatch)
    ws = _ws(tmp_path)
    (ws / "0-sources" / "a.jpg").write_bytes(b"AAAA")
    # Classify the group as a phone *before* plan() seeds the config (so the fingerprint matches).
    prep.CONFIG["camera_time_and_timezone_policy"]["device_groups"]["phones"] = ["test-cam"]
    _run(ws)
    groups = _handoff(ws)["camera_groups"]
    g = [cg for cg in groups if cg["group_key"] == "test-cam"][0]
    assert g["contributing_identity_fields"].get("Make") == "TestMake"
    assert g["contributing_identity_fields"].get("Model") == "TestModel"
    assert g["device_class"] == "phone"


def test_unknown_device_class_when_not_configured(tmp_path, monkeypatch):
    _mock(monkeypatch)
    ws = _ws(tmp_path)
    (ws / "0-sources" / "a.jpg").write_bytes(b"AAAA")
    _run(ws)
    g = [cg for cg in _handoff(ws)["camera_groups"] if cg["group_key"] == "test-cam"][0]
    assert g["device_class"] == "unknown"


def test_handoff_written_sorted_and_deterministic(tmp_path, monkeypatch):
    """The handoff must be byte-deterministic for a given workspace state (shared contract §4):
    routed through write_json_artifact (sort_keys), so its SHA-256 — which calibration records as a
    json_dependency over the exact bytes — does not flip spuriously. The on-disk bytes must equal the
    canonical sorted form."""
    _mock(monkeypatch)
    ws = _ws(tmp_path)
    (ws / "0-sources" / "a.jpg").write_bytes(b"AAAA")
    (ws / "0-sources" / "b.jpg").write_bytes(b"BBBB")
    _run(ws)
    raw = open(utils.handoff_path(str(ws))).read()
    obj = json.loads(raw)
    assert raw == json.dumps(obj, indent=2, sort_keys=True)


def test_handoff_content_fingerprint_ignores_run_metadata_and_audit():
    """The content fingerprint is byte-stable across no-op reruns: it excludes run_metadata,
    diagnostics, the execution-journal pointer, and itself; only real content moves it."""
    import photos_utils as utils
    base = {"schema_version": 1, "cache_fingerprint": "cf", "files": [{"relative_path": "a"}],
            "depends_on": {"effective_config": {"fingerprint": "c1"},
                           "execution_journal": {"sha256": "j1"}},
            "diagnostics": {"blockers": []},
            "run_metadata": {"plan_id": "p1", "execution_id": "e1"}}
    fp1 = utils.handoff_content_fingerprint(base)
    volatile_changed = {**base, "run_metadata": {"plan_id": "p2", "execution_id": "e2"},
                        "diagnostics": {"blockers": ["x"]}, "content_fingerprint": "stale",
                        "depends_on": {"effective_config": {"fingerprint": "c1"},
                                       "execution_journal": {"sha256": "j2"}}}
    assert utils.handoff_content_fingerprint(volatile_changed) == fp1     # no-op rerun -> stable
    assert utils.handoff_content_fingerprint({**base, "cache_fingerprint": "CF2"}) != fp1   # real change


def test_handoff_roundtrip_assertion_catches_unstable_fingerprint(tmp_path, monkeypatch):
    """If the just-written handoff would NOT re-read to the same content_fingerprint (a non-round-trip-
    stable field crept in), prep fails loudly rather than shipping a forever-stale handoff (§16)."""
    import pytest
    _mock(monkeypatch)
    ws = _ws(tmp_path)
    (ws / "0-sources" / "a.jpg").write_bytes(b"AAAA")
    calls = []
    def fake_fp(h):                       # compute -> "A" (stored); re-read verify -> "B" (mismatch)
        calls.append(1)
        return "A" if len(calls) == 1 else "B"
    monkeypatch.setattr(utils, "handoff_content_fingerprint", fake_fp)
    with pytest.raises(RuntimeError, match="round-trip stable"):
        _run(ws)
