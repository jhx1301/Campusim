"""Minimal campus intervention example.

Demonstrates:
1) symptom-based testing
2) campus periodic asymptomatic screening
3) campus contact tracing
4) online teaching switch

This example assumes the following custom interventions have been added to
``covasim/interventions.py`` and exported by the package:

- ``cv.campus_periodic_screening``
- ``cv.campus_online_teaching``

Run:
    python examples/t05_campus_interventions_minimal.py
"""

import covasim as cv
import numpy as np
import pylab as pl
from pathlib import Path


def summarize_window(sim, start, end, label):
    """Print compact summary statistics for a day window."""
    start = max(0, int(start))
    end = min(sim.npts - 1, int(end))
    if end < start:
        return

    new_inf = sim.results["new_infections"].values[start:end + 1]
    new_diag = sim.results["new_diagnoses"].values[start:end + 1]
    new_tests = sim.results["new_tests"].values[start:end + 1]
    n_quar = sim.results["n_quarantined"].values[start:end + 1]

    print(
        f"{label}: days {start}-{end} "
        f"({sim.date(start)} to {sim.date(end)}), "
        f"mean_new_infections={np.mean(new_inf):.2f}, "
        f"mean_new_diagnoses={np.mean(new_diag):.2f}, "
        f"mean_new_tests={np.mean(new_tests):.2f}, "
        f"mean_n_quarantined={np.mean(n_quar):.2f}"
    )


def layer_counts_by_window(sim, start, end, layers):
    """Count transmission events by layer from the infection log."""
    counts = {layer: 0 for layer in layers}
    for entry in sim.people.infection_log:
        day = entry["date"]
        layer = entry["layer"]
        if start <= day <= end and layer in counts:
            counts[layer] += 1
    return counts


def make_output_dir():
    """Create a local directory for figures."""
    outdir = Path(__file__).resolve().parent / "figures"
    outdir.mkdir(exist_ok=True)
    return outdir


def plot_timeseries(sim, online_start, online_active_end, online_end, outdir):
    """Save a compact paper-style time-series figure."""
    dates = sim.datevec
    fig = pl.figure(figsize=(12, 7))

    ax1 = fig.add_subplot(2, 1, 1)
    ax1.plot(dates, sim.results["new_infections"].values, label="New infections", lw=2)
    ax1.plot(dates, sim.results["new_diagnoses"].values, label="New diagnoses", lw=2)
    ax1.axvspan(dates[online_start], dates[online_active_end], color="#d9edf7", alpha=0.5, label="Online teaching")
    ax1.axvline(dates[online_end], color="#aa4444", ls="--", lw=1.5, label="Restore day")
    ax1.set_title("Campus epidemic trajectory under screening, tracing, and online teaching")
    ax1.set_ylabel("People per day")
    ax1.legend()
    ax1.grid(alpha=0.3)

    ax2 = fig.add_subplot(2, 1, 2, sharex=ax1)
    ax2.plot(dates, sim.results["new_tests"].values, label="New tests", lw=2)
    ax2.plot(dates, sim.results["n_quarantined"].values, label="People in quarantine", lw=2)
    ax2.axvspan(dates[online_start], dates[online_active_end], color="#d9edf7", alpha=0.5)
    ax2.axvline(dates[online_end], color="#aa4444", ls="--", lw=1.5)
    ax2.set_ylabel("People")
    ax2.set_xlabel("Date")
    ax2.legend()
    ax2.grid(alpha=0.3)

    fig.autofmt_xdate()
    fig.tight_layout()
    figpath = outdir / "campus_interventions_timeseries.png"
    fig.savefig(figpath, dpi=200, bbox_inches="tight")
    pl.close(fig)
    return figpath


def plot_layer_bars(before_counts, during_counts, after_counts, outdir):
    """Save layer-wise transmission comparison for paper use."""
    layers = list(before_counts.keys())
    x = np.arange(len(layers))
    width = 0.25

    fig = pl.figure(figsize=(10, 5))
    ax = fig.add_subplot(1, 1, 1)
    ax.bar(x - width, [before_counts[k] for k in layers], width=width, label="Before online")
    ax.bar(x, [during_counts[k] for k in layers], width=width, label="During online")
    ax.bar(x + width, [after_counts[k] for k in layers], width=width, label="After online")
    ax.set_xticks(x)
    ax.set_xticklabels(layers)
    ax.set_ylabel("Transmission events")
    ax.set_title("Transmission events by campus layer")
    ax.legend()
    ax.grid(axis="y", alpha=0.3)

    fig.tight_layout()
    figpath = outdir / "campus_layer_transmissions.png"
    fig.savefig(figpath, dpi=200, bbox_inches="tight")
    pl.close(fig)
    return figpath


def main():
    tp = cv.test_prob(
        symp_prob=0.10,
        asymp_prob=0.0,
        symp_quar_prob=0.35,
        asymp_quar_prob=0.0,
        start_day=3,
        label="symptomatic_testing",
    )

    screen = cv.campus_periodic_screening(
        group_cycles=dict(
            teacher=3,
            lab=3,
            dorm=5,
            course=7,
            id_bucket=10,
        ),
        daily_capacity=600,
        start_day=5,
        exclude_recent_days=2,
        test_delay=1,
        label="campus_screening",
    )

    ct = cv.contact_tracing(
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

    online = cv.campus_online_teaching(
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

    sim = cv.Sim(
        pars=dict(
            pop_type="campus",
            pop_size=5000,
            pop_infected=30,
            n_days=70,
            rand_seed=1,
        ),
        interventions=[tp, screen, ct, online],
    )

    sim.run()

    online_start = sim.day(25)
    online_end = sim.day(45)
    online_active_end = online_end - 1 if online_end is not None else sim.npts - 1
    campus_layers = ["d", "clu", "clg", "of", "ta", "cm"]
    outdir = make_output_dir()

    print("\n=== Intervention schedule ===")
    print(f"Symptomatic testing starts: day 3 ({sim.date(3)})")
    print(f"Campus screening starts: day 5 ({sim.date(5)})")
    print(f"Campus tracing starts: day 5 ({sim.date(5)})")
    print(
        f"Online teaching active window: day {online_start} to day {online_active_end} "
        f"({sim.date(online_start)} to {sim.date(online_active_end)})"
    )
    print(f"Online teaching restore day: day {online_end} ({sim.date(online_end)})")

    print("\n=== Window summaries ===")
    summarize_window(sim, online_start - 7, online_start - 1, "Before online teaching")
    summarize_window(sim, online_start, online_start + 6, "Early online teaching")
    summarize_window(sim, online_active_end - 6, online_active_end, "Late online teaching")
    summarize_window(sim, online_end + 1, online_end + 7, "After online teaching")

    print("\n=== Transmission events by layer ===")
    before_counts = layer_counts_by_window(sim, 0, online_start - 1, campus_layers)
    during_counts = layer_counts_by_window(sim, online_start, online_active_end, campus_layers)
    restore_counts = layer_counts_by_window(sim, online_end, online_end, campus_layers)
    after_counts = layer_counts_by_window(sim, online_end + 1, sim.npts - 1, campus_layers)
    print(f"Before online teaching : {before_counts}")
    print(f"During online teaching : {during_counts}")
    print(f"Restore day only       : {restore_counts}")
    print(f"After online teaching  : {after_counts}")

    print("\n=== Interpretation check ===")
    print(
        "If online teaching is behaving as intended, "
        "clu/clg transmission counts during the active online-teaching window "
        "should be zero or near zero; restore-day counts may be nonzero."
    )
    print(
        f"Observed during-online classroom counts: "
        f"clu={during_counts['clu']}, clg={during_counts['clg']}"
    )
    print(
        f"Observed restore-day classroom counts: "
        f"clu={restore_counts['clu']}, clg={restore_counts['clg']}"
    )

    ts_fig = plot_timeseries(sim, online_start, online_active_end, online_end, outdir)
    layer_fig = plot_layer_bars(before_counts, during_counts, after_counts, outdir)
    print("\n=== Saved figures ===")
    print(ts_fig)
    print(layer_fig)

    print("date,new_infections,new_diagnoses,n_quarantined")
    for t in range(sim.npts):
        date = sim.date(t)
        new_inf = int(round(sim.results["new_infections"][t]))
        new_diag = int(round(sim.results["new_diagnoses"][t]))
        n_quar = int(round(sim.results["n_quarantined"][t]))
        print(f"{date},{new_inf},{new_diag},{n_quar}")


if __name__ == "__main__":
    main()
