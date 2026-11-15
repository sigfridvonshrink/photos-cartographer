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

// Front-end unit tests for the questions of a camera's clock changed during the day (photos-21 clock_change), each
// answerable here, writing the decision field the record documents (decision-json-reference §4.4).
import { test } from "node:test";
import assert from "node:assert/strict";
import * as app from "../web/app.js";

const setWork = (work) => { app.state.work = work; app.state.base = JSON.parse(JSON.stringify(work)); };
const DEST = "6-photos-by-dest/Kyoto";

const runs = [{ offset_seconds: -3600, photos: 3, first: { source_file: `${DEST}/a.arw`, camera_source_naive_time: "2024:07:03 09:00:00" },
  last: { source_file: `${DEST}/c.arw`, camera_source_naive_time: "2024:07:03 10:00:00" } },
{ offset_seconds: -32400, photos: 3, first: { source_file: `${DEST}/d.arw`, camera_source_naive_time: "2024:07:03 21:30:00" },
  last: { source_file: `${DEST}/f.arw`, camera_source_naive_time: "2024:07:03 22:30:00" } }];
const change = { evidence: "gpx_self_anchor", runs, acceptance_tolerance_seconds: 120,
  between: [{ source_file: `${DEST}/q.arw`, camera_source_naive_time: "2024:07:03 11:30:00" }] };
const dayCell = () => ({ camera_group: "C", clock_change: JSON.parse(JSON.stringify(change)),
  proposal: { proposal_source: "gpx_self_anchor", proposed_offset_seconds: -3600 },
  user_decision: { accept_proposal: false, accepted_offset_seconds: "", manual_offset_seconds: "", accept_clock_change: false,
    accepted_change_offsets_seconds: "", first_after_change: "" }, requires_user_input: true });

test("a clock changed during the day: the split is accepted once, naming its offsets and, where asked, the first photo after", () => {
  const cell = dayCell();
  assert.equal(app.clockChangeHolds(cell), false);
  const on = { ...cell, user_decision: { ...cell.user_decision, ...app.clockChangeFields(cell, true) } };
  assert.deepEqual(on.user_decision.accepted_change_offsets_seconds, [-3600, -32400]);
  assert.equal(app.clockChangeHolds(on), false);                       // a photo lies between: which was first after?
  on.user_decision.first_after_change = "2024:07:03 11:30:00";
  assert.equal(app.clockChangeHolds(on), true);
  on.user_decision.first_after_change = "2024:07:03 21:30:00";         // none of them: the second run's first
  assert.equal(app.clockChangeAt(on), "2024:07:03 21:30:00");
  on.user_decision.first_after_change = "2024:07:03 08:00:00";         // not between the runs
  assert.equal(app.clockChangeHolds(on), false);
  const none = { ...on, clock_change: { ...change, between: [] }, user_decision: { ...on.user_decision, first_after_change: "" } };
  assert.equal(app.clockChangeHolds(none), true);                      // nothing to ask
  none.user_decision.accepted_change_offsets_seconds = [-3600, -36000];
  assert.equal(app.clockChangeHolds(none), false);                     // accepted for other offsets
  none.user_decision.accepted_change_offsets_seconds = [-3600, -32400];
  none.user_decision.manual_offset_seconds = -3600;                     // one offset written for the whole day outranks
  assert.equal(app.clockChangeHolds(none), false);
  assert.deepEqual(app.clockChangeFields(cell, false), { accept_clock_change: false, accepted_change_offsets_seconds: "", first_after_change: "" });
});

test("photos agreeing with no group: the interim sub-folder advice is gone — a split, a review, or another body", () => {
  const p = { conflicting_files: [`${DEST}/x.arw`], groups: [] };
  const plain = app.proposalNotes(p)[0];
  assert.doesNotMatch(plain, /sub-folder/);
  assert.match(plain, /GPS view/);
  assert.match(app.proposalNotes(p, { clock_change: change })[0], /clock changed/);
  assert.match(app.proposalNotes(p, { several_bodies: true })[0], /several bodies/);
});

test("an own position the agreed offset contradicts: kept unless the track's is taken, written as manual_lat/lon", () => {
  const rel = `${DEST}/stray.arw`, ref = { file: "gps", dest: DEST, kind: "review", path: rel };
  const item = { relative_path: rel, reason: "own_position_contradicted", own_position: { lat: 51.025, lon: 3.7 },
    proposed_position: { lat: 51.0125, lon: 3.7, method: "interpolated", gpx_file: "walk.gpx" }, apart_meters: 1390,
    user_decision: { manual_lat: "", manual_lon: "" }, requires_user_input: false };
  setWork({ gps: { destinations: { [DEST]: { gps_decisions: { review_items: [item] } } } } });
  assert.equal(app.wouldResolve(ref), true);                           // its own position kept: nothing waits
  assert.match(app.contradictedNote(item), /1390 m from where the track was/);
  assert.match(app.contradictedNote({ ...item, proposed_position: null }), /no track/);
  Object.assign(app.state.work.gps.destinations[DEST].gps_decisions.review_items[0].user_decision, app.takeTrackPosition(item));
  assert.deepEqual(app.cellAt(app.state.work, ref).user_decision, { manual_lat: 51.0125, manual_lon: 3.7 });
  assert.equal(app.refInvalid(ref), false);
});

test("a day offered the day next to it: accepted as any proposal, by the offset it names, then checked on the tracks", () => {
  const p = { proposal_source: "neighbour_day", proposed_offset_seconds: -3600,
    neighbour_day: { day: "2024-07-03", bucket: "C@2024-07-03" }, confidence: "review_required" };
  assert.match(app.neighbourDayNote(p), /3 Jul 2024/);
  assert.match(app.neighbourDayNote(p), /Drift view/);
  const cell = { proposal: p, user_decision: { ...app.acceptFields(p, true), manual_offset_seconds: "" } };
  assert.equal(app.acceptHolds(cell), true);
  assert.equal(app.acceptHolds({ ...cell, user_decision: { ...cell.user_decision, accepted_offset_seconds: -3601 } }), false);
});

test("the split resolves the day's offset cell, and its parts are shown on their day, never as rows of their own", () => {
  const cell = dayCell();
  Object.assign(cell.user_decision, app.clockChangeFields(cell, true, "2024:07:03 11:30:00"));
  setWork({ time: { destinations: { [DEST]: { camera_group_time_decisions: { C: cell,
    "C#1": { camera_group: "C", clock_change_part: { of: "C", part: 1 }, user_decision: {} } } } } } });
  const ref = { file: "time", dest: DEST, kind: "offset", key: "C" };
  assert.equal(app.wouldResolve(ref), true);
  const groups = app.offsetGroups(app.state.work.time.destinations[DEST]);
  assert.deepEqual(groups[0].buckets.map((b) => b.key), ["C"]);
});
