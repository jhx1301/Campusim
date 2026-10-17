"""Independent P5 provider probes and exact, version-bound acceptance receipts."""
from datetime import datetime, timezone
import json
import os
from pathlib import Path

from .llm import LLMConfigurationError, LLMError
from .logging import resolved_snapshot, snapshot_sha256

MEMORY_ACCEPTANCE_VERSION = "cemas-memory-provider-acceptance-v1"
MEMORY_PROBE_MODES = {"day0_none": "none", "four_weeks_short": "short", "four_weeks_global": "global",
                      "four_weeks_both": "both", "no_case": "global", "long_numeric": "both"}


def memory_service_identity(controller):
    return {"memory_profile_sha256": controller.memory_profile.sha256,
            "template_sha256": controller.prompt_config.template_sha256,
            "knowledge_bundle_sha256": controller.knowledge_bundle.sha256,
            "response_schema_version": controller.response_schema_version,
            "tokenizer_identity": resolved_snapshot(controller.token_counter.identity),
            "endpoint": controller.settings.endpoint,
            "request_parameters": controller.settings.request_parameters()}


def validate_memory_acceptance(path, controller):
    """A filename or version label alone never enables a live memory episode."""
    from .llm_memory import parse_memory_response
    from .knowledge import CORE_IDS
    from .memory_types import (strict_json_loads, observation_from_dict, memory_context_from_dict,
                               public_hash, public_to_dict)
    from .llm_memory import build_memory_messages
    try:
        value = strict_json_loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError, TypeError):
        raise LLMConfigurationError("memory_not_accepted", "A matching P5 provider acceptance receipt is required") from None
    identity = memory_service_identity(controller)
    required = {"version", "status", "experimental_trajectory", "accepted_at", "cases", "sha256", *identity}
    if (type(value) is not dict or set(value) != required or value["version"] != MEMORY_ACCEPTANCE_VERSION
            or value["status"] != "accepted" or value["experimental_trajectory"] is not False
            or not isinstance(value["accepted_at"], str)
            or value["sha256"] != snapshot_sha256({key: item for key, item in value.items() if key != "sha256"})
            or any(value[key] != resolved_snapshot(expected) for key, expected in identity.items())):
        raise LLMConfigurationError("memory_acceptance_mismatch", "P5 receipt does not match the current resources, profile or service")
    cases = value["cases"]
    if (type(cases) is not list or len(cases) != len(MEMORY_PROBE_MODES)
            or any(type(case) is not dict for case in cases)
            or {case.get("name") for case in cases} != set(MEMORY_PROBE_MODES)):
        raise LLMConfigurationError("memory_acceptance_incomplete", "P5 acceptance requires all six registered input cases")
    services = set()
    original_mode = controller.memory_mode
    for case in cases:
        try:
            messages, response, count = case["messages"], case["response"], case["input_tokens"]
            if ([message["role"] for message in messages] != ["system", "user"]
                    or case["memory_mode"] != MEMORY_PROBE_MODES[case["name"]]
                    or case["messages_sha256"] != snapshot_sha256(messages)
                    or type(count) is not int or not 0 < count <= controller.settings.input_token_budget
                    or response["usage"]["prompt_tokens"] != count
                    or not response["model"] or not response["response_id"] or response["finish_reason"] == "length"):
                raise ValueError("inconsistent case")
            payload = strict_json_loads(messages[1]["content"])
            observation = observation_from_dict(payload["observation"])
            context = memory_context_from_dict(payload["memory"])
            expected_mode = MEMORY_PROBE_MODES[case["name"]]
            if context.mode != expected_mode:
                raise ValueError("probe memory mode does not match its registered name")
            if public_hash(observation) != case.get("observation_hash"):
                raise ValueError("probe observation hash does not bind the sent public observation")
            if case["name"] == "day0_none" and (observation.decision_day != 0 or any(observation.week_valid)):
                raise ValueError("day0 must have no history")
            if case["name"] != "day0_none" and not all(observation.week_valid):
                raise ValueError("memory probes require four valid weeks")
            if case["name"] == "no_case" and (context.retrieval.status != "empty" or context.retrieval.items):
                raise ValueError("no_case must exercise an explicitly empty retrieval")
            if case["name"] in ("four_weeks_global", "four_weeks_both", "long_numeric") and (context.retrieval.status != "ok" or not context.retrieval.items):
                raise ValueError("retrieval probe must include successful public cases")
            if case["name"] == "four_weeks_both" and "case_conflict" not in payload["required_uncertainty_codes"]:
                raise ValueError("both probe must exercise a conflicting case pair")
            available_cards = {card.id: card for card in controller.knowledge_bundle.select(observation)}
            sent_cards = {card.id: card for card in context.knowledge}
            if set(sent_cards) - set(available_cards) or any(
                    public_to_dict(card) != public_to_dict(available_cards[card.id])
                    for card in context.knowledge):
                raise ValueError("receipt knowledge cards are not from the current reviewed bundle")
            if not set(CORE_IDS).issubset(sent_cards):
                raise ValueError("receipt omitted a required core simulation rule")
            if context.mode in ("global", "both") and controller.memory_mode in ("global", "both"):
                from .memory_store import FrozenPublicCaseStore
                if type(controller.store) is not FrozenPublicCaseStore:
                    raise ValueError("global receipt lacks the current verified public case store")
                current_cases = {case.case_id: case for case in controller.store.cases()}
                for item in context.retrieval.items:
                    current = current_cases.get(item.case.case_id)
                    if current is None or public_to_dict(current) != public_to_dict(item.case):
                        raise ValueError("receipt case is not from the current verified public case store")
            elif context.retrieval.items or context.retrieval.flags != ("disabled",):
                raise ValueError("memory-disabled probe contains global retrieval material")
            rebuilt_messages, rebuilt_registry, rebuilt_required = build_memory_messages(
                observation, controller.prompt_config, context)
            if resolved_snapshot(messages) != resolved_snapshot(rebuilt_messages):
                raise ValueError("receipt messages do not rehydrate from current prompt, observation and memory context")
            if list(payload["evidence_registry"]) != list(rebuilt_registry):
                raise ValueError("receipt evidence registry does not bind to rehydrated public context")
            if tuple(payload["required_uncertainty_codes"]) != tuple(rebuilt_required):
                raise ValueError("receipt required uncertainty flags do not bind to rehydrated context")
            if case["messages_sha256"] != snapshot_sha256(rebuilt_messages):
                raise ValueError("receipt message hash does not match rehydrated messages")
            # Also replay the current deterministic selector and budget policy.
            # This binds retrieval scores/status and trimming decisions, rather
            # than accepting an arbitrary self-consistent context from the receipt.
            # none/short live episodes do not open a case store, so their
            # receipt validation remains structural for the global probes. A
            # global/both episode must replay the current store-backed selector.
            if expected_mode in ("none", "short") or controller.memory_mode in ("global", "both"):
                controller.memory_mode = expected_mode
                controller.reset()
                current_messages, current_count = controller._prepare_input(observation)
                if resolved_snapshot(current_messages) != resolved_snapshot(messages) or current_count != count:
                    raise ValueError("receipt context is not produced by current memory resources")
                recount = controller.token_counter.count_input(current_messages, controller.settings)
                if type(recount) is not int or recount <= 0 or recount != count:
                    raise ValueError("receipt token count does not match current official counter")
            registry = {key: rebuilt_registry[key] for key in rebuilt_registry}
            parse_memory_response(response["content"], registry=registry,
                                  required_uncertainty_codes=rebuilt_required,
                                  legal_action_mask=observation.legal_action_mask,
                                  reason_max_chars=controller.settings.reason_max_chars)
            services.add((response["model"], response.get("system_fingerprint")))
        except (KeyError, TypeError, ValueError, LLMError):
            raise LLMConfigurationError("memory_acceptance_invalid", "P5 receipt has inconsistent public probe evidence") from None
        finally:
            controller.memory_mode = original_mode
            controller.reset()
    if len(services) != 1:
        raise LLMConfigurationError("provider_changed", "P5 probes returned different service identities")
    by_name = {case["name"]: case for case in cases}
    if len(by_name["long_numeric"]["messages"][1]["content"]) <= len(by_name["four_weeks_both"]["messages"][1]["content"]):
        raise LLMConfigurationError("memory_acceptance_invalid", "Long numeric probe must stress a larger complete input")
    return value


def accept_memory_llm(transport, counter, prompt_config, probes, output_dir, *, memory_profile=None, knowledge_bundle=None):
    """Use the production retry/parser/audit path; this does not advance a world."""
    from .llm_memory import MemoryLLMController
    if set(probes) != set(MEMORY_PROBE_MODES):
        raise ValueError("all six named P5 probes are required")
    output = Path(output_dir)
    output.mkdir(parents=True, exist_ok=False)

    def write(name, value):
        with (output / name).open("x", encoding="utf-8", newline="\n") as stream:
            stream.write(json.dumps(resolved_snapshot(value), ensure_ascii=False, indent=2, allow_nan=False) + "\n")
            stream.flush()
            os.fsync(stream.fileno())

    write("manifest.json", {"purpose": "memory_provider_acceptance", "experimental_trajectory": False})
    cases, identity, last_controller = [], None, None
    try:
        for name, mode in MEMORY_PROBE_MODES.items():
            probe = probes[name]
            controller = MemoryLLMController(transport, prompt_config, transport.settings, counter,
                memory_mode=mode, memory_profile=memory_profile, knowledge_bundle=knowledge_bundle, store=probe.get("store"))
            last_controller = controller
            audits = ()
            try:
                proposal = controller.decide(probe["observation"])
            finally:
                audits = controller.drain_call_audits()
                with (output / "llm_calls.jsonl").open("a", encoding="utf-8", newline="\n") as stream:
                    for audit in audits:
                        stream.write(json.dumps(resolved_snapshot(audit), ensure_ascii=False, allow_nan=False) + "\n")
                    stream.flush()
                    os.fsync(stream.fileno())
            if proposal is None or not audits or audits[-1].response is None:
                raise LLMConfigurationError("memory_acceptance_failed", "P5 probe exhausted its normal retry budget")
            audit = audits[-1]
            current = memory_service_identity(controller)
            if identity is not None and identity != current:
                raise LLMConfigurationError("provider_changed", "P5 probe resources changed during acceptance")
            identity = current
            cases.append({"name": name, "memory_mode": mode, "observation_hash": public_hash(probe["observation"]),
                          "messages": resolved_snapshot(audit.messages), "messages_sha256": audit.messages_sha256,
                          "input_tokens": audit.input_tokens, "response": resolved_snapshot(audit.response), "attempt_count": len(audits)})
        receipt = {"version": MEMORY_ACCEPTANCE_VERSION, "status": "accepted", "experimental_trajectory": False,
                   "accepted_at": datetime.now(timezone.utc).isoformat(), **identity, "cases": cases}
        receipt["sha256"] = snapshot_sha256(receipt)
        # Validate the whole artifact before giving it an accepted filename.
        candidate = output / "candidate.json"
        write("candidate.json", receipt)
        validate_memory_acceptance(candidate, last_controller)
        write("memory_prompt_acceptance.json", receipt)
        return output / "memory_prompt_acceptance.json"
    except BaseException as error:
        write("failure.json", {"error_type": type(error).__name__,
                               "error": str(error) if isinstance(error, LLMError) else "P5 provider acceptance failed"})
        raise
