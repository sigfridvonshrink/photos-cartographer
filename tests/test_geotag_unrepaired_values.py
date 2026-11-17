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

"""An invalid value is used as written or not at all (RUL-invalid_value_never_repaired): a timezone that differs from
a real one only by its case or a stray space is not quietly taken for that zone — it stops geotag, located, and the
decision record keeps exactly what was written."""
import pytest

import photos_2_geotag as cal
from test_geotag_time_decisions import CAM, _edit, _hfile, _run, _ws

DEST = "6-photos-by-dest/Brussels"


@pytest.mark.spec("RUL-invalid_value_never_repaired", "RUL-invalid_value_located", "RUL-invalid_decision_kept",
                  test="TST-geotag_unrepaired_values-a_nearly_right_timezone_is_not_repaired")
@pytest.mark.parametrize("written", ["europe/brussels", " Europe/Brussels", "Europe/Brussels "])
def test_a_nearly_right_timezone_is_not_repaired(tmp_path, monkeypatch, capsys, written):
    ws = _ws(tmp_path, files=[_hfile(f"{DEST}/a.jpg")], device_groups={"fixed_clock_cameras": [CAM], "phones": []})
    _run(monkeypatch, ws)
    _edit(ws, lambda a: a["destinations"][DEST]["destination_timezone"]["user_decision"]
          .__setitem__("manual_iana_timezone", written))
    record = ws / ".photos-ingest" / cal.TIME_DECISIONS_ARTIFACT
    before = record.read_bytes()
    capsys.readouterr()

    assert _run(monkeypatch, ws) == 2                                     # stopped, not run on a repaired zone
    err = capsys.readouterr().err
    assert DEST in err and "manual_iana_timezone" in err and repr(written) in err, err     # located, as written
    assert record.read_bytes() == before                                  # the record keeps what was written
