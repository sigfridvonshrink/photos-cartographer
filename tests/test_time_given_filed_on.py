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

"""A file in missing metadata given a time by hand is filed on by the next prep run (BACKLOG 50, case 6).

Prep sets a file with no recorded time apart in missing metadata; once the user writes it a time where it lies, the
next prep run files it as it files a file of a new dump — photos into photos by date, videos into videos by date, in
the day's folder under the timestamp name, suffixed on a clash, set aside if it is a copy of one already filed — and
the check of the next run finds the workspace as that execution left it. One still without a time stays.

Prep runs for real, its fingerprint and metadata reading stood in for: a file's "pixels" are what comes before `|`,
so a time written by hand (`|TIME:...`) changes the file but not its fingerprint, as with a real photo."""
import glob
import hashlib
import json
import os
import types

import pytest

import photos_1_prep as prep
import photos_utils as utils
from cartographer.reporting import CaptureSink, ChangesEvent, Reporter, use_reporter

MANAGED = ["0-sources", "1-strays", "2-missing-metadata", "3-redundant-jpgs",
           "4-videos-by-date", "5-photos-by-date", "6-photos-by-dest"]
MISSING, BY_DATE, VIDEOS = "2-missing-metadata", "5-photos-by-date", "4-videos-by-date"
WHEN = "2023:01:02 03:04:05"


def _fp(p):
    with open(p, "rb") as f:
        return "sig-" + hashlib.sha256(f.read().split(b"|", 1)[0]).hexdigest()[:24]


def _install(monkeypatch):
    prep.CONFIG["zfs"] = {"enabled": False}
    prep.CONFIG["jobs"] = 1
    monkeypatch.setattr(prep.ContentHasher, "fingerprint_image",
                        lambda p: {"status": "valid", "strategy": "image-content-hash-v2", "value": _fp(p),
                                   "engine_version": "t"})
    monkeypatch.setattr(prep.ContentHasher, "fingerprint_video",
                        lambda p: {"status": "valid", "strategy": "video-md5-v2", "value": _fp(p)})

    def meta(folders, max_workers=4, progress_coordinator=None):
        res = {}
        for fo in folders:
            for fn in os.listdir(fo):
                p = os.path.join(fo, fn)
                if not os.path.isfile(p):
                    continue
                data = open(p, "rb").read()
                timed = b"|TIME:" in data
                res[p] = {"extraction_status": "extracted_ok",
                          **({"DateTimeOriginal": data.split(b"|TIME:", 1)[1].decode()} if timed else {})}
        return res, set()
    monkeypatch.setattr(utils.MetadataReader, "read_metadata_concurrently", meta)


def _ws(tmp_path):
    ws = tmp_path / "ws"
    ws.mkdir(parents=True)
    for d in MANAGED:
        (ws / d).mkdir()
    (ws / ".photos-ingest").mkdir()
    (ws / ".photos-ingest" / "photos-00-workspace-guard").touch()
    return ws


def _prep(monkeypatch, ws, command):
    """Run a prep command as the command line does; (exit status, everything it said, the stop's event or None)."""
    sink = CaptureSink()
    monkeypatch.chdir(ws)
    with use_reporter(Reporter([sink])):
        try:
            prep.run(types.SimpleNamespace(command=command, jobs=1, accept_changes=None))
            rc = 0
        except SystemExit as e:
            rc = e.code or 0
    stops = [e for e in sink.events if isinstance(e, ChangesEvent)]
    return rc, "\n".join(e.msg for e in sink.logs()), (stops[-1] if stops else None)


def _ingest(monkeypatch, ws):
    for cmd in ("plan", "execute"):
        rc, said, _ = _prep(monkeypatch, ws, cmd)
        assert rc == 0, said


def _dump(monkeypatch, tmp_path, files):
    """A workspace whose first dump, `files` ({name: bytes}), prep has filed."""
    _install(monkeypatch)
    ws = _ws(tmp_path)
    for name, content in files.items():
        (ws / "0-sources" / name).write_bytes(content)
    _ingest(monkeypatch, ws)
    return ws


def _give_time(path, when=WHEN):
    with open(path, "ab") as f:
        f.write(b"|TIME:" + when.encode())


def _rel(ws, pattern):
    return sorted(os.path.relpath(p, ws) for p in glob.glob(str(ws / pattern), recursive=True))


def _log(ws):
    with open(utils.prep_log_path(str(ws))) as f:
        return json.load(f)


@pytest.mark.spec("RUL-time_given_filed_on", "RUL-filed_file_stays", "BLD-time_given_organized",
                  "RUL-hand_time_passes", "RUL-execution_records_state",
                  test="TST-time_given_filed_on-a_photo_given_a_time_is_filed_and_named")
def test_a_photo_given_a_time_is_filed_and_named(tmp_path, monkeypatch):
    """Two photos set apart for want of a time; one is given a time where it lies. The next prep run files it into
    its day's folder of photos by date under its timestamp name, its journey in prep's log gaining the steps a
    dump's photo takes, and names the change by hand; the other, still untimed, stays as it was. The next run's
    check finds the workspace as that execution left it, and plans nothing for either."""
    ws = _dump(monkeypatch, tmp_path, {"a.jpg": b"PIX-A", "b.jpg": b"PIX-B"})
    assert _rel(ws, f"{MISSING}/*") == [f"{MISSING}/UNKN_a.jpg", f"{MISSING}/UNKN_b.jpg"]
    fp = _fp(ws / MISSING / "UNKN_a.jpg")
    _give_time(ws / MISSING / "UNKN_a.jpg")

    rc, said, stop = _prep(monkeypatch, ws, "plan")
    assert rc == 0 and stop is None and "changed by hand" in said, said
    rc, said, _ = _prep(monkeypatch, ws, "execute")
    assert rc == 0, said

    assert _rel(ws, f"{BY_DATE}/**/*.jpg") == [f"{BY_DATE}/2023-01-02/2023-01-02--03-04-05.jpg"]
    assert _rel(ws, f"{MISSING}/*") == [f"{MISSING}/UNKN_b.jpg"]                # still untimed: stays
    assert (ws / MISSING / "UNKN_b.jpg").read_bytes() == b"PIX-B"
    log = _log(ws)
    assert [c["kind"] for c in log["workspace_changes"]] == ["time_given"]
    entry = log["photos"][fp]
    assert entry["prep_path"] == f"{BY_DATE}/2023-01-02/2023-01-02--03-04-05.jpg"
    assert [s["action"] for s in entry["journey"]] == ["organized", "provisional_rename",
                                                       "organized", "provisional_rename"]
    assert entry["journey"][-2]["from"] == f"{MISSING}/UNKN_a.jpg"
    assert entry["journey"][-1] == dict(entry["journey"][-1], **{"from": "UNKN_a.jpg",
                                                                 "to": "2023-01-02--03-04-05.jpg"})

    rc, said, stop = _prep(monkeypatch, ws, "plan")                             # the move was prep's own
    assert rc == 0 and stop is None and "changed by hand" not in said, said
    plan = json.load(open(utils.prep_plan_path(str(ws))))
    assert not [o for o in plan["operations"] if o["type"] in ("move_no_clobber", "rename_no_clobber",
                                                               "quarantine_move")], plan["operations"]


@pytest.mark.spec("RUL-time_given_filed_on", "BLD-time_given_organized",
                  test="TST-time_given_filed_on-a_video_given_a_time_is_filed_into_videos_by_date")
def test_a_video_given_a_time_is_filed_into_videos_by_date(tmp_path, monkeypatch):
    """Missing metadata holds videos too: one given a time is filed into its day's folder of videos by date."""
    ws = _dump(monkeypatch, tmp_path, {"clip.MP4": b"FRAMES-1"})
    assert _rel(ws, f"{MISSING}/*") == [f"{MISSING}/UNKN_clip.mp4"]
    _give_time(ws / MISSING / "UNKN_clip.mp4")
    _ingest(monkeypatch, ws)
    assert _rel(ws, f"{VIDEOS}/**/*.mp4") == [f"{VIDEOS}/2023-01-02/2023-01-02--03-04-05.mp4"]
    assert _rel(ws, f"{MISSING}/*") == []
    rc, said, stop = _prep(monkeypatch, ws, "plan")
    assert rc == 0 and stop is None, said


@pytest.mark.spec("RUL-time_given_filed_on", "RUL-copy_kept_by_folder", "RUL-duplicate_set_aside_as_found",
                  "BLD-time_given_organized", test="TST-time_given_filed_on-a_copy_of_one_already_filed_is_quarantined")
def test_a_copy_of_one_already_filed_is_quarantined(tmp_path, monkeypatch):
    """A file in missing metadata given a time, a copy of a photo already in photos by date — the same pixels — is
    set aside into the quarantine from where it lies, as a dump's copy would be, the photo already filed kept; and
    where its twin arrives in the inbox with the time given, it is the one kept and filed, the dump's copy set
    aside — the order of folders a copy is kept by, the same for both."""
    _install(monkeypatch)
    ws = _ws(tmp_path)
    filed = ws / BY_DATE / "2023-01-02" / "2023-01-02--03-04-05.jpg"
    filed.parent.mkdir()
    filed.write_bytes(b"PIX-A|TIME:" + WHEN.encode())
    (ws / MISSING / "UNKN_x.jpg").write_bytes(b"PIX-A|TIME:" + WHEN.encode())
    rc, said, _ = _prep(monkeypatch, ws, "plan")
    assert rc == 0, said
    ops = json.load(open(utils.prep_plan_path(str(ws))))["operations"]
    assert [(o["type"], o["source"]) for o in ops if o["source"] and o["source"].startswith(MISSING)] == [
        ("quarantine_move", f"{MISSING}/UNKN_x.jpg")]
    rc, said, _ = _prep(monkeypatch, ws, "execute")
    assert rc == 0, said
    assert _rel(ws, f"{BY_DATE}/**/*.jpg") == [os.path.relpath(filed, ws)] and _rel(ws, f"{MISSING}/*") == []
    assert _rel(ws, f"{utils.QUARANTINE_DIR}/*/{MISSING}/*") and _prep(monkeypatch, ws, "plan")[2] is None

    ws2 = _dump(monkeypatch, tmp_path / "two", {"x.jpg": b"PIX-B"})
    _give_time(ws2 / MISSING / "UNKN_x.jpg")
    (ws2 / "0-sources" / "a.jpg").write_bytes(b"PIX-B|TIME:" + WHEN.encode())
    rc, said, _ = _prep(monkeypatch, ws2, "plan")
    assert rc == 0, said
    ops = json.load(open(utils.prep_plan_path(str(ws2))))["operations"]
    assert [o["source"] for o in ops if o["type"] == "quarantine_move"] == ["0-sources/a.jpg"]
    rc, said, _ = _prep(monkeypatch, ws2, "execute")
    assert rc == 0, said
    assert _rel(ws2, f"{BY_DATE}/**/*.jpg") == [f"{BY_DATE}/2023-01-02/2023-01-02--03-04-05.jpg"]
    kept = _log(ws2)["photos"][_fp(ws2 / BY_DATE / "2023-01-02" / "2023-01-02--03-04-05.jpg")]
    assert [s.get("from") for s in kept["journey"] if s["action"] == "organized"][-1] == f"{MISSING}/UNKN_x.jpg"
    assert [q["origin"] for q in kept["deduplicated"]["quarantined"]] == ["0-sources/a.jpg"]


@pytest.mark.spec("RUL-time_given_filed_on", "RUL-suffix_no_clobber", "BLD-time_given_organized",
                  test="TST-time_given_filed_on-a_name_clash_is_suffixed")
def test_a_name_clash_is_suffixed(tmp_path, monkeypatch):
    """A file given the time of a photo already filed by date — another photo, of other pixels — is filed beside it
    under its timestamp name suffixed, never over it."""
    ws = _dump(monkeypatch, tmp_path, {"a.jpg": b"PIX-A|TIME:" + WHEN.encode(), "b.jpg": b"PIX-B"})
    first = ws / BY_DATE / "2023-01-02" / "2023-01-02--03-04-05.jpg"
    assert first.exists() and (ws / MISSING / "UNKN_b.jpg").exists()
    _give_time(ws / MISSING / "UNKN_b.jpg")
    _ingest(monkeypatch, ws)
    assert _rel(ws, f"{BY_DATE}/**/*.jpg") == [f"{BY_DATE}/2023-01-02/2023-01-02--03-04-05-001.jpg",
                                               f"{BY_DATE}/2023-01-02/2023-01-02--03-04-05.jpg"]
    assert first.read_bytes() == b"PIX-A|TIME:" + WHEN.encode()
    assert _prep(monkeypatch, ws, "plan")[2] is None
