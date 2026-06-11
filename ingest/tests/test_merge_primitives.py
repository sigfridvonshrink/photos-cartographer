"""Increment 1 — shared primitives for the library-merge phase (`photos-3-merge`).

These live in `photos_utils.py` and are built ahead of the merge script itself: the library-side
lock, the library identity marker + `init-library` writer, the workspace seal-marker writer, the
library-file fingerprint cache, deep merge-config validation, the shared suffix convention
(allocate/root/max), and the archive re-seal. photos_utils comes from conftest.py.
"""
import json
import os

import photos_utils as utils


# --- LibraryLock (shared contract §15.2 / merge §12) ---------------------------

def test_library_lock_keyed_to_root_records_owner(tmp_path):
    lib = tmp_path / "library"
    lib.mkdir()
    lock = utils.LibraryLock(str(lib))
    assert lock.acquire() is True
    try:
        assert os.path.isfile(utils.library_lock_path(str(lib)))   # the .photos-merge.lock dotfile
        owner = lock.read_owner()
        assert owner is not None
        assert owner["pid"] == os.getpid()
        assert owner["started_at"] and owner["host"]
    finally:
        lock.release()


def test_library_lock_excludes_then_release_frees(tmp_path):
    lib = tmp_path / "library"
    lib.mkdir()
    l1 = utils.LibraryLock(str(lib))
    assert l1.acquire() is True
    l2 = utils.LibraryLock(str(lib))
    assert l2.acquire() is False          # same library held -> fail-fast, no block
    assert l2.owner and l2.owner["pid"] == os.getpid()
    l1.release()
    l3 = utils.LibraryLock(str(lib))
    assert l3.acquire() is True           # freed by the release above
    l3.release()


def test_workspace_lock_still_works_after_refactor(tmp_path):
    # WorkspaceLock now shares _FlockLock; its behavior must be unchanged.
    lock = utils.WorkspaceLock(str(tmp_path))
    assert lock.acquire() is True
    assert lock.read_owner()["pid"] == os.getpid()
    lock.release()


# --- Library identity marker + init-library writer -----------------------------

def test_library_marker_path_and_identity(tmp_path):
    lib = tmp_path / "library"
    lib.mkdir()
    assert utils.library_marker_path(str(lib)) == os.path.join(str(lib), ".photos-library")
    assert utils.is_library(str(lib)) is False        # no structural inspection — marker only
    utils.write_library_marker(str(lib))
    assert utils.is_library(str(lib)) is True
    assert os.path.isfile(os.path.join(str(lib), ".photos-library"))


def test_write_library_marker_is_idempotent_no_clobber(tmp_path):
    lib = tmp_path / "library"
    lib.mkdir()
    p1 = utils.write_library_marker(str(lib))
    # Put a sentinel byte in to prove a second call does NOT clobber it.
    with open(p1, "w") as f:
        f.write("x")
    p2 = utils.write_library_marker(str(lib))          # no-op success
    assert p1 == p2
    assert open(p1).read() == "x"                      # untouched


# --- Workspace seal marker writer (merge §9.4 / shared §13.7) -------------------

def test_write_sealed_marker(tmp_path):
    ws = tmp_path / "ws"
    ws.mkdir()
    assert utils.is_sealed(str(ws)) is False
    digest = utils.write_sealed_marker(str(ws), "merge-run-42", "/srv/library")
    assert utils.is_sealed(str(ws)) is True
    data = json.loads(open(utils.sealed_marker_path(str(ws))).read())
    assert data == {"sealed": True, "merged_run_id": "merge-run-42", "library_root": "/srv/library"}
    assert digest == utils.sha256_file(utils.sealed_marker_path(str(ws)))


# --- Library-file fingerprint cache (merge §7 / shared §13.4) -------------------

def _fp(value="abc123"):
    return {"status": "valid", "value": value, "strategy": "image-content-hash-v1",
            "engine_version": "im-7.1"}


def test_library_fingerprint_cache_roundtrip_and_staleness(tmp_path):
    cache = utils.WorkspaceCache(str(tmp_path), in_memory=True)
    try:
        p = "/library/Belgium/Brussels/2024-07-03--14-12-21.arw"
        assert cache.get_cached_library_fingerprint(p, 100, 111) is None      # cold miss
        cache.cache_library_fingerprint(p, 100, 111, _fp("deadbeef"))
        hit = cache.get_cached_library_fingerprint(p, 100, 111)
        assert hit["value"] == "deadbeef"
        assert hit["strategy"] == "image-content-hash-v1"
        assert hit["engine_version"] == "im-7.1"
        # Changed file (different size or mtime) -> miss, must be re-fingerprinted.
        assert cache.get_cached_library_fingerprint(p, 101, 111) is None
        assert cache.get_cached_library_fingerprint(p, 100, 222) is None
        # Re-cache (file changed) overwrites in place.
        cache.cache_library_fingerprint(p, 101, 111, _fp("feedface"))
        assert cache.get_cached_library_fingerprint(p, 101, 111)["value"] == "feedface"
    finally:
        cache.close()


# --- Deep merge-config validation (merge §4 / shared §14.1) --------------------

def _cfg(lib, placement="preserve_destination_structure", collision="suffix_incoming"):
    return {"merge": {"library_root": str(lib), "placement_policy": placement,
                      "collision_policy": collision}}


def test_validate_merge_config_accepts_valid(tmp_path):
    ws = tmp_path / "ws"; ws.mkdir()
    lib = tmp_path / "library"; lib.mkdir()
    utils.validate_merge_config(_cfg(lib), str(ws))      # no raise


def test_validate_merge_config_rejects_bad_inputs(tmp_path):
    import pytest
    ws = tmp_path / "ws"; ws.mkdir()
    lib = tmp_path / "library"; lib.mkdir()

    with pytest.raises(ValueError, match="merge must be an object"):
        utils.validate_merge_config({"merge": "nope"}, str(ws))
    with pytest.raises(ValueError, match="library_root must be a non-empty"):
        utils.validate_merge_config(_cfg(""), str(ws))
    with pytest.raises(ValueError, match="is not an existing directory"):
        utils.validate_merge_config(_cfg(tmp_path / "missing"), str(ws))
    inside = ws / "inside"; inside.mkdir()                 # exists, but inside the workspace
    with pytest.raises(ValueError, match="outside the workspace"):
        utils.validate_merge_config(_cfg(inside), str(ws))
    with pytest.raises(ValueError, match="placement_policy"):
        utils.validate_merge_config(_cfg(lib, placement="year_prefix"), str(ws))
    with pytest.raises(ValueError, match="collision_policy"):
        utils.validate_merge_config(_cfg(lib, collision="overwrite"), str(ws))


def test_validate_merge_config_rejects_library_inside_workspace(tmp_path):
    import pytest
    ws = tmp_path / "ws"; ws.mkdir()
    inside = ws / "6-photos-by-dest"; inside.mkdir()
    with pytest.raises(ValueError, match="outside the workspace"):
        utils.validate_merge_config(_cfg(inside), str(ws))


# --- Shared suffix convention (shared §7.2; merge §7 append-at-max+1) ----------

def test_allocate_suffix_sequential_and_case_insensitive():
    idx = set()
    assert utils.allocate_suffix("name", "arw", idx) == "name-001.arw"
    assert utils.allocate_suffix("name", "arw", idx) == "name-002.arw"   # index mutated
    # A pre-occupied (differently-cased) name is skipped.
    idx2 = {"photo-001.jpg"}
    assert utils.allocate_suffix("Photo", "JPG", idx2) == "Photo-002.JPG"
    # start_idx lets merge begin past the highest existing suffix.
    assert utils.allocate_suffix("x", "tif", set(), start_idx=5) == "x-005.tif"
    # No extension form.
    assert utils.allocate_suffix("base", "", set()) == "base-001"


def test_suffix_root_strips_only_the_dedup_suffix():
    assert utils.suffix_root("foo") == "foo"
    assert utils.suffix_root("foo-001") == "foo"
    assert utils.suffix_root("foo-017") == "foo"
    # A bare civil-time name (2-digit fields) is NOT mistaken for a suffixed name.
    assert utils.suffix_root("2024-07-03--14-12-21") == "2024-07-03--14-12-21"
    # A real dedup suffix on top of a timestamp is stripped back to the timestamp.
    assert utils.suffix_root("2024-07-03--14-12-21-001") == "2024-07-03--14-12-21"


def test_max_suffix():
    names = ["foo.arw", "foo-001.arw", "foo-003.arw", "bar-009.arw"]
    assert utils.max_suffix("foo", names) == 3          # highest for foo, ignores bar
    assert utils.max_suffix("bar", names) == 9
    assert utils.max_suffix("none", names) == 0         # absent root
    assert utils.max_suffix("foo", ["foo.arw"]) == 0    # bare name only -> 0
    # Case-insensitive root match.
    assert utils.max_suffix("FOO", ["foo-005.arw"]) == 5


def test_append_at_max_plus_one_integration():
    # The merge collision-rename composition: root + max(library, incoming) + 1.
    lib_names = ["ts.arw", "ts-002.arw"]
    incoming_names = ["ts-004.arw"]
    root = utils.suffix_root("ts")
    start = max(utils.max_suffix(root, lib_names), utils.max_suffix(root, incoming_names)) + 1
    occupied = {n.lower() for n in lib_names + incoming_names}
    assert utils.allocate_suffix(root, "arw", occupied, start_idx=start) == "ts-005.arw"


# --- Archive re-seal (merge §9.4 / shared §13.6) -------------------------------

def test_reseal_writes_own_manifest_and_never_touches_the_25(tmp_path):
    ws = tmp_path / "ws"
    cd = utils.ensure_control_dir(str(ws))
    # A realistic subset of package artifacts present, including the calibration manifest.
    for name, body in [
        ("photos-00-config.json", {"a": 1}),
        ("photos-11-handoff.json", {"files": []}),
        ("photos-25-complete-log.json", {"photos": {}}),
        ("photos-25-archive-manifest.json", {"artifact_name": "photos-25-archive-manifest.json"}),
        ("photos-31-merge-summary.json", {"status": "success"}),
        ("photos-35-merge-log.json", {"photos": {}}),
    ]:
        utils.write_json_artifact(os.path.join(cd, name), body)
    cal_manifest = os.path.join(cd, "photos-25-archive-manifest.json")
    cal_before = utils.sha256_file(cal_manifest)

    digest = utils.reseal_archival_package(
        str(ws), workspace_name="ws", plan_id="p1", execution_id="e1",
        merge_run_id="m1", generated_at="2026-06-11T00:00:00Z")

    mpath = utils.merge_archive_manifest_path(str(ws))
    assert os.path.isfile(mpath)
    assert digest == utils.sha256_file(mpath)
    manifest = json.loads(open(mpath).read())
    assert manifest["artifact_name"] == "photos-35-archive-manifest.json"
    assert manifest["supersedes"] == "photos-25-archive-manifest.json"
    assert manifest["merge_run_id"] == "m1"
    # Present artifacts are listed with correct hashes; absent ones (e.g. the DB) are omitted.
    c = manifest["contents"]
    assert "photos-31-merge-summary.json" in c and "photos-35-merge-log.json" in c
    assert "photos-25-archive-manifest.json" in c          # calibration's manifest is bundled
    assert "photos-00-ingest.db" not in c                  # not present in this fixture
    assert c["photos-11-handoff.json"]["sha256"] == utils.sha256_file(
        os.path.join(cd, "photos-11-handoff.json"))
    # §13.0a: calibration's own manifest is bundled (read), never rewritten.
    assert utils.sha256_file(cal_manifest) == cal_before
