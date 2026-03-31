"""Run campus simulations with separate interventions and save each figure.

Scenarios included:
1) baseline (no intervention)
2) symptom-based testing only
3) periodic campus screening only
4) campus contact tracing only
5) online teaching only
6) all four interventions combined

Run:
    python examples/t05_campus_interventions_separate_runs.py
"""

from __future__ import annotations

from pathlib import Path

import covasim as cv
import pandas as pd


def make_output_dir() -> Path:
    """Create the output directory for plots and summaries."""
    outdir = Path(__file__).resolve().parent / "figures" / "campus_separate_runs"
    outdir.mkdir(parents=True, exist_ok=True)
    return outdir


def make_common_pars() -> dict:
    """Shared campus simulation parameters."""
    return dict(
        pop_type="campus",
        pop_size=5000,
        pop_infected=30,
        n_days=70,
        rand_seed=1,
    )


def make_symptomatic_testing():
    return cv.test_prob(
        symp_prob=0.10,
        asymp_prob=0.0,
        symp_quar_prob=0.35,
        asymp_quar_prob=0.0,
        start_day=3,
        label="symptomatic_testing",
    )


def make_periodic_screening():
    return cv.campus_periodic_screening(
        group_cycles=dict(
            teacher=3,
            lab=3,
            dorm=5,
            course=7,
            id_bucket=10,
        ),
        daily_capacity=1000,
        start_day=5,
        exclude_recent_days=2,
        test_delay=1,
        label="campus_screening",
    )


def make_contact_tracing():
    return cv.contact_tracing(
        trace_probs=dict(
            d=0.95,
            clu=0.90,
            clg=0.90,
            of=0.90,
            ta=0.80,
            cm=0.0,
        ),
        trace_time=dict(
            d=0,
            clu=1,
            clg=1,
            of=1,
            ta=1,
            cm=0,
        ),
        start_day=5,
        label="campus_tracing",
    )


def make_online_teaching():
    return cv.campus_online_teaching(
        start_day=25,
        end_day=45,
        dorm_change=1.20,
        community_change=0.60,
        lab_mode="reduce",
        lab_change=0.50,
        office_mode="reduce",
        office_change=0.70,
        label="online_teaching",
    )


def build_scenarios() -> list[tuple[str, list]]:
    """Return all named intervention scenarios."""
    return [
        ("baseline", []),
        ("symptomatic_testing_only", [make_symptomatic_testing()]),
        ("periodic_screening_only", [make_periodic_screening()]),
        ("contact_tracing_only", [make_contact_tracing()]),
        ("online_teaching_only", [make_online_teaching()]),
        (
            "all_four_interventions",
            [
                make_symptomatic_testing(),
                make_periodic_screening(),
                make_contact_tracing(),
                make_online_teaching(),
            ],
        ),
    ]


def summarize_sim(sim: cv.Sim, scenario_name: str) -> dict:
    """Collect a compact summary for later comparison."""
    return dict(
        scenario=scenario_name,
        cum_infections=float(sim.results["cum_infections"][-1]),
        cum_diagnoses=float(sim.results["cum_diagnoses"][-1]),
        cum_tests=float(sim.results["cum_tests"][-1]),
        peak_new_infections=float(sim.results["new_infections"].values.max()),
        peak_quarantined=float(sim.results["n_quarantined"].values.max()),
        final_r_eff=float(sim.results["r_eff"][-1]),
    )


def run_one_scenario(scenario_name: str, interventions: list, outdir: Path) -> dict:
    """Run one campus scenario and save its figure."""
    sim = cv.Sim(pars=make_common_pars(), interventions=interventions, label=scenario_name)
    sim.run()

    fig_path = outdir / f"{scenario_name}.png"
    sim.plot(
        to_plot=["new_infections", "new_diagnoses", "new_tests", "n_quarantined"],
        do_show=False,
        do_save=True,
        fig_path=str(fig_path),
    )

    summary = summarize_sim(sim, scenario_name)
    summary["figure_path"] = str(fig_path)
    print(
        f"{scenario_name}: "
        f"cum_infections={summary['cum_infections']:.0f}, "
        f"cum_diagnoses={summary['cum_diagnoses']:.0f}, "
        f"cum_tests={summary['cum_tests']:.0f}, "
        f"figure={fig_path}"
    )
    return summary


def main():
    outdir = make_output_dir()
    scenarios = build_scenarios()
    summaries = []

    print("=== Campus separate intervention runs ===")
    print(f"Output directory: {outdir}")

    for scenario_name, interventions in scenarios:
        print(f"\nRunning: {scenario_name}")
        summaries.append(run_one_scenario(scenario_name, interventions, outdir))

    summary_df = pd.DataFrame(summaries)
    summary_path = outdir / "scenario_summary.csv"
    summary_df.to_csv(summary_path, index=False, encoding="utf-8-sig")

    print("\n=== Saved figures ===")
    for row in summaries:
        print(row["figure_path"])

    print("\n=== Summary CSV ===")
    print(summary_path)

    print("\n=== Scenario metrics ===")
    print(summary_df.to_string(index=False))


if __name__ == "__main__":
    main()
