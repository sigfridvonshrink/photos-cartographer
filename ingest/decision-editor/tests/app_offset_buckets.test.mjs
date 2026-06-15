// Front-end unit tests for the per-date offset bucketing logic (web/app.js §4.4):
// offsetGroups (group by camera group, collapse equal-proposal undecided days), dateRange, peerKeys.
import { test } from "node:test";
import assert from "node:assert/strict";
import * as app from "../web/app.js";

const cell = (group, date, proposedOffset, ud = {}) => ({
  camera_group: group,
  ...(date ? { date } : {}),
  proposal: proposedOffset == null ? { proposal_source: "manual_required" }
    : { proposal_source: "timezone_naive", proposed_offset_seconds: proposedOffset, proposed_from_timezone: "Europe/Brussels" },
  user_decision: ud,
});

test("offsetGroups: single-day common case stays one bare bucket, no date", () => {
  const g = app.offsetGroups({ camera_group_time_decisions: { "CAM": cell("CAM", null, null) } });
  assert.equal(g.length, 1);
  assert.equal(g[0].dated, false);
  assert.equal(g[0].buckets.length, 1);
  assert.equal(g[0].buckets[0].date, null);
});

test("offsetGroups: equal-proposal days collapse, distinct proposals split (summer/winter)", () => {
  const cells = {
    "CAM@2024-07-03": cell("CAM", "2024-07-03", -7200),
    "CAM@2024-07-04": cell("CAM", "2024-07-04", -7200),
    "CAM@2024-12-22": cell("CAM", "2024-12-22", -3600),
  };
  const g = app.offsetGroups({ camera_group_time_decisions: cells });
  assert.equal(g.length, 1);                    // one camera group
  assert.equal(g[0].dated, true);
  assert.equal(g[0].proposals.length, 2);       // summer cluster + winter cluster
  const summer = g[0].proposals.find((p) => p.offset === -7200);
  assert.deepEqual(summer.keys, ["CAM@2024-07-03", "CAM@2024-07-04"]);
  assert.deepEqual(summer.dates, ["2024-07-03", "2024-07-04"]);
  assert.equal(summer.source, "timezone_naive");
  assert.equal(summer.tz, "Europe/Brussels");
  assert.equal(g[0].proposals.find((p) => p.offset === -3600).keys.length, 1);
});

test("offsetGroups: a day with its own decision is NOT pooled with equal-proposal peers", () => {
  const cells = {
    "CAM@2024-07-03": cell("CAM", "2024-07-03", -7200),
    "CAM@2024-07-04": cell("CAM", "2024-07-04", -7200, { manual_offset_seconds: -7200 }),
  };
  const g = app.offsetGroups({ camera_group_time_decisions: cells });
  assert.equal(g[0].proposals.length, 2);       // the decided day breaks out of the cluster
  assert.ok(g[0].proposals.every((p) => p.keys.length === 1));
});

test("offsetGroups: equal-proposal days that share an identical decision stay clustered", () => {
  const cells = {                                  // both summer days accepted → one cluster, still collapsed
    "CAM@2024-07-03": cell("CAM", "2024-07-03", -7200, { accept_proposal: true, manual_offset_seconds: "", manual_real_utc: "" }),
    "CAM@2024-07-04": cell("CAM", "2024-07-04", -7200, { accept_proposal: true, manual_offset_seconds: "", manual_real_utc: "" }),
  };
  const g = app.offsetGroups({ camera_group_time_decisions: cells });
  assert.equal(g[0].proposals.length, 1);
  assert.deepEqual(g[0].proposals[0].keys, ["CAM@2024-07-03", "CAM@2024-07-04"]);
});

test("offsetGroups: same accept decision but DIFFERENT proposals do not merge", () => {
  const cells = {                                  // accepting summer (-7200) vs winter (-3600) stay separate
    "CAM@2024-07-03": cell("CAM", "2024-07-03", -7200, { accept_proposal: true }),
    "CAM@2024-12-22": cell("CAM", "2024-12-22", -3600, { accept_proposal: true }),
  };
  const g = app.offsetGroups({ camera_group_time_decisions: cells });
  assert.equal(g[0].proposals.length, 2);
});

test("offsetGroups: separate camera groups never merge", () => {
  const cells = {
    "CAM@2024-07-03": cell("CAM", "2024-07-03", -7200),
    "OTHER@2024-07-03": cell("OTHER", "2024-07-03", -7200),
  };
  const g = app.offsetGroups({ camera_group_time_decisions: cells });
  assert.deepEqual(g.map((x) => x.group), ["CAM", "OTHER"]);
});

test("offsetGroups: no-proposal days cluster together as one 'needs input' group", () => {
  const cells = {
    "CAM@2024-07-03": cell("CAM", "2024-07-03", null),
    "CAM@2024-07-04": cell("CAM", "2024-07-04", null),
  };
  const g = app.offsetGroups({ camera_group_time_decisions: cells });
  assert.equal(g[0].proposals.length, 1);
  assert.equal(g[0].proposals[0].offset, null);
  assert.equal(g[0].proposals[0].keys.length, 2);
});

test("dateRange: single, range", () => {
  assert.equal(app.dateRange(["2024-07-03"]), "3 Jul 2024");
  assert.equal(app.dateRange(["2024-07-03", "2024-07-04", "2024-12-22"]), "3 Jul 2024 … 22 Dec 2024 (3 days)");
  assert.equal(app.dateRange([]), "");
});

test("peerKeys: cluster ref fans out to its peers, plain ref to itself", () => {
  assert.deepEqual(app.peerKeys({ key: "A", peers: ["A", "B", "C"] }), ["A", "B", "C"]);
  assert.deepEqual(app.peerKeys({ key: "A" }), ["A"]);
});
