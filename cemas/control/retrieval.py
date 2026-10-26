"""Deterministic 38-dimensional public-state and raw-difference retrieval."""
from __future__ import annotations

from collections import Counter
from collections.abc import Mapping
from dataclasses import replace
from math import exp, isclose, sqrt

from .actions import encode_action
from .memory import MemoryProfile, _validate_retrieval_config
from .memory_store import CaseStoreUnavailable, public_content_sha256
from .memory_types import (CASE_SCHEMA_VERSION, QUERY_SCHEMA_VERSION, CaseQuery,
    RetrievalItem, RetrievalResult)
from .types import ACTION_SIZES, PublicObservation

STATE_SCALES = (.01,.12,.10,.02,.05,.05,1,1,1,1,.02,.10,.01,1,1,1,1,*([1]*5),*([1]*16))
TREND_SCALES = (.01,.12,.10,.05,1)
DEFAULT_RETRIEVAL = {
    "configuration_version":"numeric-retrieval-v1","feature_version":"cemas-public-case-features-v1",
    "state_scales":STATE_SCALES,"trend_scales":TREND_SCALES,
    "state_weight":.75,"trend_weight":.25,"minimum_valid_overlap":.75,
    "maximum_state_rms":3,"minimum_score":.35,"capacity_ratio_tolerances":(.01,.03,.005),
    "candidate_pool_size":24,"top_k":6,"maximum_per_action":2,"maximum_per_group":1,
    "redundancy_penalty":.10,"conflict_minimum_state_score":.8,"conflict_minimum_diagnosis_change":5}


def _configuration(value):
    if type(value) is MemoryProfile:
        value = value.retrieval
    if value is not None and not isinstance(value,Mapping):
        raise ValueError("retrieval configuration has unsupported fields")
    config = {**DEFAULT_RETRIEVAL,**(dict(value) if value is not None else {})}
    _validate_retrieval_config(config)
    return config


def _rates(week,population):
    count = population.population
    cost = week.cost
    return (week.delivered_diagnoses/count,(cost.clinical_tests+cost.screening_tests)/(7*count),
        cost.delivered_notifications/(7*count),cost.union_person_days/(7*count),
        (cost.school_restriction_person_days+cost.work_restriction_person_days+cost.community_restriction_person_days)/(7*count))


def build_case_query(observation,public_task_sha256,profile=None):
    """Encode raw public rates; feature scales are applied only in distance RMS."""
    if type(observation) is not PublicObservation:
        raise TypeError("query requires an exact PublicObservation")
    if profile is not None:
        _configuration(profile)
    population,resources = observation.population,observation.resources
    count,school,work = population.population,population.school_population,population.work_population
    weeks = [week for week,valid in zip(observation.history,observation.week_valid) if valid]
    state,valid = [0.0]*10,[False]*10
    if weeks:
        week,cost = weeks[-1],weeks[-1].cost
        state = [week.delivered_diagnoses/count,(cost.clinical_tests+cost.screening_tests)/(7*count),
            cost.delivered_notifications/(7*count),cost.isolation_person_days/(7*count),
            cost.quarantine_person_days/(7*count),cost.union_person_days/(7*count),
            cost.school_restriction_person_days/(7*school) if school else 0.,
            cost.work_restriction_person_days/(7*work) if work else 0.,
            cost.community_restriction_person_days/(7*count),week.growth]
        valid = [True]*10
        valid[6],valid[7],valid[9] = bool(school),bool(work),week.growth_valid
    remaining = (observation.execution_days-observation.decision_day)/observation.execution_days
    state.extend((resources.clinical_daily_capacity/count,resources.screening_daily_capacity/count,
        resources.tracing_daily_index_capacity/count,remaining,school/count,work/count,population.school_work_population/count))
    state.extend(value/count for value in population.age_band_counts)
    state.extend(float(level==selected) for selected,size in zip(observation.current_action.values,ACTION_SIZES) for level in range(size))
    valid.extend([True]*28)
    rates = [_rates(week,population) for week in weeks[-3:]]
    trend = tuple(tuple(b-a for a,b in zip(before,after)) for before,after in zip(rates,rates[1:]))
    return CaseQuery(QUERY_SCHEMA_VERSION,public_task_sha256,tuple(state),tuple(valid),trend,
        tuple((True,)*5 for _ in trend),resources,observation.legal_action_mask,remaining)


def _state_distance(left,right,config):
    overlap = [i for i,(a,b) in enumerate(zip(left.state_valid,right.state_valid)) if a and b]
    union = sum(a or b for a,b in zip(left.state_valid,right.state_valid))
    if not overlap or len(overlap)/union<config["minimum_valid_overlap"]:
        return None
    rms = sqrt(sum(((left.state[i]-right.state[i])/config["state_scales"][i])**2 for i in overlap)/len(overlap))
    return rms,exp(-rms)


def _trend_score(left,right,config):
    cells = []
    # Reverse zip right-aligns up to two raw difference rows without padding.
    for a,b,av,bv in zip(reversed(left.trend),reversed(right.trend),reversed(left.trend_valid),reversed(right.trend_valid)):
        cells.extend(((x-y)/scale)**2 for x,y,valid_x,valid_y,scale in zip(a,b,av,bv,config["trend_scales"]) if valid_x and valid_y)
    return exp(-sqrt(sum(cells)/len(cells))) if cells else None


def _diagnosis_change(case):
    history = [week for week,valid in zip(case.pre_observation.history,case.pre_observation.week_valid) if valid]
    return case.executed_window.delivered_diagnoses-history[-1].delivered_diagnoses if history else None


class NumericRetriever:
    def __init__(self,store,config=None):
        self.store,self.config = store,_configuration(config)

    def retrieve(self,query):
        return retrieve(query,self.store,self.config)


def retrieve(query,store,config=None):
    """Scan public cases, then apply conflict priority and bounded greedy MMR."""
    if type(query) is not CaseQuery:
        raise TypeError("retrieval requires an exact CaseQuery")
    config = _configuration(config)
    version = config["configuration_version"]
    if store is None:
        return RetrievalResult("empty",configuration_version=version)
    excluded = Counter()
    try:
        cases = store.cases()
    except CaseStoreUnavailable:
        return RetrievalResult("unavailable",flags=("temporary_io",),configuration_version=version)
    pool,structural_count = [],0
    for case in cases:
        reason = None
        if case.schema_version!=CASE_SCHEMA_VERSION:
            reason = "schema"
        elif case.public_task_sha256!=query.public_task_sha256:
            reason = "public_task"
        elif case.public_source["kind"]!="source_simulation":
            reason = "source"
        elif case.window_days!=7:
            reason = "partial_window"
        elif query.remaining_fraction==1 and case.pre_observation.decision_day!=0:
            reason = "history"
        elif not query.legal_action_mask[encode_action(case.executed_window.executed_action)]:
            reason = "illegal_action"
        if reason:
            excluded[reason]+=1
            continue
        case_query = build_case_query(case.pre_observation,case.public_task_sha256)
        if query.has_history and not case_query.has_history:
            excluded["history"]+=1
            continue
        population = case.pre_observation.population.population
        capacities = case.executed_window.resources
        ratios = (capacities.clinical_daily_capacity/population,capacities.screening_daily_capacity/population,
                  capacities.tracing_daily_index_capacity/population)
        differences = (abs(a-b) for a,b in zip(query.state[10:13],ratios))
        if any(difference>tolerance and not isclose(difference,tolerance,rel_tol=1e-12,abs_tol=1e-15)
               for difference,tolerance in zip(differences,config["capacity_ratio_tolerances"])):
            excluded["resource"]+=1
            continue
        state = _state_distance(query,case_query,config)
        if state is None:
            excluded["valid_overlap"]+=1
            continue
        structural_count+=1
        rms,state_score = state
        trend_score = _trend_score(query,case_query,config)
        weight = config["state_weight"]+config["trend_weight"]
        score = (state_score if trend_score is None else
                 (config["state_weight"]*state_score+config["trend_weight"]*trend_score)/weight)
        if rms>config["maximum_state_rms"] or score<config["minimum_score"]:
            excluded["distance"]+=1
            continue
        codes = ("compatible",) if trend_score is not None else ("compatible","trend_missing")
        item = RetrievalItem(case,rms,state_score,trend_score,score,codes)
        pool.append((item,case_query,store.group_for(case.case_id),public_content_sha256(case)))
    if not pool:
        return RetrievalResult("out_of_support" if structural_count else "empty",
            excluded_counts=dict(excluded),configuration_version=version)
    pool.sort(key=lambda value:(-value[0].final_score,value[0].case.case_id))
    excluded["pool_limit"]+=max(0,len(pool)-config["candidate_pool_size"])
    pool = pool[:config["candidate_pool_size"]]
    pairwise = {}

    def similarity(a,b):
        key = tuple(sorted((a[0].case.case_id,b[0].case.case_id)))
        if key not in pairwise:
            distance = _state_distance(a[1],b[1],config)
            pairwise[key] = distance[1] if distance else 0.
        return pairwise[key]

    selected,conflict_ids = [],set()
    if config["top_k"]>=2 and config["maximum_per_action"]>=2:
        conflicts = []
        minimum_change = config["conflict_minimum_diagnosis_change"]
        for i,left in enumerate(pool):
            change_left = _diagnosis_change(left[0].case)
            if change_left is None or abs(change_left)<minimum_change:
                continue
            for right in pool[i+1:]:
                change_right = _diagnosis_change(right[0].case)
                if (left[0].case.executed_window.executed_action!=right[0].case.executed_window.executed_action
                        or left[2]==right[2] or left[3]==right[3] or change_right is None
                        or abs(change_right)<minimum_change or change_left*change_right>=0
                        or similarity(left,right)<config["conflict_minimum_state_score"]):
                    continue
                ids = tuple(sorted((left[0].case.case_id,right[0].case.case_id)))
                conflicts.append((-min(left[0].final_score,right[0].final_score),ids,left,right))
        if conflicts:
            winner = min(conflicts,key=lambda value:(value[0],value[1]))
            selected = sorted((winner[2],winner[3]),key=lambda value:(-value[0].final_score,value[0].case.case_id))
            conflict_ids = {row[0].case.case_id for row in selected}

    def eligible(candidate):
        item,_query,group,content = candidate
        action = item.case.executed_window.executed_action
        return (sum(row[0].case.executed_window.executed_action==action for row in selected)<config["maximum_per_action"]
                and sum(row[2]==group for row in selected)<config["maximum_per_group"]
                and all(row[3]!=content for row in selected))

    while len(selected)<config["top_k"]:
        available = [row for row in pool if row not in selected and eligible(row)]
        if not available:
            break
        actions = {row[0].case.executed_window.executed_action for row in selected}
        different = [row for row in available if row[0].case.executed_window.executed_action not in actions]
        if selected and len(actions)<2 and different:
            available = different
        def ranking(row):
            penalty = max((similarity(row,chosen) for chosen in selected),default=0.)
            return (-(row[0].final_score-config["redundancy_penalty"]*penalty),-row[0].final_score,row[0].case.case_id)
        selected.append(min(available,key=ranking))
    excluded["diversity"]+=len(pool)-len(selected)
    items = tuple(replace(row[0],applicability_codes=(*row[0].applicability_codes,"conflict_pair"))
                  if row[0].case.case_id in conflict_ids else row[0] for row in selected)
    flags = []
    if conflict_ids:
        flags.append("case_conflict")
    if any(item.trend_score is None for item in items):
        flags.append("trend_missing")
    return RetrievalResult("ok",items,tuple(flags),{k:v for k,v in excluded.items() if v},version)
