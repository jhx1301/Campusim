"""Shared physical and autonomous-control clocks."""


def observation_days(protocol):
    return protocol.definition["engine"]["initial_baseline_days"]


def scoring_start(protocol):
    return observation_days(protocol) if "snapshot_training" in protocol.definition else 0


def normalization_days(protocol, execution_days):
    settings = protocol.definition.get("snapshot_training")
    return settings.get("control_days", 112) if settings is not None else execution_days


def rule_update_due(day, control_start):
    elapsed = day - control_start
    return elapsed > 0 and elapsed % 28 == 0
