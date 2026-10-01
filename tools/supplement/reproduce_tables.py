"""Rebuild the paper tables from packaged machine-readable artifacts."""

from __future__ import annotations

import argparse
import csv
import json
import math
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
RESULTS = ROOT / "results"


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def write_csv(path: Path, rows: list[dict], fields: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)


def number(row: dict[str, str], key: str, default: float = 0.0) -> float:
    value = row.get(key, "")
    return default if value in (None, "") else float(value)


def build_table1(output: Path) -> Path:
    source = RESULTS / "calibration" / "calibration_results.json"
    data = json.loads(source.read_text(encoding="utf-8"))
    defaults = data["default_pars"]
    calibrated = data["best_pars"]
    rows = []
    for key in ["beta", "beta_layer_d", "beta_layer_cl", "beta_layer_cm"]:
        before = float(defaults[key])
        after = float(calibrated[key])
        rows.append({
            "parameter": key,
            "default": f"{before:.9g}",
            "calibrated": f"{after:.9g}",
            "change_percent": f"{100.0 * (after / before - 1.0):.3f}",
        })
    path = output / "table1_calibration.csv"
    write_csv(path, rows, ["parameter", "default", "calibrated", "change_percent"])
    return path


def build_table2(output: Path) -> Path:
    source = RESULTS / "calibration" / "sensitivity_summary.csv"
    rows = read_csv(source)
    path = output / "table2_sensitivity.csv"
    fields = list(rows[0]) if rows else []
    write_csv(path, rows, fields)
    return path


def build_table3(output: Path) -> Path:
    source = RESULTS / "policy_comparison" / "policy_summary_metrics.csv"
    rows = []
    for row in read_csv(source):
        rows.append({
            "scenario": row["scenario"],
            "strategy": row["strategy"],
            "n_runs": row["n_runs"],
            "cum_infections_mean": f"{number(row, 'cum_infections_mean'):.3f}",
            "cum_infections_std": f"{math.sqrt(max(0.0, number(row, 'cum_infections_var'))):.3f}",
            "peak_new_infections_mean": f"{number(row, 'peak_new_infections_mean'):.3f}",
            "peak_new_infections_std": f"{math.sqrt(max(0.0, number(row, 'peak_new_infections_var'))):.3f}",
            "mean_quarantined": f"{number(row, 'mean_quarantined_mean'):.3f}",
            "online_teaching_days": f"{number(row, 'teaching_restriction_days_mean'):.3f}",
            "policy_switches": f"{number(row, 'policy_switch_count_mean'):.3f}",
            "total_tests": f"{number(row, 'cum_tests_mean'):.3f}",
            "CPBU": f"{number(row, 'CPBU'):.6f}",
        })
    fields = list(rows[0]) if rows else []
    path = output / "table3_policy_comparison.csv"
    write_csv(path, rows, fields)
    return path


def build_table4(output: Path) -> Path:
    source = RESULTS / "recent_memory_ablation" / "memory_summary_metrics.csv"
    rows = []
    for row in read_csv(source):
        rows.append({
            "scenario": row["scenario"],
            "strategy": row["strategy"],
            "n_runs": row["n_runs"],
            "cum_infections_mean": f"{number(row, 'cum_infections_mean'):.3f}",
            "cum_infections_std": f"{math.sqrt(max(0.0, number(row, 'cum_infections_var'))):.3f}",
            "peak_new_infections_mean": f"{number(row, 'peak_new_infections_mean'):.3f}",
            "peak_new_infections_std": f"{math.sqrt(max(0.0, number(row, 'peak_new_infections_var'))):.3f}",
            "policy_switches": f"{number(row, 'policy_switch_count_mean'):.3f}",
            "high_intensity_days": f"{number(row, 'P3_P4_days_mean'):.3f}",
            "isolation_burden": f"{number(row, 'mean_quarantined_mean'):.3f}",
        })
    fields = list(rows[0]) if rows else []
    path = output / "table4_recent_memory_ablation.csv"
    write_csv(path, rows, fields)
    return path


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", default=str(ROOT / "reproduced_tables"))
    args = parser.parse_args()
    output = Path(args.output).resolve()
    paths = [
        build_table1(output),
        build_table2(output),
        build_table3(output),
        build_table4(output),
    ]
    print("Reproduced paper tables:")
    for path in paths:
        print(f"- {path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
