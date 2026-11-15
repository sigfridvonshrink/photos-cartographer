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
