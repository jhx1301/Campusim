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
            week["pre_decision_action"] = list(observation.current_action.values)
            week["matched_condition_ids"] = [identity for identity, condition in packet["condition_catalog"].items()
                                               if applicability({identity: condition}, observation) == "matched"]
    packet["task_rules"] = task_rules
    return packet


def _content(content, bundle, path):
    exact(content, CONTENT_FIELDS, "rule content", path=path)
    references(content["condition_ids"], bundle["condition_catalog"], nonempty=True, path=path + "/condition_ids")
    text_field(content["lesson"], "lesson", path=path + "/lesson")
    if not isinstance(content["limitations"], list) or not 1 <= len(content["limitations"]) <= 3:
        raise FeedbackResponseError("invalid_limitations", "Rules require one to three limitations",
            details={"path": path + "/limitations", "expected": "list of one to three strings",
                     "actual": len(content["limitations"]) if isinstance(content["limitations"], list) else type(content["limitations"]).__name__})
    for index, value in enumerate(content["limitations"]):
        text_field(value, "limitation", path=f"{path}/limitations/{index}")


def _judgments(value, bundle, *, require_support=False, path):
    if not isinstance(value, list):
        raise FeedbackResponseError("invalid_judgments", "Judgments must be a list",
            details={"path": path, "expected": "list", "actual": type(value).__name__})
    windows = {item["window_id"]: item for item in bundle.get("weeks", [])}
    result = []
    seen = set()
    for index, item in enumerate(value):
        item_path = f"{path}/{index}"
        exact(item, ("window_id", "judgment"), "judgment", path=item_path)
        identity, judgment = item["window_id"], item["judgment"]
        if not isinstance(identity, str) or identity not in windows:
            raise FeedbackResponseError("invalid_judgment", "Unknown window",
                details={"path": item_path + "/window_id", "expected": "supplied autonomous window ID",
                         "actual": identity if isinstance(identity, str) else type(identity).__name__})
        if identity in seen:
            raise FeedbackResponseError("invalid_judgments", "Judgments must identify distinct supplied windows",
                details={"path": item_path + "/window_id", "expected": "window not already judged in this operation",
                         "actual": identity})
        seen.add(identity)
        if judgment not in JUDGMENT_VALUES:
            raise FeedbackResponseError("invalid_judgment", "Unknown judgment",
                details={"path": item_path + "/judgment", "expected": list(JUDGMENT_VALUES),
                         "actual": judgment if isinstance(judgment, str) else type(judgment).__name__})
        window = windows[identity]
        if window["role"] != "autonomous":
            raise FeedbackResponseError("invalid_judgment", "Reference weeks must be omitted from judgments, including ignore",
                details={"path": item_path + "/window_id", "expected": "autonomous window; omit reference weeks entirely",
                         "actual": identity, "window_id": identity, "role": window["role"]})
        if judgment != "ignore" and not window.get("support_window", False):
            raise FeedbackResponseError("invalid_judgment", "Only complete autonomous windows can update rule statistics",
                details={"path": item_path + "/judgment", "expected": "ignore for an incomplete autonomous window",
                         "actual": judgment, "window_id": identity})
        result.append({"window_id": identity, "judgment": judgment})
    if require_support and not any(item["judgment"] == "support" for item in result):
        raise FeedbackResponseError("missing_support", "A new rule requires a supporting window",
            details={"path": path, "expected": "at least one supporting complete autonomous window",
                     "actual": "no supporting judgment"})
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


def _check_conditions(judgments, bundle, conditions, store, path):
    windows = {item["window_id"]: item for item in bundle["weeks"]}
    for index, item in enumerate(judgments):
        if item["judgment"] != "ignore":
            window = windows[item["window_id"]]
            case = store.case(window["case_id"], window["revision"])
            missing = [identity for identity, condition in conditions.items()
                       if applicability({identity: condition}, case.pre_observation) == "not_matched"]
            if missing:
                raise FeedbackResponseError("conditions_not_matched", "Conditions apply to the pre-decision state; inapplicable windows must be ignored",
                    details={"path": f"{path}/{index}/judgment", "expected": "ignore unless every rule condition matches the pre-decision state",
                             "actual": item["judgment"], "window_id": item["window_id"],
                             "missing_condition_ids": missing,
                             "pre_decision_action": list(case.pre_observation.current_action.values)})


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
    if patch["schema_version"] != "cemas-public-rule-patch-v3":
        raise FeedbackResponseError("invalid_schema", "Unknown rule patch schema",
            details={"path": "/schema_version", "expected": "cemas-public-rule-patch-v3",
                     "actual": patch["schema_version"] if isinstance(patch["schema_version"], str) else type(patch["schema_version"]).__name__})
    if not isinstance(patch["operations"], list):
        raise FeedbackResponseError("invalid_schema", "Rule operations must be a list",
            details={"path": "/operations", "expected": "list", "actual": type(patch["operations"]).__name__})
    current = {rule["id"]: rule for rule in rules}
    next_id = max(current, default=0) + 1
    changed, updates, seen = [], [], set()
    for index, operation in enumerate(patch["operations"]):
        path = f"/operations/{index}"
        if not isinstance(operation, dict):
            raise FeedbackResponseError("invalid_operation", "Expected rule operation",
                details={"path": path, "expected": "operation object", "actual": type(operation).__name__})
        op = operation.get("op")
        fields = {"ADD": ("op", "content", "increment", "judgments"),
                  "REVISE": ("op", "target_id", "base_version", "content", "increment", "judgments"),
                  "SUSPEND": ("op", "target_id", "base_version", "reason")}
        if not isinstance(op, str) or op not in fields:
            raise FeedbackResponseError("invalid_operation", "Unknown rule operation",
                details={"path": path + "/op", "expected": list(fields),
                         "actual": op if isinstance(op, str) else type(op).__name__})
        exact(operation, fields[op], op, path=path)
        old = None
        if op != "ADD":
            target = operation["target_id"]
            if type(target) is not int or target not in current or target in seen:
                raise FeedbackResponseError("invalid_target", "Target missing or modified twice",
                    details={"path": path + "/target_id", "expected": "existing integer rule ID not already changed in this batch",
                             "actual": target if type(target) is int else type(target).__name__})
            old = current[target]
            if type(operation["base_version"]) is not int or operation["base_version"] != old["version"]:
                raise FeedbackResponseError("stale_version", "Rule target version is stale",
                    details={"path": path + "/base_version", "expected": old["version"],
                             "actual": operation["base_version"] if type(operation["base_version"]) is int else type(operation["base_version"]).__name__,
                             "rule_id": target})
            seen.add(target)
        if op == "SUSPEND":
            text_field(operation["reason"], "reason", path=path + "/reason")
            changed.append(_rule_payload(old, identity=old["id"], version=old["version"],
                                         content=deepcopy(old["content"]),
                                         conditions=deepcopy(old["conditions"]), store=store,
                                         bundle=bundle,
                                         status="suspended", reason=operation["reason"]))
            continue
        content = deepcopy(operation["content"])
        _content(content, bundle, path + "/content")
        content["condition_ids"].sort()
        text_field(operation["increment"], "increment", path=path + "/increment")
        content_changed = old is not None and content != old["content"]
        judgments = _judgments(operation["judgments"], bundle, require_support=old is None, path=path + "/judgments")
        identity = old["id"] if old else next_id
        if old is None:
            next_id += 1
        version = old["version"] + 1 if content_changed else (old["version"] if old else 1)
        new_rows = _rows(identity, version, judgments, bundle)
        if old is not None and not content_changed and not judgments:
            raise FeedbackResponseError("empty_update", "A rule update requires content or judgments",
                details={"path": path, "expected": "changed content or at least one window judgment",
                         "actual": "unchanged content and empty judgments", "rule_id": old["id"]})
        updates.extend(new_rows)
        conditions = {key: bundle["condition_catalog"][key] for key in content["condition_ids"]}
        _check_conditions(judgments, bundle, conditions, store, path + "/judgments")
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
