"""Phase 11 — fallback / error branches the happy path skips.

photos_1_prep / photos_utils come from conftest.py.
"""
import shutil
import subprocess

import pytest

import photos_1_prep as prep
import photos_utils as utils


def test_move_no_clobber_uses_link_unlink_fallback(tmp_path, monkeypatch):
    # Force the renameat2-unavailable path so _move_no_clobber goes through link+unlink.
    monkeypatch.setattr(prep, "_get_renameat2", lambda: False)
    src = tmp_path / "a"; src.write_bytes(b"X")
    dest = tmp_path / "b"
    prep._move_no_clobber(str(src), str(dest))
    assert dest.read_bytes() == b"X" and not src.exists()

    s2 = tmp_path / "s2"; s2.write_bytes(b"Y")
    d2 = tmp_path / "d2"; d2.write_bytes(b"KEEP")
    with pytest.raises(FileExistsError):
        prep._move_no_clobber(str(s2), str(d2))
    assert d2.read_bytes() == b"KEEP" and s2.read_bytes() == b"Y"   # refused + preserved


def test_get_exiftool_version_unknown_on_error(monkeypatch):
    monkeypatch.setattr(subprocess, "check_output",
                        lambda *a, **k: (_ for _ in ()).throw(FileNotFoundError("no exiftool")))
    assert utils.get_exiftool_version() == "unknown"


def test_get_imagemagick_version_unknown_when_absent(monkeypatch):
    monkeypatch.setattr(utils, "_IMAGEMAGICK_VERSION", None)     # bypass the per-process cache
    monkeypatch.setattr(shutil, "which", lambda name: None)      # neither magick nor identify present
    assert utils.get_imagemagick_version() == "unknown"
