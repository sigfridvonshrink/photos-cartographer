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

"""Each plan has one fixed place: no command is told where a plan is, and an unchanged re-plan
writes nothing (shared contract §4)."""
import argparse
import json
import os

import pytest

import photos_utils as utils
from cartographer import cli


def _arguments(parser, path=()):
    """Every (command, argument) of the CLI, walking the phase and subcommand parsers."""
    out = set()
    for action in parser._actions:
        if isinstance(action, argparse._SubParsersAction):
            for name, sub in action.choices.items():
                out |= _arguments(sub, path + (name,))
        else:
            for opt in action.option_strings or [action.dest]:
                out.add((" ".join(path), opt))
    return out


# The whole argument surface. None of these says where a plan is put or found: `--plan-id` selects
# quarantine folders to prune, and init-library's `path` is the library to bless. A new argument
# fails this test until it is added here — after checking it does not name a plan's place.
_KNOWN = {
    ("", "--version"),
    ("prep", "--jobs"), ("prep", "-j"), ("geotag", "--jobs"), ("geotag", "-j"),
    ("merge", "--jobs"), ("merge", "-j"),
    ("prep prune-quarantine", "--plan-id"), ("prep prune-quarantine", "--older-than-days"),
    ("prep prune-quarantine", "--all"), ("prep prune-quarantine", "--yes"),
    ("merge init-library", "path"),
    ("edit", "--demo"), ("edit", "--port"), ("edit", "--host"),
    ("console", "--port"), ("console", "--host"),
}


@pytest.mark.spec("RUL-no_plan_location_option", test="TST-plan_place-no_plan_location_option")
def test_no_command_takes_a_plan_location():
    found = {a for a in _arguments(cli.build_parser()) if a[1] not in ("-h", "--help")}
    assert found == _KNOWN


@pytest.mark.spec("RUL-unchanged_replan_writes_nothing", test="TST-plan_place-unchanged_replan_writes_nothing")
def test_identical_rewrite_writes_nothing_and_backs_up_nothing(tmp_path):
    path = tmp_path / "photos-21-time-decisions.json"
    obj = {"status": "complete", "destinations": {"a": 1}}
    sha, backup = utils.write_versioned_json(str(path), obj)
    assert backup is None
    before = os.stat(path)
    sha2, backup2 = utils.write_versioned_json(str(path), json.loads(path.read_text()))
    after = os.stat(path)
    assert backup2 is None and sha2 == sha
    assert (after.st_ino, after.st_mtime_ns) == (before.st_ino, before.st_mtime_ns)   # not rewritten
    assert sorted(os.listdir(tmp_path)) == [path.name]                               # nothing set aside
    _, backup3 = utils.write_versioned_json(str(path), dict(obj, status="requires_user_input"))
    assert backup3 and os.path.exists(backup3)                                       # a change is set aside
