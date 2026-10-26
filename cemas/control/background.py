"""Fixed campus contact background shared by calibration, replay and control."""

from math import isfinite

import numpy as np


def background_multipliers(config):
    """Older configurations without employee adjustments use unit multipliers."""
    values = {name: config.get(name, 1.0) for name in ("employee_cm", "employee_ta")}
    for name, value in values.items():
        if type(value) not in (int, float) or not isfinite(value) or not 0 <= value <= 1:
            raise ValueError(f"{name} must be a finite number in [0, 1]")
    return values


def employee_community(cv, multiplier):
    class EmployeeCommunity(cv.Intervention):
        """Scale employee-involving edges once after daily community regeneration."""

        def __init__(self):
            super().__init__(label="employee-community", do_plot=False)
            self.multiplier = float(multiplier)
            self.last_applied_day = None

        def initialize(self, sim=None):
            super().initialize(sim)
            if not sim["dynam_layer"]["cm"]:
                raise ValueError("Employee community background requires daily dynamic cm")
            students = np.asarray(
                sim.people.campus_registry_metadata["student_indices"], dtype=np.int64)
            self.employees = np.setdiff1d(np.arange(sim.n, dtype=np.int64), students)
            self.last_applied_day = None

        def apply(self, sim):
            if self.last_applied_day == sim.t:
                return
            self.last_applied_day = sim.t
            community = sim.people.contacts["cm"]
            mask = (np.isin(community["p1"], self.employees)
                    | np.isin(community["p2"], self.employees))
            community["beta"][mask] *= self.multiplier

    return EmployeeCommunity()
