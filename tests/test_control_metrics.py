"""Private flow aggregation and reset checks."""

from dataclasses import FrozenInstanceError
from types import SimpleNamespace

import numpy as np
import pytest

from cemas.control.metrics import PrivateMetricsAnalyzer


class FakeSim(dict):
    def __init__(self):
        super().__init__(pop_scale=1, rescale=False, use_waning=False, n_imports=0, pop_infected=3)
        self.t = 0
        self.people = SimpleNamespace(
            flows={"new_infections": 0}, exposed=np.array([True, False, False]),
            infectious=np.array([False, True, False]), dead=np.array([False, False, False]),
        )


def test_daily_flow_window_aggregation_and_initial_infections_counted_once():
    sim = FakeSim()
    analyzer = PrivateMetricsAnalyzer(3)
    analyzer.initialize(sim)
    for day, new in enumerate((2, 4, 1)):
        sim.t = day
        sim.people.flows["new_infections"] = new
        analyzer.apply(sim)
    all_days = analyzer.aggregate(0, 2)
    assert all_days.new_infections == 7
    assert all_days.initial_infections == 3 and all_days.cumulative_infections == 10
    assert all_days.peak_daily_infections == 4 and all_days.terminal_active_infections == 2
    last = analyzer.aggregate(2, 2)
    assert last.new_infections == 1 and last.cumulative_infections == 10
    with pytest.raises(FrozenInstanceError):
        analyzer.records[0].new_infections = 99
    with pytest.raises(ValueError):
        analyzer.apply(sim)
    with pytest.raises(ValueError):
        analyzer.aggregate(0, 3)
    analyzer.initialize(sim)
    assert analyzer.records == ()
    sim.t = 0
    sim.people.flows["new_infections"] = 0
    analyzer.apply(sim)
    assert analyzer.records[0].cumulative_infections == 3


@pytest.mark.parametrize("key,value", [("pop_scale", 2), ("rescale", True), ("use_waning", True), ("n_imports", 1), ("pop_infected", 4)])
def test_private_metric_protocol_assumptions_are_checked(key, value):
    sim = FakeSim()
    sim[key] = value
    with pytest.raises(ValueError):
        PrivateMetricsAnalyzer(3).initialize(sim)
