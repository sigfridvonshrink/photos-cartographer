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

// Front-end unit tests for where the editor asks for a date fallback or a folder fallback (web/app.js,
// BLD-editor_date_asking, BLD-editor_fallback_asking): as for a timezone, an answer given in the editor settles, at once,
// the questions below it that it answers — the date cells it covers, and the folder fallback cells and the photos
// nothing else places under a folder fallback in effect. Run by tools/jstest, and by test_front_end.py for the corpus.
import { test } from "node:test";
import assert from "node:assert/strict";
import * as app from "../web/app.js";

const clone = (o) => JSON.parse(JSON.stringify(o));
const R = "6-photos-by-dest", A = `${R}/A`, B = `${R}/A/B`, C = `${R}/C`;
const date = (asks) => ({ date_fallback: { user_decision: { date: "" }, effective_date: null,
  untimed_photos: asks ? [`${B}/u.jpg`] : [], requires_user_input: asks, stale_user_decision: false } });
const fb = (asks, photos = []) => ({ folder_fallback: { user_decision: { fallback_lat: "", fallback_lon: "" },
  effective_fallback: null, requires_user_input: asks, stale_user_decision: false },
  gps_decisions: { review_items: photos.map((p) => ({ relative_path: p, reason: "no_reliable_gps_source",
    requires_user_input: true, stale_user_decision: false, user_decision: { manual_lat: "", manual_lon: "" } })) } });
const status = (ref) => (app.statusOf(ref) || [])[0];

test("a date written above settles, before any run, the date cells below that it covers", () => {
  const work = { time: { destinations: { [R]: date(false), [A]: date(false), [B]: date(true), [C]: date(true) } } };
  app.state.base = clone(work); app.state.work = work;
  const below = { file: "time", dest: B, kind: "date" }, beside = { file: "time", dest: C, kind: "date" };
  assert.equal(status(below), "needs");
  work.time.destinations[A].date_fallback.user_decision.date = "1985";
  assert.equal(status(below), "ok");                                  // untouched, and settled by the date above
  assert.equal(status(beside), "needs");                              // a date covers nothing beside it
  work.time.destinations[A].date_fallback.user_decision.date = "";
  assert.equal(status(below), "needs");                               // taken away, the question is back
});

test("a folder fallback written settles its own cell and the photos nothing else places at and below it", () => {
  const work = { gps: { destinations: { [R]: fb(false), [A]: fb(true, [`${A}/x.jpg`]), [B]: fb(true, [`${B}/y.jpg`]),
    [C]: fb(true, [`${C}/z.jpg`]) } } };
  app.state.base = clone(work); app.state.work = work;
  const photo = (dest, p) => ({ file: "gps", dest, kind: "review", path: p });
  const cellOf = (dest) => ({ file: "gps", dest, kind: "fallback" });
  assert.equal(status(photo(B, `${B}/y.jpg`)), "needs");
  assert.equal(status(cellOf(B)), "needs");
  Object.assign(work.gps.destinations[A].folder_fallback.user_decision, { fallback_lat: 50.1, fallback_lon: 4.2 });
  assert.equal(status(photo(A, `${A}/x.jpg`)), "ok");                 // placed by the fallback written at its folder
  assert.equal(status(photo(B, `${B}/y.jpg`)), "ok");                 // and by the one it inherits
  assert.equal(status(cellOf(B)), "ok");                              // the folder below asks no more
  assert.equal(status(photo(C, `${C}/z.jpg`)), "needs");              // nothing reaches a folder beside it
  assert.equal(status(cellOf(C)), "needs");
});
