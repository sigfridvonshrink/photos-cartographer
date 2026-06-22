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

"""Phase 4b — whole-run workspace lock + owner identity.

The lock is a plain fcntl.flock with the holder's identity recorded for observability.
main() acquires it once for the whole run; here we test the WorkspaceLock primitive.

photos_1_prep / photos_utils come from conftest.py.
"""
import json
import os
import subprocess
import sys
import time

import photos_1_prep as prep
import photos_utils as utils
import pytest


@pytest.mark.spec("lock-stale-detectable-1")
def test_acquire_records_owner_identity(tmp_path):
    lock = prep.WorkspaceLock(str(tmp_path))
    assert lock.acquire() is True
    try:
        owner = lock.read_owner()
        assert owner is not None
        assert owner["pid"] == os.getpid()
        assert owner["started_at"]
        assert owner["host"]
    finally:
        lock.release()


@pytest.mark.spec("lock-release-on-exit-error-1")
def test_release_frees_the_lock(tmp_path):
    l1 = prep.WorkspaceLock(str(tmp_path))
    assert l1.acquire() is True
    l1.release()
    l2 = prep.WorkspaceLock(str(tmp_path))
    assert l2.acquire() is True   # freed by the release above
    l2.release()


@pytest.mark.spec("lock-mutual-exclusion-1")
def test_cross_process_exclusion_and_owner_report(tmp_path):
    utils.ensure_control_dir(str(tmp_path))
    lock_path = utils.lock_path(str(tmp_path))
    ready = tmp_path / "ready"
    go = tmp_path / "go"

    # A separate process holds a raw flock on the lock file and records its pid.
    code = (
        "import fcntl, os, json, time\n"
        f"fd = os.open({lock_path!r}, os.O_RDWR | os.O_CREAT, 0o644)\n"
        "fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)\n"
        "os.ftruncate(fd, 0)\n"
        "os.write(fd, json.dumps({'pid': os.getpid(), 'started_at': 'x', 'host': 'h'}).encode())\n"
        f"open({str(ready)!r}, 'w').close()\n"
        f"while not os.path.exists({str(go)!r}): time.sleep(0.02)\n"
    )
    holder = subprocess.Popen([sys.executable, "-c", code])
    try:
        for _ in range(500):                 # wait for the holder to take the lock
            if ready.exists():
                break
            time.sleep(0.02)
        assert ready.exists(), "holder process did not start"

        lock = prep.WorkspaceLock(str(tmp_path))
        assert lock.acquire() is False        # held by the other process
        owner = lock.read_owner()
        assert owner and owner["pid"] == holder.pid
    finally:
        go.write_text("")                     # let the holder exit
        holder.wait(timeout=10)

    # Kernel released the holder's flock on exit -> we can take it now.
    lock2 = prep.WorkspaceLock(str(tmp_path))
    assert lock2.acquire() is True
    lock2.release()
