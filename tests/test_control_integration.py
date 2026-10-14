"""Small end-to-end proof of the Phase 2 public/private control pipeline."""

from pathlib import Path

from cemas.control.actions import legal_action_mask
from cemas.control.observation import build_observation, encode_observation
from cemas.control.protocol import load_protocol
from cemas.control.resolution import resolve_action
from cemas.control.scenarios import build_scenario
from cemas.control.types import ActionProposal, ActionVector


PROTOCOL_PATH = Path(__file__).resolve().parents[1] / "docs/control_protocol_v1.json"


def test_resolution_executor_simulator_ledger_observation_pipeline():
    protocol = load_protocol(PROTOCOL_PATH)
    bundle = build_scenario(protocol, 91231, population=100, execution_days=15,
                            initial_infections=3)
    action = ActionVector((1, 1, 1, 1, 1))
    proposal = ActionProposal(action, "end to end")
    mask = legal_action_mask(bundle.executor.resources, 100, protocol.definition["actions"])
    resolution = resolve_action(proposal, bundle.executor.current_action,
                                 bundle.executor.resources, 100,
                                 protocol.definition["actions"])
    assert mask[resolution.executed_action_id]
    bundle.executor.set_action(resolution)
    bundle.sim.run(until=7, reset_seed=False, verbose=0)

    records = bundle.public_analyzer.ledger.snapshot()
    assert len(records) == 7 and tuple(record.day for record in records) == tuple(range(7))
    assert len(bundle.private_analyzer.records) == 7
    assert records[0].executed_action == action
    assert bundle.private_analyzer.records[0].initial_infections == 3

    observation = build_observation(
        bundle.public_analyzer.ledger, bundle.registry.public_population,
        bundle.executor.current_action, bundle.executor.resources, 7,
        execution_days=15, initial_infections=3,
        action_duration_days=bundle.public_analyzer.ledger.action_duration_days(
            7, bundle.executor.current_action),
        legal_action_mask=tuple(mask),
    )
    encoded = encode_observation(observation)
    assert observation.week_valid == (False, False, False, True)
    assert encoded.dtype.name == "float32" and encoded.shape == (198,)
    assert not hasattr(observation, "sim") and not hasattr(observation, "private_metrics")


def test_private_metrics_are_separate_after_public_feedback_window():
    protocol = load_protocol(PROTOCOL_PATH)
    bundle = build_scenario(protocol, 91232, population=80, execution_days=10,
                            initial_infections=2)
    bundle.sim.run(until=10, reset_seed=False, verbose=0)
    feedback = bundle.public_analyzer.ledger.feedback(0, 6)
    private = bundle.private_analyzer.aggregate(0, 9)
    assert feedback.week.end_day == 6
    assert private.initial_infections == 2
    assert private.cumulative_infections >= private.initial_infections
    assert feedback.week.delivered_diagnoses >= 0
