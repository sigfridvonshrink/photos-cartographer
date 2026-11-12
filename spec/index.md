# photos-cartographer — the specification

One corpus in three levels, each in the same four documents as the phases: **what cartographer guarantees**, **why**,
and **how this build does it** — and the tests that verify it. Every item has an id and a status (`seed` until ruled);
the links between items are typed and checked at every build.

```{toctree}
:maxdepth: 2
:caption: What it guarantees

intent/shared
intent/prep
intent/merge
```

```{toctree}
:maxdepth: 2
:caption: Why

rationale/philosophy
rationale/shared
rationale/prep
rationale/merge
```

```{toctree}
:maxdepth: 2
:caption: How this build does it

build/shared
build/prep
build/merge
```

```{toctree}
:maxdepth: 1
:caption: The tests

_generated/tests
```
