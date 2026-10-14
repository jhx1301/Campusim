"""Private daily disease metrics, never a source of public observations."""

import numpy as np
from covasim.analysis import Analyzer

from .types import PrivateDailyMetrics, PrivateMetrics


class PrivateMetricsAnalyzer(Analyzer):
    """Collect model-day flows without reading unfinalized cumulative results."""

    def __init__(self, initial_infections: int):
        super().__init__(label="control_v1_private_metrics")
        if type(initial_infections) is not int or initial_infections < 0:
            raise ValueError("initial_infections must be a nonnegative ordinary integer")
        self.initial_infections = initial_infections
        self._records: list[PrivateDailyMetrics] = []

    def initialize(self, sim):
        super().initialize(sim)
        if sim["pop_scale"] != 1 or sim["rescale"] or sim["use_waning"] or sim["n_imports"]:
            raise ValueError("v1 metrics require unscaled, non-waning, closed population")
        if int(sim["pop_infected"]) != self.initial_infections:
            raise ValueError("initial infection count must match simulator configuration")
        self._records = []

    @property
    def records(self) -> tuple[PrivateDailyMetrics, ...]:
        return tuple(self._records)

    def apply(self, sim):
        day = int(sim.t)
        if day != len(self._records):
            raise ValueError("private metrics must record each model day exactly once")
        new = int(sim.people.flows["new_infections"])
        cumulative = (self._records[-1].cumulative_infections if self._records
                      else self.initial_infections) + new
        active = int(np.count_nonzero((sim.people.exposed | sim.people.infectious)
                                     & ~sim.people.dead))
        self._records.append(PrivateDailyMetrics(
            day, new, self.initial_infections, cumulative, active,
        ))

    def aggregate(self, start_day: int, end_day: int) -> PrivateMetrics:
        """Inclusive window; cumulative is the global count through its end."""
        if (type(start_day) is not int or type(end_day) is not int
                or not 0 <= start_day <= end_day < len(self._records)):
            raise ValueError("metrics window must contain completed model days")
        records = self._records[start_day:end_day + 1]
        return PrivateMetrics(
            start_day, end_day, sum(record.new_infections for record in records),
            self.initial_infections, records[-1].cumulative_infections,
            max(record.new_infections for record in records), records[-1].active_infections,
        )
