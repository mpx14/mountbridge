import importlib.machinery
import importlib.util
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent


@pytest.fixture(scope="session")
def helper():
    """Import data/mountbridge-helper (no .py extension) as a module."""
    path = str(ROOT / "data" / "mountbridge-helper")
    loader = importlib.machinery.SourceFileLoader("mountbridge_helper", path)
    spec = importlib.util.spec_from_loader(loader.name, loader)
    mod = importlib.util.module_from_spec(spec)
    loader.exec_module(mod)
    return mod
