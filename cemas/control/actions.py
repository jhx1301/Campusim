"""Pure v1 action encoding and decision-time screening legality."""

from collections.abc import Mapping
from fractions import Fraction
from math import isfinite
from typing import Any

from .types import ACTION_SIZES, JOINT_ACTION_COUNT, ActionVector, PublicResources, _action_id


ACTION_ENCODING = "((((t*4+s)*3+c)*3+e)*3+a)"


def encode_action(action: ActionVector) -> int:
    """Encode T/S/C/E/A with T most significant; never inspect resources."""
    if type(action) is not ActionVector:
        raise TypeError("action must be ActionVector")
    return _action_id(action.values)


def decode_action(action_id: int) -> ActionVector:
    """Decode an ordinary integer in [0, 324); invalid input raises."""
    if type(action_id) is not int:
        raise TypeError("action_id must be an ordinary integer")
    if not 0 <= action_id < JOINT_ACTION_COUNT:
        raise ValueError(f"action_id must be in [0, {JOINT_ACTION_COUNT})")
    remainder, a = divmod(action_id, ACTION_SIZES[4])
    remainder, e = divmod(remainder, ACTION_SIZES[3])
    remainder, c = divmod(remainder, ACTION_SIZES[2])
    t, s = divmod(remainder, ACTION_SIZES[1])
    return ActionVector((t, s, c, e, a))


# Immutable and indexed by action_id, independent of resources and baselines.
ACTION_TABLE = tuple(decode_action(i) for i in range(JOINT_ACTION_COUNT))


def legal_action_mask(resources: PublicResources, population: int,
                      action_spec: Mapping[str, Any]) -> tuple[bool, ...]:
    """Use the loaded protocol's actions section and public registered N.

    Only S request_ratio * N <= screening_daily_capacity determines legality.
    No resource allocation, action adjustment or fallback happens here. T/C
    capacities and actual eligible populations belong to the Phase 2 executor.
    """
    if type(resources) is not PublicResources:
        raise TypeError("resources must be PublicResources")
    if type(population) is not int or population <= 0:
        raise ValueError("population must be a positive ordinary integer")
    if not isinstance(action_spec, Mapping):
        raise TypeError("action_spec must be the protocol actions mapping")
    levels = action_spec.get("S")
    if type(levels) not in (list, tuple) or len(levels) != ACTION_SIZES[1]:
        raise ValueError("action_spec.S must contain four ordered levels")
    ratios = []
    for index, level in enumerate(levels):
        if (not isinstance(level, Mapping) or type(level.get("level")) is not int
                or level["level"] != index):
            raise ValueError("action_spec.S levels must be ordered ordinary integers 0..3")
        parameters = level.get("effective_parameters")
        if not isinstance(parameters, Mapping):
            raise ValueError("each S level must define effective_parameters")
        ratio = parameters.get("request_ratio")
        if (type(ratio) not in (int, float) or not 0 <= ratio <= 1
                or not isfinite(ratio)):
            raise ValueError("screening request_ratio must be finite in [0, 1]")
        # Decimal JSON values define exact capacity boundaries (e.g. .07 * 100).
        ratios.append(Fraction(str(ratio)))
    if ratios[0] != 0 or ratios != sorted(ratios):
        raise ValueError("S ratios must start at zero and be nondecreasing")
    legal_levels = tuple(ratio * population <= resources.screening_daily_capacity
                         for ratio in ratios)
    return tuple(legal_levels[action.values[1]] for action in ACTION_TABLE)
