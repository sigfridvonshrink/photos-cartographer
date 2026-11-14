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

"""A content fingerprint covers the whole file: every frame of an image, in order, the same whichever of
the two image paths takes it (the persistent `magick -script` worker or the per-file `identify`), and every
stream of a video. Real ImageMagick and ffmpeg, skipped where absent. From conftest.py.
"""
import json
import os
import shutil
import subprocess

import pytest

import photos_1_prep as prep
import photos_utils as utils

requires_magick = pytest.mark.skipif(not shutil.which("magick"), reason="ImageMagick 7 (magick) not available")
requires_ffmpeg = pytest.mark.skipif(not shutil.which("ffmpeg"), reason="ffmpeg not available")
requires_exiftool = pytest.mark.skipif(not shutil.which("exiftool"), reason="exiftool not available")
CAM_SMALL = os.path.join(os.path.dirname(__file__), "fixtures", "cam_small.jpg")


def _magick(*args):
    subprocess.run(["magick", *args], check=True, capture_output=True)


def _pages(path, *colours):
    """A multi-frame TIFF at `path`, one 8x8 page per colour, in order."""
    _magick(*[a for c in colours for a in ("-size", "8x8", f"xc:{c}")], str(path))
    return str(path)


def _both_paths(monkeypatch, path):
    """(persistent worker's result, per-file identify's result) for `path`."""
    worker = utils.ContentHasher.fingerprint_image(path)
    with monkeypatch.context() as m:
        m.setattr(utils, "get_magick_command", lambda: [])
        fallback = utils.ContentHasher.fingerprint_image(path)
    return worker, fallback


def _frame_signature(path):
    """ImageMagick's own signature of the file's single frame, as `identify` prints it."""
    return subprocess.run(["magick", "identify", "-format", "%#", "-colorspace", "sRGB", "-depth", "8", path],
                          check=True, capture_output=True, text=True).stdout.strip()


@requires_magick
@pytest.mark.spec("RUL-fingerprint_covers_every_frame",
                  test="TST-fingerprint_frames-later_frame_tells_images_apart")
def test_later_frame_tells_images_apart(tmp_path, monkeypatch):
    """Two 2-page TIFFs sharing their first page and differing in their second are different photos, on
    both paths."""
    a = _pages(tmp_path / "a.tif", "red", "blue")
    b = _pages(tmp_path / "b.tif", "red", "green")
    wa, fa = _both_paths(monkeypatch, a)
    wb, fb = _both_paths(monkeypatch, b)
    assert {wa["status"], fa["status"], wb["status"], fb["status"]} == {"valid"}
    assert wa["value"] != wb["value"]
    assert fa["value"] != fb["value"]


@requires_magick
@pytest.mark.spec("RUL-fingerprint_covers_every_frame",
                  test="TST-fingerprint_frames-frame_order_matters")
def test_frame_order_matters(tmp_path, monkeypatch):
    """The same frames in another order are another image."""
    ab = _both_paths(monkeypatch, _pages(tmp_path / "ab.tif", "red", "blue"))
    ba = _both_paths(monkeypatch, _pages(tmp_path / "ba.tif", "blue", "red"))
    assert ab[0]["value"] != ba[0]["value"] and ab[1]["value"] != ba[1]["value"]


@requires_magick
@pytest.mark.spec("RUL-fingerprint_covers_every_frame",
                  test="TST-fingerprint_frames-both_paths_agree_on_many_frames")
def test_both_paths_agree_on_many_frames(tmp_path, monkeypatch):
    """The worker and `identify` give one value for the same file, a 70-frame one too: no count of
    frames makes a legitimate file fail."""
    two = _pages(tmp_path / "two.tif", "red", "blue")
    many = str(tmp_path / "many.gif")
    _magick(*[a for i in range(70) for a in ("-size", "4x4", f"xc:rgb({i},{2 * i},{3 * i})")], many)
    for path in (two, many):
        worker, fallback = _both_paths(monkeypatch, path)
        assert worker["status"] == fallback["status"] == "valid", (worker, fallback)
        assert worker["value"] == fallback["value"]
        assert worker["value"] == _both_paths(monkeypatch, path)[0]["value"]       # and it is stable


@requires_magick
@pytest.mark.spec("RUL-fingerprint_covers_every_frame",
                  test="TST-fingerprint_frames-single_frame_value_is_its_signature")
def test_single_frame_value_is_its_signature(tmp_path, monkeypatch):
    """A single-frame image's fingerprint is that frame's signature, as before, on both paths."""
    one = _pages(tmp_path / "one.tif", "red")
    for path in (one, CAM_SMALL):
        worker, fallback = _both_paths(monkeypatch, path)
        assert worker["value"] == fallback["value"] == _frame_signature(path)


@requires_magick
@requires_exiftool
@pytest.mark.spec("RUL-fingerprint_covers_every_frame",
                  test="TST-fingerprint_frames-prep_keeps_pages_differing_after_the_first")
def test_prep_keeps_pages_differing_after_the_first(tmp_path):
    """Prep does not quarantine one of two TIFFs as the other's duplicate because their first pages agree;
    two copies of one TIFF are still duplicates."""
    ws = tmp_path / "ws"
    ws.mkdir()
    for d in ("0-sources", "1-strays", "2-missing-metadata", "3-redundant-jpgs",
              "4-videos-by-date", "5-photos-by-date", "6-photos-by-dest"):
        (ws / d).mkdir()
    (ws / ".photos-ingest").mkdir()
    (ws / ".photos-ingest" / "photos-00-workspace-guard").touch()
    _pages(ws / "0-sources" / "a.tiff", "red", "blue")
    _pages(ws / "0-sources" / "b.tiff", "red", "green")
    prep.CONFIG["jobs"] = 1

    def quarantined():
        plan = prep.WorkspacePrepWorkflow(str(ws), prep.WorkspaceCache(str(ws), in_memory=True)).plan()
        assert plan.blockers == [], plan.blockers
        return [op.source for op in plan.operations if op.type == "quarantine_move"]

    assert quarantined() == []
    shutil.copy(ws / "0-sources" / "a.tiff", ws / "0-sources" / "c.tiff")
    assert len(quarantined()) == 1


def _clip(path, *tones):
    """An mp4 with one video stream and an audio stream per tone, in order."""
    cmd = ["ffmpeg", "-nostdin", "-loglevel", "error", "-y",
           "-f", "lavfi", "-i", "testsrc=size=32x32:rate=5:duration=1"]
    for t in tones:
        cmd += ["-f", "lavfi", "-i", f"sine=f={t}:d=1"]
    for i in range(len(tones) + 1):
        cmd += ["-map", str(i)]
    subprocess.run(cmd + ["-c:v", "mpeg4", "-c:a", "aac", str(path)], check=True, capture_output=True)
    return str(path)


@requires_ffmpeg
@pytest.mark.spec("RUL-fingerprint_covers_every_stream",
                  test="TST-fingerprint_frames-second_audio_stream_tells_videos_apart")
def test_second_audio_stream_tells_videos_apart(tmp_path):
    """Two clips alike but for their second audio stream are different videos; one clip is itself."""
    a = _clip(tmp_path / "a.mp4", 440, 660)
    b = _clip(tmp_path / "b.mp4", 440, 880)
    fa, fb = utils.ContentHasher.fingerprint_video(a), utils.ContentHasher.fingerprint_video(b)
    assert fa["status"] == fb["status"] == "valid"
    assert fa["value"] != fb["value"]
    assert utils.ContentHasher.fingerprint_video(a)["value"] == fa["value"]


@requires_ffmpeg
@pytest.mark.spec("RUL-fingerprint_covers_every_stream",
                  test="TST-fingerprint_frames-subtitle_and_timecode_streams_are_covered")
def test_subtitle_and_timecode_streams_are_covered(tmp_path):
    """A clip holding a subtitle stream and a timecode data stream fingerprints, and its subtitles count."""
    def clip(name, text):
        srt = tmp_path / f"{name}.srt"
        srt.write_text(f"1\n00:00:00,000 --> 00:00:00,500\n{text}\n")
        out = tmp_path / f"{name}.mov"
        subprocess.run(["ffmpeg", "-nostdin", "-loglevel", "error", "-y",
                        "-f", "lavfi", "-i", "testsrc=size=32x32:rate=5:duration=1", "-i", str(srt),
                        "-map", "0", "-map", "1", "-c:v", "mpeg4", "-c:s", "mov_text",
                        "-timecode", "01:00:00:00", str(out)], check=True, capture_output=True)
        return utils.ContentHasher.fingerprint_video(str(out))
    one, other = clip("one", "hello"), clip("other", "world")
    assert one["status"] == other["status"] == "valid", (one, other)
    assert one["value"] != other["value"]


@pytest.mark.spec("RUL-fingerprint_covers_every_frame", "RUL-fingerprint_covers_every_stream",
                  test="TST-fingerprint_frames-earlier_method_values_are_not_reused")
def test_earlier_method_values_are_not_reused(tmp_path):
    """A fingerprint recorded by the method that hashed only the first frame, or only the default streams,
    is never reused — in prep's records or in merge's library cache — so it is never compared with one
    taken the way this build takes it."""
    old_image = json.dumps({"status": "valid", "strategy": "image-content-hash-v1", "value": "x" * 64,
                            "engine_version": "im-1"})
    old_video = json.dumps({"status": "valid", "strategy": "video-md5-v1", "value": "y" * 32})
    assert utils.fingerprint_reusable(old_image, "image", "im-1") is False
    assert utils.fingerprint_reusable(old_image, "raw", "im-1") is False
    assert utils.fingerprint_reusable(old_video, "video", "im-1") is False
    current = json.dumps({"status": "valid", "strategy": utils.IMAGE_FINGERPRINT_STRATEGY, "value": "x" * 64,
                          "engine_version": "im-1"})
    assert utils.fingerprint_reusable(current, "image", "im-1") is True
    cache = utils.WorkspaceCache(str(tmp_path), in_memory=True)
    cache.cache_library_fingerprint("/lib/a.tif", 10, 20, json.loads(old_image))
    assert cache.get_cached_library_fingerprint("/lib/a.tif", 10, 20, "im-1") is None
    cache.cache_library_fingerprint("/lib/a.tif", 10, 20, json.loads(current))
    assert cache.get_cached_library_fingerprint("/lib/a.tif", 10, 20, "im-1")["value"] == "x" * 64


def _scripted_worker(monkeypatch, lines):
    """A persistent worker whose magick process answers `lines` (an iterator) to whatever it is sent."""
    class _Proc:
        def __init__(self):
            self.stdin = self.stdout = self
        def write(self, s): pass
        def flush(self): pass
        def readline(self): return next(lines)
        def close(self): pass
        def wait(self, timeout=None): pass
        def kill(self): pass
    monkeypatch.setattr(utils, "get_magick_command", lambda: ["magick"])
    monkeypatch.setattr(utils.subprocess, "Popen", lambda *a, **k: _Proc())
    return utils.PersistentMagickWorker()


@pytest.mark.spec("RUL-fingerprint_covers_every_frame", test="TST-fingerprint_frames-worker_reads_every_frame_line")
def test_worker_reads_every_frame_line(monkeypatch):
    """However many frames a file has, every signature line is read and folded; an answer that is not a
    signature is a broken process, never a read without end."""
    import itertools
    sigs = [f"{i:064x}" for i in range(200)]
    w = _scripted_worker(monkeypatch, iter([s + "\n" for s in sigs] + ["{ready}\n"]))
    try:
        assert w.signature("/many.gif") == utils.frames_fingerprint(sigs)
    finally:
        w.close()
    w = _scripted_worker(monkeypatch, itertools.repeat("garbage\n"))
    try:
        with pytest.raises(utils.ProcessCrashedError):
            w.signature("/broken.tif")
    finally:
        w.close()
