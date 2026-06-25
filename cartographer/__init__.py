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

"""cartographer — safe digiKam/Immich photo ingestion + GPS/time calibration + merge.

The three phases (prep / geotag / merge) plus the shared utilities, packaged so they can be
shipped as self-contained zipapp executables. Each phase module exposes `main()`.
"""

# Source sentinel only. Release builds inject the git tag here via `tools/build-pyz --version`,
# rewriting it in the built artifact alone — the source tree keeps this placeholder (see AGENTS.md
# "Releases"). A released binary's `--version` reports the tag, e.g. 1.4.0, not this value.
__version__ = "0.1.0"
