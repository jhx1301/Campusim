"""Shared snapshot training, single validation and time-limit bootstrapping."""

from dataclasses import replace
import json
from pathlib import Path
from types import SimpleNamespace

import cloudpickle
import numpy as np
import pytest

from cemas.control.environment import WeeklyControlEnvironment
from cemas.control.logging import resolved_snapshot
from cemas.control.observation import encode_observation, SNAPSHOT_FEATURE_NAMES
from cemas.control.snapshot_protocol import (load_training_protocol, history_seeds,
    snapshot_scenarios, SnapshotEpisodePlan)
from cemas.control.snapshots import generate_history_snapshots, SNAPSHOT_SCHEMA

ROOT = Path(__file__).resolve().parents[1]
ANCHOR = "fixture-anchor"


@pytest.fixture(scope="module")
def protocol():
    return load_training_protocol(ROOT / "docs/baseline_snapshot_training_v1.json")


@pytest.fixture
def small_world(protocol, tmp_path, monkeypatch):
    from cemas.e0 import artifacts, data
    original = data.load_e0_config(ROOT / "docs/e0_protocol_v2.json")
    config = dict(original, population=500, initial_infections=2,
        target_groups={"students": 400, "employees": 100},
        target_roles={"undergraduate_students": 330, "non_undergraduate_students": 70,
                      "teachers": 10, "staff": 90},
        engine_overrides={"campus_age_data": [[17,23,.66],[24,30,.14],[31,65,.20]],
            "campus_age_counts": [330,70,100], "campus_teacher_ratio": .02, "campus_staff_ratio": .18})
    monkeypatch.setattr(data, "load_e0_config", lambda *a, **kw: config)
    monkeypatch.setattr(artifacts, "load_calibration_artifact", lambda *a, **kw:
                        SimpleNamespace(beta=.038583333332, sha256=ANCHOR))
    small = replace(protocol, population=500, initial_infections=2)
    return small, generate_history_snapshots(small, ANCHOR, tmp_path / "library", 20101, "val")


def make_env(world, index=0, seed=123, horizon=14, mode="evaluation"):
    protocol, paths = world
    env = WeeklyControlEnvironment(protocol, mode=mode, purpose="scientific",
        scenario_options={"snapshot_path": paths[index], "future_seed": seed,
                          "calibration_artifact": ANCHOR, "execution_days": horizon})
    return env, env.reset(20101)[0]


def test_shared_training_pool_filter_and_seed_independence(protocol,tmp_path):
    definition=resolved_snapshot(protocol.definition)
    definition['snapshot_training']['library']=str(tmp_path)
    configured=replace(protocol,definition=definition)
    worlds=history_seeds(configured,'train')
    for history in worlds:
        for day in (21,35,49,63):
            (tmp_path/f'{history}-{day}.json').write_text(json.dumps({
                'active_infections':0 if day>=49 and history==worlds[0] else 1}))
    first=SnapshotEpisodePlan(configured,11,ANCHOR)
    same=SnapshotEpisodePlan(configured,11,ANCHOR)
    other=SnapshotEpisodePlan(configured,22,ANCHOR)
    assert first.worlds==other.worlds==worlds and len(worlds)==128 and first.filtered_count==2
    n=len(first.items); rows=[first() for _ in range(n*2)]; others=[other() for _ in range(n)]
    assert rows==[same() for _ in range(n*2)]
    key=lambda r:r['scenario_options']['snapshot_path']
    assert {key(r) for r in rows[:n]}=={key(r) for r in others}
    assert [key(r) for r in rows[:n]]!=[key(r) for r in others]
    seeds={key(r):r['scenario_options']['future_seed'] for r in rows[:n]}
    assert all(seeds[key(r)]!=r['scenario_options']['future_seed'] for r in others+rows[n:])
    assert [len(snapshot_scenarios(protocol,s)) for s in ('val','test')]==[36,480]
    pools=[set(history_seeds(protocol,s)) for s in ('train','val','test','pilot')]
    assert all(not a&b for i,a in enumerate(pools) for b in pools[i+1:])


def test_val36_sorted_capacity_groups(protocol):
    assert history_seeds(protocol,'val')==tuple(range(20101,20110))
    rows=snapshot_scenarios(protocol,'val')
    assert len({r['scenario_id'] for r in rows})==36
    for capacity,start in ((.02,20101),(.05,20104),(.10,20107)):
        group=[r for r in rows if r['scenario_options']['screening_capacity_ratio']==capacity]
        assert len(group)==12
        assert {r['world_seed'] for r in group}==set(range(start,start+3))
        for history in range(start,start+3):
            assert sorted(r['snapshot_day'] for r in group if r['world_seed']==history)==[21,35,49,63]


@pytest.mark.parametrize('index',[0,1,2,3])
def test_snapshot_history_and_common_observation_before_action(small_world,index):
    env,obs=make_env(small_world,index)
    assert env._bundle.sim.t==(21,35,49,63)[index] and obs.decision_day==0
    assert obs.initial_infections==2 and obs.history[-1].end_day==-1
    assert sum(obs.week_valid)==(3 if index==0 else 4)
    assert encode_observation(obs).shape==(len(SNAPSHOT_FEATURE_NAMES),)
    assert env._bundle.sim['beta_layer']['ta']==pytest.approx(.6)
    for action in (-1,324,True,323):
        with pytest.raises((ValueError,TypeError)): env.step(action)
    with pytest.raises(ValueError,match='protocol-fixed'): env.step_proposal(None)
    assert env.audit_snapshot().elapsed_days==0
    obs, _, _, _, _ = env.advance_initial_week()
    assert obs.decision_day == 7 and sum(obs.week_valid) == 4
    env.step(242)
    assert env._bundle.executor.current_action.values==(2,0,2,2,2)
    env.close()


def test_features_hide_time_and_extension_horizon(small_world):
    env,obs=make_env(small_world,index=1)
    later=replace(obs,execution_days=168,decision_day=14,
        history=tuple(replace(w,start_day=w.start_day-14,end_day=w.end_day-14)
                      if valid else w for w,valid in zip(obs.history,obs.week_valid)))
    np.testing.assert_array_equal(encode_observation(obs),encode_observation(later))
    assert not any('start_day' in n or 'end_day' in n or 'decision_day' in n or 'execution_days' in n
                   for n in SNAPSHOT_FEATURE_NAMES)
    assert sum(n.endswith('is_history_week') for n in SNAPSHOT_FEATURE_NAMES)==4
    assert not any('field_valid' in n or 'historical_policy' in n or 'split_valid' in n for n in SNAPSHOT_FEATURE_NAMES)
    env.close()


def test_two_disk_loads_reproduce_119_days_and_count_control_period(small_world):
    traces=[]
    for mode in ('training','evaluation'):
        env,_=make_env(small_world,index=1,horizon=119,mode=mode)
        env.advance_initial_week()
        for step in range(16):
            _,_,terminated,truncated,_=env.step(0)
            assert not terminated and truncated==(step==15)
        audit=env.audit_snapshot()
        assert audit.status=='completed' and len(audit.windows)==17
        after=int(env._bundle.sim.results['cum_infections'][-1])-audit.manifest['cum_infections_at_x']
        assert audit.terminal_metrics.new_infections==after and audit.terminal_metrics.initial_infections==0
        assert sum(audit.manifest['group_new_infections'].values())==sum(d.new_infections for d in audit.private_daily[7:])
        traces.append((audit.public_daily,audit.private_daily)); env.close()
    assert traces[0]==traces[1]


def test_pending_event_delivered_without_source_account(small_world):
    _,paths=small_world; path=Path(paths[1]); metadata=json.loads(path.read_text())
    state=path.parent/metadata['state_file']; saved=cloudpickle.loads(state.read_bytes())
    sim=saved['sim']; person=int(np.flatnonzero(sim.people.susceptible)[0])
    sim.people._pending_quarantine[sim.t+1].append((person,sim.t+8))
    state.write_bytes(cloudpickle.dumps(saved))
    env,_=make_env(small_world,index=1); env.step(0)
    assert sum(r.cost.delivered_notifications for r in env.audit_snapshot().public_daily)>=1
    env.step(0); assert env.audit_snapshot().status=='completed'; env.close()


def test_lightweight_loading_rejects_version_without_hashing(small_world,monkeypatch):
    from cemas.control import snapshots
    monkeypatch.setattr(snapshots,'file_hash',lambda *a: (_ for _ in ()).throw(AssertionError('load hashed data')))
    env,_=make_env(small_world); env.close()
    _,paths=small_world; path=Path(paths[0]); metadata=json.loads(path.read_text()); state=path.parent/metadata['state_file']
    saved=cloudpickle.loads(state.read_bytes()); saved['version']='unsupported'; state.write_bytes(cloudpickle.dumps(saved))
    with pytest.raises(ValueError,match='version'): make_env(small_world)
    with pytest.raises(FileNotFoundError):
        snapshots.restore_snapshot(small_world[0],path.parent/'absent.json',20101,2,.038)


def test_static_serialization_preserves_capture_state(small_world,monkeypatch,tmp_path):
    protocol,_=small_world; original=cloudpickle.dump; captures=[]
    def check(saved,handle):
        original(saved,handle); handle.flush(); loaded=cloudpickle.loads(Path(handle.name).read_bytes())
        assert loaded['version']==SNAPSHOT_SCHEMA
        for key in ('uid','age','date_exposed','date_infectious','date_recovered','date_diagnosed',
                    'date_quarantined','date_end_quarantine','date_tested'):
            np.testing.assert_array_equal(getattr(saved['sim'].people,key),getattr(loaded['sim'].people,key))
        for layer in saved['sim'].people.contacts:
            for key in ('p1','p2','beta'):
                np.testing.assert_array_equal(saved['sim'].people.contacts[layer][key],loaded['sim'].people.contacts[layer][key])
        captures.append(saved['sim'].t)
    monkeypatch.setattr(cloudpickle,'dump',check)
    generate_history_snapshots(protocol,ANCHOR,tmp_path/'static',20102,'val',days=[21,35])
    assert captures==[21,35]


def test_future_seed_preserves_initial_state_changes_contacts(small_world):
    states=[]; contacts=[]
    for seed in (123,456):
        env,_=make_env(small_world,index=1,seed=seed); states.append(env._bundle.sim.people.date_exposed.copy())
        env.step(0); contacts.append(env._bundle.sim.people.contacts['cm']['p1'].copy()); env.close()
    np.testing.assert_array_equal(*states); assert not np.array_equal(*contacts)


def test_history_json_uses_null_without_flag_matrix(small_world):
    from cemas.control.logging import public_observation_to_dict
    env,obs=make_env(small_world,index=1); week=public_observation_to_dict(obs)['history'][-1]
    assert week['historical'] and week['resources'] is None and week['executed_action'] is None
    assert week['cost']['clinical_tests'] is None and week['total_tests']>=0
    assert 'field_valid' not in week and 'historical_policy' not in week; env.close()


def gym_factory(small_world):
    from cemas.control.rl.env import GymControlEnv
    protocol,paths=small_world
    def build():
        plan=lambda seed=None:{'world_seed':20101,'scenario_options':{
            'snapshot_path':paths[1],'future_seed':321,'calibration_artifact':ANCHOR,'execution_days':21}}
        return GymControlEnv(WeeklyControlEnvironment(protocol,purpose='scientific',mode='training'),plan,
                            reference_population=500,reference_horizon=112)
    return build


@pytest.mark.parametrize('method',['ppo','ddqn'])
def test_learners_bootstrap_update_and_reload(small_world,tmp_path,method):
    import torch
    from stable_baselines3.common.vec_env import DummyVecEnv
    from cemas.control.rl.ppo import build_ppo,PPOController
    from cemas.control.rl.ddqn import DDQNTrainer,DDQNController
    torch.set_num_threads(1); protocol,_=small_world; vec=DummyVecEnv([gym_factory(small_world)])
    config=resolved_snapshot(protocol.definition['controllers'][method])
    try:
        if method=='ppo':
            learner=build_ppo(vec,config,11); before=[p.detach().clone() for p in learner.policy.parameters()]
            predict=learner.policy.predict_values
            learner.policy.predict_values=lambda obs: torch.full((len(obs),1),2.,device=obs.device)
            original_step=vec.envs[0].step; actual=[]
            def record(action):
                result=original_step(action); actual.append((result[1],result[3])); return result
            vec.envs[0].step=record
            learner.learn(256)
            expected=np.array([reward+2. if truncated else reward for reward,truncated in actual])
            np.testing.assert_allclose(learner.rollout_buffer.rewards.ravel(),expected,atol=1e-6)
            assert any(not torch.equal(a,b) for a,b in zip(before,learner.policy.parameters()))
            learner.policy.predict_values=predict; path=tmp_path/'ppo.zip'; learner.save(path)
            loaded=PPOController.load(path,reference_population=500,reference_horizon=112)
            features=vec.reset()[0]; mask=vec.env_method('action_masks')[0]
            assert loaded.predict(features,mask)==int(learner.predict(features,deterministic=True,action_masks=mask)[0])
        else:
            learner=DDQNTrainer(vec,config,11,initial_budget=8192)
            before=[p.detach().clone() for p in learner.online.parameters()]; learner.train(513)
            assert learner.gradient_updates>=1 and not learner.replay.terminated[:513].any()
            assert any(not torch.equal(a,b) for a,b in zip(before,learner.online.parameters()))
            path=tmp_path/'ddqn.pt'; learner.save(path)
            loaded=DDQNController.load(path,reference_population=500,reference_horizon=112)
            assert loaded.network.observation_size==len(SNAPSHOT_FEATURE_NAMES)
            for a,b in zip(learner.online.parameters(),loaded.network.parameters()): assert torch.equal(a,b)
    finally: vec.close()


@pytest.mark.parametrize('time_limit',[False,True])
def test_ddqn_bootstrap_uses_finished_world_observation_and_mask(protocol,time_limit):
    from cemas.control.rl.ddqn import DDQNTrainer
    class Vec:
        num_envs=1
        observation_space=SimpleNamespace(shape=(len(SNAPSHOT_FEATURE_NAMES),))
        def reset(self): return np.zeros((1,len(SNAPSHOT_FEATURE_NAMES)),dtype=np.float32)
        def env_method(self,name): return [np.ones(324,dtype=bool)]
        def step(self,actions):
            mask=np.zeros(324,dtype=bool); mask[2]=True
            return self.reset(),np.array([-1.]),np.array([True]),[{
                'terminal_observation':np.full(len(SNAPSHOT_FEATURE_NAMES),7.,dtype=np.float32),
                'TimeLimit.truncated':time_limit,'next_mask':mask}]
    trainer=DDQNTrainer(Vec(),resolved_snapshot(protocol.definition['controllers']['ddqn']),11,initial_budget=8192)
    trainer.train(1)
    np.testing.assert_array_equal(trainer.replay.next_observations[0],7.)
    assert trainer.replay.terminated[0]==(not time_limit)
    assert np.flatnonzero(trainer.replay.next_masks[0]).tolist()==[2]


def test_single_validation_selection_without_second_round(small_world,tmp_path):
    from cemas.control.training import tune_threshold,select_checkpoint
    protocol,_=small_world
    def evaluate(job):
        assert 20101<=job['world_seed']<=20109
        return {'world_seed':job['world_seed'],'scenario_id':job['scenario_id'],'snapshot_day':job['snapshot_day'],
            'summary':{'status':'completed','positive_cost':1.,'reward_breakdown':{'normalized':[0.,0.,0.,0.,.1]}}}
    result=tune_threshold(protocol,tmp_path/'threshold',None,evaluator=evaluate)
    assert result['selection']['validation_episode_count']==1152
    assert all('validation_B' not in r and 'validation_A' not in r for r in result['selection']['candidates'])
    rows=[{'train_seed':11,'step':s,'artifact':str(s),'validation':{'mean_positive_cost':c}}
          for s,c in [(2048,2.),(4096,1.),(6144,1.)]]
    selected=select_checkpoint(protocol,rows,lambda _: (_ for _ in ()).throw(AssertionError('B invoked')))
    assert selected['selected']['step']==4096


def test_fixed_horizon_and_independent_test_extension(protocol,tmp_path):
    from cemas.control.artifacts import horizon_report
    from cemas.control.training import evaluate_source
    with pytest.raises(ValueError,match='fixed'): horizon_report(protocol,{})
    jobs=[]
    def evaluate(job):
        jobs.append(job)
        return {'world_seed':job['world_seed'],'scenario_id':job['scenario_id'],'snapshot_day':job['snapshot_day'],
            'summary':{'status':'completed','positive_cost':1.,'reward_breakdown':{'normalized':[0.]*5}}}
    evaluate_source(protocol,{'method':'minimum'},tmp_path/'test',ANCHOR,pool='test',execution_days=168,evaluator=evaluate)
    assert len(jobs)==480 and all(j['purpose']=='snapshot_test' and j['scenario_options']['execution_days']==175 for j in jobs)


def test_budget_counts_steps_and_completed_episodes_only(small_world,tmp_path):
    from cemas.control.artifacts import training_budget
    env=gym_factory(small_world)(); events=[]; env.private_record_sink=events.append
    env.reset(); assert events==[]
    env.step(0); env.step(0); env.reset(); env.close()
    assert len(events)==2 and all(e['event']=='transition' for e in events)
    path=tmp_path/'events.jsonl'; path.write_text('\n'.join(json.dumps(e) for e in events),encoding='utf-8')
    budget=training_budget(path)
    assert budget['step_count']==2 and budget['episode_count']==1 and budget['simulated_days']==21
    assert budget['control_simulated_days']==14 and budget['observation_positive_cost']>=0
    assert 'initialized_unstepped_worlds' not in budget


def test_independent_baseline_test_report_clustered_pairing(protocol,tmp_path):
    from cemas.control.training import compare_snapshot_baselines
    reports={}
    scenarios=snapshot_scenarios(protocol,'test')
    for method in ('ppo','ddqn','threshold','minimum','maximum_feasible'):
        reports[method]=[]
        for seed in ((11,22,33) if method in ('ppo','ddqn') else (None,)):
            cost=1. if method=='minimum' else .75
            rows=[{'method':method,'train_seed':seed,'scenario_id':s['scenario_id'],
                'world_seed':s['world_seed'],'snapshot_day':s['snapshot_day'],
                'day112_active_infections':3,'snapshot_active_infections':0 if s['snapshot_day']==63 else 10,
                'summary':{'status':'completed','execution_days':119,'control_period':{'execution_days':112},'positive_cost':cost,
                    'group_new_infections':{'students':8,'employees':2},
                    'reward_breakdown':{'normalized':[cost,0.,0.,0.,0.]}}} for s in scenarios]
            path=tmp_path/f'{method}-{seed}.json'
            path.write_text(json.dumps({'purpose':'snapshot_test','records':rows}),encoding='utf-8')
            reports[method].append(str(path))
    result=compare_snapshot_baselines(protocol,reports,tmp_path/'comparison')
    assert result['history_worlds']==20 and len(result['strata'])==13
    primary=result['strata']['day21-capacity0.05']['ppo']
    assert primary['cost_difference_vs_minimum']==-.25
    assert primary['paired_95pct_interval']==[-.25,-.25]
    assert result['strata']['all']['minimum']['zero_active_snapshot_fraction']==.25
    assert (tmp_path/'comparison/report.md').exists()
    reports['ppo'][1]=reports['ppo'][0]
    with pytest.raises(ValueError,match='distinct'):
        compare_snapshot_baselines(protocol,reports,tmp_path/'invalid')


def test_frozen_extension_keeps_112_reward_scale_and_finishes(small_world,tmp_path):
    from cemas.control.runner import run_episode
    from cemas.control.controllers import MinimumController
    from cemas.control.rewards import V1RewardCalculator
    protocol,paths=small_world
    calculator=V1RewardCalculator(protocol,500,168)
    assert calculator.configuration['denominators']==V1RewardCalculator(protocol,500,112).configuration['denominators']
    # Test runner purpose with the actual reserved test seed, using generated fixture state.
    library=Path(paths[0]).parent
    generate_history_snapshots(protocol,ANCHOR,library,50001,'test',days=[21])
    result=run_episode(protocol,MinimumController(),tmp_path/'extension',50001,purpose='snapshot_test',
        scenario_options={'snapshot_path':str(library/'50001-21.json'),'future_seed':99,
            'calibration_artifact':ANCHOR,'execution_days':175})
    assert result.summary['decision_count']==24 and result.summary['elapsed_days']==175
