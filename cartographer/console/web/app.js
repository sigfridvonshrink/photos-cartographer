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
let gatePlanId = null;     // plan_id of the plan the open gate shows — set only by openGate, never by a state poll
let gatePhase = "prep";    // the phase the open gate is for (tab could change underneath)
let currentJobLabel = null;// label of the running job (e.g. "prep execute"), for the Stop confirm
let prevRunning = false;   // last poll's running flag — to detect a job just finishing

// Reload the folded-in decision editor (Edit tab) so it re-reads the latest decision JSONs. Called
// when a geotag plan finishes — the plan it just wrote is what the editor edits. No-op until the
// iframe has been opened at least once (it loads fresh on first switch anyway). Never over unsaved
// edits: reloading would discard them silently, and they cannot be saved over the regenerated records
// anyway (the save is refused as changed since loaded) — so the console says so (#edit-stale-banner)
// and leaves the reload to the user. The editor page (same origin) answers window.editorHasUnsavedEdits().
function reloadEditFrame() {
  const frame = $("#edit-frame");
  if (!frame.getAttribute("src")) return;
  let unsaved = false;
  try { unsaved = !!(frame.contentWindow.editorHasUnsavedEdits && frame.contentWindow.editorHasUnsavedEdits()); }
  catch { /* not readable (not loaded yet): nothing to keep */ }
  if (unsaved) { $("#edit-stale-banner").hidden = false; return; }
  forceReloadEditFrame();
}
function forceReloadEditFrame() {
  const frame = $("#edit-frame");
  $("#edit-stale-banner").hidden = true;
  try { frame.contentWindow.location.reload(); }
  catch { frame.setAttribute("src", "/edit/"); }   // cross-origin guard / fallback
}
$("#edit-reload").onclick = forceReloadEditFrame;   // the user's own reload, unsaved edits and all
let jobsSeeded = false;    // seed the Jobs (-j) box from the server default exactly once
let cpuCount = 256;        // server machine's CPU count = the Jobs box upper bound (set from state)

// Current Jobs (-j) value to attach to a run, or undefined to let the phase use its own default.
function jobsValue() {
  const v = parseInt($("#jobs-input").value, 10);
  return Number.isFinite(v) && v >= 1 ? v : undefined;
}

// Mouse wheel over the Jobs box nudges the count, bounded [1, CPU count]. preventDefault so the page
// doesn't scroll while adjusting.
$(".jobs-box").addEventListener("wheel", (e) => {
  e.preventDefault();
  const input = $("#jobs-input");
  const cur = parseInt(input.value, 10) || cpuCount;
  const next = Math.min(cpuCount, Math.max(1, cur + (e.deltaY < 0 ? 1 : -1)));
  input.value = next;
}, { passive: false });

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
  if (s.changes) showChanges(s.changes);       // a stop on changes is offered until the next run starts
}

// --- live connection + server-down detection ------------------------------
// EventSource silently auto-reconnects, so a stopped server would otherwise look like a frozen page.
// Surface it: on error we start a short grace timer (ride out transient blips / tunnel hiccups); if the
// stream hasn't reopened by then, show the "server connection lost" dialog with Retry / Close.
let downTimer = null;
function showDown() { $("#down-overlay").hidden = false; }
function hideDown() { $("#down-overlay").hidden = true; }
$("#down-retry").onclick = () => location.reload();
$("#down-close").onclick = () => { window.close(); hideDown(); /* if close is blocked, just dismiss */ };

const es = new EventSource("/api/events");
es.onopen = () => { clearTimeout(downTimer); downTimer = null; hideDown(); };
es.onerror = () => {
  // readyState CLOSED = terminal; CONNECTING = auto-retrying. Either way, confirm with a grace window.
  if (downTimer === null) downTimer = setTimeout(showDown, 4000);
};
es.onmessage = (ev) => {
  let m;
  try { m = JSON.parse(ev.data); } catch { return; }
  if (m.kind === "snapshot") applySnapshot(m);
  else if (m.kind === "log") addLog(m);
  else if (m.kind === "progress") upsertProgress(m);
  else if (m.kind === "changes") showChanges(m);
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
      : kind === "prune" ? openPrune
      : (currentPhase === "prep" && cmd === "plan") ? prepPlan : () => trigger(cmd);
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
  // Seed the Jobs (-j) box once from the server's default (cpu_count-1); never clobber a user edit.
  // Record the CPU count as the upper bound (input max + wheel clamp).
  if (s.cpu_count) { cpuCount = s.cpu_count; $("#jobs-input").max = cpuCount; }
  if (!jobsSeeded && s.default_jobs) { $("#jobs-input").value = s.default_jobs; jobsSeeded = true; }
  // Show the "not initialized" banner only for a TRULY fresh workspace: no guard AND no prep plan yet.
  // Prep plan doesn't write the guard (execute does), so once a plan exists the banner would be stale.
  const planned = !!(s.phases && s.phases.prep && s.phases.prep.plan_exists);
  $("#init-banner").hidden = !(s.initialized === false && !planned);
  const running = s.job && s.job.state === "running";
  // A geotag plan just finished → its new decision JSONs are what the Edit tab reads; reload the iframe
  // so it isn't stale (closes the edit → re-plan → reload loop when re-planning from the console).
  if (prevRunning && !running && s.job && s.job.label === "geotag plan"
      && (s.job.state === "done" || s.job.state === "failed")) {   // blockers still write decisions to edit
    reloadEditFrame();
  }
  prevRunning = running;
  currentJobLabel = (s.job && s.job.label) || null;
  $("#stop-btn").hidden = !running;                      // Stop is offered only while a job runs
  const lock = $("#lock");
  lock.textContent = running ? `● running: ${s.job.label}`
    : (s.job && s.job.state === "cancelled") ? `● cancelled: ${s.job.label}` : "● idle";
  lock.style.color = running ? "var(--accent)" : "var(--muted)";

  if (s.sealed) { lock.textContent = "● sealed"; lock.style.color = "var(--muted)"; }
  else if (!running && s.lock_owner) { lock.textContent = "● locked (another run)"; lock.style.color = "var(--warn)"; }

  zoneQuestion = s.zone_table || null;
  const ph = (s.phases && s.phases[currentPhase]) || {};
  // status chip for the current phase (plan-exists / blockers / staleness / ready)
  const ps = $("#phase-status");
  if (!ph.plan_exists) { ps.textContent = "no plan yet"; ps.className = "chip"; }
  else if (ph.blockers) { ps.textContent = `plan · ${ph.blockers} blocker(s)`; ps.className = "chip"; }
  else if (ph.stale) { ps.textContent = "plan stale — re-plan"; ps.className = "chip"; }
  else { ps.textContent = "plan ✓ ready"; ps.className = "chip ok"; }

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

async function stopRun() {
  // Stop = interrupt the running job (Ctrl-C equivalent). A mutating execute is confirmed first; the
  // run is journalled/idempotent so an interrupt leaves nothing partially applied — safe to rerun.
  const isExec = (currentJobLabel || "").endsWith("execute");
  if (isExec && !confirm(
        "Interrupt this execute? It mutates originals, but the run is journalled and resumable — "
        + "nothing is left partially applied, and you can rerun to finish.")) return;
  let res = null;
  try {
    res = await fetch("/api/cancel", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ confirm: isExec }),
    });
  } catch { /* state poll will reflect reality */ }
  await logRefusal(res, "stop");
  await refreshState();
  pollWhileRunning();
}
$("#stop-btn").onclick = stopRun;

// A request the server refused (409/400/403 with its error: a gate's stale or changed plan, a blocker, the prune
// guard, a bad accept code, a run already in progress) is said in the log pane, as the CLI says why it stops — never
// dropped, the buttons' state after the next poll left as the only trace. Nothing is decided here: the refusal holds.
async function logRefusal(res, what) {
  if (!res || res.ok) return;
  let why = `HTTP ${res.status}`;
  try { why = (await res.json()).error || why; } catch { /* no JSON body: the status says it */ }
  addLog({ level: "error", msg: `${what} refused: ${why}` });
}

// Start a run. The body is remembered per command, so that "Accept these" (below) sends a checking command's run
// again — an execute's confirmation and reviewed plan id included — with the code its stop printed.
const lastRun = {};        // "phase/command" -> the body of its last run
async function postRun(body) {
  lastRun[`${body.phase}/${body.command}`] = body;
  hideChanges();
  let res = null;
  try {
    res = await fetch("/api/run", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    });
  } catch { /* state poll will reflect reality */ }
  await logRefusal(res, `${body.phase} ${body.command}`);
  await refreshState();
  pollWhileRunning();
}

async function trigger(command) {
  await postRun({ phase: currentPhase, command, jobs: jobsValue() });
}

// --- prep plan: the question of the table of countries ----------------------
// Where the host's zone database has no table of countries and the workspace has not answered, prep plan asks before
// downloading one; the console asks the same question here and sends the answer with the run — the CLI's
// `--download-zone-table` (BLD-zone_table_question; docs/design/decisions.md). Cancel runs nothing.
let zoneQuestion = null;   // { question } while the workspace has it unanswered, from the last state poll
const zoneOverlay = $("#zone-overlay");
async function prepPlan() {
  await refreshState();
  if (!zoneQuestion) return trigger("plan");
  $("#zone-question").textContent = zoneQuestion.question;
  zoneOverlay.hidden = false;
}
function closeZone() { zoneOverlay.hidden = true; }
async function answerZone(answer) {
  closeZone();
  await postRun({ phase: "prep", command: "plan", zone_table: answer, jobs: jobsValue() });
}
$("#zone-cancel").onclick = closeZone;
$("#zone-no").onclick = () => answerZone("no");
$("#zone-yes").onclick = () => answerZone("yes");
zoneOverlay.onclick = (e) => { if (e.target === zoneOverlay) closeZone(); };

// --- a run stopped on changes to the workspace -----------------------------
// Every checking command first compares the workspace with the state the last execution left it in, and stops on a
// change nobody is expected to make (RUL-unexpected_change_stops), printing the list and the code that accepts it.
// The console shows the same list, and "Accept these" sends that code through the same command — the phase's own
// check accepts exactly the list it printed (docs/design/decisions.md). Nothing is decided here.
const changesOverlay = $("#changes-overlay");
let pendingChanges = null;   // the stop's event: { phase, command, code, lines }
function showChanges(m) {
  pendingChanges = m;
  $("#changes-title").textContent = `${m.phase} ${m.command} stopped: the workspace is not as the last run left it`;
  $("#changes-list").textContent = (m.lines || []).join("\n");
  $("#changes-cmd").textContent = `Accept these runs: photos-cartographer ${m.phase} ${m.command} --accept-changes ${m.code}`;
  changesOverlay.hidden = false;
}
function hideChanges() { pendingChanges = null; changesOverlay.hidden = true; }
async function acceptChanges() {
  const m = pendingChanges;
  if (!m) return;
  const prev = lastRun[`${m.phase}/${m.command}`];
  if (!prev && m.command === "execute") {
    // No execute remembered by this page (reloaded, or another tab): its confirmation was never given here, so the
    // execute gate opens on the saved plan, the code attached — never a confirmation made up for it.
    hideChanges();
    return openGate(m.phase, m.code);
  }
  await postRun({ ...(prev || { phase: m.phase, command: m.command, jobs: jobsValue() }), accept_changes: m.code });
}
$("#changes-close").onclick = hideChanges;
$("#changes-accept").onclick = acceptChanges;

// --- execute confirm gate (prep) ------------------------------------------
const overlay = $("#gate-overlay");

// `accept`: the code of a stop on changes to the workspace, sent with the execute once confirmed ("Accept these" with
// no execute remembered by this page, above); none from the Execute button.
let gateAccept = null;
async function openGate(phase = currentPhase, accept = null) {
  if (typeof phase !== "string") phase = currentPhase;    // opened by the Execute button: its click event
  let s;
  try { s = await (await fetch(`/api/plan-summary?phase=${encodeURIComponent(phase)}`)).json(); } catch { return; }
  // A plan the server would refuse to execute opens no gate, and the log says why (as logRefusal does for a refused
  // request): none saved, a blocker, or stale against what it was made from.
  const why = !s.exists ? "no saved plan — run plan first"
    : (s.blockers && s.blockers.length) ? `the plan has ${s.blockers.length} blocker(s): ${s.blockers[0]}`
    : (s.stale && s.stale.length) ? `the plan is stale (${s.stale[0]}) — plan again`
    : null;
  if (why) {
    addLog({ level: "error", msg: `${phase} execute: ${why}` });
    await refreshState();
    return;
  }
  gatePhase = phase;
  gateAccept = accept;
  // The id of the plan this gate shows, sent with the confirmation as the plan reviewed. Kept apart from the state
  // polls (heartbeat, focus, visibility), which run while the gate is open: a plan made again in a terminal meanwhile
  // must meet the server's "plan changed since you reviewed it" refusal, never be executed under the old summary.
  gatePlanId = s.plan_id;
  $("#gate-title").textContent = `Confirm ${phase} execute` + (accept ? ", accepting the listed changes" : "");
  $("#gate-sum").textContent = `Plan ${s.plan_id}\n${(s.lines || []).join("\n")}`;
  $("#gate-warn").textContent = GATE_WARN[phase] || "This mutates workspace state.";
  $("#gate-go").textContent = `Execute ${s.operations} operation${s.operations === 1 ? "" : "s"}`;
  overlay.hidden = false;
}

function closeGate() { overlay.hidden = true; }

async function confirmExecute() {
  closeGate();
  await postRun({ phase: gatePhase, command: "execute", confirm: true, plan_id: gatePlanId, jobs: jobsValue(),
                  ...(gateAccept ? { accept_changes: gateAccept } : {}) });
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
  await postRun({ phase: "merge", command: "init-library", path: path || undefined, jobs: jobsValue() });
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
  await postRun({ phase: "prep", command: "prune-quarantine", confirm: deleteFlag, prune, jobs: jobsValue() });
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
