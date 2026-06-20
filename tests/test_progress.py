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

"""ProgressCoordinator.set_detail — the per-item label (e.g. the destination being calibrated) that
geotag shows on the progress line so a heavy destination is visible while it's worked on. From
conftest.py (photos_utils loaded once into sys.modules).

ProgressCoordinator is now a back-compat adapter over the reporting seam (cartographer/reporting.py):
its methods emit events; the TtySink renders. So these tests drive a Reporter with a visible TtySink
(or a CaptureSink) installed via use_reporter, rather than poking the coordinator's old internals."""
import io

import photos_utils as utils
from cartographer.reporting import (
    Reporter, TtySink, CaptureSink, use_reporter, FINISH,
)


class _NonTtyStream(io.StringIO):
    def isatty(self):
        return False


def test_set_detail_appears_on_line_and_forces_render():
    stream = _NonTtyStream()
    with use_reporter(Reporter([TtySink(stream=stream, quiet=False)])):
        c = utils.ProgressCoordinator()
        c.start_phase("calibrating clock offsets", 3)
        c.set_detail("Japan/Kyoto")                    # forces an immediate render
    out = stream.getvalue()
    assert "calibrating clock offsets" in out and "Japan/Kyoto" in out


def test_start_phase_resets_detail():
    stream = _NonTtyStream()
    with use_reporter(Reporter([TtySink(stream=stream, quiet=False)])):
        c = utils.ProgressCoordinator()
        c.start_phase("calibrating clock offsets", 2)
        c.set_detail("Japan/Kyoto")
        stream.seek(0); stream.truncate(0)             # discard the first phase's output
        c.start_phase("deciding GPS placement", 5)     # must clear the prior detail
        c.set_detail("")
    out = stream.getvalue()
    assert "deciding GPS placement" in out and "Japan/Kyoto" not in out


def test_detail_silent_when_quiet():
    stream = _NonTtyStream()
    with use_reporter(Reporter([TtySink(stream=stream, quiet=True)])):  # piped/cron/tests: no noise
        c = utils.ProgressCoordinator()
        c.start_phase("calibrating clock offsets", 1)
        c.set_detail("Japan/Kyoto")
        c.increment_completed(1)
    assert stream.getvalue() == ""


def test_prep_scrolling_output_routes_through_injected_reporter(tmp_path):
    """Prep's scrolling messages now go through the active Reporter — so a caller (tests, the future
    web console) can inject a sink and capture them, with stdout/stderr routing preserved."""
    import photos_1_prep as prep
    cap = CaptureSink()
    with use_reporter(Reporter([cap])):
        prep.prune_quarantine(str(tmp_path))           # no quarantine dir -> one stdout line
    logs = cap.logs()
    assert any("nothing to prune" in e.msg for e in logs)
    assert all(e.stream == "stdout" for e in logs)     # user-facing prune output is a stdout deliverable


def test_gpx_build_reports_per_file_progress(tmp_path):
    import photos_2_geotag as cal
    d = tmp_path / "gpx"; d.mkdir()
    for i in range(3):
        (d / f"track{i}.gpx").write_text("")           # extension is enough to be counted
    cap = CaptureSink()
    with use_reporter(Reporter([cap])):
        c = utils.ProgressCoordinator()
        cal.GPXIndex(str(d)).build(c)
    prog = cap.progress()
    assert prog[0].total == 3                           # phase started with the right total
    assert prog[-1].state == FINISH and prog[-1].cur == 3   # advanced once per file, then finished
