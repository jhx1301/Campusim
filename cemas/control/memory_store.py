"""Private source construction and separately published read-only public cases."""
from __future__ import annotations

from collections import Counter
from collections.abc import Mapping
from dataclasses import asdict, dataclass, replace
import errno
import hashlib
import json
import os
from pathlib import Path
import shutil
import sqlite3
from uuid import uuid4

from .memory_types import (CASE_SCHEMA_VERSION, LocalCaseRevision, PublicCase,
    canonical_json, public_case_from_dict, public_hash, public_to_dict)

STORE_SCHEMA_VERSION = "cemas-public-case-store-v1"
DATABASE_FILENAME = "observable_source_memory_v1.sqlite"
SOURCE_POLICIES = ("minimum", "maximum_feasible", "uniform_legal_independent_rng", "tuned_threshold")
_PURPOSES = ("fixture", "development", "evaluation_ready")
_TABLE_COLUMNS = {
    "case_revisions": ("case_id", "revision", "payload_json", "public_content_sha256"),
    "active_revision": ("case_id", "revision"),
    "case_group": ("case_id", "opaque_group"), "metadata": ("key", "value")}


class CaseStoreError(RuntimeError):
    """Fatal source, schema, provenance, or integrity failure."""


class CaseStoreUnavailable(OSError):
    """A classified temporary read error, safe to retry next week."""


def _sha(value, name):
    if type(value) is not str or len(value) != 64 or any(c not in "0123456789abcdef" for c in value):
        raise CaseStoreError(f"{name} must be a lowercase SHA-256")
    return value


def _file_sha(path):
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _temporary_read_error(exc):
    if isinstance(exc, OSError):
        return exc.errno in (errno.EAGAIN, errno.EINTR, errno.EBUSY, errno.ETIMEDOUT, getattr(errno, "ESTALE", -1))
    if isinstance(exc, sqlite3.OperationalError):
        return getattr(exc, "sqlite_errorcode", None) in (
            sqlite3.SQLITE_BUSY, sqlite3.SQLITE_LOCKED, getattr(sqlite3, "SQLITE_IOERR_READ", 266))
    return False


def public_content_sha256(case):
    """Semantic identity excludes IDs, grouping, and generated prose."""
    payload = public_to_dict(case)
    for key in ("case_id", "revision", "description", "public_source"):
        payload.pop(key, None)
    return public_hash(payload)


def public_case(local, case_id, task_hash):
    """Convert one accepted public transition; shared by source and learning stores."""
    return PublicCase(case_id=case_id, revision=local.revision, schema_version=CASE_SCHEMA_VERSION,
        public_task_sha256=task_hash, pre_observation=local.pre_observation,
        executed_week=local.executed_week, window_days=local.window_days,
        status=local.status, available_through_day=local.available_through_day,
        attribution="descriptive_not_causal",
        flags=local.flags, description=local.description, public_source={"kind": "source_simulation",
            "observation_sha256": public_hash(local.pre_observation),
            "week_sha256": public_hash(local.executed_week)})


@dataclass(frozen=True, slots=True)
class StoreManifest:
    schema_version: str
    purpose: str
    storage_state: str
    public_task_sha256: str
    database_sha256: str
    case_count: int
    revision_count: int
    active_revisions: tuple[tuple[int, int], ...]
    database_filename: str = DATABASE_FILENAME

    def __post_init__(self):
        if self.schema_version != STORE_SCHEMA_VERSION or self.purpose not in _PURPOSES or self.storage_state != "immutable":
            raise CaseStoreError("unsupported store manifest identity")
        _sha(self.public_task_sha256, "public_task_sha256")
        _sha(self.database_sha256, "database_sha256")
        if (type(self.case_count) is not int or self.case_count < 0 or type(self.revision_count) is not int
                or self.revision_count < self.case_count):
            raise CaseStoreError("invalid manifest counts")
        revisions = tuple(tuple(pair) for pair in self.active_revisions)
        if (any(len(p) != 2 or any(type(v) is not int or v <= 0 for v in p) for p in revisions)
                or tuple(sorted(revisions)) != revisions or len({p[0] for p in revisions}) != len(revisions)
                or len(revisions) != self.case_count):
            raise CaseStoreError("invalid active revision identities")
        if Path(self.database_filename).name != self.database_filename or not self.database_filename:
            raise CaseStoreError("manifest database filename must be a simple name")
        object.__setattr__(self, "active_revisions", revisions)

    def to_dict(self):
        return public_to_dict(asdict(self))


@dataclass(frozen=True, slots=True)
class CollectionReport:
    trajectory_count: int
    completed_trajectory_count: int
    case_count: int
    revision_count: int
    private_manifest_path: str


def load_store_manifest(value):
    if isinstance(value, StoreManifest):
        return value
    if isinstance(value, (str, Path)):
        try:
            value = json.loads(Path(value).read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            raise CaseStoreError("store manifest cannot be read") from exc
    if not isinstance(value, Mapping):
        raise CaseStoreError("verified store manifest is required")
    try:
        return StoreManifest(**dict(value))
    except (TypeError, ValueError) as exc:
        raise CaseStoreError("invalid store manifest fields") from exc


def _world(seed):
    from .protocol import load_protocol, source_grid
    protocol = load_protocol(Path(__file__).resolve().parents[2] / "docs/control_protocol_v1.json")
    return source_grid(protocol, "memory_collection", seed)


def _compatibility(value, required):
    if not isinstance(value, Mapping):
        raise CaseStoreError("source compatibility must be a mapping")
    result = dict(value)
    if required:
        for key in ("source_code_sha256", "calibration_artifact_sha256", "objective_sha256"):
            _sha(result.get(key), key)
        if type(result.get("execution_days")) is not int or result["execution_days"] <= 0:
            raise CaseStoreError("source execution_days must be positive")
    return json.loads(canonical_json(result))


def _registration(value, purpose, compatibility):
    if not isinstance(value, Mapping):
        raise CaseStoreError("private source registration must be a mapping")
    result = json.loads(canonical_json(dict(value)))
    if type(result.get("trajectory_id")) is not str or not result["trajectory_id"].strip():
        raise CaseStoreError("private trajectory_id is required")
    if result.get("purpose", purpose) != purpose:
        raise CaseStoreError("source purpose mismatch")
    result["purpose"] = purpose
    if purpose != "fixture":
        if result.get("source_kind") != "source_simulation" or result.get("split") != "source":
            raise CaseStoreError("only audited source simulations may enter a source store")
        seed = result.get("seed")
        if type(seed) is not int or not 30001 <= seed <= 30027:
            raise CaseStoreError("source seed outside memory collection pool")
        if result.get("policy") not in SOURCE_POLICIES or result.get("world") != _world(seed):
            raise CaseStoreError("unsupported policy or incorrect source world mapping")
        if result["policy"] == "tuned_threshold":
            _sha(result.get("baseline_artifact_sha256"), "baseline_artifact_sha256")
        if _compatibility(result.get("compatibility", {}), True) != compatibility:
            raise CaseStoreError("source compatibility mismatch")
    return result

class PublicCaseBuilder:
    """Append public revisions and export private provenance as a JSON manifest."""

    def __init__(self, staging_dir, public_task_sha256, *, purpose="fixture", compatibility=None):
        if purpose not in _PURPOSES:
            raise CaseStoreError("unsupported collection purpose")
        self.staging_dir = Path(staging_dir).resolve()
        self.public_task_sha256 = _sha(public_task_sha256, "public_task_sha256")
        self.purpose = purpose
        self.compatibility = _compatibility(compatibility or {}, purpose != "fixture")
        self.staging_dir.mkdir(parents=True, exist_ok=True)
        self.path = self.staging_dir / DATABASE_FILENAME
        self.private_path = self.staging_dir / "private_manifest.json"
        if any(path.exists() for path in (self.path, self.private_path)):
            raise CaseStoreError("staging output already exists; use a new directory")
        self._public = sqlite3.connect(self.path)
        self._closed = self._finalized = False
        self._trajectories = {}
        self._public.executescript("""
            PRAGMA foreign_keys=ON;
            CREATE TABLE case_revisions(case_id INTEGER NOT NULL,revision INTEGER NOT NULL,
                payload_json TEXT NOT NULL,public_content_sha256 TEXT NOT NULL,PRIMARY KEY(case_id,revision));
            CREATE TABLE active_revision(case_id INTEGER PRIMARY KEY,revision INTEGER NOT NULL,
                FOREIGN KEY(case_id,revision) REFERENCES case_revisions(case_id,revision));
            CREATE TABLE case_group(case_id INTEGER PRIMARY KEY,opaque_group TEXT NOT NULL);
            CREATE TABLE metadata(key TEXT PRIMARY KEY,value TEXT NOT NULL);
        """)
        self._public.executemany("INSERT INTO metadata VALUES(?,?)", (
            ("schema_version", STORE_SCHEMA_VERSION), ("case_schema_version", CASE_SCHEMA_VERSION),
            ("public_task_sha256", self.public_task_sha256)))
        self._public.commit()

    def append(self, local_revisions, private_source_registration):
        if self._closed or self._finalized:
            raise CaseStoreError("collection is closed or finalized")
        revisions = tuple(local_revisions)
        if any(type(item) is not LocalCaseRevision for item in revisions):
            raise TypeError("append accepts only LocalCaseRevision values")
        registration = _registration(private_source_registration, self.purpose, self.compatibility)
        trajectory = registration["trajectory_id"]
        encoded, ids = canonical_json(registration), []
        existing = self._trajectories.get(trajectory)
        if existing is not None:
            previous, group, known_ids = existing
            if previous != encoded:
                raise CaseStoreError("trajectory registration changed")
            local_ids = dict(known_ids)
        else:
            group, local_ids = uuid4().hex, {}
        try:
            self._public.execute("BEGIN IMMEDIATE")
            next_id = self._public.execute("SELECT COALESCE(MAX(case_id),0)+1 FROM case_revisions").fetchone()[0]
            for local in revisions:
                case_id = local_ids.get(local.local_id)
                if case_id is None:
                    if local.revision != 1:
                        raise CaseStoreError("new local case must begin at revision one")
                    case_id, next_id = next_id, next_id + 1
                    local_ids[local.local_id] = case_id
                case = public_case(local, case_id, self.public_task_sha256)
                if self.purpose != "fixture" and case.pre_observation.execution_days != self.compatibility["execution_days"]:
                    raise CaseStoreError("case horizon mismatches source compatibility")
                payload = canonical_json(public_to_dict(case))
                old = self._public.execute("SELECT payload_json FROM case_revisions WHERE case_id=? AND revision=?", (case_id, local.revision)).fetchone()
                if old:
                    if old[0] != payload:
                        raise CaseStoreError("same revision has different public content")
                    ids.append(case_id)
                    continue
                active = self._public.execute("SELECT revision FROM active_revision WHERE case_id=?", (case_id,)).fetchone()
                if local.revision != (active[0]+1 if active else 1):
                    raise CaseStoreError("case revisions must be consecutive and append-only")
                if active:
                    prior = public_case_from_dict(json.loads(self._public.execute("SELECT payload_json FROM case_revisions WHERE case_id=? AND revision=?", (case_id,active[0])).fetchone()[0]))
                    if (prior.pre_observation != case.pre_observation
                            or (prior.executed_week.start_day, prior.executed_week.end_day)
                               != (case.executed_week.start_day, case.executed_week.end_day)):
                        raise CaseStoreError("revision cannot change its decision or execution window")
                self._public.execute("INSERT INTO case_revisions VALUES(?,?,?,?)", (case_id,local.revision,payload,public_content_sha256(case)))
                self._public.execute("INSERT OR REPLACE INTO active_revision VALUES(?,?)", (case_id,local.revision))
                self._public.execute("INSERT OR IGNORE INTO case_group VALUES(?,?)", (case_id,group))
                ids.append(case_id)
            self._public.commit()
        except Exception:
            self._public.rollback()
            raise
        # Publish the private ID mapping only after the public transaction commits.
        self._trajectories[trajectory] = (encoded, group, local_ids)
        return tuple(ids)

    def finalize(self, source_run_status):
        if self._closed or self._finalized:
            raise CaseStoreError("collection is closed or finalized")
        trajectories = sorted(self._trajectories.items())
        statuses = ({trajectory:source_run_status for trajectory,_ in trajectories} if isinstance(source_run_status,str)
                    else dict(source_run_status) if isinstance(source_run_status,Mapping) else {})
        if set(statuses) != set(self._trajectories) or any(v not in ("completed","failed","cancelled") for v in statuses.values()):
            raise CaseStoreError("statuses must identify every trajectory exactly")
        entries = []
        for trajectory, (encoded, group, local_ids) in trajectories:
            entry = json.loads(encoded)
            entry.update(status=statuses[trajectory],opaque_group=group,
                         case_ids=sorted(local_ids.values()))
            entries.append(entry)
        cases = self._public.execute("SELECT COUNT(*) FROM active_revision").fetchone()[0]
        revisions = self._public.execute("SELECT COUNT(*) FROM case_revisions").fetchone()[0]
        manifest = {"schema_version":STORE_SCHEMA_VERSION,"purpose":self.purpose,
            "public_task_sha256":self.public_task_sha256,"compatibility":self.compatibility,
            "trajectories":entries,"case_count":cases,"revision_count":revisions}
        path = self.private_path
        with path.open("x",encoding="utf-8",newline="\n") as stream:
            stream.write(canonical_json(manifest)+"\n")
        self._finalized = True
        self.close()
        return CollectionReport(len(entries),sum(e["status"]=="completed" for e in entries),cases,revisions,str(path))

    def close(self):
        if not self._closed:
            self._public.execute("PRAGMA wal_checkpoint(TRUNCATE)")
            self._public.close()
            self._closed = True

    def __enter__(self):
        return self

    def __exit__(self,*_args):
        self.close()

def _private_manifest(value):
    if isinstance(value,(str,Path)):
        try:
            value = json.loads(Path(value).read_text(encoding="utf-8"))
        except (OSError,ValueError) as exc:
            raise CaseStoreError("private build manifest cannot be read") from exc
    if not isinstance(value,Mapping):
        raise CaseStoreError("private build manifest is required")
    return json.loads(canonical_json(dict(value)))


def verify_source_manifest(value, expected_compatibility=None, *, purpose=None, compatibility=None):
    """Private runner gate, independent of the public runtime reader."""
    manifest = _private_manifest(value)
    if "database_sha256" in manifest:
        expected_database_hash = _sha(manifest["database_sha256"], "database_sha256")
        if isinstance(value, (str, Path)):
            database = Path(value).resolve().parent / DATABASE_FILENAME
            try:
                if _file_sha(database) != expected_database_hash:
                    raise CaseStoreError("private source manifest database hash mismatch")
            except OSError as exc:
                raise CaseStoreError("private source manifest database missing or unreadable") from exc
    actual = manifest.get("purpose")
    if manifest.get("schema_version") != STORE_SCHEMA_VERSION or actual not in _PURPOSES or purpose is not None and actual != purpose:
        raise CaseStoreError("private source purpose/version mismatch")
    _sha(manifest.get("public_task_sha256"),"public_task_sha256")
    compat = _compatibility(manifest.get("compatibility",{}),actual!="fixture")
    expected = expected_compatibility if expected_compatibility is not None else compatibility
    if expected is not None and compat != _compatibility(expected,actual!="fixture"):
        raise CaseStoreError("source compatibility does not match current runner")
    trajectories = manifest.get("trajectories")
    if type(trajectories) is not list or not trajectories:
        raise CaseStoreError("source manifest has no trajectories")
    seen, identities, groups, case_ids = set(),set(),set(),set()
    for entry in trajectories:
        if not isinstance(entry,dict):
            raise CaseStoreError("invalid source trajectory entry")
        source_purpose = "development" if actual == "evaluation_ready" and "promotion" in manifest else actual
        registration = _registration({k:v for k,v in entry.items() if k not in ("status","opaque_group","case_ids")},source_purpose,compat)
        identity = registration["trajectory_id"]
        if identity in seen or entry.get("status") != "completed":
            raise CaseStoreError("source trajectories must be unique and completed")
        seen.add(identity)
        group = entry.get("opaque_group")
        if type(group) is not str or len(group)!=32 or any(c not in "0123456789abcdef" for c in group) or group in groups:
            raise CaseStoreError("invalid or duplicated opaque trajectory group")
        groups.add(group)
        ids = entry.get("case_ids")
        if (type(ids) is not list or not ids or any(type(i) is not int or i<=0 or i in case_ids for i in ids)
                or len(set(ids)) != len(ids)):
            raise CaseStoreError("trajectory case identities must be nonempty and unique")
        case_ids.update(ids)
        if actual != "fixture":
            pair = (registration["seed"],registration["policy"])
            if pair in identities:
                raise CaseStoreError("duplicated source world/policy trajectory")
            identities.add(pair)
    if manifest.get("case_count") != len(case_ids):
        raise CaseStoreError("source manifest case coverage mismatch")
    if actual == "evaluation_ready":
        required = {(s,p) for s in range(30001,30028) for p in SOURCE_POLICIES}
        if identities != required or len(trajectories)!=108:
            raise CaseStoreError("evaluation_ready requires exactly all 108 world/policy trajectories")
        _verify_promotion(value, manifest)
    return manifest


def coverage_report(staging_or_manifest):
    value = staging_or_manifest
    if isinstance(value, (str, Path)) and Path(value).is_dir():
        directory = Path(value)
        value = directory / ("private_manifest.json" if (directory / "private_manifest.json").exists() else "build_manifest.json")
    manifest = _private_manifest(value)
    entries = manifest.get("trajectories",[])
    observed = {(item.get("seed"),item.get("policy")) for item in entries}
    required = {(s,p) for s in range(30001,30028) for p in SOURCE_POLICIES}
    report = {"purpose":manifest.get("purpose"),"trajectory_count":len(entries),
        "completed_trajectory_count":sum(e.get("status")=="completed" for e in entries),
        "case_count":manifest.get("case_count",0),"revision_count":manifest.get("revision_count",0),
        "policies":sorted({e["policy"] for e in entries if "policy" in e}),
        "policy_trajectory_counts":dict(sorted(Counter(e["policy"] for e in entries if "policy" in e).items())),
        "world_count":len({e["seed"] for e in entries if "seed" in e}),
        "missing_world_policy_identities":[[s,p] for s,p in sorted(required-observed)],
        "exact_108_identity_coverage":observed==required and len(entries)==108}
    cells = Counter((e.get("world", {}).get("beta_scale"), e.get("world", {}).get("screening_capacity_ratio"))
                    for e in entries if isinstance(e.get("world"), dict))
    expected_cells = {tuple(_world(seed)[key] for key in ("beta_scale", "screening_capacity_ratio"))
                      for seed in range(30001, 30028)}
    report["world_cells"] = [{"beta_scale": beta, "screening_capacity_ratio": cap, "trajectories": cells[(beta, cap)]}
                             for beta, cap in sorted(expected_cells)]
    report["missing_world_cells"] = [list(cell) for cell in sorted(expected_cells - cells.keys())]
    if not isinstance(value, (str, Path)):
        report["public_case_coverage"] = {"status": "unavailable", "reason": "database_path_required"}
        return report
    database = Path(value).resolve().parent / DATABASE_FILENAME
    with sqlite3.connect(database.as_uri() + "?mode=ro", uri=True) as connection:
        rows = connection.execute("SELECT c.payload_json FROM case_revisions c JOIN active_revision a "
                                  "ON c.case_id=a.case_id AND c.revision=a.revision ORDER BY c.case_id")
        cases = tuple(public_case_from_dict(json.loads(row[0])) for row in rows)
    report["public_case_coverage"] = _public_case_coverage(cases)
    return report


def _public_case_coverage(cases):
    from .actions import ACTION_TABLE
    from .types import ACTION_ORDER, ACTION_SIZES
    levels = {name: Counter() for name in ACTION_ORDER}
    durations = {name: Counter() for name in ACTION_ORDER}
    joint, transitions, histories, capacities = Counter(), Counter(), Counter(), {}
    changes = Counter()
    values = {name: [] for name in ("diagnoses", "growth", "diagnosis_test_proxy", "tests", "notifications",
                                  "union_person_days", "activity_person_days")}
    for case in cases:
        pre, week = case.pre_observation, case.executed_week
        action = week.executed_action.values
        for index, name in enumerate(ACTION_ORDER):
            levels[name][action[index]] += 1
            durations[name][pre.action_duration_days[index]] += 1
        joint[",".join(map(str, action))] += 1
        transitions[",".join(map(str, pre.current_action.values)) + "->" + ",".join(map(str, action))] += 1
        histories[sum(pre.week_valid)] += 1
        capacity = pre.resources.screening_daily_capacity / pre.population.population
        bucket = capacities.setdefault(capacity, {"available": set(), "executed": Counter()})
        bucket["available"].update(a.values[1] for a, legal in zip(ACTION_TABLE, pre.legal_action_mask) if legal)
        bucket["executed"][action[1]] += 1
        changes["capacity_changed"] += int("capacity_changed" in case.flags)
        changes["testing_changed"] += int("testing_changed" in case.flags)
        changes["growth_valid"] += int(week.growth_valid)
        changes["proxy_valid"] += int(week.proxy_valid)
        values["diagnoses"].append(week.delivered_diagnoses)
        if week.growth_valid:
            values["growth"].append(week.growth)
        if week.proxy_valid:
            values["diagnosis_test_proxy"].append(week.diagnosis_test_proxy)
        cost = week.cost
        values["tests"].append(cost.clinical_tests + cost.screening_tests)
        values["notifications"].append(cost.delivered_notifications)
        values["union_person_days"].append(cost.union_person_days)
        values["activity_person_days"].append(cost.school_restriction_person_days + cost.work_restriction_person_days
                                              + cost.community_restriction_person_days)
    missing = {name: sorted(set(range(size)) - levels[name].keys()) for name, size in zip(ACTION_ORDER, ACTION_SIZES)}
    screening = [{"capacity_ratio": cap, "available_levels": sorted(data["available"]),
                  "executed_counts": dict(sorted(data["executed"].items())),
                  "missing_levels": sorted(data["available"] - data["executed"].keys())}
                 for cap, data in sorted(capacities.items())]
    return {"status": "available", "case_count": len(cases), "independent_worlds": False,
            "dimension_level_counts": {name: dict(sorted(counts.items())) for name, counts in levels.items()},
            "missing_dimension_levels": missing, "screening_by_capacity": screening,
            "action_coverage_complete": not any(missing.values()) and all(not row["missing_levels"] for row in screening),
            "joint_action_counts": dict(sorted(joint.items())), "action_transition_counts": dict(sorted(transitions.items())),
            "history_length_counts": dict(sorted(histories.items())),
            "action_duration_days_counts": {name: dict(sorted(counts.items())) for name, counts in durations.items()},
            "measurement_changes": dict(sorted(changes.items())),
            "outcomes_and_burdens": {name: {"count": len(items), "min": min(items) if items else None,
                                            "max": max(items) if items else None} for name, items in values.items()}}


def _verify_promotion(value, manifest):
    promotion = manifest.get("promotion")
    if not isinstance(promotion, dict) or not isinstance(value, (str, Path)):
        raise CaseStoreError("evaluation_ready requires verified Phase 6 promotion evidence")
    if (set(promotion) != {"development_dir", "development_manifest_sha256", "phase6_release_path", "phase6_release_sha256"}
            or any(type(promotion.get(key)) is not str or not promotion[key]
                   for key in ("development_dir", "phase6_release_path"))):
        raise CaseStoreError("invalid Phase 6 promotion evidence fields")
    from .artifacts import validate_phase6_release
    original = Path(promotion["development_dir"]) / "build_manifest.json"
    release = Path(promotion["phase6_release_path"])
    try:
        if (_file_sha(original) != _sha(promotion.get("development_manifest_sha256"), "development_manifest_sha256")
                or _file_sha(release) != _sha(promotion.get("phase6_release_sha256"), "phase6_release_sha256")):
            raise CaseStoreError("Phase 6 promotion evidence hash mismatch")
    except OSError as exc:
        raise CaseStoreError("Phase 6 promotion evidence missing or unreadable") from exc
    source = verify_source_manifest(original, manifest["compatibility"], purpose="development")
    expected = {**source, "purpose": "evaluation_ready", "promotion": promotion}
    if manifest != expected:
        raise CaseStoreError("promotion changed original source provenance or public data identity")
    validate_phase6_release(release, development_dir=original.parent)


def promote_public_store(development_dir, release_path, output_dir):
    """Publish verified development data with unchanged cases and source purposes."""
    from .artifacts import validate_phase6_release
    source, release = Path(development_dir).resolve(), Path(release_path).resolve()
    private_path = source / "build_manifest.json"
    manifest = verify_source_manifest(private_path, purpose="development")
    coverage = coverage_report(private_path)
    if not coverage["exact_108_identity_coverage"]:
        raise CaseStoreError("evaluation_ready requires exactly all 108 world/policy trajectories")
    validate_phase6_release(release, development_dir=source)
    frozen = load_store_manifest(source / "store_manifest.json")
    if frozen.purpose != "development" or frozen.database_sha256 != manifest["database_sha256"]:
        raise CaseStoreError("promotion requires the verified development publication")
    # Reuse the existing complete-trajectory and immutable-copy verification.
    result = freeze_public_store(source, private_path, output_dir, purpose="development")
    output = Path(output_dir).resolve()
    shutil.copyfile(private_path, output / "development_build_manifest.json")
    shutil.copyfile(release, output / "phase6_release.json")
    manifest.update(purpose="evaluation_ready", promotion={"development_dir": str(source),
        "development_manifest_sha256": _file_sha(private_path), "phase6_release_path": str(release),
        "phase6_release_sha256": _file_sha(release)})
    result = replace(result, purpose="evaluation_ready")
    for name, content in (("store_manifest.json", result.to_dict()), ("build_manifest.json", manifest)):
        (output / name).write_text(canonical_json(content) + "\n", encoding="utf-8")
    verify_source_manifest(output / "build_manifest.json", purpose="evaluation_ready")
    publication = {"purpose": "evaluation_ready", "database_sha256": result.database_sha256,
                   "build_manifest_sha256": _file_sha(output / "build_manifest.json"),
                   "phase6_release_sha256": manifest["promotion"]["phase6_release_sha256"]}
    (output / "publication_result.json").write_text(canonical_json(publication) + "\n", encoding="utf-8")
    return result


def freeze_public_store(staging, private_manifest, output_dir, purpose=None):
    """Copy a closed staging file into a fresh publication directory."""
    staging, output = Path(staging),Path(output_dir).resolve()
    source = (staging/DATABASE_FILENAME if staging.is_dir() else staging).resolve()
    if source.parent==output or source==output or output.exists():
        raise CaseStoreError("freeze output must be a new directory distinct from staging")
    manifest = verify_source_manifest(private_manifest,purpose=purpose)
    if not source.is_file() or any(Path(str(source)+suffix).exists() for suffix in ("-wal","-journal")):
        raise CaseStoreError("staging database must be closed and checkpointed before freeze")
    connection = sqlite3.connect(source,timeout=0)
    try:
        connection.execute("BEGIN EXCLUSIVE")
        if connection.execute("PRAGMA integrity_check").fetchone() != ("ok",):
            raise CaseStoreError("staging database integrity check failed")
        active = tuple(connection.execute("SELECT case_id,revision FROM active_revision ORDER BY case_id"))
        count = connection.execute("SELECT COUNT(*) FROM case_revisions").fetchone()[0]
        metadata = dict(connection.execute("SELECT key,value FROM metadata"))
        if (metadata != {"schema_version":STORE_SCHEMA_VERSION,"case_schema_version":CASE_SCHEMA_VERSION,
                         "public_task_sha256":manifest["public_task_sha256"]}
                or len(active)!=manifest.get("case_count") or count!=manifest.get("revision_count")):
            raise CaseStoreError("staging database mismatches private build manifest")
        expected_groups = {case_id:e["opaque_group"] for e in manifest["trajectories"] for case_id in e["case_ids"]}
        if dict(connection.execute("SELECT case_id,opaque_group FROM case_group")) != expected_groups:
            raise CaseStoreError("public grouping mismatches source registration")
        connection.rollback()
        connection.execute("PRAGMA wal_checkpoint(TRUNCATE)")
    except sqlite3.DatabaseError as exc:
        raise CaseStoreError("staging database cannot be frozen") from exc
    finally:
        connection.close()
    source_hash = _file_sha(source)
    result = StoreManifest(STORE_SCHEMA_VERSION,manifest["purpose"],"immutable",manifest["public_task_sha256"],source_hash,len(active),count,active)
    with FrozenPublicCaseStore.open(source,result) as reader:
        cases = reader.cases()
        if manifest["purpose"] != "fixture":
            from .memory import PublicEpisodeMemory
            from .types import PublicWeekFeedback
            for entry in manifest["trajectories"]:
                trajectory = sorted((c for c in cases if c.case_id in entry["case_ids"]),
                                    key=lambda c:c.executed_week.start_day)
                windows = [case.executed_week for case in trajectory]
                horizon = manifest["compatibility"]["execution_days"]
                if not windows or windows[0].start_day!=0 or windows[-1].end_day!=horizon-1:
                    raise CaseStoreError("completed source trajectory must cover its entire horizon")
                memory,previous = PublicEpisodeMemory(),None
                try:
                    for index,case in enumerate(trajectory):
                        if case.pre_observation.execution_days != horizon:
                            raise ValueError("source case horizon mismatch")
                        memory.stage(case.pre_observation)
                        memory.accept(PublicWeekFeedback(case.executed_week,previous))
                        previous = case.executed_week
                except (TypeError,ValueError) as exc:
                    raise CaseStoreError("source trajectory has inconsistent public transitions") from exc
    output.mkdir(parents=True,exist_ok=False)
    destination = output/DATABASE_FILENAME
    with source.open("rb") as incoming,destination.open("xb") as outgoing:
        shutil.copyfileobj(incoming,outgoing)
        outgoing.flush()
        os.fsync(outgoing.fileno())
    if _file_sha(destination)!=source_hash or _file_sha(source)!=source_hash:
        raise CaseStoreError("database changed during publication; output is invalid")
    manifest["database_sha256"] = source_hash
    for name,value in (("store_manifest.json",result.to_dict()),("build_manifest.json",manifest)):
        with (output/name).open("x",encoding="utf-8",newline="\n") as stream:
            stream.write(canonical_json(value)+"\n")
    return result

class FrozenPublicCaseStore:
    """Immutable public rows and internal, meaningless trajectory groups."""

    def __init__(self):
        raise TypeError("use FrozenPublicCaseStore.open")

    @classmethod
    def open(cls,path,verified_manifest):
        manifest = load_store_manifest(verified_manifest)
        source = Path(path).resolve()
        if source.is_dir():
            source = source/manifest.database_filename
        instance = object.__new__(cls)
        instance.path,instance.manifest = source,manifest
        instance.purpose,instance.public_task_sha256 = manifest.purpose,manifest.public_task_sha256
        instance.store_sha256,instance._closed,instance._groups = manifest.database_sha256,False,{}
        instance.verify_integrity()
        try:
            instance._connection = sqlite3.connect(source.as_uri()+"?mode=ro",uri=True,timeout=0)
            instance._connection.execute("PRAGMA query_only=ON")
            instance._connection.execute("PRAGMA trusted_schema=OFF")
            tables = {r[0] for r in instance._connection.execute("SELECT name FROM sqlite_master WHERE type='table'")}
            if tables != set(_TABLE_COLUMNS):
                raise CaseStoreError("unexpected public database schema")
            for name,columns in _TABLE_COLUMNS.items():
                actual = tuple(r[1] for r in instance._connection.execute(f"PRAGMA table_info({name})"))
                if actual!=columns:
                    raise CaseStoreError("unexpected public database columns")
            if dict(instance._connection.execute("SELECT key,value FROM metadata")) != {
                    "schema_version":STORE_SCHEMA_VERSION,"case_schema_version":CASE_SCHEMA_VERSION,
                    "public_task_sha256":manifest.public_task_sha256}:
                raise CaseStoreError("public database metadata mismatch")
            if instance._connection.execute("PRAGMA integrity_check").fetchone() != ("ok",):
                raise CaseStoreError("public database integrity check failed")
            instance._groups = dict(instance._connection.execute("SELECT case_id,opaque_group FROM case_group"))
            if any(type(g) is not str or len(g)!=32 or any(c not in "0123456789abcdef" for c in g) for g in instance._groups.values()):
                raise CaseStoreError("malformed opaque trajectory grouping")
            instance.cases()
            denied = {sqlite3.SQLITE_ATTACH,sqlite3.SQLITE_DETACH,sqlite3.SQLITE_INSERT,
                sqlite3.SQLITE_UPDATE,sqlite3.SQLITE_DELETE,sqlite3.SQLITE_CREATE_TABLE,
                sqlite3.SQLITE_DROP_TABLE,sqlite3.SQLITE_ALTER_TABLE}
            instance._connection.set_authorizer(lambda action,_a,_b,_db,_trigger:
                sqlite3.SQLITE_DENY if action in denied else sqlite3.SQLITE_OK)
            return instance
        except Exception as exc:
            if hasattr(instance,"_connection"):
                instance._connection.close()
            if isinstance(exc,(CaseStoreError,CaseStoreUnavailable)):
                raise
            raise CaseStoreError("public database cannot be opened") from exc

    def verify_integrity(self):
        if self._closed:
            raise CaseStoreError("public store is closed")
        try:
            if _file_sha(self.path)!=self.manifest.database_sha256:
                raise CaseStoreError("immutable public database hash changed")
        except OSError as exc:
            if _temporary_read_error(exc):
                raise CaseStoreUnavailable("temporary public database read error") from exc
            raise CaseStoreError("immutable public database missing or unreadable") from exc

    def cases(self):
        self.verify_integrity()
        try:
            active = tuple(self._connection.execute("SELECT case_id,revision FROM active_revision ORDER BY case_id"))
            if active!=self.manifest.active_revisions or set(self._groups)!={r[0] for r in active}:
                raise CaseStoreError("active revision/group identities changed")
            rows = self._connection.execute("SELECT case_id,revision,payload_json,public_content_sha256 FROM case_revisions ORDER BY case_id,revision").fetchall()
            if len(rows)!=self.manifest.revision_count:
                raise CaseStoreError("revision count mismatch")
            latest,counts,result = {},{},{}
            for case_id,revision,payload,content_hash in rows:
                case = public_case_from_dict(json.loads(payload))
                if (case.case_id!=case_id or case.revision!=revision or case.public_task_sha256!=self.public_task_sha256
                        or case.schema_version!=CASE_SCHEMA_VERSION or public_content_sha256(case)!=content_hash):
                    raise CaseStoreError("public case identity/content mismatch")
                counts[case_id] = counts.get(case_id,0)+1
                if revision!=counts[case_id]:
                    raise CaseStoreError("public revisions must be consecutive")
                if case_id in result:
                    previous = result[case_id]
                    if (case.pre_observation != previous.pre_observation
                            or (case.executed_week.start_day, case.executed_week.end_day)
                               != (previous.executed_week.start_day, previous.executed_week.end_day)):
                        raise CaseStoreError("public revision changed its decision or execution window")
                latest[case_id],result[case_id] = revision,case
            if tuple(sorted(latest.items()))!=active:
                raise CaseStoreError("active revision must be the latest revision")
            return tuple(result[case_id] for case_id,_ in active)
        except (CaseStoreError,CaseStoreUnavailable):
            raise
        except Exception as exc:
            if _temporary_read_error(exc):
                raise CaseStoreUnavailable("temporary public database query error") from exc
            raise CaseStoreError("public database query/schema/content failure") from exc

    def group_for(self,case_id):
        try:
            return self._groups[case_id]
        except KeyError as exc:
            raise CaseStoreError("public case has no opaque grouping") from exc

    def close(self):
        if not self._closed:
            self._connection.close()
            self._closed = True

    def __enter__(self):
        return self

    def __exit__(self,*_args):
        self.close()
