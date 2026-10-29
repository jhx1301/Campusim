# CEMAS: Campus Epidemic Multi-Agent Simulation

CEMAS studies adaptive epidemic control in a shared, partially observable
simulation task. The current V1 implementation combines a Covasim-derived
campus engine with weekly control, public observations, LLM controllers,
deterministic public memory, tuned thresholds, MaskablePPO, and Double DQN.

**Current status (2026-10-23):** the UW configuration uses 69,457 agents,
2,321 teachers, 21,596 other staff, and `campus_k_ts=3`. These recent model
changes require a new E0 calibration. The existing `results/e0_v2/full/`
anchor belongs to the previous model and is retained as historical evidence.
Formal source development, release freeze, and E1–E4 evaluation are not
complete. See [UW control integration](docs/uw_control_integration.md) for the
current configuration, commands, and evidence limits.

## V1 control task

- All methods use the same `[T,S,C,E,A]` action vector: clinical testing,
  screening, tracing, school restrictions, and work/community restrictions.
  The joint action space has 324 combinations.
- Controllers receive public observations and closed public execution
  feedback. Hidden infections, private reward, beta, seeds, future events,
  and simulator objects do not enter LLM prompts or memory.
- The current snapshot feedback task uses seven shared observation days,
  followed by 112 autonomous control days: 119 days and 16 decisions in total.
  The first autonomous decision is on day 7.
- The campus engine uses six contact layers: `d`, `clu`, `clg`, `of`, `ta`,
  and `cm`. All controllers share the weekly environment and executor.
- Memory uses deterministic recent summaries, knowledge cards, numeric
  state/trend retrieval, and optional LLM weekly feedback and persistent rules.
  Training accumulates independent weekly cases and aggregate rule statistics;
  formal evaluation reads one frozen learning library. The current contract is
  the [feedback design](docs/llm_feedback_component_design.md). Earlier P5
  documents describe the historical frozen-source-only design.

## Repository and documentation

| Location | Purpose |
|---|---|
| [Current reading index](docs/CEMAS_READING_INDEX.md) | Current status, reading order, and implementation boundaries |
| [Documentation index](docs/README.md) | Protocols, phase contracts, and environment notes |
| [Control protocol](docs/control_protocol_v1.json) | Shared task, actions, resources, objective, seeds, and experiment settings |
| [Memory profile](docs/control_memory_v1.json) | Active P5 numeric retrieval and memory configuration |
| [Feedback design](docs/llm_feedback_component_design.md), [implementation contract](docs/PLAN%20(1).md) | Flat weekly feedback, persistent aggregate rules, v2 learning library, and frozen evaluation |
| [E0 protocol](docs/e0_protocol_v2.json) | UW W1 calibration configuration |
| [cemas/control/](cemas/control/) | Weekly control, LLM/memory controllers, baselines, training, and audit |
| [cemas/e0/](cemas/e0/) | UW observation loading, simulation study, and control-anchor verification |
| [examples/control_v1/](examples/control_v1/) | Current command-line entry points |
| [covasim/](covasim/) | Population, contact networks, epidemic engine, and interventions |
| [Historical data research](research/historical_epidemics/README.md) | Sources, normalized observations, context, and provenance |

## Environment and local checks

Use the source checkout and the existing simulation environment. Run commands
from the repository root:

```powershell
$python = 'E:\pytroch\anaconda3\envs\simulation\python.exe'
& $python -B -X utf8 tools/check_control_environment.py
& $python -m examples.control_v1.smoke --output results/v1_smoke_next --seed 90001 --population 100 --days 14 --initial-infections 3
```

The smoke command uses an uncalibrated, reduced population to check the control
loop. It does not establish scientific validity. Output directories must be new.
Dependency declarations and historical environment snapshots have different
purposes; see [environment notes](docs/README.md#环境与依赖) before installing.
Standalone package installation and CI do not yet establish complete V1 runtime
acceptance.

## Calibration and subsequent runs

The current E0 uses the UW–Madison on-campus student/employee testing series
for 2020-08-17 through 2020-09-06. Positive-test counts are observations of
tested samples, not hidden infection counts. See the [data description](data/README.md).

Run a complete study for the current model in a new directory:

```powershell
& $python -m examples.control_v1.e0_study --output results/uw_e0_roles_20261023 --workers 4
```

After this study completes and exports a compatible `control_anchor.json`,
the fixed references can use it:

```powershell
& $python -m examples.control_v1.run_references --artifact results/uw_e0_roles_20261023/control_anchor.json --seed 20005 --output results/uw_references
```

These are execution examples, not records of completed calibration or formal
evaluation. The anchor must remain with its original study files. It provides
a W1 in-sample parameter anchor and consistency check, not predictive or
real-world intervention validation. Baseline and training commands are in the
[Phase 6 contract](docs/control_phase6_contracts.md).

LLM runs use [run_llm.py](examples/control_v1/run_llm.py) or
[run_memory_llm.py](examples/control_v1/run_memory_llm.py), with an endpoint,
the name of a credential environment variable, official tokenizer resources,
and a compatible E0 anchor. `global`/`both` memory additionally needs a verified
frozen source store. Development acceptance reports are retained separately;
normal runs do not require them as startup credentials. Persistent feedback
learning uses [learn_memory.py](examples/control_v1/learn_memory.py) with
`train`, `freeze`, and `evaluate`; the new v2 learning library does not read
deprecated v1 learning databases.

## Historical implementation and results

The old `covasim/llm_policy.py`, `covasim/llm_memory.py`,
`campus_policy_agent`, P0–P4 policy catalogue, old experiments, and
[paper result mapping](RESULT_MAPPING.md) belong to the previous implementation.
V1 uses the separate control modules described above. The old modules remain
for API/history dependencies and recorded source identities; their results do
not establish current UW acceptance. Historical reproduction tools are under
`tools/supplement/` and `tools/build_cemas_supplement.py`.

## License and upstream attribution

CEMAS includes substantial portions of Covasim v3.1.7 and preserves its MIT
License and original copyright notice. See [LICENSE](LICENSE).
