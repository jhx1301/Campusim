"""Public memory decisions layered on the single Phase 4 request/retry path."""

from collections.abc import Mapping
from dataclasses import dataclass
import json
import time
from uuid import uuid4

from .actions import encode_action
from .knowledge import KnowledgeBundle, load_knowledge_bundle, observation_flags
from .llm import (ActionResponseError, ChatMessage, LLMConfigurationError, LLMController,
                  LLMError, PublicPromptConfig, _immutable,
                  _public_rates, _reject_constant, _render_system, _unique_pairs,
                  _response_text, count_request)
from .logging import public_observation_to_dict, snapshot_sha256
from .memory import MemoryProfile, PublicEpisodeMemory, load_memory_profile, public_task_hash
from .memory_types import (RESPONSE_SCHEMA_VERSION, UNCERTAINTY_CODES, PublicMemoryContext,
                           RetrievalResult, canonical_json, public_hash,
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


def _ordinary_action(value, *, path):
    if type(value) is not list or len(value) != 5 or any(type(item) is not int for item in value):
        raise ActionResponseError("invalid_action_type", "Action must contain five ordinary integers",
            details={"path": path, "expected": "five integers in T,S,C,E,A order", "actual": type(value).__name__})
    try:
        return ActionVector(tuple(value))
    except (TypeError, ValueError):
        raise ActionResponseError("invalid_action_range", "Action levels are outside the shared ranges",
            details={"path": path, "expected": "levels within the supplied action ranges", "actual": value}) from None


def _evidence_ids(value, registry, maximum, *, path):
    if (type(value) is not list or not 1 <= len(value) <= maximum
            or any(type(item) is not str for item in value) or len(set(value)) != len(value)):
        raise ActionResponseError("invalid_evidence_ids", "Evidence IDs must be a bounded list of distinct strings",
            details={"path": path, "expected": f"1 to {maximum} distinct string IDs",
                     "actual": type(value).__name__})
    if any(item not in registry for item in value):
        raise ActionResponseError("unknown_evidence_id", "Evidence references must exist in the final sent registry",
            details={"path": path, "expected": "copy IDs exactly from evidence_registry",
                     "actual": [item for item in value if item not in registry]})
    return tuple(value)


def parse_memory_response(raw_text, *, registry, required_uncertainty_codes=(),
                          legal_action_mask=None, reason_max_chars=120):
    """Validate the five-field wire; leave main-action feasibility to the resolver."""
    if type(raw_text) is not str:
        raise ActionResponseError("invalid_content", "Final content must be text",
            details={"path": "", "expected": "JSON text", "actual": type(raw_text).__name__})
    try:
        value = json.loads(raw_text, object_pairs_hook=_unique_pairs, parse_constant=_reject_constant)
    except (json.JSONDecodeError, ValueError, RecursionError) as error:
        if isinstance(error, ActionResponseError):
            raise
        raise ActionResponseError("invalid_json", "Final content is not a single JSON value",
            details={"path": "", "expected": "one JSON object without Markdown"}) from None
    expected = {"action", "reason", "evidence_ids", "alternative_actions", "uncertainty_codes"}
    if type(value) is not dict or set(value) != expected:
        raise ActionResponseError("invalid_fields", "Response must contain exactly the five public decision fields",
            details={"path": "", "expected": sorted(expected),
                     "actual": list(value) if type(value) is dict else type(value).__name__})
    action = _ordinary_action(value["action"], path="/action")
    reason = _response_text(value["reason"], "reason", path="/reason")
    evidence = _evidence_ids(value["evidence_ids"], registry, 8, path="/evidence_ids")
    alternatives = value["alternative_actions"]
    if type(alternatives) is not list or len(alternatives) > 2:
        raise ActionResponseError("invalid_alternatives", "At most two alternative actions are allowed",
            details={"path": "/alternative_actions", "expected": "array of zero to two objects",
                     "actual": len(alternatives) if type(alternatives) is list else type(alternatives).__name__})
    parsed_alternatives, seen = [], {action.values}
    for index, item in enumerate(alternatives):
        path = f"/alternative_actions/{index}"
        if type(item) is not dict or set(item) != {"action", "tradeoff", "evidence_ids"}:
            raise ActionResponseError("invalid_alternative_fields", "Alternative action fields are invalid",
                details={"path": path, "expected": ["action", "tradeoff", "evidence_ids"],
                         "actual": list(item) if type(item) is dict else type(item).__name__})
        vector = _ordinary_action(item["action"], path=path + "/action")
        if vector.values in seen:
            raise ActionResponseError("duplicate_alternative", "Alternative actions must differ from the main action and one another",
                details={"path": path + "/action", "expected": "action distinct from main and earlier alternatives",
                         "actual": vector.values})
        seen.add(vector.values)
        tradeoff = _response_text(item["tradeoff"], "tradeoff", path=path + "/tradeoff")
        ids = _evidence_ids(item["evidence_ids"], registry, 4, path=path + "/evidence_ids")
        feasible = bool(legal_action_mask[encode_action(vector)]) if legal_action_mask is not None else None
        parsed_alternatives.append({"action": vector.values, "tradeoff": tradeoff,
                                    "evidence_ids": ids, "feasible": feasible})
    flags = value["uncertainty_codes"]
    if (type(flags) is not list or not 1 <= len(flags) <= 8 or any(type(item) is not str for item in flags)
            or len(set(flags)) != len(flags) or any(item not in UNCERTAINTY_CODES for item in flags)
            or not set(required_uncertainty_codes).issubset(flags)):
        raise ActionResponseError("invalid_uncertainty_codes", "Uncertainty codes must include all final program-required flags",
            details={"path": "/uncertainty_codes", "expected": {"allowed": UNCERTAINTY_CODES,
                     "required": required_uncertainty_codes, "count": "1 to 8 distinct values"},
                     "actual": flags if type(flags) is list and all(type(item) is str for item in flags)
                               else type(flags).__name__})
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
    return tuple(code for code in UNCERTAINTY_CODES if code in flags)


def build_memory_messages(observation, prompt_config, context, *, feedback=None, learned_rules=None):
    """Pure two-message construction plus the exact sent reference values."""
    if (type(observation) is not PublicObservation or type(prompt_config) is not PublicPromptConfig
            or type(context) is not PublicMemoryContext):
        raise TypeError("memory messages require exact public input/config/context types")
    registry = _registry(observation, context)
    required = _required_flags(observation, context)
    payload = {"observation": public_observation_to_dict(observation), "public_rates": _public_rates(observation),
               "memory": public_to_dict(context), "evidence_registry": list(registry),
               "required_uncertainty_codes": list(required)}
    for name, entries in (("feedback", feedback), ("learned_rules", learned_rules)):
        if entries is not None:
            payload[name] = entries
            registry.update((entry["id"], entry) for entry in entries)
    payload["evidence_registry"] = list(registry)
    messages = (ChatMessage("system", _render_system(prompt_config)), ChatMessage("user", canonical_json(payload)))
    return messages, registry, required


def memory_prompt_config(prompt_config, profile=None):
    """Project the P5 template while retaining the existing public-task allowlist."""
    if type(prompt_config) is not PublicPromptConfig:
        raise TypeError("memory prompt config requires PublicPromptConfig")
    profile = load_memory_profile() if profile is None else profile
    if type(profile) is not MemoryProfile:
        raise TypeError("memory profile must be a validated MemoryProfile")
    path = profile.resource_path("template_path")
    try:
        template = strict_json_loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, ValueError):
        raise LLMConfigurationError("memory_template_missing", "Cannot read the frozen P5 prompt template") from None
    if type(template) is not dict or template.get("version") != "cemas-public-memory-prompt-v2":
        raise LLMConfigurationError("memory_template_version", "Unknown P5 prompt template version")
    return PublicPromptConfig(template, prompt_config.public_spec, prompt_config.reason_max_chars)


class MemoryLLMController(LLMController):
    method = "llm_public_memory_v1"
    response_schema_version = RESPONSE_SCHEMA_VERSION

    def __init__(self, transport, prompt_config, settings, token_counter, *, memory_mode="none",
                 memory_profile=None, knowledge_bundle=None, store=None, retriever=None,
                 feedback_backend="disabled", rule_memory="off",
                 sleeper=time.sleep, clock=time.perf_counter):
        if memory_mode not in MEMORY_MODES:
            raise LLMConfigurationError("invalid_memory_mode", "Unknown public memory mode")
        self.memory_mode = memory_mode
        if feedback_backend not in ("disabled", "llm") or rule_memory not in ("off", "adaptive"):
            raise LLMConfigurationError("invalid_feedback_mode", "Unknown feedback or rule memory mode")
        from .learning_store import LearningMemoryStore
        if rule_memory != "off" and not isinstance(store, LearningMemoryStore):
            raise LLMConfigurationError("missing_learning_store", "Rules require a learning library")
        self.learning_store = store if isinstance(store, LearningMemoryStore) else None
        self.feedback_backend, self.rule_memory = feedback_backend, rule_memory
        self.control_start = prompt_config.public_spec["task"]["initial_baseline_days"]
        self.memory_profile = load_memory_profile() if memory_profile is None else memory_profile
        if type(self.memory_profile) is not MemoryProfile:
            raise TypeError("memory_profile must be MemoryProfile")
        if knowledge_bundle is None:
            knowledge_bundle = load_knowledge_bundle(self.memory_profile.resource_path("knowledge_path"))
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
        config = memory_prompt_config(prompt_config, self.memory_profile)
        if feedback_backend != "disabled" or rule_memory != "off":
            template = dict(config.template)
            template["version"] = "cemas-public-learning-prompt-v3"
            template["system"] += ("\n本次可含feedback近期经验和learned_rules检索规则。F:和L:仅引用本次实际展示的条目。"
                "经验和规则未经语义验证，只是建议；按适用状态、当前事实和固定约束判断是否采用。")
            config = PublicPromptConfig(template, config.public_spec, config.reason_max_chars)
        super().__init__(transport, config, settings, token_counter,
                         sleeper=sleeper, clock=clock)

    def reset(self):
        super().reset()
        self.memory.reset()
        self._evidence = []
        self._case_revisions = []
        self._prepared_context = None
        self._parsed_decision = None
        self._feedback_events = []
        self._pending_cases = {}
        self._latest_cases = {}
        self._notes = {}
        self._processed = set()
        self._rule_days = set()
        self._episode_group = uuid4().hex
        self._last_day = 0
        self._sent_feedback, self._sent_rules = None, None

    def observe_initial_week(self, observation, feedback):
        if observation.snapshot_day:
            return
        self.memory.stage(observation)
        # The shared observation week seeds public history but is not an algorithm case.
        self.memory.accept(feedback, publish=False)

    def observe(self, feedback):
        if type(feedback) is not PublicWeekFeedback:
            raise TypeError("MemoryLLMController requires PublicWeekFeedback")
        revisions = self.memory.accept(feedback)
        self._case_revisions.extend(revisions)
        self._last_day = feedback.week.end_day + 1
        cases = revisions
        if self.learning_store is not None and not self.learning_store.readonly:
            cases = self.learning_store.append_cases(revisions)
        from .feedback import case_key
        for case in cases:
            key = case_key(case)
            self._latest_cases[key] = case
            self._pending_cases[key] = case
        self._notes = {key: note for key, note in self._notes.items()
                       if all(self._latest_cases[k].revision == revision
                              for k, revision in note["dependencies"].items())}

    def drain_feedback_events(self):
        result, self._feedback_events = tuple(self._feedback_events), []
        return result

    def _generator(self):
        from .llm_feedback import LLMFeedback
        from .rule_memory import prepare_patch
        return LLMFeedback(self.transport, self.token_counter, self.settings, self.prompt_config,
            self._feedback_events, sleeper=self._sleeper, clock=self._clock,
            rule_parser=lambda raw, bundle, rules: prepare_patch(raw, bundle, rules, self.learning_store))

    def _maintain_rules(self, day):
        from .timing import rule_update_due
        from .rule_memory import rule_bundle
        store = self.learning_store
        if self.rule_memory == "off" or store.readonly:
            return
        if not rule_update_due(day, self.control_start) or day in self._rule_days:
            return
        key = f"rules:{day}"
        if store.operation(key) is not None:
            self._rule_days.add(day)
            return
        rules = store.current_rules()
        cases = tuple(self._latest_cases.values())
        bundle = rule_bundle(cases, rules, store, day, self.control_start,
                             public_to_dict(self.knowledge_bundle.cards))
        result = self._generator().propose(bundle, rules)
        if result is not None:
            store.write_rule_changes(result["rules"], result["updates"])
        store.record_operation(key, {"status": "unavailable" if result is None else "completed"})
        self._rule_days.add(day)

    def finish_episode(self):
        if self._last_day:
            self._maintain_rules(self._last_day)

    def _prepare_feedback(self, observation):
        from .feedback import project_feedback, case_key
        day = observation.decision_day
        if self.feedback_backend == "llm" and self._pending_cases:
            cases = sorted(self._pending_cases.values(), key=lambda c: (c.executed_week.start_day, c.revision))[-2:]
            packet = project_feedback(cases, day, self._task_hash(observation),
                control_start=self.control_start,
                group_for=(self.learning_store.group_for
                           if self.learning_store is not None and not self.learning_store.readonly
                           else lambda _: self._episode_group))
            packet["task_rules"] = public_to_dict(self.knowledge_bundle.cards)
            digest = public_hash(packet)
            if packet["weeks"] and digest not in self._processed:
                result = self._generator().generate(packet)
                self._processed.add(digest)
                if result is not None:
                    dependencies = {case_key(c): c.revision for c in cases}
                    weeks_by_id = {item["window_id"]: item for item in packet["weeks"]}
                    for item in result["items"]:
                        if item["status"] == "candidate":
                            refs = tuple(dict.fromkeys(item["finding"]["evidence_ids"] + item["decision_check"]["evidence_ids"]))
                            note_key = item["window_id"]
                            self._notes[note_key] = {"id": "F:" + public_hash({"packet": digest, "item": item}),
                                "item": item, "facts": {ref: packet["facts"][ref] for ref in refs},
                                "dependencies": dependencies, "generated_for_decision_day": day,
                                "earliest_day": min(weeks_by_id[packet["facts"][ref]["window_id"]]["start_day"]
                                                    for ref in refs),
                                "semantic_review": "not_reviewed"}
            self._pending_cases.clear()
        self._maintain_rules(day)
        self._sent_feedback = None
        if self.feedback_backend == "llm":
            eligible = [n for n in self._notes.values() if n["earliest_day"] >= day - 28]
            eligible.sort(key=lambda n: (-n["generated_for_decision_day"], n["item"]["window_id"]))
            self._sent_feedback = eligible[:2]
        self._sent_rules = None
        if self.rule_memory != "off":
            from .rule_memory import retrieve_rules
            self._sent_rules = retrieve_rules(observation, self.learning_store, self.memory_profile.retrieval)

    def drain_decision_evidence(self):
        result, self._evidence = tuple(self._evidence), []
        return result

    def _task_hash(self, observation):
        # Frozen extensions retain the training task and normalization semantics.
        return (self.learning_store.public_task_sha256 if self.learning_store is not None
                else public_task_hash(self.prompt_config, observation.execution_days))

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
        if self.learning_store is not None or self.feedback_backend != "disabled" or self.rule_memory != "off":
            from .llm_feedback import FEEDBACK_PROMPT, RULE_PROMPT
            data.update(feedback_backend=self.feedback_backend, rule_memory=self.rule_memory,
                        learning_readonly=getattr(self.learning_store, "readonly", None),
                        feedback_template_sha256=public_hash(FEEDBACK_PROMPT),
                        rule_template_sha256=public_hash(RULE_PROMPT))
        return data

    def _prepare_input(self, observation):
        if type(observation) is not PublicObservation:
            raise TypeError("MemoryLLMController requires PublicObservation")
        self._prepared_context = None
        self._parsed_decision = None
        self.memory.validate_observation(observation)
        if self.feedback_backend != "disabled" or self.rule_memory != "off":
            self.token_counter.validate(self.settings)
            self.transport.prepare()
            self._prepare_feedback(observation)
        recent = self.memory.recent(observation) if self.memory_mode in ("short", "both") else None
        knowledge = self.knowledge_bundle.select(observation)
        if self.memory_mode in ("global", "both"):
            from .retrieval import build_case_query
            query = build_case_query(observation, self._task_hash(observation), self.memory_profile)
            retrieved = self.retriever.retrieve(query)
            if type(retrieved) is not RetrievalResult:
                raise TypeError("retrievers must return exact public RetrievalResult")
        else:
            retrieved = RetrievalResult("empty", flags=("disabled",))
        context = PublicMemoryContext(self.memory_mode, recent, knowledge, retrieved)
        initial_knowledge_ids = tuple(card.id for card in knowledge)
        dropped_case_ids, trims = [], []
        messages, registry, required = build_memory_messages(observation, self.prompt_config, context,
            feedback=self._sent_feedback, learned_rules=self._sent_rules)
        count = None
        try:
            self.token_counter.validate(self.settings)
            count = count_request(messages, self.token_counter, self.settings)
        except LLMError as error:
            error.details = _immutable({**error.details, "messages_sha256": snapshot_sha256(messages),
                                        "input_tokens": count if count is not None else error.details.get("input_tokens"),
                                        "memory_profile_sha256": self.memory_profile.sha256,
                                        "knowledge_sha256": self.knowledge_bundle.sha256})
            raise
        context_hash = public_hash({"memory": public_to_dict(context), "evidence_registry": list(registry),
                                    "required_uncertainty_codes": list(required),
                                    **({"feedback": self._sent_feedback, "learned_rules": self._sent_rules}
                                       if self._sent_feedback is not None or self._sent_rules is not None else {})})
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
        final_call = self._audits[-1]
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
                    "context_hash": prepared.context_hash, "messages_sha256": final_call.messages_sha256,
                    "input_tokens": final_call.input_tokens, "selected_case_ids": cases,
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
                    "public_task_sha256": self._task_hash(observation),
                    "case_store_sha256": getattr(self.store, "store_sha256", None),
                    "retrieval_config_sha256": public_hash(self.memory_profile.retrieval),
                    "program_flags": prepared.required_uncertainty_codes,
                    "request_action": proposal.action.values if proposal is not None else None,
                    "structural_checks": {"response_schema": "passed" if parsed is not None else "not_available",
                                          "references": "passed" if parsed is not None else "not_available",
                                          "required_uncertainty": "passed" if parsed is not None else "not_available"},
                    "semantic_review_status": "not_reviewed"}
        self._evidence.append(_immutable(evidence))
