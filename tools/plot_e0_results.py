"""Visualize a completed E0 run without rerunning or changing the experiment."""

import argparse
import csv
import hashlib
import html
import json
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.dates as mdates
import matplotlib.pyplot as plt
import numpy as np


BLUE, ORANGE, RED = "#2474ab", "#e69b38", "#c34c54"
LABELS = {"main": "主设置 I0=30 / symp=80", "i0_10": "I0=10",
          "i0_100": "I0=100", "symp20": "symp=20", "symp200": "symp=200"}
METRICS = {"cumulative": "累计损失", "weekly": "周总量损失"}


def primary(case):
    return next(e for e in case["evaluations"] if e["is_primary"])


def audit(root, summary, manifest):
    """Check frozen artifacts and independently reconstruct evaluation summaries."""
    hashes = {}
    for name, expected in manifest["artifacts"].items():
        actual = hashlib.sha256((root / name).read_bytes()).hexdigest()
        if actual != expected:
            raise ValueError(f"Artifact hash mismatch: {name}")
        hashes[name] = actual
    records = [json.loads(line) for line in
               (root / "worlds_evaluation.jsonl").read_text(encoding="utf-8").splitlines()]
    checks = 0
    for case in summary["cases"]:
        for e in case["evaluations"]:
            selected = [r for r in records if r["case"] == case["name"] and r["beta"] == e["beta"]]
            seeds = [r["seed"] for r in selected]
            if len(seeds) != e["worlds"] or set(seeds) != set(manifest["config"]["evaluation_seeds"]):
                raise ValueError("Evaluation seed/count mismatch")
            for group in ("students", "employees", "total"):
                values = []
                for r in selected:
                    groups = r["world"]["groups"]
                    raw = (np.array(groups["students"]["positive"]) + groups["employees"]["positive"]
                           if group == "total" else np.array(groups[group]["positive"]))
                    shift = e["alignment"]
                    values.append(np.r_[np.zeros(shift), raw][:len(raw)])
                values = np.array(values)
                for key, array in (("positive_daily", values),
                                   ("positive_cumulative", values.cumsum(axis=1)),
                                   ("positive_weekly", values.reshape(len(values), -1, 7).sum(axis=2))):
                    quantiles = np.quantile(array, [0.05, 0.5, 0.95], axis=0)
                    np.testing.assert_allclose(quantiles, [e["groups"][group][key][q]
                                                         for q in ("q05", "q50", "q95")])
                    checks += 1
            losses = [next(x[e["selection_metric"]] for x in r["losses"]
                           if x["alignment"] == e["alignment"]) for r in selected]
            np.testing.assert_allclose([np.mean(losses), np.std(losses, ddof=1)/np.sqrt(len(losses))],
                                       [e["evaluation_loss"]["mean"], e["evaluation_loss"]["se"]])
    return {"artifact_sha256": hashes, "evaluation_records": len(records),
            "reconstructed_quantile_sets": checks,
            "evaluation_loss_checks": sum(len(c["evaluations"]) for c in summary["cases"])}


def band(ax, x, curve, color=BLUE, label="模拟中位数"):
    ax.fill_between(x, curve["q05"], curve["q95"], color=color, alpha=0.17,
                    label="随机世界 5–95% 分位带")
    ax.plot(x, curve["q50"], color=color, lw=2, label=label)


def observed(ax, x, values):
    ax.plot(x, values, "o-", color="#252d38", ms=3.5, lw=1.2, label="观测")


def dates_axis(ax):
    ax.xaxis.set_major_locator(mdates.DayLocator(interval=4))
    ax.xaxis.set_major_formatter(mdates.DateFormatter("%m-%d"))
    ax.set_xlabel("2020 年日期")


def save(fig, out, name, title, note):
    fig.suptitle(title, fontsize=17, fontweight="bold", y=0.99)
    fig.text(0.02, 0.015, note, fontsize=9, color="#505967")
    fig.tight_layout(rect=(0, 0.05, 1, 0.95), h_pad=2.2)
    for ext in ("png", "pdf"):
        fig.savefig(out / f"{name}.{ext}", dpi=180, facecolor="white")
    plt.close(fig)


def figures(s, out):
    dates = np.array(s["dates"], dtype="datetime64[D]")
    main = next(c for c in s["cases"] if c["name"] == "main")
    e = primary(main)
    obs = s["observed"]
    g = e["groups"]["total"]
    fig, axes = plt.subplots(2, 2, figsize=(13, 8))
    for ax, key, obs_key, title in (
        (axes[0, 0], "positive_daily", "positive", "每日阳性数"),
        (axes[0, 1], "positive_cumulative", "cumulative_positive", "累计阳性数")):
        band(ax, dates, g[key]); observed(ax, dates, obs["total"][obs_key])
        dates_axis(ax); ax.set_title(title); ax.set_ylabel("阳性检测数"); ax.legend(fontsize=8)
    ax = axes[1, 0]
    weekly = np.array(obs["total"]["positive"]).reshape(-1, 7).sum(axis=1)
    x = np.arange(3)
    q = g["positive_weekly"]
    ax.bar(x - .18, weekly, .36, color="#374151", label="观测")
    ax.bar(x + .18, q["q50"], .36, color=BLUE, label="模拟中位数")
    ax.errorbar(x + .18, q["q50"], yerr=[np.array(q["q50"])-q["q05"],
                np.array(q["q95"])-q["q50"]], fmt="none", color=BLUE, capsize=4)
    ax.set_xticks(x, ["08-17～08-23", "08-24～08-30", "08-31～09-06"])
    ax.set_title("三个完整周的总量"); ax.set_ylabel("阳性检测数"); ax.legend(fontsize=8)
    ax = axes[1, 1]
    residual = np.array(g["daily_residual"])
    ax.bar(dates, residual, color=np.where(residual >= 0, BLUE, RED))
    ax.axhline(0, color="black", lw=.8); dates_axis(ax)
    ax.set_title("每日残差：模拟中位数 − 观测"); ax.set_ylabel("阳性检测数之差")
    save(fig, out, "01_main_fit", f"E0 主设置 | β={e['beta']:.5f} · 日期后移 {e['alignment']} 天 · 累计目标",
         f"W1 样本内拟合；{e['worlds']} 个独立评估世界；分位带仅表示固定参数下的模拟随机性，不包含参数不确定性。")

    fig, axes = plt.subplots(3, 3, figsize=(15, 10))
    for row, (group, label) in enumerate((("total", "总计"), ("students", "学生"), ("employees", "员工"))):
        for col, (key, obs_key, title) in enumerate((("positive_daily", "positive", "每日阳性数"),
                ("positive_cumulative", "cumulative_positive", "累计阳性数"),
                ("positivity_daily", "positivity", "每日阳性率"))):
            ax = axes[row, col]
            curve = e["groups"][group][key]
            scale = 100 if col == 2 else 1
            band(ax, dates, {k: np.array(v, dtype=float)*scale for k, v in curve.items()})
            observed(ax, dates, np.array(obs[group][obs_key], dtype=float)*scale)
            ax.set_title(f"{label} · {title}"); dates_axis(ax)
            ax.set_ylabel("%" if col == 2 else "阳性检测数")
            if row == 0 and col == 0:
                ax.legend(fontsize=8)
    save(fig, out, "02_group_diagnostics", "分组诊断 | 总量接近时仍需检查学生与员工",
         "各子图使用独立纵轴；零检测日的阳性率留空；各组中位数之和不一定等于总计中位数。")

    fig, axes = plt.subplots(2, 3, figsize=(15, 8))
    for row, metric in enumerate(("cumulative", "weekly")):
        for col, alignment in enumerate((0, 1, 2)):
            ax = axes[row, col]
            p = next(p for p in main["profiles"]["fit"] if p["metric"] == metric and p["alignment"] == alignment)
            for stage, color, label in (("scan", "#a2a9b1", "粗扫描 / 20 世界"), ("fit", BLUE, "精细拟合 / 40 世界")):
                profile = next(p for p in main["profiles"][stage] if p["metric"] == metric and p["alignment"] == alignment)
                pts = sorted(profile["points"], key=lambda pt: pt["beta"])
                ax.errorbar([pt["beta"] for pt in pts], [pt["mean_loss"] for pt in pts],
                            yerr=[pt["se_loss"] for pt in pts], fmt="o-", ms=3, lw=1, color=color,
                            alpha=.8, label=label)
            chosen = [pt for pt in p["points"] if pt["in_one_se"]]
            ax.scatter([pt["beta"] for pt in chosen], [pt["mean_loss"] for pt in chosen],
                       color=ORANGE, s=28, zorder=5, label="one-SE 集合")
            ax.axvline(p["best_beta"], color=RED, ls="--", lw=1)
            ax.axhline(p["one_se_threshold"], color=ORANGE, ls=":", lw=1)
            ax.set_yscale("log"); ax.set_title(f"{METRICS[metric]} · 后移 {alignment} 天 · β={p['best_beta']:.5f}")
            ax.set_xlabel("β"); ax.set_ylabel("平均损失 ± 1 SE（对数轴）")
            if row == 0 and col == 0:
                ax.legend(fontsize=7)
    save(fig, out, "03_beta_profiles", "主设置的 β 损失剖面 | 每种日期偏移与目标分别选参",
         "累计与周损失具有不同尺度，不应直接比较数值大小；one-SE 是描述性候选集合，不是参数置信区间。")

    cases = s["cases"]
    fig, axes = plt.subplots(2, 2, figsize=(14, 9))
    for row, metric in enumerate(("cumulative", "weekly")):
        ax = axes[row, 0]
        for alignment, color in zip((0, 1, 2), (BLUE, ORANGE, RED)):
            values = [next(e["beta"] for e in c["evaluations"] if e["alignment"] == alignment
                           and e["selection_metric"] == metric) for c in cases]
            ax.plot(range(len(cases)), values, "o-", color=color, label=f"后移 {alignment} 天")
        ax.set_xticks(range(len(cases)), [LABELS[c["name"]] for c in cases], rotation=12)
        ax.set_title(f"{METRICS[metric]} · 各情景重新选择 β"); ax.set_ylabel("β"); ax.legend(fontsize=8)
        ax = axes[row, 1]
        matrix = np.array([[next(e["evaluation_loss"]["mean"] for e in c["evaluations"]
                    if e["alignment"] == a and e["selection_metric"] == metric) for a in (0, 1, 2)] for c in cases])
        ax.imshow(matrix, cmap="YlOrRd", aspect="auto")
        for (i, j), value in np.ndenumerate(matrix):
            ax.text(j, i, f"{value:.3f}", ha="center", va="center",
                    color="white" if value > (matrix.min()+matrix.max())/2 else "#252d38")
        ax.set_yticks(range(len(cases)), [LABELS[c["name"]] for c in cases])
        ax.set_xticks(range(3), ["后移 0 天", "后移 1 天", "后移 2 天"])
        ax.set_title(f"{METRICS[metric]} · 独立世界平均损失（越低越好）")
    save(fig, out, "04_sensitivity", "敏感性分析 | 初始感染人数、检测权重、日期偏移",
         "symp 是实验中的症状检测相对权重，并非检测概率；两行热图分别着色；情景间差异不等同于因果效应。")

    fig, axes = plt.subplots(2, 2, figsize=(14, 8))
    ax = axes[0, 0]
    observed(ax, dates, obs["total"]["positive"])
    ax.plot(dates, g["positive_daily"]["q50"], color=BLUE, lw=2, label="主设置模拟中位数")
    for name, label, color in (("persistence", "首周恒定阳性率", ORANGE), ("fixed_growth", "首周固定增长率", RED)):
        ax.plot(dates, s["baselines"][name]["positive_daily"], color=color, ls="--", label=label)
    ax.axvspan(dates[0], dates[6], color="#9ca3af", alpha=.12)
    ax.set_title("内部基线比较：灰区为基线初始化周"); dates_axis(ax); ax.legend(fontsize=8)
    ax = axes[0, 1]
    vals = [s["baselines"][name]["comparison_daily_mse"] for name in ("persistence", "fixed_growth")]
    vals.append(e["baseline_comparison"]["comparison_daily_mse"])
    bars = ax.bar(["首周恒定阳性率", "首周固定增长率", "主设置"], vals, color=[ORANGE, RED, BLUE])
    ax.bar_label(bars, fmt="%.1f"); ax.set_ylim(0, max(vals)*1.2)
    ax.set_title("08-24～09-06 每日 MSE（模拟取跨世界平均）")
    ax = axes[1, 0]
    for group, label, color in (("students", "学生", BLUE), ("employees", "员工", ORANGE)):
        ax.plot(dates, obs[group]["tests"], "o-", color=color, ms=3, label=f"{label}观测")
        ax.plot(dates, e["groups"][group]["tests_daily"]["q50"], "--", color=color, label=f"{label}模拟中位数")
    dates_axis(ax); ax.set_title("检测量分配与日期偏移"); ax.set_ylabel("每日检测数"); ax.legend(fontsize=8)
    ax = axes[1, 1]
    band(ax, dates, e["r_eff"]); ax.axhline(1, color=RED, ls="--")
    dates_axis(ax); ax.set_title("引擎有效再生数 R_eff（模拟原始日期）")
    ax.set_ylabel("R_eff"); ax.legend(fontsize=8)
    save(fig, out, "05_baselines_and_checks", "基线与机制诊断 | 结果解释的边界",
         "β 使用全部 21 天选取，基线只用首周初始化：此比较不构成预测验证。R_eff 未随报告日期后移，且不是隐含 R0。")


def write_report(s, out, checks):
    main = next(c for c in s["cases"] if c["name"] == "main")
    e = primary(main)
    p = next(p for p in main["profiles"]["fit"] if p["alignment"] == e["alignment"] and p["metric"] == e["selection_metric"])
    rows = []
    for case in s["cases"]:
        for item in case["evaluations"]:
            rows.append({"case": case["name"], "alignment": item["alignment"], "metric": item["selection_metric"],
                "beta": item["beta"], "worlds": item["worlds"], "evaluation_loss": item["evaluation_loss"]["mean"],
                "evaluation_se": item["evaluation_loss"]["se"], "daily_coverage": item["groups"]["total"]["metrics"]["daily"]["coverage"],
                "daily_mean_width": item["groups"]["total"]["metrics"]["daily"]["mean_width"],
                "identifiable_by_profile_rule": item["fit_identifiable"]})
    with (out / "metrics.csv").open("w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=rows[0].keys()); writer.writeheader(); writer.writerows(rows)
    g = e["groups"]["total"]
    lines = ["# E0 v2 实验结果解读", "", f"数据窗口：{s['dates'][0]}～{s['dates'][-1]}。状态：{s['status']}。",
        "5 个情景 × 3 种日期后移 × 2 种拟合目标，共 30 组；每组 40 个独立评估世界。", "",
        "## 主设置", "", f"默认展示：累计损失、日期后移 {e['alignment']} 天，β = {e['beta']:.5f}。",
        f"拟合 one-SE 候选范围 {p['one_se_range'][0]:.5f}～{p['one_se_range'][1]:.5f}；它是描述性集合，不是参数置信区间。",
        f"独立评估世界损失均值 {e['evaluation_loss']['mean']:.4f}，SE {e['evaluation_loss']['se']:.4f}。",
        f"总计每日 5–95% 分位带覆盖观测 {g['metrics']['daily']['coverage']:.1%}（13/21 天），平均带宽 {g['metrics']['daily']['mean_width']:.2f}。", "",
        "| 组别 | 观测累计 | 模拟累计中位数 | 模拟 5–95% 分位范围 |", "|---|---:|---:|---:|"]
    for group, label in (("total", "总计"), ("students", "学生"), ("employees", "员工")):
        q = e["groups"][group]["positive_cumulative"]
        lines.append(f"| {label} | {s['observed'][group]['cumulative_positive'][-1]} | {q['q50'][-1]:.1f} | {q['q05'][-1]:.1f}～{q['q95'][-1]:.1f} |")
    lines += ["", "总计终点中位数比观测低约 3.5%，但学生低估与员工高估同时存在。员工观测 5 例，模拟中位数 78 例，且观测落在终点分位带下方。",
        "总量接近不能证明分组传播或检测机制匹配；员工观测本身信息量较低。各组中位数不可直接相加。", "",
        "## 稳健性与机制", "",
        "- 同为累计目标，主设置在日期后移 0/1/2 天时，β 分别为 0.04633 / 0.05925 / 0.06442，说明日期口径会影响参数锚点。",
        "- 默认日期后移 1 天、累计目标下，I₀=10/30/100 对应 β=0.09542/0.05925/0.02567；β 对初始感染假设敏感。",
        "- I₀=100 的累计评估损失约 0.1699，低于主设置 0.2085，但每日覆盖率仅 42.9%，不能只用一个损失值判断机制更合理。",
        "- 默认累计目标下，symp=20/80/200 对应 β=0.05667/0.05925/0.05667。symp 是检测相对权重，不是概率。",
        "- 30 组均通过实现中的剖面可识别性规则；这只描述给定情景内的剖面形态，不证明 β 与 I₀、检测假设在联合意义上可识别。",
        "- 主设置 β 高于实验诊断阈值 0.04，引擎 R_eff 中位数约 5.46～8.18；需要结合接触层权重、接触量和初始状态复核，不能解释为经验证的 R₀。", "",
        "## 基线比较与证据范围", "",
        "08-24～09-06 的每日 MSE：主设置 517.12、恒定阳性率基线 2691.24、固定增长率基线 3589.35。",
        "主设置比两条基线分别低约 80.8% 和 85.6%，但 β 使用全部 21 天拟合，而基线仅使用首周初始化。此比较只支持样本内一致性，不支持预测能力或公平的样本外优越性结论。",
        "分位带只反映固定参数的模拟随机性，不包含参数或模型结构不确定性。累计与周损失尺度不同，不能直接横比。",
        "默认日期偏移不是已验证的真实报告时钟；窗口外延迟结果保留在原始产物中，图仅展示 W1。", "",
        "建议下一步先复核员工传播/检测分配与日期口径，再考虑使用 E0 β 作为后续实验的参数锚点。当前结果适合作为 W1 样本内校准与一致性检查。", "",
        "## 文件与验证", "",
        f"已核对 manifest 中全部 3 个原始 JSONL 的 SHA-256；读取 {checks['evaluation_records']} 条评估记录，重建 {checks['reconstructed_quantile_sets']} 组分位摘要并核对全部 30 组损失均值与 SE。",
        "图表直接使用本次运行 summary 中冻结的观测和结果，不读取当前可能变化的数据，不重新运行仿真。",
        "每图提供 PNG 与 PDF，metrics.csv 含全部 30 组指标，verification.json 记录校验。", "",
        "复现命令：", "", "```powershell", "& 'E:\\pytroch\\anaconda3\\envs\\simulation\\python.exe' tools/plot_e0_results.py --input results/e0_v2/full", "```"]
    report = "\n".join(lines) + "\n"
    (out / "analysis_zh.md").write_text(report, encoding="utf-8")
    names = [("01_main_fit", "主设置拟合"), ("02_group_diagnostics", "分组诊断"),
             ("03_beta_profiles", "β 损失剖面"), ("04_sensitivity", "敏感性分析"),
             ("05_baselines_and_checks", "基线与机制诊断")]
    cards = "".join(f'<section id="{name}"><h2>{title}</h2><a href="{name}.png"><img src="{name}.png" alt="{title}"></a><p><a href="{name}.pdf">下载 PDF</a></p></section>' for name, title in names)
    page = '<!doctype html><html lang="zh-CN"><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1"><title>E0 v2 结果</title><style>body{font:16px/1.7 "Microsoft YaHei",sans-serif;background:#f1f5f9;color:#253044;max-width:1400px;margin:auto;padding:24px}section,header{background:white;padding:24px;margin:20px 0;border-radius:12px}img{width:100%;height:auto}pre{white-space:pre-wrap;font:14px/1.8 "Microsoft YaHei",sans-serif}a{color:#2474ab}</style><header><h1>E0 v2 实验结果</h1><p>总量接近观测，分组偏差和参数敏感性仍需关注。</p><p><a href="analysis_zh.md">中文分析</a> · <a href="metrics.csv">全部指标 CSV</a> · <a href="verification.json">校验记录</a></p></header>' + cards + '<section><h2>完整解读</h2><pre>' + html.escape(report) + '</pre></section></html>'
    (out / "index.html").write_text(page, encoding="utf-8")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, default=Path("results/e0_v2/full"))
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    s = json.loads((args.input / "summary.json").read_text(encoding="utf-8"))
    manifest = json.loads((args.input / "manifest.json").read_text(encoding="utf-8"))
    if s["status"] != "complete" or manifest["status"] != "complete":
        raise ValueError("Expected a completed experiment")
    checks = audit(args.input, s, manifest)
    out = args.output or args.input / "visualizations"
    out.mkdir(parents=True, exist_ok=True)
    plt.rcParams.update({"font.sans-serif": ["Microsoft YaHei", "SimHei", "DejaVu Sans"],
                         "axes.unicode_minus": False, "axes.spines.top": False,
                         "axes.spines.right": False, "axes.grid": True,
                         "grid.alpha": .16, "axes.axisbelow": True, "font.size": 10,
                         "pdf.fonttype": 42})
    figures(s, out)
    (out / "verification.json").write_text(json.dumps(checks, indent=2), encoding="utf-8")
    write_report(s, out, checks)
    print(f"Verified and generated 5 PNG/PDF figures, metrics and report: {out}")


if __name__ == "__main__":
    main()
