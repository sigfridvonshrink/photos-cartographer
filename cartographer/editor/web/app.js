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

// Decision editor. Loads the workspace's decision artifacts into a working copy, lets the human edit
// only the `user_decision` blocks (timezone / offset / fallback / review) with client-side validation,
// override/inherited/edited badges, an advisory effective-outcome preview, and Save (writes
// user_decision back via the server). GPS cells get a side-panel map picker (fixed-crosshair pick) plus
// a photo preview for review items (map.js + the server's /api/photo). The time tree shows a live,
// advisory inheritance preview (a child with no own decision shows the timezone it would inherit from
// its nearest resolved ancestor). The edit loop is: edit → Save → re-run `photos-cartographer geotag plan`
// in a terminal → reload the page (no in-app Re-run).
// Vanilla + ES modules; no build. Leaflet is vendored (global L); tiles come from OSM at runtime.

import { mapPicker } from "./map.js";

const state = { base: null, work: null, view: "time", selected: null, saving: false, message: null, timeChangedSinceRerun: false, driftChangedSinceRerun: false, offsetExpand: new Set(), coordClipboard: null, gpsAnchor: null, gpsAnchorDest: null };

const $ = (s) => document.querySelector(s);
function el(tag, attrs = {}, ...kids) {
  const n = document.createElement(tag);
  for (const [k, v] of Object.entries(attrs)) {
    if (v == null) continue;
    if (k === "class") n.className = v;
    else if (k === "html") n.innerHTML = v;
    else if (k.startsWith("on") && typeof v === "function") n.addEventListener(k.slice(2), v);
    else n.setAttribute(k, v);
  }
  for (const c of kids.flat()) if (c != null) n.append(c.nodeType ? c : document.createTextNode(c));
  return n;
}
const clone = (o) => JSON.parse(JSON.stringify(o));

// --- validation (mirrors decision-json-reference §7) -------------------------
const isNum = (v) => typeof v === "number" && isFinite(v) && typeof v !== "boolean";
// A timezone is checked against the HOST's list — the zones geotag's plan accepts, which the server sends with the
// decisions (`zones`, server.py `_host_zones`) — never the browser's own: a name one knows and the other does not
// (`US/Eastern` on a host without the legacy names) would be saved here and refused by the plan.
let HOST_ZONES = [], HOST_ZONE_SET = new Set();
function setHostZones(zones) { HOST_ZONES = Array.isArray(zones) ? [...zones] : []; HOST_ZONE_SET = new Set(HOST_ZONES); }
function validTz(s) { return s === "" || s == null || HOST_ZONE_SET.has(s); }
function validOffset(v) { return v === "" || v == null || (isNum(v) && Number.isInteger(Number(v))); }
const validLat = (v) => v === "" || v == null || (isNum(v) && v >= -90 && v <= 90);
const validLon = (v) => v === "" || v == null || (isNum(v) && v >= -180 && v <= 180);
const bothOrNeither = (a, b) => (a === "" || a == null) === (b === "" || b == null);
// Parse a "lat, lon" coordinate as copied from Google Maps ("50.5254337, 4.2697812") — comma or
// whitespace separated — into {lat, lon}, or null if it isn't a valid in-range pair. The single
// canonical coordinate parser used by every coordinate input and paste in the editor.
function parseLatLon(s) {
  if (typeof s !== "string") return null;
  const m = s.trim().match(/^(-?\d+(?:\.\d+)?)\s*[,\s]\s*(-?\d+(?:\.\d+)?)$/);
  if (!m) return null;
  const lat = +m[1], lon = +m[2];
  return lat >= -90 && lat <= 90 && lon >= -180 && lon <= 180 ? { lat, lon } : null;
}
// How a coordinate cell's stored decision renders in the single text field: "lat, lon" when both are
// numbers, the raw rejected text when a bad entry was kept (so it stays visible + flagged), else empty.
function coordText(u, la, lo) {
  if (isNum(u[la]) && isNum(u[lo])) return `${u[la]}, ${u[lo]}`;
  if (typeof u[la] === "string" && u[la].trim() !== "") return u[la];
  return "";
}

// --- cell access -------------------------------------------------------------
function cellAt(arts, ref) {
  if (!ref || !arts) return null;
  if (ref.file === "time") {
    const d = arts.time?.destinations?.[ref.dest]; if (!d) return null;
    if (ref.kind === "reading") return d.local_time_readings?.[ref.key];
    if (ref.kind === "unidentified") return d.unidentified_files;
    if (ref.kind === "changed") return d.changed_times?.[ref.key];
    if (ref.kind === "date") return d.date_fallback;
    return ref.kind === "timezone" ? d.destination_timezone : d.camera_group_time_decisions?.[ref.key];
  }
  if (ref.file === "drift") {
    const d = arts.drift?.destinations?.[ref.dest]; if (!d) return null;
    return d.drift_decisions?.[ref.key];
  }
  if (ref.file === "cameras")                  // a camera group the configuration does not class, by its key; or a
    // fixed-clock camera group, whether it is several bodies (BLD-editor_marks_several_bodies)
    return (ref.kind === "bodies" ? arts.cameras?.bodies?.[ref.key] : arts.cameras?.groups?.[ref.key]) || null;
  if (ref.file === "execution")                // photos-25: a photo whose content changed after a write, by its path
    return (arts.execution?.fingerprint_mismatches || []).find((m) => m && m.relative_path === ref.path) || null;
  const d = arts.gps?.destinations?.[ref.dest]; if (!d) return null;
  if (ref.kind === "fallback") return d.folder_fallback;
  if (ref.kind === "chosen")                   // a photo the tracks or the fallback place, given a position of its own
    return (d.gps_decisions?.placed_photos || []).find((r) => r.relative_path === ref.path);
  return (d.gps_decisions?.review_items || []).find((r) => r.relative_path === ref.path);
}
// photos-23 lists the photos the tracks or the fallback place (`placed_photos`) without a decision: each is given an
// empty `user_decision` here, the position the user may set for that photo alone. Saved, it becomes a review item
// `chosen_by_user` (BLD-chosen_position). Applied to the record as loaded, so base and work start equal. Pure.
function withChosenCells(art) {
  for (const d of Object.values(art?.gps?.destinations || {}))
    for (const p of d?.gps_decisions?.placed_photos || [])
      if (p && !p.user_decision) p.user_decision = { manual_lat: "", manual_lon: "" };
  return art;
}
// What a review item offers, in order (BLD-chosen_position, docs/design/decisions.md): a photo nothing places is
// offered its folder's fallback FIRST — set once, it places every unplaced photo of the folder, and below it once
// accepted there — and a position for this photo alone second. Any other item offers the photo's own position. Pure.
function reviewOffers(c) {
  if (c && c.reason === "no_reliable_gps_source") return ["folder_fallback", "position"];
  return ["position"];
}
// How a photo of photos-23's `placed_photos` is placed, as its row says it. Pure.
const placedByLabel = (pp) => (pp && pp.placed_by === "folder_fallback" ? "fallback" : "tracks");
// The folded list's heading: how many photos the tracks and the fallback place. Pure.
function placedSummary(placed) {
  const n = (placed || []).length, fb = (placed || []).filter((p) => p && p.placed_by === "folder_fallback").length;
  const parts = [n - fb ? `${n - fb} by the tracks` : null, fb ? `${fb} by the fallback` : null].filter(Boolean);
  return `${n} placed — ${parts.join(", ")}: set a position for one`;
}
const workCell = (ref) => cellAt(state.work, ref);
const baseCell = (ref) => cellAt(state.base, ref);

function allRefs() {
  const out = [];
  for (const key of Object.keys(state.work.cameras?.groups || {})) out.push({ file: "cameras", kind: "camera", key });
  for (const key of Object.keys(state.work.cameras?.bodies || {})) out.push({ file: "cameras", kind: "bodies", key });
  for (const [dest, d] of Object.entries(state.work.time?.destinations || {})) {
    out.push({ file: "time", dest, kind: "timezone" });
    if (d.date_fallback) out.push({ file: "time", dest, kind: "date" });
    for (const key of Object.keys(d.camera_group_time_decisions || {})) out.push({ file: "time", dest, kind: "offset", key });
    for (const key of Object.keys(d.local_time_readings || {})) out.push({ file: "time", dest, kind: "reading", key });
    for (const key of Object.keys(d.changed_times || {})) out.push({ file: "time", dest, kind: "changed", key });
    if (d.unidentified_files) out.push({ file: "time", dest, kind: "unidentified" });
  }
  for (const [dest, d] of Object.entries(state.work.drift?.destinations || {})) {
    for (const key of Object.keys(d.drift_decisions || {})) out.push({ file: "drift", dest, kind: "drift", key });
  }
  for (const [dest, d] of Object.entries(state.work.gps?.destinations || {})) {
    out.push({ file: "gps", dest, kind: "fallback" });
    for (const ri of d.gps_decisions?.review_items || []) out.push({ file: "gps", dest, kind: "review", path: ri.relative_path });
    for (const pp of d.gps_decisions?.placed_photos || []) out.push({ file: "gps", dest, kind: "chosen", path: pp.relative_path });
  }
  for (const m of state.work.execution?.fingerprint_mismatches || [])
    if (m && m.relative_path) out.push({ file: "execution", kind: "fingerprint", path: m.relative_path });
  return out;
}
function isDirty(ref) {
  const w = workCell(ref), b = baseCell(ref);
  return w && b && JSON.stringify(w.user_decision) !== JSON.stringify(b.user_decision);
}
function refInvalid(ref) {
  const c = workCell(ref); if (!c) return false; const u = c.user_decision || {};
  if (ref.kind === "timezone") {
    const k = effectiveCountry(ref.dest);            // a zone written inside a country is one of that country's
    return !validTz(u.manual_iana_timezone) || (!!u.manual_iana_timezone && !!k && k.zones.length > 0 && !k.zones.includes(u.manual_iana_timezone));
  }
  if (ref.kind === "offset") return !validOffset(u.manual_offset_seconds);
  if (ref.kind === "date") return !validDateFallback(u.date);
  if (ref.kind === "reading") return !validReading(c, u.utc_offset_seconds);
  if (ref.kind === "drift") return !validOffset(u.corrected_offset_seconds);
  if (ref.kind === "fingerprint") return typeof u.accept_fingerprint_change !== "boolean";
  if (ref.kind === "camera") return !["", ...DEVICE_CLASSES].includes(u.device_class ?? "");
  if (ref.kind === "bodies") return typeof u.several_bodies !== "boolean";
  if (ref.kind === "changed") return !["", ...CHANGED_ANSWERS].includes(u.keep ?? "");
  if (ref.kind === "fallback") return !validLat(u.fallback_lat) || !validLon(u.fallback_lon) || !bothOrNeither(u.fallback_lat, u.fallback_lon);
  return !validLat(u.manual_lat) || !validLon(u.manual_lon) || !bothOrNeither(u.manual_lat, u.manual_lon);
}
// A destination's date fallback (photos-21 date_fallback, BLD-date_fallback_cell): "YYYY", "YYYY-MM" or "YYYY-MM-DD", a
// day the calendar has; the month and day left out are the first. The day it stands for as "YYYY-MM-DD", or null — the
// same check geotag makes (`date_fallback_day`). Pure — unit-tested.
function dateFallbackDay(v) {
  const m = typeof v === "string" ? /^([0-9]{4})(?:-([0-9]{2})(?:-([0-9]{2}))?)?$/.exec(v) : null;
  if (!m) return null;
  const y = +m[1], mo = m[2] ? +m[2] : 1, d = m[3] ? +m[3] : 1;
  if (y < 1 || mo < 1 || mo > 12 || d < 1) return null;
  const t = new Date(Date.UTC(2000, mo - 1, d)); t.setUTCFullYear(y);
  if (t.getUTCFullYear() !== y || t.getUTCMonth() !== mo - 1 || t.getUTCDate() !== d) return null;
  return `${m[1]}-${String(mo).padStart(2, "0")}-${String(d).padStart(2, "0")}`;
}
const validDateFallback = (v) => v === "" || v == null || dateFallbackDay(v) !== null;
// A photo's answer for a time its zone skips or repeats (photos-21 local_time_readings, BLD-local_time_readings): a whole
// number of seconds within ±14 h; for a time shown twice, one of its two readings. Empty = not answered.
function validReading(c, v) {
  if (v === "" || v == null) return true;
  if (!isNum(v) || !Number.isInteger(v) || Math.abs(v) > 14 * 3600) return false;
  return c.case !== "repeated" || (c.offsets_seconds || []).includes(v);
}
const dirtyRefs = () => allRefs().filter(isDirty);
const anyInvalid = () => allRefs().some(refInvalid);
// --- per-date offset buckets (decision-json-reference §4.4) -------------------
// A destination's `camera_group_time_decisions` is keyed by the bare camera group for the single-day
// common case, or `<group>@<YYYY-MM-DD>` per day when the group spans >1 naive date there (a camera set
// to local time each morning has a per-day offset). Group those buckets by camera group, then collapse
// undecided buckets that share the SAME proposed offset into one actionable cluster (equal proposals —
// e.g. all summer days — confirm together; winter falls into its own cluster). A bucket with its own
// user_decision stays its own cluster so a divergent manual day is never hidden. Pure logic — unit-tested.
function offsetGroups(destCell) {
  const cells = destCell?.camera_group_time_decisions || {};
  const byGroup = new Map();
  for (const key of Object.keys(cells)) {
    const c = cells[key], g = c.camera_group || key;
    if (c.clock_change_part) continue;                     // a part of a day split at a clock change: shown on its day
    if (!byGroup.has(g)) byGroup.set(g, []);
    byGroup.get(g).push({ key, cell: c, date: c.date || null });
  }
  const out = [];
  for (const group of [...byGroup.keys()].sort()) {
    const buckets = byGroup.get(group).sort((a, b) => (a.date || "") < (b.date || "") ? -1 : (a.date || "") > (b.date || "") ? 1 : 0);
    // Cluster by (decision signature, proposed offset): undecided equal-proposal days collapse together;
    // days sharing an identical decision (e.g. both "accept proposal") stay collapsed after editing; a
    // day with a divergent manual decision breaks out into its own row so it is never hidden.
    const byProp = new Map();                              // cluster key → member buckets
    for (const b of buckets) {
      const u = b.cell.user_decision || {}, p = b.cell.proposal || {};
      const udSig = `${u.accept_proposal === true ? 1 : 0}|${u.accepted_offset_seconds ?? ""}|${u.manual_offset_seconds ?? ""}` +
        (b.cell.clock_change ? `|change:${b.key}` : "");      // a day whose clock changed is a row of its own
      const pk = `${udSig}@${"proposed_offset_seconds" in p ? p.proposed_offset_seconds : "none"}`;
      if (!byProp.has(pk)) byProp.set(pk, []);
      byProp.get(pk).push(b);
    }
    const proposals = [...byProp.values()].map((members) => {
      const p = members[0].cell.proposal || {};
      return { keys: members.map((m) => m.key), dates: members.map((m) => m.date).filter(Boolean),
        offset: "proposed_offset_seconds" in p ? p.proposed_offset_seconds : null,
        source: p.proposal_source || null, tz: p.proposed_from_timezone || null };
    });
    out.push({ group, dated: buckets.some((b) => b.date), buckets, proposals });
  }
  return out;
}
// Compact a sorted list of YYYY-MM-DD dates: single → "3 Jul 2024", contiguous-ish range → "3–7 Jul",
// else "first … last". Purely for the row label of a collapsed multi-day cluster.
function dateRange(dates) {
  const ds = (dates || []).filter(Boolean);
  if (!ds.length) return "";
  if (ds.length === 1) return fmtDate(ds[0]);
  return `${fmtDate(ds[0])} … ${fmtDate(ds[ds.length - 1])} (${ds.length} days)`;
}
function fmtDate(iso) {
  const m = /^(\d{4})-(\d\d)-(\d\d)$/.exec(iso || ""); if (!m) return iso || "";
  const mon = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"][+m[2] - 1];
  return `${+m[3]} ${mon} ${m[1]}`;
}

// --- edit + status -----------------------------------------------------------
// Time edits invalidate the GPS decisions (GPS placement is computed from resolved UTC), and GPS is
// only recomputed on a Re-run — so flag any time change to drive the GPS-view stale/lock notices below.
// Time edits invalidate drift + GPS; drift edits invalidate GPS. Both are only recomputed on Re-run,
// so flag each to drive the downstream stale notices.
const touchChange = (ref) => {
  if (ref.file === "time") state.timeChangedSinceRerun = true;
  if (ref.file === "drift") state.driftChangedSinceRerun = true;
};
// A ref may stand for SEVERAL sibling cells via `ref.peers` — a collapsed per-date offset cluster (peers
// are bucket keys) or a multi-selected run of GPS review photos (peers are relative paths). An edit fans
// out identically to all of them so one action resolves the whole set. The identifying field differs by
// kind: review cells are addressed by `path`, everything else by `key`. A ref with no peers edits itself.
const peerField = (ref) => (ref.kind === "review" || ref.kind === "chosen" ? "path" : "key");
const peerKeys = (ref) => (ref.peers && ref.peers.length ? ref.peers : [ref[peerField(ref)]]);
const peerRefs = (ref) => peerKeys(ref).map((id) => ({ ...ref, [peerField(ref)]: id, peers: undefined }));
const eachPeer = (ref, fn) => { for (const r of peerRefs(ref)) { const c = cellAt(state.work, r); if (c) fn(c, r); } };
function edit(ref, field, value) { touchChange(ref); eachPeer(ref, (c) => { c.user_decision[field] = value; }); render(); }
function editMany(ref, obj) { touchChange(ref); eachPeer(ref, (c) => Object.assign(c.user_decision, obj)); render(); }
function resetRef(ref) {
  for (const r of peerRefs(ref)) { const w = cellAt(state.work, r), b = cellAt(state.base, r); if (w && b) w.user_decision = clone(b.user_decision); }
  render();
}

function cellStatus(cell) {
  if (!cell) return null;
  // a photos-25 fingerprint mismatch carries no flags: it asks until its changed content is accepted
  if ("actual_fingerprint" in cell) return mismatchAccepted(cell) ? ["ok", "accepted"] : ["needs", "needs input"];
  if (cell.requires_user_input) return ["needs", "needs input"];
  if (cell.stale_user_decision) return ["stale", "stale"];
  if (cell.decision_mode === "auto_resolved") return ["auto", "auto"];
  // The folder fallback is OPTIONAL (requires_user_input is always false), so "resolved" must mean it
  // actually has an effective value — otherwise an unset fallback wrongly reads as resolved and that
  // tag propagates to descendants. `effective_fallback` is the field unique to the fallback cell.
  if ("effective_fallback" in cell) return cell.effective_fallback ? ["ok", "resolved"] : ["none", "none"];
  return ["ok", "resolved"];
}
const chip = (k, t) => el("span", { class: `chip ${k}` }, t);
// Would the WORKING decision resolve this cell? (advisory — mirrors the reference §6 resolution rules.)
function wouldResolve(ref) {
  const c = workCell(ref); if (!c) return false;
  const u = c.user_decision || {}, p = c.proposal || {};
  if (ref.kind === "timezone")
    return ((!!u.manual_iana_timezone && validTz(u.manual_iana_timezone))
      || tzOwnDecision(ref.dest)?.source === "country"                         // a country of one timezone gives it
      || (!!c.proposed_iana_timezone && c.proposal_source === "inherited"))   // an inherited zone applies itself...
      && zoneSpokenFor(c);                                                     // ...unless the photos here say otherwise
  if (ref.kind === "offset")
    return (u.manual_offset_seconds !== "" && u.manual_offset_seconds != null && validOffset(u.manual_offset_seconds))
      || keepHolds(c)                                           // a phone kept as it records itself
      || clockChangeHolds(c)                                    // the day split where its clock changed
      || (acceptHolds(c) && !p.far_from_evidence && !inConflict(c));   // far from all evidence, or one clock read two
                                                                // ways the same day: an acceptance is withheld again
  if (ref.kind === "reading")
    return u.utc_offset_seconds !== "" && u.utc_offset_seconds != null && validReading(c, u.utc_offset_seconds);
  if (ref.kind === "unidentified") return unidentifiedHolds(ref.dest, c);
  if (ref.kind === "date") return !!previewDate(ref.dest);           // a date given here, or one in effect above
  if (ref.kind === "fingerprint") return mismatchAccepted(c);
  if (ref.kind === "camera") return DEVICE_CLASSES.includes(u.device_class);
  if (ref.kind === "bodies") return typeof u.several_bodies === "boolean";   // a setting: either answer stands
  if (ref.kind === "changed") return changedHolds(c);
  if (ref.kind === "drift")                       // confirmed for this offset (zero-scrub or a valid correction)
    return driftConfirmHolds(c) && validOffset(u.corrected_offset_seconds);
  if (ref.kind === "fallback")
    return (u.fallback_lat !== "" && u.fallback_lat != null && u.fallback_lon !== "" && u.fallback_lon != null)
      || (!!u.accept_proposal && !!p.proposed_fallback);
  if (c.reason === "own_position_contradicted") return true;      // its own position kept, or the one set for it
  if (ref.kind === "chosen") return true;                         // the tracks or the fallback place it already
  return (u.manual_lat !== "" && u.manual_lat != null && u.manual_lon !== "" && u.manual_lon != null)
    || (c.reason === "no_reliable_gps_source" && !!fbOwnDecision(ref.dest));   // its folder's fallback places it
}
function statusChip(ref) {
  if (isDirty(ref)) {                          // a pending edit supersedes the last run's status
    if (refInvalid(ref)) return null;          // the ✗ invalid chip (tags) already speaks
    if (wouldResolve(ref)) return chip("ok", "resolved");
    if (ref.kind === "fallback") return chip("none", "none");  // a cleared/empty working fallback is "none", not the old base status
  }
  const s = cellStatus(baseCell(ref));
  return s ? chip(s[0], s[1]) : null;
}

function fmtOffset(s) {
  if (s === "" || s == null) return "—"; const n = Math.abs(s), sign = s < 0 ? "−" : "+";
  return `${sign}${Math.floor(n / 3600)}h ${String(Math.floor(n % 3600 / 60)).padStart(2, "0")}m ${String(n % 60).padStart(2, "0")}s`;
}

// Offset ⟷ real-UTC conversion. The offset is the one stored value; UTC is just the anchor frame's
// real instant (camera_naive + offset) rendered as a clock. All math is on naive wall-times treated as
// UTC epoch ms (Date.UTC), matching geotag's `real_utc_naive − camera_naive` (cartographer._geotag_calc).
const _pad = (n) => String(n).padStart(2, "0");
function camNaiveMs(s) { // camera EXIF naive "YYYY:MM:DD HH:MM:SS"
  const m = /^(\d{4}):(\d\d):(\d\d)[ T](\d\d):(\d\d):(\d\d)/.exec(s || "");
  return m ? Date.UTC(+m[1], +m[2] - 1, +m[3], +m[4], +m[5], +m[6]) : null;
}
function dtLocalToMs(s) { // <input type=datetime-local> value "YYYY-MM-DDTHH:MM(:SS)?", read as UTC wall time
  const m = /^(\d{4})-(\d\d)-(\d\d)T(\d\d):(\d\d)(?::(\d\d))?$/.exec(s || "");
  return m ? Date.UTC(+m[1], +m[2] - 1, +m[3], +m[4], +m[5], m[6] ? +m[6] : 0) : null;
}
function msToDtLocal(ms) { // UTC epoch ms → datetime-local value
  const d = new Date(ms);
  return `${d.getUTCFullYear()}-${_pad(d.getUTCMonth() + 1)}-${_pad(d.getUTCDate())}T${_pad(d.getUTCHours())}:${_pad(d.getUTCMinutes())}:${_pad(d.getUTCSeconds())}`;
}
function utcStrToMs(s) { const ms = Date.parse(s || ""); return isFinite(ms) ? ms : null; }
function fmtLocal(ms, tz) { // the real instant rendered in destination-local wall time
  try { return new Intl.DateTimeFormat("en-GB", { timeZone: tz, dateStyle: "medium", timeStyle: "medium" }).format(new Date(ms)); }
  catch { return null; }
}
function fmtDT(ms, tz) { // {date,time} in `tz`, the two halves formatted identically for both sides of an arrow
  try {
    return {
      date: new Intl.DateTimeFormat("en-GB", { timeZone: tz, day: "2-digit", month: "short", year: "numeric" }).format(new Date(ms)),
      time: new Intl.DateTimeFormat("en-GB", { timeZone: tz, hour: "2-digit", minute: "2-digit", second: "2-digit", hour12: false }).format(new Date(ms)),
    };
  } catch { return null; }
}
// The human-readable impact of an offset on the anchor photo: its current (camera) local time → the
// corrected local time, with the corrected UTC in parentheses after. Date shown once when invariant;
// any side whose date differs carries its own. With no resolved timezone, corrected is shown as UTC.
function offsetImpact(camMs, offsetSec, tz) {
  if (camMs == null || offsetSec == null) return null;
  const realMs = camMs + offsetSec * 1000, cam = fmtDT(camMs, "UTC"), utc = fmtDT(realMs, "UTC");
  const utcStr = utc.date === cam.date ? utc.time : `${utc.date} ${utc.time}`;
  const cor = tz ? fmtDT(realMs, tz) : null;
  if (!cor) return `${cam.date} · ${cam.time} → ${utcStr} UTC`;
  const right = cor.date === cam.date ? cor.time : `${cor.date} ${cor.time}`;
  return `${cam.date} · ${cam.time} → ${right} (${tz}, UTC ${utcStr})`;
}
// A true time typed for a photo, in its destination's zone: the wall-clock reading of an instant in `tz`, and back.
// Wall times are epoch ms read as UTC (as camNaiveMs gives them). With no zone the wall time is UTC. Pure — unit-tested.
function utcToZonedWallMs(ms, tz) {
  if (ms == null || !isFinite(ms)) return null;
  if (!tz) return ms;
  try {
    const parts = Object.fromEntries(new Intl.DateTimeFormat("en-US", { timeZone: tz, hourCycle: "h23", year: "numeric",
      month: "2-digit", day: "2-digit", hour: "2-digit", minute: "2-digit", second: "2-digit" })
      .formatToParts(new Date(ms)).map((x) => [x.type, x.value]));
    return Date.UTC(+parts.year, +parts.month - 1, +parts.day, +parts.hour, +parts.minute, +parts.second);
  } catch { return null; }
}
// The one instant a wall time names in `tz`, or null: a time the zone's clocks skipped, or showed twice at a
// daylight-saving change, names none or two — never one of them guessed.
function zonedWallToUtcMs(wallMs, tz) {
  if (wallMs == null) return null;
  if (!tz) return wallMs;
  const offs = new Set();
  for (const probe of [wallMs - 86400000, wallMs, wallMs + 86400000]) {
    const w = utcToZonedWallMs(probe, tz);
    if (w == null) return null;
    offs.add(w - probe);
  }
  const hits = new Set([...offs].map((o) => wallMs - o).filter((u) => utcToZonedWallMs(u, tz) === wallMs));
  return hits.size === 1 ? [...hits][0] : null;
}
// The clock offset a photo's true time gives: that time (a datetime-local value, in `tz`) − the photo's camera time,
// in seconds — what is written as manual_offset_seconds. Null for a time that is none, or names no one instant.
function offsetFromTrueTime(camNaive, trueValue, tz) {
  const cam = camNaiveMs(camNaive), utc = zonedWallToUtcMs(dtLocalToMs(trueValue), tz);
  return cam == null || utc == null ? null : Math.round((utc - cam) / 1000);
}
// The true time an offset gives a photo, as a datetime-local value in `tz` — what the field shows. Null if none.
function trueTimeOf(camNaive, offsetSec, tz) {
  const cam = camNaiveMs(camNaive);
  if (cam == null || offsetSec == null || !isFinite(offsetSec)) return null;
  const w = utcToZonedWallMs(cam + offsetSec * 1000, tz);
  return w == null ? null : msToDtLocal(w);
}
// --- GPS-drift scrub math (BLD-drift_validation) -----------------------------
// Placing a photo at a GPX track point fixes the camera→UTC offset: offset = (that point's UTC time)
// − (the photo's camera-naive time), in seconds. Both are naive wall-times read as UTC epoch ms, the
// same convention as the pipeline's `resolved_utc_naive − camera_naive`. Pure — unit-tested.
function scrubOffset(point, frame) {
  const t = utcStrToMs(point && point.time_utc), n = camNaiveMs(frame && frame.camera_naive);
  return t == null || n == null ? null : Math.round((t - n) / 1000);
}
// The track index a photo currently sits at under `currentOffset` — where the scrub marker starts, so
// "don't move" = the current placement and any scroll is a deliberate correction.
function scrubSeedIndex(track, frame, currentOffset) {
  const n = camNaiveMs(frame && frame.camera_naive);
  if (!Array.isArray(track) || !track.length || n == null || currentOffset == null) return 0;
  const target = n + currentOffset * 1000;
  let best = 0, bestD = Infinity;
  track.forEach((p, i) => { const d = Math.abs((utcStrToMs(p.time_utc) ?? target) - target); if (d < bestD) { bestD = d; best = i; } });
  return best;
}
let _driftFrame = 0, _driftCellKey = null;   // which bucket frame the scrub view shows (earliest default); reset on cell change
let _driftTab = "photo";                     // drift sub-tab: "photo" (choose representative) | "map" (scrub track); resets to photo per cell

// advisory effective preview (NOT authoritative — geotag recomputes on re-run)
function previewEffective(ref) {
  const c = workCell(ref), u = c.user_decision || {}, p = c.proposal || {};
  if (ref.kind === "timezone") {
    if (u.manual_iana_timezone) return validTz(u.manual_iana_timezone) ? u.manual_iana_timezone : "✗ invalid zone";
    const pv = previewTz(ref.dest);
    if (pv && pv.source === "inherited") return `${pv.tz} (inherited ⟵ ${leaf(pv.from)}, preview)`;
    if (c.proposal_source === "config_default" && c.proposed_iana_timezone)
      return `— (proposed: ${c.proposed_iana_timezone}, the configured default — use it or pick another)`;
    return "— (needs input)";
  }
  if (ref.kind === "offset") {
    if (u.manual_offset_seconds !== "" && u.manual_offset_seconds != null) {
      if (!validOffset(u.manual_offset_seconds)) return "✗ invalid offset";
      // one of the GPS groups, picked: geotag records it as anchored (gpx_anchor_chosen), not as a manual guess
      const picked = (p.groups || []).some((g) => g.offset_seconds === Number(u.manual_offset_seconds));
      return `${fmtOffset(u.manual_offset_seconds)} (${picked ? "GPS group, picked" : "manual"})`;
    }
    if (keepHolds(c)) return "as the phone records itself (its own GPS set aside)";
    if (clockChangeHolds(c)) return `split where the clock changed: ${fmtOffset(c.clock_change.runs[0].offset_seconds)} before, ` +
      `${fmtOffset(c.clock_change.runs[1].offset_seconds)} after`;
    if (u.accept_clock_change && c.clock_change && !clockChangeHolds(c))
      return !clockChangePartsGiven(c) ? "— (say which part each photo without GPS belongs to)"
        : "— (accepted another change — accept again)";
    if (acceptHolds(c) && p.far_from_evidence) return "— (accepting is not enough here — set the offset)";
    if (acceptHolds(c) && inConflict(c)) return "— (an acceptance is withheld here — take the offset as your own)";
    if (acceptHolds(c)) return `${fmtOffset(p.proposed_offset_seconds)} (accept proposal)`;
    if (u.accept_proposal) return "— (accepted another proposal — accept again)";
    return "— (GPX auto-resolves on re-run, else needs input)";
  }
  if (ref.kind === "date") {
    if (!validDateFallback(u.date)) return "✗ not a date";
    const pv = previewDate(ref.dest);
    if (!pv) return (c.untimed_photos || []).length ? "— (needs input: a date, or move these photos out)" : "— (none)";
    return `${pv.date} — ${pv.filled} 00:00:00 local` + (pv.source === "inherited" ? ` (inherited ⟵ ${leaf(pv.from)}, preview)` : "");
  }
  if (ref.kind === "unidentified") {
    if (unidentifiedHolds(ref.dest, c)) return `read as local time in ${u.accepted_timezone}`;
    if (u.accept_proposal) return "— (accepted for another timezone — accept again)";
    return "— (needs input)";
  }
  if (ref.kind === "reading") {
    const v = u.utc_offset_seconds;
    if (v === "" || v == null) return "— (needs input)";
    if (!validReading(c, v)) return c.case === "repeated" ? "✗ not one of its two readings" : "✗ invalid offset";
    return `${utcOff(v)} — ${trueInstant(c.camera_time, v)}`;
  }
  if (ref.kind === "drift") {
    if (!u.confirmed) return "— (needs confirmation)";
    if (!driftConfirmHolds(c)) return driftStaleReason(c) === "tracks"
      ? "— (confirmed against other tracks — confirm again)" : "— (confirmed for another offset — confirm again)";
    if (u.corrected_offset_seconds === "" || u.corrected_offset_seconds == null)
      return `${fmtOffset(p.current_offset_seconds)} (confirmed — offset was right)`;
    return validOffset(u.corrected_offset_seconds)
      ? `${fmtOffset(u.corrected_offset_seconds)} (corrected)` : "✗ invalid offset";
  }
  if (ref.kind === "changed") return !changedHolds(c) ? (u.keep ? "— (answered for another time — answer again)" : "— (needs input)")
    : u.keep === "new" ? `keeps ${timePair(c.held_time)} — the true local time, no clock offset applied`
      : `geotag's time written back${c.geotag_wrote ? ` (${timePair(c.geotag_wrote)})` : ""}`;
  if (ref.kind === "bodies") return u.several_bodies
    ? "several bodies — written into several_bodies_groups: an offset from its GPS is always a proposal"
    : "one camera — an offset its GPS agrees on applies itself as the configuration allows";
  if (ref.kind === "camera") return u.device_class === "phones" ? "a phone — written into device_groups.phones"
    : u.device_class === "fixed_clock_cameras" ? "a camera with a hand-set clock — written into device_groups.fixed_clock_cameras"
      : "— (needs input: geotag stops until it is classed)";
  if (ref.kind === "fingerprint") return mismatchAccepted(c)
    ? "accepted — the next `geotag execute` takes this content as the photo's, and goes on with it"
    : "— (held: its writes and rename wait for an answer)";
  if (ref.kind === "fallback") {
    if (u.fallback_lat !== "" && u.fallback_lon !== "") return `${u.fallback_lat}, ${u.fallback_lon}`;
    if (u.accept_proposal && p.proposed_fallback) return `${p.proposed_fallback.lat}, ${p.proposed_fallback.lon} (inherited)`;
    const pv = previewFallback(ref.dest);
    if (pv && pv.source === "inherited") return `${pv.lat}, ${pv.lon} (inherited ⟵ ${leaf(pv.from)}, preview)`;
    return "— (optional)";
  }
  if (u.manual_lat !== "" && u.manual_lat != null && u.manual_lon !== "" && u.manual_lon != null)
    return `${u.manual_lat}, ${u.manual_lon} (manual)`;
  if (c.reason === "own_position_contradicted") return "its own position kept";
  if (ref.kind === "chosen") return c.placed_by === "folder_fallback" ? "placed by its folder's fallback" : "placed by the tracks";
  const fb = fbOwnDecision(ref.dest);
  if (fb) return `${fb.lat}, ${fb.lon} (its folder's fallback)`;
  return "— (needs its folder's fallback, or a position for this photo)";
}

// --- advisory timezone inheritance preview -----------------------------------
// Mirrors geotag's rule for DISPLAY ONLY: a child timezone with no own decision would, on re-run,
// inherit from its nearest ancestor that resolves. Updates live as you edit ancestors; authoritative only
// after Re-run. A zone written by hand is the one decision a timezone takes; an inherited one applies itself,
// the configured default is only proposed — so a destination's own value is its manual zone or nothing.
const leaf = (p) => (p || "").split("/").pop();
// --- a country, chosen once at the top of its tree (RUL-country_chosen_once) ---
const tzCell = (dest) => state.work.time?.destinations?.[dest]?.destination_timezone;
const countryInfo = (code) => (state.work.time?.countries || {})[code] || null;
// The country in effect at `dest` in the WORKING decisions: the one chosen highest above it, or at it.
// {code, from, zones} or null. The choice highest in the tree stands; nothing inside it chooses another.
function effectiveCountry(dest) {
  const parts = dest.split("/");
  for (let i = 1; i <= parts.length; i++) {
    const at = parts.slice(0, i).join("/"), code = tzCell(at)?.user_decision?.country;
    if (code) return { code, from: at, zones: countryInfo(code)?.zones || [] };
  }
  return null;
}
// Choosing a country at `dest` takes out every country chosen inside it. Returns the destinations it was
// taken out of, for the warning. Mutates the working decisions.
function clearCountriesInside(dest) {
  const out = [];
  for (const [d, v] of Object.entries(state.work.time?.destinations || {})) {
    const u = v.destination_timezone?.user_decision;
    if (d.startsWith(dest + "/") && u && u.country) { u.country = ""; out.push(d); }
  }
  return out;
}
function tzOwnDecision(dest) {
  const c = tzCell(dest);
  if (!c) return null;
  const u = c.user_decision || {};
  if (u.manual_iana_timezone) return { tz: u.manual_iana_timezone, source: "manual" };
  const k = effectiveCountry(dest);                  // a country of one timezone: that is the zone
  if (k && k.zones.length === 1) return { tz: k.zones[0], source: "country", from: k.from };
  return null;
}
// A destination whose own photos record another offset than the zone it would take — the one the last run checked —
// and where the user has not kept that zone for them, takes no zone, and passes none down: what lies inside it does
// not reach past it to the zone its photos contradict (geotag's _ZONE_WAITS in build_time_decisions).
const TZ_WAITS = { waits: true };
function zoneWaits(dest, tz) {
  const c = tzCell(dest), k = c && c.contradicted_by;
  return !!k && tz === k.timezone && !zoneSpokenFor(c);
}
function tzWalk(dest) {
  let got = tzOwnDecision(dest);
  if (!got) {
    const parts = dest.split("/");
    const k = effectiveCountry(dest);
    for (let i = parts.length - 1; i > 0; i--) {
      const anc = parts.slice(0, i).join("/");
      // a country of several timezones gives none to what lies inside it, and lets none through from above
      if (k && k.zones.length > 1 && (anc === k.from || !anc.startsWith(k.from + "/"))) break;
      if (state.work.time?.destinations?.[anc]) {
        const a = tzWalk(anc);
        if (a === TZ_WAITS) break;                   // the destination above waits on its own photos: so does this
        if (a && a.tz) { got = { tz: a.tz, source: "inherited", from: anc }; break; }
      }
    }
  }
  return got && zoneWaits(dest, got.tz) ? TZ_WAITS : got;   // the configured default is proposed, never in effect
}
function previewTz(dest) {
  const r = tzWalk(dest);
  return r === TZ_WAITS ? null : r;
}
// The date fallback in effect at `dest` in the WORKING decisions — written there, else the nearest above it, which
// applies itself (RUL-date_fallback_from_nearest): {date, filled, source, from}, or null. Pure over state.
function previewDate(dest) {
  const dests = state.work.time?.destinations || {}, parts = dest.split("/");
  for (let i = parts.length; i > 0; i--) {
    const at = parts.slice(0, i).join("/"), v = dests[at]?.date_fallback?.user_decision?.date;
    if (at in dests && v !== "" && v != null) {
      const filled = dateFallbackDay(v);
      return filled ? { date: v, filled, source: at === dest ? "own" : "inherited", from: at } : null;
    }
  }
  return null;
}
// Whether a destination's time-view row shows its date fallback: where it, or a destination inside it, holds a photo
// with no recorded time, or a date is written there. The cell is in the record for every destination. Pure over state.
function showsDate(dest) {
  const dests = state.work.time?.destinations || {}, own = dests[dest]?.date_fallback;
  if (!own) return false;
  if ((own.user_decision?.date ?? "") !== "") return true;
  return Object.entries(dests).some(([d, v]) => (d === dest || d.startsWith(dest + "/")) && (v.date_fallback?.untimed_photos || []).length);
}
// Same advisory walk for the GPS folder-fallback: a destination with no own fallback shows the one it
// would inherit from its nearest resolved ancestor (e.g. a parent/container you just set), updating live.
function fbOwnDecision(dest) {
  const c = state.work.gps?.destinations?.[dest]?.folder_fallback;
  if (!c) return null;
  const u = c.user_decision || {};
  if (u.fallback_lat !== "" && u.fallback_lat != null && u.fallback_lon !== "" && u.fallback_lon != null)
    return { lat: u.fallback_lat, lon: u.fallback_lon, source: "manual" };
  if (u.accept_proposal && c.proposal?.proposed_fallback)
    return { lat: c.proposal.proposed_fallback.lat, lon: c.proposal.proposed_fallback.lon, source: "accept" };
  return null;
}
function previewFallback(dest) {
  const own = fbOwnDecision(dest);
  if (own) return own;
  const parts = dest.split("/");
  for (let i = parts.length - 1; i > 0; i--) {
    const anc = parts.slice(0, i).join("/");
    if (state.work.gps?.destinations?.[anc]) {
      const a = previewFallback(anc);
      if (a) return { lat: a.lat, lon: a.lon, source: "inherited", from: anc };
    }
  }
  return null;
}

// --- list views --------------------------------------------------------------
function isSel(ref) {
  const s = state.selected;
  if (!s || s.file !== ref.file || s.dest !== ref.dest || s.kind !== ref.kind) return false;
  const id = ref[peerField(ref)];                         // highlight the primary AND any peer in a multi-selection
  return s[peerField(s)] === id || !!(s.peers && s.peers.includes(id));
}
function tags(ref) {
  const out = [];
  if (ref.kind === "timezone") {
    const pv = previewTz(ref.dest);                       // live preview, updates as ancestors change
    if (pv && pv.source === "inherited") out.push(chip("inherited", `inherited ⟵ ${leaf(pv.from)}`));
  } else if (ref.kind === "fallback") {
    const pv = previewFallback(ref.dest);                 // live preview, updates as ancestors change
    if (pv && pv.source === "inherited") out.push(chip("inherited", `inherited ⟵ ${leaf(pv.from)}`));
  } else if (ref.kind === "date") {
    const pv = previewDate(ref.dest);                     // live preview, updates as ancestors change
    if (pv && pv.source === "inherited") out.push(chip("inherited", `inherited ⟵ ${leaf(pv.from)}`));
  }                                                       // offsets never inherit (RUL-offset_from_own_evidence)
  if (isDirty(ref)) out.push(chip("edited", "edited"));
  if (refInvalid(ref)) out.push(chip("invalid", "✗ invalid"));
  return out;
}
function row(ref, label, sub, eff) {
  return el("div", { class: "row" + (isSel(ref) ? " sel" : ""), onclick: () => { state.selected = ref; render(); } },
    el("span", { class: "label" }, label, sub ? el("span", { class: "sub" }, "  " + sub) : null),
    eff ? el("span", { class: "eff" }, eff) : null, ...tags(ref), statusChip(ref));
}

function buildTree(dests) {
  const root = { seg: "", path: "", children: {}, dest: null };
  for (const path of Object.keys(dests).sort()) {
    let node = root, acc = "";
    for (const s of path.split("/")) { acc = acc ? acc + "/" + s : s; node.children[s] = node.children[s] || { seg: s, path: acc, children: {}, dest: null }; node = node.children[s]; }
    node.dest = dests[path];
  }
  return root;
}
function renderTreeNode(node, box) {
  const n = el("div", { class: "node" });
  if (node.dest) {
    n.append(el("div", { class: "dest" }, node.seg || "(root)",
      node.dest.file_less ? el("span", { class: "container-tag", title: "no photos here — its decisions only set defaults for sub-destinations" }, "container") : null));
    const tzpv = previewTz(node.path);
    n.append(row({ file: "time", dest: node.path, kind: "timezone" }, "Timezone", null, tzpv ? tzpv.tz : "—"));
    if (showsDate(node.path)) {
      const dpv = previewDate(node.path), k = (node.dest.date_fallback.untimed_photos || []).length;
      n.append(row({ file: "time", dest: node.path, kind: "date" }, "Date fallback",
        k ? `${k} photo${k === 1 ? "" : "s"} with no time` : null, dpv ? dpv.date : "—"));
    }
    renderOffsetRows(node.path, node.dest, n);
    if (node.dest.unidentified_files) {
      const q = node.dest.unidentified_files;
      n.append(row({ file: "time", dest: node.path, kind: "unidentified" }, "Files naming no camera",
        `${q.files} file${q.files === 1 ? "" : "s"}`, q.effective_iana_timezone ? leaf(q.effective_iana_timezone) : "—"));
    }
    for (const [key, cc] of Object.entries(node.dest.changed_times || {}))
      n.append(row({ file: "time", dest: node.path, kind: "changed", key }, "Time changed since geotag", leaf(key), timePair(cc.held_time)));
    for (const [key, rc] of Object.entries(node.dest.local_time_readings || {}))
      n.append(row({ file: "time", dest: node.path, kind: "reading", key }, "Time at a clock change", leaf(key),
        rc.effective_utc_offset_seconds === "" || rc.effective_utc_offset_seconds == null ? "—" : utcOff(rc.effective_utc_offset_seconds)));
  }
  const kids = Object.keys(node.children).sort();
  if (kids.length) { const w = el("div", { class: "kids" }); for (const k of kids) renderTreeNode(node.children[k], w); n.append(w); }
  box.append(n);
}
// One selectable offset row. `keys` is the bucket(s) it stands for — >1 ⇒ a collapsed equal-proposal
// cluster that edits all its days at once (`ref.peers`). `pr` supplies the cluster's proposal so a
// timezone-derived row is labelled with its source zone.
function offsetRow(dest, keys, sub, cell, pr, indent) {
  const ref = { file: "time", dest, kind: "offset", key: keys[0] };
  if (keys.length > 1) ref.peers = keys;
  const e = cell.effective_time_anchor;
  const eff = e && typeof e === "object" ? (e.source === "as_recorded" ? "as recorded" : fmtOffset(e.offset_seconds))
    : "proposed_offset_seconds" in (cell.proposal || {}) ? `${fmtOffset(cell.proposal.proposed_offset_seconds)} proposed` : "—";
  if (cell.phone) sub = `${sub} · phone`;
  const s =pr && pr.source === "timezone_naive" && pr.tz ? `${sub} · from ${leaf(pr.tz)}`
    : pr && pr.source === "recorded_offset" ? `${sub} · as recorded`
      : pr && pr.source === "gps_time" ? `${sub} · from GPS time` : sub;
  const r = row(ref, "Offset", s, eff);
  if (indent) r.classList.add("off-sub");
  return r;
}
// Render a destination's offset decisions. Single-day common case → one plain row. A group spanning >1
// naive date → a header + one row per distinct proposal, equal proposals collapsed into a single
// multi-day cluster row (a chevron expands it to per-day rows for divergent manual edits).
function renderOffsetRows(dest, destCell, n) {
  const cells = destCell.camera_group_time_decisions || {};
  for (const g of offsetGroups(destCell)) {
    if (g.buckets.length === 1 && !g.buckets[0].date) { n.append(offsetRow(dest, [g.buckets[0].key], g.group, g.buckets[0].cell, null, false)); continue; }
    n.append(el("div", { class: "offset-grp" }, `Offset · ${g.group}`, el("span", { class: "sub" }, `  ${g.buckets.length} days`)));
    for (const pr of g.proposals) {
      if (pr.keys.length === 1) { const k = pr.keys[0]; n.append(offsetRow(dest, [k], fmtDate(cells[k].date) || g.group, cells[k], pr, true)); continue; }
      const expKey = `${dest}|${pr.keys.join(",")}`;
      if (!state.offsetExpand.has(expKey)) {
        const r = offsetRow(dest, pr.keys, dateRange(pr.dates), cells[pr.keys[0]], pr, true);
        r.prepend(el("span", { class: "off-chevron", title: "show each day", onclick: (e) => { e.stopPropagation(); state.offsetExpand.add(expKey); render(); } }, "▸"));
        n.append(r);
      } else {
        n.append(el("div", { class: "off-collapse", onclick: () => { state.offsetExpand.delete(expKey); render(); } }, `▾ ${dateRange(pr.dates)} — collapse`));
        for (const k of pr.keys) n.append(offsetRow(dest, [k], fmtDate(cells[k].date), cells[k], pr, true));
      }
    }
  }
}
// What a view shows of a record it has nothing to list from: the record absent, or — a record that is there but cannot
// be read (the server's `_error`) — that, said as it is, never as "no file": a record a hand broke is still the answers.
function recordAbsentText(art, name) {
  if (art && art._error) return `${art._error} — repair it by hand (or restore it from a -NNN backup), then reload; ` +
    "geotag stops on it too, and leaves it as it is.";
  return `No ${name}.`;
}
function recordAbsent(art, name) {
  return art && art._error ? el("div", { class: "gate warn" }, el("div", { class: "gate-title" }, `${name} cannot be read`),
    recordAbsentText(art, name)) : el("div", { class: "empty" }, recordAbsentText(art, name));
}
function renderTime(list) {
  const t = state.work.time;
  if (!t?.destinations) return list.append(recordAbsent(t, "photos-21-time-decisions.json"));
  if (!state.base.demo && state.timeChangedSinceRerun)
    list.append(el("div", { class: "gate warn" }, "Time decisions changed — re-run `photos-cartographer geotag plan` (in a terminal), then reload, so GPS is recomputed from the new times."));
  const root = buildTree(t.destinations);
  for (const k of Object.keys(root.children).sort()) renderTreeNode(root.children[k], list);
}
// The contiguous run of `order` between `anchor` and `target` inclusive (either direction), or null if
// either is absent — the set a shift-click multi-selection covers. Pure logic — unit-tested.
function contiguousRange(order, anchor, target) {
  const i = order.indexOf(anchor), j = order.indexOf(target);
  if (i < 0 || j < 0) return null;
  const [a, b] = i <= j ? [i, j] : [j, i];
  return order.slice(a, b + 1);
}
// Select a GPS review photo. A plain click selects one and sets the range anchor; a shift-click extends
// to a CONTIGUOUS run from the anchor — but only within the SAME destination's worklist (a shift-click in
// another destination just starts a fresh single selection), so a multi-selection never crosses a
// destination boundary. A run of >1 becomes a `peers` ref whose edits fan out to every photo in it.
function selectReview(ev, dest, path, order) {
  const base = { file: "gps", dest, kind: "review", path };
  if (ev.shiftKey && state.gpsAnchor && state.gpsAnchorDest === dest) {
    const run = contiguousRange(order, state.gpsAnchor, path);
    if (run && run.length > 1) { state.selected = { ...base, path: run[0], peers: run }; render(); return; }
  }
  state.gpsAnchor = path; state.gpsAnchorDest = dest; state.selected = base; render();
}
function renderGps(list) {
  const g = state.work.gps;
  // GPS placement is derived from each photo's resolved UTC, so the GPS phase is gated on the time
  // decisions: geotag only (re)generates photos-23 once every time decision is resolved. Make
  // that gate visible rather than showing an empty or stale GPS view.
  if (!state.base.demo && state.work.time?.requires_user_input)
    return list.append(el("div", { class: "gate" },
      el("div", { class: "gate-title" }, "GPS is waiting on the time decisions"),
      "GPS placement (interpolation / extrapolation) is computed from each photo's resolved UTC, so the GPS "
      + "decisions are generated only once every timezone and clock-offset decision is resolved. Finish them in "
      + "the Time view, then re-run `photos-cartographer geotag plan` and reload."));
  if (!state.base.demo && state.work.drift?.requires_user_input)
    return list.append(el("div", { class: "gate" },
      el("div", { class: "gate-title" }, "GPS is waiting on the drift validation"),
      "A manual or timezone-derived clock offset with no native-GPS anchor must be confirmed against the GPX "
      + "track before placement, or it could silently mis-place the whole batch. Confirm each bucket in the "
      + "Drift view, then re-run `photos-cartographer geotag plan` and reload."));
  if (!g?.destinations) return list.append(recordAbsent(g, "photos-23-gps-decisions.json"));
  if (!state.base.demo && (state.timeChangedSinceRerun || state.driftChangedSinceRerun))
    list.append(el("div", { class: "gate warn" }, "Time or drift decisions changed since the last geotag run — re-run `photos-cartographer geotag plan` and reload to recompute GPS. The decisions below are stale until you do."));
  for (const dest of Object.keys(g.destinations).sort()) {
    const d = g.destinations[dest], fb = d.folder_fallback, s = d.gps_decisions?.summary || {};
    list.append(el("div", { class: "group-title" }, dest,
      d.file_less ? el("span", { class: "container-tag", title: "no photos here — its fallback only seeds sub-destinations" }, "container") : null));
    const fbpv = previewFallback(dest);
    list.append(row({ file: "gps", dest, kind: "fallback" }, "Folder fallback", null,
      fb.effective_fallback ? `${fb.effective_fallback.lat}, ${fb.effective_fallback.lon}` : (fbpv ? `${fbpv.lat}, ${fbpv.lon}` : "—")));
    const order = (d.gps_decisions?.review_items || []).map((ri) => ri.relative_path);
    for (const ri of d.gps_decisions?.review_items || []) {
      const ref = { file: "gps", dest, kind: "review", path: ri.relative_path };
      list.append(el("div", { class: "row" + (isSel(ref) ? " sel" : ""), onclick: (ev) => selectReview(ev, dest, ri.relative_path, order),
          onmouseenter: (ev) => showHoverPreview(ri.relative_path, ev), onmousemove: moveHoverPreview, onmouseleave: hideHoverPreview },
        el("span", { class: "label" }, ri.relative_path.split("/").pop()), chip("reason", ri.reason), ...tags(ref), statusChip(ref)));
    }
    // The photos the tracks or the fallback place, folded: each can be given a position of its own (`set position`),
    // which outranks both (BLD-chosen_position). Folded, since nothing about them waits (docs/design/decisions.md).
    const placed = d.gps_decisions?.placed_photos || [];
    if (placed.length) {
      const fold = el("details", { class: "placed", open: (state.openPlaced || []).includes(dest) ? "" : null,
        ontoggle: (ev) => { const o = new Set(state.openPlaced || []); ev.target.open ? o.add(dest) : o.delete(dest); state.openPlaced = [...o]; } },
        el("summary", {}, placedSummary(placed)));
      for (const pp of placed) {
        const ref = { file: "gps", dest, kind: "chosen", path: pp.relative_path };
        fold.append(el("div", { class: "row" + (isSel(ref) ? " sel" : ""),
            onmouseenter: (ev) => showHoverPreview(pp.relative_path, ev), onmousemove: moveHoverPreview, onmouseleave: hideHoverPreview },
          el("span", { class: "label" }, pp.relative_path.split("/").pop()), chip("reason", placedByLabel(pp)), ...tags(ref),
          isDirty(ref) ? statusChip(ref) : null,
          el("button", { class: "mini", onclick: () => { state.selected = ref; render(); } }, "set position")));
      }
      list.append(fold);
    }
    list.append(el("div", { class: "summary" }, `${s.files_total ?? 0} files — preserve ${s.preserve_native_gps ?? 0}, interp ${s.automatic_gpx_interpolation ?? 0}, extrap ${s.automatic_gpx_extrapolation ?? 0}, fallback ${s.automatic_folder_fallback ?? 0}, blocked ${s.blocked ?? 0}`));
  }
}

function renderDrift(list) {
  const dr = state.work.drift;
  // Drift sits between time and GPS: it can only be validated once the time decisions are complete
  // (the offsets it checks must exist), and it itself gates GPS. Mirror the time→GPS gate.
  if (!state.base.demo && state.work.time?.requires_user_input)
    return list.append(el("div", { class: "gate" },
      el("div", { class: "gate-title" }, "Drift validation is waiting on the time decisions"),
      "The GPS-drift check validates each bucket's clock offset against the GPX track, so it is generated "
      + "only once every timezone and clock-offset decision is resolved. Finish them in the Time view, then re-run `photos-cartographer geotag plan` and reload."));
  if (!dr?.destinations) return list.append(recordAbsent(dr, "photos-22-gps-drift-validation.json"));
  if (!state.base.demo && state.timeChangedSinceRerun)
    list.append(el("div", { class: "gate warn" }, "Time decisions changed since the last geotag run — re-run `photos-cartographer geotag plan` and reload so the drift buckets (and their track segments) are re-extracted. The buckets below are stale until you do."));
  const dests = Object.keys(dr.destinations);
  if (!dests.length) return list.append(el("div", { class: "empty" }, "No at-risk buckets — every offset is GPX-anchored or independently placeable."));
  for (const dest of dests.sort()) {
    const d = dr.destinations[dest];
    list.append(el("div", { class: "group-title" }, dest));
    for (const [key, cell] of Object.entries(d.drift_decisions || {})) {
      const ref = { file: "drift", dest, kind: "drift", key };
      const sub = `${cell.proposal?.proposal_source || "?"} · ${fmtOffset(cell.proposal?.current_offset_seconds ?? 0)}`
        + (cell.date ? ` · ${fmtDate(cell.date)}` : "");
      list.append(row(ref, `Drift · ${cell.camera_group || key}`, sub, null));
    }
  }
}

// A camera group the configuration does not class — geotag stops on it before it writes any decision
// (BLD-known_camera_group). Its answer is the array of camera_time_and_timezone_policy.device_groups the group is written
// into (BLD-editor_writes_device_groups); the snippet geotag prints, to paste by hand, says the same.
const DEVICE_CLASSES = ["phones", "fixed_clock_cameras"];
function renderCameras(list) {
  const cams = state.work.cameras;
  if (!cams || cams._error) return list.append(recordAbsent(cams, "photos-00-config.json"));
  const keys = Object.keys(cams.groups || {}).sort();
  if (!keys.length) {
    list.append(el("div", { class: "empty" }, "Every camera group of the photos is classed in photos-00-config.json."));
    return renderBodies(list);
  }
  list.append(el("div", { class: "hint" }, "Geotag stops on a camera it has not met: say whether each is a phone (its clock set by the " +
    "network, its offset recorded with each photo) or a camera with a clock set by hand. Saving writes it into " +
    "photos-00-config.json (camera_time_and_timezone_policy.device_groups), as pasting geotag's lists would; then re-run `geotag plan`."));
  for (const key of keys) {
    const g = cams.groups[key], ref = { file: "cameras", kind: "camera", key };
    const who = Object.values(g.identity || {}).join(" ");
    list.append(el("div", { class: "row" + (isSel(ref) ? " sel" : ""), onclick: () => { state.selected = ref; render(); },
        onmouseenter: (ev) => showHoverPreview((g.examples || [])[0], ev), onmousemove: moveHoverPreview, onmouseleave: hideHoverPreview },
      el("span", { class: "label" }, who || key, el("span", { class: "sub" }, `  ${g.files} photo${g.files === 1 ? "" : "s"}`)),
      ...tags(ref), statusChip(ref)));
  }
  renderBodies(list);
}
// Each fixed-clock camera group of the photos, one camera or several bodies of one model that write no serial
// (camera_time_and_timezone_policy.several_bodies_groups, BLD-editor_marks_several_bodies): a setting, by default one
// camera — never a question that waits. Saved like a new group's class, into photos-00-config.json.
function renderBodies(list) {
  const bodies = state.work.cameras?.bodies || {}, keys = Object.keys(bodies).sort();
  if (!keys.length) return;
  list.append(el("div", { class: "group-title" }, "Cameras with a hand-set clock"));
  list.append(el("div", { class: "hint" }, "Two bodies of one model that write no serial are one group. Mark such a group as several " +
    "bodies: an offset its GPS gives is then always a proposal, and its photos that disagree are not read as wrong positions. " +
    "To tell the bodies apart, move one body's photos into a sub-folder and re-run prep."));
  for (const key of keys) {
    const g = bodies[key], ref = { file: "cameras", kind: "bodies", key };
    const who = Object.values(g.identity || {}).join(" ");
    list.append(el("div", { class: "row" + (isSel(ref) ? " sel" : ""), onclick: () => { state.selected = ref; render(); },
        onmouseenter: (ev) => showHoverPreview((g.examples || [])[0], ev), onmousemove: moveHoverPreview, onmouseleave: hideHoverPreview },
      el("span", { class: "label" }, who || key, el("span", { class: "sub" },
        `  ${g.files} photo${g.files === 1 ? "" : "s"}${(g.user_decision || {}).several_bodies ? " · several bodies" : ""}`)),
      ...tags(ref), statusChip(ref)));
  }
}
function bodiesControls(ref) {
  const c = workCell(ref), u = c.user_decision || {}, wrap = el("div", { class: "ctl-block" });
  wrap.append(el("div", { class: "hint" }, `${c.files} photo${c.files === 1 ? "" : "s"} under photos by destination, e.g. ` +
    `${(c.examples || []).map(leaf).join(", ")}.`));
  const opt = (on, label) => el("div", { class: "off-opt" + (u.several_bodies === on ? " on" : ""), onclick: () => edit(ref, "several_bodies", on) },
    el("span", { class: "off-dot" }, u.several_bodies === on ? "●" : "○"), el("span", {}, label));
  wrap.append(opt(false, "one camera — the default"));
  wrap.append(opt(true, "several bodies of one model — never apply an offset from its GPS by itself"));
  return wrap;
}
function cameraControls(ref) {
  const c = workCell(ref), u = c.user_decision || {}, wrap = el("div", { class: "ctl-block" });
  wrap.append(el("div", { class: "hint" }, `${c.files} photo${c.files === 1 ? "" : "s"} under photos by destination, e.g. ` +
    `${(c.examples || []).map(leaf).join(", ")}.`));
  const opt = (cls, label) => el("div", { class: "off-opt" + (u.device_class === cls ? " on" : ""), onclick: () => edit(ref, "device_class", cls) },
    el("span", { class: "off-dot" }, u.device_class === cls ? "●" : "○"), el("span", {}, label));
  wrap.append(opt("phones", "a phone — its clock is the network's, its offset recorded with each photo"));
  wrap.append(opt("fixed_clock_cameras", "a camera with a clock set by hand — its offset found per day"));
  return wrap;
}

// photos-25's fingerprint mismatches: a photo whose decoded content was not what the plan expected once geotag wrote to
// it, its writes unconfirmed and its rename held back until the user accepts the content as it now is
// (user_decision.accept_fingerprint_change, BLD-execution_summary). The next `geotag execute` of the same plan reads it.
function mismatchAccepted(c) {
  return !!c && (c.user_decision || {}).accept_fingerprint_change === true && !!c.actual_fingerprint;
}
function renderExecution(list) {
  const x = state.work.execution;
  if (!x) return list.append(el("div", { class: "empty" }, "No photos-25-execution-summary.json — geotag has not executed here yet."));
  if (x._error) return list.append(recordAbsent(x, "photos-25-execution-summary.json"));
  const ms = (x.fingerprint_mismatches || []).filter((m) => m && m.relative_path);
  if (!ms.length) return list.append(el("div", { class: "empty" }, "No photo's content changed when geotag wrote to it."));
  list.append(el("div", { class: "hint" }, `The last \`geotag execute\` (plan ${x.plan_id || "?"}) found these photos' content ` +
    "changed when it wrote to them: their writes are not confirmed and their rename waits. Accept each whose content is " +
    "right as it is now, save, and run `geotag execute` again."));
  for (const m of ms) {
    const ref = { file: "execution", kind: "fingerprint", path: m.relative_path };
    list.append(el("div", { class: "row" + (isSel(ref) ? " sel" : ""), onclick: () => { state.selected = ref; render(); },
        onmouseenter: (ev) => showHoverPreview(m.relative_path, ev), onmousemove: moveHoverPreview, onmouseleave: hideHoverPreview },
      el("span", { class: "label" }, leaf(m.relative_path), el("span", { class: "sub" }, "  " + m.relative_path.split("/").slice(0, -1).join("/"))),
      ...tags(ref), statusChip(ref)));
  }
}
function mismatchControls(ref) {
  const c = workCell(ref), u = c.user_decision || {}, wrap = el("div", { class: "ctl-block" });
  const fp = (v) => (v ? String(v).slice(0, 16) + "…" : "none");
  wrap.append(el("div", { class: "hint warn" }, `Expected fingerprint ${fp(c.expected_fingerprint)}; after geotag wrote to it, ` +
    `${c.actual_fingerprint ? fp(c.actual_fingerprint) : "none could be taken"}. The photo's pixels are not what the plan pinned: ` +
    "look at it — if it is right as it is, accept it."));
  if (!c.actual_fingerprint) wrap.append(el("div", { class: "hint" }, "With no fingerprint taken there is nothing to accept: " +
    "put the photo right, then run `geotag execute` again."));
  else wrap.append(checkbox("accept this photo's content as it is now", u.accept_fingerprint_change === true,
    (v) => edit(ref, "accept_fingerprint_change", v)));
  return wrap;
}

// --- editing controls --------------------------------------------------------
function checkbox(label, checked, onchange, disabled) {
  const cb = el("input", { type: "checkbox", disabled: disabled ? "" : null }); cb.checked = !!checked; cb.addEventListener("change", () => onchange(cb.checked));
  return el("label", { class: disabled ? "ctl-check disabled" : "ctl-check" }, cb, label);
}

function tzSelect(value, onchange, disabled, only) {
  const cur = value || "", zones = only && only.length ? only : HOST_ZONES;
  const opts = [el("option", { value: "" }, "— none —"), ...zones.map((z) => el("option", { value: z }, z))];
  // Keep a pre-existing value the host doesn't know about visible/selectable rather than silently dropping it.
  if (cur && !zones.includes(cur)) opts.splice(1, 0, el("option", { value: cur }, cur + " (unknown)"));
  const sel = el("select", { class: validTz(cur) ? null : "bad", disabled: disabled ? "" : null }, ...opts);
  sel.value = cur;
  sel.addEventListener("change", () => onchange(sel.value));
  return sel;
}

// Offset editor: the h/m/s spinner and a real-UTC datetime picker are two views of one stored value
// (manual_offset_seconds). Whichever view you click drives editing; the other goes read-only and tracks
// it. The UTC view only exists for a gpx_self_anchor proposal (it needs the anchor frame's camera time);
// editing always stores the offset. The clock offset is set in exactly ONE of two mutually-exclusive ways
// — accept the proposal, or an offset of your own, typed or picked as the anchor frame's real-UTC — mapped
// to the two user_decision fields (accept_proposal / manual_offset_seconds). Picking one resets the other,
// so the reference §6 precedence never has to arbitrate.
// Two exclusive choices: ACCEPT the proposal (the automatic offset) or SET IT YOURSELF. The self-set
// offset has two ALWAYS-VISIBLE, ALWAYS-SYNCED views — the h/m/s spinner and the anchor real-UTC picker
// (picker = anchor camera time + offset); editing either updates both. They're editable only while
// self-set is the active choice; otherwise they're read-only but still show the effective offset (so
// nothing is hidden), and clicking either switches to self-set seeded from it. A common Impact line
// shows what the effective offset does to the anchor photo. Stored canonically as manual_offset_seconds.
function offsetEditor(ref) {
  const c = workCell(ref), u = c.user_decision, p = c.proposal || {};
  const isGpx = p.proposal_source === "gpx_self_anchor";
  const camMs = isGpx && p.anchors && p.anchors[0] ? camNaiveMs(p.anchors[0].camera_source_naive_time) : null;
  const hasProp = "proposed_offset_seconds" in p;
  const far = !!p.far_from_evidence;                  // accepting it would not take effect (offsetCellNotes says why)
  // Representative camera-naive instant for the Impact line — the anchor frame's time for a GPX proposal,
  // else recovered from a timezone-derived proposal (camera_naive = proposed_real_utc − proposed_offset),
  // so the per-date / timezone buckets also show "camera local → corrected local" with the common date.
  const repCamMs = camMs != null ? camMs
    : (hasProp && p.proposed_real_utc != null && utcStrToMs(p.proposed_real_utc) != null
      ? utcStrToMs(p.proposed_real_utc) - p.proposed_offset_seconds * 1000 : null);
  const conflict = inConflict(c);                     // one clock read two ways: the proposal is taken as the user's own
  const accepted = acceptHolds(c) && !conflict;
  const manualOff = u.manual_offset_seconds;          // the one stored value of a self-set offset
  const manualSet = manualOff !== "" && manualOff != null;
  const selKey = `${ref.dest}|${ref.key}`;
  // Exactly one choice is active. For a self-set value the active VIEW (offset spinner, anchor-UTC picker or
  // a photo's true time) is a per-cell UI state; default to the spinner. The automatic (accept) value is
  // never edited — it's always the proposal. Clicking a choice activates it; the other manual view
  // updates to show the active value (synced), the automatic stays the proposal.
  const mine = state.offsetEdit && state.offsetEdit.key === selKey ? state.offsetEdit : null;
  const view = mine ? mine.view : "offset";
  // A proposal accepting which is not enough (far from all evidence) is never the value shown, nor seeded into an
  // offset of the user's own: a click on a view opens it empty, and only a value typed there is written.
  // In a same-day conflict the proposal taken is the user's own offset: shown as the proposal taken until a view is opened.
  const ownTaken = conflict && manualSet && Number(manualOff) === p.proposed_offset_seconds && !mine;
  const active = (accepted && !far) || ownTaken ? "accept" : manualSet ? view : far && mine && mine.open ? view : "";
  const eff = accepted && !far ? p.proposed_offset_seconds : manualSet ? Number(manualOff)
    : (hasProp && !far ? p.proposed_offset_seconds : null);
  const cur = Number(eff) || 0, abs = Math.abs(cur);

  const setManual = (off, v) => { state.offsetEdit = { key: selKey, view: v }; editMany(ref, { ...acceptFields(p, false), manual_offset_seconds: off, ...unkept(c) }); };
  const choose = (v) => {
    state._focusOffset = v;
    if (manualSet || far) { state.offsetEdit = { key: selKey, view: v, open: true }; render(); } else setManual(eff ?? 0, v);
  };
  const accept = () => { state.offsetEdit = null; editMany(ref, { ...proposalTaken(c), ...unkept(c) }); };
  const opt = (on, body, onclick, cls = "") => el("div", { class: "off-opt" + (on ? " on" : "") + cls, onclick },
    el("span", { class: "off-dot" }, on ? "●" : "○"), body);

  const wrap = el("div", { class: "ctl-block" });
  let numI, pickI, trueI;

  // choice 1 — accept the proposal (automatic; its value is never edited)
  const src = p.proposal_source === "timezone_naive" ? ` from timezone ${p.proposed_from_timezone}`
    : p.proposal_source === "recorded_offset" ? " as the photos record it"
      : p.proposal_source === "gps_time" ? " from the GPS fixes' own times" : "";
  const canAccept = hasProp && !far;
  wrap.append(opt(active === "accept",
    el("span", {}, !hasProp ? "accept proposal — none to accept"
      : far ? `accept proposal (${fmtOffset(p.proposed_offset_seconds)}) — not enough here: set the offset`
        : conflict ? `use the proposal (${fmtOffset(p.proposed_offset_seconds)}) as your own offset${src}`
          : `accept proposal (${fmtOffset(p.proposed_offset_seconds)})${src}`),
    canAccept ? accept : undefined, canAccept ? "" : " disabled"));

  if (u.accept_proposal && !accepted && hasProp) wrap.append(el("div", { class: "hint warn" },
    `Accepted when the proposal was ${u.accepted_offset_seconds === "" || u.accepted_offset_seconds == null ? "another one" : fmtOffset(u.accepted_offset_seconds)}; it is now ${fmtOffset(p.proposed_offset_seconds)} — accept it again, or set the offset.`));

  // choice 2 — manual offset (h/m/s spinner). Editable only when active; otherwise click to activate.
  const editO = active === "offset";
  const bump = (secs, dir) => setManual(cur + dir * secs, "offset");
  const unit = (label, secs, value) => {
    const box = el("div", { class: "spin-unit", tabindex: editO ? "0" : null,
      title: editO ? `scroll or ↑/↓ to adjust ${label}` : "click to set the offset" },
      el("div", { class: "spin-unit-val" }, String(value).padStart(2, "0")), el("div", { class: "spin-unit-lbl" }, label));
    if (editO) {
      box.addEventListener("wheel", (e) => { e.preventDefault(); bump(secs, e.deltaY < 0 ? 1 : -1); }, { passive: false });
      box.addEventListener("keydown", (e) => { if (e.key !== "ArrowUp" && e.key !== "ArrowDown") return; e.preventDefault(); bump(secs, e.key === "ArrowUp" ? 1 : -1); });
    }
    return box;
  };
  const units = el("div", { class: "spin-units" + (editO ? "" : " ro") + (validOffset(manualOff) ? "" : " bad") },
    el("span", { class: "spin-sign" }, cur < 0 ? "−" : "+"),
    unit("h", 3600, Math.floor(abs / 3600)), el("span", { class: "spin-colon" }, ":"),
    unit("m", 60, Math.floor(abs / 60) % 60), el("span", { class: "spin-colon" }, ":"),
    unit("s", 1, abs % 60));
  numI = el("input", { type: "number", step: "1", class: "spin-num", readonly: editO ? null : "", value: eff == null ? "" : eff });
  if (editO) numI.addEventListener("change", () => setManual(numI.value === "" ? "" : Number(numI.value), "offset"));
  wrap.append(opt(editO, el("div", { class: "ctl-field off-field" }, el("span", {}, "manual offset"),
    el("div", { class: "spin-wrap" }, units, numI)), editO ? undefined : () => choose("offset")));
  if (editO && !validOffset(manualOff)) wrap.append(el("div", { class: "err" }, "offset must be a whole number of seconds"));

  // choice 3 — anchor real-UTC (datetime picker), only with an anchor frame. Editable only when active.
  if (camMs != null) {
    const editU = active === "utc";
    pickI = el("input", { type: "datetime-local", step: "1", class: "spin-num utc-pick", readonly: editU ? null : "",
      title: "the anchor frame's true UTC; offset = this − the frame's camera clock" });
    pickI.value = eff == null ? "" : msToDtLocal(camMs + cur * 1000);
    if (editU) pickI.addEventListener("change", () => { const m = dtLocalToMs(pickI.value); setManual(pickI.value && m != null ? Math.round((m - camMs) / 1000) : "", "utc"); });
    wrap.append(opt(editU, el("label", { class: "ctl-field off-field" }, el("span", {}, "anchor real-UTC"), pickI),
      editU ? undefined : () => choose("utc")));
    if (p.proposed_real_utc) wrap.append(el("div", { class: "hint" }, `GPX estimate: ${p.proposed_real_utc}`));
  }

  // choice 4 — the true time of one photo, for a cell with no anchor frame: its representative, the earliest photo
  // (photos-21 `representative`). Typed in the destination's zone (UTC with none), it gives the offset — stored as
  // manual_offset_seconds, like any offset of the user's own: an editor affordance, no decision field of its own.
  const rp = c.representative;
  if (camMs == null && rp && camNaiveMs(rp.camera_source_naive_time) != null) {
    const editT = active === "true", zone = previewTz(ref.dest)?.tz || "";
    const bad = mine ? mine.bad : undefined;          // a time typed that names no one instant, kept to show
    trueI = el("input", { type: "datetime-local", step: "1", class: "spin-num utc-pick", readonly: editT ? null : "",
      title: `the true time of ${leaf(rp.source_file)}, in ${zone || "UTC"}; offset = that − its camera time` });
    trueI.value = typeof bad === "string" ? bad : (eff == null ? "" : trueTimeOf(rp.camera_source_naive_time, cur, zone) || "");
    if (editT) trueI.addEventListener("change", () => {
      const o = offsetFromTrueTime(rp.camera_source_naive_time, trueI.value, zone);
      if (o == null) { state.offsetEdit = { key: selKey, view: "true", open: true, bad: trueI.value || "" }; render(); return; }
      setManual(o, "true");
    });
    wrap.append(opt(editT, el("label", { class: "ctl-field off-field" }, el("span", {}, "true time of a photo"), trueI),
      editT ? undefined : () => choose("true")));
    const thumb = state.base.demo ? null : el("img", { class: "decision-thumb", alt: rp.source_file, title: leaf(rp.source_file),
      src: "/api/photo?path=" + encodeURIComponent(rp.source_file) });
    if (thumb) thumb.addEventListener("error", () => thumb.remove());
    wrap.append(el("div", { class: "hint" }, thumb, `${leaf(rp.source_file)} — its camera says ${rp.camera_source_naive_time}; ` +
      `type when it was really taken${zone ? `, ${zone} time` : ", in UTC (set the destination's timezone to type local time)"}.`));
    if (editT && typeof bad === "string")
      wrap.append(el("div", { class: "err" }, bad ? `${bad.replace("T", " ")} names no one instant in ${zone || "UTC"} — ` +
        "its clocks skipped it or showed it twice at a daylight-saving change; give another photo's time or the offset" : "type a time"));
  }

  // common Impact line — what the effective offset does to the anchor photo (or the offset + formula)
  const tz = previewTz(ref.dest)?.tz;
  if (eff == null) wrap.append(el("div", { class: "off-impact hint" }, "no offset set — a GPX self-anchor auto-resolves on re-run; otherwise this day needs input"));
  else if (repCamMs != null) {
    wrap.append(el("div", { class: "off-impact" }, offsetImpact(repCamMs, cur, tz)));
    if (!tz) wrap.append(el("div", { class: "hint" }, "set this destination's timezone to see the corrected local time"));
  } else {
    wrap.append(el("div", { class: "off-impact" }, `offset ${fmtOffset(cur)} — a photo's camera time + this = UTC${tz ? `, shown in ${tz}` : ""}`));
  }
  // no proposal at all → tell the user how to get one: a resolved timezone yields a timezone-derived offset —
  // except at a daylight-saving change of that zone, where no run ever derives one (ambiguousTimeNote)
  const amb = ambiguousTimeNote(p.timezone_ambiguous);
  if (!hasProp) wrap.append(amb ? el("div", { class: "hint warn" }, amb) : el("div", { class: "hint" }, tz
    ? "no offset proposal yet — re-run `photos-cartographer geotag plan` to derive one from the resolved timezone"
    : "no offset proposal — set this destination's timezone (Time view), then re-run `photos-cartographer geotag plan`, to derive one from the local time"));

  if (u.accept_proposal || manualSet || u.keep_as_recorded) wrap.append(el("button", { class: "mini",
    onclick: () => { state.offsetEdit = null; editMany(ref, { ...acceptFields(p, false), manual_offset_seconds: "", ...unkept(c) }); } },
    "clear (let geotag auto-resolve / re-derive)"));

  // restore focus to the view just activated (click-to-activate), so it's ready to edit
  if (state._focusOffset) {
    const tgt = state._focusOffset === "utc" ? pickI : state._focusOffset === "true" ? trueI : numI; state._focusOffset = null;
    if (tgt) queueMicrotask(() => tgt.focus());
  }
  return wrap;
}

function controls(ref) {
  const c = workCell(ref), u = c.user_decision, p = c.proposal || {}, wrap = el("div", { class: "ctl-block" });
  if (ref.kind === "timezone") {
    // An inherited zone applies itself; the configured default is only proposed (RUL-default_zone_proposed_only) —
    // one click takes it as the user's own. The one decision here is a zone written by hand, which overrides either.
    if (zoneContradiction(c)) {
      wrap.append(el("div", { class: "hint warn" }, zoneContradiction(c)));
      const said = (u.confirmed_despite_recorded_offsets || []).length > 0 && zoneSpokenFor({ ...c, user_decision: { ...u, manual_iana_timezone: "" } });
      wrap.append(checkbox(`keep ${c.contradicted_by.timezone} for these photos — their device was set to another zone`, said,
        (v) => edit(ref, "confirmed_despite_recorded_offsets", zoneDespiteFields(c, v).confirmed_despite_recorded_offsets)));
    }
    const offer = zoneOffer(c);
    if (offer) wrap.append(el("button", { class: "mini", onclick: () => edit(ref, "manual_iana_timezone", offer) }, `use ${offer}`));
    // The country this folder is in — whatever it is called. Said once, at the top of its tree: inside a country
    // none is chosen, and choosing one here takes out any chosen inside.
    const k = effectiveCountry(ref.dest), above = k && k.from !== ref.dest, table = state.work.time?.countries || {};
    if (Object.keys(table).length) {
      const csel = el("select", { disabled: above ? "" : null },
        el("option", { value: "" }, "— none —"),
        ...Object.entries(table).sort((a, b) => a[1].name.localeCompare(b[1].name)).map(([code, v]) =>
          el("option", { value: code }, `${v.name} (${code}) — ${v.zones.length === 1 ? v.zones[0] : v.zones.length + " timezones"}`)));
      csel.value = above ? k.code : (u.country || "");
      csel.addEventListener("change", () => {
        const removed = csel.value ? clearCountriesInside(ref.dest) : [];
        if (removed.length) state.message = `Country removed from ${removed.length} folder${removed.length === 1 ? "" : "s"} inside ` +
          `(${removed.map(leaf).join(", ")}): what lies inside a folder is in that folder's country, said once at the top — that is how photos by destination must be laid out.`;
        edit(ref, "country", csel.value);
      });
      wrap.append(el("label", { class: "ctl-field" }, el("span", {}, "In country"), csel));
      if (above) wrap.append(el("div", { class: "hint" }, `In ${countryInfo(k.code)?.name || k.code}, as said at ${leaf(k.from)}: a country is said once, at the top of its tree.`));
      else if (k && k.zones.length > 1) wrap.append(el("div", { class: "hint" }, `${k.zones.length} timezones: each folder inside answers for itself; none is passed down from here.`));
      if (c.country_removed) wrap.append(el("div", { class: "hint warn" },
        `The country said here (${c.country_removed.country}) was removed by the last run: ${leaf(c.country_removed.because)} above is in ${c.country_removed.country_there}, and so is everything inside it.`));
    }
    const sel = tzSelect(u.manual_iana_timezone, (v) => edit(ref, "manual_iana_timezone", v), false, k ? k.zones : null);
    wrap.append(el("label", { class: "ctl-field" }, el("span", {}, "Manual timezone"), sel));
    if (!validTz(u.manual_iana_timezone)) wrap.append(el("div", { class: "err" }, "not a valid IANA timezone"));
    else if (refInvalid(ref)) wrap.append(el("div", { class: "err" }, `not a timezone of ${countryInfo(k.code)?.name || k.code}`));
  } else if (ref.kind === "offset") {
    for (const note of offsetCellNotes(c)) wrap.append(el("div", { class: "hint warn" }, note));
    if (c.clock_change) wrap.append(clockChangeControls(ref));
    if (c.phone && keepOffered(c)) {
      // a phone's own reading kept, its GPS's finding set aside: the track was someone else's (BLD-phone_offset_cell)
      wrap.append(checkbox("keep this phone as its photos record themselves — its GPS here is wrong", !!u.keep_as_recorded,
        (v) => { state.offsetEdit = null; editMany(ref, keepFields(c, v)); }));
    }
    wrap.append(offsetEditor(ref));
  } else if (ref.kind === "date") {
    wrap.append(dateControls(ref));
  } else if (ref.kind === "reading") {
    wrap.append(readingControls(ref));
  } else if (ref.kind === "unidentified") {
    wrap.append(unidentifiedControls(ref));
  } else if (ref.kind === "drift") {
    wrap.append(driftControls(ref));
  } else if (ref.kind === "fingerprint") {
    wrap.append(mismatchControls(ref));
  } else if (ref.kind === "camera") {
    wrap.append(cameraControls(ref));
  } else if (ref.kind === "bodies") {
    wrap.append(bodiesControls(ref));
  } else if (ref.kind === "changed") {
    wrap.append(changedControls(ref));
  } else if (ref.kind === "fallback") {
    const hasProp = p.proposal_source === "inherited";
    const cb = checkbox(hasProp ? `accept inherited (${p.proposed_fallback.lat}, ${p.proposed_fallback.lon})` : "accept inherited — none",
      u.accept_proposal, (v) => edit(ref, "accept_proposal", v), !hasProp);
    // The folder fallback is optional. Once authored (a manual coord OR an accepted inherited value)
    // there was no way to take it back; offer an explicit reset to NONE right beside the checkbox —
    // clears the coordinate AND the accept flag in one action, so effective_fallback becomes null and
    // descendants re-inherit from above. (To inherit instead of none, re-tick "accept inherited".)
    const authored = !!u.accept_proposal
      || (u.fallback_lat !== "" && u.fallback_lat != null) || (u.fallback_lon !== "" && u.fallback_lon != null);
    const row = el("div", { class: "ctl-row" }, cb);
    if (authored) row.append(el("button", { class: "mini", title: "remove this folder fallback (back to none)",
      onclick: () => editMany(ref, { fallback_lat: "", fallback_lon: "", accept_proposal: false }) }, "clear"));
    wrap.append(row, coordField(ref));
  } else if (c.reason === "own_position_contradicted") {
    // a photo's own position its camera's agreed clock offset contradicts (BLD-contradicted_position): its own is
    // kept unless the user takes the track's — or sets another — as manual_lat/lon (RUL-own_position_replaced_on_answer)
    wrap.append(el("div", { class: "hint warn" }, contradictedNote(c)));
    const pp = c.proposed_position;
    if (pp) wrap.append(el("button", { class: "mini", onclick: () => editMany(ref, takeTrackPosition(c)) }, "take the track's position"));
    wrap.append(coordField(ref));
    if (u.manual_lat !== "" && u.manual_lat != null)
      wrap.append(el("button", { class: "mini", onclick: () => editMany(ref, { manual_lat: "", manual_lon: "" }) }, "keep its own position"));
  } else if (ref.kind === "chosen") {
    // a photo the tracks or the fallback place, given a position of its own: written as a `chosen_by_user` review
    // item, which outranks both and is kept while it holds a position (BLD-chosen_position)
    wrap.append(el("div", { class: "hint" }, `${c.placed_by === "folder_fallback" ? "Its folder's fallback" : "The tracks"} ` +
      "place this photo. A position set here is this photo's alone, and stays while it is set."));
    wrap.append(coordField(ref));
    if (u.manual_lat !== "" && u.manual_lat != null)
      wrap.append(el("button", { class: "mini", onclick: () => editMany(ref, { manual_lat: "", manual_lon: "" }) },
        c.placed_by === "folder_fallback" ? "back to the fallback" : "back to the tracks"));
  } else {
    const note = tracksNote(c.tracks);
    if (note) wrap.append(el("div", { class: "hint" }, note));
    for (const offer of reviewOffers(c)) {
      if (offer === "folder_fallback") {
        // the folder's fallback first: one answer places every photo of the folder nothing else places
        // (docs/design/decisions.md)
        const fbRef = { file: "gps", dest: ref.dest, kind: "fallback" }, fb = fbOwnDecision(ref.dest);
        wrap.append(el("div", { class: "ctl-row" },
          el("button", { class: "btn", onclick: () => { state.selected = fbRef; render(); } }, "set the folder's fallback"),
          el("span", { class: "hint" }, fb ? `set: ${fb.lat}, ${fb.lon} — it places this photo`
            : "places every photo of this folder the tracks do not")));
        wrap.append(el("div", { class: "hint" }, "or a position for this photo alone:"));
      } else wrap.append(coordField(ref));
    }
  }
  return wrap;
}
// What a review item of an own position its camera's agreed offset contradicts says (photos-23 own_position_contradicted):
// the photo's own position, where the track puts it at its corrected time, and how far apart. Pure — unit-tested.
function contradictedNote(c) {
  const own = (c && c.own_position) || {}, pp = c && c.proposed_position;
  const head = `This photo's own position (${own.lat}, ${own.lon}) agrees with none of its camera's other photos: the ` +
    "offset they agree on puts it ";
  if (!pp) return head + "where no track is now — its own position is kept, unless you set another.";
  return head + `${c.apart_meters} m from where the track was then (${pp.lat}, ${pp.lon}, ${pp.method}, ${pp.gpx_file}). ` +
    "Most likely its GPS was wrong — a stale fix, jitter — take the track's position; or keep its own.";
}
const takeTrackPosition = (c) => ({ manual_lat: c.proposed_position.lat, manual_lon: c.proposed_position.lon });
// Why the tracks placed nothing for a photo (photos-23 review item `tracks`), in one line: the user's lead to
// the cure — a track to add, a threshold, a track that is not theirs — before they reach for the map.
function tracksNote(t) {
  if (!t || !t.reason) return "";
  const span = (s) => s >= 3600 ? `${Math.round(s / 360) / 10} h` : s >= 60 ? `${Math.round(s / 60)} min` : `${s} s`;
  if (t.reason === "no_tracks") return "No tracks to place it by.";
  if (t.reason === "time_from_date_fallback") return "Its time is its folder's date fallback, not when it was taken: the tracks do not place it.";
  if (t.reason === "outside_track") return `The nearest track point is ${span(t.seconds_from_track)} from this photo's time.`;
  if (t.reason === "track_gap") return `The track has a ${span(t.gap_seconds)} gap here; its nearest point is ${span(t.seconds_from_track)} away.`;
  if (t.reason === "track_jump") return `The track jumps ${t.jump_meters} m between the two points around this photo — too far or too fast to place it between them.`;
  if (t.reason === "tracks_disagree") return `Tracks ${(t.gpx_files || []).join(" and ")} cover this time ${t.apart_meters} m apart — take the one that is not this trip's out of the tracks folder.`;
  return "";
}
// GPS-drift bucket: confirm the current offset as-is (zero scrub — must be explicit) or show the
// scrubbed correction. The scrub itself happens on the track map below (it sets `confirmed` +
// `corrected_offset_seconds`); this pinned control is the affirmation + readout + a clear-back.
// A drift confirmation names the offset it was made against and holds only while that is the bucket's
// offset (RUL-confirmation_holds_for_its_offset): confirming writes the offset shown; one made against another
// offset is stale. It names the tracks shown as well, each with its SHA-256 (BLD-drift_confirmation_tracks), and
// holds only while each is there unchanged (RUL-confirmation_rests_on_its_tracks) — one made with no track shown,
// only while none is (RUL-trackless_confirmation_holds_while_none).
function driftConfirmHolds(c) {
  const u = c.user_decision || {}, p = c.proposal || {};
  return !!u.confirmed && u.confirmed_offset_seconds !== "" && u.confirmed_offset_seconds != null
    && Number(u.confirmed_offset_seconds) === p.current_offset_seconds && driftTracksHold(c);
}
// Whether the tracks a confirmation names still stand. A track shown now is checked against its SHA-256 here; one
// named but no longer shown, by what geotag found under gpx_root (`confirmed_tracks_changed`) — the editor writes
// only tracks it shows, so any other came from the record geotag judged.
function driftTracksHold(c) {
  const named = (c.user_decision || {}).confirmed_against_tracks;
  const shown = new Map(((c.proposal || {}).tracks || []).map((t) => [t.gpx_file, t.sha256]));
  if (!Array.isArray(named)) return false;
  if (named.length === 0) return shown.size === 0;
  const changed = new Set(c.confirmed_tracks_changed || []);
  return named.every((t) => !!t && typeof t.gpx_file === "string" && typeof t.sha256 === "string"
    && (shown.has(t.gpx_file) ? shown.get(t.gpx_file) === t.sha256 : !changed.has(t.gpx_file)));
}
function driftConfirmFields(c, on) {
  const p = c.proposal || {};
  return on ? { confirmed: true, confirmed_offset_seconds: p.current_offset_seconds,
    confirmed_against_tracks: (p.tracks || []).map((t) => ({ gpx_file: t.gpx_file, sha256: t.sha256 })) }
    : { confirmed: false, confirmed_offset_seconds: "", confirmed_against_tracks: [] };
}
// Why a confirmation no longer holds, for the readout and its warning: "offset", "tracks", or null while it holds.
function driftStaleReason(c) {
  const u = c.user_decision || {}, p = c.proposal || {};
  if (!u.confirmed || driftConfirmHolds(c)) return null;
  return Number(u.confirmed_offset_seconds) !== p.current_offset_seconds ? "offset" : "tracks";
}
function driftControls(ref) {
  const c = workCell(ref), u = c.user_decision || {}, p = c.proposal || {}, wrap = el("div", { class: "ctl-block" });
  wrap.append(el("div", { class: "hint" },
    `Current offset ${fmtOffset(p.current_offset_seconds)} (${p.proposal_source || "?"}). Scroll the photo along the track below to correct it, type the correction, or confirm it as-is.`));
  const holds = driftConfirmHolds(c);
  if (u.confirmed && !holds) wrap.append(el("div", { class: "hint warn" }, driftStaleReason(c) === "tracks"
    ? "Confirmed against tracks since removed or changed — check it on the track as it is now and confirm again."
    : `Confirmed for ${fmtOffset(u.confirmed_offset_seconds)}; the offset is now ${fmtOffset(p.current_offset_seconds)} — check it on the track and confirm again.`));
  wrap.append(checkbox("confirm this bucket (offset is right as shown)", holds, (v) => editMany(ref, driftConfirmFields(c, v))));
  const corr = u.corrected_offset_seconds;
  if (corr !== "" && corr != null) {
    const delta = isNum(corr) ? corr - (p.current_offset_seconds || 0) : null;
    wrap.append(el("div", { class: "ctl-field" },
      el("span", {}, `scrubbed correction: ${fmtOffset(corr)}${delta != null ? ` (Δ ${fmtOffset(delta)})` : ""}`),
      el("button", { class: "mini", onclick: () => editMany(ref, { corrected_offset_seconds: "" }) }, "clear — offset was right")));
  }
  if (!validOffset(corr)) wrap.append(el("div", { class: "err" }, "the correction must be a whole number of seconds"));
  wrap.append(driftTyped(ref));
  return wrap;
}
// What a correction writes, scrubbed or typed: the bucket confirmed against the offset and tracks shown, and corrected.
const driftCorrectionFields = (c, v) => ({ ...driftConfirmFields(c, true), corrected_offset_seconds: v });
// A drift correction typed rather than scrubbed: the offset known, or the true time of one of the bucket's photos — the
// only way to give one where no track lies by the photos. Written as a scrub is: confirmed, with the offset and tracks
// shown, and the corrected offset (photos-22 corrected_offset_seconds).
function driftTyped(ref) {
  const c = workCell(ref), u = c.user_decision || {}, p = c.proposal || {}, frames = p.frames || [];
  const box = el("div", { class: "ctl-block" });
  const set = (v) => editMany(ref, driftCorrectionFields(c, v));
  const corr = u.corrected_offset_seconds, typed = corr !== "" && corr != null;
  const offI = el("input", { type: "number", step: "1", class: "spin-num", placeholder: String(p.current_offset_seconds ?? ""),
    value: typed ? corr : "", title: "the corrected clock offset in seconds: camera time + this = UTC" });
  offI.addEventListener("change", () => set(offI.value === "" ? "" : Number(offI.value)));
  box.append(el("label", { class: "ctl-field" }, el("span", {}, "corrected offset (seconds)"), offI));
  const frame = frames[Math.min(_driftFrame, Math.max(0, frames.length - 1))];
  if (frame && camNaiveMs(frame.camera_naive) != null) {
    const zone = previewTz(ref.dest)?.tz || "";
    const shown = typed && validOffset(corr) ? corr : p.current_offset_seconds;
    const tI = el("input", { type: "datetime-local", step: "1", class: "spin-num utc-pick",
      value: trueTimeOf(frame.camera_naive, shown, zone) || "",
      title: `the true time of ${leaf(frame.source_file)}, in ${zone || "UTC"}; offset = that − its camera time` });
    tI.addEventListener("change", () => {
      const o = offsetFromTrueTime(frame.camera_naive, tI.value, zone);
      if (o == null) { state.message = `${(tI.value || "").replace("T", " ")} names no one instant in ${zone || "UTC"} — type another time, or the offset`; render(); return; }
      set(o);
    });
    box.append(el("label", { class: "ctl-field" }, el("span", {}, `true time of ${leaf(frame.source_file)}`), tI));
    box.append(el("div", { class: "hint" }, `its camera says ${frame.camera_naive}; type when it was really taken` +
      (zone ? `, ${zone} time` : ", in UTC") + " — or the offset above. Either confirms the bucket with that correction."));
  }
  return box;
}

// The "lat, lon" input lives in the pinned top box; as the map pans below, the live map center is
// mirrored into it (display only — committing stays on Enter/blur or "use map center"). Tracked here so
// the map's onMove can reach the current input across re-renders.
let _coordInp = null;
// A single "lat, lon" text field for a coordinate cell (review or fallback) — accepts a value pasted
// straight from Google Maps. A valid entry (committed on paste, or on Enter / blur) writes both stored
// fields, refreshes the in-editor clipboard, and jumps the map to that exact coordinate at full zoom; a
// non-empty unparseable entry is kept verbatim and flagged invalid; empty clears the cell.
function coordField(ref) {
  const [la, lo] = coordFields(ref), u = workCell(ref).user_decision || {};
  const inp = el("input", { type: "text", class: refInvalid(ref) ? "bad" : null,
    placeholder: "lat, lon  —  e.g. 50.525434, 4.269781", value: coordText(u, la, lo) });
  _coordInp = inp;
  const commit = () => {
    const t = inp.value.trim();
    if (t === "") return editMany(ref, { [la]: "", [lo]: "" });
    const c = parseLatLon(t);
    if (c) { state.coordClipboard = { lat: c.lat, lon: c.lon }; editMany(ref, { [la]: c.lat, [lo]: c.lon }); if (_map) _map.jumpMax(c); }
    else editMany(ref, { [la]: t, [lo]: "" });        // keep the bad text visible and let validation flag it
  };
  inp.addEventListener("change", commit);             // Enter / blur
  // Paste should act immediately, not wait for Enter/blur. The value isn't updated yet on the paste
  // event, so commit on the next tick (a re-render rebuilds the field, so read inp.value before then).
  inp.addEventListener("paste", () => setTimeout(commit, 0));
  const lbl = el("label", { class: "ctl-field" }, el("span", {}, "Coordinate (lat, lon)"), inp);
  const wrap = el("div", {}, lbl, el("div", { class: "hint" }, "paste “lat, lon” (e.g. from Google Maps), pan the map under the crosshair and “use map center”, or paste a copied location"));
  if (refInvalid(ref)) wrap.append(el("div", { class: "err" }, "enter coordinates as “lat, lon” (lat ±90, lon ±180)"));
  return wrap;
}

// --- GPS map + photo (side panel) --------------------------------------------
const coordFields = (ref) => ref.kind === "fallback" ? ["fallback_lat", "fallback_lon"] : ["manual_lat", "manual_lon"];
function currentCoord(ref) {
  const u = workCell(ref).user_decision || {}, [la, lo] = coordFields(ref);
  return isNum(u[la]) && isNum(u[lo]) ? { lat: u[la], lon: u[lo] } : null;
}
function destFallbackCoord(dest) {
  const fb = state.work.gps?.destinations?.[dest]?.folder_fallback;
  const e = fb?.effective_fallback || fb?.proposal?.proposed_fallback;
  return e && isNum(e.lat) && isNum(e.lon) ? { lat: e.lat, lon: e.lon } : null;
}
function gpsRefMarkers(ref) {
  const c = workCell(ref), p = c.proposal || {}, out = [];
  if (ref.kind === "fallback") {
    if (c.effective_fallback) out.push({ ...c.effective_fallback, label: "effective fallback", color: "#4f9cf9" });
    if (p.proposed_fallback) out.push({ ...p.proposed_fallback, label: `inherited (${p.inherited_from || "ancestor"})`, color: "#e0a85e" });
  } else {
    const fb = destFallbackCoord(ref.dest);
    if (fb) out.push({ ...fb, label: "folder fallback", color: "#e0a85e" });
  }
  return out;
}
// Seed the map view for a freshly-selected GPS cell: its own decision first, else the LAST coordinate
// the operator placed (so the next un-located photo opens centred where the previous one was set — they
// are usually near each other), else a reference pin. The clipboard is set on every pick/paste below.
const seedCenter = (ref) => currentCoord(ref) || state.coordClipboard || gpsRefMarkers(ref)[0] || null;
// Copy/paste a coordinate between cells so the operator need not re-navigate to a place already found.
// "copy" stashes this cell's decision (or its best reference) on the clipboard; "paste" applies it here.
function copyPasteBar(ref) {
  const [la, lo] = coordFields(ref), have = currentCoord(ref) || gpsRefMarkers(ref)[0] || null, clip = state.coordClipboard;
  const fmtC = (c) => `${c.lat.toFixed(6)}, ${c.lon.toFixed(6)}`;
  const copy = el("button", { class: "btn", disabled: have ? null : "", title: have ? "remember this location for other photos" : "no location here to copy",
    onclick: () => { state.coordClipboard = { lat: have.lat, lon: have.lon }; try { navigator.clipboard?.writeText(fmtC(have)); } catch { /* best effort */ } state.message = `copied ${fmtC(have)}`; render(); } }, "copy location");
  const paste = el("button", { class: "btn", disabled: clip ? null : "", title: clip ? `paste ${fmtC(clip)}` : "copy a location first",
    onclick: () => { editMany(ref, { [la]: clip.lat, [lo]: clip.lon }); if (_map) _map.recenter(clip); } },
    clip ? `paste ${fmtC(clip)}` : "paste");
  return el("div", { class: "map-cp" }, copy, paste);
}

// One Leaflet instance, kept across re-renders of the same selection (rebuilding it on each keystroke
// would reset pan/zoom). Rebuilt when the selected cell changes; torn down for non-GPS cells.
let _map = null, _mapKey = null;
// A GPS-review cell's reference pins and seed centre are DEST-scoped (gpsRefMarkers ignores path/peers),
// so extending a multi-photo selection — shift-click — never changes the map. Give review cells a key
// that's stable across path/peers within a dest, so the SAME Leaflet instance survives the re-render
// instead of being torn down and rebuilt (a rebuild blanks the whole panel = the visible flash). Other
// kinds keep their per-cell key so switching cell still rebuilds the map.
const mapKeyFor = (ref) => !ref ? null
  : ref.kind === "review" ? `${ref.file}|${ref.dest}|review`
    : `${ref.file}|${ref.dest}|${ref.kind}|${ref.key || ""}|${ref.path || ""}|${(ref.peers || []).join(",")}`;
function teardownMap() { if (_map) { _map.destroy(); _map = null; _mapKey = null; } }
function mapBlock(ref) {
  const key = mapKeyFor(ref);
  if (_mapKey !== key) {
    teardownMap();
    const [la, lo] = coordFields(ref);
    _map = mapPicker({ center: seedCenter(ref), markers: gpsRefMarkers(ref),
      onPick: (lat, lon) => { state.coordClipboard = { lat, lon }; editMany(ref, { [la]: lat, [lo]: lon }); },
      // Pan mirrors the crosshair into the pinned coord field (skipped while it's being typed in).
      onMove: (lat, lon) => { if (_coordInp && document.activeElement !== _coordInp) _coordInp.value = `${lat}, ${lon}`; } });
    _mapKey = key;
  }
  _map.setCurrent(currentCoord(ref));
  setTimeout(() => _map && _map.refresh(), 0);     // recompute size after (re)attach to the DOM
  // Controls (place search, readout + "use map center", copy/paste) ABOVE the map; the big map fills
  // the rest of the panel below them.
  return el("div", { class: "pblock" }, el("h3", {}, "Place on map"),
    _map.search, _map.bar, copyPasteBar(ref), _map.el);
}
// Scrub-on-track block for a drift bucket: a representative photo above a max-zoomed track map; the
// scroll wheel slides the photo along the GPX segment (map.js), and each step computes the bucket's
// corrected offset from THAT photo's camera-naive time. A frame picker lets the operator cross-check
// other photos in the bucket (each must yield the same offset); the last scrub wins.
// Two sub-tabs under the pinned decision (like the Time/Drift/GPS views): "Photo" (active on load) to
// pick which frame represents the bucket, and "Track" to scrub that photo along the GPX segment. The
// scrub map is mounted only on the Track tab (so its wheel/key handlers exist only there).
function scrubBlock(ref) {
  const c = workCell(ref), p = c.proposal || {}, frames = p.frames || [], track = p.track_segment || [];
  const wrap = el("div", { class: "pblock" });
  if (!frames.length || !track.length) { teardownMap(); wrap.append(el("div", { class: "placeholder" }, "no track to scrub along — type the correction above, or confirm the offset as it is")); return wrap; }
  const fi = Math.min(_driftFrame, frames.length - 1), frame = frames[fi];
  const tabBtn = (id, label) => el("button", { class: _driftTab === id ? "on" : null, onclick: () => { _driftTab = id; render(); } }, label);
  wrap.append(el("div", { class: "seg subtab" }, tabBtn("photo", "Photo"), tabBtn("map", "Track")));

  if (_driftTab === "map") {                      // Track tab — scrub the chosen photo along the GPX segment
    wrap.append(driftMap(ref, frame, fi));
    wrap.append(el("div", { class: "hint" }, `Placing ${frame.source_file.split("/").pop()} (photo ${fi + 1}/${frames.length}). `
      + "Scroll over the map, or press [ / ] (Shift for ×10), to slide it along the track; the chosen point sets this bucket's corrected offset for every photo in it."));
    return wrap;
  }

  // Photo tab — choose the representative frame (the map is not mounted here).
  teardownMap();
  const setFrame = (i) => { _driftFrame = Math.max(0, Math.min(frames.length - 1, i)); render(); };
  wrap.append(el("div", { class: "frame-nav" },
    el("button", { class: "btn", disabled: fi === 0 ? "" : null, onclick: () => setFrame(fi - 1) }, "‹ prev"),
    el("span", { class: "frame-count" }, `Photo ${fi + 1} / ${frames.length}`),
    el("button", { class: "btn", disabled: fi === frames.length - 1 ? "" : null, onclick: () => setFrame(fi + 1) }, "next ›")));
  wrap.append(el("div", { class: "hint" }, frame.source_file.split("/").pop()));
  if (state.base.demo) wrap.append(el("div", { class: "placeholder" }, "no preview in demo mode (no workspace files)"));
  else {
    const img = el("img", { class: "photo-img", alt: frame.source_file, src: "/api/photo?path=" + encodeURIComponent(frame.source_file) });
    img.addEventListener("error", () => { img.remove(); wrap.append(el("div", { class: "placeholder" }, "no embedded preview available")); });
    wrap.append(img);
  }
  wrap.append(el("div", { class: "hint" }, "‹ prev / next › picks the photo that represents this group; switch to Track to place it on the GPX track."));
  return wrap;
}
function driftMap(ref, frame, fi) {
  const key = mapKeyFor(ref) + "|f" + fi;
  if (_mapKey !== key) {
    teardownMap();
    const p = workCell(ref).proposal || {}, track = p.track_segment || [];
    _map = mapPicker({ track, scrubIndex: scrubSeedIndex(track, frame, p.current_offset_seconds),
      onScrub: (i, pt) => { const off = scrubOffset(pt, frame);
        if (off != null) editMany(ref, driftCorrectionFields(workCell(ref), off)); } });
    _mapKey = key;
  }
  setTimeout(() => _map && _map.refresh(), 0);
  return _map.el;
}
// A small right-aligned preview of the first/only selected photo, shown inside the pinned "Your
// decision" box for a GPS review item (the big map gets the rest of the panel). Null in demo mode or
// for non-photo cells; for a multi-photo run, `ref.path` is the first photo.
function decisionThumb(ref) {
  const photo = ref.kind === "reading" || ref.kind === "changed" ? ref.key : ["camera", "bodies"].includes(ref.kind) ? (workCell(ref)?.examples || [])[0] : ref.path;
  if (state.base.demo || !["review", "chosen", "reading", "fingerprint", "camera", "bodies", "changed"].includes(ref.kind) || !photo) return null;
  const img = el("img", { class: "decision-thumb", alt: photo, title: photo.split("/").pop(),
    src: "/api/photo?path=" + encodeURIComponent(photo) });
  img.addEventListener("error", () => img.remove());
  return img;
}

// Floating full-size preview shown while hovering a photo name in the worklist — lets you eyeball each
// photo (and build a shift-click run) without opening it. Follows the cursor like a tooltip. One reused
// element; never in demo mode.
let _hoverImg = null, _hoverPath = null;
function _placeHover(x, y) {                      // near the cursor, flipped/clamped to stay on-screen
  if (!_hoverImg) return;
  const W = 340, H = 340, off = 16;
  let left = x + off, top = y + off;
  if (left + W > window.innerWidth) left = x - W - off;
  if (top + H > window.innerHeight) top = y - H - off;
  _hoverImg.style.left = Math.max(8, left) + "px";
  _hoverImg.style.top = Math.max(8, top) + "px";
}
function showHoverPreview(path, ev) {
  if (state.base.demo || !path) return;
  if (!_hoverImg) {
    _hoverImg = el("img", { class: "hover-preview" });
    _hoverImg.addEventListener("error", () => { _hoverImg.hidden = true; });
    document.body.append(_hoverImg);
  }
  if (path !== _hoverPath) { _hoverImg.src = "/api/photo?path=" + encodeURIComponent(path); _hoverPath = path; }
  _placeHover(ev.clientX, ev.clientY);
  _hoverImg.hidden = false;
}
function moveHoverPreview(ev) { if (_hoverImg && !_hoverImg.hidden) _placeHover(ev.clientX, ev.clientY); }
function hideHoverPreview() { if (_hoverImg) { _hoverImg.hidden = true; _hoverPath = null; } }

// --- side panel --------------------------------------------------------------
function jsonBlock(title, obj) { return obj === undefined ? null : el("div", { class: "pblock" }, el("h3", {}, title), el("pre", { class: "json" }, JSON.stringify(obj, null, 2))); }

// Picking a correction group of a GPX self-anchor proposal (BLD-anchor_matching): the recommended one is
// accepting the proposal; any other sets its offset — which geotag counts as anchored by the GPS
// (gpx_anchor_chosen), so no drift check follows. One click, for every day bundled with this proposal.
// In a same-day conflict (`conflict`) the recommended one is taken as the user's own offset too: an acceptance there is
// withheld again.
function groupChoice(p, g, conflict = false) {
  return g.offset_seconds === p.proposed_offset_seconds && !conflict
    ? { ...acceptFields(p, true), manual_offset_seconds: "" }
    : { ...acceptFields(p, false), manual_offset_seconds: g.offset_seconds };
}
// A cell geotag found in a same-day conflict (`conflicts_with`, BLD-offset_shared_within_day): one clock read two ways in
// two destinations. An acceptance there counts as what the camera's GPS gave by itself, and is withheld again; the user's
// own offset keeps its effect (RUL-chosen_offset_not_withheld). So the proposal is taken there as manual_offset_seconds.
const inConflict = (c) => ((c && c.conflicts_with) || []).length > 0;
// What taking a cell's proposal writes: an acceptance naming its offset, or — in a same-day conflict — the offset as the
// user's own (BLD-editor_answers_every_question).
function proposalTaken(c) {
  const p = (c && c.proposal) || {};
  return inConflict(c) ? { ...acceptFields(p, false), manual_offset_seconds: p.proposed_offset_seconds }
    : { ...acceptFields(p, true), manual_offset_seconds: "" };
}
// An acceptance names the offset it accepts (accepted_offset_seconds) and holds only while that is what is
// proposed — within the proposal's own agreement spread for one found from GPS. Mirrors BLD-offset_acceptance: a
// proposal that became another one was never accepted.
function acceptFields(p, on) {
  return on ? { accept_proposal: true, accepted_offset_seconds: p.proposed_offset_seconds }
    : { accept_proposal: false, accepted_offset_seconds: "" };
}
function acceptHolds(c) {
  const u = c.user_decision || {}, p = c.proposal || {};
  if (!u.accept_proposal || !("proposed_offset_seconds" in p)) return false;
  if (u.accepted_offset_seconds === "" || u.accepted_offset_seconds == null) return false;
  // an offset from the camera's own GPS — its positions on the tracks or its fixes' times — holds within the tolerance
  const slack = p.proposal_source === "gpx_self_anchor" || p.proposal_source === "gps_time" ? (p.acceptance_tolerance_seconds || 0) : 0;
  return Math.abs(Number(u.accepted_offset_seconds) - p.proposed_offset_seconds) <= slack;
}
// The working decision's offset, to mark the group it picks (null while nothing is chosen).
function chosenOffset(p, u) {
  if (u.manual_offset_seconds !== "" && u.manual_offset_seconds != null) return Number(u.manual_offset_seconds);
  return acceptHolds({ user_decision: u, proposal: p }) ? p.proposed_offset_seconds : null;
}
// What the user must settle, said in one line each: a tie between visits, and photos agreeing with no group.
// Does the zone stand against what the destination's own photos record? Yes where none speaks against it,
// where the user has spoken for every offset they record, or where the zone picked is no longer the one the
// last run checked (the next run checks the new one).
function zoneSpokenFor(c) {
  const k = c && c.contradicted_by; if (!k) return true;
  const u = c.user_decision || {};
  if (u.manual_iana_timezone && u.manual_iana_timezone !== k.timezone) return true;
  const said = new Set(u.confirmed_despite_recorded_offsets || []);
  return (k.recorded_offsets || []).every((o) => said.has(o));
}
// The decision fields that keep a zone against the photos' recorded offsets: the word names the offsets it is given for.
function zoneDespiteFields(c, on) {
  return { confirmed_despite_recorded_offsets: on ? [...((c.contradicted_by || {}).recorded_offsets || [])] : [] };
}
// The zone a timezone cell offers to take in one click ("use <zone>"), or "": the configured default (only proposed),
// or the proposal standing where the photos contradicted the zone written here. Never the zone the photos contradict:
// writing it resolves nothing — keeping it is the confirmation's to say, and another zone or country the other way.
function zoneOffer(c) {
  const u = (c && c.user_decision) || {}, k = c && c.contradicted_by;
  if (!c || !c.proposed_iana_timezone || u.manual_iana_timezone) return "";
  if (k && c.proposed_iana_timezone === k.timezone) return "";
  return c.proposal_source === "config_default" || k ? c.proposed_iana_timezone : "";
}
// Why a destination does not take its zone: its own photos record another offset.
function zoneContradiction(c) {
  const k = c && c.contradicted_by; if (!k) return "";
  const off = (s) => fmtOffset(s).replace(/ 00s$/, "");
  return `${k.photos} photo${k.photos === 1 ? "" : "s"} here record${k.photos === 1 ? "s" : ""} ${off(k.recorded_offset_seconds)} from UTC ` +
    `(${k.example}); ${k.timezone} was at ${off(k.timezone_offset_seconds)} then. A destination has one timezone: pick the one ` +
    `these photos were taken in, move those taken elsewhere to a folder of their own, or keep ${k.timezone} for them below.`;
}
// What an offset cell has to say beyond its proposal: where a shared offset came from, that a timezone's
// guess is checked on the tracks, that the camera's GPS gave another offset elsewhere that day, that its photos
// record different offsets.
function offsetCellNotes(c) {
  const out = [], p = (c && c.proposal) || {}, eff = (c && c.effective_time_anchor) || {};
  if (p.proposal_source === "same_day_elsewhere" && p.shared_from)
    out.push(`No photo here has its own position. The camera's GPS fixed its clock that day in ${p.shared_from.destination}: ` +
      `${fmtOffset(p.proposed_offset_seconds)}` + (p.confidence === "high" ? ", applied here too." : " — accept it here, or set another."));
  if (eff.source === "timezone_unconfirmed" || eff.source === "recorded_offset_unconfirmed")
    out.push("Tracks lie by these photos, so this is checked against them — confirm it in the Drift view; nothing to accept here.");
  const differ = (c && c.recorded_offsets_differ) || [];
  if (differ.length)
    out.push(`These photos record different offsets with their times — ${differ.map((d) => `${utcOff(d.recorded_offset_seconds)} ` +
      `(${d.photos} photo${d.photos === 1 ? "" : "s"}, e.g. ${leaf(d.example)})`).join(", ")} — so none is proposed from them. ` +
      "The camera's zone setting changed that day, or the tag is wrong: set the offset, or move the photos of each setting into a sub-folder and re-run.");
  if (c && c.phone) out.push(phoneNote(c));
  const aside = c && c.gps_time_set_aside;
  if (aside) out.push(gpsTimeAsideNote(aside));
  const far = p.far_from_evidence;
  if (far) out.push(`This offset puts these photos ${fmtSpan(far.nearest_other_photo_seconds)} from the nearest photo another ` +
    `device took here (${leaf(far.nearest_other_photo)})` +
    (far.nearest_track_seconds === "" || far.nearest_track_seconds == null ? "" : ` and ${fmtSpan(far.nearest_track_seconds)} from the nearest track point`) +
    ` — farther than a clock may be wrong (${fmtSpan(far.max_clock_error_seconds)}); the camera's clock was likely reset. ` +
    "Accepting it is not enough: give the true time of one of its photos, or set the offset.");
  // Who said what: the other side may be an offset the user chose, and this cell may be the user's choice itself.
  const mine = eff.source === "gpx_anchor_chosen";
  for (const k of (c && c.conflicts_with) || []) {
    if (k.chosen)
      out.push(`You chose ${fmtOffset(k.offset_seconds)} for this camera the same day in ${k.destination} — one clock, two readings. ` +
        "Set this cell's offset by hand, or change your choice there.");
    else if (mine)
      out.push(`The camera's GPS gives ${fmtOffset(k.offset_seconds)} by itself the same day in ${k.destination}, against the offset ` +
        "you chose here — one clock, two readings. Your choice stands; that cell waits for you: set its offset by hand, or change yours.");
    else
      out.push(`The camera's GPS gives ${fmtOffset(k.offset_seconds)} the same day in ${k.destination} — one clock, two readings. ` +
        "Set the right offset by hand in the one that is wrong — taking a proposal here takes it as your own offset.");
  }
  return out;
}
// A day with no anchor of its own offered the offset the camera's GPS gave the day before or after it here (photos-21
// proposal_source "neighbour_day", BLD-neighbour_day_proposal): asked once, as a timezone's guess is — with tracks by
// its photos it takes effect unconfirmed and is confirmed in the Drift view, nothing to accept here; else accepted
// here. Pure.
function neighbourDayNote(p, eff) {
  const n = (p && p.neighbour_day) || {};
  return `No photo of this day has its own position, but the camera's GPS fixed its clock on ${fmtDate(n.day)} here: ` +
    `${fmtOffset(p.proposed_offset_seconds)}. A camera's midnight in the middle of an outing splits it in two — ` +
    ((eff && eff.source) === "neighbour_day_unconfirmed"
      ? "tracks lie by these photos, so it is checked against them: confirm it in the Drift view if the clock was not " +
        "set in between; nothing to accept here."
      : "accept it if the clock was not set in between.");
}
// Why the times the photos' own GPS fixes recorded say nothing of the clock here (gps_time_set_aside,
// BLD-gps_time_proposal): a stale fix repeating its time, or readings that disagree.
function gpsTimeAsideNote(a) {
  const n = `${a.gps_time_count} photo${a.gps_time_count === 1 ? "" : "s"}`;
  if (a.reason === "repeated_gps_time")
    return `${n} here hold a GPS fix time, but two record the same one at different camera times (e.g. ${leaf(a.example)}) — ` +
      "a stale fix — so the fixes' times are not read as the clock.";
  const [lo, hi] = a.offsets_seconds || [];
  return `${n} here hold a GPS fix time, but they give offsets from ${fmtOffset(lo)} to ${fmtOffset(hi)} (e.g. ${leaf(a.example)}) — ` +
    "too far apart to be one clock — so the fixes' times are not read as the clock.";
}
// A camera's clock changed during the day (photos-21 clock_change, BLD-clock_change_split): its photos with their own
// position, in the order of the true times their GPS gives them, fall into two runs, each agreeing on its own offset.
// The answer, on the day's cell: accept the split, naming the two offsets accepted (accepted_change_offsets_seconds) —
// and, for each photo without GPS that either part could have taken, or neither (clock_change.unsettled), the part it
// belongs to (photo_parts, by its source file: 1 or 2). Pure — unit-tested.
function clockChangePartsGiven(c) {
  const ch = (c && c.clock_change) || {}, parts = ((c && c.user_decision) || {}).photo_parts || {};
  return (ch.unsettled || []).every((p) => parts[p.source_file] === 1 || parts[p.source_file] === 2);
}
function clockChangeHolds(c) {
  const ch = c && c.clock_change, u = (c && c.user_decision) || {};
  if (!ch || u.accept_clock_change !== true || (u.manual_offset_seconds !== "" && u.manual_offset_seconds != null)) return false;
  const offs = u.accepted_change_offsets_seconds, tol = ch.acceptance_tolerance_seconds || 0;
  return Array.isArray(offs) && offs.length === 2
    && offs.every((o, i) => isNum(o) && Math.abs(o - ch.runs[i].offset_seconds) <= tol) && clockChangePartsGiven(c);
}
// The decision fields of splitting the day (or not): accepting names the runs' offsets, keeping the parts given so
// far; the day's own offset answers are cleared, a split replacing them.
function clockChangeFields(c, on, parts = {}) {
  const runs = ((c && c.clock_change) || {}).runs || [];
  return on ? { accept_clock_change: true, accepted_change_offsets_seconds: runs.map((r) => r.offset_seconds),
    photo_parts: { ...parts }, accept_proposal: false, accepted_offset_seconds: "", manual_offset_seconds: "" }
    : { accept_clock_change: false, accepted_change_offsets_seconds: "", photo_parts: {} };
}
// One photo's part given (1 or 2), the others' kept: the cell's new photo_parts.
function clockChangePart(c, file, part) {
  return { ...(((c && c.user_decision) || {}).photo_parts || {}), [file]: part };
}
function clockChangeControls(ref) {
  const c = workCell(ref), u = c.user_decision || {}, ch = c.clock_change, wrap = el("div", { class: "pblock" });
  const [a, b] = ch.runs, by = ch.evidence === "gps_time" ? "the times their GPS fixes recorded" : "their positions on the tracks";
  wrap.append(el("h3", {}, "The camera's clock changed this day"));
  wrap.append(el("div", { class: "hint warn" }, `By ${by}, ${a.photos} photo${a.photos === 1 ? "" : "s"} up to ${leaf(a.last.source_file)} ` +
    `(camera ${a.last.camera_source_naive_time}, ${a.last.real_utc}) give ${fmtOffset(a.offset_seconds)}, and ${b.photos} from ` +
    `${leaf(b.first.source_file)} (camera ${b.first.camera_source_naive_time}, ${b.first.real_utc}) give ${fmtOffset(b.offset_seconds)}: ` +
    "the clock was set between them. Split the day there, each part corrected by its own photos — or, if the clock did not " +
    "change, answer the day's offset below."));
  const on = u.accept_clock_change === true;
  wrap.append(checkbox("split the day where the clock changed", on, (v) => { state.offsetEdit = null; editMany(ref, clockChangeFields(c, v, u.photo_parts || {})); }));
  const unsettled = ch.unsettled || [];
  if (on && unsettled.length) {
    // a clock set back shows an hour twice: no one camera time divides these photos, so each is given its part
    wrap.append(el("div", { class: "hint" }, `${unsettled.length} photo${unsettled.length === 1 ? "" : "s"} without GPS could ` +
      "belong to either part by their camera time (or fit neither): say for each whether it was taken before the change or after it."));
    const parts = u.photo_parts || {};
    for (const p of unsettled) {
      const row = el("div", { class: "off-opt" }, el("span", {}, `${leaf(p.source_file)} (camera ${p.camera_source_naive_time}): `));
      for (const [n, label] of [[1, `before (${fmtOffset(a.offset_seconds)})`], [2, `after (${fmtOffset(b.offset_seconds)})`]]) {
        const sel = parts[p.source_file] === n;
        row.append(el("span", { class: "off-opt" + (sel ? " on" : ""), onclick: () => edit(ref, "photo_parts", clockChangePart(c, p.source_file, n)) },
          el("span", { class: "off-dot" }, sel ? "●" : "○"), el("span", {}, ` ${label} `)));
      }
      wrap.append(row);
    }
  }
  if (on && !clockChangeHolds(c)) wrap.append(el("div", { class: "hint warn" }, !clockChangePartsGiven(c)
    ? "Say which part each photo above belongs to." : "Accepted for other offsets than the photos now give — accept again."));
  return wrap;
}
// A phone's day kept as its photos record themselves (photos-21 user_decision.keep_as_recorded, BLD-phone_offset_cell):
// offered, and holding, only where the cell's proposal is the phone's own GPS — its track anchor or its fixes' times.
const keepOffered = (c) => ["gpx_self_anchor", "gps_time"].includes((c && c.proposal || {}).proposal_source);
function keepHolds(c) {
  const u = (c && c.user_decision) || {};
  return !!(c && c.phone) && u.keep_as_recorded === true && keepOffered(c)
    && (u.manual_offset_seconds === "" || u.manual_offset_seconds == null);
}
// The decision fields of keeping (or not) a phone as recorded: one answer, the others cleared.
function keepFields(c, on) {
  return on ? { keep_as_recorded: true, accept_proposal: false, accepted_offset_seconds: "", manual_offset_seconds: "" }
    : { keep_as_recorded: false };
}
// What an answer other than keeping writes into a phone's cell: keep cleared (absent on a camera's cell).
const unkept = (c) => (c && c.phone ? { keep_as_recorded: false } : {});
// What a phone's cell has to say: its own GPS reads its clock otherwise than its photos are read.
function phoneNote(c) {
  const ph = c && c.phone; if (!ph) return "";
  const p = c.proposal || {}, read = (ph.read_by_offsets || []).map(fmtOffset).join(", ") || "nothing (no offset recorded, no zone)";
  const by = p.proposal_source === "gps_time" ? "the times its own GPS fixes recorded" : "its photos' own positions on the tracks";
  const n = `${ph.photos} photo${ph.photos === 1 ? "" : "s"}`;
  if (ph.applies_to === "untagged_photos") {
    if (keepOffered(c)) return `${n} of this phone here record${ph.photos === 1 ? "s" : ""} no offset with ${ph.photos === 1 ? "its" : "their"} time; ` +
      `${by} put its clock at ${fmtOffset(p.proposed_offset_seconds)} that day, which reads ${ph.photos === 1 ? "it" : "them"}.`;
    return `${n} of this phone here record${ph.photos === 1 ? "s" : ""} no offset with ${ph.photos === 1 ? "its" : "their"} time, and nothing ` +
      "of the phone's own says which: no tagged photo of the day at the zone's offset, no position on a track, no GPS fix time. " +
      "Accept the reading proposed (the Drift view checks it where tracks lie by), or set the offset.";
  }
  return `This phone's photos are read by ${read}, but ${by} put its clock at ${fmtOffset(p.proposed_offset_seconds)} — ` +
    `for all ${n} of its day here. Accept it, set the offset, or keep the phone as it records itself if the track is not yours.`;
}
// The instant a local camera time names under a UTC offset (seconds east of UTC), as "YYYY-MM-DD HH:MM:SS UTC".
function trueInstant(camTime, utcOffset) {
  const ms = camNaiveMs(camTime); if (ms == null || !isNum(utcOffset)) return "";
  return new Date(ms - utcOffset * 1000).toISOString().replace("T", " ").replace(/\.\d+Z$/, " UTC");
}
// A destination's files naming no camera and recording no offset (photos-21 unidentified_files,
// BLD-unidentified_files_question): one question — read them as local time in the destination's zone? The answer names
// the zone it is given for (accepted_timezone) and holds while that is the zone in effect: the one the run checked,
// or the one the working decisions now give (previewTz), whichever the user is looking at.
function unidentifiedZone(dest, c) {
  return previewTz(dest)?.tz || c.proposed_iana_timezone || "";
}
function unidentifiedHolds(dest, c) {
  const u = (c && c.user_decision) || {}, z = unidentifiedZone(dest, c || {});
  return u.accept_proposal === true && !!z && u.accepted_timezone === z;
}
const unidentifiedFields = (zone, on) => on ? { accept_proposal: true, accepted_timezone: zone }
  : { accept_proposal: false, accepted_timezone: "" };
function unidentifiedControls(ref) {
  const c = workCell(ref), u = c.user_decision || {}, zone = unidentifiedZone(ref.dest, c), wrap = el("div", { class: "ctl-block" });
  wrap.append(el("div", { class: "hint warn" }, `${c.files} file${c.files === 1 ? "" : "s"} here name${c.files === 1 ? "s" : ""} no camera ` +
    `and record${c.files === 1 ? "s" : ""} no offset with ${c.files === 1 ? "its" : "their"} time (e.g. ${(c.examples || []).map(leaf).join(", ")}). ` +
    "A screenshot or a stripped photo keeps the local time it was made at, if any; nothing else says when it was."));
  if (!zone) wrap.append(el("div", { class: "hint" }, "Set this destination's timezone first."));
  else wrap.append(checkbox(`read them as local time in ${zone}`, unidentifiedHolds(ref.dest, c),
    (v) => editMany(ref, unidentifiedFields(zone, v))));
  if (u.accept_proposal && !unidentifiedHolds(ref.dest, c)) wrap.append(el("div", { class: "hint warn" },
    `Accepted for ${u.accepted_timezone || "no timezone"}; the timezone here is now ${zone || "none"} — accept again, or move the files out.`));
  return wrap;
}
// A photo's time changed since geotag wrote it (photos-21 changed_times, BLD-changed_time_question): keep the time it
// holds — the true local time, read by the destination's zone, no clock offset applied (BLD-changed_time_kept) — or take
// back geotag's. The answer names the time it was given for (answered_for, a copy of held_time) and holds while the
// photo holds that time. An offset tag beside it that the zone does not give then is shown (BLD-changed_time_kept_tag_noted).
const CHANGED_ANSWERS = ["new", "geotag"];
const timePair = (t) => !t || !t.DateTimeOriginal ? "no time" : `${t.DateTimeOriginal}${t.OffsetTimeOriginal ? " " + t.OffsetTimeOriginal : " (no offset)"}`;
function changedHolds(c) {
  const u = (c && c.user_decision) || {}, a = u.answered_for, h = (c && c.held_time) || {};
  return CHANGED_ANSWERS.includes(u.keep) && !!a && typeof a === "object"
    && a.DateTimeOriginal === h.DateTimeOriginal && (a.OffsetTimeOriginal ?? null) === (h.OffsetTimeOriginal ?? null)
    && (u.keep !== "new" || !!h.DateTimeOriginal);
}
const changedFields = (c, keep) => ({ keep, answered_for: keep ? { ...(c.held_time || {}) } : "" });
// "keep" says what the owner ruled it means: the true local time, never corrected by a clock offset.
const changedKeepLabel = (c) => `keep ${timePair(c.held_time)} — this is the true local time: read by the ` +
  "destination's timezone, no camera clock offset applied, now or on any later run";
// The offset tag beside the time, where the destination's zone gives another then (offset_tag_disagrees), or "".
function keptTagNote(c) {
  const dis = c && c.offset_tag_disagrees;
  if (!dis) return "";
  return `Its offset tag says ${utcOff(dis.recorded_offset_seconds)}, but ${dis.timezone} is ` +
    `${(dis.timezone_offsets_seconds || []).map(utcOff).join(" or ")} at that time. Kept, the time is read by the ` +
    "timezone, not the tag, and the tag is written to match — a time set in another zone would be off by the difference.";
}
function changedControls(ref) {
  const c = workCell(ref), u = c.user_decision || {}, wrap = el("div", { class: "ctl-block" });
  wrap.append(el("div", { class: "hint warn" }, `${leaf(ref.key)} holds ${timePair(c.held_time)}, but geotag wrote ` +
    `${c.geotag_wrote ? timePair(c.geotag_wrote) : "no time"} to it, and its own time before geotag was ${timePair(c.own_time)}. ` +
    "Its time was changed since — in another tool, or by a slip. Only you know which it is."));
  const on = changedHolds(c) ? u.keep : "";
  const opt = (keep, label, disabled) => el("div", { class: "off-opt" + (on === keep ? " on" : "") + (disabled ? " disabled" : ""),
    onclick: disabled ? undefined : () => editMany(ref, changedFields(c, keep)) }, el("span", { class: "off-dot" }, on === keep ? "●" : "○"), el("span", {}, label));
  wrap.append(opt("new", changedKeepLabel(c), !(c.held_time || {}).DateTimeOriginal));
  wrap.append(opt("geotag", "take back geotag's time — written again as geotag decided it"));
  const note = keptTagNote(c);
  if (note) wrap.append(el("div", { class: "hint warn" }, note));
  if (u.keep && !changedHolds(c)) wrap.append(el("div", { class: "hint warn" },
    "Answered for another time than the one the photo holds now — answer again."));
  if (u.keep) wrap.append(el("button", { class: "mini", onclick: () => editMany(ref, changedFields(c, "")) }, "clear"));
  return wrap;
}
// A photo's time at a daylight-saving change (photos-21 local_time_readings): pick one of its readings — for a time
// skipped, or type the offset its clock was on. Writes user_decision.utc_offset_seconds.
function readingControls(ref) {
  const c = workCell(ref), u = c.user_decision || {}, wrap = el("div", { class: "ctl-block" });
  const how = c.case === "skipped" ? "never happened there — the clocks went forward over it"
    : "happened twice there — the clocks went back over it";
  wrap.append(el("div", { class: "hint warn" }, `${leaf(ref.key)}: its time ${c.camera_time} ${how} in ${c.timezone}. ` +
    (c.case === "skipped" ? "Pick the offset its clock was on, or type it." : "Pick which of the two it was.")));
  (c.offsets_seconds || []).forEach((o, i) => {
    const on = u.utc_offset_seconds === o;
    wrap.append(el("div", { class: "off-opt" + (on ? " on" : ""), onclick: () => edit(ref, "utc_offset_seconds", o) },
      el("span", { class: "off-dot" }, on ? "●" : "○"),
      el("span", {}, `${utcOff(o)} — ${(c.readings_utc || [])[i] || trueInstant(c.camera_time, o)}` +
        (i === 0 ? " (before the change)" : " (after the change)"))));
  });
  if (c.case === "skipped") {
    const inp = el("input", { type: "text", class: "spin-num", placeholder: "+01:00", value:
      isNum(u.utc_offset_seconds) && !(c.offsets_seconds || []).includes(u.utc_offset_seconds) ? utcOff(u.utc_offset_seconds) : "" });
    inp.addEventListener("change", () => { const v = parseUtcOff(inp.value); edit(ref, "utc_offset_seconds", v == null ? inp.value : v); });
    wrap.append(el("label", { class: "ctl-field" }, el("span", {}, "another offset"), inp));
  }
  if (!validReading(c, u.utc_offset_seconds)) wrap.append(el("div", { class: "err" },
    c.case === "repeated" ? "must be one of its two readings" : "an offset such as +01:00, within ±14:00"));
  if (u.utc_offset_seconds !== "" && u.utc_offset_seconds != null)
    wrap.append(el("button", { class: "mini", onclick: () => edit(ref, "utc_offset_seconds", "") }, "clear"));
  return wrap;
}
// A destination's date fallback: the date its photos with no recorded time were made — a year, a month or a day. It
// times only those photos, at midnight local to the destination, and places none of them by the tracks.
function dateControls(ref) {
  const c = workCell(ref), u = c.user_decision || {}, wrap = el("div", { class: "ctl-block" }), k = (c.untimed_photos || []).length;
  wrap.append(el("div", { class: k ? "hint warn" : "hint" }, (k ? `${k} photo${k === 1 ? "" : "s"} here record${k === 1 ? "s" : ""} no time ` +
    `(${(c.untimed_photos || []).slice(0, 5).map(leaf).join(", ")}${k > 5 ? ", …" : ""}). ` : "") +
    "A date given here times every photo with no recorded time in this folder and the folders inside it, at midnight " +
    "local time; a photo with a time of its own keeps it. The tracks place none of them by it — their position comes " +
    "from their own GPS, a position set for them, or the folder fallback."));
  const inp = el("input", { type: "text", class: "spin-num" + (refInvalid(ref) ? " bad" : ""), placeholder: "1985, 1985-06 or 1985-06-14",
    value: typeof u.date === "string" ? u.date : (u.date == null ? "" : String(u.date)) });
  inp.addEventListener("change", () => edit(ref, "date", inp.value.trim()));
  wrap.append(el("label", { class: "ctl-field" }, el("span", {}, "Date"), inp));
  if (!validDateFallback(u.date)) wrap.append(el("div", { class: "err" }, "a year (1985), a year and month (1985-06) or a day (1985-06-14)"));
  if ((u.date ?? "") !== "") wrap.append(el("button", { class: "mini", onclick: () => edit(ref, "date", "") }, "clear"));
  return wrap;
}
// "+01:00" / "-05:30" / "+0100" / "Z" as seconds east of UTC, or null.
function parseUtcOff(s) {
  const t = String(s || "").trim();
  if (t === "Z") return 0;
  const m = /^([+-])(\d\d):?([0-5]\d)$/.exec(t);
  if (!m || +m[2] > 14) return null;
  const v = (+m[2] * 3600 + +m[3] * 60) * (m[1] === "-" ? -1 : 1);
  return Math.abs(v) <= 14 * 3600 ? v : null;
}
// A span of seconds in the unit a reader takes in at once: years, days, hours or minutes.
function fmtSpan(s) {
  const n = Math.abs(Number(s) || 0);
  if (n >= 365.25 * 86400) return `${Math.round(n / (365.25 * 86400) * 10) / 10} years`;
  if (n >= 2 * 86400) return `${Math.round(n / 86400)} days`;
  if (n >= 2 * 3600) return `${Math.round(n / 3600)} hours`;
  return `${Math.round(n / 60)} minutes`;
}
// A UTC offset as it is recorded with a time ("+01:00"): the zone a clock is set to, not the clock offset.
function utcOff(s) {
  const m = Math.round(Math.abs(s) / 60);
  return `${s < 0 ? "−" : "+"}${_pad(Math.floor(m / 60))}:${_pad(m % 60)}`;
}
// Why an offset cell has no proposal and never will (proposal.timezone_ambiguous): the camera's time is one its
// zone skipped or repeated at a daylight-saving change, so the zone gives it two offsets and no run picks one
// (RUL-ambiguous_local_time_never_guessed). The two are said as clock offsets (camera time + offset = UTC), the
// value the user sets. "" when the cell carries no such fact.
function ambiguousTimeNote(a) {
  const offs = (a && a.offsets_seconds) || [];
  if (offs.length < 2) return "";
  const t = String(a.camera_time || "").replace(/^(\d{4}):(\d\d):(\d\d)/, "$1-$2-$3");
  const how = a.case === "skipped" ? "the clocks went forward over it, so no clock there showed that time"
    : "the clocks went back over it, so that time happened twice";
  return `This camera's time ${t} falls at a daylight-saving change in ${a.timezone}: ${how}. Its offset is either ` +
    `${fmtOffset(-offs[0])} or ${fmtOffset(-offs[1])}, and no re-run of geotag plan will choose — set the offset yourself.`;
}
function proposalNotes(p, cell) {
  const out = [], groups = p.groups || [];
  if (p.tied && groups.length) {
    const n = groups.filter((g) => g.count === groups[0].count).length;
    out.push(`These photos lie on ${n} visits of the tracks equally — pick the day you were there.`);
  }
  if (p.imprecise_seconds) out.push(`The tracks stayed at these photos' place for ${fmtOffset(p.imprecise_seconds).replace(/^[+−-]/, "")}, ` +
    "so their GPS says where but not when — the offset shown is one that fits, not a reading. Accept it and " +
    "check it on the track (Drift view), or set the offset you know.");
  const files = p.conflicting_files || [];
  if (files.length) {
    // what geotag does with them: a clock change, proposed as a split of the day (BLD-clock_change_split); else, once
    // the offset is in effect, their positions set against the tracks (BLD-contradicted_position)
    const shown = files.slice(0, 5).join(", ") + (files.length > 5 ? ` and ${files.length - 5} more` : "");
    out.push(`${files.length} photo${files.length === 1 ? "" : "s"} agree${files.length === 1 ? "s" : ""} with none of these: ${shown}. ` +
      (cell && cell.several_bodies ? "This group may be several bodies: they are likely another body's — set the offset of " +
        "the one whose photos these are, and move the other body's photos into a sub-folder to give them offsets of their own."
        : cell && cell.clock_change ? "The camera's clock changed during the day — see the split offered above."
          : "Accept the offset most agree on: a photo whose own position it contradicts is then offered the track's " +
            "position in the GPS view."));
  }
  return out;
}

// A GPX self-anchor offset proposal, collapsed: the consensus correction, then up to three
// "N photos → ±Xh Ym" groups (each with one named photo at its FULL by-dest path and that photo's
// corrected local time), plus a note for frames skipped (no track / track from another trip).
function offsetProposalBlock(ref, p) {
  if (p.proposal_source === "recorded_offset") {
    // No GPX anchor, but the camera's photos record the UTC offset its clock was set to, all the same one
    // (BLD-recorded_offset_proposal): the clock offset is its negative.
    return el("div", { class: "pblock" }, el("h3", {}, "Proposal — the offset the photos record"),
      el("div", { class: "prop-head" }, fmtOffset(p.proposed_offset_seconds),
        el("span", { class: "muted" }, ` (${p.recorded_by} photo${p.recorded_by === 1 ? "" : "s"} record${p.recorded_by === 1 ? "s" : ""} ` +
          `${utcOff(p.recorded_offset_seconds)} from UTC, e.g. ${leaf(p.example)})`)),
      el("div", { class: "hint" }, (p.proposed_real_utc ? `real UTC ${p.proposed_real_utc} — ` : "") +
        "the camera says its clock was set to that zone; confirm only if its time was right in it (a clock set to the wrong hour keeps its zone)."));
  }
  if (p.proposal_source === "timezone_naive") {
    // No GPX anchor: the offset is derived from the destination's local time for this day, assuming the
    // camera clock tracked it (DST-aware, so summer/winter days get different offsets — BLD-timezone_naive_offset).
    return el("div", { class: "pblock" }, el("h3", {}, "Proposal — derived from the local time"),
      el("div", { class: "prop-head" }, fmtOffset(p.proposed_offset_seconds),
        el("span", { class: "muted" }, ` (assuming the camera was on ${p.proposed_from_timezone} time)`)),
      el("div", { class: "hint" }, `real UTC ${p.proposed_real_utc} — confirm only if the camera really tracked local time (a camera left on home time would be wrong).`));
  }
  if (p.proposal_source === "gps_time") {
    // No GPX anchor, but the photos' own GPS fixes recorded their UTC: each, less the camera time, is a reading of the
    // clock (BLD-gps_time_proposal). Two or more agreeing applied themselves; one is offered.
    const rows = (p.gps_times || []).slice(0, 3).map((r) => el("div", { class: "hint" },
      `${leaf(r.source_file)}: camera ${r.camera_source_naive_time} · fix ${r.gps_utc} → ${fmtOffset(r.offset_seconds)}`));
    return el("div", { class: "pblock" }, el("h3", {}, "Proposal — the times the GPS fixes recorded"),
      el("div", { class: "prop-head" }, fmtOffset(p.proposed_offset_seconds),
        el("span", { class: "muted" }, ` (${p.gps_time_count} fix${p.gps_time_count === 1 ? "" : "es"}, ${p.confidence})`)),
      ...rows,
      el("div", { class: "hint" }, p.gps_time_count === 1
        ? "one fix only: a stale one repeats an earlier time — accept it if the photo's corrected time is right."
        : "the fixes' times all differ and agree: applied by itself."));
  }
  if (p.proposal_source === "neighbour_day") return el("div", { class: "pblock" },
    el("h3", {}, "Proposal — the day next to it"), el("div", { class: "prop-head" }, fmtOffset(p.proposed_offset_seconds)),
    el("div", { class: "hint" }, neighbourDayNote(p, workCell(ref)?.effective_time_anchor)));
  if (p.proposal_source !== "gpx_self_anchor") return jsonBlock("Proposal", p);
  const tz = previewTz(ref.dest)?.tz;
  const wrap = el("div", { class: "pblock" }, el("h3", {}, "Proposal — suggested clock correction"),
    el("div", { class: "prop-head" }, fmtOffset(p.proposed_offset_seconds),
      el("span", { class: "muted" }, ` (${p.confidence}; ${p.anchor_count} geotagged photo${p.anchor_count === 1 ? "" : "s"})`)));
  for (const note of proposalNotes(p, workCell(ref))) wrap.append(el("div", { class: "hint warn" }, note));
  const groups = p.groups || [];
  const u = workCell(ref)?.user_decision || {}, picked = chosenOffset(p, u);
  for (const g of groups.slice(0, 3)) {
    // camera (naive wall time) → corrected (real UTC in the destination tz), both formatted identically;
    // when the date is unchanged it's shown once and the arrow carries only the time correction.
    const cam = camNaiveMs(g.representative.camera_source_naive_time), real = utcStrToMs(g.representative.real_utc);
    const cdt = cam != null ? fmtDT(cam, "UTC") : null, rdt = real != null && tz ? fmtDT(real, tz) : null;
    let line;
    if (cdt && rdt) line = cdt.date === rdt.date
      ? `${cdt.date} · ${cdt.time} → ${rdt.time} (${tz})`
      : `${cdt.date} ${cdt.time} → ${rdt.date} ${rdt.time} (${tz})`;
    else if (cdt) line = `${cdt.date} ${cdt.time} → ${g.representative.real_utc} — set this destination's timezone to see local time`;
    else line = `camera ${g.representative.camera_source_naive_time} → ${g.representative.real_utc}`;
    const on = picked === g.offset_seconds;
    wrap.append(el("div", { class: "prop-group" + (on ? " on" : "") },
      el("div", { class: "prop-group-h" }, `${g.count} photo${g.count === 1 ? "" : "s"} → ${fmtOffset(g.offset_seconds)}`,
        on ? el("span", { class: "muted" }, " ✓ chosen")
          : el("button", { class: "mini", onclick: () => { state.offsetEdit = null; editMany(ref, groupChoice(p, g, inConflict(workCell(ref)))); } },
            g.offset_seconds === p.proposed_offset_seconds && !inConflict(workCell(ref)) ? "accept" : "use this")),
      el("div", { class: "hint" }, `e.g. ${g.representative.source_file}` +
        (g.representative.gpx_file ? ` · track ${g.representative.gpx_file}` : "")),
      el("div", { class: "hint" }, line)));
  }
  if (groups.length > 3) wrap.append(el("div", { class: "hint" }, `+ ${groups.length - 3} more correction group(s)`));
  const sk = p.skipped || {}, notes = [];
  if (sk.outside_time_window) notes.push(`${sk.outside_time_window} with a GPX track only outside the plausible time window (likely a different trip/year)`);
  if (sk.no_nearby_track) notes.push(`${sk.no_nearby_track} with no nearby GPX track`);
  if (notes.length) wrap.append(el("div", { class: "hint skip" }, `Skipped: ${notes.join("; ")}.`));
  return wrap;
}
function renderPanel() {
  const p = $("#panel"); p.replaceChildren();
  _coordInp = null;                                   // re-set by coordField() when this panel has one
  const ref = state.selected, c = workCell(ref);
  const isGpsCoord = ref && ref.file === "gps" && ["fallback", "review", "chosen"].includes(ref.kind);
  const isScrub = ref && ref.kind === "drift";
  if (!isGpsCoord && !isScrub) teardownMap();
  const cellKey = mapKeyFor(ref);
  if (cellKey !== _driftCellKey) { _driftFrame = 0; _driftTab = "photo"; _driftCellKey = cellKey; }  // reset frame + tab per cell
  if (!ref || !c) return p.append(el("div", { class: "empty" }, "Select a decision to edit it."));
  const multi = ref.peers && ref.peers.length > 1;
  const title = ref.kind === "offset" ? `Offset · ${c.camera_group || ref.key}${c.phone ? " (phone)" : ""}`
    : ref.kind === "reading" ? "Time at a daylight-saving change"
    : ref.kind === "changed" ? "Time changed since geotag wrote it"
    : ref.kind === "unidentified" ? "Files naming no camera"
    : ref.kind === "date" ? "Date fallback"
    : ref.kind === "drift" ? `Drift · ${c.camera_group || ref.key}`
    : ref.kind === "fingerprint" ? "Content changed after a write"
    : ref.kind === "camera" ? "A new camera group"
    : ref.kind === "bodies" ? "One camera, or several bodies"
    : ref.kind === "review" ? (multi ? `GPS review · ${ref.peers.length} photos` : "GPS review item")
    : ref.kind === "chosen" ? "A position for one placed photo"
      : ref.kind === "fallback" ? "Folder fallback" : "Timezone";
  p.append(el("h2", {}, title), el("div", { class: "path" }, ref.path || (["reading", "camera", "bodies", "changed"].includes(ref.kind) ? ref.key : ref.dest)));
  const head = el("div", { class: "pblock" }, ...(statusChip(ref) ? [statusChip(ref)] : []), ...tags(ref));
  // A multi-cell ref edits several siblings at once — say so. Offset cluster → which days; review run → how many.
  if (ref.kind === "offset" && multi) {
    const dates = ref.peers.map((k) => workCell({ ...ref, key: k })?.date).filter(Boolean);
    head.append(el("div", { class: "hint" }, `editing all ${ref.peers.length} days with this proposal: ${dateRange(dates)}`));
  } else if (ref.kind === "offset" && c.date) {
    head.append(el("div", { class: "hint" }, `this day only: ${fmtDate(c.date)}`));
  } else if (ref.kind === "review" && multi) {
    head.append(el("div", { class: "hint" }, `applying one location to all ${ref.peers.length} selected photos: ${ref.peers.map((p2) => p2.split("/").pop()).join(", ")}`));
  } else if (ref.kind === "review") {
    head.append(el("div", { class: "hint" }, "shift-click another photo in this destination to select a run and place them together"));
  } else if (ref.kind === "drift" && c.date) {
    head.append(el("div", { class: "hint" }, `this day only: ${fmtDate(c.date)}`));
  }
  if (isDirty(ref)) head.append(el("button", { class: "mini", onclick: () => resetRef(ref) }, "reset"));
  // Fixed top: title + status + the decision controls + the effective preview — always visible, no scroll.
  const top = el("div", { class: "panel-top" },
    el("h2", {}, title), el("div", { class: "path" }, ref.path || (["reading", "camera", "bodies", "changed"].includes(ref.kind) ? ref.key : ref.dest)), head,
    el("div", { class: "pblock" }, el("h3", {}, "Your decision"), decisionThumb(ref), controls(ref)),
    el("div", { class: "pblock eff" }, el("h3", {}, "Effective (advisory — re-run to apply)"), el("div", { class: "eff-val" }, previewEffective(ref))));
  // Scroll area, the only thing that scrolls. For a GPS coord cell the MAP comes first — directly under
  // the pinned "Your decision" box — so a paste/edit's effect (jump to full zoom) is visible without
  // scrolling; then the photo; then the proposal evidence last. Non-GPS cells just show the proposal.
  const scroll = el("div", { class: "panel-scroll" });
  if (isScrub) scroll.append(scrubBlock(ref));
  if (isGpsCoord) scroll.append(mapBlock(ref));   // the review photo is now a thumbnail in "Your decision" + a hover preview in the worklist
  // No raw "Proposal" JSON box for fallback — the inherited proposal is already shown in the
  // "accept inherited (lat, lon)" checkbox label, so the JSON dump was redundant clutter.
  if (c.proposal && ref.kind !== "drift" && ref.kind !== "fallback" && ref.kind !== "reading" && ref.kind !== "fingerprint" && ref.kind !== "camera" && ref.kind !== "bodies")
    scroll.append(ref.kind === "offset" ? offsetProposalBlock(ref, c.proposal) : jsonBlock("Proposal", c.proposal));
  p.replaceChildren(top, scroll);
}

// --- header / save -----------------------------------------------------------
// The save's body: the edits, by record, and the hashes of the records as the editor loaded them. The server
// refuses the save when a record on disk is not the one loaded (RUL-save_only_what_was_shown), and its refusal
// shows through the save-error message below.
function savePayload(refs, cellOf, hashes) {
  const payload = { time: [], drift: [], gps: [], execution: [], cameras: [], hashes: { ...(hashes || {}) } };
  for (const ref of refs)
    (payload[ref.file] = payload[ref.file] || []).push({ dest: ref.dest, kind: ref.kind, key: ref.key, path: ref.path, user_decision: cellOf(ref).user_decision });
  return payload;
}

async function save() {
  if (state.base.demo || state.saving) return;
  const payload = savePayload(dirtyRefs(), workCell, state.base.hashes);
  state.saving = true; state.message = "saving…"; render();
  try {
    const r = await (await fetch("/api/save", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(payload) })).json();
    // The records now hold what was saved: their new hashes are what the next save is made from.
    if (r.ok) {
      state.work.hashes = r.hashes; state.base = clone(state.work);
      // an answer in photos-25 is read by the next execution; every other, by the next plan
      const next = r.written.length && r.written.every((n) => n.startsWith("photos-25")) ? "geotag execute" : "geotag plan";
      state.message = `saved ${r.written.join(", ")} — run \`photos-cartographer ${next}\` then reload to apply`;
    }
    else state.message = "save failed: " + (r.error || "unknown");
  } catch (e) { state.message = "save failed: " + e; }
  state.saving = false; render();
}

// Geotag is re-run from the CLI (`photos-cartographer geotag plan`), then the operator reloads the page;
// the editor only edits + saves the decision JSON (no in-app Re-run — it was error-prone and offered
// little over a terminal command).

function render() {
  hideHoverPreview();                              // a re-render replaces the worklist rows; drop any stuck hover preview
  const a = state.base;
  $("#workspace").textContent = a.demo ? "demo mode — example fixtures (read-only)" : a.workspace;
  for (const b of document.querySelectorAll("#view-toggle button")) b.classList.toggle("on", b.dataset.view === state.view);
  const dirty = dirtyRefs().length, invalid = anyInvalid(), busy = state.saving;
  $("#todo").textContent = dirty ? `${dirty} unsaved${invalid ? " · ✗ invalid" : ""}` : (state.message || "no changes");
  const save = $("#save"); save.disabled = a.demo || busy || dirty === 0 || invalid;
  save.title = a.demo ? "demo mode is read-only — run `photos-cartographer edit` from inside a workspace to save" : invalid ? "fix invalid fields first" : "";
  $("#reset").disabled = dirty === 0 || busy;
  const list = $("#list"); list.replaceChildren();
  ({ cameras: renderCameras, time: renderTime, drift: renderDrift, gps: renderGps, execution: renderExecution }[state.view] || renderTime)(list);
  renderPanel();
}

// Draggable list|panel split. The divider sets the grid's first-column width (`--list-w`); the panel
// takes the rest. Clamped to sane bounds, persisted in localStorage, and the map is resized live so
// Leaflet keeps filling its (now narrower/wider) pane.
function setupDivider() {
  const divider = $("#divider"), mainEl = document.querySelector("main"), root = document.documentElement;
  try { const w = localStorage.getItem("listW"); if (w) root.style.setProperty("--list-w", w); } catch { /* ignore */ }
  let dragging = false;
  const onMove = (e) => {
    if (!dragging) return;
    const x = e.clientX - mainEl.getBoundingClientRect().left;
    const w = Math.max(280, Math.min(mainEl.clientWidth - 340, x));
    root.style.setProperty("--list-w", `${Math.round(w)}px`);
    if (_map) _map.refresh();
  };
  divider.addEventListener("mousedown", (e) => { e.preventDefault(); dragging = true; divider.classList.add("dragging"); document.body.style.userSelect = "none"; });
  window.addEventListener("mousemove", onMove);
  window.addEventListener("mouseup", () => {
    if (!dragging) return;
    dragging = false; divider.classList.remove("dragging"); document.body.style.userSelect = "";
    try { localStorage.setItem("listW", root.style.getPropertyValue("--list-w")); } catch { /* ignore */ }
    if (_map) _map.refresh();
  });
}

// Why loading the decisions was refused, or "" when they loaded. The console's Edit tab answers 409
// {ok:false, error} for a workspace that is sealed, not initialized, or open in another editor; any other
// failed answer is said by its status.
function loadRefusal(status, body) {
  if (body && body.ok === false) return body.error || `the decisions could not be loaded (HTTP ${status})`;
  if (!(status >= 200 && status < 300)) return (body && body.error) || `the decisions could not be loaded (HTTP ${status})`;
  return "";
}
// Edits made here and not saved (demo edits cannot be saved, so they are none). Read by the console before it
// reloads its Edit tab (window.editorHasUnsavedEdits) and by the browser-level reload/close guard.
function hasUnsavedEdits() {
  return !!(state.base && state.work) && !state.base.demo && dirtyRefs().length > 0;
}
// A refused load shows the refusal in place of the views, and leaves nothing to edit.
function showRefusal(msg) {
  for (const b of document.querySelectorAll("#view-toggle button")) b.disabled = true;
  $("#workspace").textContent = ""; $("#todo").textContent = "";
  $("#list").replaceChildren(el("div", { class: "gate" }, el("div", { class: "gate-title" }, "The decision editor cannot open this workspace"), msg));
  $("#panel").replaceChildren();
}

async function main() {
  window.editorHasUnsavedEdits = hasUnsavedEdits;
  window.addEventListener("beforeunload", (e) => { if (hasUnsavedEdits()) { e.preventDefault(); e.returnValue = ""; } });
  for (const b of document.querySelectorAll("#view-toggle button")) b.addEventListener("click", () => { state.view = b.dataset.view; state.selected = null; render(); });
  $("#save").addEventListener("click", save);
  $("#reset").addEventListener("click", () => { state.work = clone(state.base); state.message = null; render(); });
  setupDivider();
  let res = null, body = null;
  try { res = await fetch("/api/artifacts"); body = await res.json(); }
  catch (e) { return showRefusal(res ? `the decisions could not be loaded (HTTP ${res.status})` : `the decisions could not be loaded: ${e}`); }
  const refusal = loadRefusal(res.status, body);
  if (refusal) return showRefusal(refusal);
  setHostZones(body.zones);
  state.base = withChosenCells(body); state.work = clone(state.base);
  if (Object.keys(body.cameras?.groups || {}).length) state.view = "cameras";   // geotag waits on these first
  render();
}
// Auto-start in the browser only; importing this module in Node (for the unit tests) must not run it
// (there's no document/fetch there). The named exports below expose the pure logic for those tests.
if (typeof document !== "undefined") main();

export {
  isNum, validTz, setHostZones, validOffset, validLat, validLon, bothOrNeither,
  fmtOffset, camNaiveMs, dtLocalToMs, msToDtLocal, utcStrToMs, fmtLocal, fmtDT, offsetImpact,
  cellAt, cellStatus, wouldResolve, previewTz, previewFallback, refInvalid, isDirty, state,
  offsetGroups, dateRange, fmtDate, peerKeys, parseLatLon, coordText, contiguousRange,
  groupChoice, chosenOffset, inConflict, proposalTaken, proposalNotes, driftConfirmHolds, driftConfirmFields, driftCorrectionFields, driftTracksHold, driftStaleReason, acceptFields, acceptHolds, tracksNote,
  zoneContradiction, offsetCellNotes, zoneSpokenFor, zoneDespiteFields, effectiveCountry, clearCountriesInside,
  clockChangeHolds, clockChangePartsGiven, clockChangeFields, clockChangePart, contradictedNote, takeTrackPosition, neighbourDayNote,
  scrubOffset, scrubSeedIndex, mapKeyFor, savePayload, withChosenCells, reviewOffers, placedByLabel, placedSummary,
  ambiguousTimeNote, gpsTimeAsideNote, zoneOffer, validReading, keepHolds, keepFields, keepOffered, phoneNote,
  trueInstant, parseUtcOff, mismatchAccepted, recordAbsentText, DEVICE_CLASSES, changedHolds, changedFields, changedKeepLabel, keptTagNote, unidentifiedHolds, unidentifiedFields, loadRefusal, hasUnsavedEdits, utcOff,
  dateFallbackDay, validDateFallback, previewDate, showsDate,
  fmtSpan, utcToZonedWallMs, zonedWallToUtcMs, offsetFromTrueTime, trueTimeOf,
};
