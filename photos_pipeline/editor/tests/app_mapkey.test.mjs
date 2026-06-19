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

// Front-end unit tests for mapKeyFor (web/app.js): the cache key that decides when the side-panel
// Leaflet map is torn down and rebuilt. A rebuild blanks the panel (a visible flash), so extending a
// GPS-review selection (shift-click) must NOT change the key — its pins/centre are dest-scoped.
import { test } from "node:test";
import assert from "node:assert/strict";
import * as app from "../web/app.js";

test("mapKeyFor: review key is stable across path/peers within a dest (no flash on shift-click)", () => {
  const dest = "2024/trip";
  const single = { file: "gps", dest, kind: "review", path: "a.jpg" };
  const extendedDown = { file: "gps", dest, kind: "review", path: "a.jpg", peers: ["a.jpg", "b.jpg", "c.jpg"] };
  const extendedUp = { file: "gps", dest, kind: "review", path: "x.jpg", peers: ["x.jpg", "y.jpg"] };
  const k = app.mapKeyFor(single);
  assert.equal(app.mapKeyFor(extendedDown), k, "growing peers must not change the key");
  assert.equal(app.mapKeyFor(extendedUp), k, "changing run[0]/path must not change the key");
});

test("mapKeyFor: a different dest still rebuilds the map", () => {
  const a = { file: "gps", dest: "2024/a", kind: "review", path: "p.jpg" };
  const b = { file: "gps", dest: "2024/b", kind: "review", path: "p.jpg" };
  assert.notEqual(app.mapKeyFor(a), app.mapKeyFor(b));
});

test("mapKeyFor: non-review kinds keep their per-cell key (path/peers significant)", () => {
  const fb = { file: "gps", dest: "2024/a", kind: "fallback", key: "k1" };
  const fb2 = { file: "gps", dest: "2024/a", kind: "fallback", key: "k2" };
  assert.notEqual(app.mapKeyFor(fb), app.mapKeyFor(fb2));
  const off1 = { file: "time", dest: "d", kind: "offset", key: "cam", peers: ["1"] };
  const off2 = { file: "time", dest: "d", kind: "offset", key: "cam", peers: ["1", "2"] };
  assert.notEqual(app.mapKeyFor(off1), app.mapKeyFor(off2));
});

test("mapKeyFor: null ref → null", () => {
  assert.equal(app.mapKeyFor(null), null);
});
