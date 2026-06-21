// Console front-end. Triggers phase runs and renders the live event stream (SSE). No framework.
// The two event channels map straight to the two regions: log -> the scrolling pane, progress ->
// the latest-wins widgets. One run at a time, so the log/progress show the current/last run for
// whichever phase tab you're on. Status is cosmetic; correctness always comes from the artifacts.

const $ = (s) => document.querySelector(s);
const logEl = $("#log");
const progList = $("#prog-list");
const tasks = new Map();   // task_id -> { root, pl, fill, pn }

// Per-phase commands. 'execute' goes through the confirm gate (per-phase), never a direct run;
// 'prune-quarantine' opens its own dialog (dry-run is free, the --yes delete is confirmed).
const PHASE_CMDS = {
  prep: [["plan", "Plan", "primary"], ["dry-run", "Dry-run", ""], ["execute", "Execute", "gate"],
         ["prune-quarantine", "Prune quarantine", "prune"]],
  geotag: [["plan", "Plan", "primary"], ["execute", "Execute", "gate"], ["finalize", "Finalize", ""]],
  merge: [["init-library", "Init library", "initlib"], ["plan", "Plan", "primary"],
          ["dry-run", "Dry-run", ""], ["execute", "Execute", "gate"]],
};
// What each phase's execute actually touches — shown in the gate so the user knows the stakes.
const GATE_WARN = {
  prep: "Moves irreplaceable originals. No-clobber enforced; duplicates are quarantined, never deleted.",
  geotag: "Writes GPS/time metadata into the originals. Journalled and idempotent — safe to rerun.",
  merge: "Moves files into the permanent library and seals the workspace. No-clobber enforced.",
};
let currentPhase = "prep";
let planId = null;         // plan_id being reviewed in the gate
let gatePhase = "prep";    // the phase the open gate is for (tab could change underneath)

// --- log + progress rendering --------------------------------------------
function addLog(e) {
  const div = document.createElement("div");
  div.textContent = e.msg;
  if (e.level === "warn") div.className = "w";
  else if (e.level === "error") div.className = "e";
  const atBottom = logEl.scrollHeight - logEl.scrollTop - logEl.clientHeight < 40;
  logEl.appendChild(div);
  if (atBottom) logEl.scrollTop = logEl.scrollHeight;
}

function progRow() {
  const root = document.createElement("div");
  root.className = "prog-row";
  const pl = document.createElement("span"); pl.className = "pl";
  const track = document.createElement("span"); track.className = "track";
  const fill = document.createElement("span"); fill.className = "fill"; fill.style.width = "0%";
  track.appendChild(fill);
  const pn = document.createElement("span"); pn.className = "pn";
  root.append(pl, track, pn);
  return { root, pl, fill, pn };
}

function setIdleIfEmpty() {
  if (tasks.size === 0) progList.innerHTML = '<p class="idle">No active task.</p>';
}

function upsertProgress(e) {
  if (e.state === "finish") {
    const t = tasks.get(e.task_id);
    if (t) { t.root.remove(); tasks.delete(e.task_id); }
    setIdleIfEmpty();
    return;
  }
  let t = tasks.get(e.task_id);
  if (!t) {
    if (tasks.size === 0) progList.innerHTML = "";
    t = progRow(); tasks.set(e.task_id, t); progList.appendChild(t.root);
  }
  const pct = e.total ? (e.cur / e.total) * 100 : null;
  t.pl.textContent = e.label;
  t.fill.style.width = pct != null ? pct.toFixed(1) + "%" : "0%";
  let n = e.total != null ? `${e.cur}/${e.total}` : `${e.cur}`;
  if (pct != null) n += ` · ${pct.toFixed(1)}%`;
  if (e.detail) n += ` · ${e.detail}`;
  t.pn.textContent = n;
}

function applySnapshot(s) {
  logEl.textContent = "";
  tasks.clear();
  progList.innerHTML = "";
  (s.log || []).forEach(addLog);
  (s.progress || []).forEach(upsertProgress);
  setIdleIfEmpty();
}

const es = new EventSource("/api/events");
es.onmessage = (ev) => {
  let m;
  try { m = JSON.parse(ev.data); } catch { return; }
  if (m.kind === "snapshot") applySnapshot(m);
  else if (m.kind === "log") addLog(m);
  else if (m.kind === "progress") upsertProgress(m);
};

// --- phase tabs + actions -------------------------------------------------
function renderActions() {
  const wrap = $("#action-buttons");
  wrap.innerHTML = "";
  for (const [cmd, label, kind] of (PHASE_CMDS[currentPhase] || [])) {
    const b = document.createElement("button");
    b.className = "btn" + (kind === "primary" ? " primary" : "");
    b.textContent = label;
    b.dataset.cmd = cmd;
    b.onclick = kind === "gate" ? openGate : kind === "initlib" ? openInitLib
      : kind === "prune" ? openPrune : () => trigger(cmd);
    wrap.appendChild(b);
  }
}

function setPhase(phase) {
  if (phase === currentPhase) return;
  currentPhase = phase;
  for (const t of document.querySelectorAll("#tabs button")) t.classList.toggle("on", t.dataset.phase === phase);
  // The Edit tab is the folded-in decision editor (an iframe at /edit/), not a phase view.
  const isEdit = phase === "edit";
  $("#phase-view").hidden = isEdit;
  const frame = $("#edit-frame");
  frame.hidden = !isEdit;
  if (isEdit) {
    if (!frame.getAttribute("src")) frame.setAttribute("src", "/edit/");   // lazy-load once
    return;
  }
  renderActions();
  refreshState();
}

for (const t of document.querySelectorAll("#tabs button")) {
  if (!t.disabled) t.onclick = () => setPhase(t.dataset.phase);
}

// --- state + polling ------------------------------------------------------
let pollTimer = null;
async function refreshState() {
  let s;
  try { s = await (await fetch("/api/state")).json(); } catch { return false; }
  $("#workspace").textContent = s.workspace || "";
  const running = s.job && s.job.state === "running";
  const lock = $("#lock");
  lock.textContent = running ? `● running: ${s.job.label}` : "● idle";
  lock.style.color = running ? "var(--accent)" : "var(--muted)";

  if (s.sealed) { lock.textContent = "● sealed"; lock.style.color = "var(--muted)"; }
  else if (!running && s.lock_owner) { lock.textContent = "● locked (another run)"; lock.style.color = "var(--warn)"; }

  const ph = (s.phases && s.phases[currentPhase]) || {};
  // status chip for the current phase (plan-exists / blockers / staleness / ready)
  const ps = $("#phase-status");
  if (!ph.plan_exists) { ps.textContent = "no plan yet"; ps.className = "chip"; }
  else if (ph.blockers) { ps.textContent = `plan · ${ph.blockers} blocker(s)`; ps.className = "chip"; }
  else if (ph.stale) { ps.textContent = "plan stale — re-plan"; ps.className = "chip"; }
  else { ps.textContent = "plan ✓ ready"; ps.className = "chip ok"; }
  planId = ph.plan_id || null;

  // button enablement from the server's per-command affordance (precondition + staleness + sealed/lock)
  const acts = s.actions || {};
  for (const b of document.querySelectorAll("#action-buttons button")) {
    const act = acts[`${currentPhase}/${b.dataset.cmd}`] || { ok: !running, reason: "" };
    b.disabled = !act.ok;
    b.title = act.ok ? "" : act.reason;
  }
  return running;
}

function pollWhileRunning() {
  clearTimeout(pollTimer);
  pollTimer = setTimeout(async () => {
    const running = await refreshState();
    if (running) pollWhileRunning();
  }, 1200);
}

async function trigger(command) {
  try {
    await fetch("/api/run", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ phase: currentPhase, command }),
    });
  } catch { /* state poll will reflect reality */ }
  await refreshState();
  pollWhileRunning();
}

// --- execute confirm gate (prep) ------------------------------------------
const overlay = $("#gate-overlay");

async function openGate() {
  const phase = currentPhase;
  let s;
  try { s = await (await fetch(`/api/plan-summary?phase=${encodeURIComponent(phase)}`)).json(); } catch { return; }
  if (!s.exists || (s.blockers && s.blockers.length)) { await refreshState(); return; }
  gatePhase = phase;
  planId = s.plan_id;
  $("#gate-title").textContent = `Confirm ${phase} execute`;
  $("#gate-sum").textContent = `Plan ${s.plan_id}\n${(s.lines || []).join("\n")}`;
  $("#gate-warn").textContent = GATE_WARN[phase] || "This mutates workspace state.";
  $("#gate-go").textContent = `Execute ${s.operations} operation${s.operations === 1 ? "" : "s"}`;
  overlay.hidden = false;
}

function closeGate() { overlay.hidden = true; }

async function confirmExecute() {
  closeGate();
  try {
    await fetch("/api/run", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ phase: gatePhase, command: "execute", confirm: true, plan_id: planId }),
    });
  } catch { /* state poll reflects reality */ }
  await refreshState();
  pollWhileRunning();
}

$("#gate-cancel").onclick = closeGate;
$("#gate-go").onclick = confirmExecute;
overlay.onclick = (e) => { if (e.target === overlay) closeGate(); };

// --- init-library (optional path) -----------------------------------------
const initOverlay = $("#initlib-overlay");
function openInitLib() { $("#initlib-path").value = ""; initOverlay.hidden = false; $("#initlib-path").focus(); }
function closeInitLib() { initOverlay.hidden = true; }
async function confirmInitLib() {
  const path = $("#initlib-path").value.trim();
  closeInitLib();
  try {
    await fetch("/api/run", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ phase: "merge", command: "init-library", path: path || undefined }),
    });
  } catch { /* state poll reflects reality */ }
  await refreshState();
  pollWhileRunning();
}
$("#initlib-cancel").onclick = closeInitLib;
$("#initlib-go").onclick = confirmInitLib;
initOverlay.onclick = (e) => { if (e.target === initOverlay) closeInitLib(); };

// --- prune-quarantine (dry-run is free; the --yes delete is confirmed) -----
const pruneOverlay = $("#prune-overlay");
function openPrune() { $("#prune-ids").value = ""; $("#prune-all").checked = false; pruneOverlay.hidden = false; }
function closePrune() { pruneOverlay.hidden = true; }
function _pruneSel(deleteFlag) {
  const ids = $("#prune-ids").value.split(/[\s,]+/).filter(Boolean);
  const all = $("#prune-all").checked;
  const prune = { delete: deleteFlag };
  if (ids.length) prune.plan_ids = ids;
  if (all) prune.all = true;
  return prune;
}
async function runPrune(deleteFlag) {
  // A delete needs a selector; a dry-run lists the whole footprint with none.
  const prune = _pruneSel(deleteFlag);
  if (deleteFlag && !prune.plan_ids && !prune.all) { $("#prune-err").textContent = "select plan id(s) or 'all' to delete"; return; }
  closePrune();
  try {
    await fetch("/api/run", {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ phase: "prep", command: "prune-quarantine", confirm: deleteFlag, prune }),
    });
  } catch { /* state poll reflects reality */ }
  await refreshState();
  pollWhileRunning();
}
$("#prune-cancel").onclick = closePrune;
$("#prune-dry").onclick = () => { $("#prune-err").textContent = ""; runPrune(false); };
$("#prune-del").onclick = () => { $("#prune-err").textContent = ""; runPrune(true); };
pruneOverlay.onclick = (e) => { if (e.target === pruneOverlay) closePrune(); };

$("#clear").onclick = () => { logEl.textContent = ""; };

// Reflect external changes (a terminal re-plan, an editor save, another run finishing) without a
// page reload: a slow idle heartbeat + an immediate refetch whenever the tab regains focus.
setInterval(refreshState, 5000);
window.addEventListener("focus", refreshState);
document.addEventListener("visibilitychange", () => { if (!document.hidden) refreshState(); });

renderActions();
refreshState();
