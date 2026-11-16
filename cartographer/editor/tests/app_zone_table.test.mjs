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

// Front-end unit tests for the question of the table of countries in the editor (web/app.js,
// BLD-editor_answers_zone_table): asked while the workspace has it open, answered yes or no, and saved as its own edit.
import { test } from "node:test";
import assert from "node:assert/strict";
import * as app from "../web/app.js";

const setWork = (work) => { app.state.work = work; app.state.base = JSON.parse(JSON.stringify(work)); };
const REF = { file: "zone_table", kind: "zone_table" };
const open = () => ({ question: "Download the table?", user_decision: { download: "" },
                      requires_user_input: false, stale_user_decision: false });

test("the open question is a cell of its own, unanswered and holding nothing up", () => {
  setWork({ zone_table: open() });
  assert.deepEqual(app.cellAt(app.state.work, REF), open());
  assert.deepEqual(app.statusOf(REF), ["none", "unanswered"]);
  assert.equal(app.wouldResolve(REF), false);
  assert.equal(app.refInvalid(REF), false);
});

test("no question where the workspace has none to ask", () => {
  setWork({ zone_table: null });
  assert.equal(app.cellAt(app.state.work, REF), null);
});

test("yes or no answers it; nothing else is an answer", () => {
  setWork({ zone_table: open() });
  for (const v of ["yes", "no"]) {
    app.state.work.zone_table.user_decision.download = v;
    assert.equal(app.refInvalid(REF), false);
    assert.equal(app.wouldResolve(REF), true);
    assert.deepEqual(app.statusOf(REF), ["ok", "resolved"]);
  }
  app.state.work.zone_table.user_decision.download = "maybe";
  assert.equal(app.refInvalid(REF), true);
  assert.deepEqual(app.ZONE_TABLE_ANSWERS, ["", "yes", "no"]);
});

test("the answer is saved as an edit of its own, beside the records' hashes", () => {
  setWork({ zone_table: open() });
  app.state.work.zone_table.user_decision.download = "no";
  const p = app.savePayload([REF], (r) => app.cellAt(app.state.work, r), { time: "h21" });
  assert.deepEqual(p.zone_table, [{ dest: undefined, kind: "zone_table", key: undefined, path: undefined,
                                    user_decision: { download: "no" } }]);
  assert.deepEqual(p.hashes, { time: "h21" });
});
