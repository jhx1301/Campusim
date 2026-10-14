"""Public proposal resolution, independent of the simulator."""

from pathlib import Path

import pytest

from cemas.control.actions import encode_action
from cemas.control.protocol import load_protocol
from cemas.control.resolution import resolve_action
from cemas.control.types import ActionProposal, ActionVector, PublicResources


@pytest.fixture
def spec():
    return load_protocol(Path(__file__).resolve().parents[1] / "docs" / "control_protocol_v1.json").definition["actions"]


def test_legal_proposal_is_preserved_even_if_previous_action_is_now_invalid(spec):
    previous = ActionVector((2, 3, 2, 2, 2))
    request = ActionVector((0, 1, 0, 0, 0))
    result = resolve_action(ActionProposal(request), previous, PublicResources(0, 240, 0), 12000, spec)
    assert result.requested_action is request and result.executed_action is request
    assert result.requested_action_id == result.executed_action_id == encode_action(request)
    assert result.adjustment_reason is None and result.fallback_reason is None


def test_resource_invalid_request_keeps_current_action_instead_of_clamping_proposal(spec):
    current = ActionVector((0, 0, 0, 0, 0))
    request = ActionVector((2, 3, 1, 0, 1))
    result = resolve_action(ActionProposal(request), current, PublicResources(240, 600, 120), 12000, spec)
    assert result.requested_action == request
    assert result.executed_action == current
    assert result.fallback_reason == "screening_capacity_exceeded"
    assert result.adjustment_reason is None


@pytest.mark.parametrize("capacity,expected_s", [(0, 0), (239, 0), (240, 1), (600, 2)])
def test_capacity_decline_projects_only_current_s(spec, capacity, expected_s):
    current = ActionVector((2, 3, 1, 0, 1))
    result = resolve_action(None, current, PublicResources(0, capacity, 0), 12000, spec,
                            fallback_reason="controller_parse_error")
    assert result.requested_action is None and result.requested_action_id is None
    assert result.executed_action.values == (2, expected_s, 1, 0, 1)
    assert result.executed_action_id == encode_action(result.executed_action)
    assert result.adjustment_reason and result.fallback_reason == "controller_parse_error"


def test_controller_failure_holds_and_runtime_capacities_do_not_change_t_c(spec):
    current = ActionVector((2, 0, 2, 1, 1))
    result = resolve_action(None, current, PublicResources(), 12000, spec)
    assert result.executed_action == current
    assert result.adjustment_reason is None and result.fallback_reason


@pytest.mark.parametrize("bad", [True, {}, [], 12])
def test_parser_boundary_rejects_raw_payloads(spec, bad):
    with pytest.raises(TypeError):
        resolve_action(bad, ActionVector((0, 0, 0, 0, 0)), PublicResources(), 12000, spec)
