# Who is this for?

*The fewest questions that settle one thing — who the tool is for — and, traced downward, the
same roots are the design explained. Read them forward to decide fit; read them down to see why
it is built this way.*

---

> Where this comes from: twenty years of wrestling with the *full geotag* problem.

---

## What this is

The structure here — the numbered folder workspace, the JSON decision files, prep recording your
sort before geotag plans, the plan/validate/execute ceremony — is the direct, more or less
inevitable consequence of a few root facts/decisions, and the point of laying them out here is
economy: ask the **smallest set of questions that settles fit**, so one can quickly decide if this
is for them.

The roots are what is open to debate; the rest follows from them. **If one accepts the roots,
the architecture is largely not negotiable; if one rejects them, one is simply not the intended
user — and in neither case are the downstream details the place to start.**

So this is where you find the project's **opinions**: a few high-level commitments, and then
the chain by which each forces the engineering visible in the code and the specification.

---

## The root layer: three facts, four choices

Before any choices, three **facts** about photos — awkward, under-named, and almost certainly
already familiar even if never filed as a *kind* of problem. The recognition is the point: these
are potholes, not opinions one has to adopt.

1. **A photo batch is large** — a trip dump or a years-deep library: thousands of RAW and JPEG
   frames, several cameras and phones. *Met as:* the card one keeps meaning to deal with; the
   decade of folders; *"I'll geotag these someday."*
2. **Camera clocks drift — independently, and from day to day.** Each body's clock is wrong by its
   own amount, and that amount changes between days (drift, a reset to local time in the morning,
   a missed daylight-saving change). There is no single offset to find. *Met as:* the import that
   landed an hour early; the shots an hour off after a border.
3. **GPX coverage is partial.** The logger's tracks reach *some* of the library, never all of it,
   so the tracks alone can never place every frame. *Met as:* the half-tagged library; the map
   view with holes.

Then, given those facts, four **choices** — the arguable part, where someone else could have gone
another way. These can be argued with.

1. **Photos matter; they are irreplaceable, so they deserve care** — no original may be lost or
   silently altered; correctness beats convenience.
2. **A local, owned, folder-based library** — a plain directory tree on disk (digiKam, Immich,
   anything that reads folders), not a cloud service or a proprietary catalog.
3. **Ask only what the data can't settle** — resolve everything derivable automatically; ask only
   real judgment questions, and make each one cheap to answer.
4. **100% placement, even under GPS scarcity** — every photo ends up on the map, precise where
   tracks allow, rough or manual where they don't: a *map-complete* library.

Each is written up, with where one has met it or what it commits to, in
[the philosophy](../spec/rationale/philosophy.md) ([read it online](https://sigfridvonshrink.github.io/photos-cartographer/rationale/philosophy.html)) — part of
[the specification](../spec/README.md), published at [sigfridvonshrink.github.io/photos-cartographer](https://sigfridvonshrink.github.io/photos-cartographer/).

**If the roots above aren't a match, stop here.** Everything below is only their consequence.
The **facts** are not up for disagreement — clocks drift, batches are large, coverage is partial —
but they may simply fail to reach a given case: someone shooting only a phone, a handful of
frames, or a track that already covers everything has a situation these facts don't touch, and
this tool does not apply. The **choices** are a different matter — those are values, and people
may disagree: a cloud library over an owned folder tree, or no appetite for a plan-driven
pipeline. Disagree with a choice and the tool again is useless.

Two things that may look like roots are not: **Linux** and **open source**. The tool is built and
run on Linux, but it is plain Python calling `exiftool`, ImageMagick and `ffmpeg`, all
cross-platform; open source follows from the *local, owned* choice rather than driving anything.

---

## The entailment: premise → forced consequence → concrete mechanism

Everything below the roots is their consequence, and [the philosophy](../spec/rationale/philosophy.md)
records each step as an item that names what it follows from:

- from *photos matter* — the non-destructive core: plan → validate → execute, no-clobber moves,
  quarantine instead of deletion, and a record of each photo's own values so any decision can be
  withdrawn;
- from *clocks drift* with *ask only what the data can't settle* — a clock offset per camera,
  destination and day; the split between the JSON record and the editor that writes it; and
  minimal asks — a timezone or a fallback position set once high in the destination tree and
  inherited below it — piggybacked on the destination sort you would do anyway;
- from *photos matter* with *partial coverage* — the recoverable core: discrete stages, the
  filesystem as truth, re-runs that act only on what changed, and an identity that survives
  metadata writes and renames;
- from *100% placement* with *partial coverage* — the total-coverage cascade: every point of the
  tracks squeezed out (matched, interpolated, extrapolated), a folder fallback position, a short
  worklist of what nothing can place, and every position marked with how it was found;
- from *large batches* with *100% placement* — a job that spans several sittings, and the durable
  record it forces: plain JSON decisions read back each run, and one self-describing log.

Each item says the concrete mechanism it puts in the code; the graph there is drawn from the
links, and the specification's build fails if a consequence marked forced traces back to no root.
Only the seven roots are independent; everything below the first rank is entailment. Read it and
the headline is plain: of seven roots, only four are arguable, and the rest of the system is
entailment.

The residue — what is *not* forced: the exact stage cut points, the clustering details, which
folder-based library, the folder names — is there too, each marked as a judgement.

---

## Using this document

When a specific design decision looks surprising, trace it up. If it lands on a root, that root is
where the conversation belongs. If it lands in the residue above, it is fair game for ordinary
debate.

This document is the **roots and rationale**; for the **mechanics** they produce — camera groups,
per-day clock offsets, the by-dest tree, what cascades — see [Concepts](concepts.md). For where the
existing tools sit relative to these roots — and why the niche is empty — see
[How this compares](comparison.md).
