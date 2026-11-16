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

// The editor's views grouped by what can differ (docs/design/decisions.md): a level only where its members can carry
// different answers; a level of one member folded into its parent; what waits open and first, what is settled folded;
// destination → its own decisions → per-camera ones → single photos. Run with `tools/jstest`.
import { test } from "node:test";
import assert from "node:assert/strict";
import * as app from "../web/app.js";

const D = "6-photos-by-dest/Japan", CAM = "SONY|A7|1", PHONE = "APPLE|iPhone|P";
const placed = (name, by, extra = {}) => ({ relative_path: `${D}/${name}`, content_fingerprint: `fp-${name}`, placed_by: by, ...extra });
const review = (name, reason, extra = {}) => ({ relative_path: `${D}/${name}`, reason, requires_user_input: reason === "no_reliable_gps_source",
  user_decision: { manual_lat: "", manual_lon: "" }, ...extra });
const paths = (ps) => ps.map((x) => x.entry.relative_path.split("/").pop());

test("GPS view: Fallback and Placed buckets, each split by why the tracks missed or how the photo was placed", () => {
  const d = { gps_decisions: { review_items: [review("hand.arw", "manual_locked")], placed_photos: [
    placed("own.arw", "own_position"),
    placed("i1.arw", "tracks", { method: "interpolated" }), placed("i2.arw", "tracks", { method: "interpolated" }),
    placed("pt.arw", "tracks", { method: "direct_match" }),
    placed("f1.arw", "folder_fallback", { tracks: { reason: "outside_track", seconds_from_track: 7200 } }),
    placed("f2.arw", "folder_fallback", { tracks: { reason: "outside_track", seconds_from_track: 9000 } }),
    placed("f3.arw", "folder_fallback", { tracks: { reason: "track_gap", seconds_from_track: 900, gap_seconds: 3600 } }),
    placed("f4.arw", "folder_fallback", { tracks: { reason: "track_gap", seconds_from_track: 800, gap_seconds: 3600 } }),
  ] } };
  const [fb, pl] = app.gpsBuckets(D, d);
  assert.equal(fb.kind, "fallback"); assert.equal(fb.title, "Fallback (4)"); assert.equal(fb.open, false);   // settled: folded
  assert.deepEqual(fb.groups.map((g) => g.label), ["away from the tracks (2)", "in a gap of the tracks (2)"]);
  assert.deepEqual(fb.groups.map((g) => g.photos[0].ref.kind), ["chosen", "chosen"]);   // each keeps "set position"
  assert.equal(pl.kind, "placed"); assert.equal(pl.title, "Placed (5)"); assert.equal(pl.open, false);
  // camera GPS is placed too; a group of one is no group — its photo stands under the bucket, labelled
  assert.deepEqual(pl.groups.map((g) => g.label), ["between points (2)"]);
  assert.deepEqual(pl.photos.map((x) => [x.entry.relative_path.split("/").pop(), x.label]),
    [["own.arw", "camera GPS"], ["pt.arw", "track point"], ["hand.arw", "set by hand"]]);
  assert.equal(pl.photos[0].ref, null);                                 // its own position: no position set here replaces it
  assert.equal(pl.photos[2].ref.kind, "review");
});

test("GPS view: a bucket of one sub-group folds it into its title; Unplaced waits, open and first", () => {
  const d = { gps_decisions: {
    review_items: [review("u1.arw", "no_reliable_gps_source", { tracks: { reason: "no_tracks" } }),
      review("u2.arw", "no_reliable_gps_source", { tracks: { reason: "no_tracks" } })],
    placed_photos: [placed("a.arw", "tracks", { method: "interpolated" }), placed("b.arw", "tracks", { method: "interpolated" })] } };
  const [un, pl] = app.gpsBuckets(D, d);
  assert.deepEqual([un.kind, un.title, un.open, un.groups.length], ["unplaced", "Unplaced (2) · no tracks", true, 0]);
  assert.deepEqual(paths(un.photos), ["u1.arw", "u2.arw"]);
  assert.equal(un.photos[0].ref.kind, "review");
  assert.deepEqual([pl.title, pl.groups.length, paths(pl.photos)], ["Placed (2) · between points", 0, ["a.arw", "b.arw"]]);
  assert.deepEqual(app.gpsBuckets(D, { gps_decisions: { review_items: [] } }), []);    // a container: its fallback row only
});

test("GPS view: a camera day whose photos here all fell back, though the tracks had points that day, is named", () => {
  const day = `${CAM}@2024-07-03`, other = `${CAM}@2024-07-04`, near = { reason: "outside_track", seconds_from_track: 3600 };
  const d = { gps_decisions: { review_items: [], placed_photos: [
    placed("a.arw", "folder_fallback", { camera_bucket: day, tracks: near }),
    placed("b.arw", "folder_fallback", { camera_bucket: day, tracks: { reason: "no_tracks" } }),
    placed("c.arw", "folder_fallback", { camera_bucket: other, tracks: near }),
    placed("d.arw", "tracks", { camera_bucket: other, method: "interpolated" }),          // the tracks placed one of its day
    placed("e.arw", "folder_fallback", { camera_bucket: PHONE, tracks: { reason: "outside_track", seconds_from_track: 200000 } }),
    placed("f.arw", "folder_fallback", { tracks: near }),                                  // no camera day: not counted
  ] } };
  assert.deepEqual(app.fellBackCameras(d), [day]);                      // the phone's nearest point is days away: no offset cures it
  assert.equal(app.cameraDayLabel(day), `${CAM} · 3 Jul 2024`);
  assert.equal(app.cameraDayLabel(PHONE), PHONE);
  // unplaced counts as fallen back too
  const u = { gps_decisions: { review_items: [review("u.arw", "no_reliable_gps_source", { camera_bucket: day, tracks: near })] } };
  assert.deepEqual(app.fellBackCameras(u), [day]);
  assert.equal(app.tracksNearThatDay({ reason: "time_from_date_fallback" }), false);
  assert.equal(app.tracksNearThatDay({ reason: "tracks_disagree", gpx_files: ["a", "b"] }), true);
});

test("Time view: cameras the photos settle fold away; cameras that ask or were answered stay; one camera has no level", () => {
  const settled = { effective_time_anchor: { offset_seconds: -3600, source: "gpx_anchor_auto" }, decision_mode: "auto_resolved",
    requires_user_input: false, user_decision: { accept_proposal: false, accepted_offset_seconds: "", manual_offset_seconds: "" } };
  const asks = { requires_user_input: true, proposal: { proposed_offset_seconds: 0 },
    user_decision: { accept_proposal: false, accepted_offset_seconds: "", manual_offset_seconds: "" } };
  const answered = { ...settled, user_decision: { ...settled.user_decision, manual_offset_seconds: -3500 } };
  const dest = { camera_group_time_decisions: { [CAM]: settled, "NIKON|D750|B": asks, "CANON|R5|C": answered } };
  const s = app.offsetSections(dest);
  assert.deepEqual(s.shown.map((g) => g.group), ["CANON|R5|C", "NIKON|D750|B"]);
  assert.deepEqual(s.settled.map((g) => g.group), [CAM]);
  assert.equal(s.oneCamera, false);
  assert.equal(app.offsetSettledByPhotos(answered), false);
  assert.equal(app.offsetAnswered({ user_decision: { accept_proposal: true, accepted_offset_seconds: 0 } }), true);
  assert.equal(app.offsetAnswered({ user_decision: { keep_as_recorded: false, split: {} } }), false);
  // a camera settled on one day but asking on another is shown, all its days
  const days = { camera_group_time_decisions: { [`${CAM}@2024-07-03`]: { ...settled, camera_group: CAM, date: "2024-07-03" },
    [`${CAM}@2024-07-04`]: { ...asks, camera_group: CAM, date: "2024-07-04" } } };
  const t = app.offsetSections(days);
  assert.deepEqual([t.shown.length, t.settled.length, t.oneCamera], [1, 0, true]);
});
