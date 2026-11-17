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

"""The workspace lock spans the whole run: taken before the workspace is first read, and held until the run ends.

Each command is run as the command line runs it, in-process, and the lock is probed — from a file descriptor of its
own, as another run would find it — at the moments the run reads the workspace and at every report it makes."""
import os

import pytest

import photos_1_prep as prep
import photos_2_geotag as geotag
import photos_3_merge as merge
import photos_utils as utils
from cartographer import reporting
from test_cli import _EVERY_COMMAND, _ws as _cli_ws


def _workspace(tmp_path):
    """A workspace with work for every command: a dump to plan, a quarantine to prune, a library to bless."""
    lib = tmp_path / "lib"; lib.mkdir()
    cfg = {k: v for k, v in utils.CONFIG.items() if k != "jobs"}
    cfg["zfs"] = dict(cfg["zfs"], enabled=False)                     # never shell out to `zfs snapshot`
    cfg["merge"] = dict(cfg.get("merge") or {}); cfg["merge"]["library_root"] = str(lib)
    ws = _cli_ws(tmp_path, config=cfg)
    (ws / "0-sources" / "a.jpg").write_bytes(b"a dump to plan")
    qd = ws / ".photos-ingest-quarantine" / "20260101T000000Z-abc123"
    qd.mkdir(parents=True); (qd / "dup.jpg").write_bytes(b"recoverable")
    return ws, lib


def _held(ws):
    return utils.WorkspaceLock(str(ws), create=False).held_owner() is not None


def _run(monkeypatch, ws, lib, command):
    import cartographer.cli as cli
    monkeypatch.chdir(str(ws))
    try:
        cli.main([str(lib) if a == "<library>" else a for a in command])
    except SystemExit:
        pass


class _ProbeSink(reporting.Sink):
    """Every report the run makes, with whether the workspace lock was held as it was made."""

    def __init__(self, ws, timeline):
        self.ws, self.timeline = ws, timeline

    def handle(self, event):
        self.timeline.append(("report", getattr(event, "msg", type(event).__name__), _held(self.ws)))


def _watch_the_lock(monkeypatch, timeline):
    """Record in `timeline` each taking and each letting go of the workspace lock."""
    real_acquire, real_release = utils.WorkspaceLock.acquire, utils.WorkspaceLock.release

    def acquire(self, *a, **k):
        ok = real_acquire(self, *a, **k)
        timeline.append(("acquire", ok))
        return ok

    def release(self, *a, **k):
        timeline.append(("release",))
        return real_release(self, *a, **k)
    monkeypatch.setattr(utils.WorkspaceLock, "acquire", acquire)
    monkeypatch.setattr(utils.WorkspaceLock, "release", release)


def _probe_steps(monkeypatch, ws, timeline, steps):
    """Wrap each (owner, name) of `steps` so that a call records whether the workspace lock was held at it."""
    for owner, name in steps:
        real = getattr(owner, name)

        def probe(*a, _real=real, _name=name, **k):
            timeline.append(("step", _name, _held(ws)))
            return _real(*a, **k)
        monkeypatch.setattr(owner, name, probe)


# The first reads of each phase's run: the shape of the workspace and the check against the state its last execution
# left — and the walk over its folders for their filesystems, made by every command.
_FIRST_READS = [(prep, "_shape_blockers"), (prep, "check_workspace"),
                (geotag, "top_level_links"), (geotag, "check_workspace"),
                (merge.MergeWorkflow, "shape_passes"), (merge, "check_workspace"),
                (utils, "workspace_volume_error"), (geotag, "workspace_volume_error"),
                (merge, "workspace_volume_error")]


@pytest.mark.parametrize("command", _EVERY_COMMAND[:-1],
                         ids=[" ".join(c[:2]) + (" <path>" if "<library>" in c else "") for c in _EVERY_COMMAND[:-1]])
@pytest.mark.spec("RUL-lock_through_the_run", test="TST-lock_spans_the_run-the_lock_is_held_until_the_run_ends")
def test_the_lock_is_held_until_the_run_ends(tmp_path, monkeypatch, command):
    """Every command of every phase holds the workspace lock from the moment it takes it until the run ends: each
    report the run makes after taking it, through the last before letting it go, and each read of the workspace
    along the way, is made while another run would find the workspace locked."""
    ws, lib = _workspace(tmp_path)
    if command[0] == "prep" and command[1] in ("dry-run", "execute"):
        _run(monkeypatch, ws, lib, ("prep", "plan"))                 # the saved plan they carry out
    timeline = []
    _watch_the_lock(monkeypatch, timeline)
    _probe_steps(monkeypatch, ws, timeline, _FIRST_READS)
    with reporting.use_reporter(reporting.Reporter([_ProbeSink(ws, timeline)])):
        _run(monkeypatch, ws, lib, command)

    taken = [i for i, e in enumerate(timeline) if e == ("acquire", True)]
    assert len(taken) == 1, timeline
    last_release = max(i for i, e in enumerate(timeline) if e == ("release",))
    during = [e for e in timeline[taken[0] + 1:last_release] if e[0] in ("report", "step")]
    assert len(during) >= 2, timeline                                 # the run did report and read under it
    assert all(held for _kind, _what, held in during), [e for e in during if not e[2]]
    assert not _held(ws)                                              # and let it go when it ended


@pytest.mark.parametrize("command", [c for c in _EVERY_COMMAND if c[1] in ("plan", "dry-run", "execute", "finalize")],
                         ids=lambda c: " ".join(c))
@pytest.mark.spec("RUL-lock_before_reading", test="TST-lock_spans_the_run-the_lock_is_taken_before_the_workspace_is_read")
def test_the_lock_is_taken_before_the_workspace_is_read(tmp_path, monkeypatch, command):
    """A run takes the workspace lock before it reads the workspace's content: the check of its shape and the check
    of it against the state its last execution left — the first reads of prep, geotag and merge alike — are made
    with the lock already held."""
    ws, lib = _workspace(tmp_path)
    if command[0] == "prep" and command[1] in ("dry-run", "execute"):
        _run(monkeypatch, ws, lib, ("prep", "plan"))
    timeline = []
    _probe_steps(monkeypatch, ws, timeline, _FIRST_READS)
    _run(monkeypatch, ws, lib, command)
    first_reads = {"_shape_blockers", "check_workspace", "top_level_links", "shape_passes"}
    reads = [e for e in timeline if e[1] in first_reads]
    assert any(e[1] == "check_workspace" for e in reads), timeline   # the run did read the workspace
    assert all(held for _step, _name, held in reads), reads
