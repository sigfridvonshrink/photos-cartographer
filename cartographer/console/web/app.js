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
async function refreshState() {
  let s;
  try { s = await (await fetch("/api/state")).json(); } catch { return false; }
  $("#workspace").textContent = s.workspace || "";
  const running = s.job && s.job.state === "running";
  const lock = $("#lock");
  lock.textContent = running ? `● running: ${s.job.label}` : "● idle";
  lock.style.color = running ? "var(--accent)" : "var(--muted)";
  $("#btn-plan").disabled = running;
  $("#btn-dry").disabled = running;
  const ps = $("#phase-status");
  if (s.phases && s.phases.prep && s.phases.prep.plan_exists) { ps.textContent = "plan ✓"; ps.className = "chip ok"; }
  else { ps.textContent = "no plan yet"; ps.className = "chip"; }
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
