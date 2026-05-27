import os, sys
os.environ['COVASIM_VERBOSE'] = '0'
sys.path.insert(0, 'D:/项目/毕业设计/covasim-main/examples')

import numpy as np
import covasim as cv
import covasim.llm_policy as cvlp
from t17_campus_llm_thesis_experiments import parse_args, resolve_config, make_common_pars, make_policy_agent, DEFAULT_OUTDIR

args = parse_args()
args.preset = 'paper'
args.use_api = False
config = resolve_config(args)
agent = make_policy_agent(args, 'ablation_expert_and_memory', DEFAULT_OUTDIR)
print(f'agent.decision_interval_days={agent.decision_interval_days}')
print(f'agent.defer_first_decision_until_interval={agent.defer_first_decision_until_interval}')
print(f'agent.start_day={agent.start_day}')
print(f'agent.decision_fn is not None: {agent.decision_fn is not None}')

pars = make_common_pars(config, 'medium', 1)
sim = cv.Sim(pars=pars, interventions=[agent], label='test')
sim.run()

print(f"Sim completed. npts={sim.npts}, decision_history={len(agent.decision_history)}")
print(f"agent.last_decision_day={agent.last_decision_day}")
print(f"agent.current_policy={agent.current_policy}")
print(f"Sub-interventions: {len(agent.sub_interventions)}")

# Check if decisions happened but weren't recorded in decision_history
# The decision_history is populated at line 1858
