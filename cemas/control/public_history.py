"""Public weekly measurements, including genuinely missing historical fields."""

from dataclasses import asdict


def week_values(week):
    values = asdict(week)
    if week.historical:
        values["executed_action"] = values["resources"] = None
        for key in ("clinical_tests", "screening_tests", "delivered_notifications",
                    "school_restriction_person_days", "work_restriction_person_days",
                    "community_restriction_person_days"):
            values["cost"][key] = None
    else:
        values.pop("historical")
        values.pop("total_tests")
    return values


def tests_in(week):
    return week.total_tests if week.historical else week.cost.clinical_tests + week.cost.screening_tests


def activity_in(week):
    if week.historical:
        return None
    cost = week.cost
    return cost.school_restriction_person_days + cost.work_restriction_person_days + cost.community_restriction_person_days
