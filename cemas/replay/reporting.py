"""Summarize raw continuous replay worlds without changing fitted settings."""

from __future__ import annotations

import csv
from datetime import date
from pathlib import Path

import numpy as np

from ..e0.study import align_world


GROUPS = ("total", "students", "employees")
WINDOWS = {"W1": ("2020-08-17", "2020-09-06"),
           "W2": ("2020-09-07", "2020-09-25"),
           "W3": ("2020-09-26", "2020-10-30")}
LABELS = {"total": "总量", "students": "学生", "employees": "员工"}


def _plain(values):
    array = np.asarray(values, dtype=float)
    if array.ndim == 0:
        return float(array) if np.isfinite(array) else None
    return [_plain(value) for value in array]


def _band(values, observed=None):
    values = np.asarray(values, dtype=float)
    scalar = values.ndim == 1
    matrix = values[:, None] if scalar else values
    valid = np.isfinite(matrix).any(axis=0)
    result = {key: np.full(matrix.shape[1], np.nan) for key in ("q05", "q50", "q95", "mean")}
    if valid.any():
        quantiles = np.nanquantile(matrix[:, valid], [0.05, 0.5, 0.95], axis=0)
        for key, array in zip(("q05", "q50", "q95"), quantiles):
            result[key][valid] = array
        result["mean"][valid] = np.nanmean(matrix[:, valid], axis=0)
    output = {key: _plain(value[0] if scalar else value) for key, value in result.items()}
    if observed is not None:
        observed = np.asarray(observed, dtype=float)
        mask = np.isfinite(observed) & valid
        covered = ((observed >= result["q05"]) & (observed <= result["q95"]))
        output["coverage"] = float(covered[mask].mean()) if mask.any() else None
        output["coverage_days"] = int(mask.sum())
    return output


def _ratio(numerator, denominator):
    numerator, denominator = np.broadcast_arrays(np.asarray(numerator, dtype=float),
                                                np.asarray(denominator, dtype=float))
    result = np.full(numerator.shape, np.nan)
    np.divide(numerator, denominator, out=result, where=denominator > 0)
    return result


def _rolling_sum(values):
    """Seven complete days, including days across a window boundary."""
    values = np.asarray(values, dtype=float)
    result = np.full(values.shape, np.nan)
    cumulative = np.cumsum(values, axis=-1)
    if values.shape[-1] >= 7:
        result[..., 6:] = cumulative[..., 6:] - np.concatenate(
            (np.zeros_like(cumulative[..., :1]), cumulative[..., :-7]), axis=-1)
    return result


def _counts(groups, group, field):
    if group == "total":
        return np.asarray(groups["students"][field], dtype=float) + groups["employees"][field]
    return np.asarray(groups[group][field], dtype=float)


def summarize_worlds(worlds, data):
    """Align once, then retain world quantiles, reset cumulative windows and tails.

    All metrics aggregate world-level quantities. In particular, positive rates
    and allocation shares are computed per world before taking quantiles.
    """
    worlds = list(worlds)
    if not worlds:
        raise ValueError("Replay summaries require at least one world")
    dates = list(worlds[0]["dates"])
    if any(list(world["dates"]) != dates for world in worlds):
        raise ValueError("Replay worlds must have identical dates")
    if list(data["dates"])[:len(dates)] != dates:
        raise ValueError("Replay and observation dates differ")
    if any("alignment" in world for world in worlds):
        raise ValueError("summarize_worlds expects raw, unaligned worlds")
    aligned = [align_world(world, 1) for world in worlds]
    total_tests = np.asarray([_counts(world["groups"], "total", "tests") for world in aligned])
    requested = np.asarray([world["requested_tests"] for world in aligned], dtype=float)
    observed_total_tests = _counts(data["groups"], "total", "tests")[:len(dates)]
    windows = {name: np.flatnonzero([(start <= day <= end) for day in dates])
               for name, (start, end) in WINDOWS.items()}
    output = {"dates": dates, "worlds": len(worlds), "alignment": 1, "groups": {},
              "out_of_window": {"dates": aligned[0]["out_of_window"]["dates"], "groups": {}}}
    for group in GROUPS:
        positives = np.asarray([_counts(world["groups"], group, "positive") for world in aligned])
        tests = np.asarray([_counts(world["groups"], group, "tests") for world in aligned])
        obs_positive = _counts(data["groups"], group, "positive")[:len(dates)]
        obs_tests = _counts(data["groups"], group, "tests")[:len(dates)]
        residual = positives - obs_positive
        obs_share = _ratio(obs_tests, observed_total_tests)
        share = _ratio(tests, total_tests)
        obs_series = {"positive": obs_positive, "actual_tests": obs_tests,
                      "positive_7day_mean": _rolling_sum(obs_positive) / 7,
                      "positivity_7day": _ratio(_rolling_sum(obs_positive), _rolling_sum(obs_tests)),
                      "test_share": obs_share}
        series = {"positive": positives, "absolute_error": np.abs(residual),
                  "residual": residual, "actual_tests": tests,
                  "tests_difference": tests - obs_tests,
                  "positive_7day_mean": _rolling_sum(positives) / 7,
                  "positivity_7day": _ratio(_rolling_sum(positives), _rolling_sum(tests)),
                  "test_share": share, "test_share_difference": share - obs_share}
        cumulative = np.zeros_like(positives)
        obs_cumulative = np.zeros_like(obs_positive)
        window_metrics = {}
        for name, indices in windows.items():
            if not len(indices):
                continue
            model = positives[:, indices]
            obs = obs_positive[indices]
            cumulative[:, indices] = model.cumsum(axis=1)
            obs_cumulative[indices] = obs.cumsum()
            errors = model.cumsum(axis=1) - obs.cumsum()
            observed_positive = float(obs.sum())
            observed_tests = float(obs_tests[indices].sum())
            model_total = model.sum(axis=1)
            actual_tests = tests[:, indices].sum(axis=1)
            window_share = _ratio(actual_tests, total_tests[:, indices].sum(axis=1))
            observed_share = float(_ratio(observed_tests, observed_total_tests[indices].sum()))
            scalars = {
                "total_positive": model_total,
                "mean_daily_positive": model.mean(axis=1),
                "daily_mae": np.abs(model - obs).mean(axis=1),
                "cumulative_mae": np.abs(errors).mean(axis=1),
                "end_bias": model_total - observed_positive,
                "relative_end_bias": _ratio(model_total - observed_positive, observed_positive),
                "actual_tests_total": actual_tests,
                "test_total_difference": actual_tests - observed_tests,
                "test_share": window_share,
                "test_share_difference": window_share - observed_share,
                "cumulative_loss": _ratio(np.square(errors).sum(axis=1), observed_positive ** 2),
            }
            cumulative_band = _band(model.cumsum(axis=1), obs.cumsum())
            window_metrics[name] = {
                "dates": [dates[indices[0]], dates[indices[-1]]], "days": len(indices),
                "observed_positive": observed_positive, "observed_tests": observed_tests,
                "observed_test_share": _plain(observed_share),
                **{key: _band(values) for key, values in scalars.items()},
                "daily_coverage": _band(model, obs)["coverage"],
                "cumulative_coverage": cumulative_band["coverage"],
                "cumulative_positive": cumulative_band,
                "cumulative_error": _band(errors),
            }
        series["cumulative_positive"] = cumulative
        series["cumulative_error"] = cumulative - obs_cumulative
        obs_series["cumulative_positive"] = obs_cumulative
        if group == "total":
            series["requested_tests"] = requested
            series["requested_actual_difference"] = total_tests - requested
            obs_series["requested_tests"] = observed_total_tests
        output["groups"][group] = {
            "observed": {key: _plain(value) for key, value in obs_series.items()},
            "series": {key: _band(values, obs_series.get(key)) for key, values in series.items()},
            "windows": window_metrics,
        }
        tail = output["out_of_window"]["groups"][group] = {}
        for field in ("positive", "tests"):
            values = [_counts(world["out_of_window"]["groups"], group, field) for world in aligned]
            tail[field] = _band(values)
    output["out_of_window"]["requested_tests"] = _band(
        [world["out_of_window"]["requested_tests"] for world in aligned])
    return output


def _scenario_rows(summary):
    return [("fixed_w2", item) for item in summary.get("fixed_w2", [])] + [
        ("evaluation", item) for item in summary.get("scenarios", [])]


def _csv(path, rows):
    rows = list(rows)
    if not rows:
        return
    fields = list(dict.fromkeys(key for row in rows for key in row))
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)


def _tables(output, summary):
    daily, windows, tails = [], [], []
    for stage, scenario in _scenario_rows(summary):
        meta = {"stage": stage, **{key: scenario.get(key) for key in ("name", "kind", "h", "c", "recovery")}}
        metrics = scenario["metrics"]
        for group, details in metrics["groups"].items():
            for index, day in enumerate(metrics["dates"]):
                row = {**meta, "group": group, "date": day}
                row.update({"observed_" + key: values[index] for key, values in details["observed"].items()})
                for key, band in details["series"].items():
                    row.update({key + "_" + quantile: band[quantile][index]
                                for quantile in ("q05", "q50", "q95", "mean")})
                daily.append(row)
            for name, window in details["windows"].items():
                row = {**meta, "group": group, "window": name}
                for key, value in window.items():
                    if isinstance(value, dict) and isinstance(value.get("q50"), (int, float, type(None))):
                        row.update({key + "_" + q: value[q] for q in ("q05", "q50", "q95", "mean")})
                    elif not isinstance(value, (dict, list)):
                        row[key] = value
                windows.append(row)
            for index, day in enumerate(metrics["out_of_window"]["dates"]):
                row = {**meta, "group": group, "date": day}
                for key, band in metrics["out_of_window"]["groups"][group].items():
                    row.update({key + "_" + q: band[q][index] for q in ("q05", "q50", "q95", "mean")})
                tails.append(row)
    _csv(output / "daily_metrics.csv", daily)
    _csv(output / "window_metrics.csv", windows)
    _csv(output / "out_of_window.csv", tails)


def _figures(output, summary, profiles):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.dates as mdates
    import matplotlib.pyplot as plt

    plt.rcParams.update({"font.sans-serif": ["Microsoft YaHei", "SimHei", "DejaVu Sans"],
                         "axes.unicode_minus": False})
    target = output / "figures"
    target.mkdir(exist_ok=True)
    if profiles:
        fig, ax = plt.subplots(figsize=(9, 5))
        for profile in profiles:
            rows = profile.get("rows", profile.get("points", []))
            ax.errorbar([row["c"] for row in rows], [row["mean_loss"] for row in rows],
                        yerr=[row["se_loss"] for row in rows], fmt="o-", ms=3,
                        label=f"h={profile['h']:g}; c*={profile['best_c']:g}")
        ax.set(xlabel="W2 本科社区保留比例 c", ylabel="W2 累计阳性损失：均值 ± 1 SE",
               title="固定住宿方案分别选择 c；未使用 W3 选参")
        ax.legend()
        fig.tight_layout()
        fig.savefig(target / "selection.png", dpi=160)
        plt.close(fig)
    for h in sorted({item["h"] for item in summary.get("scenarios", [])}):
        scenarios = [item for item in summary["scenarios"] if item["h"] == h]
        fig, axes = plt.subplots(3, 4, figsize=(21, 11))
        for row, group in enumerate(GROUPS):
            for col, (key, label) in enumerate((("positive", "每日阳性"),
                    ("positive_7day_mean", "连续 7 日平均阳性"),
                    ("positivity_7day", "7 日阳性率"),
                    ("cumulative_positive", "窗口内累计阳性（边界重新起算）"))):
                ax = axes[row, col]
                for index, scenario in enumerate(scenarios):
                    metrics = scenario["metrics"]
                    x = [date.fromisoformat(day) for day in metrics["dates"]]
                    detail = metrics["groups"][group]
                    band = detail["series"][key]
                    color = f"C{index}"
                    label_s = f"{scenario['kind']} c={scenario['c']:g}, r={scenario['recovery']:g}"
                    ax.plot(x, np.asarray(band["q50"], dtype=float), color=color, lw=1.6, label=label_s)
                    ax.fill_between(x, np.asarray(band["q05"], dtype=float),
                                    np.asarray(band["q95"], dtype=float), color=color, alpha=.08)
                    if index == 0:
                        ax.plot(x, np.asarray(detail["observed"][key], dtype=float),
                                color="#20252c", lw=1.3, label="原始观测")
                for day in ("2020-09-07", "2020-09-26"):
                    ax.axvline(date.fromisoformat(day), color="gray", lw=.7, ls=":")
                ax.set_title(f"{LABELS[group]} · {label}")
                ax.xaxis.set_major_locator(mdates.DayLocator(interval=14))
                ax.xaxis.set_major_formatter(mdates.DateFormatter("%m-%d"))
                if row == 0 and col == 0:
                    ax.legend(fontsize=7)
        fig.suptitle(f"h={h:g} 连续重放；5/50/95 分位数为固定参数的模拟随机性范围", fontsize=15)
        fig.tight_layout(rect=(0, 0, 1, .97))
        fig.savefig(target / f"replay_h{h:g}.png", dpi=160)
        plt.close(fig)


def _number(value, digits=1):
    return "空" if value is None else f"{value:.{digits}f}"


def write_report(output, summary, profiles, data):
    """Write tables, reproducible static figures and a Chinese interpretation."""
    output = Path(output)
    output.mkdir(parents=True, exist_ok=True)
    _tables(output, summary)
    _figures(output, summary, profiles)
    lines = ["# UW 2020 连续历史重放结果", "",
             f"E0 锚点：`{summary.get('anchor_path', '')}`；β={summary.get('beta')}。",
             f"锚点 SHA256：`{summary.get('anchor_sha256', '')}`。", "",
             "基础参数、初始感染、W1 检测分配权重和零外部输入假设固定。仅用 W2 总阳性累计损失选择 c；住宿补偿不与 c 联合自由拟合。",
             "模拟连续运行，报告日期统一后移 1 天，阳性与实际检测分母同步移动；终点尾部保存在 out_of_window.csv 及逐世界记录中。", "",
             "5/50/95 分位数表示固定参数的模拟随机性范围，不是参数置信区间。W3 属于时间上的后段验证；敏感性结果不用于重选 c 或 β。", "",
             "## W2 选参", "", "| 固定住宿 h | c* | one-SE 候选 | 诊断 |",
             "|---:|---:|---|---|"]
    for profile in profiles:
        cs = profile.get("one_se_cs", [])
        diagnoses = []
        if profile["best_c"] in (0, 1):
            diagnoses.append("最优在网格边界，参数辨识不足")
        if len(cs) > 1:
            diagnoses.append("多个候选落入 one-SE 集合，难以区分")
        if profile["best_c"] > .5:
            diagnoses.append("限制期 c 高于恢复期 0.5，接触强度次序与预期不一致")
        if profile["best_c"] == 0:
            diagnoses.append("下界对照最优，未满足社区接触保留非零的机制预期")
        if profile.get("identifiable") is False and not diagnoses:
            diagnoses.append("参数辨识不足")
        lines.append(f"| {profile['h']:g} | {profile['best_c']:g} | {', '.join(f'{c:g}' for c in cs)} | {'；'.join(diagnoses) or '见完整损失曲线'} |")
    lines += ["", "one-SE 集合用于描述随机损失曲线，未替代最小均值损失的选参规则。", "",
              "![W2 选参曲线](figures/selection.png)", "", "## 分组评价", "",
              "表中总量为世界中位数 [5%, 95%]；MAE 是逐世界每日绝对误差的世界均值。落带比例按每日观测计算。", "",
              "| h | 方案 | c | 恢复比例 | 窗口 | 分组 | 观测阳性 | 模拟阳性 | 每日 MAE | 每日观测落带 |",
              "|---:|---|---:|---:|---|---|---:|---|---:|---:|"]
    for scenario in summary.get("scenarios", []):
        for window in ("W1", "W2", "W3"):
            for group in GROUPS:
                metrics = scenario["metrics"]["groups"][group]["windows"].get(window)
                if metrics is None:
                    continue
                band = metrics["total_positive"]
                count = f"{_number(band['q50'])} [{_number(band['q05'])}, {_number(band['q95'])}]"
                coverage = metrics["daily_coverage"]
                lines.append(f"| {scenario['h']:g} | {scenario['kind']} | {scenario['c']:g} | {scenario['recovery']:g} | {window} | {LABELS[group]} | {metrics['observed_positive']:g} | {count} | {_number(metrics['daily_mae']['mean'])} | {_number(100 * coverage if coverage is not None else None)}% |")
    lines += ["", "## 恢复期敏感性和解释边界", ""]
    for h in sorted({item["h"] for item in summary.get("scenarios", [])}):
        candidates = [item for item in summary["scenarios"] if item["h"] == h and
                      item.get("kind") != "fixed" and "W3" in item["metrics"]["groups"]["students"]["windows"]]
        if candidates:
            best = min(candidates, key=lambda item: item["metrics"]["groups"]["students"]["windows"]["W3"]["daily_mae"]["mean"])
            metric = best["metrics"]["groups"]["students"]["windows"]["W3"]
            lines.append(f"h={h:g}：按 W3 学生每日 MAE 的事后描述，预设恢复比例 {best['recovery']:g} 最接近原始曲线（MAE={metric['daily_mae']['mean']:.2f}）。这仅比较预设敏感性分支，不把该档位改成 W2 拟合得到的主参数。")
            main = [item for item in candidates if item["recovery"] == .5]
            if main:
                groups = main[0]["metrics"]["groups"]
                student = groups["students"]["windows"]["W3"]
                employee = groups["employees"]["windows"]["W3"]
                lines.append(f"主恢复比例 0.5 的 W3 学生期末偏差中位数 {student['end_bias']['q50']:+.1f}，员工 {employee['end_bias']['q50']:+.1f}；学生每日观测落带比例 {student['daily_coverage']:.1%}，员工 {employee['daily_coverage']:.1%}。员工偏差独立报告，不以总量吻合替代分组判断。")
        lines += ["", f"![h={h:g} 分组曲线](figures/replay_h{h:g}.png)", ""]
    observed = np.asarray(data["groups"]["students"]["positive"], dtype=float)
    peak = np.flatnonzero(observed == observed.max())
    lines += [f"原始学生日表的全期最高值为 {observed.max():g}，日期为 {', '.join(data['dates'][i] for i in peak)}；不把计划中未经核验的峰值日期或逐日单调回落叙述作为验收前提。",
              "", "接触比例和住宿补偿是模型假设；拟合 c 是给定假设下的有效参数，不能解释为历史真实依从率或单独归因于本科生活动限制。未单独重现 Sellery/Witte 整楼检疫。",
              "工程检查通过与历史解释成立分别判断。持续的 W3 偏差如实保留，没有追加外部输入、调整检测权重或重选 β。模拟到 10/30 是本轮范围选择，不表示之后没有数据，也不表示该日已核实为大规模离校起点。", "",
              f"完成世界数：{summary.get('worlds_completed', '')}；失败世界：{summary.get('failed_worlds', 0)}。失败详情保留在 summary/manifest 和失败记录中，不补换种子。", "",
              "完整指标见 [daily_metrics.csv](daily_metrics.csv)、[window_metrics.csv](window_metrics.csv)、[out_of_window.csv](out_of_window.csv)；原始逐世界输出及兼容验证见同目录 JSON/JSONL。", ""]
    (output / "report.md").write_text("\n".join(lines), encoding="utf-8")
