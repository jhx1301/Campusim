"""Export and verify the sole UW E0 parameter anchor used by control runs.

An anchor is derived from the frozen main case, never a sensitivity winner.
Independent simulation seeds remain an in-sample consistency check, not a
historical forecast validation. Export does not rerun any simulations.
"""

from dataclasses import dataclass
import hashlib
from importlib.metadata import version
import json
from math import isfinite
from pathlib import Path
import sys
from types import MappingProxyType
from typing import Mapping

from .data import ROOT, load_e0_config, load_e0_data


ARTIFACT_SCHEMA = "cemas-uw-control-anchor-v1"
ARTIFACT_FILENAME = "control_anchor.json"


def _read(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def _file_hash(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def _digest(payload):
    return hashlib.sha256(json.dumps(payload, sort_keys=True, separators=(",", ":"),
                                     allow_nan=False).encode("utf-8")).hexdigest()


def _freeze(value):
    if isinstance(value, dict):
        return MappingProxyType({k: _freeze(v) for k, v in value.items()})
    if isinstance(value, list):
        return tuple(_freeze(v) for v in value)
    return value


@dataclass(frozen=True, slots=True)
class CalibrationArtifact:
    payload: Mapping
    sha256: str

    @property
    def beta(self):
        return self.payload["beta"]


def _compatibility(protocol):
    from ..control.scenarios import base_model_configuration

    files = [*sorted((ROOT / "covasim").glob("*.py")),
             *sorted((ROOT / "cemas/e0").glob("*.py")),
             ROOT / "cemas/control/scenarios.py", ROOT / "cemas/control/protocol.py"]
    return {"base_model": json.loads(json.dumps(base_model_configuration(protocol))),
            "start_day": protocol.definition["engine"]["start_day"],
            "runtime": {"python": sys.version, "packages": {
                name: version(name) for name in ("numpy", "scipy", "pandas", "numba", "sciris")}},
            "source_sha256": {p.relative_to(ROOT).as_posix(): _file_hash(p) for p in files}}


def _config(protocol):
    return load_e0_config(ROOT / protocol.definition["calibration"]["config"])


def _config_spec(config):
    # Runtime path labels are not scientific settings and may move with a checkout.
    excluded = {"config_path", "config_sha256", "base_protocol_path", "window_days", "seed_count",
                "data_path", "provenance_path"}
    return {k: v for k, v in config.items() if k not in excluded}


def export_control_anchor(study_dir, protocol):
    """Reconstruct selection/evaluation evidence, then write an immutable anchor."""
    from .study import _profiles, _evaluation, _world_losses, _total

    root = Path(study_dir).resolve()
    target = root / ARTIFACT_FILENAME
    if target.exists():
        raise FileExistsError(target)
    manifest, summary = _read(root / "manifest.json"), _read(root / "summary.json")
    config = _config(protocol)
    frozen = manifest["config"]
    if (manifest["status"] != "complete" or summary["status"] != "complete"
            or manifest["schema_version"] != "cemas-uw-e0-study-v1"
            or _config_spec(frozen) != _config_spec(config)):
        raise ValueError("A complete study using the current UW E0 configuration is required")
    data = load_e0_data(config)
    if manifest["data_sha256"] != data["sha256"] or manifest["config_sha256"] != config["config_sha256"]:
        raise ValueError("UW calibration data/config hash mismatch")
    compatibility = _compatibility(protocol)
    if compatibility["runtime"] != {k: manifest["environment"][k] for k in ("python", "packages")}:
        raise ValueError("Runtime differs from the recorded UW study")
    # Existing E0 runs record these engine and study sources. Keep their evidence
    # unchanged; the exported anchor additionally fingerprints shared control code.
    for name, digest in manifest["source_sha256"].items():
        if _file_hash(ROOT / name) != digest:
            raise ValueError(f"Study source changed since calibration: {name}")
    hashes = {}
    streams = {}
    for stage in ("scan", "fit", "evaluation"):
        name = f"worlds_{stage}.jsonl"
        hashes[name] = _file_hash(root / name)
        if hashes[name] != manifest["artifacts"][name]:
            raise ValueError(f"Study evidence hash mismatch: {name}")
        records = [json.loads(line) for line in (root / name).read_text(encoding="utf-8").splitlines()]
        records = [r for r in records if r["case"] == "main"]
        records.sort(key=lambda r: (r["beta"], r["seed"]))
        for record in records:
            if record["losses"] != _world_losses(record["world"], _total(data["groups"], "positive"), config["alignments"]):
                raise ValueError(f"Recorded {stage} losses differ from raw world curves")
        betas = {r["beta"] for r in records}
        for beta in betas:
            seeds = [r["seed"] for r in records if r["beta"] == beta]
            if len(seeds) != len(set(seeds)) or set(seeds) != set(config[f"{stage}_seeds"]):
                raise ValueError(f"Incomplete or duplicate main {stage} worlds")
        if not records:
            raise ValueError(f"Missing main {stage} evidence")
        streams[stage] = records
    primary = {"alignment": config["primary_alignment"], "metric": config["primary_metric"]}
    if summary["primary"] != primary or manifest["primary"] != primary:
        raise ValueError("Study primary selection differs from the UW protocol")
    profiles = {}
    for stage in ("scan", "fit"):
        profiles[stage] = next(p for p in _profiles(streams[stage], config["alignments"])
                               if p["alignment"] == primary["alignment"] and p["metric"] == primary["metric"])
    evaluation = _evaluation(streams["evaluation"], profiles["fit"], profiles["scan"], data)
    cases = [c for c in summary["cases"] if c["name"] == "main"]
    if len(cases) != 1:
        raise ValueError("Exactly one main case is required")
    recorded = [e for e in cases[0]["evaluations"] if e.get("is_primary")]
    if (len(recorded) != 1 or {k: v for k, v in recorded[0].items() if k != "is_primary"}
            != json.loads(json.dumps(evaluation))):
        raise ValueError("Summary does not match raw main evaluation evidence")
    if not evaluation["fit_identifiable"]:
        raise ValueError("The main UW beta profile is flagged as unidentifiable")
    for record in streams["evaluation"]:
        world = record["world"]
        if (world["population"] != protocol.population
                or world["roles"] != {**config["target_roles"], **config["target_groups"]}
                or world["resolved_parameters"]["pop_infected"] != protocol.initial_infections):
            raise ValueError("Evaluation world population differs from control")
    for name in ("manifest.json", "summary.json", "config.json"):
        hashes[name] = _file_hash(root / name)
    payload = {"schema_version": ARTIFACT_SCHEMA, "method_version": config["method_version"],
               "beta": evaluation["beta"], "selection": {"case": "main", **primary},
               "evidence_scope": config["evidence_scope"], "evaluation_worlds": evaluation["worlds"],
               "evaluation_loss": evaluation["evaluation_loss"],
               "config_sha256": config["config_sha256"], "data_sha256": data["sha256"],
               "compatibility": compatibility, "study_sha256": hashes}
    envelope = {"payload": payload, "sha256": _digest(payload)}
    with target.open("x", encoding="utf-8", newline="\n") as f:
        json.dump(envelope, f, ensure_ascii=False, allow_nan=False, indent=2)
        f.write("\n")
    return target


def load_calibration_artifact(path, protocol, *, data_path=None):
    """Verify one UW anchor and its study files before any scientific reset."""
    path = Path(path).resolve()
    try:
        envelope = _read(path)
        payload = envelope["payload"]
        if payload["schema_version"] != ARTIFACT_SCHEMA or _digest(payload) != envelope["sha256"]:
            raise ValueError("Unsupported or corrupted UW anchor")
        config = _config(protocol)
        if data_path is not None:
            config = dict(config, data_path=str((ROOT / Path(data_path)).resolve()))
        data = load_e0_data(config)
        selection = {"case": "main", "alignment": config["primary_alignment"], "metric": config["primary_metric"]}
        beta = payload["beta"]
        if (payload["selection"] != selection or payload["method_version"] != config["method_version"]
                or payload["config_sha256"] != config["config_sha256"]
                or payload["data_sha256"] != data["sha256"]
                or payload["evaluation_worlds"] != len(config["evaluation_seeds"])
                or payload["compatibility"] != _compatibility(protocol)
                or type(beta) not in (int, float) or not isfinite(beta)
                or not config["beta_range"][0] <= beta <= config["beta_range"][1]):
            raise ValueError("UW anchor is incompatible with the current model, data or selection")
        required = {"manifest.json", "summary.json", "config.json",
                    "worlds_scan.jsonl", "worlds_fit.jsonl", "worlds_evaluation.jsonl"}
        if set(payload["study_sha256"]) != required:
            raise ValueError("UW anchor has incomplete study evidence")
        for name, digest in payload["study_sha256"].items():
            if _file_hash(path.parent / name) != digest:
                raise ValueError(f"UW study evidence changed: {name}")
        summary = _read(path.parent / "summary.json")
        main = next(c for c in summary["cases"] if c["name"] == "main")
        selected = next(e for e in main["evaluations"] if e.get("is_primary"))
        if (beta != selected["beta"] or payload["evaluation_loss"] != selected["evaluation_loss"]
                or not selected["fit_identifiable"]):
            raise ValueError("UW anchor does not match the selected main study result")
        return CalibrationArtifact(_freeze(payload), envelope["sha256"])
    except (KeyError, TypeError, ValueError, OSError, StopIteration) as exc:
        raise ValueError(f"UW calibration evidence is incompatible or incomplete: {exc}") from exc
