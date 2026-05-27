'''
TransTree Visualization Demo
Demonstrates 3 core visualizations:
  1. plot()            — daily transmissions grouped by layer, symptom stage, quarantine status, etc.
  2. animate()         — day-by-day animation: who infected whom
  3. plot_histograms() — distribution of secondary infections per person
'''

import covasim as cv
import sciris as sc

# ========== 配置 ==========
pop_size = 500        # 人口数
n_days = 60           # 仿真天数
beta = 0.18           # 传播率 (hybrid 下每个接触层的传播率)
contacts = {'h': 2, 's': 2, 'w': 2, 'c': 2}  # 每层每人每日接触数
pop_infected = 10     # 初始感染者数

# 干预措施：第15天开始检测 + 接触追踪
iday = 15
tp = cv.test_prob(
    start_day=iday,
    symp_prob=0.01,
    asymp_prob=0.0,
    symp_quar_prob=1.0,
    asymp_quar_prob=1.0,
    test_delay=0,
)
ct = cv.contact_tracing(
    trace_probs={'h': 1.0, 's': 1.0, 'w': 1.0, 'c': 1.0},
    trace_time={'h': 0, 's': 0, 'w': 0, 'c': 0},
    start_day=iday,
)

pars = dict(
    pop_size=pop_size,
    pop_type='hybrid',
    n_days=n_days,
    contacts=contacts,
    beta=beta,
    pop_infected=pop_infected,
    rand_seed=1,
)

# ========== 运行三组仿真 ==========
labels = ['No Intervention', 'Testing Only', 'Test + Trace']
sims = sc.objdict()
sims.base = cv.Sim(pars)
sims.test = cv.Sim(pars, interventions=tp)
sims.trace = cv.Sim(pars, interventions=[tp, ct])

for key, sim in sims.items():
    label = labels[list(sims.keys()).index(key)]
    print(f'Running: {label}...')
    sim.run()

# ========== 构建传播树 ==========
tts = sc.objdict()
for key, sim in sims.items():
    tts[key] = sim.make_transtree()

# ========== 1. Daily Transmission Category Plot ==========
print('\n>>> Generating daily transmission category plot (tt.plot)...')
for i, (key, tt) in enumerate(tts.items()):
    fig = tt.plot(fig_args=dict(figsize=(16, 8)))
    fig.suptitle(f'Daily Transmissions by Category — {labels[i]}', fontsize=14, fontweight='bold')
    fig.savefig(f'examples/figures/transtree_plot_{key}.png', dpi=150, bbox_inches='tight')
    print(f'  Saved: examples/figures/transtree_plot_{key}.png')

# ========== 2. Daily Animation ==========
print('\n>>> Generating daily transmission animation (tt.animate)...')
for i, (key, tt) in enumerate(tts.items()):
    print(f'  Playing animation: {labels[i]} — watch the matplotlib window...')
    fig = tt.animate(
        animate=True,
        delay=0.3,
        fig_args=dict(figsize=(14, 8)),
        markersize=6,
        cmap='parula',
    )
    print(f'  Animation finished: {labels[i]}')

# ========== 3. Transmission Count Histograms ==========
print('\n>>> Generating transmission count histograms (tt.plot_histograms)...')
for i, (key, tt) in enumerate(tts.items()):
    fig = tt.plot_histograms(fig_args=dict(figsize=(14, 6)))
    fig.suptitle(f'Transmission Count Distribution — {labels[i]}', fontsize=14, fontweight='bold')
    fig.savefig(f'examples/figures/transtree_hist_{key}.png', dpi=150, bbox_inches='tight')
    print(f'  Saved: examples/figures/transtree_hist_{key}.png')

# ========== Output Statistics ==========
print('\n========== Transmission Statistics ==========')
for i, (key, tt) in enumerate(tts.items()):
    sim = sims[key]
    print(f'\n{labels[i]}:')
    print(f'  Total infections: {sim.results["cum_infections"].values[-1]}')
    print(f'  Total transmission events: {len(tt.infection_log)}')
    print(f'  By layer:')
    if not tt.df.empty:
        layer_counts = tt.df.groupby('layer').size()
        for layer, count in layer_counts.items():
            print(f'    {layer}: {count}')

print('\nDemo complete! Images saved to examples/figures/')
