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
