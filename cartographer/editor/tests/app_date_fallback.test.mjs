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

// Front-end unit tests for a destination's date fallback (photos-21 date_fallback, web/app.js): the value checked as
// geotag checks it, the date in effect previewed down the tree, and the question of a folder holding photos with no
// recorded time answered here, writing the field the record documents (decision-json-reference §4).
import { test } from "node:test";
import assert from "node:assert/strict";
import * as app from "../web/app.js";

const setWork = (work) => { app.state.work = work; app.state.base = JSON.parse(JSON.stringify(work)); };
const ROOT = "6-photos-by-dest", SCANS = `${ROOT}/Scans`, XMAS = `${SCANS}/Christmas`, TRIP = `${ROOT}/Trip`;
const cell = (date = "", untimed = []) => ({ user_decision: { date }, effective_date: null,
  ...(untimed.length ? { untimed_photos: untimed } : {}), requires_user_input: untimed.length > 0, stale_user_decision: false });

test("a date fallback is a year, a year and month, or a day the calendar has; the rest are the first", () => {
  assert.equal(app.dateFallbackDay("1985"), "1985-01-01");
  assert.equal(app.dateFallbackDay("1985-06"), "1985-06-01");
  assert.equal(app.dateFallbackDay("1985-06-14"), "1985-06-14");
  assert.equal(app.dateFallbackDay("2024-02-29"), "2024-02-29");
  for (const bad of ["1985-02-30", "1985-13", "1985-00", "0000", "85", "1985-6", "1985/06", "1985-06-14T00:00", " 1985", 1985, null])
    assert.equal(app.dateFallbackDay(bad), null, String(bad));
  assert.equal(app.validDateFallback(""), true);                 // none given
  assert.equal(app.validDateFallback("1985-02-30"), false);
});

test("the date in effect is the one given at the folder, else the nearest above it — no acceptance asked", () => {
  setWork({ time: { destinations: { [ROOT]: { date_fallback: cell() }, [SCANS]: { date_fallback: cell("1985") },
    [XMAS]: { date_fallback: cell("", [`${XMAS}/scan001.jpg`]) }, [TRIP]: { date_fallback: cell() } } } });
  assert.deepEqual(app.previewDate(XMAS), { date: "1985", filled: "1985-01-01", source: "inherited", from: SCANS });
  assert.deepEqual(app.previewDate(SCANS), { date: "1985", filled: "1985-01-01", source: "own", from: SCANS });
  assert.equal(app.previewDate(TRIP), null);
  const ref = { file: "time", dest: XMAS, kind: "date" };
  assert.equal(app.wouldResolve(ref), true);                     // the inherited date times its photos
  app.state.work.time.destinations[XMAS].date_fallback.user_decision.date = "1985-12-25";
  assert.deepEqual(app.previewDate(XMAS), { date: "1985-12-25", filled: "1985-12-25", source: "own", from: XMAS });
  assert.equal(app.isDirty(ref), true);
});

test("a folder holding photos with no time asks for a date; a bad one is invalid; the answer is saved as `date`", () => {
  setWork({ time: { destinations: { [ROOT]: { date_fallback: cell() },
    [XMAS]: { date_fallback: cell("", [`${XMAS}/scan001.jpg`, `${XMAS}/scan002.jpg`]) } } } });
  const ref = { file: "time", dest: XMAS, kind: "date" };
  assert.deepEqual(app.cellStatus(app.cellAt(app.state.base, ref)), ["needs", "needs input"]);
  assert.equal(app.wouldResolve(ref), false);
  assert.equal(app.showsDate(XMAS), true);
  assert.equal(app.showsDate(ROOT), true);                       // a folder above them can carry it for all
  app.state.work.time.destinations[XMAS].date_fallback.user_decision.date = "1985-02-30";
  assert.equal(app.refInvalid(ref), true);
  app.state.work.time.destinations[XMAS].date_fallback.user_decision.date = "1985-06";
  assert.equal(app.refInvalid(ref), false);
  assert.equal(app.wouldResolve(ref), true);
  const p = app.savePayload([ref], (r) => app.cellAt(app.state.work, r), {});
  assert.deepEqual(p.time, [{ dest: XMAS, kind: "date", key: undefined, path: undefined, user_decision: { date: "1985-06" } }]);
});

test("a folder with no photo lacking a time, and no date written, shows no date row", () => {
  setWork({ time: { destinations: { [TRIP]: { date_fallback: cell() } } } });
  assert.equal(app.showsDate(TRIP), false);
});

test("why the tracks did not place a photo timed by its folder's date", () => {
  assert.match(app.tracksNote({ reason: "time_from_date_fallback" }), /date fallback/);
});
