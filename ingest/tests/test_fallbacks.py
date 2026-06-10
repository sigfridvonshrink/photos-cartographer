"""Phase 11 — fallback / error branches the happy path skips.

photos_1_prep / photos_utils come from conftest.py.
"""
import errno
import os
import shutil
import subprocess

import pytest

import photos_1_prep as prep
import photos_utils as utils


def test_move_no_clobber_uses_link_unlink_fallback(tmp_path, monkeypatch):
    # Force the renameat2-unavailable path so _move_no_clobber goes through link+unlink.
    # _get_renameat2 / _move_no_clobber now live in photos_utils (Phase 0 shared infra).
    monkeypatch.setattr(utils, "_get_renameat2", lambda: False)
    src = tmp_path / "a"; src.write_bytes(b"X")
    dest = tmp_path / "b"
    utils._move_no_clobber(str(src), str(dest))
    assert dest.read_bytes() == b"X" and not src.exists()

    s2 = tmp_path / "s2"; s2.write_bytes(b"Y")
    d2 = tmp_path / "d2"; d2.write_bytes(b"KEEP")
    with pytest.raises(FileExistsError):
        utils._move_no_clobber(str(s2), str(d2))
    assert d2.read_bytes() == b"KEEP" and s2.read_bytes() == b"Y"   # refused + preserved


def test_get_exiftool_version_unknown_on_error(monkeypatch):
    monkeypatch.setattr(subprocess, "check_output",
                        lambda *a, **k: (_ for _ in ()).throw(FileNotFoundError("no exiftool")))
    assert utils.get_exiftool_version() == "unknown"


def test_get_imagemagick_version_unknown_when_absent(monkeypatch):
    monkeypatch.setattr(utils, "_IMAGEMAGICK_VERSION", None)     # bypass the per-process cache
    monkeypatch.setattr(shutil, "which", lambda name: None)      # neither magick nor identify present
    assert utils.get_imagemagick_version() == "unknown"


# --- cross-filesystem move fallback (shared contract §15.3) -------------------

def test_cross_fs_move_copies_then_removes_source(tmp_path):
    sub = tmp_path / "sub"; sub.mkdir()
    src = tmp_path / "s"; src.write_bytes(b"PHOTO")
    dest = sub / "x.jpg"
    utils._move_cross_fs_no_clobber(str(src), str(dest))
    assert dest.read_bytes() == b"PHOTO" and not src.exists()
    assert not list(sub.glob(".tmp-xdev-*"))                    # temp cleaned


def test_cross_fs_move_is_no_clobber(tmp_path):
    src = tmp_path / "s"; src.write_bytes(b"NEW")
    dest = tmp_path / "x.jpg"; dest.write_bytes(b"KEEP")
    with pytest.raises(FileExistsError):
        utils._move_cross_fs_no_clobber(str(src), str(dest))
    assert dest.read_bytes() == b"KEEP" and src.read_bytes() == b"NEW"   # neither touched
    assert not list(tmp_path.glob(".tmp-xdev-*"))


def test_cross_fs_move_aborts_on_verify_failure(tmp_path):
    src = tmp_path / "s"; src.write_bytes(b"Z")
    dest = tmp_path / "x.jpg"
    def bad_verify(s, t):
        raise OSError("verify failed")
    with pytest.raises(OSError):
        utils._move_cross_fs_no_clobber(str(src), str(dest), verify=bad_verify)
    assert src.exists() and not dest.exists()                   # source kept, no destination
    assert not list(tmp_path.glob(".tmp-xdev-*"))


def _exdev_seam(monkeypatch):
    """Make the first same-fs rename (the original src->dest) report EXDEV, then delegate to the real
    primitive for the cross-fs helper's internal tmp->dest rename."""
    real = utils._rename_no_clobber_same_fs
    seen = {"n": 0}
    def fake(s, d):
        seen["n"] += 1
        if seen["n"] == 1:
            raise OSError(errno.EXDEV, "Invalid cross-device link")
        return real(s, d)
    monkeypatch.setattr(utils, "_rename_no_clobber_same_fs", fake)
    return seen


def test_move_no_clobber_falls_back_to_cross_fs_on_exdev(tmp_path, monkeypatch):
    seen = _exdev_seam(monkeypatch)
    src = tmp_path / "s"; src.write_bytes(b"XDEV")
    dest = tmp_path / "d.jpg"
    utils._move_no_clobber(str(src), str(dest))
    assert dest.read_bytes() == b"XDEV" and not src.exists() and seen["n"] == 2


def test_move_no_clobber_cross_fs_preserves_on_existing_dest(tmp_path, monkeypatch):
    _exdev_seam(monkeypatch)
    src = tmp_path / "s"; src.write_bytes(b"NEW")
    dest = tmp_path / "d.jpg"; dest.write_bytes(b"KEEP")
    with pytest.raises(FileExistsError):
        utils._move_no_clobber(str(src), str(dest))
    assert dest.read_bytes() == b"KEEP" and src.read_bytes() == b"NEW"
    assert not list(tmp_path.glob(".tmp-xdev-*"))               # temp cleaned on the no-clobber abort


def test_rename_same_fs_raises_on_unexpected_errno(tmp_path, monkeypatch):
    """renameat2 returning a non-zero with an errno outside ENOSYS/EINVAL/ENOTSUP/EEXIST/EXDEV is a
    real failure surfaced as OSError (not silently fallen back)."""
    import ctypes
    def fake_renameat2(*a):
        ctypes.set_errno(errno.EPERM)
        return -1
    monkeypatch.setattr(utils, "_get_renameat2", lambda: fake_renameat2)
    src = tmp_path / "s"; src.write_bytes(b"X")
    with pytest.raises(OSError) as ei:
        utils._rename_no_clobber_same_fs(str(src), str(tmp_path / "d"))
    assert ei.value.errno == errno.EPERM


def test_cross_fs_move_aborts_on_size_mismatch(tmp_path, monkeypatch):
    """The default verify (byte-size equality) catches a short/torn copy and aborts, keeping src."""
    src = tmp_path / "s"; src.write_bytes(b"FULL-CONTENT")
    dest = tmp_path / "d.jpg"
    monkeypatch.setattr(utils.shutil, "copyfile",
                        lambda s, d: open(d, "wb").write(b"short"))   # fewer bytes than src
    with pytest.raises(OSError, match="size mismatch"):
        utils._move_cross_fs_no_clobber(str(src), str(dest))
    assert src.exists() and not dest.exists()
    assert not list(tmp_path.glob(".tmp-xdev-*"))
