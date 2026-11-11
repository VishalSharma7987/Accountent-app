"""The fast default run must never need a database; database tests must be marked `integration`."""

import re
from pathlib import Path

TESTS = Path(__file__).resolve().parents[1]
DB_FIXTURES = ("test_conn", "clean_db")


def test_every_integration_test_module_is_marked_integration():
    modules = sorted((TESTS / "integration").glob("test_*.py"))
    assert modules, "no integration test modules found"
    unmarked = [m.name for m in modules if "pytestmark = pytest.mark.integration" not in m.read_text(encoding="utf-8")]
    assert unmarked == []


def test_tests_outside_the_integration_folder_never_use_the_database_fixtures():
    offenders = []
    for path in TESTS.rglob("test_*.py"):
        if "integration" in path.relative_to(TESTS).parts or path.name == Path(__file__).name:
            continue
        text = path.read_text(encoding="utf-8")
        if any(re.search(rf"def test_\w+\([^)]*\b{fixture}\b", text) for fixture in DB_FIXTURES):
            offenders.append(path.name)
    assert offenders == []


def test_default_pytest_run_excludes_integration_tests():
    ini = (TESTS.parent / "pyproject.toml").read_text(encoding="utf-8")
    assert "-m 'not integration'" in ini
    assert "--strict-markers" in ini
