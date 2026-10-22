"""Public serialization and runner-owned, separate public/private audit files."""

from collections.abc import Mapping
from dataclasses import asdict, dataclass, fields, is_dataclass
from datetime import date, datetime
import csv
import hashlib
import json
from math import isfinite
import os
from pathlib import Path

from .types import (
    ACTION_ORDER, ActionProposal, ActionVector, PrivateDailyMetrics, PrivateMetrics,
    PublicCost, PublicObservation, PublicResources, SCHEMA_VERSION,
)


CONTROLLER_TYPES = (
    "llm", "ppo", "ddqn", "threshold", "minimum", "maximum_feasible",
    "uniform_legal_independent_rng",
)


def resolved_snapshot(value):
    """Detach resolved configuration into JSON values without string fallbacks.

    Unlike ``asdict``, walking fields does not deepcopy immutable mapping proxies.
    Unknown runtime objects are rejected rather than silently losing parameters.
    """
    if value is None or type(value) in (str, bool, int):
        return value
    if type(value) is float:
        if not isfinite(value):
            raise ValueError("snapshot numbers must be finite")
        return value
    if isinstance(value, Mapping):
        result = {}
        for key, item in value.items():
            if type(key) not in (str, int):
                raise TypeError("snapshot mapping keys must be strings or integers")
            name = str(key)
            if name in result:
                raise ValueError("snapshot mapping keys collide after JSON conversion")
            result[name] = resolved_snapshot(item)
        return result
    if is_dataclass(value) and not isinstance(value, type):
        return {field.name: resolved_snapshot(getattr(value, field.name))
                for field in fields(value)}
    if isinstance(value, (tuple, list)):
        return [resolved_snapshot(item) for item in value]
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if isinstance(value, Path):
        return str(value)
    if type(value).__module__.split(".")[0] == "numpy":
        if hasattr(value, "tolist"):
            return resolved_snapshot(value.tolist())
        if hasattr(value, "item"):
            return resolved_snapshot(value.item())
    raise TypeError(f"unsupported snapshot type: {type(value).__module__}.{type(value).__qualname__}")


def snapshot_sha256(value) -> str:
    payload = json.dumps(resolved_snapshot(value), ensure_ascii=False, sort_keys=True,
                         separators=(",", ":"), allow_nan=False)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def public_observation_to_dict(observation: PublicObservation) -> dict:
    """Serialize the exact public type; private/general dictionaries are rejected."""
    if type(observation) is not PublicObservation:
        raise TypeError("only PublicObservation can be serialized as a public observation")
    return json.loads(json.dumps(asdict(observation), ensure_ascii=False, allow_nan=False))


def hash_observation(observation: PublicObservation) -> str:
    """Hash only the common public observation, excluding memory and audit data."""
    payload = json.dumps(public_observation_to_dict(observation), ensure_ascii=False,
                         sort_keys=True, separators=(",", ":"), allow_nan=False)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


@dataclass(frozen=True, slots=True)
class DecisionRecord:
    """Runner-owned record. Do not pass this object to controllers or memory."""

    observation_hash: str
    decision_day: int
    decision_time: datetime
    controller_type: str
    action_proposal: ActionProposal | None
    executed_action: ActionVector
    fallback_used: bool = False
    fallback_reason: str | None = None
    adjustment_reason: str | None = None
    reasoning: str | None = None
    retrieved_case_ids: tuple[int, ...] = ()
    elapsed_ms: float = 0.0
    llm_attempt_count: int = 0
    llm_succeeded: bool | None = None
    decision_source: str = "controller"

    def __post_init__(self) -> None:
        if (type(self.observation_hash) is not str or len(self.observation_hash) != 64
                or any(character not in "0123456789abcdef" for character in self.observation_hash)):
            raise ValueError("observation_hash must be a lowercase SHA-256 hex digest")
        if type(self.decision_day) is not int or self.decision_day < 0:
            raise ValueError("decision_day must be a nonnegative ordinary integer")
        if type(self.decision_time) is not datetime or self.decision_time.utcoffset() is None:
            raise ValueError("decision_time must be a timezone-aware datetime")
        if type(self.controller_type) is not str or self.controller_type not in CONTROLLER_TYPES:
            raise ValueError("unknown controller_type")
        if self.action_proposal is not None and type(self.action_proposal) is not ActionProposal:
            raise TypeError("action_proposal must be ActionProposal or None")
        if type(self.executed_action) is not ActionVector:
            raise TypeError("executed_action must be ActionVector")
        if type(self.fallback_used) is not bool:
            raise TypeError("fallback_used must be a boolean")
        for name in ("fallback_reason", "adjustment_reason", "reasoning"):
            value = getattr(self, name)
            if value is not None and (type(value) is not str or not value.strip()):
                raise ValueError(f"{name} must be nonempty text or None")
        if self.fallback_used != (self.fallback_reason is not None):
            raise ValueError("fallback_used and fallback_reason must agree")
        if (type(self.retrieved_case_ids) is not tuple
                or any(type(value) is not int or value <= 0 for value in self.retrieved_case_ids)):
            raise ValueError("retrieved_case_ids must be a tuple of positive case ids")
        if type(self.elapsed_ms) not in (int, float) or not 0 <= self.elapsed_ms < float("inf"):
            raise ValueError("elapsed_ms must be finite and nonnegative")
        object.__setattr__(self, "elapsed_ms", 0.0 if self.elapsed_ms == 0 else float(self.elapsed_ms))
        if type(self.llm_attempt_count) is not int or self.llm_attempt_count < 0:
            raise ValueError("llm_attempt_count must be a nonnegative ordinary integer")
        if self.llm_succeeded is not None and type(self.llm_succeeded) is not bool:
            raise TypeError("llm_succeeded must be boolean or None")
        if self.decision_source not in ("protocol_fixed", "controller"):
            raise ValueError("unknown decision_source")
        if self.decision_source == "protocol_fixed" and (
                self.decision_day != 0 or self.executed_action.values != (0, 0, 0, 0, 0)
                or self.fallback_used or self.adjustment_reason is not None
                or self.llm_attempt_count or self.llm_succeeded is not None):
            raise ValueError("invalid protocol-fixed decision record")

    def to_dict(self) -> dict:
        record = asdict(self)
        record["schema_version"] = SCHEMA_VERSION
        record["decision_time"] = self.decision_time.isoformat()
        return json.loads(json.dumps(record, ensure_ascii=False, allow_nan=False))


_COST_FIELDS = tuple(field.name for field in fields(PublicCost))
_RESOURCE_FIELDS = tuple(field.name for field in fields(PublicResources))
_ACTION_FIELDS = tuple(f"action_{name}" for name in ACTION_ORDER)
_REWARD_FIELDS = ("infections", "tests", "notifications", "union", "activity")


def _public_row(record) -> dict:
    row = {field.name: getattr(record, field.name) for field in fields(record)
           if field.name not in ("cost", "resources", "executed_action")}
    row.update(resolved_snapshot(record.cost))
    row.update(resolved_snapshot(record.resources))
    row.update(zip(_ACTION_FIELDS, record.executed_action.values))
    return row


class RunLogger:
    """One new run directory; manifest completion is committed after log flush.

    A failed or interrupted attempt is never overwritten. The manifest, rather
    than the mere existence of a summary, determines whether a run completed.
    """

    def __init__(self, output_dir: str | Path, manifest: Mapping):
        self.output_dir = Path(output_dir)
        self._manifest = resolved_snapshot(manifest)
        self._manifest["schema_version"] = SCHEMA_VERSION
        self._manifest["status"] = "running"
        self._handles = {}
        self._writers = {}
        self._public_count = self._private_count = self._window_count = 0
        self._closed = False
        self.output_dir.mkdir(parents=True, exist_ok=False)
        try:
            self._write_json("manifest.json", self._manifest)
            public_fields = ("delivered_diagnoses",) + _COST_FIELDS + _RESOURCE_FIELDS + _ACTION_FIELDS
            self._csv("public_daily.csv", ("day",) + public_fields + (
                "known_isolated", "known_quarantined", "known_union"))
            self._csv("private_daily.csv", tuple(field.name for field in fields(PrivateDailyMetrics)))
            self._csv("public_weekly.csv", ("start_day", "end_day") + public_fields + (
                "growth", "growth_valid", "diagnosis_test_proxy", "proxy_valid"))
            private_fields = tuple(field.name for field in fields(PrivateMetrics))
            self._csv("private_weekly_rewards.csv", private_fields + _COST_FIELDS + (
                "window_days", "formula_version", "reward", "positive_cost")
                + tuple(f"normalized_{name}" for name in _REWARD_FIELDS)
                + tuple(f"weighted_{name}" for name in _REWARD_FIELDS))
            self._handles["decisions.jsonl"] = (self.output_dir / "decisions.jsonl").open(
                "x", encoding="utf-8", newline="\n")
        except BaseException:
            self.close()
            raise

    def _csv(self, filename: str, columns: tuple[str, ...]) -> None:
        handle = (self.output_dir / filename).open("x", encoding="utf-8", newline="")
        self._handles[filename] = handle
        writer = csv.DictWriter(handle, fieldnames=columns)
        writer.writeheader()
        self._writers[filename] = writer

    def _write_json(self, filename: str, payload) -> None:
        text = json.dumps(resolved_snapshot(payload), ensure_ascii=False, indent=2, allow_nan=False)
        temporary = self.output_dir / (filename + ".tmp")
        with temporary.open("w", encoding="utf-8", newline="\n") as handle:
            handle.write(text + "\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, self.output_dir / filename)

    def write_decision(self, decision: DecisionRecord, *, observation=None, resolution=None) -> None:
        if self._closed:
            raise RuntimeError("run logger is closed")
        payload = decision.to_dict()
        if observation is not None:
            payload["observation"] = public_observation_to_dict(observation)
        if resolution is not None:
            payload["resolution"] = resolved_snapshot(resolution)
        self._handles["decisions.jsonl"].write(
            json.dumps(payload, ensure_ascii=False, allow_nan=False) + "\n")

    def write_llm_calls(self, audits, *, metadata=None) -> None:
        """Durably deliver actual calls before advancing the environment."""
        from .llm import LLMCallAudit

        if self._closed:
            raise RuntimeError("run logger is closed")
        if type(audits) is not tuple or any(type(audit) is not LLMCallAudit for audit in audits):
            raise TypeError("call audits must be an immutable tuple of LLMCallAudit")
        if audits and "llm_calls.jsonl" not in self._handles:
            self._handles["llm_calls.jsonl"] = (self.output_dir / "llm_calls.jsonl").open(
                "x", encoding="utf-8", newline="\n")
        for audit in audits:
            self._handles["llm_calls.jsonl"].write(
                json.dumps(resolved_snapshot(audit), ensure_ascii=False, allow_nan=False) + "\n")
        if metadata is not None:
            self._manifest["llm"] = resolved_snapshot(metadata)
            self._write_json("manifest.json", self._manifest)
        if audits:
            self.flush()

    def _write_sidecar(self, filename, records):
        if self._closed:
            raise RuntimeError("run logger is closed")
        if not records:
            return
        if filename not in self._handles:
            self._handles[filename] = (self.output_dir / filename).open("x", encoding="utf-8", newline="\n")
        for record in records:
            self._handles[filename].write(json.dumps(resolved_snapshot(record), ensure_ascii=False, allow_nan=False) + "\n")
        self.flush()

    def write_decision_evidence(self, evidence) -> None:
        """Durable public context/response evidence, before the world advances."""
        if type(evidence) is not tuple or any(not isinstance(item, Mapping) for item in evidence):
            raise TypeError("decision evidence must be a tuple of public mappings")
        self._write_sidecar("decision_evidence.jsonl", evidence)

    def write_evidence_resolution(self, evidence, resolution) -> None:
        records = tuple({"event": "resolved", "decision_day": item["decision_day"],
                         "observation_hash": item["observation_hash"], "context_hash": item["context_hash"],
                         "executed_action": resolved_snapshot(resolution.executed_action),
                         "adjustment_reason": resolution.adjustment_reason,
                         "fallback_reason": resolution.fallback_reason} for item in evidence)
        self._write_sidecar("decision_evidence.jsonl", records)

    def write_memory_revisions(self, revisions) -> None:
        from .memory_types import LocalCaseRevision
        if type(revisions) is not tuple or any(type(item) is not LocalCaseRevision for item in revisions):
            raise TypeError("memory revisions must be exact public LocalCaseRevision objects")
        self._write_sidecar("memory_revisions.jsonl", revisions)

    def write_snapshot(self, snapshot) -> None:
        if self._closed:
            raise RuntimeError("run logger is closed")
        if (len(snapshot.public_daily) < self._public_count
                or len(snapshot.private_daily) < self._private_count
                or len(snapshot.windows) < self._window_count):
            raise ValueError("an audit snapshot cannot go backwards")
        for record in snapshot.public_daily[self._public_count:]:
            self._writers["public_daily.csv"].writerow(_public_row(record))
            self._public_count += 1
        for record in snapshot.private_daily[self._private_count:]:
            self._writers["private_daily.csv"].writerow(resolved_snapshot(record))
            self._private_count += 1
        for window in snapshot.windows[self._window_count:]:
            self._writers["public_weekly.csv"].writerow(_public_row(window.feedback.week))
            row = resolved_snapshot(window.private_metrics)
            row.update(resolved_snapshot(window.feedback.week.cost))
            row.update(window_days=window.end_day - window.start_day + 1,
                       formula_version=snapshot.manifest["reward_configuration"]["formula_version"],
                       reward=window.reward, positive_cost=-window.reward)
            row.update(zip((f"normalized_{name}" for name in _REWARD_FIELDS),
                           window.reward_breakdown.normalized))
            row.update(zip((f"weighted_{name}" for name in _REWARD_FIELDS),
                           window.reward_breakdown.weighted))
            self._writers["private_weekly_rewards.csv"].writerow(row)
            self._window_count += 1
        self._manifest.update(resolved_snapshot(snapshot.manifest))
        self._manifest.update(status="running", environment_status=snapshot.status,
                              elapsed_days=snapshot.elapsed_days)
        self._write_json("manifest.json", self._manifest)
        self.flush()

    def flush(self) -> None:
        for handle in self._handles.values():
            if not handle.closed:
                handle.flush()
                os.fsync(handle.fileno())

    def complete(self, summary: Mapping) -> None:
        if self._closed:
            raise RuntimeError("run logger is closed")
        if self._manifest.get("environment_status") != "completed":
            raise RuntimeError("only a completed environment can complete a run")
        self.flush()
        self.close()
        self._write_json("summary.json", dict(summary, status="completed"))
        self._manifest["status"] = "completed"
        self._write_json("manifest.json", self._manifest)

    def fail(self, error: BaseException, snapshot=None, *, safe_error=None, details=None) -> None:
        failure = {"error_type": type(error).__name__, "error": str(error) if safe_error is None else safe_error}
        if details is not None:
            failure["details"] = resolved_snapshot(details)
        log_errors = []
        if snapshot is not None and not self._closed:
            try:
                self.write_snapshot(snapshot)
            except Exception as log_error:
                log_errors.append(f"audit snapshot: {type(log_error).__name__ if safe_error is not None else log_error}")
        try:
            self.flush()
        except Exception as log_error:
            log_errors.append(f"flush: {type(log_error).__name__ if safe_error is not None else log_error}")
        try:
            self.close()
        except Exception as log_error:
            log_errors.append(f"close: {type(log_error).__name__ if safe_error is not None else log_error}")
        failure["logging_errors"] = log_errors
        self._manifest["status"] = "failed"
        write_errors = []
        # Each file is attempted even if a different file or a stream failed.
        for filename, payload in (
            ("failure.json", failure),
            ("summary.json", {"status": "failed", "elapsed_days":
                              self._manifest.get("elapsed_days", 0), **failure}),
            ("manifest.json", self._manifest),
        ):
            try:
                self._write_json(filename, payload)
            except Exception as log_error:
                write_errors.append(log_error)
        if write_errors:
            raise write_errors[0]

    def close(self) -> None:
        first_error = None
        for handle in self._handles.values():
            try:
                handle.close()
            except Exception as error:
                first_error = first_error or error
        self._closed = True
        if first_error is not None:
            raise first_error
