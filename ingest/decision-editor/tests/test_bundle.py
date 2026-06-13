"""Bundle integrity tests.

The committed standalone `decision-editor` must stay in sync with its source + assets, and its embedded
assets must be retrievable through the same accessors the server uses. The bundle is self-contained, so
it is loaded directly here (not via conftest, which loads the unbundled source).
"""
import importlib.machinery
import importlib.util
import os
import subprocess
import sys

DE_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
BUNDLE = os.path.join(DE_DIR, "decision-editor")
BUNDLER = os.path.join(DE_DIR, "bundle")


def _load(name, path):
    loader = importlib.machinery.SourceFileLoader(name, path)
    spec = importlib.util.spec_from_loader(name, loader)
    module = importlib.util.module_from_spec(spec)
    loader.exec_module(module)  # name != "__main__", so main() does not run
    return module


def test_bundle_in_sync():
    # Guards against a stale bundle or a hand-edit of the generated file: `./bundle --check`
    # regenerates in memory and byte-compares to the committed decision-editor.
    r = subprocess.run([sys.executable, BUNDLER, "--check"], capture_output=True, text=True)
    assert r.returncode == 0, f"bundle out of sync — run ./bundle\n{r.stdout}{r.stderr}"


def test_bundle_embeds_web_assets():
    mod = _load("decision_editor_bundled_web", BUNDLE)
    index = mod._web_asset("index.html")
    assert index and b"Decision editor" in index
    leaflet = mod._web_asset("vendor/leaflet/leaflet.js")
    assert leaflet and b"Leaflet" in leaflet
    png = mod._web_asset("vendor/leaflet/images/marker-icon.png")
    assert png and png[:8] == b"\x89PNG\r\n\x1a\n"  # PNG magic
    assert mod._web_asset("does-not-exist.txt") is None


def test_bundle_embeds_demo_fixtures():
    mod = _load("decision_editor_bundled_demo", BUNDLE)
    art = mod._load_artifacts(None)  # demo mode reads the embedded fixtures, no sibling files
    assert art["demo"] is True and art["workspace"] is None
    assert "destinations" in art["time"] and "destinations" in art["gps"]
