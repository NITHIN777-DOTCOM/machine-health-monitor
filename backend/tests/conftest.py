"""Shared fixtures. No test touches real hardware or sleeps for more than a fraction of a second."""
from __future__ import annotations

import copy
import json

import pytest

from app.config import SENSORS_PATH
from app.registry import Registry
from app.sources.simulator import load_profile
from app.ml import training
from app.ml.dataset import Dataset, Segment
from helpers import run_scenario, sim_rows


@pytest.fixture(scope="session")
def sensors_data() -> dict:
    """The real backend/config/sensors.json, parsed."""
    return json.loads(SENSORS_PATH.read_text(encoding="utf-8"))


@pytest.fixture
def registry(sensors_data) -> Registry:
    return Registry.from_dict(copy.deepcopy(sensors_data))


@pytest.fixture
def make_registry(sensors_data):
    """Registry built from a modified copy of sensors.json: make_registry(lambda d: ...)."""
    def _make(mutate=None) -> Registry:
        data = copy.deepcopy(sensors_data)
        if mutate:
            mutate(data)
        return Registry.from_dict(data)
    return _make


@pytest.fixture(scope="session")
def profile() -> dict:
    return load_profile()


@pytest.fixture
def run_sim(registry, profile):
    """run_sim(scenario, seconds, seed=0) -> (rows, device snapshots), stepped without sleeping."""
    def _run(scenario, seconds, seed=0, reg=None, **kwargs):
        return run_scenario(reg or registry, profile, scenario, seconds, seed, **kwargs)
    return _run


@pytest.fixture(scope="session")
def reg(sensors_data) -> Registry:
    """Session-wide copy of the real registry (for session-scoped fixtures)."""
    return Registry.from_dict(copy.deepcopy(sensors_data))


@pytest.fixture(scope="session")
def trained(reg):
    """(model, meta) trained once on 20 min of simulated normal data (60 trees, for speed)."""
    data = Dataset(["a", "b"], [Segment("a", sim_rows(reg, "normal", 600, 1)),
                                Segment("b", sim_rows(reg, "normal", 600, 2))])
    return training.train(data, reg, window_s=10, n_estimators=60)
