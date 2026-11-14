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

"""`prune-quarantine --older-than-days` takes an age of at least one day, and selects by age only the
quarantine folders whose names give one. From conftest.py.
"""
import os

import pytest

import photos_1_prep as prep
import photos_utils as utils

OLD = "20200101T000000Z-aaaaaa"


def _ws(tmp_path, *names):
    ws = tmp_path / "ws"
    for d in ("0-sources", "1-strays", "2-missing-metadata", "3-redundant-jpgs",
              "4-videos-by-date", "5-photos-by-date", "6-photos-by-dest"):
        (ws / d).mkdir(parents=True)
    (ws / ".photos-ingest").mkdir()
    (ws / ".photos-ingest" / "photos-00-workspace-guard").touch()
    qbase = utils.quarantine_dir(str(ws))
    for n in names:
        os.makedirs(os.path.join(qbase, n))
        with open(os.path.join(qbase, n, "x.jpg"), "wb") as f:
            f.write(b"recoverable")
    return ws, qbase


@pytest.mark.parametrize("days", ["0", "-1"])
@pytest.mark.spec("RUL-prune_age_at_least_one_day", test="TST-prune_age-cli_refuses_an_age_below_one_day")
def test_cli_refuses_an_age_below_one_day(tmp_path, monkeypatch, capsys, days):
    """`--older-than-days 0` would select every dated folder — the whole quarantine — under the look of a
    selector: refused, naming the option, and nothing deleted."""
    ws, qbase = _ws(tmp_path, OLD, "20991231T000000Z-bbbbbb")
    monkeypatch.chdir(ws)
    with pytest.raises(SystemExit) as e:
        prep.main(["prune-quarantine", "--older-than-days", days, "--yes"])
    assert e.value.code == 2
    assert "--older-than-days" in capsys.readouterr().err
    assert sorted(os.listdir(qbase)) == [OLD, "20991231T000000Z-bbbbbb"]


@pytest.mark.spec("RUL-prune_age_at_least_one_day", test="TST-prune_age-function_refuses_an_age_below_one_day")
def test_function_refuses_an_age_below_one_day(tmp_path):
    """The console reaches the prune without the command line's parsing: it refuses there too."""
    ws, qbase = _ws(tmp_path, OLD)
    with pytest.raises(RuntimeError, match="--older-than-days"):
        prep.prune_quarantine(str(ws), older_than_days=0, do_delete=True)
    assert os.listdir(qbase) == [OLD]


@pytest.mark.spec("RUL-prune_age_at_least_one_day", test="TST-prune_age-one_day_is_accepted")
def test_one_day_is_accepted(tmp_path, monkeypatch):
    ws, qbase = _ws(tmp_path, OLD, "20991231T000000Z-bbbbbb")
    monkeypatch.chdir(ws)
    prep.main(["prune-quarantine", "--older-than-days", "1", "--yes"])
    assert os.listdir(qbase) == ["20991231T000000Z-bbbbbb"]


@pytest.mark.spec("RUL-prune_age_at_least_one_day", test="TST-prune_age-folder_without_an_age_is_listed_not_selected")
def test_folder_without_an_age_is_listed_not_selected(tmp_path, capsys):
    """A quarantine folder whose name gives no age is never selected by age, and is listed as such."""
    ws, qbase = _ws(tmp_path, OLD, "kept-by-hand")
    prep.prune_quarantine(str(ws), older_than_days=30, do_delete=True)
    assert os.listdir(qbase) == ["kept-by-hand"]
    out = capsys.readouterr().out
    line = next((ln for ln in out.splitlines() if "kept-by-hand" in ln), "")
    assert "age" in line and "Removing" not in line, out
