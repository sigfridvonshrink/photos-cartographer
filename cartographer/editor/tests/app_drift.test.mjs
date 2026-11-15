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

// Front-end unit tests for the GPS-drift (photos-21a) scrub logic in web/app.js: the scrub→offset
// math, the seed-index placement, drift cell resolution/validation. Pure logic; some read the
// module-global `state` (set `app.state.work` first).
import { test } from "node:test";
import assert from "node:assert/strict";
import * as app from "../web/app.js";

const setWork = (work) => { app.state.work = work; app.state.base = work; };
const TRIP = [{ gpx_file: "trip.gpx", sha256: "a".repeat(64) }];   // the tracks a drift cell shows

test("scrubOffset = (chosen track UTC) − (photo camera-naive), in seconds", () => {
  const frame = { camera_naive: "2024:07:03 14:00:00" };
  // photo's true position at 12:00:00Z -> offset −7200 (camera ran 2h ahead of UTC)
  assert.equal(app.scrubOffset({ time_utc: "2024-07-03T12:00:00Z" }, frame), -7200);
  assert.equal(app.scrubOffset({ time_utc: "2024-07-03T14:00:00Z" }, frame), 0);
  assert.equal(app.scrubOffset({ time_utc: "2024-07-03T15:30:00Z" }, frame), 5400);
  // malformed inputs -> null (no decision written)
  assert.equal(app.scrubOffset({ time_utc: "nope" }, frame), null);
  assert.equal(app.scrubOffset({ time_utc: "2024-07-03T12:00:00Z" }, { camera_naive: "" }), null);
});

test("scrubSeedIndex lands on the track point implied by the current offset", () => {
  const frame = { camera_naive: "2024:07:03 14:00:00" };
  const track = [
    { time_utc: "2024-07-03T11:58:00Z" }, { time_utc: "2024-07-03T12:00:00Z" },
    { time_utc: "2024-07-03T12:02:00Z" }, { time_utc: "2024-07-03T12:04:00Z" },
  ];
  // current offset −7200 -> photo sits at 12:00:00Z -> index 1
  assert.equal(app.scrubSeedIndex(track, frame, -7200), 1);
  // current offset −7320 (=−2h02m) -> 11:58:00Z -> index 0
  assert.equal(app.scrubSeedIndex(track, frame, -7320), 0);
  // empty / bad inputs -> 0
  assert.equal(app.scrubSeedIndex([], frame, -7200), 0);
  assert.equal(app.scrubSeedIndex(track, frame, null), 0);
});

test("wouldResolve(drift): confirmed for this offset (zero scrub or valid correction) resolves; else not", () => {
  const dest = "6-photos-by-dest/D", key = "CAM", ref = { file: "drift", dest, kind: "drift", key };
  const mk = (ud) => setWork({ drift: { destinations: { [dest]: { drift_decisions: { [key]: {
    user_decision: { confirmed_offset_seconds: -7200, confirmed_against_tracks: TRIP, ...ud },
    proposal: { current_offset_seconds: -7200, tracks: TRIP } } } } } } });

  mk({ confirmed: true, corrected_offset_seconds: "" });        assert.equal(app.wouldResolve(ref), true);   // zero scrub
  mk({ confirmed: true, corrected_offset_seconds: -3600 });     assert.equal(app.wouldResolve(ref), true);   // correction
  mk({ confirmed: false, corrected_offset_seconds: "" });       assert.equal(app.wouldResolve(ref), false);  // inaction blocks
  mk({ confirmed: true, corrected_offset_seconds: 12.5 });      assert.equal(app.wouldResolve(ref), false);  // not whole seconds
  mk({ confirmed: true, corrected_offset_seconds: "", confirmed_offset_seconds: 0 });
  assert.equal(app.wouldResolve(ref), false);                                                                 // another offset's
  mk({ confirmed: true, corrected_offset_seconds: "", confirmed_offset_seconds: "" });
  assert.equal(app.wouldResolve(ref), false);                                                                 // names none
  mk({ confirmed: true, corrected_offset_seconds: "", confirmed_against_tracks: undefined });
  assert.equal(app.wouldResolve(ref), false);                                                                 // names no tracks
});

test("driftConfirmFields: confirming names the offset and the tracks shown; unconfirming clears both", () => {
  const c = { user_decision: {}, proposal: { current_offset_seconds: -5400, tracks: TRIP } };
  assert.deepEqual(app.driftConfirmFields(c, true),
    { confirmed: true, confirmed_offset_seconds: -5400, confirmed_against_tracks: TRIP });
  assert.deepEqual(app.driftConfirmFields(c, false),
    { confirmed: false, confirmed_offset_seconds: "", confirmed_against_tracks: [] });
  const ud = app.driftConfirmFields(c, true);
  assert.equal(app.driftConfirmHolds({ ...c, user_decision: ud }), true);
  assert.equal(app.driftConfirmHolds({ ...c, user_decision: { ...ud, confirmed_offset_seconds: 0 } }), false);
  assert.equal(app.driftStaleReason({ ...c, user_decision: { ...ud, confirmed_offset_seconds: 0 } }), "offset");
  assert.equal(app.driftStaleReason({ ...c, user_decision: ud }), null);
});

test("driftConfirmHolds: a confirmation holds only while the tracks it names stand (RUL-confirmation_rests_on_its_tracks)", () => {
  const ud = { confirmed: true, confirmed_offset_seconds: -7200, corrected_offset_seconds: "", confirmed_against_tracks: TRIP };
  const cell = (tracks, extra = {}) => ({ user_decision: ud, proposal: { current_offset_seconds: -7200, tracks }, ...extra });
  assert.equal(app.driftConfirmHolds(cell(TRIP)), true);
  // the track shown is another export of the day: its SHA-256 differs
  const redone = [{ gpx_file: "trip.gpx", sha256: "b".repeat(64) }];
  assert.equal(app.driftConfirmHolds(cell(redone)), false);
  assert.equal(app.driftStaleReason(cell(redone)), "tracks");
  // a track added beside the one named leaves it standing
  assert.equal(app.driftConfirmHolds(cell([...TRIP, { gpx_file: "other.gpx", sha256: "c".repeat(64) }])), true);
  // named but no longer shown: what geotag found under gpx_root decides
  const other = [{ gpx_file: "other.gpx", sha256: "c".repeat(64) }];
  assert.equal(app.driftConfirmHolds(cell(other, { confirmed_tracks_changed: [] })), true);
  assert.equal(app.driftConfirmHolds(cell(other, { confirmed_tracks_changed: ["trip.gpx"] })), false);
  // confirming again names the tracks shown now, which hold whatever geotag found of the old ones
  const again = cell(redone, { confirmed_tracks_changed: ["trip.gpx"] });
  again.user_decision = { ...ud, ...app.driftConfirmFields(again, true) };
  assert.equal(app.driftConfirmHolds(again), true);
  // a confirmation without the tracks field confirms nothing
  assert.equal(app.driftConfirmHolds({ ...cell(TRIP), user_decision: { ...ud, confirmed_against_tracks: undefined } }), false);
});

test("driftConfirmHolds: one made with no track shown holds only while none is (RUL-trackless_confirmation_holds_while_none)", () => {
  const ud = { confirmed: true, confirmed_offset_seconds: -7200, corrected_offset_seconds: "", confirmed_against_tracks: [] };
  assert.equal(app.driftConfirmHolds({ user_decision: ud, proposal: { current_offset_seconds: -7200, tracks: [] } }), true);
  assert.equal(app.driftConfirmHolds({ user_decision: ud, proposal: { current_offset_seconds: -7200, tracks: TRIP } }), false);
});

test("refInvalid(drift): only a correction that is not whole seconds is invalid", () => {
  const dest = "6-photos-by-dest/D", key = "CAM", ref = { file: "drift", dest, kind: "drift", key };
  const mk = (ud) => setWork({ drift: { destinations: { [dest]: { drift_decisions: { [key]: { user_decision: ud, proposal: {} } } } } } });
  mk({ confirmed: true, corrected_offset_seconds: "" });        assert.equal(app.refInvalid(ref), false);
  mk({ confirmed: true, corrected_offset_seconds: -7200 });     assert.equal(app.refInvalid(ref), false);
  mk({ confirmed: true, corrected_offset_seconds: 1e9 });       assert.equal(app.refInvalid(ref), false);  // any size
  mk({ confirmed: true, corrected_offset_seconds: 0.25 });      assert.equal(app.refInvalid(ref), true);
});

test("cellStatus(drift): unconfirmed needs input, confirmed resolves", () => {
  assert.deepEqual(app.cellStatus({ requires_user_input: true }), ["needs", "needs input"]);
  assert.deepEqual(app.cellStatus({ requires_user_input: false }), ["ok", "resolved"]);
});

test("driftCorrectionFields: a correction typed for a bucket with no track confirms it, and resolves it", () => {
  // a bucket no track lies by: nothing to scrub along, so the correction is typed (or given as a photo's true time)
  const dest = "6-photos-by-dest/D", key = "CAM", ref = { file: "drift", dest, kind: "drift", key };
  const cell = { proposal: { current_offset_seconds: -7200, frames: [{ source_file: "a.arw", camera_naive: "2024:07:03 14:00:00" }],
    track_segment: [], tracks: [] }, user_decision: { confirmed: false, corrected_offset_seconds: "", confirmed_offset_seconds: "",
    confirmed_against_tracks: [] } };
  const typed = app.driftCorrectionFields(cell, -3600);
  assert.deepEqual(typed, { confirmed: true, confirmed_offset_seconds: -7200, confirmed_against_tracks: [], corrected_offset_seconds: -3600 });
  setWork({ drift: { destinations: { [dest]: { drift_decisions: { [key]: { ...cell, user_decision: typed } } } } } });
  assert.equal(app.wouldResolve(ref), true);
  // the offset a photo's true time gives, as the typed field computes it: true time − camera time
  assert.equal(app.offsetFromTrueTime("2024:07:03 14:00:00", "2024-07-03T13:00:00", ""), -3600);
});
