"""Resolve proposals using public decision-time constraints only."""

from collections.abc import Mapping
from typing import Any

from .actions import encode_action, legal_action_mask
from .types import ActionProposal, ActionResolution, ActionVector, PublicResources


def resolve_action(proposal: ActionProposal | None, current_action: ActionVector,
                   resources: PublicResources, population: int,
                   action_spec: Mapping[str, Any], *,
                   fallback_reason: str | None = None) -> ActionResolution:
    """Keep a legal proposal, otherwise retain/project the current action.

    Controller adapters parse their own output into ActionProposal. A parse or
    service failure is represented by None and its audit reason, never repaired
    by a decoder. Clinical/tracing workload is resolved by the daily executor.
    """
    if proposal is not None and type(proposal) is not ActionProposal:
        raise TypeError("proposal must be ActionProposal or None")
    if type(current_action) is not ActionVector:
        raise TypeError("current_action must be ActionVector")
    if fallback_reason is not None and (
            type(fallback_reason) is not str or not fallback_reason.strip()):
        raise ValueError("fallback_reason must be nonempty text or None")
    mask = legal_action_mask(resources, population, action_spec)
    requested = proposal.action if proposal is not None else None
    requested_id = encode_action(requested) if requested is not None else None
    if requested is not None and mask[requested_id]:
        if fallback_reason is not None:
            raise ValueError("a legal proposal cannot also report a controller failure")
        return ActionResolution(requested, requested, requested_id, requested_id)

    reason = (fallback_reason or "controller_output_missing") if requested is None else "screening_capacity_exceeded"
    executed = current_action
    adjustment = None
    if not mask[encode_action(current_action)]:
        t, _, c, e, a = current_action.values
        highest_s = max(s for s in range(4)
                        if mask[encode_action(ActionVector((t, s, c, e, a)))])
        executed = ActionVector((t, highest_s, c, e, a))
        adjustment = "current_screening_level_invalid_after_capacity_change"
    return ActionResolution(requested, executed, requested_id, encode_action(executed),
                            adjustment_reason=adjustment, fallback_reason=reason)
