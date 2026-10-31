# Who is this for?

*The fewest questions that settle one thing — who the tool is for — and, traced downward, the
same roots are the design explained. Read them forward to decide fit; read them down to see why
it is built this way.*

---

> Where this comes from: twenty years of wrestling with the *full geotag* problem.

---

## What this is

The structure here — the numbered folder workspace, the JSON files, the mandatory re-prep, the
plan/validate/execute ceremony — is the direct, more or less inevitable consequence of a few root
facts/decisions, and the point of laying them out here is economy: ask the **smallest set of
questions that settles fit**, so one can quickly decide if this is for them.

The roots are what is open to debate; the rest follows from them. **If one accepts the roots,
the architecture is largely not negotiable; if one rejects them, one is simply not the intended
user — and in neither case are the downstream details the place to start.**

So this is where you fine the project's **opinions**: a few high-level commitments, and then
the chain by which each forces the engineering visible in the code and the specs.

---

## The root layer: three facts, four choices

Before any choices, three **facts** (`Fx`) about photos — awkward, under-named, and almost
certainly already familiar even if never filed as a *kind* of problem. The recognition is the
point: these are potholes, not opinions one has to adopt.

The three facts — `FCT-large_batches` (F1), `FCT-clocks_drift` (F2), `FCT-partial_track_coverage` (F3) — are
items of [the specification's philosophy](https://github.com/sigfridvonshrink/photos-cartographer/blob/main/spec/rationale/philosophy.md), each with what it means and where one has met it.

Then, given those facts, four **choices** (`Px`) — the arguable part, where someone else
could have gone another way. These can be argued with.

The four choices — `CHC-photos_matter` (P1), `CHC-local_folder_library` (P2), `CHC-ask_only_what_data_cannot_settle`
(P3), `CHC-total_placement` (P4) — are items there too, each with its kind and what it commits to.

**If the roots above aren't a match, stop here.** Everything below is only their consequence.
The **facts** (`Fx`) are not up for disagreement — clocks drift, batches are large, coverage
is partial — but they may simply fail to reach a given case: someone shooting only a phone,
a handful of frames, or a track that already covers everything has a situation these facts
don't touch, and this script does not apply. The **choices** (`Px`) are a different matter
— those are values, and people may disagree: a cloud library over an owned folder tree,
or no appetite for a plan-driven pipeline. Disagree with a choice and the script again is useless.

---

## The entailment: premise → forced consequence → concrete mechanism

Everything below the roots is their consequence, and [the philosophy](https://github.com/sigfridvonshrink/photos-cartographer/blob/main/spec/rationale/philosophy.md) records each step as an item that names
what it follows from: from P1, the non-destructive core; from F2 + P3, the per-(camera group, destination, day) offset,
the format + editor split and the minimal, cascading asks; from P1 + F3, the recoverable core; from P4, the
total-coverage cascade; from F1 + P4, the multi-session job and the durable record it forces. Each says the concrete
mechanism it puts in the code; the graph there is drawn from the links, and the specification's build fails if a
consequence marked forced traces back to no root. Only the seven roots are independent; everything below the first
rank is entailment. Read it and the headline is plain: of seven roots, only four are arguable, and the rest of the system is entailment.

The residue — what is *not* forced: the exact stage cut points, the clustering details, which folder-based library,
the folder names — is there too, each marked as a judgement.

---

## Using this document

When a specific design decision looks surprising, trace it up. If it lands on a root, that root is
where the conversation belongs. If it lands in the residue above, it is fair game for ordinary
debate.

This document is the **roots and rationale**; for the **mechanics** they produce — camera groups,
per-day clock offsets, the by-dest tree, what cascades — see [Concepts](concepts.md). For where the
existing tools sit relative to these roots — and why the niche is empty — see
[How this compares](comparison.md).
