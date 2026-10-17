"""Public memory decisions layered on the single Phase 4 request/retry path."""

from collections.abc import Mapping
from dataclasses import dataclass, replace
import json
from pathlib import Path
import time

from .actions import encode_action
from .knowledge import CORE_IDS, KnowledgeBundle, load_knowledge_bundle, observation_flags
from .llm import (ActionResponseError, ChatMessage, LLMConfigurationError, LLMController,
                  LLMError, PromptBudgetError, PublicPromptConfig, _immutable,
                  _public_rates, _reject_constant, _render_system, _unique_pairs)
from .logging import public_observation_to_dict, snapshot_sha256
from .memory import MemoryProfile, PublicEpisodeMemory, load_memory_profile, public_task_hash
from .memory_types import (RESPONSE_SCHEMA_VERSION, UNCERTAINTY_CODES, PublicMemoryContext,
                           RecentSummary, RetrievalResult, canonical_json, public_hash,
                           public_to_dict, strict_json_loads)
from .types import ActionProposal, ActionVector, PublicObservation, PublicWeekFeedback


MEMORY_MODES = ("none", "short", "global", "both")


@dataclass(frozen=True, slots=True)
class ParsedMemoryDecision:
    proposal: ActionProposal
    evidence_ids: tuple
    alternative_actions: tuple
    uncertainty_codes: tuple

    def __post_init__(self):
        if type(self.proposal) is not ActionProposal:
            raise TypeError("parsed decisions require ActionProposal")
        object.__setattr__(self, "evidence_ids", tuple(self.evidence_ids))
        object.__setattr__(self, "alternative_actions", tuple(_immutable(item) for item in self.alternative_actions))
        object.__setattr__(self, "uncertainty_codes", tuple(self.uncertainty_codes))


@dataclass(frozen=True, slots=True)
class PreparedDecision:
    messages: tuple
    messages_sha256: str
    input_tokens: int
    observation_hash: str
    context_hash: str
    context: PublicMemoryContext
    registry: Mapping
    required_uncertainty_codes: tuple
    dropped_case_ids: tuple
    trim_events: tuple
    initial_knowledge_ids: tuple

    def __post_init__(self):
        object.__setattr__(self, "messages", tuple(self.messages))
        object.__setattr__(self, "registry", _immutable(self.registry))
        object.__setattr__(self, "trim_events", tuple(_immutable(item) for item in self.trim_events))
        for name in ("required_uncertainty_codes", "dropped_case_ids", "initial_knowledge_ids"):
            object.__setattr__(self, name, tuple(getattr(self, name)))


def _ordinary_action(value):
    if type(value) is not list or len(value) != 5 or any(type(item) is not int for item in value):
        raise ActionResponseError("invalid_action_type", "Action must contain five ordinary integers")
    try:
        return ActionVector(tuple(value))
    except (TypeError, ValueError):
        raise ActionResponseError("invalid_action_range", "Action levels are outside the shared ranges") from None


def _single_line(value, limit, name):
    if (type(value) is not str or not value.strip() or len(value) > limit
            or value.splitlines() != [value]):
        raise ActionResponseError("invalid_" + name, "Expected nonempty single-line text within its character limit")
    return value


def _evidence_ids(value, registry, maximum):
    if (type(value) is not list or not 1 <= len(value) <= maximum
            or any(type(item) is not str for item in value) or len(set(value)) != len(value)):
        raise ActionResponseError("invalid_evidence_ids", "Evidence IDs must be a bounded list of distinct strings")
    if any(item not in registry for item in value):
        raise ActionResponseError("unknown_evidence_id", "Evidence references must exist in the final sent registry")
    return tuple(value)


def parse_memory_response(raw_text, *, registry, required_uncertainty_codes=(),
                          legal_action_mask=None, reason_max_chars=120):
    """Validate the five-field wire; leave main-action feasibility to the resolver."""
    if type(raw_text) is not str:
        raise ActionResponseError("invalid_content", "Final content must be text")
    try:
        value = json.loads(raw_text, object_pairs_hook=_unique_pairs, parse_constant=_reject_constant)
    except (json.JSONDecodeError, ValueError, RecursionError) as error:
        if isinstance(error, ActionResponseError):
            raise
        raise ActionResponseError("invalid_json", "Final content is not a single JSON value") from None
    expected = {"action", "reason", "evidence_ids", "alternative_actions", "uncertainty_codes"}
    if type(value) is not dict or set(value) != expected:
        raise ActionResponseError("invalid_fields", "Response must contain exactly the five public decision fields")
    action = _ordinary_action(value["action"])
    reason = _single_line(value["reason"], reason_max_chars, "reason")
    evidence = _evidence_ids(value["evidence_ids"], registry, 8)
    alternatives = value["alternative_actions"]
    if type(alternatives) is not list or len(alternatives) > 2:
        raise ActionResponseError("invalid_alternatives", "At most two alternative actions are allowed")
    parsed_alternatives, seen = [], {action.values}
    for item in alternatives:
        if type(item) is not dict or set(item) != {"action", "tradeoff", "evidence_ids"}:
            raise ActionResponseError("invalid_alternative_fields", "Alternative action fields are invalid")
        vector = _ordinary_action(item["action"])
        if vector.values in seen:
            raise ActionResponseError("duplicate_alternative", "Alternative actions must differ from the main action and one another")
        seen.add(vector.values)
        tradeoff = _single_line(item["tradeoff"], 80, "tradeoff")
        ids = _evidence_ids(item["evidence_ids"], registry, 4)
        feasible = bool(legal_action_mask[encode_action(vector)]) if legal_action_mask is not None else None
        parsed_alternatives.append({"action": vector.values, "tradeoff": tradeoff,
                                    "evidence_ids": ids, "feasible": feasible})
    flags = value["uncertainty_codes"]
    if (type(flags) is not list or not 1 <= len(flags) <= 8 or any(type(item) is not str for item in flags)
            or len(set(flags)) != len(flags) or any(item not in UNCERTAINTY_CODES for item in flags)
            or not set(required_uncertainty_codes).issubset(flags)):
        raise ActionResponseError("invalid_uncertainty_codes", "Uncertainty codes must include all final program-required flags")
    return ParsedMemoryDecision(ActionProposal(action, reasoning=reason), evidence,
                                tuple(parsed_alternatives), tuple(flags))


def _registry(observation, context):
    observed = public_observation_to_dict(observation)
    paths = ("decision_day", "execution_days", "initial_infections", "population", "resources", "current_action",
             "action_duration_days", "legal_action_mask", "previous_day_known_isolated",
             "previous_day_known_quarantined", "previous_day_known_union")
    registry = {"O:/" + name: observed[name] for name in paths}
    for name, value in observed["resources"].items():
        registry["O:/resources/" + name] = value
    for index, valid in enumerate(observation.week_valid):
        if not valid:
            continue
        week = observed["history"][index]
        for name in ("start_day", "end_day", "delivered_diagnoses", "cost", "executed_action", "resources"):
            registry[f"O:/history/{index}/{name}"] = week[name]
        if observation.history[index].growth_valid:
            registry[f"O:/history/{index}/growth"] = week["growth"]
        if observation.history[index].proxy_valid:
            registry[f"O:/history/{index}/diagnosis_test_proxy"] = week["diagnosis_test_proxy"]
    if context.recent is not None:
        for name, value in public_to_dict(context.recent).items():
            registry["R:/" + name] = value
    for card in context.knowledge:
        registry["K:" + card.id] = public_to_dict(card)
    for item in context.retrieval.items:
        registry["C:" + str(item.case.case_id)] = public_to_dict(item.case)
    return {key: registry[key] for key in sorted(registry)}


def _required_flags(observation, context):
    flags = set(observation_flags(observation))
    if context.mode in ("global", "both") and not context.retrieval.items:
        flags.add("no_case")
    if context.retrieval.status == "out_of_support":
        flags.add("out_of_support")
    paired = [item for item in context.retrieval.items if "conflict_pair" in item.applicability_codes]
    if len(paired) == 2:
        flags.add("case_conflict")
    for item in context.retrieval.items:
        followup = item.case.followup_window
        if followup is None or followup.end_day - followup.start_day + 1 < 7:
            flags.add("truncated_followup")
    return tuple(code for code in UNCERTAINTY_CODES if code in flags)


def build_memory_messages(observation, prompt_config, context):
    """Pure two-message construction plus the exact sent reference values."""
    if (type(observation) is not PublicObservation or type(prompt_config) is not PublicPromptConfig
            or type(context) is not PublicMemoryContext):
        raise TypeError("memory messages require exact public input/config/context types")
    registry = _registry(observation, context)
    required = _required_flags(observation, context)
    payload = {"observation": public_observation_to_dict(observation), "public_rates": _public_rates(observation),
               "memory": public_to_dict(context), "evidence_registry": list(registry),
               "required_uncertainty_codes": list(required)}
    messages = (ChatMessage("system", _render_system(prompt_config)), ChatMessage("user", canonical_json(payload)))
    return messages, registry, required


def memory_prompt_config(prompt_config, profile=None):
    """Project the P5 template while retaining the existing public-task allowlist."""
    if type(prompt_config) is not PublicPromptConfig:
        raise TypeError("memory prompt config requires PublicPromptConfig")
    profile = load_memory_profile() if profile is None else profile
    if type(profile) is not MemoryProfile:
        raise TypeError("memory profile must be a validated MemoryProfile")
    root = Path(__file__).resolve().parents[2]
    path = Path(profile.data["template_path"])
    if not path.is_absolute():
        path = root / path
    try:
        template = strict_json_loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, ValueError):
        raise LLMConfigurationError("memory_template_missing", "Cannot read the frozen P5 prompt template") from None
    if type(template) is not dict or template.get("version") != "cemas-public-memory-prompt-v1":
        raise LLMConfigurationError("memory_template_version", "Unknown P5 prompt template version")
    return PublicPromptConfig(template, prompt_config.public_spec, prompt_config.reason_max_chars)


class MemoryLLMController(LLMController):
    method = "llm_public_memory_v1"
    response_schema_version = RESPONSE_SCHEMA_VERSION

    def __init__(self, transport, prompt_config, settings, token_counter, *, memory_mode="none",
                 memory_profile=None, knowledge_bundle=None, store=None, retriever=None,
                 sleeper=time.sleep, clock=time.perf_counter):
        if memory_mode not in MEMORY_MODES:
            raise LLMConfigurationError("invalid_memory_mode", "Unknown public memory mode")
        self.memory_mode = memory_mode
        self.memory_profile = load_memory_profile() if memory_profile is None else memory_profile
        if type(self.memory_profile) is not MemoryProfile:
            raise TypeError("memory_profile must be MemoryProfile")
        if knowledge_bundle is None:
            root = Path(__file__).resolve().parents[2]
            knowledge_bundle = load_knowledge_bundle(root / self.memory_profile.data["knowledge_path"])
        if type(knowledge_bundle) is not KnowledgeBundle:
            raise TypeError("knowledge_bundle must be KnowledgeBundle")
        self.knowledge_bundle = knowledge_bundle
        self.store = store
        self.retriever = retriever
        if memory_mode in ("global", "both") and retriever is None:
            if store is None:
                raise LLMConfigurationError("missing_case_store", "Global memory requires a verified public case store")
            from .retrieval import NumericRetriever
            self.retriever = NumericRetriever(store, self.memory_profile.retrieval)
        self.memory = PublicEpisodeMemory()
        super().__init__(transport, memory_prompt_config(prompt_config, self.memory_profile), settings, token_counter,
                         sleeper=sleeper, clock=clock)

    def reset(self):
        super().reset()
        self.memory.reset()
        self._evidence = []
        self._case_revisions = []
        self._prepared_context = None
        self._parsed_decision = None

    def observe(self, feedback):
        if type(feedback) is not PublicWeekFeedback:
            raise TypeError("MemoryLLMController requires PublicWeekFeedback")
        self._case_revisions.extend(self.memory.accept(feedback))

    def drain_decision_evidence(self):
        result, self._evidence = tuple(self._evidence), []
        return result

    def drain_case_revisions(self):
        result, self._case_revisions = tuple(self._case_revisions), []
        return result

    def run_metadata(self):
        data = super().run_metadata()
        data.update(memory_mode=self.memory_mode, response_schema_version=self.response_schema_version,
                    memory_profile_sha256=self.memory_profile.sha256, knowledge_sha256=self.knowledge_bundle.sha256,
                    architecture_version=self.memory_profile.data["architecture_version"],
                    case_store_sha256=getattr(self.store, "store_sha256", None),
                    retrieval_config_sha256=public_hash(self.memory_profile.retrieval))
        return data

    def _prepare_input(self, observation):
        if type(observation) is not PublicObservation:
            raise TypeError("MemoryLLMController requires PublicObservation")
        self._prepared_context = None
        self._parsed_decision = None
        recent = self.memory.recent(observation) if self.memory_mode in ("short", "both") else None
        knowledge = self.knowledge_bundle.select(observation)
        if self.memory_mode in ("global", "both"):
            from .retrieval import build_case_query
            query = build_case_query(observation, public_task_hash(self.prompt_config, observation.execution_days), self.memory_profile)
            retrieved = self.retriever.retrieve(query)
            if type(retrieved) is not RetrievalResult:
                raise TypeError("retrievers must return exact public RetrievalResult")
        else:
            retrieved = RetrievalResult("empty", flags=("disabled",))
        context = PublicMemoryContext(self.memory_mode, recent, knowledge, retrieved)
        initial_knowledge_ids = tuple(card.id for card in knowledge)
        dropped_case_ids, trims = [], []
        messages, registry, required = build_memory_messages(observation, self.prompt_config, context)
        count = None
        try:
            self.token_counter.validate(self.settings)
            while True:
                count = self.token_counter.count_input(messages, self.settings)
                if type(count) is not int or count < 0:
                    raise LLMConfigurationError("tokenizer_invalid_result", "Input token count must be a nonnegative ordinary integer")
                if count <= self.settings.input_token_budget:
                    break
                if context.retrieval.items:
                    last = context.retrieval.items[-1]
                    if "conflict_pair" in last.applicability_codes:
                        removed = tuple(item.case.case_id for item in context.retrieval.items if "conflict_pair" in item.applicability_codes)
                    else:
                        removed = (last.case.case_id,)
                    items = tuple(item for item in context.retrieval.items if item.case.case_id not in removed)
                    flags = tuple(flag for flag in context.retrieval.flags if flag != "case_conflict" or len([item for item in items if "conflict_pair" in item.applicability_codes]) == 2)
                    if not items:
                        flags = tuple(dict.fromkeys((*flags, "budget_trimmed")))
                    retrieval = replace(context.retrieval, status="ok" if items else "empty", items=items, flags=flags)
                    context = replace(context, retrieval=retrieval)
                    dropped_case_ids.extend(removed)
                    trims.append({"kind": "cases", "ids": removed, "reason": "input_budget_exceeded"})
                else:
                    external = [card for card in context.knowledge if card.id not in CORE_IDS]
                    if external:
                        # Higher numerical priority is more important; ties use ID.
                        removed = min(external, key=lambda card: (card.priority, card.id)).id
                        context = replace(context, knowledge=tuple(card for card in context.knowledge if card.id != removed))
                        trims.append({"kind": "knowledge", "ids": (removed,), "reason": "input_budget_exceeded"})
                    elif context.recent is not None:
                        context = replace(context, recent=None)
                        trims.append({"kind": "recent", "reason": "input_budget_exceeded"})
                    else:
                        raise PromptBudgetError(count, self.settings.input_token_budget, snapshot_sha256(messages))
                messages, registry, required = build_memory_messages(observation, self.prompt_config, context)
        except LLMError as error:
            error.details = _immutable({**error.details, "messages_sha256": snapshot_sha256(messages), "input_tokens": count,
                                        "memory_profile_sha256": self.memory_profile.sha256,
                                        "knowledge_sha256": self.knowledge_bundle.sha256})
            raise
        context_hash = public_hash({"memory": public_to_dict(context), "evidence_registry": list(registry),
                                    "required_uncertainty_codes": list(required)})
        # Stage only after profile/token/count validation and deterministic context construction.
        # A fatal preflight/query/budget failure must not create a pending case.
        self.memory.stage(observation)
        self._prepared_context = PreparedDecision(messages, snapshot_sha256(messages), count, public_hash(observation),
                                                  context_hash, context, registry, required, tuple(dropped_case_ids),
                                                  tuple(trims), initial_knowledge_ids)
        return messages, count

    def _parse_response(self, response, observation):
        prepared = self._prepared_context
        self._parsed_decision = parse_memory_response(response.content, registry=prepared.registry,
                                                      required_uncertainty_codes=prepared.required_uncertainty_codes,
                                                      legal_action_mask=observation.legal_action_mask,
                                                      reason_max_chars=self.settings.reason_max_chars)
        return self._parsed_decision.proposal

    def _decision_finished(self, observation, proposal, attempt_count):
        prepared = self._prepared_context
        parsed = self._parsed_decision if proposal is not None else None
        citations = tuple(parsed.evidence_ids) if parsed is not None else ()
        all_citations = list(citations)
        if parsed is not None:
            all_citations.extend(identity for alternative in parsed.alternative_actions for identity in alternative["evidence_ids"])
        all_citations = tuple(dict.fromkeys(all_citations))
        cases = tuple(item.case.case_id for item in prepared.context.retrieval.items)
        cards = tuple(card.id for card in prepared.context.knowledge)
        sent_knowledge_hash = public_hash(tuple(public_to_dict(card) for card in prepared.context.knowledge))
        evidence = {"event": "prepared", "schema_version": self.response_schema_version,
                    "status": "success" if proposal is not None else "retry_exhausted",
                    "decision_day": observation.decision_day, "observation_hash": prepared.observation_hash,
                    "context_hash": prepared.context_hash, "messages_sha256": prepared.messages_sha256,
                    "input_tokens": prepared.input_tokens, "selected_case_ids": cases,
                    "cited_case_ids": tuple(int(identity[2:]) for identity in all_citations if identity.startswith("C:")),
                    "dropped_case_ids": prepared.dropped_case_ids, "knowledge_ids": cards,
                    "knowledge_sha256": sent_knowledge_hash, "knowledge_bundle_sha256": self.knowledge_bundle.sha256,
                    "initial_knowledge_ids": prepared.initial_knowledge_ids,
                    "registry": tuple(prepared.registry),
                    "cited_evidence": {identity: prepared.registry[identity] for identity in all_citations},
                    "required_uncertainty_codes": prepared.required_uncertainty_codes,
                    "uncertainty_codes": parsed.uncertainty_codes if parsed is not None else (),
                    "evidence_ids": citations, "alternative_actions": parsed.alternative_actions if parsed is not None else (),
                    "reason": proposal.reasoning if proposal is not None else None, "attempt_count": attempt_count,
                    "trim_events": prepared.trim_events, "memory_mode": self.memory_mode,
                    "response_schema_version": self.response_schema_version,
                    "memory_profile_sha256": self.memory_profile.sha256, "review_status": "not_reviewed",
                    "retrieval_status": prepared.context.retrieval.status,
                    "retrieval_flags": prepared.context.retrieval.flags,
                    "template_sha256": self.prompt_config.template_sha256,
                    "public_spec_sha256": self.prompt_config.public_spec_sha256,
                    "public_task_sha256": public_task_hash(self.prompt_config, observation.execution_days),
                    "case_store_sha256": getattr(self.store, "store_sha256", None),
                    "retrieval_config_sha256": public_hash(self.memory_profile.retrieval),
                    "program_flags": prepared.required_uncertainty_codes,
                    "request_action": proposal.action.values if proposal is not None else None,
                    "structural_checks": {"response_schema": "passed" if parsed is not None else "not_available",
                                          "references": "passed" if parsed is not None else "not_available",
                                          "required_uncertainty": "passed" if parsed is not None else "not_available"},
                    "semantic_review_status": "not_reviewed"}
        self._evidence.append(_immutable(evidence))
