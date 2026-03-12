"""Minimal campus-style example:
1) symptom-based testing
2) periodic asymptomatic screening with daily capacity
3) contact tracing
4) vaccination

Run:
    python examples/t05_test_trace_vaccinate_minimal.py
"""

import covasim as cv
import numpy as np


class periodic_asymptomatic_screening(cv.Intervention):
    """Screen asymptomatic people at a fixed cadence, with daily throughput limits."""

    def __init__(
        self,
        interval_days=7,
        daily_capacity=None,
        start_day=0,
        end_day=None,
        sensitivity=1.0,
        loss_prob=0.0,
        test_delay=0,
        **kwargs,
    ):
        super().__init__(**kwargs)
        self.interval_days = int(interval_days)
        self.daily_capacity = daily_capacity
        self.start_day = start_day
        self.end_day = end_day
        self.sensitivity = sensitivity
        self.loss_prob = loss_prob
        self.test_delay = int(test_delay)
        self.last_screened = None

    def initialize(self, sim):
        super().initialize(sim)
        self.start_day = sim.day(self.start_day)
        self.end_day = sim.day(self.end_day) if self.end_day is not None else None
        self.last_screened = np.full(sim["pop_size"], -10**9, dtype=np.int32)
        return

    def apply(self, sim):
        t = sim.t
        if t < self.start_day:
            return
        if self.end_day is not None and t > self.end_day:
            return

        if self.daily_capacity is None:
            n_tests = int(np.ceil(sim["pop_size"] / self.interval_days))
        else:
            n_tests = int(self.daily_capacity)
        if n_tests <= 0:
            return

        eligible = np.where(
            (~sim.people.dead)
            & (~sim.people.diagnosed)
            & (~sim.people.symptomatic)
        )[0]
        if len(eligible) == 0:
            return

        due_mask = (t - self.last_screened[eligible]) >= self.interval_days
        due = eligible[due_mask]
        if len(due) == 0:
            return

        # Fairness rule: prioritize people who were screened longest ago.
        order = np.argsort(self.last_screened[due], kind="stable")
        test_inds = due[order[: min(n_tests, len(due))]]

        sim.people.test(
            test_inds,
            test_sensitivity=self.sensitivity,
            loss_prob=self.loss_prob,
            test_delay=self.test_delay,
        )
        self.last_screened[test_inds] = t
        sim.results["new_tests"][t] += len(test_inds) * sim["pop_scale"] / sim.rescale_vec[t]
        return test_inds


def main():
    # 1) Define interventions
    # Symptomatic testing stays on (asymptomatic is handled by scheduled screening below).
    tp = cv.test_prob(
        symp_prob=0.12,
        asymp_prob=0.0,
        symp_quar_prob=0.35,
        asymp_quar_prob=0.0,
        start_day=5,
    )
    # Campus-style asymptomatic screening:
    # target ~7-day cadence with a daily cap (cannot finish everyone in one day).
    asymp_screen = periodic_asymptomatic_screening(
        interval_days=7,
        daily_capacity=1200,
        start_day=5,
        test_delay=1,
        label="asymptomatic_screening",
    )
    ct = cv.contact_tracing(
        trace_probs=dict(h=0.9, s=0.5, w=0.5, c=0.2),
        trace_time=dict(h=0, s=1, w=1, c=2),
        start_day=7,
    )
    vx = cv.vaccinate_prob(
        vaccine="pfizer",
        days=[20, 35, 50],
        prob=0.10,
    )

    # 2) Build and run simulation
    sim = cv.Sim(
        pars=dict(
            pop_type="hybrid",
            pop_size=8000,
            pop_infected=80,
            n_days=70,
            rand_seed=1,
        ),
        interventions=[tp, asymp_screen, ct, vx],
    )
    sim.run()

    # 3) Print daily stocks requested by user
    print("date,n_quarantined,n_isolated,n_diagnosed")
    for t in range(sim.npts):
        date = sim.date(t)
        n_quar = int(round(sim.results["n_quarantined"][t]))
        n_iso = int(round(sim.results["n_isolated"][t]))
        n_diag = int(round(sim.results["n_diagnosed"][t]))
        print(f"{date},{n_quar},{n_iso},{n_diag}")


if __name__ == "__main__":
    main()
