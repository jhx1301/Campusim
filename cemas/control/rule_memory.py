"""Aggregate rule statistics and deterministic public-state retrieval."""

from copy import deepcopy

from .feedback import FeedbackResponseError, exact, parse_json, project_week_sequence, references, text_field
from .knowledge import observation_flags
from .memory_types import public_hash, public_to_dict
from .retrieval import build_case_query, query_similarity


CONTENT_FIELDS = ("condition_ids", "lesson", "limitations")
JUDGMENT_VALUES = ("support", "contradict", "ignore")


def condition_catalog(cases, rules):
    catalog = {}

    def add(condition):
        catalog["COND:" + public_hash(condition)] = condition

    for case in cases:
        observation = case.pre_observation
        add({"kind": "resources", "value": public_to_dict(observation.resources)})
        for dimension, level in enumerate(observation.current_action.values):
            add({"kind": "action", "dimension": dimension, "value": level})
        add({"kind": "history", "value": sum(observation.week_valid)})
        for flag in observation_flags(observation):
            add({"kind": "flag", "value": flag})
    for rule in rules:
        catalog.update(rule.get("conditions", {}))
    return dict(sorted(catalog.items()))


def applicability(conditions, observation):
    results = []
    for condition in conditions.values():
        kind, expected = condition["kind"], condition["value"]
        if kind == "resources":
            result = public_to_dict(observation.resources) == expected
        elif kind == "action":
            result = observation.current_action.values[condition["dimension"]] == expected
        elif kind == "history":
            result = sum(observation.week_valid) >= expected
        elif kind == "flag":
            result = expected in observation_flags(observation)
        else:
            result = None
        results.append(result)
    return "not_matched" if False in results else "unknown" if None in results else "matched"


def rule_bundle(cases, rules, store, as_of_day, control_start, task_rules):
    cases = tuple(cases)
    packet = project_week_sequence(cases, as_of_day, store.public_task_sha256,
                                   control_start=control_start, count=4,
                                   group_for=store.group_for)
    packet["schema_version"] = "cemas-public-rule-input-v3"
    by_id = {case.case_id: case for case in cases}
    selected_cases = [by_id[week["case_id"]] for week in packet["weeks"]
                      if week["role"] == "autonomous"]
    packet["condition_catalog"] = condition_catalog(selected_cases, rules)
    for week in packet["weeks"]:
        if week["role"] == "autonomous":
            observation = by_id[week["case_id"]].pre_observation
            week["matched_condition_ids"] = [identity for identity, condition in packet["condition_catalog"].items()
                                               if applicability({identity: condition}, observation) == "matched"]
    packet["task_rules"] = task_rules
    return packet


def _content(content, bundle):
    exact(content, CONTENT_FIELDS, "rule content")
    references(content["condition_ids"], bundle["condition_catalog"], nonempty=True)
    text_field(content["lesson"], "lesson", 180)
    if not isinstance(content["limitations"], list) or not 1 <= len(content["limitations"]) <= 3:
        raise FeedbackResponseError("invalid_limitations", "Rules require one to three limitations")
    for value in content["limitations"]:
        text_field(value, "limitation", 120)


def _judgments(value, bundle, *, require_support=False):
    if not isinstance(value, list):
        raise FeedbackResponseError("invalid_judgments", "Judgments must be a list")
    if any(not isinstance(item, dict) for item in value):
        raise FeedbackResponseError("invalid_judgment", "Judgments must be objects")
    identities = [item.get("window_id") for item in value]
    if any(not isinstance(identity, str) for identity in identities):
        raise FeedbackResponseError("invalid_judgment", "Window IDs must be strings")
    if len(identities) != len(set(identities)):
        raise FeedbackResponseError("invalid_judgments", "Judgments must identify distinct supplied windows")
    windows = {item["window_id"]: item for item in bundle.get("weeks", [])}
    result = []
    for item in value:
        exact(item, ("window_id", "judgment"), "judgment")
        identity, judgment = item["window_id"], item["judgment"]
        if identity not in windows or judgment not in JUDGMENT_VALUES:
            raise FeedbackResponseError("invalid_judgment", "Unknown window or judgment")
        window = windows[identity]
        if window["role"] != "autonomous":
            raise FeedbackResponseError("invalid_judgment", "The reference week is comparison context only")
        if judgment != "ignore" and not window.get("support_window", False):
            raise FeedbackResponseError("invalid_judgment", "Only complete autonomous windows can update rule statistics")
        result.append({"window_id": identity, "judgment": judgment})
    if require_support and not any(item["judgment"] == "support" for item in result):
        raise FeedbackResponseError("missing_support", "A new rule requires a supporting window")
    return result


def _rows(rule_id, version, judgments, bundle):
    weeks = {item["window_id"]: item for item in bundle.get("weeks", [])}
    rows = []
    for item in judgments:
        window = weeks[item["window_id"]]
        rows.append({"rule_id": rule_id, "rule_version": version,
                     "opaque_group": window["opaque_group"], "case_id": window["case_id"],
                     "case_revision": window["revision"],
                     "window_start": window["start_day"], "window_end": window["end_day"],
                     "judgment": item["judgment"]})
    return rows


def _check_conditions(judgments, bundle, conditions, store):
    windows = {item["window_id"]: item for item in bundle["weeks"]}
    for item in judgments:
        if item["judgment"] != "ignore":
            window = windows[item["window_id"]]
            case = store.case(window["case_id"], window["revision"])
            if applicability(conditions, case.pre_observation) == "not_matched":
                raise FeedbackResponseError("conditions_not_matched", "Inapplicable windows must be ignored")


def _rule_payload(old, *, identity, version, content, conditions, store, bundle,
                  status=None, increment=None, reason=None):
    result = deepcopy(old) if old else {}
    if old is None or version != old["version"]:
        result.update(support_count=0, contradiction_count=0, confidence=.5, status="candidate")
    result.update({"id": identity, "version": version,
                   "public_task_sha256": store.public_task_sha256,
                   "content": content, "conditions": conditions,
                   "updated_at_day": bundle["as_of_day"],
                   "updated_in_episode": store.episode_group})
    if status is not None:
        result["status"] = status
    if increment is not None:
        result["increment"] = increment
    if reason is not None:
        result["reason"] = reason
    elif result["status"] != "suspended":
        result.pop("reason", None)
    return result


def prepare_patch(raw, bundle, rules, store):
    """Parse and resolve a complete aggregate-statistics patch without writing it."""
    patch = parse_json(raw)
    exact(patch, ("schema_version", "operations"), "rule patch")
    if patch["schema_version"] != "cemas-public-rule-patch-v3" or not isinstance(patch["operations"], list):
        raise FeedbackResponseError("invalid_schema", "Unknown rule patch schema")
    current = {rule["id"]: rule for rule in rules}
    next_id = max(current, default=0) + 1
    changed, updates, seen = [], [], set()
    for operation in patch["operations"]:
        if not isinstance(operation, dict):
            raise FeedbackResponseError("invalid_operation", "Expected rule operation")
        op = operation.get("op")
        fields = {"ADD": ("op", "content", "increment", "judgments"),
                  "REVISE": ("op", "target_id", "base_version", "content", "increment", "judgments"),
                  "SUSPEND": ("op", "target_id", "base_version", "reason")}
        if not isinstance(op, str) or op not in fields:
            raise FeedbackResponseError("invalid_operation", "Unknown rule operation")
        exact(operation, fields[op], op)
        old = None
        if op != "ADD":
            target = operation["target_id"]
            if type(target) is not int or target not in current or target in seen:
                raise FeedbackResponseError("invalid_target", "Target missing or modified twice")
            old = current[target]
            if type(operation["base_version"]) is not int or operation["base_version"] != old["version"]:
                raise FeedbackResponseError("stale_version", "Rule target version is stale")
            seen.add(target)
        if op == "SUSPEND":
            text_field(operation["reason"], "reason", 120)
            changed.append(_rule_payload(old, identity=old["id"], version=old["version"],
                                         content=deepcopy(old["content"]),
                                         conditions=deepcopy(old["conditions"]), store=store,
                                         bundle=bundle,
                                         status="suspended", reason=operation["reason"]))
            continue
        content = deepcopy(operation["content"])
        _content(content, bundle)
        content["condition_ids"].sort()
        text_field(operation["increment"], "increment", 120)
        content_changed = old is not None and content != old["content"]
        judgments = _judgments(operation["judgments"], bundle, require_support=old is None)
        identity = old["id"] if old else next_id
        if old is None:
            next_id += 1
        version = old["version"] + 1 if content_changed else (old["version"] if old else 1)
        new_rows = _rows(identity, version, judgments, bundle)
        if old is not None and not content_changed and not judgments:
            raise FeedbackResponseError("empty_update", "A rule update requires content or judgments")
        updates.extend(new_rows)
        conditions = {key: bundle["condition_catalog"][key] for key in content["condition_ids"]}
        _check_conditions(judgments, bundle, conditions, store)
        changed.append(_rule_payload(old, identity=identity, version=version, content=content, conditions=conditions,
                                     store=store, bundle=bundle,
                                     increment=operation["increment"],
                                     status="suspended" if old and old["status"] == "suspended" and not content_changed else None))
    return {"rules": tuple(changed), "updates": tuple(updates)}


def retrieve_rules(observation, store, config):
    query = build_case_query(observation, store.public_task_sha256)
    selected = []
    for rule in store.current_rules():
        if (rule.get("status") != "active" or rule.get("public_task_sha256") != store.public_task_sha256
                or rule.get("support_count", 0) < 2):
            continue
        match = applicability(rule.get("conditions", {}), observation)
        if match == "not_matched":
            continue
        scores = []
        for update in store.rule_updates(rule["id"], rule["version"]):
            if update["judgment"] != "support":
                continue
            case = store.case(update["case_id"], update["case_revision"])
            similarity = query_similarity(query, build_case_query(case.pre_observation, case.public_task_sha256), config)
            if similarity and similarity[0] <= config["maximum_state_rms"] and similarity[3] >= config["minimum_score"]:
                scores.append(similarity[3])
        if scores:
            selected.append({"id": f"L:rule-{rule['id']}:v{rule['version']}",
                             "rule_id": rule["id"], "version": rule["version"],
                             "content": rule["content"], "conditions": rule["conditions"],
                             "support_count": rule.get("support_count", 0),
                             "contradiction_count": rule.get("contradiction_count", 0),
                             "confidence": rule.get("confidence", 0.5),
                             "applicability": match, "similarity": max(scores),
                             "semantic_review": "not_reviewed"})
    selected.sort(key=lambda rule: (rule["applicability"] != "matched", -rule["similarity"], rule["rule_id"]))
    return selected[:6]
