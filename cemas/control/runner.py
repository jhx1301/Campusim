"""Sequential v1 runs; protocol projection and private audit belong here."""

from dataclasses import dataclass, fields
from datetime import datetime, timezone
import json
from math import fsum, isclose
from pathlib import Path
import sys
from time import perf_counter
from types import MappingProxyType
from weakref import WeakKeyDictionary

_MEMORY_SOURCE_MANIFESTS = WeakKeyDictionary()

from .controllers import Controller
from .logging import (
    DecisionRecord, RunLogger, hash_observation, resolved_snapshot, snapshot_sha256,
)
from .protocol import ControlProtocol
from .rewards import V1RewardCalculator
from .types import ActionProposal, ExecutedAction, PublicCost


@dataclass(frozen=True, slots=True)
class RunResult:
    status: str
    output_dir: Path
    summary: object


def _add_error_note(error, message):
    """Retain secondary failures without masking the original on Python 3.10."""
    add_note = getattr(error, "add_note", None)
    if add_note is not None:
        add_note(message)
    else:
        error.__notes__ = [*getattr(error, "__notes__", ()), message]


def _validate_development_seed(protocol, seed, purpose):
    seeds = protocol.definition["seeds"]
    if purpose == "smoke":
        if seed not in seeds["smoke"]:
            raise ValueError("smoke runs require protocol smoke seeds; final-test worlds are forbidden")
    elif purpose == "scientific":
        if not any(seeds[name]["start_inclusive"] <= seed <= seeds[name]["end_inclusive"]
                   for name in ("validation_A", "validation_B")):
            raise ValueError("scientific runs require source validation seeds; final-test worlds are forbidden")
    elif purpose == "pilot":
        if seed not in protocol.definition["source"]["pilot_worlds"]:
            raise ValueError("pilot requires reserved pilot seeds; final-test worlds are forbidden")
    elif purpose == "memory_collection":
        pool = seeds["memory_collection"]
        if not pool["start_inclusive"] <= seed <= pool["end_inclusive"]:
            raise ValueError("memory_collection requires reserved source seeds; final-test worlds are forbidden")
    elif purpose == "prompt_development":
        pool = seeds["prompt_development"]
        if not pool["start_inclusive"] <= seed <= pool["end_inclusive"]:
            raise ValueError("prompt_development runs require reserved source seeds; final-test worlds are forbidden")
    else:
        raise ValueError("purpose must be smoke, scientific, pilot, prompt_development or memory_collection")


def make_public_prompt_config(protocol: ControlProtocol, *, template_path=None):
    """Project nested allowlists, never pass the complete protocol to an LLM."""
    from .llm import LLMConfigurationError, PUBLIC_SPEC_FIELDS, PublicPromptConfig

    if type(protocol) is not ControlProtocol:
        raise TypeError("prompt factory requires ControlProtocol")
    llm = protocol.definition["controllers"]["llm"]
    path = Path(template_path) if template_path is not None else Path(__file__).resolve().parents[2] / llm["prompt_template"]
    try:
        template = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        raise LLMConfigurationError("template_unavailable", "Cannot read the public prompt template") from None
    spec = {}
    for section, keys in PUBLIC_SPEC_FIELDS.items():
        if section == "task":
            engine = protocol.definition["engine"]
            spec[section] = {"decision_interval_days": engine["decision_interval_days"],
                             "history_weeks": engine["history_weeks"], "quarantine_days": engine["quar_period"]}
        else:
            source = protocol.definition[section]
            spec[section] = {key: source[key] for key in keys}
    for dimension in protocol.action_order:
        spec["actions"][dimension] = tuple({"level": entry["level"],
                                            "effective_parameters": entry["effective_parameters"]}
                                           for entry in protocol.definition["actions"][dimension])
    return PublicPromptConfig(template, spec, llm["reason_max_chars"])


def make_llm_settings(protocol: ControlProtocol, *, provider="deepseek", endpoint, api_key_env):
    """Model parameters retain their single source in the validated protocol."""
    from .llm import LLMSettings

    llm = protocol.definition["controllers"]["llm"]
    keys = ("input_token_budget", "max_output_tokens", "reason_max_chars", "max_attempts",
            "retry_delays_seconds", "timeout_seconds", "temperature", "thinking", "primary_effort",
            "primary_top_p", "token_count_method")
    model_key = "primary_api_model" if provider == "deepseek" else "secondary_api_model"
    return LLMSettings(provider=provider, model=llm[model_key], endpoint=endpoint,
                       api_key_env=api_key_env, **{key: llm[key] for key in keys})


def make_llm_controller(protocol: ControlProtocol, *, endpoint, api_key_env, tokenizer_manifest,
                        tokenizer_acceptance=None, provider="deepseek", client=None):
    """Build a runtime controller; the legacy report argument is ignored."""
    from .llm import LLMController, LLMTransport, OfficialInputTokenCounter

    settings = make_llm_settings(protocol, provider=provider, endpoint=endpoint, api_key_env=api_key_env)
    return LLMController(LLMTransport(settings, client=client), make_public_prompt_config(protocol), settings,
                         OfficialInputTokenCounter(tokenizer_manifest))


def accept_llm_token_counter(transport, counter, prompt_config, observations, output_dir):
    """Record three isolated provider probes, never an experimental episode.

    The caller supplies exact public types. Results are development evidence,
    independent of normal episode startup.
    """
    from .llm import (
        LLMCallAudit, LLMConfigurationError, LLMError, LLMResponse, PromptBudgetError,
        TokenCountMismatchError, build_public_messages, parse_action_response,
    )
    from .types import PublicObservation

    names = ("day0", "four_weeks", "long_numeric")
    if set(observations) != set(names) or any(type(observations[name]) is not PublicObservation for name in names):
        raise TypeError("acceptance requires day0, four_weeks and long_numeric PublicObservation cases")
    if observations["day0"].decision_day != 0 or any(observations["day0"].week_valid):
        raise ValueError("day0 acceptance case must have empty history")
    if not all(all(observations[name].week_valid) for name in names[1:]):
        raise ValueError("four-week and numeric acceptance cases require four valid public weeks")
    base = build_public_messages(observations["four_weeks"], prompt_config)
    stress = build_public_messages(observations["long_numeric"], prompt_config)
    if len(stress[1].content) <= len(base[1].content):
        raise ValueError("long_numeric must exercise a longer public numeric payload")
    settings = transport.settings
    output = Path(output_dir)
    output.mkdir(parents=True, exist_ok=False)

    def write(filename, content):
        with (output / filename).open("x", encoding="utf-8", newline="\n") as handle:
            handle.write(json.dumps(resolved_snapshot(content), ensure_ascii=False, indent=2, allow_nan=False) + "\n")
            handle.flush()
            import os

            os.fsync(handle.fileno())

    write("manifest.json", {"purpose": "provider_tokenizer_acceptance", "experimental_trajectory": False})
    cases = []
    service = None
    try:
        transport.prepare()
        for name in names:
            observation = observations[name]
            messages = build_public_messages(observation, prompt_config)
            digest = snapshot_sha256(messages)
            count = counter.count_input(messages, settings)
            if count > settings.input_token_budget:
                raise PromptBudgetError(count, settings.input_token_budget, digest)
            called_at = datetime.now(timezone.utc).isoformat()
            started = perf_counter()
            response = error = None
            try:
                response = transport.complete(messages)
                if type(response) is not LLMResponse:
                    raise TypeError("transport must return LLMResponse")
                if response.usage.get("prompt_tokens") != count:
                    raise TokenCountMismatchError("token_count_mismatch", "Candidate counter differs from provider usage",
                                                  details={"input_tokens": count, "messages_sha256": digest})
                if not response.model or not response.response_id:
                    raise LLMConfigurationError("provider_identity_missing", "Acceptance requires returned model and response id")
                current_service = (response.model, response.system_fingerprint)
                if service is not None and service != current_service:
                    raise LLMConfigurationError("provider_changed", "Provider identity changed during acceptance")
                service = current_service
                if response.finish_reason == "length":
                    raise LLMConfigurationError("acceptance_output_truncated", "Acceptance response was truncated")
                parse_action_response(response.content, reason_max_chars=settings.reason_max_chars)
            except BaseException as caught:
                error = caught
                raise
            finally:
                audit = LLMCallAudit(
                    observation.decision_day, 1, called_at, settings.provider, settings.endpoint, settings.model,
                    settings.request_parameters(), messages, prompt_config.version, prompt_config.template_sha256,
                    prompt_config.public_spec_sha256, digest, counter.identity, count, settings.input_token_budget,
                    response, (perf_counter() - started) * 1000,
                    type(error).__name__ if error else None,
                    error.code if isinstance(error, LLMError) else ("unexpected_error" if error else None),
                    error.retryable if isinstance(error, LLMError) else False,
                    str(error) if isinstance(error, LLMError) else ("Unexpected provider acceptance failure" if error else None))
                with (output / "llm_calls.jsonl").open("a", encoding="utf-8", newline="\n") as handle:
                    handle.write(json.dumps(resolved_snapshot(audit), ensure_ascii=False, allow_nan=False) + "\n")
                    handle.flush()
                    import os

                    os.fsync(handle.fileno())
            cases.append({"name": name, "messages": resolved_snapshot(messages), "messages_sha256": digest,
                          "input_tokens": count, "response": resolved_snapshot(response)})
        receipt = {"version": "cemas-provider-token-count-acceptance-v1", "status": "accepted",
                   "experimental_trajectory": False, "accepted_at": datetime.now(timezone.utc).isoformat(),
                   "tokenizer_identity": resolved_snapshot(counter.identity), "endpoint": settings.endpoint,
                   "request_parameters": settings.request_parameters(), "cases": cases}
        receipt["sha256"] = snapshot_sha256(receipt)
        write("tokenizer_acceptance.json", receipt)
        return output / "tokenizer_acceptance.json"
    except BaseException as error:
        write("failure.json", {"error_type": type(error).__name__,
                               "error": str(error) if isinstance(error, LLMError) else "Provider acceptance failed",
                               "details": error.details if isinstance(error, LLMError) else {}})
        raise


def episode_summary(protocol, snapshot, population):
    if (snapshot.status != "completed" or snapshot.elapsed_days != snapshot.horizon
            or snapshot.terminal_metrics is None):
        raise RuntimeError("environment did not complete its announced horizon")
    if len(snapshot.public_daily) != snapshot.horizon or len(snapshot.private_daily) != snapshot.horizon:
        raise ValueError("completed run must contain every public and private day")
    totals = {field.name: fsum(getattr(day.cost, field.name) for day in snapshot.public_daily)
              for field in fields(PublicCost)}
    for name in ("clinical_tests", "screening_tests", "delivered_notifications"):
        totals[name] = int(totals[name])
    cost = PublicCost(**totals)
    for name, total in totals.items():
        weekly = fsum(getattr(window.feedback.week.cost, name) for window in snapshot.windows)
        if not isclose(total, weekly, rel_tol=1e-10, abs_tol=1e-8):
            raise ValueError(f"daily/weekly {name} mismatch")
    diagnoses = sum(day.delivered_diagnoses for day in snapshot.public_daily)
    if diagnoses != sum(window.feedback.week.delivered_diagnoses for window in snapshot.windows):
        raise ValueError("daily/weekly delivered diagnoses mismatch")
    infections = sum(day.new_infections for day in snapshot.private_daily)
    terminal = snapshot.terminal_metrics
    if (infections != sum(window.private_metrics.new_infections for window in snapshot.windows)
            or infections != terminal.new_infections
            or terminal.cumulative_infections != terminal.initial_infections + infections):
        raise ValueError("daily/weekly/terminal infection counts mismatch")
    history = tuple(ExecutedAction(window.start_day, window.end_day,
                                   window.resolution.executed_action)
                    for window in snapshot.windows)
    calculator = V1RewardCalculator(protocol, population, snapshot.horizon)
    breakdown = calculator.breakdown(terminal, cost, history)
    reward = fsum(window.reward for window in snapshot.windows)
    if not isclose(reward, breakdown.reward, rel_tol=1e-10, abs_tol=1e-10):
        raise ValueError("weekly return does not equal terminal objective")
    switches = [0] * 5
    changes = [0] * 5
    for previous, current in zip(history, history[1:]):
        for index, (before, after) in enumerate(zip(previous.action.values, current.action.values)):
            switches[index] += int(before != after)
            changes[index] += abs(after - before)
    return {
        "status": "completed", "elapsed_days": snapshot.elapsed_days,
        "execution_days": snapshot.horizon, "decision_count": len(snapshot.windows),
        "population": population, "delivered_diagnoses": diagnoses,
        "private_metrics": resolved_snapshot(terminal), "public_cost": resolved_snapshot(cost),
        "total_reward": reward, "positive_cost": -reward,
        "reward_breakdown": resolved_snapshot(breakdown),
        "reward_configuration": calculator.configuration,
        "objective_sha256": snapshot_sha256(calculator.configuration),
        "switches_by_dimension": switches, "level_changes_by_dimension": changes,
        "fallback_count": sum(window.resolution.fallback_reason is not None for window in snapshot.windows),
        "adjustment_count": sum(window.resolution.adjustment_reason is not None for window in snapshot.windows),
        "pending_notifications": snapshot.pending_notifications,
        "pending_diagnoses": snapshot.pending_diagnoses,
        "daily_weekly_terminal_reconciled": True,
    }


def run_episode(protocol: ControlProtocol, controller: Controller, output_dir: str | Path,
                world_seed: int, *, purpose="smoke", mode="evaluation", scenario_options=None,
                public_transition_sink=None) -> RunResult:
    """Run one attempt, retaining failure evidence and refusing existing paths.

    The controller receives only ``reset()``, a PublicObservation, and closed
    PublicWeekFeedback. Mode and all private audit values stay in this runner.
    """
    if type(protocol) is not ControlProtocol or not isinstance(controller, Controller):
        raise TypeError("run_episode requires ControlProtocol and Controller")
    if type(world_seed) is not int:
        raise TypeError("world_seed must be an ordinary integer")
    _validate_development_seed(protocol, world_seed, purpose)
    controller_type = getattr(controller, "controller_type", None)
    if controller_type not in ("minimum", "maximum_feasible", "llm", "uniform_legal_independent_rng", "threshold", "ppo", "ddqn"):
        raise ValueError("runner requires an implemented v1 controller")
    if public_transition_sink is not None and not callable(public_transition_sink):
        raise TypeError("public_transition_sink must be callable with public observation and feedback")
    if purpose == "memory_collection" and controller_type not in ("minimum", "maximum_feasible", "uniform_legal_independent_rng", "threshold"):
        raise ValueError("memory_collection supports only the implemented non-LLM collection policies")
    if controller_type == "uniform_legal_independent_rng" and purpose not in ("smoke", "memory_collection"):
        raise ValueError("uniform legal policy is limited to smoke and memory_collection")
    if purpose == "prompt_development" and controller_type != "llm":
        raise ValueError("prompt_development is reserved for the public LLM controller")
    if controller_type == "llm":
        from .llm import LLMTransport

        live = isinstance(controller.transport, LLMTransport)
        if ((live and purpose not in ("prompt_development", "scientific", "pilot"))
                or (not live and purpose != "smoke")):
            raise ValueError("live LLM calls require reserved source worlds; offline transports require smoke")
    if getattr(controller, "method", None) == "llm_public_memory_v1":
        _validate_memory_run(protocol, controller, purpose, scenario_options)
    manifest = {
        "protocol_id": protocol.protocol_id, "protocol_sha256": protocol.source_sha256,
        "world_seed": world_seed, "controller_type": controller_type,
        "purpose": purpose, "mode": mode, "train_seed": None,
        "controller_seed": getattr(controller, "_controller_seed", None),
        "paired_world": world_seed, "started_at": datetime.now(timezone.utc).isoformat(),
    }
    if controller_type == "llm":
        manifest["llm"] = controller.run_metadata()
    if controller_type in ("threshold", "ppo", "ddqn"):
        from .controllers import _BASELINE_METADATA
        metadata = _BASELINE_METADATA.get(controller)
        if metadata is not None:
            manifest["baseline"] = metadata
    manifest["run_purpose"] = purpose
    logger = RunLogger(output_dir, manifest)
    environment = None
    call_audit_error = None
    try:
        from .environment import WeeklyControlEnvironment

        environment = WeeklyControlEnvironment(protocol, mode=mode,
                                               purpose="scientific" if purpose in ("prompt_development", "memory_collection", "pilot") else purpose,
                                               scenario_options=scenario_options)
        reset_started = perf_counter()
        observation, _ = environment.reset(world_seed)
        initialization_seconds = perf_counter() - reset_started
        if "artifact_sha256" in manifest.get("baseline", {}) and purpose != "smoke":
            baseline = manifest["baseline"]
            actual_calibration = environment.audit_snapshot().manifest["calibration"]["artifact_sha256"]
            if (observation.execution_days != baseline["reference_horizon"]
                    or actual_calibration != baseline["calibration_artifact_sha256"]):
                raise ValueError("loaded baseline and evaluation task use different H or E0 identities")
        population = observation.population.population
        controller.reset()
        logger.write_snapshot(environment.audit_snapshot())
        while True:
            decision_time = datetime.now(timezone.utc)
            started = perf_counter()
            call_audits, decision_evidence = (), ()
            decision_error = None
            try:
                proposal = controller.decide(observation)
            except BaseException as error:
                decision_error = error
                raise
            finally:
                elapsed_ms = (perf_counter() - started) * 1000
                try:
                    call_audits = controller.drain_call_audits()
                    logger.write_llm_calls(call_audits, metadata=controller.run_metadata()
                                           if controller_type == "llm" else None)
                    decision_evidence = controller.drain_decision_evidence()
                    logger.write_decision_evidence(decision_evidence)
                except Exception as audit_error:
                    if decision_error is None:
                        raise
                    call_audit_error = {"stage": "call_audit_delivery", "error_type": type(audit_error).__name__,
                                        "error": "Call audit delivery failed"}
                    _add_error_note(decision_error,
                                    f"Call audit delivery also failed ({type(audit_error).__name__})")
            failure_reason = controller.consume_failure_reason()
            if proposal is None and (type(failure_reason) is not str or not failure_reason.strip()):
                raise ValueError("a missing proposal requires a nonempty controller failure reason")
            if proposal is not None and failure_reason is not None:
                raise ValueError("a proposal cannot also carry a controller failure reason")
            if proposal is not None and type(proposal) is not ActionProposal:
                raise TypeError("controllers must return ActionProposal or None")
            next_observation, _, terminated, truncated, _ = environment.step_proposal(
                proposal, fallback_reason=failure_reason)
            snapshot = environment.audit_snapshot()
            window = snapshot.windows[-1]
            resolution = window.resolution
            valid_proposal = proposal if type(proposal) is ActionProposal else None
            decision = DecisionRecord(
                hash_observation(observation), observation.decision_day, decision_time,
                controller_type, valid_proposal, resolution.executed_action,
                fallback_used=resolution.fallback_reason is not None,
                fallback_reason=resolution.fallback_reason,
                adjustment_reason=resolution.adjustment_reason,
                reasoning=valid_proposal.reasoning if valid_proposal else None,
                retrieved_case_ids=tuple(decision_evidence[-1].get("selected_case_ids", ())) if decision_evidence else (),
                elapsed_ms=elapsed_ms,
                llm_attempt_count=len(call_audits),
                llm_succeeded=(proposal is not None) if controller_type == "llm" else None,
            )
            logger.write_decision(decision, observation=observation, resolution=resolution)
            logger.write_snapshot(snapshot)
            logger.write_evidence_resolution(decision_evidence, resolution)
            controller.observe(window.feedback)
            logger.write_memory_revisions(controller.drain_case_revisions())
            if public_transition_sink is not None:
                public_transition_sink(observation, window.feedback)
            if truncated:
                raise RuntimeError("an interrupted run cannot be reported as complete")
            if terminated:
                break
            observation = next_observation
        environment.close()
        snapshot = environment.audit_snapshot()
        summary = episode_summary(protocol, snapshot, population)
        if purpose == "pilot":
            summary["initialization_seconds"] = initialization_seconds
        logger.complete(summary)
        return RunResult("completed", Path(output_dir), MappingProxyType(summary))
    except BaseException as error:
        snapshot = None
        if environment is not None:
            try:
                environment.close()
                snapshot = environment.audit_snapshot()
            except Exception as close_error:
                description = type(close_error).__name__ if call_audit_error is not None else close_error
                _add_error_note(error, f"Environment cleanup also failed: {description}")
        try:
            from .llm import LLMError

            details = {"error_code": error.code, **error.details} if isinstance(error, LLMError) else {}
            if call_audit_error is not None:
                details["call_audit_error"] = call_audit_error
            logger.fail(error, snapshot, safe_error=(str(error) if isinstance(error, LLMError)
                                                    else "LLM run failed; inspect the raised exception locally")
                        if controller_type == "llm" else None,
                        details=details or None)
        except Exception as log_error:
            description = type(log_error).__name__ if call_audit_error is not None else log_error
            _add_error_note(error, f"Failure audit could not be completed: {description}")
        raise
    finally:
        active_error = sys.exc_info()[1]
        try:
            logger.close()
        except Exception as close_error:
            if active_error is None:
                raise
            description = type(close_error).__name__ if call_audit_error is not None else close_error
            _add_error_note(active_error, f"Log cleanup also failed: {description}")


def memory_source_compatibility(protocol, calibration_artifact=None, *, execution_days=None, data_path=None):
    """Compute private source compatibility outside every public memory component."""
    import hashlib
    from .calibration import load_calibration_artifact
    root = Path(__file__).resolve().parents[2]
    source = {}
    for directory in (root / "cemas/control", root / "covasim"):
        for path in sorted(directory.rglob("*.py")):
            source[path.relative_to(root).as_posix()] = hashlib.sha256(path.read_bytes()).hexdigest()
    objective = resolved_snapshot(protocol.definition["objective"])
    objective.pop("status", None)
    days = protocol.definition["engine"]["execution_days"] if execution_days is None else execution_days
    objective["execution_days"] = days
    artifact_sha = None
    if calibration_artifact is not None:
        artifact_sha = load_calibration_artifact(calibration_artifact, protocol, require_evaluation=True, data_path=data_path).sha256
    return {"source_code_sha256": snapshot_sha256(source), "calibration_artifact_sha256": artifact_sha,
            "execution_days": days, "objective_sha256": snapshot_sha256(objective)}


def make_memory_llm_controller(protocol, *, endpoint, api_key_env="DASHSCOPE_API_KEY", tokenizer_manifest,
                               tokenizer_acceptance=None, memory_acceptance=None, provider="deepseek", client=None,
                               memory_mode="none", memory_profile_path=None, store_path=None,
                               store_manifest=None, build_manifest=None):
    """Build a runtime controller; legacy report arguments are ignored."""
    from .llm import LLMTransport, OfficialInputTokenCounter
    from .llm_memory import MemoryLLMController
    from .memory import load_memory_profile
    from .memory_store import FrozenPublicCaseStore
    settings = make_llm_settings(protocol, provider=provider, endpoint=endpoint, api_key_env=api_key_env)
    profile = load_memory_profile(memory_profile_path)
    store = None
    if memory_mode in ("global", "both"):
        if store_path is None or store_manifest is None:
            raise ValueError("global memory requires an explicit frozen public store and manifest")
        store = FrozenPublicCaseStore.open(store_path, store_manifest)
    try:
        controller = MemoryLLMController(LLMTransport(settings, client=client), make_public_prompt_config(protocol),
            settings, OfficialInputTokenCounter(tokenizer_manifest),
            memory_mode=memory_mode, memory_profile=profile, store=store)
    except BaseException:
        if store is not None:
            store.close()
        raise
    # Private source provenance stays with the runner, outside controller inputs.
    _MEMORY_SOURCE_MANIFESTS[controller] = build_manifest
    return controller


def _validate_memory_run(protocol, controller, purpose, scenario_options):
    from .llm import LLMConfigurationError
    from .memory import public_task_hash
    from .memory_store import FrozenPublicCaseStore, verify_source_manifest
    store = controller.store
    if controller.memory_mode in ("global", "both"):
        if type(store) is not FrozenPublicCaseStore:
            raise LLMConfigurationError("invalid_case_store", "Episodes require the verified read-only public case store")
        store.verify_integrity()
        options = dict(scenario_options or {})
        days = options.get("execution_days", protocol.definition["engine"]["execution_days"])
        if store.public_task_sha256 != public_task_hash(controller.prompt_config, days):
            raise LLMConfigurationError("case_task_mismatch", "Source cases use a different public task or horizon")
        if purpose == "smoke":
            if store.purpose != "fixture":
                raise LLMConfigurationError("invalid_store_purpose", "Offline smoke uses a clearly marked fixture case store")
        else:
            if store.purpose not in ("development", "evaluation_ready"):
                raise LLMConfigurationError("fixture_store_forbidden", "Real prompt development cannot use a fixture source library")
            path = _MEMORY_SOURCE_MANIFESTS.get(controller)
            if path is None:
                raise LLMConfigurationError("source_provenance_missing", "Real memory episodes require a separate private source manifest")
            compatibility = memory_source_compatibility(protocol, options.get("calibration_artifact"),
                execution_days=days, data_path=options.get("calibration_data_path"))
            source = verify_source_manifest(path, compatibility, purpose=store.purpose)
            if source.get("database_sha256") != store.store_sha256:
                raise LLMConfigurationError("source_store_mismatch", "Private build evidence and public database do not match")
