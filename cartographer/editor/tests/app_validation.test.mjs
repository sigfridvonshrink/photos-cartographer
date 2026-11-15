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

// Front-end unit tests for the decision editor's pure validation/format logic (web/app.js).
// Run with Node's built-in runner (no deps): `node --test cartographer/editor/tests/`.
// app.js is a browser ES module; importing it in Node only works because its auto-start is guarded
// (`if (typeof document !== "undefined") main()`) and the tested functions are exported.
import { test } from "node:test";
import assert from "node:assert/strict";
import * as app from "../web/app.js";

test("validTz accepts the host's zones / empty, rejects any other — the browser's own list says nothing", () => {
  app.setHostZones(["UTC", "Europe/Brussels", "Asia/Tokyo"]);       // as the server sends them
  for (const ok of ["", null, "UTC", "Europe/Brussels", "Asia/Tokyo"]) assert.equal(app.validTz(ok), true);
  for (const bad of ["Nowhere/Nope", "xyz"]) assert.equal(app.validTz(bad), false);
  // a name the browser knows but the host does not: geotag's plan would refuse it, so the editor does
  assert.doesNotThrow(() => new Intl.DateTimeFormat("en", { timeZone: "US/Eastern" }));
  assert.equal(app.validTz("US/Eastern"), false);
  app.setHostZones(undefined);                                          // nothing sent: no zone is known
  assert.equal(app.validTz("UTC"), false);
  assert.equal(app.validTz(""), true);
});

test("validOffset is empty-or-a-whole-number of seconds, of any size", () => {
  for (const ok of ["", null, 0, 86400, -93600, 3600, 762000000]) assert.equal(app.validOffset(ok), true);
  for (const bad of [1.5, "x", true, NaN]) assert.equal(app.validOffset(bad), false);
});

test("lat/lon ranges and bothOrNeither", () => {
  assert.equal(app.validLat(90), true); assert.equal(app.validLat(-90), true); assert.equal(app.validLat(91), false);
  assert.equal(app.validLon(180), true); assert.equal(app.validLon(-181), false);
  assert.equal(app.bothOrNeither("", ""), true);
  assert.equal(app.bothOrNeither(1, 2), true);
  assert.equal(app.bothOrNeither(1, ""), false);
  assert.equal(app.bothOrNeither("", 2), false);
});

test("fmtOffset formats h/m/s with sign", () => {
  assert.equal(app.fmtOffset(""), "—");
  assert.equal(app.fmtOffset(0), "+0h 00m 00s");
  assert.equal(app.fmtOffset(3661), "+1h 01m 01s");
  assert.equal(app.fmtOffset(-3661), "−1h 01m 01s");   // U+2212 minus sign
});
