"""The pack runner needs the same guarded database fixtures as the integration tests (test schema only).

They are loaded from tests/integration/conftest.py by path, so there is one definition and no copy to keep in step.
"""

import importlib.util
from pathlib import Path

_path = Path(__file__).resolve().parents[1] / "integration" / "conftest.py"
_spec = importlib.util.spec_from_file_location("integration_conftest_for_acceptance", _path)
_module = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_module)

# re-exported so pytest registers them as fixtures of this folder
test_conn = _module.test_conn
_emptied_test_schema = _module._emptied_test_schema
test_engine = _module.test_engine
svc_conn = _module.svc_conn
