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

// --- picking a correction group (a place visited on several days, RUL-revisit_matched_to_its_day) ---
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


test("zoneContradiction: why an inherited zone is not taken", () => {
  assert.equal(app.zoneContradiction({}), "");
  const note = app.zoneContradiction({ contradicted_by: { photos: 2, example: "6-photos-by-dest/Iberia/Madrid/c.jpg",
    recorded_offset_seconds: 7200, timezone: "Europe/Lisbon", timezone_offset_seconds: 3600 } });
  assert.match(note, /2 photos here record \+2h 00m from UTC/);
  assert.match(note, /Europe\/Lisbon was at \+1h 00m then/);
});

test("offsetCellNotes: a shared offset, a guess checked on the tracks, one clock read two ways", () => {
  assert.deepEqual(app.offsetCellNotes({ proposal: { proposal_source: "gpx_self_anchor" } }), []);
  const shared = app.offsetCellNotes({ proposal: { proposal_source: "same_day_elsewhere", proposed_offset_seconds: -7200,
    confidence: "review_required", shared_from: { destination: "6-photos-by-dest/Museum", bucket: "K" } } });
  assert.match(shared[0], /fixed its clock that day in 6-photos-by-dest\/Museum.*accept it here/);
  assert.match(app.offsetCellNotes({ proposal: { proposal_source: "timezone_naive" },
    effective_time_anchor: { offset_seconds: -7200, source: "timezone_unconfirmed" } })[0], /Drift view/);
  assert.match(app.offsetCellNotes({ conflicts_with: [{ destination: "6-photos-by-dest/Other", bucket: "K", offset_seconds: -6600 }] })[0],
    /6-photos-by-dest\/Other — one clock, two readings/);
  // the other side is the user's choice: named as theirs, not as what the GPS gives
  const theirs = app.offsetCellNotes({ conflicts_with: [{ destination: "6-photos-by-dest/Castle", bucket: "K", offset_seconds: -6600, chosen: true }] });
  assert.match(theirs[0], /^You chose .* in 6-photos-by-dest\/Castle .*change your choice there/);
  assert.doesNotMatch(theirs[0], /camera's GPS gives/);
  // this cell is the user's choice: it stands, the GPS's own reading waits
  const mine = app.offsetCellNotes({ effective_time_anchor: { offset_seconds: -6600, source: "gpx_anchor_chosen" },
    conflicts_with: [{ destination: "6-photos-by-dest/Trip", bucket: "K", offset_seconds: -7200, chosen: false }] });
  assert.match(mine[0], /by itself the same day in 6-photos-by-dest\/Trip, against the offset you chose here.*Your choice stands/);
});

test("offsetCellNotes: a recorded offset checked on the tracks, and photos recording different offsets", () => {
  assert.match(app.offsetCellNotes({ proposal: { proposal_source: "recorded_offset" },
    effective_time_anchor: { offset_seconds: -3600, source: "recorded_offset_unconfirmed" } })[0], /Drift view/);
  const differ = app.offsetCellNotes({ proposal: { proposal_source: "timezone_naive" }, recorded_offsets_differ: [
    { recorded_offset_seconds: 3600, photos: 1, example: "6-photos-by-dest/Kyoto/a.arw" },
    { recorded_offset_seconds: -18000, photos: 2, example: "6-photos-by-dest/Kyoto/b.arw" }] });
  assert.equal(differ.length, 1);
  assert.match(differ[0], /\+01:00 \(1 photo, e\.g\. a\.arw\), −05:00 \(2 photos, e\.g\. b\.arw\)/);
  assert.match(differ[0], /none is proposed from them/);
});

test("utcOff: a recorded UTC offset reads as it is written, sign, hours and minutes", () => {
  assert.equal(app.utcOff(3600), "+01:00");
  assert.equal(app.utcOff(-34200), "−09:30");
  assert.equal(app.utcOff(0), "+00:00");
  assert.equal(app.utcOff(20700), "+05:45");
});


test("zoneSpokenFor: a zone stands against the photos only on the user's word for every offset they record", () => {
  const k = { photos: 2, example: "x", recorded_offset_seconds: 7200, recorded_offsets: [7200, 32400],
    timezone: "Europe/Lisbon", timezone_offset_seconds: 3600 };
  assert.equal(app.zoneSpokenFor({}), true);
  assert.equal(app.zoneSpokenFor({ contradicted_by: k, user_decision: {} }), false);
  assert.equal(app.zoneSpokenFor({ contradicted_by: k, user_decision: { confirmed_despite_recorded_offsets: [7200] } }), false);
  assert.deepEqual(app.zoneDespiteFields({ contradicted_by: k }, true), { confirmed_despite_recorded_offsets: [7200, 32400] });
  assert.deepEqual(app.zoneDespiteFields({ contradicted_by: k }, false), { confirmed_despite_recorded_offsets: [] });
  assert.equal(app.zoneSpokenFor({ contradicted_by: k, user_decision: app.zoneDespiteFields({ contradicted_by: k }, true) }), true);
  // another zone picked since the run that checked: the next run checks that one
  assert.equal(app.zoneSpokenFor({ contradicted_by: k, user_decision: { manual_iana_timezone: "Europe/Madrid" } }), true);
  assert.equal(app.zoneSpokenFor({ contradicted_by: k, user_decision: { manual_iana_timezone: "Europe/Lisbon" } }), false);
});

test("ambiguousTimeNote: a camera time at a daylight-saving change is the user's to set", () => {
  assert.equal(app.ambiguousTimeNote(undefined), "");
  const skipped = app.ambiguousTimeNote({ camera_time: "2024:03:31 02:30:00", timezone: "Europe/Berlin", case: "skipped",
    offsets_seconds: [3600, 7200] });
  assert.match(skipped, /2024-03-31 02:30:00 falls at a daylight-saving change in Europe\/Berlin/);
  assert.match(skipped, /clocks went forward over it/);
  assert.match(skipped, /either −1h 00m 00s or −2h 00m 00s/);      // as clock offsets: camera + offset = UTC
  assert.match(skipped, /set the offset yourself/);
  assert.doesNotMatch(skipped, /derive/);
  const repeated = app.ambiguousTimeNote({ camera_time: "2024:10:27 02:30:00", timezone: "Europe/Berlin", case: "repeated",
    offsets_seconds: [7200, 3600] });
  assert.match(repeated, /clocks went back over it, so that time happened twice/);
  assert.match(repeated, /either −2h 00m 00s or −1h 00m 00s/);
});

test("zoneOffer: one click takes the proposed zone, never the zone the photos contradict", () => {
  const k = { timezone: "Europe/Lisbon", recorded_offsets: [7200] };
  assert.equal(app.zoneOffer({ proposed_iana_timezone: "Europe/Brussels", proposal_source: "config_default", user_decision: {} }), "Europe/Brussels");
  assert.equal(app.zoneOffer({ proposed_iana_timezone: "Asia/Tokyo", proposal_source: "inherited", user_decision: {} }), "");   // applies itself
  // inherited and contradicted: writing it resolves nothing — the keep-confirmation is the way to keep it
  assert.equal(app.zoneOffer({ proposed_iana_timezone: "Europe/Lisbon", proposal_source: "inherited", contradicted_by: k, user_decision: {} }), "");
  // the zone written here was contradicted; the proposal standing beside it is another zone, and may be taken
  assert.equal(app.zoneOffer({ proposed_iana_timezone: "Europe/Madrid", proposal_source: "inherited", contradicted_by: k, user_decision: {} }), "Europe/Madrid");
  assert.equal(app.zoneOffer({ proposed_iana_timezone: "Europe/Brussels", proposal_source: "config_default",
    user_decision: { manual_iana_timezone: "Asia/Tokyo" } }), "");
});

test("offsetCellNotes / fmtSpan: a guess far from all evidence says how far, and that accepting is not enough", () => {
  const notes = app.offsetCellNotes({ proposal: { proposal_source: "timezone_naive", proposed_offset_seconds: -3600,
    far_from_evidence: { max_clock_error_seconds: 172800, other_photos: 3, nearest_other_photo: "6-photos-by-dest/Bruges/p.heic",
      nearest_other_photo_seconds: 26.3 * 365.25 * 86400, nearest_track_seconds: "" } } });
  assert.equal(notes.length, 1);
  assert.match(notes[0], /26\.3 years from the nearest photo another device took here \(p\.heic\) — farther than a clock may be wrong \(2 days\)/);
  assert.match(notes[0], /Accepting it is not enough: give the true time of one of its photos/);
  assert.doesNotMatch(notes[0], /track point/);
  const withTrack = app.offsetCellNotes({ proposal: { far_from_evidence: { max_clock_error_seconds: 172800, other_photos: 1,
    nearest_other_photo: "p.heic", nearest_other_photo_seconds: 864000, nearest_track_seconds: 18000 } } });
  assert.match(withTrack[0], /10 days from .* and 5 hours from the nearest track point/);
  assert.equal(app.fmtSpan(90), "2 minutes");
  assert.equal(app.fmtSpan(-7200), "2 hours");
});
