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


# --- cross-filesystem move fallback (BLD-cross_fs_temp) -------------------

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


@pytest.mark.spec("RUL-cross_fs_all_or_nothing", "BLD-cross_fs_temp", test="TST-fallbacks-cross_fs_move_refuses_a_copy_differing_in_any_byte")
def test_cross_fs_move_refuses_a_copy_differing_in_any_byte(tmp_path, monkeypatch):
    """A copy of the right size but one byte off — damage a fingerprint of the decoded image would not
    see, in the metadata geotag wrote, say — is refused: the source kept, no destination, no temp."""
    src = tmp_path / "s"; src.write_bytes(b"PIXELS+GPS=48.85")
    dest = tmp_path / "x.jpg"
    monkeypatch.setattr(utils.shutil, "copyfile",
                        lambda s, d: open(d, "wb").write(b"PIXELS+GPS=48.86"))
    with pytest.raises(OSError, match="differs from its source"):
        utils._move_cross_fs_no_clobber(str(src), str(dest))
    assert src.exists() and not dest.exists()
    assert not list(tmp_path.glob(".tmp-xdev-*"))


@pytest.mark.spec("RUL-cross_fs_all_or_nothing", "BLD-cross_fs_temp", test="TST-fallbacks-cross_fs_move_makes_the_rename_durable_before_removing_the_source")
def test_cross_fs_move_makes_the_rename_durable_before_removing_the_source(tmp_path, monkeypatch):
    """The source is removed only after the destination folder — holding the rename into place — is
    flushed to disk: a power cut cannot keep the removal and lose the rename."""
    sub = tmp_path / "lib"; sub.mkdir()
    src = tmp_path / "s"; src.write_bytes(b"PHOTO")
    dest = sub / "x.jpg"
    events = []
    real_fsync, real_unlink = os.fsync, os.unlink
    def fsync(fd):
        events.append(("fsync", os.readlink(f"/proc/self/fd/{fd}")))
        return real_fsync(fd)
    def unlink(p, *a, **k):
        events.append(("unlink", str(p)))
        return real_unlink(p, *a, **k)
    monkeypatch.setattr(utils.os, "fsync", fsync)
    monkeypatch.setattr(utils.os, "unlink", unlink)
    utils._move_cross_fs_no_clobber(str(src), str(dest))
    assert ("fsync", str(sub)) in events
    assert events.index(("fsync", str(sub))) < events.index(("unlink", str(src)))


PHOTO = b"PHOTO-BYTES-" * 64


def _held_whole(*names):
    """The photo is whole under at least one of `names` and under no name partly."""
    held = [p for p in names if os.path.exists(p)]
    assert held, "the photo is under neither name"
    for p in held:
        assert open(p, "rb").read() == PHOTO, f"{p} holds part of the photo"


def _stopping(stopped, names, stop_with):
    """A stand-in for one step of a move: it checks the photo is whole as the move stands when stopped there —
    what a kill would leave — and stops it there, by an interrupt or by the step failing."""
    def stop(*a, **k):
        stopped.append(True)
        _held_whole(*names)
        raise stop_with()
    return stop


_STOPS = {"interrupted": KeyboardInterrupt, "failing": lambda: OSError(errno.EIO, "Input/output error")}


@pytest.mark.spec("RUL-split_move_never_lost", "RUL-cross_fs_all_or_nothing",
                  test="TST-fallbacks-a_cross_fs_move_stopped_at_any_step_loses_nothing")
@pytest.mark.parametrize("stop_by", sorted(_STOPS))
@pytest.mark.parametrize("step", ["copy", "halfway_through_the_copy", "copy_times", "compare", "sync",
                                  "rename", "sync_folder", "remove_source"])
def test_a_cross_fs_move_stopped_at_any_step_loses_nothing(tmp_path, monkeypatch, step, stop_by):
    """Merge's move into a library on another filesystem — copy, check, sync, rename into place, sync the folder,
    remove the source — interrupted, or failing, at any of its steps or halfway through the copy, leaves the photo
    whole under its old name, its new name or both: at the moment it stops, and once the stop has unwound. Until the
    rename into place, nothing at all is under the new name — the copy is made under a temporary one."""
    lib = tmp_path / "lib"; lib.mkdir()
    src = tmp_path / "s.jpg"; src.write_bytes(PHOTO)
    dest = lib / "x.jpg"
    stopped, dest_at_stop = [], []
    stop_here = _stopping(stopped, (str(src), str(dest)), _STOPS[stop_by])

    def stop(*a, **k):
        dest_at_stop.append(os.path.lexists(dest))
        return stop_here(*a, **k)
    real_unlink = os.unlink

    def half_copy(s, d, *a, **k):
        with open(d, "wb") as f:
            f.write(PHOTO[:len(PHOTO) // 2])
        stop()

    def unlink(p, *a, **k):
        return stop() if str(p) == str(src) else real_unlink(p, *a, **k)
    seam = {"copy": (utils.shutil, "copyfile", stop), "halfway_through_the_copy": (utils.shutil, "copyfile", half_copy),
            "copy_times": (utils.shutil, "copystat", stop), "compare": (utils, "_same_bytes", stop),
            "sync": (utils.os, "fsync", stop), "rename": (utils, "_rename_no_clobber_same_fs", stop),
            "sync_folder": (utils, "_fsync_dir", stop), "remove_source": (utils.os, "unlink", unlink)}[step]
    with monkeypatch.context() as m:
        m.setattr(*seam)
        try:
            utils._move_cross_fs_no_clobber(str(src), str(dest))
        except (KeyboardInterrupt, OSError):
            pass                                                    # (copying the times may fail, and is let go)
    assert stopped == [True]
    _held_whole(str(src), str(dest))
    if step not in ("sync_folder", "remove_source"):                    # stopped before the rename into place
        assert dest_at_stop == [False]


@pytest.mark.spec("RUL-split_move_never_lost",
                  test="TST-fallbacks-a_hard_link_move_stopped_at_either_step_loses_nothing")
@pytest.mark.parametrize("stop_by", sorted(_STOPS))
@pytest.mark.parametrize("step", ["link", "unlink"])
def test_a_hard_link_move_stopped_at_either_step_loses_nothing(tmp_path, monkeypatch, step, stop_by):
    """Where the filesystem has no rename that refuses a taken name, a move is a hard link under the new name and
    then the old name's removal: interrupted, or failing, at either, it leaves the photo whole under its old name,
    or both."""
    monkeypatch.setattr(utils, "_get_renameat2", lambda: False)
    src = tmp_path / "s.jpg"; src.write_bytes(PHOTO)
    dest = tmp_path / "sub" / "x.jpg"; dest.parent.mkdir()
    stopped = []
    with monkeypatch.context() as m:
        m.setattr(utils.os, step, _stopping(stopped, (str(src), str(dest)), _STOPS[stop_by]))
        with pytest.raises((KeyboardInterrupt, OSError)):
            utils._move_no_clobber(str(src), str(dest))
    assert stopped == [True]
    _held_whole(str(src), str(dest))


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
    utils._move_no_clobber(str(src), str(dest), cross_fs=True)
    assert dest.read_bytes() == b"XDEV" and not src.exists() and seen["n"] == 2


@pytest.mark.spec("RUL-workspace_moves_one_filesystem", test="TST-fallbacks-move_no_clobber_refuses_exdev_unless_cross_fs")
def test_move_no_clobber_refuses_exdev_unless_cross_fs(tmp_path, monkeypatch):
    """Only merge crosses filesystems: for prep and geotag (no cross_fs) a move that would cross one is
    raised as a failure, never turned into a copy — the source stays and no temp is left."""
    seen = _exdev_seam(monkeypatch)
    src = tmp_path / "s"; src.write_bytes(b"XDEV")
    dest = tmp_path / "d.jpg"
    with pytest.raises(OSError) as ei:
        utils._move_no_clobber(str(src), str(dest))
    assert ei.value.errno == errno.EXDEV and seen["n"] == 1
    assert src.read_bytes() == b"XDEV" and not dest.exists()
    assert not list(tmp_path.glob(".tmp-xdev-*"))


def test_move_no_clobber_cross_fs_preserves_on_existing_dest(tmp_path, monkeypatch):
    _exdev_seam(monkeypatch)
    src = tmp_path / "s"; src.write_bytes(b"NEW")
    dest = tmp_path / "d.jpg"; dest.write_bytes(b"KEEP")
    with pytest.raises(FileExistsError):
        utils._move_no_clobber(str(src), str(dest), cross_fs=True)
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
    """A short/torn copy is caught and aborts, keeping src."""
    src = tmp_path / "s"; src.write_bytes(b"FULL-CONTENT")
    dest = tmp_path / "d.jpg"
    monkeypatch.setattr(utils.shutil, "copyfile",
                        lambda s, d: open(d, "wb").write(b"short"))   # fewer bytes than src
    with pytest.raises(OSError, match="differs from its source"):
        utils._move_cross_fs_no_clobber(str(src), str(dest))
    assert src.exists() and not dest.exists()
    assert not list(tmp_path.glob(".tmp-xdev-*"))
