"""Phase 6c-0 — the content-fingerprint engine (the cross-phase identity spine prep pins and
calibration recomputes after EXIF writes). The default path is a persistent `magick -script -` worker
(§17.5), reused across files; a magick-less system falls back to per-file `identify`. Tools are
mocked, as the rest of the suite mocks external tools. From conftest.py.
"""
import photos_utils as utils


def test_content_hasher_is_shared():
    assert callable(utils.ContentHasher.fingerprint_image)
    import photos_1_prep as prep
    assert prep.ContentHasher is utils.ContentHasher          # prep re-exports the moved class


def test_fingerprint_image_missing_imagemagick(monkeypatch):
    monkeypatch.setattr(utils, "get_magick_command", lambda: [])
    monkeypatch.setattr(utils, "get_identify_command", lambda: [])
    r = utils.ContentHasher.fingerprint_image("/nope.jpg")
    assert r["status"] == "failed" and r["value"] is None and r["strategy"] == "image-content-hash-v1"
    assert "ImageMagick not found" in r["error"]


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
    assert res == {"status": "valid", "strategy": "image-content-hash-v1",
                   "value": "sig-abc123", "engine_version": "magick-test"}


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
    assert res == {"status": "valid", "strategy": "image-content-hash-v1",
                   "value": "sig-abc123", "engine_version": "magick-test"}


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
