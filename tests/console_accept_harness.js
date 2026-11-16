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
const fs = require("fs");
const vm = require("vm");

const src = fs.readFileSync(process.argv[2], "utf8");
const from = src.indexOf("// --- a run stopped on changes to the workspace");
const to = src.indexOf("// --- init-library");
if (from < 0 || to < from) throw new Error("app.js sections not found");

function sandbox(lastRun) {
  const els = {};
  const posted = [];
  const ctx = {
    $: (sel) => els[sel] || (els[sel] = { hidden: true, textContent: "", onclick: null }),
    lastRun, posted,
    postRun: async (body) => { posted.push(body); },
    jobsValue: () => 2,
    fetch: async () => ({ json: async () => ({ exists: true, plan_id: "p7", blockers: [], operations: 3, lines: [] }) }),
    refreshState: async () => {},
    GATE_WARN: {}, currentPhase: "prep", gatePhase: "prep", planId: null,
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

(async () => {
  const code = "0123456789ab";
  const remembered = { phase: "geotag", command: "execute", confirm: true, plan_id: "p3", jobs: 4 };
  console.log(JSON.stringify({
    execute_not_remembered: await accept({}, { phase: "merge", command: "execute", code, lines: [] }, true),
    execute_remembered: await accept({ "geotag/execute": remembered },
                                     { phase: "geotag", command: "execute", code, lines: [] }, false),
    plan_not_remembered: await accept({}, { phase: "prep", command: "plan", code, lines: [] }, false),
  }));
})();
