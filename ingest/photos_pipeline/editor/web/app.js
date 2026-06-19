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
function validTz(s) { if (s === "" || s == null) return true; try { new Intl.DateTimeFormat("en", { timeZone: s }); return true; } catch { return false; } }
function validOffset(v) { return v === "" || v == null || (isNum(v) && Math.abs(v) <= 86400); }
function validUtc(s) { if (s === "" || s == null) return true; return /^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(Z|[+-]\d{2}:\d{2})?$/.test(s) && !isNaN(Date.parse(s)); }
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
    return ref.kind === "timezone" ? d.destination_timezone : d.camera_group_time_decisions?.[ref.key];
  }
  if (ref.file === "drift") {
    const d = arts.drift?.destinations?.[ref.dest]; if (!d) return null;
    return d.drift_decisions?.[ref.key];
  }
  const d = arts.gps?.destinations?.[ref.dest]; if (!d) return null;
  if (ref.kind === "fallback") return d.folder_fallback;
  return (d.gps_decisions?.review_items || []).find((r) => r.relative_path === ref.path);
}
const workCell = (ref) => cellAt(state.work, ref);
const baseCell = (ref) => cellAt(state.base, ref);

function allRefs() {
  const out = [];
  for (const [dest, d] of Object.entries(state.work.time?.destinations || {})) {
    out.push({ file: "time", dest, kind: "timezone" });
    for (const key of Object.keys(d.camera_group_time_decisions || {})) out.push({ file: "time", dest, kind: "offset", key });
  }
  for (const [dest, d] of Object.entries(state.work.drift?.destinations || {})) {
    for (const key of Object.keys(d.drift_decisions || {})) out.push({ file: "drift", dest, kind: "drift", key });
  }
  for (const [dest, d] of Object.entries(state.work.gps?.destinations || {})) {
    out.push({ file: "gps", dest, kind: "fallback" });
    for (const ri of d.gps_decisions?.review_items || []) out.push({ file: "gps", dest, kind: "review", path: ri.relative_path });
  }
  return out;
}
function isDirty(ref) {
  const w = workCell(ref), b = baseCell(ref);
  return w && b && JSON.stringify(w.user_decision) !== JSON.stringify(b.user_decision);
}
function refInvalid(ref) {
  const c = workCell(ref); if (!c) return false; const u = c.user_decision || {};
  if (ref.kind === "timezone") return !validTz(u.manual_iana_timezone);
  if (ref.kind === "offset") return !validOffset(u.manual_offset_seconds) || !validUtc(u.manual_real_utc);
  if (ref.kind === "drift") return !validOffset(u.corrected_offset_seconds);
  if (ref.kind === "fallback") return !validLat(u.fallback_lat) || !validLon(u.fallback_lon) || !bothOrNeither(u.fallback_lat, u.fallback_lon);
  return !validLat(u.manual_lat) || !validLon(u.manual_lon) || !bothOrNeither(u.manual_lat, u.manual_lon);
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
      const udSig = `${u.accept_proposal === true ? 1 : 0}|${u.manual_offset_seconds ?? ""}|${u.manual_real_utc ?? ""}`;
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
const peerField = (ref) => (ref.kind === "review" ? "path" : "key");
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
  if (cell.requires_user_input) return ["needs", "needs input"];
  if (cell.stale_user_decision) return ["stale", "stale"];
  if (cell.decision_mode === "auto_resolved") return ["auto", "auto"];
  return ["ok", "resolved"];
}
const chip = (k, t) => el("span", { class: `chip ${k}` }, t);
// Would the WORKING decision resolve this cell? (advisory — mirrors the reference §6 resolution rules.)
function wouldResolve(ref) {
  const c = workCell(ref); if (!c) return false;
  const u = c.user_decision || {}, p = c.proposal || {};
  if (ref.kind === "timezone")
    return (!!u.manual_iana_timezone && validTz(u.manual_iana_timezone)) || (!!u.accept_proposed_timezone && !!c.proposed_iana_timezone);
  if (ref.kind === "offset")
    return (u.manual_offset_seconds !== "" && u.manual_offset_seconds != null && validOffset(u.manual_offset_seconds))
      || (!!u.manual_real_utc && validUtc(u.manual_real_utc) && p.proposal_source === "gpx_self_anchor")
      || (!!u.accept_proposal && "proposed_offset_seconds" in p);
  if (ref.kind === "drift")                       // confirmed (zero-scrub or a valid correction) resolves
    return !!u.confirmed && validOffset(u.corrected_offset_seconds);
  if (ref.kind === "fallback")
    return (u.fallback_lat !== "" && u.fallback_lat != null && u.fallback_lon !== "" && u.fallback_lon != null)
      || (!!u.accept_proposal && !!p.proposed_fallback);
  return (u.manual_lat !== "" && u.manual_lat != null && u.manual_lon !== "" && u.manual_lon != null) || !!u.accept_unlocated;
}
function statusChip(ref) {
  if (isDirty(ref)) {                          // a pending edit supersedes the last run's status
    if (refInvalid(ref)) return null;          // the ✗ invalid chip (tags) already speaks
    if (wouldResolve(ref)) return chip("ok", "resolved");
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
// UTC epoch ms (Date.UTC), matching geotag's `real_utc_naive − camera_naive` (photos_pipeline.photos_2_geotag).
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
// --- GPS-drift scrub math (§22a) ---------------------------------------------
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
    if (u.accept_proposed_timezone && c.proposed_iana_timezone) return c.proposed_iana_timezone;
    const pv = previewTz(ref.dest);
    if (pv && pv.source === "inherited") return `${pv.tz} (inherited ⟵ ${leaf(pv.from)}, preview)`;
    return "— (needs input)";
  }
  if (ref.kind === "offset") {
    if (u.manual_offset_seconds !== "" && u.manual_offset_seconds != null)
      return validOffset(u.manual_offset_seconds) ? `${fmtOffset(u.manual_offset_seconds)} (manual)` : "✗ invalid offset";
    if (u.manual_real_utc) return validUtc(u.manual_real_utc) ? "via real-UTC (computed on re-run)" : "✗ invalid UTC";
    if (u.accept_proposal && "proposed_offset_seconds" in p) return `${fmtOffset(p.proposed_offset_seconds)} (accept proposal)`;
    return "— (GPX auto-resolves on re-run, else needs input)";
  }
  if (ref.kind === "drift") {
    if (!u.confirmed) return "— (needs confirmation)";
    if (u.corrected_offset_seconds === "" || u.corrected_offset_seconds == null)
      return `${fmtOffset(p.current_offset_seconds)} (confirmed — offset was right)`;
    return validOffset(u.corrected_offset_seconds)
      ? `${fmtOffset(u.corrected_offset_seconds)} (corrected)` : "✗ invalid offset";
  }
  if (ref.kind === "fallback") {
    if (u.fallback_lat !== "" && u.fallback_lon !== "") return `${u.fallback_lat}, ${u.fallback_lon}`;
    if (u.accept_proposal && p.proposed_fallback) return `${p.proposed_fallback.lat}, ${p.proposed_fallback.lon} (inherited)`;
    const pv = previewFallback(ref.dest);
    if (pv && pv.source === "inherited") return `${pv.lat}, ${pv.lon} (inherited ⟵ ${leaf(pv.from)}, preview)`;
    return "— (optional)";
  }
  if (u.manual_lat !== "" && u.manual_lon !== "") return `${u.manual_lat}, ${u.manual_lon} (manual)`;
  if (u.accept_unlocated) return "left unlocated";
  return "— (needs a coordinate or accept-unlocated)";
}

// --- advisory timezone inheritance preview -----------------------------------
// Mirrors geotag's rule for DISPLAY ONLY: a child timezone with no own decision would, on re-run,
// inherit from its nearest ancestor that resolves. Updates live as you edit ancestors; authoritative
// only after Re-run. (Timezone never auto-resolves, so a resolved value always traces to a decision.)
const leaf = (p) => (p || "").split("/").pop();
function tzOwnDecision(dest) {
  const c = state.work.time?.destinations?.[dest]?.destination_timezone;
  if (!c) return null;
  const u = c.user_decision || {};
  if (u.manual_iana_timezone) return { tz: u.manual_iana_timezone, source: "manual" };
  if (u.accept_proposed_timezone && c.proposed_iana_timezone) return { tz: c.proposed_iana_timezone, source: "accept" };
  return null;
}
function previewTz(dest) {
  const own = tzOwnDecision(dest);
  if (own) return own;
  const parts = dest.split("/");
  for (let i = parts.length - 1; i > 0; i--) {
    const anc = parts.slice(0, i).join("/");
    if (state.work.time?.destinations?.[anc]) {
      const a = previewTz(anc);
      if (a && a.tz) return { tz: a.tz, source: "inherited", from: anc };
    }
  }
  return null;
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
  }                                                       // offsets never inherit (per-date buckets, §10.2)
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
    renderOffsetRows(node.path, node.dest, n);
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
  const eff = e && typeof e === "object" ? fmtOffset(e.offset_seconds)
    : "proposed_offset_seconds" in (cell.proposal || {}) ? `${fmtOffset(cell.proposal.proposed_offset_seconds)} proposed` : "—";
  const s = pr && pr.source === "timezone_naive" && pr.tz ? `${sub} · from ${leaf(pr.tz)}` : sub;
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
function renderTime(list) {
  const t = state.work.time;
  if (!t?.destinations) return list.append(el("div", { class: "empty" }, "No photos-21-time-decisions.json."));
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
  if (!g?.destinations) return list.append(el("div", { class: "empty" }, "No photos-23-gps-decisions.json."));
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
  if (!dr?.destinations) return list.append(el("div", { class: "empty" }, "No photos-22-gps-drift-validation.json."));
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

// --- editing controls --------------------------------------------------------
function checkbox(label, checked, onchange, disabled) {
  const cb = el("input", { type: "checkbox", disabled: disabled ? "" : null }); cb.checked = !!checked; cb.addEventListener("change", () => onchange(cb.checked));
  return el("label", { class: disabled ? "ctl-check disabled" : "ctl-check" }, cb, label);
}

let TZ_ZONES = null;
function tzZones() {
  if (TZ_ZONES) return TZ_ZONES;
  try { TZ_ZONES = Intl.supportedValuesOf("timeZone"); } catch { TZ_ZONES = ["UTC", "Europe/Brussels", "Asia/Tokyo", "America/New_York"]; }
  return TZ_ZONES;
}
function tzSelect(value, onchange, disabled) {
  const cur = value || "", zones = tzZones();
  const opts = [el("option", { value: "" }, "— none —"), ...zones.map((z) => el("option", { value: z }, z))];
  // Keep a pre-existing value the browser doesn't know about visible/selectable rather than silently dropping it.
  if (cur && !zones.includes(cur)) opts.splice(1, 0, el("option", { value: cur }, cur + " (unknown)"));
  const sel = el("select", { class: validTz(cur) ? null : "bad", disabled: disabled ? "" : null }, ...opts);
  sel.value = cur;
  sel.addEventListener("change", () => onchange(sel.value));
  return sel;
}

// Offset editor: the h/m/s spinner and a real-UTC datetime picker are two views of one stored value
// (manual_offset_seconds). Whichever view you click drives editing; the other goes read-only and tracks
// it. The UTC view only exists for a gpx_self_anchor proposal (it needs the anchor frame's camera time);
// editing always canonicalizes to the offset and clears manual_real_utc so the stored value is unambiguous.
// The clock offset is set in exactly ONE of three mutually-exclusive ways — accept the proposal, a
// manual offset, or the anchor frame's real-UTC — mapped to the three user_decision fields
// (accept_proposal / manual_offset_seconds / manual_real_utc). Picking one resets the other two, so the
// reference §6 precedence never has to arbitrate. Anchor real-UTC needs a gpx_self_anchor frame.
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
  // Representative camera-naive instant for the Impact line — the anchor frame's time for a GPX proposal,
  // else recovered from a timezone-derived proposal (camera_naive = proposed_real_utc − proposed_offset),
  // so the per-date / timezone buckets also show "camera local → corrected local" with the common date.
  const repCamMs = camMs != null ? camMs
    : (hasProp && p.proposed_real_utc != null && utcStrToMs(p.proposed_real_utc) != null
      ? utcStrToMs(p.proposed_real_utc) - p.proposed_offset_seconds * 1000 : null);
  const accepted = !!u.accept_proposal && hasProp;
  let manualOff = u.manual_offset_seconds;            // canonical store; tolerate a legacy manual_real_utc
  if ((manualOff === "" || manualOff == null) && u.manual_real_utc && camMs != null) {
    const m = utcStrToMs(u.manual_real_utc); if (m != null) manualOff = Math.round((m - camMs) / 1000);
  }
  const manualSet = manualOff !== "" && manualOff != null;
  const selKey = `${ref.dest}|${ref.key}`;
  // Exactly one of three choices is active. For a self-set value the active VIEW (offset spinner vs
  // anchor-UTC picker) is a per-cell UI state; default to the spinner. The automatic (accept) value is
  // never edited — it's always the proposal. Clicking a choice activates it; the other manual view
  // updates to show the active value (synced), the automatic stays the proposal.
  const view = state.offsetEdit && state.offsetEdit.key === selKey ? state.offsetEdit.view : "offset";
  const active = accepted ? "accept" : manualSet ? view : "";
  const eff = accepted ? p.proposed_offset_seconds : manualSet ? Number(manualOff) : (hasProp ? p.proposed_offset_seconds : null);
  const cur = Number(eff) || 0, abs = Math.abs(cur);

  const setManual = (off, v) => { state.offsetEdit = { key: selKey, view: v }; editMany(ref, { accept_proposal: false, manual_real_utc: "", manual_offset_seconds: off }); };
  const choose = (v) => { state._focusOffset = v; if (manualSet) { state.offsetEdit = { key: selKey, view: v }; render(); } else setManual(eff ?? 0, v); };
  const accept = () => { state.offsetEdit = null; editMany(ref, { accept_proposal: true, manual_offset_seconds: "", manual_real_utc: "" }); };
  const opt = (on, body, onclick, cls = "") => el("div", { class: "off-opt" + (on ? " on" : "") + cls, onclick },
    el("span", { class: "off-dot" }, on ? "●" : "○"), body);

  const wrap = el("div", { class: "ctl-block" });
  let numI, pickI;

  // choice 1 — accept the proposal (automatic; its value is never edited)
  const src = p.proposal_source === "timezone_naive" ? ` from timezone ${p.proposed_from_timezone}` : "";
  wrap.append(opt(active === "accept",
    el("span", {}, hasProp ? `accept proposal (${fmtOffset(p.proposed_offset_seconds)})${src}` : "accept proposal — none to accept"),
    hasProp ? accept : undefined, hasProp ? "" : " disabled"));

  // choice 2 — manual offset (h/m/s spinner). Editable only when active; otherwise click to activate.
  const editO = active === "offset";
  const bump = (secs, dir) => setManual(Math.max(-86400, Math.min(86400, cur + dir * secs)), "offset");
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
  if (editO && !validOffset(manualOff)) wrap.append(el("div", { class: "err" }, "offset must be within ±86400 s"));

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

  // common Impact line — what the effective offset does to the anchor photo (or the offset + formula)
  const tz = previewTz(ref.dest)?.tz;
  if (eff == null) wrap.append(el("div", { class: "off-impact hint" }, "no offset set — a GPX self-anchor auto-resolves on re-run; otherwise this day needs input"));
  else if (repCamMs != null) {
    wrap.append(el("div", { class: "off-impact" }, offsetImpact(repCamMs, cur, tz)));
    if (!tz) wrap.append(el("div", { class: "hint" }, "set this destination's timezone to see the corrected local time"));
  } else {
    wrap.append(el("div", { class: "off-impact" }, `offset ${fmtOffset(cur)} — a photo's camera time + this = UTC${tz ? `, shown in ${tz}` : ""}`));
  }
  // no proposal at all → tell the user how to get one: a resolved timezone yields a timezone-derived offset
  if (!hasProp) wrap.append(el("div", { class: "hint" }, tz
    ? "no offset proposal yet — re-run `photos-cartographer geotag plan` to derive one from the resolved timezone"
    : "no offset proposal — set this destination's timezone (Time view), then re-run `photos-cartographer geotag plan`, to derive one from the local time"));

  if (accepted || manualSet) wrap.append(el("button", { class: "mini",
    onclick: () => { state.offsetEdit = null; editMany(ref, { accept_proposal: false, manual_offset_seconds: "", manual_real_utc: "" }); } },
    "clear (let geotag auto-resolve / re-derive)"));

  // restore focus to the view just activated (click-to-activate), so it's ready to edit
  if (state._focusOffset) {
    const tgt = state._focusOffset === "utc" ? pickI : numI; state._focusOffset = null;
    if (tgt) queueMicrotask(() => tgt.focus());
  }
  return wrap;
}

function controls(ref) {
  const c = workCell(ref), u = c.user_decision, p = c.proposal || {}, wrap = el("div", { class: "ctl-block" });
  if (ref.kind === "timezone") {
    const hasProp = !!c.proposed_iana_timezone;
    const locked = !!u.accept_proposed_timezone && hasProp;
    // Accepting the proposal mirrors it into the manual field and locks the drop-down; unaccepting frees it again.
    wrap.append(checkbox(`accept proposed${hasProp ? " (" + c.proposed_iana_timezone + ")" : " — none"}`, u.accept_proposed_timezone,
      (v) => v && hasProp
        ? editMany(ref, { accept_proposed_timezone: true, manual_iana_timezone: c.proposed_iana_timezone })
        : edit(ref, "accept_proposed_timezone", v), !hasProp));
    const sel = tzSelect(u.manual_iana_timezone, (v) => edit(ref, "manual_iana_timezone", v), locked);
    wrap.append(el("label", { class: "ctl-field" }, el("span", {}, "Manual timezone"), sel));
    if (!validTz(u.manual_iana_timezone)) wrap.append(el("div", { class: "err" }, "not a valid IANA timezone"));
  } else if (ref.kind === "offset") {
    wrap.append(offsetEditor(ref));
  } else if (ref.kind === "drift") {
    wrap.append(driftControls(ref));
  } else if (ref.kind === "fallback") {
    const hasProp = p.proposal_source === "inherited";
    wrap.append(checkbox(hasProp ? `accept inherited (${p.proposed_fallback.lat}, ${p.proposed_fallback.lon})` : "accept inherited — none", u.accept_proposal, (v) => edit(ref, "accept_proposal", v), !hasProp));
    wrap.append(coordField(ref));
  } else {
    wrap.append(coordField(ref));
    wrap.append(checkbox("leave unlocated (accept no GPS)", u.accept_unlocated, (v) => edit(ref, "accept_unlocated", v)));
  }
  return wrap;
}
// GPS-drift bucket: confirm the current offset as-is (zero scrub — must be explicit) or show the
// scrubbed correction. The scrub itself happens on the track map below (it sets `confirmed` +
// `corrected_offset_seconds`); this pinned control is the affirmation + readout + a clear-back.
function driftControls(ref) {
  const c = workCell(ref), u = c.user_decision || {}, p = c.proposal || {}, wrap = el("div", { class: "ctl-block" });
  wrap.append(el("div", { class: "hint" },
    `Current offset ${fmtOffset(p.current_offset_seconds)} (${p.proposal_source || "?"}). Scroll the photo along the track below to correct it, or confirm it as-is.`));
  wrap.append(checkbox("confirm this bucket (offset is right as shown)", u.confirmed, (v) => edit(ref, "confirmed", v)));
  const corr = u.corrected_offset_seconds;
  if (corr !== "" && corr != null) {
    const delta = isNum(corr) ? corr - (p.current_offset_seconds || 0) : null;
    wrap.append(el("div", { class: "ctl-field" },
      el("span", {}, `scrubbed correction: ${fmtOffset(corr)}${delta != null ? ` (Δ ${fmtOffset(delta)})` : ""}`),
      el("button", { class: "mini", onclick: () => editMany(ref, { corrected_offset_seconds: "" }) }, "clear — offset was right")));
  }
  if (!validOffset(corr)) wrap.append(el("div", { class: "err" }, "scrubbed point is more than 24h off the camera clock — pick a nearer point"));
  return wrap;
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
  if (!frames.length || !track.length) { teardownMap(); wrap.append(el("div", { class: "placeholder" }, "no frames or track to scrub")); return wrap; }
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
      onScrub: (i, pt) => { const off = scrubOffset(pt, frame); if (off != null) editMany(ref, { confirmed: true, corrected_offset_seconds: off }); } });
    _mapKey = key;
  }
  setTimeout(() => _map && _map.refresh(), 0);
  return _map.el;
}
// A small right-aligned preview of the first/only selected photo, shown inside the pinned "Your
// decision" box for a GPS review item (the big map gets the rest of the panel). Null in demo mode or
// for non-photo cells; for a multi-photo run, `ref.path` is the first photo.
function decisionThumb(ref) {
  if (state.base.demo || ref.kind !== "review" || !ref.path) return null;
  const img = el("img", { class: "decision-thumb", alt: ref.path, title: ref.path.split("/").pop(),
    src: "/api/photo?path=" + encodeURIComponent(ref.path) });
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

// A GPX self-anchor offset proposal, collapsed: the consensus correction, then up to three
// "N photos → ±Xh Ym" groups (each with one named photo at its FULL by-dest path and that photo's
// corrected local time), plus a note for frames skipped (no track / track from another trip).
function offsetProposalBlock(ref, p) {
  if (p.proposal_source === "timezone_naive") {
    // No GPX anchor: the offset is derived from the destination's local time for this day, assuming the
    // camera clock tracked it (DST-aware, so summer/winter days get different offsets — §19.4).
    return el("div", { class: "pblock" }, el("h3", {}, "Proposal — derived from the local time"),
      el("div", { class: "prop-head" }, fmtOffset(p.proposed_offset_seconds),
        el("span", { class: "muted" }, ` (assuming the camera was on ${p.proposed_from_timezone} time)`)),
      el("div", { class: "hint" }, `real UTC ${p.proposed_real_utc} — confirm only if the camera really tracked local time (a camera left on home time would be wrong).`));
  }
  if (p.proposal_source !== "gpx_self_anchor") return jsonBlock("Proposal", p);
  const tz = previewTz(ref.dest)?.tz;
  const wrap = el("div", { class: "pblock" }, el("h3", {}, "Proposal — suggested clock correction"),
    el("div", { class: "prop-head" }, fmtOffset(p.proposed_offset_seconds),
      el("span", { class: "muted" }, ` (${p.confidence}; ${p.anchor_count} geotagged photo${p.anchor_count === 1 ? "" : "s"})`)));
  const groups = p.groups || [];
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
    wrap.append(el("div", { class: "prop-group" },
      el("div", { class: "prop-group-h" }, `${g.count} photo${g.count === 1 ? "" : "s"} → ${fmtOffset(g.offset_seconds)}`),
      el("div", { class: "hint" }, `e.g. ${g.representative.source_file}`),
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
  const isGpsCoord = ref && ref.file === "gps" && (ref.kind === "fallback" || ref.kind === "review");
  const isScrub = ref && ref.kind === "drift";
  if (!isGpsCoord && !isScrub) teardownMap();
  const cellKey = mapKeyFor(ref);
  if (cellKey !== _driftCellKey) { _driftFrame = 0; _driftTab = "photo"; _driftCellKey = cellKey; }  // reset frame + tab per cell
  if (!ref || !c) return p.append(el("div", { class: "empty" }, "Select a decision to edit it."));
  const multi = ref.peers && ref.peers.length > 1;
  const title = ref.kind === "offset" ? `Offset · ${c.camera_group || ref.key}`
    : ref.kind === "drift" ? `Drift · ${c.camera_group || ref.key}`
    : ref.kind === "review" ? (multi ? `GPS review · ${ref.peers.length} photos` : "GPS review item")
      : ref.kind === "fallback" ? "Folder fallback" : "Timezone";
  p.append(el("h2", {}, title), el("div", { class: "path" }, ref.path || ref.dest));
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
    el("h2", {}, title), el("div", { class: "path" }, ref.path || ref.dest), head,
    el("div", { class: "pblock" }, el("h3", {}, "Your decision"), decisionThumb(ref), controls(ref)),
    el("div", { class: "pblock eff" }, el("h3", {}, "Effective (advisory — re-run to apply)"), el("div", { class: "eff-val" }, previewEffective(ref))));
  // Scroll area, the only thing that scrolls. For a GPS coord cell the MAP comes first — directly under
  // the pinned "Your decision" box — so a paste/edit's effect (jump to full zoom) is visible without
  // scrolling; then the photo; then the proposal evidence last. Non-GPS cells just show the proposal.
  const scroll = el("div", { class: "panel-scroll" });
  if (isScrub) scroll.append(scrubBlock(ref));
  if (isGpsCoord) scroll.append(mapBlock(ref));   // the review photo is now a thumbnail in "Your decision" + a hover preview in the worklist
  if (c.proposal && ref.kind !== "drift") scroll.append(ref.kind === "offset" ? offsetProposalBlock(ref, c.proposal) : jsonBlock("Proposal", c.proposal));
  p.replaceChildren(top, scroll);
}

// --- header / save -----------------------------------------------------------
async function save() {
  if (state.base.demo || state.saving) return;
  const payload = { time: [], drift: [], gps: [] };
  for (const ref of dirtyRefs()) {
    const ud = workCell(ref).user_decision;
    payload[ref.file].push({ dest: ref.dest, kind: ref.kind, key: ref.key, path: ref.path, user_decision: ud });
  }
  state.saving = true; state.message = "saving…"; render();
  try {
    const r = await (await fetch("/api/save", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(payload) })).json();
    if (r.ok) { state.base = clone(state.work); state.message = `saved ${r.written.join(", ")} — run \`photos-cartographer geotag plan\` then reload to apply`; }
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
  save.title = a.demo ? "demo mode is read-only — run `serve <workspace>` to save" : invalid ? "fix invalid fields first" : "";
  $("#reset").disabled = dirty === 0 || busy;
  const list = $("#list"); list.replaceChildren();
  (state.view === "time" ? renderTime : state.view === "drift" ? renderDrift : renderGps)(list);
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

async function main() {
  for (const b of document.querySelectorAll("#view-toggle button")) b.addEventListener("click", () => { state.view = b.dataset.view; state.selected = null; render(); });
  $("#save").addEventListener("click", save);
  $("#reset").addEventListener("click", () => { state.work = clone(state.base); state.message = null; render(); });
  setupDivider();
  try { state.base = await (await fetch("/api/artifacts")).json(); state.work = clone(state.base); }
  catch (e) { $("#list").replaceChildren(el("div", { class: "empty" }, "Could not load /api/artifacts: " + e)); return; }
  render();
}
// Auto-start in the browser only; importing this module in Node (for the unit tests) must not run it
// (there's no document/fetch there). The named exports below expose the pure logic for those tests.
if (typeof document !== "undefined") main();

export {
  isNum, validTz, validOffset, validUtc, validLat, validLon, bothOrNeither,
  fmtOffset, camNaiveMs, dtLocalToMs, msToDtLocal, utcStrToMs, fmtLocal, fmtDT, offsetImpact,
  cellAt, cellStatus, wouldResolve, previewTz, previewFallback, refInvalid, isDirty, state,
  offsetGroups, dateRange, fmtDate, peerKeys, parseLatLon, coordText, contiguousRange,
  scrubOffset, scrubSeedIndex, mapKeyFor,
};
