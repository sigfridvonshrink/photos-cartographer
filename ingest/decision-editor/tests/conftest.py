import os
import sys
import importlib.machinery
import importlib.util

# The decision-editor server is an extensionless executable (`ingest/decision-editor/serve`), stdlib
# only and independent of the pipeline modules. Load it once here — exactly as ingest/tests/conftest.py
# loads the pipeline scripts — under a stable name so every test file's `import decision_editor_serve`
# returns the same instance (matters for the Handler class attribute the HTTP tests toggle).
_DE_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))


def _load_once(module_name, filename):
    if module_name not in sys.modules:
        path = os.path.join(_DE_DIR, filename)
        loader = importlib.machinery.SourceFileLoader(module_name, path)
        spec = importlib.util.spec_from_loader(module_name, loader)
        module = importlib.util.module_from_spec(spec)
        sys.modules[module_name] = module
        loader.exec_module(module)
    return sys.modules[module_name]


_load_once("decision_editor_serve", "serve")
