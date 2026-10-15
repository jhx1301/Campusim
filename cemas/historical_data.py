"""Read historical observations without changing their reporting semantics.

Dates are returned as pandas timestamps. Missing values and irregular observation
dates are preserved; converting to Covasim columns requires an explicit mapping.
"""

import gzip
import hashlib
import io
import json
from pathlib import Path, PureWindowsPath
import re

import pandas as pd


SCHEMA_VERSION = "historical-epidemics-v1"
OBSERVATION_COLUMNS = (
    "dataset_id", "entity_id", "population_group", "observation_scope",
    "date_start", "date_end", "time_basis", "frequency", "metric", "value",
    "unit", "quality", "source_id", "source_url", "source_locator",
)
DEFAULT_DATA_ROOT = Path(__file__).resolve().parents[1] / "research" / "historical_epidemics" / "data"


def _dataset_id(value):
    if not isinstance(value, str) or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]*", value):
        raise ValueError("dataset_id must contain only letters, numbers, dots, underscores or hyphens")
    return value


def _text(value, field):
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field} must be nonempty text")
    return value


def _inside_root(root, relative_path):
    _text(relative_path, "observations_file")
    path = Path(relative_path)
    # Windows drive paths must also be rejected when checks run on another OS.
    windows_path = PureWindowsPath(relative_path)
    if path.is_absolute() or windows_path.drive or windows_path.root:
        raise ValueError("Data file paths must be relative to data_root")
    resolved = (root / path).resolve()
    if not resolved.is_relative_to(root):
        raise ValueError("Data file path escapes data_root")
    return resolved


def _catalog(data_root):
    root = Path(data_root if data_root is not None else DEFAULT_DATA_ROOT).resolve()
    path = _inside_root(root, "catalog.json")
    try:
        catalog = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ValueError(f"Invalid catalog JSON: {exc}") from exc
    if not isinstance(catalog, dict) or catalog.get("schema_version") != SCHEMA_VERSION:
        raise ValueError(f"catalog.schema_version must be {SCHEMA_VERSION!r}")
    datasets = catalog.get("datasets")
    if not isinstance(datasets, list):
        raise ValueError("catalog.datasets must be a list")
    seen = set()
    for dataset in datasets:
        if not isinstance(dataset, dict):
            raise ValueError("Each catalog dataset must be an object")
        dataset_id = _dataset_id(dataset.get("id"))
        if dataset_id in seen:
            raise ValueError(f"Duplicate dataset_id in catalog: {dataset_id}")
        seen.add(dataset_id)
        _text(dataset.get("title"), "title")
        _inside_root(root, dataset.get("observations_file"))
        digest = dataset.get("sha256")
        if not isinstance(digest, str) or not re.fullmatch(r"[0-9a-fA-F]{64}", digest):
            raise ValueError(f"Invalid sha256 for dataset {dataset_id}")
    return root, datasets


def list_datasets(data_root=None) -> list[dict]:
    """Return validated catalog entries without loading observation files."""
    return _catalog(data_root)[1]


def load_observations(
    dataset_id, *, entity_id=None, population_group=None, observation_scope=None,
    data_root=None, verify_hash=True,
) -> pd.DataFrame:
    """Load a validated CSV or CSV.GZ, optionally selecting one population and scope.

    Unknown datasets raise KeyError; malformed metadata, tables and hash mismatches
    raise ValueError. Empty numeric cells remain missing rather than becoming zero.
    """
    _dataset_id(dataset_id)
    root, datasets = _catalog(data_root)
    dataset = next((item for item in datasets if item["id"] == dataset_id), None)
    if dataset is None:
        raise KeyError(f"Unknown dataset_id: {dataset_id}")
    path = _inside_root(root, dataset["observations_file"])
    raw = path.read_bytes()
    if verify_hash and hashlib.sha256(raw).hexdigest() != dataset["sha256"].lower():
        raise ValueError(f"sha256 mismatch for dataset {dataset_id}")
    content = gzip.decompress(raw) if path.suffix.lower() == ".gz" else raw
    frame = pd.read_csv(io.BytesIO(content), dtype=str, keep_default_na=False)
    missing = set(OBSERVATION_COLUMNS).difference(frame.columns)
    if missing:
        raise ValueError(f"Missing observation columns: {', '.join(sorted(missing))}")
    if not frame["dataset_id"].eq(dataset_id).all():
        raise ValueError("Observation dataset_id does not match the catalog entry")
    for field in ("entity_id", "population_group", "observation_scope", "metric"):
        if frame[field].str.strip().eq("").any():
            raise ValueError(f"Observation {field} must be nonempty")
    for field in ("date_start", "date_end"):
        if not frame[field].str.fullmatch(r"\d{4}-\d{2}-\d{2}").all():
            raise ValueError(f"{field} must contain ISO dates (YYYY-MM-DD)")
        try:
            frame[field] = pd.to_datetime(frame[field], format="%Y-%m-%d", errors="raise")
        except ValueError as exc:
            raise ValueError(f"Invalid {field}: {exc}") from exc
    if frame["date_start"].gt(frame["date_end"]).any():
        raise ValueError("date_start must not be later than date_end")
    try:
        frame["value"] = pd.to_numeric(frame["value"].str.strip().replace("", float("nan")), errors="raise")
    except ValueError as exc:
        raise ValueError(f"Observation value must be numeric or empty: {exc}") from exc
    if frame["value"].isin([float("inf"), -float("inf")]).any():
        raise ValueError("Observation value must be finite or missing")
    for field, selected in (
        ("entity_id", entity_id), ("population_group", population_group),
        ("observation_scope", observation_scope),
    ):
        if selected is not None:
            _text(selected, field)
            frame = frame.loc[frame[field].eq(selected)]
    return frame.reset_index(drop=True)


def to_covasim_data(
    dataset_id, *, entity_id, population_group, observation_scope, metric_map: dict,
    data_root=None,
) -> pd.DataFrame:
    """Map explicitly selected point observations into a Covasim-style wide table.

    The returned table has a date column and DatetimeIndex. This does not infer
    diagnoses from tests, distribute weekly totals, fill gaps, difference cumulative
    values or reset their baseline. Unmapped metrics are left out of the result.
    """
    if not isinstance(metric_map, dict) or not metric_map:
        raise ValueError("metric_map must be a nonempty mapping of metrics to Covasim columns")
    for metric, target in metric_map.items():
        _text(metric, "metric_map metric")
        _text(target, "metric_map column")
        if target == "date":
            raise ValueError("metric_map cannot use the reserved date column")
    if len(set(metric_map.values())) != len(metric_map):
        raise ValueError("metric_map must map each metric to a distinct column")
    for field, selected in (
        ("entity_id", entity_id), ("population_group", population_group),
        ("observation_scope", observation_scope),
    ):
        _text(selected, field)
    frame = load_observations(
        dataset_id, entity_id=entity_id, population_group=population_group,
        observation_scope=observation_scope, data_root=data_root,
    )
    unavailable = set(metric_map).difference(frame["metric"])
    if unavailable:
        raise ValueError(f"Mapped metrics are absent from the selected observations: {', '.join(sorted(unavailable))}")
    frame = frame.loc[frame["metric"].isin(metric_map)]
    if frame["quality"].str.contains("source_date_review_required", regex=False).any():
        raise ValueError("Source dates require review before calendar alignment; inspect the long table and raw source")
    if not frame["date_start"].eq(frame["date_end"]).all():
        raise ValueError("Covasim conversion requires point observations; date intervals are not supported")
    if frame.duplicated(["date_start", "metric"]).any():
        raise ValueError("Duplicate observations for the same date and metric")
    wide = frame.pivot(index="date_start", columns="metric", values="value")
    wide = wide.rename(columns=metric_map).reindex(columns=list(metric_map.values())).sort_index()
    wide.index.name = "date"
    wide.columns.name = None
    wide.insert(0, "date", wide.index)
    return wide
