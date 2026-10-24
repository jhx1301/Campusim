"""Reproduce this overview from the archived UW data, without network access.

Run from any directory with the project's Python environment. CSV exports use
UTF-8 BOM for Excel. Rolling statistics require seven observed calendar days.
"""

import hashlib
import json
from pathlib import Path
import sys

import matplotlib

matplotlib.use("Agg")
import matplotlib.dates as mdates
from matplotlib import font_manager
import matplotlib.pyplot as plt
from matplotlib.ticker import PercentFormatter, StrMethodFormatter
import pandas as pd


OUTPUT = Path(__file__).resolve().parent
ROOT = OUTPUT.parents[1]
sys.path.insert(0, str(ROOT.parents[1]))
from research.historical_epidemics.scripts.normalizers import normalize


def main():
    catalog = json.loads((ROOT / "data/catalog.json").read_text(encoding="utf-8"))
    manifest = json.loads((ROOT / "data/download_manifest.json").read_text(encoding="utf-8"))
    datasets = {row["id"]: row for row in catalog["datasets"]}
    for name in ("uw_madison_2020", "uw_madison_2021_spring", "bigten_raw"):
        path = ROOT / "data" / datasets[name]["observations_file"]
        assert hashlib.sha256(path.read_bytes()).hexdigest() == datasets[name]["sha256"], name
    for row in manifest:
        if row["file"].startswith("uw_madison"):
            path = ROOT / "data/raw" / row["file"]
            assert hashlib.sha256(path.read_bytes()).hexdigest() == row["sha256"], path

    source = pd.read_csv(ROOT / "data/observations/uw_madison_2020.csv.gz", keep_default_na=False)
    assert len(source) == 548
    assert source["value"].notna().all()
    assert source["quality"].eq("observed").all()
    assert source["observation_scope"].eq("on_campus_testing").all()
    keys = ["date_start", "population_group", "observation_scope", "metric"]
    assert not source.duplicated(keys).any()
    parsed = pd.DataFrame(normalize("uw_madison_2020", (ROOT / "data/raw/uw_madison_2020.html").read_bytes()))
    columns = keys + ["date_end", "time_basis", "frequency", "value", "unit", "quality", "source_locator", "raw_value"]
    pd.testing.assert_frame_equal(
        source[columns].sort_values(keys).reset_index(drop=True),
        parsed[columns].sort_values(keys).reset_index(drop=True),
    )
    spring = pd.read_csv(ROOT / "data/observations/uw_madison_2021_spring.csv.gz")
    overlap = source.merge(spring, on=keys, suffixes=("_2020", "_spring"), validate="one_to_one")
    assert len(overlap) == 548 and overlap.value_2020.eq(overlap.value_spring).all()

    wide = source.pivot(index="date_start", columns=["population_group", "metric"], values="value").sort_index()
    dates = pd.to_datetime(wide.index)
    assert dates.equals(pd.date_range("2020-08-17", "2020-12-31", name="date_start"))
    daily = pd.DataFrame({"date": dates.strftime("%Y-%m-%d")})
    for group in ("students", "employees"):
        positive = wide[group]["new_positive_tests"].reset_index(drop=True)
        tests = wide[group]["new_tests"].reset_index(drop=True)
        assert ((positive >= 0) & (positive <= tests)).all()
        daily[f"{group}_positive_tests"] = positive
        daily[f"{group}_tests"] = tests
        daily[f"{group}_positivity_pct"] = 100 * positive / tests.replace(0, float("nan"))
        daily[f"{group}_positive_7d_mean"] = positive.rolling(7).mean()
        daily[f"{group}_tests_7d_mean"] = tests.rolling(7).mean()
        daily[f"{group}_positivity_7d_pct"] = 100 * positive.rolling(7).sum() / tests.rolling(7).sum().replace(0, float("nan"))
    daily.to_csv(OUTPUT / "daily.csv", index=False, encoding="utf-8-sig", float_format="%.6f")

    monthly = []
    for month, frame in daily.groupby(daily.date.str[:7]):
        for group in ("students", "employees"):
            positive = int(frame[f"{group}_positive_tests"].sum())
            tests = int(frame[f"{group}_tests"].sum())
            monthly.append(dict(month=month, population_group=group, days_observed=len(frame), positive_tests=positive, tests=tests, positivity_pct=100 * positive / tests))
    pd.DataFrame(monthly).to_csv(OUTPUT / "monthly.csv", index=False, encoding="utf-8-sig", float_format="%.6f")

    available = {font.name for font in font_manager.fontManager.ttflist}
    plt.rcParams.update({
        "font.family": next((name for name in ("Microsoft YaHei", "Noto Sans CJK SC", "SimHei") if name in available), "DejaVu Sans"),
        "font.size": 10,
        "axes.unicode_minus": False,
        "axes.spines.top": False,
        "axes.spines.right": False,
        "axes.edgecolor": "#cbd5e1",
        "axes.labelcolor": "#334155",
        "text.color": "#172033",
        "xtick.color": "#475569",
        "ytick.color": "#475569",
        "svg.fonttype": "none",
    })
    fig, axes = plt.subplots(3, 2, figsize=(15, 11.2), sharex=True)
    fig.patch.set_facecolor("#f8fafc")
    fig.subplots_adjust(left=.075, right=.97, top=.845, bottom=.16, hspace=.22, wspace=.20)
    fig.text(.075, .965, "UW–Madison 2020 秋季：检测与阳性变化", fontsize=23, weight="bold")
    fig.text(.075, .925, "2020-08-17 至 12-31 · 连续 137 天 · 官方校内检测日表 · 学生与员工分别展示", fontsize=12, color="#475569")
    fig.text(.096, .885, "每日记录", fontsize=10, color="#475569")
    fig.text(.220, .885, "7 日移动平均（向前回看）", fontsize=10, color="#475569")
    fig.add_artist(plt.Line2D([.075, .088], [.891, .891], transform=fig.transFigure, color="#93c5fd", linewidth=6, alpha=.8))
    fig.add_artist(plt.Line2D([.190, .212], [.891, .891], transform=fig.transFigure, color="#1e40af", linewidth=2.5))
    groups = (("students", "学生", "#2563eb"), ("employees", "员工", "#0f766e"))
    for col, (group, title, color) in enumerate(groups):
        positive = daily[f"{group}_positive_tests"]
        tests = daily[f"{group}_tests"]
        rate = 100 * positive.sum() / tests.sum()
        axes[0, col].set_title(f"{title}  |  阳性 {positive.sum():,} 次 / 检测 {tests.sum():,} 次 / 全期 {rate:.2f}%", loc="left", fontsize=12, pad=13, weight="bold", color=color)
        for row, metric, mean_metric in ((0, "positive_tests", "positive_7d_mean"), (1, "tests", "tests_7d_mean")):
            ax = axes[row, col]
            ax.bar(dates, daily[f"{group}_{metric}"], width=.9, color=color, alpha=.30, zorder=2)
            ax.plot(dates, daily[f"{group}_{mean_metric}"], color=color, linewidth=2, zorder=3)
        axes[2, col].plot(dates, daily[f"{group}_positivity_7d_pct"], color=color, linewidth=2)
        axes[2, col].fill_between(dates, daily[f"{group}_positivity_7d_pct"], color=color, alpha=.10)
        axes[2, col].yaxis.set_major_formatter(PercentFormatter(xmax=100, decimals=0 if group == "students" else 1))
        for row, label in enumerate(("每日阳性（次）", "每日检测（次）", "7 日检测阳性率")):
            ax = axes[row, col]
            ax.set_ylabel(label)
            ax.set_facecolor("white")
            ax.set_axisbelow(True)
            ax.grid(axis="y", color="#e2e8f0", linewidth=.7)
            ax.axvspan(pd.Timestamp("2020-09-10"), pd.Timestamp("2020-09-26"), color="#f59e0b", alpha=.10, linewidth=0)
            ax.set_ylim(bottom=0)
            ax.set_xlim(dates.min() - pd.Timedelta(days=1), dates.max() + pd.Timedelta(hours=12))
            if row < 2:
                ax.yaxis.set_major_formatter(StrMethodFormatter("{x:,.0f}"))
        axes[2, col].set_xticks(pd.to_datetime(["2020-08-17", "2020-09-01", "2020-10-01", "2020-11-01", "2020-12-01", "2020-12-31"]))
        axes[2, col].xaxis.set_major_formatter(mdates.DateFormatter("%m-%d"))
        axes[2, col].set_xlabel("日期（2020 年）")
        peak = positive.idxmax()
        axes[0, col].annotate(
            f"{dates[peak]:%m-%d}：{positive.iloc[peak]} 次",
            xy=(dates[peak], positive.iloc[peak]), xytext=(12, 8), textcoords="offset points", fontsize=9, color=color,
        )
        axes[0, col].set_ylim(top=positive.max() * 1.25)
    fig.text(.075, .100, "浅橙区域：公告安排的暂停相关线下集体授课时段（09-10 至 09-25）；09-14 起转远程。", fontsize=10, color="#92400e")
    fig.text(.075, .074, "7 日阳性率 = 最近 7 天阳性次数之和 ÷ 检测次数之和；前 6 天不计算完整 7 日指标，零检测分母留空。", fontsize=10, color="#475569")
    fig.text(.075, .048, "阳性检测次数不等于真实感染人数；检测地点不代表居住地。两列纵轴分别取值，政策标记仅用于时间参照。", fontsize=10, color="#475569")
    fig.text(.075, .022, "数据：research/historical_epidemics/data/observations/uw_madison_2020.csv.gz  |  日表求和，与原网页 Total 分别保留", fontsize=9, color="#64748b")
    for extension in ("png", "svg"):
        fig.savefig(OUTPUT / f"overview.{extension}", dpi=180, facecolor=fig.get_facecolor())
    plt.close(fig)

    exported = pd.read_csv(OUTPUT / "daily.csv")
    assert len(exported) == 137
    for group in ("students", "employees"):
        assert exported[f"{group}_positive_tests"].sum() == daily[f"{group}_positive_tests"].sum()
        assert exported[f"{group}_tests"].sum() == daily[f"{group}_tests"].sum()
        assert exported[f"{group}_positivity_7d_pct"].iloc[:6].isna().all()
        zero_tests = exported[f"{group}_tests"].eq(0)
        assert exported.loc[zero_tests, f"{group}_positivity_pct"].isna().all()
    print("Verified archived hashes, all 548 raw-source observations, continuous dates, snapshot overlap, and 137 exported daily rows.")
    print(pd.DataFrame(monthly).to_string(index=False))


if __name__ == "__main__":
    main()
