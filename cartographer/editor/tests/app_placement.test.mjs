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

test("a position the user set, emptied, previews the photo placed as before, never as waiting", () => {
  const rel = `${D}/set.arw`, ref = { file: "gps", dest: D, kind: "review", path: rel };
  const item = { relative_path: rel, reason: "manual_locked", requires_user_input: false,
    user_decision: { manual_lat: 35.0, manual_lon: 135.7 } };
  const work = { gps: { destinations: { [D]: { folder_fallback: fallback({}), gps_decisions: { review_items: [item] } } } } };
  app.state.base = JSON.parse(JSON.stringify(work)); app.state.work = work;
  item.user_decision = { manual_lat: "", manual_lon: "" };
  assert.match(app.previewEffective(ref), /placed as before/);
  assert.doesNotMatch(app.previewEffective(ref), /needs/);
  work.gps.destinations[D].folder_fallback.user_decision = { fallback_lat: 35.6, fallback_lon: 139.6 };
  assert.match(app.previewEffective(ref), /placed as before/);                     // the tracks may place it before the fallback
});

test("a position chosen and saved, read back before a plan, is the placed photo's decision, listed once", () => {
  // BLD-chosen_position: the `chosen_by_user` entry is the photo's decision. Read back before the next plan, the photo
  // is still among `placed_photos`: listed once, on its placed row, holding the entry's position — never a second row
  // saying "placed by the tracks" with an empty field.
  const rel = `${D}/x.arw`;
  const art = { gps: { destinations: { [D]: { folder_fallback: fallback({}), gps_decisions: {
    placed_photos: [{ relative_path: rel, placed_by: "tracks", method: "interpolated" }],
    review_items: [{ relative_path: rel, reason: "chosen_by_user", requires_user_input: false, stale_user_decision: false,
      user_decision: { manual_lat: 50, manual_lon: 4 } }] } } } } };
  app.withChosenCells(art);
  app.state.base = JSON.parse(JSON.stringify(art)); app.state.work = JSON.parse(JSON.stringify(art));
  const listed = app.gpsBuckets(D, art.gps.destinations[D]).flatMap((b) => [...b.photos, ...b.groups.flatMap((g) => g.photos)]);
  assert.deepEqual(listed.map((p) => [p.entry.relative_path, p.ref && p.ref.kind]), [[rel, "chosen"]]);
  const ref = { file: "gps", dest: D, kind: "chosen", path: rel };
  assert.match(app.previewEffective(ref), /^50, 4 \(manual\)/);
  assert.equal(app.isDirty(ref), false);
});

test("placedPosition: a placed photo's row copies where it is placed, in the form the coordinate field takes", () => {
  const rel = (n) => `${D}/${n}.arw`;
  const placed = [{ relative_path: rel("t"), content_fingerprint: "fp-t", placed_by: "tracks", method: "interpolated",
                    position: { lat: 50.525434, lon: 4.269781 } },
                  { relative_path: rel("o"), content_fingerprint: "fp-o", placed_by: "own_position",
                    position: { lat: -33.8688, lon: 151.2093 } },
                  { relative_path: rel("f"), content_fingerprint: "fp-f", placed_by: "folder_fallback",
                    position: { lat: 1, lon: 2 } },
                  { relative_path: rel("n"), content_fingerprint: "fp-n", placed_by: "tracks", method: "interpolated" }];
  const loaded = app.withChosenCells({ gps: { destinations: { [D]: {
    folder_fallback: fallback({ fallback_lat: 35.6, fallback_lon: 139.6 }),
    gps_decisions: { review_items: [], placed_photos: placed } } } } });
  app.state.base = loaded; app.state.work = JSON.parse(JSON.stringify(loaded));
  const rows = app.gpsBuckets(D, app.state.work.gps.destinations[D]).flatMap((b) => [...b.photos, ...b.groups.flatMap((g) => g.photos)]);
  const at = (n) => app.placedPosition(D, rows.find((x) => x.entry.relative_path === rel(n)));
  assert.deepEqual(at("t"), { lat: 50.525434, lon: 4.269781 });                 // where the tracks placed it
  assert.deepEqual(at("o"), { lat: -33.8688, lon: 151.2093 });                  // its own position
  assert.deepEqual(at("f"), { lat: 35.6, lon: 139.6 });                         // the fallback in effect now
  assert.equal(at("n"), null);                                                  // no position recorded: nothing to copy
  app.state.work.gps.destinations[D].gps_decisions.placed_photos[0].user_decision = { manual_lat: 48.1, manual_lon: 11.5 };
  assert.deepEqual(at("t"), { lat: 48.1, lon: 11.5 });                          // a position chosen for it here
  for (const c of [at("t"), at("o"), { lat: 0.0000004, lon: -179.9999996 }]) {
    const text = app.fmtCoord(c);
    assert.match(text, /^-?\d+\.\d{6}, -?\d+\.\d{6}$/);
    const back = app.parseLatLon(text);                                         // pasted into the coordinate field
    assert.ok(Math.abs(back.lat - c.lat) < 1e-6 && Math.abs(back.lon - c.lon) < 1e-6, text);
  }
});
