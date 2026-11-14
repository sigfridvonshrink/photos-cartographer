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

// Front-end unit tests for the per-date offset bucketing logic (web/app.js §4.4):
// offsetGroups (group by camera group, collapse equal-proposal undecided days), dateRange, peerKeys.
import { test } from "node:test";
import assert from "node:assert/strict";
import * as app from "../web/app.js";

const cell = (group, date, proposedOffset, ud = {}) => ({
  camera_group: group,
  ...(date ? { date } : {}),
  proposal: proposedOffset == null ? { proposal_source: "manual_required" }
    : { proposal_source: "timezone_naive", proposed_offset_seconds: proposedOffset, proposed_from_timezone: "Europe/Brussels" },
  user_decision: ud,
});

test("offsetGroups: single-day common case stays one bare bucket, no date", () => {
  const g = app.offsetGroups({ camera_group_time_decisions: { "CAM": cell("CAM", null, null) } });
  assert.equal(g.length, 1);
  assert.equal(g[0].dated, false);
  assert.equal(g[0].buckets.length, 1);
  assert.equal(g[0].buckets[0].date, null);
});

test("offsetGroups: equal-proposal days collapse, distinct proposals split (summer/winter)", () => {
  const cells = {
    "CAM@2024-07-03": cell("CAM", "2024-07-03", -7200),
    "CAM@2024-07-04": cell("CAM", "2024-07-04", -7200),
    "CAM@2024-12-22": cell("CAM", "2024-12-22", -3600),
  };
  const g = app.offsetGroups({ camera_group_time_decisions: cells });
  assert.equal(g.length, 1);                    // one camera group
  assert.equal(g[0].dated, true);
  assert.equal(g[0].proposals.length, 2);       // summer cluster + winter cluster
  const summer = g[0].proposals.find((p) => p.offset === -7200);
  assert.deepEqual(summer.keys, ["CAM@2024-07-03", "CAM@2024-07-04"]);
  assert.deepEqual(summer.dates, ["2024-07-03", "2024-07-04"]);
  assert.equal(summer.source, "timezone_naive");
  assert.equal(summer.tz, "Europe/Brussels");
  assert.equal(g[0].proposals.find((p) => p.offset === -3600).keys.length, 1);
});

test("offsetGroups: a day with its own decision is NOT pooled with equal-proposal peers", () => {
  const cells = {
    "CAM@2024-07-03": cell("CAM", "2024-07-03", -7200),
    "CAM@2024-07-04": cell("CAM", "2024-07-04", -7200, { manual_offset_seconds: -7200 }),
  };
  const g = app.offsetGroups({ camera_group_time_decisions: cells });
  assert.equal(g[0].proposals.length, 2);       // the decided day breaks out of the cluster
  assert.ok(g[0].proposals.every((p) => p.keys.length === 1));
});

test("offsetGroups: equal-proposal days that share an identical decision stay clustered", () => {
  const cells = {                                  // both summer days accepted → one cluster, still collapsed
    "CAM@2024-07-03": cell("CAM", "2024-07-03", -7200, { accept_proposal: true, manual_offset_seconds: "" }),
    "CAM@2024-07-04": cell("CAM", "2024-07-04", -7200, { accept_proposal: true, manual_offset_seconds: "" }),
  };
  const g = app.offsetGroups({ camera_group_time_decisions: cells });
  assert.equal(g[0].proposals.length, 1);
  assert.deepEqual(g[0].proposals[0].keys, ["CAM@2024-07-03", "CAM@2024-07-04"]);
});

test("offsetGroups: same accept decision but DIFFERENT proposals do not merge", () => {
  const cells = {                                  // accepting summer (-7200) vs winter (-3600) stay separate
    "CAM@2024-07-03": cell("CAM", "2024-07-03", -7200, { accept_proposal: true }),
    "CAM@2024-12-22": cell("CAM", "2024-12-22", -3600, { accept_proposal: true }),
  };
  const g = app.offsetGroups({ camera_group_time_decisions: cells });
  assert.equal(g[0].proposals.length, 2);
});

test("offsetGroups: separate camera groups never merge", () => {
  const cells = {
    "CAM@2024-07-03": cell("CAM", "2024-07-03", -7200),
    "OTHER@2024-07-03": cell("OTHER", "2024-07-03", -7200),
  };
  const g = app.offsetGroups({ camera_group_time_decisions: cells });
  assert.deepEqual(g.map((x) => x.group), ["CAM", "OTHER"]);
});

test("offsetGroups: no-proposal days cluster together as one 'needs input' group", () => {
  const cells = {
    "CAM@2024-07-03": cell("CAM", "2024-07-03", null),
    "CAM@2024-07-04": cell("CAM", "2024-07-04", null),
  };
  const g = app.offsetGroups({ camera_group_time_decisions: cells });
  assert.equal(g[0].proposals.length, 1);
  assert.equal(g[0].proposals[0].offset, null);
  assert.equal(g[0].proposals[0].keys.length, 2);
});

test("dateRange: single, range", () => {
  assert.equal(app.dateRange(["2024-07-03"]), "3 Jul 2024");
  assert.equal(app.dateRange(["2024-07-03", "2024-07-04", "2024-12-22"]), "3 Jul 2024 … 22 Dec 2024 (3 days)");
  assert.equal(app.dateRange([]), "");
});

test("peerKeys: cluster ref fans out to its peers, plain ref to itself", () => {
  assert.deepEqual(app.peerKeys({ key: "A", peers: ["A", "B", "C"] }), ["A", "B", "C"]);
  assert.deepEqual(app.peerKeys({ key: "A" }), ["A"]);
});

// --- picking a correction group (a place visited on several days, §19.2) ----------------------------
test("groupChoice: the recommended group accepts the proposal, another sets its offset", () => {
  const p = { proposed_offset_seconds: -7200, groups: [{ offset_seconds: -7200, count: 3 }, { offset_seconds: -93600, count: 3 }] };
  assert.deepEqual(app.groupChoice(p, p.groups[0]), { accept_proposal: true, accepted_offset_seconds: -7200, manual_offset_seconds: "" });
  assert.deepEqual(app.groupChoice(p, p.groups[1]), { accept_proposal: false, accepted_offset_seconds: "", manual_offset_seconds: -93600 });
  assert.equal(app.chosenOffset(p, { accept_proposal: true, accepted_offset_seconds: -7200, manual_offset_seconds: "" }), -7200);
  assert.equal(app.chosenOffset(p, { accept_proposal: false, manual_offset_seconds: -93600 }), -93600);
  assert.equal(app.chosenOffset(p, { accept_proposal: false, manual_offset_seconds: "" }), null);
});

test("proposalNotes: a tie asks for the day; disagreeing photos are named, five at most", () => {
  const tied = { tied: true, groups: [{ offset_seconds: -7200, count: 3 }, { offset_seconds: -93600, count: 3 }, { offset_seconds: 0, count: 1 }] };
  assert.deepEqual(app.proposalNotes(tied), ["These photos lie on 2 visits of the tracks equally — pick the day you were there."]);
  const files = ["a", "b", "c", "d", "e", "f", "g"].map((x) => `6-photos-by-dest/B/${x}.jpg`);
  const [note] = app.proposalNotes({ tied: false, groups: [], conflicting_files: files });
  assert.match(note, /^7 photos agree with none of these: 6-photos-by-dest\/B\/a\.jpg, .*e\.jpg and 2 more\./);
  assert.match(app.proposalNotes({ conflicting_files: [files[0]] })[0], /^1 photo agrees with none of these/);
  assert.deepEqual(app.proposalNotes({ tied: false, groups: [], conflicting_files: [] }), []);
});

// --- what the editor says about evidence that settles nothing -----------------------------------------
test("proposalNotes: a stay of the tracks is said to fix no time", () => {
  const notes = app.proposalNotes({ proposed_offset_seconds: -2740, imprecise_seconds: 3595, groups: [] });
  assert.equal(notes.length, 1);
  assert.match(notes[0], /where but not when/);
});

test("acceptFields: an acceptance names the offset it accepts; clearing it clears both", () => {
  assert.deepEqual(app.acceptFields({ proposed_offset_seconds: -7200 }, true), { accept_proposal: true, accepted_offset_seconds: -7200 });
  assert.deepEqual(app.acceptFields({ proposed_offset_seconds: -7200 }, false), { accept_proposal: false, accepted_offset_seconds: "" });
});

test("tracksNote: why the tracks placed nothing, in one line", () => {
  assert.equal(app.tracksNote(undefined), "");
  assert.match(app.tracksNote({ reason: "outside_track", seconds_from_track: 3600 }), /1 h from this photo/);
  assert.match(app.tracksNote({ reason: "track_gap", gap_seconds: 2400, seconds_from_track: 900 }), /40 min gap.*15 min away/);
  assert.match(app.tracksNote({ reason: "tracks_disagree", gpx_files: ["a.gpx", "b.gpx"], apart_meters: 5560 }), /a\.gpx and b\.gpx.*5560 m apart/);
});
