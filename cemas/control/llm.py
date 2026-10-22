"""Public-only, stateless LLM decisions; SDK and tokenizer imports stay lazy.

Runner factories own protocol projection. This module never receives a protocol,
simulator, private metrics, run manifest, or a world seed.
"""

from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import datetime, timezone
import hashlib
from importlib.metadata import PackageNotFoundError, version as package_version
import json
from math import isfinite
import os
from pathlib import Path
import re
from string import Template
import time
from types import MappingProxyType
from urllib.parse import urlsplit

from .controllers import Controller
from .logging import public_observation_to_dict, resolved_snapshot, snapshot_sha256
from .types import AGE_BANDS, ActionProposal, ActionVector, PublicObservation, PublicWeekFeedback


def _canonical(value):
    return json.dumps(resolved_snapshot(value), ensure_ascii=False, sort_keys=True,
                      separators=(",", ":"), allow_nan=False)


def _immutable(value):
    if isinstance(value, Mapping):
        return MappingProxyType({key: _immutable(item) for key, item in value.items()})
    if isinstance(value, (list, tuple)):
        return tuple(_immutable(item) for item in value)
    if value is None or type(value) in (str, bool, int, float):
        resolved_snapshot(value)
        return value
    raise TypeError("LLM records require JSON-compatible values")


class LLMError(RuntimeError):
    """Safe stable errors; never include a raw SDK exception or credentials."""

    retryable = False

    def __init__(self, code, description, *, details=None):
        self.code = code
        self.details = _immutable(details or {})
        super().__init__(description)


class LLMConfigurationError(LLMError):
    pass


class LLMServiceError(LLMError):
    retryable = True


class ActionResponseError(LLMError):
    retryable = True


class PromptBudgetError(LLMError):
    def __init__(self, count, budget, messages_sha256):
        super().__init__("input_budget_exceeded", "Complete input exceeds the token budget",
                         details={"input_tokens": count, "input_token_budget": budget,
                                  "messages_sha256": messages_sha256})


class TokenCountMismatchError(LLMError):
    pass


def _exact_keys(value, keys, name):
    if not isinstance(value, Mapping) or set(value) != set(keys):
        raise LLMConfigurationError("invalid_public_config", f"Invalid {name} fields")


# Explicit, nested allowlists prevent future private protocol fields entering a
# prompt just because a new key was added to an otherwise public section.
PUBLIC_SPEC_FIELDS = MappingProxyType({
    "actions": ("order", "sizes", "joint_count", "encoding", "zero_level_semantics",
                "hold_intervals", "transition_limit", "illegal_action_fallback", "T", "S", "C", "E", "A"),
    "resources": ("clinical_tests_per_person_per_day", "tracing_index_cases_per_person_per_day",
                  "carry_over", "clinical_priority", "quar_testing_policy", "duplicate_test_policy",
                  "recent_screening_exclusion_days", "screening_selector", "screening_shortage",
                  "screening_unused_stratum_quota", "screening_queue", "tracing_index_selection",
                  "tracing_presumptive", "tracing_contacts", "notification_deduplication",
                  "notification_deceased_at_delivery", "notification_pending_after_action_change",
                  "tests", "recent_test_exclusion_scope", "quarantine_merge_rule"),
    "activity": ("daily_budget_school_or_work", "daily_budget_community", "dual_school_work_each",
                 "neither_school_nor_work_community", "calendar", "weights_fixed_at_reset",
                 "school_work_community_report_separately", "overlap_with_quarantine", "monetary_cost"),
    "objective": ("formula_version", "status", "lambda", "burden_weights",
                  "test_reference_daily_ratio", "notification_reference_daily_ratio", "formula",
                  "switch_penalty", "reward_clip", "gamma", "initial_infections_in_reward"),
    "observation": ("cutoff", "history_order", "history_week_valid", "weekly_fields", "context_fields",
                    "growth", "growth_requires_two_valid_weeks", "proxy", "proxy_zero_denominator",
                    "rates", "clip", "age_bands_shared"),
    "task": ("decision_interval_days", "initial_baseline_days", "history_weeks", "quarantine_days"),
})


@dataclass(frozen=True, slots=True)
class PublicPromptConfig:
    template: Mapping
    public_spec: Mapping
    reason_max_chars: int

    def __post_init__(self):
        _exact_keys(self.template, ("version", "system", "expert_rules"), "template")
        if any(type(self.template[key]) is not str or not self.template[key].strip()
               for key in self.template):
            raise LLMConfigurationError("invalid_template", "Template values must be nonempty text")
        _exact_keys(self.public_spec, PUBLIC_SPEC_FIELDS, "public_spec")
        for section, keys in PUBLIC_SPEC_FIELDS.items():
            _exact_keys(self.public_spec[section], keys, section)
        age_bands = self.public_spec["observation"]["age_bands_shared"]
        if (not isinstance(age_bands, (list, tuple)) or len(age_bands) != len(AGE_BANDS)
                or any(not isinstance(band, (list, tuple)) or len(band) != 2
                       or any(type(boundary) is not int for boundary in band) for band in age_bands)
                or tuple(tuple(band) for band in age_bands) != AGE_BANDS):
            raise LLMConfigurationError("invalid_age_bands", "observation.age_bands_shared must match the public age bands")
        actions = self.public_spec["actions"]
        parameter_keys = {"T": ("symptomatic_daily_probability", "ordinary_asymptomatic_daily_probability",
                                "symptomatic_quarantine_entry_probability", "asymptomatic_quarantine_entry_probability"),
                          "S": ("request_ratio",), "C": ("coverage_probability", "notification_delay_days"),
                          "E": ("transmission_multiplier", "restriction_time_fraction"),
                          "A": ("transmission_multiplier", "restriction_time_fraction")}
        for name, keys in parameter_keys.items():
            for level in actions[name]:
                _exact_keys(level, ("level", "effective_parameters"), f"actions.{name}")
                _exact_keys(level["effective_parameters"], keys, f"actions.{name}.parameters")
                if name == "C":
                    for group in level["effective_parameters"].values():
                        _exact_keys(group, ("home", "school", "work", "community"), "contact scopes")
        _exact_keys(self.public_spec["resources"]["tests"],
                    ("sensitivity", "loss_prob", "report_delay_days", "swab_delay", "ili_prev"), "tests")
        _exact_keys(self.public_spec["objective"]["burden_weights"],
                    ("tests", "notifications", "union", "activity"), "weights")
        if type(self.reason_max_chars) is not int or self.reason_max_chars <= 0:
            raise LLMConfigurationError("invalid_reason_limit", "reason_max_chars must be positive")
        object.__setattr__(self, "template", _immutable(self.template))
        object.__setattr__(self, "public_spec", _immutable(self.public_spec))

    @property
    def template_sha256(self):
        return snapshot_sha256(self.template)

    @property
    def public_spec_sha256(self):
        return snapshot_sha256({**self.public_spec, "reason_max_chars": self.reason_max_chars})

    @property
    def version(self):
        return self.template["version"]


@dataclass(frozen=True, slots=True)
class ChatMessage:
    role: str
    content: str

    def __post_init__(self):
        if self.role not in ("system", "user") or type(self.content) is not str or not self.content:
            raise ValueError("public messages require system/user roles and nonempty content")


def _render_system(config):
    spec = config.public_spec
    actions, resources = spec["actions"], spec["resources"]
    objective, activity, task = spec["objective"], spec["activity"], spec["task"]
    replacements = {**task, "reason_max_chars": config.reason_max_chars,
                    "expert_rules": config.template["expert_rules"],
                    "age_bands": "、".join(f"{lower}–{upper}" for lower, upper
                                           in spec["observation"]["age_bands_shared"]),
                    "ranges": ",".join(f"[0..{size-1}]" for size in actions["sizes"]),
                    "joint_count": actions["joint_count"],
                    "clinical_ratio": resources["clinical_tests_per_person_per_day"],
                    "tracing_ratio": resources["tracing_index_cases_per_person_per_day"],
                    "recent_exclusion": resources["recent_screening_exclusion_days"],
                    "sensitivity": resources["tests"]["sensitivity"],
                    "loss_prob": resources["tests"]["loss_prob"],
                    "report_delay": resources["tests"]["report_delay_days"],
                    "test_reference": objective["test_reference_daily_ratio"],
                    "notification_reference": objective["notification_reference_daily_ratio"],
                    "lambda": objective["lambda"], "formula_version": objective["formula_version"],
                    "objective_status": objective["status"],
                    "weights": _canonical(objective["burden_weights"]),
                    "single_budget": activity["daily_budget_school_or_work"],
                    "community_budget": activity["daily_budget_community"],
                    "dual_budget": activity["dual_school_work_each"],
                    "neither_budget": activity["neither_school_nor_work_community"],
                    }
    for name in actions["order"]:
        lines = []
        for entry in actions[name]:
            params = entry["effective_parameters"]
            if name == "T":
                values = [params[key] for key in ("symptomatic_daily_probability", "ordinary_asymptomatic_daily_probability",
                                                  "symptomatic_quarantine_entry_probability", "asymptomatic_quarantine_entry_probability")]
                text = _canonical(values)
            elif name == "S":
                ratio = params["request_ratio"]
                text = f"ceil({ratio}N)" if ratio else "0"
            elif name == "C":
                scopes = ("home", "school", "work", "community")
                text = ("覆盖" + _canonical([params["coverage_probability"][key] for key in scopes])
                        + "，延迟" + _canonical([params["notification_delay_days"][key] for key in scopes]) + "天")
            else:
                text = (f"传播乘数{params['transmission_multiplier']}；"
                        f"活动限制比例{params['restriction_time_fraction']}")
            lines.append(f"{name}{entry['level']} = {text}")
        replacements[f"{name}_levels"] = "\n".join(lines)
    return Template(config.template["system"]).substitute(replacements)


def _public_rates(observation):
    population = observation.population
    n, h = population.population, observation.execution_days

    def capacities(resources):
        return {name + "_over_population": getattr(resources, name) / n
                for name in ("clinical_daily_capacity", "screening_daily_capacity", "tracing_daily_index_capacity")}

    history = []
    for week, valid in zip(observation.history, observation.week_valid):
        cost = week.cost
        record = {"week_valid": valid, "delivered_diagnoses_over_population": week.delivered_diagnoses / n,
                  "growth": week.growth, "growth_valid": valid and week.growth_valid,
                  "diagnosis_test_proxy": week.diagnosis_test_proxy, "proxy_valid": valid and week.proxy_valid,
                  **capacities(week.resources)}
        for name in ("clinical_tests", "screening_tests", "delivered_notifications", "isolation_person_days",
                     "quarantine_person_days", "union_person_days"):
            record[name + "_over_7_population"] = getattr(cost, name) / (7 * n)
        for scope, target in (("school", population.school_population), ("work", population.work_population), ("community", n)):
            record[scope + "_target_valid"] = valid and target > 0
            record[scope + "_restriction_person_days_over_7_target"] = (
                getattr(cost, scope + "_restriction_person_days") / (7 * target) if valid and target else 0)
        history.append(record)
    return {"decision_day_over_horizon": observation.decision_day / h,
            "initial_infections_over_population": observation.initial_infections / n,
            "age_band_counts_over_population": tuple(value / n for value in population.age_band_counts),
            "school_population_over_population": population.school_population / n,
            "work_population_over_population": population.work_population / n,
            "school_work_population_over_population": population.school_work_population / n,
            "school_target_valid": population.school_population > 0, "work_target_valid": population.work_population > 0,
            "community_target_valid": True, "action_duration_days_over_horizon": tuple(value / h for value in observation.action_duration_days),
            **capacities(observation.resources),
            **{name + "_over_population": getattr(observation, name) / n for name in (
                "previous_day_known_isolated", "previous_day_known_quarantined", "previous_day_known_union")},
            "history": history}


def build_public_messages(observation: PublicObservation, prompt_config: PublicPromptConfig, *, memory_context=None) -> tuple[ChatMessage, ...]:
    """Build the complete two-message input from one immutable public snapshot."""
    if type(observation) is not PublicObservation or type(prompt_config) is not PublicPromptConfig:
        raise TypeError("public messages require PublicObservation and PublicPromptConfig")
    if memory_context is not None:
        raise NotImplementedError("Phase 4 does not support memory_context")
    return (ChatMessage("system", _render_system(prompt_config)),
            ChatMessage("user", _canonical({"observation": public_observation_to_dict(observation),
                                             "public_rates": _public_rates(observation)})))


def _reject_constant(value):
    raise ActionResponseError("invalid_json_constant", "Nonstandard JSON constants are forbidden")


def _unique_pairs(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ActionResponseError("duplicate_json_key", "Duplicate JSON keys are forbidden")
        result[key] = value
    return result


def parse_action_response(raw_text: str, *, reason_max_chars=120) -> ActionProposal:
    """Strictly parse final content; never repair, trim a reason, or consult a mask."""
    if type(raw_text) is not str:
        raise ActionResponseError("invalid_content", "Final content must be text")
    try:
        value = json.loads(raw_text, object_pairs_hook=_unique_pairs, parse_constant=_reject_constant)
    except (json.JSONDecodeError, ValueError, RecursionError) as error:
        if isinstance(error, ActionResponseError):
            raise
        raise ActionResponseError("invalid_json", "Final content is not a single JSON value") from None
    if type(value) is not dict or set(value) != {"action", "reason"}:
        raise ActionResponseError("invalid_fields", "Response must contain exactly action and reason")
    action, reason = value["action"], value["reason"]
    if type(action) is not list or len(action) != 5 or any(type(item) is not int for item in action):
        raise ActionResponseError("invalid_action_type", "Action must contain five ordinary integers")
    if (type(reason) is not str or not reason.strip() or len(reason) > reason_max_chars
            or reason.splitlines() != [reason]):
        raise ActionResponseError("invalid_reason", "Reason must be nonempty single-line text within the character limit")
    try:
        vector = ActionVector(tuple(action))
    except (TypeError, ValueError):
        raise ActionResponseError("invalid_action_range", "Action levels are outside the common ranges") from None
    return ActionProposal(vector, reasoning=reason)


@dataclass(frozen=True, slots=True)
class LLMSettings:
    provider: str
    model: str
    endpoint: str
    api_key_env: str
    input_token_budget: int
    max_output_tokens: int
    reason_max_chars: int
    max_attempts: int
    retry_delays_seconds: tuple
    timeout_seconds: float
    temperature: float
    thinking: bool
    primary_effort: str
    primary_top_p: float
    token_count_method: str

    def __post_init__(self):
        url = urlsplit(self.endpoint)
        if (url.scheme != "https" or not url.hostname or url.username or url.password or url.query or url.fragment):
            raise LLMConfigurationError("invalid_endpoint", "Endpoint must be HTTPS without credentials, query or fragment")
        if self.provider not in ("deepseek", "qwen") or not self.model or not self.api_key_env:
            raise LLMConfigurationError("invalid_provider", "Provider, model and credential environment name are required")
        if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", self.api_key_env):
            raise LLMConfigurationError("invalid_credentials_name", "Supply an environment variable name, never a credential value")
        for name in ("input_token_budget", "max_output_tokens", "reason_max_chars"):
            if type(getattr(self, name)) is not int or getattr(self, name) <= 0:
                raise LLMConfigurationError("invalid_settings", f"{name} must be a positive integer")
        if (type(self.max_attempts) is not int or self.max_attempts != 3
                or tuple(self.retry_delays_seconds) != (2, 4)
                or any(type(delay) is not int for delay in self.retry_delays_seconds)):
            raise LLMConfigurationError("invalid_retries", "v1 requires at most three attempts with 2/4 second delays")
        if (type(self.thinking) is not bool or type(self.timeout_seconds) not in (int, float)
                or not isfinite(self.timeout_seconds) or self.timeout_seconds <= 0):
            raise LLMConfigurationError("invalid_settings", "Invalid thinking or timeout setting")
        if (type(self.temperature) not in (int, float) or not isfinite(self.temperature) or self.temperature < 0
                or type(self.primary_top_p) not in (int, float) or not isfinite(self.primary_top_p)
                or not 0 <= self.primary_top_p <= 1 or self.primary_effort not in ("low", "high", "max")):
            raise LLMConfigurationError("invalid_settings", "Invalid sampling or thinking effort setting")
        object.__setattr__(self, "retry_delays_seconds", tuple(self.retry_delays_seconds))

    def request_parameters(self):
        params = {"model": self.model, "temperature": self.temperature,
                  "stream": False}
        if self.provider == "deepseek":
            params.update(max_tokens=self.max_output_tokens, top_p=self.primary_top_p, extra_body={
                "thinking": {"type": "enabled" if self.thinking else "disabled"},
                "reasoning_effort": self.primary_effort})
        else:
            # Qwen max_tokens excludes reasoning; cap the entire completion instead.
            params.update(max_completion_tokens=self.max_output_tokens,
                          extra_body={"enable_thinking": self.thinking})
        return params


@dataclass(frozen=True, slots=True)
class LLMResponse:
    content: str | None
    model: str | None = None
    response_id: str | None = None
    system_fingerprint: str | None = None
    finish_reason: str | None = None
    usage: Mapping = field(default_factory=dict)

    def __post_init__(self):
        for name in ("content", "model", "response_id", "system_fingerprint", "finish_reason"):
            value = getattr(self, name)
            if value is not None and type(value) is not str:
                raise TypeError(f"response {name} must be text or None")
        if not isinstance(self.usage, Mapping):
            raise TypeError("response usage must be a mapping")
        object.__setattr__(self, "usage", _immutable(self.usage))


@dataclass(frozen=True, slots=True)
class LLMCallAudit:
    decision_day: int
    attempt: int
    called_at: str
    provider: str
    endpoint: str
    request_model: str
    request_parameters: Mapping
    messages: tuple[ChatMessage, ...]
    template_version: str
    template_sha256: str
    public_spec_sha256: str
    messages_sha256: str
    tokenizer_identity: Mapping
    input_tokens: int
    input_token_budget: int
    response: LLMResponse | None
    elapsed_ms: float
    error_category: str | None = None
    error_code: str | None = None
    retryable: bool = False
    error_description: str | None = None

    def __post_init__(self):
        for name in ("request_parameters", "tokenizer_identity"):
            object.__setattr__(self, name, _immutable(getattr(self, name)))
        object.__setattr__(self, "messages", tuple(self.messages))


def _provider_error(error, sdk, provider="deepseek"):
    """Classify only known SDK failures; unknown exceptions retain their type."""
    if not isinstance(error, sdk.APIError):
        return None
    body = getattr(error, "body", None)
    code = getattr(error, "code", None)
    structured_message = ""
    if isinstance(body, Mapping):
        nested = body.get("error", body)
        if isinstance(nested, Mapping):
            code = nested.get("code") or nested.get("type") or code
            if type(nested.get("message")) is str:
                structured_message = nested["message"].lower()
    normalized = str(code or "").lower()
    status = getattr(error, "status_code", None)
    # Never log arbitrary remote strings, including unknown remote error codes.
    if (any(word in normalized for word in ("balance", "payment", "arrear", "credit", "billing", "commoditynotpurchased"))
            or any(phrase in structured_message for phrase in (
                "free allocated quota exceeded", "free quota expired", "insufficient balance", "hard quota exceeded"))):
        return LLMConfigurationError("hard_quota_exhausted", "Provider balance or hard quota is exhausted")
    # Qwen's OpenAI-compatible insufficient_quota can mean temporary TPM/TPS
    # throttling. Its meaning cannot be borrowed from another provider.
    if provider == "qwen" and status == 429 and (normalized == "insufficient_quota" or normalized.startswith("throttling")):
        return LLMServiceError("temporary_rate_limit", "Temporary provider request or token rate limit")
    if "quota" in normalized:
        return LLMConfigurationError("hard_quota_exhausted", "Provider balance or hard quota is exhausted")
    if any(word in normalized for word in ("api_key", "authentication", "permission", "invalid_model", "model_not_found", "invalid_parameter")):
        return LLMConfigurationError("provider_configuration", "Provider rejected credentials, model or parameters")
    if normalized in ("invalid_request_error", "unsupported_parameter", "badrequest", "modelnotfound"):
        return LLMConfigurationError("provider_configuration", "Provider rejected request configuration")
    if normalized in ("rate_limit_exceeded", "ratelimitexceeded", "throttling", "request_timeout", "service_unavailable"):
        return LLMServiceError("temporary_service", "Temporary provider rate limit, timeout or service failure")
    if isinstance(error, (sdk.APIConnectionError, sdk.APITimeoutError)):
        return LLMServiceError("temporary_connection", "Provider connection or timeout failure")
    if status == 402:
        return LLMConfigurationError("hard_quota_exhausted", "Provider balance or hard quota is exhausted")
    if status in (400, 401, 403, 404, 405, 422):
        return LLMConfigurationError(f"provider_http_{status}", "Provider rejected request configuration")
    if status in (408, 429, 500, 502, 503, 504):
        return LLMServiceError(f"provider_http_{status}", "Temporary provider service failure")
    return None


class LLMTransport:
    """One SDK request, no retry, no conversation state, no secret in settings."""

    def __init__(self, settings: LLMSettings, *, client=None):
        self.settings = settings
        self._client = client

    def prepare(self):
        if self._client is None:
            key = os.environ.get(self.settings.api_key_env)
            if not key:
                raise LLMConfigurationError("missing_credentials", "Provider credential environment variable is not set")
            try:
                from openai import OpenAI
            except ImportError:
                raise LLMConfigurationError("sdk_unavailable", "Install the declared control LLM SDK dependency") from None
            self._client = OpenAI(api_key=key, base_url=self.settings.endpoint,
                                  timeout=self.settings.timeout_seconds, max_retries=0)

    def complete(self, messages: tuple[ChatMessage, ...]) -> LLMResponse:
        self.prepare()
        import openai

        # with_options also disables retries on an injected OpenAI client.
        client = self._client.with_options(max_retries=0, timeout=self.settings.timeout_seconds)
        try:
            result = client.chat.completions.create(
                messages=resolved_snapshot(messages), **self.settings.request_parameters())
        except openai.APIError as error:
            classified = _provider_error(error, openai, self.settings.provider)
            if classified is None:
                raise
            raise classified from None
        choices = result.choices
        choice = choices[0] if choices else None
        usage = result.usage.model_dump(mode="json") if result.usage is not None else {}
        return LLMResponse(content=choice.message.content if choice else None, model=result.model,
                           response_id=result.id, system_fingerprint=getattr(result, "system_fingerprint", None),
                           finish_reason=choice.finish_reason if choice else None, usage=usage)


class OfficialInputTokenCounter:
    """Pinned local counting with independent, optional acceptance validation."""

    def __init__(self, resource_manifest: str | Path, *, acceptance_path=None):
        self.manifest_path = Path(resource_manifest).resolve()
        self.acceptance_path = Path(acceptance_path).resolve() if acceptance_path else None
        self._tokenizer = None
        self._identity = None
        self._expected_service = None

    @property
    def identity(self):
        if self._identity is None:
            return MappingProxyType({"status": "not_loaded"})
        return self._identity

    def _load(self, settings):
        try:
            manifest = json.loads(self.manifest_path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            raise LLMConfigurationError("tokenizer_missing", "Cannot read local tokenizer resource manifest") from None
        self._manifest = manifest
        required = ("adapter", "provider", "model", "official_source", "library_versions", "files",
                    "chat_template_file", "template_kwargs", "request_parameters_sha256")
        _exact_keys(manifest, required, "tokenizer manifest")
        if self._identity is not None and self._identity["manifest_sha256"] != snapshot_sha256(manifest):
            raise LLMConfigurationError("tokenizer_resources_changed", "Tokenizer manifest changed during this batch")
        if (manifest["adapter"] != "hf_apply_chat_template_v1" or settings.token_count_method != "official_local_chat_template_v1"
                or (manifest["provider"], manifest["model"]) != (settings.provider, settings.model)
                or manifest["request_parameters_sha256"] != snapshot_sha256(settings.request_parameters())):
            raise LLMConfigurationError("tokenizer_incompatible", "Tokenizer model, adapter or request mode is incompatible")
        if not isinstance(manifest["official_source"], str) or not manifest["official_source"].startswith("https://"):
            raise LLMConfigurationError("tokenizer_provenance_missing", "Official resource provenance is required")
        _exact_keys(manifest["library_versions"], ("transformers", "tokenizers", "jinja2", "markupsafe"), "tokenizer libraries")
        for name, expected in manifest["library_versions"].items():
            try:
                actual = package_version(name)
            except PackageNotFoundError:
                raise LLMConfigurationError("tokenizer_library_missing", "Tokenizer loading library is absent") from None
            if actual != expected:
                raise LLMConfigurationError("tokenizer_library_mismatch", "Tokenizer loading library version differs from the pin")
        root = self.manifest_path.parent
        files = manifest["files"]
        if not isinstance(files, dict) or not files or manifest["chat_template_file"] not in files:
            raise LLMConfigurationError("tokenizer_template_missing", "A pinned chat template is required")
        for filename, expected in files.items():
            path = (root / filename).resolve()
            if not path.is_relative_to(root):
                raise LLMConfigurationError("tokenizer_invalid_path", "Tokenizer resources must stay in their local directory")
            try:
                actual = hashlib.sha256(path.read_bytes()).hexdigest()
            except OSError:
                raise LLMConfigurationError("tokenizer_missing", "A pinned tokenizer resource is absent") from None
            if actual != expected:
                raise LLMConfigurationError("tokenizer_hash_mismatch", "Tokenizer resource hash differs from the pin")
        # Refuse unpinned loader inputs as well as changed pinned inputs.
        loader_files = {path.relative_to(root).as_posix() for path in root.rglob("*")
                        if path.is_file() and path.suffix in (".json", ".jinja", ".model", ".txt", ".tiktoken")
                        and path.resolve() not in (self.manifest_path, self.acceptance_path)}
        if not loader_files.issubset(files):
            raise LLMConfigurationError("tokenizer_unpinned_files", "Tokenizer directory contains unpinned loading resources")
        if not isinstance(manifest["template_kwargs"], dict):
            raise LLMConfigurationError("tokenizer_template_invalid", "Template arguments must be an object")
        if set(manifest["template_kwargs"]) & {
                "tokenize", "add_generation_prompt", "return_tensors", "return_dict", "chat_template",
                "truncation", "padding", "max_length", "tokenizer_kwargs", "continue_final_message", "tools", "documents"}:
            raise LLMConfigurationError("tokenizer_template_invalid", "Template arguments cannot override complete-request counting")
        if self._tokenizer is None:
            try:
                from transformers import AutoTokenizer

                self._tokenizer = AutoTokenizer.from_pretrained(str(root), local_files_only=True, trust_remote_code=False)
            except (OSError, ValueError, ImportError):
                raise LLMConfigurationError("tokenizer_load_failed", "Pinned local tokenizer could not be loaded") from None
        template = (root / manifest["chat_template_file"]).read_text(encoding="utf-8")
        if not template.strip():
            raise LLMConfigurationError("tokenizer_template_missing", "Chat template must not be empty")
        self._tokenizer.chat_template = template
        self._identity = _immutable({**manifest, "manifest_sha256": snapshot_sha256(manifest)})

    def validate(self, settings):
        """Check the current counting resources; a report is not a prerequisite."""
        self._load(settings)

    def validate_acceptance(self, settings):
        """Explicitly check a development report, outside normal episode startup."""
        self._load(settings)
        if self.acceptance_path is None:
            raise LLMConfigurationError("tokenizer_not_accepted", "Select a provider acceptance report to validate")
        try:
            receipt = json.loads(self.acceptance_path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            raise LLMConfigurationError("tokenizer_not_accepted", "Cannot read provider acceptance receipt") from None
        _exact_keys(receipt, ("version", "status", "experimental_trajectory", "accepted_at", "tokenizer_identity",
                              "endpoint", "request_parameters", "cases", "sha256"), "acceptance receipt")
        content = {key: value for key, value in receipt.items() if key != "sha256"}
        if (receipt["version"] != "cemas-provider-token-count-acceptance-v1" or receipt["experimental_trajectory"] is not False
                or receipt.get("sha256") != snapshot_sha256(content) or receipt.get("status") != "accepted"
                or receipt.get("tokenizer_identity") != resolved_snapshot(self._identity)
                or receipt.get("endpoint") != settings.endpoint
                or receipt.get("request_parameters") != settings.request_parameters()):
            raise LLMConfigurationError("tokenizer_acceptance_mismatch", "Provider acceptance does not match current resources or request")
        cases = receipt.get("cases", [])
        if (type(cases) is not list or len(cases) != 3 or any(type(case) is not dict for case in cases)
                or {case.get("name") for case in cases} != {"day0", "four_weeks", "long_numeric"}):
            raise LLMConfigurationError("tokenizer_acceptance_incomplete", "Acceptance requires all three public input cases")
        for case in cases:
            response = case.get("response", {})
            count = case.get("input_tokens")
            if type(response) is not dict or type(response.get("usage")) is not dict:
                raise LLMConfigurationError("tokenizer_acceptance_invalid", "Acceptance must retain raw provider usage")
            if (type(count) is not int or count <= 0 or count > settings.input_token_budget
                    or response.get("usage", {}).get("prompt_tokens") != count
                    or not response.get("response_id") or not response.get("model")
                    or case.get("messages_sha256") != snapshot_sha256(case.get("messages"))):
                raise LLMConfigurationError("tokenizer_acceptance_invalid", "Acceptance has missing or inconsistent call evidence")
        services = {(case["response"]["model"], case["response"].get("system_fingerprint")) for case in cases}
        if len(services) != 1:
            raise LLMConfigurationError("provider_changed", "Acceptance cases returned different service identities")
        return receipt

    def verify_response(self, response):
        service = (response.model, response.system_fingerprint)
        if self._expected_service is None:
            self._expected_service = service
        elif self._expected_service != service:
            raise LLMConfigurationError("provider_changed", "Provider model or fingerprint changed during this batch")

    def count_input(self, messages, settings):
        self._load(settings)
        encoded = self._tokenizer.apply_chat_template(
            resolved_snapshot(messages), tokenize=True, add_generation_prompt=True, return_dict=False,
            truncation=False, padding=False,
            **self._manifest["template_kwargs"])
        if not isinstance(encoded, list) or any(type(token) is not int for token in encoded):
            raise LLMConfigurationError("tokenizer_invalid_result", "Official chat tokenizer must return a flat token id list")
        return len(encoded)


class LLMController(Controller):
    controller_type = "llm"
    method = "llm_no_explicit_memory"

    def __init__(self, transport, prompt_config: PublicPromptConfig, settings: LLMSettings,
                 token_counter: OfficialInputTokenCounter, *, sleeper=time.sleep, clock=time.perf_counter):
        if type(prompt_config) is not PublicPromptConfig or type(settings) is not LLMSettings:
            raise TypeError("LLMController requires projected prompt config and settings")
        if settings.reason_max_chars != prompt_config.reason_max_chars:
            raise LLMConfigurationError("reason_limit_mismatch", "Prompt and parser reason limits must agree")
        self.transport, self.prompt_config, self.settings = transport, prompt_config, settings
        self.token_counter, self._sleeper, self._clock = token_counter, sleeper, clock
        self.reset()

    def reset(self):
        self._failure_reason = None
        self._audits = []

    def observe(self, feedback):
        if type(feedback) is not PublicWeekFeedback:
            raise TypeError("LLMController requires PublicWeekFeedback")

    def consume_failure_reason(self):
        result, self._failure_reason = self._failure_reason, None
        return result

    def drain_call_audits(self):
        result, self._audits = tuple(self._audits), []
        return result

    def run_metadata(self):
        return {"method": self.method, "template_version": self.prompt_config.version,
                "template_sha256": self.prompt_config.template_sha256,
                "public_spec_sha256": self.prompt_config.public_spec_sha256,
                "llm_settings": resolved_snapshot(self.settings),
                "live_provider": isinstance(self.transport, LLMTransport),
                "transport_type": type(self.transport).__name__,
                "tokenizer_identity": resolved_snapshot(self.token_counter.identity)}

    def _prepare_input(self, observation):
        """Build and count one immutable input before entering the shared retry loop."""
        messages = build_public_messages(observation, self.prompt_config)
        count = None
        try:
            self.token_counter.validate(self.settings)
            count = self.token_counter.count_input(messages, self.settings)
            if type(count) is not int or count < 0:
                raise LLMConfigurationError("tokenizer_invalid_result", "Input token count must be a nonnegative ordinary integer")
            if count > self.settings.input_token_budget:
                raise PromptBudgetError(count, self.settings.input_token_budget, snapshot_sha256(messages))
            return messages, count
        except LLMError as error:
            error.details = _immutable({**error.details, "messages_sha256": snapshot_sha256(messages),
                                        "input_tokens": count})
            raise

    def _parse_response(self, response, observation):
        return parse_action_response(response.content, reason_max_chars=self.settings.reason_max_chars)

    def _decision_finished(self, observation, proposal, attempt_count):
        """Extension point for public evidence; never adds a provider call."""

    def decide(self, observation):
        self._failure_reason = None
        messages, digest, count = (), None, None
        try:
            if isinstance(self.transport, LLMTransport) and not isinstance(self.token_counter, OfficialInputTokenCounter):
                raise LLMConfigurationError("tokenizer_not_official", "Live transports require the pinned official token counter")
            messages, count = self._prepare_input(observation)
            digest = snapshot_sha256(messages)
            self.transport.prepare()
        except LLMError as error:
            error.details = _immutable({**error.details,
                                        "messages_sha256": digest or error.details.get("messages_sha256"),
                                        "template_sha256": self.prompt_config.template_sha256,
                                        "public_spec_sha256": self.prompt_config.public_spec_sha256,
                                        "input_tokens": count if count is not None else error.details.get("input_tokens"),
                                        "input_token_budget": self.settings.input_token_budget})
            raise
        for attempt in range(1, self.settings.max_attempts + 1):
            started = self._clock()
            called_at = datetime.now(timezone.utc).isoformat()
            response = None
            caught = None
            try:
                response = self.transport.complete(messages)
                if type(response) is not LLMResponse:
                    raise TypeError("transport must return LLMResponse")
                actual = response.usage.get("prompt_tokens")
                if actual is not None and (type(actual) is not int or actual != count
                                           or actual > self.settings.input_token_budget):
                    raise TokenCountMismatchError("token_count_mismatch", "Provider input usage disagrees with the accepted local counter",
                                                  details={"input_tokens": count, "provider_input_tokens": actual,
                                                           "input_token_budget": self.settings.input_token_budget,
                                                           "messages_sha256": digest})
                self.token_counter.verify_response(response)
                if response.finish_reason == "length":
                    raise ActionResponseError("truncated_content", "Provider output reached its generation limit")
                proposal = self._parse_response(response, observation)
                self._decision_finished(observation, proposal, attempt)
                return proposal
            except (LLMServiceError, ActionResponseError) as error:
                caught = error
            except BaseException as error:
                caught = error
                raise
            finally:
                known = isinstance(caught, LLMError)
                self._audits.append(LLMCallAudit(
                    observation.decision_day, attempt, called_at, self.settings.provider,
                    self.settings.endpoint, self.settings.model, self.settings.request_parameters(), messages,
                    self.prompt_config.version, self.prompt_config.template_sha256,
                    self.prompt_config.public_spec_sha256, digest, self.token_counter.identity,
                    count, self.settings.input_token_budget, response, (self._clock() - started) * 1000,
                    type(caught).__name__ if caught else None, caught.code if known else ("unexpected_error" if caught else None),
                    caught.retryable if known else False,
                    str(caught) if known else ("Unexpected transport or program failure" if caught else None)))
            if attempt < self.settings.max_attempts:
                self._sleeper(self.settings.retry_delays_seconds[attempt - 1])
        self._failure_reason = "llm_retry_exhausted"
        self._decision_finished(observation, None, self.settings.max_attempts)
        return None
