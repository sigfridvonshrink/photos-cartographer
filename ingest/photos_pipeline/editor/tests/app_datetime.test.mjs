// Front-end unit tests for the editor's offset⟷real-UTC date math and formatting (web/app.js).
import { test } from "node:test";
import assert from "node:assert/strict";
import * as app from "../web/app.js";

test("camera-naive parse round-trips through msToDtLocal (UTC wall time)", () => {
  const ms = app.camNaiveMs("2026:03:22 13:25:21");
  assert.equal(ms, Date.UTC(2026, 2, 22, 13, 25, 21));
  assert.equal(app.msToDtLocal(ms), "2026-03-22T13:25:21");
  assert.equal(app.camNaiveMs("garbage"), null);
});

test("datetime-local parse (seconds optional, treated as UTC wall time)", () => {
  assert.equal(app.dtLocalToMs("2026-03-22T13:25:21"), Date.UTC(2026, 2, 22, 13, 25, 21));
  assert.equal(app.dtLocalToMs("2026-03-22T13:25"), Date.UTC(2026, 2, 22, 13, 25, 0));
  assert.equal(app.dtLocalToMs("garbage"), null);
});

test("offset derives as real_utc − camera_naive (matches the geotag script)", () => {
  const cam = app.camNaiveMs("2026:03:22 14:25:21");
  const real = app.utcStrToMs("2026-03-22T13:25:21Z");
  assert.equal(Math.round((real - cam) / 1000), -3600);   // camera 1h ahead of UTC
});

test("fmtDT splits identical {date,time}; fmtLocal renders in the tz; bad tz → null", () => {
  const ms = app.utcStrToMs("2026-03-22T12:24:18Z");      // 22 Mar is pre-DST → Brussels = UTC+1
  const dt = app.fmtDT(ms, "Europe/Brussels");
  assert.deepEqual(dt, { date: "22 Mar 2026", time: "13:24:18" });
  assert.match(app.fmtLocal(ms, "Europe/Brussels"), /13:24:18/);
  assert.equal(app.fmtDT(ms, "Bogus/Zone"), null);
  assert.equal(app.fmtLocal(ms, "Bogus/Zone"), null);
});

test("offsetImpact: photo-local → corrected-local (UTC in parens after), date once if invariant", () => {
  const cam = app.camNaiveMs("2026:03:22 14:25:21");       // photo's current (camera) local
  // offset 0: corrected UTC = 14:25:21Z, Brussels (UTC+1 pre-DST) → 15:25:21 local, same date
  assert.equal(app.offsetImpact(cam, 0, "Europe/Brussels"),
    "22 Mar 2026 · 14:25:21 → 15:25:21 (Europe/Brussels, UTC 14:25:21)");
  // no timezone → corrected shown as UTC
  assert.equal(app.offsetImpact(cam, -3600, null), "22 Mar 2026 · 14:25:21 → 13:25:21 UTC");
  assert.equal(app.offsetImpact(null, 0, "UTC"), null);
});
