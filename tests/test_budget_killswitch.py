import importlib.util
import sys
from pathlib import Path
from types import ModuleType

import pytest

MAIN = Path(__file__).resolve().parent.parent / "deploy" / "budget_killswitch" / "main.py"


@pytest.fixture
def killswitch(monkeypatch):
    # Stub the cloud-only dependencies so the pure decision logic is testable offline.
    ff = ModuleType("functions_framework")
    ff.cloud_event = lambda fn: fn
    gac = ModuleType("googleapiclient")
    gac.discovery = ModuleType("googleapiclient.discovery")
    monkeypatch.setitem(sys.modules, "functions_framework", ff)
    monkeypatch.setitem(sys.modules, "googleapiclient", gac)
    monkeypatch.setitem(sys.modules, "googleapiclient.discovery", gac.discovery)
    monkeypatch.setenv("PROJECT_ID", "test-project")

    spec = importlib.util.spec_from_file_location("budget_killswitch", MAIN)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.mark.parametrize(
    ("cost", "budget", "expected"),
    [(0.10, 1.0, False), (0.99, 1.0, False), (1.0, 1.0, True), (3.5, 1.0, True), (5.0, 0, False)],
)
def test_should_disable(killswitch, cost, budget, expected):
    assert killswitch.should_disable({"costAmount": cost, "budgetAmount": budget}) is expected
