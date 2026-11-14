# Copyright 2026 sigfridvonshrink
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

"""The corpus's own pieces: the tests as items, and the checks sphinx-needs cannot make by itself.

- **The tests.** Before the corpus is read, pytest collects the suite (no test runs) and writes every
  `@pytest.mark.spec(<ids>..., test="TST-...")` it finds; `_generated/tests.md` is written from that, one `tst` item per
  marked test, `verifies` the items it names.
- **The checks**, each a warning, which fails the build:
  - a mark naming an id that is no item;
  - an item whose `verify` is `required` that no test verifies;
  - a link against the levels' direction: an intent item naming a build item; a rationale named by any link but
    `follows_from` (a rationale is never binding); a `follows_from` from anything but a rationale;
  - a fact or a choice nothing follows from;
  - a rationale marked `forced: yes` whose `follows_from` chain reaches no fact or choice;
  - an item stating more than one SHALL: an item carries one obligation, so a second is an item of its own;
  - a rule or invariant no rationale justifies, directly or through the item it refines or upholds — but for the
    ones listed in `unjustified.txt`, a list that only shrinks;
  - an option continued onto a second line, which sphinx-needs would silently drop.
"""
import json
import os
import subprocess
import sys
import tempfile

from sphinx.util import logging

LOG = logging.getLogger(__name__)
GENERATED = "_generated"


def _repo_root(app):
    return os.path.dirname(app.srcdir.rstrip(os.sep)) if isinstance(app.srcdir, str) else str(app.srcdir.parent)


def _collect_marks(root):
    """[{nodeid, file, line, ids, test}] from a collection-only pytest pass over the suite."""
    fd, dump = tempfile.mkstemp(prefix="corpus-marks-", suffix=".json")
    os.close(fd)
    try:
        proc = subprocess.run(
            [sys.executable, "-m", "pytest", "--collect-only", "-q", "-p", "no:cacheprovider", f"--spec-marks={dump}"],
            cwd=root, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
        if proc.returncode != 0 or os.path.getsize(dump) == 0:
            LOG.warning("pytest collection failed; no test items:\n" + proc.stdout[-2000:], type="corpus", subtype="tests")
            return []
        with open(dump) as f:
            return json.load(f)
    finally:
        os.remove(dump)


def _md_escape(text):
    return text.replace("\n", " ").strip()


def _corpus_items(srcdir):
    """The id of every item in the corpus sources, read from their `:id:` lines."""
    import glob
    import re
    items = set()
    for path in sorted(glob.glob(os.path.join(srcdir, "*", "*.md"))):
        if os.sep + GENERATED + os.sep in path:
            continue
        for line in open(path, encoding="utf-8"):
            m = re.match(r":id:\s*(\S+)", line)
            if m:
                items.add(m.group(1))
    return items


def _write_tests_page(app):
    root = _repo_root(app)
    items = _corpus_items(app.srcdir)
    by_test = {}
    for m in _collect_marks(root):
        if len(m.get("tests") or []) > 1:
            LOG.warning(f"{m['nodeid']} declares more than one test id: {', '.join(m['tests'])}",
                        type="corpus", subtype="tests")
        if not m.get("test"):
            continue
        # a parametrized test is several pytest items under one test id: one item, every node listed
        prior = by_test.get(m["test"])
        if prior and (prior["file"], prior["line"]) != (m["file"], m["line"]):
            LOG.warning(f"test id {m['test']} declared by two tests: {prior['nodeid']} and {m['nodeid']}",
                        type="corpus", subtype="tests")
            continue
        if prior:
            prior["nodeids"].append(m["nodeid"])
            prior["ids"] = sorted(set(prior["ids"]) | set(m["ids"]))
        else:
            by_test[m["test"]] = dict(m, nodeids=[m["nodeid"]])
    marks = list(by_test.values())
    out_dir = os.path.join(app.srcdir, GENERATED)
    os.makedirs(out_dir, exist_ok=True)
    lines = ["# The tests", "",
             "*Generated at every build from the suite's `@pytest.mark.spec(…, test=\"TST-…\")` marks — never edited. "
             "Each test verifies the items its mark names.*", ""]
    for m in sorted(marks, key=lambda m: m["test"]):
        unknown = sorted(t for t in m["ids"] if t not in items)
        if unknown:
            LOG.warning(f"{m['nodeid']} marks {', '.join(unknown)}, which no item is", type="corpus", subtype="tests")
        verifies = sorted(set(t for t in m["ids"] if t in items))
        block = [f":::{{tst}} {_md_escape(m['title'])}", f":id: {m['test']}", f":nodeid: {' '.join(m['nodeids'])}"]
        if verifies:
            block.append(":verifies: " + ", ".join(verifies))
        block += ["", f"`{m['file']}:{m['line']}`"]
        lines += block + [":::", ""]
    text = "\n".join(lines)
    path = os.path.join(out_dir, "tests.md")
    old = open(path).read() if os.path.exists(path) else None
    if old != text:  # rewrite only on change, so an unchanged suite does not re-read the page
        with open(path, "w") as f:
            f.write(text)


def _required_are_verified(app, env):
    from sphinx_needs.data import SphinxNeedsData
    view = SphinxNeedsData(env).get_needs_view()
    verified = {t for need in view.values() if need["type"] == "tst" for t in need["verifies"]}
    missing = sorted(n["id"] for n in view.values() if n.get("verify") == "required" and n["id"] not in verified)
    if missing:
        LOG.warning(f"{len(missing)} items must be verified and no test verifies them: {', '.join(missing)}",
                    type="corpus", subtype="verify")


LINK_TYPES = ("uses", "refines", "excepts", "upholds", "realises", "justifies", "follows_from", "assumes", "illustrates",
              "verifies")
ROOTS = ("fct", "chc")


def _level(need):
    return need["docname"].split("/", 1)[0] if need.get("docname") else None


def _links_hold(app, env):
    from sphinx_needs.data import SphinxNeedsData
    view = SphinxNeedsData(env).get_needs_view()
    bad = []
    for need in view.values():
        for link in LINK_TYPES:
            for target_id in need.get(link) or []:
                target = view.get(target_id)
                if target is None:
                    continue  # a dead link: sphinx-needs reports it
                if _level(need) == "intent" and _level(target) == "build":
                    bad.append(f"{need['id']} ({link}) names build item {target_id}: intent never depends on the build")
                if target["type"] == "rat" and link != "follows_from":
                    bad.append(f"{need['id']} ({link}) names rationale {target_id}: a rationale is never binding")
                if link == "follows_from" and need["type"] != "rat":
                    bad.append(f"{need['id']} follows from {target_id}: only a rationale follows from anything")
    followed = {t for need in view.values() for t in need.get("follows_from") or []}
    for need in view.values():
        if need["type"] in ROOTS and need["id"] not in followed:
            bad.append(f"{need['id']}: nothing follows from this {'fact' if need['type'] == 'fct' else 'choice'}")

    def reaches_root(need_id, seen):
        need = view.get(need_id)
        if need is None or need_id in seen:
            return False
        if need["type"] in ROOTS:
            return True
        return any(reaches_root(t, seen | {need_id}) for t in need.get("follows_from") or [])

    for need in view.values():
        if need["type"] == "rat" and need.get("forced") == "yes" and not reaches_root(need["id"], set()):
            bad.append(f"{need['id']} is forced but follows from no fact or choice")
    for line in sorted(bad):
        LOG.warning(line, type="corpus", subtype="links")


def _items_well_formed(app, env):
    """Read from the sources, since what sphinx-needs drops never reaches its data: one SHALL per item, and every
    option on one line."""
    import glob
    import re
    bad = []
    for path in sorted(glob.glob(os.path.join(app.srcdir, "*", "*.md"))):
        if os.sep + GENERATED + os.sep in path:
            continue
        rel = os.path.relpath(path, app.srcdir)
        text = open(path, encoding="utf-8").read()
        for m in re.finditer(r"^:::\{\w+\}[^\n]*\n(.*?)^:::$", text, re.S | re.M):
            lines = m.group(1).split("\n")
            item = next((re.match(r":id:\s*(\S+)", l).group(1) for l in lines if l.startswith(":id:")), "?")
            head = True
            for line in lines:
                if head and not line.strip():
                    head = False
                elif head and not line.startswith(":"):
                    bad.append(f"{rel}: {item}: an option continues onto a second line, which sphinx-needs drops: "
                               f"{line.strip()[:60]}")
            body = "\n".join(l for l in lines if not l.startswith(":"))
            shalls = len(re.findall(r"\bSHALL\b", body))
            if shalls > 1:
                bad.append(f"{rel}: {item} states {shalls} SHALLs: an item carries one obligation")
    for line in bad:
        LOG.warning(line, type="corpus", subtype="form")


def _rules_justified(app, env):
    """Every rule and invariant has a reason: a rationale justifies it, or the item it refines or upholds."""
    from sphinx_needs.data import SphinxNeedsData
    view = SphinxNeedsData(env).get_needs_view()
    justified = {t for need in view.values() if need["type"] == "rat" for t in need.get("justifies") or []}

    def reasoned(need_id, seen):
        if need_id in justified:
            return True
        need = view.get(need_id)
        if need is None or need_id in seen:
            return False
        return any(reasoned(p, seen | {need_id}) for p in (need.get("refines") or []) + (need.get("upholds") or []))

    listed = set()
    path = os.path.join(app.srcdir, "unjustified.txt")
    if os.path.exists(path):
        listed = {l.strip() for l in open(path, encoding="utf-8") if l.strip() and not l.startswith("#")}
    bad = []
    for need in view.values():
        if need["type"] in ("rul", "inv") and not reasoned(need["id"], frozenset()) and need["id"] not in listed:
            bad.append(f"{need['id']}: no rationale justifies it, directly or through the item it refines or upholds")
    for item in sorted(listed):
        if item not in view:
            bad.append(f"unjustified.txt lists {item}, which is not an item: take it off")
        elif reasoned(item, frozenset()):
            bad.append(f"unjustified.txt lists {item}, which now has a rationale: take it off")
    for line in sorted(bad):
        LOG.warning(line, type="corpus", subtype="rationale")


def setup(app):
    app.connect("builder-inited", _write_tests_page)
    app.connect("env-check-consistency", _required_are_verified)
    app.connect("env-check-consistency", _links_hold)
    app.connect("env-check-consistency", _items_well_formed)
    app.connect("env-check-consistency", _rules_justified)
    return {"parallel_read_safe": False, "parallel_write_safe": True}
