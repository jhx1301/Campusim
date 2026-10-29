"""Hand-computable numeric features, threshold boundaries, and selection order."""
from dataclasses import replace
from math import exp, sqrt
import sqlite3

import pytest

from cemas.control.memory import MemoryProfile, load_memory_profile
from cemas.control.memory_store import CaseStoreUnavailable
from cemas.control.memory_types import (CASE_SCHEMA_VERSION, PublicCase, public_hash, public_to_dict)
from cemas.control.retrieval import (NumericRetriever, build_case_query, retrieve,
    _state_distance, _configuration)
from cemas.control.types import (ActionVector, PublicCost, PublicObservation,
    PublicPopulation, PublicResources, PublicWeeklyRecord)

TASK = "a"*64
ZERO = ActionVector((0,0,0,0,0))


def observation(diagnoses=(10,),population=None,resources=None,cost=None):
    population = population or PublicPopulation(100,(10,20,20,40,10),20,40,5)
    resources = resources or PublicResources(2,5,1)
    cost = cost or PublicCost(clinical_tests=70)
    weeks = tuple(PublicWeeklyRecord(i*7,i*7+6,value,cost,ZERO,resources,growth_valid=True)
                  for i,value in enumerate(diagnoses))
    padding = 4-len(weeks)
    return PublicObservation(len(weeks)*7,112,1,population,resources,ZERO,(0,)*5,(True,)*324,
        (PublicWeeklyRecord(),)*padding+weeks,(False,)*padding+(True,)*len(weeks))


def case(case_id,pre=None,after=10,action=ZERO,resources=None,task=TASK):
    pre = pre or observation()
    day = pre.decision_day
    executed = PublicWeeklyRecord(day,min(day+6,pre.execution_days-1),after,executed_action=action,
        resources=resources or pre.resources)
    return PublicCase(case_id,1,CASE_SCHEMA_VERSION,task,pre,executed,
        executed.end_day-executed.start_day+1,
        "closed",
        executed.end_day,"descriptive_not_causal",(),"Descriptive public record.",
        {"kind":"source_simulation","observation_sha256":public_hash(pre),
            "week_sha256":public_hash(executed)})


class Store:
    def __init__(self,cases,groups=None,error=None):
        self.records,self.groups,self.error = tuple(cases),groups or {},error

    def cases(self):
        if self.error:
            raise self.error
        return self.records

    def group_for(self,case_id):
        return self.groups.get(case_id,f"private-opaque-{case_id}")


def test_38_raw_features_order_scales_validity_and_action_onehot():
    cost = PublicCost(clinical_tests=14,screening_tests=70,delivered_notifications=70,
        isolation_person_days=14,quarantine_person_days=21,union_person_days=28,
        school_restriction_person_days=70,work_restriction_person_days=140,community_restriction_person_days=70)
    pre = observation((1,),cost=cost)
    last = replace(pre.history[-1],growth=.5)
    pre = replace(pre,history=pre.history[:-1]+(last,),current_action=ActionVector((1,2,1,0,2)))
    query = build_case_query(pre,TASK,load_memory_profile())
    assert len(query.state)==len(query.state_valid)==38
    assert query.state[:10]==pytest.approx((.01,.12,.10,.02,.03,.04,.5,.5,.1,.5))
    assert query.state[10:22]==pytest.approx((.02,.05,.01,105/112,.2,.4,.05,.1,.2,.2,.4,.1))
    assert query.state[22:]==(0,1,0,0,0,1,0,0,1,0,1,0,0,0,0,1)
    assert all(query.state_valid)
    assert query.trend==()
    empty = build_case_query(observation(()),TASK)
    assert empty.state_valid[:10]==(False,)*10
    no_targets = replace(pre,population=PublicPopulation(100,(10,20,20,40,10),0,0))
    assert build_case_query(no_targets,TASK).state_valid[6:8]==(False,False)


def test_raw_trend_deltas_normalized_exactly_once_and_constant_is_valid():
    query = build_case_query(observation((10,11,12)),TASK)
    source = case(1,observation((10,10,10)),after=11)
    result = retrieve(query,Store((source,)))
    assert result.status=="ok"
    item = result.items[0]
    # Only diagnosis differs: state distance=2/sqrt(38); trend has two
    # unit-scaled diagnosis deltas among ten cells, RMS=sqrt(2/10).
    assert query.trend[0][0]==pytest.approx(.01)
    assert item.state_rms==pytest.approx(2/sqrt(38))
    assert item.trend_score==pytest.approx(exp(-sqrt(.2)))
    assert item.final_score==pytest.approx(.75*exp(-2/sqrt(38))+.25*exp(-sqrt(.2)))
    constant = build_case_query(observation((10,10,10)),TASK)
    equal = retrieve(constant,Store((source,))).items[0]
    assert equal.trend_score==equal.state_score==equal.final_score==1


def test_trend_rows_right_align_and_missing_trend_uses_state_weight_one():
    query = build_case_query(observation((10,11,13)),TASK)
    source = case(1,observation((11,13)),after=13)
    item = retrieve(query,Store((source,))).items[0]
    assert item.trend_score==pytest.approx(1)
    first = retrieve(build_case_query(observation(),TASK),Store((case(2),))).items[0]
    assert first.trend_score is None
    assert first.final_score==first.state_score==1
    assert "trend_missing" in first.applicability_codes


def test_overlap_exact_75_percent_is_inclusive_missing_is_not_stable():
    pre = observation(population=PublicPopulation(100,(10,20,20,40,10),0,0))
    pre = replace(pre,history=pre.history[:-1]+(replace(pre.history[-1],growth_valid=False),))
    source = build_case_query(pre,TASK)
    common = [i for i,valid in enumerate(source.state_valid) if valid][:27]
    validity = tuple(i in common or i==6 for i in range(38))
    query = replace(source,state_valid=validity)
    assert sum(a and b for a,b in zip(query.state_valid,source.state_valid))==27
    assert sum(a or b for a,b in zip(query.state_valid,source.state_valid))==36
    assert _state_distance(query,source,_configuration(None))==(0,1)
    below = replace(query,state_valid=tuple(value if i!=common[-1] else False for i,value in enumerate(validity)))
    assert _state_distance(below,source,_configuration(None)) is None
    result = retrieve(below,Store((case(1,pre),)))
    assert result.status=="empty" and result.excluded_counts["valid_overlap"]==1


def test_capacity_boundaries_use_actual_first_window_and_public_ratios():
    population = PublicPopulation(200,(20,40,40,80,20),40,80,10)
    pre = observation(population=population,resources=PublicResources(4,10,2))
    query = build_case_query(pre,TASK)
    at_boundary = case(1,pre,resources=PublicResources(6,16,3))
    assert retrieve(query,Store((at_boundary,))).status=="ok"
    for capacities in (PublicResources(7,16,3),PublicResources(6,17,3),PublicResources(6,16,4)):
        result = retrieve(query,Store((case(2,pre,resources=capacities),)))
        assert result.status=="empty" and result.excluded_counts["resource"]==1
    # Same public rates with twice the population remain comparable.
    bigger = observation(population=population,resources=PublicResources(4,10,2),cost=PublicCost(clinical_tests=140),diagnoses=(20,))
    assert retrieve(build_case_query(observation(),TASK),Store((case(3,bigger),))).status=="ok"


def test_history_partial_task_and_action_hard_filters():
    day0 = observation(())
    week1 = observation()
    assert retrieve(build_case_query(day0,TASK),Store((case(1,week1),))).excluded_counts["history"]==1
    assert retrieve(build_case_query(week1,TASK),Store((case(1,day0),))).excluded_counts["history"]==1
    assert retrieve(build_case_query(day0,TASK),Store((case(1,day0),))).status=="ok"
    tail = replace(week1,execution_days=9)
    assert retrieve(build_case_query(tail,TASK),Store((case(1,tail),))).excluded_counts["partial_window"]==1
    assert retrieve(build_case_query(week1,TASK),Store((case(1,task="b"*64),))).excluded_counts["public_task"]==1
    action = ActionVector((1,0,0,0,0))
    mask = list(week1.legal_action_mask)
    from cemas.control.actions import encode_action
    mask[encode_action(action)] = False
    query = build_case_query(replace(week1,legal_action_mask=tuple(mask)),TASK)
    assert retrieve(query,Store((case(1,action=action),))).excluded_counts["illegal_action"]==1


def test_empty_out_of_support_and_known_io_have_distinct_semantics():
    query = build_case_query(observation(),TASK)
    assert retrieve(query,Store(())).status=="empty"
    far = case(1,observation((1000,)))
    assert retrieve(query,Store((far,))).status=="out_of_support"
    unavailable = retrieve(query,Store((),error=CaseStoreUnavailable("temporary read")))
    assert unavailable.status=="unavailable" and not unavailable.items
    with pytest.raises(sqlite3.DatabaseError):
        retrieve(query,Store((),error=sqlite3.DatabaseError("malformed database")))
    with pytest.raises(RuntimeError):
        retrieve(query,Store((),error=RuntimeError("unknown error")))


def test_conflict_pair_priority_beats_single_highest_score_and_then_different_action():
    query = build_case_query(observation(),TASK)
    highest = case(1,action=ActionVector((1,0,0,0,0)))
    positive = case(2,observation((11,)),after=16)
    negative = case(3,observation((11,)),after=6)
    result = retrieve(query,Store((highest,negative,positive)))
    assert [item.case.case_id for item in result.items]==[2,3,1]
    assert "case_conflict" in result.flags
    assert all("conflict_pair" in item.applicability_codes for item in result.items[:2])
    assert "conflict_pair" not in result.items[2].applicability_codes
    assert result.items[2].final_score>result.items[0].final_score
    assert "private-opaque" not in str(public_to_dict(result))


def test_conflict_pair_ties_ids_magnitude_and_group_constraints():
    query = build_case_query(observation(),TASK)
    records = (case(4,after=5),case(3,after=15),case(5,after=5),case(2,after=15))
    result = retrieve(query,Store(records))
    assert [item.case.case_id for item in result.items]==[2,4]
    same_group = retrieve(query,Store((case(1,after=15),case(2,after=5)),{1:"same",2:"same"}))
    assert "case_conflict" not in same_group.flags and len(same_group.items)==1
    weak = retrieve(query,Store((case(1,after=14),case(2,after=5))))
    assert "case_conflict" not in weak.flags


def test_greedy_second_action_then_content_group_and_action_limits():
    query = build_case_query(observation(),TASK)
    alternative = ActionVector((1,0,0,0,0))
    records = (case(1,after=10),case(2,after=11),case(3,observation((11,)),after=11,action=alternative),case(4,after=12))
    result = NumericRetriever(Store(records)).retrieve(query)
    assert [item.case.case_id for item in result.items]==[1,3,2]
    duplicate = replace(records[0],case_id=99,description="Same facts in other prose.")
    result = retrieve(query,Store((records[0],duplicate,records[2]),{1:"group-a",99:"group-b",3:"group-a"}))
    assert [item.case.case_id for item in result.items]==[1]


def test_pool_24_top_six_deterministic_independent_of_scan_order():
    query = build_case_query(observation(),TASK)
    actions = [ActionVector((t,0,c,0,0)) for t in range(3) for c in range(3)]
    records = tuple(case(i,after=10+i,action=actions[(i-1)%9]) for i in range(1,31))
    forward = retrieve(query,Store(records))
    backward = retrieve(query,Store(reversed(records)))
    assert forward==backward and len(forward.items)==6
    assert all(item.case.case_id<=24 for item in forward.items)
    assert forward.excluded_counts["pool_limit"]==6


@pytest.mark.parametrize("config",[{"top_k":7},{"maximum_per_action":3},{"maximum_per_group":2},
    {"state_scales":[0]*38},{"candidate_pool_size":25},{"minimum_valid_overlap":-1},{"typo":1},
    {"candidate_pool_size":1},{"minimum_valid_overlap":0},{"state_weight":0,"trend_weight":1},
    {"state_weight":.4},{"configuration_version":"unknown"},{"feature_version":"unknown"},
    {"conflict_minimum_diagnosis_change":0},{"conflict_minimum_diagnosis_change":.5}])
def test_configuration_cannot_relax_phase5_limits(config):
    with pytest.raises(ValueError):
        NumericRetriever(Store(()),config)


def test_profile_and_direct_retriever_share_zero_capacity_tolerance_contract():
    data = public_to_dict(load_memory_profile().data)
    data["retrieval"]["capacity_ratio_tolerances"] = [0,0,0]
    profile = MemoryProfile(data)
    pre = observation()
    query = build_case_query(pre,TASK,profile)
    records = (case(1,pre),case(2,pre,resources=PublicResources(3,5,1)))
    result = NumericRetriever(Store(records),profile).retrieve(query)
    assert [item.case.case_id for item in result.items]==[1]
    assert result.excluded_counts["resource"]==1
    assert retrieve(query,Store(records),profile.retrieval)==result
