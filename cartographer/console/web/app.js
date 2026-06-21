// Console front-end. Triggers prep runs and renders the live event stream (SSE). No framework.
// The two event channels map straight to the two regions: log -> the scrolling pane, progress ->
// the latest-wins widgets. Status is cosmetic; correctness always comes from the artifacts.

const $ = (s) => document.querySelector(s);
const logEl = $("#log");
const progList = $("#prog-list");
const tasks = new Map();   // task_id -> { root, pl, fill, pn }

function addLog(e) {
  const div = document.createElement("div");
  div.textContent = e.msg;
  if (e.level === "warn") div.className = "w";
  else if (e.level === "error") div.className = "e";
  const atBottom = logEl.scrollHeight - logEl.scrollTop - logEl.clientHeight < 40;
  logEl.appendChild(div);
  if (atBottom) logEl.scrollTop = logEl.scrollHeight;   // follow the tail unless the user scrolled up
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

let pollTimer = null;
let planId = null;          // plan_id the user is reviewing in the gate
async function refreshState() {
  let s;
  try { s = await (await fetch("/api/state")).json(); } catch { return false; }
  $("#workspace").textContent = s.workspace || "";
  const running = s.job && s.job.state === "running";
  const lock = $("#lock");
  lock.textContent = running ? `● running: ${s.job.label}` : "● idle";
  lock.style.color = running ? "var(--accent)" : "var(--muted)";
  const prep = (s.phases && s.phases.prep) || {};
  $("#btn-plan").disabled = running;
  $("#btn-dry").disabled = running;
  // Execute is enabled only when a parseable, blocker-free plan exists and nothing is running.
  $("#btn-exec").disabled = running || !prep.executable;
  planId = prep.plan_id || null;
  const ps = $("#phase-status");
  if (!prep.plan_exists) { ps.textContent = "no plan yet"; ps.className = "chip"; }
  else if (prep.blockers) { ps.textContent = `plan · ${prep.blockers} blocker(s)`; ps.className = "chip"; }
  else { ps.textContent = "plan ✓ ready"; ps.className = "chip ok"; }
  return running;
}

// --- execute confirm gate -------------------------------------------------
const overlay = $("#gate-overlay");

async function openGate() {
  let s;
  try { s = await (await fetch("/api/plan-summary")).json(); } catch { return; }
  if (!s.exists || (s.blockers && s.blockers.length)) { await refreshState(); return; }
  const ops = Object.entries(s.op_counts || {}).sort().map(([t, n]) => `${t} ${n}`).join(" · ") || "none";
  $("#gate-sum").textContent =
    `Plan ${s.plan_id} — ${s.operations} operation(s):\n  ${ops}\n  ` +
    `no-op / already-correct ${s.no_op} · warnings ${s.warnings} · blockers 0`;
  $("#gate-go").textContent = `Execute ${s.operations} operation${s.operations === 1 ? "" : "s"}`;
  planId = s.plan_id;
  overlay.hidden = false;
}

function closeGate() { overlay.hidden = true; }

async function confirmExecute() {
  closeGate();
  try {
    await fetch("/api/run", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ phase: "prep", command: "execute", confirm: true, plan_id: planId }),
    });
  } catch { /* state poll reflects reality */ }
  await refreshState();
  pollWhileRunning();
}

$("#btn-exec").onclick = openGate;
$("#gate-cancel").onclick = closeGate;
$("#gate-go").onclick = confirmExecute;
overlay.onclick = (e) => { if (e.target === overlay) closeGate(); };   // click backdrop to cancel

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
      body: JSON.stringify({ phase: "prep", command }),
    });
  } catch { /* ignore; state poll will reflect reality */ }
  await refreshState();
  pollWhileRunning();
}

$("#btn-plan").onclick = () => trigger("plan");
$("#btn-dry").onclick = () => trigger("dry-run");
$("#clear").onclick = () => { logEl.textContent = ""; };

refreshState();
