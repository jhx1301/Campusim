"""Versioned E0 fitting and independent evaluation of reconstructed diagnoses.

The data are aggregate reconstructions. These fits are an empirical anchor for
the synthetic task, not evidence of real-world predictive or causal validity.
"""

from __future__ import annotations

from collections.abc import Mapping
import csv
from dataclasses import dataclass
from datetime import date, datetime, timezone
import hashlib
from importlib.metadata import version
import json
from math import isclose, isfinite, sqrt
from pathlib import Path
import platform
from types import MappingProxyType

import numpy as np

from .logging import resolved_snapshot
from .protocol import ControlProtocol
from .scenarios import (
    base_model_configuration, build_population_registry, configuration_sha256,
    population_configuration, resolve_campus_parameters,
)


ROOT = Path(__file__).resolve().parents[2]
DEFAULT_DATA_PATH = Path("data/notre_dame_2020_early.csv")
ARTIFACT_SCHEMA = "cemas-e0-artifact-v1"
REPORT_SCHEMA = "cemas-e0-report-v1"
# The audited pre-portability implementation (CRLF/LF) has identical fit and
# simulation semantics. Every other source and compatibility field stays exact.
# Re-audit/remove this bridge when fitting or simulation semantics change.
_LEGACY_CALIBRATION_SOURCES = frozenset({
    "c2656931b635b998da2d390b050b49b51dbf6349664d9a05c4339797dfb34fc9",
    "cb0e8347837b729149a44f5009ce9f22141ea38a71856a186afc279eaf6d91b4",
})


def _freeze(value):
    if isinstance(value, Mapping):
        return MappingProxyType({key: _freeze(item) for key, item in value.items()})
    if isinstance(value, (list, tuple)):
        return tuple(_freeze(item) for item in value)
    return value


def _digest(payload) -> str:
    encoded = json.dumps(resolved_snapshot(payload), sort_keys=True,
                         separators=(",", ":"), allow_nan=False).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


@dataclass(frozen=True, slots=True)
class CalibrationData:
    source_path: str
    source_sha256: str
    dates: tuple[str, ...]
    diagnoses: tuple[float, ...]
    tests: tuple[float, ...]

    def snapshot(self) -> dict:
        return resolved_snapshot(self)


@dataclass(frozen=True, slots=True)
class CalibrationArtifact:
    payload: Mapping
    sha256: str

    @property
    def beta(self) -> float:
        return self.payload["beta"]


@dataclass(frozen=True, slots=True)
class FitReport:
    payload: Mapping
    sha256: str


class CalibrationFitError(RuntimeError):
    """Preserve completed and failed trials when fitting cannot produce an artifact."""

    def __init__(self, error, trials):
        super().__init__(f"E0 fitting failed: {type(error).__name__}: {error}")
        self.trial_records = trials


def _trial_records(study):
    return [{"number": trial.number, "state": trial.state.name,
             "beta": trial.params.get("beta"), "loss": trial.value,
             "per_world_loss": trial.user_attrs.get("per_world_loss"),
             "duration_seconds": trial.duration.total_seconds() if trial.duration else None}
            for trial in study.trials]


def read_calibration_data(path: str | Path | None = None) -> CalibrationData:
    """Resolve inputs from the project root; persist only a portable source label."""
    path = DEFAULT_DATA_PATH if path is None else Path(path)
    path = (ROOT / path).resolve()
    raw = path.read_bytes()
    rows = list(csv.DictReader(raw.decode("utf-8-sig").splitlines()))
    if not rows:
        raise ValueError("calibration data are empty")
    dates, diagnoses, tests = [], [], []
    previous = None
    for row in rows:
        try:
            day = date.fromisoformat(row["date"])
            diagnosis, test = float(row["new_diagnoses"]), float(row["new_tests"])
        except (KeyError, TypeError, ValueError) as exc:
            raise ValueError("calibration data require date/new_diagnoses/new_tests") from exc
        if previous is not None and (day - previous).days != 1:
            raise ValueError("calibration data dates must be unique, ordered and contiguous")
        if not all(isfinite(value) and value >= 0 for value in (diagnosis, test)):
            raise ValueError("calibration counts must be finite and nonnegative")
        if diagnosis != int(diagnosis):
            raise ValueError("observed diagnoses must be integer counts")
        dates.append(day.isoformat())
        diagnoses.append(diagnosis)
        tests.append(test)
        previous = day
    # External files have no project-relative location; retain their name for
    # provenance and require an explicit data_path when loading custom inputs.
    source = path.relative_to(ROOT).as_posix() if path.is_relative_to(ROOT) else path.name
    return CalibrationData(source, hashlib.sha256(raw).hexdigest(),
                           tuple(dates), tuple(diagnoses), tuple(tests))


def _window(protocol, window):
    spec = protocol.definition["calibration"]
    if window == "primary":
        return tuple(spec["primary_window"])
    if window == "exploratory":
        return tuple(spec["exploratory_fit_window"])
    raise ValueError("window must be primary or exploratory")


def _indices(data: CalibrationData, start: str, end: str) -> tuple[int, int]:
    try:
        first, last = data.dates.index(start), data.dates.index(end)
    except ValueError as exc:
        raise ValueError("data do not cover the requested calibration window") from exc
    if last < first:
        raise ValueError("calibration window is reversed")
    return first, last + 1


def _engine_sources() -> dict:
    files = list((ROOT / "covasim").glob("*.py"))
    files.extend((Path(__file__), Path(__file__).with_name("scenarios.py")))
    return {str(path.relative_to(ROOT)).replace("\\", "/"):
            hashlib.sha256(path.read_bytes()).hexdigest() for path in sorted(files)}


def _compatibility(protocol: ControlProtocol) -> dict:
    population = resolved_snapshot(population_configuration(protocol))
    model = resolved_snapshot(base_model_configuration(protocol))
    return {
        "population_config": population,
        "population_config_sha256": configuration_sha256(population),
        "base_model_config": model,
        "base_model_config_sha256": configuration_sha256(model),
        "engine_sources": _engine_sources(),
        "runtime_versions": {"python": platform.python_version(),
                             **{name: version(name) for name in ("numpy", "sciris", "numba")}},
    }


def make_calibration_sim(protocol: ControlProtocol, beta: float, world_seed: int,
                         window="primary", *, data: CalibrationData | str | Path,
                         through_holdout=False):
    """Return a once-initialized E0 world, without the control executor."""
    if not isinstance(data, CalibrationData):
        data = read_calibration_data(data)
    start, end = _window(protocol, window)
    if through_holdout:
        if window != "exploratory":
            raise ValueError("only the exploratory fit has a continuous holdout")
        end = protocol.definition["calibration"]["exploratory_holdout"][1]
    first, stop = _indices(data, start, end)
    days = stop - first
    pars = resolve_campus_parameters(protocol, world_seed, beta=beta, execution_days=days)
    pars["start_day"] = start
    import covasim as cv
    intervention = cv.test_num(daily_tests=list(data.tests[first:stop]),
                               **dict(protocol.definition["calibration"]["testing"]))
    sim = cv.Sim(pars=pars, interventions=[intervention])
    sim.initialize()
    return sim


def _run_calibration(protocol, beta, seed, window, data, *, through_holdout=False):
    sim = make_calibration_sim(protocol, beta, seed, window, data=data,
                               through_holdout=through_holdout)
    registry = build_population_registry(sim.people, activity_config=protocol.definition["activity"])
    record = {
        "world_seed": seed,
        "resolved_parameters": resolved_snapshot({key: value for key, value in sim.pars.items()
                                                   if key not in ("interventions", "analyzers")}),
        "interventions": [{"type": type(item).__name__,
                           "constructor": resolved_snapshot(item.input_args),
                           "daily_tests": resolved_snapshot(item.daily_tests),
                           "quar_policy": item.quar_policy} for item in sim["interventions"]],
        "population": resolved_snapshot(registry.public_population),
        "roles": {key: len(indices) for key, indices in sim.people.campus_registry_metadata.items()},
    }
    days = sim.npts
    for _ in range(days):
        sim.step()
    sim.finalize(verbose=0)
    record["diagnoses"] = tuple(float(value) for value in sim.results["new_diagnoses"].values)
    if len(record["diagnoses"]) != days:
        raise RuntimeError("E0 diagnoses did not cover every actual day")
    return record


def normalized_diagnosis_mse(curves, observed) -> float:
    """Average world MSEs, not MSE of the average simulated curve."""
    curves, observed = np.asarray(curves, dtype=float), np.asarray(observed, dtype=float)
    if (curves.ndim != 2 or observed.ndim != 1 or curves.shape[1] != len(observed)
            or not curves.shape[0] or not len(observed)
            or not np.isfinite(curves).all() or not np.isfinite(observed).all()
            or (curves < 0).any() or (observed < 0).any()):
        raise ValueError("diagnosis curves must be finite, nonnegative and aligned")
    return float(np.mean(np.mean((curves - observed) ** 2, axis=1)) / (observed.mean() + 1) ** 2)


def _fit_seeds(protocol, window):
    return (tuple(protocol.definition["seeds"]["calibration"]) if window == "primary"
            else tuple(protocol.definition["calibration"]["exploratory_train_seeds"]))


def _evaluation_seeds(protocol, window):
    if window == "primary":
        interval = protocol.definition["seeds"]["fit_evaluation"]
        return tuple(range(interval["start_inclusive"], interval["end_inclusive"] + 1))
    interval = protocol.definition["calibration"]["exploratory_holdout_seed_range_inclusive"]
    return tuple(range(interval["start"], interval["end"] + 1))


def fit_beta(protocol: ControlProtocol, reconstructed_data: str | Path | None = None, *, window="primary") -> CalibrationArtifact:
    """Fit the prescribed scalar using fixed worlds and an independent TPE RNG."""
    try:
        import optuna
    except ImportError as exc:
        raise RuntimeError("E0 fitting requires the approved Optuna dependency") from exc
    data = read_calibration_data(reconstructed_data)
    start, end = _window(protocol, window)
    first, stop = _indices(data, start, end)
    # The exploratory artifact must also contain the continuous holdout inputs.
    if window == "exploratory":
        _indices(data, start, protocol.definition["calibration"]["exploratory_holdout"][1])
    observed = data.diagnoses[first:stop]
    spec = protocol.definition["calibration"]
    seeds = _fit_seeds(protocol, window)
    best_runs, best_loss = None, float("inf")

    def objective(trial):
        nonlocal best_runs, best_loss
        beta = trial.suggest_float("beta", *spec["beta_range"])
        runs = [_run_calibration(protocol, beta, seed, window, data) for seed in seeds]
        loss = normalized_diagnosis_mse([run["diagnoses"] for run in runs], observed)
        trial.set_user_attr("per_world_loss", [normalized_diagnosis_mse([run["diagnoses"]], observed)
                                               for run in runs])
        if loss < best_loss:
            best_loss, best_runs = loss, runs
        return loss

    study = optuna.create_study(direction="minimize",
        sampler=optuna.samplers.TPESampler(seed=spec["optimizer_seed"]),
        pruner=optuna.pruners.NopPruner())
    try:
        study.optimize(objective, n_trials=spec["trials"], n_jobs=1)
    except (Exception, KeyboardInterrupt) as error:
        raise CalibrationFitError(error, _trial_records(study)) from error
    trials = _trial_records(study)
    payload = {
        "schema_version": ARTIFACT_SCHEMA, "method_version": spec["method_version"],
        "created_at": datetime.now(timezone.utc).isoformat(),
        "window": window, "fit_window": (start, end), "execution_days": stop - first,
        "n_days": stop - first - 1, "beta": study.best_params["beta"],
        "beta_range": tuple(spec["beta_range"]), "loss_definition": spec["loss"],
        "best_loss": study.best_value, "best_trial": study.best_trial.number,
        "optimizer_seed": spec["optimizer_seed"], "fit_seeds": seeds,
        "calibration_spec": resolved_snapshot(spec), "protocol_sha256": protocol.source_sha256,
        "protocol_path": str(protocol.source_path),
        "data": data.snapshot(), "trials": trials, "best_runs": best_runs,
        "compatibility": _compatibility(protocol),
        "versions": {name: version(name) for name in ("numpy", "sciris", "numba", "optuna")},
        "beta_at_boundary": min(abs(study.best_params["beta"] - value)
                                for value in spec["beta_range"]) < 1e-5,
        "evidence_scope": "fit_of_reconstructed_aggregate_diagnoses_not_real_world_validation",
    }
    return CalibrationArtifact(_freeze(payload), _digest(payload))


def _write_envelope(path: Path, payload, digest):
    path.parent.mkdir(parents=True, exist_ok=True)
    # Exclusive creation protects previous successes and failed attempts.
    with path.open("x", encoding="utf-8") as stream:
        json.dump({"sha256": digest, "payload": resolved_snapshot(payload)}, stream,
                  ensure_ascii=False, sort_keys=True, indent=2, allow_nan=False)
        stream.write("\n")


def save_calibration_artifact(artifact: CalibrationArtifact, output_dir: str | Path) -> Path:
    path = Path(output_dir) / "artifact.json"
    _write_envelope(path, artifact.payload, artifact.sha256)
    with path.with_name("trials.jsonl").open("x", encoding="utf-8") as stream:
        for trial in artifact.payload["trials"]:
            stream.write(json.dumps(resolved_snapshot(trial), allow_nan=False) + "\n")
    return path


def _read_envelope(path: Path, schema: str):
    try:
        envelope = json.loads(path.read_text(encoding="utf-8"),
                              parse_constant=lambda value: (_ for _ in ()).throw(ValueError(value)))
        payload, digest = envelope["payload"], envelope["sha256"]
        if payload["schema_version"] != schema or _digest(payload) != digest:
            raise ValueError("schema or content hash mismatch")
    except (OSError, KeyError, TypeError, ValueError) as exc:
        raise ValueError(f"invalid {schema} artifact: {path}") from exc
    return payload, digest


def _compatible(recorded, current):
    recorded = resolved_snapshot(recorded)
    if not isinstance(recorded, dict) or not isinstance(recorded.get("engine_sources"), dict):
        return False
    source = "cemas/control/calibration.py"
    source_hash = recorded["engine_sources"].get(source)
    if isinstance(source_hash, str) and source_hash in _LEGACY_CALIBRATION_SOURCES:
        recorded["engine_sources"][source] = current["engine_sources"][source]
    return recorded == current


def _validate_fit_payload(payload, protocol, *, data_path=None):
    spec = protocol.definition["calibration"]
    if (payload["method_version"] != spec["method_version"]
            or not _compatible(payload["compatibility"], _compatibility(protocol))
            or payload["calibration_spec"] != resolved_snapshot(spec)):
        raise ValueError("calibration population, base model, method or fit configuration is incompatible")
    beta = payload["beta"]
    if type(beta) not in (int, float) or not isfinite(beta) or not spec["beta_range"][0] <= beta <= spec["beta_range"][1]:
        raise ValueError("invalid calibrated beta")
    window = payload["window"]
    if tuple(payload["fit_window"]) != _window(protocol, window):
        raise ValueError("calibration window mismatch")
    seeds = _fit_seeds(protocol, window)
    if tuple(payload["fit_seeds"]) != seeds or payload["optimizer_seed"] != spec["optimizer_seed"]:
        raise ValueError("calibration seed purpose mismatch")
    try:
        data = read_calibration_data(data_path)
    except OSError as exc:
        raise ValueError(f"cannot read calibration data; set data_path/--data: {exc}") from exc
    snapshot = data.snapshot()
    if any(snapshot[key] != payload["data"][key]
           for key in ("source_sha256", "dates", "diagnoses", "tests")):
        raise ValueError("calibration data or its source hash have changed")
    first, stop = _indices(data, *payload["fit_window"])
    if payload["execution_days"] != stop - first or payload["n_days"] != stop - first - 1:
        raise ValueError("calibration actual execution days mismatch")
    trials = payload["trials"]
    if len(trials) != spec["trials"] or [trial["number"] for trial in trials] != list(range(spec["trials"])):
        raise ValueError("calibration trial record is incomplete")
    completed = [trial for trial in trials if trial["state"] == "COMPLETE"]
    if not completed:
        raise ValueError("calibration has no completed fit")
    best = min(completed, key=lambda trial: trial["loss"])
    if (best["beta"] != beta or best["number"] != payload["best_trial"]
            or best["loss"] != payload["best_loss"]):
        raise ValueError("calibrated beta does not match trial evidence")
    runs = payload["best_runs"]
    if tuple(run["world_seed"] for run in runs) != seeds:
        raise ValueError("fit world evidence is incomplete")
    loss = normalized_diagnosis_mse([run["diagnoses"] for run in runs], data.diagnoses[first:stop])
    if not isclose(loss, payload["best_loss"], rel_tol=1e-12, abs_tol=1e-12):
        raise ValueError("fit loss does not match recorded per-world diagnoses")
    return data


def load_calibration_artifact(path: str | Path, protocol: ControlProtocol, *,
                              require_evaluation=True, data_path: str | Path | None = None) -> CalibrationArtifact:
    """Verify evidence against current data, independently of historical paths."""
    path = Path(path).resolve()
    payload, digest = _read_envelope(path, ARTIFACT_SCHEMA)
    try:
        data = _validate_fit_payload(payload, protocol, data_path=data_path)
        if require_evaluation:
            if payload["window"] != "primary":
                raise ValueError("scientific control requires the primary E0 fit")
            report, _ = _read_envelope(path.with_name("fit_report.json"), REPORT_SCHEMA)
            _validate_report(report, payload, digest, protocol, data)
    except (KeyError, TypeError, IndexError, ValueError) as exc:
        raise ValueError(f"calibration evidence is incompatible or incomplete: {exc}") from exc
    return CalibrationArtifact(_freeze(payload), digest)


def evaluate_beta(artifact: CalibrationArtifact, evaluation_seeds=None, *, protocol=None,
                  data_path: str | Path | None = None) -> FitReport:
    """Evaluate fixed beta on disjoint worlds, continuing auxiliary holdout state."""
    payload = artifact.payload
    if _digest(payload) != artifact.sha256:
        raise ValueError("calibration artifact content hash mismatch")
    if protocol is None:
        from .protocol import load_protocol
        protocol = load_protocol(payload["protocol_path"])
    data = _validate_fit_payload(resolved_snapshot(payload), protocol, data_path=data_path)
    expected = _evaluation_seeds(protocol, payload["window"])
    seeds = expected if evaluation_seeds is None else tuple(evaluation_seeds)
    if seeds != expected:
        raise ValueError("evaluation must use the complete prescribed independent seed set")
    auxiliary = payload["window"] == "exploratory"
    runs = [_run_calibration(protocol, artifact.beta, seed, payload["window"], data,
                             through_holdout=auxiliary) for seed in seeds]
    fit_start = payload["fit_window"][0]
    evaluation_window = (tuple(protocol.definition["calibration"]["exploratory_holdout"])
                         if auxiliary else tuple(payload["fit_window"]))
    first, stop = _indices(data, *evaluation_window)
    offset = (date.fromisoformat(evaluation_window[0]) - date.fromisoformat(fit_start)).days
    count = stop - first
    observed = np.asarray(data.diagnoses[first:stop])
    curves = np.asarray([run["diagnoses"][offset:offset + count] for run in runs])
    quantiles = tuple(protocol.definition["calibration"]["fit_band_quantiles"])
    report = {
        "schema_version": REPORT_SCHEMA, "artifact_sha256": artifact.sha256,
        "method_version": payload["method_version"], "beta": artifact.beta,
        "window": payload["window"], "evaluation_window": evaluation_window,
        "evaluation_seeds": seeds, "observed": tuple(observed),
        "simulated": tuple(tuple(row) for row in curves),
        **_report_statistics(curves, observed, seeds, quantiles),
        "execution_start": fit_start, "continuous_from_fit_start": auxiliary,
        "population_by_world": [{"world_seed": run["world_seed"], "population": run["population"],
                                  "roles": run["roles"]} for run in runs],
        "evidence_scope": payload["evidence_scope"],
    }
    return FitReport(_freeze(report), _digest(report))


def _report_statistics(curves, observed, seeds, quantiles):
    curves, observed = np.asarray(curves, dtype=float), np.asarray(observed, dtype=float)
    loss = normalized_diagnosis_mse(curves, observed)
    if len(curves) != len(seeds):
        raise ValueError("each evaluation world must have one curve")
    errors = curves - observed
    per_world = [{"world_seed": seed, "mae": float(np.mean(abs(error))),
                  "rmse": sqrt(float(np.mean(error ** 2))),
                  "cumulative_diagnoses_error": float(error.sum())}
                 for seed, error in zip(seeds, errors)]
    return {"per_world": per_world, "mean_diagnoses": tuple(curves.mean(axis=0)),
            "band_quantiles": tuple(quantiles),
            "diagnoses_band": tuple(tuple(row) for row in np.quantile(curves, quantiles, axis=0)),
            "mean_mae": float(np.mean([row["mae"] for row in per_world])),
            "mean_rmse": float(np.mean([row["rmse"] for row in per_world])),
            "normalized_mse": loss}


def _validate_report(report, fit_payload, artifact_digest, protocol, data):
    if (report["artifact_sha256"] != artifact_digest or report["beta"] != fit_payload["beta"]
            or report["method_version"] != fit_payload["method_version"]
            or report["window"] != fit_payload["window"]):
        raise ValueError("independent report does not match the calibration artifact")
    if tuple(report["evaluation_seeds"]) != _evaluation_seeds(protocol, fit_payload["window"]):
        raise ValueError("independent evaluation worlds are incomplete or have wrong purpose")
    evaluation_window = (tuple(protocol.definition["calibration"]["exploratory_holdout"])
                         if fit_payload["window"] == "exploratory" else tuple(fit_payload["fit_window"]))
    if tuple(report["evaluation_window"]) != evaluation_window:
        raise ValueError("independent evaluation window mismatch")
    first, stop = _indices(data, *evaluation_window)
    observed = data.diagnoses[first:stop]
    curves = report["simulated"]
    if len(curves) != 20 or tuple(report["observed"]) != observed:
        raise ValueError("independent evaluation evidence is incomplete")
    statistics = _report_statistics(curves, observed, report["evaluation_seeds"],
                                     protocol.definition["calibration"]["fit_band_quantiles"])
    for name, value in statistics.items():
        if resolved_snapshot(value) != report[name]:
            raise ValueError(f"evaluation {name} does not match recorded diagnoses")
    if (report["execution_start"] != fit_payload["fit_window"][0]
            or report["continuous_from_fit_start"] is not (fit_payload["window"] == "exploratory")):
        raise ValueError("evaluation must preserve the declared fit-start state")


def save_fit_report(report: FitReport, output_dir: str | Path) -> Path:
    path = Path(output_dir) / "fit_report.json"
    _write_envelope(path, report.payload, report.sha256)
    return path
