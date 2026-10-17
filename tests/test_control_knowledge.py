"""Frozen knowledge identity, O-only triggers and publication rejection tests."""

from dataclasses import replace
import json
from pathlib import Path

import pytest

from cemas.control.actions import legal_action_mask
from cemas.control.knowledge import (CORE_IDS, EXTERNAL_IDS, DEFAULT_KNOWLEDGE_PATH,
                                     load_knowledge_bundle, observation_flags)
from cemas.control.llm import LLMConfigurationError
from cemas.control.protocol import load_protocol
from cemas.control.types import (ActionVector, PublicCost, PublicObservation,
                                 PublicPopulation, PublicResources, PublicWeeklyRecord)


ROOT = Path(__file__).resolve().parents[1]


def observation(tests=(100, 125), *, capacity_changed=False):
    protocol = load_protocol(ROOT / "docs/control_protocol_v1.json")
    resources = PublicResources(2, 5, 1)
    weeks = tuple(PublicWeeklyRecord(index * 7, index * 7 + 6, 3 + index,
                                     PublicCost(clinical_tests=count), resources=resources)
                  for index, count in enumerate(tests))
    missing = 4 - len(weeks)
    return PublicObservation(len(weeks) * 7, 112, 2, PublicPopulation(100, (0, 100, 0, 0, 0), 50, 40),
                             replace(resources, screening_daily_capacity=6) if capacity_changed else resources,
                             ActionVector((0, 0, 0, 0, 0)), (0,) * 5,
                             legal_action_mask(resources, 100, protocol.definition["actions"]),
                             (PublicWeeklyRecord(),) * missing + weeks, (False,) * missing + (True,) * len(weeks))


def write_bundle(tmp_path, mutate):
    value = json.loads(DEFAULT_KNOWLEDGE_PATH.read_text(encoding="utf-8"))
    mutate(value)
    path = tmp_path / "knowledge.json"
    path.write_text(json.dumps(value), encoding="utf-8")
    return path


def test_nine_reviewed_cards_have_correct_identity_sources_and_frozen_values():
    bundle = load_knowledge_bundle()
    assert {card.id for card in bundle.cards} == set(CORE_IDS + EXTERNAL_IDS)
    cards = {card.id: card for card in bundle.cards}
    assert cards["PH-01"].source["publisher"] == "US CDC"
    assert cards["PH-02"].source["publisher"] == "UK Health Security Agency"
    assert cards["PH-03"].source["publisher"] == "World Health Organization"
    for card in bundle.cards:
        assert card.review_status == "reviewed" and card.limitations and card.preconditions
        if card.id in CORE_IDS:
            assert (ROOT / card.source["url"]).is_file()
    with pytest.raises(TypeError):
        cards["PH-01"].source["publisher"] = "changed"
    assert "synthetic_example" not in bundle.as_dict()
    assert len(bundle.sha256) == 64


def test_resource_move_does_not_change_content_identity(tmp_path):
    original = load_knowledge_bundle()
    copied = tmp_path / "resource.json"
    copied.write_bytes(DEFAULT_KNOWLEDGE_PATH.read_bytes())
    assert load_knowledge_bundle(copied).sha256 == original.sha256


def test_o_only_knowledge_triggers_share_summary_arithmetic():
    bundle = load_knowledge_bundle()
    day0 = observation(())
    assert {card.id for card in bundle.select(day0)} == set(CORE_IDS) | {"PH-03"}
    boundary = observation((100, 125))
    assert "testing_changed" not in observation_flags(boundary)
    assert {card.id for card in bundle.select(boundary)} == set(CORE_IDS) | {"PH-01", "PH-03"}
    changed = observation((100, 126), capacity_changed=True)
    assert set(observation_flags(changed)) == {"partial_observability", "testing_changed", "capacity_changed"}
    assert {card.id for card in bundle.select(changed)} == set(CORE_IDS + EXTERNAL_IDS)
    assert "testing_changed" in observation_flags(observation((0, 1)))
    assert "testing_changed" not in observation_flags(observation((0, 0)))


@pytest.mark.parametrize("mutate", [
    lambda value: value["cards"].pop(),
    lambda value: value["cards"].append(value["cards"][0]),
    lambda value: value.update(schema_version="future-version"),
    lambda value: value.update(world_seed=30001),
    lambda value: value.update(conflict_pairs=[["SIM-01", "SIM-02"]]),
    lambda value: value["cards"][0].update(review_status="candidate"),
    lambda value: value["cards"][0].update(review_status="excluded"),
    lambda value: value["cards"][0].update(trigger="case_conflict"),
    lambda value: value["cards"][0].update(id="PH-04"),
    lambda value: value["cards"][0].update(public_fields=["private_metrics"]),
    lambda value: value["cards"][0].update(world_seed=30001),
    lambda value: value["cards"][0]["source"].update(publisher="World Health Organization"),
    lambda value: value["cards"][0]["source"].update(private_path="secrets"),
    lambda value: value["cards"][0]["source"].update(url="https://unreviewed.invalid/report"),
    lambda value: value["cards"][0]["source"].update(issued_on="2030-01-01"),
    lambda value: value["cards"][3].update(trigger="has_history"),
    lambda value: value["cards"][3]["source"].update(url="../outside.md"),
])
def test_invalid_or_unpublished_knowledge_fails_closed(tmp_path, mutate):
    with pytest.raises((LLMConfigurationError, ValueError)):
        load_knowledge_bundle(write_bundle(tmp_path, mutate))


def test_same_topic_group_is_not_an_unresolved_rule_conflict():
    bundle = load_knowledge_bundle()
    assert sum(card.conflict_group == "real-vs-synthetic" for card in bundle.cards) == 2
    assert bundle.conflict_pairs == ()


def test_knowledge_json_rejects_duplicate_keys_and_nonfinite_values(tmp_path):
    path = tmp_path / "knowledge.json"
    original = DEFAULT_KNOWLEDGE_PATH.read_text(encoding="utf-8")
    for text in (original.replace('"cards": [', '"cards": [], "cards": ['),
                 original.replace('"priority": 2', '"priority": NaN'),
                 original.replace('"priority": 2', '"priority": 1e999')):
        path.write_text(text, encoding="utf-8")
        with pytest.raises((LLMConfigurationError, ValueError)):
            load_knowledge_bundle(path)
