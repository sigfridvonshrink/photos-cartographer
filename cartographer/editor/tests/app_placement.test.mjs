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

// No photo leaves geotag without a position: a photo nothing places is offered its folder's fallback first, a
// position of its own second; and a photo the tracks or the fallback place can be given a position of its own,
// saved as a `chosen_by_user` review item (BLD-chosen_position, docs/design/decisions.md). Run with `tools/jstest`.
import { test } from "node:test";
import assert from "node:assert/strict";
import * as app from "../web/app.js";

const D = "6-photos-by-dest/Japan";
const fallback = (ud) => ({ inherited_fallback: null, effective_fallback: null, fallback_source: "none",
  user_decision: { fallback_lat: "", fallback_lon: "", ...ud } });
const unplaced = (rel) => ({ relative_path: rel, reason: "no_reliable_gps_source", requires_user_input: true,
  user_decision: { manual_lat: "", manual_lon: "" } });

test("an unplaced photo is offered its folder's fallback first, a position for itself second", () => {
  assert.deepEqual(app.reviewOffers(unplaced(`${D}/a.arw`)), ["folder_fallback", "position"]);
  assert.deepEqual(app.reviewOffers({ reason: "manual_locked" }), ["position"]);
  assert.deepEqual(app.reviewOffers({ reason: "own_position_contradicted" }), ["position"]);
});

test("the folder's fallback, once set, resolves the photo nothing else places; leave-unlocated is gone", () => {
  const ref = { file: "gps", dest: D, kind: "review", path: `${D}/a.arw` };
  const work = { gps: { destinations: { [D]: { folder_fallback: fallback({}),
    gps_decisions: { review_items: [unplaced(`${D}/a.arw`)] } } } } };
  app.state.work = work; app.state.base = JSON.parse(JSON.stringify(work));
  assert.equal(app.wouldResolve(ref), false);
  work.gps.destinations[D].gps_decisions.review_items[0].user_decision.accept_unlocated = true;   // no such answer
  assert.equal(app.wouldResolve(ref), false);
  delete work.gps.destinations[D].gps_decisions.review_items[0].user_decision.accept_unlocated;
  work.gps.destinations[D].folder_fallback.user_decision = { fallback_lat: 35.6, fallback_lon: 139.6 };
  assert.equal(app.wouldResolve(ref), true);                                    // the fallback places it
  work.gps.destinations[D].folder_fallback = fallback({});
  work.gps.destinations[D].gps_decisions.review_items[0].user_decision = { manual_lat: 35.0, manual_lon: 135.7 };
  assert.equal(app.wouldResolve(ref), true);                                    // or a position for it alone
});

test("a placed photo is listed, given an empty answer, and saved as a chosen position by its path", () => {
  const rel = `${D}/interp.arw`, ref = { file: "gps", dest: D, kind: "chosen", path: rel };
  const placed = [{ relative_path: rel, content_fingerprint: "fp-i", placed_by: "tracks" },
                  { relative_path: `${D}/f.arw`, content_fingerprint: "fp-f", placed_by: "folder_fallback" }];
  const loaded = app.withChosenCells({ gps: { destinations: { [D]: { folder_fallback: fallback({}),
    gps_decisions: { review_items: [], placed_photos: placed } } } } });
  assert.deepEqual(loaded.gps.destinations[D].gps_decisions.placed_photos[0].user_decision, { manual_lat: "", manual_lon: "" });
  app.state.base = loaded; app.state.work = JSON.parse(JSON.stringify(loaded));
  assert.equal(app.cellAt(app.state.work, ref).placed_by, "tracks");
  assert.equal(app.isDirty(ref), false);
  assert.equal(app.wouldResolve(ref), true);                                    // placed already: nothing waits
  app.state.work.gps.destinations[D].gps_decisions.placed_photos[0].user_decision = { manual_lat: 35.0, manual_lon: 135.75 };
  assert.equal(app.isDirty(ref), true);
  assert.equal(app.refInvalid(ref), false);
  const p = app.savePayload([ref], (r) => app.cellAt(app.state.work, r), { gps: "g1" });
  assert.deepEqual(p.gps, [{ dest: D, kind: "chosen", key: undefined, path: rel,
    user_decision: { manual_lat: 35.0, manual_lon: 135.75 } }]);
  app.state.work.gps.destinations[D].gps_decisions.placed_photos[0].user_decision = { manual_lat: 95, manual_lon: 135.75 };
  assert.equal(app.refInvalid(ref), true);                                      // checked as any position
});
