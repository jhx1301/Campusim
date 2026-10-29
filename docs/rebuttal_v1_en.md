**Point-by-point author responses — English**

These responses describe the revised implementation and distinguish completed changes from experiments that still need to be run. Numbering matches the [Chinese version](rebuttal_v1_zh.md). Supporting records are listed in the [evidence document](rebuttal_v1_evidence_and_next_steps.md).

**Reviewer eojL**

**eojL-W1 — Stronger baselines and comparisons with existing LLM epidemic systems are missing.**

**Response:** We have added two reinforcement-learning controllers, PPO and Double DQN, a threshold controller whose parameters can be optimized, and an LLM given no additional memory summaries or retrieved cases. All methods receive the same observable epidemic records and choose from the same interventions. Full training and comparisons remain incomplete, including comparisons with existing LLM epidemic systems, so superiority is not yet established.

**eojL-W2 — The claimed advantage depends on chosen weights and potentially saturating normalization.**

**Response:** We agree that the original CPBU ranking cannot establish a general advantage. In the revised evaluation, the scales used to convert infection counts and intervention burdens into comparable quantities are fixed before comparison, and values above the reference scales are not capped. We will also report infections and each burden separately. Weight-sensitivity results are still unavailable.

**eojL-W3 — Calibration fit, error metrics, and out-of-sample validation are missing.**

**Response:** We now have observed-versus-simulated daily diagnosis curves for August 3–18, 2020. Across 20 independent simulation runs, mean absolute error and root mean squared error average 5.578 and 11.223, respectively. However, these are the same dates used for calibration. This checks fit across repeated simulations, not prediction on unseen dates; a separate time-based validation is still needed.

**eojL-Q1 — Which LLM was used, and do the results hold for another model?**

**Response:** The archived supplement names deepseek-v4-flash as the default, but the model that actually produced the original tables still requires confirmation from saved API records. The revised implementation specifies deepseek-flash as the main model and qwen3.5-plus-2026-02-15 for a second-model comparison. That comparison has not yet been completed.

**eojL-Q2 — Can you add RL on the same task or thresholds tuned with the same optimization budget?**

**Response:** PPO and Double DQN now use the same observable information and 324 intervention combinations as the LLM. Threshold parameters are also selected using simulations reserved for tuning, with the same evaluation objective that accounts for infections and intervention burden. We have not established equal tuning budgets across methods. Full training and comparisons, including actual resource use, remain incomplete.

**eojL-Q3 — Under which utility weights does the LLM remain superior?**

**Response:** We cannot yet identify such a range. The planned comparison uses total cost = infection cost + λ × intervention burden, with λ = 0.5, 1, and 2. A smaller λ places more importance on infection control. For each value, baseline parameters must be optimized again and the LLM given the same preference before their results are compared.

**eojL-Q4 — Show calibration fit and explain conflicting values in the two tables.**

**Response:** The current calibration report includes observed and simulated curves; average per-run mean absolute error and root mean squared error are 5.578 and 11.223 across 20 runs. The original table discrepancy remains unresolved. For the new experiments, identical conditions in the main comparison and memory ablation will use the same simulation results, rather than separate runs that could introduce unexplained differences.

**Reviewer SSFu**

**SSFu-W1 — Evaluation in the same simulator does not establish real-world generalization.**

**Response:** We agree. Fitting one outbreak and evaluating policies in the same simulator cannot establish effectiveness in real populations. We plan to test the controllers on simulated populations with different age distributions and contact networks, without changing their selected parameters or historical case library. Those tests remain incomplete and would establish only transfer between simulated settings.

**SSFu-W2 — Stronger non-LLM methods are needed to establish the LLM's value.**

**Response:** We have added PPO, Double DQN, and a threshold controller whose parameters can be tuned. They make decisions from the same observable information and have the same intervention choices as the LLM. So far, we have only checked that the implementations run and completed brief training runs; a full comparison is still needed to determine whether the LLM improves outcomes.

**SSFu-W3 — The utility function and prompt discouraging online teaching may favor the LLM.**

**Response:** The revised prompt no longer tells the LLM to avoid online teaching. It asks the model to consider both infections and intervention burden, using the same objective applied to threshold tuning and reinforcement learning. Changing interventions carries no additional penalty. This removes the explicit preference in the prompt, but a fair outcome comparison and weight-sensitivity tests remain necessary.

**SSFu-W4 — Calibration and sensitivity analysis report inconsistent R_e ranges.**

**Response:** In the old calibration code, values outside [1.5, 3.5] increased the calibration loss; they were not prohibited. This means estimates above 3.5 were possible, but does not establish why the paper reports 4.52–6.71. We still need to check how those values were calculated and over which dates. The revised calibration fits daily diagnoses without this additional R_e penalty.

**SSFu-W5 — Longer strict intervention confounds the memory ablation.**

**Response:** Longer intervention may be a pathway through which memory works, so it does not by itself invalidate memory's overall effect. The original comparison cannot establish better control at comparable burden. We will add a no-memory controller with delayed relaxation and a diagnostic comparison with equal total teaching restrictions but freely chosen timing, testing simple persistence and more effective decisions separately. These experiments remain incomplete.

**SSFu-Q1 — How is R_e defined, and why does it exceed the calibration range?**

**Response:** R_e is the expected number of secondary infections under the prevailing susceptibility and intervention conditions. The earlier [1.5, 3.5] range was a calibration penalty target, not an enforced limit. For subsequent E0 experiments, we will fix the estimator and early comparison period, and establish a reference range for that period's mean R_e using outbreak data, relevant studies, and estimation uncertainty. Only if that range is sufficiently supported will it become a parameter-acceptance condition, checked through independent simulation runs. Failed checks will not be reported as successful calibration, and out-of-range estimates will not be capped. This range applies to the specified calibration conditions, not to every scenario with a different transmission strength.

**SSFu-Q2 — How was the threshold baseline tuned, and did it share the LLM's objective?**

**Response:** The revised procedure will compare 32 candidate threshold settings on simulations excluded from final testing, first screening candidates and then selecting parameters on a separate set of simulations. Selection uses a predefined objective combining infections and intervention burden. The LLM prompt specifies that same objective and its weights, but we do not train or fine-tune the LLM against it. Stating the objective does not establish that its decisions are optimal. Formal threshold tuning remains incomplete.

**SSFu-Q3 — Summarize CPBU weight sensitivity, particularly when infection control receives more weight.**

**Response:** We agree that the original CPBU ranking cannot establish a general advantage. The revised evaluation no longer uses CPBU to rank methods. We will report infections and intervention burdens separately, making any trade-offs explicit. If a baseline prevents more infections, that advantage will be reported directly; lower intervention burden will not be presented as evidence that the LLM is best overall.

**SSFu-Q4 — How is global memory constructed, and does it overlap evaluation scenarios?**

**Response:** The planned library contains 108 histories: 27 simulated outbreaks, each run under minimum intervention, the strongest available intervention, random feasible interventions, and a tuned threshold controller. Some transmission and resource settings match the main campus tests, but the library and tests use independently generated outbreaks and do not reuse trajectories. This tests new outbreaks under known settings. The library is not yet complete.

**SSFu-Q5 — How much infection reduction comes from memory reasoning versus longer intervention?**

**Response:** Longer intervention may be a pathway through which memory works, so the observed benefit cannot naturally be divided into separate reasoning and duration percentages. Alongside the unrestricted comparison, we will add a no-memory controller with delayed relaxation and a diagnostic task with equal total teaching restrictions but freely chosen timing. These test whether simple persistence reproduces the benefit and whether memory improves timing for the same amount of teaching restriction. Infections and other burdens will be reported separately; neither comparison directly measures an independent contribution from internal reasoning.

**AI review**

**AI-W1 — Cumulative infections exceed the stated population.**

**Response:** The original total of 51,651 cannot be explained from the stated population and single-infection model using the records we have verified. The revised setup has 12,000 people, with each simulated person representing one person, no reinfection, and no imported cases. Consequently, the 30 initial infections plus all subsequent infections must not exceed 12,000. The original totals still require reconstruction.

**AI-W2 — CPBU normalization, weights, and missing uncertainty undermine the ranking.**

**Response:** We agree that the original score does not establish a reliable overall ranking. The revised evaluation will report infections, testing, contact notifications, isolation/quarantine, and activity restrictions separately. Methods will be compared under the same simulated conditions, with confidence intervals for their differences. Different weightings will also be tested. These analyses remain incomplete, so overall superiority cannot yet be claimed.

**AI-W3 — Simulator fidelity and dormitory/classroom dominance lack direct evidence.**

**Response:** The current report compares observed and simulated daily diagnoses, with average per-run root mean squared error of 11.223 across 20 runs. This assesses fit to the calibration dates, not broader predictive accuracy. It also does not establish where transmission mainly occurs. Claims that dormitories and classrooms consistently dominate require direct transmission counts by setting, which have not yet been reported.

**AI-W4 — The contribution is insufficiently distinguished from prior RL control and memory-based LLM agents.**

**Response:** We agree that learning epidemic-control policies and using memory in LLM decision-making are established ideas, as shown by [Mai et al.](https://www.ijcai.org/proceedings/2023/682), [Meirom et al.](https://proceedings.mlr.press/v139/meirom21a.html), [RAFA](https://proceedings.mlr.press/v235/liu24ab.html), and [DiLu](https://proceedings.iclr.cc/paper_files/paper/2024/hash/93c936b9e492def9c00782cab79dbc6d-Abstract-Conference.html). Our contribution should be limited to selecting executable campus interventions from observable epidemic information and historical cases, and testing their value against alternatives under shared conditions. That comparative evidence remains incomplete.

**AI-W5 — Greater intervention intensity confounds the memory benefit.**

**Response:** Longer restrictions may result from memory-assisted decisions and contribute to memory's overall effect, but this does not establish better control at the same cost. The existing strongest-intervention reference does not ensure comparable burden. We plan to add delayed relaxation without memory and an equal-total-teaching-restriction diagnostic task, testing whether simple persistence reproduces the benefit and whether timing improves for the same amount of teaching restriction. Other intervention burdens will also be reported.

**AI-W6 — Ablations do not isolate memory branches or directly measure policy stability.**

**Response:** We have implemented four conditions: no additional memory, recent-history summaries only, retrieved historical cases only, and both. All retain the same basic four-week observations, model settings, expert knowledge, and output requirements. Their outcome comparisons remain incomplete. The claim that expert knowledge improves stability also needs a separate with/without-knowledge comparison measuring actual intervention changes, rather than infection curves alone.

**AI-S1 — Present a clear observation–action–feedback specification.**

**Response:** The revised task specifies decisions every seven days. Controllers observe reported diagnoses, testing, previous interventions, and available resources, then choose clinical testing, screening, tracing, teaching restrictions, and other activity restrictions from 324 combinations. They subsequently receive records of what was actually carried out and its burden. Isolation and quarantine follow fixed rules. The manuscript still needs a compact table listing the exact intervention parameters.

**AI-S2 — Analyze invalid outputs, fallback, misleading retrieval, and policy failures.**

**Response:** We now record whether model outputs can be read correctly, whether proposed interventions exceed available resources, what is actually executed when a proposal fails, and which historical cases were retrieved. These records allow the requested analysis. However, error rates and examined examples of misleading cases, premature relaxation, or excessive restrictions still need to be reported from completed experiments.

**AI-S3 — Test generalization using different memory-building and evaluation conditions.**

**Response:** We plan to build the historical case library using campus simulations, fix its contents before testing, and apply it to populations with different ages and contact patterns without adding test cases to the library. These experiments remain incomplete. Repeating the same campus setup with different random initialization does not by itself demonstrate adaptation to different transmission or imported-case conditions.

**AI-S4 — Separate simulator and controller contributions in the narrative.**

**Response:** The simulator provides an environment in which interventions have executable consequences; the controller selects those interventions from observable information. Matching an observed diagnosis curve offers limited support for the simulator, while policy comparisons assess the controller. The title, abstract, and conclusion should state these contributions separately and avoid using policy results as evidence that the simulator accurately reproduces real campuses.

**AI-M1 — “Never uses online teaching” contradicts the reported 1.4 days.**

**Response:** We agree that the statement contradicts Table 1. It should state that Table 1 reports an average of 1.4 online-teaching days in the High condition, rather than saying online teaching is never used. The underlying count still requires verification against the original experiment records.

**AI-M2 — “Daily quarantine” lacks a clear unit.**

**Response:** We distinguish the number quarantined on a particular day from accumulated quarantine person-days: one person quarantined for three days contributes three person-days. Average daily quarantine is total person-days divided by simulation days. The table must specify which quantity it reports. When isolation and quarantine are combined, a person in both is counted only once per day.

**AI-M3 — The memory formula is undefined at the first decision.**

**Response:** At the first decision, the revised implementation supplies no completed weekly records and explicitly indicates that history and trends are unavailable. It therefore does not evaluate a weighted average with an empty denominator. Missing history is not treated as zero infections or a stable epidemic.

**AI-M4 — Similarity calculations need rules for zero vectors and constant or short trends.**

**Response:** We now compare numerical differences after converting measurements to fixed scales, instead of dividing by vector lengths or trend variance. Zero values and constant trends therefore remain valid. With fewer than two completed weeks, no trend comparison is made; matching uses the available current information. Cases with too little comparable information are excluded.

**AI-M5 — Full-memory results differ between the main and ablation tables.**

**Response:** We have not yet established why the original values differ and should not attribute the discrepancy to seeds or settings without supporting records. In the new experiments, a method evaluated under identical conditions will contribute the same saved results to both tables. Any different settings or repetitions must be explicitly identified.

**AI-M6 — “theory/notheory” and “expert knowledge” use inconsistent terminology.**

**Response:** The figure, caption, legend, and text should consistently use “with expert knowledge” and “without expert knowledge.” These labels state exactly which component is changed and avoid suggesting that the comparison concerns a theoretical guarantee.

**Next-stage improvements**

1. Verify the original infection totals, table inputs, actual model identity, and real API calls; correct results that cannot be reproduced.
2. Complete baseline training and threshold tuning using simulations excluded from final testing. Fix parameters, prompts, historical cases, evaluation weights, and duration before running the final comparison.
3. Compare methods using the same simulated outbreaks and report infections, each intervention burden, confidence intervals, and computational/API costs separately.
4. Repeat the comparison under different infection–burden preferences, optimizing each method for each preference. Compare memory methods at similar intervention duration or burden, and test expert knowledge separately.
5. Test predictions on dates excluded from calibration, investigate why the fitted parameter lies near the search limit, and distinguish simulated transfer from real-world validation.
6. Complete the second-model comparison and failure analysis; make the task description, units, figures, related work, and conclusions match the evidence.
