// Front-end unit tests for the GPS-drift (photos-21a) scrub logic in web/app.js: the scrub→offset
// math, the seed-index placement, drift cell resolution/validation. Pure logic; some read the
// module-global `state` (set `app.state.work` first).
import { test } from "node:test";
import assert from "node:assert/strict";
import * as app from "../web/app.js";

const setWork = (work) => { app.state.work = work; app.state.base = work; };

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

test("wouldResolve(drift): confirmed (zero scrub or valid correction) resolves; bad/unconfirmed does not", () => {
  const dest = "6-photos-by-dest/D", key = "CAM", ref = { file: "drift", dest, kind: "drift", key };
  const mk = (ud) => setWork({ drift: { destinations: { [dest]: { drift_decisions: { [key]: { user_decision: ud, proposal: {} } } } } } });

  mk({ confirmed: true, corrected_offset_seconds: "" });        assert.equal(app.wouldResolve(ref), true);   // zero scrub
  mk({ confirmed: true, corrected_offset_seconds: -3600 });     assert.equal(app.wouldResolve(ref), true);   // correction
  mk({ confirmed: false, corrected_offset_seconds: "" });       assert.equal(app.wouldResolve(ref), false);  // inaction blocks
  mk({ confirmed: true, corrected_offset_seconds: 999999 });    assert.equal(app.wouldResolve(ref), false);  // out of range
});

test("refInvalid(drift): only an out-of-range correction is invalid", () => {
  const dest = "6-photos-by-dest/D", key = "CAM", ref = { file: "drift", dest, kind: "drift", key };
  const mk = (ud) => setWork({ drift: { destinations: { [dest]: { drift_decisions: { [key]: { user_decision: ud, proposal: {} } } } } } });
  mk({ confirmed: true, corrected_offset_seconds: "" });        assert.equal(app.refInvalid(ref), false);
  mk({ confirmed: true, corrected_offset_seconds: -7200 });     assert.equal(app.refInvalid(ref), false);
  mk({ confirmed: true, corrected_offset_seconds: 1e9 });       assert.equal(app.refInvalid(ref), true);
});

test("cellStatus(drift): unconfirmed needs input, confirmed resolves", () => {
  assert.deepEqual(app.cellStatus({ requires_user_input: true }), ["needs", "needs input"]);
  assert.deepEqual(app.cellStatus({ requires_user_input: false }), ["ok", "resolved"]);
});
