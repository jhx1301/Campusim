"""Static design acceptance only: no model, simulator, training or dependency install."""
import hashlib
import importlib.util
import json
import math
import re
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
DOCS = HERE.parent


def read(name):
    return json.loads((HERE / name).read_text(encoding="utf-8"))


def canonical(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)


def digest(value):
    return hashlib.sha256(canonical(value).encode("utf-8")).hexdigest()


module_spec = importlib.util.spec_from_file_location("public_contract_fixture", ROOT / "cemas/control/types.py")
types = importlib.util.module_from_spec(module_spec)
sys.modules[module_spec.name] = types
module_spec.loader.exec_module(types)


def week(raw):
    value = dict(raw)
    value["cost"] = types.PublicCost(**value["cost"])
    value["executed_action"] = types.ActionVector(value["executed_action"]["values"])
    value["resources"] = types.PublicResources(**value["resources"])
    return types.PublicWeeklyRecord(**value)


def observation(raw):
    value = dict(raw)
    value["population"] = types.PublicPopulation(**dict(value["population"], age_band_counts=tuple(value["population"]["age_band_counts"])))
    value["resources"] = types.PublicResources(**value["resources"])
    value["current_action"] = types.ActionVector(value["current_action"]["values"])
    for key in ("action_duration_days", "legal_action_mask", "week_valid"):
        value[key] = tuple(value[key])
    value["history"] = tuple(week(w) for w in value["history"])
    return types.PublicObservation(**value)


def resolve_pointer(value, pointer):
    assert pointer.startswith("/")
    for token in pointer[1:].split("/"):
        token = token.replace("~1", "/").replace("~0", "~")
        value = value[int(token)] if isinstance(value,list) else value[token]
    return value


def action_id(values):
    t,s,c,e,a=types.ActionVector(values).values
    return 108*t+27*s+9*c+3*e+a


counts={"public_observations":0,"weekly_records":0,"responses":0,"registry_references":0,"hashes":0,"local_links":0}
manifest=read("manifest.json")
for name,expected in manifest["files"].items():
    assert hashlib.sha256((HERE/name).read_bytes()).hexdigest()==expected, name
    counts["hashes"]+=1
assert manifest["synthetic_example"] is True
knowledge=read("knowledge_cards.json")
assert not knowledge["conflict_pairs"]
assert len({c["id"] for c in knowledge["cards"]})==9
cardmap={c["id"]:c for c in knowledge["cards"]}
for i in range(1,7):
    assert cardmap[f"SIM-0{i}"]["trigger"]=="always"
assert cardmap["PH-01"]["source"]["publisher"]=="US CDC"
assert cardmap["PH-02"]["source"]["publisher"]=="UK Health Security Agency"
assert cardmap["PH-03"]["source"]["publisher"]=="World Health Organization"

systems=[]
payloads=[]
allowed_codes={"partial_observability","no_history","testing_changed","capacity_changed","no_case","case_conflict","out_of_support","truncated_followup"}
for mode in ("none","both","failure"):
    messages=read(mode+"_messages.json")
    assert [m["role"] for m in messages]==["system","user"]
    assert "${" not in messages[0]["content"]
    systems.append(messages[0]["content"])
    p=json.loads(messages[1]["content"])
    payloads.append(p)
    assert set(p)=={"observation","public_rates","memory","evidence_registry","required_uncertainty_codes"}
    o=observation(p["observation"])
    counts["public_observations"]+=1
    counts["weekly_records"]+=4
    assert sum(o.legal_action_mask)==243
    for i,legal in enumerate(o.legal_action_mask):
        s=(i//27)%4
        assert legal==(math.ceil((0,.02,.05,.1)[s]*o.population.population)<=o.resources.screening_daily_capacity)
    for i,w in enumerate(o.history):
        tests=w.cost.clinical_tests+w.cost.screening_tests
        assert math.isclose(w.diagnosis_test_proxy,w.delivered_diagnoses/tests)
        assert p["public_rates"]["history"][i]["delivered_diagnoses_over_population"]==w.delivered_diagnoses/o.population.population
        assert w.growth_valid==(i>0)
        if i:
            assert math.isclose(w.growth,math.log2((w.delivered_diagnoses+1)/(o.history[i-1].delivered_diagnoses+1)))
    ks={c["id"] for c in p["memory"]["knowledge"]}
    cs={str(x["case"]["case_id"]) for x in p["memory"]["retrieval"]["items"]}
    registry=p["evidence_registry"]
    assert len(registry)==len(set(registry))
    for eid in registry:
        kind,ref=eid.split(":",1)
        if kind=="O":
            resolve_pointer(p["observation"],ref)
            if ref.startswith("/history/"):
                assert p["observation"]["week_valid"][int(ref.split("/")[2])]
        elif kind=="R":resolve_pointer(p["memory"]["recent"],ref)
        elif kind=="K":assert ref in ks
        elif kind=="C":assert ref in cs
        else:raise AssertionError(eid)
        counts["registry_references"]+=1
    walk=read(mode+"_walkthrough.json")
    assert walk["synthetic_example"] and not walk["real_model_result"]
    assert digest(messages)==walk["messages_sha256"]
    r=walk["proposed_response"]
    assert set(r)=={"action","reason","evidence_ids","alternative_actions","uncertainty_codes"}
    assert o.legal_action_mask[action_id(r["action"])]
    assert 1<=len(r["reason"])<=120 and not any(c in r["reason"] for c in "\r\n")
    assert 1<=len(r["evidence_ids"])<=8 and set(r["evidence_ids"])<=set(registry)
    assert len(r["evidence_ids"])==len(set(r["evidence_ids"]))
    assert set(p["required_uncertainty_codes"])<=set(r["uncertainty_codes"])<=allowed_codes
    assert 1<=len(r["uncertainty_codes"])<=8
    for alt in r["alternative_actions"]:
        assert set(alt)=={"action","tradeoff","evidence_ids"}
        assert alt["action"]!=r["action"] and o.legal_action_mask[action_id(alt["action"])]
        assert 1<=len(alt["tradeoff"])<=80 and not any(c in alt["tradeoff"] for c in "\r\n")
        assert 1<=len(alt["evidence_ids"])<=4 and set(alt["evidence_ids"])<=set(registry)
    counts["responses"]+=1
assert len(set(systems))==1
assert all(p["observation"]==payloads[0]["observation"] for p in payloads)
assert all(p["public_rates"]==payloads[0]["public_rates"] for p in payloads)
assert payloads[0]["memory"]["recent"] is None
assert not payloads[0]["memory"]["retrieval"]["items"]

cases=read("synthetic_cases.json")["cases"]
for c in cases:
    pre=observation(c["pre_observation"])
    first=week(c["executed_window"]); follow=week(c["followup_window"])
    counts["public_observations"]+=1; counts["weekly_records"]+=6
    assert first.start_day==pre.decision_day and first.end_day==first.start_day+6
    assert follow.start_day==first.end_day+1 and follow.end_day==follow.start_day+6
    assert c["window_days"]==7 and c["available_through_day"]==follow.end_day
    assert c["attribution"]=="descriptive_not_causal"
    for key,value in (("observation_sha256",c["pre_observation"]),("feedback_sha256",c["executed_window"]),("followup_sha256",c["followup_window"])):
        assert c["public_source"][key]==digest(value)
q=read("query_and_retrieval.json")
assert len(q["query"]["state"])==len(q["state_scale"])==38
assert len(q["query"]["trend"])==2 and all(len(t)==5 for t in q["query"]["trend"])
for score in q["pool_scores"]:
    assert math.isclose(score["state_score"],math.exp(-score["state_rms"]))
    assert math.isclose(score["final_score"],.75*score["state_score"]+.25*score["trend_score"])
    assert score["state_rms"]<=3 and score["final_score"]>=.35
assert cases[0]["executed_window"]["delivered_diagnoses"]-cases[0]["pre_observation"]["history"][-1]["delivered_diagnoses"]<=-5
assert cases[1]["executed_window"]["delivered_diagnoses"]-cases[1]["pre_observation"]["history"][-1]["delivered_diagnoses"]>=5
assert cases[0]["executed_window"]["executed_action"]==cases[1]["executed_window"]["executed_action"]

tail=read("terminal_feedback.json")
pre=observation(tail["pre_observation"])
f=types.PublicWeekFeedback(week(tail["feedback"]["week"]),week(tail["feedback"]["previous_week"]))
counts["public_observations"]+=1; counts["weekly_records"]+=6
assert pre.decision_day==f.week.start_day==105 and pre.execution_days==f.week.end_day+1==110
assert f.week.end_day-f.week.start_day+1==5 and not f.week.growth_valid and f.week.growth==0
assert f.previous_week.end_day==104
assert tail["expected"]["new_decision_calls"]==tail["expected"]["additional_simulation_days"]==0

for path in DOCS.rglob("*.md"):
    text=path.read_text(encoding="utf-8")
    assert "\ufffd" not in text, path
    for target in re.findall(r"\]\(([^)]+)\)",text):
        target=target.strip("<>").split("#",1)[0]
        if not target or re.match(r"[a-z]+://",target):continue
        target=re.sub(r":\d+$","",target)
        assert (path.parent/target).exists(),(path,target)
        counts["local_links"]+=1

result={"status":"passed","scope":"documentation synthetic structure and arithmetic only","checks":counts,
        "simulation_runs":0,"model_calls":0,"official_token_count":None,"runtime_memory_implementation_tested":False,
        "notes":["Loaded existing types.py dataclasses without importing simulator.","No real API, efficacy, cost or causal conclusion validated."]}
(HERE/"verification.json").write_text(json.dumps(result,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
print(json.dumps(result,ensure_ascii=False))
