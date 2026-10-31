"""The cartographer specification as one Sphinx project: MyST Markdown, sphinx-needs items.

Built from the repo root with this directory as the source and config:
    tools/spec-build      (wraps: sphinx-build -W spec spec/_build/html; the diagrams need graphviz's `dot`)
The corpus is three levels in one project, each in four documents as the phases are -- shared, prep, geotag, merge:
`intent/` (what cartographer guarantees, naming no tool, file or database), `rationale/` (why: the justifications,
tagged, never normative) and `build/` (how this build meets the intent). The tests are items too, generated at every
build from pytest's own collection of `@pytest.mark.spec(..., test="TST-...")` (spec/_ext/corpus.py).
The specs not yet converted (spec/photos-*.md) stay outside the build until each is.
"""
import os
import sys

project = "photos-cartographer"
root_doc = "index"
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "_ext"))
extensions = ["myst_parser", "sphinx_needs", "sphinx.ext.graphviz", "corpus"]

# The item kinds. The prefix names the kind; the name after it is the item's own (`_` between words). Kinds are added
# as the conversion needs them -- each one ruled before it is used.
needs_types = [
    # intent/: what cartographer guarantees
    {"directive": "def", "title": "Definition", "prefix": "DEF-", "color": "#E0E0C8", "style": "node"},
    {"directive": "inv", "title": "Invariant", "prefix": "INV-", "color": "#E8C9C9", "style": "node"},
    {"directive": "rul", "title": "Rule", "prefix": "RUL-", "color": "#D9E4C8", "style": "node"},
    # an assumption about the user's media the rules rely on: unlike a fact, a user can break it
    {"directive": "asm", "title": "Assumption", "prefix": "ASM-", "color": "#E6D8EC", "style": "node"},
    # a worked example: never normative; it shows the items it `illustrates`
    {"directive": "exm", "title": "Example", "prefix": "EXM-", "color": "#F2F2E6", "style": "node"},
    # rationale/: why -- never normative; where it and the intent differ, the intent wins. Its roots are facts about the
    # world and design choices, which nothing follows from; every other rationale follows from them or from another.
    {"directive": "fct", "title": "Fact", "prefix": "FCT-", "color": "#F2DFB6", "style": "node"},
    {"directive": "chc", "title": "Choice", "prefix": "CHC-", "color": "#C9E2D4", "style": "node"},
    {"directive": "rat", "title": "Rationale", "prefix": "RAT-", "color": "#F0E6D2", "style": "node"},
    # build/: how this build meets the intent
    {"directive": "bld", "title": "Construction requirement", "prefix": "BLD-", "color": "#DDEBF7", "style": "node"},
    # the tests, from their marks
    {"directive": "tst", "title": "Test", "prefix": "TST-", "color": "#EDEDED", "style": "node"},
]
# Why one item names another, typed by meaning; each link is declared once, on the item whose text carries the reason,
# and sphinx-needs shows its other end.
needs_links = {
    "uses": {"outgoing": "uses", "incoming": "used by"},  # a term or mechanism defined there
    "refines": {"outgoing": "refines", "incoming": "refined by"},  # the specific -> the general it spells out
    "excepts": {"outgoing": "is the exception to", "incoming": "excepted by"},
    "upholds": {"outgoing": "upholds", "incoming": "upheld by"},  # a rule -> the invariant it makes hold
    "realises": {"outgoing": "realises", "incoming": "realised by"},  # a build item -> the intent it implements
    "justifies": {"outgoing": "justifies", "incoming": "justified by"},  # a rationale -> what it argues for
    "follows_from": {"outgoing": "follows from", "incoming": "forces"},  # a rationale -> the fact, choice or rationale it follows from
    "assumes": {"outgoing": "assumes", "incoming": "assumed by"},  # an item -> the assumption it relies on
    "illustrates": {"outgoing": "illustrates", "incoming": "illustrated by"},  # an example -> what it shows
    "verifies": {"outgoing": "verifies", "incoming": "verified by"},  # a test -> what it checks holds
}
needs_id_regex = r"^[A-Z]{3}-[\w-]+$"
needs_id_required = True
needs_fields = {
    # ruled (by Vasile) · seed (converted, not yet ruled) · retired (no longer load-bearing; the id is kept)
    "status": {"nullable": True, "schema": {"type": "string", "enum": ["ruled", "seed", "retired"]}},
    # what a failure would cost: carried over from the clause index
    "criticality": {"nullable": True, "schema": {"type": "string", "enum": ["high", "med", "low"]}},
    # a must-refuse / must-not obligation -- the kind a happy-path test cannot show
    "anti": {"nullable": True, "schema": {"type": "string", "enum": ["yes"]}},
    # required: a test must verify it (the gate) · incidental: exercised, not asserted · none: no test; `omit_reason` says why
    "verify": {"nullable": True, "schema": {"type": "string", "enum": ["required", "incidental", "none"]}},
    "omit_reason": {"nullable": True},
    # the older names this item replaces -- clause-index ids, or a user guide's numbers (F1, P1); a test mark naming a
    # clause-index id verifies this item until the marks are renamed
    "aliases": {"nullable": True},
    # a choice's kind, as the user guide names it
    "choice_kind": {"nullable": True, "schema": {"type": "string", "enum": ["value", "choice", "design-value", "goal"]}},
    # a rationale that could not reasonably be otherwise, given what it follows from (yes), or a judgement (no)
    "forced": {"nullable": True, "schema": {"type": "string", "enum": ["yes", "no"]}},
    # a test's place in the suite
    "nodeid": {"nullable": True},
}
needs_build_json = True
needs_flow_engine = "graphviz"

source_suffix = {".md": "markdown"}
myst_enable_extensions = ["colon_fence", "deflist"]
myst_heading_anchors = 4

include_patterns = ["index.md", "intent/*.md", "rationale/*.md", "build/*.md", "_generated/*.md"]
exclude_patterns = ["_build", ".venv", "photos-*.md", "README.md", "conversion"]

html_theme = "alabaster"
html_last_updated_fmt = None  # no build time in the output: the same corpus renders the same bytes
