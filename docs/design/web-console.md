# Design note — operational web console (DRAFT / discussion)

**Status:** exploratory. Nothing here is committed to the spec. This captures a design
conversation so it can be resumed later. `spec/` remains the behavioral source of truth;
this note is *not* authoritative.

## Goal

Add an operational interface that lets the user **run and monitor every phase** (prep / geotag /
merge), not just `edit`, from a browser — served the same way the decision editor is (local web
server, in-package, importlib.resources assets, no bundler). The CLI must keep working exactly as it
does today; the web console is an *additional* front-end, not a replacement.

Motivation for the run-modes (below): the workspace lives on a server where the work is CPU/IO
intensive; the user may want to drive the UI from a laptop while the work runs on the server.

The non-negotiable USP stays: safety — no-clobber, quarantine-not-delete, fingerprint abort,
whole-run lock, plan → dry-run → execute. The web layer must not weaken any of it.

## Roadmap (decided)

**v1 = the event seam + sinks, CLI only. No webserver.** Refactor the CLI to push/sink mode; build no
UI. This preps the application for the web console without building it.

Rationale (why this slice first):
- It's the **only slice with zero new concepts** — no async, no server, no SSE, no auth, no SPA, no
  thread boundary. Just restructure existing output. All hard web work deferred.
- **Zero new concurrency:** tty/log sinks run inline on the same thread; the tricky
  queue-across-thread-boundary handoff appears only with the *web* sink (v2), not now.
- **Independently valuable even if the web UI never happens:** testable events (assert on emitted
  events, not scraped stdout), one verbosity knob (a sink filter, not scattered `if`s), one consistent
  output vocabulary across phases.
- It de-risks the **seam shape** where it's easy to verify (you can see the tty output), so the web
  sink later is genuinely "just another sink."

The one thing v1 must get right (or the web inherits the damage): **core emits structured events, not
preformatted strings.** Semantics in events, formatting in sinks — e.g. core emits
`Progress(task_id, cur, total)`; the tty sink formats `"hashing 4123/9000"` + the `\r` bar; the future
web sink renders a widget from the same numbers. If the core emits tty-shaped strings, the web can
only reprint them — coarse data that can't be un-baked.

v1 scope discipline:
- **Map existing output 1:1 into events.** Don't invent new granularity (that's the separate
  `on_event`-breadth question) — keep it a true refactor so golden tests can prove "same output."
- **Land infra + one phase first** (prep), then the other two follow mechanically; keeps the first PR
  reviewable. Infra = `Event` types (`Log`, `Progress`), the sink interface, a broadcast dispatcher,
  a tty sink, a log sink, wired into `run()` with a **default CLI sink** so standalone
  `python -m cartographer.photos_1_prep …` still works unchanged.
- Bake in now (tty-sink concerns anyway): **progress = latest-wins register** even on the CLI (`\r`
  overwrite — the same "repaint current" the web sink will do); **isatty branch lives in the tty
  sink** (bar when a terminal, plain lines when piped).
- **Progress→done convention:** an explicit terminal signal — a `done` flag on `Progress` with a
  status (`ok`/`aborted`) — so a sink unambiguously finalizes (freeze/clear) the line/widget. Do
  **not** rely on `cur==total` (a task can end early/aborted without reaching total, leaving the sink
  hanging). The narrative summary ("hashed 9000 in 42s") is a **separate, optional `Log`**, not coupled
  to the progress mechanic.
- **Golden/snapshot tests on the tty sink** — silent output drift is the one real risk; guard it.

**v2+** (on a core that already emits): web sink + stdlib `ThreadingHTTPServer` + SPA + the **prep**
vertical (trigger → dry-run summary → confirm → execute). Then geotag (fold `edit` in as its decision
step), then merge (most dangerous, last) + the cross-phase dashboard. See "Run modes" / "Security"
for how remote works (SSH path).

## Core principle: one mutation path, two planes

The whole design hinges on splitting two planes that are tangled together in the current scripts:

- **Control/data plane (unchanged):** direct function calls, return values, exceptions. All
  correctness and safety live here. The web console must *drive* this, never re-implement it. No web
  handler builds/edits plans or moves files itself — every action calls the same `run()` /
  `add_arguments` the CLI calls. One code path = the safety contract cannot be forked.
- **Observation plane (new):** a **one-way status tap**. Core emits status outward to sinks while it
  works. Nobody reads status to make a decision. Litmus test: if the entire status stream vanished,
  the pipeline would run and produce byte-identical artifacts. Status is lossy, optional, cosmetic.

This keeps "keep the core constant" honest: we add a *read tap*, not a new path.

## Status vs durable record — explicitly different things

- **Artifacts + sqlite + journals** = durable, replayable truth. Already exists. **Out of scope** for
  this feature. The status stream has *no* durability requirement and must not be conflated with the
  journal. (Earlier in the discussion we wrongly proposed "replay status from the journal" — dropped.
  Status is fire-and-forget.)
- **Status stream** = ephemeral progress signal for humans watching. Lossy-OK.

## Two status channels (this is the key modeling insight)

Today `print` and `\r`-overwrite are two different semantics tangled together. Make them two explicit
event kinds in the model, so each sink can render appropriately:

- **Log events (scrolling):** discrete, ordered, append-only facts ("phase prep started",
  "quarantined 3 dups", "plan written to …"). Narrative; prefer none lost.
  - Shape: `Log(level, msg)`.
- **Progress events (overwriting):** one mutable value, high frequency, **latest-wins**
  ("hashing 4123/9000"). Intermediate values disposable.
  - Shape: `Progress(task_id, label, cur, total)`. `task_id` is essential — it tells a sink *which*
    line/widget to overwrite. Multiple concurrent `task_id`s = multiple bars.

### Delivery: one transport, two consumption disciplines

Don't force log and progress into the same push/pull pattern — their semantics are opposite. Use one
shared notification transport, consumed two ways:

```
shared area (per run):
  log:      append list + per-consumer cursor  → drain new since cursor  (lossless, ordered)  → PUSH-like
  progress: dict task_id → latest value         → read snapshot          (lossy, latest-wins)  → PULL-like

producer: append log / set progress[id] ; signal "changed"
consumer (on wakeup or own timer):
  - drain log from my cursor   (gets everything)
  - read progress snapshot     (gets only latest)
```

- Log → **push / lossless drain** (pull would drop lines between polls).
- Progress → **pull / latest-wins register** (gives coalescing + throttling for free; push would
  require bolting coalescing back on, and would flood a tight per-file loop / the web socket).

### Sink behavior matrix

| event             | tty                         | web (SPA)                       | log file                         |
|-------------------|-----------------------------|---------------------------------|----------------------------------|
| log (scrolling)   | println                     | append to log pane              | append line                      |
| progress (overwr) | `\r` / bar on same line     | update widget keyed by `task_id`| **drop**, or sample (start+end)  |

Consequences:
- **Throttle/coalesce progress at source** (~5–10/s) or let each sink keep newest-per-`task_id`. The
  overwrite semantic *is* the throttle.
- **isatty degradation:** overwrite needs a real terminal. Piped/redirected stdout → drop progress or
  print periodic scroll samples. The event model formalizes the ad-hoc isatty check.
- **Web renders richer than tty for free:** tty struggles with N concurrent bars (ANSI cursor
  juggling) and collapses to the active one; web trivially shows N widgets. Same event stream. This is
  the payoff of putting the distinction in the model.
- **Progress → done handoff:** a finished progress task closes with a final `Log` line ("hashed 9000
  in 42s"); widget clears or freezes at 100%. Convention TBD (done flag vs terminating log event).

## In-process execution (no subprocess)

The web server imports the core and calls `run()` **in-process**, passing the observer callback.
Decided against spawning the CLI as a subprocess (that was an earlier option — rejected in favor of
in-process for tighter integration and rich live events).

```
web server (generalize editor's)
  POST /prep/plan → submit to single-slot executor (max_workers=1)
                  → core.run(on_event=push)        # worker thread
                  → push → queue → SSE → browser
  GET  /events    → SSE stream (live status)
core unchanged except an additive, optional on_event hook
```

Four gotchas the subprocess would have isolated, and how to handle them in-process:

1. **Don't block the server.** `run()` is long + synchronous → run in a worker thread/executor; keep
   the HTTP loop free for SSE. Single-worker executor naturally matches the one-run-at-a-time lock.
2. **Lock still applies.** In-process call acquires the same whole-run lock; a second trigger blocks
   or is rejected. Only hold the lock across the actual run, not idle UI time.
3. **Global `CONFIG`.** Core uses a module-global `CONFIG` (the conftest restore-between-tests is the
   tell). One process = one CONFIG. Safe *because* the lock serializes runs — never run two phases in
   parallel in one process.
4. **No crash isolation.** An unhandled exception can kill the server → wrap the job, catch + report
   to UI, keep server alive. Native crashes (exiftool/magick/ffmpeg) stay isolated because core
   already subprocesses those; only catchable Python exceptions reach the server.

## Server stack — stdlib `ThreadingHTTPServer` (resolved)

The data flow doesn't want async. Map the channels:
- **status down** = SSE (one-way server→browser): a long-lived HTTP response writing chunks.
- **commands up** = plain POSTs.

No bidirectional channel → **no WebSocket → no strong reason for async/ASGI** (async earns its keep
for WebSockets or C10k connection counts; here it's ~1–3 browsers, unidirectional streaming).

So use stdlib **`ThreadingHTTPServer`** — which the `editor` already uses:
- thread per request (concurrent browsers + SSE + API),
- the job in a single-worker thread pool (matches the whole-run lock),
- SSE handler thread blocks on `queue.get()`, writes a chunk per event,
- broadcast via thread-safe queues.

Zero new deps, matches the editor, threads cover this scale.

### zipapp constraint (why a framework is costly here)
The tool ships as **one self-contained zipapp** (`tools/build-pyz`). A zipapp imports Python in place
and **cannot `dlopen` a C extension (`.so`) from inside the zip** without extraction. So any bundled
dep must be **pure Python**, and adding one would be the project's **first runtime pip dependency** —
a break from the current zero-pip-runtime ethos, plus a vendoring step in `build-pyz`
(`pip install --target` into the staging dir).

### Documented escape hatch (only if WebSockets are ever needed)
If a future need (true bidirectional WS, painful hand-rolled routing) justifies a framework, the
zipapp-safe picks are **pure-Python only** — avoid the C-accelerated bits:
- ❌ `uvloop`, `httptools` (C), `aiohttp`'s C parser.
- ✅ **Starlette + uvicorn *minimal*** (deps `click` + `h11`, both pure Python; do **not** install the
  `[standard]` extras that pull uvloop/httptools), or **Quart + Hypercorn** (h11/h2/wsproto, pure
  Python). `h11`, `websockets`, `werkzeug` also pure-Python (skip their optional C speedups).
- Cost: first runtime dep + `build-pyz` vendoring.

## Run modes

The run-mode axis is **orthogonal** to the sink/event design — GUI mode just attaches the web sink +
serves the SPA; CLI mode attaches tty/log sinks. Same core, same events.

Crucial clarification: in **all** GUI modes the **server process runs on the box with the workspace**;
the browser is only the SPA client. So "remote" does not ship compute to the laptop — compute stays
server-side and the web sink streams *status* (pixels) to the laptop. The laptop-drives-server goal is
satisfied for free by the in-process design.

**The server always binds `127.0.0.1`.** Remote access is the SSH path below, not a non-loopback
bind. This is the convergence the security discussion arrived at (see "Security stance").

| mode            | how                                   | open browser |
|-----------------|---------------------------------------|--------------|
| local           | `cartographer console` (binds loopback) | no           |
| local + launch  | same + `--open`                        | yes (laptop) |
| remote          | SSH one-liner: tunnel + launch (below) | laptop-side wrapper |
| LAN-direct      | *optional opt-in* `--host 0.0.0.0` + token (demoted; see below) | no |

Proposed surface: `cartographer console --port --open [--host]`. `--host` defaults to `127.0.0.1`;
`0.0.0.0` is the gated opt-in. CLI phases unchanged.

### Lifetime + reconnect
- **Default (SSH-session-tied):** on the blessed SSH path the server's lifetime is the SSH session —
  close the laptop → SIGHUP → server stops. A run interrupted that way is resumable from artifacts, so
  nothing is corrupted. Simplest, and good "drive-from-laptop" ergonomics. (Detached/daemon mode that
  outlives the session is an open question, below.)
- **Browser reconnect within a live session:** a browser that drops and returns reads the current
  **snapshot** (progress dict + recent log buffer) then resumes live events. A dropped browser
  corrupts nothing (status is ephemeral; truth is the artifacts).
- If the server process itself dies mid-run (reboot, SSH drop): the in-process run dies, but the
  idempotent/resumable contract means it resumes from artifacts/journal. Acceptable.
- Many browsers may watch (broadcast sinks); the whole-run lock guarantees one run at a time.

## Security stance (settled on the SSH path)

Context the user set: **this will never run over the internet — LAN only.** And the user already
reaches the server over **SSH** (that's how they'd read a printed URL). Those two facts decide the
whole design: the blessed remote path is an SSH tunnel, not a non-loopback HTTP bind.

Framing that must not be lost: the safety USP (no-clobber etc.) protects against **mistakes**. A
non-loopback bind introduces an **adversary** — a different threat. An unauthenticated control surface
reachable over the network lets anyone who can hit the port trigger `execute` / `merge` / `quarantine`
on **irreplaceable originals**, and no-clobber won't stop a *valid* malicious request.

### Blessed remote path: SSH tunnel + remote launch in one command

The server binds `127.0.0.1` on the server; a single SSH command both launches it and tunnels to it:

```bash
ssh -t -o ExitOnForwardFailure=yes -L 8765:127.0.0.1:8765 you@server \
    'cd /path/to/workspace && cartographer console --host 127.0.0.1 --port 8765'
# then open http://127.0.0.1:8765 on the laptop
```

Everything the earlier DIY-crypto discussion tried to hand-build falls out for free:
- Server bound `127.0.0.1` on the server → **unreachable except through the tunnel**.
- Transport **encrypted + authenticated by SSH** — reviewed implementation, zero custom crypto.
- Laptop hits `http://127.0.0.1:8765` → a **secure context** (so `crypto.subtle` would even be
  available if ever needed) and **loopback-exempt → no token friction**.
- No pubkey pinning, no in-URL bootstrap app, no WebCrypto. Deleted.

Flags that matter:
- `-t` → pty, so Ctrl-C tears the remote server down cleanly.
- `-o ExitOnForwardFailure=yes` → fail fast if the port can't forward (don't launch a server you
  can't reach).
- **Do not** use `--open` server-side — it'd try to open a browser on the headless server. Browser
  launch belongs on the laptop: either click the `http://127.0.0.1:8765` the server prints to stdout
  (it appears in the laptop terminal over SSH), or a thin **laptop-side wrapper** runs the ssh command,
  waits for the "listening" line, then opens the local browser (this is where `--open` logic lives).

### Why the DIY-crypto branch was abandoned (kept for the record)

The discussion explored deriving a secure channel without SSH. The conclusions, so we don't re-walk
them:
- Bootstrapping *authenticated* encryption over a channel an active attacker controls requires a
  trust anchor delivered **out-of-band**. There is no third option — it's a theorem, not a missing
  trick. TLS certs and SSH `known_hosts` are exactly that anchor.
- An SSH-delivered printed URL **is** a legitimate out-of-band anchor (a LAN MITM can't see it), so a
  pubkey-fingerprint-in-URL + SPA-integrity-hash scheme is cryptographically *sound* — but it is just
  hand-built "TLS with a pinned cert."
- Two facts kill DIY anyway: (1) **WebCrypto (`crypto.subtle`) is gated to secure contexts** —
  HTTPS or `localhost` only; it's `undefined` over `http://LAN-IP`, so browser crypto over plain LAN
  HTTP is a non-starter. (2) The scheme's anchor *requires* an SSH session to exist; but if SSH
  exists, `ssh -L` to `localhost` gives the same guarantee for free. The DIY scheme can never beat the
  tunnel in the user's setup.
- It would only earn its keep if the URL arrived via a channel that **can't tunnel** (physical
  console, QR code) — not this setup.

### LAN-direct mode (optional, demoted — not the blessed path)

If the user ever wants browser access **without** an SSH session (trusted LAN, can't be bothered),
`--host 0.0.0.0` is the opt-in. It must then carry the full guard, because it's the adversary case:
- Token-in-URL → session cookie (Jupyter model): strong random token (`secrets.token_urlsafe`,
  ≥128-bit), printed **to stdout only** (never the log file), exchanged on first hit for an
  **HttpOnly session cookie**, then `history.replaceState` strips the token from the URL bar. It's
  "one token → one session," not a per-request nonce (a SPA makes many requests).
- `SameSite=Strict` cookie + a required custom header (e.g. `X-Cartographer: 1`) on mutating POSTs →
  kills CSRF.
- **IP-pin** the session to the first client that presents the token (recoverable by re-presenting
  the token, since DHCP can change the laptop IP) + a **same-subnet allowlist**. These kill remote and
  off-path attackers.
- **Fail closed:** refuse to bind non-loopback unless this guard is configured.
- ⚠️ **Residual that this mode does NOT cover:** a same-segment **on-path/MITM** attacker on an
  untrusted/WiFi segment (ARP spoof is trivial) can sniff token/cookie over plaintext HTTP. That is a
  conscious trust assumption, not something the token/IP-pin eliminated. The SSH path has no such
  residual — which is *why* it's blessed and this is demoted.

### Auth ≠ the mistake-guard
Auth answers *who*. It does **not** replace the dry-run → confirm 2-step for
execute/merge/quarantine. Keep both layers: auth stops the wrong person; the 2-step stops the right
person's wrong click.

## UI safety surfaces (render, don't bypass)
- **Execute is a deliberate 2-step:** plan → show the dry-run **summary of the real serialized plan**
  (the canonical artifact, per the shared contract — not a JS simulation) → explicit confirm →
  execute. Never a one-click execute.
- Quarantine / merge / execute get confirm dialogs.
- Filesystem/journal stays the source of truth; never hold mutable run state in server memory as
  truth (resumability rule).

## Decisions so far
- **v1 = event seam + sinks, CLI only (no webserver).** Refactor CLI to push/sink mode; emit
  structured events (not strings); 1:1 map of today's output; infra + prep first, then the other
  phases; golden tests guard output drift. Web is v2+ on a core that already emits. (See "Roadmap".)
- One mutation core, driven (not re-implemented) by both CLI and web.
- Status is a one-way, ephemeral observation tap; separate from durable artifacts/sqlite/journals.
- Two status channels: log (lossless drain / push) and progress (latest-wins register / pull), over
  one shared transport. Per-sink consumption is **log = push/drain, progress = pull/snapshot**.
- **Progress→done = explicit `done` flag + status (`ok`/`aborted`) on `Progress`** (not `cur==total`);
  narrative summary is a separate optional `Log`.
- In-process execution via an additive `on_event` hook; **not** subprocess spawning.
- **Server stack = stdlib `ThreadingHTTPServer`** (as the editor): SSE-down + POST-up needs no async,
  no WebSocket, no framework, zero new deps. Pure-Python Starlette/uvicorn-minimal is the documented
  escape hatch *only* if WebSockets are ever needed — gated by the zipapp pure-Python constraint and a
  `build-pyz` vendoring cost (first runtime dep).
- Server **always binds `127.0.0.1`**; compute always server-side; reconnect via snapshot.
- **Remote = SSH tunnel + remote launch in one command** (the blessed path): encrypted, authenticated,
  secure-context, loopback-exempt → no custom auth or crypto. Browser launch is laptop-side.
- DIY in-browser crypto **rejected**: WebCrypto needs a secure context (not available over
  `http://LAN-IP`), and any sound scheme requires an SSH session anyway — at which point the tunnel
  wins.
- `--host 0.0.0.0` (LAN-direct) is an **optional, demoted** opt-in, fully guarded
  (token→cookie + SameSite + IP-pin + subnet allowlist + fail-closed), with a known on-path/MITM
  residual the SSH path doesn't have.

## Deferred (default set — revisit when the need is real)

All prior open items now have a decided default; none blocks v1.

- **Event granularity beyond v1's 1:1 map** — *defer, demand-driven.* The seam makes adding an event a
  one-liner; add finer per-op instrumentation later, only where a real sink (e.g. a web progress bar)
  wants it. No decision needed now.
- **`edit` fold-in** — *v2; direction = embed, don't duplicate.* Fold `edit` into the console as a
  route/tab (it's geotag's decision step), reusing the generalized editor server, **while keeping the
  standalone `cartographer edit` entry working** (it exists; tests use it).
- **Laptop-side launcher wrapper (SSH path)** — *documented one-liner now; convenience later, low
  priority.* The raw `ssh -t -L … 'cartographer console …'` works copy-paste. A
  `cartographer console --remote you@server` that builds the ssh command + waits for the "listening"
  line + opens the local browser is a v2+ nicety, not a blocker. Shape (shell script vs in-tool) TBD.
- **SSH server lifecycle** — *default = session-tied.* Close laptop → SIGHUP → server stops; the run
  resumes from artifacts. A detached/daemon mode (`nohup`/`systemd`/`tmux` + separate tunnel) so a long
  run outlives the session is opt-in, deferred until that need is real.

## Rejected / corrected along the way
- Subprocess-spawn execution model (chose in-process).
- "Replay status from the journal" (status has no durability requirement; journals are for artifacts).
- Forcing log and progress into the same push/pull pattern.
- Casual `0.0.0.0` with no auth (now: loopback-only by default; `0.0.0.0` is guarded + demoted).
- **DIY in-browser crypto / ephemeral-key / pubkey-in-URL channel** — sound in theory but blocked by
  the WebCrypto secure-context rule and strictly dominated by the SSH tunnel in this setup.
- "Server reaches out to the SPA" — browsers don't accept inbound connections; the SPA always
  initiates.
- Thinking of it as a message-passing / actor architecture — it is direct-call core + a one-way tap.
```
