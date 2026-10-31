# AI disclosure

**The design and specifications are mine. The implementation is AI-written.**

I authored the design: what this tool does, the safety model (no mutation outside a plan,
recoverable quarantine, no-clobber, filesystem-as-truth), the pipeline shape, and the behavioral
specifications in [`spec/`](spec/). Those design documents were turned into precise behavior
specifications, and the code was written by an AI coding assistant working against them.

The specifications are the source of truth, not the generated code. The behavioral clauses in
[`spec/`](spec/) are indexed; each CI-gated clause is backed by a test that runs on every push and
pull request, and the remaining clauses carry explicit and tracked omission reasons (see
[`COVERAGE.md`](COVERAGE.md)). So the AI-written implementation is held to a human-authored
specification and verified mechanically — the gate fails if a covered clause loses its test, before
a regression can touch a photo.

The specifications are being restructured, with AI assistance, into a sphinx-needs corpus — what the tool
guarantees, why, and how the build does it, as linked items (see [`spec/README.md`](spec/README.md)). The words and the
decisions remain mine: every converted sentence is recorded verbatim beside where it went, and an item counts as part of
the specification only once I have ruled it.

In short:

- **Human (me):** the design, the safety guarantees, the specifications, and the tests' intent.
- **AI:** the implementation that satisfies those specifications.
- **CI:** proves the implementation still matches the specifications on every change.
