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

// Runs the console's "Accept these" and execute-gate code (cartographer/console/web/app.js, from its section on a run
// stopped on changes to the one on init-library) in a sandbox, the page's DOM and requests stood in for, and prints
// what each scenario sent as JSON. Driven by tests/test_console_server.py: node console_accept_harness.js <app.js>.
// The gate scenarios also run the page's own state poll (`refreshState`), sending of a run (`postRun`) and refusal
// logging (`logRefusal`), taken from app.js by name.
const fs = require("fs");
const vm = require("vm");

const src = fs.readFileSync(process.argv[2], "utf8");
const from = src.indexOf("// --- a run stopped on changes to the workspace");
const to = src.indexOf("// --- init-library");
if (from < 0 || to < from) throw new Error("app.js sections not found");

// A top-level function of app.js, by name: from its declaration to the first closing brace at the start of a line.
function fnSrc(name) {
  const m = new RegExp(`^(async )?function ${name}\\(`, "m").exec(src);
  if (!m) throw new Error(`function ${name} not found in app.js`);
  return src.slice(m.index, src.indexOf("\n}\n", m.index) + 3);
}

function element() {
  return { hidden: true, textContent: "", onclick: null, value: "", style: {}, max: 0 };
}

function sandbox(lastRun) {
  const els = {};
  const posted = [];
  const ctx = {
    $: (sel) => els[sel] || (els[sel] = element()),
    lastRun, posted,
    postRun: async (body) => { posted.push(body); },
    jobsValue: () => 2,
    fetch: async () => ({ json: async () => ({ exists: true, plan_id: "p7", blockers: [], operations: 3, lines: [] }) }),
    refreshState: async () => {},
    addLog: () => {},
    GATE_WARN: {}, currentPhase: "prep", gatePhase: "prep", gatePlanId: null,
  };
  vm.createContext(ctx);
  vm.runInContext(src.slice(from, to) + "\n;globalThis.api = { showChanges, acceptChanges, confirmExecute };", ctx);
  return { ctx, els, posted };
}

async function accept(lastRun, stop, confirm) {
  const { ctx, els, posted } = sandbox(lastRun);
  ctx.api.showChanges(stop);
  await ctx.api.acceptChanges();
  const out = { sent_on_accept: posted.slice(), gate_open: !els["#gate-overlay"].hidden };
  if (confirm) {
    await ctx.api.confirmExecute();
    out.sent_on_confirm = posted.slice(out.sent_on_accept.length);
  }
  return out;
}

// The gate with the page's own poll, run sending and refusal logging. `summary`: what /api/plan-summary answers;
// `state`: what /api/state answers (a poll); `run`: [status, body] /api/run answers.
function gateSandbox({ summary, state, run }) {
  const els = {};
  const sent = [], logged = [];
  const ctx = {
    $: (sel) => els[sel] || (els[sel] = element()),
    document: { querySelectorAll: () => [] },
    lastRun: {}, jobsValue: () => 2, hideChanges: () => {}, pollWhileRunning: () => {}, reloadEditFrame: () => {},
    addLog: (e) => { logged.push(e); },
    fetch: async (url, opts) => {
      if (url.startsWith("/api/plan-summary")) return { ok: true, status: 200, json: async () => summary };
      if (url === "/api/state") return { ok: true, status: 200, json: async () => state };
      if (url === "/api/run") {
        sent.push(JSON.parse(opts.body));
        return { ok: run[0] === 200, status: run[0], json: async () => run[1] };
      }
      throw new Error(`unexpected fetch ${url}`);
    },
    GATE_WARN: {}, currentPhase: "merge", gatePhase: "merge", gatePlanId: null, gateAccept: null,
    jobsSeeded: true, cpuCount: 8, prevRunning: false, currentJobLabel: null, zoneQuestion: null,
  };
  vm.createContext(ctx);
  vm.runInContext(["refreshState", "logRefusal", "postRun", "openGate", "closeGate", "confirmExecute"].map(fnSrc).join("\n")
    + '\n;var overlay = $("#gate-overlay");'
    + "\n;globalThis.api = { refreshState, openGate, confirmExecute };", ctx);
  return { ctx, els, sent, logged };
}

const SUMMARY = { exists: true, plan_id: "p7", blockers: [], stale: [], operations: 3, lines: [] };
const STATE_REPLANNED = { workspace: "/w", phases: { merge: { plan_exists: true, plan_id: "p8" } }, actions: {} };

async function gate({ summary = SUMMARY, poll = false, run = [200, { ok: true }] } = {}) {
  const { ctx, els, sent, logged } = gateSandbox({ summary, state: STATE_REPLANNED, run });
  await ctx.api.openGate("merge");
  const out = { gate_open: !els["#gate-overlay"].hidden };
  if (out.gate_open) {
    if (poll) await ctx.api.refreshState();   // a poll while the gate is open: the plan was made again in a terminal
    await ctx.api.confirmExecute();
  }
  return { ...out, sent, logged: logged.map((e) => e.msg) };
}

(async () => {
  const code = "0123456789ab";
  const remembered = { phase: "geotag", command: "execute", confirm: true, plan_id: "p3", jobs: 4 };
  console.log(JSON.stringify({
    execute_not_remembered: await accept({}, { phase: "merge", command: "execute", code, lines: [] }, true),
    execute_remembered: await accept({ "geotag/execute": remembered },
                                     { phase: "geotag", command: "execute", code, lines: [] }, false),
    plan_not_remembered: await accept({}, { phase: "prep", command: "plan", code, lines: [] }, false),
    gate_polled_while_open: await gate({ poll: true }),
    gate_refused: await gate({ run: [409, { ok: false, error: "the plan changed since you reviewed it — re-open the gate" }] }),
    gate_on_blockers: await gate({ summary: { ...SUMMARY, blockers: ["a photo is missing"] } }),
    gate_on_stale: await gate({ summary: { ...SUMMARY, stale: ["the handoff changed"] } }),
    gate_on_no_plan: await gate({ summary: { exists: false } }),
  }));
})();
