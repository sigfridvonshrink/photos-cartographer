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

"""A time limit on every test, for both test directories (tests/ and cartographer/editor/tests/), so that a broken lock
or seal check — a run that waits on a lock forever, an editor that goes on to serve — fails its test instead of hanging
the suite. Here at the root, the one conftest every test sits under; the suite's own set-up is in tests/conftest.py.

The limit is far above the slowest test (about 5 s, a `slow` one; the slowest other about 2 s): it only ever fires on a
test that would otherwise never end. SIGALRM interrupts the test's main thread — a blocking `flock`, a `select`, a
`join` alike — and fails it; should that thread be stuck where no signal handler can run, faulthandler dumps every
thread's stack and ends the run a minute later. Where SIGALRM does not exist, or a test runs off the main thread, there
is no limit."""
import faulthandler
import os
import signal
import threading

import pytest

TIME_LIMIT = 120          # seconds, for a test
SLOW_TIME_LIMIT = 600     # for a test marked `slow`, which decodes large real photos
BACKSTOP = 60             # seconds after the limit at which faulthandler ends a run the alarm could not

_stderr_fd = None         # the terminal's stderr, outside pytest's capture, for the backstop's stack dump


def pytest_configure(config):
    global _stderr_fd
    try:
        _stderr_fd = os.dup(2)            # capture is suspended while plugins are configured
    except OSError:
        _stderr_fd = None


def pytest_unconfigure(config):
    global _stderr_fd
    if _stderr_fd is not None:
        os.close(_stderr_fd)
        _stderr_fd = None


@pytest.fixture(autouse=True)
def _time_limit(request):
    if not hasattr(signal, "SIGALRM") or threading.current_thread() is not threading.main_thread():
        yield
        return
    limit = SLOW_TIME_LIMIT if request.node.get_closest_marker("slow") else TIME_LIMIT

    def expired(signum, frame):
        pytest.fail(f"{request.node.nodeid} ran longer than its time limit of {limit} s (conftest.py) — "
                    "a wait that never ends?", pytrace=True)
    previous = signal.signal(signal.SIGALRM, expired)
    faulthandler.dump_traceback_later(limit + BACKSTOP, exit=True,
                                      file=_stderr_fd if _stderr_fd is not None else 2)
    signal.alarm(limit)
    try:
        yield
    finally:
        signal.alarm(0)
        faulthandler.cancel_dump_traceback_later()
        signal.signal(signal.SIGALRM, previous)
