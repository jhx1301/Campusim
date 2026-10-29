"""Flat public-week projections and the boundary parser for weekly notes."""

from .llm import ActionResponseError
from .memory_types import public_hash, strict_json_loads
from .public_history import week_values


class FeedbackResponseError(ActionResponseError):
    pass


def exact(value, keys, name, *, path=""):
    if not isinstance(value, dict) or set(value) != set(keys):
        raise FeedbackResponseError("invalid_fields", f"Invalid {name} fields",
            details={"path": path, "expected": list(keys),
                     "actual": list(value) if isinstance(value, dict) else type(value).__name__})


def text_field(value, name, *, path=""):
    """Read descriptive text without imposing a character limit."""
    if not isinstance(value, str) or not value.strip() or value.splitlines() != [value]:
        raise FeedbackResponseError("invalid_text", f"Invalid {name}",
            details={"path": path, "expected": "nonempty single-line string",
                     "actual": type(value).__name__ if not isinstance(value, str) else "empty or multiline string"})
    return value


def references(value, facts, *, nonempty=False, path=""):
    if not isinstance(value, list) or (nonempty and not value):
        raise FeedbackResponseError("invalid_reference", "References must identify distinct supplied facts",
            details={"path": path, "expected": "nonempty list of supplied IDs" if nonempty else "list of supplied IDs",
                     "actual": type(value).__name__ if not isinstance(value, list) else []})
    seen = set()
    for index, identity in enumerate(value):
        if not isinstance(identity, str) or identity in seen or identity not in facts:
            raise FeedbackResponseError("invalid_reference", "Copy distinct IDs verbatim from the supplied input",
                details={"path": f"{path}/{index}", "expected": "distinct ID copied verbatim from supplied input",
                         "actual": identity if isinstance(identity, str) else type(identity).__name__})
        seen.add(identity)
    return value


def parse_json(raw):
    try:
        return strict_json_loads(raw)
    except (ValueError, TypeError, RecursionError):
        raise FeedbackResponseError("invalid_json", "Expected one strict JSON object",
            details={"path": "", "expected": "one strict JSON object without duplicate keys or nonstandard constants",
                     "actual": "invalid JSON"}) from None


def case_identity(case):
    return case.case_id if hasattr(case, "case_id") else case.local_id


def case_key(case):
    return f"case:{case_identity(case)}"


def _week_identity(group, week):
    return "W:" + public_hash({"group": group, "window": [week.start_day, week.end_day]})


def _tests(values):
    if values.get("historical"):
        return values["total_tests"]
    cost = values.get("cost", {})
    clinical, screening = cost.get("clinical_tests"), cost.get("screening_tests")
    return clinical + screening if clinical is not None and screening is not None else None


def project_week_sequence(cases, as_of_day, task_hash, *, control_start=7, count=4, group_for=None):
    """Project one de-duplicated reference-plus-control public week sequence."""
    candidates, seen = [], set()
    lower = as_of_day - count * 7
    for case in cases:
        week = case.executed_week
        if week.start_day < lower or week.end_day >= as_of_day:
            continue
        group = group_for(case_identity(case)) if group_for is not None else "local"
        identity = (group, week.start_day, week.end_day)
        if identity not in seen:
            seen.add(identity)
            candidates.append((week.start_day, group, case, week, "autonomous"))
    candidates.sort(key=lambda row: (row[0], row[1]))
    controls = candidates[-count:]
    ordered = list(controls)
    if controls:
        first_start = controls[0][3].start_day
        reference = None
        for _, group, case, _, _ in controls:
            for week, valid in zip(case.pre_observation.history, case.pre_observation.week_valid):
                if valid and week.end_day == first_start - 1:
                    reference = (week.start_day, group, case, week, "reference")
                    break
            if reference is not None:
                break
        if reference is not None:
            ordered.insert(0, reference)

    weeks = []
    for _, group, case, week, role in ordered:
        weeks.append({"window_id": _week_identity(group, week), "case_id": case_identity(case),
                      "revision": case.revision, "opaque_group": group, "role": role,
                      "start_day": week.start_day, "end_day": week.end_day,
                      "values": week_values(week),
                      "support_window": role == "autonomous" and week.start_day >= control_start
                                        and week.end_day - week.start_day == 6})

    comparisons = []
    for before, after in zip(weeks, weeks[1:]):
        if before["opaque_group"] != after["opaque_group"] or before["end_day"] + 1 != after["start_day"]:
            continue
        left, right = before["values"], after["values"]
        metrics = {}
        for name in ("delivered_diagnoses", "delivered_notifications", "union_person_days",
                     "school_restriction_person_days", "work_restriction_person_days",
                     "community_restriction_person_days"):
            left_value = left.get(name, left.get("cost", {}).get(name))
            right_value = right.get(name, right.get("cost", {}).get(name))
            if left_value is not None and right_value is not None:
                metrics[name] = right_value - left_value
        left_tests, right_tests = _tests(left), _tests(right)
        if left_tests is not None and right_tests is not None:
            metrics["total_tests"] = right_tests - left_tests
        limitations = ["descriptive_not_causal"]
        if left.get("resources") is not None and right.get("resources") is not None and left["resources"] != right["resources"]:
            limitations.append("capacity_changed")
        if left.get("executed_action") is not None and right.get("executed_action") is not None and left["executed_action"] != right["executed_action"]:
            limitations.append("action_changed")
        if left_tests is not None and right_tests is not None and abs(right_tests - left_tests) / max(left_tests, 1) > .25:
            limitations.append("testing_changed")
        comparisons.append({"before_window_id": before["window_id"], "after_window_id": after["window_id"],
                            "metrics": metrics, "limitations": limitations})
    return {"schema_version": "cemas-public-week-sequence-v1", "as_of_day": as_of_day,
            "public_task_sha256": task_hash, "weeks": weeks, "comparisons": comparisons}


def _feedback_facts(packet):
    facts = {}
    for week in packet["weeks"]:
        values = week["values"]
        for name in ("delivered_diagnoses", "executed_action", "resources", "growth", "diagnosis_test_proxy"):
            if name == "growth" and not values["growth_valid"]:
                continue
            if name == "diagnosis_test_proxy" and not values["proxy_valid"]:
                continue
            if values.get(name) is not None:
                facts[f"{week['window_id']}:{name}"] = {"window_id": week["window_id"], "name": name, "value": values[name]}
        for name, value in values.get("cost", {}).items():
            if value is not None:
                facts[f"{week['window_id']}:cost.{name}"] = {"window_id": week["window_id"],
                                                               "name": f"cost.{name}", "value": value}
    return facts


def project_feedback(cases, as_of_day, task_hash, *, control_start=7, group_for=None):
    packet = project_week_sequence(cases, as_of_day, task_hash, control_start=control_start,
                                   count=1, group_for=group_for)
    packet["schema_version"] = "cemas-public-feedback-input-v3"
    packet["scope"] = "local"
    packet["facts"] = _feedback_facts(packet)
    return packet


def parse_feedback(raw, packet):
    result = parse_json(raw)
    exact(result, ("schema_version", "items"), "feedback")
    if result["schema_version"] != "cemas-public-feedback-result-v2":
        raise FeedbackResponseError("invalid_schema", "Unknown feedback schema",
            details={"path": "/schema_version", "expected": "cemas-public-feedback-result-v2",
                     "actual": result["schema_version"] if isinstance(result["schema_version"], str) else type(result["schema_version"]).__name__})
    if not isinstance(result["items"], list):
        raise FeedbackResponseError("invalid_schema", "Feedback items must be a list",
            details={"path": "/items", "expected": "list", "actual": type(result["items"]).__name__})
    expected = {week["window_id"] for week in packet["weeks"] if week["role"] == "autonomous"}
    seen = set()
    for index, item in enumerate(result["items"]):
        path = f"/items/{index}"
        if not isinstance(item, dict) or not isinstance(item.get("window_id"), str):
            raise FeedbackResponseError("invalid_window", "Expected a supplied window_id",
                details={"path": path + "/window_id", "expected": "supplied autonomous window ID string",
                         "actual": type(item.get("window_id")).__name__ if isinstance(item, dict) else type(item).__name__})
        identity = item["window_id"]
        if identity not in expected or identity in seen:
            raise FeedbackResponseError("invalid_window", "Feedback must cover each supplied window once",
                details={"path": path + "/window_id", "expected": "distinct supplied autonomous window ID",
                         "actual": identity})
        seen.add(identity)
        if item.get("status") == "abstain":
            exact(item, ("window_id", "status", "reason_code"), "abstention", path=path)
            if item["reason_code"] not in ("insufficient_evidence", "no_new_insight", "redundant_with_packet"):
                raise FeedbackResponseError("invalid_abstention", "Unknown abstention reason",
                    details={"path": path + "/reason_code",
                             "expected": ["insufficient_evidence", "no_new_insight", "redundant_with_packet"],
                             "actual": item["reason_code"] if isinstance(item["reason_code"], str) else type(item["reason_code"]).__name__})
            continue
        exact(item, ("window_id", "status", "finding", "decision_check", "applicability", "limitations"), "candidate", path=path)
        if item["status"] != "candidate":
            raise FeedbackResponseError("invalid_status", "Expected candidate or abstain",
                details={"path": path + "/status", "expected": ["candidate", "abstain"],
                         "actual": item["status"] if isinstance(item["status"], str) else type(item["status"]).__name__})
        for name in ("finding", "decision_check"):
            exact(item[name], ("text", "evidence_ids"), name, path=path + "/" + name)
            text_field(item[name]["text"], name, path=path + "/" + name + "/text")
            references(item[name]["evidence_ids"], packet["facts"], nonempty=True,
                       path=path + "/" + name + "/evidence_ids")
        text_field(item["applicability"], "applicability", path=path + "/applicability")
        if not isinstance(item["limitations"], list) or not 1 <= len(item["limitations"]) <= 3:
            raise FeedbackResponseError("invalid_limitations", "Expected one to three limitations",
                details={"path": path + "/limitations", "expected": "list of one to three strings",
                         "actual": len(item["limitations"]) if isinstance(item["limitations"], list) else type(item["limitations"]).__name__})
        for limit_index, limit in enumerate(item["limitations"]):
            text_field(limit, "limitation", path=f"{path}/limitations/{limit_index}")
    if seen != expected:
        raise FeedbackResponseError("missing_window", "Feedback omitted an input window",
            details={"path": "/items", "expected": "one item per autonomous window",
                     "actual": {"missing_window_ids": sorted(expected - seen)}})
    return result
