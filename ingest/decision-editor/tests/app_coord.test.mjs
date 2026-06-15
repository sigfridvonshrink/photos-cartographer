// Front-end unit tests for the coordinate helpers (web/app.js): parseLatLon (Google-Maps paste),
// coordText (single-field display), contiguousRange (multi-select run).
import { test } from "node:test";
import assert from "node:assert/strict";
import * as app from "../web/app.js";

test("parseLatLon: accepts Google-Maps 'lat, lon', comma or whitespace separated", () => {
  assert.deepEqual(app.parseLatLon("50.52543370051842, 4.269781248712496"), { lat: 50.52543370051842, lon: 4.269781248712496 });
  assert.deepEqual(app.parseLatLon("  -33.8688 , 151.2093 "), { lat: -33.8688, lon: 151.2093 });
  assert.deepEqual(app.parseLatLon("50.5 4.2"), { lat: 50.5, lon: 4.2 });
  assert.deepEqual(app.parseLatLon("0, 0"), { lat: 0, lon: 0 });
});

test("parseLatLon: rejects junk and out-of-range", () => {
  for (const bad of ["", "hello", "50.5", "50.5, 4.2, 9", "91, 0", "0, 181", "-91, 0", "abc, def"])
    assert.equal(app.parseLatLon(bad), null, `should reject ${JSON.stringify(bad)}`);
  assert.equal(app.parseLatLon(null), null);
});

test("coordText: numbers → 'lat, lon'; kept bad text → verbatim; else empty", () => {
  assert.equal(app.coordText({ manual_lat: 50.5, manual_lon: 4.2 }, "manual_lat", "manual_lon"), "50.5, 4.2");
  assert.equal(app.coordText({ manual_lat: "garbage", manual_lon: "" }, "manual_lat", "manual_lon"), "garbage");
  assert.equal(app.coordText({ manual_lat: "", manual_lon: "" }, "manual_lat", "manual_lon"), "");
  assert.equal(app.coordText({ fallback_lat: -1, fallback_lon: 2 }, "fallback_lat", "fallback_lon"), "-1, 2");
});

test("contiguousRange: inclusive run in either direction, null when an endpoint is absent", () => {
  const order = ["a", "b", "c", "d", "e"];
  assert.deepEqual(app.contiguousRange(order, "b", "d"), ["b", "c", "d"]);
  assert.deepEqual(app.contiguousRange(order, "d", "b"), ["b", "c", "d"]);   // reversed click order
  assert.deepEqual(app.contiguousRange(order, "c", "c"), ["c"]);
  assert.equal(app.contiguousRange(order, "b", "z"), null);
  assert.equal(app.contiguousRange(order, "z", "b"), null);
});
