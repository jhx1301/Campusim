"""Saved acceptance checks must bind the compact knowledge actually sent."""

import json

import pytest

from cemas.control.llm import LLMConfigurationError
from cemas.control.logging import snapshot_sha256
from cemas.control.memory_types import prompt_json
from tools.memory_acceptance import validate_memory_acceptance
from test_control_llm_memory import (
    config, day0, observation, memory_probes, memory_receipt, controller, _rewrite_receipt,
)


def test_receipt_rehydrates_compact_knowledge_without_exposing_provenance(config, memory_receipt):
    path, _ = memory_receipt
    record = validate_memory_acceptance(path, controller(config))
    for case in record["cases"]:
        cards = json.loads(case["messages"][1]["content"])["memory"]["knowledge"]
        assert all("source" not in card and "review_status" not in card for card in cards)
        assert all(card["statement"] and card["kind"] and card["limitations"] for card in cards)


@pytest.mark.parametrize("damage", ["changed_statement", "injected_source", "unknown_id", "duplicate_card"])
def test_receipt_rejects_rehashed_compact_knowledge_tampering(config, memory_receipt, damage):
    path, _ = memory_receipt

    def mutate(record):
        case = record["cases"][0]
        payload = json.loads(case["messages"][1]["content"])
        cards = payload["memory"]["knowledge"]
        if damage == "changed_statement":
            cards[0]["statement"] = "A statement absent from the reviewed bundle"
        elif damage == "injected_source":
            cards[0]["source"] = {"publisher": "Unsent provenance"}
        elif damage == "unknown_id":
            cards[0]["id"] = "NOT-PROVIDED"
        else:
            cards.append(cards[0])
        case["messages"][1]["content"] = prompt_json(payload)
        case["messages_sha256"] = snapshot_sha256(case["messages"])

    _rewrite_receipt(path, mutate)
    with pytest.raises(LLMConfigurationError) as caught:
        validate_memory_acceptance(path, controller(config))
    assert caught.value.code == "memory_acceptance_invalid"
