// Copyright 2026 sigfridvonshrink
//
// Licensed under the Apache License, Version 2.0 (the "License");
// you may not use this file except in compliance with the License.
// You may obtain a copy of the License at
//
//     http://www.apache.org/licenses/LICENSE-2.0
//
// Unless required by applicable law or agreed to in writing, software
// distributed under the License is distributed on an "AS IS" BASIS,
// WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
// See the License for the specific language governing permissions and
// limitations under the License.

// Front-end unit tests for the questions geotag asks of a phone's clock, of the GPS fixes' own times, of files naming
// no camera and of a time a daylight-saving change skips or repeats (web/app.js): each is answerable here, writing
// the decision field the record documents (decision-json-reference §4).
import { test } from "node:test";
import assert from "node:assert/strict";
import * as app from "../web/app.js";

const setWork = (work) => { app.state.work = work; app.state.base = JSON.parse(JSON.stringify(work)); };
app.setHostZones(["Asia/Tokyo", "Europe/Brussels", "UTC"]);
const DEST = "6-photos-by-dest/Kyoto";

test("a GPS-time proposal: accepted within its tolerance, as one from the camera's GPS is", () => {
  const p = { proposal_source: "gps_time", proposed_offset_seconds: -32430, acceptance_tolerance_seconds: 120 };
  assert.equal(app.acceptHolds({ user_decision: { accept_proposal: true, accepted_offset_seconds: -32400 }, proposal: p }), true);
  assert.equal(app.acceptHolds({ user_decision: { accept_proposal: true, accepted_offset_seconds: -3600 }, proposal: p }), false);
});

test("why the fixes' times were set aside is said", () => {
  assert.match(app.gpsTimeAsideNote({ reason: "repeated_gps_time", gps_time_count: 2, example: `${DEST}/a.arw` }), /stale fix/);
  assert.match(app.gpsTimeAsideNote({ reason: "offsets_disagree", gps_time_count: 2, example: `${DEST}/a.arw`,
    offsets_seconds: [-32430, -31830] }), /too far apart/);
  const notes = app.offsetCellNotes({ proposal: {}, gps_time_set_aside: { reason: "repeated_gps_time", gps_time_count: 2, example: "a" } });
  assert.equal(notes.length, 1);
});

const PHONE = "Apple|iPhone 15|";
const phoneCell = (ud, source = "gpx_self_anchor") => ({
  camera_group: PHONE, camera_group_class: "smartphone", phone: { applies_to: "every_photo", photos: 3, read_by_offsets: [-7200] },
  proposal: { proposal_source: source, proposed_offset_seconds: -3600, acceptance_tolerance_seconds: 120 },
  user_decision: { accept_proposal: false, accepted_offset_seconds: "", manual_offset_seconds: "", keep_as_recorded: false, ...ud } });

test("a phone's day: kept as it records itself, accepted, or set — each resolves it, one at a time", () => {
  const ref = { file: "time", dest: DEST, kind: "offset", key: PHONE };
  const mk = (cell) => setWork({ time: { destinations: { [DEST]: { camera_group_time_decisions: { [PHONE]: cell } } } } });
  mk(phoneCell({}));                                                   assert.equal(app.wouldResolve(ref), false);
  mk(phoneCell(app.keepFields(phoneCell({}), true)));                  assert.equal(app.wouldResolve(ref), true);
  assert.deepEqual(app.keepFields(phoneCell({}), true),
    { keep_as_recorded: true, accept_proposal: false, accepted_offset_seconds: "", manual_offset_seconds: "" });
  mk(phoneCell({ keep_as_recorded: true }, "timezone_naive"));        assert.equal(app.wouldResolve(ref), false);  // nothing of its GPS to set aside
  assert.equal(app.keepOffered(phoneCell({}, "gps_time")), true);
  mk(phoneCell({ accept_proposal: true, accepted_offset_seconds: -3600 })); assert.equal(app.wouldResolve(ref), true);
  assert.match(app.phoneNote(phoneCell({})), /read by −2h 00m 00s.*−1h 00m 00s.*all 3/);
  assert.equal(app.phoneNote({ proposal: {} }), "");
});

test("a photo's time at a daylight-saving change: one of its two readings, or for a skipped time an offset", () => {
  const rel = `${DEST}/twice.jpg`, ref = { file: "time", dest: DEST, kind: "reading", key: rel };
  const cell = (c, v) => ({ case: c, offsets_seconds: [7200, 3600], camera_time: "2026:10:25 02:30:00", timezone: "Europe/Brussels",
    readings_utc: ["2026-10-25T00:30:00Z", "2026-10-25T01:30:00Z"], user_decision: { utc_offset_seconds: v } });
  const mk = (c) => setWork({ time: { destinations: { [DEST]: { local_time_readings: { [rel]: c } } } } });
  mk(cell("repeated", ""));        assert.equal(app.wouldResolve(ref), false); assert.equal(app.refInvalid(ref), false);
  mk(cell("repeated", 3600));      assert.equal(app.wouldResolve(ref), true);
  mk(cell("repeated", 0));         assert.equal(app.wouldResolve(ref), false); assert.equal(app.refInvalid(ref), true);
  mk(cell("skipped", 0));          assert.equal(app.wouldResolve(ref), true);
  mk(cell("skipped", 15 * 3600));  assert.equal(app.refInvalid(ref), true);
  assert.equal(app.cellAt(app.state.work, ref).case, "skipped");
  assert.equal(app.parseUtcOff("+01:00"), 3600); assert.equal(app.parseUtcOff("-0530"), -19800);
  assert.equal(app.parseUtcOff("Z"), 0); assert.equal(app.parseUtcOff("+15:00"), null); assert.equal(app.parseUtcOff("one"), null);
  assert.equal(app.trueInstant("2026:10:25 02:30:00", 3600), "2026-10-25 01:30:00 UTC");
  // saved into photos-21 by its photo's path
  const p = app.savePayload([ref], (r) => app.cellAt(app.state.work, r), { time: "h" });
  assert.deepEqual(p.time, [{ dest: DEST, kind: "reading", key: rel, path: undefined, user_decision: { utc_offset_seconds: 15 * 3600 } }]);
});
