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

"""Phase 6c-0 — the content-fingerprint engine (the cross-phase identity spine prep pins and
geotag recomputes after EXIF writes). The default path is a persistent `magick -script -` worker
(BLD-tool_workers), reused across files; a magick-less system falls back to per-file `identify`. Tools are
mocked, as the rest of the suite mocks external tools. From conftest.py.
"""
import photos_utils as utils
import pytest


def test_content_hasher_is_shared():
    assert callable(utils.ContentHasher.fingerprint_image)
    import photos_1_prep as prep
    assert prep.ContentHasher is utils.ContentHasher          # prep re-exports the moved class


def test_fingerprint_image_missing_imagemagick(monkeypatch):
    monkeypatch.setattr(utils, "get_magick_command", lambda: [])
    monkeypatch.setattr(utils, "get_identify_command", lambda: [])
    r = utils.ContentHasher.fingerprint_image("/nope.jpg")
    assert r["status"] == "failed" and r["value"] is None and r["strategy"] == "image-content-hash-v2"
    assert "ImageMagick not found" in r["error"]


@pytest.mark.spec("BLD-identify_silence_limit", test="TST-content_hasher-a_silent_identify_is_killed_after_ten_seconds")
def test_a_silent_identify_is_killed_after_ten_seconds(monkeypatch):
    """Without `magick`, an `identify` that gives no output for ten seconds is killed; after its two attempts the
    fingerprint is failed, never valid. The wait is answered at once here, so the test takes no ten seconds."""
    import types
    import sys
    monkeypatch.setattr(utils, "get_magick_command", lambda: [])
    monkeypatch.setattr(utils, "get_identify_command",
                        lambda: [sys.executable, "-c", "import time; time.sleep(60)"])
    waits, procs = [], []
    real_popen = utils.subprocess.Popen

    def popen(*a, **k):
        procs.append(real_popen(*a, **k))
        return procs[-1]

    def select(rlist, wlist, xlist, timeout):
        waits.append(timeout)
        return [], [], []                                  # the wait ran out with nothing to read
    monkeypatch.setattr(utils.subprocess, "Popen", popen)
    monkeypatch.setattr(utils, "select", types.SimpleNamespace(select=select))
    r = utils.ContentHasher.fingerprint_image("/slow.cr2")
    assert r["status"] == "failed" and r["value"] is None and "timed out" in r["error"]
    assert waits == [10.0, 10.0]                              # two attempts, each waiting ten seconds
    for p in procs:
        assert p.wait(timeout=5) is not None                  # each attempt's process was killed


@pytest.mark.spec("BLD-tool_workers", test="TST-content_hasher-fingerprint_image_uses_persistent_worker")
def test_fingerprint_image_uses_persistent_worker(monkeypatch):
    """Default path: the per-thread persistent magick worker returns the signature."""
    monkeypatch.setattr(utils, "get_magick_command", lambda: ["magick"])
    monkeypatch.setattr(utils, "get_imagemagick_version", lambda: "magick-test")

    class _W:
        closed = False
        def signature(self, p):
            return "sig-abc123"
        def restart(self):
            pass
    monkeypatch.setattr(utils, "_thread_magick_worker", lambda: _W())
    res = utils.ContentHasher.fingerprint_image("/img.jpg")
    assert res == {"status": "valid", "strategy": "image-content-hash-v2",
                   "value": "sig-abc123", "engine_version": "magick-test"}


@pytest.mark.spec("RUL-tool_failure_retried", "RUL-tool_failure_never_valid",
                  test="TST-content_hasher-fingerprint_image_worker_crash_fails_after_retry")
def test_fingerprint_image_worker_crash_fails_after_retry(monkeypatch):
    """A worker that keeps crashing is restarted, retried once, then reported failed (never confirmed)."""
    monkeypatch.setattr(utils, "get_magick_command", lambda: ["magick"])
    monkeypatch.setattr(utils, "get_imagemagick_version", lambda: "v")
    restarts = []

    class _W:
        closed = False
        def signature(self, p):
            raise utils.ProcessCrashedError("boom")
        def restart(self):
            restarts.append(1)
    monkeypatch.setattr(utils, "_thread_magick_worker", lambda: _W())
    res = utils.ContentHasher.fingerprint_image("/bad.jpg")
    assert res["status"] == "failed" and "boom" in res["error"]
    assert len(restarts) == 2                                  # restarted on each of the 2 attempts


@pytest.mark.spec("RUL-tool_failure_retried", "RUL-tool_failure_never_valid",
                  test="TST-content_hasher-ffmpeg_that_cannot_be_run_fails_the_fingerprint")
def test_ffmpeg_that_cannot_be_run_fails_the_fingerprint(monkeypatch):
    """ffmpeg that cannot be run — an OSError other than its absence — is tried twice, then recorded as the file's
    failed fingerprint; the error never escapes the scan."""
    calls = []

    def run(*a, **k):
        calls.append(1)
        raise PermissionError(13, "Permission denied")
    monkeypatch.setattr(utils.subprocess, "run", run)
    res = utils.ContentHasher.fingerprint_video("/clip.mp4")
    assert res["status"] == "failed" and res["value"] is None and "Permission denied" in res["error"]
    assert len(calls) == 2


def test_fingerprint_image_falls_back_to_per_file_identify(monkeypatch):
    """No `magick` script mode on this system -> the legacy per-file `identify` path."""
    monkeypatch.setattr(utils, "get_magick_command", lambda: [])
    monkeypatch.setattr(utils, "get_identify_command", lambda: ["identify"])
    monkeypatch.setattr(utils, "get_imagemagick_version", lambda: "magick-test")

    class _Proc:
        returncode = 0
        def __init__(self):
            self.stdout = self
            self._chunks = ["sig-abc123\n", ""]
        def read(self, _n):
            return self._chunks.pop(0)
        def wait(self):
            pass
    monkeypatch.setattr(utils.subprocess, "Popen", lambda *a, **k: _Proc())
    monkeypatch.setattr(utils.select, "select", lambda r, w, x, t: (r, [], []))
    res = utils.ContentHasher.fingerprint_image("/img.jpg")
    assert res == {"status": "valid", "strategy": "image-content-hash-v2",
                   "value": "sig-abc123", "engine_version": "magick-test"}


@pytest.mark.spec("BLD-tool_workers", test="TST-content_hasher-persistent_magick_worker_protocol")
def test_persistent_magick_worker_protocol(monkeypatch):
    """signature() sends the `-read ... -print %# ... {ready}` script and returns the line before
    the {ready} sentinel."""
    monkeypatch.setattr(utils, "get_magick_command", lambda: ["magick"])
    sent = []

    class _Proc:
        def __init__(self):
            self.stdin = self
            self.stdout = self
            self._out = iter(["e45edb40\n", "{ready}\n"])
        def write(self, s):
            sent.append(s)
        def flush(self):
            pass
        def readline(self):
            return next(self._out)
        def close(self):
            pass
        def wait(self, timeout=None):
            pass
        def kill(self):
            pass
    monkeypatch.setattr(utils.subprocess, "Popen", lambda *a, **k: _Proc())
    w = utils.PersistentMagickWorker()
    try:
        assert w.signature("/a b.jpg") == "e45edb40"
        assert '-read "/a b.jpg"' in sent[0] and "%#" in sent[0]
    finally:
        w.close()
