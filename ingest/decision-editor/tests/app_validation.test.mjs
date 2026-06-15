// Front-end unit tests for the decision editor's pure validation/format logic (web/app.js).
// Run with Node's built-in runner (no deps): `node --test ingest/decision-editor/tests/`.
// app.js is a browser ES module; importing it in Node only works because its auto-start is guarded
// (`if (typeof document !== "undefined") main()`) and the tested functions are exported.
import { test } from "node:test";
import assert from "node:assert/strict";
import * as app from "../web/app.js";

test("validTz accepts real IANA zones / empty, rejects bogus", () => {
  for (const ok of ["", null, "UTC", "Europe/Brussels", "Asia/Tokyo"]) assert.equal(app.validTz(ok), true);
  for (const bad of ["Nowhere/Nope", "xyz"]) assert.equal(app.validTz(bad), false);
});

test("validOffset is empty-or-number within ±86400", () => {
  for (const ok of ["", null, 0, 86400, -86400, 3600]) assert.equal(app.validOffset(ok), true);
  for (const bad of [86401, -86401, "x", true, NaN]) assert.equal(app.validOffset(bad), false);
});

test("validUtc requires ISO-8601 with T and seconds, no millis", () => {
  for (const ok of ["", "2024-07-03T14:12:21Z", "2024-07-03T14:12:21+02:00"]) assert.equal(app.validUtc(ok), true);
  for (const bad of ["2024-07-03 14:12:21", "2024-07-03T14:12:21.000Z", "2024-07-03T14:12", "nope"])
    assert.equal(app.validUtc(bad), false);
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
