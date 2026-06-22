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

// Front-end unit tests for the editor's status + resolution + inheritance-preview logic (web/app.js).
// These read the module-global `state`, so each test sets app.state.work first.
import { test } from "node:test";
import assert from "node:assert/strict";
import * as app from "../web/app.js";

const setWork = (work) => { app.state.work = work; app.state.base = work; };

test("cellStatus maps the system flags", () => {
  assert.deepEqual(app.cellStatus({ requires_user_input: true }), ["needs", "needs input"]);
  assert.deepEqual(app.cellStatus({ stale_user_decision: true }), ["stale", "stale"]);
  assert.deepEqual(app.cellStatus({ decision_mode: "auto_resolved" }), ["auto", "auto"]);
  assert.deepEqual(app.cellStatus({}), ["ok", "resolved"]);
  assert.equal(app.cellStatus(null), null);
  // The optional folder fallback: "resolved" only with an effective value, else "none" (not resolved).
  assert.deepEqual(app.cellStatus({ effective_fallback: { lat: 1, lon: 2 } }), ["ok", "resolved"]);
  assert.deepEqual(app.cellStatus({ effective_fallback: null }), ["none", "none"]);
});

test("wouldResolve: each of the three offset modes is independently sufficient", () => {
  const dest = "6-photos-by-dest/B", key = "CAM", ref = { file: "time", dest, kind: "offset", key };
  const mk = (ud, proposal = {}) => setWork(
    { time: { destinations: { [dest]: { camera_group_time_decisions: { [key]: { user_decision: ud, proposal } } } } } });

  mk({ manual_offset_seconds: -3600 });                                         assert.equal(app.wouldResolve(ref), true);
  mk({ accept_proposal: true }, { proposed_offset_seconds: -3600 });            assert.equal(app.wouldResolve(ref), true);
  mk({ manual_real_utc: "2026-03-22T13:00:00Z" }, { proposal_source: "gpx_self_anchor" }); assert.equal(app.wouldResolve(ref), true);
  mk({ accept_proposal: true }, {});                                            assert.equal(app.wouldResolve(ref), false);  // nothing to accept
  mk({ manual_offset_seconds: 999999 });                                        assert.equal(app.wouldResolve(ref), false);  // out of range
  mk({});                                                                       assert.equal(app.wouldResolve(ref), false);
});

test("clearing a folder fallback (the Clear button payload) resolves to none", () => {
  const dest = "6-photos-by-dest/Belgium", ref = { file: "gps", dest, kind: "fallback" };
  const mk = (ud, proposal = {}) => setWork(
    { gps: { destinations: { [dest]: { folder_fallback: { user_decision: ud, proposal } } } } });
  mk({ fallback_lat: 50.5, fallback_lon: 4.2 });                              assert.equal(app.wouldResolve(ref), true);   // manual
  mk({ accept_proposal: true }, { proposed_fallback: { lat: 50, lon: 4 } }); assert.equal(app.wouldResolve(ref), true);   // accept inherited
  // The Clear button writes exactly this — clears coord AND the accept flag -> effective none:
  mk({ fallback_lat: "", fallback_lon: "", accept_proposal: false });        assert.equal(app.wouldResolve(ref), false);
});

test("previewTz / previewFallback inherit from the nearest resolved ancestor", () => {
  setWork({
    time: { destinations: {
      "6-photos-by-dest/Japan": { destination_timezone: { proposed_iana_timezone: "Asia/Tokyo", user_decision: { accept_proposed_timezone: true } } },
      "6-photos-by-dest/Japan/Kyoto": { destination_timezone: { user_decision: {} } },
    } },
    gps: { destinations: {
      "6-photos-by-dest/Japan": { folder_fallback: { user_decision: { fallback_lat: 35.0, fallback_lon: 139.0 } } },
      "6-photos-by-dest/Japan/Kyoto": { folder_fallback: { user_decision: {} } },
    } },
  });
  assert.equal(app.previewTz("6-photos-by-dest/Japan").tz, "Asia/Tokyo");
  const inhTz = app.previewTz("6-photos-by-dest/Japan/Kyoto");
  assert.equal(inhTz.tz, "Asia/Tokyo");
  assert.equal(inhTz.source, "inherited");

  const inhFb = app.previewFallback("6-photos-by-dest/Japan/Kyoto");
  assert.deepEqual([inhFb.lat, inhFb.lon, inhFb.source], [35.0, 139.0, "inherited"]);
});
