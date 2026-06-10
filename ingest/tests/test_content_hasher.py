"""Phase 6c-0 — the content-fingerprint engine, now shared in photos_utils (the cross-phase identity
spine prep pins and calibration will recompute after EXIF writes). The `identify` subprocess is
mocked, as the rest of the suite mocks external tools. From conftest.py.
"""
import photos_utils as utils


def test_content_hasher_is_shared():
    assert callable(utils.ContentHasher.fingerprint_image)
    import photos_1_prep as prep
    assert prep.ContentHasher is utils.ContentHasher          # prep re-exports the moved class


def test_fingerprint_image_missing_imagemagick(monkeypatch):
    monkeypatch.setattr(utils, "get_identify_command", lambda: [])
    r = utils.ContentHasher.fingerprint_image("/nope.jpg")
    assert r["status"] == "failed" and r["value"] is None and r["strategy"] == "image-content-hash-v1"
    assert "ImageMagick not found" in r["error"]


def test_fingerprint_image_success(monkeypatch):
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
