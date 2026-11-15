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

// Front-end unit tests for the editor's status + resolution + inheritance-preview logic (web/app.js).
// These read the module-global `state`, so each test sets app.state.work first.
import { test } from "node:test";
import assert from "node:assert/strict";
import * as app from "../web/app.js";

const setWork = (work) => { app.state.work = work; app.state.base = work; };

test("cellStatus maps the system flags", () => {
  assert.deepEqual(app.cellStatus({ requires_user_input: true }), ["needs", "needs input"]);
  assert.deepEqual(app.cellStatus({ stale_user_decision: true }), ["stale", "stale"]);
  assert.deepEqual(app.cellStatus({ decision_mode: "auto_resolved" }), ["auto", "auto"]);
  assert.deepEqual(app.cellStatus({}), ["ok", "resolved"]);
  assert.equal(app.cellStatus(null), null);
  // The optional folder fallback: "resolved" only with an effective value, else "none" (not resolved).
  assert.deepEqual(app.cellStatus({ effective_fallback: { lat: 1, lon: 2 } }), ["ok", "resolved"]);
  assert.deepEqual(app.cellStatus({ effective_fallback: null }), ["none", "none"]);
});

test("wouldResolve: each of the two offset modes is independently sufficient", () => {
  const dest = "6-photos-by-dest/B", key = "CAM", ref = { file: "time", dest, kind: "offset", key };
  const mk = (ud, proposal = {}) => setWork(
    { time: { destinations: { [dest]: { camera_group_time_decisions: { [key]: { user_decision: ud, proposal } } } } } });

  mk({ manual_offset_seconds: -3600 });                                         assert.equal(app.wouldResolve(ref), true);
  mk({ accept_proposal: true, accepted_offset_seconds: -3600 }, { proposed_offset_seconds: -3600 }); assert.equal(app.wouldResolve(ref), true);
  mk({ accept_proposal: true }, { proposed_offset_seconds: -3600 });            assert.equal(app.wouldResolve(ref), false);  // names no offset: accepts nothing
  mk({ accept_proposal: true, accepted_offset_seconds: -3600 }, { proposed_offset_seconds: -7200 }); assert.equal(app.wouldResolve(ref), false);  // accepted another proposal
  mk({ accept_proposal: true, accepted_offset_seconds: -3600 }, { proposed_offset_seconds: -3590, proposal_source: "gpx_self_anchor", acceptance_tolerance_seconds: 120 });
  assert.equal(app.wouldResolve(ref), true);                                     // a GPS proposal within its own spread is the one accepted
  mk({ accept_proposal: true }, {});                                            assert.equal(app.wouldResolve(ref), false);  // nothing to accept
  mk({ manual_offset_seconds: 999999 });                                        assert.equal(app.wouldResolve(ref), true);   // any size
  mk({ manual_offset_seconds: 1.5 });                                           assert.equal(app.wouldResolve(ref), false);  // not whole seconds
  mk({});                                                                       assert.equal(app.wouldResolve(ref), false);
});

test("wouldResolve: a guess far from all evidence is not resolved by its acceptance, only by an offset written", () => {
  const dest = "6-photos-by-dest/B", key = "CAM", ref = { file: "time", dest, kind: "offset", key };
  const far = { proposal_source: "timezone_naive", proposed_offset_seconds: -3600,
    far_from_evidence: { max_clock_error_seconds: 172800, other_photos: 1, nearest_other_photo: "p.heic",
      nearest_other_photo_seconds: 830000000, nearest_track_seconds: "" } };
  const mk = (ud) => setWork(
    { time: { destinations: { [dest]: { camera_group_time_decisions: { [key]: { user_decision: ud, proposal: far } } } } } });
  mk({ accept_proposal: true, accepted_offset_seconds: -3600, manual_offset_seconds: "" });
  assert.equal(app.wouldResolve(ref), false);
  mk({ accept_proposal: false, accepted_offset_seconds: "", manual_offset_seconds: 830000000 });
  assert.equal(app.wouldResolve(ref), true);
});

test("clearing a folder fallback (the Clear button payload) resolves to none", () => {
  const dest = "6-photos-by-dest/Belgium", ref = { file: "gps", dest, kind: "fallback" };
  const mk = (ud, proposal = {}) => setWork(
    { gps: { destinations: { [dest]: { folder_fallback: { user_decision: ud, proposal } } } } });
  mk({ fallback_lat: 50.5, fallback_lon: 4.2 });                              assert.equal(app.wouldResolve(ref), true);   // manual
  mk({ accept_proposal: true }, { proposed_fallback: { lat: 50, lon: 4 } }); assert.equal(app.wouldResolve(ref), true);   // accept inherited
  // The Clear button writes exactly this — clears coord AND the accept flag -> effective none:
  mk({ fallback_lat: "", fallback_lon: "", accept_proposal: false });        assert.equal(app.wouldResolve(ref), false);
});

test("previewTz / previewFallback inherit from the nearest resolved ancestor", () => {
  setWork({
    time: { destinations: {
      "6-photos-by-dest/Japan": { destination_timezone: { proposed_iana_timezone: "Asia/Tokyo", user_decision: { manual_iana_timezone: "Asia/Tokyo" } } },
      "6-photos-by-dest/Japan/Kyoto": { destination_timezone: { user_decision: {} } },
    } },
    gps: { destinations: {
      "6-photos-by-dest/Japan": { folder_fallback: { user_decision: { fallback_lat: 35.0, fallback_lon: 139.0 } } },
      "6-photos-by-dest/Japan/Kyoto": { folder_fallback: { user_decision: {} } },
    } },
  });
  assert.equal(app.previewTz("6-photos-by-dest/Japan").tz, "Asia/Tokyo");
  const inhTz = app.previewTz("6-photos-by-dest/Japan/Kyoto");
  assert.equal(inhTz.tz, "Asia/Tokyo");
  assert.equal(inhTz.source, "inherited");

  const inhFb = app.previewFallback("6-photos-by-dest/Japan/Kyoto");
  assert.deepEqual([inhFb.lat, inhFb.lon, inhFb.source], [35.0, 139.0, "inherited"]);
});

test("timezone: an inherited zone applies itself, the configured default is only proposed", () => {
  const dest = "6-photos-by-dest/Japan", ref = { file: "time", dest, kind: "timezone" };
  const mk = (cell) => setWork({ time: { destinations: { [dest]: { destination_timezone: { user_decision: {}, ...cell } } } } });
  mk({ proposed_iana_timezone: "Asia/Tokyo", proposal_source: "inherited" });  assert.equal(app.wouldResolve(ref), true);
  mk({ proposed_iana_timezone: "Europe/Brussels", proposal_source: "config_default" });
  assert.equal(app.wouldResolve(ref), false);                 // home zone offered, not taken for a trip abroad
  assert.equal(app.previewTz(dest), null);                    // and nothing beneath inherits it
  mk({ proposed_iana_timezone: "Europe/Brussels", proposal_source: "config_default",
       user_decision: { manual_iana_timezone: "Asia/Tokyo" } });
  assert.equal(app.wouldResolve(ref), true);
});

test("a country is chosen once, at the top of its tree; one of several timezones gives none down", () => {
  const y = "6-photos-by-dest/2024", cell = (ud = {}) => ({ destination_timezone: { user_decision: { manual_iana_timezone: "", country: "", ...ud } } });
  const work = { time: { countries: { JP: { name: "Japan", zones: ["Asia/Tokyo"] },
                                     US: { name: "United States", zones: ["America/New_York", "America/Phoenix"] } },
    destinations: {
      [y]: cell({ manual_iana_timezone: "Europe/Bucharest" }),
      [`${y}/Japonia`]: cell({ country: "JP" }), [`${y}/Japonia/Kyoto`]: cell(),
      [`${y}/SUA`]: cell({ country: "US" }), [`${y}/SUA/Arizona`]: cell({ manual_iana_timezone: "America/Phoenix" }),
      [`${y}/SUA/Arizona/Canyon`]: cell({ country: "JP" }), [`${y}/SUA/Oregon`]: cell(),
    } } };
  setWork(work);
  assert.deepEqual(app.effectiveCountry(`${y}/Japonia/Kyoto`), { code: "JP", from: `${y}/Japonia`, zones: ["Asia/Tokyo"] });
  assert.equal(app.effectiveCountry(y), null);
  assert.deepEqual(app.previewTz(`${y}/Japonia/Kyoto`), { tz: "Asia/Tokyo", source: "country", from: `${y}/Japonia` });
  // the choice highest in the tree stands, whatever is written inside it
  assert.equal(app.effectiveCountry(`${y}/SUA/Arizona/Canyon`).code, "US");
  // several timezones: nothing from the country, nothing from above it — only from inside it
  assert.equal(app.previewTz(`${y}/SUA/Oregon`), null);
  assert.equal(app.previewTz(`${y}/SUA/Arizona/Canyon`).tz, "America/Phoenix");
  // a zone written inside a country is one of that country's
  const ref = { file: "time", dest: `${y}/SUA/Oregon`, kind: "timezone" };
  work.time.destinations[`${y}/SUA/Oregon`].destination_timezone.user_decision.manual_iana_timezone = "Europe/Paris";
  assert.equal(app.refInvalid(ref), true);
  work.time.destinations[`${y}/SUA/Oregon`].destination_timezone.user_decision.manual_iana_timezone = "America/Phoenix";
  assert.equal(app.refInvalid(ref), false);
  // choosing a country takes out every one chosen inside it
  assert.deepEqual(app.clearCountriesInside(`${y}/SUA`), [`${y}/SUA/Arizona/Canyon`]);
  assert.equal(work.time.destinations[`${y}/SUA/Arizona/Canyon`].destination_timezone.user_decision.country, "");
  assert.equal(work.time.destinations[`${y}/Japonia`].destination_timezone.user_decision.country, "JP");   // not inside it
  // a country of one timezone resolves the cell by itself
  assert.equal(app.wouldResolve({ file: "time", dest: `${y}/Japonia/Kyoto`, kind: "timezone" }), true);
});

test("previewTz: a zone its photos contradict, not kept, is neither in effect nor passed down", () => {
  const i = "6-photos-by-dest/Iberia", m = `${i}/Madrid`, pr = `${m}/Prado`;
  const k = { timezone: "Europe/Lisbon", recorded_offsets: [7200] };
  const work = { time: { destinations: {
    [i]: { destination_timezone: { user_decision: { manual_iana_timezone: "Europe/Lisbon" } } },
    [m]: { destination_timezone: { proposed_iana_timezone: "Europe/Lisbon", proposal_source: "inherited", contradicted_by: k, user_decision: {} } },
    [pr]: { destination_timezone: { user_decision: {} } },
  } } };
  setWork(work);
  assert.equal(app.previewTz(m), null);
  assert.equal(app.previewTz(pr), null);                     // and nothing inside reaches past it to Iberia's zone
  // kept for those photos: in effect, and inherited below
  work.time.destinations[m].destination_timezone.user_decision.confirmed_despite_recorded_offsets = [7200];
  assert.deepEqual(app.previewTz(pr), { tz: "Europe/Lisbon", source: "inherited", from: m });
  // another zone written here: the next run checks that one, and it passes down
  work.time.destinations[m].destination_timezone.user_decision = { manual_iana_timezone: "Europe/Madrid" };
  assert.deepEqual(app.previewTz(pr), { tz: "Europe/Madrid", source: "inherited", from: m });
  // the zone above changed since the run that checked: the one it now inherits is not the one contradicted
  work.time.destinations[m].destination_timezone.user_decision = {};
  work.time.destinations[i].destination_timezone.user_decision.manual_iana_timezone = "Europe/Madrid";
  assert.equal(app.previewTz(pr).tz, "Europe/Madrid");
});
