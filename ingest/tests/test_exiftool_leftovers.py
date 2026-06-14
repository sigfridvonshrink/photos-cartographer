"""Recognition + quarantine of orphaned exiftool artifacts.

A hard kill (SIGKILL/OOM/power loss) during a calibration metadata write can orphan exiftool's
`<media>_exiftool_tmp` intermediate (or, were `-overwrite_original` ever dropped, a `<media>_original`
backup). The live original is always intact (the rename is atomic). Prep recognizes such leftovers,
pulls them out of the media inventory, and quarantines them (recoverable, never deleted) instead of
mis-parking them forever in 1-strays.

photos_1_prep / photos_utils come from conftest.py.
"""
import os

import pytest

import photos_1_prep as prep
import photos_utils as utils


# --- unit: the recognizer is precise --------------------------------------

@pytest.mark.parametrize("name,expected", [
    ("IMG_1234.jpg_exiftool_tmp", "IMG_1234.jpg"),   # temp from -overwrite_original
    ("shot.CR2_original", "shot.CR2"),               # backup (case-insensitive ext)
    ("clip.mp4_exiftool_tmp", "clip.mp4"),           # video
    ("IMG_1234.jpg", None),                          # a normal media file, no suffix
    ("notes_original", None),                        # no media extension under the suffix
    ("data.txt_original", None),                     # .txt is not media -> not an artifact
    ("_original", None),                             # nothing before the suffix
])
def test_exiftool_artifact_base(name, expected):
    assert utils.exiftool_artifact_base(name) == expected


# --- integration: prep quarantines a leftover in a managed folder ----------

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
    monkeypatch.setattr(prep.ContentHasher, "fingerprint_image",
                        lambda p: {"status": "valid", "strategy": "image-content-hash-v1",
                                   "value": "sig-" + os.path.basename(p), "engine_version": "t"})

    def meta(folders, max_workers=4, progress_coordinator=None):
        res = {}
        for folder in folders:
            for f in os.listdir(folder):
                res[os.path.join(folder, f)] = {
                    "DateTimeOriginal": "2023:01:02 03:04:05",
                    "extraction_status": "extracted_ok", "raw_payload": "{}",
                }
        return res, set()
    monkeypatch.setattr(utils.MetadataReader, "read_metadata_concurrently", meta)


def _plan(ws):
    prep.CONFIG["jobs"] = 1
    return prep.WorkspacePrepWorkflow(str(ws), prep.WorkspaceCache(str(ws), in_memory=True)).plan()


def test_managed_folder_leftover_is_quarantined(tmp_path, monkeypatch):
    _mock(monkeypatch)
    ws = _ws(tmp_path)
    leftover = ws / "5-photos-by-date" / "2023" / "IMG_1.jpg_exiftool_tmp"
    leftover.parent.mkdir(parents=True)
    leftover.write_bytes(b"partial-jpeg-bytes")

    plan = _plan(ws)
    q_ops = [op for op in plan.operations
             if op.type == "quarantine_move" and op.verification.get("kind") == "exiftool_leftover"]
    assert len(q_ops) == 1
    assert q_ops[0].source == "5-photos-by-date/2023/IMG_1.jpg_exiftool_tmp"
    # The leftover is NOT inventoried as media (excluded from the scanned file model).
    assert all("_exiftool_tmp" not in p["relative_path"] for p in plan.workspace_file_preconditions)

    prep.PlanExecutor(str(ws)).execute(plan)
    assert not leftover.exists()                                  # moved out of the managed folder
    qbase = utils.quarantine_dir(str(ws))
    moved = [os.path.join(r, f) for r, _d, fs in os.walk(qbase) for f in fs
             if f.endswith("_exiftool_tmp")]
    assert moved, "leftover should land in recoverable quarantine"
    # It must NOT have been parked in 1-strays.
    strays = [f for _r, _d, fs in os.walk(ws / "1-strays") for f in fs]
    assert not any(s.endswith("_exiftool_tmp") for s in strays)


def test_bydest_leftover_left_untouched_with_warning(tmp_path, monkeypatch):
    _mock(monkeypatch)
    ws = _ws(tmp_path)
    leftover = ws / "6-photos-by-dest" / "Trip" / "IMG_2.jpg_exiftool_tmp"
    leftover.parent.mkdir(parents=True)
    leftover.write_bytes(b"partial")

    plan = _plan(ws)
    assert not [op for op in plan.operations
                if op.type == "quarantine_move" and op.verification.get("kind") == "exiftool_leftover"]
    assert any("by-dest" in w and "_exiftool_tmp" in w for w in plan.warnings)

    prep.PlanExecutor(str(ws)).execute(plan)
    assert leftover.exists()                                      # read-only staging untouched
