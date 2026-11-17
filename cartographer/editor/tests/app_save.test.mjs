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

// The save's body carries back the hashes of the decision records as loaded, so the server can refuse a save
// made from records that have changed since (RUL-save_only_what_was_shown). Run with `tools/jstest`.
import { test } from "node:test";
import assert from "node:assert/strict";
import * as app from "../web/app.js";

test("savePayload groups the edits by record and carries the loaded hashes", () => {
  const cells = { a: { user_decision: { manual_iana_timezone: "Asia/Tokyo" } }, b: { user_decision: { accept_proposal: true } } };
  const refs = [
    { file: "time", dest: "6-photos-by-dest/Japan", kind: "timezone", id: "a" },
    { file: "gps", dest: "6-photos-by-dest/Japan", kind: "review", path: "6-photos-by-dest/Japan/x.arw", id: "b" },
  ];
  const hashes = { time: "t1", drift: null, gps: "g1" };
  const p = app.savePayload(refs, (r) => cells[r.id], hashes);
  assert.deepEqual(p.hashes, hashes);
  assert.notEqual(p.hashes, hashes);                       // a copy, not the page's own object
  assert.deepEqual(p.time, [{ dest: "6-photos-by-dest/Japan", kind: "timezone", key: undefined, path: undefined,
                              user_decision: { manual_iana_timezone: "Asia/Tokyo" } }]);
  assert.equal(p.drift.length, 0);
  assert.equal(p.gps[0].path, "6-photos-by-dest/Japan/x.arw");
});

test("a photos-25 fingerprint mismatch: asked until accepted, saved into photos-25 by its photo's path", () => {
  const rel = "6-photos-by-dest/Japan/x.arw", ref = { file: "execution", kind: "fingerprint", path: rel };
  const m = (ud, actual = "b".repeat(64)) => ({ relative_path: rel, expected_fingerprint: "a".repeat(64), actual_fingerprint: actual, user_decision: ud });
  const work = { execution: { plan_id: "p1", fingerprint_mismatches: [m({ accept_fingerprint_change: false })] } };
  app.state.work = work; app.state.base = JSON.parse(JSON.stringify(work));
  assert.equal(app.cellAt(work, ref).actual_fingerprint, "b".repeat(64));
  assert.deepEqual(app.cellStatus(app.cellAt(work, ref)), ["needs", "needs input"]);
  assert.equal(app.wouldResolve(ref), false);
  work.execution.fingerprint_mismatches[0].user_decision.accept_fingerprint_change = true;
  assert.equal(app.wouldResolve(ref), true);
  assert.equal(app.isDirty(ref), true);
  assert.equal(app.refInvalid(ref), false);
  assert.equal(app.mismatchAccepted(m({ accept_fingerprint_change: true }, null)), false);   // no fingerprint taken: nothing to accept
  const p = app.savePayload([ref], (r) => app.cellAt(app.state.work, r), { execution: "e1" });
  assert.deepEqual(p.execution, [{ dest: undefined, kind: "fingerprint", key: undefined, path: rel,
    user_decision: { accept_fingerprint_change: true } }]);
});

test("a new camera group: asked until classed as one of the two device_groups arrays, saved under cameras by its key", () => {
  const key = "Apple|iPhone 15", ref = { file: "cameras", kind: "camera", key };
  const work = { cameras: { groups: { [key]: { files: 3, examples: ["6-photos-by-dest/A/1.heic"], identity: { Make: "Apple" },
    user_decision: { device_class: "" }, requires_user_input: true } } } };
  app.state.work = work; app.state.base = JSON.parse(JSON.stringify(work));
  assert.deepEqual(app.cellStatus(app.cellAt(work, ref)), ["needs", "needs input"]);
  assert.equal(app.wouldResolve(ref), false);
  assert.equal(app.refInvalid(ref), false);
  work.cameras.groups[key].user_decision.device_class = "phones";
  assert.equal(app.wouldResolve(ref), true);
  work.cameras.groups[key].user_decision.device_class = "phone";
  assert.equal(app.refInvalid(ref), true);                          // only the two arrays' names
  work.cameras.groups[key].user_decision.device_class = "fixed_clock_cameras";
  assert.deepEqual(app.DEVICE_CLASSES, ["phones", "fixed_clock_cameras"]);
  const p = app.savePayload([ref], (r) => app.cellAt(app.state.work, r), { cameras: "c1" });
  assert.deepEqual(p.cameras, [{ dest: undefined, kind: "camera", key, path: undefined, user_decision: { device_class: "fixed_clock_cameras" } }]);
});

test("a fixed-clock camera group: one camera or several bodies, a setting never waiting, saved under cameras by its key", () => {
  const key = "Sony|ILCE-6400|", ref = { file: "cameras", kind: "bodies", key };
  const work = { cameras: { groups: {}, bodies: { [key]: { files: 2, examples: ["6-photos-by-dest/A/1.arw"], identity: { Make: "Sony" },
    user_decision: { several_bodies: false }, requires_user_input: false } } } };
  app.state.work = work; app.state.base = JSON.parse(JSON.stringify(work));
  assert.equal(app.cellAt(work, ref), work.cameras.bodies[key]);
  assert.equal(app.cellAt(work, { ...ref, kind: "camera" }), null);   // not a question of class
  assert.deepEqual(app.cellStatus(app.cellAt(work, ref)), ["ok", "resolved"]);
  assert.equal(app.refInvalid(ref), false);
  work.cameras.bodies[key].user_decision.several_bodies = true;
  assert.equal(app.wouldResolve(ref), true);
  assert.equal(app.isDirty(ref), true);
  work.cameras.bodies[key].user_decision.several_bodies = "yes";
  assert.equal(app.refInvalid(ref), true);                          // true or false, nothing else
  work.cameras.bodies[key].user_decision.several_bodies = true;
  const p = app.savePayload([ref], (r) => app.cellAt(app.state.work, r), { cameras: "c1" });
  assert.deepEqual(p.cameras, [{ dest: undefined, kind: "bodies", key, path: undefined, user_decision: { several_bodies: true } }]);
});

test("a time changed since geotag wrote it: keep it or take back geotag's, the answer naming the time it is for", () => {
  const dest = "6-photos-by-dest/T", key = `${dest}/a.arw`, ref = { file: "time", dest, kind: "changed", key };
  const held = { DateTimeOriginal: "2024:07:03 14:45:00", OffsetTimeOriginal: "+02:00" };
  const cell = (ud, h = held) => ({ held_time: h, geotag_wrote: { DateTimeOriginal: "2024:07:03 14:30:00", OffsetTimeOriginal: "+02:00" },
    own_time: { DateTimeOriginal: "2024:07:03 14:20:00", OffsetTimeOriginal: null }, user_decision: ud, requires_user_input: true });
  const mk = (c) => { app.state.work = { time: { destinations: { [dest]: { changed_times: { [key]: c } } } } }; app.state.base = app.state.work; };
  mk(cell({ keep: "", answered_for: "" }));
  assert.equal(app.wouldResolve(ref), false);
  assert.deepEqual(app.changedFields(cell({}), "new"), { keep: "new", answered_for: held });
  mk(cell(app.changedFields(cell({}), "new")));                 assert.equal(app.wouldResolve(ref), true);
  mk(cell(app.changedFields(cell({}), "geotag")));              assert.equal(app.wouldResolve(ref), true);
  mk(cell({ keep: "new", answered_for: { ...held, DateTimeOriginal: "2024:07:03 14:40:00" } }));
  assert.equal(app.wouldResolve(ref), false);                                       // answered for another time
  mk(cell({ keep: "new", answered_for: { DateTimeOriginal: null, OffsetTimeOriginal: null } }, { DateTimeOriginal: null, OffsetTimeOriginal: null }));
  assert.equal(app.wouldResolve(ref), false);                                       // no time to keep
  mk(cell({ keep: "both", answered_for: held }));               assert.equal(app.refInvalid(ref), true);
  const p = app.savePayload([ref], (r) => app.cellAt(app.state.work, r), { time: "h" });
  assert.equal(p.time[0].kind, "changed");
  assert.equal(p.time[0].key, key);
});

test("a changed time's keep says it is the true local time, and an offset tag the zone does not give is noted", () => {
  const held = { DateTimeOriginal: "2024:07:03 14:45:00", OffsetTimeOriginal: "+09:00" };
  assert.match(app.changedKeepLabel({ held_time: held }), /^keep 2024:07:03 14:45:00 \+09:00 — this is the true local time/);
  assert.match(app.changedKeepLabel({ held_time: held }), /no camera clock offset applied/);
  assert.equal(app.keptTagNote({ held_time: held }), "");
  const note = app.keptTagNote({ held_time: held, offset_tag_disagrees: { recorded_offset_seconds: 32400,
    timezone: "Europe/Brussels", timezone_offsets_seconds: [7200] } });
  assert.match(note, /^Its offset tag says \+09:00, but Europe\/Brussels is \+02:00 at that time\./);
  assert.match(app.keptTagNote({ offset_tag_disagrees: { recorded_offset_seconds: 0, timezone: "Europe/Brussels",
    timezone_offsets_seconds: [7200, 3600] } }), /is \+02:00 or \+01:00/);
});

test("recordAbsentText: a record that does not parse is shown as that error, never as no file", () => {
  const err = { _error: "could not read photos-21-time-decisions.json: Expecting value: line 3 column 1 (char 7)" };
  const said = app.recordAbsentText(err, "photos-21-time-decisions.json");
  assert.match(said, /Expecting value: line 3 column 1/);
  assert.doesNotMatch(said, /^No /);
  assert.match(app.recordAbsentText(null, "photos-21-time-decisions.json"), /^No photos-21-time-decisions\.json yet/);
  assert.match(app.recordAbsentText({}, "photos-22-gps-drift-validation.json"), /^No photos-22-gps-drift-validation\.json yet/);
});

test("savePayload with no hashes loaded sends none, which the server refuses", () => {
  assert.deepEqual(app.savePayload([], () => ({}), undefined).hashes, {});
});

test("loadRefusal: a refused load says why; a loaded one says nothing", () => {
  assert.equal(app.loadRefusal(200, { workspace: "/w", demo: false, time: {} }), "");
  // the console's Edit tab refuses a sealed / uninitialized / already-open workspace with 409 {ok:false,error}
  assert.equal(app.loadRefusal(409, { ok: false, error: "workspace is sealed (already merged): the decision editor will not open it" }),
    "workspace is sealed (already merged): the decision editor will not open it");
  assert.match(app.loadRefusal(409, { ok: false }), /HTTP 409/);
  assert.match(app.loadRefusal(500, {}), /could not be loaded \(HTTP 500\)/);
});

test("hasUnsavedEdits: an edit not yet saved, never in demo mode or before anything loaded", () => {
  const dest = "6-photos-by-dest/Japan";
  const arts = (tz, demo = false) => ({ demo, time: { destinations: { [dest]: { destination_timezone: { user_decision: { manual_iana_timezone: tz } } } } } });
  app.state.base = null; app.state.work = null;
  assert.equal(app.hasUnsavedEdits(), false);              // refused or still loading
  app.state.base = arts(""); app.state.work = arts("");
  assert.equal(app.hasUnsavedEdits(), false);
  app.state.work = arts("Asia/Tokyo");
  assert.equal(app.hasUnsavedEdits(), true);
  app.state.base = arts("", true); app.state.work = arts("Asia/Tokyo", true);
  assert.equal(app.hasUnsavedEdits(), false);              // demo edits cannot be saved
});

test("a changed time: keep is no answer where the photo holds no time geotag reads", () => {
  const garbled = { DateTimeOriginal: "garbage", OffsetTimeOriginal: "+02:00" };
  const cell = (h) => ({ held_time: h, user_decision: { keep: "new", answered_for: { ...h } } });
  assert.equal(app.heldTimeKeepable(cell(garbled)), false);
  assert.equal(app.changedHolds(cell(garbled)), false);                             // geotag: a blocker, no time to keep
  const read = { DateTimeOriginal: "2024:07:03 14:45:00", OffsetTimeOriginal: "+02:00" };
  assert.equal(app.heldTimeKeepable(cell(read)), true);
  assert.equal(app.changedHolds(cell(read)), true);
  assert.equal(app.changedHolds({ ...cell(garbled), user_decision: { keep: "geotag", answered_for: { ...garbled } } }), true);
});

test("recordAbsentText: an absent record says what writes it", () => {
  for (const name of ["photos-21-time-decisions.json", "photos-22-gps-drift-validation.json", "photos-23-gps-decisions.json"]) {
    const said = app.recordAbsentText(null, name);
    assert.match(said, /geotag plan/, said);
    assert.match(said, /reload\.$/, said);
  }
  assert.match(app.recordAbsentText(null, "photos-00-config.json"), /prep plan/);
  assert.equal(app.recordAbsentText(null, "photos-99-other.json"), "No photos-99-other.json.");
});
