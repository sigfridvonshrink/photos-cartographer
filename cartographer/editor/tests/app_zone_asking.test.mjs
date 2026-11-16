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

// Front-end unit tests for where the editor asks for a timezone (web/app.js, BLD-editor_zone_asking): geotag asks at
// every folder above a destination waiting for one (`asked_for`); a zone answered in the editor stops the asking, at
// once, at every destination it reaches and at every folder asking for no other. Run by tools/jstest, and by
// test_zone_asking.py for the corpus.
import { test } from "node:test";
import assert from "node:assert/strict";
import * as app from "../web/app.js";

app.setHostZones(["America/Los_Angeles", "America/New_York", "Asia/Tokyo", "Europe/Brussels", "Europe/Rome"]);
const R = "6-photos-by-dest";
const clone = (o) => JSON.parse(JSON.stringify(o));
const setWork = (work) => { app.state.base = clone(work); app.state.work = work; };
const tz = (cell = {}) => ({ destination_timezone: { proposal_source: "none", requires_user_input: true,
  user_decision: { manual_iana_timezone: "", country: "" }, ...cell } });
const box = (asked, cell = {}) => ({ file_less: true, ...tz({ requires_user_input: asked.length > 0, ...(asked.length ? { asked_for: asked } : {}), ...cell }) });
const status = (dest) => (app.statusOf({ file: "time", dest, kind: "timezone" }) || [])[0];
const write = (work, dest, field, value) => { work.time.destinations[dest].destination_timezone.user_decision[field] = value; };

test("a zone answered on a folder settles every destination it reaches, and the folders asking for those alone", () => {
  const work = { time: { destinations: {
    [R]: box([`${R}/Italy/Rome`, `${R}/Japan/Kyoto`, `${R}/Japan/Tokyo`]),
    [`${R}/Japan`]: box([`${R}/Japan/Kyoto`, `${R}/Japan/Tokyo`]), [`${R}/Italy`]: box([`${R}/Italy/Rome`]),
    [`${R}/Japan/Kyoto`]: tz(), [`${R}/Japan/Tokyo`]: tz(), [`${R}/Italy/Rome`]: tz(),
  } } };
  setWork(work);
  for (const d of Object.keys(work.time.destinations)) assert.equal(status(d), "needs", d);
  write(work, `${R}/Japan`, "manual_iana_timezone", "Asia/Tokyo");
  for (const d of [`${R}/Japan`, `${R}/Japan/Kyoto`, `${R}/Japan/Tokyo`]) assert.equal(status(d), "ok", d);
  for (const d of [R, `${R}/Italy`, `${R}/Italy/Rome`]) assert.equal(status(d), "needs", d);   // Rome still waits
  write(work, `${R}/Italy/Rome`, "manual_iana_timezone", "Europe/Rome");
  for (const d of Object.keys(work.time.destinations)) assert.equal(status(d), "ok", d);        // nothing left to ask
  // undone, the questions are back
  write(work, `${R}/Japan`, "manual_iana_timezone", "");
  assert.equal(status(`${R}/Japan/Kyoto`), "needs");
  assert.equal(status(R), "needs");
});

test("an answer settles nothing it does not reach: past a country of several timezones, or a zone the photos contradict", () => {
  const work = { time: { countries: { US: { name: "United States", zones: ["America/Los_Angeles", "America/New_York"] } },
    destinations: {
      [R]: box([`${R}/Belgium/Ghent`]),
      [`${R}/US`]: box([], { user_decision: { manual_iana_timezone: "", country: "US" } }),
      [`${R}/US/California`]: box([`${R}/US/California/LA`]), [`${R}/US/California/LA`]: tz(),
      [`${R}/Belgium`]: box([`${R}/Belgium/Ghent`]),
      [`${R}/Belgium/Ghent`]: tz({ contradicted_by: { timezone: "Europe/Brussels", recorded_offsets: [32400] } }),
    } } };
  setWork(work);
  write(work, `${R}/US`, "manual_iana_timezone", "America/New_York");          // a country of several gives none down
  assert.equal(status(`${R}/US/California/LA`), "needs");
  assert.equal(status(`${R}/US/California`), "needs");
  write(work, `${R}/US/California`, "manual_iana_timezone", "America/Los_Angeles");
  assert.equal(status(`${R}/US/California/LA`), "ok");
  write(work, `${R}/Belgium`, "manual_iana_timezone", "Europe/Brussels");      // the zone Ghent's photos speak against
  assert.equal(status(`${R}/Belgium/Ghent`), "needs");
  assert.equal(status(R), "needs");
  write(work, `${R}/Belgium`, "manual_iana_timezone", "Asia/Tokyo");           // another: the next run checks it
  assert.equal(status(`${R}/Belgium/Ghent`), "ok");
  assert.equal(status(R), "ok");
});
