// Decision editor. Loads the workspace's decision artifacts into a working copy, lets the human edit
// only the `user_decision` blocks (timezone / offset / fallback / review) with client-side validation,
// override/inherited/edited badges, an advisory effective-outcome preview, and Save (writes
// user_decision back via the server). GPS cells get a side-panel map picker (fixed-crosshair pick) plus
// a photo preview for review items (map.js + the server's /api/photo). The time tree shows a live,
// advisory inheritance preview (a child with no own decision shows the timezone it would inherit from
// its nearest resolved ancestor), and Re-run invokes `photos-2-time-gps run` on the server then reloads
// the regenerated authoritative artifacts (the edit → Save → Re-run → reload loop).
// Vanilla + ES modules; no build. Leaflet is vendored (global L); tiles come from OSM at runtime.

import { mapPicker } from "./map.js";

const state = { base: null, work: null, view: "time", selected: null, saving: false, running: false, message: null, runResult: null, timeChangedSinceRerun: false };

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

// --- cell access -------------------------------------------------------------
function cellAt(arts, ref) {
  if (!ref || !arts) return null;
  if (ref.file === "time") {
    const d = arts.time?.destinations?.[ref.dest]; if (!d) return null;
    return ref.kind === "timezone" ? d.destination_timezone : d.camera_group_time_decisions?.[ref.key];
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
  if (ref.kind === "fallback") return !validLat(u.fallback_lat) || !validLon(u.fallback_lon) || !bothOrNeither(u.fallback_lat, u.fallback_lon);
  return !validLat(u.manual_lat) || !validLon(u.manual_lon) || !bothOrNeither(u.manual_lat, u.manual_lon);
}
const dirtyRefs = () => allRefs().filter(isDirty);
const anyInvalid = () => allRefs().some(refInvalid);
const udSet = (u) => Object.values(u || {}).some((v) => v === true || (v !== "" && v != null && v !== false));

// --- edit + status -----------------------------------------------------------
// Time edits invalidate the GPS decisions (GPS placement is computed from resolved UTC), and GPS is
// only recomputed on a Re-run — so flag any time change to drive the GPS-view stale/lock notices below.
const touchTime = (ref) => { if (ref.file === "time") state.timeChangedSinceRerun = true; };
function edit(ref, field, value) { touchTime(ref); workCell(ref).user_decision[field] = value; render(); }
function editMany(ref, obj) { touchTime(ref); Object.assign(workCell(ref).user_decision, obj); render(); }
function resetRef(ref) { workCell(ref).user_decision = clone(baseCell(ref).user_decision); render(); }

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
// UTC epoch ms (Date.UTC), matching calibration's `real_utc_naive − camera_naive` (photos-2-time-gps).
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

// advisory effective preview (NOT authoritative — calibration recomputes on re-run)
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
    return "— (will auto/inherit on re-run, or needs input)";
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
// Mirrors calibration's rule for DISPLAY ONLY: a child timezone with no own decision would, on re-run,
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
function isSel(ref) { const s = state.selected; return s && s.file === ref.file && s.dest === ref.dest && s.kind === ref.kind && s.key === ref.key && s.path === ref.path; }
function tags(ref) {
  const c = baseCell(ref), out = [];
  if (ref.kind === "timezone") {
    const pv = previewTz(ref.dest);                       // live preview, updates as ancestors change
    if (pv && pv.source === "inherited") out.push(chip("inherited", `inherited ⟵ ${leaf(pv.from)}`));
  } else if (ref.kind === "fallback") {
    const pv = previewFallback(ref.dest);                 // live preview, updates as ancestors change
    if (pv && pv.source === "inherited") out.push(chip("inherited", `inherited ⟵ ${leaf(pv.from)}`));
  } else if (c?.proposal?.proposal_source === "inherited") {
    out.push(chip("inherited", "inherited"));
  }
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
    for (const key of Object.keys(node.dest.camera_group_time_decisions || {}).sort()) {
      const c = node.dest.camera_group_time_decisions[key];
      const e = c.effective_time_anchor; n.append(row({ file: "time", dest: node.path, kind: "offset", key }, "Offset", key, e && typeof e === "object" ? fmtOffset(e.offset_seconds) : "—"));
    }
  }
  const kids = Object.keys(node.children).sort();
  if (kids.length) { const w = el("div", { class: "kids" }); for (const k of kids) renderTreeNode(node.children[k], w); n.append(w); }
  box.append(n);
}
function renderTime(list) {
  const t = state.work.time;
  if (!t?.destinations) return list.append(el("div", { class: "empty" }, "No photos-21-time-decisions.json."));
  if (!state.base.demo && state.timeChangedSinceRerun)
    list.append(el("div", { class: "gate warn" }, "Time decisions changed — Re-run afterward so GPS is recomputed from the new times."));
  const root = buildTree(t.destinations);
  for (const k of Object.keys(root.children).sort()) renderTreeNode(root.children[k], list);
}
function renderGps(list) {
  const g = state.work.gps;
  // GPS placement is derived from each photo's resolved UTC, so the GPS phase is gated on the time
  // decisions: calibration only (re)generates photos-22 once every time decision is resolved. Make
  // that gate visible rather than showing an empty or stale GPS view.
  if (!state.base.demo && state.work.time?.requires_user_input)
    return list.append(el("div", { class: "gate" },
      el("div", { class: "gate-title" }, "GPS is waiting on the time decisions"),
      "GPS placement (interpolation / extrapolation) is computed from each photo's resolved UTC, so the GPS "
      + "decisions are generated only once every timezone and clock-offset decision is resolved. Finish them in "
      + "the Time view, then Re-run."));
  if (!g?.destinations) return list.append(el("div", { class: "empty" }, "No photos-22-gps-decisions.json."));
  if (!state.base.demo && state.timeChangedSinceRerun)
    list.append(el("div", { class: "gate warn" }, "Time decisions changed since the last calibration run — Re-run to recompute GPS. The decisions below are stale until you do."));
  for (const dest of Object.keys(g.destinations).sort()) {
    const d = g.destinations[dest], fb = d.folder_fallback, s = d.gps_decisions?.summary || {};
    list.append(el("div", { class: "group-title" }, dest,
      d.file_less ? el("span", { class: "container-tag", title: "no photos here — its fallback only seeds sub-destinations" }, "container") : null));
    const fbpv = previewFallback(dest);
    list.append(row({ file: "gps", dest, kind: "fallback" }, "Folder fallback", null,
      fb.effective_fallback ? `${fb.effective_fallback.lat}, ${fb.effective_fallback.lon}` : (fbpv ? `${fbpv.lat}, ${fbpv.lon}` : "—")));
    for (const ri of d.gps_decisions?.review_items || []) {
      const ref = { file: "gps", dest, kind: "review", path: ri.relative_path };
      list.append(el("div", { class: "row" + (isSel(ref) ? " sel" : ""), onclick: () => { state.selected = ref; render(); } },
        el("span", { class: "label" }, ri.relative_path.split("/").pop()), chip("reason", ri.reason), ...tags(ref), statusChip(ref)));
    }
    list.append(el("div", { class: "summary" }, `${s.files_total ?? 0} files — preserve ${s.preserve_native_gps ?? 0}, interp ${s.automatic_gpx_interpolation ?? 0}, extrap ${s.automatic_gpx_extrapolation ?? 0}, fallback ${s.automatic_folder_fallback ?? 0}, blocked ${s.blocked ?? 0}`));
  }
}

// --- editing controls --------------------------------------------------------
function checkbox(label, checked, onchange, disabled) {
  const cb = el("input", { type: "checkbox", disabled: disabled ? "" : null }); cb.checked = !!checked; cb.addEventListener("change", () => onchange(cb.checked));
  return el("label", { class: disabled ? "ctl-check disabled" : "ctl-check" }, cb, label);
}
function numField(label, value, onchange, invalid) {
  const inp = el("input", { type: "number", step: "any", class: invalid ? "bad" : null, value: value === "" || value == null ? "" : value });
  inp.addEventListener("change", () => onchange(inp.value === "" ? "" : Number(inp.value)));
  return el("label", { class: "ctl-field" }, el("span", {}, label), inp);
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
function offsetEditor(ref) {
  const c = workCell(ref), u = c.user_decision, p = c.proposal || {};
  const isGpx = p.proposal_source === "gpx_self_anchor";
  const camMs = isGpx && p.anchors && p.anchors[0] ? camNaiveMs(p.anchors[0].camera_source_naive_time) : null;
  const canUtc = camMs != null;
  // current offset: the stored value, or (legacy hand-edited JSON) derived from manual_real_utc
  let off = u.manual_offset_seconds;
  if ((off === "" || off == null) && u.manual_real_utc && camMs != null) {
    const m = utcStrToMs(u.manual_real_utc); if (m != null) off = Math.round((m - camMs) / 1000);
  }
  const hasOff = off !== "" && off != null, cur = Number(off) || 0, abs = Math.abs(cur);
  const selKey = `${ref.dest}|${ref.key}`;
  const mode = canUtc && state.offsetEdit?.key === selKey && state.offsetEdit.mode === "utc" ? "utc" : "offset";
  const activate = (m) => { state.offsetEdit = { key: selKey, mode: m }; state._focusOffset = m; render(); };
  const setOff = (v) => editMany(ref, { manual_offset_seconds: v, manual_real_utc: "" });

  // --- offset view: h/m/s spinner --------------------------------------------
  const bump = (secs, dir) => setOff(Math.max(-86400, Math.min(86400, cur + dir * secs)));
  const unit = (label, secs, value) => {
    const box = el("div", { class: "spin-unit", tabindex: mode === "offset" ? "0" : null,
      title: mode === "offset" ? `scroll or ↑/↓ to adjust ${label}` : "driven by real-UTC — click to edit the offset directly" },
      el("div", { class: "spin-unit-val" }, String(value).padStart(2, "0")),
      el("div", { class: "spin-unit-lbl" }, label));
    if (mode === "offset") {
      box.addEventListener("wheel", (e) => { e.preventDefault(); bump(secs, e.deltaY < 0 ? 1 : -1); }, { passive: false });
      box.addEventListener("keydown", (e) => {
        if (e.key !== "ArrowUp" && e.key !== "ArrowDown") return; e.preventDefault();
        bump(secs, e.key === "ArrowUp" ? 1 : -1);
      });
    } else box.addEventListener("click", () => activate("offset"));
    return box;
  };
  const units = el("div", { class: "spin-units" + (validOffset(off) ? "" : " bad") + (mode === "offset" ? "" : " ro") },
    el("span", { class: "spin-sign" }, cur < 0 ? "−" : "+"),
    unit("h", 3600, Math.floor(abs / 3600)), el("span", { class: "spin-colon" }, ":"),
    unit("m", 60, Math.floor(abs / 60) % 60), el("span", { class: "spin-colon" }, ":"),
    unit("s", 1, abs % 60));
  const num = el("input", { type: "number", step: "1", class: "spin-num", readonly: mode === "offset" ? null : "",
    value: hasOff ? off : "" });
  if (mode === "offset") num.addEventListener("change", () => setOff(num.value === "" ? "" : Number(num.value)));
  else num.addEventListener("focus", () => activate("offset"));
  const wrap = el("div", { class: "ctl-block" },
    el("div", { class: "ctl-field" }, el("span", {}, "Manual offset"),
      el("div", { class: "spin-wrap" }, units, num, el("button", { class: "mini", onclick: () => setOff("") }, "clear"))));
  if (!validOffset(off)) wrap.append(el("div", { class: "err" }, "offset must be a number within ±86400 s"));

  if (!canUtc) {
    wrap.append(el("div", { class: "hint" }, isGpx
      ? "no anchor frame on this proposal — set the offset directly"
      : "real-UTC entry needs a GPX self-anchor proposal — set the offset directly"));
    return wrap;
  }

  // --- real-UTC view: datetime-local picker (interpreted as UTC) --------------
  const pick = el("input", { type: "datetime-local", step: "1", class: "spin-num utc-pick", readonly: mode === "utc" ? null : "",
    title: "the true UTC time of the matched anchor frame; sets the offset = this − the frame's camera clock" });
  pick.value = hasOff ? msToDtLocal(camMs + cur * 1000) : "";
  if (mode === "utc") pick.addEventListener("change", () => setOff(pick.value === "" ? "" : Math.round((dtLocalToMs(pick.value) - camMs) / 1000)));
  else { pick.addEventListener("click", () => activate("utc")); pick.addEventListener("focus", () => activate("utc")); }
  wrap.append(el("label", { class: "ctl-field" }, el("span", {}, "Anchor real-UTC"), pick));

  // derived destination-local label (display only), or a nudge when the timezone isn't resolved yet
  if (hasOff) {
    const realMs = camMs + cur * 1000, pv = previewTz(ref.dest), loc = pv && pv.tz ? fmtLocal(realMs, pv.tz) : null;
    wrap.append(loc
      ? el("div", { class: "hint" }, `= ${loc} · ${pv.tz}${pv.source === "inherited" ? " (inherited)" : ""} — local time, derived from this destination's timezone decision`)
      : el("div", { class: "hint" }, "set this destination's timezone to see the equivalent local time"));
  }
  if (p.proposed_real_utc) wrap.append(el("div", { class: "hint" }, `GPX estimate for this anchor: ${p.proposed_real_utc}`));

  if (state._focusOffset) {
    const target = state._focusOffset === "utc" ? pick : num; state._focusOffset = null;
    queueMicrotask(() => target.focus());
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
    const hasOff = "proposed_offset_seconds" in p;
    wrap.append(checkbox(`accept proposal${hasOff ? " (" + fmtOffset(p.proposed_offset_seconds) + ")" : " — none to accept"}`, u.accept_proposal, (v) => edit(ref, "accept_proposal", v), !hasOff));
    wrap.append(offsetEditor(ref));
  } else if (ref.kind === "fallback") {
    const hasProp = p.proposal_source === "inherited";
    wrap.append(checkbox(hasProp ? `accept inherited (${p.proposed_fallback.lat}, ${p.proposed_fallback.lon})` : "accept inherited — none", u.accept_proposal, (v) => edit(ref, "accept_proposal", v), !hasProp));
    wrap.append(numField("Fallback lat", u.fallback_lat, (v) => edit(ref, "fallback_lat", v), !validLat(u.fallback_lat)));
    wrap.append(numField("Fallback lon", u.fallback_lon, (v) => edit(ref, "fallback_lon", v), !validLon(u.fallback_lon)));
    wrap.append(el("div", { class: "hint" }, "or pan the map below under the crosshair and “use map center”"));
    if (!bothOrNeither(u.fallback_lat, u.fallback_lon)) wrap.append(el("div", { class: "err" }, "set both lat and lon, or neither"));
  } else {
    wrap.append(numField("Manual lat", u.manual_lat, (v) => edit(ref, "manual_lat", v), !validLat(u.manual_lat)));
    wrap.append(numField("Manual lon", u.manual_lon, (v) => edit(ref, "manual_lon", v), !validLon(u.manual_lon)));
    wrap.append(checkbox("leave unlocated (accept no GPS)", u.accept_unlocated, (v) => edit(ref, "accept_unlocated", v)));
    wrap.append(el("div", { class: "hint" }, "or pan the map below under the crosshair and “use map center”"));
    if (!bothOrNeither(u.manual_lat, u.manual_lon)) wrap.append(el("div", { class: "err" }, "set both lat and lon, or neither"));
  }
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
const seedCenter = (ref) => currentCoord(ref) || gpsRefMarkers(ref)[0] || null;

// One Leaflet instance, kept across re-renders of the same selection (rebuilding it on each keystroke
// would reset pan/zoom). Rebuilt when the selected cell changes; torn down for non-GPS cells.
let _map = null, _mapKey = null;
const mapKeyFor = (ref) => ref ? `${ref.file}|${ref.dest}|${ref.kind}|${ref.key || ""}|${ref.path || ""}` : null;
function teardownMap() { if (_map) { _map.destroy(); _map = null; _mapKey = null; } }
function mapBlock(ref) {
  const key = mapKeyFor(ref);
  if (_mapKey !== key) {
    teardownMap();
    const [la, lo] = coordFields(ref);
    _map = mapPicker({ center: seedCenter(ref), markers: gpsRefMarkers(ref),
      onPick: (lat, lon) => editMany(ref, { [la]: lat, [lo]: lon }) });
    _mapKey = key;
  }
  _map.setCurrent(currentCoord(ref));
  setTimeout(() => _map && _map.refresh(), 0);     // recompute size after (re)attach to the DOM
  return el("div", { class: "pblock" }, el("h3", {}, "Place on map"), _map.el, _map.bar);
}
function photoBlock(ref) {
  if (state.base.demo)
    return el("div", { class: "pblock" }, el("h3", {}, "Photo"),
      el("div", { class: "placeholder" }, "no preview in demo mode (no workspace files)"));
  const img = el("img", { class: "photo-img", alt: ref.path, src: "/api/photo?path=" + encodeURIComponent(ref.path) });
  const block = el("div", { class: "pblock" }, el("h3", {}, "Photo"), img);
  img.addEventListener("error", () => { img.remove(); block.append(el("div", { class: "placeholder" }, "no embedded preview available")); });
  return block;
}

// --- side panel --------------------------------------------------------------
function jsonBlock(title, obj) { return obj === undefined ? null : el("div", { class: "pblock" }, el("h3", {}, title), el("pre", { class: "json" }, JSON.stringify(obj, null, 2))); }

// A GPX self-anchor offset proposal, collapsed: the consensus correction, then up to three
// "N photos → ±Xh Ym" groups (each with one named photo at its FULL by-dest path and that photo's
// corrected local time), plus a note for frames skipped (no track / track from another trip).
function offsetProposalBlock(ref, p) {
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
  const ref = state.selected, c = workCell(ref);
  const isGpsCoord = ref && ref.file === "gps" && (ref.kind === "fallback" || ref.kind === "review");
  if (!isGpsCoord) teardownMap();
  if (!ref || !c) return p.append(el("div", { class: "empty" }, "Select a decision to edit it."));
  const title = ref.kind === "offset" ? `Offset · ${ref.key}` : ref.kind === "review" ? "GPS review item" : ref.kind === "fallback" ? "Folder fallback" : "Timezone";
  p.append(el("h2", {}, title), el("div", { class: "path" }, ref.path || ref.dest));
  const head = el("div", { class: "pblock" }, ...(statusChip(ref) ? [statusChip(ref)] : []), ...tags(ref));
  if (isDirty(ref)) head.append(el("button", { class: "mini", onclick: () => resetRef(ref) }, "reset"));
  p.append(head);
  if (c.proposal) p.append(ref.kind === "offset" ? offsetProposalBlock(ref, c.proposal) : jsonBlock("Proposal", c.proposal));
  if (ref.kind === "review") p.append(photoBlock(ref));
  if (isGpsCoord) p.append(mapBlock(ref));
  p.append(el("div", { class: "pblock" }, el("h3", {}, "Your decision"), controls(ref)));
  p.append(el("div", { class: "pblock eff" }, el("h3", {}, "Effective (advisory — re-run to apply)"), el("div", { class: "eff-val" }, previewEffective(ref))));
}

// --- header / save -----------------------------------------------------------
async function save() {
  if (state.base.demo || state.saving) return;
  const payload = { time: [], gps: [] };
  for (const ref of dirtyRefs()) {
    const ud = workCell(ref).user_decision;
    payload[ref.file].push({ dest: ref.dest, kind: ref.kind, key: ref.key, path: ref.path, user_decision: ud });
  }
  state.saving = true; state.message = "saving…"; render();
  try {
    const r = await (await fetch("/api/save", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(payload) })).json();
    if (r.ok) { state.base = clone(state.work); state.message = `saved ${r.written.join(", ")} — re-run calibration to apply`; }
    else state.message = "save failed: " + (r.error || "unknown");
  } catch (e) { state.message = "save failed: " + e; }
  state.saving = false; render();
}

// Re-run calibration: `photos-2-time-gps run` regenerates the authoritative artifacts from the SAVED
// decisions, so we require a clean (saved, valid) state first, then reload what calibration wrote.
async function rerun() {
  if (state.base.demo || state.saving || state.running) return;
  state.running = true; state.runResult = null; state.message = "re-running calibration…"; render();
  try {
    const r = await (await fetch("/api/rerun", { method: "POST" })).json();
    state.runResult = r;
    if (r.ok) {
      state.base = await (await fetch("/api/artifacts")).json();
      state.work = clone(state.base);
      state.selected = null;
      state.timeChangedSinceRerun = false;   // GPS was just recomputed against the current time decisions
      state.message = "re-ran calibration — artifacts reloaded";
    } else {
      state.message = r.error ? `re-run failed: ${r.error}` : `re-run reported blockers (exit ${r.returncode})`;
    }
  } catch (e) { state.message = "re-run failed: " + e; state.runResult = { ok: false, error: String(e) }; }
  state.running = false; render();
}

function renderRunlog() {
  const box = $("#runlog"), r = state.runResult;
  if (!r) { box.hidden = true; box.replaceChildren(); return; }
  box.hidden = false; box.className = "runlog " + (r.ok ? "ok" : "bad");
  const out = [r.error, r.stderr, r.stdout].filter(Boolean).join("\n").trim();
  box.replaceChildren(
    el("button", { class: "mini close", onclick: () => { state.runResult = null; render(); } }, "✕"),
    el("strong", {}, r.ok ? "calibration re-run OK" : `calibration did not complete${r.returncode != null ? ` (exit ${r.returncode})` : ""}`),
    out ? el("pre", { class: "runlog-out" }, out) : null);
}

function render() {
  const a = state.base;
  $("#workspace").textContent = a.demo ? "demo mode — example fixtures (read-only)" : a.workspace;
  for (const b of document.querySelectorAll("#view-toggle button")) b.classList.toggle("on", b.dataset.view === state.view);
  const dirty = dirtyRefs().length, invalid = anyInvalid(), busy = state.saving || state.running;
  $("#todo").textContent = dirty ? `${dirty} unsaved${invalid ? " · ✗ invalid" : ""}` : (state.message || "no changes");
  const save = $("#save"); save.disabled = a.demo || busy || dirty === 0 || invalid;
  save.title = a.demo ? "demo mode is read-only — run `serve <workspace>` to save" : invalid ? "fix invalid fields first" : "";
  // Re-run needs calibration's dependencies present on THIS host: the pipeline script (the bundle
  // doesn't embed it) and the configured gpx_root (a mount that may live only on the workspace's own
  // host). Re-running without them would fail or silently wipe GPX-derived decisions — so gate on it.
  const depsMissing = !a.demo && a.environment && !a.environment.deps_ok;
  const rerunBtn = $("#rerun"); rerunBtn.disabled = a.demo || busy || dirty > 0 || invalid || depsMissing;
  rerunBtn.textContent = state.running ? "running…" : "Re-run";
  rerunBtn.title = a.demo ? "demo mode — no workspace to calibrate"
    : depsMissing ? `can't re-run on this machine — missing: ${a.environment.missing.join(", ")}. Run the editor on the host with the pipeline and its data.`
    : dirty > 0 ? "save your changes first, then re-run"
    : invalid ? "fix invalid fields first" : "run `photos-2-time-gps run` and reload the result";
  $("#reset").disabled = dirty === 0 || busy;
  renderRunlog();
  const list = $("#list"); list.replaceChildren();
  (state.view === "time" ? renderTime : renderGps)(list);
  renderPanel();
}

async function main() {
  for (const b of document.querySelectorAll("#view-toggle button")) b.addEventListener("click", () => { state.view = b.dataset.view; state.selected = null; render(); });
  $("#save").addEventListener("click", save);
  $("#rerun").addEventListener("click", rerun);
  $("#reset").addEventListener("click", () => { state.work = clone(state.base); state.message = null; render(); });
  try { state.base = await (await fetch("/api/artifacts")).json(); state.work = clone(state.base); }
  catch (e) { $("#list").replaceChildren(el("div", { class: "empty" }, "Could not load /api/artifacts: " + e)); return; }
  render();
}
main();
