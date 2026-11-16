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

"""The editor's half of the rules it answers lives in its front end (web/app.js), tested with Node's own runner in
the *.test.mjs files beside this one; each test here runs one of those files, so the corpus names a test of what the
editor writes (tests are items of the corpus by their pytest marks), as test_zone_asking.py does for its file."""
import os
import shutil
import subprocess

import pytest

_HERE = os.path.dirname(os.path.abspath(__file__))


def _node_test(name):
    """Run one front-end test file; skip where the host has no node (tools/jstest runs them all)."""
    node = shutil.which("node")
    if node is None:
        pytest.skip("no node on this host: tools/jstest runs the editor's front-end tests")
    run = subprocess.run([node, "--test", os.path.join(_HERE, name)], capture_output=True, text=True, timeout=120)
    assert run.returncode == 0, run.stdout + run.stderr


@pytest.mark.spec("RUL-save_only_what_was_shown", "RUL-content_acceptance_is_of_that_content", "RUL-changed_time_asked",
                  "BLD-changed_time_question", "BLD-editor_lists_new_camera_groups", "BLD-editor_marks_several_bodies",
                  test="TST-front_end-the_editor_saves_answers_with_what_they_were_given_for")
def test_the_editor_saves_answers_with_what_they_were_given_for():
    """A save carries the hashes of the records as loaded; a changed content is accepted for that content, a changed
    time answered for the time it holds — kept only where it holds one geotag reads; a camera group classed, or named
    several bodies, in the configuration."""
    _node_test("app_save.test.mjs")


@pytest.mark.spec("RUL-confirmation_holds_for_its_offset", "RUL-confirmation_rests_on_its_tracks",
                  "RUL-trackless_confirmation_holds_while_none",
                  test="TST-front_end-a_drift_confirmation_names_its_offset_and_its_tracks")
def test_a_drift_confirmation_names_its_offset_and_its_tracks():
    """A drift confirmation written in the editor names the offset it confirms and the tracks shown, and holds only
    while both stand."""
    _node_test("app_drift.test.mjs")


@pytest.mark.spec("RUL-phone_kept_as_recorded", "RUL-repeated_time_answered_by_a_reading",
                  "RUL-camera_less_answer_kept", "RUL-acceptance_holds_for_its_proposal",
                  "BLD-unidentified_files_question", "BLD-offset_acceptance",
                  test="TST-front_end-a_phone_a_reading_and_files_naming_no_camera_are_answered_in_the_editor")
def test_a_phone_a_reading_and_files_naming_no_camera_are_answered_in_the_editor():
    """A phone's day kept as it records itself, accepted or set; a time at a daylight-saving change given a reading;
    files naming no camera read in the zone the answer names; an acceptance shown as the offset it accepted."""
    _node_test("app_questions.test.mjs")


@pytest.mark.spec("RUL-clock_change_needs_acceptance", "RUL-clock_change_unsettled_photo_asked",
                  "RUL-contradicted_position_kept_unless_taken", "BLD-neighbour_day_proposal",
                  "BLD-editor_answers_every_question",
                  test="TST-front_end-a_split_day_is_accepted_and_withdrawn_on_its_day")
def test_a_split_day_is_accepted_and_withdrawn_on_its_day():
    """A day split where its clock changed is accepted once, naming its offsets and each unsettled photo's part, on the
    day's cell; held stale with no change proposed, it is withdrawn there."""
    _node_test("app_clock_change.test.mjs")


@pytest.mark.spec("RUL-chosen_offset_not_withheld", "RUL-offset_far_from_evidence_asks", "RUL-country_chosen_once",
                  "RUL-default_zone_proposed_only", "RUL-zone_against_photos_needs_word",
                  test="TST-front_end-the_editor_shows_settled_only_what_geotag_takes")
def test_the_editor_shows_settled_only_what_geotag_takes():
    """An acceptance in a same-day conflict, or of a guess far from all evidence, settles nothing; a country is chosen
    once at the top of its tree; the configured default zone is only proposed; a zone the photos contradict is not in
    effect without the user's word."""
    _node_test("app_resolution.test.mjs")


@pytest.mark.spec("RUL-chosen_offset_not_withheld", "RUL-acceptance_holds_for_its_proposal",
                  "BLD-editor_answers_every_question", "BLD-phone_offset_cell",
                  test="TST-front_end-an_answer_given_for_several_days_is_written_as_each_takes_it")
def test_an_answer_given_for_several_days_is_written_as_each_takes_it():
    """Days answered together share what an answer writes: a day in a same-day conflict, kept as its phone records
    itself, or far from all evidence is a row of its own; a proposal taken in a conflict is the user's own offset; a
    group picked on a phone's kept day ends the keeping; an acceptance names its offset."""
    _node_test("app_offset_buckets.test.mjs")


@pytest.mark.spec("RUL-chosen_position_kept", "BLD-chosen_position",
                  test="TST-front_end-a_position_chosen_for_a_photo_is_kept_and_emptied_places_it_as_before")
def test_a_position_chosen_for_a_photo_is_kept_and_emptied_places_it_as_before():
    """A photo nothing places is offered its folder's fallback, then a position; a placed photo is given one as a
    `chosen_by_user` item; a position the user set, emptied, is shown placed as before."""
    _node_test("app_placement.test.mjs")


@pytest.mark.spec("RUL-zone_table_answered_in_editor", "BLD-editor_answers_zone_table",
                  test="TST-front_end-the_table_of_countries_is_answered_in_the_editor")
def test_the_table_of_countries_is_answered_in_the_editor():
    """The question of downloading the table of countries, while the workspace has it open, is a cell of the editor's
    own, answered yes or no and saved as an edit of its own; unanswered, it holds nothing up."""
    _node_test("app_zone_table.test.mjs")
