"""Offline Phase 4 contracts: public prompts, strict outputs and call control."""

from dataclasses import FrozenInstanceError, replace
import json
from pathlib import Path
from types import SimpleNamespace
import sys

import pytest

from cemas.control import (
    ActionProposal, ActionResponseError, ActionVector, ChatMessage, LLMConfigurationError,
    LLMController, LLMResponse, LLMServiceError, LLMTransport, OfficialInputTokenCounter,
    PromptBudgetError, PublicCost, PublicObservation, PublicPopulation, PublicPromptConfig,
    PublicResources, PublicWeekFeedback, PublicWeeklyRecord, TokenCountMismatchError,
    build_public_messages, legal_action_mask, load_protocol, make_llm_settings,
    make_public_prompt_config, parse_action_response,
)
from cemas.control.llm import _provider_error
from cemas.control.logging import resolved_snapshot, snapshot_sha256


ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture
def protocol():
    return load_protocol(ROOT / "docs/control_protocol_v1.json")


@pytest.fixture
def settings(protocol):
    return make_llm_settings(protocol, endpoint="https://provider.invalid/v1", api_key_env="CEMAS_TEST_API_KEY")


@pytest.fixture
def prompt_config(protocol):
    return make_public_prompt_config(protocol)


@pytest.fixture
def observation(protocol):
    population = PublicPopulation(100, (0, 100, 0, 0, 0), 50, 40, 10)
    resources = PublicResources(2, 5, 1)
    return PublicObservation(0, 112, 2, population, resources, ActionVector((0, 0, 0, 0, 0)),
                             (0, 0, 0, 0, 0), legal_action_mask(resources, 100, protocol.definition["actions"]))


class StubCounter:
    """Injected test counter; its identity explicitly prevents scientific claims."""

    identity = {"adapter": "offline_test_stub", "accepted_for_live": False}

    def __init__(self, count=100, error=None):
        self.count, self.error, self.counted = count, error, []

    def validate(self, settings):
        if self.error:
            raise self.error

    def count_input(self, messages, settings):
        self.counted.append(messages)
        return self.count

    def verify_response(self, response):
        pass


class ScriptedTransport:
    def __init__(self, outcomes):
        self.outcomes = list(outcomes)
        self.messages = []
        self.prepared = 0

    def prepare(self):
        self.prepared += 1

    def complete(self, messages):
        self.messages.append(messages)
        result = self.outcomes.pop(0)
        if isinstance(result, BaseException):
            raise result
        return result


def response(action=(0, 0, 0, 0, 0), **kwargs):
    return LLMResponse(json.dumps({"action": action, "reason": "根据公共观察决策"}),
                       model="test-returned-model", response_id="test-response", **kwargs)


def full_observation(observation):
    weeks = tuple(PublicWeeklyRecord(index * 7, index * 7 + 6, 20 + index,
                                     PublicCost(clinical_tests=7, screening_tests=14,
                                                delivered_notifications=800,
                                                school_restriction_person_days=400),
                                     resources=observation.resources,
                                     growth=.5 if index else 0, growth_valid=bool(index),
                                     diagnosis_test_proxy=(20 + index) / 21, proxy_valid=True)
                  for index in range(4))
    return replace(observation, decision_day=28, history=weeks, week_valid=(True,) * 4)


def test_public_prompt_shape_rates_and_no_clipping(observation, prompt_config):
    messages = build_public_messages(full_observation(observation), prompt_config)
    assert [message.role for message in messages] == ["system", "user"]
    payload = json.loads(messages[1].content)
    assert set(payload) == {"observation", "public_rates"}
    assert payload["observation"]["week_valid"] == [True] * 4
    assert [week["start_day"] for week in payload["observation"]["history"]] == [0, 7, 14, 21]
    rates = payload["public_rates"]["history"][0]
    assert rates["delivered_notifications_over_7_population"] == pytest.approx(800 / 700)
    assert rates["school_restriction_person_days_over_7_target"] == pytest.approx(400 / 350)
    assert "initial_infections" in messages[1].content
    for forbidden in ("beta", "world_seed", "private_metrics", "active_infections", "total_reward", "source_sha256"):
        assert forbidden not in messages[0].content + messages[1].content
    assert "0.12*N*H" in messages[0].content and "0.1*N*H" in messages[0].content
    assert "T2 = [0.22,0,0.8,0.08]" in messages[0].content
    assert "固定专家规则" in messages[0].content


def test_day0_padding_target_validity_and_memory_rejection(observation, prompt_config):
    empty_targets = replace(observation, population=PublicPopulation(100, (0, 100, 0, 0, 0), 0, 0))
    payload = json.loads(build_public_messages(empty_targets, prompt_config)[1].content)
    assert payload["observation"]["week_valid"] == [False] * 4
    assert payload["public_rates"]["school_target_valid"] is False
    assert all(not week["growth_valid"] and not week["proxy_valid"] for week in payload["public_rates"]["history"])
    assert all(week["school_restriction_person_days_over_7_target"] == 0 for week in payload["public_rates"]["history"])
    with pytest.raises(NotImplementedError, match="memory_context"):
        build_public_messages(observation, prompt_config, memory_context={})
    with pytest.raises(TypeError):
        build_public_messages(resolved_snapshot(observation), prompt_config)


def test_public_projection_hashes_and_reward_single_source(protocol, observation, tmp_path):
    config = make_public_prompt_config(protocol)
    data = resolved_snapshot(protocol.definition)
    data["engine"]["smoke_beta"] = .03
    data["engine"]["pop_infected"] = 50
    data["seeds"]["controller_rng"] = "a different private RNG configuration"
    data["private_future_events"] = [{"new_infections": 99, "reward": -100}]
    changed = replace(protocol, definition=data)
    private_config = make_public_prompt_config(changed)
    assert config == private_config
    assert build_public_messages(observation, config) == build_public_messages(observation, private_config)
    assert config.public_spec_sha256 == private_config.public_spec_sha256
    data["objective"]["lambda"] = 2
    data["objective"]["test_reference_daily_ratio"] = .2
    changed_config = make_public_prompt_config(changed)
    from cemas.control.rewards import V1RewardCalculator

    calculator = V1RewardCalculator(changed, 100, 112)
    assert calculator.configuration["lambda"] == changed_config.public_spec["objective"]["lambda"] == 2
    assert "0.2*N*H" in build_public_messages(observation, changed_config)[0].content
    assert config.template_sha256 == changed_config.template_sha256
    assert config.public_spec_sha256 != changed_config.public_spec_sha256
    template = dict(config.template, expert_rules=config.template["expert_rules"] + "\n附加公共解释")
    modified = replace(config, template=template)
    assert config.template_sha256 != modified.template_sha256
    assert snapshot_sha256(build_public_messages(observation, config)) != snapshot_sha256(build_public_messages(observation, modified))


def test_configs_and_nested_audits_are_immutable(prompt_config, settings):
    with pytest.raises(FrozenInstanceError):
        settings.model = "other"
    with pytest.raises(TypeError):
        prompt_config.public_spec["objective"]["burden_weights"]["tests"] = 1
    private = resolved_snapshot(prompt_config.public_spec)
    private["actions"]["T"][0]["effective_parameters"]["beta"] = .3
    with pytest.raises(LLMConfigurationError):
        PublicPromptConfig(prompt_config.template, private, 120)
    raw = {"prompt_tokens": 9, "nested": {"values": [1]}}
    result = response(usage=raw)
    raw["nested"]["values"].append(2)
    assert result.usage["nested"]["values"] == (1,)


def test_cemas_facade_is_lazy_and_matches_control_exports():
    import subprocess

    script = "import sys, cemas; from cemas.control import LLMController; assert cemas.LLMController is LLMController; assert not {'openai', 'transformers', 'tokenizers'} & set(sys.modules)"
    result = subprocess.run([sys.executable, "-c", script], cwd=ROOT, capture_output=True, text=True)
    assert result.returncode == 0, result.stderr


def test_transport_missing_credentials_is_a_safe_preflight(settings, monkeypatch):
    monkeypatch.delenv(settings.api_key_env, raising=False)
    transport = LLMTransport(settings)
    with pytest.raises(LLMConfigurationError) as caught:
        transport.prepare()
    assert caught.value.code == "missing_credentials" and transport._client is None


@pytest.mark.parametrize("field,value", [("max_attempts", 3.0), ("timeout_seconds", True),
                                         ("primary_top_p", 2), ("api_key_env", "sk-NOT_A_VARIABLE"),
                                         ("endpoint", "https://sk-secret@provider.invalid"),
                                         ("endpoint", "https://provider.invalid?key=secret")])
def test_settings_reject_unusable_or_credential_bearing_configuration(settings, field, value):
    with pytest.raises(LLMConfigurationError):
        replace(settings, **{field: value})


@pytest.mark.parametrize("action", [(0, 0, 0, 0, 0), (2, 3, 2, 2, 2)])
def test_parser_accepts_joint_endpoints(action):
    assert parse_action_response(json.dumps({"action": action, "reason": "a" * 120})).action.values == action


@pytest.mark.parametrize("raw", [
    "", "null", "[]", '"text"',
    '{"action":[0,0,0,0,0]}',
    '{"action":[0,0,0,0,0],"reason":"ok","risk":1}',
    '{"action":[0,0,0,0,0],"reason":"ok","reason":"second"}',
    '{"action":[0,0,0,0,0],"action":[1,1,1,1,1],"reason":"ok"}',
    '{"action":[NaN,0,0,0,0],"reason":"ok"}',
    '{"action":[Infinity,0,0,0,0],"reason":"ok"}',
    '{"action":[-Infinity,0,0,0,0],"reason":"ok"}',
    'prefix {"action":[0,0,0,0,0],"reason":"ok"}',
    '{"action":[0,0,0,0,0],"reason":"ok"} suffix',
    '```json\n{"action":[0,0,0,0,0],"reason":"ok"}\n```',
    '{"action":[true,0,0,0,0],"reason":"ok"}',
    '{"action":[0.0,0,0,0,0],"reason":"ok"}',
    '{"action":[3,0,0,0,0],"reason":"ok"}',
    '{"action":[0,-1,0,0,0],"reason":"ok"}',
    '{"action":[0,0,0,0],"reason":"ok"}',
    '{"action":[0,0,0,0,0,0],"reason":"ok"}',
    '{"action":"00000","reason":"ok"}',
    '{"action":[0,0,0,0,0],"reason":null}',
    '{"action":[0,0,0,0,0],"reason":"   "}',
    '{"action":[0,0,0,0,0],"reason":"a\\nb"}',
    '{"action":[0,0,0,0,0],"reason":"a\\n"}',
    json.dumps({"action": [0] * 5, "reason": "a\u2028b"}),
    json.dumps({"action": [0] * 5, "reason": "a" * 121}),
])
def test_parser_rejects_without_repair(raw):
    with pytest.raises(ActionResponseError):
        parse_action_response(raw)


@pytest.mark.parametrize("failures", [0, 1, 2, 3])
def test_exact_retry_counts_waits_and_identical_messages(settings, prompt_config, observation, failures):
    outcomes = [LLMServiceError("timeout", "temporary")] * failures
    if failures < 3:
        outcomes.append(response())
    transport, counter, waits = ScriptedTransport(outcomes), StubCounter(), []
    controller = LLMController(transport, prompt_config, settings, counter, sleeper=waits.append)
    proposal = controller.decide(observation)
    assert len(transport.messages) == min(failures + 1, 3)
    assert len(counter.counted) == 1
    assert waits == [2, 4][:min(failures, 2)]
    assert all(message is transport.messages[0] for message in transport.messages)
    audits = controller.drain_call_audits()
    assert len({audit.messages_sha256 for audit in audits}) == 1
    assert [audit.attempt for audit in audits] == list(range(1, len(audits) + 1))
    assert controller.drain_call_audits() == ()
    assert (proposal is None) == (failures == 3)
    assert controller.consume_failure_reason() == ("llm_retry_exhausted" if failures == 3 else None)
    assert controller.consume_failure_reason() is None


def test_observe_cannot_change_prompt_and_parse_retry_has_no_correction(settings, prompt_config, observation):
    transport = ScriptedTransport([LLMResponse("bad json"), response(), response()])
    controller = LLMController(transport, prompt_config, settings, StubCounter(), sleeper=lambda _: None)
    controller.decide(observation)
    controller.observe(PublicWeekFeedback(PublicWeeklyRecord(0, 6, 100)))
    controller.observe(PublicWeekFeedback(PublicWeeklyRecord(7, 8, 500)))  # terminal tail
    controller.decide(observation)
    assert transport.messages[0] == transport.messages[1] == transport.messages[2]
    assert len(transport.messages[0]) == 2
    assert controller.drain_call_audits()[0].error_category == "ActionResponseError"
    with pytest.raises(TypeError):
        controller.observe({"week": {}})


def test_failure_state_clears_on_next_decision_and_reset(settings, prompt_config, observation):
    transport = ScriptedTransport([LLMResponse("bad")] * 3 + [response()])
    controller = LLMController(transport, prompt_config, settings, StubCounter(), sleeper=lambda _: None)
    assert controller.decide(observation) is None
    assert controller.decide(observation) is not None
    assert controller.consume_failure_reason() is None
    controller.reset()
    assert controller.drain_call_audits() == ()


@pytest.mark.parametrize("count", [7999, 8000, 8001])
def test_input_budget_covers_complete_messages_and_is_separate_from_output(settings, prompt_config, observation, count):
    transport, counter = ScriptedTransport([response()]), StubCounter(count)
    controller = LLMController(transport, prompt_config, settings, counter)
    if count <= 8000:
        controller.decide(observation)
        assert len(transport.messages) == 1
    else:
        with pytest.raises(PromptBudgetError) as caught:
            controller.decide(observation)
        assert caught.value.details["input_tokens"] == count
        assert caught.value.details["input_token_budget"] == 8000
        assert len(caught.value.details["messages_sha256"]) == 64
        assert transport.messages == [] and controller.drain_call_audits() == ()
    assert len(counter.counted[0]) == 2
    assert settings.request_parameters()["max_tokens"] == 8192


@pytest.mark.parametrize("error", [LLMConfigurationError("auth", "invalid credentials"), RuntimeError("unknown bug")])
def test_fatal_errors_abort_without_fallback_after_prior_retry(settings, prompt_config, observation, error):
    transport = ScriptedTransport([LLMResponse("bad"), error, response()])
    waits = []
    controller = LLMController(transport, prompt_config, settings, StubCounter(), sleeper=waits.append)
    with pytest.raises(type(error)):
        controller.decide(observation)
    assert len(transport.messages) == 2 and waits == [2]
    assert controller.consume_failure_reason() is None
    assert controller.drain_call_audits()[-1].retryable is False


@pytest.mark.parametrize("actual", [99, 8001, True, "100"])
def test_usage_mismatch_stops_instead_of_retrying(settings, prompt_config, observation, actual):
    transport = ScriptedTransport([response(usage={"prompt_tokens": actual})])
    controller = LLMController(transport, prompt_config, settings, StubCounter(100))
    with pytest.raises(TokenCountMismatchError):
        controller.decide(observation)
    assert len(transport.messages) == len(controller.drain_call_audits()) == 1


def test_truncated_output_is_retried_even_if_final_json_looks_complete(settings, prompt_config, observation):
    transport = ScriptedTransport([response(finish_reason="length"), response()])
    controller = LLMController(transport, prompt_config, settings, StubCounter(), sleeper=lambda _: None)
    controller.decide(observation)
    assert controller.drain_call_audits()[0].error_code == "truncated_content"


def test_transport_sdk_parameters_and_only_final_content(settings, observation, prompt_config):
    calls, options = [], []

    def create(**kwargs):
        calls.append(kwargs)
        return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content=response().content,
                                   reasoning_content="private model reasoning must not be parsed"), finish_reason="stop")],
                               usage=SimpleNamespace(model_dump=lambda **_: {"prompt_tokens": 100}),
                               model="returned", id="id", system_fingerprint="fp")

    client = SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=create)))
    client.with_options = lambda **kwargs: (options.append(kwargs) or client)
    for candidate in (settings, replace(settings, provider="qwen", model="secondary")):
        result = LLMTransport(candidate, client=client).complete(build_public_messages(observation, prompt_config))
        assert result.content == response().content and "reasoning_content" not in resolved_snapshot(result)
        assert calls[-1]["max_tokens"] == 8192 and calls[-1]["stream"] is False
        assert "tools" not in calls[-1]
        assert options[-1] == {"max_retries": 0, "timeout": 120}
    assert calls[0]["extra_body"]["thinking"] == {"type": "enabled"}
    assert calls[0]["extra_body"]["reasoning_effort"] == "high"
    assert calls[1]["extra_body"] == {"enable_thinking": True, "thinking_budget": 4096}


@pytest.mark.parametrize("status,code,category", [
    (429, "insufficient_quota", LLMConfigurationError),
    (429, "Arrearage", LLMConfigurationError),
    (429, "invalid_api_key", LLMConfigurationError),
    (429, "rate_limit_exceeded", LLMServiceError),
    (402, None, LLMConfigurationError), (401, None, LLMConfigurationError),
    (403, None, LLMConfigurationError), (400, None, LLMConfigurationError),
    (404, None, LLMConfigurationError), (422, None, LLMConfigurationError),
    (408, None, LLMServiceError), (500, None, LLMServiceError), (503, None, LLMServiceError),
    (409, None, type(None)),
])
def test_error_classification_prefers_structured_code_and_drops_secret_text(status, code, category):
    class APIError(Exception):
        pass

    class ConnectionError(APIError):
        pass

    sdk = SimpleNamespace(APIError=APIError, APIConnectionError=ConnectionError, APITimeoutError=ConnectionError)
    error = APIError("raw server text with sk-SECRET")
    error.status_code, error.body = status, {"error": {"code": code}}
    classified = _provider_error(error, sdk)
    assert type(classified) is category
    assert "SECRET" not in str(classified)
    assert _provider_error(RuntimeError("bug"), sdk) is None


@pytest.mark.parametrize("code", ["insufficient_quota", "Throttling.RateQuota", "Throttling.AllocationQuota"])
def test_qwen_temporary_rate_quotas_are_not_confused_with_hard_quotas(code):
    import openai
    import httpx

    error = openai.RateLimitError("secret-bearing raw text", response=httpx.Response(429,
                                  request=httpx.Request("POST", "https://provider.invalid")),
                                  body={"error": {"code": code}})
    assert isinstance(_provider_error(error, openai, "qwen"), LLMServiceError)
    hard = openai.RateLimitError("raw", response=error.response, body={"error": {"code": "Arrearage"}})
    assert isinstance(_provider_error(hard, openai, "qwen"), LLMConfigurationError)
    free = openai.RateLimitError("raw", response=error.response, body={"error": {
        "code": code, "message": "Free allocated quota exceeded."}})
    assert isinstance(_provider_error(free, openai, "qwen"), LLMConfigurationError)


def candidate_counter(tmp_path, settings, monkeypatch):
    """Artificial resources exercise local loading; never official acceptance."""
    (tmp_path / "tokenizer.json").write_text("{}", encoding="utf-8")
    (tmp_path / "chat_template.jinja").write_text("test template", encoding="utf-8")
    import hashlib

    manifest = {"adapter": "hf_apply_chat_template_v1", "provider": settings.provider, "model": settings.model,
                "official_source": "https://official.invalid/unit-test-only",
                "library_versions": {name: "test" for name in ("transformers", "tokenizers", "jinja2", "markupsafe")},
                "files": {path.name: hashlib.sha256(path.read_bytes()).hexdigest() for path in tmp_path.iterdir()},
                "chat_template_file": "chat_template.jinja", "template_kwargs": {"enable_thinking": True},
                "request_parameters_sha256": snapshot_sha256(settings.request_parameters())}
    path = tmp_path / "resources.json"
    path.write_text(json.dumps(manifest), encoding="utf-8")
    import cemas.control.llm as llm

    monkeypatch.setattr(llm, "package_version", lambda _: "test")
    calls = []

    def encode(messages, **kwargs):
        calls.append((messages, kwargs))
        return [1] * 100

    tokenizer = SimpleNamespace(apply_chat_template=encode)
    loader = SimpleNamespace(from_pretrained=lambda *a, **kw: (calls.append(kw) or tokenizer))
    monkeypatch.setitem(sys.modules, "transformers", SimpleNamespace(AutoTokenizer=loader))
    return OfficialInputTokenCounter(path), manifest, path, calls


def test_official_adapter_local_only_generation_prefix_and_missing_acceptance(tmp_path, settings, observation, prompt_config, monkeypatch):
    counter, manifest, path, calls = candidate_counter(tmp_path, settings, monkeypatch)
    messages = build_public_messages(observation, prompt_config)
    assert counter.count_input(messages, settings) == 100
    assert calls[0] == {"local_files_only": True, "trust_remote_code": False}
    assert calls[1][0] == resolved_snapshot(messages)
    assert calls[1][1] == {"tokenize": True, "add_generation_prompt": True, "return_dict": False,
                          "truncation": False, "padding": False, "enable_thinking": True}
    with pytest.raises(LLMConfigurationError, match="acceptance"):
        counter.validate(settings)
    controller = LLMController(ScriptedTransport([response()]), prompt_config, settings, counter)
    with pytest.raises(LLMConfigurationError):
        controller.decide(observation)
    assert controller.transport.messages == []


def test_real_local_tokenizer_library_counts_roles_template_and_generation_prefix(tmp_path, settings, observation, prompt_config):
    """Synthetic vocabulary tests the library path, not official model acceptance."""
    import hashlib
    from importlib.metadata import version
    from tokenizers import Tokenizer, models, pre_tokenizers
    from transformers import PreTrainedTokenizerFast

    backend = Tokenizer(models.WordLevel({"<unk>": 0, "<bos>": 1, "<assistant>": 2}, unk_token="<unk>"))
    backend.pre_tokenizer = pre_tokenizers.Whitespace()
    tokenizer = PreTrainedTokenizerFast(tokenizer_object=backend, unk_token="<unk>", bos_token="<bos>")
    tokenizer.chat_template = "{{ bos_token }}{% for m in messages %}{{ m['role'] }} {{ m['content'] }} {% endfor %}{% if add_generation_prompt %}<assistant>{% endif %}"
    tokenizer.save_pretrained(tmp_path)
    manifest = {"adapter": "hf_apply_chat_template_v1", "provider": settings.provider, "model": settings.model,
                "official_source": "https://unit.invalid/synthetic-vocabulary-not-official",
                "library_versions": {name: version(name) for name in ("transformers", "tokenizers", "jinja2", "markupsafe")},
                "files": {path.name: hashlib.sha256(path.read_bytes()).hexdigest() for path in tmp_path.iterdir()},
                "chat_template_file": "chat_template.jinja", "template_kwargs": {},
                "request_parameters_sha256": snapshot_sha256(settings.request_parameters())}
    path = tmp_path / "resources.json"
    path.write_text(json.dumps(manifest), encoding="utf-8")
    messages = build_public_messages(full_observation(observation), prompt_config)
    counter = OfficialInputTokenCounter(path)
    expected = tokenizer.apply_chat_template(resolved_snapshot(messages), tokenize=True, add_generation_prompt=True, return_dict=False)
    assert counter.count_input(messages, settings) == len(expected)
    without_prefix = tokenizer.apply_chat_template(resolved_snapshot(messages), tokenize=True, add_generation_prompt=False, return_dict=False)
    assert len(expected) > len(without_prefix)
    with pytest.raises(LLMConfigurationError, match="acceptance"):
        counter.validate(settings)


@pytest.mark.parametrize("change", ["hash", "model", "template", "library", "request", "unpinned"])
def test_tokenizer_readiness_failures_are_preflight(tmp_path, settings, monkeypatch, change):
    counter, manifest, path, _ = candidate_counter(tmp_path, settings, monkeypatch)
    if change == "hash":
        (tmp_path / "tokenizer.json").write_text("changed", encoding="utf-8")
    elif change == "model":
        manifest["provider"] = "qwen"
    elif change == "template":
        manifest["chat_template_file"] = "missing.jinja"
    elif change == "library":
        manifest["library_versions"]["tokenizers"] = "other"
    elif change == "request":
        manifest["request_parameters_sha256"] = "0" * 64
    else:
        (tmp_path / "extra.json").write_text("{}", encoding="utf-8")
    path.write_text(json.dumps(manifest), encoding="utf-8")
    with pytest.raises(LLMConfigurationError):
        counter.validate(settings)


def test_missing_resource_is_deferred_to_logged_episode_preflight(tmp_path, settings, prompt_config, observation):
    counter = OfficialInputTokenCounter(tmp_path / "absent.json")
    controller = LLMController(ScriptedTransport([response()]), prompt_config, settings, counter)
    with pytest.raises(LLMConfigurationError) as caught:
        controller.decide(observation)
    assert caught.value.code == "tokenizer_missing"
    assert controller.transport.messages == [] and controller.drain_call_audits() == ()


def numeric_observation(observation):
    full = full_observation(observation)
    weeks = tuple(replace(week, cost=replace(week.cost,
                         school_restriction_person_days=123.1234567890123,
                         work_restriction_person_days=100.9876543210123,
                         community_restriction_person_days=101.2345678901234)) for week in full.history)
    return replace(full, history=weeks)


def test_provider_acceptance_receipt_enables_only_matching_resource_mode_and_service(tmp_path, settings, observation, prompt_config, monkeypatch):
    from cemas.control.runner import accept_llm_token_counter

    resources = tmp_path / "resources"
    resources.mkdir()
    counter, _, path, _ = candidate_counter(resources, settings, monkeypatch)
    transport = ScriptedTransport([response(usage={"prompt_tokens": 100})] * 3)
    transport.settings = settings
    cases = {"day0": observation, "four_weeks": full_observation(observation),
             "long_numeric": numeric_observation(observation)}
    receipt = accept_llm_token_counter(transport, counter, prompt_config, cases, tmp_path / "acceptance")
    assert len(transport.messages) == 3
    record = json.loads(receipt.read_text(encoding="utf-8"))
    assert record["experimental_trajectory"] is False and record["status"] == "accepted"
    accepted = OfficialInputTokenCounter(path, acceptance_path=receipt)
    accepted.validate(settings)
    accepted.verify_response(response())
    assert accepted.identity["acceptance_sha256"] == record["sha256"]
    with pytest.raises(LLMConfigurationError, match="changed"):
        accepted.verify_response(response(system_fingerprint="changed"))
    with pytest.raises(LLMConfigurationError):
        accepted.validate(replace(settings, endpoint="https://other.invalid/v1"))
    with pytest.raises(LLMConfigurationError):
        accepted.validate(replace(settings, thinking=False))


def test_failed_provider_acceptance_retains_call_and_never_creates_accepted_receipt(tmp_path, settings, observation, prompt_config, monkeypatch):
    from cemas.control.runner import accept_llm_token_counter

    resources = tmp_path / "resources"
    resources.mkdir()
    counter, _, _, _ = candidate_counter(resources, settings, monkeypatch)
    transport = ScriptedTransport([response(usage={"prompt_tokens": 101})])
    transport.settings = settings
    output = tmp_path / "failed-acceptance"
    with pytest.raises(TokenCountMismatchError):
        accept_llm_token_counter(transport, counter, prompt_config,
                                {"day0": observation, "four_weeks": full_observation(observation),
                                 "long_numeric": numeric_observation(observation)}, output)
    assert len((output / "llm_calls.jsonl").read_text(encoding="utf-8").splitlines()) == 1
    assert not (output / "tokenizer_acceptance.json").exists()
    assert (output / "failure.json").exists()


def _json_lines(path):
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]


def test_runner_audits_before_advancing_and_keeps_resource_illegal_proposal(protocol, settings, prompt_config, tmp_path, monkeypatch):
    from cemas.control.environment import WeeklyControlEnvironment
    from cemas.control.logging import RunLogger
    from cemas.control.runner import run_episode
    import cemas.control.runner as runner

    output = tmp_path / "episode"
    transport = ScriptedTransport([LLMResponse("bad")] * 3 + [response((2, 3, 2, 2, 2))])
    controller = LLMController(transport, prompt_config, settings, StubCounter(), sleeper=lambda _: None)
    now = [0.0]
    complete, write_calls = transport.complete, RunLogger.write_llm_calls

    def timed_complete(messages):
        now[0] += 1
        return complete(messages)

    def slow_audit(logger, *args, **kwargs):
        now[0] += 100
        return write_calls(logger, *args, **kwargs)

    monkeypatch.setattr(transport, "complete", timed_complete)
    monkeypatch.setattr(runner, "perf_counter", lambda: now[0])
    monkeypatch.setattr(RunLogger, "write_llm_calls", slow_audit)
    step = WeeklyControlEnvironment.step_proposal
    deliveries = []

    def checked_step(environment, proposal, **kwargs):
        deliveries.append(len(_json_lines(output / "llm_calls.jsonl")))
        return step(environment, proposal, **kwargs)

    monkeypatch.setattr(WeeklyControlEnvironment, "step_proposal", checked_step)
    result = run_episode(protocol, controller, output, 90001,
                         scenario_options={"population": 30, "initial_infections": 1, "execution_days": 9})
    assert result.status == "completed" and deliveries == [3, 4]
    decisions = _json_lines(output / "decisions.jsonl")
    assert [item["llm_attempt_count"] for item in decisions] == [3, 1]
    assert [item["llm_succeeded"] for item in decisions] == [False, True]
    assert [item["elapsed_ms"] for item in decisions] == [3000.0, 1000.0]
    assert decisions[0]["fallback_reason"] == "llm_retry_exhausted"
    assert decisions[1]["fallback_reason"] == "screening_capacity_exceeded"
    assert decisions[1]["action_proposal"]["action"]["values"] == [2, 3, 2, 2, 2]
    assert len(transport.messages) == 4
    manifest = json.loads((output / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["llm"]["method"] == "llm_no_explicit_memory"
    assert manifest["llm"]["tokenizer_identity"]["adapter"] == "offline_test_stub"


@pytest.mark.parametrize("kind", ["auth", "quota", "unexpected", "usage"])
def test_runner_fatal_keeps_prior_week_and_failure_call_without_credentials(protocol, settings, prompt_config, tmp_path, kind):
    from cemas.control.runner import run_episode

    errors = {"auth": LLMConfigurationError("provider_http_401", "Provider rejected credentials"),
              "quota": LLMConfigurationError("hard_quota_exhausted", "Provider hard quota exhausted"),
              "unexpected": RuntimeError("unexpected client bug with sk-DO_NOT_LOG"),
              "usage": response(usage={"prompt_tokens": 101})}
    transport = ScriptedTransport([response(), errors[kind]])
    controller = LLMController(transport, prompt_config, settings, StubCounter())
    output = tmp_path / "fatal"
    with pytest.raises((LLMConfigurationError, RuntimeError, TokenCountMismatchError)):
        run_episode(protocol, controller, output, 90002,
                    scenario_options={"population": 30, "initial_infections": 1, "execution_days": 9})
    manifest = json.loads((output / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["status"] == "failed" and manifest["elapsed_days"] == 7
    assert len(_json_lines(output / "decisions.jsonl")) == 1
    audits = _json_lines(output / "llm_calls.jsonl")
    assert len(audits) == 2 and audits[-1]["decision_day"] == 7
    assert audits[-1]["retryable"] is False
    for path in output.iterdir():
        assert "sk-DO_NOT_LOG" not in path.read_text(encoding="utf-8")


@pytest.mark.parametrize("kind", ["budget", "missing_counter", "credentials"])
def test_runner_preflight_failure_is_logged_without_fictitious_attempt(protocol, settings, prompt_config, tmp_path, kind):
    from cemas.control.runner import run_episode

    counter = StubCounter(8001) if kind == "budget" else OfficialInputTokenCounter(tmp_path / "missing.json")
    transport = ScriptedTransport([response()])
    if kind == "credentials":
        counter = StubCounter()

        def missing():
            raise LLMConfigurationError("missing_credentials", "Provider credential is absent")

        transport.prepare = missing
    controller = LLMController(transport, prompt_config, settings, counter)
    output = tmp_path / "preflight"
    with pytest.raises((PromptBudgetError, LLMConfigurationError)):
        run_episode(protocol, controller, output, 90001,
                    scenario_options={"population": 30, "initial_infections": 1, "execution_days": 7})
    assert not (output / "llm_calls.jsonl").exists()
    assert _json_lines(output / "decisions.jsonl") == []
    failure = json.loads((output / "failure.json").read_text(encoding="utf-8"))
    assert failure["details"]["error_code"]
    assert len(failure["details"]["messages_sha256"]) == 64
    assert transport.messages == []
    if kind == "budget":
        assert failure["details"]["input_tokens"] == 8001


def test_runner_capacity_decline_projects_only_s_on_llm_exhaustion(protocol, settings, prompt_config, tmp_path, monkeypatch):
    from cemas.control.environment import WeeklyControlEnvironment
    from cemas.control.runner import run_episode

    make_observation = WeeklyControlEnvironment._observation

    def lower_capacity(environment):
        if environment._elapsed_days == 7:
            environment._bundle.executor.resources = PublicResources(2, 0, 1)
        return make_observation(environment)

    monkeypatch.setattr(WeeklyControlEnvironment, "_observation", lower_capacity)
    transport = ScriptedTransport([response((2, 2, 2, 2, 2))] + [LLMResponse("invalid")] * 3)
    controller = LLMController(transport, prompt_config, settings, StubCounter(), sleeper=lambda _: None)
    output = tmp_path / "declining-capacity"
    run_episode(protocol, controller, output, 90001,
                scenario_options={"population": 100, "initial_infections": 2, "execution_days": 9})
    first, second = _json_lines(output / "decisions.jsonl")
    assert first["executed_action"]["values"] == [2, 2, 2, 2, 2]
    assert second["executed_action"]["values"] == [2, 0, 2, 2, 2]
    assert second["fallback_reason"] == "llm_retry_exhausted"
    assert second["adjustment_reason"] == "current_screening_level_invalid_after_capacity_change"


def test_call_audit_disk_failure_stops_before_environment_step(protocol, settings, prompt_config, tmp_path, monkeypatch):
    from cemas.control.logging import RunLogger
    from cemas.control.runner import run_episode

    def disk_failure(*args, **kwargs):
        raise OSError("call audit write failed")

    monkeypatch.setattr(RunLogger, "write_llm_calls", disk_failure)
    controller = LLMController(ScriptedTransport([response()]), prompt_config, settings, StubCounter())
    output = tmp_path / "audit-disk-failure"
    with pytest.raises(OSError, match="call audit write failed"):
        run_episode(protocol, controller, output, 90001,
                    scenario_options={"population": 30, "initial_infections": 1, "execution_days": 9})
    manifest = json.loads((output / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["status"] == "failed" and manifest["elapsed_days"] == 0
    assert _json_lines(output / "decisions.jsonl") == []


@pytest.mark.parametrize("secondary_failure", ["fail", "close"])
def test_runner_preserves_original_exception_when_failure_logging_or_cleanup_also_fails(protocol, settings, prompt_config, tmp_path, monkeypatch, secondary_failure):
    from cemas.control.logging import RunLogger
    from cemas.control.runner import run_episode

    original = RuntimeError("original controller failure")
    close = RunLogger.close

    def secondary(logger, *args, **kwargs):
        if secondary_failure == "close":
            close(logger)
        raise OSError("secondary audit failure")

    monkeypatch.setattr(RunLogger, secondary_failure, secondary)
    controller = LLMController(ScriptedTransport([original]), prompt_config, settings, StubCounter())
    with pytest.raises(RuntimeError, match="original controller failure") as caught:
        run_episode(protocol, controller, tmp_path / "compound-failure", 90001,
                    scenario_options={"population": 30, "initial_infections": 1, "execution_days": 9})
    assert caught.value is original
    assert any("secondary audit failure" in note for note in original.__notes__)


@pytest.mark.parametrize("proposal,reason", [(None, None), (ActionProposal(ActionVector((0,) * 5)), "stale")])
def test_runner_refuses_inconsistent_proposal_failure_pairs(protocol, tmp_path, proposal, reason):
    from cemas.control.controllers import MinimumController
    from cemas.control.runner import run_episode

    class BrokenContract(MinimumController):
        def decide(self, observation):
            return proposal

        def consume_failure_reason(self):
            return reason

    with pytest.raises(ValueError):
        run_episode(protocol, BrokenContract(), tmp_path / "bad-pair", 90001,
                    scenario_options={"population": 20, "initial_infections": 1, "execution_days": 1})
    assert _json_lines(tmp_path / "bad-pair" / "decisions.jsonl") == []


def test_llm_final_pool_and_wrong_development_purpose_are_refused(protocol, settings, prompt_config, tmp_path):
    from cemas.control.runner import run_episode

    controller = LLMController(ScriptedTransport([]), prompt_config, settings, StubCounter())
    for purpose, seed in (("prompt_development", 50001), ("scientific", 20001)):
        with pytest.raises(ValueError):
            run_episode(protocol, controller, tmp_path / f"forbidden-{seed}", seed, purpose=purpose)
        assert not (tmp_path / f"forbidden-{seed}").exists()


def test_prompt_development_uses_reserved_seed_and_still_requires_e0(protocol, settings, prompt_config, tmp_path):
    from cemas.control.runner import run_episode

    controller = LLMController(LLMTransport(settings), prompt_config, settings,
                               OfficialInputTokenCounter(tmp_path / "missing.json"))
    output = tmp_path / "requires-e0"
    with pytest.raises(ValueError, match="verified calibration artifact"):
        run_episode(protocol, controller, output, 40001, purpose="prompt_development")
    manifest = json.loads((output / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["status"] == "failed" and manifest["run_purpose"] == "prompt_development"
    assert not (output / "llm_calls.jsonl").exists()
