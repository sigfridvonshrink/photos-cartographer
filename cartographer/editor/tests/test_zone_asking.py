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

"""Where the editor asks for a timezone lives in its front end (web/app.js), tested with Node's own runner in
app_zone_asking.test.mjs; this runs that file, so the corpus names a test of it (tests are items of the corpus by
their pytest marks)."""
import os
import shutil
import subprocess

import pytest

_HERE = os.path.dirname(os.path.abspath(__file__))


@pytest.mark.spec("RUL-editor_answer_ends_zone_asking", "BLD-editor_zone_asking",
                  test="TST-zone_asking-an_answer_ends_the_asking_below_it")
def test_an_answer_in_the_editor_ends_the_asking_below_it():
    """A zone answered in the editor settles, before any run, every destination it reaches and every folder asking for
    those alone; nothing it does not reach — past a country of several zones, or a zone the photos contradict."""
    node = shutil.which("node")
    if node is None:
        pytest.skip("no node on this host: tools/jstest runs the editor's front-end tests")
    run = subprocess.run([node, "--test", os.path.join(_HERE, "app_zone_asking.test.mjs")],
                         capture_output=True, text=True, timeout=120)
    assert run.returncode == 0, run.stdout + run.stderr
