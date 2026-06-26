# AI disclosure

**The design and specifications are mine. The implementation is AI-written.**

I authored the design: what this tool does, the safety model (no mutation outside a plan,
recoverable quarantine, no-clobber, filesystem-as-truth), the pipeline shape, and the behavioral
specifications in [`spec/`](spec/). Those design documents were turned into precise behavior
specifications, and the code was written by an AI coding assistant working against them.

The specifications are the source of truth, not the generated code. Each behavioral clause is backed
by an automated test, and the full suite runs in CI on every push and pull request (see
[`COVERAGE.md`](COVERAGE.md) and [`spec/`](spec/)). So the AI-written implementation is held to a
human-authored specification and verified mechanically — a change that violates the intended behavior
is caught before it can touch a photo.

In short:

- **Human (me):** the design, the safety guarantees, the specifications, and the tests' intent.
- **AI:** the implementation that satisfies those specifications.
- **CI:** proves the implementation still matches the specifications on every change.
