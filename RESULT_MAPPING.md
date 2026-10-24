# Paper-to-artifact mapping

> Historical paper supplement: this mapping describes the previous P0–P4
> implementation and its packaged output layout. It does not describe the
> current V1 checkout or establish UW validation; the listed result families
> are not all present here. Use the [V1 entry point](README.md) and
> [UW integration contract](docs/uw_control_integration.md) for current work.

This file identifies the exact artifact family supporting each paper table.
The distinction is important because the repository contains both a recent
policy-history mechanism and a newer dual-branch memory mechanism.

| Paper item | Packaged source | Runs | Interpretation |
|---|---|---:|---|
| Table 1 | `results/calibration/calibration_results.json` | 80 Optuna trials | Default and calibrated transmission parameters |
| Table 2 | `results/calibration/sensitivity_run_metrics.csv` | 20 seeds per variant | One-at-a-time +/-20% sensitivity analysis |
| Table 3 | `results/policy_comparison/policy_*` | 10 seeds per scenario and strategy | No policy, threshold rule, and `llm_single_memory` |
| Table 4 | `results/recent_memory_ablation/memory_*` | 5 seeds per scenario and strategy | LLM with and without recent policy history |
| Additional dual-memory study | `results/dual_memory_ablation/` | 5 seeds per condition | Short-term trajectory compression and frozen long-term similar-scenario retrieval |

## Memory terminology

`llm_single_memory` uses a four-week recent policy history together with expert
prompt rules and the structured campus policy catalogue. It generated the
numerical values currently reported in Tables 3 and 4.

`llm_dual_memory` additionally uses within-episode trajectory compression and
retrieval from a frozen cross-simulation memory database. Its outputs are
packaged as a separate additional experiment and must not be presented as the
source of the existing Table 3 or Table 4 numbers.

The included decision logs contain the exact prompt, parsed decision, model
name, endpoint, token settings, and usage metadata needed to audit each external
LLM decision. API credentials are never logged.
