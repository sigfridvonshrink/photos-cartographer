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

// --- the true time of a photo, typed in its destination's zone, gives the clock offset ------------------------------

test("utcToZonedWallMs / zonedWallToUtcMs: an instant's wall time in a zone, and back", () => {
  const summer = Date.UTC(2026, 6, 3, 12, 0, 0);
  assert.equal(app.utcToZonedWallMs(summer, "Europe/Brussels"), Date.UTC(2026, 6, 3, 14, 0, 0));   // CEST, +2
  assert.equal(app.zonedWallToUtcMs(Date.UTC(2026, 6, 3, 14, 0, 0), "Europe/Brussels"), summer);
  assert.equal(app.zonedWallToUtcMs(Date.UTC(2026, 0, 3, 14, 0, 0), "Europe/Brussels"), Date.UTC(2026, 0, 3, 13, 0, 0));
  assert.equal(app.zonedWallToUtcMs(Date.UTC(2026, 6, 3, 14, 0, 0), ""), Date.UTC(2026, 6, 3, 14, 0, 0));   // no zone: UTC
  assert.equal(app.utcToZonedWallMs(summer, "Bogus/Zone"), null);
  assert.equal(app.zonedWallToUtcMs(Date.UTC(2026, 6, 3, 14, 0, 0), "Bogus/Zone"), null);
});

test("zonedWallToUtcMs: a time the clocks skipped or showed twice names no one instant — never guessed", () => {
  // Brussels 2026-03-29: 02:00 → 03:00 (02:30 never happened); 2026-10-25: 03:00 → 02:00 (02:30 happened twice)
  assert.equal(app.zonedWallToUtcMs(Date.UTC(2026, 2, 29, 2, 30, 0), "Europe/Brussels"), null);
  assert.equal(app.zonedWallToUtcMs(Date.UTC(2026, 9, 25, 2, 30, 0), "Europe/Brussels"), null);
  assert.equal(app.zonedWallToUtcMs(Date.UTC(2026, 2, 29, 3, 30, 0), "Europe/Brussels"), Date.UTC(2026, 2, 29, 1, 30, 0));
});

test("offsetFromTrueTime: a reset clock's photo, given its true local time, yields manual_offset_seconds", () => {
  // the camera reads its factory date; the photo was really taken 2026-05-01 14:00 in Bruges (CEST, UTC+2)
  const off = app.offsetFromTrueTime("2000:01:01 10:00:00", "2026-05-01T14:00:00", "Europe/Brussels");
  assert.equal(off, Math.round((Date.UTC(2026, 4, 1, 12, 0, 0) - Date.UTC(2000, 0, 1, 10, 0, 0)) / 1000));
  // camera time + offset = the true UTC, as geotag computes it
  assert.equal(app.camNaiveMs("2000:01:01 10:00:00") + off * 1000, Date.UTC(2026, 4, 1, 12, 0, 0));
  // with no zone the time typed is UTC; seconds optional
  assert.equal(app.offsetFromTrueTime("2026:05:01 15:00:00", "2026-05-01T14:00", ""), -3600);
  // nothing to compute from
  assert.equal(app.offsetFromTrueTime("2026:05:01 15:00:00", "", "Europe/Brussels"), null);
  assert.equal(app.offsetFromTrueTime("garbage", "2026-05-01T14:00:00", "Europe/Brussels"), null);
  assert.equal(app.offsetFromTrueTime("2026:03:29 09:00:00", "2026-03-29T02:30:00", "Europe/Brussels"), null);  // skipped
});

test("trueTimeOf: the field shows the true time an offset gives the photo, round-tripping offsetFromTrueTime", () => {
  assert.equal(app.trueTimeOf("2026:05:01 15:00:00", -3600, "Europe/Brussels"), "2026-05-01T16:00:00");
  assert.equal(app.trueTimeOf("2026:05:01 15:00:00", -3600, ""), "2026-05-01T14:00:00");
  const off = app.offsetFromTrueTime("2000:01:01 10:00:00", "2026-05-01T14:00:00", "Europe/Brussels");
  assert.equal(app.trueTimeOf("2000:01:01 10:00:00", off, "Europe/Brussels"), "2026-05-01T14:00:00");
  assert.equal(app.trueTimeOf("garbage", 0, "UTC"), null);
  assert.equal(app.trueTimeOf("2026:05:01 15:00:00", null, "UTC"), null);
});
