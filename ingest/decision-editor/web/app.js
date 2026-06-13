// Decision editor — skeleton SPA (read-only). Loads the workspace's decision artifacts and renders
// both views (time tree, GPS worklist) with a master-detail side panel. Editing, the map/photo panel,
// save, and re-run land in later phases (see design-notes.md). Vanilla + ES modules; no build.

const state = { artifacts: null, view: "time", selected: null };

const $ = (sel) => document.querySelector(sel);
function el(tag, attrs = {}, ...kids) {
  const n = document.createElement(tag);
  for (const [k, v] of Object.entries(attrs)) {
    if (k === "class") n.className = v;
    else if (k === "onclick") n.addEventListener("click", v);
    else if (v != null) n.setAttribute(k, v);
  }
  for (const c of kids.flat()) if (c != null) n.append(c.nodeType ? c : document.createTextNode(c));
  return n;
}

// --- cell status -> chip -----------------------------------------------------
function cellStatus(cell) {
  if (!cell) return null;
  if (cell.requires_user_input) return ["needs", "needs input"];
  if (cell.stale_user_decision) return ["stale", "stale — re-decide"];
  if (cell.decision_mode === "auto_resolved") return ["auto", "auto"];
  return ["ok", "resolved"];
}
function chip(kind, text) { return el("span", { class: `chip ${kind}` }, text); }
function statusChip(cell) { const s = cellStatus(cell); return s ? chip(s[0], s[1]) : null; }

function offsetEffective(cell) {
  const e = cell.effective_time_anchor;
  return e && typeof e === "object" ? `${e.offset_seconds >= 0 ? "+" : ""}${e.offset_seconds}s (${e.source})` : "—";
}

// --- selection ---------------------------------------------------------------
function select(ref) { state.selected = ref; render(); }
function isSel(ref) {
  const s = state.selected;
  return s && s.file === ref.file && s.dest === ref.dest && s.kind === ref.kind
    && s.key === ref.key && s.path === ref.path;
}
function getCell(ref) {
  const a = state.artifacts;
  if (!ref) return null;
  if (ref.file === "time") {
    const d = a.time?.destinations?.[ref.dest]; if (!d) return null;
    return ref.kind === "timezone" ? d.destination_timezone : d.camera_group_time_decisions?.[ref.key];
  }
  const d = a.gps?.destinations?.[ref.dest]; if (!d) return null;
  if (ref.kind === "fallback") return d.folder_fallback;
  return (d.gps_decisions?.review_items || []).find((r) => r.relative_path === ref.path);
}

function row(ref, label, sub, cell, effText) {
  const r = el("div", { class: "row" + (isSel(ref) ? " sel" : ""), onclick: () => select(ref) },
    el("span", { class: "label" }, label, sub ? el("span", { class: "sub" }, "  " + sub) : null),
    effText ? el("span", { class: "eff" }, effText) : null,
    statusChip(cell));
  return r;
}

// --- time view (recursive destination tree) ---------------------------------
function buildTree(dests) {
  const root = { seg: "", path: "", children: {}, dest: null };
  for (const path of Object.keys(dests).sort()) {
    let node = root, acc = "";
    for (const s of path.split("/")) { acc = acc ? acc + "/" + s : s;
      node.children[s] = node.children[s] || { seg: s, path: acc, children: {}, dest: null }; node = node.children[s]; }
    node.dest = dests[path];
  }
  return root;
}
function renderTreeNode(node) {
  const box = el("div", { class: "node" });
  if (node.dest) {
    box.append(el("div", { class: "dest" }, node.seg || node.path || "(root)"));
    box.append(row({ file: "time", dest: node.path, kind: "timezone" }, "Timezone", null,
      node.dest.destination_timezone, node.dest.destination_timezone.effective_iana_timezone || "—"));
    for (const key of Object.keys(node.dest.camera_group_time_decisions || {}).sort()) {
      const c = node.dest.camera_group_time_decisions[key];
      box.append(row({ file: "time", dest: node.path, kind: "offset", key }, "Offset", key, c, offsetEffective(c)));
    }
  }
  const kids = Object.keys(node.children).sort();
  if (kids.length) { const wrap = el("div", { class: "kids" }); for (const k of kids) wrap.append(renderTreeNode(node.children[k])); box.append(wrap); }
  return box;
}
function renderTime(listEl) {
  const t = state.artifacts.time;
  if (!t || !t.destinations) return listEl.append(el("div", { class: "empty" }, "No photos-21-time-decisions.json."));
  const root = buildTree(t.destinations);
  for (const k of Object.keys(root.children).sort()) listEl.append(renderTreeNode(root.children[k]));
}

// --- gps view (worklist) -----------------------------------------------------
function renderGps(listEl) {
  const g = state.artifacts.gps;
  if (!g || !g.destinations) return listEl.append(el("div", { class: "empty" }, "No photos-22-gps-decisions.json."));
  for (const dest of Object.keys(g.destinations).sort()) {
    const d = g.destinations[dest];
    const reviews = d.gps_decisions?.review_items || [];
    const fb = d.folder_fallback;
    listEl.append(el("div", { class: "group-title" }, dest));
    listEl.append(row({ file: "gps", dest, kind: "fallback" }, "Folder fallback", null, fb,
      fb.effective_fallback ? `${fb.effective_fallback.lat}, ${fb.effective_fallback.lon}` : "—"));
    for (const ri of reviews) {
      const base = ri.relative_path.split("/").pop();
      const r = el("div", { class: "row" + (isSel({ file: "gps", dest, kind: "review", path: ri.relative_path }) ? " sel" : ""),
        onclick: () => select({ file: "gps", dest, kind: "review", path: ri.relative_path }) },
        el("span", { class: "label" }, base, el("span", { class: "sub" }, "  ")),
        chip("reason", ri.reason), statusChip(ri));
      listEl.append(r);
    }
    const s = d.gps_decisions?.summary || {};
    listEl.append(el("div", { class: "summary" },
      `${s.files_total ?? 0} files — preserve ${s.preserve_native_gps ?? 0}, interp ${s.automatic_gpx_interpolation ?? 0}, `
      + `extrap ${s.automatic_gpx_extrapolation ?? 0}, fallback ${s.automatic_folder_fallback ?? 0}, blocked ${s.blocked ?? 0}`));
  }
}

// --- side panel (read-only detail) ------------------------------------------
function jsonBlock(title, obj) {
  if (obj === undefined) return null;
  return el("div", { class: "pblock" }, el("h3", {}, title), el("pre", { class: "json" }, JSON.stringify(obj, null, 2)));
}
function renderPanel() {
  const p = $("#panel"); p.replaceChildren();
  const ref = state.selected, cell = getCell(ref);
  if (!ref || !cell) return p.append(el("div", { class: "empty" }, "Select a decision to inspect it."));
  const title = ref.kind === "offset" ? `Offset · ${ref.key}`
    : ref.kind === "review" ? "GPS review item" : ref.kind === "fallback" ? "Folder fallback" : "Timezone";
  p.append(el("h2", {}, title));
  p.append(el("div", { class: "path" }, ref.path || ref.dest));
  const s = cellStatus(cell); if (s) p.append(el("div", { class: "pblock" }, chip(s[0], s[1])));
  p.append(jsonBlock("Proposal", cell.proposal));
  p.append(jsonBlock("Your decision (user_decision)", cell.user_decision));
  p.append(jsonBlock("Effective", cell.effective_time_anchor ?? cell.effective_iana_timezone ?? cell.effective_fallback));
  p.append(el("div", { class: "pblock" }, el("span", { class: "placeholder" },
    "Editing controls (timezone select, offset wheel-spinner, map + photo) arrive in a later phase.")));
}

// --- todo + shell ------------------------------------------------------------
function todoCount() {
  const a = state.artifacts; let n = 0;
  if (state.view === "time" && a.time?.destinations) {
    for (const d of Object.values(a.time.destinations)) {
      if (d.destination_timezone?.requires_user_input) n++;
      for (const c of Object.values(d.camera_group_time_decisions || {})) if (c.requires_user_input) n++;
    }
  } else if (a.gps?.destinations) {
    for (const d of Object.values(a.gps.destinations))
      for (const ri of d.gps_decisions?.review_items || []) if (ri.requires_user_input) n++;
  }
  return n;
}
function render() {
  const a = state.artifacts;
  $("#workspace").textContent = a.demo ? "demo mode — example fixtures" : a.workspace;
  for (const b of document.querySelectorAll("#view-toggle button")) b.classList.toggle("on", b.dataset.view === state.view);
  const n = todoCount();
  $("#todo").textContent = n ? `⚠ ${n} to-do` : "all resolved";
  const list = $("#list"); list.replaceChildren();
  (state.view === "time" ? renderTime : renderGps)(list);
  renderPanel();
}

async function main() {
  for (const b of document.querySelectorAll("#view-toggle button"))
    b.addEventListener("click", () => { state.view = b.dataset.view; state.selected = null; render(); });
  try {
    state.artifacts = await (await fetch("/api/artifacts")).json();
  } catch (e) {
    $("#list").replaceChildren(el("div", { class: "empty" }, "Could not load /api/artifacts: " + e));
    return;
  }
  render();
}
main();
