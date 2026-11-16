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

"""Tests for the decision-editor server (`cartographer/editor/server.py`).

Covers the request-independent helpers (port auto-bump, machine-IP detection, the single-editor lock,
JSON read/write, the user_decision-only edit apply, and save round-trip) plus a few end-to-end HTTP
checks of the GET/POST routes. Loaded via tests/conftest.py's SourceFileLoader, like the pipeline
scripts.
"""
import copy
import json
import os
import shutil
import socket
import subprocess
import threading
import urllib.error
import urllib.request
from contextlib import contextmanager

import pytest

import decision_editor_serve as serve

# Demo fixtures are package data now; in a checkout they're a real dir beside the server module.
EXAMPLES = os.path.join(os.path.dirname(serve.__file__), "examples")
HAVE_MAGICK = bool(shutil.which("magick"))


def _make_jpeg(path):
    subprocess.run(["magick", "-size", "64x48", "xc:navy", str(path)], check=True)


# --------------------------------------------------------------------------- helpers

def _workspace_with_fixtures(tmp_path):
    """A workspace dir whose .photos-ingest/ holds the two requires-input example artifacts."""
    cd = tmp_path / serve.CONTROL
    cd.mkdir(parents=True)
    for src, dst in (("photos-21-time-decisions.requires-input.json", serve.TIME_NAME),
                     ("photos-23-gps-decisions.requires-input.json", serve.GPS_NAME)):
        (cd / dst).write_text((open(os.path.join(EXAMPLES, src))).read())
    return str(tmp_path)


@contextmanager
def _running(workspace):
    """Run the real Handler in a background thread on an OS-assigned port; yield its base URL."""
    old = serve.Handler.workspace
    serve.Handler.workspace = workspace
    httpd = serve._bind("127.0.0.1", 0, serve.Handler)
    httpd.daemon_threads = True
    t = threading.Thread(target=httpd.serve_forever, daemon=True)
    t.start()
    try:
        yield f"http://127.0.0.1:{httpd.server_address[1]}"
    finally:
        httpd.shutdown()
        httpd.server_close()
        serve.Handler.workspace = old


def _get(url):
    try:
        with urllib.request.urlopen(url) as r:
            return r.status, r.read(), r.headers.get("Content-Type", "")
    except urllib.error.HTTPError as e:
        return e.code, e.read(), e.headers.get("Content-Type", "")


def _post_json(url, obj):
    req = urllib.request.Request(url, data=json.dumps(obj).encode(), method="POST",
                                 headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req) as r:
            return r.status, json.loads(r.read())
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read())


# --------------------------------------------------------------------------- _bind (port auto-bump)

def test_bind_uses_a_free_port():
    srv = serve._bind("127.0.0.1", 0, serve.Handler)  # 0 → OS assigns a free port
    try:
        assert srv.server_address[1] != 0
    finally:
        srv.server_close()


def test_bind_bumps_past_a_busy_port():
    held = serve._bind("127.0.0.1", 0, serve.Handler)
    busy = held.server_address[1]
    try:
        moved = serve._bind("127.0.0.1", busy, serve.Handler)
        try:
            assert moved.server_address[1] > busy  # busy port is never an error — it moves up
        finally:
            moved.server_close()
    finally:
        held.server_close()


def test_bind_reraises_non_addrinuse():
    # A non-local address fails to bind with something other than EADDRINUSE; _bind must not swallow it.
    with pytest.raises(OSError):
        serve._bind("203.0.113.1", 0, serve.Handler)  # TEST-NET-3: not an address on this machine


# --------------------------------------------------------------------------- _machine_ip

def test_machine_ip_is_a_valid_ipv4():
    ip = serve._machine_ip()
    assert isinstance(ip, str) and ip
    socket.inet_aton(ip)  # raises if not a dotted-quad IPv4


# --------------------------------------------------------------------------- editor lock

def test_lock_acquire_writes_owner_record(tmp_path):
    lock, owner = serve._acquire_editor_lock(str(tmp_path))
    try:
        assert owner is None and lock is not None
        path = tmp_path / serve.CONTROL / serve.EDITOR_LOCK
        assert path.is_file()
        rec = json.loads(path.read_text())
        assert rec["pid"] == os.getpid()
        assert rec["host"] and rec["started_at"]
    finally:
        lock.close()


def test_lock_creates_control_dir(tmp_path):
    assert not (tmp_path / serve.CONTROL).exists()
    lock, owner = serve._acquire_editor_lock(str(tmp_path))
    try:
        assert lock is not None
        assert (tmp_path / serve.CONTROL).is_dir()
    finally:
        lock.close()


@pytest.mark.spec("RUL-one_editor_at_a_time", "BLD-editor_session_lock", test="TST-serve-lock_blocks_second_editor")
def test_lock_blocks_second_editor(tmp_path):
    first, _ = serve._acquire_editor_lock(str(tmp_path))
    try:
        second, owner = serve._acquire_editor_lock(str(tmp_path))
        assert second is None  # refused while another editor holds it
        assert owner["pid"] == os.getpid()
    finally:
        first.close()


def test_lock_released_after_close(tmp_path):
    first, _ = serve._acquire_editor_lock(str(tmp_path))
    first.close()  # closing the file releases the flock
    again, owner = serve._acquire_editor_lock(str(tmp_path))
    try:
        assert again is not None and owner is None
    finally:
        again.close()


# --------------------------------------------------------------------------- _read_json / _write_json

def test_read_json_missing_returns_none(tmp_path):
    assert serve._read_json(str(tmp_path / "nope.json")) is None


def test_read_json_bad_returns_error(tmp_path):
    p = tmp_path / "bad.json"
    p.write_text("{not json")
    out = serve._read_json(str(p))
    assert isinstance(out, dict) and "_error" in out


def test_write_json_is_deterministic_atomic_and_round_trips(tmp_path):
    p = tmp_path / "out.json"
    serve._write_json(str(p), {"b": 1, "a": {"y": 2, "x": 1}})
    text = p.read_text()
    assert json.loads(text) == {"b": 1, "a": {"y": 2, "x": 1}}
    assert text == json.dumps({"b": 1, "a": {"y": 2, "x": 1}}, indent=2, sort_keys=True)
    assert not (tmp_path / "out.json.tmp").exists()  # temp file renamed away


# --------------------------------------------------------------------------- _load_artifacts

def _loaded(ws):
    """The hashes of the decision records as the editor loads them, which a save carries back."""
    return serve._load_artifacts(ws)["hashes"]


def test_load_artifacts_demo_mode():
    art = serve._load_artifacts(None)
    assert art["demo"] is True and art["workspace"] is None
    assert "destinations" in art["time"] and "destinations" in art["gps"]


@pytest.mark.spec("RUL-checked_timezones", test="TST-serve-the_editor_checks_zones_by_the_host_s_list")
def test_the_editor_checks_zones_by_the_host_s_list(tmp_path):
    """The editor checks a timezone against the zones geotag's plan accepts on this host, sent with the decisions —
    never the browser's own list — so a zone it lets be saved is one the plan takes. The host's own names
    (`localtime`, `Factory`, `posixrules`) are no place's zone, and are not among them."""
    import zoneinfo
    for art in (serve._load_artifacts(None), serve._load_artifacts(_workspace_with_fixtures(tmp_path))):
        zones = art["zones"]
        assert zones == sorted(zones) and {"UTC", "Europe/Brussels", "Asia/Tokyo"} <= set(zones)
        assert not {"localtime", "Factory", "posixrules"} & set(zones)
        assert all(serve.photos_utils.valid_iana_timezone(z) for z in zones)
        assert set(zones) == {z for z in zoneinfo.available_timezones() if serve.photos_utils.valid_iana_timezone(z)}
    with _running(None) as base:
        _status, body, _ctype = _get(base + "/api/artifacts")
        assert json.loads(body)["zones"] == serve._host_zones()


def test_load_artifacts_workspace(tmp_path):
    ws = _workspace_with_fixtures(tmp_path)
    art = serve._load_artifacts(ws)
    assert art["demo"] is False
    assert art["workspace"] == os.path.abspath(ws)
    assert "destinations" in art["time"] and "destinations" in art["gps"]


# --------------------------------------------------------------------------- _apply_edits

def _time_art():
    return json.load(open(os.path.join(EXAMPLES, "photos-21-time-decisions.requires-input.json")))


def _gps_art():
    return json.load(open(os.path.join(EXAMPLES, "photos-23-gps-decisions.requires-input.json")))


def test_apply_edits_timezone_touches_only_user_decision():
    art = _time_art()
    dest = "6-photos-by-dest/Japan"
    cell = art["destinations"][dest]["destination_timezone"]
    proposal_before = copy.deepcopy(cell.get("proposal"))
    n = serve._apply_edits(art, [{"dest": dest, "kind": "timezone",
                                  "user_decision": {"manual_iana_timezone": "Asia/Tokyo"}}])
    assert n == 1
    assert cell["user_decision"]["manual_iana_timezone"] == "Asia/Tokyo"
    assert cell.get("proposal") == proposal_before  # everything but user_decision is untouched


def test_apply_edits_offset_by_group_key():
    art = _time_art()
    dest, key = "6-photos-by-dest/Japan", "SONY|ILCE-6400|A"
    n = serve._apply_edits(art, [{"dest": dest, "kind": "offset", "key": key,
                                  "user_decision": {"accept_proposal": False,
                                                    "manual_offset_seconds": 42}}])
    assert n == 1
    cell = art["destinations"][dest]["camera_group_time_decisions"][key]
    assert cell["user_decision"]["manual_offset_seconds"] == 42


def test_apply_edits_fallback_and_review():
    art = _gps_art()
    dest = "6-photos-by-dest/Japan"
    review_path = "6-photos-by-dest/Japan/blocked-a.arw"
    n = serve._apply_edits(art, [
        {"dest": dest, "kind": "fallback",
         "user_decision": {"fallback_lat": 35.0, "fallback_lon": 139.0}},
        {"dest": dest, "kind": "review", "path": review_path,
         "user_decision": {"manual_lat": 35.6, "manual_lon": 139.7}},
    ])
    assert n == 2
    d = art["destinations"][dest]
    assert d["folder_fallback"]["user_decision"]["fallback_lat"] == 35.0
    item = next(r for r in d["gps_decisions"]["review_items"] if r["relative_path"] == review_path)
    assert item["user_decision"]["manual_lat"] == 35.6


@pytest.mark.spec("BLD-chosen_position", "BLD-editor_answers_every_question", "RUL-save_only_what_was_shown",
                  test="TST-serve-a_position_chosen_for_a_placed_photo_is_saved_as_its_entry")
def test_a_position_chosen_for_a_placed_photo_is_saved_as_its_entry(tmp_path):
    """A position set in the editor for a photo the tracks place is written as the entry a hand would write — the
    photo's path, `chosen_by_user`, the position — into its destination's review items; saved again, that entry is
    changed, never doubled. A photo photos-23 does not list as placed is refused, nothing written."""
    ws = _workspace_with_fixtures(tmp_path)
    dest, rel = "6-photos-by-dest/Japan", "6-photos-by-dest/Japan/interp.arw"
    gps = os.path.join(ws, serve.CONTROL, serve.GPS_NAME)
    placed = json.load(open(gps))["destinations"][dest]["gps_decisions"]["placed_photos"]
    assert any(p["relative_path"] == rel and p["placed_by"] == "tracks" for p in placed)
    for lat in (35.1, 35.2):
        res = serve._save(ws, {"gps": [{"dest": dest, "kind": "chosen", "path": rel,
                                        "user_decision": {"manual_lat": lat, "manual_lon": 135.7}}],
                               "hashes": _loaded(ws)})
        assert res["ok"] is True and res["written"] == [serve.GPS_NAME]
        d = json.load(open(gps))["destinations"][dest]["gps_decisions"]
        assert [r for r in d["review_items"] if r["relative_path"] == rel] == [
            {"relative_path": rel, "content_fingerprint": f"fp-{rel}", "reason": "chosen_by_user",
             "user_decision": {"manual_lat": lat, "manual_lon": 135.7}, "requires_user_input": False,
             "stale_user_decision": False}]
        assert d["placed_photos"] == placed                       # the list itself is left as geotag wrote it
    before = open(gps, "rb").read()
    res = serve._save(ws, {"gps": [{"dest": dest, "kind": "chosen", "path": f"{dest}/blocked-a.arw",
                                    "user_decision": {"manual_lat": 35.0, "manual_lon": 135.7}}],
                           "hashes": _loaded(ws)})
    assert res["ok"] is False and open(gps, "rb").read() == before


@pytest.mark.spec("RUL-unknown_decision_field_refused", "BLD-geotag_checks_decisions",
                  test="TST-serve-a_photos_23_holding_leave_unlocated_shows_as_unreadable")
def test_a_photos_23_holding_leave_unlocated_shows_as_unreadable(tmp_path):
    """A photos-23 whose photo's decision still holds `accept_unlocated` — a field it does not have — is shown as a
    record that cannot be read, naming the field, as geotag refuses it; and nothing is saved into it."""
    ws = _workspace_with_fixtures(tmp_path)
    gps = os.path.join(ws, serve.CONTROL, serve.GPS_NAME)
    art = json.load(open(gps))
    art["destinations"]["6-photos-by-dest/Japan"]["gps_decisions"]["review_items"][0]["user_decision"][
        "accept_unlocated"] = True
    open(gps, "w").write(json.dumps(art))
    shown = serve._load_artifacts(ws)["gps"]
    assert set(shown) == {"_error"} and "user_decision.accept_unlocated is not a field" in shown["_error"]
    res = serve._save(ws, {"gps": [{"dest": "6-photos-by-dest/Japan", "kind": "fallback",
                                    "user_decision": {"fallback_lat": 35.0, "fallback_lon": 139.0}}],
                           "hashes": _loaded(ws)})
    assert res["ok"] is False and "cannot read" in res["error"]


@pytest.mark.spec("RUL-every_question_in_editor", "BLD-editor_answers_every_question",
                  test="TST-serve-saves_a_phone_s_and_a_clock_change_s_answers")
def test_apply_edits_saves_the_questions_of_a_phone_and_of_a_time_at_a_clock_change():
    """A phone's day kept as it records itself, and a photo's reading at a daylight-saving change: each saved into its
    own decision field of photos-21, nothing else of the record touched."""
    dest, rel = "6-photos-by-dest/B", "6-photos-by-dest/B/twice.jpg"
    art = {"destinations": {dest: {
        "camera_group_time_decisions": {"PHONE": {"camera_group_class": "smartphone", "phone": {"applies_to": "every_photo"},
                                                  "user_decision": {"keep_as_recorded": False}}},
        "local_time_readings": {rel: {"case": "repeated", "offsets_seconds": [7200, 3600],
                                      "user_decision": {"utc_offset_seconds": ""}}}}}}
    before = copy.deepcopy(art)
    edits = [{"dest": dest, "kind": "offset", "key": "PHONE", "user_decision": {"keep_as_recorded": True}},
             {"dest": dest, "kind": "reading", "key": rel, "user_decision": {"utc_offset_seconds": 3600}}]
    assert serve._unapplicable_edits(art, edits) == []
    assert serve._apply_edits(art, edits) == 2
    d = art["destinations"][dest]
    assert d["camera_group_time_decisions"]["PHONE"]["user_decision"] == {"keep_as_recorded": True}
    assert d["local_time_readings"][rel]["user_decision"] == {"utc_offset_seconds": 3600}
    assert d["local_time_readings"][rel]["offsets_seconds"] == before["destinations"][dest]["local_time_readings"][rel]["offsets_seconds"]


@pytest.mark.spec("RUL-every_question_in_editor", "BLD-editor_answers_every_question", "RUL-changed_time_asked",
                  test="TST-serve-saves_a_changed_time_s_answer")
def test_apply_edits_saves_the_answer_for_a_time_changed_since_geotag_wrote_it():
    """A photo's time changed since geotag wrote it: the answer saved into its entry of photos-21's changed_times, by its
    photo's path, nothing else of the record touched."""
    dest, rel = "6-photos-by-dest/T", "6-photos-by-dest/T/a.arw"
    held = {"DateTimeOriginal": "2024:07:03 14:45:00", "OffsetTimeOriginal": "+02:00"}
    art = {"destinations": {dest: {"changed_times": {rel: {"held_time": held, "content_fingerprint": "fp",
                                                           "user_decision": {"keep": "", "answered_for": ""}}}}}}
    edits = [{"dest": dest, "kind": "changed", "key": rel, "user_decision": {"keep": "new", "answered_for": held}}]
    assert serve._unapplicable_edits(art, edits) == [] and serve._apply_edits(art, edits) == 1
    c = art["destinations"][dest]["changed_times"][rel]
    assert c["user_decision"] == {"keep": "new", "answered_for": held} and c["held_time"] == held


@pytest.mark.spec("RUL-every_question_in_editor", "BLD-editor_answers_every_question",
                  test="TST-serve-saves_the_camera_less_files_answer")
def test_apply_edits_saves_the_answer_for_a_destination_s_files_naming_no_camera():
    dest = "6-photos-by-dest/B"
    art = {"destinations": {dest: {"unidentified_files": {"files": 2, "proposed_iana_timezone": "Europe/Brussels",
                                                          "user_decision": {"accept_proposal": False, "accepted_timezone": ""}}}}}
    edits = [{"dest": dest, "kind": "unidentified",
              "user_decision": {"accept_proposal": True, "accepted_timezone": "Europe/Brussels"}}]
    assert serve._unapplicable_edits(art, edits) == [] and serve._apply_edits(art, edits) == 1
    q = art["destinations"][dest]["unidentified_files"]
    assert q["user_decision"] == {"accept_proposal": True, "accepted_timezone": "Europe/Brussels"} and q["files"] == 2


@pytest.mark.spec("RUL-every_question_in_editor", "BLD-editor_answers_every_question", "BLD-date_fallback_cell",
                  test="TST-serve-saves_a_destination_s_date_fallback")
def test_apply_edits_saves_a_destination_s_date_fallback():
    """The date given a destination for its photos with no recorded time is written as its `date_fallback`'s
    `user_decision.date` in photos-21, nothing else of the cell touched."""
    dest = "6-photos-by-dest/Scans"
    art = {"destinations": {dest: {"date_fallback": {"user_decision": {"date": ""}, "effective_date": None,
                                                     "untimed_photos": [f"{dest}/scan001.jpg"],
                                                     "requires_user_input": True, "stale_user_decision": False}}}}
    edits = [{"dest": dest, "kind": "date", "user_decision": {"date": "1985-06"}}]
    assert serve._unapplicable_edits(art, edits) == [] and serve._apply_edits(art, edits) == 1
    c = art["destinations"][dest]["date_fallback"]
    assert c["user_decision"] == {"date": "1985-06"} and c["untimed_photos"] == [f"{dest}/scan001.jpg"]
    assert serve._unapplicable_edits({"destinations": {dest: {}}}, edits) == edits     # no cell: refused, not dropped


@pytest.mark.spec("RUL-every_question_in_editor", "RUL-every_question_answerable_by_hand",
                  "BLD-editor_answers_every_question", "BLD-editor_save_locks",
                  test="TST-serve-saves_a_fingerprint_change_s_answer_into_photos_25")
def test_save_answers_a_fingerprint_mismatch_in_photos_25(tmp_path):
    """photos-25's fingerprint mismatches each ask whether the photo's changed content stands: the editor loads the
    summary with its hash, saves the answer into `user_decision.accept_fingerprint_change` of the mismatch named by its
    photo's path — nothing else of the summary touched — and refuses, like any record, when the summary changed since."""
    ws = _workspace_with_fixtures(tmp_path)
    rel = "6-photos-by-dest/Japan/IMG_1.jpg"
    summary = {"plan_id": "p1", "status": "partial", "totals": {"renames": 0},
               "fingerprint_mismatches": [{"relative_path": rel, "expected_fingerprint": "a" * 64,
                                           "actual_fingerprint": "b" * 64,
                                           "user_decision": {"accept_fingerprint_change": False}}]}
    path = os.path.join(ws, serve.CONTROL, serve.EXECUTION_NAME)
    serve._write_json(path, summary)
    loaded = serve._load_artifacts(ws)
    assert loaded["execution"]["fingerprint_mismatches"][0]["relative_path"] == rel
    edit = {"kind": "fingerprint", "path": rel, "user_decision": {"accept_fingerprint_change": True}}
    # an edit naming a photo the summary holds no mismatch for is refused, nothing written
    res = serve._save(ws, {"execution": [dict(edit, path="6-photos-by-dest/Japan/other.jpg")], "hashes": loaded["hashes"]})
    assert res["ok"] is False and "fingerprint mismatch" in res["error"]
    res = serve._save(ws, {"execution": [edit], "hashes": loaded["hashes"]})
    assert res["ok"] is True and res["written"] == [serve.EXECUTION_NAME]
    after = json.load(open(path))
    assert after["fingerprint_mismatches"][0]["user_decision"] == {"accept_fingerprint_change": True}
    assert {k: v for k, v in after.items() if k != "fingerprint_mismatches"} == \
        {k: v for k, v in summary.items() if k != "fingerprint_mismatches"}
    # a summary rewritten since the editor loaded it (another execution) is not saved over
    serve._write_json(path, dict(summary, plan_id="p2"))
    res = serve._save(ws, {"execution": [edit], "hashes": res["hashes"]})
    assert res["ok"] is False and serve.EXECUTION_NAME in res["error"]


def _camera_workspace(tmp_path):
    """A workspace with the default configuration (`Canon|EOS` classed a fixed-clock camera) and a handoff whose photos
    under photos by destination name one new camera group, `Apple|iPhone 15` — and a video of another, not asked."""
    from cartographer import photos_utils as utils
    ws = _workspace_with_fixtures(tmp_path)
    cfg = copy.deepcopy(utils.DEFAULT_CONFIG)
    cfg["camera_time_and_timezone_policy"]["device_groups"] = {"phones": [], "fixed_clock_cameras": ["Canon|EOS"]}
    utils.write_json_artifact(os.path.join(ws, serve.CONTROL, serve.CONFIG_NAME), cfg)

    def rec(rel, key, media="image"):
        return {"relative_path": rel, "folder_class": "6-photos-by-dest", "media_class": media,
                "metadata_status": {"camera_group_key": key, "has_timestamp": True,
                                    "parsed_json": json.dumps({"selected_source_timestamp_tag": "EXIF:DateTimeOriginal"})}}
    handoff = {"files": [rec("6-photos-by-dest/A/2.heic", "Apple|iPhone 15"), rec("6-photos-by-dest/A/1.heic", "Apple|iPhone 15"),
                         rec("6-photos-by-dest/A/c.cr2", "Canon|EOS", "raw"), rec("6-photos-by-dest/A/v.mov", "GoPro|7", "video")],
               "camera_groups": [{"group_key": "Apple|iPhone 15", "contributing_identity_fields": {"Make": "Apple"}}]}
    utils.write_json_artifact(os.path.join(ws, serve.CONTROL, serve.HANDOFF_NAME), handoff)
    return ws, cfg


@pytest.mark.spec("RUL-every_question_in_editor", "RUL-editor_classes_camera_group", "BLD-editor_writes_device_groups", "BLD-editor_lists_new_camera_groups",
                  "BLD-editor_answers_every_question",
                  test="TST-serve-classes_a_new_camera_group_into_device_groups")
def test_save_classes_a_new_camera_group_into_the_configuration(tmp_path):
    """The editor lists each camera group geotag would stop on — the photos' groups the configuration classes as
    neither phone nor fixed-clock camera — with a photo of it, and its save writes the class the user gives into
    `camera_time_and_timezone_policy.device_groups`, under the lock, over the configuration it loaded, every other
    setting kept."""
    ws, cfg = _camera_workspace(tmp_path)
    loaded = serve._load_artifacts(ws)
    groups = loaded["cameras"]["groups"]
    assert list(groups) == ["Apple|iPhone 15"]                      # a classed camera and a video's group are not asked
    g = groups["Apple|iPhone 15"]
    assert g["files"] == 2 and g["examples"][0] == "6-photos-by-dest/A/1.heic" and g["identity"] == {"Make": "Apple"}
    assert g["user_decision"] == {"device_class": ""} and g["requires_user_input"] is True
    edit = {"kind": "camera", "key": "Apple|iPhone 15", "user_decision": {"device_class": "phones"}}
    # not one of the two arrays: refused, nothing written
    res = serve._save(ws, {"cameras": [dict(edit, user_decision={"device_class": "phone"})], "hashes": loaded["hashes"]})
    assert res["ok"] is False
    res = serve._save(ws, {"cameras": [edit], "hashes": loaded["hashes"]})
    assert res["ok"] is True and res["written"] == [serve.CONFIG_NAME]
    after = json.load(open(os.path.join(ws, serve.CONTROL, serve.CONFIG_NAME)))
    assert after["camera_time_and_timezone_policy"]["device_groups"] == {"phones": ["Apple|iPhone 15"],
                                                                         "fixed_clock_cameras": ["Canon|EOS"]}
    after["camera_time_and_timezone_policy"]["device_groups"] = cfg["camera_time_and_timezone_policy"]["device_groups"]
    assert after == cfg                                                # that setting, and no other
    assert serve._load_artifacts(ws)["cameras"]["groups"] == {}        # nothing left to ask
    # a group classed meanwhile is no question to answer; and a configuration changed since is not written over
    res2 = serve._save(ws, {"cameras": [edit], "hashes": res["hashes"]})
    assert res2["ok"] is False and "classes no new camera group" in res2["error"]
    res3 = serve._save(ws, {"cameras": [edit], "hashes": loaded["hashes"]})
    assert res3["ok"] is False and serve.CONFIG_NAME in res3["error"]


@pytest.mark.spec("RUL-save_only_what_was_shown", "BLD-editor_writes_device_groups", "BLD-editor_marks_several_bodies",
                  test="TST-serve-a_class_is_not_saved_over_a_configuration_changed_since_load")
def test_a_class_is_not_saved_over_a_configuration_changed_since_load(tmp_path):
    """The configuration changed by hand since the editor loaded it — another setting, the camera group still
    unclassed, so the class asked for is still a question — refuses the save of a class, naming the configuration, and
    leaves the file as the hand left it; reloaded, the same class is saved over the configuration as it now stands."""
    ws, cfg = _camera_workspace(tmp_path)
    cfg_path = os.path.join(ws, serve.CONTROL, serve.CONFIG_NAME)
    loaded = serve._load_artifacts(ws)
    assert list(loaded["cameras"]["groups"]) == ["Apple|iPhone 15"]
    by_hand = copy.deepcopy(cfg)
    by_hand["merge"]["library_space_margin_percent"] = 7               # an unrelated setting, the group untouched
    from cartographer import photos_utils as utils
    utils.write_json_artifact(cfg_path, by_hand)
    before = open(cfg_path, "rb").read()
    edit = {"kind": "camera", "key": "Apple|iPhone 15", "user_decision": {"device_class": "phones"}}
    res = serve._save(ws, {"cameras": [edit], "hashes": loaded["hashes"]})
    assert res["ok"] is False and serve.CONFIG_NAME in res["error"] and "changed since" in res["error"], res
    assert open(cfg_path, "rb").read() == before                       # left as the hand left it
    again = serve._load_artifacts(ws)
    res = serve._save(ws, {"cameras": [edit], "hashes": again["hashes"]})
    assert res["ok"] is True, res
    after = json.load(open(cfg_path))
    assert after["merge"]["library_space_margin_percent"] == 7
    assert after["camera_time_and_timezone_policy"]["device_groups"]["phones"] == ["Apple|iPhone 15"]


@pytest.mark.spec("RUL-editor_marks_several_bodies", "BLD-editor_marks_several_bodies", "RUL-every_question_in_editor",
                  "RUL-every_question_answerable_by_hand",
                  test="TST-serve-names_a_camera_group_several_bodies_in_the_configuration")
def test_save_names_a_camera_group_several_bodies_in_the_configuration(tmp_path):
    """The editor lists each fixed-clock camera group of the photos with whether the configuration names it several
    bodies — never a question that waits — and its save puts the group into `several_bodies_groups`, or takes it out,
    under the lock, over the configuration it loaded, that setting and no other. A group that is no fixed-clock camera
    of the photos, or an answer that is not true or false, is refused."""
    ws, cfg = _camera_workspace(tmp_path)
    loaded = serve._load_artifacts(ws)
    bodies = loaded["cameras"]["bodies"]
    assert list(bodies) == ["Canon|EOS"]                            # the new phone group is a question, not a body
    assert bodies["Canon|EOS"]["user_decision"] == {"several_bodies": False}
    assert bodies["Canon|EOS"]["requires_user_input"] is False and bodies["Canon|EOS"]["files"] == 1
    edit = {"kind": "bodies", "key": "Canon|EOS", "user_decision": {"several_bodies": True}}
    for bad in (dict(edit, key="Apple|iPhone 15"), dict(edit, user_decision={"several_bodies": "yes"})):
        res = serve._save(ws, {"cameras": [bad], "hashes": loaded["hashes"]})
        assert res["ok"] is False
    res = serve._save(ws, {"cameras": [edit], "hashes": loaded["hashes"]})
    assert res["ok"] is True and res["written"] == [serve.CONFIG_NAME]
    path = os.path.join(ws, serve.CONTROL, serve.CONFIG_NAME)
    after = json.load(open(path))
    assert after["camera_time_and_timezone_policy"]["several_bodies_groups"] == ["Canon|EOS"]
    after["camera_time_and_timezone_policy"]["several_bodies_groups"] = []
    assert after == cfg                                                # that setting, and no other
    again = serve._load_artifacts(ws)
    assert again["cameras"]["bodies"]["Canon|EOS"]["user_decision"] == {"several_bodies": True}
    res = serve._save(ws, {"cameras": [dict(edit, user_decision={"several_bodies": False})], "hashes": again["hashes"]})
    assert res["ok"] is True
    assert json.load(open(path))["camera_time_and_timezone_policy"]["several_bodies_groups"] == []


@pytest.mark.spec("RUL-editor_classes_camera_group", "BLD-editor_writes_device_groups",
                  test="TST-serve-a_class_given_moves_a_group_listed_twice_and_is_checked")
def test_a_class_given_moves_a_group_listed_in_both_arrays_and_the_result_is_checked(tmp_path):
    """Geotag's snippet lists a new group in both arrays; one left in both is still unclassed, and asked. Answered, it is
    taken out of the other; a configuration that `load_config` would refuse is not written."""
    ws, cfg = _camera_workspace(tmp_path)
    path = os.path.join(ws, serve.CONTROL, serve.CONFIG_NAME)
    cfg["camera_time_and_timezone_policy"]["device_groups"] = {"phones": ["Apple|iPhone 15"],
                                                               "fixed_clock_cameras": ["Canon|EOS", "Apple|iPhone 15"]}
    serve._write_json(path, cfg)
    loaded = serve._load_artifacts(ws)
    assert list(loaded["cameras"]["groups"]) == ["Apple|iPhone 15"]
    edit = {"kind": "camera", "key": "Apple|iPhone 15", "user_decision": {"device_class": "fixed_clock_cameras"}}
    res = serve._save(ws, {"cameras": [edit], "hashes": loaded["hashes"]})
    assert res["ok"] is True
    assert json.load(open(path))["camera_time_and_timezone_policy"]["device_groups"] == {
        "phones": [], "fixed_clock_cameras": ["Canon|EOS", "Apple|iPhone 15"]}
    # a configuration lacking a setting is refused as load_config refuses it, and left as it is
    broken = copy.deepcopy(cfg)
    del broken["gpx_root"]
    serve._write_json(path, broken)
    before = open(path).read()
    loaded = serve._load_artifacts(ws)
    res = serve._save(ws, {"cameras": [edit], "hashes": loaded["hashes"]})
    assert res["ok"] is False and "gpx_root" in res["error"] and open(path).read() == before


def _every_record_workspace(tmp_path):
    """The camera workspace with a photos-22 besides, and a save payload that changes photos-21, -22, -23 and the
    configuration at once."""
    ws, _cfg = _camera_workspace(tmp_path)
    shutil.copy(os.path.join(EXAMPLES, "photos-22-gps-drift-validation.requires-input.json"),
                os.path.join(ws, serve.CONTROL, serve.DRIFT_NAME))
    payload = {
        "time": [{"dest": "6-photos-by-dest/Japan", "kind": "timezone",
                  "user_decision": {"confirmed_despite_recorded_offsets": [], "country": "",
                                    "manual_iana_timezone": "Asia/Tokyo"}}],
        "drift": [{"dest": "6-photos-by-dest/DriftTown", "kind": "drift", "key": "CAM|drift|D",
                   "user_decision": {"accept_proposal": True}}],
        "gps": [{"dest": "6-photos-by-dest/Japan", "kind": "fallback",
                 "user_decision": {"fallback_lat": 35.0, "fallback_lon": 139.0}}],
        "cameras": [{"kind": "camera", "key": "Apple|iPhone 15", "user_decision": {"device_class": "phones"}}],
        "hashes": serve._load_artifacts(ws)["hashes"]}
    return ws, payload


@pytest.mark.spec("RUL-save_writes_in_order", "BLD-editor_save_order",
                  test="TST-serve-a_save_writes_its_records_in_order")
def test_a_save_writes_its_records_in_order(tmp_path, monkeypatch):
    """A save changing every record writes photos-21, photos-22, photos-23 and then the configuration, one after
    another."""
    from cartographer import photos_utils as utils
    ws, payload = _every_record_workspace(tmp_path)
    order = []
    real_record, real_config = serve._write_json, utils.write_json_artifact
    monkeypatch.setattr(serve, "_write_json", lambda p, o: (order.append(os.path.basename(p)), real_record(p, o))[1])
    monkeypatch.setattr(utils, "write_json_artifact",
                        lambda p, o: (order.append(os.path.basename(p)), real_config(p, o))[1])
    res = serve._save(ws, payload)
    assert res["ok"] is True
    assert order == res["written"] == [serve.TIME_NAME, serve.DRIFT_NAME, serve.GPS_NAME, serve.CONFIG_NAME]


@pytest.mark.spec("RUL-save_writes_in_order", "BLD-editor_save_order",
                  test="TST-serve-a_save_cut_short_leaves_only_its_leading_records")
def test_a_save_cut_short_leaves_only_its_leading_records(tmp_path, monkeypatch):
    """A save whose write of photos-22 fails has written photos-21 and left photos-22, photos-23 and the configuration
    as they were: what it leaves is a leading part of it."""
    ws, payload = _every_record_workspace(tmp_path)
    cd = os.path.join(ws, serve.CONTROL)
    before = {n: open(os.path.join(cd, n), "rb").read()
              for n in (serve.TIME_NAME, serve.DRIFT_NAME, serve.GPS_NAME, serve.CONFIG_NAME)}
    real = serve._write_json

    def cut(path, obj):
        if os.path.basename(path) == serve.DRIFT_NAME:
            raise OSError("no space left on device")
        real(path, obj)
    monkeypatch.setattr(serve, "_write_json", cut)
    with pytest.raises(OSError):
        serve._save(ws, payload)
    after = {n: open(os.path.join(cd, n), "rb").read() for n in before}
    assert after[serve.TIME_NAME] != before[serve.TIME_NAME]
    assert json.loads(after[serve.TIME_NAME])["destinations"]["6-photos-by-dest/Japan"]["destination_timezone"][
        "user_decision"]["manual_iana_timezone"] == "Asia/Tokyo"
    assert {n: after[n] for n in (serve.DRIFT_NAME, serve.GPS_NAME, serve.CONFIG_NAME)} == \
        {n: before[n] for n in (serve.DRIFT_NAME, serve.GPS_NAME, serve.CONFIG_NAME)}
    lock = serve.photos_utils.WorkspaceLock(ws, create=False)
    assert lock.acquire()                                                   # the lock was let go
    lock.release()


@pytest.mark.spec("RUL-save_keeps_the_replaced", "BLD-editor_keeps_replaced_record",
                  test="TST-serve-a_save_keeps_the_record_it_replaces_under_nnn")
def test_a_save_keeps_the_record_it_replaces_under_nnn(tmp_path):
    """Each save that changes a record first keeps the one it replaces beside it under -NNN, numbered on from the
    copies a re-plan left: two saves leave two copies, in order. A save that changes nothing in the record sets nothing
    aside; the configuration keeps no copy."""
    ws, payload = _every_record_workspace(tmp_path)
    cd = os.path.join(ws, serve.CONTROL)
    gps = os.path.join(cd, serve.GPS_NAME)
    replanned = os.path.join(cd, "photos-23-gps-decisions-001.json")      # a re-plan's copy, already there
    with open(replanned, "w") as f:
        f.write('{"earlier": "plan"}')
    original = open(gps, "rb").read()
    fallback = payload["gps"][0]
    res = serve._save(ws, {"gps": [fallback], "hashes": payload["hashes"]})
    assert res["ok"] is True
    first = open(gps, "rb").read()
    res = serve._save(ws, {"gps": [dict(fallback, user_decision={"fallback_lat": 36.0, "fallback_lon": 139.0})],
                           "hashes": res["hashes"]})
    assert res["ok"] is True
    copies = sorted(n for n in os.listdir(cd) if n.startswith("photos-23-gps-decisions-"))
    assert copies == ["photos-23-gps-decisions-001.json", "photos-23-gps-decisions-002.json",
                      "photos-23-gps-decisions-003.json"]
    assert open(replanned).read() == '{"earlier": "plan"}'
    assert open(os.path.join(cd, copies[1]), "rb").read() == original
    assert open(os.path.join(cd, copies[2]), "rb").read() == first
    assert json.load(open(gps))["destinations"]["6-photos-by-dest/Japan"]["folder_fallback"]["user_decision"][
        "fallback_lat"] == 36.0
    # the same answer saved again changes nothing in the record: nothing more set aside
    res = serve._save(ws, {"gps": [dict(fallback, user_decision={"fallback_lat": 36.0, "fallback_lon": 139.0})],
                           "hashes": res["hashes"]})
    assert res["ok"] is True and len([n for n in os.listdir(cd) if n.startswith("photos-23-gps-decisions-")]) == 3
    # the configuration, rewritten by a camera group's class, keeps no copy
    res = serve._save(ws, {"cameras": payload["cameras"], "hashes": res["hashes"]})
    assert res["ok"] is True and not [n for n in os.listdir(cd) if n.startswith("photos-00-config-")]


def test_apply_edits_ignores_unknown_targets():
    art = _time_art()
    n = serve._apply_edits(art, [
        {"dest": "6-photos-by-dest/Nowhere", "kind": "timezone", "user_decision": {"x": 1}},
        {"dest": "6-photos-by-dest/Japan", "kind": "bogus", "user_decision": {"x": 1}},
        {"dest": "6-photos-by-dest/Japan", "kind": "timezone", "user_decision": "not-a-dict"},
    ])
    assert n == 0


# --------------------------------------------------------------------------- _save

def test_save_round_trips_only_user_decision(tmp_path):
    ws = _workspace_with_fixtures(tmp_path)
    before = json.load(open(os.path.join(ws, serve.CONTROL, serve.TIME_NAME)))
    res = serve._save(ws, {"time": [{"dest": "6-photos-by-dest/Japan", "kind": "timezone",
                                     "user_decision": {"manual_iana_timezone": "Asia/Tokyo"}}],
                           "hashes": _loaded(ws)})
    assert res["ok"] is True and res["written"] == [serve.TIME_NAME]
    after = json.load(open(os.path.join(ws, serve.CONTROL, serve.TIME_NAME)))
    edited = after["destinations"]["6-photos-by-dest/Japan"]["destination_timezone"]
    assert edited["user_decision"]["manual_iana_timezone"] == "Asia/Tokyo"
    # Strip user_decision everywhere and the artifact must be byte-for-byte what it was.
    def _strip(a):
        a = copy.deepcopy(a)
        for d in a["destinations"].values():
            for cell in (d.get("destination_timezone"), d.get("folder_fallback")):
                if isinstance(cell, dict):
                    cell.pop("user_decision", None)
            for cell in (d.get("camera_group_time_decisions") or {}).values():
                cell.pop("user_decision", None)
        return a
    assert _strip(after) == _strip(before)


def test_save_no_edits_writes_nothing(tmp_path):
    ws = _workspace_with_fixtures(tmp_path)
    before = _loaded(ws)
    assert serve._save(ws, {}) == {"ok": True, "written": [], "hashes": before}
    assert _loaded(ws) == before


def test_save_unreadable_artifact_errors(tmp_path):
    ws = _workspace_with_fixtures(tmp_path)
    (tmp_path / serve.CONTROL / serve.TIME_NAME).write_text("{broken")
    res = serve._save(ws, {"time": [{"dest": "6-photos-by-dest/Japan", "kind": "timezone",
                                     "user_decision": {"x": 1}}]})
    assert res["ok"] is False and "error" in res


# --------------------------------------------------------------------------- HTTP routes

def test_http_get_artifacts_demo():
    with _running(None) as base:
        status, body, ctype = _get(base + "/api/artifacts")
        assert status == 200 and "json" in ctype
        data = json.loads(body)
        assert data["demo"] is True and "destinations" in data["time"]


def test_http_get_static_index_and_404():
    with _running(None) as base:
        status, body, ctype = _get(base + "/")
        assert status == 200 and "html" in ctype and b"Decision editor" in body
        assert _get(base + "/does-not-exist.txt")[0] == 404


def test_http_post_save_is_403_in_demo():
    with _running(None) as base:
        status, data = _post_json(base + "/api/save", {"time": []})
        assert status == 403 and data["ok"] is False


def test_http_post_unknown_route_404():
    with _running(None) as base:
        status, data = _post_json(base + "/api/nope", {})
        assert status == 404


# --------------------------------------------------------------------------- photo preview

def test_safe_workspace_path_blocks_escape(tmp_path):
    ws = str(tmp_path)
    assert serve._safe_workspace_path(ws, "../../etc/passwd") is None
    assert serve._safe_workspace_path(ws, "a/../../b") is None
    inside = serve._safe_workspace_path(ws, "6-photos-by-dest/x.arw")
    assert inside == os.path.join(os.path.abspath(ws), "6-photos-by-dest/x.arw")
    # A leading slash is neutralised to workspace-relative (stays inside, never reaches the real root).
    neutralised = serve._safe_workspace_path(ws, "/etc/passwd")
    assert neutralised.startswith(os.path.abspath(ws) + os.sep)


def test_photo_preview_missing_file_is_none(tmp_path):
    assert serve._photo_preview(str(tmp_path), "nope.jpg") is None


@pytest.mark.skipif(not HAVE_MAGICK, reason="ImageMagick not installed")
def test_photo_preview_returns_jpeg(tmp_path):
    sub = tmp_path / "6-photos-by-dest" / "Japan"
    sub.mkdir(parents=True)
    _make_jpeg(sub / "pic.jpg")
    data = serve._photo_preview(str(tmp_path), "6-photos-by-dest/Japan/pic.jpg")
    assert data and data[:2] == b"\xff\xd8"  # JPEG start-of-image


def test_http_photo_404_in_demo():
    with _running(None) as base:
        assert _get(base + "/api/photo?path=x.jpg")[0] == 404


def test_http_photo_missing_and_escape_404(tmp_path):
    ws = _workspace_with_fixtures(tmp_path)
    with _running(ws) as base:
        assert _get(base + "/api/photo?path=6-photos-by-dest/Japan/nope.jpg")[0] == 404
        assert _get(base + "/api/photo?path=../../../../etc/passwd")[0] == 404


@pytest.mark.skipif(not HAVE_MAGICK, reason="ImageMagick not installed")
def test_http_photo_serves_jpeg(tmp_path):
    ws = _workspace_with_fixtures(tmp_path)
    sub = os.path.join(ws, "6-photos-by-dest", "Japan")
    os.makedirs(sub)
    _make_jpeg(os.path.join(sub, "pic.jpg"))
    with _running(ws) as base:
        status, body, ctype = _get(base + "/api/photo?path=6-photos-by-dest/Japan/pic.jpg")
        assert status == 200 and "image/jpeg" in ctype and body[:2] == b"\xff\xd8"


def test_http_serves_vendored_leaflet():
    with _running(None) as base:
        status, body, ctype = _get(base + "/vendor/leaflet/leaflet.js")
        assert status == 200 and "javascript" in ctype and b"Leaflet" in body
        assert _get(base + "/vendor/leaflet/images/marker-icon.png")[2] == "image/png"


def test_http_post_save_writes_to_workspace(tmp_path):
    ws = _workspace_with_fixtures(tmp_path)
    with _running(ws) as base:
        hashes = json.loads(_get(base + "/api/artifacts")[1])["hashes"]
        status, data = _post_json(base + "/api/save", {
            "time": [{"dest": "6-photos-by-dest/Japan", "kind": "timezone",
                      "user_decision": {"manual_iana_timezone": "Asia/Tokyo"}}], "hashes": hashes})
        assert status == 200 and data["ok"] is True and data["written"] == [serve.TIME_NAME]
    saved = json.load(open(os.path.join(ws, serve.CONTROL, serve.TIME_NAME)))
    cell = saved["destinations"]["6-photos-by-dest/Japan"]["destination_timezone"]
    assert cell["user_decision"]["manual_iana_timezone"] == "Asia/Tokyo"


# --------------------------------------------------------------------------- cwd-workspace contract

def test_serve_aborts_when_cwd_is_not_a_workspace(tmp_path):
    # edit operates on the cwd workspace; an uninitialized dir (no guard sentinel) is refused, not served.
    with pytest.raises(SystemExit) as e:
        serve.serve(str(tmp_path), port=0)
    assert e.value.code == 2


def test_serve_aborts_when_control_present_but_guard_absent(tmp_path):
    # Having a .photos-ingest/ with decision JSON is NOT enough — the workspace guard must exist.
    ws = _workspace_with_fixtures(tmp_path)
    assert not os.path.exists(os.path.join(ws, serve.CONTROL, serve.GUARD_NAME))
    with pytest.raises(SystemExit) as e:
        serve.serve(ws, port=0)
    assert e.value.code == 2


def test_send_swallows_client_disconnect():
    # A browser that cancels a hover photo-preview mid-send makes wfile.write raise BrokenPipeError;
    # _send must drop it quietly (no traceback) and mark the connection for close.
    h = serve.Handler.__new__(serve.Handler)
    h.close_connection = False
    h.send_response = lambda *a, **k: None
    h.send_header = lambda *a, **k: None
    h.end_headers = lambda: None

    class _Boom:
        def write(self, b):
            raise BrokenPipeError(32, "Broken pipe")
    h.wfile = _Boom()
    h._send(200, b"x" * 16, "image/jpeg")        # must NOT raise
    assert h.close_connection is True


def test_edit_has_no_workspace_arg_and_demo_is_the_only_no_workspace_mode():
    import argparse
    p = argparse.ArgumentParser()
    serve.add_arguments(p)
    a = p.parse_args([])
    assert a.demo is False and not hasattr(a, "workspace")   # no workspace-naming argument
    assert p.parse_args(["--demo"]).demo is True


def test_edit_help_names_both_refusals_and_the_whole_loop():
    # `edit -h` refuses an uninitialized workspace AND a sealed one, and the loop runs through finalize.
    assert "sealed" in serve.EDIT_BLURB
    assert "geotag execute -> geotag finalize" in serve.EDIT_BLURB


@pytest.mark.spec("RUL-one_editor_at_a_time", "BLD-editor_session_lock", test="TST-serve-serve_refuses_a_second_editor_without_naming_a_workspace_argument")
def test_serve_refuses_a_second_editor_without_naming_a_workspace_argument(tmp_path, capsys):
    # The editor works on the cwd: the refusal says to close the other editor (or console Edit tab), or to
    # run this one from another workspace's folder — never to "point it at" a workspace it takes no argument for.
    ws = _workspace_with_fixtures(tmp_path)
    open(os.path.join(ws, serve.CONTROL, serve.GUARD_NAME), "w").close()
    held, _ = serve._acquire_editor_lock(ws)
    try:
        with pytest.raises(SystemExit) as e:
            serve.serve(ws, port=0)
        assert e.value.code == 1
    finally:
        held.close()
    err = capsys.readouterr().err
    assert "console" in err and "run this one from another workspace's folder" in err
    assert "point this one" not in err


def _seal(ws):
    (open(os.path.join(ws, serve.CONTROL, "photos-00-sealed.json"), "w")
     .write('{"sealed": true, "merged_run_id": "r1"}'))


@pytest.mark.spec("RUL-editor_refuses_sealed", test="TST-serve-serve_refuses_a_sealed_workspace")
def test_serve_refuses_a_sealed_workspace(tmp_path):
    # A merged workspace is final: the editor will not open it, so its decisions cannot change.
    ws = _workspace_with_fixtures(tmp_path)
    open(os.path.join(ws, serve.CONTROL, serve.GUARD_NAME), "w").close()
    _seal(ws)
    with pytest.raises(SystemExit) as e:
        serve.serve(ws, port=0)
    assert e.value.code == 2
    assert not os.path.exists(os.path.join(ws, serve.CONTROL, serve.EDITOR_LOCK))


@pytest.mark.spec("RUL-sealed_new_dump_warned", "RUL-sealed_new_dump_left", test="TST-serve-serve_points_out_a_dump_in_a_sealed_workspace")
def test_serve_points_out_a_dump_in_a_sealed_workspace(tmp_path, capsys):
    # Refusing a sealed workspace, the editor says a dump dropped in its inbox is likely new, and leaves it.
    ws = _workspace_with_fixtures(tmp_path)
    open(os.path.join(ws, serve.CONTROL, serve.GUARD_NAME), "w").close()
    _seal(ws)
    inbox = os.path.join(ws, "0-sources")
    os.makedirs(inbox, exist_ok=True)
    open(os.path.join(inbox, "new.jpg"), "wb").write(b"img")
    with pytest.raises(SystemExit) as e:
        serve.serve(ws, port=0)
    assert e.value.code == 2
    assert "new dump" in capsys.readouterr().err.lower()
    assert os.listdir(inbox) == ["new.jpg"]


@pytest.mark.spec("RUL-sealed_new_dump_warned", test="TST-serve-sealed_dump_check_goes_by_the_workspaces_folder_names")
def test_sealed_dump_check_goes_by_the_workspaces_folder_names(tmp_path, capsys):
    # The editor never loads the workspace's configuration, so the check reads the folder names from its
    # file: a workspace with renamed folders holding only them has no new dump, and one dropped into its
    # renamed inbox is pointed out by that name.
    ws = _workspace_with_fixtures(tmp_path)
    folders = {r: f"x-{n}" for r, n in serve.photos_utils.DEFAULT_FOLDERS.items()}
    with open(os.path.join(ws, serve.CONTROL, "photos-00-config.json"), "w") as f:
        json.dump({"folders": folders}, f)
    for n in folders.values():
        os.makedirs(os.path.join(ws, n))
    open(os.path.join(ws, serve.CONTROL, serve.GUARD_NAME), "w").close()
    _seal(ws)
    with pytest.raises(SystemExit):
        serve.serve(ws, port=0)
    assert "new dump" not in capsys.readouterr().err.lower()
    inbox = os.path.join(ws, folders["sources"])
    open(os.path.join(inbox, "new.jpg"), "wb").write(b"img")
    with pytest.raises(SystemExit):
        serve.serve(ws, port=0)
    err = capsys.readouterr().err
    assert "new dump" in err.lower() and folders["sources"] in err
    assert serve.photos_utils.CONFIG["folders"] == serve.photos_utils.DEFAULT_FOLDERS   # CONFIG untouched


@pytest.mark.spec("RUL-editor_refuses_sealed_save", test="TST-serve-save_refuses_a_sealed_workspace")
def test_save_refuses_a_sealed_workspace(tmp_path):
    # The console calls _save directly, without serve()'s startup check: the save refuses on its own.
    ws = _workspace_with_fixtures(tmp_path)
    _seal(ws)
    before = open(os.path.join(ws, serve.CONTROL, serve.TIME_NAME), "rb").read()
    res = serve._save(ws, {"time": [{"dest": "6-photos-by-dest/Japan", "kind": "timezone",
                                     "user_decision": {"manual_iana_timezone": "Asia/Tokyo"}}]})
    assert res["ok"] is False and "sealed" in res["error"]
    assert open(os.path.join(ws, serve.CONTROL, serve.TIME_NAME), "rb").read() == before


@pytest.mark.spec("RUL-every_command_locks", test="TST-serve-save_refuses_while_a_run_holds_the_lock")
def test_save_refuses_while_a_run_holds_the_lock(tmp_path):
    """A save changes the workspace, so it takes the workspace's lock: while a run holds it, the save
    refuses and writes nothing — it cannot land between a geotag plan's read and its rewrite. Once the
    run ends, the same save goes through, and leaves the lock free."""
    ws = _workspace_with_fixtures(tmp_path)
    edit = {"time": [{"dest": "6-photos-by-dest/Japan", "kind": "timezone",
                      "user_decision": {"manual_iana_timezone": "Asia/Tokyo"}}]}
    path = os.path.join(ws, serve.CONTROL, serve.TIME_NAME)
    before = open(path, "rb").read()
    run = serve.photos_utils.WorkspaceLock(ws, create=False)
    assert run.acquire()
    try:
        res = serve._save(ws, edit)
        assert res["ok"] is False and "run is in progress" in res["error"]
        assert open(path, "rb").read() == before
    finally:
        run.release()
    assert serve._save(ws, dict(edit, hashes=_loaded(ws)))["ok"] is True
    assert open(path, "rb").read() != before
    assert serve.photos_utils.WorkspaceLock(ws, create=False).held_owner() is None


# --------------------------------------------------------------------------- save only what was shown

def _records(ws):
    return {n: open(os.path.join(ws, serve.CONTROL, n), "rb").read()
            for n in (serve.TIME_NAME, serve.GPS_NAME)}


_TZ_EDIT = {"dest": "6-photos-by-dest/Japan", "kind": "timezone",
            "user_decision": {"manual_iana_timezone": "Asia/Tokyo"}}


@pytest.mark.spec("RUL-save_only_what_was_shown", test="TST-serve-save_refused_when_a_record_changed_since_loaded")
def test_save_refused_when_a_record_changed_since_loaded(tmp_path):
    """A geotag plan rewrote photos-23 after the editor loaded the records: a save of photos-21 edits is
    refused, telling the user to reload, and none of the records is written."""
    ws = _workspace_with_fixtures(tmp_path)
    hashes = _loaded(ws)
    gps = os.path.join(ws, serve.CONTROL, serve.GPS_NAME)
    art = json.load(open(gps))
    art["requires_user_input"] = not art.get("requires_user_input")
    serve._write_json(gps, art)
    before = _records(ws)
    res = serve._save(ws, {"time": [_TZ_EDIT], "hashes": hashes})
    assert res["ok"] is False and serve.GPS_NAME in res["error"] and "reload" in res["error"].lower()
    assert serve.TIME_NAME not in res["error"]
    assert _records(ws) == before


@pytest.mark.spec("RUL-save_only_what_was_shown", test="TST-serve-save_refused_without_the_loaded_hashes")
def test_save_refused_without_the_loaded_hashes(tmp_path):
    """A save that does not say which records it was made from cannot show it was made from these."""
    ws = _workspace_with_fixtures(tmp_path)
    before = _records(ws)
    res = serve._save(ws, {"time": [_TZ_EDIT]})
    assert res["ok"] is False and "reload" in res["error"].lower()
    assert _records(ws) == before


@pytest.mark.spec("RUL-save_only_what_was_shown", test="TST-serve-save_refused_when_an_edit_names_no_cell")
def test_save_refused_when_an_edit_names_no_cell(tmp_path):
    """An edit naming a decision the record does not hold is refused — never dropped while the rest is
    written — and nothing is written."""
    ws = _workspace_with_fixtures(tmp_path)
    before = _records(ws)
    res = serve._save(ws, {"time": [_TZ_EDIT, {"dest": "6-photos-by-dest/Nowhere", "kind": "timezone",
                                                "user_decision": {"manual_iana_timezone": "UTC"}}],
                           "hashes": _loaded(ws)})
    assert res["ok"] is False and "6-photos-by-dest/Nowhere" in res["error"] and "reload" in res["error"].lower()
    assert _records(ws) == before


@pytest.mark.spec("RUL-save_only_what_was_shown", test="TST-serve-save_hands_back_the_hashes_it_leaves")
def test_save_hands_back_the_hashes_it_leaves(tmp_path):
    """A save made from the records as loaded goes through, a record absent then and now among them, and
    hands back the hashes of what it left, so the next save from the same page goes through too."""
    ws = _workspace_with_fixtures(tmp_path)
    loaded = _loaded(ws)
    assert loaded["drift"] is None                               # this workspace has no photos-22
    res = serve._save(ws, {"time": [_TZ_EDIT], "hashes": loaded})
    assert res["ok"] is True and res["hashes"] == _loaded(ws) and res["hashes"]["time"] != loaded["time"]
    again = serve._save(ws, {"time": [dict(_TZ_EDIT, user_decision={"manual_iana_timezone": "Asia/Seoul"})],
                             "hashes": res["hashes"]})
    assert again["ok"] is True
    stale = serve._save(ws, {"time": [_TZ_EDIT], "hashes": loaded})   # the page's first hashes are now stale
    assert stale["ok"] is False
