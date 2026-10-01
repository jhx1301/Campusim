# CEMAS: Campus Epidemic Multi-Agent Simulation

CEMAS is a research framework for simulating epidemic transmission on a
university campus and evaluating adaptive intervention policies. It combines a
campus-specific agent-based epidemic model, a structured policy catalogue, an
LLM policy agent, and short- and long-term decision memory.

This anonymous code-and-data supplement contains the implementation, processed
input data, per-seed outputs, decision audit records, and scripts needed to
verify and reconstruct the numerical results reported in the paper.

## Main capabilities

- A six-layer campus contact network covering dormitories, undergraduate and
  graduate classrooms, offices and laboratories, teaching and administrative
  staff, and campus common spaces.
- Individual-level infection progression, transmission, testing, diagnosis,
  quarantine, isolation, immunity, and intervention tracking.
- Five ordered campus policy levels, from normal operation to emergency
  restrictions.
- A provider-neutral LLM policy client compatible with OpenAI-style endpoints.
- Structured parsing and format validation for LLM policy responses.
- Recent-policy memory plus a dual-branch memory design combining short-term
  trajectory summaries with long-term similar-scenario retrieval.
- Multi-seed policy evaluation, calibration, sensitivity analysis, audit logs,
  table reconstruction, and integrity verification.

## System architecture

```text
Campus data and scenario configuration
                 |
                 v
      Campus population and six-layer network
                 |
                 v
       Agent-based epidemic simulation
                 |
                 v
     Epidemiological state summarization
                 |
        +--------+---------+
        |                  |
        v                  v
 Recent trajectory     Similar historical
     memory             scenario retrieval
        |                  |
        +--------+---------+
                 |
                 v
             LLM policy agent
                 |
                 v
       Response parsing and policy execution
                 |
                 v
 Metrics, policy traces, decision logs, and tables
```

## Core modules

### Public CEMAS API

The `cemas` package is the public entry point. It exposes the simulator,
interventions, `PolicyClient`, and memory components through one import:

```python
import cemas as ce

sim = ce.Sim(pop_type="campus", pop_size=4000, n_days=56)
sim.run()
```

### Campus population and contact network

The campus population module assigns agents to campus roles and constructs six
epidemiologically distinct contact layers:

| Layer | Meaning |
|---|---|
| `d` | Dormitory contacts |
| `clu` | Undergraduate classroom contacts |
| `clg` | Graduate classroom contacts |
| `of` | Office and laboratory contacts |
| `ta` | Teaching and administrative staff contacts |
| `cm` | Campus common-space contacts |

Each layer can use different contact patterns and transmission weights, making
it possible to represent targeted teaching, residence, workplace, and
common-space interventions.

### Epidemic simulation engine

The simulation engine maintains individual infection states and advances the
campus epidemic day by day. It records infections, diagnoses, testing,
quarantine, intervention burden, effective reproduction estimates, and
layer-specific transmission contributions.

### Campus policy agent

The policy module converts recent simulation observations into a structured
decision state. A policy decision contains a policy identifier, risk level, and
reason. The agent validates the response against the policy catalogue before
applying testing, quarantine, contact reduction, and teaching-mode changes.

`PolicyClient` accepts any configured OpenAI-compatible endpoint. LLM
experiments always use the configured API.

### Policy catalogue

CEMAS defines five ordered policies:

| Policy | Interpretation |
|---|---|
| `P0_normal` | Normal campus operation |
| `P1_guarded` | Enhanced monitoring and testing |
| `P2_moderate` | Moderate transmission controls |
| `P3_strong` | Strong contact and teaching restrictions |
| `P4_emergency` | Emergency campus controls |

LLM responses are parsed into the required fields and checked against this
catalogue before execution.

### Memory subsystem

CEMAS supports two related memory mechanisms:

- Recent-policy memory supplies the agent with the latest policy decisions and
  observed outcomes.
- Dual-branch memory combines a compressed within-run trajectory with retrieval
  of similar completed situations from a frozen cross-run memory store.

The two mechanisms are evaluated separately. `RESULT_MAPPING.md` explains which
one supports each paper table.

### Experiment and validation pipeline

`experiments/run_cemas_experiments.py` runs formal policy comparisons, memory
ablations, and robustness analyses. Strategies that use an LLM require the
configured API.

`experiments/run_cemas_validation.py` performs campus-model calibration and
one-at-a-time parameter sensitivity analysis.

`experiments/reproduce_tables.py` reconstructs Tables 1--4 from the supplied
results without rerunning simulations or calling an external API.

`experiments/verify_results.py` checks result structure, audit logs, the
read-only memory audit index, file hashes, and anonymous-release constraints.

## Repository layout

```text
CEMAS_Code_and_Data_Supplement/
├── cemas/                 Public CEMAS Python API
├── experiments/           Experiment, validation, and reproduction scripts
├── data/                  Reconstructed campus outbreak time series
├── results/
│   ├── calibration/       Calibration and sensitivity outputs
│   ├── policy_comparison/ Table 3 multi-seed policy results
│   ├── recent_memory_ablation/
│   ├── dual_memory_ablation/
│   ├── figures/           Selected paper-facing figures
│   └── llm_audit_logs.zip
├── RESULT_MAPPING.md      Paper-to-artifact mapping
├── SHA256SUMS.txt         File-integrity hashes
└── requirements.txt       Reproducible Python environment
```

## Installation

The reference environment uses Python 3.10:

```bash
python -m pip install -r requirements.txt
python -m pip install -e .
```

## Paper result map

| Paper item | Included artifacts | Experiment |
|---|---|---|
| Table 1 | `results/calibration/calibration_results.json` | Campus-model calibration |
| Table 2 | `results/calibration/sensitivity_*.csv` | Parameter sensitivity, 20 seeds per variant |
| Table 3 | `results/policy_comparison/policy_*` | No intervention, threshold policy, and CEMAS LLM policy |
| Table 4 | `results/recent_memory_ablation/memory_*` | Recent-policy-memory ablation |
| Additional study | `results/dual_memory_ablation/` | Short-term and long-term memory branches |

See `RESULT_MAPPING.md` for the exact strategy definitions and the distinction
between recent-policy memory and dual-branch memory.

## Verify and reconstruct the supplied results

The included numerical results can be checked without network access, an API
key, or rerunning the simulations:

```bash
python experiments/verify_results.py
python experiments/reproduce_tables.py
```

The reconstructed CSV tables are written to `reproduced_tables/`.

## Run experiments

LLM experiments require an OpenAI-compatible endpoint:

```bash
export LLM_API_KEY="..."
export LLM_BASE_URL="https://your-provider.example/v1"
export LLM_MODEL="your-model"

python experiments/run_cemas_experiments.py \
  --experiment policy
```

The generic `LLM_API_KEY`, `LLM_BASE_URL`, and `LLM_MODEL` settings take
precedence over legacy compatibility variables. API credentials are never
written to manifests or decision logs.

Calibration and non-LLM baselines do not call the endpoint. Any selected
strategy that uses an LLM requires `LLM_API_KEY`.

## Data and outputs

The files under `data/` contain reconstructed daily campus outbreak series
derived from a public epidemiological report. They are aggregate time series,
not individual-level records. See `data/README.md` for provenance, variables,
and calibration windows.

The result directories include:

- per-seed run metrics;
- aggregated summary metrics;
- daily epidemic trajectories;
- policy trajectories and decision summaries;
- layer-specific transmission contributions;
- memory-retrieval audit records;
- compressed JSONL LLM decision logs;
- selected figures used to inspect the reported results.

## License and upstream attribution

CEMAS includes substantial portions of Covasim v3.1.7 and preserves its MIT
License and original copyright notice. The full license is provided in
`LICENSE`.
