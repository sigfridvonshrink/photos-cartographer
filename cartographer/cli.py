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

"""photos-cartographer — the single combined CLI entry point.

Dispatches to the pipeline phases: `prep` → `geotag` → `merge` (and, once folded in, `edit` — the
decision editor). Each phase keeps its own subcommands (the same surface as running it standalone via
`python -m cartographer.<phase>`). Self-documenting: with no phase, or a phase with no subcommand,
it prints a short role blurb rather than an arg-only usage line — the tool is used a few times a year,
so it explains itself.
"""
import argparse

from . import __version__, photos_1_prep, photos_2_geotag, photos_3_merge
from .editor import server as editor
from .console import server as console

OVERALL_BLURB = (
    "photos-cartographer — safely turn a raw photo dump into a calibrated, geotagged, merged library.\n\n"
    "A three-phase pipeline you run inside a workspace directory; between phases you resolve the open\n"
    "decisions in the editor, then re-plan. Every phase plans first (no mutation), and only a\n"
    "validated plan is ever executed; originals are never lost.\n\n"
    "  prep    phase 1 — organize the dump into the managed 0-6 folders (dedup, by-date, by-dest).\n"
    "  geotag  phase 2 — infer camera clocks from GPX and place photos in time + on the map.\n"
    "  merge   phase 3 — move the finalized tree into your permanent library (terminal).\n"
    "  edit    open the decision editor to resolve time / GPS / drift decisions between geotag runs.\n"
  "  console run and monitor the pipeline from a browser (live log + progress over the workspace).\n\n"
    "Run `photos-cartographer <phase>` (no subcommand) for that phase's role + commands; "
    "`photos-cartographer <phase> <cmd> --help` for argument detail."
)

# (name, module). `edit` (the decision editor) is a leaf phase — no subcommands; it runs the server.
_PHASES = (("prep", photos_1_prep), ("geotag", photos_2_geotag), ("merge", photos_3_merge),
           ("edit", editor), ("console", console))


def build_parser():
    parser = argparse.ArgumentParser(prog="photos-cartographer", description=OVERALL_BLURB,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--version", action="version", version=f"photos-cartographer {__version__}")
    phases = parser.add_subparsers(dest="phase")
    for name, mod in _PHASES:
        blurb = _phase_blurb(mod)
        p = phases.add_parser(name, description=blurb, help=blurb.splitlines()[0],
                              formatter_class=argparse.RawDescriptionHelpFormatter)
        mod.add_arguments(p)        # sets _run + _parser on p
    return parser


def _phase_blurb(mod):
    for attr in ("PREP_BLURB", "GEOTAG_BLURB", "MERGE_BLURB", "EDIT_BLURB", "CONSOLE_BLURB"):
        if hasattr(mod, attr):
            return getattr(mod, attr)
    return mod.__doc__ or ""


def main(argv=None):
    parser = build_parser()
    args = parser.parse_args(argv)
    if getattr(args, "phase", None) is None:        # no phase -> overall role blurb
        parser.print_help()
        return 0
    if hasattr(args, "command") and args.command is None:   # a phase with subcommands, none given -> its blurb
        args._parser.print_help()
        return 0
    return args._run(args)                           # leaf phase (edit) or a chosen subcommand


if __name__ == "__main__":
    import sys
    sys.exit(main())
